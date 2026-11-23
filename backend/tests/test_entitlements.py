from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from app.core.config import Settings
from app.services import entitlements


USER = UUID("11111111-1111-4111-8111-111111111111")
ASSIGNMENT = "22222222-2222-4222-8222-222222222222"
PLAN = "33333333-3333-4333-8333-333333333333"


class FakeResponse:
    def __init__(self, data):
        self.data = data
        self.content = b"[]"

    def raise_for_status(self):
        return None

    def json(self):
        return self.data


class FakeClient:
    def __init__(self, responses, calls):
        self.responses = responses
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, *, params, headers):
        table = url.rsplit("/", 1)[-1]
        self.calls.append((table, params, headers))
        return FakeResponse(self.responses[table].pop(0))


def configured_settings():
    return Settings(
        supabase_url="https://example.supabase.co/",
        supabase_service_role_key="sb_secret_test_key",
    )


def _active_assignment():
    now = datetime.now(timezone.utc)
    return {
        "id": ASSIGNMENT,
        "user_id": str(USER),
        "approved_plan_version_id": PLAN,
        "starts_at": (now.replace(day=1)).isoformat(),
        "ends_at": (now.replace(day=1).replace(month=12)).isoformat(),
        "created_at": now.isoformat(),
    }


def test_no_active_plan_does_not_promote_pending_assignment(monkeypatch):
    calls = []
    responses = {
        "user_plan_assignments": [[_active_assignment()]],
        "user_plan_assignment_events": [[
            {"id": 1, "assignment_id": ASSIGNMENT, "event_type": "created", "occurred_at": "2026-11-01T00:00:00+00:00"},
        ]],
    }
    monkeypatch.setattr(
        entitlements.httpx, "Client",
        lambda timeout: FakeClient(responses, calls),
    )
    result = entitlements.resolve_user_entitlements(configured_settings(), user_id=USER)
    assert result["status"] == "no_active_plan"
    assert result["plan"] is None
    assert result["features"] == []
    assert result["capabilities_enabled"] is False
    assert result["pending_assignment_exists"] is True
    assert [call[0] for call in calls] == ["user_plan_assignments", "user_plan_assignment_events"]


def test_multiple_active_assignments_fail_closed(monkeypatch):
    calls = []
    responses = {
        "user_plan_assignments": [[
            _active_assignment(),
            {**_active_assignment(), "id": "44444444-4444-4444-8444-444444444444"},
        ]],
        "user_plan_assignment_events": [[
            {"id": 2, "assignment_id": ASSIGNMENT, "event_type": "activated", "occurred_at": "2026-11-01T00:00:00+00:00"},
            {"id": 1, "assignment_id": "44444444-4444-4444-8444-444444444444", "event_type": "activated", "occurred_at": "2026-11-01T00:00:00+00:00"},
        ]],
    }
    monkeypatch.setattr(
        entitlements.httpx, "Client",
        lambda timeout: FakeClient(responses, calls),
    )
    result = entitlements.resolve_user_entitlements(configured_settings(), user_id=USER)
    assert result["status"] == "ambiguous_active_assignments"
    assert result["capabilities_enabled"] is False
    assert result["plan"] is None


def test_active_plan_reports_utc_usage_and_unenforced_dimensions(monkeypatch):
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    calls = []
    responses = {
        "user_plan_assignments": [[_active_assignment()]],
        "user_plan_assignment_events": [[
            {"id": 2, "assignment_id": ASSIGNMENT, "event_type": "activated", "occurred_at": "2026-11-01T00:00:00+00:00"},
        ]],
        "approved_plan_versions": [{
            "id": PLAN,
            "plan_code": "creator",
            "plan_version": 3,
            "display_name": "Creator",
            "billing_period": "month",
            "period_days": 30,
            "credits_per_period": 1000,
            "price_minor": None,
            "currency": None,
            "limits_json": {
                "daily_image_generations": 10,
                "monthly_image_generations": 100,
                "max_concurrent_ai_requests": 2,
                "daily_generation_jobs": 20,
                "monthly_generation_jobs": 100,
                "max_parallel_jobs": 2,
                "max_video_seconds": 60,
                "max_resolution": "1080p",
            },
            "features_json": ["image", "video", "audio", "ai"],
        }],
        "plan_quota_reservations": [
            {"feature_key": "daily_image_generations", "reserved_units": 3,
             "status": "completed", "period_start": day_start.isoformat()},
            {"feature_key": "monthly_image_generations", "reserved_units": 7,
             "status": "reserved", "period_start": month_start.isoformat()},
            {"feature_key": "max_concurrent_ai_requests", "reserved_units": 1,
             "status": "reserved", "period_start": now.isoformat()},
            {"feature_key": "max_concurrent_ai_requests", "reserved_units": 1,
             "status": "completed", "period_start": now.isoformat()},
            {"feature_key": "daily_generation_jobs", "reserved_units": 2,
             "status": "completed", "period_start": day_start.isoformat()},
            {"feature_key": "monthly_generation_jobs", "reserved_units": 3,
             "status": "reserved", "period_start": month_start.isoformat()},
            {"feature_key": "max_parallel_jobs", "reserved_units": 1,
             "status": "reserved", "period_start": "1970-01-01T00:00:00+00:00"},
            {"feature_key": "max_parallel_jobs", "reserved_units": 1,
             "status": "completed", "period_start": "1970-01-01T00:00:00+00:00"},
        ],
    }
    monkeypatch.setattr(
        entitlements.httpx, "Client",
        lambda timeout: FakeClient(responses, calls),
    )
    result = entitlements.resolve_user_entitlements(configured_settings(), user_id=USER)

    assert result["status"] == "active"
    assert result["capabilities_enabled"] is True
    assert result["plan"]["code"] == "creator"
    assert result["features"] == ["image", "video", "audio", "ai"]
    assert result["capabilities"]["image"]["available"] is True
    assert result["capabilities"]["video"]["available"] is False
    assert result["capabilities"]["ai"]["available"] is False
    assert result["quotas"]["daily_image_generations"]["limit"] == 10
    assert result["quotas"]["daily_image_generations"]["used"] == 3
    assert result["quotas"]["daily_image_generations"]["remaining"] == 7
    assert result["quotas"]["daily_image_generations"]["enforced"] is True
    assert result["quotas"]["daily_image_generations"]["configured"] is True
    assert result["quotas"]["daily_image_generations"]["reset_at"] == (day_start + timedelta(days=1)).isoformat()
    assert result["quotas"]["monthly_image_generations"]["used"] == 7
    assert result["quotas"]["monthly_image_generations"]["reset_at"] == (
        (month_start.replace(day=28) + timedelta(days=4)).replace(day=1).isoformat()
    )
    assert result["quotas"]["max_concurrent_ai_requests"]["used"] == 1
    assert result["quotas"]["max_video_seconds"]["enforced"] is True
    assert result["quotas"]["max_video_seconds"]["limit"] == 60
    assert result["quotas"]["max_resolution"]["enforced"] is True
    assert result["quotas"]["max_parallel_jobs"]["used"] == 1
    assert result["quotas"]["daily_generation_jobs"]["used"] == 2
    assert result["quotas"]["monthly_generation_jobs"]["used"] == 3
    assert result["activation_enabled"] is False
    assert result["checkout_enabled"] is False
    assert result["credits_granted"] is False
    assert [call[0] for call in calls] == [
        "user_plan_assignments", "user_plan_assignment_events",
        "approved_plan_versions", "plan_quota_reservations",
    ]


def test_invalid_active_plan_snapshot_fails_closed(monkeypatch):
    calls = []
    responses = {
        "user_plan_assignments": [[_active_assignment()]],
        "user_plan_assignment_events": [[
            {"id": 2, "assignment_id": ASSIGNMENT, "event_type": "activated", "occurred_at": "2026-11-01T00:00:00+00:00"},
        ]],
        "approved_plan_versions": [],
    }
    monkeypatch.setattr(
        entitlements.httpx, "Client",
        lambda timeout: FakeClient(responses, calls),
    )
    with pytest.raises(entitlements.EntitlementsUnavailable):
        entitlements.resolve_user_entitlements(configured_settings(), user_id=USER)


def test_future_scheduled_assignment_is_reported_pending_not_active(monkeypatch):
    now = datetime.now(timezone.utc)
    future = {
        **_active_assignment(),
        "starts_at": (now.replace(day=1) + timedelta(days=40)).isoformat(),
        "ends_at": (now.replace(day=1) + timedelta(days=70)).isoformat(),
    }
    calls = []
    responses = {
        "user_plan_assignments": [[future]],
        "user_plan_assignment_events": [[
            {"id": 3, "assignment_id": ASSIGNMENT, "event_type": "scheduled", "occurred_at": now.isoformat()},
        ]],
    }
    monkeypatch.setattr(
        entitlements.httpx, "Client",
        lambda timeout: FakeClient(responses, calls),
    )
    result = entitlements.resolve_user_entitlements(configured_settings(), user_id=USER)
    assert result["status"] == "no_active_plan"
    assert result["pending_assignment_exists"] is True
    assert result["capabilities_enabled"] is False
