import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.core.config import Settings
from app.services.ai_service import ask_ai


class AIServiceOutputBudgetTests(unittest.TestCase):
    @patch("app.services.ai_service.completion")
    def test_provider_call_has_bounded_output_token_budget(self, completion):
        completion.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="A useful reply"))],
            usage=None,
            model="deepseek-flash",
            _hidden_params={},
        )
        settings = Settings(ai_provider="deepseek", ai_model="deepseek-flash", deepseek_api_key="test-key")

        result = ask_ai(settings, [{"role": "user", "content": "Hello"}])

        self.assertEqual(result.text, "A useful reply")
        self.assertEqual(completion.call_args.kwargs["max_tokens"], 2048)
        self.assertEqual(completion.call_args.kwargs["max_retries"], 1)
        self.assertEqual(completion.call_args.kwargs["timeout"], 90)


if __name__ == "__main__":
    unittest.main()
