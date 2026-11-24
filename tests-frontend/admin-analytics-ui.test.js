import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
const app = readFileSync(new URL("../app.js", import.meta.url), "utf8");

test("admin analytics panel exposes only the three documented aggregate metrics", () => {
  for (const id of [
    "adminAnalyticsSection",
    "adminAnalyticsStart",
    "adminAnalyticsEnd",
    "adminAnalyticsRegistrations",
    "adminAnalyticsProjects",
    "adminAnalyticsAI",
    "adminAnalyticsFeedback",
  ]) assert.match(html, new RegExp('id="' + id + '"'));
  assert.match(html, /Регистрации/);
  assert.match(html, /Проектная активность/);
  assert.match(html, /Успешные AI-запросы/);
  assert.match(html, /не счётчик посетителей/i);
  assert.doesNotMatch(html, /Уникальные посетители/);
});

test("analytics fetch remains behind the server-confirmed owner panel", () => {
  assert.match(app, /apiRequest\("\/api\/auth\/me"\)/);
  assert.match(app, /panel\.hidden = data\.role !== "admin"/);
  assert.match(app, /if\s*\(!authSession\?\.user \|\| !panel \|\| panel\.hidden \|\| !section\)\s*return/);
  assert.match(app, /apiRequest\("\/api\/admin\/analytics\?"\s*\+\s*query\.toString\(\)\)/);
});

test("analytics UI bounds date ranges and rejects stale account responses", () => {
  assert.match(app, /31\*24\*60\*60\*1000/);
  assert.match(app, /start>=end/);
  assert.match(app, /version!==authContextVersion \|\| authSession\?\.user\?\.id!==userId \|\| panel\.hidden/);
  assert.match(app, /requestId===adminAnalyticsRequestId/);
  assert.match(app, /textContent=Number\.isSafeInteger/);
  assert.match(app, /Статистика пока не подключена к базе/);
});

test("analytics UI does not display raw account rows or personal identifiers", () => {
  const start = app.indexOf("const loadAdminAnalytics");
  const end = app.indexOf("setAdminAnalyticsDefaultRange();", start);
  assert.ok(start >= 0 && end > start, "analytics loader should be present");
  const loader = app.slice(start, end);
  assert.doesNotMatch(loader, /innerHTML/);
  assert.doesNotMatch(loader, /email|user_id|username|project_title/i);
});
