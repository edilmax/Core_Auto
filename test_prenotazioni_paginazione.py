"""Collaudo PAGINAZIONE SERVER-SIDE di 'Le mie prenotazioni' (refactoring 2026-07-18).

Il taglio lo fa il DATABASE (fase58 `elenco_prenotazioni_pagina` con LIMIT/OFFSET +
`conta_prenotazioni` con COUNT): al client viaggia SOLO il sottoinsieme richiesto.
Invarianti difesi (richiesta esplicita del fondatore: "esattamente il numero di
record richiesti e non di piu'"):
  1. ESATTEZZA: ogni pagina porta al massimo `limit` righe; con 23 attive e limit 10
     le pagine sono 10/10/3, MAI una riga in piu';
  2. COMPLETEZZA: l'unione delle pagine == l'insieme intero, senza doppioni ne' buchi
     (ordine stabile: check_in DESC, rowid DESC);
  3. SEPARAZIONE: vista 'attive' e 'archivio' sono disgiunte e complete;
  4. CLAMP: limit ostile (0, -5, 999) viene riportato in 1..50; offset oltre la fine
     -> lista vuota senza errori; parametri-veleno sull'endpoint (page='abc',
     limit=-5, vista='<script>') -> MAI 5xx, default garbati;
  5. MULTI-ALLOGGIO: la pagina attraversa TUTTI gli alloggi dell'host in una sola
     query (niente N+1 per alloggio);
  6. le richieste 'su richiesta' non ancora approvate NON compaiono (sono uno stato
     del flusso servito da /api/host/richieste, non un blocco d'inventario).
"""
import hashlib
import hmac
import json
import shutil
import sqlite3
import tempfile
import time
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router, sweep_hold_una_passata

SEG = b"h" * 32
HK = {"X-Host-Key": "hk"}
AK = {"X-Admin-Key": "ak"}
WHSEC = "whsec_test"


class TestPaginazioneServerSide(unittest.TestCase):
    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, db_catalogo=f"{d}/c.db",
            db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_viral=f"{d}/v.db", db_messaggi=f"{d}/m.db", db_domanda=f"{d}/dom.db",
            db_garanzia=f"{d}/g.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/po.db",
            db_tassa_comunale=f"{d}/tc.db", file_referral=f"{d}/ref.json",
            commissione_bps=1500, stripe_webhook_secret=WHSEC))
        self.sis.concierge._link = lambda dati: "https://pay/" + str(dati.get("riferimento", ""))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        # DUE alloggi dello stesso host: la pagina deve attraversarli entrambi
        for slug in ("hotel-a", "hotel-b"):
            self.g("POST", "/api/host/pubblica", {"host_id": "demo", "slug": slug,
                   "titolo": slug.upper(), "citta": "Roma", "descrizione": "x",
                   "prezzo_notte_cents": 10000, "capacita": 2, "servizi": [],
                   "immagini": [], "tassa_pp_notte_cents": 0}, HK)
            self.g("POST", "/api/host/disponibilita_range", {"alloggio_id": slug,
                   "da": "2027-10-01", "a": "2027-11-30", "unita_totali": 30,
                   "prezzo_netto_cents": 10000}, HK)
        self._seq = 0

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

    def _prenota_paga(self, slug, ci, co):
        self._seq += 1
        _, q = self.g("POST", "/api/concierge/quote", {"alloggio_id": slug,
                      "check_in": ci, "check_out": co, "party": 2})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"],
                       "email": f"p{self._seq}@collaudo.invalid"})
        rif = b["riferimento"]
        payload = json.dumps({"type": "checkout.session.completed",
                              "data": {"object": {"metadata": {"riferimento": rif}}}})
        ts = str(int(time.time()))
        mac = hmac.new(WHSEC.encode(), f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()
        s, _ = self.r.gestisci("POST", "/api/payments/webhook", {}, payload,
                               {"Stripe-Signature": "t=%s,v1=%s" % (ts, mac)})
        self.assertEqual(s, 200)
        return rif

    def _semina(self, n_attive=23, n_archivio=7):
        """23 attive + 7 rimborsate, alternate sui 2 alloggi e su date DIVERSE
        (l'ordine per check_in e' quindi significativo)."""
        rifs = []
        for i in range(n_attive + n_archivio):
            slug = "hotel-a" if i % 2 == 0 else "hotel-b"
            giorno = 1 + i          # date tutte diverse -> ordine deterministico
            ci = "2027-10-%02d" % giorno
            co = "2027-10-%02d" % (giorno + 1)
            rifs.append((self._prenota_paga(slug, ci, co), slug, ci, co))
        for rif, slug, ci, co in rifs[:n_archivio]:      # le prime 7 -> rimborsate
            idem = self.sis.pagamenti_pendenti.info(rif)["idem_key"]
            s, _ = self.g("POST", "/api/admin/rimborso", {"alloggio_id": slug,
                          "check_in": ci, "check_out": co, "idem_key": idem}, AK)
            self.assertEqual(s, 200)
        return rifs

    # ── 1+2+5: esattezza, completezza, multi-alloggio (livello STORE fase58) ──
    def test_store_pagine_esatte_e_complete(self):
        self._semina()
        inv = self.sis.inventario
        alloggi = ["hotel-a", "hotel-b"]
        self.assertEqual(inv.conta_prenotazioni(alloggi=alloggi, vista="attive"), 23)
        self.assertEqual(inv.conta_prenotazioni(alloggi=alloggi, vista="archivio"), 7)
        viste = []
        for off, attesi in ((0, 10), (10, 10), (20, 3), (30, 0)):
            pag = inv.elenco_prenotazioni_pagina(alloggi=alloggi, vista="attive",
                                                 limit=10, offset=off)
            self.assertEqual(len(pag), attesi,
                             f"offset {off}: attese {attesi} righe ESATTE, avute {len(pag)}")
            viste.extend(p["idem_key"] for p in pag)
        # completezza: unione pagine == insieme intero, zero doppioni
        self.assertEqual(len(viste), 23)
        self.assertEqual(len(set(viste)), 23, "doppioni tra le pagine")
        # ordine: check_in DECRESCENTE attraverso le pagine
        date = [p["check_in"] for off in (0, 10, 20)
                for p in inv.elenco_prenotazioni_pagina(alloggi=alloggi, vista="attive",
                                                        limit=10, offset=off)]
        self.assertEqual(date, sorted(date, reverse=True), "ordine non decrescente")
        # multi-alloggio: nella prima pagina compaiono ENTRAMBI gli alloggi
        prima = inv.elenco_prenotazioni_pagina(alloggi=alloggi, vista="attive", limit=10)
        self.assertEqual({p["alloggio_id"] for p in prima}, {"hotel-a", "hotel-b"})
        # separazione: l'archivio non contiene chiavi della vista attiva
        arch = inv.elenco_prenotazioni_pagina(alloggi=alloggi, vista="archivio", limit=50)
        self.assertEqual(len(arch), 7)
        self.assertEqual(set(viste) & {p["idem_key"] for p in arch}, set())

    # ── 4: clamp e input ostili (store + endpoint) ─────────────────────────
    def test_clamp_e_veleni(self):
        self._semina(n_attive=5, n_archivio=0)
        inv = self.sis.inventario
        alloggi = ["hotel-a", "hotel-b"]
        self.assertEqual(len(inv.elenco_prenotazioni_pagina(alloggi=alloggi, limit=0)), 1,
                         "limit 0 -> clampato a 1 (mai 'tutto')")
        self.assertEqual(len(inv.elenco_prenotazioni_pagina(alloggi=alloggi, limit=-5)), 1)
        self.assertEqual(len(inv.elenco_prenotazioni_pagina(alloggi=alloggi, limit=999)), 5,
                         "limit enorme -> clampato a 50 (qui 5 esistenti)")
        self.assertEqual(inv.elenco_prenotazioni_pagina(alloggi=alloggi, offset=100), [])
        self.assertEqual(inv.elenco_prenotazioni_pagina(alloggi=[], limit=10), [])
        self.assertEqual(inv.conta_prenotazioni(alloggi=None, vista="attive"), 0)
        # endpoint coi veleni: mai 5xx, default garbati
        for q in ({"page": "abc", "limit": "-5", "vista": "<script>"},
                  {"page": "0", "limit": "0"}, {"page": "999999", "limit": "999"},
                  {"vista": "archivio", "page": "", "limit": None}):
            qq = {"host_id": "demo"}
            qq.update({k: v for k, v in q.items() if v is not None})
            s, d = self.g("GET", "/api/host/prenotazioni", None, HK, qq)
            self.assertEqual(s, 200, d)
            self.assertLessEqual(len(d["prenotazioni"]), 50)
            self.assertGreaterEqual(d["limit"], 1)
            self.assertLessEqual(d["limit"], 50)
            self.assertIn(d["vista"], ("attive", "archivio"))

    # ── 1 (endpoint): il payload porta ESATTAMENTE la pagina, mai di piu' ──
    def test_endpoint_pagina_esatta(self):
        self._semina()
        s, d = self.g("GET", "/api/host/prenotazioni", None, HK,
                      {"host_id": "demo", "page": "1", "limit": "10"})
        self.assertEqual(s, 200)
        self.assertEqual(len(d["prenotazioni"]), 10)     # esatti, non 23
        self.assertEqual(d["totale"], 23)
        self.assertEqual(d["pagine"], 3)
        self.assertEqual(d["totale_archivio"], 7)
        s, d3 = self.g("GET", "/api/host/prenotazioni", None, HK,
                       {"host_id": "demo", "page": "3", "limit": "10"})
        self.assertEqual(len(d3["prenotazioni"]), 3)     # ultima pagina parziale
        s, d9 = self.g("GET", "/api/host/prenotazioni", None, HK,
                       {"host_id": "demo", "page": "9", "limit": "10"})
        self.assertEqual(d9["prenotazioni"], [])          # oltre la fine: vuoto, non errore
        # vista archivio paginata
        s, da = self.g("GET", "/api/host/prenotazioni", None, HK,
                       {"host_id": "demo", "vista": "archivio", "page": "1", "limit": "5"})
        self.assertEqual(len(da["prenotazioni"]), 5)
        self.assertEqual(da["totale"], 7)
        self.assertEqual(da["pagine"], 2)
        self.assertTrue(all(p["archiviata"] for p in da["prenotazioni"]))

    # ── 6: una richiesta non approvata NON e' una prenotazione ─────────────
    def test_richiesta_non_approvata_non_in_lista(self):
        # alloggio 'su richiesta': il book crea 'in_attesa_host', nessun blocco inventario
        self.g("POST", "/api/host/pubblica", {"host_id": "demo", "slug": "sur",
               "titolo": "SR", "citta": "Roma", "descrizione": "x",
               "prezzo_notte_cents": 10000, "capacita": 2, "servizi": [], "immagini": [],
               "tassa_pp_notte_cents": 0, "modalita_prenotazione": "su_richiesta"}, HK)
        self.g("POST", "/api/host/disponibilita_range", {"alloggio_id": "sur",
               "da": "2027-10-01", "a": "2027-10-31", "unita_totali": 1,
               "prezzo_netto_cents": 10000}, HK)
        _, q = self.g("POST", "/api/concierge/quote", {"alloggio_id": "sur",
                      "check_in": "2027-10-05", "check_out": "2027-10-07", "party": 2})
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "sr@collaudo.invalid"})
        self.assertIn(s, (200, 201))
        self.assertEqual(b.get("stato"), "in_attesa_host", b)
        for vista in ("attive", "archivio"):
            s, d = self.g("GET", "/api/host/prenotazioni", None, HK,
                          {"host_id": "demo", "vista": vista, "limit": "50"})
            self.assertEqual(d["prenotazioni"], [],
                             f"la richiesta NON approvata e' comparsa in vista {vista}")
        # ma e' visibile dove deve: /api/host/richieste (stato del flusso)
        s, r = self.g("GET", "/api/host/richieste", None, HK, {"host_id": "demo"})
        self.assertEqual(len(r["richieste"]), 1)
        # SCADENZA senza approvazione: la richiesta esce dal flusso e finisce in
        # archivio con l'etichetta ONESTA 'scaduta' (non "rimborsata": nessuno ha
        # pagato, niente da rimborsare)
        con = sqlite3.connect(f"{self.dir}/p.db")
        with con:
            con.execute("UPDATE pendenti SET scadenza_ts=1 WHERE stato='in_attesa_host'")
        con.close()
        sweep_hold_una_passata(self.sis, self.r)
        s, r = self.g("GET", "/api/host/richieste", None, HK, {"host_id": "demo"})
        self.assertEqual(r["richieste"], [])
        s, d = self.g("GET", "/api/host/prenotazioni", None, HK,
                      {"host_id": "demo", "vista": "archivio", "limit": "50"})
        self.assertEqual([p["stato"] for p in d["prenotazioni"]], ["scaduta"])
        s, d = self.g("GET", "/api/host/prenotazioni", None, HK,
                      {"host_id": "demo", "vista": "attive", "limit": "50"})
        self.assertEqual(d["prenotazioni"], [],
                         "la richiesta scaduta non deve riapparire tra le attive")


if __name__ == "__main__":
    unittest.main()
