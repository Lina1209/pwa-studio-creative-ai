/* Durable local movie drafts. IndexedDB is an additional recovery copy; localStorage remains the synchronous compatibility cache. */
(() => {
  const DB_NAME = "pwa-studio-local-vault";
  const DB_VERSION = 1;
  const STORE = "records";
  let databasePromise;
  const openDatabase = () => {
    if (!("indexedDB" in window)) return Promise.reject(new Error("IndexedDB недоступна"));
    if (!databasePromise) databasePromise = new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE, { keyPath: "key" });
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || new Error("Не удалось открыть IndexedDB"));
      request.onblocked = () => reject(new Error("IndexedDB заблокирована другой вкладкой"));
    });
    return databasePromise;
  };
  const transaction = async (mode, action) => {
    const db = await openDatabase();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, mode);
      const store = tx.objectStore(STORE);
      let result;
      try { result = action(store); } catch (error) { reject(error); return; }
      tx.oncomplete = () => resolve(result && result.result !== undefined ? result.result : result);
      tx.onerror = () => reject(tx.error || new Error("Ошибка транзакции IndexedDB"));
      tx.onabort = () => reject(tx.error || new Error("Транзакция IndexedDB отменена"));
    });
  };
  window.PWAMovieVault = Object.freeze({
    get: key => transaction("readonly", store => store.get(key)),
    set: (key, value) => transaction("readwrite", store => store.put({ key, value, savedAt: new Date().toISOString() })),
    remove: key => transaction("readwrite", store => store.delete(key))
  });
})();