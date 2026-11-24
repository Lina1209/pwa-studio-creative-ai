"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

test("service worker pre-caches all local scripts required by the app shell", () => {
  const root = path.join(__dirname, "..");
  const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
  const worker = fs.readFileSync(path.join(root, "sw.js"), "utf8");
  const coreMatch = worker.match(/const CORE_ASSETS = \[([\s\S]*?)\];/);
  assert.ok(coreMatch, "CORE_ASSETS must be declared");
  const coreAssets = new Set([...coreMatch[1].matchAll(/"([^"]+)"/g)].map(match => match[1]));
  const localScripts = [...html.matchAll(/<script[^>]+src=["']([^"']+)/g)]
    .map(match => match[1])
    .filter(src => src.startsWith("./"));
  for (const script of localScripts) assert.ok(coreAssets.has(script), `Missing offline shell asset: ${script}`);
});

test("runtime modules use the network-first shell update path", () => {
  const worker = fs.readFileSync(path.join(__dirname, "../sw.js"), "utf8");
  for (const asset of ["movie-cloud-context.js", "movie-cloud-operations.js", "movie-version-history.js",
    "movie-storage-guard.js", "movie-guest-expiry.js", "movie-tombstone-storage.js", "movie-id.js"]) {
    assert.ok(worker.includes(`"/${asset}"`), `${asset} must be network-first`);
  }
});
