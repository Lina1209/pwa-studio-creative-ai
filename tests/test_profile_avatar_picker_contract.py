from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ProfileAvatarPickerContractTests(unittest.TestCase):
    def test_picker_has_real_curated_2d_catalog_and_explicit_3d_unavailable_state(self):
        app = (ROOT / "app.js").read_text(encoding="utf-8")
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        catalog = (ROOT / "profile-avatar-catalog.js").read_text(encoding="utf-8")
        self.assertIn('const PROFILE_AVATAR_CATALOG = globalThis.PWAProfileAvatarCatalog.items;', app)
        self.assertIn('profile-avatar-catalog.js?v=20261127-1', html)
        self.assertIn('id:"portrait-violet"', app)
        self.assertIn('id:"forest-elf"', app)
        self.assertIn('id:"fox-scout"', app)
        self.assertIn('id:"robo-buddy"', app)
        self.assertIn('id:"katty-assistant"', app)
        self.assertIn('id:"comic-star"', app)
        self.assertIn('id:"cosmo-pilot"', app)
        self.assertIn('id:"sun-garden"', app)
        self.assertIn('id:"prism-orbit"', app)
        self.assertIn('id="profileAvatarTab3d"', html)
        self.assertIn('disabled aria-disabled="true"', html)
        self.assertIn('assets/avatars/2d/', catalog)
        self.assertIn('identityKey: "katty-katarina"', catalog)

    def test_avatar_persistence_is_fenced_to_current_authenticated_account(self):
        app = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn('const version=authContextVersion', app)
        self.assertIn('authSession?.user?.id!==userId', app)
        self.assertIn('saved.user_id!==userId', app)
        self.assertIn('avatar_catalog_id:profileAvatarDraftId', app)
        self.assertIn('applyProfileAvatarChrome(profileAvatarSavedId)', app)
        self.assertIn('"#accountAvatar","#topAvatar",".profile .avatar"', app)

    def test_guest_selection_is_local_and_separate_from_signed_in_profiles(self):
        app = (ROOT / "app.js").read_text(encoding="utf-8")
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('pwa_studio_guest_profile_avatar_v1', app)
        self.assertIn('localStorage.setItem("pwa_studio_guest_profile_avatar_v1"', app)
        account_start = html.index('id="view-account"')
        picker_start = html.index('id="profileAvatarPicker"') if 'id="profileAvatarPicker"' in html else html.index('id="profileAvatarTitle"')
        community_start = html.index('id="communityPanel"')
        self.assertLess(account_start, picker_start)
        self.assertLess(picker_start, community_start)

    def test_all_catalog_assets_exist_and_are_svg(self):
        ids = [
            "portrait-violet", "forest-elf", "fox-scout", "robo-buddy", "katty-assistant",
            "comic-star", "cosmo-pilot", "sun-garden", "prism-orbit",
        ]
        for avatar_id in ids:
            path = ROOT / "assets" / "avatars" / "2d" / f"{avatar_id}.svg"
            self.assertTrue(path.is_file(), f"Missing catalog asset: {avatar_id}")
            self.assertIn("<svg", path.read_text(encoding="utf-8")[:200])


if __name__ == "__main__":
    unittest.main()
