"use strict";

const readMovieTombstones = (storage, key, isUuid) => {
  let raw;
  try { raw = storage.getItem(key); }
  catch (error) { throw new Error("Не удалось прочитать очередь удалений из памяти браузера.", { cause: error }); }
  if (raw === null) return [];
  let value;
  try { value = JSON.parse(raw); }
  catch (error) { throw new Error("Очередь удалений повреждена и не может считаться пустой.", { cause: error }); }
  if (!Array.isArray(value)) throw new Error("Очередь удалений имеет неверный формат.");
  return value.filter(isUuid);
};

const api = { read: readMovieTombstones };
if (typeof module !== "undefined" && module.exports) module.exports = api;
if (typeof window !== "undefined") window.PWAMovieTombstones = api;
