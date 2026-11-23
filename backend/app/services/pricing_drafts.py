"""Admin-only, immutable tariff draft storage. Drafts never alter live pricing."""
from uuid import UUID
import httpx
from app.core.config import Settings

class PricingDraftUnavailable(RuntimeError):
    pass

def _headers(settings: Settings):
    key=settings.supabase_service_role_key
    if not settings.supabase_url or not key:
        raise PricingDraftUnavailable("Pricing draft storage is not configured.")
    headers={"apikey":key,"Content-Type":"application/json","Accept":"application/json"}
    if key.startswith("eyJ"): headers["Authorization"]=f"Bearer {key}"
    return headers

def _request(settings: Settings, method: str, *, params=None, payload=None, prefer=None):
    try:
        with httpx.Client(timeout=8.0) as client:
            response=client.request(method,
                f"{settings.supabase_url.rstrip('/')}/rest/v1/pricing_catalog_drafts",
                params=params,json=payload,
                headers={**_headers(settings),**({"Prefer":prefer} if prefer else {})})
            response.raise_for_status()
            return response.json() if response.content else []
    except PricingDraftUnavailable: raise
    except Exception as exc: raise PricingDraftUnavailable("Tariff draft storage is temporarily unavailable.") from exc

def create_draft(settings: Settings, *, version: str, catalog: dict, actor_id: UUID):
    rows=_request(settings,"POST",payload={"version":version,"catalog_json":catalog,"created_by":str(actor_id)},
                  prefer="return=representation")
    if not isinstance(rows,list) or len(rows)!=1: raise PricingDraftUnavailable("Could not save tariff draft.")
    return rows[0]

def list_drafts(settings: Settings, *, limit: int=50):
    rows=_request(settings,"GET",params={"select":"id,version,catalog_json,created_by,created_at",
        "order":"created_at.desc,id.desc","limit":str(limit)})
    if not isinstance(rows,list): raise PricingDraftUnavailable("Invalid tariff draft list.")
    return rows
