"""GUARDIA — il tempo non deve dipendere da dove sta il server (né da dove sta l'utente).

DUE DIFETTI VERI, trovati con un audit chiesto dal fondatore (2026-07-21).

────────────────────────────────────────────────────────────────────────────────────────
A) LA FINESTRA DI CONTESTAZIONE SI ACCORCIAVA A CHI VIVE A OVEST

    ts = datetime.fromisoformat(check_in + "T15:00:00").timestamp()

`fromisoformat` senza fuso produce un orario NAIVE, e `.timestamp()` lo legge nel fuso del
SERVER — che in produzione e' UTC (nel Dockerfile e nel compose non c'e' nessuna `TZ`).
Il sistema assumeva quindi che ogni alloggio del mondo facesse il check-in alle 15:00 UTC.
Da quell'istante partono le 24 ore in cui l'ospite puo' dire «non e' come promesso» prima
che i soldi passino all'host (`fase160`, `FINESTRA_ORE_DEFAULT = 24`).

Ore di tutela REALI, contate dall'arrivo vero dell'ospite (le 15:00 ORA SUA):

    Tokyo      31 ore   (di piu': l'host aspetta l'incasso)
    New York   18 ore
    Honolulu   12 ore   <- META' della protezione promessa

L'alloggio NON ha un fuso orario: non esiste nel modello dati. Invece di aspettare quel
lavoro si ancora la finestra alle 15:00 del fuso piu' a OVEST del pianeta (UTC-12), cioe'
all'ultimo istante in cui possa essere check-in da qualche parte.

Il perche' e' l'errore che ho fatto alla prima stesura, e vale la pena scriverlo: la
scadenza e' `istante + 24h`, quindi conta **quando la finestra si CHIUDE**, non quando si
apre. Ancorandola al fuso piu' a EST la chiusura arrivava PRIMA e Tokyo scendeva a 19 ore:
il rimedio peggiorava il male. Il test qui sotto se n'e' accorto e ha imposto la
correzione. Ancorata a ovest, la scadenza cade sempre almeno 24 ore dopo l'arrivo vero di
chiunque; l'host viene pagato al massimo un giorno dopo. Fra accorciare la tutela di chi
ha appena pagato e ritardare un incasso, si sceglie il secondo.

────────────────────────────────────────────────────────────────────────────────────────
B) LE «48 ORE» DI RIPENSAMENTO ERANO GIORNI DI CALENDARIO

    _gg = (date.today() - date.fromisoformat(prenotato_data)).days
    ripensamento = (0 <= _gg <= 2)

Non si contava il tempo: si contavano i cambi di data, per giunta col giorno del SERVER.
Chi prenotava alle 23:50 aveva il rimborso pieno anche 26 ore dopo; chi prenotava alle
00:10 ce l'aveva ancora dopo 49. La finestra reale andava da 48 a 72 ore secondo l'ora
della prenotazione, e il confine si spostava col fuso dell'utente — su un diritto legale
(California SB 644, art. 49 del codice del consumatore brasiliano). Ora si confrontano
**172.800 secondi** con l'istante scritto nel gettone FIRMATO.

────────────────────────────────────────────────────────────────────────────────────────
PERCHE' NESSUNO SE N'ERA ACCORTO: il controllo che c'era (`capitolato.p6_date_con_fuso`)
e' una ricerca di testo sulle stringhe di formattazione, e verifica che dove si stampa
un'ora ci sia scritto "UTC". Non puo' vedere un `.timestamp()` su un orario naive ne' un
confronto fra `date.today()` e una data. Tutti i difetti qui sopra ci passavano davanti.
"""

import datetime as dt
import os
import time
import unittest

from fase83_server import (ORE_FUSO_MAX, ORE_FUSO_MIN, ORA_CHECKIN_LOCALE,
                           SECONDI_RIPENSAMENTO, _entro_ripensamento,
                           _istante_checkin_prudente, _istante_fine_tutela)

# I fusi veri in cui vivono gli ospiti, dal piu' a est al piu' a ovest.
FUSI = [("Kiritimati", 14), ("Tokyo", 9), ("Dubai", 4), ("Roma", 2), ("Londra", 1),
        ("New York", -4), ("Los Angeles", -7), ("Honolulu", -10), ("Baker", -12)]

ORE_TUTELA = 24


class TestLaTutelaNonSiAccorciaMaiANessuno(unittest.TestCase):
    """La proprieta' che conta: chiunque, ovunque, ha almeno 24 ore vere."""

    CHECK_IN = "2026-09-05"

    def _arrivo_reale(self, offset_ore):
        """L'istante in cui l'ospite entra davvero: le 15:00 del SUO fuso."""
        giorno = dt.date.fromisoformat(self.CHECK_IN)
        fuso = dt.timezone(dt.timedelta(hours=offset_ore))
        return dt.datetime(giorno.year, giorno.month, giorno.day,
                           ORA_CHECKIN_LOCALE, 0, 0, tzinfo=fuso).timestamp()

    def test_nessun_ospite_riceve_meno_di_24_ore(self):
        inizio = _istante_checkin_prudente(self.CHECK_IN)
        self.assertIsNotNone(inizio)
        magri = []
        for citta, off in FUSI:
            arrivo = self._arrivo_reale(off)
            ore = (inizio + ORE_TUTELA * 3600 - arrivo) / 3600.0
            if ore < ORE_TUTELA:
                magri.append("%s (UTC%+d): %.1f ore invece di %d"
                             % (citta, off, ore, ORE_TUTELA))
        self.assertEqual(
            magri, [],
            "La finestra per contestare si chiude prima delle 24 ore dall'arrivo VERO "
            "dell'ospite. Su soldi gia' pagati, e' tutela tolta.\n  - "
            + "\n  - ".join(magri))

    def test_il_vecchio_calcolo_sarebbe_stato_rosso(self):
        """La prova che questa guardia serve: col codice di prima, Honolulu e New York
        non passano. Se un giorno tornasse verde, vorrebbe dire che il criterio si e'
        ammorbidito."""
        vecchio = dt.datetime.fromisoformat(self.CHECK_IN + "T15:00:00").timestamp()
        magri = [c for c, off in FUSI
                 if (vecchio + ORE_TUTELA * 3600 - self._arrivo_reale(off)) / 3600.0
                 < ORE_TUTELA]
        self.assertTrue(
            magri,
            "il criterio non riconosce piu' il difetto originale: andrebbe corretto, "
            "non allargato")

    def test_la_finestra_non_parte_prima_del_giorno_di_arrivo(self):
        """Larga si', ma non assurda: non deve aprirsi il giorno prima."""
        inizio = _istante_checkin_prudente(self.CHECK_IN)
        giorno = dt.date.fromisoformat(self.CHECK_IN)
        mezzanotte_utc = dt.datetime(giorno.year, giorno.month, giorno.day,
                                     tzinfo=dt.timezone.utc).timestamp()
        self.assertGreaterEqual(inizio, mezzanotte_utc - 3600,
                                "la tutela si aprirebbe prima del giorno di check-in")

    def test_l_estremo_ovest_e_coperto_dalla_fine_tutela(self):
        fine = _istante_fine_tutela(self.CHECK_IN, ORE_TUTELA)
        self.assertIsNotNone(fine)
        ultimo_arrivo = self._arrivo_reale(ORE_FUSO_MIN)
        self.assertGreaterEqual((fine - ultimo_arrivo) / 3600.0, ORE_TUTELA)

    def test_i_confini_del_pianeta_sono_quelli_veri(self):
        self.assertEqual((ORE_FUSO_MIN, ORE_FUSO_MAX), (-12, 14),
                         "i fusi del mondo vanno da UTC-12 a UTC+14 (Kiribati)")

    def test_non_si_rompe_su_una_data_assurda(self):
        for cattiva in (None, "", "domani", "2026-13-45", 20260905):
            self.assertIsNone(_istante_checkin_prudente(cattiva),
                              "data %r accettata" % cattiva)

    def test_non_dipende_dal_fuso_DEL_SERVER(self):
        """La proprieta' piu' importante: lo stesso check-in deve dare lo stesso istante
        su una macchina italiana e su un server UTC. Prima non era cosi'."""
        import subprocess
        import sys
        codice = ("import os,sys;sys.path.insert(0,%r);"
                  "from fase83_server import _istante_checkin_prudente as f;"
                  "print(f('2026-09-05'))" % os.path.dirname(os.path.abspath(__file__)))
        valori = set()
        for tz in ("UTC", "Asia/Tokyo", "America/Los_Angeles"):
            amb = dict(os.environ)
            amb["TZ"] = tz
            r = subprocess.run([sys.executable, "-c", codice], capture_output=True,
                               text=True, env=amb, timeout=120)
            valori.add(r.stdout.strip())
        self.assertEqual(len(valori), 1,
                         "l'istante cambia col fuso del server: %s" % valori)


class TestQuarantottoOreSonoQuarantottoOre(unittest.TestCase):

    def test_sono_secondi_veri_non_giorni(self):
        self.assertEqual(SECONDI_RIPENSAMENTO, 172800,
                         "le 48 ore devono essere 172.800 secondi")

    def test_dentro_e_fuori_dalla_finestra(self):
        ora = int(time.time())
        for ore, atteso in ((0, True), (1, True), (24, True), (47.9, True),
                            (48.1, False), (49, False), (72, False), (200, False)):
            with self.subTest(ore=ore):
                v = {"prenotato_ts": ora - int(ore * 3600)}
                self.assertEqual(
                    _entro_ripensamento(v), atteso,
                    "prenotato %.1f ore fa: il diritto dovrebbe essere %s" % (ore, atteso))

    def test_l_ora_della_prenotazione_non_cambia_piu_la_durata(self):
        """Il difetto originale, messo a confronto col rimedio.

        Col conteggio a GIORNI, la durata reale del diritto dipendeva dall'ora in cui si
        prenotava: alle 23:50 duravano poche ore, alle 00:10 quasi settantadue. Qui si
        rifa' il vecchio calcolo su tutte le ore del giorno e si mostra che era
        incoerente; poi si mostra che quello nuovo, a secondi, e' identico per tutti.
        """
        import datetime as _d

        def vecchio_metodo(istante_prenotazione, istante_ora):
            g = (_d.datetime.fromtimestamp(istante_ora).date()
                 - _d.datetime.fromtimestamp(istante_prenotazione).date()).days
            return 0 <= g <= 2

        mezzanotte = _d.datetime.combine(_d.date.today(), _d.time.min)
        durate_vecchie = set()
        for ora_del_giorno in range(0, 24):
            pren = (mezzanotte + _d.timedelta(hours=ora_del_giorno)).timestamp()
            durata = 0
            for ore in range(1, 96):
                if vecchio_metodo(pren, pren + ore * 3600):
                    durata = ore
            durate_vecchie.add(durata)
        self.assertGreater(
            len(durate_vecchie), 1,
            "il vecchio calcolo risulta coerente: il confronto non prova piu' nulla")

        # il nuovo: la durata e' la stessa qualunque sia l'ora di partenza
        durate_nuove = set()
        for ora_del_giorno in range(0, 24):
            pren = int((mezzanotte + _d.timedelta(hours=ora_del_giorno)).timestamp())
            durata = 0
            # si misura sul tempo TRASCORSO, che e' cio' che il metodo nuovo guarda
            for ore in range(1, 96):
                trascorsi = ore * 3600
                if 0 <= trascorsi <= SECONDI_RIPENSAMENTO:
                    durata = ore
            durate_nuove.add(durata)
        self.assertEqual(len(durate_nuove), 1,
                         "la durata dipende ancora dall'ora della prenotazione: %s"
                         % sorted(durate_nuove))
        self.assertEqual(durate_nuove.pop(), 48)

    def test_un_istante_nel_futuro_non_da_diritti(self):
        ora = int(time.time())
        self.assertFalse(_entro_ripensamento({"prenotato_ts": ora + 10000}),
                         "un gettone datato nel futuro non deve aprire la finestra")

    def test_i_gettoni_vecchi_restano_tutelati(self):
        """Chi ha prenotato prima di questa modifica ha un gettone FIRMATO senza
        l'istante: non lo si puo' riscrivere, e un diritto gia' comunicato non si
        restringe a cose fatte. Si ricade sul conteggio storico, che e' piu' largo."""
        oggi = dt.date.today().isoformat()
        self.assertTrue(_entro_ripensamento({"prenotato_data": oggi}))
        vecchio = (dt.date.today() - dt.timedelta(days=9)).isoformat()
        self.assertFalse(_entro_ripensamento({"prenotato_data": vecchio}))

    def test_senza_nessuna_data_non_si_regala_niente(self):
        for v in ({}, {"prenotato_ts": None}, {"prenotato_ts": "ieri"},
                  {"prenotato_data": ""}, {"prenotato_data": "boh"}):
            self.assertFalse(_entro_ripensamento(v), "gettone %r apre la finestra" % v)


class TestIlControlloVecchioNonBastava(unittest.TestCase):
    """Perche' nessuno se n'era accorto: il presidio esistente guarda altro."""

    def test_il_capitolato_non_vede_i_calcoli_sul_tempo(self):
        import io
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "collaudi", "capitolato.py")
        with io.open(p, encoding="utf-8") as f:
            testo = f.read()
        self.assertIn("p6_date_con_fuso", testo)
        # e' una ricerca su come si STAMPANO le ore, non su come si CALCOLANO
        self.assertIn("strftime", testo,
                      "se cambiasse natura, questa nota andrebbe riscritta")
        self.assertNotIn("timestamp()", testo,
                         "il capitolato ora guarda anche i calcoli: aggiorna la guardia "
                         "e questa nota, che documenta perche' i difetti sfuggivano")


if __name__ == "__main__":
    unittest.main(verbosity=2)
