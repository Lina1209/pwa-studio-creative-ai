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
  let resetMovieWorkspaceForAuthChange = null;
  let activeAssistantConversationId = null;
  let assistantHistoryBusy = false;
  let assistantUserId = null;
  let activeMessageThreadId = null;
  let activeMessagePartnerId = null;
  let conversationsCache = [];
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
    if (nextUserId !== assistantUserId) {
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
      const directMessageList = $("#directMessageList"); if (directMessageList) directMessageList.replaceChildren();
      const directMessageForm = $("#directMessageForm"); if (directMessageForm) directMessageForm.hidden = true;
      const conversationTitle = $("#conversationTitle"); if (conversationTitle) conversationTitle.textContent = "Выберите диалог";
      activeMessageThreadId = null;
      activeMessagePartnerId = null;
      assistantUserId = nextUserId;
      authContextVersion += 1;
      resetMovieWorkspaceForAuthChange?.();
      activeAssistantConversationId = null;
      const history = $("#assistantHistoryList");
      const messages = $("#assistantMessages");
      const status = $("#assistantHistoryStatus");
      if (history) history.replaceChildren();
      if (messages) messages.replaceChildren();
      if (status) status.textContent = nextUserId ? "Загружаем историю нового аккаунта…" : "Войдите в аккаунт, чтобы сохранять историю диалогов.";
    }
    authSession = session;
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
      const topAvatar = $(".top-avatar");
      if (topAvatar) topAvatar.textContent = "L";
    }
  };
  if (!supabaseClient) {
    authGate.hidden = false;
    setAuthMessage("Не найдена конфигурация Supabase. Проверьте файл supabase-config.js.", true);
  } else {
    // A session event may arrive before getSession() resolves. Do not let a
    // late bootstrap response overwrite the newer auth state from the listener.
    const bootstrapAuthVersion = authContextVersion;
    supabaseClient.auth.getSession().then(({data,error}) => {
      if (bootstrapAuthVersion !== authContextVersion) return;
      if (error) setAuthMessage(error.message, true);
      refreshAuthUI(data?.session || null);
      setTimeout(() => { if (typeof renderMovieProjects === "function") renderMovieProjects(); if (typeof loadMovieProjectsFromCloud === "function") loadMovieProjectsFromCloud(); if (typeof loadAccountRole === "function") loadAccountRole(); if (typeof loadNotifications === "function") loadNotifications(); if (typeof loadConversations === "function") loadConversations(); if (typeof loadCommunityProfile === "function") loadCommunityProfile(); if (typeof renderAssistantHistory === "function") renderAssistantHistory(); }, 0);
    }).catch(error => {
      if (bootstrapAuthVersion === authContextVersion) setAuthMessage(error.message || "Не удалось восстановить сессию.", true);
    });
    supabaseClient.auth.onAuthStateChange((_event, session) => { authContextVersion += 1; refreshAuthUI(session); setTimeout(() => { loadAccountRole(); if (typeof loadNotifications === "function") loadNotifications(); if (typeof loadConversations === "function") loadConversations(); if (typeof renderMovieProjects === "function") renderMovieProjects(); if (typeof loadMovieProjectsFromCloud === "function") loadMovieProjectsFromCloud(); if (typeof renderAssistantHistory === "function") renderAssistantHistory(); }, 0); });
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
    if (!supabaseClient) return;
    const {error} = await supabaseClient.auth.signOut();
    if (error) setAuthMessage(error.message, true);
    else { refreshAuthUI(null); setAuthMode("login"); }
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
    if (!response.ok) throw new Error(data.detail || "Ошибка API (" + response.status + ").");
    return data;
  };


  const communityFeedback = message => { const el=$("#communityProfileFeedback"); if(el)el.textContent=message; };
  const loadCommunityProfile = async () => {
    const version=authContextVersion,userId=authSession?.user?.id;
    const panel=$("#communityPanel");
    if(!panel)return;
    panel.hidden=!userId;
    if(!userId)return;
    try{
      const profile=await apiRequest("/api/community/profile");
      if(version!==authContextVersion||authSession?.user?.id!==userId)return;
      $("#communityDisplayName").value=profile.display_name||"";
      $("#communityUsername").value=profile.username||"";
      $("#communityBio").value=profile.bio||"";
      $("#communityPublic").checked=profile.visibility==="public";
      $("#communityListed").checked=!!profile.show_in_directory;
      communityFeedback("Профиль загружен. Управляйте публичностью в настройках ниже.");
    }catch(error){if(version===authContextVersion)communityFeedback("Не удалось загрузить профиль: "+error.message);}
  };
  $("#communityProfileForm")?.addEventListener("submit",async event=>{
    event.preventDefault();
    if(!authSession?.user)return;
    const form=event.currentTarget,button=form.querySelector('button[type="submit"]');
    const version=authContextVersion;
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
    }catch(error){if(version===authContextVersion)communityFeedback("Не удалось сохранить профиль: "+error.message);}
    finally{button.disabled=false;}
  });
  const renderCommunityResults = profiles => {
    const list=$("#communityResults");if(!list)return;
    list.replaceChildren();
    if(!profiles.length){list.append(adminNode("div","admin-empty","По этому запросу авторы не найдены."));return;}
    profiles.forEach(profile=>{
      const card=adminNode("article","community-user-card");
      const avatar=adminNode("div","community-user-avatar",(profile.display_name||"?").trim().charAt(0).toUpperCase());
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
    if(!authSession?.user)return;
    const q=$("#communitySearchInput").value.trim();
    if(q.length<2){$("#communityResults").replaceChildren(adminNode("div","admin-empty","Введите не менее 2 символов."));return;}
    const version=authContextVersion,userId=authSession.user.id;
    $("#communityResults").replaceChildren(adminNode("div","admin-empty","Ищем авторов…"));
    try{
      const profiles=await apiRequest("/api/community/users?q="+encodeURIComponent(q));
      if(version!==authContextVersion||authSession?.user?.id!==userId)return;
      renderCommunityResults(profiles);
    }catch(error){if(version===authContextVersion)$("#communityResults").replaceChildren(adminNode("div","admin-empty","Поиск недоступен: "+error.message));}
  };
  const openCommunityProfile = async profileUserId => {
    const version=authContextVersion,userId=authSession?.user?.id;
    if(!userId)return;
    const box=$("#communityPublicProfile");
    box.hidden=false;box.replaceChildren(adminNode("div","admin-empty","Загружаем карточку автора…"));
    try{
      const profile=await apiRequest("/api/community/profiles/"+encodeURIComponent(profileUserId));
      if(version!==authContextVersion||authSession?.user?.id!==userId)return;
      box.replaceChildren();
      const head=adminNode("div","community-profile-card");
      head.append(adminNode("div","community-user-avatar community-user-avatar-large",(profile.display_name||"?").trim().charAt(0).toUpperCase()));
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
    }catch(error){if(version===authContextVersion)box.replaceChildren(adminNode("div","admin-empty","Карточка недоступна: "+error.message));}
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
  const loadNotifications = async () => {
    const panel = $("#notificationPanel");
    if (!panel) return;
    if (!authSession?.user) { panel.hidden = true; return; }
    panel.hidden = false;
    const version = authContextVersion, userId = authSession.user.id;
    notificationFeedback("Проверяем новые сообщения…");
    const list = $("#notificationList");
    if (list) list.replaceChildren(adminNode("div","admin-empty","Загружаем уведомления…"));
    try {
      const items = await apiRequest("/api/notifications");
      if (version !== authContextVersion || authSession?.user?.id !== userId) return;
      renderNotifications(items);
      notificationFeedback(items.length ? "Уведомления синхронизированы с вашим аккаунтом." : "Новых сообщений пока нет.");
    } catch (error) {
      if (version !== authContextVersion || authSession?.user?.id !== userId) return;
      notificationFeedback("Не удалось загрузить уведомления: " + error.message);
      if (list) list.replaceChildren(adminNode("div","admin-empty","Центр уведомлений временно недоступен."));
    }
  };
  const markOneNotificationRead = async (id, button) => {
    const version = authContextVersion, userId = authSession?.user?.id;
    if (!userId) return;
    button.disabled = true;
    try {
      await apiRequest("/api/notifications/" + encodeURIComponent(id) + "/read", {method:"POST"});
      if (version === authContextVersion && authSession?.user?.id === userId) loadNotifications();
    } catch (error) {
      if (version === authContextVersion) notificationFeedback("Не удалось отметить уведомление: " + error.message);
      button.disabled = false;
    }
  };
  $("#notificationRefresh")?.addEventListener("click", loadNotifications);
  $("#notificationReadAll")?.addEventListener("click", async event => {
    const button = event.currentTarget, version = authContextVersion, userId = authSession?.user?.id;
    if (!userId) return;
    button.disabled = true;
    try {
      await apiRequest("/api/notifications/read-all", {method:"POST"});
      if (version === authContextVersion && authSession?.user?.id === userId) loadNotifications();
    } catch (error) {
      if (version === authContextVersion) notificationFeedback("Не удалось обновить уведомления: " + error.message);
      button.disabled = false;
    }
  });

  const messagesFeedback = message => { const el = $("#messagesFeedback"); if (el) el.textContent = message; };
  const messagePartnerId = thread => thread.user_a_id === authSession?.user?.id ? thread.user_b_id : thread.user_a_id;
  const renderConversations = threads => {
    conversationsCache = Array.isArray(threads) ? threads : [];
    const list = $("#conversationList"); if (!list) return;
    list.replaceChildren();
    if (!threads.length) { list.append(adminNode("div","admin-empty","Пока нет диалогов. Начните переписку с первого сообщения.")); return; }
    threads.forEach(thread => {
      const partnerId = messagePartnerId(thread);
      const button = adminNode("button","conversation-button");
      button.type = "button";
      button.setAttribute("aria-current",String(thread.id === activeMessageThreadId));
      button.append(adminNode("b","", "Пользователь · "+partnerId.slice(0,8)+"…"));
      button.append(adminNode("small","",thread.last_message_at ? "Последнее сообщение · "+formatAdminDate(thread.last_message_at) : "Диалог создан"));
      button.addEventListener("click",()=>openConversation(thread.id,partnerId));
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
    if(list)list.replaceChildren(adminNode("div","admin-empty","Загружаем диалоги…"));
    try{
      const threads=await apiRequest("/api/conversations");
      if(version!==authContextVersion||authSession?.user?.id!==userId)return;
      renderConversations(Array.isArray(threads)?threads:[]);
      if(activeMessageThreadId && !(threads||[]).some(item=>item.id===activeMessageThreadId)){
        activeMessageThreadId=null;activeMessagePartnerId=null;
        $("#directMessageForm").hidden=true;
        $("#conversationTitle").textContent="Выберите диалог";
        $("#directMessageList").replaceChildren(adminNode("div","admin-empty","Выберите диалог из списка."));
      }
      messagesFeedback(threads.length ? "Диалоги загружены. Переписка доступна только её участникам." : "Создайте первый диалог.");
    }catch(error){
      if(version!==authContextVersion||authSession?.user?.id!==userId)return;
      messagesFeedback("Не удалось загрузить диалоги: "+error.message);
      if(list)list.replaceChildren(adminNode("div","admin-empty","Список диалогов временно недоступен."));
    }
  };
  const loadConversationMessages = async (threadId) => {
    const version=authContextVersion,userId=authSession?.user?.id;
    if(!userId||!threadId)return;
    const list=$("#directMessageList");
    if(list)list.replaceChildren(adminNode("div","admin-empty","Загружаем сообщения…"));
    try{
      const messages=await apiRequest("/api/conversations/"+encodeURIComponent(threadId)+"/messages");
      if(version!==authContextVersion||authSession?.user?.id!==userId||activeMessageThreadId!==threadId)return;
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
            try{await apiRequest("/api/messages/"+encodeURIComponent(message.id),{method:"PATCH",body:JSON.stringify({body:next.trim()})});loadConversationMessages(threadId);}
            catch(error){messagesFeedback("Не удалось изменить сообщение: "+error.message);}
          });
          const remove=adminNode("button","message-action is-danger","Удалить у себя");remove.type="button";
          remove.addEventListener("click",async()=>{
            if(!window.confirm("Скрыть это сообщение только в вашей переписке? У собеседника оно останется."))return;
            try{await apiRequest("/api/messages/"+encodeURIComponent(message.id),{method:"DELETE"});loadConversationMessages(threadId);}
            catch(error){messagesFeedback("Не удалось удалить сообщение: "+error.message);}
          });
          actions.append(edit,remove);item.append(actions);
        }
        list.append(item);
      });
      list.scrollTop=list.scrollHeight;
      await apiRequest("/api/conversations/"+encodeURIComponent(threadId)+"/read",{method:"POST"});
      if(version===authContextVersion&&authSession?.user?.id===userId)loadConversations();
    }catch(error){
      if(version===authContextVersion&&authSession?.user?.id===userId)messagesFeedback("Не удалось загрузить переписку: "+error.message);
    }
  };
  const openConversation = (threadId,partnerId) => {
    activeMessageThreadId=threadId;activeMessagePartnerId=partnerId;
    $("#conversationTitle").textContent="Диалог с пользователем "+partnerId;
    $("#directMessageForm").hidden=false;
    const blockButton=$("#blockConversationUser");if(blockButton){blockButton.hidden=false;blockButton.textContent="Заблокировать";blockButton.disabled=false;}
    renderConversations(conversationsCache);
    loadConversationMessages(threadId);
  };
  $("#blockConversationUser")?.addEventListener("click",async()=>{
    if(!activeMessagePartnerId||!authSession?.user)return;
    if(!window.confirm("Заблокировать пользователя? Он не сможет отправлять вам сообщения, и вы не сможете писать ему."))return;
    const button=$("#blockConversationUser"),version=authContextVersion;
    button.disabled=true;
    try{
      await apiRequest("/api/blocks",{method:"POST",body:JSON.stringify({user_id:activeMessagePartnerId})});
      if(version!==authContextVersion)return;
      $("#directMessageForm").hidden=true;
      messagesFeedback("Пользователь заблокирован. Переписка сохранена, новые сообщения между вами недоступны.");
      button.textContent="Заблокирован";
    }catch(error){messagesFeedback("Не удалось заблокировать пользователя: "+error.message);button.disabled=false;}
  });
  $("#messagesRefresh")?.addEventListener("click",()=>{loadConversations();if(activeMessageThreadId)loadConversationMessages(activeMessageThreadId);});
  $("#newConversationForm")?.addEventListener("submit",async event=>{
    event.preventDefault();
    if(!authSession?.user)return;
    const form=event.currentTarget,button=form.querySelector('button[type="submit"]');
    const recipient=$("#messageRecipientId").value.trim(),body=$("#messageFirstText").value.trim();
    if(!recipient||!body)return;
    const version=authContextVersion,userId=authSession.user.id;
    button.disabled=true;messagesFeedback("Открываем защищённый диалог…");
    try{
      const sent=await apiRequest("/api/conversations/"+encodeURIComponent(recipient)+"/messages",{method:"POST",body:JSON.stringify({body})});
      if(version!==authContextVersion||authSession?.user?.id!==userId)return;
      form.reset();activeMessageThreadId=sent.thread_id;activeMessagePartnerId=recipient;
      $("#conversationTitle").textContent="Диалог с пользователем "+recipient;
      $("#directMessageForm").hidden=false;
      await loadConversations();await loadConversationMessages(activeMessageThreadId);
      messagesFeedback("Первое сообщение отправлено.");
    }catch(error){if(version===authContextVersion)messagesFeedback("Не удалось начать диалог: "+error.message);}
    finally{button.disabled=false;}
  });
  $("#directMessageForm")?.addEventListener("submit",async event=>{
    event.preventDefault();
    if(!authSession?.user||!activeMessagePartnerId)return;
    const form=event.currentTarget,button=form.querySelector('button[type="submit"]');
    const body=$("#directMessageText").value.trim();if(!body)return;
    const version=authContextVersion,userId=authSession.user.id,threadId=activeMessageThreadId;
    button.disabled=true;
    try{
      await apiRequest("/api/conversations/"+encodeURIComponent(activeMessagePartnerId)+"/messages",{method:"POST",body:JSON.stringify({body})});
      if(version!==authContextVersion||authSession?.user?.id!==userId||activeMessageThreadId!==threadId)return;
      $("#directMessageText").value="";
      await loadConversationMessages(threadId);
    }catch(error){if(version===authContextVersion)messagesFeedback("Не удалось отправить сообщение: "+error.message);}
    finally{button.disabled=false;}
  });

  const reportFeedback = message => { const el = $("#reportFeedback"); if (el) el.textContent = message; };
  $("#userReportForm")?.addEventListener("submit", async event => {
    event.preventDefault();
    if (!authSession?.user) { setAuthMode("login"); authGate.hidden = false; reportFeedback("Сначала войдите в аккаунт, чтобы отправить обращение."); return; }
    const form = event.currentTarget;
    const button = form.querySelector('button[type="submit"]');
    const version = authContextVersion;
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
      if (version !== authContextVersion) return;
      form.reset();
      reportFeedback("✓ Обращение принято. Номер: " + result.id + ". Статус: " + (result.status || "new") + ". Спасибо, что помогаете поддерживать безопасную среду.");
    } catch (error) {
      if (version === authContextVersion) reportFeedback("Не удалось отправить обращение: " + error.message);
    } finally {
      button.disabled = false;
    }
  });

  const adminFeedback = message => { const el = $("#adminFeedback"); if (el) el.textContent = message; };
  const adminNode = (tag, className, value) => { const el = document.createElement(tag); if (className) el.className = className; if (value !== undefined) el.textContent = value; return el; };
  const formatAdminDate = value => { if (!value) return "Без срока"; const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString("ru-RU"); };
  const analyticsLocalInputValue = date => {
    const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
    return local.toISOString().slice(0, 16);
  };
  const setAdminAnalyticsDefaultRange = () => {
    const end = new Date();
    const start = new Date(end.getTime() - 7 * 24 * 60 * 60 * 1000);
    const startInput = $("#adminAnalyticsStart"), endInput = $("#adminAnalyticsEnd");
    if (startInput && !startInput.value) startInput.value = analyticsLocalInputValue(start);
    if (endInput && !endInput.value) endInput.value = analyticsLocalInputValue(end);
  };
  const renderAdminAnalyticsUnavailable = message => {
    ["adminAnalyticsRegistrations","adminAnalyticsProjects","adminAnalyticsAI"].forEach(id => { const el=$("#"+id); if(el)el.textContent="—"; });
    const feedback=$("#adminAnalyticsFeedback"); if(feedback)feedback.textContent=message;
  };
  let adminAnalyticsRequestId = 0;
  const loadAdminAnalytics = async () => {
    const panel=$("#adminPanel"), section=$("#adminAnalyticsSection");
    if(!authSession?.user || !panel || panel.hidden || !section)return;
    const version=authContextVersion, userId=authSession.user.id;
    const startValue=$("#adminAnalyticsStart")?.value, endValue=$("#adminAnalyticsEnd")?.value;
    if(!startValue || !endValue){renderAdminAnalyticsUnavailable("Выберите начало и конец периода.");return;}
    const start=new Date(startValue), end=new Date(endValue);
    if(Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || start>=end){renderAdminAnalyticsUnavailable("Проверьте период: дата окончания должна быть позже начала.");return;}
    if(end-start>31*24*60*60*1000){renderAdminAnalyticsUnavailable("Можно выбрать период не длиннее 31 дня.");return;}
    const requestId=++adminAnalyticsRequestId;
    const button=$("#adminAnalyticsLoad"); if(button)button.disabled=true;
    const feedback=$("#adminAnalyticsFeedback"); if(feedback)feedback.textContent="Загружаем агрегированную статистику…";
    try{
      const query=new URLSearchParams({start_at:start.toISOString(),end_at:end.toISOString()});
      const result=await apiRequest("/api/admin/analytics?"+query.toString());
      if(version!==authContextVersion || authSession?.user?.id!==userId || panel.hidden)return;
      const metrics=result.metrics||{};
      $("#adminAnalyticsRegistrations").textContent=Number.isSafeInteger(metrics.registered_accounts)?metrics.registered_accounts.toLocaleString("ru-RU"):"—";
      $("#adminAnalyticsProjects").textContent=Number.isSafeInteger(metrics.accounts_with_project_updates)?metrics.accounts_with_project_updates.toLocaleString("ru-RU"):"—";
      $("#adminAnalyticsAI").textContent=Number.isSafeInteger(metrics.accounts_with_successful_ai_usage)?metrics.accounts_with_successful_ai_usage.toLocaleString("ru-RU"):"—";
      if(feedback)feedback.textContent="Период: "+formatAdminDate(result.period?.start_at)+" — "+formatAdminDate(result.period?.end_at)+". Получены только сводные числа.";
      const note=$("#adminAnalyticsNote");
      if(note && result.data_quality?.note)note.textContent=result.data_quality.note;
    }catch(error){
      if(version!==authContextVersion || authSession?.user?.id!==userId)return;
      renderAdminAnalyticsUnavailable(error.message.includes("not installed") || error.message.includes("not available") ? "Статистика пока не подключена к базе: миграция аналитики ещё не установлена. Остальные разделы кабинета работают отдельно." : "Статистика временно недоступна: "+error.message);
    }finally{
      if(requestId===adminAnalyticsRequestId && button)button.disabled=false;
    }
  };
  setAdminAnalyticsDefaultRange();
  $("#adminAnalyticsFilters")?.addEventListener("submit",event=>{event.preventDefault();loadAdminAnalytics();});
  $("#adminAnalyticsWeek")?.addEventListener("click",()=>{const start=$("#adminAnalyticsStart"),end=$("#adminAnalyticsEnd");if(start)start.value="";if(end)end.value="";setAdminAnalyticsDefaultRange();loadAdminAnalytics();});
  let adminAuditPage = 1;
  const loadAdminWorkspace = async () => {
    const reportsList = $("#adminReportsList"), suspensionsList = $("#adminSuspensionsList");
    if (!authSession?.user || !$("#adminPanel") || $("#adminPanel").hidden) return;
    adminFeedback("Обновляем данные модерации…");
    if (reportsList) reportsList.replaceChildren(adminNode("div","admin-empty","Загружаем жалобы…"));
    if (suspensionsList) suspensionsList.replaceChildren(adminNode("div","admin-empty","Загружаем ограничения…"));
    const version = authContextVersion;
    try {
      const [reports, suspensions] = await Promise.all([
        apiRequest("/api/admin/reports"),
        apiRequest("/api/admin/suspensions")
      ]);
      if (version !== authContextVersion || !authSession?.user) return;
      renderAdminReports(Array.isArray(reports) ? reports : []);
      renderAdminSuspensions(Array.isArray(suspensions) ? suspensions : []);
      await loadAdminAuditLog();
      await loadAdminAnalytics();
      adminFeedback("Данные обновлены. Действия модерации записываются в журнал.");
    } catch (error) {
      if (version !== authContextVersion) return;
      adminFeedback("Не удалось загрузить данные: " + error.message);
      if (reportsList) reportsList.replaceChildren(adminNode("div","admin-empty","Список жалоб временно недоступен."));
      if (suspensionsList) suspensionsList.replaceChildren(adminNode("div","admin-empty","Список ограничений временно недоступен."));
    }
  };
  const renderAdminReports = reports => {
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
        const version=authContextVersion, userId=authSession?.user?.id;
        if(!userId)return;
        save.disabled=true;
        try {
          await apiRequest("/api/admin/reports/"+encodeURIComponent(report.id),{method:"PATCH",body:JSON.stringify({status:status.value,moderator_note:note.value.trim()||null})});
          if(version!==authContextVersion || authSession?.user?.id!==userId)return;
          adminFeedback("Решение по жалобе сохранено.");
          await loadAdminWorkspace();
        } catch(error){
          if(version===authContextVersion && authSession?.user?.id===userId){adminFeedback("Не удалось сохранить решение: "+error.message);save.disabled=false;}
        }
      });
      actions.append(status,save); card.append(note,actions); list.append(card);
    });
  };
  const renderAdminSuspensions = suspensions => {
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
        revoke.addEventListener("click",async()=>{
          if(!confirm("Отменить это ограничение доступа?"))return;
          const version=authContextVersion, userId=authSession?.user?.id;
          if(!userId)return;
          revoke.disabled=true;
          try{
            await apiRequest("/api/admin/suspensions/revoke",{method:"POST",body:JSON.stringify({suspension_id:item.id})});
            if(version!==authContextVersion || authSession?.user?.id!==userId)return;
            adminFeedback("Ограничение отменено.");
            await loadAdminWorkspace();
          }catch(error){
            if(version===authContextVersion && authSession?.user?.id===userId){adminFeedback("Не удалось отменить: "+error.message);revoke.disabled=false;}
          }
        });
        card.append(revoke);
      }
      list.append(card);
    });
  };
  const auditFeedback = message => { const el=$("#adminAuditFeedback"); if(el)el.textContent=message; };
  const loadAdminAuditLog = async () => {
    const list=$("#adminAuditList");
    if(!list || !authSession?.user || $("#adminPanel")?.hidden)return;
    const version=authContextVersion, userId=authSession.user.id;
    const params=new URLSearchParams({page:String(adminAuditPage),page_size:"25"});
    const values={actor_user_id:$("#adminAuditActor")?.value.trim(),target_user_id:$("#adminAuditTarget")?.value.trim(),action:$("#adminAuditAction")?.value.trim(),entity_type:$("#adminAuditEntity")?.value.trim()};
    Object.entries(values).forEach(([key,value])=>{if(value)params.set(key,value);});
    list.replaceChildren(adminNode("div","admin-empty","Загружаем журнал действий…"));
    auditFeedback("Получаем записи журнала…");
    try{
      const data=await apiRequest("/api/admin/audit-log?"+params.toString());
      if(version!==authContextVersion || authSession?.user?.id!==userId)return;
      const items=Array.isArray(data.items)?data.items:[];
      $("#adminAuditCount").textContent=String(items.length);
      $("#adminAuditPage").textContent="Страница "+data.page;
      $("#adminAuditPrev").disabled=data.page<=1;
      $("#adminAuditNext").disabled=!data.has_more;
      list.replaceChildren();
      if(!items.length)list.append(adminNode("div","admin-empty","По выбранным условиям записей нет."));
      items.forEach(item=>{
        const card=adminNode("article","admin-item"), head=adminNode("div","admin-item-head");
        head.append(adminNode("b","",item.action||"Действие"),adminNode("span","admin-status",item.entity_type||"событие"));
        card.append(head,adminNode("p","admin-item-meta","Дата: "+formatAdminDate(item.created_at)),adminNode("p","admin-item-meta","Администратор: "+(item.actor_user_id||"не указан")));
        if(item.target_user_id)card.append(adminNode("p","admin-item-meta","Затронутый пользователь: "+item.target_user_id));
        if(item.entity_id)card.append(adminNode("p","admin-item-meta","ID объекта: "+item.entity_id));
        if(item.metadata && typeof item.metadata==="object"){
          const details=adminNode("details","admin-audit-details"), pre=adminNode("pre","admin-item-meta");
          details.append(adminNode("summary","","Подробности записи"));
          try{pre.textContent=JSON.stringify(item.metadata,null,2);}catch{pre.textContent="Подробности недоступны";}
          details.append(pre);card.append(details);
        }
        list.append(card);
      });
      auditFeedback("Журнал загружен. Показано записей: "+items.length+".");
    }catch(error){
      if(version!==authContextVersion)return;
      list.replaceChildren(adminNode("div","admin-empty","Не удалось загрузить журнал."));
      auditFeedback("Ошибка загрузки журнала: "+error.message);
      $("#adminAuditPrev").disabled=adminAuditPage<=1;$("#adminAuditNext").disabled=true;
    }
  };
  $("#adminAuditFilters")?.addEventListener("submit",event=>{event.preventDefault();adminAuditPage=1;loadAdminAuditLog();});
  $("#adminAuditReset")?.addEventListener("click",()=>{$("#adminAuditFilters")?.reset();adminAuditPage=1;loadAdminAuditLog();});
  $("#adminAuditPrev")?.addEventListener("click",()=>{if(adminAuditPage>1){adminAuditPage--;loadAdminAuditLog();}});
  $("#adminAuditNext")?.addEventListener("click",()=>{adminAuditPage++;loadAdminAuditLog();});
  $("#adminRefresh")?.addEventListener("click",loadAdminWorkspace);
  $("#adminSuspensionForm")?.addEventListener("submit",async event=>{
    event.preventDefault();
    const button=$("#adminSuspensionForm button[type=submit]");
    const userId=$("#suspensionUserId").value.trim(), reason=$("#suspensionReason").value.trim(), expiry=$("#suspensionExpiry").value;
    if(!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(userId)){adminFeedback("Проверьте UUID пользователя — нужен полный идентификатор Supabase Auth.");return;}
    if(authSession?.user?.id===userId){adminFeedback("Нельзя ограничить собственный аккаунт.");return;}
    const payload={user_id:userId,reason,scope:$("#suspensionScope").value,expires_at:expiry?new Date(expiry).toISOString():null};
    const version=authContextVersion, actorUserId=authSession?.user?.id;
    if(!actorUserId)return;
    button.disabled=true;
    try{
      await apiRequest("/api/admin/suspensions",{method:"POST",body:JSON.stringify(payload)});
      if(version!==authContextVersion || authSession?.user?.id!==actorUserId)return;
      $("#adminSuspensionForm").reset();
      adminFeedback("Ограничение создано и записано в журнал.");
      await loadAdminWorkspace();
    }catch(error){
      if(version===authContextVersion && authSession?.user?.id===actorUserId)adminFeedback("Не удалось создать ограничение: "+error.message);
    }finally{
      if(version===authContextVersion && authSession?.user?.id===actorUserId)button.disabled=false;
    }
  });
  if (authSession?.user) setTimeout(loadAccountRole, 0);
  const labels = {guestspace:"Гостевое пространство",account:"Личный кабинет",rules:"Правила и безопасность",home:"Главная",control:"Центр управления",create:"Создать видео",movie:"Миникиностудия",editor:"Видеоредактор",prompts:"Prompt Studio",library:"Медиатека",voice:"Голос и музыка",scenes:"Сценарий и сцены",assistant:"AI Companion",guide:"Путеводитель",about:"О студии",settings:"Настройки"};

  function navigate(view) {
    if (!labels[view]) return;
    const targetView = view === "control" ? "home" : view;
    $(".view").forEach(el => el.classList.toggle("active", el.id === "view-" + targetView));
    $(".nav-item[data-view]").forEach(el => el.classList.toggle("active", el.dataset.view === view));
    $("#crumbCurrent").textContent = labels[view];
    $("#sidebar").classList.remove("open");
    window.location.hash = targetView === "home" && view === "home" ? "" : view;
    window.scrollTo({top:0,behavior:"smooth"});
  }

  $$(".nav-item[data-view]").forEach(btn => btn.addEventListener("click", () => navigate(btn.dataset.view)));
  $$("[data-go]").forEach(btn => btn.addEventListener("click", () => navigate(btn.dataset.go)));
  $(".profile").addEventListener("click", () => navigate("account"));
  $("#topAvatar")?.addEventListener("click", () => navigate("account"));
  $("#accountLogin").addEventListener("click", () => setAuthMode("login"));
  $("#accountLogout").addEventListener("click", async () => { if (supabaseClient) await supabaseClient.auth.signOut(); });
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
    button.disabled = true;
    button.textContent = "✦ AI готовит промт…";
    $("#promptFeedback").textContent = "Отправляем запрос на backend. Ключ AI-провайдера остаётся на сервере.";
    try {
      const result = await apiRequest("/api/prompts", {
        method: "POST",
        body: JSON.stringify({ idea, purpose: $("#promptType").value, language: $("#promptLanguage").value, style: "Cinematic, coherent, detailed" })
      });
      $("#promptOutput").textContent = result.prompt;
      $("#promptFeedback").textContent = "Готово: ответ получен от " + result.provider + " · " + result.model + ".";
    } catch (error) {
      $("#promptFeedback").textContent = error.message;
    } finally {
      button.disabled = false;
      button.textContent = "✦ Сформировать промт";
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

  $$("[data-assist]").forEach(btn => btn.addEventListener("click", () => {
    $("#assistantInput").value = btn.dataset.assist;
    $("#assistantInput").focus();
  }));
  // AI Companion cloud history. Supabase RLS restricts every row to its owner.
  const assistantHistoryList = $("#assistantHistoryList");
  const assistantMessages = $("#assistantMessages");
  const assistantStatus = $("#assistantHistoryStatus");
  const setAssistantStatus = message => { if (assistantStatus) assistantStatus.textContent = message || ""; };
  const renderAssistantMessage = (role, content) => {
    const bubble = document.createElement("div");
    bubble.className = "helper-text assistant-message " + (role === "user" ? "user-message" : "ai-message");
    bubble.textContent = (role === "user" ? "Вы: " : "Studio AI: ") + content;
    assistantMessages.appendChild(bubble);
  };
  const clearAssistantMessages = () => { if (assistantMessages) assistantMessages.replaceChildren(); };
  const loadAssistantMessages = async conversationId => {
    if (!supabaseClient || !authSession?.user || !conversationId) return;
    const requestUserId = authSession.user.id;
    const requestVersion = authContextVersion;
    const { data, error } = await supabaseClient.from("assistant_messages")
      .select("id,role,content,created_at").eq("conversation_id", conversationId)
      .eq("user_id", requestUserId).order("created_at", { ascending: true });
    if (error) throw error;
    if (authSession?.user?.id !== requestUserId || authContextVersion !== requestVersion) return;
    clearAssistantMessages();
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
    if (assistantHistoryBusy) return;
    assistantHistoryBusy = true; setAssistantStatus("Загружаем ваши диалоги…");
    const requestUserId = authSession.user.id;
    const requestVersion = authContextVersion;
    try {
      const { data, error } = await supabaseClient.from("assistant_conversations")
        .select("id,title,updated_at").eq("user_id", requestUserId)
        .order("updated_at", { ascending: false });
      if (error) throw error;
      if (authSession?.user?.id !== requestUserId || authContextVersion !== requestVersion) return;
      assistantHistoryList.replaceChildren();
      (data || []).forEach(conversation => {
        const row = document.createElement("div"); row.className = "assistant-history-row";
        const open = document.createElement("button"); open.type = "button";
        open.className = "assistant-history-open"; open.textContent = conversation.title || "Новый диалог";
        open.title = open.textContent; open.setAttribute("aria-current", conversation.id === activeAssistantConversationId ? "true" : "false");
        open.addEventListener("click", async () => {
          try { await loadAssistantMessages(conversation.id); renderAssistantHistory(); setAssistantStatus(""); }
          catch (error) { setAssistantStatus("Не удалось открыть диалог: " + error.message); }
        });
        const rename = document.createElement("button"); rename.type = "button";
        rename.className = "assistant-history-rename"; rename.textContent = "✎";
        rename.title = "Переименовать диалог"; rename.setAttribute("aria-label", "Переименовать диалог");
        rename.addEventListener("click", async () => {
          const title = prompt("Название диалога:", conversation.title || "Новый диалог");
          if (title === null) return;
          const cleanTitle = title.trim().slice(0, 100); if (!cleanTitle) return;
          const { error: updateError } = await supabaseClient.from("assistant_conversations")
            .update({ title: cleanTitle }).eq("id", conversation.id).eq("user_id", authSession.user.id);
          if (updateError) setAssistantStatus("Не удалось переименовать: " + updateError.message);
          else { setAssistantStatus("Название сохранено."); renderAssistantHistory(); }
        });
        row.append(open, rename); assistantHistoryList.appendChild(row);
      });
      if (!activeAssistantConversationId && data?.length) {
        await loadAssistantMessages(data[0].id);
      }
      setAssistantStatus((data || []).length ? "Диалоги сохраняются в вашем аккаунте." : "Пока нет сохранённых диалогов. Начните новый разговор.");
    } catch (error) {
      setAssistantStatus("История пока недоступна. Проверьте, применена ли миграция Supabase. " + error.message);
    } finally { assistantHistoryBusy = false; }
  };
  const startAssistantConversation = async () => {
    if (!authSession?.user || !supabaseClient) throw new Error("Сначала войдите в аккаунт.");
    const { data, error } = await supabaseClient.from("assistant_conversations")
      .insert({ user_id: authSession.user.id, title: "Новый диалог" }).select("id").single();
    if (error) throw error;
    activeAssistantConversationId = data.id; clearAssistantMessages();
    await renderAssistantHistory();
    setAssistantStatus("Создан новый диалог. Предыдущие разговоры сохранены.");
  };
  $("#assistantNewChat")?.addEventListener("click", async () => {
    try { await startAssistantConversation(); $("#assistantInput").focus(); }
    catch (error) { setAssistantStatus("Не удалось создать диалог: " + error.message); }
  });
  $("#assistantForm").addEventListener("submit", async event => {
    event.preventDefault();
    const input = $("#assistantInput"); const value = input.value.trim(); if (!value) return;
    if (!authSession?.user) { setAuthMode("signup"); setAuthMessage("Войдите или зарегистрируйтесь, чтобы общаться с AI Companion."); return; }
    const button = $("#assistantForm button"); button.disabled = true; input.disabled = true; input.value = "";
    const requestUserId = authSession.user.id;
    const requestVersion = authContextVersion;
    const contextIsCurrent = () => authSession?.user?.id === requestUserId && authContextVersion === requestVersion;
    try {
      if (!activeAssistantConversationId) await startAssistantConversation();
      if (!contextIsCurrent()) return;
      const conversationId = activeAssistantConversationId;
      const { error: userSaveError } = await supabaseClient.from("assistant_messages")
        .insert({ conversation_id: conversationId, user_id: requestUserId, role: "user", content: value });
      if (userSaveError) throw userSaveError;
      if (!contextIsCurrent()) return;
      renderAssistantMessage("user", value);
      const { data: titleRow } = await supabaseClient.from("assistant_conversations")
        .select("title").eq("id", conversationId).eq("user_id", requestUserId).single();
      if (!contextIsCurrent()) return;
      if (titleRow?.title === "Новый диалог") {
        await supabaseClient.from("assistant_conversations")
          .update({ title: value.slice(0, 72) }).eq("id", conversationId).eq("user_id", requestUserId);
      }
      if (!contextIsCurrent()) return;
      const result = await apiRequest("/api/chat", { method: "POST", body: JSON.stringify({ message: value }) });
      if (!contextIsCurrent()) return;
      const { error: assistantSaveError } = await supabaseClient.from("assistant_messages")
        .insert({ conversation_id: conversationId, user_id: requestUserId, role: "assistant", content: result.reply });
      if (assistantSaveError) throw assistantSaveError;
      if (!contextIsCurrent()) return;
      renderAssistantMessage("assistant", result.reply); await renderAssistantHistory();
    } catch (error) { setAssistantStatus("Сообщение не удалось полностью обработать: " + error.message); }
    finally { button.disabled = false; input.disabled = false; input.focus(); }
  });
  setTimeout(() => renderAssistantHistory(), 0);


  // Mini Movie Studio: resilient local drafts with per-project editing and staged workflow.
  const movieStorageKey = () => "pwa-studio-movie-projects:" + (authSession?.user?.id || "guest");
  let activeMovieId = null;
  let editingMovieId = null;
  let editingMovieBaseUpdatedAt = null;
  resetMovieWorkspaceForAuthChange = () => {
    activeMovieId = null;
    editingMovieId = null;
    editingMovieBaseUpdatedAt = null;
    const form = $("#movieForm");
    if (form) form.reset();
    const panel = $("#movieWorkflowPanel");
    if (panel) { panel.hidden = true; panel.replaceChildren(); }
    const feedback = $("#movieFeedback");
    if (feedback) feedback.textContent = "Контекст аккаунта изменился. Откройте нужный проект заново; черновик другого пространства не переносился.";
  };
  const movieStages = [
    {key:"story",title:"Сценарий и раскадровка",fields:[["story","Сценарий","Напишите историю, действия и диалоги по сценам."],["storyboard","Раскадровка","Опишите кадры, планы камеры, движение и переходы."]]},
    {key:"characters",title:"Персонажи и аватары",fields:[["characters","Персонажи","Опишите героев: внешность, одежду, характер и особенности образа."]]},
    {key:"voices",title:"Голоса и озвучка",fields:[["voices","Голоса и звук","Назначьте голос каждому персонажу, укажите язык, манеру речи, реплики, музыку и звуковые эффекты."]]},
    {key:"edit",title:"Монтаж и экспорт",fields:[["edit","План монтажа","Опишите порядок сцен, длительность, переходы, музыку, титры и параметры будущего экспорта. Реальный видеорендер пока не подключён."]]}
  ];
  // Cloud persistence for movie projects. Supabase RLS scopes every query to the signed-in owner.
  const movieCloudState = { syncingContext: null, pendingContext: null, loadingContext: null, timer: null };
  const movieCloudContext = window.PWAMovieCloudContext;
  if (!movieCloudContext) console.error("Movie cloud context guard is unavailable; cloud sync is disabled.");
  const movieDeletedKey = () => "pwa-studio-movie-deleted:" + (authSession?.user?.id || "guest");
  const readMovieTombstones = () => window.PWAMovieTombstones.read(localStorage, movieDeletedKey(), isUuid);
  const writeMovieTombstones = ids => {
    try { localStorage.setItem(movieDeletedKey(), JSON.stringify([...new Set(ids.filter(isUuid))])); return true; }
    catch (error) { console.error("Movie deletion queue failed:", error); return false; }
  };
  const isUuid = value => /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(String(value || ""));
  const movieToCloudRow = (project, ownerId) => {
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
  const movieCloudOperations = window.PWAMovieCloudOperations?.createMovieCloudOperations({
    isCurrent: context => movieCloudContext.isCurrent(context, authSession?.user?.id || null, authContextVersion),
    setTimer: (fn, delay) => setTimeout(fn, delay),
    clearTimer: id => clearTimeout(id),
    supabase: () => supabaseClient,
    readTombstones: ownerId => {
      let value;
      try {
        const stored=localStorage.getItem("pwa-studio-movie-deleted:"+ownerId);
        value=stored ? JSON.parse(stored) : [];
      } catch(error) {
        throw new Error("Не удалось прочитать очередь удалённых фильмов; облачная операция остановлена: " + (error.message || "ошибка хранилища"));
      }
      if (!Array.isArray(value)) throw new Error("Очередь удалённых фильмов повреждена; облачная операция остановлена.");
      return value.filter(isUuid);
    },
    writeTombstones: (ownerId, ids) => {
      try {
        localStorage.setItem("pwa-studio-movie-deleted:"+ownerId,JSON.stringify([...new Set(ids.filter(isUuid))]));
        return true;
      } catch(error) {
        console.error("Movie deletion queue failed:",error);
        return false;
      }
    },
    readProjects: ownerId => {
      if (ownerId !== authSession?.user?.id) throw new Error("Контекст аккаунта изменился; локальные фильмы не прочитаны.");
      return readMovieProjectsForCloud();
    },
    writeProjects: (ownerId, projects) => localStorage.setItem("pwa-studio-movie-projects:"+ownerId,JSON.stringify(projects)),
    toCloudRow: movieToCloudRow,
    fromCloudRow: movieFromCloudRow,
    render: () => renderMovieProjects(),
    feedback: message => { const el=$("#movieFeedback"); if(el)el.textContent=message; },
    syncError: error => {
      console.error("Movie cloud sync failed:",error);
      const el=$("#movieFeedback"); if(el)el.textContent="Черновик сохранён на этом устройстве, но облачная синхронизация не удалась. Проверьте соединение и повторите попытку.";
    },
    loadError: error => {
      console.error("Movie cloud load failed:",error);
      const el=$("#movieFeedback"); if(el)el.textContent="Не удалось загрузить фильмы из облака. Локальные черновики сохранены на устройстве.";
    }
  }) || null;
  const scheduleMovieCloudSync = () => {
    const context=movieCloudContext?.capture(authSession?.user?.id,authContextVersion);
    if(context) movieCloudOperations?.schedule(context);
  };
  const loadMovieProjectsFromCloud = async () => {
    const context=movieCloudContext?.capture(authSession?.user?.id,authContextVersion);
    if(context) await movieCloudOperations?.load(context);
  };
  const movieStorageGuard = window.PWAMovieStorageGuard.create();
  const movieRead = (options = {}) => {
    const strict = options.strict === true;
    try {
      const raw = JSON.parse(localStorage.getItem(movieStorageKey()) || "[]");
      if (!Array.isArray(raw)) throw new Error("Локальное хранилище фильмов имеет неверный формат.");
      const now = Date.now();
      let changed = false;
      const projects = raw.filter(item => item && typeof item === "object" && item.id).map(item => {
        const project = {
          ...item,
          story: item.story || item.idea || "",
          completedSteps: Array.isArray(item.completedSteps) ? item.completedSteps.filter(key => movieStages.some(stage => stage.key === key)) : []
        };
        if (!authSession?.user) {
          const expiry = window.PWAGuestProjectExpiry.normalizeGuestProjectExpiry(project, now);
          if (expiry.changed) changed = true;
          return expiry.project;
        }
        return project;
      });
      const active = authSession?.user ? projects : projects.filter(project => {
        const expired = Date.parse(project.guestExpiresAt) <= now;
        if (expired) changed = true;
        return !expired;
      });
      if (changed) {
        if (!authSession?.user && active.length !== projects.length) sessionStorage.setItem("pwa-studio-guest-expired-notice", "1");
        localStorage.setItem(movieStorageKey(), JSON.stringify(active));
      }
      movieStorageGuard.readSucceeded();
      return active.sort((a, b) => new Date(b.updatedAt || b.createdAt || 0) - new Date(a.updatedAt || a.createdAt || 0));
    } catch (error) {
      movieStorageGuard.readFailed();
      console.error("Movie project storage read failed:", error);
      const feedback = $("#movieFeedback");
      if (feedback) feedback.textContent = "Не удалось прочитать локальные фильмы. Чтобы не показать пустой список и не перезаписать облачные проекты, синхронизация остановлена до восстановления доступа к памяти браузера.";
      if (strict) throw error;
      return [];
    }
  };
  // Cloud reads use the same single read/normalization pass, but propagate failures.
  const readMovieProjectsForCloud = () => movieRead({ strict: true });
  const movieWrite = projects => {
    if (!movieStorageGuard.canWrite()) {
      const feedback = $("#movieFeedback");
      if (feedback) feedback.textContent = "Сохранение остановлено: перед этим не удалось прочитать текущие фильмы. Повторите чтение после восстановления доступа к памяти, чтобы не затереть существующие проекты.";
      return false;
    }
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
  const movieId = () => window.PWAMovieId.create(window.crypto);
  const movieSnapshot = project => MovieVersionHistory.snapshot(project);
  const addMovieVersion = project => MovieVersionHistory.addVersion(project);
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
    let baseUpdatedAt=project.updatedAt||project.createdAt||null;
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
      const current=latest[index];
      if((current.updatedAt||current.createdAt||null)!==baseUpdatedAt){
        status.textContent="Этот фильм изменился в другом окне или на другом устройстве. Сведения не перезаписаны — закройте этап и откройте его заново, чтобы загрузить актуальную версию.";
        return false;
      }
      addMovieVersion(current);
      Object.assign(current,{
        name, seriesNumber:inputs.movieSeriesNumber.value?Number(inputs.movieSeriesNumber.value):null,
        versionLabel:inputs.movieVersionLabel.value.trim(), idea:inputs.movieIdea.value.trim(),
        genre:inputs.movieGenre.value, duration:Number(inputs.movieDuration.value), frame:inputs.movieFrame.value,
        updatedAt:new Date().toISOString()
      });
      if(!movieWrite(latest)){status.textContent="Не удалось сохранить изменения.";return false;}
      baseUpdatedAt=current.updatedAt;
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
    const stage=movieStages[stageIndex];
    let baseUpdatedAt=project.updatedAt||project.createdAt||null;
    panel.replaceChildren();
    const head=document.createElement("div"); head.className="movie-workflow-head";
    const title=document.createElement("h2"); title.textContent="Этап "+(stageIndex+1)+" из 4 · "+stage.title;
    const edition=movieEditionLabel(project);
    const subtitle=document.createElement("p"); subtitle.textContent="Фильм: "+project.name+(edition?" · "+edition:"")+" · "+(done.includes(stage.key)?"Этап сохранён — его можно редактировать.":"Заполните материалы и сохраните, чтобы открыть следующий этап.");
    head.append(title,subtitle);
    const form=document.createElement("div"); form.className="movie-stage-fields"; const inputs={};
    stage.fields.forEach(([key,labelText,placeholder])=>{
      const wrap=document.createElement("label"); wrap.className="movie-stage-field";
      const label=document.createElement("span"); label.textContent=labelText;
      const textarea=document.createElement("textarea"); textarea.rows=(key==="story"||key==="storyboard")?7:6; textarea.maxLength=30000; textarea.placeholder=placeholder;
      textarea.value=project[key]||(key==="story"?project.idea||"":""); inputs[key]=textarea; wrap.append(label,textarea); form.append(wrap);
    });
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
        const current=latest[index];
        if((current.updatedAt||current.createdAt||null)!==baseUpdatedAt){draftStatus.textContent="Этот фильм изменился в другом окне или устройстве. Черновик не перезаписан — закройте этап и откройте его заново, чтобы загрузить актуальную версию.";return;}
        addMovieVersion(current);
        stage.fields.forEach(([key])=>{current[key]=inputs[key].value.trim();});
        if(stage.key==="story" && current.story) current.idea=current.story;
        current.updatedAt=new Date().toISOString();
        if(!movieWrite(latest)){draftStatus.textContent="Сохранение не удалось. Проверьте сообщение вверху страницы.";return;}
        baseUpdatedAt=current.updatedAt;
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
      const current=latest[index];
      if((current.updatedAt||current.createdAt||null)!==baseUpdatedAt){$("#movieFeedback").textContent="Этот фильм изменился в другом окне или устройстве. Этап не перезаписан — откройте его заново, чтобы загрузить актуальную версию.";return;}
      addMovieVersion(current);
      stage.fields.forEach(([key])=>{current[key]=inputs[key].value.trim();});
      current.completedSteps=(Array.isArray(current.completedSteps)?current.completedSteps:[]).filter(key=>movieStages.findIndex(item=>item.key===key)<=stageIndex);
      if(!current.completedSteps.includes(stage.key))current.completedSteps.push(stage.key);
      current.workflowStep=Math.min(stageIndex+1,4); current.updatedAt=new Date().toISOString();
      baseUpdatedAt=current.updatedAt;
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
    actions.append(previous,draft,close,save,draftStatus); panel.append(head,form,actions); panel.hidden=false; panel.setAttribute("data-active-stage",stage.key); requestAnimationFrame(()=>panel.scrollIntoView({behavior:"smooth",block:"start"}));
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
  let dashboardActivityBusy = false;
  let dashboardActivityPending = false;
  const renderDashboardActivity = async () => {
    const list = $("#dashboardActivityList");
    if (!list) return;
    if (dashboardActivityBusy) { dashboardActivityPending = true; return; }
    dashboardActivityBusy = true;
    const requestUserId = authSession?.user?.id || null;
    const requestVersion = authContextVersion;
    try {
      const items = movieRead().slice(0, 5).map(project => ({
        kind: "movie", id: project.id, title: project.name || "Без названия",
        detail: "Проект фильма · " + movieProgress(project),
        updatedAt: project.updatedAt || project.createdAt || null
      }));
      let conversationHistoryUnavailable = false;
      if (requestUserId && supabaseClient) {
        try {
          const { data, error } = await supabaseClient.from("assistant_conversations")
            .select("id,title,updated_at").eq("user_id", requestUserId)
            .order("updated_at", { ascending: false }).limit(5);
          if (error) throw error;
          if (authSession?.user?.id !== requestUserId || authContextVersion !== requestVersion) return;
          (data || []).forEach(conversation => items.push({
            kind: "assistant", id: conversation.id,
            title: conversation.title || "Новый диалог",
            detail: "Разговор с AI Companion",
            updatedAt: conversation.updated_at || null
          }));
        } catch (historyError) {
          if (authSession?.user?.id !== requestUserId || authContextVersion !== requestVersion) return;
          conversationHistoryUnavailable = true;
          console.warn("Dashboard conversation history is unavailable:", historyError);
        }
      }
      if (authSession?.user?.id !== requestUserId || authContextVersion !== requestVersion) return;
      items.sort((a, b) => new Date(b.updatedAt || 0) - new Date(a.updatedAt || 0));
      list.replaceChildren();
      if (!items.length) {
        const empty = document.createElement("div"); empty.className = "dashboard-empty";
        empty.textContent = requestUserId
          ? (conversationHistoryUnavailable
            ? "История AI Companion пока недоступна. Создайте проект — он появится здесь."
            : "Здесь появятся ваши новые проекты и разговоры с AI Companion.")
          : "Создайте проект — и здесь появится ваша недавняя активность.";
        list.append(empty); return;
      }
      items.slice(0, 6).forEach(item => {
        const button = document.createElement("button");
        button.type = "button"; button.className = "dashboard-activity-item";
        const icon = document.createElement("span"); icon.className = "dashboard-activity-icon";
        icon.textContent = item.kind === "movie" ? "🎬" : "✦";
        const copy = document.createElement("span"); copy.className = "dashboard-activity-copy";
        const title = document.createElement("b"); title.textContent = item.title;
        const detail = document.createElement("small");
        detail.textContent = item.detail + (item.updatedAt ? " · " + movieDate(item.updatedAt) : "");
        copy.append(title, detail);
        const arrow = document.createElement("span"); arrow.className = "dashboard-activity-arrow"; arrow.textContent = "↗";
        button.append(icon, copy, arrow);
        button.addEventListener("click", async () => {
          if (item.kind === "movie") {
            activeMovieId = item.id; navigate("movie");
            setTimeout(() => openMovieOverview(item.id), 80);
          } else {
            navigate("assistant");
            try { await loadAssistantMessages(item.id); await renderAssistantHistory(); }
            catch (error) { setAssistantStatus("Не удалось открыть диалог: " + error.message); }
          }
        });
        list.append(button);
      });
      if (conversationHistoryUnavailable) {
        const note = document.createElement("div"); note.className = "dashboard-empty";
        note.textContent = "История AI Companion временно недоступна; ваши проекты показаны выше.";
        list.append(note);
      }
    } catch (error) {
      if (authSession?.user?.id !== requestUserId || authContextVersion !== requestVersion) return;
      list.replaceChildren();
      const note = document.createElement("div"); note.className = "dashboard-empty";
      note.textContent = "Не удалось обновить недавнюю активность. Попробуйте открыть Центр управления позже.";
      list.append(note);
      console.warn("Dashboard activity could not be rendered:", error);
    } finally {
      dashboardActivityBusy = false;
      if (dashboardActivityPending) { dashboardActivityPending = false; renderDashboardActivity(); }
    }
  };
  const renderCreativeDashboard = () => {
    const list=$("#dashboardProjectList");
    if(!list)return;
    const projects=movieRead().slice(0,4);
    const count=$("#dashboardProjectCount");
    if(count)count.textContent=projects.length+" из "+movieRead().length;
    list.replaceChildren();
    if(!projects.length){
      const empty=document.createElement("div"); empty.className="dashboard-empty";
      const title=document.createElement("b"); title.textContent="Ваша первая история начнётся здесь";
      const note=document.createElement("p"); note.textContent="Создайте проект в Миникиностудии — он появится в этом пространстве.";
      const action=document.createElement("button"); action.type="button"; action.className="secondary-button"; action.textContent="Создать первый фильм →";
      action.addEventListener("click",()=>navigate("movie"));
      empty.append(title,note,action); list.append(empty);
    }else{
      projects.forEach(project=>{
        const card=document.createElement("article"); card.className="dashboard-project";
        const main=document.createElement("div"); main.className="dashboard-project-main";
        const title=document.createElement("b"); title.textContent=project.name||"Без названия";
        const meta=document.createElement("small"); meta.textContent=[project.genre||"Жанр не указан",movieProgress(project),"Изменён "+movieDate(project.updatedAt||project.createdAt)].join(" · ");
        main.append(title,meta);
        const state=document.createElement("span"); state.className="dashboard-save-state";
        state.textContent=authSession?.user?"Статус облака — в мастерской":"Сохранено на этом устройстве";
        const open=document.createElement("button"); open.type="button"; open.className="secondary-button"; open.textContent="Продолжить →";
        open.addEventListener("click",()=>{activeMovieId=project.id;navigate("movie");setTimeout(()=>openMovieOverview(project.id),80);});
        card.append(main,state,open); list.append(card);
      });
    }
    const recent=$("#dashboardRecentLabel");
    if(recent)recent.textContent=projects.length?"Недавно изменённые проекты":"Пока нет недавних проектов";
    renderDashboardActivity();
  };
  const renderMovieProjects = () => {
    const list=$("#movieProjectList"); if(!list)return;
    const projects=movieRead(); const count=$("#movieCount");
    if(count)count.textContent=projects.length+(projects.length===1?" проект":projects.length>1&&projects.length<5?" проекта":" проектов");
    if(!projects.length){
      list.innerHTML='<div class="movie-empty"><span>✧</span><b>Здесь появятся ваши фильмы</b><small>Создайте первый проект, чтобы начать свою кинематографическую историю.</small></div>';
      activeMovieId=null; updateMovieStageCards(); renderCreativeDashboard(); return;
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
            const selectedVersion=versions[selectedIndex];
            const latestVersions=Array.isArray(live.versions)?live.versions:[];
            const stillAvailable=latestVersions.some(entry=>entry.savedAt===selectedVersion.savedAt && JSON.stringify(entry.data)===JSON.stringify(selectedVersion.data));
            if(!stillAvailable){
              overlay.remove();
              $("#movieFeedback").textContent="Выбранная версия больше недоступна в актуальной истории (возможно, история обновилась или старые записи были ограничены). Откройте историю заново и выберите существующую версию.";
              return;
            }
            const restored=MovieVersionHistory.restore(live,selectedVersion,new Date().toISOString());
            if(!restored){
              overlay.remove();
              $("#movieFeedback").textContent="Эта запись истории повреждена или относится к другому фильму. Текущий проект не изменён.";
              return;
            }
            latest[latest.findIndex(item=>item.id===project.id)]=restored;
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
        const currentProjects=movieRead();
        const latest=currentProjects.filter(item=>item.id!==project.id);
        let deletedIds;
        try { deletedIds=readMovieTombstones(); }
        catch(error) { $("#movieFeedback").textContent="Не удалось прочитать очередь удалений. Фильм не удалён и облачная синхронизация не запускалась. Проверьте память браузера и повторите попытку."; console.error("Movie deletion queue read failed:",error); return; }
        const needsTombstone=!!authSession?.user && isUuid(project.id) && !deletedIds.includes(project.id);
        if(needsTombstone && !writeMovieTombstones([...deletedIds,project.id])){
          $("#movieFeedback").textContent="Не удалось надёжно поставить облачное удаление в очередь. Фильм оставлен на месте — освободите память браузера и повторите попытку.";
          return;
        }
        if(movieWrite(latest)){
          if(activeMovieId===project.id)activeMovieId=latest[0]?.id||null;
          renderMovieProjects();
          const workflow=$("#movieWorkflowPanel");if(workflow)workflow.hidden=true;
          $("#movieFeedback").textContent=authSession?.user?"Проект удалён с устройства. Удаление ожидает подтверждения облачной синхронизации.":"Проект удалён с этого устройства.";
        } else if(needsTombstone) {
          // Roll back the newly queued cloud delete when possible. If storage also
          // blocks rollback, explain that the cloud deletion remains queued.
          if(!writeMovieTombstones(deletedIds)) {
            console.error("Could not roll back the tombstone after local project write failed.");
            $("#movieFeedback").textContent="Не удалось удалить фильм из памяти устройства. При этом очередь облачного удаления не удалось отменить: облачная копия может быть удалена при следующей синхронизации. Освободите память браузера и проверьте проект перед продолжением.";
          }
        }
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
    renderCreativeDashboard();
  };
  $("#movieStart").addEventListener("click",()=>{
    editingMovieId=null; editingMovieBaseUpdatedAt=null; $("#movieForm").reset();
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
      savedProject=projects[existingIndex];
      if(editingMovieBaseUpdatedAt && (savedProject.updatedAt||savedProject.createdAt||null)!==editingMovieBaseUpdatedAt){
        $("#movieFeedback").textContent="Этот фильм изменился в другом окне или на другом устройстве. Изменения не сохранены — откройте проект заново, чтобы загрузить актуальную версию.";
        return;
      }
      addMovieVersion(savedProject);
      const ideaChanged=(savedProject.idea||"")!==$("#movieIdea").value.trim();
      Object.assign(savedProject,{name,idea:$("#movieIdea").value.trim(),genre:$("#movieGenre").value,seriesNumber:$("#movieSeriesNumber").value?Number($("#movieSeriesNumber").value):null,versionLabel:$("#movieVersionLabel").value.trim(),duration:Number($("#movieDuration").value),frame:$("#movieFrame").value,updatedAt:now});
      if(ideaChanged){savedProject.completedSteps=[];savedProject.workflowStep=0;}
      projects[existingIndex]=savedProject;
    }else{
      savedProject={id:movieId(),name,idea:$("#movieIdea").value.trim(),genre:$("#movieGenre").value,seriesNumber:$("#movieSeriesNumber").value?Number($("#movieSeriesNumber").value):null,versionLabel:$("#movieVersionLabel").value.trim(),duration:Number($("#movieDuration").value),frame:$("#movieFrame").value,createdAt:now,updatedAt:now,...(!authSession?.user?{guestExpiresAt:new Date(Date.now()+24*60*60*1000).toISOString()}:{}),workflowStep:0,completedSteps:[],story:"",storyboard:"",characters:"",voices:"",edit:"",versions:[]};
      projects.unshift(savedProject);
    }
    if(!movieWrite(projects))return;
    activeMovieId=savedProject.id; editingMovieId=savedProject.id; editingMovieBaseUpdatedAt=savedProject.updatedAt||savedProject.createdAt||null;
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
    list.replaceChildren();
    if(!projects.length){
      const empty=document.createElement("div");empty.className="movie-empty";
      const icon=document.createElement("span");icon.textContent="✧";
      const title=document.createElement("b");title.textContent="Пока здесь пусто";
      const hint=document.createElement("small");hint.textContent="Создайте фильм в Миникиностудии — он появится в этом пространстве.";
      empty.append(icon,title,hint);list.append(empty);return;
    }
    projects.forEach((project,index)=>{
      const card=document.createElement("article");card.className="guest-project-card";
      const head=document.createElement("div");head.className="guest-project-card-head";
      const number=document.createElement("span");number.className="movie-project-number";number.textContent=String(index+1).padStart(2,"0");
      const title=document.createElement("b");title.textContent=project.name||"Без названия";
      head.append(number,title);
      const meta=document.createElement("p");meta.textContent=[project.genre||"Жанр не указан",(project.duration||5)+" мин",project.frame||"16:9",movieProgress(project)].join(" · ");
      const expiry=document.createElement("div");expiry.className="guest-project-expiry";expiry.textContent="Осталось: "+formatGuestRemaining(project.guestExpiresAt);
      const actions=document.createElement("div");actions.className="guest-project-actions";
      const open=document.createElement("button");open.type="button";open.className="primary-button";open.textContent="Продолжить фильм";open.addEventListener("click",()=>{activeMovieId=project.id;editingMovieId=project.id;navigate("movie");const next=movieStages.findIndex(stage=>!(project.completedSteps||[]).includes(stage.key));if((project.completedSteps||[]).length===4)openMovieOverview(project.id);else openMovieStage(project.id,next<0?0:next);});
      const download=document.createElement("button");download.type="button";download.className="secondary-button";download.textContent="⇩ Скачать проект";download.addEventListener("click",()=>downloadGuestProject(project));
      actions.append(open,download);card.append(head,meta,expiry,actions);list.append(card);
    });
  };
  $("#guestCreateMovie")?.addEventListener("click",()=>navigate("movie"));
  $("#guestExportAll")?.addEventListener("click",()=>{
    const projects=movieRead();
    if(!projects.length){window.alert("Пока нет гостевых проектов для скачивания.");return;}
    const blob=new Blob([JSON.stringify({format:"PWA Studio guest workspace",schemaVersion:1,exportedAt:new Date().toISOString(),projects},null,2)],{type:"application/json;charset=utf-8"});
    const url=URL.createObjectURL(blob);const link=document.createElement("a");link.href=url;link.download="pwa-studio-guest-projects.json";document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
  renderGuestSpace();
  setInterval(()=>{if(!authSession?.user && !$("#view-guestspace")?.hidden)renderGuestSpace();},60000);

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