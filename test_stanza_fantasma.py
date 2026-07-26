"""GUARDIA — la STANZA FANTASMA si chiude: una notte occupata nell'inventario SENZA una
prenotazione (idem_key non presente fra i pendenti), da un crash fra il blocco e la
registrazione, dev'essere liberata. Lo sweeper degli hold scaduti NON la vede (non c'e' un
pendente da far scadere): resterebbe occupata per sempre = notte invendibile.

Trovata dalla caccia profonda (collaudi/stati_impossibili.py, sonda C). Fix: fase58.orfani (read)
+ fase58.libera_orfani (chiude, idempotente); il tick fase83 la chiude passando gli idem_key dei
pendenti; il guardiano fase186 la conta ('hold_fantasma').

Protezioni: (1) il set dei pendenti idem_validi -> un hold LEGITTIMO non viene mai liberato;
(2) la GRAZIA -> un blocco appena creato (checkout in corso) non viene toccato.
Vista ROSSA: senza il filtro idem_validi, anche un blocco legittimo verrebbe liberato.
"""
import shutil
import sqlite3
import tempfile
import unittest

from fase58_channel_manager import crea_channel_manager


class TestStanzaFantasma(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.db = self.d + "/i.db"
        self.cm = crea_channel_manager(self.db)
        for g in ("2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04",
                  "2026-07-05", "2026-07-06"):
            self.cm.imposta_disponibilita("a", g, unita_totali=1,
                                          prezzo_netto_cents=10000, min_notti=1)
        # 3 blocchi su notti distinte (1 unita' ciascuna)
        self.cm.blocca("a", "2026-07-01", "2026-07-02", idem_key="legit")     # ha un pendente
        self.cm.blocca("a", "2026-07-03", "2026-07-04", idem_key="ph_old")    # fantasma vecchio
        self.cm.blocca("a", "2026-07-05", "2026-07-06", idem_key="ph_recent")  # fantasma appena nato
        # invecchio SOLO ph_old (blocco di anni fa)
        con = sqlite3.connect(self.db)
        con.execute("UPDATE movimenti SET ts='2020-01-01T00:00:00' WHERE idem_key='ph_old'")
        con.commit()
        con.close()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _occ(self, giorno):
        con = sqlite3.connect(self.db)
        r = con.execute("SELECT unita_occupate FROM inventario WHERE alloggio_id='a' AND giorno=?",
                        (giorno,)).fetchone()
        con.close()
        return r[0] if r else None

    def test_orfani_solo_il_vecchio_senza_pendente(self):
        orf = {o["idem_key"] for o in self.cm.orfani({"legit"}, grazia_sec=3600)}
        self.assertEqual(orf, {"ph_old"},
                         "orfano = solo il blocco vecchio senza pendente; legit protetto, recente in grazia")

    def test_libera_orfani_chiude_solo_il_fantasma(self):
        self.assertEqual(self._occ("2026-07-03"), 1)          # ph_old occupa
        liberati = {o["idem_key"] for o in self.cm.libera_orfani({"legit"}, grazia_sec=3600)}
        self.assertEqual(liberati, {"ph_old"})
        self.assertEqual(self._occ("2026-07-03"), 0, "la stanza fantasma e' liberata (rivendibile)")
        self.assertEqual(self._occ("2026-07-01"), 1, "il blocco LEGITTIMO resta (ha un pendente)")
        self.assertEqual(self._occ("2026-07-05"), 1, "il blocco RECENTE resta (grazia: checkout in corso)")

    def test_idempotente(self):
        self.cm.libera_orfani({"legit"}, grazia_sec=3600)
        self.assertEqual(self.cm.libera_orfani({"legit"}, grazia_sec=3600), [],
                         "gia' chiusa -> niente da liberare (idempotente)")

    def test_vista_rossa_senza_il_set_pendenti_il_legittimo_e_orfano(self):
        # rendo 'vecchio' anche il legittimo: e' il set idem_validi (i pendenti) l'unica cosa
        # che lo protegge. Se orfani() NON filtrasse idem_validi, lo libererebbe -> danno.
        con = sqlite3.connect(self.db)
        con.execute("UPDATE movimenti SET ts='2020-01-01T00:00:00' WHERE idem_key='legit'")
        con.commit()
        con.close()
        orf_vuoto = {o["idem_key"] for o in self.cm.orfani(set(), grazia_sec=3600)}
        self.assertIn("legit", orf_vuoto,
                      "senza i pendenti anche il legittimo risulterebbe orfano: il filtro e' la protezione")
        # CON il set corretto il legittimo NON e' orfano
        orf_ok = {o["idem_key"] for o in self.cm.orfani({"legit"}, grazia_sec=3600)}
        self.assertNotIn("legit", orf_ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
