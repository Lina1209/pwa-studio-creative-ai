from types import SimpleNamespace

from fastapi import HTTPException

from app.core.config import Settings
from app.services import moderation_service


USER_A = "11111111-1111-4111-8111-111111111111"
USER_B = "22222222-2222-4222-8222-222222222222"
ADMIN_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
REPORT_ID = "33333333-3333-4333-8333-333333333333"
SUSPENSION_ID = "44444444-4444-4444-8444-444444444444"


def test_report_creation_uses_verified_reporter_and_allowlisted_fields(monkeypatch):
    calls = []

    def fake_request(settings, method, table, *, params=None, payload=None):
        calls.append((method, table, params, payload))
        return [{"id": REPORT_ID, "status": "open", "created_at": "now"}]

    monkeypatch.setattr(moderation_service, "_request", fake_request)
    payload = SimpleNamespace(
        reported_user_id=USER_B,
        category="harassment",
        description="Report details",
        content_reference={"kind": "profile"},
        reporter_user_id=USER_B,
        user_id=USER_B,
    )
    moderation_service.create_user_report(Settings(), USER_A, payload)

    method, table, params, body = calls[0]
    assert (method, table) == ("POST", "user_reports")
    assert body["reporter_user_id"] == USER_A
    assert body["reported_user_id"] == USER_B
    assert "user_id" not in body
    assert "reporter_user_id" not in params["select"]


def test_report_review_is_scoped_to_exact_report_and_records_verified_moderator(monkeypatch):
    calls = []

    def fake_request(settings, method, table, *, params=None, payload=None):
        calls.append((method, table, params, payload))
        if table == "user_reports":
            return [{"id": REPORT_ID, "status": "resolved", "created_at": "now",
                     "reporter_user_id": USER_A}]
        return []

    monkeypatch.setattr(moderation_service, "_request", fake_request)
    result = moderation_service.review_user_report(
        Settings(), REPORT_ID, ADMIN_ID,
        SimpleNamespace(status="resolved", moderator_note="Reviewed"),
    )

    assert result["reporter_user_id"] == USER_A
    method, table, params, body = calls[0]
    assert (method, table) == ("PATCH", "user_reports")
    assert params["id"] == f"eq.{REPORT_ID}"
    assert body["reviewed_by"] == ADMIN_ID
    assert body["status"] == "resolved"
    assert calls[1][1] == "admin_audit_log"
    assert calls[1][3]["actor_user_id"] == ADMIN_ID


def test_suspension_creation_uses_moderator_identity_and_target_only(monkeypatch):
    calls = []

    def fake_request(settings, method, table, *, params=None, payload=None):
        calls.append((method, table, params, payload))
        if table == "user_suspensions":
            return [{"id": SUSPENSION_ID, "user_id": USER_B, "scope": "community"}]
        return []

    monkeypatch.setattr(moderation_service, "_request", fake_request)
    payload = SimpleNamespace(
        user_id=USER_B, reason="abuse", scope="community",
        expires_at="2026-11-25T00:00:00+00:00", created_by=USER_B,
    )
    moderation_service.create_suspension(Settings(), ADMIN_ID, payload)

    body = calls[0][3]
    assert body["user_id"] == USER_B
    assert body["created_by"] == ADMIN_ID
    assert "created_by" not in calls[0][2].get("select", "")
    assert calls[1][1] == "admin_audit_log"
    assert calls[1][3]["actor_user_id"] == ADMIN_ID


def test_suspension_revocation_only_targets_active_exact_record(monkeypatch):
    calls = []

    def fake_request(settings, method, table, *, params=None, payload=None):
        calls.append((method, table, params, payload))
        if table == "user_suspensions":
            return [{"id": SUSPENSION_ID, "user_id": USER_B, "scope": "community"}]
        return []

    monkeypatch.setattr(moderation_service, "_request", fake_request)
    result = moderation_service.revoke_suspension(Settings(), ADMIN_ID, SUSPENSION_ID)

    assert result == {"success": True, "id": SUSPENSION_ID}
    params = calls[0][2]
    assert params["id"] == f"eq.{SUSPENSION_ID}"
    assert params["revoked_at"] == "is.null"
    assert calls[0][3]["revoked_by"] == ADMIN_ID
    assert calls[1][1] == "admin_audit_log"


def test_suspension_check_rejects_active_platform_or_feature_restriction(monkeypatch):
    calls = []

    def fake_request(settings, method, table, *, params=None, payload=None):
        calls.append((method, table, params))
        return [{"id": SUSPENSION_ID, "reason": "abuse", "expires_at": None}]

    monkeypatch.setattr(moderation_service, "_request", fake_request)
    try:
        moderation_service.ensure_user_not_suspended(Settings(), USER_A, "community")
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("Expected active suspension to be enforced.")

    params = calls[0][2]
    assert params["user_id"] == f"eq.{USER_A}"
    assert params["revoked_at"] == "is.null"
    assert params["scope"] == "in.(platform,community)"


def test_suspension_check_allows_user_when_no_active_restriction(monkeypatch):
    monkeypatch.setattr(moderation_service, "_request", lambda *args, **kwargs: [])
    assert moderation_service.ensure_user_not_suspended(Settings(), USER_A, "assistant") is None
