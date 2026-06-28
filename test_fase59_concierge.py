"""
Test Fase 59 - Protocollo Concierge AI (agent-discoverable booking).

Copre: firma HMAC (round-trip + manomissione), manifest, scopri (machine-clean),
quota (prezzo firmato dal CORE, non_disponibile, non_quotabile, date invalide),
prenota (conferma + idempotenza + scadenza + firma rotta + email), la REGOLA D'ORO
(l'agente NON puo' alterare il prezzo: ogni manomissione rompe la firma), e lo stress
concorrente anti-overbooking via protocollo (10x). Usa i veri motori fase57/58.
"""
import base64
import json
import threading
import unittest

from fase57_vetrina import CatalogoVetrina, CriteriRicerca, crea_catalogo, SchedaAlloggio
from fase58_channel_manager import crea_channel_manager
from fase59_concierge import (
    FirmaQuote, ProtocolloConcierge, crea_protocollo,
)

SEGRETO = b"0123456789abcdef0123456789abcdef"
GIORNI = ("2026-09-01", "2026-09-02", "2026-09-03")


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

    def test_link_pagamento_che_solleva_non_rompe(self):
        inv, cat, _ = _setup(unita=1)
        def boom(_):
            raise RuntimeError("psp giu'")
        proto = ProtocolloConcierge(inv, FirmaQuote(SEGRETO), catalogo=cat,
                                    link_pagamento=boom)
        r = proto.quota({"alloggio_id": "casa", "check_in": "2026-09-01",
                         "check_out": "2026-09-03"})
        rb = proto.prenota({"quote_token": r.corpo["quote_token"], "email": "g@x.it"})
        self.assertEqual(rb.status, 201)      # prenotazione valida nonostante PSP giu'
        self.assertNotIn("payment_url", rb.corpo)


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


if __name__ == "__main__":
    unittest.main()
