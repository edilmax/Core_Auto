# -*- coding: utf-8 -*-
"""L'ESAME DEI PERCORSI PER RUOLO — il giro INTERO di admin e super admin, e la COERENZA
fra le letture che ruoli diversi fanno dello STESSO fatto.

    python collaudi/esame_percorso_ruoli.py                 misura e MOSTRA (tutto in-process)
    python collaudi/esame_percorso_ruoli.py --scrivi        misura e SCRIVE le due caselle
    python collaudi/esame_percorso_ruoli.py --casella giro|coerenza [--scrivi]   una sola
    python collaudi/esame_percorso_ruoli.py --con-guasto    stacca un anello: deve gridare, NON scrive
    python collaudi/esame_percorso_ruoli.py --autoprova     il giudizio nelle due direzioni, senza banco

⛔ IL TESTO DELLE CASELLE NON SI RICOPIA: si legge da `collaudi/piano.py`, e si trova per
   TESTO (non per indice), perche' tutt'e due sono entrate IN CODA al loro blocco e il posto
   in coda puo' cambiare ancora.

PERCHE' ESISTE (METODO_v4 PARTE 20, aggiunta il 2026-09-10). I nove strati chiedono tutti
«questo pezzo e' giusto?». Il Blocco 3 misura CHI puo' aprire una porta (401/403 senza
credenziali, matrice dei permessi); nessuno misurava che, aperta la porta, il lavoro si
PORTI A TERMINE. E nessuno confrontava le letture che due ruoli fanno dello stesso fatto --
la famiglia che l'8 settembre ha prodotto un difetto vero: il pannello dell'host mostrava
fra i guadagni un hold che nessuno aveva pagato, mentre il mastro dei payout era GIUSTO.
Nessuna delle due parti era rotta: erano in disaccordo fra loro.

I DUE GIRI, e ogni anello lascia una TRACCIA (regola ferrea 9 applicata al percorso):
  ADMIN         la porta rifiuta senza chiave · entra e VEDE la prenotazione appena fatta ·
                l'ospite contesta -> la controversia COMPARE nel suo elenco · risolve con una
                cifra -> la garanzia diventa 'risolta' con QUELLA cifra · la riga COMPARE fra
                i rimborsi dovuti col pulsante · rimborsa -> la riga ESCE dall'elenco.
  SUPER ADMIN   la porta rifiuta senza sessione · il codice sbagliato rifiuta, quello giusto
                apre · crea un conto d'operatore -> l'elenco CRESCE di uno · quel conto entra
                davvero da `/api/admin/login` · rilegge lo scaglione dell'host · rilegge gli
                invarianti (violazioni vuote).

🔑 OGNI ANELLO E' UNA DIFFERENZA, MAI UNA PRESENZA. PRIMA non c'e', DOPO c'e' (o viceversa).
   Un elenco che mostra righe sembra sano anche quando non ha letto niente: e' il modo di
   rompersi n. 1 (dati effimeri). Per questo il denominatore si chiama ANELLI, non «controlli».

LA COERENZA, e cosa confronta davvero (letto dalle risposte VERE, il 2026-09-10, non dedotto):
  · `/api/host/payout` da' il netto per valuta (`{"EUR": {"maturato": 16400}}`);
  · `/api/admin/prenotazioni` NON porta cifre: porta `idem_key`, che COMINCIA col riferimento
    -- ed e' l'aggancio fra le due letture;
  · `/api/admin/rimborsi_dovuti` porta le cifre dei rimborsi, ed e' li' che i due ruoli
    guardano lo stesso denaro;
  · il mastro (fase131) su file, letto con SQL, e' il terzo testimone.
  Si pretende che coincidano RIGA PER RIGA, non nei totali: due errori che si compensano
  danno un totale giusto, ed e' il caso che non trova nessuno.

⛔ D18, LE QUATTRO CONDIZIONI DI UNO STRUMENTO CHE MISURA:
   1. misura PRIMA se stesso (`precondizioni`): senza le caselle nel piano e senza il banco
      si FERMA e non scrive;
   2. provato nelle DUE direzioni: `--con-guasto` stacca un anello vero (l'admin risolve la
      controversia con una cifra e il rimborso dovuto ne mostra un'altra) e l'esame deve
      gridare; `--autoprova` giudica passi costruiti, senza banco;
   3. dichiara cosa NON ha esaminato: `NON_GUARDA`, stampato a ogni giro;
   4. e' sotto guardia: `test_pipeline_ci.TestLEsameDeiPercorsiPerRuoloNonPuoBARARE`.

⛔ AMBIENTE INTATTO: il banco imposta `UPLOAD_DIR` e sostituisce il fetch di Stripe sulla
   classe; qui si salvano PRIMA e si rimettono DOPO, sempre (`finally`).
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time

QUI = os.path.dirname(os.path.abspath(__file__))
RADICE = os.path.dirname(QUI)
for _p in (RADICE, QUI):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import scheda  # noqa: E402
from piano import BLOCCHI  # noqa: E402

BLOCCO_GIRI = 3
MARCA_GIRO = "giro INTERO"
COMANDO_GIRO = "python collaudi/esame_percorso_ruoli.py --casella giro --scrivi"

BLOCCO_SOLDI = 1
MARCA_COERENZA = "STESSO numero al centesimo"
COMANDO_COERENZA = "python collaudi/esame_percorso_ruoli.py --casella coerenza --scrivi"

#  ⛔ L'ORDINE DI QUESTI ANELLI E' IL PASSAGGIO VERO FRA I DUE RUOLI, misurato il 2026-09-10
#     leggendo il codice: `_admin_controversia_risolvi` pretende `_auth_admin` **E**
#     `_bunker_ok_o_field(azione="controversia_risolvi")` -- decidere quanto torna all'ospite
#     MUOVE denaro, e il prodotto lo tiene dietro il secondo fattore. `_admin_rimborsa_dovuto`
#     invece sta col solo `_auth_admin`. Quindi il caso passa di mano: l'admin lo vede
#     arrivare, il super admin decide la cifra, l'admin preme il pulsante. E' proprio quel
#     PASSAGGIO che nessuno strato guardava (METODO PARTE 20.1).
ANELLI_ADMIN = ("porta", "vede", "controversia", "dovuto", "rimborsa")
ANELLI_SUPER = ("porta_b", "entra", "crea", "opera", "risolve", "scaglione", "invarianti")
ANELLI_COERENZA = ("aggancio", "netto", "arbitro", "riga_per_riga")

PASSWORD_HOST = "password1"          # solo per il banco locale: nessun conto vero
PASSWORD_BUNKER = "SuperPw@1"        # idem: e' la password del bunker DI PROVA
IP = {"X-Forwarded-For": "203.0.113.5"}
ADMIN = {"X-Admin-Key": "ak"}

PASSI = []

NON_GUARDA = (
    "la PAGINA: qui si misurano le risposte delle rotte JSON, non cio' che il browser disegna. "
    "I tre pannelli col browser vero li percorre gia' `collaudi/clickthrough_pannelli.js`, e il "
    "confine ospite->host `collaudi/percorso_ospite_host.js`",
    "il giro dell'OSPITE e quello dell'HOST: li misurano il Blocco 7 (`esame_host_da_solo`, "
    "`esame_pannello_soldi`) e il percorso col browser; qui ci sono i due ruoli che non li aveva "
    "nessuno",
    "`/api/bunker/riconciliazione` e il ramo Stripe di `/api/bunker/guardiano`: chiamano l'API "
    "vera di Stripe e sul banco rispondono 503 / 'riconciliazione_non_eseguita'. Sono ISOLATI per "
    "costruzione (il Guardiano prosegue), e la loro casella e' quella della riconciliazione nel "
    "blocco SOLDI, non questa",
    "il bonifico vero verso l'host (Connect: 'in_transito' -> 'pagato'): il banco ha Stripe "
    "sostituito, quindi il mastro si ferma a 'maturato'",
    "`revenue_cents` di `/api/host/metriche` (valore lordo occupato) contro il netto del mastro: "
    "sono due grandezze DIVERSE dichiarate, e le giudica `esame_pannello_soldi` (casella 2 del "
    "blocco 7). Qui si confrontano solo letture che parlano dello STESSO numero",
    "gli altri ruoli d'operatore (`supporto`) oltre a quello creato: la matrice dei permessi per "
    "ruolo la misura `esame_accessi`",
)


def passo(anello, nome, ok, dettaglio=""):
    PASSI.append((anello, nome, bool(ok), dettaglio))
    print("  %s  [%s] %s%s" % ("OK  " if ok else "ROSSO", anello, nome,
                               ("  -> " + dettaglio) if dettaglio else ""))
    return bool(ok)


# --------------------------------------------------------------------------------------
# IL GIUDIZIO (puro: riceve passi, rende verdetto)
# --------------------------------------------------------------------------------------
def giudica(passi, anelli):
    """(verde, motivi, denominatore). Un anello SENZA passi non e' verde: e' NON MISURATO
    (sbaglio S7), e il denominatore e' il numero di passi osservati."""
    motivi = []
    for a in anelli:
        suoi = [p for p in passi if p[0] == a]
        if not suoi:
            motivi.append("anello «%s» NON misurato" % a)
            continue
        for _a, nome, ok, dettaglio in suoi:
            if not ok:
                motivi.append("[%s] %s%s" % (a, nome, (" (%s)" % dettaglio) if dettaglio else ""))
    fuori = [p for p in passi if p[0] not in anelli]
    if fuori:
        motivi.append("passi fuori dagli anelli dichiarati: %d" % len(fuori))
    return (not motivi), motivi, len(passi)


def condizione(blocco, marca):
    """Il testo ESATTO della casella, letto dal piano e trovato per TESTO: una e una sola."""
    b = [x for x in BLOCCHI if x["ordine"] == blocco]
    cond = b[0]["finito_quando"] if len(b) == 1 else ()
    trovate = [c for c in cond if marca in str(c)]
    if len(trovate) != 1:
        raise ValueError("il blocco %d ha %d caselle con «%s», ne serve esattamente una"
                         % (blocco, len(trovate), marca))
    return trovate[0]


# --------------------------------------------------------------------------------------
# MISURA PRIMA SE STESSO (D18 punto 1)
# --------------------------------------------------------------------------------------
def precondizioni():
    fuori = []
    for blocco, marca, eti in ((BLOCCO_GIRI, MARCA_GIRO, "dei giri"),
                               (BLOCCO_SOLDI, MARCA_COERENZA, "della coerenza")):
        try:
            fuori.append(("la casella %s esiste nel piano, una sola" % eti, True,
                          " ".join(condizione(blocco, marca).split())[:66]))
        except Exception as e:
            fuori.append(("la casella %s esiste nel piano, una sola" % eti, False,
                          "%s: %s" % (type(e).__name__, e)))
    for blocco in (BLOCCO_GIRI, BLOCCO_SOLDI):
        try:
            impronta = scheda.impronta_del_blocco(blocco)
            fuori.append(("il blocco %d ha un'impronta" % blocco, bool(impronta),
                          impronta or "il piano non si legge: una misura senza ancoraggio non vale"))
        except Exception as e:
            fuori.append(("il blocco %d ha un'impronta" % blocco, False, str(e)))
    try:
        from collaudi.gare_estreme import _fake_fetch, _host_pubblica, _quote  # noqa: F401
        from fase163_accettazioni import doc_sha256  # noqa: F401
        from fase87_stripe_webhook import firma_di_test  # noqa: F401
        fuori.append(("il banco, le accettazioni e il webhook si importano", True, ""))
    except Exception as e:
        fuori.append(("il banco, le accettazioni e il webhook si importano", False,
                      "%s: %s" % (type(e).__name__, e)))
    return all(ok for _, ok, _ in fuori), fuori


# --------------------------------------------------------------------------------------
# IL BANCO: sistema vero, Stripe finto, bunker CONFIGURATO, ambiente rimesso a posto
# --------------------------------------------------------------------------------------
def _ambiente_salvato():
    import fase85_pagamenti_stripe as stripe_mod
    return (os.environ.get("UPLOAD_DIR"), vars(stripe_mod.ProviderStripe).get("_fetch_reale"))


def _ambiente_ripristinato(salvato):
    import fase85_pagamenti_stripe as stripe_mod
    upload, fetch = salvato
    if upload is None:
        os.environ.pop("UPLOAD_DIR", None)
    else:
        os.environ["UPLOAD_DIR"] = upload
    if fetch is None:
        if "_fetch_reale" in vars(stripe_mod.ProviderStripe):
            delattr(stripe_mod.ProviderStripe, "_fetch_reale")
    else:
        stripe_mod.ProviderStripe._fetch_reale = fetch


class GatewayDiProva(object):
    """Il gateway del banco: TIENE CONTO di cosa ha rimborsato, invece di dire sempre di si'.

    ⛔ PERCHE' NON BASTA UN FINTO CHE ANNUISCE. La lista dei rimborsi dovuti non si fida del
       nostro database: chiede al gateway `rimborsi_di(pi)` e pretende `ok=True`, e la riga
       ESCE dall'elenco solo quando il gateway dichiara un rimborso > 0 (fase83:4746-4756,
       letto il 2026-09-10). Un finto che rispondesse sempre «ok, zero» terrebbe la riga
       nell'elenco per sempre; uno che rispondesse sempre «ok, tutto rimborsato» la farebbe
       sparire PRIMA che qualcuno prema il pulsante -- e allora l'anello [rimborsa] sarebbe
       verde senza che sia uscito un centesimo (S7: un verde che non ha guardato).
       Quindi qui si tiene lo stato: prima del pulsante zero, dopo la cifra vera.
    ⛔ E `ok=False` vuol dire «NON LO SO», mai «nessun rimborso»: questo finto non lo usa mai,
       cosi' non insegna all'esame a leggere un'incertezza come una risposta."""

    def __init__(self):
        self.rimborsati = {}          # payment_intent -> centesimi gia' usciti
        self.chiamate = []            # per poter dire CHI ha chiesto cosa, se serve
        self.muto = False             # IL GUASTO 2: il gateway non sa rispondere

    def rimborsa(self, payment_intent, importo_cents, chiave_idem):
        pi = str(payment_intent)
        self.chiamate.append(("rimborsa", pi, int(importo_cents), str(chiave_idem)))
        #  idempotenza vera: la stessa chiave non fa uscire i soldi due volte
        if any(c[0] == "rimborsa" and c[3] == str(chiave_idem) for c in self.chiamate[:-1]):
            return {"ok": True, "id": "re_" + pi[-8:], "importo_cents": self.rimborsati.get(pi, 0),
                    "stato": "succeeded", "ripetuto": True}
        self.rimborsati[pi] = self.rimborsati.get(pi, 0) + int(importo_cents)
        return {"ok": True, "id": "re_" + pi[-8:], "importo_cents": int(importo_cents),
                "stato": "succeeded"}

    def rimborsi_di(self, payment_intent):
        pi = str(payment_intent)
        self.chiamate.append(("rimborsi_di", pi, 0, ""))
        if self.muto:
            #  «NON LO SO», che non e' «nessun rimborso»: e' il caso vero di Stripe
            #  irraggiungibile. Il prodotto DEVE rifiutarsi di muovere soldi che non puo'
            #  verificare, e la catena dell'admin deve fermarsi li'.
            return {"ok": False, "motivo": "gateway muto (guasto iniettato dal banco)"}
        return {"ok": True, "rimborsato_cents": self.rimborsati.get(pi, 0),
                "conteggio": 1 if self.rimborsati.get(pi) else 0}


class Banco(object):
    """⛔ Il bunker vuole `bunker_password` nella configurazione: senza, ogni sua rotta
    risponde 503 «bunker_non_configurato» e il giro del super admin non sarebbe misurato ma
    SALTATO. Il banco di `gare_estreme._sistema` non la mette, quindi qui il sistema si
    costruisce a parte -- e il mastro sta SU FILE, cosi' il terzo testimone si legge con SQL."""

    def __init__(self, d):
        import fase85_pagamenti_stripe as _stripe
        from collaudi.gare_estreme import _fake_fetch, _Posta
        from fase131_payout_dashboard import crea_payout_dashboard
        from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
        from fase83_server import crea_router
        self.d = d
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)
        os.environ["UPLOAD_DIR"] = d + "/uploads"
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"R" * 32, con_registrazione_host=True,
            db_catalogo=d + "/c.db", db_inventario=d + "/i.db", db_registro_host=d + "/r.db",
            db_accettazioni=d + "/a.db", db_pendenti=d + "/p.db", db_messaggi=d + "/m.db",
            db_garanzia=d + "/g.db", db_recensioni=d + "/rec.db", db_finanza=d + "/fin.db",
            bunker_password=PASSWORD_BUNKER,
            commissione_bps=1500, psp_bps=300, stripe_secret_key="sk",
            stripe_webhook_secret="whsec_x", stripe_success_url="https://x/ok",
            stripe_cancel_url="https://x/no"))
        self.sis.email_provider = _Posta()
        #  Il gateway del banco prende il posto di quello vero SOLO su questo sistema (mai
        #  sulla classe): `fase83` lo legge con `getattr(self._sys, "stripe", None)`.
        self.gateway = GatewayDiProva()
        self.sis.stripe = self.gateway
        self.db_payout = d + "/payout.db"
        self.sis.payout = crea_payout_dashboard(self.db_payout)
        self.sis.payout.inizializza_schema()
        self.router = crea_router(self.sis, host_key="hk", admin_key="ak", base_url="https://x")
        self.tk, self.host_id = self.registra_host("host-ruoli@esame.it")

    def g(self, m, p, b=None, h=None):
        return self.router.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def registra_host(self, email):
        from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256
        s, c = self.g("POST", "/api/host/registrazione", {
            "email": email, "password": PASSWORD_HOST, "accetta_termini": True,
            "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
            "versione": CONTRATTO_HOST_VERSIONE})
        c = c if isinstance(c, dict) else {}
        if s != 201 or not c.get("token"):
            raise RuntimeError("registrazione host fallita: %s %s" % (s, c))
        return {"X-Host-Token": c["token"]}, c.get("host_id", "")

    def alloggio(self, slug, unita, da, a):
        from collaudi.gare_estreme import _host_pubblica
        return _host_pubblica(self.g, self.tk, slug, unita, 10000, da, a)

    def pagata(self, slug, ci, co):
        from collaudi.gare_estreme import _quote
        from fase87_stripe_webhook import firma_di_test
        tok = _quote(self.g, slug, ci, co)
        s, b = self.g("POST", "/api/concierge/book", {"quote_token": tok, "email": "ospite@esame.it"})
        if s != 201:
            return None, None
        rif, vt = b["riferimento"], b["voucher_token"]
        #  ⛔ L'EVENTO PORTA `id` (cs_...) E `payment_intent`, non solo i metadati: senza il
        #     `cs_` il server registra «payment_intent non conservabile» e la riga dei rimborsi
        #     dovuti nasce SENZA pulsante -- non perche' il prodotto sia rotto, ma perche' non
        #     c'e' nessun pagamento vero da rimborsare. Un banco povero produce un rosso che
        #     sembra del prodotto (S3): la forma dell'evento e' quella dei collaudi che passano.
        pi = "pi_" + rif[:16]
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"id": "cs_" + pi, "payment_intent": pi,
                                             "metadata": {"riferimento": rif}}}})
        self.router.gestisci("POST", "/api/payments/webhook", {}, pl,
                             {"Stripe-Signature": firma_di_test(pl, "whsec_x", int(time.time()))})
        return rif, vt

    # -- le tre letture dello stesso denaro --------------------------------------------
    def payout_host(self):
        s, c = self.g("GET", "/api/host/payout", None, self.tk)
        return (c or {}).get("payout", {}) if s == 200 else {}

    def prenotazioni_admin(self):
        s, c = self.g("GET", "/api/admin/prenotazioni", None, ADMIN)
        return (c or {}).get("prenotazioni", []) if s == 200 else []

    def rimborsi_admin(self):
        s, c = self.g("GET", "/api/admin/rimborsi_dovuti", None, ADMIN)
        return (c or {}).get("rimborsi", []) if s == 200 else []

    def controversie_admin(self):
        s, c = self.g("GET", "/api/admin/controversie", None, ADMIN)
        return (c or {}).get("controversie", []) if s == 200 else []

    def mastro_sql(self, host_id=None):
        """Il terzo testimone: le righe del mastro lette con SQL, non dalla rotta.

        ⛔ I NOMI DELLE COLONNE SONO QUELLI VERI, letti da `fase131` il 2026-09-10:
           `prenotazione_id, host_id, minori, valuta, stato, ts`. La cifra si chiama
           `minori` (unita' minori della valuta), NON `importo_cents`: indovinarla dava
           somma ZERO su una riga che esiste -- un rosso prodotto dall'attrezzo (S2)."""
        righe = []
        try:
            cx = sqlite3.connect(self.db_payout)
            cx.row_factory = sqlite3.Row
            for r in cx.execute("SELECT prenotazione_id, host_id, minori, valuta, stato FROM payout"):
                d = dict(r)
                if host_id is None or d.get("host_id") == host_id:
                    righe.append(d)
            cx.close()
        except Exception:
            return []
        return righe

    def guasta_il_mastro(self, rif):
        """IL GUASTO (--con-guasto), iniettato NEI DATI del banco e mai nel codice di
        produzione: la riga del mastro cambia di un centesimo DOPO che il pannello dell'host
        ha gia' mostrato la sua cifra. Nessun evento lo spiega: e' due letture dello stesso
        fatto che non coincidono piu' -- la famiglia 20.2, nella sua forma piu' piccola."""
        cx = sqlite3.connect(self.db_payout)
        cx.execute("UPDATE payout SET minori = minori + 1 WHERE prenotazione_id LIKE ?", (rif + "%",))
        cx.commit()
        cx.close()

    def bunker_headers(self, codice=PASSWORD_BUNKER):
        s, o = self.g("POST", "/api/bunker/login", {"codice": codice}, dict(ADMIN, **IP))
        h = dict(ADMIN, **IP)
        if s == 200 and isinstance(o, dict) and o.get("sessione"):
            h["X-Bunker-Session"] = o["sessione"]
        return s, h


# --------------------------------------------------------------------------------------
# I DUE GIRI E LA COERENZA
# --------------------------------------------------------------------------------------
def _importo(riga):
    """La cifra di una riga di `rimborsi_dovuti`, comunque si chiami il campo: si CERCA fra i
    nomi possibili invece di sceglierne uno a memoria (sbaglio S2), e se non c'e' torna None."""
    for k in ("dovuto_cents", "importo_cents", "rimborso_cents", "cents"):
        if isinstance(riga, dict) and isinstance(riga.get(k), int):
            return riga[k]
    return None


def _riferimento(riga):
    for k in ("riferimento", "rif", "prenotazione_id", "idem_key"):
        v = riga.get(k) if isinstance(riga, dict) else None
        if isinstance(v, str) and v:
            return v
    return ""


def giro_admin_prima_meta(b, sc):
    print("\n--- L'ADMIN, PRIMA META': entra, vede la prenotazione, riceve la controversia ---")
    s_senza, _ = b.g("GET", "/api/admin/prenotazioni", None, {})
    passo("porta", "senza chiave la porta dell'admin rifiuta (401/403), e la porta ESISTE",
          s_senza in (401, 403), "http=%s" % s_senza)

    prima = sc["prenotazioni_prima"]
    dopo = b.prenotazioni_admin()
    agganciata = [r for r in dopo if _riferimento(r).startswith(sc["rif"])]
    passo("vede", "la prenotazione pagata COMPARE nell'elenco dell'admin (prima non c'era)",
          len(prima) == 0 and len(dopo) == 1 and len(agganciata) == 1,
          "prima=%d dopo=%d agganciate=%d" % (len(prima), len(dopo), len(agganciata)))

    c_prima = b.controversie_admin()
    s_cont, _corpo = b.g("POST", "/api/garanzia/contesta",
                         {"voucher_token": sc["vt"], "motivo": "la stanza non era quella"})
    c_dopo = b.controversie_admin()
    passo("controversia", "l'ospite contesta e la controversia COMPARE nell'elenco dell'admin",
          s_cont == 200 and len(c_prima) == 0 and len(c_dopo) == 1,
          "http=%s prima=%d dopo=%d" % (s_cont, len(c_prima), len(c_dopo)))


def giro_admin_seconda_meta(b, sc, BH):
    print("\n--- LA CHIUSURA: il caso torna deciso, e il pulsante muove i soldi (secondo fattore) ---")
    cifra = sc["cifra_arbitro"]
    dovuti = b.rimborsi_admin()
    mia = [r for r in dovuti if _riferimento(r).startswith(sc["rif"])]
    manca = mia[0].get("manca") if mia else None
    passo("dovuto", "la riga COMPARE fra i rimborsi dovuti con la cifra dell'arbitro, ed e' PRONTA "
                    "(il prodotto dice da se' cosa le manca: qui non deve mancare niente)",
          len(mia) == 1 and _importo(mia[0]) == cifra and not manca,
          "righe=%d importo=%s attesa=%d manca=%s pulsante=%s"
          % (len(mia), _importo(mia[0]) if mia else None, cifra, manca,
             mia[0].get("bottone") if mia else "-"))

    #  ⛔ ANCHE QUESTO PULSANTE VUOLE IL SECONDO FATTORE: `_admin_rimborsa_dovuto` chiama
    #     `_bunker_ok_o_field(azione="rimborso")` prima di muovere un centesimo. Il modello e'
    #     coerente e piu' stretto di quanto sembri da fuori: l'admin VEDE e PREPARA, ma nessun
    #     gesto che muove denaro passa con la sola chiave. Si prova nelle due direzioni.
    s_solo_admin, _c = b.g("POST", "/api/admin/rimborsa_dovuto", {"riferimento": sc["rif"]}, ADMIN)
    s_rim, _corpo = b.g("POST", "/api/admin/rimborsa_dovuto", {"riferimento": sc["rif"]}, BH)
    restanti = [r for r in b.rimborsi_admin() if _riferimento(r).startswith(sc["rif"])]
    passo("rimborsa", "col SOLO admin il pulsante rifiuta; col secondo fattore i soldi partono e "
                      "la riga ESCE dall'elenco (prima c'era, dopo no)",
          s_solo_admin == 403 and s_rim == 200 and len(mia) == 1 and len(restanti) == 0,
          "solo_admin=%s bunker=%s prima=%d dopo=%d" % (s_solo_admin, s_rim, len(mia), len(restanti)))
    return {"cifra": cifra, "dovuti": dovuti, "mia": mia}


def giro_super_admin(b, sc):
    print("\n--- IL GIRO DEL SUPER ADMIN: secondo fattore, crea un operatore, DECIDE la controversia ---")
    s_senza, _ = b.g("GET", "/api/bunker/admin_accounts", None, dict(ADMIN, **IP))
    passo("porta_b", "senza sessione del bunker la porta rifiuta (403), e la porta ESISTE",
          s_senza == 403, "http=%s" % s_senza)

    s_male, _ = b.bunker_headers(codice="sbagliata")
    s_bene, BH = b.bunker_headers()
    passo("entra", "il codice SBAGLIATO rifiuta e quello giusto apre (le due direzioni)",
          s_male in (401, 403) and s_bene == 200 and "X-Bunker-Session" in BH,
          "sbagliato=%s giusto=%s" % (s_male, s_bene))

    s_p, c_p = b.g("GET", "/api/bunker/admin_accounts", None, BH)
    prima = len((c_p or {}).get("account", [])) if s_p == 200 else -1
    s_c, c_c = b.g("POST", "/api/bunker/admin_accounts",
                   {"azione": "crea", "email": "operatore@esame.it",
                    "password": "password123", "ruolo": "supporto"}, BH)
    s_d, c_d = b.g("GET", "/api/bunker/admin_accounts", None, BH)
    dopo = len((c_d or {}).get("account", [])) if s_d == 200 else -1
    passo("crea", "crea un conto d'operatore e l'elenco CRESCE di uno (prima 0, dopo 1)",
          s_c in (200, 201) and prima == 0 and dopo == 1,
          "http=%s prima=%d dopo=%d" % (s_c, prima, dopo))

    s_op, c_op = b.g("POST", "/api/admin/login",
                     {"email": "operatore@esame.it", "password": "password123"})
    passo("opera", "il conto appena creato ENTRA davvero da /api/admin/login (non e' una riga morta)",
          s_op == 200, "http=%s" % s_op)

    #  Il passaggio di mano: decidere quanto torna all'ospite MUOVE denaro, e sta dietro il
    #  secondo fattore. Con la sola chiave admin la stessa rotta risponde 403: si prova PRIMA
    #  che rifiuti, cosi' l'anello dice anche cosa NON basta.
    #  ⚠️ I DUE NOMI SONO DIVERSI, e sono quelli veri (letti in `_admin_controversia_risolvi`
    #     il 2026-09-10): la rotta RICEVE `rimborso_ospite_cents` e RISPONDE
    #     `rimborso_cliente_cents`. Usare il nome della risposta anche nella richiesta da' 422
    #     («percentuale_o_importo_mancante»), che e' un rosso dell'attrezzo, non del prodotto.
    cifra = sc["cifra_arbitro"]
    corpo = {"riferimento": sc["rif"], "rimborso_ospite_cents": cifra}
    s_solo_admin, _c = b.g("POST", "/api/admin/controversia/risolvi", corpo, ADMIN)
    s_ris, corpo_ris = b.g("POST", "/api/admin/controversia/risolvi", corpo, BH)
    stato_g = b.sis.garanzia.stato(sc["rif"]) or {}
    stato = stato_g.get("stato") if isinstance(stato_g, dict) else stato_g
    passo("risolve", "col SOLO admin la rotta rifiuta; col secondo fattore decide, e la garanzia "
                     "porta ESATTAMENTE quella cifra",
          s_solo_admin == 403 and s_ris == 200 and isinstance(corpo_ris, dict)
          and corpo_ris.get("rimborso_cliente_cents") == cifra and stato == "risolto",
          "solo_admin=%s bunker=%s cifra=%s garanzia=%s"
          % (s_solo_admin, s_ris, (corpo_ris or {}).get("rimborso_cliente_cents"), stato))

    s_sc, c_sc = b.g("GET", "/api/bunker/scaglioni_host", None, BH)
    host = [h for h in (c_sc or {}).get("host", []) if h.get("host_id") == b.host_id] if s_sc == 200 else []
    passo("scaglione", "rilegge lo scaglione dell'host, con il suo bps",
          len(host) == 1 and isinstance(host[0].get("bps"), int) and host[0]["bps"] > 0,
          "http=%s host=%d bps=%s" % (s_sc, len(host), host[0].get("bps") if host else None))

    s_i, c_i = b.g("GET", "/api/bunker/invarianti", None, BH)
    passo("invarianti", "rilegge gli invarianti sugli archivi veri: nessuna violazione",
          s_i == 200 and isinstance(c_i, dict) and c_i.get("ok") is True and not c_i.get("violazioni"),
          "http=%s ok=%s violazioni=%s" % (s_i, (c_i or {}).get("ok"), (c_i or {}).get("violazioni")))
    return BH


def coerenza(b, sc, esito_admin):
    print("\n--- LA COERENZA: lo STESSO fatto letto da tre parti, riga per riga ---")
    prenotazioni = b.prenotazioni_admin()
    agganciate = [r for r in prenotazioni if _riferimento(r).startswith(sc["rif"])]
    passo("aggancio", "l'admin e l'host parlano della STESSA prenotazione (l'aggancio si legge, non si suppone)",
          len(agganciate) == 1,
          "riferimento=%s idem_key=%s" % (sc["rif"][:12],
                                          (_riferimento(agganciate[0])[:12] + "...") if agganciate else "-"))

    #  ⛔ LE DUE LETTURE SI PRENDONO NELLO STESSO ISTANTE, prima della controversia. Confrontare
    #     il pannello di PRIMA col mastro di ADESSO darebbe 16400 contro 11400 e sembrerebbe
    #     un'incoerenza: in mezzo c'e' l'arbitrato, che riallinea il mastro alla quota dell'host
    #     (16400 - 5000). Un evento che spiega la differenza NON e' una divergenza -- e un
    #     confronto fra due istanti diversi accusa il prodotto di una cosa che ha fatto giusta.
    netto = sc["netto_prima"]
    somma_mastro, righe_sue = sc["mastro_prima"]
    passo("netto", "nello STESSO istante, il netto del pannello dell'host == la riga del mastro "
                   "letta con SQL (due testimoni diversi dello stesso denaro)",
          netto is not None and netto > 0 and righe_sue == 1 and somma_mastro == netto,
          "pannello=%s mastro_sql=%s righe_sue=%d" % (netto, somma_mastro, righe_sue))

    cifra = esito_admin["cifra"]
    mia = esito_admin["mia"]
    passo("arbitro", "la cifra decisa dall'admin e quella mostrata fra i rimborsi dovuti coincidono al centesimo",
          len(mia) == 1 and _importo(mia[0]) == cifra,
          "decisa=%d mostrata=%s" % (cifra, _importo(mia[0]) if mia else None))

    totale = sum((_importo(r) or 0) for r in esito_admin["dovuti"])
    righe_ok = all(_importo(r) is not None for r in esito_admin["dovuti"])
    passo("riga_per_riga", "ogni riga dell'elenco porta la SUA cifra (un totale giusto non basta: "
                           "due errori che si compensano lo darebbero uguale)",
          righe_ok and totale == cifra and len(esito_admin["dovuti"]) == 1,
          "righe=%d tutte_con_cifra=%s totale=%d cifra=%d"
          % (len(esito_admin["dovuti"]), righe_ok, totale, cifra))


def scenario(b, con_guasto=False):
    slug = b.alloggio("casa-ruoli", 3, "2027-06-01", "2027-06-30")
    prenotazioni_prima = b.prenotazioni_admin()
    rif, vt = b.pagata(slug, "2027-06-05", "2027-06-07")
    if not rif:
        raise RuntimeError("il banco non ha prodotto una prenotazione pagata")
    netto_prima = (b.payout_host().get("EUR") or {}).get("maturato")
    if con_guasto:
        # IL GUASTO sta NEI DATI del banco, mai nel codice di produzione: il mastro cambia di
        # un centesimo DOPO che il pannello ha gia' mostrato la sua cifra, e nessun evento lo
        # spiega. E' l'incoerenza fra due letture dello stesso fatto (famiglia 20.2), nella
        # forma piu' piccola che esista -- se l'esame non vede UN centesimo, non vede niente.
        # ⛔ VA INIETTATO QUI, FRA LE DUE LETTURE: dopo tutt'e due, i due testimoni tornerebbero
        #    a coincidere e l'autoprova sarebbe un verde che non ha guardato (sbaglio S7).
        b.guasta_il_mastro(rif)
        # ⛔ E SERVONO DUE GUASTI, non uno: il primo rompe solo la COERENZA e lascerebbe il
        #    giro tutto verde -- cioe' meta' attrezzo non sarebbe mai stata vista gridare.
        #    Il secondo spegne il gateway: la riga dei rimborsi dovuti non e' piu' verificabile
        #    e la catena dell'admin si ferma dove deve fermarsi.
        b.gateway.muto = True
    sue = [r for r in b.mastro_sql(b.host_id)
           if str(r.get("prenotazione_id") or "").startswith(rif)]
    mastro_prima = (sum(r.get("minori") or 0 for r in sue), len(sue))
    return {"slug": slug, "rif": rif, "vt": vt, "netto_prima": netto_prima,
            "mastro_prima": mastro_prima, "prenotazioni_prima": prenotazioni_prima,
            "cifra_arbitro": 5000}


# --------------------------------------------------------------------------------------
# L'AUTOPROVA (D18 punto 2): passi costruiti, nelle due direzioni, senza banco
# --------------------------------------------------------------------------------------
def passi_finti(anelli, rossi=(), senza=()):
    fatti = []
    for a in anelli:
        if a in senza:
            continue
        fatti.append((a, "passo di prova", a not in rossi, ""))
    return fatti


def autoprova():
    casi = []
    for eti, anelli in (("giro admin", ANELLI_ADMIN), ("giro super", ANELLI_SUPER),
                        ("coerenza", ANELLI_COERENZA)):
        casi.append(("%s: tutti gli anelli verdi" % eti, passi_finti(anelli), anelli, True))
        casi.append(("%s: un anello ROSSO" % eti, passi_finti(anelli, rossi=(anelli[0],)), anelli, False))
        casi.append(("%s: un anello NON MISURATO" % eti, passi_finti(anelli, senza=(anelli[-1],)),
                     anelli, False))
    casi.append(("un passo fuori dagli anelli",
                 passi_finti(ANELLI_ADMIN) + [("intruso", "x", True, "")], ANELLI_ADMIN, False))
    casi.append(("nessun passo affatto", [], ANELLI_ADMIN, False))
    righe, riuscita = [], True
    for nome, passi, anelli, atteso in casi:
        verde, motivi, den = giudica(passi, anelli)
        ok = (verde == atteso)
        riuscita = riuscita and ok
        righe.append("   %-40s -> %-6s (atteso %-6s) denominatore %d%s"
                     % (nome, "VERDE" if verde else "ROSSO", "VERDE" if atteso else "ROSSO", den,
                        "" if ok else "   ⛔ NON E' QUELLO CHE DOVEVA DIRE: %s" % "; ".join(motivi)))
    return riuscita, righe


# --------------------------------------------------------------------------------------
def _stampa_non_guarda():
    print("-" * 86)
    print("⛔ COSA QUESTO ESAME NON HA ESAMINATO (D18 punto 3)")
    for r in NON_GUARDA:
        print("   · %s" % r)


def main(argv=None):
    global PASSI
    argv = list(sys.argv[1:] if argv is None else argv)
    os.chdir(RADICE)
    scrivi = "--scrivi" in argv
    con_guasto = "--con-guasto" in argv
    quale = argv[argv.index("--casella") + 1] if "--casella" in argv and \
        argv.index("--casella") + 1 < len(argv) else None
    if quale not in (None, "giro", "coerenza"):
        print("⛔ casella sconosciuta: %s (valide: giro, coerenza)" % quale)
        return 2
    if con_guasto and scrivi:
        print("⛔ FERMO: `--con-guasto` non scrive. Serve a vedere l'esame gridare; registrare")
        print("   quel rosso metterebbe nella scheda un'incoerenza costruita apposta.")
        return 2

    print("=" * 86)
    print("🧾 ESAME DEI PERCORSI PER RUOLO — il giro di admin e super admin, e la coerenza")
    print("=" * 86)

    if "--autoprova" in argv:
        print("🔁 AUTOPROVA — il giudizio nelle due direzioni, senza banco (D18 punto 2)")
        riuscita, righe = autoprova()
        for r in righe:
            print(r)
        _stampa_non_guarda()
        print("=" * 86)
        print("VERDETTO: %s" % ("✅ il giudizio grida sugli anelli staccati e tace su quelli interi"
                                if riuscita else "⛔ IL GIUDIZIO NON SA DISTINGUERE"))
        return 0 if riuscita else 1

    print("PRIMA DI MISURARE, L'ESAME MISURA SE STESSO (D18 punto 1)")
    ok_pre, fuori = precondizioni()
    for nome, ok, dettaglio in fuori:
        print("  %s      %-62s %s" % ("OK  " if ok else "ROSSO", nome, dettaglio))
    if not ok_pre:
        print("VERDETTO: ⛔ FERMO — le precondizioni non reggono, non misuro e non scrivo")
        return 2

    PASSI = []
    salvato = _ambiente_salvato()
    d = tempfile.mkdtemp(prefix="ruoli_")
    try:
        b = Banco(d)
        sc = scenario(b, con_guasto=con_guasto)
        #  L'ordine e' il passaggio VERO: l'admin riceve il caso, il super admin decide la
        #  cifra (secondo fattore), l'admin preme il pulsante. Invertirlo misurerebbe due
        #  mezzi giri invece di una catena.
        giro_admin_prima_meta(b, sc)
        BH = giro_super_admin(b, sc)
        esito_admin = giro_admin_seconda_meta(b, sc, BH)
        coerenza(b, sc, esito_admin)
    finally:
        _ambiente_ripristinato(salvato)
        shutil.rmtree(d, ignore_errors=True)

    passi_giro = [p for p in PASSI if p[0] in ANELLI_ADMIN or p[0] in ANELLI_SUPER]
    passi_coer = [p for p in PASSI if p[0] in ANELLI_COERENZA]
    anelli_giro = tuple(dict.fromkeys(ANELLI_ADMIN + ANELLI_SUPER))
    verde_giro, motivi_giro, den_giro = giudica(passi_giro, anelli_giro)
    verde_coer, motivi_coer, den_coer = giudica(passi_coer, ANELLI_COERENZA)

    print()
    print("VERDETTO giro (admin + super admin): %s — anelli %d, rossi %d, denominatore %d"
          % ("✅ VERDE" if verde_giro else "⛔ ROSSO", len(anelli_giro), len(motivi_giro), den_giro))
    for m in motivi_giro:
        print("   perche': %s" % m)
    print("VERDETTO coerenza:                   %s — anelli %d, rossi %d, denominatore %d"
          % ("✅ VERDE" if verde_coer else "⛔ ROSSO", len(ANELLI_COERENZA), len(motivi_coer), den_coer))
    for m in motivi_coer:
        print("   perche': %s" % m)

    if scrivi:
        print("\nSCRITTURA NELLA SCHEDA")
        for nome, blocco, marca, comando, verde, motivi, den in (
                ("giro", BLOCCO_GIRI, MARCA_GIRO, COMANDO_GIRO, verde_giro, motivi_giro, den_giro),
                ("coerenza", BLOCCO_SOLDI, MARCA_COERENZA, COMANDO_COERENZA, verde_coer,
                 motivi_coer, den_coer)):
            if quale is not None and quale != nome:
                continue
            riga = scheda.registra(condizione(blocco, marca), esito=verde, denominatore=den,
                                   comando=comando, ordine=blocco,
                                   motivo=("; ".join(motivi)[:600] if motivi else None))
            print("  scritta: blocco %s · esito %s · denominatore %s · impronta %s · motivo: %s"
                  % (riga.get("blocco"), riga.get("esito"), riga.get("denominatore"),
                     riga.get("impronta"), riga.get("motivo") or "-"))
    else:
        print("\n(non ho scritto niente: aggiungi --scrivi per registrare nella scheda)")

    _stampa_non_guarda()
    print("=" * 86)
    tutto = (verde_giro if quale in (None, "giro") else True) and \
            (verde_coer if quale in (None, "coerenza") else True)
    return 0 if tutto else 1


if __name__ == "__main__":
    sys.exit(main())
