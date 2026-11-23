(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const API_URL_KEY = "pwa-studio-api-url";
  const API_TRUST_KEY = "pwa-studio-trusted-api-origin";
  const DEFAULT_API_BASE = "https://pwa-studio-creative-ai.onrender.com";
  // Supabase Auth: only the public publishable key is used in the browser.
  const authGate = $("#authGate");
  const authFeedback = $("#authFeedback");
  const supabaseConfig = window.PWA_SUPABASE_CONFIG || {};
  const supabaseClient = window.supabase && supabaseConfig.url && supabaseConfig.publishableKey
    ? window.supabase.createClient(supabaseConfig.url, supabaseConfig.publishableKey)
    : null;
  let authSession = null;
  let adminUiAuthorized = false;
  let financeUiAuthorized = false;
  let financeAccess = null;
  let activeAssistantConversationId = null;
  let lastAuthUserId = null;
  let authStateEventReceived = false;
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
    authSession = session;
    const adminPanel = $("#adminPanel");
    adminUiAuthorized = false;
    if (adminPanel) adminPanel.hidden = true;
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
    supabaseClient.auth.getSession().then(({data,error}) => {
      if (error) setAuthMessage(error.message, true);
      if (authStateEventReceived) return;
      const session = data?.session || null;
      lastAuthUserId = session?.user?.id || null;
      refreshAuthUI(session);
      setTimeout(() => {
        if (typeof renderMovieProjects === "function") renderMovieProjects();
        if (typeof restoreMovieStorageForCurrentUser === "function") restoreMovieStorageForCurrentUser();
        if (typeof loadMovieProjectsFromCloud === "function") loadMovieProjectsFromCloud();
        if (typeof loadAccountRole === "function") loadAccountRole();
        if (typeof loadMyEntitlements === "function") loadMyEntitlements();
        if (typeof renderAssistantHistory === "function") renderAssistantHistory();
        if (typeof syncCloudVisualLibrary === "function") syncCloudVisualLibrary();
      }, 0);
    });
    supabaseClient.auth.onAuthStateChange((_event, session) => {
      authStateEventReceived = true;
      const nextUserId = session?.user?.id || null;
      const accountChanged = lastAuthUserId !== nextUserId;
      // Invalidate any in-flight visual-library sync immediately, including logout.
      if (accountChanged) visualLibrarySyncSequence++;
      lastAuthUserId = nextUserId;
      refreshAuthUI(session);
      setTimeout(() => {
        if (accountChanged) {
          // Never carry an editor draft or selected asset across account boundaries.
          if (typeof resetVisualAssetEditor === "function") resetVisualAssetEditor();
          if (typeof renderVisualLibrary === "function") renderVisualLibrary();
          financeUiAuthorized = false; financeAccess = null;
          const financePanel = $("#financePanel"); if (financePanel) financePanel.hidden = true;
          activeAssistantConversationId = null;
          $("#assistantHistoryList")?.replaceChildren();
          $("#assistantMessages")?.replaceChildren();
          const assistantInput = $("#assistantInput"); if (assistantInput) assistantInput.value = "";
          const promptIdea = $("#promptIdea"); if (promptIdea) promptIdea.value = "";
          $("#promptOutput")?.replaceChildren();
          const topic = $("#topic"); if (topic) topic.value = "";
          $("#movieForm")?.reset();
          const workflow = $("#movieWorkflowPanel");
          if (workflow) { workflow.hidden = true; workflow.replaceChildren(); }
          if (typeof setMovieCreationFormVisible === "function") setMovieCreationFormVisible(true);
          if (typeof activeMovieId !== "undefined") activeMovieId = null;
          if (typeof editingMovieId !== "undefined") editingMovieId = null;
          if (typeof movieCloudState !== "undefined") {
            clearTimeout(movieCloudState.timer);
            movieCloudState.pending = false;
          }
        }
        if (typeof loadAccountRole === "function") loadAccountRole();
        if (typeof loadMyEntitlements === "function") loadMyEntitlements();
        if (typeof renderAssistantHistory === "function") renderAssistantHistory();
        if (accountChanged && nextUserId && typeof syncCloudVisualLibrary === "function" && authSession?.user?.id === nextUserId) syncCloudVisualLibrary();
        if (typeof renderMovieProjects === "function") renderMovieProjects();
        if (typeof loadMovieProjectsFromCloud === "function") loadMovieProjectsFromCloud();
      }, 0);
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


  const getApiBase = () => (localStorage.getItem(API_URL_KEY) || DEFAULT_API_BASE).trim().replace(/\/+$/, "");
  const loadAccountRole = async () => {
    const panel = $("#adminPanel");
    const userId = authSession?.user?.id;
    if (!userId || !panel) {
      if (panel) panel.hidden = true;
      financeUiAuthorized = false; financeAccess = null;
      const financePanel = $("#financePanel"); if (financePanel) financePanel.hidden = true;
      return;
    }
    try {
      const data = await apiRequest("/api/auth/me");
      if (authSession?.user?.id !== userId) return;
      $("#accountRole").textContent = data.role === "admin" ? "Владелец студии" : "Автор";
      adminUiAuthorized = data.role === "admin";
      panel.hidden = !adminUiAuthorized;
      if (adminUiAuthorized) { loadAdminAnalytics(); loadAdminAuditEvents(true); loadAdminAiProviders(); loadAdminAiCostBudget(); }
      loadFinanceAccess();
    } catch {
      if (authSession?.user?.id === userId) {
        adminUiAuthorized = false; panel.hidden = true;
        financeUiAuthorized = false; financeAccess = null;
        const financePanel = $("#financePanel"); if (financePanel) financePanel.hidden = true;
      }
    }
  };
  const apiRequest = async (path, options = {}) => {
    const base = getApiBase();
    if (!base) throw new Error("Сначала укажите адрес развёрнутого backend API в разделе «Настройки».");
    let apiUrl;
    try { apiUrl = new URL(base); } catch { throw new Error("Адрес backend API имеет неверный формат."); }
    const isLocalApi = apiUrl.protocol === "http:" && ["localhost", "127.0.0.1"].includes(apiUrl.hostname);
    if ((apiUrl.protocol !== "https:" && !isLocalApi) || apiUrl.username || apiUrl.password || apiUrl.search || apiUrl.hash) {
      throw new Error("Для backend API нужен HTTPS-адрес без логина, пароля, query-параметров и hash. HTTP разрешён только для localhost.");
    }
    const defaultOrigin = new URL(DEFAULT_API_BASE).origin;
    const trustedOrigin = localStorage.getItem(API_TRUST_KEY);
    if (apiUrl.origin !== defaultOrigin && !isLocalApi && trustedOrigin !== apiUrl.origin) {
      throw new Error("Этот адрес API ещё не подтверждён. Откройте «Настройки» и сохраните его, подтвердив доверие к серверу.");
    }
    const token = authSession?.access_token;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 100000);
    try {
      const response = await fetch(base + path, {
        ...options,
        signal: controller.signal,
        headers: {
          ...(options.body ? { "Content-Type": "application/json" } : {}),
          ...(token ? { Authorization: "Bearer " + token } : {}),
          ...(options.headers || {})
        }
      });
      let data = {};
      try { data = await response.json(); } catch {}
      if (!response.ok) throw new Error(data.detail || "Ошибка API (" + response.status + ").");
      return data;
    } catch (error) {
      if (error?.name === "AbortError") throw new Error("Сервер не ответил за 100 секунд. Попробуйте ещё раз.");
      throw error;
    } finally {
      clearTimeout(timeoutId);
    }
  };


  const entitlementCapabilityLabels = {
    ai: { title: "AI Companion", icon: "✦", dimensions: ["daily_ai_requests", "monthly_ai_requests", "max_concurrent_ai_requests"] },
    image: { title: "Генерация изображений", icon: "▧", dimensions: ["daily_image_generations", "monthly_image_generations"] },
    video: { title: "Генерация видео", icon: "🎬", dimensions: ["daily_video_generations", "monthly_video_generations", "max_video_seconds", "max_resolution"] },
    audio: { title: "Генерация аудио", icon: "♫", dimensions: ["daily_audio_generations", "monthly_audio_generations"] },
    jobs: { title: "Общий ресурс заданий", icon: "⚙", dimensions: ["daily_generation_jobs", "monthly_generation_jobs", "max_parallel_jobs"], capability: false }
  };
  const entitlementDimensionLabels = {
    daily_ai_requests: "Запросы AI за день",
    monthly_ai_requests: "Запросы AI за месяц",
    max_concurrent_ai_requests: "Одновременные AI-запросы",
    daily_image_generations: "Изображения за день",
    monthly_image_generations: "Изображения за месяц",
    daily_video_generations: "Видео за день",
    monthly_video_generations: "Видео за месяц",
    daily_audio_generations: "Аудио за день",
    monthly_audio_generations: "Аудио за месяц",
    daily_generation_jobs: "Задания за день",
    monthly_generation_jobs: "Задания за месяц",
    max_parallel_jobs: "Одновременные задания",
    max_video_seconds: "Максимальная длительность видео",
    max_resolution: "Максимальное разрешение"
  };
  let entitlementRequestVersion = 0;
  const clearMyEntitlements = message => {
    const status = $("#myEntitlementsStatus");
    const plan = $("#myEntitlementsPlan");
    const cards = $("#myEntitlementsCapabilities");
    const refresh = $("#refreshMyEntitlements");
    if (status) status.textContent = message;
    if (plan) { plan.hidden = true; plan.textContent = ""; }
    if (cards) cards.replaceChildren();
    if (refresh) refresh.hidden = !authSession?.user;
  };
  const renderMyEntitlements = data => {
    const status = $("#myEntitlementsStatus");
    const planBox = $("#myEntitlementsPlan");
    const cards = $("#myEntitlementsCapabilities");
    const footnote = $("#myEntitlementsFootnote");
    if (!status || !planBox || !cards) return;
    cards.replaceChildren();
    if (data.status === "no_active_plan") {
      status.textContent = data.pending_assignment_exists
        ? "Назначение тарифа ожидает активации. Тарифные преимущества пока недоступны."
        : "Активный тариф пока не назначен. Доступные функции будут показаны здесь после активации тарифа.";
      planBox.hidden = true;
      return;
    }
    if (data.status === "ambiguous_active_assignments") {
      status.textContent = "Не удалось однозначно определить тариф. Доступ к тарифным функциям временно закрыт до проверки.";
      planBox.hidden = true;
      return;
    }
    if (data.status !== "active" || !data.plan) {
      status.textContent = "Состояние тарифа не удалось определить.";
      planBox.hidden = true;
      return;
    }
    const plan = data.plan;
    planBox.hidden = false;
    planBox.textContent = plan.name + " · версия " + plan.version + " · " +
      (plan.billing_period === "week" ? "7 дней" : "30 дней") +
      (data.assignment?.ends_at ? " · действует до " + new Date(data.assignment.ends_at).toLocaleDateString() : "");
    status.textContent = data.capabilities_enabled
      ? "Тариф определён. Ниже показаны доступные инструменты и текущие квоты."
      : "Тариф назначен, но для доступных инструментов пока не настроены все обязательные квоты.";
    for (const [key, meta] of Object.entries(entitlementCapabilityLabels)) {
      const capability = data.capabilities?.[key] || {};
      const card = document.createElement("article");
      card.className = "account-tile entitlement-quota-card";
      const icon = document.createElement("span"); icon.textContent = meta.icon;
      const title = document.createElement("b"); title.textContent = meta.title;
      const state = document.createElement("p");
      state.textContent = key === "jobs" ? "Общие ограничения для всех типов заданий" :
        capability.available ? "Доступно по вашему тарифу" :
        capability.included_in_plan ? "Включено в тариф, но квоты ещё не готовы" : "Не входит в тариф";
      card.append(icon, title, state);
      for (const dimension of meta.dimensions) {
        const quota = data.quotas?.[dimension];
        const line = document.createElement("small");
        line.className = "entitlement-quota-line";
        if (!quota || !quota.configured) {
          line.textContent = entitlementDimensionLabels[dimension] + ": лимит не задан";
        } else if (dimension === "max_resolution") {
          line.textContent = entitlementDimensionLabels[dimension] + ": " + quota.limit;
        } else if (dimension === "max_video_seconds") {
          line.textContent = entitlementDimensionLabels[dimension] + ": " + quota.limit + " сек. на одно видео";
        } else {
          line.textContent = entitlementDimensionLabels[dimension] + ": " +
            quota.used + " / " + quota.limit +
            (quota.remaining !== null ? " · осталось " + quota.remaining : "") +
            (quota.reset_at ? " · сброс " + new Date(quota.reset_at).toLocaleDateString() : "");
        }
        card.append(line);
      }
      cards.append(card);
    }
    const notEnforced = Object.entries(data.quotas || {}).filter(([, quota]) => quota.configured && !quota.enforced);
    if (footnote && notEnforced.length) {
      footnote.textContent = "Некоторые дополнительные ограничения тарифа отображаются справочно и пока не блокируют генерацию. Мы не показываем их как действующие лимиты.";
    }
  };
  const loadMyEntitlements = async () => {
    const requestVersion = ++entitlementRequestVersion;
    const userId = authSession?.user?.id;
    if (!userId) { clearMyEntitlements("Войдите в аккаунт, чтобы проверить тариф и доступные инструменты."); return; }
    const status = $("#myEntitlementsStatus");
    const refresh = $("#refreshMyEntitlements");
    if (status) status.textContent = "Проверяем ваш тариф и квоты…";
    if (refresh) refresh.hidden = false;
    try {
      const data = await apiRequest("/api/me/entitlements", { cache: "no-store" });
      if (requestVersion !== entitlementRequestVersion || authSession?.user?.id !== userId) return;
      renderMyEntitlements(data);
    } catch (error) {
      if (requestVersion !== entitlementRequestVersion || authSession?.user?.id !== userId) return;
      clearMyEntitlements("Не удалось загрузить тариф: " + error.message);
    }
  };
  $("#refreshMyEntitlements")?.addEventListener("click", loadMyEntitlements);

  const supportStatusLabels = {open:"Открыто",in_progress:"В работе",waiting_user:"Ожидает ответа",resolved:"Решено",closed:"Закрыто"};
  let mySupportTickets = [];
  let adminSupportTickets = [];
  let selectedMySupportTicket = null;
  let selectedAdminSupportTicket = null;
  const supportMessageNode = (message, adminView = false) => {
    const row = document.createElement("article");
    row.className = "assistant-message " + (message.sender_role === "admin" ? "ai-message" : "user-message");
    const label = document.createElement("b");
    label.textContent = (message.sender_role === "admin" ? "Поддержка" : "Вы") + " · " + new Date(message.created_at).toLocaleString();
    const body = document.createElement("p");
    body.textContent = message.body || "";
    row.append(label, body);
    return row;
  };
  const setSupportOptions = (select, tickets, emptyLabel) => {
    if (!select) return;
    select.replaceChildren();
    const empty = document.createElement("option"); empty.value = ""; empty.textContent = tickets.length ? "Выберите обращение" : emptyLabel; select.append(empty);
    tickets.forEach(ticket => {
      const option = document.createElement("option");
      option.value = ticket.id;
      option.textContent = ticket.subject + " · " + (supportStatusLabels[ticket.status] || ticket.status);
      select.append(option);
    });
  };
  const loadMySupportTickets = async () => {
    const status = $("#supportUserStatus");
    if (!authSession?.user) { if (status) status.textContent = "Войдите в аккаунт, чтобы пользоваться поддержкой."; return; }
    if (status) status.textContent = "Загружаем ваши обращения…";
    try {
      const data = await apiRequest("/api/support/tickets");
      mySupportTickets = data.tickets || [];
      setSupportOptions($("#supportMyTicketSelect"), mySupportTickets, "Пока нет обращений");
      if (status) status.textContent = mySupportTickets.length ? "Ваши обращения загружены." : "Обращений пока нет. Можно создать первое выше.";
      const conversation = $("#supportMyConversation");
      if (conversation) conversation.hidden = true;
      selectedMySupportTicket = null;
    } catch (error) { if (status) status.textContent = error.message; }
  };
  const loadMySupportConversation = async ticketId => {
    selectedMySupportTicket = ticketId || null;
    const box = $("#supportMyConversation"), list = $("#supportMyMessages");
    if (!ticketId) { if (box) box.hidden = true; return; }
    try {
      const data = await apiRequest("/api/support/tickets/" + encodeURIComponent(ticketId));
      if (list) { list.replaceChildren(); (data.messages || []).forEach(message => list.append(supportMessageNode(message))); }
      if (box) box.hidden = false;
      const closed = ["resolved","closed"].includes(data.ticket?.status);
      $("#supportUserReplyForm").hidden = closed;
      $("#supportUserStatus").textContent = "Статус: " + (supportStatusLabels[data.ticket?.status] || data.ticket?.status || "—");
    } catch (error) { $("#supportUserStatus").textContent = error.message; if (box) box.hidden = true; }
  };
  $("#supportCreateForm")?.addEventListener("submit", async event => {
    event.preventDefault();
    const status = $("#supportUserStatus");
    if (!authSession?.user) { if (status) status.textContent = "Сначала войдите в аккаунт."; return; }
    const button = event.submitter; if (button) button.disabled = true;
    try {
      await apiRequest("/api/support/tickets", {method:"POST",body:JSON.stringify({subject:$("#supportNewSubject").value,message:$("#supportNewMessage").value})});
      $("#supportNewSubject").value = ""; $("#supportNewMessage").value = "";
      if (status) status.textContent = "Обращение отправлено.";
      await loadMySupportTickets();
    } catch (error) { if (status) status.textContent = error.message; }
    finally { if (button) button.disabled = false; }
  });
  $("#refreshMySupportTickets")?.addEventListener("click", loadMySupportTickets);
  $("#supportMyTicketSelect")?.addEventListener("change", event => loadMySupportConversation(event.target.value));
  $("#supportUserReplyForm")?.addEventListener("submit", async event => {
    event.preventDefault();
    if (!selectedMySupportTicket) return;
    const button = event.submitter; if (button) button.disabled = true;
    try {
      await apiRequest("/api/support/tickets/" + encodeURIComponent(selectedMySupportTicket) + "/messages", {method:"POST",body:JSON.stringify({message:$("#supportUserReply").value})});
      $("#supportUserReply").value = "";
      await loadMySupportConversation(selectedMySupportTicket);
      await loadMySupportTickets();
    } catch (error) { $("#supportUserStatus").textContent = error.message; }
    finally { if (button) button.disabled = false; }
  });
  const loadAdminSupportTickets = async () => {
    const status = $("#adminSupportStatus");
    if (!adminUiAuthorized) { if (status) status.textContent = "Нет доступа."; return; }
    if (status) status.textContent = "Загружаем очередь обращений…";
    try {
      const data = await apiRequest("/api/admin/support/tickets");
      adminSupportTickets = data.tickets || [];
      setSupportOptions($("#adminSupportTicketSelect"), adminSupportTickets, "Новых обращений нет");
      if (status) status.textContent = "Обращений в очереди: " + adminSupportTickets.length + ".";
      $("#adminSupportConversation").hidden = true;
      selectedAdminSupportTicket = null;
    } catch (error) { if (status) status.textContent = error.message; }
  };
  const loadAdminSupportConversation = async ticketId => {
    selectedAdminSupportTicket = ticketId || null;
    const box = $("#adminSupportConversation");
    if (!ticketId) { if (box) box.hidden = true; return; }
    try {
      const data = await apiRequest("/api/admin/support/tickets/" + encodeURIComponent(ticketId));
      $("#adminSupportMessages").replaceChildren(...(data.messages || []).map(message => supportMessageNode(message, true)));
      $("#adminSupportTicketMeta").textContent = data.ticket.subject + " · пользователь " + data.ticket.user_id + " · создано " + new Date(data.ticket.created_at).toLocaleString();
      $("#adminSupportStatusSelect").value = data.ticket.status;
      box.hidden = false;
    } catch (error) { $("#adminSupportFeedback").textContent = error.message; if (box) box.hidden = true; }
  };
  $("#refreshAdminSupport")?.addEventListener("click", loadAdminSupportTickets);
  $("#adminSupportTicketSelect")?.addEventListener("change", event => loadAdminSupportConversation(event.target.value));
  $("#adminSupportReplyForm")?.addEventListener("submit", async event => {
    event.preventDefault(); if (!selectedAdminSupportTicket) return;
    const button = event.submitter; if (button) button.disabled = true;
    try {
      await apiRequest("/api/admin/support/tickets/" + encodeURIComponent(selectedAdminSupportTicket) + "/messages", {method:"POST",body:JSON.stringify({message:$("#adminSupportReply").value})});
      $("#adminSupportReply").value = "";
      await loadAdminSupportConversation(selectedAdminSupportTicket);
      await loadAdminSupportTickets();
      $("#adminSupportTicketSelect").value = selectedAdminSupportTicket;
      await loadAdminSupportConversation(selectedAdminSupportTicket);
      $("#adminSupportFeedback").textContent = "Ответ отправлен.";
    } catch (error) { $("#adminSupportFeedback").textContent = error.message; }
    finally { if (button) button.disabled = false; }
  });
  $("#saveAdminSupportStatus")?.addEventListener("click", async () => {
    if (!selectedAdminSupportTicket) return;
    try {
      const status = $("#adminSupportStatusSelect").value;
      await apiRequest("/api/admin/support/tickets/" + encodeURIComponent(selectedAdminSupportTicket) + "/status", {method:"PATCH",body:JSON.stringify({status})});
      await loadAdminSupportTickets();
      $("#adminSupportTicketSelect").value = selectedAdminSupportTicket;
      await loadAdminSupportConversation(selectedAdminSupportTicket);
      $("#adminSupportFeedback").textContent = "Статус сохранён.";
    } catch (error) { $("#adminSupportFeedback").textContent = error.message; }
  });


  const loadAdminPricingDrafts = async () => {
    const status = $("#pricingDraftStatus");
    if (!adminUiAuthorized) { if (status) status.textContent = "Нет доступа."; return; }
    if (status) status.textContent = "Загружаем версии тарифов…";
    try {
      const data = await apiRequest("/api/admin/pricing/drafts");
      const list = $("#pricingDraftList");
      if (list) {
        list.replaceChildren();
        const active = document.createElement("p");
        active.textContent = "Действующая версия: " + (data.live_catalog_version || "не настроена");
        list.append(active);
        (data.drafts || []).forEach(draft => {
          const card = document.createElement("article");
          card.className = "assistant-message";
          const title = document.createElement("b");
          title.textContent = "Черновик " + draft.version;
          const detail = document.createElement("p");
          detail.textContent = (draft.catalog_json?.rules?.length || 0) + " правил · создан " + new Date(draft.created_at).toLocaleString();
          const note = document.createElement("p");
          note.textContent = "Не активирован · не влияет на стоимость генерации.";
          card.append(title, detail, note);
          list.append(card);
        });
      }
      if (status) status.textContent = "Черновики загружены. Публикация тарифов отключена до отдельной проверки и согласования.";
    } catch (error) { if (status) status.textContent = error.message; }
  };
  $("#refreshPricingDrafts")?.addEventListener("click", loadAdminPricingDrafts);
  $("#pricingDraftForm")?.addEventListener("submit", async event => {
    event.preventDefault();
    if (!adminUiAuthorized) return;
    const status = $("#pricingDraftStatus");
    const button = event.submitter; if (button) button.disabled = true;
    try {
      const rules = JSON.parse($("#pricingDraftRules").value);
      if (!Array.isArray(rules)) throw new Error("Правила должны быть JSON-массивом.");
      const version = $("#pricingDraftVersion").value.trim();
      await apiRequest("/api/admin/pricing/drafts", {method:"POST",body:JSON.stringify({version,rules})});
      $("#pricingDraftVersion").value = "";
      $("#pricingDraftRules").value = "";
      if (status) status.textContent = "Черновик сохранён. Действующие тарифы не изменены.";
      await loadAdminPricingDrafts();
    } catch (error) { if (status) status.textContent = error instanceof SyntaxError ? "Проверьте синтаксис JSON." : error.message; }
    finally { if (button) button.disabled = false; }
  });


  const loadAdminPlanDrafts = async () => {
    const status = $("#planDraftStatus");
    if (!adminUiAuthorized) { if (status) status.textContent = "Нет доступа."; return; }
    if (status) status.textContent = "Загружаем тарифные планы…";
    try {
      const data = await apiRequest("/api/admin/plans/drafts");
      const list = $("#planDraftList");
      if (list) {
        list.replaceChildren();
        (data.drafts || []).forEach(plan => {
          const card = document.createElement("article");
          card.className = "assistant-message";
          const title = document.createElement("b");
          title.textContent = plan.display_name + " · " + plan.plan_code + " v" + plan.plan_version;
          const price = plan.price_minor === null ? "Цена не задана" : String(plan.price_minor) + " " + plan.currency;
          const detail = document.createElement("p");
          detail.textContent = String(plan.credits_per_period) + " кредитов / " + String(plan.period_days) + " дней · " + price;
          const note = document.createElement("p");
          note.textContent = "Черновик · не опубликован · начисления и checkout отключены.";
          card.append(title, detail, note);
          list.append(card);
        });
      }
      if (status) status.textContent = "Черновики загружены. Публикация и начисление кредитов пока отключены.";
    } catch (error) { if (status) status.textContent = error.message; }
  };
  $("#refreshPlanDrafts")?.addEventListener("click", loadAdminPlanDrafts);
  $("#planDraftForm")?.addEventListener("submit", async event => {
    event.preventDefault();
    if (!adminUiAuthorized) return;
    const status = $("#planDraftStatus");
    const button = event.submitter; if (button) button.disabled = true;
    try {
      const limits = JSON.parse($("#planDraftLimits").value || "{}");
      const features = JSON.parse($("#planDraftFeatures").value || "[]");
      if (!limits || typeof limits !== "object" || Array.isArray(limits) || !Array.isArray(features)) throw new Error("Проверьте формат JSON: лимиты — объект, возможности — массив.");
      const rawPrice = $("#planDraftPrice").value.trim();
      const rawCurrency = $("#planDraftCurrency").value.trim().toUpperCase();
      if (Boolean(rawPrice) !== Boolean(rawCurrency)) throw new Error("Укажите одновременно цену и валюту либо оставьте оба поля пустыми.");
      const payload = {
        plan_code: $("#planDraftCode").value.trim(),
        plan_version: Number($("#planDraftVersion").value),
        display_name: $("#planDraftName").value.trim(),
        billing_period: $("#planDraftPeriod").value,
        period_days: $("#planDraftPeriod").value === "week" ? 7 : 30,
        credits_per_period: Number($("#planDraftCredits").value),
        price_minor: rawPrice ? Number(rawPrice) : null,
        currency: rawCurrency || null,
        limits, features
      };
      await apiRequest("/api/admin/plans/drafts", {method:"POST",body:JSON.stringify(payload)});
      $("#planDraftForm").reset();
      $("#planDraftVersion").value = "1";
      $("#planDraftLimits").value = "{}";
      $("#planDraftFeatures").value = "[]";
      if (status) status.textContent = "План сохранён как черновик. Кредиты не начислены, оплата не включена.";
      await loadAdminPlanDrafts();
    } catch (error) { if (status) status.textContent = error instanceof SyntaxError ? "Проверьте синтаксис JSON." : error.message; }
    finally { if (button) button.disabled = false; }
  });

  const loadFinanceAccess = async () => {
    const userId = authSession?.user?.id;
    const panel = $("#financePanel");
    if (!userId || !panel) { financeUiAuthorized = false; financeAccess = null; if (panel) panel.hidden = true; return; }
    try {
      const data = await apiRequest("/api/finance/me");
      if (authSession?.user?.id !== userId) return;
      financeAccess = data;
      financeUiAuthorized = Boolean(data.active && (
        data.can_read_credit_requests || data.can_read_refund_requests
        || (data.permissions || []).some(permission => permission.endsWith(".request"))
      ));
      panel.hidden = !financeUiAuthorized;
      const createPanel = $("#financeRequestCreatePanel");
      if (createPanel) createPanel.hidden = !(data.permissions || []).some(permission =>
        permission === "credit.compensation.request" || permission === "billing.refund.request"
      );
      if (financeUiAuthorized) {
        $("#financeAccessStatus").textContent = "Назначено областей доступа: " + Number(data.scope_count || 0) + ". Полномочия проверяются сервером при каждом действии.";
        loadFinanceQueue(true);
      }
    } catch {
      if (authSession?.user?.id === userId) {
        financeUiAuthorized = false; financeAccess = null; panel.hidden = true;
      }
    }
  };

  if (authSession?.user) setTimeout(loadAccountRole, 0);
  const routeLabels = {home:"Главная",create:"Создание",movie:"Миникиностудия",editor:"Редактор",prompts:"Prompt Studio",library:"Медиатека",account:"Кабинет",voice:"Голос и музыка",scenes:"Сцены",assistant:"AI Companion",guide:"Путеводитель",rules:"Правила",settings:"Настройки",other:"Другие"};
  const formatMetric = value => new Intl.NumberFormat("ru-RU").format(value);
  const loadAdminAiProviders = async () => {
    const status = $("#adminAiProviderStatus"), rows = $("#adminAiProviderRows");
    if (!status || !rows || !adminUiAuthorized) return;
    status.textContent = "Проверяем безопасные метаданные провайдеров…";
    rows.replaceChildren();
    try {
      const data = await apiRequest("/api/admin/ai/providers");
      if (!adminUiAuthorized) return;
      $("#adminAiSelectedProvider").textContent = data.selected_provider || "—";
      $("#adminAiSelectedModel").textContent = "Модель: " + (data.selected_model || "—");
      $("#adminAiKeyStatus").textContent = data.ai_ready ? "Настроен" : "Не настроен";
      $("#adminAiFallbackStatus").textContent = data.automatic_fallback ? "Включено" : "Выключено";
      (data.providers || []).forEach(provider => {
        const tr = document.createElement("tr");
        const tier = provider.pricing_mode === "google_free_tier_eligible"
          ? "Free Tier у модели · доступ проекта не подтверждён"
          : "Платный API";
        [
          provider.label + (provider.selected ? " · активен" : ""),
          provider.model,
          provider.supported ? "Поддерживается" : "Недоступен",
          provider.api_key_configured ? "Да" : "Нет",
          tier
        ].forEach(value => {
          const td = document.createElement("td"); td.textContent = String(value); tr.appendChild(td);
        });
        rows.appendChild(tr);
      });
      const note = $("#adminAiProviderSafetyNote");
      if (note) note.textContent = data.safety_note || "Проверьте тариф и квоты в кабинете провайдера.";
      const limits = data.admission_limits || {};
      status.textContent = (data.runtime_provider_switching
        ? "Провайдер может изменяться настройками."
        : "Текущий провайдер: " + data.selected_provider + ". Переключение выполняется только контролируемым обновлением backend.")
        + " Лимиты: " + (limits.requests_per_user_per_minute ?? "—") + " запросов/мин на пользователя; "
        + (limits.requests_per_user_per_24h ?? "—") + " запросов/24 ч на пользователя; "
        + (limits.requests_global_per_24h ?? "—") + " запросов/24 ч глобально; "
        + "вывод до " + (limits.output_tokens_per_request ?? "—") + " токенов.";
    } catch (error) {
      status.textContent = "Не удалось получить состояние провайдеров: " + error.message;
    }
  };
  $("#refreshAdminAiProviders")?.addEventListener("click", loadAdminAiProviders);

  const loadAdminAiCostBudget = async () => {
    const status = $("#adminAiCostBudgetStatus"), rows = $("#adminAiCostBudgetRows");
    if (!status || !rows || !adminUiAuthorized) return;
    status.textContent = "Загружаем атомарные резервы и дневные USD-лимиты…";
    rows.replaceChildren();
    try {
      const data = await apiRequest("/api/admin/ai/budget");
      if (!adminUiAuthorized) return;
      const money = value => "$" + Number(value || 0).toFixed(6);
      $("#adminAiGlobalBudget").textContent = money(data.global_daily_budget_usd);
      $("#adminAiOutstandingBudget").textContent = money(data.global_outstanding_reserved_usd);
      $("#adminAiRemainingBudget").textContent = money(data.global_remaining_usd);
      const labels = {
        within_limit: "В пределах лимита",
        warning: "Приближается к лимиту",
        threshold_reached: "Дневной лимит достигнут",
        unknown_costs: "Есть неизвестные расходы",
        disabled: "Отключён"
      };
      (data.providers || []).forEach(item => {
        const tr = document.createElement("tr");
        [
          item.provider,
          money(item.daily_budget_usd),
          money(item.settled_estimated_spend_usd),
          money(item.outstanding_reserved_usd),
          money(item.remaining_usd),
          String(item.unknown_reservations || 0),
          labels[item.status] || item.status
        ].forEach(value => {
          const td = document.createElement("td"); td.textContent = String(value); tr.appendChild(td);
        });
        rows.appendChild(tr);
      });
      status.textContent = "Дата UTC: " + data.date_utc
        + ". Общий дневной лимит: " + money(data.global_daily_budget_usd)
        + "; остаток: " + money(data.global_remaining_usd)
        + "; максимальная одновременная экспозиция: " + money(data.max_outstanding_reserved_usd) + ".";
      const note = $("#adminAiCostBudgetNote");
      if (note) note.textContent = data.note || "Оценка стоимости не является фактическим счётом провайдера.";
      const unknown = $("#adminAiUnknownReservation");
      if (unknown) {
        unknown.replaceChildren();
        const empty = document.createElement("option"); empty.value = ""; empty.textContent = "Нет доступных неизвестных резервов"; unknown.append(empty);
        (data.unknown_reservations || []).forEach(item => {
          const option = document.createElement("option"); option.value = item.request_id;
          option.textContent = item.provider + " · " + item.model + " · " + money(item.reserved_cost_usd) + " · " + item.created_at;
          unknown.append(option);
        });
      }
      if ($("#adminAiGlobalDailyLimit")) $("#adminAiGlobalDailyLimit").value = data.global_daily_budget_usd;
      if ($("#adminAiGlobalOutstandingLimit")) $("#adminAiGlobalOutstandingLimit").value = data.max_outstanding_reserved_usd;
      if ($("#adminAiGlobalEnabled")) $("#adminAiGlobalEnabled").checked = Boolean(data.enabled);
      const selectedProvider = (data.providers || []).find(item => item.provider === $("#adminAiBudgetProvider")?.value) || (data.providers || [])[0];
      if (selectedProvider) {
        $("#adminAiBudgetProvider").value = selectedProvider.provider;
        $("#adminAiProviderDailyLimit").value = selectedProvider.daily_budget_usd;
        $("#adminAiProviderEnabled").checked = Boolean(selectedProvider.enabled);
      }
    } catch (error) {
      status.textContent = "Не удалось загрузить денежные лимиты AI: " + error.message;
    }
  };
  $("#refreshAdminAiCostBudget")?.addEventListener("click", loadAdminAiCostBudget);

  const adminAiBudgetControlStatus = $("#adminAiBudgetControlStatus");
  const saveAdminAiGlobalBudget = async () => {
    if (!adminUiAuthorized || !window.confirm("Сохранить новые глобальные USD-лимиты AI? Новые значения начнут действовать сразу после записи.")) return;
    adminAiBudgetControlStatus.textContent = "Сохраняем глобальные лимиты…";
    try {
      await apiRequest("/api/admin/ai/budget/global", {
        method: "PUT", body: JSON.stringify({
          enabled: $("#adminAiGlobalEnabled").checked,
          daily_budget_usd: $("#adminAiGlobalDailyLimit").value,
          max_outstanding_usd: $("#adminAiGlobalOutstandingLimit").value
        })
      });
      adminAiBudgetControlStatus.textContent = "Глобальные лимиты обновлены. Журнал аудита содержит запрос изменения.";
      await loadAdminAiCostBudget();
    } catch (error) { adminAiBudgetControlStatus.textContent = "Не удалось изменить лимиты: " + error.message; }
  };
  $("#saveAdminAiGlobalBudget")?.addEventListener("click", saveAdminAiGlobalBudget);

  $("#saveAdminAiProviderBudget")?.addEventListener("click", async () => {
    if (!adminUiAuthorized || !window.confirm("Сохранить дневной лимит и состояние выбранного AI-провайдера?")) return;
    adminAiBudgetControlStatus.textContent = "Сохраняем лимит провайдера…";
    try {
      await apiRequest("/api/admin/ai/budget/provider", {
        method: "PUT", body: JSON.stringify({
          provider: $("#adminAiBudgetProvider").value,
          enabled: $("#adminAiProviderEnabled").checked,
          daily_budget_usd: $("#adminAiProviderDailyLimit").value
        })
      });
      adminAiBudgetControlStatus.textContent = "Лимит провайдера обновлён.";
      await loadAdminAiCostBudget();
    } catch (error) { adminAiBudgetControlStatus.textContent = "Не удалось изменить лимит: " + error.message; }
  });

  $("#adminAiBudgetProvider")?.addEventListener("change", () => {
    const current = ($("#adminAiCostBudgetRows")?.dataset || {});
    const label = $("#adminAiBudgetProvider").value;
    const row = [...($("#adminAiCostBudgetRows")?.querySelectorAll("tr") || [])].find(item => item.children[0]?.textContent === label);
    if (!row) return;
    $("#adminAiProviderDailyLimit").value = row.children[1].textContent.replace("$", "");
    $("#adminAiProviderEnabled").checked = row.children[6].textContent !== "Отключён";
  });

  $("#resolveAdminAiReservation")?.addEventListener("click", async () => {
    if (!adminUiAuthorized) return;
    const requestId = $("#adminAiUnknownReservation").value;
    const resolution = $("#adminAiReservationResolution").value;
    const note = $("#adminAiReservationNote").value.trim();
    if (!requestId || note.length < 8) {
      adminAiBudgetControlStatus.textContent = "Выберите неизвестный резерв и укажите причину не короче 8 символов.";
      return;
    }
    const cost = $("#adminAiReservationCost").value;
    if (resolution === "record_estimated_cost" && (cost === "" || !Number.isFinite(Number(cost)) || Number(cost) < 0)) {
      adminAiBudgetControlStatus.textContent = "Укажите неотрицательную оценку расхода в USD.";
      return;
    }
    if (!window.confirm("Подтвердить решение по неизвестному резерву? Оно изменит финансовый журнал и не может быть отменено автоматически.")) return;
    adminAiBudgetControlStatus.textContent = "Проверяем и разрешаем резерв…";
    try {
      await apiRequest("/api/admin/ai/budget/reservations/resolve", {
        method: "POST", body: JSON.stringify({
          request_id: requestId, resolution,
          actual_estimated_cost_usd: resolution === "record_estimated_cost" ? cost : null,
          note
        })
      });
      $("#adminAiReservationNote").value = "";
      $("#adminAiReservationCost").value = "";
      adminAiBudgetControlStatus.textContent = "Резерв обработан. Обновляем финансовые показатели…";
      await loadAdminAiCostBudget();
    } catch (error) { adminAiBudgetControlStatus.textContent = "Не удалось обработать резерв: " + error.message; }
  });

  const setAdminAiUsageDefaultDates = () => {
    const to = new Date(), from = new Date(to);
    from.setDate(from.getDate() - 6);
    const iso = value => value.toISOString().slice(0, 10);
    if ($("#adminAiUsageDateFrom") && !$("#adminAiUsageDateFrom").value) $("#adminAiUsageDateFrom").value = iso(from);
    if ($("#adminAiUsageDateTo") && !$("#adminAiUsageDateTo").value) $("#adminAiUsageDateTo").value = iso(to);
  };
  const loadAdminAiUsage = async () => {
    const status = $("#adminAiUsageStatus"), rows = $("#adminAiUsageRows");
    if (!status || !rows || !adminUiAuthorized) return;
    const dateFrom = $("#adminAiUsageDateFrom")?.value;
    const dateTo = $("#adminAiUsageDateTo")?.value;
    if (!dateFrom || !dateTo || dateFrom > dateTo) {
      status.textContent = "Укажите корректный период.";
      return;
    }
    status.textContent = "Загружаем агрегированную статистику…";
    rows.replaceChildren();
    try {
      const data = await apiRequest("/api/admin/ai/usage?date_from=" + encodeURIComponent(dateFrom) + "&date_to=" + encodeURIComponent(dateTo));
      if (!adminUiAuthorized) return;
      const totals = data.totals || {};
      const number = value => new Intl.NumberFormat("ru-RU").format(Number(value || 0));
      $("#adminAiUsageRequests").textContent = number(totals.requests);
      $("#adminAiUsageTokens").textContent = number((totals.input_tokens || 0) + (totals.output_tokens || 0));
      $("#adminAiUsageCost").textContent = Number(totals.reported_estimated_cost_usd || 0).toFixed(6);
      (data.by_provider_model || []).forEach(item => {
        const tr = document.createElement("tr");
        [
          item.provider, item.model, number(item.requests),
          number(item.input_tokens), number(item.output_tokens),
          Number(item.reported_estimated_cost_usd || 0).toFixed(6),
          number(item.cost_unknown_events)
        ].forEach(value => {
          const td = document.createElement("td"); td.textContent = String(value); tr.appendChild(td);
        });
        rows.appendChild(tr);
      });
      const disclaimer = $("#adminAiUsageDisclaimer");
      if (disclaimer) disclaimer.textContent = data.cost_disclaimer || "Оценка стоимости не является фактическим списанием.";
      const budgetLabels = { unconfigured: "лимит не настроен", within_limit: "ниже порога", warning: "внимание: достигнуто 80% лимита", threshold_reached: "порог достигнут", unknown_costs: "есть запросы с неизвестной стоимостью", outside_report_period: "сегодня вне выбранного периода" };
      const budgetSummary = (data.daily_budget_status || []).map(item =>
        item.provider + ": " + (budgetLabels[item.status] || item.status)
        + (item.utilization_percent === null ? "" : " (" + item.utilization_percent + "%)")
      ).join("; ");
      status.textContent = "Период UTC: " + data.period.from + " — " + data.period.to
        + ". Запросов без оценки стоимости: " + number(totals.cost_unknown_events)
        + ". Запросов с неполными данными токенов: " + number(totals.token_count_unknown_events)
        + ". Сегодня: " + (budgetSummary || "нет данных")
        + ". Фактические списания не сверены.";
      if (disclaimer && data.budget_status_note) disclaimer.textContent += " " + data.budget_status_note;
    } catch (error) {
      status.textContent = "Не удалось загрузить статистику: " + error.message;
    }
  };
  setAdminAiUsageDefaultDates();
  $("#loadAdminAiUsage")?.addEventListener("click", loadAdminAiUsage);


  const loadAdminAnalytics = async () => {
    const status = $("#adminAnalyticsStatus");
    const requestedUserId = authSession?.user?.id;
    if (!requestedUserId || !$("#adminPanel") || $("#adminPanel").hidden) return;
    if (status) status.textContent = "Обновляем агрегированную статистику…";
    try {
      const data = await apiRequest("/api/admin/analytics/site-visits");
      if (authSession?.user?.id !== requestedUserId || $("#adminPanel").hidden) return;
      $("#adminTotalVisits").textContent = formatMetric(data.total_page_views);
      $("#adminTodayVisits").textContent = formatMetric(data.today_page_views);
      $("#adminUniqueToday").textContent = formatMetric(data.today_unique_visitors);
      $("#adminWeekVisits").textContent = formatMetric(data.last_7_days_page_views);
      $("#adminMonthVisits").textContent = formatMetric(data.last_30_days_page_views);
      $("#adminRateLimited").textContent = formatMetric(data.rate_limited_requests_last_24h);
      const chart = $("#adminVisitsChart"); chart.replaceChildren();
      const series = data.daily_series || [];
      const max = Math.max(1, ...series.map(row => row.page_views));
      series.forEach(row => {
        const bar = document.createElement("button"); bar.type = "button";
        bar.style.setProperty("--bar-height", Math.max(3, Math.round(row.page_views / max * 100)) + "%");
        bar.title = row.date + ": " + formatMetric(row.page_views) + " просмотров";
        bar.setAttribute("aria-label", bar.title);
        const label = document.createElement("span"); label.textContent = row.date.slice(8, 10);
        bar.appendChild(label); chart.appendChild(bar);
      });
      const routes = $("#adminPopularRoutes"); routes.replaceChildren();
      const routeRows = data.top_routes || [];
      if (!routeRows.length) {
        const empty = document.createElement("span"); empty.className = "helper-text";
        empty.textContent = "Пока нет накопленных данных по разделам."; routes.appendChild(empty);
      } else {
        const routeMax = Math.max(1, ...routeRows.map(row => row.page_views));
        routeRows.forEach(row => {
          const item = document.createElement("div"); item.className = "owner-route-row";
          const name = document.createElement("span"); name.textContent = routeLabels[row.route_group] || "Другие";
          const track = document.createElement("div"); track.className = "owner-route-bar";
          const fill = document.createElement("i"); fill.style.width = Math.round(row.page_views / routeMax * 100) + "%"; track.appendChild(fill);
          const count = document.createElement("strong"); count.textContent = formatMetric(row.page_views);
          item.append(name, track, count); routes.appendChild(item);
        });
      }
      if (status) status.textContent = "Данные обновлены. Период графика и разделов — последние 30 дней (UTC).";
    } catch (error) {
      if (status) status.textContent = "Не удалось загрузить статистику: " + error.message;
    }
  };
  $("#refreshSiteAnalytics")?.addEventListener("click", loadAdminAnalytics);

  let adminAuditCursor = null;
  let adminAuditLoading = false;
  const loadAdminAuditEvents = async (reset = false) => {
    const status = $("#adminAuditStatus");
    const body = $("#adminAuditRows");
    const more = $("#loadMoreAdminAudit");
    if (!body || adminAuditLoading || !adminUiAuthorized) return;
    adminAuditLoading = true;
    if (reset) { body.replaceChildren(); adminAuditCursor = null; }
    if (status) status.textContent = "Загружаем защищённый журнал…";
    if (more) more.disabled = true;
    try {
      const query = new URLSearchParams({limit:"50"});
      if (adminAuditCursor) {
        query.set("before", adminAuditCursor.before);
        query.set("before_id", adminAuditCursor.before_id);
      }
      const data = await apiRequest("/api/admin/audit-events?" + query.toString());
      if (!adminUiAuthorized) return;
      const rows = Array.isArray(data.events) ? data.events : [];
      rows.forEach(row => {
        const tr = document.createElement("tr");
        [row.occurred_at, row.actor_user_id, row.action, row.outcome, row.resource_type, row.reason || "—"].forEach(value => {
          const td = document.createElement("td");
          td.textContent = String(value ?? "—");
          tr.appendChild(td);
        });
        body.appendChild(tr);
      });
      adminAuditCursor = data.next_cursor || null;
      if (status) status.textContent = rows.length ? "Показаны последние события аудита. Секреты и содержимое пользовательских запросов не записываются." : "В журнале пока нет событий.";
      if (more) more.hidden = !adminAuditCursor;
    } catch (error) {
      if (status) status.textContent = "Не удалось загрузить журнал: " + error.message;
    } finally {
      adminAuditLoading = false;
      if (more) more.disabled = false;
    }
  };
  $("#refreshAdminAudit")?.addEventListener("click", () => loadAdminAuditEvents(true));
  $("#loadMoreAdminAudit")?.addEventListener("click", () => loadAdminAuditEvents(false));
  
  const localDateInput = (date) => {
    const y = date.getFullYear(), m = String(date.getMonth() + 1).padStart(2, "0"), d = String(date.getDate()).padStart(2, "0");
    return y + "-" + m + "-" + d;
  };
  const costFrom = $("#adminCostDateFrom"), costTo = $("#adminCostDateTo");
  if (costFrom && costTo) {
    const today = new Date(), weekAgo = new Date(today);
    weekAgo.setDate(today.getDate() - 6);
    costFrom.value = localDateInput(weekAgo); costTo.value = localDateInput(today);
  }
  const loadAdminProviderCosts = async () => {
    const status = $("#adminProviderCostStatus"), body = $("#adminProviderCostRows");
    if (!status || !body || !adminUiAuthorized) return;
    const from = costFrom?.value, to = costTo?.value;
    if (!from || !to || from > to) { status.textContent = "Укажите корректный период."; return; }
    const days = (Date.parse(to + "T00:00:00Z") - Date.parse(from + "T00:00:00Z")) / 86400000 + 1;
    if (!Number.isInteger(days) || days < 1 || days > 31) { status.textContent = "Период должен составлять от 1 до 31 дня."; return; }
    status.textContent = "Загружаем подтверждённые данные…"; body.replaceChildren();
    try {
      const data = await apiRequest("/api/admin/financial/provider-costs?date_from=" + encodeURIComponent(from) + "&date_to=" + encodeURIComponent(to));
      if (!adminUiAuthorized) return;
      $("#adminKnownProviderCost").textContent = String(data.known_provider_cost_usd ?? "—");
      $("#adminProviderCostEvents").textContent = formatMetric(data.event_count ?? 0);
      $("#adminUnknownProviderCosts").textContent = formatMetric(data.cost_evidence?.unknown ?? 0);
      (data.by_provider_model || []).forEach(row => {
        const tr = document.createElement("tr");
        [row.provider, row.model, formatMetric(row.events), String(row.known_cost_usd), formatMetric(row.unknown_events)].forEach(value => {
          const td = document.createElement("td"); td.textContent = String(value ?? "—"); tr.appendChild(td);
        });
        body.appendChild(tr);
      });
      if (!body.children.length) {
        const tr = document.createElement("tr"), td = document.createElement("td");
        td.colSpan = 5; td.textContent = "За выбранный период записей нет."; tr.appendChild(td); body.appendChild(tr);
      }
      status.textContent = "Отчёт за " + from + " — " + to + " (UTC). Неизвестные суммы не включены в известный итог.";
    } catch (error) { status.textContent = "Отчёт недоступен: " + error.message; }
  };
  $("#loadAdminProviderCosts")?.addEventListener("click", loadAdminProviderCosts);

  const loadAdminWallet = async () => {
    const status = $("#adminWalletStatus"), id = $("#adminWalletUserId")?.value.trim();
    if (!status || !adminUiAuthorized) return;
    if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(id || "")) {
      status.textContent = "Введите корректный UUID аккаунта."; return;
    }
    status.textContent = "Проверяем доступ и загружаем сводку…";
    ["adminWalletAvailable","adminWalletReserved","adminWalletTotal"].forEach(key => { const el = $("#" + key); if (el) el.textContent = "—"; });
    try {
      const data = await apiRequest("/api/admin/financial/wallets/" + encodeURIComponent(id));
      if (!adminUiAuthorized) return;
      $("#adminWalletAvailable").textContent = formatMetric(data.available_credits);
      $("#adminWalletReserved").textContent = formatMetric(data.reserved_credits);
      $("#adminWalletTotal").textContent = formatMetric(data.total_credits);
      $("#adminWalletDetails").textContent = "Активных резервов: " + formatMetric(data.active_holds_count) + " · партий: " + formatMetric(data.lot_count) + " · распределений: " + formatMetric(data.allocation_count) + ".";
      status.textContent = "Сводка загружена. Доступ к кошельку записан в административный аудит.";
      loadAdminCreditLedger(true);
    } catch (error) { status.textContent = "Сводка недоступна: " + error.message; }
  };
  $("#loadAdminWallet")?.addEventListener("click", loadAdminWallet);

  let adminCreditLedgerCursor = null, adminCreditLedgerLoading = false;
  const loadAdminCreditLedger = async (reset = false) => {
    const body = $("#adminCreditLedgerRows"), status = $("#adminCreditLedgerStatus");
    const more = $("#loadMoreAdminCreditLedger"), id = $("#adminWalletUserId")?.value.trim();
    if (!body || !status || adminCreditLedgerLoading || !adminUiAuthorized) return;
    if (!id) { status.textContent = "Сначала укажите UUID пользователя в блоке кошелька."; return; }
    adminCreditLedgerLoading = true;
    if (reset) { body.replaceChildren(); adminCreditLedgerCursor = null; }
    if (more) more.disabled = true;
    status.textContent = "Загружаем журнал кредитных единиц…";
    try {
      const query = new URLSearchParams({limit:"50"});
      if (adminCreditLedgerCursor) {
        query.set("before_created_at", adminCreditLedgerCursor.before_created_at);
        query.set("before_id", String(adminCreditLedgerCursor.before_id));
      }
      const data = await apiRequest("/api/admin/financial/ledger/" + encodeURIComponent(id) + "?" + query.toString());
      if (!adminUiAuthorized || $("#adminWalletUserId")?.value.trim() !== id) return;
      (data.entries || []).forEach(row => {
        const tr = document.createElement("tr");
        const operation = ({grant:"Начисление",reserve:"Резерв",capture:"Списание",release:"Возврат резерва",refund:"Возврат",adjustment:"Корректировка"})[row.operation_type] || row.operation_type;
        const available = (row.delta_available > 0 ? "+" : "") + row.delta_available;
        const reserved = (row.delta_reserved > 0 ? "+" : "") + row.delta_reserved;
        const balance = row.balance_available_after + " / " + row.balance_reserved_after;
        [new Date(row.created_at).toLocaleString("ru-RU",{timeZone:"UTC"}) + " UTC",operation,available,reserved,balance]
          .forEach(value => { const td=document.createElement("td"); td.textContent=String(value); tr.appendChild(td); });
        body.appendChild(tr);
      });
      adminCreditLedgerCursor = data.next_cursor || null;
      if (!body.children.length) {
        const tr=document.createElement("tr"),td=document.createElement("td");
        td.colSpan=5; td.textContent="Записей в кредитном журнале пока нет."; tr.appendChild(td); body.appendChild(tr);
      }
      status.textContent = data.accounting_note || "Показан журнал кредитных единиц. Это не денежная отчётность.";
      if (more) more.hidden = !adminCreditLedgerCursor;
    } catch(error) { status.textContent = "Журнал недоступен: " + error.message; }
    finally { adminCreditLedgerLoading=false; if(more) more.disabled=false; }
  };
  $("#loadMoreAdminCreditLedger")?.addEventListener("click", () => loadAdminCreditLedger(false));



  let financeQueueCursor = null;
  let financeQueueLoading = false;
  const financePermission = (requestType, action) => {
    const prefix = requestType === "credit_compensation" ? "credit.compensation" : "billing.refund";
    return Boolean(financeAccess?.permissions?.includes(prefix + "." + action));
  };
  const loadFinanceQueue = async (reset = false) => {
    const body = $("#financeQueueRows");
    const statusText = $("#financeQueueStatusText");
    const more = $("#loadMoreFinanceQueue");
    if (!body || financeQueueLoading || !financeUiAuthorized) return;
    financeQueueLoading = true;
    if (reset) { body.replaceChildren(); financeQueueCursor = null; }
    if (statusText) statusText.textContent = "Загружаем очередь в пределах назначенных полномочий…";
    if (more) more.disabled = true;
    try {
      const query = new URLSearchParams({limit:"50"});
      const selectedStatus = $("#financeQueueStatus")?.value || "";
      if (selectedStatus) query.set("status", selectedStatus);
      if (financeQueueCursor) {
        query.set("before", financeQueueCursor.before);
        query.set("before_id", financeQueueCursor.before_id);
      }
      const data = await apiRequest("/api/finance/requests?" + query.toString());
      if (!financeUiAuthorized) return;
      const rows = Array.isArray(data.items) ? data.items : [];
      rows.forEach(row => {
        const tr = document.createElement("tr");
        const typeLabel = row.request_type === "credit_compensation" ? "Компенсация кредитов" : "Денежный возврат";
        const stateLabel = ({pending:"Ожидает",approved:"Подтверждена",rejected:"Отклонена",cancelled:"Отменена"})[row.status] || row.status;
        const values = [
          row.requested_at ? new Date(row.requested_at).toLocaleString("ru-RU") : "—",
          row.requester_id, row.target_user_id, typeLabel,
          String(row.amount) + " " + row.currency_code, stateLabel, row.reason || "—"
        ];
        values.forEach(value => {
          const td = document.createElement("td"); td.textContent = String(value ?? "—"); tr.appendChild(td);
        });
        const actions = document.createElement("td");
        if (row.status === "pending" && row.requester_id === authSession?.user?.id && financePermission(row.request_type, "cancel")) {
          const cancel = document.createElement("button"); cancel.type = "button"; cancel.className = "secondary-button"; cancel.textContent = "Отменить";
          cancel.addEventListener("click", async () => {
            const reason = window.prompt("Причина отмены заявки (1–500 символов):");
            if (!reason || !reason.trim()) return;
            try {
              await apiRequest("/api/finance/requests/" + encodeURIComponent(row.request_id) + "/cancel", {
                method:"POST", body:JSON.stringify({reason:reason.trim()})
              });
              loadFinanceQueue(true);
            } catch (error) { if (statusText) statusText.textContent = "Не удалось отменить заявку: " + error.message; }
          });
          actions.appendChild(cancel);
        } else if (row.status === "pending" && row.requester_id !== authSession?.user?.id && financePermission(row.request_type, "approve")) {
          ["approve","reject"].forEach(decision => {
            const button = document.createElement("button"); button.type = "button"; button.className = "secondary-button";
            button.textContent = decision === "approve" ? "Подтвердить" : "Отклонить";
            button.addEventListener("click", async () => {
              const reason = window.prompt("Обоснование решения (1–500 символов):");
              if (!reason || !reason.trim()) return;
              try {
                await apiRequest("/api/finance/requests/" + encodeURIComponent(row.request_id) + "/decision", {
                  method:"POST", body:JSON.stringify({decision,reason:reason.trim()})
                });
                loadFinanceQueue(true);
              } catch (error) { if (statusText) statusText.textContent = "Решение не сохранено: " + error.message; }
            });
            actions.appendChild(button);
          });
        } else {
          actions.textContent = row.decision_reason || "—";
        }
        const timelineButton = document.createElement("button");
        timelineButton.type = "button"; timelineButton.className = "secondary-button"; timelineButton.textContent = "История";
        timelineButton.addEventListener("click", async () => {
          const existing = tr.nextElementSibling;
          if (existing?.classList.contains("finance-event-row")) { existing.remove(); return; }
          timelineButton.disabled = true;
          try {
            const history = await apiRequest("/api/finance/requests/" + encodeURIComponent(row.request_id) + "/events");
            const detailRow = document.createElement("tr"); detailRow.className = "finance-event-row";
            const detailCell = document.createElement("td"); detailCell.colSpan = 8;
            const list = document.createElement("ol");
            (history.events || []).forEach(event => {
              const item = document.createElement("li");
              const label = ({ "request.created":"Заявка создана", "request.approved":"Заявка подтверждена", "request.rejected":"Заявка отклонена", "request.cancelled":"Заявка отменена" })[event.event_type] || event.event_type;
              item.textContent = new Date(event.occurred_at).toLocaleString("ru-RU") + " · " + label + " · " + event.actor_id + " · " + event.reason;
              list.appendChild(item);
            });
            if (!list.children.length) {
              const empty = document.createElement("span"); empty.textContent = "История пока пуста."; detailCell.appendChild(empty);
            } else detailCell.appendChild(list);
            detailRow.appendChild(detailCell); tr.after(detailRow);
          } catch (error) {
            const detailRow = document.createElement("tr"); detailRow.className = "finance-event-row";
            const detailCell = document.createElement("td"); detailCell.colSpan = 8;
            detailCell.textContent = "Не удалось загрузить историю: " + error.message;
            detailRow.appendChild(detailCell); tr.after(detailRow);
          } finally { timelineButton.disabled = false; }
        });
        actions.appendChild(timelineButton);
        tr.appendChild(actions); body.appendChild(tr);
      });
      financeQueueCursor = data.next_cursor || null;
      if (statusText) statusText.textContent = rows.length
        ? "Заявки загружены. Все действия проходят повторную серверную проверку."
        : "В назначенных областях пока нет заявок.";
      if (more) more.hidden = !financeQueueCursor;
    } catch (error) {
      if (statusText) statusText.textContent = "Не удалось загрузить очередь: " + error.message;
    } finally {
      financeQueueLoading = false;
      if (more) more.disabled = false;
    }
  };
  $("#refreshFinanceQueue")?.addEventListener("click", () => loadFinanceQueue(true));
  $("#loadMoreFinanceQueue")?.addEventListener("click", () => loadFinanceQueue(false));
  $("#financeQueueStatus")?.addEventListener("change", () => loadFinanceQueue(true));

  const updateFinanceRequestForm = () => {
    const type = $("#financeRequestType")?.value;
    const currency = $("#financeRequestCurrency");
    const amount = $("#financeRequestAmount");
    if (!currency || !amount) return;
    if (type === "credit_compensation") {
      currency.value = "CRD"; currency.disabled = true; amount.min = "1"; amount.step = "1";
    } else {
      currency.disabled = false;
      if (currency.value === "CRD") currency.value = "KZT";
      amount.min = "0.0001"; amount.step = "0.0001";
    }
  };
  $("#financeRequestType")?.addEventListener("change", updateFinanceRequestForm);
  updateFinanceRequestForm();
  let financePendingSubmission = null;
  $("#financeRequestCreateForm")?.addEventListener("submit", async event => {
    event.preventDefault();
    const type = $("#financeRequestType").value;
    const permission = type === "credit_compensation" ? "credit.compensation.request" : "billing.refund.request";
    if (!financeAccess?.permissions?.includes(permission)) return;
    const button = $("#submitFinanceRequest"); button.disabled = true;
    try {
      const target = $("#financeTargetUserId").value.trim();
      const draft = {
        request_type:type, target_user_id:target,
        amount:$("#financeRequestAmount").value,
        currency_code:$("#financeRequestCurrency").value,
        reason:$("#financeRequestReason").value.trim()
      };
      const fingerprint = JSON.stringify(draft);
      if (!financePendingSubmission || financePendingSubmission.fingerprint !== fingerprint) {
        financePendingSubmission = {fingerprint, key:crypto.randomUUID()};
      }
      const payload = {...draft, idempotency_key:financePendingSubmission.key};
      await apiRequest("/api/finance/requests", {method:"POST",body:JSON.stringify(payload)});
      financePendingSubmission = null;
      $("#financeRequestCreateForm").reset(); updateFinanceRequestForm();
      $("#financeQueueStatus").value = "pending";
      loadFinanceQueue(true);
      $("#financeQueueStatusText").textContent = "Заявка отправлена на независимое рассмотрение.";
    } catch (error) {
      $("#financeQueueStatusText").textContent = "Заявка не создана: " + error.message;
    } finally { button.disabled = false; }
  });

  const financeRoleStatus = $("#financeRoleAdminStatus");
  const loadFinanceRoles = async (principalId) => {
    if (!adminUiAuthorized || !principalId) return;
    const rows = $("#financeRoleRows"); if (!rows) return;
    rows.replaceChildren();
    if (financeRoleStatus) financeRoleStatus.textContent = "Загружаем активные назначения…";
    try {
      const data = await apiRequest("/api/admin/finance/roles/" + encodeURIComponent(principalId));
      (data.assignments || []).forEach(assignment => {
        const tr = document.createElement("tr");
        [assignment.role_code, assignment.scope_key, assignment.valid_until, assignment.granted_by].forEach(value => {
          const td = document.createElement("td"); td.textContent = String(value ?? "—"); tr.appendChild(td);
        });
        const actions = document.createElement("td");
        const revoke = document.createElement("button"); revoke.type = "button"; revoke.className = "secondary-button"; revoke.textContent = "Отозвать";
        revoke.addEventListener("click", async () => {
          const reason = window.prompt("Причина отзыва роли (1–500 символов):");
          if (!reason || !reason.trim()) return;
          revoke.disabled = true;
          try {
            await apiRequest("/api/admin/finance/roles/" + encodeURIComponent(assignment.assignment_id) + "/revoke", {
              method:"POST", body:JSON.stringify({reason:reason.trim()})
            });
            await loadFinanceRoles(principalId);
          } catch (error) {
            if (financeRoleStatus) financeRoleStatus.textContent = "Не удалось отозвать роль: " + error.message;
            revoke.disabled = false;
          }
        });
        actions.appendChild(revoke); tr.appendChild(actions); rows.appendChild(tr);
      });
      if (financeRoleStatus) financeRoleStatus.textContent = data.assignments?.length
        ? "Показаны активные назначения. Истёкшие и отозванные назначения не выдаются как активные."
        : "У аккаунта нет активных финансовых назначений.";
    } catch (error) {
      if (financeRoleStatus) financeRoleStatus.textContent = "Не удалось загрузить назначения: " + error.message;
    }
  };
  $("#loadFinanceRoles")?.addEventListener("click", () => loadFinanceRoles($("#financeRoleLookupId").value.trim()));
  $("#financeRoleGrantForm")?.addEventListener("submit", async event => {
    event.preventDefault();
    if (!adminUiAuthorized) return;
    const button = $("#grantFinanceRoleButton"); button.disabled = true;
    try {
      const principalId = $("#financeRolePrincipalId").value.trim();
      const scopeTargetId = $("#financeRoleScopeUserId").value.trim();
      const validUntil = new Date($("#financeRoleValidUntil").value);
      if (!Number.isFinite(validUntil.getTime()) || validUntil <= new Date()) {
        throw new Error("Укажите будущую дату окончания полномочий.");
      }
      const payload = {
        principal_id:principalId,
        role_code:$("#financeRoleCode").value,
        scope_key:"user:" + scopeTargetId.toLowerCase(),
        valid_until:validUntil.toISOString(),
        reason:$("#financeRoleReason").value.trim()
      };
      await apiRequest("/api/admin/finance/roles", {method:"POST",body:JSON.stringify(payload)});
      $("#financeRoleLookupId").value = principalId;
      $("#financeRoleReason").value = "";
      if (financeRoleStatus) financeRoleStatus.textContent = "Роль назначена. Проверяем сохранённое назначение…";
      await loadFinanceRoles(principalId);
    } catch (error) {
      if (financeRoleStatus) financeRoleStatus.textContent = "Назначение не сохранено: " + error.message;
    } finally { button.disabled = false; }
  });

  const labels = {"finance-operations":"Финансовые операции","admin-platform":"Управление платформой","admin-technical":"Технический и финансовый центр",guestspace:"Гостевое пространство",account:"Личный кабинет",rules:"Правила и безопасность",home:"Главная",create:"Создать видео",movie:"Миникиностудия",editor:"Видеоредактор",prompts:"Prompt Studio",library:"Медиатека",voice:"Голос и музыка",scenes:"Сценарий и сцены",assistant:"AI Companion",guide:"Путеводитель",about:"О студии",settings:"Настройки"};

  function navigate(view) {
    if (!labels[view]) return;
    if (view.startsWith("admin-") && !adminUiAuthorized) { view = "account"; window.location.hash = "account"; }
    if (view === "finance-operations" && !financeUiAuthorized) { view = "account"; window.location.hash = "account"; }
    $$(".view").forEach(el => el.classList.toggle("active", el.id === "view-" + view));
    $$(".nav-item[data-view]").forEach(el => el.classList.toggle("active", el.dataset.view === view));
    $("#crumbCurrent").textContent = labels[view];
    $("#sidebar").classList.remove("open");
    window.location.hash = view === "home" ? "" : view;
    window.scrollTo({top:0,behavior:"smooth"});
    if (view === "account" && authSession?.user) { loadMySupportTickets(); if (adminUiAuthorized) { loadAdminSupportTickets(); loadAdminPricingDrafts(); loadAdminPlanDrafts(); } }
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
  window.addEventListener("hashchange", () => {
    const view = location.hash.replace(/^#/, "") || "home";
    if (labels[view]) navigate(view);
  });

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

  let lastGeneratedPrompt = null;
  $("#buildPrompt").addEventListener("click", async () => {
    if (!authSession?.user) { setAuthMode("signup"); setAuthMessage("Войдите или зарегистрируйтесь, чтобы пользоваться AI-инструментами."); return; }
    const requestUserId = authSession.user.id;
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
        body: JSON.stringify({
          idea,
          purpose: $("#promptType").value,
          language: $("#promptLanguage").value,
          style: "Cinematic, coherent, detailed",
          ...(activeMovieId && movieRead().some(project => project.id === activeMovieId) ? {
            project_context: (() => {
              const project = movieRead().find(item => item.id === activeMovieId);
              return {
                title: String(project.name || "Без названия").slice(0, 120),
                idea: String(project.idea || "").slice(0, 2000),
                genre: String(project.genre || "").slice(0, 80),
                duration_minutes: Number.isInteger(project.duration) ? Math.min(30, Math.max(1, project.duration)) : null,
                frame: ["16:9", "9:16", "1:1"].includes(project.frame) ? project.frame : null,
                story: String(project.story || "").slice(0, 6000),
                storyboard: String(project.storyboard || "").slice(0, 6000),
                characters: String(project.characters || "").slice(0, 3000),
                visual_continuity: (Array.isArray(project.visualContinuity)?project.visualContinuity:[]).slice(0,12).map(ref=>({type:ref.type==="scene"?"scene":"character",name:String(ref.name||"").slice(0,80),description:String(ref.description||"").slice(0,3000),...(ref.passport?{passport:{face:String(ref.passport.face||"").slice(0,600),profile:String(ref.passport.profile||"").slice(0,600),fullBody:String(ref.passport.fullBody||"").slice(0,600),wardrobe:String(ref.passport.wardrobe||"").slice(0,800),palette:String(ref.passport.palette||"").slice(0,300),expressions:String(ref.passport.expressions||"").slice(0,500)}}:{})})),
                voices: String(project.voices || "").slice(0, 2000),
                edit: String(project.edit || "").slice(0, 2000)
              };
            })()
          } : {})
        })
      });
      if (authSession?.user?.id !== requestUserId) return;
      $("#promptOutput").textContent = result.prompt;
      lastGeneratedPrompt = {
        prompt: result.prompt,
        purpose: $("#promptType").value,
        language: $("#promptLanguage").value,
        idea,
        provider: result.provider,
        model: result.model,
        createdAt: new Date().toISOString()
      };
      $("#promptSaveFeedback").textContent = activeMovieId
        ? "Промпт готов. Его можно сохранить в выбранный фильм."
        : "Промпт готов. Чтобы сохранить его, сначала откройте фильм в Миникиностудии.";
      $("#promptFeedback").textContent = "Готово: ответ получен от " + result.provider + " · " + result.model + ".";
    } catch (error) {
      if (authSession?.user?.id === requestUserId) $("#promptFeedback").textContent = error.message;
    } finally {
      button.disabled = false;
      button.textContent = "✦ Сформировать промт";
    }
  });

  let editingPromptRef = null;
  const promptVersionStyle = document.createElement("style");
  promptVersionStyle.textContent = `
    .prompt-version-history{margin:10px 0;padding:10px 12px;border:1px solid var(--line);border-radius:12px;background:rgba(135,105,220,.045)}
    .prompt-version-history summary{cursor:pointer;font-size:12px;font-weight:700;color:var(--muted)}
    .prompt-version-row{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;padding:10px 0;border-top:1px solid var(--line)}
    .prompt-block-builder{margin:14px 0;padding:14px;border:1px solid rgba(170,140,255,.25);border-radius:14px;background:rgba(135,105,220,.06)}
    .prompt-visual-library{margin:16px 0;padding:14px;border:1px solid var(--border);border-radius:14px;background:var(--surface)}.prompt-visual-library textarea{width:100%;resize:vertical}.prompt-visual-list{display:grid;gap:9px;margin-top:12px}.prompt-visual-card{padding:11px;border:1px solid var(--border);border-radius:11px;background:var(--card,transparent)}.prompt-visual-card p{margin:7px 0;white-space:pre-wrap;overflow-wrap:anywhere}.prompt-preset-row{display:flex;align-items:end;gap:9px;margin:12px 0}.prompt-preset-row>div{flex:1;min-width:0}.prompt-preset-row select{width:100%;min-height:42px;padding:9px;border:1px solid var(--border);border-radius:10px;background:var(--surface);color:var(--text)}
    .prompt-block-controls{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}.prompt-block-list{display:grid;gap:8px;margin-top:10px}
    .prompt-builder-block{display:grid;grid-template-columns:1fr auto;gap:6px 12px;padding:11px;border:1px solid var(--border);border-radius:11px;background:var(--surface)}
    .prompt-builder-block b{font-size:13px}.prompt-builder-block p{grid-column:1;white-space:pre-wrap;overflow-wrap:anywhere;margin:0;color:var(--muted);font-size:12px;line-height:1.5}
    .prompt-builder-block button{grid-column:2;grid-row:1/3;align-self:center}
    @media(max-width:520px){.prompt-preset-row{align-items:stretch;flex-direction:column}.prompt-preset-row button{width:100%}.prompt-block-controls button{flex:1}.prompt-builder-block{grid-template-columns:1fr}.prompt-builder-block p,.prompt-builder-block button{grid-column:1;grid-row:auto}.prompt-builder-block button{justify-self:start}}
    .prompt-workbench,.prompt-fragments{margin:14px 0;padding:14px;border:1px solid rgba(170,140,255,.2);border-radius:14px;background:rgba(135,105,220,.045)}
    .prompt-workbench-head{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:10px}.prompt-workbench-head span,.prompt-variable-tools small{font-size:11px;color:var(--muted)}
    .prompt-workbench-action{display:flex;align-items:end}.prompt-workbench-action button{width:100%;min-height:42px}
    .prompt-variable-tools{display:grid;gap:8px;margin-top:12px}.prompt-variable-tools textarea{width:100%;padding:11px;border:1px solid var(--border);border-radius:10px;background:var(--surface);color:var(--text);font:inherit;resize:vertical}
    .prompt-fragment-actions{display:flex;gap:8px;flex-wrap:wrap}.prompt-fragment-actions input{flex:1;min-width:150px;padding:10px;border:1px solid var(--border);border-radius:10px;background:var(--surface);color:var(--text)}
    .prompt-fragment-list{display:grid;gap:8px;margin-top:10px}.prompt-fragment-row{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:10px;border:1px solid var(--border);border-radius:10px}.prompt-fragment-info{display:grid;gap:5px;min-width:0}.prompt-fragment-info small{color:var(--muted);overflow-wrap:anywhere}
    @media(max-width:520px){.prompt-fragment-row{align-items:stretch;flex-direction:column}.prompt-workbench-head{align-items:flex-start;flex-direction:column}}
    .prompt-editor-toolbar{display:flex;flex-wrap:wrap;gap:7px;margin:12px 0}
    .prompt-editor-toolbar button{font-size:12px;padding:8px 10px}
    .prompt-output[contenteditable="true"]{outline:1px solid rgba(170,140,255,.45);cursor:text}
    .prompt-output[contenteditable="true"]:focus{outline:2px solid rgba(170,140,255,.75)}
    .prompt-version-row>div{min-width:0}.prompt-version-row b{font-size:12px}.prompt-version-row p{margin:5px 0 0;overflow-wrap:anywhere}
    .prompt-version-compare{margin:12px 0;padding:12px;border:1px solid rgba(170,140,255,.22);border-radius:12px;background:rgba(8,7,18,.18)}
    .prompt-version-compare-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
    .prompt-version-compare-pane{min-width:0}.prompt-version-compare-pane h4{margin:0 0 7px;font-size:12px;color:var(--muted)}
    .prompt-version-compare-pane pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:360px;overflow:auto;margin:0;padding:10px;border-radius:8px;background:rgba(0,0,0,.16);font-family:inherit;font-size:12px;line-height:1.55}
    .prompt-version-compare-pane pre span{display:block;padding:1px 4px;border-radius:3px}
    .prompt-version-compare-pane pre .diff-added{background:rgba(65,180,115,.18)}
    .prompt-version-compare-pane pre .diff-removed{background:rgba(220,90,90,.18)}
    .prompt-version-compare-note{font-size:11px;color:var(--muted);margin:8px 0 0}
    @media(max-width:640px){.prompt-version-compare-grid{grid-template-columns:1fr}}
    @media(max-width:480px){.prompt-version-row{flex-direction:column}.prompt-version-row button{width:100%}}
  `;
  document.head.appendChild(promptVersionStyle);
  const promptModeLabels = { video:"Видео", image:"Изображения", music:"Музыка", sound:"Звуковые эффекты", script:"Сценарий", character:"Персонажи", voice:"Голос", storyboard:"Раскадровка" };
  const snapshotPromptVersion = prompt => ({
    prompt: String(prompt.prompt || "").slice(0,12000),
    idea: String(prompt.idea || "").slice(0,2000),
    purpose: String(prompt.purpose || "").slice(0,40),
    language: String(prompt.language || "").slice(0,40),
    provider: String(prompt.provider || "").slice(0,100),
    model: String(prompt.model || "").slice(0,100),
    savedAt: String(prompt.updatedAt || prompt.createdAt || new Date().toISOString())
  });
  const promptVersionLabel = version => {
    const date = new Date(version.savedAt);
    return Number.isNaN(date.getTime()) ? "Дата неизвестна" : date.toLocaleString("ru-RU");
  };
  const resetPromptEditing = () => {
    editingPromptRef = null;
    $("#promptOutput").contentEditable = "false";
    $("#savePromptToMovie").textContent = "＋ Сохранить в выбранный фильм";
    $("#cancelPromptEdit").hidden = true;
  };
  const renderPromptLibrary = () => {
    const list = $("#promptLibraryList");
    if (!list) return;
    const projects = movieRead();
    const entries = projects.flatMap(project => (Array.isArray(project.prompts) ? project.prompts : []).map((prompt, index) => ({
      projectId: project.id, projectName: project.name || "Без названия", prompt, index
    }))).filter(entry => entry.prompt && typeof entry.prompt.prompt === "string");
    const query = ($("#promptLibrarySearch")?.value || "").trim().toLocaleLowerCase();
    const category = $("#promptLibraryCategory")?.value || "";
    const filtered = entries.filter(entry => {
      const p = entry.prompt;
      const searchable = [entry.projectName, p.idea, p.prompt, p.purpose, p.language].join(" ").toLocaleLowerCase();
      return (!query || searchable.includes(query)) && (!category || p.purpose === category);
    }).sort((a,b) => Date.parse(b.prompt.createdAt || 0) - Date.parse(a.prompt.createdAt || 0));
    $("#promptLibraryCount").textContent = String(filtered.length) + " / " + String(entries.length);
    list.replaceChildren();
    if (!filtered.length) {
      const empty = document.createElement("p");
      empty.className = "helper-text";
      empty.textContent = entries.length ? "По вашему запросу ничего не найдено." : "Пока нет сохранённых промптов. Создайте промпт и сохраните его в выбранный фильм.";
      list.appendChild(empty);
      return;
    }
    filtered.forEach(entry => {
      const card = document.createElement("article");
      card.className = "prompt-library-card";
      const heading = document.createElement("div"); heading.className = "result-head";
      const title = document.createElement("b"); title.textContent = (promptModeLabels[entry.prompt.purpose] || "Промпт") + " · " + entry.projectName;
      const badge = document.createElement("span"); badge.className = "draft-badge"; badge.textContent = entry.prompt.language || "—";
      heading.append(title,badge);
      const idea = document.createElement("p"); idea.className = "helper-text"; idea.textContent = String(entry.prompt.idea || "Без исходного описания").slice(0,240);
      const preview = document.createElement("p"); preview.className = "prompt-library-preview"; preview.textContent = String(entry.prompt.prompt).slice(0,420) + (entry.prompt.prompt.length > 420 ? "…" : "");
      const versions = Array.isArray(entry.prompt.versions) ? entry.prompt.versions.slice(-20).reverse() : [];
      const history = document.createElement("details"); history.className = "prompt-version-history";
      const historySummary = document.createElement("summary"); historySummary.textContent = "История версий · " + versions.length;
      history.appendChild(historySummary);
      if (versions.length) {
        versions.forEach((version, versionIndex) => {
          const row = document.createElement("div"); row.className = "prompt-version-row";
          const info = document.createElement("div");
          const date = document.createElement("b"); date.textContent = "Версия " + (versions.length - versionIndex) + " · " + promptVersionLabel(version);
          const excerpt = document.createElement("p"); excerpt.className = "helper-text"; excerpt.textContent = String(version.prompt || "").slice(0,180) + (String(version.prompt || "").length > 180 ? "…" : "");
          info.append(date,excerpt);
          const compare = document.createElement("button"); compare.type = "button"; compare.className = "secondary-button"; compare.textContent = "Сравнить с текущей";
          compare.addEventListener("click", () => {
            const oldLines = String(version.prompt || "").split("\n");
            const newLines = String(entry.prompt.prompt || "").split("\n");
            const rows = oldLines.length * newLines.length <= 40000 ? (() => {
              const dp = Array.from({length:oldLines.length + 1}, () => new Uint16Array(newLines.length + 1));
              for (let a=oldLines.length-1;a>=0;a--) for (let b=newLines.length-1;b>=0;b--)
                dp[a][b] = oldLines[a] === newLines[b] ? dp[a+1][b+1] + 1 : Math.max(dp[a+1][b],dp[a][b+1]);
              const left=[],right=[]; let a=0,b=0;
              while(a<oldLines.length || b<newLines.length){
                if(a<oldLines.length && b<newLines.length && oldLines[a]===newLines[b]){left.push({text:oldLines[a],kind:""});right.push({text:newLines[b],kind:""});a++;b++;}
                else if(a<oldLines.length && (b>=newLines.length || dp[a+1][b]>=dp[a][b+1])){left.push({text:oldLines[a++],kind:"diff-removed"});}
                else {right.push({text:newLines[b++],kind:"diff-added"});}
              }
              return {left,right};
            })() : {left:oldLines.map(text=>({text,kind:"diff-removed"})),right:newLines.map(text=>({text,kind:"diff-added"}))};
            const panel=document.createElement("section"); panel.className="prompt-version-compare";
            const grid=document.createElement("div"); grid.className="prompt-version-compare-grid";
            const makePane=(label,items)=>{const pane=document.createElement("div");pane.className="prompt-version-compare-pane";const h=document.createElement("h4");h.textContent=label;const pre=document.createElement("pre");items.forEach(item=>{const line=document.createElement("span");line.className=item.kind;line.textContent=item.text || " ";pre.appendChild(line);});pane.append(h,pre);return pane;};
            grid.append(makePane("Старая версия · "+promptVersionLabel(version),rows.left),makePane("Текущая версия",rows.right));
            const note=document.createElement("p");note.className="prompt-version-compare-note";note.textContent="Красным отмечены удалённые строки, зелёным — добавленные. Неизменившиеся строки показаны без выделения.";
            const close=document.createElement("button");close.type="button";close.className="secondary-button";close.textContent="Закрыть сравнение";close.addEventListener("click",()=>panel.remove());
            panel.append(grid,note,close);
            const existing=card.querySelector(".prompt-version-compare");if(existing)existing.remove();
            history.insertAdjacentElement("afterend",panel);
          });
          const restore = document.createElement("button"); restore.type = "button"; restore.className = "secondary-button"; restore.textContent = "Восстановить";
          restore.addEventListener("click", () => {
            if (!window.confirm("Восстановить эту версию? Текущий текст сохранится в истории.")) return;
            const all = movieRead(); const projectIndex = all.findIndex(p => p.id === entry.projectId);
            if (projectIndex < 0) return;
            const project = { ...all[projectIndex] }; const saved = Array.isArray(project.prompts) ? [...project.prompts] : [];
            const current = saved[entry.index];
            if (!current) return;
            const currentSnapshot = snapshotPromptVersion(current);
            const historyItems = Array.isArray(current.versions) ? [...current.versions] : [];
            const selected = snapshotPromptVersion(version);
            const duplicate = currentSnapshot.prompt === selected.prompt && currentSnapshot.idea === selected.idea &&
              currentSnapshot.purpose === selected.purpose && currentSnapshot.language === selected.language;
            saved[entry.index] = {
              ...current, ...selected,
              versions: (duplicate ? historyItems : [...historyItems, currentSnapshot]).slice(-20),
              createdAt: current.createdAt || new Date().toISOString(),
              updatedAt: new Date().toISOString()
            };
            project.prompts = saved; project.updatedAt = new Date().toISOString(); all[projectIndex] = project;
            if (!movieWrite(all)) { $("#promptLibraryFeedback").textContent = "Не удалось восстановить версию."; return; }
            renderPromptLibrary(); renderMovieProjects();
            $("#promptLibraryFeedback").textContent = "Предыдущая версия восстановлена. Текущий вариант сохранён в истории.";
          });
          const rowActions=document.createElement("div");rowActions.className="prompt-library-actions";rowActions.append(compare,restore);
          row.append(info,rowActions); history.appendChild(row);
        });
      } else {
        const emptyHistory = document.createElement("p"); emptyHistory.className = "helper-text"; emptyHistory.textContent = "История появится после первого изменения промпта.";
        history.appendChild(emptyHistory);
      }
      const actions = document.createElement("div"); actions.className = "prompt-library-actions";
      const makeButton = (label, handler, danger = false) => {
        const button = document.createElement("button"); button.type = "button"; button.className = danger ? "secondary-button prompt-library-danger" : "secondary-button"; button.textContent = label; button.addEventListener("click", handler); return button;
      };
      actions.append(
        makeButton("Использовать", () => {
          resetPromptEditing();
          $("#promptIdea").value = entry.prompt.idea || "";
          $("#promptType").value = promptModeLabels[entry.prompt.purpose] ? entry.prompt.purpose : "video";
          $("#promptLanguage").value = entry.prompt.language || "Русский";
          $("#promptOutput").textContent = entry.prompt.prompt;
          lastGeneratedPrompt = { ...entry.prompt };
          $("#promptSaveFeedback").textContent = "Промпт загружен. Можно скопировать его или сохранить как новую версию в выбранный фильм.";
          $("#promptLibraryFeedback").textContent = "Промпт загружен в редактор.";
          $("#view-prompts").scrollIntoView({behavior:"smooth",block:"start"});
        }),
        makeButton("Редактировать", () => {
          editingPromptRef = { projectId: entry.projectId, index: entry.index };
          lastGeneratedPrompt = { ...entry.prompt };
          $("#promptIdea").value = entry.prompt.idea || "";
          $("#promptType").value = promptModeLabels[entry.prompt.purpose] ? entry.prompt.purpose : "video";
          $("#promptLanguage").value = entry.prompt.language || "Русский";
          $("#promptOutput").textContent = entry.prompt.prompt;
          $("#promptOutput").contentEditable = "true";
          $("#savePromptToMovie").textContent = "✓ Сохранить изменения";
          $("#cancelPromptEdit").hidden = false;
          $("#promptSaveFeedback").textContent = "Режим редактирования: измените текст промпта выше и сохраните изменения.";
          $("#promptLibraryFeedback").textContent = "Открыт редактор выбранного промпта.";
          $("#view-prompts").scrollIntoView({behavior:"smooth",block:"start"});
          $("#promptOutput").focus();
        }),
        makeButton("Удалить", () => {
          if (!window.confirm("Удалить этот промпт из фильма «" + entry.projectName + "»?")) return;
          const all = movieRead(); const projectIndex = all.findIndex(p => p.id === entry.projectId);
          if (projectIndex < 0) return;
          const project = { ...all[projectIndex] }; const saved = Array.isArray(project.prompts) ? [...project.prompts] : [];
          saved.splice(entry.index,1); project.prompts = saved; project.updatedAt = new Date().toISOString(); all[projectIndex] = project;
          if (!movieWrite(all)) { $("#promptLibraryFeedback").textContent = "Не удалось удалить промпт."; return; }
          renderPromptLibrary(); renderMovieProjects();
          $("#promptLibraryFeedback").textContent = "Промпт удалён из проекта.";
        }, true)
      );
      card.append(heading,idea,preview,history,actions); list.appendChild(card);
    });
  };
  $("#promptLibrarySearch").addEventListener("input", renderPromptLibrary);
  $("#promptLibraryCategory").addEventListener("change", renderPromptLibrary);
  $("#cancelPromptEdit").addEventListener("click", () => { resetPromptEditing(); $("#promptLibraryFeedback").textContent = "Редактирование отменено."; });
  $("#savePromptToMovie").addEventListener("click", () => {
    const feedback = $("#promptSaveFeedback");
    if (!lastGeneratedPrompt?.prompt) { feedback.textContent = "Сначала сформируйте промпт."; return; }
    if (!authSession?.user) { feedback.textContent = "Войдите в аккаунт, чтобы сохранить промпт в проект."; return; }
    const projects = movieRead();
    const targetProjectId = editingPromptRef?.projectId || activeMovieId;
    if (!targetProjectId) { feedback.textContent = "Сначала откройте нужный фильм в Миникиностудии."; return; }
    const index = projects.findIndex(project => project.id === targetProjectId);
    if (index < 0) { feedback.textContent = "Фильм не найден. Откройте проект заново."; return; }
    const project = { ...projects[index] };
    const saved = Array.isArray(project.prompts) ? [...project.prompts] : [];
    const item = {
      ...lastGeneratedPrompt,
      prompt: String($("#promptOutput").textContent || lastGeneratedPrompt.prompt).slice(0,12000),
      idea: String($("#promptIdea").value || lastGeneratedPrompt.idea || "").slice(0,2000),
      purpose: $("#promptType").value,
      language: $("#promptLanguage").value,
      updatedAt: new Date().toISOString()
    };
    if (editingPromptRef) {
      if (editingPromptRef.index < 0 || editingPromptRef.index >= saved.length) { feedback.textContent = "Промпт больше не найден в проекте."; return; }
      const previous = saved[editingPromptRef.index];
      const previousSnapshot = snapshotPromptVersion(previous);
      const hasMeaningfulChange = previousSnapshot.prompt !== item.prompt || previousSnapshot.idea !== item.idea ||
        previousSnapshot.purpose !== item.purpose || previousSnapshot.language !== item.language;
      const previousVersions = Array.isArray(previous.versions) ? [...previous.versions] : [];
      saved[editingPromptRef.index] = {
        ...previous, ...item,
        versions: (hasMeaningfulChange ? [...previousVersions, previousSnapshot] : previousVersions).slice(-20),
        createdAt: previous.createdAt || item.createdAt
      };
    } else {
      saved.push({ ...item, createdAt: item.createdAt || new Date().toISOString() });
    }
    project.prompts = saved.slice(-100);
    project.updatedAt = new Date().toISOString();
    projects[index] = project;
    if (!movieWrite(projects)) { feedback.textContent = "Не удалось сохранить промпт. Проверьте свободное место."; return; }
    const wasEditing = Boolean(editingPromptRef);
    resetPromptEditing();
    renderPromptLibrary(); renderMovieProjects();
    feedback.textContent = wasEditing ? "✓ Изменения сохранены в фильме «" + String(project.name || "Без названия").slice(0,80) + "»." : "✓ Промпт сохранён в фильме «" + String(project.name || "Без названия").slice(0,80) + "».";
  });
  setTimeout(() => renderPromptLibrary(), 0);

  const promptOutput = $("#promptOutput");
  const getPromptSelection = () => {
    const selection = window.getSelection();
    if (!selection || !selection.rangeCount || !promptOutput.contains(selection.anchorNode)) return null;
    return { selection, range: selection.getRangeAt(0) };
  };
  $("#selectAllPrompt").addEventListener("click", () => {
    const range=document.createRange(); range.selectNodeContents(promptOutput);
    const selection=window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
    promptOutput.focus();
  });
  $("#copySelectedPrompt").addEventListener("click", async () => {
    const selected=getPromptSelection();
    const value=selected ? selected.selection.toString() : "";
    if(!value){$("#promptSaveFeedback").textContent="Сначала выделите нужный фрагмент текста.";return;}
    try{await navigator.clipboard.writeText(value);$("#promptSaveFeedback").textContent="Выделенный фрагмент скопирован ✓";}
    catch{$("#promptSaveFeedback").textContent="Не удалось скопировать. Используйте стандартное копирование устройства.";}
  });
  const wrapPromptSelection = (before,after=before) => {
    const selected=getPromptSelection();
    if(!selected || selected.range.collapsed){$("#promptSaveFeedback").textContent="Выделите фрагмент промпта, который нужно оформить.";return;}
    const value=selected.selection.toString();
    const replacement=document.createTextNode(before+value+after);
    selected.range.deleteContents(); selected.range.insertNode(replacement);
    const next=document.createRange();next.selectNodeContents(replacement);
    selected.selection.removeAllRanges();selected.selection.addRange(next);
    promptOutput.focus();
    $("#promptSaveFeedback").textContent="Фрагмент оформлен. Сохраните изменения, чтобы не потерять результат.";
  };
  $("#wrapBoldPrompt").addEventListener("click",()=>wrapPromptSelection("**"));
  $("#wrapQuotePrompt").addEventListener("click",()=>wrapPromptSelection("> ",""));
  $("#wrapCodePrompt").addEventListener("click",()=>wrapPromptSelection("`","`"));
  const promptBlockLabels = {character:"Персонаж",scene:"Сцена и окружение",camera:"Камера и композиция",light:"Свет и цвет",style:"Визуальный стиль",sound:"Звук и музыка"};
  let promptBuilderBlocks = [];
  const renderPromptBuilderBlocks = () => {
    const list=$("#promptBlockList");if(!list)return;list.replaceChildren();
    if(!promptBuilderBlocks.length){const empty=document.createElement("p");empty.className="helper-text";empty.textContent="Добавьте один или несколько блоков. Их можно будет удалить до сборки промпта.";list.append(empty);return;}
    promptBuilderBlocks.forEach((block,index)=>{
      const row=document.createElement("article");row.className="prompt-builder-block";
      const heading=document.createElement("b");heading.textContent=(index+1)+". "+promptBlockLabels[block.type];
      const content=document.createElement("p");content.textContent=block.text;
      const remove=document.createElement("button");remove.type="button";remove.className="secondary-button";remove.textContent="Удалить";remove.addEventListener("click",()=>{promptBuilderBlocks.splice(index,1);renderPromptBuilderBlocks();});
      row.append(heading,content,remove);list.append(row);
    });
  };
  $("#insertPromptPreset").addEventListener("click",()=>{
    const preset=$("#promptPresetSelect").value;
    if(!preset){$("#promptSaveFeedback").textContent="Выберите готовую настройку.";return;}
    const field=$("#promptBlockText");field.value=field.value.trim()?field.value.trim()+" "+preset:preset;
    field.focus();$("#promptSaveFeedback").textContent="Настройка добавлена в поле блока. Выберите тип и нажмите «Добавить блок».";
  });
  $("#addPromptBlock").addEventListener("click",()=>{
    const type=$("#promptBlockType").value;const value=$("#promptBlockText").value.trim();
    if(!promptBlockLabels[type]||!value){$("#promptSaveFeedback").textContent="Выберите тип блока и заполните его содержание.";return;}
    if(promptBuilderBlocks.length>=20){$("#promptSaveFeedback").textContent="В одном конструкторе можно собрать не более 20 блоков.";return;}
    promptBuilderBlocks.push({type,text:value.slice(0,1800)});
    $("#promptBlockText").value="";renderPromptBuilderBlocks();$("#promptSaveFeedback").textContent="Блок добавлен в конструктор.";
  });
  $("#composePromptBlocks").addEventListener("click",()=>{
    if(!promptBuilderBlocks.length){$("#promptSaveFeedback").textContent="Сначала добавьте хотя бы один блок.";return;}
    const assembled=promptBuilderBlocks.map((block,index)=>"["+String(index+1).padStart(2,"0")+" · "+promptBlockLabels[block.type]+"]\n"+block.text).join("\n\n");
    const hasContent=promptOutput.textContent.trim()&&!promptOutput.textContent.startsWith("Здесь появится");
    if(hasContent&&!window.confirm("Заменить текущий текст промпта собранными блоками?"))return;
    promptOutput.textContent=assembled;promptOutput.contentEditable="true";promptOutput.focus();
    $("#promptSaveFeedback").textContent="Готово: собрано блоков — "+promptBuilderBlocks.length+". Теперь промпт можно редактировать, копировать или сохранить в фильм.";
  });
  $("#clearPromptBlocks").addEventListener("click",()=>{promptBuilderBlocks=[];renderPromptBuilderBlocks();$("#promptSaveFeedback").textContent="Блоки конструктора очищены.";});
  renderPromptBuilderBlocks();
  const visualLibraryKey = () => "pwa-studio-visual-library-v1:"+(authSession?.user?.id||"guest");
  const readVisualLibrary = () => {
    try {
      const items=JSON.parse(localStorage.getItem(visualLibraryKey())||"[]");
      return Array.isArray(items)?items.filter(item=>item&&["character","scene"].includes(item.type)&&typeof item.name==="string"&&typeof item.text==="string").slice(0,100):[];
    } catch { return []; }
  };
  const visualRefDbName="pwa-studio-visual-references-v1";
  const openVisualRefDb=()=>new Promise((resolve,reject)=>{
    if(!("indexedDB" in window)){reject(new Error("IndexedDB недоступен"));return;}
    const request=indexedDB.open(visualRefDbName,1);
    request.onupgradeneeded=()=>{if(!request.result.objectStoreNames.contains("images"))request.result.createObjectStore("images",{keyPath:"id"});};
    request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error||new Error("Не удалось открыть хранилище"));
  });
  const saveVisualRefImage=async(id,blob,ownerId)=>{
    if(typeof id!=="string"||!id||typeof ownerId!=="string"||!ownerId||!(blob instanceof Blob))throw new Error("Некорректные данные изображения или владельца.");
    const db=await openVisualRefDb();
    try{
      await new Promise((resolve,reject)=>{
        const tx=db.transaction("images","readwrite"),store=tx.objectStore("images"),request=store.get(id);
        let conflict=false;
        request.onsuccess=()=>{
          if(request.result&&request.result.ownerId!==ownerId){conflict=true;tx.abort();return;}
          store.put({id,ownerId,blob,createdAt:new Date().toISOString()});
        };
        request.onerror=()=>reject(request.error);
        tx.oncomplete=resolve;
        tx.onerror=()=>reject(conflict?new Error("Идентификатор изображения уже принадлежит другому аккаунту."):tx.error);
        tx.onabort=()=>reject(conflict?new Error("Идентификатор изображения уже принадлежит другому аккаунту."):tx.error||new Error("Сохранение изображения отменено."));
      });
    }finally{db.close();}
  };
  const getVisualRefImage=async(id,ownerId)=>{
    const db=await openVisualRefDb();
    try{
      const record=await new Promise((resolve,reject)=>{const request=db.transaction("images","readonly").objectStore("images").get(id);request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);});
      return record&&record.ownerId===ownerId?record.blob:null;
    }finally{db.close();}
  };
  const deleteVisualRefImage=async(id,ownerId)=>{
    const db=await openVisualRefDb();
    try{
      await new Promise((resolve,reject)=>{
        const tx=db.transaction("images","readwrite"),store=tx.objectStore("images"),request=store.get(id);
        request.onsuccess=()=>{if(request.result&&request.result.ownerId===ownerId)store.delete(id);};
        tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error||new Error("Удаление изображения отменено."));
      });
    }finally{db.close();}
  };
  const cloudVisualBucket="character-references";
  let visualLibrarySyncSequence=0;
  const syncCloudVisualLibrary=async()=>{
    const userId=authSession?.user?.id;if(!supabaseClient||!userId)return;
    const syncSequence=++visualLibrarySyncSequence;
    const isCurrentSync=()=>authSession?.user?.id===userId&&syncSequence===visualLibrarySyncSequence;
    try{
      const {data,error}=await supabaseClient.from("character_visual_assets").select("asset_id,asset,deleted_at").eq("user_id",userId);
      if(error)throw error;
      const cloudById=new Map();
      const tombstones=new Set();
      let invalidRows=0,missingImages=0,unmigratedLocalAssets=0;
      for(const row of (data||[])){
        const id=row?.asset_id,asset=row?.asset;
        const refs=asset?.referenceImages;
        const validRefs=refs===undefined||(Array.isArray(refs)&&
          refs.every(ref=>ref&&typeof ref==="object"&&!Array.isArray(ref)&&
            typeof ref.id==="string"&&ref.id.length>0&&
            (ref.storagePath===undefined||(typeof ref.storagePath==="string"&&ref.storagePath.length>0))&&
            (ref.name===undefined||typeof ref.name==="string")&&
            (ref.type===undefined||typeof ref.type==="string"))&&
          new Set(refs.map(ref=>ref.id)).size===refs.length);
        if(typeof id!=="string"||!id.length||!asset||typeof asset!=="object"||Array.isArray(asset)||asset.id!==id||!validRefs){invalidRows++;continue;}
        if(row.deleted_at){tombstones.add(id);continue;}
        cloudById.set(id,{...asset,referenceImages:refs||[]});
      }
      // Import legacy device-only entries once; cloud tombstones always win over stale local copies.
      if(!isCurrentSync())return;
      for(const localItem of readVisualLibrary()){
        if(!isCurrentSync())return;
        if(tombstones.has(localItem.id)||cloudById.has(localItem.id))continue;
        if(typeof localItem.id!=="string"||!localItem.id.length||
          (localItem.referenceImages!==undefined&&!Array.isArray(localItem.referenceImages))){
          unmigratedLocalAssets++;continue;
        }
        const refs=localItem.referenceImages||[];
        const blobs=[];
        let canMigrate=true;
        for(const ref of refs){
          if(!ref||typeof ref!=="object"||Array.isArray(ref)||typeof ref.id!=="string"||!ref.id.length){
            canMigrate=false;break;
          }
          if(ref.storagePath){
            if(typeof ref.storagePath!=="string"||!ref.storagePath.startsWith(userId+"/"))throw new Error("Обнаружен путь к чужому облачному объекту.");
            blobs.push(null);continue;
          }
          const blob=await getVisualRefImage(ref.id,userId);
          if(!isCurrentSync())return;
          if(!blob){
            missingImages++;canMigrate=false;break;
          }
          blobs.push(blob);
        }
        if(!isCurrentSync())return;
        // Never publish metadata for a local-only asset when one of its images
        // is missing: that would create a cloud reference with no backing object.
        if(!canMigrate){unmigratedLocalAssets++;continue;}
        const migrated=await saveVisualAssetToCloud(localItem,blobs);
        if(!isCurrentSync())return;
        cloudById.set(migrated.id,migrated);
      }
      if(cloudById.size>100){
        $("#promptSaveFeedback").textContent="В облаке обнаружено больше 100 активных материалов. Локальная библиотека не перезаписана, чтобы не скрыть записи. Обратитесь к администратору для проверки данных.";
        return;
      }
      const activeItems=[...cloudById.values()];
      for(const item of activeItems){
        if(!isCurrentSync())return;
        for(const ref of (Array.isArray(item.referenceImages)?item.referenceImages:[])){
          if(!ref.storagePath){
            // Legacy metadata may still have a valid device-local image. Keep it;
            // report it as unavailable only when this device has no cached blob.
            const localBlob=await getVisualRefImage(ref.id,userId);
            if(!localBlob)missingImages++;
            continue;
          }
          if(!ref.storagePath.startsWith(userId+"/")){missingImages++;continue;}
          const {data:blob,error:downloadError}=await supabaseClient.storage.from(cloudVisualBucket).download(ref.storagePath);
          if(downloadError||!blob){missingImages++;continue;}
          if(!isCurrentSync())return;
          try{
            await saveVisualRefImage(ref.id,blob,userId);
          }catch(cacheError){
            missingImages++;
            console.warn("Visual reference could not be cached locally:",cacheError);
          }
        }
      }
      if(!isCurrentSync())return;
      // Remove owner-scoped local image blobs for assets whose cloud tombstones won.
      for(const localItem of readVisualLibrary()){
        if(!tombstones.has(localItem.id))continue;
        for(const ref of (Array.isArray(localItem.referenceImages)?localItem.referenceImages:[])){
          if(!isCurrentSync())return;
          await deleteVisualRefImage(ref.id,userId);
        }
      }
      if(!isCurrentSync())return;
      // Never replace the device library with an incomplete cloud snapshot.
      // Malformed rows may represent valid local work that must remain recoverable.
      if(invalidRows||unmigratedLocalAssets){
        $("#promptSaveFeedback").textContent="Синхронизация частичная: повреждённых облачных записей — "+invalidRows+", локальных материалов, которые не удалось безопасно перенести, — "+unmigratedLocalAssets+". Локальная библиотека сохранена без перезаписи; недоступных изображений — "+missingImages+".";
        return;
      }
      localStorage.setItem(visualLibraryKey(),JSON.stringify(activeItems));
      renderVisualLibrary();
      $("#promptSaveFeedback").textContent=invalidRows||missingImages
        ? "Синхронизация завершена частично: пропущено записей — "+invalidRows+", недоступных изображений — "+missingImages+". Остальные материалы загружены."
        : "Облачная библиотека синхронизирована. Удалённые материалы не восстанавливаются со старых устройств.";
    }catch(error){
      if(authSession?.user?.id!==userId||syncSequence!==visualLibrarySyncSequence)return;
      console.warn("Visual library cloud sync unavailable:",error);
      $("#promptSaveFeedback").textContent="Облачная синхронизация пока недоступна. Локальная библиотека сохранена без изменений.";
    }
  };
  const saveVisualAssetToCloud=async(item,files)=>{
    const userId=authSession?.user?.id;if(!supabaseClient||!userId)return item;
    const assertOwner=()=>{if(authSession?.user?.id!==userId)throw new Error("Аккаунт изменился во время синхронизации.");};
    try{
      for(let i=0;i<files.length;i++){
        const entry=files[i],file=entry?.file||entry,ref=entry?.ref||item.referenceImages[i];
        if(ref.storagePath){
          if(!ref.storagePath.startsWith(userId+"/"))throw new Error("Путь к референсу не принадлежит текущему аккаунту.");
          continue;
        }
        if(!file)continue;
        const ext=file.type==="image/jpeg"?"jpg":file.type==="image/webp"?"webp":"png";
        // Immutable per-upload paths prevent a failed metadata update from destroying
        // the previously committed image at a stable path.
        const uploadToken=crypto.randomUUID?crypto.randomUUID():Date.now().toString(36)+"-"+Math.random().toString(36).slice(2);
        const storagePath=userId+"/"+item.id+"/"+ref.id+"-"+uploadToken+"."+ext;
        const {error}=await supabaseClient.storage.from(cloudVisualBucket).upload(storagePath,file,{contentType:file.type,upsert:false});
        if(error)throw error;
        ref.storagePath=storagePath;
        assertOwner();
      }
      assertOwner();
      const {error}=await supabaseClient.from("character_visual_assets").upsert(
        {user_id:userId,asset_id:item.id,asset:item,updated_at:new Date().toISOString(),deleted_at:null},
        {onConflict:"user_id,asset_id"}
      );
      if(error)throw error;
      // The cloud write is committed for the captured owner. Keep older objects
      // until a later safe garbage-collection pass; never risk deleting live refs.
      return item;
    }catch(error){
      // A failed/timeout response may still follow a committed metadata upsert.
      // Keep uploaded objects until a reconciliation pass proves they are unreferenced.
      throw error;
    }
  };
  const deleteVisualAssetFromCloud=async(item,expectedUserId=authSession?.user?.id)=>{
    const userId=expectedUserId;if(!supabaseClient||!userId)return;
    const assertOwner=()=>{if(authSession?.user?.id!==userId)throw new Error("Аккаунт изменился во время удаления.");};
    const paths=(item?.referenceImages||[]).map(ref=>ref.storagePath).filter(Boolean);
    if(paths.some(path=>!path.startsWith(userId+"/")))throw new Error("Отказано в удалении объекта вне текущего аккаунта.");
    const deletedAt=new Date().toISOString();
    const {error:markError}=await supabaseClient.from("character_visual_assets").upsert(
      {user_id:userId,asset_id:item.id,asset:item,deleted_at:deletedAt,updated_at:deletedAt},
      {onConflict:"user_id,asset_id"}
    );
    if(markError)throw markError;
    assertOwner();
    if(paths.length){const {error}=await supabaseClient.storage.from(cloudVisualBucket).remove(paths);if(error){const cleanupError=new Error("Запись удалена из облачной библиотеки, но не все файлы удалось очистить.");cleanupError.tombstoneCommitted=true;throw cleanupError;}}
    assertOwner();
  };
  let editingVisualAssetId=null;
  const visualReferenceRemovalLocks=new Set();
  const resetVisualAssetEditor=()=>{
    editingVisualAssetId=null;
    $("#saveVisualAsset").textContent="＋ Сохранить в библиотеку";
    $("#visualAssetName").value="";$("#visualAssetDescription").value="";$("#visualReferenceFiles").value="";
    ["#passportFace","#passportProfile","#passportFullBody","#passportWardrobe","#passportPalette","#passportExpressions"].forEach(id=>$(id).value="");
    syncPassportFields();
  };
  const renderVisualLibrary = () => {
    const list=$("#visualAssetList");if(!list)return;
    const items=readVisualLibrary();list.replaceChildren();
    if(!items.length){const empty=document.createElement("p");empty.className="helper-text";empty.textContent="Ваша библиотека пока пуста.";list.append(empty);return;}
    const renderOwnerId=authSession?.user?.id||null;
    items.forEach((item,index)=>{
      const card=document.createElement("article");card.className="prompt-visual-card";
      const title=document.createElement("b");title.textContent=(item.type==="character"?"Персонаж · ":"Сцена · ")+item.name;
      const description=document.createElement("p");description.textContent=item.text;
      if(item.type==="character"&&item.passport){
        const passport=document.createElement("p");passport.className="helper-text";
        passport.textContent=["Лицо: "+(item.passport.face||"—"),"Профиль: "+(item.passport.profile||"—"),"Полный рост: "+(item.passport.fullBody||"—"),"Одежда: "+(item.passport.wardrobe||"—"),"Палитра: "+(item.passport.palette||"—"),"Эмоции: "+(item.passport.expressions||"—")].join(" · ");
        card.append(title,description,passport);
      }else{card.append(title,description);}
      if(Array.isArray(item.referenceImages)&&item.referenceImages.length){
        const gallery=document.createElement("div");gallery.className="visual-reference-gallery";
        const label=document.createElement("p");label.className="helper-text";label.textContent="Прикреплённые референсы: "+item.referenceImages.length;gallery.append(label);
        item.referenceImages.slice(0,6).forEach(async(ref)=>{
          try{
            const blob=await getVisualRefImage(ref.id,renderOwnerId||"guest");
            if(!blob||(authSession?.user?.id||null)!==renderOwnerId||!card.isConnected)return;
            const tile=document.createElement("div");tile.className="visual-reference-tile";
            const image=document.createElement("img");image.alt="Референс материала "+item.name;image.loading="lazy";
            const objectUrl=URL.createObjectURL(blob);image.src=objectUrl;
            image.addEventListener("load",()=>URL.revokeObjectURL(objectUrl),{once:true});
            image.addEventListener("error",()=>URL.revokeObjectURL(objectUrl),{once:true});
            const removeRef=document.createElement("button");removeRef.type="button";removeRef.className="secondary-button";removeRef.textContent="Удалить изображение";
            removeRef.addEventListener("click",async()=>{
              const removalKey=item.id;
              if(visualReferenceRemovalLocks.has(removalKey))return;
              const ownerId=authSession?.user?.id||null,storageKey=visualLibraryKey();
              const current=readVisualLibrary().find(entry=>entry.id===item.id);
              const refNow=current?.referenceImages?.find(entry=>entry.id===ref.id);
              if(!current||!refNow)return;
              visualReferenceRemovalLocks.add(removalKey);
              // Prevent an older in-flight cloud sync from restoring stale metadata locally.
              visualLibrarySyncSequence++;
              removeRef.disabled=true;
              let metadataCommitted=false,localMetadataUpdated=false,localBlobRemoved=false,cloudObjectRemoved=false;
              try{
                const nextAsset={...current,referenceImages:current.referenceImages.filter(entry=>entry.id!==ref.id),updatedAt:new Date().toISOString()};
                const nextItems=readVisualLibrary().map(entry=>entry.id===current.id?nextAsset:entry);
                if(ownerId){
                  if(refNow.storagePath&&!refNow.storagePath.startsWith(ownerId+"/"))throw new Error("Путь к изображению не принадлежит текущему аккаунту.");
                  await saveVisualAssetToCloud(nextAsset,[]);
                  metadataCommitted=true;
                  if(authSession?.user?.id!==ownerId)throw new Error("Аккаунт изменился после обновления облачной записи.");
                }else{
                  metadataCommitted=true;
                }
                localStorage.setItem(storageKey,JSON.stringify(nextItems));
                localMetadataUpdated=true;
                if(authSession?.user?.id!==(ownerId||null))throw new Error("Аккаунт изменился перед очисткой локального изображения.");
                await deleteVisualRefImage(ref.id,ownerId||"guest");
                localBlobRemoved=true;
                if(ownerId&&refNow.storagePath){
                  if(authSession?.user?.id!==ownerId)throw new Error("Аккаунт изменился перед очисткой облачного файла.");
                  const {error}=await supabaseClient.storage.from(cloudVisualBucket).remove([refNow.storagePath]);
                  if(error)throw error;
                  cloudObjectRemoved=true;
                }else cloudObjectRemoved=true;
                $("#promptSaveFeedback").textContent="Изображение удалено из материала. Остальные референсы сохранены.";
                renderVisualLibrary();
              }catch(error){
                console.warn("Single reference delete/cleanup status:",{error,metadataCommitted,localMetadataUpdated,localBlobRemoved,cloudObjectRemoved});
                if(!metadataCommitted){
                  $("#promptSaveFeedback").textContent="Не удалось обновить запись материала. Изображение осталось в библиотеке; повторите попытку.";
                  removeRef.disabled=false;
                }else{
                  const pending=[];
                  if(!localMetadataUpdated)pending.push("локальная запись");
                  if(!localBlobRemoved)pending.push("локальный файл");
                  if(ownerId&&refNow.storagePath&&!cloudObjectRemoved)pending.push("облачный файл");
                  $("#promptSaveFeedback").textContent=pending.length
                    ?"Изображение уже исключено из материала. Требует завершения очистка: "+pending.join(", ")+". Обновите библиотеку или войдите снова для синхронизации."
                    :"Изображение удалено из материала.";
                  if(localMetadataUpdated)renderVisualLibrary();
                }
              }finally{
                visualReferenceRemovalLocks.delete(removalKey);
              }
            });
            tile.append(image,removeRef);gallery.append(tile);
          }catch{}
        });
        card.append(gallery);
      }
      const actions=document.createElement("div");actions.className="prompt-library-actions";
      const edit=document.createElement("button");edit.type="button";edit.className="secondary-button";edit.textContent="Изменить";
      edit.addEventListener("click",()=>{
        const current=readVisualLibrary().find(entry=>entry.id===item.id);if(!current)return;
        editingVisualAssetId=current.id;
        $("#visualAssetType").value=current.type;$("#visualAssetName").value=current.name;$("#visualAssetDescription").value=current.text;
        const p=current.passport||{};
        $("#passportFace").value=p.face||"";$("#passportProfile").value=p.profile||"";$("#passportFullBody").value=p.fullBody||"";
        $("#passportWardrobe").value=p.wardrobe||"";$("#passportPalette").value=p.palette||"";$("#passportExpressions").value=p.expressions||"";
        $("#visualReferenceFiles").value="";$("#saveVisualAsset").textContent="Сохранить изменения";
        syncPassportFields();$("#visualAssetName").scrollIntoView({behavior:"smooth",block:"center"});
        $("#promptSaveFeedback").textContent="Режим редактирования: существующие референсы сохранятся. Новые изображения можно добавить отдельно.";
      });
      actions.append(edit);
      const insert=document.createElement("button");insert.type="button";insert.className="secondary-button";insert.textContent="Вставить в конструктор";insert.addEventListener("click",()=>{
        $("#promptBlockType").value=item.type;$("#promptBlockText").value=item.text;$("#promptBlockText").focus();
        $("#promptSaveFeedback").textContent="Материал «"+item.name+"» загружен в конструктор. При необходимости дополните его и добавьте блок.";
      });
      const activeProject=activeMovieId?movieRead().find(project=>project.id===activeMovieId):null;
      const pinned=Array.isArray(activeProject?.visualContinuity)?activeProject.visualContinuity.some(ref=>ref.id===item.id):false;
      const pin=document.createElement("button");pin.type="button";pin.className="secondary-button";pin.textContent=pinned?"Открепить от фильма":"Закрепить в фильме";
      pin.addEventListener("click",()=>{
        const projects=movieRead();const project=projects.find(entry=>entry.id===activeMovieId);
        if(!project){$("#promptSaveFeedback").textContent="Сначала откройте или создайте фильм в Миникиностудии.";return;}
        const refs=Array.isArray(project.visualContinuity)?project.visualContinuity.slice():[];
        const existing=refs.findIndex(ref=>ref.id===item.id);
        if(existing>=0){refs.splice(existing,1);}
        else{
          if(refs.length>=12){$("#promptSaveFeedback").textContent="В одном фильме можно закрепить до 12 персонажей и локаций.";return;}
          refs.push({id:item.id,type:item.type,name:item.name.slice(0,80),description:item.text.slice(0,3000),...(item.passport?{passport:item.passport}:{})});
        }
        project.visualContinuity=refs;project.updatedAt=new Date().toISOString();
        if(movieWrite(projects)){renderVisualLibrary();$("#promptSaveFeedback").textContent=existing>=0?"Материал откреплён от текущего фильма.":"Материал закреплён: AI будет учитывать его при создании новых промптов.";}
      });
      if(item.type==="character"){
        const sheet=document.createElement("button");sheet.type="button";sheet.className="secondary-button";sheet.textContent="Собрать Character Sheet";
        sheet.addEventListener("click",()=>{
          const p=item.passport||{};
          const sections=[
            "CHARACTER SHEET — CONSISTENT MODEL REFERENCE",
            "Character: "+item.name,
            "Core identity and personality: "+item.text,
            "FRONT FACE / PORTRAIT: "+(p.face||"Define from the core description; preserve identity."),
            "SIDE PROFILE: "+(p.profile||"Create a clear side profile matching the same face and skull shape."),
            "FULL BODY: "+(p.fullBody||"Show complete body proportions, posture and silhouette."),
            "WARDROBE AND ACCESSORIES: "+(p.wardrobe||"Design a coherent outfit consistent with the character description."),
            "COLOR PALETTE: "+(p.palette||"Derive a restrained, consistent palette from the description."),
            "EXPRESSIONS: "+(p.expressions||"Include neutral, joyful, concerned and determined expressions."),
            "LAYOUT: one clean professional character-reference sheet on a plain neutral background; front portrait, side profile, full-body front view, full-body back view, and a compact expression row. Keep every view of the exact same character.",
            "CONTINUITY RULES: identical facial identity, age appearance, body proportions, hairstyle, outfit construction, accessories and palette across all panels. No redesign, no extra characters, no cropped feet, no perspective distortion, no text labels or watermarks unless requested.",
            "STYLE AND QUALITY: polished production-ready concept-art reference, clear readable silhouettes, consistent anatomy, even studio lighting, high detail."
          ];
          const output=$("#promptOutput");if(output){output.textContent=sections.join("\n\n");output.setAttribute("contenteditable","true");output.focus();output.scrollIntoView({behavior:"smooth",block:"center"});}
          $("#promptSaveFeedback").textContent="Лист персонажа собран как готовый промпт. Проверьте детали и при необходимости сохраните его в библиотеку промптов.";
        });
        actions.append(sheet);
        const pack=document.createElement("button");pack.type="button";pack.className="secondary-button";pack.textContent="Подготовить 6 референсов";
        pack.addEventListener("click",()=>{
          const identity=[
            "CHARACTER IDENTITY LOCK — "+item.name,
            "Core description: "+item.text,
            "Face identity: "+(p.face||"derive from core description and keep identical in every image"),
            "Profile: "+(p.profile||"same skull shape, nose, jawline and facial proportions as the portrait"),
            "Body and silhouette: "+(p.fullBody||"consistent believable proportions, height and posture"),
            "Wardrobe: "+(p.wardrobe||"one coherent outfit, identical construction and accessories in every view"),
            "Palette: "+(p.palette||"consistent palette derived from the character description"),
            "Expression direction: "+(p.expressions||"natural readable expressions, preserve facial identity"),
            "Character essence: never change identity, apparent age, facial structure, hairstyle, body proportions, costume or accessories between references. No additional characters. Neutral uncluttered studio background. Production-quality concept art, clear anatomy, full details, no text, no watermark."
          ].join("\n");
          const views=[
            ["01 — PORTRAIT FRONT","Create a straight-on head-and-shoulders portrait, neutral relaxed expression, face fully visible, centered framing, soft even studio light. Match the identity lock exactly."],
            ["02 — SIDE PROFILE","Create a strict 90-degree side profile from head to upper chest. Clearly show forehead, nose, lips, chin, ear and head silhouette. This must be the exact same character as the portrait, not a redesign."],
            ["03 — FULL BODY FRONT","Create a full-length front view from head to shoes, neutral standing pose, arms slightly separated from torso, natural proportions, entire silhouette visible with space around the feet."],
            ["04 — FULL BODY BACK","Create a full-length rear view of the exact same character and outfit. Clearly show hairstyle from behind, garment construction, seams, layers, fastenings and accessories. Entire body and shoes visible."],
            ["05 — EXPRESSION STUDY","Create a clean expression study with six evenly sized head-and-shoulders variations: neutral, joyful, concerned, surprised, sad and determined. Preserve identical facial structure and hairstyle in every expression."],
            ["06 — COSTUME AND DETAILS","Create a design-detail reference showing the exact outfit in clear readable views, with close details of fabrics, textures, footwear, jewelry and signature accessories. Do not invent or alter costume elements."]
          ];
          const bundle=views.map(([title,direction])=>title+"\n"+identity+"\n\nSHOT INSTRUCTIONS: "+direction).join("\n\n"+"=".repeat(56)+"\n\n");
          const output=$("#promptOutput");if(output){output.textContent="REFERENCE PACK — "+item.name+"\nSix separate prompts. Generate each view independently and use the same identity reference image whenever the image model supports reference images.\n\n"+bundle;output.setAttribute("contenteditable","true");output.focus();output.scrollIntoView({behavior:"smooth",block:"center"});}
          $("#promptSaveFeedback").textContent="Подготовлены 6 самостоятельных промптов. Генерируйте виды отдельно и используйте один и тот же исходный референс для закрепления внешности. Изображения пока не создаются автоматически.";
        });
        actions.append(pack);
      }
      const remove=document.createElement("button");remove.type="button";remove.className="secondary-button";remove.textContent="Удалить";remove.addEventListener("click",async()=>{
        const ownerId=authSession?.user?.id||null,storageKey=visualLibraryKey();
        const current=readVisualLibrary(),removed=current.find(asset=>asset.id===item.id);if(!removed)return;
        if(visualReferenceRemovalLocks.has(removed.id)){
          $("#promptSaveFeedback").textContent="Сначала дождитесь завершения удаления изображения из этого материала.";
          return;
        }
        const stillOwner=()=>((authSession?.user?.id||null)===ownerId);
        remove.disabled=true;
        // A sync started before this deletion must not restore its stale snapshot.
        visualLibrarySyncSequence++;
        try{
          // Persist the cloud tombstone before removing the local copy, so a network error cannot resurrect it.
          if(ownerId)await deleteVisualAssetFromCloud(removed,ownerId);
          if(!stillOwner())throw new Error("Аккаунт изменился во время удаления.");
          const next=JSON.parse(localStorage.getItem(storageKey)||"[]").filter(asset=>asset.id!==removed.id);
          localStorage.setItem(storageKey,JSON.stringify(next));
          const localCleanup=await Promise.allSettled((removed.referenceImages||[]).map(ref=>deleteVisualRefImage(ref.id,ownerId||"guest")));
          const cleanupFailed=localCleanup.some(result=>result.status==="rejected");
          $("#promptSaveFeedback").textContent=cleanupFailed
            ?"Материал удалён из библиотеки, но часть локальных файлов не удалось очистить. Остальные данные сохранены; повторите очистку позже."
            :"Материал удалён из библиотеки.";
          renderVisualLibrary();
        }catch(error){
          console.warn("Cloud asset delete failed:",error);
          if(error?.tombstoneCommitted&&stillOwner()){
            try{
              const next=JSON.parse(localStorage.getItem(storageKey)||"[]").filter(asset=>asset.id!==removed.id);
              localStorage.setItem(storageKey,JSON.stringify(next));
              const localCleanup=await Promise.allSettled((removed.referenceImages||[]).map(ref=>deleteVisualRefImage(ref.id,ownerId||"guest")));
              const cleanupFailed=localCleanup.some(result=>result.status==="rejected");
              $("#promptSaveFeedback").textContent=cleanupFailed
                ?"Материал удалён из библиотеки и помечен удалённым в облаке. Часть локальных файлов не удалось очистить; они не восстановятся при синхронизации."
                :"Материал удалён из библиотеки и помечен удалённым в облаке. Не удалось очистить часть облачных файлов; они не восстановятся при синхронизации.";
              renderVisualLibrary();
              return;
            }catch(localError){console.warn("Local visual asset cleanup failed:",localError);}
          }
          $("#promptSaveFeedback").textContent=stillOwner()
            ?"Не удалось подтвердить удаление в облаке. Материал оставлен на устройстве; повторите попытку."
            :"Аккаунт изменился. Данные другого аккаунта не изменены; обновите библиотеку после входа.";
          remove.disabled=false;
        }
      });
      actions.append(insert,pin,remove);card.append(actions);list.append(card);
    });
  };
  $("#saveVisualAsset").addEventListener("click",async()=>{
    const ownerId=authSession?.user?.id||null,storageKey=visualLibraryKey();
    const assertOwner=()=>{if((authSession?.user?.id||null)!==ownerId)throw new Error("Аккаунт изменился во время сохранения.");};
    const type=$("#visualAssetType").value,name=$("#visualAssetName").value.trim(),value=$("#visualAssetDescription").value.trim();
    if(!["character","scene"].includes(type)||!name||!value){$("#promptSaveFeedback").textContent="Укажите тип, название и описание материала.";return;}
    const items=readVisualLibrary(),editingId=editingVisualAssetId;
    const existing=editingId?items.find(item=>item.id===editingId):null;
    if(editingId&&!existing){resetVisualAssetEditor();$("#promptSaveFeedback").textContent="Материал больше не найден. Обновите библиотеку.";return;}
    if(editingId&&visualReferenceRemovalLocks.has(editingId)){
      $("#promptSaveFeedback").textContent="Сначала дождитесь завершения удаления изображения из этого материала.";
      return;
    }
    if(!editingId&&items.length>=100){$("#promptSaveFeedback").textContent="Библиотека вмещает до 100 материалов. Удалите ненужные записи.";return;}
    const files=Array.from($("#visualReferenceFiles")?.files||[]);
    const oldRefs=existing&&Array.isArray(existing.referenceImages)?existing.referenceImages:[];
    if(files.length+oldRefs.length>6){$("#promptSaveFeedback").textContent="Всего у одного материала может быть не более 6 референсов. Удалите старые или выберите меньше новых изображений.";return;}
    if(files.some(file=>!["image/png","image/jpeg","image/webp"].includes(file.type)||file.size>8*1024*1024)){
      $("#promptSaveFeedback").textContent="Поддерживаются PNG, JPEG и WebP до 8 МБ каждый.";return;
    }
    const passport=type==="character"?{
      face:$("#passportFace").value.trim().slice(0,600),profile:$("#passportProfile").value.trim().slice(0,600),
      fullBody:$("#passportFullBody").value.trim().slice(0,600),wardrobe:$("#passportWardrobe").value.trim().slice(0,800),
      palette:$("#passportPalette").value.trim().slice(0,300),expressions:$("#passportExpressions").value.trim().slice(0,500)
    }:null;
    const assetId=existing?existing.id:(crypto.randomUUID?crypto.randomUUID():String(Date.now()));
    const newRefs=files.map(file=>({id:assetId+"-"+(crypto.randomUUID?crypto.randomUUID():Date.now().toString(36)+"-"+Math.random().toString(36).slice(2)),name:file.name.slice(0,120),type:file.type}));
    const updated={...(existing||{}),id:assetId,type,name:name.slice(0,80),text:value.slice(0,5000),...(passport?{passport}:{}),...(!passport?{passport:undefined}:{}),referenceImages:[...oldRefs,...newRefs],createdAt:existing?.createdAt||new Date().toISOString(),updatedAt:new Date().toISOString()};
    const next=existing?items.map(item=>item.id===assetId?updated:item):[updated,...items];
    const saveButton=$("#saveVisualAsset");saveButton.disabled=true;
    // Invalidate any older cloud snapshot before saving or editing this asset.
    visualLibrarySyncSequence++;
    let localImagesPrepared=false,cloudSaveAttempted=false;
    try{
      for(let i=0;i<files.length;i++){assertOwner();await saveVisualRefImage(newRefs[i].id,files[i],ownerId||"guest");}
      localImagesPrepared=true;
      assertOwner();
      if(ownerId){cloudSaveAttempted=true;await saveVisualAssetToCloud(updated,files.map((file,index)=>({file,ref:newRefs[index]})));}
      assertOwner();
      localStorage.setItem(storageKey,JSON.stringify(next));
    }catch(error){
      let preservedLocally=false;
      // A cloud timeout can be ambiguous: the server may have committed the metadata.
      // Keep prepared blobs and a local copy so a later sync can safely reconcile them.
      if(cloudSaveAttempted&&localImagesPrepared&&(authSession?.user?.id||null)===ownerId){
        try{localStorage.setItem(storageKey,JSON.stringify(next));preservedLocally=true;}
        catch(localError){console.warn("Local fallback metadata write failed:",localError);}
      }else if(!cloudSaveAttempted){
        await Promise.all(newRefs.map(ref=>deleteVisualRefImage(ref.id,ownerId||"guest").catch(()=>{})));
      }
      $("#promptSaveFeedback").textContent=preservedLocally
        ?"Облако временно недоступно. Материал и изображения сохранены на этом устройстве; синхронизация повторится при следующем входе или обновлении библиотеки."
        :ownerId
          ?"Не удалось подтвердить сохранение. Проверьте подключение и аккаунт; подготовленные файлы не удалены автоматически."
          :"Не удалось сохранить материал. Проверьте свободное место браузера и доступность IndexedDB.";
      console.warn("Visual asset save failed:",{error,localImagesPrepared,cloudSaveAttempted,preservedLocally});
      saveButton.disabled=false;return;
    }
    saveButton.disabled=false;resetVisualAssetEditor();renderVisualLibrary();
    $("#promptSaveFeedback").textContent=ownerId
      ?(existing?"Изменения материала «"+name+"» сохранены в облачной библиотеке.":"«"+name+"» сохранён в облачной библиотеке вашего аккаунта.")
      :(existing?"Изменения материала «"+name+"» сохранены локально.":"«"+name+"» сохранён локально. Войдите в аккаунт для облачной синхронизации.");
  });
  const syncPassportFields=()=>{$("#characterPassportFields").hidden=$("#visualAssetType").value!=="character";};
  $("#visualAssetType").addEventListener("change",syncPassportFields);
  syncPassportFields();
  renderVisualLibrary();
  if(authSession?.user?.id)syncCloudVisualLibrary();
    const promptTemplates = {
    cinematic: "Субъект: {{subject}}.\nЛокация: {{location}}.\nНастроение: {{mood}}.\nКинематографичная композиция, выразительная глубина кадра, естественное освещение, детализированные материалы, продуманная цветовая палитра. Камера: {{camera}}. Сохранить визуальную целостность и реалистичную физику.",
    character: "Персонаж: {{subject}}.\nВнешность и отличительные черты: {{appearance}}.\nОдежда и аксессуары: {{wardrobe}}.\nХарактер и манера движения: {{personality}}. Сохранять одинаковые черты лица, пропорции, причёску и одежду во всех кадрах. Не менять идентичность персонажа.",
    video: "Сцена: {{subject}}.\nДействие: {{action}}.\nОкружение: {{location}}.\nДвижение камеры: {{camera}}.\nДлительность: {{duration}}. Описать начало, развитие и завершение движения, темп, направление, непрерывность и переход к следующему кадру.",
    music: "Создать музыкальное сопровождение для: {{subject}}.\nЖанр: {{genre}}. Настроение: {{mood}}. Темп: {{tempo}}. Инструменты: {{instruments}}. Структура: вступление, развитие, кульминация и завершение. Без вокала, если не указано иное.",
    sound: "Звуковая сцена: {{subject}}.\nМесто: {{location}}.\nАтмосфера: {{mood}}.\nОсновные звуки: {{sounds}}. Указать дистанцию, акустику пространства, слои фонового окружения, динамику и точное время появления ключевых эффектов."
  };
  const fragmentStorageKey = () => "pwa-studio-prompt-fragments-v1:" + (authSession?.user?.id || "guest");
  const readPromptFragments = () => { try { const value=JSON.parse(localStorage.getItem(fragmentStorageKey())||"[]"); return Array.isArray(value)?value.filter(x=>x&&typeof x.text==="string"&&typeof x.name==="string").slice(0,80):[]; } catch { return []; } };
  const writePromptFragments = items => { try { localStorage.setItem(fragmentStorageKey(),JSON.stringify(items.slice(0,80))); return true; } catch { return false; } };
  const renderPromptFragments = () => {
    const list=$("#promptFragmentList"); if(!list)return;
    const items=readPromptFragments(); list.replaceChildren();
    if(!items.length){const empty=document.createElement("p");empty.className="helper-text";empty.textContent="Сохранённых фрагментов пока нет.";list.append(empty);return;}
    items.forEach((item,index)=>{
      const row=document.createElement("div");row.className="prompt-fragment-row";
      const info=document.createElement("div");info.className="prompt-fragment-info";
      const title=document.createElement("b");title.textContent=item.name;
      const preview=document.createElement("small");preview.textContent=item.text.slice(0,180);
      info.append(title,preview);
      const actions=document.createElement("div");actions.className="prompt-library-actions";
      const insert=document.createElement("button");insert.type="button";insert.className="secondary-button";insert.textContent="Вставить";insert.addEventListener("click",()=>{
        const selected=getPromptSelection();
        if(selected&&!selected.range.collapsed)selected.range.deleteContents();
        const range=selected?selected.range:document.createRange();if(!selected){range.selectNodeContents(promptOutput);range.collapse(false);}
        const node=document.createTextNode(item.text);range.insertNode(node);
        const next=document.createRange();next.selectNodeContents(node);next.collapse(false);const selection=window.getSelection();selection.removeAllRanges();selection.addRange(next);
        promptOutput.contentEditable="true";promptOutput.focus();$("#promptSaveFeedback").textContent="Фрагмент вставлен. Сохраните изменения, чтобы его оставить.";
      });
      const remove=document.createElement("button");remove.type="button";remove.className="secondary-button";remove.textContent="Удалить";remove.addEventListener("click",()=>{const next=readPromptFragments();next.splice(index,1);writePromptFragments(next);renderPromptFragments();});
      actions.append(insert,remove);row.append(info,actions);list.append(row);
    });
  };
  $("#applyPromptTemplate").addEventListener("click",()=>{
    const key=$("#promptTemplateSelect").value; if(!promptTemplates[key]){$("#promptSaveFeedback").textContent="Сначала выберите шаблон.";return;}
    promptOutput.textContent=promptTemplates[key];promptOutput.contentEditable="true";promptOutput.focus();
    $("#promptSaveFeedback").textContent="Шаблон добавлен. Заполните переменные или отредактируйте текст.";
  });
  $("#applyPromptVariables").addEventListener("click",()=>{
    const values={};$("#promptVariableValues").value.split(/\r?\n/).forEach(line=>{const at=line.indexOf("=");if(at>0){const key=line.slice(0,at).trim().replace(/^\\{\\{|\\}\\}$/g,"");const value=line.slice(at+1).trim();if(/^[a-zA-Z0-9_]{1,40}$/.test(key)&&value)values[key]=value;}});
    let result=promptOutput.textContent;let count=0;
    Object.entries(values).forEach(([key,value])=>{const pattern=new RegExp("\\{\\{\\s*"+key+"\\s*\\}\\}","g");result=result.replace(pattern,()=>{count++;return value;});});
    promptOutput.textContent=result;promptOutput.contentEditable="true";
    $("#promptSaveFeedback").textContent=count?"Подставлено значений: "+count+".":"Подходящие переменные не найдены. Проверьте формат имя=значение.";
  });
  $("#savePromptFragment").addEventListener("click",()=>{
    const selected=getPromptSelection();const value=selected?selected.selection.toString().trim():"";
    if(!value){$("#promptSaveFeedback").textContent="Выделите фрагмент внутри текста промпта.";return;}
    const name=$("#promptFragmentName").value.trim()||("Фрагмент "+(readPromptFragments().length+1));
    const items=readPromptFragments();items.unshift({id:Date.now().toString(36),name:name.slice(0,60),text:value,createdAt:new Date().toISOString()});
    if(!writePromptFragments(items)){$("#promptSaveFeedback").textContent="Не удалось сохранить фрагмент в памяти браузера.";return;}
    $("#promptFragmentName").value="";renderPromptFragments();$("#promptSaveFeedback").textContent="Фрагмент «"+name+"» сохранён.";
  });
  renderPromptFragments();
  window.addEventListener("pwa-studio-auth-changed",renderPromptFragments);
  $("#copyPrompt").addEventListener("click", async () => {
    if (editingPromptRef) $("#promptLibraryFeedback").textContent = "Вы можете сначала сохранить изменения или отменить редактирование.";

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
  let assistantHistoryBusy = false;
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
    const userId = authSession?.user?.id;
    if (!supabaseClient || !userId || !conversationId) return;
    const { data, error } = await supabaseClient.from("assistant_messages")
      .select("id,role,content,created_at").eq("conversation_id", conversationId)
      .eq("user_id", userId).order("created_at", { ascending: true });
    if (error) throw error;
    if (authSession?.user?.id !== userId) return;
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
    const userId = authSession.user.id;
    assistantHistoryBusy = true; setAssistantStatus("Загружаем ваши диалоги…");
    try {
      const { data, error } = await supabaseClient.from("assistant_conversations")
        .select("id,title,updated_at").eq("user_id", userId)
        .order("updated_at", { ascending: false });
      if (error) throw error;
      if (authSession?.user?.id !== userId) return;
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
        if (authSession?.user?.id !== userId) return;
      }
      setAssistantStatus((data || []).length ? "Диалоги сохраняются в вашем аккаунте." : "Пока нет сохранённых диалогов. Начните новый разговор.");
    } catch (error) {
      setAssistantStatus("История пока недоступна. Проверьте, применена ли миграция Supabase. " + error.message);
    } finally {
      assistantHistoryBusy = false;
      if (authSession?.user?.id && authSession.user.id !== userId) setTimeout(renderAssistantHistory, 0);
    }
  };
  const startAssistantConversation = async () => {
    const userId = authSession?.user?.id;
    if (!userId || !supabaseClient) throw new Error("Сначала войдите в аккаунт.");
    const { data, error } = await supabaseClient.from("assistant_conversations")
      .insert({ user_id: userId, title: "Новый диалог" }).select("id").single();
    if (error) throw error;
    if (authSession?.user?.id !== userId) return null;
    activeAssistantConversationId = data.id; clearAssistantMessages();
    await renderAssistantHistory();
    if (authSession?.user?.id !== userId) return null;
    setAssistantStatus("Создан новый диалог. Предыдущие разговоры сохранены.");
    return data.id;
  };
  $("#assistantNewChat")?.addEventListener("click", async () => {
    try { await startAssistantConversation(); $("#assistantInput").focus(); }
    catch (error) { setAssistantStatus("Не удалось создать диалог: " + error.message); }
  });
  $("#assistantForm").addEventListener("submit", async event => {
    event.preventDefault();
    const input = $("#assistantInput"); const value = input.value.trim(); if (!value) return;
    if (!authSession?.user) { setAuthMode("signup"); setAuthMessage("Войдите или зарегистрируйтесь, чтобы общаться с AI Companion."); return; }
    const requestUserId = authSession.user.id;
    const button = $("#assistantForm button"); button.disabled = true; input.disabled = true; input.value = "";
    try {
      if (!activeAssistantConversationId) await startAssistantConversation();
      if (authSession?.user?.id !== requestUserId) {
        setAssistantStatus("Сеанс аккаунта изменился. Сообщение не было сохранено.");
        return;
      }
      const conversationId = activeAssistantConversationId;
      if (!conversationId) throw new Error("Не удалось открыть диалог. Начните новый разговор.");
      const { data: previousMessages, error: historyReadError } = await supabaseClient.from("assistant_messages")
        .select("role,content").eq("conversation_id", conversationId).eq("user_id", requestUserId)
        .order("created_at", { ascending: false }).limit(8);
      if (historyReadError) throw historyReadError;
      if (authSession?.user?.id !== requestUserId) return;
      const chatHistory = (previousMessages || []).reverse().map(item => ({
        role: item.role, content: String(item.content || "").slice(0, 3000)
      }));
      const { error: userSaveError } = await supabaseClient.from("assistant_messages")
        .insert({ conversation_id: conversationId, user_id: requestUserId, role: "user", content: value });
      if (userSaveError) throw userSaveError;
      if (authSession?.user?.id !== requestUserId) return;
      renderAssistantMessage("user", value);
      const { data: titleRow, error: titleReadError } = await supabaseClient.from("assistant_conversations")
        .select("title").eq("id", conversationId).eq("user_id", requestUserId).single();
      if (titleReadError) throw titleReadError;
      if (authSession?.user?.id !== requestUserId) return;
      if (titleRow?.title === "Новый диалог") {
        const { error: titleUpdateError } = await supabaseClient.from("assistant_conversations")
          .update({ title: value.slice(0, 72) }).eq("id", conversationId).eq("user_id", requestUserId);
        if (titleUpdateError) throw titleUpdateError;
      }
      if (authSession?.user?.id !== requestUserId) return;
      const activeProject = activeMovieId ? movieRead().find(project => project.id === activeMovieId) : null;
      const projectContext = activeProject ? {
        title: String(activeProject.name || "Без названия").slice(0, 120),
        idea: String(activeProject.idea || "").slice(0, 2000),
        genre: String(activeProject.genre || "").slice(0, 80),
        duration_minutes: Number.isInteger(activeProject.duration) ? Math.min(30, Math.max(1, activeProject.duration)) : null,
        frame: ["16:9", "9:16", "1:1"].includes(activeProject.frame) ? activeProject.frame : null,
        story: String(activeProject.story || "").slice(0, 6000),
        storyboard: String(activeProject.storyboard || "").slice(0, 6000),
        characters: String(activeProject.characters || "").slice(0, 3000),
        visual_continuity: (Array.isArray(activeProject.visualContinuity)?activeProject.visualContinuity:[]).slice(0,12).map(ref=>({type:ref.type==="scene"?"scene":"character",name:String(ref.name||"").slice(0,80),description:String(ref.description||"").slice(0,3000),...(ref.passport?{passport:{face:String(ref.passport.face||"").slice(0,600),profile:String(ref.passport.profile||"").slice(0,600),fullBody:String(ref.passport.fullBody||"").slice(0,600),wardrobe:String(ref.passport.wardrobe||"").slice(0,800),palette:String(ref.passport.palette||"").slice(0,300),expressions:String(ref.passport.expressions||"").slice(0,500)}}:{})})),
        voices: String(activeProject.voices || "").slice(0, 2000),
        edit: String(activeProject.edit || "").slice(0, 2000)
      } : null;
      const chatPayload = {
        message: value,
        history: chatHistory,
        ...(projectContext ? { project_context: projectContext } : {})
      };
      const result = await apiRequest("/api/chat", { method: "POST", body: JSON.stringify(chatPayload) });
      if (authSession?.user?.id !== requestUserId) {
        setAssistantStatus("Сеанс аккаунта изменился. Ответ не был сохранён в другом аккаунте.");
        return;
      }
      const { error: assistantSaveError } = await supabaseClient.from("assistant_messages")
        .insert({ conversation_id: conversationId, user_id: requestUserId, role: "assistant", content: result.reply });
      if (assistantSaveError) throw assistantSaveError;
      if (authSession?.user?.id !== requestUserId) return;
      renderAssistantMessage("assistant", result.reply);
      await renderAssistantHistory();
    } catch (error) {
      if (authSession?.user?.id === requestUserId) setAssistantStatus("Сообщение не удалось полностью обработать: " + error.message);
    } finally { button.disabled = false; input.disabled = false; input.focus(); }
  });
  setTimeout(() => renderAssistantHistory(), 0);


  // Mini Movie Studio: resilient local drafts with per-project editing and staged workflow.
  const movieStorageKey = () => "pwa-studio-movie-projects:" + (authSession?.user?.id || "guest");
  const movieVaultKey = (kind, userId = authSession?.user?.id || "guest") => "movie:" + kind + ":" + userId;
  let activeMovieId = null;
  let editingMovieId = null;
  const movieStages = [
    {key:"story",title:"Сценарий и раскадровка",fields:[["story","Сценарий","Напишите историю, действия и диалоги по сценам."],["storyboard","Раскадровка","Опишите кадры, планы камеры, движение и переходы."]]},
    {key:"characters",title:"Персонажи и аватары",fields:[["characters","Персонажи","Опишите героев: внешность, одежду, характер и особенности образа."]]},
    {key:"voices",title:"Голоса и озвучка",fields:[["voices","Голоса и звук","Назначьте голос каждому персонажу, укажите язык, манеру речи, реплики, музыку и звуковые эффекты."]]},
    {key:"edit",title:"Монтаж и экспорт",fields:[["edit","План монтажа","Опишите порядок сцен, длительность, переходы, музыку, титры и параметры будущего экспорта. Реальный видеорендер пока не подключён."]]}
  ];
  // Cloud persistence for movie projects. Supabase RLS scopes every query to the signed-in owner.
  const movieCloudState = { syncing: false, pending: false, loadingUser: null, timer: null, syncRetryCount: 0, syncRetryUser: null, loadRetryCount: 0, loadRetryUser: null, loadRetryTimer: null };
  const movieDeletedKey = () => "pwa-studio-movie-deleted:" + (authSession?.user?.id || "guest");
  const readMovieTombstones = (key = movieDeletedKey()) => {
    try { const value = JSON.parse(localStorage.getItem(key) || "[]"); return Array.isArray(value) ? value.filter(isUuid) : []; }
    catch { return []; }
  };
  const writeMovieTombstones = (ids, key = movieDeletedKey()) => {
    const clean = [...new Set(ids.filter(isUuid))];
    try { localStorage.setItem(key, JSON.stringify(clean)); }
    catch (error) { console.error("Movie deletion queue failed:", error); return false; }
    const ownerId = authSession?.user?.id || "guest";
    window.PWAMovieVault?.set(movieVaultKey("tombstones", ownerId), clean).catch(error => console.warn("IndexedDB tombstone mirror failed:", error));
    return true;
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
  const scheduleMovieCloudSync = (delayMs = 350, expectedUserId = null) => {
    const scheduledUserId = authSession?.user?.id;
    if (!scheduledUserId || !supabaseClient || (expectedUserId && expectedUserId !== scheduledUserId)) return;
    clearTimeout(movieCloudState.timer);
    movieCloudState.timer = setTimeout(async () => {
      const userId = scheduledUserId;
      if (!userId || !supabaseClient || authSession?.user?.id !== userId) return;
      if (movieCloudState.syncing) { movieCloudState.pending = true; return; }
      const projectKey = "pwa-studio-movie-projects:" + userId;
      const deletedKey = "pwa-studio-movie-deleted:" + userId;
      movieCloudState.syncing = true;
      try {
        const deletedIds = readMovieTombstones(deletedKey);
        if (deletedIds.length) {
          const { error: deleteError } = await supabaseClient.from("projects").delete()
            .in("id", deletedIds).eq("owner_id", userId).eq("project_type", "movie");
          if (deleteError) throw deleteError;
          if (authSession?.user?.id !== userId) return;
          writeMovieTombstones(readMovieTombstones(deletedKey).filter(id => !deletedIds.includes(id)), deletedKey);
        }
        if (authSession?.user?.id !== userId) return;
        let localProjects;
        try {
          const stored = JSON.parse(localStorage.getItem(projectKey) || "[]");
          localProjects = Array.isArray(stored)
            ? stored.filter(project => project && typeof project === "object" && project.id && !deletedIds.includes(project.id))
            : [];
        } catch { localProjects = []; }
        const rows = localProjects.map(project => movieToCloudRow(project, userId));
        // Persist UUID normalization only to the account-specific local key captured above.
        localStorage.setItem(projectKey, JSON.stringify(localProjects));
        if (rows.length) {
          if (authSession?.user?.id !== userId) return;
          const { error } = await supabaseClient.from("projects").upsert(rows, { onConflict: "id" });
          if (error) throw error;
        }
        if (authSession?.user?.id !== userId) return;
        movieCloudState.syncRetryCount = 0;
        movieCloudState.syncRetryUser = userId;
        const feedback = $("#movieFeedback");
        if (feedback) feedback.textContent = deletedIds.length
          ? "✓ Фильмы и удаления синхронизированы с облаком Supabase."
          : "✓ Изменения сохранены в облаке Supabase.";
      } catch (error) {
        console.error("Movie cloud sync failed:", error);
        if (authSession?.user?.id === userId) {
          if (movieCloudState.syncRetryUser !== userId) { movieCloudState.syncRetryUser = userId; movieCloudState.syncRetryCount = 0; }
          movieCloudState.syncRetryCount = Math.min(movieCloudState.syncRetryCount + 1, 9);
        }
        if (authSession?.user?.id === userId) {
          const feedback = $("#movieFeedback");
          if (feedback) feedback.textContent = "Черновик сохранён на этом устройстве, но облачная синхронизация не удалась. Проверьте соединение и повторите попытку.";
        }
      } finally {
        movieCloudState.syncing = false;
        if (movieCloudState.pending) {
          movieCloudState.pending = false;
          if (authSession?.user?.id === userId) scheduleMovieCloudSync(350, userId);
        } else if (movieCloudState.syncRetryUser === userId && movieCloudState.syncRetryCount > 0 && authSession?.user?.id === userId) {
          const retryDelay = Math.min(1000 * (2 ** (movieCloudState.syncRetryCount - 1)), 300000);
          scheduleMovieCloudSync(retryDelay, userId);
        }
      }
    }, Math.max(0, delayMs));
  };
  const loadMovieProjectsFromCloud = async () => {
    const userId = authSession?.user?.id;
    if (!userId || !supabaseClient || movieCloudState.loadingUser === userId) return;
    movieCloudState.loadingUser = userId;
    const deletedKey = "pwa-studio-movie-deleted:" + userId;
    try {
      const { data, error } = await supabaseClient
        .from("projects")
        .select("id, owner_id, title, description, project_type, status, settings, created_at, updated_at")
        .eq("project_type", "movie")
        .order("updated_at", { ascending: false });
      if (error) throw error;
      if (authSession?.user?.id !== userId) return;
      const deletedIds = readMovieTombstones(deletedKey);
      if (deletedIds.length) {
        const { error: deleteError } = await supabaseClient.from("projects").delete()
          .in("id", deletedIds).eq("owner_id", userId).eq("project_type", "movie");
        if (deleteError) throw deleteError;
        if (authSession?.user?.id !== userId) return;
        writeMovieTombstones([], deletedKey);
      }
      if (authSession?.user?.id !== userId) return;
      movieCloudState.loadRetryCount = 0;
      movieCloudState.loadRetryUser = userId;
      clearTimeout(movieCloudState.loadRetryTimer);
      movieCloudState.loadRetryTimer = null;
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
      if (movieWrite(projects)) {
        renderMovieProjects();
        scheduleMovieCloudSync();
        const feedback = $("#movieFeedback");
        if (feedback) feedback.textContent = "✓ Фильмы загружены из облака. Изменения синхронизируются автоматически.";
      }
    } catch (error) {
      console.error("Movie cloud load failed:", error);
      if (authSession?.user?.id === userId) {
        if (movieCloudState.loadRetryUser !== userId) { movieCloudState.loadRetryUser = userId; movieCloudState.loadRetryCount = 0; }
        movieCloudState.loadRetryCount = Math.min(movieCloudState.loadRetryCount + 1, 9);
        const retryDelay = Math.min(2000 * (2 ** (movieCloudState.loadRetryCount - 1)), 300000);
        clearTimeout(movieCloudState.loadRetryTimer);
        movieCloudState.loadRetryTimer = setTimeout(() => {
          if (authSession?.user?.id === userId) loadMovieProjectsFromCloud();
        }, retryDelay);
        const feedback = $("#movieFeedback");
        if (feedback) feedback.textContent = "Не удалось загрузить фильмы из облака. Локальные черновики сохранены; повторная попытка запланирована.";
      }
    } finally {
      if (movieCloudState.loadingUser === userId) movieCloudState.loadingUser = null;
    }
  };
  window.addEventListener("online", () => {
    const userId = authSession?.user?.id;
    if (!userId || !supabaseClient) return;
    loadMovieProjectsFromCloud();
    scheduleMovieCloudSync(0, userId);
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && authSession?.user?.id) {
      scheduleMovieCloudSync(0, authSession.user.id);
    }
  });
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
      const active = authSession?.user ? projects : projects.filter(project => {
        const expired = Date.parse(project.guestExpiresAt) <= now;
        if (expired) changed = true;
        return !expired;
      });
      if (changed) {
        if (!authSession?.user && active.length !== projects.length) sessionStorage.setItem("pwa-studio-guest-expired-notice", "1");
        localStorage.setItem(movieStorageKey(), JSON.stringify(active));
      }
      return active.sort((a, b) => new Date(b.updatedAt || b.createdAt || 0) - new Date(a.updatedAt || a.createdAt || 0));
    } catch { return []; }
  };
  const movieWrite = projects => {
    const ownerId = authSession?.user?.id || "guest";
    try {
      localStorage.setItem(movieStorageKey(), JSON.stringify(projects));
      window.PWAMovieVault?.set(movieVaultKey("projects", ownerId), projects).catch(error => {
        console.warn("IndexedDB project mirror failed:", error);
        const feedback = $("#movieFeedback");
        if (feedback) feedback.textContent = "Проект сохранён в браузере, но резервная копия IndexedDB недоступна. Скачайте JSON-копию."; 
      });
      scheduleMovieCloudSync();
      if (typeof renderPromptLibrary === "function") renderPromptLibrary();
      return true;
    } catch (error) {
      console.error("Movie project storage failed:", error);
      const feedback = $("#movieFeedback");
      if (feedback) feedback.textContent = "Не удалось сохранить изменения в памяти браузера. Проверьте свободное место и настройки приватности.";
      return false;
    }
  };

  const restoreMovieStorageForCurrentUser = async () => {
    const ownerId = authSession?.user?.id || "guest";
    const localKey = "pwa-studio-movie-projects:" + ownerId;
    try {
      const record = await window.PWAMovieVault?.get(movieVaultKey("projects", ownerId));
      if ((authSession?.user?.id || null) !== (ownerId === "guest" ? null : ownerId)) return;
      const durableProjects = Array.isArray(record?.value) ? record.value : [];
      let localProjects = [];
      try { const parsed = JSON.parse(localStorage.getItem(localKey) || "[]"); if (Array.isArray(parsed)) localProjects = parsed; } catch {}
      if (durableProjects.length) {
        const merged = new Map(localProjects.filter(item => item && item.id).map(item => [item.id, item]));
        durableProjects.filter(item => item && item.id).forEach(item => {
          const current = merged.get(item.id);
          if (!current || Date.parse(item.updatedAt || item.createdAt || 0) > Date.parse(current.updatedAt || current.createdAt || 0)) merged.set(item.id, item);
        });
        const recovered = [...merged.values()];
        if (recovered.length > localProjects.length || recovered.some(item => !localProjects.some(local => local.id === item.id && Date.parse(local.updatedAt || local.createdAt || 0) >= Date.parse(item.updatedAt || item.createdAt || 0)))) {
          localStorage.setItem(localKey, JSON.stringify(recovered));
          renderMovieProjects();
        }
      } else if (localProjects.length) {
        await window.PWAMovieVault?.set(movieVaultKey("projects", ownerId), localProjects);
      }
      const tombstoneRecord = await window.PWAMovieVault?.get(movieVaultKey("tombstones", ownerId));
      const deletedKey = "pwa-studio-movie-deleted:" + ownerId;
      if (Array.isArray(tombstoneRecord?.value) && !localStorage.getItem(deletedKey)) localStorage.setItem(deletedKey, JSON.stringify(tombstoneRecord.value.filter(isUuid)));
      if (authSession?.user?.id !== (ownerId === "guest" ? null : ownerId)) return;
      const feedback = $("#movieFeedback");
      if (feedback && !feedback.textContent.includes("резервная копия")) feedback.textContent = "Локальная копия IndexedDB проверена. Облачная синхронизация работает отдельно.";
    } catch (error) {
      console.warn("IndexedDB recovery unavailable; localStorage remains active:", error);
      const feedback = $("#movieFeedback");
      if (feedback) feedback.textContent = "Работаем в резервном режиме браузера: IndexedDB недоступна. Скачивайте JSON-копии важных проектов.";
    }
  };
  const downloadMovieBackup = () => {
    const ownerId = authSession?.user?.id || null;
    const projects = movieRead();
    if (!projects.length) { window.alert("Пока нет проектов для резервного копирования."); return; }
    const backup = { format: "PWA Studio movie workspace backup", schemaVersion: 1, exportedAt: new Date().toISOString(), scope: ownerId ? "account" : "guest", ownerId, projects };
    const blob = new Blob([JSON.stringify(backup, null, 2)], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url; link.download = "pwa-studio-movie-backup-" + new Date().toISOString().slice(0,10) + ".json";
    document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const importMovieBackup = async file => {
    if (!file || file.size > 10 * 1024 * 1024) throw new Error("Файл резервной копии пуст или превышает 10 МБ.");
    const backup = JSON.parse(await file.text());
    const ownerId = authSession?.user?.id || null;
    if (!backup || backup.format !== "PWA Studio movie workspace backup" || backup.schemaVersion !== 1 || !Array.isArray(backup.projects) || backup.projects.length > 2000) throw new Error("Формат резервной копии не распознан или превышает допустимый объём.");
    if (backup.scope !== (ownerId ? "account" : "guest") || (ownerId && backup.ownerId !== ownerId) || (!ownerId && backup.ownerId !== null)) throw new Error("Эта копия создана для другого аккаунта или другого режима. Переключитесь на исходный аккаунт.");
    const valid = backup.projects.filter(project => project && typeof project === "object" && typeof project.id === "string" && project.id.length <= 128 && typeof project.name === "string" && project.name.length <= 300 && typeof (project.updatedAt || project.createdAt) === "string" && Number.isFinite(Date.parse(project.updatedAt || project.createdAt)));
    if (valid.length !== backup.projects.length) throw new Error("В копии есть проекты с некорректными идентификаторами или датами. Импорт отменён.");
    const merged = new Map(movieRead().map(project => [project.id, project]));
    valid.forEach(project => {
      const current = merged.get(project.id);
      if (!current || Date.parse(project.updatedAt || project.createdAt) > Date.parse(current.updatedAt || current.createdAt)) merged.set(project.id, project);
    });
    if (!movieWrite([...merged.values()])) throw new Error("Не удалось сохранить импортированные проекты. Проверьте свободное место.");
    renderMovieProjects();
    window.alert("Импорт завершён. Проекты объединены по ID; более новые локальные версии сохранены.");
  };
  const installMovieBackupControls = () => {
    const list = $("#movieProjectList");
    if (!list || $("#movieBackupToolbar")) return;
    const toolbar = document.createElement("div");
    toolbar.id = "movieBackupToolbar";
    toolbar.className = "movie-backup-toolbar";
    toolbar.style.cssText = "display:flex;gap:8px;flex-wrap:wrap;margin:0 0 12px";
    const exportButton = document.createElement("button");
    exportButton.type = "button"; exportButton.className = "secondary-button"; exportButton.textContent = "⇩ Резервная копия";
    exportButton.addEventListener("click", downloadMovieBackup);
    const importButton = document.createElement("button");
    importButton.type = "button"; importButton.className = "secondary-button"; importButton.textContent = "⇧ Восстановить из копии";
    const input = document.createElement("input");
    input.type = "file"; input.accept = "application/json,.json"; input.hidden = true;
    importButton.addEventListener("click", () => input.click());
    input.addEventListener("change", async () => {
      try { await importMovieBackup(input.files?.[0]); }
      catch (error) { window.alert("Не удалось восстановить копию: " + (error.message || "неизвестная ошибка")); }
      finally { input.value = ""; }
    });
    toolbar.append(exportButton, importButton, input);
    list.parentNode.insertBefore(toolbar, list);
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
    const title=document.createElement("h2"); title.textContent="Основные сведения о фильме";
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
    const form=document.createElement("div"); form.className="movie-stage-fields"; const inputs={};
    stage.fields.forEach(([key,labelText,placeholder])=>{
      const wrap=document.createElement("label"); wrap.className="movie-stage-field";
      const label=document.createElement("span"); label.textContent=labelText;
      const textarea=document.createElement("textarea"); textarea.rows=(key==="story"||key==="storyboard")?7:6; textarea.maxLength=30000; textarea.placeholder=placeholder;
      textarea.value=project[key]||(key==="story"?project.idea||"":""); inputs[key]=textarea; wrap.append(label,textarea); form.append(wrap);
    });
    const actions=document.createElement("div"); actions.className="movie-stage-actions";
    const draft=document.createElement("button"); draft.type="button"; draft.className="secondary-button"; draft.textContent="Сохранить черновик";
    let aiScriptStatus=null;
    if(stage.key==="story"){
      const aiGenerate=document.createElement("button"); aiGenerate.type="button"; aiGenerate.className="secondary-button";
      aiGenerate.textContent="✦ Создать сценарий и раскадровку с AI";
      aiScriptStatus=document.createElement("p"); aiScriptStatus.className="movie-stage-feedback";
      aiScriptStatus.setAttribute("role","status"); aiScriptStatus.setAttribute("aria-live","polite");
      aiScriptStatus.style.cssText="display:block;flex-basis:100%;margin:4px 0;";
      aiGenerate.addEventListener("click",async()=>{
        if(!authSession?.user){setAuthMode("signup");setAuthMessage("Войдите, чтобы создавать сценарии с AI.");return;}
        if(!project.idea?.trim()){aiScriptStatus.textContent="Сначала заполните идею фильма в основных сведениях.";return;}
        const userId=authSession.user.id; aiGenerate.disabled=true;
        aiGenerate.textContent="✦ AI пишет сценарий…"; aiScriptStatus.textContent="Создаём сценарий и покадровую раскадровку. Это может занять некоторое время.";
        try{
          const result=await apiRequest("/api/movie/script",{method:"POST",body:JSON.stringify({
            title:project.name||"Новый фильм",idea:project.idea,genre:project.genre||"Приключения",
            duration_minutes:Number(project.duration)||5,frame:project.frame||"16:9",language:"Русский"
          })});
          if(authSession?.user?.id!==userId)return;
          inputs.story.value=result.story; inputs.storyboard.value=result.storyboard;
          aiScriptStatus.textContent="✓ Сценарий и раскадровка готовы ("+result.provider+" · "+result.model+"). Проверьте текст и нажмите «Сохранить черновик».";
        }catch(error){if(authSession?.user?.id===userId)aiScriptStatus.textContent="Не удалось создать сценарий: "+error.message;}
        finally{aiGenerate.disabled=false;aiGenerate.textContent="✦ Создать сценарий и раскадровку с AI";}
      });
      actions.append(aiGenerate,aiScriptStatus);
    }
    if(stage.key==="story"){
      const directorButton=document.createElement("button"); directorButton.type="button"; directorButton.className="secondary-button";
      directorButton.textContent="🎬 Разложить сценарий на сцены (AI-режиссёр)";
      const directorStatus=document.createElement("p"); directorStatus.className="movie-stage-feedback";
      directorStatus.setAttribute("role","status"); directorStatus.setAttribute("aria-live","polite");
      directorStatus.style.cssText="display:block;flex-basis:100%;margin:4px 0;";
      directorButton.addEventListener("click",async()=>{
        if(!authSession?.user){setAuthMode("signup");setAuthMessage("Войдите, чтобы использовать AI-режиссёра.");return;}
        const screenplay=inputs.story.value.trim();
        if(screenplay.length<50){directorStatus.textContent="Сначала создайте или вставьте сценарий (не менее 50 символов).";return;}
        const userId=authSession.user.id; directorButton.disabled=true; directorButton.textContent="🎬 Режиссёр разбирает сценарий…";
        directorStatus.textContent="Формируем сцены, действия, персонажей, планы камеры и свет.";
        try{
          const result=await apiRequest("/api/movie/director",{method:"POST",body:JSON.stringify({
            title:project.name||"Новый фильм",story:screenplay,genre:project.genre||"Приключения",
            duration_minutes:Number(project.duration)||5,frame:project.frame||"16:9",language:"Русский"
          })});
          if(authSession?.user?.id!==userId)return;
          inputs.storyboard.value=JSON.stringify({scenes:result.scenes},null,2);
          directorStatus.textContent="✓ Подготовлено сцен: "+result.scenes.length+" ("+result.provider+" · "+result.model+"). Проверьте и сохраните черновик.";
        }catch(error){if(authSession?.user?.id===userId)directorStatus.textContent="Не удалось разбить сценарий на сцены: "+error.message;}
        finally{directorButton.disabled=false;directorButton.textContent="🎬 Разложить сценарий на сцены (AI-режиссёр)";}
      });
      actions.append(directorButton,directorStatus);
    }
    if(stage.key==="story"){
      const storyboardButton=document.createElement("button"); storyboardButton.type="button"; storyboardButton.className="secondary-button";
      storyboardButton.textContent="🎞 Создать покадровую раскадровку";
      const storyboardStatus=document.createElement("p"); storyboardStatus.className="movie-stage-feedback";
      storyboardStatus.setAttribute("role","status"); storyboardStatus.setAttribute("aria-live","polite");
      storyboardStatus.style.cssText="display:block;flex-basis:100%;margin:4px 0;";
      storyboardButton.addEventListener("click",async()=>{
        if(!authSession?.user){setAuthMode("signup");setAuthMessage("Войдите, чтобы создавать раскадровки с AI.");return;}
        let sceneData;
        try{sceneData=JSON.parse(inputs.storyboard.value);}
        catch(_){storyboardStatus.textContent="Сначала запустите AI-режиссёра и получите структурированный список сцен.";return;}
        if(!Array.isArray(sceneData?.scenes)||!sceneData.scenes.length){storyboardStatus.textContent="Сначала запустите AI-режиссёра: нужны готовые сцены.";return;}
        const userId=authSession.user.id; storyboardButton.disabled=true; storyboardButton.textContent="🎞 Рисуем план кадров…";
        storyboardStatus.textContent="Создаём последовательность кадров и описания для будущей генерации изображений.";
        try{
          const result=await apiRequest("/api/movie/storyboard",{method:"POST",body:JSON.stringify({
            title:project.name||"Новый фильм",scenes:sceneData.scenes,
            frame:project.frame||"16:9",visual_style:project.visualStyle||"Кинематографичный реализм",language:"Русский"
          })});
          if(authSession?.user?.id!==userId)return;
          inputs.storyboard.value=JSON.stringify({
            character_bible:result.characters,
            scenes:sceneData.scenes.map((scene,index)=>({
              ...scene,frames:result.scenes[index].frames
            }))
          },null,2);
          storyboardStatus.textContent="✓ Создан паспорт внешности "+result.characters.length+" персонажей и "+result.scenes.reduce((n,scene)=>n+scene.frames.length,0)+" кадров в "+result.scenes.length+" сценах. Проверьте и сохраните черновик.";
        }catch(error){if(authSession?.user?.id===userId)storyboardStatus.textContent="Не удалось создать раскадровку: "+error.message;}
        finally{storyboardButton.disabled=false;storyboardButton.textContent="🎞 Создать покадровую раскадровку";}
      });
      actions.append(storyboardButton,storyboardStatus);
    }
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
    editingMovieId=null;
    $("#movieForm").reset();
    setMovieCreationFormVisible(true);
    const workflow=$("#movieWorkflowPanel");
    if(workflow){workflow.hidden=true;workflow.removeAttribute("data-active-stage");}
    const submit=$("#movieForm button[type='submit']");
    if(submit)submit.innerHTML="Создать проект фильма <span>→</span>";
    $("#movieFeedback").textContent="Задайте основу нового фильма. Уже существующие проекты останутся без изменений.";
    $("#movieName").focus();
    $("#movieForm").scrollIntoView({behavior:"smooth",block:"center"});
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
  workflowStyle.textContent=".movie-project-accordion{padding:0!important;overflow:hidden}.movie-project-toggle{display:flex;align-items:center;gap:14px;width:100%;padding:16px 18px;text-align:left;color:inherit;background:transparent;border:0;cursor:pointer}.movie-project-toggle:hover,.movie-project-card.is-active .movie-project-toggle{background:rgba(160,130,230,.08)}.movie-project-number{display:grid;place-items:center;flex:0 0 36px;height:36px;border-radius:11px;background:rgba(157,121,235,.15);color:#c8aaff;font-weight:800;font-size:12px}.movie-project-heading{display:grid;gap:5px;min-width:0;flex:1}.movie-project-heading b{font-size:15px;overflow-wrap:anywhere}.movie-project-heading small,.movie-project-date,.movie-project-progress{color:var(--muted);font-size:12px}.movie-project-chevron{font-size:22px;color:#c8aaff;transition:transform .2s}.movie-project-details{padding:0 18px 18px 68px}.movie-project-details[hidden],.movie-workflow-panel[hidden]{display:none}.movie-project-details p{white-space:pre-wrap;line-height:1.65;margin:0 0 10px;color:var(--text)}.movie-project-progress{display:block;margin:8px 0}.movie-project-actions,.movie-stage-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}.movie-project-actions button,.movie-stage-actions button{min-height:40px}.movie-tool-card:disabled{opacity:.45;cursor:not-allowed;filter:grayscale(.5)}.movie-tool-card.is-locked em{font-style:normal}.movie-workflow-panel{margin:24px 0;padding:22px}.movie-workflow-head h2{margin:0 0 8px}.movie-workflow-head p,.movie-workflow-complete p{color:var(--muted);line-height:1.6}.movie-stage-fields{display:grid;gap:16px;margin-top:18px}.movie-stage-field{display:grid;gap:8px;font-weight:600}.movie-stage-field textarea{width:100%;min-height:130px;padding:13px;border:1px solid var(--border);border-radius:12px;background:var(--surface);color:var(--text);font:inherit;resize:vertical}.movie-stage-actions{justify-content:space-between}.movie-workflow-complete h2{margin-top:0}.danger-button{border:1px solid rgba(255,90,90,.35);color:#ff9292;background:rgba(255,70,70,.08);border-radius:10px;padding:9px 12px}@media(max-width:520px){.movie-project-toggle{padding:14px 12px;gap:10px}.movie-project-details{padding:0 12px 14px 58px}.movie-project-heading b{font-size:14px}.movie-project-actions button{font-size:12px;padding:8px 10px}.movie-workflow-panel{padding:15px}}";
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
  installMovieBackupControls();
  restoreMovieStorageForCurrentUser();

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
    if (value) {
      let parsed;
      try { parsed = new URL(value); } catch {
        apiStatus.textContent = "Укажите корректный полный адрес backend API.";
        return;
      }
      const isLocalApi = parsed.protocol === "http:" && ["localhost", "127.0.0.1"].includes(parsed.hostname);
      if ((parsed.protocol !== "https:" && !isLocalApi) || parsed.username || parsed.password || parsed.search || parsed.hash) {
        apiStatus.textContent = "Нужен HTTPS-адрес без логина, пароля, query и hash. HTTP разрешён только для localhost.";
        return;
      }
      const defaultOrigin = new URL(DEFAULT_API_BASE).origin;
      if (parsed.origin !== defaultOrigin && !isLocalApi) {
        const trusted = window.confirm("PWA Studio будет отправлять этому backend-серверу токен вашей сессии Supabase. Продолжайте только если вы владеете этим сервером или полностью ему доверяете. Разрешить этот адрес?");
        if (!trusted) {
          apiStatus.textContent = "Адрес не сохранён: сервер не подтверждён.";
          return;
        }
        localStorage.setItem(API_TRUST_KEY, parsed.origin);
      } else {
        localStorage.removeItem(API_TRUST_KEY);
      }
    } else {
      localStorage.removeItem(API_TRUST_KEY);
    }
    localStorage.setItem(API_URL_KEY, value);
    apiStatus.textContent = value ? "Адрес сохранён. Проверяем соединение…" : "Используется адрес API по умолчанию.";
    if (value) checkBackend();
    else checkBackend();
  });
  $("#testBackend").addEventListener("click", checkBackend);

  if ("serviceWorker" in navigator && location.protocol.startsWith("http")) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("./sw.js").catch(error => console.warn("PWA service worker:", error));
    });
  }
})();