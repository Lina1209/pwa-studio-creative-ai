/* PWA Studio: safe cloud-to-local Character Library restore planner.
 * This module is deliberately side-effect free: it performs no storage writes,
 * no image downloads, and no UI activation. The caller must review and commit
 * the complete plan only after all pages validate and the account is unchanged.
 */
(() => {
  "use strict";

  const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  const MAX_PAGES = 100;
  const MAX_ITEMS = 10000;
  const MAX_PAGE_SIZE = 100;

  const fail = message => { throw new Error(message); };
  const isUuid = value => typeof value === "string" && UUID.test(value);
  const text = (value, max, label) => {
    if (typeof value !== "string" || value.length > max) fail("Invalid " + label + ".");
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
    const passport = value.passport && typeof value.passport === "object" && !Array.isArray(value.passport) ? value.passport : {};
    const refs = value.referenceImages === undefined ? [] : value.referenceImages;
    if (!Array.isArray(refs) || refs.length > 6) fail("Cloud passport reference manifest is invalid.");
    const manifest = refs.map(ref => {
      if (!ref || typeof ref !== "object" || Array.isArray(ref)) fail("Cloud reference descriptor is invalid.");
      return {
        id: text(ref.id || "", 180, "cloud reference ID"),
        name: text(ref.name || "", 120, "cloud reference name"),
        type: text(ref.type || "", 80, "cloud reference type")
      };
    });
    return {
      kind: value.kind === "scene" ? "scene" : "character",
      representation: ["2d", "3d", "both"].includes(value.representation) ? value.representation : "2d",
      voice: text(value.voice || "", 500, "character voice"),
      passport: {
        face: text(passport.face || "", 1200, "passport face"),
        body: text(passport.body || "", 1200, "passport body"),
        wardrobe: text(passport.wardrobe || "", 1200, "passport wardrobe"),
        palette: text(passport.palette || "", 1200, "passport palette")
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

  async function planRestore({ownerId, fetchPage, existingLocalItems, isCurrent = () => true}) {
    if (!isUuid(ownerId)) fail("A valid authenticated owner ID is required.");
    if (typeof fetchPage !== "function") fail("A cloud page loader is required.");
    if (!Array.isArray(existingLocalItems) || existingLocalItems.length > 100) fail("The local library is invalid or exceeds its supported limit.");
    const localById = new Map();
    for (const item of existingLocalItems) {
      if (!item || !isUuid(item.id) || typeof item.name !== "string" || localById.has(item.id)) fail("Local library contains an invalid or duplicate character ID.");
      localById.set(item.id, item);
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
    const proposedItems = [];
    const unchanged = [];
    const conflicts = [];
    for (const row of cloudRows) {
      const data = safeReferenceData(row.reference_data || {});
      const existing = localById.get(row.source_local_id);
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
            referenceManifest: data.referenceManifest
          }
        });
        continue;
      }
      const same = existing.name === row.name &&
        String(existing.description || "") === String(row.description || "") &&
        canonical(localProjection(existing)) === canonical(data);
      const knownCloudId = existing.cloudBackup?.characterId;
      if (knownCloudId && knownCloudId !== row.id) {
        conflicts.push({localId: row.source_local_id, cloudId: row.id, reason: "local_cloud_identity_mismatch"});
      } else if (same) {
        unchanged.push({localId: row.source_local_id, cloudId: row.id, version: row.version});
      } else {
        conflicts.push({localId: row.source_local_id, cloudId: row.id, reason: "local_and_cloud_content_differ"});
      }
    }
    if (!isCurrent()) fail("Account changed before cloud restore planning completed.");
    return Object.freeze({
      complete: true,
      ownerId,
      pagesRead,
      cloudCount: cloudRows.length,
      proposedItems: Object.freeze(proposedItems),
      unchanged: Object.freeze(unchanged),
      conflicts: Object.freeze(conflicts)
    });
  }

  globalThis.PWACharacterCloudRestore = Object.freeze({planRestore});
})();
