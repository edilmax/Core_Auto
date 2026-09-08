"""L'ESAME DELLA CASELLA 2 DEL BLOCCO 6 (ESPERIENZA DELL'OSPITE) — i numeri MOSTRATI hanno senso nel mondo.

    python collaudi/esame_plausibilita.py                  legge i numeri che il sito VIVO mostra (catalogo
                                                           pubblico + dettaglio di ogni annuncio), misura e MOSTRA
    python collaudi/esame_plausibilita.py --scrivi         misura e SCRIVE nella scheda (anche un rosso, col motivo)
    python collaudi/esame_plausibilita.py --dati=CARTELLA  in piu', esegue i CONTROLLI di plausibilita.py sugli
                                                           ARCHIVI in quella cartella (una copia della produzione:
                                                           la porta B, che ha l'accesso al server)
    python collaudi/esame_plausibilita.py --salva F        salva le letture del sito in F (per giudicarle dopo)
    python collaudi/esame_plausibilita.py --da-file F      giudica letture salvate: niente rete
    python collaudi/esame_plausibilita.py --con-guasto     storce le letture (un prezzo x100, la trappola dello
                                                           yen): deve gridare, e NON scrive mai
    python collaudi/esame_plausibilita.py --autoprova      il giudizio su letture costruite, nelle due direzioni

⛔ IL TESTO DELLA CASELLA NON SI RICOPIA: si legge da `collaudi/piano.py` (e' la chiave della scheda).

D10 — QUESTO FILE NON RISCRIVE `collaudi/plausibilita.py`: LO RIUSA. Le bande (`NOTTE_MIN_EUR`, `NOTTE_MAX_EUR`),
la conversione `in_euro` (che chiede i decimali VERI al motore fase99), `valuta_nota` e i cinque CONTROLLI sugli
archivi sono i suoi. Quello che plausibilita.py non faceva -- e che la casella chiede -- e' guardare i numeri
DOVE L'OSPITE LI VEDE: le rotte pubbliche del sito vivo. Qui si aggiunge solo quello, piu' le quattro condizioni
di D18 (precondizioni, due direzioni, NON_GUARDA, guardia in test_pipeline_ci) che plausibilita.py non aveva.

COSA MISURA, dichiarato (D18) — decisione della chat A il 2026-09-07 col mandato di B, rovesciabile.
  MOSTRATI  per OGNI annuncio che /api/catalogo elenca (tutte le pagine, fino a `totale`) e per il suo
            /api/catalogo/<slug>: il prezzo a notte in euro sta nella banda di plausibilita.py; la valuta e'
            una sigla ISO; capacita', camere e bagni sono interi in bande umane (1..50, 0..50, 0..50); le
            recensioni hanno conteggio >= 0 e media 0..500 centesimi (0..5 stelle); le coordinate, se ci
            sono, stanno sulla Terra; la tassa di soggiorno a persona/notte, se c'e', e' sotto i 50 EUR e la
            percentuale sotto il 100%; e la scheda di dettaglio mostra LO STESSO prezzo, valuta e capacita'
            dell'elenco (due pagine, un solo numero). Denominatore = numeri esaminati.
  ARCHIVI   solo con `--dati=`: i cinque CONTROLLI di plausibilita.py sulla copia della produzione; ogni
            assurdita' che trovano e' un passo rosso, e «righe esaminate: 0» e' rosso (un denominatore zero
            non e' verde: e' l'assenza di misura, sbaglio S1).
  ⛔ ZERO ANNUNCI NON E' VERDE: se il catalogo vivo e' vuoto la casella non e' misurata (rosso col motivo).

⛔ D18: `precondizioni()` ferma il giro; `--autoprova` e `--con-guasto` (che non scrive mai); `NON_GUARDA`;
   guardia `test_pipeline_ci.TestLEsameDellaPlausibilitaNonPuoBARARE`. Sul sito vivo SOLO letture pubbliche
   (GET del catalogo), nessuna credenziale, nessuna scrittura. Ambiente: `os.environ` non viene toccato.
"""
import io
import json
import os
import sys
import urllib.error
import urllib.request

QUI = os.path.dirname(os.path.abspath(__file__))
RADICE = os.path.dirname(QUI)
for _p in (RADICE, QUI):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import plausibilita  # noqa: E402  (D10: si riusa, non si riscrive)
import scheda  # noqa: E402
from piano import BLOCCHI  # noqa: E402

BLOCCO = 6
MARCA = "ha senso nel mondo vero"
COMANDO = "python collaudi/esame_plausibilita.py --scrivi"
SITO = "https://bookinvip.com"
SITUAZIONI = ("mostrati",)
SITUAZIONI_CON_ARCHIVI = ("mostrati", "archivi")
PAGINA = 100
TETTO_ANNUNCI = 2000
BANDE = {"capacita": (1, 50), "camere": (0, 50), "bagni": (0, 50), "recensioni.conteggio": (0, 10 ** 6),
         "recensioni.media_centesimi": (0, 500), "tassa_max_notti": (0, 60), "tassa_perc_bps": (0, 10000)}
TASSA_PP_MAX_EUR = 50.0
PASSI = []

NON_GUARDA = (
    "i numeri dentro le pagine HTML disegnate dal browser (index.html/app.js): qui si leggono le rotte JSON "
    "da cui quelle pagine prendono i numeri, non la loro resa a schermo (e' l'occhio del fondatore)",
    "i preventivi (/api/concierge/quote) e i totali di una prenotazione: chiederli crea un hold sul sito vivo; "
    "la loro aritmetica e' il blocco SOLDI (esame_prezzi, oracolo del payout)",
    "i numeri riservati (pannello host, admin, bunker): servono credenziali, e sul sito vivo questo esame "
    "non ne usa; gli archivi si guardano con `--dati` su una copia",
    "gli archivi di PRODUZIONE dal vivo: questo computer non li ha; `--dati` li legge da una copia che porta B",
    "se un prezzo «plausibile» sia anche GIUSTO: la banda ferma il x100 dello yen, non un prezzo sbagliato "
    "del 20%",
    "i testi (titolo, citta', paese): la casella parla di NUMERI; un `paese: XX` si stampa nel rapporto ma non "
    "e' un passo",
)


def passo(situazione, nome, ok, dettaglio=""):
    PASSI.append((situazione, nome, bool(ok), dettaglio))
    print("  %s  [%s] %s%s" % ("OK  " if ok else "ROSSO", situazione, nome,
                                ("  -> " + dettaglio) if dettaglio else ""))
    return bool(ok)


# --------------------------------------------------------------------------------------
# IL GIUDIZIO (puro): letture -> passi -> verdetto
# --------------------------------------------------------------------------------------
def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _in(v, banda):
    return _num(v) and banda[0] <= v <= banda[1]


def giudica_annuncio(elenco, dettaglio):
    """I passi per UN annuncio: (nome, ok, dettaglio). Puro: niente rete, niente archivi."""
    fuori = []
    slug = str(elenco.get("slug") or "?")
    prezzo, valuta = elenco.get("prezzo_notte_cents"), elenco.get("valuta")
    ok_val = plausibilita.valuta_nota(valuta)
    fuori.append(("%s: valuta ISO" % slug, ok_val, "valuta=%r" % (valuta,)))
    if ok_val and _num(prezzo):
        try:
            eur = plausibilita.in_euro(prezzo, valuta)
            fuori.append(("%s: prezzo a notte in banda (%.0f..%.0f EUR)" % (slug, plausibilita.NOTTE_MIN_EUR,
                                                                              plausibilita.NOTTE_MAX_EUR),
                          plausibilita.NOTTE_MIN_EUR <= eur <= plausibilita.NOTTE_MAX_EUR,
                          "%s %s = %.2f EUR" % (prezzo, valuta, eur)))
        except Exception as e:                                   # noqa: BLE001 - una conversione rotta e' un rosso
            fuori.append(("%s: prezzo a notte convertibile" % slug, False, "%s: %s" % (type(e).__name__, e)))
    else:
        fuori.append(("%s: prezzo a notte e' un numero" % slug, _num(prezzo), "prezzo=%r" % (prezzo,)))
    for campo, banda in BANDE.items():
        if "." in campo:
            a, b = campo.split(".")
            v = (elenco.get(a) or {}).get(b) if isinstance(elenco.get(a), dict) else None
        else:
            v = elenco.get(campo, dettaglio.get(campo))
        if v is None and campo.startswith("tassa"):
            continue                                              # la tassa puo' non esserci
        fuori.append(("%s: %s in banda %s" % (slug, campo, banda), _in(v, banda), "%s=%r" % (campo, v)))
    lat, lon = elenco.get("lat_micro"), elenco.get("lon_micro")
    if lat is not None or lon is not None:
        fuori.append(("%s: coordinate sulla Terra" % slug,
                      _in(lat, (-90 * 10 ** 6, 90 * 10 ** 6)) and _in(lon, (-180 * 10 ** 6, 180 * 10 ** 6)),
                      "lat=%r lon=%r" % (lat, lon)))
    tassa = dettaglio.get("tassa_pp_notte_cents")
    if tassa is not None:
        try:
            eur = plausibilita.in_euro(tassa, valuta) if ok_val else float("inf")
        except Exception:                                         # noqa: BLE001
            eur = float("inf")
        fuori.append(("%s: tassa a persona/notte sotto %.0f EUR" % (slug, TASSA_PP_MAX_EUR),
                      _num(tassa) and 0 <= eur <= TASSA_PP_MAX_EUR, "tassa=%r (%.2f EUR)" % (tassa, eur)))
    if dettaglio:
        uguali = all(elenco.get(k) == dettaglio.get(k) for k in ("prezzo_notte_cents", "valuta", "capacita"))
        fuori.append(("%s: elenco e dettaglio mostrano lo STESSO prezzo, valuta e capacita'" % slug, uguali,
                      "elenco=%r dettaglio=%r" % ({k: elenco.get(k) for k in ("prezzo_notte_cents", "valuta", "capacita")},
                                                  {k: dettaglio.get(k) for k in ("prezzo_notte_cents", "valuta", "capacita")})))
    else:
        fuori.append(("%s: la scheda di dettaglio risponde" % slug, False, "dettaglio assente"))
    return fuori


def giudica(passi, situazioni=SITUAZIONI):
    motivi = []
    for s in situazioni:
        suoi = [p for p in passi if p[0] == s]
        if not suoi:
            motivi.append("situazione «%s» NON misurata" % s)
            continue
        for _s, nome, ok, dettaglio in suoi:
            if not ok:
                motivi.append("[%s] %s%s" % (s, nome, (" (%s)" % dettaglio) if dettaglio else ""))
    fuori = [p for p in passi if p[0] not in situazioni]
    if fuori:
        motivi.append("passi fuori dalle situazioni: %d" % len(fuori))
    return (not motivi), motivi, len(passi)


def condizione():
    blocco = [b for b in BLOCCHI if b["ordine"] == BLOCCO]
    cond = blocco[0]["finito_quando"] if len(blocco) == 1 else ()
    trovate = [c for c in cond if MARCA in str(c)]
    if len(trovate) != 1:
        raise RuntimeError("nel blocco %d trovo %d caselle con «%s»: ne serve UNA" % (BLOCCO, len(trovate), MARCA))
    return trovate[0]


def precondizioni(con_rete=True):
    fuori = []
    try:
        testo = " ".join(str(condizione()).split())
        fuori.append(("la casella esiste nel piano, una sola, e parla del modo di rompersi 10", "10" in testo, testo[:70]))
    except Exception as e:
        fuori.append(("la casella esiste nel piano, una sola", False, str(e)))
    try:
        impronta = scheda.impronta_del_blocco(BLOCCO)
        fuori.append(("il blocco ha un'impronta", bool(impronta), impronta or "il piano non si legge"))
    except Exception as e:
        fuori.append(("il blocco ha un'impronta", False, str(e)))
    try:
        eur = plausibilita.in_euro(180000000, "JPY")
        fuori.append(("plausibilita.py risponde e sa che lo yen non ha decimali (1.800.000 JPY ~ %.0f EUR)" % eur,
                      eur > plausibilita.NOTTE_MAX_EUR and plausibilita.NOTTE_MIN_EUR < plausibilita.NOTTE_MAX_EUR,
                      "%d controlli negli archivi" % len(plausibilita.CONTROLLI)))
    except Exception as e:
        fuori.append(("plausibilita.py risponde", False, "%s: %s" % (type(e).__name__, e)))
    if con_rete:
        try:
            with urllib.request.urlopen(SITO + "/api/health", timeout=20) as r:   # noqa: S310  # nosec B310 - https fisso, sola lettura
                fuori.append(("il sito vivo risponde (/api/health)", r.status == 200, "http=%s" % r.status))
        except Exception as e:
            fuori.append(("il sito vivo risponde (/api/health)", False, "%s: %s" % (type(e).__name__, e)))
    return all(ok for _, ok, _ in fuori), fuori


# --------------------------------------------------------------------------------------
# LE LETTURE (rete, sola lettura pubblica)
# --------------------------------------------------------------------------------------
def _get_json(url):
    if not str(url).startswith("https://"):
        raise ValueError("solo https: %r" % (url,))
    with urllib.request.urlopen(url, timeout=30) as r:                            # noqa: S310  # nosec B310 - solo https, sola lettura
        return r.status, json.loads(r.read().decode("utf-8", "replace"))


def leggi_dal_vivo(sito=SITO):
    letture = {"sito": sito, "annunci": []}
    offset, totale = 0, None
    while True:
        st, corpo = _get_json("%s/api/catalogo?limit=%d&offset=%d" % (sito, PAGINA, offset))
        if st != 200 or not isinstance(corpo, dict):
            raise RuntimeError("catalogo: http %s" % st)
        totale = int(corpo.get("totale") or 0)
        risultati = corpo.get("risultati") or []
        for el in risultati:
            slug = el.get("slug")
            dett = {}
            try:
                st2, dett = _get_json("%s/api/catalogo/%s" % (sito, urllib.request.quote(str(slug))))
                dett = dett if st2 == 200 and isinstance(dett, dict) else {}
            except urllib.error.HTTPError as e:
                dett = {"_http": e.code}
            letture["annunci"].append({"elenco": el, "dettaglio": dett})
        offset += len(risultati)
        if not risultati or offset >= totale or offset >= TETTO_ANNUNCI:
            break
    letture["totale_dichiarato"] = totale
    return letture


def misura_mostrati(letture, con_guasto=False):
    print("\n--- MOSTRATI: ogni annuncio del catalogo pubblico, elenco + dettaglio ---")
    annunci = list(letture.get("annunci") or [])
    if con_guasto and annunci:
        annunci[0] = json.loads(json.dumps(annunci[0]))
        annunci[0]["elenco"]["prezzo_notte_cents"] = int(annunci[0]["elenco"].get("prezzo_notte_cents") or 100) * 100
        annunci[0]["dettaglio"]["prezzo_notte_cents"] = annunci[0]["elenco"]["prezzo_notte_cents"]
    passo("mostrati", "il catalogo elenca almeno un annuncio (zero annunci = casella NON misurata)",
          len(annunci) > 0 and len(annunci) == int(letture.get("totale_dichiarato") or 0),
          "annunci=%d totale dichiarato=%r" % (len(annunci), letture.get("totale_dichiarato")))
    for a in annunci:
        for nome, ok, dett in giudica_annuncio(a.get("elenco") or {}, a.get("dettaglio") or {}):
            passo("mostrati", nome, ok, dett)
    testi_strani = [str((a.get("elenco") or {}).get("slug")) for a in annunci
                    if str((a.get("elenco") or {}).get("paese") or "").upper() in ("", "XX", "ZZ")]
    if testi_strani:
        print("  ℹ️  (non e' un passo) annunci con `paese` vuoto o segnaposto: %r" % (testi_strani,))


def misura_archivi(cartella):
    print("\n--- ARCHIVI (--dati): i cinque controlli di plausibilita.py su una copia della produzione ---")
    del plausibilita.VIOL[:]
    plausibilita.CONTA["controlli"] = 0
    plausibilita.CONTA["righe"] = 0
    passo("archivi", "la cartella dei dati esiste", os.path.isdir(cartella), cartella)
    if not os.path.isdir(cartella):
        return
    for nome, funzione in plausibilita.CONTROLLI:
        prima = len(plausibilita.VIOL)
        try:
            funzione(cartella)
        except Exception as e:                                    # noqa: BLE001 - un controllo rotto e' un rosso
            plausibilita.viola(nome, "(esecuzione)", "%s: %s" % (type(e).__name__, e))
        nuove = plausibilita.VIOL[prima:]
        passo("archivi", "controllo «%s»: nessuna assurdita'" % nome, not nuove,
              "; ".join("%s: %s" % (c, d) for _a, c, d in nuove)[:300])
    passo("archivi", "righe esaminate > 0 (un denominatore zero non e' verde)", plausibilita.CONTA["righe"] > 0,
          "righe=%d controlli=%d" % (plausibilita.CONTA["righe"], plausibilita.CONTA["controlli"]))


# --------------------------------------------------------------------------------------
def annuncio_finto(**kw):
    el = {"slug": kw.pop("slug", "casa-finta"), "prezzo_notte_cents": 12000, "valuta": "EUR", "capacita": 4,
          "camere": 2, "bagni": 1, "lat_micro": 41900000, "lon_micro": 12500000,
          "recensioni": {"conteggio": 3, "media_centesimi": 450}}
    el.update(kw)
    dett = dict(el)
    dett["tassa_pp_notte_cents"] = kw.get("tassa_pp_notte_cents", 350)
    return {"elenco": el, "dettaglio": dett}


def autoprova():
    casi = [
        ("un annuncio sano", {"annunci": [annuncio_finto()], "totale_dichiarato": 1}, True),
        ("lo yen x100 (1.800.000 JPY a notte)", {"annunci": [annuncio_finto(prezzo_notte_cents=180000000, valuta="JPY")], "totale_dichiarato": 1}, False),
        ("lo yen giusto (18.000 JPY a notte)", {"annunci": [annuncio_finto(prezzo_notte_cents=18000, valuta="JPY")], "totale_dichiarato": 1}, True),
        ("valuta inventata", {"annunci": [annuncio_finto(valuta="EURO")], "totale_dichiarato": 1}, False),
        ("capacita' 0", {"annunci": [annuncio_finto(capacita=0)], "totale_dichiarato": 1}, False),
        ("media recensioni 6 stelle", {"annunci": [annuncio_finto(recensioni={"conteggio": 1, "media_centesimi": 600})], "totale_dichiarato": 1}, False),
        ("coordinate fuori dalla Terra", {"annunci": [annuncio_finto(lat_micro=95000000)], "totale_dichiarato": 1}, False),
        ("dettaglio con un prezzo DIVERSO dall'elenco", {"annunci": [_dettaglio_diverso()], "totale_dichiarato": 1}, False),
        ("zero annunci", {"annunci": [], "totale_dichiarato": 0}, False),
        ("totale dichiarato diverso dagli annunci letti", {"annunci": [annuncio_finto()], "totale_dichiarato": 2}, False),
    ]
    righe, riuscita = [], True
    for nome, letture, atteso in casi:
        del PASSI[:]
        flusso, vero = io.StringIO(), sys.stdout
        sys.stdout = flusso
        try:
            misura_mostrati(letture)
        finally:
            sys.stdout = vero
        verde, motivi, den = giudica(PASSI)
        ok = verde == atteso
        riuscita = riuscita and ok
        righe.append("   %-46s -> %-6s (atteso %-6s) denominatore %d%s"
                     % (nome, "VERDE" if verde else "ROSSO", "VERDE" if atteso else "ROSSO", den,
                        "" if ok else "   ⛔ NON E' QUELLO CHE DOVEVA DIRE: %s" % "; ".join(motivi)[:200]))
    del PASSI[:]
    return riuscita, righe


def _dettaglio_diverso():
    a = annuncio_finto()
    a["dettaglio"]["prezzo_notte_cents"] = 12100
    return a


def _stampa_non_guarda():
    print("-" * 86)
    print("⛔ COSA QUESTO ESAME NON HA ESAMINATO (D18 punto 3)")
    for r in NON_GUARDA:
        print("   · %s" % r)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    os.chdir(RADICE)
    del PASSI[:]
    print("=" * 86)
    print("🧾 ESAME DEL BLOCCO 6 — casella 2: i numeri mostrati hanno senso nel mondo vero")
    print("=" * 86)

    if "--autoprova" in argv:
        print("🔁 AUTOPROVA — il giudizio si vede gridare e tacere su letture costruite (D18 punto 2)")
        riuscita, righe = autoprova()
        for r in righe:
            print(r)
        _stampa_non_guarda()
        print("=" * 86)
        print("VERDETTO: %s" % ("✅ il giudizio grida sulle assurdita' e tace sui numeri sani" if riuscita
                                else "⛔ IL GIUDIZIO NON E' AFFIDABILE"))
        return 0 if riuscita else 1

    con_guasto = "--con-guasto" in argv
    if con_guasto and "--scrivi" in argv:
        print("⛔ FERMO: `--con-guasto` non scrive. Serve a vedere l'esame gridare; registrare quel")
        print("   rosso metterebbe nella scheda un prezzo x100 costruito apposta.")
        return 2

    da_file = argv[argv.index("--da-file") + 1] if "--da-file" in argv else None
    cartella = None
    for a in argv:
        if a.startswith("--dati="):
            cartella = a.split("=", 1)[1]
    tutte_ok, righe = precondizioni(con_rete=da_file is None)
    print("PRIMA DI MISURARE, L'ESAME MISURA SE STESSO (D18 punto 1)")
    for nome, ok, motivo in righe:
        print("  %-9s %-80s %s" % ("OK" if ok else "⛔ NO", nome, motivo))
    if not tutte_ok:
        print("VERDETTO: ⛔ FERMO — una precondizione non regge, quindi NON misuro e NON scrivo.")
        _stampa_non_guarda()
        return 2
    if con_guasto:
        print("⚠️  PASSATA COL GUASTO DENTRO: il primo annuncio ha il prezzo x100")

    ambiente_prima = dict(os.environ)
    try:
        if da_file:
            with io.open(da_file, encoding="utf-8") as f:
                letture = json.load(f)
            print("letture da file: %s (%d annunci)" % (da_file, len(letture.get("annunci") or [])))
        else:
            letture = leggi_dal_vivo()
            print("letture dal vivo: %s (%d annunci, totale dichiarato %r)"
                  % (SITO, len(letture["annunci"]), letture.get("totale_dichiarato")))
            if "--salva" in argv:
                percorso = argv[argv.index("--salva") + 1]
                with io.open(percorso, "w", encoding="utf-8") as f:
                    json.dump(letture, f, ensure_ascii=False, indent=1)
                print("letture salvate in %s" % percorso)
    except Exception as e:                                        # noqa: BLE001 - una lettura rotta e' un rosso
        letture = {"annunci": [], "totale_dichiarato": 0}
        passo("mostrati", "le letture sono ESPLOSE", False, "%s: %s" % (type(e).__name__, e))
    situazioni = SITUAZIONI_CON_ARCHIVI if cartella else SITUAZIONI
    try:
        misura_mostrati(letture, con_guasto)
    except Exception as e:                                        # noqa: BLE001
        passo("mostrati", "la misura e' ESPLOSA", False, "%s: %s" % (type(e).__name__, e))
    if cartella:
        try:
            misura_archivi(cartella)
        except Exception as e:                                    # noqa: BLE001
            passo("archivi", "la misura e' ESPLOSA", False, "%s: %s" % (type(e).__name__, e))
    passo("mostrati", "l'ambiente (os.environ) e' identico a prima della misura", dict(os.environ) == ambiente_prima)

    verde, motivi, denominatore = giudica(PASSI, situazioni)
    print("")
    print("VERDETTO: %s — passi %d, rossi %d, denominatore %d"
          % ("✅ VERDE" if verde else "⛔ ROSSO", len(PASSI), sum(1 for p in PASSI if not p[2]), denominatore))
    for m in motivi[:40]:
        print("   perche': %s" % m)
    if "--scrivi" in argv:
        print("")
        print("SCRITTURA NELLA SCHEDA")
        riga = scheda.registra(condizione(), esito=verde, denominatore=denominatore, comando=COMANDO,
                               ordine=BLOCCO, motivo="; ".join(motivi)[:600] or None)
        print("  scritta: blocco %d · esito %s · denominatore %d · impronta %s · motivo: %s"
              % (riga["blocco"], riga["esito"], riga["denominatore"], riga["impronta"], riga.get("motivo") or "-"))
    else:
        print("")
        print("(non ho scritto niente: aggiungi --scrivi per registrare nella scheda)")
    _stampa_non_guarda()
    print("=" * 86)
    return 0 if verde else 1


if __name__ == "__main__":
    sys.exit(main())
