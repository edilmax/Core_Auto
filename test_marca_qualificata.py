"""GUARDIA — MARCA TEMPORALE QUALIFICATA EUROPEA (eIDAS art. 42).

PERCHE' CONTA. Una marca RFC 3161 qualunque prova che un terzo ha attestato l'ora.
Una marca QUALIFICATA, emessa da un prestatore iscritto nella lista di fiducia europea,
gode dell'**art. 41 eIDAS**: presunzione legale di esattezza della data e dell'ora e di
integrita' dei dati. In giudizio l'onere si rovescia — non tocca a noi provare che l'ora
e' giusta, tocca a chi contesta provare il contrario.

LA QUALIFICA NON SI CREDE, SI LEGGE. Il certificato con cui la TSA firma contiene la
dichiarazione ETSI EN 319 422 `esi4-qtstStatement-1` (OID 0.4.0.19422.1.1). E' li' dentro
il token: `e_qualificata()` la cerca. Se un prestatore perdesse la qualifica, la marca
successiva risulterebbe subito non qualificata, senza che nessuno debba accorgersene.

Scelti sul campo il 2026-07-21 interrogando 16 endpoint europei: ACCV (ES) e QuoVadis EU
sono qualificati **e** verificabili con il solo archivio CA di sistema; Izenpe (ES) e
BOSA (BE) sono qualificati ma richiedono la loro radice (quindi solo come riserva).
"""

import base64
import os
import sqlite3
import tempfile
import unittest

import fase184_marca_temporale as mt
from test_fase184_marca_temporale import IMPRONTA, _risposta, _tstinfo


def _token_qualificato(impronta, **kw):
    """Token che contiene la dichiarazione ETSI, come quelli veri di ACCV/QuoVadis."""
    tst = _tstinfo(impronta, **kw)
    finto_cert = mt._der(0x30, mt._der_oid(mt.OID_QTST_ETSI) + mt._der(0x05, b""))
    econtent = mt._der(0xA0, mt._der(0x04, tst))
    encap = mt._der(0x30, mt._der_oid((1, 2, 840, 113549, 1, 9, 16, 1, 4)) + econtent)
    signed = mt._der(0x30, mt._der_intero(3) + mt._der(0xA0, finto_cert) + encap)
    token = mt._der(0x30, mt._der_oid((1, 2, 840, 113549, 1, 7, 2))
                    + mt._der(0xA0, signed))
    return mt._der(0x30, mt._der(0x30, mt._der_intero(0)) + token)


def _rete_ordinaria(url, richiesta, timeout):
    """TSA finta NON qualificata, fedele su impronta e nonce."""
    t = mt._leggi_tlv(richiesta, 0)
    c = mt._figli(richiesta, t[1], t[2])
    imp = mt._figli(richiesta, c[1][1], c[1][2])[1]
    return _risposta(richiesta[imp[1]:imp[2]],
                     nonce=mt._intero_da(richiesta, c[2][1], c[2][2]))


class TestRiconoscimento(unittest.TestCase):

    def test_riconosce_una_marca_qualificata(self):
        e = mt.interpreta_risposta(_token_qualificato(IMPRONTA), IMPRONTA)
        self.assertTrue(e["ok"], e.get("motivo"))
        self.assertTrue(mt.e_qualificata(e["token"]))

    def test_una_marca_ordinaria_NON_e_qualificata(self):
        """Il ripiego non deve mai potersi spacciare per qualificato."""
        e = mt.interpreta_risposta(_risposta(IMPRONTA), IMPRONTA)
        self.assertTrue(e["ok"])
        self.assertFalse(mt.e_qualificata(e["token"]))

    def test_gli_OID_sono_quelli_dello_standard(self):
        """Valori noti: 0.4.0.19422.1.1 e 0.4.0.1862.1.1."""
        self.assertEqual(mt._der_oid(mt.OID_QTST_ETSI),
                         bytes.fromhex("0607040081975e0101"))
        self.assertEqual(mt._der_oid(mt.OID_QC_COMPLIANCE),
                         bytes.fromhex("060604008e460101"))

    def test_su_spazzatura_non_dichiara_mai_qualificata(self):
        for cattivo in [b"", None, b"\x00" * 50, os.urandom(200), "testo", 12345]:
            self.assertFalse(mt.e_qualificata(cattivo))


class TestArchivio(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.percorso = os.path.join(self.d, "m.db")
        self.a = mt.crea_archivio_marche(self.percorso)

    def test_la_qualifica_viene_archiviata(self):
        e = mt.interpreta_risposta(_token_qualificato(IMPRONTA, nonce=3), IMPRONTA, 3)
        e["qualificata"] = mt.e_qualificata(e["token"])
        r = self.a.scrivi(giorno="2026-07-21", ambito="registri",
                          impronta=IMPRONTA.hex(), canonico="X", esito=e)
        self.assertEqual(self.a.elenco()[0]["qualificata"], 1)
        v = self.a.verifica(r["id"])
        self.assertTrue(v["qualificata"])
        self.assertTrue(v["qualifica_coerente"])

    def test_smaschera_una_qualifica_ALZATA_A_MANO(self):
        """Qualcuno mette qualificata=1 su una marca ordinaria sperando di gonfiarne il
        valore: la riverifica rilegge DAL TOKEN e denuncia l'incoerenza."""
        e = mt.interpreta_risposta(_risposta(IMPRONTA, nonce=4), IMPRONTA, 4)
        e["qualificata"] = False
        r = self.a.scrivi(giorno="2026-07-21", ambito="registri",
                          impronta=IMPRONTA.hex(), canonico="X", esito=e)
        con = sqlite3.connect(self.percorso)
        con.execute("UPDATE marche SET qualificata=1 WHERE id=?", (r["id"],))
        con.commit()
        con.close()
        v = self.a.verifica(r["id"])
        self.assertTrue(v["ok"])
        self.assertFalse(v["qualificata"], "il token NON e' qualificato")
        self.assertFalse(v["qualifica_coerente"], "l'incoerenza deve emergere")

    def test_le_marche_vecchie_restano_valide(self):
        """Migrazione: una marca archiviata prima del 2026-07-21 non aveva la colonna.
        Deve restare leggibile e risultare NON qualificata — che e' la verita'."""
        d2 = tempfile.mkdtemp()
        p2 = os.path.join(d2, "vecchio.db")
        con = sqlite3.connect(p2)
        con.execute("""CREATE TABLE marche (id INTEGER PRIMARY KEY AUTOINCREMENT,
            giorno TEXT NOT NULL, ambito TEXT NOT NULL DEFAULT 'registri',
            impronta TEXT NOT NULL, canonico TEXT NOT NULL DEFAULT '',
            stato TEXT NOT NULL, tsa TEXT NOT NULL DEFAULT '',
            policy TEXT NOT NULL DEFAULT '', seriale TEXT NOT NULL DEFAULT '',
            gen_time INTEGER NOT NULL DEFAULT 0, richiesto_ts INTEGER NOT NULL,
            token_b64 TEXT NOT NULL DEFAULT '', errore TEXT NOT NULL DEFAULT '')""")
        e = mt.interpreta_risposta(_risposta(IMPRONTA, nonce=9), IMPRONTA, 9)
        con.execute("INSERT INTO marche (giorno, impronta, stato, richiesto_ts,"
                    " token_b64, gen_time) VALUES ('2026-07-20', ?, 'ok', 1, ?, ?)",
                    (IMPRONTA.hex(), base64.b64encode(e["token"]).decode(),
                     e["gen_time"]))
        con.commit()
        con.close()
        a2 = mt.crea_archivio_marche(p2)               # migrazione idempotente
        righe = a2.elenco()
        self.assertEqual(len(righe), 1)
        self.assertEqual(righe[0]["qualificata"], 0)
        self.assertTrue(a2.verifica(righe[0]["id"])["ok"],
                        "la prova archiviata prima deve restare valida")


class TestPolitica(unittest.TestCase):

    def setUp(self):
        self._vecchio = os.environ.get("MARCA_SOLO_QUALIFICATA")
        self.addCleanup(self._ripristina)

    def _ripristina(self):
        if self._vecchio is None:
            os.environ.pop("MARCA_SOLO_QUALIFICATA", None)
        else:
            os.environ["MARCA_SOLO_QUALIFICATA"] = self._vecchio

    def test_il_divieto_toglie_del_tutto_il_ripiego(self):
        os.environ["MARCA_SOLO_QUALIFICATA"] = "1"
        self.assertEqual(mt._tsa_configurate(), mt.TSA_QUALIFICATE)
        os.environ["MARCA_SOLO_QUALIFICATA"] = "0"
        self.assertEqual(mt._tsa_configurate(), mt.TSA_PREDEFINITE)

    def test_col_divieto_meglio_nessuna_marca_che_una_ordinaria(self):
        d = tempfile.mkdtemp()
        a = mt.crea_archivio_marche(os.path.join(d, "m.db"))
        os.environ["MARCA_SOLO_QUALIFICATA"] = "1"
        r = mt.marca_i_registri(a, accettazioni=None, finanza=None,
                                giorno="2026-07-21", url="http://t.finto",
                                trasporto=_rete_ordinaria)
        self.assertFalse(r["ok"])
        self.assertEqual(r["motivo"], "solo_qualificate_ma_nessuna_disponibile")
        self.assertFalse(a.gia_marcato("2026-07-21"),
                         "non deve restare archiviata come riuscita")

    def test_senza_divieto_si_ripiega_MA_etichettando(self):
        d = tempfile.mkdtemp()
        a = mt.crea_archivio_marche(os.path.join(d, "m.db"))
        os.environ["MARCA_SOLO_QUALIFICATA"] = "0"
        r = mt.marca_i_registri(a, accettazioni=None, finanza=None,
                                giorno="2026-07-21", url="http://t.finto",
                                trasporto=_rete_ordinaria)
        self.assertTrue(r["ok"], "meglio una prova onesta che nessuna prova")
        self.assertFalse(r["qualificata"], "ma dichiarata per quello che e'")
        self.assertEqual(a.elenco()[0]["qualificata"], 0)

    def test_le_qualificate_vengono_interrogate_PRIMA(self):
        """L'ordine E' la politica: sarebbe assurdo ottenere una marca di rango
        inferiore avendone a disposizione una qualificata."""
        lista = mt._tsa_configurate()
        primo_ripiego = min((lista.index(u) for u in mt.TSA_RIPIEGO if u in lista),
                            default=len(lista))
        ultimo_qual = max((lista.index(u) for u in mt.TSA_QUALIFICATE if u in lista),
                          default=-1)
        self.assertGreater(primo_ripiego, ultimo_qual)

    def test_almeno_due_prestatori_qualificati_indipendenti(self):
        """Uno solo sarebbe un unico punto di rottura."""
        self.assertGreaterEqual(len(mt.TSA_QUALIFICATE), 2)
        domini = {u.split("//")[1].split("/")[0].split(":")[0]
                  for u in mt.TSA_QUALIFICATE}
        self.assertEqual(len(domini), len(mt.TSA_QUALIFICATE))

    def test_solo_prestatori_verificati_dal_vivo(self):
        """Il dominio NON dice se un prestatore e' qualificato (QuoVadis EU usa un .com
        pur essendo il servizio qualificato europeo): la prova e' la dichiarazione ETSI
        dentro il token, controllata a ogni marca da `e_qualificata()` e archiviata riga
        per riga. Qui si impedisce di aggiungere alla lista un endpoint che non sia stato
        interrogato dal vivo e trovato qualificato — il 2026-07-21, su 16 candidati."""
        verificati = {
            "tss.accv.es": "ACCV, Generalitat Valenciana (ES)",
            "ts.quovadisglobal.com": "QuoVadis EU",
            "tsa.izenpe.com": "Izenpe, Paesi Baschi (ES)",
            "tsa.belgium.be": "BOSA, Stato belga (BE)",
        }
        for url in mt.TSA_QUALIFICATE:
            dominio = url.split("//")[1].split("/")[0].split(":")[0]
            self.assertIn(dominio, verificati,
                          "%s non risulta fra i prestatori interrogati e trovati "
                          "QUALIFICATI: aggiungerlo senza provarlo dal vivo significa "
                          "dichiarare una qualifica che nessuno ha verificato" % dominio)

    def test_le_prime_due_sono_verificabili_da_chiunque(self):
        """Provato dal vivo: ACCV e QuoVadis si verificano con il solo archivio CA di
        sistema. Izenpe e BOSA richiedono la loro radice -> solo come riserva, altrimenti
        il perito che riceve il .tsr non potrebbe verificarlo da solo."""
        for url in mt.TSA_QUALIFICATE[:2]:
            self.assertTrue("accv.es" in url or "quovadisglobal.com" in url, url)


if __name__ == "__main__":
    unittest.main(verbosity=2)
