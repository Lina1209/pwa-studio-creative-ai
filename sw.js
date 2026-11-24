const CACHE_NAME = "pwa-studio-shell-v16";
const CORE_ASSETS = [
  "./",
  "./index.html",
  "./styles.css",
  "./supabase-config.js",
  "./movie-cloud-context.js?v=20261124-1",
  "./movie-cloud-operations.js?v=20261124-2",
  "./movie-version-history.js?v=20261124-1",
  "./movie-storage-guard.js?v=20261124-1",
  "./movie-guest-expiry.js?v=20261124-1",
  "./movie-tombstone-storage.js?v=20261124-1",
  "./movie-id.js?v=20261124-1",
  "./app.js?v=20261124-2",
  "./audio-lab.js?v=20261121-1",
  "./manifest.webmanifest",
  "./assets/icon.svg"
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
    ["/index.html", "/app.js", "/audio-lab.js", "/styles.css", "/supabase-config.js", "/movie-cloud-context.js", "/movie-cloud-operations.js", "/movie-version-history.js", "/movie-storage-guard.js", "/movie-guest-expiry.js", "/movie-tombstone-storage.js", "/movie-id.js", "/manifest.webmanifest"].some(asset => url.pathname.endsWith(asset));

  if (isShellAsset) {
    event.respondWith(
      fetch(request)
        .then(response => {
          if (response && response.ok && response.type === "basic") {
            const copy = response.clone();
            event.waitUntil(
              caches.open(CACHE_NAME)
                .then(cache => cache.put(request, copy))
                .catch(() => {})
            );
          }
          return response;
        })
        .catch(async () => {
          const cached = await caches.match(request);
          return cached || (request.mode === "navigate" ? (await caches.match("./index.html")) : null) || Response.error();
        })
    );
    return;
  }

  event.respondWith(
    caches.match(request).then(cached => {
      if (cached) return cached;
      return fetch(request).then(response => {
        if (response && response.ok && response.type === "basic") {
          const copy = response.clone();
          event.waitUntil(
            caches.open(CACHE_NAME)
              .then(cache => cache.put(request, copy))
              .catch(() => {})
          );
        }
        return response;
      });
    })
  );
});
