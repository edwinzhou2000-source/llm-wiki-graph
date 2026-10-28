// v2 — network-first with cache fallback; old cache-first was the culprit
const CACHE = 'llm-wiki-kb-v2';
self.addEventListener('install', e => {
  // Activate immediately, don't wait for old tabs to close
  self.skipWaiting();
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(['/product-hub.html', '/graph-data.json', '/manifest.json']))
  );
});
self.addEventListener('activate', e => {
  // Delete old caches, take control of all clients immediately
  e.waitUntil(
    caches.keys().then(keys => Promise.all(
      keys.filter(k => k !== CACHE).map(k => caches.delete(k))
    ))
  );
  self.clients.claim();
});
self.addEventListener('fetch', e => {
  // Network-first: try network, fall back to cache (offline only)
  e.respondWith(
    fetch(e.request)
      .then(response => {
        // Cache successful responses for offline use
        const clone = response.clone();
        caches.open(CACHE).then(c => c.put(e.request, clone));
        return response;
      })
      .catch(() => caches.match(e.request))
  );
});
