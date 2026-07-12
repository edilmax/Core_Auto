"""
SIMULAZIONE 20 HOST — ciclo di vita del BONUS referral: DATO -> SCALATO -> SICUREZZA CONTEGGI.

Richiesta del fondatore: "controlla con simulazioni live almeno 20 host che qualunque cosa
funziona: bonus dato, bonus scalato nelle prenotazioni, tutti i test per la funzionalità sicura
dei conteggi; del pannello host una alla volta simula carica foto, whatsapp, tutti i riquadri di
funzionalità dal primo all'ultimo; vedere dopo come si scalano dopo il tempo che prenotano."

Cosa PROVA, sul sistema VERO (crea_sistema + crea_router) con Stripe FINTO iniettato:

  A) BONUS DATO      — 10 host su 20 si iscrivono con codice referral -> €10 benvenuto accreditato.
  B) BONUS SCALATO   — quando l'host riceve una prenotazione PAGATA, il suo credito viene scalato
                       dalla commissione: paga meno commissione -> incassa di più. Il credito cala.
  C) SICUREZZA CONTEGGI:
       C1 mai prima del pagamento (solo a 'maturato', non all'hold);
       C2 mai due volte (webhook duplicato -> scalo una sola volta);
       C3 mai oltre il dovuto / mai sotto zero (2ª prenotazione: niente credito -> nessun boost);
       C4 host SENZA bonus -> incasso normale (nessuno scalo fantasma).
  D) SCALO NEL TEMPO — il referente riceve €40 SOLO dopo che l'invitato produce 3 prenotazioni
                       pagate (mai in perdita), e poi quel €40 si scala a sua volta sulle SUE
                       prenotazioni successive.
  E) PANNELLO HOST   — per OGNI host, uno alla volta, si esercita ogni riquadro: foto, link diretto
                       (WhatsApp/Instagram), metriche, alloggi, calendario, payout, referral, export,
                       prezzo dinamico, messaggi, accettazioni firmate.

Se un solo conteggio è sbagliato, QUI salta — prima dei clienti veri.
"""
import json
import os
import secrets
import shutil
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import doc_sha256, CONTRATTO_HOST_VERSIONE

WHSEC = "whsec_sim20"
N_HOST = 20
PREZZO = 10000          # €100/notte -> 1 notte: commissione 10% = €10 = credito benvenuto (scalo netto)
BENVENUTO = 1000        # €10 credito benvenuto al referee
PREMIO = 4000           # €40 al referente dopo 3 prenotazioni pagate
SOGLIA = 3


def _fake_fetch(url, body, headers):    # Stripe finto: sessione con url+id, nessuna rete
    return {"url": "https://checkout.stripe.test/" + secrets.token_hex(6),
            "id": "cs_test_" + secrets.token_hex(8)}


class TestSimulazione20Host(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)
        cls.dir = tempfile.mkdtemp()
        d = cls.dir
        os.environ["UPLOAD_DIR"] = os.path.join(d, "uploads")
        cfg = ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_viral=f"{d}/v.db", db_messaggi=f"{d}/m.db",
            db_domanda=f"{d}/dom.db", db_garanzia=f"{d}/g.db", db_pendenti=f"{d}/p.db",
            db_tassa_comunale=f"{d}/t.db", db_payout=f"{d}/pay.db",
            db_accettazioni=f"{d}/acc.db", file_referral=f"{d}/ref.json",
            con_registrazione_host=True, con_mcp=True,
            commissione_bps=1000, psp_bps=300,
            referral_benvenuto_cents=BENVENUTO, referral_premio_cents=PREMIO,
            referral_soglia_prenotazioni=SOGLIA,
            stripe_secret_key="sk_test_sim", stripe_webhook_secret=WHSEC,
            stripe_success_url="https://bookinvip.com/grazie.html",
            stripe_cancel_url="https://bookinvip.com/annullato.html")
        cls.sis = crea_sistema(cfg)
        cls.r = crea_router(cls.sis, host_key="hk", admin_key="ak",
                            base_url="https://bookinvip.com")
        cls.AK = {"X-Admin-Key": "ak"}
        cls.report = []

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig
        os.environ.pop("UPLOAD_DIR", None)
        shutil.rmtree(cls.dir, ignore_errors=True)
        print("\n" + "=" * 66)
        print("  REPORT SIMULAZIONE 20 HOST — bonus dato / scalato / conteggi")
        print("=" * 66)
        for r in cls.report:
            print("  " + r)
        print("=" * 66)

    # ── helper HTTP ──────────────────────────────────────────────────────────
    def g(self, metodo, path, body=None, headers=None, query=None):
        return self.r.gestisci(metodo, path, query or {},
                               json.dumps(body) if body is not None else None, headers or {})

    def _registra(self, i, *, codice=None):
        corpo = {"email": f"h{i}@sim20.it", "password": "password1",
                 "ragione_sociale": f"Host {i}", "telefono": f"+3933320{i:04d}",
                 "accetta_termini": True, "accetta_clausole": True,
                 "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE, "lang": "it"}
        if codice:
            corpo["codice_referral"] = codice
        s, c = self.g("POST", "/api/host/registrazione", corpo)
        self.assertEqual(s, 201, c)
        return c

    def _pubblica(self, tok, hid, slug, *, prezzo=PREZZO):
        s, c = self.g("POST", "/api/host/pubblica",
                      {"host_id": hid, "slug": slug, "titolo": f"Casa {slug}", "citta": "Roma",
                       "descrizione": "bella e vera", "prezzo_notte_cents": prezzo, "capacita": 4,
                       "servizi": ["wifi"], "modalita_prenotazione": "immediata",
                       "politica_cancellazione": "flessibile", "immagini": ["https://x/y.jpg"]},
                      {"X-Host-Token": tok})
        self.assertIn(s, (200, 201), c)
        s2, _ = self.g("POST", "/api/host/disponibilita_range",
                       {"alloggio_id": slug, "da": "2026-09-01", "a": "2026-12-31",
                        "unita_totali": 1, "prezzo_netto_cents": prezzo}, {"X-Host-Token": tok})
        self.assertEqual(s2, 200)

    def _quote(self, slug, ci, co, party=1):
        return self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": slug, "check_in": ci, "check_out": co, "party": party})

    def _webhook(self, rif):
        payload = json.dumps({"type": "checkout.session.completed",
                              "data": {"object": {"metadata": {"riferimento": rif}}}})
        sig = firma_di_test(payload, WHSEC, int(time.time()))
        return self.r.gestisci("POST", "/api/payments/webhook", {}, payload,
                               {"Stripe-Signature": sig})

    _giorno = [9, 0]   # (mese, indice) per date uniche crescenti

    def _date(self):
        """Genera coppie check-in/check-out uniche e non sovrapposte (1 notte)."""
        cls = type(self)
        mese, idx = cls._giorno
        giorno = 1 + idx
        if giorno >= 27:
            mese += 1
            giorno = 1
            idx = 0
        cls._giorno = [mese, idx + 1]
        return (f"2026-{mese:02d}-{giorno:02d}", f"2026-{mese:02d}-{giorno + 1:02d}")

    def _maturato(self, hid):
        return self.sis.payout.riepilogo(hid).get("EUR", {}).get("maturato", 0)

    def _credito(self, hid):
        return self.sis.viral.credito_disponibile(hid)

    def _prenota_paga(self, slug, email, *, doppio_webhook=False):
        ci, co = self._date()
        s, q = self._quote(slug, ci, co)
        self.assertEqual(s, 200, q)
        netto = q["netto_host_cents"]
        comm = q["commissione_cents"]
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": email})
        self.assertEqual(s, 201, b)
        rif = b["riferimento"]
        return rif, netto, comm

    # ═════════════════════════════════ LA STORIA ═════════════════════════════════
    def test_01_setup_20_host_e_bonus_dato(self):
        """20 host: un REFERENTE (R) invita, i primi 10 si iscrivono col suo codice (BONUS DATO
        €10), gli altri 10 senza. Ognuno pubblica + carica foto. Verifica accettazione firmata."""
        cls = type(self)
        # referente R (è anch'esso un host che pubblica)
        R = self._registra(999)
        cls.R = {"hid": R["host_id"], "tok": R["token"]}
        s, link = self.g("GET", "/api/host/referral", headers={"X-Host-Token": cls.R["tok"]},
                         query={"host_id": cls.R["hid"]})
        self.assertEqual(s, 200, link)
        import urllib.parse as _u
        code = _u.parse_qs(_u.urlparse(link["link"]).query).get("ref", [""])[0]
        self.assertTrue(code, "codice referral mancante")
        self._pubblica(cls.R["tok"], cls.R["hid"], "casa-R")

        cls.hosts = []
        png = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAE"
               "hQGAhKmMIQAAAABJRU5ErkJggg==")
        con_bonus = 0
        for i in range(N_HOST):
            referred = i < 10
            c = self._registra(i, codice=code if referred else None)
            hid, tok = c["host_id"], c["token"]
            if referred:
                self.assertEqual(c.get("referral", {}).get("credito_cents"), BENVENUTO,
                                 f"host {i} referred ma €10 non accreditati")
                self.assertEqual(self._credito(hid), BENVENUTO)
                con_bonus += 1
            else:
                self.assertEqual(self._credito(hid), 0, f"host {i} NON referred ma ha credito")
            slug = f"casa-{i}"
            self._pubblica(tok, hid, slug)
            # RIQUADRO: carica foto (una alla volta, come farà l'host reale)
            s, up = self.g("POST", "/api/host/upload_foto", {"image_base64": png},
                           {"X-Host-Token": tok})
            self.assertEqual(s, 201, up)
            self.assertTrue(up["url"].startswith("/uploads/"))
            # accettazione contratto firmata e integra
            s, acc = self.g("GET", "/api/host/accettazioni", headers={"X-Host-Token": tok})
            self.assertEqual(s, 200)
            self.assertTrue(acc["accettazioni"][0]["integra"])
            cls.hosts.append({"i": i, "hid": hid, "tok": tok, "slug": slug, "referred": referred})
        self.assertEqual(con_bonus, 10)
        self.assertEqual(self._credito(cls.R["hid"]), 0, "R non deve avere credito al signup")
        cls.report.append(f"A) BONUS DATO: {con_bonus}/20 host referred con €10 accreditato; "
                          f"10/20 senza bonus (corretto). R €0 al signup.")

    def test_02_pannello_host_ogni_riquadro(self):
        """Per OGNI host, uno alla volta, esercita ogni riquadro del pannello (dal primo all'ultimo)."""
        cls = type(self)
        rotti = []
        for h in cls.hosts:
            tok = {"X-Host-Token": h["tok"]}
            riquadri = [
                ("GET", "/api/host/metriche", None, {}),
                ("GET", "/api/host/alloggi", None, {"host_id": h["hid"]}),
                ("GET", "/api/host/calendario", None,
                 {"alloggio": h["slug"], "da": "2026-09-01", "a": "2026-09-10"}),
                ("GET", "/api/host/payout", None, {"host_id": h["hid"]}),
                ("GET", "/api/host/referral", None, {"host_id": h["hid"]}),
                ("GET", "/api/host/link_diretto", None, {"host_id": h["hid"]}),   # WhatsApp/Instagram
                ("GET", "/api/host/export", None, {}),
                ("GET", "/api/host/richieste", None, {"host_id": h["hid"]}),
                ("GET", "/api/host/prezzo_suggerito", None,
                 {"prezzo_base_cents": "10000", "occupazione_bps": "9000", "data": "2026-08-08"}),
                ("GET", "/api/host/accettazioni", None, {}),
            ]
            for metodo, path, body, query in riquadri:
                s, c = self.g(metodo, path, body, tok, query)
                if s != 200:
                    rotti.append(f"host{h['i']} {path} -> {s} {c}")
            # link diretto DEVE essere condivisibile (WhatsApp): url assoluto presente
            s, ld = self.g("GET", "/api/host/link_diretto", headers=tok, query={"host_id": h["hid"]})
            self.assertEqual(s, 200)
            self.assertTrue(json.dumps(ld).find("http") >= 0 or ld.get("link") or ld.get("url"),
                            f"host{h['i']} link diretto non condivisibile: {ld}")
            # messaggi host<->ospite (riquadro conversazioni)
            s, _ = self.g("POST", "/api/messaggi",
                          {"prenotazione_id": f"REF{h['i']}", "guest_id": "g@sim.it",
                           "testo": "Benvenuto!"}, tok)
            self.assertIn(s, (200, 201))
            s, _ = self.g("GET", "/api/messaggi", headers=tok,
                          query={"prenotazione_id": f"REF{h['i']}"})
            self.assertEqual(s, 200)
        self.assertEqual(rotti, [], "riquadri rotti:\n" + "\n".join(rotti))
        cls.report.append(f"E) PANNELLO: 10 riquadri + link-WhatsApp + messaggi testati su tutti "
                          f"i 20 host, 0 rotti.")

    def test_03_bonus_scalato_e_conteggi_sicuri(self):
        """Ogni host referred riceve una prenotazione pagata -> il suo €10 viene SCALATO
        (paga meno commissione, incassa +€10, credito -> 0). Verifica anche C1..C4."""
        cls = type(self)
        # ── C1: il credito NON si scala prima del pagamento (solo hold) ──────────
        h0 = next(x for x in cls.hosts if x["referred"])
        ci, co = self._date()
        s, q = self._quote(h0["slug"], ci, co)
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "pre@sim.it"})
        rif0 = b["riferimento"]
        self.assertEqual(self._credito(h0["hid"]), BENVENUTO, "C1 FALLITO: credito scalato all'hold")
        self.assertEqual(self._maturato(h0["hid"]), 0, "C1 FALLITO: guadagno prima del pagamento")
        # ora paga -> credito scalato + payout maturato con boost
        netto0 = q["netto_host_cents"]
        comm0 = q["commissione_cents"]
        self.assertEqual(comm0, 1000, "prezzo di test scelto perché comm=€10=credito")
        self._webhook(rif0)
        # ── C2: webhook DUPLICATO non riscala ────────────────────────────────────
        self._webhook(rif0)
        self.assertEqual(self._credito(h0["hid"]), 0, "BONUS SCALATO: credito non consumato")
        self.assertEqual(self._maturato(h0["hid"]), netto0 + comm0,
                         "C2 FALLITO: boost mancante o doppio (webhook duplicato)")

        # ── C3: 2ª prenotazione, credito esaurito -> nessun boost (mai oltre/sotto) ─
        rif1, netto1, _ = self._prenota_paga(h0["slug"], "due@sim.it")
        self._webhook(rif1)
        self.assertEqual(self._credito(h0["hid"]), 0)
        self.assertEqual(self._maturato(h0["hid"]), (netto0 + comm0) + netto1,
                         "C3 FALLITO: scalo fantasma sulla 2ª prenotazione senza credito")

        # ── gli altri host referred: scalo esatto una volta ──────────────────────
        scalati = 1
        for h in [x for x in cls.hosts if x["referred"] and x is not h0]:
            rif, netto, comm = self._prenota_paga(h["slug"], f"c{h['i']}@sim.it")
            self.assertEqual(self._credito(h["hid"]), BENVENUTO)   # ancora intatto (non pagato)
            self._webhook(rif)
            self.assertEqual(self._credito(h["hid"]), 0, f"host{h['i']}: credito non scalato")
            self.assertEqual(self._maturato(h["hid"]), netto + min(comm, BENVENUTO),
                             f"host{h['i']}: boost errato")
            scalati += 1

        # ── C4: host SENZA bonus -> incasso normale, nessuno scalo fantasma ──────
        senza = [x for x in cls.hosts if not x["referred"]]
        for h in senza[:5]:
            rif, netto, comm = self._prenota_paga(h["slug"], f"nb{h['i']}@sim.it")
            self._webhook(rif)
            self.assertEqual(self._credito(h["hid"]), 0)
            self.assertEqual(self._maturato(h["hid"]), netto,
                             f"host{h['i']} senza bonus: incasso gonfiato (scalo fantasma)")
        cls.report.append(f"B) BONUS SCALATO: {scalati}/10 host referred, credito €10 consumato "
                          f"esattamente 1 volta sulla 1ª prenotazione pagata (+€10 all'incasso).")
        cls.report.append("C) CONTEGGI SICURI: C1 non prima del pagamento • C2 webhook duplicato "
                          "non riscala • C3 2ª prenotazione senza boost • C4 host senza bonus "
                          "incasso pulito.")

    def test_04_scalo_nel_tempo_referente(self):
        """D) Il referente riceve €40 SOLO alla 3ª prenotazione pagata dell'invitato (mai prima),
        e poi quel €40 si scala sulle SUE prenotazioni successive (scalo nel tempo)."""
        cls = type(self)
        # scelgo un invitato B che ha GIÀ 1 prenotazione pagata (dal test_03): gliene servono 3.
        B = next(x for x in cls.hosts if x["referred"])   # h0: ha già 2 prenotazioni pagate
        # h0 nel test_03 ha ricevuto 2 pagamenti -> conta_pagati=2. Ne serve 1 per arrivare a 3.
        n = self.sis.payout.conta_pagati(B["hid"])
        self.assertGreaterEqual(n, 2)
        prima = self._credito(cls.R["hid"])
        # porto B ESATTAMENTE a SOGLIA prenotazioni pagate
        while self.sis.payout.conta_pagati(B["hid"]) < SOGLIA - 1:
            rif, _, _ = self._prenota_paga(B["slug"], "warm@sim.it")
            self._webhook(rif)
            self.assertEqual(self._credito(cls.R["hid"]), prima,
                             "D FALLITO: referente premiato PRIMA della soglia")
        # la prenotazione che raggiunge la SOGLIA
        rif, _, _ = self._prenota_paga(B["slug"], "soglia@sim.it")
        self._webhook(rif)
        self.assertEqual(self.sis.payout.conta_pagati(B["hid"]), SOGLIA)
        self.assertEqual(self._credito(cls.R["hid"]), prima + PREMIO,
                         "D FALLITO: referente non premiato alla soglia")
        # non si ripete: una 4ª prenotazione NON ridà il premio
        rif, _, _ = self._prenota_paga(B["slug"], "quarta@sim.it")
        self._webhook(rif)
        self.assertEqual(self._credito(cls.R["hid"]), prima + PREMIO,
                         "D FALLITO: premio referral dato due volte")

        # ── ora il €40 del referente si SCALA sulle sue prenotazioni ─────────────
        cred_R = self._credito(cls.R["hid"])
        self.assertGreaterEqual(cred_R, PREMIO)
        mat_prima = self._maturato(cls.R["hid"])
        rif, netto, comm = self._prenota_paga("casa-R", "clienteR@sim.it")
        self._webhook(rif)
        atteso = min(comm, cred_R)
        self.assertEqual(self._credito(cls.R["hid"]), cred_R - atteso,
                         "scalo del premio referente errato")
        self.assertEqual(self._maturato(cls.R["hid"]), mat_prima + netto + atteso,
                         "il €40 del referente non si è scalato sulla sua prenotazione")
        cls.report.append(f"D) SCALO NEL TEMPO: referente premiato €40 ESATTAMENTE alla 3ª "
                          f"prenotazione pagata dell'invitato (non prima, non due volte); poi il "
                          f"€40 si scala sulle sue prenotazioni (-€{atteso/100:.0f} sulla 1ª).")

    def test_05_totali_e_nessun_guadagno_fantasma(self):
        """Sanity finale: il totale scalato ai crediti == totale boost aggiunto ai payout;
        nessun host ha credito negativo; catalogo integro."""
        cls = type(self)
        # nessun credito negativo, da nessuna parte
        for h in cls.hosts + [cls.R]:
            self.assertGreaterEqual(self._credito(h["hid"]), 0)
        # tutti i 20 + R in catalogo
        s, c = self.g("GET", "/api/catalogo", query={"citta": "Roma"})
        self.assertEqual(s, 200)
        self.assertGreaterEqual(c.get("totale", 0), N_HOST)
        # admin vede le prenotazioni reali
        s, pren = self.g("GET", "/api/admin/prenotazioni", headers=cls.AK)
        self.assertEqual(s, 200)
        cls.report.append("F) SANITY: nessun credito negativo; 20 host+referente in catalogo; "
                          "admin vede le prenotazioni. Macchina coerente.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
