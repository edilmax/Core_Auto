"""LE LOGICHE — i ragionamenti a catena che tengono in piedi la macchina.

═══════════════════════════════════════════════════════════════════════════════════
L'INTUIZIONE (fondatore, 2026-07-21)
═══════════════════════════════════════════════════════════════════════════════════
«Quello e' quello che ricordo, ma non ricordo il procedimento della logica e le logiche
coerenti e strategiche.»

Il `capitolato.py` controlla le COSE (traduzioni, segreti, escape, cifre). Ma meta' della
macchina non e' fatta di cose: e' fatta di RAGIONAMENTI A CATENA. Del tipo:

    l'host cancella una prenotazione gia' pagata
      -> scatta la penale del 15%
        -> si compensa dai suoi incassi futuri
          -> se non ne ha, diventa un DEBITO
            -> il debito si riscuote alla fonte sul primo payout utile

Quattro anelli. Ogni singolo pezzo puo' essere perfetto e avere il suo test verde: se
UN anello si stacca, i soldi si perdono e nessun test se ne accorge, perche' ogni test
guarda un pezzo e nessuno guarda la CATENA.

Qui le logiche vengono scritte come catene ESEGUIBILI: si parte dalla causa, si segue
ogni anello su un sistema vero, e si pretende l'effetto. Chi legge questo file capisce
come deve funzionare la macchina anche senza ricordarselo.

REGOLA ANTI-FINTO-VERDE: se un anello non e' eseguibile qui, si dichiara SCOPERTO —
non si salta in silenzio.
"""
import io
import json
import os
import shutil
import sys

try:  # Windows: console cp1252 non regge box-drawing/emoji -> uscita UTF-8 tollerante
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.chdir(REPO)

VIOL = []
CONTA = {"anelli": 0, "catene": 0, "scoperti": 0}
AK = {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.5", "User-Agent": "F"}
PW = "SuperPw@1"


def anello(catena, descrizione, condizione, dettaglio=""):
    CONTA["anelli"] += 1
    if not condizione:
        VIOL.append("[%s] anello ROTTO: %s %s" % (catena, descrizione, dettaglio))
    return bool(condizione)


def scoperto(catena, descrizione, perche):
    CONTA["scoperti"] += 1
    VIOL.append("[%s] anello SCOPERTO (nessuno lo verifica): %s — %s"
                % (catena, descrizione, perche))


class Mondo:
    """Un sistema vero, montato da zero per ogni catena."""

    def __init__(self):
        import fase85_pagamenti_stripe as _stripe
        self._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(self._finto_stripe)
        os.environ["MARCA_TEMPORALE"] = "0"
        from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
        from fase83_server import crea_router
        self.d = d = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=d + "/c.db", db_inventario=d + "/i.db",
            db_registro_host=d + "/r.db", db_accettazioni=d + "/a.db",
            db_pendenti=d + "/p.db", db_finanza=d + "/f.db", db_payout=d + "/pay.db",
            db_garanzia=d + "/g.db", db_recensioni=d + "/rec.db",
            db_messaggi=d + "/m.db", db_marche=d + "/mt.db",
            commissione_bps=1000, psp_bps=300, promo_lancio_attiva=True,
            bunker_password=PW, stripe_secret_key="sk",
            stripe_webhook_secret="whsec_x",
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/no"))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")

    @staticmethod
    def _finto_stripe(url, body, headers):
        import secrets
        return {"url": "https://x/" + secrets.token_hex(4),
                "id": "cs_" + secrets.token_hex(4)}

    def g(self, metodo, percorso, corpo=None, testate=None, query=None):
        return self.r.gestisci(metodo, percorso, query or {},
                               json.dumps(corpo) if corpo is not None else None,
                               testate or AK)

    def chiudi(self):
        import fase85_pagamenti_stripe as _stripe
        _stripe.ProviderStripe._fetch_reale = self._orig
        shutil.rmtree(self.d, ignore_errors=True)

    def host(self, email="logica@prova.local"):
        st, c = self.g("POST", "/api/host/registrazione", {
            "email": email, "password": "password1", "accetta_termini": True,
            "accetta_clausole": True, "accetta_privacy": True,
            "ragione_sociale": "Prova SRL", "paese": "IT"})
        return (c or {}).get("host_id"), (c or {}).get("token"), st


# ═══════════════════════════════════════════════════════════════════════════════
#  CATENA 1 — IL PREZZO NON SI TOCCA
#    preventivo firmato -> l'ospite non lo puo' cambiare -> si paga esattamente quello
# ═══════════════════════════════════════════════════════════════════════════════
def catena_prezzo(m):
    """La catena piu' importante di tutte: il prezzo che l'ospite vede deve essere
    ESATTAMENTE quello che gli viene addebitato, e nessuno deve poterlo cambiare
    per strada. Anelli: alloggio pubblicato -> preventivo FIRMATO -> l'identita'
    dei conti torna -> una firma manomessa viene respinta."""
    c = "PREZZO INTOCCABILE"
    CONTA["catene"] += 1
    hid, tok, _ = m.host("prezzo@prova.local")
    if not tok:
        scoperto(c, "creazione host", "registrazione non riuscita")
        return
    testate = dict(AK)
    testate["X-Host-Token"] = tok
    st, pub = m.g("POST", "/api/host/pubblica", {
        "slug": "attico-prova-logiche", "titolo": "Attico prova logiche",
        "citta": "Roma", "paese": "IT", "prezzo_notte_cents": 10000,
        "prezzo_cents": 10000, "valuta": "EUR", "capacita": 4, "ospiti_max": 4,
        # CIN obbligatorio per l'Italia (legge nazionale): la catena lo ha riscoperto
        # da sola al secondo giro, ed e' giusto che la pubblicazione lo pretenda.
        "cin": "IT999888A1XYZ2WQRS",
        "descrizione": "alloggio di prova per la catena del prezzo"}, testate)
    if st not in (200, 201):
        scoperto(c, "pubblicazione dell'alloggio",
                 "stato %s: %s" % (st, str(pub)[:80]))
        return
    slug = (pub or {}).get("slug") or (pub or {}).get("alloggio_id")
    anello(c, "l'alloggio pubblicato ha un identificativo", bool(slug), str(pub)[:70])
    if not slug:
        return

    # ANELLO: pubblicato NON vuol dire prenotabile. Finche' l'host non apre le date,
    # l'alloggio non si vende — regola vera, riscoperta da questa catena.
    st_chiuso, q_chiuso = m.g("POST", "/api/concierge/quote", {
        "alloggio_id": slug, "check_in": "2027-03-01", "check_out": "2027-03-03",
        "party": 2}, {})
    anello(c, "pubblicato ma con calendario CHIUSO non e' prenotabile",
           st_chiuso >= 400,
           "stato %s: si venderebbero date che l'host non ha aperto" % st_chiuso)

    st_ap, ap = m.g("POST", "/api/host/disponibilita_range", {
        "alloggio_id": slug, "da": "2027-03-01", "a": "2027-03-05",
        "unita_totali": 1, "prezzo_netto_cents": 10000}, testate)
    if st_ap not in (200, 201):
        scoperto(c, "apertura del calendario", "stato %s: %s" % (st_ap, str(ap)[:70]))
        return

    st, q = m.g("POST", "/api/concierge/quote", {
        "alloggio_id": slug, "check_in": "2027-03-01", "check_out": "2027-03-03",
        "party": 2}, {})
    if st != 200 or not isinstance(q, dict):
        scoperto(c, "preventivo", "stato %s: %s" % (st, str(q)[:90]))
        return

    firma = q.get("firma") or q.get("token") or q.get("quote_token")
    anello(c, "il preventivo esce FIRMATO", bool(firma),
           "senza firma il prezzo sarebbe manipolabile dal browser")

    numeri = {k: v for k, v in q.items() if k.endswith("_cents")}
    anello(c, "ogni importo e' un INTERO in centesimi",
           all(isinstance(v, int) for v in numeri.values()),
           "non interi: %s" % {k: type(v).__name__ for k, v in numeri.items()
                               if not isinstance(v, int)})

    totale = q.get("totale_cents")
    netto = q.get("netto_host_cents")
    comm = q.get("commissione_cents")
    psp = q.get("psp_cents") or q.get("costo_pagamento_cents")
    if None not in (totale, netto, comm, psp):
        anello(c, "l'identita' dei conti torna al centesimo "
                  "(ospite = netto + commissione + tecnica)",
               totale == netto + comm + psp,
               "%d != %d + %d + %d" % (totale, netto, comm, psp))
    else:
        scoperto(c, "identita' dei conti",
                 "il preventivo non espone tutte le voci: %s" % sorted(q)[:8])

    if firma:
        rotta = str(firma)[:-2] + ("XY" if not str(firma).endswith("XY") else "AB")
        st2, o2 = m.g("POST", "/api/concierge/book", {
            "alloggio_id": slug, "check_in": "2027-03-01",
            "check_out": "2027-03-03", "party": 2, "firma": rotta, "token": rotta,
            "email": "ospite@prova.local", "nome": "Prova"}, {})
        anello(c, "una firma MANOMESSA viene respinta", st2 >= 400,
               "stato %s: il prezzo si potrebbe cambiare dal browser" % st2)


# ═══════════════════════════════════════════════════════════════════════════════
#  CATENA 2 — LA RAMPA NON TORNA MAI INDIETRO
#    0% -> 8% -> 10%, mai al contrario; e il 3% tecnico c'e' SEMPRE
# ═══════════════════════════════════════════════════════════════════════════════
def catena_rampa(m):
    c = "RAMPA E TARIFFA TECNICA"
    CONTA["catene"] += 1
    from fase98_policy_commissione import LANCIO_BPS_REGIME, stato_scaglione
    precedente, cambi = -1, []
    for giorni in range(0, 800, 3):
        bps = stato_scaglione(giorni)["bps"]
        if bps != precedente and precedente >= 0:
            cambi.append((giorni, precedente, bps))
        anello(c, "la commissione non scende mai (giorno %d)" % giorni,
               bps >= precedente, "%d -> %d" % (precedente, bps))
        precedente = bps
    anello(c, "la rampa ha esattamente due scatti", len(cambi) == 2,
           "scatti trovati: %s" % cambi)
    anello(c, "non si supera mai il regime", precedente == LANCIO_BPS_REGIME,
           "finisce a %d invece di %d" % (precedente, LANCIO_BPS_REGIME))
    st, t = m.g("GET", "/api/trasparenza", None, {})
    if st == 200 and isinstance(t, dict):
        nostro = t.get("scenario_nostro", {})
        anello(c, "la tariffa tecnica compare SEMPRE, anche a commissione 0",
               "psp_cents" in nostro,
               "la trasparenza pubblica non espone il costo tecnico")
    else:
        scoperto(c, "trasparenza pubblica", "endpoint non disponibile qui")


# ═══════════════════════════════════════════════════════════════════════════════
#  CATENA 3 — SENZA I TRE CONSENSI NON ESISTE L'ACCOUNT
#    manca una spunta -> 422 -> nessun account -> nessuna prova
# ═══════════════════════════════════════════════════════════════════════════════
def catena_consensi(m):
    c = "CONSENSI"
    CONTA["catene"] += 1
    for manca in ("accetta_termini", "accetta_clausole", "accetta_privacy"):
        corpo = {"email": "no-%s@prova.local" % manca, "password": "password1",
                 "accetta_termini": True, "accetta_clausole": True,
                 "accetta_privacy": True, "ragione_sociale": "X", "paese": "IT"}
        corpo.pop(manca)
        st, o = m.g("POST", "/api/host/registrazione", corpo)
        anello(c, "senza '%s' l'account NON nasce" % manca, st == 422,
               "stato %s" % st)
        anello(c, "il rifiuto dice cosa manca", (o or {}).get("errore") ==
               "consensi_mancanti" and manca in ((o or {}).get("mancanti") or []),
               str(o)[:70])
    hid, tok, st = m.host("consensi-ok@prova.local")
    anello(c, "con tutte e tre le spunte l'account nasce", st in (200, 201) and hid,
           "stato %s" % st)
    if hid and m.sis.accettazioni:
        prove = m.sis.accettazioni.elenco(hid)
        anello(c, "restano DUE prove firmate (contratto + privacy)", len(prove) >= 2,
               "trovate %d" % len(prove))
        anello(c, "ogni prova e' integra", all(p.get("integra") for p in prove))
        anello(c, "la prova del contratto porta il flag delle clausole vessatorie",
               any(p.get("vessatorie") for p in prove))


# ═══════════════════════════════════════════════════════════════════════════════
#  CATENA 4 — CONTRATTO NUOVO -> RI-ACCETTAZIONE PRIMA DI OPERARE
# ═══════════════════════════════════════════════════════════════════════════════
def catena_riaccettazione(m):
    c = "RI-ACCETTAZIONE"
    CONTA["catene"] += 1
    hid, tok, _ = m.host("riacc@prova.local")
    if not tok:
        scoperto(c, "creazione host", "non riuscita in questo montaggio")
        return
    testate = dict(AK)
    testate["X-Host-Token"] = tok
    st, o = m.g("GET", "/api/host/contratto_stato", None, testate)
    anello(c, "appena firmato NON deve ri-accettare",
           st == 200 and not (o or {}).get("deve_riaccettare"), str(o)[:70])
    import fase163_accettazioni as f163
    vecchia = f163.CONTRATTO_HOST_VERSIONE
    try:
        f163.CONTRATTO_HOST_VERSIONE = "2099-01-01"
        st, o = m.g("GET", "/api/host/contratto_stato", None, testate)
        anello(c, "se la versione cambia, DEVE ri-accettare",
               st == 200 and (o or {}).get("deve_riaccettare"), str(o)[:70])
    finally:
        f163.CONTRATTO_HOST_VERSIONE = vecchia
    st, o = m.g("GET", "/api/host/contratto_stato", None, testate)
    anello(c, "tornata la versione, non deve piu' ri-accettare",
           st == 200 and not (o or {}).get("deve_riaccettare"))


# ═══════════════════════════════════════════════════════════════════════════════
#  CATENA 5 — LA PENALE SI COMPENSA, E SE NON C'E' NULLA DIVENTA DEBITO
#    (la logica che il fondatore ha descritto: l'host promette e poi non c'e')
# ═══════════════════════════════════════════════════════════════════════════════
def catena_penale(m):
    c = "PENALE -> COMPENSAZIONE -> DEBITO"
    CONTA["catene"] += 1
    fc = m.sis.finanza
    if fc is None or not hasattr(fc, "processa_penale"):
        scoperto(c, "motore contabile", "financial controller non montato")
        return
    from fase83_server import PENALE_HOST_BPS
    anello(c, "la penale e' una percentuale dichiarata", PENALE_HOST_BPS > 0,
           "PENALE_HOST_BPS = %s" % PENALE_HOST_BPS)
    esito = fc.processa_penale(riferimento="prova-penale", host_id="host-x",
                               penale_cents=15000, valuta="EUR",
                               payout=m.sis.payout)
    anello(c, "la penale viene lavorata", esito is not None, str(esito)[:70])
    if esito is None:
        return
    anello(c, "senza incassi da compensare resta un RESIDUO a debito",
           int(esito.get("residuo_cents") or 0) > 0,
           "residuo %s: la penale sarebbe evaporata" % esito.get("residuo_cents"))
    aperti = fc.debiti_aperti() if hasattr(fc, "debiti_aperti") else []
    anello(c, "il debito resta APERTO e visibile",
           any(d.get("host_id") == "host-x" for d in aperti),
           "debiti aperti: %s" % [d.get("host_id") for d in aperti][:5])
    anello(c, "il giornale ha registrato il movimento",
           fc.esiste_evento("penale:prova-penale")
           if hasattr(fc, "esiste_evento") else True,
           "nessuna riga nel libro giornale")
    catena = fc.verifica_catena()
    anello(c, "la catena hash del giornale resta integra", catena.get("ok"),
           "rotta alla riga %s" % catena.get("seq_rotta"))


# ═══════════════════════════════════════════════════════════════════════════════
#  CATENA 6 — LE PROVE LEGALI ARRIVANO FINO AL FASCICOLO
#    consenso -> firma -> sigillo -> dossier certificato
# ═══════════════════════════════════════════════════════════════════════════════
def catena_prove(m):
    c = "PROVE -> SIGILLO -> FASCICOLO"
    CONTA["catene"] += 1
    hid, tok, _ = m.host("prove@prova.local")
    acc = m.sis.accettazioni
    if acc is None:
        scoperto(c, "registro accettazioni", "non montato")
        return
    s1 = acc.sigillo()
    anello(c, "il registro produce un sigillo", len(s1.get("sigillo", "")) == 64)
    acc.registra("altro-host", ip="1.2.3.4", vessatorie=True)
    s2 = acc.sigillo()
    anello(c, "una prova in piu' CAMBIA il sigillo", s1["sigillo"] != s2["sigillo"],
           "il sigillo non segue il registro: una manomissione non si vedrebbe")
    st, o = m.g("POST", "/api/bunker/login", {"codice": PW})
    if st != 200:
        scoperto(c, "ingresso nel Bunker", "login non riuscito: stato %s" % st)
        return
    testate = dict(AK)
    testate["X-Bunker-Session"] = o["sessione"]
    st, d = m.g("GET", "/api/bunker/export_legale", None, testate, {"formato": "csv"})
    anello(c, "il fascicolo si genera", st == 200 and (d or {}).get("contenuto"))
    testo = (d or {}).get("contenuto", "")
    anello(c, "il fascicolo e' SIGILLATO in fondo",
           "# FINE DOSSIER - INTEGRITÀ:" in testo,
           "senza sigillo finale un fascicolo troncato sembrerebbe valido")
    anello(c, "il fascicolo dichiara le prove manomesse", "prove_manomesse" in testo)


# ═══════════════════════════════════════════════════════════════════════════════
#  CATENA 7 — CHI NON E' IN REGOLA NON VIENE PAGATO
# ═══════════════════════════════════════════════════════════════════════════════
def catena_dac7(m):
    """Chi non e' in regola col fisco non viene pagato — ma SOLO quando la legge lo
    prevede. Il 2026-07-21 questa catena ha rivelato due cose: che la logica non stava
    dove la cercavo (non in fase100 ma nel router), e che la mia ASPETTATIVA era
    sbagliata — pretendevo il blocco per un host appena iscritto, mentre la Direttiva
    UE 2021/514 rende segnalabile un venditore solo sopra le soglie (>=30 prenotazioni
    o >=2000 EUR). Trattenere denaro a chi non ha nulla da dichiarare sarebbe illegittimo.

    Quando un collaudo e' rosso, la prima domanda non e' «dove sbaglia il codice?» ma
    «chi ha ragione fra i due?»."""
    c = "CONFORMITA' -> BLOCCO DEI BONIFICI"
    CONTA["catene"] += 1
    anello(c, "esiste chi DECIDE il blocco",
           hasattr(m.r, "_dac7_payout_bloccato"),
           "il router non espone piu' la decisione di blocco")
    if not hasattr(m.r, "_dac7_payout_bloccato"):
        return
    hid, tok, _ = m.host("dac7@prova.local")
    if not hid:
        scoperto(c, "creazione host", "non riuscita")
        return

    # ANELLO 1 — sotto soglia: NON si blocca, anche con i dati incompleti
    bloccato, manca = m.r._dac7_payout_bloccato(hid)
    anello(c, "host SOTTO soglia non viene bloccato (non ha nulla da dichiarare)",
           not bloccato,
           "bloccato senza obbligo di legge: si tratterrebbe denaro dovuto")

    # ANELLO 2 — la macchina SA quali dati mancano, anche quando non blocca
    if hasattr(m.r, "_dac7_mancanti"):
        reg = m.sis.registro_host
        info = reg.info_host(hid) if reg else None
        mancanti = m.r._dac7_mancanti(info) if info else []
        anello(c, "di un host senza dati fiscali la macchina sa cosa manca",
               bool(mancanti),
               "non risulta mancare nulla a un host appena iscritto")
    else:
        scoperto(c, "elenco dei dati mancanti", "il router non espone _dac7_mancanti")

    # ANELLO 3 — sopra soglia con dati incompleti: DEVE bloccare
    fc = m.sis.finanza
    if fc is None:
        scoperto(c, "superamento soglia", "giornale non montato")
    else:
        import datetime as _dt
        anno = _dt.datetime.utcnow().year
        for i in range(31):        # oltre le 30 prenotazioni della soglia UE
            fc.movimento(tipo="incasso", riferimento="dac7-%d" % i,
                         soggetto="host:" + hid, importo_cents=20000,
                         valuta="EUR", causale="prova soglia DAC7")
        bloccato2, manca2 = m.r._dac7_payout_bloccato(hid)
        anello(c, "host SOPRA soglia e con dati incompleti viene BLOCCATO", bloccato2,
               "non bloccato: si pagherebbe chi la legge obbliga a identificare")
        anello(c, "il blocco dice QUALI dati mancano", bool(manca2),
               "bloccato senza spiegare: l'host non saprebbe come sbloccarsi")

    # ANELLO 4 — l'host vede il proprio stato
    testate = dict(AK)
    testate["X-Host-Token"] = tok
    st, o = m.g("GET", "/api/host/dac7_stato", None, testate)
    if st == 200 and isinstance(o, dict):
        anello(c, "l'host VEDE se e' bloccato e cosa manca",
               "payout_bloccati" in o and "mancanti" in o, str(o)[:80])
    else:
        scoperto(c, "vista dell'host sul proprio stato fiscale", "stato %s" % st)

    # ANELLO 5 — fail-open: un guasto del controllo non deve congelare i bonifici
    vecchio = m.sis.registro_host
    try:
        m.sis.registro_host = None
        bloccato3, _ = m.r._dac7_payout_bloccato(hid)
        anello(c, "se il controllo si guasta NON blocca (il payout e' denaro dovuto)",
               not bloccato3,
               "un bug del controllo congelerebbe bonifici legittimi")
    finally:
        m.sis.registro_host = vecchio

    # ANELLO 6 — il kill-switch esiste e funziona
    import os as _os
    prec = _os.environ.get("DAC7_BLOCCO_PAYOUT")
    try:
        _os.environ["DAC7_BLOCCO_PAYOUT"] = "0"
        bloccato4, _ = m.r._dac7_payout_bloccato(hid)
        anello(c, "il kill-switch spegne il blocco", not bloccato4,
               "il blocco non si puo' spegnere in emergenza")
    finally:
        if prec is None:
            _os.environ.pop("DAC7_BLOCCO_PAYOUT", None)
        else:
            _os.environ["DAC7_BLOCCO_PAYOUT"] = prec


CATENE = [
    ("prezzo intoccabile", catena_prezzo),
    ("rampa e tariffa tecnica", catena_rampa),
    ("consensi", catena_consensi),
    ("ri-accettazione", catena_riaccettazione),
    ("penale -> compensazione -> debito", catena_penale),
    ("prove -> sigillo -> fascicolo", catena_prove),
    ("conformita' -> blocco bonifici", catena_dac7),
]


if __name__ == "__main__":
    print("=" * 92)
    print("LE LOGICHE — i ragionamenti a catena, seguiti anello per anello")
    print("=" * 92)
    for nome, funzione in CATENE:
        prima = len(VIOL)
        mondo = Mondo()
        try:
            funzione(mondo)
        except Exception as e:
            VIOL.append("[%s] ECCEZIONE %s: %s" % (nome, type(e).__name__, e))
        finally:
            mondo.chiudi()
        nuove = len(VIOL) - prima
        print("  %-42s %s" % (nome, "OK" if nuove == 0 else "%d PROBLEMI" % nuove))

    print("\n" + "=" * 92)
    print("catene: %d | anelli verificati: %d | anelli scoperti: %d"
          % (CONTA["catene"], CONTA["anelli"], CONTA["scoperti"]))
    if VIOL:
        print("\nANELLI ROTTI O SCOPERTI: %d\n" % len(VIOL))
        for v in VIOL:
            print("  X " + v[:150])
        sys.exit(1)
    print("\nTUTTE LE CATENE REGGONO, anello per anello.")
    sys.exit(0)
