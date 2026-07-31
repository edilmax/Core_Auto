"""TEST DI MUTAZIONE SUL MOTORE — la prova piu' severa che esista sui test.

Tutti gli altri collaudi chiedono: *"il codice fa la cosa giusta?"*.
Questo chiede l'opposto, che e' la domanda che nessuno si fa: **"se il codice facesse
la cosa SBAGLIATA, i test se ne accorgerebbero?"**

Metodo (mutation testing, lo standard aureo della letteratura): si introduce di
proposito UN difetto realistico nel codice di produzione — un `>=` che diventa `>`,
una costante cambiata, un controllo di sicurezza saltato — e si eseguono i test che
dovrebbero proteggere quel punto. Se restano VERDI, quel mutante e' **sopravvissuto**:
significa che li' non c'e' nessuna rete di protezione, e un bug vero passerebbe uguale.

Le mutazioni NON sono casuali: sono i guasti che costerebbero davvero — soldi
addebitati male, consensi non verificati, firme non controllate, marche accettate a
torto. Ogni mutante e' accompagnato dal danno che provocherebbe nel mondo reale.

Due famiglie, perche' i modi di perdere sono due. I mutanti sui SOLDI (in cima)
chiedono «paghiamo/incassiamo la cifra giusta?». Quelli sulle GUARDIE DI SICUREZZA
(in fondo) chiedono «chi ENTRA e' davvero chi dice di essere?»: firme, cookie di
sessione, token operatore, password, rate-limit, consensi. Sono i guasti piu' insidiosi,
perche' col codice guasto il sito continua a funzionare benissimo — semplicemente, la
porta e' aperta. Il 2026-07-27 questa seconda famiglia ha trovato DUE buchi veri sul
token operatore admin (firma non provata, scadenza non provata): le guardie mancanti
sono ora in `test_admin_accounts.py`.

Il codice viene SEMPRE ripristinato, anche se qualcosa va storto.
"""
import importlib.util
import io
import os
import shutil
import subprocess
import sys

try:  # Windows: console cp1252 non regge box-drawing/emoji -> uscita UTF-8 tollerante
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)

# (file, testo originale, mutazione, test da eseguire, danno nel mondo reale)
def classifica_mutante(primo_giro_verde, riverifiche):
    """UCCISO · SOPRAVVISSUTO · INCERTO — e la terza categoria e' il punto.

    Prima c'erano solo due esiti, e chi moriva *a volte* finiva fra gli UCCISI ("era una
    flakiness del killer"). Ma un mutante visto solo a volte non dimostra che quel punto sia
    sorvegliato: dimostra che NON SI SA. Contarlo come ucciso gonfia il numero -- ed e' il
    numero che dovrebbe dirci la verita' sui test. Meglio un punteggio piu' basso e onesto.

    Non e' teorico: il 2026-07-30 un mutante e' sopravvissuto sulla CI ed e' stato ucciso in
    locale; l'avevamo archiviato come intoppo del runner. Con questa regola sarebbe rimasto
    IN SOSPESO -- che era la verita'.

      · primo giro ROSSO           -> UCCISO      (deterministico: i test lo vedono)
      · verde a TUTTI i giri       -> SOPRAVVISSUTO (buco reale, il job deve diventare rosso)
      · verde solo a volte         -> INCERTO     (ne' l'uno ne' l'altro: da guardare)
    """
    if not primo_giro_verde:
        return "ucciso"
    return "sopravvissuto" if all(riverifiche) else "incerto"


MUTANTI = [
    # ── I SOLDI ────────────────────────────────────────────────────────────────
    ("fase98_policy_commissione.py",
     "    if g < gg:",
     "    if g <= gg:",
     "test_fase98_policy_commissione test_promo_lancio test_promo_lancio_e2e",
     "un giorno in piu' di commissione 0%: ricavo regalato su ogni host"),

    ("fase98_policy_commissione.py",
     "fase1 = min(LANCIO_BPS_FASE1, regime)",
     "fase1 = regime",
     "test_fase98_policy_commissione test_promo_lancio test_trasparenza_costi",
     "l'host paga il 10% invece dell'8% nel secondo scaglione: addebito eccessivo"),

    ("fase81_bootstrap_casavip.py",
     "hid = catalogo.host_di_alloggio(slug)",
     "hid = None",
     "test_promo_lancio_e2e test_fase81_bootstrap_casavip",
     "la rampa salta: promo 0% mai applicata (E' IL BUG VERO DEL 2026-07-20)"),

    # ── LE PROVE LEGALI ────────────────────────────────────────────────────────
    ("fase163_accettazioni.py",
     "if riferimento:\n            canonico += \"|\" + str(riferimento)",
     "if False:\n            canonico += \"|\" + str(riferimento)",
     "test_identita_contratto test_fase163_accettazioni",
     "il legame con l'identita' esce dalla firma: manomissione non piu' rilevabile"),

    ("fase163_accettazioni.py",
     "        valida = hmac.compare_digest(atteso, firma)",
     "        valida = True",
     "test_fase163_accettazioni test_consensi_blindati test_identita_contratto",
     "ogni prova risulta integra anche se manomessa: il registro non prova piu' nulla"),

    # ── LA MARCA TEMPORALE ─────────────────────────────────────────────────────
    ("fase184_marca_temporale.py",
     "if impronta != impronta_attesa:               # ← il controllo che conta",
     "if False:                                     # ← mutato",
     "test_fase184_marca_temporale test_marca_qualificata test_qualifica_catena",
     "si accetta una marca che certifica UN ALTRO documento: prova senza valore"),

    ("fase184_marca_temporale.py",
     "        return _der_oid(OID_QTST_ETSI) in bytes(token or b\"\")",
     "        return True",
     "test_marca_qualificata test_qualifica_catena",
     "ogni marca risulta QUALIFICATA anche quando non lo e': dichiarazione falsa"),

    ("fase184_marca_temporale.py",
     "    if stato not in STATI_CONCESSI:",
     "    if False:",
     "test_fase184_marca_temporale",
     "si accetta una marca che l'Autorita' ha RIFIUTATO"),

    # ── I CONSENSI ─────────────────────────────────────────────────────────────
    ("fase83_server.py",
     "        if mancanti:\n            return 422",
     "        if False:\n            return 422",
     "test_consensi_blindati test_pannelli_contratto",
     "account creati senza contratto, clausole vessatorie o privacy accettati"),

    # ── LA PERSISTENZA ─────────────────────────────────────────────────────────
    ("main_casavip.py",
     "db_recensioni=os.environ.get(\"DB_RECENSIONI\", \"data/recensioni.db\"),",
     "",
     "test_avvio_main test_db_persistenti",
     "le recensioni tornano a vivere in RAM: perse a ogni riavvio (BUG VERO DI OGGI)"),

    # ── PAGA IN STRUTTURA (anticipo/saldo, fase188 + fase83) ─────────────────────
    ("fase188_paga_struttura.py",
     "GATEWAY_BPS = 325",
     "GATEWAY_BPS = 200",
     "test_paga_struttura_p0 test_paga_struttura",
     "la copertura carta non copre il 3,25% di Stripe extra-UE: si PERDE denaro su ogni carta straniera"),

    ("fase188_paga_struttura.py",
     "GATEWAY_FISSO_CENTS = 55",
     "GATEWAY_FISSO_CENTS = 25",
     "test_paga_struttura_p0",
     "sparisce il margine di sicurezza sopra il fisso Stripe (0,25): si perde sui piccoli addebiti"),

    ("fase83_server.py",
     "if corpo.get(\"modo_pagamento\") != \"in_struttura\":",
     "if corpo.get(\"modo_pagamento\") == \"in_struttura\":",
     "test_paga_struttura_e2e",
     "protezione soldi INVERTITA: l'online perde escrow+payout / l'in-struttura trattiene un saldo che non ha"),

    ("fase83_server.py",
     "if not self._rec_in_struttura(rec):",
     "if True:",
     "test_paga_struttura_e2e",
     "il webhook DUPLICATO in-struttura registra il TOTALE + la tassa come incasso nostro (soldi mai ricevuti)"),

    ("fase83_server.py",
     "if v.get(\"modo_pagamento\") == \"in_struttura\":",
     "if v.get(\"modo_pagamento\") == \"MAI\":",
     "test_paga_struttura_e2e",
     "cancellando un'in-struttura si rimborsa il PREZZO PIENO mai incassato online (solo l'anticipo e' passato da noi): perdita secca"),

    ("fase83_server.py",
     "if ore >= 24:",
     "if ore >= 99999:",
     "test_paga_struttura_e2e",
     "la penale (prima notte) scatta anche con >24h di preavviso: addebito indebito sulla carta del cliente"),

    ("fase83_server.py",
     "if ore >= 24:",
     "if ore > 24:",
     "test_paga_struttura_avanzato.TestConfine24hEsatto",
     "OFF-BY-ONE al confine: a ESATTAMENTE 24h di preavviso la penale scatta lo stesso (addebito indebito sulla carta salvata di chi ha disdetto in tempo)"),

    ("fase83_server.py",
     "penale = prezzo // notti",
     "penale = prezzo",
     "test_paga_struttura_avanzato",
     "la penale addebita il TOTALE del soggiorno invece della sola prima notte: addebito enormemente gonfiato"),

    # ── GATE STATO-PAGAMENTO del voucher (PIN/controversia mai prima del pagamento) ──────
    ("fase83_server.py",
     "    _pagato = bool(_rec_stato) and _rec_stato.get(\"stato\") == \"pagato\"",
     "    _pagato = True",
     "test_fase83_server test_email_ciclo",
     "il gate salta alla RADICE: ogni voucher trattato come PAGATO -> PIN check-in e controversia esposti su prenotazioni NON pagate (rompe entrambi i livelli, gate + guardia)"),

    ("fase83_server.py",
     "    if not _pagato:\n        # NON pagato: niente PIN, niente controversia",
     "    if False:\n        # NON pagato: niente PIN, niente controversia",
     "test_fase83_server test_email_ciclo",
     "i tasti controversia/garanzia e il check-in restano sul voucher non pagato: post-vendita esposto prima del pagamento"),

    # ── IL CALENDARIO (blocco atomico anti-overbooking, fase58) ──────────────────
    ("fase58_channel_manager.py",
     "                if row[\"unita_occupate\"] >= row[\"unita_totali\"]:\n                    motivo = \"pieno\"",
     "                if row[\"unita_occupate\"] > row[\"unita_totali\"]:\n                    motivo = \"pieno\"",
     "test_fase58_channel_manager",
     "OVERBOOKING di 1: l'ultima unita' si vende DUE volte (>= diventa >) -> due ospiti, una stanza"),

    ("fase58_channel_manager.py",
     "                if row[\"chiuso\"]:\n                    motivo = \"chiuso\"",
     "                if False:\n                    motivo = \"chiuso\"",
     "test_fase58_channel_manager",
     "una notte CHIUSA dall'host diventa prenotabile lo stesso: si vende una data bloccata"),

    ("fase58_channel_manager.py",
     "                if i == 0 and len(notti_list) < row[\"min_notti\"]:\n                    motivo = \"min_notti\"",
     "                if i == 0 and len(notti_list) < 0:\n                    motivo = \"min_notti\"",
     "test_fase58_channel_manager",
     "il soggiorno minimo (min_notti) non e' piu' imposto: si accettano soggiorni piu' corti del consentito"),

    # ── I PERMESSI (ruoli operatore admin, fase192) ──────────────────────────────
    ("fase192_admin_accounts.py",
     "        return str(azione) not in AZIONI_SOLO_ADMIN",
     "        return True",
     "test_admin_accounts",
     "il ruolo 'supporto' (assistenza) puo' muovere i SOLDI: rimborsi/storni da un account che non deve toccarli"),

    # ── L'ESCROW non paga l'host su prenotazione RIMBORSATA (fase160) ─────────────
    ("fase160_escrow_garanzia.py",
     "                            salta = bool(salta_se(rif))",
     "                            salta = False",
     "test_escrow_no_pay_rimborsata",
     "l'auto-rilascio paga l'host anche su prenotazione RIMBORSATA: perdita secca (rimborso ospite + bonifico host)"),

    # ── LA STANZA FANTASMA (inventario occupato senza prenotazione, fase58) ──────
    ("fase58_channel_manager.py",
     "                if r[\"idem_key\"] not in validi and r[\"check_in\"] and r[\"check_out\"]]",
     "                if r[\"idem_key\"] in validi and r[\"check_in\"] and r[\"check_out\"]]",
     "test_stanza_fantasma",
     "il filtro dei pendenti INVERTITO: si libererebbe la prenotazione LEGITTIMA e si terrebbe la fantasma"),

    # ══ LE GUARDIE DI SICUREZZA: firme, gate, permessi, anti-abuso ════════════════
    # I soldi hanno gia' i loro mutanti (sopra). Qui si attacca l'ALTRO lato: chi ENTRA.
    # Ogni mutazione qui e' un modo realistico in cui una porta resta aperta — e nessuno
    # se ne accorge, perche' il sito continua a funzionare benissimo. Sono i guasti che
    # non si vedono finche' non e' troppo tardi.

    # ── LA CHIAVE (confronto firma, rate-limit, input velenoso) ──────────────────
    ("fase83_server.py",
     "            return hmac.compare_digest(fornita.encode(\"utf-8\", \"surrogatepass\"), atteso.encode(\"utf-8\", \"surrogatepass\"))",
     "            return True",
     "test_fase201_partner test_auth_non_ascii",
     "il confronto della chiave diventa SEMPRE-VERO: ogni chiave admin/host e' accettata -> pannelli, dati e soldi aperti a chiunque"),

    ("fase83_server.py",
     "            return hmac.compare_digest(fornita.encode(\"utf-8\", \"surrogatepass\"), atteso.encode(\"utf-8\", \"surrogatepass\"))",
     "            return hmac.compare_digest(fornita.encode(\"utf-8\"), atteso.encode(\"utf-8\"))",
     "test_auth_non_ascii",
     "cade il 'surrogatepass': un surrogato Unicode isolato nella chiave fa esplodere l'auth -> 500 invece del 401 (rotta abbattibile a mano + oracolo per chi sonda)"),

    ("fase83_server.py",
     "        consentito, attesa = rl.consenti(chiave)\n        if not consentito:",
     "        consentito, attesa = rl.consenti(chiave)\n        if False:",
     "test_rate_limit_login",
     "il buttafuori per IP non blocca piu' nessuno: la chiave admin si prova a raffica all'infinito (brute-force senza freni)"),

    # ── IL GATE DELLE PAGINE (cookie di sessione firmato, fase83 gatekeeper) ─────
    ("fase83_server.py",
     "        if not _h.compare_digest(sig, atteso):\n            return False",
     "        if False:\n            return False",
     "test_gatekeeper",
     "il cookie di sessione-pagina non e' piu' verificato: basta scrivere 'admin|9999999999|x|deadbeef' nel browser per farsi servire la dashboard admin"),

    ("fase83_server.py",
     "        if livello != livello_atteso:\n            return False",
     "        if False:\n            return False",
     "test_gatekeeper",
     "il livello del cookie non conta piu': un cookie HOST valido apre la pagina ADMIN (scalata di privilegio da host ad amministratore)"),

    # ── IL TOKEN OPERATORE ADMIN (fase192 + fase83): e' una credenziale ──────────
    ("fase83_server.py",
     "            if not _h.compare_digest(atteso, str(sig)):\n                return None",
     "            if False:\n                return None",
     "test_admin_accounts",
     "token operatore FABBRICATO a mano: chi conosce l'email di un operatore entra come lui senza password (LACUNA VERA scoperta il 2026-07-27: sopravviveva, guardia aggiunta)"),

    ("fase83_server.py",
     "            if int(exp) < int(_t.time()):\n                return None",
     "            if False:\n                return None",
     "test_admin_accounts",
     "il token operatore non scade MAI: uno rubato una volta vale per sempre (LACUNA VERA scoperta il 2026-07-27: sopravviveva, guardia aggiunta)"),

    ("fase83_server.py",
     "            return aa.ruolo_attivo(d[\"email\"])",
     "            return d.get(\"ruolo\")  # mutato",
     "test_admin_accounts",
     "il ruolo non e' piu' riletto dal DB: revoca e declassamento perdono effetto -> un operatore licenziato resta dentro finche' il suo token non scade"),

    ("fase192_admin_accounts.py",
     "        if not hmac.compare_digest(atteso, calcolato):\n            return {\"ok\": False, \"errore\": \"credenziali_non_valide\"}",
     "        if False:\n            return {\"ok\": False, \"errore\": \"credenziali_non_valide\"}",
     "test_admin_accounts",
     "la password dell'operatore admin non e' piu' verificata: qualunque parola apre un account amministrativo"),

    # ── LA PASSWORD DELL'HOST (fase88): il pannello con annunci e incassi ────────
    ("fase88_registro_host.py",
     "        if not hmac.compare_digest(atteso, calcolato):\n            return EsitoHost(False, errore=\"credenziali_non_valide\")",
     "        if False:\n            return EsitoHost(False, errore=\"credenziali_non_valide\")",
     "test_fase88_registro_host",
     "qualunque password apre il pannello di QUALUNQUE host: annunci, calendario, dati e incassi di un altro"),

    # ── IL DEEP-LINK TELEGRAM FIRMATO (fase83) ──────────────────────────────────
    ("fase83_server.py",
     "        return hid if _h.compare_digest(sig, atteso) else None",
     "        return hid",
     "test_telegram_host",
     "il payload del deep-link non e' piu' firmato: chi indovina un host_id dirotta sul proprio telefono le notifiche di prenotazione di quell'host"),

    # ── IL KILL-SWITCH D'EMERGENZA (fase191) ────────────────────────────────────
    ("fase83_server.py",
     "        if self._transazioni_bloccate():           # kill-switch globale: niente nuove prenotazioni",
     "        if False:           # kill-switch globale: niente nuove prenotazioni",
     "test_blocco_globale",
     "il freno d'emergenza non ferma piu' le prenotazioni: durante un incidente si continua a incassare da clienti che non potremo servire"),

    # ── ANTI-ABUSO E GDPR DEL PROGRAMMA PARTNER (fase201) ───────────────────────
    ("fase201_partner.py",
     "        if consenso is not True:\n            return {\"errore\": \"consenso_richiesto\"}",
     "        if False:\n            return {\"errore\": \"consenso_richiesto\"}",
     "test_fase201_partner",
     "candidature partner archiviate SENZA consenso privacy: dato personale trattato senza base giuridica (violazione GDPR)"),

    ("fase201_partner.py",
     "                if recenti >= MAX_CANDIDATURE_ORA:",
     "                if False:",
     "test_fase201_partner",
     "cade il tetto orario: uno script riempie l'archivio partner a volonta' (flooding del DB)"),

    ("fase201_partner.py",
     "                            (em, n, tipo, _testo(citta, 80),",
     "                            (str(email), n, tipo, _testo(citta, 80),",
     "test_fase201_partner",
     "l'email non e' piu' normalizzata prima di scrivere: la stessa casella entra N volte cambiando le maiuscole (dedup aggirata, archivio sporco)"),
]


def invalida_bytecode(percorso):
    """Butta via la versione COMPILATA del file appena riscritto. Ritorna il .pyc rimosso.

    ⛔ SENZA QUESTA RIGA IL GIUDICE GIUDICA CODICE CHE NON STA GIRANDO.

    Python non ricompila un modulo se DIMENSIONE e DATA-AL-SECONDO della sorgente
    coincidono con quelle scritte nell'intestazione del suo `.pyc`. Quasi tutti i mutanti
    di questo elenco cambiano un OPERATORE — `!=` diventa `==`, `>=` diventa `>` — cioe'
    scrivono ESATTAMENTE LO STESSO NUMERO DI BYTE. Se la riscrittura cade nello stesso
    secondo della precedente, il processo figlio importa il `.pyc` di prima ed esegue il
    codice NON MUTATO: i test passano, e il motore conclude «mutante SOPRAVVISSUTO» per un
    guasto che non e' mai esistito. Falso allarme, cioe' un difetto (REGOLA FERREA 10) —
    e il gemello silenzioso e' peggio: un mutante «ucciso» che non e' mai stato provato.

    PROVATO il 2026-07-31, non dedotto, su un modulo usa-e-getta fuori dal progetto:
    scritto `SEGNO = '!='`, importato (nasce il .pyc), riscritto `SEGNO = '=='` (stessa
    dimensione, stesso secondo) -> un processo NUOVO stampava ancora `!=`. Cancellato il
    `.pyc`, lo stesso processo stampava `==`.
    Spiega anche la vecchia «instabilita' del job mutazione sulla CI» scritta piu' sotto:
    non era carico del runner, era un secondo di orologio.
    """
    pyc = importlib.util.cache_from_source(percorso)
    try:
        os.remove(pyc)
    except FileNotFoundError:
        pass                      # non c'era cache: e' gia' la condizione che vogliamo
    return pyc


def esegui(test_str, timeout=900):
    p = subprocess.run([sys.executable, "-m", "unittest"] + test_str.split(),
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    return p.returncode == 0, p.stdout.decode("utf-8", "replace")


if __name__ == "__main__":
    riserva = tempfile.mkdtemp(prefix="mutazione_")
    file_toccati = sorted({m[0] for m in MUTANTI})
    for f in file_toccati:
        shutil.copy(f, os.path.join(riserva, f.replace("/", "_")))

    print("=" * 90)
    print("TEST DI MUTAZIONE — se il motore facesse la cosa sbagliata, i test se ne")
    print("accorgerebbero? Un mutante SOPRAVVISSUTO e' un buco nella rete di protezione.")
    print("=" * 90)

    sopravvissuti, uccisi, non_applicabili, incerti = [], 0, [], []
    t0 = time.time()
    try:
        for i, (percorso, orig, mut, test, danno) in enumerate(MUTANTI, 1):
            testo = io.open(percorso, encoding="utf-8").read()
            if orig not in testo:
                non_applicabili.append("%s (testo non trovato)" % percorso)
                print("\n%2d. %-28s  ? testo non trovato: mutante non applicabile"
                      % (i, percorso))
                continue
            io.open(percorso, "w", encoding="utf-8", newline="\n").write(
                testo.replace(orig, mut, 1))
            invalida_bytecode(percorso)       # il figlio deve vedere IL GUASTO, non la cache
            try:
                verde, uscita = esegui(test)
            finally:
                io.open(percorso, "w", encoding="utf-8", newline="\n").write(testo)
                invalida_bytecode(percorso)   # ...e il mutante dopo non deve vedere QUESTA
            print("\n%2d. %s" % (i, percorso))
            print("    guasto introdotto: %s" % danno)
            if verde:
                # RI-VERIFICA prima di gridare "buco": un survivor puo' essere una FLAKINESS
                # transitoria del killer (subprocess sotto carico sul runner CI, oppure una rotta
                # a tempo che al primo giro non ha visto il mutante). Un buco VERO sopravvive in
                # modo DETERMINISTICO a OGNI giro; una flakiness muore appena il killer riprende.
                # Rigiro il killer fino a 2 volte IN PIU' (3 totali sul codice MUTATO): se ANCHE
                # UNA sola volta lo uccide -> era flaky, ucciso. Solo se regge a TUTTI e 3 e' un
                # buco reale. Cosi' non si maschera un gap (sopravvive comunque) ne' si fa rosso
                # il job per un intoppo passeggero (falso-survivor ~ p^3 invece di p^2). Storia:
                # il job MUTAZIONE flakava a intermittenza sul CI (locale sempre 18/18), passando
                # al re-run -> classica flakiness transitoria da carico del runner.
                # SPAZIATE: se il picco e' un transitorio di CARICO del runner (subprocess lenti),
                # 3 giri back-to-back cadono tutti nella stessa finestra; una piccola pausa la lascia
                # dissolvere. Un buco VERO resta comunque (e' deterministico), un intoppo di carico no.
                riverifiche = []
                for _ in range(2):
                    time.sleep(2)
                    riverifiche.append(esegui(test)[0])
                esito = classifica_mutante(True, riverifiche)
                if esito == "sopravvissuto":
                    sopravvissuti.append((percorso, danno, test))
                    print("    ESITO: MUTANTE SOPRAVVISSUTO — i test restano VERDI (3 giri su 3)!")
                else:
                    incerti.append((percorso, danno, test))
                    print("    ESITO: INCERTO — visto solo a volte (%d giri su 3 lo hanno mancato)."
                          "\n           NON conta come ucciso: quel punto NON e' sorvegliato in "
                          "modo affidabile." % (1 + sum(1 for x in riverifiche if x)))
            else:
                uccisi += 1
                riga = [r for r in uscita.splitlines()
                        if r.startswith("FAILED") or r.startswith("Ran ")]
                print("    ESITO: ucciso dai test  (%s)" % " ".join(riga[-2:])[:70])
    finally:
        for f in file_toccati:
            shutil.copy(os.path.join(riserva, f.replace("/", "_")), f)
            invalida_bytecode(f)              # l'albero torna sano anche per chi importa dopo
        shutil.rmtree(riserva, ignore_errors=True)

    provati = len(MUTANTI) - len(non_applicabili)
    print("\n" + "=" * 90)
    print("MUTANTI PROVATI: %d  |  UCCISI: %d  |  SOPRAVVISSUTI: %d  |  INCERTI: %d  |  %.1f minuti"
          % (provati, uccisi, len(sopravvissuti), len(incerti), (time.time() - t0) / 60.0))
    if non_applicabili:
        print("non applicabili (il codice e' cambiato): %s" % ", ".join(non_applicabili))
    if incerti:
        # NON fanno rosso il job (un intoppo del runner non deve bloccare la produzione) ma
        # non sono nemmeno UCCISI: quel punto non e' sorvegliato in modo affidabile e va
        # guardato a mano. Il numero degli uccisi resta cosi' ONESTO.
        print("\nPUNTI NON SORVEGLIATI IN MODO AFFIDABILE (visti solo a volte — NON contano"
              " come uccisi):")
        for percorso, danno, test in incerti:
            print("  ? %s" % percorso)
            print("    danno che a volte passa: %s" % danno)
            print("    test che dovrebbero vederlo SEMPRE: %s" % test)
            # Avviso, non errore: gli incerti NON fanno rosso il job (un intoppo del
            # runner non deve bloccare la produzione). Ma devono essere VISIBILI a chi
            # non ha i diritti per scaricare il registro, altrimenti «non conta come
            # ucciso» resta una frase che nessuno legge mai.
            print("::warning title=Mutante INCERTO in %s::%s | visto solo a volte dai "
                  "test: %s" % (percorso, danno, test))
    if sopravvissuti:
        print("\nBUCHI NELLA RETE DI PROTEZIONE:")
        for percorso, danno, test in sopravvissuti:
            print("  X %s" % percorso)
            print("    danno che passerebbe: %s" % danno)
            print("    test che avrebbero dovuto vederlo: %s" % test)
            # L'ESITO DEVE ESSERE LEGGIBILE DA FUORI. Il registro del job lo scarica solo
            # chi ha diritti di AMMINISTRATORE sul repository: per tutti gli altri un job
            # mutazione rosso dice soltanto «exit code 1», che non e' un'informazione. Le
            # annotazioni invece sono pubbliche. Senza questa riga il buco resta scritto
            # in un posto dove quasi nessuno puo' guardare -- osservabile debole, cioe' un
            # difetto (REGOLA FERREA 9). Provato il 2026-07-31 sul job 91155447837:
            # l'unica cosa leggibile era «Process completed with exit code 1».
            print("::error title=Mutante SOPRAVVISSUTO in %s::%s | test che avrebbero "
                  "dovuto vederlo: %s" % (percorso, danno, test))
        sys.exit(1)
    print("\nNESSUN MUTANTE SOPRAVVISSUTO: ogni guasto simulato viene visto dai test.")
    sys.exit(0)
