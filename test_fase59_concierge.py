"""
Test Fase 59 - Protocollo Concierge AI (agent-discoverable booking).

Copre: firma HMAC (round-trip + manomissione), manifest, scopri (machine-clean),
quota (prezzo firmato dal CORE, non_disponibile, non_quotabile, date invalide),
prenota (conferma + idempotenza + scadenza + firma rotta + email), la REGOLA D'ORO
(l'agente NON puo' alterare il prezzo: ogni manomissione rompe la firma), e lo stress
concorrente anti-overbooking via protocollo (10x). Usa i veri motori fase57/58.
"""
import base64
import datetime
import json
import threading
import unittest

from fase57_vetrina import CatalogoVetrina, CriteriRicerca, crea_catalogo, SchedaAlloggio
from fase58_channel_manager import EsitoPrenotazione, crea_channel_manager
from fase59_concierge import (
    MAX_CENTS, FirmaQuote, ProtocolloConcierge, crea_protocollo,
)

SEGRETO = b"0123456789abcdef0123456789abcdef"
GIORNI = ("2026-09-01", "2026-09-02", "2026-09-03")
LOGGER = "core_auto.concierge"
# Scadenza che nessun collaudo puo' raggiungere (2100-01-01). Costante, non calcolata
# dall'orologio: un token costruito con `now()+N` scadrebbe in modo diverso a seconda di
# quando gira la suite, ed e' esattamente la bomba a tempo che abbiamo gia' pagato.
FUTURO = 4102444800


def _setup(unita=1, prezzo=10000, commissione=None, clock=None):
    inv = crea_channel_manager()
    for g in GIORNI:
        inv.imposta_disponibilita("casa", g, unita_totali=unita, prezzo_netto_cents=prezzo)
    cat = crea_catalogo(disponibilita=inv.disponibile)
    cat.pubblica(SchedaAlloggio(host_id="h", slug="casa", titolo="Casa",
                                citta="Roma", prezzo_notte_cents=prezzo, capacita=4))
    proto = ProtocolloConcierge(inv, FirmaQuote(SEGRETO), catalogo=cat,
                                commissione=commissione,
                                orologio=clock)
    return inv, cat, proto


# ─────────────────────────────────────────────────────────────────────────────
# Attrezzi per i confini (aggiunti il 2026-08-14 per chiudere i punti scoperti)
# ─────────────────────────────────────────────────────────────────────────────
def _giorni(quante, inizio="2026-09-01"):
    d0 = datetime.date.fromisoformat(inizio)
    return [(d0 + datetime.timedelta(days=i)).isoformat() for i in range(quante)]


def _setup_soggiorno(quante_notti, *, sett_bps=0, mese_bps=0, prezzo=10000):
    """Un alloggio con `quante_notti` notti caricate e gli sconti soggiorno-lungo dell'host.
    Ritorna (proto, check_in, check_out) gia' pronti per `quota`."""
    inv = crea_channel_manager()
    for g in _giorni(quante_notti):
        inv.imposta_disponibilita("casa", g, unita_totali=1, prezzo_netto_cents=prezzo)
    cat = crea_catalogo(disponibilita=inv.disponibile)
    cat.pubblica(SchedaAlloggio(host_id="h", slug="casa", titolo="Casa", citta="Roma",
                                prezzo_notte_cents=prezzo, capacita=4,
                                sconto_settimana_bps=sett_bps, sconto_mese_bps=mese_bps))
    proto = ProtocolloConcierge(inv, FirmaQuote(SEGRETO), catalogo=cat)
    fine = (datetime.date.fromisoformat("2026-09-01")
            + datetime.timedelta(days=quante_notti)).isoformat()
    return proto, "2026-09-01", fine


def _credito(cents, exp, valuta="EUR", tipo="credito_fondatore"):
    """Un token di Credito Fondatore FIRMATO con la nostra chiave (quindi legittimo):
    serve a provare le guardie del credito, non la firma."""
    return FirmaQuote(SEGRETO).codifica({"tipo": tipo, "credito_cents": cents,
                                         "exp": exp, "valuta": valuta})


def _traccia(log, frammento):
    """Il record di log che contiene `frammento`, o None.

    ⛔ Si chiede l'`exc_info` PROPRIO a quel messaggio, mai «a qualche record»: sulla via
    del fail-safe ne escono due, e uno con la traccia MASCHEREREBBE l'altro senza. Una
    guardia che si accontenta di «almeno uno» e' un ornamento (regola dei 10 collaudi)."""
    for rec in log.records:
        if frammento in rec.getMessage():
            return rec
    return None


class _InventarioFinto:
    """Inventario duck-typed per COSTRUIRE A MANO gli stati che il flusso normale non
    raggiunge (D19: una difesa si mette alla prova adesso, non il giorno del disastro).
    Copre: esiti senza i campi attesi, blocchi che esplodono, rilasci che falliscono."""

    def __init__(self, *, esito=None, blocca_esplode=False, rilascia_esplode=False,
                 prezzo=10000):
        self._esito = esito
        self._blocca_esplode = blocca_esplode
        self._rilascia_esplode = rilascia_esplode
        self._prezzo = prezzo
        self.rilasci = 0

    def disponibile(self, alloggio_id, check_in, check_out):
        return True

    def stato_giorno(self, alloggio_id, giorno):
        return {"prezzo_netto_cents": self._prezzo}

    def blocca(self, alloggio_id, check_in, check_out, *, idem_key, origine=""):
        if self._blocca_esplode:
            raise RuntimeError("inventario giu'")
        return self._esito

    def rilascia(self, alloggio_id, check_in, check_out, *, idem_key):
        self.rilasci += 1
        if self._rilascia_esplode:
            raise RuntimeError("rilascio giu'")
        return EsitoPrenotazione(True, "")


class TestFirma(unittest.TestCase):
    def test_round_trip(self):
        f = FirmaQuote(SEGRETO)
        t = f.codifica({"a": 1, "prezzo": 999})
        self.assertEqual(f.decodifica(t)["prezzo"], 999)

    def test_manomissione_firma_rotta(self):
        f = FirmaQuote(SEGRETO)
        t = f.codifica({"prezzo_guest_cents": 10000})
        b64, sig = t.split(".")
        # l'agente prova ad abbassare il prezzo nel payload
        falso = json.loads(base64.urlsafe_b64decode(b64))
        falso["prezzo_guest_cents"] = 1
        b64_falso = base64.urlsafe_b64encode(
            json.dumps(falso, separators=(",", ":"), sort_keys=True).encode()).decode()
        token_falso = b64_falso + "." + sig
        self.assertIsNone(f.decodifica(token_falso))   # firma non combacia

    def test_token_malformati(self):
        f = FirmaQuote(SEGRETO)
        for bad in (None, 123, "", "senza-punto", "a.b.c", "x." + "0" * 64):
            self.assertIsNone(f.decodifica(bad))

    def test_segreto_corto_rifiutato(self):
        with self.assertRaises(ValueError):
            FirmaQuote(b"corto")

    def test_chiave_diversa_non_verifica(self):
        t = FirmaQuote(SEGRETO).codifica({"x": 1})
        self.assertIsNone(FirmaQuote(b"X" * 32).decodifica(t))


class TestManifestScopri(unittest.TestCase):
    def test_manifest_dichiara_regole(self):
        _, _, proto = _setup()
        m = proto.manifest()
        self.assertEqual(m["money_unit"], "cents_integer")
        self.assertTrue(m["regole"]["agente_non_puo_alterare_il_prezzo"])

    def test_scopri_machine_clean(self):
        _, _, proto = _setup()
        r = proto.scopri({"citta": "Roma", "check_in": "2026-09-01",
                          "check_out": "2026-09-03"})
        self.assertEqual(r.status, 200)
        self.assertEqual(r.corpo["money_unit"], "cents_integer")
        self.assertEqual(r.corpo["totale"], 1)
        self.assertIsInstance(r.corpo["risultati"][0]["prezzo_notte_cents"], int)

    def test_scopri_senza_catalogo(self):
        inv = crea_channel_manager()
        proto = crea_protocollo(inv, SEGRETO)
        self.assertEqual(proto.scopri({}).status, 501)


class TestQuota(unittest.TestCase):
    def test_quota_prezzo_firmato_dal_core(self):
        _, _, proto = _setup(prezzo=10000, commissione=lambda netto: netto // 10)
        r = proto.quota({"alloggio_id": "casa", "check_in": "2026-09-01",
                         "check_out": "2026-09-03"})
        self.assertEqual(r.status, 200)
        # 2 notti x 10000 = 20000 listino; commissione 10% = 2000 DEDOTTA dall'host.
        # 0% ospite: l'ospite paga il prezzo pulito (20000); l'host riceve 18000.
        self.assertEqual(r.corpo["prezzo_netto_cents"], 20000)
        self.assertEqual(r.corpo["commissione_cents"], 2000)
        self.assertEqual(r.corpo["prezzo_guest_cents"], 20000)   # pulito, no guest fee
        self.assertEqual(r.corpo["netto_host_cents"], 18000)     # host riceve listino - comm
        self.assertIn("quote_token", r.corpo)

    def test_quota_non_disponibile(self):
        inv, _, proto = _setup(unita=1)
        # consuma l'unica unita'
        inv.blocca("casa", "2026-09-01", "2026-09-03", idem_key="x")
        r = proto.quota({"alloggio_id": "casa", "check_in": "2026-09-01",
                         "check_out": "2026-09-03"})
        self.assertEqual(r.status, 409)

    def test_quota_date_non_valide(self):
        _, _, proto = _setup()
        r = proto.quota({"alloggio_id": "casa", "check_in": "2026-09-03",
                         "check_out": "2026-09-01"})
        self.assertEqual(r.status, 422)

    def test_quota_non_quotabile_prezzo_zero(self):
        inv = crea_channel_manager()
        inv.imposta_disponibilita("casa", "2026-09-01", unita_totali=1,
                                  prezzo_netto_cents=0)  # nessun prezzo impostato
        proto = crea_protocollo(inv, SEGRETO)
        r = proto.quota({"alloggio_id": "casa", "check_in": "2026-09-01",
                         "check_out": "2026-09-02"})
        self.assertEqual(r.status, 422)
        self.assertEqual(r.corpo["errore"], "non_quotabile")

    def test_quota_input_blindato(self):
        _, _, proto = _setup()
        for bad in (None, [], "x", {"alloggio_id": "casa|x", "check_in": "2026-09-01",
                                    "check_out": "2026-09-03"}):
            self.assertGreaterEqual(proto.quota(bad).status, 400)


class TestPrenota(unittest.TestCase):
    def _quota_token(self, proto):
        r = proto.quota({"alloggio_id": "casa", "check_in": "2026-09-01",
                         "check_out": "2026-09-03"})
        return r.corpo["quote_token"]

    def test_prenota_conferma(self):
        inv, _, proto = _setup(unita=1)
        token = self._quota_token(proto)
        r = proto.prenota({"quote_token": token, "email": "g@x.it"})
        self.assertEqual(r.status, 201)
        self.assertEqual(r.corpo["stato"], "confermata")
        self.assertEqual(r.corpo["prezzo_guest_cents"], 20000)
        # inventario scalato
        self.assertFalse(inv.disponibile("casa", "2026-09-01", "2026-09-03"))

    def test_prenota_idempotente(self):
        inv, _, proto = _setup(unita=1)
        token = self._quota_token(proto)
        r1 = proto.prenota({"quote_token": token, "email": "g@x.it"})
        r2 = proto.prenota({"quote_token": token, "email": "g@x.it"})
        self.assertEqual(r1.status, 201)
        self.assertEqual(r2.status, 201)
        self.assertTrue(r2.corpo["idempotente"])
        self.assertEqual(inv.stato_giorno("casa", "2026-09-01")["unita_occupate"], 1)

    def test_prenota_firma_rotta(self):
        _, _, proto = _setup()
        token = self._quota_token(proto)
        manomesso = token[:-2] + ("aa" if not token.endswith("aa") else "bb")
        r = proto.prenota({"quote_token": manomesso, "email": "g@x.it"})
        self.assertEqual(r.status, 400)
        self.assertEqual(r.corpo["errore"], "quote_non_valida")

    def test_prenota_scaduta(self):
        t = {"v": 1000}
        clock = lambda: t["v"]
        _, _, proto = _setup(clock=clock)
        token = self._quota_token(proto)      # exp = 1000 + 900 = 1900
        t["v"] = 5000                          # tempo avanza oltre la scadenza
        r = proto.prenota({"quote_token": token, "email": "g@x.it"})
        self.assertEqual(r.status, 410)
        self.assertEqual(r.corpo["errore"], "quote_scaduta")

    def test_prenota_email_invalida(self):
        _, _, proto = _setup()
        token = self._quota_token(proto)
        r = proto.prenota({"quote_token": token, "email": "non-email"})
        self.assertEqual(r.status, 400)

    def test_agente_non_puo_abbassare_il_prezzo(self):
        """La regola d'oro: manipolare il prezzo nel token rompe la firma -> rifiuto."""
        _, _, proto = _setup()
        token = self._quota_token(proto)
        b64, sig = token.split(".")
        payload = json.loads(base64.urlsafe_b64decode(b64))
        payload["prezzo_guest_cents"] = 1     # l'agente prova a pagare 1 cent
        b64_falso = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()).decode()
        r = proto.prenota({"quote_token": b64_falso + "." + sig, "email": "g@x.it"})
        self.assertEqual(r.status, 400)       # firma non combacia -> niente sconto pirata

    def test_link_pagamento_isolato(self):
        inv, cat, _ = _setup(unita=1)
        proto = ProtocolloConcierge(inv, FirmaQuote(SEGRETO), catalogo=cat,
                                    link_pagamento=lambda d: "https://pay/x")
        r = proto.quota({"alloggio_id": "casa", "check_in": "2026-09-01",
                         "check_out": "2026-09-03"})
        rb = proto.prenota({"quote_token": r.corpo["quote_token"], "email": "g@x.it"})
        self.assertEqual(rb.corpo.get("payment_url"), "https://pay/x")

    def test_link_pagamento_che_solleva_NON_conferma(self):
        """⚠️ CORRETTO IL 2026-07-29. Questo test asseriva `status == 201` col commento
        «prenotazione valida nonostante PSP giu'»: **codificava come atteso un difetto che
        regalava il soggiorno** (voucher + PIN validi, date bloccate, nessun payment_url,
        nessun pendente → stanza fuori mercato e incasso zero). Un test che benedice una
        perdita di denaro è più pericoloso di nessun test.
        Comportamento corretto: gateway CONFIGURATO ma in avaria → 503 e stanza rilasciata,
        esattamente come già faceva il ramo su-richiesta. Dettaglio e prove in
        test_stripe_giu_al_book.py."""
        inv, cat, _ = _setup(unita=1)
        def boom(_):
            raise RuntimeError("psp giu'")
        proto = ProtocolloConcierge(inv, FirmaQuote(SEGRETO), catalogo=cat,
                                    link_pagamento=boom)
        r = proto.quota({"alloggio_id": "casa", "check_in": "2026-09-01",
                         "check_out": "2026-09-03"})
        rb = proto.prenota({"quote_token": r.corpo["quote_token"], "email": "g@x.it"})
        self.assertEqual(rb.status, 503)
        self.assertEqual(rb.corpo.get("errore"), "pagamento_non_disponibile")
        self.assertNotIn("payment_url", rb.corpo)
        self.assertNotIn("voucher_token", rb.corpo)


class TestToolAggiuntivi(unittest.TestCase):
    def test_dettaglio(self):
        _, _, proto = _setup()
        r = proto.dettaglio({"alloggio_id": "casa"})
        self.assertEqual(r.status, 200)
        self.assertEqual(r.corpo["slug"], "casa")

    def test_dettaglio_404(self):
        _, _, proto = _setup()
        self.assertEqual(proto.dettaglio({"alloggio_id": "mai"}).status, 404)

    def test_dettaglio_senza_catalogo(self):
        inv, _, _ = _setup()
        from fase59_concierge import ProtocolloConcierge, FirmaQuote
        proto = ProtocolloConcierge(inv, FirmaQuote(SEGRETO))   # no catalogo
        self.assertEqual(proto.dettaglio({"alloggio_id": "casa"}).status, 501)

    def test_lingue(self):
        _, _, proto = _setup()
        r = proto.lingue({})
        self.assertEqual(r.status, 200)
        self.assertIn("en", r.corpo["lingue"])

    def test_confronto(self):
        _, _, proto = _setup()
        r = proto.confronto({"prezzo_cents": 10000, "ota": "booking"})
        self.assertEqual(r.status, 200)
        self.assertGreater(r.corpo["guadagno_extra_host_cents"], 0)

    def test_confronto_prezzo_invalido(self):
        _, _, proto = _setup()
        self.assertEqual(proto.confronto({"prezzo_cents": -5}).status, 400)


class TestStressConcierge(unittest.TestCase):
    def test_anti_overbooking_via_protocollo_10x(self):
        """10 ripetizioni: 1 unita', molti agenti quotano+prenotano la stessa notte;
        esattamente 1 conferma (zero doppie vendite via protocollo)."""
        import os
        import shutil
        import tempfile
        from fase58_channel_manager import crea_channel_manager as cm_file
        for rip in range(10):
            d = tempfile.mkdtemp()
            try:
                inv = cm_file(os.path.join(d, f"c{rip}.db"))
                inv.imposta_disponibilita("casa", "2026-09-01", unita_totali=1,
                                          prezzo_netto_cents=10000)
                proto = ProtocolloConcierge(inv, FirmaQuote(SEGRETO))
                esiti = []
                lock = threading.Lock()

                def agente(i):
                    q = proto.quota({"alloggio_id": "casa", "check_in": "2026-09-01",
                                     "check_out": "2026-09-02"})
                    if q.status != 200:
                        return
                    r = proto.prenota({"quote_token": q.corpo["quote_token"],
                                       "email": f"a{i}@x.it"})
                    with lock:
                        esiti.append(r.status)

                th = [threading.Thread(target=agente, args=(i,)) for i in range(20)]
                for t in th:
                    t.start()
                for t in th:
                    t.join()
                confermate = [s for s in esiti if s == 201]
                self.assertEqual(len(confermate), 1,
                                 f"rip {rip}: attese 1 conferma, trovate {len(confermate)}")
                self.assertEqual(inv.stato_giorno("casa", "2026-09-01")["unita_occupate"], 1)
            finally:
                shutil.rmtree(d, ignore_errors=True)


# ═════════════════════════════════════════════════════════════════════════════
# I PUNTI SCOPERTI DI `fase59` — chiusi il 2026-08-14
#
# Non sono difetti del prodotto: sono punti dove un difetto NON verrebbe visto. Il
# Giudice della mutazione (22 sorveglianti, 252 minuti) ne aveva trovati 42 su 114.
# Ogni test qui sotto e' stato VISTO ROSSO col suo mutante dentro e verde senza, con
# ripristino byte-identico (sha256): senza il rosso un verde non vale niente.
# ═════════════════════════════════════════════════════════════════════════════
class TestManifestCostanti(unittest.TestCase):
    """Le promesse del manifest sono il CONTRATTO che l'agente esterno legge: se una
    diventa `False` in silenzio, un agente puo' concludere che il prezzo e' trattabile
    o che un doppio invio raddoppia la prenotazione."""

    def test_manifest_promette_prezzo_firmato_E_idempotenza(self):
        _, _, proto = _setup()
        regole = proto.manifest()["regole"]
        self.assertIs(regole["il_prezzo_e_firmato_dal_core"], True)
        self.assertIs(regole["idempotente"], True)


class TestPrimitive(unittest.TestCase):
    """`_stringa`, `impronta` e `codifica`: tre funzioni di due righe da cui dipendono
    la validazione di ogni ingresso, il riconoscimento di un dato e la firma del prezzo."""

    def test_stringa_accetta_il_limite_ESATTO_e_rifiuta_il_passo_dopo(self):
        from fase59_concierge import _stringa
        self.assertEqual(_stringa("a" * 256), "a" * 256)
        self.assertIsNone(_stringa("a" * 257))

    def test_stringa_rifiuta_il_vuoto_e_i_soli_spazi(self):
        from fase59_concierge import _stringa
        self.assertIsNone(_stringa(""))
        self.assertIsNone(_stringa("   "))
        self.assertEqual(_stringa("  casa  "), "casa")

    def test_impronta_DISTINGUE_due_valori_diversi(self):
        """Se l'impronta collassasse sullo stesso valore per tutti, due persone diverse
        risulterebbero la stessa persona -- e il riconoscimento senza conservazione,
        che e' lo scopo della funzione, sarebbe un ornamento."""
        f = FirmaQuote(SEGRETO)
        self.assertNotEqual(f.impronta("mario@x.it"), f.impronta("luigi@x.it"))
        self.assertEqual(f.impronta(" Mario@X.IT "), f.impronta("mario@x.it"))

    def test_codifica_e_STABILE_qualunque_sia_l_ordine_delle_chiavi(self):
        """Due dizionari con lo stesso contenuto devono dare lo STESSO token: senza
        l'ordinamento delle chiavi la firma dipenderebbe dall'ordine di inserimento, e
        lo stesso preventivo comparato due volte darebbe due idem-key diverse (cioe'
        due prenotazioni per un solo cliente)."""
        f = FirmaQuote(SEGRETO)
        self.assertEqual(f.codifica({"alfa": 1, "beta": 2, "gamma": 3}),
                         f.codifica({"gamma": 3, "beta": 2, "alfa": 1}))


class TestScopriCriteri(unittest.TestCase):
    """`scopri` traduce il JSON dell'agente nei criteri del catalogo: se un criterio si
    perde per strada la ricerca risponde 200 con risultati SBAGLIATI, che e' peggio di
    un errore."""

    class _CatalogoSpia:
        def __init__(self):
            self.visto = None

        def cerca(self, criteri):
            self.visto = criteri
            return {"totale": 0, "risultati": []}

    def _proto_con_spia(self):
        spia = self._CatalogoSpia()
        return ProtocolloConcierge(crea_channel_manager(), FirmaQuote(SEGRETO),
                                   catalogo=spia), spia

    def test_citta_e_date_ARRIVANO_al_catalogo(self):
        proto, spia = self._proto_con_spia()
        r = proto.scopri({"citta": "Roma", "check_in": "2026-09-01",
                          "check_out": "2026-09-03", "servizi": ["wifi"]})
        self.assertEqual(r.status, 200)
        self.assertEqual(spia.visto.citta, "Roma")
        self.assertEqual(spia.visto.check_in, "2026-09-01")
        self.assertEqual(spia.visto.check_out, "2026-09-03")
        self.assertEqual(spia.visto.servizi, ("wifi",))

    def test_scopri_in_avaria_LASCIA_LA_TRACCIA_dell_eccezione(self):
        """Senza `exc_info` resta scritto «eccezione ISOLATA» e nient'altro: un guasto
        senza nome (regola ferrea 9, l'osservabile debole e' un difetto)."""
        class _Rotto:
            def cerca(self, criteri):
                raise RuntimeError("catalogo giu'")

        proto = ProtocolloConcierge(crea_channel_manager(), FirmaQuote(SEGRETO),
                                    catalogo=_Rotto())
        with self.assertLogs(LOGGER, level="ERROR") as log:
            r = proto.scopri({"citta": "Roma"})
        self.assertEqual(r.status, 503)
        rec = _traccia(log, "scopri: eccezione ISOLATA")
        self.assertIsNotNone(rec)
        self.assertIsInstance(rec.exc_info, tuple,
                              "il log non porta la traccia dell'eccezione")


class TestSogliaSoggiornoLungo(unittest.TestCase):
    """I due confini dello sconto soggiorno-lungo (7 e 28 notti) sono SOLDI: un passo
    sbagliato regala o nega uno sconto a ogni prenotazione lunga."""

    def test_lo_sconto_settimana_scatta_a_SETTE_notti_esatte(self):
        proto, ci, co = _setup_soggiorno(7, sett_bps=1000)
        r = proto.quota({"alloggio_id": "casa", "check_in": ci, "check_out": co})
        self.assertEqual(r.status, 200)
        self.assertEqual(r.corpo["prezzo_listino_cents"], 70000)
        self.assertEqual(r.corpo["sconto_soggiorno_lungo_cents"], 7000)
        self.assertEqual(r.corpo["prezzo_guest_cents"], 63000)

    def test_lo_sconto_mese_scatta_a_VENTOTTO_notti_esatte_e_PREVALE(self):
        proto, ci, co = _setup_soggiorno(28, sett_bps=1000, mese_bps=2000)
        r = proto.quota({"alloggio_id": "casa", "check_in": ci, "check_out": co})
        self.assertEqual(r.status, 200)
        self.assertEqual(r.corpo["prezzo_listino_cents"], 280000)
        self.assertEqual(r.corpo["sconto_soggiorno_lungo_cents"], 56000)   # 20%, non 10%

    def test_a_VENTOTTO_notti_senza_sconto_mese_vale_quello_settimana(self):
        proto, ci, co = _setup_soggiorno(28, sett_bps=1000, mese_bps=0)
        r = proto.quota({"alloggio_id": "casa", "check_in": ci, "check_out": co})
        self.assertEqual(r.corpo["sconto_soggiorno_lungo_cents"], 28000)   # 10% di 280000

    def test_a_SETTE_notti_lo_sconto_mese_NON_si_applica(self):
        proto, ci, co = _setup_soggiorno(7, sett_bps=1000, mese_bps=2000)
        r = proto.quota({"alloggio_id": "casa", "check_in": ci, "check_out": co})
        self.assertEqual(r.corpo["sconto_soggiorno_lungo_cents"], 7000)    # 10%, non 20%

    def test_sotto_le_SETTE_notti_NESSUNO_sconto(self):
        proto, ci, co = _setup_soggiorno(2, sett_bps=1000, mese_bps=2000)
        r = proto.quota({"alloggio_id": "casa", "check_in": ci, "check_out": co})
        self.assertEqual(r.corpo["sconto_soggiorno_lungo_cents"], 0)
        self.assertEqual(r.corpo["prezzo_guest_cents"], 20000)


class TestBandeDelPrezzo(unittest.TestCase):
    """I due estremi della banda di prezzo, provati sul confine esatto."""

    def test_il_prezzo_al_TETTO_esatto_e_ancora_accettato(self):
        inv = crea_channel_manager()
        inv.imposta_disponibilita("casa", "2026-09-01", unita_totali=1,
                                  prezzo_netto_cents=MAX_CENTS)
        proto = ProtocolloConcierge(inv, FirmaQuote(SEGRETO))
        r = proto.quota({"alloggio_id": "casa", "check_in": "2026-09-01",
                         "check_out": "2026-09-02"})
        self.assertEqual(r.status, 200)
        self.assertEqual(r.corpo["prezzo_guest_cents"], MAX_CENTS)

    def test_un_prezzo_ospite_a_ZERO_e_RIFIUTATO(self):
        """D19: lo stato «impossibile» si costruisce a mano, adesso. Nessun credito vero
        puo' azzerare il prezzo (il pavimento sui costi lascia sempre >= 225 cent), quindi
        questa guardia non e' raggiungibile dal flusso normale -- ed e' esattamente il
        motivo per cui va provata iniettando lo sconto, invece di darla per buona."""
        inv, cat, _ = _setup(unita=1)

        class _ProtoScontoTotale(ProtocolloConcierge):
            def _sconto_credito(self, token, netto, comm, valuta="EUR"):
                return netto, "sconto-totale"

        proto = _ProtoScontoTotale(inv, FirmaQuote(SEGRETO), catalogo=cat)
        r = proto.quota({"alloggio_id": "casa", "check_in": "2026-09-01",
                         "check_out": "2026-09-03"})
        self.assertEqual(r.status, 422)
        self.assertEqual(r.corpo["errore"], "prezzo_fuori_banda")


class TestDenaroSempreIntero(unittest.TestCase):
    """Il modulo promette `money_unit: cents_integer`. Un valore non intero che entra da
    un pezzo iniettato (commissione, tassa, credito) romperebbe la promessa in silenzio:
    e' il modo di rompersi #10, il dato assurdo col formato giusto."""

    def test_una_commissione_NON_intera_viene_azzerata(self):
        inv, cat, _ = _setup(unita=1)
        proto = ProtocolloConcierge(inv, FirmaQuote(SEGRETO), catalogo=cat,
                                    commissione=lambda netto: netto * 0.1)
        r = proto.quota({"alloggio_id": "casa", "check_in": "2026-09-01",
                         "check_out": "2026-09-03"})
        self.assertEqual(r.status, 200)
        self.assertEqual(r.corpo["commissione_cents"], 0)
        self.assertIsInstance(r.corpo["netto_host_cents"], int)

    def test_una_tassa_NON_intera_viene_ignorata(self):
        inv, cat, _ = _setup(unita=1)
        proto = ProtocolloConcierge(inv, FirmaQuote(SEGRETO), catalogo=cat,
                                    tassa_alloggio=lambda slug, **kw: 12.5)
        r = proto.quota({"alloggio_id": "casa", "check_in": "2026-09-01",
                         "check_out": "2026-09-03"})
        self.assertEqual(r.status, 200)
        self.assertEqual(r.corpo["tassa_soggiorno_cents"], 0)
        self.assertIsInstance(r.corpo["totale_cents"], int)

    def test_una_tassa_NEGATIVA_viene_ignorata(self):
        """Una tassa negativa non e' uno sconto: sarebbe denaro tolto alla citta' e
        regalato, e il totale scenderebbe sotto il soggiorno."""
        inv, cat, _ = _setup(unita=1)
        proto = ProtocolloConcierge(inv, FirmaQuote(SEGRETO), catalogo=cat,
                                    tassa_alloggio=lambda slug, **kw: -500)
        r = proto.quota({"alloggio_id": "casa", "check_in": "2026-09-01",
                         "check_out": "2026-09-03"})
        self.assertEqual(r.corpo["tassa_soggiorno_cents"], 0)
        self.assertEqual(r.corpo["totale_cents"], r.corpo["prezzo_guest_cents"])

    def test_quota_in_avaria_LASCIA_LA_TRACCIA_dell_eccezione(self):
        class _InvRotto:
            def disponibile(self, *a, **k):
                raise RuntimeError("inventario giu'")

            def stato_giorno(self, *a, **k):
                return {"prezzo_netto_cents": 10000}

        proto = ProtocolloConcierge(_InvRotto(), FirmaQuote(SEGRETO))
        with self.assertLogs(LOGGER, level="ERROR") as log:
            r = proto.quota({"alloggio_id": "casa", "check_in": "2026-09-01",
                             "check_out": "2026-09-03"})
        self.assertEqual(r.status, 503)
        rec = _traccia(log, "quota: eccezione ISOLATA")
        self.assertIsNotNone(rec)
        self.assertIsInstance(rec.exc_info, tuple,
                              "il log non porta la traccia dell'eccezione")


class TestValutaDellAnnuncio(unittest.TestCase):
    def test_una_valuta_FUORI_MISURA_ricade_sul_default(self):
        """`_valuta_alloggio` accetta 1-8 caratteri. Senza il controllo sulla lunghezza,
        una stringa qualsiasi del catalogo finirebbe nella valuta dell'ADDEBITO."""
        class _CatValutaAssurda:
            def dettaglio(self, slug):
                return {"slug": slug, "valuta": "VALUTA-TROPPO-LUNGA"}

        inv = crea_channel_manager()
        inv.imposta_disponibilita("casa", "2026-09-01", unita_totali=1,
                                  prezzo_netto_cents=10000)
        proto = ProtocolloConcierge(inv, FirmaQuote(SEGRETO), catalogo=_CatValutaAssurda())
        r = proto.quota({"alloggio_id": "casa", "check_in": "2026-09-01",
                         "check_out": "2026-09-02"})
        self.assertEqual(r.status, 200)
        self.assertEqual(r.corpo["valuta"], "EUR")


class TestCreditoFondatore(unittest.TestCase):
    """Le guardie del Credito Fondatore. Netto 20000, commissione 2000, pavimento sui
    costi 875 -> margine regalabile 1125: un credito da 500 sconta 500."""

    def _proto(self, **kw):
        t = {"v": 1000}
        inv, cat, proto = _setup(unita=1, commissione=lambda netto: netto // 10,
                                 clock=lambda: t["v"])
        if kw:
            proto = ProtocolloConcierge(inv, FirmaQuote(SEGRETO), catalogo=cat,
                                        commissione=lambda netto: netto // 10,
                                        orologio=lambda: t["v"], **kw)
        return proto, t

    def _quota(self, proto, token):
        return proto.quota({"alloggio_id": "casa", "check_in": "2026-09-01",
                            "check_out": "2026-09-03", "credito_token": token})

    def test_un_credito_che_scade_ESATTAMENTE_ADESSO_vale_ancora(self):
        proto, t = self._proto()
        r = self._quota(proto, _credito(500, t["v"]))
        self.assertEqual(r.status, 200)
        self.assertEqual(r.corpo["sconto_credito_cents"], 500)
        self.assertEqual(r.corpo["prezzo_guest_cents"], 19500)

    def test_un_credito_SCADUTO_di_un_secondo_non_sconta(self):
        proto, t = self._proto()
        r = self._quota(proto, _credito(500, t["v"] - 1))
        self.assertEqual(r.corpo["sconto_credito_cents"], 0)

    def test_una_scadenza_BOOLEANA_non_e_una_scadenza(self):
        """`True` e' un `int` per Python: senza l'esclusione esplicita dei booleani un
        credito con `exp: true` sarebbe eternamente valido."""
        proto, _ = self._proto()
        r = self._quota(proto, _credito(500, True))
        self.assertEqual(r.corpo["sconto_credito_cents"], 0)

    def test_un_credito_NELLA_STESSA_valuta_sconta(self):
        proto, _ = self._proto()
        r = self._quota(proto, _credito(500, FUTURO, valuta="EUR"))
        self.assertEqual(r.corpo["sconto_credito_cents"], 500)

    def test_un_credito_in_ALTRA_valuta_NON_sconta(self):
        """La guardia cross-valuta: senza, 5 EUR di credito varrebbero 500 JPY (circa
        3 EUR) o -- al contrario -- un credito nato in valuta debole si spenderebbe
        come euro. Perdita farmabile, mai una conversione occulta."""
        proto, _ = self._proto()
        r = self._quota(proto, _credito(500, FUTURO, valuta="JPY"))
        self.assertEqual(r.corpo["sconto_credito_cents"], 0)

    def test_un_credito_NON_intero_non_sconta(self):
        proto, _ = self._proto()
        r = self._quota(proto, _credito(500.5, FUTURO))
        self.assertEqual(r.corpo["sconto_credito_cents"], 0)
        self.assertIsInstance(r.corpo["prezzo_guest_cents"], int)

    def test_un_credito_di_TIPO_sbagliato_non_sconta(self):
        proto, _ = self._proto()
        r = self._quota(proto, _credito(500, FUTURO, tipo="buono_regalo"))
        self.assertEqual(r.corpo["sconto_credito_cents"], 0)

    def test_lo_store_del_credito_ROTTO_lascia_la_traccia_e_NON_toglie_lo_sconto(self):
        """Fail-open dichiarato: un guasto del nostro schedario non deve punire un
        credito legittimo. Ma dev'essere SCRITTO, con la traccia, o non lo sapra' nessuno."""
        class _StoreRotto:
            def usato(self, credito_id):
                raise RuntimeError("store giu'")

        proto, _ = self._proto(credito_store=_StoreRotto())
        with self.assertLogs(LOGGER, level="WARNING") as log:
            r = self._quota(proto, _credito(500, FUTURO))
        self.assertEqual(r.corpo["sconto_credito_cents"], 500)
        rec = _traccia(log, "credito single-use: check ISOLATO fallito")
        self.assertIsNotNone(rec)
        self.assertIsInstance(rec.exc_info, tuple,
                              "il log non porta la traccia dell'eccezione")

    def test_un_credito_GIA_SPESO_non_sconta_piu(self):
        class _StoreUsato:
            def usato(self, credito_id):
                return True

        proto, _ = self._proto(credito_store=_StoreUsato())
        r = self._quota(proto, _credito(500, FUTURO))
        self.assertEqual(r.corpo["sconto_credito_cents"], 0)


class TestConfiniPrenota(unittest.TestCase):
    """`prenota` e' l'atto che muove il denaro e blocca la stanza: qui ogni difesa va
    provata da sola, perche' il giorno che serve e' il giorno in cui tutto il resto ha
    gia' ceduto (D19)."""

    def _token(self, proto):
        r = proto.quota({"alloggio_id": "casa", "check_in": "2026-09-01",
                         "check_out": "2026-09-03"})
        return r.corpo["quote_token"]

    def test_la_quote_e_valida_NELL_ISTANTE_ESATTO_della_scadenza(self):
        """Un preventivo che scade «adesso» dev'essere ancora onorato: rifiutarlo un
        secondo prima significa perdere prenotazioni vere sul filo del TTL."""
        t = {"v": 1000}
        _, _, proto = _setup(unita=1, clock=lambda: t["v"])
        token = self._token(proto)          # exp = 1000 + 900 = 1900
        t["v"] = 1900                        # siamo ESATTAMENTE alla scadenza
        r = proto.prenota({"quote_token": token, "email": "g@x.it"})
        self.assertEqual(r.status, 201)

    def test_la_quote_e_scaduta_UN_SECONDO_DOPO(self):
        t = {"v": 1000}
        _, _, proto = _setup(unita=1, clock=lambda: t["v"])
        token = self._token(proto)
        t["v"] = 1901
        r = proto.prenota({"quote_token": token, "email": "g@x.it"})
        self.assertEqual(r.status, 410)

    def test_una_scadenza_NON_INTERA_e_trattata_come_scaduta(self):
        inv, cat, _ = _setup(unita=1)
        proto = ProtocolloConcierge(inv, FirmaQuote(SEGRETO), catalogo=cat)
        token = FirmaQuote(SEGRETO).codifica(
            {"alloggio_id": "casa", "check_in": "2026-09-01", "check_out": "2026-09-03",
             "exp": "domani", "prezzo_guest_cents": 20000})
        r = proto.prenota({"quote_token": token, "email": "g@x.it"})
        self.assertEqual(r.status, 410)
        self.assertEqual(r.corpo["errore"], "quote_scaduta")

    def test_un_esito_SENZA_il_campo_ok_non_conferma(self):
        """Se l'inventario cambiasse e restituisse un oggetto senza `ok`, un valore di
        comodo trasformerebbe un rifiuto in una conferma: stanza venduta due volte."""
        class _EsitoMuto:
            pass

        proto = ProtocolloConcierge(_InventarioFinto(esito=_EsitoMuto()),
                                    FirmaQuote(SEGRETO))
        r = proto.prenota({"quote_token": self._token(proto), "email": "g@x.it"})
        self.assertEqual(r.status, 422)
        self.assertEqual(r.corpo["stato"], "rifiutata")

    def test_un_esito_SENZA_il_campo_idempotente_NON_e_un_replay(self):
        """`idempotente: True` dice al chiamante «questa prenotazione l'avevi gia'»:
        dichiararlo per difetto farebbe scartare una prenotazione NUOVA come doppione."""
        class _EsitoOk:
            ok = True
            motivo = ""

        proto = ProtocolloConcierge(_InventarioFinto(esito=_EsitoOk()), FirmaQuote(SEGRETO))
        r = proto.prenota({"quote_token": self._token(proto), "email": "g@x.it"})
        self.assertEqual(r.status, 201)
        self.assertIs(r.corpo["idempotente"], False)

    def test_il_MOTIVO_del_rifiuto_sceglie_il_codice_giusto(self):
        """409 = «riprova con altre date» (la stanza e' occupata); 422 = «la richiesta e'
        sbagliata». Scambiarli manda un agente esterno a insistere su una via chiusa."""
        for motivo, atteso in (("pieno", 409), ("chiuso", 409), ("min_notti", 409),
                               ("giorno_non_caricato", 409), ("date_non_valide", 422)):
            proto = ProtocolloConcierge(
                _InventarioFinto(esito=EsitoPrenotazione(False, motivo)),
                FirmaQuote(SEGRETO))
            r = proto.prenota({"quote_token": self._token(proto), "email": "g@x.it"})
            self.assertEqual(r.status, atteso, "motivo %r" % motivo)
            self.assertEqual(r.corpo["motivo"], motivo)

    def test_il_blocco_in_avaria_LASCIA_LA_TRACCIA(self):
        proto = ProtocolloConcierge(_InventarioFinto(blocca_esplode=True), FirmaQuote(SEGRETO))
        token = self._token(proto)
        with self.assertLogs(LOGGER, level="ERROR") as log:
            r = proto.prenota({"quote_token": token, "email": "g@x.it"})
        self.assertEqual(r.status, 503)
        rec = _traccia(log, "prenota: blocco ISOLATO fallito")
        self.assertIsNotNone(rec)
        self.assertIsInstance(rec.exc_info, tuple,
                              "il log non porta la traccia dell'eccezione")

    def test_un_token_SENZA_totale_addebita_il_soggiorno(self):
        """Preventivi firmati prima che esistesse la tassa di soggiorno non hanno
        `totale_cents`: devono restare pagabili, addebitando il solo soggiorno."""
        visti = []
        inv, cat, _ = _setup(unita=1)
        proto = ProtocolloConcierge(
            inv, FirmaQuote(SEGRETO), catalogo=cat,
            link_pagamento=lambda d: visti.append(d) or "https://pay/x")
        token = FirmaQuote(SEGRETO).codifica(
            {"alloggio_id": "casa", "check_in": "2026-09-01", "check_out": "2026-09-03",
             "exp": FUTURO, "prezzo_guest_cents": 20000})
        r = proto.prenota({"quote_token": token, "email": "g@x.it"})
        self.assertEqual(r.status, 201)
        self.assertEqual(visti[0]["totale_cents"], 20000)

    def test_un_token_con_totale_ZERO_addebita_il_soggiorno(self):
        """Uno zero non e' un totale: addebitarlo significa consegnare il soggiorno
        gratis con tutti i controlli verdi."""
        visti = []
        inv, cat, _ = _setup(unita=1)
        proto = ProtocolloConcierge(
            inv, FirmaQuote(SEGRETO), catalogo=cat,
            link_pagamento=lambda d: visti.append(d) or "https://pay/x")
        token = FirmaQuote(SEGRETO).codifica(
            {"alloggio_id": "casa", "check_in": "2026-09-01", "check_out": "2026-09-03",
             "exp": FUTURO, "prezzo_guest_cents": 20000, "totale_cents": 0})
        r = proto.prenota({"quote_token": token, "email": "g@x.it"})
        self.assertEqual(r.status, 201)
        self.assertEqual(visti[0]["totale_cents"], 20000)


class TestGatewayInAvaria(unittest.TestCase):
    """Il fail-safe «Stripe giu' = soggiorno gratis»: gateway CONFIGURATO ma senza link
    -> si rilascia la stanza e si risponde 503. Provato in ogni suo pezzo."""

    def _token(self, proto):
        return proto.quota({"alloggio_id": "casa", "check_in": "2026-09-01",
                            "check_out": "2026-09-03"}).corpo["quote_token"]

    def test_il_503_dice_esplicitamente_di_RIPROVARE(self):
        inv, cat, _ = _setup(unita=1)
        proto = ProtocolloConcierge(inv, FirmaQuote(SEGRETO), catalogo=cat,
                                    link_pagamento=lambda d: None)
        r = proto.prenota({"quote_token": self._token(proto), "email": "g@x.it"})
        self.assertEqual(r.status, 503)
        self.assertIs(r.corpo["riprova"], True)

    def test_un_link_che_NON_E_UNA_STRINGA_e_un_guasto_non_un_link(self):
        """Senza il controllo di tipo, un gateway che risponde un numero manderebbe
        l'ospite su un `payment_url` inesistente con la prenotazione gia' confermata."""
        inv, cat, _ = _setup(unita=1)
        proto = ProtocolloConcierge(inv, FirmaQuote(SEGRETO), catalogo=cat,
                                    link_pagamento=lambda d: 12345)
        r = proto.prenota({"quote_token": self._token(proto), "email": "g@x.it"})
        self.assertEqual(r.status, 503)
        self.assertEqual(r.corpo["errore"], "pagamento_non_disponibile")

    def test_un_link_che_SOLLEVA_lascia_la_traccia(self):
        def boom(dati):
            raise RuntimeError("psp giu'")

        inv, cat, _ = _setup(unita=1)
        proto = ProtocolloConcierge(inv, FirmaQuote(SEGRETO), catalogo=cat,
                                    link_pagamento=boom)
        token = self._token(proto)
        with self.assertLogs(LOGGER, level="WARNING") as log:
            r = proto.prenota({"quote_token": token, "email": "g@x.it"})
        self.assertEqual(r.status, 503)
        rec = _traccia(log, "link pagamento fallito (ignorato)")
        self.assertIsNotNone(rec)
        self.assertIsInstance(rec.exc_info, tuple,
                              "il log non porta la traccia dell'eccezione")

    def test_il_RILASCIO_fallito_lascia_la_traccia(self):
        """La stanza non e' tornata vendibile: e' il caso peggiore del fail-safe, e
        senza la traccia nessuno sapra' MAI perche' quella stanza e' rimasta bloccata."""
        inv = _InventarioFinto(esito=EsitoPrenotazione(True, ""), rilascia_esplode=True)
        proto = ProtocolloConcierge(inv, FirmaQuote(SEGRETO), link_pagamento=lambda d: None)
        token = proto.quota({"alloggio_id": "casa", "check_in": "2026-09-01",
                             "check_out": "2026-09-03"}).corpo["quote_token"]
        with self.assertLogs(LOGGER, level="ERROR") as log:
            r = proto.prenota({"quote_token": token, "email": "g@x.it"})
        self.assertEqual(r.status, 503)
        self.assertEqual(inv.rilasci, 1)
        rec = _traccia(log, "prenota: rilascio dopo link fallito ISOLATO")
        self.assertIsNotNone(rec)
        self.assertIsInstance(rec.exc_info, tuple,
                              "il log non porta la traccia dell'eccezione")


class TestDettaglioInAvaria(unittest.TestCase):
    def test_dettaglio_in_avaria_LASCIA_LA_TRACCIA(self):
        class _CatRotto:
            def dettaglio(self, slug):
                raise RuntimeError("catalogo giu'")

        proto = ProtocolloConcierge(crea_channel_manager(), FirmaQuote(SEGRETO),
                                    catalogo=_CatRotto())
        with self.assertLogs(LOGGER, level="ERROR") as log:
            r = proto.dettaglio({"alloggio_id": "casa"})
        self.assertEqual(r.status, 503)
        rec = _traccia(log, "dettaglio: eccezione ISOLATA")
        self.assertIsNotNone(rec)
        self.assertIsInstance(rec.exc_info, tuple,
                              "il log non porta la traccia dell'eccezione")


class TestRotteConcierge(unittest.TestCase):
    """Le tre rotte Flask. `silent=True` significa: un corpo illeggibile diventa `None` e
    lo giudica IL NOSTRO protocollo, con la nostra risposta JSON. Senza, risponderebbe
    Flask con una pagina d'errore -- e un agente esterno riceverebbe HTML dove il
    protocollo promette JSON."""

    def _client(self):
        from flask import Flask
        from fase59_concierge import registra_concierge
        _, _, proto = _setup(unita=1)
        app = Flask("collaudo_concierge")
        registra_concierge(app, proto)
        return app.test_client()

    def test_un_corpo_ILLEGGIBILE_riceve_la_NOSTRA_risposta_JSON(self):
        cli = self._client()
        for rotta in ("/concierge/search", "/concierge/quote", "/concierge/book"):
            resp = cli.post(rotta, data="questo-non-e-json",
                            content_type="text/plain")
            self.assertEqual(resp.status_code, 400, rotta)
            corpo = resp.get_json()
            self.assertIsNotNone(corpo, "%s: la risposta non e' JSON" % rotta)
            self.assertEqual(corpo["errore"], "payload_non_oggetto", rotta)

    def test_il_manifest_risponde_dalla_rotta(self):
        resp = self._client().get("/concierge/manifest")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["money_unit"], "cents_integer")


class TestSegretoDellaFirma(unittest.TestCase):
    def test_un_segreto_di_SEDICI_byte_e_ACCETTATO(self):
        """Il confine dichiarato e' «almeno 16 byte». Rifiutare proprio il 16 renderebbe
        impossibile la configurazione minima che la macchina promette di accettare, e il
        guasto si vedrebbe solo il giorno del primo avvio con quella chiave."""
        FirmaQuote(b"0123456789abcdef")             # 16 byte esatti: deve passare
        with self.assertRaises(ValueError):
            FirmaQuote(b"0123456789abcde")          # 15: uno in meno, deve rifiutare


class TestIngressiDiQuota(unittest.TestCase):
    """Le quattro porte d'ingresso di `quota`. Ognuna deve rispondere con IL SUO errore:
    un agente esterno decide cosa fare dopo leggendo proprio quello."""

    def test_senza_alloggio_id_e_400(self):
        _, _, proto = _setup()
        r = proto.quota({"check_in": "2026-09-01", "check_out": "2026-09-03"})
        self.assertEqual(r.status, 400)
        self.assertEqual(r.corpo["errore"], "alloggio_id_non_valido")

    def test_senza_check_in_e_400_DATE_MANCANTI(self):
        _, _, proto = _setup()
        r = proto.quota({"alloggio_id": "casa", "check_out": "2026-09-03"})
        self.assertEqual(r.status, 400)
        self.assertEqual(r.corpo["errore"], "date_mancanti")

    def test_senza_check_out_e_400_DATE_MANCANTI(self):
        _, _, proto = _setup()
        r = proto.quota({"alloggio_id": "casa", "check_in": "2026-09-01"})
        self.assertEqual(r.status, 400)
        self.assertEqual(r.corpo["errore"], "date_mancanti")

    def test_un_party_NON_VALIDO_e_sempre_400(self):
        """`True` e `2.0` sembrano numeri e non lo sono: senza il controllo di tipo
        finirebbero firmati dentro il preventivo."""
        _, _, proto = _setup()
        for party in ("tre", 0, -1, 51, True, 2.0, None):
            r = proto.quota({"alloggio_id": "casa", "check_in": "2026-09-01",
                             "check_out": "2026-09-03", "party": party})
            self.assertEqual(r.status, 400, repr(party))
            self.assertEqual(r.corpo["errore"], "party_non_valido", repr(party))

    def test_senza_fonte_la_fonte_e_MARKETPLACE(self):
        """La fonte decide la commissione (5% sul link diretto, scaglione sul
        marketplace): lasciarla vuota significa firmare un preventivo senza sapere
        quanto prendiamo."""
        _, _, proto = _setup()
        r = proto.quota({"alloggio_id": "casa", "check_in": "2026-09-01",
                         "check_out": "2026-09-03"})
        self.assertEqual(r.corpo["fonte"], "marketplace")


class TestAnnuncioVendibile(unittest.TestCase):
    def test_uno_slug_SCONOSCIUTO_non_e_quotabile(self):
        """Un annuncio sospeso o inesistente non e' vendibile nemmeno con lo slug in mano:
        e' il difetto gia' provato per cui la sospensione nascondeva dalla ricerca ma non
        bloccava le vendite."""
        _, _, proto = _setup()
        r = proto.quota({"alloggio_id": "mai-esistito", "check_in": "2026-09-01",
                         "check_out": "2026-09-03"})
        self.assertEqual(r.status, 404)
        self.assertEqual(r.corpo["errore"], "alloggio_non_disponibile")

    def test_un_catalogo_in_avaria_NON_blocca_tutte_le_vendite(self):
        """Fail-open DICHIARATO: un errore transitorio del catalogo non deve fermare ogni
        prenotazione della macchina. L'inventario resta la guardia vera."""
        class _CatRotto:
            def dettaglio(self, slug):
                raise RuntimeError("catalogo giu'")

        inv = crea_channel_manager()
        inv.imposta_disponibilita("casa", "2026-09-01", unita_totali=1,
                                  prezzo_netto_cents=10000)
        proto = ProtocolloConcierge(inv, FirmaQuote(SEGRETO), catalogo=_CatRotto())
        r = proto.quota({"alloggio_id": "casa", "check_in": "2026-09-01",
                         "check_out": "2026-09-02"})
        self.assertEqual(r.status, 200)


class TestPoliticaCancellazione(unittest.TestCase):
    def test_la_politica_NON_RIMBORSABILE_sconta_il_DODICI_per_cento(self):
        """Scambio onesto finanziato dall'HOST: niente rimborso, ma si paga meno. Se il
        ramo non scatta, l'ospite rinuncia al rimborso E paga pieno -- ci rimette solo lui."""
        inv = crea_channel_manager()
        for g in GIORNI:
            inv.imposta_disponibilita("casa", g, unita_totali=1, prezzo_netto_cents=10000)
        cat = crea_catalogo(disponibilita=inv.disponibile)
        cat.pubblica(SchedaAlloggio(host_id="h", slug="casa", titolo="Casa", citta="Roma",
                                    prezzo_notte_cents=10000, capacita=4,
                                    politica_cancellazione="non_rimborsabile"))
        proto = ProtocolloConcierge(inv, FirmaQuote(SEGRETO), catalogo=cat)
        r = proto.quota({"alloggio_id": "casa", "check_in": "2026-09-01",
                         "check_out": "2026-09-03"})
        self.assertEqual(r.status, 200)
        self.assertEqual(r.corpo["sconto_non_rimborsabile_cents"], 2400)   # 12% di 20000
        self.assertEqual(r.corpo["prezzo_guest_cents"], 17600)


def _setup_valuta(valuta_annuncio, *, psp_bps=0, psp_estera=0, tasso=None):
    """Un alloggio prezzato in `valuta_annuncio` (like-for-like) con le tariffe carta."""
    inv = crea_channel_manager()
    inv.imposta_disponibilita("casa", "2026-09-01", unita_totali=1,
                              prezzo_netto_cents=10000)
    cat = crea_catalogo(disponibilita=inv.disponibile)
    cat.pubblica(SchedaAlloggio(host_id="h", slug="casa", titolo="Casa", citta="Roma",
                                prezzo_notte_cents=10000, capacita=4,
                                valuta=valuta_annuncio))
    return ProtocolloConcierge(inv, FirmaQuote(SEGRETO), catalogo=cat,
                               psp_bps=psp_bps, psp_bps_valuta_estera=psp_estera,
                               tasso_cambio=tasso)


class TestCostoDellaCarta(unittest.TestCase):
    """Il costo della carta e' a carico dell'HOST e copre Stripe: sbagliarlo ci mette
    SOTTO COSTO su ogni prenotazione, in silenzio. E' gia' successo (tariffa 3% secca)."""

    def _quota(self, proto):
        return proto.quota({"alloggio_id": "casa", "check_in": "2026-09-01",
                            "check_out": "2026-09-02"})

    def test_la_tariffa_DIPENDE_dalla_valuta_dell_annuncio(self):
        """5% in euro, 7% se l'annuncio e' in altra valuta (Stripe converte, +2%).
        Scambiare i due rami e' la perdita perfetta: nessun test la vede, i conti tornano."""
        for valuta, atteso in (("EUR", 500), ("JPY", 700)):
            r = self._quota(_setup_valuta(valuta, psp_bps=500, psp_estera=700))
            self.assertEqual(r.corpo["valuta"], valuta)
            self.assertEqual(r.corpo["costo_pagamento_cents"], atteso, valuta)

    def test_la_tariffa_estera_NON_IMPOSTATA_ricade_su_quella_normale(self):
        """Se nessuno imposta la tariffa estera si usa quella normale: azzerarla
        significherebbe pagare NOI la conversione di Stripe."""
        r = self._quota(_setup_valuta("JPY", psp_bps=500))
        self.assertEqual(r.corpo["valuta"], "JPY")
        self.assertEqual(r.corpo["costo_pagamento_cents"], 500)

    def test_una_quota_fissa_NON_INTERA_non_e_una_quota(self):
        inv, cat, _ = _setup(unita=1)
        for fisso in (True, 25.5, "25", None):
            proto = ProtocolloConcierge(inv, FirmaQuote(SEGRETO), catalogo=cat,
                                        psp_fisso_cents=fisso)
            r = proto.quota({"alloggio_id": "casa", "check_in": "2026-09-01",
                             "check_out": "2026-09-03"})
            self.assertEqual(r.corpo["costo_pagamento_cents"], 0, repr(fisso))

    def test_il_preventivo_REGGE_quando_il_costo_carta_pareggia_l_incasso(self):
        """Confine: se all'host resta ESATTAMENTE quanto costa la carta, nessuno ci
        rimette e il preventivo e' valido. Rifiutarlo un centesimo prima significa
        buttare via prenotazioni buone."""
        inv = crea_channel_manager()
        inv.imposta_disponibilita("casa", "2026-09-01", unita_totali=1,
                                  prezzo_netto_cents=10000)
        proto = ProtocolloConcierge(inv, FirmaQuote(SEGRETO),
                                    commissione=lambda netto: 7000,
                                    psp_bps=2000, psp_fisso_cents=1000)
        r = proto.quota({"alloggio_id": "casa", "check_in": "2026-09-01",
                         "check_out": "2026-09-02"})
        self.assertEqual(r.status, 200)
        self.assertEqual(r.corpo["costo_pagamento_cents"], 3000)   # tetto sul totale + quota fissa
        self.assertEqual(r.corpo["netto_host_cents"], 0)

    def test_se_all_host_NON_BASTA_il_preventivo_e_rifiutato(self):
        inv = crea_channel_manager()
        inv.imposta_disponibilita("casa", "2026-09-01", unita_totali=1,
                                  prezzo_netto_cents=10000)
        proto = ProtocolloConcierge(inv, FirmaQuote(SEGRETO),
                                    commissione=lambda netto: 7001,
                                    psp_bps=2000, psp_fisso_cents=1000)
        r = proto.quota({"alloggio_id": "casa", "check_in": "2026-09-01",
                         "check_out": "2026-09-02"})
        self.assertEqual(r.status, 422)
        self.assertEqual(r.corpo["errore"], "prezzo_non_sostenibile")


class TestCambioIndicativo(unittest.TestCase):
    """La stima «≈ nella tua moneta» e' solo display: l'addebito resta nella valuta
    dell'annuncio. Ma una stima sbagliata fa dubitare del prezzo vero."""

    def _quota(self, proto, **extra):
        richiesta = {"alloggio_id": "casa", "check_in": "2026-09-01",
                     "check_out": "2026-09-02"}
        richiesta.update(extra)
        return proto.quota(richiesta)

    def test_la_stima_nella_valuta_dell_ospite_ARRIVA(self):
        r = self._quota(_setup_valuta("EUR", tasso=lambda da, a: 160),
                        valuta_ospite="JPY")
        self.assertEqual(r.status, 200)
        self.assertEqual(r.corpo["valuta_indicativa"], "JPY")
        self.assertGreater(r.corpo["totale_indicativo_cents"], 0)

    def test_NESSUNA_stima_se_la_valuta_e_LA_STESSA(self):
        """Convertire EUR in EUR non e' una stima: e' rumore che contraddice il prezzo."""
        r = self._quota(_setup_valuta("EUR", tasso=lambda da, a: 160),
                        valuta_ospite="EUR")
        self.assertEqual(r.corpo["totale_indicativo_cents"], 0)
        self.assertEqual(r.corpo["valuta_indicativa"], "")

    def test_il_servizio_dei_cambi_NON_viene_nemmeno_INTERROGATO_senza_richiesta(self):
        """Chi non chiede la stima non deve pagarne il costo: una dipendenza in piu' sul
        percorso del prezzo e' una dipendenza in piu' che puo' cadere."""
        chiamate = []

        def tasso(da, a):
            chiamate.append((da, a))
            return 160

        r = self._quota(_setup_valuta("EUR", tasso=tasso))
        self.assertEqual(r.status, 200)
        self.assertEqual(chiamate, [])
        self.assertEqual(r.corpo["totale_indicativo_cents"], 0)

    def test_un_tasso_ASSENTE_non_fa_inventare_una_stima(self):
        r = self._quota(_setup_valuta("EUR", tasso=lambda da, a: None),
                        valuta_ospite="JPY")
        self.assertEqual(r.corpo["totale_indicativo_cents"], 0)


class TestPavimentoDelCredito(unittest.TestCase):
    """Il pavimento sui costi e' cio' che impedisce a uno sconto di farci perdere denaro.
    E' gia' stato sbagliato una volta (2,9% invece di 3,25%): su 1000 EUR in valuta
    estera lasciava passare 21,50 EUR piu' del suo stesso limite."""

    def test_il_pavimento_usa_la_tariffa_EURO_su_un_annuncio_in_EURO(self):
        t = {"v": 1000}
        _, _, proto = _setup(unita=1, commissione=lambda netto: netto // 10,
                             clock=lambda: t["v"])
        r = proto.quota({"alloggio_id": "casa", "check_in": "2026-09-01",
                         "check_out": "2026-09-03",
                         "credito_token": _credito(100000, FUTURO)})
        # netto 20000 · comm 2000 · costo = 20000*325/10000 + 25 + 200 = 875
        # margine regalabile = 2000 - 875 = 1125, e il credito enorme si ferma li'
        self.assertEqual(r.corpo["sconto_credito_cents"], 1125)

    def test_una_valuta_di_incasso_VUOTA_ricade_su_EURO(self):
        """`valuta=""` e' una configurazione costruibile, e il codice la fa ricadere su
        EUR con `valuta or "EUR"`. Se quel ricadere sparisce succede una di due cose,
        entrambe invisibili: un credito legittimo viene buttato via dalla guardia
        cross-valuta, oppure il pavimento cambia tariffa senza che nessuno lo veda."""
        inv = crea_channel_manager()
        for g in GIORNI:
            inv.imposta_disponibilita("casa", g, unita_totali=1, prezzo_netto_cents=10000)
        proto = ProtocolloConcierge(inv, FirmaQuote(SEGRETO), valuta="",
                                    commissione=lambda netto: netto // 10)
        r = proto.quota({"alloggio_id": "casa", "check_in": "2026-09-01",
                         "check_out": "2026-09-03",
                         "credito_token": _credito(100000, FUTURO)})
        self.assertEqual(r.status, 200)
        # il credito EUR passa la guardia; il pavimento usa 5,25% perche' "EUR" non
        # coincide con la valuta di incasso dichiarata (vuota):
        # costo = 20000*525/10000 + 225 = 1275 -> margine = 2000 - 1275 = 725
        self.assertEqual(r.corpo["sconto_credito_cents"], 725)


class TestTokenCorrotto(unittest.TestCase):
    def test_un_token_FIRMATO_ma_corrotto_nei_tipi_e_RIFIUTATO(self):
        """La firma garantisce che il payload sia NOSTRO, non che sia SANO. Un preventivo
        malformato dev'essere fermato PRIMA di toccare l'inventario, altrimenti blocca
        notti vere con dati che nessuno sa leggere."""
        inv, cat, _ = _setup(unita=1)
        proto = ProtocolloConcierge(inv, FirmaQuote(SEGRETO), catalogo=cat)
        base = {"alloggio_id": "casa", "check_in": "2026-09-01",
                "check_out": "2026-09-03", "exp": FUTURO, "prezzo_guest_cents": 20000}
        for campo, valore in (("alloggio_id", 123), ("check_in", 20260901),
                              ("check_out", None), ("prezzo_guest_cents", "20000")):
            corrotto = dict(base)
            corrotto[campo] = valore
            token = FirmaQuote(SEGRETO).codifica(corrotto)
            r = proto.prenota({"quote_token": token, "email": "g@x.it"})
            self.assertEqual(r.status, 400, campo)
            self.assertEqual(r.corpo["errore"], "quote_corrotta", campo)


class TestConfrontoOTA(unittest.TestCase):
    def test_un_confronto_con_prezzo_ZERO_e_rifiutato(self):
        """Zero non e' un prezzo: un confronto su zero produce un «risparmio» inventato,
        ed e' una cifra pubblica che finisce davanti a un host."""
        _, _, proto = _setup()
        r = proto.confronto({"prezzo_cents": 0})
        self.assertEqual(r.status, 400)
        self.assertEqual(r.corpo["errore"], "prezzo_non_valido")


# ═════════════════════════════════════════════════════════════════════════════
# COLLAUDO 5 — ORACOLO INDIPENDENTE
# Un SECONDO calcolo, scritto separatamente e per un'altra strada: il motore fa le
# percentuali con l'intero (`x * bps // 10000`), l'oracolo con i RAZIONALI ESATTI e poi
# tronca. Se i due coincidono su casi annidati, la catena dei soldi non ha un errore di
# arrotondamento nascosto; se divergono, uno dei due mente e si va a vedere quale.
# ═════════════════════════════════════════════════════════════════════════════
def _oracolo(prezzi_notte, *, sett_bps=0, mese_bps=0, non_rimborsabile=False,
             comm_bps=0, tassa=0, psp_bps=0, psp_fisso=0):
    from fractions import Fraction

    def perc(importo, bps):
        return int(Fraction(importo, 1) * Fraction(bps, 10000))

    n = len(prezzi_notte)
    listino = sum(prezzi_notte)
    if n >= 28 and mese_bps > 0:
        bps = mese_bps
    elif n >= 7 and sett_bps > 0:
        bps = sett_bps
    else:
        bps = 0
    sconto_lungo = perc(listino, bps)
    netto = listino - sconto_lungo
    sconto_nr = perc(netto, 1200) if non_rimborsabile else 0
    netto = netto - sconto_nr
    comm = min(max(perc(netto, comm_bps), 0), netto)
    netto_host = netto - comm
    guest = netto
    totale = guest + tassa
    costo = perc(totale, psp_bps) + (psp_fisso if totale > 0 else 0)
    return {"prezzo_listino_cents": listino,
            "sconto_soggiorno_lungo_cents": sconto_lungo,
            "sconto_non_rimborsabile_cents": sconto_nr,
            "prezzo_netto_cents": netto,
            "commissione_cents": comm,
            "prezzo_guest_cents": guest,
            "tassa_soggiorno_cents": tassa,
            "totale_cents": totale,
            "costo_pagamento_cents": costo,
            "netto_host_cents": max(0, netto_host - costo)}


def _proto_completo(quante_notti, *, sett_bps=0, mese_bps=0, politica="flessibile",
                    comm_bps=0, tassa=0, psp_bps=0, psp_fisso=0, prezzo=10000):
    inv = crea_channel_manager()
    for g in _giorni(quante_notti):
        inv.imposta_disponibilita("casa", g, unita_totali=1, prezzo_netto_cents=prezzo)
    cat = crea_catalogo(disponibilita=inv.disponibile)
    cat.pubblica(SchedaAlloggio(host_id="h", slug="casa", titolo="Casa", citta="Roma",
                                prezzo_notte_cents=prezzo, capacita=8,
                                politica_cancellazione=politica,
                                sconto_settimana_bps=sett_bps, sconto_mese_bps=mese_bps))
    proto = ProtocolloConcierge(
        inv, FirmaQuote(SEGRETO), catalogo=cat,
        commissione=lambda netto: netto * comm_bps // 10000,
        tassa_alloggio=(lambda slug, **kw: tassa) if tassa else None,
        psp_bps=psp_bps, psp_fisso_cents=psp_fisso)
    fine = (datetime.date.fromisoformat("2026-09-01")
            + datetime.timedelta(days=quante_notti)).isoformat()
    return proto, "2026-09-01", fine


class TestOracoloIndipendente(unittest.TestCase):
    """COLLAUDO 5. Ogni caso attraversa la catena INTERA e la confronta, voce per voce,
    con un calcolo scritto a parte. COLLAUDO 4 (neuroni) e' l'ultimo caso: tutti gli
    scaglioni annidati insieme, che nel flusso vero capitano di rado e proprio per questo
    non li guarda nessuno."""

    CASI = (
        ("nudo, due notti", 2, {}),
        ("sette notti, sconto settimana", 7, {"sett_bps": 1000}),
        ("ventotto notti, il mese prevale", 28, {"sett_bps": 1000, "mese_bps": 2000}),
        ("non rimborsabile + commissione", 3, {"politica": "non_rimborsabile",
                                               "comm_bps": 1000}),
        ("tassa + costo carta", 3, {"comm_bps": 1000, "tassa": 900, "psp_bps": 500,
                                    "psp_fisso": 25}),
        # ── NEURONI: tutto insieme, annidato ────────────────────────────────────
        ("NEURONI: mese + non rimborsabile + commissione + tassa + carta", 30,
         {"sett_bps": 1000, "mese_bps": 2000, "politica": "non_rimborsabile",
          "comm_bps": 1000, "tassa": 4200, "psp_bps": 500, "psp_fisso": 25}),
        ("NEURONI al confine dei 28 con arrotondamenti scomodi", 28,
         {"mese_bps": 1333, "politica": "non_rimborsabile", "comm_bps": 777,
          "tassa": 1, "psp_bps": 333, "psp_fisso": 25}),
    )

    def test_il_motore_e_l_oracolo_dicono_LA_STESSA_COSA(self):
        for nome, notti, kw in self.CASI:
            with self.subTest(caso=nome):
                prezzo = kw.get("prezzo", 10000)
                proto, ci, co = _proto_completo(notti, **kw)
                r = proto.quota({"alloggio_id": "casa", "check_in": ci, "check_out": co,
                                 "party": 2})
                self.assertEqual(r.status, 200, nome)
                atteso = _oracolo(
                    [prezzo] * notti,
                    sett_bps=kw.get("sett_bps", 0), mese_bps=kw.get("mese_bps", 0),
                    non_rimborsabile=kw.get("politica") == "non_rimborsabile",
                    comm_bps=kw.get("comm_bps", 0), tassa=kw.get("tassa", 0),
                    psp_bps=kw.get("psp_bps", 0), psp_fisso=kw.get("psp_fisso", 0))
                for campo, valore in sorted(atteso.items()):
                    self.assertEqual(r.corpo[campo], valore,
                                     "%s · %s: motore=%r oracolo=%r"
                                     % (nome, campo, r.corpo[campo], valore))

    def test_i_conti_TORNANO_da_soli(self):
        """L'invariante che nessun oracolo puo' salvare: quello che l'ospite paga
        dev'essere esattamente quello che si spartiscono host, noi e la citta'."""
        for nome, notti, kw in self.CASI:
            with self.subTest(caso=nome):
                proto, ci, co = _proto_completo(notti, **kw)
                c = proto.quota({"alloggio_id": "casa", "check_in": ci,
                                 "check_out": co, "party": 2}).corpo
                self.assertEqual(c["totale_cents"],
                                 c["prezzo_guest_cents"] + c["tassa_soggiorno_cents"], nome)
                self.assertEqual(c["prezzo_netto_cents"],
                                 c["prezzo_listino_cents"]
                                 - c["sconto_soggiorno_lungo_cents"]
                                 - c["sconto_non_rimborsabile_cents"], nome)
                self.assertEqual(c["netto_host_cents"] + c["commissione_cents"]
                                 + c["costo_pagamento_cents"] + c["sconto_credito_cents"],
                                 c["prezzo_guest_cents"], nome)


# ═════════════════════════════════════════════════════════════════════════════
# COLLAUDO 6 — FUZZING, CONCORRENZA, ESTREMI
# ═════════════════════════════════════════════════════════════════════════════
class TestFuzzing(unittest.TestCase):
    """Ingressi assurdi con un seme FISSO: un fuzzing che non si ripete non e' un
    collaudo, e un seme preso dall'orologio e' una bomba a tempo (ne abbiamo gia' pagate
    tredici). Il contratto e' che `quota` e `prenota` NON SOLLEVANO MAI: sono la porta
    d'ingresso di agenti esterni ostili."""

    VALORI = (None, 0, -1, 1, True, False, "", " ", "x", "casa", 2.5, -2.5, [], {},
              [1, 2], {"a": 1}, "a" * 300, "2026-09-01", "2026-13-45", "0000-00-00",
              10 ** 18, -10 ** 18, "casa|x", "\t\n", "EUR", "JPY", 50, 51,
              "../../etc/passwd", "' OR 1=1 --", "\x00")
    CAMPI = ("alloggio_id", "check_in", "check_out", "party", "fonte", "credito_token",
             "valuta_ospite", "quote_token", "email")
    STATI_LECITI = (200, 201, 400, 404, 409, 410, 422, 501, 503)

    def test_quota_e_prenota_NON_SOLLEVANO_MAI_e_i_soldi_restano_INTERI(self):
        import random
        rng = random.Random(20260814)
        _, _, proto = _setup(unita=1)
        for giro in range(600):
            richiesta = {c: rng.choice(self.VALORI) for c in self.CAMPI}
            for fn in (proto.quota, proto.prenota):
                try:
                    r = fn(richiesta)
                except Exception as e:                       # noqa: BLE001
                    self.fail("giro %d · %s ha SOLLEVATO %s: %r\ningresso: %r"
                              % (giro, fn.__name__, type(e).__name__, e, richiesta))
                self.assertIn(r.status, self.STATI_LECITI,
                              "giro %d · %s · ingresso %r" % (giro, fn.__name__, richiesta))
                for chiave, valore in r.corpo.items():
                    if chiave.endswith("_cents"):
                        self.assertIsInstance(valore, int, "%s non e' intero" % chiave)
                        self.assertNotIsInstance(valore, bool, "%s e' un booleano" % chiave)

    def test_scopri_dettaglio_confronto_NON_SOLLEVANO_MAI(self):
        import random
        rng = random.Random(20260815)
        _, _, proto = _setup()
        for _ in range(300):
            richiesta = {c: rng.choice(self.VALORI)
                         for c in ("citta", "prezzo_max_cents", "capacita_min", "servizi",
                                   "check_in", "check_out", "limit", "offset", "ordine",
                                   "alloggio_id", "prezzo_cents", "ota")}
            for fn in (proto.scopri, proto.dettaglio, proto.confronto):
                try:
                    r = fn(richiesta)
                except Exception as e:                       # noqa: BLE001
                    self.fail("%s ha SOLLEVATO %s: %r\ningresso: %r"
                              % (fn.__name__, type(e).__name__, e, richiesta))
                self.assertIn(r.status, self.STATI_LECITI)


class TestEstremi(unittest.TestCase):
    def test_il_tetto_delle_NOTTI_e_rispettato_al_confine(self):
        """366 notti si quotano, 367 no. Il tetto e' anti-abuso: un agente che chiede
        dieci anni non deve poter far calcolare dieci anni di prezzi."""
        inv = crea_channel_manager()
        for g in _giorni(367):
            inv.imposta_disponibilita("casa", g, unita_totali=1, prezzo_netto_cents=100)
        proto = ProtocolloConcierge(inv, FirmaQuote(SEGRETO))
        d0 = datetime.date.fromisoformat("2026-09-01")
        r = proto.quota({"alloggio_id": "casa", "check_in": "2026-09-01",
                         "check_out": (d0 + datetime.timedelta(days=366)).isoformat()})
        self.assertEqual(r.status, 200)
        self.assertEqual(r.corpo["notti"], 366)
        r2 = proto.quota({"alloggio_id": "casa", "check_in": "2026-09-01",
                          "check_out": (d0 + datetime.timedelta(days=367)).isoformat()})
        self.assertEqual(r2.status, 422)
        self.assertEqual(r2.corpo["errore"], "date_non_valide")

    def test_i_confini_del_PARTY_sono_uno_e_cinquanta(self):
        _, _, proto = _setup()
        for party, atteso in ((1, 200), (50, 200), (0, 400), (51, 400)):
            r = proto.quota({"alloggio_id": "casa", "check_in": "2026-09-01",
                             "check_out": "2026-09-03", "party": party})
            self.assertEqual(r.status, atteso, "party=%r" % party)

    def test_check_in_UGUALE_a_check_out_non_e_un_soggiorno(self):
        _, _, proto = _setup()
        r = proto.quota({"alloggio_id": "casa", "check_in": "2026-09-01",
                         "check_out": "2026-09-01"})
        self.assertEqual(r.status, 422)


class TestConcorrenzaQuotaPrenota(unittest.TestCase):
    """COLLAUDO 6, la parte che costa: la CORSA fra due clienti sulla stessa stanza.
    Su file vero (mai `:memory:`), perche' la gara si decide nel lock di SQLite."""

    def test_dieci_giri_di_corsa_su_QUOTA_e_PRENOTA(self):
        import os
        import shutil
        import tempfile
        for rip in range(10):
            d = tempfile.mkdtemp()
            try:
                inv = crea_channel_manager(os.path.join(d, "c%d.db" % rip))
                for g in GIORNI:
                    inv.imposta_disponibilita("casa", g, unita_totali=1,
                                              prezzo_netto_cents=10000)
                proto = ProtocolloConcierge(inv, FirmaQuote(SEGRETO),
                                            commissione=lambda netto: netto // 10)
                esiti, errori = [], []
                lock = threading.Lock()

                def agente(i):
                    try:
                        q = proto.quota({"alloggio_id": "casa", "check_in": "2026-09-01",
                                         "check_out": "2026-09-03", "party": 2})
                        if q.status != 200:
                            with lock:
                                esiti.append(q.status)
                            return
                        b = proto.prenota({"quote_token": q.corpo["quote_token"],
                                           "email": "a%d@x.it" % i})
                        with lock:
                            esiti.append(b.status)
                    except Exception as e:                   # noqa: BLE001
                        with lock:
                            errori.append("%s: %r" % (type(e).__name__, e))

                th = [threading.Thread(target=agente, args=(i,)) for i in range(24)]
                for t in th:
                    t.start()
                for t in th:
                    t.join()
                self.assertEqual(errori, [], "giro %d: eccezioni durante la corsa" % rip)
                self.assertEqual(sum(1 for s in esiti if s == 201), 1,
                                 "giro %d: attesa UNA sola conferma, esiti %r" % (rip, esiti))
                self.assertEqual(inv.stato_giorno("casa", "2026-09-01")["unita_occupate"], 1)
            finally:
                shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
