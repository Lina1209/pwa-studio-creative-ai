import hashlib
import json
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.schemas import ChatRequest, ChatResponse, PromptRequest, PromptResponse, SceneImageJobRequest
from app.services.ai_service import AIConfigurationError, AIOverloadedError, ask_ai
from app.services.auth import StudioUser, get_current_user, require_admin
from app.services.content_safety import check_content
from app.services.usage_service import record_ai_usage
from app.services.generation_jobs import (
    GenerationJobsNotConfiguredError,
    GenerationJobsServiceError,
    get_generation_job,
    create_scene_generation_job,
)

settings = get_settings()

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


@app.get("/")
def root():
    return {"name": settings.app_name, "status": "ok", "docs": "/docs"}


@app.get(f"{settings.api_prefix}/health")
def health():
    provider = settings.ai_provider.strip().lower()
    ai_configured = (
        bool(settings.openai_api_key) if provider == "openai"
        else bool(settings.deepseek_api_key) if provider == "deepseek"
        else bool(settings.anthropic_api_key) if provider in {"anthropic", "claude"}
        else bool(settings.ollama_api_base) if provider == "ollama"
        else False
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
        "generation_worker_ready": bool(settings.generation_job_worker_ready),
        "image_generation_configured": bool(settings.image_generation_provider and settings.image_generation_model),
    }


@app.get(f"{settings.api_prefix}/jobs/{job_id}")
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


@app.post(f"{settings.api_prefix}/scenes/{scene_id}/image-jobs", status_code=202)
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

@app.get(f"{settings.api_prefix}/auth/me")
def auth_me(user: StudioUser = Depends(get_current_user)):
    return {"id": user.user_id, "email": user.email, "role": user.role}


@app.get(f"{settings.api_prefix}/admin/me")
def admin_me(user: StudioUser = Depends(require_admin)):
    return {"id": user.user_id, "email": user.email, "role": user.role, "access": "owner"}


def _run_ai(operation: str, call):
    try:
        return call()
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
    result = _run_ai("chat", lambda: ask_ai(settings, [
        {"role": "system", "content": system},
        {"role": "user", "content": payload.message},
    ]))
    record_ai_usage(settings, user_id=user.user_id, request_id=uuid4(), endpoint="chat",
                    provider=settings.ai_provider, result=result)
    return ChatResponse(reply=result.text, provider=settings.ai_provider, model=result.actual_model)


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
    result = _run_ai("prompts", lambda: ask_ai(settings, [
        {"role": "system", "content": system},
        {"role": "user", "content": request},
    ]))
    record_ai_usage(settings, user_id=user.user_id, request_id=uuid4(), endpoint="prompts",
                    provider=settings.ai_provider, result=result)
    return PromptResponse(prompt=result.text, provider=settings.ai_provider, model=result.actual_model)
