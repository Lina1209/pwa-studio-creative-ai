# AI Generation API, Provider and Cost-Control Audit

Date: 2026-11-24
Scope: source-only review of authenticated text-generation routes, provider configuration, rate limiting, safety checks, output ceilings, usage telemetry, and the credit/pricing adapter. No live provider request, live Supabase query, SQL execution, production change, or deployment was performed.

## Reviewed
- `backend/app/main.py`
- `backend/app/schemas.py`
- `backend/app/core/config.py`
- `backend/app/services/auth.py`
- `backend/app/services/ai_service.py`
- `backend/app/services/ai_rate_limit_service.py`
- `backend/app/services/content_safety.py`
- `backend/app/services/usage_service.py`
- `backend/app/services/pricing_service.py`
- `backend/app/services/credit_service.py`
- `supabase/migrations/0003_ai_usage_metering.sql`
- `supabase/migrations/0012_atomic_ai_rate_limit.sql`
- related backend tests and wallet migration already reviewed

## Positive controls observed

1. Both `POST /api/chat` and `POST /api/prompts` require `get_current_user`; identity is derived from a verified Supabase JWT.
2. Neither request schema accepts provider, model, API key, user ID, price, or credit amount as an input field. The active provider/model are server configuration.
3. Both routes check account suspension, run a content guard, and consume an atomic per-user/per-endpoint rate-limit slot before provider use.
4. Rate-limit storage fails closed when Supabase configuration/network/RPC response is unavailable. The migration revokes direct table access from anon/authenticated and grants the RPC only to service_role.
5. Provider API keys are passed only by the backend to LiteLLM. The service enforces a bounded output token ceiling (default 2,048; configured range 256–8,192), timeout 90 seconds, and one retry.
6. Provider failure logs contain provider/model/error type/status code only; raw prompts, provider response bodies and credentials are not logged.
7. Usage telemetry contains account, request ID, endpoint, provider/model, token counts and measured cost metadata; it does not persist prompt or response text. Unknown cost remains NULL.
8. AI usage table source has RLS enabled and no anon/authenticated policies; service-role writes are intended.
9. The credit wallet/pricing adapter is not wired to generation endpoints. Its production pricing catalog is empty, so unapproved pricing fails closed. No credit debit is currently performed by these text-generation routes.
10. Existing tests cover output ceiling bounds, per-user rate-limit RPC behavior/fail-closed handling, metadata-only telemetry, and server-owned pricing calculations.

## Findings and recommendations

### GEN-1 — High: text safety is a narrow keyword guard, not complete moderation
`check_content` explicitly describes itself as a first-layer keyword/pattern guard. It covers several severe categories but is not semantic moderation and can miss paraphrases, other languages, context, obfuscation, or newly emerging abuse patterns. The `/api/prompts` system instruction is also materially less explicit than the chat system instruction: it asks for a production-ready prompt but does not repeat the platform's prohibited-content/consent rules.

Recommendation: use a layered moderation policy for every generation endpoint, with provider-independent policy checks and explicit safety instructions in every system prompt. Add adversarial and multilingual tests, including prompt-injection attempts and benign educational/creative false-positive cases. Do not treat the current regex filter as the platform's complete safety boundary.

### GEN-2 — High: telemetry can silently lose successful generation records
`record_ai_usage` is best-effort and catches all write failures. The route returns a successful generated result even if usage persistence fails. This is intentionally resilient for availability, but it can undercount provider spend and make later cost reconciliation incomplete. The request ID is generated only after provider success and is not a durable idempotency key across a retry.

Recommendation: introduce a durable metadata-only outbox or request ledger with a stable request ID created before provider invocation, bounded retries, deduplication, dead-letter visibility, and reconciliation against provider usage. Never put prompt or response text into the outbox.

### GEN-3 — Medium: rate limit is per-user only and fixed-window
The RPC enforces 10 requests per 60-second window per user and endpoint, with an atomic upsert. It does not provide a global/provider spend ceiling, IP/device abuse signal, or concurrency cap. Fixed windows can permit a burst around a boundary. Multiple accounts could still collectively generate high provider spend.

Recommendation: preserve per-account limits, add a global provider budget/circuit breaker, concurrency controls, and abuse signals with privacy safeguards. Consider a sliding/token-bucket limit if burst behavior becomes a problem. Verify the RPC's effective grants and security-definer ownership in live catalog before relying on it.

### GEN-4 — Medium: provider/model configuration is flexible rather than DeepSeek-locked
The backend chooses provider/model from server settings, so a client cannot override them. However, `AI_PROVIDER` and `AI_MODEL` are free-form strings and the service supports OpenAI, DeepSeek, Anthropic, and Ollama. This is operationally flexible but does not enforce a DeepSeek-only production policy in code. The health endpoint exposes the provider name and configured boolean (not secrets), which is useful diagnostics but should be understood as public operational metadata.

Recommendation: if DeepSeek-only is the intended production policy, validate the allowed provider/model pair at startup in production and fail closed for other providers; keep experiments in a separate non-production environment. Confirm Render environment values through a secure owner-only process; never copy keys into chat or client code.

### GEN-5 — Medium: successful generation and usage recording are not one durable operation
The provider call happens first, then usage metadata is inserted. If the process crashes between provider success and telemetry insert, no local durable record remains. Conversely, a provider timeout may be ambiguous: the provider could have processed the request even if the backend received no usable response. The current route returns a generic 502 and does not record an explicit ambiguous outcome.

Recommendation: create a request lifecycle record before provider invocation with states such as accepted, provider_started, succeeded, failed_definitive, and outcome_unknown. Reconcile ambiguous outcomes rather than automatically treating them as zero-cost. Keep this separate from user-visible prompt history.

### GEN-6 — Medium: no generation-level idempotency key or concurrency guard
The chat and prompt routes accept no idempotency key and can start duplicate provider calls if a user double-taps, retries after a network delay, or the frontend repeats a request. Rate limiting reduces frequency but does not make retries idempotent.

Recommendation: add server-generated/request-scoped idempotency with a bounded replay window and per-user in-flight limits. Return the same completed result for a safe replay where feasible; do not persist content in telemetry. UI button disabling is helpful but not a server-side control.

### GEN-7 — Medium: request schemas ignore unknown fields by default
The Pydantic request models do not explicitly forbid extra fields. Current handlers only use declared fields, so a client-supplied `provider`, `model`, `user_id`, or `credits` field is ignored rather than honored. This is not a demonstrated privilege bypass, but rejecting unknown fields makes the contract clearer and reduces future accidental trust of unreviewed inputs.

Recommendation: set `extra="forbid"` on generation request models (or a shared strict base model) and test that owner/provider/model/price/credit overrides receive 422.

### GEN-8 — Low: provider response metadata should be normalized and validated
The API response reports `settings.ai_provider` and the provider-returned actual model. Provider/model strings are not secrets, but provider aliases or unexpected provider response metadata may complicate cost reconciliation. The current telemetry uses the configured provider and actual model, while cost is based on LiteLLM's optional response_cost.

Recommendation: normalize provider identity, store configured and actual model separately if needed, and mark provider-reported cost as an estimate/measurement source with explicit confidence. Do not infer a billable cost from a missing value.

### GEN-9 — High (live-state verification required): database RPC and telemetry privileges are source-only
Migration source indicates service-role-only AI rate-limit RPC execution and no direct client access to ai_usage. Source review cannot establish that these migrations were applied, that no extra permissive policies/grants exist, or that deployed RPC definitions match repository source.

Recommendation: conduct a read-only live audit of migration history, table RLS/policies/grants, function definitions/owners/search_path/EXECUTE grants, and recent metadata-only telemetry rows. Use disposable test accounts for concurrent limit and owner-isolation tests. Do not apply SQL until the live state is reconciled.

## Pricing and billing status
- The production pricing catalog is empty.
- Text-generation routes do not reserve or debit wallet credits.
- No subscription, payment, or purchase operation was performed.
- This is a safe pre-billing state; do not enable charging until real provider rates, conversion policy, infrastructure overhead, free-tier allocation, failure/refund behavior, and reconciliation workflow are approved and tested.
- Keep unknown provider outcomes and missing token usage out of automatic refund paths.

## Recommended implementation order
1. Strengthen safety parity between chat and prompt generation; add adversarial tests.
2. Add durable metadata-only request lifecycle/outbox and stable idempotency.
3. Add global spend/concurrency controls in addition to per-user rate limiting.
4. Enforce production provider allowlist if DeepSeek-only remains the requirement.
5. Reject unexpected request fields and add API contract tests.
6. Reconcile live Supabase migration/RLS/grants/RPC state read-only before any schema change.
7. Only then consider connecting approved pricing and wallet reservations to generation routes.

## Explicitly not performed
- No live DeepSeek request or paid generation was made.
- No API keys or production environment values were read or changed.
- No SQL, migration, RPC, RLS, grants, or database records were changed.
- No credits were charged, reserved, or granted.
- No PR merge or production deployment was performed.
