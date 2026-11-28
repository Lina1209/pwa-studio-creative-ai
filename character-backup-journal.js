/* PWA Studio Character Library backup journal.
 * Browser-only persistence primitive. This module performs NO network requests,
 * does not import characters, and never mutates canonical passports or image Blobs.
 * Load as a classic script; exposes window.PWACharacterBackupJournal.
 */
(() => {
  "use strict";

  const DB_NAME = "pwa-studio-character-backup-journal-v1";
  const DB_VERSION = 2;
  const STORE = "journals";
  const PROTOCOL_VERSION = 1;
  const STATES = new Set([
    "local_only", "reserved", "upload_pending", "object_uploaded",
    "verified", "retryable_error", "conflict", "terminal_error"
  ]);
  const NEXT = {
    local_only: new Set(["reserved", "retryable_error", "conflict", "terminal_error"]),
    reserved: new Set(["upload_pending", "retryable_error", "conflict", "terminal_error"]),
    upload_pending: new Set(["reserved", "object_uploaded", "retryable_error", "conflict", "terminal_error"]),
    object_uploaded: new Set(["upload_pending", "verified", "retryable_error", "conflict", "terminal_error"]),
    retryable_error: new Set(["reserved", "upload_pending", "retryable_error", "conflict", "terminal_error"]),
    conflict: new Set(),
    terminal_error: new Set(),
    verified: new Set()
  };

  const fail = message => { throw new Error(message); };
  const requiredString = (value, label, max = 200) => {
    if (typeof value !== "string" || !value.trim() || value.length > max) fail("Invalid " + label + ".");
    return value;
  };
  const uuid = (value, label) => {
    requiredString(value, label, 64);
    if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value)) fail("Invalid " + label + ".");
    return value.toLowerCase();
  };
  const clone = value => {
    if (typeof structuredClone === "function") return structuredClone(value);
    return JSON.parse(JSON.stringify(value));
  };
  const keyFor = (ownerId, localCharacterId) => ownerId + ":" + localCharacterId;

  function openDb() {
    if (!globalThis.indexedDB) return Promise.reject(new Error("IndexedDB is unavailable."));
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      let settled = false;
      request.onupgradeneeded = () => {
        const db = request.result;
        const store = db.objectStoreNames.contains(STORE)
          ? request.transaction.objectStore(STORE)
          : db.createObjectStore(STORE, { keyPath: "id" });
        if (!store.indexNames.contains("byOwner")) store.createIndex("byOwner", "ownerId", { unique: false });
      };
      request.onsuccess = () => {
        const db = request.result;
        // An upgrade may be unblocked after onblocked has already rejected this
        // operation. Close the late connection so it cannot pin a stale schema.
        if (settled) {
          db.close();
          return;
        }
        settled = true;
        resolve(db);
      };
      request.onerror = () => {
        if (settled) return;
        settled = true;
        reject(request.error || new Error("Could not open backup journal."));
      };
      request.onblocked = () => {
        if (settled) return;
        settled = true;
        reject(new Error("Backup journal upgrade is blocked by another tab."));
      };
    });
  }

  async function transact(mode, action) {
    const db = await openDb();
    try {
      return await new Promise((resolve, reject) => {
        const tx = db.transaction(STORE, mode);
        const store = tx.objectStore(STORE);
        let result;
        try { result = action(store, tx); }
        catch (error) { try { tx.abort(); } catch {} reject(error); return; }
        tx.oncomplete = () => resolve(result);
        tx.onerror = () => reject(tx.error || new Error("Backup journal transaction failed."));
        tx.onabort = () => reject(tx.error || new Error("Backup journal transaction aborted."));
      });
    } finally { db.close(); }
  }

  async function readRecord(id) {
    const db = await openDb();
    try {
      return await new Promise((resolve, reject) => {
        const request = db.transaction(STORE, "readonly").objectStore(STORE).get(id);
        request.onsuccess = () => resolve(request.result || null);
        request.onerror = () => reject(request.error || new Error("Could not read backup journal."));
      });
    } finally { db.close(); }
  }

  function normalizeReference(ref) {
    if (!ref || typeof ref !== "object") fail("Invalid reference descriptor.");
    const referenceId = requiredString(ref.localReferenceId, "local reference ID", 180);
    const sha256 = requiredString(ref.sha256, "reference SHA-256", 64).toLowerCase();
    if (!/^[a-f0-9]{64}$/.test(sha256)) fail("Invalid reference SHA-256.");
    const sizeBytes = Number(ref.sizeBytes);
    if (!Number.isSafeInteger(sizeBytes) || sizeBytes < 1 || sizeBytes > 8 * 1024 * 1024) fail("Invalid reference size.");
    const mimeType = requiredString(ref.mimeType, "reference MIME type", 80).toLowerCase();
    if (!["image/png", "image/jpeg", "image/webp"].includes(mimeType)) fail("Unsupported reference MIME type.");
    const fileName = requiredString(ref.fileName, "reference filename", 120);
    const idempotencyKey = requiredString(ref.idempotencyKey, "idempotency key", 180);
    return {
      localReferenceId: referenceId, sha256, sizeBytes, mimeType, fileName,
      idempotencyKey, cloudAssetId: null, state: "local_only",
      lastErrorCategory: null, lastVerifiedAt: null
    };
  }

  function assertRecord(record) {
    if (!record || record.protocolVersion !== PROTOCOL_VERSION || !Array.isArray(record.references)) fail("Invalid backup journal record.");
    const ownerId = uuid(record.ownerId, "journal owner ID");
    const localCharacterId = uuid(record.localCharacterId, "journal local character ID");
    if (record.id !== keyFor(ownerId, localCharacterId)) fail("Journal primary key does not match its owner mapping.");
    if (record.cloudCharacterId !== null) uuid(record.cloudCharacterId, "cloud character ID");
    const fingerprint = requiredString(record.passportFingerprint, "passport fingerprint", 64).toLowerCase();
    if (!/^[a-f0-9]{64}$/.test(fingerprint)) fail("Invalid passport fingerprint.");
    for (const field of ["createdAt", "updatedAt"]) {
      if (typeof record[field] !== "string" || !Number.isFinite(Date.parse(record[field]))) fail("Invalid journal timestamp.");
    }
    if (record.references.length > 6) fail("A character may have at most six references.");
    const ids = new Set();
    const keys = new Set();
    for (const ref of record.references) {
      if (!ref || typeof ref !== "object") fail("Invalid backup reference record.");
      requiredString(ref.localReferenceId, "local reference ID", 180);
      const sha = requiredString(ref.sha256, "reference SHA-256", 64).toLowerCase();
      if (!/^[a-f0-9]{64}$/.test(sha)) fail("Invalid reference SHA-256.");
      if (!Number.isSafeInteger(ref.sizeBytes) || ref.sizeBytes < 1 || ref.sizeBytes > 8 * 1024 * 1024) fail("Invalid reference size.");
      if (!["image/png", "image/jpeg", "image/webp"].includes(ref.mimeType)) fail("Unsupported reference MIME type.");
      requiredString(ref.fileName, "reference filename", 120);
      requiredString(ref.idempotencyKey, "idempotency key", 180);
      if (ref.cloudAssetId !== null) uuid(ref.cloudAssetId, "cloud asset ID");
      if (!STATES.has(ref.state)) fail("Unknown backup reference state.");
      if (ref.lastErrorCategory !== null) requiredString(ref.lastErrorCategory, "error category", 80);
      if (ref.lastVerifiedAt !== null && (typeof ref.lastVerifiedAt !== "string" || !Number.isFinite(Date.parse(ref.lastVerifiedAt)))) fail("Invalid reference verification timestamp.");
      if (ref.state === "verified" && (!ref.cloudAssetId || !ref.lastVerifiedAt)) fail("Verified reference is missing its cloud proof.");
      if (ids.has(ref.localReferenceId) || keys.has(ref.idempotencyKey)) fail("Duplicate reference identity or idempotency key.");
      ids.add(ref.localReferenceId); keys.add(ref.idempotencyKey);
    }
    return record;
  }

  async function create(input) {
    if (!input || typeof input !== "object") fail("Journal input is required.");
    const ownerId = uuid(input.ownerId, "owner ID");
    const localCharacterId = uuid(input.localCharacterId, "local character ID");
    if (!Array.isArray(input.references) || input.references.length > 6) fail("Invalid reference list.");
    const references = input.references.map(normalizeReference);
    const now = new Date().toISOString();
    const passportFingerprint = requiredString(input.passportFingerprint, "passport fingerprint", 64).toLowerCase();
    if (!/^[a-f0-9]{64}$/.test(passportFingerprint)) fail("Invalid passport fingerprint.");
    const record = {
      id: keyFor(ownerId, localCharacterId), protocolVersion: PROTOCOL_VERSION,
      ownerId, localCharacterId, cloudCharacterId: null,
      passportFingerprint,
      references, createdAt: now, updatedAt: now
    };
    assertRecord(record);
    await transact("readwrite", store => store.add(record));
    const readBack = await readRecord(record.id);
    if (!readBack || JSON.stringify(readBack) !== JSON.stringify(record)) fail("Backup journal read-back verification failed.");
    return clone(readBack);
  }

  async function get(ownerIdValue, localCharacterIdValue) {
    const ownerId = uuid(ownerIdValue, "owner ID");
    const localCharacterId = uuid(localCharacterIdValue, "local character ID");
    const record = await readRecord(keyFor(ownerId, localCharacterId));
    if (!record) return null;
    assertRecord(record);
    if (record.ownerId !== ownerId || record.localCharacterId !== localCharacterId) fail("Backup journal owner boundary mismatch.");
    return clone(record);
  }

  const encodeCursor = value => {
    const bytes = new TextEncoder().encode(JSON.stringify(value));
    let binary = "";
    bytes.forEach(byte => { binary += String.fromCharCode(byte); });
    return btoa(binary).replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
  };
  const decodeCursor = value => {
    if (typeof value !== "string" || value.length > 512 || !/^[A-Za-z0-9_-]+$/.test(value)) fail("Invalid journal cursor.");
    const binary = atob(value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - value.length % 4) % 4));
    const bytes = Uint8Array.from(binary, char => char.charCodeAt(0));
    const parsed = JSON.parse(new TextDecoder().decode(bytes));
    if (!parsed || parsed.v !== 1 || typeof parsed.ownerId !== "string" || typeof parsed.lastId !== "string") fail("Invalid journal cursor.");
    return parsed;
  };

  async function listPage(ownerIdValue, options = {}) {
    const ownerId = uuid(ownerIdValue, "owner ID");
    const limit = options.limit === undefined ? 50 : options.limit;
    if (!Number.isInteger(limit) || limit < 1 || limit > 100) fail("Journal page limit must be between 1 and 100.");
    let lastId = "";
    if (options.cursor) {
      const decoded = decodeCursor(options.cursor);
      if (decoded.ownerId !== ownerId || !decoded.lastId.startsWith(ownerId + ":")) fail("Journal cursor owner boundary mismatch.");
      lastId = decoded.lastId;
    }
    const db = await openDb();
    try {
      return await new Promise((resolve, reject) => {
        const tx = db.transaction(STORE, "readonly");
        const index = tx.objectStore(STORE).index("byOwner");
        const request = index.openCursor(IDBKeyRange.only(ownerId), "next");
        const rows = [];
        let hasMore = false;
        request.onsuccess = () => {
          try {
            const cursor = request.result;
            if (!cursor) {
              rows.forEach(assertRecord);
              resolve({
                items: clone(rows),
                nextCursor: hasMore && rows.length
                  ? encodeCursor({v:1, ownerId, lastId:rows[rows.length - 1].id})
                  : null
              });
              return;
            }
            if (cursor.primaryKey > lastId) {
              if (rows.length === limit) {
                hasMore = true;
                rows.forEach(assertRecord);
                resolve({
                  items: clone(rows),
                  nextCursor: encodeCursor({v:1, ownerId, lastId:rows[rows.length - 1].id})
                });
                return;
              }
              const row = cursor.value;
              if (row.ownerId !== ownerId || row.id !== keyFor(ownerId, row.localCharacterId)) fail("Backup journal owner boundary mismatch.");
              rows.push(row);
            }
            cursor.continue();
          } catch (error) { reject(error); }
        };
        request.onerror = () => reject(request.error || new Error("Could not list backup journals."));
      });
    } finally { db.close(); }
  }

  // Compatibility helper: returns the first bounded page only.
  async function list(ownerIdValue) {
    return (await listPage(ownerIdValue, {limit:100})).items;
  }

  async function setCloudCharacter(ownerIdValue, localCharacterIdValue, cloudCharacterIdValue) {
    const ownerId = uuid(ownerIdValue, "owner ID");
    const localCharacterId = uuid(localCharacterIdValue, "local character ID");
    const cloudCharacterId = uuid(cloudCharacterIdValue, "cloud character ID");
    const id = keyFor(ownerId, localCharacterId);
    await transact("readwrite", store => {
      const request = store.get(id);
      request.onsuccess = () => {
        const row = request.result;
        if (!row) return;
        if (row.cloudCharacterId && row.cloudCharacterId !== cloudCharacterId) { try { request.transaction.abort(); } catch {} return; }
        row.cloudCharacterId = cloudCharacterId;
        row.updatedAt = new Date().toISOString();
        store.put(row);
      };
    });
    const row = await readRecord(id);
    if (!row || row.cloudCharacterId !== cloudCharacterId) fail("Cloud character mapping was not persisted.");
    return clone(row);
  }

  async function transition(input) {
    const ownerId = uuid(input?.ownerId, "owner ID");
    const localCharacterId = uuid(input?.localCharacterId, "local character ID");
    const localReferenceId = requiredString(input?.localReferenceId, "local reference ID", 180);
    const nextState = requiredString(input?.state, "next state", 40);
    if (!STATES.has(nextState)) fail("Unknown backup reference state.");
    const id = keyFor(ownerId, localCharacterId);
    await transact("readwrite", store => {
      const request = store.get(id);
      request.onsuccess = () => {
        const row = request.result;
        if (!row || row.ownerId !== ownerId) { try { request.transaction.abort(); } catch {} return; }
        const ref = row.references.find(item => item.localReferenceId === localReferenceId);
        if (!ref) { try { request.transaction.abort(); } catch {} return; }
        if (ref.state !== nextState && !NEXT[ref.state].has(nextState)) { try { request.transaction.abort(); } catch {} return; }
        if (input.cloudAssetId) {
          const assetId = uuid(input.cloudAssetId, "cloud asset ID");
          if (ref.cloudAssetId && ref.cloudAssetId !== assetId) { try { request.transaction.abort(); } catch {} return; }
          ref.cloudAssetId = assetId;
        }
        if (nextState === "verified" && !ref.cloudAssetId) { try { request.transaction.abort(); } catch {} return; }
        ref.state = nextState;
        ref.lastErrorCategory = input.errorCategory ? requiredString(input.errorCategory, "error category", 80) : null;
        ref.lastVerifiedAt = nextState === "verified" ? new Date().toISOString() : null;
        row.updatedAt = new Date().toISOString();
        store.put(row);
      };
    });
    const row = await readRecord(id);
    const ref = row?.references.find(item => item.localReferenceId === localReferenceId);
    if (!ref || ref.state !== nextState) fail("Backup reference transition was not persisted.");
    return clone(row);
  }

  function completionStatus(record) {
    assertRecord(record);
    const complete = !!record.cloudCharacterId &&
      record.references.every(ref => ref.state === "verified" && !!ref.cloudAssetId && !!ref.lastVerifiedAt);
    return { complete, verifiedReferences: record.references.filter(ref => ref.state === "verified").length, totalReferences: record.references.length };
  }

  globalThis.PWACharacterBackupJournal = Object.freeze({
    protocolVersion: PROTOCOL_VERSION, create, get, list, listPage, setCloudCharacter,
    transition, completionStatus
  });
})();
