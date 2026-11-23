from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.services.admin_audit_service import (
    AdminAuditUnavailable,
    get_admin_audit_events,
    record_admin_audit_event,
)


ACTOR = UUID("11111111-1111-4111-8111-111111111111")
RESOURCE = UUID("22222222-2222-4222-8222-222222222222")
CORRELATION = UUID("33333333-3333-4333-8333-333333333333")
EVENT = UUID("44444444-4444-4444-8444-444444444444")
SETTINGS = SimpleNamespace(supabase_url="https://example.supabase.co", supabase_service_role_key="test")


def test_record_admin_audit_event_rejects_non_uuid_references_before_rpc(monkeypatch):
    import app.services.admin_audit_service as service

    monkeypatch.setattr(service, "_rpc", lambda *a, **k: pytest.fail("RPC must not run"))
    with pytest.raises(ValueError, match="resource UUID"):
        record_admin_audit_event(
            SETTINGS, actor_user_id=ACTOR, action="admin.access", outcome="allowed",
            resource_type="platform", resource_id="not-a-uuid",
        )
    with pytest.raises(ValueError, match="correlation UUID"):
        record_admin_audit_event(
            SETTINGS, actor_user_id=ACTOR, action="admin.access", outcome="allowed",
            resource_type="platform", correlation_id="not-a-uuid",
        )


def test_record_admin_audit_event_serializes_verified_uuid_references(monkeypatch):
    import app.services.admin_audit_service as service

    captured = {}
    monkeypatch.setattr(service, "_rpc", lambda settings, name, payload: captured.update(payload) or "audit-id")
    result = record_admin_audit_event(
        SETTINGS, actor_user_id=ACTOR, action="admin.user.view", outcome="allowed",
        resource_type="user", resource_id=RESOURCE, correlation_id=CORRELATION,
    )
    assert result == "audit-id"
    assert captured["p_resource_id"] == str(RESOURCE)
    assert captured["p_correlation_id"] == str(CORRELATION)


@pytest.mark.parametrize("field", ["resource_id", "correlation_id"])
def test_read_admin_audit_events_rejects_malformed_reference_ids(monkeypatch, field):
    import app.services.admin_audit_service as service

    row = {
        "id": str(EVENT), "occurred_at": "2026-11-23T00:00:00+00:00",
        "actor_user_id": str(ACTOR), "action": "admin.access", "outcome": "allowed",
        "resource_type": "platform", "resource_id": None, "correlation_id": None,
        "reason": None,
    }
    row[field] = "not-a-uuid"
    monkeypatch.setattr(service, "_rpc", lambda *a, **k: [row])
    with pytest.raises(AdminAuditUnavailable, match="references"):
        get_admin_audit_events(SETTINGS)


def test_read_admin_audit_events_returns_canonical_reference_ids(monkeypatch):
    import app.services.admin_audit_service as service

    row = {
        "id": str(EVENT), "occurred_at": "2026-11-23T00:00:00+00:00",
        "actor_user_id": str(ACTOR), "action": "admin.user.view", "outcome": "allowed",
        "resource_type": "user", "resource_id": str(RESOURCE).upper(),
        "correlation_id": str(CORRELATION), "reason": None,
    }
    monkeypatch.setattr(service, "_rpc", lambda *a, **k: [row])
    events = get_admin_audit_events(SETTINGS)
    assert events[0]["resource_id"] == str(RESOURCE)
    assert events[0]["correlation_id"] == str(CORRELATION)


@pytest.mark.parametrize(
    "resource_type",
    ["credit_ledger", "pricing_catalog_draft", "plan_catalog_draft"],
)
def test_record_admin_audit_event_accepts_resource_types_used_by_admin_routes(monkeypatch, resource_type):
    import app.services.admin_audit_service as service

    captured = {}
    monkeypatch.setattr(service, "_rpc", lambda settings, name, payload: captured.update(payload) or "audit-id")
    result = record_admin_audit_event(
        SETTINGS, actor_user_id=ACTOR, action="admin.access", outcome="allowed",
        resource_type=resource_type,
    )
    assert result == "audit-id"
    assert captured["p_resource_type"] == resource_type


@pytest.mark.parametrize("action", ["admin.support.reply", "admin.support.status.changed"])
def test_record_admin_audit_event_accepts_explicit_support_mutation_actions(monkeypatch, action):
    import app.services.admin_audit_service as service

    captured = {}
    monkeypatch.setattr(service, "_rpc", lambda settings, name, payload: captured.update(payload) or "audit-id")
    result = record_admin_audit_event(
        SETTINGS, actor_user_id=ACTOR, action=action, outcome="executed",
        resource_type="support_ticket", resource_id=RESOURCE,
    )
    assert result == "audit-id"
    assert captured["p_action"] == action
    assert captured["p_outcome"] == "executed"
