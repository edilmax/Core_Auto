"""CASELLA 2, la riga d'arrivo: **i soldi tornano DAVVERO**, non «il libro dice che sono dovuti».

`test_rimborso_ogni_strada.py` censisce le **sette** strade e prova che nessuna sfugga.
`test_rimborso_coppie_stessa_chiave.py` sorveglia cosa succede quando due si incrociano.
Restava il pezzo che conta di piu' e che era fermo a **zero**: nessuna strada era mai stata
percorsa **fino al gateway**. Scrivere una riga nel giornale e restituire i soldi sono due
fatti diversi, e il primo puo' essere vero mentre il secondo e' falso — e' esattamente il
difetto del 2026-08-16, quando le strade erano due e ne funzionava una.

⛔ **COSA VERIFICA, e la differenza e' tutta qui:** non che la rotta risponda 200, non che il
libro registri il dovuto, ma che **il gateway riceva la richiesta di rimborso con l'importo
giusto e sul pagamento giusto**. Il provider e' sostituito da una **spia** che registra ogni
chiamata: e' l'ultimo anello prima dei soldi veri, e oltre quello c'e' solo Stripe.

📊 **IL DENOMINATORE NON E' 7, ED E' LA SCOPERTA PIU' UTILE DI QUESTO FILE.** Contare «2 strade
su 7 provate» sembrava onesto e invece confondeva due cose diverse:
· **7** sono le strade che **REGISTRANO** un rimborso dovuto nel libro dei soldi;
· ⛔ **2** sono i punti che possono **FARLO PARTIRE** verso il gateway — e sono **entrambi qui
  dentro**. ⇒ **2 su 2, non 2 su 7.**
Misurato: nel prodotto vivo le chiamate a `.rimborsa(` sono **esattamente due**
(`_admin_rimborso` e `_admin_rimborsa_dovuto`). Il terzo punto del progetto sta in
`fase35_pagamenti.py`, che e' importato **solo** da `fase36_booking_api` e `fase41_admin_panel`
— il **vecchio stack**, non il percorso vivo. E il codice stesso lo dichiara: *«`fase85.rimborsa()`
esiste, ed e' chiamata da `_admin_rimborso` e da `_admin_rimborsa_dovuto`»*.

🔑 **QUINDI IL MODELLO E' QUESTO, ed e' voluto:** le sette strade **mettono in lista**, e i soldi
partono **solo quando una persona preme il pulsante**. Il pannello lo scrive: *«i soldi NON
partono da soli: ogni riga si esegue a mano col pulsante»*. ⇒ La riga d'arrivo della casella 2
(«i soldi tornano DAVVERO da OGNI strada») si legge cosi': **ogni strada porta al pannello, e
dal pannello partono davvero** — ed e' quest'ultimo pezzo che qui e' provato.
⛔ **IL PEZZO CHE RESTA, CON LA SUA CIFRA: 1 SU 7.** La domanda ancora aperta e' *«ogni strada
arriva in lista con il dovuto GIUSTO?»*, ed e' diversa da quella chiusa qui («dal pannello i
soldi partono davvero»). Provata per **la cancellazione ospite** (sotto, la strada 2); per le
altre **sei no**.
⚠️ **Denominatore dichiarato: 7, cioe' tutte le strade che registrano.** Non 6: **non ho
misurato** quali delle sette debbano comparire in lista e quali no — `_admin_rimborso` scrive
nel giornale *e* fa partire i soldi, quindi potrebbe legittimamente non aspettare nessun
pulsante. Finche' non e' misurato, il denominatore prudente e' quello intero: **meglio un 1/7
che dichiara di non sapere, di un 1/6 che assume**.
📌 **E il difetto dei 200 euro vive esattamente li'**: e' una strada che arriva in lista con
l'importo **sbagliato** (lo scaglione dell'ospite al posto del totale mosso dall'admin). ⇒ Il
lavoro che resta e la riparazione che aspetta la parola del fondatore sono **la stessa cosa
vista da due lati**.

⛔ NON COPERTO (D18 punto 3): il gateway e' **finto**. Questo file dimostra che la richiesta
parte con l'importo e il riferimento giusti; **non** dimostra che Stripe la esegua, ne' che il
denaro arrivi sul conto dell'ospite. Per quello serve un giro col banco vero e una chiave di
prova, ed e' un lavoro a se'.
"""
import ast
import datetime
import json
import os
import shutil
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

WH = "whsec_gateway"
CHIAVE_FINTA = "sk"

RADICE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(RADICE, "fase83_server.py")
# ⛔ I DUE punti — e SOLO due — da cui i soldi possono partire nel prodotto vivo. Sono i
# metodi che li contengono, non le righe: i numeri di riga invecchiano al primo inserimento.
PARTENZE_CENSITE = {"_admin_rimborso", "_admin_rimborsa_dovuto"}


def metodi_che_chiamano_il_gateway():
    """I metodi di `fase83_server.py` che chiamano `.rimborsa(...)`, letti dall'AST.

    ⛔ `ast` e non `grep`: a `:6795` c'e' un **commento** che nomina `fase85.rimborsa()` per
    spiegare il modello, e un conteggio testuale lo conterebbe come una terza partenza (S6).
    E' lo stesso difetto che stanotte e' stato trovato in due attrezzi diversi del progetto."""
    with open(SERVER, "r", encoding="utf-8") as f:
        albero = ast.parse(f.read(), filename=SERVER)
    dentro = set()
    for fn in ast.walk(albero):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for nodo in ast.walk(fn):
            if isinstance(nodo, ast.Call) and getattr(nodo.func, "attr", None) == "rimborsa":
                dentro.add(fn.name)
    return dentro


class _SpiaGateway:
    """Registra ogni richiesta di rimborso al posto di mandarla a Stripe.

    ⛔ Sostituisce SOLO `rimborsa`: tutto il resto del provider resta quello vero, cosi' la
    prova non finisce per misurare un finto al posto del prodotto."""

    def __init__(self, vero, conferma=True):
        self._vero = vero
        self.chiamate = []
        # ⛔ `conferma=False` simula «Stripe non risponde / non conferma». Serve perche' il
        # prodotto ha un freno: senza la conferma dalla fonte **il pulsante non compare e i
        # soldi non partono** (`fase83_server.py`, «LA VERITA' LA DICE STRIPE, NON IL NOSTRO
        # DATABASE»). Un finto che dice sempre di si' nasconderebbe quel freno invece di
        # provarlo.
        self.conferma = conferma

    def __getattr__(self, nome):
        return getattr(self._vero, nome)

    def rimborsi_di(self, payment_intent):
        """Cosa risulta a STRIPE su quel pagamento. Il pannello lo interroga PRIMA di
        mostrare il pulsante: e' il punto in cui il prodotto rifiuta di fidarsi del proprio
        database."""
        if not self.conferma:
            return {"ok": False, "motivo": "gateway_non_raggiungibile"}
        return {"ok": True, "rimborsato_cents": 0}

    def rimborsa(self, payment_intent, importo_cents, chiave=None):
        self.chiamate.append({"payment_intent": payment_intent,
                              "importo_cents": importo_cents, "chiave": chiave})
        return {"ok": True, "id": "re_finto_%d" % len(self.chiamate)}


class _BancoGateway(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(
            lambda u, b, h: {"url": "https://x/cs", "id": "cs_" + str(time.time_ns())})

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/a.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/po.db",
            db_garanzia=f"{d}/g.db", db_tassa_comunale=f"{d}/t.db",
            commissione_bps=1500, psp_bps=300, stripe_secret_key=CHIAVE_FINTA,
            stripe_webhook_secret=WH, stripe_success_url="https://x/ok",
            stripe_cancel_url="https://x/no"))
        # LA SPIA all'ultimo anello prima dei soldi veri.
        self.spia = _SpiaGateway(getattr(self.sis, "stripe", None))
        self.sis.stripe = self.spia
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://b.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@gw.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "accetta_privacy": True,
                       "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.tok = c["token"]
        self.oggi = datetime.date.today()
        self.g("POST", "/api/host/pubblica",
               {"slug": "casa", "titolo": "C", "citta": "Roma", "prezzo_notte_cents": 20000,
                "capacita": 4, "tassa_pp_notte_cents": 200}, {"X-Host-Token": self.tok})
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": "casa", "da": self.oggi.isoformat(),
                "a": (self.oggi + datetime.timedelta(days=60)).isoformat(),
                "unita_totali": 2, "prezzo_netto_cents": 20000}, {"X-Host-Token": self.tok})

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def prenota_paga(self, email, pi="pi_prova_gw"):
        """⛔ Il webhook porta `payment_intent`: senza, il rimborso non parte da solo — la
        scheda dichiara `manca: payment_intent` e il pulsante non compare."""
        ci = self.oggi.isoformat()
        co = (self.oggi + datetime.timedelta(days=2)).isoformat()
        _, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": ci, "check_out": co, "party": 2})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": email})
        rif = b["riferimento"]
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"id": "cs_gw", "payment_intent": pi,
                                             "metadata": {"riferimento": rif}}}})
        self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                        {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})
        totale = q.get("totale_cents") or q.get("prezzo_guest_cents")
        return rif, b["voucher_token"], totale, ci, co

    def idem_key_vera(self, rif):
        _, adm = self.g("GET", "/api/admin/prenotazioni", None, {"X-Admin-Key": "ak"})
        for p in (adm or {}).get("prenotazioni", []):
            if str(p.get("idem_key", ""))[:24] == rif:
                return p.get("idem_key")
        return None


class TestDaDoveIsoldiPossonoPARTIRE(unittest.TestCase):
    """⛔ Il MODELLO, sorvegliato: **i soldi non partono da soli.**

    Sette strade mettono in lista, **due** possono far partire il denaro, e il pannello lo
    dichiara: *«i soldi NON partono da soli: ogni riga si esegue a mano col pulsante»*. È una
    scelta, non un limite — e come tutte le scelte va sorvegliata, altrimenti cambia per
    distrazione. Il giorno che qualcuno aggiunge un rimborso **automatico**, questa guardia
    grida lo stesso giorno invece che al primo rimborso sbagliato."""

    def test_NESSUNA_strada_fa_partire_i_soldi_DA_SOLA(self):
        partenze = metodi_che_chiamano_il_gateway()
        self.assertTrue(
            partenze,
            "PREMESSA NON VALIDA: nessuna chiamata a `.rimborsa(` trovata nell'albero "
            "sintattico. O il metodo è stato rinominato, o l'attrezzo non sa più leggere il "
            "codice: in entrambi i casi il confronto qui sotto sarebbe verde per assenza.")
        nuove = partenze - PARTENZE_CENSITE
        sparite = PARTENZE_CENSITE - partenze
        self.assertEqual(
            nuove, set(),
            "⛔ UN NUOVO PUNTO FA PARTIRE I SOLDI: %r. Finora il denaro usciva **solo** dai due "
            "comandi del pannello, cioè solo quando una persona decideva. Se questo è voluto "
            "va misurato prima (chi lo innesca? con quale importo? è idempotente?) e censito "
            "qui; se non lo è, è un rimborso che parte senza che nessuno l'abbia deciso."
            % (sorted(nuove),))
        self.assertEqual(
            sparite, set(),
            "⛔ UN PUNTO DI PARTENZA È SPARITO: %r. Se quel comando non chiama più il gateway, "
            "le righe che ci passavano restano in lista e i soldi **non tornano più** — e "
            "nessuno se ne accorge, perché la lista continua a compilarsi." % (sorted(sparite),))


class TestIRimborsiARRIVANOAlGateway(_BancoGateway):

    def test_STRADA_1_su_7_il_rimborso_admin_arriva_al_gateway_con_il_TOTALE(self):
        """Strada «rimborso disposto da admin» (`/api/admin/rimborso`), percorsa fino in fondo.

        Non basta il 200 e non basta la riga nel giornale: si guarda **cosa riceve il
        gateway**. L'importo dev'essere il totale della prenotazione e il pagamento dev'essere
        quello vero, altrimenti i soldi partono per la cifra o per la persona sbagliata."""
        rif, _vou, totale, ci, co = self.prenota_paga("a@gw.it", pi="pi_uno")
        idem = self.idem_key_vera(rif)
        self.assertIsNotNone(idem, "PREMESSA NON VALIDA: idem_key non trovata nel pannello.")
        self.assertEqual(self.spia.chiamate, [],
                         "PREMESSA NON VALIDA: il gateway ha gia' ricevuto qualcosa prima "
                         "che la strada fosse percorsa.")

        s, o = self.g("POST", "/api/admin/rimborso",
                      {"alloggio_id": "casa", "check_in": ci, "check_out": co,
                       "idem_key": idem}, {"X-Admin-Key": "ak"})
        self.assertEqual(s, 200, "la strada non e' stata percorsa: %r" % (o,))

        self.assertEqual(
            len(self.spia.chiamate), 1,
            "I SOLDI NON SONO PARTITI. La rotta ha risposto 200 e il giornale ha la sua riga, "
            "ma il gateway non ha ricevuto **nessuna** richiesta di rimborso: e' esattamente "
            "la differenza fra «il libro dice che sono dovuti» e «tornano davvero». "
            "Chiamate registrate: %r" % (self.spia.chiamate,))
        c = self.spia.chiamate[0]
        self.assertEqual(
            c["importo_cents"], totale,
            "IL GATEWAY HA RICEVUTO L'IMPORTO SBAGLIATO: %s invece di %s (il totale della "
            "prenotazione). All'ospite tornerebbe una cifra diversa da quella dovuta."
            % (c["importo_cents"], totale))
        self.assertEqual(
            c["payment_intent"], "pi_uno",
            "IL GATEWAY HA RICEVUTO IL PAGAMENTO SBAGLIATO (%r): i soldi partirebbero da "
            "un'altra transazione." % (c["payment_intent"],))

    def test_STRADA_2_su_7_il_pulsante_dei_rimborsi_dovuti_arriva_al_gateway(self):
        """Strada «rimborsa_dovuto» (`/api/admin/rimborsa_dovuto`), percorsa fino in fondo.

        È il pulsante che nasce dalla lista dei rimborsi dovuti: la cancellazione dell'ospite
        scrive quanto si deve, e questo lo esegue. Si verifica che al gateway arrivi **quella**
        cifra — se ne arrivasse un'altra, la lista e i soldi direbbero cose diverse."""
        rif, voucher, _totale, _ci, _co = self.prenota_paga("b@gw.it", pi="pi_due")
        s1, _ = self.g("POST", "/api/concierge/cancella", {"voucher_token": voucher})
        self.assertEqual(s1, 200, "PREMESSA NON VALIDA: la cancellazione ospite non riesce.")

        s2, lista = self.g("GET", "/api/admin/rimborsi_dovuti", None, {"X-Admin-Key": "ak"})
        self.assertEqual(s2, 200, "PREMESSA NON VALIDA: la lista non risponde: %r" % (lista,))
        # la chiave e' `rimborsi`, non `righe`: verificata sull'uscita vera del pannello.
        righe = [r for r in (lista or {}).get("rimborsi", []) if r.get("riferimento") == rif]
        self.assertTrue(
            righe,
            "PREMESSA NON VALIDA: dopo la cancellazione la prenotazione NON compare fra i "
            "rimborsi dovuti, quindi il pulsante non esiste e questa strada non si puo' "
            "percorrere. Lista ricevuta: %r" % (lista,))
        dovuto = righe[0].get("dovuto_cents")
        self.assertIsNotNone(dovuto, "PREMESSA NON VALIDA: la riga non dichiara il dovuto.")
        self.assertEqual(self.spia.chiamate, [],
                         "PREMESSA NON VALIDA: il gateway ha gia' ricevuto qualcosa.")

        s3, o3 = self.g("POST", "/api/admin/rimborsa_dovuto", {"riferimento": rif},
                        {"X-Admin-Key": "ak"})
        self.assertEqual(s3, 200, "il pulsante non ha eseguito: %r" % (o3,))

        self.assertEqual(
            len(self.spia.chiamate), 1,
            "I SOLDI NON SONO PARTITI dal pulsante dei rimborsi dovuti: la riga resta in "
            "lista e nessuno se ne accorge. Chiamate: %r" % (self.spia.chiamate,))
        c = self.spia.chiamate[0]
        self.assertEqual(
            c["importo_cents"], dovuto,
            "IL GATEWAY HA RICEVUTO %s mentre la lista dichiarava %s dovuti: il pannello e i "
            "soldi direbbero due cose diverse." % (c["importo_cents"], dovuto))
        self.assertEqual(
            c["payment_intent"], "pi_due",
            "IL GATEWAY HA RICEVUTO IL PAGAMENTO SBAGLIATO: %r" % (c["payment_intent"],))

    def test_SENZA_conferma_da_Stripe_il_pulsante_NON_c_e_e_i_soldi_NON_partono(self):
        """⛔ IL FRENO, e l'ho trovato inciampandoci: il prodotto **non si fida del proprio
        database**.

        Prima di mostrare il pulsante, il pannello chiede a Stripe cosa risulta su quel
        pagamento (*«LA VERITA' LA DICE STRIPE, NON IL NOSTRO DATABASE»*). Se la fonte non
        conferma, la riga compare **senza pulsante** e dichiara `manca: verifica_stripe`.
        ⇒ È la difesa che impedisce di restituire due volte gli stessi soldi quando il nostro
        archivio e Stripe non sono d'accordo — e senza questa guardia sarebbe **codice
        difensivo mai eseguito** (D19): sembra sicurezza, e nessuno sa se funziona."""
        self.spia.conferma = False          # Stripe non risponde / non conferma
        rif, voucher, _totale, _ci, _co = self.prenota_paga("c@gw.it", pi="pi_tre")
        s1, _ = self.g("POST", "/api/concierge/cancella", {"voucher_token": voucher})
        self.assertEqual(s1, 200, "PREMESSA NON VALIDA: la cancellazione ospite non riesce.")

        _s, lista = self.g("GET", "/api/admin/rimborsi_dovuti", None, {"X-Admin-Key": "ak"})
        righe = [r for r in (lista or {}).get("rimborsi", []) if r.get("riferimento") == rif]
        self.assertTrue(righe, "PREMESSA NON VALIDA: la riga non compare affatto, quindi non "
                               "si sta misurando il pulsante ma la lista: %r" % (lista,))
        riga = righe[0]

        self.assertFalse(
            riga.get("bottone"),
            "IL FRENO E' CADUTO: il pannello offre il pulsante anche se Stripe NON ha "
            "confermato nulla su quel pagamento. Da qui si restituiscono soldi fidandosi del "
            "nostro solo archivio — ed e' esattamente il caso in cui i due possono non essere "
            "d'accordo (un rimborso gia' fatto a mano, un pagamento mai arrivato). Riga: %r"
            % (riga,))
        self.assertIn(
            "verifica_stripe", riga.get("manca") or [],
            "la riga non dichiara PERCHE' manca il pulsante: chi guarda il pannello vede una "
            "riga muta e non sa se aspettare o intervenire (osservabile debole, ferrea 9). "
            "Riga: %r" % (riga,))

        s3, o3 = self.g("POST", "/api/admin/rimborsa_dovuto", {"riferimento": rif},
                        {"X-Admin-Key": "ak"})
        self.assertGreaterEqual(
            s3, 400,
            "PEGGIO DEL PULSANTE: la rotta esegue il rimborso anche quando il pannello lo "
            "vieta (HTTP %s). Il freno sarebbe solo grafico, e chiunque conosca l'indirizzo "
            "lo aggira: %r" % (s3, o3))
        self.assertEqual(
            self.spia.chiamate, [],
            "I SOLDI SONO PARTITI LO STESSO: il gateway ha ricevuto %r nonostante la verifica "
            "non fosse riuscita." % (self.spia.chiamate,))


if __name__ == "__main__":
    unittest.main(verbosity=2)
