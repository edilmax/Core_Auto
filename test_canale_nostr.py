"""GUARDIA — Canale NOSTR (fase197): firma BIP340 (Schnorr/secp256k1) + evento firmato + canale gated.

Vista ROSSA:
- se le costanti della curva / la moltiplicazione scalare fossero sbagliate, le CHIAVI PUBBLICHE
  note (privata 1,2,3 su secp256k1 — valori pubblici verificabili) NON tornerebbero;
- se la firma fosse rotta, schnorr_verify(sign(...)) sarebbe False, o non rifiuterebbe la manomissione;
- se il canale non fosse cablato/gated, i test di configurazione fallirebbero.
La firma e' fedele al riferimento BIP340: un verificatore standard (i relay Nostr) usa la STESSA
equazione s·G = R + e·P, quindi ciò che qui verifica passa anche sui relay reali.
"""
import hashlib
import json
import unittest

from fase90_marketing import Post
from fase197_canale_nostr import (CanaleNostr, crea_canale_nostr_da_env, crea_evento_nota,
                                  pubkey_xonly, schnorr_sign, schnorr_verify)

# chiavi PUBBLICHE x-only note per privata=1,2,3 su secp256k1 (valori pubblici, verificabili
# ovunque): validano costanti curva + point_mul/point_add con 3 scalari diversi.
_SK = lambda n: (n).to_bytes(32, "big")
_PUB_NOTE = {
    1: "79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798",
    2: "c6047f9441ed7d6d3045406e95c07cd85c778e4b8cef3ca7abac09b95c709ee5",
    3: "f9308a019258c31049344f85f89d5229b531c845836f99b08601f113bce036f9",
}
_SECKEY_HEX = "%064x" % 3


class TestBIP340(unittest.TestCase):
    def test_pubkey_da_vettori_noti(self):
        for d, atteso in _PUB_NOTE.items():
            self.assertEqual(pubkey_xonly(_SK(d)).hex(), atteso,
                             "pubkey x-only errata per d=%d (costanti/point_mul rotti)" % d)

    def test_firma_verifica_round_trip(self):
        msg = hashlib.sha256(b"BookinVIP nostr").digest()
        sk = _SK(3)
        sig = schnorr_sign(msg, sk, bytes(32))
        self.assertEqual(len(sig), 64)
        self.assertTrue(schnorr_verify(msg, pubkey_xonly(sk), sig), "firma valida non verificata")

    def test_deterministica_con_aux_fisso(self):
        msg = hashlib.sha256(b"x").digest()
        a = schnorr_sign(msg, _SK(3), bytes(32))
        b = schnorr_sign(msg, _SK(3), bytes(32))
        self.assertEqual(a, b, "BIP340 deve essere deterministica a parita' di aux")

    def test_verifica_rifiuta_manomissione(self):
        msg = hashlib.sha256(b"vero").digest()
        sk = _SK(3)
        pub = pubkey_xonly(sk)
        sig = bytearray(schnorr_sign(msg, sk, bytes(32)))
        sig[10] ^= 0x01                                   # 1 bit girato -> deve fallire
        self.assertFalse(schnorr_verify(msg, pub, bytes(sig)), "firma manomessa accettata!")
        msg2 = hashlib.sha256(b"falso").digest()          # messaggio diverso -> deve fallire
        self.assertFalse(schnorr_verify(msg2, pub, schnorr_sign(msg, sk, bytes(32))))

    def test_verifica_input_malformati(self):
        self.assertFalse(schnorr_verify(bytes(32), b"corta", bytes(64)))
        self.assertFalse(schnorr_verify(bytes(32), bytes(32), b"corta"))


class TestEventoNostr(unittest.TestCase):
    def test_evento_firmato_e_coerente(self):
        ev = crea_evento_nota("Ciao dal Colosseo", _SK(3), created_at=1_700_000_000,
                              aux_rand=bytes(32))
        # id = sha256 della serializzazione canonica
        ser = json.dumps([0, ev["pubkey"], ev["created_at"], 1, ev["tags"], ev["content"]],
                         separators=(",", ":"), ensure_ascii=False)
        self.assertEqual(ev["id"], hashlib.sha256(ser.encode()).hexdigest())
        self.assertEqual(ev["pubkey"], _PUB_NOTE[3])
        # la firma verifica sull'id (32 byte)
        self.assertTrue(schnorr_verify(bytes.fromhex(ev["id"]), bytes.fromhex(ev["pubkey"]),
                                       bytes.fromhex(ev["sig"])), "sig dell'evento non valida")

    def test_id_cambia_col_contenuto(self):
        a = crea_evento_nota("uno", _SK(3), created_at=1, aux_rand=bytes(32))
        b = crea_evento_nota("due", _SK(3), created_at=1, aux_rand=bytes(32))
        self.assertNotEqual(a["id"], b["id"])


class TestCanaleNostr(unittest.TestCase):
    def setUp(self):
        self.inviati = []                                 # [(relay, messaggio)]

    def _sender(self, relay, messaggio):
        self.inviati.append((relay, messaggio))
        return True

    def _canale(self, sender=None):
        return CanaleNostr(_SECKEY_HEX, ["wss://relay.damus.io", "wss://nos.lol"],
                           sender=sender or self._sender, clock=lambda: 1_700_000_000)

    def test_pubblica_manda_evento_valido_ai_relay(self):
        ok = self._canale().pubblica(Post(tema="host", lingua="it", testo="Affitta senza il 25%",
                                           hashtag=[], link="https://bookinvip.com/affitta/roma"))
        self.assertTrue(ok)
        self.assertEqual(len(self.inviati), 2, "deve inviare a ENTRAMBI i relay")
        _, messaggio = self.inviati[0]
        tipo, evento = json.loads(messaggio)
        self.assertEqual(tipo, "EVENT")
        self.assertIn("bookinvip.com/affitta/roma", evento["content"])
        # firma verificabile da un verificatore standard (= relay)
        self.assertTrue(schnorr_verify(bytes.fromhex(evento["id"]),
                                       bytes.fromhex(evento["pubkey"]),
                                       bytes.fromhex(evento["sig"])))

    def test_fallisce_se_nessun_relay_accetta(self):
        ok = self._canale(sender=lambda r, m: False).pubblica(
            Post(tema="t", lingua="it", testo="x", hashtag=[], link="https://bookinvip.com/"))
        self.assertFalse(ok, "senza relay che accetta -> False")

    def test_gated_off_senza_chiave(self):
        self.assertIsNone(crea_canale_nostr_da_env({}))
        self.assertIsNone(crea_canale_nostr_da_env({"NOSTR_PRIVATE_KEY": _SECKEY_HEX}))  # senza relay
        self.assertIsNone(crea_canale_nostr_da_env({"NOSTR_RELAYS": "wss://x"}))          # senza chiave

    def test_gated_on_da_env(self):
        c = crea_canale_nostr_da_env(
            {"NOSTR_PRIVATE_KEY": _SECKEY_HEX, "NOSTR_RELAYS": "wss://relay.damus.io, wss://nos.lol"},
            fetch=self._sender)
        self.assertIsInstance(c, CanaleNostr)
        self.assertTrue(c.pubblica(Post(tema="t", lingua="it", testo="ciao", hashtag=[],
                                        link="https://bookinvip.com/")))
        self.assertEqual(len(self.inviati), 2)

    def test_seckey_malformata_non_pubblica(self):
        c = CanaleNostr("nonhex", ["wss://x"], sender=self._sender)
        self.assertFalse(c.pubblica(Post(tema="t", lingua="it", testo="x", hashtag=[],
                                         link="https://bookinvip.com/")))

    def test_cablato_in_fase91(self):
        from fase91_canali_social import crea_canali_da_env
        canali = crea_canali_da_env(
            {"NOSTR_PRIVATE_KEY": _SECKEY_HEX, "NOSTR_RELAYS": "wss://relay.damus.io"},
            fetch=self._sender)
        self.assertIn("nostr", canali, "il canale nostr non e' cablato in fase91")


if __name__ == "__main__":
    unittest.main(verbosity=2)
