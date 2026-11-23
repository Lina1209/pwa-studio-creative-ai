-- Administrative moderation queue, sanctions and user appeals for private messaging.
create table if not exists public.direct_user_moderation (
 user_id uuid primary key references auth.users(id) on delete cascade,
 status text not null check(status in ('muted','banned')),
 reason text not null check(char_length(reason) between 1 and 500),
 expires_at timestamptz, created_by uuid not null references auth.users(id),
 updated_at timestamptz not null default now()
);
create table if not exists public.direct_moderation_events (
 id uuid primary key default gen_random_uuid(),
 target_user_id uuid not null references auth.users(id) on delete cascade,
 actor_user_id uuid not null references auth.users(id),
 action text not null check(action in ('warn','mute','ban','unmute','unban')),
 reason text not null check(char_length(reason) between 1 and 500),
 expires_at timestamptz, created_at timestamptz not null default now()
);
create index if not exists direct_moderation_events_user_idx on public.direct_moderation_events(target_user_id,created_at desc);
create table if not exists public.direct_moderation_appeals (
 id uuid primary key default gen_random_uuid(),
 user_id uuid not null references auth.users(id) on delete cascade,
 reason text not null check(char_length(reason) between 10 and 2000),
 status text not null default 'pending' check(status in ('pending','accepted','rejected')),
 created_at timestamptz not null default now(), reviewed_at timestamptz,
 reviewed_by uuid references auth.users(id) on delete set null,
 decision_reason text check(decision_reason is null or char_length(decision_reason)<=500)
);
create unique index if not exists direct_moderation_one_pending_appeal on public.direct_moderation_appeals(user_id) where status='pending';
create index if not exists direct_moderation_appeals_queue_idx on public.direct_moderation_appeals(status,created_at desc);
alter table public.direct_user_moderation enable row level security;
alter table public.direct_moderation_events enable row level security;
alter table public.direct_moderation_appeals enable row level security;
revoke all on public.direct_user_moderation from public,anon,authenticated;
revoke all on public.direct_moderation_events from public,anon,authenticated;
revoke all on public.direct_moderation_appeals from public,anon,authenticated;
grant select,insert,update,delete on public.direct_user_moderation to service_role;
grant select,insert on public.direct_moderation_events to service_role;
grant select,insert,update on public.direct_moderation_appeals to service_role;

create or replace function public.apply_direct_user_moderation(p_target_user_id uuid,p_actor_user_id uuid,p_action text,p_reason text,p_expires_at timestamptz default null)
returns uuid language plpgsql security definer set search_path=''
as $$
declare v_id uuid;
begin
 if p_target_user_id is null or p_actor_user_id is null or p_target_user_id=p_actor_user_id
 or p_action not in ('warn','mute','ban','unmute','unban') or p_reason is null
 or char_length(btrim(p_reason)) not between 1 and 500
 or (p_expires_at is not null and p_expires_at<=now()) then
 raise exception 'invalid moderation action' using errcode='22023'; end if;
 if not exists(select 1 from auth.users u where u.id=p_target_user_id) then
 raise exception 'moderation target not found' using errcode='23503'; end if;
 if p_action in ('mute','ban') then
 insert into public.direct_user_moderation(user_id,status,reason,expires_at,created_by,updated_at)
 values(p_target_user_id,case when p_action='mute' then 'muted' else 'banned' end,btrim(p_reason),p_expires_at,p_actor_user_id,now())
 on conflict(user_id) do update set status=excluded.status,reason=excluded.reason,expires_at=excluded.expires_at,created_by=excluded.created_by,updated_at=now();
 elsif p_action in ('unmute','unban') then
 delete from public.direct_user_moderation where user_id=p_target_user_id;
 end if;
 insert into public.direct_moderation_events(target_user_id,actor_user_id,action,reason,expires_at)
 values(p_target_user_id,p_actor_user_id,p_action,btrim(p_reason),p_expires_at) returning id into v_id;
 return v_id;
end; $$;

create or replace function public.review_direct_message_report(p_report_id uuid,p_reviewer_user_id uuid,p_status text)
returns boolean language plpgsql security definer set search_path=''
as $$
begin
 if p_report_id is null or p_reviewer_user_id is null or p_status not in ('reviewing','resolved','dismissed') then
 raise exception 'invalid report review state' using errcode='22023'; end if;
 update public.direct_message_reports set status=p_status,
 reviewed_at=case when p_status in ('resolved','dismissed') then now() else null end,
 reviewed_by=case when p_status in ('resolved','dismissed') then p_reviewer_user_id else null end
 where id=p_report_id;
 return found;
end; $$;

create or replace function public.create_direct_moderation_appeal(p_user_id uuid,p_reason text)
returns uuid language plpgsql security definer set search_path=''
as $$
declare v_id uuid;
begin
 if p_user_id is null or p_reason is null or char_length(btrim(p_reason)) not between 10 and 2000 then
 raise exception 'invalid appeal' using errcode='22023'; end if;
 if not exists(select 1 from public.direct_user_moderation m where m.user_id=p_user_id and (m.expires_at is null or m.expires_at>now())) then
 raise exception 'no active moderation restriction to appeal' using errcode='22023'; end if;
 insert into public.direct_moderation_appeals(user_id,reason) values(p_user_id,btrim(p_reason)) returning id into v_id;
 return v_id;
end; $$;

create or replace function public.review_direct_moderation_appeal(p_appeal_id uuid,p_reviewer_user_id uuid,p_status text,p_decision_reason text)
returns boolean language plpgsql security definer set search_path=''
as $$
declare v_user_id uuid; v_restriction_status text;
begin
 if p_appeal_id is null or p_reviewer_user_id is null or p_status not in ('accepted','rejected')
 or p_decision_reason is null or char_length(btrim(p_decision_reason)) not between 1 and 500 then
 raise exception 'invalid appeal decision' using errcode='22023'; end if;
 update public.direct_moderation_appeals set status=p_status,reviewed_at=now(),reviewed_by=p_reviewer_user_id,decision_reason=btrim(p_decision_reason)
 where id=p_appeal_id and status='pending' returning user_id into v_user_id;
 if v_user_id is null then return false; end if;
 if p_status='accepted' then
   select status into v_restriction_status from public.direct_user_moderation where user_id=v_user_id;
   delete from public.direct_user_moderation where user_id=v_user_id;
   if v_restriction_status is not null then
     insert into public.direct_moderation_events(target_user_id,actor_user_id,action,reason)
     values(v_user_id,p_reviewer_user_id,case when v_restriction_status='muted' then 'unmute' else 'unban' end,btrim(p_decision_reason));
   end if;
 end if;
 return true;
end; $$;

create or replace function public.enforce_direct_message_safety()
returns trigger language plpgsql security definer set search_path=''
as $$
declare v_peer uuid; v_recent integer; v_status text;
begin
 select p.user_id into v_peer from public.direct_conversation_participants p
 where p.conversation_id=new.conversation_id and p.user_id<>new.sender_user_id limit 1;
 if v_peer is null then raise exception 'conversation recipient not found' using errcode='42501'; end if;
 if exists(select 1 from public.direct_user_blocks b where b.blocker_user_id=v_peer and b.blocked_user_id=new.sender_user_id) then
 raise exception 'recipient does not accept messages from this account' using errcode='42501'; end if;
 select m.status into v_status from public.direct_user_moderation m where m.user_id=new.sender_user_id and (m.expires_at is null or m.expires_at>now());
 if v_status is not null then raise exception 'account is restricted from sending private messages' using errcode='42501'; end if;
 perform pg_advisory_xact_lock(hashtextextended(new.sender_user_id::text||':'||new.conversation_id::text,0));
 select count(*) into v_recent from public.direct_messages m where m.sender_user_id=new.sender_user_id and m.conversation_id=new.conversation_id and m.created_at>now()-interval '1 minute';
 if v_recent>=20 then raise exception 'direct message rate limit exceeded' using errcode='P0001'; end if;
 return new;
end; $$;

alter table public.admin_audit_events drop constraint if exists admin_audit_events_action_check;
alter table public.admin_audit_events add constraint admin_audit_events_action_check check(action in (
'admin.access','admin.permission.denied','admin.user.view','admin.support.view','admin.support.reply','admin.support.status.changed',
'admin.tariff.change.requested','admin.tariff.change.approved','admin.finance.operation.requested','admin.finance.operation.approved',
'admin.finance.operation.executed','admin.finance.role.grant','admin.finance.role.revoke','admin.finance.request.create',
'admin.finance.request.decide','admin.finance.request.cancel','admin.pricing.draft.create','admin.plan.draft.create',
'admin.plan.draft.approve','admin.plan.assignment.create','admin.security.settings.changed',
'admin.direct_message.report.view','admin.direct_message.moderation.action','admin.direct_message.appeal.review'));
alter table public.admin_audit_events drop constraint if exists admin_audit_events_resource_type_check;
alter table public.admin_audit_events add constraint admin_audit_events_resource_type_check check(resource_type in (
'platform','user','support_ticket','tariff','payment','credit_wallet','credit_ledger','finance_request',
'pricing_catalog_draft','plan_catalog_draft','permission','security_setting','direct_message_report','direct_moderation_appeal'));

create or replace function public.record_admin_audit_event(p_actor_user_id uuid,p_action text,p_outcome text,p_resource_type text,p_resource_id uuid default null,p_correlation_id uuid default null,p_reason text default null)
returns uuid language plpgsql security definer set search_path=pg_catalog,public
as $$
declare v_id uuid;
begin
 if p_actor_user_id is null
 or p_action not in ('admin.access','admin.permission.denied','admin.user.view','admin.support.view','admin.support.reply','admin.support.status.changed',
 'admin.tariff.change.requested','admin.tariff.change.approved','admin.finance.operation.requested','admin.finance.operation.approved',
 'admin.finance.operation.executed','admin.finance.role.grant','admin.finance.role.revoke','admin.finance.request.create',
 'admin.finance.request.decide','admin.finance.request.cancel','admin.pricing.draft.create','admin.plan.draft.create',
 'admin.plan.draft.approve','admin.plan.assignment.create','admin.security.settings.changed',
 'admin.direct_message.report.view','admin.direct_message.moderation.action','admin.direct_message.appeal.review')
 or p_outcome not in ('allowed','denied','requested','approved','executed','failed')
 or p_resource_type not in ('platform','user','support_ticket','tariff','payment','credit_wallet','credit_ledger','finance_request',
 'pricing_catalog_draft','plan_catalog_draft','permission','security_setting','direct_message_report','direct_moderation_appeal')
 or (p_reason is not null and length(p_reason)>500) then
 raise exception 'invalid admin audit event' using errcode='22023'; end if;
 insert into public.admin_audit_events(actor_user_id,action,outcome,resource_type,resource_id,correlation_id,reason)
 values(p_actor_user_id,p_action,p_outcome,p_resource_type,p_resource_id,p_correlation_id,p_reason) returning id into v_id;
 return v_id;
end; $$;

revoke all on function public.apply_direct_user_moderation(uuid,uuid,text,text,timestamptz) from public,anon,authenticated;
revoke all on function public.review_direct_message_report(uuid,uuid,text) from public,anon,authenticated;
revoke all on function public.create_direct_moderation_appeal(uuid,text) from public,anon,authenticated;
revoke all on function public.review_direct_moderation_appeal(uuid,uuid,text,text) from public,anon,authenticated;
grant execute on function public.apply_direct_user_moderation(uuid,uuid,text,text,timestamptz) to service_role;
grant execute on function public.review_direct_message_report(uuid,uuid,text) to service_role;
grant execute on function public.create_direct_moderation_appeal(uuid,text) to service_role;
grant execute on function public.review_direct_moderation_appeal(uuid,uuid,text,text) to service_role;
