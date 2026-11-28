"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const root = path.join(__dirname, "..");
const readJson = file => JSON.parse(fs.readFileSync(path.join(root, file), "utf8"));
const layers = readJson("assets/characters/katty/2d-layers.v1.json");
const expressions = readJson("assets/characters/katty/expressions.v1.json");
const identity = readJson("assets/characters/katty/identity.v1.json");

assert.equal(layers.schemaVersion, 1);
assert.equal(layers.identityKey, identity.identityKey);
assert.equal(layers.status, "layer_architecture_specification_only");
assert.equal(layers.runtimeStatus, "not_connected");
assert.equal(layers.baseArtwork, identity.representations["2d"].asset);
assert.equal(layers.fallback.asset, layers.baseArtwork);
assert.equal(layers.fallback.mode, "static");
assert.equal(layers.motionSafety.defaultMotion, "static");
assert.equal(layers.motionSafety.reducedMotion, "static");
assert.equal(layers.motionSafety.pauseWhenDocumentHidden, true);
assert.equal(layers.motionSafety.pauseWhenOffscreen, true);
const ids = layers.layers.map(layer => layer.id);
const z = layers.layers.map(layer => layer.zIndex);
assert.equal(new Set(ids).size, ids.length);
assert.equal(new Set(z).size, z.length);
assert.deepEqual(z, [...z].sort((a,b) => a-b));
for (const id of ["back-hair","hoodie","shirt-brand","headphones","face-base","freckles","eyes-white","irises-and-pupils","eyelids","eyebrows","mouth","front-hair","star-accents"]) {
  assert.ok(ids.includes(id), "missing semantic layer: " + id);
}
assert.ok(expressions.expressions.length >= 8);
assert.equal(layers.expressionBindings.source, "assets/characters/katty/expressions.v1.json");
assert.ok(layers.expressionBindings.requiredControls.every(id => ids.includes(id)));
assert.ok(!layers.layers.some(layer => layer.status === "implemented"), "spec must not claim unbuilt layers are implemented");
console.log("Katty 2D layer manifest checks passed.");
