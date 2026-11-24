"use strict";

function createMovieCloudOperations(deps) {
  const state = { timer: null, syncingContext: null, pendingContext: null, loadingContext: null };
  const current = context => deps.isCurrent(context);
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
        deps.writeTombstones(context.ownerId, deps.readTombstones(context.ownerId).filter(id => !deletedIds.includes(id)));
      }
      if (!current(context)) return;
      // A newer local deletion may have been recorded while the cloud delete
      // request was pending. Never include those projects in this sync batch.
      const currentTombstones = new Set(deps.readTombstones(context.ownerId));
      const localProjects = deps.readProjects(context.ownerId).filter(project =>
        !deletedIds.includes(project.id) && !currentTombstones.has(project.id));
      const rows = localProjects.map(project => deps.toCloudRow(project, context.ownerId));
      deps.writeProjects(context.ownerId, localProjects);
      if (rows.length) {
        const { error } = await deps.supabase().from("projects").upsert(rows, { onConflict: "id" });
        if (error) throw error;
        if (!current(context)) return;
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
      const deletedIds = deps.readTombstones(context.ownerId);
      if (deletedIds.length) {
        const { error: deleteError } = await deps.supabase().from("projects").delete()
          .in("id", deletedIds).eq("owner_id", context.ownerId).eq("project_type", "movie");
        if (deleteError) throw deleteError;
        if (!current(context)) return;
        deps.writeTombstones(context.ownerId, deps.readTombstones(context.ownerId).filter(id => !deletedIds.includes(id)));
      }
      // Re-read after the awaited delete: newer tombstones may have been added
      // while the request was in flight and must not be reintroduced by this load.
      const deleted = new Set([...deletedIds, ...deps.readTombstones(context.ownerId)]);
      const merged = new Map(deps.readProjects(context.ownerId).filter(p => !deleted.has(p.id)).map(p => [p.id, p]));
      (data || []).filter(row => !deleted.has(row.id)).forEach(row => {
        const cloud = deps.fromCloudRow(row);
        const local = merged.get(cloud.id);
        if (!local || new Date(cloud.updatedAt || 0) >= new Date(local.updatedAt || 0)) merged.set(cloud.id, cloud);
      });
      const projects = [...merged.values()].sort((a,b) =>
        new Date(b.updatedAt || b.createdAt || 0) - new Date(a.updatedAt || a.createdAt || 0));
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
