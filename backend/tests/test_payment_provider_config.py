import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.services.payment_provider_contracts import (
    PaymentProviderNotConfigured,
    build_payment_provider_registry,
)


def test_payment_provider_defaults_are_disabled_test_mode():
    settings = Settings()
    assert settings.payment_provider_runtime_enabled is False
    assert settings.payment_provider_mode == "test"
    assert build_payment_provider_registry(settings).provider_codes == ()


def test_live_payment_mode_requires_explicit_runtime_enablement():
    with pytest.raises(ValidationError, match="PAYMENT_PROVIDER_RUNTIME_ENABLED"):
        Settings(payment_provider_mode="live")


def test_live_mode_still_fails_closed_without_a_concrete_server_adapter():
    settings = Settings(
        payment_provider_runtime_enabled=True,
        payment_provider_mode="live",
    )
    with pytest.raises(PaymentProviderNotConfigured, match="without a concrete server adapter"):
        build_payment_provider_registry(settings)
