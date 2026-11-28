/* PWA Studio: safe cloud-to-local Character Library restore planner.
 * This module is deliberately side-effect free: it performs no storage writes,
 * no image downloads, and no UI activation. The caller must review and commit
 * the complete plan only after all pages validate and the account is unchanged.
 */
(() => {
  "use strict";

  const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  const LOCAL_REFERENCE_KEY = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(-[a-z0-9_-]{8,80})?$/;
  const MAX_PAGES = 100;
  const MAX_ITEMS = 10000;
  const MAX_PAGE_SIZE = 100;
  // Only plans produced by this module instance may cross the commit boundary.
  // A caller-created object must never be able to forge a "complete" plan.
  const issuedPlans = new WeakSet();

  const fail = message => { throw new Error(message); };
  const isUuid = value => typeof value === "string" && UUID.test(value);
  const text = (value, max, label) => {
    if (typeof value !== "string" || value.length > max) fail("Invalid " + label + ".");
    return value;
  };
  const optionalText = (value, max, label) =>
    value === undefined || value === null ? "" : text(value, max, label);
  const deepFreeze = value => {
    if (value && typeof value === "object" && !Object.isFrozen(value)) {
      Object.values(value).forEach(deepFreeze);
      Object.freeze(value);
    }
    return value;
  };
  const canonical = value => JSON.stringify(value, (key, item) => {
    if (item && typeof item === "object" && !Array.isArray(item)) {
      return Object.keys(item).sort().reduce((out, name) => (out[name] = item[name], out), {});
    }
    return item;
  });
  const safeReferenceData = value => {
    if (!value || typeof value !== "object" || Array.isArray(value)) fail("Cloud passport reference data is invalid.");
    if (value.passport !== undefined && (!value.passport || typeof value.passport !== "object" || Array.isArray(value.passport))) fail("Cloud passport fields are invalid.");
    const passport = value.passport || {};
    const refs = value.referenceImages === undefined ? [] : value.referenceImages;
    if (!Array.isArray(refs) || refs.length > 6) fail("Cloud passport reference manifest is invalid.");
    const manifest = refs.map(ref => {
      if (!ref || typeof ref !== "object" || Array.isArray(ref) || typeof ref.id !== "string" || !LOCAL_REFERENCE_KEY.test(ref.id)) fail("Cloud reference descriptor is invalid.");
      return {
        id: text(ref.id, 180, "cloud reference ID"),
        name: optionalText(ref.name, 120, "cloud reference name"),
        type: optionalText(ref.type, 80, "cloud reference type")
      };
    });
    return {
      kind: ["character", "scene"].includes(value.kind) ? value.kind : fail("Cloud passport kind is invalid."),
      representation: ["2d", "3d", "both"].includes(value.representation) ? value.representation : fail("Cloud passport representation is invalid."),
      voice: optionalText(value.voice, 500, "character voice"),
      passport: {
        face: optionalText(passport.face, 1200, "passport face"),
        body: optionalText(passport.body, 1200, "passport body"),
        wardrobe: optionalText(passport.wardrobe, 1200, "passport wardrobe"),
        palette: optionalText(passport.palette, 1200, "passport palette")
      },
      referenceManifest: manifest
    };
  };
  const localProjection = local => ({
    kind: local.kind === "scene" ? "scene" : "character",
    representation: ["2d", "3d", "both"].includes(local.representation) ? local.representation : "2d",
    voice: String(local.voice || "").slice(0, 500),
    passport: {
      face: String(local.passport?.face || "").slice(0, 1200),
      body: String(local.passport?.body || "").slice(0, 1200),
      wardrobe: String(local.passport?.wardrobe || "").slice(0, 1200),
      palette: String(local.passport?.palette || "").slice(0, 1200)
    },
    referenceManifest: (Array.isArray(local.referenceImages) && local.referenceImages.length ? local.referenceImages : (Array.isArray(local.cloudBackup?.referenceManifest) ? local.cloudBackup.referenceManifest : [])).slice(0, 6).map(ref => ({
      id: String(ref.id || "").slice(0, 180),
      name: String(ref.name || "").slice(0, 120),
      type: String(ref.type || "").slice(0, 80)
    }))
  });

  async function planRestore({ownerId, fetchPage, fetchReferences, existingLocalItems, isCurrent = () => true}) {
    if (!isUuid(ownerId)) fail("A valid authenticated owner ID is required.");
    if (typeof fetchPage !== "function") fail("A cloud page loader is required.");
    if (!Array.isArray(existingLocalItems) || existingLocalItems.length > 100) fail("The local library is invalid or exceeds its supported limit.");
    let localSnapshot;
    try { localSnapshot = JSON.parse(JSON.stringify(existingLocalItems)); }
    catch { fail("The local library could not be snapshotted safely."); }
    const localById = new Map();
    const localByCloudId = new Map();
    for (const item of localSnapshot) {
      if (!item || !isUuid(item.id) || typeof item.name !== "string" || localById.has(item.id)) fail("Local library contains an invalid or duplicate character ID.");
      localById.set(item.id, item);
      const mappedCloudId = item.cloudBackup?.characterId;
      if (mappedCloudId !== undefined && mappedCloudId !== null) {
        if (!isUuid(mappedCloudId) || localByCloudId.has(mappedCloudId)) fail("Local library contains an invalid or duplicate cloud character mapping.");
        localByCloudId.set(mappedCloudId, item);
      }
    }

    const cloudRows = [];
    const cloudIds = new Set();
    const localIds = new Set();
    let cursor = null;
    let pagesRead = 0;
    do {
      if (!isCurrent()) fail("Account changed during cloud restore planning.");
      const page = await fetchPage(cursor);
      if (!isCurrent()) fail("Account changed during cloud restore planning.");
      if (!page || !Array.isArray(page.items) || !(page.next_cursor === null || typeof page.next_cursor === "string")) {
        fail("Cloud API returned an incomplete page.");
      }
      if (page.items.length > MAX_PAGE_SIZE) fail("Cloud API exceeded the page-size limit.");
      for (const row of page.items) {
        if (!row || !isUuid(row.id) || !isUuid(row.source_local_id) || !Number.isInteger(row.version) || row.version < 1) {
          fail("Cloud passport identity or version is invalid.");
        }
        if (typeof row.name !== "string" || !row.name.trim() || row.name.length > 120) fail("Cloud passport name is invalid.");
        if (row.description !== null && row.description !== undefined && (typeof row.description !== "string" || row.description.length > 5000)) fail("Cloud passport description is invalid.");
        if (!row.created_at || !Number.isFinite(Date.parse(row.created_at))) fail("Cloud passport timestamp is invalid.");
        if (cloudIds.has(row.id) || localIds.has(row.source_local_id)) fail("Cloud library contains duplicate identity mappings.");
        cloudIds.add(row.id);
        localIds.add(row.source_local_id);
        cloudRows.push(row);
        if (cloudRows.length > MAX_ITEMS) fail("Cloud library exceeds the safe restore planning limit.");
      }
      cursor = page.next_cursor;
      pagesRead += 1;
      if (pagesRead > MAX_PAGES) fail("Cloud restore exceeded the maximum page count.");
    } while (cursor);

    if (!isCurrent()) fail("Account changed before cloud restore planning completed.");

    // Resolve every passport reference through the server's explicit,
    // owner-scoped local_reference_id -> media asset catalog. Never infer
    // identity from filenames, order, MIME, dimensions, or image similarity.
    const cloudDataById = new Map(cloudRows.map(row => [row.id, safeReferenceData(row.reference_data || {})]));
    const rowsWithReferences = cloudRows.filter(row => cloudDataById.get(row.id).referenceManifest.length);
    const referenceAssetsByCharacter = new Map();
    const seenCloudAssetIds = new Set();
    if (rowsWithReferences.length) {
      if (typeof fetchReferences !== "function") fail("A cloud reference asset loader is required for passports with images.");
      for (let offset = 0; offset < rowsWithReferences.length; offset += 100) {
        if (!isCurrent()) fail("Account changed during cloud reference mapping.");
        const batch = rowsWithReferences.slice(offset, offset + 100);
        const ids = batch.map(row => row.id);
        const assets = await fetchReferences(ids);
        if (!isCurrent()) fail("Account changed during cloud reference mapping.");
        if (!Array.isArray(assets) || assets.length > 600) fail("Cloud reference catalog is invalid or exceeds its safe limit.");
        const requested = new Set(ids);
        for (const asset of assets) {
          if (!asset || !isUuid(asset.id) || !isUuid(asset.character_id) || !requested.has(asset.character_id)) {
            fail("Cloud reference asset identity is invalid or outside the requested character set.");
          }
          if (seenCloudAssetIds.has(asset.id)) fail("Cloud reference catalog contains duplicate asset IDs.");
          seenCloudAssetIds.add(asset.id);
          if (asset.local_reference_id === null || asset.local_reference_id === undefined) continue;
          if (typeof asset.local_reference_id !== "string" || !LOCAL_REFERENCE_KEY.test(asset.local_reference_id)) {
            fail("Cloud reference asset has an invalid local reference mapping.");
          }
          if (!["pending_upload", "object_uploaded", "ready", "upload_failed", "cleanup_pending", "deleted"].includes(asset.status)) {
            fail("Cloud reference asset status is invalid.");
          }
          if (typeof asset.file_name !== "string" || !asset.file_name.trim() || asset.file_name.length > 255 ||
              !["image/png", "image/jpeg", "image/webp"].includes(asset.file_type) ||
              !Number.isSafeInteger(asset.size_bytes) || asset.size_bytes < 1 || asset.size_bytes > 8 * 1024 * 1024 ||
              typeof asset.content_sha256 !== "string" || !/^[0-9a-f]{64}$/.test(asset.content_sha256) ||
              !Number.isInteger(asset.width) || asset.width < 1 || asset.width > 8192 ||
              !Number.isInteger(asset.height) || asset.height < 1 || asset.height > 8192) {
            fail("Cloud reference asset integrity metadata is invalid.");
          }
          let byReference = referenceAssetsByCharacter.get(asset.character_id);
          if (!byReference) referenceAssetsByCharacter.set(asset.character_id, byReference = new Map());
          if (byReference.has(asset.local_reference_id)) fail("Cloud reference catalog contains duplicate local reference mappings.");
          byReference.set(asset.local_reference_id, asset);
        }
      }
    }

    const mappedManifestByCharacter = new Map();
    for (const row of rowsWithReferences) {
      const descriptors = cloudDataById.get(row.id).referenceManifest;
      const byReference = referenceAssetsByCharacter.get(row.id) || new Map();
      const mapped = descriptors.map(reference => {
        const asset = byReference.get(reference.id);
        if (!asset) fail("A cloud passport reference has no explicit media asset mapping.");
        if (asset.status !== "ready") fail("A mapped cloud reference asset is not ready for restore.");
        if (reference.type && reference.type !== asset.file_type) fail("Cloud reference MIME type does not match its passport descriptor.");
        return {
          ...reference,
          name: reference.name || asset.file_name.slice(0, 120),
          type: asset.file_type,
          characterId: row.id,
          sourceLocalId: row.source_local_id,
          localReferenceId: reference.id,
          cloudAssetId: asset.id,
          expectedSha256: asset.content_sha256,
          expectedSizeBytes: asset.size_bytes,
          expectedMimeType: asset.file_type,
          width: asset.width,
          height: asset.height
        };
      });
      if (byReference.size !== mapped.length) fail("Cloud reference catalog contains assets absent from the character passport.");
      mappedManifestByCharacter.set(row.id, deepFreeze(mapped));
    }

    const proposedItems = [];
    const unchanged = [];
    const conflicts = [];
    for (const row of cloudRows) {
      const data = cloudDataById.get(row.id);
      const existing = localById.get(row.source_local_id);
      const mappedLocal = localByCloudId.get(row.id);
      if (mappedLocal && mappedLocal.id !== row.source_local_id) {
        conflicts.push({localId:mappedLocal.id, cloudId:row.id, reason:"cloud_character_already_mapped_to_another_local_id"});
        continue;
      }
      if (!existing) {
        proposedItems.push({
          id: row.source_local_id,
          name: row.name,
          description: row.description || "",
          kind: data.kind,
          representation: data.representation,
          voice: data.voice,
          passport: data.passport,
          // Reference files are not present in the metadata API. Never create
          // broken local image references; retain a manifest for later recovery.
          referenceImages: [],
          createdAt: row.created_at,
          updatedAt: row.created_at,
          cloudBackup: {
            characterId: row.id,
            version: row.version,
            referenceManifest: mappedManifestByCharacter.get(row.id) || []
          }
        });
        continue;
      }
      const same = existing.name === row.name &&
        String(existing.description || "") === String(row.description || "") &&
        canonical(localProjection(existing)) === canonical(data);
      const knownCloudId = existing.cloudBackup?.characterId;
      if (knownCloudId !== row.id) {
        conflicts.push({
          localId: row.source_local_id,
          cloudId: row.id,
          reason: knownCloudId ? "local_cloud_identity_mismatch" : "local_record_missing_cloud_identity_binding"
        });
      } else if (same) {
        unchanged.push({localId: row.source_local_id, cloudId: row.id, version: row.version});
      } else {
        conflicts.push({localId: row.source_local_id, cloudId: row.id, reason: "local_and_cloud_content_differ"});
      }
    }
    if (!isCurrent()) fail("Account changed before cloud restore planning completed.");
    const plan = Object.freeze({
      complete: true,
      ownerId,
      baseLocalFingerprint: canonical(localSnapshot),
      pagesRead,
      cloudCount: cloudRows.length,
      proposedItems: deepFreeze(proposedItems),
      unchanged: deepFreeze(unchanged),
      conflicts: deepFreeze(conflicts)
    });
    issuedPlans.add(plan);
    return plan;
  }

  function selectRestorePlan({ownerId, plan, selectedCloudIds}) {
    if (!isUuid(ownerId) || !plan || !issuedPlans.has(plan) || plan.ownerId !== ownerId || plan.complete !== true) fail("Restore selection requires a complete plan for this owner.");
    if (!Array.isArray(selectedCloudIds) || selectedCloudIds.length < 1 || selectedCloudIds.length > 100) fail("Select between 1 and 100 cloud characters.");
    const selected = new Set();
    for (const id of selectedCloudIds) {
      if (!isUuid(id) || selected.has(id)) fail("Restore selection contains an invalid or duplicate cloud character.");
      selected.add(id);
    }
    const available = new Set([
      ...plan.proposedItems.map(x => x.cloudBackup.characterId),
      ...plan.unchanged.map(x => x.cloudId),
      ...plan.conflicts.map(x => x.cloudId)
    ]);
    for (const id of selected) if (!available.has(id)) fail("Restore selection contains a character outside the reviewed cloud snapshot.");
    const selectedPlan = Object.freeze({
      complete: true, ownerId, baseLocalFingerprint: plan.baseLocalFingerprint,
      pagesRead: plan.pagesRead, cloudCount: selected.size,
      selectedCloudIds: Object.freeze([...selected]),
      proposedItems: deepFreeze(plan.proposedItems.filter(x => selected.has(x.cloudBackup.characterId))),
      unchanged: deepFreeze(plan.unchanged.filter(x => selected.has(x.cloudId))),
      conflicts: deepFreeze(plan.conflicts.filter(x => selected.has(x.cloudId)))
    });
    issuedPlans.add(selectedPlan);
    return selectedPlan;
  }

  function applyRestorePlan({ownerId, plan, readLocalItems, writeLocalItems, isCurrent = () => true}) {
    if (!isUuid(ownerId) || !plan || !issuedPlans.has(plan) || plan.complete !== true || plan.ownerId !== ownerId) fail("Restore plan owner or completion proof is invalid.");
    if (typeof readLocalItems !== "function" || typeof writeLocalItems !== "function") fail("Local restore adapters are required.");
    if (!Array.isArray(plan.proposedItems) || !Array.isArray(plan.conflicts) || plan.conflicts.length) fail("Resolve every cloud/local conflict before restoring.");
    if (!isCurrent()) fail("Account changed before local restore commit.");
    const current = readLocalItems(ownerId);
    if (current && typeof current.then === "function") fail("Local restore adapters must be synchronous.");
    if (!Array.isArray(current) || canonical(current) !== plan.baseLocalFingerprint) fail("The local library changed after planning. Rebuild the restore plan before committing.");
    const ids = new Set(current.map(item => item?.id));
    const cloudIds = new Set();
    for (const item of plan.proposedItems) {
      if (!item || !isUuid(item.id) || !item.cloudBackup || !isUuid(item.cloudBackup.characterId) ||
          !Number.isInteger(item.cloudBackup.version) || item.cloudBackup.version < 1 ||
          !Array.isArray(item.referenceImages) || item.referenceImages.length !== 0) {
        fail("Restore proposal contains an invalid passport or missing-media reference.");
      }
      if (ids.has(item.id) || cloudIds.has(item.cloudBackup.characterId)) fail("Restore proposal contains a duplicate local or cloud identity.");
      ids.add(item.id);
      cloudIds.add(item.cloudBackup.characterId);
    }
    const merged = [...plan.proposedItems, ...current];
    if (merged.length > 100) fail("The local library limit of 100 materials would be exceeded.");
    if (!isCurrent()) fail("Account changed before local restore commit.");
    let writeStarted = false;
    try {
      writeStarted = true;
      const writeResult = writeLocalItems(ownerId, merged);
      if (writeResult && typeof writeResult.then === "function") fail("Local restore adapter must commit synchronously.");
      if (!isCurrent()) fail("Account changed during local restore commit.");
      const readBack = readLocalItems(ownerId);
      if (readBack && typeof readBack.then === "function") fail("Local restore adapters must be synchronous.");
      if (!Array.isArray(readBack) || canonical(readBack) !== canonical(merged)) fail("Local restore read-back verification failed.");
      return Object.freeze({restoredCount:plan.proposedItems.length,totalCount:merged.length});
    } catch (error) {
      // Best-effort compensation: adapters are required to address the supplied
      // owner key, never whichever account happens to be active in the UI.
      // If the account changed, do not invoke a potentially session-bound writer.
      if (writeStarted && isCurrent()) {
        try {
          writeLocalItems(ownerId, current);
          const rollbackReadBack = readLocalItems(ownerId);
          if (!Array.isArray(rollbackReadBack) || canonical(rollbackReadBack) !== canonical(current)) {
            fail("Local restore failed and rollback verification also failed.");
          }
        } catch {
          fail("Local restore failed; rollback could not be verified. Keep the browser storage intact and contact support before retrying.");
        }
      }
      throw error;
    }
  }

  globalThis.PWACharacterCloudRestore = Object.freeze({planRestore,selectRestorePlan,applyRestorePlan});
})();
