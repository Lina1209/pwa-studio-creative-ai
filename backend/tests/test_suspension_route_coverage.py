"""Static route-contract tests for account suspension enforcement.

These tests intentionally inspect route wiring so adding a new endpoint cannot
silently bypass the platform/community/assistant suspension policy.
"""
import ast
from pathlib import Path
import unittest


APP_ROOT = Path(__file__).resolve().parents[1] / "app"


def _functions_with_routes(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        route_decorators = [
            decorator for decorator in node.decorator_list
            if isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr in {"get", "post", "put", "patch", "delete"}
        ]
        if route_decorators:
            found[node.name] = node
    return found


def _default_expressions(function):
    expressions = list(function.args.defaults)
    expressions.extend(value for value in function.args.kw_defaults if value is not None)
    return [ast.unparse(value) for value in expressions]


def _body_calls(function):
    return [
        (ast.unparse(node.func), [ast.unparse(arg) for arg in node.args])
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
    ]


class SuspensionRouteCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main_routes = _functions_with_routes(APP_ROOT / "main.py")
        cls.character_routes = _functions_with_routes(APP_ROOT / "character_api.py")

    def test_private_media_and_reference_routes_require_platform_active_user(self):
        names = {
            "list_character_reference_catalog",
            "list_character_reference_status",
            "upload_character_reference",
            "private_media_content",
            "private_media_access",
        }
        self.assertTrue(names.issubset(self.main_routes))
        for name in sorted(names):
            with self.subTest(route=name):
                defaults = " ".join(_default_expressions(self.main_routes[name]))
                self.assertIn("get_platform_active_user", defaults)

    def test_character_crud_routes_require_platform_active_user(self):
        expected = {"list_characters", "create_character", "read_character", "patch_character"}
        self.assertTrue(expected.issubset(self.character_routes))
        for name in sorted(expected):
            with self.subTest(route=name):
                defaults = " ".join(_default_expressions(self.character_routes[name]))
                self.assertIn("get_platform_active_user", defaults)

    def test_every_community_route_checks_community_suspension(self):
        community = {
            name: node for name, node in self.main_routes.items()
            if name in {
                "own_community_profile", "update_community_profile",
                "community_user_search", "community_public_profile",
                "conversations", "conversation_messages", "send_message",
                "read_conversation", "edit_direct_message", "remove_direct_message",
                "blocked_users", "create_user_block", "remove_user_block",
            }
        }
        self.assertGreaterEqual(len(community), 12)
        for name, node in community.items():
            with self.subTest(route=name):
                calls = _body_calls(node)
                self.assertTrue(any(
                    func.endswith("ensure_user_not_suspended")
                    and len(args) >= 3 and args[2].strip("'\\"") == "community"
                    for func, args in calls
                ))

    def test_assistant_routes_check_assistant_suspension(self):
        for name in ("chat", "create_prompt"):
            with self.subTest(route=name):
                self.assertIn(name, self.main_routes)
                calls = _body_calls(self.main_routes[name])
                self.assertTrue(any(
                    func.endswith("ensure_user_not_suspended")
                    and len(args) >= 3 and args[2].strip("'\\"") == "assistant"
                    for func, args in calls
                ))

    def test_admin_moderation_routes_remain_require_admin(self):
        names = {
            "admin_me", "admin_reports", "review_report",
            "suspend_user", "admin_suspensions", "unsuspend_user",
        }
        self.assertTrue(names.issubset(self.main_routes))
        for name in sorted(names):
            with self.subTest(route=name):
                defaults = " ".join(_default_expressions(self.main_routes[name]))
                self.assertIn("require_admin", defaults)


if __name__ == "__main__":
    unittest.main()
