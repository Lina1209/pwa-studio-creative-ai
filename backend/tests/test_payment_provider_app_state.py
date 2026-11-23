from app.main import app
from app.services.payment_provider_contracts import PaymentProviderNotConfigured


def test_app_state_uses_single_disabled_payment_provider_registry():
    registry = app.state.payment_provider_registry
    assert registry.provider_codes == ()
    try:
        registry.get("examplepay")
    except PaymentProviderNotConfigured:
        pass
    else:
        raise AssertionError("Payment provider registry must remain disabled.")
