// Service worker for SEÑAL — offline-capable daily reader.
// Shell is cache-first (instant loads); feed.json is network-first (fresh when
// online, last-known when offline). Bump CACHE when the shell changes.
const CACHE = 'senal-v1';
const SHELL = ['./', './index.html', './icon.svg', './manifest.webmanifest'];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);

  // Only handle our own origin; let cross-origin (fonts, MyMemory, images) pass through.
  if (url.origin !== self.location.origin) return;

  // feed.json: network-first so content stays fresh, fall back to cache offline.
  if (url.pathname.endsWith('/feed.json')) {
    event.respondWith(
      fetch(request)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(request, copy));
          return res;
        })
        .catch(() => caches.match(request))
    );
    return;
  }

  // Everything else (shell): cache-first, fall back to network.
  event.respondWith(
    caches.match(request).then((cached) => cached || fetch(request))
  );
});
