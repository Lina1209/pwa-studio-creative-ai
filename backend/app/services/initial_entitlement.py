"""Idempotent first-wallet-read entitlement grant, disabled unless explicitly configured."""
from uuid import UUID
import httpx
from app.core.config import Settings

class EntitlementGrantUnavailable(RuntimeError): pass

def grant_initial_free_entitlement(settings: Settings, *, user_id: UUID) -> dict | None:
    policy=(settings.free_entitlement_policy_code or "").strip()
    if not policy:
        return None
    if not isinstance(user_id,UUID):
        raise ValueError("Verified user UUID is required.")
    if len(policy)>64 or not policy.isascii() or not policy[0].islower() or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789_" for ch in policy):
        raise ValueError("Free entitlement policy code is invalid.")
    key=settings.supabase_service_role_key
    if not settings.supabase_url or not key:
        raise EntitlementGrantUnavailable("Entitlement storage is not configured.")
    headers={"apikey":key,"Content-Type":"application/json"}
    if key.startswith("eyJ"): headers["Authorization"]=f"Bearer {key}"
    payload={
      "p_user_id":str(user_id),
      "p_policy_code":policy,
      "p_event_key":"initial_wallet_entitlement:v1",
      "p_source_reference":"initial_wallet:"+str(user_id),
      "p_metadata":{"grant_reason":"first_wallet_read"}
    }
    try:
        with httpx.Client(timeout=8.0) as client:
            response=client.post(
              f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/grant_user_credit_entitlement",
              json=payload,headers=headers)
            response.raise_for_status()
            data=response.json()
    except Exception as exc:
        raise EntitlementGrantUnavailable("Initial free entitlement could not be verified.") from exc
    if isinstance(data,list):
        if len(data)!=1: raise EntitlementGrantUnavailable("Entitlement RPC returned an invalid result.")
        data=data[0]
    if not isinstance(data,dict):
        raise EntitlementGrantUnavailable("Entitlement RPC returned an invalid result.")
    for field in ("available_credits","reserved_credits"):
        value=data.get(field)
        if isinstance(value,bool) or not isinstance(value,int) or value<0:
            raise EntitlementGrantUnavailable("Entitlement RPC returned an invalid balance.")
    if not isinstance(data.get("replayed"),bool):
        raise EntitlementGrantUnavailable("Entitlement RPC returned invalid idempotency metadata.")
    return {"replayed":data["replayed"]}
