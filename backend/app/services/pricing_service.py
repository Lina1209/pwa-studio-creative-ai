"""Server-owned, versioned pricing calculations.

The production catalog is intentionally empty until the owner approves real
provider rates, a credit conversion policy, and operation ceilings. Never read
prices or multipliers from browser payloads.
"""
from dataclasses import dataclass
import re
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from typing import Mapping


class PricingError(ValueError):
    """The operation has no safe, approved price or usage cannot be priced."""


@dataclass(frozen=True)
class AIPricingRule:
    operation_code: str
    pricing_version: int
    provider: str
    model: str
    input_usd_per_million_tokens: Decimal
    output_usd_per_million_tokens: Decimal
    credits_per_usd: Decimal
    max_input_tokens: int
    max_output_tokens: int
    min_credits: int = 1
    max_credits: int = 100_000_000
    active: bool = False


@dataclass(frozen=True)
class PricingQuote:
    operation_code: str
    pricing_version: int
    provider: str
    model: str
    reserved_credits: int
    max_input_tokens: int
    max_output_tokens: int


@dataclass(frozen=True)
class PricingSettlement:
    operation_code: str
    pricing_version: int
    captured_credits: int
    input_tokens: int
    output_tokens: int


# No rates are enabled by default. Add only reviewed, versioned rules here.
# A future rule must use the provider's actual model identifier and an
# explicitly approved credit conversion factor.
AI_PRICING_CATALOG: dict[tuple[str, str, str], AIPricingRule] = {}
_OPERATION_RE = re.compile(r"^[a-z0-9_.-]{1,80}$")


def _ceil_credits(usd: Decimal, credits_per_usd: Decimal) -> int:
    try:
        value = usd * credits_per_usd
        if not value.is_finite() or value < 0:
            raise PricingError("Calculated price is invalid.")
        return int(value.to_integral_value(rounding=ROUND_CEILING))
    except (InvalidOperation, TypeError) as exc:
        raise PricingError("Calculated price is invalid.") from exc


def _validate_rule(rule: AIPricingRule) -> None:
    if not rule.active:
        raise PricingError("Pricing rule is not active.")
    if (not isinstance(rule.operation_code, str)
            or not _OPERATION_RE.fullmatch(rule.operation_code)
            or not isinstance(rule.provider, str) or not rule.provider.strip()
            or not isinstance(rule.model, str) or not rule.model.strip()):
        raise PricingError("Pricing rule identity is invalid.")
    if (isinstance(rule.pricing_version, bool)
            or not isinstance(rule.pricing_version, int) or rule.pricing_version < 1):
        raise PricingError("Pricing version must be a positive integer.")
    for rate in (
        rule.input_usd_per_million_tokens,
        rule.output_usd_per_million_tokens,
        rule.credits_per_usd,
    ):
        if not isinstance(rate, Decimal) or not rate.is_finite() or rate < 0:
            raise PricingError("Pricing rates must be finite, non-negative decimals.")
    if rule.credits_per_usd <= 0:
        raise PricingError("Credit conversion rate must be positive.")
    for limit in (rule.max_input_tokens, rule.max_output_tokens):
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise PricingError("Token ceilings must be positive integers.")
    if (isinstance(rule.min_credits, bool) or not isinstance(rule.min_credits, int)
            or isinstance(rule.max_credits, bool) or not isinstance(rule.max_credits, int)
            or rule.min_credits < 1 or rule.max_credits < rule.min_credits
            or rule.max_credits > 100_000_000):
        raise PricingError("Credit bounds are invalid.")


def _resolve_rule(
    operation_code: str,
    provider: str,
    model: str,
    catalog: Mapping[tuple[str, str, str], AIPricingRule],
) -> AIPricingRule:
    rule = catalog.get((operation_code, provider.strip().lower(), model.strip()))
    if rule is None:
        raise PricingError("No approved pricing rule exists for this operation and model.")
    _validate_rule(rule)
    return rule


def _usd_for_tokens(rule: AIPricingRule, input_tokens: int, output_tokens: int) -> Decimal:
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0
           for v in (input_tokens, output_tokens)):
        raise PricingError("Token usage must be non-negative integers.")
    if input_tokens > rule.max_input_tokens or output_tokens > rule.max_output_tokens:
        raise PricingError("Actual token usage exceeds the approved operation ceiling.")
    million = Decimal(1_000_000)
    return (
        Decimal(input_tokens) * rule.input_usd_per_million_tokens / million
        + Decimal(output_tokens) * rule.output_usd_per_million_tokens / million
    )


def quote_ai_operation(
    *,
    operation_code: str,
    provider: str,
    model: str,
    catalog: Mapping[tuple[str, str, str], AIPricingRule] = AI_PRICING_CATALOG,
) -> PricingQuote:
    """Reserve against the full server-defined token ceiling before provider use."""
    rule = _resolve_rule(operation_code, provider, model, catalog)
    maximum_cost = _usd_for_tokens(rule, rule.max_input_tokens, rule.max_output_tokens)
    credits = max(rule.min_credits, _ceil_credits(maximum_cost, rule.credits_per_usd))
    if credits > rule.max_credits:
        raise PricingError("Maximum reservation exceeds the approved credit ceiling.")
    return PricingQuote(
        operation_code=rule.operation_code,
        pricing_version=rule.pricing_version,
        provider=rule.provider,
        model=rule.model,
        reserved_credits=credits,
        max_input_tokens=rule.max_input_tokens,
        max_output_tokens=rule.max_output_tokens,
    )


def settle_ai_operation(
    quote: PricingQuote,
    *,
    provider: str,
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
    catalog: Mapping[tuple[str, str, str], AIPricingRule] = AI_PRICING_CATALOG,
) -> PricingSettlement:
    """Price trusted provider usage; missing usage or overrun requires reconciliation."""
    if input_tokens is None or output_tokens is None:
        raise PricingError("Provider usage is incomplete; reservation requires reconciliation.")
    if (not isinstance(provider, str) or not isinstance(model, str)
            or provider.strip().lower() != quote.provider.strip().lower()
            or model.strip() != quote.model):
        raise PricingError("Provider/model differs from the reserved pricing quote.")
    rule = _resolve_rule(quote.operation_code, quote.provider, quote.model, catalog)
    if rule.pricing_version != quote.pricing_version:
        raise PricingError("Pricing version changed after reservation.")
    cost = _usd_for_tokens(rule, input_tokens, output_tokens)
    captured = max(rule.min_credits, _ceil_credits(cost, rule.credits_per_usd))
    if captured > quote.reserved_credits:
        raise PricingError("Actual charge exceeds reserved credits; reconciliation is required.")
    return PricingSettlement(
        operation_code=quote.operation_code,
        pricing_version=quote.pricing_version,
        captured_credits=captured,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
