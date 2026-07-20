"""
fase163 — CONTRATTO HOST + REGISTRO D'ACCETTAZIONE a prova di manomissione.

Perche' esiste (piu' avanti dei colossi):
  Il testo dei termini, da solo, in causa vale poco: serve la PROVA di CHI ha accettato
  QUALE versione ESATTA, QUANDO e DA DOVE. Questo modulo tiene un registro APPEND-ONLY,
  ogni riga firmata HMAC col segreto di sistema -> se qualcuno altera la riga nel DB, la
  firma non torna e noi lo dimostriamo. Cattura: versione, HASH del testo accettato (cosi'
  proviamo il contenuto esatto, non la loro parola), lingua mostrata, IP, dispositivo,
  e la SPECIFICA approvazione delle clausole vessatorie (art. 1341-1342 c.c.) che rende
  valide in Italia manleva, limitazione di responsabilita', foro e penali.

Onesta': il TESTO e' una bozza robusta ispirata ai leader di settore; prima del lancio con
denaro reale va fatto revisionare da un legale per le giurisdizioni target. La MACCHINA
(clickwrap versionato + prova firmata + doppia spunta vessatorie) e' cio' che rende
l'accettazione realmente opponibile, ed e' completa e testata.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import sqlite3
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Bump questa versione a OGNI modifica sostanziale del testo -> gli host dovranno ri-accettare.
CONTRATTO_HOST_VERSIONE = "2026-07-20"

# ── TESTO DEL CONTRATTO (it = lingua che fa fede) ─────────────────────────────
_IT = """CONTRATTO HOST BOOKINVIP — Versione {VER}

PREMESSA — Ruolo di BookinVIP.
BookinVIP e' una piattaforma tecnologica di intermediazione che mette in contatto chi
offre un alloggio ("Host") con chi lo prenota ("Ospite"). BookinVIP NON e' proprietaria,
gestore, locatore ne' fornitrice degli alloggi, NON e' parte del contratto di ospitalita'
tra Host e Ospite e non presta servizi di alloggio. L'Host offre e gestisce il proprio
alloggio in piena autonomia e sotto la propria esclusiva responsabilita'.

ART. 1 — DEFINIZIONI.
"Piattaforma": il sito, le app e le API di BookinVIP. "Annuncio": la scheda dell'alloggio
pubblicata dall'Host. "Commissione": il corrispettivo dovuto a BookinVIP per il servizio
di intermediazione. "Payout": la somma spettante all'Host per un soggiorno.

ART. 2 — OGGETTO.
Il presente contratto disciplina l'uso della Piattaforma da parte dell'Host per pubblicare
annunci, ricevere prenotazioni e incassare i relativi importi tramite gli strumenti di
BookinVIP. L'accettazione e' condizione necessaria per usare la Piattaforma come Host.

ART. 3 — REQUISITI E GARANZIE DELL'HOST (LEGALITA' NEL PROPRIO PAESE).
L'Host dichiara e garantisce, sotto la propria esclusiva responsabilita', che:
 (a) ha il pieno diritto e titolo di offrire in locazione/ospitalita' l'alloggio (proprieta'
     o autorizzazione scritta del proprietario, del condominio e di ogni avente diritto);
 (b) rispetta TUTTE le leggi e i regolamenti del proprio Paese e localita', incluse a titolo
     esemplificativo: licenze e autorizzazioni per l'affitto breve/turistico (es. in Italia il
     Codice Identificativo Nazionale-CIN e ove previsto la SCIA), la comunicazione degli
     alloggiati alle autorita' di pubblica sicurezza (es. Alloggiati Web), i regolamenti
     condominiali e la destinazione d'uso, le norme di sicurezza (rilevatori di fumo/gas,
     estintori, impianti a norma) e gli obblighi assicurativi di responsabilita' civile;
 (c) e' l'unico responsabile della veridicita' dell'Annuncio: foto reali e attuali del
     medesimo alloggio, servizi realmente presenti, capienza, posizione e prezzo corretti;
 (d) manterra' validi nel tempo i suddetti titoli, licenze e requisiti per tutta la durata.
L'Host esibira' a BookinVIP, su richiesta, la documentazione comprovante quanto sopra.

ART. 4 — FISCALITA' (RESPONSABILITA' ESCLUSIVA DELL'HOST).
L'Host e' l'unico responsabile di tutti gli obblighi fiscali derivanti dalla propria attivita':
imposte sui redditi, IVA ove dovuta, eventuale cedolare secca, e in particolare la RACCOLTA e
il VERSAMENTO della tassa/imposta di soggiorno al Comune competente. BookinVIP non e' sostituto
d'imposta ne' responsabile delle imposte dell'Host, salvo dove una legge imperativa imponga alla
piattaforma specifici obblighi di ritenuta o comunicazione (es. DAC7 UE), che BookinVIP adempira'
richiedendo all'Host i dati necessari; la mancata fornitura di tali dati e' a rischio dell'Host.

ART. 5 — OBBLIGHI OPERATIVI.
L'Host si impegna a: mantenere il calendario aggiornato ed evitare l'overbooking; onorare ogni
prenotazione confermata; applicare in modo leale la politica di cancellazione dichiarata;
comunicare con l'Ospite tramite la Piattaforma; consegnare l'alloggio conforme all'Annuncio.

ART. 6 — COMMISSIONI E PAGAMENTI.
All'Host e' dovuta la Commissione secondo il tariffario vigente pubblicato in Piattaforma.
BookinVIP applica il modello a costo zero per l'Ospite: la Commissione e' trattenuta dal Payout
dell'Host. Il Payout matura a soggiorno regolarmente avvenuto. BookinVIP ha diritto di
TRATTENERE, COMPENSARE o RECUPERARE dai Payout presenti o futuri dell'Host ogni importo a
qualunque titolo dovuto dall'Host (penali, rimborsi all'Ospite, storni/chargeback, costi,
sanzioni), anche senza preventivo consenso ulteriore.

ART. 6-BIS — TARIFFA TECNICA DI ELABORAZIONE DEI PAGAMENTI (SEMPRE DOVUTA).
Oltre alla Commissione, resta a carico esclusivo dell'Host una TARIFFA TECNICA FISSA pari al
3% (tre per cento) dell'importo della transazione, a copertura dei costi del gateway di
pagamento (Stripe), trattenuta automaticamente al momento del pagamento. Tale tariffa e'
SEMPRE dovuta, per l'intero ciclo di vita dell'Host sulla Piattaforma, e si applica anche nei
periodi in cui la Commissione di piattaforma e' pari allo 0%. Riepilogo del tariffario vigente:
 (a) prenotazioni provenienti dal marketplace BookinVIP: Commissione 0% nei primi 90 (novanta)
     giorni dalla registrazione dell'Host; 8% dal 91esimo giorno e fino a 1 (un) anno; 10% a
     regime oltre 1 (un) anno — in ogni caso OLTRE alla tariffa tecnica del 3%;
 (b) prenotazioni provenienti dal link diretto dell'Host: Commissione 5%, OLTRE alla tariffa
     tecnica del 3%.
BookinVIP non consegue alcun margine sulla tariffa tecnica, destinata a coprire i costi del
servizio di pagamento. L'Ospite non sostiene alcuna commissione (modello 0% Ospite).

ART. 7 — DIVIETO DI DISINTERMEDIAZIONE (ANTI-CIRCONVENZIONE).
E' vietato all'Host dirottare fuori dalla Piattaforma prenotazioni originate su di essa, o
sollecitare l'Ospite a prenotare altrove, o scambiare contatti/pagamenti allo scopo di evitare
la Commissione. La violazione comporta una penale pari alla Commissione elusa maggiorata del
50%, oltre alla sospensione o risoluzione, fatto salvo il maggior danno.

ART. 8 — ANTIFRODE E PENALI ("CHI SBAGLIA PAGA").
Costituiscono grave inadempimento, sanzionabili con penali, storno del Payout, sospensione o
risoluzione e RIVALSA per i costi e i danni: annunci o foto non veritieri, alloggi inesistenti
o difformi, doppie prenotazioni o no-show imputabili all'Host, recensioni o identita' false,
qualsiasi condotta ingannevole verso l'Ospite o BookinVIP. L'Host risponde inoltre dei
chargeback e delle contestazioni di pagamento causati da una propria inadempienza.

ART. 9 — MANLEVA E INDENNIZZO.
L'Host TIENE INDENNE e MANLEVA BookinVIP, i suoi amministratori e collaboratori, da qualsiasi
pretesa, azione, danno, perdita, sanzione, tributo, costo e spesa (incluse spese legali)
derivanti da o connessi a: (i) violazione da parte dell'Host di legge, regolamento o del presente
contratto; (ii) l'alloggio e il soggiorno, inclusi danni o lesioni a Ospiti o terzi; (iii) pretese
di autorita' fiscali, comunali o amministrative relative all'Host; (iv) violazione di diritti di
terzi. Chi sbaglia paga: le conseguenze economiche delle violazioni dell'Host restano a suo carico.

ART. 10 — LIMITAZIONE DI RESPONSABILITA' DI BOOKINVIP.
BookinVIP fornisce un servizio di sola intermediazione e non garantisce l'idoneita', la
sicurezza o la legalita' degli alloggi ne' la condotta di Host e Ospiti. Nei limiti massimi
consentiti dalla legge, la responsabilita' complessiva di BookinVIP verso l'Host per qualsiasi
titolo e' limitata all'importo delle Commissioni effettivamente incassate da BookinVIP per la
prenotazione da cui deriva la pretesa; e' esclusa ogni responsabilita' per danni indiretti,
consequenziali o da lucro cessante. Nulla esclude responsabilita' non escludibili per legge.

ART. 11 — SOSPENSIONE E RISOLUZIONE.
BookinVIP puo' sospendere o rimuovere un Annuncio e sospendere o risolvere l'account dell'Host
in caso di violazione del presente contratto o di rischio per Ospiti, terzi o per la Piattaforma,
con preavviso proporzionato o, in caso di frode o rischio grave e imminente, con effetto immediato.
Restano dovute all'Host le somme maturate e non contestate, al netto di quanto BookinVIP ha diritto
di trattenere ai sensi dell'art. 6 e 8.

ART. 12 — DATI PERSONALI E PROVA D'ACCETTAZIONE.
L'Host acconsente a che BookinVIP registri e CONSERVI la prova della presente accettazione
(versione del documento, impronta informatica-hash del testo, data e ora, indirizzo IP,
dispositivo e specifica approvazione delle clausole vessatorie) per finalita' di prova, per la
durata dei termini di prescrizione applicabili. I dati sono trattati secondo l'informativa privacy.

ART. 13 — MODIFICHE.
BookinVIP puo' aggiornare il presente contratto dandone avviso. La pubblicazione di una nuova
versione richiede una nuova accettazione per continuare a operare come Host; l'uso della
Piattaforma dopo l'avviso, ove consentito dalla legge, vale come accettazione della nuova versione.

ART. 14 — LEGGE APPLICABILE E FORO.
Il presente contratto e' regolato dalla legge italiana. Per le controversie e' competente in via
esclusiva il foro della sede di BookinVIP, salve le tutele inderogabili spettanti all'Host ove
qualificabile come consumatore o in base a norme imperative del suo Paese di residenza.

ART. 15 — CLAUSOLE VESSATORIE (approvazione specifica ex artt. 1341-1342 c.c.).
Con la spunta specifica di approvazione, l'Host dichiara di aver letto e di APPROVARE
espressamente le seguenti clausole: Art. 6 (trattenuta e compensazione sui Payout),
Art. 7 (penale per disintermediazione), Art. 8 (penali, storno e rivalsa), Art. 9 (manleva e
indennizzo), Art. 10 (limitazione di responsabilita' di BookinVIP), Art. 11 (sospensione e
risoluzione), Art. 13 (modifiche unilaterali con nuova accettazione), Art. 14 (foro competente).

Accettando, l'Host dichiara di aver letto e compreso l'intero contratto e di accettarlo.
"""

_EN = """BOOKINVIP HOST AGREEMENT — Version {VER}

PREAMBLE — Role of BookinVIP.
BookinVIP is a technology intermediation platform connecting those who offer accommodation
("Host") with those who book it ("Guest"). BookinVIP is NOT the owner, manager, landlord or
provider of the accommodations, is NOT a party to the hospitality contract between Host and
Guest, and does not provide accommodation services. The Host offers and manages the
accommodation independently and under its sole responsibility.

ART. 1 — DEFINITIONS. "Platform": BookinVIP's site, apps and APIs. "Listing": the Host's
published accommodation. "Commission": the fee due to BookinVIP for intermediation.
"Payout": the amount due to the Host for a stay.

ART. 2 — SUBJECT. This agreement governs the Host's use of the Platform to publish listings,
receive bookings and collect the related amounts. Acceptance is required to use the Platform as a Host.

ART. 3 — HOST REQUIREMENTS AND WARRANTIES (LEGAL COMPLIANCE IN ITS COUNTRY).
The Host represents and warrants, under its sole responsibility, that: (a) it has full right and
title to offer the accommodation (ownership or written authorization of owner/condominium/rights
holders); (b) it complies with ALL laws and regulations of its country and locality, including
by way of example: short-term/tourist rental licenses and permits (e.g. in Italy the National
Identification Code-CIN and, where required, the SCIA), guest reporting to public-security
authorities, condominium rules and permitted use, safety rules (smoke/gas detectors, fire
extinguishers, compliant systems) and civil-liability insurance obligations; (c) it is solely
responsible for the truthfulness of the Listing: real and current photos of the same
accommodation, actually available amenities, correct capacity, location and price; (d) it will
keep such titles, licenses and requirements valid throughout. The Host shall provide supporting
documentation upon request.

ART. 4 — TAXES (SOLE RESPONSIBILITY OF THE HOST). The Host is solely responsible for all tax
obligations arising from its activity: income taxes, VAT where due, and in particular the
COLLECTION and PAYMENT of the tourist tax to the competent municipality. BookinVIP is not a
withholding agent nor responsible for the Host's taxes, save where a mandatory law imposes
specific obligations on the platform (e.g. EU DAC7), which BookinVIP will fulfil by requesting
the necessary data from the Host; failure to provide such data is at the Host's risk.

ART. 5 — OPERATIONAL OBLIGATIONS. The Host shall: keep the calendar up to date and avoid
overbooking; honour every confirmed booking; fairly apply the declared cancellation policy;
communicate with the Guest via the Platform; deliver the accommodation as described.

ART. 6 — COMMISSIONS AND PAYMENTS. The Commission is due per the published fee schedule.
BookinVIP applies a zero-cost model for the Guest: the Commission is withheld from the Host's
Payout. Payout accrues once the stay has duly taken place. BookinVIP may WITHHOLD, SET OFF or
RECOVER from present or future Payouts any amount owed by the Host on any basis (penalties,
Guest refunds, chargebacks, costs, sanctions).

ART. 6-BIS — PAYMENT PROCESSING TECHNICAL FEE (ALWAYS DUE). In addition to the Commission, a
FIXED TECHNICAL FEE of 3% (three per cent) of the transaction amount remains solely payable by
the Host, covering the costs of the payment gateway (Stripe), withheld automatically at the
time of payment. This fee is ALWAYS due, for the Host's entire lifecycle on the Platform, and
applies also during periods in which the platform Commission is 0%. Current fee schedule:
 (a) bookings from the BookinVIP marketplace: Commission 0% for the first 90 (ninety) days from
     the Host's registration; 8% from day 91 up to 1 (one) year; 10% thereafter — in each case
     IN ADDITION TO the 3% technical fee;
 (b) bookings from the Host's direct link: Commission 5%, IN ADDITION TO the 3% technical fee.
BookinVIP makes no margin on the technical fee, which covers payment-service costs. The Guest
bears no commission (0% Guest model).

ART. 7 — ANTI-CIRCUMVENTION. The Host may not divert off-Platform any booking originated on it,
solicit the Guest to book elsewhere, or exchange contacts/payments to avoid the Commission.
Breach entails a penalty equal to the avoided Commission plus 50%, plus suspension or termination,
without prejudice to greater damages.

ART. 8 — ANTI-FRAUD AND PENALTIES ("WHOEVER ERRS, PAYS"). The following are material breaches,
subject to penalties, Payout reversal, suspension or termination and recourse for costs and
damages: untruthful listings or photos, non-existent or non-conforming accommodations, double
bookings or Host-attributable no-shows, false reviews or identity, any deceptive conduct toward
the Guest or BookinVIP. The Host is also liable for chargebacks caused by its own breach.

ART. 9 — INDEMNIFICATION. The Host shall INDEMNIFY and HOLD HARMLESS BookinVIP from any claim,
action, damage, loss, sanction, tax, cost and expense (including legal fees) arising from or
connected to: (i) the Host's breach of law or of this agreement; (ii) the accommodation and the
stay, including harm to Guests or third parties; (iii) claims by tax or administrative authorities
relating to the Host; (iv) infringement of third-party rights.

ART. 10 — LIMITATION OF BOOKINVIP'S LIABILITY. BookinVIP provides intermediation only and does not
warrant the suitability, safety or legality of accommodations nor the conduct of Hosts and Guests.
To the maximum extent permitted by law, BookinVIP's total liability to the Host is limited to the
Commissions actually collected for the booking giving rise to the claim; indirect, consequential
or lost-profit damages are excluded. Liabilities that cannot be excluded by law are unaffected.

ART. 11 — SUSPENSION AND TERMINATION. BookinVIP may suspend or remove a Listing and suspend or
terminate the Host's account upon breach or risk to Guests, third parties or the Platform, with
proportionate notice or, in case of fraud or serious imminent risk, with immediate effect.

ART. 12 — PERSONAL DATA AND PROOF OF ACCEPTANCE. The Host consents to BookinVIP recording and
RETAINING proof of this acceptance (document version, text hash, date and time, IP address, device
and specific approval of onerous clauses) for evidentiary purposes for the applicable limitation
period, processed per the privacy notice.

ART. 13 — CHANGES. BookinVIP may update this agreement upon notice. A new version requires a new
acceptance to keep operating as a Host.

ART. 14 — GOVERNING LAW AND JURISDICTION. This agreement is governed by Italian law; the courts of
BookinVIP's registered office have exclusive jurisdiction, save mandatory protections available to
the Host as a consumer or under mandatory rules of its country of residence.

ART. 15 — ONEROUS CLAUSES (specific approval under Italian Civil Code arts. 1341-1342). By the
specific approval checkbox, the Host expressly approves: Art. 6 (withholding/set-off), Art. 7
(anti-circumvention penalty), Art. 8 (penalties, reversal, recourse), Art. 9 (indemnification),
Art. 10 (limitation of liability), Art. 11 (suspension and termination), Art. 13 (unilateral
changes), Art. 14 (jurisdiction).

By accepting, the Host declares having read and understood the entire agreement and accepts it.
"""

CONTRATTO_HOST: Dict[str, str] = {
    "it": _IT.replace("{VER}", CONTRATTO_HOST_VERSIONE),
    "en": _EN.replace("{VER}", CONTRATTO_HOST_VERSIONE),
}
LINGUE_CONTRATTO = tuple(CONTRATTO_HOST.keys())
DOCUMENTO_HOST = "contratto_host"


def testo_contratto(lang: str = "it") -> str:
    return CONTRATTO_HOST.get((lang or "it").lower(), CONTRATTO_HOST["it"])


def doc_sha256() -> str:
    """Impronta VINCOLANTE del contratto = hash della versione + testo che fa fede (it).
    Indipendente dalla lingua mostrata: prova UN contenuto per versione."""
    base = (CONTRATTO_HOST_VERSIONE + "\n" + CONTRATTO_HOST["it"]).encode("utf-8")
    return hashlib.sha256(base).hexdigest()


def documento_corrente(lang: str = "it") -> Dict[str, Any]:
    lang = (lang or "it").lower()
    if lang not in CONTRATTO_HOST:
        lang = "it"
    return {
        "documento": DOCUMENTO_HOST,
        "versione": CONTRATTO_HOST_VERSIONE,
        "doc_sha256": doc_sha256(),
        "lang": lang,
        "lingue": list(LINGUE_CONTRATTO),
        "testo": CONTRATTO_HOST[lang],
        "lingua_che_fa_fede": "it",
    }


class RegistroAccettazioni:
    """Registro APPEND-ONLY delle accettazioni, ogni riga firmata HMAC (a prova di manomissione)."""

    def __init__(self, db_path: str, segreto: bytes,
                 now: Optional[Any] = None) -> None:
        self._db = db_path
        self._seg = bytes(segreto)
        self._now = now or (lambda: int(time.time()))
        # :memory: = una SOLA connessione condivisa e persistente (altrimenti ogni connect
        # crea un DB vuoto separato e la tabella "sparisce"). Su file: connessione per-chiamata.
        self._mem = sqlite3.connect(":memory:", check_same_thread=False) \
            if db_path == ":memory:" else None

    def _apri(self) -> sqlite3.Connection:
        if self._mem is not None:
            return self._mem
        con = sqlite3.connect(self._db, timeout=30)
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.Error:
            pass
        return con

    def _chiudi(self, con: sqlite3.Connection) -> None:
        if con is not self._mem:      # la connessione :memory: condivisa resta aperta
            con.close()

    def inizializza_schema(self) -> None:
        con = self._apri()
        try:
            with con:
                con.execute("""
                    CREATE TABLE IF NOT EXISTS accettazioni (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        host_id TEXT NOT NULL,
                        documento TEXT NOT NULL,
                        versione TEXT NOT NULL,
                        doc_sha256 TEXT NOT NULL,
                        lang TEXT NOT NULL DEFAULT 'it',
                        ip TEXT NOT NULL DEFAULT '',
                        user_agent TEXT NOT NULL DEFAULT '',
                        vessatorie INTEGER NOT NULL DEFAULT 0,
                        accettato_ts INTEGER NOT NULL,
                        firma TEXT NOT NULL)""")
                con.execute("CREATE INDEX IF NOT EXISTS idx_acc_host "
                            "ON accettazioni(host_id)")
        finally:
            self._chiudi(con)

    def _firma(self, host_id: str, documento: str, versione: str, doc_sha256_: str,
               lang: str, ip: str, user_agent: str, vessatorie: int, ts: int) -> str:
        canonico = "|".join([
            host_id, documento, versione, doc_sha256_, lang, ip,
            user_agent, str(int(vessatorie)), str(int(ts))])
        return hmac.new(self._seg, canonico.encode("utf-8"), hashlib.sha256).hexdigest()

    def registra(self, host_id: Any, *, documento: str = DOCUMENTO_HOST,
                 versione: str = CONTRATTO_HOST_VERSIONE,
                 doc_sha256_: Optional[str] = None, lang: str = "it",
                 ip: str = "", user_agent: str = "", vessatorie: bool = False,
                 ts: Optional[int] = None) -> Dict[str, Any]:
        """Scrive UNA prova d'accettazione firmata. Ritorna {ok, id, firma, ...}."""
        if not (isinstance(host_id, str) and host_id):
            return {"ok": False, "errore": "host_id_mancante"}
        doc_hash = doc_sha256_ or doc_sha256()
        lang = (str(lang or "it").lower())[:8]
        ip = str(ip or "")[:64]
        ua = str(user_agent or "")[:400]
        vex = 1 if vessatorie else 0
        t = int(ts if ts is not None else self._now())
        firma = self._firma(host_id, documento, versione, doc_hash, lang, ip, ua, vex, t)
        con = self._apri()
        try:
            with con:
                cur = con.execute(
                    "INSERT INTO accettazioni (host_id, documento, versione, doc_sha256, "
                    "lang, ip, user_agent, vessatorie, accettato_ts, firma) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (host_id, documento, versione, doc_hash, lang, ip, ua, vex, t, firma))
            return {"ok": True, "id": cur.lastrowid, "host_id": host_id,
                    "documento": documento, "versione": versione, "doc_sha256": doc_hash,
                    "lang": lang, "vessatorie": bool(vex), "accettato_ts": t, "firma": firma}
        except Exception:
            logger.error("registra accettazione fallita (ISOLATA)", exc_info=True)
            return {"ok": False, "errore": "errore_interno"}
        finally:
            self._chiudi(con)

    def _riga_dict(self, r: sqlite3.Row) -> Dict[str, Any]:
        (id_, host_id, documento, versione, doc_hash, lang, ip, ua, vex, ts, firma) = r
        atteso = self._firma(host_id, documento, versione, doc_hash, lang, ip, ua, vex, ts)
        valida = hmac.compare_digest(atteso, firma)
        return {"id": id_, "host_id": host_id, "documento": documento, "versione": versione,
                "doc_sha256": doc_hash, "lang": lang, "ip": ip, "user_agent": ua,
                "vessatorie": bool(vex), "accettato_ts": ts, "firma": firma,
                "integra": valida}     # integra=False -> riga MANOMESSA

    def elenco(self, host_id: Any, documento: Optional[str] = None) -> List[Dict[str, Any]]:
        if not (isinstance(host_id, str) and host_id):
            return []
        con = self._apri()
        try:
            if documento:
                cur = con.execute(
                    "SELECT id,host_id,documento,versione,doc_sha256,lang,ip,user_agent,"
                    "vessatorie,accettato_ts,firma FROM accettazioni "
                    "WHERE host_id=? AND documento=? ORDER BY id",
                    (host_id, documento))
            else:
                cur = con.execute(
                    "SELECT id,host_id,documento,versione,doc_sha256,lang,ip,user_agent,"
                    "vessatorie,accettato_ts,firma FROM accettazioni "
                    "WHERE host_id=? ORDER BY id", (host_id,))
            return [self._riga_dict(r) for r in cur.fetchall()]
        except Exception:
            logger.error("elenco accettazioni fallito (ISOLATO)", exc_info=True)
            return []
        finally:
            self._chiudi(con)

    def ha_accettato_corrente(self, host_id: Any,
                              documento: str = DOCUMENTO_HOST) -> bool:
        """True se l'host ha una accettazione INTEGRA della versione corrente del documento."""
        for r in self.elenco(host_id, documento):
            if r["versione"] == CONTRATTO_HOST_VERSIONE and r["integra"]:
                return True
        return False

    def conta(self) -> int:
        con = self._apri()
        try:
            return int(con.execute("SELECT COUNT(*) FROM accettazioni").fetchone()[0])
        except Exception:
            return 0
        finally:
            self._chiudi(con)


def crea_registro_accettazioni(db_path: str, segreto: bytes,
                               now: Optional[Any] = None) -> RegistroAccettazioni:
    reg = RegistroAccettazioni(db_path, segreto, now=now)
    reg.inizializza_schema()
    return reg
