from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ProfileAvatarPickerContractTests(unittest.TestCase):
    def test_picker_uses_shared_catalog_and_keeps_3d_unavailable(self):
        app = (ROOT / "app.js").read_text(encoding="utf-8")
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        catalog = (ROOT / "profile-avatar-catalog.js").read_text(encoding="utf-8")
        self.assertIn("const PROFILE_AVATAR_CATALOG = globalThis.PWAProfileAvatarCatalog.items;", app)
        self.assertIn("profile-avatar-catalog.js?v=20261127-1", html)
        for avatar_id in (
            "portrait-violet", "forest-elf", "fox-scout", "robo-buddy",
            "katty-assistant", "comic-star", "cosmo-pilot", "sun-garden", "prism-orbit",
        ):
            self.assertIn('id: "' + avatar_id + '"', catalog)
        self.assertIn('identityKey: "katty-katarina"', catalog)
        self.assertIn('id="profileAvatarTab3d"', html)
        self.assertIn('disabled aria-disabled="true"', html)
        self.assertIn("assets/avatars/2d/", catalog)

    def test_avatar_persistence_is_fenced_to_current_authenticated_account(self):
        app = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("const version=authContextVersion", app)
        self.assertIn("authSession?.user?.id!==userId", app)
        self.assertIn("saved.user_id!==userId", app)
        self.assertIn("avatar_catalog_id:profileAvatarDraftId", app)
        self.assertIn("applyProfileAvatarChrome(profileAvatarSavedId)", app)
        self.assertIn('"#accountAvatar","#topAvatar",".profile .avatar"', app)

    def test_guest_selection_is_local_and_separate_from_signed_in_profiles(self):
        app = (ROOT / "app.js").read_text(encoding="utf-8")
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("pwa_studio_guest_profile_avatar_v1", app)
        self.assertIn('localStorage.setItem("pwa_studio_guest_profile_avatar_v1"', app)
        account_start = html.index('id="view-account"')
        picker_start = html.index('id="profileAvatarPicker"') if 'id="profileAvatarPicker"' in html else html.index('id="profileAvatarTitle"')
        community_start = html.index('id="communityPanel"')
        self.assertLess(account_start, picker_start)
        self.assertLess(picker_start, community_start)

    def test_all_catalog_assets_exist_and_are_svg(self):
        ids = (
            "portrait-violet", "forest-elf", "fox-scout", "robo-buddy", "katty-assistant",
            "comic-star", "cosmo-pilot", "sun-garden", "prism-orbit",
        )
        for avatar_id in ids:
            path = ROOT / "assets" / "avatars" / "2d" / (avatar_id + ".svg")
            self.assertTrue(path.is_file(), "Missing catalog asset: " + avatar_id)
            self.assertIn("<svg", path.read_text(encoding="utf-8")[:200])


    def test_katty_expression_preview_is_temporary_and_only_shown_for_katty(self):
        app = (ROOT / "app.js").read_text(encoding="utf-8")
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="kattyExpressionPicker"', html)
        self.assertIn('hidden aria-label="Выражения Катти"', html)
        self.assertIn("const KATTY_EXPRESSIONS=", app)
        for expression_id in ("neutral-warm", "joy", "delight", "curious", "focused", "surprised", "empathetic", "thinking"):
            self.assertIn('["' + expression_id + '"', app)
        self.assertIn('expressionPicker.hidden=profileAvatarDraftId!=="katty-assistant"', app)
        self.assertIn('assets/characters/katty/expressions/"+kattyExpressionDraft+".svg', app)
        self.assertIn("kattyExpressionDraft=id;renderProfileAvatarPicker();", app)
        self.assertNotIn("avatar_expression", app)


    def test_ai_companion_uses_katty_static_expressions_for_conversation_states(self):
        app = (ROOT / "app.js").read_text(encoding="utf-8")
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="kattyCompanionExpression"', html)
        self.assertIn("const KATTY_ASSISTANT_EXPRESSIONS", app)
        self.assertIn("setKattyAssistantExpression(kattyContextState(value))", app)
        self.assertIn("setKattyAssistantExpression(kattyResponseState(value, result.reply))", app)
        self.assertIn('setKattyAssistantExpression("neutral")', app)
        self.assertIn('assets/characters/katty/expressions/" + id + ".svg', app)
        self.assertNotIn("apiRequest(", app[app.index("const setKattyAssistantExpression"):app.index("const copyAssistantText")])


    def test_katty_contextual_states_cover_learning_creativity_support_and_reset(self):
        app = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("const kattyContextState", app)
        self.assertIn('return "curious"', app)
        self.assertIn('return "focused"', app)
        self.assertIn('return "empathetic"', app)
        self.assertIn("const kattyResponseState", app)
        self.assertIn('setKattyAssistantExpression(kattyContextState(value))', app)
        self.assertIn('setKattyAssistantExpression(kattyResponseState(value, result.reply))', app)
        self.assertIn("const clearAssistantMessages = () => {", app)
        self.assertIn("const loadAssistantMessages = async conversationId => {", app)

    def test_katty_mode_is_visible_to_user(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "styles.css").read_text(encoding="utf-8")
        app = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="kattyAssistantModeLabel"', html)
        self.assertIn(".katty-mode-badge", css)
        self.assertIn('badge.textContent = "Режим: " + selected.label', app)

    def test_katty_assistant_modes_are_separate_from_expression_states(self):
        app = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("const KATTY_ASSISTANT_MODES", app)
        for mode in ("companion", "teacher", "creator", "guide"):
            self.assertIn(mode + ": { label:", app)
        self.assertIn("const kattyModeForMessage", app)
        self.assertIn("const setKattyAssistantMode", app)
        self.assertIn("image.dataset.assistantMode = mode", app)
        self.assertIn("setKattyAssistantMode(kattyModeForMessage(value))", app)
        self.assertIn("setKattyAssistantExpression(kattyContextState(value))", app)


    def test_katty_mode_previews_prompt_suggestions(self):
        app = (ROOT / "app.js").read_text(encoding="utf-8")
        start = app.indexOf('$$("[data-assist]")') if hasattr(app, "indexOf") else app.index('$$("[data-assist]")')
        end = app.index("\n  // AI Companion cloud history", start)
        handler = app[start:end]
        self.assertIn("setKattyAssistantMode(kattyModeForMessage(prompt))", handler)
        self.assertIn("setKattyAssistantExpression(kattyContextState(prompt))", handler)
        self.assertIn('$("#assistantInput").value = prompt', handler)

    def test_katty_mode_resets_when_conversation_changes(self):
        app = (ROOT / "app.js").read_text(encoding="utf-8")
        for function_name in ("clearAssistantMessages", "loadAssistantMessages", "startAssistantConversation"):
            start = app.index("const " + function_name)
            end = app.index("\n  };", start) + 5
            self.assertIn('setKattyAssistantMode("companion")', app[start:end])

if __name__ == "__main__":

    unittest.main()
