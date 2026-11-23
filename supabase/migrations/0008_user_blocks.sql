-- User-controlled blocks for private messaging.
create table if not exists public.user_blocks (
  id uuid primary key default gen_random_uuid(),
  blocker_id uuid not null references auth.users(id) on delete cascade,
  blocked_id uuid not null references auth.users(id) on delete cascade,
  created_at timestamptz not null default now(),
  constraint user_blocks_distinct check (blocker_id <> blocked_id),
  constraint user_blocks_unique unique (blocker_id, blocked_id)
);
create index if not exists user_blocks_blocked_idx on public.user_blocks(blocked_id);
alter table public.user_blocks enable row level security;
revoke all on public.user_blocks from anon, authenticated;
grant select on public.user_blocks to authenticated;
grant select, insert, delete on public.user_blocks to service_role;
drop policy if exists "Users read blocks they created" on public.user_blocks;
create policy "Users read blocks they created" on public.user_blocks
  for select to authenticated using (auth.uid() = blocker_id);
comment on table public.user_blocks is 'Private user block list; writes are server-managed.';
