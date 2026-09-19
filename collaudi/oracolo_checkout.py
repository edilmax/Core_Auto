"""IL SECONDO CONTO SUL PREVENTIVO DEL CHECKOUT (Tappa 1 della mappa di blindatura).

`test_quote_coerenza.py` verifica che la RISPOSTA sia coerente CON SE STESSA (le identita'
fra i suoi campi, su mille preventivi caotici). Qui si fa il passo che manca: si RICALCOLA
ogni componente DA ZERO, con regole scritte a parte, e si confronta con cio' che il motore
vera dice:

  listino  = notti x prezzo dichiarato dall'host
  sconto_lungo = listino x bps(mese se >=28 notti, altrimenti settimana se >=7) // 10000
  sconto_nr    = (listino - sconto_lungo) x 12% se la politica e' non_rimborsabile
  netto   = listino - sconto_lungo - sconto_nr
  comm    = netto x RAMPA(eta' host, fonte) // 10000     [0% <90gg · 8% <1anno · 10% · 5% diretto]
  tassa   = pp x min(notti, max_notti) x ospiti + perc x netto // 10000   [regola del comune]
  guest   = netto - sconto_credito                        [griglia senza credito: vedi confini]
  totale  = guest + tassa                                 <- QUELLO CHE L'OSPITE PAGA
  carta   = totale x (5% euro | 7% valuta estera) // 10000 + 0,25          [a carico HOST]
  netto_host = netto - comm - carta

Le costanti qui sono scritte A MANO e NON importate: il test-testimone le confronta con
quelle di produzione (fase98), cosi' se qualcuno le cambia l'oracolo grida invece di
seguire il cambiamento in silenzio (il difetto di ogni secondo conto che copia il primo).

CONFINI DICHIARATI: il credito fondatore non entra nella griglia (lo copre gia' il fratello
`test_quote_coerenza`, invariante B); il tetto per-persona della tassa e il ramo
`prezzo_non_sostenibile` non vengono esercitati (i prezzi della griglia li rendono impossibili).
Uso:  python collaudi/oracolo_checkout.py   (stampa il conto)  ·  import da test_oracolo_checkout.
"""
import datetime
import json
import shutil
import tempfile
import time

# ── LE REGOLE DEL SECONDO CONTO (scritte a mano: il testimone le vigila) ──────────
RAMPA_GIORNI_GRATIS = 90
RAMPA_BPS_FASE1 = 800
RAMPA_GIORNI_FASE1 = 365
RAMPA_BPS_REGIME = 1000       # = COMMISSIONE_BPS di serie, che la griglia usa
BPS_DIRETTO = 500
SCONTO_NR_BPS = 1200
PSP_BPS = 500                 # annuncio nella valuta d'incasso
PSP_BPS_ESTERA = 700          # annuncio in altra valuta: il gateway converte
PSP_FISSO_CENTS = 25


def rampa_bps(giorni, fonte):
    """La commissione che il secondo conto si aspetta (indipendente da fase98)."""
    if str(fonte or "").lower() == "diretto":
        return BPS_DIRETTO
    g = giorni if isinstance(giorni, int) and giorni >= 0 else 10 ** 9
    if g < RAMPA_GIORNI_GRATIS:
        return 0
    if g < RAMPA_GIORNI_FASE1:
        return RAMPA_BPS_FASE1
    return RAMPA_BPS_REGIME


def tassa_attesa(pp_cents, perc_bps, max_notti, notti, ospiti, imponibile_cents):
    """Il secondo conto della tassa di soggiorno (indipendente da fase66)."""
    notti_tass = min(notti, max_notti) if max_notti else notti
    return pp_cents * notti_tass * ospiti + perc_bps * imponibile_cents // 10000


def carta_attesa(totale_cents, valuta_annuncio, valuta_incasso):
    bps = PSP_BPS if str(valuta_annuncio).upper() == str(valuta_incasso).upper() \
        else PSP_BPS_ESTERA
    return totale_cents * bps // 10000 + (PSP_FISSO_CENTS if totale_cents > 0 else 0)


def riconta(risposta, scheda, guasto_attesi=None):
    """Il secondo conto su UNA risposta della rotta quote. -> lista di divergenze.

    `guasto_attesi(attesi)` e' il secondo punto d'iniezione (per il test che grida):
    riceve il dizionario degli attesi PRIMA del confronto e puo' corromperne UN cent."""
    fuori = []
    notti = scheda["notti"]
    ospiti = scheda["party"]
    listino = notti * scheda["prezzo"]
    bps = 0
    if notti >= 28 and scheda["sconto_mese_bps"] > 0:
        bps = scheda["sconto_mese_bps"]
    elif notti >= 7:
        bps = scheda["sconto_settimana_bps"]
    sconto_lungo = listino * max(bps, 0) // 10000
    netto_dopo_lungo = listino - sconto_lungo
    sconto_nr = netto_dopo_lungo * SCONTO_NR_BPS // 10000 \
        if scheda["politica"] == "non_rimborsabile" else 0
    netto = netto_dopo_lungo - sconto_nr
    comm = netto * rampa_bps(scheda["giorni_host"], scheda["fonte"]) // 10000
    tassa = tassa_attesa(scheda["tassa_pp"], scheda["tassa_perc"], scheda["tassa_max_notti"],
                         notti, ospiti, netto)
    guest = netto                       # griglia senza credito (confine dichiarato)
    totale = guest + tassa
    carta = carta_attesa(totale, scheda["valuta"], scheda["valuta_incasso"])
    attesi = {
        "notti": notti,
        "prezzo_listino_cents": listino,
        "sconto_soggiorno_lungo_cents": sconto_lungo,
        "sconto_non_rimborsabile_cents": sconto_nr,
        "prezzo_netto_cents": netto,
        "commissione_cents": comm,
        "prezzo_guest_cents": guest,
        "tassa_soggiorno_cents": tassa,
        "totale_cents": totale,
        "costo_pagamento_cents": carta,
        "netto_host_cents": netto - comm - carta,
    }
    if guasto_attesi is not None:
        guasto_attesi(attesi)
    for campo, atteso in attesi.items():
        if risposta.get(campo) != atteso:
            fuori.append("%s: atteso %r, il motore dice %r [%s]"
                         % (campo, atteso, risposta.get(campo), scheda["etichetta"]))
    return fuori


# ── IL BANCO: sistema vero, annunci veri, quote vere dalla rotta ──────────────────
def _backdate(percorso_db, email, giorni):
    """Porta la registrazione dell'host indietro di `giorni` (per la rampa)."""
    import sqlite3
    con = sqlite3.connect(percorso_db)
    try:
        con.execute("UPDATE host SET creato_ts=? WHERE email=?",
                    (int(time.time()) - giorni * 86400, email))
        con.commit()
    finally:
        con.close()


def _schede():
    """Le schede degli annunci: tre eta' di host x tre confezioni di regole."""
    return ([
        # (etichetta, giorni_host, prezzo, sconto_sett_bps, sconto_mese_bps, politica,
        #  tassa_pp, tassa_perc, tassa_max_notti, valuta)
        ("giovane-base", 10, 18000, 0, 0, "flessibile", 0, 0, 0, "EUR"),
        ("giovane-tassa-sconti", 10, 33333, 1000, 2000, "flessibile", 300, 0, 5, "EUR"),
        ("giovane-nr-perc", 10, 7000, 0, 0, "non_rimborsabile", 0, 100, 0, "EUR"),
        ("medio-base", 100, 18000, 0, 0, "flessibile", 0, 0, 0, "EUR"),
        ("medio-tassa-sconti", 100, 33333, 1000, 2000, "flessibile", 300, 0, 5, "EUR"),
        ("medio-estera", 100, 18000, 0, 0, "flessibile", 0, 0, 0, "USD"),
        ("medio-yen", 100, 18000, 0, 0, "flessibile", 0, 0, 0, "JPY"),
        ("vecchio-base", 400, 18000, 0, 0, "flessibile", 0, 0, 0, "EUR"),
        ("vecchio-nr-sconti", 400, 33333, 1000, 2000, "non_rimborsabile", 300, 0, 5, "EUR"),
        ("vecchio-estera", 400, 25000, 1500, 2500, "flessibile", 200, 0, 7, "USD"),
    ], None)


NOTI_GRIGLIA = (1, 2, 6, 7, 8, 27, 28, 30)     # i confini degli sconti lungo
PARTY_GRIGLIA = (1, 2, 3)
FONTI = ("marketplace", "diretto")


def confronta(guasto=None, guasto_attesi=None):
    """Il giro della griglia sul motore VERO. -> (provate, differenze, eccezioni).

    `guasto(scheda)` corrompe la scheda prima del riconto, `guasto_attesi(attesi)`
    corrompe gli attesi un attimo prima del confronto: sono i due punti d'iniezione
    per provare che l'oracolo GRIDA (regola 10: un allarme provato in un verso solo
    e' un ornamento)."""
    d = tempfile.mkdtemp(prefix="oracolo_checkout_")
    provate, differenze, eccezioni = 0, [], []
    try:
        r, oggi, per_eta = banco(d)
        for (nome, eta, prezzo, s_sett, s_mese, pol, t_pp, t_perc, t_max, valuta) in _schede()[0]:
            slug = "oracolo-" + nome
            for notti in NOTI_GRIGLIA:
                for party in PARTY_GRIGLIA:
                    for fonte in FONTI:
                        scheda = {
                            "etichetta": "%s n%d p%d %s" % (nome, notti, party, fonte),
                            "notti": notti, "party": party, "fonte": fonte,
                            "prezzo": prezzo, "sconto_settimana_bps": s_sett,
                            "sconto_mese_bps": s_mese, "politica": pol,
                            "tassa_pp": t_pp, "tassa_perc": t_perc,
                            "tassa_max_notti": t_max, "valuta": valuta,
                            "valuta_incasso": "EUR", "giorni_host": eta,
                        }
                        if guasto is not None:
                            guasto(scheda)
                        ci = oggi + datetime.timedelta(days=10)
                        co = ci + datetime.timedelta(days=notti)
                        try:
                            s, corpo = r.gestisci("POST", "/api/concierge/quote", {},
                                                  json.dumps({"alloggio_id": slug,
                                                              "check_in": ci.isoformat(),
                                                              "check_out": co.isoformat(),
                                                              "party": party,
                                                              "fonte": fonte}))
                        except Exception as e:                      # il contratto dice MAI
                            eccezioni.append("%s: %r" % (scheda["etichetta"], e))
                            continue
                        if s != 200:
                            eccezioni.append("%s: HTTP %s %r"
                                             % (scheda["etichetta"], s, corpo))
                            continue
                        provate += 1
                        differenze.extend(riconta(corpo, scheda, guasto_attesi))
        return provate, differenze, eccezioni
    finally:
        shutil.rmtree(d, ignore_errors=True)


def banco(d):
    """Il banco del secondo conto: sistema vero in `d`, tre host di 10/100/400 giorni,
    nove annunci con le regole della griglia. -> (router, oggi, {eta: slug->prezzo...}).

    Usato da `confronta` e dai test di proprieta': UN posto solo per la semina, cosi'
    il banco non puo' divergere fra chi conta e chi confronta."""
    import json as _json
    from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
    from fase83_server import crea_router
    from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

    cfg = ConfigCasaVIP(
        abilitato=True, segreto_hmac=b"O" * 32, con_registrazione_host=True,
        db_catalogo=d + "/c.db", db_inventario=d + "/i.db",
        db_registro_host=d + "/r.db", db_accettazioni=d + "/a.db",
        db_pendenti=d + "/p.db", db_payout=d + "/po.db", db_finanza=d + "/f.db",
        db_garanzia=d + "/g.db", db_tassa_comunale=d + "/t.db",
        commissione_bps=RAMPA_BPS_REGIME, promo_lancio_attiva=True,
        psp_bps=PSP_BPS, psp_bps_valuta_estera=PSP_BPS_ESTERA,
        psp_fisso_cents=PSP_FISSO_CENTS, valuta="EUR")
    sistema = crea_sistema(cfg)
    r = crea_router(sistema, host_key="hk", admin_key="ak")

    def g(m, p, b=None, h=None):
        return r.gestisci(m, p, {}, _json.dumps(b) if b is not None else None, h or {})

    schede, _ = _schede()
    oggi = datetime.date.today()
    per_eta = {10: "host10@oracolo.it", 100: "host100@oracolo.it", 400: "host400@oracolo.it"}
    token = {}
    for eta, email in per_eta.items():
        s, c = g("POST", "/api/host/registrazione",
                 {"email": email, "password": "password1", "accetta_termini": True,
                  "accetta_clausole": True, "accetta_privacy": True,
                  "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        if s != 201:
            raise RuntimeError("registrazione %s: %s %r" % (email, s, c))
        token[eta] = c["token"]
        _backdate(d + "/r.db", email, eta)
    per_slug = {}
    for (nome, eta, prezzo, s_sett, s_mese, pol, t_pp, t_perc, t_max, valuta) in schede:
        slug = "oracolo-" + nome
        s, c = g("POST", "/api/host/pubblica",
                 {"slug": slug, "titolo": "Casa " + nome, "citta": "Roma", "paese": "IT",
                  "cin": "IT058091C2X5V0ABCD", "prezzo_notte_cents": prezzo, "capacita": 4,
                  "valuta": valuta, "sconto_settimana_bps": s_sett,
                  "sconto_mese_bps": s_mese, "politica_cancellazione": pol,
                  "tassa_pp_notte_cents": t_pp, "tassa_perc_bps": t_perc,
                  "tassa_max_notti": t_max},
                 {"X-Host-Token": token[eta]})
        if s != 201:
            raise RuntimeError("pubblica %s: %s %r" % (slug, s, c))
        s, c = g("POST", "/api/host/disponibilita_range",
                 {"alloggio_id": slug, "da": oggi.isoformat(),
                  "a": (oggi + datetime.timedelta(days=120)).isoformat(),
                  "unita_totali": 2, "prezzo_netto_cents": prezzo},
                 {"X-Host-Token": token[eta]})
        if s != 200:
            raise RuntimeError("disponibilita %s: %s %r" % (slug, s, c))
        per_slug[slug] = {"prezzo": prezzo, "giorni_host": eta, "valuta": valuta}
    return r, oggi, per_slug


def conto():
    """Stampa il conto (uso manuale: python collaudi/oracolo_checkout.py)."""
    provate, differenze, eccezioni = confronta()
    print("provate=%d differenze=%d eccezioni=%d" % (provate, len(differenze), len(eccezioni)))
    for riga in (differenze + eccezioni)[:10]:
        print("  " + riga)
    guasto = bool(differenze or eccezioni or provate < 300)
    return 1 if guasto else 0


if __name__ == "__main__":
    import sys
    sys.exit(conto())
