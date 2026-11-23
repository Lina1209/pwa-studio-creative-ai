-- PWA Studio: moderation, reports, suspensions and immutable admin audit trail.
-- Apply this migration in the Supabase SQL Editor before enabling moderation endpoints.

create table if not exists public.user_reports (
  id uuid primary key default gen_random_uuid(),
  reporter_user_id uuid not null references auth.users(id) on delete cascade,
  reported_user_id uuid references auth.users(id) on delete set null,
  category text not null check (category in (
    'harassment', 'impersonation', 'spam', 'copyright',
    'unsafe_content', 'privacy', 'other'
  )),
  description text not null check (char_length(description) between 10 and 4000),
  content_reference text check (content_reference is null or char_length(content_reference) <= 500),
  status text not null default 'pending' check (status in (
    'pending', 'reviewing', 'resolved', 'rejected'
  )),
  moderator_note text check (moderator_note is null or char_length(moderator_note) <= 2000),
  reviewed_by uuid references auth.users(id) on delete set null,
  reviewed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists user_reports_status_created_idx
  on public.user_reports(status, created_at desc);
create index if not exists user_reports_reporter_created_idx
  on public.user_reports(reporter_user_id, created_at desc);

create table if not exists public.user_suspensions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  reason text not null check (char_length(reason) between 5 and 1000),
  scope text not null default 'platform' check (scope in ('platform', 'assistant', 'community')),
  created_by uuid not null references auth.users(id) on delete restrict,
  expires_at timestamptz,
  revoked_at timestamptz,
  revoked_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  check (expires_at is null or expires_at > created_at)
);

create index if not exists user_suspensions_active_user_idx
  on public.user_suspensions(user_id, expires_at)
  where revoked_at is null;

create table if not exists public.admin_audit_log (
  id bigint generated always as identity primary key,
  actor_user_id uuid not null references auth.users(id) on delete restrict,
  action text not null check (char_length(action) between 3 and 100),
  target_user_id uuid references auth.users(id) on delete set null,
  entity_type text not null check (char_length(entity_type) between 2 and 60),
  entity_id text check (entity_id is null or char_length(entity_id) <= 120),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists admin_audit_log_created_idx
  on public.admin_audit_log(created_at desc);
create index if not exists admin_audit_log_actor_idx
  on public.admin_audit_log(actor_user_id, created_at desc);

alter table public.user_reports enable row level security;
alter table public.user_suspensions enable row level security;
alter table public.admin_audit_log enable row level security;

-- Reports: users may submit and read only their own reports.
revoke all on public.user_reports from anon, authenticated;
grant insert, select on public.user_reports to authenticated;
drop policy if exists "Users submit own reports" on public.user_reports;
create policy "Users submit own reports" on public.user_reports
  for insert to authenticated
  with check (auth.uid() = reporter_user_id);
drop policy if exists "Users read own reports" on public.user_reports;
create policy "Users read own reports" on public.user_reports
  for select to authenticated
  using (auth.uid() = reporter_user_id);

-- Moderation state and audit history are server-only (service_role bypasses RLS).
revoke all on public.user_suspensions from anon, authenticated;
revoke all on public.admin_audit_log from anon, authenticated;
grant all on public.user_reports, public.user_suspensions to service_role;
grant select, insert on public.admin_audit_log to service_role;
revoke update, delete, truncate on public.admin_audit_log from service_role;

-- No user-supplied status, reviewer, moderator note, or audit mutation is permitted.
comment on table public.user_reports is 'User-submitted moderation reports. Review fields are server-managed.';
comment on table public.user_suspensions is 'Server-managed account restrictions; never writable by authenticated clients.';
comment on table public.admin_audit_log is 'Append-only administrative action history; server-managed only.';
