import unittest
from pydantic import ValidationError

from app.schemas import ChatRequest


class ChatRequestLimitsTests(unittest.TestCase):
    def test_accepts_context_within_total_character_budget(self):
        payload = ChatRequest(
            message="current question",
            history=[
                {"role": "user", "content": "a" * 12000},
                {"role": "assistant", "content": "b" * 11900},
            ],
        )
        self.assertLessEqual(
            len(payload.message) + sum(len(turn.content) for turn in payload.history),
            24000,
        )

    def test_rejects_context_over_total_character_budget(self):
        with self.assertRaisesRegex(ValidationError, "complete chat context"):
            ChatRequest(
                message="c" * 12000,
                history=[
                    {"role": "user", "content": "a" * 12000},
                    {"role": "assistant", "content": "b"},
                ],
            )

    def test_keeps_existing_per_turn_limit(self):
        with self.assertRaises(ValidationError):
            ChatRequest(message="x", history=[{"role": "user", "content": "a" * 12001}])


if __name__ == "__main__":
    unittest.main()
