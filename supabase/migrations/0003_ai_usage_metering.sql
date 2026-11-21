-- PWA Studio: private AI usage metering (no credit debits).
-- Apply manually after reviewing the target Supabase project.
create table if not exists public.ai_usage (
  id bigint generated always as identity primary key,
  request_id uuid not null unique,
  user_id uuid not null references auth.users(id) on delete cascade,
  endpoint text not null check (endpoint in ('chat', 'prompts')),
  provider text not null,
  model text not null,
  input_tokens integer check (input_tokens is null or input_tokens >= 0),
  output_tokens integer check (output_tokens is null or output_tokens >= 0),
  total_tokens integer check (total_tokens is null or total_tokens >= 0),
  cost_usd numeric(20, 10) check (cost_usd is null or cost_usd >= 0),
  cost_source text,
  created_at timestamptz not null default now()
);

create index if not exists ai_usage_user_created_idx
  on public.ai_usage(user_id, created_at desc);
create index if not exists ai_usage_created_idx
  on public.ai_usage(created_at desc);

alter table public.ai_usage enable row level security;
-- No policies are granted to anon/authenticated. Backend service-role writes only.
