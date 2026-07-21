"""FASE 184 — MARCA TEMPORALE (RFC 3161): l'ora certificata da un TERZO indipendente.

IL PROBLEMA CHE CHIUDE
----------------------
Le nostre prove (accettazioni fase163, giornale contabile fase177) sono firmate da NOI.
In causa la controparte puo' obiettare: *"i registri e l'ora ve li siete scritti voi"*.
Una MARCA TEMPORALE RFC 3161 e' un token firmato da un'**Autorita' di Marcatura Temporale**
(TSA) che attesta: *"alle ore X esisteva un documento con questa impronta"*. Non e'
un'affermazione nostra: e' la firma di un terzo, verificabile da chiunque anche fra 10 anni.

COSA VEDE LA TSA — NULLA
------------------------
Le si manda **solo un'impronta SHA-256** (32 byte). Non i dati, non i nomi, non gli IP:
un'impronta e' a senso unico. Nessun trasferimento di dati personali (GDPR: nessun dato,
nessun trasferimento), e la TSA non puo' risalire a niente.

QUALIFICATA EUROPEA (eIDAS art. 42) — ATTIVA
--------------------------------------------
Le marche sono chieste a **prestatori QUALIFICATI europei** (ACCV/Spagna, QuoVadis EU,
Izenpe/Spagna, BOSA/Belgio). eIDAS art. 41 da' alla marca qualificata la **presunzione
legale** di esattezza della data e dell'ora e di integrita' dei dati: in giudizio non
tocca a noi dimostrare che l'ora e' giusta — tocca a chi contesta dimostrare il
contrario. E' un rovesciamento dell'onere della prova, ed e' il motivo per cui vale la
pena usarle.

La qualifica NON si crede sulla parola: `e_qualificata()` cerca dentro il token la
dichiarazione ETSI EN 319 422 `esi4-qtstStatement-1` (OID 0.4.0.19422.1.1) che il
prestatore appone sotto la propria responsabilita' e sotto vigilanza dell'organismo
nazionale. Ogni marca viene ARCHIVIATA con il suo esito: se un prestatore perdesse la
qualifica, la marca successiva risulterebbe subito non qualificata, senza che nessuno
debba accorgersene a mano.

Se nessun qualificato risponde si ripiega su TSA pubbliche non qualificate (DigiCert,
Sectigo, Entrust) **etichettando onestamente la marca come non qualificata**: meglio una
prova dichiarata per quello che e' che nessuna prova. Con `MARCA_SOLO_QUALIFICATA=1` il
ripiego e' vietato del tutto.

ZERO DIPENDENZE
---------------
ASN.1/DER e' scritto a mano qui sotto (encoder minimale + parser tollerante al BER a
lunghezza indefinita che alcune TSA restituiscono). Rete via `urllib` (stdlib).
Nessuna libreria esterna, coerente con la regola del progetto.

COME SI ACCENDE
---------------
  MARCA_TEMPORALE=1           (default: acceso)
  MARCA_SOLO_QUALIFICATA=1    vieta il ripiego non qualificato (default: 0, ripiega)
  TSA_URL=...                 una o piu' URL separate da virgola: scavalca la lista
  DB_MARCHE=/data/marche.db   archivio append-only dei token

MAI BLOCCANTE: se la rete o la TSA non rispondono, l'errore viene ARCHIVIATO e si riprova
al giro dopo. Nessuna funzione di questo modulo puo' rompere il money-path.
"""

import base64
import hashlib
import logging
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("core_auto.marca_temporale")

# ═════════════════════════════════════════════════════════════════════════════════
#  CHI FIRMA L'ORA — prima i QUALIFICATI europei (eIDAS art. 42)
# ═════════════════════════════════════════════════════════════════════════════════
# "Qualificata" non e' una parola di marketing: e' VERIFICABILE. Il certificato con cui
# la TSA firma deve contenere la dichiarazione ETSI EN 319 422 `esi4-qtstStatement-1`
# (OID 0.4.0.19422.1.1) = "emetto marche temporali QUALIFICATE". Qui non si crede a
# nessuno sulla parola: si guarda dentro il token (`e_qualificata`).
#
# SCELTI SUL CAMPO il 2026-07-21: interrogati dal vivo 16 endpoint di prestatori europei,
# controllata la dichiarazione ETSI dentro ogni token e provata la verifica con
# `openssl ts -verify` contro il SOLO archivio CA di sistema. Esito:
#   QUALIFICATI e verificabili da chiunque : ACCV (ES) · QuoVadis EU
#   QUALIFICATI ma serve la loro radice    : Izenpe (ES) · BOSA (BE)
#   NON qualificati                        : Certum, CESNET, DFN, Lex Persona
#   non hanno risposto                     : APED (GR), BalTstamp, Disig, SK ID, InfoCert
# Verificato anche che il container di produzione li raggiunga tutti (ACCV usa la porta
# 8318, non standard: sarebbe stato il classico guasto scoperto mesi dopo).
OID_QTST_ETSI = (0, 4, 0, 19422, 1, 1)      # esi4-qtstStatement-1: marca QUALIFICATA
OID_QC_COMPLIANCE = (0, 4, 0, 1862, 1, 1)   # QcCompliance: certificato qualificato

TSA_QUALIFICATE = (
    "http://tss.accv.es:8318/tsa",        # ACCV (Generalitat Valenciana, ES)
    "http://ts.quovadisglobal.com/eu",    # QuoVadis EU
    "http://tsa.izenpe.com",              # Izenpe (Paesi Baschi, ES)
    "http://tsa.belgium.be/connect",      # BOSA (Stato belga)
)

# RIPIEGO NON QUALIFICATO: si usa SOLO se nessun prestatore qualificato risponde, per non
# restare del tutto senza prova. La marca viene ARCHIVIATA COME NON QUALIFICATA e il
# Bunker lo mostra: meglio una prova onestamente etichettata che nessuna prova — ma il
# ripiego non deve mai potersi spacciare per una marca qualificata.
TSA_RIPIEGO = (
    "http://timestamp.digicert.com",
    "http://timestamp.sectigo.com",
    "http://timestamp.entrust.net/TSS/RFC3161sha2TS",
)

TSA_PREDEFINITE = TSA_QUALIFICATE + TSA_RIPIEGO

OID_SHA256 = (2, 16, 840, 1, 101, 3, 4, 2, 1)

# PKIStatus (RFC 3161 §2.4.2): solo 0 e 1 sono un rilascio valido.
STATI_CONCESSI = {0: "concessa", 1: "concessa_con_modifiche"}
STATI_RIFIUTO = {2: "rifiutata", 3: "in_attesa", 4: "avviso_revoca", 5: "revoca"}

VERSIONE_SIGILLO = "BOOKINVIP-SIGILLO-v1"


# ═════════════════════════════════════════════════════════════════════════════════
#  ASN.1 / DER — encoder minimale
# ═════════════════════════════════════════════════════════════════════════════════

def _der_lunghezza(n: int) -> bytes:
    """Codifica DER della lunghezza: forma corta sotto 128, altrimenti forma lunga."""
    if n < 0x80:
        return bytes([n])
    corpo = b""
    while n > 0:
        corpo = bytes([n & 0xFF]) + corpo
        n >>= 8
    return bytes([0x80 | len(corpo)]) + corpo


def _der(tag: int, contenuto: bytes) -> bytes:
    return bytes([tag]) + _der_lunghezza(len(contenuto)) + contenuto


def _der_intero(valore: int) -> bytes:
    """INTEGER DER. Complemento a due, minimo numero di byte, mai negativo per noi."""
    if valore == 0:
        return _der(0x02, b"\x00")
    if valore < 0:
        raise ValueError("interi negativi non previsti")
    corpo = b""
    v = valore
    while v > 0:
        corpo = bytes([v & 0xFF]) + corpo
        v >>= 8
    if corpo[0] & 0x80:          # bit alto acceso -> serve un byte 0x00 davanti
        corpo = b"\x00" + corpo  # altrimenti verrebbe letto come negativo
    return _der(0x02, corpo)


def _der_oid(archi: Tuple[int, ...]) -> bytes:
    """OBJECT IDENTIFIER: i primi due archi stanno in un byte (40*a + b), gli altri
    in base 128 big-endian con il bit di continuazione."""
    if len(archi) < 2:
        raise ValueError("OID troppo corto")
    corpo = bytes([40 * archi[0] + archi[1]])
    for a in archi[2:]:
        if a == 0:
            corpo += b"\x00"
            continue
        pezzi = []
        while a > 0:
            pezzi.insert(0, a & 0x7F)
            a >>= 7
        corpo += bytes([p | 0x80 for p in pezzi[:-1]] + [pezzi[-1]])
    return _der(0x06, corpo)


# ═════════════════════════════════════════════════════════════════════════════════
#  ASN.1 / DER — parser (tollerante al BER a lunghezza indefinita)
# ═════════════════════════════════════════════════════════════════════════════════

def _leggi_tlv(dati: bytes, i: int) -> Optional[Tuple[int, int, int, int]]:
    """Legge UN elemento a partire da `i`.
    Ritorna (tag, inizio_contenuto, fine_contenuto, fine_elemento) oppure None.

    Gestisce anche la LUNGHEZZA INDEFINITA (0x80) del BER: alcune TSA rispondono con
    CMS a lunghezza indefinita e un parser DER puro fallirebbe sul token vero."""
    n = len(dati)
    if i >= n:
        return None
    tag = dati[i]
    j = i + 1
    if (tag & 0x1F) == 0x1F:          # tag a piu' byte: non previsto nei nostri oggetti
        return None
    if j >= n:
        return None
    primo = dati[j]
    j += 1
    if primo < 0x80:
        fine = j + primo
        if fine > n:
            return None
        return (tag, j, fine, fine)
    if primo == 0x80:                  # indefinita: scorre i figli fino a 00 00
        if not (tag & 0x20):           # solo i costruiti possono essere indefiniti
            return None
        k = j
        while k < n:
            if dati[k] == 0x00 and k + 1 < n and dati[k + 1] == 0x00:
                return (tag, j, k, k + 2)
            figlio = _leggi_tlv(dati, k)
            if figlio is None:
                return None
            k = figlio[3]
        return None
    conta = primo & 0x7F
    if conta == 0 or conta > 4 or j + conta > n:
        return None
    lung = 0
    for b in dati[j:j + conta]:
        lung = (lung << 8) | b
    j += conta
    fine = j + lung
    if fine > n:
        return None
    return (tag, j, fine, fine)


def _figli(dati: bytes, inizio: int, fine: int) -> List[Tuple[int, int, int]]:
    """Elenco (tag, inizio_contenuto, fine_contenuto) dei figli di un costruito."""
    fuori = []
    i = inizio
    while i < fine:
        t = _leggi_tlv(dati, i)
        if t is None:
            break
        fuori.append((t[0], t[1], t[2]))
        if t[3] <= i:
            break
        i = t[3]
    return fuori


def _intero_da(dati: bytes, inizio: int, fine: int) -> int:
    v = 0
    for b in dati[inizio:fine]:
        v = (v << 8) | b
    return v


def _oid_da(dati: bytes, inizio: int, fine: int) -> Tuple[int, ...]:
    corpo = dati[inizio:fine]
    if not corpo:
        return ()
    archi = [corpo[0] // 40, corpo[0] % 40]
    v = 0
    for b in corpo[1:]:
        v = (v << 7) | (b & 0x7F)
        if not (b & 0x80):
            archi.append(v)
            v = 0
    return tuple(archi)


def _tutti_octet_string(dati: bytes, inizio: int, fine: int,
                        profondita: int = 0) -> List[bytes]:
    """Raccoglie ricorsivamente il contenuto di OGNI OCTET STRING dell'albero.
    Serve a pescare il TSTInfo dentro il CMS senza dover navigare tutto il CMS."""
    fuori = []
    if profondita > 24:
        return fuori
    for tag, i, f in _figli(dati, inizio, fine):
        if tag == 0x04:
            fuori.append(dati[i:f])
        if tag & 0x20:                 # costruito: scendi
            fuori.extend(_tutti_octet_string(dati, i, f, profondita + 1))
    return fuori


# ═════════════════════════════════════════════════════════════════════════════════
#  RFC 3161 — richiesta
# ═════════════════════════════════════════════════════════════════════════════════

def costruisci_richiesta(impronta_sha256: bytes, nonce: int) -> bytes:
    """TimeStampReq (RFC 3161 §2.4.1):
         SEQUENCE { version=1, messageImprint, nonce, certReq=TRUE }
    `certReq=TRUE` chiede alla TSA di includere il proprio certificato nel token:
    senza, fra dieci anni il token sarebbe verificabile solo procurandosi il
    certificato altrove. Con, il token e' AUTOSUFFICIENTE."""
    if not isinstance(impronta_sha256, bytes) or len(impronta_sha256) != 32:
        raise ValueError("l'impronta deve essere SHA-256 (32 byte)")
    algoritmo = _der(0x30, _der_oid(OID_SHA256) + _der(0x05, b""))   # AlgorithmIdentifier
    imprint = _der(0x30, algoritmo + _der(0x04, impronta_sha256))    # MessageImprint
    corpo = (_der_intero(1) + imprint + _der_intero(int(nonce))
             + _der(0x01, b"\xff"))                                  # certReq = TRUE
    return _der(0x30, corpo)


# ═════════════════════════════════════════════════════════════════════════════════
#  RFC 3161 — risposta
# ═════════════════════════════════════════════════════════════════════════════════

def _gen_time_a_epoch(grezzo: bytes) -> Optional[int]:
    """GeneralizedTime -> secondi UNIX. Formato 'YYYYMMDDHHMMSS[.fff]Z' (sempre UTC
    nei token RFC 3161)."""
    try:
        t = grezzo.decode("ascii").strip()
    except Exception:
        return None
    if not t.endswith("Z") or len(t) < 15:
        return None
    base = t[:14]
    if not base.isdigit():
        return None
    try:
        return int(__import__("calendar").timegm((
            int(base[0:4]), int(base[4:6]), int(base[6:8]),
            int(base[8:10]), int(base[10:12]), int(base[12:14]), 0, 1, -1)))
    except Exception:
        return None


def _leggi_tstinfo(blob: bytes, impronta_attesa: bytes) -> Optional[Dict[str, Any]]:
    """Prova a interpretare `blob` come TSTInfo (RFC 3161 §2.4.2):
         SEQUENCE { version, policy OID, messageImprint, serialNumber,
                    genTime, [accuracy] [ordering] [nonce] [tsa] [extensions] }
    Ritorna il contenuto SOLO se l'impronta dentro il token e' ESATTAMENTE la nostra:
    e' il controllo di sicurezza vero (un token che certifica un altro documento non
    ci serve e non deve essere accettato)."""
    t = _leggi_tlv(blob, 0)
    if t is None or t[0] != 0x30:
        return None
    campi = _figli(blob, t[1], t[2])
    if len(campi) < 5:
        return None
    if campi[0][0] != 0x02 or _intero_da(blob, campi[0][1], campi[0][2]) != 1:
        return None
    if campi[1][0] != 0x06:                       # policy OID
        return None
    if campi[2][0] != 0x30:                       # messageImprint
        return None
    imp = _figli(blob, campi[2][1], campi[2][2])
    if len(imp) != 2 or imp[1][0] != 0x04:
        return None
    impronta = blob[imp[1][1]:imp[1][2]]
    if impronta != impronta_attesa:               # ← il controllo che conta
        return None
    if campi[3][0] != 0x02:                       # serialNumber
        return None
    seriale = _intero_da(blob, campi[3][1], campi[3][2])
    if campi[4][0] != 0x18:                       # genTime
        return None
    quando = _gen_time_a_epoch(blob[campi[4][1]:campi[4][2]])
    if quando is None:
        return None
    nonce = None
    for tag, i, f in campi[5:]:                   # il primo INTEGER dopo genTime = nonce
        if tag == 0x02:
            nonce = _intero_da(blob, i, f)
            break
    return {"policy": ".".join(str(a) for a in _oid_da(blob, campi[1][1], campi[1][2])),
            "seriale": seriale, "gen_time": quando, "nonce": nonce,
            "impronta_hex": impronta.hex()}


def interpreta_risposta(risposta: bytes, impronta_attesa: bytes,
                        nonce_atteso: Optional[int] = None) -> Dict[str, Any]:
    """Legge una TimeStampResp e ne estrae l'attestazione, verificandola.

    Verifiche fatte QUI (tutte necessarie, nessuna e' cosmetica):
      1. lo stato PKI dice davvero 'concessa';
      2. il TSTInfo contiene ESATTAMENTE la nostra impronta (altrimenti scartato);
      3. il nonce torna -> la risposta e' per QUESTA richiesta, non un token
         vecchio rigiocato da chi sta in mezzo (anti-replay).

    NON verifica la firma crittografica della TSA sul token (richiederebbe X.509 +
    RSA/ECDSA, cioe' una dipendenza esterna). Il token viene ARCHIVIATO INTEGRO: la
    verifica della firma e' fattibile in qualsiasi momento da chiunque, con `openssl
    ts -verify`, dal giudice o dal suo perito. E' questo che conta in causa."""
    if not isinstance(risposta, (bytes, bytearray)) or not risposta:
        return {"ok": False, "motivo": "risposta_vuota"}
    dati = bytes(risposta)
    t = _leggi_tlv(dati, 0)
    if t is None or t[0] != 0x30:
        return {"ok": False, "motivo": "non_e_asn1"}
    campi = _figli(dati, t[1], t[2])
    if not campi or campi[0][0] != 0x30:
        return {"ok": False, "motivo": "manca_stato"}
    stato_campi = _figli(dati, campi[0][1], campi[0][2])
    if not stato_campi or stato_campi[0][0] != 0x02:
        return {"ok": False, "motivo": "stato_illeggibile"}
    stato = _intero_da(dati, stato_campi[0][1], stato_campi[0][2])
    if stato not in STATI_CONCESSI:
        return {"ok": False, "motivo": "stato_" + STATI_RIFIUTO.get(stato, str(stato)),
                "stato": stato}
    if len(campi) < 2:
        return {"ok": False, "motivo": "manca_token", "stato": stato}
    # Il token e' il secondo elemento: lo riprendiamo COMPLETO (con la sua intestazione)
    # perche' e' quello che va archiviato e riconsegnato tale e quale a un perito.
    inizio_token = None
    i = t[1]
    idx = 0
    while i < t[2]:
        e = _leggi_tlv(dati, i)
        if e is None:
            break
        if idx == 1:
            inizio_token = (i, e[3])
            break
        idx += 1
        i = e[3]
    if inizio_token is None:
        return {"ok": False, "motivo": "token_illeggibile", "stato": stato}
    token = dati[inizio_token[0]:inizio_token[1]]
    # Il TSTInfo e' incapsulato in un OCTET STRING dentro il CMS: lo si cerca fra tutti
    # gli OCTET STRING dell'albero e si accetta SOLO quello con la nostra impronta.
    tt = _leggi_tlv(token, 0)
    candidati = ([token] if tt is None else
                 _tutti_octet_string(token, tt[1], tt[2]) + [token])
    for blob in candidati:
        info = _leggi_tstinfo(blob, impronta_attesa)
        if info is None:
            continue
        if nonce_atteso is not None and info.get("nonce") not in (None, int(nonce_atteso)):
            return {"ok": False, "motivo": "nonce_diverso", "stato": stato}
        info.update({"ok": True, "stato": stato,
                     "stato_nome": STATI_CONCESSI[stato], "token": token})
        return info
    return {"ok": False, "motivo": "impronta_non_corrisponde", "stato": stato}


# ═════════════════════════════════════════════════════════════════════════════════
#  Rete
# ═════════════════════════════════════════════════════════════════════════════════

def e_qualificata(token: bytes) -> bool:
    """Il token e' una marca QUALIFICATA ai sensi di eIDAS art. 42?

    Non lo si deduce dal nome del prestatore ne' dalla sua pubblicita': si cerca dentro
    il certificato di firma la dichiarazione ETSI EN 319 422 `esi4-qtstStatement-1`
    (OID 0.4.0.19422.1.1). E' il prestatore stesso a metterla, sotto la propria
    responsabilita' e sotto vigilanza dell'organismo nazionale: se c'e', dichiara di
    emettere marche qualificate; se non c'e', la marca NON e' qualificata e va detto."""
    try:
        return _der_oid(OID_QTST_ETSI) in bytes(token or b"")
    except Exception:
        return False


def solo_qualificate() -> bool:
    """MARCA_SOLO_QUALIFICATA=1 -> mai ripiegare su un prestatore non qualificato
    (si preferisce nessuna marca a una marca di rango inferiore). Default: si ripiega,
    ma la marca resta ARCHIVIATA come non qualificata."""
    return str(os.environ.get("MARCA_SOLO_QUALIFICATA", "0")).strip().lower() \
        in ("1", "true", "yes", "si", "on")


def _tsa_configurate(url: Optional[str] = None) -> Tuple[str, ...]:
    """L'ordine e' la politica: prima i QUALIFICATI europei, poi — solo se nessuno
    risponde e non e' vietato — il ripiego non qualificato."""
    grezzo = url if url is not None else os.environ.get("TSA_URL", "")
    scelte = tuple(u.strip() for u in str(grezzo).split(",") if u.strip())
    if scelte:
        return scelte
    return TSA_QUALIFICATE if solo_qualificate() else TSA_PREDEFINITE


def chiedi_marca(impronta_sha256: bytes, *, url: Optional[str] = None,
                 timeout: float = 12.0, trasporto=None) -> Dict[str, Any]:
    """Chiede la marca alla prima TSA che risponde bene (failover in ordine).
    NON solleva MAI: in caso di guaio ritorna {'ok': False, ...} con il dettaglio.
    `trasporto` e' iniettabile per i test (nessuna rete nella suite)."""
    try:
        nonce = int.from_bytes(os.urandom(8), "big") or 1
        richiesta = costruisci_richiesta(impronta_sha256, nonce)
    except Exception as e:
        return {"ok": False, "motivo": "richiesta_non_costruita", "dettaglio": str(e)}
    tentativi = []
    for indirizzo in _tsa_configurate(url):
        try:
            if trasporto is not None:
                grezza = trasporto(indirizzo, richiesta, timeout)
            else:
                import urllib.request
                req = urllib.request.Request(
                    indirizzo, data=richiesta,
                    headers={"Content-Type": "application/timestamp-query",
                             "Accept": "application/timestamp-reply",
                             "User-Agent": "BookinVIP-TSA/1.0"})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    grezza = r.read()
            esito = interpreta_risposta(grezza, impronta_sha256, nonce_atteso=nonce)
            if esito.get("ok"):
                esito["tsa"] = indirizzo
                esito["nonce_inviato"] = nonce
                # QUALIFICATA? lo dice il certificato dentro il token, non la lista qui
                # sopra: se un prestatore perdesse la qualifica, la marca risulterebbe
                # subito non qualificata senza che nessuno debba accorgersene a mano.
                esito["qualificata"] = e_qualificata(esito.get("token") or b"")
                if not esito["qualificata"] and indirizzo in TSA_QUALIFICATE:
                    logger.warning("marca temporale: %s NON ha piu' la dichiarazione ETSI "
                                   "di prestatore qualificato", indirizzo)
                return esito
            tentativi.append({"tsa": indirizzo, "motivo": esito.get("motivo")})
        except Exception as e:
            tentativi.append({"tsa": indirizzo, "motivo": type(e).__name__,
                              "dettaglio": str(e)[:200]})
    return {"ok": False, "motivo": "nessuna_tsa_disponibile", "tentativi": tentativi}


# ═════════════════════════════════════════════════════════════════════════════════
#  Il SIGILLO del giorno
# ═════════════════════════════════════════════════════════════════════════════════

def componi_sigillo(*, giorno: str, accettazioni_sigillo: str, accettazioni_righe: int,
                    giornale_testa: str, giornale_righe: int) -> Dict[str, Any]:
    """Riduce lo stato dei registri a UNA impronta da marcare.

    La stringa e' volutamente LEGGIBILE e stampata nel fascicolo: chiunque, avendo il
    database, puo' ricalcolarla e confrontarla con quella dentro il token della TSA.
    Se coincide, e' provato che a quell'ora QUEL contenuto esisteva gia'."""
    canonico = "|".join([VERSIONE_SIGILLO, str(giorno),
                         "accettazioni=" + str(accettazioni_sigillo),
                         "righe_accettazioni=" + str(int(accettazioni_righe)),
                         "giornale=" + str(giornale_testa),
                         "righe_giornale=" + str(int(giornale_righe))])
    return {"canonico": canonico,
            "impronta": hashlib.sha256(canonico.encode("utf-8")).hexdigest()}


# ═════════════════════════════════════════════════════════════════════════════════
#  Archivio append-only dei token
# ═════════════════════════════════════════════════════════════════════════════════

class ArchivioMarche:
    """Custodia dei token. APPEND-ONLY: si scrive e non si cancella mai (un token
    cancellabile non e' una prova). Una marca per giorno per ambito: idempotente,
    cosi' un riavvio o un doppio giro non moltiplica le richieste alla TSA."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        # ':memory:' crea un database NUOVO a ogni connessione: la tabella sparirebbe
        # subito dopo averla creata. Per quel caso (solo test) si tiene UNA connessione
        # condivisa. Su file resta una connessione per operazione, come tutto il resto.
        self._mem: Optional[sqlite3.Connection] = None
        if str(db_path) == ":memory:":
            self._mem = sqlite3.connect(db_path, timeout=30,
                                        check_same_thread=False)
            self._mem.row_factory = sqlite3.Row
        self.inizializza_schema()

    def _apri(self) -> sqlite3.Connection:
        if self._mem is not None:
            return self._mem
        con = sqlite3.connect(self.db_path, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA busy_timeout=30000")
        except Exception:
            pass
        return con

    def _chiudi(self, con: sqlite3.Connection) -> None:
        if con is not self._mem:      # la connessione condivisa in RAM resta aperta
            con.close()

    def inizializza_schema(self) -> None:
        con = self._apri()
        try:
            with con:
                con.execute("""
                    CREATE TABLE IF NOT EXISTS marche (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        giorno TEXT NOT NULL,
                        ambito TEXT NOT NULL DEFAULT 'registri',
                        impronta TEXT NOT NULL,
                        canonico TEXT NOT NULL DEFAULT '',
                        stato TEXT NOT NULL,
                        tsa TEXT NOT NULL DEFAULT '',
                        policy TEXT NOT NULL DEFAULT '',
                        seriale TEXT NOT NULL DEFAULT '',
                        gen_time INTEGER NOT NULL DEFAULT 0,
                        richiesto_ts INTEGER NOT NULL,
                        token_b64 TEXT NOT NULL DEFAULT '',
                        errore TEXT NOT NULL DEFAULT '')""")
                # QUALIFICATA (eIDAS art. 42): aggiunta il 2026-07-21, migrazione
                # idempotente. Le marche gia' archiviate restano valide e risultano
                # non qualificate, che e' la verita' (erano RFC 3161 e basta).
                try:
                    con.execute("ALTER TABLE marche ADD COLUMN "
                                "qualificata INTEGER NOT NULL DEFAULT 0")
                except sqlite3.OperationalError:
                    pass
                # Una marca riuscita per giorno E PER RANGO: cosi' una qualificata
                # puo' AGGIUNGERSI a un ripiego preso prima (l'archivio e' append-only:
                # non si cancella la prova vecchia, si affianca quella migliore).
                con.execute("DROP INDEX IF EXISTS idx_marca_giorno")
                con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_marca_giorno_rango "
                            "ON marche(giorno, ambito, qualificata) WHERE stato='ok'")
                con.execute("CREATE INDEX IF NOT EXISTS idx_marca_ts "
                            "ON marche(richiesto_ts)")
        finally:
            self._chiudi(con)

    def gia_marcato(self, giorno: str, ambito: str = "registri",
                    solo_qualificata: bool = False) -> bool:
        """C'e' gia' una marca riuscita per quel giorno?
        Con `solo_qualificata` la domanda diventa: c'e' gia' una marca QUALIFICATA?
        Serve al giro giornaliero per non accontentarsi di un ripiego preso quando i
        prestatori europei erano momentaneamente irraggiungibili."""
        con = self._apri()
        try:
            sql = ("SELECT 1 FROM marche WHERE giorno=? AND ambito=? AND stato='ok'")
            if solo_qualificata:
                sql += " AND qualificata=1"
            r = con.execute(sql, (str(giorno), str(ambito))).fetchone()
            return r is not None
        finally:
            self._chiudi(con)

    def scrivi(self, *, giorno: str, ambito: str, impronta: str, canonico: str,
               esito: Dict[str, Any], ora_ts: Optional[int] = None) -> Dict[str, Any]:
        ok = bool(esito.get("ok"))
        token = esito.get("token") or b""
        riga = (str(giorno), str(ambito), str(impronta), str(canonico),
                "ok" if ok else "errore", str(esito.get("tsa") or ""),
                str(esito.get("policy") or ""), str(esito.get("seriale") or ""),
                int(esito.get("gen_time") or 0),
                int(ora_ts if ora_ts is not None else time.time()),
                base64.b64encode(token).decode("ascii") if token else "",
                "" if ok else str(esito.get("motivo") or "errore"),
                1 if (ok and esito.get("qualificata")) else 0)
        con = self._apri()
        try:
            with con:
                cur = con.execute(
                    "INSERT INTO marche (giorno, ambito, impronta, canonico, stato, tsa,"
                    " policy, seriale, gen_time, richiesto_ts, token_b64, errore,"
                    " qualificata) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", riga)
            return {"ok": ok, "id": int(cur.lastrowid)}
        except sqlite3.IntegrityError:
            return {"ok": ok, "id": None, "duplicato": True}
        finally:
            self._chiudi(con)

    def elenco(self, limit: int = 100, solo_ok: bool = False) -> List[Dict[str, Any]]:
        con = self._apri()
        try:
            sql = ("SELECT id, giorno, ambito, impronta, canonico, stato, tsa, policy,"
                   " seriale, gen_time, richiesto_ts, errore, qualificata,"
                   " length(token_b64) AS peso FROM marche")
            if solo_ok:
                sql += " WHERE stato='ok'"
            sql += " ORDER BY id DESC LIMIT ?"
            return [dict(r) for r in con.execute(sql, (max(1, int(limit)),))]
        finally:
            self._chiudi(con)

    def token(self, marca_id: int) -> Optional[bytes]:
        """Il token grezzo (.tsr), da consegnare tale e quale a un perito o a un giudice:
        si verifica con `openssl ts -verify`, senza di noi e senza il nostro software."""
        con = self._apri()
        try:
            r = con.execute("SELECT token_b64 FROM marche WHERE id=?",
                            (int(marca_id),)).fetchone()
            if r is None or not r["token_b64"]:
                return None
            return base64.b64decode(r["token_b64"])
        except Exception:
            return None
        finally:
            self._chiudi(con)

    def verifica(self, marca_id: int) -> Dict[str, Any]:
        """Rilegge il token archiviato e ricontrolla che certifichi PROPRIO la nostra
        impronta. Smaschera una riga a cui qualcuno avesse cambiato l'impronta nel
        database lasciando il token vecchio (o viceversa)."""
        con = self._apri()
        try:
            r = con.execute("SELECT impronta, token_b64, gen_time, qualificata "
                            "FROM marche WHERE id=?", (int(marca_id),)).fetchone()
        finally:
            self._chiudi(con)
        if r is None:
            return {"ok": False, "motivo": "inesistente"}
        if not r["token_b64"]:
            return {"ok": False, "motivo": "senza_token"}
        try:
            token = base64.b64decode(r["token_b64"])
            attesa = bytes.fromhex(r["impronta"])
        except Exception:
            return {"ok": False, "motivo": "archivio_illeggibile"}
        tt = _leggi_tlv(token, 0)
        candidati = ([token] if tt is None else
                     _tutti_octet_string(token, tt[1], tt[2]) + [token])
        for blob in candidati:
            info = _leggi_tstinfo(blob, attesa)
            if info is not None:
                info["ok"] = True
                info["coerente_con_archivio"] = (int(info["gen_time"])
                                                 == int(r["gen_time"]))
                # la qualifica si rilegge DAL TOKEN: se qualcuno alzasse il flag nel
                # database senza avere un token qualificato, qui emergerebbe.
                info["qualificata"] = e_qualificata(token)
                info["qualifica_coerente"] = (int(bool(info["qualificata"]))
                                              == int(r["qualificata"] or 0))
                return info
        return {"ok": False, "motivo": "token_non_certifica_questa_impronta"}

    def conta(self) -> int:
        con = self._apri()
        try:
            return int(con.execute("SELECT count(*) FROM marche").fetchone()[0])
        finally:
            self._chiudi(con)


def crea_archivio_marche(db_path: str) -> Optional[ArchivioMarche]:
    """Fabbrica isolata: se l'archivio non si apre, il resto della macchina prosegue."""
    try:
        return ArchivioMarche(db_path)
    except Exception:
        logger.error("marca temporale: archivio non inizializzato", exc_info=True)
        return None


def attivo() -> bool:
    return str(os.environ.get("MARCA_TEMPORALE", "1")).strip().lower() \
        not in ("0", "false", "no", "off", "")


# ═════════════════════════════════════════════════════════════════════════════════
#  Il giro completo
# ═════════════════════════════════════════════════════════════════════════════════

def marca_i_registri(archivio: ArchivioMarche, *, accettazioni=None, finanza=None,
                     giorno: Optional[str] = None, url: Optional[str] = None,
                     trasporto=None, ora_ts: Optional[int] = None) -> Dict[str, Any]:
    """UN giro: legge lo stato dei registri, ne compone il sigillo, lo fa marcare da un
    terzo e archivia il token. Idempotente sul giorno. NON solleva mai."""
    try:
        import datetime as _dt
        g = giorno or _dt.datetime.utcfromtimestamp(
            ora_ts if ora_ts is not None else time.time()).strftime("%Y-%m-%d")
        # Il giorno e' concluso quando c'e' la prova del rango che vogliamo: se
        # preferiamo le qualificate, un ripiego preso stamattina NON basta a fermare
        # i tentativi — si riprova finche' un prestatore europeo risponde.
        punta_a_qualificata = not str(
            os.environ.get("MARCA_ACCETTA_RIPIEGO", "")).strip().lower() in (
                "1", "true", "yes", "si", "on")
        if archivio.gia_marcato(g, solo_qualificata=punta_a_qualificata):
            return {"ok": True, "saltato": "gia_marcato_oggi", "giorno": g,
                    "qualificata": punta_a_qualificata}
        aveva_ripiego = punta_a_qualificata and archivio.gia_marcato(g)
        acc_sig, acc_righe = "assente", 0
        if accettazioni is not None:
            s = accettazioni.sigillo()
            acc_sig, acc_righe = s.get("sigillo", "assente"), int(s.get("righe") or 0)
        gio_testa, gio_righe = "assente", 0
        if finanza is not None:
            c = finanza.verifica_catena()
            gio_testa = str(c.get("testa") or ("ROTTA:%s" % c.get("seq_rotta")))
            gio_righe = int(c.get("righe") or 0)
        sig = componi_sigillo(giorno=g, accettazioni_sigillo=acc_sig,
                              accettazioni_righe=acc_righe,
                              giornale_testa=gio_testa, giornale_righe=gio_righe)
        esito = chiedi_marca(bytes.fromhex(sig["impronta"]), url=url, trasporto=trasporto)
        if (esito.get("ok") and solo_qualificate() and not esito.get("qualificata")):
            # richiesta esplicita: nessuna marca e' meglio di una di rango inferiore
            esito = {"ok": False, "motivo": "solo_qualificate_ma_nessuna_disponibile"}
        if aveva_ripiego and esito.get("ok") and not esito.get("qualificata"):
            # si stava solo cercando di MIGLIORARE una prova gia' presa: se torna di
            # nuovo un ripiego non si archivia un doppione, si riprovera' dopo.
            return {"ok": True, "saltato": "ripiego_gia_presente", "giorno": g,
                    "qualificata": False}
        scritto = archivio.scrivi(giorno=g, ambito="registri", impronta=sig["impronta"],
                                  canonico=sig["canonico"], esito=esito, ora_ts=ora_ts)
        if esito.get("ok"):
            logger.warning("MARCA TEMPORALE%s ottenuta | giorno=%s | tsa=%s | seriale=%s "
                           "| ora certificata=%s",
                           " QUALIFICATA (eIDAS)" if esito.get("qualificata") else
                           " (NON qualificata: ripiego)", g, esito.get("tsa"),
                           esito.get("seriale"), esito.get("gen_time"))
        else:
            logger.warning("marca temporale non ottenuta (si riprova): %s",
                           esito.get("motivo"))
        return {"ok": bool(esito.get("ok")), "giorno": g, "impronta": sig["impronta"],
                "id": scritto.get("id"), "motivo": esito.get("motivo"),
                "tsa": esito.get("tsa"), "gen_time": esito.get("gen_time"),
                "qualificata": bool(esito.get("qualificata"))}
    except Exception:
        logger.error("marca temporale: giro fallito (ISOLATO)", exc_info=True)
        return {"ok": False, "motivo": "eccezione_isolata"}
