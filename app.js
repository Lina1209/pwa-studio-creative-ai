(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const labels = {home:"Главная",create:"Создать видео",editor:"Видеоредактор",prompts:"Prompt Studio",library:"Медиатека",voice:"Голос и музыка",scenes:"Сценарий и сцены",assistant:"AI Companion",settings:"Настройки"};

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

  if ("serviceWorker" in navigator && location.protocol.startsWith("http")) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("./sw.js").catch(error => console.warn("PWA service worker:", error));
    });
  }
})();