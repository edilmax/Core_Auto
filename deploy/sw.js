/* Casa VIP - Service Worker (PWA offline + installabile, zero dipendenze) */
const CACHE = 'casavip-v1';
const SHELL = ['/', '/index.html', '/host.html', '/manifest.json', '/icon.svg'];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  // API: rete prima, con fallback offline (mai dati stantii sulle prenotazioni)
  if (url.pathname.startsWith('/api/')) {
    e.respondWith(
      fetch(e.request).catch(() =>
        new Response(JSON.stringify({ errore: 'offline' }),
          { headers: { 'Content-Type': 'application/json' } }))
    );
    return;
  }
  // shell statico: cache prima, poi rete
  e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request)));
});
