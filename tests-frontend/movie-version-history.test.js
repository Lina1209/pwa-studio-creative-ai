"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { snapshot, addVersion, isRestorable, restore } = require("../movie-version-history.js");

const project = () => ({
  id: "film-1", name: "Тайна моря", createdAt: "2026-01-01T00:00:00.000Z",
  updatedAt: "2026-01-02T00:00:00.000Z", completedSteps: ["story"],
  characters: "Капитан", versions: []
});

test("snapshot is a deep independent copy without nested version history", () => {
  const source = project();
  const saved = snapshot(source);
  source.completedSteps.push("storyboard");
  assert.deepEqual(saved.completedSteps, ["story"]);
  assert.equal(Object.hasOwn(saved, "versions"), false);
});

test("adding versions keeps newest first and caps history at twenty", () => {
  const source = project();
  for (let i = 0; i < 22; i++) addVersion(source, new Date(2026, 0, i + 1).toISOString());
  assert.equal(source.versions.length, 20);
  assert.equal(source.versions[0].savedAt, new Date(2026, 0, 22).toISOString());
  assert.equal(source.versions[19].savedAt, new Date(2026, 0, 3).toISOString());
});

test("restore preserves current state as newest backup and does not mutate selected snapshot", () => {
  const live = project();
  live.name = "Текущий вариант";
  live.versions = [{ savedAt: "2026-01-01T00:00:00.000Z", data: { id: live.id, name: "Старый", completedSteps: [] } }];
  const selectedData = project();
  delete selectedData.versions;
  selectedData.name = "Предыдущая версия";
  const selected = { savedAt: "2026-01-01T00:00:00.000Z", data: selectedData };
  const restored = restore(live, selected, "2026-02-01T00:00:00.000Z");
  assert.equal(restored.name, "Предыдущая версия");
  assert.equal(restored.id, live.id);
  assert.equal(restored.versions.length, 2);
  assert.equal(restored.versions[0].data.name, "Текущий вариант");
  assert.equal(selected.data.name, "Предыдущая версия");
  restored.completedSteps.push("characters");
  assert.deepEqual(selected.data.completedSteps, ["story"]);
});

test("restore rejects malformed, foreign, or structurally unsafe snapshots", () => {
  const live = project();
  const invalid = [
    null,
    { savedAt: "not-a-date", data: project() },
    { savedAt: "2026-01-01T00:00:00.000Z", data: null },
    { savedAt: "2026-01-01T00:00:00.000Z", data: { ...project(), id: "another-film" } },
    { savedAt: "2026-01-01T00:00:00.000Z", data: { ...project(), completedSteps: "story" } },
    { savedAt: "2026-01-01T00:00:00.000Z", data: { ...project(), versions: [] } }
  ];
  for (const entry of invalid) {
    assert.equal(isRestorable(entry, live.id), false);
    assert.equal(restore(live, entry), null);
  }
  assert.equal(live.name, "Тайна моря");
  assert.equal(live.versions.length, 0);
});


test("stage completion advances its stale-edit baseline only after local persistence succeeds", () => {
  const fs = require("node:fs");
  const app = fs.readFileSync(require.resolve("../app.js"), "utf8");
  const expected = [
    "current.workflowStep=Math.min(stageIndex+1,4); current.updatedAt=new Date().toISOString();",
    "if(!movieWrite(latest))return;",
    "baseUpdatedAt=current.updatedAt;"
  ];
  const start = app.indexOf(expected[0]);
  assert.notEqual(start, -1, "stage completion block should exist");
  let previous = start;
  for (const fragment of expected.slice(1)) {
    const next = app.indexOf(fragment, previous + 1);
    assert.notEqual(next, -1, "expected persistence-before-baseline ordering");
    assert.ok(next > previous);
    previous = next;
  }
});


test("rename re-reads the project after the prompt and aborts if its baseline changed", () => {
  const fs = require("node:fs");
  const app = fs.readFileSync(require.resolve("../app.js"), "utf8");
  const start = app.indexOf('const rename=makeAction("✎ Переименовать фильм"');
  const end = app.indexOf('const copy=makeAction("⧉ Создать копию"', start);
  assert.notEqual(start, -1, "rename action should exist");
  assert.ok(end > start, "rename action should end before copy action");
  const handler = app.slice(start, end);
  const baseline = handler.indexOf("const baseUpdatedAt=initial.updatedAt||initial.createdAt||null;");
  const prompt = handler.indexOf("window.prompt(");
  const reread = handler.indexOf("const latest=movieRead();");
  const guard = handler.indexOf("(original.updatedAt||original.createdAt||null)!==baseUpdatedAt");
  const snapshot = handler.indexOf("addMovieVersion(original);");
  assert.ok(baseline >= 0 && baseline < prompt);
  assert.ok(prompt < reread && reread < guard && guard < snapshot);
  assert.match(handler, /Название не изменено/);
});


test("restore dialog closes and reports success only after local persistence succeeds", () => {
  const fs = require("node:fs");
  const app = fs.readFileSync(require.resolve("../app.js"), "utf8");
  const start = app.indexOf('const restore=makeAction("Восстановить эту версию"');
  const end = app.indexOf('restore.classList.add("movie-history-restore")', start);
  assert.notEqual(start, -1, "restore action should exist");
  assert.ok(end > start, "restore action should end before its button is attached");
  const handler = app.slice(start, end);
  const persist = handler.indexOf("if(movieWrite(latest)){");
  const close = handler.indexOf("overlay.remove();", persist);
  const success = handler.indexOf("Предыдущая версия восстановлена", persist);
  assert.ok(persist >= 0, "restore must check local persistence result");
  assert.ok(close > persist, "dialog must close only inside successful persistence branch");
  assert.ok(success > close, "success feedback must follow persistence and dialog close");
  assert.equal(handler.includes("movieWrite(latest);overlay.remove();"), false);
});

test("copy and restore refuse projects with a pending cloud deletion",()=>{
  const fs=require("node:fs");
  const app=fs.readFileSync(require.resolve("../app.js"),"utf8");
  const copyStart=app.indexOf('const copy=makeAction("⧉ Создать копию"');
  const copyEnd=app.indexOf('const version=makeAction("↶ История версий"',copyStart);
  assert.ok(copyStart>=0&&copyEnd>copyStart);
  const copyHandler=app.slice(copyStart,copyEnd);
  const copyQueueCheck=copyHandler.indexOf("readMovieTombstones()");
  const copyGuard=copyHandler.indexOf("pendingDeletes.includes(original.id)");
  const clone=copyHandler.indexOf("const clone=");
  assert.ok(copyQueueCheck>=0&&copyGuard>copyQueueCheck&&clone>copyGuard);

  const restoreStart=app.indexOf('const restore=makeAction("Восстановить эту версию"');
  const restoreEnd=app.indexOf('restore.classList.add("movie-history-restore")',restoreStart);
  assert.ok(restoreStart>=0&&restoreEnd>restoreStart);
  const restoreHandler=app.slice(restoreStart,restoreEnd);
  const restoreQueueCheck=restoreHandler.indexOf("readMovieTombstones()");
  const restoreGuard=restoreHandler.indexOf("pendingDeletes.includes(live.id)");
  const restoreMutation=restoreHandler.indexOf("MovieVersionHistory.restore(");
  assert.ok(restoreQueueCheck>=0&&restoreGuard>restoreQueueCheck&&restoreMutation>restoreGuard);
});
