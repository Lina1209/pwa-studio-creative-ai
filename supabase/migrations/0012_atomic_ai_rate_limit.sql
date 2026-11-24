-- Atomic per-user AI request limits. The trusted backend is the only caller.
create table if not exists public.ai_rate_limits (
  user_id uuid not null references auth.users(id) on delete cascade,
  endpoint text not null check (endpoint in ('chat', 'prompts')),
  window_start timestamptz not null,
  request_count integer not null default 0 check (request_count >= 0),
  primary key (user_id, endpoint)
);

alter table public.ai_rate_limits enable row level security;
revoke all on public.ai_rate_limits from anon, authenticated;
grant select, insert, update, delete on public.ai_rate_limits to service_role;

create or replace function public.consume_ai_rate_limit(
  p_user_id uuid,
  p_endpoint text,
  p_limit integer default 10,
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
  if p_user_id is null
     or p_endpoint not in ('chat', 'prompts')
     or p_limit < 1 or p_limit > 100
     or p_window_seconds < 1 or p_window_seconds > 3600 then
    raise exception 'Invalid AI rate limit parameters';
  end if;

  v_window_start := to_timestamp(
    floor(extract(epoch from clock_timestamp()) / p_window_seconds)
    * p_window_seconds
  );

  insert into public.ai_rate_limits (user_id, endpoint, window_start, request_count)
  values (p_user_id, p_endpoint, v_window_start, 1)
  on conflict (user_id, endpoint) do update
    set window_start = excluded.window_start,
        request_count = case
          when public.ai_rate_limits.window_start = excluded.window_start
            then public.ai_rate_limits.request_count + 1
          else 1
        end
    where public.ai_rate_limits.window_start <> excluded.window_start
       or public.ai_rate_limits.request_count < p_limit
  returning request_count into v_count;

  return found;
end;
$$;

revoke all on function public.consume_ai_rate_limit(uuid, text, integer, integer)
  from public, anon, authenticated;
grant execute on function public.consume_ai_rate_limit(uuid, text, integer, integer)
  to service_role;

comment on table public.ai_rate_limits is
  'Server-managed atomic fixed-window request counters for AI endpoints.';
