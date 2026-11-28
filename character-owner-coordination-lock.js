/* Cooperative owner-wide critical-section lease for restore activation/cleanup.
 * Isolated IndexedDB database; no app wiring or deletion capability.
 */
(() => {
  "use strict";
  const DB = "pwa-studio-character-owner-coordination-v1";
  const VERSION = 1;
  const STORE = "locks";
  const fail = message => { throw new Error(message); };
  const validOwner = value => typeof value === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
  const clone = value => structuredClone(value);
  const now = () => Date.now();
  const validLockRecord = (record, ownerId) => !!record &&
    record.ownerId === ownerId &&
    Number.isSafeInteger(record.epoch) && record.epoch >= 1 &&
    Number.isFinite(record.expiresAt) && record.expiresAt >= 0 &&
    record.protocolVersion === 1 &&
    (record.token === null
      ? record.expiresAt === 0
      : typeof record.token === "string" &&
        /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(record.token) &&
        record.expiresAt > 0);

  function open() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(DB, VERSION);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE, { keyPath: "ownerId" });
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || new Error("Owner coordination database open failed."));
      request.onblocked = () => reject(new Error("Owner coordination database upgrade is blocked."));
    });
  }
  async function mutate(ownerId, action) {
    if (!validOwner(ownerId)) fail("Invalid owner identity.");
    const db = await open();
    try {
      return await new Promise((resolve, reject) => {
        const tx = db.transaction(STORE, "readwrite");
        const store = tx.objectStore(STORE);
        let value, failure;
        try { action(store, tx, result => { value = result; }, error => { failure = error; try { tx.abort(); } catch {} }); }
        catch (error) { failure = error; try { tx.abort(); } catch {} }
        tx.oncomplete = () => failure ? reject(failure) : resolve(value);
        tx.onerror = () => reject(failure || tx.error || new Error("Owner coordination transaction failed."));
        tx.onabort = () => reject(failure || tx.error || new Error("Owner coordination transaction aborted."));
      });
    } finally { db.close(); }
  }
  async function acquire(ownerId, { ttlMs = 30000 } = {}) {
    if (!Number.isInteger(ttlMs) || ttlMs < 1000 || ttlMs > 120000) fail("Owner lock duration must be 1–120 seconds.");
    return mutate(ownerId, (store, tx, done, abort) => {
      const request = store.get(ownerId);
      request.onsuccess = () => {
        const previous = request.result;
        const time = now();
        if (previous && !validLockRecord(previous, ownerId)) {
          abort(new Error("Owner lock record is malformed; refusing unsafe takeover."));
          return;
        }
        if (previous && previous.expiresAt > time) { abort(new Error("Owner critical section is already leased.")); return; }
        const epoch = (previous?.epoch || 0) + 1;
        const lease = { ownerId, token: crypto.randomUUID(), epoch, expiresAt: time + ttlMs, protocolVersion: 1 };
        store.put(lease);
        done(clone(lease));
      };
      request.onerror = () => abort(request.error || new Error("Owner lock read failed."));
    });
  }
  async function renew(lease, { ttlMs = 30000 } = {}) {
    if (!lease || !validOwner(lease.ownerId) || !Number.isInteger(ttlMs) || ttlMs < 1000 || ttlMs > 120000)
      fail("Invalid owner lock renewal.");
    return mutate(lease.ownerId, (store, tx, done, abort) => {
      const request = store.get(lease.ownerId);
      request.onsuccess = () => {
        const current = request.result;
        if (!validLockRecord(current, lease.ownerId) || !current.token ||
            current.token !== lease.token || current.epoch !== lease.epoch || current.expiresAt <= now()) {
          abort(new Error("Owner lock renewal rejected: stale or expired fencing token."));
          return;
        }
        current.expiresAt = now() + ttlMs;
        store.put(current);
        done(clone(current));
      };
      request.onerror = () => abort(request.error || new Error("Owner lock read failed."));
    });
  }
  async function release(lease) {
    if (!lease || !validOwner(lease.ownerId)) fail("Invalid owner lock release.");
    return mutate(lease.ownerId, (store, tx, done, abort) => {
      const request = store.get(lease.ownerId);
      request.onsuccess = () => {
        const current = request.result;
        if (!validLockRecord(current, lease.ownerId) || !current.token ||
            current.token !== lease.token || current.epoch !== lease.epoch || current.expiresAt <= now()) {
          abort(new Error("Owner lock release rejected: stale or malformed fencing token."));
          return;
        }
        current.token = null;
        current.expiresAt = 0;
        current.releasedAt = new Date(now()).toISOString();
        store.put(current);
        done(true);
      };
      request.onerror = () => abort(request.error || new Error("Owner lock read failed."));
    });
  }
  async function isCurrent(lease) {
    if (!lease || !validOwner(lease.ownerId)) return false;
    const db = await open();
    try {
      return await new Promise((resolve, reject) => {
        const request = db.transaction(STORE, "readonly").objectStore(STORE).get(lease.ownerId);
        request.onsuccess = () => {
          const current = request.result;
          resolve(validLockRecord(current, lease.ownerId) && !!current.token &&
            current.token === lease.token && current.epoch === lease.epoch && current.expiresAt > now());
        };
        request.onerror = () => reject(request.error || new Error("Owner lock check failed."));
      });
    } finally { db.close(); }
  }
  globalThis.PWACharacterOwnerCoordinationLock = Object.freeze({ acquire, renew, release, isCurrent });
})();
