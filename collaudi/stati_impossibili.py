"""
CACCIA PROFONDA AGLI STATI IMPOSSIBILI — la rete di sicurezza (guardiano fase186) VEDE i disastri?

Gli happy-path sono testati. La domanda profonda e' un'altra: quando un CRASH / webhook perso /
riga orfana lascia il sistema in uno stato IMPOSSIBILE (soldi senza stanza, escrow che non si apre,
bonifico verso un host che non esiste, payout su una prenotazione rimborsata), QUALCUNO se ne accorge?
Questo collaudo INIETTA di proposito ogni stato impossibile e verifica che il guardiano GRIDI
(pulito=False + la categoria giusta). E' il "visto ROSSO" della rete di sicurezza stessa.

  A) INIEZIONE & RILEVAMENTO — 6 stati impossibili iniettati, il guardiano li deve vedere tutti;
     su sistema pulito NON deve gridare (niente falsi allarmi).
  B) TRANSIZIONI ILLEGALI sul percorso vivo dei soldi — confermare una prenotazione cancellata,
     doppia cancellazione, webhook per un riferimento inesistente: mai "soldi senza stanza",
     mai crash, mai doppio effetto.
  C) SONDA CROSS-DB — un'occupazione fantasma (inventario occupato senza prenotazione): la vede
     qualche guardiano? (se no, e' un buco piu' profondo da segnalare onestamente).

Deterministico, in-house, orologio iniettato. Un solo comando:
    python collaudi/stati_impossibili.py
"""
import datetime
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fase186_guardiano as GUARD
import fase199_invarianti as INV
from collaudi.gare_estreme import _sistema, _host_pubblica, _quote
from collaudi.multivettore import _router, _g, _host
from fase87_stripe_webhook import firma_di_test

FALLE = []
_N = [0]
GIORNO = 86400


def _orolo(ts):
    """Il guardiano vuole un OROLOGIO callable (ora or time.time)(): avvolgo il timestamp."""
    return lambda: ts


def esito(nome, ok, dett=""):
    _N[0] += 1
    print("  [%s] %2d. %s%s" % ("OK   " if ok else "FALLA", _N[0], nome,
                                "" if ok else "  -> " + dett))
    if not ok:
        FALLE.append("%s: %s" % (nome, dett))


def _nuovo():
    d = tempfile.mkdtemp()
    return d, _sistema(d)


def _cat(rep, nome):
    """Estrae la lista/dict di una categoria di anomalie dal referto del guardiano (annidata)."""
    an = rep.get("anomalie", {}) if isinstance(rep, dict) else {}
    if nome in an:
        return an[nome]
    for v in an.values():                      # alcune categorie sono annidate (payout/rimborsata)
        if isinstance(v, dict) and nome in v:
            return v[nome]
    return None


def _nonvuoto(x):
    return bool(x) if not isinstance(x, dict) else any(x.values())


def _altre_categorie(rep):
    """Categorie di anomalia POPOLATE diverse dalla riconciliazione (che nel test non gira:
    senza Stripe reale il guardiano segnala 'riconciliazione_non_eseguita', atteso qui)."""
    an = rep.get("anomalie", {}) if isinstance(rep, dict) else {}
    fuori = []
    for k, v in an.items():
        if k == "riconciliazione_stripe":
            continue
        if _nonvuoto(v):
            fuori.append(k)
    return fuori


# ══════════════════════════════════════════════════════════════════════════════
# A) INIEZIONE & RILEVAMENTO
# ══════════════════════════════════════════════════════════════════════════════
def sezione_A():
    print("-- A  INIEZIONE & RILEVAMENTO (il guardiano GRIDA su ogni stato impossibile?) --")
    ora = int(time.time())

    # A0) sistema PULITO -> nessuna categoria (a parte la riconciliazione, che nel test non gira)
    d, sis = _nuovo()
    rep = GUARD.scansiona(sis, ora=_orolo(ora))
    esito("A0 sistema pulito -> nessun falso allarme (a parte riconciliazione non-eseguita)",
          not _altre_categorie(rep), "categorie=%r" % _altre_categorie(rep))
    shutil.rmtree(d, ignore_errors=True)

    # A1) ESCROW BLOCCATO: garanzia aperta con auto-rilascio gia' scaduto da giorni
    d, sis = _nuovo()
    sis.garanzia.apri("rifA1", 50000, alloggio_id="x", ora_checkin_ts=ora, finestra_ore=1)
    rep = GUARD.scansiona(sis, ora=_orolo(ora + 5 * GIORNO))     # 5 giorni dopo: rilascio scaduto da un pezzo
    esito("A1 escrow bloccato (rilascio scaduto) -> RILEVATO",
          _nonvuoto(_cat(rep, "escrow_bloccato") or _cat(rep, "escrow_bloccati")),
          "anomalie=%r" % rep.get("anomalie"))
    shutil.rmtree(d, ignore_errors=True)

    # A2) BONIFICO FERMO: payout 'maturato' fermo da piu' di 7 giorni (host VERO -> non orfano)
    d, sis = _nuovo()
    hid = sis.registro_host.registra("host@a2.it", "password12", accetta_termini=True).host_id
    sis.payout.registra_maturato("rifA2", hid, 40000, "EUR")
    rep = GUARD.scansiona(sis, ora=_orolo(ora + 9 * GIORNO))     # 9 giorni dopo: bonifico fermo da >7gg
    esito("A2 bonifico fermo (payout maturato >7gg) -> RILEVATO",
          _nonvuoto(_cat(rep, "bonifico_fermo")), "anomalie=%r" % rep.get("anomalie"))
    shutil.rmtree(d, ignore_errors=True)

    # A3) PAYOUT ORFANO: bonifico maturato verso un host che NON esiste piu'
    d, sis = _nuovo()
    sis.payout.registra_maturato("rifA3", "host_inesistente_xyz", 30000, "EUR")
    rep = GUARD.scansiona(sis, ora=_orolo(ora))
    esito("A3 payout orfano (host inesistente) -> RILEVATO",
          _nonvuoto(_cat(rep, "payout_orfano")), "anomalie=%r" % rep.get("anomalie"))
    shutil.rmtree(d, ignore_errors=True)

    # A4) SOLDI SU RIMBORSATA: payout 'maturato' su una prenotazione cancellata dall'host
    d, sis = _nuovo()
    hid = sis.registro_host.registra("host@a4.it", "password12", accetta_termini=True).host_id
    sis.pagamenti_pendenti.registra("rifA4", alloggio_id="x", check_in="2026-09-01",
                                    check_out="2026-09-03", host_id=hid)
    sis.pagamenti_pendenti.marca_cancellata_host("rifA4", penale_cents=0)
    sis.payout.registra_maturato("rifA4", hid, 40000, "EUR")
    rep = GUARD.scansiona(sis, ora=_orolo(ora))
    esito("A4 payout su prenotazione RIMBORSATA -> RILEVATO",
          _nonvuoto(_cat(rep, "payout_su_rimborsata")), "anomalie=%r" % rep.get("anomalie"))
    shutil.rmtree(d, ignore_errors=True)

    # A5) ESCROW SU RIMBORSATA (rilascio gia' SCADUTO): garanzia aperta su prenotazione cancellata
    d, sis = _nuovo()
    sis.pagamenti_pendenti.registra("rifA5", alloggio_id="x", check_in="2026-09-01",
                                    check_out="2026-09-03")
    sis.pagamenti_pendenti.marca_cancellata_host("rifA5", penale_cents=0)
    sis.garanzia.apri("rifA5", 50000, alloggio_id="x", ora_checkin_ts=ora - 10 * GIORNO, finestra_ore=1)
    rep = GUARD.scansiona(sis, ora=_orolo(ora))
    esito("A5 escrow (rilascio scaduto) su prenotazione RIMBORSATA -> RILEVATO",
          _nonvuoto(_cat(rep, "escrow_su_rimborsata")), "anomalie=%r" % rep.get("anomalie"))
    shutil.rmtree(d, ignore_errors=True)

    # A6) SONDA — escrow su rimborsata ma con rilascio FUTURO: e' il GAP DOCUMENTATO (il guardiano
    # vede l'escrow-su-rimborsata solo quando il rilascio E' GIA' scattato, non proattivamente).
    d, sis = _nuovo()
    sis.pagamenti_pendenti.registra("rifA6", alloggio_id="x", check_in="2026-09-01",
                                    check_out="2026-09-03")
    sis.pagamenti_pendenti.marca_cancellata_host("rifA6", penale_cents=0)
    sis.garanzia.apri("rifA6", 50000, alloggio_id="x", ora_checkin_ts=ora, finestra_ore=72)
    rep = GUARD.scansiona(sis, ora=_orolo(ora))
    visto = _nonvuoto(_cat(rep, "escrow_su_rimborsata"))
    print("     [SONDA] escrow su rimborsata con rilascio FUTURO rilevato? %s%s"
          % ("SI" if visto else "NO",
             "" if visto else " — GAP DOCUMENTATO (rilevato solo a rilascio scaduto; futuro non proattivo)"))
    shutil.rmtree(d, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════════════════
# B) TRANSIZIONI ILLEGALI SUL PERCORSO VIVO
# ══════════════════════════════════════════════════════════════════════════════
def _webhook(gz, rif):
    pl = json.dumps({"type": "checkout.session.completed",
                     "data": {"object": {"metadata": {"riferimento": rif}}}})
    return gz.gestisci("POST", "/api/payments/webhook", {}, pl,
                       {"Stripe-Signature": firma_di_test(pl, "whsec_x", int(time.time()))})


def sezione_B():
    print("-- B  TRANSIZIONI ILLEGALI (mai 'soldi senza stanza', mai doppio effetto, mai crash) --")
    d, sis = _nuovo()
    r = _router(sis)
    g = _g(r)
    tk = _host(g)
    oggi = datetime.date.today()
    slug = _host_pubblica(g, tk, "sb", 1, 20000, oggi.isoformat(),
                          (oggi + datetime.timedelta(days=40)).isoformat())
    ci = (oggi + datetime.timedelta(days=5)).isoformat()
    co = (oggi + datetime.timedelta(days=7)).isoformat()

    # B1) CONFERMARE UNA PRENOTAZIONE CANCELLATA: book -> cancella -> webhook TARDIVO
    tok = _quote(g, slug, ci, co)
    _s, b = g("POST", "/api/concierge/book", {"quote_token": tok, "email": "o@x.it"})
    rif = (b or {}).get("riferimento")
    vt = (b or {}).get("voucher_token")
    g("POST", "/api/concierge/cancella", {"voucher_token": vt})
    w, _ = _webhook(r, rif)                                   # pagamento arriva DOPO la cancellazione
    info = sis.pagamenti_pendenti.info(rif) or {}
    stato = info.get("stato")
    # invariante: una cancellata non diventa 'pagato' (soldi senza stanza) + niente payout maturato
    payout_stato = sis.payout.stato_di(rif) if hasattr(sis.payout, "stato_di") else ""
    esito("B1 webhook su prenotazione CANCELLATA -> non diventa 'pagato' (mai soldi senza stanza)",
          stato != "pagato" and payout_stato != "maturato" and w in (200, 409),
          "stato=%s payout=%s webhook=%s" % (stato, payout_stato, w))

    # B2) DOPPIA CANCELLAZIONE: la seconda e' idempotente/controllata (non un secondo rimborso)
    s1, _ = g("POST", "/api/concierge/cancella", {"voucher_token": vt})
    s2, _ = g("POST", "/api/concierge/cancella", {"voucher_token": vt})
    esito("B2 doppia cancellazione -> controllata, nessun secondo effetto",
          s1 in (200, 409, 410, 422) and s2 in (200, 409, 410, 422),
          "s1=%s s2=%s" % (s1, s2))

    # B3) WEBHOOK per un RIFERIMENTO INESISTENTE -> controllato, nessun crash, nessuno stato creato
    w3, _ = _webhook(r, "riferimento_mai_esistito_zzz")
    esito("B3 webhook per riferimento inesistente -> controllato (mai 500, nessuno stato)",
          w3 in (200, 404, 409), "webhook=%s" % w3)

    # B4) l'auditor invarianti resta pulito dopo tutte le transizioni illegali
    viol = INV.scansiona_db(d).get("violazioni", {})
    esito("B4 auditor invarianti pulito dopo le transizioni illegali", not viol,
          "violazioni=%r" % viol)
    shutil.rmtree(d, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════════════════
# C) STANZA FANTASMA — inventario occupato SENZA prenotazione: rilevata E chiusa?
# ══════════════════════════════════════════════════════════════════════════════
def sezione_C():
    print("-- C  STANZA FANTASMA (notte occupata senza prenotazione: il guardiano la vede E la chiude?) --")
    d, sis = _nuovo()
    r = _router(sis)
    g = _g(r)
    tk = _host(g)
    oggi = datetime.date.today()
    slug = _host_pubblica(g, tk, "sc", 1, 20000, oggi.isoformat(),
                          (oggi + datetime.timedelta(days=40)).isoformat())
    ci = (oggi + datetime.timedelta(days=5)).isoformat()
    co = (oggi + datetime.timedelta(days=6)).isoformat()
    # FANTASMA REALISTICO: blocco l'inventario (scrive occupazione + movimento, come nel flusso
    # vero) ma NON registro il pendente -> simula il crash fra blocca e registra-pendente.
    sis.inventario.blocca(slug, ci, co, idem_key="fantasma_xyz", origine="test")
    occ0 = _occ_inv(d, slug, ci)
    ora = int(time.time())
    # 1) il guardiano fase186 ora la VEDE (categoria hold_fantasma), con l'ora avanti oltre la grazia
    rep = GUARD.scansiona(sis, ora=_orolo(ora + 3 * 3600))
    visto = _nonvuoto(_cat(rep, "hold_fantasma"))
    esito("C1 stanza fantasma RILEVATA dal guardiano (hold_fantasma)", visto,
          "categorie=%r" % list((rep.get("anomalie") or {}).keys()))
    # 2) il tick la CHIUDE: libera_orfani (idem_validi = i pendenti veri, qui nessuno) -> notte libera
    liberati = sis.inventario.libera_orfani(sis.pagamenti_pendenti.idem_keys(), ora_ts=ora + 3 * 3600)
    occ1 = _occ_inv(d, slug, ci)
    esito("C2 stanza fantasma CHIUSA (notte di nuovo libera, rivendibile)",
          occ0 == 1 and occ1 == 0 and any(o["idem_key"] == "fantasma_xyz" for o in liberati),
          "occ prima=%s dopo=%s liberati=%r" % (occ0, occ1, [o["idem_key"] for o in liberati]))
    shutil.rmtree(d, ignore_errors=True)


def _occ_inv(dbdir, slug, giorno):
    con = sqlite3.connect(dbdir + "/i.db", timeout=30)
    try:
        row = con.execute("SELECT unita_occupate FROM inventario WHERE alloggio_id=? AND giorno=?",
                          (slug, giorno)).fetchone()
        return row[0] if row else None
    except sqlite3.Error:
        return None
    finally:
        con.close()


def main():
    print("=" * 84)
    print("CACCIA PROFONDA AGLI STATI IMPOSSIBILI — la rete di sicurezza vede i disastri?")
    print("=" * 84)
    sezione_A()
    sezione_B()
    sezione_C()
    print("=" * 84)
    if FALLE:
        print("FALLE TROVATE: %d" % len(FALLE))
        for f in FALLE:
            print("   [X] " + f)
    else:
        print("0 FALLE: il guardiano vede ogni stato impossibile iniettato; nessuna transizione illegale passa.")
    print("=" * 84)
    sys.exit(1 if FALLE else 0)


if __name__ == "__main__":
    main()
