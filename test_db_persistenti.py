"""GUARDIA — OGNI database deve finire nel VOLUME, non in una cartella effimera.

LA TRAPPOLA (scoperta il 2026-07-21, prima del rilascio della marca temporale).
In produzione il volume Docker e' montato SOLO su `/data`. La cartella `/app/data`
esiste ma NON e' il volume: e' dentro l'immagine, quindi **viene ricreata da zero a
ogni deploy**. `main_casavip.py` usa come ripiego percorsi RELATIVI (`data/xxx.db`)
che finiscono proprio li'.

Conseguenza: un database nuovo che non venga dichiarato in `docker-compose.casavip.yml`
funziona benissimo in tutti i test, funziona benissimo in produzione... e **sparisce al
primo aggiornamento**, in silenzio. Per una cache e' un fastidio; per le prove legali
(accettazioni, marche temporali) sarebbe la perdita di tutto il valore probatorio,
scoperta anni dopo, in causa.

Questa guardia rende impossibile ripetere l'errore: se qualcuno aggiunge un `db_*` alla
configurazione e dimentica la riga nel compose, la suite diventa rossa.
"""

import os
import re
import unittest

QUI = os.path.dirname(os.path.abspath(__file__))
COMPOSE = os.path.join(QUI, "docker-compose.casavip.yml")
MAIN = os.path.join(QUI, "main_casavip.py")

# Database di puro appoggio: se si perdono si ricostruiscono da soli, nessun danno.
# Tutto il resto DEVE essere dichiarato. Aggiungere qui e' una decisione consapevole.
RIGENERABILI = {"db_geocache", "db_poicache"}


def _testo(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


class TestDatabasePersistenti(unittest.TestCase):

    def setUp(self):
        from fase81_bootstrap_casavip import ConfigCasaVIP
        self.campi = sorted(c for c in ConfigCasaVIP.__dataclass_fields__
                            if c.startswith("db_"))
        self.compose = _testo(COMPOSE)
        self.main = _testo(MAIN)

    def test_ci_sono_database_da_controllare(self):
        self.assertGreater(len(self.campi), 15, "configurazione non letta")

    def test_ogni_database_e_dichiarato_nel_compose(self):
        """Il cuore della guardia."""
        mancanti = []
        for campo in self.campi:
            if campo in RIGENERABILI:
                continue
            variabile = campo.upper()          # db_marche -> DB_MARCHE
            if not re.search(r"^\s*%s\s*:" % variabile, self.compose, re.M):
                mancanti.append(variabile)
        self.assertEqual(
            mancanti, [],
            "Questi database NON sono dichiarati in docker-compose.casavip.yml: "
            "finirebbero in /app/data e verrebbero CANCELLATI a ogni deploy.\n"
            "Aggiungi una riga '%s: /data/<nome>.db' nella sezione environment "
            "del servizio app.\nMancanti: %s"
            % (mancanti[0] if mancanti else "DB_X", ", ".join(mancanti)))

    def test_ogni_dichiarazione_punta_al_volume(self):
        """Non basta esserci: deve puntare a /data, che e' l'unico punto montato."""
        for variabile, percorso in re.findall(r"^\s*(DB_[A-Z_]+)\s*:\s*(\S+)",
                                              self.compose, re.M):
            self.assertTrue(percorso.startswith("/data/"),
                            "%s punta a '%s': fuori dal volume, si perde al deploy"
                            % (variabile, percorso))
            self.assertTrue(percorso.endswith(".db"), "%s: %s" % (variabile, percorso))

    def test_il_programma_legge_davvero_quelle_variabili(self):
        """Una riga nel compose non serve a niente se il programma non la legge."""
        non_letti = []
        for campo in self.campi:
            variabile = campo.upper()
            if not re.search(r"^\s*%s\s*:" % variabile, self.compose, re.M):
                continue
            if ('os.environ.get("%s"' % variabile) not in self.main:
                non_letti.append(variabile)
        self.assertEqual(non_letti, [],
                         "dichiarati nel compose ma MAI letti da main_casavip.py: %s"
                         % ", ".join(non_letti))

    def test_nessun_percorso_ripetuto(self):
        """Due database sullo stesso file si sovrascriverebbero a vicenda."""
        percorsi = re.findall(r"^\s*DB_[A-Z_]+\s*:\s*(\S+)", self.compose, re.M)
        doppi = sorted({p for p in percorsi if percorsi.count(p) > 1})
        self.assertEqual(doppi, [], "stesso file per piu' database: %s" % doppi)

    def test_le_prove_legali_sono_fra_i_persistenti(self):
        """Esplicito e non negoziabile: queste tre non possono MAI essere effimere."""
        for variabile in ["DB_ACCETTAZIONI", "DB_MARCHE", "DB_FINANZA"]:
            self.assertRegex(
                self.compose, r"(?m)^\s*%s\s*:\s*/data/" % variabile,
                "%s custodisce PROVE LEGALI: deve stare nel volume persistente"
                % variabile)

    def test_il_ripiego_relativo_esiste_ma_e_solo_per_i_test(self):
        """Il ripiego 'data/xxx.db' va bene in locale; in produzione non deve MAI
        essere quello che si usa — per questo esiste la dichiarazione nel compose."""
        self.assertIn('os.environ.get("DB_MARCHE", "data/marche.db")', self.main)
        self.assertRegex(self.compose, r"(?m)^\s*DB_MARCHE\s*:\s*/data/marche\.db")


if __name__ == "__main__":
    unittest.main(verbosity=2)
