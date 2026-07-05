/* BookinVIP - Service Worker. PAGINE/navigazioni: RETE PRIMA (il sito mostra SEMPRE l'ultima
   versione, niente piu' contenuti vecchi dopo un deploy); asset statici: cache; API: rete. */
const CACHE = 'bookinvip-v3';   // bump -> invalida la cache vecchia su tutti i dispositivi al prossimo accesso
const SHELL = ['/', '/index.html', '/host.html', '/manifest.json', '/icon.svg', '/logo.svg'];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL).catch(() => {})).then(() => self.skipWaiting())
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
  const req = e.request;
  const url = new URL(req.url);

  // API: rete prima, fallback offline (mai dati stantii sulle prenotazioni)
  if (url.pathname.startsWith('/api/')) {
    e.respondWith(
      fetch(req).catch(() =>
        new Response(JSON.stringify({ errore: 'offline' }),
          { headers: { 'Content-Type': 'application/json' } }))
    );
    return;
  }

  // PAGINE (HTML/navigazioni): RETE PRIMA -> il sito riflette subito ogni deploy;
  // aggiorna la cache; offline -> cache.
  const accept = req.headers.get('accept') || '';
  if (req.mode === 'navigate' || accept.includes('text/html')) {
    e.respondWith(
      fetch(req).then((r) => {
        const copia = r.clone();
        caches.open(CACHE).then((c) => c.put(req, copia)).catch(() => {});
        return r;
      }).catch(() => caches.match(req).then((r) => r || caches.match('/')))
    );
    return;
  }

  // Asset statici (icone, logo, manifest): cache prima, poi rete (e aggiorna la cache).
  e.respondWith(
    caches.match(req).then((r) => r || fetch(req).then((resp) => {
      const copia = resp.clone();
      caches.open(CACHE).then((c) => c.put(req, copia)).catch(() => {});
      return resp;
    }))
  );
});
