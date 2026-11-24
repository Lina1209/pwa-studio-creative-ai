"use strict";

function createMovieCloudOperations(deps) {
  const state = { timer: null, syncingContext: null, pendingContext: null, loadingContext: null };
  const current = context => deps.isCurrent(context);
  const timestamp = value => {
    const parsed = Date.parse(value);
    return Number.isFinite(parsed) ? parsed : null;
  };
  const cloudIsNewer = (cloud, local) => {
    const cloudTime = timestamp(cloud.updatedAt);
    const localTime = timestamp(local.updatedAt);
    if (cloudTime === null) return false;
    if (localTime === null) return true;
    // Keep the device copy on ties: it may contain an unsynced edit whose
    // client timestamp has the same precision as the cloud row.
    return cloudTime > localTime;
  };
  const projectTime = project => timestamp(project.updatedAt) ?? timestamp(project.createdAt) ?? -Infinity;
  const MAX_PROJECT_PAYLOAD_BYTES = 256 * 1024;
  const MAX_SYNC_BATCH_BYTES = 2 * 1024 * 1024;
  function validateCloudRows(rows, ownerId) {
    if (!Array.isArray(rows)) throw new Error("Некорректный список облачных проектов.");
    let batchBytes = 0;
    for (const row of rows) {
      if (!row || typeof row !== "object" || Array.isArray(row) || row.owner_id !== ownerId ||
          (row.project_type != null && row.project_type !== "movie") ||
          (row.settings != null && (typeof row.settings !== "object" || Array.isArray(row.settings)))) {
        throw new Error("Структура облачного проекта некорректна; синхронизация остановлена.");
      }
      let serialized;
      try { serialized = JSON.stringify(row); }
      catch { throw new Error("Проект содержит данные, которые нельзя безопасно сериализовать."); }
      if (typeof serialized !== "string") throw new Error("Не удалось проверить размер облачного проекта.");
      const bytes = typeof TextEncoder === "function"
        ? new TextEncoder().encode(serialized).length
        : unescape(encodeURIComponent(serialized)).length;
      if (bytes > MAX_PROJECT_PAYLOAD_BYTES) {
        throw new Error("Проект слишком большой для облачного сохранения (лимит 256 КиБ). Разделите материал на несколько проектов.");
      }
      batchBytes += bytes;
      if (batchBytes > MAX_SYNC_BATCH_BYTES) {
        throw new Error("Пакет облачной синхронизации превышает 2 МиБ. Уменьшите объём проектов и повторите попытку.");
      }
    }
    return rows;
  }
  const schedule = context => {
    if (!context || !current(context)) return;
    deps.clearTimer(state.timer);
    state.timer = deps.setTimer(() => { state.timer = null; void sync(context); }, 350);
  };
  async function sync(context) {
    if (!current(context)) return;
    if (state.syncingContext) { state.pendingContext = context; return; }
    state.syncingContext = context;
    try {
      const deletedIds = deps.readTombstones(context.ownerId);
      if (deletedIds.length) {
        const { error } = await deps.supabase().from("projects").delete()
          .in("id", deletedIds).eq("owner_id", context.ownerId).eq("project_type", "movie");
        if (error) throw error;
        if (!current(context)) return;
        if (deps.writeTombstones(context.ownerId, deps.readTombstones(context.ownerId).filter(id => !deletedIds.includes(id))) === false) throw new Error("Удаление выполнено в облаке, но очередь ещё не удалось очистить на устройстве. Повторная синхронизация безопасна.");
      }
      if (!current(context)) return;
      // A newer local deletion may have been recorded while the cloud delete
      // request was pending. Never include those projects in this sync batch.
      const currentTombstones = new Set(deps.readTombstones(context.ownerId));
      let localProjects = deps.readProjects(context.ownerId).filter(project =>
        !deletedIds.includes(project.id) && !currentTombstones.has(project.id));
      let rows = validateCloudRows(localProjects.map(project => deps.toCloudRow(project, context.ownerId)), context.ownerId);
      if (rows.length) {
        // Preflight conflict check: do not blindly overwrite a cloud copy that
        // is already newer than this device's local draft. This narrows the
        // stale-device window, but is not a transaction/CAS against a write
        // arriving after this SELECT.
        const { data: cloudRows, error: readError } = await deps.supabase().from("projects")
          .select("id, owner_id, title, description, project_type, status, settings, created_at, updated_at")
          .in("id", rows.map(row => row.id)).eq("owner_id", context.ownerId).eq("project_type", "movie");
        if (readError) throw readError;
        if (!current(context)) return;
        const cloudById = new Map((cloudRows || []).map(row => [row.id, deps.fromCloudRow(row)]));
        const retained = new Map(localProjects.map(project => [project.id, project]));
        const blockedIds = new Set();
        for (const local of localProjects) {
          const cloud = cloudById.get(local.id);
          if (cloud && cloudIsNewer(cloud, local)) {
            retained.set(local.id, cloud);
            blockedIds.add(local.id);
          }
        }
        if (blockedIds.size) {
          localProjects = [...retained.values()];
          rows = validateCloudRows(rows.filter(row => !blockedIds.has(row.id)), context.ownerId);
        }
      }
      if (!current(context)) return;
      deps.writeProjects(context.ownerId, localProjects);
      if (rows.length !== localProjects.length && current(context)) deps.render();
      if (rows.length) {
        const { error } = await deps.supabase().from("projects").upsert(rows, { onConflict: "id" });
        if (error) throw error;
        if (!current(context)) return;
        // A delete can be recorded in another tab while this upsert is in
        // flight. Re-check the durable queue after the write and immediately
        // remove any just-resurrected rows; the queued sync will later clear
        // the tombstones after this idempotent delete is confirmed.
        const deletedDuringUpsert = deps.readTombstones(context.ownerId)
          .filter(id => rows.some(row => row.id === id));
        if (deletedDuringUpsert.length) {
          const { error: cleanupError } = await deps.supabase().from("projects").delete()
            .in("id", deletedDuringUpsert).eq("owner_id", context.ownerId).eq("project_type", "movie");
          if (cleanupError) throw cleanupError;
          if (!current(context)) return;
        }
      }
      if (current(context)) deps.feedback(deletedIds.length
        ? "✓ Фильмы и удаления синхронизированы с облаком Supabase."
        : "✓ Изменения сохранены в облаке Supabase.");
    } catch (error) {
      if (current(context)) deps.syncError(error);
    } finally {
      if (state.syncingContext === context) state.syncingContext = null;
      const pending = state.pendingContext;
      state.pendingContext = null;
      if (pending && current(pending)) schedule(pending);
    }
  }
  async function load(context) {
    if (!context || !current(context)) return;
    if (state.loadingContext && current(state.loadingContext)) return;
    state.loadingContext = context;
    try {
      const { data, error } = await deps.supabase().from("projects")
        .select("id, owner_id, title, description, project_type, status, settings, created_at, updated_at")
        .eq("owner_id", context.ownerId).eq("project_type", "movie").order("updated_at", { ascending: false });
      if (error) throw error;
      if (!current(context)) return;
      // Treat the SELECT response as untrusted input even though the query is owner-scoped
      // and Supabase RLS is the primary boundary. Never merge a foreign/malformed row locally.
      validateCloudRows(data || [], context.ownerId);
      const deletedIds = deps.readTombstones(context.ownerId);
      if (deletedIds.length) {
        const { error: deleteError } = await deps.supabase().from("projects").delete()
          .in("id", deletedIds).eq("owner_id", context.ownerId).eq("project_type", "movie");
        if (deleteError) throw deleteError;
        if (!current(context)) return;
        if (deps.writeTombstones(context.ownerId, deps.readTombstones(context.ownerId).filter(id => !deletedIds.includes(id))) === false) throw new Error("Удаление выполнено в облаке, но очередь ещё не удалось очистить на устройстве. Повторная синхронизация безопасна.");
      }
      // Re-read after the awaited delete: newer tombstones may have been added
      // while the request was in flight and must not be reintroduced by this load.
      const deleted = new Set([...deletedIds, ...deps.readTombstones(context.ownerId)]);
      const merged = new Map(deps.readProjects(context.ownerId).filter(p => !deleted.has(p.id)).map(p => [p.id, p]));
      (data || []).filter(row => !deleted.has(row.id)).forEach(row => {
        const cloud = deps.fromCloudRow(row);
        const local = merged.get(cloud.id);
        if (!local || cloudIsNewer(cloud, local)) merged.set(cloud.id, cloud);
      });
      const projects = [...merged.values()].sort((a,b) => projectTime(b) - projectTime(a));
      if (!current(context)) return;
      deps.writeProjects(context.ownerId, projects);
      deps.render();
      schedule(context);
      deps.feedback("✓ Фильмы загружены из облака. Изменения синхронизируются автоматически.");
    } catch (error) {
      if (current(context)) deps.loadError(error);
    } finally {
      if (state.loadingContext === context) state.loadingContext = null;
    }
  }
  return Object.freeze({
    schedule,
    load,
    state,
    cancelTimer() { deps.clearTimer(state.timer); state.timer = null; }
  });
}

if (typeof module === "object" && module.exports) module.exports = { createMovieCloudOperations };
if (typeof window !== "undefined") window.PWAMovieCloudOperations = { createMovieCloudOperations };
