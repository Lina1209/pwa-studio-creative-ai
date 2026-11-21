from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.schemas import ChatRequest, ChatResponse, PromptRequest, PromptResponse
from app.services.ai_service import AIConfigurationError, ask_ai
from app.services.auth import StudioUser, get_current_user, require_admin
from app.services.content_safety import check_content
from app.services.usage_service import record_ai_usage

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description="Private API for PWA Studio — Creative AI.",
    version="0.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
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
        "authentication_configured": bool(settings.supabase_url),
        "usage_telemetry_configured": bool(settings.supabase_url and settings.supabase_service_role_key),
    }


@app.get(f"{settings.api_prefix}/auth/me")
def auth_me(user: StudioUser = Depends(get_current_user)):
    return {"id": user.user_id, "email": user.email, "role": user.role}


@app.get(f"{settings.api_prefix}/admin/me")
def admin_me(user: StudioUser = Depends(require_admin)):
    return {"id": user.user_id, "email": user.email, "role": user.role, "access": "owner"}


@app.post(f"{settings.api_prefix}/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, user: StudioUser = Depends(get_current_user)):
    check_content(payload.message)
    system = payload.system_prompt or (
        "You are Studio AI Companion, a helpful creative assistant inside PWA Studio. "
        "Help users develop video ideas, scripts, scenes and prompts. Be clear and practical. Follow platform safety rules: do not assist sexual exploitation of minors, non-consensual intimate imagery, real-world violence, self-harm instructions, weapons construction, fraud, doxxing, harassment or malware. Respect consent for real people’s likenesses and voices."
    )
    try:
        result = ask_ai(settings, [
            {"role": "system", "content": system},
            {"role": "user", "content": payload.message},
        ])
        record_ai_usage(settings, user_id=user.user_id, request_id=uuid4(), endpoint="chat",
                        provider=settings.ai_provider, result=result)
        return ChatResponse(reply=result.text, provider=settings.ai_provider, model=result.actual_model)
    except AIConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="The AI provider could not complete the request.") from exc


@app.post(f"{settings.api_prefix}/prompts", response_model=PromptResponse)
def create_prompt(payload: PromptRequest, user: StudioUser = Depends(get_current_user)):
    check_content(payload.idea)
    system = (
        "You are an expert prompt engineer for creative AI tools. "
        "Turn the user's idea into one detailed, coherent, production-ready prompt. "
        "Include subject, setting, action, composition, lighting, camera movement, mood "
        "and constraints when relevant. Return only the finished prompt."
    )
    request = (
        f"Purpose: {payload.purpose}\nOutput language: {payload.language}\n"
        f"Visual style: {payload.style or 'Choose a fitting style'}\n"
        f"User idea: {payload.idea}"
    )
    try:
        result = ask_ai(settings, [
            {"role": "system", "content": system},
            {"role": "user", "content": request},
        ])
        record_ai_usage(settings, user_id=user.user_id, request_id=uuid4(), endpoint="prompts",
                        provider=settings.ai_provider, result=result)
        return PromptResponse(prompt=result.text, provider=settings.ai_provider, model=result.actual_model)
    except AIConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="The AI provider could not create the prompt.") from exc
