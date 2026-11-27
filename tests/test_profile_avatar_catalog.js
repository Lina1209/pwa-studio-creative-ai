"use strict";
const assert = require("node:assert/strict");
require("../profile-avatar-catalog.js");

const catalog = globalThis.PWAProfileAvatarCatalog;
assert.ok(catalog, "shared avatar catalog must be exposed");
assert.equal(catalog.version, 1);
assert.equal(catalog.items.length, 9);
assert.equal(new Set(catalog.items.map(item => item.id)).size, catalog.items.length, "catalog IDs must be unique");
assert.ok(catalog.items.every(item => item.representation === "2d"), "only real 2D assets are currently published");
for (const item of catalog.items) {
  assert.match(item.assetPath, /^assets\/avatars\/2d\/[a-z0-9-]+\.svg$/);
  assert.equal(catalog.getById(item.id), item);
}
const katty = catalog.getById("katty-assistant");
assert.equal(katty.identityKey, "katty-katarina");
assert.equal(catalog.getAssetPath("katty-assistant"), katty.assetPath);
assert.equal(catalog.getAssetPath("unknown-avatar"), catalog.items[0].assetPath);
assert.equal(catalog.getById("unknown-avatar"), null);
assert.equal(Object.isFrozen(catalog), true);
assert.equal(Object.isFrozen(catalog.items), true);
assert.ok(catalog.items.every(Object.isFrozen), "catalog entries must be immutable");
console.log("Profile avatar catalog runtime checks passed.");
