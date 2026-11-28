/* Read-only cloud restore review UI. No writes, downloads, or activation. */
(() => {
  "use strict";
  const $ = (selector, root=document) => root.querySelector(selector);
  const button = $("#previewCharacterRestore");
  const panel = $("#characterRestorePanel");
  const status = $("#characterRestoreStatus");
  const list = $("#characterRestoreChoices");
  const preview = $("#characterRestorePreview");
  if (!button || !panel || !status || !list || !preview) return;

  let issuedPlan = null;
  let issuedPreview = null;
  let ownerId = null;
  let contextVersion = null;

  const say = message => { status.textContent = message; };
  const current = () => {
    const bridge = window.PWAStudioCharacterRestoreBridge;
    return !!bridge && bridge.isCurrent(ownerId, contextVersion);
  };
  const element = (tag, text) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const clear = node => { while (node.firstChild) node.removeChild(node.firstChild); };

  function showChoices(plan) {
    clear(list);
    clear(preview);
    issuedPreview = null;
    const intro = element("p", "Выберите облачные карточки для проверки. Пока ничего не изменяется.");
    list.append(intro);
    for (const item of plan.cloudSummary) {
      const label = element("label");
      label.className = "character-restore-choice";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.value = item.cloudId;
      input.checked = true;
      const detail = element("span");
      const title = element("b", item.name);
      const meta = element("small", (item.kind === "scene" ? "Локация" : "Персонаж") + " · " + item.referenceCount + " изображений");
      detail.append(title, meta);
      label.append(input, detail);
      list.append(label);
    }
    const review = element("button", "Проверить выбранные карточки");
    review.type = "button";
    review.className = "secondary-button";
    review.addEventListener("click", () => buildPreview(plan));
    list.append(review);
    panel.hidden = false;
  }

  function buildPreview(plan) {
    if (!current()) { say("Аккаунт изменился. Начните проверку заново."); return; }
    const selectedCloudIds = [...list.querySelectorAll('input[type="checkbox"]:checked')].map(x => x.value);
    if (!selectedCloudIds.length) { say("Выберите хотя бы одну карточку."); return; }
    try {
      const api = window.PWACharacterCloudRestore;
      const selectedPlan = api.selectRestorePlan({ownerId, plan, selectedCloudIds});
      const reviewed = api.buildRestorePreview({ownerId, plan:selectedPlan});
      issuedPlan = selectedPlan;
      issuedPreview = reviewed;
      clear(preview);
      const summary = element("p", "Выбрано: " + reviewed.selectedCount +
        " · можно восстановить: " + reviewed.restorableCount +
        " · уже актуальны: " + reviewed.unchangedCount +
        " · конфликтов: " + reviewed.conflictCount +
        " · изображений: " + reviewed.referenceCount);
      preview.append(summary);
      for (const item of reviewed.items) {
        const row = element("div");
        row.className = "character-restore-preview-row";
        row.append(element("b", item.name + " — " + item.statusLabel));
        if (item.conflictMessage) row.append(element("small", item.conflictMessage));
        row.append(element("small", item.referencesPending
          ? item.referenceCount + " референсов. " + item.referencesPending + " требуют отдельного безопасного восстановления файлов."
          : item.referenceStatusLabel));
        preview.append(row);
      }
      if (reviewed.canContinue) {
        preview.append(element("p", "Проверка завершена. Для этой версии интерфейса доступен только просмотр плана; запись в библиотеку и загрузка файлов не выполняются."));
      } else {
        preview.append(element("p", "Продолжение заблокировано: выберите карточки без конфликтов, содержащие новые материалы."));
      }
      say("Облачный план проверен. Записей и файлов не изменено.");
    } catch (error) {
      clear(preview);
      say("Не удалось проверить план: " + error.message + " Локальная библиотека не изменена.");
    }
  }

  button.addEventListener("click", async () => {
    const bridge = window.PWAStudioCharacterRestoreBridge;
    const planner = window.PWACharacterCloudRestore;
    if (!bridge || !planner) { say("Модуль восстановления ещё загружается. Обновите страницу."); return; }
    const session = bridge.getSession();
    ownerId = session?.user?.id || null;
    contextVersion = bridge.getContextVersion();
    if (!ownerId || !session?.access_token) {
      say("Для просмотра облачной копии войдите в свой аккаунт. Гостевая библиотека останется на этом устройстве.");
      return;
    }
    button.disabled = true;
    button.textContent = "⏳ Проверяем облачную библиотеку…";
    try {
      const localItems = bridge.getLocalItems();
      const plan = await planner.planRestore({
        ownerId,
        existingLocalItems: localItems,
        isCurrent: current,
        fetchPage: async cursor => {
          const query = new URLSearchParams({limit:"100"});
          if (cursor) query.set("cursor", cursor);
          return bridge.apiRequest("/api/characters?" + query.toString());
        },
        fetchReferences: async ids => {
          const query = new URLSearchParams({character_ids:ids.join(",")});
          return bridge.apiRequest("/api/media/character-references?" + query.toString());
        }
      });
      if (!current()) throw new Error("Аккаунт изменился во время проверки.");
      issuedPlan = plan;
      showChoices(plan);
      say("Найдено облачных карточек: " + plan.cloudCount + ". Выберите материалы и проверьте конфликты.");
      if (!plan.cloudCount) say("В облачной библиотеке пока нет сохранённых карточек.");
    } catch (error) {
      say("Проверка не завершена: " + error.message + " Никакие данные не изменены.");
      clear(list);
      clear(preview);
      panel.hidden = false;
    } finally {
      button.disabled = false;
      button.textContent = "☁ Проверить облачную копию";
    }
  });

  window.addEventListener("pwa-studio-auth-changed", () => {
    issuedPlan = null;
    issuedPreview = null;
    ownerId = null;
    contextVersion = null;
    panel.hidden = true;
    clear(list);
    clear(preview);
  });
})();
