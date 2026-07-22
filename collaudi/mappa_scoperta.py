"""MAPPA DELLO SCOPERTO — cosa è stato costruito e poi DIMENTICATO.

Tutti gli altri collaudi provano cio' che qualcuno si e' ricordato di provare. Questo fa
la domanda opposta, che nessun test verde puo' rispondere:

    **Che cosa, in questa macchina, non e' guardato da NESSUNO?**

Perche' conta: ~134 moduli e centinaia di rotte costruiti in mesi. Un modulo che nessun
test importa, o una porta che nessun test chiama, e' codice che potrebbe essere rotto da
settimane senza che una sola suite diventi rossa. La suite resterebbe verde per il motivo
peggiore: **non guarda da quella parte**.

Cinque mappe:

  M1  ROTTE SCOPERTE      - porte HTTP che nessun file di test nomina mai
  M2  MODULI SCOPERTI     - `fase*.py` che nessun test importa
  M3  PORTE APERTE        - rotte che rispondono 200 SENZA credenziali (prova viva)
  M4  MATRICE PERMESSI    - ogni rotta riservata × nessuna credenziale / chiave sbagliata
  M5  COSTRUITO E SPENTO  - moduli dichiarati "spenti" nel registro: esistono ancora?

Non e' un test: e' un censimento. Serve a sapere DOVE non stiamo guardando.
"""
import io
import os
import re
import sys

try:  # Windows: console cp1252 non regge box-drawing/emoji -> uscita UTF-8 tollerante
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.chdir(REPO)

SCOPERTO = {"M1": [], "M2": [], "M3": [], "M4": [], "M5": []}


def _testi_dei_test():
    fuori = {}
    for f in sorted(os.listdir(REPO)):
        if f.startswith("test_") and f.endswith(".py"):
            try:
                fuori[f] = io.open(os.path.join(REPO, f), encoding="utf-8").read()
            except Exception:
                pass
    return fuori


def m1_rotte_scoperte(testi):
    """Ogni rotta dichiarata nel router deve comparire in almeno un test."""
    server = io.open(os.path.join(REPO, "fase83_server.py"), encoding="utf-8").read()
    rotte = sorted(set(re.findall(r'path == "(/[^"]+)"', server))
                   | set(re.findall(r'path\.startswith\("(/[^"]+)"\)', server))
                   | set(re.findall(r'u\.path == "(/[^"]+)"', server)))
    tutto = "\n".join(testi.values())
    for r in rotte:
        if r not in tutto:
            SCOPERTO["M1"].append(r)
    return rotte


def m2_moduli_scoperti(testi):
    """Ogni `faseNN_*.py` del prodotto vivo deve essere importato da almeno un test."""
    legacy = re.compile(r"^fase(1[3-9]|[2-5][0-9])_")   # stack Mango/Tavola VIP
    tutto = "\n".join(testi.values())
    for f in sorted(os.listdir(REPO)):
        if not (f.startswith("fase") and f.endswith(".py")):
            continue
        if legacy.match(f):
            continue
        nome = f[:-3]
        if nome not in tutto:
            SCOPERTO["M2"].append(f)


def _sistema():
    import shutil
    import tempfile
    from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
    from fase83_server import crea_router
    d = tempfile.mkdtemp()
    os.environ["MARCA_TEMPORALE"] = "0"
    sis = crea_sistema(ConfigCasaVIP(
        abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
        db_catalogo=d + "/c.db", db_inventario=d + "/i.db", db_registro_host=d + "/r.db",
        db_accettazioni=d + "/a.db", db_pendenti=d + "/p.db", db_finanza=d + "/f.db",
        db_recensioni=d + "/rec.db", db_messaggi=d + "/m.db", db_garanzia=d + "/g.db",
        bunker_password="SuperPw@1"))
    return crea_router(sis, host_key="hk", admin_key="ak",
                       base_url="https://bookinvip.com"), d, shutil


def m3_m4_permessi(rotte):
    """PROVA VIVA: ogni rotta riservata chiamata SENZA credenziali e con credenziali
    SBAGLIATE. Una risposta 200 con dati e' una porta lasciata aperta."""
    import json
    router, d, shutil = _sistema()
    riservate = [r for r in rotte
                 if r.startswith(("/api/admin", "/api/bunker", "/api/host"))]
    # ATTENZIONE (difetto della sonda, corretto il 2026-07-21): la terza combinazione
    # mandava la chiave admin VERA ("ak"), quindi le rotte admin rispondevano 200 a
    # ragione e la mappa segnalava porte aperte inesistenti. Una sonda che sbaglia le
    # credenziali produce allarmi falsi, e gli allarmi falsi fanno ignorare la mappa.
    credenziali = [
        ("nessuna credenziale", {}),
        ("chiave admin SBAGLIATA", {"X-Admin-Key": "chiave-inventata-xyz"}),
        ("sessione bunker falsa + admin sbagliata",
         {"X-Bunker-Session": "falsa", "X-Admin-Key": "chiave-inventata-xyz"}),
    ]
    # rotte pubbliche PER PROGETTO: devono rispondere anche senza credenziali
    per_progetto = {
        "/api/host/password_dimenticata",   # chi ha perso la password non ha credenziali
        "/api/host/reimposta_password",
        "/api/host/login", "/api/host/registrazione",
        "/api/admin/login", "/api/bunker/login",
        "/api/bunker/logout", "/api/host/logout",   # uscire non richiede di essere dentro
    }
    for rotta in riservate:
        for nome, testate in credenziali:
            for metodo in ("GET", "POST"):
                corpo = json.dumps({}) if metodo == "POST" else None
                try:
                    st, risp = router.gestisci(metodo, rotta, {}, corpo, dict(testate))
                except Exception as e:
                    SCOPERTO["M4"].append("%s %s [%s] ECCEZIONE %s"
                                          % (metodo, rotta, nome, type(e).__name__))
                    continue
                if st == 200 and rotta not in per_progetto:
                    # 200 con credenziali assenti/false: la porta e' aperta
                    peso = len(json.dumps(risp, default=str)) if risp else 0
                    SCOPERTO["M3"].append("%s %s [%s] -> 200 (%d byte)"
                                          % (metodo, rotta, nome, peso))
    shutil.rmtree(d, ignore_errors=True)


def m5_costruito_e_spento():
    """I moduli che il registro dichiara SPENTI: esistono ancora e si importano?"""
    reg = io.open(os.path.join(REPO, "REGISTRO_INGEGNERIA.md"), encoding="utf-8").read()
    spenti = set(re.findall(r"fase(\d+)_\w+\.py[^|\n]{0,200}?(?:SPENTO|DORMIENTE)", reg))
    spenti |= set(re.findall(r"(?:SPENTO|DORMIENTE)[^|\n]{0,200}?fase(\d+)_", reg))
    for numero in sorted(spenti, key=lambda x: int(x)):
        trovati = [f for f in os.listdir(REPO)
                   if f.startswith("fase%s_" % numero) and f.endswith(".py")]
        if not trovati:
            SCOPERTO["M5"].append("fase%s: dichiarato nel registro ma IL FILE NON C'E'"
                                  % numero)
            continue
        nome = trovati[0][:-3]
        try:
            __import__(nome)
        except Exception as e:
            SCOPERTO["M5"].append("%s: dichiarato spento ma NON SI IMPORTA PIU' (%s)"
                                  % (trovati[0], type(e).__name__))


if __name__ == "__main__":
    testi = _testi_dei_test()
    print("=" * 88)
    print("MAPPA DELLO SCOPERTO — cosa non e' guardato da nessuno")
    print("=" * 88)
    rotte = m1_rotte_scoperte(testi)
    m2_moduli_scoperti(testi)
    m5_costruito_e_spento()
    try:
        m3_m4_permessi(rotte)
        viva = True
    except Exception as e:
        viva = False
        print("  (prova viva dei permessi non eseguita: %s)" % type(e).__name__)

    titoli = {
        "M1": "ROTTE che nessun test nomina mai",
        "M2": "MODULI fase*.py che nessun test importa",
        "M3": "PORTE APERTE: rispondono 200 senza credenziali valide",
        "M4": "ECCEZIONI sulle rotte riservate (il router non deve mai sollevare)",
        "M5": "MODULI dichiarati spenti nel registro: problemi",
    }
    print("\nrotte censite: %d | file di test: %d | prova viva permessi: %s"
          % (len(rotte), len(testi), "SI" if viva else "NO"))
    totale = 0
    for k in ("M3", "M4", "M1", "M2", "M5"):
        v = SCOPERTO[k]
        totale += len(v)
        print("\n%s  %s: %d" % (k, titoli[k], len(v)))
        for x in v[:30]:
            print("    " + x)
        if len(v) > 30:
            print("    ... e altri %d" % (len(v) - 30))
    print("\n" + "=" * 88)
    print("PUNTI SCOPERTI: %d" % totale)
    # M3 (porte aperte) e M4 (eccezioni) sono GRAVI: fanno uscire rosso.
    sys.exit(1 if (SCOPERTO["M3"] or SCOPERTO["M4"]) else 0)
