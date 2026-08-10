"""
CORE_AUTO - BANCO DEGLI INCROCI DEL LATO OSPITE.

Perche' esiste: i pezzi del percorso ospite sono provati uno per uno; le GIUNZIONI
quasi mai. Il buco del CIN (2026-08-09) era esattamente di quella forma -- due meta'
provate, la giunzione no. Qui si cammina ogni combinazione fino ai SOLDI.

LE COMBINAZIONI SONO 24, NON 48, e i due tagli sono MISURATI (non stimati):
  · i modi di pagare sono DUE, non tre: il "diviso fra amici" e' solo il CALCOLATORE
    "EUR X a testa" -- il pagamento reale-diviso e' PARCHEGGIATO dal fondatore
    (REGISTRO_INGEGNERIA.md righe 35 e 208); fase65 e' un registro puro che delega
    l'addebito a fase35, e fase35 NON e' raggiungibile dalla produzione
    (collaudi/raggiungibilita.py).
  · "in struttura" + "su richiesta" e' IMPOSSIBILE per costruzione: con su_richiesta
    fase83_server._book esce alla riga 4666, PRIMA di _forse_paga_struttura (4670);
    e nemmeno l'approvazione dell'host la richiama (5168 chiama solo
    _finalizza_prenotazione, con un link a PREZZO PIENO).
  2 modi di pagare x 2 modi di prenotare x 4 politiche x 2 finestre - 8 impossibili = 24.

L'ORACOLO E' INDIPENDENTE (collaudo #5): le percentuali attese sono scritte A MANO qui
sotto dalla definizione delle politiche, NON chiamando fase111. Un banco che chiede al
codice cosa deve aspettarsi non prova niente.

OSSERVABILE FORTE (mai lo stato interno): quanto e' stato incassato, quanto torna
all'ospite, quanto resta trattenuto, e se il giornale dei conti lo sa.

CIO' CHE QUESTO BANCO NON GUARDA (dichiarato, D18 punto 3):
  · la tassa di soggiorno e' messa a ZERO negli annunci, per tenere pulita l'aritmetica
    del rimborso: la sua strada (rimborsata SEMPRE per intero) non e' provata qui;
  · una sola valuta (EUR) e una sola lingua;
  · la cancellazione da parte dell'HOST e il no-show: qui cancella sempre l'OSPITE;
  · l'arrivo e' sempre a +8 giorni, scelto perche' separa tre scaglioni diversi
    (flessibile 100% / moderata 100% / rigida 50% / non rimborsabile 0%): altre
    distanze non sono state camminate.

USO:
    python collaudi/incroci_ospite.py --solo 2     # prova in piccolo, PRIMA
    python collaudi/incroci_ospite.py              # tutte e 24
Il codice d'uscita e' scritto in fondo all'output (S8: senza quella riga il file non
e' un esito e non si commenta).
"""
import datetime
import json
import os
import shutil
import sys
import tempfile
import time

# La vetrina "paga in struttura" e' GATED da questo flag. Va acceso PRIMA di comporre il
# sistema. MISURATO il 2026-08-09: in produzione vale gia' "1" (docker exec casavip_app
# env), mentre tre commenti del sorgente lo danno per spento -- vedi RIPRENDI_QUI.md.
os.environ["PAGA_STRUTTURA_ATTIVO"] = "1"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fase85_pagamenti_stripe as _stripe                             # noqa: E402
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema      # noqa: E402
from fase83_server import crea_router                                 # noqa: E402
from fase87_stripe_webhook import firma_di_test                       # noqa: E402
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256  # noqa: E402

WHSEC = "whsec_incroci"
PREFISSO = "incroci_ospite_"

# ── L'ORACOLO, scritto a mano dalle definizioni di fase111 (NON chiamando fase111) ──
# Arrivo a +8 giorni. flessibile ((1,100%),(0,50%)) -> 100. moderata ((5,100%),(1,50%),
# (0,0)) -> 100. rigida ((30,100%),(7,50%),(0,0)) -> 8>=7 -> 50. non_rimborsabile -> 0.
GIORNI_ARRIVO = 8
ATTESO_BPS = {"flessibile": 10000, "moderata": 10000, "rigida": 5000,
              "non_rimborsabile": 0}


def combinazioni():
    """Le 24 vive. Le 8 di 'in struttura + su richiesta' sono tolte perche' il codice
    non puo' produrle, non perche' sia scomodo provarle."""
    out = []
    for pagare in ("online", "in_struttura"):
        for prenotare in ("immediata", "su_richiesta"):
            if pagare == "in_struttura" and prenotare == "su_richiesta":
                continue
            for politica in ("flessibile", "moderata", "rigida", "non_rimborsabile"):
                for dentro in (True, False):
                    out.append((pagare, prenotare, politica, dentro))
    return out


def _fetch_finto(url, body, headers):
    import secrets
    return {"url": "https://checkout.stripe.test/" + secrets.token_hex(6),
            "id": "cs_test_" + secrets.token_hex(6)}


class Banco:
    """Un sistema composto da zero, isolato su disco, per UNA combinazione."""

    def __init__(self, radice, politica, modalita):
        self.dir = tempfile.mkdtemp(prefix=PREFISSO, dir=radice)
        d = self.dir
        self.sys = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_accettazioni=f"{d}/acc.db",
            db_pendenti=f"{d}/p.db", db_payout=f"{d}/pay.db", db_garanzia=f"{d}/g.db",
            db_tassa_comunale=f"{d}/t.db", db_split=f"{d}/s.db",
            commissione_bps=1000, psp_bps=300,
            stripe_secret_key="sk_test_incroci", stripe_webhook_secret=WHSEC,
            stripe_success_url="https://bookinvip.com/grazie.html",
            stripe_cancel_url="https://bookinvip.com/annullato.html"))
        self.r = crea_router(self.sys, host_key="hk", base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@incroci.it", "password": "password1",
                       "accetta_termini": True, "accetta_clausole": True,
                       "accetta_privacy": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        if s != 201:
            raise RuntimeError(f"registrazione host: {s} {c}")
        self.hid, self.tok = c["host_id"], c["token"]
        oggi = datetime.date.today()
        self.ci = (oggi + datetime.timedelta(days=GIORNI_ARRIVO)).isoformat()
        self.co = (oggi + datetime.timedelta(days=GIORNI_ARRIVO + 2)).isoformat()
        s, c = self.g("POST", "/api/host/pubblica",
                      {"slug": "casa-inc", "titolo": "Casa Incroci", "citta": "Roma",
                       "prezzo_notte_cents": 10000, "capacita": 2,
                       "tassa_pp_notte_cents": 0,
                       "politica_cancellazione": politica,
                       "modalita_prenotazione": modalita}, {"X-Host-Token": self.tok})
        if s != 201:
            raise RuntimeError(f"pubblica: {s} {c}")
        s, c = self.g("POST", "/api/host/disponibilita_range",
                      {"alloggio_id": "casa-inc", "da": oggi.isoformat(),
                       "a": (oggi + datetime.timedelta(days=60)).isoformat(),
                       "unita_totali": 1, "prezzo_netto_cents": 10000},
                      {"X-Host-Token": self.tok})
        if s != 200:
            raise RuntimeError(f"disponibilita: {s} {c}")

    def g(self, metodo, path, body=None, headers=None, query=None):
        return self.r.gestisci(metodo, path, query or {},
                               json.dumps(body) if body is not None else None,
                               headers or {})

    def paga(self, rif):
        """Il pagamento vero: il webhook firmato di Stripe. Non passa da self.g perche'
        il corpo dev'essere la STRINGA su cui e' calcolata la firma, non un dict."""
        payload = json.dumps({"type": "checkout.session.completed",
                              "data": {"object": {"metadata": {"riferimento": rif}}}})
        firma = firma_di_test(payload, WHSEC, int(time.time()))
        return self.r.gestisci("POST", "/api/payments/webhook", {}, payload,
                               {"Stripe-Signature": firma})

    def invecchia_voucher(self, token, secondi):
        """Sposta indietro l'istante della prenotazione RIFIRMANDO il voucher con la
        chiave del sistema. Si fa cosi' e non spostando l'orologio globale: patchare
        time.time() cambierebbe anche sqlite, i log e le scadenze, e un banco che
        muove l'orologio a tutti misura un'altra macchina (sbaglio S3)."""
        v = self.sys.firma.decodifica(token)
        if not isinstance(v, dict):
            return None
        ts = v.get("prenotato_ts")
        if not (isinstance(ts, int) and not isinstance(ts, bool) and ts > 0):
            return None                      # niente istante: non e' invecchiabile
        nuovo = dict(v)
        nuovo["prenotato_ts"] = ts - secondi
        return self.sys.firma.codifica(nuovo)

    def chiudi(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def cammina(radice, pagare, prenotare, politica, dentro):
    """Una combinazione, dal preventivo al rimborso. Ritorna la riga di esito."""
    riga = {"pagare": pagare, "prenotare": prenotare, "politica": politica,
            "dentro": dentro, "esito": "", "note": "", "incassato": 0,
            "rimborso": 0, "trattenuto": 0, "credito": 0, "atteso": 0,
            "giornale": False}
    b = None
    try:
        b = Banco(radice, politica, prenotare)
        s, q = b.g("POST", "/api/concierge/quote",
                   {"alloggio_id": "casa-inc", "check_in": b.ci, "check_out": b.co,
                    "party": 2})
        if s != 200:
            riga["esito"] = "NON ESEGUITO"
            riga["note"] = f"preventivo {s}"
            return riga
        corpo = {"quote_token": q["quote_token"], "email": "ospite@incroci.it"}
        if pagare == "in_struttura":
            corpo["modo_pagamento"] = "in_struttura"
        s, pren = b.g("POST", "/api/concierge/book", corpo)
        if s != 201:
            riga["esito"] = "NON ESEGUITO"
            riga["note"] = f"prenotazione {s}"
            return riga
        rif = pren.get("riferimento", "")

        if prenotare == "su_richiesta":
            if pren.get("stato") != "in_attesa_host":
                riga["esito"] = "NON ESEGUITO"
                riga["note"] = f"atteso in_attesa_host, ottenuto {pren.get('stato')!r}"
                return riga
            s, ap = b.g("POST", "/api/host/richieste/approva", {"riferimento": rif},
                        {"X-Host-Token": b.tok})
            if s != 200:
                riga["esito"] = "NON ESEGUITO"
                riga["note"] = f"approvazione host {s}"
                return riga
            pren = ap.get("prenotazione", {}) or {}

        # PREMESSA, non risultato: se il ramo "in struttura" e' caduto nel fail-safe
        # ONLINE, questa riga NON e' verde -- e' NON ESEGUITA (sbaglio S7: un controllo
        # che da' OK quando la premessa manca).
        if pagare == "in_struttura" and pren.get("modo_pagamento") != "in_struttura":
            riga["esito"] = "NON ESEGUITO"
            riga["note"] = "il ramo in_struttura e' caduto nel fail-safe ONLINE"
            return riga

        if pagare == "in_struttura":
            incassato = int(pren.get("anticipo_online_cents", 0) or 0)
        else:
            incassato = int(pren.get("prezzo_guest_cents", 0) or 0)
        riga["incassato"] = incassato
        # SBAGLIO S1 ("ho confrontato due cose vuote e ho scritto UGUALI"): con
        # incassato=0 ogni controllo qui sotto passerebbe da solo -- 0 reso su 0 atteso,
        # conservazione 0+0==0 -- e la riga sarebbe VERDE senza aver misurato niente.
        # Il vuoto non e' un valore: e' assenza di misura.
        if incassato <= 0:
            riga["esito"] = "NON ESEGUITO"
            riga["note"] = ("nessun importo incassato: non c'e' niente da rimborsare "
                            "e nessun controllo sarebbe significativo")
            return riga

        tok = pren.get("voucher_token", "")
        if not tok:
            riga["esito"] = "NON ESEGUITO"
            riga["note"] = "nessun voucher_token dopo la prenotazione"
            return riga

        s, _ = b.paga(rif)                                    # l'ospite paga davvero
        if s != 200:
            riga["esito"] = "NON ESEGUITO"
            riga["note"] = f"webhook pagamento {s}"
            return riga

        if not dentro:                                        # fuori dalle 48 ore
            invecchiato = b.invecchia_voucher(tok, 3 * 24 * 3600)
            if invecchiato is None:
                riga["esito"] = "NON ESEGUITO"
                riga["note"] = "voucher senza prenotato_ts: finestra non spostabile"
                return riga
            tok = invecchiato

        s, canc = b.g("POST", "/api/concierge/cancella", {"voucher_token": tok})
        if s != 200:
            riga["esito"] = "NON ESEGUITO"
            riga["note"] = f"cancellazione {s} {canc}"
            return riga
        riga["rimborso"] = int(canc.get("rimborso_cents", 0) or 0)
        riga["trattenuto"] = int(canc.get("trattenuto_cents", 0) or 0)
        riga["credito"] = int(canc.get("credito_viaggio_cents", 0) or 0)
        try:
            mov = b.sys.finanza.movimenti(str(rif))
            riga["giornale"] = any(m.get("tipo") == "rimborso" for m in mov)
        except Exception:
            riga["giornale"] = False

        # ── L'ORACOLO INDIPENDENTE ────────────────────────────────────────────────
        # in struttura: la cancellazione FORZA non_rimborsabile (fase83:6026) e la base
        # e' l'ANTICIPO, mai il prezzo pieno (rimborsare il pieno sarebbe regalare soldi
        # mai incassati). Il ripensamento vince su qualunque politica (fase83:6030).
        if dentro:
            bps = 10000
        elif pagare == "in_struttura":
            bps = 0
        else:
            bps = ATTESO_BPS[politica]
        atteso = incassato * bps // 10000
        riga["atteso"] = atteso

        guasti = []
        if riga["rimborso"] != atteso:
            guasti.append(f"rimborso {riga['rimborso']} invece di {atteso}")
        if riga["rimborso"] + riga["trattenuto"] != incassato:
            guasti.append(f"conservazione rotta: {riga['rimborso']}+{riga['trattenuto']}"
                          f" != {incassato}")
        if riga["rimborso"] > incassato:
            guasti.append(f"reso {riga['rimborso']} su {incassato} incassati")
        if riga["rimborso"] > 0 and not riga["giornale"]:
            guasti.append("rimborso promesso ma il giornale non lo sa")
        riga["esito"] = "ROSSO" if guasti else "OK"
        riga["note"] = " | ".join(guasti)
        return riga
    except Exception as exc:                                  # pragma: no cover
        riga["esito"] = "NON ESEGUITO"
        riga["note"] = f"eccezione {type(exc).__name__}: {exc}"
        return riga
    finally:
        if b is not None:
            b.chiudi()


def main(argomenti):
    solo = None
    for a in argomenti:
        if a.startswith("--solo"):
            solo = int(a.split("=", 1)[1]) if "=" in a else None
    if solo is None and "--solo" in argomenti:
        i = argomenti.index("--solo")
        if i + 1 < len(argomenti):
            solo = int(argomenti[i + 1])

    _stripe.ProviderStripe._fetch_reale = staticmethod(_fetch_finto)

    radice = tempfile.mkdtemp(prefix="radice_" + PREFISSO)
    tutte = combinazioni()
    elenco = tutte[:solo] if solo else tutte
    print("=" * 78)
    print("BANCO DEGLI INCROCI DEL LATO OSPITE")
    print(f"  combinazioni vive: {len(tutte)}  |  camminate ora: {len(elenco)}"
          + ("  (PROVA IN PICCOLO)" if solo else ""))
    print(f"  arrivo a +{GIORNI_ARRIVO} giorni  |  tassa di soggiorno azzerata  |  EUR")
    print("=" * 78)
    intest = (f"{'pagare':<13}{'prenotare':<13}{'politica':<18}{'fin.':<6}"
              f"{'incass.':>8}{'reso':>8}{'atteso':>8}  esito")
    print(intest)
    print("-" * 78)

    righe = []
    try:
        for (pagare, prenotare, politica, dentro) in elenco:
            r = cammina(radice, pagare, prenotare, politica, dentro)
            righe.append(r)
            fin = "entro" if dentro else "fuori"
            print(f"{pagare:<13}{prenotare:<13}{politica:<18}{fin:<6}"
                  f"{r['incassato']:>8}{r['rimborso']:>8}{r['atteso']:>8}  "
                  f"{r['esito']}" + (f"  <- {r['note']}" if r["note"] else ""))
    finally:
        shutil.rmtree(radice, ignore_errors=True)

    ok = sum(1 for r in righe if r["esito"] == "OK")
    rossi = [r for r in righe if r["esito"] == "ROSSO"]
    non_eseguiti = [r for r in righe if r["esito"] == "NON ESEGUITO"]
    print("-" * 78)
    print(f"  OK: {ok}   ROSSI: {len(rossi)}   NON ESEGUITI: {len(non_eseguiti)}")
    if non_eseguiti:
        print("  ATTENZIONE: un NON ESEGUITO non e' un verde. Righe senza premessa:")
        for r in non_eseguiti:
            print(f"    - {r['pagare']}/{r['prenotare']}/{r['politica']}/"
                  f"{'entro' if r['dentro'] else 'fuori'}: {r['note']}")
    if rossi:
        print("  ROSSI (i soldi non tornano):")
        for r in rossi:
            print(f"    - {r['pagare']}/{r['prenotare']}/{r['politica']}/"
                  f"{'entro' if r['dentro'] else 'fuori'}: {r['note']}")
    uscita = 1 if (rossi or non_eseguiti) else 0
    print("=" * 78)
    print(f"USCITA: {uscita}")
    return uscita


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
