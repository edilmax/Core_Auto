# -*- coding: utf-8 -*-
"""LA FEDELTA' DEL BANCO — la copia di prova misura la STESSA macchina della produzione?

PERCHE' ESISTE, misurato il 2026-08-08 e non ipotizzato. `collaudi/banco_prova.sh`
accendeva la copia di prova con `--env-file .env.casavip` e basta. La produzione riceve
altre DICIOTTO variabili dal blocco `environment:` di `docker-compose.casavip.yml`, e
QUATTORDICI di quelle dicono DOVE salvare i database. Senza, `main_casavip.py:105`
ripiega sul percorso RELATIVO `data/pendenti.db` — dentro il contenitore invece che nel
volume montato — e 13 database fra cui `pendenti`, `payout`, `garanzia`, `accettazioni`
e le marche temporali (valore legale) finiscono in `/app/data`, che muore col contenitore.

Il compose stesso lo dice, in un commento scritto dopo che era gia' successo una volta:
    DB_MARCHE: /data/marche.db  # senza questa riga i token finirebbero in /app/data
Il banco riproduceva ESATTAMENTE il guasto che quel file esiste per impedire.

QUANTO E' COSTATO. La «prova generale» del 2026-08-08 ha dichiarato «la catena dei soldi
REGGE» e ha concluso che la cancellazione non lasciava traccia del rimborso. Rimisurato la
sera stessa su 15 prenotazioni: la traccia C'ERA — 6 pendenti su 6 `rimborsato`, 6 payout
su 6 `trattenuto`, 6 tasse su 6 stornate — ma stava in `/app/data/pendenti.db`, che
nessuno guardava e che `docker rm -f` aveva cancellato davvero.

D18 — uno strumento che MISURA deve avere un controllo meccanico che gli impedisca di
barare. Questo e' quel controllo, e sta in Python (non dentro lo script di shell) proprio
perche' cosi' lo si puo' provare NELLE DUE DIREZIONI dalla suite: le guardie stanno in
`test_pipeline_ci.TestIlBancoDiProvaMisuraLaStessaMacchinaDellaProduzione`.

⛔ COSA QUESTO CONTROLLO NON GUARDA, dichiarato (D18 punto 3):
  · Confronta i NOMI delle variabili, non i valori. I valori devono differire: la chiave
    di Stripe del banco e' `sk_test_`, quella della produzione `sk_live_`, ed e' il
    controllo [5] di `banco_prova.sh` a pretenderlo (e a fermarsi se non e' cosi').
  · NON copia i SEGRETI dalla produzione al banco. Un banco che gira con la chiave vera
    e' un banco che puo' muovere soldi veri. I segreti arrivano al banco dal suo
    `--env-file`; se un giorno ne comparisse uno definito SOLO nel compose, questo
    controllo lo dichiara mancante e FERMA — cosi' lo aggiunge una persona, sapendolo.
  · NON conta i database presenti: il numero dei file in `/data` dipende da cosa e' stato
    esercitato, e mettere un cancello su una soglia di cui non conosco la varianza
    sarebbe un falso allarme in attesa di succedere. Il cancello e' sui due fatti che non
    ammettono interpretazioni: una variabile che manca, e un `.db` nel posto sbagliato.

USO, sul VPS:
    python3 collaudi/fedelta_banco.py ambiente  casavip_app  /root/.env.banco_derivato
    python3 collaudi/fedelta_banco.py controlla banco_prova_app casavip_app
"""
import re
import subprocess
import sys

# Nomi che NON si copiano MAI dalla produzione al banco. Non e' un elenco di variabili:
# e' un criterio, perche' un elenco andrebbe aggiornato e nessuno lo farebbe.
SEGRETI = re.compile(
    r"(KEY|SECRET|TOKEN|PASSWORD|PASSWD|RECOVERY|TOTP|CREDENTIAL|DSN|SEGRETO)")


# ---------------------------------------------------------------------------
# IL GIUDIZIO — Python puro, senza docker, provabile nelle due direzioni
# ---------------------------------------------------------------------------
def variabili_mancanti(nomi_produzione, nomi_banco):
    """Le variabili che la produzione HA e il banco NO.

    Solo in questa direzione: il banco puo' legittimamente averne in piu' (GIRI, la
    chiave di prova). Cio' che rende il banco bugiardo e' cio' che gli MANCA.
    """
    return sorted(set(nomi_produzione) - set(nomi_banco))


def database_fuori_posto(elenco_dentro_il_contenitore):
    """I `.db` finiti DENTRO il contenitore invece che nel volume montato.

    E' l'impronta OSSERVABILE del difetto, non la sua configurazione: un log dentro il
    contenitore e' normale, un database no — quello e' dato che deve sopravvivere.
    """
    return sorted(n for n in elenco_dentro_il_contenitore
                  if isinstance(n, str) and n.endswith(".db"))


def banco_infedele(mancanti, fuori_posto):
    """True = il banco misura un'ALTRA macchina: ci si ferma, non si misura."""
    return bool(mancanti) or bool(fuori_posto)


def da_copiare(nomi_mancanti):
    """Delle mancanti, quali si possono copiare senza portare segreti nel banco."""
    return [n for n in nomi_mancanti if not SEGRETI.search(n)]


# ---------------------------------------------------------------------------
# LA MISURA — qui si parla con docker
# ---------------------------------------------------------------------------
def _esegui(argomenti):
    """Esegue e restituisce (uscita, testo). L'esito si legge DIRETTO, mai da un tubo."""
    p = subprocess.run(argomenti, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.returncode, p.stdout.decode("utf-8", "replace")


def ambiente_del_contenitore(nome):
    """Le righe `NOME=valore` del contenitore, o None se non esiste/non gira."""
    uscita, testo = _esegui(
        ["docker", "inspect", "--format",
         "{{range .Config.Env}}{{println .}}{{end}}", nome])
    if uscita != 0:
        return None
    return [r for r in testo.splitlines() if "=" in r]


def nomi(righe):
    return [r.split("=", 1)[0] for r in (righe or [])]


def elenco_app_data(nome_banco):
    """Cosa c'e' in /app/data dentro il banco (il posto sbagliato). [] se non esiste."""
    uscita, testo = _esegui(["docker", "exec", nome_banco, "sh", "-c",
                             "ls -1 /app/data 2>/dev/null || true"])
    if uscita != 0:
        return None
    return [r.strip() for r in testo.splitlines() if r.strip()]


def _scrivi_ambiente(nome_prod, destinazione):
    """Genera il file d'ambiente del banco copiando dalla produzione cio' che NON e' segreto."""
    righe_prod = ambiente_del_contenitore(nome_prod)
    if righe_prod is None:
        print("  ⛔ il contenitore di produzione '%s' non risponde: non posso copiarne "
              "l'ambiente, e partire senza sarebbe misurare un'altra macchina. MI FERMO."
              % nome_prod)
        return 1
    copiate = [r for r in righe_prod if not SEGRETI.search(r.split("=", 1)[0])]
    saltate = [r for r in righe_prod if SEGRETI.search(r.split("=", 1)[0])]
    with open(destinazione, "w", encoding="utf-8", newline="\n") as f:
        f.write("# GENERATO da collaudi/fedelta_banco.py dal contenitore '%s'.\n"
                "# Non si modifica a mano: si rigenera. Contiene SOLO variabili non\n"
                "# segrete (percorsi dei database, cartelle, parametri).\n" % nome_prod)
        for riga in copiate:
            f.write(riga + "\n")
    print("  variabili copiate dalla produzione : %d" % len(copiate))
    print("  SEGRETI non copiati di proposito   : %d (arrivano dal --env-file del banco)"
          % len(saltate))
    return 0


def _controlla(nome_banco, nome_prod):
    righe_prod = ambiente_del_contenitore(nome_prod)
    righe_banco = ambiente_del_contenitore(nome_banco)
    if righe_prod is None:
        print("  ⛔ il contenitore di produzione '%s' non risponde: senza il termine di "
              "paragone non posso dire se il banco e' fedele. MI FERMO." % nome_prod)
        return 1
    if righe_banco is None:
        print("  ⛔ il banco '%s' non risponde. MI FERMO." % nome_banco)
        return 1
    mancanti = variabili_mancanti(nomi(righe_prod), nomi(righe_banco))
    dentro = elenco_app_data(nome_banco)
    if dentro is None:
        print("  ⛔ non riesco a guardare dentro il banco. MI FERMO.")
        return 1
    fuori = database_fuori_posto(dentro)

    # SI CONTANO I NOMI DISTINTI, non le righe. Una variabile che arriva da due
    # --env-file compare DUE VOLTE in Config.Env (l'ultima vince a tempo di
    # esecuzione): contare le righe faceva leggere «125 contro 88» e mandava a caccia
    # di 37 variabili che non esistono. Un numero che non torna si insegue finche' non
    # ha un nome (D23) -- ed e' successo davvero, il 2026-08-08.
    distinti_prod = sorted(set(nomi(righe_prod)))
    distinti_banco = sorted(set(nomi(righe_banco)))
    doppioni = len(righe_banco) - len(distinti_banco)
    print("  variabili distinte in produzione  : %d" % len(distinti_prod))
    print("  variabili distinte nel banco      : %d  (righe %d, di cui %d doppie: "
          "l'ultima vince)" % (len(distinti_banco), len(righe_banco), doppioni))
    print("  MANCANTI al banco                 : %d" % len(mancanti))
    if mancanti:
        print("     %s" % " ".join(mancanti))
    print("  database nel posto SBAGLIATO      : %d" % len(fuori))
    if fuori:
        print("     %s" % " ".join(fuori))

    if not banco_infedele(mancanti, fuori):
        print("  ✅ FEDELE: stesse variabili della produzione, nessun database fuori posto.")
        return 0

    print("  ⛔ IL BANCO NON E' FEDELE ALLA PRODUZIONE.")
    if mancanti:
        segrete = [n for n in mancanti if SEGRETI.search(n)]
        if segrete:
            print("     Fra le mancanti ci sono nomi che sembrano SEGRETI (%s): quelli"
                  % " ".join(segrete))
            print("     non li copio io. Li mette una persona, sapendo cosa sta facendo.")
        else:
            print("     Rigenera il file d'ambiente:  fedelta_banco.py ambiente %s <file>"
                  % nome_prod)
    if fuori:
        print("     I database qui sopra stanno DENTRO il contenitore e moriranno con lui:")
        print("     e' il difetto del 2026-08-08. Manca una DB_* nell'ambiente del banco.")
    print("     Un banco infedele non misura il prodotto: misura un'altra macchina.")
    return 1


def main(argomenti):
    if len(argomenti) >= 4 and argomenti[1] == "ambiente":
        return _scrivi_ambiente(argomenti[2], argomenti[3])
    if len(argomenti) >= 4 and argomenti[1] == "controlla":
        return _controlla(argomenti[2], argomenti[3])
    print("uso: fedelta_banco.py ambiente  <contenitore_prod> <file_uscita>")
    print("     fedelta_banco.py controlla <contenitore_banco> <contenitore_prod>")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
