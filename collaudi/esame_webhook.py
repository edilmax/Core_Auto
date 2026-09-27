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
  3. LE CASELLE 7 e 10 (2026-09-27, «la cosa giusta» e poi «autorizzato» del fondatore).
     La 7 e' stata RISCRITTA sulla guida di Stripe per la consegna dopo il Checkout (si
     consegna dentro la risposta; il perche' sta sopra la casella, in piano.py): si misura
     con la firma sul grezzo, il salvataggio prima, il NON-2xx su cio' che non e' salvato E
     su cio' che non e' applicato, e le guardie di quelle tre cose. La 10 si misura
     sull'ALBERO SINTATTICO del gestore, non cercando una parola nel testo (sbaglio S6: la
     ricerca di prima, `payment_status` ovunque in fase83, la soddisfaceva un commento): la
     rilettura e' chiamata dentro `_webhook_stripe` PRIMA della conferma, passa dalla
     `stato_sessione` del fornitore (fase85), e i tipi d'evento che confermano comprendono
     `async_payment_succeeded`; piu' la guardia `test_webhook_rilettura_stato`, eseguita.

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
GUARDIE = ("test_webhook_dedup_fatto", "test_sweep_eventi", "test_fase87_stripe_webhook",
           "test_webhook_evento_archiviato", "test_webhook_stripe_esiti_persi",
           "test_webhook_rilettura_stato")
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
    "la rilettura della casella 10 vale quando il sistema ha un fornitore Stripe: senza "
    "chiave non si creano link di pagamento (fase85 `crea_provider_stripe`) e la conferma "
    "resta quella di prima. Che in produzione il fornitore ci sia (`stripe(85)` fra i "
    "componenti dell'avvio) lo si legge dal registro del server al deploy, non da qui",
    "il TEMPO della consegna dentro la risposta (Checkout aspetta fino a 10 secondi) non si "
    "misura: il gestore fa fino a tre letture a Stripe, ognuna col suo timeout; oltre, "
    "Checkout manda comunque il cliente avanti e la conferma arriva un attimo dopo",
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
    # (e) CASELLA 7: cio' che non e' APPLICATO risponde NON-2xx (Stripe ritenta).
    fuori["non_2xx_se_non_applicato"] = bool(re.search(
        r"return 503, \{\"errore\": \"esito_non_applicato\"", server))
    # (f) CASELLA 10, sull'albero sintattico (codice che gira, non commenti): la rilettura
    # e' chiamata dentro `_webhook_stripe` PRIMA della conferma; passa dalla lettura del
    # fornitore; e gli eventi che confermano comprendono `async_payment_succeeded`.
    funzioni = {n.name: n for n in ast.walk(albero) if isinstance(n, ast.FunctionDef)}

    def _chiamate(funzione, nome):
        return sorted(c.lineno for c in ast.walk(funzione)
                      if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                      and c.func.attr == nome)
    gestore = funzioni.get("_webhook_stripe")
    lettura = funzioni.get("_stato_pagamento_da_stripe")
    riletture = _chiamate(gestore, "_stato_pagamento_da_stripe") if gestore else []
    conferme = _chiamate(gestore, "_conferma_pagamento") if gestore else []
    fuori["rilettura_prima_della_conferma"] = bool(
        riletture and conferme and riletture[0] < conferme[0])
    fuori["rilettura_dal_fornitore"] = bool(lettura and _chiamate(lettura, "stato_sessione"))
    fuori["evento_differito_gestito"] = bool(gestore) and any(
        isinstance(c, ast.Constant) and c.value == "checkout.session.async_payment_succeeded"
        for c in ast.walk(gestore))
    fornitore = ast.parse(testo_modulo("fase85_pagamenti_stripe.py"))
    fuori["fornitore_legge_payment_status"] = any(
        isinstance(f, ast.FunctionDef) and f.name == "stato_sessione"
        and any(isinstance(c, ast.Constant) and c.value == "payment_status"
                for c in ast.walk(f))
        for f in ast.walk(fornitore))
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

    # CAS. 7 (webhook), riscritta il 2026-09-27: firma sul grezzo, salvataggio prima della
    # risposta col NON-2xx se non salvato, NON-2xx se non applicato, guardie verdi.
    condizioni_web = {"firma sul corpo grezzo": fatti["firma_sul_grezzo"],
                      "salvataggio prima della risposta (NON-2xx se non salvato)":
                          fatti["salva_prima_della_risposta"],
                      "NON-2xx se non applicato": fatti["non_2xx_se_non_applicato"]}
    web_esito = all(condizioni_web.values()) and not rossi
    dedup_ok = (not rossi) and fatti["memoria_non_scade"]
    sweep_ok = fatti["sweep_esiste"] and not rossi
    web_motivo = ""
    if not web_esito:
        web_motivo = ("condizioni non vere: %s; guardie rosse: %s"
                      % (", ".join(k for k, v in condizioni_web.items() if not v) or "nessuna",
                         ", ".join(rossi) or "nessuna"))
    # CAS. 10 (rilettura): quattro fatti dell'albero sintattico e le guardie verdi.
    condizioni_ril = {"rilettura prima della conferma in _webhook_stripe":
                          fatti["rilettura_prima_della_conferma"],
                      "rilettura dalla stato_sessione del fornitore":
                          fatti["rilettura_dal_fornitore"],
                      "async_payment_succeeded fra gli eventi che confermano":
                          fatti["evento_differito_gestito"],
                      "fase85.stato_sessione legge payment_status":
                          fatti["fornitore_legge_payment_status"]}
    rilettura = all(condizioni_ril.values()) and not rossi
    rilettura_motivo = ""
    if not rilettura:
        rilettura_motivo = ("condizioni non vere: %s; guardie rosse: %s"
                            % (", ".join(k for k, v in condizioni_ril.items() if not v)
                               or "nessuna", ", ".join(rossi) or "nessuna"))

    esiti = {
        "webhook": (web_esito, len(condizioni_web) + n_guardie, web_motivo),
        "dedup": (dedup_ok, 2 + n_guardie,
                  "" if dedup_ok else "guardie rosse: %s" % ", ".join(rossi)),
        "sweep": (sweep_ok, 3 + n_guardie,
                  "" if sweep_ok else "guardie rosse o sweeper incompleto"),
        "rilettura": (rilettura, len(condizioni_ril) + n_guardie, rilettura_motivo),
    }
    return esiti, g, fatti


def _esegui(nome):
    flusso = io.StringIO()
    suite = unittest.TestLoader().loadTestsFromName(nome)
    return unittest.TextTestRunner(stream=flusso, verbosity=0).run(suite).wasSuccessful(), \
        flusso.getvalue()[-200:]


def autoprova():
    """D18 punto 2: con un guasto dentro, la guardia deve GRIDARE; a macchina sana deve
    TACERE. Due guasti, iniettati nel processo e tolti in un `finally` (nessun file
    toccato): la dedup spenta (il fatto non e' mai gia' visto) e la rilettura spenta (il
    gestore torna a credere all'evento: `_stato_pagamento_da_stripe` risponde «nessun
    fornitore»)."""
    import fase204_eventi_stripe as archivio_mod
    import fase83_server as server_mod
    prova_dedup = ("test_webhook_dedup_fatto.TestDedupPerFatto."
                   "test_due_eventi_diversi_per_lo_stesso_fatto_contano_UNO")
    prova_ril = ("test_webhook_rilettura_stato.TestLoStatoSiRileggeDallAPI."
                 "test_SESSIONE_CHIUSA_SENZA_SOLDI_NON_CONFERMA_LA_STANZA")
    vero = archivio_mod.ArchivioEventiStripe.fatto_gia_presente
    archivio_mod.ArchivioEventiStripe.fatto_gia_presente = lambda self, **k: False
    try:
        passa_dedup, dettaglio = _esegui(prova_dedup)
    finally:
        archivio_mod.ArchivioEventiStripe.fatto_gia_presente = vero
    vera_lettura = server_mod.RouterHTTP._stato_pagamento_da_stripe
    server_mod.RouterHTTP._stato_pagamento_da_stripe = lambda self, sessione: None
    try:
        passa_ril, dettaglio_ril = _esegui(prova_ril)
    finally:
        server_mod.RouterHTTP._stato_pagamento_da_stripe = vera_lettura
    grida = (not passa_dedup) and (not passa_ril)
    tace = _esegui(prova_dedup)[0] and _esegui(prova_ril)[0]
    return grida, tace, dettaglio + " | " + dettaglio_ril


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
    for nome, ok, rossi, _dettaglio in g:
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
        # Una casella rossa non e' un suo fallimento e non cambia qui il codice d'uscita.
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
