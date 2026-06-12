{% load static %}// Ledger PWA service worker. Bumping CACHE invalidates old caches on activate.
const CACHE = 'ledger-pwa-v1';
// Precache the offline page AND the stylesheet it needs, so the fallback renders
// styled even on the very first offline navigation. {% templatetag openblock %} static {% templatetag closeblock %}
// resolves the hashed URL under ManifestStaticFilesStorage in production.
const PRECACHE = ['/offline/', '{% static "css/tailwind.css" %}'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

async function cacheFirst(request) {
  const cache = await caches.open(CACHE);
  const hit = await cache.match(request);
  if (hit) return hit;
  const res = await fetch(request);
  if (res && res.ok) cache.put(request, res.clone());
  return res;
}

async function networkFirstNav(request) {
  try {
    return await fetch(request);
  } catch (e) {
    const cache = await caches.open(CACHE);
    return (await cache.match('/offline/')) || Response.error();
  }
}

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;                       // writes -> network
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;        // cross-origin (fonts, CDN) -> network
  const p = url.pathname;
  if (p.startsWith('/api/') || p.startsWith('/admin/') || p === '/healthz/') return; // SSE/admin/health
  if (p.startsWith('/static/')) {                         // immutable hashed assets
    event.respondWith(cacheFirst(req));
    return;
  }
  if (req.mode === 'navigate') {                          // pages -> network-first + offline fallback
    event.respondWith(networkFirstNav(req));
  }
});
