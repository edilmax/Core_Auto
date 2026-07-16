"""Test collaudo — le prove-foto non devono poter riempire il disco (= sito giu').

BUG trovato in collaudo 2026-07-15: `_salva_foto_raw` limitava 5MB **per FILE** ma NESSUNO
limitava il NUMERO. Con UNA sola prenotazione valida (voucher firmato) si potevano caricare
foto all'infinito: 44GB liberi / 5MB = ~9000 file -> disco pieno -> SQLite non riesce piu' a
scrivere -> TUTTO il sito si ferma. Non serve nemmeno un malintenzionato: basta un client con
un ciclo sbagliato che ritenta.

FIX: tetto `MAX_PROVE_FOTO` per prenotazione, controllato PRIMA di scrivere su disco (se si e'
oltre non si salva affatto: il punto e' non consumare spazio, non solo rifiutare il messaggio).
"""
from __future__ import annotations

import base64
import json
import unittest

from fase57_vetrina import SchedaAlloggio
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import MAX_PROVE_FOTO, crea_router

PNG_MINIMO = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 200).decode()


class TestTettoProveFoto(unittest.TestCase):

    def setUp(self):
        self.sys = crea_sistema(ConfigCasaVIP(abilitato=True, segreto_hmac=b"0" * 32))
        self.sys.catalogo.pubblica(SchedaAlloggio(
            host_id="h", slug="casa-x", titolo="T", citta="Roma",
            prezzo_notte_cents=10000, capacita=2))
        for g in (1, 2):
            self.sys.inventario.imposta_disponibilita(
                "casa-x", "2026-09-0%d" % g, unita_totali=1, prezzo_netto_cents=10000)
        self.r = crea_router(self.sys)
        _, q = self.r.gestisci("POST", "/api/concierge/quote", body=json.dumps(
            {"alloggio_id": "casa-x", "check_in": "2026-09-01", "check_out": "2026-09-02"}))
        _, b = self.r.gestisci("POST", "/api/concierge/book", body=json.dumps(
            {"quote_token": q["quote_token"], "email": "g@x.it"}))
        self.vt = b.get("voucher_token")
        self.assertTrue(self.vt, "serve un voucher per il test")

    def _carica(self, img=PNG_MINIMO):
        return self.r.gestisci("POST", "/api/voucher/prova", body=json.dumps(
            {"voucher_token": self.vt, "image_base64": img}))[0]

    def test_tetto_per_prenotazione(self):
        esiti = [self._carica() for _ in range(MAX_PROVE_FOTO + 4)]
        self.assertEqual(esiti.count(201), MAX_PROVE_FOTO,
                         "caricate %d foto invece di %d" % (esiti.count(201), MAX_PROVE_FOTO))
        self.assertEqual(esiti.count(429), 4, "oltre il tetto deve rispondere 429")

    def test_una_controversia_vera_non_e_ostacolata(self):
        """10 foto sono abbondanti per una contestazione reale: le prime devono passare."""
        for i in range(MAX_PROVE_FOTO):
            self.assertEqual(self._carica(), 201, "bloccata la foto n.%d (tetto=%d)"
                             % (i + 1, MAX_PROVE_FOTO))

    def test_voucher_non_valido_non_scrive(self):
        st = self.r.gestisci("POST", "/api/voucher/prova", body=json.dumps(
            {"voucher_token": "finto.token", "image_base64": PNG_MINIMO}))[0]
        self.assertEqual(st, 400, "un voucher finto non deve poter caricare nulla")

    def test_formato_non_immagine_respinto(self):
        """Difesa gia' esistente (magic bytes): qui si verifica che regga ancora."""
        html = base64.b64encode(b"<html><script>alert(1)</script></html>").decode()
        self.assertEqual(self._carica(html), 422)


if __name__ == "__main__":
    unittest.main()
