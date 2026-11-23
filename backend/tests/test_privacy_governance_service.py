from uuid import UUID

import pytest

from app.services import privacy_governance as privacy
from app.services.privacy_governance import PrivacyGovernanceUnavailable


USER_ID = UUID("11111111-1111-4111-8111-111111111111")
EVENT_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


class Settings:
    supabase_url = "https://project.example.supabase.co"
    supabase_service_role_key = "server-only-test-key"


def test_record_consent_event_sends_only_versioned_metadata(monkeypatch):
    calls = []
    monkeypatch.setattr(privacy, "_rpc", lambda settings, name, payload: calls.append((name, payload)) or str(EVENT_ID))
    result = privacy.record_consent_event(
        Settings(), user_id=USER_ID, consent_scope="vision_deepseek",
        action="accepted", policy_version="privacy-v1", consent_version="vision-v1",
    )
    assert result == str(EVENT_ID)
    assert calls[0][0] == "record_privacy_consent_event"
    assert calls[0][1]["p_user_id"] == str(USER_ID)
    assert "image" not in str(calls[0][1]).lower()
    assert "prompt" not in calls[0][1]


def test_vision_transfer_requires_consent_evidence(monkeypatch):
    calls = []
    monkeypatch.setattr(privacy, "_rpc", lambda *args: calls.append(args))
    with pytest.raises(ValueError):
        privacy.record_ai_transfer_event(
            Settings(), user_id=USER_ID, provider="deepseek",
            model="deepseek-flash", operation="vision", outcome="attempted",
        )
    assert calls == []


def test_transfer_audit_rpc_payload_contains_no_user_content(monkeypatch):
    calls = []
    monkeypatch.setattr(privacy, "_rpc", lambda settings, name, payload: calls.append((name, payload)) or str(EVENT_ID))
    privacy.record_ai_transfer_event(
        Settings(), user_id=USER_ID, provider="deepseek", model="deepseek-flash",
        operation="vision", outcome="attempted", consent_event_id=EVENT_ID,
    )
    name, payload = calls[0]
    assert name == "record_ai_data_transfer_event"
    assert set(payload) == {
        "p_user_id", "p_provider", "p_model", "p_operation",
        "p_outcome", "p_consent_event_id", "p_correlation_id",
    }
    assert not any(word in str(payload).lower() for word in ("prompt", "image_data", "base64", "signed_url"))


def test_consent_status_rejects_malformed_database_rows(monkeypatch):
    monkeypatch.setattr(privacy, "_rpc", lambda *args: [{"consent_scope": "unknown", "action": "accepted"}])
    with pytest.raises(PrivacyGovernanceUnavailable):
        privacy.get_consent_status(Settings(), user_id=USER_ID)


def test_privacy_request_list_is_bounded(monkeypatch):
    monkeypatch.setattr(privacy, "_rpc", lambda *args: [])
    assert privacy.list_privacy_requests(Settings(), user_id=USER_ID, limit=100) == []
    with pytest.raises(ValueError):
        privacy.list_privacy_requests(Settings(), user_id=USER_ID, limit=101)
