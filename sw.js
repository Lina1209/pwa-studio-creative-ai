const CACHE_NAME = "pwa-studio-shell-v36";
const CORE_ASSETS = [
  "./",
  "./index.html",
  "./styles.css",
  "./app.js",
  "./movie-storage-guard.js",
  "./character-cloud-restore.js?v=20261128-1",
  "./character-restore-review-ui.js?v=20261128-1",
  "./character-owner-coordination-lock.js?v=20261128-1",
  "./profile-avatar-catalog.js?v=20261127-1",
  "./audio-lab.js",
  "./supabase-config.js",
  "./manifest.webmanifest",
  "./assets/icon.svg",
  "./site-cache-tools.js?v=20261128-1"
];

self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(CORE_ASSETS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys
          .filter(key => key.startsWith("pwa-studio-shell-") && key !== CACHE_NAME)
          .map(key => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", event => {
  const request = event.request;
  const url = new URL(request.url);

  if (request.method !== "GET" || url.origin !== self.location.origin) return;

  const isShellAsset = request.mode === "navigate" ||
    ["/index.html", "/app.js", "/movie-storage-guard.js", "/character-cloud-restore.js", "/character-restore-review-ui.js", "/character-owner-coordination-lock.js", "/profile-avatar-catalog.js", "/audio-lab.js", "/styles.css", "/supabase-config.js", "/site-cache-tools.js", "/manifest.webmanifest", "/assets/icon.svg"].some(asset => url.pathname.endsWith(asset));

  if (isShellAsset) {
    event.respondWith(
      fetch(request)
        .then(response => {
          if (response && response.ok && response.type === "basic") {
            const copy = response.clone();
            caches.open(CACHE_NAME).then(cache => cache.put(request, copy));
          }
          return response;
        })
        .catch(async () => {
          const cache = await caches.open(CACHE_NAME);
          // Shell assets are precached without cache-busting query strings.
          const cached = await cache.match(request, { ignoreSearch: true });
          const appIndex = new URL("./index.html", self.registration.scope).href;
          return cached || (request.mode === "navigate" ? (await cache.match(appIndex)) : null) || Response.error();
        })
    );
    return;
  }

  // Everything outside the explicit app-shell allowlist is network-only.
  // In particular, never accumulate generated images, audio, video, or user files
  // in Cache Storage: large media can exhaust device storage and make the PWA sluggish.
  return;
});
