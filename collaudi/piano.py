"""IL PIANO DELLA MACCHINA — dieci blocchi, e a dire se sono finiti e' una MACCHINA.

⛔ PERCHE' ESISTE QUESTO FILE (2026-08-15, ordine del fondatore)
==============================================================================
*«Se non mettiamo a posto questo foglio, ogni chat fa quel che vuole.»*

Aveva ragione, e la prova sta nel codice, non nelle opinioni. Il guardiano che c'era
prima -- `collaudi/piano_dei_soldi.py` -- prova a capire il piano **leggendo la prosa**
scritta a mano dentro i documenti:

    _ANCORA_GIUDICATI = re.compile(r"passati dal giudice - (\\d+)")
    _CONTO_GIUDICATI  = re.compile(r"(\\d+) moduli dei soldi giudicati")

Cioe': una macchina che cerca di indovinare un tema. Cambia una parola e diventa cieca;
riscrivi il paragrafo e il piano e' un altro. **Il piano non puo' vivere in un racconto.**

Qui si gira al contrario, ed e' tutta la differenza:

    PRIMA:  la chat scrive il racconto  ->  la macchina prova a leggerlo
    ADESSO: la macchina tiene i DATI    ->  il racconto lo stampa lei

`BLOCCHI` qui sotto **e' il piano**. Non lo descrive: lo E'. Ogni blocco dichiara i suoi
moduli, gli strumenti d'ingegneria che DEVE aver superato (presi dalla ricerca del
2026-08-14, non inventati) e cosa vuol dire «finito» per quel mestiere. E ogni cosa che
si puo' misurare la misura questo file, non una frase.

==============================================================================
COSA GARANTISCE MECCANICAMENTE (e cosa no -- D18 punto 3)
==============================================================================
GARANTISCE:
  G1  ogni `fase*.py` del progetto sta in ESATTAMENTE UN blocco: un modulo nuovo che
      nessuno classifica fa diventare ROSSO questo controllo il giorno stesso. E' la
      difesa contro «costruito e dimenticato», che qui e' gia' costato decine di moduli
      dimenticati e una classifica di rischio tarata su numeri gonfiati.
      ⛔ QUI C'ERA UNA CIFRA (59), ED ERA SMENTITA. Veniva da un conto fatto partendo anche
      da `app.py`, che in produzione non ci va (misurato il 2026-08-18: nessuna immagine lo
      copia). Il numero vero lo produce `python collaudi/raggiungibilita.py`, e non si
      ricopia: un numero che descrive lo stato della macchina non si scrive, si PRODUCE.
      ⚠️ E notare DOVE si era nascosto: la voce 7 del foglio unico, che esiste apposta per
      stanare i numeri scritti a mano, legge solo i `.md` -- in un `.py` come questo non
      poteva vederlo. L'ha trovato una revisione indipendente, non uno strumento nostro.
  G2  nessun blocco nomina un modulo che non esiste (sbaglio S2: i nomi si leggono, non
      si inventano -- `fase186_guardiano_stati.py` fu inventato due volte).
  G3  nessun modulo sta in due blocchi (un modulo con due padroni non ha nessun padrone).
  G4  ogni strumento dichiarato obbligatorio esiste davvero in `collaudi/`.
  G5  un blocco NON puo' dichiararsi FINITO senza la prova: lo stato lo calcola questo
      file dalle misure, non lo digita una chat. E' il divieto B1 applicato ai giudizi.

NON GARANTISCE (dichiarato, perche' un taglio silenzioso fa sembrare «coperto» cio' che
nessuno ha guardato):
  N1  «modulo coperto» qui vuol dire **il suo nome compare in un file di test**. NON vuol
      dire che quel test lo esegua, ne' che lo esegua bene. E' un limite reale: un modulo
      puo' essere nominato e morto al 94% dentro (misurato su `fase133`).
  N2  non misura la mutazione, la copertura di riga, ne' gli esiti degli strumenti: quelli
      li scriveranno gli strumenti stessi (il pezzo 5 del piano, «la scheda la scrive il
      Giudice»). Finche' non esiste quella scheda, NESSUN blocco puo' risultare FINITO --
      e questo file lo dice a voce alta invece di dare un verde comodo.
  N3  non legge i 5 documenti e non li giudica: quello lo fa `audit_millimetrico.py`.

==============================================================================
COME SI USA
==============================================================================
    python collaudi/piano.py            # stampa il piano misurato, esce 1 se c'e' una
                                        # contraddizione fra i dati e la macchina
    python collaudi/piano.py --breve    # solo il riepilogo per blocco

Lo stampa anche `collaudi/regole_avvio.py` a ogni inizio di sessione, cosi' nessuna chat
puo' dire «non sapevo cosa fare».
"""
import io
import os
import re
import sys

try:  # Windows: la console cp1252 non regge gli accenti -> uscita tollerante
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ==============================================================================
# LA CASSETTA DEGLI ATTREZZI — dalla ricerca industriale del 2026-08-14
# ==============================================================================
# Ogni voce dice: come si chiama qui da noi, e COSA dimostra. Un blocco elenca quali
# di questi gli si applicano: non tutti servono a tutto, ed e' il punto -- la ricerca
# dice che AWS non sceglie UN metodo, ne usa SEI, ognuno per cio' che sa vedere.
ATTREZZI = {
    "mutazione": (
        "collaudi/mutazione_prodotto.py",
        "rompe il motore di proposito: i test se ne accorgono? (Google, IEEE TSE 2021)"),
    "z3": (
        "test_fase199_invarianti.py",
        "dimostrazione matematica: le leggi dei soldi non si possono violare (Bornholt, SOSP 2021)"),
    "hypothesis": (
        "collaudi/fuzz_soldi.py",
        "test a proprieta': uccide ~50x i mutanti di un test normale (Ravi & Coblenz, OOPSLA 2025)"),
    "oracolo": (
        "collaudi/oracolo_tassa.py",
        "un secondo calcolo scritto separatamente ricalcola da zero e confronta"),
    "gare": (
        "collaudi/gare_estreme.py",
        "concorrenza: due che prenotano lo stesso letto nello stesso istante"),
    "orologio": (
        "collaudi/bombe_a_tempo.py",
        "il tempo che passa: scadenze, hold, finestre di penale"),
    "produzione": (
        "collaudi/verifica_produzione.py",
        "verifica a tempo di esecuzione sulla macchina VERA (AWS PObserve, 2023)"),
    "plausibilita": (
        "collaudi/plausibilita.py",
        "questo numero ha senso nel mondo vero? (1.800.000 yen a notte no)"),
    "occhio": (
        "collaudi/occhio_del_fondatore.py",
        "chi apre questa pagina, cosa legge davvero?"),
    "permessi": (
        "collaudi/mappa_scoperta.py",
        "matrice dei permessi: ogni rotta riservata x nessuna credenziale"),
    "finti_verdi": (
        "collaudi/caccia_finti_verdi.py",
        "test saltati, senza asserzioni, guardie che non possono fallire"),
    "stati_impossibili": (
        "collaudi/stati_impossibili.py",
        "lo stato che «non puo' capitare» si costruisce a mano, adesso (D19)"),
    "conti": (
        "collaudi/conti_stripe.py",
        "i conti col gestore veri: la tariffa copre il costo?"),
    "e2e": (
        "collaudi/percorso_e2e.py",
        "il percorso intero come lo fa una persona, dall'inizio alla fine"),
}

# ==============================================================================
# ⛔ I DIECI BLOCCHI — QUESTO E' IL PIANO
# ==============================================================================
# «ordine» = in che sequenza si lavorano. Non e' la grandezza a decidere: decide il
# danno che fa un guasto li' dentro. I soldi di una persona vera vengono prima di una
# pagina di marketing, sempre.
#
# «finito_quando» = le condizioni, in italiano, che rendono quel blocco chiuso. Sono
# scritte perche' le legga un essere umano, ma ognuna e' pensata per diventare una
# MISURA: quando lo strumento che la misura esiste, si aggancia qui.
BLOCCHI = (
    {
        "ordine": 1,
        "nome": "SOLDI E PAGAMENTI",
        "perche": "un guasto qui toglie soldi veri a una persona vera: e' l'unico blocco "
                  "dove un difetto non si puo' rimediare con una correzione",
        "moduli": (
            "fase15_idempotency", "fase17_money", "fase35_pagamenti",
            "fase65_split_payment", "fase85_pagamenti_stripe", "fase87_stripe_webhook",
            "fase99_multicurrency", "fase101_stripe_connect", "fase102_motore_autonomo",
            "fase104_gateway_asia", "fase131_payout_dashboard", "fase133_split_quote_uguali",
            "fase149_deposito_cauzionale", "fase160_escrow_garanzia", "fase162_pagamenti_pendenti",
            "fase167_credito_single_use", "fase177_financial_controller", "fase181_audit_console",
            "fase182_riconciliazione", "fase183_carta_offsession", "fase186_guardiano",
            "fase188_paga_struttura", "fase191_blocco_globale", "fase199_invarianti",
        ),
        "attrezzi": ("z3", "hypothesis", "mutazione", "oracolo", "orologio", "conti",
                     "produzione", "stati_impossibili", "e2e"),
        "finito_quando": (
            "le dimostrazioni z3 sugli invarianti GIRANO in CI, e i test che le portano "
            "NON risultano saltati",
            # ⛔ CORRETTA IL 2026-08-17, e la correzione conta piu' del testo. Diceva: «il
            # rimborso all'ospite parte DA SOLO». Ma il 2026-08-16 il fondatore ha deciso
            # l'opposto -- a mano, con la lista e il pulsante: «se la macchina sbaglia ci
            # rimetto conti, fiducia, credibilita'». Una riga d'arrivo che descrive un
            # obiettivo ABBANDONATO non si spunta mai: chi arriva dopo lavora per far
            # sparire una casella che non doveva esserci, oppure dichiara «finito» a caso.
            # La riga d'arrivo vera non e' COME partono i soldi, e' SE arrivano.
            "i soldi tornano DAVVERO all'ospite da OGNI strada che porta a un rimborso, non "
            "solo da quella che qualcuno si e' ricordato di provare (il 2026-08-16 le strade "
            "erano due e ne funzionava una). ⛔ L'AUTOMATICO NON e' la riga d'arrivo di "
            "questo blocco: e' una decisione del fondatore, e si accende dopo -- prima si "
            "guadagna la fiducia, poi si toglie il dito",
            "gli orologi di prova Stripe hanno visto scadere hold, payout e penale davvero",
            "esistono le relazioni metamorfiche sull'aritmetica del denaro",
            "zero punti di mutazione scoperti sul codice che la produzione ESEGUE",
            "gli invarianti sono verificati in PRODUZIONE, non solo nei test",
        ),
    },
    {
        "ordine": 2,
        "nome": "PRENOTAZIONI E INVENTARIO",
        "perche": "il sovra-affitto e' il difetto che uccide la fiducia in un colpo solo: "
                  "una persona arriva e il letto non c'e'",
        "moduli": (
            "fase34_prenotazioni", "fase36_booking_api", "fase58_channel_manager",
            "fase59_concierge", "fase62_predictive_noshow", "fase67_coda_intelligente",
            "fase71_commitment", "fase82_ical_sync", "fase111_cancellazione",
            "fase135_ical_bidirezionale", "fase152_notifiche_prenotazione", "fase187_fuso_orario",
        ),
        "attrezzi": ("z3", "gare", "mutazione", "orologio", "hypothesis", "e2e", "produzione"),
        "finito_quando": (
            "la macchina a stati copre cancellazioni, modifiche, no-show e sovra-affitto",
            "il blocco atomico regge sotto gara (misurato: 10 giri x 24 agenti, 1 conferma)",
            "iCal ha una difesa dal RITARDO 15 min-2 ore (oggi: zero, e' la finestra "
            "delle prenotazioni fantasma)",
            "zero punti di mutazione scoperti sul codice che la produzione ESEGUE",
        ),
    },
    {
        "ordine": 3,
        "nome": "IDENTITA', ACCESSI E SICUREZZA",
        "perche": "una porta senza serratura non e' un difetto di collaudo: e' una porta "
                  "aperta, e chiunque puo' entrare oggi",
        "moduli": (
            "fase64_smartpass", "fase73_firma_agile", "fase80_sentinel", "fase105_identity_gate",
            "fase127_checkin_digitale", "fase143_kyc_host", "fase179_rate_limit",
            "fase180_bunker", "fase192_admin_accounts",
        ),
        "attrezzi": ("permessi", "produzione", "mutazione", "stati_impossibili", "finti_verdi"),
        "finito_quando": (
            "nessuna rotta pubblica SCRIVE senza identita' (oggi due: `_split_crea`, `_split_paga`)",
            "la matrice dei permessi e' verde su ogni rotta riservata, provata SUL SITO VERO",
            "ogni sonda negativa interroga un indirizzo che risponde diverso da 404",
        ),
    },
    {
        "ordine": 4,
        "nome": "PREZZI, COMMISSIONI E TASSE",
        "perche": "e' la cifra che l'host legge e su cui decide se fidarsi: se il sito dice "
                  "un numero e il motore ne fa un altro, l'abbiamo perso",
        "moduli": (
            "fase43_commissione", "fase44_prezzo", "fase45_pricing", "fase66_tassa_soggiorno",
            "fase69_trasparenza", "fase98_policy_commissione", "fase106_dynamic_pricing",
            "fase119_calendario_prezzi", "fase125_confronto_guest", "fase147_tassa_comunale",
            "fase189_price_alerts", "fase190_rate_parity",
        ),
        "attrezzi": ("oracolo", "plausibilita", "hypothesis", "mutazione", "occhio", "conti"),
        "finito_quando": (
            "ogni cifra pubblica coincide col motore (lo misura gia' `audit_millimetrico.py`)",
            "le relazioni metamorfiche reggono: raddoppiare le notti raddoppia la parte fissa, "
            "l'ordine degli sconti non cambia il totale",
            "da noi costa SEMPRE meno che sulle OTA, e l'host non puo' mentire sul prezzo",
        ),
    },
    {
        "ordine": 5,
        "nome": "LEGALE E CONFORMITA'",
        "perche": "qui un difetto non si vede per mesi e poi arriva come una multa o una "
                  "causa: nessun test lo scopre, solo il confronto col testo di legge",
        "moduli": (
            "fase79_dichiarazione", "fase100_dac7", "fase103_reverse_charge",
            "fase145_contratto_pdf", "fase151_alloggiati_web", "fase154_giurisdizioni_marketing",
            "fase156_erasure", "fase163_accettazioni", "fase184_marca_temporale",
            "fase185_testi_legali",
        ),
        "attrezzi": ("occhio", "produzione", "finti_verdi", "e2e"),
        "finito_quando": (
            "le 3 spunte obbligatorie sono bloccate lato browser E rifiutate 422 lato server",
            "termini e privacy sono leggibili in tutte le lingue dichiarate",
            "un avvocato vero ha validato i testi (⛔ non lo puo' dire una macchina)",
        ),
    },
    {
        "ordine": 6,
        "nome": "ESPERIENZA DELL'OSPITE",
        "perche": "e' l'unica parte che il cliente vede: due dei difetti piu' cari li ha "
                  "trovati il fondatore GUARDANDO il sito, non un test",
        "moduli": (
            "fase26_ricerca", "fase57_vetrina", "fase61_localizzazione", "fase63_recensioni",
            "fase74_sensory_engine", "fase107_traduzione_annunci", "fase113_messaggistica",
            "fase117_wishlist", "fase121_geo_ricerca", "fase123_web_push",
            "fase129_traduzione_recensioni", "fase137_fedelta_guest", "fase139_chatbot_guest",
            "fase166_geocoder", "fase175_poi_osm",
        ),
        "attrezzi": ("occhio", "plausibilita", "e2e", "produzione"),
        "finito_quando": (
            "nessun testo resta congelato in italiano dove la pagina dichiara 8 lingue "
            "(restano ~1034 parole non tradotte)",
            "ogni numero mostrato ha senso nel mondo vero (modo di rompersi 10)",
        ),
    },
    {
        "ordine": 7,
        "nome": "HOST: PANNELLO E OPERATIVITA'",
        "perche": "senza host non c'e' prodotto: il primo host vero e' il prossimo passo "
                  "di business, e non deve trovare un pannello che lo confonde",
        "moduli": (
            "fase70_turnover", "fase72_digital_twin", "fase75_guardian_engine",
            "fase78_sleep_guarantee", "fase88_registro_host", "fase109_referral_host",
            "fase115_dashboard_metriche", "fase141_onboarding_wizard",
        ),
        "attrezzi": ("occhio", "e2e", "produzione", "finti_verdi"),
        "finito_quando": (
            "un host si iscrive, carica un annuncio e incassa SENZA che nessuno lo aiuti",
            "il pannello dice sempre la verita' sui suoi soldi (nessun saldo stimato)",
        ),
    },
    {
        "ordine": 8,
        "nome": "INFRASTRUTTURA E COMUNICAZIONI",
        "perche": "e' il pavimento: se cede, tutto il resto e' irraggiungibile e nessuno "
                  "dei blocchi sopra conta piu' niente",
        "moduli": (
            "fase13_protocollo_finale", "fase16_outbox", "fase23_datastore", "fase28_gateway",
            "fase29_backpressure", "fase37_notifiche", "fase38_backup", "fase39_whatsapp",
            "fase42_observability", "fase60_mcp_server", "fase81_bootstrap_casavip",
            "fase83_server", "fase86_email", "fase178_watchdog",
        ),
        "attrezzi": ("produzione", "gare", "finti_verdi", "stati_impossibili", "e2e"),
        "finito_quando": (
            "il salvataggio e' stato RIPRISTINATO e letto, non solo prodotto",
            "il deploy passa sempre dal protocollo D17, mai a mano",
            "una sentinella ESTERNA (non nostra) si accorge se il sito muore",
        ),
    },
    {
        "ordine": 9,
        "nome": "CRESCITA E MARKETING",
        "perche": "vale solo dopo che la macchina regge: portare gente su un prodotto "
                  "rotto moltiplica il danno invece del guadagno",
        "moduli": (
            "fase24_channels", "fase48_advertising", "fase68_niche_profiler", "fase76_viral_loop",
            "fase77_portability", "fase89_jurisdiction_outreach", "fase90_marketing",
            "fase91_canali_social", "fase92_canale_x", "fase93_canale_tiktok",
            "fase94_scheduler_campagna", "fase95_outreach_email", "fase96_fonte_osm",
            "fase97_inbound_seo", "fase158_domanda", "fase161_domanda_allarme",
            "fase169_indexnow", "fase171_cervello_seo", "fase173_motore_seo",
            "fase193_canale_mastodon", "fase194_canale_bluesky", "fase195_canale_reddit",
            "fase196_video_ai", "fase197_canale_nostr", "fase198_blog",
            "fase200_campagna_persuasiva", "fase201_partner",
        ),
        "attrezzi": ("occhio", "finti_verdi", "produzione"),
        "finito_quando": (
            "nessun canale pubblica senza che una persona possa fermarlo",
            "si pubblica SOLO dove e' lecito (le giurisdizioni le decide fase154)",
        ),
    },
    {
        "ordine": 10,
        "nome": "CORE LEGACY / MANGO",
        "perche": "e' il passato del progetto: qui la domanda giusta non e' «come lo "
                  "collaudo?» ma «perche' esiste ancora?» (DO-178C, terza uscita: il "
                  "codice estraneo si TOGLIE, la sua presenza e' un errore)",
        "moduli": (
            "fase25_brain", "fase27_proposte", "fase30_llm", "fase31_conversazione",
            "fase32_governatore", "fase33_persistenza", "fase40_agente_booking",
            "fase41_admin_panel", "fase46_esploratore", "fase47_venditore", "fase49_ponte_booking",
            "fase50_orchestratore", "fase51_scheduler", "fase52_persistenza_metriche",
            "fase53_healthguard", "fase54_loop", "fase55_bootstrap", "fase56_gateway_tavoli",
            "fase164_pool_ai", "fase165_adattatori_esterni",
        ),
        "attrezzi": ("finti_verdi",),
        "finito_quando": (
            "ogni modulo qui dentro ha UNA delle tre uscite: serve e si collauda · "
            "e' spento e si dice come si accende · e' estraneo e SI TOGLIE",
            "⛔ non si cancella niente prima di aver dimostrato che nulla di vivo lo usa",
        ),
    },
)


# ==============================================================================
# LE MISURE — da qui in giu' non ci sono opinioni, solo conteggi
# ==============================================================================
def moduli_sul_disco(radice=None):
    """I `fase*.py` che ESISTONO davvero. La verita' la dice il disco, non l'elenco."""
    base = radice or RADICE
    try:
        nomi = os.listdir(base)
    except OSError:
        return set()
    return set(
        n[:-3] for n in nomi
        if n.startswith("fase") and n.endswith(".py") and os.path.isfile(os.path.join(base, n))
    )


def moduli_nel_piano():
    """I moduli dichiarati nei blocchi, e quante volte ognuno compare (per G3)."""
    quante = {}
    for b in BLOCCHI:
        for m in b["moduli"]:
            quante[m] = quante.get(m, 0) + 1
    return quante


def moduli_nominati_dai_test(radice=None):
    """Quali moduli compaiono per nome in almeno un `test_*.py`.

    ⚠️ LIMITE DICHIARATO (N1): conta che il NOME compaia, non che il test lo esegua.
    Un modulo puo' essere nominato e restare morto al 94% dentro -- misurato su `fase133`,
    dove la produzione ne raggiunge ~9 righe su 142. Chi legge questo numero deve saperlo,
    altrimenti si costruisce una classifica di rischio su una cifra gonfiata (successo).
    """
    base = radice or RADICE
    try:
        test = [n for n in os.listdir(base) if n.startswith("test_") and n.endswith(".py")]
    except OSError:
        return set()
    visti = set()
    trova = re.compile(r"\bfase\d+\w*")
    for nome in test:
        try:
            with io.open(os.path.join(base, nome), "r", encoding="utf-8", errors="replace") as f:
                for pezzo in trova.findall(f.read()):
                    visti.add(pezzo)
        except OSError:
            continue
    return visti


def attrezzi_mancanti():
    """Strumenti dichiarati obbligatori da un blocco che NON esistono sul disco (G4)."""
    mancano = []
    for chiave, (percorso, _scopo) in sorted(ATTREZZI.items()):
        if not os.path.isfile(os.path.join(RADICE, percorso.replace("/", os.sep))):
            mancano.append((chiave, percorso))
    return mancano


def attrezzi_ignoti():
    """Un blocco che chiede un attrezzo non in cassetta: sbaglio S2 (nomi inventati)."""
    ignoti = []
    for b in BLOCCHI:
        for a in b["attrezzi"]:
            if a not in ATTREZZI:
                ignoti.append((b["nome"], a))
    return ignoti


def stato_del_blocco(b, sul_disco, nominati):
    """Le misure di UN blocco. Nessun giudizio scritto a mano entra qui dentro."""
    moduli = list(b["moduli"])
    esistono = [m for m in moduli if m in sul_disco]
    fantasmi = [m for m in moduli if m not in sul_disco]
    coperti = [m for m in esistono if m in nominati]
    scoperti = [m for m in esistono if m not in nominati]
    return {
        "moduli": len(moduli),
        "fantasmi": fantasmi,
        "coperti": len(coperti),
        "scoperti": scoperti,
    }


def contraddizioni(sul_disco=None):
    """Tutto cio' che rende il piano incoerente con la macchina. Vuoto = coerente.

    ⛔ D18 punto 1 — PRIMA misura se stesso: se sul disco non si vede NESSUN modulo, la
    misura non e' «tutto a posto», e' NON VALIDA, e si dice. Confrontare due elenchi vuoti
    e scrivere «uguali» e' lo sbaglio S1, ed e' gia' successo qui dentro.

    `sul_disco` si puo' passare da fuori per UNA sola ragione: perche' le guardie possano
    iniettare il guasto e vedere questa funzione ROSSA **senza toccare il disco vero**
    (D19: una difesa dev'essere provabile senza aspettare il disastro che la giustifica).
    In esercizio non lo passa nessuno e la verita' la dice il disco.
    """
    if sul_disco is None:
        sul_disco = moduli_sul_disco()
    if not sul_disco:
        return ["MISURA NON VALIDA: non vedo nessun fase*.py in %s. Non giudico." % RADICE]

    problemi = []
    nel_piano = moduli_nel_piano()

    non_classificati = sorted(sul_disco - set(nel_piano))
    if non_classificati:
        problemi.append(
            "MODULI FUORI DA OGNI BLOCCO: %d -> %s"
            % (len(non_classificati), ", ".join(non_classificati)))

    fantasmi = sorted(set(nel_piano) - sul_disco)
    if fantasmi:
        problemi.append(
            "MODULI DICHIARATI CHE NON ESISTONO: %d -> %s"
            % (len(fantasmi), ", ".join(fantasmi)))

    doppi = sorted(m for m, q in nel_piano.items() if q > 1)
    if doppi:
        problemi.append("MODULI IN PIU' DI UN BLOCCO: %s" % ", ".join(doppi))

    for chiave, percorso in attrezzi_mancanti():
        problemi.append("ATTREZZO DICHIARATO E ASSENTE: %s -> %s" % (chiave, percorso))

    for nome, a in attrezzi_ignoti():
        problemi.append("IL BLOCCO «%s» CHIEDE UN ATTREZZO CHE NON ESISTE IN CASSETTA: %s"
                        % (nome, a))

    ordini = [b["ordine"] for b in BLOCCHI]
    if sorted(ordini) != list(range(1, len(BLOCCHI) + 1)):
        problemi.append("L'ORDINE DEI BLOCCHI NON E' 1..%d: %s" % (len(BLOCCHI), ordini))

    return problemi


# ==============================================================================
# LA STAMPA — il racconto lo scrive la macchina, non la chat
# ==============================================================================
def _scheda_stato(condizione):
    """Lo stato di UNA casella, chiesto alla scheda (`collaudi/scheda.py`).

    ⛔ Se la scheda non c'e' o non si carica, la casella resta VUOTA e lo dice: un piano che
    desse per buona una casella senza saper leggere la scheda sarebbe un verde per assenza,
    cioe' il peggiore di tutti (sbaglio S7)."""
    import importlib.util
    try:
        percorso = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scheda.py")
        spec = importlib.util.spec_from_file_location("_scheda_dal_piano", percorso)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        return modulo.stato(condizione)
    except Exception as errore:
        return (False, "la scheda non si legge (%r): senza, nessuna casella vale" % (errore,))


def stampa(breve=False):
    sul_disco = moduli_sul_disco()
    nominati = moduli_nominati_dai_test()

    print("=" * 78)
    print("🧭 IL PIANO DELLA MACCHINA — %d blocchi, %d moduli sul disco"
          % (len(BLOCCHI), len(sul_disco)))
    print("=" * 78)
    print("  I blocchi si lavorano IN ORDINE. Non decide la grandezza: decide il danno")
    print("  che fa un guasto li' dentro. ⛔ Nessun blocco puo' dirsi FINITO finche' gli")
    print("  strumenti non scrivono da soli la loro scheda (pezzo 5 del piano).")
    print("")

    for b in sorted(BLOCCHI, key=lambda x: x["ordine"]):
        s = stato_del_blocco(b, sul_disco, nominati)
        print("-" * 78)
        print(" %2d. %s" % (b["ordine"], b["nome"]))
        print("     perche': %s" % b["perche"])
        print("     moduli: %d   ·   nominati da un test: %d   ·   MAI NOMINATI: %d"
              % (s["moduli"], s["coperti"], len(s["scoperti"])))
        if s["scoperti"]:
            print("     ⛔ nessun test li nomina: %s" % ", ".join(sorted(s["scoperti"])))
        if s["fantasmi"]:
            print("     ⛔ DICHIARATI E INESISTENTI: %s" % ", ".join(sorted(s["fantasmi"])))
        if not breve:
            print("     attrezzi obbligatori:")
            for a in b["attrezzi"]:
                percorso, scopo = ATTREZZI[a]
                print("       · %-18s %s" % (a, scopo))
            print("     e' FINITO quando:")
            # ⛔ LA CASELLA NON E' PIU' UNA COSTANTE. Fino al 2026-08-21 qui c'era
            # `print("       ☐ %s" % c)`: un quadratino VUOTO scritto nel codice, e in tutto
            # il progetto non esisteva nessun `☑`. Cioe' nessun blocco poteva risultare
            # finito **per costruzione**, e il fondatore ha passato settimane a chiedere «il
            # Blocco 1 e' finito?» a una macchina incapace di rispondere.
            # Adesso la spunta la SCHEDA, e solo se: qualcuno l'ha misurata · su QUESTO
            # commit · avendo esaminato piu' di zero cose. Il perche' e' stampato accanto.
            for c in b["finito_quando"]:
                ok, motivo = _scheda_stato(c)
                print("       %s %s" % ("☑" if ok else "☐", c))
                print("         (%s)" % motivo)
        print("")

    print("=" * 78)
    print("⚠️  COSA QUESTO CONTROLLO **NON** GUARDA (dichiarato apposta, D18 punto 3)")
    print("=" * 78)
    print("  · «nominato da un test» NON vuol dire eseguito: conta che il nome compaia.")
    print("    Un modulo puo' essere nominato e morto al 94% dentro (misurato su fase133).")
    print("  · non misura mutazione, copertura di riga, ne' gli esiti degli strumenti.")
    print("  · non giudica i 5 documenti: quello lo fa collaudi/audit_millimetrico.py")
    print("")

    problemi = contraddizioni()
    print("=" * 78)
    if problemi:
        print("⛔ IL PIANO E LA MACCHINA NON COINCIDONO — %d contraddizioni" % len(problemi))
        print("=" * 78)
        for p in problemi:
            print("  · %s" % p)
        print("")
        print("  Non e' burocrazia: un modulo fuori da ogni blocco e' un pezzo di macchina")
        print("  che nessuno ha deciso chi collauda. E' cosi' che nascono i «costruiti e")
        print("  dimenticati» -- qui ne sono gia' stati contati decine.")
        return 1
    print("✅ PIANO COERENTE: ogni modulo sul disco sta in esattamente un blocco,")
    print("   ogni modulo dichiarato esiste, ogni attrezzo obbligatorio e' al suo posto.")
    print("=" * 78)
    return 0


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    return stampa(breve="--breve" in argv)


if __name__ == "__main__":
    sys.exit(main())
