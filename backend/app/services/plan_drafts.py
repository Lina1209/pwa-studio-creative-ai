"""Admin-only storage for immutable subscription-plan drafts."""
import httpx
from uuid import UUID
from app.core.config import Settings

class PlanDraftUnavailable(RuntimeError):
    pass

def _headers(settings: Settings):
    key=settings.supabase_service_role_key
    if not settings.supabase_url or not key:
        raise PlanDraftUnavailable("Plan draft storage is not configured.")
    headers={"apikey":key,"Content-Type":"application/json","Accept":"application/json"}
    if key.startswith("eyJ"): headers["Authorization"]=f"Bearer {key}"
    return headers

def _request(settings: Settings,method: str,*,params=None,payload=None,prefer=None):
    try:
        with httpx.Client(timeout=8.0) as client:
            response=client.request(method,f"{settings.supabase_url.rstrip('/')}/rest/v1/plan_catalog_drafts",
                params=params,json=payload,headers={**_headers(settings),**({"Prefer":prefer} if prefer else {})})
            response.raise_for_status()
            return response.json() if response.content else []
    except PlanDraftUnavailable: raise
    except Exception as exc: raise PlanDraftUnavailable("Plan draft storage is temporarily unavailable.") from exc

def create_plan_draft(settings: Settings, *, payload: dict, actor_id: UUID):
    rows=_request(settings,"POST",payload={**payload,"created_by":str(actor_id)},prefer="return=representation")
    if not isinstance(rows,list) or len(rows)!=1: raise PlanDraftUnavailable("Could not save plan draft.")
    return rows[0]

def list_plan_drafts(settings: Settings, *, limit: int=100):
    rows=_request(settings,"GET",params={"select":"id,plan_code,plan_version,display_name,billing_period,period_days,credits_per_period,price_minor,currency,limits_json,features_json,created_by,created_at","order":"created_at.desc,id.desc","limit":str(limit)})
    if not isinstance(rows,list): raise PlanDraftUnavailable("Invalid plan draft list.")
    return rows
