import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from fastapi import HTTPException

from app.services import ai_rate_limit


class AIRateLimitTests(unittest.TestCase):
    def setUp(self):
        ai_rate_limit._reset_rate_limit_state_for_tests()

    def tearDown(self):
        ai_rate_limit._reset_rate_limit_state_for_tests()

    @patch("app.services.ai_rate_limit.time.monotonic", return_value=100.0)
    def test_allows_ten_requests_per_user_in_window(self, _clock):
        for _ in range(10):
            ai_rate_limit.enforce_ai_rate_limit("user-a")

    @patch("app.services.ai_rate_limit.time.monotonic", return_value=100.0)
    def test_rejects_eleventh_request_with_retry_after(self, _clock):
        for _ in range(10):
            ai_rate_limit.enforce_ai_rate_limit("user-a")
        with self.assertRaises(HTTPException) as raised:
            ai_rate_limit.enforce_ai_rate_limit("user-a")
        self.assertEqual(raised.exception.status_code, 429)
        self.assertEqual(raised.exception.headers["Retry-After"], "60")

    def test_limits_are_isolated_by_user(self):
        with patch("app.services.ai_rate_limit.time.monotonic", return_value=100.0):
            for _ in range(10):
                ai_rate_limit.enforce_ai_rate_limit("user-a")
            ai_rate_limit.enforce_ai_rate_limit("user-b")

    def test_window_expires_and_allows_new_request(self):
        with patch("app.services.ai_rate_limit.time.monotonic", side_effect=[100.0] * 10 + [161.0]):
            for _ in range(10):
                ai_rate_limit.enforce_ai_rate_limit("user-a")
            ai_rate_limit.enforce_ai_rate_limit("user-a")

    def test_concurrent_requests_cannot_exceed_user_limit(self):
        def attempt(_):
            try:
                ai_rate_limit.enforce_ai_rate_limit("user-a")
                return "allowed"
            except HTTPException as exc:
                return exc.status_code

        with patch("app.services.ai_rate_limit.time.monotonic", return_value=100.0):
            with ThreadPoolExecutor(max_workers=20) as pool:
                outcomes = list(pool.map(attempt, range(40)))

        self.assertEqual(outcomes.count("allowed"), 10)
        self.assertEqual(outcomes.count(429), 30)


if __name__ == "__main__":
    unittest.main()
