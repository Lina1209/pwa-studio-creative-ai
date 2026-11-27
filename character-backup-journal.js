/* PWA Studio Character Library backup journal.
 * Browser-only persistence primitive. This module performs NO network requests,
 * does not import characters, and never mutates canonical passports or image Blobs.
 * Load as a classic script; exposes window.PWACharacterBackupJournal.
 */
(() => {
  "use strict";

  const DB_NAME = "pwa-studio-character-backup-journal-v1";
  const DB_VERSION = 1;
  const STORE = "journals";
  const PROTOCOL_VERSION = 1;
  const STATES = new Set([
    "local_only", "reserved", "upload_pending", "object_uploaded",
    "verified", "retryable_error", "conflict", "terminal_error"
  ]);
  const NEXT = {
    local_only: new Set(["reserved", "retryable_error", "conflict", "terminal_error"]),
    reserved: new Set(["upload_pending", "object_uploaded", "retryable_error", "conflict", "terminal_error"]),
    upload_pending: new Set(["reserved", "object_uploaded", "retryable_error", "conflict", "terminal_error"]),
    object_uploaded: new Set(["upload_pending", "verified", "retryable_error", "conflict", "terminal_error"]),
    retryable_error: new Set(["reserved", "upload_pending", "object_uploaded", "retryable_error", "conflict", "terminal_error"]),
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
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE, { keyPath: "id" });
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || new Error("Could not open backup journal."));
      request.onblocked = () => reject(new Error("Backup journal upgrade is blocked by another tab."));
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
    if (!record || record.protocolVersion !== PROTOCOL_VERSION || !record.ownerId || !record.localCharacterId || !Array.isArray(record.references)) fail("Invalid backup journal record.");
    if (record.references.length > 6) fail("A character may have at most six references.");
    const ids = new Set();
    const keys = new Set();
    for (const ref of record.references) {
      if (!STATES.has(ref.state)) fail("Unknown backup reference state.");
      if (ids.has(ref.localReferenceId) || keys.has(ref.idempotencyKey)) fail("Duplicate reference identity or idempotency key.");
      ids.add(ref.localReferenceId); keys.add(ref.idempotencyKey);
    }
  }

  async function create(input) {
    if (!input || typeof input !== "object") fail("Journal input is required.");
    const ownerId = uuid(input.ownerId, "owner ID");
    const localCharacterId = uuid(input.localCharacterId, "local character ID");
    if (!Array.isArray(input.references) || input.references.length > 6) fail("Invalid reference list.");
    const references = input.references.map(normalizeReference);
    const now = new Date().toISOString();
    const record = {
      id: keyFor(ownerId, localCharacterId), protocolVersion: PROTOCOL_VERSION,
      ownerId, localCharacterId, cloudCharacterId: null,
      passportFingerprint: requiredString(input.passportFingerprint, "passport fingerprint", 64),
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

  async function list(ownerIdValue) {
    const ownerId = uuid(ownerIdValue, "owner ID");
    const db = await openDb();
    try {
      return await new Promise((resolve, reject) => {
        const request = db.transaction(STORE, "readonly").objectStore(STORE).getAll();
        request.onsuccess = () => {
          try {
            const rows = request.result.filter(row => row.ownerId === ownerId);
            rows.forEach(assertRecord);
            resolve(clone(rows));
          } catch (error) { reject(error); }
        };
        request.onerror = () => reject(request.error || new Error("Could not list backup journals."));
      });
    } finally { db.close(); }
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
    protocolVersion: PROTOCOL_VERSION, create, get, list, setCloudCharacter,
    transition, completionStatus
  });
})();
