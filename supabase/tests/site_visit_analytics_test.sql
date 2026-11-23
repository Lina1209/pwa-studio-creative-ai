-- Run after migrations 0027 and 0028 in a disposable test database.
begin;
do $$
declare
  v_before bigint;
  v_after bigint;
  v_route_before bigint;
  v_route_after bigint;
  v_first jsonb;
  v_replay jsonb;
  v_limited jsonb;
  v_event uuid := gen_random_uuid();
  v_rate_event uuid := gen_random_uuid();
  v_blocked_event uuid := gen_random_uuid();
  v_event_count bigint;
  v_total_before_block bigint;
  v_total_after_block bigint;
  v_rate_count integer;
  v_hash text := repeat('a', 64);
  v_rate_hash text := repeat('b', 64);
  i integer;
begin
  select total_page_views into v_before
  from public.site_visit_totals where singleton = true;

  select page_views into v_route_before
  from public.site_visit_daily_routes
  where visit_date = (now() at time zone 'UTC')::date and route_group = 'home';

  v_first := public.record_site_visit(
    v_event, (now() at time zone 'UTC')::date, v_hash, 'home'
  );
  v_after := (v_first->>'total_page_views')::bigint;
  if v_after <> coalesce(v_before, 0) + 1 then
    raise exception 'page view total did not increment exactly once';
  end if;

  select page_views into v_route_after
  from public.site_visit_daily_routes
  where visit_date = (now() at time zone 'UTC')::date and route_group = 'home';
  if v_route_after <> coalesce(v_route_before, 0) + 1 then
    raise exception 'daily route aggregate did not increment exactly once';
  end if;

  v_replay := public.record_site_visit(
    v_event, (now() at time zone 'UTC')::date, v_hash, 'home'
  );
  if (v_replay->>'total_page_views')::bigint <> v_after then
    raise exception 'duplicate event changed lifetime counter';
  end if;

  if (select page_views from public.site_visit_daily_routes
      where visit_date = (now() at time zone 'UTC')::date and route_group = 'home') <> v_route_after then
    raise exception 'duplicate event changed route aggregate';
  end if;

  if not exists (
    select 1 from public.site_visit_daily_visitors
    where visit_date = (now() at time zone 'UTC')::date
      and visitor_token_hash = v_hash
  ) then
    raise exception 'daily visitor deduplication record missing';
  end if;

  -- A distinct visitor token can record no more than 20 unique page views
  -- within one minute. The 21st event must be rejected without incrementing totals.
  v_limited := public.record_site_visit(
    v_rate_event, (now() at time zone 'UTC')::date, v_rate_hash, 'other'
  );
  -- Exact replay must not consume another rate-limit slot.
  for i in 1..5 loop
    v_limited := public.record_site_visit(
      v_rate_event, (now() at time zone 'UTC')::date, v_rate_hash, 'other'
    );
    if coalesce((v_limited->>'rate_limited')::boolean, false) then
      raise exception 'idempotent replay consumed rate-limit budget';
    end if;
  end loop;

  for i in 2..20 loop
    v_limited := public.record_site_visit(
      gen_random_uuid(), (now() at time zone 'UTC')::date, v_rate_hash, 'other'
    );
    if coalesce((v_limited->>'rate_limited')::boolean, false) then
      raise exception 'rate limit triggered before the 21st event';
    end if;
  end loop;
  select request_count into v_rate_count
  from public.site_visit_rate_limits
  where visitor_token_hash = v_rate_hash
    and window_start = date_trunc('minute', now());
  if v_rate_count <> 20 then
    raise exception 'idempotent event replay changed the rate-limit count';
  end if;

  select total_page_views into v_total_before_block
  from public.site_visit_totals where singleton = true;
  v_limited := public.record_site_visit(
    v_blocked_event, (now() at time zone 'UTC')::date, v_rate_hash, 'other'
  );
  if coalesce((v_limited->>'rate_limited')::boolean, false) is not true then
    raise exception '21st event was not rate limited';
  end if;
  select count(*) into v_event_count
  from public.site_visit_events where visitor_token_hash = v_rate_hash;
  if v_event_count <> 20 then
    raise exception 'rejected events were persisted or accepted event deduplication is incorrect';
  end if;
  if exists (select 1 from public.site_visit_events where event_id = v_blocked_event) then
    raise exception 'rate-limited event ID was persisted';
  end if;
  select total_page_views into v_total_after_block
  from public.site_visit_totals where singleton = true;
  if v_total_after_block <> v_total_before_block then
    raise exception 'rate-limited event changed the lifetime counter';
  end if;
end;
$$;
rollback;
