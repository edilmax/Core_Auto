# -*- coding: utf-8 -*-
"""LA MACCHINA DELLE COMBINAZIONI DEI SOLDI — blocco 1, punto 1 del PIANO DEI SOLDI (11/10).

COSA FA. Prende una prenotazione PAGATA e le fa succedere sopra, in tutti gli ordini possibili,
i gesti che muovono soldi -- l'ospite cancella, l'host cancella, il rimborso dell'admin, il
pulsante dei rimborsi dovuti, «tutto ok», «segnala un problema», l'arbitro, la contestazione
della carta, i dati fiscali dell'host -- mentre l'OROLOGIO AVANZA davvero fra un gesto e l'altro
(subito, dopo le 48 ore, il giorno d'arrivo, la fine del giorno d'arrivo, lo sblocco della
garanzia, dopo la partenza) e a ogni passo dell'orologio gira il GIRO ORARIO del server. Dopo
OGNI passo guarda tre conti, presi da chi i soldi li muove e non dal nostro database:

  PIATTAFORMA  uscito <= incassato: rimborsi chiesti a Stripe + bonifici all'host + soldi tolti
               da una contestazione della carta non superano mai quello che Stripe ha incassato;
  HOST         quello che la garanzia assegna all'host = bonificato + ancora da pagare
               (registro dei bonifici 'maturato'); finche' la garanzia non ha deciso, all'host
               non e' uscito niente;
  OSPITE       il rimborso promesso (la riga «rimborso» del giornale, e la cifra detta nella
               risposta) = rimborsato su Stripe, oppure in lista nei «rimborsi da eseguire».
E a FINE CORSA, dopo la partenza: nessun blocco sulla carta lasciato aperto, nessuna garanzia
rimasta ferma oltre la sua scadenza. Una risposta 5xx e' un difetto anche lei.

⛔ I SOLDI SI CONTANO DA CHI LI MUOVE. Stripe e Connect sono finti SOLO NELLA RETE: i fornitori
   veri (`fase85.ProviderStripe`, `fase101.ProviderConnect`) girano interi, e la rete finta
   RICORDA cosa le e' stato chiesto e si comporta come quella vera dove conta: il blocco sulla
   carta (`requires_capture`) si incassa o si annulla una volta sola e scade da solo dopo 7
   giorni; un rimborso su un pagamento contestato e' rifiutato (`charge_disputed`), oltre il
   residuo e' rifiutato (`amount_too_large` / `charge_already_refunded`); la stessa
   Idempotency-Key entro 24 ore ridà la stessa risposta, con parametri diversi e' un errore, e
   dopo 24 ore fa una richiesta NUOVA (docs.stripe.com/error-codes e /api/idempotent_requests,
   letti l'11/10/2026). Il SALDO DISPONIBILE della piattaforma e' ZERO: un bonifico all'host
   non legato all'addebito dell'ospite fallisce (`balance_insufficient`); legato
   (`source_transaction`) passa, se la somma dei bonifici su quell'addebito non lo supera
   (docs.stripe.com/connect/separate-charges-and-transfers, «Transfer availability», letto
   l'11/10/2026 -- Compito 41).

⛔ IL GIRO ORARIO E' UNA COPIA, E LA COPIA SI CONFRONTA COL VIVO. `_tick_garanzia` vive dentro
   `avvia_server` e non si puo' chiamare: qui si ricopia (`GIRO_ORARIO_COPIATO`) e
   `test_A_...` legge l'albero sintattico di `fase83_server.py` e diventa ROSSA se il giro vero
   chiama altro, o in un altro ordine.

LE FONTI (D25, lette l'11/10/2026 prima di scrivere una riga):
  · J. Hughes, «Experiences with QuickCheck: testing the hard stuff and staying sane», 2016:
    i sistemi con stato si provano generando SEQUENZE di chiamate e, dopo ogni chiamata, una
    postcondizione; i difetti veri stavano in sequenze di 5-6 chiamate; e «gli errori sono
    spesso nel modello, non nel codice» -- un rosso di questa macchina si diagnostica PRIMA di
    chiamarlo difetto.
  · D.R. Kuhn, D.R. Wallace, A.M. Gallo, IEEE TSE 30(6), 2004: i guasti studiati scattano con
    poche condizioni insieme (quasi tutti entro 4-6), quindi provare TUTTE le combinazioni
    piccole e' quasi esaustivo; ma avvertono che non basta per il software che dipende da
    SEQUENZE di eventi -- per questo qui si enumerano sequenze, non solo combinazioni.
  · TigerBeetle, «A Tale of Four Fuzzers», 2025: il tempo e' simulato e avanza a passi,
    gli invarianti si controllano a ogni passo, un fallimento si ripete dal seme.
  · Hypothesis, documentazione «stateful testing»: gli @invariant girano dopo OGNI passo.
    Qui non si usa la libreria: le sequenze corte si enumerano TUTTE (piccolo ambito), le lunghe
    si estraggono da un seme fisso -- cosi' un giro si ripete identico anche dove Hypothesis non
    c'e'.

COME SI USA
    python test_macchina_dei_soldi.py --giro suite      4 configurazioni, al massimo 1 gesto
    python test_macchina_dei_soldi.py --giro corto      32 configurazioni, al massimo 1 gesto
    python test_macchina_dei_soldi.py --giro lungo      32 configurazioni, TUTTE le coppie di
                                                        gesti, piu' --casuali N sequenze da 3 a
                                                        6 gesti dal --seme S (ore: va staccato)
    python test_macchina_dei_soldi.py --autoprova       si vede gridare sui guasti e tacere sani
    python test_macchina_dei_soldi.py --una "lontano,flessibile,si,piccolo" "subito:tutto_ok"
                                                        ripete UNA corsa e stampa i fatti grezzi
                                                        dopo ogni passo
  Uscita 0 = nessun difetto; 1 = difetti (elencati, con la sequenza piu' corta che li mostra);
  2 = NON ESEGUITO (la macchina non era in condizione di misurare: nessun numero e' valido).

⛔ D18, LE QUATTRO CONDIZIONI DI UNO STRUMENTO CHE MISURA:
   1. misura PRIMA se stesso: `precondizioni()` controlla che l'orologio finto comandi davvero
      Python e SQLite, che la rete finta sia quella usata, che la copia del giro orario sia
      quella viva, che ogni configurazione sia quella che dichiara, e che una corsa senza
      gesti MUOVA davvero soldi; se una sola cosa non torna esce con 2 e non stampa numeri;
   2. provata nelle DUE direzioni: `--autoprova` inietta quattro guasti VERI nel prodotto (in
      memoria, mai nei file) e pretende il rosso del conto giusto, poi la stessa corsa SANA verde;
   3. dichiara cosa NON guarda: `NON_GUARDA`, stampato a ogni giro;
   4. e' sotto guardia: le prove `test_A` .. `test_D` qui sotto girano nella suite.
"""
import ast
import itertools
import json
import os
import random
import shutil
import subprocess  # nosec B404 - lancia SOLO questo file, nessun input esterno
import sys
import tempfile
import time
import unittest
from urllib.parse import parse_qs, urlparse

QUI = os.path.dirname(os.path.abspath(__file__))

# L'istante zero e' FISSO: il 4 novembre 2026 alle 9 UTC (le 10 a Roma, dopo il cambio d'ora di
# fine ottobre). Scritto in parole e non come data ISO: `collaudi/bombe_a_tempo.py` legge le date
# ISO dei file di prova come scadenze. Un giro si ripete identico; il prezzo e' che i giorni del
# cambio d'ora non si vedono (NON_GUARDA). La macchina non ne soffre: l'orologio e' il suo.
ISTANTE_ZERO = 1793782800
CHIAVE_FINTA = "sk_test_macchina"       # costanti, non letterali sul posto (bandit B106)
SEGRETO_WEBHOOK = "whsec_macchina"
CHIAVE_HOST = "hk"
CHIAVE_ADMIN = "ak"
AK = {"X-Admin-Key": CHIAVE_ADMIN}

POLITICHE = ("flessibile", "moderata", "rigida", "non_rimborsabile")
# vicino: si incassa subito; lontano: blocco sulla carta (arrivo a >= GIORNI_MINIMI_BLOCCO).
# Lo dichiarato si controlla in `precondizioni()`, non si crede.
ARRIVI = {"vicino": 3, "lontano": 8}
# prezzo netto per notte, due notti: piccolo sotto la soglia DAC7, grande sopra (host da segnalare)
IMPORTI = {"piccolo": 10000, "grande": 105000}
NOTTI = 2

CONFIGURAZIONI = tuple(itertools.product(ARRIVI, POLITICHE, ("si", "no"), IMPORTI))
CONFIG_SUITE = (("vicino", "flessibile", "si", "piccolo"), ("lontano", "flessibile", "si", "piccolo"),
                ("vicino", "rigida", "no", "grande"), ("lontano", "moderata", "no", "grande"))

TEMPI = ("subito", "dopo_48_ore", "giorno_arrivo", "fine_giorno_arrivo", "sblocco_garanzia",
         "dopo_partenza")
GESTI = ("ospite_cancella", "host_cancella", "admin_rimborso", "pulsante", "tutto_ok", "segnala",
         "arbitro_0", "arbitro_50", "arbitro_100", "chargeback", "dati_fiscali")
CHI_SCRIVE_UN_DOVUTO = ("ospite_cancella", "host_cancella", "admin_rimborso",
                        "arbitro_0", "arbitro_50", "arbitro_100")

# Quello che `_tick_garanzia` (fase83_server.avvia_server) chiama, in ordine. La copia e' in
# `Corsa.giro_orario`; `test_A_...` la confronta col vivo.
GIRO_ORARIO_COPIATO = ("_ritenta_bonifici_fermi", "_incassa_blocchi", "_subentro_per_disaccordo",
                       "_sblocca_garanzie_scadute",
                       "_pulizia_uploads_se_ora", "_conservazione_se_ora",
                       "_riscuoti_carta_se_ora", "sleep")

NON_GUARDA = (
    "UNA prenotazione per corsa, un host, un annuncio a Roma, in euro: le penali dell'host che "
    "compensano ALTRI suoi bonifici, il cambio di valuta e le gare fra due prenotazioni non "
    "si vedono",
    "il paga-in-struttura (anticipo online), il su-richiesta, lo split di gruppo, il Credito "
    "Viaggio e il deposito cauzionale: non sono fra i gesti",
    "il subentro per disaccordo in chat (serve che scrivano tutti e due): il giro lo chiama, ma "
    "nessuna corsa scrive in chat, quindi non scatta mai",
    "lo Scatto 3 (carta dell'host addebitata fuori sessione): resta spento come in produzione "
    "finche' SCATTO3_ATTIVO non e' acceso",
    "il giorno del cambio d'ora: l'istante zero e' fisso a novembre",
    "l'orologio di SQLite e' spostato solo quando 'now' e' il PRIMO argomento (`datetime('now')`, "
    "la forma che usa il prodotto); `strftime('%s','now')` resta sull'ora vera -- nessun modulo "
    "dei soldi lo usa (grep dell'11/10), ma un modulo nuovo che lo usasse sfuggirebbe",
    "una contestazione della carta che si CHIUDE (vinta o persa): il prodotto non la gestisce, e "
    "qui si conta come soldi tolti per l'intero residuo, senza la commissione di 15 euro",
    "la commissione di Stripe e quella del bonifico: i conti sono sull'importo, non sul netto",
    "gli errori di Stripe di VALIDAZIONE non si salvano sulla chiave (come dice la "
    "documentazione); quali errori siano di validazione e quali di esecuzione e' una scelta "
    "della rete finta, non una misura",
    "un guasto di rete o di Stripe a meta' di un gesto: la rete finta risponde sempre",
    "le sequenze da 3 gesti in su sono un CAMPIONE dal seme, non tutte",
    "il saldo disponibile e' SEMPRE zero: un bonifico non legato all'addebito fallisce sempre (in "
    "produzione fallisce quando il saldo non basta, cioe' quasi sempre coi bonifici automatici "
    "del conto); la valuta dell'addebito non si confronta (tutto in euro)",
    "un bonifico legato a un addebito NON ancora incassato: cosa fa Stripe non e' documentato; il "
    "prodotto non lo chiede mai (BONIFICO FERMATO), e se lo chiedesse lo vedrebbe il conto "
    "PIATTAFORMA (l'incassato conta solo i pagamenti 'succeeded')",
)


# --------------------------------------------------------------------------------------
# l'orologio e il prodotto: SOLO nel processo della macchina, mai in quello della suite
# --------------------------------------------------------------------------------------
_P = {}


def _accendi(rompi_orologio=False):
    """Orologio finto PRIMA del prodotto: chi fa `from datetime import datetime` all'import deve
    trovare quello finto. Si riusa quello di `collaudi/bombe_a_tempo.py` (D10), che sposta anche
    `gmtime`, `localtime` e l'orologio di SQLite (le cinque trappole del 13/08)."""
    if _P:
        return _P
    sys.path.insert(0, QUI)
    from collaudi import bombe_a_tempo as orologio
    orologio.installa_orologio()
    orologio._SCARTO[0] = 0
    orologio._BASE[0] = ISTANTE_ZERO
    if rompi_orologio:
        # solo per `test_B`: un orologio che NON comanda SQLite. La macchina deve accorgersene.
        orologio._sq.connect = orologio._vera_connect
    import logging
    logging.disable(logging.CRITICAL)
    import fase59_concierge
    import fase85_pagamenti_stripe
    import fase83_server
    from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
    from fase87_stripe_webhook import firma_di_test
    from fase101_stripe_connect import crea_provider_connect
    from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256
    _P.update(orologio=orologio, concierge=fase59_concierge, stripe=fase85_pagamenti_stripe,
              server=fase83_server, ConfigCasaVIP=ConfigCasaVIP, crea_sistema=crea_sistema,
              firma_di_test=firma_di_test, crea_provider_connect=crea_provider_connect,
              CONTRATTO_HOST_VERSIONE=CONTRATTO_HOST_VERSIONE, doc_sha256=doc_sha256)
    return _P


def _ora():
    return int(_P["orologio"]._BASE[0])


def _vai(ts):
    _P["orologio"]._BASE[0] = int(ts)


# --------------------------------------------------------------------------------------
# la rete di Stripe, finta: ricorda e si comporta come quella vera dove conta
# --------------------------------------------------------------------------------------
class ErroreStripe(Exception):
    """Come l'HTTPError vero: `read()` da' il corpo JSON dell'errore, che i fornitori leggono."""

    def __init__(self, codice, messaggio):
        super().__init__("HTTP Error 400: Bad Request")
        self.code = 400
        self._corpo = json.dumps({"error": {"type": "invalid_request_error", "code": codice,
                                            "message": messaggio}}).encode("utf-8")

    def read(self):
        return self._corpo


class ReteStripe:
    """Pagamenti, blocchi, rimborsi, contestazioni e bonifici, per riferimento di prenotazione."""

    SETTE_GIORNI = 7 * 86400
    VITA_CHIAVE = 24 * 3600

    def __init__(self):
        self.sessioni = {}      # cs -> {rif, importo, manuale, chiusa}
        self.pagamenti = {}     # pi -> {rif, importo, manuale, stato, autorizzato_ts, rimborsi, contestato}
        self.bonifici = []      # {rif, importo, acct, ts, fonte}
        self.chiavi = {}        # Idempotency-Key -> (ts, parametri, risposta)
        self.conta = 0

    # ── i fatti, per i conti ──
    def _di(self, rif):
        return self.pagamenti.get("pi_" + rif)

    def incassato(self, rif):
        p = self._di(rif)
        return p["importo"] if p and self._stato(p) == "succeeded" else 0

    def rimborsato(self, rif):
        p = self._di(rif)
        return sum(r["amount"] for r in p["rimborsi"]) if p else 0

    def contestato(self, rif):
        p = self._di(rif)
        return p["contestato"] if p else 0

    def bonificato(self, rif):
        return sum(b["importo"] for b in self.bonifici if b["rif"] == rif)

    def stato_pi(self, rif):
        p = self._di(rif)
        return self._stato(p) if p else ""

    def _stato(self, p):
        if p["stato"] == "requires_capture" and _ora() >= p["autorizzato_ts"] + self.SETTE_GIORNI:
            p["stato"] = "canceled"          # l'autorizzazione scade da sola (7 giorni)
        return p["stato"]

    # ── i gesti che arrivano dal mondo, non dal nostro codice ──
    def paga(self, rif):
        """L'ospite paga sulla pagina di Stripe: la sessione si chiude."""
        s = self.sessioni["cs_" + rif]
        s["chiusa"] = True
        self.pagamenti["pi_" + rif] = {
            "rif": rif, "importo": s["importo"], "manuale": s["manuale"],
            "stato": "requires_capture" if s["manuale"] else "succeeded",
            "autorizzato_ts": _ora(), "rimborsi": [], "contestato": 0}

    def contesta(self, rif):
        """La banca dell'ospite apre una contestazione: Stripe toglie il residuo dal nostro saldo."""
        p = self._di(rif)
        p["contestato"] = p["importo"] - sum(r["amount"] for r in p["rimborsi"])
        return p["contestato"]

    # ── la rete ──
    def __call__(self, url, body, headers):
        chiave = {str(k).lower(): v for k, v in (headers or {}).items()}.get("idempotency-key", "")
        parametri = body.decode("utf-8") if body else ""
        if body and chiave:
            vecchia = self.chiavi.get(chiave)
            if vecchia and _ora() - vecchia[0] < self.VITA_CHIAVE:
                if vecchia[1] != (url, parametri):
                    raise ErroreStripe("idempotency_error",
                                       "Keys for idempotent requests can only be used with the "
                                       "same parameters they were first used with.")
                return json.loads(vecchia[2])
        risposta = self._rispondi(url.split("?", 1)[0], url, body)
        if body and chiave:
            self.chiavi[chiave] = (_ora(), (url, parametri), json.dumps(risposta))
        return risposta

    def _rispondi(self, percorso, url, body):
        q = {k: v[-1] for k, v in parse_qs(body.decode("utf-8")).items()} if body else {}
        if percorso.endswith("/v1/checkout/sessions") and body:
            rif = q.get("metadata[riferimento]", "")
            cs = "cs_" + rif
            manuale = any(k.endswith("[capture_method]") and v == "manual" for k, v in q.items())
            self.sessioni[cs] = {"rif": rif, "importo": int(q["line_items[0][price_data][unit_amount]"]),
                                 "manuale": manuale, "chiusa": False}
            return {"id": cs, "object": "checkout.session", "url": "https://checkout.test/" + cs}
        if "/v1/checkout/sessions/" in percorso and not body:
            cs = percorso.rstrip("/").rsplit("/", 1)[-1]
            s = self.sessioni.get(cs)
            if s is None:
                raise ErroreStripe("resource_missing", "No such checkout.session: " + cs)
            if not s["chiusa"]:
                return {"id": cs, "status": "open", "payment_status": "unpaid", "payment_intent": None}
            pi = "pi_" + s["rif"]
            return {"id": cs, "status": "complete", "payment_intent": pi,
                    "payment_status": "unpaid" if s["manuale"] else "paid"}
        if percorso.endswith("/v1/refunds") and not body:
            pi = (parse_qs(urlparse(url).query).get("payment_intent") or [""])[0]
            p = self.pagamenti.get(pi)
            return {"object": "list", "has_more": False,
                    "data": [dict(r) for r in (p["rimborsi"] if p else [])]}
        if percorso.endswith("/v1/refunds") and body:
            return self._rimborso(q.get("payment_intent", ""), int(q.get("amount") or 0))
        if "/v1/payment_intents/" in percorso:
            pezzi = percorso.split("/v1/payment_intents/", 1)[1].split("/")
            p = self.pagamenti.get(pezzi[0])
            if p is None:
                raise ErroreStripe("resource_missing", "No such payment_intent: " + pezzi[0])
            stato = self._stato(p)
            if len(pezzi) > 1 and pezzi[1] in ("capture", "cancel") and body:
                if stato != "requires_capture":
                    raise ErroreStripe("payment_intent_unexpected_state",
                                       "This PaymentIntent could not be %s because it has a status "
                                       "of %s." % ("captured" if pezzi[1] == "capture" else "canceled",
                                                   stato))
                p["stato"] = "succeeded" if pezzi[1] == "capture" else "canceled"
                return {"id": pezzi[0], "status": p["stato"]}
            # `latest_charge` e' l'id dell'addebito; l'oggetto intero solo con `expand[]`.
            # `disputed` c'e' sempre nell'oggetto Charge vero («Whether the charge has been
            # disputed», docs.stripe.com/api/charges/object, letta il 16/10): senza, il prodotto
            # risponderebbe «non lo so» e ogni pulsante resterebbe spento (visto il 16/10, S4).
            addebito = {"id": "ch_" + p["rif"], "disputed": bool(p["contestato"]),
                        "payment_method_details": {"card": {"fingerprint": ""}}}
            espanso = "latest_charge" in (parse_qs(urlparse(url).query).get("expand[]") or [])
            return {"id": pezzi[0], "status": stato, "amount": p["importo"],
                    "amount_capturable": p["importo"] if stato == "requires_capture" else 0,
                    "amount_received": p["importo"] if stato == "succeeded" else 0,
                    "latest_charge": addebito if espanso else addebito["id"]}
        if percorso.endswith("/v1/transfers") and body:
            fonte = q.get("source_transaction", "")
            if not fonte:
                raise ErroreStripe("balance_insufficient", "You have insufficient funds in your "
                                                           "Stripe account.")
            p = self.pagamenti.get("pi_" + fonte[3:]) if fonte.startswith("ch_") else None
            if p is None:
                raise ErroreStripe("resource_missing", "No such charge: '%s'" % fonte)
            importo = int(q.get("amount") or 0)
            if importo + sum(b["importo"] for b in self.bonifici if b["fonte"] == fonte) \
                    > p["importo"]:
                # la regola e' documentata, il suo codice d'errore no: quello dei rimborsi
                raise ErroreStripe("amount_too_large", "The transfers exceed the source charge.")
            self.conta += 1
            self.bonifici.append({"rif": q.get("metadata[riferimento]", ""), "importo": importo,
                                  "acct": q.get("destination", ""), "ts": _ora(), "fonte": fonte,
                                  "id": "tr_%d" % self.conta,
                                  "valuta": q.get("currency", "")})
            return {"id": "tr_%d" % self.conta, "object": "transfer"}
        if percorso.endswith("/v1/transfers") and not body:
            # la rilettura anti-doppio del Connect (Pilastro zero, 19/10): la lista vera dei
            # bonifici verso quel conto, il piu' nuovo per primo (docs.stripe.com/api/transfers/list)
            dest = (parse_qs(urlparse(url).query).get("destination") or [""])[0]
            return {"object": "list", "has_more": False, "data": [
                {"id": b["id"], "object": "transfer", "amount": b["importo"],
                 "currency": b["valuta"], "destination": b["acct"],
                 "metadata": {"riferimento": b["rif"]}, "reversed": False, "amount_reversed": 0}
                for b in reversed(self.bonifici) if b["acct"] == dest]}
        # commissioni e movimenti di saldo: non modellati (NON_GUARDA), il prodotto li dichiara
        # «sconosciuti» invece di inventarli.
        raise ErroreStripe("resource_missing", "non modellato dalla rete finta: " + percorso)

    def _rimborso(self, pi, importo):
        p = self.pagamenti.get(pi)
        if p is None:
            raise ErroreStripe("resource_missing", "No such payment_intent: " + pi)
        stato = self._stato(p)
        if stato != "succeeded":
            # misurato su Stripe di prova il 28/9 (fase85, docstring di `annulla`)
            raise ErroreStripe("payment_intent_unexpected_state",
                               "You must cancel the PaymentIntent to reverse the authorization "
                               "instead of refunding the Charge directly.")
        if p["contestato"]:
            raise ErroreStripe("charge_disputed", "Charge %s has been charged back; cannot issue "
                                                  "a refund." % ("ch_" + p["rif"]))
        residuo = p["importo"] - sum(r["amount"] for r in p["rimborsi"])
        if residuo <= 0:
            raise ErroreStripe("charge_already_refunded",
                               "Charge %s has already been refunded." % ("ch_" + p["rif"]))
        if importo > residuo:
            raise ErroreStripe("amount_too_large", "Refund amount is greater than unrefunded "
                                                   "amount on charge.")
        self.conta += 1
        r = {"id": "re_%d" % self.conta, "object": "refund", "status": "succeeded",
             "amount": importo, "payment_intent": pi}
        p["rimborsi"].append(r)
        return dict(r)


# --------------------------------------------------------------------------------------
# una corsa: una prenotazione, una sequenza di gesti, l'orologio che avanza
# --------------------------------------------------------------------------------------
def _config_sistema(cartella):
    P = _P
    campi = {k: os.path.join(cartella, k[3:] + ".db")
             for k in vars(P["ConfigCasaVIP"]()) if k.startswith("db_")}
    # I numeri dei soldi sono quelli di `main_casavip.py` (produzione), non quelli di comodo dei
    # banchi: commissione a regime, rampa di lancio accesa, tariffa tecnica con la quota fissa.
    return P["ConfigCasaVIP"](
        abilitato=True, segreto_hmac=b"M" * 32, con_registrazione_host=True,
        commissione_bps=1000, promo_lancio_attiva=True, psp_bps=500, psp_bps_valuta_estera=700,
        psp_fisso_cents=25, stripe_secret_key=CHIAVE_FINTA, stripe_webhook_secret=SEGRETO_WEBHOOK,
        stripe_success_url="https://bookinvip.com/grazie.html",
        stripe_cancel_url="https://bookinvip.com/annullato.html",
        file_referral=os.path.join(cartella, "referral.json"), **campi)


def _giorno_zero():
    import datetime as _d
    z = time.gmtime(ISTANTE_ZERO)
    return _d.date(z.tm_year, z.tm_mon, z.tm_mday)


# L'host di ogni configurazione si prepara UNA volta (registrazione, Stripe, annuncio,
# calendario) e ogni corsa parte da una COPIA dei suoi archivi: e' un riavvio del server fra la
# preparazione e la prenotazione, cosa che in produzione succede a ogni deploy. Misurato l'11/10:
# rifare tutto a ogni corsa costava da 1 a 4 secondi, e cresceva col numero di archivi creati.
_BASI = {}


def _prepara_base(config, radice):
    import datetime as _d
    P = _P
    arrivo, politica, collegato, importo = config
    cartella = tempfile.mkdtemp(dir=radice, prefix="base_")
    P["stripe"].ProviderStripe._fetch_reale = staticmethod(ReteStripe())
    _vai(ISTANTE_ZERO - 86400)                    # l'host si e' registrato ieri (rampa: 0%)
    sis = P["crea_sistema"](_config_sistema(cartella))
    r = P["server"].crea_router(sis, host_key=CHIAVE_HOST, admin_key=CHIAVE_ADMIN,
                                base_url="https://bookinvip.com")

    def g(m, p, b=None, h=None):
        return r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})
    s, c = g("POST", "/api/host/registrazione",
             {"email": "host@macchina.test", "password": "password1",
              "accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True,
              "doc_sha256": P["doc_sha256"](), "versione": P["CONTRATTO_HOST_VERSIONE"]})
    Corsa._esige(s == 201, "registrazione host", s, c)
    hid, token = c["host_id"], c["token"]
    if collegato == "si":
        sis.registro_host.imposta_stripe_account(hid, "acct_macchina")
    zero = _giorno_zero()
    prezzo = IMPORTI[importo]
    s1, c1 = g("POST", "/api/host/pubblica",
               {"slug": "casa-macchina", "titolo": "Casa della macchina", "citta": "Roma",
                "prezzo_notte_cents": prezzo, "capacita": 2, "politica_cancellazione": politica},
               {"X-Host-Token": token})
    s2, c2 = g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": "casa-macchina", "da": zero.isoformat(),
                "a": (zero + _d.timedelta(days=30)).isoformat(), "unita_totali": 1,
                "prezzo_netto_cents": prezzo}, {"X-Host-Token": token})
    Corsa._esige(s1 == 201 and s2 == 200, "annuncio e calendario", (s1, s2), (c1, c2))
    g = r = sis = None
    import gc
    gc.collect()                                  # archivi chiusi prima della copia
    return cartella, hid, token


class Corsa:
    """Una vita intera di una prenotazione, dentro un processo solo, come in produzione."""

    def __init__(self, config, radice):
        import datetime as _d
        self.config = config
        self.arrivo, self.politica, collegato, self.importo = config
        self.collegato = collegato == "si"
        zero = _giorno_zero()
        self.ci = (zero + _d.timedelta(days=ARRIVI[self.arrivo])).isoformat()
        self.co = (zero + _d.timedelta(days=ARRIVI[self.arrivo] + NOTTI)).isoformat()
        if config not in _BASI:
            _BASI[config] = _prepara_base(config, radice)
        base, self.hid, token = _BASI[config]
        self.th = {"X-Host-Token": token}
        self.cartella = os.path.join(radice, "corsa_%d" % len(os.listdir(radice)))
        shutil.copytree(base, self.cartella)
        self.rete = ReteStripe()
        P = _P
        P["stripe"].ProviderStripe._fetch_reale = staticmethod(self.rete)
        _vai(ISTANTE_ZERO - 60)
        self.sis = P["crea_sistema"](_config_sistema(self.cartella))
        self.sis.connect = P["crea_provider_connect"](CHIAVE_FINTA, fetch=self.rete)
        self.r = P["server"].crea_router(self.sis, host_key=CHIAVE_HOST, admin_key=CHIAVE_ADMIN,
                                         base_url="https://bookinvip.com")
        self.risposte = []                        # (gesto, stato http, corpo ridotto)
        self.promesse = []                        # (gesto, cents) dette all'ospite in risposta

    @staticmethod
    def _esige(ok, cosa, stato, corpo):
        if not ok:
            raise PremessaMancante("%s: %r %r" % (cosa, stato, corpo))

    def g(self, metodo, percorso, corpo=None, intestazioni=None):
        return self.r.gestisci(metodo, percorso, {},
                               json.dumps(corpo) if corpo is not None else None,
                               intestazioni or {})

    def chiudi(self):
        import gc
        P = _P
        P["stripe"].ProviderStripe._fetch_reale = staticmethod(_rete_spenta)
        self.sis = self.r = None
        gc.collect()                  # su Windows un archivio ancora aperto non si cancella
        shutil.rmtree(self.cartella, ignore_errors=True)

    def _webhook(self, tipo, oggetto):
        self.rete.conta += 1
        corpo = json.dumps({"id": "evt_%d" % self.rete.conta, "type": tipo,
                            "data": {"object": oggetto}})
        firma = _P["firma_di_test"](corpo, SEGRETO_WEBHOOK, _ora())
        return self.r.gestisci("POST", "/api/payments/webhook", {}, corpo,
                               {"Stripe-Signature": firma})

    # ── prenotare e pagare: la premessa di ogni corsa ──
    def prenota_e_paga(self):
        _vai(ISTANTE_ZERO)
        s, q = self.g("POST", "/api/concierge/quote", {"alloggio_id": "casa-macchina",
                                                       "check_in": self.ci, "check_out": self.co,
                                                       "party": 2})
        self._esige(s == 200, "preventivo", s, q)
        s, b = self.g("POST", "/api/concierge/book", {"quote_token": q["quote_token"],
                                                      "email": "ospite@macchina.test"})
        self._esige(s == 201, "prenotazione", s, b)
        self.rif, self.vt = b["riferimento"], b["voucher_token"]
        self.idem = self.sis.firma.decodifica(self.vt).get("idem_key", "")
        self._esige("cs_" + self.rif in self.rete.sessioni, "la sessione di Stripe nella rete finta",
                    sorted(self.rete.sessioni), b)
        _vai(ISTANTE_ZERO + 30)
        self.rete.paga(self.rif)
        s, w = self._webhook("checkout.session.completed",
                             {"id": "cs_" + self.rif, "payment_intent": "pi_" + self.rif,
                              "metadata": {"riferimento": self.rif}})
        self._esige(s == 200, "webhook del pagamento", s, w)
        self._esige((self.sis.pagamenti_pendenti.info(self.rif) or {}).get("stato") == "pagato",
                    "prenotazione pagata", s, self.sis.pagamenti_pendenti.info(self.rif))
        _vai(ISTANTE_ZERO + 60)

    # ── l'orologio ──
    def istante(self, tempo):
        P = _P
        fuso = "Europe/Rome"
        if tempo == "subito":
            return ISTANTE_ZERO + 60
        if tempo == "dopo_48_ore":
            ts = self.sis.firma.decodifica(self.vt).get("prenotato_ts") or ISTANTE_ZERO
            return int(ts) + P["server"].SECONDI_RIPENSAMENTO + 60
        if tempo == "giorno_arrivo":
            return int(P["server"]._istante_checkin(self.ci, fuso))
        if tempo == "fine_giorno_arrivo":
            return int(self.sis.concierge._fine_giorno_arrivo("casa-macchina", self.ci)) + 1
        if tempo == "sblocco_garanzia":
            st = self.sis.garanzia.stato(self.rif) or {}
            ts = st.get("sblocco_auto_ts") or (P["server"]._istante_checkin(self.ci, fuso) + 86400)
            return int(ts) + 1
        if tempo == "dopo_partenza":
            return int(P["server"]._istante_checkin(self.co, fuso)) + 86400
        raise ValueError(tempo)

    def giro_orario(self):
        """COPIA di `_tick_garanzia` (fase83_server.avvia_server), nello stesso ordine; il
        confronto col vivo e' `test_A`. Piu' lo spazzino dei blocchi non pagati (`_tick_hold`)."""
        P, r, sis = _P, self.r, self.sis
        r._ritenta_bonifici_fermi()                  # R3 (21/10): Stripe non ritenta da solo
        r._incassa_blocchi()
        P["server"]._subentro_per_disaccordo(sis)
        # voce 177 (pacco 3, 27/10): lo sblocco delle garanzie scadute e i loro bonifici stanno
        # in un metodo del router, con `auto_rilascia` sotto `_BONIFICI_LOCK`: si chiama quello,
        # non una sua copia, cosi' la macchina misura il lucchetto vero.
        r._sblocca_garanzie_scadute()
        r._pulizia_uploads_se_ora()
        r._conservazione_se_ora()
        r._riscuoti_carta_se_ora()
        P["server"].sweep_hold_una_passata(sis, r)

    # ── i gesti ──
    def possibile(self, gesto):
        """La premessa VERA del gesto, letta adesso. Falsa = la sequenza non e' realizzabile."""
        if gesto == "pulsante":
            return self.riga_in_lista() is not None
        if gesto.startswith("arbitro_"):
            return (self.sis.garanzia.stato(self.rif) or {}).get("stato") == "contestato"
        if gesto == "chargeback":
            return (self.rete.incassato(self.rif) > self.rete.rimborsato(self.rif)
                    and not self.rete.contestato(self.rif))
        return True

    def fai(self, gesto):
        _vai(_ora() + 1)
        if gesto == "ospite_cancella":
            s, c = self.g("POST", "/api/concierge/cancella", {"voucher_token": self.vt})
            if s == 200 and c.get("stato") == "cancellata":
                self.promesse.append((gesto, int(c.get("rimborso_cents") or 0)))
        elif gesto == "host_cancella":
            s, c = self.g("POST", "/api/host/cancella", {"riferimento": self.rif}, self.th)
            if s == 200:
                self.promesse.append((gesto, int(c.get("rimborso_cliente_cents") or 0)))
        elif gesto == "admin_rimborso":
            s, c = self.g("POST", "/api/admin/rimborso",
                          {"alloggio_id": "casa-macchina", "check_in": self.ci,
                           "check_out": self.co, "idem_key": self.idem}, AK)
        elif gesto == "pulsante":
            s, c = self.g("POST", "/api/admin/rimborsa_dovuto", {"riferimento": self.rif}, AK)
        elif gesto == "tutto_ok":
            s, c = self.g("POST", "/api/garanzia/conferma", {"voucher_token": self.vt})
        elif gesto == "segnala":
            s, c = self.g("POST", "/api/garanzia/contesta", {"voucher_token": self.vt,
                                                             "motivo": "non corrisponde"})
        elif gesto.startswith("arbitro_"):
            s, c = self.g("POST", "/api/admin/controversia/risolvi",
                          {"riferimento": self.rif,
                           "percentuale_ospite": int(gesto.split("_", 1)[1])}, AK)
            if s == 200:
                self.promesse.append((gesto, int(c.get("rimborso_cliente_cents") or 0)))
        elif gesto == "chargeback":
            importo = self.rete.contesta(self.rif)
            s, c = self._webhook("charge.dispute.created",
                                 {"id": "dp_" + self.rif, "payment_intent": "pi_" + self.rif,
                                  "amount": importo, "currency": "eur", "reason": "fraudulent"})
        elif gesto == "dati_fiscali":
            s, c = self.g("POST", "/api/host/dati_fiscali",
                          {"codice_fiscale": "RSSMRA85T10A562S", "indirizzo_fiscale": "Via Roma 1",
                           "paese": "IT", "iban": "IT60X0542811101000000123456"}, self.th)
        else:
            raise ValueError(gesto)
        self.risposte.append((gesto, s, _riduci(c)))
        return s, c

    # ── i fatti, letti da chi li tiene ──
    def riga_in_lista(self):
        s, lista = self.g("GET", "/api/admin/rimborsi_dovuti", None, AK)
        for r in (lista or {}).get("rimborsi") or []:
            if r.get("riferimento") == self.rif:
                return r
        return None

    def fatti(self):
        sis, rif, rete = self.sis, self.rif, self.rete
        gz = sis.garanzia.stato(rif) or {}
        po = sis.payout.info(rif) or {}
        rimborsi = [m for m in sis.finanza.movimenti(rif) if (m.get("tipo") or "") == "rimborso"]
        riga = self.riga_in_lista()
        return {
            "ora": _ora(),
            "pendente": (sis.pagamenti_pendenti.info(rif) or {}).get("stato"),
            "pi": rete.stato_pi(rif),
            "incassato": rete.incassato(rif), "rimborsato": rete.rimborsato(rif),
            "contestato_carta": rete.contestato(rif), "bonificato": rete.bonificato(rif),
            "garanzia": gz.get("stato"), "garanzia_host": int(gz.get("host_riceve_cents") or 0),
            "garanzia_importo": int(gz.get("importo_host_cents") or 0),
            "payout": po.get("stato"), "payout_minori": int(po.get("minori") or 0),
            "promessa_giornale": int(rimborsi[-1]["importo_cents"]) if rimborsi else None,
            "riga": None if riga is None else {k: riga.get(k) for k in (
                "dovuto_cents", "bottone", "manca", "gia_rimborsato")},
            "promesse_risposte": list(self.promesse),
            "bonifico_automatico_atteso": self.collegato and (
                self.importo == "piccolo" or ("dati_fiscali", 200) in
                [(g, s) for g, s, _ in self.risposte]),
        }


class PremessaMancante(Exception):
    """La corsa non e' arrivata dove doveva (preparazione): non e' un esito, e' un NON ESEGUITO."""


def _rete_spenta(url, body, headers):
    raise ErroreStripe("rete_spenta", "nessuna corsa in atto")


def _riduci(c):
    if not isinstance(c, dict):
        return c
    return {k: c[k] for k in sorted(c) if k in (
        "stato", "errore", "motivo", "rimborso_cents", "rimborso_cliente_cents", "rimborso_stripe",
        "passi_falliti", "manca", "importo_cents", "va_all_host_cents", "ok", "sottocodice")}


# --------------------------------------------------------------------------------------
# i tre conti (e la fine corsa)
# --------------------------------------------------------------------------------------
def conti(f, fine=False):
    """-> lista di (conto, codice, spiegazione). Vuota = i conti tornano."""
    out = []
    uscito = f["rimborsato"] + f["bonificato"] + f["contestato_carta"]
    if uscito > f["incassato"]:
        # Una contestazione della carta dopo il bonifico all'host: Stripe prende da noi e la quota
        # dell'host va recuperata da lui (fase83 `_contestazione_carta` lo dichiara e lo grida).
        # Si scrive col suo nome, separato: e' un rischio del mestiere, non un conto sbagliato.
        solo_carta = f["contestato_carta"] and f["rimborsato"] + f["bonificato"] <= f["incassato"]
        out.append(("ESPOSIZIONE" if solo_carta else "PIATTAFORMA",
                    "contestazione_dopo_il_bonifico" if solo_carta else "uscito_oltre_incassato",
                    "usciti %d (rimborsi %d + bonifici %d + contestazione %d) > incassati %d" % (
                        uscito, f["rimborsato"], f["bonificato"], f["contestato_carta"],
                        f["incassato"])))
    gst = f["garanzia"]
    if gst in ("rilasciato", "risolto"):
        assegnato = f["garanzia_host"]
    elif gst in ("in_garanzia", "contestato") or (gst is None and f["pendente"] == "pagato"):
        assegnato = None
    else:
        assegnato = 0
    da_pagare = f["payout_minori"] if f["payout"] == "maturato" else 0
    # Due attese VOLUTE, che non sono soldi spariti (corretto l'11/10 dopo il primo giro: il
    # modello le contava come buchi, Hughes 2016 «gli errori sono spesso nel modello»):
    # · 'trattenuto' dopo una contestazione (della carta o dell'ospite): decide una persona;
    # · 'in_attesa' finche' il blocco sulla carta non e' incassato: i soldi non ci sono ancora.
    fermo = 0
    if f["payout"] == "trattenuto" and (f["contestato_carta"] or gst == "contestato"):
        fermo = f["payout_minori"]
    if f["payout"] == "in_attesa" and f["pi"] == "requires_capture":
        fermo = f["payout_minori"]
    if assegnato is None:
        if f["bonificato"]:
            out.append(("HOST", "bonifico_prima_della_decisione",
                        "garanzia '%s' (ancora da decidere) ma all'host sono gia' usciti %d" % (
                            gst, f["bonificato"])))
    elif f["bonificato"] + da_pagare + fermo != assegnato:
        out.append(("HOST", "assegnato_diverso_da_pagato",
                    "la garanzia '%s' assegna all'host %d; bonificati %d + ancora da pagare %d "
                    "+ fermi per una decisione %d (registro bonifici '%s', %d)" % (
                        gst, assegnato, f["bonificato"], da_pagare, fermo, f["payout"],
                        f["payout_minori"])))
    promessa = f["promessa_giornale"]
    if promessa is not None:
        riga = f["riga"]
        eseguito = f["rimborsato"] == promessa
        in_lista = f["rimborsato"] == 0 and riga is not None and riga["dovuto_cents"] == promessa
        if not (eseguito or in_lista):
            out.append(("OSPITE", "promessa_ne_eseguita_ne_in_lista",
                        "promessi %d (giornale); rimborsati su Stripe %d; in lista %r" % (
                            promessa, f["rimborsato"], riga)))
    for gesto, cifra in f["promesse_risposte"]:
        if cifra <= 0 or cifra == promessa:
            continue
        if promessa is None and f["incassato"] == 0 and f["pi"] in ("canceled", "requires_capture"):
            continue            # blocco sulla carta: l'autorizzazione torna tutta all'ospite
        out.append(("OSPITE", "promessa_in_risposta_diversa_dai_conti",
                    "la risposta di '%s' ha detto %d all'ospite; il giornale dice %r" % (
                        gesto, cifra, promessa)))
    if fine:
        if f["pi"] == "requires_capture":
            out.append(("FINE_CORSA", "blocco_lasciato_aperto",
                        "dopo la partenza il pagamento e' ancora solo autorizzato"))
        if f["pendente"] == "pagato" and gst == "in_garanzia":
            out.append(("FINE_CORSA", "garanzia_mai_sbloccata",
                        "dopo la partenza la garanzia e' ancora 'in_garanzia'"))
        if f["pendente"] == "pagato" and f["incassato"] == 0:
            out.append(("FINE_CORSA", "soggiorno_senza_incasso",
                        "la prenotazione e' rimasta pagata e viva ma Stripe non ha incassato "
                        "niente (pi '%s')" % f["pi"]))
        # La promessa all'host COLLEGATO e' il bonifico AUTOMATICO. L'attesa la decide il modello,
        # non il prodotto (un oracolo che chiede al codice se deve aspettare si sposta col guasto):
        # si aspetta solo un host sopra la soglia DAC7 senza dati fiscali, o una contestazione.
        if (f["bonifico_automatico_atteso"] and gst in ("rilasciato", "risolto")
                and f["garanzia_host"] > f["bonificato"] and not f["contestato_carta"]):
            out.append(("FINE_CORSA", "bonifico_automatico_mai_partito",
                        "host collegato a Stripe, garanzia '%s' gli assegna %d, dopo la partenza "
                        "bonificati %d (registro bonifici '%s')" % (
                            gst, f["garanzia_host"], f["bonificato"], f["payout"])))
    return out


# --------------------------------------------------------------------------------------
# le sequenze
# --------------------------------------------------------------------------------------
def realizzabile(sequenza):
    """Le premesse che si possono dire SENZA eseguire (le altre le dice `Corsa.possibile`)."""
    nomi = [g for _, g in sequenza]
    if len(set(nomi)) != len(nomi) or sum(n.startswith("arbitro_") for n in nomi) > 1:
        return False
    for i, n in enumerate(nomi):
        prima = nomi[:i]
        if n == "pulsante" and not any(p in CHI_SCRIVE_UN_DOVUTO for p in prima):
            return False
        if n.startswith("arbitro_") and not any(p in ("segnala", "chargeback") for p in prima):
            return False
    return True


def sequenze(k):
    """TUTTE le sequenze di esattamente k gesti, ogni gesto in un tempo, tempi non decrescenti."""
    for gesti in itertools.permutations(GESTI, k):
        for tempi in itertools.combinations_with_replacement(range(len(TEMPI)), k):
            seq = tuple((TEMPI[t], g) for t, g in zip(tempi, gesti))
            if realizzabile(seq):
                yield seq


def sequenze_casuali(n, seme, da=3, a=6):
    rnd = random.Random(seme)  # nosec B311 - sceglie sequenze di prova, non protegge niente
    viste, fatte, tentativi = set(), 0, 0
    while fatte < n and tentativi < n * 50:
        tentativi += 1
        k = rnd.randint(da, a)
        gesti = rnd.sample(GESTI, k)
        tempi = sorted(rnd.randrange(len(TEMPI)) for _ in range(k))
        seq = tuple((TEMPI[t], g) for t, g in zip(tempi, gesti))
        if seq in viste or not realizzabile(seq):
            continue
        viste.add(seq)
        fatte += 1
        yield seq


def corri(config, sequenza, radice, racconta=None):
    """Una corsa. -> {'esito': 'ok'|'rosso'|'non_realizzabile', 'rossi': [...], ...}"""
    c = Corsa(config, radice)
    try:
        c.prenota_e_paga()
        rossi, passi = [], []

        def guarda(dove, fine=False):
            f = c.fatti()
            for conto, codice, perche in conti(f, fine):
                rossi.append({"dove": dove, "conto": conto, "codice": codice, "perche": perche})
            passi.append((dove, f))
            if racconta:
                racconta(dove, f, c.risposte[-1] if c.risposte and dove.endswith(c.risposte[-1][0])
                         else None)

        guarda("dopo il pagamento")
        da_fare = list(sequenza)
        for tempo in TEMPI:
            if tempo != "subito":
                _vai(max(_ora() + 1, c.istante(tempo)))
                c.giro_orario()
                guarda("%s (giro orario)" % tempo)
            while da_fare and da_fare[0][0] == tempo:
                _, gesto = da_fare.pop(0)
                if not c.possibile(gesto):
                    return {"esito": "non_realizzabile", "gesto": gesto, "tempo": tempo}
                s, corpo = c.fai(gesto)
                if s >= 500:
                    rossi.append({"dove": "%s: %s" % (tempo, gesto), "conto": "RISPOSTA_5XX",
                                  "codice": "risposta_%d" % s, "perche": repr(_riduci(corpo))})
                guarda("%s: %s" % (tempo, gesto))
        _vai(_ora() + 3600)
        c.giro_orario()
        guarda("fine corsa", fine=True)
        return {"esito": "rosso" if rossi else "ok", "rossi": rossi, "risposte": c.risposte,
                "ultimi_fatti": passi[-1][1]}
    finally:
        c.chiudi()


# --------------------------------------------------------------------------------------
# D18 punto 1: la macchina misura se stessa PRIMA di misurare
# --------------------------------------------------------------------------------------
def copia_del_giro_vivo(sorgente=None):
    """I nomi chiamati da `_tick_garanzia` dentro `avvia_server`, in ordine di sorgente."""
    if sorgente is None:
        with open(os.path.join(QUI, "fase83_server.py"), encoding="utf-8") as fh:
            sorgente = fh.read()
    for nodo in ast.walk(ast.parse(sorgente)):
        if isinstance(nodo, ast.FunctionDef) and nodo.name == "_tick_garanzia":
            chiamate = sorted((n for n in ast.walk(nodo) if isinstance(n, ast.Call)),
                              key=lambda n: (n.lineno, n.col_offset))
            nomi = []
            for n in chiamate:
                nome = n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
                if nome in ("error", "warning", "info", "exception", "__import__"):
                    continue                         # il registro e l'import non muovono soldi
                nomi.append(nome)
            return tuple(nomi)
    return ()


def precondizioni(radice):
    """-> lista di problemi (vuota = la macchina e' in condizione di misurare)."""
    import datetime as _d
    import sqlite3
    P = _P
    problemi = []
    t = ISTANTE_ZERO + 12345
    _vai(t)
    con = sqlite3.connect(":memory:")
    try:
        # ⛔ La forma che il prodotto USA (`datetime('now')`, fase23): l'orologio riusato sposta
        # solo il 'now' in PRIMA posizione, e `strftime('%s','now')` gli sfugge (NON_GUARDA).
        visto_sqlite = con.execute("SELECT strftime('%s', datetime('now'))").fetchone()[0]
    finally:
        con.close()
    facce = {"time.time": int(time.time()), "date.today": _d.date.today().isoformat(),
             "datetime.now(UTC)": int(_d.datetime.now(_d.timezone.utc).timestamp()),
             "gmtime": time.strftime("%Y-%m-%d", time.gmtime()), "sqlite now": int(visto_sqlite)}
    attese = {"time.time": t, "date.today": time.strftime("%Y-%m-%d", time.localtime(t)),
              "datetime.now(UTC)": t, "gmtime": time.strftime("%Y-%m-%d", _P["orologio"]._vero_gmtime(t)),
              "sqlite now": t}
    for nome in facce:
        if facce[nome] != attese[nome]:
            problemi.append("l'orologio finto non comanda '%s': %r invece di %r" % (
                nome, facce[nome], attese[nome]))
    if copia_del_giro_vivo() != GIRO_ORARIO_COPIATO:
        problemi.append("il giro orario vero chiama %r, la copia %r" % (
            copia_del_giro_vivo(), GIRO_ORARIO_COPIATO))
    if problemi:
        return problemi
    for arrivo in ("vicino", "lontano"):
        try:
            esito = corri((arrivo, "flessibile", "si", "piccolo"), (), radice)
        except PremessaMancante as e:
            problemi.append("la corsa di prova '%s' non parte: %s" % (arrivo, e))
            continue
        f = esito["ultimi_fatti"]
        if not f["incassato"]:
            problemi.append("corsa '%s' senza gesti: Stripe non ha incassato niente (%r): la "
                            "macchina non vede i soldi entrare" % (arrivo, f))
        if not f["bonificato"]:
            problemi.append("corsa '%s' senza gesti, host collegato: nessun bonifico dopo la "
                            "partenza (%r): la macchina non vede i soldi uscire" % (arrivo, f))
        if esito["rossi"]:
            problemi.append("corsa '%s' senza gesti gia' rossa: %r" % (arrivo, esito["rossi"]))
    _vai(ISTANTE_ZERO)
    for arrivo, giorni in ARRIVI.items():
        import datetime as _dd
        z = time.gmtime(ISTANTE_ZERO)
        ci = (_dd.date(z.tm_year, z.tm_mon, z.tm_mday) + _dd.timedelta(days=giorni)).isoformat()
        if P["stripe"].blocco_sulla_carta(ci) != (arrivo == "lontano"):
            problemi.append("la configurazione '%s' non e' quella che dichiara: blocco sulla carta "
                            "= %r" % (arrivo, P["stripe"].blocco_sulla_carta(ci)))
    return problemi


# --------------------------------------------------------------------------------------
# D18 punto 2: si vede gridare (guasto VERO, in memoria) e tacere (stessa corsa, sana)
# --------------------------------------------------------------------------------------
def _guasti():
    """(nome, metodo di RouterHTTP, sostituto, configurazione, sequenza, conto che deve gridare).
    Ogni guasto e' un difetto VERO, gia' visto o plausibile, non un'astrazione: togliere un
    freno, saltare un passo di sicurezza, spegnere la lista, fermare l'incasso."""
    return [
        # «tutto ok» al giorno d'arrivo: dal 14/10 ((ad)) prima dell'arrivo la rotta lo
        # rifiuta, e con «subito» l'host non veniva piu' pagato e il guasto non si vedeva
        ("il freno «garanzia gia' divisa» tolto: l'admin rimborsa tutto a host gia' pagato",
         "_garanzia_gia_divisa", lambda self, idem: False,
         ("vicino", "flessibile", "si", "piccolo"),
         (("giorno_arrivo", "tutto_ok"), ("giorno_arrivo", "admin_rimborso")), "PIATTAFORMA"),
        ("la trattenuta del bonifico tolta: l'host resta 'maturato' su una prenotazione cancellata",
         "_payout_trattieni", lambda self, rif: True,
         ("vicino", "flessibile", "no", "piccolo"), (("subito", "ospite_cancella"),), "HOST"),
        ("la scheda del rimborso dovuto spenta: la promessa non arriva mai in lista",
         "_rimborso_dovuto_scheda", lambda self, rif: (None, True),
         ("vicino", "flessibile", "no", "piccolo"), (("subito", "ospite_cancella"),), "OSPITE"),
        ("il giro orario non incassa piu' i blocchi sulla carta",
         "_incassa_blocchi", lambda self, ora_ts=None: {},
         ("lontano", "flessibile", "no", "piccolo"), (), "FINE_CORSA"),
        ("il bonifico automatico non parte piu' (l'host collegato resta 'maturato')",
         "_trasferisci_all_host", lambda self, rif, importo_cents, penale=False: None,
         ("vicino", "flessibile", "si", "piccolo"), (), "FINE_CORSA"),
        ("il bonifico non si lega piu' all'addebito dell'ospite (esce dal saldo, che e' zero)",
         "_addebito_del_pagamento", lambda self, rec: "",
         ("vicino", "flessibile", "si", "piccolo"), (), "FINE_CORSA"),
    ]


def autoprova(radice):
    risultati = []
    cls = _P["server"].RouterHTTP
    for nome, metodo, finto, config, seq, conto_atteso in _guasti():
        vero = getattr(cls, metodo)
        sano = corri(config, seq, radice)
        setattr(cls, metodo, finto)
        try:
            rotto = corri(config, seq, radice)
        finally:
            setattr(cls, metodo, vero)
        conti_rossi = sorted({r["conto"] for r in rotto.get("rossi", [])})
        risultati.append({"guasto": nome, "config": config, "sequenza": seq,
                          "conto_atteso": conto_atteso,
                          "rosso_col_guasto": conto_atteso in conti_rossi,
                          "conti_rossi_col_guasto": conti_rossi,
                          "verde_senza_guasto": sano["esito"] == "ok",
                          "rossi_senza_guasto": sano.get("rossi", [])})
    return risultati


def _impronta_produzione():
    import hashlib
    h = {}
    for nome in ("fase83_server.py", "fase85_pagamenti_stripe.py", "fase160_escrow_garanzia.py",
                 "fase131_payout_dashboard.py", "fase101_stripe_connect.py"):
        with open(os.path.join(QUI, nome), "rb") as fh:
            h[nome] = hashlib.sha256(fh.read()).hexdigest()
    return h


# --------------------------------------------------------------------------------------
# l'esplorazione
# --------------------------------------------------------------------------------------
def esplora(configurazioni, k_max, casuali, seme, radice, avanzamento=None):
    difetti, esposizioni, contatori = {}, {}, {"corse": 0, "ok": 0, "rosse": 0,
                                               "non_realizzabili": 0, "premesse_mancanti": 0}
    inizio = time.perf_counter()       # `time.time` e' l'orologio finto: il cronometro no
    lotti = []
    for k in range(0, k_max + 1):
        lotti.append(("tutte le sequenze da %d gesti" % k, lambda k=k: sequenze(k)))
    if casuali:
        lotti.append(("%d sequenze casuali da 3 a 6 gesti, seme %d" % (casuali, seme),
                      lambda: sequenze_casuali(casuali, seme)))
    for config in configurazioni:
        for _, genera in lotti:
            for seq in genera():
                contatori["corse"] += 1
                try:
                    e = corri(config, seq, radice)
                except PremessaMancante as ex:
                    contatori["premesse_mancanti"] += 1
                    difetti.setdefault(("PREMESSA", str(ex)[:80]), {
                        "conto": "PREMESSA", "codice": "premessa_mancante", "perche": str(ex),
                        "config": config, "sequenza": seq})
                    continue
                if e["esito"] == "non_realizzabile":
                    contatori["non_realizzabili"] += 1
                    continue
                contatori["ok" if e["esito"] == "ok" else "rosse"] += 1
                for r in e.get("rossi", []):
                    chiave = (r["conto"], r["codice"], tuple(g for _, g in seq))
                    dove = esposizioni if r["conto"] == "ESPOSIZIONE" else difetti
                    if chiave not in dove:
                        dove[chiave] = dict(r, config=config, sequenza=seq,
                                            risposte=e.get("risposte"))
                if avanzamento and contatori["corse"] % 50 == 0:
                    avanzamento(contatori, time.perf_counter() - inizio, len(difetti))
    contatori["secondi"] = int(time.perf_counter() - inizio)
    return contatori, list(difetti.values()), list(esposizioni.values())


def _riassunto_difetti(difetti):
    """Un difetto per (conto, codice): la sequenza PIU' CORTA che lo mostra (le corte vengono
    prima nell'enumerazione), e quante sequenze diverse lo mostrano."""
    per = {}
    for d in difetti:
        chiave = (d["conto"], d["codice"])
        per.setdefault(chiave, []).append(d)
    out = []
    for _chiave, lista in sorted(per.items()):
        lista.sort(key=lambda d: len(d["sequenza"]))
        out.append(dict(lista[0], quante_sequenze=len(lista)))
    return out


def _stampa(titolo, righe):
    print(titolo)
    for r in righe:
        print("   · " + r)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if hasattr(sys.stdout, "reconfigure"):          # la console di Windows (cp1252) e i simboli
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    def opz(nome, predefinito=None):
        if nome in argv:
            i = argv.index(nome)
            return argv[i + 1] if i + 1 < len(argv) else predefinito
        return predefinito
    esito_file = opz("--esito") or os.path.join(tempfile.gettempdir(), "macchina_dei_soldi.json")
    _accendi(rompi_orologio="--rompi-orologio" in argv)
    radice = tempfile.mkdtemp(prefix="macchina_soldi_")
    risultato = {"comando": " ".join(["python", os.path.basename(__file__)] + argv),
                 "istante_zero": ISTANTE_ZERO, "non_guarda": list(NON_GUARDA)}
    codice = 2
    try:
        print("=" * 86)
        print("LA MACCHINA DELLE COMBINAZIONI DEI SOLDI — %s" % risultato["comando"])
        print("=" * 86)
        problemi = precondizioni(radice)
        if problemi:
            risultato.update(esito="NON ESEGUITO", problemi=problemi)
            _stampa("⛔ NON ESEGUITO: la macchina non e' in condizione di misurare (D18 punto 1). "
                    "Nessun numero di questo giro vale.", problemi)
            return 2
        print("✅ precondizioni: orologio, rete finta, giro orario e configurazioni verificati")
        if "--autoprova" in argv:
            prima = _impronta_produzione()
            ris = autoprova(radice)
            dopo = _impronta_produzione()
            risultato.update(autoprova=ris, file_di_produzione_intatti=(prima == dopo))
            for r in ris:
                print("  %s %s\n      col guasto: %s · senza: %s" % (
                    "OK   " if r["rosso_col_guasto"] and r["verde_senza_guasto"] else "FALLA",
                    r["guasto"], "ROSSO %s" % r["conti_rossi_col_guasto"]
                    if r["rosso_col_guasto"] else "NON VISTO (%s)" % r["conti_rossi_col_guasto"],
                    "verde" if r["verde_senza_guasto"] else "ROSSO %r" % r["rossi_senza_guasto"]))
            print("  file di produzione intatti (sha256 prima e dopo): %s" % (prima == dopo))
            buono = all(r["rosso_col_guasto"] and r["verde_senza_guasto"] for r in ris) \
                and prima == dopo
            risultato["esito"] = "OK" if buono else "AUTOPROVA FALLITA"
            codice = 0 if buono else 1
            return codice
        if "--una" in argv:
            i = argv.index("--una")
            config = tuple(argv[i + 1].split(","))
            seq = tuple(tuple(p.split(":", 1)) for p in argv[i + 2].split(",") if p) \
                if i + 2 < len(argv) and not argv[i + 2].startswith("--") else ()

            def racconta(dove, f, risposta):
                print("\n--- %s" % dove)
                if risposta:
                    print("    risposta: %r" % (risposta,))
                print("    fatti: %s" % json.dumps(f, sort_keys=True, default=str))
            e = corri(config, seq, radice, racconta=racconta)
            risultato.update(una=e)
            print("\nESITO: %s" % e["esito"])
            for r in e.get("rossi", []):
                print("  ROSSO %s/%s @ %s: %s" % (r["conto"], r["codice"], r["dove"], r["perche"]))
            codice = 0 if e["esito"] == "ok" else 1
            return codice
        giro = opz("--giro", "suite")
        if giro == "suite":
            configurazioni, k_max, casuali = CONFIG_SUITE, 1, 0
        elif giro == "corto":
            configurazioni, k_max, casuali = CONFIGURAZIONI, 1, 0
        elif giro == "lungo":
            configurazioni, k_max = CONFIGURAZIONI, int(opz("--k", "2"))
            casuali = int(opz("--casuali", "2000"))
        else:
            print("giro sconosciuto: %r" % giro)
            return 2
        # `--parte i/n`: la stessa esplorazione divisa fra n processi (configurazioni a pettine).
        # Misurato l'11/10: un processo solo, dopo pochi secondi, va da 3 a 6 volte piu' piano
        # (anche il calcolo puro della password): il processore lo sposta sui nuclei lenti.
        parte = opz("--parte")
        if parte:
            i, n = (int(x) for x in parte.split("/"))
            configurazioni = tuple(c for j, c in enumerate(configurazioni) if j % n == i - 1)
            risultato["parte"] = parte
        seme = int(opz("--seme", "20261011"))

        def avanzamento(c, sec, nd):
            print("   ... %d corse (%d ok, %d rosse, %d non realizzabili) in %ds, difetti "
                  "distinti %d" % (c["corse"], c["ok"], c["rosse"], c["non_realizzabili"],
                                   int(sec), nd), flush=True)
        contatori, difetti, esposizioni = esplora(configurazioni, k_max, casuali, seme, radice,
                                                  avanzamento)
        riassunto = _riassunto_difetti(difetti)
        risultato.update(giro=giro, configurazioni=len(configurazioni), k_max=k_max,
                         casuali=casuali, seme=seme, contatori=contatori,
                         difetti=riassunto, difetti_tutti=difetti, esposizioni=esposizioni)
        print("\nCORSE: %(corse)d · ok %(ok)d · rosse %(rosse)d · non realizzabili "
              "%(non_realizzabili)d · premesse mancanti %(premesse_mancanti)d · %(secondi)ds"
              % contatori)
        print("DENOMINATORE: %d configurazioni x tutte le sequenze fino a %d gesti%s" % (
            len(configurazioni), k_max,
            (" + %d casuali (seme %d)" % (casuali, seme)) if casuali else ""))
        if riassunto:
            print("\n⛔ DIFETTI (%d distinti; per ognuno la sequenza piu' corta):" % len(riassunto))
            for d in riassunto:
                print("  [%s/%s] %s\n      config %s · sequenza %s · %d sequenze lo mostrano" % (
                    d["conto"], d["codice"], d["perche"], ",".join(d["config"]),
                    " -> ".join("%s:%s" % p for p in d["sequenza"]) or "(nessun gesto)",
                    d["quante_sequenze"]))
        else:
            print("\n✅ nessun conto rotto nelle corse eseguite")
        if esposizioni:
            print("\n⚠️  ESPOSIZIONI DICHIARATE (non conti sbagliati: rischi che il prodotto grida "
                  "da se'): %d" % len(esposizioni))
            for d in esposizioni[:5]:
                print("   · %s · config %s · %s" % (d["perche"], ",".join(d["config"]),
                                                     " -> ".join("%s:%s" % p for p in d["sequenza"])))
        risultato["esito"] = "DIFETTI" if riassunto or contatori["premesse_mancanti"] else "OK"
        codice = 1 if risultato["esito"] != "OK" else 0
        return codice
    finally:
        _stampa("\n⚠️  COSA QUESTA MACCHINA NON GUARDA (D18 punto 3):", NON_GUARDA)
        risultato["codice_uscita"] = codice
        with open(esito_file, "w", encoding="utf-8") as fh:
            json.dump(risultato, fh, ensure_ascii=False, indent=1, default=str)
        print("esito scritto in %s" % esito_file)
        shutil.rmtree(radice, ignore_errors=True)
        print("CODICE_USCITA=%d" % codice, flush=True)


# --------------------------------------------------------------------------------------
# la guardia nella suite (D18 punto 4): la macchina gira in un processo SUO, perche' sposta
# l'orologio di tutto il processo e la suite non deve accorgersene
# --------------------------------------------------------------------------------------
class TestLaMacchinaDeiSoldi(unittest.TestCase):

    def _lancia(self, *argomenti, tetto=900, parti=1):
        """Lancia la macchina in `parti` processi paralleli (`--parte i/n`) e unisce gli esiti."""
        cartella = tempfile.mkdtemp()
        ambiente = dict(os.environ, PYTHONIOENCODING="utf-8")
        processi = []
        for i in range(1, parti + 1):
            esito = os.path.join(cartella, "esito_%d.json" % i)
            extra = ["--parte", "%d/%d" % (i, parti)] if parti > 1 else []
            # argomenti fissi di questo file, nessun ingresso esterno
            processi.append((esito, subprocess.Popen(  # nosec B603  # noqa: S603
                [sys.executable, os.path.abspath(__file__)] + list(argomenti) + extra
                + ["--esito", esito], cwd=QUI, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", env=ambiente)))
        uscite, testi, dati = [], [], []
        for esito, p in processi:
            fuori, errori = p.communicate(timeout=tetto)
            uscite.append(p.returncode)
            testi.append(fuori + errori)
            try:
                with open(esito, encoding="utf-8") as fh:
                    dati.append(json.load(fh))
            except (OSError, ValueError):
                dati.append(None)
        shutil.rmtree(cartella, ignore_errors=True)
        return uscite, "\n".join(testi), dati

    def test_A_la_copia_del_giro_orario_e_quella_che_gira_in_produzione(self):
        vivo = copia_del_giro_vivo()
        self.assertTrue(vivo, "PREMESSA NON VALIDA: `_tick_garanzia` non si trova piu' in "
                              "fase83_server.py: la macchina non sa piu' cosa copiare")
        self.assertEqual(vivo, GIRO_ORARIO_COPIATO,
                         "IL GIRO ORARIO VERO E' CAMBIATO: ora chiama %r. La copia della macchina "
                         "(`Corsa.giro_orario` e `GIRO_ORARIO_COPIATO`) va riallineata, o i suoi "
                         "conti parlano di un server che non esiste piu'." % (vivo,))

    def test_A_la_guardia_della_copia_vede_un_giro_cambiato(self):
        """Nelle DUE direzioni: un giro vero con un passo in meno deve dare un elenco diverso."""
        with open(os.path.join(QUI, "fase83_server.py"), encoding="utf-8") as fh:
            sorgente = fh.read()
        rotto = sorgente.replace("router._incassa_blocchi()", "pass", 1)
        self.assertNotEqual(sorgente, rotto, "PREMESSA NON VALIDA: il passo da togliere non c'e'")
        self.assertNotEqual(copia_del_giro_vivo(rotto), GIRO_ORARIO_COPIATO)

    def test_B_si_ferma_se_l_orologio_non_obbedisce(self):
        (uscita,), testo, (dati,) = self._lancia("--giro", "suite", "--rompi-orologio", tetto=300)
        self.assertEqual(uscita, 2, "con l'orologio rotto la macchina NON doveva misurare: "
                                    "uscita %r\n%s" % (uscita, testo[-3000:]))
        self.assertIn("NON ESEGUITO", testo)
        self.assertTrue(dati and dati.get("esito") == "NON ESEGUITO" and dati.get("problemi"),
                        "il NON ESEGUITO deve dire il perche': %r" % (dati,))

    def test_C_l_autoprova_vede_i_guasti_veri_e_tace_a_macchina_sana(self):
        (uscita,), testo, (dati,) = self._lancia("--autoprova", tetto=600)
        self.assertIsNotNone(dati, "nessun esito scritto:\n%s" % testo[-3000:])
        ris = dati.get("autoprova") or []
        self.assertEqual(len(ris), len(_guasti()), "PREMESSA NON VALIDA: i guasti dell'autoprova "
                                                   "sono %r" % (ris,))
        self.assertEqual({r["conto_atteso"] for r in ris},
                         {"PIATTAFORMA", "HOST", "OSPITE", "FINE_CORSA"},
                         "ogni conto deve essere visto gridare almeno una volta")
        for r in ris:
            self.assertTrue(r["rosso_col_guasto"],
                            "IL CONTO %s NON VEDE IL GUASTO «%s»: rossi %r" % (
                                r["conto_atteso"], r["guasto"], r["conti_rossi_col_guasto"]))
            self.assertTrue(r["verde_senza_guasto"],
                            "LA STESSA CORSA SANA E' ROSSA (falso allarme, ferrea 10) «%s»: %r" % (
                                r["guasto"], r["rossi_senza_guasto"]))
        self.assertTrue(dati.get("file_di_produzione_intatti"),
                        "l'autoprova ha cambiato un file di produzione: i guasti vanno SOLO in "
                        "memoria")
        self.assertEqual(uscita, 0, testo[-3000:])

    def test_D_le_combinazioni_corte_non_rompono_i_conti(self):
        # due processi: uno solo, dopo pochi secondi, rallenta da 3 a 6 volte (misurato l'11/10)
        uscite, testo, dati = self._lancia("--giro", "suite", tetto=1200, parti=2)
        self.assertTrue(all(dati), "un esito non e' stato scritto:\n%s" % testo[-3000:])
        for d in dati:
            self.assertNotEqual(d.get("esito"), "NON ESEGUITO", d.get("problemi"))
        eseguite = sum((d.get("contatori") or {}).get("ok", 0)
                       + (d.get("contatori") or {}).get("rosse", 0) for d in dati)
        self.assertGreater(eseguite, 150, "PREMESSA NON VALIDA: troppe poche corse eseguite: %r"
                           % ([d.get("contatori") for d in dati],))
        difetti = [x for d in dati for x in (d.get("difetti") or [])]
        self.assertEqual(difetti, [], "I CONTI DEI SOLDI SI ROMPONO in %d modi:\n%s" % (
            len(difetti), "\n".join("[%s/%s] %s | %s | %s" % (
                d["conto"], d["codice"], d["perche"], d["config"], d["sequenza"])
                for d in difetti)))
        self.assertEqual(uscite, [0, 0], testo[-3000:])

    # ── GUARDIE DI DIFETTI VIVI TROVATI DA QUESTA MACCHINA (S18, 15-16/10). D20: scritte e
    #    viste ROSSE prima di ogni riparazione. Rifanno con `--una` la corsa che ha mostrato il
    #    difetto: codice vero, rete finta. Le PREMESSE vengono prima (D19): se la corsa non e'
    #    piu' quella descritta, la guardia lo dice invece di passare a vuoto. ──
    def test_S18_con_la_contestazione_della_banca_il_pulsante_e_spento_e_non_da_5xx(self):
        """S18, causa 1 (si chiude con S4/(am)). L'host cancella: all'ospite sono dovuti 200 EUR
        e la riga compare nella lista col bottone. Poi la banca dell'ospite contesta TUTTO
        l'incasso. Stripe non rimborsa un pagamento contestato (docs.stripe.com/error-codes,
        letta il 15/10: `charge_disputed`, `refund_disputed_payment`): il bottone deve essere
        SPENTO e il pulsante deve dire il motivo (4xx), mai 5xx. Oggi la scheda non guarda la
        contestazione (`_rimborso_dovuto_scheda`, fase83_server.py:5369-5426): bottone acceso,
        e il pulsante risponde 502 (fase83_server.py:5606). La regola la scrive gia' il codice
        (fase83_server.py:5293-5295 e 5424-5426): la lista non deve mostrare «un bottone che il
        pulsante rifiuta»."""
        (uscita,), testo, (dati,) = self._lancia(
            "--una", "vicino,flessibile,si,piccolo",
            "giorno_arrivo:host_cancella,fine_giorno_arrivo:chargeback,dopo_partenza:pulsante",
            tetto=300)
        self.assertNotEqual(uscita, 2, "NON ESEGUITO:\n%s" % testo[-3000:])
        una = (dati or {}).get("una") or {}
        self.assertIn(una.get("esito"), ("ok", "rosso"),
                      "PREMESSA NON VALIDA: la corsa non e' stata fatta tutta (%r). Se la riga "
                      "sparisce con la contestazione, la regola e' cambiata: questa guardia va "
                      "riscritta con la decisione del fondatore.\n%s" % (una, testo[-3000:]))
        risposte = {g: s for g, s, _ in una.get("risposte") or []}
        f = una.get("ultimi_fatti") or {}
        self.assertEqual((risposte.get("host_cancella"), risposte.get("chargeback")), (200, 200),
                         "PREMESSA NON VALIDA: %r" % (una.get("risposte"),))
        self.assertTrue(f.get("incassato", 0) > 0
                        and f.get("contestato_carta") == f.get("incassato"),
                        "PREMESSA NON VALIDA: la banca non contesta tutto l'incassato: %r" % (f,))
        self.assertTrue(400 <= risposte.get("pulsante", 0) < 500,
                        "CON LA CONTESTAZIONE APERTA IL PULSANTE HA RISPOSTO %r: deve dire il "
                        "motivo (4xx), mai 5xx e mai 200. Tutte le risposte: %r"
                        % (risposte.get("pulsante"), una.get("risposte")))
        self.assertIs((f.get("riga") or {}).get("bottone"), False,
                      "CON LA CONTESTAZIONE APERTA IL BOTTONE E' ACCESO: %r" % (f.get("riga"),))
        # ⛔ E SPENTO PER IL MOTIVO GIUSTO (aggiunto il 16/10, alla riparazione di S4): con la
        # rete finta senza `disputed` il prodotto rispondeva «verifica_contestazione», cioe'
        # «non lo so», e questa guardia passava lo stesso -- un verde che non prova niente.
        corpo = {g: c for g, _, c in una.get("risposte") or []}.get("pulsante") or {}
        self.assertEqual(((f.get("riga") or {}).get("manca"), corpo.get("manca")),
                         (["contestazione_banca"], ["contestazione_banca"]),
                         "IL BOTTONE E' SPENTO MA NON (SOLO) PER LA CONTESTAZIONE: riga %r, "
                         "pulsante %r" % (f.get("riga"), corpo))

    def test_S18_aq_il_rimborso_dell_admin_su_un_blocco_gia_tolto_non_scrive_un_debito(self):
        """(aq), trovato in S18 il 15/10. Prenotazione lontana: sulla carta c'e' solo un BLOCCO,
        nessun soldo entrato. L'host cancella: il blocco si toglie e non resta niente da
        restituire (giusto: nessuna riga). Poi l'admin preme «rimborso»: la risposta dice
        «nessun incasso da restituire», ma nel giornale finisce un «rimborso» pari al TOTALE e
        nella lista compare una riga col bottone: un debito verso chi non ha pagato niente.
        Dove: fase83_server.py:5196-5214 -- il giornale si scrive con `tot > 0 and not
        _senza_incasso`; con lo stato `cancellata_host` `_era_pagato` e' falso, quindi anche
        `_senza_incasso`. ⚠️ I conti della macchina NON lo vedono: questa stessa corsa da' «ok»
        (misurato il 16/10); lo mostrava solo il 502 del pulsante premuto dopo. Per questo la
        guardia legge il giornale e la lista, non l'esito della corsa."""
        (uscita,), testo, (dati,) = self._lancia(
            "--una", "lontano,flessibile,si,piccolo", "subito:host_cancella,subito:admin_rimborso",
            tetto=300)
        self.assertNotEqual(uscita, 2, "NON ESEGUITO:\n%s" % testo[-3000:])
        una = (dati or {}).get("una") or {}
        self.assertIn(una.get("esito"), ("ok", "rosso"),
                      "PREMESSA NON VALIDA: la corsa non e' stata fatta tutta: %r\n%s"
                      % (una, testo[-3000:]))
        risposte = {g: s for g, s, _ in una.get("risposte") or []}
        f = una.get("ultimi_fatti") or {}
        self.assertEqual(risposte.get("host_cancella"), 200,
                         "PREMESSA NON VALIDA: %r" % (una.get("risposte"),))
        self.assertTrue(risposte.get("admin_rimborso", 500) < 500,
                        "PREMESSA NON VALIDA (o un altro difetto): il rimborso dell'admin ha "
                        "risposto %r" % (una.get("risposte"),))
        self.assertEqual((f.get("incassato"), f.get("pi")), (0, "canceled"),
                         "PREMESSA NON VALIDA: il blocco non e' stato tolto, o qualcosa e' stato "
                         "incassato: %r" % (f,))
        self.assertEqual((f.get("promessa_giornale"), f.get("riga")), (None, None),
                         "UN DEBITO FINTO: l'ospite non ha pagato niente (incassato 0, blocco "
                         "annullato), ma il giornale dice rimborso %r e la lista mostra %r"
                         % (f.get("promessa_giornale"), f.get("riga")))


if __name__ == "__main__":
    sys.exit(main())
