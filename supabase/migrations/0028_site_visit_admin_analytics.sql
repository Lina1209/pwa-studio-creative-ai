-- Owner-only aggregate analytics: daily trend and popular route groups.
-- This migration stores only coarse route categories, never IP or geographic data.
create table if not exists public.site_visit_daily_routes (
  visit_date date not null,
  route_group text not null check (route_group in ('home','create','movie','editor','prompts','library','account','voice','scenes','assistant','guide','rules','settings','other')),
  page_views bigint not null default 0 check (page_views >= 0),
  updated_at timestamptz not null default now(),
  primary key (visit_date, route_group)
);
alter table public.site_visit_daily_routes enable row level security;
revoke all on public.site_visit_daily_routes from public, anon, authenticated;
grant select, insert, update, delete on public.site_visit_daily_routes to service_role;

create or replace function public.record_site_visit(
  p_event_id uuid, p_visit_date date, p_visitor_token_hash text, p_route_group text
) returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
declare v_inserted integer; v_unique integer;
begin
  if p_event_id is null or p_visit_date is null
     or p_visit_date <> (now() at time zone 'UTC')::date
     or p_visitor_token_hash is null or p_visitor_token_hash !~ '^[0-9a-f]{64}$'
     or p_route_group is null
     or p_route_group not in ('home','create','movie','editor','prompts','library','account','voice','scenes','assistant','guide','rules','settings','other') then
    raise exception 'invalid visit event';
  end if;
  insert into public.site_visit_events(event_id, visit_date, visitor_token_hash, route_group)
  values (p_event_id, p_visit_date, p_visitor_token_hash, p_route_group)
  on conflict (event_id) do nothing;
  get diagnostics v_inserted = row_count;
  if v_inserted = 1 then
    delete from public.site_visit_events where created_at < now() - interval '7 days';
    delete from public.site_visit_daily_visitors where created_at < now() - interval '2 days';
    insert into public.site_visit_totals(singleton, total_page_views, updated_at)
    values (true, 1, now())
    on conflict (singleton) do update set total_page_views = public.site_visit_totals.total_page_views + 1, updated_at = now();
    insert into public.site_visit_daily(visit_date, page_views, unique_visitors, updated_at)
    values (p_visit_date, 1, 0, now())
    on conflict (visit_date) do update set page_views = public.site_visit_daily.page_views + 1, updated_at = now();
    insert into public.site_visit_daily_routes(visit_date, route_group, page_views, updated_at)
    values (p_visit_date, p_route_group, 1, now())
    on conflict (visit_date, route_group) do update set page_views = public.site_visit_daily_routes.page_views + 1, updated_at = now();
    insert into public.site_visit_daily_visitors(visit_date, visitor_token_hash)
    values (p_visit_date, p_visitor_token_hash)
    on conflict (visit_date, visitor_token_hash) do nothing;
    get diagnostics v_unique = row_count;
    if v_unique = 1 then
      update public.site_visit_daily set unique_visitors = unique_visitors + 1, updated_at = now()
      where visit_date = p_visit_date;
    end if;
  end if;
  return public.get_site_visit_stats();
end;
$$;
revoke all on function public.record_site_visit(uuid,date,text,text) from public, anon, authenticated;
grant execute on function public.record_site_visit(uuid,date,text,text) to service_role;

create or replace function public.get_site_visit_admin_stats()
returns jsonb language sql stable security definer set search_path = public, pg_temp as $$
  select public.get_site_visit_stats() || jsonb_build_object(
    'daily_series', coalesce((
      select jsonb_agg(jsonb_build_object('date', days.visit_date::date, 'page_views', coalesce(d.page_views, 0),
                                          'unique_visitors', coalesce(d.unique_visitors, 0)) order by days.visit_date)
      from generate_series((now() at time zone 'UTC')::date - 29,
                           (now() at time zone 'UTC')::date, interval '1 day') as days(visit_date)
      left join public.site_visit_daily d on d.visit_date = days.visit_date::date
    ), '[]'::jsonb),
    'top_routes', coalesce((
      select jsonb_agg(jsonb_build_object('route_group', routes.route_group, 'page_views', routes.page_views)
                       order by routes.page_views desc, routes.route_group)
      from (select route_group, sum(page_views)::bigint as page_views
            from public.site_visit_daily_routes
            where visit_date >= (now() at time zone 'UTC')::date - 29
            group by route_group order by sum(page_views) desc, route_group limit 8) routes
    ), '[]'::jsonb)
  );
$$;
revoke all on function public.get_site_visit_admin_stats() from public, anon, authenticated;
grant execute on function public.get_site_visit_admin_stats() to service_role;
