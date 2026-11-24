-- Durable metadata-only AI request journal.
-- Insert a row before calling an external provider. No prompts or responses are stored.
-- Apply only after live Supabase schema/ACL reconciliation.

create table if not exists public.ai_usage_outbox (
  request_id uuid primary key,
  user_id uuid not null,
  endpoint text not null check (endpoint in ('chat', 'prompts')),
  provider text not null,
  model text not null,
  status text not null default 'started'
    check (status in ('started', 'succeeded', 'unknown')),
  input_tokens integer check (input_tokens is null or input_tokens >= 0),
  output_tokens integer check (output_tokens is null or output_tokens >= 0),
  total_tokens integer check (total_tokens is null or total_tokens >= 0),
  cost_usd numeric(20, 10) check (cost_usd is null or cost_usd >= 0),
  cost_source text,
  error_type text,
  started_at timestamptz not null default now(),
  completed_at timestamptz,
  updated_at timestamptz not null default now()
);

create index if not exists ai_usage_outbox_status_started_idx
  on public.ai_usage_outbox(status, started_at);

create index if not exists ai_usage_outbox_user_started_idx
  on public.ai_usage_outbox(user_id, started_at desc);

alter table public.ai_usage_outbox enable row level security;
revoke all on table public.ai_usage_outbox from public, anon, authenticated;
grant select, insert, update on table public.ai_usage_outbox to service_role;

comment on table public.ai_usage_outbox is
  'Metadata-only durable journal for AI provider calls. Started rows must be reconciled; unknown is not assumed free. Never store prompts or generated content.';
