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
      refreshAuthUI(data?.session || null);
      setTimeout(() => { if (typeof renderMovieProjects === "function") renderMovieProjects(); if (typeof loadMovieProjectsFromCloud === "function") loadMovieProjectsFromCloud(); if (typeof loadAccountRole === "function") loadAccountRole(); }, 0);
    });
    supabaseClient.auth.onAuthStateChange((_event, session) => { refreshAuthUI(session); setTimeout(() => { loadAccountRole(); if (typeof renderMovieProjects === "function") renderMovieProjects(); if (typeof loadMovieProjectsFromCloud === "function") loadMovieProjectsFromCloud(); }, 0); });
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
    try {
      const data = await apiRequest("/api/auth/me");
      $("#accountRole").textContent = data.role === "admin" ? "Владелец студии" : "Автор";
      panel.hidden = data.role !== "admin";
    } catch { panel.hidden = true; }
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
  if (authSession?.user) setTimeout(loadAccountRole, 0);
  const labels = {account:"Личный кабинет",rules:"Правила и безопасность",home:"Главная",create:"Создать видео",movie:"Миникиностудия",editor:"Видеоредактор",prompts:"Prompt Studio",library:"Медиатека",voice:"Голос и музыка",scenes:"Сценарий и сцены",assistant:"AI Companion",guide:"Путеводитель",about:"О студии",settings:"Настройки"};

  function navigate(view) {
    if (!labels[view]) return;
    $$(".view").forEach(el => el.classList.toggle("active", el.id === "view-" + view));
    $$(".nav-item[data-view]").forEach(el => el.classList.toggle("active", el.dataset.view === view));
    $("#crumbCurrent").textContent = labels[view];
    $("#sidebar").classList.remove("open");
    window.location.hash = view === "home" ? "" : view;
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
  $("#assistantForm").addEventListener("submit", async event => {
    event.preventDefault();
    const input = $("#assistantInput");
    const value = input.value.trim();
    if (!value) return;
    if (!authSession?.user) { setAuthMode("signup"); setAuthMessage("Войдите или зарегистрируйтесь, чтобы общаться с AI Companion."); return; }
    const button = $("#assistantForm button");
    button.disabled = true;
    input.disabled = true;
    const addMessage = (kind, content) => {
      const bubble = document.createElement("div");
      bubble.className = "helper-text assistant-message " + kind;
      bubble.textContent = content;
      $(".assistant-panel").insertBefore(bubble, $("#assistantForm"));
    };
    addMessage("user-message", "Вы: " + value);
    input.value = "";
    try {
      const result = await apiRequest("/api/chat", { method: "POST", body: JSON.stringify({ message: value }) });
      addMessage("ai-message", "Studio AI: " + result.reply);
    } catch (error) {
      addMessage("error-message", "Не удалось получить ответ: " + error.message);
    } finally {
      button.disabled = false;
      input.disabled = false;
      input.focus();
    }
  });


  // Mini Movie Studio: resilient local drafts with per-project editing and staged workflow.
  const movieStorageKey = () => "pwa-studio-movie-projects:" + (authSession?.user?.id || "guest");
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
  const movieToCloudRow = project => {
    if (!isUuid(project.id)) project.id = movieId();
    const snapshot = { ...project, cloudSchemaVersion: 1 };
    return {
      id: project.id,
      owner_id: authSession.user.id,
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
    if (!authSession?.user || !supabaseClient) return;
    clearTimeout(movieCloudState.timer);
    movieCloudState.timer = setTimeout(async () => {
      if (!authSession?.user) return;
      if (movieCloudState.syncing) { movieCloudState.pending = true; return; }
      movieCloudState.syncing = true;
      try {
        const deletedIds = readMovieTombstones();
        if (deletedIds.length) {
          const { error: deleteError } = await supabaseClient.from("projects").delete()
            .in("id", deletedIds).eq("owner_id", authSession.user.id).eq("project_type", "movie");
          if (deleteError) throw deleteError;
          writeMovieTombstones(readMovieTombstones().filter(id => !deletedIds.includes(id)));
        }
        const localProjects = movieRead().filter(project => !deletedIds.includes(project.id));
        const rows = localProjects.map(movieToCloudRow);
        // Persist any UUID normalization before sending rows to Supabase.
        localStorage.setItem(movieStorageKey(), JSON.stringify(localProjects));
        if (rows.length) {
          const { error } = await supabaseClient.from("projects").upsert(rows, { onConflict: "id" });
          if (error) throw error;
        }
        const feedback = $("#movieFeedback");
        if (feedback) feedback.textContent = deletedIds.length
          ? "✓ Фильмы и удаления синхронизированы с облаком Supabase."
          : "✓ Изменения сохранены в облаке Supabase.";
      } catch (error) {
        console.error("Movie cloud sync failed:", error);
        const feedback = $("#movieFeedback");
        if (feedback) feedback.textContent = "Черновик сохранён на этом устройстве, но облачная синхронизация не удалась. Проверьте соединение и повторите попытку.";
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
    movieCloudState.loadingUser = userId;
    try {
      const { data, error } = await supabaseClient
        .from("projects")
        .select("id, owner_id, title, description, project_type, status, settings, created_at, updated_at")
        .eq("project_type", "movie")
        .order("updated_at", { ascending: false });
      if (error) throw error;
      if (authSession?.user?.id !== userId) return;
      const deletedIds = readMovieTombstones();
      if (deletedIds.length) {
        const { error: deleteError } = await supabaseClient.from("projects").delete()
          .in("id", deletedIds).eq("owner_id", userId).eq("project_type", "movie");
        if (deleteError) throw deleteError;
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
      if (movieWrite(projects)) {
        renderMovieProjects();
        scheduleMovieCloudSync();
        const feedback = $("#movieFeedback");
        if (feedback) feedback.textContent = "✓ Фильмы загружены из облака. Изменения синхронизируются автоматически.";
      }
    } catch (error) {
      console.error("Movie cloud load failed:", error);
      const feedback = $("#movieFeedback");
      if (feedback) feedback.textContent = "Не удалось загрузить фильмы из облака. Локальные черновики сохранены на устройстве.";
    } finally {
      if (movieCloudState.loadingUser === userId) movieCloudState.loadingUser = null;
    }
  };
  const movieRead = () => {
    try {
      const value = JSON.parse(localStorage.getItem(movieStorageKey()) || "[]");
      return Array.isArray(value) ? value.filter(item => item && typeof item === "object" && item.id).map(item => ({
        ...item,
        // Keep older projects editable: their screenplay may exist only in the original idea field.
        story: item.story || item.idea || "",
        completedSteps: Array.isArray(item.completedSteps) ? item.completedSteps.filter(key => movieStages.some(stage => stage.key === key)) : []
      })) : [];
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
  const openMovieStage = (projectId,stageIndex) => {
    const projects=movieRead(); const project=projects.find(item=>item.id===projectId); const panel=ensureMovieWorkflowPanel();
    if(!project||!panel||stageIndex<0||stageIndex>=movieStages.length)return;
    const done=Array.isArray(project.completedSteps)?project.completedSteps:[];
    if(stageIndex>0&&!done.includes(movieStages[stageIndex-1].key)){const feedback=$("#movieFeedback");if(feedback)feedback.textContent="Сначала завершите предыдущий этап.";return;}
    activeMovieId=projectId; updateMovieStageCards();
    const stage=movieStages[stageIndex]; panel.replaceChildren();
    const head=document.createElement("div"); head.className="movie-workflow-head";
    const title=document.createElement("h2"); title.textContent="Этап "+(stageIndex+1)+" из 4 · "+stage.title;
    const subtitle=document.createElement("p"); subtitle.textContent="Фильм: "+project.name+" · "+(done.includes(stage.key)?"Этап сохранён — его можно редактировать.":"Заполните материалы и сохраните, чтобы открыть следующий этап.");
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
    const close=document.createElement("button"); close.type="button"; close.className="secondary-button"; close.textContent="← К проекту"; close.addEventListener("click",()=>{panel.hidden=true;});
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
        const back=document.createElement("button"); back.type="button"; back.className="secondary-button"; back.textContent="Вернуться к проекту"; back.addEventListener("click",()=>{panel.hidden=true;});
        complete.append(h,p,back); panel.append(complete);
      }
    });
    actions.append(draft,close,save,draftStatus); panel.append(head,form,actions); panel.hidden=false; panel.setAttribute("data-active-stage",stage.key); requestAnimationFrame(()=>panel.scrollIntoView({behavior:"smooth",block:"start"}));
  };
  const openMovieOverview = projectId => {
    const project=movieRead().find(item=>item.id===projectId); const panel=ensureMovieWorkflowPanel();
    if(!project||!panel)return;
    activeMovieId=projectId; updateMovieStageCards(); panel.replaceChildren();
    const done=Array.isArray(project.completedSteps)?project.completedSteps:[];
    const allDone=movieStages.every(stage=>done.includes(stage.key));
    const head=document.createElement("div"); head.className="movie-workflow-head";
    const title=document.createElement("h2"); title.textContent=allDone?"✓ Все этапы завершены":"Рабочие этапы фильма";
    const subtitle=document.createElement("p"); subtitle.textContent="Фильм: "+project.name+" · "+movieProgress(project)+". Выберите доступный этап для просмотра или редактирования.";
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
      const details=document.createElement("small"); details.textContent=(project.genre||"Жанр не указан")+" · "+(project.duration||5)+" мин · "+(project.frame||"16:9");
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
      const editDetails=makeAction("Изменить сведения","secondary-button",()=>{
        activeMovieId=project.id; editingMovieId=project.id;
        $("#movieName").value=project.name||""; $("#movieIdea").value=project.idea||""; $("#movieGenre").value=project.genre||"Приключения";
        $("#movieDuration").value=String(project.duration||5); $("#movieFrame").value=project.frame||"16:9";
        const submit=$('#movieForm button[type="submit"]'); if(submit)submit.innerHTML="Сохранить изменения <span>→</span>";
        $("#movieFeedback").textContent="Изменение основных сведений фильма. Сценарий и этапы останутся отдельными материалами.";
        $("#movieForm").scrollIntoView({behavior:"smooth",block:"center"});
      });
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
        const latest=movieRead(); const current=latest.find(item=>item.id===project.id); if(!current)return;
        const versions=Array.isArray(current.versions)?current.versions:[];
        if(!versions.length){$("#movieFeedback").textContent="Пока нет сохранённых версий. Они создаются автоматически перед изменениями.";return;}
        const choice=window.prompt("Введите номер версии для восстановления:\n"+versions.map((v,i)=>(i+1)+". "+movieDate(v.savedAt)).join("\n"));
        if(choice===null)return; const n=Number(choice);
        if(!Number.isInteger(n)||n<1||n>versions.length){$("#movieFeedback").textContent="Номер версии указан неверно.";return;}
        const restored=versions[n-1].data; addMovieVersion(current); const keepVersions=current.versions;
        latest[latest.findIndex(item=>item.id===project.id)]={...restored,versions:keepVersions,updatedAt:new Date().toISOString()};
        if(movieWrite(latest)){renderMovieProjects();$("#movieFeedback").textContent="Предыдущая версия восстановлена. Текущая версия сохранена в истории.";}
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
    if(!authSession?.user){setAuthMode("signup");setAuthMessage("Войдите или зарегистрируйтесь, чтобы сохранять собственные фильмы. Введённые поля останутся на месте.");return;}
    const name=$("#movieName").value.trim(); if(!name){$("#movieFeedback").textContent="Укажите название будущего фильма.";return;}
    const projects=movieRead(); const existingIndex=editingMovieId?projects.findIndex(item=>item.id===editingMovieId):-1; const now=new Date().toISOString();
    let savedProject;
    if(existingIndex>=0){
      savedProject=projects[existingIndex]; addMovieVersion(savedProject);
      const ideaChanged=(savedProject.idea||"")!==$("#movieIdea").value.trim();
      Object.assign(savedProject,{name,idea:$("#movieIdea").value.trim(),genre:$("#movieGenre").value,duration:Number($("#movieDuration").value),frame:$("#movieFrame").value,updatedAt:now});
      if(ideaChanged){savedProject.completedSteps=[];savedProject.workflowStep=0;}
      projects[existingIndex]=savedProject;
    }else{
      savedProject={id:movieId(),name,idea:$("#movieIdea").value.trim(),genre:$("#movieGenre").value,duration:Number($("#movieDuration").value),frame:$("#movieFrame").value,createdAt:now,updatedAt:now,workflowStep:0,completedSteps:[],story:"",storyboard:"",characters:"",voices:"",edit:"",versions:[]};
      projects.unshift(savedProject);
    }
    if(!movieWrite(projects))return;
    activeMovieId=savedProject.id; editingMovieId=savedProject.id;
    const submit=$("#movieForm button[type='submit']"); if(submit)submit.innerHTML="Создать проект фильма <span>→</span>";
    renderMovieProjects();
    $("#movieFeedback").textContent=existingIndex>=0?"✓ Изменения сохранены в проекте «"+name+"».":"✓ Фильм «"+name+"» создан. Форма теперь редактирует этот проект; для нового фильма нажмите «Новый фильм». Этап 1 — сценарий и раскадровка — уже доступен.";
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