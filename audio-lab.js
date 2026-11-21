(() => {
  "use strict";
  const $ = (selector) => document.querySelector(selector);
  const tabs = [...document.querySelectorAll("[data-audio-tab]")];
  const panels = [...document.querySelectorAll("[data-audio-panel]")];
  const activateTab = (name) => {
    tabs.forEach((tab) => {
      const active = tab.dataset.audioTab === name;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
    });
    panels.forEach((panel) => {
      const active = panel.dataset.audioPanel === name;
      panel.hidden = !active;
      panel.classList.toggle("active", active);
    });
  };
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => activateTab(tab.dataset.audioTab));
    tab.addEventListener("keydown", (event) => {
      if (!["ArrowRight", "ArrowLeft", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 :
        (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
      tabs[next].focus();
      activateTab(tabs[next].dataset.audioTab);
    });
  });
  document.querySelectorAll("[data-audio-tab-go]").forEach((button) => {
    button.addEventListener("click", () => {
      activateTab(button.dataset.audioTabGo);
      $("#audio-tab-" + button.dataset.audioTabGo)?.scrollIntoView({behavior:"smooth",block:"nearest"});
    });
  });
  document.querySelectorAll(".audio-chip").forEach((chip) => {
    chip.addEventListener("click", () => chip.classList.toggle("active"));
  });
  const speechText = $("#audioSpeechText");
  const speechCount = $("#audioSpeechCount");
  speechText?.addEventListener("input", () => {
    speechCount.textContent = speechText.value.length + " / 5000";
  });

  const recordStart = $("#audioRecordStart");
  const recordStop = $("#audioRecordStop");
  const recordStatus = $("#audioRecordStatus");
  const fileInput = $("#audioVoiceFile");
  const fileStatus = $("#audioFileStatus");
  const preview = $("#audioVoicePreview");
  const previewName = $("#audioPreviewName");
  const clearPreview = $("#audioClearPreview");
  let mediaRecorder = null;
  let mediaStream = null;
  let chunks = [];
  let previewUrl = null;

  const showPreview = (blob, name) => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = URL.createObjectURL(blob);
    preview.src = previewUrl;
    preview.hidden = false;
    previewName.textContent = name;
    clearPreview.disabled = false;
  };
  const clearAudio = () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = null;
    preview.pause();
    preview.removeAttribute("src");
    preview.load();
    preview.hidden = true;
    previewName.textContent = "Пока нет аудиозаписи";
    clearPreview.disabled = true;
    if (fileInput) fileInput.value = "";
    if (fileStatus) fileStatus.textContent = "Файл не выбран.";
  };
  clearPreview?.addEventListener("click", clearAudio);
  fileInput?.addEventListener("change", () => {
    const file = fileInput.files?.[0];
    if (!file) return;
    if (!file.type.startsWith("audio/")) {
      fileStatus.textContent = "Выберите аудиофайл.";
      fileInput.value = "";
      return;
    }
    showPreview(file, file.name);
    fileStatus.textContent = "Файл выбран. Он не загружается на сервер.";
  });
  recordStart?.addEventListener("click", async () => {
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      recordStatus.textContent = "Запись микрофона не поддерживается этим браузером. Можно загрузить аудиофайл.";
      return;
    }
    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({audio:true});
      chunks = [];
      mediaRecorder = new MediaRecorder(mediaStream);
      mediaRecorder.addEventListener("dataavailable", (event) => {
        if (event.data?.size) chunks.push(event.data);
      });
      mediaRecorder.addEventListener("stop", () => {
        const blob = new Blob(chunks, {type:mediaRecorder.mimeType || "audio/webm"});
        if (blob.size) showPreview(blob, "Запись с микрофона · локальный образец");
        recordStatus.textContent = blob.size ? "Запись готова для локального прослушивания. Она не отправлена на сервер." : "Не удалось получить аудиоданные. Попробуйте ещё раз.";
        mediaStream?.getTracks().forEach((track) => track.stop());
        mediaStream = null;
        recordStart.disabled = false;
        recordStop.disabled = true;
      });
      mediaRecorder.start();
      recordStart.disabled = true;
      recordStop.disabled = false;
      recordStatus.textContent = "Идёт запись. Нажмите «Остановить», когда закончите.";
    } catch (error) {
      recordStatus.textContent = error?.name === "NotAllowedError"
        ? "Доступ к микрофону не разрешён. Проверьте разрешения браузера."
        : "Не удалось начать запись. Проверьте подключение микрофона.";
      mediaStream?.getTracks().forEach((track) => track.stop());
      mediaStream = null;
    }
  });
  recordStop?.addEventListener("click", () => {
    if (mediaRecorder?.state === "recording") mediaRecorder.stop();
  });
  window.addEventListener("beforeunload", () => {
    mediaStream?.getTracks().forEach((track) => track.stop());
    if (previewUrl) URL.revokeObjectURL(previewUrl);
  });
})();