import json
from uuid import UUID

import pytest
from fastapi import HTTPException, Response

from app import main
from app.core.config import Settings
from app.schemas import PricingQuoteRequest
from app.services.auth import StudioUser
from app.services.pricing_service import canonical_request_hash, verify_pricing_quote
from app.services.generation_jobs import PersistedPricingQuote


USER_ID = UUID("11111111-1111-4111-8111-111111111111")
SCENE_ID = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
SECRET = "endpoint-test-signing-secret-with-32-bytes"


def test_quote_endpoint_fails_closed_when_catalog_is_empty(monkeypatch):
    monkeypatch.setattr(
        main,
        "settings",
        Settings(
            pricing_quote_signing_secret=SECRET,
            pricing_catalog_json='{"version":"unconfigured","rules":[]}',
        ),
    )
    with pytest.raises(HTTPException) as error:
        main.create_pricing_quote(
            PricingQuoteRequest(
                job_type="image_generation",
                provider="provider-a",
                model="model-a",
                studio_scene_id=SCENE_ID,
                request_snapshot={"prompt": "test"},
            ),
            Response(),
            "pricing-endpoint-key-001",
            StudioUser(str(USER_ID), None, "creator"),
        )
    assert error.value.status_code == 503


def test_quote_endpoint_returns_signed_owner_and_scene_bound_preview(monkeypatch):
    catalog = {
        "version": "test-catalog-v1",
        "rules": [{
            "job_type": "image_generation",
            "provider": "provider-a",
            "model": "model-a",
            "credits_per_unit": 12,
            "unit_label": "image",
            "min_quantity": 1,
            "max_quantity": 2,
        }],
    }
    monkeypatch.setattr(
        main,
        "settings",
        Settings(
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="sb_secret_test_key",
            pricing_quote_signing_secret=SECRET,
            pricing_catalog_json=json.dumps(catalog),
        ),
    )
    stored = {}
    def persist(_settings, **kwargs):
        key = kwargs["idempotency_key"]
        if key not in stored:
            stored[key] = kwargs["quote_snapshot"]
            return PersistedPricingQuote(stored[key], True, False)
        return PersistedPricingQuote(stored[key], False, False)
    monkeypatch.setattr(main, "store_pricing_quote", persist)
    response = Response()
    snapshot = main.create_pricing_quote(
        PricingQuoteRequest(
            job_type="image_generation",
            provider="provider-a",
            model="model-a",
            studio_scene_id=SCENE_ID,
            request_snapshot={"prompt": "a safe test scene"},
            quantity=2,
        ),
        response,
        "pricing-endpoint-key-002",
        StudioUser(str(USER_ID), None, "creator"),
    )

    assert snapshot["amount"] == 24
    assert snapshot["maximum_authorized_charge"] == 24
    assert snapshot["user_id"] == str(USER_ID)
    assert snapshot["studio_scene_id"] == str(SCENE_ID)
    assert snapshot["idempotency_key"] == "pricing-endpoint-key-002"
    assert response.headers["Cache-Control"] == "private, no-store"
    verified = verify_pricing_quote(
        snapshot,
        secret=SECRET,
        user_id=USER_ID,
        job_type="image_generation",
        provider="provider-a",
        model="model-a",
        request_hash=snapshot["request_hash"],
        idempotency_key="pricing-endpoint-key-002",
        studio_scene_id=SCENE_ID,
    )
    assert verified.amount == 24
    assert snapshot["request_hash"] == canonical_request_hash({
        "prompt": "a safe test scene",
        "quantity": 2,
    })

    # A second call with the same key and same request returns the byte-for-byte
    # original signed quote, rather than issuing a fresh quote ID or expiry.
    second = main.create_pricing_quote(
        PricingQuoteRequest(
            job_type="image_generation",
            provider="provider-a",
            model="model-a",
            studio_scene_id=SCENE_ID,
            request_snapshot={"prompt": "a safe test scene"},
            quantity=2,
        ),
        Response(),
        "pricing-endpoint-key-002",
        StudioUser(str(USER_ID), None, "creator"),
    )
    assert second == snapshot


def test_quote_endpoint_rejects_expired_persisted_idempotency_key(monkeypatch):
    catalog = {
        "version": "test-catalog-v1",
        "rules": [{
            "job_type": "image_generation",
            "provider": "provider-a",
            "model": "model-a",
            "credits_per_unit": 12,
            "unit_label": "image",
            "min_quantity": 1,
            "max_quantity": 2,
        }],
    }
    monkeypatch.setattr(
        main,
        "settings",
        Settings(
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="sb_secret_test_key",
            pricing_quote_signing_secret=SECRET,
            pricing_catalog_json=json.dumps(catalog),
        ),
    )
    monkeypatch.setattr(
        main,
        "store_pricing_quote",
        lambda _settings, **kwargs: PersistedPricingQuote(kwargs["quote_snapshot"], False, True),
    )
    with pytest.raises(HTTPException) as error:
        main.create_pricing_quote(
            PricingQuoteRequest(
                job_type="image_generation",
                provider="provider-a",
                model="model-a",
                request_snapshot={"prompt": "expired quote"},
            ),
            Response(),
            "pricing-endpoint-key-expired",
            StudioUser(str(USER_ID), None, "creator"),
        )
    assert error.value.status_code == 409


def test_quote_endpoint_rejects_quantity_conflicting_with_request_snapshot(monkeypatch):
    catalog = {
        "version": "test-catalog-v1",
        "rules": [{
            "job_type": "image_generation",
            "provider": "provider-a",
            "model": "model-a",
            "credits_per_unit": 12,
            "unit_label": "image",
            "min_quantity": 1,
            "max_quantity": 2,
        }],
    }
    monkeypatch.setattr(
        main,
        "settings",
        Settings(
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="sb_secret_test_key",
            pricing_quote_signing_secret=SECRET,
            pricing_catalog_json=json.dumps(catalog),
        ),
    )
    monkeypatch.setattr(
        main,
        "store_pricing_quote",
        lambda **kwargs: pytest.fail("Mismatched quantity must be rejected before persistence"),
    )
    with pytest.raises(HTTPException) as error:
        main.create_pricing_quote(
            PricingQuoteRequest(
                job_type="image_generation",
                provider="provider-a",
                model="model-a",
                request_snapshot={"prompt": "quantity mismatch", "quantity": 1},
                quantity=2,
            ),
            Response(),
            "pricing-endpoint-key-mismatch",
            StudioUser(str(USER_ID), None, "creator"),
        )
    assert error.value.status_code == 422
