"""D23 -- NESSUNO VERIFICAVA CHE L'ATTIVITA' DELL'HOST ESISTA. Ora la partita IVA si chiede al VIES.

Il fondatore, 29/9 notte: «come facciamo a sapere se quello li' e' registrato?». La DAC7
(Dir. UE 2021/514, Allegato V) OBBLIGA gia' la piattaforma a verificare il numero IVA con
«any electronic interface made available free of charge by a Member State or the Union»: per
le partite IVA dell'UE e' il VIES della Commissione (servizio REST ufficiale,
ec.europa.eu/taxation_customs/vies). Misurato il 30/9 in sola lettura: risponde valida /
non valida con nome e indirizzo, e con la NOSTRA partita IVA come richiedente da' un
`requestIdentifier`, il numero di consultazione: la PROVA che il controllo e' stato fatto.

Invarianti:
  1. il numero si scompone giusto (prefisso UE, oppure il paese dell'host; la Grecia e' EL);
  2. un numero fuori UE NON si manda al VIES: «non verificabile», mai «valida»;
  3. valida / non valida / errore del servizio restano tre cose distinte, e l'errore dice il
     codice del VIES (regola ferrea 9);
  4. l'esito e la prova si scrivono nel registro dell'host SOLO per il numero verificato: se
     l'host cambia partita IVA la verifica vecchia sparisce;
  5. salvare i dati fiscali con una partita IVA la fa verificare subito;
  6. la ritenuta esenta SOLO una partita IVA verificata valida: dichiararla non basta.
"""
import json
import os
import shutil
import tempfile
import time
import unittest

from fase100_dac7 import scomponi_partita_iva, verifica_vies

# Una costante, non una stringa letterale nel banco: per bandit una password passata come
# letterale e' un segreto cablato (B106), ed e' lo stesso rimedio di test_bunker_controlroom.
_CHIAVE_BUNKER_DI_PROVA = "SuperPw@1"


class _HttpFinto:
    def __init__(self, risposta=None, eccezione=None):
        self.risposta = risposta
        self.eccezione = eccezione
        self.chiamate = []

    def __call__(self, url, corpo, timeout):
        self.chiamate.append((url, dict(corpo), timeout))
        if self.eccezione is not None:
            raise self.eccezione
        return self.risposta


VALIDA = {"countryCode": "IT", "vatNumber": "01234567890", "valid": True,
          "requestIdentifier": "WAPIAAAAaDxc__Zb", "name": "ROSSI MARIO", "address": "ROMA"}
NON_VALIDA = {"countryCode": "IT", "vatNumber": "01234567890", "valid": False,
              "requestIdentifier": "WAPIAAAAbbbbbbbb", "name": "---", "address": "---"}
RIFIUTO = {"actionSucceed": False, "errorWrappers": [{"error": "MS_UNAVAILABLE"}]}


class TestScomposizione(unittest.TestCase):
    def test_prefisso_ue_o_paese_dell_host(self):
        self.assertEqual(scomponi_partita_iva("IT01234567890"), ("IT", "01234567890"))
        self.assertEqual(scomponi_partita_iva("it 012.345-67890"), ("IT", "01234567890"))
        self.assertEqual(scomponi_partita_iva("01234567890", "IT"), ("IT", "01234567890"))
        self.assertEqual(scomponi_partita_iva("01234567890", "Italia"), ("IT", "01234567890"))
        self.assertEqual(scomponi_partita_iva("DE123456789", "IT"), ("DE", "123456789"))
        self.assertEqual(scomponi_partita_iva("GR123456789"), ("EL", "123456789"))
        self.assertEqual(scomponi_partita_iva("123456789", "GR"), ("EL", "123456789"))

    def test_senza_cifre_non_e_un_numero_IVA(self):
        """Sopravvissuto del giro sul diff (fase100:158): una «partita IVA» di sole lettere
        passava per numero e finiva al VIES."""
        self.assertEqual(scomponi_partita_iva("IT"), ("", ""))
        self.assertEqual(scomponi_partita_iva("IT", "IT"), ("", ""))
        self.assertEqual(scomponi_partita_iva("ABCDEF", "IT"), ("", ""))
        self.assertEqual(scomponi_partita_iva("NL123456789B01"), ("NL", "123456789B01"))

    def test_fuori_ue_o_vuoto_non_si_scompone(self):
        self.assertEqual(scomponi_partita_iva("US12-3456789"), ("", ""))
        self.assertEqual(scomponi_partita_iva("123456789", "JP"), ("", ""))
        self.assertEqual(scomponi_partita_iva("123456789", ""), ("", ""))
        self.assertEqual(scomponi_partita_iva(""), ("", ""))
        self.assertEqual(scomponi_partita_iva(None, "IT"), ("", ""))


class TestVerificaVIES(unittest.TestCase):
    def test_valida_con_la_prova_e_il_richiedente(self):
        http = _HttpFinto(VALIDA)
        r = verifica_vies("01234567890", "IT", richiedente="IT11795700969", http=http)
        self.assertEqual(r, {"esito": "valida", "prova": "WAPIAAAAaDxc__Zb",
                             "nome": "ROSSI MARIO", "motivo": ""})
        url, corpo, _t = http.chiamate[0]
        self.assertTrue(url.startswith("https://ec.europa.eu/taxation_customs/vies/rest-api/"))
        self.assertEqual(corpo, {"countryCode": "IT", "vatNumber": "01234567890",
                                 "requesterMemberStateCode": "IT",
                                 "requesterNumber": "11795700969"})

    def test_non_valida_e_non_valida(self):
        r = verifica_vies("IT01234567890", http=_HttpFinto(NON_VALIDA))
        self.assertEqual((r["esito"], r["nome"]), ("non_valida", ""))

    def test_rifiuto_del_servizio_e_ERRORE_col_suo_codice(self):
        with self.assertLogs("core_auto.dac7", level="WARNING") as log:
            r = verifica_vies("IT01234567890", http=_HttpFinto(RIFIUTO))
        self.assertEqual((r["esito"], r["motivo"]), ("errore", "MS_UNAVAILABLE"))
        self.assertTrue(any("MS_UNAVAILABLE" in x for x in log.output), log.output)

    def test_rete_giu_e_ERRORE_mai_valida(self):
        with self.assertLogs("core_auto.dac7", level="WARNING"):
            r = verifica_vies("IT01234567890", http=_HttpFinto(eccezione=TimeoutError("lento")))
        self.assertEqual((r["esito"], r["motivo"]), ("errore", "TimeoutError"))

    def test_fuori_ue_NON_si_chiede_al_VIES(self):
        http = _HttpFinto(VALIDA)
        r = verifica_vies("123456789", "JP", http=http)
        self.assertEqual(r["esito"], "non_verificabile")
        self.assertEqual(http.chiamate, [])


class TestLaRispostaDelServizioSiLeggeDavvero(unittest.TestCase):
    """`_post_json` era l'unico pezzo che nessuna prova toccava (le prove passano un finto):
    sopravvissuto del giro sul diff (fase100:176). Un servizio VERO su 127.0.0.1 risponde
    200, 500 con la spiegazione del rifiuto, 500 vuoto."""

    def _servi(self, stato, corpo):
        import http.server
        import threading

        class _H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                self.send_response(stato)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(corpo.encode("utf-8"))

            def log_message(self, *a):
                pass
        srv = http.server.HTTPServer(("127.0.0.1", 0), _H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return "http://127.0.0.1:%d/" % srv.server_address[1]

    def test_200_si_legge(self):
        from fase100_dac7 import _post_json
        url = self._servi(200, json.dumps(VALIDA))
        self.assertEqual(_post_json(url, {"countryCode": "IT"}, 5), VALIDA)

    def test_500_con_la_spiegazione_si_legge_la_spiegazione(self):
        from fase100_dac7 import _post_json
        url = self._servi(500, json.dumps(RIFIUTO))
        self.assertEqual(_post_json(url, {"countryCode": "IT"}, 5), RIFIUTO)

    def test_500_vuoto_e_un_rifiuto_senza_nome(self):
        from fase100_dac7 import _post_json
        url = self._servi(500, "")
        self.assertEqual(_post_json(url, {"countryCode": "IT"}, 5), {})


class _ConSistema(unittest.TestCase):
    def setUp(self):
        from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
        from fase83_server import crea_router
        d = self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"v" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_garanzia=f"{d}/g.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/po.db",
            db_tassa_comunale=f"{d}/tc.db", db_finanza=f"{d}/fin.db",
            bunker_password=_CHIAVE_BUNKER_DI_PROVA))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak")
        self.reg = self.sis.registro_host
        self.hid = self.reg.registra("vies@collaudo.invalid", "password12",
                                     accetta_termini=True).host_id

    def g(self, m, p, b=None, h=None, q=None):
        return self.r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or {})

    def token(self):
        s, c = self.g("POST", "/api/host/login", {"email": "vies@collaudo.invalid",
                                                  "password": "password12"})
        self.assertEqual(s, 200, c)
        return {"X-Host-Token": c["token"]}


class TestIlRegistroTieneLaProva(_ConSistema):
    def test_esito_e_prova_nel_registro(self):
        self.reg.imposta_dati_fiscali(self.hid, {"partita_iva": "IT01234567890"})
        self.assertTrue(self.reg.registra_verifica_piva(self.hid, "IT01234567890", "valida",
                                                        "WAPIAAAAaDxc__Zb", "ROSSI MARIO"))
        info = self.reg.info_host(self.hid)
        self.assertEqual((info["piva_vies_esito"], info["piva_vies_prova"],
                          info["piva_vies_nome"]), ("valida", "WAPIAAAAaDxc__Zb", "ROSSI MARIO"))
        self.assertTrue(abs(int(info["piva_vies_ts"]) - int(time.time())) < 60)

    def test_cambiata_la_partita_iva_la_verifica_vecchia_SPARISCE(self):
        self.reg.imposta_dati_fiscali(self.hid, {"partita_iva": "IT01234567890"})
        self.reg.registra_verifica_piva(self.hid, "IT01234567890", "valida", "P1", "ROSSI")
        self.reg.imposta_dati_fiscali(self.hid, {"partita_iva": "IT09999999999"})
        self.assertEqual(self.reg.info_host(self.hid)["piva_vies_esito"], "")

    def test_la_verifica_di_un_numero_che_non_e_piu_quello_NON_si_scrive(self):
        self.reg.imposta_dati_fiscali(self.hid, {"partita_iva": "IT09999999999"})
        self.assertFalse(self.reg.registra_verifica_piva(self.hid, "IT01234567890", "valida",
                                                         "P1", "ROSSI"))
        self.assertEqual(self.reg.info_host(self.hid)["piva_vies_esito"], "")

    def test_ingressi_sbagliati_NON_scrivono(self):
        """Sopravvissuti del giro sul diff (fase88:485-488)."""
        self.assertFalse(self.reg.registra_verifica_piva(self.hid, "  ", "valida"))
        self.assertFalse(self.reg.registra_verifica_piva(self.hid, None, "valida"))
        self.assertEqual(self.reg.info_host(self.hid)["piva_vies_esito"], "")
        self.reg.imposta_dati_fiscali(self.hid, {"partita_iva": "IT01234567890"})
        self.assertFalse(self.reg.registra_verifica_piva(self.hid, "IT01234567890", "forse"))
        self.assertEqual(self.reg.info_host(self.hid)["piva_vies_esito"], "")

    def test_archivio_guasto_torna_False_e_lo_dice_con_la_traccia(self):
        """Sopravvissuti del giro sul diff (fase88:499-500): il ramo d'errore."""
        import sqlite3
        self.reg._apri = lambda: sqlite3.connect(":memory:")     # nessuna tabella: UPDATE fallisce
        with self.assertLogs("core_auto", level="WARNING") as log:
            esito = self.reg.registra_verifica_piva(self.hid, "IT01234567890", "valida")
        self.assertIs(esito, False)
        rec = [r for r in log.records if "registra_verifica_piva" in r.getMessage()]
        self.assertEqual(len(rec), 1, log.output)
        self.assertIsInstance(rec[0].exc_info, tuple)

    def test_salvare_altri_dati_NON_cancella_la_verifica(self):
        self.reg.imposta_dati_fiscali(self.hid, {"partita_iva": "IT01234567890"})
        self.reg.registra_verifica_piva(self.hid, "IT01234567890", "valida", "P1", "ROSSI")
        self.reg.imposta_dati_fiscali(self.hid, {"iban": "IT60X0542811101000000123456"})
        self.assertEqual(self.reg.info_host(self.hid)["piva_vies_esito"], "valida")


class TestSalvareLaPartitaIvaLaFaVerificare(_ConSistema):
    def test_il_pannello_host_salva_e_il_VIES_risponde(self):
        chiamate = []

        def vies(numero, paese):
            chiamate.append((numero, paese))
            return {"esito": "valida", "prova": "WAPIAAAAaDxc__Zb", "nome": "ROSSI MARIO",
                    "motivo": ""}
        self.sis.vies = vies
        with self.assertLogs("core_auto.server", level="WARNING") as log:
            s, c = self.g("POST", "/api/host/dati_fiscali",
                          {"partita_iva": "01234567890", "paese": "IT"}, self.token())
        self.assertEqual(s, 200, c)
        self.assertEqual(c["partita_iva_verifica"], "valida")
        # la riga del registro porta esito, prova e motivo (sopravvissuti fase83:3471)
        self.assertTrue(any("ESITO: valida | PROVA: WAPIAAAAaDxc__Zb | MOTIVO: -" in x
                            for x in log.output), log.output)
        self.assertEqual(chiamate, [("01234567890", "IT")])
        info = self.reg.info_host(self.hid)
        self.assertEqual((info["piva_vies_esito"], info["piva_vies_prova"]),
                         ("valida", "WAPIAAAAaDxc__Zb"))

    def test_partita_iva_vuota_o_non_testo_NON_chiama_il_VIES(self):
        """Sopravvissuto del giro sul diff (fase83:3428)."""
        chiamate = []
        self.sis.vies = lambda numero, paese: chiamate.append(numero) or {"esito": "valida"}
        iban = "IT60X0542811101000000123456"
        for piva in ("   ", 12345678901):
            with self.subTest(piva=piva):
                s, c = self.g("POST", "/api/host/dati_fiscali",
                              {"partita_iva": piva, "iban": iban}, self.token())
                self.assertEqual(s, 200, c)
                self.assertEqual(c["partita_iva_verifica"], "")
        self.assertEqual(chiamate, [])

    def test_un_VIES_che_esplode_e_un_errore_con_la_traccia(self):
        """Sopravvissuto del giro sul diff (fase83:3466): il ramo d'errore della verifica."""
        def vies(numero, paese):
            raise RuntimeError("guasto")
        self.sis.vies = vies
        with self.assertLogs("core_auto.server", level="ERROR") as log:
            s, c = self.g("POST", "/api/host/dati_fiscali", {"partita_iva": "IT01234567890"},
                          self.token())
        self.assertEqual((s, c["partita_iva_verifica"]), (200, "errore"))
        self.assertEqual(self.reg.info_host(self.hid)["piva_vies_esito"], "errore")
        rec = [r for r in log.records if "VIES" in r.getMessage() and r.levelname == "ERROR"]
        self.assertEqual(len(rec), 1, log.output)
        self.assertIsInstance(rec[0].exc_info, tuple)

    def test_senza_VIES_configurato_resta_non_verificata(self):
        self.assertIsNone(self.sis.vies)
        s, c = self.g("POST", "/api/host/dati_fiscali", {"partita_iva": "01234567890"},
                      self.token())
        self.assertEqual(s, 200, c)
        self.assertEqual(c["partita_iva_verifica"], "")
        self.assertEqual(self.reg.info_host(self.hid)["piva_vies_esito"], "")

    def test_il_bunker_vede_l_esito_nella_conformita_DAC7(self):
        self.reg.imposta_dati_fiscali(self.hid, {"partita_iva": "IT01234567890"})
        self.reg.registra_verifica_piva(self.hid, "IT01234567890", "non_valida", "P9", "")
        s, out = self.g("POST", "/api/bunker/login", {"codice": _CHIAVE_BUNKER_DI_PROVA},
                        {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.9"})
        self.assertEqual(s, 200, out)
        hb = {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.9",
              "X-Bunker-Session": out["sessione"]}
        s, d = self.g("GET", "/api/bunker/dac7_conformita", None, hb,
                      q={"anno": str(time.gmtime().tm_year)})
        self.assertEqual(s, 200, d)
        riga = {h["host_id"]: h for h in d["host"]}[self.hid]
        self.assertEqual((riga["partita_iva_vies"], riga["partita_iva_vies_prova"]),
                         ("non_valida", "P9"))


class TestIlSistemaNasceColVIESSoloSeConfigurato(unittest.TestCase):
    def test_configurato_c_e_non_configurato_no(self):
        from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        base = dict(abilitato=True, segreto_hmac=b"v" * 32, db_payout=os.path.join(d, "p.db"))
        self.assertIsNone(crea_sistema(ConfigCasaVIP(**base)).vies)
        self.assertTrue(callable(crea_sistema(ConfigCasaVIP(
            vies_richiedente="IT11795700969", **base)).vies))


if __name__ == "__main__":
    unittest.main()
