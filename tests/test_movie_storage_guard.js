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
assert.match(app, /Гостевые проекты не загружены/);


assert.match(app, /PWAStudioMovieStorageGuard\.parse\(localStorage\.getItem\(movieStorageKey\(\)\)\);\s*PWAStudioMovieStorageGuard\.parse\(JSON\.stringify\(projects\)\);/);
assert.match(app, /Validate the local library before processing deletion tombstones or uploading anything/);
assert.match(app, /A corrupt local library must stop cloud-side deletion and merge as well/);
assert.match(app, /PWAStudioMovieStorageGuard\.parse\(localStorage\.getItem\(guestArchiveKey\(\)\)\)/);


assert.match(app, /Очередь удалений фильмов повреждена/);
assert.match(app, /value\.some\(id=>!isUuid\(id\)\)/);
assert.match(app, /!writeMovieTombstones\(\[\.\.\.deletedIds,project\.id\]\)\)return/);
\nconsole.log("Movie storage guard tests passed.");
