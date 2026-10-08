"""D2 del Compito 52 (busta 6 di Claude, confermato da GML il 6/10/2026): LE PROVE FOTO DI UNA
CONTROVERSIA ERANO PUBBLICHE.

`_voucher_prova` salva la foto che l'ospite carica come prova nella STESSA cartella delle foto
degli annunci, e `_serve_upload` la dava a CHIUNQUE avesse l'URL, con
«Cache-Control: public, max-age=31536000»: un anno in ogni memoria intermedia, revoca
impossibile. L'URL vive nella chat, nei registri di nginx, nella cronologia del browser. Chi perde:
l'ospite che carica una prova (documenti, danni, persone nelle foto).

IL CONTRATTO che queste prove fissano (prima della riparazione, D20):
  - una prova si apre SOLO con un link firmato e a scadenza: `/uploads/<nome>?t=<gettone>`, dove il
    gettone e' firmato dal segreto del sistema (`firma.codifica`) col contenuto
    {"tipo": "prova_foto", "nome": <nome>, "exp": <istante>}; senza, con un gettone di un'altra
    prova, scaduto, manomesso, di un altro tipo (un voucher) o non ASCII -> 403, mai 500;
  - il link firmato lo ricevono, dentro la chat, i tre che la chat la leggono: l'ospite (voucher),
    l'host della prenotazione, l'arbitro; e la risposta e' «private, no-store»;
  - la firma si da' solo per le prove DI QUELLA prenotazione: un ospite che cita in chat la prova
    di un altro non ottiene un link che la apre;
  - le foto degli annunci restano pubbliche come prima, ANCHE se qualcuno le cita in chat con la
    forma di una prova (altrimenti un finto messaggio spegnerebbe le foto di un concorrente);
  - le prove caricate PRIMA della riparazione (nessun proprietario registrato, citate in chat
    dall'ospite come prova) diventano private anche loro;
  - i tre disegnatori di link (pagina del voucher, admin.html, host.html) tengono la firma
    attaccata al link.
Sistema vero, server HTTP vero in un thread, archivi su file temporanei, nessuna rete.
"""
from __future__ import annotations

import base64
import datetime
import http.client
import json
import os
import re
import secrets
import shutil
import socket
import tempfile
import threading
import time
import unittest
from urllib.parse import quote

import fase83_server
from fase57_vetrina import SchedaAlloggio
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router, pagina_voucher_html

SEGRETO = b"P" * 32
RADICE = os.path.dirname(os.path.abspath(__file__))
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00" * 40
PREFISSO = fase83_server._PREFISSO_PROVA
CACHE_ANNUNCI = "public, max-age=31536000"


def _porta_libera():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class TestLeProveFotoSonoPrivate(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._env_prec = {k: os.environ.get(k) for k in ("MARCA_TEMPORALE", "UPLOAD_DIR",
                                                         "PAGE_GATE")}
        cls.dir = tempfile.mkdtemp()
        os.environ["MARCA_TEMPORALE"] = "0"          # niente marca temporale in rete
        os.environ["UPLOAD_DIR"] = cls.dir + "/uploads"
        os.environ.pop("PAGE_GATE", None)
        d = cls.dir
        cls.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEGRETO, db_catalogo=d + "/c.db",
            db_inventario=d + "/i.db", db_registro_host=d + "/r.db", db_pendenti=d + "/p.db",
            db_payout=d + "/y.db", db_garanzia=d + "/g.db", db_messaggi=d + "/m.db",
            db_domanda=d + "/dom.db", db_viral=d + "/v.db", file_referral=d + "/ref.json"))
        cls.r = crea_router(cls.sis, host_key="hk", admin_key="ak")
        cls._prepara()
        cls.porta = _porta_libera()
        threading.Thread(
            target=fase83_server.servi,
            kwargs=dict(sistema=cls.sis, host="127.0.0.1", porta=cls.porta,
                        cartella_statica=os.path.join(RADICE, "deploy"),
                        host_key="hk", admin_key="ak", base_url="https://bookinvip.com"),
            daemon=True).start()
        for _ in range(300):
            try:
                if cls._http("GET", "/api/health/live")[0] == 200:
                    break
            except Exception:
                pass
            time.sleep(0.02)

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._env_prec.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(cls.dir, ignore_errors=True)

    # ── dati veri: due host, due annunci, due prenotazioni PAGATE, una prova a testa ──
    @classmethod
    def _g(cls, m, p, b=None, h=None, q=None):
        return cls.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

    @classmethod
    def _prenota_pagata(cls, slug, hid):
        oggi = datetime.date.today()
        ci = (oggi + datetime.timedelta(days=20)).isoformat()
        co = (oggi + datetime.timedelta(days=22)).isoformat()
        for g in (ci, (oggi + datetime.timedelta(days=21)).isoformat()):
            cls.sis.inventario.imposta_disponibilita(slug, g, unita_totali=1,
                                                     prezzo_netto_cents=10000)
        s, q = cls._g("POST", "/api/concierge/quote",
                      {"alloggio_id": slug, "check_in": ci, "check_out": co, "party": 2})
        assert s == 200, (s, q)
        s, b = cls._g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": slug + "@ospite.it"})
        assert s == 201 and b.get("voucher_token"), (s, b)
        rif = b["riferimento"]
        pp = cls.sis.pagamenti_pendenti
        if pp.info(rif) is None:
            assert pp.registra(rif, alloggio_id=slug, check_in=ci, check_out=co, host_id=hid)
        pp.conferma(rif)
        assert pp.info(rif).get("stato") == "pagato", pp.info(rif)
        return b["voucher_token"], rif

    @classmethod
    def _prova(cls, voucher):
        s, c = cls._g("POST", "/api/voucher/prova", {
            "voucher_token": voucher, "image_base64": base64.b64encode(PNG).decode("ascii")})
        assert s == 201, (s, c)
        return c["url"].rsplit("/", 1)[1]

    @classmethod
    def _prepara(cls):
        reg = cls.sis.registro_host
        a = reg.registra("a@host.it", "password-a-1", accetta_termini=True)
        b = reg.registra("b@host.it", "password-b-1", accetta_termini=True)
        assert a.ok and b.ok
        cls.hid_a, cls.tok_a, cls.hid_b = a.host_id, a.token, b.host_id
        updir = os.environ["UPLOAD_DIR"]
        os.makedirs(updir, exist_ok=True)
        # UNA FOTO D'ANNUNCIO NATA PRIMA DELLA TABELLA DEI PROPRIETARI: e' sul disco, l'annuncio
        # la cita, nessuna riga la registra (come in produzione per i file vecchi).
        cls.foto_vecchia = secrets.token_hex(16) + ".png"
        with open(os.path.join(updir, cls.foto_vecchia), "wb") as f:
            f.write(PNG)
        for hid, slug in ((cls.hid_a, "casa-a"), (cls.hid_b, "casa-b")):
            cls.sis.catalogo.pubblica(
                SchedaAlloggio(host_id=hid, slug=slug, titolo="Casa " + slug, citta="Roma",
                               prezzo_notte_cents=10000, capacita=2),
                immagini=([{"url": "/uploads/" + cls.foto_vecchia}] if slug == "casa-a" else []))
        cls.voucher_a, cls.rif_a = cls._prenota_pagata("casa-a", cls.hid_a)
        cls.voucher_b, cls.rif_b = cls._prenota_pagata("casa-b", cls.hid_b)
        # la foto d'annuncio caricata OGGI dall'host A (registrata col suo padrone)
        s, c = cls._g("POST", "/api/host/upload_foto",
                      {"image_base64": base64.b64encode(PNG).decode("ascii")},
                      {"X-Host-Token": cls.tok_a})
        assert s == 201, (s, c)
        cls.foto_annuncio = c["url"].rsplit("/", 1)[1]
        # le PROVE: una per prenotazione, caricate dall'ospite col suo voucher
        cls.prova_a = cls._prova(cls.voucher_a)
        cls.prova_b = cls._prova(cls.voucher_b)
        # UNA PROVA VECCHIA: caricata prima della riparazione (file sul disco, citata in chat
        # dall'ospite con la forma della prova, nessuna riga di proprietario)
        cls.prova_vecchia = secrets.token_hex(16) + ".png"
        with open(os.path.join(updir, cls.prova_vecchia), "wb") as f:
            f.write(PNG)
        assert cls.sis.messaggistica.invia(cls.rif_a, cls.hid_a, "ospite", "ospite",
                                           PREFISSO + " /uploads/" + cls.prova_vecchia)
        # UNA PROVA VECCHIA CONTESA: l'ospite A la cita come prova, e anche l'ospite B (un finto
        # messaggio). Non si sa di chi sia: privata per tutti, e nessuno riceve la firma.
        cls.prova_contesa = secrets.token_hex(16) + ".png"
        with open(os.path.join(updir, cls.prova_contesa), "wb") as f:
            f.write(PNG)
        assert cls.sis.messaggistica.invia(cls.rif_a, cls.hid_a, "ospite", "ospite",
                                           PREFISSO + " /uploads/" + cls.prova_contesa)
        # L'OSPITE B CITA in chat, con la forma della prova, la prova di A, la foto vecchia
        # dell'annuncio di A e la prova contesa: non deve ottenere niente da nessuna.
        for nome in (cls.prova_a, cls.foto_vecchia, cls.prova_contesa):
            s, c = cls._g("POST", "/api/voucher/messaggio",
                          {"voucher_token": cls.voucher_b,
                           "testo": PREFISSO + " /uploads/" + nome})
            assert s == 201, (s, c)

    # ── trasporto HTTP grezzo ──
    @classmethod
    def _http(cls, metodo, path):
        c = http.client.HTTPConnection("127.0.0.1", cls.porta, timeout=10)
        try:
            c.request(metodo, path)
            r = c.getresponse()
            dati = r.read()
            return r.status, {k.lower(): v for k, v in r.getheaders()}, dati
        finally:
            c.close()

    def _link_firmato(self, messaggi, nome):
        """Il link che la chat consegna per `nome`, con la firma; None se non c'e'."""
        for m in messaggi:
            t = re.search(r"/uploads/" + re.escape(nome) + r"\?t=[A-Za-z0-9_.=\-]+",
                          str(m.get("testo", "")))
            if t:
                return t.group(0)
        return None

    def _thread_ospite(self, voucher):
        s, c = self._g("GET", "/api/voucher/messaggi", q={"voucher_token": voucher})
        self.assertEqual(200, s, c)
        return c["messaggi"]

    def _apre_privata(self, link):
        s, hd, corpo = self._http("GET", link)
        self.assertEqual(200, s, link)
        self.assertEqual(PNG, corpo)
        cc = hd.get("cache-control", "")
        self.assertIn("no-store", cc)
        self.assertIn("private", cc)
        self.assertNotIn("public", cc)

    # ── 1. senza permesso la prova non si apre ──
    def test_LA_PROVA_NON_SI_APRE_SENZA_PERMESSO(self):
        for nome in (self.prova_a, self.prova_b):
            s, hd, corpo = self._http("GET", "/uploads/" + nome)
            self.assertEqual(403, s, "la prova %s si apre senza permesso" % nome)
            self.assertNotEqual(PNG, corpo)
            self.assertNotIn("public", hd.get("cache-control", ""))

    def test_SE_LA_PROPRIETA_NON_SI_LEGGE_SI_NEGA(self):
        """D19: lo stato «impossibile» costruito a mano. L'archivio dei proprietari solleva:
        il server non sa se il file e' una prova, quindi lo tratta da prova. Senza gettone nega
        (anche la foto di un annuncio); col gettone giusto apre, perche' quel gettone l'ha
        firmato il server per quel nome. La chat risponde lo stesso, coi link senza firma."""
        buona = self.sis.firma.codifica(
            {"tipo": "prova_foto", "nome": self.prova_a, "exp": int(time.time()) + 600})
        cat = self.sis.catalogo
        vera = cat.proprietario_upload
        cat.proprietario_upload = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("db giu"))
        try:
            for nome in (self.prova_a, self.foto_annuncio):
                s, _hd, corpo = self._http("GET", "/uploads/" + nome)
                self.assertEqual(403, s, nome)
                self.assertNotEqual(PNG, corpo, nome)
            s, hd, _c = self._http("GET", "/uploads/%s?t=%s" % (self.prova_a, buona))
            self.assertEqual(200, s)
            self.assertIn("no-store", hd.get("cache-control", ""))
            msgs = self._thread_ospite(self.voucher_a)
            self.assertTrue(msgs)
            self.assertIsNone(self._link_firmato(msgs, self.prova_a))
        finally:
            cat.proprietario_upload = vera
        self.assertEqual(200, self._http("GET", "/uploads/%s?t=%s" % (self.prova_a, buona))[0])

    def test_LA_PROVA_VECCHIA_CONTESA_E_PRIVATA_PER_TUTTI(self):
        s, _hd, corpo = self._http("GET", "/uploads/" + self.prova_contesa)
        self.assertEqual(403, s)
        self.assertNotEqual(PNG, corpo)
        for voucher in (self.voucher_a, self.voucher_b):
            self.assertIsNone(self._link_firmato(self._thread_ospite(voucher), self.prova_contesa))

    def test_LA_PROVA_CARICATA_A_SERVER_ACCESO_E_SUBITO_PRIVATA(self):
        """Le prove di `_prepara` nascono PRIMA dell'avvio, quindi le registra anche la ripresa
        delle prove vecchie: da sole non dicono se la riga nasce col caricamento. Questa si
        carica a server gia' acceso, e deve essere privata subito, non dal prossimo riavvio."""
        nuova = self._prova(self.voucher_a)
        self.assertEqual("prova:" + self.rif_a,
                         self.sis.catalogo.proprietario_upload(nuova.upper()))
        s, _hd, corpo = self._http("GET", "/uploads/" + nuova)
        self.assertEqual(403, s, "la prova appena caricata si apre senza permesso")
        self.assertNotEqual(PNG, corpo)
        self._apre_privata(self._link_firmato(self._thread_ospite(self.voucher_a), nuova))

    def test_UN_NOME_ALIAS_NON_APRE_LA_PROVA(self):
        """Sul disco di Windows `ABC.PNG`, `abc.png.`, `abc.png ` e `abc.png::$DATA` aprono lo stesso
        file di `abc.png` (Compito 49); su Linux non esistono (404). In nessuno dei due la prova
        esce."""
        n = self.prova_a
        for alias in (n.upper(), n + ".", n + "%20", n + "%3A%3A%24DATA", n + "::$DATA"):
            s, _hd, corpo = self._http("GET", "/uploads/" + alias)
            self.assertIn(s, (403, 404), alias)
            self.assertNotEqual(PNG, corpo, alias)

    def test_LA_PROVA_VECCHIA_NON_SI_APRE_SENZA_PERMESSO(self):
        s, _hd, corpo = self._http("GET", "/uploads/" + self.prova_vecchia)
        self.assertEqual(403, s)
        self.assertNotEqual(PNG, corpo)

    # ── 2. i tre lettori della chat la aprono dal link firmato ──
    def test_L_OSPITE_LA_APRE_DALLA_SUA_CHAT(self):
        msgs = self._thread_ospite(self.voucher_a)
        for nome in (self.prova_a, self.prova_vecchia):
            link = self._link_firmato(msgs, nome)
            self.assertIsNotNone(link, "nella chat dell'ospite manca il link firmato di %s" % nome)
            self._apre_privata(link)

    def test_L_HOST_DELLA_PRENOTAZIONE_LA_APRE(self):
        s, c = self._g("GET", "/api/messaggi", q={"prenotazione_id": self.rif_a},
                       h={"X-Host-Token": self.tok_a})
        self.assertEqual(200, s, c)
        link = self._link_firmato(c["messaggi"], self.prova_a)
        self.assertIsNotNone(link, "nella chat dell'host manca il link firmato della prova")
        self._apre_privata(link)

    def test_L_ARBITRO_LA_APRE(self):
        s, c = self._g("GET", "/api/admin/messaggi", q={"riferimento": self.rif_a},
                       h={"X-Admin-Key": "ak"})
        self.assertEqual(200, s, c)
        link = self._link_firmato(c["messaggi"], self.prova_a)
        self.assertIsNotNone(link, "nella vista dell'arbitro manca il link firmato della prova")
        self._apre_privata(link)

    # ── 3. una firma apre UNA prova, finche' vale, e solo lei ──
    def test_UNA_FIRMA_NON_APRE_UN_ALTRA_PROVA_NE_DOPO_LA_SCADENZA(self):
        f = self.sis.firma
        dopo = int(time.time()) + 600
        # controllo positivo del formato: senza questo, i rossi qui sotto non direbbero niente
        buona = f.codifica({"tipo": "prova_foto", "nome": self.prova_a, "exp": dopo})
        self.assertEqual(200, self._http("GET", "/uploads/%s?t=%s" % (self.prova_a, buona))[0])
        cattivi = {
            "firma di A su B": (self.prova_b, buona),
            "scaduto": (self.prova_a, f.codifica(
                {"tipo": "prova_foto", "nome": self.prova_a, "exp": int(time.time()) - 5})),
            "manomesso": (self.prova_a, buona[:-1] + ("0" if buona[-1] != "0" else "1")),
            "un voucher al posto della firma": (self.prova_a, self.voucher_a),
            "un altro tipo con lo stesso nome": (self.prova_a, f.codifica(
                {"tipo": "voucher", "nome": self.prova_a, "exp": dopo})),
            "senza scadenza": (self.prova_a, f.codifica(
                {"tipo": "prova_foto", "nome": self.prova_a})),
            "non ASCII": (self.prova_a, quote("é" * 8)),
            "vuoto": (self.prova_a, ""),
        }
        for caso, (nome, tok) in cattivi.items():
            s, _hd, corpo = self._http("GET", "/uploads/%s?t=%s" % (nome, tok))
            self.assertEqual(403, s, caso)
            self.assertNotEqual(PNG, corpo, caso)

    def test_UN_OSPITE_NON_OTTIENE_LA_FIRMA_PER_LA_PROVA_DI_UN_ALTRO(self):
        msgs = self._thread_ospite(self.voucher_b)
        testi = " ".join(str(m.get("testo", "")) for m in msgs)
        self.assertIn("/uploads/" + self.prova_a, testi)        # il messaggio c'e'
        self.assertIsNone(self._link_firmato(msgs, self.prova_a))
        self.assertIsNotNone(self._link_firmato(msgs, self.prova_b))   # la sua invece si'

    # ── 4. le foto degli annunci restano pubbliche ──
    def test_LE_FOTO_DEGLI_ANNUNCI_RESTANO_PUBBLICHE(self):
        for nome in (self.foto_annuncio, self.foto_vecchia):
            s, hd, corpo = self._http("GET", "/uploads/" + nome)
            self.assertEqual(200, s, nome)
            self.assertEqual(PNG, corpo, nome)
            self.assertEqual(CACHE_ANNUNCI, hd.get("cache-control"), nome)

    # ── 5. i tre disegnatori di link tengono la firma ──
    def _espressioni_dei_link(self, testo, dove):
        trovate = re.findall(r"replace\(/(\(\\/uploads.*?)/g,", testo)
        self.assertTrue(trovate, "%s: nessuna espressione che disegna i link /uploads/" % dove)
        return [t.replace("\\/", "/") for t in trovate]

    def test_I_TRE_DISEGNATORI_DI_LINK_TENGONO_LA_FIRMA(self):
        nome = "ab" * 16 + ".png"
        gettone = "eyJhIjoxfQ-_=.0f9e"
        campione = PREFISSO + " /uploads/" + nome + "?t=" + gettone
        sorgenti = {"pagina del voucher": pagina_voucher_html(self.sis, self.voucher_a, "it")}
        for f in ("admin.html", "host.html"):
            with open(os.path.join(RADICE, "deploy", f), encoding="utf-8") as fh:
                sorgenti[f] = fh.read()
        self.assertIn("chBox", sorgenti["pagina del voucher"])   # la chat c'e' (pagata)
        for dove, testo in sorgenti.items():
            for espr in self._espressioni_dei_link(testo, dove):
                href = re.sub(espr, lambda m: "<a href='%s'>" % m.group(1), campione)
                self.assertIn("/uploads/%s?t=%s'" % (nome, gettone), href,
                              "%s: il link perde la firma (%s)" % (dove, espr))


if __name__ == "__main__":
    unittest.main(verbosity=2)
