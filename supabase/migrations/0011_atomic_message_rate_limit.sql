-- Atomic fixed-window rate limiter for direct messages.
-- The only caller should be the trusted backend using the server-side service key.

create table if not exists public.message_rate_limits (
  user_id uuid primary key references auth.users(id) on delete cascade,
  window_start timestamptz not null,
  request_count integer not null default 0 check (request_count >= 0)
);

alter table public.message_rate_limits enable row level security;
revoke all on public.message_rate_limits from anon, authenticated;
grant select, insert, update, delete on public.message_rate_limits to service_role;

create or replace function public.consume_message_rate_limit(
  p_user_id uuid,
  p_limit integer default 20,
  p_window_seconds integer default 60
)
returns boolean
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_window_start timestamptz;
  v_count integer;
begin
  if p_user_id is null or p_limit < 1 or p_limit > 1000
     or p_window_seconds < 1 or p_window_seconds > 3600 then
    raise exception 'Invalid rate limit parameters';
  end if;

  v_window_start := to_timestamp(
    floor(extract(epoch from clock_timestamp()) / p_window_seconds)
    * p_window_seconds
  );

  insert into public.message_rate_limits (user_id, window_start, request_count)
  values (p_user_id, v_window_start, 1)
  on conflict (user_id) do update
    set window_start = excluded.window_start,
        request_count = case
          when public.message_rate_limits.window_start = excluded.window_start
            then public.message_rate_limits.request_count + 1
          else 1
        end
    where public.message_rate_limits.window_start <> excluded.window_start
       or public.message_rate_limits.request_count < p_limit
  returning request_count into v_count;

  return found;
end;
$$;

revoke all on function public.consume_message_rate_limit(uuid, integer, integer)
  from public, anon, authenticated;
grant execute on function public.consume_message_rate_limit(uuid, integer, integer)
  to service_role;

comment on table public.message_rate_limits is
  'Server-managed atomic fixed-window counters for direct-message abuse prevention.';
