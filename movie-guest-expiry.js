"use strict";

const GUEST_PROJECT_TTL_MS = 24 * 60 * 60 * 1000;

const normalizeGuestProjectExpiry = (project, now = Date.now()) => {
  if (!project || typeof project !== "object" || Array.isArray(project)) {
    throw new TypeError("Ожидался объект гостевого проекта.");
  }
  const expiry = Date.parse(project.guestExpiresAt);
  if (Number.isFinite(expiry)) return { project, changed: false };
  return {
    project: { ...project, guestExpiresAt: new Date(now + GUEST_PROJECT_TTL_MS).toISOString() },
    changed: true
  };
};

const api = { GUEST_PROJECT_TTL_MS, normalizeGuestProjectExpiry };
if (typeof module !== "undefined" && module.exports) module.exports = api;
if (typeof window !== "undefined") window.PWAGuestProjectExpiry = api;
