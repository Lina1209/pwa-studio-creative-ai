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

  // Audio → Story: local audio preview + browser speech dictation + AI transformation of supplied transcript.
  const audioTabBar = document.querySelector(".audio-lab-tabs");
  const audioWorkspace = document.querySelector(".audio-lab-workspace");
  if (audioTabBar && audioWorkspace && !document.querySelector('[data-audio-tab="audio-story"]')) {
    const tab = document.createElement("button");
    tab.className = "audio-tab"; tab.type = "button"; tab.role = "tab";
    tab.id = "audio-tab-audio-story"; tab.setAttribute("aria-selected","false");
    tab.setAttribute("aria-controls","audio-panel-audio-story"); tab.dataset.audioTab = "audio-story";
    tab.innerHTML = "<span>✦</span> Аудио → История";
    audioTabBar.append(tab);
    const panel = document.createElement("div");
    panel.className = "audio-panel"; panel.id = "audio-panel-audio-story";
    panel.role = "tabpanel"; panel.setAttribute("aria-labelledby",tab.id);
    panel.dataset.audioPanel = "audio-story"; panel.hidden = true;
    panel.innerHTML = `
      <div class="audio-panel-intro"><div><div class="eyebrow">AUDIO TO CREATIVE</div><h3>Превратите звук в историю</h3><p>Загрузите запись, добавьте её расшифровку или надиктуйте текст — Studio AI поможет создать сценарий, рассказ или песню.</p></div><span class="audio-coming">Новый инструмент</span></div>
      <div class="audio-story-grid">
        <section class="audio-card-inner">
          <div class="audio-card-icon">🎧</div><h4>1. Добавьте аудио</h4>
          <label class="audio-upload-zone" for="audioStoryFile"><span>＋</span><b>Выбрать аудиофайл</b><small>MP3, WAV, M4A, OGG, WebM · до 25 МБ</small></label>
          <input class="audio-file-input" id="audioStoryFile" type="file" accept="audio/*">
          <p class="audio-live-status" id="audioStoryFileStatus" role="status">Файл остаётся на устройстве и пока используется только для прослушивания.</p>
          <audio id="audioStoryPreview" controls hidden></audio>
        </section>
        <section class="audio-card-inner">
          <div class="audio-card-icon">🗣</div><h4>2. Получите текст записи</h4>
          <p>Можно вставить уже распознанный текст или надиктовать речь с помощью распознавания браузера.</p>
          <div class="audio-record-controls"><button class="audio-record-button" id="audioStoryDictate" type="button">🎙 Начать диктовку</button><button class="audio-stop-button" id="audioStoryDictateStop" type="button" disabled>Остановить</button></div>
          <p class="audio-live-status" id="audioStoryDictateStatus" role="status">Распознавание речи работает через браузер, если он поддерживает эту функцию.</p>
        </section>
      </div>
      <div class="audio-form-card audio-story-form">
        <label for="audioStoryTranscript">Текст или описание аудио</label>
        <textarea id="audioStoryTranscript" rows="7" maxlength="12000" placeholder="Вставьте расшифровку речи, опишите мелодию и её настроение или напишите, о чём аудиозапись..."></textarea>
        <div class="audio-form-meta"><span id="audioStoryCount">0 / 12000</span><span>Текст отправится в Studio AI только после нажатия кнопки ниже.</span></div>
        <div class="audio-form-row">
          <label>Что создаём<select id="audioStoryOutput"><option value="movie">Сценарий фильма</option><option value="story">Рассказ</option><option value="lyrics">Текст песни</option></select></label>
          <label>Язык результата<select id="audioStoryLanguage"><option value="русский">Русский</option><option value="казахский">Казахский</option><option value="английский">Английский</option></select></label>
          <label>Тип исходника<select id="audioStorySource"><option value="речь / голосовая запись">Речь или голосовая запись</option><option value="песня / вокал">Песня или вокал</option><option value="инструментальная музыка">Инструментальная музыка</option><option value="свободная творческая идея">Другое / идея</option></select></label>
        </div>
        <div class="audio-record-controls"><button class="audio-record-button" id="audioStoryGenerate" type="button">✦ Создать с Studio AI</button><button class="audio-clear-button" id="audioStoryClear" type="button">Очистить текст</button></div>
        <p class="audio-live-status" id="audioStoryStatus" role="status" aria-live="polite">Важно: автоматическая расшифровка загруженного файла и анализ самой музыки пока не подключены. Для работы AI используйте распознанный текст или диктовку.</p>
      </div>
      <div class="audio-story-result" id="audioStoryResult" hidden>
        <div class="audio-panel-intro"><div><div class="eyebrow">STUDIO AI RESULT</div><h3>Ваш творческий материал</h3></div></div>
        <textarea id="audioStoryResultText" rows="12" readonly aria-label="Результат Studio AI"></textarea>
        <div class="audio-record-controls"><button class="audio-record-button" id="audioStoryCopy" type="button">⧉ Копировать</button><button class="audio-record-button" id="audioStoryToMovie" type="button">🎬 Отправить в Миникиностудию</button></div>
        <p class="audio-live-status" id="audioStoryResultStatus" role="status"></p>
      </div>`;
    audioWorkspace.append(panel);
    tab.addEventListener("click", () => {
      document.querySelectorAll("[data-audio-tab]").forEach(item => {
        const active = item.dataset.audioTab === "audio-story";
        item.classList.toggle("active", item === tab);
        item.setAttribute("aria-selected", String(item === tab));
      });
      document.querySelectorAll("[data-audio-panel]").forEach(item => {
        const active = item.dataset.audioPanel === "audio-story";
        item.hidden = !active; item.classList.toggle("active", active);
      });
    });
    const audioStoryStyle = document.createElement("style");
    audioStoryStyle.textContent = ".audio-story-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px;margin-bottom:14px}.audio-story-form{margin-top:14px}.audio-story-result{margin-top:16px;padding:18px;border:1px solid var(--line);border-radius:12px;background:#111020}.audio-story-result textarea{width:100%;padding:12px;border:1px solid var(--line);border-radius:9px;background:#0c0b18;color:#eee9fa;font:inherit;font-size:11px;line-height:1.6;resize:vertical}.audio-story-result[hidden]{display:none}.audio-story-grid audio{width:100%;margin-top:10px}@media(max-width:600px){.audio-story-grid{grid-template-columns:1fr}}";
    document.head.append(audioStoryStyle);
    const input = document.querySelector("#audioStoryFile");
    const fileStatus = document.querySelector("#audioStoryFileStatus");
    const preview = document.querySelector("#audioStoryPreview");
    const transcript = document.querySelector("#audioStoryTranscript");
    const count = document.querySelector("#audioStoryCount");
    const status = document.querySelector("#audioStoryStatus");
    const generate = document.querySelector("#audioStoryGenerate");
    const resultBox = document.querySelector("#audioStoryResult");
    const resultText = document.querySelector("#audioStoryResultText");
    let selectedFile = null, previewUrl = null, recognition = null, latestResult = "";
    let audioStoryRequestVersion = 0;
    window.addEventListener("pwa-studio-auth-changed", () => {
      audioStoryRequestVersion += 1;
      if (recognition) {
        const staleRecognition = recognition;
        recognition = null;
        try { staleRecognition.abort(); } catch {}
      }
      latestResult = "";
      resultText.value = "";
      resultBox.hidden = true;
      generate.disabled = false;
      if (dictate) dictate.disabled = !SpeechRecognition;
      if (stop) stop.disabled = true;
      if (dictateStatus) dictateStatus.textContent = "Диктовка остановлена из-за смены аккаунта.";
      status.textContent = "Аккаунт изменился. Создайте материал заново в текущем сеансе.";
    });
    input.addEventListener("change", () => {
      const file = input.files?.[0]; if (!file) return;
      if (!file.type.startsWith("audio/") || file.size > 25*1024*1024) {
        fileStatus.textContent = "Выберите аудиофайл размером до 25 МБ."; input.value = ""; selectedFile = null; return;
      }
      selectedFile = file;
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      previewUrl = URL.createObjectURL(file); preview.src = previewUrl; preview.hidden = false;
      fileStatus.textContent = "Выбран файл: " + file.name + ". Он не загружается на сервер.";
    });
    transcript.addEventListener("input",()=>count.textContent=transcript.value.length+" / 12000");
    resultText.addEventListener("input",()=>{latestResult=resultText.value;});
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const dictate = document.querySelector("#audioStoryDictate");
    const stop = document.querySelector("#audioStoryDictateStop");
    const dictateStatus = document.querySelector("#audioStoryDictateStatus");
    if (!SpeechRecognition) {
      dictate.disabled = true;
      dictateStatus.textContent = "В этом браузере нет встроенного распознавания речи. Можно вставить готовую расшифровку вручную.";
    } else {
      dictate.addEventListener("click",()=>{
        recognition = new SpeechRecognition();
        const activeRecognition = recognition;
        const recognitionVersion = audioStoryRequestVersion;
        const recognitionIsCurrent = () => recognition === activeRecognition && recognitionVersion === audioStoryRequestVersion;
        recognition.lang = document.querySelector("#audioStoryLanguage").value==="казахский"?"kk-KZ":document.querySelector("#audioStoryLanguage").value==="английский"?"en-US":"ru-RU";
        recognition.continuous = true; recognition.interimResults = true;
        const base = transcript.value.trim(); let finalText = "";
        recognition.onresult = event => {
          if (!recognitionIsCurrent()) return;
          let interim = "";
          for(let i=event.resultIndex;i<event.results.length;i++){const part=event.results[i][0].transcript;if(event.results[i].isFinal)finalText += part+" ";else interim += part;}
          transcript.value = [base,finalText,interim].filter(Boolean).join(base?" ":"");
          count.textContent=transcript.value.length+" / 12000";
        };
        recognition.onerror = event => { if (recognitionIsCurrent()) dictateStatus.textContent = "Распознавание остановлено: "+event.error+"."; };
        recognition.onend = () => {
          if (!recognitionIsCurrent()) return;
          recognition = null;
          dictate.disabled=false;stop.disabled=true;
          dictateStatus.textContent="Диктовка завершена. Проверьте распознанный текст и исправьте ошибки.";
        };
        try{recognition.start();dictate.disabled=true;stop.disabled=false;dictateStatus.textContent="Слушаю речь… Говорите в микрофон."}
        catch(error){if(recognitionIsCurrent()){recognition=null;dictate.disabled=false;stop.disabled=true;dictateStatus.textContent="Не удалось запустить микрофон: "+error.message}}
      });
      stop.addEventListener("click",()=>{if(recognition)recognition.stop()});
    }
    document.querySelector("#audioStoryClear").addEventListener("click",()=>{transcript.value="";count.textContent="0 / 12000";resultBox.hidden=true;latestResult="";});
    generate.addEventListener("click",async()=>{
      if(!transcript.value.trim()){status.textContent="Сначала добавьте расшифровку или описание аудио.";transcript.focus();return;}
      if(!window.PWAStudioAudioBridge){status.textContent="Модуль студии ещё загружается. Обновите страницу через минуту.";return;}
      generate.disabled=true;status.textContent="Studio AI создаёт материал…";
      const requestVersion = audioStoryRequestVersion;
      try{
        const generated = await window.PWAStudioAudioBridge.generate({transcript:transcript.value,outputType:document.querySelector("#audioStoryOutput").value,language:document.querySelector("#audioStoryLanguage").value,sourceKind:document.querySelector("#audioStorySource").value,fileName:selectedFile?.name||""});
        if (requestVersion !== audioStoryRequestVersion) return;
        latestResult=generated;resultText.value=latestResult;resultBox.hidden=false;status.textContent="✓ Материал создан. Проверьте его перед сохранением.";
        resultBox.scrollIntoView({behavior:"smooth",block:"start"});
      }catch(error){if(requestVersion===audioStoryRequestVersion)status.textContent="Не удалось создать материал: "+error.message}
      finally{if(requestVersion===audioStoryRequestVersion)generate.disabled=false;}
    });
    document.querySelector("#audioStoryCopy").addEventListener("click",async()=>{
      try{await navigator.clipboard.writeText(latestResult);document.querySelector("#audioStoryResultStatus").textContent="Скопировано ✓";}
      catch{resultText.focus();resultText.select();document.querySelector("#audioStoryResultStatus").textContent="Выделите текст и скопируйте вручную."}
    });
    document.querySelector("#audioStoryToMovie").addEventListener("click",()=>{
      try{
        const heading=latestResult.match(/^\s*[#*]*\s*[«"]?([^\n»"]{3,90})[»"]?/m);
        const title=(heading?.[1]||"История из аудио").replace(/[#*]/g,"").trim();
        const created=window.PWAStudioAudioBridge.createMovie({title,story:latestResult,sourceLabel:selectedFile?.name||"Аудио → История"});
        document.querySelector("#audioStoryResultStatus").textContent="✓ Проект «"+created.name+"» создан и открыт в Миникиностудии.";
      }catch(error){document.querySelector("#audioStoryResultStatus").textContent="Не удалось перенести проект: "+error.message}
    });
  }

  window.addEventListener("beforeunload", () => {
    mediaStream?.getTracks().forEach((track) => track.stop());
    if (previewUrl) URL.revokeObjectURL(previewUrl);
  });
})();