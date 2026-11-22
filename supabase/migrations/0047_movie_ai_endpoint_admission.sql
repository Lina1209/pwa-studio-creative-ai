-- Extend private AI metering and distributed admission to the Mini Movie Studio
-- pre-production endpoints. Existing data and privileges remain unchanged.
alter table public.ai_usage
  drop constraint if exists ai_usage_endpoint_check;
alter table public.ai_usage
  add constraint ai_usage_endpoint_check
  check (endpoint in (
    'chat', 'prompts', 'movie_script', 'movie_director', 'movie_storyboard'
  ));

alter table public.ai_request_admission_reservations
  drop constraint if exists ai_request_admission_reservations_endpoint_check;
alter table public.ai_request_admission_reservations
  add constraint ai_request_admission_reservations_endpoint_check
  check (endpoint in (
    'chat', 'prompts', 'movie_script', 'movie_director', 'movie_storyboard'
  ));

comment on constraint ai_usage_endpoint_check on public.ai_usage is
  'Supported server-side AI usage endpoints, including Mini Movie Studio pre-production.';
comment on constraint ai_request_admission_reservations_endpoint_check
  on public.ai_request_admission_reservations is
  'Supported server-side AI admission endpoints, including Mini Movie Studio pre-production.';
