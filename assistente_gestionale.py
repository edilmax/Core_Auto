#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Assistente Gestionale - Progetto TavolaVIP
==========================================

Strumento LOCALE di supporto. Aiuta a:
  1. Organizzare la ricerca di alloggi (criteri, query, confronto candidati).
  2. Preparare BOZZE di email e di testi per i social.

Principio di sicurezza fondamentale (NON negoziabile):
  - Lo strumento NON ha autonomia completa.
  - Ogni azione verso l'esterno (invio email, pubblicazione social, richiesta web)
    richiede l'APPROVAZIONE UMANA ESPLICITA tramite il "gate" di approvazione.
  - Di default le azioni esterne non sono collegate ad alcun servizio reale:
    sono stub che vanno integrati consapevolmente dall'utente con credenziali proprie.

Questo modulo e' volutamente ISOLATO: non importa ne' richiama nessuno degli altri
script presenti nella cartella.
"""

import os
import re
import csv
import sys
import json
import ssl
import time
import queue
import random
import secrets
import sqlite3
import smtplib
import logging
import argparse
import datetime
import threading
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage
from email.mime.text import MIMEText
from dataclasses import dataclass, field, fields, asdict
from typing import Callable, List, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config_assistente.json")

# Carica le variabili d'ambiente da un file .env locale (se presente).
# Le credenziali NON vivono nel codice: stanno nel .env (escluso da git).
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, ".env"))
except ImportError:
    # python-dotenv non installato: si possono comunque usare le env var di sistema.
    pass


# ---------------------------------------------------------------------------
# Configurazione
# ---------------------------------------------------------------------------
def carica_config(percorso: str = CONFIG_PATH) -> dict:
    """Carica la configurazione di sicurezza dal file JSON."""
    if not os.path.exists(percorso):
        raise FileNotFoundError(
            f"Config non trovata: {percorso}. "
            "Crea config_assistente.json prima di avviare."
        )
    with open(percorso, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------
class AuditLog:
    """Registro append-only di tutte le richieste e decisioni umane."""

    def __init__(self, percorso: str):
        self.percorso = percorso
        os.makedirs(os.path.dirname(percorso), exist_ok=True)

    def registra(self, evento: str, dettagli: dict) -> None:
        riga = {
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "evento": evento,
            "dettagli": dettagli,
        }
        with open(self.percorso, "a", encoding="utf-8") as f:
            f.write(json.dumps(riga, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Gate di approvazione umana (cuore della sicurezza)
# ---------------------------------------------------------------------------
class ApprovalGate:
    """
    Intercetta ogni azione verso l'esterno e la blocca finche' un umano
    non la approva esplicitamente. Nessuna azione esterna passa altrove.
    """

    def __init__(self, config: dict, audit: AuditLog,
                 prompt: Callable[[str], str] = input):
        sicurezza = config["sicurezza"]
        self.autonomia_completa = sicurezza.get("autonomia_completa", False)
        self.azioni_consentite = set(sicurezza.get("azioni_esterne_consentite", []))
        self.azioni_vietate = set(sicurezza.get("azioni_sempre_vietate", []))
        self.audit = audit
        self._prompt = prompt  # iniettabile per i test

    def richiedi_approvazione(self, tipo_azione: str, anteprima: str) -> bool:
        """Restituisce True solo se un umano approva esplicitamente."""
        if self.autonomia_completa:
            # Salvaguardia: questo strumento non deve mai girare in piena autonomia.
            raise RuntimeError(
                "autonomia_completa=true non e' supportato per motivi di sicurezza."
            )

        if tipo_azione in self.azioni_vietate:
            self.audit.registra("azione_vietata_bloccata", {"tipo": tipo_azione})
            print(f"\n[BLOCCATO] L'azione '{tipo_azione}' e' sempre vietata.")
            return False

        if tipo_azione not in self.azioni_consentite:
            self.audit.registra("azione_fuori_ambito", {"tipo": tipo_azione})
            print(f"\n[BLOCCATO] '{tipo_azione}' non e' tra le azioni consentite.")
            return False

        print("\n" + "=" * 60)
        print(f"RICHIESTA DI APPROVAZIONE -> {tipo_azione}")
        print("-" * 60)
        print(anteprima)
        print("=" * 60)
        risposta = self._prompt("Approvi questa azione? Scrivi 'APPROVO' per confermare: ").strip()
        approvato = risposta == "APPROVO"

        self.audit.registra(
            "decisione_approvazione",
            {"tipo": tipo_azione, "approvato": approvato, "risposta": risposta},
        )
        print("[APPROVATO]" if approvato else "[ANNULLATO]")
        return approvato


# ---------------------------------------------------------------------------
# Ricerca alloggi
# ---------------------------------------------------------------------------
@dataclass
class CriteriRicerca:
    citta: str = ""
    check_in: str = ""
    check_out: str = ""
    ospiti: int = 2
    budget_max_notte: float = 0.0
    note: str = ""


@dataclass
class Alloggio:
    titolo: str
    prezzo_notte: float
    url: str = ""
    note: str = ""


class RicercaAlloggi:
    """
    Organizza la ricerca alloggi. NON esegue richieste web da sola:
    costruisce query e confronta candidati. Qualsiasi chiamata verso
    l'esterno deve passare dal gate di approvazione.
    """

    def __init__(self, gate: ApprovalGate, audit: AuditLog,
                 percorso_file: Optional[str] = None):
        self.gate = gate
        self.audit = audit
        self.percorso_file = percorso_file  # se None, i candidati restano in memoria
        self.candidati: list[Alloggio] = []
        self._carica()

    def _carica(self) -> None:
        """Ricarica dal disco i candidati salvati nelle sessioni precedenti."""
        if not self.percorso_file or not os.path.exists(self.percorso_file):
            return
        try:
            with open(self.percorso_file, "r", encoding="utf-8") as f:
                dati = json.load(f)
            self.candidati = [Alloggio(**d) for d in dati]
            print(f"[OK] Ripresi {len(self.candidati)} candidati alloggio salvati.")
        except (json.JSONDecodeError, TypeError, OSError) as e:
            print(f"[ATTENZIONE] Candidati salvati illeggibili, si riparte da zero ({e}).")

    def _salva(self) -> None:
        if not self.percorso_file:
            return
        os.makedirs(os.path.dirname(self.percorso_file), exist_ok=True)
        with open(self.percorso_file, "w", encoding="utf-8") as f:
            json.dump([asdict(a) for a in self.candidati], f,
                      ensure_ascii=False, indent=2)

    def costruisci_query(self, criteri: CriteriRicerca) -> str:
        parti = [criteri.citta, criteri.check_in, criteri.check_out,
                 f"{criteri.ospiti} ospiti"]
        if criteri.budget_max_notte:
            parti.append(f"max {criteri.budget_max_notte}/notte")
        query = " | ".join(p for p in parti if p)
        self.audit.registra("query_costruita", {"query": query})
        return query

    def aggiungi_candidato(self, alloggio: Alloggio) -> None:
        """Aggiunge un alloggio (inserito a mano o importato) e salva su disco."""
        self.candidati.append(alloggio)
        self._salva()
        self.audit.registra("candidato_aggiunto", {"titolo": alloggio.titolo,
                                                   "prezzo_notte": alloggio.prezzo_notte})

    def classifica(self, budget_max: float) -> list[Alloggio]:
        """Ordina i candidati per prezzo, evidenziando chi rispetta il budget."""
        return sorted(
            self.candidati,
            key=lambda a: (budget_max and a.prezzo_notte > budget_max, a.prezzo_notte),
        )

    def cerca_online(self, query: str, esecutore: Optional[Callable[[str], str]] = None) -> Optional[str]:
        """
        Ricerca web reale: SOLO previa approvazione umana.
        'esecutore' e' la funzione (fornita dall'utente) che effettua davvero
        la richiesta. Se assente, l'azione resta una bozza.
        """
        if not self.gate.richiedi_approvazione("richiesta_web", f"Query: {query}"):
            return None
        if esecutore is None:
            print("[INFO] Nessun esecutore web collegato: ricerca non eseguita.")
            return None
        risultato = esecutore(query)
        self.audit.registra("azione_eseguita", {"tipo": "richiesta_web",
                                                "query": query})
        return risultato


# ---------------------------------------------------------------------------
# Gestione bozze (email + social)
# ---------------------------------------------------------------------------
@dataclass
class Bozza:
    tipo: str            # "email" | "social"
    destinatario: str    # email o nome piattaforma
    oggetto: str
    corpo: str
    creata_il: str = field(
        default_factory=lambda: datetime.datetime.now().isoformat(timespec="seconds")
    )


class GestoreBozze:
    """Crea e salva LOCALMENTE bozze. L'invio reale passa dal gate."""

    def __init__(self, cartella: str, gate: ApprovalGate, audit: AuditLog):
        self.cartella = cartella
        self.gate = gate
        self.audit = audit
        os.makedirs(cartella, exist_ok=True)

    def crea_email(self, destinatario: str, oggetto: str, corpo: str) -> Bozza:
        bozza = Bozza("email", destinatario, oggetto, corpo)
        self._salva(bozza)
        return bozza

    def crea_social(self, piattaforma: str, testo: str) -> Bozza:
        bozza = Bozza("social", piattaforma, oggetto="(post social)", corpo=testo)
        self._salva(bozza)
        return bozza

    def _salva(self, bozza: Bozza) -> str:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        nome = f"bozza_{bozza.tipo}_{ts}.json"
        percorso = os.path.join(self.cartella, nome)
        with open(percorso, "w", encoding="utf-8") as f:
            json.dump(asdict(bozza), f, ensure_ascii=False, indent=2)
        self.audit.registra("bozza_creata", {"file": nome, "tipo": bozza.tipo})
        print(f"[OK] Bozza salvata: {percorso}")
        return percorso

    def elenca_salvate(self) -> list[tuple[str, Bozza]]:
        """Rilegge dal disco le bozze salvate, dalla piu' recente alla piu' vecchia.
        I file illeggibili vengono saltati con un avviso, senza interrompere."""
        bozze: list[tuple[str, Bozza]] = []
        for nome in sorted(os.listdir(self.cartella), reverse=True):
            if not (nome.startswith("bozza_") and nome.endswith(".json")):
                continue
            percorso = os.path.join(self.cartella, nome)
            try:
                with open(percorso, "r", encoding="utf-8") as f:
                    dati = json.load(f)
                bozze.append((nome, Bozza(**dati)))
            except (json.JSONDecodeError, TypeError, OSError) as e:
                print(f"[ATTENZIONE] Bozza illeggibile, saltata: {nome} ({e})")
        return bozze

    def invia(self, bozza: Bozza,
              esecutore: Optional[Callable[[Bozza], None]] = None) -> bool:
        """
        Invio/pubblicazione reale: SOLO previa approvazione umana.
        Senza 'esecutore' collegato, l'azione resta una simulazione.
        """
        tipo_azione = "invio_email" if bozza.tipo == "email" else "pubblicazione_social"
        anteprima = (f"A: {bozza.destinatario}\n"
                     f"Oggetto: {bozza.oggetto}\n\n{bozza.corpo}")
        if not self.gate.richiedi_approvazione(tipo_azione, anteprima):
            return False
        if esecutore is None:
            print("[INFO] Nessun esecutore collegato: invio simulato, niente inviato.")
            return False
        esecutore(bozza)
        self.audit.registra("azione_eseguita", {"tipo": tipo_azione,
                                                 "destinatario": bozza.destinatario})
        return True


# ---------------------------------------------------------------------------
# Esecutore SMTP Gmail
# ---------------------------------------------------------------------------
@dataclass
class CredenzialiSMTP:
    """Credenziali SMTP. La password NON viene mai loggata ne' stampata."""
    utente: str
    password: str
    host: str = "smtp.gmail.com"
    porta: int = 465

    def __repr__(self) -> str:  # evita di esporre la password in stack/trace
        return f"CredenzialiSMTP(utente={self.utente!r}, host={self.host!r}, password=***)"


def carica_credenziali_smtp(config: dict) -> CredenzialiSMTP:
    """
    Carica le credenziali in modo sicuro, con questa precedenza:
      1. Variabili d'ambiente (consigliato):
           GMAIL_USER          -> indirizzo email mittente
           GMAIL_APP_PASSWORD  -> "password per le app" Google (16 caratteri)
      2. Sezione "smtp" di config_assistente.json (sconsigliato per la password).

    Le credenziali NON sono mai scritte in chiaro nel codice. Se mancano,
    viene sollevato un errore esplicito senza esporre alcun segreto.
    """
    smtp_cfg = config.get("smtp", {}) or {}

    utente = os.environ.get("GMAIL_USER") or smtp_cfg.get("utente", "")
    password = os.environ.get("GMAIL_APP_PASSWORD") or smtp_cfg.get("app_password", "")
    host = os.environ.get("GMAIL_SMTP_HOST") or smtp_cfg.get("host", "smtp.gmail.com")
    porta = int(os.environ.get("GMAIL_SMTP_PORT") or smtp_cfg.get("porta", 465))

    if not utente or not password:
        raise RuntimeError(
            "Credenziali SMTP mancanti. Imposta le variabili d'ambiente "
            "GMAIL_USER e GMAIL_APP_PASSWORD (consigliato), oppure compila la "
            "sezione \"smtp\" in config_assistente.json. "
            "Usa una 'password per le app' Google, non la password dell'account."
        )
    return CredenzialiSMTP(utente=utente.strip(), password=password.strip(),
                           host=host.strip(), porta=porta)


def crea_esecutore_smtp(credenziali: CredenzialiSMTP) -> Callable[["Bozza"], None]:
    """
    Restituisce un esecutore che invia DAVVERO l'email via SMTP su SSL.
    Va passato a GestoreBozze.invia(), che lo chiama SOLO dopo l'approvazione
    umana ('APPROVO') del gate. Questa funzione non contiene alcuna logica di
    approvazione: e' un puro trasporto, invocato solo a valle del gate.
    """
    def _invia(bozza: "Bozza") -> None:
        if bozza.tipo != "email":
            raise ValueError("L'esecutore SMTP gestisce solo bozze di tipo 'email'.")

        msg = EmailMessage()
        msg["From"] = credenziali.utente
        msg["To"] = bozza.destinatario
        msg["Subject"] = bozza.oggetto
        msg.set_content(bozza.corpo)

        contesto = ssl.create_default_context()
        with smtplib.SMTP_SSL(credenziali.host, credenziali.porta,
                              context=contesto, timeout=30) as server:
            server.login(credenziali.utente, credenziali.password)
            server.send_message(msg)
        print(f"[INVIATO] Email recapitata a {bozza.destinatario} via {credenziali.host}.")

    return _invia


# Segnaposto della password Mailtrap nel .env: se ancora presente, la notifica
# non parte (evita login con un valore fittizio).
_SMTP_PASS_SEGNAPOSTO = "tuo_password_mailtrap_qui"


def invia_notifica_email(oggetto: str, corpo: str) -> bool:
    """Invia una email di NOTIFICA di sistema (es. i link magici generati a fine
    ciclo di scraping) tramite la configurazione SMTP del .env. Pensata per
    Mailtrap (STARTTLS su porta 2525) ma valida per qualsiasi server STARTTLS.
    Usa solo la libreria standard (smtplib + email.mime).

    Variabili d'ambiente lette:
      SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM, NOTIFICA_EMAIL.

    NON solleva eccezioni: una notifica non deve mai interrompere il ciclo.
    Restituisce True se l'email parte, False se la config manca o l'invio fallisce.
    A differenza di GestoreBozze.invia(), questo e' un canale di servizio interno
    (verso il proprietario) e non passa dal gate di approvazione umana.
    """
    host = os.environ.get("SMTP_HOST", "").strip()
    porta = os.environ.get("SMTP_PORT", "").strip()
    utente = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASS", "").strip()
    mittente = os.environ.get("SMTP_FROM", "").strip() or utente
    destinatario = os.environ.get("NOTIFICA_EMAIL", "").strip()

    mancanti = [nome for nome, valore in (
        ("SMTP_HOST", host), ("SMTP_PORT", porta), ("SMTP_USER", utente),
        ("SMTP_PASS", password), ("NOTIFICA_EMAIL", destinatario)) if not valore]
    if mancanti:
        print(f"[NOTIFICA] Config SMTP incompleta ({', '.join(mancanti)}): "
              "notifica non inviata.")
        return False
    if password == _SMTP_PASS_SEGNAPOSTO:
        print("[NOTIFICA] SMTP_PASS e' ancora un segnaposto nel .env: "
              "notifica non inviata.")
        return False

    messaggio = MIMEText(corpo, _charset="utf-8")
    messaggio["Subject"] = oggetto
    messaggio["From"] = mittente
    messaggio["To"] = destinatario

    try:
        with smtplib.SMTP(host, int(porta), timeout=30) as server:
            server.ehlo()
            if server.has_extn("starttls"):
                server.starttls()  # crea da sola un contesto SSL sicuro di default
                server.ehlo()
            server.login(utente, password)
            server.send_message(messaggio)
        print(f"[NOTIFICA] Email '{oggetto}' inviata a {destinatario} via {host}.")
        return True
    except (OSError, smtplib.SMTPException) as e:
        print(f"[NOTIFICA] Invio fallito ({e}).")
        return False


# ---------------------------------------------------------------------------
# Input utente
# ---------------------------------------------------------------------------
def chiedi_int(messaggio: str, default: int = 0) -> int:
    """Chiede un intero. Input vuoto -> default; input non numerico -> riprova."""
    while True:
        testo = input(messaggio).strip()
        if not testo:
            return default
        try:
            return int(testo)
        except ValueError:
            print("Valore non valido: inserisci un numero intero.")


def chiedi_float(messaggio: str, default: float = 0.0) -> float:
    """Chiede un numero. Input vuoto -> default; input non numerico -> riprova."""
    while True:
        testo = input(messaggio).strip()
        if not testo:
            return default
        try:
            return float(testo.replace(",", "."))
        except ValueError:
            print("Valore non valido: inserisci un numero (es. 85 o 85.50).")


# ---------------------------------------------------------------------------
# Motore di ricerca globale a campagne
# ---------------------------------------------------------------------------
# Il controllo umano si sposta dal singolo passaggio alla CAMPAGNA: il gate
# approva una volta l'intero piano (mercati, budget, limiti, scadenza) e da
# li' in poi il motore esegue i cicli da solo, dentro i limiti dichiarati.
# Ogni ciclo resta tracciato nell'audit log; le campagne si possono sospendere.

STATO_ATTESA = "in_attesa_approvazione"
STATO_ATTIVA = "attiva"
STATO_SOSPESA = "sospesa"

_PREZZO_RE = re.compile(
    r"(?:€|\$|£|EUR|USD|GBP)\s*(\d{1,5}(?:[.,]\d{1,2})?)"
    r"|(\d{1,5}(?:[.,]\d{1,2})?)\s*(?:€|\$|£|EUR|USD|GBP|euro)",
    re.IGNORECASE,
)


def estrai_prezzo(testo: str) -> float:
    """Estrae il primo prezzo in euro da un testo libero; 0.0 se assente."""
    trovato = _PREZZO_RE.search(testo or "")
    if not trovato:
        return 0.0
    valore = trovato.group(1) or trovato.group(2)
    return float(valore.replace(",", "."))


@dataclass
class MercatoTarget:
    """Un mercato della campagna: citta', localizzazione e criteri di filtro."""
    citta: str
    check_in: str = ""
    check_out: str = ""
    ospiti: int = 2
    budget_max_notte: float = 0.0
    soglia_punteggio: float = 0.4
    parole_escluse: list = field(default_factory=list)
    paese: str = ""          # codice ISO: IT, FR, US...
    lingua: str = "it"       # lingua delle query: it, en, fr, es, de
    fuso_orario: str = ""    # es. Europe/Rome (per lo scheduling locale)
    valuta: str = "EUR"      # EUR, USD, GBP...

    def query(self) -> str:
        parti = [f"alloggio {self.citta}", self.check_in, self.check_out,
                 f"{self.ospiti} ospiti"]
        if self.budget_max_notte:
            parti.append(f"max {self.budget_max_notte:g} {self.valuta} a notte")
        return " ".join(p for p in parti if p)


# Catalogo predefinito dei mercati globali: la query viene localizzata
# automaticamente (lingua) e il filtro prezzo usa la valuta del mercato.
CATALOGO_MERCATI = {
    # EUROPA
    "Milano":    {"paese": "IT", "lingua": "it", "fuso_orario": "Europe/Rome",      "valuta": "EUR"},
    "Roma":      {"paese": "IT", "lingua": "it", "fuso_orario": "Europe/Rome",      "valuta": "EUR"},
    "Parigi":    {"paese": "FR", "lingua": "fr", "fuso_orario": "Europe/Paris",     "valuta": "EUR"},
    "Madrid":    {"paese": "ES", "lingua": "es", "fuso_orario": "Europe/Madrid",    "valuta": "EUR"},
    "Berlino":   {"paese": "DE", "lingua": "de", "fuso_orario": "Europe/Berlin",    "valuta": "EUR"},
    "Amsterdam": {"paese": "NL", "lingua": "en", "fuso_orario": "Europe/Amsterdam", "valuta": "EUR"},
    "Lisbona":   {"paese": "PT", "lingua": "en", "fuso_orario": "Europe/Lisbon",    "valuta": "EUR"},
    # USA
    "New York":    {"paese": "US", "lingua": "en", "fuso_orario": "America/New_York",    "valuta": "USD"},
    "Los Angeles": {"paese": "US", "lingua": "en", "fuso_orario": "America/Los_Angeles", "valuta": "USD"},
    "Miami":       {"paese": "US", "lingua": "en", "fuso_orario": "America/New_York",    "valuta": "USD"},
    "Chicago":     {"paese": "US", "lingua": "en", "fuso_orario": "America/Chicago",     "valuta": "USD"},
    # ASIA
    "Tokyo":     {"paese": "JP", "lingua": "en", "fuso_orario": "Asia/Tokyo",     "valuta": "JPY"},
    "Bangkok":   {"paese": "TH", "lingua": "en", "fuso_orario": "Asia/Bangkok",   "valuta": "THB"},
    "Singapore": {"paese": "SG", "lingua": "en", "fuso_orario": "Asia/Singapore", "valuta": "SGD"},
    # LATAM
    "Buenos Aires":      {"paese": "AR", "lingua": "es", "fuso_orario": "America/Argentina/Buenos_Aires", "valuta": "ARS"},
    "Rio de Janeiro":    {"paese": "BR", "lingua": "en", "fuso_orario": "America/Sao_Paulo",              "valuta": "BRL"},
    "Citta del Messico": {"paese": "MX", "lingua": "es", "fuso_orario": "America/Mexico_City",            "valuta": "MXN"},
}


def mercato_da_catalogo(citta: str, **parametri) -> MercatoTarget:
    """Crea un MercatoTarget dal catalogo globale; i parametri espliciti
    hanno la precedenza. Citta' fuori catalogo: default generici."""
    base = dict(CATALOGO_MERCATI.get(citta, {}))
    base.update(parametri)
    return MercatoTarget(citta=citta, **base)


class QueryExpander:
    """Espande la query base in varianti semantiche nella lingua del mercato.
    La 'traduzione' avviene tramite dizionari statici locali (nessuna chiamata
    esterna); lingua sconosciuta -> fallback inglese."""

    TERMINI = {
        "it": ["affitto breve", "appartamento vacanze", "affitto turistico",
               "casa vacanze", "alloggio economico"],
        "en": ["short term rental", "vacation apartment", "holiday let",
               "serviced apartment", "furnished apartment"],
        "fr": ["location courte duree", "appartement de vacances",
               "location saisonniere", "logement touristique", "appart hotel"],
        "es": ["alquiler corta estancia", "apartamento vacacional",
               "alquiler turistico", "piso turistico", "alojamiento vacacional"],
        "de": ["Kurzzeitmiete", "Ferienwohnung", "Apartment auf Zeit",
               "moeblierte Wohnung", "Unterkunft guenstig"],
    }
    KEYWORD_LOCALI = {
        "US": "Airbnb alternative",
        "IT": "affitto turistico",
        "FR": "meuble de tourisme",
        "ES": "vivienda turistica",
        "DE": "Ferienwohnung privat",
    }

    def espandi(self, mercato: MercatoTarget, max_varianti: int = 5) -> List[str]:
        termini = list(self.TERMINI.get(mercato.lingua, self.TERMINI["en"]))
        locale = self.KEYWORD_LOCALI.get(mercato.paese)
        if locale and locale not in termini:
            termini[-1] = locale  # l'ultima variante diventa la keyword locale
        suffisso = ""
        if mercato.budget_max_notte:
            suffisso = f" max {mercato.budget_max_notte:g} {mercato.valuta}"
        return [f"{termine} {mercato.citta}{suffisso}"
                for termine in termini[:max_varianti]]


@dataclass
class CampagnaRicerca:
    """Piano di ricerca approvato in blocco. Lo stato e' il kill switch."""
    nome: str
    mercati: list  # list[MercatoTarget]
    max_richieste_giorno: int = 30
    pausa_secondi: float = 2.0
    scadenza: str = ""            # "AAAA-MM-GG"; vuota = senza scadenza
    stato: str = STATO_ATTESA
    approvata_il: str = ""
    contatore_giorno: str = ""    # data a cui si riferisce richieste_giorno
    richieste_giorno: int = 0

    @classmethod
    def da_dict(cls, dati: dict) -> "CampagnaRicerca":
        # Ignora le chiavi sconosciute: il JSON puo' provenire da versioni vecchie.
        noti = {f.name for f in fields(cls)}
        dati = {k: v for k, v in dati.items() if k in noti}
        dati["mercati"] = [MercatoTarget(**m) for m in dati.get("mercati", [])]
        return cls(**dati)

    def scaduta(self) -> bool:
        return bool(self.scadenza) and datetime.date.today().isoformat() > self.scadenza

    def anteprima(self) -> str:
        righe = [
            f"Campagna: {self.nome}",
            f"Limiti: max {self.max_richieste_giorno} richieste/giorno, "
            f"pausa {self.pausa_secondi:g}s tra le richieste",
            f"Scadenza: {self.scadenza or 'nessuna'}",
            "Mercati target:",
        ]
        for m in self.mercati:
            righe.append(
                f"  - {m.citta} | {m.check_in or '?'} -> {m.check_out or '?'} | "
                f"{m.ospiti} ospiti | budget {m.budget_max_notte:g}/notte | "
                f"escluse: {', '.join(m.parole_escluse) or '-'}")
        righe.append("Approvando, i cicli futuri verranno eseguiti "
                     "SENZA ulteriori conferme (finche' non sospendi la campagna).")
        return "\n".join(righe)


class ICampagnaProvider(ABC):
    """Contratto di accesso alle campagne per il MotoreRicerca (Regola 1).
    Il motore conosce SOLO questi quattro metodi, mai gli interni del gestore."""

    @abstractmethod
    def get_campagna(self, nome: str) -> Optional["CampagnaRicerca"]:
        ...

    @abstractmethod
    def aggiorna_contatori(self, nome: str, eseguiti: int, trovati: int,
                           timestamp: str) -> None:
        ...

    @abstractmethod
    def get_stato_autorizzazione(self, nome: str) -> bool:
        ...

    @abstractmethod
    def elenca_campagne_attive(self) -> List["CampagnaRicerca"]:
        ...


class GestoreCampagne(ICampagnaProvider):
    """Campagne su SQLite (tabella campagne_stato, stesso file dei candidati):
    unica fonte di verita' (Regola 2). Il vecchio campagne.json e' solo
    bootstrap: migrato una volta, mai piu' riscritto.
    L'approvazione umana resta UNA per campagna, tramite gate."""

    def __init__(self, db_path: str, file_json_bootstrap: str,
                 gate: ApprovalGate, audit: AuditLog):
        self.db_path = db_path
        self.file_json_bootstrap = file_json_bootstrap
        self.gate = gate
        self.audit = audit
        self._init_schema()
        self._migra_json_se_necessario()

    def _connetti(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_schema(self) -> None:
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        con = self._connetti()
        try:
            with con:
                con.execute("""
                    CREATE TABLE IF NOT EXISTS campagne_stato (
                        nome                TEXT PRIMARY KEY,
                        eseguiti_oggi       INTEGER DEFAULT 0,
                        ultimo_eseguito     TEXT,
                        autorizzata         BOOLEAN DEFAULT 0,
                        data_creazione      TEXT,
                        configurazione_json TEXT)""")
        finally:
            con.close()

    def _migra_json_se_necessario(self) -> None:
        """Bootstrap una tantum dal vecchio campagne.json (Regola 2):
        migra solo se la tabella e' vuota; le migrate NON sono autorizzate
        (l'autorizzazione si riottiene dal gate, non si eredita)."""
        if not os.path.exists(self.file_json_bootstrap):
            return
        con = self._connetti()
        try:
            if con.execute("SELECT COUNT(*) FROM campagne_stato").fetchone()[0]:
                return  # migrazione gia' avvenuta
            with open(self.file_json_bootstrap, "r", encoding="utf-8") as f:
                elenco = json.load(f)
            adesso = datetime.datetime.now().isoformat(timespec="seconds")
            with con:
                for dati in elenco:
                    con.execute(
                        "INSERT OR IGNORE INTO campagne_stato VALUES (?,?,?,?,?,?)",
                        (dati["nome"], 0, None, 0, adesso,
                         json.dumps(dati, ensure_ascii=False)))
            self.audit.registra("campagne_migrate_da_json", {"quante": len(elenco)})
        except (json.JSONDecodeError, TypeError, KeyError, OSError) as e:
            print(f"[ATTENZIONE] Bootstrap da campagne.json non riuscito ({e}).")
        finally:
            con.close()

    # ------------------------- ICampagnaProvider -------------------------
    def get_campagna(self, nome: str) -> Optional[CampagnaRicerca]:
        con = self._connetti()
        try:
            riga = con.execute(
                "SELECT configurazione_json, eseguiti_oggi, ultimo_eseguito "
                "FROM campagne_stato WHERE nome = ?", (nome,)).fetchone()
        finally:
            con.close()
        if riga is None:
            return None
        campagna = CampagnaRicerca.da_dict(json.loads(riga[0]))
        oggi = datetime.date.today().isoformat()
        stesso_giorno = bool(riga[2]) and riga[2][:10] == oggi
        campagna.contatore_giorno = oggi
        campagna.richieste_giorno = riga[1] if stesso_giorno else 0
        return campagna

    def aggiorna_contatori(self, nome: str, eseguiti: int, trovati: int,
                           timestamp: str) -> None:
        con = self._connetti()
        try:
            with con:
                riga = con.execute(
                    "SELECT eseguiti_oggi, ultimo_eseguito FROM campagne_stato "
                    "WHERE nome = ?", (nome,)).fetchone()
                if riga is None:
                    return
                stesso_giorno = bool(riga[1]) and riga[1][:10] == timestamp[:10]
                totale = (riga[0] if stesso_giorno else 0) + eseguiti
                con.execute(
                    "UPDATE campagne_stato SET eseguiti_oggi = ?, "
                    "ultimo_eseguito = ? WHERE nome = ?",
                    (totale, timestamp, nome))
        finally:
            con.close()
        self.audit.registra("contatori_aggiornati", {
            "nome": nome, "eseguiti": eseguiti, "trovati": trovati})

    def get_stato_autorizzazione(self, nome: str) -> bool:
        con = self._connetti()
        try:
            riga = con.execute(
                "SELECT autorizzata FROM campagne_stato WHERE nome = ?",
                (nome,)).fetchone()
            return bool(riga and riga[0])
        finally:
            con.close()

    def elenca_campagne_attive(self) -> List[CampagnaRicerca]:
        con = self._connetti()
        try:
            righe = con.execute(
                "SELECT configurazione_json FROM campagne_stato "
                "WHERE autorizzata = 1").fetchall()
        finally:
            con.close()
        return [CampagnaRicerca.da_dict(json.loads(r[0])) for r in righe]

    # ----------------------- gestione (fuori interfaccia) -----------------------
    def crea_campagna(self, campagna: CampagnaRicerca) -> bool:
        """Inserisce la campagna; autorizzata=1 SOLO se il gate approva il piano.
        Se il gate nega, resta registrata ma non autorizzata (approvabile dopo)."""
        if self.get_campagna(campagna.nome) is not None:
            print(f"Esiste gia' una campagna '{campagna.nome}'.")
            return False
        approvata = self.gate.richiedi_approvazione("campagna_ricerca_web",
                                                    campagna.anteprima())
        adesso = datetime.datetime.now().isoformat(timespec="seconds")
        con = self._connetti()
        try:
            with con:
                con.execute(
                    "INSERT INTO campagne_stato VALUES (?,?,?,?,?,?)",
                    (campagna.nome, 0, None, int(approvata), adesso,
                     json.dumps(asdict(campagna), ensure_ascii=False)))
        finally:
            con.close()
        self.audit.registra("campagna_creata",
                            {"nome": campagna.nome, "autorizzata": approvata})
        return approvata

    def approva(self, nome: str) -> bool:
        """Autorizza una campagna esistente, sempre passando dal gate."""
        campagna = self.get_campagna(nome)
        if campagna is None:
            print(f"Campagna '{nome}' inesistente.")
            return False
        if self.get_stato_autorizzazione(nome):
            return True
        if not self.gate.richiedi_approvazione("campagna_ricerca_web",
                                               campagna.anteprima()):
            return False
        self._imposta_autorizzazione(nome, True)
        return True

    def revoca(self, nome: str) -> None:
        """Kill switch: la campagna smette di girare al prossimo ciclo."""
        self._imposta_autorizzazione(nome, False)

    def _imposta_autorizzazione(self, nome: str, autorizzata: bool) -> None:
        con = self._connetti()
        try:
            with con:
                con.execute(
                    "UPDATE campagne_stato SET autorizzata = ? WHERE nome = ?",
                    (int(autorizzata), nome))
        finally:
            con.close()
        self.audit.registra("campagna_autorizzazione",
                            {"nome": nome, "autorizzata": autorizzata})


class DatabaseCandidati:
    """Archivio SQLite dei candidati. L'unicita' per URL la garantisce il
    database (UNIQUE INDEX + ON CONFLICT, Regola 4): nessun dedup in Python."""

    _UPSERT_SQL = """
        INSERT INTO candidati
        (url_candidato, titolo, descrizione, prezzo, localita, fonte,
         punteggio, data_trovato, campagna_origine, paese)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(url_candidato) DO UPDATE SET
            titolo = excluded.titolo,
            descrizione = excluded.descrizione,
            prezzo = excluded.prezzo,
            localita = excluded.localita,
            fonte = excluded.fonte,
            punteggio = excluded.punteggio,
            data_trovato = excluded.data_trovato,
            campagna_origine = excluded.campagna_origine,
            paese = excluded.paese"""

    # FASE 5: colonne aggiunte via ALTER TABLE (idempotente). Tutte con DEFAULT
    # cosi' gli INSERT esistenti (lista colonne esplicita) restano validi e i
    # test che leggono colonne specifiche non vengono toccati.
    _COLONNE_ESTESE = [
        ("tipo_struttura",    "TEXT DEFAULT ''"),
        ("servizi_json",      "TEXT DEFAULT ''"),
        ("capienza_persone",  "INTEGER DEFAULT 0"),
        ("camere",            "INTEGER DEFAULT 0"),
        ("bagni",             "INTEGER DEFAULT 0"),
        ("host_email",        "TEXT DEFAULT ''"),
        ("host_telefono",     "TEXT DEFAULT ''"),
        ("host_nome",         "TEXT DEFAULT ''"),
        ("stato",             "TEXT DEFAULT 'candidato'"),
        ("modalita_ingresso", "TEXT DEFAULT 'scraping'"),
        ("data_scadenza",     "TEXT DEFAULT ''"),
        ("ical_url",          "TEXT DEFAULT ''"),
        ("ical_last_sync",    "TEXT DEFAULT ''"),
        ("link_magico",       "TEXT DEFAULT ''"),
    ]

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_schema()

    def _apri(self) -> sqlite3.Connection:
        """Connessione con foreign_keys attive (Regola 2/6): l'enforcement
        delle FK e' per-connessione, quindi va riattivato a ogni apertura."""
        con = sqlite3.connect(self.db_path)
        con.execute("PRAGMA foreign_keys=ON;")
        return con

    def connessione(self) -> sqlite3.Connection:
        """Connessione pubblica (con foreign_keys attive) per i moduli che
        scrivono direttamente sul DB: ingest VIP, flash host, link magici, iCal.
        Evita l'accesso al membro protetto _apri da fuori dalla classe."""
        return self._apri()

    def _init_schema(self) -> None:
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        con = self._apri()
        try:
            # FASE 1: WAL (persistente sul file) + foreign_keys (per-connessione).
            con.execute("PRAGMA journal_mode=WAL;")
            con.execute("PRAGMA foreign_keys=ON;")
            with con:
                con.execute("""
                    CREATE TABLE IF NOT EXISTS candidati (
                        url_candidato    TEXT,
                        titolo           TEXT NOT NULL,
                        descrizione      TEXT DEFAULT '',
                        prezzo           REAL DEFAULT 0,
                        localita         TEXT NOT NULL,
                        fonte            TEXT DEFAULT '',
                        punteggio        REAL DEFAULT 0,
                        data_trovato     TEXT NOT NULL,
                        campagna_origine TEXT DEFAULT '',
                        paese            TEXT DEFAULT '')""")
                con.execute("CREATE UNIQUE INDEX IF NOT EXISTS "
                            "idx_candidati_url ON candidati(url_candidato)")
                # Migrazione per i database creati prima del multi-mercato.
                colonne = [r[1] for r in
                           con.execute("PRAGMA table_info(candidati)")]
                if "paese" not in colonne:
                    con.execute("ALTER TABLE candidati "
                                "ADD COLUMN paese TEXT DEFAULT ''")
                # FASE 5: ALTER TABLE idempotente per le colonne estese.
                for nome_col, ddl in self._COLONNE_ESTESE:
                    if nome_col not in colonne:
                        con.execute(f"ALTER TABLE candidati "
                                    f"ADD COLUMN {nome_col} {ddl}")
                # FASE 6: tabelle nuove con FK su candidati(url_candidato) +
                # indici su ogni foreign key.
                con.execute("""
                    CREATE TABLE IF NOT EXISTS prenotazioni (
                        id              INTEGER PRIMARY KEY AUTOINCREMENT,
                        candidato_url   TEXT REFERENCES candidati(url_candidato),
                        ospite_nome     TEXT DEFAULT '',
                        ospite_email    TEXT DEFAULT '',
                        check_in        TEXT DEFAULT '',
                        check_out       TEXT DEFAULT '',
                        stato           TEXT DEFAULT 'richiesta',
                        origine         TEXT DEFAULT '',
                        uid_ical        TEXT DEFAULT '',
                        data_creazione  TEXT)""")
                con.execute("""
                    CREATE TABLE IF NOT EXISTS link_magici_log (
                        id              INTEGER PRIMARY KEY AUTOINCREMENT,
                        candidato_url   TEXT REFERENCES candidati(url_candidato),
                        token           TEXT,
                        ruolo           TEXT DEFAULT '',
                        azione          TEXT DEFAULT '',
                        usato           INTEGER DEFAULT 0,
                        data_creazione  TEXT,
                        data_uso        TEXT DEFAULT '')""")
                con.execute("""
                    CREATE TABLE IF NOT EXISTS ical_sync_log (
                        id              INTEGER PRIMARY KEY AUTOINCREMENT,
                        candidato_url   TEXT REFERENCES candidati(url_candidato),
                        ical_url        TEXT DEFAULT '',
                        eventi_letti    INTEGER DEFAULT 0,
                        eventi_importati INTEGER DEFAULT 0,
                        esito           TEXT DEFAULT '',
                        timestamp       TEXT)""")
                con.execute("CREATE INDEX IF NOT EXISTS "
                            "idx_prenotazioni_candidato ON prenotazioni(candidato_url)")
                con.execute("CREATE INDEX IF NOT EXISTS "
                            "idx_link_magici_candidato ON link_magici_log(candidato_url)")
                con.execute("CREATE UNIQUE INDEX IF NOT EXISTS "
                            "idx_link_magici_token ON link_magici_log(token)")
                con.execute("CREATE INDEX IF NOT EXISTS "
                            "idx_ical_sync_candidato ON ical_sync_log(candidato_url)")
                # Indici di performance su candidati: ORDER BY punteggio (top
                # opportunita'/migliori), WHERE stato (pulizia flash), GROUP BY
                # paese/localita (report globale e dashboard).
                con.execute("CREATE INDEX IF NOT EXISTS "
                            "idx_candidati_punteggio ON candidati(punteggio DESC)")
                con.execute("CREATE INDEX IF NOT EXISTS "
                            "idx_candidati_stato ON candidati(stato)")
                con.execute("CREATE INDEX IF NOT EXISTS "
                            "idx_candidati_paese_localita ON candidati(paese, localita)")
                # FASE 3: cache dello scraping HTML su filesystem + indice DB.
                con.execute("""
                    CREATE TABLE IF NOT EXISTS cache_scraping (
                        url             TEXT PRIMARY KEY,
                        percorso_file   TEXT,
                        timestamp       TEXT,
                        dati_json       TEXT DEFAULT '')""")
                # --- Distribuzione a Cascata SQLite (PARTE 1: infrastruttura) ---
                # partner_distribuzione: canali/partner verso cui distribuire.
                con.execute("""
                    CREATE TABLE IF NOT EXISTS partner_distribuzione (
                        id             INTEGER PRIMARY KEY AUTOINCREMENT,
                        nome           TEXT UNIQUE NOT NULL,
                        tipo           TEXT DEFAULT '',
                        endpoint       TEXT DEFAULT '',
                        attivo         INTEGER DEFAULT 1,
                        config_json    TEXT DEFAULT '{}',
                        data_creazione TEXT)""")
                # template_contenuti: modelli di contenuto per canale.
                con.execute("""
                    CREATE TABLE IF NOT EXISTS template_contenuti (
                        id             INTEGER PRIMARY KEY AUTOINCREMENT,
                        nome           TEXT UNIQUE NOT NULL,
                        canale         TEXT DEFAULT '',
                        oggetto        TEXT DEFAULT '',
                        corpo          TEXT DEFAULT '',
                        variabili_json TEXT DEFAULT '{}',
                        data_creazione TEXT)""")
                # coda_distribuzione: la coda di job. FK su partner/template
                # nullable (NULL = esente da check FK), cosi' la coda e'
                # testabile prima di popolare partner/template.
                con.execute("""
                    CREATE TABLE IF NOT EXISTS coda_distribuzione (
                        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                        candidato_url       TEXT DEFAULT '',
                        partner_id          INTEGER
                                            REFERENCES partner_distribuzione(id),
                        template_id         INTEGER
                                            REFERENCES template_contenuti(id),
                        payload_json        TEXT DEFAULT '{}',
                        stato               TEXT DEFAULT 'in_coda',
                        priorita            INTEGER DEFAULT 0,
                        tentativi           INTEGER DEFAULT 0,
                        max_tentativi       INTEGER DEFAULT 3,
                        lock_worker         TEXT DEFAULT '',
                        lock_scadenza       TEXT DEFAULT '',
                        programmato_per     TEXT DEFAULT '',
                        ultimo_errore       TEXT DEFAULT '',
                        data_creazione      TEXT,
                        data_aggiornamento  TEXT)""")
                con.execute("CREATE INDEX IF NOT EXISTS "
                            "idx_coda_stato ON coda_distribuzione(stato)")
                con.execute("CREATE INDEX IF NOT EXISTS "
                            "idx_coda_priorita ON coda_distribuzione(priorita, id)")
                con.execute("CREATE INDEX IF NOT EXISTS "
                            "idx_coda_lock ON coda_distribuzione(lock_scadenza)")
                # log_distribuzione: storico dei tentativi di distribuzione.
                con.execute("""
                    CREATE TABLE IF NOT EXISTS log_distribuzione (
                        id         INTEGER PRIMARY KEY AUTOINCREMENT,
                        coda_id    INTEGER REFERENCES coda_distribuzione(id),
                        partner_id INTEGER REFERENCES partner_distribuzione(id),
                        esito      TEXT DEFAULT '',
                        dettaglio  TEXT DEFAULT '',
                        timestamp  TEXT)""")
                con.execute("CREATE INDEX IF NOT EXISTS "
                            "idx_log_coda ON log_distribuzione(coda_id)")
                # metriche_partner: contatori aggregati per partner.
                con.execute("""
                    CREATE TABLE IF NOT EXISTS metriche_partner (
                        partner_id   INTEGER PRIMARY KEY
                                     REFERENCES partner_distribuzione(id),
                        inviati      INTEGER DEFAULT 0,
                        successi     INTEGER DEFAULT 0,
                        fallimenti   INTEGER DEFAULT 0,
                        ultimo_invio TEXT DEFAULT '')""")
        finally:
            con.close()

    def upsert(self, candidato: dict,
               conn: Optional[sqlite3.Connection] = None) -> None:
        """Inserisce o aggiorna per URL (decide il database, non Python).
        Con 'conn' usa la connessione/transazione del chiamante (Regola 3);
        senza, apre e chiude una connessione propria."""
        parametri = (candidato["url_candidato"], candidato["titolo"],
                     candidato.get("descrizione", ""),
                     candidato.get("prezzo", 0.0), candidato["localita"],
                     candidato.get("fonte", ""), candidato.get("punteggio", 0.0),
                     candidato["data_trovato"],
                     candidato.get("campagna_origine", ""),
                     candidato.get("paese", ""))
        if conn is not None:
            conn.execute(self._UPSERT_SQL, parametri)
            return
        con = self._apri()
        try:
            with con:
                con.execute(self._UPSERT_SQL, parametri)
        finally:
            con.close()

    def migliori(self, limite: int = 15) -> list:
        con = self._apri()
        try:
            return con.execute(
                "SELECT localita, punteggio, prezzo, titolo, url_candidato "
                "FROM candidati ORDER BY punteggio DESC, "
                "CASE WHEN prezzo > 0 THEN prezzo ELSE 999999 END "
                "LIMIT ?", (limite,)).fetchall()
        finally:
            con.close()

    def conta(self) -> int:
        con = self._apri()
        try:
            return con.execute("SELECT COUNT(*) FROM candidati").fetchone()[0]
        finally:
            con.close()

    # ------------------------- reporting globale -------------------------
    def report_globale(self) -> dict:
        """Statistiche aggregate per paese e mercato."""
        con = self._apri()
        try:
            righe = con.execute(
                "SELECT COALESCE(NULLIF(paese, ''), '?'), localita, COUNT(*), "
                "ROUND(AVG(punteggio), 2), "
                "ROUND(AVG(CASE WHEN prezzo > 0 THEN prezzo END), 2) "
                "FROM candidati GROUP BY 1, 2 ORDER BY 1, 2").fetchall()
        finally:
            con.close()
        report = {"totale_candidati": 0, "paesi": {}}
        for paese, localita, quanti, punteggio_medio, prezzo_medio in righe:
            report["totale_candidati"] += quanti
            voce = report["paesi"].setdefault(paese, {"candidati": 0,
                                                      "mercati": {}})
            voce["candidati"] += quanti
            voce["mercati"][localita] = {"candidati": quanti,
                                         "punteggio_medio": punteggio_medio,
                                         "prezzo_medio": prezzo_medio}
        return report

    def top_opportunita(self, quanti: int) -> list:
        """I migliori N candidati mondiali per punteggio (prezzo a parita')."""
        con = self._apri()
        try:
            righe = con.execute(
                "SELECT paese, localita, punteggio, prezzo, titolo, "
                "url_candidato, fonte FROM candidati "
                "ORDER BY punteggio DESC, "
                "CASE WHEN prezzo > 0 THEN prezzo ELSE 999999 END "
                "LIMIT ?", (quanti,)).fetchall()
        finally:
            con.close()
        chiavi = ("paese", "localita", "punteggio", "prezzo", "titolo",
                  "url", "fonte")
        return [dict(zip(chiavi, r)) for r in righe]

    def esporta_csv(self, percorso: str) -> int:
        """Esporta tutti i candidati in CSV leggibile da Excel
        (UTF-8 con BOM, separatore ';'). Restituisce il numero di righe."""
        con = self._apri()
        try:
            righe = con.execute(
                "SELECT url_candidato, titolo, descrizione, prezzo, localita, "
                "paese, fonte, punteggio, data_trovato, campagna_origine "
                "FROM candidati ORDER BY punteggio DESC").fetchall()
        finally:
            con.close()
        with open(percorso, "w", encoding="utf-8-sig", newline="") as f:
            scrittore = csv.writer(f, delimiter=";")
            scrittore.writerow(["url", "titolo", "descrizione", "prezzo",
                                "localita", "paese", "fonte", "punteggio",
                                "data_trovato", "campagna_origine"])
            scrittore.writerows(righe)
        return len(righe)

    # ------------------------- FASE 3: cache scraping -------------------------
    def cache_leggi(self, url: str, validita_secondi: int = 3600) -> Optional[dict]:
        """Restituisce i dati JSON in cache per 'url' se piu' recenti di
        'validita_secondi' (default 1 ora), altrimenti None."""
        con = self._apri()
        try:
            riga = con.execute(
                "SELECT timestamp, dati_json FROM cache_scraping WHERE url = ?",
                (url,)).fetchone()
        finally:
            con.close()
        if riga is None or not riga[0]:
            return None
        try:
            quando = datetime.datetime.fromisoformat(riga[0])
        except ValueError:
            return None
        if (datetime.datetime.now() - quando).total_seconds() > validita_secondi:
            return None
        try:
            return json.loads(riga[1]) if riga[1] else {}
        except json.JSONDecodeError:
            return None

    def cache_scrivi(self, url: str, html: str, dati: dict,
                     cartella: str) -> str:
        """Salva l'HTML fisicamente in 'cartella' e indicizza url->file+dati
        nella tabella cache_scraping. Restituisce il percorso del file."""
        os.makedirs(cartella, exist_ok=True)
        nome = secrets.token_hex(16) + ".html"
        percorso = os.path.join(cartella, nome)
        with open(percorso, "w", encoding="utf-8") as f:
            f.write(html or "")
        adesso = datetime.datetime.now().isoformat(timespec="seconds")
        con = self._apri()
        try:
            with con:
                con.execute(
                    "INSERT INTO cache_scraping (url, percorso_file, timestamp, "
                    "dati_json) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(url) DO UPDATE SET percorso_file = excluded.percorso_file, "
                    "timestamp = excluded.timestamp, dati_json = excluded.dati_json",
                    (url, percorso, adesso,
                     json.dumps(dati, ensure_ascii=False)))
        finally:
            con.close()
        # Pulizia opportunistica delle voci scadute: tiene la cache snella.
        self.cache_pulisci_scaduti()
        return percorso

    def cache_pulisci_scaduti(self, validita_secondi: int = 86400) -> int:
        """Cancella i file HTML e le righe di cache piu' vecchi di
        'validita_secondi' (default 24h). Robusto: gli errori su singolo file
        non interrompono la pulizia. Restituisce il numero di voci rimosse."""
        soglia = datetime.datetime.now() - datetime.timedelta(seconds=validita_secondi)
        rimossi = 0
        con = self._apri()
        try:
            with con:
                righe = con.execute(
                    "SELECT url, percorso_file, timestamp FROM cache_scraping"
                ).fetchall()
                for url, percorso_file, ts in righe:
                    try:
                        scaduto = (not ts or
                                   datetime.datetime.fromisoformat(ts) < soglia)
                    except ValueError:
                        scaduto = True  # timestamp illeggibile: meglio rimuovere
                    if not scaduto:
                        continue
                    if percorso_file and os.path.exists(percorso_file):
                        try:
                            os.remove(percorso_file)
                        except OSError as e:
                            logging.warning("Cache: file %s non rimosso (%s).",
                                            percorso_file, e)
                    con.execute("DELETE FROM cache_scraping WHERE url = ?", (url,))
                    rimossi += 1
        finally:
            con.close()
        return rimossi


class IFonteRicerca(ABC):
    """Contratto comune delle fonti di ricerca. Pure trasporto: il motore le
    usa solo per campagne gia' approvate. 'intervallo_minimo' e' la distanza
    minima in secondi tra due richieste alla stessa fonte (rate limit)."""

    nome = "?"
    intervallo_minimo = 1.0

    @abstractmethod
    def cerca(self, query: str, mercato: Optional[MercatoTarget] = None,
              lingua: str = "") -> List[dict]:
        ...


class FonteBraveSearch(IFonteRicerca):
    """Brave Search API (chiave BRAVE_API_KEY nel .env). Supporta la
    localizzazione: paese e lingua del mercato passati all'API."""

    nome = "brave_search"
    intervallo_minimo = 1.1  # piano Free: 1 richiesta/secondo
    ENDPOINT = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str, timeout: int = 20,
                 risultati_per_query: int = 20):
        self.api_key = api_key
        self.timeout = timeout
        self.risultati_per_query = risultati_per_query

    def cerca(self, query: str, mercato: Optional[MercatoTarget] = None,
              lingua: str = "") -> List[dict]:
        parametri = {"q": query, "count": self.risultati_per_query}
        if mercato is not None and mercato.paese:
            parametri["country"] = mercato.paese.lower()
        if lingua:
            parametri["search_lang"] = lingua
        url = self.ENDPOINT + "?" + urllib.parse.urlencode(parametri)
        richiesta = urllib.request.Request(url, headers={
            "Accept": "application/json",
            "X-Subscription-Token": self.api_key,
        })
        with urllib.request.urlopen(richiesta, timeout=self.timeout) as risposta:
            dati = json.loads(risposta.read().decode("utf-8"))
        return [{"titolo": r.get("title", ""),
                 "url": r.get("url", ""),
                 "descrizione": r.get("description", "")}
                for r in (dati.get("web", {}) or {}).get("results", []) or []]


class FonteDuckDuckGo(IFonteRicerca):
    """API 'Instant Answer' di DuckDuckGo: gratuita, senza chiave.
    Limite onesto: e' pensata per risposte enciclopediche, quindi per query
    commerciali rende spesso pochi o zero risultati. Fonte di rinforzo."""

    nome = "duckduckgo"
    intervallo_minimo = 1.0
    ENDPOINT = "https://api.duckduckgo.com/"

    def __init__(self, timeout: int = 20):
        self.timeout = timeout

    def cerca(self, query: str, mercato: Optional[MercatoTarget] = None,
              lingua: str = "") -> List[dict]:
        url = self.ENDPOINT + "?" + urllib.parse.urlencode(
            {"q": query, "format": "json", "no_html": 1, "no_redirect": 1})
        richiesta = urllib.request.Request(url, headers={
            "User-Agent": "AssistenteGestionale/0.1 (uso personale)"})
        with urllib.request.urlopen(richiesta, timeout=self.timeout) as risposta:
            dati = json.loads(risposta.read().decode("utf-8"))
        risultati = []
        voci = list(dati.get("RelatedTopics", []) or [])
        for voce in voci:
            if isinstance(voce, dict) and "Topics" in voce:  # categorie annidate
                voci.extend(voce.get("Topics", []) or [])
                continue
            if isinstance(voce, dict) and voce.get("FirstURL") and voce.get("Text"):
                risultati.append({"titolo": voce["Text"][:80],
                                  "url": voce["FirstURL"],
                                  "descrizione": voce["Text"]})
        return risultati


class FonteSerpApi(IFonteRicerca):
    """Stub pronto per integrazione futura (https://serpapi.com).
    Inattiva finche' SERPAPI_KEY non e' impostata e il metodo completato."""

    nome = "serpapi"
    intervallo_minimo = 1.0

    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    @property
    def attiva(self) -> bool:
        return bool(self.api_key)

    def cerca(self, query: str, mercato: Optional[MercatoTarget] = None,
              lingua: str = "") -> List[dict]:
        if not self.api_key:
            return []
        raise NotImplementedError(
            "FonteSerpApi: integrazione da completare prima dell'uso.")


# Cartella di destinazione per l'HTML salvato dalla cache di scraping (FASE 3).
CACHE_SCRAPING_DIR = os.path.join(BASE_DIR, "cache_scraping")

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]


class FontePlaywrightStealth(IFonteRicerca):
    """FASE 2 - Fonte di scraping headless con maschera anti-bot.

    Playwright e playwright_stealth sono importati DENTRO cerca() (non a livello
    di modulo): cosi' l'assistente e i 32 test girano anche senza il browser
    installato. Se le librerie mancano o lo scraping fallisce, cerca() logga e
    restituisce [], lasciando che il motore prosegua con Brave/DuckDuckGo (FASE 4).

    sync_playwright() viene avviato per ogni chiamata, cosi' ogni thread del
    ThreadPool del motore ha la sua istanza isolata (thread-safe)."""

    nome = "playwright_stealth"
    intervallo_minimo = 3.0
    ENDPOINT = "https://duckduckgo.com/html/"

    def __init__(self, database: Optional["DatabaseCandidati"] = None,
                 cartella_cache: str = CACHE_SCRAPING_DIR,
                 max_pagine: int = 1, headless: bool = True):
        self.database = database
        self.cartella_cache = cartella_cache
        self.max_pagine = max_pagine
        self.headless = headless

    def cerca(self, query: str, mercato: Optional[MercatoTarget] = None,
              lingua: str = "") -> List[dict]:
        url = self.ENDPOINT + "?" + urllib.parse.urlencode({"q": query})

        # FASE 3: se la cache su DB e' fresca (< 1 ora) si evita lo scraping.
        if self.database is not None:
            in_cache = self.database.cache_leggi(url)
            if in_cache and in_cache.get("risultati"):
                return in_cache["risultati"]

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logging.warning("Playwright non installato: fonte stealth saltata "
                            "(fallback su altre fonti).")
            return []

        # playwright_stealth ha due API a seconda della versione:
        #   - >= 2.0: classe Stealth().apply_stealth_sync(page)
        #   - < 2.0:  funzione stealth_sync(page)
        # Risolviamo un unico callable applica_stealth(page) (o None se assente).
        applica_stealth = None
        try:
            from playwright_stealth import Stealth
            applica_stealth = Stealth().apply_stealth_sync
        except ImportError:
            try:
                from playwright_stealth import stealth_sync as applica_stealth
            except ImportError:
                applica_stealth = None

        try:
            html, risultati = self._scrape(sync_playwright, applica_stealth,
                                           url, mercato)
        except Exception as e:  # qualsiasi errore -> fallback, non blocca il ciclo
            logging.warning("Scraping Playwright fallito (%s): fallback.", e)
            return []

        if self.database is not None:
            try:
                self.database.cache_scrivi(url, html, {"risultati": risultati},
                                           self.cartella_cache)
            except Exception:
                logging.warning("Salvataggio cache scraping non riuscito.")
        return risultati

    def _scrape(self, sync_playwright, applica_stealth, url: str,
                mercato: Optional[MercatoTarget]):
        """Esegue lo scraping vero. Isolato per rendere cerca() leggibile e per
        contenere la logica che dipende dal browser. 'applica_stealth' e' il
        callable di evasione (o None se la libreria non e' disponibile)."""
        timezone = (mercato.fuso_orario if mercato and mercato.fuso_orario
                    else "Europe/Rome")
        viewport = {"width": random.choice([1280, 1366, 1440, 1920]),
                    "height": random.choice([720, 768, 900, 1080])}
        user_agent = random.choice(_USER_AGENTS)
        risultati: List[dict] = []
        html = ""
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"])
            try:
                contesto = browser.new_context(
                    user_agent=user_agent, viewport=viewport,
                    locale=(mercato.lingua if mercato else "it"),
                    timezone_id=timezone)
                page = contesto.new_page()
                if applica_stealth is not None:
                    applica_stealth(page)
                # Maschera esplicita di navigator.webdriver.
                page.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', "
                    "{get: () => undefined});")
                # Route abort per media pesanti: piu' veloce e meno tracciabile.
                page.route(
                    re.compile(r"\.(png|jpg|jpeg|gif|svg|css|woff2?|ttf)$"),
                    lambda route: route.abort())
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                html = page.content()
                risultati = self._estrai(page)
                time.sleep(3)  # pausa tra le pagine (cortesia + anti-bot)
            finally:
                browser.close()
        return html, risultati

    def _estrai(self, page) -> List[dict]:
        """Estrae candidati da JSON-LD e microdata schema.org della pagina."""
        risultati: List[dict] = []
        # JSON-LD
        for blocco in page.query_selector_all('script[type="application/ld+json"]'):
            try:
                dati = json.loads(blocco.inner_text())
            except (json.JSONDecodeError, AttributeError):
                continue
            for voce in (dati if isinstance(dati, list) else [dati]):
                if not isinstance(voce, dict):
                    continue
                url_voce = voce.get("url") or voce.get("@id") or ""
                if not url_voce:
                    continue
                risultati.append({
                    "titolo": str(voce.get("name", ""))[:120],
                    "url": url_voce,
                    "descrizione": str(voce.get("description", ""))})
        # Microdata (itemscope/itemprop)
        for nodo in page.query_selector_all('[itemtype*="schema.org"]'):
            try:
                link = nodo.query_selector('[itemprop="url"] , a')
                href = link.get_attribute("href") if link else None
            except Exception:
                href = None
            if not href:
                continue
            nome_el = nodo.query_selector('[itemprop="name"]')
            risultati.append({
                "titolo": (nome_el.inner_text()[:120] if nome_el else ""),
                "url": href,
                "descrizione": ""})
        return risultati


class MotoreRicerca:
    """
    Esegue il ciclo di una campagna AUTORIZZATA. Parla con le campagne SOLO
    tramite ICampagnaProvider (Regola 1) e scrive i candidati in un'unica
    transazione SQLite: BEGIN IMMEDIATE -> COMMIT, ROLLBACK su qualsiasi
    errore (Regola 3). Nessun prompt: il controllo umano e' avvenuto a monte,
    approvando la campagna. Ogni ciclo finisce nell'audit log.
    """

    def __init__(self, provider: ICampagnaProvider, database: DatabaseCandidati,
                 fonti, audit: AuditLog,
                 sleep: Callable[[float], None] = time.sleep):
        self.provider = provider
        self.database = database
        self.fonti = list(fonti) if isinstance(fonti, (list, tuple)) else [fonti]
        self.audit = audit
        self.expander = QueryExpander()
        self._sleep = sleep      # iniettabile per i test
        self._rate: dict = {}    # nome fonte -> [lock, istante ultima richiesta]

    def _cerca_rate_limited(self, fonte: IFonteRicerca, query: str,
                            mercato: MercatoTarget, pausa_campagna: float) -> List[dict]:
        """Serializza le richieste verso la stessa fonte rispettando il suo
        intervallo minimo (i thread paralleli non aggirano il rate limit)."""
        stato = self._rate.setdefault(fonte.nome, [threading.Lock(), 0.0])
        intervallo = max(getattr(fonte, "intervallo_minimo", 0.0), pausa_campagna)
        with stato[0]:
            attesa = intervallo - (time.monotonic() - stato[1])
            if attesa > 0:
                self._sleep(attesa)
            stato[1] = time.monotonic()
        return fonte.cerca(query, mercato, mercato.lingua)

    def esegui(self, nome: str) -> dict:
        riepilogo = {"campagna": nome, "eseguito": False, "richieste": 0,
                     "archiviati": 0, "scartati": 0, "errori_fonti": 0,
                     "archiviati_per_paese": {}, "motivo": ""}
        if not self.provider.get_stato_autorizzazione(nome):
            riepilogo["motivo"] = "campagna inesistente o non autorizzata"
            self.audit.registra("ciclo_ricerca", riepilogo)
            return riepilogo
        campagna = self.provider.get_campagna(nome)
        if campagna is None:
            riepilogo["motivo"] = "campagna inesistente"
            self.audit.registra("ciclo_ricerca", riepilogo)
            return riepilogo
        if campagna.scaduta():
            riepilogo["motivo"] = "campagna scaduta"
            self.audit.registra("ciclo_ricerca", riepilogo)
            return riepilogo
        disponibili = campagna.max_richieste_giorno - campagna.richieste_giorno
        if disponibili <= 0:
            riepilogo["motivo"] = "limite giornaliero di richieste gia' raggiunto"
            self.audit.registra("ciclo_ricerca", riepilogo)
            return riepilogo

        adesso = datetime.datetime.now().isoformat(timespec="seconds")
        coda: "queue.Queue" = queue.Queue()   # raccolta thread-safe
        lucchetto = threading.Lock()
        contatori = {"richieste": 0, "scartati": 0, "errori": 0}

        def prenota_richiesta() -> bool:
            with lucchetto:
                if contatori["richieste"] >= disponibili:
                    return False
                contatori["richieste"] += 1
                return True

        def processa_mercato(mercato: MercatoTarget) -> None:
            """Un thread per mercato: tutte le varianti su tutte le fonti."""
            for query in self.expander.espandi(mercato):
                for fonte in self.fonti:
                    if not prenota_richiesta():
                        return
                    try:
                        risultati = self._cerca_rate_limited(
                            fonte, query, mercato, campagna.pausa_secondi)
                    except Exception:
                        # FASE 4: una fonte che fallisce (rete, Playwright assente,
                        # parsing) non blocca le altre: si logga e si prosegue.
                        with lucchetto:
                            contatori["errori"] += 1
                        continue
                    for risultato in risultati:
                        candidato = self._valuta(risultato, mercato)
                        if candidato is None:
                            with lucchetto:
                                contatori["scartati"] += 1
                        else:
                            coda.put((candidato, fonte.nome))

        # Ricerche in parallelo: rete fuori dalla transazione, max 5 thread.
        with ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(processa_mercato, campagna.mercati))
        if contatori["richieste"] >= disponibili:
            riepilogo["motivo"] = "limite giornaliero di richieste raggiunto"

        # Aggregazione: stesso URL da piu' fonti -> punteggio combinato
        # (+0.1, tetto 1.0) e fonti concatenate. L'unicita' su disco resta
        # garantita dall'indice UNIQUE.
        aggregati: dict = {}
        while not coda.empty():
            candidato, nome_fonte = coda.get()
            noto = aggregati.get(candidato["url_candidato"])
            if noto is None:
                candidato["fonte"] = nome_fonte
                aggregati[candidato["url_candidato"]] = candidato
            elif nome_fonte not in noto["fonte"]:
                noto["fonte"] += "+" + nome_fonte
                noto["punteggio"] = round(
                    min(1.0, max(noto["punteggio"],
                                 candidato["punteggio"]) + 0.1), 2)

        # Unica transazione finale per TUTTI i candidati (Regola 3).
        conn = sqlite3.connect(self.database.db_path)
        conn.isolation_level = None  # transazione gestita a mano
        conn.execute("PRAGMA foreign_keys=ON;")
        try:
            conn.execute("BEGIN IMMEDIATE")
            for candidato in aggregati.values():
                candidato["data_trovato"] = adesso
                candidato["campagna_origine"] = nome
                self.database.upsert(candidato, conn=conn)
            conn.execute("COMMIT")
            riepilogo["eseguito"] = True
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

        riepilogo["richieste"] = contatori["richieste"]
        riepilogo["scartati"] = contatori["scartati"]
        riepilogo["errori_fonti"] = contatori["errori"]
        riepilogo["archiviati"] = len(aggregati)
        for candidato in aggregati.values():
            paese = candidato.get("paese") or "?"
            riepilogo["archiviati_per_paese"][paese] = \
                riepilogo["archiviati_per_paese"].get(paese, 0) + 1

        # Contatori via provider DOPO il COMMIT: l'interfaccia non accetta una
        # connessione esterna e una seconda connessione in scrittura resterebbe
        # bloccata dal lock EXCLUSIVE. In caso di ROLLBACK non si arriva qui,
        # quindi il ciclo resta atomico: o tutto (candidati + contatori) o niente.
        self.provider.aggiorna_contatori(nome, eseguiti=riepilogo["richieste"],
                                         trovati=riepilogo["archiviati"],
                                         timestamp=adesso)
        self.audit.registra("ciclo_ricerca", riepilogo)
        return riepilogo

    def _valuta(self, risultato: dict, mercato: MercatoTarget) -> Optional[dict]:
        """Filtri automatici invariati (budget, parole escluse, punteggio).
        None = scartato; altrimenti il candidato pronto per l'upsert."""
        if not risultato.get("url"):
            return None
        testo = f"{risultato.get('titolo', '')} {risultato.get('descrizione', '')}"
        minuscolo = testo.lower()
        if any(p.lower() in minuscolo for p in mercato.parole_escluse if p):
            return None
        prezzo = estrai_prezzo(testo)
        if mercato.budget_max_notte and prezzo > mercato.budget_max_notte:
            return None
        punteggio = 0.4
        if prezzo:
            punteggio += 0.3
        if mercato.citta.lower() in minuscolo:
            punteggio += 0.3
        if punteggio < mercato.soglia_punteggio:
            return None
        return {"url_candidato": risultato["url"],
                "titolo": risultato.get("titolo", ""),
                "descrizione": risultato.get("descrizione", ""),
                "prezzo": prezzo,
                "localita": mercato.citta,
                "paese": mercato.paese,
                "punteggio": round(punteggio, 2)}


def stampa_riepilogo_ciclo(riepilogo: dict) -> None:
    if not riepilogo["eseguito"]:
        print(f"[NON ESEGUITO] {riepilogo['motivo']}")
        return
    extra = f" ({riepilogo['motivo']})" if riepilogo["motivo"] else ""
    paesi = riepilogo.get("archiviati_per_paese") or {}
    dettaglio_paesi = (", paesi: " + ", ".join(f"{p}={n}" for p, n in
                                               sorted(paesi.items()))
                       if paesi else "")
    print(f"[CICLO COMPLETATO] richieste: {riepilogo['richieste']}, "
          f"archiviati: {riepilogo['archiviati']}, "
          f"scartati: {riepilogo['scartati']}, "
          f"errori fonti: {riepilogo.get('errori_fonti', 0)}"
          f"{dettaglio_paesi}{extra}")


# ---------------------------------------------------------------------------
# FASE 7: moduli operativi (ingest VIP, flash host, link magici, iCal)
# ---------------------------------------------------------------------------
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_TEL_RE = re.compile(r"(?:\+?\d[\d\s().\-]{7,}\d)")


def _estrai_contatti(testo: str) -> dict:
    """Estrae la prima email e il primo telefono plausibili da un testo libero."""
    email = _EMAIL_RE.search(testo or "")
    tel = _TEL_RE.search(testo or "")
    return {"email": email.group(0) if email else "",
            "telefono": re.sub(r"\s+", " ", tel.group(0)).strip() if tel else ""}


class IngestoreVIP:
    """Inserisce manualmente candidati 'VIP' di alto valore. Geocodifica gli
    indirizzi con geopy/Nominatim (sleep 1.1s tra le chiamate, rispettando le
    policy d'uso), estrae i contatti via regex e forza il punteggio a 2.0 cosi'
    che i VIP emergano sempre in cima alle classifiche. geopy e' importato dentro
    il metodo: l'assistente parte anche senza la libreria installata."""

    PUNTEGGIO_VIP = 2.0

    def __init__(self, database: "DatabaseCandidati", audit: AuditLog,
                 user_agent: str = "TavolaVIP-Ingestore/1.0"):
        self.database = database
        self.audit = audit
        self.user_agent = user_agent

    def _geolocalizza(self, indirizzo: str):
        """Restituisce (lat, lon, indirizzo_normalizzato) oppure (None, None, '').
        Se geopy non c'e' o la chiamata fallisce, degrada senza interrompere."""
        if not indirizzo:
            return (None, None, "")
        try:
            from geopy.geocoders import Nominatim
        except ImportError:
            logging.warning("geopy non installato: geocodifica saltata.")
            return (None, None, "")
        try:
            geocoder = Nominatim(user_agent=self.user_agent)
            time.sleep(1.1)  # rate limit Nominatim: max 1 richiesta/secondo
            posizione = geocoder.geocode(indirizzo)
        except Exception as e:
            logging.warning("Geocodifica fallita per %r (%s).", indirizzo, e)
            return (None, None, "")
        if posizione is None:
            return (None, None, "")
        return (posizione.latitude, posizione.longitude, posizione.address)

    def ingesta(self, annunci: List[dict]) -> dict:
        """'annunci' = lista di dict con chiavi opzionali: titolo, citta,
        indirizzo, testo, url. Inserisce ognuno come candidato VIP."""
        adesso = datetime.datetime.now().isoformat(timespec="seconds")
        inseriti, errori = 0, 0
        con = self.database.connessione()
        try:
            for annuncio in annunci:
                try:
                    testo = annuncio.get("testo", "")
                    contatti = _estrai_contatti(
                        f"{testo} {annuncio.get('email', '')} "
                        f"{annuncio.get('telefono', '')}")
                    lat, lon, indirizzo_norm = self._geolocalizza(
                        annuncio.get("indirizzo", ""))
                    citta = (annuncio.get("citta")
                             or indirizzo_norm.split(",")[0] if indirizzo_norm
                             else annuncio.get("citta", "")) or "VIP"
                    url = (annuncio.get("url")
                           or f"vip://{secrets.token_hex(8)}")
                    servizi = {"lat": lat, "lon": lon,
                               "indirizzo": indirizzo_norm}
                    with con:
                        con.execute(
                            "INSERT INTO candidati "
                            "(url_candidato, titolo, descrizione, prezzo, "
                            "localita, fonte, punteggio, data_trovato, "
                            "campagna_origine, paese, host_email, host_telefono, "
                            "host_nome, modalita_ingresso, servizi_json, stato) "
                            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                            "ON CONFLICT(url_candidato) DO UPDATE SET "
                            "punteggio=excluded.punteggio, "
                            "modalita_ingresso=excluded.modalita_ingresso",
                            (url, annuncio.get("titolo", "Annuncio VIP"),
                             testo, float(annuncio.get("prezzo", 0.0) or 0.0),
                             citta, "ingest_vip", self.PUNTEGGIO_VIP, adesso,
                             "", annuncio.get("paese", ""),
                             contatti["email"], contatti["telefono"],
                             annuncio.get("host_nome", ""), "vip",
                             json.dumps(servizi, ensure_ascii=False),
                             "vip"))
                    inseriti += 1
                except Exception as e:
                    logging.warning("Ingest VIP fallito per un annuncio (%s).", e)
                    errori += 1
        finally:
            con.close()
        riepilogo = {"inseriti": inseriti, "errori": errori}
        self.audit.registra("ingest_vip", riepilogo)
        return riepilogo


class FlashHostManager:
    """Annunci 'flash' a tempo: nascono con scadenza a 7 giorni e vengono
    rimossi quando scadono. Utili per disponibilita' last-minute."""

    DURATA_GIORNI = 7

    def __init__(self, database: "DatabaseCandidati", audit: AuditLog):
        self.database = database
        self.audit = audit

    def crea_flash(self, dati: dict) -> str:
        """Crea un annuncio flash. 'dati' come per IngestoreVIP. Restituisce
        l'url_candidato generato."""
        adesso = datetime.datetime.now()
        scadenza = (adesso + datetime.timedelta(days=self.DURATA_GIORNI)
                    ).date().isoformat()
        url = dati.get("url") or f"flash://{secrets.token_hex(8)}"
        con = self.database.connessione()
        try:
            with con:
                con.execute(
                    "INSERT INTO candidati "
                    "(url_candidato, titolo, descrizione, prezzo, localita, "
                    "fonte, punteggio, data_trovato, paese, stato, "
                    "modalita_ingresso, data_scadenza) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(url_candidato) DO UPDATE SET "
                    "data_scadenza=excluded.data_scadenza, stato='flash'",
                    (url, dati.get("titolo", "Flash host"),
                     dati.get("testo", ""),
                     float(dati.get("prezzo", 0.0) or 0.0),
                     dati.get("citta", "Flash"), "flash_host", 1.0,
                     adesso.isoformat(timespec="seconds"),
                     dati.get("paese", ""), "flash", "flash", scadenza))
        finally:
            con.close()
        self.audit.registra("flash_creato", {"url": url, "scadenza": scadenza})
        return url

    def pulisci_scaduti(self) -> int:
        """Cancella gli annunci flash con data_scadenza passata. Restituisce
        il numero di annunci rimossi."""
        oggi = datetime.date.today().isoformat()
        con = self.database.connessione()
        try:
            with con:
                cur = con.execute(
                    "DELETE FROM candidati WHERE stato = 'flash' "
                    "AND data_scadenza != '' AND data_scadenza < ?", (oggi,))
                rimossi = cur.rowcount
        finally:
            con.close()
        self.audit.registra("flash_puliti", {"rimossi": rimossi})
        return rimossi


class LinkMagiciEngine:
    """Link 'magici' monouso per host e ospiti: un token opaco mappa a un
    candidato e a un ruolo. risolvi_link() li valida, esegui_azione() compie
    l'azione e aggiorna lo stato del candidato in DB."""

    def __init__(self, database: "DatabaseCandidati", audit: AuditLog,
                 base_url: str = "https://tavolavip.local/m/"):
        self.database = database
        self.audit = audit
        self.base_url = base_url

    def _genera(self, candidato_url: str, ruolo: str) -> str:
        token = secrets.token_urlsafe(24)
        adesso = datetime.datetime.now().isoformat(timespec="seconds")
        con = self.database.connessione()
        try:
            with con:
                con.execute(
                    "INSERT INTO link_magici_log "
                    "(candidato_url, token, ruolo, data_creazione) "
                    "VALUES (?,?,?,?)", (candidato_url, token, ruolo, adesso))
        finally:
            con.close()
        self.audit.registra("link_magico_creato",
                            {"candidato": candidato_url, "ruolo": ruolo})
        return self.base_url + token

    def genera_link_host(self, candidato_url: str) -> str:
        return self._genera(candidato_url, "host")

    def genera_link_ospite(self, candidato_url: str) -> str:
        return self._genera(candidato_url, "ospite")

    def risolvi_link(self, token: str) -> Optional[dict]:
        """Estrae il token dalla URL completa o accetta il token nudo;
        restituisce i dati del link (o None se inesistente)."""
        token = token.rsplit("/", 1)[-1]
        con = self.database.connessione()
        try:
            riga = con.execute(
                "SELECT candidato_url, ruolo, azione, usato FROM "
                "link_magici_log WHERE token = ?", (token,)).fetchone()
        finally:
            con.close()
        if riga is None:
            return None
        return {"token": token, "candidato_url": riga[0], "ruolo": riga[1],
                "azione": riga[2], "usato": bool(riga[3])}

    def esegui_azione(self, token: str, azione: str,
                      nuovo_stato: str = "") -> bool:
        """Marca il link come usato, registra l'azione e (se indicato) aggiorna
        lo stato del candidato collegato. Un link gia' usato viene rifiutato."""
        dati = self.risolvi_link(token)
        if dati is None or dati["usato"]:
            return False
        adesso = datetime.datetime.now().isoformat(timespec="seconds")
        con = self.database.connessione()
        try:
            with con:
                con.execute(
                    "UPDATE link_magici_log SET usato = 1, azione = ?, "
                    "data_uso = ? WHERE token = ?",
                    (azione, adesso, dati["token"]))
                if nuovo_stato and dati["candidato_url"]:
                    con.execute(
                        "UPDATE candidati SET stato = ? WHERE url_candidato = ?",
                        (nuovo_stato, dati["candidato_url"]))
        finally:
            con.close()
        self.audit.registra("link_magico_azione",
                            {"token": dati["token"], "azione": azione,
                             "nuovo_stato": nuovo_stato})
        return True


class iCalSyncEngine:
    """Sincronizzazione calendari iCal: importa le prenotazioni da un feed
    esterno (ignorando eventi piu' vecchi di 90 giorni) e genera un feed iCal
    di uscita dalle prenotazioni in DB. 'icalendar' e' importato dentro i metodi
    cosi' l'assistente parte anche senza la libreria."""

    GIORNI_IGNORA = 90

    def __init__(self, database: "DatabaseCandidati", audit: AuditLog):
        self.database = database
        self.audit = audit

    def sync_da_ical(self, candidato_url: str, contenuto_ical: str) -> dict:
        """Importa le prenotazioni dal testo iCal fornito. Eventi piu' vecchi
        di 90 giorni vengono ignorati. Restituisce un riepilogo."""
        try:
            from icalendar import Calendar
        except ImportError:
            logging.warning("icalendar non installato: sync iCal saltato.")
            return {"letti": 0, "importati": 0, "esito": "icalendar assente"}
        limite = datetime.date.today() - datetime.timedelta(days=self.GIORNI_IGNORA)
        adesso = datetime.datetime.now().isoformat(timespec="seconds")
        letti, importati = 0, 0
        try:
            calendario = Calendar.from_ical(contenuto_ical)
        except Exception as e:
            self.audit.registra("ical_sync", {"candidato": candidato_url,
                                              "esito": f"parse fallito: {e}"})
            return {"letti": 0, "importati": 0, "esito": "parse fallito"}
        con = self.database.connessione()
        try:
            with con:
                for componente in calendario.walk("VEVENT"):
                    letti += 1
                    inizio = componente.get("DTSTART")
                    data_inizio = inizio.dt if inizio is not None else None
                    if isinstance(data_inizio, datetime.datetime):
                        data_inizio = data_inizio.date()
                    if isinstance(data_inizio, datetime.date) and data_inizio < limite:
                        continue  # evento troppo vecchio: ignorato
                    fine = componente.get("DTEND")
                    data_fine = fine.dt if fine is not None else None
                    if isinstance(data_fine, datetime.datetime):
                        data_fine = data_fine.date()
                    uid = str(componente.get("UID", "") or "")
                    con.execute(
                        "INSERT INTO prenotazioni (candidato_url, check_in, "
                        "check_out, stato, origine, uid_ical, data_creazione) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (candidato_url,
                         data_inizio.isoformat() if data_inizio else "",
                         data_fine.isoformat() if data_fine else "",
                         "occupato", "ical", uid, adesso))
                    importati += 1
                con.execute(
                    "INSERT INTO ical_sync_log (candidato_url, eventi_letti, "
                    "eventi_importati, esito, timestamp) VALUES (?,?,?,?,?)",
                    (candidato_url, letti, importati, "ok", adesso))
                con.execute(
                    "UPDATE candidati SET ical_last_sync = ? "
                    "WHERE url_candidato = ?", (adesso, candidato_url))
        finally:
            con.close()
        riepilogo = {"letti": letti, "importati": importati, "esito": "ok"}
        self.audit.registra("ical_sync",
                            {"candidato": candidato_url, **riepilogo})
        return riepilogo

    def genera_ical_uscita(self, candidato_url: str) -> str:
        """Genera un feed iCal (stringa) dalle prenotazioni del candidato."""
        try:
            from icalendar import Calendar, Event
        except ImportError:
            logging.warning("icalendar non installato: feed non generato.")
            return ""
        con = self.database.connessione()
        try:
            righe = con.execute(
                "SELECT check_in, check_out, ospite_nome, uid_ical FROM "
                "prenotazioni WHERE candidato_url = ?", (candidato_url,)).fetchall()
        finally:
            con.close()
        calendario = Calendar()
        calendario.add("prodid", "-//TavolaVIP//iCalSyncEngine//IT")
        calendario.add("version", "2.0")
        for check_in, check_out, ospite, uid in righe:
            evento = Event()
            evento.add("summary", f"Prenotazione {ospite}".strip())
            if check_in:
                evento.add("dtstart", datetime.date.fromisoformat(check_in))
            if check_out:
                evento.add("dtend", datetime.date.fromisoformat(check_out))
            evento.add("uid", uid or secrets.token_hex(8))
            calendario.add_component(evento)
        return calendario.to_ical().decode("utf-8")


# ---------------------------------------------------------------------------
# Database verticali "Solo Professionisti" (4 file SQLite indipendenti)
# ---------------------------------------------------------------------------
# Ogni verticale (immobili, mezzi, talento, esperienze) e' un file SQLite a se',
# separato dal DB dei candidati: nessuna interferenza con la tabella 'candidati'.
# Schema identico per tutti; i campi specifici del verticale vivono in
# 'metadati_json'. Stati: da_approvare -> attivo | sospeso | rifiutato.

STATI_RISORSA = ("da_approvare", "attivo", "sospeso", "rifiutato")
RISORSA_VERTICALI = ("immobili", "mezzi", "talento", "esperienze")
# Chiavi di prezzo riconosciute nei metadati, in ordine di priorita'.
_CHIAVI_PREZZO = ("prezzo_giorno", "tariffa_giorno", "prezzo_persona", "prezzo")


def _prezzo_da_metadati(metadati: dict) -> float:
    """Estrae il prezzo da un dict di metadati verticali (le chiavi variano per
    categoria). 0.0 se nessuna chiave nota o valore non numerico."""
    for chiave in _CHIAVI_PREZZO:
        if chiave in metadati:
            try:
                return float(metadati[chiave])
            except (TypeError, ValueError):
                return 0.0
    return 0.0


class GestoreRisorseVerticali:
    """Gestore riutilizzabile di un singolo DB verticale di risorse
    professionali. Ogni operazione di scrittura e' una transazione atomica
    (BEGIN IMMEDIATE -> COMMIT/ROLLBACK) e viene registrata nell'audit.
    Il gate (se fornito) protegge l'approvazione; senza gate, si approva diretto."""

    def __init__(self, db_path: str, audit: AuditLog,
                 gate: Optional[ApprovalGate] = None):
        self.db_path = db_path
        self.audit = audit
        self.gate = gate
        self._init_schema()

    def _init_schema(self) -> None:
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        con = sqlite3.connect(self.db_path)
        try:
            con.execute("PRAGMA journal_mode=WAL;")
            con.execute("PRAGMA foreign_keys=ON;")
            with con:
                con.execute("""
                    CREATE TABLE IF NOT EXISTS risorse (
                        id                INTEGER PRIMARY KEY AUTOINCREMENT,
                        nome              TEXT NOT NULL,
                        contatto_diretto  TEXT NOT NULL,
                        area_geografica   TEXT NOT NULL,
                        stato             TEXT DEFAULT 'da_approvare',
                        data_creazione    TEXT,
                        data_approvazione TEXT,
                        approvato_da      TEXT,
                        note              TEXT,
                        metadati_json     TEXT)""")
                con.execute("CREATE INDEX IF NOT EXISTS "
                            "idx_risorse_stato ON risorse(stato)")
                con.execute("CREATE INDEX IF NOT EXISTS "
                            "idx_risorse_area ON risorse(area_geografica)")
                con.execute("CREATE INDEX IF NOT EXISTS "
                            "idx_risorse_contatto ON risorse(contatto_diretto)")
        finally:
            con.close()

    def _scrivi(self, sql: str, parametri: tuple) -> Optional[int]:
        """Esegue una scrittura in transazione atomica BEGIN IMMEDIATE.
        Restituisce lastrowid (utile per gli INSERT) o None su rowcount 0."""
        con = sqlite3.connect(self.db_path)
        con.isolation_level = None  # transazione gestita a mano
        con.execute("PRAGMA foreign_keys=ON;")
        try:
            con.execute("BEGIN IMMEDIATE")
            cur = con.execute(sql, parametri)
            esito = cur.lastrowid if cur.rowcount else (cur.lastrowid or None)
            con.execute("COMMIT")
            return esito
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()

    def _modifica(self, sql: str, parametri: tuple) -> bool:
        """Come _scrivi ma per UPDATE: True se almeno una riga e' stata toccata."""
        con = sqlite3.connect(self.db_path)
        con.isolation_level = None
        con.execute("PRAGMA foreign_keys=ON;")
        try:
            con.execute("BEGIN IMMEDIATE")
            cur = con.execute(sql, parametri)
            toccate = cur.rowcount
            con.execute("COMMIT")
            return toccate > 0
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()

    def _leggi(self, sql: str, parametri: tuple = ()) -> List[dict]:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            righe = con.execute(sql, parametri).fetchall()
        finally:
            con.close()
        return [dict(r) for r in righe]

    def inserisci(self, nome: str, contatto: str, area: str, metadati) -> int:
        """Inserisce una risorsa in stato 'da_approvare'. 'metadati' puo' essere
        un dict o una stringa JSON: viene SEMPRE validato con json.loads/dumps
        (FASE 5.5/5.6). Se non e' JSON valido, rifiuta l'insert, logga e -1."""
        if isinstance(metadati, str):
            try:
                metadati = json.loads(metadati)
            except (json.JSONDecodeError, TypeError):
                self.audit.registra("risorsa_insert_rifiutato",
                                    {"db": self.db_path, "nome": nome,
                                     "motivo": "metadati JSON non valido"})
                print("[ERRORE] metadati non in JSON valido: insert rifiutato.")
                return -1
        if not isinstance(metadati, dict):
            self.audit.registra("risorsa_insert_rifiutato",
                                {"db": self.db_path, "nome": nome,
                                 "motivo": "metadati non e' un oggetto JSON"})
            return -1
        adesso = datetime.datetime.now().isoformat(timespec="seconds")
        nuovo_id = self._scrivi(
            "INSERT INTO risorse (nome, contatto_diretto, area_geografica, "
            "stato, data_creazione, metadati_json) VALUES (?,?,?,?,?,?)",
            (nome, contatto, area, "da_approvare", adesso,
             json.dumps(metadati, ensure_ascii=False)))
        self.audit.registra("risorsa_inserita",
                            {"db": self.db_path, "id": nuovo_id, "nome": nome})
        return nuovo_id or -1

    def approva(self, id_risorsa: int, approvatore: str,
                usa_gate: bool = True) -> bool:
        """Porta la risorsa allo stato 'attivo'. Se un gate e' disponibile e
        usa_gate=True, richiede l'approvazione umana ('approvazione_risorsa');
        altrimenti approva diretto (FASE 5.7 - automazione/CLI)."""
        risorsa = self.get(id_risorsa)
        if risorsa is None:
            print(f"[INFO] Risorsa {id_risorsa} inesistente.")
            return False
        if self.gate is not None and usa_gate:
            anteprima = (f"Risorsa #{id_risorsa}: {risorsa['nome']} "
                         f"({risorsa['area_geografica']}) - {risorsa['contatto_diretto']}")
            if not self.gate.richiedi_approvazione("approvazione_risorsa", anteprima):
                self.audit.registra("risorsa_approvazione_negata",
                                    {"db": self.db_path, "id": id_risorsa})
                return False
        adesso = datetime.datetime.now().isoformat(timespec="seconds")
        ok = self._modifica(
            "UPDATE risorse SET stato='attivo', data_approvazione=?, "
            "approvato_da=? WHERE id=?", (adesso, approvatore, id_risorsa))
        self.audit.registra("risorsa_approvata",
                            {"db": self.db_path, "id": id_risorsa,
                             "approvato_da": approvatore, "esito": ok})
        return ok

    def sospendi(self, id_risorsa: int, motivo: str) -> bool:
        ok = self._modifica(
            "UPDATE risorse SET stato='sospeso', note=? WHERE id=?",
            (motivo, id_risorsa))
        self.audit.registra("risorsa_sospesa",
                            {"db": self.db_path, "id": id_risorsa, "motivo": motivo})
        return ok

    def rifiuta(self, id_risorsa: int, motivo: str) -> bool:
        ok = self._modifica(
            "UPDATE risorse SET stato='rifiutato', note=? WHERE id=?",
            (motivo, id_risorsa))
        self.audit.registra("risorsa_rifiutata",
                            {"db": self.db_path, "id": id_risorsa, "motivo": motivo})
        return ok

    def elenca_attive(self) -> List[dict]:
        return self._leggi("SELECT * FROM risorse WHERE stato='attivo' ORDER BY id")

    def elenca_da_approvare(self) -> List[dict]:
        return self._leggi(
            "SELECT * FROM risorse WHERE stato='da_approvare' ORDER BY id")

    def cerca_per_area(self, area: str) -> List[dict]:
        return self._leggi(
            "SELECT * FROM risorse WHERE area_geografica LIKE ? ORDER BY id",
            (f"%{area}%",))

    def get(self, id_risorsa: int) -> Optional[dict]:
        righe = self._leggi("SELECT * FROM risorse WHERE id=?", (id_risorsa,))
        return righe[0] if righe else None


# ---------------------------------------------------------------------------
# Motore di composizione "Pacchetto Pronto" (V5)
# ---------------------------------------------------------------------------
# Compone un pacchetto selezionando 1 risorsa ATTIVA per categoria dai 4 DB
# verticali (in SOLA LETTURA, Vincolo 1), traccia le richieste ai partner con
# timer 24h e applica fallback automatico (max 3 tentativi). Lo stato mutabile
# vive in un DB separato 'pacchetti.sqlite3': i DB verticali non si toccano.
#
# Nota su schema reale: la tabella 'risorse' non ha colonne 'area'/'prezzo'
# (sono 'area_geografica' e il prezzo sta in metadati_json), quindi il filtro
# prezzo<=budget/4 e l'ordinamento avvengono lato Python via _prezzo_da_metadati.
#
# Nota su Vincolo 1 (DB verticali read-only): il passo "UPDATE risorse SET
# stato='in_attesa_conferma'" della specifica scriverebbe su un DB verticale;
# per rispettare il vincolo, la conferma e' tracciata in richieste_partner
# (stato='confermata') invece che mutando la risorsa.


class MotoreComposizionePacchetti:
    """Orchestratore del ciclo di vita di un pacchetto: composizione, invio
    richieste partner, scadenze/fallback e conferma. Ogni scrittura su
    pacchetti.sqlite3 e' una transazione atomica (BEGIN IMMEDIATE) e ogni
    operazione e' tracciata nell'audit."""

    CATEGORIE = ("immobili", "mezzi", "talento", "esperienze")
    DURATA_ATTESA_ORE = 24
    MAX_TENTATIVI_FALLBACK = 3

    def __init__(self, audit: AuditLog, db_path: str, gestori: dict):
        """'gestori' = {categoria: GestoreRisorseVerticali} usati in SOLA LETTURA."""
        self.audit = audit
        self.db_path = db_path
        self.gestori = dict(gestori)
        self._init_schema()

    def _init_schema(self) -> None:
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        con = sqlite3.connect(self.db_path)
        try:
            con.execute("PRAGMA journal_mode=WAL;")
            con.execute("PRAGMA foreign_keys=ON;")
            with con:
                con.execute("""
                    CREATE TABLE IF NOT EXISTS pacchetti (
                        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                        codice              TEXT UNIQUE NOT NULL,
                        destinazione        TEXT NOT NULL,
                        budget_max          REAL,
                        data_inizio         TEXT,
                        data_fine           TEXT,
                        stato               TEXT DEFAULT 'in_composizione',
                        risorse_json        TEXT,
                        totale_prezzo       REAL DEFAULT 0,
                        data_creazione      TEXT,
                        data_scadenza       TEXT,
                        tentativi_fallback  INTEGER DEFAULT 0)""")
                con.execute("""
                    CREATE TABLE IF NOT EXISTS richieste_partner (
                        id              INTEGER PRIMARY KEY AUTOINCREMENT,
                        pacchetto_id    INTEGER NOT NULL,
                        risorsa_db      TEXT NOT NULL,
                        risorsa_id      INTEGER NOT NULL,
                        stato           TEXT DEFAULT 'inviata',
                        data_invio      TEXT,
                        data_risposta   TEXT,
                        risposta_partner TEXT,
                        FOREIGN KEY (pacchetto_id) REFERENCES pacchetti(id))""")
                con.execute("CREATE INDEX IF NOT EXISTS "
                            "idx_pacchetti_stato ON pacchetti(stato)")
                con.execute("CREATE INDEX IF NOT EXISTS "
                            "idx_pacchetti_scadenza ON pacchetti(data_scadenza)")
                con.execute("CREATE INDEX IF NOT EXISTS "
                            "idx_richieste_pacchetto ON richieste_partner(pacchetto_id)")
                con.execute("CREATE INDEX IF NOT EXISTS "
                            "idx_richieste_stato ON richieste_partner(stato)")
        finally:
            con.close()

    def _apri(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        con.isolation_level = None  # transazioni gestite a mano (BEGIN IMMEDIATE)
        con.execute("PRAGMA foreign_keys=ON;")
        return con

    @staticmethod
    def _adesso() -> str:
        return datetime.datetime.now().isoformat(timespec="seconds")

    # ----------------------- lettura DB verticali (read-only) -----------------------
    def _risorse_attive_ordinate(self, categoria: str, area: str,
                                 escludi: tuple = ()) -> List[tuple]:
        """Risorse ATTIVE della categoria nell'area, come (riga, prezzo),
        ordinate per prezzo crescente. Sola lettura sul DB verticale."""
        gestore = self.gestori.get(categoria)
        if gestore is None:
            return []
        area_l = (area or "").lower()
        out = []
        for r in gestore.cerca_per_area(area):
            if r.get("stato") != "attivo" or r["id"] in escludi:
                continue
            if area_l not in (r.get("area_geografica") or "").lower():
                continue
            try:
                meta = json.loads(r.get("metadati_json") or "{}")
            except json.JSONDecodeError:
                meta = {}
            out.append((r, _prezzo_da_metadati(meta)))
        out.sort(key=lambda t: t[1])
        return out

    @staticmethod
    def _soddisfa(riga: dict, esigenze_cat: Optional[dict]) -> bool:
        if not esigenze_cat:
            return True
        try:
            meta = json.loads(riga.get("metadati_json") or "{}")
        except json.JSONDecodeError:
            meta = {}
        return all(str(meta.get(k)) == str(v) for k, v in esigenze_cat.items())

    def _trova_alternativa(self, categoria: str, area: str,
                           escludi_id: int) -> Optional[int]:
        attive = self._risorse_attive_ordinate(categoria, area, escludi=(escludi_id,))
        return attive[0][0]["id"] if attive else None

    # ----------------------- letture pacchetti -----------------------
    def get_pacchetto(self, pacchetto_id: int) -> Optional[dict]:
        con = self._apri()
        try:
            riga = con.execute("SELECT * FROM pacchetti WHERE id=?",
                               (pacchetto_id,)).fetchone()
        finally:
            con.close()
        return dict(riga) if riga else None

    def elenca_pacchetti(self, stato: Optional[str] = None) -> List[dict]:
        con = self._apri()
        try:
            if stato:
                righe = con.execute("SELECT * FROM pacchetti WHERE stato=? "
                                    "ORDER BY id", (stato,)).fetchall()
            else:
                righe = con.execute("SELECT * FROM pacchetti ORDER BY id").fetchall()
        finally:
            con.close()
        return [dict(r) for r in righe]

    def get_richieste(self, pacchetto_id: int) -> List[dict]:
        con = self._apri()
        try:
            righe = con.execute("SELECT * FROM richieste_partner WHERE "
                                "pacchetto_id=? ORDER BY id", (pacchetto_id,)).fetchall()
        finally:
            con.close()
        return [dict(r) for r in righe]

    # ----------------------- composizione -----------------------
    def componi(self, destinazione: str, budget_max, data_inizio: str,
                data_fine: str, esigenze_json=None) -> dict:
        """Compone un pacchetto: 1 risorsa attiva (la piu' economica che
        soddisfa le esigenze) per categoria, con prezzo <= budget_max/4."""
        if not destinazione or not destinazione.strip():
            return {"esito": "errore", "motivo": "destinazione vuota"}
        try:
            budget_max = float(budget_max)
        except (TypeError, ValueError):
            return {"esito": "errore", "motivo": "budget non numerico"}
        if budget_max <= 0:
            return {"esito": "errore", "motivo": "budget non valido"}
        for d in (data_inizio, data_fine):
            try:
                datetime.date.fromisoformat(d)
            except (TypeError, ValueError):
                return {"esito": "errore", "motivo": "date non valide (ISO AAAA-MM-GG)"}

        esigenze = {}
        if esigenze_json:
            if isinstance(esigenze_json, dict):
                esigenze = esigenze_json
            else:
                try:
                    esigenze = json.loads(esigenze_json)
                except (json.JSONDecodeError, TypeError):
                    return {"esito": "errore", "motivo": "esigenze JSON non valido"}

        tetto = budget_max / 4
        risorse, mancanti, totale = {}, [], 0.0
        for categoria in self.CATEGORIE:
            scelta = None
            for riga, prezzo in self._risorse_attive_ordinate(categoria, destinazione):
                if prezzo > tetto:
                    continue
                if not self._soddisfa(riga, esigenze.get(categoria)):
                    continue
                scelta = (riga, prezzo)
                break  # gia' ordinate per prezzo crescente: la prima e' la migliore
            if scelta is None:
                mancanti.append(categoria)
            else:
                risorse[categoria] = scelta[0]["id"]
                totale += scelta[1]

        codice = ("PAC-" + datetime.date.today().strftime("%Y%m%d") + "-"
                  + secrets.token_hex(3).upper())
        stato = "in_attesa" if not mancanti else "in_composizione"
        adesso = self._adesso()
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            cur = con.execute(
                "INSERT INTO pacchetti (codice, destinazione, budget_max, "
                "data_inizio, data_fine, stato, risorse_json, totale_prezzo, "
                "data_creazione) VALUES (?,?,?,?,?,?,?,?,?)",
                (codice, destinazione, budget_max, data_inizio, data_fine,
                 stato, json.dumps(risorse), round(totale, 2), adesso))
            pacchetto_id = cur.lastrowid
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()
        esito = {"esito": "ok" if not mancanti else "incompleto",
                 "id": pacchetto_id, "codice": codice, "stato": stato,
                 "risorse": risorse, "mancanti": mancanti,
                 "totale": round(totale, 2)}
        self.audit.registra("pacchetto_creato",
                            {"id": pacchetto_id, "codice": codice,
                             "stato": stato, "mancanti": mancanti,
                             "totale": round(totale, 2)})
        return esito

    # ----------------------- invio richieste -----------------------
    def invia_richieste_partner(self, pacchetto_id: int) -> dict:
        pac = self.get_pacchetto(pacchetto_id)
        if pac is None:
            return {"esito": "inesistente"}
        risorse = json.loads(pac["risorse_json"] or "{}")
        if not risorse:
            return {"esito": "nessuna_risorsa"}
        adesso_dt = datetime.datetime.now()
        adesso = adesso_dt.isoformat(timespec="seconds")
        scadenza = (adesso_dt + datetime.timedelta(hours=self.DURATA_ATTESA_ORE)
                    ).isoformat(timespec="seconds")
        con = self._apri()
        try:
            con.execute("BEGIN IMMEDIATE")
            for categoria, risorsa_id in risorse.items():
                con.execute(
                    "INSERT INTO richieste_partner (pacchetto_id, risorsa_db, "
                    "risorsa_id, stato, data_invio) VALUES (?,?,?,?,?)",
                    (pacchetto_id, categoria, risorsa_id, "inviata", adesso))
                # Placeholder invio reale (email/API): per ora solo simulazione.
            con.execute("UPDATE pacchetti SET stato='in_attesa', data_scadenza=? "
                        "WHERE id=?", (scadenza, pacchetto_id))
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()
        self.audit.registra("richieste_inviate",
                            {"pacchetto_id": pacchetto_id,
                             "inviate": len(risorse), "scadenza": scadenza})
        return {"esito": "ok", "pacchetto_id": pacchetto_id,
                "inviate": len(risorse), "data_scadenza": scadenza}

    # ----------------------- scadenze e fallback -----------------------
    def verifica_scadenze(self) -> list:
        adesso_dt = datetime.datetime.now()
        adesso = adesso_dt.isoformat(timespec="seconds")
        risultati = []
        con = self._apri()
        try:
            scaduti = con.execute(
                "SELECT * FROM pacchetti WHERE stato='in_attesa' "
                "AND data_scadenza IS NOT NULL AND data_scadenza < ?",
                (adesso,)).fetchall()
            for pac in scaduti:
                risorse = json.loads(pac["risorse_json"] or "{}")
                inviate = con.execute(
                    "SELECT * FROM richieste_partner WHERE pacchetto_id=? "
                    "AND stato='inviata'", (pac["id"],)).fetchall()
                fallback_fallito = False
                con.execute("BEGIN IMMEDIATE")
                try:
                    for req in inviate:
                        con.execute("UPDATE richieste_partner SET stato='scaduta', "
                                    "data_risposta=? WHERE id=?", (adesso, req["id"]))
                        alt = self._trova_alternativa(
                            req["risorsa_db"], pac["destinazione"], req["risorsa_id"])
                        if alt is not None:
                            risorse[req["risorsa_db"]] = alt
                        else:
                            fallback_fallito = True
                    nuovo_tent = pac["tentativi_fallback"] + (1 if fallback_fallito else 0)
                    if nuovo_tent >= self.MAX_TENTATIVI_FALLBACK:
                        con.execute("UPDATE pacchetti SET stato='scaduto', "
                                    "tentativi_fallback=? WHERE id=?",
                                    (nuovo_tent, pac["id"]))
                        esito_tipo = "pacchetto_scaduto"
                    else:
                        nuova_scad = (adesso_dt + datetime.timedelta(
                            hours=self.DURATA_ATTESA_ORE)).isoformat(timespec="seconds")
                        con.execute("UPDATE pacchetti SET risorse_json=?, "
                                    "tentativi_fallback=?, data_scadenza=? WHERE id=?",
                                    (json.dumps(risorse), nuovo_tent, nuova_scad,
                                     pac["id"]))
                        for categoria, risorsa_id in risorse.items():
                            con.execute(
                                "INSERT INTO richieste_partner (pacchetto_id, "
                                "risorsa_db, risorsa_id, stato, data_invio) "
                                "VALUES (?,?,?,?,?)",
                                (pac["id"], categoria, risorsa_id, "inviata", adesso))
                        esito_tipo = "fallback_eseguito"
                    con.execute("COMMIT")
                except Exception:
                    con.execute("ROLLBACK")
                    raise
                self.audit.registra(esito_tipo,
                                    {"pacchetto_id": pac["id"], "codice": pac["codice"],
                                     "tentativi": nuovo_tent})
                risultati.append({"pacchetto_id": pac["id"], "codice": pac["codice"],
                                  "esito": esito_tipo, "tentativi": nuovo_tent})
        finally:
            con.close()
        return risultati

    # ----------------------- risposta partner -----------------------
    def registra_risposta_partner(self, richiesta_id: int, esito: str,
                                  nota: str = "") -> bool:
        adesso = self._adesso()
        con = self._apri()
        try:
            req = con.execute("SELECT * FROM richieste_partner WHERE id=?",
                              (richiesta_id,)).fetchone()
            if req is None:
                return False
            pacchetto_id = req["pacchetto_id"]
            con.execute("BEGIN IMMEDIATE")
            try:
                con.execute("UPDATE richieste_partner SET stato=?, data_risposta=?, "
                            "risposta_partner=? WHERE id=?",
                            (esito, adesso, nota, richiesta_id))
                if esito == "rifiutata":
                    # Fallback automatico per la risorsa rifiutata (read-only sui
                    # DB verticali: si cerca un'alternativa, non si muta la risorsa).
                    pac = con.execute("SELECT * FROM pacchetti WHERE id=?",
                                      (pacchetto_id,)).fetchone()
                    risorse = json.loads(pac["risorse_json"] or "{}")
                    alt = self._trova_alternativa(
                        req["risorsa_db"], pac["destinazione"], req["risorsa_id"])
                    if alt is not None:
                        risorse[req["risorsa_db"]] = alt
                        con.execute("UPDATE pacchetti SET risorse_json=? WHERE id=?",
                                    (json.dumps(risorse), pacchetto_id))
                        con.execute(
                            "INSERT INTO richieste_partner (pacchetto_id, risorsa_db, "
                            "risorsa_id, stato, data_invio) VALUES (?,?,?,?,?)",
                            (pacchetto_id, req["risorsa_db"], alt, "inviata", adesso))
                    else:
                        con.execute("UPDATE pacchetti SET tentativi_fallback="
                                    "tentativi_fallback+1 WHERE id=?", (pacchetto_id,))
                # Pacchetto confermato se non restano richieste 'inviata' e ogni
                # categoria del risorse_json ha una richiesta 'confermata'.
                rimaste = con.execute(
                    "SELECT COUNT(*) FROM richieste_partner WHERE pacchetto_id=? "
                    "AND stato='inviata'", (pacchetto_id,)).fetchone()[0]
                pac2 = con.execute("SELECT risorse_json FROM pacchetti WHERE id=?",
                                   (pacchetto_id,)).fetchone()
                risorse2 = json.loads(pac2["risorse_json"] or "{}")
                confermate = {r["risorsa_db"] for r in con.execute(
                    "SELECT DISTINCT risorsa_db FROM richieste_partner WHERE "
                    "pacchetto_id=? AND stato='confermata'", (pacchetto_id,)).fetchall()}
                if rimaste == 0 and risorse2 and set(risorse2).issubset(confermate):
                    con.execute("UPDATE pacchetti SET stato='confermato' WHERE id=?",
                                (pacchetto_id,))
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        finally:
            con.close()
        self.audit.registra("risposta_partner",
                            {"richiesta_id": richiesta_id, "esito": esito,
                             "pacchetto_id": pacchetto_id})
        return True


# ---------------------------------------------------------------------------
# Generatore di proposte commerciali (V6 - intelligenza creativa)
# ---------------------------------------------------------------------------
# Genera un documento Markdown professionale per i pacchetti 'confermato',
# leggendo (in SOLA LETTURA) pacchetti.sqlite3 e i 4 DB verticali. Non crea
# nuovi DB: scrive solo file .md in Proposte_Clienti/AAAA/MM/.


class GeneratorePropostaCommerciale:
    """Crea proposte commerciali su misura per pacchetti confermati.
    Sola lettura su DB; scrive documenti Markdown su filesystem."""

    COMMISSIONE = 0.10
    ETICHETTE = {"immobili": "Immobili", "mezzi": "Mezzi",
                 "talento": "Talento", "esperienze": "Esperienze"}

    def __init__(self, audit: AuditLog, base_dir: str,
                 motore_pacchetti: "MotoreComposizionePacchetti", gestori: dict):
        self.audit = audit
        self.base_dir = base_dir
        self.motore = motore_pacchetti
        self.gestori = dict(gestori)
        # La cartella si crea LAZY (solo alla prima genera()): cosi' la sola
        # istanza dell'orchestratore non scrive nulla su disco (test isolati).
        self.cartella = os.path.join(base_dir, "Proposte_Clienti")

    def _cartella_periodo(self, data_inizio: str) -> str:
        """Sottocartella AAAA/MM ricavata da data_inizio (fallback: oggi)."""
        try:
            data = datetime.date.fromisoformat(data_inizio)
        except (TypeError, ValueError):
            data = datetime.date.today()
        percorso = os.path.join(self.cartella, f"{data.year:04d}",
                                f"{data.month:02d}")
        os.makedirs(percorso, exist_ok=True)
        return percorso

    def genera(self, pacchetto_id: int) -> dict:
        pac = self.motore.get_pacchetto(pacchetto_id)
        if pac is None or pac["stato"] != "confermato":
            raise ValueError("Pacchetto non confermato o inesistente")
        risorse = json.loads(pac["risorse_json"] or "{}")

        voci, totale = [], 0.0
        for categoria in MotoreComposizionePacchetti.CATEGORIE:
            if categoria not in risorse:
                continue
            gestore = self.gestori.get(categoria)
            riga = gestore.get(risorse[categoria]) if gestore else None
            if riga is None:
                voci.append((categoria, "(risorsa non trovata)", "-", 0.0, ""))
                continue
            try:
                meta = json.loads(riga.get("metadati_json") or "{}")
            except json.JSONDecodeError:
                meta = {}
            prezzo = _prezzo_da_metadati(meta)
            totale += prezzo
            servizi = ", ".join(f"{k}: {v}" for k, v in meta.items()
                                if k not in _CHIAVI_PREZZO)
            voci.append((categoria, riga.get("nome", ""),
                         riga.get("area_geografica", ""), prezzo, servizi))

        commissione = round(totale * self.COMMISSIONE, 2)
        totale_cliente = round(totale + commissione, 2)
        adesso = datetime.datetime.now()
        ts_file = adesso.strftime("%Y%m%d_%H%M%S_%f")
        ts_display = adesso.isoformat(timespec="seconds")
        nome_file = f"PROPOSTA_{pac['codice']}_{ts_file}.md"

        contenuto = self._markdown(pac, voci, totale, commissione,
                                   totale_cliente, ts_display)
        cartella = self._cartella_periodo(pac["data_inizio"])
        percorso = os.path.join(cartella, nome_file)
        try:
            with open(percorso, "w", encoding="utf-8") as f:
                f.write(contenuto)
        except OSError as e:
            self.audit.registra("proposta_errore",
                                {"pacchetto_id": pacchetto_id, "errore": str(e)})
            raise
        self.audit.registra("proposta_generata",
                            {"pacchetto_id": pacchetto_id, "codice": pac["codice"],
                             "percorso": percorso, "totale_cliente": totale_cliente})
        return {"percorso": percorso, "totale": round(totale, 2),
                "commissione": commissione, "totale_cliente": totale_cliente}

    def _markdown(self, pac, voci, totale, commissione, totale_cliente,
                  ts_display) -> str:
        righe = [
            "# Proposta Commerciale Tavola Privé",
            f"## Codice: {pac['codice']}",
            f"## Destinazione: {pac['destinazione']}",
            f"## Periodo: {pac['data_inizio']} → {pac['data_fine']}",
            "",
            "### Riepilogo Risorse",
            "",
            "| Categoria | Risorsa | Area | Prezzo |",
            "|-----------|---------|------|--------|",
        ]
        for categoria, nome, area, prezzo, servizi in voci:
            etichetta = self.ETICHETTE.get(categoria, categoria.capitalize())
            righe.append(f"| {etichetta} | {nome} | {area} | €{prezzo:.2f} |")
            if servizi:
                righe.append(f"| | _{servizi}_ | | |")
        righe += [
            "",
            f"### Totale: €{totale:.2f}",
            f"### Commissione Tavola Privé (10%): €{commissione:.2f}",
            f"### Totale Cliente: €{totale_cliente:.2f}",
            "",
            "*Proposta generata automaticamente dal sistema Tavola Privé*",
            f"*Data: {ts_display}*",
            "",
        ]
        return "\n".join(righe)

    def lista_proposte(self, destinazione_filter: Optional[str] = None) -> list:
        """Scansiona Proposte_Clienti/ per i file .md, estrae i metadati dall'
        intestazione e restituisce la lista ordinata per data decrescente."""
        proposte = []
        try:
            for radice, _, files in os.walk(self.cartella):
                for nome in files:
                    if not nome.endswith(".md"):
                        continue
                    percorso = os.path.join(radice, nome)
                    meta = self._estrai_intestazione(percorso)
                    if meta is None:
                        continue
                    if (destinazione_filter and destinazione_filter.lower()
                            not in meta["destinazione"].lower()):
                        continue
                    proposte.append(meta)
        except OSError as e:
            logging.warning("Scansione proposte fallita (%s).", e)
        proposte.sort(key=lambda m: m["data"], reverse=True)
        return proposte

    @staticmethod
    def _estrai_intestazione(percorso: str) -> Optional[dict]:
        try:
            with open(percorso, "r", encoding="utf-8") as f:
                testo = f.read(2000)
        except OSError:
            return None
        def _cerca(etichetta):
            trovato = re.search(rf"{etichetta}:\s*(.+)", testo)
            # rimuove eventuali marcatori Markdown di chiusura (es. '*')
            return trovato.group(1).strip().rstrip("*").strip() if trovato else ""
        return {"codice": _cerca("Codice"),
                "destinazione": _cerca("Destinazione"),
                "data": _cerca(r"\*Data"),
                "percorso": percorso}

    def leggi_proposta(self, percorso_file: str) -> str:
        if not os.path.exists(percorso_file):
            raise FileNotFoundError(f"Proposta non trovata: {percorso_file}")
        with open(percorso_file, "r", encoding="utf-8") as f:
            return f.read()


# ---------------------------------------------------------------------------
# Distribuzione a Cascata SQLite - PARTE 1: coda dei job
# ---------------------------------------------------------------------------
# Gestore della coda 'coda_distribuzione'. Il prelievo di un job (dequeue) usa
# BEGIN IMMEDIATE per garantire che, anche con piu' worker concorrenti, ogni job
# venga assegnato a UN solo worker (lock atomico). Connessione-per-operazione:
# ogni chiamata apre/chiude la propria connessione -> thread-safe.


class DistribuzioneQueueManager:
    """Coda di distribuzione su SQLite. PARTE 1: accodamento e lock atomico.
    Niente worker, niente load balancer (parti successive)."""

    LOCK_TIMEOUT_DEFAULT = 300  # secondi di validita' del lock di un job

    def __init__(self, database: "DatabaseCandidati", audit: Optional[AuditLog] = None):
        self.db = database
        self.audit = audit

    def _con(self) -> sqlite3.Connection:
        """Connessione in modalita' transazione manuale (per BEGIN IMMEDIATE),
        con row_factory=Row e foreign_keys attive."""
        con = sqlite3.connect(self.db.db_path)
        con.row_factory = sqlite3.Row
        con.isolation_level = None
        con.execute("PRAGMA foreign_keys=ON;")
        return con

    def _log(self, evento: str, dettagli: dict) -> None:
        if self.audit is not None:
            self.audit.registra(evento, dettagli)

    def accoda(self, candidato_url: str = "", partner_id: Optional[int] = None,
               template_id: Optional[int] = None, payload: Optional[dict] = None,
               priorita: int = 0, programmato_per: str = "") -> int:
        """Inserisce un job in stato 'in_coda'. Restituisce l'id del job."""
        adesso = datetime.datetime.now().isoformat(timespec="seconds")
        con = self._con()
        try:
            con.execute("BEGIN IMMEDIATE")
            cur = con.execute(
                "INSERT INTO coda_distribuzione (candidato_url, partner_id, "
                "template_id, payload_json, stato, priorita, programmato_per, "
                "data_creazione, data_aggiornamento) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (candidato_url, partner_id, template_id,
                 json.dumps(payload or {}, ensure_ascii=False), "in_coda",
                 priorita, programmato_per, adesso, adesso))
            job_id = cur.lastrowid
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()
        self._log("distribuzione_accodato",
                  {"job_id": job_id, "partner_id": partner_id,
                   "priorita": priorita})
        return job_id

    def preleva(self, worker_id: str,
                lock_timeout: int = LOCK_TIMEOUT_DEFAULT) -> Optional[dict]:
        """Preleva e BLOCCA il prossimo job disponibile in modo atomico
        (BEGIN IMMEDIATE): seleziona il job 'in_coda' a priorita' piu' alta (id
        crescente a parita') la cui finestra di programmazione e' arrivata, lo
        marca 'in_elaborazione' con lock_worker e lock_scadenza. Restituisce il
        job (dict) o None se la coda non ha job disponibili.
        Recupera prima i lock scaduti, cosi' i job orfani tornano disponibili."""
        adesso_dt = datetime.datetime.now()
        adesso = adesso_dt.isoformat(timespec="seconds")
        scadenza = (adesso_dt + datetime.timedelta(
            seconds=lock_timeout)).isoformat(timespec="seconds")
        con = self._con()
        try:
            con.execute("BEGIN IMMEDIATE")
            # Recupero lock scaduti: job 'in_elaborazione' con lock scaduto
            # tornano 'in_coda' (worker morto/lento).
            con.execute(
                "UPDATE coda_distribuzione SET stato='in_coda', lock_worker='', "
                "lock_scadenza='', data_aggiornamento=? "
                "WHERE stato='in_elaborazione' AND lock_scadenza != '' "
                "AND lock_scadenza < ?", (adesso, adesso))
            riga = con.execute(
                "SELECT id FROM coda_distribuzione WHERE stato='in_coda' "
                "AND (programmato_per = '' OR programmato_per <= ?) "
                "ORDER BY priorita DESC, id ASC LIMIT 1", (adesso,)).fetchone()
            if riga is None:
                con.execute("COMMIT")
                return None
            job_id = riga["id"]
            con.execute(
                "UPDATE coda_distribuzione SET stato='in_elaborazione', "
                "lock_worker=?, lock_scadenza=?, tentativi=tentativi+1, "
                "data_aggiornamento=? WHERE id=?",
                (worker_id, scadenza, adesso, job_id))
            job = dict(con.execute(
                "SELECT * FROM coda_distribuzione WHERE id=?", (job_id,)).fetchone())
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()
        self._log("distribuzione_prelevato",
                  {"job_id": job_id, "worker": worker_id})
        return job

    def completa(self, job_id: int) -> bool:
        """Marca un job come 'completato'."""
        return self._aggiorna_stato(job_id, "completato")

    def fallisci(self, job_id: int, motivo: str = "") -> bool:
        """Registra un fallimento: se restano tentativi, il job torna 'in_coda';
        altrimenti diventa 'fallito'."""
        adesso = datetime.datetime.now().isoformat(timespec="seconds")
        con = self._con()
        try:
            con.execute("BEGIN IMMEDIATE")
            riga = con.execute(
                "SELECT tentativi, max_tentativi FROM coda_distribuzione "
                "WHERE id=?", (job_id,)).fetchone()
            if riga is None:
                con.execute("COMMIT")
                return False
            nuovo_stato = ("in_coda" if riga["tentativi"] < riga["max_tentativi"]
                           else "fallito")
            con.execute(
                "UPDATE coda_distribuzione SET stato=?, lock_worker='', "
                "lock_scadenza='', ultimo_errore=?, data_aggiornamento=? "
                "WHERE id=?", (nuovo_stato, motivo, adesso, job_id))
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()
        self._log("distribuzione_fallito",
                  {"job_id": job_id, "stato": nuovo_stato, "motivo": motivo})
        return True

    def _aggiorna_stato(self, job_id: int, stato: str) -> bool:
        adesso = datetime.datetime.now().isoformat(timespec="seconds")
        con = self._con()
        try:
            con.execute("BEGIN IMMEDIATE")
            cur = con.execute(
                "UPDATE coda_distribuzione SET stato=?, lock_worker='', "
                "lock_scadenza='', data_aggiornamento=? WHERE id=?",
                (stato, adesso, job_id))
            con.execute("COMMIT")
            return cur.rowcount > 0
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()

    def get(self, job_id: int) -> Optional[dict]:
        con = self._con()
        try:
            riga = con.execute("SELECT * FROM coda_distribuzione WHERE id=?",
                               (job_id,)).fetchone()
        finally:
            con.close()
        return dict(riga) if riga else None

    def conta_per_stato(self) -> dict:
        con = self._con()
        try:
            righe = con.execute("SELECT stato, COUNT(*) AS n FROM "
                                "coda_distribuzione GROUP BY stato").fetchall()
        finally:
            con.close()
        return {r["stato"]: r["n"] for r in righe}

    def registra_log(self, coda_id: int, partner_id: Optional[int],
                     esito: str, dettaglio: str = "") -> None:
        """Scrive una riga in log_distribuzione (storico dei tentativi)."""
        adesso = datetime.datetime.now().isoformat(timespec="seconds")
        con = self._con()
        try:
            con.execute("BEGIN IMMEDIATE")
            con.execute(
                "INSERT INTO log_distribuzione (coda_id, partner_id, esito, "
                "dettaglio, timestamp) VALUES (?,?,?,?,?)",
                (coda_id, partner_id, esito, dettaglio, adesso))
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()


# ---------------------------------------------------------------------------
# Distribuzione a Cascata SQLite - PARTE 2: bilanciamento e template
# ---------------------------------------------------------------------------


class PartnerLoadBalancer:
    """Seleziona il partner a cui inviare con Weighted Round Robin (variante
    'smooth' deterministica): il peso effettivo combina il peso base del partner
    (config_json['peso']) con il tasso di successo storico. I partner inattivi
    sono esclusi. Connessione-per-operazione su SQLite. Lo stato WRR
    (current_weight) vive in memoria nell'istanza."""

    def __init__(self, database: "DatabaseCandidati", audit: Optional[AuditLog] = None):
        self.db = database
        self.audit = audit
        self._current: dict = {}  # partner_id -> current_weight (stato SWRR)

    def _con(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db.db_path)
        con.row_factory = sqlite3.Row
        con.isolation_level = None
        con.execute("PRAGMA foreign_keys=ON;")
        return con

    def registra_partner(self, nome: str, tipo: str = "", peso: int = 1,
                         attivo: bool = True, endpoint: str = "") -> int:
        """Crea un partner e la sua riga di metriche. Restituisce l'id."""
        adesso = datetime.datetime.now().isoformat(timespec="seconds")
        con = self._con()
        try:
            con.execute("BEGIN IMMEDIATE")
            cur = con.execute(
                "INSERT INTO partner_distribuzione (nome, tipo, endpoint, attivo, "
                "config_json, data_creazione) VALUES (?,?,?,?,?,?)",
                (nome, tipo, endpoint, int(attivo),
                 json.dumps({"peso": peso}), adesso))
            partner_id = cur.lastrowid
            con.execute("INSERT OR IGNORE INTO metriche_partner (partner_id) "
                        "VALUES (?)", (partner_id,))
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()
        return partner_id

    def _partner_attivi(self) -> List[dict]:
        """Partner attivi con peso effettivo = peso_base * (1 + tasso_successo)."""
        con = self._con()
        try:
            righe = con.execute(
                "SELECT p.id, p.nome, p.tipo, p.config_json, "
                "COALESCE(m.inviati,0) AS inviati, COALESCE(m.successi,0) AS successi "
                "FROM partner_distribuzione p "
                "LEFT JOIN metriche_partner m ON m.partner_id = p.id "
                "WHERE p.attivo = 1 ORDER BY p.id").fetchall()
        finally:
            con.close()
        partner = []
        for r in righe:
            try:
                peso_base = float(json.loads(r["config_json"] or "{}").get("peso", 1))
            except (json.JSONDecodeError, TypeError, ValueError):
                peso_base = 1.0
            tasso = (r["successi"] / r["inviati"]) if r["inviati"] else 0.0
            partner.append({"id": r["id"], "nome": r["nome"], "tipo": r["tipo"],
                            "peso_base": peso_base, "tasso_successo": tasso,
                            "peso_eff": peso_base * (1.0 + tasso)})
        return partner

    def seleziona_partner(self) -> Optional[dict]:
        """Restituisce il partner scelto (dict) o None se nessun partner attivo.
        Smooth WRR: la prima selezione e' il partner col peso effettivo maggiore;
        su N=somma_pesi chiamate la distribuzione rispetta i pesi."""
        partner = self._partner_attivi()
        if not partner:
            return None
        presenti = {p["id"] for p in partner}
        for pid in list(self._current):
            if pid not in presenti:
                del self._current[pid]  # partner non piu' attivo: scartato
        totale = sum(p["peso_eff"] for p in partner)
        if totale <= 0:
            return partner[0]  # tutti peso 0: fallback al primo (id minore)
        for p in partner:
            self._current[p["id"]] = self._current.get(p["id"], 0.0) + p["peso_eff"]
        migliore = max(partner, key=lambda p: self._current[p["id"]])
        self._current[migliore["id"]] -= totale
        if self.audit is not None:
            self.audit.registra("partner_selezionato",
                                {"partner_id": migliore["id"],
                                 "nome": migliore["nome"]})
        return migliore

    def aggiorna_metriche(self, partner_id: int, successo: bool) -> None:
        """Aggiorna i contatori del partner dopo un invio (successo/fallimento)."""
        adesso = datetime.datetime.now().isoformat(timespec="seconds")
        con = self._con()
        try:
            con.execute("BEGIN IMMEDIATE")
            con.execute("INSERT OR IGNORE INTO metriche_partner (partner_id) "
                        "VALUES (?)", (partner_id,))
            con.execute(
                "UPDATE metriche_partner SET inviati = inviati + 1, "
                "successi = successi + ?, fallimenti = fallimenti + ?, "
                "ultimo_invio = ? WHERE partner_id = ?",
                (1 if successo else 0, 0 if successo else 1, adesso, partner_id))
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()
        if self.audit is not None:
            self.audit.registra("metriche_aggiornate",
                                {"partner_id": partner_id, "successo": successo})

    def tasso_successo(self, partner_id: int) -> float:
        con = self._con()
        try:
            riga = con.execute("SELECT inviati, successi FROM metriche_partner "
                               "WHERE partner_id = ?", (partner_id,)).fetchone()
        finally:
            con.close()
        if not riga or not riga["inviati"]:
            return 0.0
        return riga["successi"] / riga["inviati"]


class TemplateEngine:
    """Legge i template da 'template_contenuti' e sostituisce le variabili nella
    sintassi {{nome_variabile}}. Le variabili sconosciute restano invariate
    (nessun crash). Connessione-per-operazione su SQLite."""

    _VAR_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")

    def __init__(self, database: "DatabaseCandidati"):
        self.db = database

    def _con(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db.db_path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON;")
        return con

    def registra_template(self, nome: str, canale: str = "", oggetto: str = "",
                          corpo: str = "", variabili: Optional[dict] = None) -> int:
        adesso = datetime.datetime.now().isoformat(timespec="seconds")
        con = self._con()
        try:
            with con:
                cur = con.execute(
                    "INSERT INTO template_contenuti (nome, canale, oggetto, corpo, "
                    "variabili_json, data_creazione) VALUES (?,?,?,?,?,?)",
                    (nome, canale, oggetto, corpo,
                     json.dumps(variabili or {}, ensure_ascii=False), adesso))
                return cur.lastrowid
        finally:
            con.close()

    def get_template(self, nome: str) -> Optional[dict]:
        con = self._con()
        try:
            riga = con.execute("SELECT * FROM template_contenuti WHERE nome = ?",
                               (nome,)).fetchone()
        finally:
            con.close()
        return dict(riga) if riga else None

    @classmethod
    def render_testo(cls, testo: str, variabili: dict) -> str:
        """Sostituisce {{var}} con variabili[var]; lascia intatte le variabili
        non fornite."""
        def _sost(match):
            chiave = match.group(1)
            return (str(variabili[chiave]) if chiave in variabili
                    else match.group(0))
        return cls._VAR_RE.sub(_sost, testo or "")

    def render(self, nome: str, variabili: Optional[dict] = None) -> dict:
        """Carica il template 'nome' e restituisce oggetto/corpo renderizzati.
        Solleva KeyError se il template non esiste."""
        template = self.get_template(nome)
        if template is None:
            raise KeyError(f"Template inesistente: {nome}")
        variabili = variabili or {}
        return {"oggetto": self.render_testo(template["oggetto"], variabili),
                "corpo": self.render_testo(template["corpo"], variabili)}

    def render_id(self, template_id: int,
                  variabili: Optional[dict] = None) -> Optional[dict]:
        """Come render() ma per id; None se il template non esiste."""
        con = self._con()
        try:
            riga = con.execute("SELECT oggetto, corpo FROM template_contenuti "
                               "WHERE id = ?", (template_id,)).fetchone()
        finally:
            con.close()
        if riga is None:
            return None
        variabili = variabili or {}
        return {"oggetto": self.render_testo(riga["oggetto"], variabili),
                "corpo": self.render_testo(riga["corpo"], variabili)}


# ---------------------------------------------------------------------------
# Distribuzione a Cascata SQLite - PARTE 3: worker
# ---------------------------------------------------------------------------


class DistribuzioneWorker:
    """Worker della coda di distribuzione. Preleva un job, sceglie il partner
    (via load balancer se non specificato), formatta il testo (template engine),
    simula l'invio e chiude il job (completa/fallisci) aggiornando le metriche.

    Esecuzione: 'elabora_uno()' processa un singolo job in modo SINCRONO (per i
    test); 'esegui_ciclo()' svuota la coda; 'start_async()' avvia un thread che
    cicla finche' non viene fermato con 'stop()'."""

    def __init__(self, coda: "DistribuzioneQueueManager",
                 load_balancer: "PartnerLoadBalancer",
                 template_engine: "TemplateEngine",
                 audit: Optional[AuditLog] = None,
                 worker_id: Optional[str] = None,
                 esecutore: Optional[Callable] = None):
        self.coda = coda
        self.load_balancer = load_balancer
        self.template_engine = template_engine
        self.audit = audit
        self.worker_id = worker_id or f"worker-{secrets.token_hex(4)}"
        # Esecutore d'invio: callable(job, partner_id, contenuto) -> bool.
        # Default: invio SIMULATO con successo (nessuna azione esterna reale).
        self.esecutore = esecutore or (lambda job, partner_id, contenuto: True)
        self._running = False
        self._thread = None

    def _invia(self, job, partner_id, contenuto):
        try:
            ok = self.esecutore(job, partner_id, contenuto)
            return bool(ok), ("inviato" if ok else "invio rifiutato dal partner")
        except Exception as e:
            return False, f"eccezione invio: {e}"

    def elabora_uno(self) -> Optional[dict]:
        """Processa al piu' un job. Restituisce un riepilogo dict o None se la
        coda non ha job disponibili."""
        job = self.coda.preleva(self.worker_id)
        if job is None:
            return None
        job_id = job["id"]
        try:
            partner_id = job["partner_id"]
            if not partner_id:
                partner = self.load_balancer.seleziona_partner()
                if partner is None:
                    self.coda.fallisci(job_id, "nessun partner disponibile")
                    self.coda.registra_log(job_id, None, "errore",
                                           "nessun partner disponibile")
                    return {"job_id": job_id, "esito": "fallito",
                            "motivo": "nessun partner disponibile"}
                partner_id = partner["id"]
            payload = json.loads(job["payload_json"] or "{}")
            contenuto = None
            if job["template_id"]:
                contenuto = self.template_engine.render_id(job["template_id"], payload)
            successo, dettaglio = self._invia(job, partner_id, contenuto)
            self.load_balancer.aggiorna_metriche(partner_id, successo)
            if successo:
                self.coda.completa(job_id)
                self.coda.registra_log(job_id, partner_id, "successo", dettaglio)
                esito = "completato"
            else:
                self.coda.fallisci(job_id, dettaglio)
                self.coda.registra_log(job_id, partner_id, "errore", dettaglio)
                esito = "fallito"
            if self.audit is not None:
                self.audit.registra("distribuzione_elaborato",
                                    {"job_id": job_id, "partner_id": partner_id,
                                     "esito": esito})
            return {"job_id": job_id, "partner_id": partner_id, "esito": esito}
        except Exception as e:
            self.coda.fallisci(job_id, f"errore worker: {e}")
            return {"job_id": job_id, "esito": "fallito", "motivo": str(e)}

    def esegui_ciclo(self, max_job: Optional[int] = None) -> int:
        """Svuota la coda (o al massimo 'max_job' job). Restituisce quanti job
        sono stati processati."""
        processati = 0
        while max_job is None or processati < max_job:
            if self.elabora_uno() is None:
                break
            processati += 1
        return processati

    def start_async(self, intervallo_secondi: float = 1.0):
        """Avvia un thread che cicla sulla coda finche' non viene fermato."""
        self._running = True

        def loop():
            while self._running:
                try:
                    if self.elabora_uno() is None:
                        time.sleep(intervallo_secondi)  # coda vuota: attende
                except Exception:
                    time.sleep(intervallo_secondi)

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Orchestratore
# ---------------------------------------------------------------------------
class AssistenteGestionale:
    def __init__(self, config: Optional[dict] = None):
        self.config = config or carica_config()
        percorsi = self.config["percorsi"]
        cartella_bozze = os.path.join(BASE_DIR, percorsi["cartella_bozze"])
        file_audit = os.path.join(BASE_DIR, percorsi["file_log_audit"])
        file_candidati = os.path.join(BASE_DIR, percorsi.get(
            "file_candidati",
            os.path.join(percorsi["cartella_bozze"], "candidati_alloggi.json")))
        file_campagne = os.path.join(BASE_DIR, percorsi.get(
            "file_campagne",
            os.path.join(percorsi["cartella_bozze"], "campagne.json")))
        db_candidati = os.path.join(BASE_DIR, percorsi.get(
            "db_candidati",
            os.path.join(percorsi["cartella_bozze"], "candidati.sqlite3")))

        # Cablaggio nell'ordine prescritto: audit, gate, db, campagne
        # (stesso file SQLite del db), fonte, motore.
        self.audit = AuditLog(file_audit)
        self.gate = ApprovalGate(self.config, self.audit)
        self.db = DatabaseCandidati(db_candidati)
        self.campagne = GestoreCampagne(db_candidati, file_campagne,
                                        self.gate, self.audit)
        api_key = os.environ.get("BRAVE_API_KEY", "").strip()
        if not api_key:
            print("[ATTENZIONE] BRAVE_API_KEY assente nel .env: i cicli di "
                  "ricerca falliranno finche' non la imposti.")
        serpapi_key = os.environ.get("SERPAPI_KEY", "").strip()
        # FASE 4: ordine delle fonti con fallback. Playwright (stealth) prima;
        # se assente/fallisce il motore prosegue su Brave e poi DuckDuckGo.
        self.fonti: List[IFonteRicerca] = [
            FontePlaywrightStealth(self.db),
            FonteBraveSearch(api_key),
            FonteDuckDuckGo()]
        # SerpApi: stub non ancora implementato, si aggiunge solo quando lo sara'.
        self.fonte_serpapi = FonteSerpApi(serpapi_key)
        self.motore = MotoreRicerca(self.campagne, self.db, self.fonti,
                                    self.audit)
        self.ricerca = RicercaAlloggi(self.gate, self.audit,
                                      percorso_file=file_candidati)
        self.bozze = GestoreBozze(cartella_bozze, self.gate, self.audit)
        # FASE 7/8: moduli operativi cablati sull'unica fonte di verita' (il DB).
        self.ingestore = IngestoreVIP(self.db, self.audit)
        self.flash = FlashHostManager(self.db, self.audit)
        self.link_engine = LinkMagiciEngine(self.db, self.audit)
        self.ical_engine = iCalSyncEngine(self.db, self.audit)
        # Database verticali "Solo Professionisti": 4 file SQLite SEPARATI, nella
        # stessa cartella del DB candidati (cosi' i test restano in temp).
        cartella_db = os.path.dirname(db_candidati)
        self.db_immobili = GestoreRisorseVerticali(
            os.path.join(cartella_db, "db_immobili.sqlite3"), self.audit, self.gate)
        self.db_mezzi = GestoreRisorseVerticali(
            os.path.join(cartella_db, "db_mezzi.sqlite3"), self.audit, self.gate)
        self.db_talento = GestoreRisorseVerticali(
            os.path.join(cartella_db, "db_talento.sqlite3"), self.audit, self.gate)
        self.db_esperienze = GestoreRisorseVerticali(
            os.path.join(cartella_db, "db_esperienze.sqlite3"), self.audit, self.gate)
        # Mappa tipo->gestore per menu e CLI.
        self.risorse_per_tipo = {
            "immobili": self.db_immobili, "mezzi": self.db_mezzi,
            "talento": self.db_talento, "esperienze": self.db_esperienze}
        # Motore "Pacchetto Pronto" (V5): DB pacchetti separato; legge i 4
        # verticali in sola lettura tramite i gestori gia' cablati.
        self.motore_pacchetti = MotoreComposizionePacchetti(
            self.audit, os.path.join(cartella_db, "pacchetti.sqlite3"),
            self.risorse_per_tipo)
        # Generatore proposte (V6): scrive .md in BASE_DIR/Proposte_Clienti
        # (cartella creata lazy alla prima generazione).
        self.generatore = GeneratorePropostaCommerciale(
            self.audit, BASE_DIR, self.motore_pacchetti, self.risorse_per_tipo)
        # Distribuzione a Cascata (PARTE 3): coda + bilanciamento + template +
        # worker. Il worker NON parte da solo (niente thread in __init__): si
        # avvia con start_async() o si usa in modo sincrono (elabora_uno).
        self.coda_marketing = DistribuzioneQueueManager(self.db, self.audit)
        self.load_balancer = PartnerLoadBalancer(self.db, self.audit)
        self.template_engine = TemplateEngine(self.db)
        self.distribuzione_worker = DistribuzioneWorker(
            self.coda_marketing, self.load_balancer, self.template_engine,
            self.audit)
        self.audit.registra("avvio", {"progetto": self.config.get("progetto")})

    def distribuisci_proposta(self, candidato_url: str, payload: dict,
                              priorita: int = 0,
                              partner_id: Optional[int] = None,
                              template_id: Optional[int] = None) -> int:
        """Inserisce una proposta nella coda di marketing. Restituisce l'id del
        job. L'elaborazione effettiva avviene tramite il worker."""
        job_id = self.coda_marketing.accoda(
            candidato_url=candidato_url, partner_id=partner_id,
            template_id=template_id, payload=payload, priorita=priorita)
        self.audit.registra("proposta_distribuita",
                            {"job_id": job_id, "candidato_url": candidato_url})
        return job_id

    def componi_pacchetto(self, area: str, budget_max: float) -> dict:
        """Compone un pacchetto combinando 1 risorsa ATTIVA per categoria
        (immobile + mezzo + talento + esperienza) nell'area indicata, scegliendo
        la piu' economica di ciascuna. Restituisce il pacchetto se il totale
        rientra in budget_max, altrimenti {'esito': 'budget_insufficiente'}.
        Accede SOLO a risorse in stato 'attivo'."""
        area_l = area.lower()
        selezione = {}
        totale = 0.0
        for categoria, gestore in self.risorse_per_tipo.items():
            candidate = [r for r in gestore.elenca_attive()
                         if area_l in (r.get("area_geografica") or "").lower()]
            migliore, prezzo_migliore = None, None
            for r in candidate:
                try:
                    meta = json.loads(r.get("metadati_json") or "{}")
                except json.JSONDecodeError:
                    meta = {}
                prezzo = _prezzo_da_metadati(meta)
                if prezzo_migliore is None or prezzo < prezzo_migliore:
                    migliore, prezzo_migliore = r, prezzo
            if migliore is not None:
                selezione[categoria] = {"id": migliore["id"],
                                        "nome": migliore["nome"],
                                        "contatto": migliore["contatto_diretto"],
                                        "prezzo": prezzo_migliore}
                totale += prezzo_migliore
        if not selezione:
            esito = {"esito": "nessuna_risorsa_attiva", "area": area,
                     "pacchetto": {}, "totale": 0.0}
            self.audit.registra("pacchetto_composto", esito)
            return esito
        if totale > budget_max:
            esito = {"esito": "budget_insufficiente", "area": area,
                     "totale_minimo": round(totale, 2), "budget_max": budget_max}
            self.audit.registra("pacchetto_composto", esito)
            return esito
        esito = {"esito": "ok", "area": area, "pacchetto": selezione,
                 "totale": round(totale, 2), "budget_max": budget_max}
        self.audit.registra("pacchetto_composto",
                            {"esito": "ok", "area": area, "totale": esito["totale"]})
        return esito

    def _esecutore_email(self) -> Optional[Callable[["Bozza"], None]]:
        """Costruisce l'esecutore SMTP solo quando serve. Se le credenziali
        non ci sono, avvisa e restituisce None (l'invio resta simulato)."""
        try:
            credenziali = carica_credenziali_smtp(self.config)
        except RuntimeError as e:
            print(f"[ATTENZIONE] {e}")
            return None
        return crea_esecutore_smtp(credenziali)

    def menu(self) -> None:
        opzioni = {
            "1": "Imposta criteri e costruisci query alloggi",
            "2": "Aggiungi candidato alloggio",
            "3": "Mostra classifica candidati",
            "4": "Prepara bozza email",
            "5": "Prepara bozza testo social",
            "6": "Elenca e invia bozze esistenti",
            "7": "Esegui campagna per NOME (Task Scheduler ready)",
            "8": "Crea nuova campagna di ricerca",
            "9": "Report globale",
            "10": "Esporta CSV",
            "11": "Ingesta candidato VIP (geocodifica + contatti)",
            "12": "Crea annuncio Flash (scadenza 7 giorni)",
            "13": "Pulisci annunci Flash scaduti",
            "14": "Genera link magico (host/ospite)",
            "15": "Risolvi/usa un link magico",
            "16": "Sincronizza calendario iCal (import)",
            "17": "Genera feed iCal (export)",
            "18": "Inserisci risorsa (Immobili)",
            "19": "Inserisci risorsa (Mezzi)",
            "20": "Inserisci risorsa (Talento)",
            "21": "Inserisci risorsa (Esperienze)",
            "22": "Approva risorsa in attesa",
            "23": "Elenca risorse attive",
            "24": "Componi pacchetto (solo risorse Attive)",
            "25": "Pacchetto Pronto: componi (motore V5)",
            "26": "Pacchetto Pronto: invia richieste partner",
            "27": "Pacchetto Pronto: verifica scadenze",
            "28": "Pacchetto Pronto: registra risposta partner",
            "29": "Genera proposta commerciale",
            "30": "Elenca proposte generate",
            "31": "Leggi proposta (percorso)",
            "0": "Esci",
        }
        while True:
            print("\n=== ASSISTENTE GESTIONALE - TavolaVIP ===")
            for k, v in opzioni.items():
                print(f"  {k}. {v}")
            scelta = input("> ").strip()
            if scelta == "0":
                break
            elif scelta == "1":
                self._flow_query()
            elif scelta == "2":
                self._flow_aggiungi_candidato()
            elif scelta == "3":
                self._flow_classifica()
            elif scelta == "4":
                self._flow_email()
            elif scelta == "5":
                self._flow_social()
            elif scelta == "6":
                self._flow_bozze_salvate()
            elif scelta == "7":
                self._flow_esegui_campagna()
            elif scelta == "8":
                self._flow_crea_campagna()
            elif scelta == "9":
                self._flow_report_globale()
            elif scelta == "10":
                self._flow_esporta_csv()
            elif scelta == "11":
                self._flow_ingesta_vip()
            elif scelta == "12":
                self._flow_flash_crea()
            elif scelta == "13":
                self._flow_flash_pulisci()
            elif scelta == "14":
                self._flow_link_genera()
            elif scelta == "15":
                self._flow_link_risolvi()
            elif scelta == "16":
                self._flow_sync_ical()
            elif scelta == "17":
                self._flow_genera_ical()
            elif scelta in ("18", "19", "20", "21"):
                tipo = {"18": "immobili", "19": "mezzi",
                        "20": "talento", "21": "esperienze"}[scelta]
                self._flow_inserisci_risorsa(tipo)
            elif scelta == "22":
                self._flow_approva_risorsa()
            elif scelta == "23":
                self._flow_elenca_attive()
            elif scelta == "24":
                self._flow_componi_pacchetto()
            elif scelta == "25":
                self._flow_pp_componi()
            elif scelta == "26":
                self._flow_pp_invia()
            elif scelta == "27":
                self._flow_pp_scadenze()
            elif scelta == "28":
                self._flow_pp_risposta()
            elif scelta == "29":
                self._flow_genera_proposta()
            elif scelta == "30":
                self._flow_elenca_proposte()
            elif scelta == "31":
                self._flow_leggi_proposta()
            else:
                print("Scelta non valida.")

    def _flow_query(self) -> None:
        c = CriteriRicerca(
            citta=input("Citta': ").strip(),
            check_in=input("Check-in (AAAA-MM-GG): ").strip(),
            check_out=input("Check-out (AAAA-MM-GG): ").strip(),
            ospiti=chiedi_int("Ospiti [2]: ", default=2),
            budget_max_notte=chiedi_float("Budget max/notte [0]: "),
        )
        print("Query suggerita:", self.ricerca.costruisci_query(c))

    def _flow_aggiungi_candidato(self) -> None:
        self.ricerca.aggiungi_candidato(Alloggio(
            titolo=input("Titolo alloggio: ").strip(),
            prezzo_notte=chiedi_float("Prezzo/notte: "),
            url=input("URL (opz.): ").strip(),
        ))
        print(f"[OK] Candidato aggiunto. Totale: {len(self.ricerca.candidati)}")

    def _flow_classifica(self) -> None:
        if not self.ricerca.candidati:
            print("Nessun candidato salvato: aggiungine prima uno (opzione 2).")
            return
        budget = chiedi_float("Budget per la classifica [0]: ")
        print("\n-- Classifica --")
        for a in self.ricerca.classifica(budget):
            fuori = " (FUORI BUDGET)" if budget and a.prezzo_notte > budget else ""
            print(f"  {a.prezzo_notte:>7.2f}  {a.titolo}{fuori}")

    def _flow_email(self) -> None:
        b = self.bozze.crea_email(
            destinatario=input("Destinatario: ").strip(),
            oggetto=input("Oggetto: ").strip(),
            corpo=input("Corpo: ").strip(),
        )
        if input("Procedere all'invio reale? [s/N] ").strip().lower() == "s":
            # invia() richiede comunque l'approvazione 'APPROVO' dal gate
            # PRIMA di chiamare l'esecutore SMTP.
            self.bozze.invia(b, esecutore=self._esecutore_email())

    def _flow_social(self) -> None:
        b = self.bozze.crea_social(
            piattaforma=input("Piattaforma: ").strip(),
            testo=input("Testo del post: ").strip(),
        )
        if input("Procedere alla pubblicazione reale? [s/N] ").strip().lower() == "s":
            self.bozze.invia(b)

    def _flow_bozze_salvate(self) -> None:
        salvate = self.bozze.elenca_salvate()
        if not salvate:
            print("Nessuna bozza salvata nella cartella.")
            return
        print("\n-- Bozze salvate --")
        for i, (nome, b) in enumerate(salvate, start=1):
            print(f"  {i}. [{b.tipo:6}] {b.creata_il}  A: {b.destinatario}  -  {b.oggetto}")
        indice = chiedi_int("Numero della bozza da inviare [0 = annulla]: ", default=0)
        if indice == 0:
            return
        if not 1 <= indice <= len(salvate):
            print("Numero fuori elenco.")
            return
        nome, bozza = salvate[indice - 1]
        print(f"\nBozza selezionata: {nome}")
        esecutore = self._esecutore_email() if bozza.tipo == "email" else None
        # invia() richiede comunque l'approvazione 'APPROVO' dal gate.
        self.bozze.invia(bozza, esecutore=esecutore)

    def _flow_esegui_campagna(self) -> None:
        nome = input("Nome campagna: ").strip()
        if not nome:
            return
        try:
            stampa_riepilogo_ciclo(self.motore.esegui(nome))
        except Exception as e:
            logging.exception("Ciclo campagna '%s' fallito", nome)
            self.audit.registra("errore_ciclo",
                                {"campagna": nome, "errore": str(e)})
            print(f"[ERRORE] Ciclo non completato: {e}")

    def _flow_crea_campagna(self) -> None:
        nome = input("Nome campagna: ").strip()
        if not nome:
            return
        mercati: List[MercatoTarget] = []
        while True:
            citta = input(f"Mercato {len(mercati) + 1} - citta' "
                          "(vuoto = fine): ").strip()
            if not citta:
                break
            mercati.append(MercatoTarget(
                citta=citta,
                check_in=input("  Check-in (AAAA-MM-GG, opz.): ").strip(),
                check_out=input("  Check-out (AAAA-MM-GG, opz.): ").strip(),
                ospiti=chiedi_int("  Ospiti [2]: ", default=2),
                budget_max_notte=chiedi_float("  Budget max/notte [0 = nessuno]: "),
                parole_escluse=[p.strip() for p in
                                input("  Parole da escludere (virgole): ").split(",")
                                if p.strip()]))
        if not mercati:
            print("Nessun mercato: campagna annullata.")
            return
        campagna = CampagnaRicerca(
            nome=nome, mercati=mercati,
            max_richieste_giorno=chiedi_int("Max richieste/giorno [30]: ",
                                            default=30),
            scadenza=input("Scadenza (AAAA-MM-GG, vuoto = nessuna): ").strip())
        try:
            if self.campagne.crea_campagna(campagna):
                print(f"[OK] Campagna '{nome}' autorizzata: i cicli girano "
                      "senza ulteriori conferme (kill switch: revoca).")
        except Exception as e:
            logging.exception("Creazione campagna '%s' fallita", nome)
            self.audit.registra("errore_campagna",
                                {"nome": nome, "errore": str(e)})
            print(f"[ERRORE] {e}")

    def _flow_report_globale(self) -> None:
        try:
            print(json.dumps(self.db.report_globale(), indent=2,
                             ensure_ascii=False))
        except Exception as e:
            logging.exception("Report globale fallito")
            self.audit.registra("errore_report", {"errore": str(e)})
            print(f"[ERRORE] {e}")

    def _flow_esporta_csv(self) -> None:
        nome = input("Nome file CSV [candidati.csv]: ").strip() or "candidati.csv"
        try:
            quanti = self.db.esporta_csv(os.path.join(BASE_DIR, nome))
            print(f"[OK] Esportati {quanti} candidati in {nome}")
        except Exception as e:
            logging.exception("Export CSV fallito")
            self.audit.registra("errore_export", {"errore": str(e)})
            print(f"[ERRORE] {e}")

    # ----------------------- FASE 8: flussi dei moduli nuovi -----------------------
    def _flow_ingesta_vip(self) -> None:
        annuncio = {
            "titolo": input("Titolo annuncio VIP: ").strip(),
            "citta": input("Citta' (opz.): ").strip(),
            "indirizzo": input("Indirizzo da geocodificare (opz.): ").strip(),
            "testo": input("Testo/descrizione (con email/telefono): ").strip(),
            "prezzo": chiedi_float("Prezzo/notte [0]: "),
        }
        try:
            print(self.ingestore.ingesta([annuncio]))
        except Exception as e:
            logging.exception("Ingest VIP fallito")
            print(f"[ERRORE] {e}")

    def _flow_flash_crea(self) -> None:
        url = self.flash.crea_flash({
            "titolo": input("Titolo flash: ").strip(),
            "citta": input("Citta': ").strip(),
            "prezzo": chiedi_float("Prezzo/notte [0]: "),
        })
        print(f"[OK] Flash creato: {url} (scade tra {self.flash.DURATA_GIORNI} giorni)")

    def _flow_flash_pulisci(self) -> None:
        rimossi = self.flash.pulisci_scaduti()
        print(f"[OK] Annunci flash scaduti rimossi: {rimossi}")

    def _flow_link_genera(self) -> None:
        url = input("URL candidato: ").strip()
        ruolo = input("Ruolo [host/ospite]: ").strip().lower()
        if ruolo == "ospite":
            print("Link:", self.link_engine.genera_link_ospite(url))
        else:
            print("Link:", self.link_engine.genera_link_host(url))

    def _flow_link_risolvi(self) -> None:
        token = input("Token o URL del link magico: ").strip()
        dati = self.link_engine.risolvi_link(token)
        if dati is None:
            print("[INFO] Link inesistente.")
            return
        print(dati)
        if input("Eseguire un'azione? [s/N] ").strip().lower() == "s":
            azione = input("Azione: ").strip()
            stato = input("Nuovo stato candidato (opz.): ").strip()
            ok = self.link_engine.esegui_azione(token, azione, stato)
            print("[OK] Azione eseguita." if ok else "[INFO] Link gia' usato o invalido.")

    def _flow_sync_ical(self) -> None:
        url = input("URL candidato: ").strip()
        percorso = input("Percorso file .ics da importare: ").strip()
        try:
            with open(percorso, "r", encoding="utf-8") as f:
                contenuto = f.read()
            print(self.ical_engine.sync_da_ical(url, contenuto))
        except OSError as e:
            print(f"[ERRORE] File iCal non leggibile: {e}")

    def _flow_genera_ical(self) -> None:
        url = input("URL candidato: ").strip()
        feed = self.ical_engine.genera_ical_uscita(url)
        if not feed:
            print("[INFO] Nessun feed generato (icalendar assente?).")
            return
        nome = input("Salva come [uscita.ics]: ").strip() or "uscita.ics"
        percorso = os.path.join(BASE_DIR, nome)
        with open(percorso, "w", encoding="utf-8") as f:
            f.write(feed)
        print(f"[OK] Feed iCal salvato in {percorso}")

    # ----------------- Risorse verticali "Solo Professionisti" -----------------
    def _flow_inserisci_risorsa(self, tipo: str) -> None:
        gestore = self.risorse_per_tipo[tipo]
        nome = input(f"Nome risorsa ({tipo}): ").strip()
        contatto = input("Contatto diretto: ").strip()
        area = input("Area geografica: ").strip()
        meta = input('Metadati JSON (es. {"tipo":"villa","prezzo_giorno":150}): ').strip()
        nuovo_id = gestore.inserisci(nome, contatto, area, meta or "{}")
        if nuovo_id > 0:
            print(f"[OK] Risorsa #{nuovo_id} inserita (stato: da_approvare).")
        else:
            print("[ERRORE] Inserimento non riuscito (metadati JSON non validi?).")

    def _flow_approva_risorsa(self) -> None:
        tipo = input(f"Tipo {RISORSA_VERTICALI}: ").strip().lower()
        gestore = self.risorse_per_tipo.get(tipo)
        if gestore is None:
            print("Tipo non valido.")
            return
        in_attesa = gestore.elenca_da_approvare()
        if not in_attesa:
            print("Nessuna risorsa in attesa.")
            return
        for r in in_attesa:
            print(f"  #{r['id']}  {r['nome']} - {r['area_geografica']} "
                  f"- {r['contatto_diretto']}")
        id_ris = chiedi_int("ID da approvare [0 = annulla]: ", default=0)
        if id_ris <= 0:
            return
        # invia() del gate chiede 'APPROVO' prima di attivare.
        if gestore.approva(id_ris, approvatore="operatore_menu"):
            print(f"[OK] Risorsa #{id_ris} attivata.")
        else:
            print("[INFO] Approvazione non completata.")

    def _flow_elenca_attive(self) -> None:
        tipo = input(f"Tipo {RISORSA_VERTICALI}: ").strip().lower()
        gestore = self.risorse_per_tipo.get(tipo)
        if gestore is None:
            print("Tipo non valido.")
            return
        attive = gestore.elenca_attive()
        if not attive:
            print("Nessuna risorsa attiva.")
            return
        for r in attive:
            print(f"  #{r['id']}  {r['nome']} - {r['area_geografica']} "
                  f"- {r['contatto_diretto']}  {r['metadati_json']}")

    def _flow_componi_pacchetto(self) -> None:
        area = input("Area geografica: ").strip()
        budget = chiedi_float("Budget massimo: ")
        print(json.dumps(self.componi_pacchetto(area, budget),
                         indent=2, ensure_ascii=False))

    # ------------------- Pacchetto Pronto (motore V5) -------------------
    def _flow_pp_componi(self) -> None:
        destinazione = input("Destinazione: ").strip()
        budget = chiedi_float("Budget massimo: ")
        data_inizio = input("Data inizio (AAAA-MM-GG): ").strip()
        data_fine = input("Data fine (AAAA-MM-GG): ").strip()
        esigenze = input("Esigenze JSON (opz., Invio per saltare): ").strip()
        print(json.dumps(self.motore_pacchetti.componi(
            destinazione, budget, data_inizio, data_fine, esigenze or None),
            indent=2, ensure_ascii=False))

    def _flow_pp_invia(self) -> None:
        pid = chiedi_int("ID pacchetto: ", default=0)
        if pid <= 0:
            return
        print(json.dumps(self.motore_pacchetti.invia_richieste_partner(pid),
                         indent=2, ensure_ascii=False))

    def _flow_pp_scadenze(self) -> None:
        print(json.dumps(self.motore_pacchetti.verifica_scadenze(),
                         indent=2, ensure_ascii=False))

    def _flow_pp_risposta(self) -> None:
        rid = chiedi_int("ID richiesta partner: ", default=0)
        if rid <= 0:
            return
        esito = input("Esito [confermata/rifiutata]: ").strip().lower()
        nota = input("Nota (opz.): ").strip()
        ok = self.motore_pacchetti.registra_risposta_partner(rid, esito, nota)
        print("[OK] Risposta registrata." if ok else "[INFO] Richiesta inesistente.")

    # ------------------- Proposte commerciali (V6) -------------------
    def _flow_genera_proposta(self) -> None:
        pid = chiedi_int("ID pacchetto (confermato): ", default=0)
        if pid <= 0:
            return
        try:
            esito = self.generatore.genera(pid)
            print(f"[OK] Proposta generata: {esito['percorso']}")
            print(f"     Totale cliente: €{esito['totale_cliente']:.2f}")
        except ValueError as e:
            print(f"[INFO] {e}")
        except OSError as e:
            print(f"[ERRORE] Scrittura proposta non riuscita: {e}")

    def _flow_elenca_proposte(self) -> None:
        filtro = input("Filtra per destinazione (vuoto = tutte): ").strip() or None
        proposte = self.generatore.lista_proposte(filtro)
        if not proposte:
            print("Nessuna proposta trovata.")
            return
        for p in proposte:
            print(f"  {p['data']}  [{p['codice']}]  {p['destinazione']}")
            print(f"     {p['percorso']}")

    def _flow_leggi_proposta(self) -> None:
        percorso = input("Percorso file proposta: ").strip()
        try:
            print("\n" + self.generatore.leggi_proposta(percorso))
        except (FileNotFoundError, OSError) as e:
            print(f"[ERRORE] {e}")

    # ----------------------- Dashboard (sola lettura) -----------------------
    def _conta_errori_audit_recenti(self, ore: int = 24):
        """Conta gli eventi di errore nelle ultime 'ore' leggendo l'audit log
        (JSONL via self.audit). In questo progetto l'audit NON e' una tabella
        SQLite con colonna 'livello': e' un file JSONL, quindi si conta dal
        file gli eventi il cui nome inizia per 'errore'. Su problemi di lettura
        si restituisce 'N/A'."""
        try:
            soglia = datetime.datetime.now() - datetime.timedelta(hours=ore)
            quanti = 0
            with open(self.audit.percorso, "r", encoding="utf-8") as f:
                for riga in f:
                    riga = riga.strip()
                    if not riga:
                        continue
                    try:
                        evento = json.loads(riga)
                        quando = datetime.datetime.fromisoformat(
                            evento.get("timestamp", ""))
                    except (json.JSONDecodeError, ValueError):
                        continue
                    if (quando >= soglia
                            and str(evento.get("evento", "")).startswith("errore")):
                        quanti += 1
            return quanti
        except OSError:
            return "N/A"

    def mostra_dashboard(self) -> None:
        """Pannello di sintesi a SOLA LETTURA del progetto. Usa solo self.db e
        self.audit gia' presenti: query SQLite dirette su candidati e
        campagne_stato (ogni blocco protetto da OperationalError -> 'N/A' se la
        tabella non esiste ancora) ed errori recenti dall'audit. Nessuna azione
        esterna, nessuna scrittura: solo print formattato."""
        # I caratteri box-drawing richiedono stdout UTF-8 (su Windows la code
        # page di default potrebbe non gestirli): riconfiguriamo in modo difensivo.
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

        NA = "N/A"
        # --- Candidati: totale, ultimo trovato, top mercati per localita ---
        try:
            con = sqlite3.connect(self.db.db_path)
            try:
                totale, ultimo = con.execute(
                    "SELECT COUNT(*), MAX(data_trovato) FROM candidati").fetchone()
                per_localita = con.execute(
                    "SELECT localita, COUNT(*) FROM candidati "
                    "GROUP BY localita ORDER BY COUNT(*) DESC, localita LIMIT 5"
                ).fetchall()
            finally:
                con.close()
            tot_candidati = totale or 0
            ultimo_trovato = ultimo or "-"
        except sqlite3.OperationalError:
            tot_candidati, ultimo_trovato, per_localita = NA, NA, []

        # --- Campagne autorizzate: nome, eseguiti_oggi, ultimo_eseguito ---
        try:
            con = sqlite3.connect(self.db.db_path)
            try:
                campagne = con.execute(
                    "SELECT nome, eseguiti_oggi, ultimo_eseguito "
                    "FROM campagne_stato WHERE autorizzata = 1 ORDER BY nome"
                ).fetchall()
            finally:
                con.close()
        except sqlite3.OperationalError:
            campagne = NA

        # --- Errori nelle ultime 24h (dall'audit log JSONL) ---
        errori_24h = self._conta_errori_audit_recenti(24)

        # --- Disegno della tabella ASCII (box drawing) ---
        W = 56  # larghezza dell'area di contenuto
        def riga(testo: str = "") -> str:
            return f"│ {testo:<{W}} │"
        bordo_top = "┌" + "─" * (W + 2) + "┐"
        bordo_mid = "├" + "─" * (W + 2) + "┤"
        bordo_bot = "└" + "─" * (W + 2) + "┘"

        righe = [bordo_top, riga(f"{'DASHBOARD - TavolaVIP':^{W}}"), bordo_mid]
        righe.append(riga(f"Candidati totali     : {tot_candidati}"))
        righe.append(riga(f"Ultimo trovato       : {str(ultimo_trovato)[:33]}"))
        righe.append(riga(f"Errori (ultime 24h)  : {errori_24h}"))
        righe.append(bordo_mid)

        righe.append(riga("Top mercati (per n. candidati)"))
        if per_localita == [] and tot_candidati == NA:
            righe.append(riga(f"  {NA}"))
        elif not per_localita:
            righe.append(riga("  (nessun candidato)"))
        else:
            for localita, quanti in per_localita:
                righe.append(riga(f"  {str(localita)[:34]:<36}{quanti:>5}"))
        righe.append(bordo_mid)

        righe.append(riga("Campagne attive"))
        if campagne == NA:
            righe.append(riga(f"  {NA}"))
        elif not campagne:
            righe.append(riga("  (nessuna campagna autorizzata)"))
        else:
            for nome, eseguiti, ultimo_eseguito in campagne:
                ts = (str(ultimo_eseguito)[:16] if ultimo_eseguito else "mai")
                righe.append(riga(f"  {str(nome)[:22]:<24}oggi:{eseguiti or 0:<4}{ts}"))
        righe.append(bordo_bot)

        print("\n".join(righe))


def esegui_campagna_cli(nome: str) -> int:
    """Entry-point non interattivo (Task Scheduler): nessun prompt.
    Stampa il riepilogo del ciclo come JSON su stdout.
    Exit code 0 se il ciclo e' stato eseguito, 1 altrimenti."""
    assistente = None
    try:
        assistente = AssistenteGestionale()
        riepilogo = assistente.motore.esegui(nome)
        print(json.dumps(riepilogo, ensure_ascii=False))
        return 0 if riepilogo["eseguito"] else 1
    except Exception as e:
        logging.exception("Esecuzione campagna '%s' da CLI fallita", nome)
        if assistente is not None:
            assistente.audit.registra("errore_ciclo",
                                      {"campagna": nome, "errore": str(e)})
        print(f"[ERRORE] {e}", file=sys.stderr)
        return 1


def esegui_risorse_cli(argomenti) -> int:
    """Entry-point non interattivo per i database verticali (Task Scheduler ready).
    L'approvazione via CLI avviene SENZA gate (usa_gate=False): in automazione
    non c'e' un umano al prompt. Exit 0 se ok, 1 su errore."""
    try:
        assistente = AssistenteGestionale()
        if argomenti.inserisci_risorsa:
            tipo, dati = argomenti.inserisci_risorsa
            gestore = assistente.risorse_per_tipo.get(tipo.lower())
            if gestore is None:
                print(f"[ERRORE] Tipo '{tipo}' sconosciuto "
                      f"{RISORSA_VERTICALI}.", file=sys.stderr)
                return 1
            parti = dati.split("|", 3)
            if len(parti) < 4:
                print("[ERRORE] Formato atteso: 'nome|contatto|area|metadati_json'.",
                      file=sys.stderr)
                return 1
            nome, contatto, area, meta = (p.strip() for p in parti)
            nuovo_id = gestore.inserisci(nome, contatto, area, meta)
            if nuovo_id <= 0:
                return 1
            print(json.dumps({"inserita": nuovo_id, "tipo": tipo.lower()},
                             ensure_ascii=False))
        if argomenti.approva_risorsa:
            tipo, id_str = argomenti.approva_risorsa
            gestore = assistente.risorse_per_tipo.get(tipo.lower())
            if gestore is None:
                print(f"[ERRORE] Tipo '{tipo}' sconosciuto.", file=sys.stderr)
                return 1
            ok = gestore.approva(int(id_str), approvatore="cli", usa_gate=False)
            print(json.dumps({"approvata": int(id_str), "esito": ok},
                             ensure_ascii=False))
            if not ok:
                return 1
        if argomenti.elenca_attive:
            gestore = assistente.risorse_per_tipo.get(argomenti.elenca_attive.lower())
            if gestore is None:
                print(f"[ERRORE] Tipo '{argomenti.elenca_attive}' sconosciuto.",
                      file=sys.stderr)
                return 1
            print(json.dumps(gestore.elenca_attive(), indent=2, ensure_ascii=False))
        if argomenti.componi_pacchetto:
            area, budget = argomenti.componi_pacchetto
            print(json.dumps(assistente.componi_pacchetto(area, float(budget)),
                             indent=2, ensure_ascii=False))
        return 0
    except Exception as e:
        logging.exception("Comando risorse da CLI fallito")
        print(f"[ERRORE] {e}", file=sys.stderr)
        return 1


def esegui_proposte_cli(argomenti) -> int:
    """Entry-point non interattivo per il generatore di proposte (V6).
    Exit 0 se ok, 1 su errore."""
    try:
        assistente = AssistenteGestionale()
        gen = assistente.generatore
        if argomenti.genera_proposta:
            print(json.dumps(gen.genera(int(argomenti.genera_proposta)),
                             indent=2, ensure_ascii=False))
        if argomenti.elenca_proposte is not None:
            filtro = argomenti.elenca_proposte or None
            print(json.dumps(gen.lista_proposte(filtro),
                             indent=2, ensure_ascii=False))
        if argomenti.leggi_proposta:
            print(gen.leggi_proposta(argomenti.leggi_proposta))
        return 0
    except ValueError as e:
        print(f"[INFO] {e}", file=sys.stderr)
        return 1
    except Exception as e:
        logging.exception("Comando proposte da CLI fallito")
        print(f"[ERRORE] {e}", file=sys.stderr)
        return 1


def esegui_pacchetti_cli(argomenti) -> int:
    """Entry-point non interattivo per il motore Pacchetto Pronto (V5).
    Exit 0 se ok, 1 su errore."""
    try:
        assistente = AssistenteGestionale()
        motore = assistente.motore_pacchetti
        if argomenti.crea_pacchetto:
            dest, budget, d_in, d_fine = argomenti.crea_pacchetto
            print(json.dumps(motore.componi(dest, budget, d_in, d_fine),
                             indent=2, ensure_ascii=False))
        if argomenti.invia_richieste:
            print(json.dumps(
                motore.invia_richieste_partner(int(argomenti.invia_richieste)),
                indent=2, ensure_ascii=False))
        if argomenti.verifica_scadenze:
            print(json.dumps(motore.verifica_scadenze(),
                             indent=2, ensure_ascii=False))
        if argomenti.registra_risposta:
            rid, esito, nota = argomenti.registra_risposta
            ok = motore.registra_risposta_partner(int(rid), esito, nota)
            print(json.dumps({"registrata": int(rid), "esito": esito, "ok": ok},
                             ensure_ascii=False))
        return 0
    except Exception as e:
        logging.exception("Comando pacchetti da CLI fallito")
        print(f"[ERRORE] {e}", file=sys.stderr)
        return 1


def esegui_moduli_cli(argomenti) -> int:
    """Entry-point non interattivo per i moduli FASE 7 (Task Scheduler ready).
    Stampa l'esito su stdout. Exit code 0 se ok, 1 in caso di errore."""
    try:
        assistente = AssistenteGestionale()
        if argomenti.ingesta_vip:
            with open(argomenti.ingesta_vip, "r", encoding="utf-8") as f:
                annunci = json.load(f)
            print(json.dumps(assistente.ingestore.ingesta(annunci),
                             ensure_ascii=False))
        if argomenti.flash_host:
            with open(argomenti.flash_host, "r", encoding="utf-8") as f:
                dati = json.load(f)
            print(assistente.flash.crea_flash(dati))
        if argomenti.sync_ical:
            url_candidato, file_ics = argomenti.sync_ical
            with open(file_ics, "r", encoding="utf-8") as f:
                contenuto = f.read()
            print(json.dumps(
                assistente.ical_engine.sync_da_ical(url_candidato, contenuto),
                ensure_ascii=False))
        if argomenti.genera_ical:
            print(assistente.ical_engine.genera_ical_uscita(argomenti.genera_ical))
        if argomenti.risolvi_link:
            print(json.dumps(
                assistente.link_engine.risolvi_link(argomenti.risolvi_link),
                ensure_ascii=False))
        return 0
    except Exception as e:
        logging.exception("Comando modulo da CLI fallito")
        print(f"[ERRORE] {e}", file=sys.stderr)
        return 1


def main() -> None:
    # Output UTF-8 difensivo: i contenuti (proposte .md, dashboard, €, →) usano
    # caratteri non rappresentabili nella code page di default di Windows.
    for flusso in (sys.stdout, sys.stderr):
        try:
            flusso.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(
        description="Assistente Gestionale - Progetto TavolaVIP")
    parser.add_argument("--esegui-campagna", metavar="NOME",
                        help="esegue un ciclo della campagna ed esce "
                             "(riepilogo JSON su stdout)")
    parser.add_argument("--report-globale", action="store_true",
                        help="statistiche per paese/mercato in JSON")
    parser.add_argument("--top-opportunita", type=int, metavar="N",
                        help="i migliori N candidati mondiali per punteggio")
    parser.add_argument("--esporta-csv", metavar="NOME",
                        help="esporta i candidati in CSV per Excel")
    parser.add_argument("--ingesta-vip", metavar="FILE_JSON",
                        help="ingesta candidati VIP da un file JSON (lista di annunci)")
    parser.add_argument("--flash-host", metavar="FILE_JSON",
                        help="crea un annuncio flash da un file JSON")
    parser.add_argument("--sync-ical", nargs=2,
                        metavar=("URL_CANDIDATO", "FILE_ICS"),
                        help="importa le prenotazioni da un file .ics")
    parser.add_argument("--genera-ical", metavar="URL_CANDIDATO",
                        help="genera il feed iCal del candidato su stdout")
    parser.add_argument("--risolvi-link", metavar="TOKEN",
                        help="risolve un link magico e stampa i dati in JSON")
    parser.add_argument("--inserisci-risorsa", nargs=2,
                        metavar=("TIPO", "nome|contatto|area|metadati_json"),
                        help="inserisce una risorsa verticale (stato da_approvare)")
    parser.add_argument("--approva-risorsa", nargs=2, metavar=("TIPO", "ID"),
                        help="approva (attiva) una risorsa verticale")
    parser.add_argument("--elenca-attive", metavar="TIPO",
                        help="elenca le risorse attive di un verticale (JSON)")
    parser.add_argument("--componi-pacchetto", nargs=2, metavar=("AREA", "BUDGET"),
                        help="compone un pacchetto di risorse attive entro budget")
    parser.add_argument("--crea-pacchetto", nargs=4,
                        metavar=("DESTINAZIONE", "BUDGET", "DATA_INIZIO", "DATA_FINE"),
                        help="motore V5: compone un Pacchetto Pronto")
    parser.add_argument("--invia-richieste", metavar="PACCHETTO_ID",
                        help="invia le richieste partner di un pacchetto (timer 24h)")
    parser.add_argument("--verifica-scadenze", action="store_true",
                        help="verifica i pacchetti scaduti ed esegue il fallback")
    parser.add_argument("--registra-risposta", nargs=3,
                        metavar=("RICHIESTA_ID", "ESITO", "NOTA"),
                        help="registra la risposta di un partner a una richiesta")
    parser.add_argument("--genera-proposta", metavar="PACCHETTO_ID",
                        help="genera la proposta commerciale di un pacchetto confermato")
    parser.add_argument("--elenca-proposte", nargs="?", const="", metavar="DESTINAZIONE",
                        help="elenca le proposte generate (filtro destinazione opz.)")
    parser.add_argument("--leggi-proposta", metavar="PERCORSO_FILE",
                        help="stampa il contenuto Markdown di una proposta")
    parser.add_argument("--dashboard", action="store_true",
                        help="mostra un pannello di sintesi (sola lettura) ed esce")
    parser.add_argument("--menu", action="store_true",
                        help="avvia il menu interattivo (default)")
    argomenti = parser.parse_args()
    logging.basicConfig(level=logging.ERROR)  # traceback degli errori su stderr

    if argomenti.dashboard:
        assistente = AssistenteGestionale()
        assistente.mostra_dashboard()
        sys.exit(0)
    if (argomenti.inserisci_risorsa or argomenti.approva_risorsa
            or argomenti.elenca_attive or argomenti.componi_pacchetto):
        raise SystemExit(esegui_risorse_cli(argomenti))
    if (argomenti.crea_pacchetto or argomenti.invia_richieste
            or argomenti.verifica_scadenze or argomenti.registra_risposta):
        raise SystemExit(esegui_pacchetti_cli(argomenti))
    if (argomenti.genera_proposta or argomenti.elenca_proposte is not None
            or argomenti.leggi_proposta):
        raise SystemExit(esegui_proposte_cli(argomenti))
    if argomenti.esegui_campagna:
        raise SystemExit(esegui_campagna_cli(argomenti.esegui_campagna))
    if (argomenti.ingesta_vip or argomenti.flash_host or argomenti.sync_ical
            or argomenti.genera_ical or argomenti.risolvi_link):
        raise SystemExit(esegui_moduli_cli(argomenti))
    if (argomenti.report_globale or argomenti.top_opportunita
            or argomenti.esporta_csv):
        try:
            assistente = AssistenteGestionale()
            if argomenti.report_globale:
                print(json.dumps(assistente.db.report_globale(),
                                 indent=2, ensure_ascii=False))
            if argomenti.top_opportunita:
                print(json.dumps(
                    assistente.db.top_opportunita(argomenti.top_opportunita),
                    indent=2, ensure_ascii=False))
            if argomenti.esporta_csv:
                quanti = assistente.db.esporta_csv(
                    os.path.join(BASE_DIR, argomenti.esporta_csv))
                print(f"[OK] Esportati {quanti} candidati "
                      f"in {argomenti.esporta_csv}")
            raise SystemExit(0)
        except SystemExit:
            raise
        except Exception as e:
            logging.exception("Comando di report fallito")
            print(f"[ERRORE] {e}", file=sys.stderr)
            raise SystemExit(1) from e
    try:
        AssistenteGestionale().menu()
    except (KeyboardInterrupt, EOFError):
        print("\nUscita.")
    except Exception as exc:
        logging.exception("Errore non gestito nel menu")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
