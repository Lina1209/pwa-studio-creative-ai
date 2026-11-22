from decimal import Decimal
from uuid import UUID

import pytest

from app.services.admin_ai_cost_budget_controls import (
    resolve_unknown_reservation, update_global_budget, update_provider_budget,
)


def test_global_budget_validates_outstanding_cap_before_rpc(monkeypatch):
    import app.services.admin_ai_cost_budget_controls as controls
    monkeypatch.setattr(controls, "_rpc", lambda *a, **k: pytest.fail("RPC must not run"))
    with pytest.raises(ValueError):
        update_global_budget(None, enabled=True, daily_budget_usd="1", max_outstanding_usd="1.01")


def test_provider_is_allowlisted(monkeypatch):
    import app.services.admin_ai_cost_budget_controls as controls
    monkeypatch.setattr(controls, "_rpc", lambda *a, **k: pytest.fail("RPC must not run"))
    with pytest.raises(ValueError):
        update_provider_budget(None, provider="other", enabled=True, daily_budget_usd="1")


def test_unknown_reservation_zero_cost_is_valid(monkeypatch):
    import app.services.admin_ai_cost_budget_controls as controls
    captured = {}
    monkeypatch.setattr(controls, "_rpc", lambda settings, name, payload: captured.update(payload) or True)
    result = resolve_unknown_reservation(
        None, request_id=UUID("44444444-4444-4444-8444-444444444444"),
        resolution="record_estimated_cost", actual_estimated_cost_usd=Decimal("0"),
        note="Provider confirmed zero billable tokens",
    )
    assert result is True
    assert captured["p_actual_estimated_cost_usd"] == "0"


def test_unknown_reservation_requires_reason(monkeypatch):
    import app.services.admin_ai_cost_budget_controls as controls
    monkeypatch.setattr(controls, "_rpc", lambda *a, **k: pytest.fail("RPC must not run"))
    with pytest.raises(ValueError):
        resolve_unknown_reservation(
            None, request_id=UUID("44444444-4444-4444-8444-444444444444"),
            resolution="confirm_no_charge", actual_estimated_cost_usd=None, note="bad",
        )
