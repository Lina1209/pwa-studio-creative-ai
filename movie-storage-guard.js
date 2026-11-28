(() => {
  "use strict";
  const ALLOWED_STAGES = new Set(["story", "characters", "voices", "edit"]);
  const TEXT_FIELDS = ["name", "idea", "story", "storyboard", "characters", "voices", "edit", "genre", "frame", "versionLabel"];
  const parse = raw => {
    if (raw == null || raw === "") return [];
    let value;
    try { value = JSON.parse(raw); }
    catch (_) { throw new Error("Локальные данные фильмов повреждены (ошибка JSON). Сохранение заблокировано, исходные данные не изменены."); }
    if (!Array.isArray(value)) throw new Error("Хранилище фильмов имеет неверный формат. Сохранение заблокировано.");
    const ids = new Set();
    for (let index = 0; index < value.length; index++) {
      const item = value[index];
      if (!item || typeof item !== "object" || Array.isArray(item) || typeof item.id !== "string" || !item.id.trim()) {
        throw new Error("В списке фильмов найдена повреждённая запись №" + (index + 1) + ". Сохранение заблокировано.");
      }
      if (ids.has(item.id)) throw new Error("В списке фильмов обнаружен повторяющийся идентификатор. Сохранение заблокировано.");
      ids.add(item.id);
      for (const field of TEXT_FIELDS) {
        if (item[field] !== undefined && item[field] !== null && typeof item[field] !== "string") {
          throw new Error("Поле «" + field + "» в записи «" + item.id + "» имеет неверный формат. Сохранение заблокировано.");
        }
      }
      if (item.completedSteps !== undefined &&
          (!Array.isArray(item.completedSteps) || item.completedSteps.some(step => typeof step !== "string" || !ALLOWED_STAGES.has(step)))) {
        throw new Error("Этапы проекта «" + item.id + "» повреждены. Сохранение заблокировано.");
      }
      if (item.versions !== undefined) {
        if (!Array.isArray(item.versions) || item.versions.length > 20) {
          throw new Error("История версий проекта «" + item.id + "» повреждена. Сохранение заблокировано.");
        }
        item.versions.forEach((version, versionIndex) => {
          if (!version || typeof version !== "object" || Array.isArray(version) ||
              typeof version.savedAt !== "string" || !Number.isFinite(Date.parse(version.savedAt)) ||
              !version.data || typeof version.data !== "object" || Array.isArray(version.data) ||
              version.data.id !== item.id) {
            throw new Error("Запись истории №" + (versionIndex + 1) + " проекта «" + item.id + "» повреждена. Сохранение заблокировано.");
          }
          for (const field of TEXT_FIELDS) {
            if (version.data[field] !== undefined && version.data[field] !== null && typeof version.data[field] !== "string") {
              throw new Error("История проекта «" + item.id + "» содержит некорректное поле «" + field + "». Сохранение заблокировано.");
            }
          }
          if (version.data.completedSteps !== undefined &&
              (!Array.isArray(version.data.completedSteps) || version.data.completedSteps.some(step => typeof step !== "string" || !ALLOWED_STAGES.has(step)))) {
            throw new Error("Этапы в истории проекта «" + item.id + "» повреждены. Сохранение заблокировано.");
          }
        });
      }
    }
    return value;
  };
  window.PWAStudioMovieStorageGuard = Object.freeze({ parse });
})();
