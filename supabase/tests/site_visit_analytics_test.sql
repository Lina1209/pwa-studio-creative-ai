-- Run after migration 0027 in a disposable test database.
begin;
do $$
declare
  v_before bigint;
  v_after bigint;
  v_first jsonb;
  v_replay jsonb;
  v_event uuid := gen_random_uuid();
  v_hash text := repeat('a', 64);
begin
  select total_page_views into v_before
  from public.site_visit_totals where singleton = true;

  v_first := public.record_site_visit(
    v_event, (now() at time zone 'UTC')::date, v_hash, 'home'
  );
  v_after := (v_first->>'total_page_views')::bigint;
  if v_after <> coalesce(v_before, 0) + 1 then
    raise exception 'page view total did not increment exactly once';
  end if;

  v_replay := public.record_site_visit(
    v_event, (now() at time zone 'UTC')::date, v_hash, 'home'
  );
  if (v_replay->>'total_page_views')::bigint <> v_after then
    raise exception 'duplicate event changed lifetime counter';
  end if;

  if not exists (
    select 1 from public.site_visit_daily_visitors
    where visit_date = (now() at time zone 'UTC')::date
      and visitor_token_hash = v_hash
  ) then
    raise exception 'daily visitor deduplication record missing';
  end if;
end;
$$;
rollback;
