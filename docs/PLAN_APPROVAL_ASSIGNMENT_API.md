# Backend plan approval and pending assignment API

The integration branch now exposes two owner-only backend operations. They are intentionally separate capabilities:

- `admin.plans.approve`: approve one immutable plan draft.
- `admin.plans.assign`: create an inert pending assignment for a user.

## Approve a draft

`POST /api/admin/plans/drafts/{draft_id}/approve`

JSON body:

```json
{"reason":"Reviewed plan limits, price and provider cost assumptions"}
```

The backend obtains the actor UUID from the verified Supabase access-token subject. It never accepts an actor ID from request JSON. The route checks the approval capability, invokes the service-role-only RPC, and reads the approved snapshot back before returning it.

## Create a pending assignment

`POST /api/admin/plans/assignments`

Requires an `Idempotency-Key` header and a JSON body containing `user_id`, `approved_plan_version_id`, `source_reference`, timezone-aware `starts_at` and `ends_at`, and a reason. The public API currently permits only `operator_grant`; payment-based assignment is deliberately unavailable.

The backend checks the separate assignment capability, derives the actor from the verified session, calls the transactional RPC, and verifies the stored assignment by reading it back.

## Transaction and safety properties

- The database RPCs are service-role-only; browser clients cannot execute them.
- Approval creates one immutable approved snapshot and a central admin audit event in the same transaction.
- Pending assignment creates the assignment row, initial immutable event and central audit event in one transaction.
- Retries with the same idempotency key and identical data return the original result; conflicting reuse fails.
- Assignment rows remain `pending`. They do not activate entitlements, issue credits, enable checkout or unlock generation.
- All assignment dates must include timezone information.
- The API returns explicit `activation_enabled: false`, `credits_granted: false`, and `checkout_enabled: false` flags.

## Not implemented

There is no activation endpoint, active-plan resolver, quota consumption, payment provider, checkout, renewal, cancellation or automatic free-plan assignment. Those require separate reviewed lifecycle and quota-enforcement work. No production migration has been applied and no deployment has been triggered.
