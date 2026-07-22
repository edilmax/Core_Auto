"""TEST DI MUTAZIONE SUL MOTORE — la prova piu' severa che esista sui test.

Tutti gli altri collaudi chiedono: *"il codice fa la cosa giusta?"*.
Questo chiede l'opposto, che e' la domanda che nessuno si fa: **"se il codice facesse
la cosa SBAGLIATA, i test se ne accorgerebbero?"**

Metodo (mutation testing, lo standard aureo della letteratura): si introduce di
proposito UN difetto realistico nel codice di produzione — un `>=` che diventa `>`,
una costante cambiata, un controllo di sicurezza saltato — e si eseguono i test che
dovrebbero proteggere quel punto. Se restano VERDI, quel mutante e' **sopravvissuto**:
significa che li' non c'e' nessuna rete di protezione, e un bug vero passerebbe uguale.

Le mutazioni NON sono casuali: sono i guasti che costerebbero davvero — soldi
addebitati male, consensi non verificati, firme non controllate, marche accettate a
torto. Ogni mutante e' accompagnato dal danno che provocherebbe nel mondo reale.

Il codice viene SEMPRE ripristinato, anche se qualcosa va storto.
"""
import io
import os
import shutil
import subprocess
import sys

try:  # Windows: console cp1252 non regge box-drawing/emoji -> uscita UTF-8 tollerante
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)

# (file, testo originale, mutazione, test da eseguire, danno nel mondo reale)
MUTANTI = [
    # ── I SOLDI ────────────────────────────────────────────────────────────────
    ("fase98_policy_commissione.py",
     "    if g < gg:",
     "    if g <= gg:",
     "test_fase98_policy_commissione test_promo_lancio test_promo_lancio_e2e",
     "un giorno in piu' di commissione 0%: ricavo regalato su ogni host"),

    ("fase98_policy_commissione.py",
     "fase1 = min(LANCIO_BPS_FASE1, regime)",
     "fase1 = regime",
     "test_fase98_policy_commissione test_promo_lancio test_trasparenza_costi",
     "l'host paga il 10% invece dell'8% nel secondo scaglione: addebito eccessivo"),

    ("fase81_bootstrap_casavip.py",
     "hid = catalogo.host_di_alloggio(slug)",
     "hid = None",
     "test_promo_lancio_e2e test_fase81_bootstrap_casavip",
     "la rampa salta: promo 0% mai applicata (E' IL BUG VERO DEL 2026-07-20)"),

    # ── LE PROVE LEGALI ────────────────────────────────────────────────────────
    ("fase163_accettazioni.py",
     "if riferimento:\n            canonico += \"|\" + str(riferimento)",
     "if False:\n            canonico += \"|\" + str(riferimento)",
     "test_identita_contratto test_fase163_accettazioni",
     "il legame con l'identita' esce dalla firma: manomissione non piu' rilevabile"),

    ("fase163_accettazioni.py",
     "        valida = hmac.compare_digest(atteso, firma)",
     "        valida = True",
     "test_fase163_accettazioni test_consensi_blindati test_identita_contratto",
     "ogni prova risulta integra anche se manomessa: il registro non prova piu' nulla"),

    # ── LA MARCA TEMPORALE ─────────────────────────────────────────────────────
    ("fase184_marca_temporale.py",
     "if impronta != impronta_attesa:               # ← il controllo che conta",
     "if False:                                     # ← mutato",
     "test_fase184_marca_temporale test_marca_qualificata test_qualifica_catena",
     "si accetta una marca che certifica UN ALTRO documento: prova senza valore"),

    ("fase184_marca_temporale.py",
     "        return _der_oid(OID_QTST_ETSI) in bytes(token or b\"\")",
     "        return True",
     "test_marca_qualificata test_qualifica_catena",
     "ogni marca risulta QUALIFICATA anche quando non lo e': dichiarazione falsa"),

    ("fase184_marca_temporale.py",
     "    if stato not in STATI_CONCESSI:",
     "    if False:",
     "test_fase184_marca_temporale",
     "si accetta una marca che l'Autorita' ha RIFIUTATO"),

    # ── I CONSENSI ─────────────────────────────────────────────────────────────
    ("fase83_server.py",
     "        if mancanti:\n            return 422",
     "        if False:\n            return 422",
     "test_consensi_blindati test_pannelli_contratto",
     "account creati senza contratto, clausole vessatorie o privacy accettati"),

    # ── LA PERSISTENZA ─────────────────────────────────────────────────────────
    ("main_casavip.py",
     "db_recensioni=os.environ.get(\"DB_RECENSIONI\", \"data/recensioni.db\"),",
     "",
     "test_avvio_main test_db_persistenti",
     "le recensioni tornano a vivere in RAM: perse a ogni riavvio (BUG VERO DI OGGI)"),
]


def esegui(test_str, timeout=900):
    p = subprocess.run([sys.executable, "-m", "unittest"] + test_str.split(),
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    return p.returncode == 0, p.stdout.decode("utf-8", "replace")


if __name__ == "__main__":
    riserva = tempfile.mkdtemp(prefix="mutazione_")
    file_toccati = sorted({m[0] for m in MUTANTI})
    for f in file_toccati:
        shutil.copy(f, os.path.join(riserva, f.replace("/", "_")))

    print("=" * 90)
    print("TEST DI MUTAZIONE — se il motore facesse la cosa sbagliata, i test se ne")
    print("accorgerebbero? Un mutante SOPRAVVISSUTO e' un buco nella rete di protezione.")
    print("=" * 90)

    sopravvissuti, uccisi, non_applicabili = [], 0, []
    t0 = time.time()
    try:
        for i, (percorso, orig, mut, test, danno) in enumerate(MUTANTI, 1):
            testo = io.open(percorso, encoding="utf-8").read()
            if orig not in testo:
                non_applicabili.append("%s (testo non trovato)" % percorso)
                print("\n%2d. %-28s  ? testo non trovato: mutante non applicabile"
                      % (i, percorso))
                continue
            io.open(percorso, "w", encoding="utf-8", newline="\n").write(
                testo.replace(orig, mut, 1))
            try:
                verde, uscita = esegui(test)
            finally:
                io.open(percorso, "w", encoding="utf-8", newline="\n").write(testo)
            print("\n%2d. %s" % (i, percorso))
            print("    guasto introdotto: %s" % danno)
            if verde:
                sopravvissuti.append((percorso, danno, test))
                print("    ESITO: MUTANTE SOPRAVVISSUTO — i test restano VERDI!")
            else:
                uccisi += 1
                riga = [r for r in uscita.splitlines()
                        if r.startswith("FAILED") or r.startswith("Ran ")]
                print("    ESITO: ucciso dai test  (%s)" % " ".join(riga[-2:])[:70])
    finally:
        for f in file_toccati:
            shutil.copy(os.path.join(riserva, f.replace("/", "_")), f)
        shutil.rmtree(riserva, ignore_errors=True)

    provati = len(MUTANTI) - len(non_applicabili)
    print("\n" + "=" * 90)
    print("MUTANTI PROVATI: %d  |  UCCISI: %d  |  SOPRAVVISSUTI: %d  |  %.1f minuti"
          % (provati, uccisi, len(sopravvissuti), (time.time() - t0) / 60.0))
    if non_applicabili:
        print("non applicabili (il codice e' cambiato): %s" % ", ".join(non_applicabili))
    if sopravvissuti:
        print("\nBUCHI NELLA RETE DI PROTEZIONE:")
        for percorso, danno, test in sopravvissuti:
            print("  X %s" % percorso)
            print("    danno che passerebbe: %s" % danno)
            print("    test che avrebbero dovuto vederlo: %s" % test)
        sys.exit(1)
    print("\nNESSUN MUTANTE SOPRAVVISSUTO: ogni guasto simulato viene visto dai test.")
    sys.exit(0)
