// AEC Platform service worker — offline shell only.
//
// Caches the minimal set of routes + assets needed to show *something*
// when a field user opens the app on a flaky 3G connection or before
// the captive-portal handshake completes:
//
//   * `/` shell (will redirect to /login or /inbox once auth resolves)
//   * `/login` — the entry point users hit when their session expires
//   * `/offline` — a static "you're offline" fallback
//   * the manifest + icons so the install prompt + app-switcher
//     thumbnails render
//
// Strategy:
//   * Same-origin navigations: network-first, fall back to the cached
//     /offline page on failure. We deliberately do NOT cache authed
//     pages — those depend on per-request cookies and a stale cache
//     would show another tenant's data after a logout/login flip.
//   * Static assets (`/_next/static/*`, `/icons/*`): cache-first.
//     These are content-hashed by Next so the cache key never lies.
//   * API calls (`/api/v1/*`): pass through. We don't want to serve a
//     stale POST response or a cached 401 after a session refresh.
//
// Bump SW_VERSION to force every client to drop its old cache on the
// next page load.

const SW_VERSION = "v1";
const SHELL_CACHE = `aec-shell-${SW_VERSION}`;
const STATIC_CACHE = `aec-static-${SW_VERSION}`;

const SHELL_URLS = [
  "/offline",
  "/manifest.webmanifest",
  "/icons/icon-192.svg",
  "/icons/icon-512.svg",
  "/icons/icon-maskable.svg",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL_URLS)),
  );
  // Activate the new SW immediately on the next navigation instead of
  // waiting for every tab to close — the only reliable way to roll a
  // SW fix to users without nagging them to "Reload All Tabs".
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys
          .filter((k) => k !== SHELL_CACHE && k !== STATIC_CACHE)
          .map((k) => caches.delete(k)),
      );
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // Never cache API traffic — auth-sensitive + the freshness window is
  // the whole point.
  if (url.pathname.startsWith("/api/")) return;

  // Static Next assets — cache-first, content-hashed by the build so
  // collisions are impossible.
  if (
    url.pathname.startsWith("/_next/static/") ||
    url.pathname.startsWith("/icons/")
  ) {
    event.respondWith(cacheFirst(STATIC_CACHE, req));
    return;
  }

  // HTML navigations — network-first, fall back to /offline on failure.
  if (req.mode === "navigate") {
    event.respondWith(navigationWithOfflineFallback(req));
    return;
  }
});


async function cacheFirst(cacheName, req) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(req);
  if (cached) return cached;
  try {
    const fresh = await fetch(req);
    if (fresh.ok) cache.put(req, fresh.clone());
    return fresh;
  } catch (err) {
    return cached || Response.error();
  }
}


async function navigationWithOfflineFallback(req) {
  try {
    return await fetch(req);
  } catch {
    const cache = await caches.open(SHELL_CACHE);
    const offline = await cache.match("/offline");
    return offline || new Response("Offline", { status: 503 });
  }
}
