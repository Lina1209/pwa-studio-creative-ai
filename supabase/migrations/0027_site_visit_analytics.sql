-- Privacy-minimizing aggregate site visit counter.
-- No raw IP, user ID, email, prompt, or full user-agent is stored.
create table if not exists public.site_visit_totals (
  singleton boolean primary key default true check (singleton),
  total_page_views bigint not null default 0 check (total_page_views >= 0),
  updated_at timestamptz not null default now()
);
insert into public.site_visit_totals(singleton) values (true)
on conflict (singleton) do nothing;

create table if not exists public.site_visit_daily (
  visit_date date primary key,
  page_views bigint not null default 0 check (page_views >= 0),
  unique_visitors bigint not null default 0 check (unique_visitors >= 0),
  updated_at timestamptz not null default now()
);

create table if not exists public.site_visit_events (
  event_id uuid primary key,
  visit_date date not null,
  visitor_token_hash text not null check (visitor_token_hash ~ '^[0-9a-f]{64}

alter table public.site_visit_totals enable row level security;
alter table public.site_visit_daily enable row level security;
alter table public.site_visit_events enable row level security;
revoke all on public.site_visit_totals, public.site_visit_daily, public.site_visit_events from public, anon, authenticated;
grant select, insert, update, delete on public.site_visit_totals, public.site_visit_daily, public.site_visit_events to service_role;

create or replace function public.record_site_visit(
  p_event_id uuid,
  p_visit_date date,
  p_visitor_token_hash text,
  p_route_group text
) returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_inserted integer;
  v_unique integer := 0;
begin
  if p_event_id is null
     or p_visit_date is null
     or p_visit_date <> (now() at time zone 'UTC')::date
     or p_visitor_token_hash is null
     or p_visitor_token_hash !~ '^[0-9a-f]{64}$'
     or p_route_group is null
     or p_route_group not in ('home','create','movie','editor','prompts','library','account','voice','scenes','assistant','guide','rules','settings','other') then
    raise exception 'invalid visit event';
  end if;

  insert into public.site_visit_events(event_id, visit_date, visitor_token_hash, route_group)
  values (p_event_id, p_visit_date, p_visitor_token_hash, p_route_group)
  on conflict (event_id) do nothing;
  get diagnostics v_inserted = row_count;

  if v_inserted = 1 then
    -- Keep only short-lived deduplication material; lifetime aggregates remain.
    delete from public.site_visit_events where created_at < now() - interval '7 days';
    delete from public.site_visit_daily_visitors where created_at < now() - interval '2 days';

    insert into public.site_visit_totals(singleton, total_page_views, updated_at)
    values (true, 1, now())
    on conflict (singleton) do update
      set total_page_views = public.site_visit_totals.total_page_views + 1,
          updated_at = now();

    insert into public.site_visit_daily(visit_date, page_views, unique_visitors, updated_at)
    values (p_visit_date, 1, 0, now())
    on conflict (visit_date) do update
      set page_views = public.site_visit_daily.page_views + 1,
          updated_at = now();

    insert into public.site_visit_events(event_id, visit_date, visitor_token_hash, route_group)
    values (gen_random_uuid(), p_visit_date, p_visitor_token_hash, p_route_group)
    on conflict (visit_date, visitor_token_hash) do nothing;
    get diagnostics v_unique = row_count;
    if v_unique = 1 then
      update public.site_visit_daily
        set unique_visitors = unique_visitors + 1, updated_at = now()
        where visit_date = p_visit_date;
    end if;
  end if;

  return public.get_site_visit_stats();
end;
$$;


create or replace function public.get_site_visit_stats()
returns jsonb
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select jsonb_build_object(
    'total_page_views', coalesce((select total_page_views from public.site_visit_totals where singleton = true), 0),
    'today_page_views', coalesce((select page_views from public.site_visit_daily where visit_date = (now() at time zone 'UTC')::date), 0),
    'today_unique_visitors', coalesce((select unique_visitors from public.site_visit_daily where visit_date = (now() at time zone 'UTC')::date), 0),
    'last_7_days_page_views', coalesce((select sum(page_views) from public.site_visit_daily where visit_date >= (now() at time zone 'UTC')::date - 6), 0),
    'last_30_days_page_views', coalesce((select sum(page_views) from public.site_visit_daily where visit_date >= (now() at time zone 'UTC')::date - 29), 0)
  );
$$;

create or replace function public.record_site_visit(
  p_event_id uuid,
  p_visit_date date,
  p_visitor_token_hash text,
  p_route_group text
) returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_inserted integer;
  v_unique integer := 0;
begin
  if p_event_id is null or p_visit_date is null
     or p_visit_date <> (now() at time zone 'UTC')::date
     or p_visitor_token_hash is null
     or p_visitor_token_hash !~ '^[0-9a-f]{64}$'
     or p_route_group is null
     or p_route_group not in ('home','create','movie','editor','prompts','library','account','voice','scenes','assistant','guide','rules','settings','other') then
    raise exception 'invalid visit event';
  end if;

  insert into public.site_visit_events(event_id, visit_date, visitor_token_hash, route_group)
  values (p_event_id, p_visit_date, p_visitor_token_hash, p_route_group)
  on conflict (event_id) do nothing;
  get diagnostics v_inserted = row_count;

  if v_inserted = 1 then
    insert into public.site_visit_totals(singleton, total_page_views, updated_at)
    values (true, 1, now())
    on conflict (singleton) do update
      set total_page_views = public.site_visit_totals.total_page_views + 1, updated_at = now();

    insert into public.site_visit_daily(visit_date, page_views, unique_visitors, updated_at)
    values (p_visit_date, 1, 0, now())
    on conflict (visit_date) do update
      set page_views = public.site_visit_daily.page_views + 1, updated_at = now();

    insert into public.site_visit_daily_visitors(visit_date, visitor_token_hash)
    values (p_visit_date, p_visitor_token_hash)
    on conflict (visit_date, visitor_token_hash) do nothing;
    get diagnostics v_unique = row_count;
    if v_unique = 1 then
      update public.site_visit_daily
        set unique_visitors = unique_visitors + 1, updated_at = now()
        where visit_date = p_visit_date;
    end if;
  end if;
  return public.get_site_visit_stats();
end;
$$;

revoke all on function public.record_site_visit(uuid,date,text,text) from public, anon, authenticated;
revoke all on function public.get_site_visit_stats() from public, anon, authenticated;
grant execute on function public.record_site_visit(uuid,date,text,text) to service_role;
grant execute on function public.get_site_visit_stats() to service_role;
