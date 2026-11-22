import hashlib
import logging
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.schemas import ChatRequest, ChatResponse, PromptRequest, PromptResponse, MovieScriptRequest, MovieScriptResponse, MovieDirectorRequest, MovieDirectorScene, MovieDirectorResponse, MovieStoryboardRequest, MovieStoryboardFrame, MovieStoryboardScene, MovieStoryboardResponse, MovieCharacterReference, SceneImageJobRequest, PricingQuoteRequest, SiteVisitRequest, CreditWalletResponse, FinanceRoleGrantRequest, FinanceRoleRevocationRequest, FinanceOperationRequestCreate, FinanceOperationDecisionRequest, FinanceOperationCancelRequest
from app.services.ai_service import AIConfigurationError, AIOverloadedError, ask_ai
from app.services.ai_cost_admission import AIProviderBudgetRejected, AIProviderBudgetUnavailable
from app.services.auth import StudioUser, get_current_user, require_admin, require_permission
from app.services.finance_authorization import FinanceAuthorizationDenied, require_finance_permission
from app.services.content_safety import check_content
from app.services.usage_service import record_ai_usage
from app.services.ai_admission import (
    AIAdmissionRejected,
    AIAdmissionUnavailable,
    reserve_ai_request,
    finish_ai_request,
)
from app.services.admin_audit_service import (
    AdminAuditUnavailable,
    get_admin_audit_events,
    record_admin_audit_event,
)
from app.services.admin_ai_cost_budget_controls import (
    AIBudgetControlError, AIBudgetControlNotConfigured,
    update_global_budget, update_provider_budget, resolve_unknown_reservation,
)
from app.services.admin_ai_cost_budget_reporting import (
    AICostBudgetReportError,
    AICostBudgetReportNotConfiguredError,
    get_admin_ai_cost_budget_report,
)
from app.services.admin_ai_usage_reporting import (
    AIUsageReportError,
    AIUsageReportNotConfiguredError,
    get_admin_ai_usage_report,
)
from app.services.admin_financial_reporting import (
    ProviderCostReportError,
    ProviderCostReportNotConfiguredError,
    get_provider_cost_report,
)
from app.services.pricing_service import PricingError, canonical_request_hash, issue_pricing_quote, load_pricing_catalog, verify_pricing_quote
from app.services.site_analytics import SiteAnalyticsUnavailable, SiteAnalyticsRateLimited, record_visit, get_admin_visit_stats
from app.services.finance_registry import (
    FinanceRegistryNotConfigured,
    FinanceRegistryUnavailable,
    FinanceRoleConflict,
    grant_finance_role,
    list_active_finance_roles,
    revoke_finance_role,
    resolve_finance_grant,
)
from app.services.finance_operation_requests import (
    FinanceRequestConflict,
    FinanceRequestNotConfigured,
    FinanceRequestNotFound,
    FinanceRequestUnavailable,
    cancel_finance_operation_request,
    create_finance_operation_request,
    decide_finance_operation_request,
    read_finance_operation_request,
    list_finance_operation_requests,
    read_finance_operation_request_events,
)
from app.services.admin_credit_ledger import (
    AdminCreditLedgerUnavailable,
    list_admin_credit_ledger,
)
from app.services.credit_wallet_service import (
    CreditWalletNotConfigured,
    CreditWalletUnavailable,
    get_credit_wallet_snapshot,
)
from app.services.generation_jobs import (
    GenerationJobsNotConfiguredError,
    GenerationJobsServiceError,
    GenerationPricingQuoteConflictError,
    get_generation_job,
    create_scene_generation_job,
    store_pricing_quote,
)

settings = get_settings()
logger = logging.getLogger(__name__)


def _audit_admin_read(user: StudioUser, *, resource_type: str, reason: str) -> None:
    """Best-effort audit for successful read-only owner operations."""
    try:
        record_admin_audit_event(
            settings,
            actor_user_id=UUID(user.user_id),
            action="admin.access",
            outcome="allowed",
            resource_type=resource_type,
            reason=reason,
        )
    except (AdminAuditUnavailable, ValueError):
        # Read-only access remains available; missing audit writes are visible in server logs.
        logger.warning("Successful admin read could not be persisted to the audit journal.")

app = FastAPI(
    title=settings.app_name,
    description="Private API for PWA Studio — Creative AI.",
    version="0.4.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization", "Idempotency-Key"],
)


@app.middleware("http")
async def apply_security_headers(request, call_next):
    """Apply defensive browser headers to API and health responses."""
    response = await call_next(request)
    if request.url.path.startswith(settings.api_prefix + "/"):
        response.headers.setdefault("Cache-Control", "private, no-store")
        response.headers.setdefault("Pragma", "no-cache")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    if settings.app_env == "production":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.post(f"{settings.api_prefix}/analytics/visit")
def analytics_record_visit(payload: SiteVisitRequest, response: Response):
    """Record one anonymous page view; the database deduplicates event retries."""
    try:
        stats = record_visit(
            settings, event_id=payload.event_id,
            visitor_token=payload.visitor_token, route_group=payload.route_group,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid analytics event.") from exc
    except SiteAnalyticsRateLimited as exc:
        raise HTTPException(status_code=429, detail="Visit counter limit reached. Please try again later.",
                            headers={"Retry-After": "60"}) from exc
    except SiteAnalyticsUnavailable as exc:
        raise HTTPException(status_code=503, detail="Visit counter is temporarily unavailable.") from exc
    response.headers["Cache-Control"] = "no-store"
    return stats


@app.get("/")
def root():
    return {"name": settings.app_name, "status": "ok", "docs": "/docs"}


@app.get(f"{settings.api_prefix}/health")
def health():
    provider = settings.ai_provider.strip().lower()
    ai_configured = (
        bool(settings.deepseek_api_key) if provider == "deepseek"
        else bool(settings.gemini_api_key) if provider == "gemini"
        else False
    )
    try:
        pricing_catalog_ready = bool(load_pricing_catalog(settings.pricing_catalog_json).rules)
    except PricingError:
        pricing_catalog_ready = False
    pricing_signing_ready = bool(
        settings.pricing_quote_signing_secret
        and len(settings.pricing_quote_signing_secret.encode("utf-8")) >= 32
    )
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.app_env,
        "ai_provider": provider,
        "ai_configured": ai_configured,
        "ai_capacity": settings.ai_max_concurrent_requests,
        "authentication_configured": bool(settings.supabase_url),
        "usage_telemetry_configured": bool(settings.supabase_url and settings.supabase_service_role_key),
        "generation_jobs_enabled": bool(settings.generation_jobs_enabled and settings.supabase_url and settings.supabase_service_role_key),
        "pricing_quote_signing_configured": pricing_signing_ready,
        "pricing_catalog_configured": pricing_catalog_ready,
        "generation_worker_ready": bool(settings.generation_job_worker_ready),
        "image_generation_configured": bool(settings.image_generation_provider and settings.image_generation_model),
    }



@app.post(f"{settings.api_prefix}/pricing/quotes", status_code=200)
def create_pricing_quote(
    payload: PricingQuoteRequest,
    response: Response,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
    user: StudioUser = Depends(get_current_user),
):
    """Return a short-lived, owner-bound quote; this endpoint never reserves or charges."""
    if not settings.pricing_quote_signing_secret or len(
        settings.pricing_quote_signing_secret.encode("utf-8")
    ) < 32:
        raise HTTPException(status_code=503, detail="Pricing quotes are not configured yet.")
    try:
        catalog = load_pricing_catalog(settings.pricing_catalog_json)
        if not catalog.rules:
            raise PricingError("No approved production prices are configured.")
        normalized_request_snapshot = dict(payload.request_snapshot)
        supplied_quantity = normalized_request_snapshot.get("quantity", payload.quantity)
        if (
            isinstance(supplied_quantity, bool)
            or not isinstance(supplied_quantity, int)
            or supplied_quantity != payload.quantity
        ):
            raise HTTPException(status_code=422, detail="Generation quantity does not match the request snapshot.")
        normalized_request_snapshot["quantity"] = payload.quantity
        request_hash = canonical_request_hash(normalized_request_snapshot)
        owner_id = UUID(user.user_id)
        quote = issue_pricing_quote(
            secret=settings.pricing_quote_signing_secret,
            catalog=catalog,
            user_id=owner_id,
            job_type=payload.job_type,
            provider=payload.provider,
            model=payload.model,
            request_hash=request_hash,
            idempotency_key=idempotency_key,
            project_id=payload.project_id,
            studio_scene_id=payload.studio_scene_id,
            quantity=payload.quantity,
        )
        persisted = store_pricing_quote(
            settings,
            user_id=owner_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            job_type=payload.job_type,
            provider=payload.provider,
            model=payload.model,
            project_id=payload.project_id,
            studio_scene_id=payload.studio_scene_id,
            quote_snapshot=quote.snapshot(),
        )
        if persisted.expired:
            raise HTTPException(
                status_code=409,
                detail="This idempotency key is bound to an expired quote. Start a new generation request with a new key.",
            )
        # Re-verify the exact persisted snapshot: on replay the database returns
        # the original quote, not the newly generated candidate.
        stored_quote = verify_pricing_quote(
            persisted.snapshot,
            secret=settings.pricing_quote_signing_secret,
            user_id=owner_id,
            job_type=payload.job_type,
            provider=payload.provider,
            model=payload.model,
            request_hash=request_hash,
            idempotency_key=idempotency_key,
            project_id=payload.project_id,
            studio_scene_id=payload.studio_scene_id,
        )
    except HTTPException:
        raise
    except PricingError as exc:
        raise HTTPException(status_code=503, detail="The requested generation price is not available.") from exc
    except GenerationPricingQuoteConflictError as exc:
        raise HTTPException(status_code=409, detail="This idempotency key is already bound to a different generation request.") from exc
    except (GenerationJobsNotConfiguredError, GenerationJobsServiceError) as exc:
        raise HTTPException(status_code=503, detail="Pricing quote storage is not available.") from exc
    response.headers["Cache-Control"] = "private, no-store"
    return stored_quote.snapshot()

@app.get(f"{settings.api_prefix}/jobs/{{job_id}}")
def generation_job_status(
    job_id: UUID,
    user: StudioUser = Depends(get_current_user),
):
    if not settings.generation_jobs_enabled:
        raise HTTPException(status_code=503, detail="Generation job status is not enabled yet.")
    try:
        job = get_generation_job(
            settings,
            user_id=UUID(user.user_id),
            job_id=job_id,
        )
    except GenerationJobsNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except GenerationJobsServiceError as exc:
        raise HTTPException(status_code=502, detail="Could not load generation job status.") from exc

    if job is None:
        # Do not reveal whether a job with this id belongs to another account.
        raise HTTPException(status_code=404, detail="Generation job was not found.")
    return job


@app.post(f"{settings.api_prefix}/scenes/{{scene_id}}/image-jobs", status_code=202)
def create_scene_image_job(
    scene_id: UUID,
    payload: SceneImageJobRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
    user: StudioUser = Depends(get_current_user),
):
    # Fail closed: never enqueue work without a durable dispatcher/worker.
    if not settings.generation_jobs_enabled:
        raise HTTPException(status_code=503, detail="Image generation jobs are not enabled yet.")
    if not settings.generation_job_worker_ready:
        raise HTTPException(status_code=503, detail="Image generation is not available yet: the background processing worker is not ready.")
    provider = (settings.image_generation_provider or "").strip()
    model = (settings.image_generation_model or "").strip()
    if not provider or not model:
        raise HTTPException(status_code=503, detail="Image generation is not configured yet. No image provider has been selected.")
    check_content(payload.prompt)
    if payload.negative_prompt:
        check_content(payload.negative_prompt)
    request_snapshot = {
        "prompt": payload.prompt,
        "negative_prompt": payload.negative_prompt,
        "width": payload.width,
        "height": payload.height,
        "seed": payload.seed,
    }
    canonical_request = json.dumps(
        {"scene_id": str(scene_id), "job_type": "image_generation", "provider": provider, "model": model, "request": request_snapshot},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    request_hash = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    try:
        owner_id = UUID(user.user_id)
        result = create_scene_generation_job(
            settings, user_id=owner_id, studio_scene_id=scene_id,
            job_type="image_generation", provider=provider, model=model,
            idempotency_key=idempotency_key, request_hash=request_hash,
            request_snapshot=request_snapshot,
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="The sign-in identity is invalid.") from exc
    except GenerationJobsNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail="Image generation jobs are not configured.") from exc
    except GenerationJobsServiceError as exc:
        raise HTTPException(status_code=502, detail="Could not create the image generation job.") from exc
    return {
        "job_id": str(result.job_id),
        "event_id": str(result.event_id) if result.event_id else None,
        "scene_id": str(scene_id),
        "status": "queued",
        "created": result.created,
    }

@app.get(f"{settings.api_prefix}/credits/wallet", response_model=CreditWalletResponse)
def get_my_credit_wallet(
    response: Response,
    user: StudioUser = Depends(get_current_user),
):
    """Read the authenticated user's wallet, active holds, and recent ledger."""
    try:
        snapshot = get_credit_wallet_snapshot(
            settings, user_id=UUID(user.user_id), history_limit=50
        )
    except CreditWalletNotConfigured as exc:
        raise HTTPException(status_code=503, detail="Credit wallet is not configured yet.") from exc
    except CreditWalletUnavailable as exc:
        raise HTTPException(status_code=503, detail="Credit wallet is temporarily unavailable.") from exc

    response.headers["Cache-Control"] = "private, no-store"
    return {
        "user_id": str(snapshot.user_id),
        "currency_unit": "credit",
        "available_credits": snapshot.available_credits,
        "reserved_credits": snapshot.reserved_credits,
        "total_credits": snapshot.available_credits + snapshot.reserved_credits,
        "holds": snapshot.holds,
        "ledger": snapshot.ledger,
        "lots": snapshot.lots,
        "allocations": snapshot.allocations,
    }


@app.get(f"{settings.api_prefix}/auth/me")
def auth_me(user: StudioUser = Depends(get_current_user)):
    return {"id": user.user_id, "email": user.email, "role": user.role}


@app.get(f"{settings.api_prefix}/admin/me")
def admin_me(user: StudioUser = Depends(require_admin)):
    _audit_admin_read(user, resource_type="platform", reason="Viewed administrator identity and access status")
    return {"id": user.user_id, "email": user.email, "role": user.role, "access": "owner"}


@app.get(f"{settings.api_prefix}/admin/ai/providers")
def admin_ai_provider_status(
    response: Response,
    user: StudioUser = Depends(require_permission("admin.platform.overview.read")),
):
    """Expose safe provider readiness metadata only; never expose keys or billing secrets."""
    selected = settings.ai_provider
    providers = [
        {
            "id": "deepseek",
            "label": "DeepSeek",
            "supported": True,
            "selected": selected == "deepseek",
            "model": settings.ai_model if selected == "deepseek" else "deepseek-flash",
            "api_key_configured": bool(settings.deepseek_api_key),
            "pricing_mode": "paid_api",
            "free_tier_eligible": False,
        },
        {
            "id": "gemini",
            "label": "Google Gemini",
            "supported": True,
            "selected": selected == "gemini",
            "model": settings.ai_model if selected == "gemini" else "gemini-3.1-flash-lite",
            "api_key_configured": bool(settings.gemini_api_key),
            "pricing_mode": "google_free_tier_eligible",
            "free_tier_eligible": True,
            "project_free_tier_verified": False,
            "billing_tier_verifiable": False,
        },
    ]
    _audit_admin_read(user, resource_type="platform", reason="Viewed AI provider readiness")
    response.headers["Cache-Control"] = "private, no-store"
    return {
        "selected_provider": selected,
        "selected_model": settings.ai_model,
        "ai_ready": bool(
            settings.deepseek_api_key if selected == "deepseek" else settings.gemini_api_key
        ),
        "automatic_fallback": False,
        "runtime_provider_switching": False,
        "admission_limits": {
            "requests_per_user_per_minute": settings.ai_max_requests_per_minute_per_user,
            "requests_per_user_per_24h": settings.ai_max_requests_per_day_per_user,
            "requests_global_per_24h": settings.ai_max_requests_per_day_global,
            "concurrent_per_user": settings.ai_max_concurrent_requests_per_user,
            "concurrent_global": settings.ai_max_global_concurrent_requests,
            "output_tokens_per_request": settings.ai_max_output_tokens,
        },
        "providers": providers,
        "safety_note": (
            "Gemini 3.1 Flash-Lite is listed as Free Tier eligible by Google, but actual project "
            "quota and billing tier cannot be verified by this backend. Google may change quotas, and some projects may not be eligible for the free tier. "
            "Free-tier data may be used to improve Google products. Provider changes require a "
            "controlled backend configuration update and redeployment."
        ),
    }


@app.get(f"{settings.api_prefix}/admin/ai/budget")
def admin_ai_cost_budget_status(
    response: Response,
    user: StudioUser = Depends(require_permission("admin.platform.overview.read")),
):
    """Owner-only view of atomic synchronous AI spend reservations and remaining USD budgets."""
    try:
        report = get_admin_ai_cost_budget_report(settings)
    except AICostBudgetReportNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail="AI cost budget reporting is not configured.") from exc
    except AICostBudgetReportError as exc:
        raise HTTPException(status_code=502, detail="AI cost budget status is temporarily unavailable.") from exc
    _audit_admin_read(user, resource_type="platform", reason="Viewed synchronous AI cost budget status")
    response.headers["Cache-Control"] = "private, no-store"
    return report



class AdminAIGlobalBudgetUpdate(BaseModel):
    enabled: bool
    daily_budget_usd: Decimal = Field(gt=0, le=1000000000)
    max_outstanding_usd: Decimal = Field(gt=0, le=1000000000)


class AdminAIProviderBudgetUpdate(BaseModel):
    provider: str
    enabled: bool
    daily_budget_usd: Decimal = Field(gt=0, le=1000000000)


class AdminAIReservationResolution(BaseModel):
    request_id: UUID
    resolution: str
    actual_estimated_cost_usd: Decimal | None = Field(default=None, ge=0, le=1000000000)
    note: str = Field(min_length=8, max_length=1000)


def _audit_ai_budget_change(user: StudioUser, *, reason: str) -> None:
    try:
        record_admin_audit_event(
            settings, actor_user_id=UUID(user.user_id),
            action="admin.security.settings.changed", outcome="requested",
            resource_type="security_setting", reason=reason,
        )
    except (AdminAuditUnavailable, ValueError) as exc:
        raise HTTPException(status_code=503, detail="AI budget change audit is unavailable; no change was accepted.") from exc


@app.put(f"{settings.api_prefix}/admin/ai/budget/global")
def admin_update_ai_global_budget(
    payload: AdminAIGlobalBudgetUpdate,
    user: StudioUser = Depends(require_permission("admin.platform.overview.read")),
):
    if payload.max_outstanding_usd > payload.daily_budget_usd:
        raise HTTPException(status_code=422, detail="Outstanding exposure cannot exceed the global daily budget.")
    _audit_ai_budget_change(user, reason=f"Requested global AI USD budget change: enabled={payload.enabled}, daily={payload.daily_budget_usd}, outstanding={payload.max_outstanding_usd}")
    try:
        result = update_global_budget(
            settings, enabled=payload.enabled,
            daily_budget_usd=payload.daily_budget_usd,
            max_outstanding_usd=payload.max_outstanding_usd,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid global AI budget settings.") from exc
    except AIBudgetControlNotConfigured as exc:
        raise HTTPException(status_code=503, detail="AI budget controls are not configured.") from exc
    except AIBudgetControlError as exc:
        raise HTTPException(status_code=502, detail="Global AI budget update failed safely.") from exc
    return {"updated": True, "settings": result}


@app.put(f"{settings.api_prefix}/admin/ai/budget/provider")
def admin_update_ai_provider_budget(
    payload: AdminAIProviderBudgetUpdate,
    user: StudioUser = Depends(require_permission("admin.platform.overview.read")),
):
    _audit_ai_budget_change(user, reason=f"Requested {payload.provider} daily AI USD budget change: enabled={payload.enabled}, daily={payload.daily_budget_usd}")
    try:
        result = update_provider_budget(
            settings, provider=payload.provider, enabled=payload.enabled,
            daily_budget_usd=payload.daily_budget_usd,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid provider AI budget settings.") from exc
    except AIBudgetControlNotConfigured as exc:
        raise HTTPException(status_code=503, detail="AI budget controls are not configured.") from exc
    except AIBudgetControlError as exc:
        raise HTTPException(status_code=502, detail="Provider AI budget update failed safely.") from exc
    return {"updated": True, "settings": result}


@app.post(f"{settings.api_prefix}/admin/ai/budget/reservations/resolve")
def admin_resolve_ai_budget_reservation(
    payload: AdminAIReservationResolution,
    user: StudioUser = Depends(require_permission("admin.platform.overview.read")),
):
    _audit_ai_budget_change(user, reason=f"Requested reconciliation of unknown AI reservation {payload.request_id}: {payload.resolution}; {payload.note.strip()}")
    try:
        resolved = resolve_unknown_reservation(
            settings, request_id=payload.request_id, resolution=payload.resolution,
            actual_estimated_cost_usd=payload.actual_estimated_cost_usd, note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid reservation reconciliation details.") from exc
    except AIBudgetControlNotConfigured as exc:
        raise HTTPException(status_code=503, detail="AI budget controls are not configured.") from exc
    except AIBudgetControlError as exc:
        raise HTTPException(status_code=502, detail="Reservation reconciliation failed safely.") from exc
    if not resolved:
        raise HTTPException(status_code=409, detail="Reservation was not found or is no longer unresolved.")
    return {"resolved": True, "request_id": str(payload.request_id), "resolution": payload.resolution}


@app.get(f"{settings.api_prefix}/admin/ai/usage")
def admin_ai_usage_report(
    date_from: date,
    date_to: date,
    response: Response,
    user: StudioUser = Depends(require_permission("admin.platform.overview.read")),
):
    """Owner-only aggregate AI request and token usage; no prompts or user IDs."""
    try:
        report = get_admin_ai_usage_report(settings, date_from=date_from, date_to=date_to)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="The AI usage date range is invalid or exceeds 31 days.") from exc
    except AIUsageReportNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail="AI usage reporting is not configured.") from exc
    except AIUsageReportError as exc:
        raise HTTPException(status_code=502, detail="AI usage report is temporarily unavailable.") from exc
    budgets = {
        "deepseek": settings.ai_daily_budget_usd_deepseek,
        "gemini": settings.ai_daily_budget_usd_gemini,
    }
    daily_rows = {
        row["provider"]: row for row in report.get("today_by_provider", [])
        if isinstance(row, dict) and isinstance(row.get("provider"), str)
    }
    budget_status = []
    today_utc = datetime.now(timezone.utc).date()
    today_in_report = date_from <= today_utc <= date_to
    for provider, configured_budget in budgets.items():
        row = daily_rows.get(provider, {})
        try:
            spend = Decimal(str(row.get("reported_estimated_cost_usd", "0")))
        except (InvalidOperation, ValueError):
            spend = Decimal("0")
        unknown_events = int(row.get("cost_unknown_events", 0) or 0)
        item = {
            "provider": provider,
            "daily_budget_usd": format(configured_budget, "f") if configured_budget is not None else None,
            "estimated_spend_usd": format(spend, "f"),
            "unknown_cost_events": unknown_events,
            "utilization_percent": None,
            "status": "unconfigured",
        }
        if configured_budget is not None and not today_in_report:
            item["status"] = "outside_report_period"
        elif configured_budget is not None:
            item["utilization_percent"] = round(float(spend / configured_budget * 100), 2)
            if unknown_events:
                item["status"] = "unknown_costs"
            elif spend >= configured_budget:
                item["status"] = "threshold_reached"
            elif spend >= configured_budget * Decimal("0.8"):
                item["status"] = "warning"
            else:
                item["status"] = "within_limit"
        budget_status.append(item)
    report["daily_budget_status"] = budget_status
    report["budget_status_note"] = (
        "These are warning thresholds based on recorded LiteLLM estimates, not a hard billing cap. "
        "Unknown-cost events make utilization incomplete. Actual charges must be reconciled with provider invoices."
    )
    _audit_admin_read(user, resource_type="platform", reason="Viewed aggregate AI usage report")
    response.headers["Cache-Control"] = "private, no-store"
    return report


@app.get(f"{settings.api_prefix}/admin/analytics/site-visits")
def admin_site_visit_stats(
    response: Response,
    user: StudioUser = Depends(require_permission("admin.analytics.read")),
):
    """Owner-only aggregate analytics endpoint."""
    try:
        stats = get_admin_visit_stats(settings)
    except SiteAnalyticsUnavailable as exc:
        raise HTTPException(status_code=503, detail="Visit analytics is not configured.") from exc
    _audit_admin_read(user, resource_type="platform", reason="Viewed aggregate site analytics")
    response.headers["Cache-Control"] = "private, no-store"
    return stats


@app.get(f"{settings.api_prefix}/admin/financial/provider-costs")
def admin_provider_cost_report(
    date_from: date,
    date_to: date,
    response: Response,
    user: StudioUser = Depends(require_permission("admin.finance.costs.read")),
):
    """Read-only operational cost report; never exposes raw usage metadata."""
    try:
        report = get_provider_cost_report(
            settings, date_from=date_from, date_to=date_to
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="The report date range is invalid or exceeds 31 days.",
        ) from exc
    except ProviderCostReportNotConfiguredError as exc:
        raise HTTPException(
            status_code=503, detail="Provider cost reporting is not configured."
        ) from exc
    except ProviderCostReportError as exc:
        raise HTTPException(
            status_code=502, detail="Provider cost report is temporarily unavailable."
        ) from exc
    _audit_admin_read(user, resource_type="platform", reason="Viewed provider cost report")
    response.headers["Cache-Control"] = "private, no-store"
    return report



@app.get(f"{settings.api_prefix}/admin/financial/wallets/{{target_user_id}}")
def admin_user_wallet_summary(
    target_user_id: UUID,
    response: Response,
    user: StudioUser = Depends(require_permission("admin.finance.wallets.read")),
):
    """Read a minimal user wallet summary; the access itself is audited."""
    try:
        snapshot = get_credit_wallet_snapshot(
            settings, user_id=target_user_id, history_limit=1
        )
    except CreditWalletNotConfigured as exc:
        raise HTTPException(status_code=503, detail="Credit wallet reporting is not configured.") from exc
    except CreditWalletUnavailable as exc:
        raise HTTPException(status_code=503, detail="Credit wallet reporting is temporarily unavailable.") from exc
    try:
        record_admin_audit_event(
            settings,
            actor_user_id=UUID(user.user_id),
            action="admin.user.view",
            outcome="allowed",
            resource_type="credit_wallet",
            resource_id=target_user_id,
            reason="Viewed user credit wallet summary",
        )
    except AdminAuditUnavailable as exc:
        # Do not disclose financial data if the access cannot be audited.
        raise HTTPException(status_code=503, detail="Financial access audit is temporarily unavailable.") from exc
    response.headers["Cache-Control"] = "private, no-store"
    return {
        "user_id": str(snapshot.user_id),
        "currency_unit": "credit",
        "available_credits": snapshot.available_credits,
        "reserved_credits": snapshot.reserved_credits,
        "total_credits": snapshot.available_credits + snapshot.reserved_credits,
        "active_holds_count": len(snapshot.holds),
        "lot_count": snapshot.lot_count,
        "allocation_count": snapshot.allocation_count,
    }


@app.get(f"{settings.api_prefix}/admin/financial/ledger/{'{target_user_id}'}")
def admin_user_credit_ledger(
    target_user_id: UUID,
    response: Response,
    before_created_at: datetime | None = None,
    before_id: int | None = None,
    limit: int = 50,
    user: StudioUser = Depends(require_permission("admin.finance.wallets.read")),
):
    """Read a bounded page of one user's credit-unit ledger; every read is audited."""
    if not 1 <= limit <= 100:
        raise HTTPException(status_code=422, detail="Ledger page limit must be between 1 and 100.")
    if (before_created_at is None) != (before_id is None):
        raise HTTPException(status_code=422, detail="Ledger cursor requires timestamp and entry ID.")
    if before_created_at is not None and before_created_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="Ledger cursor timestamp must include a timezone.")
    try:
        entries = list_admin_credit_ledger(
            settings, user_id=target_user_id,
            before_created_at=before_created_at, before_id=before_id, limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid ledger query.") from exc
    except AdminCreditLedgerUnavailable as exc:
        raise HTTPException(status_code=503, detail="Credit ledger is temporarily unavailable.") from exc
    try:
        record_admin_audit_event(
            settings, actor_user_id=UUID(user.user_id),
            action="admin.user.view", outcome="allowed",
            resource_type="credit_ledger", resource_id=target_user_id,
            reason="Viewed user credit ledger page",
        )
    except AdminAuditUnavailable as exc:
        raise HTTPException(status_code=503, detail="Financial access audit is temporarily unavailable.") from exc
    next_cursor = None
    if len(entries) == limit:
        last = entries[-1]
        next_cursor = {"before_created_at": last["created_at"], "before_id": last["entry_id"]}
    response.headers["Cache-Control"] = "private, no-store"
    return {
        "user_id": str(target_user_id),
        "unit": "credit",
        "entries": entries,
        "next_cursor": next_cursor,
        "accounting_note": "Credit units only; this is not a cash, payment, revenue, or profit report.",
    }


@app.get(f"{settings.api_prefix}/admin/audit-events")
def admin_audit_events(
    response: Response,
    before: datetime | None = None,
    before_id: UUID | None = None,
    limit: int = 100,
    user: StudioUser = Depends(require_permission("admin.security.audit.read")),
):
    """Read a bounded, secret-free page from the append-only admin journal."""
    if not 1 <= limit <= 200:
        raise HTTPException(status_code=422, detail="Audit page limit must be between 1 and 200.")
    if (before is None) != (before_id is None):
        raise HTTPException(status_code=422, detail="Audit cursor requires both timestamp and event ID.")
    if before is not None and before.tzinfo is None:
        raise HTTPException(status_code=422, detail="Audit cursor must include a timezone.")
    try:
        # Identity comes only from the verified JWT principal, never request input.
        events = get_admin_audit_events(settings, before=before, before_id=before_id, limit=limit)
        record_admin_audit_event(
            settings,
            actor_user_id=UUID(user.user_id),
            action="admin.access",
            outcome="allowed",
            resource_type="platform",
            reason="Viewed administrative audit journal",
        )
    except AdminAuditUnavailable as exc:
        raise HTTPException(status_code=503, detail="Administrative audit journal is temporarily unavailable.") from exc
    response.headers["Cache-Control"] = "private, no-store"
    next_cursor = (
        {"before": events[-1]["occurred_at"], "before_id": events[-1]["id"]}
        if len(events) == limit else None
    )
    return {"events": events, "limit": limit, "next_cursor": next_cursor}


@app.get(f"{settings.api_prefix}/admin/finance/roles/{{target_user_id}}")
def admin_list_finance_roles(
    target_user_id: UUID,
    response: Response,
    user: StudioUser = Depends(require_permission("admin.finance.roles.manage")),
):
    """Read active delegated roles; only the explicit owner role manager may inspect them."""
    try:
        assignments = list_active_finance_roles(settings, principal_id=target_user_id)
        record_admin_audit_event(
            settings, actor_user_id=UUID(user.user_id), action="admin.access",
            outcome="allowed", resource_type="permission",
            resource_id=target_user_id, reason="Viewed active finance role assignments",
        )
    except FinanceRegistryNotConfigured as exc:
        raise HTTPException(status_code=503, detail="Finance role registry is not configured.") from exc
    except FinanceRegistryUnavailable as exc:
        raise HTTPException(status_code=503, detail="Finance role registry is temporarily unavailable.") from exc
    except AdminAuditUnavailable as exc:
        raise HTTPException(status_code=503, detail="Finance role access audit is temporarily unavailable.") from exc
    response.headers["Cache-Control"] = "private, no-store"
    return {"assignments": [{
        "assignment_id": str(item.assignment_id),
        "principal_id": str(item.principal_id),
        "role_code": item.role_code,
        "scope_key": item.scope_key,
        "valid_from": item.valid_from.isoformat(),
        "valid_until": item.valid_until.isoformat() if item.valid_until else None,
        "granted_by": str(item.granted_by),
        "created_at": item.created_at.isoformat(),
    } for item in assignments]}


@app.post(f"{settings.api_prefix}/admin/finance/roles")
def admin_grant_finance_role(
    payload: FinanceRoleGrantRequest,
    response: Response,
    user: StudioUser = Depends(require_permission("admin.finance.roles.manage")),
):
    """Grant a scoped delegated role; actor identity comes only from verified JWT."""
    try:
        assignment_id = grant_finance_role(
            settings,
            principal_id=payload.principal_id,
            role_code=payload.role_code,
            scope_key=payload.scope_key,
            valid_until=payload.valid_until,
            granted_by=UUID(user.user_id),
            reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Finance role assignment is invalid.") from exc
    except FinanceRoleConflict as exc:
        raise HTTPException(status_code=409, detail="An active assignment for this role and scope already exists.") from exc
    except FinanceRegistryNotConfigured as exc:
        raise HTTPException(status_code=503, detail="Finance role registry is not configured.") from exc
    except FinanceRegistryUnavailable as exc:
        raise HTTPException(status_code=503, detail="Finance role registry is temporarily unavailable.") from exc
    response.headers["Cache-Control"] = "private, no-store"
    return {"assignment_id": str(assignment_id), "status": "granted"}


@app.post(f"{settings.api_prefix}/admin/finance/roles/{{assignment_id}}/revoke")
def admin_revoke_finance_role(
    assignment_id: UUID,
    payload: FinanceRoleRevocationRequest,
    response: Response,
    user: StudioUser = Depends(require_permission("admin.finance.roles.manage")),
):
    """Append a revocation; the original role assignment remains immutable."""
    try:
        revocation_id = revoke_finance_role(
            settings, assignment_id=assignment_id,
            revoked_by=UUID(user.user_id), reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Finance role revocation is invalid.") from exc
    except FinanceRegistryNotConfigured as exc:
        raise HTTPException(status_code=503, detail="Finance role registry is not configured.") from exc
    except FinanceRegistryUnavailable as exc:
        raise HTTPException(status_code=503, detail="Finance role registry is temporarily unavailable.") from exc
    response.headers["Cache-Control"] = "private, no-store"
    return {"revocation_id": str(revocation_id), "status": "revoked"}



def _finance_target_scope(target_user_id: UUID) -> str:
    """Current finance scope is per-user until a trusted tenant membership model exists."""
    return f"user:{target_user_id}"


@app.get(f"{settings.api_prefix}/finance/me")
def finance_current_access(response: Response, user: StudioUser = Depends(get_current_user)):
    """Return the caller's own delegated finance capabilities without exposing scope identifiers."""
    try:
        grant = resolve_finance_grant(settings, principal_id=UUID(user.user_id))
    except FinanceRegistryNotConfigured as exc:
        raise HTTPException(status_code=503, detail="Finance authorization is not configured.") from exc
    except FinanceRegistryUnavailable as exc:
        raise HTTPException(status_code=503, detail="Finance authorization is temporarily unavailable.") from exc
    if grant is None or not grant.active or grant.principal_id != UUID(user.user_id):
        response.headers["Cache-Control"] = "private, no-store"
        return {"active": False, "permissions": [], "scope_count": 0}
    response.headers["Cache-Control"] = "private, no-store"
    return {
        "active": True,
        "permissions": sorted(grant.permissions),
        "scope_count": len(grant.scope_ids),
        "can_read_credit_requests": bool(grant.permission_scopes.get("credit.compensation.read")),
        "can_read_refund_requests": bool(grant.permission_scopes.get("billing.refund.read")),
    }


def _finance_request_read_scopes(user: StudioUser) -> tuple[list[str], list[str]]:
    try:
        actor_id = UUID(user.user_id)
        grant = resolve_finance_grant(settings, principal_id=actor_id)
        if grant is None or not grant.active or grant.principal_id != actor_id:
            raise FinanceAuthorizationDenied("No active finance assignment.")
        resolved: dict[str, list[str]] = {}
        for request_type, permission in (
            ("credit_compensation", "credit.compensation.read"),
            ("billing_refund", "billing.refund.read"),
        ):
            allowed: list[str] = []
            for scope in grant.permission_scopes.get(permission, frozenset()):
                if not isinstance(scope, str) or not scope.startswith("user:"):
                    continue
                try:
                    target_id = UUID(scope[5:])
                except (ValueError, TypeError, AttributeError):
                    continue
                if scope != _finance_target_scope(target_id):
                    continue
                require_finance_permission(
                    grant, actor_id=actor_id, permission=permission, target_scope=scope,
                )
                allowed.append(scope)
            resolved[request_type] = sorted(set(allowed))
        if not resolved["credit_compensation"] and not resolved["billing_refund"]:
            raise FinanceAuthorizationDenied("No finance request read scope.")
        return resolved["credit_compensation"], resolved["billing_refund"]
    except FinanceAuthorizationDenied as exc:
        raise HTTPException(status_code=403, detail="Finance request access is not permitted.") from exc
    except FinanceRegistryNotConfigured as exc:
        raise HTTPException(status_code=503, detail="Finance authorization is not configured.") from exc
    except FinanceRegistryUnavailable as exc:
        raise HTTPException(status_code=503, detail="Finance authorization is temporarily unavailable.") from exc


def _require_finance_action(user: StudioUser, *, request_type: str, action: str, scope_key: str) -> None:
    prefix = "credit.compensation" if request_type == "credit_compensation" else "billing.refund"
    try:
        grant = resolve_finance_grant(settings, principal_id=UUID(user.user_id))
        require_finance_permission(
            grant, actor_id=UUID(user.user_id),
            permission=f"{prefix}.{action}", target_scope=scope_key,
        )
    except FinanceAuthorizationDenied as exc:
        raise HTTPException(status_code=403, detail="This finance operation is not permitted.") from exc
    except FinanceRegistryNotConfigured as exc:
        raise HTTPException(status_code=503, detail="Finance authorization is not configured.") from exc
    except FinanceRegistryUnavailable as exc:
        raise HTTPException(status_code=503, detail="Finance authorization is temporarily unavailable.") from exc


@app.get(f"{settings.api_prefix}/finance/requests")
def finance_request_queue(
    response: Response,
    status: str | None = None,
    limit: int = 50,
    before: datetime | None = None,
    before_id: UUID | None = None,
    user: StudioUser = Depends(get_current_user),
):
    """Read a bounded finance queue restricted to the actor's delegated scopes."""
    if status is not None and status not in {"pending", "approved", "rejected", "cancelled"}:
        raise HTTPException(status_code=422, detail="Finance request status is invalid.")
    if isinstance(limit, bool) or not 1 <= limit <= 100:
        raise HTTPException(status_code=422, detail="Finance request page size is invalid.")
    if (before is None) != (before_id is None) or (before is not None and before.tzinfo is None):
        raise HTTPException(status_code=422, detail="A complete timezone-aware queue cursor is required.")
    credit_scopes, billing_scopes = _finance_request_read_scopes(user)
    try:
        rows = list_finance_operation_requests(
            settings, credit_scope_keys=credit_scopes, billing_scope_keys=billing_scopes,
            status=status, before=before, before_id=before_id, limit=limit + 1,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Finance queue query is invalid.") from exc
    except FinanceRequestNotConfigured as exc:
        raise HTTPException(status_code=503, detail="Finance request storage is not configured.") from exc
    except FinanceRequestUnavailable as exc:
        raise HTTPException(status_code=503, detail="Finance request queue is temporarily unavailable.") from exc
    has_more = len(rows) > limit
    page = rows[:limit]
    response.headers["Cache-Control"] = "private, no-store"
    return {
        "items": [{
            "request_id": str(item["request_id"]),
            "requester_id": str(item["requester_id"]),
            "request_type": item["request_type"],
            "target_user_id": str(item["target_user_id"]),
            "amount": format(item["amount"], "f"),
            "currency_code": item["currency_code"],
            "reason": item["reason"],
            "status": item["status"],
            "requested_at": item["requested_at"].isoformat(),
            "decided_by": str(item["decided_by"]) if item["decided_by"] else None,
            "decided_at": item["decided_at"].isoformat() if item["decided_at"] else None,
            "decision_reason": item["decision_reason"],
            "cancelled_at": item["cancelled_at"].isoformat() if item["cancelled_at"] else None,
        } for item in page],
        "limit": limit,
        "next_cursor": ({
            "before": page[-1]["requested_at"].isoformat(),
            "before_id": str(page[-1]["request_id"]),
        } if has_more and page else None),
        "execution_enabled": False,
    }


@app.get(f"{settings.api_prefix}/finance/requests/{{request_id}}/events")
def finance_request_events(
    request_id: UUID,
    response: Response,
    user: StudioUser = Depends(get_current_user),
):
    """Read an append-only request timeline only within the caller's delegated scope."""
    try:
        item = read_finance_operation_request(settings, request_id=request_id)
    except FinanceRequestNotFound as exc:
        raise HTTPException(status_code=404, detail="Finance request was not found.") from exc
    except FinanceRequestNotConfigured as exc:
        raise HTTPException(status_code=503, detail="Finance request storage is not configured.") from exc
    except FinanceRequestUnavailable as exc:
        raise HTTPException(status_code=503, detail="Finance request storage is temporarily unavailable.") from exc
    if item["scope_key"] != _finance_target_scope(item["target_user_id"]):
        raise HTTPException(status_code=403, detail="Finance request scope does not match its target.")
    _require_finance_action(
        user, request_type=item["request_type"], action="read", scope_key=item["scope_key"],
    )
    try:
        events = read_finance_operation_request_events(settings, request_id=request_id)
    except FinanceRequestNotConfigured as exc:
        raise HTTPException(status_code=503, detail="Finance request storage is not configured.") from exc
    except FinanceRequestUnavailable as exc:
        raise HTTPException(status_code=503, detail="Finance request timeline is temporarily unavailable.") from exc
    response.headers["Cache-Control"] = "private, no-store"
    return {"request_id": str(request_id), "events": [{
        "event_id": str(event["event_id"]),
        "actor_id": str(event["actor_id"]),
        "event_type": event["event_type"],
        "previous_status": event["previous_status"],
        "new_status": event["new_status"],
        "reason": event["reason"],
        "occurred_at": event["occurred_at"].isoformat(),
    } for event in events]}


@app.post(f"{settings.api_prefix}/finance/requests", status_code=201)
def finance_request_create(
    payload: FinanceOperationRequestCreate,
    response: Response,
    user: StudioUser = Depends(get_current_user),
):
    """Create an idempotent finance proposal; this never moves money or credits."""
    target_scope = _finance_target_scope(payload.target_user_id)
    _require_finance_action(
        user, request_type=payload.request_type, action="request",
        scope_key=target_scope,
    )
    try:
        request_id = create_finance_operation_request(
            settings, requester_id=UUID(user.user_id),
            request_type=payload.request_type, target_user_id=payload.target_user_id,
            amount=payload.amount, currency_code=payload.currency_code,
            scope_key=target_scope, reason=payload.reason,
            idempotency_key=payload.idempotency_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Finance request is invalid.") from exc
    except FinanceRequestNotConfigured as exc:
        raise HTTPException(status_code=503, detail="Finance request storage is not configured.") from exc
    except FinanceRequestUnavailable as exc:
        raise HTTPException(status_code=503, detail="Finance request storage is temporarily unavailable.") from exc
    try:
        current_request = read_finance_operation_request(settings, request_id=request_id)
    except FinanceRequestNotFound as exc:
        raise HTTPException(status_code=503, detail="Finance request could not be read after creation.") from exc
    except FinanceRequestUnavailable as exc:
        raise HTTPException(status_code=503, detail="Finance request state is temporarily unavailable.") from exc
    response.headers["Cache-Control"] = "private, no-store"
    return {
        "request_id": str(request_id),
        "status": current_request["status"],
        "execution_enabled": False,
    }


@app.post(f"{settings.api_prefix}/finance/requests/{{request_id}}/decision")
def finance_request_decide(
    request_id: UUID,
    payload: FinanceOperationDecisionRequest,
    response: Response,
    user: StudioUser = Depends(get_current_user),
):
    """Approve or reject a pending request after checking the exact delegated scope."""
    try:
        item = read_finance_operation_request(settings, request_id=request_id)
    except FinanceRequestNotFound as exc:
        raise HTTPException(status_code=404, detail="Finance request was not found.") from exc
    except FinanceRequestNotConfigured as exc:
        raise HTTPException(status_code=503, detail="Finance request storage is not configured.") from exc
    except FinanceRequestUnavailable as exc:
        raise HTTPException(status_code=503, detail="Finance request storage is temporarily unavailable.") from exc
    if item["requester_id"] == UUID(user.user_id):
        raise HTTPException(status_code=403, detail="A requester cannot approve or reject their own finance request.")
    if item["scope_key"] != _finance_target_scope(item["target_user_id"]):
        raise HTTPException(status_code=403, detail="Finance request scope does not match its target.")
    _require_finance_action(
        user, request_type=item["request_type"], action="approve",
        scope_key=item["scope_key"],
    )
    try:
        decide_finance_operation_request(
            settings, request_id=request_id, actor_id=UUID(user.user_id),
            decision=payload.decision, reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Finance decision is invalid.") from exc
    except FinanceRequestConflict as exc:
        raise HTTPException(status_code=409, detail="Finance request is no longer pending.") from exc
    except FinanceRequestNotFound as exc:
        raise HTTPException(status_code=404, detail="Finance request was not found.") from exc
    except FinanceRequestUnavailable as exc:
        raise HTTPException(status_code=503, detail="Finance request storage is temporarily unavailable.") from exc
    response.headers["Cache-Control"] = "private, no-store"
    return {"request_id": str(request_id), "status": "approved" if payload.decision == "approve" else "rejected"}


@app.post(f"{settings.api_prefix}/finance/requests/{{request_id}}/cancel")
def finance_request_cancel(
    request_id: UUID,
    payload: FinanceOperationCancelRequest,
    response: Response,
    user: StudioUser = Depends(get_current_user),
):
    """Allow only the original requester to cancel their still-pending proposal."""
    try:
        item = read_finance_operation_request(settings, request_id=request_id)
    except FinanceRequestNotFound as exc:
        raise HTTPException(status_code=404, detail="Finance request was not found.") from exc
    except FinanceRequestNotConfigured as exc:
        raise HTTPException(status_code=503, detail="Finance request storage is not configured.") from exc
    except FinanceRequestUnavailable as exc:
        raise HTTPException(status_code=503, detail="Finance request storage is temporarily unavailable.") from exc
    if item["requester_id"] != UUID(user.user_id):
        raise HTTPException(status_code=404, detail="Finance request was not found.")
    if item["scope_key"] != _finance_target_scope(item["target_user_id"]):
        raise HTTPException(status_code=403, detail="Finance request scope does not match its target.")
    _require_finance_action(
        user, request_type=item["request_type"], action="cancel",
        scope_key=item["scope_key"],
    )
    try:
        cancel_finance_operation_request(
            settings, request_id=request_id, actor_id=UUID(user.user_id),
            reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Finance cancellation is invalid.") from exc
    except FinanceRequestConflict as exc:
        raise HTTPException(status_code=409, detail="Finance request is no longer pending.") from exc
    except FinanceRequestNotFound as exc:
        raise HTTPException(status_code=404, detail="Finance request was not found.") from exc
    except FinanceRequestUnavailable as exc:
        raise HTTPException(status_code=503, detail="Finance request storage is temporarily unavailable.") from exc
    response.headers["Cache-Control"] = "private, no-store"
    return {"request_id": str(request_id), "status": "cancelled"}


def _run_admitted_ai(operation: str, user_id: str, call):
    try:
        reservation = reserve_ai_request(
            settings, user_id=UUID(user_id), endpoint=operation
        )
    except AIAdmissionRejected as exc:
        if exc.reason == "daily_user_limit":
            detail = "Вы достигли дневного лимита AI-запросов. Лимит обновится по скользящему 24-часовому окну."
        elif exc.reason == "daily_global_limit":
            detail = "Дневной лимит AI-сервиса временно исчерпан. Попробуйте позже."
        else:
            detail = "Достигнут временный лимит AI-запросов. Попробуйте немного позже."
        raise HTTPException(
            status_code=429,
            detail=detail,
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except AIAdmissionUnavailable as exc:
        # Fail closed: do not make a billable provider call when the shared
        # admission store cannot prove that this account is within its limits.
        raise HTTPException(
            status_code=503,
            detail="Проверка доступности AI временно недоступна. Попробуйте позже.",
            headers={"Retry-After": "10"},
        ) from exc

    completed = False
    try:
        result = _run_ai(operation, call)
        completed = True
        return result
    finally:
        try:
            finish_ai_request(settings, reservation, completed=completed)
        except AIAdmissionUnavailable:
            # Reservations expire from the active-concurrency window after
            # five minutes; never log user content or provider credentials.
            logger.warning(
                "AI admission reservation finalization failed: endpoint=%s outcome=%s",
                operation,
                "completed" if completed else "released",
            )


def _run_ai(operation: str, call):
    try:
        return call()
    except AIProviderBudgetRejected as exc:
        if exc.reason == "input_size_limit":
            raise HTTPException(status_code=413, detail="Текст запроса слишком большой для безопасного расчёта стоимости.") from exc
        raise HTTPException(
            status_code=429,
            detail="Достигнут денежный лимит AI-сервиса. Попробуйте позже или обратитесь к администратору.",
            headers={"Retry-After": "300"},
        ) from exc
    except AIProviderBudgetUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail="Проверка денежного лимита AI временно недоступна. Запрос к провайдеру не выполнен.",
            headers={"Retry-After": "10"},
        ) from exc
    except AIConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AIOverloadedError as exc:
        raise HTTPException(
            status_code=503,
            detail="Сейчас много запросов к AI. Попробуйте ещё раз через несколько секунд.",
            headers={"Retry-After": "10"},
        ) from exc
    except Exception as exc:
        # Provider details and user content are deliberately not exposed to clients.
        raise HTTPException(
            status_code=502,
            detail=f"Не удалось завершить запрос к AI ({operation}). Попробуйте позже.",
        ) from exc


@app.post(f"{settings.api_prefix}/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, user: StudioUser = Depends(get_current_user)):
    check_content(payload.message)
    system = (
        "You are Studio AI Companion, a helpful creative assistant inside PWA Studio. "
        "Help users develop video ideas, scripts, scenes and prompts. Be clear and practical. "
        "Follow platform safety rules: do not assist sexual exploitation of minors, non-consensual "
        "intimate imagery, real-world violence, self-harm instructions, weapons construction, fraud, "
        "doxxing, harassment or malware. Respect consent for real people’s likenesses and voices. "
        "When a request is unsafe, briefly explain the boundary and offer a safe creative alternative."
    )
    result = _run_admitted_ai("chat", user.user_id, lambda: ask_ai(settings, [
        {"role": "system", "content": system},
        {"role": "user", "content": payload.message},
    ], user_id=UUID(user.user_id)))
    record_ai_usage(settings, user_id=user.user_id, request_id=getattr(result, "request_id", uuid4()), endpoint="chat",
                    provider=settings.ai_provider, result=result)
    return ChatResponse(reply=result.text, provider=settings.ai_provider, model=result.actual_model)


@app.post(f"{settings.api_prefix}/movie/script", response_model=MovieScriptResponse)
def generate_movie_script(payload: MovieScriptRequest, user: StudioUser = Depends(get_current_user)):
    """Generate an editable screenplay and shot-by-shot storyboard for Mini Movie Studio."""
    check_content(payload.title)
    check_content(payload.idea)
    system = (
        "You are the screenwriter and storyboard director of PWA Studio. "
        "Create an original, coherent, production-ready short-film screenplay and matching storyboard. "
        "Respect the requested duration and aspect ratio. Divide the film into practical scenes; "
        "for every scene include a concise slugline, action, visual description and dialogue where useful. "
        "The storyboard must map one-to-one to screenplay scenes and specify shot size, camera angle, "
        "camera movement, composition, lighting and transition. Keep visual continuity consistent. "
        "Avoid copyrighted character imitation, sexual exploitation of minors, non-consensual intimate imagery, "
        "real-world harm instructions, fraud, doxxing and deceptive impersonation. Respect consent for real "
        "people and their likenesses and voices. Return ONLY a valid JSON object with exactly two string fields: "
        "story and storyboard. Do not wrap JSON in markdown."
    )
    request = {"title": payload.title, "creative_idea": payload.idea, "genre": payload.genre,
               "target_duration_minutes": payload.duration_minutes, "frame_format": payload.frame,
               "output_language": payload.language}
    result = _run_admitted_ai("movie_script", user.user_id, lambda: ask_ai(settings, [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(request, ensure_ascii=False)},
    ], user_id=UUID(user.user_id)))
    record_ai_usage(settings, user_id=user.user_id, request_id=getattr(result, "request_id", uuid4()), endpoint="movie_script",
                    provider=settings.ai_provider, result=result)
    raw = result.text.strip()
    if raw.startswith(chr(96) * 3):
        raw = raw.split(chr(10), 1)[-1]
        if raw.endswith(chr(96) * 3): raw = raw[:-3].strip()
    try:
        data = json.loads(raw)
        story = data.get("story") if isinstance(data, dict) else None
        storyboard = data.get("storyboard") if isinstance(data, dict) else None
        if not isinstance(story, str) or not story.strip() or len(story) > 30000: raise ValueError("invalid_story")
        if not isinstance(storyboard, str) or not storyboard.strip() or len(storyboard) > 30000: raise ValueError("invalid_storyboard")
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=502, detail="AI не вернул сценарий в ожидаемом формате. Попробуйте повторить запрос.") from exc
    return MovieScriptResponse(story=story.strip(), storyboard=storyboard.strip(), provider=settings.ai_provider, model=result.actual_model)

@app.post(f"{settings.api_prefix}/movie/director", response_model=MovieDirectorResponse)
def direct_movie_scenes(payload: MovieDirectorRequest, user: StudioUser = Depends(get_current_user)):
    """Turn an approved screenplay into structured, editable production scenes."""
    check_content(payload.title)
    check_content(payload.story)
    system = (
        "You are the film director and production planner for PWA Studio. "
        "Break the supplied screenplay into a coherent sequence of shootable scenes. "
        "Preserve its plot, characters, and ending; do not invent unrelated subplots. "
        "Return ONLY a JSON object with one key 'scenes', an array of objects with exactly these keys: "
        "scene_number (integer starting at 1), title, location, time_of_day, estimated_seconds (integer), "
        "characters (array of strings), action, visual_description, camera_shots (array of 1-8 concise shots), "
        "lighting, transition. Make each scene visually specific and maintain character/location continuity. "
        "The total estimated_seconds should approximately match the requested film duration. "
        "Respect the requested aspect ratio. Avoid copyrighted character imitation, sexual exploitation of minors, "
        "non-consensual intimate imagery, real-world harm instructions, fraud, doxxing and deceptive impersonation. "
        "Respect consent for real people's likenesses and voices. Do not wrap JSON in markdown."
    )
    request = {"title": payload.title, "screenplay": payload.story, "genre": payload.genre,
               "target_duration_minutes": payload.duration_minutes, "frame_format": payload.frame,
               "output_language": payload.language}
    result = _run_admitted_ai("movie_director", user.user_id, lambda: ask_ai(settings, [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(request, ensure_ascii=False)},
    ], user_id=UUID(user.user_id)))
    record_ai_usage(settings, user_id=user.user_id, request_id=getattr(result, "request_id", uuid4()), endpoint="movie_director",
                    provider=settings.ai_provider, result=result)
    raw = result.text.strip()
    if raw.startswith(chr(96) * 3):
        raw = raw.split(chr(10), 1)[-1]
        if raw.endswith(chr(96) * 3): raw = raw[:-3].strip()
    try:
        data = json.loads(raw)
        if not isinstance(data, dict) or set(data) != {"scenes"} or not isinstance(data["scenes"], list):
            raise ValueError("invalid_scene_collection")
        scenes = [MovieDirectorScene.model_validate(item) for item in data["scenes"]]
        if not scenes or [scene.scene_number for scene in scenes] != list(range(1, len(scenes) + 1)):
            raise ValueError("invalid_scene_sequence")
        if sum(scene.estimated_seconds for scene in scenes) > payload.duration_minutes * 60 * 1.5:
            raise ValueError("scene_duration_exceeds_target")
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=502, detail="AI не вернул сцены в ожидаемом формате. Попробуйте повторить запрос.") from exc
    return MovieDirectorResponse(scenes=scenes, provider=settings.ai_provider, model=result.actual_model)


@app.post(f"{settings.api_prefix}/movie/storyboard", response_model=MovieStoryboardResponse)
def create_movie_storyboard(payload: MovieStoryboardRequest, user: StudioUser = Depends(get_current_user)):
    """Create a structured shot-by-shot storyboard from reviewed director scenes."""
    check_content(payload.title)
    for scene in payload.scenes:
        for value in (
            scene.title, scene.location, scene.action, scene.visual_description,
            scene.lighting, scene.transition, *scene.camera_shots,
        ):
            check_content(value)
        for character in scene.characters:
            check_content(character)
    system = (
        "You are a cinematographer and storyboard artist for PWA Studio. "
        "Create a practical visual storyboard for every supplied scene. Preserve the scene order, "
        "story beats, named characters, locations, props, and visual continuity. "
        "Return ONLY a JSON object with exactly two keys: 'characters' and 'scenes'. "
        "characters is a canonical character bible with one object per distinct named character, "
        "in first-appearance order. Each character object has exactly: name, appearance, wardrobe, "
        "signature_details, reference_prompt. Describe only story-supported, non-sensitive visible "
        "traits. reference_prompt is a reusable image-reference prompt that locks the character's "
        "face, age-appropriate appearance, hair, silhouette, wardrobe and distinctive details. "
        "Each scene object has scene_number and frames. Each frame has exactly: frame_number "
        "(starting at 1 within its scene), duration_seconds (integer), characters (array containing "
        "only names assigned to that source scene), shot_type, camera_angle, camera_movement, "
        "composition, subject_focus, visual_prompt, continuity_notes. Create 2-6 meaningful frames "
        "per scene, not repetitive variations. visual_prompt must be a self-contained image-generation prompt "
        "describing visible subjects, environment, action, framing, lighting, palette, mood, "
        "and requested aspect ratio. Do not include text, logos, watermarks, or UI in the image. "
        "Keep recurring characters visually consistent using concrete appearance descriptors based "
        "only on the supplied story; do not infer sensitive traits. Make total frame durations per "
        "scene plausible relative to estimated scene duration. Respect the requested visual style. "
        "Avoid copyrighted character imitation, sexual exploitation of minors, non-consensual intimate "
        "imagery, real-world harm instructions, fraud, doxxing and deceptive impersonation. "
        "Respect consent for real people's likenesses and voices. Do not wrap JSON in markdown."
    )
    request = {
        "title": payload.title,
        "aspect_ratio": payload.frame,
        "visual_style": payload.visual_style,
        "output_language": payload.language,
        "scenes": [scene.model_dump() for scene in payload.scenes],
    }
    result = _run_admitted_ai("movie_storyboard", user.user_id, lambda: ask_ai(settings, [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(request, ensure_ascii=False)},
    ], user_id=UUID(user.user_id)))
    record_ai_usage(settings, user_id=user.user_id, request_id=getattr(result, "request_id", uuid4()), endpoint="movie_storyboard",
                    provider=settings.ai_provider, result=result)
    raw = result.text.strip()
    if raw.startswith(chr(96) * 3):
        raw = raw.split(chr(10), 1)[-1]
        if raw.endswith(chr(96) * 3): raw = raw[:-3].strip()
    try:
        data = json.loads(raw)
        if not isinstance(data, dict) or set(data) != {"characters", "scenes"}:
            raise ValueError("invalid_storyboard_collection")
        if not isinstance(data["characters"], list) or not isinstance(data["scenes"], list):
            raise ValueError("invalid_storyboard_collection")
        characters = [MovieCharacterReference.model_validate(item) for item in data["characters"]]
        scenes = [MovieStoryboardScene.model_validate(item) for item in data["scenes"]]
        expected_numbers = [scene.scene_number for scene in payload.scenes]
        if [scene.scene_number for scene in scenes] != expected_numbers:
            raise ValueError("storyboard_scene_mismatch")
        expected_characters = list(dict.fromkeys(
            name for source_scene in payload.scenes for name in source_scene.characters
        ))
        actual_characters = [character.name for character in characters]
        if actual_characters != expected_characters:
            raise ValueError("storyboard_character_bible_mismatch")
        for source_scene, storyboard_scene in zip(payload.scenes, scenes):
            if [frame.frame_number for frame in storyboard_scene.frames] != list(range(1, len(storyboard_scene.frames) + 1)):
                raise ValueError("invalid_frame_sequence")
            allowed_scene_characters = set(source_scene.characters)
            if any(not set(frame.characters).issubset(allowed_scene_characters)
                   for frame in storyboard_scene.frames):
                raise ValueError("frame_character_not_in_scene")
        if sum(len(scene.frames) for scene in scenes) > 300:
            raise ValueError("storyboard_frame_limit")
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=502, detail="AI не вернул раскадровку в ожидаемом формате. Попробуйте повторить запрос.") from exc
    return MovieStoryboardResponse(characters=characters, scenes=scenes, provider=settings.ai_provider, model=result.actual_model)


@app.post(f"{settings.api_prefix}/prompts", response_model=PromptResponse)
def create_prompt(payload: PromptRequest, user: StudioUser = Depends(get_current_user)):
    check_content(payload.idea)
    system = (
        "You are an expert prompt engineer for creative AI tools. "
        "Turn the user's idea into one detailed, coherent, production-ready prompt. "
        "Include subject, setting, action, composition, lighting, camera movement, mood "
        "and constraints when relevant. Do not create content involving sexual exploitation of "
        "minors, non-consensual intimate imagery, instructions for real-world harm, fraud, doxxing "
        "or deceptive impersonation. Respect consent for real people's likenesses and voices. "
        "Return only the finished prompt."
    )
    request = (
        f"Purpose: {payload.purpose}\nOutput language: {payload.language}\n"
        f"Visual style: {payload.style or 'Choose a fitting style'}\n"
        f"User idea: {payload.idea}"
    )
    result = _run_admitted_ai("prompts", user.user_id, lambda: ask_ai(settings, [
        {"role": "system", "content": system},
        {"role": "user", "content": request},
    ], user_id=UUID(user.user_id)))
    record_ai_usage(settings, user_id=user.user_id, request_id=getattr(result, "request_id", uuid4()), endpoint="prompts",
                    provider=settings.ai_provider, result=result)
    return PromptResponse(prompt=result.text, provider=settings.ai_provider, model=result.actual_model)
