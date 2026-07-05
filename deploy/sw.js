/* BookinVIP - Service Worker KILL-SWITCH (senza reload -> niente loop).
   Il vecchio SW teneva in cache versioni obsolete. Questo NON fa caching e NON ricarica la
   pagina: si installa, svuota TUTTE le cache, si DISINSTALLA e basta. Al PROSSIMO refresh manuale
   dell'utente il sito arriva fresco dal server (e nessun SW si re-installa: index.html non lo registra). */
self.addEventListener('install', () => self.skipWaiting());

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.map((k) => caches.delete(k))))   // svuota ogni cache
      .then(() => self.registration.unregister())                        // rimuove il SW
      .catch(() => {})
  );
});

/* Nessun handler 'fetch': ogni richiesta va diretta alla rete. Nessun reload automatico. */
