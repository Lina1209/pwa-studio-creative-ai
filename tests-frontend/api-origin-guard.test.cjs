const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const source = fs.readFileSync(path.join(__dirname, "../app.js"), "utf8");

test("production API origin is fixed and ignores browser storage", () => {
  assert.match(source, /const DEFAULT_API_BASE = "https:\/\/pwa-studio-creative-ai\.onrender\.com"/);
  assert.match(source, /if \(!isLocalDevelopment\) return DEFAULT_API_BASE/);
  assert.match(source, /const configured = \(localStorage\.getItem\(API_URL_KEY\)/);
  assert.match(source, /url\.hostname !== location\.hostname/);
});

test("API requests reject off-origin and non-API destinations", () => {
  assert.match(source, /!path\.startsWith\("\/api\/"\)/);
  assert.match(source, /target\.origin !== trustedOrigin/);
  assert.match(source, /!target\.pathname\.startsWith\("\/api\/"\)/);
  assert.match(source, /path\.startsWith\("\/\/"\)/);
});

test("bearer token is app-controlled and redirects are rejected", () => {
  assert.match(source, /if \(headers\.has\("Authorization"\)\) throw/);
  assert.match(source, /headers\.set\("Authorization", "Bearer " \+ token\)/);
  assert.match(source, /credentials: "omit"/);
  assert.match(source, /redirect: "error"/);
});

test("production backend URL cannot be changed from settings", () => {
  assert.match(source, /apiUrlInput\.readOnly = !isLocalDevelopment/);
  assert.match(source, /if \(!isLocalDevelopment\) \{/);
  assert.match(source, /\$\("#saveBackend"\)\.hidden = !isLocalDevelopment/);
});
