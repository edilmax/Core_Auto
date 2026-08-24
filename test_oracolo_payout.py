"""IL SECONDO CONTO SUL PAYOUT DELL'HOST — e la prova che sa GRIDARE (B6, 2026-08-24).

Sei file di test guardavano gia' il bonifico all'host, e tutti facevano la stessa domanda:
«la cifra scritta nel registro e' quella che rileggiamo?». Nessuno chiedeva **«e' quella
giusta?»**. `collaudi/oracolo_payout.py` ricalcola quel numero da zero, dal lato dell'ospite,
e qui lo si mette al lavoro.

⛔ QUATTRO DOMANDE, NON UNA. Un collaudo che chiedesse solo «i due conti coincidono?» sarebbe
indistinguibile da un collaudo che non guarda niente:
  1. sulla griglia i due conti coincidono, e ogni cent ha un padrone;
  2. **l'oracolo GRIDA** se gli si passa una regola sbagliata (le due direzioni, regola 10);
  3. il testimone `regola_di_produzione` non si e' allontanato da `_da_versare_host` VERA;
  4. il numero e' confrontato col REGISTRO vero di fase131 — costruito **e collegato** (#23).
"""
import datetime
import json
import os
import shutil
import tempfile
import unittest

import fase85_pagamenti_stripe as _stripe
from collaudi import oracolo_payout as O
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase131_payout_dashboard import crea_payout_dashboard
from fase83_server import RouterHTTP, crea_router
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256


class TestIDueContiCoincidono(unittest.TestCase):
    """Il giro completo della griglia: nessuna differenza, nessun cent senza padrone."""

    def test_griglia_zero_differenze(self):
        provate, differenze, rotture, eccezioni = O.confronta()
        self.assertGreater(provate, 500,
                           "griglia troppo corta: %d combinazioni" % provate)
        self.assertEqual([], differenze[:5], "i due conti divergono")
        self.assertEqual([], rotture[:5], "conservazione rotta: cent senza padrone")
        self.assertEqual([], eccezioni[:5], "il contratto dice: MAI un'eccezione")

    def test_lo_sconto_del_credito_non_tocca_l_host(self):
        """Il credito fondatore lo paghiamo NOI: l'ospite paga meno, l'host prende uguale."""
        senza = O.monta_corpo(netto=20000, comm=2000, sconto=0, tassa=300, costo=385)
        con = O.monta_corpo(netto=20000, comm=2000, sconto=1500, tassa=300, costo=385)
        self.assertEqual(O.da_versare_host(senza), O.da_versare_host(con))
        self.assertEqual(con["totale_cents"], senza["totale_cents"] - 1500)

    def test_la_tassa_passa_all_host(self):
        """Decisione del fondatore 2026-08-19: la tassa e' denaro in transito, e passa."""
        corpo = O.monta_corpo(netto=20000, comm=2000, sconto=0, tassa=350, costo=385)
        self.assertEqual(O.da_versare_host(corpo),
                         corpo["netto_host_cents"] + 350)


class TestLOracoloSaGridare(unittest.TestCase):
    """⛔ LA PROVA CHE VALE PIU' DEL VERDE. Un oracolo che non ha mai detto NO non ha
    dimostrato di saperlo dire: qui gli si passano regole SBAGLIATE e si pretende il rosso."""

    def test_grida_se_la_tassa_viene_dimenticata(self):
        """Il guasto piu' probabile: si smette di girare la tassa all'host."""
        def senza_tassa(corpo):
            return O._cent(corpo.get("netto_host_cents"))
        _, differenze, _, _ = O.confronta(funzione_vera=senza_tassa)
        self.assertTrue(differenze, "l'oracolo NON si e' accorto della tassa persa")

    def test_grida_se_il_costo_carta_viene_addebitato_due_volte(self):
        def doppio_costo(corpo):
            return max(0, O.regola_di_produzione(corpo)
                       - O._cent(corpo.get("costo_pagamento_cents")))
        _, differenze, _, _ = O.confronta(funzione_vera=doppio_costo)
        self.assertTrue(differenze, "l'oracolo NON si e' accorto del doppio addebito")

    def test_grida_su_un_cent_solo(self):
        """Un cent. Se non lo vede, non serve a niente: gli errori sui soldi partono da li'."""
        def un_cent_in_meno(corpo):
            v = O.regola_di_produzione(corpo)
            return v - 1 if v > 0 else v
        _, differenze, _, _ = O.confronta(funzione_vera=un_cent_in_meno)
        self.assertTrue(differenze, "l'oracolo NON vede una differenza di UN cent")

    def test_grida_se_un_cent_resta_senza_padrone(self):
        """La conservazione, provata al contrario: un corpo dove la somma non torna."""
        corpo = O.monta_corpo(netto=20000, comm=2000, sconto=0, tassa=300, costo=385)
        corpo["netto_host_cents"] += 1            # un cent creato dal nulla
        self.assertNotEqual(0, O.residuo_conservazione(corpo))

    def test_e_tace_quando_e_giusto(self):
        """L'altra direzione: sulla regola VERA non deve dire niente."""
        _, differenze, rotture, eccezioni = O.confronta(
            funzione_vera=O.regola_di_produzione)
        self.assertEqual(([], [], []), (differenze, rotture, eccezioni))


class TestLaRegolaVeraNonSiEAllontanata(unittest.TestCase):
    """⛔ IL TESTIMONE INVECCHIA SE NESSUNO LO GUARDA. `regola_di_produzione` e' una
    riscrittura di `_da_versare_host`: se quella vera cambia e questa no, l'oracolo
    continuerebbe a dire «tutto a posto» misurando una regola che non esiste piu'."""

    def test_il_testimone_coincide_con_la_funzione_vera(self):
        vera = RouterHTTP._da_versare_host
        provate, differenze, _, _ = O.confronta(funzione_vera=vera)
        self.assertGreater(provate, 500)
        self.assertEqual([], differenze[:5],
                         "`_da_versare_host` VERA e il testimone non coincidono piu'")

    def test_anche_sui_valori_sporchi(self):
        vera = RouterHTTP._da_versare_host
        for corpo in (None, {}, [], "x", {"netto_host_cents": None},
                      {"netto_host_cents": -5, "tassa_soggiorno_cents": True}):
            self.assertEqual(O.regola_di_produzione(corpo), vera(corpo),
                             "divergono su %r" % (corpo,))


class TestControIlRegistroVero(unittest.TestCase):
    """COSTRUITO ≠ COLLEGATO (#23): l'oracolo lavora contro il REGISTRO di fase131,
    quello da cui parte il bonifico, non contro un dizionario di comodo."""

    def setUp(self):
        self.pd = crea_payout_dashboard(":memory:")
        self.pd.inizializza_schema()
        self.corpo = O.monta_corpo(netto=25000, comm=2500, sconto=1000,
                                   tassa=350, costo=475)

    def _registra(self, rif, importo):
        self.assertTrue(self.pd.registra_maturato(rif, "host-1", importo, "EUR"))

    def test_il_registro_dice_la_verita(self):
        self._registra("PR-1", RouterHTTP._da_versare_host(self.corpo))
        atteso, scritto, diff = O.contro_il_ledger(self.pd, "PR-1", self.corpo)
        self.assertEqual(0, diff, "atteso %r, scritto %r" % (atteso, scritto))

    def test_un_cent_sbagliato_nel_registro_viene_visto(self):
        self._registra("PR-2", RouterHTTP._da_versare_host(self.corpo) - 1)
        _, _, diff = O.contro_il_ledger(self.pd, "PR-2", self.corpo)
        self.assertEqual(1, diff, "un cent in meno nel registro passa inosservato")

    def test_una_riga_che_non_esiste_non_e_zero_differenza(self):
        """⛔ «Nessuna riga» NON e' «tutto a posto»: e' un host che non viene pagato."""
        atteso, scritto, diff = O.contro_il_ledger(self.pd, "MAI-SCRITTA", self.corpo)
        self.assertIsNone(scritto)
        self.assertEqual(atteso, diff)
        self.assertGreater(diff, 0)

    def test_la_rettifica_referral_va_dichiarata(self):
        """`aumenta_payout` cambia la riga DOPO: non dichiararla deve fare rosso."""
        base = RouterHTTP._da_versare_host(self.corpo)
        self._registra("PR-3", base)
        self.assertTrue(self.pd.aumenta_payout("PR-3", 800))
        _, _, muta = O.contro_il_ledger(self.pd, "PR-3", self.corpo)
        self.assertEqual(-800, muta, "una rettifica silenziosa e' passata")
        _, _, dichiarata = O.contro_il_ledger(self.pd, "PR-3", self.corpo,
                                              aumento_cents=800)
        self.assertEqual(0, dichiarata)

    def test_la_quota_decisa_in_controversia_comanda_sul_preventivo(self):
        """`imposta_importo`: dopo uno split il preventivo non c'entra piu'."""
        self._registra("PR-4", RouterHTTP._da_versare_host(self.corpo))
        self.assertTrue(self.pd.imposta_importo("PR-4", 9000))
        _, _, muta = O.contro_il_ledger(self.pd, "PR-4", self.corpo)
        self.assertNotEqual(0, muta)
        _, _, dichiarata = O.contro_il_ledger(self.pd, "PR-4", self.corpo,
                                              importo_deciso=9000)
        self.assertEqual(0, dichiarata)

    def test_il_payout_in_attesa_e_lo_stesso_numero(self):
        """Un hold non pagato vale zero come guadagno, ma la CIFRA dev'essere gia' giusta:
        se sbaglia qui, sbaglia anche quando diventa 'maturato'."""
        importo = RouterHTTP._da_versare_host(self.corpo)
        self.assertTrue(self.pd.registra_in_attesa("PR-5", "host-1", importo, "EUR"))
        _, _, diff = O.contro_il_ledger(self.pd, "PR-5", self.corpo)
        self.assertEqual(0, diff)


def _fetch_finto(url, body, headers):
    """Stripe finto: zero rete. Stesso appiglio usato da `test_happy_conti`."""
    import secrets
    return {"url": "https://stripe.finto/" + secrets.token_hex(4),
            "id": "cs_" + secrets.token_hex(8)}


class TestSullaCatenaVERA(unittest.TestCase):
    """⛔ LA PROVA CHE CONTA. Le classi qui sopra montano il preventivo a mano: provano
    l'aritmetica, non il prodotto. Qui il preventivo lo produce il MOTORE, la prenotazione
    passa dalle rotte VERE, e la riga payout la scrive la produzione — nessuno la aiuta.
    Poi l'oracolo ricalcola quella cifra dal lato dell'ospite e pretende lo stesso numero.

    E' l'unico posto dove la domanda e' quella di B6: *«all'host stiamo per bonificare la
    cifra giusta?»* — non «rileggiamo quello che avevamo scritto».
    """

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="oracolo_payout_")
        self.addCleanup(shutil.rmtree, self.d, True)
        prima = os.environ.get("PAGA_STRUTTURA_ATTIVO")

        def _ripristina():
            if prima is None:
                os.environ.pop("PAGA_STRUTTURA_ATTIVO", None)
            else:
                os.environ["PAGA_STRUTTURA_ATTIVO"] = prima
        self.addCleanup(_ripristina)
        os.environ["PAGA_STRUTTURA_ATTIVO"] = "0"
        self._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fetch_finto)
        self.addCleanup(setattr, _stripe.ProviderStripe, "_fetch_reale", self._orig)

        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=self.d + "/c.db", db_inventario=self.d + "/i.db",
            db_registro_host=self.d + "/r.db", db_accettazioni=self.d + "/a.db",
            db_pendenti=self.d + "/p.db", db_payout=self.d + "/po.db",
            db_garanzia=self.d + "/g.db", db_finanza=self.d + "/f.db",
            commissione_bps=1000, psp_bps=500, psp_fisso_cents=25,
            promo_lancio_attiva=False,
            stripe_secret_key="sk", stripe_webhook_secret="whsec_oracolo",
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/ko"))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "host@oracolo.local", "password": "password1",
                       "accetta_termini": True, "accetta_clausole": True,
                       "accetta_privacy": True, "doc_sha256": doc_sha256(),
                       "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(201, s, c)
        self.tok = {"X-Host-Token": c["token"]}
        self.oggi = datetime.date.today()

    def g(self, metodo, path, body=None, headers=None):
        return self.r.gestisci(metodo, path, {},
                               json.dumps(body) if body is not None else None,
                               headers or {})

    def giorno(self, n):
        return (self.oggi + datetime.timedelta(days=n)).isoformat()

    def pubblica(self, slug, prezzo, **extra):
        corpo = {"slug": slug, "titolo": "Casa " + slug, "citta": "Roma", "paese": "IT",
                 "descrizione": "Alloggio di prova per l'oracolo del payout.",
                 "prezzo_notte_cents": prezzo, "capacita": 6, "valuta": "EUR",
                 "lat_micro": 41902782, "lon_micro": 12496366,
                 "cin": "IT058091C2X5V0ABCD"}
        corpo.update(extra)
        s, o = self.g("POST", "/api/host/pubblica", corpo, self.tok)
        self.assertEqual(201, s, o)
        s, o = self.g("POST", "/api/host/disponibilita_range",
                      {"alloggio_id": slug, "da": self.giorno(0), "a": self.giorno(60),
                       "unita_totali": 2, "prezzo_netto_cents": prezzo}, self.tok)
        self.assertEqual(200, s, o)
        return slug

    def _quota_e_prenota(self, slug, *, notti=3, ospiti=2, da=5):
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": slug, "check_in": self.giorno(da),
                       "check_out": self.giorno(da + notti), "party": ospiti,
                       "fonte": "marketplace"})
        self.assertEqual(200, s, q)
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": "ospite@oracolo.local"})
        self.assertIn(s, (200, 201), b)
        return q, b

    def _controlla(self, q, b, ctx):
        rif = b["riferimento"]
        atteso, scritto, diff = O.contro_il_ledger(self.sis.payout, rif, q)
        self.assertIsNotNone(scritto, "%s: NESSUNA riga payout per %s -- l'host non "
                                      "verrebbe pagato affatto" % (ctx, rif))
        self.assertEqual(0, diff, "%s: il registro dice %r, l'oracolo ricalcola %r "
                                  "(preventivo %r)" % (ctx, scritto, atteso, q))
        self.assertEqual(0, O.residuo_conservazione(q),
                         "%s: cent senza padrone nel preventivo %r" % (ctx, q))
        return atteso

    def test_una_prenotazione_normale(self):
        slug = self.pubblica("oracolo-normale", 12000)
        q, b = self._quota_e_prenota(slug)
        importo = self._controlla(q, b, "prenotazione normale")
        self.assertGreater(importo, 0, "un payout di zero non e' un payout")

    def test_con_la_tassa_di_soggiorno(self):
        """La tassa passa all'host: se il registro la dimentica, l'host paga il Comune
        di tasca sua. E' il caso che il conto dal lato ospite vede subito."""
        slug = self.pubblica("oracolo-tassa", 15000, tassa_pp_notte_cents=350)
        q, b = self._quota_e_prenota(slug)
        self.assertGreater(q["tassa_soggiorno_cents"], 0,
                           "la tassa non e' stata applicata: il caso non e' provato")
        self._controlla(q, b, "con tassa di soggiorno")

    def test_alloggio_non_rimborsabile(self):
        """-12% sul netto, finanziato dall'host: cambia la sua fetta, deve tornare uguale."""
        slug = self.pubblica("oracolo-nr", 18000,
                             politica_cancellazione="non_rimborsabile")
        q, b = self._quota_e_prenota(slug)
        self._controlla(q, b, "non rimborsabile")

    def test_soggiorno_lungo(self):
        """Sconto settimana: piu' notti, sconto dell'host, stessa identita'."""
        slug = self.pubblica("oracolo-lungo", 9000, sconto_settimana_bps=1000)
        q, b = self._quota_e_prenota(slug, notti=8)
        self._controlla(q, b, "soggiorno lungo")

    def test_il_registro_e_l_unica_fonte_del_bonifico(self):
        """⛔ COSTRUITO != COLLEGATO. Se domani la produzione smettesse di scrivere la riga,
        i test qui sopra passerebbero lo stesso su un preventivo giusto: e' questo che
        pretende una riga VERA nel registro, e non un dizionario in memoria."""
        slug = self.pubblica("oracolo-riga", 11000)
        q, b = self._quota_e_prenota(slug)
        riga = self.sis.payout.info(b["riferimento"])
        self.assertIsInstance(riga, dict, "nessuna riga payout scritta dalla produzione")
        self.assertIn(riga["stato"], ("in_attesa", "maturato"), riga)
        self.assertEqual("EUR", riga["valuta"], riga)
        self.assertEqual(O.da_versare_host(q), riga["minori"], riga)


if __name__ == "__main__":
    unittest.main()
