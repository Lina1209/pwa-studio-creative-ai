const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const context = { window: {} };
vm.runInNewContext(fs.readFileSync("movie-storage-guard.js", "utf8"), context);
const guard = context.window.PWAStudioMovieStorageGuard;
assert.ok(guard, "guard must be exported");

const valid = [{ id: "movie-1", name: "Тест", idea: "История", completedSteps: ["story"], versions: [] }];
assert.deepEqual(JSON.parse(JSON.stringify(guard.parse(JSON.stringify(valid)))), valid);
assert.deepEqual(JSON.parse(JSON.stringify(guard.parse(null))), []);
assert.deepEqual(JSON.parse(JSON.stringify(guard.parse(""))), []);
const historical = [{ id: "movie-history", name: "Тест", versions: [
  { savedAt: "2026-11-28T12:00:00.000Z", data: { id: "movie-history", name: "Старая версия", completedSteps: ["story"] } }
] }];
assert.equal(guard.parse(JSON.stringify(historical))[0].versions.length, 1);
for (const versions of [
  [{ savedAt: "not-a-date", data: { id: "movie-history" } }],
  [{ savedAt: "2026-11-28T12:00:00.000Z", data: { id: "other-id" } }],
  [{ savedAt: "2026-11-28T12:00:00.000Z", data: [] }],
  [{ savedAt: "2026-11-28T12:00:00.000Z", data: { id: "movie-history", name: 42 } }]
]) {
  assert.throws(() => guard.parse(JSON.stringify([{ id: "movie-history", versions }])),
    /История|истории|Запись истории/);
}

for (const raw of ["{broken", "{}", "null", '[{"name":"Без ID"}]', '[null]', '[[]]',
  '[{"id":"x"},{"id":"x"}]', '[{"id":"x","name":42}]',
  '[{"id":"x","completedSteps":"story"}]', '[{"id":"x","completedSteps":["unknown"]}]',
  '[{"id":"x","versions":{}}]']) {
  assert.throws(() => guard.parse(raw), undefined, "must reject malformed data: " + raw);
}

const mixed = '[{"id":"valid"},{"id":"broken","storyboard":false}]';
assert.throws(() => guard.parse(mixed), /Сохранение заблокировано/);
assert.equal(mixed, '[{"id":"valid"},{"id":"broken","storyboard":false}]',
  "validation must not mutate the source string");

const app = fs.readFileSync("app.js", "utf8");
assert.match(app, /const movieRead = \(\) => \{\s*\/\/ Fail closed/);
assert.match(app, /PWAStudioMovieStorageGuard\.parse\(localStorage\.getItem\(movieStorageKey\(\)\)\)/);
assert.doesNotMatch(app, /const movieRead = \(\) => \{[\s\S]{0,1800}catch\s*\{\s*return \[\];\s*\}\s*\};/);
assert.match(app, /Проекты не загружены/);
assert.match(app, /Гостевые проекты или архив не загружены/);
assert.match(app, /historyContextVersion!==authContextVersion/);
assert.match(app, /historyOwnerId!==\(authSession\?\.user\?\.id\|\|null\)/);
assert.match(app, /const liveVersion=\(live\.versions\|\|\[\]\)\.find/);
assert.match(app, /preserve all content and history exactly/);
assert.doesNotMatch(app, /copy\.(?:name|idea|story|storyboard|characters|voices|edit)=String\([^\n]*\.slice\(/);
assert.doesNotMatch(app, /copy\.completedSteps=Array\.isArray\(copy\.completedSteps\)\?copy\.completedSteps\.filter/);


assert.match(app, /PWAStudioMovieStorageGuard\.parse\(localStorage\.getItem\(movieStorageKey\(\)\)\);\s*PWAStudioMovieStorageGuard\.parse\(JSON\.stringify\(projects\)\);/);
assert.match(app, /Validate the local library before processing deletion tombstones or uploading anything/);
assert.match(app, /A corrupt local library must stop cloud-side deletion and merge as well/);
assert.match(app, /PWAStudioMovieStorageGuard\.parse\(localStorage\.getItem\(guestArchiveKey\(\)\)\)/);
assert.match(app, /const writeMovieStorage = projects => \{/);
assert.match(app, /writeMovieStorage\(localProjects\)/);
assert.match(app, /if \(changed\) writeMovieStorage\(active\)/);
assert.match(app, /Reject the entire backup if even one record or nested version is malformed/);
assert.doesNotMatch(app, /const valid=imported\.filter/);
assert.match(app, /version\.data,id:copy\.id/);
assert.match(app, /version\.data, id: project\.id/);
assert.match(app, /Экспорт остановлен для защиты данных/);
assert.match(app, /Гостевые проекты или архив не загружены/);
assert.match(app, /archivedProjects=authSession\?\.user\?\[\]:readGuestArchive\(\)/);
assert.match(app, /Облачная запись фильма имеет неверный формат или принадлежит другому пространству/);
assert.match(app, /Optimistic concurrency: never blindly upsert/);
assert.doesNotMatch(app, /from\("projects"\)\.upsert\(rows/);
assert.match(app, /\.eq\("updated_at", item\.expectedUpdatedAt\)[\s\S]*\.select\("id"\)/);
assert.match(app, /Фильм изменился на другом устройстве во время сохранения/);
assert.match(app, /локальная копия при конфликте/);
assert.match(app, /writeMovieStorage\(nextLocal\)/);
assert.match(app, /if \(!contextIsCurrent\(\) \|\| !writeMovieStorage\(nextLocal\)\)[\s\S]*?renderMovieProjects\(\)/);
assert.match(app, /localStorage\.setItem\(movieStorageKey\(\), JSON\.stringify\(projects\)\);\s*return true;/);
assert.match(app, /\.eq\("settings", JSON\.stringify\(item\.expectedSettings\)\)/);
assert.doesNotMatch(app, /else if \(sameContent\)\s*\{\s*merged\.set/);
assert.match(app, /const movieStableContent = value/);
assert.match(app, /if \(cloudTime >= localTime\)/);
assert.match(app, /Облачная версия загружена, а локальный вариант сохранён отдельной копией/);
assert.match(app, /expectedSettings: remote\.settings/);
assert.match(app, /\.eq\("settings", JSON\.stringify\(item\.expectedSettings\)\)/);
assert.match(app, /\.eq\("title", item\.expectedTitle\)[\s\S]*\.eq\("description", item\.expectedDescription\)/);
assert.match(app, /if \(!contextIsCurrent\(\) \|\| !writeMovieStorage\(nextLocal\)\)/);
assert.match(app, /movieCloudState\.pending = true/);
assert.match(app, /window\.addEventListener\("online",\s*\(\)\s*=>\s*\{\s*if \(authSession\?\.user\?\.id\) scheduleMovieCloudSync\(\);/);
assert.match(app, /return PWAStudioMovieStorageGuard\.parse\(JSON\.stringify\(\[candidate\]\)\)\[0\]/);
assert.doesNotMatch(app, /versions: Array\.isArray\(saved\.versions\) \? saved\.versions : \[\]/);
assert.doesNotMatch(app, /completedSteps: Array\.isArray\(saved\.completedSteps\) \? saved\.completedSteps : \[\]/);


assert.match(app, /Очередь удалений фильмов повреждена/);
assert.match(app, /value\.some\(id=>!isUuid\(id\)\)/);
assert.match(app, /!writeMovieTombstones\(\[\.\.\.deletedIds,project\.id\]\)\)return/);
assert.match(app, /Remove only IDs handled by this request; preserve tombstones added while awaiting the network/);
assert.match(app, /writeMovieTombstones\(readMovieTombstones\(\)\.filter\(id => !deletedIds\.includes\(id\)\)\)/);
assert.doesNotMatch(app.match(/const loadMovieProjectsFromCloud = async \(\) => \{[\s\S]*?const movieRead = \(\) => \{/)[0], /writeMovieTombstones\(\[\]\)/);
assert.match(app, /network wait may have overlapped local edits or another deletion; merge from fresh state[\\s\\S]*?local = movieRead\(\);[\\s\\S]*?deletedIds = readMovieTombstones\(\);/);

console.log("Movie storage guard tests passed.");
