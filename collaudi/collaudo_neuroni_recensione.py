"""COLLAUDO PROFONDO 'A NEURONI' del ciclo di vita della recensione — 0 ERRORI.
Percorre TUTTE le regole esistenti (neuroni), i collegamenti e i sotto-sotto-neuroni
fino allo stato terminale, poi una simulazione MISTA sostenuta (durata) che riverifica
gli invarianti a ogni giro. In-process sul sistema vero (nessun contatto col sito online).
"""
import concurrent.futures as cf
import datetime
import json
import os
import random
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

from fase63_recensioni import EmettitoreDiritto
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router, pagina_recensione_html
from fase86_email import corpo_invito_recensione_html
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

BASE = "https://bookinvip.com"
LINGUE = ["it", "en", "es", "fr", "de", "pt", "ja", "zh"]
CLUTTER = ("btnCanc", "chBox", "ckBox", "PIN check-in", "Cancella prenotazione",
           "Check-in online", "smart_pass")
MAPPA = []      # (neurone, regola, ok, dettaglio)


def N(neurone, regola, ok, dettaglio=""):
    MAPPA.append((neurone, regola, bool(ok), dettaglio))
    if not ok:
        print("   [KO] %s / %s  %s" % (neurone, regola, dettaglio), flush=True)


def build(d, unita=400):
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
             {"email": "host@n.it", "password": "password1", "accetta_termini": True,
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
       "unita_totali": unita, "prezzo_netto_cents": 24500}, tk)
    return sis, r, g


def prenota(sis, r, g, email, paga=True, giorni_ci=3, giorni_co=5):
    oggi = datetime.date.today()
    ci = (oggi + datetime.timedelta(days=giorni_ci)).isoformat()
    co = (oggi + datetime.timedelta(days=giorni_co)).isoformat()
    s, q = g("POST", "/api/concierge/quote",
             {"alloggio_id": "attico", "check_in": ci, "check_out": co, "party": 2})
    if s != 200:
        return None, None
    s, b = g("POST", "/api/concierge/book", {"quote_token": q["quote_token"], "email": email})
    if s != 201:
        return None, None
    rif, vt = b["riferimento"], b["voucher_token"]
    if paga:
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"metadata": {"riferimento": rif}}}})
        r.gestisci("POST", "/api/payments/webhook", {}, pl,
                   {"Stripe-Signature": firma_di_test(pl, "whsec_x", int(time.time()))})
    return rif, vt


def concluso(sis, vt):
    """Rifirma il voucher con check-out a ieri (soggiorno concluso)."""
    d = sis.firma.decodifica(vt)
    d["check_out"] = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    return sis.firma.codifica(d)


def maturo(sis, rif, allog="attico"):
    return EmettitoreDiritto(sis.firma).emetti(rif, allog, non_prima_ts=int(time.time()) - 60)


# ══════════════════════ NEURONE A — ELIGIBILITÀ (endpoint) ══════════════════════
def neurone_A(sis, r, g):
    rif, vt = prenota(sis, r, g, "a@n.it")
    # A1 pagata+conclusa -> 201 + verificata
    s, o = g("POST", "/api/recensioni", {"token": maturo(sis, rif), "voto": 5,
                                         "categorie": {"pulizia": 5}})
    N("A-eligibilita", "A1 pagata+conclusa->201+verificata", s == 201 and o.get("verificata"),
      "s=%s verificata=%s" % (s, o.get("verificata")))
    # A5 gia' recensita -> 409
    s, o = g("POST", "/api/recensioni", {"token": maturo(sis, rif), "voto": 1})
    N("A-eligibilita", "A5 gia'-recensita->409", s == 409, "s=%s" % s)
    # A2 prima del check-out (nbf futuro) -> 400 troppo_presto
    rif2, _ = prenota(sis, r, g, "a2@n.it")
    tokf = EmettitoreDiritto(sis.firma).emetti(rif2, "attico", non_prima_ts=int(time.time()) + 3600)
    s, o = g("POST", "/api/recensioni", {"token": tokf, "voto": 5})
    N("A-eligibilita", "A2 prima-del-checkout->respinta", s != 201 and o.get("motivo") == "troppo_presto",
      "s=%s motivo=%s" % (s, o.get("motivo")))
    # A3 non pagata -> respinta (402)
    rif3, _ = prenota(sis, r, g, "a3@n.it", paga=False)
    s, o = g("POST", "/api/recensioni", {"token": maturo(sis, rif3), "voto": 5})
    N("A-eligibilita", "A3 non-pagata->respinta", s != 201, "s=%s motivo=%s" % (s, o.get("motivo")))
    # A4 cancellata -> respinta
    rif4, vt4 = prenota(sis, r, g, "a4@n.it")
    g("POST", "/api/concierge/cancella", {"voucher_token": vt4})
    s, o = g("POST", "/api/recensioni", {"token": maturo(sis, rif4), "voto": 5})
    N("A-eligibilita", "A4 cancellata->respinta", s != 201, "s=%s stato=%s"
      % (s, (sis.pagamenti_pendenti.info(rif4) or {}).get("stato")))
    # A6 diritto forgiato (chiave sbagliata) -> respinta
    forg = EmettitoreDiritto(type(sis.firma)(b"Z" * 32)).emetti(rif, "attico",
                                                                non_prima_ts=int(time.time()) - 60)
    s, o = g("POST", "/api/recensioni", {"token": forg, "voto": 5})
    N("A-eligibilita", "A6 diritto-forgiato->respinta", s != 201, "s=%s" % s)


# ══════════════ NEURONE B — PAGINA /recensione/ (stati × 8 lingue) ══════════════
def neurone_B(sis, r, g):
    rif, vt = prenota(sis, r, g, "b@n.it")
    vtc = concluso(sis, vt)
    # B1 conclusa+non-recensita -> form
    for lng in LINGUE:
        pag = pagina_recensione_html(sis, vtc, lng)
        ok = pag is not None and "recBox" in pag and "/api/recensioni" in pag
        N("B-pagina", "B1 form-presente[%s]" % lng, ok, "" if ok else "form assente")
        # B6 nessuna roba del voucher, in NESSUNA lingua
        leak = pag and [c for c in CLUTTER if c in pag]
        N("B-pagina", "B6 no-clutter[%s]" % lng, not leak, "leak=%s" % leak)
    # B2 prima del check-out -> niente form
    fut = sis.firma.codifica({**sis.firma.decodifica(vt),
                              "check_out": (datetime.date.today()
                                            + datetime.timedelta(days=9)).isoformat()})
    pag = pagina_recensione_html(sis, fut, "it")
    N("B-pagina", "B2 prima-checkout->niente-form", pag is not None and "recBox" not in pag, "")
    # B3 cancellata -> niente form
    rifc, vtc2 = prenota(sis, r, g, "b3@n.it")
    g("POST", "/api/concierge/cancella", {"voucher_token": vtc2})
    pag = pagina_recensione_html(sis, concluso(sis, vtc2), "it")
    N("B-pagina", "B3 cancellata->niente-form", pag is not None and "recBox" not in pag, "")
    # B4 gia' recensita -> grazie
    g("POST", "/api/recensioni", {"token": maturo(sis, rif), "voto": 5})
    pag = pagina_recensione_html(sis, vtc, "it")
    N("B-pagina", "B4 gia'-recensita->grazie", pag is not None and "recBox" not in pag
      and "verificata" in pag, "")
    # B5 token invalido -> None
    N("B-pagina", "B5 token-invalido->None",
      pagina_recensione_html(sis, "rotto") is None and pagina_recensione_html(sis, vt[:-3] + "AAA") is None, "")


# ═══════════ NEURONE C — EMAIL/SELEZIONE (da_invitare_recensione) ═══════════
def neurone_C(sis, r, g):
    pp = sis.pagamenti_pendenti
    oggi = datetime.date.today()
    co = oggi + datetime.timedelta(days=5)
    dopo = (co + datetime.timedelta(days=1)).isoformat()
    rif, vt = prenota(sis, r, g, "c@n.it")

    def sel(giorno):
        return {x["riferimento"]: x for x in pp.da_invitare_recensione(oggi=giorno)}

    # C2 solo conclusa (prima del check-out non c'e')
    N("C-email", "C2 solo-conclusa", rif not in sel((co - datetime.timedelta(days=1)).isoformat())
      and rif in sel(dopo), "")
    # C1 solo pagata
    rif_np, _ = prenota(sis, r, g, "cnp@n.it", paga=False)
    N("C-email", "C1 solo-pagata", rif_np not in sel(dopo), "")
    # C3 finestra 14 giorni (oltre non si spamma)
    lontano = (co + datetime.timedelta(days=20)).isoformat()
    N("C-email", "C3 finestra-14gg", rif not in sel(lontano), "")
    # C5 una sola volta
    pp.segna_invito_recensione(rif)
    N("C-email", "C5 una-volta-sola", rif not in sel(dopo), "")
    # C4 email presente (riga senza email non selezionata) — controllo strutturale
    righe = sel(dopo)
    N("C-email", "C4 email-presente", all(x.get("email") for x in righe.values()), "")
    # C6 link dell'email -> /recensione/ + token, zero voucher/script
    rif2, _ = prenota(sis, r, g, "c6@n.it")
    rec = sel(dopo)[rif2]
    dj = json.loads(rec.get("corpo_json") or "{}")
    vt2 = dj.get("voucher_token", "")
    vurl = BASE + "/recensione/" + vt2
    html = corpo_invito_recensione_html(dj.get("titolo") or "attico", vurl)
    link = (re.search(r'href="([^"]+)"', html) or [None, ""])[1] if re.search(r'href="([^"]+)"', html) else ""
    ok = "/recensione/" in link and vt2 in link and "/voucher/" not in html and "<script" not in html
    N("C-email", "C6 link-giusto(/recensione/+token,no-voucher)", ok, "link=%s" % (link[:40] + "..."))


# ═══════════════════ NEURONE D — MOTORE VOTI (fase63) ═══════════════════
def neurone_D(sis, r, g):
    rif, vt = prenota(sis, r, g, "d@n.it")
    # D1 voto fuori scala respinto (diritto NON consumato: si puo' ritentare)
    for v in (0, 6, -1, "5", None, 3.5, True):
        s, o = g("POST", "/api/recensioni", {"token": maturo(sis, rif), "voto": v})
        if s == 201:
            N("D-motore", "D1 voto-fuori-scala-respinto(%r)" % v, False, "ACCETTATO s=201")
            return
    N("D-motore", "D1 voto-fuori-scala-respinto", True, "0/6/-1/str/None/float/bool tutti respinti")
    # D2 categorie invalide respinte
    for cat in ({"jacuzzi": 5}, {"pulizia": 9}, {"pulizia": 0}, {"pulizia": "x"}):
        s, o = g("POST", "/api/recensioni", {"token": maturo(sis, rif), "voto": 5, "categorie": cat})
        if s == 201:
            N("D-motore", "D2 categorie-invalide-respinte(%r)" % cat, False, "ACCETTATO")
            return
    N("D-motore", "D2 categorie-invalide-respinte", True, "")
    # D3 medie per categoria: il riepilogo DEVE combaciare col RICALCOLO dall'elenco
    # (robusto allo stato condiviso coi neuroni precedenti) ed essere INTERO al centesimo.
    s, o = g("POST", "/api/recensioni", {"token": maturo(sis, rif), "voto": 4,
                                         "categorie": {"pulizia": 5, "comfort": 4}})
    rif2, _ = prenota(sis, r, g, "d2@n.it")
    g("POST", "/api/recensioni", {"token": maturo(sis, rif2), "voto": 2,
                                  "categorie": {"pulizia": 3}})
    rie = sis.recensioni.riepilogo("attico")
    recs = sis.recensioni.elenco("attico", limit=500)
    pul_votes = [x["categorie"]["pulizia"] for x in recs
                 if x.get("categorie") and "pulizia" in x["categorie"]]
    exp = round(sum(pul_votes) * 100 / len(pul_votes)) if pul_votes else None
    got = rie["categorie"].get("pulizia", {}).get("media_centesimi")
    completo = len(recs) == rie["conteggio"]
    N("D-motore", "D3 medie-per-categoria=ricalcolo+intere",
      isinstance(got, int) and (not completo or got == exp),
      "pulizia riepilogo=%s ricalcolo=%s (%d voti, elenco-completo=%s)"
      % (got, exp, len(pul_votes), completo))
    # D4 una per prenotazione (gia' in A/altro), D5 verificata=paid
    N("D-motore", "D5 verificata=pagata", o.get("verificata") is True, "verificata=%s" % o.get("verificata"))


# ═══════ NEURONE E — INVARIANTI sotto SIMULAZIONE MISTA (durata) ═══════
def neurone_E(giri):
    tot_voti = 0
    for giro in range(giri):
        d = tempfile.mkdtemp()
        try:
            sis, r, g = build(d, unita=400)

            def gg(m, p, b=None, h=None):
                return r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

            eligibili = set()      # rif che POSSONO recensire (pagati, non cancellati)
            attesi = {}            # rif -> deve risultare recensito
            n = 60
            pren = []
            for i in range(n):
                stato = random.choice(["pagato", "pagato", "pagato", "non_pagato", "cancellato"])
                rif, vt = prenota(sis, r, gg, "m%d@n.it" % i, paga=(stato != "non_pagato"))
                if not rif:
                    continue
                if stato == "cancellato":
                    gg("POST", "/api/concierge/cancella", {"voucher_token": vt})
                elif stato == "pagato":
                    eligibili.add(rif)
                pren.append((rif, vt, stato))

            # guida OGNI prenotazione fino allo stato terminale: prova a recensire dalla
            # PAGINA pulita (solo gli eligibili devono riuscire); alcuni non votano.
            def guida(item):
                rif, vt, stato = item
                pag = pagina_recensione_html(sis, concluso(sis, vt), random.choice(LINGUE))
                if pag and any(c in pag for c in CLUTTER):
                    return ("leak", rif)
                if pag is None or "recBox" not in pag:
                    return ("noform", rif)           # cancellati/non-eligibili: niente form (ok)
                tok = (re.search(r'"tok":\s*"([^"]+)"', pag) or [None, ""])[1]
                if random.random() < 0.15:
                    return ("skip", rif)             # ospite che non vota
                s, o = gg("POST", "/api/recensioni",
                          {"token": tok, "voto": random.randint(1, 5),
                           "categorie": {"pulizia": random.randint(1, 5)}})
                return ("ok" if s == 201 else "no%d" % s, rif)

            with cf.ThreadPoolExecutor(max_workers=24) as ex:
                esiti = list(ex.map(guida, pren))
            tot_voti += sum(1 for e, _ in esiti if e == "ok")

            # leak in QUALSIASI pagina = errore fatale
            if any(e == "leak" for e, _ in esiti):
                N("E-invarianti", "E6 pagina-mai-clutter", False, "LEAK in un giro")
            # un NON-eligibile che riesce a recensire = errore
            for e, rif in esiti:
                if e == "ok" and rif not in eligibili:
                    N("E-invarianti", "E1 solo-eligibili-recensiscono", False, "rif non-eligibile ha votato")

            rie = sis.recensioni.riepilogo("attico")
            recs = sis.recensioni.elenco("attico", limit=500)      # store diretto, no pagina
            ids = [x["prenotazione_id"] for x in recs]
            # E1 ogni recensione appartiene a un eligibile
            estranei = [i for i in ids if i not in eligibili]
            if estranei:
                N("E-invarianti", "E1 nessuna-recensione-di-non-pagati/cancellati", False,
                  "estranei=%d" % len(estranei))
            # E2 nessun doppione
            if len(ids) != len(set(ids)):
                N("E-invarianti", "E2 nessun-doppione", False, "doppi=%d" % (len(ids) - len(set(ids))))
            # E3 conteggio coerente
            if rie["conteggio"] != len(recs):
                N("E-invarianti", "E3 conteggio-coerente", False,
                  "conteggio=%s len=%s" % (rie["conteggio"], len(recs)))
            # E4 medie ricalcolate combaciano
            if recs:
                media_calc = round(sum(x["voto"] for x in recs) * 100 / len(recs))
                if abs(media_calc - rie["media_centesimi"]) > 1:
                    N("E-invarianti", "E4 medie-ricalcolate", False,
                      "calc=%s dato=%s" % (media_calc, rie["media_centesimi"]))
        finally:
            shutil.rmtree(d, ignore_errors=True)
        print("  giro E %d/%d fatto" % (giro + 1, giri), flush=True)
    # se nessun KO e' stato registrato, i cinque invarianti sono verdi
    for reg in ("E1 nessuna-recensione-di-non-pagati/cancellati", "E2 nessun-doppione",
                "E3 conteggio-coerente", "E4 medie-ricalcolate", "E6 pagina-mai-clutter"):
        if not any(m[1] == reg and not m[2] for m in MAPPA):
            N("E-invarianti", reg, True, "")
    return tot_voti


def main():
    giri = int(os.environ.get("GIRI", "15"))
    t0 = time.time()
    print("== Neuroni statici (A,B,C,D) ==", flush=True)
    d = tempfile.mkdtemp()
    try:
        sis, r, g = build(d)
        neurone_A(sis, r, g)
        neurone_B(sis, r, g)
        neurone_C(sis, r, g)
        neurone_D(sis, r, g)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print("== Neurone E — simulazione MISTA sostenuta (%d giri) ==" % giri, flush=True)
    voti = neurone_E(giri)

    print("=" * 66)
    per_neur = {}
    for neur, reg, ok, det in MAPPA:
        per_neur.setdefault(neur, [0, 0])
        per_neur[neur][0] += 1
        per_neur[neur][1] += 1 if ok else 0
    for neur in sorted(per_neur):
        tot, ok = per_neur[neur]
        print("  %-16s  %d/%d regole verdi" % (neur, ok, tot))
    errori = [(n, reg, d) for n, reg, ok, d in MAPPA if not ok]
    print("-" * 66)
    print("COLLAUDO A NEURONI: %d regole controllate, %d giri misti, ~%d voti, %.1fs"
          % (len(MAPPA), giri, voti, time.time() - t0))
    if not errori:
        print("VERDETTO: 0 ERRORI — TUTTI I NEURONI VERDI")
    else:
        print("VERDETTO: %d ERRORI:" % len(errori))
        for n, reg, det in errori:
            print("   - %s / %s  %s" % (n, reg, det))
    print("=" * 66)
    return 0 if not errori else 1


if __name__ == "__main__":
    sys.exit(main())
