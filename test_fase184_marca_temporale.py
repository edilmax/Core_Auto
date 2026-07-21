"""GUARDIA — MARCA TEMPORALE RFC 3161 (fase184).

Parte delicatissima: e' un PROTOCOLLO BINARIO. Un byte sbagliato e la TSA rifiuta, oppure
(molto peggio) accettiamo per buono un token che NON certifica il nostro documento e ce ne
accorgiamo in tribunale. Qui si verifica, senza toccare la rete:
  A) l'encoder DER, byte per byte, contro valori noti;
  B) la richiesta, rileggendola e smontandola;
  C) la lettura della risposta, comprese TUTTE le vie di rifiuto;
  D) il sigillo dei registri (deterministico e sensibile a ogni modifica);
  E) l'archivio append-only dei token;
  F) il giro completo con la rete FINTA (successo, guasto, idempotenza).
"""

import base64
import os
import sqlite3
import tempfile
import unittest

import fase184_marca_temporale as mt


# ══════════════════════════════════════════════════════════════════════════════════
#  Officina: costruisce risposte TSA finte ma STRUTTURALMENTE VERE
# ══════════════════════════════════════════════════════════════════════════════════

def _gen_time(testo="20260721103000Z"):
    return mt._der(0x18, testo.encode("ascii"))


def _tstinfo(impronta, *, seriale=42, nonce=None, quando="20260721103000Z", versione=1):
    algo = mt._der(0x30, mt._der_oid(mt.OID_SHA256) + mt._der(0x05, b""))
    imprint = mt._der(0x30, algo + mt._der(0x04, impronta))
    corpo = (mt._der_intero(versione)
             + mt._der_oid((1, 2, 3, 4, 1))          # policy OID di prova
             + imprint
             + mt._der_intero(seriale)
             + _gen_time(quando))
    if nonce is not None:
        corpo += mt._der_intero(nonce)
    return mt._der(0x30, corpo)


def _token_cms(tstinfo_der):
    """Incapsula il TSTInfo come fa un CMS SignedData: dentro un OCTET STRING,
    annidato in piu' livelli. Il parser deve saperlo pescare da li' dentro."""
    econtent = mt._der(0xA0, mt._der(0x04, tstinfo_der))
    encap = mt._der(0x30, mt._der_oid((1, 2, 840, 113549, 1, 9, 16, 1, 4)) + econtent)
    signed = mt._der(0x30, mt._der_intero(3) + mt._der(0x31, b"") + encap)
    return mt._der(0x30, mt._der_oid((1, 2, 840, 113549, 1, 7, 2))
                   + mt._der(0xA0, signed))


def _risposta(impronta, *, stato=0, con_token=True, **kw):
    status = mt._der(0x30, mt._der_intero(stato))
    corpo = status + (_token_cms(_tstinfo(impronta, **kw)) if con_token else b"")
    return mt._der(0x30, corpo)


IMPRONTA = bytes(range(32))
ALTRA = bytes(range(1, 33))


# ══════════════════════════════════════════════════════════════════════════════════
#  A) Encoder DER
# ══════════════════════════════════════════════════════════════════════════════════

class TestDER(unittest.TestCase):

    def test_lunghezza_forma_corta(self):
        self.assertEqual(mt._der_lunghezza(0), b"\x00")
        self.assertEqual(mt._der_lunghezza(127), b"\x7f")

    def test_lunghezza_forma_lunga(self):
        self.assertEqual(mt._der_lunghezza(128), b"\x81\x80")
        self.assertEqual(mt._der_lunghezza(256), b"\x82\x01\x00")
        self.assertEqual(mt._der_lunghezza(65536), b"\x83\x01\x00\x00")

    def test_intero_zero_e_piccoli(self):
        self.assertEqual(mt._der_intero(0), b"\x02\x01\x00")
        self.assertEqual(mt._der_intero(1), b"\x02\x01\x01")

    def test_intero_bit_alto_riceve_lo_zero_davanti(self):
        """Senza il byte 0x00 un 128 verrebbe letto come NEGATIVO: e' l'errore classico
        che fa rifiutare la richiesta dalla TSA con 'bad request'."""
        self.assertEqual(mt._der_intero(128), b"\x02\x02\x00\x80")
        self.assertEqual(mt._der_intero(255), b"\x02\x02\x00\xff")
        self.assertEqual(mt._der_intero(256), b"\x02\x02\x01\x00")

    def test_intero_grande_come_un_nonce_vero(self):
        n = int.from_bytes(b"\xff" * 8, "big")
        d = mt._der_intero(n)
        t = mt._leggi_tlv(d, 0)
        self.assertEqual(mt._intero_da(d, t[1], t[2]), n)

    def test_oid_sha256_byte_per_byte(self):
        """Valore noto: 2.16.840.1.101.3.4.2.1 -> 06 09 60 86 48 01 65 03 04 02 01."""
        self.assertEqual(mt._der_oid(mt.OID_SHA256),
                         bytes.fromhex("0609608648016503040201"))

    def test_oid_andata_e_ritorno(self):
        for oid in [(1, 2, 3, 4), (1, 2, 840, 113549, 1, 9, 16, 1, 4), (2, 5, 4, 3)]:
            d = mt._der_oid(oid)
            t = mt._leggi_tlv(d, 0)
            self.assertEqual(mt._oid_da(d, t[1], t[2]), oid)

    def test_intero_negativo_rifiutato(self):
        with self.assertRaises(ValueError):
            mt._der_intero(-1)


# ══════════════════════════════════════════════════════════════════════════════════
#  B) La richiesta
# ══════════════════════════════════════════════════════════════════════════════════

class TestRichiesta(unittest.TestCase):

    def test_struttura_completa(self):
        req = mt.costruisci_richiesta(IMPRONTA, 12345)
        t = mt._leggi_tlv(req, 0)
        self.assertEqual(t[0], 0x30)
        campi = mt._figli(req, t[1], t[2])
        self.assertEqual(len(campi), 4, "version + imprint + nonce + certReq")
        self.assertEqual(mt._intero_da(req, campi[0][1], campi[0][2]), 1)
        self.assertEqual(campi[1][0], 0x30)
        self.assertEqual(mt._intero_da(req, campi[2][1], campi[2][2]), 12345)
        self.assertEqual(campi[3][0], 0x01)
        self.assertEqual(req[campi[3][1]:campi[3][2]], b"\xff", "certReq deve essere TRUE")

    def test_impronta_dentro_la_richiesta(self):
        req = mt.costruisci_richiesta(IMPRONTA, 7)
        t = mt._leggi_tlv(req, 0)
        imprint = mt._figli(req, t[1], t[2])[1]
        dentro = mt._figli(req, imprint[1], imprint[2])
        self.assertEqual(dentro[1][0], 0x04)
        self.assertEqual(req[dentro[1][1]:dentro[1][2]], IMPRONTA)

    def test_algoritmo_dichiarato_sha256(self):
        req = mt.costruisci_richiesta(IMPRONTA, 7)
        self.assertIn(mt._der_oid(mt.OID_SHA256), req)

    def test_impronta_di_lunghezza_sbagliata_rifiutata(self):
        for cattiva in [b"", b"corta", bytes(31), bytes(33), "testo"]:
            with self.assertRaises((ValueError, TypeError)):
                mt.costruisci_richiesta(cattiva, 1)

    def test_certreq_serve_ad_avere_il_certificato_nel_token(self):
        """certReq=TRUE rende il token AUTOSUFFICIENTE fra dieci anni."""
        self.assertIn(b"\x01\x01\xff", mt.costruisci_richiesta(IMPRONTA, 1))


# ══════════════════════════════════════════════════════════════════════════════════
#  C) La risposta — e tutte le vie di rifiuto
# ══════════════════════════════════════════════════════════════════════════════════

class TestRisposta(unittest.TestCase):

    def test_risposta_buona(self):
        e = mt.interpreta_risposta(_risposta(IMPRONTA, nonce=99), IMPRONTA, 99)
        self.assertTrue(e["ok"], e.get("motivo"))
        self.assertEqual(e["impronta_hex"], IMPRONTA.hex())
        self.assertEqual(e["seriale"], 42)
        self.assertEqual(e["nonce"], 99)
        self.assertEqual(e["stato_nome"], "concessa")
        self.assertTrue(e["token"])

    def test_ora_certificata_letta_giusta(self):
        e = mt.interpreta_risposta(_risposta(IMPRONTA, quando="20260721103000Z"),
                                   IMPRONTA)
        import calendar
        atteso = calendar.timegm((2026, 7, 21, 10, 30, 0, 0, 1, -1))
        self.assertEqual(e["gen_time"], atteso)

    def test_concessa_con_modifiche_accettata(self):
        e = mt.interpreta_risposta(_risposta(IMPRONTA, stato=1), IMPRONTA)
        self.assertTrue(e["ok"])
        self.assertEqual(e["stato_nome"], "concessa_con_modifiche")

    def test_stato_di_rifiuto_respinto(self):
        for stato, nome in [(2, "rifiutata"), (3, "in_attesa"),
                            (4, "avviso_revoca"), (5, "revoca")]:
            e = mt.interpreta_risposta(_risposta(IMPRONTA, stato=stato), IMPRONTA)
            self.assertFalse(e["ok"])
            self.assertEqual(e["motivo"], "stato_" + nome)

    def test_token_per_UN_ALTRO_documento_respinto(self):
        """IL controllo che conta: una TSA (o chi sta in mezzo) restituisce un token
        valido ma riferito ad ALTRO. Se lo accettassimo, avremmo in archivio una prova
        che non prova niente — e lo scopriremmo in causa."""
        e = mt.interpreta_risposta(_risposta(ALTRA), IMPRONTA)
        self.assertFalse(e["ok"])
        self.assertEqual(e["motivo"], "impronta_non_corrisponde")

    def test_nonce_diverso_respinto_antireplay(self):
        """Token vecchio rigiocato da chi sta in mezzo: il nonce non torna."""
        e = mt.interpreta_risposta(_risposta(IMPRONTA, nonce=1), IMPRONTA, 2)
        self.assertFalse(e["ok"])
        self.assertEqual(e["motivo"], "nonce_diverso")

    def test_nonce_assente_tollerato(self):
        """Alcune TSA non riportano il nonce: si accetta, l'impronta resta il vincolo."""
        e = mt.interpreta_risposta(_risposta(IMPRONTA, nonce=None), IMPRONTA, 555)
        self.assertTrue(e["ok"])

    def test_versione_sbagliata_respinta(self):
        e = mt.interpreta_risposta(_risposta(IMPRONTA, versione=2), IMPRONTA)
        self.assertFalse(e["ok"])

    def test_risposta_senza_token(self):
        e = mt.interpreta_risposta(_risposta(IMPRONTA, con_token=False), IMPRONTA)
        self.assertFalse(e["ok"])
        self.assertEqual(e["motivo"], "manca_token")

    def test_spazzatura_non_fa_esplodere_nulla(self):
        for cattiva in [b"", b"\x00", b"\x30", b"\x30\x80", b"non asn1",
                        b"\x30\x84\xff\xff\xff\xff", os.urandom(64),
                        b"\x30" + b"\xff" * 200, None, 12345, "stringa"]:
            e = mt.interpreta_risposta(cattiva, IMPRONTA)
            self.assertFalse(e["ok"])
            self.assertIn("motivo", e)

    def test_risposta_troncata_a_meta(self):
        buona = _risposta(IMPRONTA)
        for taglio in range(1, len(buona), 7):
            e = mt.interpreta_risposta(buona[:taglio], IMPRONTA)
            if taglio < len(buona):
                self.assertFalse(e["ok"])

    def test_ora_malformata_respinta(self):
        for brutta in ["", "Z", "non-una-data", "20261301103000Z", "20260721103000",
                       "2026072110300Z"]:
            e = mt.interpreta_risposta(_risposta(IMPRONTA, quando=brutta), IMPRONTA)
            self.assertFalse(e["ok"], "accettata un'ora malformata: %r" % brutta)

    def test_lunghezza_indefinita_BER_gestita(self):
        """Diverse TSA rispondono in BER a lunghezza indefinita: un parser DER puro
        fallirebbe proprio sulle risposte VERE."""
        tst = _tstinfo(IMPRONTA)
        econtent = b"\xa0\x80" + mt._der(0x04, tst) + b"\x00\x00"
        encap = b"\x30\x80" + mt._der_oid((1, 2, 840, 113549, 1, 9, 16, 1, 4)) \
            + econtent + b"\x00\x00"
        signed = b"\x30\x80" + mt._der_intero(3) + encap + b"\x00\x00"
        token = b"\x30\x80" + mt._der_oid((1, 2, 840, 113549, 1, 7, 2)) \
            + b"\xa0\x80" + signed + b"\x00\x00" + b"\x00\x00"
        risp = mt._der(0x30, mt._der(0x30, mt._der_intero(0)) + token)
        e = mt.interpreta_risposta(risp, IMPRONTA)
        self.assertTrue(e["ok"], e.get("motivo"))
        self.assertEqual(e["seriale"], 42)

    def test_token_restituito_e_quello_grezzo(self):
        """Il token va archiviato TALE E QUALE: e' l'oggetto che un perito verifica
        con openssl, senza il nostro software."""
        risp = _risposta(IMPRONTA)
        e = mt.interpreta_risposta(risp, IMPRONTA)
        self.assertIn(e["token"], risp)
        self.assertEqual(e["token"][0], 0x30)


# ══════════════════════════════════════════════════════════════════════════════════
#  D) Il sigillo dei registri
# ══════════════════════════════════════════════════════════════════════════════════

class TestSigillo(unittest.TestCase):

    def _sig(self, **kw):
        base = dict(giorno="2026-07-21", accettazioni_sigillo="a" * 64,
                    accettazioni_righe=10, giornale_testa="b" * 64, giornale_righe=20)
        base.update(kw)
        return mt.componi_sigillo(**base)

    def test_deterministico(self):
        self.assertEqual(self._sig()["impronta"], self._sig()["impronta"])

    def test_e_una_sha256(self):
        self.assertEqual(len(self._sig()["impronta"]), 64)
        int(self._sig()["impronta"], 16)

    def test_cambia_se_cambia_qualunque_ingrediente(self):
        base = self._sig()["impronta"]
        for k, v in [("giorno", "2026-07-22"), ("accettazioni_sigillo", "c" * 64),
                     ("accettazioni_righe", 11), ("giornale_testa", "d" * 64),
                     ("giornale_righe", 21)]:
            self.assertNotEqual(self._sig(**{k: v})["impronta"], base,
                                "il sigillo non reagisce a %s" % k)

    def test_canonico_leggibile_e_ricalcolabile(self):
        s = self._sig()
        import hashlib
        self.assertIn("BOOKINVIP-SIGILLO-v1", s["canonico"])
        self.assertIn("righe_accettazioni=10", s["canonico"])
        self.assertEqual(hashlib.sha256(s["canonico"].encode()).hexdigest(),
                         s["impronta"])


class TestSigilloAccettazioni(unittest.TestCase):
    """Il sigillo lato registro prove (fase163)."""

    def setUp(self):
        import fase163_accettazioni as f163
        self.d = tempfile.mkdtemp()
        self.reg = f163.crea_registro_accettazioni(
            os.path.join(self.d, "acc.db"), b"segreto-di-prova")

    def test_registro_vuoto_ha_un_sigillo(self):
        s = self.reg.sigillo()
        self.assertEqual(s["righe"], 0)
        self.assertEqual(len(s["sigillo"]), 64)

    def test_mai_il_sigillo_di_ripiego(self):
        """Il ripiego 'errore' e' fail-soft VOLUTO (non deve rompere la macchina), ma se
        comparisse in condizioni normali maschererebbe un guasto: qui lo si vieta.
        Questa guardia ha gia' scoperto un difetto vero il 2026-07-21."""
        self.assertNotEqual(self.reg.sigillo()["sigillo"], "errore")
        for i in range(3):
            self.reg.registra("h%d" % i, ip="1.2.3.4", vessatorie=True)
            s = self.reg.sigillo()
            self.assertNotEqual(s["sigillo"], "errore")
            self.assertEqual(len(s["sigillo"]), 64)
            self.assertEqual(s["righe"], i + 1)

    def test_cambia_a_ogni_prova_aggiunta(self):
        visti = {self.reg.sigillo()["sigillo"]}
        for i in range(5):
            self.reg.registra("host%d" % i, ip="1.2.3.4", vessatorie=True)
            s = self.reg.sigillo()
            self.assertNotIn(s["sigillo"], visti)
            visti.add(s["sigillo"])
            self.assertEqual(s["righe"], i + 1)

    def test_stabile_se_non_cambia_nulla(self):
        self.reg.registra("h1", ip="1.1.1.1")
        a = self.reg.sigillo()
        self.assertEqual(a, self.reg.sigillo())

    def test_manomettere_una_riga_cambia_il_sigillo(self):
        """Se qualcuno riscrive una prova nel database, il sigillo gia' MARCATO da un
        terzo non torna piu': la manomissione e' datata e dimostrabile."""
        self.reg.registra("h1", ip="1.1.1.1", vessatorie=True)
        self.reg.registra("h2", ip="2.2.2.2", vessatorie=True)
        prima = self.reg.sigillo()["sigillo"]
        con = sqlite3.connect(os.path.join(self.d, "acc.db"))
        con.execute("UPDATE accettazioni SET firma='falsa' WHERE id=1")
        con.commit(); con.close()
        self.assertNotEqual(self.reg.sigillo()["sigillo"], prima)

    def test_cancellare_una_riga_cambia_il_sigillo(self):
        for i in range(3):
            self.reg.registra("h%d" % i, ip="1.1.1.1")
        prima = self.reg.sigillo()["sigillo"]
        con = sqlite3.connect(os.path.join(self.d, "acc.db"))
        con.execute("DELETE FROM accettazioni WHERE id=2")
        con.commit(); con.close()
        s = self.reg.sigillo()
        self.assertNotEqual(s["sigillo"], prima)
        self.assertEqual(s["righe"], 2)

    def test_nessun_dato_personale_nel_calcolo(self):
        """Entrano solo id e firma: il sigillo si puo' pubblicare senza esporre nessuno."""
        self.reg.registra("host@esempio.it", ip="9.9.9.9",
                          user_agent="Mozilla/5.0 particolare")
        s = self.reg.sigillo()["sigillo"]
        self.assertNotIn("esempio", s)
        self.assertNotIn("9.9.9.9", s)


# ══════════════════════════════════════════════════════════════════════════════════
#  E) L'archivio
# ══════════════════════════════════════════════════════════════════════════════════

class TestArchivio(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.a = mt.crea_archivio_marche(os.path.join(self.d, "marche.db"))

    def _esito_ok(self, impronta=IMPRONTA):
        return mt.interpreta_risposta(_risposta(impronta, nonce=5), impronta, 5)

    def test_si_apre(self):
        self.assertIsNotNone(self.a)
        self.assertEqual(self.a.conta(), 0)

    def test_funziona_anche_in_memoria(self):
        """':memory:' crea un database NUOVO a ogni connessione: senza una connessione
        condivisa la tabella sparisce subito dopo essere stata creata e OGNI lettura
        esplode con 'no such table'. Difetto vero, trovato il 2026-07-21 prima del
        rilascio: in produzione si usa un file, ma la suite monta sistemi in RAM."""
        mem = mt.crea_archivio_marche(":memory:")
        self.assertIsNotNone(mem)
        self.assertEqual(mem.elenco(), [])
        self.assertEqual(mem.conta(), 0)
        self.assertFalse(mem.gia_marcato("2026-07-21"))
        r = mem.scrivi(giorno="2026-07-21", ambito="registri",
                       impronta=IMPRONTA.hex(), canonico="X", esito=self._esito_ok())
        self.assertTrue(r["ok"])
        self.assertEqual(mem.conta(), 1)
        self.assertTrue(mem.gia_marcato("2026-07-21"))
        self.assertTrue(mem.verifica(r["id"])["ok"])

    def test_scrive_e_rilegge(self):
        r = self.a.scrivi(giorno="2026-07-21", ambito="registri",
                          impronta=IMPRONTA.hex(), canonico="X",
                          esito=self._esito_ok())
        self.assertTrue(r["ok"])
        righe = self.a.elenco()
        self.assertEqual(len(righe), 1)
        self.assertEqual(righe[0]["stato"], "ok")
        self.assertEqual(righe[0]["seriale"], "42")

    def test_una_sola_marca_riuscita_per_giorno(self):
        """Idempotenza: un riavvio o un doppio giro non deve moltiplicare le marche."""
        for _ in range(3):
            self.a.scrivi(giorno="2026-07-21", ambito="registri",
                          impronta=IMPRONTA.hex(), canonico="X",
                          esito=self._esito_ok())
        self.assertEqual(len([r for r in self.a.elenco() if r["stato"] == "ok"]), 1)
        self.assertTrue(self.a.gia_marcato("2026-07-21"))
        self.assertFalse(self.a.gia_marcato("2026-07-22"))

    def test_i_fallimenti_si_archiviano_tutti(self):
        """I tentativi falliti NON sono soggetti all'unicita': servono a vedere che
        la macchina ci ha provato, e quante volte."""
        for _ in range(3):
            self.a.scrivi(giorno="2026-07-21", ambito="registri",
                          impronta=IMPRONTA.hex(), canonico="X",
                          esito={"ok": False, "motivo": "rete_giu"})
        self.assertEqual(self.a.conta(), 3)
        self.assertFalse(self.a.gia_marcato("2026-07-21"))

    def test_token_recuperabile_identico(self):
        e = self._esito_ok()
        r = self.a.scrivi(giorno="2026-07-21", ambito="registri",
                          impronta=IMPRONTA.hex(), canonico="X", esito=e)
        self.assertEqual(self.a.token(r["id"]), e["token"])

    def test_verifica_conferma_il_token_buono(self):
        r = self.a.scrivi(giorno="2026-07-21", ambito="registri",
                          impronta=IMPRONTA.hex(), canonico="X", esito=self._esito_ok())
        v = self.a.verifica(r["id"])
        self.assertTrue(v["ok"], v.get("motivo"))
        self.assertEqual(v["impronta_hex"], IMPRONTA.hex())
        self.assertTrue(v["coerente_con_archivio"])

    def test_verifica_smaschera_impronta_riscritta_nel_database(self):
        """Qualcuno cambia l'impronta nella riga sperando che il token copra un altro
        contenuto: la verifica non trova corrispondenza e lo dice."""
        r = self.a.scrivi(giorno="2026-07-21", ambito="registri",
                          impronta=IMPRONTA.hex(), canonico="X", esito=self._esito_ok())
        con = sqlite3.connect(os.path.join(self.d, "marche.db"))
        con.execute("UPDATE marche SET impronta=? WHERE id=?", (ALTRA.hex(), r["id"]))
        con.commit(); con.close()
        v = self.a.verifica(r["id"])
        self.assertFalse(v["ok"])
        self.assertEqual(v["motivo"], "token_non_certifica_questa_impronta")

    def test_verifica_nota_lora_riscritta(self):
        r = self.a.scrivi(giorno="2026-07-21", ambito="registri",
                          impronta=IMPRONTA.hex(), canonico="X", esito=self._esito_ok())
        con = sqlite3.connect(os.path.join(self.d, "marche.db"))
        con.execute("UPDATE marche SET gen_time=1 WHERE id=?", (r["id"],))
        con.commit(); con.close()
        v = self.a.verifica(r["id"])
        self.assertTrue(v["ok"])
        self.assertFalse(v["coerente_con_archivio"], "l'ora riscritta deve emergere")

    def test_verifica_su_riga_inesistente_o_senza_token(self):
        self.assertFalse(self.a.verifica(999)["ok"])
        r = self.a.scrivi(giorno="2026-07-21", ambito="registri",
                          impronta=IMPRONTA.hex(), canonico="X",
                          esito={"ok": False, "motivo": "rete_giu"})
        self.assertEqual(self.a.verifica(r["id"])["motivo"], "senza_token")

    def test_token_base64_valido_nellarchivio(self):
        r = self.a.scrivi(giorno="2026-07-21", ambito="registri",
                          impronta=IMPRONTA.hex(), canonico="X", esito=self._esito_ok())
        con = sqlite3.connect(os.path.join(self.d, "marche.db"))
        b64 = con.execute("SELECT token_b64 FROM marche WHERE id=?",
                          (r["id"],)).fetchone()[0]
        con.close()
        self.assertEqual(base64.b64decode(b64)[0], 0x30)


# ══════════════════════════════════════════════════════════════════════════════════
#  F) Il giro completo, con la rete FINTA
# ══════════════════════════════════════════════════════════════════════════════════

class _Registro:
    def __init__(self, sig="a" * 64, righe=3):
        self._s = {"sigillo": sig, "righe": righe}

    def sigillo(self):
        return self._s


class _Finanza:
    def __init__(self, testa="b" * 64, righe=7):
        self._c = {"ok": True, "testa": testa, "righe": righe}

    def verifica_catena(self):
        return self._c


class TestGiroCompleto(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.a = mt.crea_archivio_marche(os.path.join(self.d, "m.db"))
        self.chiamate = []

    def _rete_buona(self, url, richiesta, timeout):
        """Rete finta FEDELE: rilegge l'impronta e il nonce dalla richiesta VERA e
        risponde di conseguenza. Se la richiesta fosse malformata, qui si romperebbe."""
        self.chiamate.append(url)
        t = mt._leggi_tlv(richiesta, 0)
        campi = mt._figli(richiesta, t[1], t[2])
        imp = mt._figli(richiesta, campi[1][1], campi[1][2])[1]
        impronta = richiesta[imp[1]:imp[2]]
        nonce = mt._intero_da(richiesta, campi[2][1], campi[2][2])
        return _risposta(impronta, nonce=nonce)

    def _rete_giu(self, url, richiesta, timeout):
        self.chiamate.append(url)
        raise OSError("rete irraggiungibile")

    def test_giro_riuscito(self):
        r = mt.marca_i_registri(self.a, accettazioni=_Registro(), finanza=_Finanza(),
                                giorno="2026-07-21", url="http://tsa.finta",
                                trasporto=self._rete_buona)
        self.assertTrue(r["ok"], r.get("motivo"))
        self.assertEqual(len(r["impronta"]), 64)
        self.assertTrue(self.a.gia_marcato("2026-07-21"))
        v = self.a.verifica(r["id"])
        self.assertTrue(v["ok"])

    def test_limpronta_marcata_e_quella_dei_registri_veri(self):
        acc, fin = _Registro("c" * 64, 5), _Finanza("d" * 64, 9)
        r = mt.marca_i_registri(self.a, accettazioni=acc, finanza=fin,
                                giorno="2026-07-21", url="http://tsa.finta",
                                trasporto=self._rete_buona)
        atteso = mt.componi_sigillo(giorno="2026-07-21", accettazioni_sigillo="c" * 64,
                                    accettazioni_righe=5, giornale_testa="d" * 64,
                                    giornale_righe=9)["impronta"]
        self.assertEqual(r["impronta"], atteso)

    def test_idempotente_sul_giorno(self):
        for _ in range(4):
            mt.marca_i_registri(self.a, accettazioni=_Registro(), finanza=_Finanza(),
                                giorno="2026-07-21", url="http://tsa.finta",
                                trasporto=self._rete_buona)
        self.assertEqual(len(self.chiamate), 1, "una sola richiesta alla TSA per giorno")

    def test_rete_giu_non_rompe_niente(self):
        """Requisito assoluto: la marca e' un DI PIU'. Se la TSA e' irraggiungibile la
        macchina va avanti, archivia il tentativo e riprova al giro dopo."""
        r = mt.marca_i_registri(self.a, accettazioni=_Registro(), finanza=_Finanza(),
                                giorno="2026-07-21", url="http://tsa.finta",
                                trasporto=self._rete_giu)
        self.assertFalse(r["ok"])
        self.assertFalse(self.a.gia_marcato("2026-07-21"))
        self.assertEqual(self.a.elenco()[0]["stato"], "errore")

    def test_failover_prova_la_seconda_tsa(self):
        prima = {"fatto": False}

        def rete(url, richiesta, timeout):
            self.chiamate.append(url)
            if not prima["fatto"]:
                prima["fatto"] = True
                raise OSError("prima TSA giu'")
            return self._rete_buona(url, richiesta, timeout)

        r = mt.marca_i_registri(self.a, accettazioni=_Registro(), finanza=_Finanza(),
                                giorno="2026-07-21",
                                url="http://uno.finto,http://due.finto", trasporto=rete)
        self.assertTrue(r["ok"], r.get("motivo"))
        self.assertEqual(r["tsa"], "http://due.finto")

    def test_tsa_che_risponde_spazzatura(self):
        r = mt.marca_i_registri(self.a, accettazioni=_Registro(), finanza=_Finanza(),
                                giorno="2026-07-21", url="http://tsa.finta",
                                trasporto=lambda u, d, t: b"pagina di errore html")
        self.assertFalse(r["ok"])
        self.assertEqual(r["motivo"], "nessuna_tsa_disponibile")

    def test_tsa_che_restituisce_il_token_di_un_altro(self):
        r = mt.marca_i_registri(self.a, accettazioni=_Registro(), finanza=_Finanza(),
                                giorno="2026-07-21", url="http://tsa.finta",
                                trasporto=lambda u, d, t: _risposta(ALTRA))
        self.assertFalse(r["ok"], "un token per un altro documento NON va accettato")

    def test_funziona_anche_senza_registri_collegati(self):
        r = mt.marca_i_registri(self.a, accettazioni=None, finanza=None,
                                giorno="2026-07-21", url="http://tsa.finta",
                                trasporto=self._rete_buona)
        self.assertTrue(r["ok"], r.get("motivo"))

    def test_registro_che_esplode_non_ferma_la_macchina(self):
        class Rotto:
            def sigillo(self):
                raise RuntimeError("database in fiamme")

        r = mt.marca_i_registri(self.a, accettazioni=Rotto(), finanza=_Finanza(),
                                giorno="2026-07-21", url="http://tsa.finta",
                                trasporto=self._rete_buona)
        self.assertFalse(r["ok"])
        self.assertEqual(r["motivo"], "eccezione_isolata")

    def test_giornale_rotto_viene_marcato_comunque(self):
        """Se la catena contabile fosse spezzata, la marca lo CONGELA: si prova che a
        quell'ora era gia' rotta (utile tanto quanto provarla integra)."""
        class Spezzata:
            def verifica_catena(self):
                return {"ok": False, "seq_rotta": 17}

        r = mt.marca_i_registri(self.a, accettazioni=_Registro(), finanza=Spezzata(),
                                giorno="2026-07-21", url="http://tsa.finta",
                                trasporto=self._rete_buona)
        self.assertTrue(r["ok"])
        self.assertIn("ROTTA:17", self.a.elenco()[0]["canonico"])

    def test_nonce_diverso_a_ogni_richiesta(self):
        nonces = []

        def rete(url, richiesta, timeout):
            t = mt._leggi_tlv(richiesta, 0)
            campi = mt._figli(richiesta, t[1], t[2])
            nonces.append(mt._intero_da(richiesta, campi[2][1], campi[2][2]))
            return self._rete_buona(url, richiesta, timeout)

        for g in range(6):
            mt.marca_i_registri(self.a, accettazioni=_Registro(), finanza=_Finanza(),
                                giorno="2026-07-%02d" % (10 + g), url="http://t.finto",
                                trasporto=rete)
        self.assertEqual(len(set(nonces)), 6, "il nonce deve essere sempre nuovo")


class TestConfigurazione(unittest.TestCase):

    def test_acceso_di_default(self):
        vecchio = os.environ.pop("MARCA_TEMPORALE", None)
        try:
            self.assertTrue(mt.attivo())
        finally:
            if vecchio is not None:
                os.environ["MARCA_TEMPORALE"] = vecchio

    def test_si_spegne(self):
        vecchio = os.environ.get("MARCA_TEMPORALE")
        try:
            for spento in ["0", "false", "no", "off", ""]:
                os.environ["MARCA_TEMPORALE"] = spento
                self.assertFalse(mt.attivo(), spento)
            os.environ["MARCA_TEMPORALE"] = "1"
            self.assertTrue(mt.attivo())
        finally:
            if vecchio is None:
                os.environ.pop("MARCA_TEMPORALE", None)
            else:
                os.environ["MARCA_TEMPORALE"] = vecchio

    def test_tsa_predefinite_se_non_configurate(self):
        vecchio = os.environ.pop("TSA_URL", None)
        try:
            self.assertEqual(mt._tsa_configurate(), mt.TSA_PREDEFINITE)
            self.assertGreaterEqual(len(mt.TSA_PREDEFINITE), 3,
                                    "servono almeno tre emittenti indipendenti")
        finally:
            if vecchio is not None:
                os.environ["TSA_URL"] = vecchio

    def test_solo_TSA_i_cui_token_si_verificano_da_soli(self):
        """GUARDIA DI SCELTA. Il 2026-07-21 sette Autorita' sono state interrogate dal
        vivo e i loro token verificati con `openssl ts -verify` contro il solo archivio
        CA di sistema. Apple, FreeTSA e Izenpe hanno dato token VALIDI ma non
        verificabili senza procurarsi la loro radice: inutili davanti a un perito, e
        quindi vietate come predefinite. Se qualcuno le rimette, questo test lo ferma."""
        bocciate = ["apple.com", "freetsa.org", "izenpe.com", "baltstamp"]
        for url in mt.TSA_PREDEFINITE:
            for b in bocciate:
                self.assertNotIn(b, url,
                                 "%s era stata scartata: token non verificabile con le "
                                 "CA standard" % b)

    def test_emittenti_tutti_diversi(self):
        """Tre TSA della stessa societa' non sono un failover: sono un solo punto debole."""
        domini = {u.split("//")[1].split("/")[0].split(".")[-2] for u in mt.TSA_PREDEFINITE}
        self.assertEqual(len(domini), len(mt.TSA_PREDEFINITE),
                         "gli emittenti devono essere indipendenti fra loro")

    def test_elenco_tsa_da_variabile(self):
        self.assertEqual(mt._tsa_configurate("http://a , http://b ,"),
                         ("http://a", "http://b"))

    def test_qualsiasi_qtsp_si_innesta_cambiando_un_indirizzo(self):
        """La promessa architetturale: passare a un ente QUALIFICATO europeo non deve
        richiedere codice, solo una variabile."""
        self.assertEqual(mt._tsa_configurate("https://qtsp.esempio.eu/tsa"),
                         ("https://qtsp.esempio.eu/tsa",))


if __name__ == "__main__":
    unittest.main(verbosity=2)
