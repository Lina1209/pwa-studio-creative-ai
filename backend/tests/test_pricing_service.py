from datetime import datetime, timedelta, timezone
import json
from uuid import UUID

import pytest

from app.services.pricing_service import (
    PricingCatalog,
    PricingError,
    PricingRule,
    canonical_request_hash,
    issue_pricing_quote,
    load_pricing_catalog,
    verify_pricing_quote,
)


USER = UUID("11111111-1111-4111-8111-111111111111")
OTHER_USER = UUID("22222222-2222-4222-8222-222222222222")
SECRET = "pricing-test-signing-secret-with-32-bytes-minimum"
NOW = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
CATALOG = PricingCatalog(
    "approved-test-v3",
    (PricingRule("image_generation", "provider-a", "model-a", 7, "image", 1, 4),),
)


def make_quote(**overrides):
    values = {
        "secret": SECRET,
        "catalog": CATALOG,
        "user_id": USER,
        "job_type": "image_generation",
        "provider": "provider-a",
        "model": "model-a",
        "request_hash": "a" * 64,
        "idempotency_key": "pricing-test-key-001",
        "quantity": 3,
        "now": NOW,
    }
    values.update(overrides)
    return issue_pricing_quote(**values)


def verify(snapshot, **overrides):
    values = {
        "secret": SECRET,
        "user_id": USER,
        "job_type": "image_generation",
        "provider": "provider-a",
        "model": "model-a",
        "request_hash": "a" * 64,
        "idempotency_key": "pricing-test-key-001",
        "now": NOW + timedelta(seconds=1),
    }
    values.update(overrides)
    return verify_pricing_quote(snapshot, **values)


def test_quote_uses_server_catalog_and_calculates_integer_amount():
    quote = make_quote()
    assert quote.amount == 21
    assert quote.price_version == "approved-test-v3"
    assert quote.snapshot()["maximum_authorized_charge"] == 21
    assert quote.snapshot()["credit_unit"] == "credit"
    verified = verify(quote.snapshot())
    assert verified.quote_id == quote.quote_id
    assert verified.amount == 21


def test_quote_is_bound_to_owner_and_exact_generation_request():
    snapshot = make_quote().snapshot()
    with pytest.raises(PricingError, match="does not match"):
        verify(snapshot, user_id=OTHER_USER)
    with pytest.raises(PricingError, match="does not match"):
        verify(snapshot, request_hash="b" * 64)
    with pytest.raises(PricingError, match="does not match"):
        verify(snapshot, model="model-b")
    with pytest.raises(PricingError, match="idempotency key"):
        verify(snapshot, idempotency_key="another-idempotency-key")


def test_quote_tampering_is_detected_even_when_amount_and_limit_are_changed():
    snapshot = make_quote().snapshot()
    snapshot["amount"] = 1
    snapshot["maximum_authorized_charge"] = 1
    with pytest.raises(PricingError, match="signature"):
        verify(snapshot)


def test_quote_expiry_is_enforced():
    snapshot = make_quote(ttl_seconds=60).snapshot()
    with pytest.raises(PricingError, match="expired"):
        verify(snapshot, now=NOW + timedelta(seconds=61))


def test_catalog_must_contain_an_explicit_approved_rule():
    with pytest.raises(PricingError, match="No approved price"):
        make_quote(model="unpriced-model")


def test_quantity_and_quote_lifetime_are_bounded():
    with pytest.raises(PricingError, match="quantity"):
        make_quote(quantity=True)
    with pytest.raises(PricingError, match="quantity"):
        make_quote(quantity=5)
    with pytest.raises(PricingError, match="lifetime"):
        make_quote(ttl_seconds=3600)


def test_signing_secret_must_be_configured_and_long_enough():
    with pytest.raises(PricingError, match="signing secret"):
        make_quote(secret="short")


def test_catalog_rejects_duplicate_rules_and_invalid_credit_rates():
    rule = PricingRule("image_generation", "provider-a", "model-a", 7, "image")
    with pytest.raises(PricingError, match="duplicate"):
        PricingCatalog("v1", (rule, rule))
    with pytest.raises(PricingError, match="positive integer"):
        PricingRule("image_generation", "provider-a", "model-a", True, "image")


def test_canonical_request_hash_is_stable_and_rejects_non_json_values():
    assert canonical_request_hash({"b": 2, "a": 1}) == canonical_request_hash({"a": 1, "b": 2})
    with pytest.raises(PricingError, match="canonical JSON"):
        canonical_request_hash({"not_json": object()})


def test_quote_is_bound_to_exact_project_or_scene_target():
    scene_id = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
    project_id = UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")
    snapshot = make_quote(studio_scene_id=scene_id).snapshot()
    verify(snapshot, studio_scene_id=scene_id)
    with pytest.raises(PricingError, match="project or scene"):
        verify(snapshot, studio_scene_id=project_id)
    with pytest.raises(PricingError, match="project or scene"):
        verify(snapshot)
    with pytest.raises(PricingError, match="both"):
        make_quote(project_id=project_id, studio_scene_id=scene_id)


def test_server_catalog_loader_parses_rules_and_fails_closed_on_invalid_schema():
    catalog = load_pricing_catalog(json.dumps({
        "version": "server-v1",
        "rules": [{
            "job_type": "image_generation",
            "provider": "provider-a",
            "model": "model-a",
            "credits_per_unit": 9,
            "unit_label": "image",
            "min_quantity": 1,
            "max_quantity": 2,
        }],
    }))
    assert catalog.version == "server-v1"
    assert catalog.find("image_generation", "provider-a", "model-a").credits_per_unit == 9
    assert load_pricing_catalog('{"version":"unconfigured","rules":[]}').rules == ()
    with pytest.raises(PricingError, match="schema"):
        load_pricing_catalog('{"version":"v1","rules":[],"client_price":1}')
    with pytest.raises(PricingError, match="rule schema"):
        load_pricing_catalog(json.dumps({
            "version": "v1",
            "rules": [{
                "job_type": "image_generation",
                "provider": "provider-a",
                "model": "model-a",
                "credits_per_unit": 9,
                "unit_label": "image",
                "client_amount": 1,
            }],
        }))
    with pytest.raises(PricingError, match="valid JSON"):
        load_pricing_catalog("{broken")
