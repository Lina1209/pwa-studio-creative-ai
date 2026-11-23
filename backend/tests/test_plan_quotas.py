import pytest
from uuid import UUID

from app.core.config import Settings
from app.services import plan_quotas


USER = UUID("11111111-1111-4111-8111-111111111111")
REQUEST = UUID("22222222-2222-4222-8222-222222222222")
RESERVATION = UUID("33333333-3333-4333-8333-333333333333")
ASSIGNMENT = UUID("44444444-4444-4444-8444-444444444444")


def _settings():
    return Settings(supabase_url="https://example.supabase.co", supabase_service_role_key="service-role-test-key")


def _row(**overrides):
    data = {
        "reservation_id": str(RESERVATION),
        "assignment_id": str(ASSIGNMENT),
        "feature_limit": 20,
        "used_units": 3,
        "remaining_units": 17,
        "period_start": "2026-11-01T00:00:00+00:00",
        "status": "reserved",
        "replayed": False,
    }
    data.update(overrides)
    return data


def test_reserve_plan_quota_returns_verified_reservation(monkeypatch):
    monkeypatch.setattr(plan_quotas, "_rpc", lambda *a, **k: [_row()])
    result = plan_quotas.reserve_plan_quota(
        _settings(), user_id=USER, request_id=REQUEST,
        feature_key="monthly_video_generations",
        operation_key="video-job-0001",
    )
    assert result.reservation_id == RESERVATION
    assert result.assignment_id == ASSIGNMENT
    assert result.remaining_units == 17
    assert result.replayed is False


def test_reserve_plan_quota_rejects_inconsistent_totals(monkeypatch):
    monkeypatch.setattr(plan_quotas, "_rpc", lambda *a, **k: [_row(remaining_units=99)])
    with pytest.raises(plan_quotas.PlanQuotaUnavailable):
        plan_quotas.reserve_plan_quota(
            _settings(), user_id=USER, request_id=REQUEST,
            feature_key="daily_ai_requests", operation_key="request-0001",
        )


@pytest.mark.parametrize("feature", ["unknown", "", "credits"])
def test_reserve_plan_quota_rejects_unknown_feature_before_rpc(monkeypatch, feature):
    monkeypatch.setattr(plan_quotas, "_rpc", lambda *a, **k: (_ for _ in ()).throw(AssertionError("RPC must not run")))
    with pytest.raises(ValueError):
        plan_quotas.reserve_plan_quota(
            _settings(), user_id=USER, request_id=REQUEST,
            feature_key=feature, operation_key="request-0001",
        )


def test_reserve_plan_quota_rejects_boolean_units(monkeypatch):
    monkeypatch.setattr(plan_quotas, "_rpc", lambda *a, **k: (_ for _ in ()).throw(AssertionError("RPC must not run")))
    with pytest.raises(ValueError):
        plan_quotas.reserve_plan_quota(
            _settings(), user_id=USER, request_id=REQUEST,
            feature_key="daily_ai_requests", operation_key="request-0001", units=True,
        )


def test_finish_plan_quota_reservation_verifies_terminal_state(monkeypatch):
    monkeypatch.setattr(plan_quotas, "_rpc", lambda *a, **k: [{"status": "released", "replayed": False}])
    assert plan_quotas.finish_plan_quota_reservation(
        _settings(), user_id=USER, reservation_id=RESERVATION, completed=False
    ) is False


def test_finish_plan_quota_reservation_rejects_wrong_terminal_state(monkeypatch):
    monkeypatch.setattr(plan_quotas, "_rpc", lambda *a, **k: [{"status": "completed", "replayed": False}])
    with pytest.raises(plan_quotas.PlanQuotaUnavailable):
        plan_quotas.finish_plan_quota_reservation(
            _settings(), user_id=USER, reservation_id=RESERVATION, completed=False
        )
