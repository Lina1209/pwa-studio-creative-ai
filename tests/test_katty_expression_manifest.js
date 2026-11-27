"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");
const identity = JSON.parse(fs.readFileSync(path.join(root, "assets/characters/katty/identity.v1.json"), "utf8"));
const manifestPath = path.join(root, "assets/characters/katty/expressions.v1.json");
const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));

assert.equal(manifest.schemaVersion, 1);
assert.equal(manifest.identityKey, identity.identityKey);
assert.equal(manifest.visualIdentityManifest, "assets/characters/katty/identity.v1.json");
assert.equal(manifest.status, "static_expression_artwork_available");
assert.equal(manifest.runtimeStatus, "not_connected");
assert.equal(manifest.expressions.length, 8);
const ids = manifest.expressions.map(item => item.id);
assert.equal(new Set(ids).size, ids.length);
for (const item of manifest.expressions) {
  assert.match(item.id, /^[a-z]+(?:-[a-z]+)*$/);
  assert.ok(item.label.length > 0);
  assert.ok(item.brows && item.eyes && item.mouth && item.cheeks);
  assert.ok(Number.isFinite(item.intensity) && item.intensity >= 0 && item.intensity <= 1);
}
for (const phrase of ["green eyes", "freckles", "curly fire-red hair", "canonical hoodie"]) {
  assert.ok(manifest.invariants.some(item => item.includes(phrase)), "missing identity invariant: " + phrase);
}
assert.equal(manifest.motionPrinciples.status, "guidance_only_no_animation_assets");
assert.ok(manifest.futureRigRequirements.includes("use the same expression IDs for 2D and 3D mappings"));


for (const expression of manifest.expressions) {
  assert.equal(expression.assetType, "static_svg");
  assert.equal(expression.assetStatus, "approved_static_artwork");
  assert.ok(expression.asset.startsWith("assets/characters/katty/expressions/"));
  const svg = fs.readFileSync(path.join(root, expression.asset), "utf8");
  assert.match(svg, /^<svg\\b/);
  assert.match(svg, /#45a66d/, "green eyes must remain in " + expression.id);
  assert.match(svg, /#ffd1ad/, "canonical face tone must remain in " + expression.id);
  assert.match(svg, /#e45c2e/, "red hair must remain in " + expression.id);
  assert.match(svg, /PWA/, "PWA Studio shirt identity must remain in " + expression.id);
  assert.match(svg, /#b96b4e/, "freckles must remain in " + expression.id);
}

console.log("Katty expression manifest and static artwork checks passed.");
