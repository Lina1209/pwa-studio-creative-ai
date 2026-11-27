"""Source-contract regression tests for account-scoped character library writes.

These checks complement browser tests: they ensure async UI operations retain the
owner/storage context they started with and cannot commit into a later session.
"""
from pathlib import Path
import unittest


APP = (Path(__file__).resolve().parents[1] / "app.js").read_text(encoding="utf-8")


class CharacterLibraryAccountFencingTests(unittest.TestCase):
    def test_community_search_results_are_latest_request_only(self):
        search_start = APP.index("const searchCommunity = async")
        search_end = APP.index("const openCommunityProfile = async", search_start)
        search = APP[search_start:search_end]
        self.assertIn("const requestVersion=++communitySearchRequestVersion;", search)
        self.assertIn("requestVersion!==communitySearchRequestVersion", search)
        self.assertIn("authSession?.user?.id===userId", search)

    def test_community_profile_view_is_latest_request_and_account_only(self):
        profile_start = APP.index("const openCommunityProfile = async")
        profile_end = APP.index('$("#communitySearchButton")', profile_start)
        profile = APP[profile_start:profile_end]
        self.assertIn("const requestVersion=++communityProfileRequestVersion;", profile)
        self.assertIn("requestVersion!==communityProfileRequestVersion", profile)
        self.assertIn("version!==authContextVersion", profile)
        self.assertIn("authSession?.user?.id!==userId", profile)

    def test_logout_response_is_fenced_to_originating_account(self):
        logout_start = APP.index('authLogoutButton.addEventListener("click"')
        logout_end = APP.index('\n  });', logout_start) + 6
        logout = APP[logout_start:logout_end]
        self.assertIn("const requestUserId = authSession.user.id;", logout)
        self.assertIn("const requestVersion = authContextVersion;", logout)
        self.assertIn("if (!contextIsCurrent()) return;", logout)
        self.assertIn("if (contextIsCurrent()) authLogoutButton.disabled = false;", logout)
        self.assertNotIn("refreshAuthUI(null);", logout.split("if (!contextIsCurrent()) return;")[0])

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

    def test_stale_save_cannot_unlock_new_account_editor(self):
        self.assertIn(
            'finally{if(contextVersion===authContextVersion&&(authSession?.user?.id||"guest")===ownerId)button.disabled=false;}',
            APP,
        )

    def test_delete_uses_captured_owner_and_storage_key(self):
        self.assertIn("const deleteOwnerId=ownerId;", APP)
        self.assertIn("const deleteStorageKey=characterLibraryKey();", APP)
        self.assertIn("localStorage.setItem(deleteStorageKey,JSON.stringify(next));", APP)
        self.assertIn("deleteCharacterImage(ref.id,deleteOwnerId)", APP)


    def test_guest_and_authenticated_metadata_use_separate_keys(self):
        self.assertIn(
            '"pwa-studio-character-library-v1:" + (authSession?.user?.id || "guest")',
            APP,
        )

    def test_indexeddb_image_reads_and_deletes_verify_owner(self):
        self.assertIn("request.result?.ownerId===ownerId?request.result.blob:null", APP)
        self.assertIn("if(request.result?.ownerId===ownerId)store.delete(id);", APP)

    def test_indexeddb_image_save_refuses_cross_owner_id_collision(self):
        self.assertIn("const existing=store.get(id);", APP)
        self.assertIn("existing.result.ownerId!==ownerId", APP)
        self.assertIn("Исходная запись сохранена.", APP)
        self.assertIn("tx.abort();", APP)

    def test_auth_identity_change_increments_context_and_notifies_library(self):
        self.assertIn("authContextVersion += 1;", APP)
        self.assertIn('window.dispatchEvent(new Event("pwa-studio-auth-changed"));', APP)
        self.assertIn('window.addEventListener("pwa-studio-auth-changed",()=>{resetCharacterEditor();renderCharacterLibrary();});', APP)


    def test_movie_cloud_sync_is_fenced_after_each_account_sensitive_await(self):
        start = APP.index("const loadMovieProjectsFromCloud = async () => {")
        end = APP.index("\n  };", start) + 5
        loader = APP[start:end]
        self.assertIn("const version = authContextVersion;", loader)
        self.assertIn("const contextIsCurrent = () => version === authContextVersion && authSession?.user?.id === userId;", loader)
        self.assertIn("if (!contextIsCurrent()) return;", loader)
        self.assertIn("if (contextIsCurrent() && movieWrite(projects))", loader)
        self.assertIn("if (contextIsCurrent() && feedback)", loader)
        self.assertLess(loader.index("await supabaseClient.from(\"projects\").delete()"), loader.index("if (!contextIsCurrent()) return;", loader.index("await supabaseClient.from(\"projects\").delete()")))


    def test_audio_story_generation_and_movie_handoff_are_account_fenced(self):
        bridge_start = APP.index("window.PWAStudioAudioBridge = {")
        bridge_end = APP.index("\n  };", bridge_start) + 5
        bridge = APP[bridge_start:bridge_end]
        self.assertIn("const requestUserId = authSession?.user?.id || null;", bridge)
        self.assertIn("const requestVersion = authContextVersion;", bridge)
        self.assertIn("requestVersion !== authContextVersion", bridge)
        self.assertIn("latestAudioGenerationContext = { userId:requestUserId, version:requestVersion, reply:result.reply };", bridge)
        self.assertIn("generation.version !== authContextVersion", bridge)
        self.assertIn("generation.userId !== (authSession?.user?.id || null)", bridge)


    def test_audio_lab_discards_stale_results_and_cleanup_after_account_change(self):
        audio = (Path(__file__).resolve().parents[1] / "audio-lab.js").read_text(encoding="utf-8")
        self.assertIn('window.addEventListener("pwa-studio-auth-changed"', audio)
        self.assertIn("audioStoryRequestVersion += 1;", audio)
        self.assertIn("if (requestVersion !== audioStoryRequestVersion) return;", audio)
        self.assertIn("if(requestVersion===audioStoryRequestVersion)status.textContent", audio)
        self.assertIn("finally{if(requestVersion===audioStoryRequestVersion)generate.disabled=false;}", audio)

    def test_audio_dictation_callbacks_are_invalidated_on_account_change(self):
        audio = (Path(__file__).resolve().parents[1] / "audio-lab.js").read_text(encoding="utf-8")
        self.assertIn("const staleRecognition = recognition;", audio)
        self.assertIn("staleRecognition.abort();", audio)
        self.assertIn("const recognitionVersion = audioStoryRequestVersion;", audio)
        self.assertIn("if (!recognitionIsCurrent()) return;", audio)
        self.assertIn('Диктовка остановлена из-за смены аккаунта.', audio)

    def test_audio_story_edits_are_preserved_for_same_account_handoff(self):
        audio = (Path(__file__).resolve().parents[1] / "audio-lab.js").read_text(encoding="utf-8")
        self.assertIn('resultText.addEventListener("input",()=>{latestResult=resultText.value;});', audio)
        bridge_start = APP.index("window.PWAStudioAudioBridge = {")
        bridge_end = APP.index("\n  };", bridge_start) + 5
        bridge = APP[bridge_start:bridge_end]
        self.assertIn('!String(story || "").trim()', bridge)
        self.assertNotIn('generation.reply !== String(story || "")', bridge)
        self.assertIn("generation.version !== authContextVersion", bridge)
        self.assertIn("generation.userId !== (authSession?.user?.id || null)", bridge)


if __name__ == "__main__":
    unittest.main(verbosity=2)
