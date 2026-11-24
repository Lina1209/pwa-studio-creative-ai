from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.schemas import ReportCreateRequest, SuspensionCreateRequest, SuspensionRevokeRequest, UserBlockRequest


USER_ID = "11111111-1111-4111-8111-111111111111"


def test_suspension_accepts_timezone_aware_future_expiration():
    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    model = SuspensionCreateRequest(user_id=USER_ID, reason="Repeated abuse", expires_at=future)
    assert model.expires_at.endswith("+00:00")


@pytest.mark.parametrize("value", [
    "not-a-date",
    "2027-01-01T12:00:00",
    "2020-01-01T12:00:00+00:00",
])
def test_suspension_rejects_invalid_or_ambiguous_expiration(value):
    with pytest.raises(ValidationError):
        SuspensionCreateRequest(user_id=USER_ID, reason="Repeated abuse", expires_at=value)


def test_suspension_allows_permanent_restriction():
    model = SuspensionCreateRequest(user_id=USER_ID, reason="Repeated abuse")
    assert model.expires_at is None


@pytest.mark.parametrize("model,kwargs", [
    (SuspensionCreateRequest, {"user_id": "x" * 36, "reason": "Repeated abuse"}),
    (SuspensionRevokeRequest, {"suspension_id": "x" * 36}),
    (UserBlockRequest, {"user_id": "x" * 36}),
    (ReportCreateRequest, {"category": "spam", "description": "This is spam content", "reported_user_id": "x" * 36}),
])
def test_uuid_fields_reject_non_uuid_strings(model, kwargs):
    with pytest.raises(ValidationError):
        model(**kwargs)


def test_report_without_target_user_remains_valid():
    model = ReportCreateRequest(category="spam", description="This is spam content")
    assert model.reported_user_id is None
