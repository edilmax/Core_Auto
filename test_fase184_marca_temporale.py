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

    def test_idempotente_sul_giorno_QUANDO_LA_MARCA_E_QUALIFICATA(self):
        """REGOLA CAMBIATA il 2026-07-21 (difetto visto in PRODUZIONE). Prima bastava
        una marca qualunque a chiudere il giorno: se i prestatori europei erano
        irraggiungibili al primo giro, si ripiegava e non si riprovava piu' per tutto
        il giorno, restando con una prova di rango inferiore. Ora il giorno si chiude
        solo con una marca QUALIFICATA — e allora si', una sola richiesta."""
        from test_marca_qualificata import _token_qualificato

        def rete_qualificata(url, richiesta, timeout):
            self.chiamate.append(url)
            t = mt._leggi_tlv(richiesta, 0)
            c = mt._figli(richiesta, t[1], t[2])
            imp = mt._figli(richiesta, c[1][1], c[1][2])[1]
            return _token_qualificato(richiesta[imp[1]:imp[2]],
                                      nonce=mt._intero_da(richiesta, c[2][1], c[2][2]))

        for _ in range(4):
            mt.marca_i_registri(self.a, accettazioni=_Registro(), finanza=_Finanza(),
                                giorno="2026-07-21", url="http://tsa.finta",
                                trasporto=rete_qualificata)
        self.assertEqual(len(self.chiamate), 1,
                         "con una marca QUALIFICATA basta una sola richiesta al giorno")

    def test_col_ripiego_si_RIPROVA_per_ottenere_la_qualificata(self):
        """L'altra faccia: se in archivio c'e' solo un ripiego, i giri successivi devono
        riprovare — altrimenti una prova inferiore resterebbe li' tutto il giorno."""
        for _ in range(3):
            mt.marca_i_registri(self.a, accettazioni=_Registro(), finanza=_Finanza(),
                                giorno="2026-07-21", url="http://tsa.finta",
                                trasporto=self._rete_buona)
        self.assertGreater(len(self.chiamate), 1,
                           "col solo ripiego in archivio si deve riprovare")
        riuscite = [r for r in self.a.elenco() if r["stato"] == "ok"]
        self.assertEqual(len(riuscite), 1,
                         "ma senza archiviare doppioni dello stesso rango")

    def test_il_RIPIEGO_GIA_PRESENTE_si_dichiara_riuscito_e_NON_qualificato(self):
        """Righe 763-764, trovate scoperte dalla mutazione il 2026-08-04.

        Quando in archivio c'e' gia' un ripiego e il nuovo tentativo torna ancora di rango
        inferiore, il giro NON archivia un doppione e restituisce
        `{"ok": True, "saltato": "ripiego_gia_presente", "qualificata": False}`.

        Sono due campi, e sbagliarne uno ha conseguenze opposte:
        · `ok` a False farebbe credere che la marcatura di oggi sia FALLITA, quando invece
          la prova c'e' gia' -- e chi legge il registro cerchera' un guasto inesistente;
        · `qualificata` a True direbbe che abbiamo una prova QUALIFICATA quando abbiamo solo
          un ripiego, e si smetterebbe di riprovare per ottenere quella vera. In giudizio e'
          la differenza fra l'art. 41 eIDAS e una data che ci siamo scritti da soli.
        """
        primo = mt.marca_i_registri(self.a, accettazioni=_Registro(), finanza=_Finanza(),
                                    giorno="2026-07-21", url="http://tsa.finta",
                                    trasporto=self._rete_buona)
        self.assertTrue(primo["ok"])
        self.assertFalse(primo["qualificata"], "il primo giro doveva dare un RIPIEGO")

        r = mt.marca_i_registri(self.a, accettazioni=_Registro(), finanza=_Finanza(),
                                giorno="2026-07-21", url="http://tsa.finta",
                                trasporto=self._rete_buona)
        self.assertEqual("ripiego_gia_presente", r.get("saltato"),
                         "il secondo ripiego doveva essere SALTATO, non archiviato")
        self.assertIs(True, r["ok"],
                      "un ripiego gia' presente e' stato dichiarato FALLIMENTO: si cerchera' "
                      "un guasto che non esiste, e la prova c'e' gia'")
        self.assertIs(False, r["qualificata"],
                      "un RIPIEGO e' stato dichiarato QUALIFICATO: si smetterebbe di "
                      "riprovare, e in causa varrebbe come una data scritta da noi")

    def test_una_qualificata_puo_AFFIANCARSI_a_un_ripiego(self):
        """Archivio append-only: la prova migliore si aggiunge, non sostituisce."""
        from test_marca_qualificata import _token_qualificato
        mt.marca_i_registri(self.a, accettazioni=_Registro(), finanza=_Finanza(),
                            giorno="2026-07-21", url="http://tsa.finta",
                            trasporto=self._rete_buona)

        def rete_qualificata(url, richiesta, timeout):
            t = mt._leggi_tlv(richiesta, 0)
            c = mt._figli(richiesta, t[1], t[2])
            imp = mt._figli(richiesta, c[1][1], c[1][2])[1]
            return _token_qualificato(richiesta[imp[1]:imp[2]],
                                      nonce=mt._intero_da(richiesta, c[2][1], c[2][2]))

        r = mt.marca_i_registri(self.a, accettazioni=_Registro(), finanza=_Finanza(),
                                giorno="2026-07-21", url="http://tsa.finta",
                                trasporto=rete_qualificata)
        self.assertTrue(r["ok"])
        self.assertTrue(r["qualificata"])
        ranghi = sorted(x["qualificata"] for x in self.a.elenco()
                        if x["stato"] == "ok")
        self.assertEqual(ranghi, [0, 1], "devono convivere il ripiego e la qualificata")
        self.assertTrue(self.a.gia_marcato("2026-07-21", solo_qualificata=True))

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

    def test_le_prime_due_sono_QUALIFICATE_e_verificabili_da_chiunque(self):
        """LA REGOLA CHE CONTA. Le prime due Autorita' interrogate devono essere
        QUALIFICATE (eIDAS art. 42) **e** i loro token devono verificarsi con il solo
        archivio CA di sistema. Provato dal vivo il 2026-07-21 su 16 endpoint europei:
        ACCV (ES) e QuoVadis EU soddisfano entrambe le condizioni.
        Izenpe (ES) e BOSA (BE) sono qualificate ma richiedono la loro radice: vanno
        bene come RISERVA, mai come prima scelta, altrimenti il perito che riceve il
        `.tsr` non riuscirebbe a verificarlo senza procurarsi altro materiale."""
        prime_due = mt.TSA_QUALIFICATE[:2]
        for url in prime_due:
            self.assertTrue("accv.es" in url or "quovadisglobal.com" in url,
                            "%s non e' fra le qualificate verificabili da chiunque" % url)
        for url in prime_due:
            for solo_riserva in ("izenpe.com", "belgium.be"):
                self.assertNotIn(solo_riserva, url,
                                 "%s e' qualificata ma serve la sua radice: puo' stare "
                                 "solo DOPO le prime due" % solo_riserva)

    def test_mai_le_Autorita_bocciate(self):
        """Apple e FreeTSA: token non verificabili con le CA standard E non qualificate.
        BalTstamp: non ha risposto. Se qualcuno le rimette, questo test lo ferma."""
        for url in mt.TSA_QUALIFICATE + mt.TSA_RIPIEGO:
            for bocciata in ("apple.com", "freetsa.org", "baltstamp"):
                self.assertNotIn(bocciata, url, "%s era stata scartata" % bocciata)

    def test_il_ripiego_non_e_mai_prima_dei_qualificati(self):
        """L'ordine E' la politica: prima l'Europa qualificata, il ripiego solo dopo."""
        lista = mt._tsa_configurate()
        primo_ripiego = min((lista.index(u) for u in mt.TSA_RIPIEGO if u in lista),
                            default=len(lista))
        ultimo_qual = max((lista.index(u) for u in mt.TSA_QUALIFICATE if u in lista),
                          default=-1)
        self.assertGreater(primo_ripiego, ultimo_qual,
                           "un'Autorita' NON qualificata viene interrogata prima di una "
                           "qualificata: si otterrebbe una marca di rango inferiore "
                           "pur avendone a disposizione una qualificata")

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


class TestIMattoniDelFormatoDEVONOFinireEDireIlVero(unittest.TestCase):
    """LE FUNZIONI DI BASSO LIVELLO, PROVATE DIRETTAMENTE.

    LEZIONE DEL 2026-08-01, e vale piu' delle prove che seguono. Avevo gia' scritto sei
    guardie contro `interpreta_risposta` -- l'ingresso pubblico -- e non hanno ucciso NEMMENO
    UN mutante. Motivo: quell'ingresso e' avvolto in un `try/except` che ingoia tutto, quindi
    un guasto la' sotto esce comunque come «non valido» e il mio osservabile non poteva
    vedere niente.

    **Provare attraverso uno strato che nasconde gli errori non prova quello strato.**
    Le funzioni che costruiscono e leggono i byte vanno interrogate DIRETTAMENTE.
    """

    @staticmethod
    def _finisce_entro(fn, *a, secondi=3.0):
        """Esegue `fn` in un filo separato e dice se ha finito in tempo.

        Serve per i tre mutanti che trasformano `while n > 0` in `while n >= 0`: diventano
        cicli INFINITI, e nessun test normale puo' ucciderli perche' il processo si pianta --
        infatti risultavano «non determinabili». Qui il ciclo infinito diventa un ROSSO.
        """
        import threading
        esito = {}

        def _corri():
            try:
                esito["v"] = fn(*a)
            except Exception as e:                        # noqa: BLE001
                esito["e"] = e

        t = threading.Thread(target=_corri, daemon=True)   # daemon: se si pianta, muore col processo
        t.start()
        t.join(secondi)
        return (not t.is_alive()), esito

    def test_i_TRE_COSTRUTTORI_finiscono_sempre(self):
        finito, esito = self._finisce_entro(mt._der_lunghezza, 300)
        self.assertTrue(finito, "_der_lunghezza NON FINISCE: ciclo infinito, il sito si pianta")
        self.assertEqual(b"\x82\x01\x2c", esito.get("v"), "300 in forma lunga e' 82 01 2C")

        finito, esito = self._finisce_entro(mt._der_intero, 1234567)
        self.assertTrue(finito, "_der_intero NON FINISCE: ciclo infinito")
        self.assertEqual(b"\x02\x03\x12\xd6\x87", esito.get("v"))

        finito, esito = self._finisce_entro(mt._der_oid, (1, 2, 840, 113549))
        self.assertTrue(finito, "_der_oid NON FINISCE: ciclo infinito")
        self.assertEqual(b"\x06\x06\x2a\x86\x48\x86\xf7\x0d", esito.get("v"),
                         "l'OID RSA di riferimento non e' quello atteso")

    def test_il_CONFINE_della_forma_corta_e_a_128(self):
        self.assertEqual(b"\x7f", mt._der_lunghezza(127), "127 sta ancora in forma corta")
        self.assertEqual(b"\x81\x80", mt._der_lunghezza(128), "128 passa alla forma lunga")
        self.assertEqual(b"\x00", mt._der_lunghezza(0))

    def test_lo_ZERO_e_i_negativi(self):
        self.assertEqual(b"\x02\x01\x00", mt._der_intero(0), "lo zero DER e' 02 01 00")
        with self.assertRaises(ValueError):
            mt._der_intero(-1)

    def test_un_OID_di_DUE_soli_archi_e_legittimo(self):
        """`if len(archi) < 2: raise`. Col mutante `<= 2` un OID di due archi -- che e'
        perfettamente legale -- verrebbe rifiutato, e con lui ogni richiesta di marca."""
        self.assertEqual(b"\x06\x01\x2a", mt._der_oid((1, 2)))
        with self.assertRaises(ValueError):
            mt._der_oid((1,))

    def test_il_lettore_all_ESTREMO_dei_byte_non_va_oltre(self):
        """`if i >= n: return None`. Col mutante `>` si legge un byte che non c'e'."""
        dati = b"\x30\x00"
        self.assertIsNone(mt._leggi_tlv(dati, len(dati)),
                          "il lettore ha provato a leggere OLTRE la fine dei dati")
        self.assertIsNone(mt._leggi_tlv(b"", 0))
        self.assertIsNotNone(mt._leggi_tlv(dati, 0), "non legge piu' un TLV valido")

    def test_le_LUNGHEZZE_ASSURDE_in_forma_lunga_sono_rifiutate(self):
        """`if conta == 0 or conta > 4 or j + conta > n: return None` -- tre condizioni,
        e ognuna serve: zero byte di lunghezza, troppi byte, oppure una lunghezza che
        sborda dal pacchetto."""
        self.assertIsNone(mt._leggi_tlv(b"\x30\x80\x00", 0) if False else
                          mt._leggi_tlv(b"\x30\x85\x01\x02\x03\x04\x05", 0),
                          "accettati 5 byte di lunghezza (il massimo sensato e' 4)")
        self.assertIsNone(mt._leggi_tlv(b"\x30\x84\x01", 0),
                          "accettata una lunghezza che sborda dal pacchetto")
        self.assertIsNone(mt._leggi_tlv(b"\x30\x81", 0),
                          "accettata una forma lunga senza i byte della lunghezza")

    def test_una_lunghezza_su_QUATTRO_byte_e_ancora_legittima(self):
        """`conta > 4` e' il tetto: quattro byte di lunghezza sono ANCORA validi, cinque no.
        Col mutante `conta >= 4` verrebbe rifiutato un gettone grande ma perfettamente
        regolare -- e l'Autorita' li manda cosi' quando il certificato e' incluso."""
        buono = b"\x30\x84\x00\x00\x00\x02\x01\x02"        # SEQUENCE, lunghezza 2 su 4 byte
        t = mt._leggi_tlv(buono, 0)
        self.assertIsNotNone(t, "rifiutata una lunghezza su 4 byte, che e' legittima")
        self.assertEqual(0x30, t[0])
        self.assertEqual(2, t[2] - t[1], "la lunghezza letta non e' 2")

    def test_un_TLV_che_NON_AVANZA_non_manda_in_ciclo_il_lettore(self):
        """`if t[3] <= i: break` in `_figli`: e' la protezione contro un elemento che non
        fa avanzare la lettura. Senza, il lettore girerebbe per sempre sullo stesso byte."""
        finito, _ = self._finisce_entro(lambda: list(mt._figli(b"\x30\x00" * 6, 0, 12)))
        self.assertTrue(finito, "_figli NON FINISCE su elementi che non avanzano")

    def test_e_i_CASI_VERI_continuano_a_funzionare(self):
        """L'altra direzione: irrigidire i mattoni non deve rompere la costruzione vera."""
        r = mt.costruisci_richiesta(IMPRONTA, 12345)
        self.assertTrue(r.startswith(b"\x30"), "la richiesta non e' piu' una SEQUENCE DER")
        self.assertIn(IMPRONTA, r, "l'impronta non e' piu' dentro la richiesta")


class TestIBuchiDelLettoreTrovatiDallaMUTAZIONE(unittest.TestCase):
    """I PUNTI CHE LA MUTAZIONE HA TROVATO SCOPERTI (2026-08-04).

    Campagna sul modulo intero: 112 punti mutabili, 29 SOPRAVVISSUTI -- cioe' 29 righe che
    si potevano cambiare senza che NESSUNO dei nove file di test se ne accorgesse. Non
    significa che il codice sia sbagliato: significa che se un giorno una di quelle righe
    cambiasse -- per errore, per una riscrittura, o per un mutante lasciato dentro come il
    2026-08-03 -- la suite resterebbe VERDE.

    Qui si chiudono i sei del LETTORE DI BYTE. Ogni prova e' stata costruita calcolando a
    mano i byte che distinguono il codice giusto dal mutante, e VISTA ROSSA sul mutante
    prima di essere considerata buona.

    ⚠️ Si interrogano le funzioni DIRETTAMENTE, mai attraverso `interpreta_risposta`: quello
    e' avvolto in un `try/except` che ingoia tutto, e sei guardie scritte cosi' il 2026-08-01
    non uccisero nemmeno un mutante. Provare attraverso uno strato che nasconde gli errori
    non prova quello strato.
    """

    def test_una_SEQUENCE_VUOTA_in_forma_lunga_e_valida(self):
        """`j + conta > n` (riga 205). Il tetto `conta > 4` era gia' sorvegliato; QUESTO
        confronto no. Col mutante `>=`, un elemento i cui byte di lunghezza arrivano
        esattamente in fondo al pacchetto viene RIFIUTATO anche se e' perfettamente valido.

        `30 81 00` = SEQUENCE vuota, lunghezza 0 dichiarata in forma lunga su 1 byte:
        n=3, j=2, conta=1 -> j+conta = 3 = n. Col `>` originale passa, col `>=` muore.
        """
        t = mt._leggi_tlv(b"\x30\x81\x00", 0)
        self.assertIsNotNone(t, "rifiutata una SEQUENCE VUOTA in forma lunga, che e' valida")
        self.assertEqual((0x30, 3, 3, 3), t, "letta male: contenuto vuoto, elemento finito a 3")

    def test_CINQUE_byte_di_lunghezza_sono_rifiutati_ANCHE_se_il_valore_e_piccolo(self):
        """I due `or` di riga 205, e sono il caso piu' istruttivo di tutta la campagna.

        Una guardia esisteva gia' (`test_le_LUNGHEZZE_ASSURDE_in_forma_lunga_sono_rifiutate`)
        e usava `30 85 01 02 03 04 05`: cinque byte di lunghezza, ma con un VALORE enorme.
        Col mutante quel caso viene rifiutato lo stesso -- non dal tetto `conta > 4`, ma dal
        controllo successivo `fine > n`. **Passava per il motivo sbagliato**, ed e' per questo
        che i due mutanti sopravvivevano a tutti e nove i file di test.

        Qui la lunghezza sta ancora su cinque byte ma vale 2: nessun altro controllo puo'
        salvarla, e solo il tetto `conta > 4` la ferma.
        `30 85 | 00 00 00 00 02 | 01 02` -> n=9, conta=5, j+conta=7 <= 9.
        """
        self.assertIsNone(mt._leggi_tlv(b"\x30\x85\x00\x00\x00\x00\x02\x01\x02", 0),
                          "accettata una lunghezza su CINQUE byte: il tetto di quattro non "
                          "ferma piu' niente, e un pacchetto malformato entra nel lettore")

    def test_un_elemento_che_NON_AVANZA_viene_fermato_DAVVERO(self):
        """`if t[3] <= i: break` in `_figli` (riga 226) -- ramo DIFENSIVO.

        Oggi non si raggiunge, perche' `_leggi_tlv` restituisce sempre una fine maggiore
        dell'inizio. Ma la D19 vieta di dichiararlo equivalente per questo: «oggi non si
        raggiunge PER MERITO DI UN'ALTRA FUNZIONE, e' una conclusione con una premessa».
        Lo stato impossibile si costruisce a mano, adesso, che costa tre righe.

        La guardia esistente usa `b"\\x30\\x00"*6`, elementi che avanzano di 2 byte: prova
        che `_figli` finisce, ma NON attraversa mai questo ramo -- ed e' per questo che il
        mutante sopravviveva.
        """
        import threading
        vero = mt._leggi_tlv
        self.addCleanup(setattr, mt, "_leggi_tlv", vero)
        # un lettore che dichiara di aver finito ESATTAMENTE dove era iniziato
        mt._leggi_tlv = lambda dati, i: (0x30, i, i, i)

        esito = {}

        def _corri():
            esito["v"] = list(mt._figli(b"\x30\x00\x30\x00", 0, 4))

        t = threading.Thread(target=_corri, daemon=True)
        t.start()
        t.join(3.0)
        self.assertFalse(t.is_alive(),
                         "_figli NON SI FERMA su un elemento che non avanza: il lettore "
                         "girerebbe per sempre sullo stesso byte e il sito si pianterebbe")

    def test_il_TETTO_di_profondita_e_a_24_COMPRESO(self):
        """`if profondita > 24` (riga 258). Col mutante `>=` il tetto scende a 23 e un
        OCTET STRING annidato a 24 livelli -- struttura legittima -- non verrebbe piu'
        trovato: il TSTInfo dentro il CMS sparirebbe e il token risulterebbe illeggibile."""
        dentro = b"\x04\x01X"                       # OCTET STRING con dentro 'X'
        for _ in range(24):                          # 24 SEQUENCE annidate intorno
            dentro = b"\x30" + mt._der_lunghezza(len(dentro)) + dentro
        trovati = mt._tutti_octet_string(dentro, 0, len(dentro))
        self.assertIn(b"X", trovati,
                      "un OCTET STRING a 24 livelli non viene piu' trovato: il tetto e' "
                      "sceso di uno e il TSTInfo dentro un CMS annidato sparirebbe")

    def test_un_ORARIO_SENZA_LA_Z_non_e_una_prova(self):
        """`if not t.endswith("Z") or len(t) < 15` (riga 298).

        Nei token RFC 3161 la `Z` finale significa «questo orario e' UTC». Col mutante `and`,
        una data lunga abbastanza ma SENZA la Z viene ACCETTATA: si prenderebbe per buono un
        orario di cui non si conosce il fuso. Una marca temporale di cui non sai il fuso non
        prova niente -- ed e' proprio l'ora certificata che in giudizio sposta l'onere della
        prova sulla controparte (eIDAS art. 41).
        """
        self.assertIsNone(mt._gen_time_a_epoch(b"202608031200000"),
                          "accettato un orario SENZA la Z finale: fuso ignoto, prova nulla")
        self.assertIsNotNone(mt._gen_time_a_epoch(b"20260803120000Z"),
                             "l'altra direzione: un orario CORRETTO deve continuare a passare")

    def test_UN_SOLO_zero_non_chiude_un_contenuto_a_lunghezza_indefinita(self):
        """Primo `and` di riga 197. Il terminatore del BER indefinito e' DUE zeri, non uno.
        Col mutante `or`, un singolo `00` chiuderebbe il contenuto in anticipo e il lettore
        restituirebbe una struttura TRONCATA come se fosse valida.

        `30 80 | 04 01 41 | 00 05 | 00 00`: a meta' c'e' uno `00` seguito da `05`. Il codice
        giusto NON lo prende per terminatore, prova a leggere un elemento con tag 00 e
        lunghezza 5 che sborda -> rifiuta tutto. Il mutante lo prende per terminatore e
        restituisce un elemento.
        """
        self.assertIsNone(mt._leggi_tlv(b"\x30\x80\x04\x01\x41\x00\x05\x00\x00", 0),
                          "un solo 00 ha chiuso il contenuto indefinito: struttura troncata "
                          "accettata come valida")

    def test_lo_zero_del_terminatore_deve_essere_il_PRIMO_dei_due(self):
        """Secondo `and` di riga 197. Col mutante la condizione diventa
        `(dati[k]==0 and k+1<n) or dati[k+1]==0`: basta che il byte SUCCESSIVO sia zero, e
        il contenuto si chiude nel posto sbagliato.

        `30 80 | 04 00 | 00 00`: a k=2 c'e' `04` (tag) seguito da `00` (lunghezza zero).
        Il codice giusto legge l'OCTET STRING vuoto e trova il terminatore a k=4.
        Il mutante si ferma subito a k=2 e restituisce un contenuto vuoto.
        """
        t = mt._leggi_tlv(b"\x30\x80\x04\x00\x00\x00", 0)
        self.assertEqual((0x30, 2, 4, 6), t,
                         "il contenuto indefinito si e' chiuso nel posto sbagliato: un byte "
                         "di LUNGHEZZA zero e' stato scambiato per il terminatore")

    def test_il_terminatore_a_UN_BYTE_dalla_fine_non_fa_uscire_dai_byte(self):
        """`k + 1 < n` di riga 197. Col mutante `<=`, quando manca un solo byte alla fine il
        lettore legge `dati[k+1]` FUORI dal pacchetto: IndexError, cioe' un'eccezione grezza
        invece di un rifiuto pulito. Una risposta malformata di una TSA non deve poter far
        esplodere il lettore.

        `30 80 | 41 00 | 00`: l'ultimo `00` sta esattamente all'ultimo byte.
        """
        self.assertIsNone(mt._leggi_tlv(b"\x30\x80\x41\x00\x00", 0),
                          "il lettore non ha rifiutato pulitamente un contenuto indefinito "
                          "troncato a un byte dalla fine")


class TestIBuchiDelGIROTrovatiDallaMUTAZIONE(unittest.TestCase):
    """Gli ultimi punti scoperti: la richiesta alla TSA, l'apertura dell'archivio e i due
    registri d'errore (campagna 2026-08-04).

    Due di questi sono `exc_info=True` nei log. Sembra un dettaglio e non lo e': senza la
    traccia dell'eccezione, il registro dice CHE qualcosa e' andato storto ma non DOVE --
    ed e' l'unica cosa che resta quando il guasto e' gia' passato. E' la Regola Ferrea 9,
    «l'osservabile debole e' un difetto».
    """

    def _registri_del_logger(self):
        """Attacca un raccoglitore al logger del modulo e lo stacca a fine prova."""
        import logging
        raccolti = []

        class _Raccoglitore(logging.Handler):
            def emit(self, record):
                raccolti.append(record)

        h = _Raccoglitore()
        mt.logger.addHandler(h)
        self.addCleanup(mt.logger.removeHandler, h)
        return raccolti

    def test_una_richiesta_NON_COSTRUIBILE_e_un_fallimento_dichiarato(self):
        """Riga 465. Col mutante `True`, un'impronta di lunghezza sbagliata -- cioe' una
        richiesta che non si e' nemmeno riusciti a costruire -- verrebbe restituita come
        marca OTTENUTA. Si archivierebbe un successo per una richiesta mai partita."""
        r = mt.chiedi_marca(b"troppo-corta")
        self.assertFalse(r["ok"],
                         "una richiesta MAI COSTRUITA e' stata dichiarata riuscita")
        self.assertEqual("richiesta_non_costruita", r["motivo"])

    def test_nessun_allarme_se_una_TSA_qualificata_consegna_una_marca_QUALIFICATA(self):
        """Riga 488: `if not esito["qualificata"] and indirizzo in TSA_QUALIFICATE`.

        Col mutante `or` l'allarme suona anche quando va tutto bene, perche' basta che
        l'indirizzo sia nell'elenco dei qualificati. La Regola Ferrea 10 e' esplicita: un
        FALSO ALLARME e' un difetto quanto un allarme mancato, perche' insegna a ignorare
        i segnali -- e questo segnala che un prestatore ha perso la qualifica eIDAS.
        """
        vero = mt.e_qualificata
        self.addCleanup(setattr, mt, "e_qualificata", vero)
        mt.e_qualificata = lambda token: True          # la marca E' qualificata
        indirizzo = mt.TSA_QUALIFICATE[0]
        raccolti = self._registri_del_logger()
        r = mt.chiedi_marca(IMPRONTA, url=indirizzo,
                            trasporto=lambda u, d, t: _risposta(IMPRONTA, nonce=None))
        self.assertTrue(r["ok"], "la marca non e' stata ottenuta: prova mal costruita")
        avvisi = [x for x in raccolti if "NON ha piu'" in str(x.getMessage())]
        self.assertEqual([], avvisi,
                         "ALLARME FALSO: e' stato segnalato che un prestatore ha perso la "
                         "qualifica eIDAS mentre la marca era regolarmente qualificata")

    def test_l_archivio_IN_MEMORIA_si_usa_anche_da_un_altro_filo(self):
        """Riga 536: `check_same_thread=False`. Col mutante `True`, l'archivio in memoria
        esplode appena viene usato da un filo diverso da quello che l'ha aperto -- ed e'
        esattamente cio' che fa il giro di marcatura, che gira in un filo di fondo."""
        import threading
        mem = mt.crea_archivio_marche(":memory:")
        self.assertIsNotNone(mem)
        esito = {}

        def _da_un_altro_filo():
            try:
                esito["v"] = mem.conta()
            except Exception as e:                     # noqa: BLE001
                esito["e"] = e

        t = threading.Thread(target=_da_un_altro_filo)
        t.start()
        t.join(10)
        self.assertNotIn("e", esito,
                         "l'archivio in memoria esplode se usato da un altro filo: %r"
                         % (esito.get("e"),))
        self.assertEqual(0, esito.get("v"))

    def test_un_archivio_che_non_si_apre_lascia_la_TRACCIA_dell_errore(self):
        """Riga 712: `exc_info=True`. Col mutante `False` il registro dice «archivio non
        inizializzato» e basta: nessuna traccia, nessun perche'. Chi legge il log domani
        mattina sa che e' successo e non sa dove guardare."""
        raccolti = self._registri_del_logger()
        a = mt.crea_archivio_marche(os.path.join(tempfile.mkdtemp(), "non", "esiste", "x.db"))
        self.assertIsNone(a, "un percorso impossibile ha comunque aperto un archivio")
        righe = [x for x in raccolti if "archivio non inizializzato" in str(x.getMessage())]
        self.assertTrue(righe, "l'archivio non si e' aperto e NESSUNO l'ha scritto")
        # ⛔ NON `assertIsNotNone`: con `exc_info=False` la libreria mette dentro il record
        # il valore `False`, non `None` -- e `assertIsNotNone(False)` PASSA. Ci sono cascato
        # scrivendo questa stessa guardia il 2026-08-04, e il mutante e' sopravvissuto.
        self.assertTrue(righe[0].exc_info,
                        "il registro dice CHE e' fallito ma non DOVE: la traccia "
                        "dell'eccezione e' stata persa (exc_info=%r)" % (righe[0].exc_info,))

    def test_un_giro_che_esplode_lascia_la_TRACCIA_dell_errore(self):
        """Riga 781: `exc_info=True` nel guscio che ISOLA il giro di marcatura. Questo e'
        il piu' importante dei due: il giro e' avvolto in un `except Exception` apposta per
        non far cadere il sito, quindi la traccia nel log e' l'UNICA cosa che resta di un
        guasto la' dentro. Senza, un difetto puo' vivere per mesi dicendo solo «fallito»."""
        raccolti = self._registri_del_logger()
        r = mt.marca_i_registri(archivio=None, giorno="2026-08-04")   # archivio None -> esplode
        self.assertFalse(r["ok"])
        righe = [x for x in raccolti if "giro fallito" in str(x.getMessage())]
        self.assertTrue(righe, "il giro e' fallito e nessuno l'ha scritto")
        # ⛔ vedi la nota nella guardia gemella: `exc_info=False` finisce nel record come
        # `False`, e un `assertIsNotNone` non lo vedrebbe.
        self.assertTrue(righe[0].exc_info,
                        "il giro e' fallito lasciando solo «fallito»: senza la traccia "
                        "dell'eccezione un difetto qui dentro e' invisibile "
                        "(exc_info=%r)" % (righe[0].exc_info,))


class TestIBuchiDellArchivioTrovatiDallaMUTAZIONE(unittest.TestCase):
    """I punti scoperti dentro l'ARCHIVIO delle marche (campagna 2026-08-04).

    L'archivio e' il posto dove la prova legale viene conservata. Un guasto qui non fa
    cadere il sito: fa conservare una prova SBAGLIATA, e ce ne si accorge in causa.
    Le guardie che seguono controllano il CONTENUTO archiviato, non solo che la scrittura
    sia andata a buon fine -- «ha scritto» e «ha scritto la cosa giusta» sono due domande
    diverse, e i mutanti vivono nello scarto.
    """

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.a = mt.crea_archivio_marche(os.path.join(self.d, "marche.db"))

    def _ok(self):
        return mt.interpreta_risposta(_risposta(IMPRONTA, nonce=5), IMPRONTA, 5)

    def test_la_POLICY_dichiarata_dall_Autorita_viene_archiviata(self):
        """Riga 616: `str(esito.get("policy") or "")`. Col mutante `and` il campo diventa
        SEMPRE vuoto. La policy e' l'OID con cui l'Autorita' dichiara sotto quale regime ha
        emesso la marca -- e' lei che distingue una marca QUALIFICATA da una ordinaria.
        Perderla significa archiviare una prova di cui non si sa piu' il regime."""
        r = self.a.scrivi(giorno="2026-08-04", ambito="registri", impronta=IMPRONTA.hex(),
                          canonico="X",
                          esito={"ok": True, "policy": "0.4.0.19422.1.1", "seriale": "7",
                                 "gen_time": 1780000000, "token": b"\x30\x03\x02\x01\x00"})
        self.assertTrue(r["ok"])
        self.assertEqual("0.4.0.19422.1.1", self.a.elenco()[0]["policy"],
                         "la policy dell'Autorita' NON e' stata archiviata: la marca resta "
                         "senza il regime sotto cui e' stata emessa")

    def test_il_MOTIVO_di_un_fallimento_viene_archiviato_per_intero(self):
        """Riga 620: `str(esito.get("motivo") or "errore")`. Col mutante `and` ogni
        fallimento viene archiviato come generico «errore». Il registro degli insuccessi
        serve a capire PERCHE' una marca non c'e': appiattirlo lo rende inutile."""
        self.a.scrivi(giorno="2026-08-04", ambito="registri", impronta=IMPRONTA.hex(),
                      canonico="X", esito={"ok": False, "motivo": "tsa_irraggiungibile"})
        self.assertEqual("tsa_irraggiungibile", self.a.elenco()[0]["errore"],
                         "il motivo vero e' stato sostituito da un generico «errore»: il "
                         "registro dei fallimenti non dice piu' cosa e' successo")

    def test_una_SECONDA_marca_riuscita_nello_stesso_giorno_si_dichiara_DUPLICATO(self):
        """Riga 631: `{"ok": ok, "id": None, "duplicato": True}`. Col mutante `False` chi
        chiama non sa piu' distinguere «l'ho gia' fatto ieri» da «non l'ho fatto»: il giro
        riproverebbe all'infinito, o peggio si convincerebbe di non avere la marca."""
        self.a.scrivi(giorno="2026-08-04", ambito="registri", impronta=IMPRONTA.hex(),
                      canonico="X", esito=self._ok())
        r2 = self.a.scrivi(giorno="2026-08-04", ambito="registri", impronta=IMPRONTA.hex(),
                           canonico="X", esito=self._ok())
        self.assertIs(True, r2.get("duplicato"),
                      "una seconda marca riuscita nello stesso giorno non viene dichiarata "
                      "duplicato: chi chiama non sa piu' se la marca c'e' gia'")

    def test_una_riga_SENZA_token_non_restituisce_byte_vuoti_ma_NULLA(self):
        """Riga 655: `if r is None or not r["token_b64"]: return None`. Col mutante `and`
        una riga senza token restituisce `b""` invece di `None`. Sono cose diverse: `None`
        dice «non c'e' nessuna prova», `b""` e' una prova VUOTA -- e chi la salva su file
        produce un `.tsr` da zero byte che sembra un token e non lo e'."""
        r = self.a.scrivi(giorno="2026-08-04", ambito="registri", impronta=IMPRONTA.hex(),
                          canonico="X", esito={"ok": False, "motivo": "rete_giu"})
        self.assertIsNone(self.a.token(r["id"]),
                          "una riga senza token ha restituito byte vuoti invece di NULLA: "
                          "si genererebbe un file .tsr vuoto spacciato per una prova")

    def test_verificare_una_riga_SENZA_token_dice_NO(self):
        """Riga 676: `return {"ok": False, "motivo": "senza_token"}`. Col mutante `True`
        una riga priva di token verrebbe dichiarata VERIFICATA. E' il peggiore di questa
        famiglia: la macchina direbbe «prova valida» dove non c'e' nessuna prova."""
        r = self.a.scrivi(giorno="2026-08-04", ambito="registri", impronta=IMPRONTA.hex(),
                          canonico="X", esito={"ok": False, "motivo": "rete_giu"})
        v = self.a.verifica(r["id"])
        self.assertFalse(v["ok"], "una riga SENZA TOKEN e' stata dichiarata VERIFICATA")
        self.assertEqual("senza_token", v["motivo"])

    def test_un_archivio_ILLEGGIBILE_dice_NO(self):
        """Riga 681: `return {"ok": False, "motivo": "archivio_illeggibile"}`. Col mutante
        `True`, una riga la cui impronta non e' nemmeno esadecimale -- cioe' un archivio
        corrotto o manomesso -- verrebbe dichiarata valida senza aver confrontato niente."""
        r = self.a.scrivi(giorno="2026-08-04", ambito="registri",
                          impronta="questa-non-e-esadecimale", canonico="X",
                          esito=self._ok())
        v = self.a.verifica(r["id"])
        self.assertFalse(v["ok"],
                         "un archivio ILLEGGIBILE e' stato dichiarato verificato: si "
                         "confermerebbe una prova senza averla potuta confrontare")
        self.assertEqual("archivio_illeggibile", v["motivo"])


class TestIBuchiDiInterpretaRispostaTrovatiDallaMUTAZIONE(unittest.TestCase):
    """I punti scoperti dentro `interpreta_risposta` (campagna 2026-08-04).

    ⚠️ La lezione del 2026-08-01 vale ancora: guardie generiche su questo ingresso non
    uccidono niente, perche' qualunque guasto esce comunque come «non valido». Qui NON si
    controlla solo `ok is False`: si pretende anche il MOTIVO ESATTO. E' la differenza fra
    «ha detto no» e «ha detto no PER LA RAGIONE GIUSTA» -- e i mutanti vivono precisamente
    in quello scarto, perche' cambiano la ragione lasciando intatto il no.
    """

    IMPR = b"\x11" * 32

    def test_il_primo_campo_DEVE_essere_lo_stato(self):
        """Righe 375-376. `if not campi or campi[0][0] != 0x30: return manca_stato`.

        `30 03 | 02 01 00` = SEQUENCE che comincia con un INTEGER invece che con la
        SEQUENCE di stato. Col mutante `and` il controllo non scatta e si prosegue a leggere
        una struttura che non c'e'; col mutante `False -> True` la risposta malformata
        verrebbe dichiarata VALIDA.
        """
        r = mt.interpreta_risposta(b"\x30\x03\x02\x01\x00", self.IMPR, 1)
        self.assertFalse(r["ok"], "una risposta senza il campo di stato e' stata ACCETTATA")
        self.assertEqual("manca_stato", r["motivo"],
                         "il motivo non e' quello giusto: il controllo sul primo campo non "
                         "ha scattato e l'errore e' stato scoperto piu' avanti, per caso")

    def test_una_SEQUENCE_VUOTA_non_fa_esplodere_la_lettura_dello_stato(self):
        """Sempre riga 375, l'altra meta': con `and` al posto di `or`, una risposta con
        ZERO campi arriverebbe a `campi[0][0]` su una lista vuota -- IndexError grezzo
        invece di un rifiuto pulito."""
        r = mt.interpreta_risposta(b"\x30\x00", self.IMPR, 1)
        self.assertFalse(r["ok"])
        self.assertEqual("manca_stato", r["motivo"])

    def test_lo_stato_DEVE_essere_un_INTERO(self):
        """Righe 378-379. `if not stato_campi or stato_campi[0][0] != 0x02`.

        `30 04 | 30 02 | 04 00` = la SEQUENCE di stato c'e', ma dentro ha un OCTET STRING
        invece dell'INTEGER dello stato. Col mutante `and` si prosegue e si legge come
        numero qualcosa che non lo e'; col `False -> True` la risposta viene dichiarata buona.
        """
        r = mt.interpreta_risposta(b"\x30\x04\x30\x02\x04\x00", self.IMPR, 1)
        self.assertFalse(r["ok"], "uno stato che non e' un INTERO e' stato ACCETTATO")
        self.assertEqual("stato_illeggibile", r["motivo"],
                         "il motivo non e' quello giusto: si e' letto come numero un campo "
                         "che non e' un numero, e l'errore e' emerso altrove")

    def test_lo_stato_DEVE_esserci_DAVVERO(self):
        """Sempre righe 378-379: SEQUENCE di stato VUOTA -> `stato_campi` vuota."""
        r = mt.interpreta_risposta(b"\x30\x02\x30\x00", self.IMPR, 1)
        self.assertFalse(r["ok"])
        self.assertEqual("stato_illeggibile", r["motivo"])

    def test_la_ricerca_del_token_NON_esce_dal_contenuto_della_SEQUENCE(self):
        """Riga 391: `while i < t[2]`. Col mutante `<=` il ciclo fa UN GIRO IN PIU' quando
        l'ultimo elemento finisce esattamente dove finisce la SEQUENCE -- e legge byte che
        stanno FUORI dal contenuto dichiarato, prendendoli per il token.

        Significa archiviare come «marca temporale» dei byte che l'Autorita' non ha mai messo
        li' dentro. Non e' un errore di stile: e' una prova costruita con materiale estraneo.

        Come il 401, e' distinguibile solo costruendo a mano lo stato che `_figli` e questo
        ciclo non possono avere naturalmente (usano lo stesso lettore, quindi concordano
        sempre). La D19 impone di provarlo comunque: il ramo esiste per il giorno in cui
        smettessero di concordare.
        """
        vero_figli = mt._figli
        self.addCleanup(setattr, mt, "_figli", vero_figli)
        #  SEQUENCE(5) { SEQUENCE(3){ INTEGER 0 } }  +  04 01 41  FUORI dal contenuto
        dati = b"\x30\x05" + b"\x30\x03\x02\x01\x00" + b"\x04\x01\x41"
        n = {"c": 0}

        def _figli_che_dichiara_due_campi(d, a, b):
            n["c"] += 1
            if n["c"] == 1:
                return [(0x30, 4, 7), (0x04, 9, 10)]   # due campi: si supera «manca_token»
            return vero_figli(d, a, b)

        mt._figli = _figli_che_dichiara_due_campi
        r = mt.interpreta_risposta(dati, self.IMPR, 1)
        self.assertFalse(r["ok"])
        self.assertEqual("token_illeggibile", r["motivo"],
                         "il ciclo e' uscito dal contenuto della SEQUENCE e ha preso per "
                         "token dei byte che le stanno FUORI: si archivierebbe come prova "
                         "materiale che l'Autorita' non ha mai emesso")

    def test_se_il_token_NON_si_riesce_a_isolare_la_risposta_e_RIFIUTATA(self):
        """Righe 391 e 400-401 -- ramo DIFENSIVO, e la D19 vieta di dichiararlo equivalente
        solo perche' «oggi non si raggiunge»: oggi non si raggiunge PER MERITO di `_figli`,
        che concorda sempre con il ciclo che segue. Il giorno che smettessero di concordare,
        questo ramo e' l'unica cosa fra una risposta illeggibile e un token inventato.

        Lo stato impossibile si costruisce a mano: `_figli` dichiara DUE campi, ma il lettore
        di elementi si rifiuta di rileggerli. Il ciclo non trova il secondo elemento e deve
        rifiutare -- non proseguire con un token mai isolato.
        """
        vero_figli, vero_tlv = mt._figli, mt._leggi_tlv
        self.addCleanup(setattr, mt, "_figli", vero_figli)
        self.addCleanup(setattr, mt, "_leggi_tlv", vero_tlv)
        dati = b"\x30\x05\x30\x03\x02\x01\x00"     # SEQUENCE { SEQUENCE { INTEGER 0 } }
        chiamate = {"tlv": 0, "figli": 0}

        def _tlv_bugiardo(d, i):
            chiamate["tlv"] += 1
            if chiamate["tlv"] == 1:          # la prima lettura, quella d'ingresso, e' vera
                return vero_tlv(d, i)
            return None                        # poi il lettore «non vede piu' niente»

        def _figli_bugiardo(d, a, b):
            chiamate["figli"] += 1
            if chiamate["figli"] == 1:
                return [(0x30, 4, 7), (0x04, 7, 7)]    # dichiara DUE campi: c'e' un token
            return [(0x02, 6, 7)]                       # lo stato e' un INTERO regolare

        mt._figli = _figli_bugiardo
        mt._leggi_tlv = _tlv_bugiardo
        r = mt.interpreta_risposta(dati, self.IMPR, 1)
        self.assertFalse(r["ok"],
                         "il token non e' stato isolato eppure la risposta e' stata "
                         "dichiarata VALIDA: si archivierebbe una prova inesistente")
        self.assertEqual("token_illeggibile", r["motivo"],
                         "il motivo non dice che il token e' illeggibile")


class TestIlLettoreDiBYTENonSiFaIngannare(unittest.TestCase):
    """IL PARSER DEI GETTONI, MESSO ALLA PROVA COI BYTE ROTTI.

    La mutazione del 2026-08-01 ha trovato che quasi tutti i confini del lettore DER/ASN.1
    non erano sorvegliati: 12 sopravvissuti e 3 che facevano addirittura INCHIODARE i test
    (cicli `while n > 0` che diventano infiniti con `>=`).

    Prove sui singoli confini sarebbero fragili e non direbbero la cosa importante. La
    domanda vera su un lettore di byte e' un'altra, e ha due facce:
      1. dandogli in pasto roba rotta, puo' ESPLODERE in faccia a chi lo usa?
      2. e — molto peggio — puo' dichiarare VALIDA una prova che non lo e'?

    La seconda e' quella che conta davvero: questo modulo da' **data certa** ai contratti e
    alle accettazioni. Se accetta un gettone falso, le prove restano al loro posto e
    smettono di valere -- e ce ne accorgeremmo solo davanti a un giudice.

    ⚠️ Nessuna di queste prove tocca la rete: sono byte costruiti qui dentro.
    """

    def _buona(self):
        return _risposta(IMPRONTA, nonce=99)

    def test_una_risposta_TRONCATA_a_QUALSIASI_lunghezza_non_esplode_ne_inganna(self):
        """Il caso piu' realistico di tutti: la rete taglia la risposta a meta'.
        Si prova OGNI possibile punto di taglio, non uno scelto a caso."""
        buona = self._buona()
        for taglio in range(0, len(buona)):
            pezzo = buona[:taglio]
            try:
                e = mt.interpreta_risposta(pezzo, IMPRONTA, 99)
            except Exception as exc:                      # noqa: BLE001 - e' il punto
                self.fail("il lettore ESPLODE su una risposta troncata a %d byte: %s: %s"
                          % (taglio, type(exc).__name__, exc))
            if e and e.get("ok"):
                self.fail("una risposta TRONCATA a %d byte e' stata dichiarata VALIDA: la "
                          "prova legale non prova piu' niente" % taglio)

    def test_un_BYTE_CAMBIATO_non_rende_valida_una_prova_falsa(self):
        """Manomissione mirata: si cambia un byte per volta e si pretende che il lettore
        non dica mai «ok» su qualcosa che non e' piu' il gettone originale."""
        buona = self._buona()
        atteso = mt.interpreta_risposta(buona, IMPRONTA, 99)
        self.assertTrue(atteso["ok"], "la risposta buona non passa: la prova non vale")
        for i in range(0, len(buona), 7):                 # a campione: uno ogni 7 byte
            rotta = bytearray(buona)
            rotta[i] ^= 0xFF
            try:
                e = mt.interpreta_risposta(bytes(rotta), IMPRONTA, 99)
            except Exception as exc:                      # noqa: BLE001
                self.fail("il lettore ESPLODE cambiando il byte %d: %s: %s"
                          % (i, type(exc).__name__, exc))
            if e and e.get("ok"):
                # un byte cambiato puo' cadere in una zona non significativa: allora l'ora
                # e l'impronta devono restare quelle vere, altrimenti e' una prova falsa.
                self.assertEqual(IMPRONTA.hex(), e.get("impronta_hex"),
                                 "byte %d cambiato: dichiarata valida una marca su un'ALTRA "
                                 "impronta" % i)

    def test_ROBACCIA_qualunque_non_diventa_mai_una_prova(self):
        import hashlib
        for seme in range(60):
            robaccia = hashlib.sha256(bytes([seme])).digest() * (1 + seme % 5)
            try:
                e = mt.interpreta_risposta(robaccia, IMPRONTA, 99)
            except Exception as exc:                      # noqa: BLE001
                self.fail("il lettore ESPLODE su byte casuali (seme %d): %s: %s"
                          % (seme, type(exc).__name__, exc))
            self.assertFalse(e and e.get("ok"),
                             "byte casuali (seme %d) dichiarati marca valida" % seme)

    def test_una_LUNGHEZZA_ASSURDA_non_manda_il_lettore_fuori_strada(self):
        """Bomba classica su un parser: si dichiara una lunghezza enorme in un pacchetto
        piccolo. Deve rifiutare, non tentare di leggere memoria che non c'e'."""
        for dichiarata in (b"\x84\x7f\xff\xff\xff", b"\x83\xff\xff\xff", b"\x82\xff\xff"):
            pacchetto = b"\x30" + dichiarata + b"\x02\x01\x00"
            try:
                e = mt.interpreta_risposta(pacchetto, IMPRONTA, 99)
            except Exception as exc:                      # noqa: BLE001
                self.fail("lunghezza assurda %r fa ESPLODERE il lettore: %s"
                          % (dichiarata, exc))
            self.assertFalse(e and e.get("ok"))

    def test_il_lettore_FINISCE_SEMPRE_anche_sui_casi_peggiori(self):
        """I tre mutanti che hanno fatto INCHIODARE i test erano cicli `while n > 0`
        diventati infiniti. Qui si pretende che il lettore termini in fretta anche sugli
        ingressi piu' cattivi: un parser che non finisce e' un sito che si pianta."""
        import time as _t
        casi = [b"\x30\x80" + b"\x30\x80" * 40,          # annidamento indefinito profondo
                b"\x30\x80" + b"\xff" * 500,
                b"\x02" + b"\xff" * 300,
                bytes(2000)]
        for k, caso in enumerate(casi):
            t0 = _t.time()
            try:
                mt.interpreta_risposta(caso, IMPRONTA, 99)
            except Exception:                             # noqa: BLE001
                pass                                      # l'esplosione la giudicano gli altri test
            durata = _t.time() - t0
            self.assertLess(durata, 5.0,
                            "il lettore ci ha messo %.1fs sul caso %d: sospetto ciclo che "
                            "non finisce" % (durata, k))

    def test_e_la_risposta_BUONA_continua_a_passare(self):
        """L'altra direzione, obbligatoria: irrigidire il lettore non deve fargli rifiutare
        i gettoni veri. Un falso allarme qui bloccherebbe TUTTE le marche."""
        e = mt.interpreta_risposta(self._buona(), IMPRONTA, 99)
        self.assertTrue(e["ok"], e.get("motivo"))
        self.assertEqual(IMPRONTA.hex(), e["impronta_hex"])
        self.assertEqual(99, e["nonce"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
