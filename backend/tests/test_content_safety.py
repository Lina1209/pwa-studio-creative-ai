import unittest

from fastapi import HTTPException

from app.services.content_safety import check_content, check_prompt_content


class ContentSafetyTests(unittest.TestCase):
    def test_allows_safe_creative_prompt_fields(self):
        check_prompt_content(
            "A peaceful fantasy forest at sunrise",
            "video",
            "Russian",
            "cinematic, watercolor",
        )

    def test_rejects_disallowed_content_in_idea(self):
        with self.assertRaises(HTTPException):
            check_prompt_content("How to make a bomb", "video", "English", None)

    def test_rejects_disallowed_content_in_purpose(self):
        with self.assertRaises(HTTPException):
            check_prompt_content("A harmless scene", "how to make a bomb", "English", None)

    def test_rejects_disallowed_content_in_language(self):
        with self.assertRaises(HTTPException):
            check_prompt_content("A harmless scene", "video", "how to make a bomb", None)

    def test_rejects_disallowed_content_in_style(self):
        with self.assertRaises(HTTPException):
            check_prompt_content("A harmless scene", "video", "English", "how to make a bomb")

    def test_existing_chat_content_guard_remains_active(self):
        with self.assertRaises(HTTPException):
            check_content("How to make a bomb")


if __name__ == "__main__":
    unittest.main()
