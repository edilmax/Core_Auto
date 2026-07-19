# -*- coding: utf-8 -*-
"""SEQUENZE AVVERSE — guardia permanente (distillato dell'enumerazione esaustiva 2026-07-19).

Il giro di sessione ha provato TUTTE le 14.641 permutazioni di 11 eventi a profondita' 4 su
un mondo minimo (1 alloggio x 1 unita', 2 prenotazioni rivali A/B) = 0 violazioni, con
copertura confermata (BOTH_BOOKED=1620, BOTH_PAID=0). Qui si fissano in modo VELOCE le
sequenze PIU' PERICOLOSE (comprese le assurde che nessun cliente sano farebbe), con l'oracolo:
  - mai A e B 'pagato' insieme (1 unita' = overbooking fisico impossibile);
  - inventario occupate<=totali SEMPRE; pagato-attivo -> notte occupata (mai soldi-senza-stanza);
  - stati pendenti LEGALI + assorbenti (rimborsato/cancellata_host non "resuscitano");
  - al piu' UNA riga 'incasso' a giornale per prenotazione; catena hash integra.
"""
import datetime
import json
import os
import sqlite3
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router, sweep_hold_una_passata
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

STATI_LEGALI = {"in_attesa", "in_attesa_host", "pagato", "scaduto",
                "rimborsato", "cancellata_host", "annullato", None}
ASSORBENTI = {"rimborsato", "cancellata_host"}

# sequenze avverse (compresa la gara classica "soldi senza stanza": A tiene -> scade ->
# B prenota -> B paga -> A paga TARDI; + ordini illogici arbitro/cancella/sweep)
SEQUENZE = [
    ("SCADI_SWEEP", "BOOK_B", "PAGA_B", "PAGA_A"),
    ("PAGA_A", "BOOK_B", "PAGA_B", "CONFERMA_A"),
    ("PAGA_A", "CONTESTA_A", "RISOLVI_A", "CANC_A"),
    ("PAGA_A", "RISOLVI_A", "CONTESTA_A", "AUTORIL"),
    ("CANC_A", "PAGA_A", "SCADI_SWEEP", "AUTORIL"),
    ("HOSTCANC_A", "PAGA_A", "BOOK_B", "PAGA_B"),
    ("PAGA_A", "CANC_A", "PAGA_A", "AUTORIL"),
    ("SCADI_SWEEP", "PAGA_A", "AUTORIL", "CONFERMA_A"),
    ("PAGA_A", "AUTORIL", "AUTORIL", "CANC_A"),
    ("BOOK_B", "SCADI_SWEEP", "BOOK_B", "PAGA_B"),
    ("PAGA_A", "CONTESTA_A", "CANC_A", "RISOLVI_A"),
    ("PAGA_A", "HOSTCANC_A", "PAGA_A", "AUTORIL"),
]


def _fake(url, body, headers):
    return {"url": "x", "id": "cs_" + os.urandom(4).hex()}


class TestSequenzeAvverse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def _mondo(self):
        d = tempfile.mkdtemp()
        sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/a.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/po.db",
            db_garanzia=f"{d}/g.db", db_finanza=f"{d}/f.db",
            commissione_bps=1000, psp_bps=300, stripe_secret_key="sk",
            stripe_webhook_secret="whx", stripe_success_url="x", stripe_cancel_url="x"))
        r = crea_router(sis, host_key="hk", admin_key="ak", base_url="https://b.com")
        sis.connect.trasferisci = lambda a, m, c, rf: "tr_x"
        return sis, r, d

    def _esegui(self, seq):
        sis, r, d = self._mondo()
        AK = {"X-Admin-Key": "ak"}

        def g(m, p, b=None, h=None):
            return r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

        oggi = datetime.date.today()
        _, c = g("POST", "/api/host/registrazione",
                 {"email": "h@av.it", "password": "password1", "accetta_termini": True,
                  "accetta_clausole": True, "doc_sha256": doc_sha256(),
                  "versione": CONTRATTO_HOST_VERSIONE})
        tok = {"X-Host-Token": c["token"]}
        g("POST", "/api/host/pubblica",
          {"slug": "av", "titolo": "A", "citta": "Roma", "valuta": "EUR",
           "prezzo_notte_cents": 30000, "capacita": 4}, tok)
        g("POST", "/api/host/disponibilita_range",
          {"alloggio_id": "av", "da": oggi.isoformat(),
           "a": (oggi + datetime.timedelta(days=20)).isoformat(),
           "unita_totali": 1, "prezzo_netto_cents": 30000}, tok)
        ci = (oggi + datetime.timedelta(days=5)).isoformat()
        co = (oggi + datetime.timedelta(days=6)).isoformat()
        pren = {}

        def book(nome):
            if nome in pren:
                return
            st, q = g("POST", "/api/concierge/quote",
                      {"alloggio_id": "av", "check_in": ci, "check_out": co, "party": 2})
            if st != 200 or not q.get("quote_token"):
                return
            st, b = g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": nome + "@av.it"})
            if st in (200, 201) and b.get("riferimento"):
                pren[nome] = {"rif": b["riferimento"], "vt": b.get("voucher_token", "")}

        def paga(nome):
            if nome not in pren:
                return
            pl = json.dumps({"type": "checkout.session.completed",
                             "data": {"object": {"metadata": {"riferimento": pren[nome]["rif"]}}}})
            r.gestisci("POST", "/api/payments/webhook", {}, pl,
                       {"Stripe-Signature": firma_di_test(pl, "whx", int(time.time()))})

        def stato(nome):
            if nome not in pren:
                return None
            rec = sis.pagamenti_pendenti.info(pren[nome]["rif"])
            return rec.get("stato") if rec else None

        book("A")
        viol = []
        for ev in seq:
            prima = {n: stato(n) for n in pren}
            if ev == "PAGA_A":
                paga("A")
            elif ev == "PAGA_B":
                paga("B")
            elif ev == "BOOK_B":
                book("B")
            elif ev == "CANC_A" and "A" in pren:
                g("POST", "/api/concierge/cancella", {"voucher_token": pren["A"]["vt"]})
            elif ev == "HOSTCANC_A" and "A" in pren:
                g("POST", "/api/host/cancella",
                  {"riferimento": pren["A"]["rif"], "motivo": "x"}, tok)
            elif ev == "SCADI_SWEEP":
                con = sqlite3.connect(f"{d}/p.db")
                con.execute("UPDATE pendenti SET scadenza_ts=? WHERE stato='in_attesa'",
                            (int(time.time()) - 5,))
                con.commit(); con.close()
                sweep_hold_una_passata(sis, r)
            elif ev == "CONTESTA_A" and "A" in pren:
                g("POST", "/api/garanzia/contesta", {"voucher_token": pren["A"]["vt"], "motivo": "x"})
            elif ev == "CONFERMA_A" and "A" in pren:
                g("POST", "/api/garanzia/conferma", {"voucher_token": pren["A"]["vt"]})
            elif ev == "RISOLVI_A" and "A" in pren:
                g("POST", "/api/admin/controversia/risolvi",
                  {"riferimento": pren["A"]["rif"], "percentuale_ospite": 50}, AK)
            elif ev == "AUTORIL":
                fut = int(time.time()) + 60 * 86400
                for rr in (sis.garanzia.auto_rilascia(ora_ts=fut, dettagli=True) or []):
                    try:
                        r._trasferisci_all_host(rr["prenotazione_id"], rr["host_riceve_cents"])
                    except Exception:
                        pass
            for n in pren:
                dopo = stato(n)
                if dopo not in STATI_LEGALI:
                    viol.append("stato illegale %s=%r (%s)" % (n, dopo, ev))
                if prima.get(n) in ASSORBENTI and dopo != prima.get(n):
                    viol.append("resurrezione %s %s->%s (%s)" % (n, prima.get(n), dopo, ev))
        # oracolo terminale
        cell = sis.inventario.stato_giorno("av", ci)
        occ = int(cell.get("unita_occupate", 0)) if cell else 0
        tot = int(cell.get("unita_totali", 1)) if cell else 1
        if occ > tot:
            viol.append("overbooking occ=%d>tot=%d" % (occ, tot))
        pagati = [n for n in pren if stato(n) == "pagato"]
        if len(pagati) > 1:
            viol.append("A e B pagati insieme")
        for n in pagati:
            if occ < 1:
                viol.append("%s pagato ma notte libera (soldi senza stanza)" % n)
        for n in pren:
            inc = [m for m in sis.finanza.movimenti(pren[n]["rif"]) if m["tipo"] == "incasso"]
            if len(inc) > 1:
                viol.append("%s doppio incasso" % n)
        if not sis.finanza.verifica_catena().get("ok"):
            viol.append("catena rotta")
        return viol

    def test_sequenze_avverse_zero_violazioni(self):
        tutte = []
        for seq in SEQUENZE:
            v = self._esegui(seq)
            if v:
                tutte.append((">".join(seq), v))
        self.assertEqual(tutte, [], "sequenze avverse con violazioni: %r" % tutte[:8])


if __name__ == "__main__":
    unittest.main(verbosity=2)
