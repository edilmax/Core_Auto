"""Codice prenotazione leggibile (BVIP-XXXX-XXXX) + PIN check-in (4 cifre): stile Booking.
Deterministici e UGUALI per cliente e host; il PIN non è indovinabile (HMAC del segreto)."""
import unittest

from fase59_concierge import FirmaQuote, codice_prenotazione

SEG = b"k" * 32


class TestCodicePrenotazione(unittest.TestCase):
    def test_formato_bvip(self):
        c = codice_prenotazione("a5d660df6d99554875f212ac")
        self.assertEqual(c, "BVIP-A5D6-60DF")

    def test_deterministico(self):
        self.assertEqual(codice_prenotazione("abc123def456"),
                         codice_prenotazione("abc123def456"))

    def test_riferimento_corto_ha_padding(self):
        c = codice_prenotazione("ab")
        self.assertTrue(c.startswith("BVIP-AB00-"))
        self.assertEqual(len(c), len("BVIP-XXXX-XXXX"))

    def test_ignora_caratteri_strani(self):
        # solo alfanumerici, maiuscolo
        self.assertEqual(codice_prenotazione("a5-d6/60.df"), "BVIP-A5D6-60DF")

    def test_vuoto_non_solleva(self):
        self.assertEqual(codice_prenotazione(""), "BVIP-0000-0000")


class TestPinCheckin(unittest.TestCase):
    def setUp(self):
        self.firma = FirmaQuote(SEG)

    def test_quattro_cifre(self):
        pin = self.firma.pin_checkin("rif123")
        self.assertEqual(len(pin), 4)
        self.assertTrue(pin.isdigit())

    def test_deterministico_uguale_per_cliente_e_host(self):
        # cliente e host derivano lo STESSO pin dallo stesso riferimento
        self.assertEqual(self.firma.pin_checkin("REF-XYZ"), self.firma.pin_checkin("REF-XYZ"))

    def test_dipende_dal_riferimento(self):
        self.assertNotEqual(self.firma.pin_checkin("a"), self.firma.pin_checkin("b"))

    def test_dipende_dal_segreto_non_indovinabile(self):
        # con un segreto diverso il pin cambia -> non ricavabile senza il segreto
        altro = FirmaQuote(b"z" * 32)
        # (può coincidere per caso su 4 cifre, ma su più riferimenti no)
        diversi = sum(1 for r in ("r1", "r2", "r3", "r4", "r5")
                      if self.firma.pin_checkin(r) != altro.pin_checkin(r))
        self.assertGreaterEqual(diversi, 3)


class TestLaReteChePuliscePUOPULIRE_SE_STESSA(unittest.TestCase):
    """UN VOUCHER NON PAGATO NON DEVE CONTENERE IL PIN. MAI. QUALUNQUE SIA IL PIN.

    Il prodotto ha due difese: il PIN si scrive solo a pagamento avvenuto, e una SECONDA
    RETE lo toglie se per qualunque motivo trapelasse (`fase83_server.py`, «GUARDIA FISICA»).
    La seconda rete sostituisce il PIN con un segnaposto -- e lì c'è il difetto:

        se il SEGNAPOSTO contiene cifre, e il PIN è proprio quelle cifre,
        la sostituzione RIMETTE DENTRO il PIN che doveva togliere.

    Il PIN è di 4 cifre (10.000 valori), quindi ogni sequenza di 4 cifre che il prodotto
    scrive DA SÉ nella pagina è un PIN che la rete non sa pulire. Trovato il 2026-08-15
    perché la CI su Linux è andata rossa: `I3 VIOLATO: PIN check-in esposto PRIMA del
    pagamento`. Misurato dopo, su 3000 voucher non pagati: 2 casi, ed erano esattamente i
    valori contenuti nel segnaposto. Nessun altro.

    ⚠️ Non è una falla di sicurezza: il PIN resta annegato dentro l'entità del segnaposto e
    il browser disegna un lucchetto, quindi nessuno lo legge. Sono tre danni diversi:
      · la seconda rete NON funziona proprio nei casi in cui deve intervenire;
      · per quelle prenotazioni il server scrive un CRITICAL a OGNI visualizzazione --
        il falso allarme che insegna a ignorare gli allarmi (regola ferrea 10);
      · la CI diventa rossa a caso, e la spiegazione comoda sarebbe «è instabile»: è così
        che un difetto vero si trasforma in rumore accettato.

    ⛔ QUESTA GUARDIA NON CABLA NESSUN NUMERO. Le sequenze pericolose se le fa dire dal
    prodotto: rende una pagina non pagata, ne estrae le sequenze di 4 cifre, e per ognuna
    cerca un riferimento il cui PIN sia proprio quella. Se domani il segnaposto cambiasse e
    contenesse altre cifre, questa guardia lo prenderebbe lo stesso.
    """

    def _sistema(self):
        import shutil
        import tempfile
        from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        return crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=SEG, db_catalogo="%s/c.db" % d,
            db_inventario="%s/i.db" % d, db_registro_host="%s/r.db" % d,
            db_pendenti="%s/p.db" % d, db_finanza="%s/f.db" % d))

    @staticmethod
    def _voucher(sis, rif):
        return sis.firma.codifica({
            "tipo": "voucher", "riferimento": rif, "lingua": "it",
            "prezzo_guest_cents": 0, "valuta": "EUR",
            "check_in": "2026-09-01", "check_out": "2026-09-04",
            "alloggio": "Casa di prova", "smart_pass": "",
        })

    def test_il_segnaposto_non_puo_RIMETTERE_il_pin_che_toglie(self):
        import re
        from fase83_server import pagina_voucher_html
        sis = self._sistema()
        firma = sis.firma

        # 1) una pagina NON pagata di controllo: nessun record in `pagamenti_pendenti`,
        #    quindi il prodotto la tratta come da pagare -- il caso in esame.
        controllo = pagina_voucher_html(sis, self._voucher(sis, "0" * 24), "it")
        self.assertTrue(controllo, "voucher di controllo non renderizzato")

        # 2) le sequenze di 4 cifre che il PRODOTTO scrive da sé: ognuna è un PIN possibile
        candidati = sorted({m for m in re.findall(r"(?=(\d{4}))", controllo)})
        self.assertTrue(candidati,
                        "nessuna sequenza di 4 cifre nella pagina: la ricerca non ha "
                        "bersagli, quindi questa guardia non proverebbe niente (S7)")

        # 3) per ognuna, un riferimento il cui PIN sia PROPRIO quella, e si pretende che quel
        #    PIN non compaia MAI **come PIN** -- cioe' dentro la riga che il voucher usa per
        #    mostrarlo. ⛔ NON si cerca il numero nudo: l'anno delle date e' «2026», e un PIN
        #    che valesse 2026 farebbe scattare un allarme su una pagina perfettamente sana.
        #    E' la stessa ingenuita' che ha reso rossa la CI, vista dall'altro lato.
        from fase83_server import riga_pin_voucher
        colpevoli = []
        for atteso in candidati:
            for i in range(200000):
                rif = "p%d" % i
                if firma.pin_checkin(rif) == atteso:
                    pagina = pagina_voucher_html(sis, self._voucher(sis, rif), "it")
                    if riga_pin_voucher(atteso) in (pagina or ""):
                        colpevoli.append((rif, atteso))
                    break

        self.assertEqual(
            colpevoli, [],
            "un voucher NON PAGATO mostra il PIN nella riga del PIN. Casi trovati "
            "(riferimento, PIN): %r" % (colpevoli,))

    def test_la_rete_NON_scatta_su_una_semplice_COINCIDENZA(self):
        """UN FALSO ALLARME È UN DIFETTO QUANTO UN ALLARME MANCATO (regola ferrea 10).

        La seconda rete cercava il PIN come **quattro cifre nude** dentro tutto l'HTML. Ma
        una pagina è piena di cifre -- prezzi, date, totali -- e un PIN di 4 cifre ci
        finisce dentro per puro caso. Quando succede la rete:
          · scrive un `CRITICAL` nei log, su una pagina perfettamente sana;
          · **sostituisce quel numero** col segnaposto, cioè CORROMPE un prezzo o una data
            che l'ospite legge.
        Misurato il 2026-08-15 su 3000 voucher non pagati: **2 casi**, ~1 ogni 1500.

        💡 Il rimedio era già in casa, in un angolo solo: `collaudi/gare_micro.py:165` dice
        *«marcatori ESATTI della riga PIN (il PIN nudo e' 4 cifre: collide con date/prezzi)»*
        e cerca la riga esatta. Era una lezione imparata e **non propagata**.

        Qui si costruisce apposta una pagina in cui il PIN compare **come prezzo**, e si
        pretende che la rete NON scatti e che il prezzo resti intatto.
        """
        from fase83_server import pagina_voucher_html
        sis = self._sistema()
        firma = sis.firma

        # un riferimento il cui PIN, letto come centesimi, e' un prezzo plausibile
        rif = pin = None
        for i in range(200000):
            r = "c%d" % i
            p = firma.pin_checkin(r)
            if p[0] != "0":                      # niente zeri iniziali: dev'essere un prezzo vero
                rif, pin = r, p
                break
        self.assertTrue(rif, "premessa non valida: nessun PIN utilizzabile come prezzo")

        vt = firma.codifica({
            "tipo": "voucher", "riferimento": rif, "lingua": "it",
            "prezzo_guest_cents": int(pin),      # il prezzo E' il PIN: la coincidenza, apposta
            "valuta": "EUR", "check_in": "2026-09-01", "check_out": "2026-09-04",
            "alloggio": "Casa di prova", "smart_pass": "",
        })
        pagina = pagina_voucher_html(sis, vt, "it")
        self.assertTrue(pagina, "voucher non renderizzato")

        # come la pagina scrive davvero gli importi: col PUNTO (misurato, non supposto --
        # la prima versione di questa guardia cercava la virgola ed era rossa per colpa mia)
        atteso = "%d.%s" % (int(pin) // 100, pin[-2:])     # es. PIN 4574 -> prezzo "45.74"
        self.assertIn(
            atteso, pagina,
            "il prezzo %r non c'e' piu' nella pagina: la rete difensiva l'ha SOSTITUITO "
            "perche' coincideva col PIN. Cerca quattro cifre nude invece della riga esatta "
            "del PIN, quindi corrompe numeri innocenti (e grida al lupo nei log). "
            "Rimedio gia' noto in casa: `collaudi/gare_micro.py:165`." % (atteso,))


if __name__ == "__main__":
    unittest.main()
