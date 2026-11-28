/* Isolated, retry-safe Character Library media backup coordinator.
 * Metadata passports must already exist in the cloud. This module uploads only
 * local image Blobs; it never edits metadata, deletes remote assets, or activates UI.
 */
(() => {
  "use strict";
  const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  const LOCAL_REFERENCE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(-[a-z0-9_-]{8,80})?$/i;
  const MIME = new Set(["image/png", "image/jpeg", "image/webp"]);
  const MAX_BYTES = 8 * 1024 * 1024;
  const fail = message => { throw new Error(message); };
  const current = (isCurrent, ownerId) => {
    if (typeof isCurrent !== "function" || isCurrent(ownerId) !== true)
      fail("Account changed or is no longer current; media backup stopped.");
  };
  const sha256 = async blob => {
    if (!(blob instanceof Blob) || blob.size < 1 || blob.size > MAX_BYTES || !MIME.has(blob.type))
      fail("Local image is missing or outside the supported size/MIME limits.");
    if (!globalThis.crypto?.subtle) fail("SHA-256 is unavailable in this browser.");
    const digest = await crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
    return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
  };

  async function backupCharacterMedia({ ownerId, localItems, cloudByLocalId, getLocalBlob, mediaTransfer, isCurrent = () => true }) {
    if (typeof ownerId !== "string" || !UUID.test(ownerId)) fail("A valid signed-in owner ID is required.");
    if (!Array.isArray(localItems) || localItems.length > 100) fail("Local character inventory is invalid.");
    if (!(cloudByLocalId instanceof Map)) fail("Cloud character identity map is required.");
    if (typeof getLocalBlob !== "function") fail("Owner-scoped local Blob reader is required.");
    if (!mediaTransfer || typeof mediaTransfer.uploadAsset !== "function" || typeof mediaTransfer.waitForReady !== "function")
      fail("Verified cloud media transfer adapter is incomplete.");
    current(isCurrent, ownerId);

    const seenCharacters = new Set();
    const seenReferences = new Set();
    const results = [];
    let skippedWithoutLocalReferences = 0;

    for (const local of localItems) {
      current(isCurrent, ownerId);
      if (!local || typeof local.id !== "string" || !UUID.test(local.id) || seenCharacters.has(local.id))
        fail("Local character identity is invalid or duplicated.");
      seenCharacters.add(local.id);
      const cloud = cloudByLocalId.get(local.id);
      if (!cloud || typeof cloud.id !== "string" || !UUID.test(cloud.id) || cloud.source_local_id !== local.id)
        fail("Cloud passport mapping is missing or does not match the local character.");
      const refs = Array.isArray(local.referenceImages) ? local.referenceImages : [];
      if (refs.length > 6) fail("A character contains more than six local references.");
      if (!refs.length) { skippedWithoutLocalReferences++; continue; }

      const seenLocalIds = new Set();
      for (const ref of refs) {
        current(isCurrent, ownerId);
        if (!ref || typeof ref.id !== "string" || !LOCAL_REFERENCE.test(ref.id) || seenLocalIds.has(ref.id))
          fail("Local reference identity is invalid or duplicated.");
        seenLocalIds.add(ref.id);
        const pairKey = cloud.id + ":" + ref.id;
        if (seenReferences.has(pairKey)) fail("Duplicate cloud character/reference pair.");
        seenReferences.add(pairKey);
        const fileName = typeof ref.name === "string" && ref.name.trim() ? ref.name.trim().slice(0, 255) : "reference-image";
        const blob = await getLocalBlob(ref.id, ownerId);
        current(isCurrent, ownerId);
        if (!(blob instanceof Blob)) fail("A local reference Blob is missing or belongs to another owner.");
        const digest = await sha256(blob);
        current(isCurrent, ownerId);

        // The transfer adapter derives a stable idempotency key from owner,
        // cloud character, local reference ID and content digest. Retrying is safe.
        const uploaded = await mediaTransfer.uploadAsset({
          characterId: cloud.id,
          localReferenceId: ref.id,
          fileName,
          blob
        });
        current(isCurrent, ownerId);
        if (!uploaded || uploaded.characterId !== cloud.id || uploaded.localReferenceId !== ref.id ||
            typeof uploaded.assetId !== "string" || !UUID.test(uploaded.assetId) ||
            uploaded.sha256 !== digest || uploaded.sizeBytes !== blob.size || uploaded.mimeType !== blob.type)
          fail("Cloud upload acknowledgement does not match the exact local image.");

        const ready = await mediaTransfer.waitForReady({
          characterId: cloud.id,
          assetId: uploaded.assetId,
          localReferenceId: ref.id,
          expectedSha256: digest,
          expectedSizeBytes: blob.size,
          expectedMimeType: blob.type
        });
        current(isCurrent, ownerId);
        if (!ready || ready.status !== "ready" || ready.assetId !== uploaded.assetId ||
            ready.characterId !== cloud.id || ready.localReferenceId !== ref.id ||
            ready.sha256 !== digest || ready.sizeBytes !== blob.size || ready.mimeType !== blob.type)
          fail("Cloud media asset did not reach the exact verified ready state.");

        results.push(Object.freeze({
          localCharacterId: local.id,
          cloudCharacterId: cloud.id,
          localReferenceId: ref.id,
          cloudAssetId: uploaded.assetId,
          sha256: digest,
          sizeBytes: blob.size,
          mimeType: blob.type,
          status: "ready"
        }));
      }
    }
    current(isCurrent, ownerId);
    return Object.freeze({
      ownerId,
      uploadedAndVerified: results.length,
      skippedWithoutLocalReferences,
      results: Object.freeze(results)
    });
  }

  globalThis.PWACharacterMediaBackupCoordinator = Object.freeze({ backupCharacterMedia });
})();
