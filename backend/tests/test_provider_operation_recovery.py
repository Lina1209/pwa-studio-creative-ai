import pytest

from app.services.image_generation import ImageGenerationLookup
from app.services.provider_operation_recovery import decide_provider_recovery


@pytest.mark.parametrize(
    "lookup,idem,expected",
    [
        (ImageGenerationLookup("succeeded", result=object()), True, "use_existing_result"),
        (ImageGenerationLookup("pending"), True, "wait"),
        (ImageGenerationLookup("failed", error_code="rejected"), True, "fail"),
        (ImageGenerationLookup("not_found"), True, "resubmit_same_key"),
        (ImageGenerationLookup("not_found"), False, "quarantine"),
        (ImageGenerationLookup("unknown"), True, "quarantine"),
    ],
)
def test_provider_recovery_decisions_are_fail_closed(lookup, idem, expected):
    decision = decide_provider_recovery(
        lookup, supports_idempotency=idem, supports_lookup=True
    )
    assert decision.action == expected


def test_provider_without_lookup_is_quarantined_even_if_idempotent():
    decision = decide_provider_recovery(
        ImageGenerationLookup("unknown"),
        supports_idempotency=True,
        supports_lookup=False,
    )
    assert decision.action == "quarantine"
    assert decision.error_code == "provider_lookup_not_supported"


def test_success_requires_existing_result():
    with pytest.raises(ValueError):
        ImageGenerationLookup("succeeded")
