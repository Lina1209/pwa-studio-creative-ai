/* Owner-bound localStorage adapter for Character Library metadata restore.
 * No UI wiring: callers must authenticate and provide an account-current fence.
 */
(() => {
  "use strict";
  const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  const fail = message => { throw new Error(message); };

  function createCharacterLocalStorageAdapter({storage, ownerId, isCurrent = () => true}) {
    if (!storage || typeof storage.getItem !== "function" || typeof storage.setItem !== "function") fail("A localStorage-compatible adapter is required.");
    if (typeof ownerId !== "string" || !UUID.test(ownerId)) fail("An authenticated owner ID is required.");
    if (typeof isCurrent !== "function" || !isCurrent()) fail("Account is not current.");
    const key = "pwa-studio-character-library-v1:" + ownerId;
    const assertCurrent = () => { if (!isCurrent()) fail("Account changed during local library access."); };

    const readLocalItems = requestedOwnerId => {
      assertCurrent();
      if (requestedOwnerId !== ownerId) fail("Local library owner mismatch.");
      const raw = storage.getItem(key);
      if (raw === null || raw === "") return [];
      let parsed;
      try { parsed = JSON.parse(raw); } catch { fail("Local character library JSON is corrupted; refusing restore."); }
      if (!Array.isArray(parsed) || parsed.length > 100) fail("Local character library shape or size is invalid; refusing restore.");
      const seen = new Set();
      for (const item of parsed) {
        if (!item || typeof item !== "object" || Array.isArray(item) ||
            typeof item.id !== "string" || !item.id.trim() ||
            typeof item.name !== "string" || seen.has(item.id)) {
          fail("Local character library contains an invalid or duplicate record; refusing restore.");
        }
        seen.add(item.id);
      }
      assertCurrent();
      return parsed;
    };

    const writeLocalItems = (requestedOwnerId, items) => {
      assertCurrent();
      if (requestedOwnerId !== ownerId) fail("Local library owner mismatch.");
      if (!Array.isArray(items) || items.length > 100) fail("Local restore payload exceeds the supported limit.");
      const seen = new Set();
      for (const item of items) {
        if (!item || typeof item !== "object" || Array.isArray(item) ||
            typeof item.id !== "string" || !item.id.trim() ||
            typeof item.name !== "string" || seen.has(item.id)) {
          fail("Local restore payload contains an invalid or duplicate record.");
        }
        seen.add(item.id);
      }
      const serialized = JSON.stringify(items);
      // localStorage.setItem replaces one key atomically or throws (e.g. quota).
      storage.setItem(key, serialized);
      assertCurrent();
    };

    return Object.freeze({readLocalItems, writeLocalItems, storageKey:key});
  }

  globalThis.PWACharacterLocalStorageAdapter = Object.freeze({createCharacterLocalStorageAdapter});
})();
