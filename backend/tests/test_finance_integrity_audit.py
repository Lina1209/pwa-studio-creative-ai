import pytest

from app.services.finance_integrity_audit import audit_finance_integrity


USER = "user-1"
JOB = "job-1"


def ledger(entry_id, delta_available, delta_reserved, available, reserved, **changes):
    row = {
        "entry_id": entry_id,
        "user_id": USER,
        "delta_available": delta_available,
        "delta_reserved": delta_reserved,
        "balance_available_after": available,
        "balance_reserved_after": reserved,
        "created_at": f"2026-11-23T10:00:{entry_id:02d}Z",
    }
    row.update(changes)
    return row


def cost_event(**changes):
    row = {
        "event_id": 1,
        "job_id": JOB,
        "operation_key": "operation-001",
        "provider": "provider-a",
        "provider_usage_id": "usage-001",
        "cost_source": "reported",
        "cost_usd": "0.125",
    }
    row.update(changes)
    return row


def audit(**changes):
    args = {
        "ledger_entries": [
            ledger(1, 100, 0, 100, 0),
            ledger(2, -20, 20, 80, 20),
        ],
        "wallets": {USER: {"available_credits": 80, "reserved_credits": 20}},
        "generation_jobs": [{"job_id": JOB, "expects_provider_cost": True}],
        "provider_cost_events": [cost_event()],
        "opening_balances": {USER: (0, 0)},
        "complete": True,
    }
    args.update(changes)
    return audit_finance_integrity(**args)


def test_consistent_snapshots_are_healthy():
    report = audit()
    assert report["status"] == "healthy"
    assert report["counts"] == {"critical": 0, "warning": 0}
    assert report["complete"] is True


def test_ledger_discontinuity_is_critical_even_when_wallet_matches_last_row():
    report = audit(ledger_entries=[
        ledger(1, 100, 0, 100, 0),
        ledger(2, -20, 20, 95, 25),
    ], wallets={USER: {"available_credits": 95, "reserved_credits": 25}})
    assert report["status"] == "critical"
    assert any(item["code"] == "ledger_discontinuity" for item in report["findings"])


def test_wallet_mismatch_is_critical():
    report = audit(wallets={USER: {"available_credits": 79, "reserved_credits": 20}})
    assert report["status"] == "critical"
    assert any(item["code"] == "wallet_ledger_mismatch" for item in report["findings"])


def test_missing_opening_balance_is_warning_not_false_clean():
    report = audit(opening_balances={})
    assert report["status"] == "warning"
    assert any(item["code"] == "opening_balance_unverified" for item in report["findings"])


def test_incomplete_source_snapshot_never_reports_healthy():
    report = audit(complete=False)
    assert report["status"] == "incomplete"
    assert any(item["code"] == "source_snapshot_incomplete" for item in report["findings"])


def test_missing_expected_provider_cost_is_warning():
    report = audit(provider_cost_events=[])
    assert report["status"] == "warning"
    assert any(item["code"] == "expected_provider_cost_missing" for item in report["findings"])


def test_orphan_cost_event_is_critical():
    report = audit(provider_cost_events=[cost_event(job_id="missing-job")])
    assert report["status"] == "critical"
    assert any(item["code"] == "orphan_or_invalid_provider_cost_event" for item in report["findings"])


def test_duplicate_operation_and_provider_usage_ids_are_detected():
    second = cost_event(event_id=2, operation_key="operation-002")
    report = audit(provider_cost_events=[cost_event(), second])
    codes = {item["code"] for item in report["findings"]}
    assert report["status"] == "critical"
    assert "duplicate_provider_usage_id" in codes


def test_unknown_cost_requires_null_amount():
    report = audit(provider_cost_events=[cost_event(cost_source="unknown", cost_usd="0.1")])
    assert report["status"] == "critical"
    assert any(item["code"] == "invalid_provider_cost_evidence" for item in report["findings"])


@pytest.mark.parametrize("bad", [
    ledger(1, True, 0, 100, 0),
    ledger(1, 100, 0, 100, 0, created_at="2026-11-23T10:00:00"),
    "not-a-row",
])
def test_invalid_ledger_rows_fail_closed(bad):
    report = audit(ledger_entries=[bad])
    assert report["status"] == "critical"
    assert any(item["code"] == "invalid_ledger_row" for item in report["findings"])


def test_audit_does_not_leak_raw_provider_metadata():
    event = cost_event(metadata={"prompt": "private prompt"}, provider_usage_id="private-usage")
    report = audit(provider_cost_events=[event])
    serialized = str(report)
    assert "private prompt" not in serialized
    assert "private-usage" not in serialized


def test_duplicate_operation_key_is_detected_even_with_distinct_usage_ids():
    second = cost_event(
        event_id=2,
        provider_usage_id="usage-002",
    )
    report = audit(provider_cost_events=[cost_event(), second])
    assert report["status"] == "critical"
    assert any(item["code"] == "duplicate_provider_operation_key" for item in report["findings"])


def test_completeness_must_be_explicitly_confirmed():
    report = audit_finance_integrity(
        ledger_entries=[],
        wallets={},
        generation_jobs=[],
        provider_cost_events=[],
    )
    assert report["status"] == "incomplete"
    assert report["complete"] is False


def test_wallet_without_ledger_history_is_not_reported_healthy():
    report = audit(
        ledger_entries=[],
        wallets={USER: {"available_credits": 0, "reserved_credits": 0}},
    )
    assert report["status"] == "warning"
    assert any(item["code"] == "ledger_history_missing" for item in report["findings"])
