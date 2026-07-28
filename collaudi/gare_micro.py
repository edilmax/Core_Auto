"""
GARE AL MICROSECONDO SU SUPERFICI NUOVE — barriere di thread che scattano tutte insieme,
su superfici NON coperte da collaudi/gare_estreme.py (prenota/prezzo/cancella/blocca) ne'
da collaudi/multivettore.py (idempotenza webhook SEQUENZIALE, multi-pannello, tampering).

Cinque gare, ognuna con OSSERVABILE FORTE e — dove applicabile — l'auditor invarianti
fase199 come giudice indipendente sui DB reali (su FILE, mai ':memory:' condiviso fra
thread: la connessione unica mescola le transazioni — lezione nota del repo):

  G1  PIN/VOUCHER vs PAGAMENTO — N thread renderizzano il voucher MENTRE il webhook di
      pagamento arriva: il PIN di check-in non deve MAI comparire prima dello stato
      'pagato' (nessuna finestra, nessuna pagina "strappata" meta'-pagata/meta'-no);
      causalita': una pagina finita PRIMA che il webhook partisse non puo' avere il PIN.
  G2  CONTROVERSIA a cavallo del rilascio escrow — contesta (API voucher) in gara con
      l'auto-rilascio orario (stessa forma del server: auto_rilascia + transfer):
      mai host in lista bonifici con controversia aperta, mai doppio esito, payout
      'trattenuto' quando la contestazione vince. + 120 gare a livello motore (CAS).
  G3  RIMBORSO ADMIN vs AUTO-RILASCIO simultanei — mai doppio esborso: se l'ospite
      risulta rimborsato, il cancello dei soldi verso l'host DEVE essere chiuso
      (payout 'trattenuto', mai 'maturato'/'in_transito'/'pagato').
  G4  CANDIDATURE PARTNER simultanee stessa email (varianti maiuscole/spazi) -> UNA
      sola riga (la dedup normalizzata regge sotto gara), giudice = SQL diretto sul DB.
  G5  WEBHOOK DOPPIO IN PARALLELO (non in sequenza come multivettore V1b) -> 'pagato'
      UNA sola volta: il passo NON idempotente (credito host) eseguito esattamente 1
      volta, payout maturato una volta, giornale con 1 solo 'incasso', occupazione
      invariata.

REGOLA AUREA (visto ROSSO): con GARE_MICRO_ROSSO=g1|g2|g3|g4|g5 il collaudo INIETTA il
difetto corrispondente (gate che legge uno stato bugiardo, auto-rilascio senza CAS,
rimborso che non trattiene il payout, dedup email senza normalizzazione, conferma
read-then-write non atomica) e DEVE uscire con exit!=0. La produzione NON viene toccata:
l'iniezione e' un monkeypatch nel solo processo di collaudo.

Deterministico, in-house (Stripe finto, email finta). Un solo comando:
    python collaudi/gare_micro.py
"""
import datetime
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fase83_server as SRV
import fase85_pagamenti_stripe as _stripe
import fase199_invarianti as INV
from collaudi.gare_estreme import _fake_fetch, _host_pubblica, _quote, _Posta
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test

FALLE = []
_N = [0]
ROSSO = os.environ.get("GARE_MICRO_ROSSO", "").strip().lower()


def esito(nome, ok, dett=""):
    _N[0] += 1
    print("  [%s] %2d. %s%s" % ("OK   " if ok else "FALLA", _N[0], nome,
                                "" if ok else "  -> " + dett))
    if not ok:
        FALLE.append("%s: %s" % (nome, dett))


def _sistema(dir_):
    """Sistema REALE con TUTTI i DB toccati dalle gare su FILE (mai ':memory:' condiviso
    fra thread: la connessione unica mescola le transazioni — lezione del repo)."""
    _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)
    os.environ["UPLOAD_DIR"] = dir_ + "/uploads"
    sis = crea_sistema(ConfigCasaVIP(
        abilitato=True, segreto_hmac=b"G" * 32, con_registrazione_host=True,
        db_catalogo=dir_ + "/c.db", db_inventario=dir_ + "/i.db",
        db_registro_host=dir_ + "/r.db", db_accettazioni=dir_ + "/a.db",
        db_pendenti=dir_ + "/p.db", db_messaggi=dir_ + "/m.db",
        db_garanzia=dir_ + "/g.db", db_recensioni=dir_ + "/rec.db",
        db_partner=dir_ + "/partner.db", db_payout=dir_ + "/payout.db",
        db_finanza=dir_ + "/fin.db", db_tassa_comunale=dir_ + "/tassa.db",
        db_checkin=dir_ + "/ck.db", db_credito_usati=dir_ + "/cred.db",
        db_domanda=dir_ + "/dom.db", db_viral=dir_ + "/vir.db",
        commissione_bps=1500, psp_bps=300, stripe_secret_key="sk",
        stripe_webhook_secret="whsec_x", stripe_success_url="https://x/ok",
        stripe_cancel_url="https://x/no"))
    sis.email_provider = _Posta()
    return sis


def _g_di(r):
    def g(m, p, b=None, h=None):
        return r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})
    return g


def _host_token(g):
    from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256
    s, c = g("POST", "/api/host/registrazione", {
        "email": "host@micro.it", "password": "password1", "accetta_termini": True,
        "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
        "versione": CONTRATTO_HOST_VERSIONE})
    return {"X-Host-Token": (c or {}).get("token", "")}


def _webhook(r, rif):
    """Consegna il webhook Stripe firmato sul body GREZZO (come multivettore V1b)."""
    pl = json.dumps({"type": "checkout.session.completed",
                     "data": {"object": {"metadata": {"riferimento": rif}}}})
    return r.gestisci("POST", "/api/payments/webhook", {}, pl,
                      {"Stripe-Signature": firma_di_test(pl, "whsec_x", int(time.time()))})


def _book(g, sis, slug, ci, co, email):
    """Prenota e ritorna (rif, voucher_token, netto_host_cents dal preventivo FIRMATO)."""
    tok = _quote(g, slug, ci, co)
    netto = (sis.firma.decodifica(tok) or {}).get("netto_host_cents") if tok else None
    s, b = g("POST", "/api/concierge/book", {"quote_token": tok, "email": email})
    b = b if isinstance(b, dict) else {}
    return s, b.get("riferimento"), b.get("voucher_token"), netto


def _occ(dbdir, slug, ci, co):
    con = sqlite3.connect(dbdir + "/i.db", timeout=30)
    try:
        return con.execute("SELECT COALESCE(SUM(unita_occupate),0) FROM inventario "
                           "WHERE alloggio_id=? AND giorno>=? AND giorno<?",
                           (slug, ci, co)).fetchone()[0]
    except sqlite3.Error:
        return None
    finally:
        con.close()


def _pred_rimborsata(sis):
    """Predicato salta_se IDENTICO a quello cablato nel server (fase83, _tick_garanzia)."""
    pp = getattr(sis, "pagamenti_pendenti", None)

    def _rimborsata(rif):
        try:
            i = pp.info(rif) if pp is not None else None
            return bool(i) and i.get("stato") in ("rimborsato", "cancellata_host")
        except Exception:
            return False
    return _rimborsata


# ══════════════════════════════════════════════════════════════════════════════
# G1 — PIN/VOUCHER vs PAGAMENTO: il PIN mai prima dello stato 'pagato'
# ══════════════════════════════════════════════════════════════════════════════
def g1_pin_vs_pagamento(d, sis, r, g, tk, oggi):
    print("-- G1  PIN/VOUCHER vs PAGAMENTO (mai il PIN prima di 'pagato', mai pagina strappata) --")
    slug = _host_pubblica(g, tk, "micro1", 1, 20000, oggi.isoformat(),
                          (oggi + datetime.timedelta(days=120)).isoformat())
    ci = (oggi + datetime.timedelta(days=5)).isoformat()
    co = (oggi + datetime.timedelta(days=7)).isoformat()
    s, rif, vt, _ = _book(g, sis, slug, ci, co, "g1@micro.it")
    pin = sis.firma.pin_checkin(rif)
    # marcatori ESATTI della riga PIN (il PIN nudo e' 4 cifre: collide con date/prezzi)
    mk_pin = 'color:#1e3c72">%s</strong>' % pin
    mk_lock = 'color:#1e3c72">&#128274;</strong>'
    mk_paga = "Completa il pagamento per attivare il voucher"

    if ROSSO == "g1":
        # INIEZIONE: il gate legge uno stato BUGIARDO (equivale a rimuovere il gate):
        # info() risponde 'pagato' anche se il pagamento non e' mai arrivato.
        print("  [ROSSO] iniettato: pagamenti_pendenti.info mente ('pagato' sempre)")
        _orig = sis.pagamenti_pendenti.info
        sis.pagamenti_pendenti.info = (
            lambda rr: dict((_orig(rr) or {"riferimento": rr}), stato="pagato"))

    # gate API: contesta/conferma garanzia PRIMA del pagamento -> 409 (non un side-effect)
    s_api, b_api = g("POST", "/api/garanzia/contesta", {"voucher_token": vt, "motivo": "x"})
    esito("G1 API garanzia PRIMA del pagamento -> 409 pagamento_non_confermato",
          s_api == 409 and (b_api or {}).get("errore") == "pagamento_non_confermato",
          "status=%s corpo=%r" % (s_api, b_api))

    def coerente(pag):
        """Una pagina e' VALIDA solo tutta-pagata o tutta-non-pagata. Strappata = falla."""
        con_pin = mk_pin in pag
        con_lock = mk_lock in pag
        con_gar = "/api/garanzia/" in pag
        con_paga = mk_paga in pag
        if con_pin:
            return con_gar and not con_lock and not con_paga
        return con_lock and con_paga and not con_gar

    # FASE A: N render simultanei col pagamento NON arrivato -> MAI il PIN
    NA = 6
    barra = threading.Barrier(NA)
    pre = []
    lk = threading.Lock()

    def renda_pre():
        barra.wait()
        pag = SRV.pagina_voucher_html(sis, vt, "it") or ""
        with lk:
            pre.append(pag)

    th = [threading.Thread(target=renda_pre) for _ in range(NA)]
    [t.start() for t in th]
    [t.join() for t in th]
    con_pin_pre = sum(1 for p in pre if mk_pin in p)
    strappate_pre = sum(1 for p in pre if not coerente(p))
    esito("G1 fase A: %d render pre-pagamento simultanei -> 0 con PIN, 0 strappate" % NA,
          con_pin_pre == 0 and strappate_pre == 0,
          "con_pin=%d strappate=%d" % (con_pin_pre, strappate_pre))

    # FASE B: N render in raffica MENTRE il webhook arriva (stessa barriera)
    NB, RB = 6, 12
    barra2 = threading.Barrier(NB + 1)
    render = []                    # (t_fine_ns, pagina)
    wh = {}

    def renda_gara():
        barra2.wait()
        for _ in range(RB):
            pag = SRV.pagina_voucher_html(sis, vt, "it") or ""
            t1 = time.monotonic_ns()
            with lk:
                render.append((t1, pag))

    def paga():
        barra2.wait()
        time.sleep(0.015)                       # lascia finire qualche render pre-webhook
        wh["t_start"] = time.monotonic_ns()     # da QUI in poi 'pagato' puo' esistere
        wh["s"], _ = _webhook(r, rif)

    th = [threading.Thread(target=renda_gara) for _ in range(NB)] + \
         [threading.Thread(target=paga)]
    [t.start() for t in th]
    [t.join() for t in th]
    t0 = wh.get("t_start", 0)
    prima = [p for (t1, p) in render if t1 < t0]
    finestra = [p for p in prima if mk_pin in p]     # PIN su pagina finita PRIMA del webhook
    strappate = [p for (_t, p) in render if not coerente(p)]
    esito("G1 fase B: %d render in gara col webhook -> nessuna FINESTRA (PIN prima del pagamento)"
          % len(render), not finestra and wh.get("s") == 200,
          "finestra=%d (su %d pre-webhook) webhook=%s" % (len(finestra), len(prima), wh.get("s")))
    esito("G1 fase B: nessuna pagina STRAPPATA (meta' pagata / meta' no)",
          not strappate, "strappate=%d" % len(strappate))

    # CABLAGGIO (anti-finto-verde): a pagamento avvenuto il PIN DEVE esserci davvero
    dopo = SRV.pagina_voucher_html(sis, vt, "it") or ""
    esito("G1 dopo il pagamento: il PIN c'e' (il gate non e' un lucchetto sempre chiuso)",
          mk_pin in dopo and "/api/garanzia/" in dopo and mk_lock not in dopo,
          "pin=%s garanzia=%s" % (mk_pin in dopo, "/api/garanzia/" in dopo))


# ══════════════════════════════════════════════════════════════════════════════
# G2 — CONTROVERSIA a cavallo del rilascio atomico dell'escrow
# ══════════════════════════════════════════════════════════════════════════════
def g2_controversia_vs_rilascio(d, sis, r, g, tk, oggi):
    print("-- G2  CONTROVERSIA vs AUTO-RILASCIO escrow (mai host pagato con disputa aperta) --")
    gz = sis.garanzia
    if ROSSO == "g2":
        # INIEZIONE: auto-rilascio SENZA CAS (read-then-write cieco), il bug storico:
        # una contestazione committata fra lettura e scrittura viene SOVRASCRITTA.
        print("  [ROSSO] iniettato: auto_rilascia senza guardia di stato (no CAS)")
        import fase160_escrow_garanzia as F160

        def _bacata(self, *, ora_ts=None, dettagli=False, salta_se=None):
            ora = ora_ts if isinstance(ora_ts, int) else self._now()
            con = self._apri()
            try:
                righe = con.execute(
                    "SELECT prenotazione_id, importo_host_cents FROM garanzia "
                    "WHERE stato='in_garanzia' AND sblocco_auto_ts<=?", (ora,)).fetchall()
                time.sleep(0.004)                # la finestra read-then-write del bug
                vinte = []
                with con:
                    for rr in righe:
                        con.execute("UPDATE garanzia SET stato='rilasciato', "
                                    "host_riceve_cents=?, aggiornato_ts=? "
                                    "WHERE prenotazione_id=?",
                                    (rr["importo_host_cents"], ora, rr["prenotazione_id"]))
                        vinte.append(rr)
                if dettagli:
                    return [{"prenotazione_id": rr["prenotazione_id"],
                             "host_riceve_cents": int(rr["importo_host_cents"])}
                            for rr in vinte]
                return len(vinte)
            finally:
                con.close()
        F160.EscrowGaranzia.auto_rilascia = _bacata

    futuro = int(time.time()) + 10 ** 9
    pred = _pred_rimborsata(sis)

    # (a) FULL-STACK: contesta via API (voucher vero) vs il giro orario (stessa forma server)
    slug = _host_pubblica(g, tk, "micro2", 3, 30000, oggi.isoformat(),
                          (oggi + datetime.timedelta(days=120)).isoformat())
    K = 6
    falle_a = []
    for i in range(K):
        ci = (oggi + datetime.timedelta(days=8 + 2 * i)).isoformat()
        co = (oggi + datetime.timedelta(days=9 + 2 * i)).isoformat()
        s, rif, vt, _ = _book(g, sis, slug, ci, co, "g2-%d@micro.it" % i)
        _webhook(r, rif)                                    # pagata -> contesta ammessa
        barra = threading.Barrier(2)
        out = {}

        def contesta():
            barra.wait()
            out["s_api"], out["b_api"] = g("POST", "/api/garanzia/contesta",
                                           {"voucher_token": vt, "motivo": "non conforme"})

        def rilascia():
            barra.wait()
            rel = gz.auto_rilascia(ora_ts=futuro, dettagli=True, salta_se=pred) or []
            out["rel"] = {x["prenotazione_id"] for x in rel}
            for x in rel:                                   # stessa forma del server
                r._trasferisci_all_host(x["prenotazione_id"], x["host_riceve_cents"])

        t1, t2 = threading.Thread(target=contesta), threading.Thread(target=rilascia)
        t1.start(); t2.start(); t1.join(); t2.join()
        st = (gz.stato(rif) or {}).get("stato")
        pay = sis.payout.stato_di(rif)
        vinta_c = out.get("s_api") == 200 and (out.get("b_api") or {}).get("ok") is True
        vinta_r = rif in out.get("rel", set())
        if vinta_c == vinta_r:
            falle_a.append("iter %d: doppio/nessun esito (contesa=%s rilascio=%s stato=%s)"
                           % (i, vinta_c, vinta_r, st))
        if vinta_r and st != "rilasciato":
            falle_a.append("iter %d: in lista bonifici ma stato=%s (host pagato con "
                           "controversia!)" % (i, st))
        if vinta_c and st != "contestato":
            falle_a.append("iter %d: contesa accettata ma stato=%s" % (i, st))
        if vinta_c and pay != "trattenuto":
            falle_a.append("iter %d: disputa aperta ma payout=%s (bonifico non fermato)"
                           % (i, pay))
    esito("G2a %d gare full-stack contesta-vs-rilascio: esito UNICO e coerente, payout "
          "fermato su disputa" % K, not falle_a, " | ".join(falle_a[:3]))

    # (b) MOTORE: 120 gare secche sul CAS di fase160 (store separato, stesso componente vero)
    from fase160_escrow_garanzia import crea_escrow_garanzia
    gze = crea_escrow_garanzia(d + "/gE.db")
    gze.inizializza_schema()
    K2 = 120
    falle_b = []
    for i in range(K2):
        rif = "eng%03d" % i
        base = 1000 + i * 10 ** 6
        gze.apri(rif, 12345, alloggio_id="x", ora_checkin_ts=base)
        soglia = base + 24 * 3600                           # sblocco di QUESTA riga sola
        barra = threading.Barrier(2)
        out = {}

        def contesta_e():
            barra.wait()
            out["c"] = gze.contesta(rif, "problema")

        def rilascia_e():
            barra.wait()
            rel = gze.auto_rilascia(ora_ts=soglia, dettagli=True) or []
            out["r"] = {x["prenotazione_id"] for x in rel}

        t1, t2 = threading.Thread(target=contesta_e), threading.Thread(target=rilascia_e)
        t1.start(); t2.start(); t1.join(); t2.join()
        ok_c = (out.get("c") or {}).get("ok") is True
        ok_r = rif in out.get("r", set())
        st = (gze.stato(rif) or {}).get("stato")
        if ok_c == ok_r:
            falle_b.append("%s: contesa=%s rilascio=%s stato=%s" % (rif, ok_c, ok_r, st))
        elif ok_c and st != "contestato":
            falle_b.append("%s: contesa vinta ma stato=%s" % (rif, st))
        elif ok_r and st != "rilasciato":
            falle_b.append("%s: rilascio vinto ma stato=%s" % (rif, st))
    esito("G2b %d gare a livello motore (CAS fase160): sempre UN solo vincitore, stato "
          "coerente" % K2, not falle_b,
          "%d incoerenze, es: %s" % (len(falle_b), " | ".join(falle_b[:3])))


# ══════════════════════════════════════════════════════════════════════════════
# G3 — RIMBORSO ADMIN vs AUTO-RILASCIO escrow simultanei (mai doppio esborso)
# ══════════════════════════════════════════════════════════════════════════════
def g3_rimborso_vs_rilascio(d, sis, r, g, tk, oggi):
    print("-- G3  RIMBORSO vs AUTO-RILASCIO simultanei (mai ospite rimborsato E host pagato) --")
    if ROSSO == "g3":
        # INIEZIONE: il rimborso admin NON trattiene piu' il payout (il passo che chiude
        # il cancello dei soldi verso l'host sparisce) -> doppio esborso possibile.
        print("  [ROSSO] iniettato: _payout_trattieni diventa un no-op")
        r._payout_trattieni = lambda rif: None
    gz = sis.garanzia
    pred = _pred_rimborsata(sis)
    futuro = int(time.time()) + 10 ** 9
    slug = _host_pubblica(g, tk, "micro3", 2, 25000, oggi.isoformat(),
                          (oggi + datetime.timedelta(days=120)).isoformat())
    K = 8
    falle = []
    vinti_rilascio = 0
    for i in range(K):
        ci = (oggi + datetime.timedelta(days=40 + 2 * i)).isoformat()
        co = (oggi + datetime.timedelta(days=41 + 2 * i)).isoformat()
        s, rif, vt, _ = _book(g, sis, slug, ci, co, "g3-%d@micro.it" % i)
        _webhook(r, rif)                                    # pagata: payout 'maturato'
        idem = (sis.pagamenti_pendenti.info(rif) or {}).get("idem_key", "")
        barra = threading.Barrier(2)
        out = {}

        def rimborsa():
            barra.wait()
            out["s_adm"], out["b_adm"] = g(
                "POST", "/api/admin/rimborso",
                {"alloggio_id": slug, "check_in": ci, "check_out": co, "idem_key": idem},
                {"X-Admin-Key": "ak"})

        def rilascia():
            barra.wait()
            rel = gz.auto_rilascia(ora_ts=futuro, dettagli=True, salta_se=pred) or []
            out["rel"] = {x["prenotazione_id"] for x in rel}
            for x in rel:                                   # stessa forma del server
                r._trasferisci_all_host(x["prenotazione_id"], x["host_riceve_cents"])

        t1, t2 = threading.Thread(target=rimborsa), threading.Thread(target=rilascia)
        t1.start(); t2.start(); t1.join(); t2.join()
        st_p = (sis.pagamenti_pendenti.info(rif) or {}).get("stato")
        st_g = (gz.stato(rif) or {})
        pay = sis.payout.stato_di(rif)
        if rif in out.get("rel", set()):
            vinti_rilascio += 1
        if out.get("s_adm") != 200:
            falle.append("iter %d: rimborso admin fallito (%s %r)"
                         % (i, out.get("s_adm"), out.get("b_adm")))
            continue
        if st_p != "rimborsato":
            falle.append("iter %d: pendente=%s (atteso rimborsato)" % (i, st_p))
        # IL controllo del doppio esborso: ospite rimborsato => cancello host CHIUSO
        if pay in ("maturato", "in_transito", "pagato"):
            falle.append("iter %d: DOPPIO ESBORSO possibile - ospite rimborsato MA payout "
                         "host '%s' (escrow=%s)" % (i, pay, st_g.get("stato")))
        if st_g.get("stato") == "annullato" and st_g.get("host_riceve_cents", 0) != 0:
            falle.append("iter %d: escrow annullato con host_riceve=%s"
                         % (i, st_g.get("host_riceve_cents")))
        if st_g.get("stato") not in ("annullato", "rilasciato"):
            falle.append("iter %d: escrow in stato imprevisto %s" % (i, st_g.get("stato")))
    esito("G3 %d gare rimborso-vs-rilascio: mai rimborso ospite con payout host aperto "
          "(rilascio ha vinto %d volte)" % (K, vinti_rilascio),
          not falle, " | ".join(falle[:3]))


# ══════════════════════════════════════════════════════════════════════════════
# G4 — CANDIDATURE PARTNER simultanee stessa email -> UNA sola riga
# ══════════════════════════════════════════════════════════════════════════════
def g4_partner_dedup(d, sis, g):
    print("-- G4  PARTNER: candidature simultanee stessa email -> la dedup regge sotto gara --")
    if ROSSO == "g4":
        # INIEZIONE: la normalizzazione email sparisce -> ogni variante diventa una riga.
        print("  [ROSSO] iniettato: _email_norm senza normalizzazione (email cruda)")
        import fase201_partner as F201
        F201._email_norm = lambda e: e if isinstance(e, str) and "@" in e else None
    varianti = ["Race@Partner.IT", " race@partner.it ", "race@partner.it",
                "RACE@PARTNER.IT", "rAcE@pArTnEr.It", " RACE@partner.it",
                "race@partner.it ", "Race@partner.it", "race@Partner.it"]
    barra = threading.Barrier(len(varianti))
    ris = []
    lk = threading.Lock()

    def candida(i, em):
        barra.wait()
        s, b = g("POST", "/api/partner", {"nome": "Mario Rossi %d" % i, "email": em,
                                          "tipo": "property_manager", "citta": "Roma",
                                          "consenso": True})
        with lk:
            ris.append(s)

    th = [threading.Thread(target=candida, args=(i, em)) for i, em in enumerate(varianti)]
    [t.start() for t in th]
    [t.join() for t in th]
    # giudice indipendente: SQL diretto sul DB su file
    con = sqlite3.connect(d + "/partner.db", timeout=30)
    try:
        tot = con.execute("SELECT COUNT(*) FROM partner").fetchone()[0]
        canon = con.execute("SELECT COUNT(*) FROM partner WHERE email='race@partner.it'"
                            ).fetchone()[0]
    finally:
        con.close()
    esito("G4 %d candidature simultanee (varianti stessa email) -> 1 SOLA riga, normalizzata"
          % len(varianti),
          tot == 1 and canon == 1 and sis.partner.conta() == 1 and all(s == 201 for s in ris),
          "righe=%d canoniche=%d conta()=%d status=%r" % (tot, canon, sis.partner.conta(), ris))


# ══════════════════════════════════════════════════════════════════════════════
# G5 — WEBHOOK doppio consegnato IN PARALLELO -> 'pagato' una sola volta
# ══════════════════════════════════════════════════════════════════════════════
def g5_webhook_parallelo(d, sis, r, g, tk, oggi):
    print("-- G5  WEBHOOK doppio IN PARALLELO (non in sequenza) -> 'pagato' UNA sola volta --")
    if ROSSO == "g5":
        # INIEZIONE: conferma() torna read-then-write NON atomico (senza CAS): tutti i
        # consegnatari leggono 'in_attesa' e diventano TUTTI vincitori.
        print("  [ROSSO] iniettato: PagamentiPendenti.conferma senza CAS")
        import fase162_pagamenti_pendenti as F162

        def _bacata(self, riferimento):
            con = self._apri()
            try:
                row = con.execute("SELECT * FROM pendenti WHERE riferimento=?",
                                  (riferimento,)).fetchone()
                if row is None:
                    return None
                prima = self._riga(row)
                if row["stato"] not in ("in_attesa", "scaduto"):
                    return prima
                time.sleep(0.004)                # la finestra del bug
                with con:
                    con.execute("UPDATE pendenti SET stato='pagato' WHERE riferimento=?",
                                (riferimento,))
                return prima
            finally:
                con.close()
        F162.PagamentiPendenti.conferma = _bacata

    slug = _host_pubblica(g, tk, "micro5", 1, 40000, oggi.isoformat(),
                          (oggi + datetime.timedelta(days=120)).isoformat())
    ci = (oggi + datetime.timedelta(days=80)).isoformat()
    co = (oggi + datetime.timedelta(days=82)).isoformat()      # 2 notti
    s, rif, vt, netto = _book(g, sis, slug, ci, co, "g5@micro.it")
    occ_prima = _occ(d, slug, ci, co)

    # osservabile FORTE sul passo NON idempotente: quante volte gira il ramo "vincitore"
    conta = {"credito": 0, "email": 0}
    lk = threading.Lock()
    _oc, _oe = r._applica_credito_host, r._email_pagamento_confermato

    def _credito(*a, **k):
        with lk:
            conta["credito"] += 1
        return _oc(*a, **k)

    def _email(*a, **k):
        with lk:
            conta["email"] += 1
        return _oe(*a, **k)
    r._applica_credito_host = _credito
    r._email_pagamento_confermato = _email

    NW = 4
    barra = threading.Barrier(NW)
    stati = []

    def consegna():
        barra.wait()
        s2, _ = _webhook(r, rif)
        with lk:
            stati.append(s2)

    th = [threading.Thread(target=consegna) for _ in range(NW)]
    [t.start() for t in th]
    [t.join() for t in th]
    r._applica_credito_host, r._email_pagamento_confermato = _oc, _oe

    st = (sis.pagamenti_pendenti.info(rif) or {}).get("stato")
    occ_dopo = _occ(d, slug, ci, co)
    prec = sis.payout.info(rif) or {}
    con = sqlite3.connect(d + "/fin.db", timeout=30)
    try:
        incassi = con.execute("SELECT COUNT(*) FROM libro_giornale WHERE tipo='incasso' "
                              "AND riferimento=?", (rif,)).fetchone()[0]
    except sqlite3.Error:
        incassi = None
    finally:
        con.close()
    esito("G5 %d webhook in parallelo -> stato 'pagato', tutte le consegne 200" % NW,
          st == "pagato" and all(x == 200 for x in stati),
          "stato=%s stati=%r" % (st, stati))
    esito("G5 ramo vincitore UNA sola volta (credito=1, email conferma=1)",
          conta["credito"] == 1 and conta["email"] == 1,
          "credito=%d email=%d (piu' di 1 = 'pagato' applicato piu' volte)"
          % (conta["credito"], conta["email"]))
    esito("G5 payout maturato UNA volta, importo = netto firmato (%s)" % netto,
          prec.get("stato") == "maturato" and prec.get("minori") == netto,
          "payout=%r atteso netto=%s" % (prec, netto))
    esito("G5 giornale: UN solo movimento 'incasso' per la prenotazione",
          incassi == 1, "incassi=%s" % incassi)
    esito("G5 occupazione INVARIATA dal doppio webhook (%s notti)" % occ_prima,
          occ_prima == occ_dopo == 2, "prima=%s dopo=%s" % (occ_prima, occ_dopo))


# ══════════════════════════════════════════════════════════════════════════════
def main():
    d = tempfile.mkdtemp()
    sis = _sistema(d)
    r = crea_router(sis, host_key="hk", admin_key="ak", base_url="https://bookinvip.com")
    g = _g_di(r)
    tk = _host_token(g)
    oggi = datetime.date.today()

    print("=" * 82)
    print("GARE AL MICROSECONDO — superfici nuove: PIN-gate, controversia, rimborso, "
          "partner, webhook parallelo")
    if ROSSO:
        print(">>> MODALITA' ROSSO: difetto iniettato su '%s' — QUESTA corsa DEVE fallire <<<"
              % ROSSO)
    print("=" * 82)

    da_correre = {"g1": [g1_pin_vs_pagamento], "g2": [g2_controversia_vs_rilascio],
                  "g3": [g3_rimborso_vs_rilascio], "g4": [g4_partner_dedup],
                  "g5": [g5_webhook_parallelo]}
    if ROSSO and ROSSO not in da_correre:
        print("GARE_MICRO_ROSSO=%r non valido (usa g1..g5)" % ROSSO)
        sys.exit(2)

    ordine = [ROSSO] if ROSSO else ["g1", "g2", "g3", "g4", "g5"]
    for nome in ordine:
        fn = da_correre[nome][0]
        if nome == "g4":
            fn(d, sis, g)
        else:
            fn(d, sis, r, g, tk, oggi)

    # giudice INDIPENDENTE finale: l'auditor invarianti fase199 sui DB reali su file
    viol = INV.scansiona_db(d).get("violazioni", {})
    esito("giudice indipendente (auditor fase199) sui DB dopo TUTTE le gare: 0 violazioni",
          not viol, "violazioni=%r" % viol)

    shutil.rmtree(d, ignore_errors=True)
    print("=" * 82)
    if FALLE:
        print("FALLE TROVATE: %d" % len(FALLE))
        for f in FALLE:
            print("   [X] " + f)
    else:
        print("0 FALLE: PIN gateato senza finestre, controversia atomica, mai doppio "
              "esborso, dedup partner tenuta, webhook parallelo idempotente.")
    print("=" * 82)
    sys.exit(1 if FALLE else 0)


if __name__ == "__main__":
    main()
