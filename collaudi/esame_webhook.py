"""L'ESAME DELLE CASELLE 7-10 DEL BLOCCO SOLDI — il gestore dei webhook di Stripe.

    python collaudi/esame_webhook.py               misura e MOSTRA, senza scrivere
    python collaudi/esame_webhook.py --scrivi      misura e SCRIVE le quattro caselle
                                                   (anche false, col loro motivo onesto)
    python collaudi/esame_webhook.py --autoprova   si vede gridare e tacere (D18 punto 2)

⛔ IL TESTO DELLE CASELLE NON SI RICOPIA: si legge da `piano.py` (l'indice della lista
   `finito_quando` del blocco 1) e le precondizioni verificano che l'indice dica ancora
   la cosa giusta: se il piano cambia ordine, l'esame si ferma invece di spuntare la
   casella sbagliata.

COME MISURA:
  1. LE GUARDIE VERE SI ESEGUONO (test_webhook_dedup_fatto, test_sweep_eventi,
     test_fase87_stripe_webhook): un esito qui e' un giro di test osservato, non un file
     rilegto.
  2. I FATTI STRUTTURALI si leggono dal CODICE (testo dei moduli di produzione): la firma
     sul corpo grezzo, il ramo di non-2xx quando l'evento non si registra, l'assenza di
     DELETE dall'archivio (la memoria della dedup non scade), lo sweeper che ridelivera'.
  3. LE CASELLE 7 e 10 NON SONO VERDI e l'esame lo DICE, col motivo e con la storia: la
     7 per scelta dichiarata (il verdetto sul V4 potenziato giudica piu' sicuro lo schema
     attuale), la 10 perche' la decisione «autorizzato» del 2026-08-08 non e' stata ancora
     realizzata (raggio misurato: 82 banchi di prova passano dal webhook).

⛔ D18: precondizioni che fermano il giro, autoprova nelle due direzioni, NON_GUARDA
   stampato a ogni giro, e la guardia `TestLEsameDelWebhookNonPuoBARARE` in
   test_pipeline_ci.py che prova che PUO' barare prima che lo faccia.
"""
import ast
import io
import os
import re
import sys
import unittest

QUI = os.path.dirname(os.path.abspath(__file__))
RADICE = os.path.dirname(QUI)
for _p in (RADICE, QUI):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from piano import BLOCCHI  # noqa: E402
import scheda  # noqa: E402

BLOCCO_SOLDI = 1
# Indici (0-based) nella lista `finito_quando` del blocco 1. ⛔ NON si ricopiano i testi.
INDICI = {"webhook": 6, "dedup": 7, "sweep": 8, "rilettura": 9}
COMANDO = "python collaudi/esame_webhook.py --scrivi"
GUARDIE = ("test_webhook_dedup_fatto", "test_sweep_eventi", "test_fase87_stripe_webhook")
SEGNALI = {  # cio' che ogni indice DEVE dire, per accorgersi se il piano cambia ordine
    "webhook": ("firma", "salva"),
    "dedup": ("due volte", "72"),
    "sweep": ("non elaborato", "ritentato"),
    "rilettura": ("rilegge", "API"),
}
NON_GUARDA = (
    "l'esame non interroga Stripe: la firma e i corpi sono giudicati dai banchi con "
    "Stripe finto al bordo e dall'archivio vero; l'unico giro contro Stripe di prova "
    "resta l'E2E dell'esame dei rimborsi",
    "il cron dello sweeper SUL VPS (la riga nel crontab di root) non si vede da qui: "
    "l'installazione si verifica a mano con `crontab -l`, come per la riconciliazione",
    "la DECISIONE sulla casella 7 (architettura differita vs testo riscritto) e sulla "
    "casella 10 (quando realizzare la rilettura: raggio 82 banchi) non e' una misura: "
    "e' una scelta del fondatore, e qui resta scritta come tale",
)


def testo_casella(chiave):
    """Il testo della casella DAL PIANO, con la verifica del segnalino: se l'ordine della
    lista cambia, l'esame dice di non saperla piu' leggere invece di spuntare a caso."""
    condizioni = BLOCCHI[BLOCCO_SOLDI - 1]["finito_quando"]
    i = INDICI[chiave]
    testo = " ".join(str(condizioni[i]).split())
    if not all(s.lower() in testo.lower() for s in SEGNALI[chiave]):
        raise ValueError("la casella %d non dice piu' %r: il piano e' cambiato, questo "
                         "esame non sa piu' a cosa punta (S2: i nomi si leggono, non si "
                         "ricordano)" % (i, SEGNALI[chiave]))
    return testo


def testo_modulo(nome):
    with io.open(os.path.join(RADICE, nome), encoding="utf-8") as f:
        return f.read()


def guardie():
    """Esegue le guardie vere e torna (nome, verdi, rossi, dettaglio)."""
    fuori = []
    for nome in GUARDIE:
        caricatore = unittest.TestLoader()
        suite = caricatore.loadTestsFromName(nome)
        flusso = io.StringIO()
        esito = unittest.TextTestRunner(stream=flusso, verbosity=0).run(suite)
        fuori.append((nome, esito.wasSuccessful(), len(esito.failures) + len(esito.errors),
                      flusso.getvalue()[-400:]))
    return fuori


def fatti_strutturali():
    """I fatti che si leggono dal codice di produzione (testo e albero sintattico)."""
    fuori = {}
    server = testo_modulo("fase83_server.py")
    archivio = testo_modulo("fase204_eventi_stripe.py")
    sweep = testo_modulo(os.path.join("deploy", "cron_sweep_eventi.py"))
    albero = ast.parse(server, filename="fase83_server.py")
    # (a) la firma viene verificata sul corpo GREZZO: `gestisci_webhook(body ...)` —
    # il primo argomento e' il body della richiesta, non un JSON ri-serializzato.
    fuori["firma_sul_grezzo"] = bool(re.search(
        r"gestisci_webhook\(body or \"\"", server))
    # (b) l'evento si salva PRIMA di rispondere e il non-salvato e' un NON-2xx: se Stripe
    # non vede la riga, deve ritentare.
    fuori["salva_prima_della_risposta"] = bool(re.search(
        r"_archivio\.salva\(_evt", server)) and bool(re.search(
        r"return 503, \{\"errore\": \"evento_non_registrato\"", server))
    # (c) la memoria della dedup NON scade: nessun DELETE sull'archivio degli eventi.
    fuori["memoria_non_scade"] = ("DELETE" not in archivio)
    # (d) lo sweeper: ridelivery con firma, tentativi contati, anomalia a un'ora.
    fuori["sweep_esiste"] = bool(re.search(r"_webhook_stripe_registrato", sweep)) and \
        bool(re.search(r"segna_tentativo", sweep)) and \
        bool(re.search(r"ANOMALIA_SEC = 3600", sweep))
    # (e) la rilettura dello stato dall'API nel percorso di conferma: NON c'e' (casella
    # 9) — si misura l'assenza, perche' il rosso onesto valga per quello che e'.
    fuori["rilettura_nella_conferma"] = bool(re.search(
        r"\.pagamento\(", server)) or bool(re.search(r"payment_status", server))
    del albero
    return fuori


def precondizioni():
    """(tutte_ok, righe). Un metro storto va scoperto dal metro (D18 punto 1)."""
    righe = []
    try:
        for chiave in INDICI:
            testo_casella(chiave)
        righe.append(("le quattro caselle si leggono dal piano", True,
                      ", ".join(sorted(INDICI))))
    except Exception as e:
        righe.append(("le quattro caselle si leggono dal piano", False, str(e)))
    for nome in GUARDIE:
        ok = os.path.isfile(os.path.join(RADICE, nome + ".py"))
        righe.append(("la guardia %s esiste" % nome, ok,
                      nome if ok else "MANCA: niente da accendere"))
    for nome in ("fase83_server.py", "fase204_eventi_stripe.py",
                 "fase87_stripe_webhook.py", os.path.join("deploy", "cron_sweep_eventi.py")):
        ok = os.path.isfile(os.path.join(RADICE, nome))
        righe.append(("il modulo %s esiste" % nome, ok, nome))
    try:
        fatti = fatti_strutturali()
        righe.append(("i moduli di produzione si leggono", len(fatti) >= 5,
                      "%d fatti strutturali" % len(fatti)))
    except Exception as e:
        righe.append(("i moduli di produzione si leggono", False, str(e)))
    return all(ok for _, ok, _ in righe), righe


def misura():
    """Le quattro caselle: esito, denominatore, motivo. Nessun verde sottinteso."""
    g = guardie()
    rossi = [nome for nome, ok, _, _ in g if not ok]
    fatti = fatti_strutturali()
    n_guardie = sum(1 for _, ok, _, _ in g if ok)

    # CAS. 7 (webhook): tre condizioni vere e una per scelta dichiarata. ⛔ La quarta
    # («lo elabora DOPO, in un passo separato») NON esiste nel codice: il gestore
    # elabora dentro la risposta, ed e' la scelta dichiarata in fase204 (120 chiamate in
    # 81 banchi la presuppongono) — la casella resta rossa finche' il fondatore decide.
    web_ok = fatti["firma_sul_grezzo"] and fatti["salva_prima_della_risposta"] \
        and not rossi
    web_esito = False
    dedup_ok = (not rossi) and fatti["memoria_non_scade"]
    sweep_ok = fatti["sweep_esiste"] and not rossi
    web_motivo = ""
    if not web_esito:
        web_motivo = ("tre condizioni su quattro sono vere e sorvegliate (firma sul corpo "
                      "grezzo, salvataggio prima della risposta, NON-2xx se non salvato); "
                      "«lo elabora DOPO, in un passo separato» NON e' fatto PER SCELTA "
                      "DICHIARATA: 120 chiamate in 81 banchi aspettano la conferma dentro "
                      "la risposta, e il verdetto sul V4 potenziato (2026-09-21) giudica "
                      "piu' sicuro lo schema attuale (2xx solo se applicato). Chiudere la "
                      "casella richiede la scelta del fondatore: architettura differita o "
                      "testo della casella riscritto")
    rilettura = fatti["rilettura_nella_conferma"]
    rilettura_motivo = ""
    if not rilettura:
        rilettura_motivo = ("la conferma oggi crede al contenuto dell'evento: la rilettura "
                            "dello stato dall'API esiste come shadow-check (fase181) e "
                            "nella riconciliazione (fase182), NON nel percorso di conferma. "
                            "La decisione «autorizzato» del 2026-08-08 (confermare solo con "
                            "payment_status riletto) e' rimasta indietro: il raggio misurato "
                            "e' 82 banchi di prova che passano dal webhook — lavoro a se', "
                            "da schedulare col fondatore")

    esiti = {
        "webhook": (web_esito, 4, web_motivo),
        "dedup": (dedup_ok, 2 + n_guardie,
                  "" if dedup_ok else "guardie rosse: %s" % ", ".join(rossi)),
        "sweep": (sweep_ok, 3 + n_guardie,
                  "" if sweep_ok else "guardie rosse o sweeper incompleto"),
        "rilettura": (rilettura, 1, rilettura_motivo),
    }
    return esiti, g, fatti


def autoprova():
    """D18 punto 2: col guasto dentro la guardia della dedup deve GRIDARE, a macchina
    sana deve TACERE. Il guasto: il fatto non e' mai gia' visto (dedup spenta)."""
    import fase204_eventi_stripe as archivio_mod
    vero = archivio_mod.ArchivioEventiStripe.fatto_gia_presente
    archivio_mod.ArchivioEventiStripe.fatto_gia_presente = lambda self, **k: False
    try:
        caricatore = unittest.TestLoader()
        suite = caricatore.loadTestsFromName(
            "test_webhook_dedup_fatto.TestDedupPerFatto."
            "test_due_eventi_diversi_per_lo_stesso_fatto_contano_UNO")
        flusso = io.StringIO()
        esito = unittest.TextTestRunner(stream=flusso, verbosity=0).run(suite)
        grida = not esito.wasSuccessful()
    finally:
        archivio_mod.ArchivioEventiStripe.fatto_gia_presente = vero
    flusso2 = io.StringIO()
    suite2 = unittest.TestLoader().loadTestsFromName(
        "test_webhook_dedup_fatto.TestDedupPerFatto."
        "test_due_eventi_diversi_per_lo_stesso_fatto_contano_UNO")
    tace = unittest.TextTestRunner(stream=flusso2, verbosity=0).run(suite2).wasSuccessful()
    return grida, tace, flusso.getvalue()[-200:]


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    tutte_ok, righe = precondizioni()
    print("=" * 86)
    print("🧾 ESAME WEBHOOK — caselle 7-10 del blocco SOLDI (fase204/fase83/fase87/sweeper)")
    print("=" * 86)
    for nome, ok, dettaglio in righe:
        print("  %-6s %s  %s" % ("OK" if ok else "ROSSO", nome, dettaglio))
    if not tutte_ok:
        print("VERDETTO: ⛔ NON ESEGUIBILE — le precondizioni non reggono (S7): niente "
              "scritture, niente numeri")
        return 2
    esiti, g, fatti = misura()
    for nome, ok, rossi, dettaglio in g:
        print("  guardia %-32s %s (%d rossi)" % (nome, "VERDE" if ok else "ROSSA", rossi))
    for nome, (esito, denominatore, motivo) in esiti.items():
        print("  casella %-12s %s  (denominatore %d)%s"
              % (nome, "☑" if esito else "☐", denominatore,
                 ("\n     perche': %s" % motivo) if motivo else ""))
    if "--autoprova" in argv:
        grida, tace, dettaglio = autoprova()
        print("  AUTOPROVA: grida col guasto=%s · tace a macchina sana=%s %s"
              % (grida, tace, "" if (grida and tace) else dettaglio))
        # L'autoprova risponde a UNA domanda sola: «l'esame sa vedere il proprio guasto?».
        # Le caselle rosse ONESTE (7 e 10) non sono un suo fallimento e non cambiano qui
        # il codice d'uscita.
        return 0 if (grida and tace) else 1
    if "--scrivi" in argv:
        for chiave, (esito, denominatore, motivo) in esiti.items():
            scheda.registra(testo_casella(chiave), esito=esito, denominatore=denominatore,
                            comando=COMANDO, ordine=BLOCCO_SOLDI, motivo=motivo or None)
        print("  🗂️  quattro caselle scritte (anche le false, col motivo)")
    verdi = sum(1 for e, _, _ in esiti.values() if e)
    print("VERDETTO: %s — caselle verdi %d/4, guardie eseguite %d"
          % ("✅" if verdi == 4 else "⛔", verdi, len(g)))
    return 0 if verdi == 4 else 1


if __name__ == "__main__":
    sys.exit(main())
