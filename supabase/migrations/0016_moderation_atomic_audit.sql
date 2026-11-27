-- Atomic moderation state changes and append-only audit events.
-- Apply ONLY to a disposable Supabase project first; never run on production as part of this source change.
-- Each RPC executes its state mutation and audit insert in one PostgreSQL transaction.

create or replace function public.pwa_review_user_report(
  p_report_id uuid,
  p_moderator_id uuid,
  p_status text,
  p_moderator_note text
)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_report public.user_reports%rowtype;
begin
  if p_status not in ('reviewing', 'resolved', 'rejected') then
    raise exception 'Invalid report status' using errcode = '22023';
  end if;
  if p_moderator_note is not null and char_length(p_moderator_note) > 2000 then
    raise exception 'Moderator note is too long' using errcode = '22023';
  end if;

  update public.user_reports
     set status = p_status,
         moderator_note = p_moderator_note,
         reviewed_by = p_moderator_id,
         reviewed_at = pg_catalog.now(),
         updated_at = pg_catalog.now()
   where id = p_report_id
   returning * into v_report;

  if not found then
    return null;
  end if;

  insert into public.admin_audit_log
    (actor_user_id, action, target_user_id, entity_type, entity_id, metadata)
  values
    (p_moderator_id, 'report.reviewed', v_report.reported_user_id,
     'report', v_report.id::text,
     pg_catalog.jsonb_build_object('status', p_status));

  return pg_catalog.to_jsonb(v_report);
end;
$$;

create or replace function public.pwa_create_user_suspension(
  p_user_id uuid,
  p_moderator_id uuid,
  p_reason text,
  p_scope text,
  p_expires_at timestamptz
)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_suspension public.user_suspensions%rowtype;
begin
  if p_scope not in ('platform', 'assistant', 'community') then
    raise exception 'Invalid suspension scope' using errcode = '22023';
  end if;
  if p_reason is null or char_length(p_reason) not between 5 and 1000 then
    raise exception 'Invalid suspension reason' using errcode = '22023';
  end if;
  if p_expires_at is not null and p_expires_at <= pg_catalog.now() then
    raise exception 'Suspension expiry must be in the future' using errcode = '22023';
  end if;

  insert into public.user_suspensions
    (user_id, reason, scope, created_by, expires_at)
  values
    (p_user_id, p_reason, p_scope, p_moderator_id, p_expires_at)
  returning * into v_suspension;

  insert into public.admin_audit_log
    (actor_user_id, action, target_user_id, entity_type, entity_id, metadata)
  values
    (p_moderator_id, 'user.suspended', p_user_id,
     'suspension', v_suspension.id::text,
     pg_catalog.jsonb_build_object('scope', p_scope));

  return pg_catalog.to_jsonb(v_suspension);
end;
$$;

create or replace function public.pwa_revoke_user_suspension(
  p_suspension_id uuid,
  p_moderator_id uuid
)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_suspension public.user_suspensions%rowtype;
begin
  update public.user_suspensions
     set revoked_at = pg_catalog.now(),
         revoked_by = p_moderator_id
   where id = p_suspension_id
     and revoked_at is null
   returning * into v_suspension;

  if not found then
    return null;
  end if;

  insert into public.admin_audit_log
    (actor_user_id, action, target_user_id, entity_type, entity_id, metadata)
  values
    (p_moderator_id, 'user.suspension_revoked', v_suspension.user_id,
     'suspension', v_suspension.id::text,
     pg_catalog.jsonb_build_object('scope', v_suspension.scope));

  return pg_catalog.to_jsonb(v_suspension);
end;
$$;

revoke all on function public.pwa_review_user_report(uuid, uuid, text, text) from public, anon, authenticated;
revoke all on function public.pwa_create_user_suspension(uuid, uuid, text, text, timestamptz) from public, anon, authenticated;
revoke all on function public.pwa_revoke_user_suspension(uuid, uuid) from public, anon, authenticated;

grant execute on function public.pwa_review_user_report(uuid, uuid, text, text) to service_role;
grant execute on function public.pwa_create_user_suspension(uuid, uuid, text, text, timestamptz) to service_role;
grant execute on function public.pwa_revoke_user_suspension(uuid, uuid) to service_role;

comment on function public.pwa_review_user_report(uuid, uuid, text, text) is
  'Atomically updates report review state and appends the corresponding admin audit event.';
comment on function public.pwa_create_user_suspension(uuid, uuid, text, text, timestamptz) is
  'Atomically creates a user suspension and appends the corresponding admin audit event.';
comment on function public.pwa_revoke_user_suspension(uuid, uuid) is
  'Atomically revokes an active user suspension and appends the corresponding admin audit event.';
