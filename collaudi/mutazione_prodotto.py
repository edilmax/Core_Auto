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
import hashlib
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
    ("fase133_split_quote_uguali.py",
     "        and 0 < n <= MAX_PARTECIPANTI else 0",
     "        and n > 0 else 0",
     "test_fase133_split_quote_uguali",
     "il tetto sui partecipanti torna a non esistere: `n` arriva da una rotta PUBBLICA "
     "(/api/split/preview, nessuna sessione) e la lista si costruisce elemento per "
     "elemento, quindi UNA richiesta da quaranta byte fa allocare memoria lineare in n e "
     "il processo muore. Misurato: 4 milioni -> 34 MB, crescita lineare"),

    # ── IL CALENDARIO PREZZI (fase119) — i tre difetti VERI del 2026-08-13 ─────
    # Il file non aveva NEMMENO UN mutante: i suoi test verdi non erano mai stati
    # giudicati (appendice #12). Questi non sono guasti immaginati, sono i tre
    # difetti misurati sul router vero quel giorno, piu' il quarto che la
    # riparazione stessa aveva introdotto e che un test gia' esistente ha ripreso.
    ("fase83_server.py",
     '                            if isinstance(r, dict))',
     '                            if isinstance(r, dict) and not r.get("chiuso"))',
     "test_calendario_prezzi",
     "l'occupazione torna a non vedere le notti VENDUTE che l'host ha poi chiuso: "
     "un alloggio pieno al 100% risulta mezzo pieno e il prezzo suggerito crolla "
     "del 23,1% (misurato: 14300 -> 11000 su base 10000). L'host abbassa il prezzo "
     "proprio quando e' pieno, ed e' la schermata su cui decide"),

    ("fase83_server.py",
     "        if not celle:",
     "        if False:",
     "test_calendario_prezzi",
     "torna il «200 muto»: un range oltre i 366 giorni, due date invertite o una "
     "stringa che non e' una data ricevono di nuovo 200 con `celle: []`, cioe' la "
     "stessa risposta di «non hai caricato nulla». L'host non puo' sapere di aver "
     "sbagliato a chiedere e guarda un calendario vuoto senza spiegazione"),

    ("fase119_calendario_prezzi.py",
     "                                     giorni_all_arrivo=_distanza(oggi, g), pol=pol)",
     "                                     pol=pol)",
     "test_fase119_calendario_prezzi",
     "i due fattori temporali del motore (last-minute -15%, anticipo +5%) tornano "
     "STACCATI e valgono 10000 per sempre: nella settimana prima dell'arrivo, quando "
     "le OTA svendono, il nostro suggerito resta al prezzo pieno"),

    ("fase119_calendario_prezzi.py",
     "        return d if d >= 0 else 30",
     "        return d",
     "test_fase119_calendario_prezzi",
     "i giorni GIA' TRASCORSI tornano a prendere lo sconto «ultimo minuto»: il motore "
     "legge la distanza negativa come «<= 2 giorni» e sconta del 15% notti che non si "
     "possono piu' vendere. E' il difetto che la riparazione del 2026-08-13 aveva "
     "introdotto, ripreso da `test_prezzo_dinamico_applicato` che esisteva gia'"),

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

    # ── LA LISTA DEI RIMBORSI DOVUTI (2026-08-16) — i quattro freni sul denaro ───
    # Costruita il 16 agosto per chiudere il difetto «la cancellazione dell'ospite non
    # restituisce i soldi». I suoi test erano verdi, ma verde non vuol dire sorvegliato:
    # qui si chiede se, rompendo ogni singolo freno, qualcuno se ne accorge.
    ("fase83_server.py",
     "        if 0 < pagato < dovuto:",
     "        if False:",
     "test_admin_rimborso_money",
     "FRENO 1 SPENTO: la lista propone di restituire PIU' di quanto l'ospite ha versato, "
     "e il bottone resta premibile. La differenza esce dalla nostra cassa, una volta per "
     "ogni riga sbagliata, e nessuno se ne accorge finche' non tornano i conti"),

    ("fase83_server.py",
     '            passi_ok = stato_payout != "pagato"',
     "            passi_ok = True",
     "test_admin_rimborso_money",
     "FRENO 3 SPENTO: si rimborsa l'ospite anche quando il bonifico all'host e' GIA' "
     "partito. La stessa prenotazione viene pagata DUE volte, e la seconda la paghiamo "
     "noi -- e' esattamente la PERDITA PIENA che D16 vieta"),

    ("fase83_server.py",
     '            gia = bool(stripe_ok and int((esito or {}).get("rimborsato_cents") or 0) > 0)',
     "            gia = False",
     "test_admin_rimborso_money",
     "LA VERITA' NON LA DICE PIU' STRIPE: un rimborso gia' partito non viene visto, la "
     "riga resta in lista e l'operatore la ripreme. L'ospite riceve il doppio. E' il "
     "difetto del 16 agosto (database 'rimborsato', Stripe zero) girato al contrario"),

    ("fase83_server.py",
     '                "bottone": (not manca) and not gia}',
     '                "bottone": True}',
     "test_admin_rimborso_money",
     "IL BOTTONE C'E' SEMPRE, anche su una riga a cui manca il pagamento o l'importo: "
     "«un bottone premibile quando non si deve, prima o poi si preme», e quel clic non "
     "restituisce niente mentre fa credere il contrario"),

    ("fase83_server.py",
     '        esito = sp.rimborsa(riga["payment_intent"], int(riga["dovuto_cents"]), "rimborso:" + rif)',
     '        esito = sp.rimborsa(riga["payment_intent"], int(dati.get("importo_cents") or riga["dovuto_cents"]), "rimborso:" + rif)',
     "test_admin_rimborso_money",
     "FRENO 4 SPENTO: l'importo torna a poterlo scegliere CHI CHIAMA LA ROTTA, invece "
     "di essere quello calcolato dalla politica (fase111) e scritto nel giornale. Chi "
     "arriva alla rotta decide quanto esce dalla cassa"),

    ("fase83_server.py",
     '            if riga is not None and not riga.get("gia_rimborsato"):',
     "            if riga is not None:",
     "test_admin_rimborso_money",
     "le prenotazioni GIA' rimborsate tornano in lista: l'operatore le ripreme una per "
     "una, convinto di lavorare su una coda vera"),

    # ── L'ORACOLO E LA CONCORRENZA: i due collaudi che mancavano (5 e 6) ─────────
    # Questi due mutanti esistono per DIMOSTRARE che quei due collaudi vedono davvero il
    # guasto che dicono di vedere. Senza, sarebbero due verdi mai visti rossi.
    ("fase111_cancellazione.py",
     "    rimborso = fee + (soggiorno * bps // 10000)            # pulizia sempre resa",
     "    rimborso = pagato",
     "test_admin_rimborso_money test_fase111_cancellazione",
     "IL MOTORE DEI RIMBORSI SBAGLIA E NESSUNO LO CONFRONTA CON NIENTE: la politica non "
     "conta piu', si restituisce sempre il 100%. Su una 'rigida' a due giorni dall'arrivo "
     "l'host perde tutto cio' che la sua politica gli garantiva. E' il guasto che solo un "
     "SECONDO calcolo indipendente puo' vedere: tutti gli altri test chiedono al sistema "
     "quanto spetta e poi verificano che mostri quel numero -- sbaglierebbero insieme"),

    ("fase83_server.py",
     '        esito = sp.rimborsa(riga["payment_intent"], int(riga["dovuto_cents"]), "rimborso:" + rif)',
     '        esito = sp.rimborsa(riga["payment_intent"], int(riga["dovuto_cents"]), "rimborso:" + rif + str(id(riga)))',
     "test_admin_rimborso_money",
     "LA CHIAVE D'IDEMPOTENZA NON E' PIU' STABILE: ogni richiesta ne porta una diversa, "
     "quindi Stripe non puo' piu' riconoscere il duplicato. Due operatori che premono nello "
     "stesso istante restituiscono i soldi DUE VOLTE all'ospite. E' l'unica rete che "
     "separa due richieste simultanee: il nostro codice, da solo, non le separa"),

    # ── E LE DUE DIFESE DEL REGISTRO (trovate da CodeQL, non da noi) ─────────────
    ("fase83_server.py",
     '    pulito = re.sub(r"[^A-Za-z0-9:_.-]", "", str(rif))[:64]',
     "    pulito = str(rif)",
     "test_admin_rimborso_money",
     "il registro torna a scrivere quello che gli danno: chi passa un riferimento con "
     "un a-capo dentro FABBRICA righe di allarme false nel posto dove il Guardiano "
     "(fase186) guarda ogni giorno per sapere se un guasto sui soldi e' avvenuto"),

    ("fase83_server.py",
     "        if not (isinstance(rif, str) and _RIFERIMENTO_VALIDO.match(rif)):",
     "        if not (isinstance(rif, str) and rif):",
     "test_admin_rimborso_money",
     "la rotta sui soldi torna ad accettare qualunque stringa come riferimento, e a "
     "rimandarla indietro tal quale nella risposta d'errore"),

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


_IMPORTA_CACHE = {}


def _importa_il_modulo(percorso_test, modulo):
    """Il file di test IMPORTA il modulo (`import X`, `import X as Y`, `from X import ...`)?

    Albero sintattico, non sottostringa: un commento, una stringa o un docstring non contano.
    Un file che non si legge o non si analizza risponde False: non e' un errore, e' «non lo
    importa, che io sappia», e finisce nel gruppo di chi lo nomina soltanto. La cache e' per
    percorso e impronta del file (dimensione, ora), perche' il Giudice fa la stessa domanda
    molte volte nello stesso giro.
    """
    try:
        st = os.stat(percorso_test)
        chiave_cache = (percorso_test, modulo, st.st_size, st.st_mtime_ns)
    except OSError:
        return False
    if chiave_cache in _IMPORTA_CACHE:
        return _IMPORTA_CACHE[chiave_cache]
    risposta = False
    try:
        with io.open(percorso_test, encoding="utf-8", errors="replace") as f:
            albero = ast.parse(f.read())
    except (OSError, SyntaxError, ValueError):
        albero = None
    for nodo in ast.walk(albero) if albero is not None else ():
        if isinstance(nodo, ast.Import):
            if any(a.name == modulo or a.name.startswith(modulo + ".") for a in nodo.names):
                risposta = True
                break
        elif isinstance(nodo, ast.ImportFrom):
            if nodo.module == modulo or (nodo.module or "").startswith(modulo + "."):
                risposta = True
                break
    _IMPORTA_CACHE[chiave_cache] = risposta
    return risposta


def scegli_sorveglianti(sorveglianti, tetto, modulo, radice=None):
    """Quali occhi accendere fra i sorveglianti, e in che ordine: (scelti, dedicato).

    ⛔ FINO AL 2026-09-03 ERANO I PRIMI `tetto` IN ORDINE ALFABETICO. `test_che_nominano` elenca
    chi contiene il NOME del modulo (sottostringa: basta un commento), in ordine alfabetico, e
    le due porte del Giudice ne prendevano i primi sei (`--modulo`) o otto (`--diff`). Misurato
    sui cinque moduli del percorso del denaro: su `fase85_pagamenti_stripe` il test dedicato
    era il 29o su 84, su `fase87_stripe_webhook` il 24o su 63 -- FUORI dai sei -- e i sei
    accesi erano test di bombardamento e benchmark. Un giro cosi' produce sopravvissuti
    credibili e senza significato; e, peggio, un verdetto verde che la scheda registrava come
    «misurato e passato».

    IL CRITERIO, in tre gruppi, alfabetico dentro ognuno, tetto invariato:
      1. il test DEDICATO `test_<modulo>`, se e' fra i sorveglianti: e' l'ancora;
      2. chi IMPORTA il modulo (albero sintattico, `_importa_il_modulo`): puo' vederne il guasto;
      3. chi lo NOMINA soltanto (commento, stringa, docstring, o un file che non si analizza).
    `dedicato` e' il nome del test dedicato se c'e', altrimenti None: chi chiama decide cosa
    farne (`giro_su_moduli` dichiara il modulo NON GIUDICABILE; `giro_sul_diff` lo conta in
    `rinunce["senza_dedicato"]`). Con `--killer` questa funzione non decide niente: gli occhi
    li ha scelti una persona, e il giro lo stampa (SCELTI A MANO).

    ⚠️ Limite dichiarato (D18 punto 3): «importa» e' l'import diretto. Un test che carica il
    modulo con importlib, o lo esercita attraverso un altro modulo, sta nel gruppo 3: non e'
    escluso, viene dopo. E l'ordine dentro un gruppo resta alfabetico, cioe' non guarda il
    costo: quello lo misura `misura_normale`, e si governa con `--killer`.
    """
    radice = radice or REPO
    dedicato = "test_" + modulo
    ancora = [t for t in sorveglianti if t == dedicato]
    importano, nominano = [], []
    for t in sorveglianti:
        if t == dedicato:
            continue
        if _importa_il_modulo(os.path.join(radice, t + ".py"), modulo):
            importano.append(t)
        else:
            nominano.append(t)
    return (ancora + importano + nominano)[:tetto], (dedicato if ancora else None)


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
# ⛔⛔ NON DICHIARATI, E VOLUTAMENTE — `fase188_paga_struttura.calcola`, righe 118 e 120
#     (`if comm + fee + gateway > anticipo:`, `>` -> `>=`), trovati SOPRAVVISSUTI da un giro
#     vero il 2026-08-21.
#
#     Sono **dimostrati equivalenti con z3** (`unsat` su ogni comm>=0, fee>=0, gateway>=0 e
#     qualunque anticipo; controprova: togliendo `fee >= 0` il controesempio salta fuori
#     subito, comm=1 fee=-2 gateway=0 anticipo=-1, quindi il modello e' vivo). La ragione:
#     `>` e `>=` differiscono solo quando la somma **eguaglia** l'anticipo, e li'
#     l'assegnamento diventa `fee = max(0, fee)` -- identita', perche' fee >= 0 per
#     costruzione. Idem per `comm`.
#
#     ⛔ E TUTTAVIA NON SI DICHIARANO, perche' DUE guardie di questo schedario li rifiutano,
#     ed hanno ragione tutt'e due:
#       1. `TestLoSchedarioDegliEquivalenti_5`: le righe 118 e 120 hanno **testo identico**
#          nella **stessa funzione**, quindi la chiave (file/funzione/riga/vecchio/nuovo)
#          non le distingue: **una prova spegnerebbe due punti**. La guardia lo chiama «la
#          stessa famiglia del difetto del 2026-08-01, un passo piu' in fondo».
#       2. `TestLoSchedarioDegliEquivalenti_3`: la firma e' `calcola(prezzo_cents: Any, ...)`,
#          e un dominio dichiarato su interi e' **piu' piccolo** di cio' che la funzione
#          accetta (per esempio una sottoclasse di `int`).
#
#     💡 Quindi restano SOPRAVVISSUTI, che e' esattamente cio' che B6 prescrive quando la
#     dimostrazione non e' dichiarabile: «o c'e' una dimostrazione, o quel mutante resta
#     sopravvissuto». **Restare sopravvissuti e' la scelta sicura**; forzare la voce avrebbe
#     richiesto di cambiare la CHIAVE (farle portare la posizione) e il criterio del dominio
#     -- due lavori veri, e questo e' l'unico posto del progetto dove un errore diventa
#     cecita' permanente.
#     📌 IL LAVORO CHE SERVE, per chi riprende: **far portare alla chiave la POSIZIONE** del
#     punto (riga+colonna), non solo il testo. Chiude questa famiglia di difetti per
#     costruzione, come la chiave della scheda il 2026-08-21.
EQUIVALENTI_DICHIARATI = {
    # ⛔ QUI STAVANO DIECI VOCI SCRITTE E TOLTE LO STESSO GIORNO (2026-09-05, Blocco 2 casella 4):
    #    2 in fase62 (z3 ed esaustiva), 6 in fase58 e 2 in fase111 (traccia). Avevano tutte la
    #    stessa forma -- un controllo RIDONDANTE nella stessa funzione mascherava il solo valore
    #    in cui sano e guasto differivano -- e col «autorizzato» del fondatore quelle righe sono
    #    state RISCRITTE con una condizione sola (`n < 1`, `max(0, rowcount)`, quattro controlli
    #    separati in `prima_finestra`, `rate_bps < 1`, `max(v, 0)`): ogni mutante e' tornato
    #    uccidibile e le voci non servono. E' la strada del METODO (18.1): «o diventa un test
    #    nuovo, o e' codice da cancellare» -- mai una cecita' dichiarata quando si puo' evitare.
    ("fase184_marca_temporale.py", "_der_intero", "if valore < 0:", "<", "<="): {
        "ancore": ["if valore < 0:"],
        "impronta": "047e9643f6d6c25eba35f57816c8f34750e6565cba43b0ebe7407ad685f5b365",
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
        "ancore": ["mx = z3.If(a1 > b1, a1, b1)"],
        "impronta": "be81af356e54e93367c79ec225b3d63b5ad0acff7f67afa9709628bf44e6c2ed",
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
        "ancore": ["mn = z3.If(a2 < b2, a2, b2)"],
        "impronta": "bc5c197bf2c854bd178f2a6c10f3a8d104e3b5502898cb964c24bffd626eda4b",
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
        "ancore": ["if residuo <= 0:"],
        "impronta": "9e4a0c032966425e8db1641806eb078707559545993a7d5ad098c20eec98dfdf",
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
        "ancore": ["if not pid or pid == rif_deb or disp <= 0:"],
        "impronta": "2656e6b7159039721402e46ed06f5a7e413166ae770e128b409ce8209cafbb83",
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
        "ancore": ["and offset >= 0) else 0"],
        "impronta": "143d9e6e93494a8ef70df7f88f7a20c5d931e763f9c702c89f7cb1bf9ff9571d",
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
        "ancore": ["if tipo not in (\"credito\", \"debito\") or imp <= 0 or not (riferimento and soggetto"],
        "impronta": "c12186ee6d1e898621535ece534acf10637f5fdde552e53fcc7737ac4553a155",
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
        "ancore": ["if imp <= 0 or not (riferimento and host_id):"],
        "impronta": "0b406b29cc13b0d20f036baff706760d57cbc39fafa78d01cff6cb50e6d8c1a6",
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
        "ancore": ["if residuo <= 0:"],
        "impronta": "9e4a0c032966425e8db1641806eb078707559545993a7d5ad098c20eec98dfdf",
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
        "ancore": ["if len(self._m) <= self._max_chiavi:"],
        "impronta": "2db19ba265b9fecd22091aed2052deeda5d104272df71afec9eaeab568f603cf",
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
        "ancore": ["if piu_recente is None or m > piu_recente:"],
        "impronta": "1dfc39597bb39465387cccd65400eabc161f44e72d34ce6cebd7c0f5d3337c1e",
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
        "ancore": ["print(json.dumps(r, ensure_ascii=False))"],
        "impronta": "84181110a44db49241ee1107277ba2a8ae39907f5930de7948a0eab00a154346",
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
        "ancore": ["if not pid or pid == riferimento or disp <= 0:"],
        "impronta": "10307fab9d6d6858d9e4f4bf28dbe00d3cfc897b7b0e48b93db02e1cc0289e77",
        "metodo": "traccia",
        "dominio": "il solo caso che differisce, `disp == 0`, seguito fino allo stato "
                   "finale (`disp` viene da `_cent`, che non e' mai negativo).",
        "data": "2026-08-02",
        "prova":
        "`disp = _cent(r.get('minori'))` non e' mai negativo, quindi `disp < 0` e' sempre "
        "falso e l'unico caso che differisce e' disp == 0: si prosegue con quota = 0 e si "
        "arriva allo stesso `registra` che rifiuta pulito. Nessuna differenza osservabile.",
    },

    # ══════════════════════════════════════════════════════════════════════════════
    # fase59_concierge — i SOPRAVVISSUTI del giro del 2026-08-24 (B5)
    # ──────────────────────────────────────────────────────────────────────────────
    # Giro veloce sui 114 punti del motore che calcola OGNI prezzo: 106 uccisi, 8 vivi.
    # Nessuno dei 7 qui sotto e' un buco: sono operatori che differiscono in UN SOLO
    # punto, e in quel punto lo stato osservabile e' IDENTICO. Il giro completo da 4 ore
    # non li avrebbe uccisi -- un mutante equivalente non lo uccide nessuno.
    #
    # ⛔ L'OTTAVO NON E' QUI, ED E' LA COSA PIU' IMPORTANTE DI QUESTO BLOCCO.
    # Il sopravvissuto di riga 299 (`_ss > 0` -> `>=`) e' equivalente quanto gli altri, ma
    # la sua chiave e' INDISTINGUIBILE da quella dell'altro `>` della STESSA riga:
    #     _bps = _sm if (_nn >= 28 and _sm > 0) else (_ss if (_nn >= 7 and _ss > 0) else 0)
    # Due operatori, stesso file, stessa funzione, stesso testo di riga, stesso `>`->`>=`:
    # una sola voce li dichiarerebbe CIECHI TUTTI E DUE. E il primo (`_sm > 0`) NON e'
    # equivalente -- e' un difetto vero sui soldi (un soggiorno da 28+ notti perderebbe lo
    # sconto settimana quando l'host non ha dichiarato quello mese), ucciso oggi da
    # `test_fase59_concierge.TestSogliaSoggiornoLungo.
    # test_a_VENTOTTO_notti_senza_sconto_mese_vale_quello_settimana`.
    # E' la stessa famiglia del difetto del 2026-08-01 (la chiave che non portava la
    # funzione): una chiave che non distingue due punti li dichiara insieme. Quel
    # sopravvissuto resta VIVO e il giro resta rosso finche' la chiave non sa dire QUALE
    # operatore della riga. Meglio un rosso che una cecita'.

    # ⛔ QUI STAVA LA VOCE `quota` / `if _bps > 0:` / `>` -> `>=` del 2026-08-24. Il 2026-09-05
    #    la riscrittura dello sconto soggiorno-lungo (l'«autorizzato» del fondatore) l'ha fatta
    #    DECADERE -- l'ancora non c'era piu', controllo 2b, come deve -- e invece di rifarla
    #    quella riga e' diventata `sconto_lungo = netto_listino * max(_bps, 0) // 10000`:
    #    nessun confronto da mascherare, nessuna voce da tenere.
    ("fase59_concierge.py", "quota", "if not _intero(comm) or comm < 0:", "<", "<="): {
        "ancore": ["if not _intero(comm) or comm < 0:\ncomm = 0"],
        "impronta": "178e4c87509e3b4b345a1b7d3b588dbcc259187b777b6e8b495ccab64c3fb0a2",
        "metodo": "traccia",
        "dominio": "tutti gli interi che `comm` puo' assumere a quella riga (il ramo "
                   "`not _intero(comm)` e' invariato: la mutazione tocca solo il secondo "
                   "operando dell'`or`).",
        "data": "2026-08-24",
        "prova":
        "DIMOSTRATO PER ESAURIMENTO. `<` e `<=` differiscono solo per comm == 0. In quel "
        "punto il corpo esegue `comm = 0` su una variabile che vale gia' 0: assegnazione "
        "idempotente, stato invariato. Per ogni altro intero le due condizioni coincidono. "
        "Non c'e' niente da distinguere.",
    },

    ("fase59_concierge.py", "quota", "if comm > netto:", ">", ">="): {
        "ancore": ["if comm > netto:\ncomm = netto"],
        "impronta": "7995ee8a4fa2f54a8185c616ef20ade52374654a36613fe184ae910e793dec34",
        "metodo": "traccia",
        "dominio": "ogni coppia di interi (comm, netto) che arriva a questa riga.",
        "data": "2026-08-24",
        "prova":
        "DIMOSTRATO PER ESAURIMENTO. Le due condizioni differiscono solo per comm == netto. "
        "In quel punto il corpo esegue `comm = netto`, cioe' riassegna a `comm` il valore "
        "che ha gia'. Assegnazione idempotente: stato identico. Per comm > netto e "
        "comm < netto le due condizioni danno lo stesso esito.",
    },

    ("fase59_concierge.py", "quota", "tassa = t if (_intero(t) and t >= 0) else 0", ">=", ">"): {
        "ancore": ["tassa = t if (_intero(t) and t >= 0) else 0"],
        "impronta": "7500f33b81264b1b7021b02862cea9348a12d20d928ed5465d8743e3366fab33",
        "metodo": "traccia",
        "dominio": "tutti i valori che `self._tassa_all(...)` puo' restituire; il ramo "
                   "`_intero(t)` e' invariato, quindi il dominio residuo sono gli interi.",
        "data": "2026-08-24",
        "prova":
        "DIMOSTRATO PER ESAURIMENTO. `>=` e `>` differiscono solo per t == 0. In quel punto "
        "l'originale assegna `tassa = t`, cioe' 0; la versione mutata prende il ramo `else` "
        "e assegna `tassa = 0`. Stesso valore, stesso tipo (int). Nessun ingresso puo' "
        "distinguerle. ⚠️ Vale perche' l'oggetto e' un int: se un domani `t` potesse essere "
        "un numero con identita' osservabile (Decimal, un bool, un intero con sottoclasse), "
        "questa dichiarazione andrebbe rifatta -- ed e' per questo che l'ancora tiene la "
        "riga intera, `_intero(t)` compreso.",
    },

    ("fase59_concierge.py", "quota",
     "costo_pagamento = (totale * _psp) // 10000 + (self._psp_fisso if totale > 0 else 0)",
     ">", ">="): {
        "ancore": ["guest = netto - sconto\nif guest <= 0 or guest > MAX_CENTS:\n"
                   "return RispostaConcierge(422, {\"errore\": \"prezzo_fuori_banda\"})",
                   "totale = guest + tassa",
                   "costo_pagamento = (totale * _psp) // 10000 + "
                   "(self._psp_fisso if totale > 0 else 0)"],
        "impronta": "126b86f75de2ade43a11552bb8b2ffe52919df067f7ecb46cda4d509f289a1ad",
        "metodo": "traccia",
        "dominio": "tutti i valori che `totale` puo' assumere a questa riga, ricavati dalle "
                   "due righe che lo costruiscono, NON supposti.",
        "data": "2026-08-24",
        "prova":
        "DIMOSTRATO PER ESAURIMENTO SUL DOMINIO RESIDUO. `>` e `>=` differiscono solo per "
        "totale == 0, e a questa riga totale == 0 e' IRRAGGIUNGIBILE: `guest <= 0` esce con "
        "422 `prezzo_fuori_banda` (ancora 1), quindi guest >= 1; `tassa` e' un intero >= 0 "
        "per la riga sopra; `totale = guest + tassa` >= 1. Sul dominio residuo le due "
        "condizioni coincidono. "
        "⚠️ NON e' un «oggi non si raggiunge» alla D19: la premessa sta nella STESSA "
        "funzione, venti righe sopra, ed e' inchiodata da due guardie esistenti che "
        "pretendono quel 422 (`test_fase59_concierge.py` TestBandeDelPrezzo e "
        "`test_copertura_critica.py` test_prezzo_fuori_banda_e_rifiutato). Se qualcuno "
        "togliesse quel rifiuto, quelle due diventerebbero rosse lo stesso giorno -- e "
        "l'ancora 1 sparirebbe, facendo decadere questa dichiarazione da sola.",
    },

    ("fase59_concierge.py", "_sconto_credito",
     "if not (isinstance(token, str) and token):", "and", "or"): {
        "ancore": ["if not (isinstance(token, str) and token):\nreturn 0, \"\"",
                   "v = self._firma.decodifica(token)\n"
                   "if not isinstance(v, dict) or v.get(\"tipo\") != \"credito_fondatore\":\n"
                   "return 0, \"\"",
                   "if not isinstance(token, str) or token.count(\".\") != 1:\nreturn None"],
        "impronta": "5303e803add23bca14bd7ac1d3f09a6092c35875af4c90eeeb6e9e16e0f8aac4",
        "metodo": "traccia",
        "dominio": "qualunque oggetto Python possa arrivare come `token` "
                   "(`richiesta.get(\"credito_token\")`, cioe' JSON dell'ospite: nessun "
                   "tipo garantito). Si divide in quattro classi sui due predicati.",
        "data": "2026-08-24",
        "prova":
        "DIMOSTRATO PER CASI, sulle quattro combinazioni di A = isinstance(token, str) e "
        "B = bool(token). Con A e B veri, o con tutti e due falsi, `and` e `or` danno lo "
        "stesso esito: le due versioni sono la stessa riga. Restano le due classi che "
        "divergono, e in tutte e due la versione mutata PROSEGUE invece di uscire subito: "
        "(1) token == \"\" (stringa ma falsa) e (2) token non-stringa ma vero (123, [1], "
        "un oggetto). In tutte e due arriva a `v = self._firma.decodifica(token)`. E "
        "`FirmaQuote.decodifica` e' TOTALE (ancora 3): la sua prima riga e' "
        "`if not isinstance(token, str) or token.count(\".\") != 1: return None` -- per un "
        "non-stringa torna None, e per \"\" torna None perche' \"\".count(\".\") == 0 != 1. "
        "Quindi v is None, la riga dopo trova `not isinstance(v, dict)` vero e fa "
        "`return 0, \"\"`: ESATTAMENTE il valore di ritorno dell'originale. Nessuna "
        "eccezione, nessuno stato toccato in mezzo (decodifica non scrive niente), nessun "
        "ingresso puo' distinguere le due versioni.",
    },

    ("fase59_concierge.py", "_sconto_credito",
     "cr = cr if (_intero(cr) and cr > 0) else 0", ">", ">="): {
        "ancore": ["cr = cr if (_intero(cr) and cr > 0) else 0"],
        "impronta": "54201e4c436a921c27005fa49caf6fc5a9d68f0f8f01bfcdbc44b6be016627d1",
        "metodo": "traccia",
        "dominio": "tutti i valori di `cr = v.get(\"credito_cents\", 0)`; il ramo "
                   "`_intero(cr)` e' invariato, quindi il dominio residuo sono gli interi.",
        "data": "2026-08-24",
        "prova":
        "DIMOSTRATO PER ESAURIMENTO. `>` e `>=` differiscono solo per cr == 0. In quel punto "
        "l'originale prende il ramo `else` e assegna 0; la versione mutata assegna `cr`, che "
        "vale 0. Stesso valore, stesso tipo. E il valore prosegue in "
        "`min(cr, margine_disponibile)`, che su 0 da' 0 in entrambe: nessuna differenza "
        "osservabile nemmeno a valle.",
    },

    ("fase85_pagamenti_stripe.py", "crea_link_anticipo",
     "and saldo >= 0) else 0", ">=", ">"): {
        "ancore": ["saldo = dati.get(\"saldo_cents\")\n"
                   "saldo = saldo if (isinstance(saldo, int) and not isinstance(saldo, bool)\n"
                   "and saldo >= 0) else 0",
                   "(\"metadata[saldo_cents]\", str(int(saldo))),"],
        "impronta": "39234f7d8340f748160390037f186285232d94867b0629f46e66b959b022eae1",
        "metodo": "esaustiva",
        "dominio": "qualunque valore di `saldo = dati.get(\"saldo_cents\")` (dati del chiamante, "
                   "nessun tipo garantito). I due rami `isinstance` sono invariati e scartano "
                   "tutto cio' che non e' un intero non-bool; il dominio residuo sono gli interi, "
                   "e su di essi `>=` e `>` differiscono in UN SOLO punto: saldo == 0.",
        "data": "2026-09-04",
        "prova":
        "DIMOSTRATO PER ESAURIMENTO il 2026-09-04 (giro col solo test dedicato: 60 punti, 59 "
        "uccisi, questo il solo vivo). Lo specchio della voce di `_sconto_credito` in fase59. "
        "Per saldo == 0 l'originale prende il ramo `if` e assegna `saldo`, cioe' 0; la versione "
        "mutata prende il ramo `else` e assegna 0. Stesso valore, stesso tipo (int). Per ogni "
        "altro intero le due condizioni coincidono. Il valore prosegue solo in "
        "`str(int(saldo))` nei metadata (ancora 2), che su 0 da' \"0\" in entrambe: nessuna "
        "differenza osservabile nemmeno a valle, nessuna eccezione, nessuno stato toccato. "
        "La guardia `test_riga292_296_313_319_327_...` di test_fase85_pagamenti_stripe pretende "
        "gia' `saldo_cents=0` per None, stringa, float, negativo e bool: se qualcuno cambiasse "
        "il ramo `else` o l'uso a valle, quella guardia o queste ancore decadrebbero lo stesso "
        "giorno e questa dichiarazione andrebbe rifatta.",
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


def impronta_di(ancore):
    """L'impronta di una dimostrazione: sha256 dei BLOCCHI di codice su cui poggia.

    Ogni `ancora` e' un blocco di righe del sorgente, gia' ripulite dei margini e unite da
    `\\n`. Un blocco, non una riga sola: `comm = 0` da sola comparirebbe in mezzo file e la
    presenza non direbbe niente, mentre `if not _intero(comm) or comm < 0:\\ncomm = 0` sta
    in un posto solo.
    """
    return hashlib.sha256("\n\n".join(ancore).encode("utf-8")).hexdigest()


def ancore_intatte(voce, righe):
    """La dimostrazione poggia ANCORA sul codice su cui e' stata fatta? (ok, motivo)

    ⛔ ORDINE DEL FONDATORE, 2026-08-24, ed e' la condizione con cui questo schedario e'
    stato riaperto: *«ogni voce deve portare l'impronta esatta della riga a cui si
    riferisce: se quella riga cambia, la dichiarazione di equivalenza decade DA SOLA e il
    mutante torna da uccidere»*.

    Il perche' e' il difetto peggiore che questo schedario possa avere. Una dimostrazione
    non parla mai della sola riga mutata: parla anche delle righe che la circondano. Il
    mutante di `costo_pagamento` e' equivalente **perche' venti righe sopra un `422`
    impedisce a `totale` di valere 0**. Togli quel `422` e la dimostrazione crolla -- ma la
    chiave dello schedario (file, funzione, testo della riga, vecchio, nuovo) resta identica,
    quindi il mutante continuerebbe a essere saltato **per sempre e in silenzio**. E' la
    cecita' permanente che questo posto puo' produrre, e la chiave da sola non la ferma.

    Due controlli, e servono tutti e due:
      1. ogni ancora e' ANCORA nel file, alla lettera (se una riga cambia, sparisce);
      2. l'impronta dichiarata coincide con quella calcolata sulle ancore (se qualcuno
         allarga l'elenco delle ancore senza rifare la prova, il conto non torna).

    ⛔ E il fallimento e' SICURO NELLA DIREZIONE GIUSTA: la voce decade, il mutante torna
    da uccidere. Mai il contrario.
    """
    ancore = voce.get("ancore")
    if not (isinstance(ancore, (list, tuple)) and ancore
            and all(isinstance(a, str) and a for a in ancore)):
        return False, "voce senza ancore: nessuna impronta da verificare"
    if voce.get("impronta") != impronta_di(ancore):
        return (False, "impronta dichiarata %r, calcolata %r: le ancore sono state "
                       "cambiate senza rifare la dimostrazione"
                % (voce.get("impronta"), impronta_di(ancore)))
    testo = "\n".join(r.strip() for r in righe)
    for ancora in ancore:
        if ancora not in testo:
            return False, "il codice su cui poggia la prova non c'e' piu': %r" % (
                ancora.splitlines()[0][:70],)
    return True, ""


def _e_equivalente(percorso, righe, mutante):
    riga = righe[mutante["riga"] - 1].strip() if mutante["riga"] <= len(righe) else ""
    voce = EQUIVALENTI_DICHIARATI.get(
        (os.path.basename(percorso), funzione_di(righe, mutante["riga"]), riga,
         mutante["vecchio"], mutante["nuovo"]))
    # ⛔ L'IMPRONTA SI CONTROLLA PRIMA DI FIDARSI (ordine del fondatore, 2026-08-24).
    if isinstance(voce, dict):
        _ok, _perche = ancore_intatte(voce, righe)
        if not _ok:
            print("::warning title=EQUIVALENZA DECADUTA in %s::riga %s -- %s. Il mutante "
                  "torna da uccidere: la dichiarazione non vale piu'."
                  % (os.path.basename(percorso), mutante["riga"], _perche))
            return None
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
#  ⛔ UNA CASELLA PER WORKTREE, non una per macchina. TEMP e' condiviso da tutti i worktree
#  della stessa macchina: con un nome fisso, `recupera_da_interruzione` di un worktree
#  vedeva i biglietti dell'ALTRO e provava a rimettere a posto file che nel suo albero non
#  erano nemmeno stati toccati, e `rmtree(_TRACCIA)` spegneva la rete del giro del vicino.
#  ⛔ QUESTA FORMULA DEVE RESTARE IDENTICA a quella di `guardia_commit.py`: chi scrive il
#  biglietto e chi lo legge devono guardare nella stessa cartella.
#  ⚠️ Resta un valore di partenza, NON un valore congelato: `_biglietto()` lo rilegge al
#  momento, e i collaudi continuano a sostituirlo (`_traccia_isolata`) come prima.
_RADICE_WORKTREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SUFFISSO_WORKTREE = "".join(c if c.isalnum() else "_"
                             for c in os.path.basename(_RADICE_WORKTREE))
_TRACCIA = os.path.join(tempfile.gettempdir(),
                        "bookinvip_mutazione_in_corso_%s" % _SUFFISSO_WORKTREE)


def _biglietto(percorso):
    """La cartella del biglietto di QUEL file: UN biglietto per FILE, non uno per tutta
    la macchina.

    ⛔ PERCHE' (difetto vivo, 2026-08-14, visto GUARDANDO e non da un controllo). Il
    Giudice puo' girare DENTRO se stesso: `test_mutation_money` esegue un proprio giro su
    `fase162_pagamenti_pendenti.py`, ed e' allo stesso tempo uno dei sorveglianti di un
    giro esterno E parte di OGNI suite da 27 minuti. Con una casella sola, chi finiva per
    primo cancellava il biglietto dell'altro, e da quel momento un file di produzione
    ROTTO non era piu' sorvegliato da nessuno: `guardia_commit.py` rispondeva «via
    libera». Misurato dal vivo, due campioni durante un giro su `fase59`:
        git status -> M fase59_concierge.py · traccia -> fase162_pagamenti_pendenti.py
        fase59 con sha256 DIVERSO           · traccia -> ASSENTE

    ⛔ La chiave e' il FILE, non il processo: cosi' due giri annidati non si pestano
    nemmeno dentro lo stesso processo, e la cosa si puo' mettere alla prova. Se due giri
    rompessero lo STESSO file, `originale.txt` sarebbe comunque lo stesso sorgente sano:
    il ripristino resta corretto.
    ⛔ E si calcola AL MOMENTO, non all'import: i collaudi spostano `_TRACCIA` su una
    cartella usa-e-getta (`_traccia_isolata`), e un valore congelato tornerebbe a puntare
    a quella vera -- cioe' spegnerebbe la rete di una campagna in corso.
    """
    impronta = hashlib.sha256(os.path.abspath(percorso).encode("utf-8")).hexdigest()[:16]
    return os.path.join(_TRACCIA, "giro_" + impronta)


def biglietti_aperti(traccia=None):
    """[(cartella, percorso_quale, percorso_originale)] per OGNI giro aperto.

    ⛔ Comprende anche il formato VECCHIO (i due file direttamente in `_TRACCIA`): un giro
    interrotto PRIMA di questa riparazione resterebbe altrimenti orfano per sempre, e il
    suo file di produzione rotto non lo recupererebbe piu' nessuno.
    """
    radice = traccia or _TRACCIA
    aperti = []
    q_vecchio = os.path.join(radice, "quale.txt")
    o_vecchio = os.path.join(radice, "originale.txt")
    if os.path.exists(q_vecchio) and os.path.exists(o_vecchio):
        aperti.append((radice, q_vecchio, o_vecchio))
    try:
        for nome in sorted(os.listdir(radice)):
            cartella = os.path.join(radice, nome)
            q = os.path.join(cartella, "quale.txt")
            o = os.path.join(cartella, "originale.txt")
            if os.path.isdir(cartella) and os.path.exists(q) and os.path.exists(o):
                aperti.append((cartella, q, o))
    except OSError:
        pass
    return aperti


def _apri_traccia(percorso, sorgente):
    try:
        mio = _biglietto(percorso)
        os.makedirs(mio, exist_ok=True)
        with io.open(os.path.join(mio, "quale.txt"), "w", encoding="utf-8") as f:
            f.write(percorso)
        with io.open(os.path.join(mio, "originale.txt"), "w",
                     encoding="utf-8", newline="") as f:
            f.write(sorgente)
    except OSError:
        pass                      # la rete e' un di piu': non deve impedire il giro


def _tornato_identico(percorso):
    """(uguale, motivo): il file sul disco e' tornato IDENTICO AL BYTE all'originale?

    ⛔ PERCHE' ESISTE (2026-08-17). Il biglietto si stracciava **senza guardare il file**.
    Lo schema e' sempre `_riscrivi_intatto(...)` seguito da `_chiudi_traccia(...)`: se la
    riscrittura SOLLEVA, il `finally` propaga e il biglietto resta (bene). Ma se riscrive
    **byte diversi senza sollevare** -- disco pieno che tronca, fine-riga tradotti, una
    codifica che cambia sotto -- il biglietto spariva lo stesso, `collaudi/guardia_commit.py`
    rispondeva «via libera», e un file di produzione col guasto dentro entrava nel commit
    **con tutti i controlli verdi**.

    Finora a guardare ero io: il 2026-08-17 ho confrontato gli sha256 **a mano, quattro
    volte**. Ha funzionato quattro volte su quattro -- ed e' esattamente cio' che D18
    rifiuta: la domanda non e' «ha barato?», e' «PUO' barare?». *«La memoria umana non e'
    una strategia»* sta scritto in cima a `guardia_commit.py` dal 2026-08-02.

    ⛔ NEL DUBBIO NON SI CHIUDE. Se l'originale o il file non si riescono a leggere, questa
    funzione dice **no**: non e' un verde, e' un controllo che non ha potuto guardare
    (sbaglio S7). Il biglietto resta, e `guardia_commit.py` spiega da se' come toglierlo a
    mano. Un biglietto di troppo costa un minuto; uno di meno costa un guasto in produzione.
    """
    mio = _biglietto(percorso)
    try:
        with io.open(os.path.join(mio, "originale.txt"), encoding="utf-8", newline="") as f:
            atteso = f.read()
    except OSError:
        return (False, "l'originale del biglietto non si legge: non posso dimostrare che il "
                       "file sia tornato quello di prima")
    try:
        adesso = _leggi_intatto(percorso)
    except OSError as errore:
        return (False, "il file non si rilegge (%s): il ripristino non e' dimostrato" % errore)
    a = hashlib.sha256(atteso.encode("utf-8")).hexdigest()
    b = hashlib.sha256(adesso.encode("utf-8")).hexdigest()
    if a != b:
        return (False, "sha256 DIVERSO — atteso %s, trovato %s" % (a[:16], b[:16]))
    return (True, a[:16])


def _chiudi_traccia(percorso=None):
    """Chiude il biglietto di QUEL file, **e solo se il file e' tornato identico al byte**.
    Senza argomento chiude TUTTO -- e resta senza argomento solo dove chiudere tutto e'
    giusto (il recupero, che li ha appena ripristinati tutti).

    ⛔ La cartella madre si toglie SOLO se e' rimasta vuota: se dentro c'e' il biglietto
    di un altro giro, cancellarla spegnerebbe la sua rete. E' esattamente il difetto del
    2026-08-14 (vedi `_biglietto`), e `os.rmdir` fallisce apposta su una cartella piena:
    e' il controllo meccanico, non la buona volonta'.

    ⛔ E DAL 2026-08-17 IL BIGLIETTO NON E' PIU' UNA FORMALITA': si straccia solo dopo aver
    confrontato l'impronta (vedi `_tornato_identico`). Il gancio che serviva c'era gia' --
    `deploy/hooks/pre-commit` chiama `collaudi/guardia_commit.py` -- mancava che il biglietto
    fosse ONESTO. Un pezzo in meno, non uno in piu' (regola ferrea 1).
    """
    try:
        if percorso is None:
            shutil.rmtree(_TRACCIA, ignore_errors=True)
            return
        uguale, motivo = _tornato_identico(percorso)
        if not uguale:
            # ⛔ MAI IN SILENZIO. Il biglietto che resta e' la protezione; senza il grido,
            # chi lavora scopre il blocco al commit e non sa perche'.
            print("::error title=RIPRISTINO NON DIMOSTRATO::%s — %s. Il biglietto resta "
                  "APERTO e il salvataggio restera' bloccato: guarda `git diff HEAD -- %s`."
                  % (os.path.basename(percorso), motivo, percorso))
            print("  ⛔ RIPRISTINO NON DIMOSTRATO su %s: %s" % (percorso, motivo))
            return
        shutil.rmtree(_biglietto(percorso), ignore_errors=True)
        try:
            os.rmdir(_TRACCIA)
        except OSError:
            pass                  # ci sono altri giri aperti: la loro rete resta accesa
    except OSError:
        pass


def recupera_da_interruzione():
    """Se un giro precedente e' stato UCCISO, rimette a posto i file e lo dice.

    Ritorna il PRIMO percorso recuperato (o None), ma li ripristina **TUTTI**: dal
    2026-08-14 i biglietti sono uno per file, e fermarsi al primo lascerebbe rotti gli
    altri -- cioe' rifarebbe il difetto che questa riparazione chiude.

    ⛔ COSA NON FA, dichiarato (D18 punto 3): non distingue un giro **morto** da uno
    **vivo**. Se un giro nuovo parte mentre un altro sta gia' provando un mutante, questo
    recupero gli rimette a posto il file sotto i piedi e gli chiude il biglietto: quel
    mutante viene giudicato sul codice SANO, e l'esito non vale. E' un difetto diverso da
    quello chiuso qui (ragionato il 2026-08-14, **non misurato**), e per chiuderlo servono
    il proprietario scritto nel biglietto e una guardia sua -- non si tocca di slancio.
    Nel frattempo vale la regola: **mai due giri di mutazione insieme.**
    """
    primo = None
    for _cartella, quale, orig in biglietti_aperti():
        try:
            with io.open(quale, encoding="utf-8") as f:
                percorso = f.read().strip()
            with io.open(orig, encoding="utf-8", newline="") as f:
                sorgente = f.read()
            if percorso and os.path.exists(percorso):
                # si riusa l'aiutante che scrive E invalida: due copie della stessa cosa sono
                # un difetto in attesa, e la guardia
                # `test_il_motore_invalida_dopo_OGNI_riscrittura` me l'ha colto qui il
                # 2026-08-01, la terza volta in due giorni.
                _riscrivi_intatto(percorso, sorgente)
                print("::warning title=Giro precedente INTERROTTO::%s era rimasto MUTATO ed "
                      "e' stato rimesso a posto. Un file di produzione con un guasto dentro "
                      "puo' finire in un commit: controlla il diff."
                      % os.path.basename(percorso))
                print("  ⚠️  RECUPERO: %s era rimasto mutato dal giro precedente -> "
                      "ripristinato." % percorso)
                if primo is None:
                    primo = percorso
        except OSError:
            continue
    _chiudi_traccia()          # senza argomento: li abbiamo appena ripristinati TUTTI
    return primo


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
    esiti, rinunce = [], {"oltre_il_tetto": 0, "senza_sorveglianti": 0, "generatore": {},
                          "senza_dedicato": []}
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
        scelti, _dedicato = scegli_sorveglianti(sorveglianti, tetto_test,
                                                os.path.basename(percorso)[:-3])
        if sorveglianti and _dedicato is None:
            # Qui si giudicano RIGHE, non moduli: un test dedicato che manca e' una condizione
            # preesistente e non fa rosso il diff. Ma si CONTA, in un posto che una macchina
            # legge, e il modo --diff ne stampa il numero: una dichiarazione che vive solo in
            # una riga di stampa e' una dichiarazione che nessuno rilegge.
            rinunce["senza_dedicato"].append(percorso)
        bersaglio = " ".join(scelti)
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
                _chiudi_traccia(pieno)      # SOLO il proprio biglietto (2026-08-14)
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


# ═══════════════════════════════════════════════════════════════════════════════════════
#  PEZZO 3 DEL PIANO — LA PRODUZIONE DECIDE COSA VALE LA PENA ROMPERE
# ═══════════════════════════════════════════════════════════════════════════════════════
#  ⛔ PERCHE' ESISTE, misurato su QUESTO commit e non ereditato da nessuno:
#     su 7542 punti di mutazione di tutta la macchina, 1443 (19,13%) stanno in moduli che
#     la produzione NON raggiunge. Non sono punti «difficili da uccidere»: sono punti
#     IMPOSSIBILI da uccidere, e la letteratura lo dice in una riga sola --
#       «Such mutants are unreachable and are unable to infect the program state, thus
#        they can never be killed»   (Mutation Testing Optimisations using the Clang
#        Front-end, arXiv 2210.17215). Stesso criterio in Petrovic & Ivankovic, TSE 2021:
#       «an AST node is eligible for mutation if it is covered by at least one test and if
#        it is not arid».
#     Cioe' un quinto della fatica di ogni giro andava li' dentro a produrre rossi che
#     nessuno puo' chiudere -- e un allarme che non si puo' chiudere si impara a ignorare
#     (regola ferrea 10).
#
#  ⚠️ IL LIMITE, DICHIARATO (D18 punto 3). «Non raggiungibile» NON vuol dire «morto»: un
#     modulo puo' essere SPENTO e accendersi con un gettone. Per questo qui non si cancella
#     niente -- i punti lasciati fuori si CONTANO, si stampano col nome del modulo, e il
#     verdetto li dichiara. Un taglio silenzioso sarebbe esattamente il difetto che questo
#     strumento esiste per trovare.
#
#  ⛔ E «coperto» NON vuol dire «sano»: la stessa fonte avverte che «even when a line of
#     code is covered, it may still conceal faults». Questo filtro sceglie DOVE NON
#     SPRECARE; non dichiara a posto cio' che resta.
#
#  ⚠️⚠️ DOVE QUESTO FILTRO **NON** ARRIVA, misurato il 2026-08-21 e dichiarato invece che
#     taciuto (D18 punto 3) -- perche' «costruito» non vuol dire «collegato» (regola #23):
#       · `giro_su_moduli` (modo `--modulo`) ........... ✅ filtro ATTIVO
#       · modo DI SERIE (`mutazione_prodotto.py` senza argomenti, quello che lancia la
#         batteria) ..................................... ⚪ filtro NON applicato, e NON
#         serve: usa i 60 mutanti scritti a mano di `MUTANTI`, su 17 file, e **zero** di
#         quei file e' fuori produzione (misurato). Ecco perche' la fase 3 della batteria
#         ha impiegato 602s con il filtro e 600s senza: non c'era niente da togliere.
#         ⛔ Quel tempo uguale era la RISPOSTA GIUSTA, non un sintomo -- ed e' stato
#         verificato invece che dato per scontato.
#       · `giro_sul_diff` (modo `--diff`) .............. ⚪ filtro NON applicato, ed e' una
#         SCELTA: nel modo diff si lavora su righe appena scritte, e un modulo che stai
#         scrivendo lo stai accendendo proprio adesso. Filtrarlo direbbe «non ti sorveglio»
#         esattamente mentre lo costruisci. ⚠️ Se un domani si volesse cambiare idea, il
#         posto e' `giro_sul_diff`, e la stessa regola vale: contare e nominare, mai tagliare
#         in silenzio.
def moduli_che_la_produzione_esegue(radice=REPO):
    """(insieme dei moduli vivi, motivo) — chi la produzione raggiunge davvero.

    Si appoggia a `collaudi/raggiungibilita.py`, che cammina sugli import partendo dai
    moduli nominati dal `CMD` del Dockerfile di produzione -- non da un elenco scritto a
    mano (e' la riparazione del 2026-08-18: un ingresso non e' un file sul disco, e' un
    file che l'artefatto CONTIENE e AVVIA).

    ⛔ Se quello strumento non risponde si torna `(None, motivo)` e NON si filtra niente:
    l'assenza di misura non e' mai un permesso a sopprimere. E' lo sbaglio S1 -- il vuoto
    non e' un valore, e' l'assenza di misura.
    """
    percorso = os.path.join(os.path.dirname(os.path.abspath(__file__)), "raggiungibilita.py")
    try:
        spec = importlib.util.spec_from_file_location("_raggiungibilita_per_mutazione",
                                                      percorso)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        vivi, _morti, _tutti = modulo.cammina(radice)
    except Exception as e:
        return None, ("raggiungibilita.py non risponde (%s): NON filtro niente, si muta "
                      "tutto" % e)
    if not vivi:
        return None, ("raggiungibilita.py non ha trovato NESSUN modulo vivo: e' l'assenza "
                      "di misura, non un risultato -- NON filtro niente")
    # ⛔⛔ GLI INGRESSI SONO VIVI PER DEFINIZIONE, E QUI SI SAREBBE ROTTO TUTTO.
    #  `cammina()` elenca i moduli `fase*` RAGGIUNTI dagli import: `main_casavip.py` non e'
    #  fra loro, perche' e' il punto di PARTENZA, non una destinazione. Senza questa riga il
    #  filtro avrebbe saltato in silenzio il file da cui la produzione si accende -- il
    #  modulo piu' vivo che esista -- contandolo fra i «non eseguiti dalla produzione»,
    #  cioe' l'esatto contrario del vero. Trovato scrivendo, prima di innestare. Guardia:
    #  `test_IL_FILTRO_DELLA_PRODUZIONE_NON_PUO_SCARTARE_UN_INGRESSO`.
    vivi = set(vivi) | {n[:-3] for n in modulo.ingressi_veri(radice)}
    return vivi, "raggiungibilita.py: %d moduli vivi (ingressi compresi)" % len(vivi)


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


def giro_su_moduli(nomi, tetto=30, tetto_test=6, minuti=45, killer=None, riconferme=3):
    """La stessa domanda del modo diff, ma su un modulo INTERO scelto per rischio.

    DUE LIMITI, ed entrambi DICONO cosa hanno tagliato (mai un taglio silenzioso):
      · per mutante: 3 volte il tempo NORMALE del gruppo di test, misurato prima di
        cominciare. Piu' lungo di cosi' non e' lentezza: e' un ciclo che non finisce.
      · per giro: `minuti` complessivi. Quando scadono ci si ferma e si stampa quanti punti
        sono rimasti fuori -- un giro che si allunga senza fine non lo guarda piu' nessuno.
    """
    esiti, rinunce = [], {"oltre_il_tetto": 0, "senza_sorveglianti": 0, "generatore": {},
                          "oltre_il_tempo": 0, "normale_sec": {},
                          "riconferme_fatte": 0, "riconferme_fallite": 0,
                          # PEZZO 3: punti NON mutati perche' la produzione non li esegue.
                          # ⛔ Si contano E si nominano: un numero senza nomi non si puo'
                          #    verificare, e «19% di punti in meno» diventerebbe
                          #    indistinguibile da «19% che nessuno ha guardato».
                          "fuori_produzione": 0, "moduli_fuori_produzione": []}
    vivi, perche_vivi = moduli_che_la_produzione_esegue(REPO)
    if vivi is None:
        print("  ⚠️  filtro della produzione SPENTO: %s" % perche_vivi)
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
        # ⛔ PEZZO 3: se la produzione non esegue questo modulo, i suoi punti non sono
        #    difficili da uccidere -- sono IMPOSSIBILI da uccidere (un mutante su codice
        #    mai eseguito non puo' infettare lo stato del programma). Non si mutano, e si
        #    DICHIARANO: il verdetto li conta a parte, non spariscono.
        if vivi is not None and nome[:-3] not in vivi:
            rinunce["fuori_produzione"] += len(mutanti)
            rinunce["moduli_fuori_produzione"].append("%s (%d punti)" % (nome, len(mutanti)))
            print("  ~~~~ %-34s %4d punti NON mutati: la produzione non esegue questo modulo"
                  % (nome, len(mutanti)))
            continue
        sorveglianti = test_che_nominano(percorso)
        righe_testo = sorgente.splitlines()
        fatti_qui = 0
        riconfermati_qui = 0        # quanti «uccisi» sono stati rieseguiti in questo modulo
        # ⛔ GLI OCCHI SI SCELGONO CON UN CRITERIO, NON PER ALFABETO (dal 2026-09-03): prima il
        # test dedicato, poi chi importa il modulo, poi chi lo nomina soltanto -- vedi
        # `scegli_sorveglianti`. Prima erano i primi sei in ordine alfabetico, e su fase85 e
        # fase87 il dedicato restava fuori: sopravvissuti credibili e senza significato.
        # L'ordine dentro un gruppo resta alfabetico e non guarda il COSTO: su fase177 il primo
        # (`test_avvio_e_ripristino`) da solo pesa 76s contro i 32s di tutti gli altri sette
        # insieme. Con `killer` si punta a mano ai test che davvero esercitano quel modulo.
        # ⚠️ UN INSIEME KILLER RIDOTTO VA DICHIARATO, NON SUBITO IN SILENZIO. Meno test = piu'
        #    FACILE sopravvivere: cio' che esce da un insieme ridotto sono CANDIDATI, da
        #    ri-provare contro TUTTI i sorveglianti prima di chiamarlo buco.
        scelti, dedicato = scegli_sorveglianti(sorveglianti, tetto_test, nome[:-3])
        if killer:
            scelti = list(killer)
        elif sorveglianti and dedicato is None:
            # ⛔ D18: SENZA TEST DEDICATO LA SCELTA AUTOMATICA NON HA UN'ANCORA, e il Giudice
            #    non passa in silenzio con occhi presi a caso: il modulo e' NON GIUDICABILE,
            #    col nome e i punti che restano fuori. Chi vuole giudicarlo sceglie gli occhi
            #    con --killer, o scrive test_<modulo>. (Zero sorveglianti e' un'altra cosa:
            #    li' ogni punto e' SCOPERTO, e lo dice il ciclo qui sotto.)
            esiti.append({"file": nome, "riga": 0, "verdetto": "non_giudicabile",
                          "danno": "nessun test dedicato test_%s: gli occhi automatici non "
                                   "hanno un'ancora" % nome[:-3],
                          "nota": "%d sorveglianti, %d punti NON esaminati; --killer o il "
                                  "test dedicato" % (len(sorveglianti), len(mutanti)),
                          "punti": len(mutanti)})
            print("\n%s: NON GIUDICABILE -- nessun test dedicato test_%s fra %d sorveglianti; "
                  "%d punti NON esaminati. Scegli gli occhi con --killer o scrivi il test."
                  % (nome, nome[:-3], len(sorveglianti), len(mutanti)))
            continue
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
        # Quanti degli occhi accesi IMPORTANO il modulo (veri) e quanti lo nominano soltanto
        # (di carta): dichiarato nell'uscita del giro, non in un confronto fatto una volta.
        occhi_veri = sum(1 for t in scelti
                         if _importa_il_modulo(os.path.join(REPO, t + ".py"), nome[:-3]))
        print("\n%s: %d punti mutabili · sorveglianti %d, usati %d%s (occhi veri %d, di carta "
              "%d) · normale %.1fs · tetto %ds"
              % (nome, len(mutanti), len(sorveglianti), len(scelti),
                 " (SCELTI A MANO)" if killer else "", occhi_veri, len(scelti) - occhi_veri,
                 normale, tetto_sec))
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
                _chiudi_traccia(percorso)   # SOLO il proprio biglietto (2026-08-14)
            _v = "non_determinabile" if verde is None else (
                "sopravvissuto" if verde else "ucciso")
            _nota = "%s -> %s" % (m["vecchio"], m["nuovo"])
            # ⛔ PEZZO 2 DEL PIANO: UN «UCCISO» SI RI-CONFERMA, ALTRIMENTI IL PUNTEGGIO E'
            #    GONFIO. Un test instabile che fallisce per conto suo -- il runner sotto
            #    carico, una rotta a tempo, una risorsa contesa -- fa risultare UCCISO un
            #    punto che nessuno sorveglia davvero. Il giro dopo quel punto sopravvive, e
            #    nel mezzo qualcuno ha creduto di avere una rete dove non c'era niente.
            #    Il modo della CI ri-verifica gia' i SOPRAVVISSUTI (3 giri) per non gridare
            #    per un intoppo; qui si guarda il verso opposto, quello che NON grida mai --
            #    ed e' il piu' pericoloso dei due, perche' un falso «ucciso» tace per sempre.
            # ⚠️ E SI DICHIARA IL DENOMINATORE: ri-confermarli tutti raddoppierebbe un giro
            #    da ore, quindi se ne ri-confermano `riconferme` per modulo e si stampa
            #    quanti su quanti. Un campione dichiarato e' una misura; un campione taciuto
            #    e' un punteggio che sembra pieno.
            if _v == "ucciso" and riconfermati_qui < riconferme:
                riconfermati_qui += 1
                rinunce["riconferme_fatte"] = rinunce.get("riconferme_fatte", 0) + 1
                _apri_traccia(percorso, sorgente)
                _riscrivi_intatto(percorso, applica_mutante(sorgente, m))
                try:
                    _di_nuovo, _ = esegui(bersaglio, timeout=tetto_sec)
                finally:
                    _riscrivi_intatto(percorso, sorgente)
                    _chiudi_traccia(percorso)
                if _di_nuovo is not False:      # non l'ha ucciso la seconda volta
                    _v = "incerto"
                    _nota += "  (UCCISO al primo giro, NON al secondo: killer instabile)"
                    rinunce["riconferme_fallite"] = rinunce.get("riconferme_fallite", 0) + 1
                    print("::warning title=«Ucciso» NON RI-CONFERMATO in %s::riga %s -- il "
                          "killer lo uccide solo a volte: quel punto NON e' sorvegliato in "
                          "modo affidabile" % (nome, m["riga"]))
            esiti.append({"file": nome, "riga": m["riga"], "verdetto": _v,
                          "danno": m["danno"], "nota": _nota})
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


# --------------------------------------------------------------------------------------
#  IL VERDETTO DEL GIRO SU MODULI — una funzione pura, perche' si possa GIUDICARE
# --------------------------------------------------------------------------------------
def verdetto_modulo(esiti, rinunce, parziale=False):
    """Dice se un giro `--modulo` esce verde o rosso, e PERCHE'.

    Sta qui, fuori dal blocco `if __name__ == "__main__"`, per una ragione sola: un pezzo
    dentro quel blocco non lo puo' provare nessun test senza lanciare un giro vero da ore.
    Il verdetto del giudice era proprio quel pezzo -- l'unica parte del giudice che nessuno
    giudicava.

    Restituisce `(uscita, motivi)`: `uscita` e' il codice di uscita del processo, `motivi`
    l'elenco in chiaro di cio' che lo rende rosso (vuoto se e' verde).

    ⛔ UN PUNTO LASCIATO FUORI NON E' UN PUNTO SANO. Fino al 2026-08-19 i punti tagliati dal
    tetto, dal tempo o dal timeout dei test venivano stampati e poi IGNORATI dal codice
    d'uscita: un giro col tetto di serie su `fase59_concierge` ne lasciava fuori 84 su 114 ed
    usciva 0. Cioe' il verde di un giro che aveva guardato un quarto della macchina era
    indistinguibile dal verde di un giro completo -- e quel verdetto e' proprio cio' che
    decide se un modulo dei soldi puo' dirsi giudicato (D26).

    `parziale` non e' una scorciatoia, e' una DICHIARAZIONE: un giro corto serve per iterare
    in fretta, e chi lo lancia deve dire che lo e' (`--parziale`). ⛔ E non condona niente di
    cio' che il giro ha TROVATO: un sopravvissuto resta rosso anche in un giro dichiarato
    parziale. Copre i punti non guardati, mai i buchi visti.
    """
    sopravvissuti = [e for e in esiti if e["verdetto"] == "sopravvissuto"]
    scoperti = [e for e in esiti if e["verdetto"] == "scoperto"]
    basi_rosse = [e for e in esiti if e["verdetto"] == "base_rossa"]
    assenti = [e for e in esiti if e["verdetto"] == "assente"]
    indeterminati = [e for e in esiti if e["verdetto"] == "non_determinabile"]
    motivi = []
    if sopravvissuti:
        motivi.append("%d punti SOPRAVVISSUTI: il guasto passa e i test restano verdi"
                      % len(sopravvissuti))
    if scoperti:
        motivi.append("%d punti SCOPERTI: nessun test nomina quel modulo" % len(scoperti))
    if basi_rosse:
        motivi.append("%d moduli con BASE ROSSA: li' nessun punteggio significa niente"
                      % len(basi_rosse))
    if assenti:
        motivi.append("%d moduli ASSENTI: zero misure, non zero problemi" % len(assenti))
    # ⛔ UN «UCCISO» CHE NON SI RI-CONFERMA E' ROSSO, E «--parziale» NON LO CONDONA: non e'
    #    un punto che il giro non ha guardato, e' un punto che il giro credeva di aver
    #    coperto. Un falso «ucciso» e' peggio di un sopravvissuto, perche' non grida mai.
    incerti = [e for e in esiti if e["verdetto"] == "incerto"]
    if incerti:
        motivi.append("%d punti UCCISI SOLO A VOLTE: il killer li uccide al primo giro e non "
                      "al secondo, quindi li' non c'e' una rete affidabile" % len(incerti))
    # ⛔ D18 (2026-09-03): UN MODULO SENZA TEST DEDICATO NON E' GIUDICATO, E NON PASSA IN
    #    SILENZIO. Prima di queste righe il verdetto contava cinque categorie e nessuna sapeva
    #    che il dedicato non era fra gli occhi: un modulo sorvegliato dai sei test sbagliati
    #    usciva pulito e la scheda lo registrava «misurato e passato». Il motivo porta nome e
    #    punti, perche' la scheda lo eredita da qui e chi la apre deve leggere PERCHE'.
    non_giudicabili = [e for e in esiti if e["verdetto"] == "non_giudicabile"]
    if non_giudicabili:
        motivi.append("%d moduli NON GIUDICABILI (%s): senza test dedicato la scelta "
                      "automatica degli occhi non ha un'ancora; sceglili con --killer o "
                      "scrivi test_<modulo>"
                      % (len(non_giudicabili),
                         ", ".join("%s: %s punti fuori" % (e["file"], e.get("punti", "?"))
                                   for e in non_giudicabili)))
    # I punti NON esaminati: rossi quanto gli altri, a meno che il giro si sia dichiarato
    # parziale. Il conto lo tiene gia' `giro_su_moduli`, qui si limita a pretenderlo.
    # ⛔ PEZZO 3 — I PUNTI FUORI PRODUZIONE NON SONO ROSSI, MA UN GIRO CHE HA SALTATO
    #    **TUTTO** NON E' VERDE. Saltare codice che la produzione non esegue e' una scelta
    #    del piano, non un buco: quei mutanti non si possono uccidere per costruzione. Ma
    #    un giro lanciato SOLO su moduli morti non ha misurato niente, e uscire 0 li'
    #    sarebbe il verde per assenza -- lo stesso di «modulo ASSENTE» due righe sopra.
    esaminati = len([e for e in esiti if e["verdetto"] in
                     ("ucciso", "sopravvissuto", "incerto", "non_determinabile")])
    saltati_prod = int(rinunce.get("fuori_produzione", 0))
    if saltati_prod and not esaminati:
        motivi.append(
            "%d punti saltati perche' la produzione non li esegue, e NESSUN punto "
            "esaminato: questo giro non ha misurato niente. Moduli: %s"
            % (saltati_prod, ", ".join(rinunce.get("moduli_fuori_produzione") or ["?"])))
    fuori = (int(rinunce.get("oltre_il_tetto", 0))
             + int(rinunce.get("oltre_il_tempo", 0))
             + len(indeterminati))
    if fuori and not parziale:
        motivi.append(
            "%d punti NON ESAMINATI (oltre il tetto %d · oltre il tempo %d · i test non "
            "hanno finito in tempo %d): un punto lasciato fuori non e' un punto sano, e' un "
            "punto che nessuno ha guardato. Se il giro doveva essere corto, dichiaralo con "
            "--parziale" % (fuori, int(rinunce.get("oltre_il_tetto", 0)),
                            int(rinunce.get("oltre_il_tempo", 0)), len(indeterminati)))
    return (1 if motivi else 0), motivi


# ═══════════════════════════════════════════════════════════════════════════════════════
#  PEZZO 5 DEL PIANO — IL GIUDICE SCRIVE DA SE' LA SUA CASELLA
# ═══════════════════════════════════════════════════════════════════════════════════════
#  Fino al 2026-08-21 la casella era una COSTANTE (`print("☐ %s")`) e in tutto il progetto
#  non esisteva nessun `☑`: nessun blocco poteva risultare finito PER COSTRUZIONE, ed e' il
#  motivo per cui «il Blocco 1 e' finito?» restava senza risposta da settimane. Quel giorno
#  e' nata `collaudi/scheda.py`, che sa leggere e sa registrare -- ma NESSUN attrezzo la
#  scriveva. E' la regola #23 in forma pura: COSTRUITO != COLLEGATO.
def blocco_dei_moduli(nomi, radice=REPO):
    """(ordine del blocco, motivo) per i moduli su cui un giro ha lavorato.

    ⛔ UNA MISURA VALE SOLO PER CIO' CHE HA MISURATO. Le caselle sulla mutazione sono DUE
    (Blocco 1 «soldi» e Blocco 2 «prenotazioni»), e scrivere sempre quella del Blocco 1
    vorrebbe dire dichiarare misurati i soldi dopo un giro fatto sulle prenotazioni.

    ⛔ Se i moduli stanno in blocchi DIVERSI si torna `None`: non si sceglie a maggioranza.
    Un giro misto non ha finito nessuno dei due blocchi, e dirlo e' l'unica cosa vera.
    """
    percorso = os.path.join(os.path.dirname(os.path.abspath(__file__)), "piano.py")
    spec = importlib.util.spec_from_file_location("_piano_blocco", percorso)
    piano = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(piano)
    puliti = {n[:-3] if str(n).endswith(".py") else n for n in nomi if n}
    if not puliti:
        return None, "nessun modulo: non c'e' niente da dichiarare"
    trovati = set()
    for b in piano.BLOCCHI:
        if puliti & set(b.get("moduli") or ()):
            trovati.add(b["ordine"])
    if len(trovati) != 1:
        return None, ("questi moduli stanno in %d blocchi (%s): un giro misto non ha finito "
                      "nessun blocco, e non si sceglie a maggioranza"
                      % (len(trovati), sorted(trovati) or "nessuno"))
    return sorted(trovati)[0], "blocco %d" % sorted(trovati)[0]


def condizione_della_mutazione(radice=REPO, ordine=1):
    """Il TESTO ESATTO della casella che questo strumento puo' spuntare, LETTO dal piano.

    ⛔ NON SI RICOPIA, e non e' pignoleria: la chiave della scheda e' lo sha256 del testo
    normalizzato, quindi una copia con UN carattere diverso non spunterebbe MAI quella
    casella -- e nessuno se ne accorgerebbe, perche' resterebbe «mai misurata», che e'
    indistinguibile dal non aver mai lanciato lo strumento. E' un ROSSO finto: fa rifare
    un lavoro gia' fatto.

    ⛔ E se le candidate non sono ESATTAMENTE una si alza un'eccezione invece di indovinare:
    zero significa che il piano e' cambiato sotto, due che non si sa quale si sta
    misurando. In tutti e due i casi la risposta giusta e' fermarsi.
    """
    percorso = os.path.join(os.path.dirname(os.path.abspath(__file__)), "piano.py")
    spec = importlib.util.spec_from_file_location("_piano_per_mutazione", percorso)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    blocchi = [b for b in modulo.BLOCCHI if b["ordine"] == ordine]
    if len(blocchi) != 1:
        raise ValueError("il piano non ha esattamente un blocco %r: ne ha %d"
                         % (ordine, len(blocchi)))
    candidate = [c for c in blocchi[0]["finito_quando"]
                 if "mutazione" in " ".join(str(c).split()).lower()]
    if len(candidate) != 1:
        raise ValueError(
            "nel blocco %r le condizioni che parlano di mutazione sono %d, non una: non si "
            "indovina quale spuntare. Candidate: %r" % (ordine, len(candidate), candidate))
    return candidate[0]


def scrivi_la_scheda(esiti, rinunce, comando, radice=REPO, percorso=None):
    """Registra nella scheda cio' che QUESTO giro ha misurato. Torna (riga, motivo).

    ⛔ IL DENOMINATORE E' IL CUORE, e qui e' *quanti punti sono stati davvero esaminati* --
    non quanti ne esistono. Un giro che ne ha guardati zero scrive `denominatore=0`, e la
    scheda per costruzione NON lo conta come verde («l'attrezzo non ha esaminato NIENTE,
    quindi il suo esito non e' un giudizio»).

    ⛔ E L'ESITO NON E' «zero sopravvissuti»: e' il VERDETTO INTERO, lo stesso che decide il
    codice d'uscita del giudice. Ricalcolarlo qui con una regola mia farebbe dire verde
    alla scheda mentre il giudice esce rosso -- due giudizi sullo stesso fatto, che e'
    esattamente il difetto che `piano_dei_soldi.py` esiste per trovare.

    ⛔ `percorso` esiste perche' UN COLLAUDO NON USA MAI L'ATTREZZO VERO: senza, le guardie
    scriverebbero dentro `collaudi/scheda.json` e spunterebbero caselle VERE girando dentro
    la suite -- verde perche' un test l'ha scritto, non perche' qualcuno abbia misurato.
    """
    # ⛔ PRIMA si stabilisce DI QUALE BLOCCO parla questo giro, e solo dopo si cerca la sua
    #    casella: le caselle sulla mutazione sono due, e scriverne una a caso vorrebbe dire
    #    dichiarare misurati i soldi dopo un giro fatto sulle prenotazioni.
    ordine, motivo_blocco = blocco_dei_moduli(
        [e.get("file") for e in esiti if e.get("file")], radice)
    if ordine is None:
        return None, "non so a quale blocco appartiene questo giro (%s)" % motivo_blocco
    try:
        testo = condizione_della_mutazione(radice, ordine)
    except Exception as e:
        return None, "non so QUALE casella spuntare (%s): non scrivo niente" % e
    # ⛔⛔ UN GIRO SU UN MODULO NON DICHIARA FINITI VENTIQUATTRO MODULI.
    #  La casella dice «zero punti di mutazione scoperti sul codice che la produzione
    #  ESEGUE» -- cioe' su TUTTO il blocco. Spuntarla dopo un giro su `fase188` (4 punti)
    #  significherebbe dichiarare misurati anche gli altri 23 moduli dei soldi, che nessuno
    #  ha guardato. E' la stessa malattia della chiave condivisa, un piano piu' su.
    #  ⛔ E NON si scrive `esito=False`: direbbe «misurata e non passa», mentre la verita' e'
    #     «non l'ho misurata affatto». Un rosso falso manda a caccia di un guasto che non
    #     esiste, e costa quanto un verde falso (ferrea 10). Non si scrive, e si dice perche'.
    #  ⚠️ I moduli FUORI PRODUZIONE non contano come mancanti: saltarli e' il pezzo 3, cioe'
    #     una scelta dichiarata, non una dimenticanza.
    percorso_piano = os.path.join(os.path.dirname(os.path.abspath(__file__)), "piano.py")
    spec_p = importlib.util.spec_from_file_location("_piano_copertura", percorso_piano)
    piano = importlib.util.module_from_spec(spec_p)
    spec_p.loader.exec_module(piano)
    # ⛔ SU QUALI MODULI SI MISURA QUESTA CASELLA. Un blocco puo' dichiarare un bersaglio
    #    piu' stretto per la mutazione (`moduli_mutazione`): non e' uno sconto, e' il fatto
    #    che la casella parla di QUELLI e il suo testo lo dice. Se non lo dichiara si torna
    #    all'intero blocco, che resta il comportamento severo di serie.
    #    ⚠️ E il bersaglio si legge SEMPRE dal piano, mai da una copia qui dentro: una copia
    #       direbbe il falso il giorno che il piano cambia, ed e' esattamente la malattia che
    #       `condizione_della_mutazione` esiste per impedire sul testo della casella.
    _blocco = [b for b in piano.BLOCCHI if b["ordine"] == ordine][0]
    del_blocco = set(_blocco.get("moduli_mutazione") or _blocco.get("moduli") or ())
    visti = {str(e.get("file", ""))[:-3] for e in esiti if e.get("file")}
    saltati_prod = {str(v).split(" ")[0][:-3]
                    for v in (rinunce.get("moduli_fuori_produzione") or [])}
    mancanti = del_blocco - visti - saltati_prod
    if mancanti:
        return None, ("questo giro ha guardato %d moduli su %d del blocco %d: una casella e' "
                      "una dichiarazione su TUTTO il blocco, e %d moduli non li ha aperti "
                      "nessuno (%s%s). NON scrivo: «non misurata» e' vero, «misurata e non "
                      "passa» sarebbe falso"
                      % (len(del_blocco) - len(mancanti), len(del_blocco), ordine,
                         len(mancanti), ", ".join(sorted(mancanti)[:5]),
                         " ..." if len(mancanti) > 5 else ""))
    dove = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scheda.py")
    try:
        spec = importlib.util.spec_from_file_location("_scheda_per_mutazione", dove)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
    except Exception as e:
        return None, "la scheda non si carica (%s): non scrivo niente" % e
    uscita, _motivi = verdetto_modulo(esiti, rinunce)
    esaminati = len([e for e in esiti if e.get("verdetto") in
                     ("ucciso", "sopravvissuto", "incerto", "non_determinabile")])
    # Il PERCHE' viaggia con l'esito: e' lo stesso elenco di motivi che decide l'uscita del
    # giudice, non una regola ricalcolata qui (un giudizio, un posto solo).
    riga = modulo.registra(testo, esito=(uscita == 0), denominatore=esaminati,
                           comando=comando, ordine=ordine,
                           percorso=percorso if percorso else modulo.SCHEDA,
                           motivo="; ".join(_motivi))
    return riga, ("casella del blocco %d scritta: esito=%s, %d punti esaminati"
                  % (ordine, riga["esito"], riga["denominatore"]))


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
    # `--riconferme N`: quanti «uccisi» per modulo si rieseguono per essere sicuri che il
    # killer li uccida SEMPRE e non solo a volte (pezzo 2 del piano). 0 = nessuno, e allora
    # il giro lo DICHIARA: un punteggio senza ri-conferme e' un punteggio che puo' essere
    # gonfio, e chi lo legge deve saperlo.
    _riconferme = 3
    if "--riconferme" in sys.argv:
        _r = sys.argv.index("--riconferme")
        _riconferme = int(sys.argv[_r + 1])
        _nomi = [n for n in _nomi if n != sys.argv[_r + 1]]
    print("=" * 96)
    print("MUTANTI GENERATI SU MODULI INTERI: %s" % ", ".join(_nomi))
    print("=" * 96)
    _esiti, _rin = giro_su_moduli(_nomi, tetto=_tetto, minuti=_minuti, killer=_killer,
                                  riconferme=_riconferme)
    _sopr = [e for e in _esiti if e["verdetto"] == "sopravvissuto"]
    _scop = [e for e in _esiti if e["verdetto"] == "scoperto"]
    for e in _esiti:
        if e["verdetto"] in ("sopravvissuto", "scoperto", "assente", "non_determinabile",
                             "base_rossa", "non_giudicabile"):
            print("  %-9s %s:%s  %s  (%s)" % (e["verdetto"].upper(), e["file"], e["riga"],
                                              e.get("nota", ""), e["danno"][:46]))
    print("-" * 96)
    _nd = [e for e in _esiti if e["verdetto"] == "non_determinabile"]
    _uccisi = sum(1 for e in _esiti if e["verdetto"] == "ucciso")
    _inc = [e for e in _esiti if e["verdetto"] == "incerto"]
    print("provati: %d · uccisi: %d · SOPRAVVISSUTI: %d · scoperti: %d · equivalenti: %d "
          "· NON DETERMINABILI: %d · UCCISI SOLO A VOLTE: %d"
          % (len(_esiti), _uccisi, len(_sopr), len(_scop),
             sum(1 for e in _esiti if e["verdetto"] == "equivalente"), len(_nd), len(_inc)))
    # ⛔ IL DENOMINATORE DELLE RI-CONFERME, sempre stampato: dice su quanti «uccisi» la
    #    seconda prova e' stata fatta davvero. Senza, «0 sopravvissuti» non si sa se regge.
    print("ri-conferme: %d «uccisi» rieseguiti su %d (chieste %d per modulo) · non "
          "ri-confermati: %d"
          % (_rin.get("riconferme_fatte", 0), _uccisi + len(_inc), _riconferme,
             _rin.get("riconferme_fallite", 0)))
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
    # Un modulo ASSENTE non e' "zero problemi": e' ZERO MISURE. Bastava dimenticare il `.py`
    # nel nome e il giro non esaminava niente e usciva VERDE -- il giudizio piu' severo del
    # progetto ridotto a decorazione da un refuso, e in CI sarebbe passato liscio. Il vuoto
    # non e' un risultato, e' assenza di misura (D18 punto 1: lo strumento prova di essere
    # in condizione di misurare PRIMA di misurare).
    _ass = [e for e in _esiti if e["verdetto"] == "assente"]
    for e in _ass:
        print("::error title=NIENTE DA MISURARE in %s::%s -- il nome del modulo vuole il "
              "suffisso .py (i sorveglianti invece NO)" % (e["file"], e["danno"]))
    # ⛔ PEZZO 3 — I PUNTI SALTATI SI STAMPANO. Un filtro che toglie un quinto del lavoro e
    #    non lo dice e' indistinguibile da un attrezzo che non ha guardato.
    if _rin.get("fuori_produzione"):
        print("  ~~~~ %d punti NON mutati perche' la produzione non esegue quei moduli: %s"
              % (_rin["fuori_produzione"],
                 ", ".join(_rin.get("moduli_fuori_produzione") or [])))
    _uscita, _motivi = verdetto_modulo(_esiti, _rin, parziale="--parziale" in sys.argv)
    for _m in _motivi:
        print("  ROSSO: %s" % _m)
    # ⛔ PEZZO 5 — IL GIUDICE SCRIVE DA SE' LA SUA CASELLA, e lo fa DOPO il verdetto perche'
    #    e' il verdetto che scrive: due giudizi sullo stesso fatto sarebbero il difetto.
    #    ⚠️ Un giro `--parziale` NON scrive: ha guardato una parte per scelta, e una casella
    #    e' una dichiarazione su TUTTO il blocco. Dichiararla da un giro corto sarebbe la
    #    bugia piu' comoda che questo strumento possa raccontare.
    if "--parziale" in sys.argv:
        print("  🗂️  scheda NON scritta: giro dichiarato --parziale, non giudica il blocco")
    else:
        _riga, _perche = scrivi_la_scheda(
            _esiti, _rin, comando="python collaudi/mutazione_prodotto.py " +
            " ".join(a for a in sys.argv[1:] if a))
        print("  🗂️  %s" % _perche)
    sys.exit(_uscita)


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
    if _rinunce.get("senza_dedicato"):
        # Dichiarato col NUMERO, non solo coi nomi: fra tre settimane un conteggio che passa da
        # 1 a 9 si vede, un elenco che si allunga no.
        print("  moduli SENZA test dedicato (occhi scelti fra chi li importa, dichiarati): "
              "%d -- %s" % (len(_rinunce["senza_dedicato"]),
                            ", ".join(_rinunce["senza_dedicato"])))
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
                _chiudi_traccia(percorso)   # SOLO il proprio biglietto (2026-08-14).
                                    # la rete si richiude: una traccia lasciata aperta
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
