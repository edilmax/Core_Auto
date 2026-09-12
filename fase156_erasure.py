"""
CORE_AUTO - Fase 156: CANCELLAZIONE TOTALE di un host/attivita' + VERIFICA "da pertutto".

Il "tasto cancella tutto": rimuove un host e TUTTI i suoi dati da OGNI archivio (annunci,
inventario, messaggi, referral/crediti, account) e poi RI-CONTROLLA ogni archivio per
confermare che non sia rimasto NULLA. Diritto all'oblio (GDPR/PIPL/...) + pulizia dati di test
prima del lancio.

Resiliente: opera solo sugli store presenti che espongono i metodi (getattr) -> aggiungere un
nuovo store in futuro non richiede toccare questo file. Best-effort isolato per store: se uno
fallisce, gli altri proseguono e il residuo viene REGISTRATO (mai un falso "cancellato").
Vincitrice-del-benchmark: cancella-poi-verifica con report per-archivio, ok=True solo se 0
residui ovunque.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# ⛔ GLI ARCHIVI CHE TRATTENGONO IL DATO ANCHE DOPO L'OBLIO, CON IL PERCHE' SCRITTO.
#
# Non e' un elenco di eccezioni messo qui per far tornare il conto. E' il punto in cui due
# regole si contraddicono sullo stesso dato — il diritto alla cancellazione (GDPR art. 17)
# e l'obbligo di conservare (fisco, DAC7, difesa in giudizio) — e la scelta va SCRITTA una
# per una, col motivo, perche' nessun meccanismo la puo' dedurre.
#
# ⛔ E QUESTO ELENCO NON PUO' MARCIRE IN SILENZIO, che e' la differenza con la lista dei
# cinque archivi ricontrollati: un archivio che resta sporco e NON e' qui dentro fa uscire
# `ok=False` e lascia una riga d'ERRORE. Aggiungere un archivio domani non richiede di
# toccare questo file — ma se quell'archivio trattiene un dato, lo si scopre lo stesso
# giorno invece che mai.
#
# ⚠️ OGNI RIGA QUI DENTRO E' UNA POSIZIONE LEGALE, e va letta da un avvocato. Le due che
# ci sono oggi non sono inventate: ripetono cio' che l'informativa gia' DICHIARA al suo
# paragrafo 4, cioe' cio' che la persona ha letto prima di accettare.
# ⛔ LA CHIAVE E' LA TABELLA, NON IL FILE. Primo tentativo del 2026-09-12: era il nome del
# file (`accettazioni.db`), e nei banchi quello stesso archivio si chiama `a.db` o
# `db_accettazioni.db` — il nome dipende dalla CONFIGURAZIONE, non dal prodotto. Risultato:
# la dichiarazione non combaciava, l'oblio usciva `ok=False` e la rotta rispondeva 409 su
# un host pulito. Una posizione legale non puo' stare appesa a come qualcuno ha chiamato un
# file: la tabella sta nello schema ed e' la stessa ovunque.
TRATTENUTI_PER_LEGGE: Dict[str, str] = {
    "accettazioni":
        "prove di accettazione: conservate per la durata del rapporto e per il periodo di "
        "prescrizione (GDPR art. 17.3.e, difesa in giudizio). Cancellarle significherebbe "
        "distruggere la prova di cosa la persona ha accettato — cioe' la sua tutela oltre "
        "che la nostra. L'informativa lo dichiara al paragrafo 4.",
    "libro_giornale":
        "scritture contabili: 10 anni dall'ultima registrazione (art. 2220 c.c.), e oltre "
        "finche' non sono definiti gli accertamenti (art. 22 DPR 600/1973). "
        "L'informativa lo dichiara al paragrafo 4.",
    "note_credito":
        "documenti contabili: stesso termine delle scritture (art. 2220 c.c.).",
    "debiti_host":
        "partite contabili aperte verso l'host: stesso termine delle scritture "
        "(art. 2220 c.c.); cancellarle farebbe sparire un credito o un debito.",
}


def _slug_host(catalogo: Any, host_id: str) -> List[str]:
    try:
        el = catalogo.alloggi_host(host_id, limit=500) if catalogo else []
        return [a.get("slug") for a in (el or []) if isinstance(a, dict) and a.get("slug")]
    except Exception:
        logger.warning("erasure: lettura slug fallita (ISOLATA)", exc_info=True)
        return []


def _safe(fn, *a) -> int:
    try:
        n = fn(*a)
        return int(n) if isinstance(n, int) and not isinstance(n, bool) else 0
    except Exception:
        logger.warning("erasure: passo fallito (ISOLATO)", exc_info=True)
        return 0


# Stati del payout che significano "soldi ancora IN BALLO" (dovuti all'host, non ancora
# arrivati sul suo conto). 'pagato' e' concluso, non blocca.
_PAYOUT_IN_BALLO = ("maturato", "in_transito")


def obblighi_pendenti(sistema: Any, host_id: Any) -> Dict[str, Any]:
    """Cosa impedisce di cancellare un host SENZA lasciare qualcuno a piedi o un conto
    aperto. Ritorna {} se e' pulito, altrimenti i motivi con i numeri.

    Tre pericoli, tutti su soldi o su una persona reale:
      · prenotazioni ATTIVE (un ospite che ha pagato e sta per arrivare, o e' dentro);
      · PAYOUT DOVUTO (soldi che dobbiamo ancora bonificare all'host: cancellarlo li
        renderebbe orfani);
      · ESCROW APERTO (soldi di un ospite ancora in custodia su un suo alloggio);
      · TRANSAZIONI IN SOSPESO (richieste da approvare).

    Read-only, isolato per archivio: un archivio che non risponde non deve trasformarsi
    in un falso 'tutto pulito' che poi fa cancellare sopra dei soldi. Per questo, se un
    controllo NON si puo' fare, lo si segna come dubbio ('_incerti') invece di ignorarlo.
    """
    import datetime as _dt
    motivi: Dict[str, Any] = {}
    incerti: List[str] = []
    hid = str(host_id)
    cat = getattr(sistema, "catalogo", None)
    inv = getattr(sistema, "inventario", None)
    pay = getattr(sistema, "payout", None)
    pend = getattr(sistema, "pagamenti_pendenti", None)
    gar = getattr(sistema, "garanzia", None)
    slugs = _slug_host(cat, hid)

    # 1) prenotazioni attive/future su uno qualunque dei suoi alloggi
    oggi = _dt.date.today().isoformat()
    if inv is not None and hasattr(inv, "elenco_prenotazioni"):
        attive = 0
        for s in slugs:
            try:
                for p in (inv.elenco_prenotazioni(alloggio_id=s, limit=200) or []):
                    if not p.get("rimborsato") and str(p.get("check_out", "")) >= oggi:
                        attive += 1
            except Exception:
                incerti.append("prenotazioni:%s" % s)
                logger.warning("obblighi: prenotazioni %s (ISOLATO)", s, exc_info=True)
        if attive:
            motivi["prenotazioni_attive"] = attive
    else:
        incerti.append("prenotazioni")

    # 2) payout dovuto (maturato o in transito), in qualunque valuta
    if pay is not None and hasattr(pay, "riepilogo"):
        try:
            dovuti = {}
            for valuta, per_stato in (pay.riepilogo(hid) or {}).items():
                tot = sum(int(per_stato.get(s, 0) or 0) for s in _PAYOUT_IN_BALLO)
                if tot > 0:
                    dovuti[valuta] = tot
            if dovuti:
                motivi["payout_dovuto"] = dovuti
        except Exception:
            incerti.append("payout")
            logger.warning("obblighi: payout (ISOLATO)", exc_info=True)
    else:
        incerti.append("payout")

    # 3) escrow aperto su uno dei suoi alloggi (soldi dell'ospite in custodia)
    if gar is not None and hasattr(gar, "aperte_per_alloggio"):
        aperte = 0
        for s in slugs:
            try:
                aperte += int(gar.aperte_per_alloggio(s) or 0)
            except Exception:
                incerti.append("escrow:%s" % s)
                logger.warning("obblighi: escrow %s (ISOLATO)", s, exc_info=True)
        if aperte:
            motivi["escrow_aperto"] = aperte
    else:
        incerti.append("escrow")

    # 4) transazioni in sospeso (richieste da approvare)
    if pend is not None and hasattr(pend, "da_approvare"):
        try:
            n = len(pend.da_approvare(hid, limit=200) or [])
            if n:
                motivi["in_sospeso"] = n
        except Exception:
            incerti.append("in_sospeso")
            logger.warning("obblighi: sospesi (ISOLATO)", exc_info=True)
    else:
        incerti.append("in_sospeso")

    if incerti:
        motivi["_incerti"] = sorted(set(incerti))
    return motivi


def cancella_attivita_host(sistema: Any, host_id: Any, *, forza: bool = False) -> Dict[str, Any]:
    """Cancella host_id da OGNI archivio del sistema e verifica. Ritorna report:
    {host_id, cancellati:{archivio:n}, residui:{archivio:n}, ok:bool}.

    RIFIUTA se l'host ha soldi o persone in ballo (prenotazioni attive, payout dovuto,
    escrow aperto, sospesi) — a meno di `forza=True`, che serve per un obbligo legale
    inderogabile ma **registra comunque** cosa c'era, cosi' nulla sparisce in silenzio.
    Prima questa funzione cancellava SEMPRE, lasciando ospiti paganti senza stanza e
    bonifici orfani: era il buco piu' grave dell'audit del 2026-07-22."""
    rep: Dict[str, Any] = {"host_id": host_id, "cancellati": {}, "residui": {}, "ok": False}
    if not (isinstance(host_id, str) and host_id):
        rep["errore"] = "host_id_non_valido"
        return rep

    obblighi = obblighi_pendenti(sistema, host_id)
    if obblighi and not forza:
        rep["errore"] = "obblighi_pendenti"
        rep["obblighi"] = obblighi
        return rep                                  # NON si cancella: prima si sistema
    if obblighi and forza:
        rep["forzato_nonostante"] = obblighi        # tracciato: mai perso in silenzio
        # ⛔ `host_id` arriva dal CORPO della richiesta e questa riga finisce nel registro,
        # cioe' dove il Guardiano (fase186) cerca i guasti sui soldi: un a-capo qui dentro
        # fabbrica righe di allarme FALSE. E questa e' la riga che documenta la
        # CANCELLAZIONE FORZATA di un host che aveva obblighi pendenti -- l'ultima al mondo
        # che ci si puo' permettere di lasciar falsificare.
        # ⛔ Il rimedio NON si importa da `fase83_server`: questo modulo non lo importa, e
        # farlo per una riga di registro creerebbe una dipendenza fra un motore e il server
        # (D19: una difesa non deve dipendere dal comportamento di un altro). Sono due
        # chiamate, ed e' anche la forma che CodeQL riconosce come barriera
        # (`ReplaceLineBreaksSanitizer`, in `LogInjectionCustomizations.qll`).
        _hid = str(host_id).replace("\r\n", "\\n").replace("\n", "\\n")[:64]
        logger.critical("ERASURE FORZATA su host con obblighi: %s -> %s", _hid, obblighi)

    cat = getattr(sistema, "catalogo", None)
    inv = getattr(sistema, "inventario", None)
    reg = getattr(sistema, "registro_host", None)
    msg = getattr(sistema, "messaggistica", None)
    viral = getattr(sistema, "viral", None)

    slugs = _slug_host(cat, host_id)                       # PRIMA di cancellare il catalogo

    # ANTI-RICICLO DELLA PROMOZIONE: le impronte si depositano ORA, finche' i dati esistono
    # ancora. Dopo il DELETE non c'e' piu' niente da impastare e una ri-registrazione
    # otterrebbe altri 90 giorni a commissione zero. Si conservano SOLO impronte
    # irreversibili (mai i dati): email, telefono, codice fiscale, P.IVA e il CIN degli
    # annunci -- CIN e codice fiscale li rilascia lo Stato, non si cambiano con una mail nuova.
    if reg is not None and hasattr(reg, "deposita_impronte"):
        cin, cin_non_letti = [], []
        for s in slugs:
            try:
                d = cat.dettaglio(s) if (cat is not None and hasattr(cat, "dettaglio")) else None
                if isinstance(d, dict) and d.get("cin"):
                    cin.append(str(d["cin"]))
            except Exception:
                # ⛔ NON SI INGOIA IN SILENZIO (2026-08-01). Qui si legge il CIN, cioe'
                # l'impronta che impedisce a un host di cancellarsi e ri-registrarsi per
                # riprendersi i 90 giorni a commissione zero. Se la lettura fallisce e
                # nessuno lo sa, quel buco resta aperto per sempre. Il `pass` nudo di prima
                # nascondeva anche i DIFETTI: nessun mutante di queste righe era uccidibile
                # dall'esterno, perche' qualunque cosa andasse storta finiva nello stesso
                # silenzio. L'isolamento resta (gli altri alloggi si leggono lo stesso):
                # cambia solo che ora il fallimento si vede.
                cin_non_letti.append(s)
                logger.warning("erasure: CIN non letto per %s (ISOLATO)", s, exc_info=True)
        if cin_non_letti:
            rep["cin_non_letti"] = cin_non_letti
        rep["impronte_depositate"] = _safe(lambda h: reg.deposita_impronte(h, extra=cin), host_id)

    # --- cancella in ordine sicuro ---
    if inv is not None and hasattr(inv, "cancella_alloggio"):
        rep["cancellati"]["inventario"] = sum(_safe(inv.cancella_alloggio, s) for s in slugs)
    if cat is not None and hasattr(cat, "cancella_alloggi_host"):
        rep["cancellati"]["alloggi"] = _safe(cat.cancella_alloggi_host, host_id)
    if msg is not None and hasattr(msg, "cancella_messaggi_host"):
        rep["cancellati"]["messaggi"] = _safe(msg.cancella_messaggi_host, host_id)
    if viral is not None and hasattr(viral, "cancella_host"):
        rep["cancellati"]["referral"] = _safe(viral.cancella_host, host_id)
    if reg is not None and hasattr(reg, "cancella_host"):
        rep["cancellati"]["host"] = _safe(reg.cancella_host, host_id)

    # --- VERIFICA: ricontrolla OGNI archivio (deve essere 0) ---
    residui: Dict[str, int] = {}
    if cat is not None and hasattr(cat, "conta_alloggi_host"):
        residui["alloggi"] = _safe(cat.conta_alloggi_host, host_id)
    if inv is not None and hasattr(inv, "conta_alloggio"):
        residui["inventario"] = sum(_safe(inv.conta_alloggio, s) for s in slugs)
    if msg is not None and hasattr(msg, "conta_messaggi_host"):
        residui["messaggi"] = _safe(msg.conta_messaggi_host, host_id)
    if viral is not None and hasattr(viral, "conta_host"):
        residui["referral"] = _safe(viral.conta_host, host_id)
    if reg is not None and hasattr(reg, "esiste_host"):
        # il secondo `hasattr` che stava qui controllava la STESSA cosa dell'`if` qui sopra:
        # ramo morto, irraggiungibile. Tolto il 2026-08-01 (lo aveva scovato la mutazione,
        # che ci sbatteva contro un mutante impossibile da uccidere perche' impossibile da
        # raggiungere). Meno codice = meno posti dove nascondersi.
        residui["host"] = 1 if reg.esiste_host(host_id) else 0

    rep["residui"] = residui
    rep["verificato_archivi"] = list(residui.keys())

    # --- E ADESSO IL CONTROLLO CHE NON DIPENDE DA QUESTA LISTA ---------------------
    # ⛔ PERCHE' NON BASTAVA QUELLO SOPRA. I cinque archivi qui sopra sono nominati A MANO
    # dentro questo file, e questo file DICHIARA di essere resiliente: opera solo sugli
    # archivi che espongono i metodi giusti, cosi' «aggiungere un archivio nuovo non
    # richiede toccare questo file». Letta dal lato in cui morde: un archivio nuovo viene
    # saltato IN SILENZIO e il rapporto dice `ok=True` lo stesso. Misurato il 2026-09-12
    # percorrendo il giro intero (`collaudi/esame_oblio.py`): il dato della persona era
    # rimasto in un archivio che questa lista non nomina, e il rapporto diceva ok=True.
    # ⇒ Qui non si chiede a una lista: si guarda negli archivi VERI, contati come li conta
    # la produzione (i file `*.db` della cartella dati, stesso criterio di fase202).
    rimasto = _dove_e_rimasto(sistema, host_id)
    sporchi = rimasto.get("sporchi", {})
    rep["archivi_totali"] = rimasto.get("totali", 0)
    rep["archivi_sporchi"] = sporchi
    trattenuti: Dict[str, Dict[str, str]] = {}
    non_dichiarati: Dict[str, List[str]] = {}
    for _nome, _tabelle in sporchi.items():
        _con_legge = {t: TRATTENUTI_PER_LEGGE[t] for t in _tabelle
                      if t in TRATTENUTI_PER_LEGGE}
        _senza = [t for t in _tabelle if t not in TRATTENUTI_PER_LEGGE]
        if _con_legge:
            trattenuti[_nome] = _con_legge
        if _senza:
            non_dichiarati[_nome] = _senza
    rep["trattenuti_per_legge"] = trattenuti
    rep["sporchi_non_dichiarati"] = non_dichiarati
    if rimasto.get("motivo"):
        # Senza cartella dati (archivi in memoria) la scansione non si puo' fare: si
        # DICHIARA, e chi legge il rapporto lo vede. ⛔ Ma NON si trasforma in un rosso:
        # legandoci `ok` (primo tentativo del 2026-09-12) ogni sistema in memoria usciva
        # `ok=False` — nove guardie sane diventate rosse, cioe' un falso allarme, che e' un
        # difetto quanto un allarme mancato (regola ferrea 10). «Non eseguito» e' una terza
        # cosa: non e' «pulito» e non e' «sporco», e va detta con la sua parola.
        rep["scansione_non_eseguita"] = rimasto["motivo"]
        # ⛔ `info`, non `warning`: non e' un allarme su un passo fallito — di quelli la
        # guardia `test_ogni_guasto_ISOLATO_lascia_la_traccia_dell_errore` pretende
        # giustamente la traccia dell'eccezione, e la mia riga non ne ha nessuna perche'
        # non e' successo niente di male. Scriverla come allarme rendeva rossa una guardia
        # sana: il livello sbagliato non e' un dettaglio, e' un'informazione falsa.
        logger.info("OBLIO | host %s | scansione degli archivi veri NON eseguita (%s): "
                    "`ok` parla solo dei controlli mirati",
                    _mascherato(host_id), rimasto["motivo"])
    rep["ok"] = (bool(residui)
                 and all(v == 0 for v in residui.values())
                 and not rep["sporchi_non_dichiarati"])
    if rep["sporchi_non_dichiarati"]:
        logger.error("OBLIO INCOMPLETO | host %s | il dato e' rimasto in %d archivi che "
                     "NESSUNA legge dichiara di trattenere (su %d): %s",
                     _mascherato(host_id), len(rep["sporchi_non_dichiarati"]),
                     rep["archivi_totali"], sorted(rep["sporchi_non_dichiarati"]))
    return rep


def _mascherato(host_id: Any) -> str:
    """Un identificativo sicuro da scrivere nel registro: il registro dell'oblio non deve
    diventare il posto dove il dato sopravvive."""
    t = str(host_id or "")
    return (t[:3] + "***" + t[-2:]) if len(t) > 6 else "***"


def _dove_e_rimasto(sistema: Any, host_id: Any) -> Dict[str, Any]:
    """Gli archivi VERI in cui l'identificativo della persona compare ancora, cercato in
    ogni tabella e in ogni colonna di testo. Isolato: non solleva mai, e un archivio che
    non si legge finisce fra i motivi, mai fra i puliti.

    ⚠️ LIMITE DICHIARATO: cerca l'identificativo dell'host, non ogni dato che lo riguarda —
    una riga che lo nomina in altro modo non viene vista. E' un pavimento, non un soffitto:
    quello che trova e' rimasto per certo."""
    import glob as _glob
    import os as _os
    import sqlite3 as _sq
    ago = str(host_id or "")
    if not ago:
        return {"sporchi": {}, "totali": 0, "motivo": "host_id vuoto"}
    fin = getattr(getattr(sistema, "config", None), "db_finanza", "") or ""
    if fin in ("", ":memory:"):
        return {"sporchi": {}, "totali": 0,
                "motivo": "archivi in memoria: la scansione non e' possibile"}
    dir_dati = _os.path.dirname(fin)
    sporchi: Dict[str, List[str]] = {}
    totali = 0
    for percorso in sorted(_glob.glob(_os.path.join(dir_dati, "*.db"))):
        totali += 1
        nome = _os.path.basename(percorso)
        try:
            con = _sq.connect("file:%s?mode=ro" % percorso, uri=True)
            con.row_factory = _sq.Row
        except _sq.Error:
            sporchi.setdefault(nome, []).append("(archivio illeggibile: non giudicato)")
            continue
        try:
            tabelle = [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'")]
            for t in tabelle:
                try:
                    for r in con.execute('SELECT * FROM "%s"' % t.replace('"', '""')):  # noqa: S608
                        if any(isinstance(r[k], str) and ago in r[k] for k in r.keys()):
                            sporchi.setdefault(nome, []).append(t)
                            break
                except _sq.Error:
                    sporchi.setdefault(nome, []).append("(tabella %s illeggibile)" % t)
        except _sq.Error:
            sporchi.setdefault(nome, []).append("(archivio illeggibile: non giudicato)")
        finally:
            con.close()
    return {"sporchi": {k: sorted(set(v)) for k, v in sporchi.items()}, "totali": totali,
            "motivo": ""}
