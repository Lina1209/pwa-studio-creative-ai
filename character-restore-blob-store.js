/* Owner- and operation-scoped Blob staging adapter for Character Library restore.
 * Uses the existing character image IndexedDB database/store without changing schema.
 * Staged rows are inert until a separate, fully verified metadata activation.
 */
(() => {
  "use strict";
  const DB_NAME = "pwa-studio-character-library-v1";
  const STORE = "images";
  const fail = message => { throw new Error(message); };
  const validUuid = value => typeof value === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
  const validProof = proof => proof && typeof proof === "object" &&
    /^[a-f0-9]{64}$/i.test(proof.sha256 || "") &&
    Number.isSafeInteger(proof.sizeBytes) && proof.sizeBytes > 0 &&
    ["image/png", "image/jpeg", "image/webp"].includes(proof.mimeType) &&
    Number.isInteger(proof.width) && proof.width > 0 && proof.width <= 12000 &&
    Number.isInteger(proof.height) && proof.height > 0 && proof.height <= 12000;
  const sameProof = (a, b) => a && b &&
    a.sha256 === b.sha256 && a.sizeBytes === b.sizeBytes &&
    a.mimeType === b.mimeType && a.width === b.width && a.height === b.height;

  function createCharacterRestoreBlobStore({ indexedDB: idb = globalThis.indexedDB } = {}) {
    if (!idb || typeof idb.open !== "function") fail("IndexedDB is unavailable.");
    function open() {
      return new Promise((resolve, reject) => {
        const request = idb.open(DB_NAME, 1);
        request.onupgradeneeded = () => {
          const db = request.result;
          if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE, { keyPath: "id" });
        };
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error || new Error("Character image database open failed."));
        request.onblocked = () => reject(new Error("Character image database upgrade is blocked."));
      });
    }
    async function stageBlob({ ownerId, operationId, cloudAssetId, localStagedBlobId, blob, proof }) {
      if (!validUuid(ownerId) || !validUuid(operationId) || !validUuid(cloudAssetId) || !validUuid(localStagedBlobId))
        fail("Invalid owner, operation, asset, or staged Blob identity.");
      if (!(blob instanceof Blob) || !validProof(proof) || blob.size !== proof.sizeBytes || blob.type !== proof.mimeType)
        fail("Staged Blob or its verification proof is invalid.");
      const db = await open();
      try {
        return await new Promise((resolve, reject) => {
          const tx = db.transaction(STORE, "readwrite");
          const store = tx.objectStore(STORE);
          let result = null;
          const request = store.get(localStagedBlobId);
          request.onsuccess = () => {
            const existing = request.result;
            if (existing) {
              const stage = existing.restoreStage;
              if (existing.ownerId !== ownerId || !stage ||
                  stage.operationId !== operationId || stage.cloudAssetId !== cloudAssetId ||
                  !sameProof(stage.proof, proof)) {
                tx.abort();
                return;
              }
              result = { localStagedBlobId, reused: true };
              return;
            }
            store.add({
              id: localStagedBlobId, ownerId, blob, createdAt: new Date().toISOString(),
              restoreStage: { operationId, cloudAssetId, proof: {
                sha256: proof.sha256.toLowerCase(), sizeBytes: proof.sizeBytes,
                mimeType: proof.mimeType, width: proof.width, height: proof.height
              }}
            });
            result = { localStagedBlobId, reused: false };
          };
          request.onerror = () => { try { tx.abort(); } catch {} };
          tx.oncomplete = () => resolve(result);
          tx.onerror = () => reject(tx.error || new Error("Staged Blob write failed."));
          tx.onabort = () => reject(tx.error || new Error("Staged Blob write was rejected."));
        });
      } finally { db.close(); }
    }
    async function readStagedBlob({ ownerId, operationId, cloudAssetId, localStagedBlobId }) {
      if (!validUuid(ownerId) || !validUuid(operationId) || !validUuid(cloudAssetId) || !validUuid(localStagedBlobId))
        fail("Invalid staged Blob lookup identity.");
      const db = await open();
      try {
        return await new Promise((resolve, reject) => {
          const request = db.transaction(STORE, "readonly").objectStore(STORE).get(localStagedBlobId);
          request.onsuccess = () => {
            const row = request.result, stage = row?.restoreStage;
            if (!row || row.ownerId !== ownerId || !stage ||
                stage.operationId !== operationId || stage.cloudAssetId !== cloudAssetId) {
              resolve(null);
              return;
            }
            resolve(row.blob instanceof Blob ? row.blob : null);
          };
          request.onerror = () => reject(request.error || new Error("Staged Blob read failed."));
        });
      } finally { db.close(); }
    }
    async function deleteStagedBlob({ ownerId, operationId, cloudAssetId, localStagedBlobId, proof, inspectImage, beforeDelete }) {
      if (!validUuid(ownerId) || !validUuid(operationId) || !validUuid(cloudAssetId) ||
          !validUuid(localStagedBlobId) || !validProof(proof) || typeof inspectImage !== "function" ||
          (beforeDelete !== undefined && typeof beforeDelete !== "function"))
        fail("Invalid exact staged Blob deletion identity, proof, image inspector, or pre-delete guard.");
      // Verify the actual immutable Blob bytes before opening the delete transaction.
      // The caller must hold the owner-wide coordination lock throughout this method.
      const preflight = await readStagedBlob({ ownerId, operationId, cloudAssetId, localStagedBlobId });
      if (!preflight) return "missing";
      if (preflight.size !== proof.sizeBytes || preflight.type !== proof.mimeType)
        fail("Staged Blob bytes no longer match the durable deletion proof.");
      const digest = await crypto.subtle.digest("SHA-256", await preflight.arrayBuffer());
      const actualSha = Array.from(new Uint8Array(digest), x => x.toString(16).padStart(2, "0")).join("");
      if (actualSha !== proof.sha256.toLowerCase())
        fail("Staged Blob checksum no longer matches the durable deletion proof.");
      const dimensions = await inspectImage(preflight);
      if (!dimensions || dimensions.width !== proof.width || dimensions.height !== proof.height)
        fail("Staged Blob dimensions no longer match the durable deletion proof.");
      // The owner lock may expire while bytes are hashed or image dimensions are decoded.
      // Revalidate the caller's fencing token immediately before opening the delete transaction.
      if (beforeDelete) await beforeDelete();
      const db = await open();
      try {
        return await new Promise((resolve, reject) => {
          const tx = db.transaction(STORE, "readwrite");
          const store = tx.objectStore(STORE);
          let result = "missing";
          const request = store.get(localStagedBlobId);
          request.onsuccess = () => {
            const row = request.result;
            if (!row) return;
            const stage = row.restoreStage;
            if (row.ownerId !== ownerId || !stage ||
                stage.operationId !== operationId || stage.cloudAssetId !== cloudAssetId ||
                !sameProof(stage.proof, proof)) {
              try { tx.abort(); } catch {}
              return;
            }
            store.delete(localStagedBlobId);
            result = "deleted";
          };
          request.onerror = () => { try { tx.abort(); } catch {} };
          tx.oncomplete = () => resolve(result);
          tx.onerror = () => reject(tx.error || new Error("Exact staged Blob deletion failed."));
          tx.onabort = () => reject(tx.error || new Error("Staged Blob identity mismatch; nothing was deleted."));
        });
      } finally { db.close(); }
    }
    return Object.freeze({ stageBlob, readStagedBlob, deleteStagedBlob });
  }
  globalThis.PWACharacterRestoreBlobStore = Object.freeze({ createCharacterRestoreBlobStore });
})();
