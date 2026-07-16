"""
"1000 MENTI": fuzzer stateful basato su modello (idea del fondatore: 1000 cervelli, 1000 mappe
mentali, logiche diverse -> falli girare live e vedi quanti errori).

Ogni AGENTE e' una 'mente' con la sua logica: esegue una sequenza CASUALE di azioni (quote, book,
pay, pay-doppio, cancel, rimborso admin, cancella host, conferma, contesta, recensisci, ri-quota,
sospendi, ripubblica) contro la macchina REALE. Dopo la tempesta si verificano gli INVARIANTI
globali. Se una sequenza li rompe -> bug (e la sequenza e' la prova). La versione da 10k agenti ha
scovato un record incompleto (mancavano costo_pagamento/sconto/tassa -> i conti non riconciliavano);
qui gira una versione ridotta e veloce come GUARDIA quotidiana.

INVARIANTI: no overbooking, no occupate negative, no doppio payout, no payout negativo, host mai
'maturato' su prenotazione rimborsata/cancellata, escrow conserva, e CONSERVAZIONE del record:
totale == netto_host + (commissione - sconto) + tassa + costo_pagamento.
"""
import datetime
import json
import shutil
import sqlite3
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

WH = "whsec_menti"
AZIONI = ["quote", "book", "pay", "pay2", "cancel", "adminref", "hostcancel",
          "conferma", "contesta", "review", "requote", "suspend", "republish"]


def _fake_fetch(url, body, headers):
    import secrets
    return {"url": "https://x/" + secrets.token_hex(5), "id": "cs_" + secrets.token_hex(5)}


class TestMentiInvarianti(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def _simula(self, seed, n_agenti):
        import random
        rnd = random.Random(seed)
        d = tempfile.mkdtemp()
        try:
            sysx = crea_sistema(ConfigCasaVIP(
                abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
                db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
                db_accettazioni=f"{d}/acc.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/pay.db",
                db_garanzia=f"{d}/g.db", db_tassa_comunale=f"{d}/t.db", db_recensioni=f"{d}/rec.db",
                db_credito_usati=f"{d}/cu.db", commissione_bps=1000, psp_bps=300,
                stripe_secret_key="sk", stripe_webhook_secret=WH,
                stripe_success_url="https://x/ok", stripe_cancel_url="https://x/no"))
            r = crea_router(sysx, host_key="hk", admin_key="ak", base_url="https://bookinvip.com")

            def g(m, p, b=None, h=None):
                return r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

            def paga(rif):
                pl = json.dumps({"type": "checkout.session.completed",
                                 "data": {"object": {"metadata": {"riferimento": rif}}}})
                r.gestisci("POST", "/api/payments/webhook", {}, pl,
                           {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})

            s, c = g("POST", "/api/host/registrazione",
                     {"email": "h@m.it", "password": "password1", "accetta_termini": True,
                      "accetta_clausole": True, "doc_sha256": doc_sha256(),
                      "versione": CONTRATTO_HOST_VERSIONE})
            tok = c["token"]
            pol = ["flessibile", "moderata", "rigida", "non_rimborsabile"]
            val = ["EUR", "USD", "JPY"]
            slugs = []
            for i in range(4):
                slug = f"casa{i}"
                g("POST", "/api/host/pubblica",
                  {"slug": slug, "titolo": f"C{i}", "citta": "Roma",
                   "prezzo_notte_cents": rnd.choice([10000, 50000, 120000]), "capacita": 6,
                   "politica_cancellazione": pol[i % 4], "valuta": val[i % 3],
                   "tassa_pp_notte_cents": rnd.choice([0, 200])}, {"X-Host-Token": tok})
                g("POST", "/api/host/disponibilita_range",
                  {"alloggio_id": slug, "da": "2026-09-01", "a": "2026-12-31",
                   "unita_totali": rnd.choice([1, 2]), "prezzo_netto_cents": 50000},
                  {"X-Host-Token": tok})
                slugs.append(slug)
            base = datetime.date(2026, 9, 1)

            eccezioni = []
            for a in range(n_agenti):
                stt = {"quote": None, "rif": None, "voucher": None, "diritto": None, "slug": None}
                for _ in range(rnd.randint(1, 6)):
                    az = rnd.choice(AZIONI)
                    try:
                        if az == "quote":
                            slug = rnd.choice(slugs); off = rnd.randint(0, 100)
                            notti = rnd.choice([1, 2, 3, 7])
                            body = {"alloggio_id": slug,
                                    "check_in": (base + datetime.timedelta(days=off)).isoformat(),
                                    "check_out": (base + datetime.timedelta(days=off + notti)).isoformat(),
                                    "party": rnd.randint(1, 4)}
                            if rnd.random() < 0.3:
                                body["credito_token"] = sysx.firma.codifica(
                                    {"tipo": "credito_fondatore", "email": "x@x.it", "citta": "roma",
                                     "credito_cents": 5000, "exp": int(time.time()) + 30 * 86400,
                                     "nonce": str(rnd.random())})
                            s, q = g("POST", "/api/concierge/quote", body)
                            if s == 200:
                                stt["quote"] = q.get("quote_token"); stt["slug"] = slug
                        elif az == "requote" and stt["slug"]:
                            s, q = g("POST", "/api/concierge/quote",
                                     {"alloggio_id": stt["slug"],
                                      "check_in": (base + datetime.timedelta(days=rnd.randint(0, 100))).isoformat(),
                                      "check_out": (base + datetime.timedelta(days=rnd.randint(101, 110))).isoformat(),
                                      "party": 2})
                            if s == 200:
                                stt["quote"] = q.get("quote_token")
                        elif az == "book" and stt["quote"]:
                            s, b = g("POST", "/api/concierge/book",
                                     {"quote_token": stt["quote"], "email": "cli@m.it"})
                            if s == 201:
                                stt["rif"] = b.get("riferimento")
                                stt["voucher"] = b.get("voucher_token")
                                stt["diritto"] = b.get("diritto_recensione")
                        elif az == "pay" and stt["rif"]:
                            paga(stt["rif"])
                        elif az == "pay2" and stt["rif"]:
                            paga(stt["rif"]); paga(stt["rif"])
                        elif az == "cancel" and stt["voucher"]:
                            g("POST", "/api/concierge/cancella", {"voucher_token": stt["voucher"]})
                        elif az == "adminref" and stt["rif"]:
                            s, adm = g("GET", "/api/admin/prenotazioni", None, {"X-Admin-Key": "ak"})
                            for p in (adm.get("prenotazioni") or []):
                                if str(p.get("idem_key", ""))[:24] == stt["rif"]:
                                    g("POST", "/api/admin/rimborso",
                                      {"alloggio_id": p["alloggio_id"], "check_in": p["check_in"],
                                       "check_out": p["check_out"], "idem_key": p["idem_key"]},
                                      {"X-Admin-Key": "ak"})
                                    break
                        elif az == "hostcancel" and stt["rif"]:
                            g("POST", "/api/host/cancella", {"riferimento": stt["rif"]},
                              {"X-Host-Token": tok})
                        elif az == "conferma" and stt["voucher"]:
                            g("POST", "/api/garanzia/conferma", {"voucher_token": stt["voucher"]})
                        elif az == "contesta" and stt["voucher"]:
                            g("POST", "/api/garanzia/contesta",
                              {"voucher_token": stt["voucher"], "motivo": "x"})
                        elif az == "review" and stt["diritto"]:
                            g("POST", "/api/recensioni",
                              {"token": stt["diritto"], "voto": rnd.randint(1, 5), "testo": "ok"})
                        elif az == "suspend" and stt["slug"]:
                            g("POST", "/api/admin/alloggio_stato",
                              {"slug": stt["slug"], "stato": "sospeso"}, {"X-Admin-Key": "ak"})
                        elif az == "republish" and stt["slug"]:
                            g("POST", "/api/admin/alloggio_stato",
                              {"slug": stt["slug"], "stato": "pubblicato"}, {"X-Admin-Key": "ak"})
                    except Exception as e:  # noqa: BLE001 — un'eccezione qui e' proprio un bug
                        eccezioni.append((a, az, type(e).__name__, str(e)[:100]))
                if a % 15 == 0:
                    for slug in slugs:
                        g("POST", "/api/admin/alloggio_stato",
                          {"slug": slug, "stato": "pubblicato"}, {"X-Admin-Key": "ak"})

            self.assertEqual(eccezioni, [], f"seed={seed}: il router ha SOLLEVATO: {eccezioni[:5]}")
            self._invarianti(d, seed)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def _invarianti(self, d, seed):
        viol = []
        con = sqlite3.connect(f"{d}/i.db"); con.row_factory = sqlite3.Row
        for row in con.execute("SELECT alloggio_id, giorno, unita_totali, unita_occupate FROM inventario"):
            if row["unita_occupate"] > row["unita_totali"]:
                viol.append(("OVERBOOKING", dict(row)))
            if row["unita_occupate"] < 0:
                viol.append(("OCCUPATE_NEGATIVE", dict(row)))
        con.close()
        conp = sqlite3.connect(f"{d}/p.db"); conp.row_factory = sqlite3.Row
        paydb = sqlite3.connect(f"{d}/pay.db"); paydb.row_factory = sqlite3.Row
        pay_by_ref, dupe = {}, 0
        for pr in paydb.execute("SELECT prenotazione_id, minori, stato FROM payout"):
            if pr["prenotazione_id"] in pay_by_ref:
                dupe += 1
            pay_by_ref[pr["prenotazione_id"]] = pr
            if pr["minori"] < 0:
                viol.append(("PAYOUT_NEGATIVO", dict(pr)))
        if dupe:
            viol.append(("DOPPIO_PAYOUT", dupe))
        for pn in conp.execute("SELECT riferimento, stato, corpo_json FROM pendenti"):
            try:
                dj = json.loads(pn["corpo_json"] or "{}")
            except Exception:
                dj = {}
            if pn["stato"] == "pagato" and dj:
                tot = dj.get("totale_cents", 0)
                nh = dj.get("netto_host_cents", 0)
                comm = dj.get("commissione_cents", 0)
                sc = dj.get("sconto_credito_cents", 0)
                tassa = dj.get("tassa_soggiorno_cents", 0)
                cp = dj.get("costo_pagamento_cents", 0)
                if tot != nh + (comm - sc) + tassa + cp:
                    viol.append(("CONSERVAZIONE", pn["riferimento"], tot, nh, comm, sc, tassa, cp))
            if pn["stato"] in ("rimborsato", "cancellata_host"):
                pr = pay_by_ref.get(pn["riferimento"])
                if pr and pr["stato"] == "maturato":
                    viol.append(("HOST_PAGATO_SU_RIMBORSATO", pn["riferimento"]))
        conp.close(); paydb.close()
        cong = sqlite3.connect(f"{d}/g.db"); cong.row_factory = sqlite3.Row
        try:
            for gr in cong.execute("SELECT prenotazione_id, importo_host_cents, host_riceve_cents, "
                                   "ospite_rimborso_cents FROM garanzia"):
                hr = gr["host_riceve_cents"] or 0
                orr = gr["ospite_rimborso_cents"] or 0
                if hr < 0 or orr < 0 or hr + orr > (gr["importo_host_cents"] or 0):
                    viol.append(("ESCROW_NON_CONSERVA", dict(gr)))
        except sqlite3.Error:
            pass
        cong.close()
        self.assertEqual(viol, [], f"seed={seed}: invarianti ROTTI: {viol[:8]}")

    def test_menti_seed_1(self):
        self._simula(seed=1, n_agenti=150)

    def test_menti_seed_2(self):
        self._simula(seed=2, n_agenti=150)


if __name__ == "__main__":
    unittest.main(verbosity=2)
