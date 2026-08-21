"""
CORE_AUTO — BATTERIA COMPLETA in un solo comando.  Uso:   python collaudi/batteria.py

Lancia, in sequenza e in modo autosufficiente (ZERO servizi cloud), tutta la difesa della macchina:
  1. Suite completa (unittest, ~348 file)          — copertura logica/funzionale E2E
  2. Master E2E totale (collaudo_finale_totale)     — flusso completo + concorrenza + manomissione
  2b. Cammino E2E preciso (percorso_e2e)            — bot cammina host+ospite+eccezioni, effetto passo-passo
  3. Mutazione (mutazione_prodotto)                 — i test VEDONO i guasti? (giudica i test)
  4. Caccia finti-verdi (caccia_finti_verdi)        — test che non possono fallire
  5. Plausibilità dati (plausibilita)               — i numeri hanno senso nel mondo vero
  6. BATTERIA ESTREMA (estremo)                     — chaos/fault-injection, crash, soak, fuzzing, time-travel
  6b. Gare + Fuzzing combinatorio (gare_estreme)    — race al ms (auditor I1 giudice) + fuzz endpoint, mai 500
  6c. Multi-vettore (multivettore)                  — idempotenza retry + concorrenza pannelli + tamper + finanza 0-cent
  6d. Stati impossibili (stati_impossibili)         — inietta orfani/soldi-senza-stanza, il guardiano li vede?
  6e. Caos (caos)                                   — SIGKILL vero + file descriptor + manomissione + deadlock/timeout
  7. Sicurezza statica (Bandit)                     — gate: 0 vulnerabilità High
  8. [server] Behavioral host + pannelli DAL VIVO   — avvia server locale, prova, chiude
  8b.[server] Vicoli ciechi                         — cammina link/form/API, nessun 404/rotta-morta
  8c.[server+chiave] BANCO DEI SOLDI                — 15 host, 15 prenotazioni che PAGANO
  9. [server+node] Accessibilità WCAG + click-through
 10. [internet] Verifica produzione (sito VERO)     — salta se offline
 11. I 5 documenti contro il motore · denominatore · piano dei soldi · tasti morti

⛔ LE FASI 2c, 5b, 5c, 8c e 11 SONO STATE AGGIUNTE IL 2026-08-21, e mancavano proprio quelle
sui soldi: il banco, le percentuali, gli incroci dell'ospite e i quattro guardiani dei
documenti. Un comando che si chiama «batteria COMPLETA» ed è incompleto è peggio di nessun
comando, perché chi lo lancia crede di aver guardato.

⛔ LA FASE 8c NON SI DICHIARA VERDE SENZA LA CHIAVE. Serve `STRIPE_SECRET_KEY` di PROVA
(`sk_test_...`): senza, il motore rifiuta ogni pagamento — fail-safe giusto — e il giro
misurerebbe la configurazione del banco invece del prodotto. In quel caso la fase è NON
ESEGUITA col motivo scritto, mai un OK (sbaglio S7).
   Uso con la chiave:  STRIPE_SECRET_KEY=sk_test_... python collaudi/batteria.py

Ogni fase è isolata: se una fallisce, le altre proseguono; alla fine un RIEPILOGO + exit-code.
Le fasi 8-10 sono BEST-EFFORT (saltate con nota se manca server/node/rete). Extra:
  python collaudi/estremo.py --ore 48   → soak di durata reale (24-48h).
"""
import importlib.util
import io
import os
import socket
import subprocess
import sys
import tempfile
import time

try:                                                 # console Windows (cp1252): evita crash su UTF-8
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
PORTA = 8099


def _run(cmd, timeout=1800, env=None):
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=RADICE, capture_output=True, text=True,
                           timeout=timeout, env=env, encoding="utf-8", errors="replace")
        return p.returncode, (p.stdout or "") + (p.stderr or ""), time.time() - t0
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT", time.time() - t0
    except Exception as e:
        return 125, "ERRORE LANCIO: %r" % e, time.time() - t0


def _rete_mutazione(traccia=None):
    """Se il giro di mutazione e' stato INTERROTTO, rimette a posto la produzione e LO DICE.

    ⛔ NASCE DA UN DANNO VERO, IL 2026-08-21. La fase 3 ha sforato il tetto di 900s ed e'
    stata **uccisa**: `subprocess.run` ammazza il processo, e il `finally` del Giudice
    protegge da un'eccezione, non da un processo ucciso. Sul disco e' rimasto, dentro il
    motore dei soldi:
        fase111_cancellazione.py:  rimborso = pagato      <- il 100% a chiunque, sempre
    Le QUINDICI fasi successive hanno girato su quel codice: due sono uscite rosse e per
    un'ora sono sembrate difetti veri. E il guasto e' rimasto li', dove chiunque poteva
    committarlo.

    💡 LA RETE C'ERA GIA', E AVEVA DUE STRATI -- il Giudice ripristina all'AVVIO SUCCESSIVO,
    e `guardia_commit.py` BLOCCA il commit. Mancava quello DI MEZZO: fra il colpo e il
    riavvio non rimette a posto nessuno. Questo e' l'anello mancante, e non sostituisce gli
    altri due: li completa.

    ⚠️ NON alza il tetto. Un tetto che si alza per far smettere il rosso e' un allarme
    spento (ferrea 10): il tetto resta, e l'interruzione smette di fare danno.

    `traccia` serve ai collaudi per puntare la rete su una cartella usa-e-getta.
    Torna i NOMI dei file rimessi a posto; lista vuota = non c'era niente da fare.
    """
    percorso = os.path.join(RADICE, "collaudi", "mutazione_prodotto.py")
    spec = importlib.util.spec_from_file_location("_mutazione_rete", percorso)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    if traccia:
        modulo._TRACCIA = traccia
    nomi = []
    for _cartella, quale, _originale in modulo.biglietti_aperti(traccia):
        try:
            with io.open(quale, encoding="utf-8") as f:
                nomi.append(os.path.basename(f.read().strip()) or "(non indicato)")
        except OSError:
            nomi.append("(non indicato)")
    if not nomi:
        return []
    modulo.recupera_da_interruzione()
    return nomi


def _coda(testo, n=3):
    righe = [r for r in testo.splitlines() if r.strip()]
    return " | ".join(righe[-n:])[:300]


def _porta_su(porta, secondi=25):
    for _ in range(secondi):
        with socket.socket() as s:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", porta)) == 0:
                return True
        time.sleep(1)
    return False


def main():
    esiti = []                                       # (nome, ok, dettaglio, durata)

    def registra(nome, rc, out, dur, ok_se=lambda rc, out: rc == 0):
        ok = ok_se(rc, out)
        esiti.append((nome, ok, _coda(out), dur))
        print("  [%-4s] %-42s (%.0fs)" % ("OK" if ok else "FAIL", nome, dur))

    print("=" * 80)
    print("BATTERIA COMPLETA — tutto in locale, zero cloud")
    print("=" * 80)

    # 1-7: fasi pure-Python (nessun server)
    fasi = [
        ("1. Suite completa (unittest)", [PY, "-m", "unittest", "discover", "-s", ".",
                                          "-p", "test_*.py"], 2400, None),
        ("2. Master E2E totale", [PY, "collaudi/collaudo_finale_totale.py"], 600, None),
        ("2b. Cammino E2E preciso", [PY, "collaudi/percorso_e2e.py"], 300, None),
        ("3. Mutazione", [PY, "collaudi/mutazione_prodotto.py"], 900, None),
        ("4. Caccia finti-verdi", [PY, "collaudi/caccia_finti_verdi.py"], 300, None),
        ("5. Plausibilità dati", [PY, "collaudi/plausibilita.py"], 300, None),
        ("6. Batteria ESTREMA", [PY, "collaudi/estremo.py"], 900, None),
        ("6b. Gare+Fuzzing combinatorio", [PY, "collaudi/gare_estreme.py"], 400, None),
        ("6c. Multi-vettore (rete+pannelli+tamper+finanza)", [PY, "collaudi/multivettore.py"], 700, None),
        ("6d. Stati impossibili (guardiano + transizioni)", [PY, "collaudi/stati_impossibili.py"], 300, None),
        ("6e. Caos (SIGKILL+fd+manomissione+deadlock)", [PY, "collaudi/caos.py"], 400, None),
        # ── AGGIUNTE IL 2026-08-21 ────────────────────────────────────────────────────
        # ⛔ NON ERANO QUI, E SONO PROPRIO QUELLE SUI SOLDI. Il fondatore ha chiesto che
        # OGNI lavoro passi da tutti i collaudi; cercando cosa esisteva gia' (D10) e'
        # venuto fuori che questo comando — quello che dice «tutto» — saltava il banco,
        # le percentuali, gli incroci dell'ospite e i quattro guardiani dei documenti.
        # Un elenco che dice «tutto» ed e' incompleto e' peggio di nessun elenco: chi lo
        # lancia crede di aver guardato.
        ("2c. Incroci dell'ospite (pagamento x conferma x politica x finestra)",
         [PY, "collaudi/incroci_ospite.py"], 300, None),
        ("5b. Coerenza delle percentuali in TUTTO il progetto",
         [PY, "collaudi/audit_coerenza_tariffe.py"], 300, None),
        ("5c. Rampa commissioni (differenziale + concorrenza + catena soldi)",
         [PY, "collaudi/collaudo_rampa_totale.py"], 600, None),
        ("11. I 5 documenti contro il motore (audit millimetrico)",
         [PY, "collaudi/audit_millimetrico.py"], 300, None),
        ("11b. Denominatore (rotte/pagine/email/lingue non attraversate)",
         [PY, "collaudi/denominatore.py"], 300, None),
        ("11c. Piano dei soldi (i tre posti dicono la stessa cosa)",
         [PY, "collaudi/piano_dei_soldi.py"], 300, None),
        ("11d. Copertura dei 3 pannelli (tasti morti)",
         [PY, "collaudi/coverage_pannelli.py"], 300, None),
    ]
    for nome, cmd, to, _ok in fasi:
        rc, out, dur = _run(cmd, timeout=to)
        registra(nome, rc, out, dur)
        # ⛔ SUBITO DOPO LA MUTAZIONE, NON A FINE GIRO. Se e' stata uccisa (tetto, Ctrl-C,
        # riavvio) ha lasciato un guasto DENTRO un file di produzione: senza questo, tutte
        # le fasi qui sotto giudicherebbero codice deliberatamente rotto -- successo il
        # 2026-08-21, e due fasi sono sembrate difetti veri per un'ora.
        if "Mutazione" in nome:
            rimessi = _rete_mutazione()
            if rimessi:
                print("  ⛔ LA MUTAZIONE E' STATA INTERROTTA e aveva lasciato %d file di "
                      "PRODUZIONE mutati: %s" % (len(rimessi), ", ".join(rimessi)))
                print("     Rimessi a posto ADESSO. Senza, tutto quello che gira qui sotto "
                      "giudicherebbe codice rotto -- e quel guasto poteva finire in un "
                      "commit. Il tetto NON e' stato alzato: guarda perche' ha sforato.")

    # 7: Bandit — gate su 0 High
    rc, out, dur = _run([PY, "-m", "bandit", "-r", ".", "-x",
                         "./collaudi,./_archivio,./test_", "-q"], timeout=600)
    def bandit_ok(rc, out):
        for r in out.splitlines():
            if "High:" in r:
                try:
                    return int(r.split("High:")[1].strip().split()[0]) == 0
                except Exception:
                    return False
        return False
    registra("7. Sicurezza statica (Bandit, High=0)", rc, out, dur, ok_se=bandit_ok)

    # 8-9: fasi che richiedono un server locale (best-effort)
    srv = None
    try:
        # ⛔ LA CARTELLA DEI DATI DEV'ESSERE LA STESSA PER I DUE PROCESSI, E DEV'ESSERE
        # NUOVA. Senza `BANCO_DATI` il server se ne sceglie una col nome a caso (`mkdtemp`) e
        # il banco -- che e' un altro processo -- non sa dove sia: `somma degli incassi`,
        # `tariffa tecnica`, `riga di rimborso`, `catena di impronte` e `payout trattenuto`
        # uscivano NON ESEGUITI a OGNI batteria. Dichiarati, quindi non un verde falso, ma
        # cinque controlli sui soldi che non girava mai nessuno. Misurato il 2026-08-21:
        # con la cartella condivisa i passi del banco vanno da 29 a 34.
        # ⛔ E NUOVA a ogni giro, non riusata: una cartella con dentro il giro precedente fa
        # morire l'avviatore con `KeyError: 'token'`.
        # Guardia: `test_pipeline_ci.test_LA_BATTERIA_DA_AL_SERVER_E_AL_BANCO_LA_STESSA_CARTELLA_DEI_DATI`
        env = dict(os.environ, BASE_VISIVO="http://127.0.0.1:%d" % PORTA,
                   BANCO_DATI=tempfile.mkdtemp(prefix="batteria_banco_"))
        srv = subprocess.Popen([PY, "collaudi/avvia_server_visivo.py", str(PORTA)],
                               cwd=RADICE, env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if _porta_su(PORTA):
            for nome, cmd in (("8. Behavioral host DAL VIVO", [PY, "collaudi/beh_host.py"]),
                              ("8. Behavioral pannelli DAL VIVO", [PY, "collaudi/beh_pannelli.py"]),
                              ("8b. Vicoli ciechi (link/form/API morti)", [PY, "collaudi/vicoli_ciechi.py"])):
                rc, out, dur = _run(cmd, timeout=400, env=env)
                registra(nome, rc, out, dur)

            # ── 8c. IL BANCO DEI SOLDI — aggiunto il 2026-08-21 ──────────────────────
            # ⛔ E QUI SI DICHIARA, NON SI DA' VERDE. Senza una chiave Stripe di PROVA il
            # motore rifiuta ogni pagamento (fail-safe giusto: «gateway giu' = non si
            # conferma niente»), il giro finisce «0 pagate» e misura la CONFIGURAZIONE del
            # banco invece del prodotto. Misurato il 2026-08-21: con la chiave di prova il
            # banco passa da «OK 19 / NON OK 15» a «OK 34 / NON OK 0», e i quattro controlli
            # contabili — che senza traffico non hanno nulla da leggere — trovano finalmente
            # 41 righe di libro giornale su cui pronunciarsi.
            # 💡 Percio' l'assenza della chiave e' un BUCO DICHIARATO, mai un OK: e' la
            # stessa lezione dei verdi per assenza riparati quel giorno (sbaglio S7).
            _chiave = os.environ.get("STRIPE_SECRET_KEY", "")
            if _chiave.startswith("sk_test"):
                # ⛔ `PYTHONPATH=RADICE` NON E' ORNAMENTO: senza, `python collaudi/giro_banco.py`
                # mette in cammino la cartella dello SCRIPT e muore al primo
                # `from fase163_accettazioni import ...` con ModuleNotFoundError, **prima di
                # esaminare un solo euro**. Misurato il 2026-08-21: la fase 8c e' fallita in
                # 0 secondi, e il rosso parlava della cartella invece che dei soldi. A mano il
                # banco si lancia su stdin (`python - < collaudi/giro_banco.py`), e li' il
                # cammino parte dalla cartella corrente: per questo il difetto si vedeva solo
                # da qui. E' D23 in forma pura — l'ambiente con cui lanci fa parte della misura.
                rc, out, dur = _run([PY, "collaudi/giro_banco.py"], timeout=900,
                                    env=dict(env, PYTHONPATH=RADICE))
                registra("8c. Banco dei soldi (15 host, 15 prenotazioni che PAGANO)",
                         rc, out, dur)
            else:
                esiti.append(("8c. Banco dei soldi", None,
                              "NON ESEGUITO: serve STRIPE_SECRET_KEY di PROVA (sk_test_...). "
                              "Senza, il motore rifiuta ogni pagamento e il giro misurerebbe "
                              "la configurazione del banco, non il prodotto", 0))
                print("  [~   ] 8c. Banco dei soldi (manca la chiave di PROVA: NON eseguito)")
            # 9: node (a11y + click-through) — solo se node c'è
            if _run(["node", "--version"], timeout=20)[0] == 0:
                # ⛔ Il percorso gira qui in ATTO «rifiuto», e non e' un ripiego: questo banco
                # ha una chiave Stripe FINTA, cioe' un gateway che non risponde, ed e'
                # esattamente la condizione in cui il prodotto DEVE rifiutare e all'host non
                # deve comparire niente («nessun voucher senza incasso»). L'atto «conferma»
                # vuole un banco SENZA chiave e sta nella CI (job `browser`), che ne accende
                # due: qui se ne accendesse un secondo si allungherebbe la batteria di ogni
                # giorno per provare una cosa gia' provata a ogni commit.
                for nome, cmd, extra in (
                        ("9. Accessibilità WCAG (axe)", ["node", "collaudi/test_a11y.js"], {}),
                        ("9. Click-through pannelli", ["node", "collaudi/clickthrough_pannelli.js"], {})):
                    rc, out, dur = _run(cmd, timeout=400, env=dict(env, **extra))
                    registra(nome, rc, out, dur, ok_se=lambda rc, o: rc == 0)

                # ── «SENZA INCASSO NON ESCE NIENTE» VUOLE UN GATEWAY MUTO ────────────────
                # ⛔ E QUESTA PROVA NON PUO' GIRARE SU UN BANCO CHE INCASSA. Il 2026-08-21,
                # lanciando la batteria CON la chiave di prova, e' andata in TIMEOUT dopo 400
                # secondi: aspettava un rifiuto che non poteva arrivare, perche' il gateway
                # era vivo e il pagamento riusciva. Il suo presupposto — «Stripe non risponde»
                # — l'avevo tolto io passando la chiave a tutta la batteria.
                # 💡 Percio' e' NON ESEGUITA col motivo, mai fallita: un rosso qui direbbe «il
                # prodotto conferma senza incassare», che e' l'esatto contrario del vero.
                # ⚠️ L'altro caso resta coperto: la CI (job `browser`) accende DUE banchi, uno
                # con chiave finta e uno senza, e prova tutt'e due gli atti a ogni commit.
                if _chiave.startswith("sk_test"):
                    esiti.append(("9. Senza incasso non esce niente", None,
                                  "NON ESEGUITA: il banco ha una chiave di PROVA vera, quindi "
                                  "il gateway RISPONDE e il pagamento riesce. Questa prova "
                                  "vuole il contrario (gateway muto): la copre la CI, job "
                                  "`browser`, che accende un banco senza chiave", 0))
                    print("  [~   ] 9. Senza incasso non esce niente "
                          "(gateway VIVO: la prova vuole il contrario)")
                else:
                    rc, out, dur = _run(["node", "collaudi/percorso_ospite_host.js"],
                                        timeout=400, env=dict(env, ATTESO="rifiuto"))
                    registra("9. Senza incasso non esce niente", rc, out, dur,
                             ok_se=lambda rc, o: rc == 0)
            else:
                esiti.append(("9. a11y+click-through", None, "SALTATO: node assente", 0))
                print("  [SKIP] 9. a11y + click-through (node assente)")
        else:
            esiti.append(("8-9. behavioral/a11y", None, "SALTATO: server locale non partito", 0))
            print("  [SKIP] 8-9. behavioral/a11y (server non partito)")
    finally:
        if srv is not None:
            try:
                srv.terminate()
            except Exception:
                pass

    # 10: verifica produzione (rete) — best-effort
    rc, out, dur = _run([PY, "collaudi/verifica_produzione.py"], timeout=180)
    if "VIOLAZIONI" in out or rc == 0:
        registra("10. Verifica produzione (sito vero)", rc, out, dur,
                 ok_se=lambda rc, o: "VIOLAZIONI: 0" in o)
    else:
        esiti.append(("10. Verifica produzione", None, "SALTATA: offline?", dur))
        print("  [SKIP] 10. Verifica produzione (offline?)")

    # riepilogo
    print("=" * 80)
    falliti = [e for e in esiti if e[1] is False]
    saltati = [e for e in esiti if e[1] is None]
    passati = [e for e in esiti if e[1] is True]
    print("RIEPILOGO: %d OK · %d FALLITI · %d saltati" % (len(passati), len(falliti), len(saltati)))
    for nome, ok, det, _ in falliti:
        print("   [X] %s -> %s" % (nome, det))
    for nome, ok, det, _ in saltati:
        print("   [~] %s (%s)" % (nome, det))
    print("=" * 80)
    print("VERDETTO: " + ("TUTTO VERDE" if not falliti else "%d FASI DA GUARDARE" % len(falliti)))
    sys.exit(1 if falliti else 0)


if __name__ == "__main__":
    main()
