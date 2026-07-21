"""SONDA — quali Autorita' europee rispondono E dichiarano marche QUALIFICATE.

"Qualificata" (eIDAS art. 42) non e' una parola di marketing: e' verificabile.
Il certificato con cui la TSA firma contiene una dichiarazione ETSI (EN 319 422):

    0.4.0.19422.1.1   esi4-qtstStatement-1  -> "emetto marche temporali QUALIFICATE"
    0.4.0.1862.1.1    QcCompliance          -> "certificato qualificato"

Qui si interrogano dal vivo gli endpoint pubblici dei prestatori europei, si guarda se
la dichiarazione c'e' davvero dentro il token, e si prova la verifica con `openssl`.
Nessuna assunzione: solo cio' che l'Autorita' scrive nel suo certificato.
"""
import hashlib
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.chdir(REPO)

import fase184_marca_temporale as mt          # noqa: E402

# OID codificati in DER: si cercano cosi' come sono, dentro i byte del certificato.
OID_QTST = bytes.fromhex("0607040081975E0101".replace(" ", ""))    # 0.4.0.19422.1.1
OID_QC = bytes.fromhex("0606 0400 8E46 0101".replace(" ", ""))      # 0.4.0.1862.1.1

CANDIDATI = [
    # (paese, nome, url)
    ("ES", "ACCV (Generalitat Valenciana)", "http://tss.accv.es:8318/tsa"),
    ("GR", "APED (Amm. Pubblica greca)", "http://timestamp.aped.gov.gr/qtss"),
    ("ES", "Izenpe (Paesi Baschi)", "http://tsa.izenpe.com"),
    ("LT", "BalTstamp", "http://tsa.baltstamp.lt"),
    ("PL", "Certum (Asseco)", "http://time.certum.pl"),
    ("PL", "Certum QTS", "http://qts-17.certum.pl"),
    ("CZ", "CESNET", "http://tsa.cesnet.cz:3161/tsa"),
    ("DE", "DFN-Verein", "http://zeitstempel.dfn.de"),
    ("BE", "Belgio (BOSA)", "http://tsa.belgium.be/connect"),
    ("FR", "Lex Persona", "http://tsa.lex-persona.com/tsa"),
    ("ES", "FNMT (Zecca spagnola)", "http://tss.accv.es:8318/tsa"),
    ("IT", "InfoCert", "http://ntp.infocert.it"),
    ("EU", "QuoVadis EU", "http://ts.quovadisglobal.com/eu"),
    ("SI", "SI-TSA", "http://timestamp.si-tsa.si/tsa"),
    ("SK", "Disig", "http://tsa.disig.sk/tsa"),
    ("EE", "SK ID Solutions", "http://dd-at.ria.ee/tsa"),
]


def prova(nome, url, impronta):
    esito = mt.chiedi_marca(impronta, url=url, timeout=15)
    if not esito.get("ok"):
        motivo = esito.get("motivo")
        if motivo == "nessuna_tsa_disponibile":
            t = (esito.get("tentativi") or [{}])[0]
            motivo = t.get("dettaglio") or t.get("motivo") or "?"
        return {"ok": False, "motivo": str(motivo)[:60]}
    token = esito["token"]
    return {
        "ok": True, "token": token, "policy": esito["policy"],
        "seriale": str(esito["seriale"])[:14],
        "qualificata": OID_QTST in token,
        "cert_qualificato": OID_QC in token,
    }


def verifica_openssl(token, dato, cartella):
    """Prova la verifica: prima con le CA di sistema, poi con la catena del token."""
    t = os.path.join(cartella, "t.tsr")
    d = os.path.join(cartella, "d.txt")
    open(t, "wb").write(token)
    open(d, "wb").write(dato)
    ca = None
    for c in [r"C:\Program Files\Git\mingw64\etc\ssl\certs\ca-bundle.crt",
              "/etc/ssl/certs/ca-certificates.crt"]:
        if os.path.exists(c):
            ca = c
            break
    if not ca:
        return "CA di sistema non trovate"
    p = subprocess.run(["openssl", "ts", "-verify", "-data", d, "-in", t,
                        "-token_in", "-CAfile", ca],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
    uscita = p.stdout.decode("utf-8", "replace")
    if "Verification: OK" in uscita:
        return "OK con le CA di sistema"
    if "unable to get local issuer" in uscita:
        return "serve la radice del prestatore"
    return uscita.strip().splitlines()[-1][:60] if uscita.strip() else "?"


if __name__ == "__main__":
    dato = b"BookinVIP - sonda prestatori qualificati europei"
    impronta = hashlib.sha256(dato).digest()
    cartella = tempfile.mkdtemp()
    print("=" * 96)
    print("%-4s %-30s %-11s %-11s %-26s" % ("PAESE", "PRESTATORE", "RISPONDE",
                                            "QUALIFICATA", "VERIFICA OPENSSL"))
    print("=" * 96)
    buoni = []
    for paese, nome, url in CANDIDATI:
        r = prova(nome, url, impronta)
        if not r["ok"]:
            print("%-4s %-30s %-11s %s" % (paese, nome[:30], "no", r["motivo"]))
            continue
        q = "SI (ETSI)" if r["qualificata"] else ("cert.qual." if r["cert_qualificato"]
                                                 else "no")
        v = verifica_openssl(r["token"], dato, cartella)
        print("%-4s %-30s %-11s %-11s %-26s" % (paese, nome[:30], "si", q, v))
        print("     policy=%s  seriale=%s  token=%d byte"
              % (r["policy"], r["seriale"], len(r["token"])))
        if r["qualificata"]:
            buoni.append((paese, nome, url, r["policy"], v))
            open(os.path.join(cartella, "q_%s.tsr" % nome.split()[0].lower()),
                 "wb").write(r["token"])
    print("=" * 96)
    print("PRESTATORI CHE DICHIARANO MARCHE QUALIFICATE (ETSI 0.4.0.19422.1.1): %d"
          % len(buoni))
    for paese, nome, url, policy, v in buoni:
        print("  %s  %-28s %s" % (paese, nome[:28], url))
        print("      policy %s | %s" % (policy, v))
    print("\ntoken salvati in: %s" % cartella)
