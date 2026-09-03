"""CASELLA 2 — le COPPIE di strade che condividono la chiave contabile `rimborso:<rif>`.

`test_rimborso_ogni_strada.py` censisce le **sette** strade e dichiara che **tre** scrivono
con la chiave di default. Questo file misura cosa succede quando due di quelle tre passano
sulla **stessa prenotazione**: il libro dei soldi e' idempotente sull'evento, quindi **la
prima che arriva scrive e le altre sono no-op**.

⛔ E LA DOMANDA GIUSTA NON E' «collidono?» MA «QUANTO COSTA LA COLLISIONE?». Una collisione
strutturale **non e' ancora un danno**: se i due importi coincidono, la seconda scrittura non
avrebbe cambiato niente e il libro dice il vero lo stesso.

⚠️ **E IL DENOMINATORE VERO E' SEI, NON TRE — rilievo della corsia A, 2026-09-03.** Il
meccanismo e' **ordinato** («la prima che arriva scrive»), quindi le combinazioni sono le
**coppie ordinate**: 6, non le 3 non ordinate che questo file elencava. Le tre inverse non
erano state misurate. **Adesso lo sono tutte e sei**, nessuna dedotta:

    OSPITE (scaglione) -> ADMIN (totale)   COLLISIONE CHE FA DANNO   -> guardia a parte, ROSSA
    OSPITE (scaglione) -> HOST (100%)      FRENATA dal prodotto (409)
    HOST (100%)        -> ADMIN (totale)   collide, importi COINCIDONO -> danno zero
    ADMIN (totale)     -> OSPITE           collide, resta il TOTALE   -> danno zero
    ADMIN (totale)     -> HOST             FRENATA dal prodotto (409)
    HOST (100%)        -> OSPITE           collide, resta il TOTALE   -> danno zero

🔑 **E la misura ha smentito il sospetto da cui era nata: le inverse NON sono irraggiungibili.**
Due delle tre passano e collidono. Sono innocue per un motivo diverso e piu' preciso: **vince
la prima, quindi il libro mente solo quando la PRIMA scrive MENO della seconda.** Nelle inverse
la prima e' sempre il totale, quindi la riga che resta e' gia' quella giusta.
⇒ **Il danno non dipende dalla coppia: dipende dall'ORDINE.** Una sola combinazione su sei lo
produce — lo scaglione dell'ospite seguito dal totale. Se un domani una strada che oggi scrive
il totale cominciasse a scrivere un parziale, i casi diventerebbero altri: e' quello che
sorveglia la guardia dell'invariante qui sotto.

📌 **E IL GIORNO IN CUI LE STRADE SULLA STESSA CHIAVE DIVENTANO QUATTRO, questa tabella non si
riscrive: si sostituisce con la PROPRIETA'** *(suggerimento della corsia A, 2026-09-03)*. Con
tre strade le coppie ordinate sono 6, con quattro sono **12**, e un'enumerazione va rifatta a
mano ogni volta. La forma che non invecchia e' una sola riga di verita':
    **per ogni coppia ordinata, se la PRIMA scrive MENO della seconda, il libro mente.**
Vale per 3, per 4 e per n, e non chiede di ricontare niente. ⚠️ Non e' urgente oggi — se il
gruppo cresce, `test_LE_STRADE_CHE_CONDIVIDONO_LA_CHIAVE...` diventa rossa **lo stesso
giorno**, quindi il buco non c'e': quando succede, la strada corta e' questa e non aggiungere
righe alla tabella.

Qui vivono le due che **oggi non fanno danno**, e ci vivono per una ragione precisa: sono
assoluzioni **con la data di scadenza dentro**. La terza (quella che fa danno) sta in un file
suo, perche' e' rossa e una guardia rossa manda rossa la suite intera finche' il difetto non
e' riparato.

⚠️ **PERCHE' LA SECONDA GUARDIA NON E' UNA NOTA MA UN INVARIANTE.** «Host -> admin coincidono»
e' vero **per valore, non per costruzione**: entrambe muovono il 100% *oggi*. Il giorno in cui
la penale dell'host cambia, o la strada admin smette di muovere il totale, i due numeri
divergono e il libro comincia a mentire **senza che nessuno abbia toccato il difetto**. Una
riga di commento che dice «attenzione, potrebbe cambiare» non se ne accorgerebbe mai: una
guardia si'.
"""
import datetime
import json
import shutil
import tempfile
import time
import unittest

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

WH = "whsec_coppie"
# Valore finto in una costante, non scritto sul posto: `bandit` B106 segnala un argomento il
# cui nome contiene «secret» quando riceve un letterale, e un rilievo nuovo si chiude nel
# codice invece che nella fotografia del cricchetto.
CHIAVE_FINTA = "sk"


class _BancoRimborsi(unittest.TestCase):
    """Banco comune: un host, un alloggio, e prenotazioni pagate con arrivo OGGI.

    ⛔ L'arrivo OGGI non e' un dettaglio: `fase111_cancellazione.POLITICHE["flessibile"]` vale
    `((1, 10000), (0, 5000))`, cioe' con **almeno un giorno** all'arrivo il rimborso e' PIENO e
    coincide col totale. Con l'arrivo a +2 giorni i due importi tornavano identici e la prova
    non dimostrava niente pur sembrando una prova."""

    @classmethod
    def setUpClass(cls):
        cls._orig = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(
            lambda u, b, h: {"url": "https://x/cs", "id": "cs_" + str(time.time_ns())})

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._orig

    def setUp(self):
        d = self.dir = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/a.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/po.db",
            db_garanzia=f"{d}/g.db", db_tassa_comunale=f"{d}/t.db",
            commissione_bps=1500, psp_bps=300, stripe_secret_key=CHIAVE_FINTA,
            stripe_webhook_secret=WH, stripe_success_url="https://x/ok",
            stripe_cancel_url="https://x/no"))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://b.com")
        s, c = self.g("POST", "/api/host/registrazione",
                      {"email": "h@cp.it", "password": "password1", "accetta_termini": True,
                       "accetta_clausole": True, "accetta_privacy": True,
                       "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        self.assertEqual(s, 201, c)
        self.tok = c["token"]
        self.oggi = datetime.date.today()
        self.g("POST", "/api/host/pubblica",
               {"slug": "casa", "titolo": "C", "citta": "Roma", "prezzo_notte_cents": 20000,
                "capacita": 4, "tassa_pp_notte_cents": 200}, {"X-Host-Token": self.tok})
        self.g("POST", "/api/host/disponibilita_range",
               {"alloggio_id": "casa", "da": self.oggi.isoformat(),
                "a": (self.oggi + datetime.timedelta(days=60)).isoformat(),
                "unita_totali": 3, "prezzo_netto_cents": 20000}, {"X-Host-Token": self.tok})

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    # ── attrezzi ────────────────────────────────────────────────────────────────
    def g(self, m, p, b=None, h=None):
        return self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None, h or {})

    def prenota_e_paga(self, email):
        ci = self.oggi.isoformat()
        co = (self.oggi + datetime.timedelta(days=2)).isoformat()
        _, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": ci, "check_out": co, "party": 2})
        _, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": email})
        rif = b["riferimento"]
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"id": "cs_x", "payment_intent": "pi_x",
                                             "metadata": {"riferimento": rif}}}})
        self.r.gestisci("POST", "/api/payments/webhook", {}, pl,
                        {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})
        totale = q.get("totale_cents") or q.get("prezzo_guest_cents")
        return rif, b["voucher_token"], totale, ci, co

    def riga_rimborso(self, rif):
        """(importo, causale) della riga di rimborso nel giornale, o None."""
        fc = getattr(self.sis, "finanza", None)
        if fc is None or not hasattr(fc, "movimenti"):
            return None
        v = [m for m in fc.movimenti(str(rif)) if m.get("tipo") == "rimborso"]
        return (v[0].get("importo_cents"), v[0].get("causale")) if v else None

    def idem_key_vera(self, rif):
        """⛔ L'`idem_key` VERA, dal pannello. La rotta admin deriva il riferimento da
        `idem_key[:24]`, ma NON vale il contrario: passando il riferimento, `rilascia()`
        rifiuta con 409 **prima** di arrivare al giornale. Al primo giro quel 409 mi aveva
        fatto concludere «il prodotto frena, nessun difetto» su tutte e tre le coppie: era il
        parametro sbagliato, non un freno. Un 409 che somiglia a un risultato."""
        _, adm = self.g("GET", "/api/admin/prenotazioni", None, {"X-Admin-Key": "ak"})
        for p in (adm or {}).get("prenotazioni", []):
            if str(p.get("idem_key", ""))[:24] == rif:
                return p.get("idem_key")
        return None


class TestLeCoppieCheOggiNonFannoDanno(_BancoRimborsi):

    def test_ospite_poi_host_e_FRENATA_dal_prodotto(self):
        """La buona notizia, sorvegliata invece che annotata.

        Dopo una cancellazione dell'ospite, l'host **non puo'** cancellare la stessa
        prenotazione: il prodotto risponde **409 `gia_cancellata`** (misurato, non dedotto).
        Quindi quella coppia non e' raggiungibile e la collisione non puo' prodursi li'.
        ⚠️ Se un domani quel freno cadesse, si aprirebbe una seconda strada al difetto **senza
        che nessuno l'abbia voluto**: e' il caso in cui una buona notizia va sorvegliata, non
        scritta in un commento.

        ✅ **E I FRENI SONO TRE, IN CASCATA — contati togliendoli uno per uno, non leggendo il
        codice.** Misurato il 2026-09-03:
        ```
        macchina sana ............................... tace
        tolto F1 (stato del pendente, `pp.info`) .... tace   <- respinge l'escrow
        tolto F2 (escrow liquidato, `garanzia.stato`) tace   <- respinge lo stato
        tolti F1+F2 ................................. tace   <- respinge il CAS
        tolti F1+F2+F3 (`marca_cancellata_host`) .... **ROSSA**
        ```
        [F1] `rec["stato"] in ("cancellata_host","rimborsato")` -> 409 `gia_cancellata`
        [F2] escrow in ("rilasciato","risolto") con `host_riceve_cents > 0` -> 409
        [F3] ⛔ **il piu' robusto, e l'unico atomico**: `pp.marca_cancellata_host()` e' un CAS —
             se ha gia' perso la gara torna `False` e la rotta risponde 409. Non si aggira
             leggendo uno stato, perche' non legge: **scrive o non scrive**.
        🔑 **QUESTA GUARDIA E' STATA VISTA ROSSA**, e il limite che questo file dichiarava fino
        al 2026-09-03 e' **chiuso**: restava verde **per ridondanza a tre livelli**, non per
        cecita'. La differenza fra le due ipotesi non si poteva dedurre — si poteva solo
        misurare, togliendo i freni finche' uno non ha ceduto. ⚠️ E il terzo non l'avevo
        nemmeno visto leggendo il codice: `gia_cancellata` compare in **due** punti diversi di
        `_host_cancella` (`:6465` e `:6519`), e il secondo e' il CAS."""
        rif, voucher, totale, _ci, _co = self.prenota_e_paga("a@cp.it")
        s1, _ = self.g("POST", "/api/concierge/cancella", {"voucher_token": voucher})
        self.assertEqual(s1, 200, "PREMESSA NON VALIDA: la cancellazione ospite non riesce, "
                                  "quindi la coppia non viene nemmeno attraversata.")
        prima = self.riga_rimborso(rif)
        self.assertIsNotNone(prima, "PREMESSA NON VALIDA: nessuna riga di rimborso dopo la "
                                    "cancellazione ospite: non c'e' niente su cui collidere.")

        s2, _ = self.g("POST", "/api/host/cancella", {"riferimento": rif},
                       {"X-Host-Token": self.tok})

        self.assertGreaterEqual(
            s2, 400,
            "IL FRENO E' CADUTO. Finora l'host non poteva cancellare una prenotazione gia' "
            "cancellata dall'ospite (409), e questo teneva chiusa una delle tre coppie che "
            "condividono la chiave contabile `rimborso:<rif>`. Adesso passa (HTTP %s): la "
            "seconda scrittura sara' un no-op e il libro dei soldi terra' l'importo della "
            "PRIMA strada, che e' lo scaglione dell'ospite e non il 100%% dovuto dall'host. "
            "Va misurato quanto costa prima di lasciarlo passare." % s2)
        self.assertEqual(
            self.riga_rimborso(rif), prima,
            "la riga del giornale e' cambiata pur essendo la seconda strada rifiutata: "
            "qualcosa ha scritto senza passare dalla rotta.")

    def test_host_poi_admin_COINCIDONO_e_devono_continuare_a_coincidere(self):
        """⛔ L'INVARIANTE, e non e' una nota: **due strade che condividono la chiave contabile
        devono muovere lo STESSO importo, altrimenti il giornale mente.**

        Host e admin collidono davvero (la seconda scrittura e' un no-op), ma oggi non fa
        danno perche' muovono **tutt'e due il totale**: la riga che resta e' comunque quella
        giusta. ⚠️ E' una coincidenza **di valore**, non una garanzia di costruzione. Il giorno
        in cui la penale dell'host cambia, o la strada admin smette di muovere il totale, il
        libro comincia a dichiarare il falso **senza che nessuno abbia toccato il difetto** —
        e nessun test se ne accorgerebbe, perche' la collisione strutturale era gia' nota e
        dichiarata innocua. Questa guardia e' la data di scadenza di quell'assoluzione."""
        rif, _voucher, totale, ci, co = self.prenota_e_paga("b@cp.it")

        s1, _ = self.g("POST", "/api/host/cancella", {"riferimento": rif},
                       {"X-Host-Token": self.tok})
        self.assertEqual(s1, 200, "PREMESSA NON VALIDA: la cancellazione host non riesce.")
        dopo_host = self.riga_rimborso(rif)
        self.assertIsNotNone(dopo_host, "PREMESSA NON VALIDA: nessuna riga dopo l'host.")
        self.assertEqual(
            dopo_host[0], totale,
            "PREMESSA CAMBIATA: la cancellazione host non registra piu' il totale (%s invece "
            "di %s). Non e' detto sia un difetto, ma questa prova non sta piu' misurando la "
            "coincidenza che dice di misurare: va riscritta." % (dopo_host[0], totale))

        idem = self.idem_key_vera(rif)
        self.assertIsNotNone(
            idem, "PREMESSA NON VALIDA: idem_key non trovata nel pannello. Passare il "
                  "riferimento al posto suo fa rispondere 409 e sembrerebbe un freno.")
        s2, _ = self.g("POST", "/api/admin/rimborso",
                       {"alloggio_id": "casa", "check_in": ci, "check_out": co,
                        "idem_key": idem}, {"X-Admin-Key": "ak"})
        self.assertEqual(s2, 200, "PREMESSA NON VALIDA: il rimborso admin non riesce, quindi "
                                  "la seconda strada non viene attraversata.")

        dopo_admin = self.riga_rimborso(rif)
        self.assertEqual(
            dopo_admin[0], totale,
            "IL GIORNALE HA COMINCIATO A MENTIRE SU QUESTA COPPIA. Host e admin condividono "
            "la chiave `rimborso:<rif>` e la scrittura e' idempotente: la seconda e' un "
            "no-op. Finora non faceva danno perche' muovevano lo STESSO importo (il totale). "
            "Adesso il libro dichiara %s mentre il totale mosso e' %s: la coincidenza di "
            "valore su cui poggiava l'assoluzione non c'e' piu', e questa coppia sarebbe la "
            "PRIMA a far mentire il giornale davvero (la coppia ospite->admin, misurata il "
            "2026-09-03, e' frenata dal prodotto: vedi il metodo qui sotto)."
            % (dopo_admin[0], totale))

    def test_ospite_poi_admin_e_FRENATA_e_il_movimento_si_MISURA(self):
        """⛔ LA TERZA COPPIA — e il 2026-09-02 l'avevo classificata come L'UNICA CHE FA
        DANNO, con tanto di guardia rossa e di cifra in euro. **Misurata il 2026-09-03: il
        danno non esiste.**

        La guardia che l'accusava (`test_rimborso_collisione_importi.py`, cancellata) diceva
        «soldi mossi dall'admin: il totale» prendendo quel numero **dal preventivo**, senza
        mai guardare se un movimento fosse avvenuto: una previsione scritta con la grammatica
        di un fatto. Il rosso era vero, ma era il rosso della guardia sbagliata.
        🔑 **Un rosso non dimostra che il difetto esista: dimostra che guardia e codice non
        sono d'accordo. Poi si guarda chi dei due ha ragione** -- e qui aveva ragione il codice.

        Cosa succede davvero, misurato:
        · l'ospite cancella -> il libro registra il DOVUTO (al netto della penale) e la
          prenotazione entra nella lista dei rimborsi da fare;
        · `/api/admin/rimborso` su quella prenotazione risponde 200 `idempotente`, con
          «nessun incasso da restituire»: **non chiama il gateway e non scrive in giornale**.
          Non e' una collisione di chiavi -- il record e' gia' marcato 'rimborsato' e il ramo
          contabile non viene nemmeno attraversato (`fase83`, `_admin_rimborso`).
        · i soldi partono dall'ALTRA rotta, `/api/admin/rimborsa_dovuto` (`fase83:4891`), che
          manda `dovuto_cents`: **lo stesso importo che il libro dichiara.**

        ⚠️ QUI IL MOVIMENTO SI MISURA, spiando `stripe.rimborsa`, invece di dedurlo dallo
        stato: e' l'unico modo di non ripetere l'errore che questa guardia sostituisce.
        ⛔ COSA NON COPRE (D18 punto 3): non prova la PARTENZA dei soldi dall'altra rotta --
        quella e' provata in `test_rimborso_arriva_al_gateway.py`, che copre 2 punti su 2.
        Qui si sorveglia il FRENO: se un domani `/api/admin/rimborso` ricominciasse a muovere
        denaro su una prenotazione gia' rimborsata, uscirebbe il TOTALE mentre il libro
        dichiara il DOVUTO, e questa diventerebbe rossa lo stesso giorno."""
        rif, voucher, totale, ci, co = self.prenota_e_paga("terza.coppia@ci.it")
        sp = getattr(self.sis, "stripe", None)
        self.assertIsNotNone(sp, "BANCO ROTTO: nessun gateway da spiare, si ripara il banco.")
        mossi, vero = [], sp.rimborsa

        def _spia(pi, cents, chiave, *a, **k):
            mossi.append(int(cents))
            return vero(pi, cents, chiave, *a, **k)

        sp.rimborsa = _spia
        try:
            s1, _ = self.g("POST", "/api/concierge/cancella", {"voucher_token": voucher})
            self.assertEqual(s1, 200,
                             "PREMESSA NON VALIDA: la cancellazione ospite non riesce.")
            dovuto = self.riga_rimborso(rif)
            self.assertIsNotNone(dovuto, "PREMESSA NON VALIDA: nessuna riga di rimborso.")
            self.assertLess(
                dovuto[0], totale,
                "PREMESSA NON VALIDA: la cancellazione ospite ha registrato il TOTALE (%s), "
                "non un parziale. Senza due importi diversi non c'e' niente da confondere e "
                "questa prova non misura cio' che dice: controlla lo scaglione." % (dovuto[0],))
            idem = self.idem_key_vera(rif)
            self.assertIsNotNone(
                idem, "PREMESSA NON VALIDA: idem_key non trovata nel pannello. Passare il "
                      "riferimento al posto suo fa rispondere 409, che somiglia a un freno.")
            mossi.clear()          # da qui in poi si misura SOLO la rotta admin
            s2, o2 = self.g("POST", "/api/admin/rimborso",
                            {"alloggio_id": "casa", "check_in": ci, "check_out": co,
                             "idem_key": idem}, {"X-Admin-Key": "ak"})
            self.assertEqual(s2, 200, "PREMESSA NON VALIDA: la rotta admin non risponde "
                                      "200 (%s): %r" % (s2, o2))
            self.assertEqual(
                mossi, [],
                "IL FRENO E' CADUTO. `/api/admin/rimborso` ha mosso %s al gateway su una "
                "prenotazione GIA' rimborsata, mentre il libro dichiara il dovuto (%s). Da "
                "qui in poi i due numeri divergono, e `fase177.aggrega_dac7` somma proprio "
                "queste righe nel rendiconto fiscale." % (mossi, dovuto[0]))
            self.assertEqual(
                self.riga_rimborso(rif)[0], dovuto[0],
                "la rotta idempotente ha scritto in giornale pur non muovendo denaro: il "
                "libro non deve cambiare se nessun centesimo si sposta.")
        finally:
            sp.rimborsa = vero


if __name__ == "__main__":
    unittest.main(verbosity=2)
