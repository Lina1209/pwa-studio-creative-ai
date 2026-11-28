"""Pure server-side AI cost upper-bound estimator.

No provider prices are bundled or selected here. Callers must inject a reviewed,
versioned rate card and trusted tokenizer-derived upper bounds. This module is
not wired to API routes.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING


_USD_QUANTUM = Decimal("0.0000000001")
_MILLION = Decimal("1000000")


@dataclass(frozen=True)
class AIPriceRateCard:
    provider: str
    model: str
    version: str
    input_usd_per_million_tokens: Decimal
    output_usd_per_million_tokens: Decimal
    max_input_tokens: int
    max_output_tokens: int

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.model.strip() or not self.version.strip():
            raise ValueError("AI rate card identity fields are required.")
        for rate in (
            self.input_usd_per_million_tokens,
            self.output_usd_per_million_tokens,
        ):
            if not isinstance(rate, Decimal) or not rate.is_finite() or rate < 0:
                raise ValueError("AI token rates must be finite non-negative Decimals.")
        if (
            self.input_usd_per_million_tokens == 0
            and self.output_usd_per_million_tokens == 0
        ):
            raise ValueError("At least one AI token rate must be positive.")
        if self.max_input_tokens < 1 or self.max_output_tokens < 1:
            raise ValueError("AI rate card token ceilings must be positive.")


def estimate_ai_cost_upper_bound(
    rate_card: AIPriceRateCard,
    *,
    input_tokens_upper_bound: int,
    output_tokens_upper_bound: int,
) -> Decimal:
    """Return a USD upper bound, rounded upward to the ledger precision.

    The function never tokenizes text or invents prices. Token counts must come
    from a trusted server-side tokenizer or other reviewed upper-bound source.
    """
    if not isinstance(input_tokens_upper_bound, int) or isinstance(input_tokens_upper_bound, bool):
        raise ValueError("Input token upper bound must be an integer.")
    if not isinstance(output_tokens_upper_bound, int) or isinstance(output_tokens_upper_bound, bool):
        raise ValueError("Output token upper bound must be an integer.")
    if not 0 <= input_tokens_upper_bound <= rate_card.max_input_tokens:
        raise ValueError("Input token upper bound exceeds the reviewed rate-card ceiling.")
    if not 0 <= output_tokens_upper_bound <= rate_card.max_output_tokens:
        raise ValueError("Output token upper bound exceeds the reviewed rate-card ceiling.")

    raw_cost = (
        Decimal(input_tokens_upper_bound) * rate_card.input_usd_per_million_tokens
        + Decimal(output_tokens_upper_bound) * rate_card.output_usd_per_million_tokens
    ) / _MILLION
    try:
        return raw_cost.quantize(_USD_QUANTUM, rounding=ROUND_CEILING)
    except InvalidOperation as exc:
        raise ValueError("AI cost estimate exceeds supported ledger precision.") from exc
