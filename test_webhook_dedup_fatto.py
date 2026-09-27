"""CASELLA 8 del BLOCCO SOLDI, la seconda meta': due Event DIVERSI per lo stesso fatto
contano come UNO.

La prima meta' della casella esiste dal 2026-09-14: lo STESSO evento riconsegnato
(Stesso `evt_id`) non si rifà — l'archivio dice «elaborato» e il gestore risponde
`duplicato`. Ma Stripe può consegnare DUE EVENTI DIVERSI per lo stesso fatto (stesso
tipo, stesso oggetto: un `checkout.session.completed` riemesso con nuovo `evt_id`
dopo un incidente di rete lato Stripe): oggi il secondo evento passa la dedup
dell'identificativo, ripercorre la conferma e conta come un secondo fatto.

⛔ LE GUARDIE NASCONO PRIMA della riparazione (D20) e qui sono VISTE ROSSE sul codice
di produzione di oggi: il secondo evento risponde senza `duplicato` e ripercorre la
conferma. La memoria della dedup dura almeno 3 giorni: la finestra dei ritentativi di
Stripe è 72 ore, e una memoria più corta fa passare il ritentativo del terzo giorno
come evento nuovo (METODO 3.3: è la trappola classica).
"""
import hashlib
import hmac
import json
import shutil
import tempfile
import time
import unittest

from fase204_eventi_stripe import crea_archivio_eventi
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router

SEG = b"h" * 32
HK = {"X-Host-Key": "hk"}
WHSEC = "whsec_test"


class ProviderFinto:
    """Stripe finto al bordo: l'impronta e' una mappa, il rimborso si registra."""

    def __init__(self):
        self.impronte = {}
        self.rimborsi = []

    def impronta_carta(self, pi):
        return self.impronte.get(pi, "")

    def rimborsa(self, pi, importo, chiave):
        self.rimborsi.append((pi, importo, chiave))
        return {"ok": True, "id": "re_test"}

    def stato_sessione(self, cs):
        """La rilettura dello stato (casella 10): qui ogni sessione e' pagata con la carta."""
        return "paid"


class TestDedupPerFatto(unittest.TestCase):
    """e2e di prova: rotte vere, webhook firmato, Stripe finto al bordo."""

    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_viral=f"{d}/v.db", db_messaggi=f"{d}/m.db",
            db_domanda=f"{d}/dom.db", db_garanzia=f"{d}/g.db", db_pendenti=f"{d}/p.db",
            db_tassa_comunale=f"{d}/tc.db", db_eventi_stripe=f"{d}/evt.db",
            db_finanza=f"{d}/fin.db", file_referral=f"{d}/ref.json",
            commissione_bps=1500, stripe_webhook_secret=WHSEC))
        self.sis.concierge._link = lambda dati: "https://pay/" + str(dati.get("riferimento", ""))
        self.sis.stripe = ProviderFinto()
        self.r = crea_router(self.sis, host_key="hk", base_url="https://bookinvip.com")
        self.g("POST", "/api/host/pubblica", {"host_id": "demo", "slug": "casa", "titolo": "C",
               "citta": "Roma", "descrizione": "x", "prezzo_notte_cents": 10000, "capacita": 2,
               "servizi": [], "immagini": [], "tassa_pp_notte_cents": 200}, HK)
        self.g("POST", "/api/host/disponibilita_range", {"alloggio_id": "casa", "da": "2027-02-01",
               "a": "2027-03-31", "unita_totali": 1, "prezzo_netto_cents": 10000}, HK)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def _prenota(self, ci, co, email="o@x.it"):
        _, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": ci, "check_out": co, "party": 2})
        _, b = self.g("POST", "/api/concierge/book", {"quote_token": q["quote_token"],
                                                      "email": email})
        return b["riferimento"]

    def _webhook(self, evt_id, rif, pi, sessione=None):
        payload = json.dumps({"id": evt_id, "type": "checkout.session.completed",
                              "data": {"object": {"metadata": {"riferimento": rif},
                                                  "id": sessione or ("cs_" + pi[3:]),
                                                  "payment_intent": pi}}})
        ts = str(int(time.time()))
        mac = hmac.new(WHSEC.encode(), f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()
        return self.r.gestisci("POST", "/api/payments/webhook", {}, payload,
                               {"Stripe-Signature": "t=%s,v1=%s" % (ts, mac)})

    def incassi(self, rif):
        return [m for m in self.sis.finanza.movimenti(rif) if m.get("tipo") == "incasso"]

    def test_due_eventi_diversi_per_lo_stesso_fatto_contano_UNO(self):
        """Stesso tipo, STESSO oggetto (la sessione di checkout), `evt_id` diverso: il
        secondo evento e' lo stesso fatto che torna, e la risposta lo dichiara
        `duplicato` — non lo si rielabora. L'incasso resta UNO nel giornale."""
        rif = self._prenota("2027-02-10", "2027-02-12")
        s1, c1 = self._webhook("evt_primo", rif, "pi_A")
        self.assertEqual(s1, 200)
        self.assertEqual(self.sis.pagamenti_pendenti.info(rif)["stato"], "pagato",
                         "PREMESSA NON VALIDA: la prima consegna deve confermare")
        quanto_prima = len(self.incassi(rif))
        self.assertGreater(quanto_prima, 0, "PREMESSA NON VALIDA: la conferma incassa")

        s2, c2 = self._webhook("evt_secondo", rif, "pi_A")   # ALTRO evt_id, STESSO fatto
        self.assertEqual(s2, 200, "un duplicato non chiede il ritentativo: %r" % (c2,))
        self.assertEqual(c2.get("duplicato"), True,
                         "DUE EVENTI PER LO STESSO FATTO CONTANO COME DUE: il secondo e' "
                         "stato rielaborato invece di essere riconosciuto. Risposta: %r"
                         % (c2,))
        self.assertEqual(len(self.incassi(rif)), quanto_prima,
                         "il giornale ha PIU' incassi per lo stesso fatto: %r"
                         % (self.incassi(rif),))
        self.assertEqual(self.sis.pagamenti_pendenti.info(rif)["stato"], "pagato")

    def test_fatti_diversi_non_si_bloccano_a_vicenda(self):
        """La dedup guarda il FATTO (tipo + oggetto), non il tipo da solo: due sessioni
        di checkout diverse sono due fatti diversi, e vanno confermate entrambe."""
        rif_a = self._prenota("2027-02-15", "2027-02-17", "a@x.it")
        rif_b = self._prenota("2027-02-20", "2027-02-22", "b@x.it")
        s1, c1 = self._webhook("evt_a", rif_a, "pi_A")
        s2, c2 = self._webhook("evt_b", rif_b, "pi_B")
        self.assertEqual((s1, s2), (200, 200), "%r %r" % (c1, c2))
        self.assertIsNone(c1.get("duplicato"), "un fatto nuovo non e' un duplicato: %r" % (c1,))
        self.assertIsNone(c2.get("duplicato"), "un fatto nuovo non e' un duplicato: %r" % (c2,))
        self.assertEqual(self.sis.pagamenti_pendenti.info(rif_a)["stato"], "pagato")
        self.assertEqual(self.sis.pagamenti_pendenti.info(rif_b)["stato"], "pagato")

    def test_la_memoria_dura_oltre_le_72_ore(self):
        """La finestra dei ritentativi di Stripe e' 72 ore: una memoria della dedup che
        scade prima fa passare il ritentativo del terzo giorno come evento nuovo
        (METODO 3.3). L'archivio non cancella righe: dopo 72 ore e un secondo la
        riconsegna dello stesso fatto e' ancora un duplicato."""
        ora = [1700000000]
        archivio_con_orologio = crea_archivio_eventi(":memory:", orologio=lambda: ora[0])
        archivio_con_orologio.inizializza_schema()
        self.assertTrue(archivio_con_orologio.salva(
            "evt_vecchio", tipo="checkout.session.completed",
            corpo_json=json.dumps({"id": "evt_vecchio", "type": "checkout.session.completed",
                                   "data": {"object": {"id": "cs_vecchio"}}}),
            oggetto_id="cs_vecchio"))
        archivio_con_orologio.segna_elaborato("evt_vecchio")
        ora[0] += 72 * 3600 + 1                    # il ritentativo del TERZO giorno
        self.assertTrue(
            archivio_con_orologio.fatto_gia_presente(tipo="checkout.session.completed",
                                                     oggetto_id="cs_vecchio", evt_id="evt_nuovo"),
            "la memoria della dedup e' scaduta prima della finestra dei ritentativi di "
            "Stripe: il terzo giorno passerebbe come evento nuovo (METODO 3.3)")


if __name__ == "__main__":
    unittest.main()
