// VeriFuse Service Worker — Shell precache strategy
const CACHE_NAME = "verifuse-shell-v4";

// Shell assets to precache (Vite-built paths handled at runtime)
const SHELL_ASSETS = [
  "/",
  "/dashboard",
  "/manifest.json",
  "/manifest.webmanifest",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      // Cache shell assets — ignore failures for individual assets
      return Promise.allSettled(
        SHELL_ASSETS.map((url) =>
          cache.add(url).catch((err) => {
            console.warn("[sw] Failed to cache:", url, err);
          })
        )
      );
    })
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((k) => k !== CACHE_NAME)
            .map((k) => caches.delete(k))
        )
      )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // Never cache API calls or auth requests
  if (
    url.pathname.startsWith("/api/") ||
    url.pathname.startsWith("/api/auth/")
  ) {
    return; // Fall through to network
  }

  // Network-first for navigation requests (always fresh HTML)
  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request).catch(() =>
        caches.match("/") // fallback to cached shell
      )
    );
    return;
  }

  // Cache-first for static assets (JS/CSS/images)
  if (
    url.pathname.match(/\.(js|css|png|svg|woff2?|ico)$/)
  ) {
    event.respondWith(
      caches.match(event.request).then(
        (cached) =>
          cached ||
          fetch(event.request).then((response) => {
            if (response.ok) {
              const clone = response.clone();
              caches
                .open(CACHE_NAME)
                .then((cache) => cache.put(event.request, clone));
            }
            return response;
          })
      )
    );
    return;
  }
});
