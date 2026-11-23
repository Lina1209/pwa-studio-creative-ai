# Subscription plan quota drafts

Plan catalog drafts are immutable planning records. Saving a draft does not assign a plan to a user, change live request admission, grant credits, start a subscription, enable checkout, or charge anyone.

## Supported quota dimensions

The admin plan-draft API accepts these integer limits:

- `max_parallel_jobs`
- `max_video_seconds`
- `daily_generation_jobs`
- `monthly_generation_jobs`
- `daily_ai_requests`
- `monthly_ai_requests`
- `max_concurrent_ai_requests`
- `daily_image_generations`
- `monthly_image_generations`
- `daily_video_generations`
- `monthly_video_generations`
- `daily_audio_generations`
- `monthly_audio_generations`

`max_resolution` accepts `480p`, `720p`, `1080p`, or `4k`. Unknown keys, booleans, negative values, and non-integer values are rejected.

These fields describe intended customer-plan entitlements. They are separate from the current operational admission ceilings documented in `AI_ADMISSION_LIMITS.md`, which protect provider capacity globally and per user. A plan value is not enforced merely because it exists in a draft.

## Before plan limits can become live

A future activation path must be implemented and reviewed separately. It must:
1. Resolve an authenticated user's active plan from a trusted server-side subscription/entitlement record, never from browser input.
2. Resolve the exact immutable plan version and effective period.
3. Enforce per-plan daily/monthly quotas atomically in PostgreSQL before any provider call.
4. Keep AI request, image, video, audio, and generation-job usage counters separate where their cost profiles differ.
5. Define renewal, expiry, downgrade, cancellation, refunds, and grace-period behavior.
6. Ensure credit holds and provider USD budget reservations remain independent controls.
7. Require verified payment webhooks before paid subscription activation or paid credit grants.

Until those gates exist, all saved plans remain drafts and the existing operational admission limits remain in force.
