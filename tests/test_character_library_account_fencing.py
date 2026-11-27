"""Source-contract regression tests for account-scoped character library writes.

These checks complement browser tests: they ensure async UI operations retain the
owner/storage context they started with and cannot commit into a later session.
"""
from pathlib import Path
import unittest


APP = (Path(__file__).resolve().parents[1] / "app.js").read_text(encoding="utf-8")


class CharacterLibraryAccountFencingTests(unittest.TestCase):
    def test_render_stops_when_account_changes_during_image_read(self):
        self.assertIn("const contextVersion=authContextVersion;", APP)
        self.assertIn(
            'if(contextVersion!==authContextVersion||(authSession?.user?.id||"guest")!==ownerId)return;',
            APP,
        )

    def test_save_captures_owner_storage_key_and_session_version(self):
        self.assertIn(
            'const ownerId=authSession?.user?.id||"guest",contextVersion=authContextVersion,storageKey=characterLibraryKey();',
            APP,
        )
        self.assertIn('localStorage.setItem(storageKey,JSON.stringify(next));', APP)

    def test_save_checks_session_after_async_image_writes(self):
        self.assertIn(
            'throw new Error("Аккаунт изменился во время сохранения. Локальная карточка не была записана в другой аккаунт.");',
            APP,
        )

    def test_delete_uses_captured_owner_and_storage_key(self):
        self.assertIn("const deleteOwnerId=ownerId;", APP)
        self.assertIn("const deleteStorageKey=characterLibraryKey();", APP)
        self.assertIn("localStorage.setItem(deleteStorageKey,JSON.stringify(next));", APP)
        self.assertIn("deleteCharacterImage(ref.id,deleteOwnerId)", APP)


if __name__ == "__main__":
    unittest.main(verbosity=2)
