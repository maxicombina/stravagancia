/* Garage service worker {{ version }}. Caches only public static files and the offline page;
   never stores pages with personal data, POST responses, fragments, photos or exports. */
'use strict';
const CACHE = 'garage-{{ version }}';
const OFFLINE = {{ offline_url|safe }};
const STATIC_PREFIX = {{ static_prefix|safe }};
const ASSETS = {{ assets|safe }};

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE)
    .then(cache => Promise.all([cache.addAll(ASSETS), cache.add(new Request(OFFLINE, { credentials: 'omit' }))]))
    .then(() => self.skipWaiting()));
});

self.addEventListener('activate', event => {
  event.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(key => key.startsWith('garage-') && key !== CACHE).map(key => caches.delete(key))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  // Downloads and private photos go straight to the network (iOS standalone needs it).
  if (url.pathname.startsWith('/garage/export/') || url.pathname.startsWith('/garage/photos/')) return;
  if (request.mode === 'navigate') {
    // Network only for pages; the cached offline page is the sole fallback.
    event.respondWith(fetch(request).catch(() => caches.match(OFFLINE, { ignoreSearch: true, ignoreVary: true })));
    return;
  }
  if (url.pathname.startsWith(STATIC_PREFIX)) {
    // ?v= URLs never change content: cache first, store once.
    event.respondWith(caches.open(CACHE).then(async cache => {
      const cached = await cache.match(request);
      if (cached) return cached;
      const response = await fetch(request);
      if (response.ok && response.type === 'basic') event.waitUntil(cache.put(request, response.clone()));
      return response;
    }));
  }
});
