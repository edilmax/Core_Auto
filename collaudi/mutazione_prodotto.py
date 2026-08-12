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
import ast
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

    # ── LA TASSA DI SOGGIORNO (fase66) — i tre guasti VERI del 2026-08-12 ──────
    # Non mutanti immaginati: sono esattamente i tre difetti trovati e riparati quel
    # giorno, rimessi qui perche' se tornano il Giudice li deve vedere in CI.
    ("fase66_tassa_soggiorno.py",
     "    if _regola_malformata(regola):",
     "    if False:",
     "test_fase66_tassa_soggiorno",
     "una regola malformata (cap notti -1) torna a valere come «nessun cap»: "
     "l'ospite paga 210,00 EUR invece di 49,00 per lo stesso soggiorno"),

    ("fase66_tassa_soggiorno.py",
     "        return CalcoloTassa(0, 0, 0, notti_tass, ospiti_tass, regola.valuta)",
     "        return CalcoloTassa(MAX_CENTS, fissa, perc, notti_tass, ospiti_tass, regola.valuta)",
     "test_fase66_tassa_soggiorno",
     "la cintura anti-abuso torna a tagliare il totale lasciando intatte le componenti: "
     "tassa != fissa + percentuale e la riconciliazione non torna piu'"),

    ("fase66_tassa_soggiorno.py",
     "            if ppn < 0 or perc < 0 or (maxn is not None and maxn < 0):",
     "            if False:",
     "test_fase66_tassa_soggiorno",
     "una riga di configurazione con un meno di troppo torna a essere «aggiustata» "
     "invece che scartata: la citta' perde il tetto notti e l'ospite paga di piu'"),

    ("fase57_vetrina.py",
     "        if not (_intero(_v) and 0 <= _v <= _tetto):",
     "        if False:",
     "test_tassa_pre_acquisto test_fase66_tassa_soggiorno",
     "i valori di tassa/sconto tornano a essere AZZERATI invece che rifiutati: e lo zero, "
     "per `tassa_max_notti`, significa NESSUN TETTO -> l'ospite paga la tassa su tutte le "
     "notti per un refuso dell'host, e `pubblica` risponde 201 senza avvisare nessuno"),

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


# ═══════════════════════════════════════════════════════════════════════════════
#  GENERATORE DI MUTANTI — dal CODICE, non da un elenco scritto a mano
# ═══════════════════════════════════════════════════════════════════════════════
#  PERCHE'. I 41 mutanti qui sopra sono scelti col cervello e restano: valgono. Ma li ha
#  scritti la stessa testa che ha scritto i test, quindi confermano i guasti gia' immaginati
#  e non ne scoprono di nuovi. E toccano 12 moduli su 152: il 92% del motore non ha mai visto
#  un guasto simulato. Un elenco curato a mano non scala e non sorprende.
#
#  COSA FA. Legge un file di produzione con `ast` e propone le mutazioni nei punti dove
#  vivono i difetti di logica veri. Ogni mutante conosce la sua RIGA, cosi' si puo' applicare
#  il generatore SOLO alle righe che un commit ha toccato: il numero resta piccolo, il giro
#  veloce, e la domanda diventa quella giusta — «la riga che ho appena scritto, se fosse
#  sbagliata, se ne accorgerebbe qualcuno?».
#
#  COSA NON FA (confini dichiarati, per non spacciare copertura che non c'e'):
#   · niente aritmetica (`+`→`-`): su un importo produce troppi mutanti EQUIVALENTI, cioe'
#     rumore che insegna a ignorare l'esito;
#   · niente operatori a cavallo di due righe: l'operatore si taglia al carattere esatto,
#     e se non e' sulla stessa riga dei suoi due operandi si SALTA invece di indovinare;
#   · niente confronti a catena (`a == b == c`): stessa ragione.
#  Quello che salta viene CONTATO e dichiarato, mai nascosto.

_CONFRONTI = {
    "Eq":    ("==", "!=", "un uguale diventa un diverso: la condizione si rovescia"),
    "NotEq": ("!=", "==", "un diverso diventa un uguale: la condizione si rovescia"),
    "Lt":    ("<", "<=", "un minore stretto include il confine: errore di un passo"),
    "LtE":   ("<=", "<", "un minore-o-uguale esclude il confine: errore di un passo"),
    "Gt":    (">", ">=", "un maggiore stretto include il confine: errore di un passo"),
    "GtE":   (">=", ">", "un maggiore-o-uguale esclude il confine: errore di un passo"),
    # ── INSEGNATI AL GIUDICE IL 2026-08-05 ──────────────────────────────────────────────
    # Erano 1290 punti in tutta la macchina che lo strumento dichiarava di non saper
    # rompere: un cancello come `if r["stato"] not in ("in_attesa","scaduto")` -- quello che
    # decide se un pagamento puo' essere scritto -- non era mai stato messo alla prova.
    # Si parte da questi quattro perche' il guasto e' UNIVOCO: non c'e' da scegliere quale
    # carattere tagliare, come invece succede nelle catene (`0 < x <= 5`).
    # ⛔ La rete che rende sicura questa estensione e' `test_pipeline_ci.
    # TestGeneratoreDiMutanti.test_OGNI_MUTANTE_GENERATO_COMPILA`: un taglio sbagliato
    # produce un mutante che non compila, il killer muore di errore di sintassi e il giudice
    # lo conta UCCISO -- punteggio pieno su protezione assente.
    "Is":    ("is", "is not", "un «e' proprio quello» diventa «e' un altro»: il ramo si rovescia"),
    "IsNot": ("is not", "is", "un «e' un altro» diventa «e' proprio quello»: il ramo si rovescia"),
    "In":    ("in", "not in", "un «e' nell'elenco» diventa «non c'e'»: il cancello si rovescia"),
    "NotIn": ("not in", "in", "un «non c'e' nell'elenco» diventa «c'e'»: il cancello si rovescia"),
}


def _taglia_operatore(righe, r_dopo, c_dopo, r_prima, c_prima, simbolo):
    """Posizione ESATTA di un operatore fra i suoi due operandi, o None se non e' sulla
    stessa riga (a cavallo si salta: meglio niente che una sostituzione indovinata)."""
    if r_dopo != r_prima or r_dopo < 1 or r_dopo > len(righe):
        return None
    testo = righe[r_dopo - 1]
    if c_prima > len(testo) or c_dopo > c_prima:
        return None
    i = testo[c_dopo:c_prima].find(simbolo)
    if i < 0:
        return None
    return r_dopo, c_dopo + i, c_dopo + i + len(simbolo)


def genera_mutanti(sorgente, righe_ammesse=None):
    """I mutanti proponibili per questo sorgente. Funzione PURA: non tocca il disco.

    `righe_ammesse`: se dato, si generano SOLO i mutanti sulle righe indicate (il diff).
    Ritorna una lista di dizionari con riga, taglio esatto, testo nuovo, tipo e danno;
    l'ultima voce, `saltati`, dice quanti punti sono stati riconosciuti ma non mutati e
    perche' — un generatore che tace sulle proprie rinunce e' un generatore che mente.
    """
    albero = ast.parse(sorgente)
    righe = sorgente.splitlines()
    ammesse = set(righe_ammesse) if righe_ammesse is not None else None
    mutanti, saltati = [], {"a_cavallo": 0, "catena": 0, "non_trovato": 0,
                            "operatore_ignoto": 0}

    def _rinuncia(riga, categoria, quante=1):
        """⛔ UNA RINUNCIA SI CONTA SOLO SE RIGUARDA UNA RIGA CHE STIAMO ESAMINANDO.
        In modo `--diff` si generano mutanti solo sulle righe cambiate: dichiarare le rinunce
        di TUTTO il file farebbe accendere la riga «NON PROVATI (dichiarati)» a ogni singolo
        giro (452 punti di rumore fisso su `fase83_server.py`), e un allarme sempre acceso
        viene spento -- che e' un difetto quanto un allarme mancato (regola ferrea 10).
        Trovato il 2026-08-05 da una revisione a contesto fresco."""
        if ammesse is not None and riga not in ammesse:
            return
        saltati[categoria] += quante

    def _aggiungi(nodo_riga, taglio, nuovo, tipo, danno):
        if taglio is None:
            _rinuncia(nodo_riga, "non_trovato")
            return
        r, ci, cf = taglio
        if ammesse is not None and r not in ammesse:
            return
        mutanti.append({"riga": r, "col_inizio": ci, "col_fine": cf, "nuovo": nuovo,
                        "vecchio": righe[r - 1][ci:cf], "tipo": tipo, "danno": danno})

    for nodo in ast.walk(albero):
        if isinstance(nodo, ast.Compare):
            if len(nodo.ops) != 1:
                # ⛔ SI CONTA PER OPERATORE, NON PER NODO. `0 < limite <= 500` e' UN nodo ma
                # DUE punti mutabili, e contarlo come una rinuncia sola faceva uscire un
                # denominatore corto: 44 moduli su 152, 109 punti in tutta la macchina.
                # Scoperto il 2026-08-05 da una revisione a contesto fresco, dopo che avevo
                # scritto nel diario che 43 era «il denominatore vero di fase160»: erano 46.
                # Il conteggio a mano del 2026-08-04 diceva 43 anche lui -- due misure
                # d'accordo fra loro ed entrambe sbagliate. Ora c'e' un oracolo indipendente
                # che le confronta: `test_pipeline_ci.TestGeneratoreDiMutanti.
                # test_IL_DENOMINATORE_DICHIARATO_COINCIDE_CON_UN_ORACOLO_INDIPENDENTE`.
                _rinuncia(nodo.lineno, "catena", len(nodo.ops))
                continue
            nome = type(nodo.ops[0]).__name__
            if nome not in _CONFRONTI:
                # ⛔ `is`, `is not`, `in`, `not in`: il generatore non li sa rompere, ed e' una
                # rinuncia legittima -- ma va CONTATA. Prima si saltavano in silenzio, e il
                # denominatore usciva piu' piccolo del vero: su `fase160` erano 43 punti e ne
                # dichiarava 39. Fra i quattro muti c'era `r["stato"] not in attesi`, la sola
                # condizione che decide se un movimento di denaro e' permesso. Un punto che lo
                # strumento non esamina non e' un punto sicuro: e' un punto che nessuno ha mai
                # guardato, e tacerlo lo fa sembrare coperto (D18 punto 3).
                _rinuncia(nodo.lineno, "operatore_ignoto")
                continue
            simbolo, sostituto, danno = _CONFRONTI[nome]
            taglio = _taglia_operatore(righe, nodo.left.end_lineno, nodo.left.end_col_offset,
                                       nodo.comparators[0].lineno,
                                       nodo.comparators[0].col_offset, simbolo)
            if taglio is None and nodo.left.end_lineno != nodo.comparators[0].lineno:
                _rinuncia(nodo.lineno, "a_cavallo")
                continue
            _aggiungi(nodo.lineno, taglio, sostituto, "confronto", danno)

        elif isinstance(nodo, ast.BoolOp):
            simbolo = "and" if isinstance(nodo.op, ast.And) else "or"
            sostituto = "or" if simbolo == "and" else "and"
            danno = ("una condizione che doveva valere INSIEME ora basta da sola"
                     if simbolo == "and" else
                     "una condizione che bastava da sola ora deve valere INSIEME")
            for a, b in zip(nodo.values, nodo.values[1:]):
                taglio = _taglia_operatore(righe, a.end_lineno, a.end_col_offset,
                                           b.lineno, b.col_offset, simbolo)
                if taglio is None and a.end_lineno != b.lineno:
                    _rinuncia(nodo.lineno, "a_cavallo")
                    continue
                _aggiungi(nodo.lineno, taglio, sostituto, "booleano", danno)

        elif isinstance(nodo, ast.Constant) and nodo.value in (True, False) \
                and isinstance(nodo.value, bool):
            testo = "True" if nodo.value else "False"
            if nodo.lineno != nodo.end_lineno:
                _rinuncia(nodo.lineno, "a_cavallo")
                continue
            riga = righe[nodo.lineno - 1] if nodo.lineno <= len(righe) else ""
            if riga[nodo.col_offset:nodo.end_col_offset] != testo:
                _rinuncia(nodo.lineno, "non_trovato")
                continue
            _aggiungi(nodo.lineno, (nodo.lineno, nodo.col_offset, nodo.end_col_offset),
                      "False" if nodo.value else "True", "costante",
                      "un interruttore acceso si spegne (o viceversa)")

    mutanti.sort(key=lambda m: (m["riga"], m["col_inizio"]))
    return mutanti, saltati


def applica_mutante(sorgente, mutante):
    """Il sorgente con QUEL mutante dentro. Taglio al carattere: nessun `replace` cieco,
    che su una riga con due operatori uguali colpirebbe quello sbagliato."""
    righe = sorgente.splitlines(True)
    i = mutante["riga"] - 1
    riga = righe[i]
    fine = riga[mutante["col_fine"]:]
    righe[i] = riga[:mutante["col_inizio"]] + mutante["nuovo"] + fine
    return "".join(righe)


def righe_toccate(base="HEAD~1"):
    """I file di PRODUZIONE cambiati e le righe nuove, letti da git. {file: {righe}}."""
    r = subprocess.run(["git", "diff", "-U0", base, "--", "*.py"],
                       capture_output=True, cwd=REPO)
    if r.returncode != 0:
        raise RuntimeError("git diff fallito su %r: %s"
                           % (base, r.stderr.decode("utf-8", "replace")[:200]))
    fuori = ("test_", "collaudi/", "_archivio/")
    toccate, corrente = {}, None
    for riga in r.stdout.decode("utf-8", "replace").splitlines():
        if riga.startswith("+++ b/"):
            nome = riga[6:]
            base_nome = os.path.basename(nome)
            corrente = None if (base_nome.startswith(fuori[0])
                                or nome.startswith(fuori[1:])) else nome
        elif riga.startswith("@@") and corrente:
            pezzo = riga.split("+")[1].split("@@")[0].strip()
            inizio, _, quante = pezzo.partition(",")
            n = int(quante or 1)
            if n:
                toccate.setdefault(corrente, set()).update(
                    range(int(inizio), int(inizio) + n))
    return {f: r for f, r in toccate.items() if r and os.path.exists(os.path.join(REPO, f))}


def test_che_nominano(percorso):
    """I file di test che NOMINANO quel modulo: gli unici che possono vederne il guasto.

    Se l'elenco e' VUOTO non serve nemmeno provare: quel codice non e' sorvegliato da
    nessuno, ed e' un esito -- non un errore da nascondere.
    """
    modulo = os.path.basename(percorso)[:-3]
    trovati = []
    for nome in sorted(os.listdir(REPO)):
        if not (nome.startswith("test_") and nome.endswith(".py")):
            continue
        try:
            with io.open(os.path.join(REPO, nome), encoding="utf-8", errors="replace") as f:
                if modulo in f.read():
                    trovati.append(nome[:-3])
        except OSError:
            continue
    return trovati


# ── MUTANTI EQUIVALENTI, DICHIARATI CON LA PROVA ────────────────────────────────
#  Un mutante EQUIVALENTE non e' un buco: e' una mutazione che NON cambia il comportamento,
#  quindi nessun test potrebbe ucciderlo. Segnalarlo per sempre insegna a ignorare gli
#  allarmi del generatore -- il danno peggiore (REGOLA FERREA 10).
#  ⚠️ Questo elenco e' l'unico posto dove un sopravvissuto puo' essere «perdonato», quindi
#  ogni voce porta la PROVA di equivalenza, non un'opinione. La chiave e' il TESTO della
#  riga, non il numero: cosi' resta valida se il codice si sposta, e smette di valere --
#  giustamente -- se quella riga cambia.
# ⛔ LA CHIAVE PORTA ANCHE LA FUNZIONE (dal 2026-08-01): file · FUNZIONE · testo della riga ·
#    vecchio · nuovo. Senza il nome della funzione, una dichiarazione si estendeva a TUTTE le
#    righe identiche del file: in `fase177` la riga `if residuo <= 0:` compare in due funzioni
#    diverse, e dichiararne una avrebbe reso cieca anche l'altra. Una dichiarazione vale SOLO
#    dove e' stata dimostrata.
# ⛔ IL VALORE E' A CAMPI, NON PROSA (dal 2026-08-05). Quattro campi obbligatori:
#      metodo   uno di: "z3" | "esaustiva" | "traccia". Insieme CHIUSO: «non e' raggiungibile»
#               e «non e' osservabile» NON sono metodi di dimostrazione (divieto B6, D19).
#      dominio  su COSA e' stata fatta la prova. E' il campo che ha reso visibile la forma
#               comune delle tre voci false: una prova fatta su un dominio PIU' PICCOLO di
#               quello che la firma della funzione accetta (`v` senza tipo, `v: Any`).
#               Una dimostrazione formale vale quanto il modello su cui e' fatta.
#      data     AAAA-MM-GG. Serve a sapere se la prova e' piu' vecchia del codice.
#      prova    il testo della dimostrazione, invariato. E' l'unico campo che esce da
#               `_e_equivalente`, perche' i consumatori lo tagliano.
#    Sotto guardia in `test_pipeline_ci.py`, classi `TestLoSchedarioDegliEquivalenti_*`:
#    ancoraggio al sorgente vivo, presenza dei campi, e dominio >= firma. Chi aggiunge una
#    voce senza campi diventa rosso lo stesso giorno (D18 punto 4).
EQUIVALENTI_DICHIARATI = {
    ("fase184_marca_temporale.py", "_der_intero", "if valore < 0:", "<", "<="): {
        "metodo": "esaustiva",
        "dominio": "tutti gli interi. La firma e' `_der_intero(valore: int)`: nessun "
                   "argomento senza tipo, quindi il dominio della prova coincide con "
                   "quello che la funzione accetta.",
        "data": "2026-08-04",
        "prova":
            "DIMOSTRATO PER ESAURIMENTO il 2026-08-04, non dedotto. `<` e `<=` sugli interi "
            "differiscono in UN SOLO punto: valore == 0. E lo zero non puo' arrivare a questa "
            "riga, perche' la riga IMMEDIATAMENTE PRECEDENTE nella stessa funzione fa "
            "`if valore == 0: return _der(0x02, b'\\x00')` -- un return incondizionato. Quindi "
            "a questa riga vale sempre valore != 0, e sull'intero dominio residuo le due "
            "condizioni coincidono. Nessun ingresso puo' distinguerle: non c'e' niente da "
            "distinguere. "
            "⚠️ NON e' un «oggi non si raggiunge» alla D19: quello e' vietato perche' la "
            "premessa sta in un'ALTRA funzione e puo' cadere senza che nessuno se ne accorga. "
            "Qui la premessa e' la riga sopra, nella stessa funzione, ed e' gia' inchiodata da "
            "una guardia esistente: `test_fase184_marca_temporale.TestDER."
            "test_intero_zero_e_piccoli` pretende che `_der_intero(0)` valga b'\\x02\\x01\\x00'. "
            "Se qualcuno togliesse quel return, quella guardia diventerebbe rossa lo stesso "
            "giorno e questa dichiarazione andrebbe rifatta.",
    },
    ("fase199_invarianti.py", "dimostra_formalmente",
     "mx = z3.If(a1 > b1, a1, b1)", ">", ">="): {
        "metodo": "z3",
        "dominio": "ogni coppia di interi z3. `a1` e `b1` sono `z3.Int` dichiarati DENTRO "
                   "la funzione, e `dimostra_formalmente()` non prende argomenti: non c'e' "
                   "nessun ingresso esterno che possa stare fuori dal modello.",
        "data": "2026-07-31",
        "prova":
            "DIMOSTRATO CON Z3 il 2026-07-31, non osservato: chiesto al risolutore se esista un "
            "intero per cui If(a>b,a,b) e If(a>=b,a,b) differiscano -> unsat. Sono lo stesso "
            "massimo per OGNI coppia di interi. Nessun test potrebbe ucciderlo.",
    },
    ("fase199_invarianti.py", "dimostra_formalmente",
     "mn = z3.If(a2 < b2, a2, b2)", "<", "<="): {
        "metodo": "z3",
        "dominio": "ogni coppia di interi z3, come la voce del massimo qui sopra: `a2` e "
                   "`b2` sono `z3.Int` locali e la funzione non prende argomenti.",
        "data": "2026-07-31",
        "prova":
            "Stessa dimostrazione del massimo, applicata al minimo: If(a<b,a,b) e If(a<=b,a,b) "
            "coincidono per ogni coppia di interi.",
    },
    # ⛔ QUI C'ERA UNA FALSA EQUIVALENZA, TOLTA IL 2026-08-01.
    # Diceva: «`exc_info=True` -> `False` cambia solo quanto dettaglio finisce nel log,
    # nessun comportamento osservabile muta». **Falso**: il campo `exc_info` del record e'
    # osservabile, e lo stesso identico guasto e' stato UCCISO su fase177 lo stesso giorno.
    # Una voce sbagliata in questo elenco e' la peggiore specie di buco: non e' un punto
    # scoperto, e' un punto che abbiamo ordinato allo strumento di non guardare piu', per
    # sempre. Ora `fase199` ha la sua guardia (`test_un_DB_ILLEGGIBILE_grida_dicendo_PERCHE`)
    # e il mutante muore come deve.
    # ⚠️ LEZIONE PER CHI AGGIUNGE VOCI QUI: «non e' osservabile» va DIMOSTRATO (z3, o una
    #    prova esaustiva sugli ingressi), mai dedotto. Se la dimostrazione non c'e', la voce
    #    non va scritta: meglio un sopravvissuto aperto che una cecita' dichiarata.
    # ⛔ QUI C'ERA LA TERZA FALSA EQUIVALENZA, TOLTA IL 2026-08-05 -- ed e' la prima che non
    # ha trovato una persona: l'ha trovata una GUARDIA, sui dati veri, senza iniettare niente
    # (`test_pipeline_ci.TestLoSchedarioDegliEquivalenti_3_DOMINIO_MAGGIORE_DELLA_FIRMA`).
    # Diceva: `fase100_dac7.py` / `_n` / `>=` -> `>`, «PROVATO su 11 ingressi: 0 risposte
    # diverse», dal 2026-07-31.
    # PERCHE' ERA FALSA: la firma e' `def _n(v):` -- SENZA TIPO, quindi accetta qualunque
    # cosa -- mentre la prova ragionava sugli interi. Una prova vale quanto il modello su cui
    # e' fatta, e quel modello era piu' piccolo del dominio della funzione. Con una
    # SOTTOCLASSE di int che vale 0 (`class N(int)`, o un `IntEnum`):
    #     originale (v >= 0 vero) -> restituisce l'OGGETTO, di tipo N
    #     mutante   (v >  0 falso) -> restituisce 0, di tipo int
    # Sono distinguibili, e il test che lo ucciderebbe si scrive: `assertIs(type(_n(N(0))), N)`.
    # E' la stessa identica forma della gemella di `fase177/_cent` (tolta oggi, poco sotto) e
    # di quella di `fase160/_cent` ritirata il 2026-08-04 prima del commit: tre volte lo stesso
    # errore, e la terza l'ha vista una macchina invece di una persona.
    # ⚠️ Quel mutante ora e' un SOPRAVVISSUTO dichiarato, non un equivalente. Misurato sullo
    # stesso insieme killer prima e dopo (`test_dati_reali test_fase100_dac7`, insieme RIDOTTO
    # e dichiarato): prima 18 provati · 13 uccisi · 4 sopravvissuti · 1 equivalente; dopo,
    # l'esito e' scritto in `RIPRENDI_QUI.md`. Meglio un sopravvissuto aperto che una cecita'
    # dichiarata.
    # ⛔ QUI STAVA PER FINIRE LA SECONDA FALSA EQUIVALENZA, RITIRATA IL 2026-08-04 PRIMA DEL
    # COMMIT. Avevo dichiarato equivalente `fase160_escrow_garanzia.py` / `_cent` / `>=`->`>`
    # «su TUTTO il dominio», con una prova su 2018 ingressi. La prova era INCOMPLETA: la firma
    # e' `_cent(v: Any)` e i 2018 ingressi contenevano solo interi puri e non-interi, mai una
    # SOTTOCLASSE di int. Con `class Cent(int)` o un `IntEnum` che vale 0:
    #     originale (v >= 0 vero)  -> restituisce l'OGGETTO, tipo Cent
    #     mutante   (v >  0 falso) -> restituisce 0, tipo int
    # Sono distinguibili, e un test che uccide il mutante esiste davvero:
    #     assertIs(type(_cent(Cent(0))), Cent)   ->  True sull'originale, False sul mutante.
    # Quindi quel mutante resta SOPRAVVISSUTO e dichiarato tale, non equivalente. L'ha trovata
    # una revisione a CONTESTO FRESCO (appendice 19) rifiutando la mia dimostrazione: chi
    # scrive non giudica. Vale la stessa lezione scritta qui sopra il 2026-08-01, e stavolta
    # e' stata pagata prima del commit invece che dopo.
    # ⛔ QUI C'ERA LA QUARTA FALSA EQUIVALENZA, TOLTA IL 2026-08-05 dalla stessa guardia e per
    # lo stesso motivo. Diceva: `fase177_financial_controller.py` / `_cent` / `>` -> `>=`,
    # «DIMOSTRATO CON Z3 il 2026-08-01: unsat», ed era la piu' pericolosa delle quattro perche'
    # portava il timbro di un DIMOSTRATORE AUTOMATICO.
    # PERCHE' ERA FALSA: z3 ragiona sugli INTERI; la firma e' `def _cent(v: Any) -> int:`, cioe'
    # accetta QUALUNQUE COSA. Non ha sbagliato il risolutore -- gli era stata fatta la domanda
    # sbagliata, e la risposta giusta a una domanda sbagliata sembra identica a una prova.
    # Con `class Cent(int)` che vale 0, o un `IntEnum`:
    #     originale (v > 0 falso)  -> restituisce 0, di tipo int
    #     mutante   (v >= 0 vero)  -> restituisce l'OGGETTO, di tipo Cent
    # Distinguibili: `assertIs(type(_cent(Cent(0))), int)` e' vero sull'originale e falso sul
    # mutante. ⚠️ E' un modulo dei SOLDI: `_cent` normalizza gli importi in centesimi, e un
    # tipo diverso in uscita si propaga a chi lo scrive nel giornale.
    # ⚠️ Quel mutante ora e' un SOPRAVVISSUTO dichiarato, non un equivalente.
    # 💡 LA LEZIONE, che vale piu' delle due voci: **una dimostrazione formale vale quanto il
    # modello su cui e' fatta**. Il modo di controllarlo a macchina e' confrontare il dominio
    # dichiarato con la FIRMA, ed e' il controllo 3 della guardia sullo schedario.
    ("fase177_financial_controller.py", "riscuoti_debiti",
     "if residuo <= 0:", "<=", "<"): {
        "metodo": "traccia",
        "dominio": "il solo caso che differisce, `residuo == 0`, seguito lungo il codice "
                   "fino allo stato finale.",
        "data": "2026-08-01",
        "prova":
        "DIMOSTRATO il 2026-08-01 leggendo il codice, non supposto. Il caso che differisce e' "
        "UNO: residuo == 0 dentro il giro sulle righe di payout. Col codice sano si esce dal "
        "giro; col guasto si prosegue e per ogni riga rimanente vale quota = min(disp, 0) = 0, "
        "quindi `registra(importo_cents=0)` -- che RIFIUTA PRIMA di toccare il database e "
        "SENZA scrivere un allarme (righe 158-161: la validazione precede `self._apri()`). "
        "Il residuo non cambia, quindi nemmeno le scritture successive (righe 764-779). "
        "Stato identico, registro identico: restano solo giri a vuoto. "
        "⚠️ La premessa NON e' un'opinione: e' sotto guardia in "
        "`test_copertura_critica.test_un_importo_che_denaro_non_e_viene_RIFIUTATO_PULITO_"
        "senza_allarme`. Se qualcuno cambiasse `registra` per scrivere o gridare su un "
        "importo zero, quella guardia diventerebbe rossa e questa dichiarazione andrebbe "
        "rifatta. ⛔ Vale SOLO in `riscuoti_debiti`: la riga identica in `processa_penale` "
        "(538) NON e' dimostrata e resta un sopravvissuto aperto.",
    },
    ("fase177_financial_controller.py", "riscuoti_debiti",
     "if not pid or pid == rif_deb or disp <= 0:", "<=", "<"): {
        "metodo": "traccia",
        "dominio": "il solo caso che differisce, `disp == 0`, seguito lungo il codice fino "
                   "allo stato finale (`disp` viene da `_cent`, che non e' mai negativo).",
        "data": "2026-08-01",
        "prova":
        "DIMOSTRATO il 2026-08-01. `disp = _cent(r.get('minori'))` e `_cent` non restituisce "
        "MAI un negativo, quindi `disp < 0` e' sempre falso e l'unico caso che differisce e' "
        "disp == 0: col codice sano la riga di payout si salta, col guasto si prosegue con "
        "quota = min(0, residuo) = 0 e si arriva allo stesso `registra(importo_cents=0)` che "
        "rifiuta pulito, senza scrivere e senza gridare. Nessuna differenza di stato ne' di "
        "registro. Stessa premessa sotto guardia della voce qui sopra.",
    },

    # ── LA FAMIGLIA DEL CONFINE «ZERO» (2026-08-02) ─────────────────────────────────
    # Sei voci, una dimostrazione sola, ripetuta per ogni posto perche' la chiave porta la
    # FUNZIONE: cio' che e' dimostrato in un punto NON vale automaticamente altrove.
    # LA PREMESSA COMUNE, e non e' un'opinione: `_cent` non restituisce MAI un negativo
    # (righe 64-65), e `registra` RIFIUTA un importo zero PRIMA di aprire il database e
    # SENZA scrivere un allarme (righe 158-161: la validazione precede `self._apri()`).
    # Quindi ogni percorso che con il guasto arriva a `registra(importo_cents=0)` finisce
    # esattamente dove finiva prima: nessuna scrittura, nessun registro, stesso valore di
    # ritorno. Restano solo giri a vuoto.
    # ⚠️ LA PREMESSA E' SOTTO GUARDIA: `test_copertura_critica.
    #    test_un_importo_che_denaro_non_e_viene_RIFIUTATO_PULITO_senza_allarme`. Se qualcuno
    #    cambiasse `registra`, quella guardia diventerebbe rossa e QUESTE SEI VOCI andrebbero
    #    rifatte da capo. Non sono dispense permanenti: sono conclusioni con una premessa.
    ("fase177_financial_controller.py", "esporta_tutti",
     "and offset >= 0) else 0", ">=", ">"): {
        "metodo": "traccia",
        "dominio": "il solo valore che differisce, `offset == 0`, piu' i due rami per "
                   "offset negativo o non intero.",
        "data": "2026-08-02",
        "prova":
        "L'unico valore che differisce e' offset == 0: col codice sano la condizione e' vera "
        "e `off = offset`, cioe' 0; col guasto e' falsa e si prende il ramo `else`, che vale "
        "0. Stesso numero per la stessa via diversa. Per offset negativo o non intero "
        "entrambi danno 0. Nessun test puo' vedere la differenza perche' non ce n'e' una.",
    },
    ("fase177_financial_controller.py", "emetti_nota",
     "if tipo not in (\"credito\", \"debito\") or imp <= 0 or not (riferimento and soggetto",
     "<=", "<"): {
        "metodo": "traccia",
        "dominio": "il solo caso che differisce, `imp == 0`, seguito fino al valore di "
                   "ritorno.",
        "data": "2026-08-02",
        "prova":
        "imp == 0 e' l'unico caso che cambia: col guasto la nota non viene rifiutata subito "
        "ma si arriva a `registra(importo_cents=0)`, che rifiuta pulito -> `mv is None` -> "
        "`return None` (riga 400). Stesso valore di ritorno, nessuna nota creata, nessun "
        "movimento, nessun allarme.",
    },
    # ⛔ QUI C'ERA LA QUINTA FALSA EQUIVALENZA, TOLTA IL 2026-08-05, e non era sbagliata la
    # dimostrazione: era sbagliato CIO' CHE COPRIVA. Diceva:
    # `emetti_nota` / `if tipo not in ("credito","debito") or imp <= 0 or not (...)` / `or`->`and`.
    # Quella riga contiene **DUE** `or`, e la chiave non porta la COLONNA: una prova sola ne
    # spegneva DUE. Il testo ragionava sul primo (il `tipo` sconosciuto, che poi `registra`
    # rifiuta comunque) e nessuno si era accorto che perdonava anche il secondo.
    # IL SECONDO NON E' EQUIVALENTE -- tabella di verita' su tutte e 8 le combinazioni, due
    # differiscono, e sono due modi di far nascere un documento che non doveva nascere:
    #     tipo valido · imp > 0 · CAMPI OBBLIGATORI MANCANTI -> il sano rifiuta; col guasto la
    #         nota viene creata (causale vuota) e viene scritta una riga di GIORNALE;
    #     tipo valido · IMPORTO <= 0 · campi presenti        -> il sano rifiuta; col guasto si
    #         prosegue.
    # E' il modulo dei SOLDI, e quel punto era spento dal 2026-08-02.
    # ⛔ PERCHE' TOLTA E NON RISTRETTA: la chiave e' (file, funzione, riga, vecchio, nuovo).
    # Senza la colonna non esiste modo di dichiarare «solo il primo `or`», e inventare una
    # colonna vorrebbe dire cambiare anche il generatore. Meglio DUE sopravvissuti aperti che
    # una cecita' dichiarata su un punto che tocca il denaro.
    # 💡 E' la stessa famiglia del difetto del 2026-08-01 (una dichiarazione che si estende
    # oltre dove e' stata dimostrata) un passo piu' in fondo: allora mancava la FUNZIONE nella
    # chiave, adesso manca la COLONNA. Ora c'e' una guardia che conta -- controllo 5.
    ("fase177_financial_controller.py", "processa_penale",
     "if imp <= 0 or not (riferimento and host_id):", "<=", "<"): {
        "metodo": "traccia",
        "dominio": "il solo caso che differisce, `imp == 0`, seguito fino al valore di "
                   "ritorno.",
        "data": "2026-08-02",
        "prova":
        "imp == 0: col guasto si prosegue fino a `emetti_nota(importo_cents=0)`, che ha lo "
        "stesso controllo e restituisce None -> `if nota is None: return None` (riga 516). "
        "Identico.",
    },
    ("fase177_financial_controller.py", "processa_penale",
     "if residuo <= 0:", "<=", "<"): {
        "metodo": "traccia",
        "dominio": "il solo caso che differisce, `residuo == 0`, seguito lungo il giro "
                   "sulle righe di payout fino allo stato finale.",
        "data": "2026-08-02",
        "prova":
        "residuo == 0 dentro il giro sulle righe di payout: col codice sano si esce, col "
        "guasto si prosegue e per ogni riga rimanente quota = min(disp, 0) = 0, quindi "
        "`registra(importo_cents=0)` -> None -> `continue` (riga 553). Il residuo non cambia, "
        "quindi nemmeno le scritture successive. ⛔ Questa voce vale SOLO in `processa_penale`: "
        "la riga identica in `riscuoti_debiti` ha la sua dimostrazione a parte -- ed e' "
        "esattamente per questo che la chiave porta il nome della funzione.",
    },
    ("fase179_rate_limit.py", "_sfratta_se_serve",
     "if len(self._m) <= self._max_chiavi:", "<=", "<"): {
        "metodo": "traccia",
        "dominio": "il solo caso che differisce, `len(self._m) == self._max_chiavi`, "
                   "seguito fino alla riga che calcola quante chiavi sfrattare.",
        "data": "2026-08-02",
        "prova":
        "DIMOSTRATO il 2026-08-02 leggendo il codice. L'unico caso che differisce e' "
        "len(self._m) == self._max_chiavi: col codice sano si esce subito, col guasto si "
        "prosegue -- ma la riga dopo calcola `n_da_togliere = len - max`, che li' vale ZERO, "
        "e `sorted(...)[:0]` e' la lista VUOTA: non viene sfrattata nessuna chiave. Stato "
        "identico, registro identico; cambia solo qualche ciclo di calcolo sprecato a "
        "ordinare una lista per poi non usarla. Nessun test puo' vedere una differenza che "
        "non c'e'.",
    },
    ("fase178_watchdog.py", "eta_backup_sec",
     "if piu_recente is None or m > piu_recente:", ">", ">="): {
        "metodo": "traccia",
        "dominio": "il solo caso che differisce, `m == piu_recente`, seguito fino al "
                   "risultato finale del massimo.",
        "data": "2026-08-02",
        "prova":
        "Si cerca il backup PIU' RECENTE. L'unico caso che differisce e' m == piu_recente: "
        "col codice sano non si riassegna, col guasto si riassegna LO STESSO VALORE. Il "
        "risultato finale e' identico per costruzione (e' un massimo), e nessun test puo' "
        "vedere una differenza che non esiste. Dimostrato il 2026-08-02 leggendo il codice: "
        "`piu_recente = m` con m == piu_recente non cambia niente.",
    },
    # NB: il codice FUORI da una funzione ha nome funzione "" (vedi `funzione_di`), non
    # un'etichetta tipo "<modulo>": scriverla sbagliata fa semplicemente non combaciare la
    # voce, e il mutante resta -- giustamente -- fra i sopravvissuti.
    ("fase178_watchdog.py", "",
     "print(json.dumps(r, ensure_ascii=False))", "False", "True"): {
        "metodo": "traccia",
        "dominio": "l'uscita della riga, seguita fino a chi la consuma (il bash del server, "
                   "che la interpreta come JSON).",
        "data": "2026-08-02",
        "prova":
        "Cambia solo COME i caratteri accentati finiscono nel testo: `ensure_ascii=True` li "
        "scrive come \\uXXXX. Il JSON resta valido e, una volta LETTO, e' lo STESSO oggetto "
        "-- verificato: json.loads(dumps(x, True)) == json.loads(dumps(x, False)) per "
        "costruzione. Chi consuma questa uscita e' il bash del server, che la legge come "
        "JSON: per lui non cambia nulla. Resta un peggioramento della leggibilita' nei log, "
        "non un buco nella rete di protezione. ⚠️ Se un domani qualcuno leggesse questa "
        "uscita CONFRONTANDO I BYTE invece di interpretarla, questa dichiarazione andrebbe "
        "rifatta.",
    },
    ("fase177_financial_controller.py", "processa_penale",
     "if not pid or pid == riferimento or disp <= 0:", "<=", "<"): {
        "metodo": "traccia",
        "dominio": "il solo caso che differisce, `disp == 0`, seguito fino allo stato "
                   "finale (`disp` viene da `_cent`, che non e' mai negativo).",
        "data": "2026-08-02",
        "prova":
        "`disp = _cent(r.get('minori'))` non e' mai negativo, quindi `disp < 0` e' sempre "
        "falso e l'unico caso che differisce e' disp == 0: si prosegue con quota = 0 e si "
        "arriva allo stesso `registra` che rifiuta pulito. Nessuna differenza osservabile.",
    },
}


_FUNZIONI = {}


def funzione_di(righe, numero):
    """In quale funzione sta questa riga. Serve alla chiave delle equivalenze dichiarate.

    ⛔ DIFETTO VERO TROVATO IL 2026-08-01, prima che facesse danno. La chiave era
    (file, testo della riga, vecchio, nuovo) -- SENZA sapere DOVE. In
    `fase177_financial_controller` la riga `if residuo <= 0:` compare due volte, in due
    funzioni diverse (`processa_penale` e `riscuoti_debiti`): dichiarare equivalente l'una
    avrebbe dichiarato CIECA anche l'altra, di cui non era stato dimostrato niente.

    E' la stessa famiglia della falsa equivalenza tolta oggi da `fase199`, ma peggiore: non
    un errore di giudizio, un **effetto collaterale invisibile del meccanismo**. Una
    dichiarazione deve valere SOLO dove e' stata dimostrata.
    """
    import ast
    chiave = hash("\n".join(righe))
    if chiave not in _FUNZIONI:
        try:
            albero = ast.parse("\n".join(righe))
        except SyntaxError:
            return ""
        _FUNZIONI[chiave] = sorted((n.lineno, n.end_lineno, n.name) for n in ast.walk(albero)
                                   if isinstance(n, ast.FunctionDef))
    dentro = [f for f in _FUNZIONI[chiave] if f[0] <= numero <= f[1]]
    return dentro[-1][2] if dentro else ""


def _e_equivalente(percorso, righe, mutante):
    riga = righe[mutante["riga"] - 1].strip() if mutante["riga"] <= len(righe) else ""
    voce = EQUIVALENTI_DICHIARATI.get(
        (os.path.basename(percorso), funzione_di(righe, mutante["riga"]), riga,
         mutante["vecchio"], mutante["nuovo"]))
    # ⛔ DI QUI ESCE SEMPRE TESTO, MAI IL DIZIONARIO. I due soli consumatori tagliano il
    # risultato (`motivo[:70]` e `motivo[:60]`): restituire la voce intera farebbe morire il
    # giro con un TypeError DOPO aver gia' rotto un file di produzione. I campi `metodo`,
    # `dominio` e `data` servono alla guardia dello schedario, non al giro di mutazione.
    # Sotto guardia in `test_pipeline_ci.TestLoSchedarioDegliEquivalenti_2_CAMPI_STRUTTURATI.
    # test_IL_LETTORE_RESTITUISCE_TESTO_perche_chi_lo_usa_lo_TAGLIA`.
    # ⛔ E SI GUARDA ANCHE IL TIPO IN INGRESSO, non solo quello in uscita: una voce lasciata
    # nel formato storico (prosa, com'erano tutte fino al 2026-08-05) farebbe esplodere il
    # giro con `TypeError: string indices must be integers`. Qui invece non perdona nulla --
    # la direzione SICURA, perche' il mutante viene provato invece che saltato -- e la guardia
    # dei campi lo dice rosso alla prima esecuzione della suite.
    return voce["prova"] if isinstance(voce, dict) else None


# ── RETE DI SALVATAGGIO CONTRO L'INTERRUZIONE ───────────────────────────────────
#  Il `finally` protegge da un'ECCEZIONE, non da un PROCESSO UCCISO. E' successo due volte
#  in due giorni (2026-07-31 e 2026-08-01): un giro fermato a meta' ha lasciato un mutante
#  dentro un file di PRODUZIONE. La prima volta me ne sono accorto solo perche' ho
#  ricontrollato lo stato; la seconda idem. Un guasto cosi' puo' finire in un commit senza
#  che nessuno l'abbia voluto -- e sarebbe il peggior danno che questo strumento possa fare.
#
#  Quindi: prima di mutare si mette da parte l'originale e si scrive una TRACCIA. All'avvio,
#  se la traccia c'e' ancora, vuol dire che il giro precedente e' stato interrotto: si
#  rimette a posto il file e si GRIDA. Mai in silenzio: un ripristino silenzioso nasconde
#  proprio l'informazione che serve a capire perche' il giro e' morto.
_TRACCIA = os.path.join(tempfile.gettempdir(), "bookinvip_mutazione_in_corso")


def _apri_traccia(percorso, sorgente):
    try:
        os.makedirs(_TRACCIA, exist_ok=True)
        with io.open(os.path.join(_TRACCIA, "quale.txt"), "w", encoding="utf-8") as f:
            f.write(percorso)
        with io.open(os.path.join(_TRACCIA, "originale.txt"), "w",
                     encoding="utf-8", newline="") as f:
            f.write(sorgente)
    except OSError:
        pass                      # la rete e' un di piu': non deve impedire il giro


def _chiudi_traccia():
    try:
        shutil.rmtree(_TRACCIA, ignore_errors=True)
    except OSError:
        pass


def recupera_da_interruzione():
    """Se il giro precedente e' stato UCCISO, rimette a posto il file e lo dice. Ritorna il
    percorso recuperato, o None. Da chiamare all'avvio di ogni modo."""
    quale = os.path.join(_TRACCIA, "quale.txt")
    orig = os.path.join(_TRACCIA, "originale.txt")
    if not (os.path.exists(quale) and os.path.exists(orig)):
        return None
    try:
        with io.open(quale, encoding="utf-8") as f:
            percorso = f.read().strip()
        with io.open(orig, encoding="utf-8", newline="") as f:
            sorgente = f.read()
        if percorso and os.path.exists(percorso):
            # si riusa l'aiutante che scrive E invalida: due copie della stessa cosa sono un
            # difetto in attesa, e la guardia `test_il_motore_invalida_dopo_OGNI_riscrittura`
            # me l'ha colto qui il 2026-08-01, la terza volta in due giorni.
            _riscrivi_intatto(percorso, sorgente)
            print("::warning title=Giro precedente INTERROTTO::%s era rimasto MUTATO ed e' "
                  "stato rimesso a posto. Un file di produzione con un guasto dentro puo' "
                  "finire in un commit: controlla il diff." % os.path.basename(percorso))
            print("  ⚠️  RECUPERO: %s era rimasto mutato dal giro precedente -> ripristinato."
                  % percorso)
            return percorso
    except OSError:
        pass
    finally:
        _chiudi_traccia()
    return None


def _leggi_intatto(percorso):
    """Il file COM'E' sul disco, fine-riga compresi (`newline=""` non traduce nulla)."""
    with io.open(percorso, encoding="utf-8", newline="") as f:
        return f.read()


def _riscrivi_intatto(percorso, testo):
    """Riscrive senza toccare i fine-riga.

    ⛔ SERVE PERCHE' UN GIUDICE NON DEVE LASCIARE TRACCE. Scrivendo con `newline="\\n"` un
    file che sul disco era in stile Windows torna in stile Linux: il contenuto e' identico
    ma i BYTE no, e `git status` lo segnala come modificato. Successo davvero il 2026-07-31
    al primo giro sul diff: tre moduli di produzione risultavano cambiati dopo un giro che
    li aveva ripristinati. Nessuna riga di codice diversa -- ma una traccia del genere, in
    un'altra sessione, finisce dentro un commit senza che nessuno l'abbia voluta.
    """
    # L'invalidazione del bytecode sta QUI DENTRO, subito dopo la scrittura, e non nei
    # chiamanti: cosi' non e' una cosa da ricordarsi. Ce l'ha insegnato la guardia
    # `test_il_motore_invalida_dopo_OGNI_riscrittura`, diventata rossa il 2026-07-31 appena
    # ho spostato la scrittura in questo aiutante -- l'invalidazione era rimasta ai due
    # chiamanti, e un terzo chiamante futuro se ne sarebbe scordato. Un invariante che
    # dipende dalla memoria di chi scrive non e' un invariante.
    with io.open(percorso, "w", encoding="utf-8", newline="") as f:
        f.write(testo)
    invalida_bytecode(percorso)


_BASI = {}


def base_e_verde(bersaglio):
    """I test killer sono verdi sul codice SANO? Ritorna (verde, uscita). Misurato UNA volta
    per gruppo di killer e tenuto a mente: il costo si paga una sola volta per giro.

    ⛔ SENZA QUESTO CONTROLLO IL GIUDICE BARA, E BARA VERSO L'ALTO.
    Se i test falliscono gia' col codice sano, falliscono anche con ogni guasto dentro:
    OGNI mutante risulta «ucciso» e il giro stampa un punteggio pieno senza aver provato
    niente. Successo il 2026-08-01 su `fase156_erasure`: «42 su 42» con un test rosso in
    casa. E' la forma piu' insidiosa di finto verde, perche' non arriva come un problema --
    arriva come un trionfo, e nessuno controlla un trionfo.

    Verificato sulla storia (60 commit): nei due giri con la suite rossa i moduli falliti
    NON erano fra i killer dei mutanti, quindi i punteggi passati reggono. Ma reggevano per
    fortuna, non per costruzione: qui la fortuna smette di servire.
    """
    if bersaglio not in _BASI:
        _BASI[bersaglio] = esegui(bersaglio, timeout=900)
    return _BASI[bersaglio]


def giro_sul_diff(base="HEAD~1", tetto=40, tetto_test=8):
    """Genera i mutanti SULLE RIGHE APPENA CAMBIATE e chiede: qualcuno se ne accorgerebbe?

    Ritorna (esiti, rinunce). Ogni esito dice riga, guasto e verdetto. I tetti servono a
    non far durare un giro mezz'ora, e quando tagliano lo DICONO: un tetto silenzioso fa
    sembrare «coperto» cio' che non e' stato nemmeno provato.
    """
    esiti, rinunce = [], {"oltre_il_tetto": 0, "senza_sorveglianti": 0, "generatore": {}}
    for percorso, righe in sorted(righe_toccate(base).items()):
        pieno = os.path.join(REPO, percorso)
        sorgente = _leggi_intatto(pieno)
        try:
            mutanti, saltati = genera_mutanti(sorgente, righe)
        except SyntaxError as e:
            esiti.append({"file": percorso, "riga": getattr(e, "lineno", 0),
                          "verdetto": "non_analizzabile", "danno": str(e)[:80]})
            continue
        for k, v in saltati.items():
            rinunce["generatore"][k] = rinunce["generatore"].get(k, 0) + v
        sorveglianti = test_che_nominano(percorso)
        righe_testo = sorgente.splitlines()
        for m in mutanti:
            motivo = _e_equivalente(percorso, righe_testo, m)
            if motivo:
                # Non si prova nemmeno: non c'e' niente da vedere, ed e' scritto perche'.
                esiti.append({"file": percorso, "riga": m["riga"], "verdetto": "equivalente",
                              "danno": m["danno"], "nota": motivo[:70]})
                continue
            if len(esiti) >= tetto:
                rinunce["oltre_il_tetto"] += 1
                continue
            if not sorveglianti:
                rinunce["senza_sorveglianti"] += 1
                esiti.append({"file": percorso, "riga": m["riga"], "verdetto": "scoperto",
                              "danno": m["danno"],
                              "nota": "nessun file di test nomina questo modulo"})
                continue
            bersaglio = " ".join(sorveglianti[:tetto_test])
            _sano, _uscita = base_e_verde(bersaglio)
            if _sano is not True:
                esiti.append({"file": percorso, "riga": m["riga"], "verdetto": "base_rossa",
                              "danno": "i test killer non sono verdi sul codice sano",
                              "nota": (_uscita or "")[-200:]})
                continue
            _apri_traccia(pieno, sorgente)
            _riscrivi_intatto(pieno, applica_mutante(sorgente, m))
            try:
                verde, _ = esegui(bersaglio, timeout=600)
            finally:
                _riscrivi_intatto(pieno, sorgente)
                invalida_bytecode(pieno)
                _chiudi_traccia()
            # None = i test non hanno finito: non e' ne' ucciso ne' sopravvissuto.
            _v = "non_determinabile" if verde is None else (
                "sopravvissuto" if verde else "ucciso")
            esiti.append({"file": percorso, "riga": m["riga"], "verdetto": _v,
                          "danno": m["danno"],
                          "nota": "%s -> %s" % (m["vecchio"], m["nuovo"]),
                          "sorveglianti": len(sorveglianti)})
    return esiti, rinunce


def moduli_di_produzione():
    """I file di produzione veri: niente test, niente collaudi, niente archivio storico."""
    fuori = ("test_", "conftest")
    return sorted(n for n in os.listdir(REPO)
                  if n.endswith(".py") and not n.startswith(fuori)
                  and (n.startswith("fase") or n == "main_casavip.py"))


def censimento():
    """DOVE LA MACCHINA E' SCOPERTA — senza eseguire un solo test.

    Per ogni modulo: quanti mutanti si potrebbero generare (cioe' quanti punti di logica
    ci sono da sbagliare) e quanti file di test lo NOMINANO (cioe' quanti potrebbero
    accorgersene). Zero sorveglianti + mutanti generabili = **scoperto per certo**, e si
    vede in pochi secondi invece che in giorni di calcolo.

    Serve a decidere DOVE attaccare: il rischio non e' distribuito uniformemente, e
    generare mutanti in ordine alfabetico e' il modo migliore per sprecare una settimana.
    """
    righe = []
    for nome in moduli_di_produzione():
        percorso = os.path.join(REPO, nome)
        try:
            mutanti, saltati = genera_mutanti(_leggi_intatto(percorso))
        except SyntaxError:
            mutanti, saltati = [], {}
        # ⛔ LE RINUNCE ENTRANO NELLA TABELLA. Prima si buttavano via (`mutanti, _ = ...`) e
        # questa e' la tabella con cui si decide DOVE attaccare: un modulo scritto quasi tutto
        # a `not in` / `is None` compariva con pochi «mutanti», non risultava SCOPERTO, e
        # nessuno lo guardava -- mentre la sua logica non era mai stata messa alla prova.
        # Erano 1290 operatori invisibili in tutta la macchina. D18 punto 3, lasciata aperta
        # nel consumatore piu' letto dopo averla chiusa nel generatore (2026-08-05).
        righe.append({"modulo": nome, "mutanti": len(mutanti),
                      "rinunce": sum(saltati.values()),
                      "sorveglianti": len(test_che_nominano(percorso)),
                      "righe": sum(1 for _ in io.open(percorso, encoding="utf-8",
                                                      errors="replace"))})
    return righe


def misura_normale(bersaglio, tetto=900):
    """Quanto ci mette il gruppo di sorveglianti quando il codice e' SANO, **e se e' verde**.

    Serve a scegliere il tempo massimo con criterio invece che a caso. Misurato il
    2026-08-01 su `fase184_marca_temporale`: 64,7 secondi. Un tetto fisso di 600s era nove
    volte tanto -- e con 30 mutanti che si inchiodano avrebbe fatto CINQUE ORE.

    ⛔ E RESTITUISCE ANCHE IL VERDETTO, che prima veniva buttato via. DIFETTO VERO trovato
    il 2026-08-01 su `fase156_erasure`: un test era ROSSO gia' sul codice sano (colpa mia,
    un'asserzione sbagliata) e il giro ha stampato **42 mutanti su 42 uccisi**. Ovvio: se i
    test falliscono comunque, falliscono anche con ogni guasto dentro, e OGNI mutante
    risulta «ucciso». Il punteggio perfetto era un artefatto -- la forma piu' beffarda di
    finto verde, perche' arriva vestita da trionfo. Ora il giudice se ne accorge e si RIFIUTA
    di giudicare.
    """
    t0 = time.time()
    verde, uscita = esegui(bersaglio, timeout=tetto)
    return time.time() - t0, verde, uscita


def giro_su_moduli(nomi, tetto=30, tetto_test=6, minuti=45, killer=None):
    """La stessa domanda del modo diff, ma su un modulo INTERO scelto per rischio.

    DUE LIMITI, ed entrambi DICONO cosa hanno tagliato (mai un taglio silenzioso):
      · per mutante: 3 volte il tempo NORMALE del gruppo di test, misurato prima di
        cominciare. Piu' lungo di cosi' non e' lentezza: e' un ciclo che non finisce.
      · per giro: `minuti` complessivi. Quando scadono ci si ferma e si stampa quanti punti
        sono rimasti fuori -- un giro che si allunga senza fine non lo guarda piu' nessuno.
    """
    esiti, rinunce = [], {"oltre_il_tetto": 0, "senza_sorveglianti": 0, "generatore": {},
                          "oltre_il_tempo": 0, "normale_sec": {}}
    scadenza = time.time() + minuti * 60
    for nome in nomi:
        percorso = os.path.join(REPO, nome)
        if not os.path.exists(percorso):
            esiti.append({"file": nome, "riga": 0, "verdetto": "assente", "danno": "file inesistente"})
            continue
        sorgente = _leggi_intatto(percorso)
        mutanti, saltati = genera_mutanti(sorgente)
        for k, v in saltati.items():
            rinunce["generatore"][k] = rinunce["generatore"].get(k, 0) + v
        sorveglianti = test_che_nominano(percorso)
        righe_testo = sorgente.splitlines()
        fatti_qui = 0
        # ⛔ UN INSIEME KILLER RIDOTTO VA DICHIARATO, NON SUBITO IN SILENZIO.
        # I sorveglianti si scelgono in ordine ALFABETICO, che non ha niente a che vedere col
        # costo: su fase177 il primo (`test_avvio_e_ripristino`) da solo pesa 76s contro i 32s
        # di tutti gli altri sette insieme, e il tetto dei 45 minuti scadeva senza giudicare
        # un mutante. Con `killer` si punta ai test che davvero esercitano quel modulo.
        # ⚠️ Meno test = piu' FACILE sopravvivere: cio' che esce di qui sono CANDIDATI, da
        #    ri-provare contro TUTTI i sorveglianti prima di chiamarlo buco.
        scelti = list(killer) if killer else sorveglianti[:tetto_test]
        bersaglio = " ".join(scelti)
        # si misura il NORMALE prima di rompere qualcosa: cosi' il tetto e' scelto, non subito
        normale, sano, uscita = misura_normale(bersaglio) if sorveglianti else (0.0, True, "")
        if sano is not True:
            # ⛔ NON SI GIUDICA SU UNA BASE ROSSA. Se i sorveglianti falliscono gia' col codice
            # SANO, falliranno anche con ogni guasto dentro: ogni mutante risulterebbe
            # «ucciso» e il giro stamperebbe un punteggio pieno senza aver provato niente.
            # Successo davvero il 2026-08-01 su fase156 (42 su 42, tutto falso).
            esiti.append({"file": nome, "riga": 0, "verdetto": "base_rossa",
                          "danno": "i test killer non sono verdi sul codice sano",
                          "nota": (uscita or "")[-300:]})
            print("::error title=BASE ROSSA in %s::i test killer NON sono verdi sul codice "
                  "sano: qualunque punteggio di mutazione sarebbe falso (ogni mutante "
                  "risulterebbe ucciso). Prima si sistemano i test." % nome)
            print("\n%s: BASE ROSSA -- giro SALTATO. Killer: %s" % (nome, bersaglio))
            continue
        rinunce["normale_sec"][nome] = round(normale, 1)
        tetto_sec = max(60, int(3 * normale))
        print("\n%s: %d punti mutabili · sorveglianti %d, usati %d%s · normale %.1fs · "
              "tetto %ds" % (nome, len(mutanti), len(sorveglianti), len(scelti),
                             " (SCELTI A MANO)" if killer else "", normale, tetto_sec))
        print("  killer: %s" % (bersaglio or "NESSUNO"))
        for m in mutanti:
            motivo = _e_equivalente(nome, righe_testo, m)
            if motivo:
                esiti.append({"file": nome, "riga": m["riga"], "verdetto": "equivalente",
                              "danno": m["danno"], "nota": motivo[:60]})
                continue
            if not sorveglianti:
                rinunce["senza_sorveglianti"] += 1
                esiti.append({"file": nome, "riga": m["riga"], "verdetto": "scoperto",
                              "danno": m["danno"],
                              "nota": "nessun file di test nomina questo modulo"})
                continue
            if fatti_qui >= tetto:
                rinunce["oltre_il_tetto"] += 1
                continue
            if time.time() > scadenza:
                rinunce["oltre_il_tempo"] += 1
                continue
            fatti_qui += 1
            _apri_traccia(percorso, sorgente)
            _riscrivi_intatto(percorso, applica_mutante(sorgente, m))
            try:
                verde, _ = esegui(bersaglio, timeout=tetto_sec)
            finally:
                _riscrivi_intatto(percorso, sorgente)
                _chiudi_traccia()
            _v = "non_determinabile" if verde is None else (
                "sopravvissuto" if verde else "ucciso")
            esiti.append({"file": nome, "riga": m["riga"], "verdetto": _v,
                          "danno": m["danno"],
                          "nota": "%s -> %s" % (m["vecchio"], m["nuovo"])})
            # ⛔ SI STAMPA SUBITO, non alla fine. Il 2026-08-01 due giri sono stati interrotti
            # e hanno perso TUTTO il lavoro gia' fatto, perche' il risultato usciva solo in
            # fondo: quaranta minuti di calcolo spariti senza lasciare una riga.
            print("  %4d/%-4d riga %-5s %-18s %-9s %s"
                  % (fatti_qui, min(tetto, len(mutanti)), m["riga"],
                     "%s -> %s" % (m["vecchio"], m["nuovo"]), _v.upper(), m["danno"][:44]))
    return esiti, rinunce


def esegui(test_str, timeout=900):
    """Esegue i test killer. Ritorna (verde, uscita), dove `verde` puo' essere:
        True  -> i test passano   (il mutante SOPRAVVIVE a questo giro)
        False -> i test falliscono (il mutante e' UCCISO)
        None  -> non si sa: i test non hanno finito entro il tempo.

    ⛔ IL TERZO CASO NON ESISTEVA, E IL MOTORE MORIVA. Successo il 2026-08-01 su
    `fase184_marca_temporale`: un mutante ha fatto inchiodare i test, `TimeoutExpired` e'
    salita fino in cima e ha ucciso l'INTERO giro -- 112 punti di logica non esaminati per
    colpa di uno. Un giudice che smette di giudicare al primo intoppo non e' un giudice.

    E soprattutto: un'attesa infinita **non e' un mutante ucciso**. Trattarla come tale
    (il vecchio `if verde:` con None falsy avrebbe fatto esattamente questo) gonfia il
    punteggio con guasti che nessuno ha mai visto morire -- lo stesso difetto del bytecode
    stantio, in un'altra forma. Qui si dice NON DETERMINABILE, e si va avanti.
    """
    try:
        p = subprocess.run([sys.executable, "-m", "unittest"] + test_str.split(),
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "TEMPO SCADUTO dopo %ss: i test non hanno finito. Il mutante potrebbe " \
                     "aver introdotto un ciclo che non termina." % timeout
    return p.returncode == 0, p.stdout.decode("utf-8", "replace")


if __name__ == "__main__" and "--censimento" in sys.argv:
    recupera_da_interruzione()
    # DOVE LA MACCHINA E' SCOPERTA, senza eseguire un solo test. Serve a decidere dove
    # attaccare: generare mutanti in ordine alfabetico spreca una settimana di calcolo.
    _righe = censimento()
    _scoperti = [r for r in _righe if r["mutanti"] and not r["sorveglianti"]]
    _tot_mut = sum(r["mutanti"] for r in _righe)
    print("=" * 96)
    print("CENSIMENTO DELLA SORVEGLIANZA — %d moduli di produzione, nessun test eseguito"
          % len(_righe))
    print("=" * 96)
    print("  %-38s %7s %7s %8s %8s" % ("modulo", "righe", "mutanti", "rinunce",
                                       "chi lo vede"))
    for r in sorted(_righe, key=lambda x: (x["sorveglianti"], -x["mutanti"])):
        if r["mutanti"] == 0 and r["rinunce"] == 0 and r["sorveglianti"] > 0:
            continue                      # niente logica da sbagliare e comunque sorvegliato
        segno = "  <-- SCOPERTO" if ((r["mutanti"] or r["rinunce"])
                                     and not r["sorveglianti"]) else ""
        print("  %-38s %7d %7d %8d %8d%s"
              % (r["modulo"][:38], r["righe"], r["mutanti"], r["rinunce"],
                 r["sorveglianti"], segno))
    print("-" * 96)
    _tot_rin = sum(r["rinunce"] for r in _righe)
    print("  punti di logica sbagliabili in tutta la macchina: %d" % _tot_mut)
    # ⛔ SI DICHIARA ANCHE CIO' CHE IL GENERATORE NON SA ROMPERE. Un punto non esaminato non
    # e' un punto sicuro: e' un punto che nessuno ha mai guardato (D18 punto 3).
    print("  punti che il generatore NON sa rompere e NON prova (dichiarati): %d" % _tot_rin)
    print("  punti di logica TOTALI, esaminabili o no: %d" % (_tot_mut + _tot_rin))
    print("  moduli SCOPERTI (hanno logica e nessun test li nomina): %d su %d"
          % (len(_scoperti), len(_righe)))
    for r in _scoperti:
        print("::warning title=Modulo SCOPERTO %s::%d punti di logica e NESSUN test lo nomina"
              % (r["modulo"], r["mutanti"]))
    sys.exit(0)


if __name__ == "__main__" and "--modulo" in sys.argv:
    recupera_da_interruzione()
    _i = sys.argv.index("--modulo")
    _nomi = [a for a in sys.argv[_i + 1:] if not a.startswith("--")]
    # `--killer t1 t2 ...`: sceglie a mano i test che devono uccidere, invece dei primi sei in
    # ordine alfabetico. Serve quando un sorvegliante lentissimo mangia tutto il tempo del giro.
    _killer = None
    if "--killer" in sys.argv:
        _k = sys.argv.index("--killer")
        _killer = [a for a in sys.argv[_k + 1:] if not a.startswith("--")]
        _nomi = [n for n in _nomi if n not in _killer]
    # `--tetto N`: quanti mutanti al massimo per modulo (predefinito 30). Il tetto esiste per
    # non far durare un giro all'infinito, non per rinunciare: quando i sorveglianti costano
    # poco (qui 12s) lasciare fuori dei punti sarebbe uno spreco, non una prudenza. Cio' che
    # resta fuori viene comunque DICHIARATO in fondo al giro, sempre.
    _tetto = 30
    if "--tetto" in sys.argv:
        _t = sys.argv.index("--tetto")
        _tetto = int(sys.argv[_t + 1])
        _nomi = [n for n in _nomi if n != sys.argv[_t + 1]]
    # `--minuti N`: il tempo massimo del giro (predefinito 45). Come il tetto, esiste per non
    # far durare un giro all'infinito -- ma quando serve una misura COMPLETA va potuto
    # alzare, se no si resta con un numero parziale e ci si abitua. Il 2026-08-02 un giro su
    # 143 punti con sei moduli killer ha lasciato fuori 25 mutanti per scadenza: dichiarati,
    # ma non esaminati. Cio' che resta fuori viene DETTO in fondo al giro, sempre.
    _minuti = 45
    if "--minuti" in sys.argv:
        _m = sys.argv.index("--minuti")
        _minuti = int(sys.argv[_m + 1])
        _nomi = [n for n in _nomi if n != sys.argv[_m + 1]]
    print("=" * 96)
    print("MUTANTI GENERATI SU MODULI INTERI: %s" % ", ".join(_nomi))
    print("=" * 96)
    _esiti, _rin = giro_su_moduli(_nomi, tetto=_tetto, minuti=_minuti, killer=_killer)
    _sopr = [e for e in _esiti if e["verdetto"] == "sopravvissuto"]
    _scop = [e for e in _esiti if e["verdetto"] == "scoperto"]
    for e in _esiti:
        if e["verdetto"] in ("sopravvissuto", "scoperto", "assente", "non_determinabile",
                             "base_rossa"):
            print("  %-9s %s:%s  %s  (%s)" % (e["verdetto"].upper(), e["file"], e["riga"],
                                              e.get("nota", ""), e["danno"][:46]))
    print("-" * 96)
    _nd = [e for e in _esiti if e["verdetto"] == "non_determinabile"]
    print("provati: %d · uccisi: %d · SOPRAVVISSUTI: %d · scoperti: %d · equivalenti: %d "
          "· NON DETERMINABILI: %d"
          % (len(_esiti), sum(1 for e in _esiti if e["verdetto"] == "ucciso"),
             len(_sopr), len(_scop),
             sum(1 for e in _esiti if e["verdetto"] == "equivalente"), len(_nd)))
    for e in _nd:
        # NON fanno rosso il job (un test lento non deve bloccare la produzione) ma non sono
        # nemmeno uccisi: quel punto NON e' stato esaminato, e va detto a voce alta.
        print("::warning title=Punto NON ESAMINATO in %s::riga %s -- i test non hanno finito "
              "in tempo: %s" % (e["file"], e["riga"], e["danno"]))
    if _rin["oltre_il_tetto"] or _rin.get("oltre_il_tempo") or any(_rin["generatore"].values()):
        print("NON PROVATI (dichiarati): oltre il tetto %d · oltre il TEMPO %d · rinunce "
              "del generatore %s · secondi normali per modulo %s"
              % (_rin["oltre_il_tetto"], _rin.get("oltre_il_tempo", 0),
                 {k: v for k, v in _rin["generatore"].items() if v},
                 _rin.get("normale_sec", {})))
    for e in _sopr + _scop:
        print("::error title=Punto NON SORVEGLIATO in %s::riga %s -- %s | %s"
              % (e["file"], e["riga"], e["danno"], e.get("nota", "")))
    # una BASE ROSSA e' rossa quanto un sopravvissuto: senza di essa il punteggio non
    # significa niente, e un punteggio che non significa niente e' peggio di nessuno.
    _base = [e for e in _esiti if e["verdetto"] == "base_rossa"]
    # Un modulo ASSENTE non e' "zero problemi": e' ZERO MISURE. Bastava dimenticare il `.py`
    # nel nome e il giro non esaminava niente e usciva VERDE -- il giudizio piu' severo del
    # progetto ridotto a decorazione da un refuso, e in CI sarebbe passato liscio. Il vuoto
    # non e' un risultato, e' assenza di misura (D18 punto 1: lo strumento prova di essere
    # in condizione di misurare PRIMA di misurare).
    _ass = [e for e in _esiti if e["verdetto"] == "assente"]
    for e in _ass:
        print("::error title=NIENTE DA MISURARE in %s::%s -- il nome del modulo vuole il "
              "suffisso .py (i sorveglianti invece NO)" % (e["file"], e["danno"]))
    sys.exit(1 if (_sopr or _scop or _base or _ass) else 0)


if __name__ == "__main__" and "--diff" in sys.argv:
    recupera_da_interruzione()
    # MODO DIFF: i mutanti si GENERANO sulle righe appena cambiate, invece di pescarli da
    # un elenco scritto a mano. La domanda diventa quella giusta: «la riga che ho appena
    # scritto, se fosse sbagliata, se ne accorgerebbe qualcuno?».
    _i = sys.argv.index("--diff")
    _base = sys.argv[_i + 1] if len(sys.argv) > _i + 1 else "HEAD~1"
    print("=" * 90)
    print("MUTANTI GENERATI SUL DIFF  (base: %s)" % _base)
    print("=" * 90)
    _esiti, _rinunce = giro_sul_diff(_base)
    _sopr = [e for e in _esiti if e["verdetto"] == "sopravvissuto"]
    _scop = [e for e in _esiti if e["verdetto"] == "scoperto"]
    for e in _esiti:
        print("  %-9s %s:%s  %s  (%s)"
              % (e["verdetto"].upper(), e["file"], e["riga"], e.get("nota", ""), e["danno"][:52]))
    print("-" * 90)
    _nd = [e for e in _esiti if e["verdetto"] == "non_determinabile"]
    print("provati: %d · uccisi: %d · SOPRAVVISSUTI: %d · SCOPERTI: %d · NON DETERMINABILI: %d"
          % (len(_esiti), sum(1 for e in _esiti if e["verdetto"] == "ucciso"),
             len(_sopr), len(_scop), len(_nd)))
    for e in _nd:
        print("::warning title=Punto NON ESAMINATO in %s::riga %s -- i test non hanno finito "
              "in tempo: %s" % (e["file"], e["riga"], e["danno"]))
    if any(_rinunce["generatore"].values()) or _rinunce["oltre_il_tetto"]:
        # NIENTE TETTI SILENZIOSI: cio' che non e' stato provato si dice, sempre.
        print("NON PROVATI (dichiarati): oltre il tetto %d · rinunce del generatore %s"
              % (_rinunce["oltre_il_tetto"],
                 {k: v for k, v in _rinunce["generatore"].items() if v}))
    for e in _sopr + _scop:
        print("::error title=Riga NON SORVEGLIATA in %s::riga %s -- %s | %s"
              % (e["file"], e["riga"], e["danno"], e.get("nota", "")))
    if _sopr or _scop:
        print("\nQueste righe sono state cambiate e NESSUN test si accorgerebbe se fossero "
              "sbagliate.")
        sys.exit(1)
    print("\nOgni riga cambiata e' sorvegliata: un guasto li' verrebbe visto.")
    sys.exit(0)


if __name__ == "__main__":
    recupera_da_interruzione()          # PRIMA di tutto: un giro ucciso puo' aver lasciato
    riserva = tempfile.mkdtemp(prefix="mutazione_")   # un mutante dentro un file di produzione
    file_toccati = sorted({m[0] for m in MUTANTI})
    for f in file_toccati:
        shutil.copy(f, os.path.join(riserva, f.replace("/", "_")))

    print("=" * 90)
    print("TEST DI MUTAZIONE — se il motore facesse la cosa sbagliata, i test se ne")
    print("accorgerebbero? Un mutante SOPRAVVISSUTO e' un buco nella rete di protezione.")
    print("=" * 90)

    if "--prova-avvio" in sys.argv:
        # ⛔ L'AVVIO DEVE ESSERE PROVABILE SENZA MUTARE NIENTE.
        # Le tre modalita' a flag (--censimento, --modulo, --diff) escono PRIMA di qui, quindi
        # questo blocco -- rete di recupero, cartella di riserva, copia dei file da proteggere
        # -- non lo eseguiva nessun test: era l'unico pezzo del giudice senza un giudice.
        # Il 2026-08-01 ci e' rimasta dentro una riga spezzata a meta' (`tempfile.mkdtemp`
        # chiamato senza argomenti e poi ri-chiamato sul suo risultato): sintassi valida,
        # esplosione certa. Se n'e' accorta la CI, DOPO il push. Ora si prova in un secondo.
        print("AVVIO OK: riserva pronta, %d file di produzione messi al sicuro"
              % len(file_toccati))
        shutil.rmtree(riserva, ignore_errors=True)
        sys.exit(0)

    sopravvissuti, uccisi, non_applicabili, incerti, basi_rosse = [], 0, [], [], []
    t0 = time.time()
    try:
        for i, (percorso, orig, mut, test, danno) in enumerate(MUTANTI, 1):
            testo = io.open(percorso, encoding="utf-8").read()
            if orig not in testo:
                non_applicabili.append("%s (testo non trovato)" % percorso)
                print("\n%2d. %-28s  ? testo non trovato: mutante non applicabile"
                      % (i, percorso))
                continue
            # ⛔ LA BASE DEV'ESSERE VERDE PRIMA DI ROMPERE QUALCOSA. Questo e' il modo che
            # gira in CI e produce il numero che finisce nei documenti: se i suoi killer
            # fossero gia' rossi, ogni mutante risulterebbe «ucciso» e il punteggio pieno
            # sarebbe aria. Fino al 2026-08-01 qui non c'era nessun controllo: e' andata
            # bene per FORTUNA (verificato su 60 commit), non per costruzione.
            sano, perche = base_e_verde(test)
            if sano is not True:
                basi_rosse.append((percorso, test))
                print("\n%2d. %-28s  ⛔ BASE ROSSA: '%s' non e' verde sul codice sano"
                      % (i, percorso, test))
                print("::error title=BASE ROSSA::i killer '%s' falliscono gia' senza mutanti: "
                      "qualunque punteggio sarebbe falso. %s" % (test, (perche or "")[-200:]))
                continue
            # ⛔ LA RETE PRIMA DEL SALTO. Fino al 2026-08-03 questo era l'unico dei tre punti
            # che rompe un file di produzione SENZA aprire la traccia: un giro ucciso qui
            # lasciava il mutante sul disco e nessuno poteva vederlo -- la rete di recupero
            # non trovava niente da recuperare, e il gancio al commit niente da bloccare.
            # Successo davvero: `if ore >= 99999:` al posto di `if ore >= 24:` nella penale
            # no-show (fase83_server.py:6185), rimasto li' per ore in silenzio.
            _apri_traccia(percorso, testo)
            io.open(percorso, "w", encoding="utf-8", newline="\n").write(
                testo.replace(orig, mut, 1))
            invalida_bytecode(percorso)       # il figlio deve vedere IL GUASTO, non la cache
            try:
                verde, uscita = esegui(test)
            finally:
                io.open(percorso, "w", encoding="utf-8", newline="\n").write(testo)
                invalida_bytecode(percorso)   # ...e il mutante dopo non deve vedere QUESTA
                _chiudi_traccia()   # la rete si richiude: una traccia lasciata aperta
                                    # bloccherebbe il commit dopo per NIENTE, e un falso
                                    # allarme e' un difetto quanto uno mancato (regola 10)
            print("\n%2d. %s" % (i, percorso))
            print("    guasto introdotto: %s" % danno)
            if verde is None:
                # TEMPO SCADUTO: non si sa. Contarlo fra gli UCCISI gonfierebbe il punteggio
                # con un guasto che nessuno ha visto morire -- lo stesso difetto del bytecode
                # stantio, in un'altra forma. Va detto, e va guardato a mano.
                incerti.append((percorso, danno, test))
                print("    ESITO: NON DETERMINABILE -- i test non hanno finito in tempo.")
            elif verde:
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

    provati = len(MUTANTI) - len(non_applicabili) - len(basi_rosse)
    print("\n" + "=" * 90)
    print("MUTANTI PROVATI: %d  |  UCCISI: %d  |  SOPRAVVISSUTI: %d  |  INCERTI: %d  |  %.1f minuti"
          % (provati, uccisi, len(sopravvissuti), len(incerti), (time.time() - t0) / 60.0))
    if non_applicabili:
        print("non applicabili (il codice e' cambiato): %s" % ", ".join(non_applicabili))
    if basi_rosse:
        # ⛔ NON e' un dettaglio: ogni riga qui e' un punto che NON e' stato giudicato,
        # e che senza questo controllo sarebbe finito fra gli "uccisi" gonfiando il totale.
        print("\n⛔ BASE ROSSA su %d mutanti: i loro test killer falliscono GIA' sul codice "
              "sano, quindi li' non si puo' giudicare niente. Prima si sistemano i test."
              % len(basi_rosse))
        for percorso, test in basi_rosse:
            print("  ⛔ %-30s killer: %s" % (percorso, test))
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
    if basi_rosse:
        # Una base rossa e' rossa quanto un sopravvissuto: senza di essa il punteggio non
        # significa niente, e un punteggio che non significa niente e' peggio di nessuno.
        # Va detto QUI, se no un giro che non ha giudicato nulla uscirebbe verde.
        sys.exit(1)
    print("\nNESSUN MUTANTE SOPRAVVISSUTO: ogni guasto simulato viene visto dai test.")
    sys.exit(0)
