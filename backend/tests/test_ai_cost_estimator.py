import unittest
from decimal import Decimal

from app.services.ai_cost_estimator import (
    AIPriceRateCard,
    estimate_ai_cost_upper_bound,
)


class AICostEstimatorTests(unittest.TestCase):
    def setUp(self):
        self.rate_card = AIPriceRateCard(
            provider="test-provider",
            model="test-model",
            version="2026-11-28-reviewed-v1",
            input_usd_per_million_tokens=Decimal("0.50"),
            output_usd_per_million_tokens=Decimal("1.00"),
            max_input_tokens=64000,
            max_output_tokens=2048,
        )

    def test_calculates_decimal_cost_upper_bound(self):
        cost = estimate_ai_cost_upper_bound(
            self.rate_card,
            input_tokens_upper_bound=1000,
            output_tokens_upper_bound=500,
        )
        self.assertEqual(cost, Decimal("0.0010000000"))

    def test_rounds_up_to_ledger_precision(self):
        card = AIPriceRateCard(
            provider="test-provider",
            model="test-model",
            version="v2",
            input_usd_per_million_tokens=Decimal("0.0000001"),
            output_usd_per_million_tokens=Decimal("0.0000001"),
            max_input_tokens=10,
            max_output_tokens=10,
        )
        cost = estimate_ai_cost_upper_bound(
            card,
            input_tokens_upper_bound=1,
            output_tokens_upper_bound=0,
        )
        self.assertEqual(cost, Decimal("0.0000000001"))

    def test_rejects_untrusted_or_out_of_range_token_counts(self):
        for input_count, output_count in [(-1, 0), (64001, 0), (0, 2049), (True, 0), (1.5, 0)]:
            with self.subTest(input_count=input_count, output_count=output_count):
                with self.assertRaises(ValueError):
                    estimate_ai_cost_upper_bound(
                        self.rate_card,
                        input_tokens_upper_bound=input_count,
                        output_tokens_upper_bound=output_count,
                    )

    def test_rejects_rate_card_without_price_or_token_ceiling(self):
        with self.assertRaises(ValueError):
            AIPriceRateCard(
                provider="test",
                model="model",
                version="v1",
                input_usd_per_million_tokens=Decimal("0"),
                output_usd_per_million_tokens=Decimal("0"),
                max_input_tokens=10,
                max_output_tokens=10,
            )
        with self.assertRaises(ValueError):
            AIPriceRateCard(
                provider="test",
                model="model",
                version="v1",
                input_usd_per_million_tokens=Decimal("1"),
                output_usd_per_million_tokens=Decimal("1"),
                max_input_tokens=0,
                max_output_tokens=10,
            )
        with self.assertRaises(ValueError):
            AIPriceRateCard(
                provider="test",
                model="model",
                version="v1",
                input_usd_per_million_tokens=Decimal("1"),
                output_usd_per_million_tokens=Decimal("1"),
                max_input_tokens=True,
                max_output_tokens=10,
            )

    def test_rejects_non_finite_or_negative_rates(self):
        for rate in [Decimal("-0.01"), Decimal("NaN"), Decimal("Infinity")]:
            with self.subTest(rate=rate):
                with self.assertRaises(ValueError):
                    AIPriceRateCard(
                        provider="test",
                        model="model",
                        version="v1",
                        input_usd_per_million_tokens=rate,
                        output_usd_per_million_tokens=Decimal("1"),
                        max_input_tokens=10,
                        max_output_tokens=10,
                    )


if __name__ == "__main__":
    unittest.main()
