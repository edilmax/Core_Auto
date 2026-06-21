"""
CORE_AUTO - Fase 64: Smart-Pass d'ingresso / self check-in (la chiave digitale).

Per gli ALLOGGI (affitti brevi/hotel) il vero costo operativo e' la reception: qualcuno
deve consegnare le chiavi, fare il check-in, aspettare l'ospite. I colossi non lo
risolvono (non hanno la fisicita'). Noi sì, a costo zero: quando il pagamento e'
confermato, il CORE emette un PASS D'INGRESSO firmato; la serratura smart lo verifica
e apre. Il telefono diventa la chiave. L'host non fa nulla, noi non assumiamo nessuno.

Come funziona (pass firmato, time-boxed, verificabile OFFLINE):
  1. a prenotazione confermata e pagata, il CORE firma HMAC (riusa fase59.FirmaQuote) un
     pass legato a (prenotazione_id, alloggio_id) e VALIDO SOLO nella finestra del
     soggiorno [check-in ore 15:00 .. check-out ore 11:00] (orari configurabili);
  2. la serratura verifica il pass con la chiave condivisa, SENZA chiamare il server
     ad ogni apertura (offline, zero latenza, nessun single-point-of-failure online);
  3. fuori finestra -> negato; porta sbagliata -> negato; firma manomessa -> negato;
  4. REVOCA opzionale (iniettabile e ISOLATA): se la prenotazione e' stata annullata/
     rimborsata, l'accesso e' negato. Su accesso fisico la revoca e' FAIL-CLOSED: se il
     controllo revoca non e' verificabile, si NEGA (un cancellato che entra e' peggio di
     un ospite che chiama il supporto).

VINCITRICE DEL BENCHMARK (4 modelli di chiave digitale):
  V3 'pass firmato HMAC time-boxed, verificabile offline + revoca opzionale'. La
  serratura apre da sola con la chiave condivisa, valido solo nella finestra, legato
  alla prenotazione, infalsificabile. Le altre perdono: V1 'codice/PIN statico
  condiviso' = trapela, niente scadenza, non legato alla prenotazione; V2 'sessione
  verificata al server ad ogni accesso' = richiede serratura online + chiamata per ogni
  apertura (latenza, guasto online lascia l'ospite fuori); V4 'chiave NFT/blockchain' =
  pesante, costa gas, overkill.

DENARO: nessuno (controllo accessi). Tempo in epoch interi (zero ambiguita'). Firma
HMAC stdlib (zero dipendenze). SOPRAVVIVENZA TOTALE: validatore BLINDATO che non solleva
mai; fail-closed su firma/finestra/porta/revoca; orologio iniettabile (test deterministici).
La serratura fisica reale e' gated (hardware), ma emissione+verifica del pass sono pure.
"""
from __future__ import annotations

import datetime
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from fase59_concierge import FirmaQuote

logger = logging.getLogger("core_auto.smartpass")


def _intero(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _epoch_da_data_ora(data_iso: str, ora: int) -> Optional[int]:
    """Epoch (UTC) di una data ISO a una data ora intera. None se invalida."""
    try:
        d = datetime.date.fromisoformat(str(data_iso))
    except (ValueError, TypeError):
        return None
    if not (0 <= ora <= 23):
        return None
    dt = datetime.datetime(d.year, d.month, d.day, ora, 0, 0,
                           tzinfo=datetime.timezone.utc)
    return int(dt.timestamp())


@dataclass(frozen=True)
class EsitoAccesso:
    consentito: bool
    motivo: str = ""           # '' se ok; altrimenti fuori_finestra/alloggio_errato/...


# ─────────────────────────────────────────────────────────────────────────────
# Emissione del pass (lato booking, dopo pagamento confermato)
# ─────────────────────────────────────────────────────────────────────────────
class EmettitorePass:
    """Firma un pass d'ingresso valido nella finestra del soggiorno."""

    def __init__(self, firma: FirmaQuote, *, ora_checkin: int = 15,
                 ora_checkout: int = 11) -> None:
        self._firma = firma
        self._ora_in = ora_checkin if 0 <= ora_checkin <= 23 else 15
        self._ora_out = ora_checkout if 0 <= ora_checkout <= 23 else 11

    def emetti(self, prenotazione_id: str, alloggio_id: str,
               check_in: str, check_out: str) -> Optional[str]:
        """Ritorna il token del pass, o None se le date sono invalide."""
        valido_da = _epoch_da_data_ora(check_in, self._ora_in)
        valido_a = _epoch_da_data_ora(check_out, self._ora_out)
        if valido_da is None or valido_a is None or valido_da >= valido_a:
            return None
        return self._firma.codifica({
            "prenotazione_id": str(prenotazione_id),
            "alloggio_id": str(alloggio_id),
            "check_in": str(check_in), "check_out": str(check_out),
            "valido_da": valido_da, "valido_a": valido_a,
        })


# ─────────────────────────────────────────────────────────────────────────────
# Verifica del pass (lato serratura; offline)
# ─────────────────────────────────────────────────────────────────────────────
class VerificatorePass:
    """Verifica un pass alla porta. `revocato`: callable opzionale
    (prenotazione_id -> bool); se solleva, l'accesso e' NEGATO (fail-closed)."""

    def __init__(self, firma: FirmaQuote, *,
                 orologio: Optional[Callable[[], int]] = None,
                 revocato: Optional[Callable[[str], bool]] = None) -> None:
        self._firma = firma
        self._now = orologio or (lambda: int(time.time()))
        self._revocato = revocato

    def verifica(self, token: Any, alloggio_id_porta: str) -> EsitoAccesso:
        dati = self._firma.decodifica(token)
        if dati is None:
            return EsitoAccesso(False, "pass_non_valido")        # firma rotta/assente
        prenotazione_id = dati.get("prenotazione_id")
        alloggio = dati.get("alloggio_id")
        valido_da = dati.get("valido_da")
        valido_a = dati.get("valido_a")
        if not (isinstance(prenotazione_id, str) and isinstance(alloggio, str)
                and _intero(valido_da) and _intero(valido_a)):
            return EsitoAccesso(False, "pass_corrotto")
        if alloggio != str(alloggio_id_porta):
            return EsitoAccesso(False, "alloggio_errato")        # pass di un'altra porta
        ora = self._now()
        if ora < valido_da:
            return EsitoAccesso(False, "troppo_presto")
        if ora > valido_a:
            return EsitoAccesso(False, "scaduto")
        if self._revocato is not None:
            try:
                if self._revocato(prenotazione_id):
                    return EsitoAccesso(False, "revocato")
            except Exception:
                logger.error("verifica revoca fallita -> NEGATO (fail-closed)",
                             exc_info=True)
                return EsitoAccesso(False, "verifica_revoca_fallita")
        return EsitoAccesso(True, "")


# ─────────────────────────────────────────────────────────────────────────────
# Costruzione del pass per il Wallet del telefono (payload; emissione reale gated)
# ─────────────────────────────────────────────────────────────────────────────
def costruisci_pass_wallet(token: str, *, alloggio_id: str, titolo: str,
                           check_in: str, check_out: str,
                           istruzioni: str = "") -> Dict[str, Any]:
    """Payload strutturato per Apple/Google Wallet o QR. Il token e' il contenuto del
    QR che la serratura legge. (La firma del .pkpass con i certificati Apple e' gated.)"""
    return {
        "formato": "qr",
        "payload": token,                 # cio' che la serratura verifica
        "alloggio_id": alloggio_id,
        "titolo": titolo,
        "check_in": check_in,
        "check_out": check_out,
        "istruzioni": istruzioni or "Avvicina questo codice alla serratura per entrare.",
    }


def crea_emettitore_pass(segreto: bytes, **kw: Any) -> EmettitorePass:
    return EmettitorePass(FirmaQuote(segreto), **kw)


def crea_verificatore_pass(segreto: bytes, **kw: Any) -> VerificatorePass:
    return VerificatorePass(FirmaQuote(segreto), **kw)
