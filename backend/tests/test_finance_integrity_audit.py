import pytest

from app.services.finance_integrity_audit import audit_finance_integrity


USER = "user-1"
JOB = "job-1"


def ledger(entry_id, delta_available, delta_reserved, available, reserved, **changes):
    row = {
        "entry_id": entry_id,
        "user_id": USER,
        "operation_type": "grant" if entry_id == 1 else "reserve",
        "operation_key": f"operation-key-{entry_id:04d}",
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
        "user_id": USER,
        "operation_key": "operation-001",
        "provider": "provider-a",
        "model": "image-v1",
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
        "generation_jobs": [{"job_id": JOB, "user_id": USER, "provider": "provider-a", "model": "image-v1", "status": "succeeded", "expects_provider_cost": True}],
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


def test_provider_cost_owner_or_provider_mismatch_is_critical():
    report = audit(provider_cost_events=[cost_event(user_id="different-user")])
    assert report["status"] == "critical"
    assert any(item["code"] == "provider_cost_job_identity_mismatch" for item in report["findings"])


def projection_rows():
    return {
        "credit_lots": [{
            "lot_id": "lot-1", "user_id": USER, "granted_credits": 100,
            "available_credits": 80, "reserved_credits": 20,
        }],
        "credit_holds": [{
            "hold_id": "hold-1", "user_id": USER, "amount": 20, "status": "held",
        }],
        "hold_allocations": [{
            "allocation_id": "allocation-1", "user_id": USER,
            "hold_id": "hold-1", "lot_id": "lot-1", "amount": 20, "status": "held",
        }],
    }


def test_consistent_lots_holds_and_allocations_are_healthy():
    report = audit(**projection_rows())
    assert report["status"] == "healthy"


def test_lot_wallet_projection_mismatch_is_critical():
    rows = projection_rows()
    rows["credit_lots"][0]["available_credits"] = 79
    report = audit(**rows)
    assert report["status"] == "critical"
    assert any(item["code"] == "lot_wallet_projection_mismatch" for item in report["findings"])


def test_held_reservation_without_full_allocation_is_critical():
    rows = projection_rows()
    rows["hold_allocations"][0]["amount"] = 19
    report = audit(**rows)
    assert report["status"] == "critical"
    assert any(item["code"] == "hold_allocation_total_mismatch" for item in report["findings"])


def test_orphan_or_cross_owner_allocation_is_critical():
    rows = projection_rows()
    rows["hold_allocations"][0]["lot_id"] = "missing-lot"
    report = audit(**rows)
    assert report["status"] == "critical"
    assert any(item["code"] == "orphan_hold_allocation" for item in report["findings"])


def test_duplicate_ledger_operation_key_is_critical():
    rows = [ledger(1, 100, 0, 100, 0), ledger(2, -20, 20, 80, 20, operation_key="operation-key-0001")]
    report = audit(ledger_entries=rows)
    assert report["status"] == "critical"
    assert any(item["code"] == "duplicate_ledger_operation_key" for item in report["findings"])


def test_zero_delta_ledger_entry_is_invalid():
    report = audit(ledger_entries=[ledger(1, 0, 0, 100, 0)])
    assert report["status"] == "critical"
    assert any(item["code"] == "invalid_ledger_row" for item in report["findings"])


def test_captured_allocations_cannot_exceed_original_lot_grant():
    report = audit(
        ledger_entries=[],
        wallets={USER: {"available_credits": 0, "reserved_credits": 0}},
        credit_lots=[{
            "lot_id": "lot-1", "user_id": USER, "granted_credits": 20,
            "available_credits": 0, "reserved_credits": 0,
        }],
        credit_holds=[{
            "hold_id": "hold-1", "user_id": USER, "amount": 21, "status": "captured",
        }],
        hold_allocations=[{
            "allocation_id": "allocation-1", "user_id": USER,
            "hold_id": "hold-1", "lot_id": "lot-1", "amount": 21, "status": "captured",
        }],
    )
    assert report["status"] == "critical"
    assert any(item["code"] == "lot_consumption_exceeds_grant" for item in report["findings"])



def successful_payment_rows():
    order_id = "11111111-1111-4111-8111-111111111111"
    return {
        "payment_orders": [{
            "id": order_id, "user_id": USER, "provider_code": "examplepay",
            "merchant_reference": "merchant-ref-0001", "provider_payment_id": "provider-payment-1",
            "idempotency_key": "11111111-1111-4111-8111-111111111112",
            "amount_minor": 99000, "currency_code": "KZT", "status": "succeeded",
            "paid_at": "2026-11-23T10:00:00Z", "closed_at": None,
        }],
        "payment_provider_events": [{
            "id": "event-1", "provider_code": "examplepay", "provider_event_id": "provider-event-1",
            "payment_order_id": order_id, "event_type": "payment.succeeded",
            "payload_sha256": "a" * 64, "signature_verified": True,
            "processing_status": "processed", "processed_at": "2026-11-23T10:00:00Z",
        }],
        "payment_order_events": [
            {
                "id": "order-event-0", "payment_order_id": order_id,
                "event_type": "order.created", "previous_status": None, "new_status": "created",
                "occurred_at": "2026-11-23T09:59:00Z",
            },
            {
                "id": "order-event-1", "payment_order_id": order_id,
                "event_type": "payment.succeeded", "previous_status": "created", "new_status": "succeeded",
                "occurred_at": "2026-11-23T10:00:00Z",
            },
        ],
        "purchase_items": [{
            "payment_order_id": order_id, "user_id": USER, "item_type": "credit_pack",
            "approved_credit_pack_version_id": "pack-version-1",
            "approved_plan_version_id": None, "sku_code": "mini_topup",
            "sku_version": 1, "amount_minor": 99000, "currency_code": "KZT",
            "credit_quantity": 850, "credit_validity_days": 365, "plan_period_days": None,
        }],
        "fulfillment_outbox": [{
            "id": "fulfillment-1", "payment_order_id": order_id, "user_id": USER,
            "provider_code": "examplepay", "amount_minor": 99000, "currency_code": "KZT",
            "status": "completed",
        }],
        "plan_assignments": [],
        "plan_assignment_events": [],
        "approved_plans": [],
        "quota_reservations": [],
        "quota_events": [],
        "credit_lots": [{
            "lot_id": "payment-lot-1", "user_id": USER,
            "source_reference": "payment-order:" + order_id,
            "idempotency_key": "payment-order:" + order_id,
            "granted_credits": 850, "available_credits": 80, "reserved_credits": 20,
        }],
    }


def test_verified_payment_and_exactly_once_credit_fulfillment_are_healthy():
    report = audit(**successful_payment_rows())
    assert report["status"] == "healthy"
    assert report["complete"] is True


def test_succeeded_payment_without_fulfillment_is_critical():
    rows = successful_payment_rows()
    rows["fulfillment_outbox"] = []
    report = audit(**rows)
    assert report["status"] == "critical"
    assert any(item["code"] == "settled_payment_fulfillment_missing" for item in report["findings"])


def test_refund_status_is_explicitly_not_fully_auditable():
    rows = successful_payment_rows()
    rows["payment_orders"][0]["status"] = "refunded"
    rows["payment_orders"][0]["closed_at"] = "2026-11-24T10:00:00Z"
    rows["payment_orders"][0]["paid_at"] = "2026-11-23T10:00:00Z"
    rows["payment_orders"][0]["provider_payment_id"] = "provider-payment-1"
    rows["payment_order_events"].append({
        "id": "order-event-2", "payment_order_id": rows["payment_orders"][0]["id"],
        "event_type": "payment.refunded", "previous_status": "succeeded", "new_status": "refunded",
        "occurred_at": "2026-11-24T10:00:00Z",
    })
    report = audit(**rows)
    assert report["status"] == "warning"
    codes = {item["code"] for item in report["findings"]}
    assert "refund_amounts_not_auditable" in codes
    assert "refund_lifecycle_not_implemented" in codes


def subscription_rows():
    order_id = "22222222-2222-4222-8222-222222222222"
    assignment_id = "33333333-3333-4333-8333-333333333333"
    reservation_id = "44444444-4444-4444-8444-444444444444"
    operation_key = "quota-operation-0001"
    digest = __import__("hashlib").md5(operation_key.encode()).hexdigest()
    rows = successful_payment_rows()
    rows["credit_lots"] = []
    rows["payment_orders"] = [{
        "id": order_id, "user_id": USER, "provider_code": "examplepay",
        "merchant_reference": "merchant-subscription-001", "provider_payment_id": "provider-sub-1",
        "idempotency_key": "22222222-2222-4222-8222-222222222223",
        "amount_minor": 149000, "currency_code": "KZT", "status": "succeeded",
        "paid_at": "2026-11-23T10:00:00Z", "closed_at": None,
    }]
    rows["payment_provider_events"][0]["payment_order_id"] = order_id
    rows["payment_provider_events"][0]["provider_event_id"] = "provider-sub-event-1"
    for event in rows["payment_order_events"]:
        event["payment_order_id"] = order_id
    rows["purchase_items"] = [{
        "payment_order_id": order_id, "user_id": USER, "item_type": "subscription",
        "approved_credit_pack_version_id": None,
        "approved_plan_version_id": "55555555-5555-4555-8555-555555555555",
        "sku_code": "studio_monthly", "sku_version": 1,
        "amount_minor": 149000, "currency_code": "KZT",
        "credit_quantity": 1300, "credit_validity_days": None, "plan_period_days": 30,
    }]
    rows["fulfillment_outbox"][0]["payment_order_id"] = order_id
    rows["plan_assignments"] = [{
        "id": assignment_id, "user_id": USER,
        "approved_plan_version_id": "55555555-5555-4555-8555-555555555555",
        "assignment_source": "verified_payment",
        "source_reference": "payment-order:" + order_id,
        "idempotency_key": "payment-order:" + order_id,
    }]
    rows["plan_assignment_events"] = [
        {"id": 1, "assignment_id": assignment_id, "user_id": USER, "event_type": "created", "event_key": "created-key-0001", "occurred_at": "2026-11-23T10:00:00Z"},
        {"id": 2, "assignment_id": assignment_id, "user_id": USER, "event_type": "activated", "event_key": "activated-key-0001", "occurred_at": "2026-11-23T10:01:00Z"},
    ]
    rows["approved_plans"] = [{
        "id": "55555555-5555-4555-8555-555555555555",
        "limits_json": {"daily_image_generations": 5},
    }]
    rows["quota_reservations"] = [{
        "id": reservation_id, "user_id": USER, "assignment_id": assignment_id,
        "request_id": JOB, "feature_key": "daily_image_generations",
        "period_start": "2026-11-23T00:00:00Z", "reserved_units": 1,
        "operation_key": operation_key, "status": "completed",
    }]
    rows["quota_events"] = [
        {"id": 1, "reservation_id": reservation_id, "user_id": USER, "event_type": "reserved", "event_key": "reserved:" + digest},
        {"id": 2, "reservation_id": reservation_id, "user_id": USER, "event_type": "completed", "event_key": "completed:" + digest},
    ]
    return rows


def test_subscription_assignment_and_quota_lifecycle_are_reconciled():
    report = audit(**subscription_rows())
    assert report["status"] == "healthy", report["findings"]


def test_completed_quota_without_terminal_event_is_critical():
    rows = subscription_rows()
    rows["quota_events"] = rows["quota_events"][:1]
    report = audit(**rows)
    assert report["status"] == "critical"
    assert any(item["code"] == "plan_quota_terminal_event_mismatch" for item in report["findings"])


def test_quota_reservation_for_another_assignment_owner_is_critical():
    rows = subscription_rows()
    rows["quota_reservations"][0]["user_id"] = "other-user"
    report = audit(**rows)
    assert report["status"] == "critical"
    assert any(item["code"] == "plan_quota_assignment_mismatch" for item in report["findings"])
