import json
from uuid import UUID

import pytest
from fastapi import HTTPException, Response

from app import main
from app.core.config import Settings
from app.schemas import PricingQuoteRequest
from app.services.auth import StudioUser
from app.services.pricing_service import verify_pricing_quote


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
            pricing_quote_signing_secret=SECRET,
            pricing_catalog_json=json.dumps(catalog),
        ),
    )
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
