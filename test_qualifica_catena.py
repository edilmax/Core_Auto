"""GUARDIA — LA CATENA DELLA QUALIFICA, da capo a fondo.

Un modulo puo' riconoscere benissimo una marca qualificata e poi la cosa non arrivare
da nessuna parte: e' gia' successo su questo progetto (la promo 0% funzionava e non
veniva applicata; il motore recensioni era acceso e scriveva in RAM).

Qui si segue l'informazione lungo TUTTI gli anelli:
    token dell'Autorita'  ->  e_qualificata()  ->  archivio (colonna)
                          ->  riverifica dal token  ->  API del Bunker
                          ->  pannello HTML  ->  dossier legale (CSV e JSON)
Se un anello si spezza, la qualifica sparirebbe in silenzio proprio dove serve: davanti
a un giudice.
"""

import json
import os
import shutil
import tempfile
import unittest

import fase184_marca_temporale as mt
from test_marca_qualificata import _rete_ordinaria, _token_qualificato
from test_fase184_marca_temporale import IMPRONTA

PW = "SuperPw@1"
AK = {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.9", "User-Agent": "Firefox"}


def _rete_qualificata(url, richiesta, timeout):
    """Autorita' finta ma QUALIFICATA: risponde con la dichiarazione ETSI dentro."""
    t = mt._leggi_tlv(richiesta, 0)
    c = mt._figli(richiesta, t[1], t[2])
    imp = mt._figli(richiesta, c[1][1], c[1][2])[1]
    return _token_qualificato(richiesta[imp[1]:imp[2]],
                              nonce=mt._intero_da(richiesta, c[2][1], c[2][2]))


class BaseCatena(unittest.TestCase):

    def setUp(self):
        from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
        from fase83_server import crea_router
        self.d = d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db",
            db_registro_host=f"{d}/r.db", db_accettazioni=f"{d}/a.db",
            db_marche=f"{d}/m.db", db_pendenti=f"{d}/p.db",
            db_finanza=f"{d}/f.db", bunker_password=PW))
        self.router = crea_router(self.sis, host_key="hk", admin_key="ak",
                                  base_url="https://bookinvip.com")

    def g(self, m, p, b=None, h=None, q=None):
        return self.router.gestisci(m, p, q or {},
                                    json.dumps(b) if b is not None else None, h or AK)

    def _hdr(self):
        st, o = self.g("POST", "/api/bunker/login", {"codice": PW})
        self.assertEqual(st, 200, o)
        h = dict(AK)
        h["X-Bunker-Session"] = o["sessione"]
        return h

    def _marca(self, giorno, rete):
        return mt.marca_i_registri(self.sis.marche,
                                   accettazioni=self.sis.accettazioni,
                                   finanza=self.sis.finanza, giorno=giorno,
                                   url="http://t.finto", trasporto=rete)


class TestCatenaQualificata(BaseCatena):

    def test_anello_1_il_modulo_riconosce(self):
        r = self._marca("2026-07-21", _rete_qualificata)
        self.assertTrue(r["ok"], r.get("motivo"))
        self.assertTrue(r["qualificata"], "il modulo non ha riconosciuto la qualifica")

    def test_anello_2_larchivio_registra(self):
        self._marca("2026-07-21", _rete_qualificata)
        self.assertEqual(self.sis.marche.elenco()[0]["qualificata"], 1)

    def test_anello_3_la_riverifica_conferma_dal_token(self):
        r = self._marca("2026-07-21", _rete_qualificata)
        v = self.sis.marche.verifica(r["id"])
        self.assertTrue(v["qualificata"])
        self.assertTrue(v["qualifica_coerente"])

    def test_anello_4_lAPI_del_bunker_la_espone(self):
        self._marca("2026-07-21", _rete_qualificata)
        st, corpo = self.g("GET", "/api/bunker/marche_temporali", None, self._hdr())
        self.assertEqual(st, 200, corpo)
        self.assertEqual(corpo["qualificate"], 1)
        self.assertTrue(corpo["tutte_qualificate"])
        self.assertTrue(corpo["marche"][0]["qualificata"])
        self.assertIn("presunzione", corpo["cosa_significa_qualificata"])

    def test_anello_5_il_pannello_la_mostra(self):
        import io as _io
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "deploy", "bunker.html")
        html = _io.open(p, encoding="utf-8").read()
        self.assertIn("m.qualificata", html, "il pannello non legge il campo")
        self.assertIn("QUALIFICATA", html)
        self.assertIn("d.qualificate", html, "manca il riepilogo del conteggio")
        self.assertIn("cosa_significa_qualificata", html,
                      "il pannello non spiega cosa cambia con la qualifica")
        self.assertIn("eIDAS", html)

    def test_anello_6_il_dossier_CSV_la_riporta(self):
        self._marca("2026-07-21", _rete_qualificata)
        st, corpo = self.g("GET", "/api/bunker/export_legale", None, self._hdr(),
                           {"formato": "csv"})
        self.assertEqual(st, 200)
        testo = corpo["contenuto"]
        self.assertIn("qualificata_eidas", testo)
        self.assertIn("# marche_qualificate_eidas,1", testo)
        self.assertIn("910/2014", testo, "manca il riferimento normativo")
        self.assertTrue(corpo["certificato"], "il dossier deve restare sigillato")

    def test_anello_7_il_dossier_JSON_la_riporta(self):
        self._marca("2026-07-21", _rete_qualificata)
        st, corpo = self.g("GET", "/api/bunker/export_legale", None, self._hdr(),
                           {"formato": "json"})
        dati = json.loads(corpo["contenuto"].split("\n# FINE DOSSIER")[0])
        mtj = dati["marche_temporali"]
        self.assertEqual(mtj["qualificate_eidas"], 1)
        self.assertEqual(mtj["elenco"][0]["qualificata_eidas"], "SI")
        self.assertIn("presunzione", mtj["valore_della_qualifica"].lower())


class TestCatenaRipiego(BaseCatena):
    """Se si ripiega su un'Autorita' ordinaria, TUTTA la catena deve dirlo."""

    def test_il_ripiego_e_dichiarato_a_ogni_anello(self):
        r = self._marca("2026-07-21", _rete_ordinaria)
        self.assertTrue(r["ok"], "la prova si fa comunque")
        self.assertFalse(r["qualificata"])
        self.assertEqual(self.sis.marche.elenco()[0]["qualificata"], 0)
        self.assertFalse(self.sis.marche.verifica(r["id"])["qualificata"])
        st, corpo = self.g("GET", "/api/bunker/marche_temporali", None, self._hdr())
        self.assertEqual(corpo["qualificate"], 0)
        self.assertFalse(corpo["tutte_qualificate"])
        self.assertFalse(corpo["marche"][0]["qualificata"])
        st, corpo = self.g("GET", "/api/bunker/export_legale", None, self._hdr(),
                           {"formato": "csv"})
        self.assertIn("# marche_qualificate_eidas,0", corpo["contenuto"])

    def test_le_due_specie_convivono_senza_confondersi(self):
        """Giorni diversi, ranghi diversi: ogni riga dice la verita' sua."""
        self._marca("2026-07-21", _rete_qualificata)
        self._marca("2026-07-22", _rete_ordinaria)
        self._marca("2026-07-23", _rete_qualificata)
        st, corpo = self.g("GET", "/api/bunker/marche_temporali", None, self._hdr())
        self.assertEqual(corpo["riuscite"], 3)
        self.assertEqual(corpo["qualificate"], 2)
        self.assertFalse(corpo["tutte_qualificate"])
        per_giorno = {m["giorno"]: m["qualificata"] for m in corpo["marche"]}
        self.assertTrue(per_giorno["2026-07-21"])
        self.assertFalse(per_giorno["2026-07-22"])
        self.assertTrue(per_giorno["2026-07-23"])


class TestNienteBugie(BaseCatena):

    def test_una_qualifica_alzata_a_mano_viene_denunciata_fino_al_pannello(self):
        """Scenario ostile: qualcuno con accesso al database alza il flag. La catena
        rilegge DAL TOKEN e il pannello riceve `qualifica_coerente: false`."""
        import sqlite3
        r = self._marca("2026-07-21", _rete_ordinaria)
        con = sqlite3.connect(os.path.join(self.d, "m.db"))
        con.execute("UPDATE marche SET qualificata=1 WHERE id=?", (r["id"],))
        con.commit()
        con.close()
        st, corpo = self.g("GET", "/api/bunker/marche_temporali", None, self._hdr())
        riga = corpo["marche"][0]
        self.assertFalse(riga["qualificata"], "la verita' viene dal token")
        self.assertFalse(riga["qualifica_coerente"], "l'incoerenza deve emergere")
        self.assertEqual(corpo["qualificate"], 0)

    def test_il_pannello_ha_lallarme_per_lincoerenza(self):
        import io as _io
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "deploy", "bunker.html")
        html = _io.open(p, encoding="utf-8").read()
        self.assertIn("qualifica_coerente", html,
                      "il pannello non mostrerebbe una qualifica manomessa")


if __name__ == "__main__":
    unittest.main(verbosity=2)
