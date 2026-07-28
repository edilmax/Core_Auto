# -*- coding: utf-8 -*-
"""GUARDIE DI SICUREZZA — revisione OSTILE del router (2026-07-28).

Tesi attaccata: «nessun input utente puo' produrre 500, scalata di privilegi, XSS o accesso a
dati altrui». Tre difetti VERI trovati e corretti alla radice; qui le guardie che li bloccano.
Ogni guardia e' stata VISTA ROSSA rimettendo il codice difettoso (dettaglio nel report).

  1) SCALATA DI PRIVILEGI — `AZIONI_SOLO_ADMIN` (fase192) elenca sei azioni riservate al ruolo
     'admin', ma il router chiamava `_puo_azione` solo per DUE (rimborso, storno_penale).
     Un operatore 'supporto' otteneva **200 OK** su `/api/admin/cancella_attivita` (cancella un
     host da OGNI archivio), sospendeva qualsiasi annuncio (`alloggio_stato`) e arbitrava la
     spartizione dei soldi in garanzia (`controversia/risolvi`).
     -> fase83_server: gate di ruolo aggiunto ai tre handler.

  2) RISPOSTA UCCISA DA UN CARATTERE — `POST /api/domanda` (pubblica, senza auth) con
     `{"citta": "Rom\\ud800a"}`: il router usava la citta' GREZZA per `conta()`, per il token
     del credito e per il `messaggio`; `json.dumps(...).encode("utf-8")` alzava
     UnicodeEncodeError PRIMA di `send_response` -> il server chiudeva la connessione **senza
     spedire nulla** (verificato su socket reale; dietro nginx = 502).
     -> due correzioni: la citta' si ripulisce UNA volta nel router (`pulisci_testo`, stesso
        metro del gestore) e `corpo_json_bytes` garantisce che una risposta parta SEMPRE.
     Stessa famiglia: `Content-Length: abc` e corpo con byte non-UTF8 alzavano
     ValueError/UnicodeDecodeError in `do_POST` -> connessione chiusa senza risposta.

  3) ESCAPING ASIMMETRICO NEL JSON-LD DEL VIDEO — il nome citta' e' dato UTENTE (il registro
     landing include le citta' con inventario reale). Il blocco VideoObject usava
     `.replace("</", "<\\/")` invece di `_jsonld` (che neutralizza < > &): una citta' come
     `Zz<!--<script>` finiva grezza nel blocco e portava il parser HTML nello stato
     'script data double escaped', dove il `</script>` successivo NON chiude piu' l'elemento.
     -> fase97_inbound_seo: un solo metro di escaping per tutti i blocchi JSON-LD.
"""
import json
import shutil
import tempfile
import unittest

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import (corpo_json_bytes, corpo_richiesta_testo, crea_router,
                           lunghezza_corpo)
from fase97_inbound_seo import citta_da_slug, genera_landing_host, registro_citta, slug_citta
from fase192_admin_accounts import AZIONI_SOLO_ADMIN

IP = {"X-Forwarded-For": "203.0.113.5"}
SURROGATO = "\ud800"          # meta' di coppia UTF-16: non codificabile in UTF-8


# ─────────────────────────────────────────────────────────────────────────────
# 1) SCALATA DI PRIVILEGI: il ruolo 'supporto' contro le azioni SOLO-ADMIN
# ─────────────────────────────────────────────────────────────────────────────
class TestRuoloSupportoNonScala(unittest.TestCase):
    """Un operatore 'supporto' NON deve poter compiere nessuna azione di AZIONI_SOLO_ADMIN.
    Osservabile FORTE: stato 403 **e** codice d'errore di RUOLO (non un 422 di validazione,
    che vorrebbe dire «e' entrato, semplicemente non gli e' piaciuto il corpo»)."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        # bunker NON configurato di proposito: isola il gate di RUOLO dal gate BUNKER.
        # E' anche lo scenario peggiore reale (deploy senza super-admin): li' il ruolo e'
        # l'UNICA difesa rimasta.
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"h" * 32, db_catalogo=self.d + "/c.db",
            db_inventario=self.d + "/i.db", db_garanzia=self.d + "/g.db",
            db_payout=self.d + "/p.db", db_finanza=self.d + "/f.db",
            db_admin_accounts=self.d + "/a.db"))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak", base_url="https://x")
        self.sis.admin_accounts.crea("sup@x.it", "password123", "supporto")
        self.sis.admin_accounts.crea("boss@x.it", "password123", "admin")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _h(self, email, ruolo):
        return {"X-Admin-Op": self.r._firma_op(email, ruolo), **IP}

    # (azione, metodo, rotta, corpo) — corpi ben formati: se passa il gate di ruolo, ENTRA
    AZIONI = (
        ("rimborso", "POST", "/api/admin/rimborso",
         {"alloggio_id": "c", "check_in": "2027-12-10", "check_out": "2027-12-12",
          "idem_key": "k1"}),
        ("storno_penale", "POST", "/api/admin/storno_penale", {"riferimento": "r_x"}),
        ("alloggio_stato", "POST", "/api/admin/alloggio_stato",
         {"slug": "x", "stato": "sospeso"}),
        ("cancella_attivita", "POST", "/api/admin/cancella_attivita", {"host_id": "h_x"}),
        ("controversia_risolvi", "POST", "/api/admin/controversia/risolvi",
         {"riferimento": "r_x", "percentuale_ospite": 100}),
    )

    def test_ogni_azione_solo_admin_e_coperta_da_una_rotta(self):
        """La tabella dei permessi non deve poter mentire: se domani si aggiunge un'azione a
        AZIONI_SOLO_ADMIN senza rotta qui, questo test lo dice (niente permesso decorativo)."""
        coperte = {a for a, _, _, _ in self.AZIONI} | {"blocco_globale"}  # bunker-only
        self.assertEqual(set(AZIONI_SOLO_ADMIN), coperte,
                         "azione riservata senza guardia: aggiungila (rotta o eccezione motivata)")

    def test_supporto_respinto_su_tutte_le_azioni_solo_admin(self):
        for azione, m, rotta, corpo in self.AZIONI:
            with self.subTest(azione=azione):
                s, c = self.r.gestisci(m, rotta, {}, json.dumps(corpo),
                                       self._h("sup@x.it", "supporto"))
                self.assertEqual(s, 403, "%s: 'supporto' e' ENTRATO (stato %s, %s)"
                                 % (azione, s, c))
                self.assertEqual(c.get("errore"), "permesso_negato_ruolo",
                                 "%s: 403 per il motivo sbagliato -> %s" % (azione, c))

    def test_supporto_non_cancella_davvero_un_host(self):
        """Osservabile d'EFFETTO (non solo di stato): l'erasure non deve nemmeno partire."""
        s, c = self.r.gestisci("POST", "/api/admin/cancella_attivita", {},
                               json.dumps({"host_id": "h_x"}), self._h("sup@x.it", "supporto"))
        self.assertEqual(s, 403, c)
        self.assertNotIn("cancellati", c, "l'erasure e' stata ESEGUITA da un 'supporto'")

    def test_admin_vero_passa_il_gate_di_ruolo(self):
        """Controprova (il test non e' vacuo): il ruolo 'admin' non prende MAI il 403 di ruolo."""
        for azione, m, rotta, corpo in self.AZIONI:
            with self.subTest(azione=azione):
                s, c = self.r.gestisci(m, rotta, {}, json.dumps(corpo),
                                       self._h("boss@x.it", "admin"))
                self.assertNotEqual(c.get("errore"), "permesso_negato_ruolo",
                                    "%s: il ruolo 'admin' e' stato bloccato" % azione)

    def test_root_key_passa_il_gate_di_ruolo(self):
        """La ADMIN_KEY root resta piena potenza (non ci si chiude fuori da soli)."""
        for azione, m, rotta, corpo in self.AZIONI:
            with self.subTest(azione=azione):
                s, c = self.r.gestisci(m, rotta, {}, json.dumps(corpo),
                                       {"X-Admin-Key": "ak", **IP})
                self.assertNotEqual(c.get("errore"), "permesso_negato_ruolo",
                                    "%s: la chiave root e' stata bloccata" % azione)


# ─────────────────────────────────────────────────────────────────────────────
# 2) NESSUN INPUT PUO' UCCIDERE LA RISPOSTA
# ─────────────────────────────────────────────────────────────────────────────
class TestRispostaSempreSpedibile(unittest.TestCase):
    """Le tre funzioni PURE che stanno fra i byte del client e i byte della risposta.
    Sono il punto in cui il difetto uccideva la connessione: qui non possono piu' alzare."""

    def test_corpo_json_bytes_sopravvive_ai_surrogati(self):
        crudo = {"ok": True, "messaggio": "Rom" + SURROGATO + "a"}
        # la vecchia riga era esattamente questa, e ALZAVA:
        with self.assertRaises(UnicodeEncodeError):
            json.dumps(crudo, ensure_ascii=False).encode("utf-8")
        dati = corpo_json_bytes(crudo)            # non deve alzare
        self.assertIsInstance(dati, bytes)
        rientro = json.loads(dati.decode("utf-8"))   # e deve restare JSON VALIDO
        self.assertIs(rientro["ok"], True)
        self.assertTrue(rientro["messaggio"].startswith("Rom"))

    def test_corpo_json_bytes_non_altera_il_caso_normale(self):
        """Nessuna regressione sui corpi sani: byte identici a prima, accenti compresi."""
        for corpo in ({"a": 1}, {"citta": "Zürich", "n": None},
                      {"lista": [1, 2, {"x": "città 日本"}]}, {"vuoto": ""}):
            self.assertEqual(corpo_json_bytes(corpo),
                             json.dumps(corpo, ensure_ascii=False).encode("utf-8"))

    def test_lunghezza_corpo_mai_eccezione(self):
        for valore, atteso in (("abc", 0), ("", 0), (None, 0), ("-1", 0), ("1e3", 0),
                               ("12", 12), (7, 7), ("  9 ", 9), ("0", 0),
                               ("99999999999999999999", 99999999999999999999)):
            self.assertEqual(lunghezza_corpo(valore), atteso, "Content-Length %r" % (valore,))

    def test_corpo_richiesta_testo_mai_eccezione(self):
        with self.assertRaises(UnicodeDecodeError):      # la vecchia riga alzava
            b"\xff\xfe{}".decode("utf-8")
        self.assertIsInstance(corpo_richiesta_testo(b"\xff\xfe{}"), str)
        self.assertEqual(corpo_richiesta_testo(b'{"a":1}'), '{"a":1}')
        self.assertEqual(corpo_richiesta_testo(None), "")


class TestDomandaCittaVelenosa(unittest.TestCase):
    """`POST /api/domanda` e' PUBBLICA e senza auth: e' la porta d'ingresso piu' esposta."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"h" * 32, db_domanda=self.d + "/d.db",
            db_catalogo=self.d + "/c.db", db_inventario=self.d + "/i.db"))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak", base_url="https://x")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def post(self, corpo):
        return self.r.gestisci("POST", "/api/domanda", {}, json.dumps(corpo), dict(IP))

    def test_citta_con_surrogato_risposta_spedibile(self):
        s, c = self.post({"email": "a@b.it", "citta": "Rom" + SURROGATO + "a"})
        self.assertIn(s, (201, 422), c)
        # L'OSSERVABILE VERO: la risposta deve poter uscire dal socket. Con la citta' grezza
        # questa riga alzava UnicodeEncodeError e il client non riceveva NIENTE.
        json.dumps(c, ensure_ascii=False).encode("utf-8")

    def test_credito_e_archivio_dicono_la_stessa_citta(self):
        """Divergenza trovata insieme al crash: `registra` archiviava la citta' RIPULITA
        mentre il credito veniva firmato su quella GREZZA -> due verita' diverse."""
        s, c = self.post({"email": "a@b.it", "citta": "Rom" + SURROGATO + "a"})
        self.assertEqual(s, 201, c)
        self.assertNotIn(SURROGATO, json.dumps(c, ensure_ascii=False),
                         "il surrogato e' uscito nella risposta/nel token")
        self.assertEqual(self.sis.domanda.conta("Roma"), 1,
                         "la citta' archiviata non e' quella per cui e' stato emesso il credito")

    def test_citta_sana_resta_intatta(self):
        """Controprova: la ripulitura non deve toccare le citta' vere (accenti compresi)."""
        s, c = self.post({"email": "b@b.it", "citta": "Zürich"})
        self.assertEqual(s, 201, c)
        self.assertEqual(self.sis.domanda.conta("zürich"), 1)


# ─────────────────────────────────────────────────────────────────────────────
# 3) JSON-LD DEL VIDEO: nessun markup utente esce grezzo
# ─────────────────────────────────────────────────────────────────────────────
class TestLandingVideoJsonLd(unittest.TestCase):
    """Il nome citta' arriva dall'inventario (scritto dagli host) tramite `registro_citta`:
    `citta_da_slug` lo restituisce IDENTICO, quindi finisce nella pagina. Nessun blocco
    JSON-LD deve lasciarlo passare grezzo, con o senza spot video."""

    OSTILI = ("Zzq<img src=x onerror=alert(1)>",
              "Zzw</script><script>alert(1)</script>",
              "Zze<!--<script>",
              "Zzy</SCRIPT ><svg onload=alert(1)>")

    def test_citta_ostile_arriva_davvero_alla_landing(self):
        """Il test non e' vacuo: la premessa (dato utente -> pagina) e' vera."""
        for c in self.OSTILI:
            with self.subTest(citta=c):
                reg = registro_citta([c])
                self.assertEqual(citta_da_slug(slug_citta(c), reg), c)

    def _pagina(self, citta, con_video):
        s = slug_citta(citta)
        return genera_landing_host(
            citta, lingua="it", base_url="https://x",
            video_url=("/video/%s.mp4" % s) if con_video else "",
            video_poster=("/video/%s.jpg" % s) if con_video else "",
            video_data="2026-01-01" if con_video else "")

    def test_nessun_frammento_grezzo_nella_pagina(self):
        for citta in self.OSTILI:
            for con_video in (False, True):
                with self.subTest(citta=citta, video=con_video):
                    h = self._pagina(citta, con_video)
                    for frammento in ("<img src=x", "<svg onload", "<!--<script>",
                                      "</script><script>", "</SCRIPT "):
                        self.assertNotIn(frammento, h,
                                         "markup utente GREZZO nella pagina: %r" % frammento)

    def test_gli_script_restano_bilanciati(self):
        """Osservabile strutturale: ogni <script> aperto ha il suo </script>. Se il dato utente
        introduce un `<script` in piu' dentro il JSON-LD, il parser HTML entra in
        'script data double escaped' e il `</script>` successivo non chiude piu' nulla."""
        for citta in self.OSTILI:
            for con_video in (False, True):
                with self.subTest(citta=citta, video=con_video):
                    h = self._pagina(citta, con_video)
                    self.assertEqual(h.count("<script"), h.count("</script>"),
                                     "tag <script> sbilanciati: il parser e' pilotato dall'utente")

    def test_il_video_compare_davvero(self):
        """Controprova: senza questa, i due test sopra passerebbero anche a video sparito."""
        h = self._pagina("Roma", True)
        self.assertIn("VideoObject", h)
        self.assertIn('property="og:video"', h)
        self.assertIn("/video/roma.mp4", h)


if __name__ == "__main__":
    unittest.main(verbosity=2)
