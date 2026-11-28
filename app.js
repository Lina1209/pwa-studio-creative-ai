(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const API_URL_KEY = "pwa-studio-api-url";
  // Supabase Auth: only the public publishable key is used in the browser.
  const authGate = $("#authGate");
  const authFeedback = $("#authFeedback");
  const supabaseConfig = window.PWA_SUPABASE_CONFIG || {};
  const supabaseClient = window.supabase && supabaseConfig.url && supabaseConfig.publishableKey
    ? window.supabase.createClient(supabaseConfig.url, supabaseConfig.publishableKey)
    : null;
  let authSession = null;
  let authContextVersion = 0;
  let scheduledAuthLoadContextVersion = -1;
  let authLoadTimer = null;
  let activeAssistantConversationId = null;
  let assistantConversationLoadVersion = 0;
  let assistantConversationIntentVersion = 0;
  let assistantHistoryLoadVersion = 0;
  let assistantHistoryBusy = false;
  let assistantUserId = null;
  let activeMessageThreadId = null;
  let activeMessagePartnerId = null;
  let conversationsCache = [];
  const messageProfileCache = new Map();
  const messageProfilePending = new Map();
  let conversationRenderVersion = 0;
  let conversationMessagesRequestVersion = 0;
  let communitySearchRequestVersion = 0;
  let communityProfileRequestVersion = 0;
  const setAuthMessage = (message, isError = false) => {
    if (authFeedback) { authFeedback.textContent = message; authFeedback.style.color = isError ? "#ff9b9b" : "#b9e6c8"; }
  };
  const setAuthMode = mode => {
    authGate.hidden = false;
    $("#loginForm").hidden = mode !== "login";
    $("#signupForm").hidden = mode !== "signup";
    $("#resetForm").hidden = mode !== "reset";
    $("#showLogin").classList.toggle("active", mode === "login");
    $("#showSignup").classList.toggle("active", mode === "signup");
    $("#authTitle").textContent = mode === "signup" ? "Создайте аккаунт" : mode === "reset" ? "Восстановление пароля" : "Добро пожаловать!";
    $("#authDescription").textContent = mode === "signup" ? "Ваше личное пространство для творчества." : mode === "reset" ? "Отправим письмо со ссылкой для восстановления доступа." : "Войдите в своё творческое пространство.";
    setAuthMessage("");
  };
  const refreshAuthUI = session => {
    const nextUserId = session?.user?.id || null;
    const identityChanged = nextUserId !== assistantUserId;
    if (identityChanged) {
      const adminPanel = $("#adminPanel"); if (adminPanel) adminPanel.hidden = true;
      const notificationPanel = $("#notificationPanel"); if (notificationPanel) notificationPanel.hidden = true;
      const notificationList = $("#notificationList"); if (notificationList) notificationList.replaceChildren();
      const notificationBadge = $("#notificationUnread"); if (notificationBadge) notificationBadge.hidden = true;
      const messagesPanel = $("#messagesPanel"); if (messagesPanel) messagesPanel.hidden = true;
      const communityPanel = $("#communityPanel"); if (communityPanel) communityPanel.hidden = true;
      const communityResults = $("#communityResults"); if (communityResults) communityResults.replaceChildren();
      const communityPublicProfile = $("#communityPublicProfile"); if (communityPublicProfile) { communityPublicProfile.hidden = true; communityPublicProfile.replaceChildren(); }
      const conversationList = $("#conversationList"); if (conversationList) conversationList.replaceChildren();
      conversationsCache = [];
      messageProfileCache.clear();
      messageProfilePending.clear();
      const directMessageList = $("#directMessageList"); if (directMessageList) directMessageList.replaceChildren();
      const directMessageForm = $("#directMessageForm"); if (directMessageForm) directMessageForm.hidden = true;
      const conversationTitle = $("#conversationTitle"); if (conversationTitle) conversationTitle.textContent = "Выберите диалог";
      activeMessageThreadId = null;
      activeMessagePartnerId = null;
      assistantUserId = nextUserId;
      authContextVersion += 1;
      conversationRenderVersion += 1;
      conversationMessagesRequestVersion += 1;
      communitySearchRequestVersion += 1;
      communityProfileRequestVersion += 1;
      // Invalidate every in-flight Companion operation at the account boundary.
      assistantConversationLoadVersion += 1;
      assistantConversationIntentVersion += 1;
      assistantHistoryLoadVersion += 1;
      assistantHistoryBusy = false;
      activeAssistantConversationId = null;
      const history = $("#assistantHistoryList");
      const messages = $("#assistantMessages");
      const status = $("#assistantHistoryStatus");
      if (history) history.replaceChildren();
      if (messages) messages.replaceChildren();
      if (status) status.textContent = nextUserId ? "Загружаем историю нового аккаунта…" : "Войдите в аккаунт, чтобы сохранять историю диалогов.";
    }
    authSession = session;
    // Token refreshes and duplicate INITIAL_SESSION notifications are not
    // account changes; only identity transitions should reset account-bound UI.
    if (identityChanged) window.dispatchEvent(new Event("pwa-studio-auth-changed"));
    const user = session && session.user;
    authGate.hidden = true;
    $("#openLogin").hidden = !!user;
    $("#openSignup").hidden = !!user;
    const statusPill = $(".backend-pill");
    if (statusPill) statusPill.innerHTML = `<i></i> ${user ? "Аккаунт активен" : "Гостевой режим"}`;
    if (user) {
      const label = user.user_metadata?.display_name || user.email || "Creator";
      const profile = $(".profile");
      if (profile) { $("b", profile).textContent = label; $("small", profile).textContent = "Аккаунт активен"; }
      const logout = $("#profileLogout"); if (logout) logout.hidden = false;
      const avatar = $(".profile .avatar");
      if (avatar) avatar.textContent = label.trim().charAt(0).toUpperCase() || "C";
      const accountName = $("#accountName"); if (accountName) accountName.textContent = label;
      const accountEmail = $("#accountEmail"); if (accountEmail) accountEmail.textContent = user.email || "Адрес почты не указан";
      const accountAvatar = $("#accountAvatar"); if (accountAvatar) accountAvatar.textContent = label.trim().charAt(0).toUpperCase() || "C";
      const accountRole = $("#accountRole"); if (accountRole) accountRole.textContent = "Пользователь";
      reportFeedback("Вы вошли в аккаунт. Опишите проблему и отправьте обращение модерации.");
      $("#accountLogin").hidden = true; $("#accountLogout").hidden = false;
      const guestNav = $("#guestSpaceNav"); if (guestNav) guestNav.hidden = true;
      const topAvatar = $(".top-avatar");
      if (topAvatar) topAvatar.textContent = label.trim().charAt(0).toUpperCase() || "C";
    } else {
      const profile = $(".profile");
      if (profile) { $("b", profile).textContent = "Гость"; $("small", profile).textContent = "Гостевой режим"; }
      const sideAvatar = $(".profile .avatar"); if (sideAvatar) sideAvatar.textContent = "✦";
      const logout = $("#profileLogout"); if (logout) logout.hidden = true;
      const accountName = $("#accountName"); if (accountName) accountName.textContent = "Гостевой просмотр";
      const accountEmail = $("#accountEmail"); if (accountEmail) accountEmail.textContent = "Войдите или зарегистрируйтесь, чтобы открыть личное пространство.";
      const accountAvatar = $("#accountAvatar"); if (accountAvatar) accountAvatar.textContent = "✦";
      const accountRole = $("#accountRole"); if (accountRole) accountRole.textContent = "Гость";
      reportFeedback("Для отправки обращения войдите в аккаунт.");
      $("#accountLogin").hidden = false; $("#accountLogout").hidden = true;
      const guestNav = $("#guestSpaceNav"); if (guestNav) guestNav.hidden = false;
      const panel = $("#adminPanel"); if (panel) panel.hidden = true;
      const movieFeedback = $("#movieFeedback");
      if (movieFeedback) movieFeedback.textContent = "✓ Гостевые черновики сохраняются только в этом браузере. Синхронизация с Supabase отключена.";
      const topAvatar = $(".top-avatar");
      if (topAvatar) topAvatar.textContent = "L";
    }
  };
  const scheduleAuthContextLoad = () => {
    const scheduledVersion = authContextVersion;
    // getSession() and INITIAL_SESSION can report the same account almost
    // simultaneously. Load account data once per identity context.
    if (scheduledAuthLoadContextVersion === scheduledVersion) return;
    scheduledAuthLoadContextVersion = scheduledVersion;
    clearTimeout(authLoadTimer);
    authLoadTimer = setTimeout(() => {
      authLoadTimer = null;
      if (scheduledVersion !== authContextVersion) return;
      if (typeof renderMovieProjects === "function") renderMovieProjects();
      if (typeof loadMovieProjectsFromCloud === "function") loadMovieProjectsFromCloud();
      if (typeof loadAccountRole === "function") loadAccountRole();
      if (typeof loadNotifications === "function") loadNotifications();
      if (typeof loadConversations === "function") loadConversations();
      if (typeof loadCommunityProfile === "function") loadCommunityProfile();
      if (typeof renderAssistantHistory === "function") renderAssistantHistory();
    }, 0);
  };
  if (!supabaseClient) {
    authGate.hidden = false;
    setAuthMessage("Не найдена конфигурация Supabase. Проверьте файл supabase-config.js.", true);
  } else {
    supabaseClient.auth.getSession().then(({data,error}) => {
      if (error) setAuthMessage(error.message, true);
      refreshAuthUI(data?.session || null);
      scheduleAuthContextLoad();
    });
    supabaseClient.auth.onAuthStateChange((_event, session) => {
      refreshAuthUI(session);
      scheduleAuthContextLoad();
    });
  }
  // Password visibility controls for both sign-in and registration forms.
  const passwordStyle = document.createElement("style");
  passwordStyle.textContent = `
    .password-field-wrap{position:relative;display:block;width:100%}
    .password-field-wrap input{width:100%;padding-right:48px}
    .password-visibility-toggle{position:absolute;right:10px;top:50%;transform:translateY(-50%);border:0;background:transparent;color:inherit;opacity:.8;padding:8px;cursor:pointer;font-size:18px;line-height:1}
    .password-visibility-toggle:focus-visible{outline:2px solid #b9a0ff;border-radius:8px}
  `;
  document.head.appendChild(passwordStyle);
  const movieListStyle = document.createElement("style");
  movieListStyle.textContent = `
    .movie-project-accordion{padding:0!important;overflow:hidden}
    .movie-project-toggle{display:flex;align-items:center;gap:14px;width:100%;padding:18px 20px;text-align:left;color:inherit;background:transparent;border:0;cursor:pointer}
    .movie-project-toggle:hover{background:rgba(160,130,230,.07)}
    .movie-project-number{display:grid;place-items:center;flex:0 0 36px;height:36px;border-radius:11px;background:rgba(157,121,235,.15);color:#c8aaff;font-weight:800;font-size:12px}
    .movie-project-heading{display:grid;gap:5px;min-width:0;flex:1}
    .movie-project-heading b{font-size:15px;overflow-wrap:anywhere}
    .movie-project-heading small,.movie-project-date{color:var(--muted);font-size:12px}
    .movie-project-chevron{font-size:22px;color:#c8aaff;transition:transform .2s}
    .movie-project-details{padding:0 20px 20px 70px}
    .movie-project-details[hidden]{display:none}
    .movie-project-details p{white-space:pre-wrap;line-height:1.65;margin:0 0 12px;color:var(--text)}
    .movie-project-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}
    .movie-project-actions button{min-height:40px;flex:0 1 auto}
    @media(max-width:520px){.movie-project-toggle{padding:15px 13px;gap:10px}.movie-project-details{padding:0 13px 16px 59px}.movie-project-heading b{font-size:14px}}
  `;
  document.head.appendChild(movieListStyle);
const movieHistoryStyle = document.createElement("style");
  movieHistoryStyle.textContent = `
    .movie-history-overlay{position:fixed;inset:0;z-index:9998;background:rgba(8,7,18,.82);backdrop-filter:blur(8px);display:grid;place-items:center;padding:16px;overflow:auto}
    .movie-history-dialog{width:min(100%,900px);max-height:90vh;overflow:auto;padding:22px;border:1px solid rgba(170,140,255,.28);border-radius:20px;background:var(--panel,#171426);color:var(--text,#f7f4ff);box-shadow:0 24px 90px #0009}
    .movie-history-heading{display:flex;align-items:center;justify-content:space-between;gap:12px}.movie-history-heading h2{margin:0;font-size:22px}
    .movie-history-intro{color:var(--muted);line-height:1.5}.movie-history-layout{display:grid;grid-template-columns:minmax(150px,220px) minmax(0,1fr);gap:16px}
    .movie-history-list{display:grid;align-content:start;gap:7px;max-height:62vh;overflow:auto}
    .movie-history-item{padding:11px;text-align:left;border:1px solid rgba(170,140,255,.2);border-radius:10px;background:transparent;color:inherit;cursor:pointer}
    .movie-history-item[aria-pressed=true]{border-color:#a98aff;background:rgba(157,121,235,.16)}
    .movie-history-preview{min-width:0;max-height:62vh;overflow:auto;padding:14px;border:1px solid rgba(170,140,255,.18);border-radius:12px}
    .movie-history-meta,.movie-history-facts{color:var(--muted);font-size:12px}.movie-history-preview h3{margin:8px 0}
    .movie-history-section{margin:16px 0}.movie-history-section b{display:block;color:#c8aaff;margin-bottom:5px}
    .movie-history-section p{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.55;margin:0}
    .movie-history-restore{margin-top:12px;width:100%;justify-content:center}
    @media(max-width:640px){.movie-history-dialog{padding:16px}.movie-history-layout{grid-template-columns:1fr}.movie-history-list{grid-template-columns:repeat(2,minmax(0,1fr));max-height:180px}.movie-history-item{font-size:12px;padding:9px}.movie-history-preview{max-height:none}}
  `;
  document.head.appendChild(movieHistoryStyle);
  ["#loginPassword", "#signupPassword"].forEach(selector => {
    const input = $(selector);
    if (!input) return;
    const wrapper = document.createElement("span");
    wrapper.className = "password-field-wrap";
    input.parentNode.insertBefore(wrapper, input);
    wrapper.appendChild(input);
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "password-visibility-toggle";
    toggle.textContent = "👁";
    toggle.setAttribute("aria-label", "Показать пароль");
    toggle.setAttribute("aria-pressed", "false");
    toggle.addEventListener("click", () => {
      const visible = input.type === "password";
      input.type = visible ? "text" : "password";
      toggle.textContent = visible ? "🙈" : "👁";
      toggle.setAttribute("aria-label", visible ? "Скрыть пароль" : "Показать пароль");
      toggle.setAttribute("aria-pressed", String(visible));
    });
    wrapper.appendChild(toggle);
  });

  $("#openLogin").addEventListener("click", () => setAuthMode("login"));
  $("#openSignup").addEventListener("click", () => setAuthMode("signup"));
  $("#closeAuth").addEventListener("click", () => { authGate.hidden = true; });
  authGate.addEventListener("click", event => { if (event.target === authGate) authGate.hidden = true; });
  $("#showLogin").addEventListener("click", () => setAuthMode("login"));
  $("#showSignup").addEventListener("click", () => setAuthMode("signup"));
  $("#showReset").addEventListener("click", () => setAuthMode("reset"));
  $("#backToLogin").addEventListener("click", () => setAuthMode("login"));
  $("#loginForm").addEventListener("submit", async event => {
    event.preventDefault();
    if (!supabaseClient) return;
    const button = $("#loginForm button[type=submit]"); button.disabled = true; setAuthMessage("Выполняем вход…");
    try {
      const {data,error} = await supabaseClient.auth.signInWithPassword({email:$("#loginEmail").value.trim(),password:$("#loginPassword").value});
      if (error) throw error;
      refreshAuthUI(data.session);
    } catch(error) { setAuthMessage(error.message || "Не удалось войти.", true); }
    finally { button.disabled = false; }
  });
  $("#signupForm").addEventListener("submit", async event => {
    event.preventDefault();
    if (!supabaseClient) return;
    const button = $("#signupForm button[type=submit]"); button.disabled = true; setAuthMessage("Создаём аккаунт…");
    try {
      const {data,error} = await supabaseClient.auth.signUp({
        email:$("#signupEmail").value.trim(), password:$("#signupPassword").value,
        options:{data:{display_name:$("#signupName").value.trim()},emailRedirectTo:location.origin + location.pathname}
      });
      if (error) throw error;
      if (data.session) refreshAuthUI(data.session);
      else setAuthMessage("Аккаунт создан. Проверьте почту и подтвердите адрес, затем войдите.");
    } catch(error) { setAuthMessage(error.message || "Не удалось создать аккаунт.", true); }
    finally { button.disabled = false; }
  });
  $("#resetForm").addEventListener("submit", async event => {
    event.preventDefault();
    if (!supabaseClient) return;
    const button = $("#resetForm button[type=submit]"); button.disabled = true; setAuthMessage("Отправляем письмо…");
    try {
      const {error} = await supabaseClient.auth.resetPasswordForEmail($("#resetEmail").value.trim(),{redirectTo:location.origin + location.pathname});
      if (error) throw error;
      setAuthMessage("Если адрес зарегистрирован, на него придёт письмо со ссылкой для восстановления.");
    } catch(error) { setAuthMessage(error.message || "Не удалось отправить письмо.", true); }
    finally { button.disabled = false; }
  });
  const authLogoutButton = document.createElement("button");
  authLogoutButton.type = "button"; authLogoutButton.id = "profileLogout"; authLogoutButton.className = "auth-link"; authLogoutButton.textContent = "Выйти из аккаунта"; authLogoutButton.hidden = true;
  authLogoutButton.addEventListener("click", async () => {
    if (!supabaseClient || !authSession?.user) return;
    const requestUserId = authSession.user.id;
    const requestVersion = authContextVersion;
    const contextIsCurrent = () => requestVersion === authContextVersion && authSession?.user?.id === requestUserId;
    authLogoutButton.disabled = true;
    try {
      const {error} = await supabaseClient.auth.signOut();
      // Supabase's auth-state event normally performs the transition. Never let
      // a late logout response clear or overwrite a newer account's UI.
      if (!contextIsCurrent()) return;
      if (error) setAuthMessage(error.message, true);
      else { authGate.hidden = true; setAuthMessage(""); refreshAuthUI(null); }
    } catch (error) {
      if (contextIsCurrent()) setAuthMessage(error.message || "Не удалось выйти из аккаунта.", true);
    } finally {
      if (contextIsCurrent()) authLogoutButton.disabled = false;
    }
  });
  const profileBlock = $(".profile");
  if (profileBlock) profileBlock.appendChild(authLogoutButton);


  const getApiBase = () => (localStorage.getItem(API_URL_KEY) || "https://pwa-studio-creative-ai.onrender.com").trim().replace(/\/+$/, "");
  const loadAccountRole = async () => {
    const panel = $("#adminPanel");
    if (!authSession?.user || !panel) { if (panel) panel.hidden = true; return; }
    const userId = authSession.user.id;
    const version = authContextVersion;
    try {
      const data = await apiRequest("/api/auth/me");
      if (version !== authContextVersion || authSession?.user?.id !== userId) return;
      $("#accountRole").textContent = data.role === "admin" ? "Владелец студии" : "Автор";
      panel.hidden = data.role !== "admin";
      if (data.role === "admin") loadAdminWorkspace();
    } catch {
      if (version === authContextVersion && authSession?.user?.id === userId) panel.hidden = true;
    }
  };
  const apiRequest = async (path, options = {}) => {
    const base = getApiBase();
    if (!base) throw new Error("Сначала укажите адрес развёрнутого backend API в разделе «Настройки».");
    const token = authSession?.access_token;
    const response = await fetch(base + path, { ...options, headers: { "Content-Type": "application/json", ...(token ? { Authorization: "Bearer " + token } : {}), ...(options.headers || {}) } });
    let data = {};
    try { data = await response.json(); } catch {}
    if (!response.ok) {
      const detail = data.detail;
      const error = new Error(typeof detail === "string" ? detail : (detail?.message || "Ошибка API (" + response.status + ")."));
      error.status = response.status;
      error.code = typeof detail === "object" && detail ? detail.code : null;
      throw error;
    }
    return data;
  };

  // Shared bridge for Audio → Story. Uses the existing authenticated AI endpoint and movie storage.
  let latestAudioGenerationContext = null;
  window.PWAStudioAudioBridge = {
    async generate({ transcript, outputType, language, sourceKind, fileName }) {
      const clean = String(transcript || "").trim();
      if (!clean) throw new Error("Добавьте распознанный текст или описание аудио.");
      const labels = { movie:"сценарий короткометражного фильма с названием, персонажами, сценами, диалогами и финалом", story:"цельный художественный рассказ с названием, развитием и завершённой концовкой", lyrics:"оригинальный текст песни: куплеты, припев и при необходимости бридж" };
      const prompt = [
        "Создай творческий материал для PWA Studio на основе материала пользователя.",
        "Тип исходника: " + (sourceKind || "аудиозапись") + ".",
        "Имя аудиофайла (только справочно, содержимое файла не передавалось): " + (fileName || "не указано") + ".",
        "Язык результата: " + (language || "русский") + ".",
        "Нужный результат: " + (labels[outputType] || labels.movie) + ".",
        "Если исходник — распознанная речь, бережно сохрани основные мысли и факты, исправь очевидные ошибки распознавания, не выдумывай факты от имени говорящего.",
        "Если исходник — музыкальная идея или описание песни, используй её настроение и образы, но не воспроизводи защищённые авторские тексты.",
        "Если исходник короткий или неясный, развей его творчески и отметь придуманные детали как художественные.",
        "\nМатериал пользователя:\n" + clean
      ].join("\n");
      const requestUserId = authSession?.user?.id || null;
      const requestVersion = authContextVersion;
      const result = await apiRequest("/api/chat", { method:"POST", body:JSON.stringify({message:prompt,history:[]}) });
      if (requestVersion !== authContextVersion || (authSession?.user?.id || null) !== requestUserId) {
        throw new Error("Аккаунт изменился во время создания материала. Повторите запрос в текущем аккаунте.");
      }
      latestAudioGenerationContext = { userId:requestUserId, version:requestVersion, reply:result.reply };
      return result.reply;
    },
    createMovie({ title, story, sourceLabel }) {
      const generation = latestAudioGenerationContext;
      if (!generation || !String(story || "").trim() ||
          generation.version !== authContextVersion ||
          generation.userId !== (authSession?.user?.id || null)) {
        throw new Error("Результат создан в другом сеансе или аккаунте. Создайте материал заново.");
      }
      const name = String(title || "История из аудио").trim().slice(0,90) || "История из аудио";
      const text = String(story || "").trim();
      if (!text) throw new Error("Сценарий пуст.");
      const now = new Date().toISOString();
      const project = {
        id: movieId(), name, idea: text.slice(0,12000), genre:"Приключения",
        duration:5, frame:"16:9", createdAt:now, updatedAt:now,
        ...(!authSession?.user ? {guestExpiresAt:new Date(Date.now()+24*60*60*1000).toISOString()} : {}),
        workflowStep:0, completedSteps:[], story:text, storyboard:"", characters:"",
        voices: sourceLabel ? "Источник идеи: " + String(sourceLabel).slice(0,180) : "", edit:"", versions:[]
      };
      const projects = movieRead();
      projects.unshift(project);
      if (!movieWrite(projects)) throw new Error("Не удалось сохранить проект фильма.");
      activeMovieId = project.id; editingMovieId = project.id;
    
  renderMovieProjects();
      if (!authSession?.user) renderGuestSpace();
      navigate("movie");
      setTimeout(() => openMovieStage(project.id,0), 80);
      return { id:project.id, name };
    }
  };


  const PROFILE_AVATAR_CATALOG = globalThis.PWAProfileAvatarCatalog.items;
  const PROFILE_AVATAR_DEFAULT="portrait-violet";
  let profileAvatarSavedId=PROFILE_AVATAR_DEFAULT,profileAvatarDraftId=PROFILE_AVATAR_DEFAULT,profileAvatarCategory="all";
  const KATTY_EXPRESSIONS=[
    ["neutral-warm","Спокойствие"],["joy","Радость"],["delight","Восторг"],["curious","Любопытство"],
    ["focused","Работа"],["surprised","Удивление"],["empathetic","Поддержка"],["thinking","Размышление"]
  ];
  let kattyExpressionDraft="neutral-warm";

  const profileAvatarPath=id=>{
    return globalThis.PWAProfileAvatarCatalog.getAssetPath(id);
  };
  const applyProfileAvatarChrome=id=>{
    const src=profileAvatarPath(id);
    ["#accountAvatar","#topAvatar",".profile .avatar"].forEach(selector=>{
      const node=$(selector);if(!node)return;
      const img=document.createElement("img");img.src=src;img.alt="Аватар профиля";img.loading="lazy";
      img.onerror=()=>{node.replaceChildren();node.textContent="✦";};
      node.replaceChildren(img);
    });
  };
  const profileAvatarNode=(profile,large=false)=>{
    const item=PROFILE_AVATAR_CATALOG.find(entry=>entry.id===profile.avatar_catalog_id);
    const node=document.createElement("div");
    node.className="community-user-avatar"+(large?" community-user-avatar-large":"");
    if(item){
      const img=document.createElement("img");img.src=profileAvatarPath(item.id);img.alt="Аватар: "+item.name;img.loading="lazy";
      img.onerror=()=>{node.replaceChildren();node.textContent=(profile.display_name||"?").trim().charAt(0).toUpperCase();};
      node.append(img);
    }else node.textContent=(profile.display_name||"?").trim().charAt(0).toUpperCase();
    return node;
  };
  const renderProfileAvatarPicker=()=>{
    const grid=$("#profileAvatarGrid"),categories=$("#profileAvatarCategories"),preview=$("#profileAvatarPreview"),apply=$("#profileAvatarApply");
    if(!grid||!categories)return;
    if(preview){const item=PROFILE_AVATAR_CATALOG.find(entry=>entry.id===profileAvatarDraftId);const isKatty=profileAvatarDraftId==="katty-assistant";preview.src=isKatty?"assets/characters/katty/expressions/"+kattyExpressionDraft+".svg":profileAvatarPath(profileAvatarDraftId);preview.alt=isKatty?"Катти: "+(KATTY_EXPRESSIONS.find(([id])=>id===kattyExpressionDraft)?.[1]||"Спокойствие"):"Предпросмотр аватара: "+(item?.name||"Стандартный");}
    const expressionPicker=$("#kattyExpressionPicker");
    if(expressionPicker){expressionPicker.hidden=profileAvatarDraftId!=="katty-assistant";expressionPicker.replaceChildren();if(profileAvatarDraftId==="katty-assistant"){const title=document.createElement("p");title.className="katty-expression-title";title.textContent="Выражение Катти · только предпросмотр";expressionPicker.append(title);KATTY_EXPRESSIONS.forEach(([id,label])=>{const button=document.createElement("button");button.type="button";button.className="katty-expression-option"+(kattyExpressionDraft===id?" is-selected":"");button.textContent=label;button.setAttribute("aria-pressed",String(kattyExpressionDraft===id));button.addEventListener("click",()=>{kattyExpressionDraft=id;renderProfileAvatarPicker();});expressionPicker.append(button);});}}
    categories.replaceChildren();
    const groups=[["all","Все"],...Array.from(new Map(PROFILE_AVATAR_CATALOG.map(item=>[item.category,[item.category,item.group]])).values())];
    groups.forEach(([id,label])=>{const button=document.createElement("button");button.className="profile-avatar-category";button.textContent=label;button.type="button";button.classList.toggle("is-active",profileAvatarCategory===id);button.setAttribute("aria-pressed",String(profileAvatarCategory===id));button.addEventListener("click",()=>{profileAvatarCategory=id;renderProfileAvatarPicker();});categories.append(button);});
    grid.replaceChildren();
    PROFILE_AVATAR_CATALOG.filter(item=>profileAvatarCategory==="all"||item.category===profileAvatarCategory).forEach(item=>{
      const button=document.createElement("button");button.type="button";button.className="profile-avatar-option"+(profileAvatarDraftId===item.id?" is-selected":"");button.setAttribute("aria-pressed",String(profileAvatarDraftId===item.id));button.setAttribute("aria-label",item.name);
      const img=document.createElement("img");img.src=profileAvatarPath(item.id);img.alt="";img.loading="lazy";
      const label=document.createElement("span");label.textContent=item.name;button.append(img,label);
      button.addEventListener("click",()=>{profileAvatarDraftId=item.id;if(item.id!=="katty-assistant")kattyExpressionDraft="neutral-warm";renderProfileAvatarPicker();const feedback=$("#profileAvatarFeedback");if(feedback)feedback.textContent="Выбран образ «"+item.name+"». Нажмите «Применить аватар», чтобы сохранить.";});
      grid.append(button);
    });
    if(apply)apply.disabled=profileAvatarDraftId===profileAvatarSavedId;
  };
  const initializeGuestProfileAvatar=()=>{
    if(authSession?.user)return;
    let stored=PROFILE_AVATAR_DEFAULT;
    try{const value=localStorage.getItem("pwa_studio_guest_profile_avatar_v1");if(PROFILE_AVATAR_CATALOG.some(item=>item.id===value))stored=value;}catch(_){}
    profileAvatarSavedId=stored;profileAvatarDraftId=stored;profileAvatarCategory="all";
    renderProfileAvatarPicker();applyProfileAvatarChrome(stored);
    const feedback=$("#profileAvatarFeedback");if(feedback)feedback.textContent="Гостевой аватар хранится только в этом браузере.";
  };
  const communityFeedback = message => { const el=$("#communityProfileFeedback"); if(el)el.textContent=message; };
  $("#profileAvatarReset")?.addEventListener("click",()=>{profileAvatarDraftId=PROFILE_AVATAR_DEFAULT;profileAvatarCategory="all";renderProfileAvatarPicker();const feedback=$("#profileAvatarFeedback");if(feedback)feedback.textContent="Выбран стандартный аватар. Нажмите «Применить аватар», чтобы сохранить.";});
  initializeGuestProfileAvatar();
  $("#profileAvatarApply")?.addEventListener("click",async()=>{
    const userId=authSession?.user?.id,button=$("#profileAvatarApply");
    if(!userId){
      try{
        localStorage.setItem("pwa_studio_guest_profile_avatar_v1",profileAvatarDraftId);
        profileAvatarSavedId=profileAvatarDraftId;renderProfileAvatarPicker();applyProfileAvatarChrome(profileAvatarSavedId);
        const feedback=$("#profileAvatarFeedback");if(feedback)feedback.textContent="✓ Гостевой аватар сохранён только на этом устройстве.";
      }catch(error){const feedback=$("#profileAvatarFeedback");if(feedback)feedback.textContent="Не удалось сохранить гостевой выбор в браузере.";}
      return;
    }
    const version=authContextVersion;
    const contextIsCurrent=()=>version===authContextVersion&&authSession?.user?.id===userId;
    button.disabled=true;
    const feedback=$("#profileAvatarFeedback");if(feedback)feedback.textContent="Сохраняем аватар…";
    try{
      const saved=await apiRequest("/api/community/profile",{method:"PATCH",body:JSON.stringify({avatar_catalog_id:profileAvatarDraftId,avatar_representation:"2d"})});
      if(version!==authContextVersion||authSession?.user?.id!==userId||saved.user_id!==userId)return;
      profileAvatarSavedId=saved.avatar_catalog_id||PROFILE_AVATAR_DEFAULT;profileAvatarDraftId=profileAvatarSavedId;renderProfileAvatarPicker();applyProfileAvatarChrome(profileAvatarSavedId);
      if(feedback)feedback.textContent="✓ Аватар сохранён и будет использоваться в карточке сообщества.";
      const item=PROFILE_AVATAR_CATALOG.find(entry=>entry.id===profileAvatarSavedId);
      if($("#profileAvatarPreview"))$("#profileAvatarPreview").alt="Текущий аватар профиля: "+(item?.name||"Стандартный");
    }catch(error){if(contextIsCurrent()&&feedback)feedback.textContent="Не удалось сохранить аватар: "+error.message;}
    finally{
      // Only the account that started this save may update the shared picker button.
      if(contextIsCurrent())button.disabled=profileAvatarDraftId===profileAvatarSavedId;
    }
  });
  const loadCommunityProfile = async () => {
    const requestVersion=++communityProfileRequestVersion;
    const version=authContextVersion,userId=authSession?.user?.id;
    const contextIsCurrent=()=>requestVersion===communityProfileRequestVersion&&version===authContextVersion&&authSession?.user?.id===userId;
    const panel=$("#communityPanel");
    if(!panel)return;
    panel.hidden=!userId;
    if(!userId){initializeGuestProfileAvatar();return;}
    try{
      const profile=await apiRequest("/api/community/profile");
      if(!contextIsCurrent())return;
      profileAvatarSavedId=PROFILE_AVATAR_CATALOG.some(item=>item.id===profile.avatar_catalog_id)?profile.avatar_catalog_id:PROFILE_AVATAR_DEFAULT;
      profileAvatarDraftId=profileAvatarSavedId;profileAvatarCategory="all";renderProfileAvatarPicker();applyProfileAvatarChrome(profileAvatarSavedId);
      $("#communityDisplayName").value=profile.display_name||"";
      $("#communityUsername").value=profile.username||"";
      $("#communityBio").value=profile.bio||"";
      $("#communityPublic").checked=profile.visibility==="public";
      $("#communityListed").checked=!!profile.show_in_directory;
      communityFeedback("Профиль загружен. Управляйте публичностью в настройках ниже.");
    }catch(error){if(contextIsCurrent())communityFeedback("Не удалось загрузить профиль: "+error.message);}
  };
  $("#communityProfileForm")?.addEventListener("submit",async event=>{
    event.preventDefault();
    if(!authSession?.user)return;
    const form=event.currentTarget,button=form.querySelector('button[type="submit"]');
    const version=authContextVersion,userId=authSession.user.id;
    const contextIsCurrent=()=>version===authContextVersion&&authSession?.user?.id===userId;
    const payload={
      display_name:$("#communityDisplayName").value.trim(),
      username:$("#communityUsername").value.trim().toLowerCase(),
      bio:$("#communityBio").value.trim(),
      visibility:$("#communityPublic").checked?"public":"private",
      show_in_directory:$("#communityListed").checked
    };
    button.disabled=true;communityFeedback("Сохраняем настройки профиля…");
    try{
      const saved=await apiRequest("/api/community/profile",{method:"PATCH",body:JSON.stringify(payload)});
      if(version!==authContextVersion||authSession?.user?.id!==saved.user_id)return;
      $("#communityUsername").value=saved.username;
      communityFeedback("✓ Карточка сохранена. "+(saved.visibility==="public"&&saved.show_in_directory?"Она доступна в каталоге.":"Профиль не показывается в каталоге."));
    }catch(error){if(contextIsCurrent())communityFeedback("Не удалось сохранить профиль: "+error.message);}
    finally{
      // A save started by another account must not unlock this account's form.
      if(contextIsCurrent())button.disabled=false;
    }
  });
  const renderCommunityResults = profiles => {
    const list=$("#communityResults");if(!list)return;
    list.replaceChildren();
    if(!profiles.length){list.append(adminNode("div","admin-empty","По этому запросу авторы не найдены."));return;}
    profiles.forEach(profile=>{
      const card=adminNode("article","community-user-card");
      const avatar=profileAvatarNode(profile);
      const details=adminNode("div","community-user-details");
      details.append(adminNode("b","",profile.display_name||"Автор"));
      details.append(adminNode("small","","@"+profile.username));
      if(profile.bio)details.append(adminNode("p","",profile.bio));
      const actions=adminNode("div","community-user-actions");
      const view=adminNode("button","secondary-button","Профиль");view.type="button";
      view.addEventListener("click",()=>openCommunityProfile(profile.user_id));
      const message=adminNode("button","primary-button","Написать");message.type="button";
      message.addEventListener("click",()=>{
        $("#messageRecipientId").value=profile.user_id;
        $("#messageFirstText").focus();
        $("#messagesPanel").hidden=false;
        $("#messagesPanel").scrollIntoView({behavior:"smooth",block:"start"});
        messagesFeedback("Получатель выбран: @"+profile.username+". Напишите первое сообщение.");
      });
      actions.append(view,message);card.append(avatar,details,actions);list.append(card);
    });
  };
  const searchCommunity = async () => {
    const requestVersion=++communitySearchRequestVersion;
    if(!authSession?.user)return;
    const q=$("#communitySearchInput").value.trim();
    if(q.length<2){$("#communityResults").replaceChildren(adminNode("div","admin-empty","Введите не менее 2 символов."));return;}
    const version=authContextVersion,userId=authSession.user.id;
    $("#communityResults").replaceChildren(adminNode("div","admin-empty","Ищем авторов…"));
    try{
      const profiles=await apiRequest("/api/community/users?q="+encodeURIComponent(q));
      if(requestVersion!==communitySearchRequestVersion||version!==authContextVersion||authSession?.user?.id!==userId)return;
      renderCommunityResults(profiles);
    }catch(error){if(requestVersion===communitySearchRequestVersion&&version===authContextVersion&&authSession?.user?.id===userId)$("#communityResults").replaceChildren(adminNode("div","admin-empty","Поиск недоступен: "+error.message));}
  };
  const openCommunityProfile = async profileUserId => {
    const requestVersion=++communityProfileRequestVersion;
    const version=authContextVersion,userId=authSession?.user?.id;
    if(!userId)return;
    const box=$("#communityPublicProfile");
    box.hidden=false;box.replaceChildren(adminNode("div","admin-empty","Загружаем карточку автора…"));
    try{
      const profile=await apiRequest("/api/community/profiles/"+encodeURIComponent(profileUserId));
      if(requestVersion!==communityProfileRequestVersion||version!==authContextVersion||authSession?.user?.id!==userId)return;
      box.replaceChildren();
      const head=adminNode("div","community-profile-card");
      head.append(profileAvatarNode(profile,true));
      const info=adminNode("div","community-user-details");
      info.append(adminNode("b","",profile.display_name||"Автор"));
      info.append(adminNode("small","","@"+profile.username));
      info.append(adminNode("p","",profile.bio||"Автор пока не добавил описание."));
      head.append(info);box.append(head);
      const actions=adminNode("div","community-user-actions");
      const message=adminNode("button","primary-button","Начать диалог");message.type="button";
      message.addEventListener("click",()=>{
        $("#messageRecipientId").value=profile.user_id;
        $("#messageFirstText").focus();
        $("#messagesPanel").hidden=false;
        $("#messagesPanel").scrollIntoView({behavior:"smooth",block:"start"});
        messagesFeedback("Карточка @"+profile.username+" открыта. Напишите первое сообщение.");
      });
      const report=adminNode("button","secondary-button","Пожаловаться");report.type="button";
      report.addEventListener("click",()=>{
        $("#reportUserId").value=profile.user_id;
        $("#reportPanel").scrollIntoView({behavior:"smooth",block:"start"});
        $("#reportDescription").focus();
      });
      actions.append(message,report);box.append(actions);
    }catch(error){if(requestVersion===communityProfileRequestVersion&&version===authContextVersion&&authSession?.user?.id===userId)box.replaceChildren(adminNode("div","admin-empty","Карточка недоступна: "+error.message));}
  };
  $("#communitySearchButton")?.addEventListener("click",searchCommunity);
  $("#communitySearchInput")?.addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();searchCommunity();}});
  $("#communityRefresh")?.addEventListener("click",()=>{loadCommunityProfile();searchCommunity();});

  const notificationFeedback = message => { const el = $("#notificationFeedback"); if (el) el.textContent = message; };
  const renderNotifications = notifications => {
    const list = $("#notificationList");
    if (!list) return;
    const items = Array.isArray(notifications) ? notifications : [];
    const unread = items.filter(item => !item.read_at).length;
    const badge = $("#notificationUnread");
    if (badge) { badge.textContent = String(unread); badge.hidden = unread === 0; }
    const readAll = $("#notificationReadAll");
    if (readAll) readAll.disabled = unread === 0;
    list.replaceChildren();
    if (!items.length) { list.append(adminNode("div","admin-empty","Пока нет уведомлений. Здесь появятся важные обновления.")); return; }
    items.forEach(item => {
      const card = adminNode("article","notification-item" + (item.read_at ? "" : " is-unread"));
      const heading = adminNode("div","notification-item-heading");
      heading.append(adminNode("b","",item.title || "Уведомление"),adminNode("time","",formatAdminDate(item.created_at)));
      card.append(heading,adminNode("p","notification-item-body",item.body || ""));
      if (!item.read_at) {
        const button = adminNode("button","notification-read-button","Отметить прочитанным");
        button.type = "button";
        button.addEventListener("click", () => markOneNotificationRead(item.id, button));
        card.append(button);
      } else {
        card.append(adminNode("span","notification-read-label","Прочитано"));
      }
      list.append(card);
    });
  };
  let notificationLoadRequestVersion = 0;
  const loadNotifications = async () => {
    const requestVersion=++notificationLoadRequestVersion;
    const panel = $("#notificationPanel");
    if (!panel) return;
    if (!authSession?.user) { panel.hidden = true; return; }
    panel.hidden = false;
    const version = authContextVersion, userId = authSession.user.id;
    const contextIsCurrent=()=>requestVersion===notificationLoadRequestVersion&&version===authContextVersion&&authSession?.user?.id===userId;
    notificationFeedback("Проверяем новые сообщения…");
    const list = $("#notificationList");
    if (list) list.replaceChildren(adminNode("div","admin-empty","Загружаем уведомления…"));
    try {
      const items = await apiRequest("/api/notifications");
      if (!contextIsCurrent()) return;
      renderNotifications(items);
      notificationFeedback(items.length ? "Уведомления синхронизированы с вашим аккаунтом." : "Новых сообщений пока нет.");
    } catch (error) {
      if (!contextIsCurrent()) return;
      notificationFeedback("Не удалось загрузить уведомления: " + error.message);
      if (list) list.replaceChildren(adminNode("div","admin-empty","Центр уведомлений временно недоступен."));
    }
  };
  const markOneNotificationRead = async (id, button) => {
    const version = authContextVersion, userId = authSession?.user?.id;
    if (!userId) return;
    const contextIsCurrent = () => version === authContextVersion && authSession?.user?.id === userId;
    button.disabled = true;
    try {
      await apiRequest("/api/notifications/" + encodeURIComponent(id) + "/read", {method:"POST"});
      if (contextIsCurrent()) loadNotifications();
    } catch (error) {
      if (contextIsCurrent()) {
        notificationFeedback("Не удалось отметить уведомление: " + error.message);
        button.disabled = false;
      }
    }
  };
  $("#notificationRefresh")?.addEventListener("click", loadNotifications);
  $("#notificationReadAll")?.addEventListener("click", async event => {
    const button = event.currentTarget, version = authContextVersion, userId = authSession?.user?.id;
    if (!userId) return;
    const contextIsCurrent = () => version === authContextVersion && authSession?.user?.id === userId;
    button.disabled = true;
    try {
      await apiRequest("/api/notifications/read-all", {method:"POST"});
      if (contextIsCurrent()) loadNotifications();
    } catch (error) {
      if (contextIsCurrent()) {
        notificationFeedback("Не удалось обновить уведомления: " + error.message);
        button.disabled = false;
      }
    }
  });

  const messagesFeedback = message => { const el = $("#messagesFeedback"); if (el) el.textContent = message; };
  const messageDisplayName = userId => {
    const profile = messageProfileCache.get(userId);
    return profile?.display_name || profile?.username || ("Пользователь · " + String(userId || "").slice(0, 8) + "…");
  };
  const loadMessageProfile = async userId => {
    if (!userId || messageProfileCache.has(userId)) return messageProfileCache.get(userId);
    if (messageProfilePending.has(userId)) return messageProfilePending.get(userId);
    const requestVersion=authContextVersion,requestOwnerId=authSession?.user?.id;
    const contextIsCurrent=()=>requestVersion===authContextVersion&&authSession?.user?.id===requestOwnerId;
    const pending = apiRequest("/api/community/profiles/" + encodeURIComponent(userId))
      .then(profile => { if(contextIsCurrent())messageProfileCache.set(userId, profile || {}); return profile; })
      .catch(() => { if(contextIsCurrent())messageProfileCache.set(userId, {}); return null; })
      .finally(() => { if(messageProfilePending.get(userId)===pending)messageProfilePending.delete(userId); });
    messageProfilePending.set(userId, pending);
    return pending;
  };
  const messagePartnerId = thread => thread.user_a_id === authSession?.user?.id ? thread.user_b_id : thread.user_a_id;
  const renderConversations = threads => {
    conversationsCache = Array.isArray(threads) ? threads : [];
    const list = $("#conversationList"); if (!list) return;
    const renderVersion = ++conversationRenderVersion;
    const contextVersion = authContextVersion;
    const userId = authSession?.user?.id;
    list.replaceChildren();
    if (!conversationsCache.length) { list.append(adminNode("div","admin-empty","Пока нет диалогов. Начните переписку с первого сообщения.")); return; }
    conversationsCache.forEach(thread => {
      const partnerId = messagePartnerId(thread);
      const button = adminNode("button","conversation-button");
      button.type = "button";
      button.setAttribute("aria-current",String(thread.id === activeMessageThreadId));
      button.append(adminNode("b","", messageDisplayName(partnerId)));
      button.append(adminNode("small","",thread.last_message_at ? "Последнее сообщение · "+formatAdminDate(thread.last_message_at) : "Диалог создан"));
      button.addEventListener("click",()=>openConversation(thread.id,partnerId));
      loadMessageProfile(partnerId).then(()=>{
        if(renderVersion!==conversationRenderVersion||contextVersion!==authContextVersion||authSession?.user?.id!==userId||!button.isConnected)return;
        const title=button.querySelector("b");
        if(title)title.textContent=messageDisplayName(partnerId);
        if(thread.id===activeMessageThreadId)$("#conversationTitle").textContent="Диалог с "+messageDisplayName(partnerId);
      });
      list.append(button);
    });
  };
  const loadConversations = async () => {
    const panel=$("#messagesPanel");
    if(!panel)return;
    if(!authSession?.user){panel.hidden=true;return;}
    panel.hidden=false;
    const version=authContextVersion,userId=authSession.user.id;
    const list=$("#conversationList");
    const requestVersion=list?(Number(list.dataset.requestVersion)||0)+1:1;
    if(list){list.dataset.requestVersion=String(requestVersion);list.replaceChildren(adminNode("div","admin-empty","Загружаем диалоги…"));}
    const contextIsCurrent=()=>version===authContextVersion&&authSession?.user?.id===userId&&(!list||Number(list.dataset.requestVersion)===requestVersion);
    loadBlockedUsers();
    try{
      const threads=await apiRequest("/api/conversations");
      if(!contextIsCurrent())return;
      renderConversations(Array.isArray(threads)?threads:[]);
      if(activeMessageThreadId && !(threads||[]).some(item=>item.id===activeMessageThreadId)){
        activeMessageThreadId=null;activeMessagePartnerId=null;
        $("#directMessageForm").hidden=true;
        $("#conversationTitle").textContent="Выберите диалог";
        $("#directMessageList").replaceChildren(adminNode("div","admin-empty","Выберите диалог из списка."));
      }
      messagesFeedback(threads.length ? "Диалоги загружены. Переписка доступна только её участникам." : "Создайте первый диалог.");
    }catch(error){
      if(!contextIsCurrent())return;
      messagesFeedback("Не удалось загрузить диалоги: "+error.message);
      if(list)list.replaceChildren(adminNode("div","admin-empty","Список диалогов временно недоступен."));
    }
  };
  const loadConversationMessages = async (threadId) => {
    const version=authContextVersion,userId=authSession?.user?.id,requestVersion=++conversationMessagesRequestVersion;
    if(!userId||!threadId)return;
    const contextIsCurrent=()=>version===authContextVersion&&authSession?.user?.id===userId&&activeMessageThreadId===threadId&&requestVersion===conversationMessagesRequestVersion;
    const list=$("#directMessageList");
    if(list)list.replaceChildren(adminNode("div","admin-empty","Загружаем сообщения…"));
    try{
      const messages=await apiRequest("/api/conversations/"+encodeURIComponent(threadId)+"/messages");
      if(!contextIsCurrent())return;
      list.replaceChildren();
      if(!messages.length)list.append(adminNode("div","admin-empty","Пока нет сообщений. Напишите первым."));
      messages.forEach(message=>{
        const own=message.sender_id===userId;
        const item=adminNode("article","direct-message"+(own?" is-own":""));
        item.append(adminNode("p","",message.body||""));
        item.append(adminNode("time","",formatAdminDate(message.created_at)+(message.edited_at?" · Изменено":"")+(message.read_at&&own?" · Прочитано":"")));
        if(own){
          const actions=adminNode("div","direct-message-actions");
          const edit=adminNode("button","message-action","Изменить");edit.type="button";
          edit.addEventListener("click",async()=>{
            const next=window.prompt("Изменить сообщение:",message.body||"");
            if(next===null||!next.trim()||next.trim()===message.body)return;
            const actionIsCurrent=()=>version===authContextVersion&&authSession?.user?.id===userId&&activeMessageThreadId===threadId;
            try{await apiRequest("/api/messages/"+encodeURIComponent(message.id),{method:"PATCH",body:JSON.stringify({body:next.trim()})});if(actionIsCurrent())loadConversationMessages(threadId);}
            catch(error){if(actionIsCurrent())messagesFeedback("Не удалось изменить сообщение: "+error.message);}
          });
          const remove=adminNode("button","message-action is-danger","Удалить у себя");remove.type="button";
          remove.addEventListener("click",async()=>{
            if(!window.confirm("Скрыть это сообщение только в вашей переписке? У собеседника оно останется."))return;
            const actionVersion=authContextVersion,actionUserId=userId,actionThreadId=threadId;
            const actionIsCurrent=()=>actionVersion===authContextVersion&&authSession?.user?.id===actionUserId&&activeMessageThreadId===actionThreadId;
            try{await apiRequest("/api/messages/"+encodeURIComponent(message.id),{method:"DELETE"});if(actionIsCurrent())loadConversationMessages(threadId);}
            catch(error){if(actionIsCurrent())messagesFeedback("Не удалось удалить сообщение: "+error.message);}
          });
          actions.append(edit,remove);item.append(actions);
        }
        list.append(item);
      });
      list.scrollTop=list.scrollHeight;
      await apiRequest("/api/conversations/"+encodeURIComponent(threadId)+"/read",{method:"POST"});
      if(contextIsCurrent())loadConversations();
    }catch(error){
      if(contextIsCurrent())messagesFeedback("Не удалось загрузить переписку: "+error.message);
    }
  };
  const openConversation = (threadId,partnerId) => {
    activeMessageThreadId=threadId;activeMessagePartnerId=partnerId;
    $("#conversationTitle").textContent="Диалог с "+messageDisplayName(partnerId);
    $("#directMessageForm").hidden=false;
    const blockButton=$("#blockConversationUser");if(blockButton){blockButton.hidden=false;blockButton.textContent="Заблокировать";blockButton.disabled=false;}
    renderConversations(conversationsCache);
    loadConversationMessages(threadId);
  };
  $("#blockConversationUser")?.addEventListener("click",async()=>{
    if(!activeMessagePartnerId||!authSession?.user)return;
    if(!window.confirm("Заблокировать пользователя? Он не сможет отправлять вам сообщения, и вы не сможете писать ему."))return;
    const button=$("#blockConversationUser"),version=authContextVersion,userId=authSession.user.id,partnerId=activeMessagePartnerId,threadId=activeMessageThreadId;
    const contextIsCurrent=()=>version===authContextVersion&&authSession?.user?.id===userId&&activeMessagePartnerId===partnerId&&activeMessageThreadId===threadId;
    button.disabled=true;
    try{
      await apiRequest("/api/blocks",{method:"POST",body:JSON.stringify({user_id:partnerId})});
      if(!contextIsCurrent())return;
      $("#directMessageForm").hidden=true;
      messagesFeedback("Пользователь заблокирован. Переписка сохранена, новые сообщения между вами недоступны.");
      button.textContent="Заблокирован";
      loadBlockedUsers();
    }catch(error){if(contextIsCurrent()){messagesFeedback("Не удалось заблокировать пользователя: "+error.message);button.disabled=false;}}
  });

  const blockedUsersStyle=document.createElement("style");
  blockedUsersStyle.textContent=".blocked-users-toolbar{display:flex;align-items:center;flex-wrap:wrap;gap:12px;margin:12px 0 16px;padding:12px;border:1px solid var(--border);border-radius:12px}.blocked-users-select-all{display:flex;align-items:center;gap:8px;cursor:pointer}.blocked-users-selected-count{color:var(--muted);font-size:13px}.blocked-user-item{display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding:12px 0;border-bottom:1px solid var(--border)}.blocked-user-item span{flex:1;min-width:130px}.blocked-user-item input[type=checkbox]{width:18px;height:18px;accent-color:#a98aff}";
  document.head.appendChild(blockedUsersStyle);
  const loadBlockedUsers = async () => {
    const list=$("#blockedUsersList"); if(!list||!authSession?.user)return;
    list.replaceChildren(adminNode("div","admin-empty","Загружаем список блокировок…"));
    const version=authContextVersion,userId=authSession.user.id,requestVersion=(Number(list.dataset.requestVersion)||0)+1;
    list.dataset.requestVersion=String(requestVersion);
    const contextIsCurrent=()=>version===authContextVersion&&authSession?.user?.id===userId&&Number(list.dataset.requestVersion)===requestVersion;
    try{
      const rows=await apiRequest("/api/blocks");
      if(!contextIsCurrent())return;
      list.replaceChildren();
      if(!Array.isArray(rows)||!rows.length){list.append(adminNode("div","admin-empty","Вы никого не заблокировали."));return;}
      const selectedIds=new Set();
      const toolbar=adminNode("div","blocked-users-toolbar");
      const selectAllLabel=adminNode("label","blocked-users-select-all");
      const selectAll=document.createElement("input");selectAll.type="checkbox";
      const selectAllText=adminNode("span","","Выбрать всех");
      selectAllLabel.append(selectAll,selectAllText);
      const selectedCount=adminNode("span","blocked-users-selected-count","Выбрано: 0");
      const bulkButton=adminNode("button","primary-button","Разблокировать выбранных");
      bulkButton.type="button";bulkButton.disabled=true;
      toolbar.append(selectAllLabel,selectedCount,bulkButton);list.append(toolbar);
      const updateSelection=()=>{
        selectedCount.textContent="Выбрано: "+selectedIds.size;
        bulkButton.disabled=selectedIds.size===0;
        selectAll.checked=selectedIds.size===rows.length;
        selectAll.indeterminate=selectedIds.size>0&&selectedIds.size<rows.length;
      };
      const unblockOne=async(row,item,button)=>{
        button.disabled=true;
        try{
          await apiRequest("/api/blocks",{method:"DELETE",body:JSON.stringify({user_id:row.blocked_id})});
          if(!contextIsCurrent())return false;
          item.remove();selectedIds.delete(row.blocked_id);
          if(activeMessagePartnerId===row.blocked_id){
            const blockButton=$("#blockConversationUser");
            if(blockButton){blockButton.textContent="Заблокировать";blockButton.disabled=false;}
            $("#directMessageForm").hidden=false;
          }
          return true;
        }catch(error){if(contextIsCurrent())button.disabled=false;throw error;}
      };
      const items=new Map();
      rows.forEach(row=>{
        const item=adminNode("div","blocked-user-item");
        const choice=document.createElement("input");choice.type="checkbox";choice.setAttribute("aria-label","Выбрать пользователя "+String(row.blocked_id||"").slice(0,8));
        const label=adminNode("span","",messageDisplayName(row.blocked_id));
        loadMessageProfile(row.blocked_id).then(()=>{if(contextIsCurrent()&&item.isConnected)label.textContent=messageDisplayName(row.blocked_id);});
        const button=adminNode("button","secondary-button","Разблокировать");button.type="button";
        choice.addEventListener("change",()=>{if(choice.checked)selectedIds.add(row.blocked_id);else selectedIds.delete(row.blocked_id);updateSelection();});
        button.addEventListener("click",async()=>{
          if(!window.confirm("Разблокировать этого пользователя? Возможность переписки будет восстановлена."))return;
          try{
            await unblockOne(row,item,button);
            if(!list.querySelector(".blocked-user-item")){list.replaceChildren(adminNode("div","admin-empty","Вы никого не заблокировали."));}
            else updateSelection();
            messagesFeedback("Пользователь разблокирован. Теперь вы снова можете обмениваться сообщениями.");
          }catch(error){messagesFeedback("Не удалось разблокировать пользователя: "+error.message);}
        });
        item.append(choice,label,button);list.append(item);items.set(row.blocked_id,{row,item,button});
      });
      selectAll.addEventListener("change",()=>{
        rows.forEach(row=>{const entry=items.get(row.blocked_id);if(!entry)return;entry.item.querySelector('input[type="checkbox"]').checked=selectAll.checked;if(selectAll.checked)selectedIds.add(row.blocked_id);else selectedIds.delete(row.blocked_id);});
        updateSelection();
      });
      bulkButton.addEventListener("click",async()=>{
        const targets=rows.filter(row=>selectedIds.has(row.blocked_id));
        if(!targets.length)return;
        if(!window.confirm("Разблокировать выбранных пользователей: "+targets.length+"?"))return;
        bulkButton.disabled=true;selectAll.disabled=true;
        let success=0;const failures=[];
        for(const row of targets){
          if(!contextIsCurrent())return;
          const entry=items.get(row.blocked_id);if(!entry)continue;
          try{await unblockOne(row,entry.item,entry.button);success++;}
          catch(error){failures.push(String(row.blocked_id).slice(0,8)+": "+error.message);}
        }
        if(!contextIsCurrent())return;
        if(!list.querySelector(".blocked-user-item"))list.replaceChildren(adminNode("div","admin-empty","Вы никого не заблокировали."));
        else{selectAll.disabled=false;updateSelection();}
        if(failures.length)messagesFeedback("Разблокировано: "+success+". Не удалось: "+failures.length+". "+failures.join("; "));
        else messagesFeedback("Успешно разблокировано пользователей: "+success+".");
      });
      updateSelection();
    }catch(error){if(contextIsCurrent())list.replaceChildren(adminNode("div","admin-empty","Не удалось загрузить блокировки: "+error.message));}
  };
  $("#messagesRefresh")?.addEventListener("click",()=>{loadConversations();loadBlockedUsers();if(activeMessageThreadId)loadConversationMessages(activeMessageThreadId);});
  $("#newConversationForm")?.addEventListener("submit",async event=>{
    event.preventDefault();
    if(!authSession?.user)return;
    const form=event.currentTarget,button=form.querySelector('button[type="submit"]');
    const recipient=$("#messageRecipientId").value.trim(),body=$("#messageFirstText").value.trim();
    if(!recipient||!body)return;
    const version=authContextVersion,userId=authSession.user.id;
    const contextIsCurrent=()=>version===authContextVersion&&authSession?.user?.id===userId;
    button.disabled=true;messagesFeedback("Открываем защищённый диалог…");
    try{
      const sent=await apiRequest("/api/conversations/"+encodeURIComponent(recipient)+"/messages",{method:"POST",body:JSON.stringify({body})});
      if(!contextIsCurrent())return;
      form.reset();activeMessageThreadId=sent.thread_id;activeMessagePartnerId=recipient;
      await loadMessageProfile(recipient);
      $("#conversationTitle").textContent="Диалог с "+messageDisplayName(recipient);
      $("#directMessageForm").hidden=false;
      await loadConversations();await loadConversationMessages(activeMessageThreadId);
      messagesFeedback("Первое сообщение отправлено.");
    }catch(error){if(contextIsCurrent())messagesFeedback("Не удалось начать диалог: "+error.message);}
    finally{if(contextIsCurrent())button.disabled=false;}
  });
  $("#directMessageForm")?.addEventListener("submit",async event=>{
    event.preventDefault();
    if(!authSession?.user||!activeMessagePartnerId)return;
    const form=event.currentTarget,button=form.querySelector('button[type="submit"]');
    const body=$("#directMessageText").value.trim();if(!body)return;
    const version=authContextVersion,userId=authSession.user.id,threadId=activeMessageThreadId,partnerId=activeMessagePartnerId;
    const contextIsCurrent=()=>version===authContextVersion&&authSession?.user?.id===userId&&activeMessageThreadId===threadId&&activeMessagePartnerId===partnerId;
    button.disabled=true;
    try{
      await apiRequest("/api/conversations/"+encodeURIComponent(partnerId)+"/messages",{method:"POST",body:JSON.stringify({body})});
      if(!contextIsCurrent())return;
      $("#directMessageText").value="";
      await loadConversationMessages(threadId);
    }catch(error){if(contextIsCurrent())messagesFeedback("Не удалось отправить сообщение: "+error.message);}
    finally{if(contextIsCurrent())button.disabled=false;}
  });

  const reportFeedback = message => { const el = $("#reportFeedback"); if (el) el.textContent = message; };
  $("#userReportForm")?.addEventListener("submit", async event => {
    event.preventDefault();
    if (!authSession?.user) { setAuthMode("login"); authGate.hidden = false; reportFeedback("Сначала войдите в аккаунт, чтобы отправить обращение."); return; }
    const form = event.currentTarget;
    const button = form.querySelector('button[type="submit"]');
    const version = authContextVersion, userId = authSession.user.id;
    const contextIsCurrent = () => version === authContextVersion && authSession?.user?.id === userId;
    const description = $("#reportDescription").value.trim();
    if (description.length < 10) { reportFeedback("Добавьте немного больше подробностей (не менее 10 символов)."); return; }
    const payload = {
      category: $("#reportCategory").value,
      description,
      reported_user_id: $("#reportUserId").value.trim() || null,
      content_reference: $("#reportReference").value.trim() || null
    };
    button.disabled = true;
    reportFeedback("Отправляем обращение защищённым соединением…");
    try {
      const result = await apiRequest("/api/reports", { method: "POST", body: JSON.stringify(payload) });
      if (!contextIsCurrent()) return;
      form.reset();
      reportFeedback("✓ Обращение принято. Номер: " + result.id + ". Статус: " + (result.status || "new") + ". Спасибо, что помогаете поддерживать безопасную среду.");
    } catch (error) {
      if (contextIsCurrent()) reportFeedback("Не удалось отправить обращение: " + error.message);
    } finally {
      if (contextIsCurrent()) button.disabled = false;
    }
  });

  const adminFeedback = message => { const el = $("#adminFeedback"); if (el) el.textContent = message; };
  const adminNode = (tag, className, value) => { const el = document.createElement(tag); if (className) el.className = className; if (value !== undefined) el.textContent = value; return el; };
  const formatAdminDate = value => { if (!value) return "Без срока"; const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString("ru-RU"); };
  let adminWorkspaceRequestVersion = 0;
  const loadAdminWorkspace = async () => {
    const reportsList = $("#adminReportsList"), suspensionsList = $("#adminSuspensionsList");
    if (!authSession?.user || !$("#adminPanel") || $("#adminPanel").hidden) return;
    const version = authContextVersion, userId = authSession.user.id, requestVersion = ++adminWorkspaceRequestVersion;
    const contextIsCurrent = () => version === authContextVersion && authSession?.user?.id === userId && requestVersion === adminWorkspaceRequestVersion;
    adminFeedback("Обновляем данные модерации…");
    if (reportsList) reportsList.replaceChildren(adminNode("div","admin-empty","Загружаем жалобы…"));
    if (suspensionsList) suspensionsList.replaceChildren(adminNode("div","admin-empty","Загружаем ограничения…"));
    try {
      const [reports, suspensions] = await Promise.all([
        apiRequest("/api/admin/reports"),
        apiRequest("/api/admin/suspensions")
      ]);
      if (!contextIsCurrent()) return;
      renderAdminReports(Array.isArray(reports) ? reports : []);
      renderAdminSuspensions(Array.isArray(suspensions) ? suspensions : []);
      adminFeedback("Данные обновлены. Действия модерации записываются в журнал.");
    } catch (error) {
      if (!contextIsCurrent()) return;
      adminFeedback("Не удалось загрузить данные: " + error.message);
      if (reportsList) reportsList.replaceChildren(adminNode("div","admin-empty","Список жалоб временно недоступен."));
      if (suspensionsList) suspensionsList.replaceChildren(adminNode("div","admin-empty","Список ограничений временно недоступен."));
    }
  };
  const renderAdminReports = reports => {
    const renderVersion=authContextVersion,renderUserId=authSession?.user?.id;
    const contextIsCurrent=()=>renderVersion===authContextVersion&&authSession?.user?.id===renderUserId;
    const list = $("#adminReportsList"); if (!list) return;
    $("#adminReportCount").textContent = String(reports.length);
    list.replaceChildren();
    if (!reports.length) { list.append(adminNode("div","admin-empty","Новых обращений нет.")); return; }
    reports.forEach(report => {
      const card = adminNode("article","admin-item");
      const head = adminNode("div","admin-item-head");
      head.append(adminNode("b","","Жалоба · " + (report.category || "Без категории")),adminNode("span","admin-status",report.status || "new"));
      card.append(head);
      card.append(adminNode("p","admin-item-meta","Создана: "+formatAdminDate(report.created_at)+" · Автор: "+(report.reporter_user_id || "не указан")));
      if (report.reported_user_id) card.append(adminNode("p","admin-item-meta","Указанный пользователь: "+report.reported_user_id));
      card.append(adminNode("p","admin-item-text",report.description || "Описание не указано."));
      if (report.content_reference) card.append(adminNode("p","admin-item-meta","Ссылка/идентификатор материала: "+report.content_reference));
      const note = document.createElement("textarea"); note.rows=2; note.maxLength=2000; note.placeholder="Заметка модератора (необязательно)"; note.value=report.moderator_note || ""; note.className="admin-note";
      const actions = adminNode("div","admin-item-actions");
      const status = document.createElement("select"); status.className="admin-status-select"; status.setAttribute("aria-label","Статус жалобы");
      [["reviewing","На рассмотрении"],["resolved","Решена"],["rejected","Отклонена"]].forEach(([value,label])=>{const option=document.createElement("option");option.value=value;option.textContent=label;status.append(option);});
      status.value=["reviewing","resolved","rejected"].includes(report.status)?report.status:"reviewing";
      const save=adminNode("button","secondary-button","Сохранить решение");save.type="button";
      save.addEventListener("click",async()=>{
        if(!contextIsCurrent())return;
        save.disabled=true;
        try { await apiRequest("/api/admin/reports/"+encodeURIComponent(report.id),{method:"PATCH",body:JSON.stringify({status:status.value,moderator_note:note.value.trim()||null})}); if(!contextIsCurrent())return;adminFeedback("Решение по жалобе сохранено."); await loadAdminWorkspace(); }
        catch(error){if(contextIsCurrent()){adminFeedback("Не удалось сохранить решение: "+error.message);save.disabled=false;}}
        finally{if(contextIsCurrent())save.disabled=false;}
      });
      actions.append(status,save); card.append(note,actions); list.append(card);
    });
  };
  const renderAdminSuspensions = suspensions => {
    const renderVersion=authContextVersion,renderUserId=authSession?.user?.id;
    const contextIsCurrent=()=>renderVersion===authContextVersion&&authSession?.user?.id===renderUserId;
    const list=$("#adminSuspensionsList");if(!list)return;
    $("#adminSuspensionCount").textContent=String(suspensions.length);
    list.replaceChildren();
    if(!suspensions.length){list.append(adminNode("div","admin-empty","Ограничений пока нет."));return;}
    suspensions.forEach(item=>{
      const card=adminNode("article","admin-item");
      const head=adminNode("div","admin-item-head");
      const scopeLabel={platform:"Вся платформа",assistant:"AI Companion",community:"Сообщество"}[item.scope]||item.scope;
      head.append(adminNode("b","",scopeLabel),adminNode("span","admin-status",item.revoked_at?"Отменено":item.expires_at && new Date(item.expires_at)<=new Date()?"Истекло":"Активно"));
      card.append(head,adminNode("p","admin-item-meta","Пользователь: "+item.user_id),adminNode("p","admin-item-text",item.reason||"Причина не указана"),adminNode("p","admin-item-meta","Создано: "+formatAdminDate(item.created_at)+" · До: "+formatAdminDate(item.expires_at)));
      if(!item.revoked_at && (!item.expires_at || new Date(item.expires_at)>new Date())){
        const revoke=adminNode("button","secondary-button","Отменить ограничение");revoke.type="button";
        revoke.addEventListener("click",async()=>{if(!contextIsCurrent()||!confirm("Отменить это ограничение доступа?"))return;revoke.disabled=true;try{await apiRequest("/api/admin/suspensions/revoke",{method:"POST",body:JSON.stringify({suspension_id:item.id})});if(!contextIsCurrent())return;adminFeedback("Ограничение отменено.");await loadAdminWorkspace();}catch(error){if(contextIsCurrent()){adminFeedback("Не удалось отменить: "+error.message);revoke.disabled=false;}}finally{if(contextIsCurrent())revoke.disabled=false;}});
        card.append(revoke);
      }
      list.append(card);
    });
  };
  $("#adminRefresh")?.addEventListener("click",loadAdminWorkspace);
  $("#adminSuspensionForm")?.addEventListener("submit",async event=>{
    event.preventDefault();
    const button=$("#adminSuspensionForm button[type=submit]");
    if(!authSession?.user)return;
    const requestVersion=authContextVersion,adminUserId=authSession.user.id;
    const contextIsCurrent=()=>requestVersion===authContextVersion&&authSession?.user?.id===adminUserId;
    const userId=$("#suspensionUserId").value.trim(), reason=$("#suspensionReason").value.trim(), expiry=$("#suspensionExpiry").value;
    if(!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(userId)){adminFeedback("Проверьте UUID пользователя — нужен полный идентификатор Supabase Auth.");return;}
    if(authSession?.user?.id===userId){adminFeedback("Нельзя ограничить собственный аккаунт.");return;}
    const payload={user_id:userId,reason,scope:$("#suspensionScope").value,expires_at:expiry?new Date(expiry).toISOString():null};
    button.disabled=true;
    try{await apiRequest("/api/admin/suspensions",{method:"POST",body:JSON.stringify(payload)});if(!contextIsCurrent())return;$("#adminSuspensionForm").reset();adminFeedback("Ограничение создано и записано в журнал.");await loadAdminWorkspace();}
    catch(error){if(contextIsCurrent())adminFeedback("Не удалось создать ограничение: "+error.message);}
    finally{if(contextIsCurrent())button.disabled=false;}
  });
  if (authSession?.user) setTimeout(loadAccountRole, 0);
  const labels = {guestspace:"Гостевое пространство",account:"Личный кабинет",rules:"Правила и безопасность",home:"Главная",create:"Создать видео",movie:"Миникиностудия",editor:"Видеоредактор",prompts:"Prompt Studio",library:"Медиатека",voice:"Голос и музыка",scenes:"Сценарий и сцены",assistant:"AI Companion",guide:"Путеводитель",about:"О студии",settings:"Настройки"};

  function navigate(view) {
    if (!labels[view]) return;
    $$(".view").forEach(el => el.classList.toggle("active", el.id === "view-" + view));
    $$(".nav-item[data-view]").forEach(el => el.classList.toggle("active", el.dataset.view === view));
    $("#crumbCurrent").textContent = labels[view];
    $("#sidebar").classList.remove("open");
    window.location.hash = view === "home" ? "" : view;
    if(view==="guestspace" && typeof renderGuestSpace==="function")renderGuestSpace();
    window.scrollTo({top:0,behavior:"smooth"});
  }

  $$(".nav-item[data-view]").forEach(btn => btn.addEventListener("click", () => navigate(btn.dataset.view)));
  $$("[data-go]").forEach(btn => btn.addEventListener("click", () => navigate(btn.dataset.go)));
  $(".profile").addEventListener("click", () => navigate("account"));
  $("#topAvatar")?.addEventListener("click", () => navigate("account"));
  $("#accountLogin").addEventListener("click", () => setAuthMode("login"));
  $("#accountLogout").addEventListener("click", () => authLogoutButton.click());
  $("#mobileMenu").addEventListener("click", () => $("#sidebar").classList.toggle("open"));
  document.addEventListener("click", event => {
    if (window.innerWidth <= 720 && !event.target.closest("#sidebar") && !event.target.closest("#mobileMenu")) $("#sidebar").classList.remove("open");
  });

  const initial = location.hash.replace("#","");
  if (labels[initial]) navigate(initial);

  $("#themeToggle").addEventListener("click", () => {
    document.body.classList.toggle("light");
    const light = document.body.classList.contains("light");
    localStorage.setItem("pwa-studio-theme", light ? "light" : "dark");
    $("#themeToggle").textContent = light ? "☾" : "☼";
  });
  if (localStorage.getItem("pwa-studio-theme") === "light") {
    document.body.classList.add("light");
    $("#themeToggle").textContent = "☾";
  }
  const videoTitlesKey = "pwa-studio-video-show-titles";
  const videoTitleControls = [$("#showVideoTitles"), $("#editorShowVideoTitles")].filter(Boolean);
  const savedVideoTitles = localStorage.getItem(videoTitlesKey);
  videoTitleControls.forEach(control => {
    control.checked = savedVideoTitles === null ? true : savedVideoTitles === "true";
    control.addEventListener("change", () => {
      localStorage.setItem(videoTitlesKey, String(control.checked));
      videoTitleControls.forEach(other => { if (other !== control) other.checked = control.checked; });
    });
  });

  $("#quickCreate").addEventListener("submit", event => {
    event.preventDefault();
    $("#topic").value = $("#quickTopic").value.trim();
    navigate("create");
  });

  $("#prepareIdea").addEventListener("click", () => {
    if (!authSession?.user) { setAuthMode("signup"); setAuthMessage("Войдите, чтобы создавать и сохранять материалы."); return; }
    const topic = $("#topic").value.trim();
    $("#createFeedback").textContent = topic
      ? "Идея сохранена в форме. Следующий этап — подключение AI-сценариста и генерации сцен."
      : "Сначала напишите тему или идею будущего видео.";
  });

  $("#buildPrompt").addEventListener("click", async () => {
    if (!authSession?.user) { setAuthMode("signup"); setAuthMessage("Войдите или зарегистрируйтесь, чтобы пользоваться AI-инструментами."); return; }
    const idea = $("#promptIdea").value.trim();
    if (!idea) {
      $("#promptFeedback").textContent = "Добавьте описание вашей задумки, чтобы сформировать промт.";
      return;
    }
    const button = $("#buildPrompt");
    const requestUserId = authSession.user.id;
    const requestVersion = authContextVersion;
    const contextIsCurrent = () => requestVersion === authContextVersion && authSession?.user?.id === requestUserId;
    button.disabled = true;
    button.textContent = "✦ AI готовит промт…";
    $("#promptFeedback").textContent = "Отправляем запрос на backend. Ключ AI-провайдера остаётся на сервере.";
    try {
      const result = await apiRequest("/api/prompts", {
        method: "POST",
        body: JSON.stringify({ idea, purpose: $("#promptType").value, language: $("#promptLanguage").value, style: "Cinematic, coherent, detailed" })
      });
      if (!contextIsCurrent()) return;
      $("#promptOutput").textContent = result.prompt;
      $("#promptFeedback").textContent = "Готово: ответ получен от " + result.provider + " · " + result.model + ".";
    } catch (error) {
      if (contextIsCurrent()) $("#promptFeedback").textContent = error.message;
    } finally {
      if (contextIsCurrent()) {
        button.disabled = false;
        button.textContent = "✦ Сформировать промт";
      }
    }
  });

  $("#copyPrompt").addEventListener("click", async () => {
    const text = $("#promptOutput").textContent;
    try {
      await navigator.clipboard.writeText(text);
      $("#copyPrompt").textContent = "Скопировано ✓";
      setTimeout(() => $("#copyPrompt").innerHTML = 'Скопировать промт <span>⧉</span>', 1800);
    } catch {
      $("#promptFeedback").textContent = "Не удалось автоматически скопировать. Выделите текст промта и скопируйте вручную.";
    }
  });

  $("[data-assist]").forEach(btn => btn.addEventListener("click", () => {
    const prompt = btn.dataset.assist || "";
    $("#assistantInput").value = prompt;
    setKattyAssistantMode(kattyModeForMessage(prompt));
    setKattyAssistantExpression(kattyContextState(prompt));
    $("#assistantInput").focus();
  }));
  // AI Companion cloud history. Supabase RLS restricts every row to its owner.
  const assistantHistoryList = $("#assistantHistoryList");
  const assistantMessages = $("#assistantMessages");
  const assistantStatus = $("#assistantHistoryStatus");
  const setAssistantStatus = message => { if (assistantStatus) assistantStatus.textContent = message || ""; };
  const KATTY_ASSISTANT_EXPRESSIONS = {
    neutral: ["neutral-warm", "Катти — спокойная доброжелательность"],
    thinking: ["thinking", "Катти размышляет"],
    joy: ["joy", "Катти рада помочь"],
    empathetic: ["empathetic", "Катти внимательно слушает"]
  };
  const setKattyAssistantExpression = state => {
    const image = $("#kattyCompanionExpression");
    const [id, label] = KATTY_ASSISTANT_EXPRESSIONS[state] || KATTY_ASSISTANT_EXPRESSIONS.neutral;
    if (image) { image.src = "assets/characters/katty/expressions/" + id + ".svg"; image.alt = label; }
  };
  const kattySupportSignal = message => /(груст|тоск|страш|тревож|устал|плохо|боль|одинок|пережива|расстро|сложно)/i.test(String(message || ""));
  const kattyContextState = message => {
    const value = String(message || "");
    if (kattySupportSignal(value)) return "empathetic";
    if (/(объясни|научи|обуч|урок|как работает|разберём|изучи|изучить)/i.test(value)) return "curious";
    if (/(сценар|рассказ|истори|песн|стих|иде|придум|творч|фантаз)/i.test(value)) return "focused";
    if (/(поздрав|спасибо|получилось|готово|ура|здорово)/i.test(value)) return "joy";
    return "thinking";
  };
  const KATTY_ASSISTANT_MODES = {
    companion: { label: "Собеседница", hint: "Поддерживает диалог и помогает сформулировать мысли." },
    teacher: { label: "Учительница", hint: "Объясняет по шагам и приводит примеры." },
    creator: { label: "Творческий партнёр", hint: "Помогает развивать сюжеты, образы и идеи." },
    guide: { label: "Помощница", hint: "Помогает сориентироваться в инструментах PWA Studio." }
  };
  const kattyModeForMessage = message => {
    const value = String(message || "");
    if (/(объясни|научи|обуч|урок|как работает|разберём|изучи|изучить)/i.test(value)) return "teacher";
    if (/(сценар|рассказ|истори|песн|стих|иде|придум|творч|фантаз)/i.test(value)) return "creator";
    if (/(где найти|как открыть|как пользоваться|настройк|инструмент|в студии)/i.test(value)) return "guide";
    return "companion";
  };
  const setKattyAssistantMode = mode => {
    const image = $("#kattyCompanionExpression");
    const badge = $("#kattyAssistantModeLabel");
    const selected = KATTY_ASSISTANT_MODES[mode] || KATTY_ASSISTANT_MODES.companion;
    if (image) { image.dataset.assistantMode = mode; image.title = selected.label + ". " + selected.hint; }
    if (badge) badge.textContent = "Режим: " + selected.label;
  };
  const kattyResponseState = (prompt, reply) => {
    if (kattySupportSignal(prompt)) return "empathetic";
    if (/(вот план|шаг первый|давайте разберём|объяснение|пример)/i.test(reply)) return "curious";
    if (/(сценар|персонаж|куплет|припев|рассказ|концепци)/i.test(reply)) return "focused";
    return "joy";
  };

  const copyAssistantText = async (content, button) => {
    try {
      if (navigator.clipboard?.writeText && window.isSecureContext) {
        await navigator.clipboard.writeText(content);
      } else {
        const area = document.createElement("textarea");
        area.value = content; area.setAttribute("readonly", "");
        area.style.position = "fixed"; area.style.opacity = "0";
        document.body.appendChild(area); area.select();
        const copied = document.execCommand("copy"); area.remove();
        if (!copied) throw new Error("copy unavailable");
      }
      const previous = button.textContent;
      button.textContent = "Скопировано ✓";
      setTimeout(() => { button.textContent = previous; }, 1800);
    } catch {
      setAssistantStatus("Не удалось скопировать автоматически. Выделите текст ответа и скопируйте вручную.");
    }
  };
  const renderAssistantMessage = (role, content) => {
    const bubble = document.createElement("div");
    bubble.className = "helper-text assistant-message " + (role === "user" ? "user-message" : "ai-message");
    const text = document.createElement("div");
    text.className = "assistant-message-content";
    text.textContent = (role === "user" ? "Вы: " : "Studio AI: ") + content;
    bubble.appendChild(text);
    if (role !== "user") {
      const copy = document.createElement("button");
      copy.type = "button"; copy.className = "secondary-button assistant-copy-button";
      copy.textContent = "⧉ Копировать";
      copy.addEventListener("click", () => copyAssistantText(content, copy));
      bubble.appendChild(copy);
    }
    assistantMessages.appendChild(bubble);
    const welcome = document.querySelector(".assistant-welcome");
    if (welcome) welcome.hidden = true;
    const suggestions = document.querySelector(".assistant-panel .suggestion-row");
    if (suggestions) suggestions.hidden = true;
  };
  const clearAssistantMessages = (options = {}) => {
    if (!options.preserveKattyState) {
      setKattyAssistantMode("companion");
      setKattyAssistantExpression("neutral");
    }
    if (assistantMessages) assistantMessages.replaceChildren();
    const welcome = document.querySelector(".assistant-welcome");
    if (welcome) welcome.hidden = false;
    const suggestions = document.querySelector(".assistant-panel .suggestion-row");
    if (suggestions) suggestions.hidden = false;
  };
  const loadAssistantMessages = async conversationId => {
    const loadVersion = ++assistantConversationLoadVersion;
    const intentVersion = assistantConversationIntentVersion;
    setKattyAssistantMode("companion");
    setKattyAssistantExpression("neutral");
    if (!supabaseClient || !authSession?.user || !conversationId) return;
    const requestUserId = authSession.user.id;
    const requestVersion = authContextVersion;
    const { data, error } = await supabaseClient.from("assistant_messages")
      .select("id,role,content,created_at").eq("conversation_id", conversationId)
      .eq("user_id", requestUserId).order("created_at", { ascending: true });
    if (error) throw error;
    if (loadVersion !== assistantConversationLoadVersion ||
        intentVersion !== assistantConversationIntentVersion ||
        authSession?.user?.id !== requestUserId || authContextVersion !== requestVersion) return;
    clearAssistantMessages({ preserveKattyState: true });
    (data || []).forEach(message => renderAssistantMessage(message.role, message.content));
    activeAssistantConversationId = conversationId;
  };
  const renderAssistantHistory = async () => {
    if (!assistantHistoryList) return;
    if (!authSession?.user || !supabaseClient) {
      assistantHistoryList.replaceChildren();
      setAssistantStatus("Войдите в аккаунт, чтобы сохранять историю диалогов.");
      clearAssistantMessages(); activeAssistantConversationId = null; return;
    }
    const historyLoadVersion = ++assistantHistoryLoadVersion;
    assistantHistoryBusy = true; setAssistantStatus("Загружаем ваши диалоги…");
    const requestUserId = authSession.user.id;
    const requestVersion = authContextVersion;
    const historyContextIsCurrent = () => historyLoadVersion === assistantHistoryLoadVersion &&
      authSession?.user?.id === requestUserId && authContextVersion === requestVersion;
    try {
      const { data, error } = await supabaseClient.from("assistant_conversations")
        .select("id,title,updated_at").eq("user_id", requestUserId)
        .order("updated_at", { ascending: false });
      if (error) throw error;
      if (!historyContextIsCurrent()) return;
      assistantHistoryList.replaceChildren();
      (data || []).forEach(conversation => {
        const row = document.createElement("div"); row.className = "assistant-history-row";
        const open = document.createElement("button"); open.type = "button";
        open.className = "assistant-history-open"; open.textContent = conversation.title || "Новый диалог";
        open.title = open.textContent; open.setAttribute("aria-current", conversation.id === activeAssistantConversationId ? "true" : "false");
        open.addEventListener("click", async () => {
          if (!historyContextIsCurrent()) return;
          assistantConversationIntentVersion += 1;
          try {
            await loadAssistantMessages(conversation.id);
            if (!historyContextIsCurrent() || activeAssistantConversationId !== conversation.id) return;
            renderAssistantHistory();
            setAssistantStatus("");
          } catch (error) {
            if (historyContextIsCurrent()) setAssistantStatus("Не удалось открыть диалог: " + error.message);
          }
        });
        const rename = document.createElement("button"); rename.type = "button";
        rename.className = "assistant-history-rename"; rename.textContent = "✎";
        rename.title = "Переименовать диалог"; rename.setAttribute("aria-label", "Переименовать диалог");
        rename.addEventListener("click", async () => {
          if (!historyContextIsCurrent()) return;
          const title = prompt("Название диалога:", conversation.title || "Новый диалог");
          if (title === null || !historyContextIsCurrent()) return;
          const cleanTitle = title.trim().slice(0, 100); if (!cleanTitle) return;
          try {
            const { error: updateError } = await supabaseClient.from("assistant_conversations")
              .update({ title: cleanTitle }).eq("id", conversation.id).eq("user_id", requestUserId);
            if (!historyContextIsCurrent()) return;
            if (updateError) setAssistantStatus("Не удалось переименовать: " + updateError.message);
            else { setAssistantStatus("Название сохранено."); renderAssistantHistory(); }
          } catch (error) {
            if (historyContextIsCurrent()) setAssistantStatus("Не удалось переименовать: " + error.message);
          }
        });
        row.append(open, rename); assistantHistoryList.appendChild(row);
      });
      if (!activeAssistantConversationId && data?.length) {
        await loadAssistantMessages(data[0].id);
        if (!historyContextIsCurrent()) return;
      }
      if (!historyContextIsCurrent()) return;
      setAssistantStatus((data || []).length ? "Диалоги сохраняются в вашем аккаунте." : "Пока нет сохранённых диалогов. Начните новый разговор.");
    } catch (error) {
      if (historyContextIsCurrent()) setAssistantStatus("История пока недоступна. Проверьте, применена ли миграция Supabase. " + error.message);
    } finally {
      if (historyLoadVersion === assistantHistoryLoadVersion) assistantHistoryBusy = false;
    }
  };
  const startAssistantConversation = async () => {
    const intentVersion = ++assistantConversationIntentVersion;
    setKattyAssistantMode("companion");
    setKattyAssistantExpression("neutral");
    if (!authSession?.user || !supabaseClient) throw new Error("Сначала войдите в аккаунт.");
    const requestUserId = authSession.user.id;
    const requestVersion = authContextVersion;
    const { data, error } = await supabaseClient.from("assistant_conversations")
      .insert({ user_id: requestUserId, title: "Новый диалог" }).select("id").single();
    if (error) throw error;
    if (authSession?.user?.id !== requestUserId || authContextVersion !== requestVersion ||
        intentVersion !== assistantConversationIntentVersion) return null;
    activeAssistantConversationId = data.id; clearAssistantMessages({ preserveKattyState: true });
    await renderAssistantHistory();
    // History rendering is asynchronous: a newer account or conversation intent wins.
    if (authSession?.user?.id !== requestUserId || authContextVersion !== requestVersion ||
        intentVersion !== assistantConversationIntentVersion ||
        activeAssistantConversationId !== data.id) return null;
    setAssistantStatus("Создан новый диалог. Предыдущие разговоры сохранены.");
    return data.id;
  };
  $("#assistantNewChat")?.addEventListener("click", async () => {
    const requestUserId = authSession?.user?.id || null;
    const requestVersion = authContextVersion;
    const contextIsCurrent = () => (authSession?.user?.id || null) === requestUserId && authContextVersion === requestVersion;
    try {
      const conversationId = await startAssistantConversation();
      if (conversationId && contextIsCurrent()) $("#assistantInput").focus();
    } catch (error) {
      if (contextIsCurrent()) setAssistantStatus("Не удалось создать диалог: " + error.message);
    }
  });
  $("#assistantForm").addEventListener("submit", async event => {
    event.preventDefault();
    const input = $("#assistantInput"); const value = input.value.trim(); if (!value) return;
    if (!authSession?.user) { setAuthMode("signup"); setAuthMessage("Войдите или зарегистрируйтесь, чтобы общаться с AI Companion."); return; }
    setKattyAssistantMode(kattyModeForMessage(value));
    setKattyAssistantExpression(kattyContextState(value));
    const button = $("#assistantForm button"); button.disabled = true; input.disabled = true; input.value = "";
    const requestUserId = authSession.user.id;
    const requestVersion = authContextVersion;
    const contextIsCurrent = () => authSession?.user?.id === requestUserId && authContextVersion === requestVersion;
    let requestConversationId = null;
    try {
      if (!activeAssistantConversationId) {
        requestConversationId = await startAssistantConversation();
        if (!requestConversationId || !contextIsCurrent() ||
            activeAssistantConversationId !== requestConversationId) return;
      } else {
        requestConversationId = activeAssistantConversationId;
      }
      if (!contextIsCurrent()) return;
      const conversationId = requestConversationId;
      const conversationIsCurrent = () => contextIsCurrent() && activeAssistantConversationId === conversationId;
      const { data: previousMessages, error: historyError } = await supabaseClient.from("assistant_messages")
        .select("role,content").eq("conversation_id", conversationId)
        .eq("user_id", requestUserId).order("created_at", { ascending: false }).limit(20);
      if (historyError) throw historyError;
      if (!contextIsCurrent()) return;
      const chatHistory = (previousMessages || []).reverse()
        .filter(message => ["user", "assistant"].includes(message.role) && typeof message.content === "string")
        .map(message => ({ role: message.role, content: message.content.slice(0, 12000) }));
      const { error: userSaveError } = await supabaseClient.from("assistant_messages")
        .insert({ conversation_id: conversationId, user_id: requestUserId, role: "user", content: value });
      if (userSaveError) throw userSaveError;
      if (!conversationIsCurrent()) return;
      renderAssistantMessage("user", value);
      const { data: titleRow } = await supabaseClient.from("assistant_conversations")
        .select("title").eq("id", conversationId).eq("user_id", requestUserId).single();
      if (!contextIsCurrent()) return;
      if (titleRow?.title === "Новый диалог") {
        await supabaseClient.from("assistant_conversations")
          .update({ title: value.slice(0, 72) }).eq("id", conversationId).eq("user_id", requestUserId);
      }
      if (!contextIsCurrent()) return;
      const result = await apiRequest("/api/chat", { method: "POST", body: JSON.stringify({ message: value, history: chatHistory }) });
      if (!contextIsCurrent()) return;
      const { error: assistantSaveError } = await supabaseClient.from("assistant_messages")
        .insert({ conversation_id: conversationId, user_id: requestUserId, role: "assistant", content: result.reply });
      if (assistantSaveError) throw assistantSaveError;
      if (!contextIsCurrent()) return;
      if (conversationIsCurrent()) {
        renderAssistantMessage("assistant", result.reply);
        setKattyAssistantExpression(kattyResponseState(value, result.reply));
        await renderAssistantHistory();
      }
    } catch (error) {
      if (contextIsCurrent() && (!requestConversationId || activeAssistantConversationId === requestConversationId))
        { setKattyAssistantExpression("neutral"); setAssistantStatus("Сообщение не удалось полностью обработать: " + error.message); }
    } finally {
      // A stale request must not unlock or steal focus from a newer account's UI.
      if (contextIsCurrent()) {
        button.disabled = false; input.disabled = false;
        input.focus();
      }
    }
  });
  setTimeout(() => renderAssistantHistory(), 0);


  // Mini Movie Studio: resilient local drafts with per-project editing and staged workflow.
  const movieStorageKey = () => "pwa-studio-movie-projects:" + (authSession?.user?.id || "guest");
  const guestArchiveKey = () => "pwa-studio-movie-archive:guest";
  const readGuestArchive = () => { try { const value=JSON.parse(localStorage.getItem(guestArchiveKey())||"[]"); return Array.isArray(value)?value.filter(item=>item&&typeof item==="object"&&item.id):[]; } catch { return []; } };
  const writeGuestArchive = items => { try { localStorage.setItem(guestArchiveKey(),JSON.stringify(items)); return true; } catch(error) { console.error("Guest archive write failed:",error); return false; } };
  let activeMovieId = null;
  let editingMovieId = null;
  const movieStages = [
    {key:"story",title:"Сценарий и раскадровка",fields:[["story","Сценарий","Напишите историю, действия и диалоги по сценам."],["storyboard","Раскадровка","Опишите кадры, планы камеры, движение и переходы."]]},
    {key:"characters",title:"Персонажи и аватары",fields:[["characters","Персонажи","Опишите героев: внешность, одежду, характер и особенности образа."]]},
    {key:"voices",title:"Голоса и озвучка",fields:[["voices","Голоса и звук","Назначьте голос каждому персонажу, укажите язык, манеру речи, реплики, музыку и звуковые эффекты."]]},
    {key:"edit",title:"Монтаж и экспорт",fields:[["edit","План монтажа","Опишите порядок сцен, длительность, переходы, музыку, титры и параметры будущего экспорта. Реальный видеорендер пока не подключён."]]}
  ];
  // Cloud persistence for movie projects. Supabase RLS scopes every query to the signed-in owner.
  const movieCloudState = { syncing: false, pending: false, loadingUser: null, timer: null };
  const movieDeletedKey = () => "pwa-studio-movie-deleted:" + (authSession?.user?.id || "guest");
  const readMovieTombstones = () => {
    try { const value = JSON.parse(localStorage.getItem(movieDeletedKey()) || "[]"); return Array.isArray(value) ? value.filter(isUuid) : []; }
    catch { return []; }
  };
  const writeMovieTombstones = ids => {
    try { localStorage.setItem(movieDeletedKey(), JSON.stringify([...new Set(ids.filter(isUuid))])); return true; }
    catch (error) { console.error("Movie deletion queue failed:", error); return false; }
  };
  const isUuid = value => /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(String(value || ""));
  const movieToCloudRow = (project, ownerId = authSession?.user?.id) => {
    if (!ownerId) throw new Error("Облачное сохранение недоступно гостю.");
    if (!isUuid(project.id)) project.id = movieId();
    const snapshot = { ...project, cloudSchemaVersion: 1 };
    return {
      id: project.id,
      owner_id: ownerId,
      title: project.name || "Без названия",
      description: project.idea || "",
      project_type: "movie",
      status: (project.completedSteps || []).length === 4 ? "ready" : "draft",
      settings: snapshot,
      created_at: project.createdAt || new Date().toISOString(),
      updated_at: project.updatedAt || new Date().toISOString()
    };
  };
  const movieFromCloudRow = row => {
    const saved = row.settings && typeof row.settings === "object" ? row.settings : {};
    return {
      ...saved,
      id: row.id,
      name: row.title || saved.name || "Без названия",
      idea: row.description ?? saved.idea ?? "",
      // Legacy films stored the full screenplay in `idea`; restore it into the Story stage.
      story: saved.story || saved.idea || row.description || "",
      createdAt: saved.createdAt || row.created_at,
      updatedAt: row.updated_at || saved.updatedAt || row.created_at,
      completedSteps: Array.isArray(saved.completedSteps) ? saved.completedSteps : [],
      versions: Array.isArray(saved.versions) ? saved.versions : []
    };
  };
  const scheduleMovieCloudSync = () => {
    const userId = authSession?.user?.id, requestVersion = authContextVersion;
    if (!userId || !supabaseClient) return;
    const contextIsCurrent = () => requestVersion === authContextVersion && authSession?.user?.id === userId;
    clearTimeout(movieCloudState.timer);
    movieCloudState.timer = setTimeout(async () => {
      // Never let a queued sync from one account run after switching to guest or another user.
      if (!contextIsCurrent()) return;
      if (movieCloudState.syncing) { movieCloudState.pending = true; return; }
      movieCloudState.syncing = true;
      try {
        const deletedIds = readMovieTombstones();
        if (deletedIds.length) {
          const { error: deleteError } = await supabaseClient.from("projects").delete()
            .in("id", deletedIds).eq("owner_id", authSession.user.id).eq("project_type", "movie");
          if (deleteError) throw deleteError;
          if (!contextIsCurrent()) return;
          writeMovieTombstones(readMovieTombstones().filter(id => !deletedIds.includes(id)));
        }
        if (!contextIsCurrent()) return;
        const localProjects = movieRead().filter(project => !deletedIds.includes(project.id));
        const rows = localProjects.map(project => movieToCloudRow(project, userId));
        // Persist any UUID normalization before sending rows to Supabase.
        if (!contextIsCurrent()) return;
        localStorage.setItem("pwa-studio-movie-projects:" + userId, JSON.stringify(localProjects));
        if (!contextIsCurrent()) return;
        if (rows.length) {
          const { error } = await supabaseClient.from("projects").upsert(rows, { onConflict: "id" });
          if (error) throw error;
          if (!contextIsCurrent()) return;
        }
        if (!contextIsCurrent()) return;
        const feedback = $("#movieFeedback");
        if (feedback) feedback.textContent = deletedIds.length
          ? "✓ Фильмы и удаления синхронизированы с облаком Supabase."
          : "✓ Изменения сохранены в облаке Supabase.";
      } catch (error) {
        console.error("Movie cloud sync failed:", error);
        if (contextIsCurrent()) {
          const feedback = $("#movieFeedback");
          if (feedback) feedback.textContent = "Черновик сохранён на этом устройстве, но облачная синхронизация не удалась. Проверьте соединение и повторите попытку.";
        }
      } finally {
        movieCloudState.syncing = false;
        if (movieCloudState.pending) {
          movieCloudState.pending = false;
          scheduleMovieCloudSync();
        }
      }
    }, 350);
  };
  const loadMovieProjectsFromCloud = async () => {
    const userId = authSession?.user?.id;
    if (!userId || !supabaseClient || movieCloudState.loadingUser === userId) return;
    const version = authContextVersion;
    const contextIsCurrent = () => version === authContextVersion && authSession?.user?.id === userId;
    movieCloudState.loadingUser = userId;
    try {
      const { data, error } = await supabaseClient
        .from("projects")
        .select("id, owner_id, title, description, project_type, status, settings, created_at, updated_at")
        .eq("owner_id", userId)
        .eq("project_type", "movie")
        .order("updated_at", { ascending: false });
      if (error) throw error;
      if (!contextIsCurrent()) return;
      const deletedIds = readMovieTombstones();
      if (deletedIds.length) {
        const { error: deleteError } = await supabaseClient.from("projects").delete()
          .in("id", deletedIds).eq("owner_id", userId).eq("project_type", "movie");
        if (deleteError) throw deleteError;
        if (!contextIsCurrent()) return;
        writeMovieTombstones([]);
      }
      const deletedSet = new Set(deletedIds);
      const local = movieRead().filter(project => !deletedSet.has(project.id));
      const merged = new Map(local.map(project => [project.id, project]));
      (data || []).filter(row => !deletedSet.has(row.id)).forEach(row => {
        const cloudProject = movieFromCloudRow(row);
        const localProject = merged.get(cloudProject.id);
        if (!localProject || new Date(cloudProject.updatedAt || 0) >= new Date(localProject.updatedAt || 0)) {
          merged.set(cloudProject.id, cloudProject);
        }
      });
      const projects = [...merged.values()].sort((a, b) => new Date(b.updatedAt || b.createdAt || 0) - new Date(a.updatedAt || a.createdAt || 0));
      if (contextIsCurrent() && movieWrite(projects)) {
        renderMovieProjects();
        scheduleMovieCloudSync();
        const feedback = $("#movieFeedback");
        if (feedback) feedback.textContent = "✓ Фильмы загружены из облака. Изменения синхронизируются автоматически.";
      }
    } catch (error) {
      console.error("Movie cloud load failed:", error);
      const feedback = $("#movieFeedback");
      if (contextIsCurrent() && feedback) feedback.textContent = "Не удалось загрузить фильмы из облака. Локальные черновики сохранены на устройстве.";
    } finally {
      if (movieCloudState.loadingUser === userId) movieCloudState.loadingUser = null;
    }
  };
  const movieRead = () => {
    try {
      const raw = JSON.parse(localStorage.getItem(movieStorageKey()) || "[]");
      if (!Array.isArray(raw)) return [];
      const now = Date.now();
      let changed = false;
      const projects = raw.filter(item => item && typeof item === "object" && item.id).map(item => {
        const project = {
          ...item,
          story: item.story || item.idea || "",
          completedSteps: Array.isArray(item.completedSteps) ? item.completedSteps.filter(key => movieStages.some(stage => stage.key === key)) : []
        };
        if (!authSession?.user && !project.guestExpiresAt) {
          project.guestExpiresAt = new Date(now + 24 * 60 * 60 * 1000).toISOString();
          changed = true;
        }
        return project;
      });
      let active = projects;
      if (!authSession?.user) {
        const expired = projects.filter(project => Number.isFinite(Date.parse(project.guestExpiresAt)) && Date.parse(project.guestExpiresAt) <= now);
        active = projects.filter(project => !expired.includes(project));
        if (expired.length) {
          const archived = readGuestArchive();
          const byId = new Map(archived.map(project => [project.id, project]));
          expired.forEach(project => byId.set(project.id, { ...project, guestArchivedAt: project.guestArchivedAt || new Date(now).toISOString() }));
          if (writeGuestArchive([...byId.values()])) {
            changed = true;
            sessionStorage.setItem("pwa-studio-guest-expired-notice", "1");
          } else {
            // If archiving fails (for example, storage is full), keep expired records in the main list.
            active = projects;
          }
        }
      }
      if (changed) localStorage.setItem(movieStorageKey(), JSON.stringify(active));
      return active.sort((a, b) => new Date(b.updatedAt || b.createdAt || 0) - new Date(a.updatedAt || a.createdAt || 0));
    } catch { return []; }
  };
  const movieWrite = projects => {
    try {
      localStorage.setItem(movieStorageKey(), JSON.stringify(projects));
      scheduleMovieCloudSync();
      return true;
    } catch (error) {
      console.error("Movie project storage failed:", error);
      const feedback = $("#movieFeedback");
      if (feedback) feedback.textContent = "Не удалось сохранить изменения в памяти браузера. Проверьте свободное место и настройки приватности.";
      return false;
    }
  };
  const movieId = () => (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : "movie-" + Date.now() + "-" + Math.random().toString(36).slice(2,9);
  const movieSnapshot = project => { const copy={...project}; delete copy.versions; return copy; };
  const addMovieVersion = project => {
    const versions=Array.isArray(project.versions)?project.versions:[];
    versions.unshift({savedAt:new Date().toISOString(),data:movieSnapshot(project)});
    project.versions=versions.slice(0,20);
  };
  const movieDate = value => {
    const date=new Date(value || Date.now());
    return Number.isNaN(date.getTime())?"Дата не указана":date.toLocaleString("ru-RU",{dateStyle:"short",timeStyle:"short"});
  };
  const ensureMovieWorkflowPanel = () => {
    let panel=$("#movieWorkflowPanel"); if(panel)return panel;
    const tools=$(".movie-tools-grid"); if(!tools)return null;
    panel=document.createElement("section"); panel.id="movieWorkflowPanel"; panel.className="panel movie-workflow-panel"; panel.hidden=true;
    tools.parentNode.insertBefore(panel,tools); return panel;
  };
  const movieProgress = project => {
    const done=Array.isArray(project.completedSteps)?project.completedSteps:[];
    return done.length+" из 4 этапов завершено";
  };
  const movieEditionLabel = project => [
    project.seriesNumber ? "Серия "+project.seriesNumber : "",
    project.versionLabel ? "Версия: "+project.versionLabel : ""
  ].filter(Boolean).join(" · ");
  // Keep collection cards focused on the synopsis, not stage-specific production notes.
  const isMovieProductionNotes = value => /(?:Музыка и звуковое оформление|План монтажа|Монтаж\s*\n|Визуальный стиль\s*\n|Титры\s*\n|Full HD|24 кадра)/i.test(String(value || ""));
  const movieCardDescription = project => {
    const current = String(project.story || project.idea || "").trim();
    if (current && !isMovieProductionNotes(current)) return current;
    const previous = (Array.isArray(project.versions) ? project.versions : [])
      .map(version => version && version.data ? String(version.data.idea || "").trim() : "")
      .find(value => value && !isMovieProductionNotes(value));
    return previous || "Краткое описание истории пока не добавлено. Сценарий и материалы этапов сохранены отдельно.";
  };
  const updateMovieStageCards = () => {
    const project=movieRead().find(item=>item.id===activeMovieId);
    $$(".movie-tool-card[data-movie-tool]").forEach((button,index)=>{
      const unlocked=!!project && (index===0 || (project.completedSteps||[]).includes(movieStages[index-1].key));
      button.disabled=!unlocked; button.setAttribute("aria-disabled",String(!unlocked)); button.classList.toggle("is-locked",!unlocked);
      const hint=$("em",button);
      if(hint)hint.textContent=!project?"Сначала создайте или выберите фильм":unlocked?((project.completedSteps||[]).includes(movieStages[index].key)?"Открыть и изменить этап ↗":"Начать этап ↗"):"🔒 Сначала завершите предыдущий этап";
    });
  };
  const setMovieCreationFormVisible = visible => {
    const form=$("#movieForm");
    const heading=form?.closest(".movie-workbench")?.querySelector(".movie-section-head");
    if(form)form.hidden=!visible;
    if(heading)heading.hidden=!visible;
  };
  const openMovieDetailsStage = projectId => {
    const project=movieRead().find(item=>item.id===projectId);
    const panel=ensureMovieWorkflowPanel();
    if(!project||!panel)return;
    activeMovieId=projectId; editingMovieId=projectId; setMovieCreationFormVisible(false); updateMovieStageCards(); panel.replaceChildren();
    const head=document.createElement("div"); head.className="movie-workflow-head";
    const title=document.createElement("h2"); title.textContent="Этап 1 из 5 · Основные сведения о фильме";
    const subtitle=document.createElement("p"); subtitle.textContent="Фильм: "+(project.name||"Без названия")+" · Измените сведения и перейдите к сценарию. Уже сохранённые материалы останутся на месте.";
    head.append(title,subtitle);
    const form=document.createElement("div"); form.className="movie-stage-fields movie-details-fields";
    const fields=[
      ["movieName","Название фильма",project.name||"", "Например: Тайна старого маяка","text"],
      ["movieSeriesNumber","Номер серии",project.seriesNumber||"", "Если это продолжение","number"],
      ["movieVersionLabel","Название версии",project.versionLabel||"", "Необязательно","text"],
      ["movieIdea","Идея и краткое описание",project.idea||"", "О чём ваша история?","textarea"],
      ["movieGenre","Жанр",project.genre||"Приключения","","select"],
      ["movieDuration","Продолжительность",String(project.duration||5),"","duration"],
      ["movieFrame","Формат кадра",project.frame||"16:9","","frame"]
    ];
    const inputs={};
    fields.forEach(([key,labelText,value,placeholder,type])=>{
      const wrap=document.createElement("label"); wrap.className="movie-stage-field";
      const label=document.createElement("span"); label.textContent=labelText;
      let field;
      if(type==="textarea"){field=document.createElement("textarea");field.rows=5;field.maxLength=12000;field.placeholder=placeholder;}
      else if(type==="select"||type==="duration"||type==="frame"){
        field=document.createElement("select");
        const choices=type==="select"?["Приключения","Фэнтези","Фантастика","Драма","Комедия","Детектив","Мультфильм","Документальный","Обучающий фильм","Музыкальный клип"]:type==="duration"?[["1","До 1 минуты"],["3","Около 3 минут"],["5","Около 5 минут"],["10","Около 10 минут"],["15","Около 15 минут"],["30","30 минут и более"]]:[["16:9","Кино · 16:9"],["9:16","Вертикальный · 9:16"],["1:1","Квадрат · 1:1"]];
        choices.forEach(choice=>{const option=document.createElement("option");option.value=Array.isArray(choice)?choice[0]:choice;option.textContent=Array.isArray(choice)?choice[1]:choice;field.append(option);});
      }else{field=document.createElement("input");field.type=type;field.maxLength=key==="movieName"?90:60;if(type==="number"){field.min="1";field.max="999";field.step="1";}}
      field.value=String(value); field.id="movieDetails_"+key; inputs[key]=field; wrap.append(label,field); form.append(wrap);
    });
    const actions=document.createElement("div"); actions.className="movie-stage-actions";
    const status=document.createElement("p"); status.className="movie-stage-feedback"; status.setAttribute("role","status"); status.style.cssText="display:block;flex-basis:100%;margin:8px 0;";
    const saveDraft=document.createElement("button"); saveDraft.type="button"; saveDraft.className="secondary-button"; saveDraft.textContent="Сохранить сведения";
    const back=document.createElement("button"); back.type="button"; back.className="secondary-button"; back.textContent="← К списку фильмов"; back.addEventListener("click",()=>{panel.hidden=true;setMovieCreationFormVisible(true);});
    const next=document.createElement("button"); next.type="button"; next.className="primary-button"; next.textContent="Сохранить и перейти к сценарию →";
    const persist=()=>{
      const name=inputs.movieName.value.trim();
      if(!name){status.textContent="Укажите название фильма.";inputs.movieName.focus();return false;}
      const latest=movieRead(); const index=latest.findIndex(item=>item.id===projectId); if(index<0){status.textContent="Фильм не найден.";return false;}
      const current=latest[index]; addMovieVersion(current);
      Object.assign(current,{
        name, seriesNumber:inputs.movieSeriesNumber.value?Number(inputs.movieSeriesNumber.value):null,
        versionLabel:inputs.movieVersionLabel.value.trim(), idea:inputs.movieIdea.value.trim(),
        genre:inputs.movieGenre.value, duration:Number(inputs.movieDuration.value), frame:inputs.movieFrame.value,
        updatedAt:new Date().toISOString()
      });
      if(!movieWrite(latest)){status.textContent="Не удалось сохранить изменения.";return false;}
      renderMovieProjects(); status.textContent="✓ Основные сведения сохранены.";
      return true;
    };
    saveDraft.addEventListener("click",persist);
    next.addEventListener("click",()=>{if(persist())openMovieStage(projectId,0);});
    actions.append(back,saveDraft,next,status); panel.append(head,form,actions); panel.hidden=false; panel.setAttribute("data-active-stage","details");
    requestAnimationFrame(()=>panel.scrollIntoView({behavior:"smooth",block:"start"}));
  };
  const openMovieStage = (projectId,stageIndex) => {
    const projects=movieRead(); const project=projects.find(item=>item.id===projectId); const panel=ensureMovieWorkflowPanel();
    if(!project||!panel||stageIndex<0||stageIndex>=movieStages.length)return;
    const done=Array.isArray(project.completedSteps)?project.completedSteps:[];
    if(stageIndex>0&&!done.includes(movieStages[stageIndex-1].key)){const feedback=$("#movieFeedback");if(feedback)feedback.textContent="Сначала завершите предыдущий этап.";return;}
    activeMovieId=projectId; setMovieCreationFormVisible(false); updateMovieStageCards();
    const stage=movieStages[stageIndex]; panel.replaceChildren();
    const head=document.createElement("div"); head.className="movie-workflow-head";
    const title=document.createElement("h2"); title.textContent="Этап "+(stageIndex+1)+" из 4 · "+stage.title;
    const edition=movieEditionLabel(project);
    const subtitle=document.createElement("p"); subtitle.textContent="Фильм: "+project.name+(edition?" · "+edition:"")+" · "+(done.includes(stage.key)?"Этап сохранён — его можно редактировать.":"Заполните материалы и сохраните, чтобы открыть следующий этап.");
    head.append(title,subtitle);
    const form=document.createElement("div"); form.className="movie-stage-fields"; form.style.cssText="display:grid;grid-template-columns:minmax(0,1fr);gap:14px;width:100%;margin:16px 0;"; const inputs={};
    stage.fields.forEach(([key,labelText,placeholder])=>{
      const wrap=document.createElement("label"); wrap.className="movie-stage-field"; wrap.style.cssText="display:grid;gap:9px;width:100%;min-width:0;padding:14px;border:1px solid rgba(166,154,187,.22);border-radius:12px;background:rgba(17,16,32,.72);color:#c4bed5;";
      const label=document.createElement("span"); label.textContent=labelText; label.style.cssText="display:block;font-size:13px;font-weight:700;color:#e5def5;";
      const textarea=document.createElement("textarea"); textarea.rows=(key==="story"||key==="storyboard")?7:6; textarea.maxLength=30000; textarea.placeholder=placeholder; textarea.style.cssText="display:block;width:100%;min-height:150px;padding:13px;border:1px solid rgba(166,154,187,.35);border-radius:9px;background:#0f0e1d;color:#eee9fa;font:inherit;font-size:14px;line-height:1.55;resize:vertical;visibility:visible;opacity:1;";
      textarea.value=project[key]||(key==="story"?project.idea||"":""); inputs[key]=textarea; wrap.append(label,textarea); form.append(wrap);
    });
    let selectedLibrarySnapshots=Array.isArray(project.characterLibrarySnapshots)?project.characterLibrarySnapshots.map(item=>({...item})).filter(item=>item&&typeof item.id==="string"):[];
    if(stage.key==="characters"){
      const libraryItems=readCharacterLibrary();
      const picker=document.createElement("section");picker.className="movie-character-picker movie-stage-field";
      const pickerTitle=document.createElement("strong");pickerTitle.textContent="Персонажи из вашей библиотеки";
      const pickerNote=document.createElement("p");pickerNote.className="movie-stage-note";pickerNote.textContent=libraryItems.length?"Выберите сохранённых персонажей или локации. В фильм попадёт снимок их паспорта; мастер-карточка останется независимой. Сами файлы изображений пока остаются в библиотеке и не копируются в проект.":"В библиотеке пока нет карточек. Можно продолжить с текстовым описанием или сначала добавить персонажа в Prompt Studio.";
      picker.append(pickerTitle,pickerNote);
      if(libraryItems.length){
        const select=document.createElement("select");select.multiple=true;select.size=Math.min(5,Math.max(2,libraryItems.length));select.setAttribute("aria-label","Выберите персонажей и локации из библиотеки");select.style.cssText="width:100%;min-height:100px;padding:10px;border-radius:9px;background:#0f0e1d;color:#eee9fa;border:1px solid rgba(166,154,187,.35);";
        libraryItems.forEach(item=>{const option=document.createElement("option");option.value=item.id;option.textContent=(item.kind==="scene"?"Локация · ":"Персонаж · ")+item.name+(selectedLibrarySnapshots.some(saved=>saved.id===item.id)?" · уже добавлен":"");select.append(option);});
        const add=document.createElement("button");add.type="button";add.className="secondary-button";add.textContent="＋ Добавить выбранных в фильм";
        const selectedStatus=document.createElement("p");selectedStatus.className="movie-stage-note";selectedStatus.setAttribute("role","status");
        add.addEventListener("click",()=>{
          const chosen=libraryItems.filter(item=>Array.from(select.selectedOptions).some(option=>option.value===item.id));
          if(!chosen.length){selectedStatus.textContent="Сначала выберите хотя бы одну карточку.";return;}
          const added=[];
          chosen.forEach(item=>{
            if(selectedLibrarySnapshots.some(saved=>saved.id===item.id))return;
            const snapshot={id:item.id,name:item.name,kind:item.kind||"character",representation:item.representation||"2d",description:item.description||"",voice:item.voice||"",passport:item.passport||{},referenceImages:(item.referenceImages||[]).map(ref=>({id:ref.id,name:ref.name||"",type:ref.type||""}))};
            selectedLibrarySnapshots.push(snapshot);added.push(snapshot);
          });
          if(!added.length){selectedStatus.textContent="Выбранные карточки уже добавлены.";return;}
          const identityText=added.map(item=>[
            "[[PWA_LIBRARY_ITEM:"+item.id+"]]",
            (item.kind==="scene"?"ЛОКАЦИЯ":"ПЕРСОНАЖ")+": "+item.name,
            "Тип представления: "+(item.representation==="both"?"2D + 3D":item.representation==="3d"?"3D-паспорт":"2D"),
            "Описание: "+item.description,
            "Лицо и профиль: "+(item.passport.face||"—"),
            "Силуэт: "+(item.passport.body||"—"),
            "Одежда и аксессуары: "+(item.passport.wardrobe||"—"),
            "Палитра и эмоции: "+(item.passport.palette||"—"),
            "Голос: "+(item.voice||"—"),
            "Референсы (файлы пока не прикреплены к проекту): "+(item.referenceImages.length?item.referenceImages.map(ref=>ref.name).join(", "):"не указаны"),
            "[[/PWA_LIBRARY_ITEM:"+item.id+"]]"
          ].join("\n")).join("\n\n");
          const currentText=inputs.characters.value.trim();
          inputs.characters.value=(currentText?currentText+"\n\n":"")+identityText;
          inputs.characters.dispatchEvent(new Event("input",{bubbles:true}));
          selectedStatus.textContent="Добавлено в снимок фильма: "+added.map(item=>item.name).join(", ")+". Нажмите «Сохранить черновик» или завершите этап.";
        });
        picker.append(select,add,selectedStatus);
      }
      const linked=document.createElement("div");linked.className="movie-character-linked";
      const refreshLinked=()=>{
        linked.replaceChildren();
        if(!selectedLibrarySnapshots.length){const empty=document.createElement("p");empty.className="movie-stage-note";empty.textContent="К этому фильму пока не привязаны карточки из библиотеки.";linked.append(empty);return;}
        const caption=document.createElement("p");caption.className="movie-stage-note";caption.textContent="Снимки паспортов и выбранные референсы для будущих сцен:";linked.append(caption);
        selectedLibrarySnapshots.forEach(item=>{
          const card=document.createElement("section");card.className="movie-character-reference-card";
          const row=document.createElement("div");row.className="movie-character-linked-row";
          const name=document.createElement("strong");name.textContent=(item.kind==="scene"?"Локация · ":"Персонаж · ")+item.name;
          const remove=document.createElement("button");remove.type="button";remove.className="secondary-button";remove.textContent="Убрать из фильма";
          remove.addEventListener("click",()=>{selectedLibrarySnapshots=selectedLibrarySnapshots.filter(saved=>saved.id!==item.id);const startMarker="[[PWA_LIBRARY_ITEM:"+item.id+"]]",endMarker="[[/PWA_LIBRARY_ITEM:"+item.id+"]]",parts=inputs.characters.value.split(startMarker);if(parts.length>1){const rest=parts.slice(1).map(part=>{const endAt=part.indexOf(endMarker);return endAt>=0?part.slice(endAt+endMarker.length):part;}).join("");inputs.characters.value=parts[0]+rest;inputs.characters.dispatchEvent(new Event("input",{bubbles:true}));}refreshLinked();});
          row.append(name,remove);card.append(row);
          const referenceList=document.createElement("div");referenceList.className="movie-character-reference-list";
          const refs=(item.referenceImages||[]).filter(ref=>ref.id);
          if(refs.length){
            const hint=document.createElement("p");hint.className="movie-stage-note";hint.textContent="Отметьте изображения, которые нужно использовать как визуальные ориентиры. Файлы остаются в вашей библиотеке.";referenceList.append(hint);
            refs.forEach(ref=>{
              const label=document.createElement("label");label.className="movie-character-reference-option";
              const checkbox=document.createElement("input");checkbox.type="checkbox";checkbox.checked=(item.selectedReferenceIds||[]).includes(ref.id);
              checkbox.addEventListener("change",()=>{item.selectedReferenceIds=Array.isArray(item.selectedReferenceIds)?item.selectedReferenceIds:[];item.selectedReferenceIds=checkbox.checked?[...new Set([...item.selectedReferenceIds,ref.id])]:item.selectedReferenceIds.filter(id=>id!==ref.id);});
              const textLabel=document.createElement("span");textLabel.textContent=ref.name||"Референс";
              label.append(checkbox,textLabel);referenceList.append(label);
            });
          }else{const empty=document.createElement("p");empty.className="movie-stage-note";empty.textContent="У этой карточки пока нет изображений-референсов.";referenceList.append(empty);}
          const sceneLabel=document.createElement("label");sceneLabel.className="movie-character-scene-assignment";
          const sceneCaption=document.createElement("span");sceneCaption.textContent="Номера сцен для этого образа (например: 1, 2, 4):";
          const sceneInput=document.createElement("input");sceneInput.type="text";sceneInput.maxLength=80;sceneInput.placeholder="Все сцены — оставьте пустым";sceneInput.value=Array.isArray(item.sceneNumbers)?item.sceneNumbers.join(", "):"";
          sceneInput.addEventListener("input",()=>{item.sceneNumbers=[...new Set(sceneInput.value.split(/[;,\\s]+/).map(value=>Number(value)).filter(value=>Number.isInteger(value)&&value>0&&value<=999))];});
          sceneLabel.append(sceneCaption,sceneInput);referenceList.append(sceneLabel);card.append(referenceList);linked.append(card);
        });
      };
      refreshLinked();picker.append(linked);form.append(picker);
    }
    if(stage.key==="story"){
      const assigned=(Array.isArray(project.characterLibrarySnapshots)?project.characterLibrarySnapshots:[]).filter(item=>Array.isArray(item.selectedReferenceIds)&&item.selectedReferenceIds.length);
      if(assigned.length){
        const continuity=document.createElement("aside");continuity.className="movie-scene-reference-guidance";
        const title=document.createElement("strong");title.textContent="Визуальные ориентиры для раскадровки";
        const intro=document.createElement("p");intro.textContent="Учитывайте эти утверждённые референсы при описании кадров. Номера сцен указаны в настройках персонажей. Это подсказка для автора: файлы ещё не отправляются в видеогенератор.";
        continuity.append(title,intro);
        assigned.forEach(item=>{
          const line=document.createElement("p");const sceneText=Array.isArray(item.sceneNumbers)&&item.sceneNumbers.length?"Сцены "+item.sceneNumbers.join(", "):"Все сцены";
          const selected=(item.referenceImages||[]).filter(ref=>item.selectedReferenceIds.includes(ref.id)).map(ref=>ref.name).filter(Boolean);
          line.textContent=(item.kind==="scene"?"Локация: ":"Персонаж: ")+item.name+" · "+sceneText+" · "+(selected.length?selected.join(", "):"выбранные референсы");
          continuity.append(line);
        });
        form.append(continuity);
      }
    }
    let showTitlesControl=null;
    if(stage.key==="edit"){
      const titlesWrap=document.createElement("label");
      titlesWrap.className="movie-stage-field";
      titlesWrap.style.cssText="display:flex;align-items:center;gap:12px;padding:14px;border:1px solid rgba(166,154,187,.22);border-radius:12px;background:rgba(17,16,32,.72);color:#e5def5;";
      showTitlesControl=document.createElement("input");
      showTitlesControl.type="checkbox";
      showTitlesControl.checked=project.showTitles!==false;
      showTitlesControl.style.cssText="width:20px;height:20px;accent-color:#a98aff;flex:0 0 auto;";
      const titlesLabel=document.createElement("span");
      titlesLabel.textContent="Показывать титры (вступительные, имена персонажей и заключительные)";
      titlesWrap.append(showTitlesControl,titlesLabel);
      form.append(titlesWrap);
    }
    const aiTools=document.createElement("div"); aiTools.className="movie-stage-ai-tools";
    aiTools.style.cssText="display:flex;flex-wrap:wrap;gap:10px;margin:14px 0;width:100%;";
    let aiStatus=null;
    if(["story","characters","voices","edit"].includes(stage.key)){
      const aiButton=document.createElement("button"); aiButton.type="button"; aiButton.className="primary-button"; aiButton.textContent="✦ Создать с Studio AI";
      const manualButton=document.createElement("button"); manualButton.type="button"; manualButton.className="secondary-button"; manualButton.textContent="✍ Заполнить самостоятельно";
      aiStatus=document.createElement("p"); aiStatus.className="movie-stage-feedback"; aiStatus.setAttribute("role","status"); aiStatus.setAttribute("aria-live","polite"); aiStatus.style.cssText="display:block;flex-basis:100%;margin:4px 0;padding:10px 12px;border-radius:10px;background:rgba(157,121,235,.12);font-size:13px;";
      const stageHints={
        story:"Studio AI создаст сценарий и раскадровку по идее фильма.",
        characters:"Studio AI разработает персонажей и сохранит визуальную непрерывность.",
        voices:"Studio AI подготовит распределение голосов, реплики, музыку и звуковые эффекты.",
        edit:"Studio AI составит подробный план монтажа и будущего экспорта."
      };
      aiStatus.textContent=stageHints[stage.key];
      manualButton.addEventListener("click",()=>{const first=Object.values(inputs)[0];first?.focus();aiStatus.textContent="Можно заполнить материалы самостоятельно. Ваш текст сохранится после нажатия кнопки сохранения.";});
      aiButton.addEventListener("click",async()=>{
        const requestAuthVersion=authContextVersion,requestUserId=authSession?.user?.id||"guest";
        const contextIsCurrent=()=>requestAuthVersion===authContextVersion&&(authSession?.user?.id||"guest")===requestUserId;
        aiButton.disabled=true;manualButton.disabled=true;aiButton.textContent="Studio AI работает…";
        aiStatus.textContent="Изучаю материалы фильма и готовлю результат для этого этапа…";
        const latest=movieRead().find(item=>item.id===projectId)||project;
        const title=String(latest.name||"Без названия").slice(0,100);
        const idea=String(latest.idea||"").slice(0,5000);
        const story=String(latest.story||latest.idea||"").slice(0,16000);
        const storyboard=String(latest.storyboard||"").slice(0,7000);
        const characters=String(latest.characters||"").slice(0,7000);
        const voices=String(latest.voices||"").slice(0,9000);
        const edit=String(latest.edit||"").slice(0,7000);
        // Text-only continuity brief. Image blobs in IndexedDB are never sent through /api/chat.
        const continuityBrief=(Array.isArray(latest.characterLibrarySnapshots)?latest.characterLibrarySnapshots:[])
          .map(item=>{
            if(!item||typeof item!=="object")return "";
            const selected=(Array.isArray(item.referenceImages)?item.referenceImages:[])
              .filter(ref=>ref&&Array.isArray(item.selectedReferenceIds)&&item.selectedReferenceIds.includes(ref.id))
              .map(ref=>String(ref.name||"визуальный референс").slice(0,100));
            const scenes=Array.isArray(item.sceneNumbers)&&item.sceneNumbers.length
              ?"Только сцены: "+item.sceneNumbers.filter(n=>Number.isInteger(n)&&n>0&&n<=999).join(", ")
              :"Все сцены";
            const passport=item.passport&&typeof item.passport==="object"?item.passport:{};
            return [
              (item.kind==="scene"?"ЛОКАЦИЯ: ":"ПЕРСОНАЖ: ")+String(item.name||"Без имени").slice(0,100),
              "Образ: "+String(item.representation||"2d"),
              "Описание: "+String(item.description||"").slice(0,500),
              "Идентичность/лицо: "+String(passport.face||"").slice(0,500),
              "Силуэт: "+String(passport.body||"").slice(0,300),
              "Одежда и аксессуары: "+String(passport.wardrobe||"").slice(0,400),
              "Палитра и эмоции: "+String(passport.palette||"").slice(0,300),
              "Привязка: "+scenes,
              "Выбранные референсы (названия, не файлы): "+(selected.join(", ")||"не выбраны")
            ].join("\n");
          }).filter(Boolean).join("\n\n").slice(0,6000);
        let prompt="";
        if(stage.key==="story"){
          prompt=[
            "Ты — сценарист и режиссёр раскадровки PWA Studio.",
            "Разработай сценарий фильма «"+title+"» и подробную раскадровку.",
            "Сохраняй утверждённые паспорта персонажей как канонические. Не меняй лицо, волосы, цвет глаз, силуэт, отличительные детали и базовую палитру; меняй позу, эмоцию и ракурс только по действию сцены. Учитывай номера сцен, назначенные автором.",
            "Для каждой сцены явно указывай присутствующих персонажей и локации, не смешивай их идентичности.",
            "Исходная идея: "+(idea||"Пользователь пока не добавил отдельное описание идеи. Развивай название и имеющиеся материалы бережно."),
            "Жанр: "+String(latest.genre||"не указан")+". Заявленная длительность: "+String(latest.duration||5)+" минут. Кадр: "+String(latest.frame||"16:9")+".",
            "Если ниже уже есть сценарий или раскадровка, улучшай и развивай их, сохраняя имена, факты, сюжетные решения и авторский замысел. Не переписывай без необходимости уже готовый материал.",
            "Верни строго два раздела с точными заголовками: === СЦЕНАРИЙ === и === РАСКАДРОВКА ===.",
            "В сценарии: логлайн, персонажи в кратком виде, сцены по порядку, место/время, действия и диалоги, кульминация и финал. Соблюдай заявленную длительность; если история длиннее, честно укажи ориентировочный хронометраж.",
            "В раскадровке: для каждой сцены нумерованные кадры, крупность, композиция, движение камеры, действие, свет/цвет, переход и ориентировочная длительность. Учитывай, что это план, а не готовое видео.",
            "Пиши по-русски. Не добавляй опасных инструкций, не выдавай вымысел за реальные факты.",
            "\nПАСПОРТА И ВИЗУАЛЬНЫЕ ОГРАНИЧЕНИЯ (только текст):\n"+continuityBrief,
            "\nТЕКУЩИЙ СЦЕНАРИЙ:\n"+story,
            "\nТЕКУЩАЯ РАСКАДРОВКА:\n"+storyboard
          ].join("\n");
        }else if(stage.key==="characters"){
          prompt=[
            "Ты — художник-постановщик и специалист по дизайну персонажей PWA Studio.",
            "Создай подробную библию персонажей фильма «"+title+"» на основе сценария и раскадровки.",
            "Сначала сохрани утверждённые паспорта из библиотеки как канонические. Не переосмысливай лицо, волосы, силуэт, палитру и отличительные признаки. Если сценарий расходится с паспортом, отметь конфликт отдельно и не исправляй паспорт молча.",
            "Не меняй сюжет, имена, возраст и отношения, если они уже указаны. Не добавляй новых важных героев без необходимости. Для каждого героя опиши роль, возраст (только если известен), лицо, телосложение, волосы, одежду, обувь, аксессуары, характер, пластику, мимику, манеру держаться и отличительные детали.",
            "Добавь отдельные блоки: визуальные референсы словами для генерации; палитра и материалы; правила постоянства внешности между сценами; что нельзя менять от кадра к кадру; варианты одежды только если они обоснованы сценой.",
            "Если персонаж появляется только голосом, явно отметь это и не придумывай ему видимую внешность. Не приписывай реальным людям неуказанные особенности.",
            "Пиши по-русски, структурированно и практически, чтобы описание можно было использовать как основу для генерации изображений и видео.",
            "\nСЦЕНАРИЙ:\n"+story,
            "\nРАСКАДРОВКА:\n"+storyboard,
            "\nКАНОНИЧЕСКИЕ ПАСПОРТА И ВЫБРАННЫЕ РЕФЕРЕНСЫ (только текст):\n"+continuityBrief,
            "\nТЕКУЩИЕ ОПИСАНИЯ ПЕРСОНАЖЕЙ:\n"+String(inputs.characters?.value||characters).slice(0,7000)
          ].join("\n");
        }else if(stage.key==="voices"){
          prompt=[
            "Ты — режиссёр по звуку и специалист по озвучке PWA Studio.",
            "Подготовь полный практический план голосов и звука для фильма «"+title+"».",
            "Используй сценарий, раскадровку и персонажей. Не меняй сюжет и имена. Точные реплики бери из сценария, не придумывай события.",
            "Структура: 1) язык и общий стиль; 2) таблица персонаж → тип/тембр/возрастное звучание/манера речи/темп/эмоция; 3) реплики и голос за кадром по сценам; 4) музыка по сценам и переходам; 5) звуковые эффекты и атмосфера; 6) технические заметки для будущей генерации.",
            "Пиши по-русски, конкретно. Художественные предложения помечай как предложения. Не утверждай, что аудио уже создано.",
            "\nСЦЕНАРИЙ:\n"+story,
            "\nРАСКАДРОВКА:\n"+storyboard,
            "\nПЕРСОНАЖИ:\n"+characters,
            "\nТЕКУЩИЙ ПЛАН ОЗВУЧКИ:\n"+String(inputs.voices?.value||voices||"Нет.").slice(0,5000)
          ].join("\n");
        }else{
          prompt=[
            "Ты — режиссёр монтажа и супервайзер постпроизводства PWA Studio.",
            "Составь подробный план монтажа и будущего экспорта фильма «"+title+"» по предоставленным материалам.",
            "Сохраняй сюжет, порядок событий, имена и визуальные решения. Не добавляй новые сцены, если их нет в сценарии; допустимы только технические предложения, явно помеченные как предложения.",
            "Структура: 1) монтажная концепция и ориентировочный хронометраж; 2) последовательность сцен с длительностью, ключевыми кадрами и склейками; 3) темп и ритм; 4) цветокоррекция и визуальная непрерывность; 5) размещение диалогов, музыки и эффектов с учётом плана озвучки; 6) титры только согласно настройке пользователя; 7) параметры будущего экспорта и список контроля качества.",
            "Настройка титров: "+(showTitlesControl?.checked?"ТИТРЫ ВКЛЮЧЕНЫ — предложи уместные вступительные, имена персонажей и заключительные титры.":"ТИТРЫ ОТКЛЮЧЕНЫ — не добавляй никаких титров, надписей, имён персонажей или заключительных заставок; оставь только изображение и звук."),
            "Учитывай настройки проекта: длительность "+String(latest.duration||5)+" минут, кадр "+String(latest.frame||"16:9")+". Предлагай Full HD и 24 кадра/с только как параметры будущего экспорта, не заявляй, что рендер уже выполнен.",
            "Пиши по-русски, практично и по сценам.",
            "\nСЦЕНАРИЙ:\n"+story,
            "\nРАСКАДРОВКА:\n"+storyboard,
            "\nПЕРСОНАЖИ:\n"+characters,
            "\nПЛАН ОЗВУЧКИ:\n"+voices,
            "\nТЕКУЩИЙ ПЛАН МОНТАЖА:\n"+String(inputs.edit?.value||edit||"Нет.").slice(0,7000)
          ].join("\n");
        }
        try{
          const result=await apiRequest("/api/chat",{method:"POST",body:JSON.stringify({message:prompt,history:[]})});
          if(!contextIsCurrent())return;
          const generated=String(result.reply||"").trim();
          if(!generated)throw new Error("Studio AI вернул пустой ответ.");
          if(stage.key==="story"){
            const storyMarker="=== СЦЕНАРИЙ ===";
            const boardMarker="=== РАСКАДРОВКА ===";
            const storyAt=generated.indexOf(storyMarker);
            const boardAt=generated.indexOf(boardMarker);
            if(storyAt>=0&&boardAt>storyAt){
              inputs.story.value=generated.slice(storyAt+storyMarker.length,boardAt).trim();
              inputs.storyboard.value=generated.slice(boardAt+boardMarker.length).trim();
            }else{
              inputs.story.value=generated;
              aiStatus.textContent="✓ Черновик сценария создан. Если раскадровка не выделилась отдельно, попроси Studio AI повторить с двумя точными заголовками.";
            }
          }else{
            const key=stage.key==="characters"?"characters":stage.key==="voices"?"voices":"edit";
            if(inputs[key])inputs[key].value=generated;
          }
          Object.values(inputs).forEach(input=>input.dispatchEvent(new Event("input",{bubbles:true})));
          if(!aiStatus.textContent.startsWith("✓ Черновик сценария"))aiStatus.textContent="✓ Материалы этапа подготовлены. Проверь их, при необходимости отредактируй и нажми «Сохранить черновик» или кнопку завершения этапа.";
          Object.values(inputs)[0]?.focus();
        }catch(error){
          if(contextIsCurrent())aiStatus.textContent="Не удалось создать материалы: "+(error?.message||"ошибка соединения")+". Можно заполнить поля самостоятельно.";
        }finally{
          if(contextIsCurrent()){aiButton.disabled=false;manualButton.disabled=false;aiButton.textContent="✦ Создать с Studio AI";}
        }
      });
      aiTools.append(aiButton,manualButton,aiStatus);
    }
    const actions=document.createElement("div"); actions.className="movie-stage-actions";
    const draft=document.createElement("button"); draft.type="button"; draft.className="secondary-button"; draft.textContent="Сохранить черновик";
    const draftStatus=document.createElement("p"); draftStatus.className="movie-stage-feedback"; draftStatus.setAttribute("role","status"); draftStatus.setAttribute("aria-live","polite"); draftStatus.style.cssText="display:block;flex-basis:100%;margin:8px 0;padding:10px 12px;border-radius:10px;background:rgba(16,185,129,.12);font-size:14px;";
    let draftStatusTimer=null;
    draft.addEventListener("click",()=>{
      if(draftStatusTimer)clearTimeout(draftStatusTimer);
      draftStatus.textContent="";
      draft.disabled=true; draftStatus.textContent="Сохраняю черновик…";
      try{
        const latest=movieRead(); const index=latest.findIndex(item=>item.id===projectId);
        if(index<0){draftStatus.textContent="Не удалось найти этот фильм. Вернитесь к проекту и откройте этап снова.";return;}
        const current=latest[index]; addMovieVersion(current);
        stage.fields.forEach(([key])=>{current[key]=inputs[key].value.trim();});
        if(stage.key==="characters")current.characterLibrarySnapshots=selectedLibrarySnapshots.map(item=>({...item}));
        if(stage.key==="edit"&&showTitlesControl)current.showTitles=showTitlesControl.checked;
        if(stage.key==="story" && current.story) current.idea=current.story;
        current.updatedAt=new Date().toISOString();
        if(!movieWrite(latest)){draftStatus.textContent="Сохранение не удалось. Проверьте сообщение вверху страницы.";return;}
        draftStatus.textContent="✓ Черновик этапа «"+stage.title+"» сохранён. Этап не отмечен завершённым.";
        const savedMessage=draftStatus.textContent;
        draftStatusTimer=setTimeout(()=>{if(draftStatus.textContent===savedMessage)draftStatus.textContent="";},4000);
        const feedback=$("#movieFeedback"); if(feedback)feedback.textContent=savedMessage;
        renderMovieProjects();
      }catch(error){
        draftStatus.textContent="Ошибка сохранения: "+(error&&error.message?error.message:"неизвестная ошибка");
      }finally{draft.disabled=false;}
    });
    const close=document.createElement("button"); close.type="button"; close.className="secondary-button"; close.textContent="← К проекту"; close.addEventListener("click",()=>{panel.hidden=true;setMovieCreationFormVisible(true);});
    const save=document.createElement("button"); save.type="button"; save.className="primary-button"; save.textContent=stageIndex===3?"Завершить этап":"Сохранить и открыть следующий этап →";
    save.addEventListener("click",()=>{
      const emptyField=stage.fields.find(([key])=>!inputs[key].value.trim());
      if(emptyField){$("#movieFeedback").textContent="Заполните поле «"+emptyField[1]+"», прежде чем завершить этап.";inputs[emptyField[0]].focus();return;}
      const latest=movieRead(); const index=latest.findIndex(item=>item.id===projectId); if(index<0)return;
      const current=latest[index]; addMovieVersion(current);
      stage.fields.forEach(([key])=>{current[key]=inputs[key].value.trim();});
      if(stage.key==="characters")current.characterLibrarySnapshots=selectedLibrarySnapshots.map(item=>({...item}));
      if(stage.key==="edit"&&showTitlesControl)current.showTitles=showTitlesControl.checked;
      current.completedSteps=(Array.isArray(current.completedSteps)?current.completedSteps:[]).filter(key=>movieStages.findIndex(item=>item.key===key)<=stageIndex);
      if(!current.completedSteps.includes(stage.key))current.completedSteps.push(stage.key);
      current.workflowStep=Math.min(stageIndex+1,4); current.updatedAt=new Date().toISOString();
      if(!movieWrite(latest))return;
      renderMovieProjects(); $("#movieFeedback").textContent="✓ Этап «"+stage.title+"» сохранён в фильме «"+current.name+"».";
      if(stageIndex<3)openMovieStage(projectId,stageIndex+1);
      else {
        panel.hidden=false; panel.replaceChildren();
        const complete=document.createElement("div"); complete.className="movie-workflow-complete";
        const h=document.createElement("h2"); h.textContent="✓ Подготовительные этапы завершены";
        const p=document.createElement("p"); p.textContent="Все материалы фильма сохранены. Генерация видео и реальный экспорт пока не подключены.";
        const back=document.createElement("button"); back.type="button"; back.className="secondary-button"; back.textContent="Вернуться к проекту"; back.addEventListener("click",()=>{panel.hidden=true;setMovieCreationFormVisible(true);});
        complete.append(h,p,back); panel.append(complete);
      }
    });
    const previous= document.createElement("button"); previous.type="button"; previous.className="secondary-button"; previous.textContent="← Предыдущий лист";
    previous.addEventListener("click",()=>stageIndex===0?openMovieDetailsStage(projectId):openMovieStage(projectId,stageIndex-1));
    actions.append(previous,draft,close,save,draftStatus); panel.append(head,aiTools,form,actions); panel.hidden=false; panel.setAttribute("data-active-stage",stage.key); requestAnimationFrame(()=>panel.scrollIntoView({behavior:"smooth",block:"start"}));
  };
  const openMovieOverview = projectId => {
    const project=movieRead().find(item=>item.id===projectId); const panel=ensureMovieWorkflowPanel();
    if(!project||!panel)return;
    activeMovieId=projectId; updateMovieStageCards(); panel.replaceChildren();
    const done=Array.isArray(project.completedSteps)?project.completedSteps:[];
    const allDone=movieStages.every(stage=>done.includes(stage.key));
    const head=document.createElement("div"); head.className="movie-workflow-head";
    const title=document.createElement("h2"); title.textContent=allDone?"✓ Все этапы завершены":"Рабочие этапы фильма";
    const edition=movieEditionLabel(project);
    const subtitle=document.createElement("p"); subtitle.textContent="Фильм: "+project.name+(edition?" · "+edition:"")+" · "+movieProgress(project)+". Выберите доступный этап для просмотра или редактирования.";
    head.append(title,subtitle);
    const list=document.createElement("div"); list.className="movie-stage-fields";
    movieStages.forEach((stage,index)=>{
      const row=document.createElement("div"); row.className="movie-stage-field";
      const isDone=done.includes(stage.key); const unlocked=index===0||done.includes(movieStages[index-1].key);
      const label=document.createElement("span"); label.textContent=(index+1)+". "+stage.title+" · "+(isDone?"Сохранён":unlocked?"Черновик":"Заблокирован до завершения предыдущего этапа");
      const button=document.createElement("button"); button.type="button"; button.className="secondary-button"; button.textContent=unlocked?"Открыть этап":"Недоступен"; button.disabled=!unlocked;
      button.addEventListener("click",()=>openMovieStage(projectId,index));
      row.append(label,button); list.append(row);
    });
    const note=document.createElement("p"); note.className="movie-stage-note"; note.textContent="Генерация видео и реальный экспорт пока не подключены.";
    const back=document.createElement("button"); back.type="button"; back.className="secondary-button"; back.textContent="← К списку фильмов"; back.addEventListener("click",()=>{panel.hidden=true;});
    panel.append(head,list,note,back); panel.hidden=false; panel.removeAttribute("data-active-stage");
    requestAnimationFrame(()=>panel.scrollIntoView({behavior:"smooth",block:"start"}));
  };
  const renderMovieProjects = () => {
    const list=$("#movieProjectList"); if(!list)return;
    const projects=movieRead(); const count=$("#movieCount");
    if(count)count.textContent=projects.length+(projects.length===1?" проект":projects.length>1&&projects.length<5?" проекта":" проектов");
    if(!projects.length){
      list.innerHTML='<div class="movie-empty"><span>✧</span><b>Здесь появятся ваши фильмы</b><small>Создайте первый проект, чтобы начать свою кинематографическую историю.</small></div>';
      activeMovieId=null; updateMovieStageCards(); return;
    }
    if(!projects.some(item=>item.id===activeMovieId))activeMovieId=projects[0].id;
    list.replaceChildren();
    projects.forEach((project,index)=>{
      const card=document.createElement("article"); card.className="movie-project-card movie-project-accordion"; card.classList.toggle("is-active",project.id===activeMovieId);
      const toggle=document.createElement("button"); toggle.type="button"; toggle.className="movie-project-toggle"; toggle.setAttribute("aria-expanded","false");
      const number=document.createElement("span"); number.className="movie-project-number"; number.textContent=String(index+1).padStart(2,"0");
      const heading=document.createElement("span"); heading.className="movie-project-heading";
      const title=document.createElement("b"); title.textContent=project.name||"Без названия";
      const details=document.createElement("small"); details.textContent=[movieEditionLabel(project),project.genre||"Жанр не указан",(project.duration||5)+" мин",project.frame||"16:9"].filter(Boolean).join(" · ");
      heading.append(title,details); const chevron=document.createElement("span"); chevron.className="movie-project-chevron"; chevron.textContent="⌄"; toggle.append(number,heading,chevron);
      const panel=document.createElement("div"); panel.className="movie-project-details"; panel.hidden=true;
      const idea=document.createElement("p"); idea.textContent=movieCardDescription(project);
      const progress=document.createElement("small"); progress.className="movie-project-progress"; progress.textContent=movieProgress(project);
      const date=document.createElement("span"); date.className="movie-project-date"; date.textContent="Изменён: "+movieDate(project.updatedAt||project.createdAt);
      const actions=document.createElement("div"); actions.className="movie-project-actions";
      const makeAction=(label,style,handler)=>{const button=document.createElement("button");button.type="button";button.className=style;button.textContent=label;button.addEventListener("click",handler);return button;};
      const edit=makeAction("✎ Этапы и материалы","secondary-button",()=>{
        activeMovieId=project.id; openMovieOverview(project.id);
      });
      const editDetails=makeAction("Изменить сведения","secondary-button",()=>openMovieDetailsStage(project.id));
      const rename=makeAction("✎ Переименовать фильм","secondary-button",()=>{
        const latest=movieRead(); const original=latest.find(item=>item.id===project.id); if(!original)return;
        const entered=window.prompt("Введите новое название фильма:",original.name||"");
        if(entered===null)return;
        const nextName=entered.trim();
        if(!nextName){window.alert("Название фильма не может быть пустым.");return;}
        if(nextName===(original.name||""))return;
        addMovieVersion(original);
        original.name=nextName; original.updatedAt=new Date().toISOString();
        if(!movieWrite(latest))return;
        renderMovieProjects();
        $("#movieFeedback").textContent="✓ Название фильма изменено на «"+nextName+"». Сценарий, этапы и их прогресс сохранены без изменений.";
      });
      const copy=makeAction("⧉ Создать копию","secondary-button",()=>{
        const latest=movieRead(); const original=latest.find(item=>item.id===project.id); if(!original)return;
        const clone={...movieSnapshot(original),id:movieId(),name:(original.name||"Фильм")+" — копия",createdAt:new Date().toISOString(),updatedAt:new Date().toISOString(),versions:[]};
        latest.unshift(clone); if(movieWrite(latest)){activeMovieId=clone.id;renderMovieProjects();$("#movieFeedback").textContent="Копия создана. Оригинальный фильм не изменён.";}
      });
      const version=makeAction("↶ История версий ("+(project.versions||[]).length+")","secondary-button",()=>{
        const current=movieRead().find(item=>item.id===project.id); if(!current)return;
        const versions=Array.isArray(current.versions)?current.versions:[];
        if(!versions.length){$("#movieFeedback").textContent="Пока нет сохранённых версий. Они создаются автоматически перед изменениями.";return;}
        let selectedIndex=0;
        const overlay=document.createElement("div");
        overlay.className="movie-history-overlay";
        overlay.setAttribute("role","dialog");
        overlay.setAttribute("aria-modal","true");
        overlay.setAttribute("aria-labelledby","movieHistoryTitle");
        const dialog=document.createElement("div"); dialog.className="movie-history-dialog";
        const heading=document.createElement("div"); heading.className="movie-history-heading";
        const title=document.createElement("h2"); title.id="movieHistoryTitle"; title.textContent="История версий";
        const close=makeAction("×","secondary-button",()=>overlay.remove()); close.setAttribute("aria-label","Закрыть историю");
        heading.append(title,close);
        const intro=document.createElement("p"); intro.className="movie-history-intro"; intro.textContent="Сначала выберите версию и просмотрите её содержимое. Текущий фильм не изменится, пока вы отдельно не подтвердите восстановление.";
        const layout=document.createElement("div"); layout.className="movie-history-layout";
        const list=document.createElement("div"); list.className="movie-history-list";
        const preview=document.createElement("div"); preview.className="movie-history-preview";
        const renderPreview=()=>{
          const entry=versions[selectedIndex]||{}; const data=entry.data||{};
          preview.replaceChildren();
          const meta=document.createElement("div"); meta.className="movie-history-meta";
          meta.textContent="Версия "+(selectedIndex+1)+" из "+versions.length+" · "+movieDate(entry.savedAt);
          const name=document.createElement("h3"); name.textContent=data.name||current.name||"Без названия";
          const facts=document.createElement("p"); facts.className="movie-history-facts";
          facts.textContent=[data.genre||"Жанр не указан",data.duration||"Длительность не указана",data.frame||"Формат не указан",(data.completedSteps||[]).length+" из 4 этапов"].join(" · ");
          preview.append(meta,name,facts);
          const addSection=(label,value)=>{
            const section=document.createElement("section"); section.className="movie-history-section";
            const h=document.createElement("b"); h.textContent=label;
            const body=document.createElement("p"); body.textContent=String(value||"").trim()||"В этой версии поле пустое.";
            section.append(h,body); preview.append(section);
          };
          addSection("Сценарий",data.story||data.idea);
          addSection("Раскадровка",data.storyboard);
          addSection("Персонажи",data.characters);
          addSection("Голоса и звук",data.voices);
          addSection("План монтажа",data.edit);
          const restore=makeAction("Восстановить эту версию","primary-button",()=>{
            if(!window.confirm("Восстановить версию от "+movieDate(entry.savedAt)+"? Текущая версия будет сохранена в истории перед заменой."))return;
            const latest=movieRead(); const live=latest.find(item=>item.id===project.id); if(!live)return;
            const restored=versions[selectedIndex].data;
            addMovieVersion(live); const keepVersions=live.versions;
            latest[latest.findIndex(item=>item.id===project.id)]={...restored,versions:keepVersions,updatedAt:new Date().toISOString()};
            if(movieWrite(latest)){overlay.remove();renderMovieProjects();$("#movieFeedback").textContent="Предыдущая версия восстановлена. Текущая версия сохранена в истории.";}
          });
          restore.classList.add("movie-history-restore"); preview.append(restore);
        };
        versions.forEach((entry,index)=>{
          const button=document.createElement("button"); button.type="button"; button.className="movie-history-item";
          button.textContent=(index+1)+". "+movieDate(entry.savedAt);
          button.setAttribute("aria-pressed",String(index===selectedIndex));
          button.addEventListener("click",()=>{
            selectedIndex=index;
            [...list.children].forEach((item,i)=>item.setAttribute("aria-pressed",String(i===index)));
            renderPreview();
          });
          list.append(button);
        });
        layout.append(list,preview); dialog.append(heading,intro,layout); overlay.append(dialog);
        overlay.addEventListener("click",event=>{if(event.target===overlay)overlay.remove();});
        document.addEventListener("keydown",function closeOnEscape(event){if(event.key==="Escape"&&overlay.isConnected){overlay.remove();document.removeEventListener("keydown",closeOnEscape);}});
        document.body.append(overlay); renderPreview();
      });
      const remove=makeAction("🗑 Удалить","danger-button",()=>{
        if(!window.confirm("Удалить фильм «"+(project.name||"Без названия")+"» вместе со всей его историей версий? Это действие нельзя отменить."))return;
        const latest=movieRead().filter(item=>item.id!==project.id);
        const deletedIds=readMovieTombstones();
        if(isUuid(project.id) && !deletedIds.includes(project.id)) writeMovieTombstones([...deletedIds,project.id]);
        if(movieWrite(latest)){if(activeMovieId===project.id)activeMovieId=latest[0]?.id||null;renderMovieProjects();const workflow=$("#movieWorkflowPanel");if(workflow)workflow.hidden=true;$("#movieFeedback").textContent=authSession?.user?"Проект удалён. Удаление отправлено в облако.":"Проект удалён с этого устройства.";}
      });
      const allStagesDone=movieStages.every(stage=>(project.completedSteps||[]).includes(stage.key));
      const stageButton=makeAction((allStagesDone?"Открыть готовый проект":"Продолжить работу")+" · "+movieProgress(project), "primary-button",()=>{
        activeMovieId=project.id;
        if(allStagesDone){openMovieOverview(project.id);return;}
        const next=movieStages.findIndex(stage=>!(project.completedSteps||[]).includes(stage.key));
        openMovieStage(project.id,next<0?0:next);
      });
      actions.append(rename,edit,editDetails,copy,version,remove,stageButton); panel.append(idea,progress,date,actions);
      toggle.addEventListener("click",()=>{
        const opening=panel.hidden; panel.hidden=!opening; toggle.setAttribute("aria-expanded",String(opening)); chevron.textContent=opening?"⌃":"⌄";
        if(opening){activeMovieId=project.id;updateMovieStageCards();$$(".movie-project-card").forEach(item=>item.classList.remove("is-active"));card.classList.add("is-active");}
      });
      card.append(toggle,panel); list.append(card);
    });
    updateMovieStageCards();
  };
  $("#movieStart").addEventListener("click",()=>{
    editingMovieId=null; $("#movieForm").reset();
    const submit=$("#movieForm button[type='submit']"); if(submit)submit.innerHTML="Сохранить изменения <span>→</span>";
    $("#movieFeedback").textContent="Задайте основу нового фильма. Уже существующие проекты останутся без изменений.";
    $("#movieName").focus(); $("#movieForm").scrollIntoView({behavior:"smooth",block:"center"});
  });

  $("#movieForm").addEventListener("submit",event=>{
    event.preventDefault();
    const name=$("#movieName").value.trim(); if(!name){$("#movieFeedback").textContent="Укажите название будущего фильма.";return;}
    const projects=movieRead(); const existingIndex=editingMovieId?projects.findIndex(item=>item.id===editingMovieId):-1; const now=new Date().toISOString();
    let savedProject;
    if(existingIndex>=0){
      savedProject=projects[existingIndex]; addMovieVersion(savedProject);
      const ideaChanged=(savedProject.idea||"")!==$("#movieIdea").value.trim();
      Object.assign(savedProject,{name,idea:$("#movieIdea").value.trim(),genre:$("#movieGenre").value,seriesNumber:$("#movieSeriesNumber").value?Number($("#movieSeriesNumber").value):null,versionLabel:$("#movieVersionLabel").value.trim(),duration:Number($("#movieDuration").value),frame:$("#movieFrame").value,updatedAt:now});
      if(ideaChanged){savedProject.completedSteps=[];savedProject.workflowStep=0;}
      projects[existingIndex]=savedProject;
    }else{
      savedProject={id:movieId(),name,idea:$("#movieIdea").value.trim(),genre:$("#movieGenre").value,seriesNumber:$("#movieSeriesNumber").value?Number($("#movieSeriesNumber").value):null,versionLabel:$("#movieVersionLabel").value.trim(),duration:Number($("#movieDuration").value),frame:$("#movieFrame").value,createdAt:now,updatedAt:now,...(!authSession?.user?{guestExpiresAt:new Date(Date.now()+24*60*60*1000).toISOString()}:{}),workflowStep:0,completedSteps:[],story:"",storyboard:"",characters:"",voices:"",edit:"",versions:[]};
      projects.unshift(savedProject);
    }
    if(!movieWrite(projects))return;
    activeMovieId=savedProject.id; editingMovieId=savedProject.id;
    const submit=$("#movieForm button[type='submit']"); if(submit)submit.innerHTML="Создать проект фильма <span>→</span>";
    renderMovieProjects();
    $("#movieFeedback").textContent=existingIndex>=0?"✓ Изменения сохранены в проекте «"+name+"».":(!authSession?.user?"✓ Гостевой фильм создан. Он будет храниться в этом браузере 24 часа. Откройте «Гостевое пространство», чтобы скачать копию.":"✓ Фильм «"+name+"» создан. Форма теперь редактирует этот проект; для нового фильма нажмите «Новый фильм». Этап 1 — сценарий и раскадровка — уже доступен.");
    if(!authSession?.user) renderGuestSpace();
    const workflow=$("#movieWorkflowPanel"); if(workflow)workflow.hidden=true;
  });
  $$(".movie-tool-card[data-movie-tool]").forEach((button,index)=>button.addEventListener("click",()=>{
    if(button.disabled)return; const project=movieRead().find(item=>item.id===activeMovieId);
    if(!project){$("#movieFeedback").textContent="Сначала создайте фильм или выберите его в разделе «Мои фильмы».";return;}
    openMovieStage(project.id,index);
  }));
  const workflowStyle=document.createElement("style");
  workflowStyle.textContent=".movie-project-accordion{padding:0!important;overflow:hidden}.movie-project-toggle{display:flex;align-items:center;gap:14px;width:100%;padding:16px 18px;text-align:left;color:inherit;background:transparent;border:0;cursor:pointer}.movie-project-toggle:hover,.movie-project-card.is-active .movie-project-toggle{background:rgba(160,130,230,.08)}.movie-project-number{display:grid;place-items:center;flex:0 0 36px;height:36px;border-radius:11px;background:rgba(157,121,235,.15);color:#c8aaff;font-weight:800;font-size:12px}.movie-project-heading{display:grid;gap:5px;min-width:0;flex:1}.movie-project-heading b{font-size:15px;overflow-wrap:anywhere}.movie-project-heading small,.movie-project-date,.movie-project-progress{color:var(--muted);font-size:12px}.movie-project-chevron{font-size:22px;color:#c8aaff}.movie-project-details{padding:0 18px 18px 68px}.movie-project-details[hidden],.movie-workflow-panel[hidden]{display:none}.movie-project-details p{white-space:pre-wrap;line-height:1.65;margin:0 0 10px;color:var(--text)}.movie-project-progress{display:block;margin:8px 0}.movie-project-actions,.movie-stage-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}.movie-project-actions button,.movie-stage-actions button{min-height:40px}.movie-tool-card:disabled{opacity:.45;cursor:not-allowed;filter:grayscale(.5)}.movie-tool-card.is-locked em{font-style:normal}.movie-workflow-panel{margin:24px 0;padding:22px}.movie-workflow-head h2{margin:0 0 8px}.movie-workflow-head p,.movie-workflow-complete p{color:var(--muted);line-height:1.6}.movie-stage-fields{display:grid;gap:16px;margin-top:18px}.movie-stage-field{display:grid;gap:8px;font-weight:600}.movie-stage-field textarea{width:100%;min-height:130px;padding:13px;border:1px solid var(--border);border-radius:12px;background:var(--surface);color:var(--text);font:inherit;resize:vertical}.movie-stage-actions{justify-content:space-between}.movie-workflow-complete h2{margin-top:0}.danger-button{border:1px solid rgba(255,90,90,.35);color:#ff9292;background:rgba(255,70,70,.08);border-radius:10px;padding:9px 12px}@media(max-width:520px){.movie-project-toggle{padding:14px 12px;gap:10px}.movie-project-details{padding:0 12px 14px 58px}.movie-project-heading b{font-size:14px}.movie-project-actions button{font-size:12px;padding:8px 10px}.movie-workflow-panel{padding:15px}}";
  document.head.appendChild(workflowStyle);
  const formatGuestRemaining = expiresAt => {
    const ms = Math.max(0, Date.parse(expiresAt) - Date.now());
    const hours = Math.floor(ms / 3600000);
    const minutes = Math.floor((ms % 3600000) / 60000);
    return hours > 0 ? hours + " ч " + minutes + " мин" : minutes + " мин";
  };
  const downloadGuestProject = project => {
    const payload = { format:"PWA Studio guest project", schemaVersion:1, exportedAt:new Date().toISOString(), project };
    const blob = new Blob([JSON.stringify(payload,null,2)],{type:"application/json;charset=utf-8"});
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href=url; link.download=(String(project.name||"guest-project").replace(/[^a-zа-яё0-9_-]+/gi,"-").replace(/^-|-$/g,"")||"guest-project")+".pwa-project.json";
    document.body.append(link); link.click(); link.remove(); setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  const renderGuestSpace = () => {
    const list=$("#guestProjectList"); if(!list)return;
    const projects=authSession?.user?[]:movieRead();
    const count=$("#guestProjectCount");
    if(count)count.textContent=projects.length+(projects.length===1?" проект":projects.length>1&&projects.length<5?" проекта":" проектов");
    const notice=$("#guestExpiryNotice");
    if(notice){notice.hidden=sessionStorage.getItem("pwa-studio-guest-expired-notice")!=="1";if(!notice.hidden)sessionStorage.removeItem("pwa-studio-guest-expired-notice");}
    const warning=$("#guestExpiryWarning");
    const hasExpiring=projects.some(project=>{const left=Date.parse(project.guestExpiresAt)-Date.now();return left>0&&left<=60*60*1000;});
    if(warning)warning.hidden=!hasExpiring;
    list.replaceChildren();
    if(!projects.length){
      const empty=document.createElement("div");empty.className="movie-empty";
      const icon=document.createElement("span");icon.textContent="✧";
      const title=document.createElement("b");title.textContent="Пока здесь пусто";
      const hint=document.createElement("small");hint.textContent="Создайте фильм в Миникиностудии — он появится в этом пространстве.";
      empty.append(icon,title,hint);list.append(empty);
    }
    projects.forEach((project,index)=>{
      const card=document.createElement("article");card.className="guest-project-card";
      const head=document.createElement("div");head.className="guest-project-card-head";
      const number=document.createElement("span");number.className="movie-project-number";number.textContent=String(index+1).padStart(2,"0");
      const title=document.createElement("b");title.textContent=project.name||"Без названия";
      head.append(number,title);
      const meta=document.createElement("p");meta.textContent=[project.genre||"Жанр не указан",(project.duration||5)+" мин",project.frame||"16:9",movieProgress(project)].join(" · ");
      const expiry=document.createElement("div");expiry.className="guest-project-expiry";expiry.textContent="Осталось: "+formatGuestRemaining(project.guestExpiresAt);
      const remaining=Date.parse(project.guestExpiresAt)-Date.now();
      if(remaining>0&&remaining<=60*60*1000){expiry.textContent+=" · Скоро удаление — скачайте копию";expiry.setAttribute("role","alert");}
      const actions=document.createElement("div");actions.className="guest-project-actions";
      const open=document.createElement("button");open.type="button";open.className="primary-button";open.textContent="Продолжить фильм";open.addEventListener("click",()=>{activeMovieId=project.id;editingMovieId=project.id;navigate("movie");const next=movieStages.findIndex(stage=>!(project.completedSteps||[]).includes(stage.key));if((project.completedSteps||[]).length===4)openMovieOverview(project.id);else openMovieStage(project.id,next<0?0:next);});
      const download=document.createElement("button");download.type="button";download.className="secondary-button";download.textContent="⇩ Скачать проект";download.addEventListener("click",()=>downloadGuestProject(project));
      actions.append(open,download);card.append(head,meta,expiry,actions);list.append(card);
    });
    const archived=authSession?.user?[]:readGuestArchive();
    if(archived.length){
      const archiveHeading=document.createElement("h3");archiveHeading.textContent="Архив гостевых проектов";archiveHeading.style.margin="22px 0 10px";list.append(archiveHeading);
      archived.forEach((project,index)=>{
        const card=document.createElement("article");card.className="guest-project-card";
        const head=document.createElement("div");head.className="guest-project-card-head";
        const number=document.createElement("span");number.className="movie-project-number";number.textContent="А"+String(index+1).padStart(2,"0");
        const title=document.createElement("b");title.textContent=project.name||"Без названия";head.append(number,title);
        const meta=document.createElement("p");meta.textContent=[project.genre||"Жанр не указан",(project.duration||5)+" мин",project.frame||"16:9",movieProgress(project)].join(" · ");
        const expiry=document.createElement("div");expiry.className="guest-project-expiry";expiry.textContent="Срок хранения истёк · проект сохранён в архиве";
        const actions=document.createElement("div");actions.className="guest-project-actions";
        const restore=document.createElement("button");restore.type="button";restore.className="primary-button";restore.textContent="↶ Восстановить на 24 часа";restore.addEventListener("click",()=>{
          const current=movieRead();if(current.some(item=>item.id===project.id)){window.alert("Этот проект уже есть в активном списке.");return;}
          const restored={...project,guestExpiresAt:new Date(Date.now()+24*60*60*1000).toISOString(),updatedAt:new Date().toISOString()};const nextArchive=readGuestArchive().filter(item=>item.id!==project.id);
          if(!writeGuestArchive(nextArchive))return;
          if(!movieWrite([restored,...current])){writeGuestArchive([...nextArchive,project]);return;}
          renderGuestSpace();renderMovieProjects();
        });
        const download=document.createElement("button");download.type="button";download.className="secondary-button";download.textContent="⇩ Скачать копию";download.addEventListener("click",()=>downloadGuestProject(project));
        actions.append(restore,download);card.append(head,meta,expiry,actions);list.append(card);
      });
    }
  };
  // Import controls are static in index.html so they remain visible even if dynamic rendering changes.
  const guestImportButton=$("#guestImportButton");
  const guestImportInput=$("#guestImportInput");
  if(guestImportButton&&guestImportInput&&!guestImportButton.dataset.bound){
    guestImportButton.dataset.bound="true";
    // The native label in index.html opens the Android file picker directly.
    guestImportInput.addEventListener("change",async()=>{
      const file=guestImportInput.files?.[0];guestImportInput.value="";
      if(!file)return;
      if(authSession?.user){window.alert("Нельзя импортировать гостевой проект в аккаунт.");return;}
      if(file.size>5*1024*1024){window.alert("Файл слишком большой. Максимальный размер JSON-копии — 5 МБ.");return;}
      try{
        const importStatus=$("#guestImportStatus");
        if(importStatus){importStatus.hidden=false;importStatus.textContent="Читаем резервную копию…";}
        const raw=await new Promise((resolve,reject)=>{
          if(typeof file.text==="function"){file.text().then(resolve,reject);return;}
          const reader=new FileReader();
          reader.onload=()=>resolve(String(reader.result||""));
          reader.onerror=()=>reject(new Error("Не удалось прочитать выбранный файл."));
          reader.readAsText(file,"UTF-8");
        });
        const data=JSON.parse(raw);
        const imported=[...(Array.isArray(data?.projects)?data.projects:[]),...(Array.isArray(data?.archivedProjects)?data.archivedProjects:[]),...(data?.project?[data.project]:[])];
        if(!["PWA Studio guest project","PWA Studio guest workspace"].includes(data?.format)||!imported.length)throw new Error("Это не резервная копия PWA Studio.");
        const valid=imported.filter(item=>item&&typeof item==="object"&&!Array.isArray(item));
        if(!valid.length)throw new Error("В файле нет проектов для импорта.");
        const current=movieRead();
        const now=new Date().toISOString();
        const used=new Set(current.map(item=>item.id));
        const restored=valid.map(item=>{
          const copy={...item};
          copy.id=movieId();
          while(used.has(copy.id))copy.id=movieId();
          used.add(copy.id);
          copy.name=String(copy.name||"Импортированный фильм").slice(0,160);
          copy.idea=String(copy.idea||copy.story||"").slice(0,20000);
          copy.story=String(copy.story||copy.idea||"").slice(0,30000);
          copy.storyboard=String(copy.storyboard||"").slice(0,30000);
          copy.characters=String(copy.characters||"").slice(0,30000);
          copy.voices=String(copy.voices||"").slice(0,30000);
          copy.edit=String(copy.edit||"").slice(0,30000);
          copy.completedSteps=Array.isArray(copy.completedSteps)?copy.completedSteps.filter(key=>movieStages.some(stage=>stage.key===key)):[];
          copy.versions=Array.isArray(copy.versions)?copy.versions.slice(0,20):[];
          copy.createdAt=now;copy.updatedAt=now;
          copy.guestExpiresAt=new Date(Date.now()+24*60*60*1000).toISOString();
          copy.workflowStep=Math.max(0,Math.min(3,Number(copy.workflowStep)||0));
          return copy;
        });
        if(!movieWrite([...restored,...current]))throw new Error("Не удалось сохранить импорт. Проверьте свободное место в браузере.");
        activeMovieId=restored[0].id;
        renderGuestSpace();renderMovieProjects();
        const message="Импортировано проектов: "+restored.length+". Они будут храниться в этом браузере ещё 24 часа.";
        const status=$("#guestImportStatus");if(status){status.hidden=false;status.textContent="✓ "+message;}
        window.alert(message);
      }catch(error){
        const status=$("#guestImportStatus");if(status){status.hidden=false;status.textContent="Ошибка импорта: "+(error.message||"проверьте JSON-копию.");}
        window.alert("Не удалось импортировать файл: "+(error.message||"проверьте JSON-копию."));
      }
    });
  }
  $("#guestCreateMovie")?.addEventListener("click",()=>navigate("movie"));
  $("#guestExportAll")?.addEventListener("click",()=>{
    const projects=movieRead(); const archivedProjects=readGuestArchive();
    if(!projects.length&&!archivedProjects.length){window.alert("Пока нет гостевых проектов для скачивания.");return;}
    const blob=new Blob([JSON.stringify({format:"PWA Studio guest workspace",schemaVersion:2,exportedAt:new Date().toISOString(),projects,archivedProjects},null,2)],{type:"application/json;charset=utf-8"});
    const url=URL.createObjectURL(blob);const link=document.createElement("a");link.href=url;link.download="pwa-studio-guest-projects.json";document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
  renderGuestSpace();
  // Re-check expiry on a timer and whenever the tab becomes active again.
  const refreshGuestExpiry=()=>{
    if(authSession?.user)return;
    const before=localStorage.getItem(movieStorageKey());
    const active=movieRead();
    const after=localStorage.getItem(movieStorageKey());
    if(before!==after||!$("#view-guestspace")?.hidden)renderGuestSpace();
  };
  setInterval(refreshGuestExpiry,60000);
  window.addEventListener("focus",refreshGuestExpiry);
  document.addEventListener("visibilitychange",()=>{if(!document.hidden)refreshGuestExpiry();});
  window.addEventListener("pageshow",refreshGuestExpiry);

  // Character Library cloud backup v2: explicit, metadata-only, resumable-by-retry.
  // Local records and image Blobs are never deleted or rewritten by this operation.
  const makeCharacterUuid = () => {
    if (window.crypto?.randomUUID) return window.crypto.randomUUID();
    const bytes = new Uint8Array(16);
    window.crypto.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, value => value.toString(16).padStart(2, "0")).join("");
    return hex.slice(0,8)+"-"+hex.slice(8,12)+"-"+hex.slice(12,16)+"-"+hex.slice(16,20)+"-"+hex.slice(20);
  };
  const isCharacterUuid = value => /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value || "");
  const stableCharacterJson = value => JSON.stringify(value, (key,item) => {
    if(item&&typeof item==="object"&&!Array.isArray(item))return Object.keys(item).sort().reduce((out,name)=>(out[name]=item[name],out),{});
    return item;
  });
  const backupCharacterLibrary = async () => {
    const status=$("#characterLibraryStatus"),button=$("#backupCharacterLibrary");
    const session=authSession,ownerId=session?.user?.id,contextVersion=authContextVersion;
    const stillOwner=()=>authContextVersion===contextVersion&&authSession?.user?.id===ownerId;
    if(!ownerId||!session?.access_token){if(status)status.textContent="Для облачной копии войдите в свой аккаунт. Гостевая библиотека останется на этом устройстве.";return;}
    if(!isCharacterUuid(ownerId)){if(status)status.textContent="Не удалось проверить идентификатор аккаунта. Локальные материалы не изменены.";return;}
    if(button){button.disabled=true;button.textContent="⏳ Создаём копию…";}
    const say=message=>{if(stillOwner()&&status)status.textContent=message;};
    try{
      const localItems=readCharacterLibrary();
      if(!Array.isArray(localItems)||localItems.length>100){throw new Error("Локальная библиотека содержит недопустимое число записей.");}
      if(!localItems.length){say("Библиотека пуста — пока нечего копировать.");return;}
      say("Получаю список облачных паспортов…");
      const cloudItems=[];
      let cursor=null,pages=0;
      do{
        const query=new URLSearchParams({limit:"100"});
        if(cursor)query.set("cursor",cursor);
        const page=await apiRequest("/api/characters?"+query.toString());
        if(!stillOwner())return;
        if(!page||!Array.isArray(page.items)||!(page.next_cursor===null||typeof page.next_cursor==="string"))throw new Error("Сервер вернул неполную страницу библиотеки.");
        cloudItems.push(...page.items);
        if(cloudItems.length>10000)throw new Error("Облачная библиотека превышает безопасный предел обхода.");
        cursor=page.next_cursor;
        pages++;
        if(pages>100)throw new Error("Слишком много страниц. Операция остановлена без изменения локальных данных.");
      }while(cursor);
      const byLocalId=new Map();
      for(const item of cloudItems){
        if(!isCharacterUuid(item.source_local_id)||!isCharacterUuid(item.id))throw new Error("Облачная запись содержит некорректную связь ID.");
        if(byLocalId.has(item.source_local_id))throw new Error("Найдены повторяющиеся связи локального и облачного ID. Нужна проверка, автоматическое объединение запрещено.");
        byLocalId.set(item.source_local_id,item);
      }
      let created=0,updated=0,unchanged=0;
      for(let index=0;index<localItems.length;index++){
        if(!stillOwner())return;
        const local=localItems[index];
        if(!local||!isCharacterUuid(local.id)||typeof local.name!=="string"||!local.name.trim())throw new Error("Локальная карточка содержит некорректные данные.");
        const referenceManifest=[];
        const seenReferenceIds=new Set();
        for(const ref of [...(Array.isArray(local.referenceImages)?local.referenceImages:[]),...(Array.isArray(local.cloudBackup?.referenceManifest)?local.cloudBackup.referenceManifest:[])]){
          const refId=String(ref?.id||"").slice(0,180);
          if(!refId||seenReferenceIds.has(refId))continue;
          seenReferenceIds.add(refId);
          referenceManifest.push(ref);
          if(referenceManifest.length===6)break;
        }
        const referenceData={
          kind:local.kind==="scene"?"scene":"character",
          representation:["2d","3d","both"].includes(local.representation)?local.representation:"2d",
          voice:String(local.voice||"").slice(0,500),
          passport:{
            face:String(local.passport?.face||"").slice(0,1200),
            body:String(local.passport?.body||"").slice(0,1200),
            wardrobe:String(local.passport?.wardrobe||"").slice(0,1200),
            palette:String(local.passport?.palette||"").slice(0,1200)
          },
          referenceImages:referenceManifest.map(ref=>({
            id:String(ref.id||"").slice(0,180),name:String(ref.name||"").slice(0,120),type:String(ref.type||"").slice(0,80)
          }))
        };
        const payload={source_local_id:local.id,name:local.name.trim().slice(0,120),description:String(local.description||"").slice(0,5000),reference_data:referenceData};
        if(new TextEncoder().encode(JSON.stringify(payload.reference_data)).length>24000)throw new Error("Паспорт «"+payload.name+"» слишком велик для безопасной облачной копии.");
        const existing=byLocalId.get(local.id);
        if(!existing){
          const createdRow=await apiRequest("/api/characters",{method:"POST",body:JSON.stringify(payload)});
          if(!stillOwner())return;
          if(!createdRow||createdRow.source_local_id!==local.id||!isCharacterUuid(createdRow.id)||!Number.isInteger(createdRow.version)||createdRow.version<1)throw new Error("Сервер не подтвердил создание облачного паспорта.");
          byLocalId.set(local.id,createdRow);created++;
        }else{
          if(!Number.isInteger(existing.version)||existing.version<1)throw new Error("У облачного паспорта отсутствует версия. Обновление остановлено.");
          const same=existing.name===payload.name&&String(existing.description||"")===String(payload.description||"")&&stableCharacterJson(existing.reference_data||{})===stableCharacterJson(payload.reference_data);
          if(same){unchanged++;continue;}
          try{
            const updatedRow=await apiRequest("/api/characters/"+encodeURIComponent(existing.id),{
              method:"PATCH",body:JSON.stringify({expected_version:existing.version,name:payload.name,description:payload.description,reference_data:payload.reference_data})
            });
            if(!stillOwner())return;
            if(!updatedRow||updatedRow.id!==existing.id||updatedRow.version!==existing.version+1)throw new Error("Сервер не подтвердил новую версию паспорта.");
            byLocalId.set(local.id,updatedRow);updated++;
          }catch(error){
            if(error.status===409||error.code==="character_version_conflict"||/409|conflict|конфликт|уже измен/i.test(String(error.message)))throw new Error("Паспорт «"+payload.name+"» изменён в облаке на другом устройстве. Ничего не перезаписано; обновите данные и разрешите конфликт вручную.");
            throw error;
          }
        }
        say("Обработано "+(index+1)+" из "+localItems.length+" паспортов…");
      }
      say("Облачная копия паспортов готова: новых — "+created+", обновлено — "+updated+", без изменений — "+unchanged+". Изображения-референсы пока остаются только на этом устройстве. Локальная библиотека сохранена.");
    }catch(error){
      say("Копирование не завершено: "+error.message+" Локальные карточки и изображения сохранены; повторный запуск безопасен.");
    }finally{
      if(button){button.disabled=false;button.textContent="☁ Создать облачную копию";}
    }
  };
  $("#backupCharacterLibrary")?.addEventListener("click",backupCharacterLibrary);

  // Character Library v1: owner-scoped metadata in localStorage and image blobs in IndexedDB.
  const characterLibraryDbName = "pwa-studio-character-library-v1";
  const characterLibraryKey = () => "pwa-studio-character-library-v1:" + (authSession?.user?.id || "guest");
  const characterOwnerIsUuid = value => /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(String(value||""));
  const acquireCharacterLibraryLock = async (ownerId,contextVersion) => {
    const contextIsCurrent=()=>contextVersion===authContextVersion&&(authSession?.user?.id||"guest")===ownerId;
    const assertContext=()=>{if(!contextIsCurrent())throw new Error("Аккаунт изменился. Операция остановлена.");};
    if(ownerId==="guest")return {assertCurrent:async()=>assertContext(),release:async()=>{}};
    if(!characterOwnerIsUuid(ownerId))throw new Error("Не удалось подтвердить владельца библиотеки.");
    const api=window.PWACharacterOwnerCoordinationLock;
    if(!api)throw new Error("Защитная блокировка библиотеки недоступна. Обновите страницу и повторите попытку.");
    let lease=await api.acquire(ownerId,{ttlMs:30000}),lost=false,renewal=Promise.resolve();
    const heartbeat=setInterval(()=>{renewal=renewal.then(async()=>{try{lease=await api.renew(lease,{ttlMs:30000});}catch(_){lost=true;}});},8000);
    return {
      assertCurrent:async()=>{assertContext();await renewal;if(lost||!(await api.isCurrent(lease)))throw new Error("Защитная блокировка истекла или передана другой вкладке. Повторите действие.");assertContext();},
      release:async()=>{clearInterval(heartbeat);await renewal;try{await api.release(lease);}catch(_){}}
    };
  };
  let editingCharacterId = null;
  let removedCharacterReferenceIds = new Set();
  const openCharacterLibraryDb = () => new Promise((resolve,reject) => {
    if (!("indexedDB" in window)) { reject(new Error("IndexedDB недоступен в этом браузере.")); return; }
    const request = indexedDB.open(characterLibraryDbName,1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains("images")) request.result.createObjectStore("images",{keyPath:"id"});
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error("Не удалось открыть локальное хранилище изображений."));
  });
  const readCharacterLibrary = () => {
    try {
      const value = JSON.parse(localStorage.getItem(characterLibraryKey()) || "[]");
      return Array.isArray(value) ? value.filter(item => item && typeof item.id === "string" && typeof item.name === "string").slice(0,100) : [];
    } catch { return []; }
  };
  const saveCharacterImage = async (id,blob,ownerId) => {
    const db=await openCharacterLibraryDb();
    try {
      await new Promise((resolve,reject)=>{
        const tx=db.transaction("images","readwrite"),store=tx.objectStore("images");
        let failure=null;
        const existing=store.get(id);
        existing.onsuccess=()=>{
          if(existing.result){
            failure=new Error("Идентификатор изображения уже занят. Существующий файл, включая данные восстановления, сохранён без изменений.");
            tx.abort();
            return;
          }
          store.add({id,ownerId,blob,createdAt:new Date().toISOString()});
        };
        existing.onerror=()=>{failure=existing.error||new Error("Не удалось проверить владельца изображения.");};
        tx.oncomplete=resolve;
        tx.onerror=()=>reject(failure||tx.error||new Error("Не удалось сохранить изображение."));
        tx.onabort=()=>reject(failure||tx.error||new Error("Сохранение изображения отменено."));
      });
    } finally { db.close(); }
  };
  const getCharacterImage = async (id,ownerId) => {
    const db=await openCharacterLibraryDb();
    try {
      return await new Promise((resolve,reject)=>{
        const request=db.transaction("images","readonly").objectStore("images").get(id);
        request.onsuccess=()=>resolve(request.result?.ownerId===ownerId?request.result.blob:null);
        request.onerror=()=>reject(request.error);
      });
    } finally { db.close(); }
  };
  const deleteCharacterImage = async (id,ownerId) => {
    const raw=localStorage.getItem("pwa-studio-character-library-v1:"+ownerId);
    let cards=[];
    if(raw!==null&&raw!==""){
      try{cards=JSON.parse(raw);}catch{throw new Error("Метаданные библиотеки повреждены; изображение сохранено для безопасности.");}
      if(!Array.isArray(cards)||cards.length>100)throw new Error("Состав библиотеки не подтверждён; изображение сохранено.");
      for(const card of cards){
        if(!card||typeof card!=="object"||(card.referenceImages!=null&&!Array.isArray(card.referenceImages)))throw new Error("Структура карточки не подтверждена; изображение сохранено.");
        if((card.referenceImages||[]).some(ref=>ref&&ref.id===id))return false;
      }
    }
    const db=await openCharacterLibraryDb();
    try{return await new Promise((resolve,reject)=>{
      const tx=db.transaction("images","readwrite"),store=tx.objectStore("images"),request=store.get(id);let deleted=false;
      request.onsuccess=()=>{if(request.result?.ownerId===ownerId){store.delete(id);deleted=true;}};
      request.onerror=()=>{try{tx.abort();}catch{}};
      tx.oncomplete=()=>resolve(deleted);
      tx.onerror=()=>reject(tx.error||new Error("Не удалось удалить локальное изображение."));
      tx.onabort=()=>reject(tx.error||new Error("Удаление локального изображения отменено."));
    });}finally{db.close();}
  };
  const resetCharacterEditor = () => {
    editingCharacterId=null;
    removedCharacterReferenceIds=new Set();
    const refsPanel=$("#characterReferenceEditor");if(refsPanel)refsPanel.replaceChildren();
    ["#characterName","#characterDescription","#characterVoice","#characterFace","#characterBody","#characterWardrobe","#characterPalette"].forEach(id=>$(id).value="");
    $("#characterKind").value="character";$("#characterRepresentation").value="2d";$("#characterImages").value="";
    $("#saveCharacter").textContent="＋ Сохранить персонажа";$("#cancelCharacterEdit").hidden=true;
  };
  const renderCharacterReferenceEditor = item => {
    const panel=$("#characterReferenceEditor");if(!panel)return;
    panel.replaceChildren();
    const refs=(item.referenceImages||[]).filter(ref=>!removedCharacterReferenceIds.has(ref.id));
    if(!refs.length){const note=document.createElement("p");note.className="helper-text";note.textContent="Сохранённых референсов пока нет.";panel.append(note);return;}
    const heading=document.createElement("p");heading.className="helper-text";heading.textContent="Сохранённые референсы. Удаление вступит в силу после сохранения карточки.";panel.append(heading);
    refs.forEach(ref=>{
      const row=document.createElement("div");row.className="character-reference-row";
      const label=document.createElement("span");label.textContent=ref.name||"Изображение";
      const remove=document.createElement("button");remove.type="button";remove.className="secondary-button";remove.textContent="Убрать";
      remove.addEventListener("click",()=>{removedCharacterReferenceIds.add(ref.id);renderCharacterReferenceEditor(item);});
      row.append(label,remove);panel.append(row);
    });
  };
  const renderCharacterLibrary = async () => {
    const list=$("#characterLibraryList");if(!list)return;
    const ownerId=authSession?.user?.id||"guest";
    const contextVersion=authContextVersion;
    const query=($("#characterSearch")?.value||"").trim().toLocaleLowerCase();
    const items=readCharacterLibrary().filter(item=>!query||(item.name+" "+item.description).toLocaleLowerCase().includes(query));
    list.replaceChildren();
    if(!items.length){const empty=document.createElement("p");empty.className="helper-text";empty.textContent=query?"Ничего не найдено.":"Библиотека пока пуста. Добавьте первого персонажа.";list.append(empty);return;}
    for(const item of items){
      const card=document.createElement("article");card.className="character-card";
      const title=document.createElement("h3");title.textContent=(item.kind==="scene"?"Локация · ":"Персонаж · ")+item.name;
      const meta=document.createElement("div");meta.className="character-meta";meta.textContent=(item.representation==="both"?"2D + 3D":item.representation==="3d"?"3D-паспорт":"2D")+" · "+(item.referenceImages?.length||0)+" референсов";
      const description=document.createElement("p");description.textContent=item.description||"Описание не добавлено.";
      card.append(title,meta,description);
      if(item.passport){const passport=document.createElement("p");passport.className="character-meta";passport.textContent=["Лицо: "+(item.passport.face||"—"),"Силуэт: "+(item.passport.body||"—"),"Одежда: "+(item.passport.wardrobe||"—"),"Палитра/эмоции: "+(item.passport.palette||"—")].join(" · ");card.append(passport);}
      if(item.voice){const voice=document.createElement("p");voice.className="character-meta";voice.textContent="Голос: "+item.voice;card.append(voice);}
      const gallery=document.createElement("div");gallery.className="character-card-gallery";
      for(const ref of (item.referenceImages||[]).slice(0,6)){
        try{
          const blob=await getCharacterImage(ref.id,ownerId);
          if(contextVersion!==authContextVersion||(authSession?.user?.id||"guest")!==ownerId)return;
          if(!blob||!card.isConnected)continue;
          const img=document.createElement("img");img.alt="Референс "+item.name;img.loading="lazy";
          const url=URL.createObjectURL(blob);img.src=url;img.addEventListener("load",()=>URL.revokeObjectURL(url),{once:true});img.addEventListener("error",()=>URL.revokeObjectURL(url),{once:true});gallery.append(img);
        }catch(error){console.warn("Character image preview:",error);}
      }
      if(contextVersion!==authContextVersion||(authSession?.user?.id||"guest")!==ownerId)return;
      if(gallery.childElementCount)card.append(gallery);
      const actions=document.createElement("div");actions.className="character-card-actions";
      const edit=document.createElement("button");edit.type="button";edit.className="secondary-button";edit.textContent="Изменить";
      edit.addEventListener("click",()=>{
        editingCharacterId=item.id;removedCharacterReferenceIds=new Set();$("#characterName").value=item.name;$("#characterDescription").value=item.description||"";
        $("#characterKind").value=item.kind||"character";$("#characterRepresentation").value=item.representation||"2d";$("#characterVoice").value=item.voice||"";
        $("#characterFace").value=item.passport?.face||"";$("#characterBody").value=item.passport?.body||"";
        $("#characterWardrobe").value=item.passport?.wardrobe||"";$("#characterPalette").value=item.passport?.palette||"";
        $("#characterImages").value="";$("#saveCharacter").textContent="Сохранить изменения";$("#cancelCharacterEdit").hidden=false;
        renderCharacterReferenceEditor(item);
        $("#characterName").scrollIntoView({behavior:"smooth",block:"center"});
      });
      const remove=document.createElement("button");remove.type="button";remove.className="secondary-button";remove.textContent="Удалить";
      remove.addEventListener("click",async()=>{
        const deleteContextVersion=authContextVersion;
        const deleteOwnerId=ownerId;
        const deleteStorageKey=characterLibraryKey();
        if(!window.confirm("Удалить «"+item.name+"» и его локальные изображения?"))return;
        if(deleteContextVersion!==authContextVersion||(authSession?.user?.id||"guest")!==deleteOwnerId)return;
        let ownerLock=null;
        try{
          ownerLock=await acquireCharacterLibraryLock(deleteOwnerId,deleteContextVersion);
          await ownerLock.assertCurrent();
          const current=readCharacterLibrary(),found=current.find(x=>x.id===item.id);if(!found)return;
          const next=current.filter(x=>x.id!==item.id);
          localStorage.setItem(deleteStorageKey,JSON.stringify(next));
          await ownerLock.assertCurrent();
          const cleanup=await Promise.allSettled((found.referenceImages||[]).map(ref=>deleteCharacterImage(ref.id,deleteOwnerId)));
          await ownerLock.assertCurrent();
          const cleanupFailed=cleanup.some(result=>result.status==="rejected"||result.value===false);
          $("#characterLibraryStatus").textContent=cleanupFailed
            ?"Материал удалён из библиотеки, но часть изображений осталась в локальном хранилище. Повторите очистку позже."
            :"Материал удалён из локальной библиотеки.";
          renderCharacterLibrary();
        }catch(error){
          if(deleteContextVersion===authContextVersion&&(authSession?.user?.id||"guest")===deleteOwnerId)
            $("#characterLibraryStatus").textContent="Не удалось безопасно завершить удаление: "+error.message;
        }finally{if(ownerLock)await ownerLock.release();}
      });
      actions.append(edit,remove);card.append(actions);list.append(card);
    }
  };
  $("#characterKittyPreset")?.addEventListener("click",()=>{
    if(editingCharacterId && !window.confirm("Заменить текущие поля карточки данными стартового паспорта Катти? Сохранённая запись изменится только после нажатия «Сохранить изменения»."))return;
    editingCharacterId=null;
    removedCharacterReferenceIds=new Set();
    const refsPanel=$("#characterReferenceEditor");if(refsPanel)refsPanel.replaceChildren();
    $("#characterName").value="Катти";
    $("#characterKind").value="character";
    $("#characterRepresentation").value="both";
    $("#characterDescription").value="Добрая, выразительная мультяшная девушка с веснушками, большими зелёными глазами и длинными кудрявыми огненно-рыжими волосами. У неё тёплая улыбка, фиолетовое худи, чёрная футболка с логотипом PWA Studio, большие наушники и украшения со звёздами.";
    $("#characterFace").value="Большие зелёные глаза, заметные веснушки, добрая выразительная улыбка, длинные кудрявые огненно-рыжие волосы.";
    $("#characterBody").value="Стилизованный дружелюбный мультяшный образ. Точные пропорции и силуэт уточняются по утверждённым референсам.";
    $("#characterWardrobe").value="Фиолетовое худи, чёрная футболка с логотипом PWA Studio, большие наушники, украшения со звёздами.";
    $("#characterPalette").value="Огненно-рыжий, фиолетовый и чёрный; зелёные глаза. Эмоции: доброжелательность, любопытство, воодушевление.";
    $("#characterVoice").value="";
    $("#characterImages").value="";
    $("#saveCharacter").textContent="＋ Сохранить персонажа";
    $("#cancelCharacterEdit").hidden=false;
    $("#characterLibraryStatus").textContent="Стартовый паспорт Катти заполнен. Добавьте утверждённые изображения-референсы и нажмите «Сохранить персонажа».";
    $("#characterName").scrollIntoView({behavior:"smooth",block:"center"});
  });
  $("#saveCharacter")?.addEventListener("click",async()=>{
    const ownerId=authSession?.user?.id||"guest",contextVersion=authContextVersion,storageKey=characterLibraryKey();
    const name=$("#characterName").value.trim(),description=$("#characterDescription").value.trim();
    const kind=$("#characterKind").value,representation=$("#characterRepresentation").value,files=Array.from($("#characterImages").files||[]);
    if(!name||!description){$("#characterLibraryStatus").textContent="Укажите имя и основное описание.";return;}
    if(!["character","scene"].includes(kind)||!["2d","3d","both"].includes(representation)){return;}
    const current=readCharacterLibrary(),existing=editingCharacterId?current.find(x=>x.id===editingCharacterId):null;
    if(editingCharacterId&&!existing){resetCharacterEditor();$("#characterLibraryStatus").textContent="Запись больше не найдена. Обновите библиотеку.";return;}
    if(!existing&&current.length>=100){$("#characterLibraryStatus").textContent="Достигнут лимит в 100 материалов.";return;}
    const retainedReferences=(existing?.referenceImages||[]).filter(ref=>!removedCharacterReferenceIds.has(ref.id));
    if(files.length+retainedReferences.length>6){$("#characterLibraryStatus").textContent="У одного материала может быть не более 6 референсов.";return;}
    if(files.some(file=>!["image/png","image/jpeg","image/webp"].includes(file.type)||file.size>8*1024*1024)){ $("#characterLibraryStatus").textContent="Поддерживаются PNG, JPEG и WebP до 8 МБ каждый.";return; }
    const id=existing?.id||makeCharacterUuid();
    const refs=files.map(file=>({id:id+"-"+(crypto.randomUUID?crypto.randomUUID():Date.now().toString(36)+Math.random().toString(36).slice(2)),name:file.name.slice(0,120),type:file.type}));
    const updated={...(existing||{}),id,name:name.slice(0,80),description:description.slice(0,5000),kind,representation,voice:$("#characterVoice").value.trim().slice(0,500),
      passport:{face:$("#characterFace").value.trim().slice(0,1200),body:$("#characterBody").value.trim().slice(0,1200),wardrobe:$("#characterWardrobe").value.trim().slice(0,1200),palette:$("#characterPalette").value.trim().slice(0,1200)},
      referenceImages:[...retainedReferences,...refs],createdAt:existing?.createdAt||new Date().toISOString(),updatedAt:new Date().toISOString()};
    const button=$("#saveCharacter");button.disabled=true;
    const savedImageIds=[];
    let metadataCommitted=false,ownerLock=null;
    try{
      ownerLock=await acquireCharacterLibraryLock(ownerId,contextVersion);
      await ownerLock.assertCurrent();
      const freshLibrary=readCharacterLibrary();
      if(JSON.stringify(freshLibrary)!==JSON.stringify(current))throw new Error("Библиотека изменилась в другой вкладке. Обновите список и повторите сохранение.");
      for(let i=0;i<files.length;i++){
        await ownerLock.assertCurrent();
        if(contextVersion!==authContextVersion||(authSession?.user?.id||"guest")!==ownerId)
          throw new Error("Аккаунт изменился во время сохранения. Повторите действие в текущем аккаунте.");
        await saveCharacterImage(refs[i].id,files[i],ownerId);
        savedImageIds.push(refs[i].id);
      }
      if(contextVersion!==authContextVersion||(authSession?.user?.id||"guest")!==ownerId)
        throw new Error("Аккаунт изменился во время сохранения. Локальная карточка не была записана в другой аккаунт.");
      const next=existing?current.map(x=>x.id===id?updated:x):[updated,...current];
      await ownerLock.assertCurrent();
      localStorage.setItem(storageKey,JSON.stringify(next));
      metadataCommitted=true;
      let cleanupWarning="";
      if(existing&&removedCharacterReferenceIds.size){
        try{
          await ownerLock.assertCurrent();
          const cleanup=await Promise.all([...removedCharacterReferenceIds].map(refId=>deleteCharacterImage(refId,ownerId)));
          if(cleanup.some(deleted=>deleted===false))cleanupWarning=" Некоторые изображения оставлены: они ещё используются другими карточками.";
        }catch(cleanupError){cleanupWarning=" Карточка сохранена, но часть старых файлов не удалось безопасно очистить: "+cleanupError.message;}
      }
      if(contextVersion!==authContextVersion||(authSession?.user?.id||"guest")!==ownerId)return;
      resetCharacterEditor();$("#characterLibraryStatus").textContent="«"+name+"» сохранён в библиотеке этого браузера."+cleanupWarning;
      await renderCharacterLibrary();
    }catch(error){
      let cleanupWarning="";
      if(!metadataCommitted&&savedImageIds.length){
        let cleanupAllowed=false;
        try{await ownerLock?.assertCurrent();cleanupAllowed=true;}catch(_){}
        if(cleanupAllowed){
          const cleanup=await Promise.allSettled(savedImageIds.map(imageId=>deleteCharacterImage(imageId,ownerId)));
          if(cleanup.some(result=>result.status==="rejected"||result.value===false))
            cleanupWarning=" Часть временных изображений оставлена: очистка не подтвердила безопасность удаления.";
        }else cleanupWarning=" Временные изображения оставлены, потому что контекст аккаунта или блокировка изменились.";
      }
      if(contextVersion===authContextVersion&&(authSession?.user?.id||"guest")===ownerId)
        $("#characterLibraryStatus").textContent="Не удалось завершить сохранение: "+error.message+(metadataCommitted?" Карточка уже записана; проверьте состояние библиотеки.":cleanupWarning||" Временные изображения очищены.");
    }finally{if(ownerLock)await ownerLock.release();if(contextVersion===authContextVersion&&(authSession?.user?.id||"guest")===ownerId)button.disabled=false;}
  });
  $("#cancelCharacterEdit")?.addEventListener("click",()=>{resetCharacterEditor();$("#characterLibraryStatus").textContent="Редактирование отменено.";});
  $("#characterSearch")?.addEventListener("input",renderCharacterLibrary);
  window.addEventListener("pwa-studio-auth-changed",()=>{resetCharacterEditor();renderCharacterLibrary();});
  renderCharacterLibrary();

  // Narrow bridge for the isolated, read-only cloud restore review module.
  window.PWAStudioCharacterRestoreBridge = Object.freeze({
    getSession: () => authSession,
    getContextVersion: () => authContextVersion,
    getLocalItems: () => readCharacterLibrary(),
    isCurrent: (ownerId, version) => !!ownerId && authContextVersion === version && authSession?.user?.id === ownerId,
    apiRequest
  });

  renderMovieProjects();

  // Store only the backend URL in this browser; provider secrets stay server-side.
  const apiUrlInput = $("#backendUrl");
  const apiStatus = $("#backendStatus");
  if (apiUrlInput) apiUrlInput.value = getApiBase();
  const checkBackend = async () => {
    apiStatus.textContent = "Проверяем соединение…";
    try {
      const data = await apiRequest("/api/health");
      apiStatus.textContent = "API доступен · " + data.service + " · " + data.ai_provider + " · ключ настроен: " + (data.ai_configured ? "да" : "нет") + ".";
    } catch (error) {
      apiStatus.textContent = error.message;
    }
  };
  $("#saveBackend").addEventListener("click", () => {
    const value = apiUrlInput.value.trim().replace(/\/+$/, "");
    if (value && !/^https:\/\//i.test(value) && !/^http:\/\/localhost(?::\d+)?$/i.test(value) && !/^http:\/\/127\.0\.0\.1(?::\d+)?$/i.test(value)) {
      apiStatus.textContent = "Укажите полный адрес API с https:// (для локальной разработки допустим localhost).";
      return;
    }
    localStorage.setItem(API_URL_KEY, value);
    apiStatus.textContent = value ? "Адрес сохранён. Проверяем соединение…" : "Адрес API очищен.";
    if (value) checkBackend();
  });
  $("#testBackend").addEventListener("click", checkBackend);

  if ("serviceWorker" in navigator && location.protocol.startsWith("http")) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("./sw.js").catch(error => console.warn("PWA service worker:", error));
    });
  }
})();