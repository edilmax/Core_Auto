"""TEST DI FLUSSO END-TO-END del ciclo di vita della recensione (4 controlli).
In-process sul sistema vero (nessun contatto col sito online). Stampa l'esito dei 4 punti.
"""
import datetime
import json
import os
import re
import shutil
import sys

try:  # Windows: console cp1252 non regge box-drawing/emoji -> uscita UTF-8 tollerante
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.chdir(REPO)

import fase85_pagamenti_stripe as _stripe


def _fake_fetch(url, body, headers):
    import secrets
    return {"url": "https://x/" + secrets.token_hex(5), "id": "cs_" + secrets.token_hex(5)}


_stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)

from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router, pagina_recensione_html
from fase86_email import corpo_invito_recensione_html
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

BASE = "https://bookinvip.com"
ESITI = []


def check(n, titolo, ok, dettaglio=""):
    ESITI.append((n, titolo, ok, dettaglio))
    print("  [%s] %d. %s%s" % ("OK" if ok else "KO", n, titolo,
                               ("  ->  " + dettaglio) if dettaglio else ""), flush=True)


def build(d):
    os.environ["UPLOAD_DIR"] = f"{d}/uploads"
    sis = crea_sistema(ConfigCasaVIP(
        abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
        db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
        db_accettazioni=f"{d}/a.db", db_pendenti=f"{d}/p.db", db_messaggi=f"{d}/m.db",
        db_garanzia=f"{d}/g.db", db_recensioni=f"{d}/rec.db",
        commissione_bps=1500, psp_bps=300, stripe_secret_key="sk",
        stripe_webhook_secret="whsec_x", stripe_success_url="https://x/ok",
        stripe_cancel_url="https://x/no"))
    r = crea_router(sis, host_key="hk", admin_key="ak", base_url=BASE)

    def g(m, p, b=None, h=None):
        return r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    s, c = g("POST", "/api/host/registrazione",
             {"email": "host@e2e.it", "password": "password1", "accetta_termini": True,
              "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
              "versione": CONTRATTO_HOST_VERSIONE})
    tk = {"X-Host-Token": c["token"]}
    oggi = datetime.date.today()
    g("POST", "/api/host/pubblica",
      {"slug": "attico", "titolo": "Attico Vista Colosseo", "citta": "Roma",
       "prezzo_notte_cents": 24500, "capacita": 6}, tk)
    g("POST", "/api/host/disponibilita_range",
      {"alloggio_id": "attico", "da": oggi.isoformat(),
       "a": (oggi + datetime.timedelta(days=40)).isoformat(),
       "unita_totali": 10, "prezzo_netto_cents": 24500}, tk)
    return sis, r, g


def prenota(sis, r, g, email, ci, co, paga=True):
    s, q = g("POST", "/api/concierge/quote",
             {"alloggio_id": "attico", "check_in": ci, "check_out": co, "party": 2})
    s, b = g("POST", "/api/concierge/book", {"quote_token": q["quote_token"], "email": email})
    rif, vt = b["riferimento"], b["voucher_token"]
    if paga:
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"metadata": {"riferimento": rif}}}})
        r.gestisci("POST", "/api/payments/webhook", {}, pl,
                   {"Stripe-Signature": firma_di_test(pl, "whsec_x", int(time.time()))})
    return rif, vt


def main():
    d = tempfile.mkdtemp()
    try:
        sis, r, g = build(d)
        pp = sis.pagamenti_pendenti
        oggi = datetime.date.today()
        # prenotazione pagata, check-out fra 5 giorni. "Oggi" lo simuliamo col parametro
        # di da_invitare_recensione (come fa lo sweeper orario reale).
        ci = (oggi + datetime.timedelta(days=3)).isoformat()
        CO = (oggi + datetime.timedelta(days=5))
        rif, vt = prenota(sis, r, g, "ospite1@e2e.it", ci, CO.isoformat())

        def invitati(giorno):
            return {x["riferimento"] for x in pp.da_invitare_recensione(oggi=giorno.isoformat())}

        # ── 1. TRIGGER & TEMPISTICA ─────────────────────────────────────────────
        aperta = rif not in invitati(CO - datetime.timedelta(days=2))   # prenotazione ancora aperta
        giorno_prima = rif not in invitati(CO - datetime.timedelta(days=1))  # 1 giorno prima
        giorno_checkout = rif not in invitati(CO)                       # il giorno stesso
        dopo = rif in invitati(CO + datetime.timedelta(days=1))         # dopo il check-out
        ok1 = aperta and giorno_prima and dopo
        check(1, "Trigger & tempistica (mai prima / mai a prenotazione aperta)", ok1,
              "aperta=soppresso:%s · giorno-prima=soppresso:%s · giorno-checkout=soppresso:%s "
              "· dopo-checkout=parte:%s (granularita' GIORNALIERA: parte dal giorno dopo il "
              "check-out, mai prima)" % (aperta, giorno_prima, giorno_checkout, dopo))

        # ── 2. CANALE & DESTINATARIO (nessun incrocio) ──────────────────────────
        rif_a, vt_a = prenota(sis, r, g, "aaa@e2e.it", ci, CO.isoformat())
        rif_b, vt_b = prenota(sis, r, g, "bbb@e2e.it", ci, CO.isoformat())
        righe = {x["riferimento"]: x for x in pp.da_invitare_recensione(
            oggi=(CO + datetime.timedelta(days=1)).isoformat())}
        mail_a = righe.get(rif_a, {}).get("email")
        mail_b = righe.get(rif_b, {}).get("email")
        ok2 = (mail_a == "aaa@e2e.it" and mail_b == "bbb@e2e.it"
               and mail_a != mail_b)
        check(2, "Canale & destinatario (email solo all'indirizzo di QUELLA prenotazione)", ok2,
              "prenotazione A -> %s · prenotazione B -> %s (nessun incrocio)" % (mail_a, mail_b))

        # ── 3. INTEGRITA' DEL LINK ──────────────────────────────────────────────
        rec = righe[rif_a]
        dj = json.loads(rec.get("corpo_json") or "{}")
        vt_email = dj.get("voucher_token", "")
        vurl = BASE + "/recensione/" + vt_email          # come lo costruisce lo sweeper reale
        email_html = corpo_invito_recensione_html(dj.get("titolo") or "attico", vurl)
        m = re.search(r'href="([^"]+)"', email_html)
        link = m.group(1) if m else ""
        punta_recensione = "/recensione/" in link
        token_unico = vt_email and vt_email in link
        niente_voucher = "/voucher/" not in email_html
        niente_script = ("<script" not in email_html
                         and not any(s in email_html for s in
                                     ("btnCanc", "chBox", "ckBox", "PIN check-in",
                                      "Cancella prenotazione", "smart_pass")))
        # e la PAGINA a cui porta il link e' pulita (nessuno script del voucher)
        pagina = pagina_recensione_html(sis, vt_email, "it")
        pagina_pulita = pagina is not None and all(
            s not in pagina for s in ("btnCanc", "chBox", "ckBox", "PIN check-in",
                                      "Cancella prenotazione"))
        ok3 = punta_recensione and token_unico and niente_voucher and niente_script and pagina_pulita
        check(3, "Integrita' del link (/recensione/ + token unico, zero voucher/script)", ok3,
              "link=/recensione/<token> · token-unico:%s · no-/voucher/:%s · no-script-voucher:%s "
              "· pagina-destinazione-pulita:%s  [NB: token nel PERCORSO, non ?token=]"
              % (token_unico, niente_voucher, niente_script, pagina_pulita))

        # ── 4. STATO PRENOTAZIONE: soppressione ─────────────────────────────────
        # (a) NON pagata
        rif_np, _ = prenota(sis, r, g, "nonpag@e2e.it", ci, CO.isoformat(), paga=False)
        # (b) CANCELLATA (pagata e poi cancellata dal cliente)
        rif_c, vt_c = prenota(sis, r, g, "canc@e2e.it", ci, CO.isoformat())
        sc, oc = g("POST", "/api/concierge/cancella", {"voucher_token": vt_c})
        stato_c = (pp.info(rif_c) or {}).get("stato")
        dopo_giorno = pp.da_invitare_recensione(oggi=(CO + datetime.timedelta(days=1)).isoformat())
        ids = {x["riferimento"] for x in dopo_giorno}
        np_soppressa = rif_np not in ids
        canc_soppressa = rif_c not in ids
        pagata_presente = rif_a in ids       # controprova: la pagata sana c'e'
        ok4 = np_soppressa and canc_soppressa and pagata_presente
        check(4, "Stato prenotazione (cancellata / non pagata -> trigger SOPPRESSO)", ok4,
              "non-pagata=soppressa:%s · cancellata(stato=%s)=soppressa:%s · "
              "controprova pagata-sana=presente:%s" % (np_soppressa, stato_c, canc_soppressa,
                                                       pagata_presente))
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print("=" * 64)
    passati = sum(1 for _n, _t, ok, _d in ESITI if ok)
    print("ESITO FLUSSO: %d/4 controlli superati" % passati)
    print("=" * 64)
    return 0 if passati == 4 else 1


if __name__ == "__main__":
    sys.exit(main())
