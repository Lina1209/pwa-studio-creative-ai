"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
require("../profile-avatar-catalog.js");

const catalog = globalThis.PWAProfileAvatarCatalog;
assert.ok(catalog, "shared avatar catalog must be exposed");
assert.equal(catalog.version, 1);
assert.equal(catalog.items.length, 9);
assert.equal(new Set(catalog.items.map(item => item.id)).size, catalog.items.length);
assert.ok(catalog.items.every(item => item.representation === "2d"));
for (const item of catalog.items) {
  assert.match(item.assetPath, /^assets\/avatars\/2d\/[a-z0-9-]+\.svg$/);
  assert.equal(catalog.getById(item.id), item);
}
const katty = catalog.getById("katty-assistant");
assert.equal(katty.identityKey, "katty-katarina");
assert.equal(katty.identityManifest, "assets/characters/katty/identity.v1.json");
const passport = JSON.parse(fs.readFileSync(path.join(__dirname, "..", katty.identityManifest), "utf8"));
assert.equal(passport.identityKey, katty.identityKey);
assert.equal(passport.profileAvatarCatalogId, katty.id);
assert.equal(passport.representations["2d"].asset, katty.assetPath);
assert.equal(passport.representations["3d"].status, "not_created");
assert.equal(passport.representations["3d"].asset, null);
assert.ok(passport.identityLock.hair.includes("кудряв"));
assert.ok(passport.identityLock.eyes.includes("зелён"));
assert.ok(passport.identityLock.skin.includes("веснуш"));
assert.ok(passport.wardrobeLock.primary.includes("фиолет"));
assert.ok(passport.wardrobeLock.shirt.includes("PWA Studio"));
assert.equal(catalog.getAssetPath("katty-assistant"), katty.assetPath);
assert.equal(catalog.getAssetPath("unknown-avatar"), catalog.items[0].assetPath);
assert.equal(catalog.getById("unknown-avatar"), null);
assert.equal(Object.isFrozen(catalog), true);
assert.equal(Object.isFrozen(catalog.items), true);
assert.ok(catalog.items.every(Object.isFrozen));
console.log("Profile avatar catalog and Katty identity manifest checks passed.");
