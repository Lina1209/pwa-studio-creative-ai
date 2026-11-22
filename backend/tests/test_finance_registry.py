from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from app.core.config import Settings
from app.services import finance_registry as registry
from app.services.finance_authorization import FinanceAuthorizationDenied, require_finance_permission


ACTOR = UUID("11111111-1111-4111-8111-111111111111")
TARGET = UUID("22222222-2222-4222-8222-222222222222")
ASSIGNMENT = UUID("33333333-3333-4333-8333-333333333333")


def test_registry_resolves_only_permissions_from_active_role_rows(monkeypatch):
    now = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(registry, "_rpc", lambda *a, **k: [{
        "assignment_id": str(ASSIGNMENT), "principal_id": str(TARGET),
        "role_code": "finance_operator", "scope_key": "tenant-a",
        "valid_from": now, "valid_until": None, "granted_by": str(ACTOR),
        "created_at": now,
    }])
    grant = registry.resolve_finance_grant(Settings(supabase_url="https://example.test", supabase_service_role_key="x"), principal_id=TARGET)
    assert grant.active is True
    assert grant.permissions == frozenset({
        "credit.compensation.read", "credit.compensation.request",
        "billing.refund.read", "billing.refund.request",
    })
    assert grant.scope_ids == frozenset({"tenant-a"})


def test_registry_rejects_malformed_or_cross_principal_rows(monkeypatch):
    monkeypatch.setattr(registry, "_rpc", lambda *a, **k: [{
        "assignment_id": str(ASSIGNMENT), "principal_id": str(ACTOR),
        "role_code": "finance_operator", "scope_key": None,
        "valid_from": datetime.now(timezone.utc).isoformat(), "valid_until": None,
        "granted_by": str(ACTOR), "created_at": datetime.now(timezone.utc).isoformat(),
    }])
    with pytest.raises(registry.FinanceRegistryUnavailable):
        registry.list_active_finance_roles(
            Settings(supabase_url="https://example.test", supabase_service_role_key="x"),
            principal_id=TARGET,
        )


def test_role_grant_rejects_self_assignment_and_bad_expiry(monkeypatch):
    called = []
    monkeypatch.setattr(registry, "_rpc", lambda *a, **k: called.append(k) or str(ASSIGNMENT))
    settings = Settings(supabase_url="https://example.test", supabase_service_role_key="x")
    with pytest.raises(ValueError):
        registry.grant_finance_role(
            settings, principal_id=ACTOR, role_code="finance_operator",
            scope_key=None, valid_until=None, granted_by=ACTOR, reason="No self grant",
        )
    with pytest.raises(ValueError):
        registry.grant_finance_role(
            settings, principal_id=TARGET, role_code="finance_operator",
            scope_key=None, valid_until=datetime.now(timezone.utc) - timedelta(seconds=1),
            granted_by=ACTOR, reason="Expired",
        )
    assert called == []


def test_role_grant_calls_only_server_registry_rpc(monkeypatch):
    payloads = []
    monkeypatch.setattr(registry, "_rpc", lambda settings, name, payload: payloads.append((name, payload)) or str(ASSIGNMENT))
    settings = Settings(supabase_url="https://example.test", supabase_service_role_key="x")
    result = registry.grant_finance_role(
        settings, principal_id=TARGET, role_code="finance_approver",
        scope_key="tenant-a", valid_until=None, granted_by=ACTOR, reason="Approved assignment",
    )
    assert result == ASSIGNMENT
    assert payloads[0][0] == "grant_finance_role"
    assert payloads[0][1]["p_granted_by"] == str(ACTOR)
    assert payloads[0][1]["p_principal_id"] == str(TARGET)


def test_registry_refuses_unknown_roles_and_permission_escalation(monkeypatch):
    settings = Settings(supabase_url="https://example.test", supabase_service_role_key="x")
    with pytest.raises(ValueError):
        registry.grant_finance_role(
            settings, principal_id=TARGET, role_code="owner",
            scope_key=None, valid_until=None, granted_by=ACTOR, reason="Invalid role",
        )
    assert "finance.policy.manage" not in registry.ROLE_PERMISSIONS["finance_operator"]



def test_permissions_keep_the_scope_of_the_role_that_granted_them(monkeypatch):
    now = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(registry, "_rpc", lambda *a, **k: [
        {
            "assignment_id": str(ASSIGNMENT), "principal_id": str(TARGET),
            "role_code": "finance_operator", "scope_key": "tenant-a",
            "valid_from": now, "valid_until": None, "granted_by": str(ACTOR),
            "created_at": now,
        },
        {
            "assignment_id": "44444444-4444-4444-8444-444444444444",
            "principal_id": str(TARGET), "role_code": "finance_approver",
            "scope_key": "tenant-b", "valid_from": now, "valid_until": None,
            "granted_by": str(ACTOR), "created_at": now,
        },
    ])
    grant = registry.resolve_finance_grant(
        Settings(supabase_url="https://example.test", supabase_service_role_key="x"),
        principal_id=TARGET,
    )
    require_finance_permission(
        grant, actor_id=TARGET, permission="credit.compensation.request", target_scope="tenant-a"
    )
    with pytest.raises(FinanceAuthorizationDenied):
        require_finance_permission(
            grant, actor_id=TARGET, permission="credit.compensation.request"
        )
    with pytest.raises(FinanceAuthorizationDenied):
        require_finance_permission(
            grant, actor_id=TARGET, permission="credit.compensation.request", target_scope="tenant-b"
        )
    require_finance_permission(
        grant, actor_id=TARGET, permission="credit.compensation.approve", target_scope="tenant-b"
    )
    with pytest.raises(FinanceAuthorizationDenied):
        require_finance_permission(
            grant, actor_id=TARGET, permission="credit.compensation.approve", target_scope="tenant-a"
        )


def test_unscoped_assignment_is_global_only_for_its_own_role_permissions(monkeypatch):
    now = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(registry, "_rpc", lambda *a, **k: [{
        "assignment_id": str(ASSIGNMENT), "principal_id": str(TARGET),
        "role_code": "finance_operator", "scope_key": None,
        "valid_from": now, "valid_until": None, "granted_by": str(ACTOR),
        "created_at": now,
    }])
    grant = registry.resolve_finance_grant(
        Settings(supabase_url="https://example.test", supabase_service_role_key="x"),
        principal_id=TARGET,
    )
    require_finance_permission(
        grant, actor_id=TARGET, permission="credit.compensation.request", target_scope="any-tenant"
    )
    with pytest.raises(FinanceAuthorizationDenied):
        require_finance_permission(
            grant, actor_id=TARGET, permission="credit.compensation.approve", target_scope="any-tenant"
        )
