"""Server-only client for the private finance role registry RPCs."""
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

import httpx

from app.core.config import Settings


class FinanceRegistryNotConfigured(RuntimeError):
    pass


class FinanceRegistryUnavailable(RuntimeError):
    pass


class FinanceRoleConflict(RuntimeError):
    pass


ROLE_PERMISSIONS = {
    "finance_operator": frozenset({
        "credit.compensation.read", "credit.compensation.request",
        "billing.refund.read", "billing.refund.request",
    }),
    "finance_approver": frozenset({
        "credit.compensation.read", "credit.compensation.approve",
        "billing.refund.read", "billing.refund.approve",
    }),
    "finance_executor": frozenset({
        "credit.compensation.execute", "billing.refund.execute",
    }),
    "support_readonly": frozenset(),
    "auditor_readonly": frozenset({
        "finance.audit.read", "finance.reconciliation.read",
    }),
}
ALLOWED_ROLES = frozenset(ROLE_PERMISSIONS)


@dataclass(frozen=True)
class FinanceRoleAssignment:
    assignment_id: UUID
    principal_id: UUID
    role_code: str
    scope_key: str | None
    valid_from: datetime
    valid_until: datetime | None
    granted_by: UUID
    created_at: datetime


@dataclass(frozen=True)
class ResolvedFinanceGrant:
    principal_id: UUID
    permissions: frozenset[str]
    active: bool
    scope_ids: frozenset[str]
    permission_scopes: dict[str, frozenset[str]] = field(default_factory=dict)
    global_permissions: frozenset[str] = frozenset()


def _headers(settings: Settings) -> dict[str, str]:
    key = settings.supabase_service_role_key
    if not settings.supabase_url or not key:
        raise FinanceRegistryNotConfigured("Finance role registry is not configured.")
    headers = {"apikey": key, "Content-Type": "application/json", "Accept": "application/json"}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _rpc(settings: Settings, name: str, payload: dict):
    try:
        with httpx.Client(timeout=8.0) as client:
            response = client.post(
                f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/{name}",
                json=payload,
                headers=_headers(settings),
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 409:
                    raise FinanceRoleConflict("An active finance role assignment already exists.") from exc
                raise
            return response.json()
    except (FinanceRegistryNotConfigured, FinanceRoleConflict):
        raise
    except Exception as exc:
        raise FinanceRegistryUnavailable("Finance role registry is temporarily unavailable.") from exc


def _parse_assignment(row: object) -> FinanceRoleAssignment:
    if not isinstance(row, dict):
        raise FinanceRegistryUnavailable("Finance role registry returned an invalid assignment.")
    try:
        role = row["role_code"]
        if role not in ALLOWED_ROLES:
            raise ValueError("unknown role")
        valid_from = datetime.fromisoformat(str(row["valid_from"]).replace("Z", "+00:00"))
        created_at = datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
        valid_until_raw = row.get("valid_until")
        valid_until = (
            datetime.fromisoformat(str(valid_until_raw).replace("Z", "+00:00"))
            if valid_until_raw else None
        )
        if valid_from.tzinfo is None or created_at.tzinfo is None:
            raise ValueError("timezone missing")
        if valid_until is not None and valid_until.tzinfo is None:
            raise ValueError("timezone missing")
        return FinanceRoleAssignment(
            assignment_id=UUID(str(row["assignment_id"])),
            principal_id=UUID(str(row["principal_id"])),
            role_code=role,
            scope_key=row.get("scope_key"),
            valid_from=valid_from,
            valid_until=valid_until,
            granted_by=UUID(str(row["granted_by"])),
            created_at=created_at,
        )
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise FinanceRegistryUnavailable("Finance role registry returned malformed assignment data.") from exc


def list_active_finance_roles(settings: Settings, *, principal_id: UUID) -> list[FinanceRoleAssignment]:
    if not isinstance(principal_id, UUID):
        raise ValueError("Verified principal UUID is required.")
    result = _rpc(settings, "read_active_finance_role_assignments", {"p_principal_id": str(principal_id)})
    if not isinstance(result, list) or len(result) > 100:
        raise FinanceRegistryUnavailable("Finance role registry returned an invalid assignment page.")
    assignments = [_parse_assignment(row) for row in result]
    if any(item.principal_id != principal_id for item in assignments):
        raise FinanceRegistryUnavailable("Finance role registry returned a mismatched principal.")
    return assignments


def resolve_finance_grant(settings: Settings, *, principal_id: UUID) -> ResolvedFinanceGrant:
    assignments = list_active_finance_roles(settings, principal_id=principal_id)
    permissions: set[str] = set()
    scopes: set[str] = set()
    permission_scopes: dict[str, set[str]] = {}
    global_permissions: set[str] = set()
    for assignment in assignments:
        role_permissions = ROLE_PERMISSIONS[assignment.role_code]
        permissions.update(role_permissions)
        if assignment.scope_key is None:
            global_permissions.update(role_permissions)
        else:
            scopes.add(assignment.scope_key)
            for permission in role_permissions:
                permission_scopes.setdefault(permission, set()).add(assignment.scope_key)
    return ResolvedFinanceGrant(
        principal_id=principal_id,
        permissions=frozenset(permissions),
        active=bool(assignments),
        scope_ids=frozenset(scopes),
        permission_scopes={
            permission: frozenset(values)
            for permission, values in permission_scopes.items()
        },
        global_permissions=frozenset(global_permissions),
    )


def grant_finance_role(
    settings: Settings, *, principal_id: UUID, role_code: str,
    scope_key: str | None, valid_until: datetime | None,
    granted_by: UUID, reason: str,
) -> UUID:
    if not isinstance(principal_id, UUID) or not isinstance(granted_by, UUID):
        raise ValueError("Verified principal and actor UUIDs are required.")
    if principal_id == granted_by:
        raise ValueError("Self-assignment of finance roles is prohibited.")
    if role_code not in ALLOWED_ROLES:
        raise ValueError("Unsupported finance role.")
    if not isinstance(scope_key, str) or not scope_key or len(scope_key) > 200 or scope_key.strip() != scope_key:
        raise ValueError("An explicit finance role scope is required.")
    if valid_until is None or valid_until.tzinfo is None or valid_until <= datetime.now(valid_until.tzinfo):
        raise ValueError("A future timezone-aware finance role expiry is required.")
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 500:
        raise ValueError("A reason of 1 to 500 characters is required.")
    result = _rpc(settings, "grant_finance_role", {
        "p_principal_id": str(principal_id),
        "p_role_code": role_code,
        "p_scope_key": scope_key,
        "p_valid_until": valid_until.isoformat() if valid_until else None,
        "p_granted_by": str(granted_by),
        "p_reason": reason.strip(),
    })
    try:
        return UUID(str(result))
    except (ValueError, TypeError, AttributeError) as exc:
        raise FinanceRegistryUnavailable("Finance role grant returned an invalid identifier.") from exc


def revoke_finance_role(
    settings: Settings, *, assignment_id: UUID, revoked_by: UUID, reason: str,
) -> UUID:
    if not isinstance(assignment_id, UUID) or not isinstance(revoked_by, UUID):
        raise ValueError("Assignment and actor UUIDs are required.")
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 500:
        raise ValueError("A reason of 1 to 500 characters is required.")
    result = _rpc(settings, "revoke_finance_role", {
        "p_assignment_id": str(assignment_id),
        "p_revoked_by": str(revoked_by),
        "p_reason": reason.strip(),
    })
    try:
        return UUID(str(result))
    except (ValueError, TypeError, AttributeError) as exc:
        raise FinanceRegistryUnavailable("Finance role revocation returned an invalid identifier.") from exc
