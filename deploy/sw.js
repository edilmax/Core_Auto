/* BookinVIP - Service Worker KILL-SWITCH.
   Il vecchio SW teneva in cache versioni obsolete della pagina (causa di messaggi vecchi anche
   dopo un deploy). Questo SW NON fa piu' caching: si installa, cancella TUTTE le cache, si
   DISINSTALLA e ricarica le schede aperte -> da qui in poi il sito e' SEMPRE fresco dal server. */
self.addEventListener('install', () => self.skipWaiting());

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.map((k) => caches.delete(k))))   // svuota ogni cache
      .then(() => self.registration.unregister())                        // rimuove il SW
      .then(() => self.clients.matchAll({ type: 'window' }))
      .then((clients) => clients.forEach((c) => c.navigate(c.url)))      // ricarica le schede -> fresco
      .catch(() => {})
  );
});

/* Finche' e' attivo (una sola volta), NON intercetta nulla: ogni richiesta va diretta alla rete. */
