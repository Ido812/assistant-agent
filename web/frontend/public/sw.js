/**
 * Service Worker — Enables PWA features.
 *
 * This caches the app shell (HTML, CSS, JS) so the app loads instantly.
 * API calls (/api/*) always go to the network — never cached.
 */

const CACHE_NAME = "assistant-agent-v1";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(["/", "/index.html"]))
  );
});

self.addEventListener("fetch", (event) => {
  // Never cache API calls — always fetch fresh data
  if (event.request.method !== "GET" || event.request.url.includes("/api/")) {
    return;
  }
  event.respondWith(
    caches
      .match(event.request)
      .then((cached) => cached || fetch(event.request))
  );
});
