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
    mutanti, saltati = [], {"a_cavallo": 0, "catena": 0, "non_trovato": 0}

    def _aggiungi(nodo_riga, taglio, nuovo, tipo, danno):
        if taglio is None:
            saltati["non_trovato"] += 1
            return
        r, ci, cf = taglio
        if ammesse is not None and r not in ammesse:
            return
        mutanti.append({"riga": r, "col_inizio": ci, "col_fine": cf, "nuovo": nuovo,
                        "vecchio": righe[r - 1][ci:cf], "tipo": tipo, "danno": danno})

    for nodo in ast.walk(albero):
        if isinstance(nodo, ast.Compare):
            if len(nodo.ops) != 1:
                saltati["catena"] += 1
                continue
            nome = type(nodo.ops[0]).__name__
            if nome not in _CONFRONTI:
                continue
            simbolo, sostituto, danno = _CONFRONTI[nome]
            taglio = _taglia_operatore(righe, nodo.left.end_lineno, nodo.left.end_col_offset,
                                       nodo.comparators[0].lineno,
                                       nodo.comparators[0].col_offset, simbolo)
            if taglio is None and nodo.left.end_lineno != nodo.comparators[0].lineno:
                saltati["a_cavallo"] += 1
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
                    saltati["a_cavallo"] += 1
                    continue
                _aggiungi(nodo.lineno, taglio, sostituto, "booleano", danno)

        elif isinstance(nodo, ast.Constant) and nodo.value in (True, False) \
                and isinstance(nodo.value, bool):
            testo = "True" if nodo.value else "False"
            if nodo.lineno != nodo.end_lineno:
                saltati["a_cavallo"] += 1
                continue
            riga = righe[nodo.lineno - 1] if nodo.lineno <= len(righe) else ""
            if riga[nodo.col_offset:nodo.end_col_offset] != testo:
                saltati["non_trovato"] += 1
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
EQUIVALENTI_DICHIARATI = {
    ("fase199_invarianti.py", "mx = z3.If(a1 > b1, a1, b1)", ">", ">="):
        "DIMOSTRATO CON Z3 il 2026-07-31, non osservato: chiesto al risolutore se esista un "
        "intero per cui If(a>b,a,b) e If(a>=b,a,b) differiscano -> unsat. Sono lo stesso "
        "massimo per OGNI coppia di interi. Nessun test potrebbe ucciderlo.",
    ("fase199_invarianti.py", "mn = z3.If(a2 < b2, a2, b2)", "<", "<="):
        "Stessa dimostrazione del massimo, applicata al minimo: If(a<b,a,b) e If(a<=b,a,b) "
        "coincidono per ogni coppia di interi.",
    ("fase199_invarianti.py",
     'logger.warning("invarianti: DB illeggibile (ISOLATO): %s", f, exc_info=True)',
     "True", "False"):
        "Cambia solo QUANTO dettaglio finisce nel log (la traccia dell'eccezione), non cosa "
        "fa il programma: nessun comportamento osservabile muta. Resta un peggioramento "
        "della diagnosi, non un buco nella rete di protezione.",
    ("fase100_dac7.py",
     "return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0",
     ">=", ">"):
        "PROVATO il 2026-07-31 su 11 ingressi (0, 1, -1, 5, -5, True, False, None, 'x', "
        "3.0, 10^9): 0 risposte diverse. Con v=0 il ramo vero restituisce 0 e il ramo else "
        "restituisce 0: identico. Nessun test puo' ucciderlo perche' non c'e' niente da "
        "vedere.",
}


def _e_equivalente(percorso, righe, mutante):
    riga = righe[mutante["riga"] - 1].strip() if mutante["riga"] <= len(righe) else ""
    return EQUIVALENTI_DICHIARATI.get(
        (os.path.basename(percorso), riga, mutante["vecchio"], mutante["nuovo"]))


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
            mutanti, _ = genera_mutanti(_leggi_intatto(percorso))
        except SyntaxError:
            mutanti = []
        righe.append({"modulo": nome, "mutanti": len(mutanti),
                      "sorveglianti": len(test_che_nominano(percorso)),
                      "righe": sum(1 for _ in io.open(percorso, encoding="utf-8",
                                                      errors="replace"))})
    return righe


def misura_normale(bersaglio, tetto=900):
    """Quanto ci mette il gruppo di sorveglianti quando il codice e' SANO.

    Serve a scegliere il tempo massimo con criterio invece che a caso. Misurato il
    2026-08-01 su `fase184_marca_temporale`: 64,7 secondi. Un tetto fisso di 600s era nove
    volte tanto -- e con 30 mutanti che si inchiodano avrebbe fatto CINQUE ORE.
    """
    t0 = time.time()
    esegui(bersaglio, timeout=tetto)
    return time.time() - t0


def giro_su_moduli(nomi, tetto=30, tetto_test=6, minuti=45):
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
        bersaglio = " ".join(sorveglianti[:tetto_test])
        # si misura il NORMALE prima di rompere qualcosa: cosi' il tetto e' scelto, non subito
        normale = misura_normale(bersaglio) if sorveglianti else 0.0
        rinunce["normale_sec"][nome] = round(normale, 1)
        tetto_sec = max(60, int(3 * normale))
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
    print("  %-38s %7s %7s %8s" % ("modulo", "righe", "mutanti", "chi lo vede"))
    for r in sorted(_righe, key=lambda x: (x["sorveglianti"], -x["mutanti"])):
        if r["mutanti"] == 0 and r["sorveglianti"] > 0:
            continue                      # niente logica da sbagliare e comunque sorvegliato
        segno = "  <-- SCOPERTO" if (r["mutanti"] and not r["sorveglianti"]) else ""
        print("  %-38s %7d %7d %8d%s"
              % (r["modulo"][:38], r["righe"], r["mutanti"], r["sorveglianti"], segno))
    print("-" * 96)
    print("  punti di logica sbagliabili in tutta la macchina: %d" % _tot_mut)
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
    print("=" * 96)
    print("MUTANTI GENERATI SU MODULI INTERI: %s" % ", ".join(_nomi))
    print("=" * 96)
    _esiti, _rin = giro_su_moduli(_nomi)
    _sopr = [e for e in _esiti if e["verdetto"] == "sopravvissuto"]
    _scop = [e for e in _esiti if e["verdetto"] == "scoperto"]
    for e in _esiti:
        if e["verdetto"] in ("sopravvissuto", "scoperto", "assente", "non_determinabile"):
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
    sys.exit(1 if (_sopr or _scop) else 0)


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
