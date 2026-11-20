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
    });
    supabaseClient.auth.onAuthStateChange((_event, session) => { refreshAuthUI(session); setTimeout(loadAccountRole, 0); });
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


  // Mini Movie Studio: project drafts are stored locally until cloud storage is connected.
  const movieStorageKey = () => "pwa-studio-movie-projects:" + (authSession?.user?.id || "guest");
  const readMovieProjects = () => {
    try { return JSON.parse(localStorage.getItem(movieStorageKey()) || "[]"); }
    catch { return []; }
  };
  const renderMovieProjects = () => {
    const list = $("#movieProjectList");
    if (!list) return;
    let projects = readMovieProjects();
    // Older test clicks may have created duplicate drafts. Keep one latest entry per title.
    const seenTitles = new Set();
    projects = projects.filter(project => {
      const key = String(project.name || "").trim().toLocaleLowerCase("ru-RU");
      if (!key || seenTitles.has(key)) return false;
      seenTitles.add(key);
      return true;
    });
    localStorage.setItem(movieStorageKey(), JSON.stringify(projects));
    $("#movieCount").textContent = projects.length + (projects.length === 1 ? " проект" : projects.length > 1 && projects.length < 5 ? " проекта" : " проектов");
    if (!projects.length) {
      list.innerHTML = '<div class="movie-empty"><span>✧</span><b>Здесь появятся ваши фильмы</b><small>Создайте первый проект, чтобы начать свою кинематографическую историю.</small></div>';
      return;
    }
    list.innerHTML = "";
    projects.forEach((project, index) => {
      const card = document.createElement("article");
      card.className = "movie-project-card movie-project-accordion";
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "movie-project-toggle";
      toggle.setAttribute("aria-expanded", "false");
      const number = document.createElement("span");
      number.className = "movie-project-number";
      number.textContent = String(index + 1).padStart(2, "0");
      const heading = document.createElement("span");
      heading.className = "movie-project-heading";
      const title = document.createElement("b");
      title.textContent = project.name;
      const details = document.createElement("small");
      details.textContent = project.genre + " · " + project.duration + " мин · " + project.frame;
      heading.append(title, details);
      const chevron = document.createElement("span");
      chevron.className = "movie-project-chevron";
      chevron.textContent = "⌄";
      toggle.append(number, heading, chevron);
      const panel = document.createElement("div");
      panel.className = "movie-project-details";
      panel.hidden = true;
      const idea = document.createElement("p");
      idea.textContent = project.idea || "Описание пока не добавлено.";
      const date = document.createElement("span");
      date.className = "movie-project-date";
      date.textContent = "Черновик · " + new Date(project.createdAt).toLocaleDateString("ru-RU");
      const actions = document.createElement("div");
      actions.className = "movie-project-actions";
      const resume = document.createElement("button");
      resume.type = "button";
      resume.className = "secondary-button";
      resume.textContent = "Продолжить работу над фильмом →";
      resume.addEventListener("click", () => {
        $("#movieName").value = project.name || "";
        $("#movieIdea").value = project.idea || "";
        $("#movieGenre").value = project.genre || "Приключения";
        $("#movieDuration").value = String(project.duration || 5);
        $("#movieFrame").value = project.frame || "16:9";
        $("#movieFeedback").textContent = "Открыт проект «" + project.name + "». Измените данные и сохраните обновления.";
        $("#movieForm").scrollIntoView({behavior:"smooth",block:"center"});
      });
      actions.append(resume);
      panel.append(idea, date, actions);
      toggle.addEventListener("click", () => {
        const opening = panel.hidden;
        panel.hidden = !opening;
        toggle.setAttribute("aria-expanded", String(opening));
        chevron.textContent = opening ? "⌃" : "⌄";
      });
      card.append(toggle, panel);
      list.append(card);
    });
  };
  $("#movieStart").addEventListener("click", () => {
    $("#movieName").focus();
    $("#movieForm").scrollIntoView({behavior:"smooth",block:"center"});
  });
  $("#movieForm").addEventListener("submit", event => {
    if (!authSession?.user) { event.preventDefault(); setAuthMode("signup"); setAuthMessage("Создайте аккаунт, чтобы сохранять собственные фильмы."); return; }
    event.preventDefault();
    const name = $("#movieName").value.trim();
    if (!name) {
      $("#movieFeedback").textContent = "Укажите название будущего фильма.";
      return;
    }
    const projects = readMovieProjects();
    const existingIndex = projects.findIndex(project => String(project.name || "").trim().toLocaleLowerCase("ru-RU") === name.toLocaleLowerCase("ru-RU"));
    const savedProject = {
      id: existingIndex >= 0 ? projects[existingIndex].id : ((window.crypto && crypto.randomUUID) ? crypto.randomUUID() : String(Date.now())),
      name,
      idea: $("#movieIdea").value.trim(),
      genre: $("#movieGenre").value,
      duration: Number($("#movieDuration").value),
      frame: $("#movieFrame").value,
      createdAt: existingIndex >= 0 ? projects[existingIndex].createdAt : new Date().toISOString(),
      updatedAt: new Date().toISOString()
    };
    try {
      if (existingIndex >= 0) projects[existingIndex] = savedProject;
      else projects.unshift(savedProject);
      localStorage.setItem(movieStorageKey(), JSON.stringify(projects));
      renderMovieProjects();
      $("#movieFeedback").textContent = existingIndex >= 0
        ? "✓ Проект «" + name + "» обновлён. Повторное сохранение не создаёт копию."
        : "✓ Проект «" + name + "» создан. Он появится отдельной раскрывающейся строкой в разделе «Мои фильмы».";
      $("#movieFeedback").setAttribute("role", "status");
      // Keep the form values so the creator can review or continue editing them.
      // Do not reset the form or change the page scroll position after saving.
    } catch {
      $("#movieFeedback").textContent = "Не удалось сохранить проект в памяти браузера. Проверьте свободное место и настройки приватности.";
    }
  });
  $("[data-movie-tool]").forEach(button => button.addEventListener("click", () => {
    const destinations = {story:"scenes",characters:"library",voice:"voice",edit:"editor"};
    navigate(destinations[button.dataset.movieTool] || "movie");
  }));
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