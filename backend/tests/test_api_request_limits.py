import pytest
from pydantic import ValidationError

from app.schemas import PricingQuoteRequest


def make_quote_request(snapshot):
    return PricingQuoteRequest(
        job_type="image_generation",
        provider="provider-a",
        model="model-a",
        request_snapshot=snapshot,
    )


def test_pricing_request_snapshot_accepts_normal_payload():
    request = make_quote_request({"prompt": "A quiet mountain lake", "width": 1024})
    assert request.request_snapshot["prompt"] == "A quiet mountain lake"


def test_pricing_request_snapshot_rejects_payload_over_32_kib():
    with pytest.raises(ValidationError, match="must not exceed 32 KiB"):
        make_quote_request({"prompt": "x" * (32 * 1024)})


def test_pricing_request_snapshot_rejects_non_json_numeric_values():
    with pytest.raises(ValidationError, match="must be valid JSON"):
        make_quote_request({"prompt": "test", "weight": float("nan")})
