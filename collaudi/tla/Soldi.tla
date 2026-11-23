------------------------------- MODULE Soldi -------------------------------
(***************************************************************************)
(* I SOLDI DI UNA PRENOTAZIONE, dal pagamento all'ultimo euro.             *)
(* Blocco 1 di collaudi/piano.py, casella «il modello TLA+ degli stati del *)
(* denaro». Lo controlla TLC, il model checker di TLA+: prova TUTTE le     *)
(* sequenze di passi possibili, non solo quelle che qualcuno ha pensato di *)
(* provare. Lo lancia collaudi/esame_tla.py, in CI a ogni unione.          *)
(*                                                                         *)
(* Riscritto il 23/11/2026 leggendo il codice di quel giorno (master       *)
(* 8746be5). Il modello di ottobre (strumenti_verifica\tla\Garanzia.tla,   *)
(* fuori dal progetto) non conosceva il blocco sulla carta, l'incasso, la  *)
(* cancellazione con penale ne' il registro dei bonifici; ha trovato il    *)
(* buco «190 usciti su 100» riparato dalla PR #342.                         *)
(*                                                                         *)
(* DIFETTO = "nessuno" e' il codice di oggi: le regole in fondo devono     *)
(* reggere su ogni sequenza. Ogni altro valore rimette UN difetto gia'     *)
(* riparato, togliendo la sua guardia: TLC lo deve trovare. Cosi' il       *)
(* controllo e' visto fallire, non solo passare. Quale riga del codice fa  *)
(* valere ogni guardia lo tiene collaudi/esame_tla.py (ANCORE).            *)
(*                                                                         *)
(* Un passo qui = una funzione di fase83_server.py, fase160 o fase131,     *)
(* eseguita tutta insieme: e' cosi' nel codice, che le tiene sotto         *)
(* _BONIFICI_LOCK o in una transazione BEGIN IMMEDIATE.                    *)
(***************************************************************************)
EXTENDS Integers

CONSTANT DIFETTO

DIFETTI == {"nessuno", "persa_divide", "arbitro_prima_della_banca",
            "banca_su_reclamo_ignorata", "banca_non_trattiene", "trattenuto_paga",
            "bonifico_su_blocco", "doppio_bonifico", "cancella_in_contestazione",
            "rimborso_su_garanzia_chiusa", "rilascio_su_contestato",
            "riallinea_senza_in_attesa"}
ASSUME DIFETTO \in DIFETTI

P    == 100   \* il prezzo pagato dall'ospite
Q    == 90    \* la quota dell'host in garanzia (importo_host_cents)
PEN  == 50    \* la penale di una cancellazione con penale (fase111)
QPEN == 45    \* la parte della penale che tiene l'host (chiudi_proporzionale)

VARIABLES
    tempo,      \* ripensamento (48 ore) -> prima dell'arrivo -> soggiorno -> dopo la garanzia
    pren,       \* stato della prenotazione (fase162): pagato | rimborsato | cancellata_host
    blocco,     \* blocco sulla carta (fase162 blocco_della_carta): nessuno|aperto|incassato|annullato
    incassato,  \* i soldi che Stripe ha DAVVERO preso dall'ospite
    gz,         \* la garanzia (fase160): in_garanzia|contestato|rilasciato|risolto|annullato
    motivo,     \* chi ha aperto la controversia: nessuno | ospite | banca («chargeback:...»)
    aperta,     \* la contestazione della banca e' aperta su Stripe
    esito,      \* come l'ha chiusa la banca: nessuno | vinta | persa
    pay,        \* la riga del bonifico (fase131): in_attesa|maturato|trattenuto|partito|tolto
    payImp,     \* l'importo della riga: «comanda il ledger payout» (_trasferisci_sotto_chiave)
    bon,        \* i soldi partiti verso l'host
    rimb,       \* i rimborsi all'ospite decisi da noi
    rb,         \* i soldi che la banca ha ripreso per l'ospite (Stripe li toglie a noi)
    grido,      \* un ERROR ha detto «bonifico gia' partito: va recuperato dall'host»
    dopoPersa   \* (fantasma) noi abbiamo mosso soldi dopo una contestazione PERSA

vars == <<tempo, pren, blocco, incassato, gz, motivo, aperta, esito,
          pay, payImp, bon, rimb, rb, grido, dopoPersa>>

(* Il pagamento: subito (arrivo vicino) o bloccato sulla carta (fase85            *)
(* blocco_sulla_carta, arrivo lontano). Col blocco il bonifico nasce 'in_attesa'  *)
(* (registra_in_attesa) e diventa 'maturato' solo all'incasso.                    *)
Init == /\ tempo = "ripensamento"
        /\ pren = "pagato"
        /\ blocco \in {"nessuno", "aperto"}
        /\ incassato = IF blocco = "nessuno" THEN P ELSE 0
        /\ gz = "in_garanzia"
        /\ motivo = "nessuno"
        /\ aperta = FALSE
        /\ esito = "nessuno"
        /\ pay = IF blocco = "nessuno" THEN "maturato" ELSE "in_attesa"
        /\ payImp = Q
        /\ bon = 0 /\ rimb = 0 /\ rb = 0
        /\ grido = FALSE
        /\ dopoPersa = FALSE

(* La regola del fondatore del 22/11: dopo una contestazione PERSA da noi non     *)
(* esce piu' niente, ne' all'ospite ne' all'host.                                *)
Segna == dopoPersa' = (dopoPersa \/ (esito = "persa" /\ (rimb' > rimb \/ bon' > bon)))

Tempo == /\ \/ tempo = "ripensamento" /\ tempo' = "prima"
            \/ tempo = "prima"        /\ tempo' = "soggiorno"
            \/ tempo = "soggiorno"    /\ tempo' = "dopo"
         /\ UNCHANGED <<pren, blocco, incassato, gz, motivo, aperta, esito,
                        pay, payImp, bon, rimb, rb, grido, dopoPersa>>

(* _incassa_blocchi -> _incassa_blocco: finita la finestra, una prenotazione      *)
(* 'pagato' si INCASSA (riletta sotto il lucchetto).                              *)
(* Ogni strada e' un passo a se': la copertura di TLC conta i passi, e una strada *)
(* dentro un passo che non scatta piu' non si vedrebbe (code-review, 23/11).       *)
GiroIncassa ==
    /\ blocco = "aperto" /\ pren = "pagato" /\ tempo # "ripensamento"
    /\ blocco' = "incassato" /\ incassato' = P
    /\ pay' = IF pay = "in_attesa" THEN "maturato" ELSE pay   \* _riasserisci_incasso
    /\ UNCHANGED <<tempo, pren, gz, motivo, aperta, esito, payImp, bon, rimb, rb,
                   grido, dopoPersa>>

(* Stripe dice 'canceled': l'autorizzazione e' scaduta, soldi mai entrati.        *)
GiroScade ==
    /\ blocco = "aperto" /\ pren = "pagato" /\ tempo # "ripensamento"
    /\ blocco' = "annullato"
    /\ UNCHANGED <<tempo, pren, incassato, gz, motivo, aperta, esito, pay, payImp, bon,
                   rimb, rb, grido, dopoPersa>>

(* _incassa_blocchi, prenotazione chiusa con l'annullo fallito: si ANNULLA.       *)
GiroAnnulla ==
    /\ blocco = "aperto" /\ pren # "pagato"
    /\ blocco' = "annullato"
    /\ UNCHANGED <<tempo, pren, incassato, gz, motivo, aperta, esito, pay, payImp, bon,
                   rimb, rb, grido, dopoPersa>>

(* ... e se Stripe risponde 'succeeded' i soldi sono entrati un istante prima: si *)
(* scrive il rimborso dovuto (voce 143, R3).                                      *)
GiroGiaIncassato ==
    /\ blocco = "aperto" /\ pren # "pagato"
    /\ blocco' = "incassato" /\ incassato' = P /\ rimb' = rimb + P
    /\ UNCHANGED <<tempo, pren, gz, motivo, aperta, esito, pay, payImp, bon, rb, grido>>
    /\ Segna

(* I due freni comuni alle tre strade che restituiscono i soldi (cancellazione    *)
(* dell'ospite, dell'host, rimborso dell'admin): _garanzia_gia_divisa e           *)
(* _controversia_aperta.                                                          *)
GaranziaDecisa == gz \in {"risolto", "rilasciato"} \/ pay = "partito"
PuoChiudere == /\ pren = "pagato"
               /\ ~GaranziaDecisa \/ DIFETTO = "rimborso_su_garanzia_chiusa"
               /\ gz # "contestato" \/ DIFETTO = "cancella_in_contestazione"

(* Restituire TUTTO: _chiudi_blocco (un blocco aperto si annulla, niente          *)
(* rimborso per soldi mai entrati; annullo fallito = lo ritenta GiroAnnulla),     *)
(* garanzia annullata (fase160 annulla), riga del bonifico tolta.                 *)
Restituisci(chi) ==
    /\ pren' = chi
    /\ IF blocco = "aperto"
         THEN /\ blocco' \in {"annullato", "aperto"}
              /\ UNCHANGED <<incassato, rimb>>
         ELSE /\ UNCHANGED <<blocco, incassato>>
              /\ rimb' = rimb + incassato
    /\ gz' = IF gz \in {"in_garanzia", "contestato"} THEN "annullato" ELSE gz
    /\ pay' = IF pay = "partito" THEN pay ELSE "tolto"
    /\ UNCHANGED <<tempo, motivo, aperta, esito, payImp, bon, rb, grido>>
    /\ Segna

(* _cancella_prenotazione senza penale (ripensamento, politica): restituisce tutto. *)
CancellaSenzaPenale ==
    /\ tempo \in {"ripensamento", "prima"} /\ PuoChiudere
    /\ Restituisci("rimborsato")

(* ... con la penale si INCASSA tutto (un incasso parziale libererebbe il resto)  *)
(* e si rimborsa la parte; la garanzia si divide (chiudi_proporzionale).          *)
CancellaConPenale ==
    /\ tempo = "prima" /\ PuoChiudere /\ blocco # "annullato"
    /\ pren' = "rimborsato"
    /\ blocco' = IF blocco = "aperto" THEN "incassato" ELSE blocco
    /\ incassato' = P
    /\ rimb' = rimb + (P - PEN)
    /\ gz' = IF gz = "in_garanzia" THEN "risolto" ELSE gz
    /\ payImp' = IF gz = "in_garanzia" THEN QPEN ELSE payImp
    /\ pay' = IF gz = "in_garanzia" /\ pay # "partito" THEN "maturato" ELSE pay
    /\ UNCHANGED <<tempo, motivo, aperta, esito, bon, rb, grido>>
    /\ Segna

CancellaHost == /\ tempo \in {"ripensamento", "prima"} /\ PuoChiudere   \* _host_cancella
                /\ Restituisci("cancellata_host")

AdminRimborso == PuoChiudere /\ Restituisci("rimborsato")                 \* _admin_rimborso

(* fase160: «tutto ok» dell'ospite (conferma_ospite), la sua segnalazione         *)
(* (contesta) e il rilascio automatico a garanzia scaduta (auto_rilascia, CAS     *)
(* su 'in_garanzia'; salta_se chiude 'annullato' una prenotazione rimborsata).    *)
ConfermaOspite ==
    /\ tempo = "soggiorno" /\ pren = "pagato" /\ gz = "in_garanzia"
    /\ gz' = "rilasciato"
    /\ UNCHANGED <<tempo, pren, blocco, incassato, motivo, aperta, esito, pay, payImp,
                   bon, rimb, rb, grido, dopoPersa>>

Segnala ==
    /\ tempo = "soggiorno" /\ pren = "pagato" /\ gz = "in_garanzia"
    /\ gz' = "contestato" /\ motivo' = "ospite"
    /\ UNCHANGED <<tempo, pren, blocco, incassato, aperta, esito, pay, payImp,
                   bon, rimb, rb, grido, dopoPersa>>

AutoRilascio ==
    /\ tempo = "dopo"
    /\ gz = "in_garanzia" \/ (DIFETTO = "rilascio_su_contestato" /\ gz = "contestato")
    /\ gz' = IF pren = "pagato" THEN "rilasciato" ELSE "annullato"
    /\ UNCHANGED <<tempo, pren, blocco, incassato, motivo, aperta, esito, pay, payImp,
                   bon, rimb, rb, grido, dopoPersa>>

(* _trasferisci_sotto_chiave: si paga la riga 'maturato' (mai 'trattenuto', mai   *)
(* una gia' partita), solo su soldi INCASSATI (blocco ne' aperto ne' annullato),  *)
(* a garanzia data all'host o divisa; dopo un rimborso solo la quota della        *)
(* penale (garanzia 'risolto').                                                   *)
Bonifico ==
    /\ gz \in {"rilasciato", "risolto"}
    /\ pren = "pagato" \/ (pren = "rimborsato" /\ gz = "risolto")
    /\ \/ pay = "maturato"
       \/ DIFETTO = "trattenuto_paga" /\ pay = "trattenuto"
       \/ DIFETTO = "doppio_bonifico" /\ pay = "partito"
    /\ blocco \in {"nessuno", "incassato"} \/ DIFETTO = "bonifico_su_blocco"
    /\ payImp > 0
    /\ bon' = bon + payImp /\ pay' = "partito"
    /\ UNCHANGED <<tempo, pren, blocco, incassato, gz, motivo, aperta, esito, payImp,
                   rimb, rb, grido>>
    /\ Segna

(* _contestazione_carta: la banca contesta un addebito INCASSATO. Stripe toglie   *)
(* subito l'importo dal nostro saldo («Stripe debits dispute amounts», docs       *)
(* connect/disputes). La garanzia si ferma (contesta, o segna_contestazione_banca  *)
(* se l'ospite aveva gia' segnalato), il bonifico non partito diventa             *)
(* 'trattenuto'; se e' gia' partito un ERROR lo dice: va recuperato dall'host.    *)
BancaApre ==
    /\ ~aperta /\ esito = "nessuno" /\ incassato = P
    /\ aperta' = TRUE
    /\ rb' = IF incassato > rimb THEN incassato - rimb ELSE 0
    /\ gz' = IF gz = "in_garanzia" THEN "contestato" ELSE gz
    /\ motivo' = IF gz = "in_garanzia"
                    \/ (gz = "contestato" /\ DIFETTO # "banca_su_reclamo_ignorata")
                 THEN "banca" ELSE motivo
    /\ pay' = IF pay \in {"in_attesa", "maturato"} /\ DIFETTO # "banca_non_trattiene"
              THEN "trattenuto" ELSE pay
    /\ grido' = (grido \/ pay = "partito")
    /\ UNCHANGED <<tempo, pren, blocco, incassato, esito, payImp, bon, rimb, dopoPersa>>

(* La banca decide (charge.dispute.closed): vinta = i soldi tornano a noi.        *)
BancaVince ==
    /\ aperta
    /\ aperta' = FALSE /\ esito' = "vinta" /\ rb' = 0
    /\ UNCHANGED <<tempo, pren, blocco, incassato, gz, motivo, pay, payImp, bon, rimb,
                   grido, dopoPersa>>

BancaPerde ==
    /\ aperta
    /\ aperta' = FALSE /\ esito' = "persa"
    /\ UNCHANGED <<tempo, pren, blocco, incassato, gz, motivo, pay, payImp, bon, rimb, rb,
                   grido, dopoPersa>>

(* _admin_controversia_risolvi: con la banca aspetta la sua decisione             *)
(* (decide_la_banca). PERSA = nessuno pagato: chiudi_contestazione_persa, riga    *)
(* del bonifico tolta (gia' partita: un ERROR dice di recuperarla dall'host).     *)
PersaQui == motivo = "banca" /\ esito = "persa"

ArbitroPersa ==
    /\ gz = "contestato" /\ PersaQui /\ DIFETTO # "persa_divide"
    /\ gz' = "risolto"
    /\ pay' = IF pay = "partito" THEN pay ELSE "tolto"
    /\ grido' = (grido \/ pay = "partito")
    /\ UNCHANGED <<tempo, pren, blocco, incassato, motivo, aperta, esito, payImp, bon,
                   rimb, rb, dopoPersa>>

(* Altrimenti divide la quota in garanzia (risolvi) e riallinea la riga del       *)
(* bonifico alla parte dell'host (riallinea_maturato); tutta all'ospite = riga    *)
(* tolta, come nella PERSA.                                                       *)
Quota(pct) == (Q * pct) \div 100

ArbitroDivide(pct) ==
    /\ gz = "contestato"
    /\ \/ motivo = "ospite"
       \/ motivo = "banca" /\ esito = "vinta"
       \/ motivo = "banca" /\ esito = "nessuno" /\ DIFETTO = "arbitro_prima_della_banca"
       \/ PersaQui /\ DIFETTO = "persa_divide"
    /\ LET r     == Quota(pct)
           riall == IF DIFETTO = "riallinea_senza_in_attesa"
                    THEN {"maturato", "trattenuto"}
                    ELSE {"maturato", "trattenuto", "in_attesa"}
       IN /\ gz' = "risolto"
          /\ rimb' = rimb + r
          /\ grido' = (grido \/ pay = "partito")
          /\ IF r >= Q
               THEN /\ pay' = IF pay = "partito" THEN pay ELSE "tolto"
                    /\ UNCHANGED payImp
               ELSE /\ pay' = IF pay \in riall THEN "maturato" ELSE pay
                    /\ payImp' = IF pay \in riall THEN Q - r ELSE payImp
    /\ UNCHANGED <<tempo, pren, blocco, incassato, motivo, aperta, esito, bon, rb>>
    /\ Segna

Next == \/ Tempo \/ GiroIncassa \/ GiroScade \/ GiroAnnulla \/ GiroGiaIncassato
        \/ CancellaSenzaPenale \/ CancellaConPenale \/ CancellaHost \/ AdminRimborso
        \/ ConfermaOspite \/ Segnala \/ AutoRilascio \/ Bonifico
        \/ BancaApre \/ BancaVince \/ BancaPerde \/ ArbitroPersa
        \/ \E pct \in {0, 50, 100} : ArbitroDivide(pct)

Spec == Init /\ [][Next]_vars

(* Tetto degli stati: serve solo alla variante col bonifico doppio, che senza     *)
(* tetto crescerebbe per sempre. Non nasconde niente: i soldi crescono a passi    *)
(* di al massimo P, quindi per superare il tetto si passa per forza da uno stato  *)
(* che gia' viola SoldiNostri, e TLC si ferma li'.                               *)
Limite == bon <= 2 * P /\ rimb <= 3 * P

(***************************************************************************)
(* LE REGOLE. Ognuna e' controllata su OGNI stato raggiungibile.           *)
(***************************************************************************)
TypeOK == /\ tempo \in {"ripensamento", "prima", "soggiorno", "dopo"}
          /\ pren \in {"pagato", "rimborsato", "cancellata_host"}
          /\ blocco \in {"nessuno", "aperto", "incassato", "annullato"}
          /\ incassato \in {0, P}
          /\ gz \in {"in_garanzia", "contestato", "rilasciato", "risolto", "annullato"}
          /\ motivo \in {"nessuno", "ospite", "banca"}
          /\ aperta \in BOOLEAN
          /\ esito \in {"nessuno", "vinta", "persa"}
          /\ pay \in {"in_attesa", "maturato", "trattenuto", "partito", "tolto"}
          /\ payImp \in 0..Q
          /\ bon \in Nat /\ rimb \in Nat /\ rb \in 0..P
          /\ grido \in BOOLEAN /\ dopoPersa \in BOOLEAN

\* rimborsi decisi + bonifici all'host non superano mai il prezzo pagato
SoldiNostri == rimb + bon <= P
\* nessun bonifico all'host su soldi solo autorizzati o mai entrati
BonificoSoloSuIncasso == bon > 0 => incassato = P
\* l'host non riceve mai piu' della sua quota (un bonifico solo)
Doppio == bon <= Q
\* l'ospite non riceve mai piu' di quanto ha pagato, fra noi e la sua banca
OspiteUnaVolta == rimb + rb <= P
\* tutto quello che esce (noi + la banca) sta nel prezzo, oppure un ERROR l'ha detto
Totale == rimb + rb + bon <= P \/ grido
\* contestazione PERSA = da quel momento nessuno e' pagato (decisione del 22/11)
NienteDopoLaPersa == ~dopoPersa
\* una segnalazione dell'ospite la chiude l'arbitro, non il rilascio automatico
ReclamoAspettaLArbitro == motivo = "ospite" => gz \in {"contestato", "risolto"}
=============================================================================
