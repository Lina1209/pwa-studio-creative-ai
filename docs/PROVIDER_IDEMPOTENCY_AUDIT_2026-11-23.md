# Provider idempotency and retry-safety audit — 2026-11-23

**Status: BLOCKER / not production-approved.** This is a source-code and public-documentation audit, not a live provider-account test. No provider credentials were used and no paid provider request was sent.

## 1. Repository finding

The current review branch contains a generic durable provider-operation journal, recovery decision logic and worker orchestration, but the repository tree does not contain a production video-provider adapter package implementing concrete video API create/status/cancel/usage contracts. The README also states that video generation is not connected yet. Therefore, there is no concrete video adapter whose idempotency guarantee can honestly be certified from this repository.

The generic recovery policy is deliberately conditional:
- a retry after a definitive `not_found` is allowed only when the adapter declares provider-supported idempotency;
- pending, unknown, unavailable lookup, and ambiguous outcomes are deferred/quarantined;
- the stable internal job UUID is not, by itself, proof that the external provider deduplicates requests.

## 2. What public provider documentation establishes

| Provider/API documentation reviewed | Documented behavior | Idempotency conclusion |
|---|---|---|
| Luma Dream Machine API | Create operation returns an ID; clients poll status until ready. | The cited API overview does not document an idempotency-key guarantee. Treat create retry as unsafe until the exact endpoint contract says otherwise. |
| Runway developer pricing/API material | Public material describes model pricing and task generation. | Pricing documentation is not an idempotency contract. Do not infer safe POST retries from task IDs or request IDs. |
| OpenAI API overview | Documents authentication, request IDs, rate limits and API behavior. | A request ID is for tracing, not a promise of deduplicated execution. Require endpoint-specific idempotency documentation before enabling retry. |

### Primary references
- Luma API overview: https://docs.lumalabs.ai/docs/api
- Runway Dev API pricing guide: https://dev.runway.com/learn/ai-video-api-pricing
- OpenAI API reference overview: https://developers.openai.com/api/reference/overview

A provider task ID returned after a successful create call helps retrieve the task; it does not prove that repeating the create call with the same client key cannot create a second billable task.

## 3. Required adapter contract before enabling any provider

Every concrete adapter must provide a reviewed capability record:
1. Exact provider, API product, endpoint, API version and model family.
2. Official documentation URL and date reviewed.
3. Whether the create endpoint accepts an idempotency key; exact header/body field and documented retention window.
4. Whether duplicate keys with identical payloads return the original task; behavior for same key with different payload.
5. Whether the key is scoped by account, endpoint, model or time window.
6. Whether task lookup by provider task ID and/or client idempotency key is supported.
7. Whether lookup is strongly consistent or eventually consistent, including documented not-found behavior.
8. Whether timeout, 5xx, 429, connection reset and moderation failures can still create billable work.
9. Billing semantics for failed, cancelled, timed-out and abandoned tasks.
10. Usage/cost evidence fields and reconciliation source (task response, usage endpoint, invoice/export).

The adapter must expose explicit capabilities, not a hand-written optimistic boolean:
- `supports_create_idempotency`
- `idempotency_scope`
- `idempotency_retention_seconds`
- `supports_lookup_by_client_key`
- `lookup_consistency`
- `supports_usage_reconciliation`

If any required property is unknown, set it to unsupported and keep automatic create retry disabled.

### Webhook trust boundary in the application

The payment-order service now accepts a provider-specific adapter contract rather than a caller-supplied `signature_verified=True` flag. The adapter receives the exact raw request bytes and headers, must verify the provider's cryptographic signature and timestamp/replay window, and only then returns a typed `VerifiedProviderEvent`. The service derives the persisted payload digest from those same raw bytes and takes amount, currency, event ID and provider payment ID only from the adapter's normalized result.

This is an interface and fail-closed ingestion boundary, not a provider implementation. There is still no concrete adapter, secret configuration, webhook route or enabled payment flow. A fake adapter is used only in unit tests to verify the contract; it does not establish a real provider's signature semantics.

## 4. Safe execution policy

- Persist the exact canonical request payload hash, operation key, provider/account/model and attempt state before network I/O.
- Send a provider idempotency key only where the provider explicitly documents it.
- On a timeout or connection loss after request transmission may have begun, mark outcome ambiguous. Never create a new key and never retry blindly.
- If provider lookup by idempotency key is unavailable, keep the reservation and quarantine for operator reconciliation.
- If lookup returns not-found, do not interpret that as proof of no charge unless the provider documents lookup consistency and a safe retry rule. For eventually consistent lookup, wait the documented visibility window and query again.
- If the provider has no idempotency guarantee, an ambiguous create is not automatically resubmitted, even if our internal key remains stable.
- Reconcile task IDs and actual invoice/usage exports. Store provider request IDs for support and audit.
- Release provider-cost reservations only after documented proof of no charge or a confirmed terminal state with authoritative usage/cost evidence.

## 5. Go-live gate

A provider may be enabled for billable traffic only after:
- its exact adapter and contract tests exist;
- official endpoint-specific idempotency behavior is recorded;
- duplicate-submit and ambiguous-timeout tests pass against a sandbox or controlled low-cost account;
- task lookup consistency and billing edge cases are verified;
- invoice/usage reconciliation matches internal cost ledger;
- the adapter's declared capabilities are checked against the recovery worker at startup;
- an operator-approved per-provider cap and global budget are configured.

Until then, mark the provider `disabled_for_billable_generation`. Generic worker safety logic and a stable internal UUID are not a substitute for provider-side idempotency.


## Payment provider secret handling boundary (2026-11-23)

The generic payment layer now provides a server-only environment secret resolver.
Adapters may request only environment variable references matching
`PAYMENT_PROVIDER_<IDENTIFIER>_SECRET`; secret values are not accepted from
browser input, stored in the database, included in API responses, or included
in resolver errors. Missing, blank, whitespace-padded, or invalid references
fail closed.

The hosting environment/secret manager remains the source of truth. Rotation
is performed by replacing the secret in the hosting secret manager and
restarting/redeploying the service according to the provider's overlap/rotation
requirements. The generic layer does not assume that all providers support
dual-secret rotation; a concrete adapter must implement the provider's
documented rotation semantics. No concrete provider, credentials, webhook
route, or live payment runtime is enabled. The default runtime flag remains
false. Do not add real secret values to repository files, CI logs, issue
comments, or frontend build variables.


## Central payment-provider bootstrap

FastAPI now constructs one process-level payment adapter registry through
`build_payment_provider_registry(settings)`. The factory accepts adapters
only from trusted server code; request fields cannot register or select an
adapter implementation. With the default runtime flag false, it always
returns an empty disabled registry, even if adapters are passed. If an
operator enables the runtime before a concrete adapter is registered in
server code, startup fails closed rather than exposing a partially configured
payment path. Enabling a real provider still requires a reviewed adapter,
provider/account namespace, verified webhook route, and separate operational
approval. No adapter is currently registered and payment runtime remains off.


The settings model also rejects `PAYMENT_PROVIDER_MODE=live` unless the
server runtime flag is explicitly enabled. This is only a configuration
precondition: enabling the flag without a concrete trusted adapter still
causes the centralized bootstrap to fail startup. Therefore, changing the
mode alone cannot activate live payments, and enabling the flag alone cannot
activate a provider. The repository currently registers no concrete payment
adapter.
