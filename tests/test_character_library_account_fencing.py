"""Source-contract regression tests for account-scoped character library writes.

These checks complement browser tests: they ensure async UI operations retain the
owner/storage context they started with and cannot commit into a later session.
"""
from pathlib import Path
import unittest


APP = (Path(__file__).resolve().parents[1] / "app.js").read_text(encoding="utf-8")


class CharacterLibraryAccountFencingTests(unittest.TestCase):
    def test_notification_action_cleanup_is_account_fenced(self):
        one_start = APP.index("const markOneNotificationRead = async")
        one_end = APP.index('$("#notificationRefresh")', one_start)
        one = APP[one_start:one_end]
        self.assertIn("const contextIsCurrent = () => version === authContextVersion && authSession?.user?.id === userId;", one)
        self.assertIn("if (contextIsCurrent()) {", one)
        self.assertIn("button.disabled = false;", one)
        all_start = APP.index('$("#notificationReadAll")?.addEventListener')
        all_end = APP.index("const messagesFeedback", all_start)
        read_all = APP[all_start:all_end]
        self.assertIn("const contextIsCurrent = () => version === authContextVersion && authSession?.user?.id === userId;", read_all)
        self.assertIn("if (contextIsCurrent()) {", read_all)
        self.assertIn("button.disabled = false;", read_all)

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


    def test_conversation_profile_updates_are_fenced_to_current_render_and_account(self):
        start = APP.index("const renderConversations = threads =>")
        end = APP.index("const loadConversations = async () =>", start)
        renderer = APP[start:end]
        self.assertIn("const renderVersion = ++conversationRenderVersion;", renderer)
        self.assertIn("const contextVersion = authContextVersion;", renderer)
        self.assertIn("renderVersion!==conversationRenderVersion", renderer)
        self.assertIn("contextVersion!==authContextVersion", renderer)
        self.assertIn("authSession?.user?.id!==userId", renderer)
        self.assertIn("!button.isConnected", renderer)


    def test_conversation_message_loads_are_latest_request_and_account_only(self):
        start = APP.index("const loadConversationMessages = async (threadId) =>")
        end = APP.index("const openConversation = (threadId,partnerId)", start)
        loader = APP[start:end]
        self.assertIn("requestVersion=++conversationMessagesRequestVersion", loader)
        self.assertIn("const contextIsCurrent=()=>", loader)
        self.assertIn("requestVersion===conversationMessagesRequestVersion", loader)
        self.assertIn("if(!contextIsCurrent())return;", loader)
        self.assertIn("if(contextIsCurrent())loadConversations();", loader)

    def test_message_edit_and_delete_actions_are_account_and_thread_fenced(self):
        start = APP.index("const loadConversationMessages = async (threadId) =>")
        end = APP.index("const openConversation = (threadId,partnerId)", start)
        loader = APP[start:end]
        self.assertEqual(loader.count("const actionIsCurrent=()=>"), 2)
        self.assertIn("activeMessageThreadId===actionThreadId", loader)
        self.assertIn("if(actionIsCurrent())loadConversationMessages(threadId);", loader)
        self.assertIn("if(actionIsCurrent())messagesFeedback(", loader)


    def test_account_switch_invalidates_conversation_render_and_message_requests(self):
        start = APP.index("const refreshAuthUI = session =>")
        end = APP.index("authSession = session;", start)
        auth_transition = APP[start:end]
        self.assertIn("conversationRenderVersion += 1;", auth_transition)
        self.assertIn("conversationMessagesRequestVersion += 1;", auth_transition)


    def test_direct_message_send_cleanup_is_fenced_to_originating_thread(self):
        start = APP.index('$("#directMessageForm")?.addEventListener')
        end = APP.index('const reportFeedback', start)
        handler = APP[start:end]
        self.assertIn("const contextIsCurrent=()=>version===authContextVersion", handler)
        self.assertIn("activeMessageThreadId===threadId&&activeMessagePartnerId===partnerId", handler)
        self.assertIn("finally{if(contextIsCurrent())button.disabled=false;}", handler)
        self.assertIn("if(contextIsCurrent())messagesFeedback(", handler)

    def test_user_report_submission_cleanup_is_account_fenced(self):
        start = APP.index('$("#userReportForm")?.addEventListener')
        end = APP.index("const adminFeedback", start)
        report = APP[start:end]
        self.assertIn("const version = authContextVersion, userId = authSession.user.id;", report)
        self.assertIn("const contextIsCurrent = () => version === authContextVersion && authSession?.user?.id === userId;", report)
        self.assertIn("if (!contextIsCurrent()) return;", report)
        self.assertIn("if (contextIsCurrent()) button.disabled = false;", report)

    def test_block_actions_and_block_list_mutations_are_account_and_request_fenced(self):
        start = APP.index('$("#blockConversationUser")?.addEventListener')
        end = APP.index('$("#messagesRefresh")', start)
        block_actions = APP[start:end]
        self.assertIn("const contextIsCurrent=()=>version===authContextVersion&&authSession?.user?.id===userId&&activeMessagePartnerId===partnerId&&activeMessageThreadId===threadId;", block_actions)
        self.assertIn("if(!contextIsCurrent())return;", block_actions)
        self.assertIn("const contextIsCurrent=()=>version===authContextVersion&&authSession?.user?.id===userId&&Number(list.dataset.requestVersion)===requestVersion;", block_actions)
        self.assertIn("if(!contextIsCurrent())return false;", block_actions)
        self.assertIn("if(contextIsCurrent())button.disabled=false;", block_actions)
        self.assertIn("if(!contextIsCurrent())return;", block_actions)

    def test_new_conversation_form_cleanup_is_account_fenced(self):
        start = APP.index('$("#newConversationForm")?.addEventListener')
        end = APP.index('$("#directMessageForm")?.addEventListener', start)
        form = APP[start:end]
        self.assertIn("const contextIsCurrent=()=>version===authContextVersion&&authSession?.user?.id===userId;", form)
        self.assertIn("if(!contextIsCurrent())return;", form)
        self.assertIn("finally{if(contextIsCurrent())button.disabled=false;}", form)

    def test_admin_suspension_form_cleanup_is_account_fenced(self):
        start = APP.index('$("#adminSuspensionForm")?.addEventListener')
        end = APP.index("if (authSession?.user) setTimeout(loadAccountRole", start)
        form = APP[start:end]
        self.assertIn("const contextIsCurrent=()=>requestVersion===authContextVersion&&authSession?.user?.id===adminUserId;", form)
        self.assertIn("if(!contextIsCurrent())return;", form)
        self.assertIn("finally{if(contextIsCurrent())button.disabled=false;}", form)

    def test_conversation_list_refresh_ignores_older_requests(self):
        start = APP.index("const loadConversations = async () =>")
        end = APP.index("const loadConversationMessages", start)
        loader = APP[start:end]
        self.assertIn("const requestVersion=list?(Number(list.dataset.requestVersion)||0)+1:1;", loader)
        self.assertIn("Number(list.dataset.requestVersion)===requestVersion", loader)
        self.assertIn("if(!contextIsCurrent())return;", loader)

    def test_admin_workspace_refresh_is_latest_request_and_account_only(self):
        start = APP.index("let adminWorkspaceRequestVersion = 0;")
        end = APP.index("const renderAdminReports", start)
        loader = APP[start:end]
        self.assertIn("requestVersion = ++adminWorkspaceRequestVersion", loader)
        self.assertIn("requestVersion === adminWorkspaceRequestVersion", loader)
        self.assertIn("authSession?.user?.id === userId", loader)
        self.assertIn("if (!contextIsCurrent()) return;", loader)

    def test_community_profile_refresh_is_latest_request_and_account_only(self):
        start = APP.index("let communityProfileRequestVersion = 0;")
        end = APP.index('$("#communityProfileForm")?.addEventListener', start)
        loader = APP[start:end]
        self.assertIn("const requestVersion=++communityProfileRequestVersion;", loader)
        self.assertIn("requestVersion===communityProfileRequestVersion", loader)
        self.assertIn("if(!contextIsCurrent())return;", loader)
        self.assertIn("catch(error){if(contextIsCurrent())", loader)

    def test_notification_refresh_is_latest_request_and_account_only(self):
        start = APP.index("let notificationLoadRequestVersion = 0;")
        end = APP.index("const markOneNotificationRead", start)
        loader = APP[start:end]
        self.assertIn("const requestVersion=++notificationLoadRequestVersion;", loader)
        self.assertIn("requestVersion===notificationLoadRequestVersion", loader)
        self.assertIn("if (!contextIsCurrent()) return;", loader)

    def test_admin_report_and_suspension_actions_are_account_fenced(self):
        reports_start = APP.index("const renderAdminReports = reports =>")
        suspensions_start = APP.index("const renderAdminSuspensions = suspensions =>", reports_start)
        reports = APP[reports_start:suspensions_start]
        self.assertIn("const contextIsCurrent=()=>renderVersion===authContextVersion&&authSession?.user?.id===renderUserId;", reports)
        self.assertIn("if(!contextIsCurrent())return;", reports)
        self.assertIn("finally{if(contextIsCurrent())save.disabled=false;}", reports)
        admin_form_start = APP.index("const renderAdminSuspensions = suspensions =>")
        admin_form_end = APP.index('$("#adminRefresh")?.addEventListener', admin_form_start)
        suspensions = APP[admin_form_start:admin_form_end]
        self.assertIn("const contextIsCurrent=()=>renderVersion===authContextVersion&&authSession?.user?.id===renderUserId;", suspensions)
        self.assertIn("if(!contextIsCurrent()||!confirm(", suspensions)
        self.assertIn("finally{if(contextIsCurrent())revoke.disabled=false;}", suspensions)

    def test_movie_stage_ai_response_is_fenced_to_originating_account(self):
        start = APP.index('aiButton.addEventListener("click",async()=>{')
        end = APP.index("aiTools.append(aiButton", start)
        handler = APP[start:end]
        self.assertIn("const requestAuthVersion=authContextVersion,requestUserId=authSession?.user?.id||\"guest\";", handler)
        self.assertIn("if(!contextIsCurrent())return;", handler)
        self.assertIn("if(contextIsCurrent())aiStatus.textContent=", handler)
        self.assertIn("if(contextIsCurrent()){aiButton.disabled=false;", handler)

    def test_message_profile_cache_is_cleared_and_fenced_on_account_change(self):
        boundary_start = APP.index("const refreshAuthUI = session =>")
        boundary_end = APP.index("authSession = session;", boundary_start)
        boundary = APP[boundary_start:boundary_end]
        self.assertIn("messageProfileCache.clear();", boundary)
        self.assertIn("messageProfilePending.clear();", boundary)
        loader_start = APP.index("const loadMessageProfile = async userId =>")
        loader_end = APP.index("const messagePartnerId", loader_start)
        loader = APP[loader_start:loader_end]
        self.assertIn("const requestVersion=authContextVersion,requestOwnerId=authSession?.user?.id;", loader)
        self.assertIn("if(contextIsCurrent())messageProfileCache.set(userId, profile || {});", loader)
        self.assertIn("if(messageProfilePending.get(userId)===pending)messageProfilePending.delete(userId);", loader)

    def test_movie_cloud_sync_rechecks_account_after_each_async_boundary(self):
        start = APP.index("const scheduleMovieCloudSync = () =>")
        end = APP.index("const loadMovieProjectsFromCloud", start)
        sync = APP[start:end]
        self.assertIn("requestVersion = authContextVersion", sync)
        self.assertIn("const contextIsCurrent = () => requestVersion === authContextVersion && authSession?.user?.id === userId;", sync)
        self.assertGreaterEqual(sync.count("if (!contextIsCurrent()) return;"), 5)
        self.assertIn("if (contextIsCurrent()) {", sync)


if __name__ == "__main__":
    unittest.main(verbosity=2)
