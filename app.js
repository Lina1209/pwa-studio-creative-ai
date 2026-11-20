(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const labels = {home:"Главная",create:"Создать видео",movie:"Миникиностудия",editor:"Видеоредактор",prompts:"Prompt Studio",library:"Медиатека",voice:"Голос и музыка",scenes:"Сценарий и сцены",assistant:"AI Companion",settings:"Настройки"};

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
    const topic = $("#topic").value.trim();
    $("#createFeedback").textContent = topic
      ? "Идея сохранена в форме. Следующий этап — подключение AI-сценариста и генерации сцен."
      : "Сначала напишите тему или идею будущего видео.";
  });

  $("#buildPrompt").addEventListener("click", () => {
    const idea = $("#promptIdea").value.trim();
    if (!idea) {
      $("#promptFeedback").textContent = "Добавьте описание вашей задумки, чтобы сформировать промт.";
      return;
    }
    const type = $("#promptType").value;
    const lang = $("#promptLanguage").value;
    const prompt = lang === "English"
      ? "Create a " + type.toLowerCase() + " based on this concept: " + idea + "\n\nVisual direction: cinematic composition, intentional lighting, rich but balanced colors, clear subject, refined details. Keep the result coherent and visually engaging.\n\nAvoid: distorted anatomy, unreadable text, visual artifacts, random objects, inconsistent scene details."
      : "Создай: " + type.toLowerCase() + " на основе этой идеи: " + idea + "\n\nВизуальное направление: продуманная композиция, выразительное освещение, гармоничная цветовая палитра, чёткий главный объект и внимание к деталям. Сохраняй целостность и выразительность результата.\n\nИсключить: искажения, нечитаемый текст, визуальные артефакты, случайные объекты и несогласованность деталей.";
    $("#promptOutput").textContent = prompt;
    $("#promptFeedback").textContent = "Подготовлен демонстрационный промт-шаблон. AI-улучшение и адаптация под конкретные модели появятся после подключения backend.";
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
  $("#assistantForm").addEventListener("submit", event => {
    event.preventDefault();
    const value = $("#assistantInput").value.trim();
    if (!value) return;
    $("#assistantInput").value = "";
    $("#assistantInput").placeholder = "Сообщение подготовлено. Для живого ответа подключим AI API.";
    const notice = document.createElement("div");
    notice.className = "helper-text";
    notice.textContent = "Ваш запрос: " + value + " — интерфейс готов, отправка в ИИ будет активирована после настройки backend.";
    $(".assistant-panel").insertBefore(notice, $(".assistant-panel").lastElementChild);
  });


  // Mini Movie Studio: project drafts are stored locally until cloud storage is connected.
  const movieStorageKey = "pwa-studio-movie-projects";
  const readMovieProjects = () => {
    try { return JSON.parse(localStorage.getItem(movieStorageKey) || "[]"); }
    catch { return []; }
  };
  const renderMovieProjects = () => {
    const list = $("#movieProjectList");
    if (!list) return;
    const projects = readMovieProjects();
    $("#movieCount").textContent = projects.length + (projects.length === 1 ? " проект" : projects.length > 1 && projects.length < 5 ? " проекта" : " проектов");
    if (!projects.length) {
      list.innerHTML = '<div class="movie-empty"><span>✧</span><b>Здесь появятся ваши фильмы</b><small>Создайте первый проект, чтобы начать свою кинематографическую историю.</small></div>';
      return;
    }
    list.innerHTML = projects.map(project => {
      const card = document.createElement("article");
      card.className = "movie-project-card";
      const title = document.createElement("b");
      title.textContent = project.name;
      const details = document.createElement("small");
      details.textContent = project.genre + " · " + project.duration + " мин · " + project.frame;
      const idea = document.createElement("p");
      idea.textContent = project.idea || "Описание пока не добавлено.";
      const date = document.createElement("span");
      date.textContent = "Черновик · " + new Date(project.createdAt).toLocaleDateString("ru-RU");
      card.append(title, details, idea, date);
      return card.outerHTML;
    }).join("");
  };
  $("#movieStart").addEventListener("click", () => {
    $("#movieName").focus();
    $("#movieForm").scrollIntoView({behavior:"smooth",block:"center"});
  });
  $("#movieForm").addEventListener("submit", event => {
    event.preventDefault();
    const name = $("#movieName").value.trim();
    if (!name) {
      $("#movieFeedback").textContent = "Укажите название будущего фильма.";
      return;
    }
    const projects = readMovieProjects();
    projects.unshift({
      id: (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : String(Date.now()),
      name,
      idea: $("#movieIdea").value.trim(),
      genre: $("#movieGenre").value,
      duration: Number($("#movieDuration").value),
      frame: $("#movieFrame").value,
      createdAt: new Date().toISOString()
    });
    try {
      localStorage.setItem(movieStorageKey, JSON.stringify(projects));
      renderMovieProjects();
      $("#movieFeedback").textContent = "Черновик фильма сохранён. Следующий этап — сценарий, персонажи и план сцен.";
      $("#movieForm").reset();
      $("#movieDuration").value = "5";
    } catch {
      $("#movieFeedback").textContent = "Не удалось сохранить проект в памяти браузера. Проверьте свободное место и настройки приватности.";
    }
  });
  $("[data-movie-tool]").forEach(button => button.addEventListener("click", () => {
    const destinations = {story:"scenes",characters:"library",voice:"voice",edit:"editor"};
    navigate(destinations[button.dataset.movieTool] || "movie");
  }));
  renderMovieProjects();

  if ("serviceWorker" in navigator && location.protocol.startsWith("http")) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("./sw.js").catch(error => console.warn("PWA service worker:", error));
    });
  }
})();