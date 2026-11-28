"""Owner-scoped server API boundary for character passport metadata."""
import json
import base64
import hashlib
import hmac
import time
from datetime import datetime, timezone
import httpx
from fastapi import HTTPException
from app.core.config import Settings
from app.services.media_access import canonical_uuid

MAX_REFERENCE_DATA_BYTES = 24 * 1024

def validate_reference_data(value):
    if not isinstance(value, dict):
        raise HTTPException(status_code=422, detail="reference_data must be a JSON object.")
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="reference_data must contain valid JSON values.") from exc
    if len(encoded) > MAX_REFERENCE_DATA_BYTES:
        raise HTTPException(status_code=413, detail="Character passport data exceeds 24 KiB.")
    def check(node, depth=0):
        if depth > 6:
            raise HTTPException(status_code=422, detail="Character passport data is too deeply nested.")
        if isinstance(node, dict):
            if len(node) > 80 or any(not isinstance(k, str) or len(k) > 80 for k in node):
                raise HTTPException(status_code=422, detail="Character passport data contains invalid fields.")
            for child in node.values(): check(child, depth + 1)
        elif isinstance(node, list):
            if len(node) > 100: raise HTTPException(status_code=422, detail="Character passport list is too long.")
            for child in node: check(child, depth + 1)
        elif not (node is None or isinstance(node, (str, int, float, bool))):
            raise HTTPException(status_code=422, detail="Character passport data contains unsupported values.")
        elif isinstance(node, str) and len(node) > 4000:
            raise HTTPException(status_code=422, detail="A character passport field is too long.")
    check(value)
    return value

def _rpc(settings, function_name, payload):
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise HTTPException(status_code=503, detail="Character storage is not configured.")
    headers = {"apikey": settings.supabase_service_role_key,
                      "Content-Type": "application/json", "Accept": "application/json"}
    # sb_secret keys are apikey-only; legacy service-role JWTs also use Bearer.
    if settings.supabase_service_role_key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {settings.supabase_service_role_key}"
    try:
        response = httpx.post(
            f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/{function_name}",
            headers=headers, json=payload, timeout=12.0,
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list):
            data = data[0] if len(data) == 1 else None
        if not isinstance(data, dict):
            raise HTTPException(status_code=502, detail="Character storage returned an invalid result.")
        return data
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 409 or (exc.response.status_code == 400 and "23505" in exc.response.text):
            raise HTTPException(status_code=409, detail="The local character ID is already linked to different cloud data.") from exc
        raise HTTPException(status_code=502, detail="Character storage rejected the request.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Character storage is temporarily unavailable.") from exc


def _request(settings, method, params=None, payload=None):
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise HTTPException(status_code=503, detail="Character storage is not configured.")
    headers = {"apikey": settings.supabase_service_role_key,
                      "Content-Type": "application/json", "Accept": "application/json",
               "Prefer": "return=representation"}
    # sb_secret keys are apikey-only; legacy service-role JWTs also use Bearer.
    if settings.supabase_service_role_key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {settings.supabase_service_role_key}"
    try:
        response = httpx.request(method, f"{settings.supabase_url.rstrip('/')}/rest/v1/characters",
                                 headers=headers, params=params, json=payload, timeout=12.0)
        response.raise_for_status()
        data = response.json() if response.content else []
        if not isinstance(data, list):
            raise HTTPException(status_code=502, detail="Character storage returned an invalid response.")
        return data
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 409 or (exc.response.status_code == 400 and "23505" in exc.response.text):
            raise HTTPException(status_code=409, detail="A character with this identifier already exists.") from exc
        raise HTTPException(status_code=502, detail="Character storage rejected the request.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Character storage is temporarily unavailable.") from exc

def _public(row):
    if not isinstance(row, dict): raise HTTPException(status_code=502, detail="Character storage returned an invalid record.")
    return {k: row.get(k) for k in ("id", "source_local_id", "name", "description", "reference_data", "created_at", "version")}

def _cursor_secret(settings):
    secret = settings.supabase_service_role_key
    if not isinstance(secret, str) or len(secret) < 24:
        raise HTTPException(status_code=503, detail="Character pagination is not configured.")
    return secret.encode("utf-8")


def _encode_cursor(settings, payload):
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    signature = hmac.new(_cursor_secret(settings), encoded.encode("ascii"), hashlib.sha256).digest()
    return encoded + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")


def _decode_cursor(settings, token, owner):
    if not isinstance(token, str) or len(token) > 2048 or token.count(".") != 1:
        raise HTTPException(status_code=422, detail="Invalid character page cursor.")
    encoded, supplied = token.split(".", 1)
    expected = hmac.new(_cursor_secret(settings), encoded.encode("ascii"), hashlib.sha256).digest()
    try:
        signature = base64.urlsafe_b64decode(supplied + "=" * (-len(supplied) % 4))
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        payload = json.loads(raw)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid character page cursor.") from exc
    if not hmac.compare_digest(signature, expected) or not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Invalid character page cursor.")
    if payload.get("owner") != owner or not isinstance(payload.get("expires"), int) or payload["expires"] < int(time.time()):
        raise HTTPException(status_code=422, detail="Expired or mismatched character page cursor.")
    for key in ("snapshot", "last_created_at", "last_id"):
        if not isinstance(payload.get(key), str) or len(payload[key]) > 80:
            raise HTTPException(status_code=422, detail="Invalid character page cursor.")
    canonical_uuid(payload["last_id"], "cursor character")
    try:
        datetime.fromisoformat(payload["snapshot"].replace("Z", "+00:00"))
        datetime.fromisoformat(payload["last_created_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid character page cursor.") from exc
    return payload


def list_owned_characters(settings, owner_id, cursor=None, page_size=50):
    owner = canonical_uuid(owner_id, "owner")
    if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= 100:
        raise HTTPException(status_code=422, detail="Character page size must be between 1 and 100.")
    if cursor:
        state = _decode_cursor(settings, cursor, owner)
        snapshot = state["snapshot"]
        last_created_at = state["last_created_at"]
        last_id = state["last_id"]
    else:
        snapshot = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
        last_created_at = last_id = None
    params = {
        "select":"id,owner_id,source_local_id,name,description,reference_data,created_at,version",
        "owner_id":f"eq.{owner}",
        "created_at":f"lte.{snapshot}",
        "order":"created_at.desc,id.desc",
        "limit":str(page_size + 1),
    }
    if last_created_at is not None:
        params["or"] = f"(created_at.lt.{last_created_at},and(created_at.eq.{last_created_at},id.lt.{last_id}))"
    rows = _request(settings, "GET", params)
    if any(not isinstance(row, dict) or row.get("owner_id") != owner for row in rows):
        raise HTTPException(status_code=404, detail="Character not found.")
    has_more = len(rows) > page_size
    visible = rows[:page_size]
    next_cursor = None
    if has_more and visible:
        last = visible[-1]
        if not isinstance(last.get("created_at"), str):
            raise HTTPException(status_code=502, detail="Character storage returned an invalid page boundary.")
        next_cursor = _encode_cursor(settings, {
            "owner": owner,
            "snapshot": snapshot,
            "last_created_at": last["created_at"],
            "last_id": last.get("id"),
            "expires": int(time.time()) + 900,
        })
    return {
        "items": [_public(row) for row in visible],
        "next_cursor": next_cursor,
        "snapshot_created_at": snapshot,
    }

def create_owned_character(settings, owner_id, source_local_id, name, description, reference_data):
    owner = canonical_uuid(owner_id, "owner")
    name = name.strip()
    if not name or len(name) > 120: raise HTTPException(status_code=422, detail="Character name must contain 1–120 characters.")
    if description is not None and len(description) > 5000: raise HTTPException(status_code=422, detail="Character description exceeds 5,000 characters.")
    data = validate_reference_data(reference_data)
    local_id = canonical_uuid(source_local_id, "local character")
    normalized_description = description.strip() if description else None
    row = _rpc(settings, "pwa_create_character_idempotent", {
        "p_owner_id": owner,
        "p_source_local_id": local_id,
        "p_name": name,
        "p_description": normalized_description,
        "p_reference_data": data,
    })
    if row.get("owner_id") != owner or row.get("source_local_id") != local_id:
        raise HTTPException(status_code=502, detail="Character creation returned an invalid ownership mapping.")
    if row.get("name") != name or row.get("description") != normalized_description or row.get("reference_data") != data:
        raise HTTPException(status_code=502, detail="Character creation returned a mismatched passport.")
    return _public(row)

def get_owned_character(settings, owner_id, character_id):
    owner = canonical_uuid(owner_id, "owner")
    character = canonical_uuid(character_id, "character")
    rows = _request(settings, "GET", {"select":"id,owner_id,source_local_id,name,description,reference_data,created_at,version",
        "id":f"eq.{character}", "owner_id":f"eq.{owner}", "limit":"1"})
    if not rows: raise HTTPException(status_code=404, detail="Character not found.")
    if rows[0].get("owner_id") != owner: raise HTTPException(status_code=404, detail="Character not found.")
    return _public(rows[0])

def update_owned_character(settings, owner_id, character_id, expected_version, changes):
    owner = canonical_uuid(owner_id, "owner")
    character = canonical_uuid(character_id, "character")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 1:
        raise HTTPException(status_code=422, detail="A positive expected character version is required.")
    payload = {}
    if "name" in changes:
        value = changes["name"]
        if not isinstance(value, str): raise HTTPException(status_code=422, detail="Character name must be text.")
        value = value.strip()
        if not value or len(value) > 120: raise HTTPException(status_code=422, detail="Character name must contain 1–120 characters.")
        payload["name"] = value
    if "description" in changes:
        value = changes["description"]
        if value is not None and not isinstance(value, str): raise HTTPException(status_code=422, detail="Character description must be text.")
        if value is not None and len(value) > 5000: raise HTTPException(status_code=422, detail="Character description exceeds 5,000 characters.")
        payload["description"] = value.strip() if value else None
    if "reference_data" in changes: payload["reference_data"] = validate_reference_data(changes["reference_data"])
    if not payload: raise HTTPException(status_code=400, detail="No character changes were supplied.")
    row = _rpc(settings, "pwa_update_character_versioned", {
        "p_owner_id": owner,
        "p_character_id": character,
        "p_expected_version": expected_version,
        "p_changes": payload,
    })
    if row.get("not_found") is True:
        raise HTTPException(status_code=404, detail="Character not found.")
    if row.get("conflict") is True:
        raise HTTPException(status_code=409, detail={
            "code": "character_version_conflict",
            "message": "This character was changed elsewhere. Reload the latest version before editing.",
            "current_version": row.get("version"),
        })
    if row.get("owner_id") != owner or row.get("id") != character:
        raise HTTPException(status_code=502, detail="Character update returned an invalid ownership mapping.")
    if row.get("version") != expected_version + 1:
        raise HTTPException(status_code=502, detail="Character update returned an invalid version.")
    return _public(row)
