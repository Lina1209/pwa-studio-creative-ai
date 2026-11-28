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

    const validateCharacterSnapshots = (record, label) => {
      if (record.characterLibrarySnapshots === undefined) return;
      const snapshots = record.characterLibrarySnapshots;
      if (!Array.isArray(snapshots) || snapshots.length > 100) {
        throw new Error("Снимки персонажей проекта «" + label + "» имеют неверный формат или превышают лимит. Сохранение заблокировано.");
      }
      const snapshotIds = new Set();
      snapshots.forEach((snapshot, snapshotIndex) => {
        const prefix = "Снимок персонажа №" + (snapshotIndex + 1) + " проекта «" + label + "»";
        if (!snapshot || typeof snapshot !== "object" || Array.isArray(snapshot) ||
            typeof snapshot.id !== "string" || !snapshot.id.trim() || snapshot.id.length > 180 ||
            typeof snapshot.name !== "string" || !snapshot.name.trim() || snapshot.name.length > 120) {
          throw new Error(prefix + " повреждён. Сохранение заблокировано.");
        }
        if (snapshotIds.has(snapshot.id)) throw new Error(prefix + " повторяется. Сохранение заблокировано.");
        snapshotIds.add(snapshot.id);
        if (snapshot.kind !== undefined && !["character", "scene"].includes(snapshot.kind)) {
          throw new Error(prefix + " имеет неизвестный тип. Сохранение заблокировано.");
        }
        if (snapshot.representation !== undefined && !["2d", "3d", "both"].includes(snapshot.representation)) {
          throw new Error(prefix + " имеет неверный формат представления. Сохранение заблокировано.");
        }
        for (const field of ["description", "voice"]) {
          const limit = field === "description" ? 5000 : 500;
          if (snapshot[field] !== undefined && (typeof snapshot[field] !== "string" || snapshot[field].length > limit)) {
            throw new Error(prefix + ": поле «" + field + "» повреждено. Сохранение заблокировано.");
          }
        }
        if (snapshot.passport !== undefined) {
          const passport = snapshot.passport;
          if (!passport || typeof passport !== "object" || Array.isArray(passport)) {
            throw new Error(prefix + ": паспорт имеет неверный формат. Сохранение заблокировано.");
          }
          for (const field of ["face", "body", "wardrobe", "palette"]) {
            if (passport[field] !== undefined && (typeof passport[field] !== "string" || passport[field].length > 1200)) {
              throw new Error(prefix + ": поле паспорта «" + field + "» повреждено. Сохранение заблокировано.");
            }
          }
        }
        const refs = snapshot.referenceImages === undefined ? [] : snapshot.referenceImages;
        if (!Array.isArray(refs) || refs.length > 100) {
          throw new Error(prefix + ": список референсов повреждён. Сохранение заблокировано.");
        }
        const refIds = new Set();
        refs.forEach((ref, refIndex) => {
          if (!ref || typeof ref !== "object" || Array.isArray(ref) ||
              typeof ref.id !== "string" || !ref.id.trim() || ref.id.length > 180 ||
              (ref.name !== undefined && (typeof ref.name !== "string" || ref.name.length > 120)) ||
              (ref.type !== undefined && (typeof ref.type !== "string" || ref.type.length > 80))) {
            throw new Error(prefix + ": референс №" + (refIndex + 1) + " повреждён. Сохранение заблокировано.");
          }
          if (refIds.has(ref.id)) throw new Error(prefix + ": обнаружен повторяющийся референс. Сохранение заблокировано.");
          refIds.add(ref.id);
        });
        if (snapshot.selectedReferenceIds !== undefined) {
          const selected = snapshot.selectedReferenceIds;
          if (!Array.isArray(selected) || selected.length > 100 ||
              selected.some(id => typeof id !== "string" || !refIds.has(id)) ||
              new Set(selected).size !== selected.length) {
            throw new Error(prefix + ": выбранные референсы не соответствуют списку изображений. Сохранение заблокировано.");
          }
        }
        if (snapshot.sceneNumbers !== undefined) {
          const scenes = snapshot.sceneNumbers;
          if (!Array.isArray(scenes) || scenes.length > 999 ||
              scenes.some(number => !Number.isInteger(number) || number < 1 || number > 999) ||
              new Set(scenes).size !== scenes.length) {
            throw new Error(prefix + ": номера сцен повреждены. Сохранение заблокировано.");
          }
        }
      });
    };
    const ids = new Set();
    for (let index = 0; index < value.length; index++) {
      const item = value[index];
      if (!item || typeof item !== "object" || Array.isArray(item) || typeof item.id !== "string" || !item.id.trim()) {
        throw new Error("В списке фильмов найдена повреждённая запись №" + (index + 1) + ". Сохранение заблокировано.");
      }
      if (ids.has(item.id)) throw new Error("В списке фильмов обнаружен повторяющийся идентификатор. Сохранение заблокировано.");
      ids.add(item.id);
      validateCharacterSnapshots(item, item.id);
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
          validateCharacterSnapshots(version.data, item.id + " · история " + (versionIndex + 1));
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
