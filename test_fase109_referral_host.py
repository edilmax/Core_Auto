"""Test Fase 109 - Referral host-porta-host. Puro + durevole; nessuna rete."""
import logging
import os
import shutil
import tempfile
import unittest
from unittest import mock

from fase109_referral_host import ReferralHost, crea_referral_host

SEG = b"r" * 32


class TestReferral(unittest.TestCase):
    def setUp(self):
        self.r = crea_referral_host(SEG)

    def test_flusso_bonus(self):
        cod = self.r.genera_codice("hostA")
        self.assertTrue(self.r.registra_referral(cod, "hostB"))
        self.assertEqual(self.r.crediti("hostA"), 0)        # non ancora qualificato
        bonus = self.r.conferma_qualifica("hostB")
        self.assertEqual(bonus, 1000)                       # 1° referral -> tier 1
        self.assertEqual(self.r.crediti("hostA"), 1000)

    def test_anti_auto_referral(self):
        cod = self.r.genera_codice("hostA")
        self.assertFalse(self.r.registra_referral(cod, "hostA"))

    def test_dedup_referee(self):
        cod = self.r.genera_codice("hostA")
        self.assertTrue(self.r.registra_referral(cod, "hostB"))
        self.assertFalse(self.r.registra_referral(cod, "hostB"))

    def test_codice_falso_rifiutato(self):
        self.assertFalse(self.r.registra_referral("token.finto.xxx", "hostB"))

    def test_qualifica_idempotente(self):
        cod = self.r.genera_codice("hostA")
        self.r.registra_referral(cod, "hostB")
        self.assertEqual(self.r.conferma_qualifica("hostB"), 1000)
        self.assertEqual(self.r.conferma_qualifica("hostB"), 0)   # già qualificato
        self.assertEqual(self.r.crediti("hostA"), 1000)

    def test_scaglioni_crescenti(self):
        cod = self.r.genera_codice("hostA")
        for i in range(4):                                  # 4 referee qualificati
            self.r.registra_referral(cod, "h%d" % i)
            self.r.conferma_qualifica("h%d" % i)
        # 1..3 -> 1000 ciascuno; 4° -> 1500
        self.assertEqual(self.r.crediti("hostA"), 1000 * 3 + 1500)

    def test_credito_non_cashabile_uso(self):
        cod = self.r.genera_codice("hostA")
        self.r.registra_referral(cod, "hostB")
        self.r.conferma_qualifica("hostB")
        self.assertEqual(self.r.usa_credito("hostA", 600), 600)
        self.assertEqual(self.r.crediti("hostA"), 400)
        self.assertEqual(self.r.usa_credito("hostA", 9999), 400)   # cap al disponibile
        self.assertEqual(self.r.crediti("hostA"), 0)

    def test_durevole(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "ref.json")
        r1 = ReferralHost(SEG, p)
        cod = r1.genera_codice("hostA")
        r1.registra_referral(cod, "hostB")
        r1.conferma_qualifica("hostB")
        self.assertEqual(ReferralHost(SEG, p).crediti("hostA"), 1000)
        os.remove(p)
        os.rmdir(d)


# ═══════════════════════════════════════════════════════════════════════════════════════
# I 4 PUNTI SOPRAVVISSUTI DELLA NOTTE FRA IL 6 E IL 7 SETTEMBRE 2026 (Giudice, Blocco 7)
# ═══════════════════════════════════════════════════════════════════════════════════════

class TestI4PuntiSopravvissutiDellaNotteDel7Settembre(unittest.TestCase):
    """Il Giudice (giudice_notte_blocchi_4_7) ha trovato 4 punti in cui il guasto passa e i
    test restano verdi: il file temporaneo che nasce ALTROVE rispetto al file (e allora
    `os.replace` non e' piu' atomico, o fallisce fra due volumi), la scrittura fallita
    senza traccia, il conteggio dei referee qualificati che mescola i referrer (bonus
    di scaglione sbagliato: soldi), e una scrittura su disco per un credito di zero.
    UNA guardia per punto, vista ROSSA col mutante iniettato con l'editor."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)

    # ── riga 48: il temporaneo nasce ACCANTO al file, non nella cartella corrente ───
    def test_riga48_il_file_temporaneo_nasce_nella_cartella_del_file(self):
        percorso = os.path.join(self.d, "referral.json")
        r = crea_referral_host(SEG, percorso)
        with mock.patch.object(tempfile, "mkstemp", wraps=tempfile.mkstemp) as mk:
            self.assertTrue(r.registra_referral(r.genera_codice("hostA"), "hostB"))
        self.assertEqual(1, mk.call_count)
        self.assertEqual(self.d, mk.call_args.kwargs.get("dir"),
                         "il temporaneo e' nato in %r invece che accanto al file"
                         % (mk.call_args.kwargs.get("dir"),))
        self.assertTrue(os.path.exists(percorso))
        self.assertEqual([], [f for f in os.listdir(self.d) if f.endswith(".tmp")])

    # ── riga 58: una scrittura fallita grida WARNING con la traccia ────────────────
    def test_riga58_una_scrittura_fallita_grida_WARNING_con_la_traccia(self):
        percorso = os.path.join(self.d, "cartella_che_non_esiste", "referral.json")
        r = crea_referral_host(SEG, percorso)
        with self.assertLogs("core_auto.referral_host", level="WARNING") as cm:
            r.registra_referral(r.genera_codice("hostA"), "hostB")
        self.assertEqual(1, len(cm.records))
        rec = cm.records[0]
        self.assertEqual(logging.WARNING, rec.levelno)
        self.assertIsInstance(rec.exc_info, tuple, "la scrittura fallita non lascia la traccia")
        self.assertTrue(issubclass(rec.exc_info[0], OSError), repr(rec.exc_info[0]))

    # ── riga 93: si contano SOLO i qualificati DI QUEL referrer ────────────────────
    def test_riga93_lo_scaglione_conta_solo_i_referee_qualificati_dello_STESSO_referrer(self):
        r = crea_referral_host(SEG)
        cod_b = r.genera_codice("hostB")
        for i in range(3):                                   # B ha gia' 3 qualificati
            self.assertTrue(r.registra_referral(cod_b, "b%d" % i))
            self.assertEqual(1000, r.conferma_qualifica("b%d" % i))
        cod_a = r.genera_codice("hostA")
        self.assertTrue(r.registra_referral(cod_a, "a0"))
        self.assertTrue(r.registra_referral(cod_a, "a1"))    # a1 resta NON qualificato
        self.assertEqual(1000, r.conferma_qualifica("a0"),
                         "il primo referee di A ha preso lo scaglione di B")
        self.assertEqual(1000, r.crediti("hostA"))
        self.assertEqual(3000, r.crediti("hostB"))

    # ── riga 110: un credito di ZERO non scrive su disco ───────────────────────────
    def test_riga110_usare_un_credito_che_non_c_e_non_scrive_su_disco(self):
        percorso = os.path.join(self.d, "referral.json")
        r = crea_referral_host(SEG, percorso)
        self.assertEqual(0, r.usa_credito("hostZ", 100))
        self.assertFalse(os.path.exists(percorso), "scritto su disco per un credito di zero")
        self.assertEqual(0, r.crediti("hostZ"))


if __name__ == "__main__":
    unittest.main()
