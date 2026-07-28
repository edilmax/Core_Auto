"""REGISTRO ANTI-REGRESSIONE AUTO-VERIFICANTE - le guardie dei bug storici sono ancora VIVE.

IL BUCO CHE QUESTO FILE CHIUDE
------------------------------
Il progetto ha decine di bug storici corretti alla radice, ognuno con la sua "guardia vista
ROSSA" (regola aurea del CLAUDE.md). Ma NESSUNO verificava che quelle guardie esistessero
ancora: se un domani qualcuno cancella un file di test, rinomina un metodo in un refactor,
o svuota il corpo di una guardia lasciando un guscio senza asserzioni, il bug torna in
SILENZIO - la suite resta verde perche' il test che avrebbe dovuto gridare non c'e' piu'.
E' il modo di rompersi n.9 del CLAUDE.md ("il cuore cambia, le guardie restano sul vecchio")
applicato alle guardie stesse.

Qui sotto c'e' un REGISTRO ESPLICITO: per ogni bug storico grave (soldi, sicurezza, crash
pubblici, PII/dati) si dichiara QUALE test lo blocca e DOVE vive. Per ogni voce si verifica:

  (a) il file di guardia ESISTE nella radice del progetto;
  (b) quel file contiene DAVVERO il test dichiarato;
  (c) quel test contiene almeno UNA asserzione vera (non e' un guscio vuoto, un `pass`,
      un test disattivato con @unittest.skip o @unittest.expectedFailure);
  (d) quel test vive dentro una unittest.TestCase (altrimenti non verrebbe mai eseguito:
      un metodo `test_...` in una classe qualsiasi e' codice morto che sembra una guardia).

VISTO ROSSO (regola aurea - fatto davvero, non dichiarato)
----------------------------------------------------------
Il 2026-07-28 si e' rinominato temporaneamente
`test_escrow_gia_liquidato.test_cancella_dopo_conferma_escrow_non_supera_incasso`
in `test_cancella_dopo_conferma_escrow_non_supera_incasso_DISABILITATO`: questo file e'
diventato ROSSO su `test_ogni_guardia_dichiarata_esiste_ancora` con il messaggio
"MONEY-01 ... test SPARITO", poi il nome e' stato ripristinato e il verde e' tornato.
La stessa prova e' automatizzata e permanente in `TestIlControlloSaFallire`, che costruisce
tre guardie FINTE (file assente / test assente / guscio senza asserzioni) e pretende che
ognuno dei tre controlli le BOCCI: se qualcuno indebolisse i controlli, quei test cadono.

REGOLA DI PROCESSO (obbligatoria, come il REGISTRO_INGEGNERIA.md)
-----------------------------------------------------------------
>>> OGNI VOLTA CHE SI CORREGGE UN BUG VERO SI AGGIUNGE UNA VOCE QUI. <<<
Il ciclo completo di una correzione e':
   1. bug trovato -> fix ALLA RADICE (mai nel test, mai un cerotto sul sintomo);
   2. guardia scritta e VISTA ROSSA sul codice vecchio;
   3. riga nel REGISTRO_INGEGNERIA.md (cosa era rotto, come e' stato sistemato);
   4. **voce in `REGISTRO` qui sotto** {codice, descrizione, file, test, gravita, area}.
Senza il passo 4 la guardia e' orfana: nessuno si accorgerebbe della sua sparizione.
Se un test-guardia viene legittimamente RINOMINATO o SPOSTATO, si aggiorna la voce nello
stesso commit del rinomino - non si cancella la voce. Una voce si cancella solo se la
funzione che proteggeva non esiste piu' nel prodotto, e allora si scrive perche'.
"""
import ast
import os
import unittest

RADICE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# IL REGISTRO. Ordinato per gravita': prima i soldi, poi la sicurezza, poi i
# crash su rotte pubbliche, poi i dati/PII, infine gli altri difetti storici.
# Ogni voce: codice stabile | descrizione breve del BUG | file di guardia | test-guardia.
# ---------------------------------------------------------------------------
REGISTRO = [
    # ---------------------- SOLDI (perdite reali provate) -------------------
    {
        "codice": "MONEY-01",
        "descrizione": "Cancellazione dopo che l'escrow era gia' liquidato all'host: il "
                       "rimborso si ricalcolava dalla sola politica e superava l'incassato "
                       "(perdita 26.100 su 30.000, farmabile a ogni prenotazione).",
        "file": "test_escrow_gia_liquidato.py",
        "test": "test_cancella_dopo_conferma_escrow_non_supera_incasso",
        "gravita": "critica", "area": "soldi",
    },
    {
        "codice": "MONEY-02",
        "descrizione": "L'host che aveva GIA' incassato poteva ancora cancellare e far "
                       "rimborsare l'ospite per intero (perdita 21.600 a ciclo).",
        "file": "test_escrow_gia_liquidato.py",
        "test": "test_host_non_puo_cancellare_con_escrow_gia_liquidato",
        "gravita": "critica", "area": "soldi",
    },
    {
        "codice": "MONEY-03",
        "descrizione": "Stessa perdita per la via della controversia risolta a favore "
                       "dell'host: rimborso successivo non tagliato al residuo di cassa.",
        "file": "test_escrow_gia_liquidato.py",
        "test": "test_cancella_dopo_risoluzione_controversia_non_supera_incasso",
        "gravita": "critica", "area": "soldi",
    },
    {
        "codice": "MONEY-04",
        "descrizione": "_admin_rimborso derivava il riferimento da idem[:24] senza togliere "
                       "il prefisso 'reblock:' -> dopo un pagamento tardivo il payout non "
                       "veniva trattenuto ne' l'escrow chiuso.",
        "file": "test_stateful_api.py",
        "test": "test_pilota_rimborso_admin_dopo_reblock",
        "gravita": "critica", "area": "soldi",
    },
    {
        "codice": "MONEY-05",
        "descrizione": "Il bottone admin 'Rimborsa' liberava le date ma non metteva in "
                       "sicurezza i soldi: payout 'maturato' + escrow che si auto-rilascia "
                       "a 24h = si pagava l'host mentre si rimborsava l'ospite.",
        "file": "test_admin_rimborso_money.py",
        "test": "test_rimborso_admin_non_paga_l_host",
        "gravita": "critica", "area": "soldi",
    },
    {
        "codice": "MONEY-06",
        "descrizione": "auto_rilascia versava all'host ogni garanzia scaduta guardando solo "
                       "le contestazioni e NON lo stato di rimborso: doppio esborso "
                       "(rimborso all'ospite + bonifico all'host).",
        "file": "test_escrow_no_pay_rimborsata.py",
        "test": "test_vista_rossa_senza_filtro_la_rimborsata_verrebbe_pagata",
        "gravita": "critica", "area": "soldi",
    },
    {
        "codice": "MONEY-07",
        "descrizione": "Nessuno vedeva i soldi ancora incamminati verso l'host su una "
                       "prenotazione rimborsata (payout 'maturato' superstite): il "
                       "Guardiano fase186 non lo segnalava.",
        "file": "test_guardiano_soldi_rimborsata.py",
        "test": "test_payout_maturato_su_rimborsata",
        "gravita": "critica", "area": "soldi",
    },
    {
        "codice": "MONEY-08",
        "descrizione": "Escrow con auto-rilascio FUTURO su prenotazione gia' rimborsata: "
                       "perdita certa ma non ancora avvenuta, va segnalata IN ANTICIPO.",
        "file": "test_guardiano_soldi_rimborsata.py",
        "test": "test_escrow_FUTURO_su_rimborsata_segnalato_in_anticipo",
        "gravita": "alta", "area": "soldi",
    },
    {
        "codice": "MONEY-09",
        "descrizione": "BUG FISCALE DAC7: aggrega_dac7 leggeva il netto host solo dai payout "
                       "COMPLETATI -> con bonifico in HOLD la commissione dichiarata al Fisco "
                       "diventava il LORDO PIENO (513.000 invece di 78.000 cents).",
        "file": "test_dac7_commissione_giornale.py",
        "test": "test_commissione_corretta_con_payout_in_hold",
        "gravita": "critica", "area": "soldi",
    },
    {
        "codice": "MONEY-10",
        "descrizione": "Replay del webhook Stripe che raddoppiava la commissione a giornale.",
        "file": "test_dac7_commissione_giornale.py",
        "test": "test_webhook_replay_non_raddoppia_commissione",
        "gravita": "alta", "area": "soldi",
    },
    {
        "codice": "MONEY-11",
        "descrizione": "Il token 'credito_fondatore' era un bearer riusabile all'infinito: "
                       "lo stesso credito scontava OGNI prenotazione (erosione del ricavo).",
        "file": "test_credito_single_use.py",
        "test": "test_credito_si_spende_una_volta_sola",
        "gravita": "alta", "area": "soldi",
    },
    {
        "codice": "MONEY-12",
        "descrizione": "'Multa fantasma': admin che rimborsa e host che cancella nello stesso "
                       "istante lasciavano tassa citta' contata, payout da pagare e escrow che "
                       "bonificava comunque.",
        "file": "test_admin_host_stesso_istante.py",
        "test": "test_admin_rimborsa_mentre_host_cancella",
        "gravita": "alta", "area": "soldi",
    },
    {
        "codice": "MONEY-13",
        "descrizione": "Gara sweeper<->conferma: il pagamento tardivo su una stanza gia' "
                       "rivenduta doveva produrre rimborso, non un ospite pagante senza stanza.",
        "file": "test_race_hold_conferma.py",
        "test": "test_pagamento_tardivo_su_stanza_rubata_rimborso",
        "gravita": "critica", "area": "soldi",
    },
    {
        "codice": "MONEY-14",
        "descrizione": "BUG #20: in auto_rilascia la SELECT girava in autocommit e l'UPDATE "
                       "non aveva guardia di stato -> host PAGATO con la disputa APERTA.",
        "file": "test_contesta_autorilascio_race.py",
        "test": "test_un_solo_vincitore_mai_host_pagato_con_disputa",
        "gravita": "critica", "area": "soldi",
    },
    {
        "codice": "MONEY-15",
        "descrizione": "BUG #31: sotto la race webhook-pay/cancel la tassa di soggiorno "
                       "restava contata su prenotazioni rimborsate -> si versava al Comune una "
                       "tassa gia' restituita all'ospite.",
        "file": "test_tassa_race.py",
        "test": "test_storna_prima_di_registra_non_riattiva",
        "gravita": "alta", "area": "soldi",
    },
    {
        "codice": "MONEY-16",
        "descrizione": "Arrotondamenti: lo yen (valuta senza decimali) non deve mai avere "
                       "frazioni - la famiglia del difetto 'prezzo x100'.",
        "file": "test_arrotondamenti_totale.py",
        "test": "test_lo_yen_non_ha_MAI_frazioni",
        "gravita": "alta", "area": "soldi",
    },
    {
        "codice": "MONEY-17",
        "descrizione": "Il denaro deve conservarsi al centesimo fra host, piattaforma e carta: "
                       "voci che arrotondano ognuna per conto proprio staccavano il totale "
                       "dalla somma mostrata.",
        "file": "test_arrotondamenti_totale.py",
        "test": "test_il_denaro_si_conserva_fra_host_noi_e_carta",
        "gravita": "alta", "area": "soldi",
    },
    {
        "codice": "MONEY-18",
        "descrizione": "L'unico rimborso Stripe senza chiave di idempotenza (fase35 legacy) "
                       "poteva emettere DUE rimborsi veri: ora e' chiuso e non tocca Stripe.",
        "file": "test_rimborso_legacy_chiuso.py",
        "test": "test_rimborsa_non_emette_piu_nulla",
        "gravita": "alta", "area": "soldi",
    },
    {
        "codice": "MONEY-19",
        "descrizione": "BUG #36: lo split di gruppo girava su ':memory:' hardcoded -> 503 a "
                       "raffica sotto pagamenti simultanei e conti di gruppo PERSI a ogni "
                       "riavvio del container.",
        "file": "test_bombardamento_split_router.py",
        "test": "test_db_split_durevole_al_riavvio",
        "gravita": "critica", "area": "soldi",
    },
    {
        "codice": "MONEY-20",
        "descrizione": "BUG #32: il webhook non si auto-riparava dopo un crash a meta' (stato "
                       "'pagato' committato, tassa e payout mai eseguiti) perche' il retry "
                       "usciva subito come 'duplicato idempotente'.",
        "file": "test_crash_recovery_webhook.py",
        "test": "test_webhook_normale_piu_retry_non_raddoppia",
        "gravita": "alta", "area": "soldi",
    },
    {
        "codice": "MONEY-21",
        "descrizione": "Il retry del webhook non deve MAI risuscitare una prenotazione "
                       "cancellata (soldi incassati su una stanza gia' rivenduta).",
        "file": "test_crash_recovery_webhook.py",
        "test": "test_retry_non_risuscita_una_cancellata",
        "gravita": "critica", "area": "soldi",
    },
    {
        "codice": "MONEY-22",
        "descrizione": "BUG #18: con disputa aperta il payout restava nel giro dei bonifici "
                       "-> all'host arrivava anche la quota appena rimborsata all'ospite.",
        "file": "test_split_penale_payout.py",
        "test": "test_disputa_aperta_payout_fuori_dal_giro",
        "gravita": "critica", "area": "soldi",
    },
    {
        "codice": "MONEY-23",
        "descrizione": "Il webhook TARDIVO su una prenotazione gia' cancellata non deve "
                       "produrre la coppia impossibile soldi-incassati + stanza-libera.",
        "file": "test_stateful_api.py",
        "test": "test_pilota_webhook_tardivo_su_cancellata",
        "gravita": "critica", "area": "soldi",
    },
    {
        "codice": "MONEY-24",
        "descrizione": "Doppia conferma della garanzia che cambiava di nuovo lo stato "
                       "(rischio di secondo esborso): transizione provata terminale.",
        "file": "test_fase199_transizioni.py",
        "test": "test_doppia_conferma_non_cambia_stato",
        "gravita": "alta", "area": "soldi",
    },
    {
        "codice": "MONEY-25",
        "descrizione": "Replay dell'evento 'registra maturato' che sommava di nuovo l'importo "
                       "del payout invece di lasciarlo invariato.",
        "file": "test_fase199_transizioni.py",
        "test": "test_replay_registra_maturato_non_tocca_importo",
        "gravita": "alta", "area": "soldi",
    },
    {
        "codice": "MONEY-26",
        "descrizione": "Kill-switch globale d'emergenza: con l'interruttore acceso book e "
                       "rimborso devono dare 503, altrimenti il freno di emergenza non frena.",
        "file": "test_blocco_globale.py",
        "test": "test_freeze_blocca_book_e_rimborso",
        "gravita": "alta", "area": "soldi",
    },

    # ---------------------------- SICUREZZA --------------------------------
    {
        "codice": "SEC-01",
        "descrizione": "Scalata di privilegi: AZIONI_SOLO_ADMIN elencava sei azioni riservate "
                       "ma il router chiamava _puo_azione solo per due -> un operatore "
                       "'supporto' sospendeva annunci e arbitrava i soldi in garanzia.",
        "file": "test_sicurezza_adversarial.py",
        "test": "test_supporto_respinto_su_tutte_le_azioni_solo_admin",
        "gravita": "critica", "area": "sicurezza",
    },
    {
        "codice": "SEC-02",
        "descrizione": "Lo stesso buco permetteva a 'supporto' di cancellare DAVVERO un host "
                       "da ogni archivio (/api/admin/cancella_attivita rispondeva 200).",
        "file": "test_sicurezza_adversarial.py",
        "test": "test_supporto_non_cancella_davvero_un_host",
        "gravita": "critica", "area": "sicurezza",
    },
    {
        "codice": "SEC-03",
        "descrizione": "La FIRMA HMAC del token operatore (fase192) non era protetta da nessun "
                       "test: mutante sopravvissuto = token falsificabile conoscendo l'email.",
        "file": "test_admin_accounts.py",
        "test": "test_token_operatore_con_firma_falsa_non_autentica",
        "gravita": "critica", "area": "sicurezza",
    },
    {
        "codice": "SEC-04",
        "descrizione": "La SCADENZA del token operatore non era protetta da nessun test: "
                       "mutante sopravvissuto = token rubato valido per sempre.",
        "file": "test_admin_accounts.py",
        "test": "test_token_operatore_scaduto_non_autentica",
        "gravita": "critica", "area": "sicurezza",
    },
    {
        "codice": "SEC-05",
        "descrizione": "Contraddizione fra i due controlli d'accesso: senza ADMIN_KEY "
                       "_auth_admin diceva 'sei admin' e _puo_azione 'non sei nessuno' -> "
                       "porta aperta E controversie irrisolvibili.",
        "file": "test_admin_accounts.py",
        "test": "test_senza_chiave_admin_l_arbitrato_non_e_403_di_ruolo",
        "gravita": "alta", "area": "sicurezza",
    },
    {
        "codice": "SEC-06",
        "descrizione": "Il ruolo 'supporto' poteva muovere soldi (rimborso): il gate di ruolo "
                       "sulle azioni monetarie deve restare.",
        "file": "test_admin_accounts.py",
        "test": "test_supporto_non_muove_soldi",
        "gravita": "critica", "area": "sicurezza",
    },
    {
        "codice": "SEC-07",
        "descrizione": "/api/garanzia/contesta|conferma accettavano la chiamata diretta col "
                       "voucher di una prenotazione MAI PAGATA (la pagina nascondeva i tasti, "
                       "l'API no).",
        "file": "test_stateful_api.py",
        "test": "test_pilota_garanzia_gated_dal_pagamento",
        "gravita": "critica", "area": "sicurezza",
    },
    {
        "codice": "SEC-08",
        "descrizione": "IDOR fail-open: _decidi_richiesta controllava l'ownership solo se "
                       "host_id era valorizzato -> con host_id='' QUALSIASI host approvava "
                       "o rifiutava la richiesta di un altro.",
        "file": "test_idor_richieste.py",
        "test": "test_caso_vulnerabile_host_id_vuoto",
        "gravita": "critica", "area": "sicurezza",
    },
    {
        "codice": "SEC-09",
        "descrizione": "Isolamento cross-host in SCRITTURA: l'host A non deve poter cambiare "
                       "disponibilita' e prezzi degli annunci di B (sabotaggio a 1 cent).",
        "file": "test_rbac_scrittura_cross_host.py",
        "test": "test_A_non_cambia_disponibilita_di_B",
        "gravita": "critica", "area": "sicurezza",
    },
    {
        "codice": "SEC-10",
        "descrizione": "Stored XSS provato: valida_scheda accettava qualsiasi stringa come "
                       "slug e finiva in onclick/data-slug -> injection JS e HTML.",
        "file": "test_slug_sicurezza.py",
        "test": "test_campi_host_sempre_escapati",
        "gravita": "critica", "area": "sicurezza",
    },
    {
        "codice": "SEC-11",
        "descrizione": "Lo stesso slug non normalizzato apriva il path traversal negli URL "
                       "/api/catalogo/<slug> ('../../etc/passwd').",
        "file": "test_slug_sicurezza.py",
        "test": "test_path_traversal_neutralizzato",
        "gravita": "critica", "area": "sicurezza",
    },
    {
        "codice": "SEC-12",
        "descrizione": "hmac.compare_digest su chiave non-ASCII solleva TypeError: un login "
                       "sbagliato con emoji/surrogato diventava un 500 invece di un 401.",
        "file": "test_auth_non_ascii.py",
        "test": "test_surrogato_isolato_non_crasha_auth",
        "gravita": "alta", "area": "sicurezza",
    },
    {
        "codice": "SEC-13",
        "descrizione": "Login senza rate-limit = brute-force libero: soglia per IP, backoff "
                       "crescente e lockout devono restare (mai per-email, niente DoS account).",
        "file": "test_rate_limit_login.py",
        "test": "test_lockout_dopo_soglia_e_backoff",
        "gravita": "alta", "area": "sicurezza",
    },
    {
        "codice": "SEC-14",
        "descrizione": "Gatekeeper delle pagine riservate: un cookie di sessione MANOMESSO "
                       "non deve aprire admin/bunker/host (firma HMAC HttpOnly).",
        "file": "test_gatekeeper.py",
        "test": "test_cookie_manomesso_respinto",
        "gravita": "critica", "area": "sicurezza",
    },
    {
        "codice": "SEC-15",
        "descrizione": "Check-in digitale ammesso con pendente 'in_attesa': chi non pagava "
                       "completava il check-in e - con serratura smart - apriva la porta "
                       "(soggiorno gratis).",
        "file": "test_checkin_pass_solo_se_pagato.py",
        "test": "test_in_attesa_niente_checkin",
        "gravita": "critica", "area": "sicurezza",
    },
    {
        "codice": "SEC-16",
        "descrizione": "Email header-injection: un a-capo nel destinatario (testo scritto "
                       "dall'host) iniettava header SMTP = Bcc di massa dal nostro dominio "
                       "-> blacklist e voucher non piu' consegnati.",
        "file": "test_neuroni_guardie.py",
        "test": "test_destinatario_con_acapo_rifiutato_senza_invio",
        "gravita": "alta", "area": "sicurezza",
    },
    {
        "codice": "SEC-17",
        "descrizione": "Consensi controllati SOLO dal browser: una registrazione via API con "
                       "accetta_clausole:false creava l'account con vessatorie=0 (artt. "
                       "1341-1342 non opponibili). Ora 422 lato server, nessun account.",
        "file": "test_consensi_blindati.py",
        "test": "test_manca_una_spunta_qualsiasi_422_e_nessun_account",
        "gravita": "alta", "area": "sicurezza",
    },
    {
        "codice": "SEC-18",
        "descrizione": "La prova firmata dell'accettazione deve smascherare la manomissione "
                       "di una riga (catena HMAC-SHA256), altrimenti non vale in causa.",
        "file": "test_consensi_blindati.py",
        "test": "test_manomissione_riga_smascherata",
        "gravita": "alta", "area": "sicurezza",
    },
    {
        "codice": "SEC-19",
        "descrizione": "L'elenco admin dei contatti partner deve restare chiuso a chiave "
                       "anche con una chiave 'quasi giusta' (confronto costante).",
        "file": "test_partner_adversarial.py",
        "test": "test_elenco_admin_chiuso_a_chiave_anche_quasi_giusta",
        "gravita": "alta", "area": "sicurezza",
    },

    # ------------------- CRASH SU ROTTE PUBBLICHE (500 / no-reply) ----------
    {
        "codice": "CRASH-01",
        "descrizione": "Surrogato unicode isolato in citta'/email di /api/domanda (rotta "
                       "PUBBLICA senza auth) -> UnicodeEncodeError nell'INSERT = 500 sulla "
                       "cattura di cold-start.",
        "file": "test_domanda_velenosa.py",
        "test": "test_rotta_pubblica_mai_500",
        "gravita": "critica", "area": "crash pubblico",
    },
    {
        "codice": "CRASH-02",
        "descrizione": "Stesso surrogato isolato su /api/partner: 500 sulla rotta pubblica e "
                       "NUL byte che entrava in archivio troncando la stringa a valle.",
        "file": "test_partner_adversarial.py",
        "test": "test_surrogati_e_caratteri_di_controllo_mai_in_archivio_mai_500",
        "gravita": "critica", "area": "crash pubblico",
    },
    {
        "codice": "CRASH-03",
        "descrizione": "JSON annidato 30.000 volte -> RecursionError, che non discende da "
                       "ValueError e sfuggiva al try/except di _json = 500.",
        "file": "test_partner_adversarial.py",
        "test": "test_json_malformato_o_annidato_o_non_oggetto_e_400_mai_500",
        "gravita": "alta", "area": "crash pubblico",
    },
    {
        "codice": "CRASH-04",
        "descrizione": "do_POST con Content-Length non numerico chiudeva la connessione SENZA "
                       "alcuna risposta (client appeso, nessun log utile).",
        "file": "test_sicurezza_adversarial.py",
        "test": "test_lunghezza_corpo_mai_eccezione",
        "gravita": "alta", "area": "crash pubblico",
    },
    {
        "codice": "CRASH-05",
        "descrizione": "Corpo della richiesta non-UTF8: stessa morte silenziosa prima di "
                       "arrivare al router.",
        "file": "test_sicurezza_adversarial.py",
        "test": "test_corpo_richiesta_testo_mai_eccezione",
        "gravita": "alta", "area": "crash pubblico",
    },
    {
        "codice": "CRASH-06",
        "descrizione": "La risposta JSON con un surrogato dentro esplodeva in fase di encode: "
                       "il corpo dev'essere SEMPRE spedibile, qualunque cosa entri.",
        "file": "test_sicurezza_adversarial.py",
        "test": "test_corpo_json_bytes_sopravvive_ai_surrogati",
        "gravita": "alta", "area": "crash pubblico",
    },
    {
        "codice": "CRASH-07",
        "descrizione": "_host_pubblica con 'immagini' avvelenato (None/numero/tipi assurdi) "
                       "rispondeva 500 invece di un 4xx garbato - e il 'no' deve restare no "
                       "anche nel database.",
        "file": "test_input_invalidi_ogni_casella.py",
        "test": "test_ogni_casella_con_ogni_veleno",
        "gravita": "alta", "area": "crash pubblico",
    },
    {
        "codice": "CRASH-08",
        "descrizione": "HEAD non implementato -> 501 su / e /api/health: i monitor di uptime "
                       "usano HEAD di default e avrebbero gridato 'SITO GIU'' a sito vivo.",
        "file": "test_head_http.py",
        "test": "test_corpo_saltato_in_head",
        "gravita": "media", "area": "crash pubblico",
    },
    {
        "codice": "CRASH-09",
        "descrizione": "Degrade anti-tofu del renderer video: SCHERMO['en'] ha 5 voci ma il "
                       "formato lungo ha 7 scene -> IndexError, video MAI reso per th/ja/zh/ko "
                       "su macchina senza font CJK.",
        "file": "test_video_robusto.py",
        "test": "test_monta_degrada_anche_il_formato_lungo",
        "gravita": "media", "area": "crash pubblico",
    },

    # ------------------------- DATI / PII / DUREVOLEZZA ---------------------
    {
        "codice": "DATI-01",
        "descrizione": "maschera_pii storpiava le URL delle prove in chat: la bolla della "
                       "foto diventava illeggibile e in controversia l'arbitro non vedeva la "
                       "prova dell'ospite.",
        "file": "test_fase113_messaggistica.py",
        "test": "test_maschera_non_storpia_url_prova",
        "gravita": "alta", "area": "dati/PII",
    },
    {
        "codice": "DATI-02",
        "descrizione": "La stessa maschera deve restare SEVERA attorno alle URL: nessun "
                       "contatto (telefono/email) puo' passare travestito da link.",
        "file": "test_fase113_messaggistica.py",
        "test": "test_maschera_pii_resta_severa_attorno_alle_url",
        "gravita": "alta", "area": "dati/PII",
    },
    {
        "codice": "DATI-03",
        "descrizione": "Database non dichiarati nel compose finivano in /app/data (dentro "
                       "l'immagine) e SPARIVANO a ogni deploy: recensioni perse, crediti "
                       "rispendibili, prove legali distrutte in silenzio.",
        "file": "test_db_persistenti.py",
        "test": "test_ogni_database_e_dichiarato_nel_compose",
        "gravita": "critica", "area": "dati/PII",
    },
    {
        "codice": "DATI-04",
        "descrizione": "connect su file senza timeout: sotto contesa 'database is locked' "
                       "tornava False in silenzio (classe del bug della prova-foto persa).",
        "file": "test_neuroni_guardie.py",
        "test": "test_ogni_connect_su_file_ha_timeout",
        "gravita": "alta", "area": "dati/PII",
    },
    {
        "codice": "DATI-05",
        "descrizione": "Foto orfane su disco (riempi-disco a goccia): la scopa deve cancellare "
                       "SOLO gli orfani vecchi e mai i file citati da annunci o chat.",
        "file": "test_pulizia_uploads.py",
        "test": "test_selettiva_cancella_solo_orfani_vecchi",
        "gravita": "media", "area": "dati/PII",
    },
    {
        "codice": "DATI-06",
        "descrizione": "La guardia anti-fake delle recensioni moriva con la purga dei pendenti "
                       "(~26h) e falliva APERTA: una prenotazione rimborsata tornava "
                       "recensibile 'verificata'.",
        "file": "test_recensione_purga.py",
        "test": "test_recensione_bloccata_anche_dopo_la_purga",
        "gravita": "alta", "area": "dati/PII",
    },
    {
        "codice": "DATI-07",
        "descrizione": "PII a riposo del form partner: in archivio devono finire SOLO i campi "
                       "previsti, mai campi extra iniettati dal chiamante.",
        "file": "test_partner_adversarial.py",
        "test": "test_in_archivio_finiscono_solo_i_campi_previsti",
        "gravita": "alta", "area": "dati/PII",
    },
    {
        "codice": "DATI-08",
        "descrizione": "Nessuna riga di contatto puo' esistere senza il consenso GDPR "
                       "registrato accanto (solo il booleano True apre la porta).",
        "file": "test_partner_adversarial.py",
        "test": "test_nessuna_riga_puo_esistere_senza_consenso_registrato",
        "gravita": "alta", "area": "dati/PII",
    },
    {
        "codice": "DATI-09",
        "descrizione": "Stanza fantasma: una notte occupata nell'inventario senza pendente "
                       "(crash fra blocco e registrazione) restava invendibile per sempre; il "
                       "filtro idem_validi impedisce di liberare gli hold LEGITTIMI.",
        "file": "test_stanza_fantasma.py",
        "test": "test_vista_rossa_senza_il_set_pendenti_il_legittimo_e_orfano",
        "gravita": "alta", "area": "dati/PII",
    },
    {
        "codice": "DATI-10",
        "descrizione": "L'endpoint preventivo-email spammava terzi: il throttle aveva la data "
                       "nella chiave, bastava cambiarla per un secchiello nuovo -> dominio in "
                       "blacklist e voucher non consegnati.",
        "file": "test_abuso_email.py",
        "test": "test_cambiare_data_non_aggira_piu_il_tetto",
        "gravita": "alta", "area": "dati/PII",
    },
    {
        "codice": "DATI-11",
        "descrizione": "Azzeramento silenzioso della valuta: modificare un annuncio senza "
                       "rimandare il campo faceva scattare il default 'EUR' -> un annuncio in "
                       "yen tornava in euro (e cambiava di scala).",
        "file": "test_valuta_annuncio_bloccata.py",
        "test": "test_modifica_senza_valuta_NON_azzera_a_EUR",
        "gravita": "alta", "area": "dati/PII",
    },

    # ------------------- ALTRI DIFETTI STORICI (vista utente) ---------------
    {
        "codice": "UI-01",
        "descrizione": "BUG #35: in fase58.calendario il 'chiuso' vinceva sul 'pieno' -> una "
                       "notte GIA' VENDUTA che l'host chiude spariva dalle viste: l'host "
                       "credeva la data libera e la rivendeva altrove.",
        "file": "test_bombardamento_calendario_tutti.py",
        "test": "test_venduta_poi_chiusa_resta_piena",
        "gravita": "alta", "area": "prodotto",
    },
    {
        "codice": "UI-02",
        "descrizione": "BUG #34: host.html chiamava money(), definita solo in admin/index "
                       "(copia-incolla cross-pagina) -> ReferenceError e calendario prezzi "
                       "MORTO nel browser con la suite verde.",
        "file": "test_host_calendario_ui.py",
        "test": "test_helper_usati_sono_definiti_nella_stessa_pagina",
        "gravita": "media", "area": "prodotto",
    },
    {
        "codice": "OPS-01",
        "descrizione": "Con DATA_DIR vuota (non mancante) la diagnosi admin rispondeva "
                       "'0 db, NESSUN backup' con /data pieno: allarme cieco proprio quando "
                       "serve.",
        "file": "test_watchdog.py",
        "test": "test_data_dir_vuota_usa_fallback",
        "gravita": "media", "area": "prodotto",
    },
]


# ---------------------------------------------------------------------------
# I CONTROLLI (riusabili: li usa anche TestIlControlloSaFallire su casi finti)
# ---------------------------------------------------------------------------
_CACHE = {}  # type: dict

_DECORATORI_CHE_SPENGONO = ("skip", "expectedFailure")


def albero_di(percorso):
    """AST del file (con cache): None se il file non esiste."""
    if percorso in _CACHE:
        return _CACHE[percorso]
    if not os.path.isfile(percorso):
        _CACHE[percorso] = None
        return None
    with open(percorso, "r", encoding="utf-8") as f:
        alb = ast.parse(f.read(), filename=os.path.basename(percorso))
    _CACHE[percorso] = alb
    return alb


def _e_test_case(nodo_classe, per_nome):
    """La classe deriva (anche indirettamente, dentro lo stesso file) da TestCase?"""
    visti = set()
    da_vedere = [nodo_classe]
    while da_vedere:
        cl = da_vedere.pop()
        if id(cl) in visti:
            continue
        visti.add(id(cl))
        for base in cl.bases:
            nome = ""
            if isinstance(base, ast.Attribute):
                nome = base.attr
            elif isinstance(base, ast.Name):
                nome = base.id
            if nome == "TestCase":
                return True
            padre = per_nome.get(nome)
            if padre is not None:
                da_vedere.append(padre)
    return False


def trova_guardia(albero, nome_test):
    """Ritorna (nodo_funzione, nodo_classe) oppure (None, None)."""
    per_nome = {c.name: c for c in ast.walk(albero) if isinstance(c, ast.ClassDef)}
    for classe in per_nome.values():
        for corpo in classe.body:
            if isinstance(corpo, (ast.FunctionDef, ast.AsyncFunctionDef)) and corpo.name == nome_test:
                return corpo, classe
    # anche una funzione fuori da una classe va trovata: cosi' il controllo (d)
    # puo' dire "esiste ma non gira", invece di confondersi con "non esiste".
    for nodo in ast.walk(albero):
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)) and nodo.name == nome_test:
            return nodo, None
    return None, None


def _nome_decoratore(dec):
    if isinstance(dec, ast.Call):
        dec = dec.func
    if isinstance(dec, ast.Attribute):
        return dec.attr
    if isinstance(dec, ast.Name):
        return dec.id
    return ""


def e_spenta(nodo_funzione):
    """La guardia e' disattivata da un decoratore (@unittest.skip/@expectedFailure)?"""
    for dec in nodo_funzione.decorator_list:
        if _nome_decoratore(dec) in _DECORATORI_CHE_SPENGONO:
            return True
    return False


def conta_asserzioni(nodo_funzione):
    """Quante asserzioni VERE contiene il corpo: `assert`, self.assertX(...),
    self.fail(...), `with self.assertRaises(...)`. Solo AST: un commento o una
    stringa che contiene 'assert' non conta."""
    n = 0
    for sub in ast.walk(nodo_funzione):
        if isinstance(sub, ast.Assert):
            n += 1
        elif isinstance(sub, ast.Call):
            nome = _nome_decoratore(sub.func)
            if nome.startswith("assert") or nome == "fail" or nome.startswith("failUnless"):
                n += 1
    return n


def _percorso(voce):
    return os.path.join(RADICE, voce["file"])


def controlla_voce(voce):
    """Ritorna la lista dei problemi trovati (vuota = voce sana)."""
    guai = []
    p = _percorso(voce)
    alb = albero_di(p)
    if alb is None:
        return ["%s: file di guardia SPARITO -> %s" % (voce["codice"], voce["file"])]
    fn, classe = trova_guardia(alb, voce["test"])
    if fn is None:
        guai.append("%s: test SPARITO -> %s::%s" % (voce["codice"], voce["file"], voce["test"]))
        return guai
    if classe is None:
        guai.append("%s: %s::%s non e' dentro nessuna classe -> non viene mai eseguito"
                    % (voce["codice"], voce["file"], voce["test"]))
    elif not _e_test_case(classe, {c.name: c for c in ast.walk(alb) if isinstance(c, ast.ClassDef)}):
        guai.append("%s: %s::%s vive in %s che NON e' una unittest.TestCase -> codice morto"
                    % (voce["codice"], voce["file"], voce["test"], classe.name))
    if e_spenta(fn):
        guai.append("%s: %s::%s e' DISATTIVATO da un decoratore (skip/expectedFailure)"
                    % (voce["codice"], voce["file"], voce["test"]))
    if conta_asserzioni(fn) == 0:
        guai.append("%s: %s::%s e' un GUSCIO VUOTO (zero asserzioni)"
                    % (voce["codice"], voce["file"], voce["test"]))
    return guai


# ---------------------------------------------------------------------------
# I TEST
# ---------------------------------------------------------------------------
class TestRegistroBenFormato(unittest.TestCase):
    """Il registro stesso dev'essere sano: senza questo, i controlli girerebbero a vuoto."""

    CHIAVI = ("codice", "descrizione", "file", "test", "gravita", "area")

    def test_ci_sono_almeno_25_voci(self):
        self.assertGreaterEqual(
            len(REGISTRO), 25,
            "il registro anti-regressione deve coprire almeno i 25 bug storici piu' gravi")

    def test_ogni_voce_ha_tutti_i_campi_pieni(self):
        for voce in REGISTRO:
            for chiave in self.CHIAVI:
                self.assertIn(chiave, voce, "voce senza campo %r: %r" % (chiave, voce))
                self.assertTrue(str(voce[chiave]).strip(),
                                "campo %r vuoto nella voce %r" % (chiave, voce.get("codice")))

    def test_codici_unici(self):
        codici = [v["codice"] for v in REGISTRO]
        doppi = sorted({c for c in codici if codici.count(c) > 1})
        self.assertEqual(doppi, [], "codici duplicati nel registro: %r" % (doppi,))

    def test_nessuna_guardia_dichiarata_due_volte(self):
        coppie = [(v["file"], v["test"]) for v in REGISTRO]
        doppie = sorted({c for c in coppie if coppie.count(c) > 1})
        self.assertEqual(doppie, [],
                         "stessa guardia dichiarata per due bug diversi: %r" % (doppie,))

    def test_i_file_di_guardia_sono_test_del_progetto(self):
        for voce in REGISTRO:
            nome = voce["file"]
            self.assertTrue(nome.startswith("test_") and nome.endswith(".py"),
                            "%s: %r non e' un file di test raccolto dalla suite"
                            % (voce["codice"], nome))
            self.assertEqual(os.path.basename(nome), nome,
                             "%s: il file di guardia deve stare nella radice" % voce["codice"])

    def test_gravita_dichiarata_fra_quelle_ammesse(self):
        ammesse = {"critica", "alta", "media", "bassa"}
        for voce in REGISTRO:
            self.assertIn(voce["gravita"], ammesse,
                          "%s: gravita' %r non ammessa" % (voce["codice"], voce["gravita"]))

    def test_i_bug_dei_soldi_e_della_sicurezza_sono_la_maggioranza(self):
        """Il registro nasce per i bug GRAVI: se un giorno fosse pieno di inezie e i soldi
        fossero scoperti, questa guardia lo dice."""
        gravi = [v for v in REGISTRO if v["area"] in ("soldi", "sicurezza")]
        self.assertGreaterEqual(len(gravi), 25,
                                "coperti solo %d bug di soldi/sicurezza" % len(gravi))


class TestGuardieVive(unittest.TestCase):
    """(a) il file esiste - (b) contiene il test dichiarato - (c) il test asserisce davvero
    - (d) il test gira davvero (sta dentro una TestCase)."""

    def test_ogni_file_di_guardia_esiste_ancora(self):
        mancanti = sorted({v["file"] for v in REGISTRO if albero_di(_percorso(v)) is None})
        self.assertEqual(
            mancanti, [],
            "FILE DI GUARDIA SPARITI (i bug che proteggevano possono tornare in silenzio): %s"
            % ", ".join(mancanti))

    def test_ogni_guardia_dichiarata_esiste_ancora(self):
        spariti = []
        for voce in REGISTRO:
            alb = albero_di(_percorso(voce))
            if alb is None:
                continue  # gia' segnalato dal test precedente
            fn, _ = trova_guardia(alb, voce["test"])
            if fn is None:
                spariti.append("%s: test SPARITO -> %s::%s"
                               % (voce["codice"], voce["file"], voce["test"]))
        self.assertEqual(spariti, [], "GUARDIE SPARITE:\n  " + "\n  ".join(spariti))

    def test_nessuna_guardia_e_un_guscio_vuoto(self):
        gusci = []
        for voce in REGISTRO:
            alb = albero_di(_percorso(voce))
            if alb is None:
                continue
            fn, _ = trova_guardia(alb, voce["test"])
            if fn is None:
                continue
            if e_spenta(fn):
                gusci.append("%s: %s::%s DISATTIVATO da un decoratore"
                             % (voce["codice"], voce["file"], voce["test"]))
            elif conta_asserzioni(fn) == 0:
                gusci.append("%s: %s::%s senza nessuna asserzione"
                             % (voce["codice"], voce["file"], voce["test"]))
        self.assertEqual(gusci, [], "GUARDIE SVUOTATE:\n  " + "\n  ".join(gusci))

    def test_ogni_guardia_viene_davvero_eseguita(self):
        morte = []
        for voce in REGISTRO:
            alb = albero_di(_percorso(voce))
            if alb is None:
                continue
            fn, classe = trova_guardia(alb, voce["test"])
            if fn is None:
                continue
            per_nome = {c.name: c for c in ast.walk(alb) if isinstance(c, ast.ClassDef)}
            if classe is None or not _e_test_case(classe, per_nome):
                morte.append("%s: %s::%s non vive in una unittest.TestCase"
                             % (voce["codice"], voce["file"], voce["test"]))
        self.assertEqual(morte, [], "GUARDIE MAI ESEGUITE:\n  " + "\n  ".join(morte))

    def test_rapporto_completo_zero_guai(self):
        """Rete finale: qualunque problema su qualunque voce, tutto in un colpo solo."""
        guai = []
        for voce in REGISTRO:
            guai.extend(controlla_voce(voce))
        self.assertEqual(guai, [],
                         "REGISTRO ANTI-REGRESSIONE VIOLATO:\n  " + "\n  ".join(guai))


class TestIlControlloSaFallire(unittest.TestCase):
    """VISTO ROSSO PERMANENTE (regola aurea: un controllo che non puo' fallire e' un
    ornamento). Si costruiscono guardie FINTE guaste e si pretende che i controlli le
    BOCCINO. Se qualcuno indebolisse i controlli qui sopra, questi test cadono."""

    def setUp(self):
        import shutil
        import tempfile
        self.dir = tempfile.mkdtemp(prefix="reg_regr_")
        self.addCleanup(shutil.rmtree, self.dir, True)

    # NB: i sorgenti finti qui sotto si compongono a pezzi (`_ASS`, `_DEC_SPENTO`) e non
    # contengono MAI in chiaro le forme "guardia costante" ne' il decoratore di salto:
    # collaudi/caccia_finti_verdi.py le cerca sul testo GREZZO e le segnalerebbe come
    # finti-verdi di QUESTO file. I falsi allarmi fanno ignorare la guardia, quindi non
    # se ne introducono nemmeno nei commenti.
    _ASS = "        self.assertIn('a', 'abc')\n"
    _DEC_SPENTO = "    @unittest." + "skip('guardia spenta apposta')\n"

    def _scrivi(self, nome, testo):
        p = os.path.join(self.dir, nome)
        with open(p, "w", encoding="utf-8") as f:
            f.write(testo)
        _CACHE.pop(p, None)
        return p

    def test_il_controllo_vede_il_file_sparito(self):
        p = os.path.join(self.dir, "test_mai_esistito.py")
        self.assertIsNone(albero_di(p))

    def test_il_controllo_vede_il_test_rinominato(self):
        p = self._scrivi("test_finta_a.py",
                         "import unittest\n"
                         "class T(unittest.TestCase):\n"
                         "    def test_guardia_RINOMINATA(self):\n"
                         + self._ASS)
        alb = albero_di(p)
        fn, _ = trova_guardia(alb, "test_guardia")
        self.assertIsNone(fn, "una guardia rinominata deve risultare SPARITA")
        fn2, _ = trova_guardia(alb, "test_guardia_RINOMINATA")
        self.assertIsNotNone(fn2, "il nome nuovo invece si deve trovare")

    def test_il_controllo_vede_il_guscio_vuoto(self):
        p = self._scrivi("test_finta_b.py",
                         "import unittest\n"
                         "class T(unittest.TestCase):\n"
                         "    def test_guscio(self):\n"
                         '        """assert: questa parola nel testo non conta"""\n'
                         "        x = 1 + 1  # nessuna asserzione\n"
                         "        return x\n")
        fn, _ = trova_guardia(albero_di(p), "test_guscio")
        self.assertEqual(conta_asserzioni(fn), 0,
                         "un corpo senza asserzioni deve contare 0")

    def test_il_controllo_riconosce_le_asserzioni_vere(self):
        p = self._scrivi("test_finta_c.py",
                         "import unittest\n"
                         "class T(unittest.TestCase):\n"
                         "    def test_asserisce(self):\n"
                         + self._ASS +
                         "    def test_assert_nudo(self):\n"
                         "        assert 1 == 2 - 1\n"
                         "    def test_con_raises(self):\n"
                         "        with self.assertRaises(ValueError):\n"
                         "            int('x')\n"
                         "    def test_con_fail(self):\n"
                         "        if False:\n"
                         "            self.fail('mai')\n")
        alb = albero_di(p)
        for nome in ("test_asserisce", "test_assert_nudo", "test_con_raises", "test_con_fail"):
            fn, _ = trova_guardia(alb, nome)
            self.assertGreaterEqual(conta_asserzioni(fn), 1,
                                    "%s deve contare almeno un'asserzione" % nome)

    def test_il_controllo_vede_la_guardia_spenta(self):
        p = self._scrivi("test_finta_d.py",
                         "import unittest\n"
                         "class T(unittest.TestCase):\n"
                         + self._DEC_SPENTO +
                         "    def test_spenta(self):\n"
                         + self._ASS +
                         "    def test_accesa(self):\n"
                         + self._ASS)
        alb = albero_di(p)
        self.assertTrue(e_spenta(trova_guardia(alb, "test_spenta")[0]))
        self.assertFalse(e_spenta(trova_guardia(alb, "test_accesa")[0]))

    def test_il_controllo_vede_la_guardia_fuori_da_una_testcase(self):
        p = self._scrivi("test_finta_e.py",
                         "import unittest\n"
                         "class NonEUnTest:\n"
                         "    def test_morto(self):\n"
                         + self._ASS +
                         "class Base(unittest.TestCase):\n"
                         "    pass\n"
                         "class Vivo(Base):\n"
                         "    def test_vivo(self):\n"
                         + self._ASS)
        alb = albero_di(p)
        per_nome = {c.name: c for c in ast.walk(alb) if isinstance(c, ast.ClassDef)}
        _, cl_morto = trova_guardia(alb, "test_morto")
        _, cl_vivo = trova_guardia(alb, "test_vivo")
        self.assertFalse(_e_test_case(cl_morto, per_nome),
                         "una classe che non deriva da TestCase non esegue nulla")
        self.assertTrue(_e_test_case(cl_vivo, per_nome),
                        "l'ereditarieta' indiretta da TestCase va riconosciuta")

    def test_controlla_voce_boccia_ognuno_dei_tre_guasti(self):
        """Il controllo completo, sulle tre rotture, deve dare tre bocciature diverse."""
        globals_originale = globals()["RADICE"]
        try:
            globals()["RADICE"] = self.dir
            self._scrivi("test_finta_f.py",
                         "import unittest\n"
                         "class T(unittest.TestCase):\n"
                         "    def test_vuota(self):\n"
                         "        pass\n"
                         "    def test_piena(self):\n"
                         + self._ASS)
            base = {"codice": "X", "gravita": "alta", "area": "soldi", "descrizione": "finta"}
            senza_file = dict(base, file="test_assente.py", test="test_piena")
            senza_test = dict(base, file="test_finta_f.py", test="test_mai_scritta")
            guscio = dict(base, file="test_finta_f.py", test="test_vuota")
            sana = dict(base, file="test_finta_f.py", test="test_piena")
            self.assertIn("file di guardia SPARITO", " ".join(controlla_voce(senza_file)))
            self.assertIn("test SPARITO", " ".join(controlla_voce(senza_test)))
            self.assertIn("GUSCIO VUOTO", " ".join(controlla_voce(guscio)))
            self.assertEqual(controlla_voce(sana), [],
                             "una voce sana non deve produrre falsi allarmi")
        finally:
            globals()["RADICE"] = globals_originale


if __name__ == "__main__":
    unittest.main(verbosity=2)
