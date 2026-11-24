"use strict";

const cloneJson = value => JSON.parse(JSON.stringify(value));
const isPlainObject = value => !!value && typeof value === "object" && !Array.isArray(value) &&
  (Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null);

const snapshot = project => {
  if (!isPlainObject(project)) throw new TypeError("Movie project must be an object.");
  const copy = cloneJson(project);
  delete copy.versions;
  return copy;
};

const addVersion = (project, savedAt = new Date().toISOString()) => {
  if (!isPlainObject(project)) throw new TypeError("Movie project must be an object.");
  const previous = Array.isArray(project.versions) ? project.versions : [];
  const next = [{ savedAt, data: snapshot(project) }, ...previous].slice(0, 20);
  project.versions = next;
  return project;
};

const isRestorable = (entry, projectId) => {
  if (!isPlainObject(entry) || typeof entry.savedAt !== "string" ||
      !Number.isFinite(Date.parse(entry.savedAt)) || !isPlainObject(entry.data)) return false;
  const data = entry.data;
  if (typeof projectId !== "string" || data.id !== projectId || typeof data.name !== "string") return false;
  if (data.versions !== undefined) return false;
  if (data.completedSteps !== undefined && !Array.isArray(data.completedSteps)) return false;
  return true;
};

const restore = (liveProject, entry, updatedAt = new Date().toISOString()) => {
  if (!isPlainObject(liveProject) || !isRestorable(entry, liveProject.id)) return null;
  try {
    const restored = cloneJson(entry.data);
    const history = Array.isArray(liveProject.versions) ? cloneJson(liveProject.versions) : [];
    history.unshift({ savedAt: updatedAt, data: snapshot(liveProject) });
    restored.id = liveProject.id;
    restored.createdAt = liveProject.createdAt || restored.createdAt || updatedAt;
    restored.updatedAt = updatedAt;
    restored.versions = history.slice(0, 20);
    return restored;
  } catch {
    return null;
  }
};

const api = { snapshot, addVersion, isRestorable, restore };
if (typeof module !== "undefined" && module.exports) module.exports = api;
if (typeof window !== "undefined") window.MovieVersionHistory = api;
