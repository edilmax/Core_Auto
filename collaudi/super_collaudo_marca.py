"""SUPER COLLAUDO — MARCA TEMPORALE: il mio codice giudicato da OpenSSL.

I test normali verificano il codice CON SE STESSO: se ho sbagliato a capire lo standard,
sbaglio uguale nel test e passa tutto. Qui si usa un GIUDICE ESTERNO — OpenSSL, la
stessa implementazione di riferimento che userebbe il perito di un tribunale — e si
confronta nei DUE SENSI. Se le due implementazioni concordano su tutto, l'errore di
comprensione e' escluso.

  O1  ORACOLO ANDATA    - OpenSSL legge le MIE richieste e capisce esattamente il dovuto
  O2  ORACOLO RITORNO   - io leggo le richieste di OPENSSL e capisco esattamente il dovuto
  O3  ORACOLO RISPOSTE  - su token VERI, io e OpenSSL leggiamo gli STESSI valori
  O4  MUTAZIONE         - un token vero corrotto byte per byte: mai accettato, mai crash
  O5  CATENA REALE      - marca vera -> archivio -> .tsr su disco -> `openssl ts -verify`
  O6  RESISTENZA        - marche ripetute nel tempo, tutte verificate dal giudice esterno

Esce 0 solo con ZERO violazioni.
"""
import hashlib
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.chdir(REPO)

import fase184_marca_temporale as mt          # noqa: E402

VIOL = []
CONTA = {"n": 0}
CON_RETE = "--con-rete" in sys.argv
GIRI = 1
for a in sys.argv:
    if a.startswith("--giri="):
        GIRI = int(a.split("=")[1])

TMP = tempfile.mkdtemp(prefix="supermarca_")


def check(liv, regola, ok, dett=""):
    CONTA["n"] += 1
    if not ok:
        VIOL.append("[%s] %s %s" % (liv, regola, dett))


def openssl(*args, stdin=None):
    """Esegue OpenSSL e ritorna (codice, testo). Mai solleva."""
    try:
        p = subprocess.run(["openssl"] + list(args), input=stdin,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
        return p.returncode, p.stdout.decode("utf-8", "replace")
    except Exception as e:
        return -1, "%s: %s" % (type(e).__name__, e)


def f(nome):
    return os.path.join(TMP, nome)


def _hexdump(testo):
    """Estrae SOLO la colonna esadecimale da un dump di OpenSSL, scartando
    l'offset a sinistra e la colonna ASCII a destra (separata da 2+ spazi)."""
    pezzi = []
    for riga in testo.lower().splitlines():
        m = re.match(r"\s*[0-9a-f]{4} - ([0-9a-f \-]+?)(?:\s{2,}|$)", riga)
        if m:
            pezzi.append(re.sub(r"[^0-9a-f]", "", m.group(1)))
    return "".join(pezzi)


# ═══════════════════════════════════════════════════════════════════════════════
def o1_oracolo_andata():
    """Le MIE richieste, lette da OpenSSL: capisce esattamente cio' che ho scritto?"""
    rnd = random.Random(2026)
    for i in range(25):
        impronta = hashlib.sha256(b"documento-%d" % i).digest()
        nonce = rnd.randrange(1, 2 ** 63)
        req = mt.costruisci_richiesta(impronta, nonce)
        p = f("mia_%d.tsq" % i)
        open(p, "wb").write(req)
        rc, testo = openssl("ts", "-query", "-in", p, "-text")
        check("O1", "openssl-legge-la-mia-richiesta", rc == 0, testo[:200])
        if rc != 0:
            continue
        # 1. l'algoritmo dichiarato
        check("O1", "openssl-vede-sha256", "sha256" in testo.lower(), testo[:300])
        # 2. l'impronta, byte per byte. OpenSSL la stampa come dump esadecimale:
        #      0000 - 62 58 a5 e0 ... 0e 14   bX...w)...+.....
        #    la colonna ASCII di destra va SCARTATA (separata da 2+ spazi), altrimenti
        #    si estraggono caratteri che non fanno parte dell'impronta.
        esa = _hexdump(testo)
        check("O1", "openssl-legge-la-MIA-impronta", impronta.hex() in esa,
              "attesa %s" % impronta.hex()[:24])
        # 3. il nonce, esattamente quello che ho messo
        m = re.search(r"Nonce:\s*(?:0x)?([0-9A-Fa-f]+)", testo)
        check("O1", "openssl-legge-il-MIO-nonce",
              m is not None and int(m.group(1), 16) == nonce,
              "atteso %d, letto %s" % (nonce, m.group(1) if m else "niente"))
        # 4. certReq: il certificato DEVE essere richiesto (token autosufficiente)
        check("O1", "openssl-vede-certreq-acceso",
              re.search(r"Cert(ificate)? req(uired)?:\s*yes", testo, re.I) is not None,
              testo[:400])
        # 5. versione 1
        check("O1", "openssl-vede-versione-1",
              re.search(r"Version:\s*1", testo) is not None)


# ═══════════════════════════════════════════════════════════════════════════════
def o2_oracolo_ritorno():
    """Le richieste di OPENSSL, lette da me: capisco esattamente cio' che ha scritto?"""
    for i, opzioni in enumerate([["-sha256", "-cert"],
                                 ["-sha256"],
                                 ["-sha256", "-cert", "-no_nonce"],
                                 ["-sha256", "-no_nonce"]]):
        dato = f("dato_%d.bin" % i)
        open(dato, "wb").write(b"contenuto di prova numero %d" % i)
        atteso = hashlib.sha256(open(dato, "rb").read()).digest()
        out = f("suo_%d.tsq" % i)
        rc, testo = openssl("ts", "-query", "-data", dato, *opzioni, "-out", out)
        check("O2", "openssl-genera-la-richiesta", rc == 0 and os.path.exists(out),
              testo[:200])
        if rc != 0 or not os.path.exists(out):
            continue
        suo = open(out, "rb").read()
        # smonto la SUA richiesta col MIO parser
        t = mt._leggi_tlv(suo, 0)
        check("O2", "il-mio-parser-apre-la-sua-richiesta",
              t is not None and t[0] == 0x30 and t[3] == len(suo))
        if t is None:
            continue
        campi = mt._figli(suo, t[1], t[2])
        check("O2", "leggo-versione-1",
              campi and campi[0][0] == 0x02
              and mt._intero_da(suo, campi[0][1], campi[0][2]) == 1)
        imprint = mt._figli(suo, campi[1][1], campi[1][2])
        letta = suo[imprint[1][1]:imprint[1][2]]
        check("O2", "leggo-la-SUA-impronta-esatta", letta == atteso,
              "letta %s attesa %s" % (letta.hex()[:20], atteso.hex()[:20]))
        check("O2", "leggo-il-suo-algoritmo-sha256",
              mt._der_oid(mt.OID_SHA256) in suo)
        # se ha messo il nonce, lo devo trovare; se non l'ha messo, non devo inventarlo
        ha_nonce = "-no_nonce" not in opzioni
        interi = [c for c in campi[2:] if c[0] == 0x02]
        check("O2", "nonce-presente-o-assente-come-lui",
              bool(interi) == ha_nonce,
              "atteso nonce=%s, trovati %d interi" % (ha_nonce, len(interi)))


# ═══════════════════════════════════════════════════════════════════════════════
def _valori_openssl_dal_token(percorso):
    """Chiede a OpenSSL cosa contiene un token: (seriale_int, gentime_epoch, policy)."""
    rc, testo = openssl("ts", "-reply", "-in", percorso, "-token_in", "-text")
    if rc != 0:
        return None
    ser = re.search(r"Serial number:\s*(0x)?([0-9A-Fa-f]+)", testo)
    gen = re.search(r"Time stamp:\s*(.+)", testo)
    pol = re.search(r"Policy OID:\s*([0-9.]+)", testo)
    quando = None
    if gen:
        for fmt in ("%b %d %H:%M:%S %Y GMT", "%b %d %H:%M:%S.%f %Y GMT"):
            try:
                import calendar
                import datetime
                quando = calendar.timegm(
                    datetime.datetime.strptime(gen.group(1).strip(), fmt).timetuple())
                break
            except Exception:
                continue
    return ((int(ser.group(2), 16) if ser else None), quando,
            (pol.group(1) if pol else None), testo)


def o3_oracolo_risposte(token_veri):
    """Su token VERI: io e OpenSSL dobbiamo leggere gli STESSI valori."""
    for nome, percorso, impronta in token_veri:
        rif = _valori_openssl_dal_token(percorso)
        check("O3", "openssl-legge-il-token-%s" % nome, rif is not None)
        if rif is None:
            continue
        ser_ref, gen_ref, pol_ref, testo = rif
        token = open(percorso, "rb").read()
        tt = mt._leggi_tlv(token, 0)
        mio = None
        for blob in mt._tutti_octet_string(token, tt[1], tt[2]) + [token]:
            mio = mt._leggi_tstinfo(blob, impronta)
            if mio:
                break
        check("O3", "io-leggo-il-token-%s" % nome, mio is not None)
        if mio is None:
            continue
        check("O3", "STESSO-seriale-%s" % nome, mio["seriale"] == ser_ref,
              "io %s / openssl %s" % (mio["seriale"], ser_ref))
        check("O3", "STESSA-ora-%s" % nome, gen_ref is None
              or mio["gen_time"] == gen_ref,
              "io %s / openssl %s" % (mio["gen_time"], gen_ref))
        check("O3", "STESSA-policy-%s" % nome, pol_ref is None
              or mio["policy"] == pol_ref,
              "io %s / openssl %s" % (mio["policy"], pol_ref))
        check("O3", "STESSA-impronta-%s" % nome,
              mio["impronta_hex"] == impronta.hex())


# ═══════════════════════════════════════════════════════════════════════════════
def o4_mutazione(token_veri):
    """Un token VERO corrotto byte per byte: mai accettato per un'altra impronta,
    mai un'eccezione. E' la simulazione di chi manomette la prova in archivio."""
    if not token_veri:
        return
    nome, percorso, impronta = token_veri[0]
    originale = open(percorso, "rb").read()
    risposta = mt._der(0x30, mt._der(0x30, mt._der_intero(0)) + originale)
    e = mt.interpreta_risposta(risposta, impronta)
    check("O4", "il-token-integro-passa", e.get("ok"), str(e.get("motivo")))

    rnd = random.Random(31337)
    accettati_a_torto = 0
    for _ in range(1500):
        b = bytearray(risposta)
        for _ in range(rnd.randint(1, 4)):
            b[rnd.randrange(len(b))] ^= 1 << rnd.randrange(8)
        try:
            r = mt.interpreta_risposta(bytes(b), impronta)
        except Exception as ex:
            check("O4", "mutazione-nessuna-eccezione", False, type(ex).__name__)
            break
        if r.get("ok") and r.get("impronta_hex") != impronta.hex():
            accettati_a_torto += 1
    check("O4", "mai-accettata-unimpronta-diversa", accettati_a_torto == 0,
          "%d casi" % accettati_a_torto)

    # corruzione MIRATA dell'impronta dentro il token: deve sempre fallire
    pos = risposta.find(impronta)
    check("O4", "impronta-localizzata-nel-token", pos > 0)
    if pos > 0:
        for i in range(0, 32, 2):
            b = bytearray(risposta)
            b[pos + i] ^= 0x01
            r = mt.interpreta_risposta(bytes(b), impronta)
            check("O4", "impronta-corrotta-sempre-respinta", not r.get("ok"),
                  "byte %d" % i)

    # troncamenti progressivi
    for taglio in range(50, len(risposta), 337):
        try:
            r = mt.interpreta_risposta(risposta[:taglio], impronta)
            check("O4", "troncato-non-passa", not r.get("ok"), "a %d byte" % taglio)
        except Exception as ex:
            check("O4", "troncato-nessuna-eccezione", False, type(ex).__name__)
            break


# ═══════════════════════════════════════════════════════════════════════════════
def o5_catena_reale():
    """La catena completa: registri veri -> sigillo -> TSA vera -> archivio -> .tsr ->
    `openssl ts -verify`. E' esattamente cio' che accadrebbe in causa."""
    if not CON_RETE:
        print("   O5 saltato (serve --con-rete)")
        return []
    from fase163_accettazioni import crea_registro_accettazioni
    d = tempfile.mkdtemp()
    reg = crea_registro_accettazioni(os.path.join(d, "a.db"), b"K" * 32)
    for i in range(9):
        reg.registra("host-%d" % i, ip="203.0.113.%d" % i, vessatorie=True)
    arch = mt.crea_archivio_marche(os.path.join(d, "m.db"))

    class Fin:
        def verifica_catena(self):
            return {"ok": True, "testa": "c" * 64, "righe": 12}

    prodotti, mute = [], []
    risposte = qualificate = 0
    for i, url in enumerate(mt.TSA_PREDEFINITE):
        esito = mt.marca_i_registri(arch, accettazioni=reg, finanza=Fin(),
                                    giorno="2026-08-%02d" % (i + 1), url=url)
        nome = url.split("//")[1].split("/")[0]
        if not esito.get("ok"):
            # un'Autorita' momentaneamente irraggiungibile non e' un difetto NOSTRO:
            # e' il caso per cui esiste il failover. Il requisito si verifica in fondo.
            mute.append(nome)
            continue
        risposte += 1
        if esito.get("qualificata"):
            qualificate += 1
        riga = [r for r in arch.elenco() if r["id"] == esito["id"]][0]
        # il file che si consegna al perito
        p_tok = f("catena_%d.tsr" % i)
        open(p_tok, "wb").write(arch.token(esito["id"]))
        # il documento e' la stringa LEGGIBILE del sigillo: il perito la ricalcola
        p_dat = f("catena_%d.txt" % i)
        open(p_dat, "wb").write(riga["canonico"].encode("utf-8"))
        check("O5", "impronta-del-canonico-e-quella-marcata",
              hashlib.sha256(riga["canonico"].encode("utf-8")).hexdigest()
              == riga["impronta"])
        prodotti.append((nome, p_tok, bytes.fromhex(riga["impronta"])))
        # La QUALIFICA deve corrispondere a cio' che il prestatore dichiara nel token
        check("O5", "qualifica-coerente-col-token-%s" % nome,
              bool(esito.get("qualificata")) == mt.e_qualificata(arch.token(esito["id"])))
        if url in mt.TSA_QUALIFICATE:
            check("O5", "prestatore-qualificato-lo-dichiara-%s" % nome,
                  esito.get("qualificata"),
                  "e' nella lista dei qualificati ma il token non lo dichiara: "
                  "potrebbe aver perso la qualifica")
        # IL GIUDICE ESTERNO. Attenzione: solo i prestatori la cui radice sta negli
        # archivi CA standard possono essere verificati "nudi"; Izenpe e BOSA sono
        # QUALIFICATI ma richiedono la loro radice, ed e' per questo che stanno in
        # riserva e non fra le prime due scelte. Il collaudo pretende la verifica piena
        # dai primi, e dagli altri pretende comunque che il fallimento sia SOLO di
        # ancoraggio (catena incompleta) e MAI di contenuto.
        serve_radice_propria = any(x in nome for x in ("izenpe", "belgium"))
        rc, testo = openssl("ts", "-verify", "-data", p_dat, "-in", p_tok,
                            "-token_in", "-CAfile", _ca_bundle())
        if serve_radice_propria:
            # Due modi in cui si manifesta la mancanza dell'ancora di fiducia:
            #  · "unable to get local issuer"          -> la radice non e' nel token
            #  · "self-signed certificate in chain"    -> la radice C'E' (Izenpe, e il
            #    "Belgium Root CA6" dello Stato belga) ma non sta nel magazzino di
            #    sistema. In entrambi i casi il CONTENUTO e' intatto: se fosse un
            #    problema di contenuto OpenSSL direbbe "message imprint mismatch".
            ancoraggio = ("unable to get local issuer" in testo
                          or "self-signed certificate" in testo
                          or "self signed certificate" in testo)
            check("O5", "fallimento-solo-di-ancoraggio-%s" % nome,
                  ancoraggio or "Verification: OK" in testo,
                  "atteso un problema di sola catena, non di contenuto: %s"
                  % testo.strip()[:120])
            check("O5", "mai-un-problema-di-contenuto-%s" % nome,
                  "mismatch" not in testo.lower(),
                  "il token non corrisponde al documento: e' ben peggio di un'ancora")
        else:
            check("O5", "openssl-verifica-la-catena-%s" % nome,
                  "Verification: OK" in testo, testo.strip()[:200])
        # prova del contrario: il canonico con UN carattere in piu'
        p_falso = f("catena_falso_%d.txt" % i)
        open(p_falso, "wb").write(riga["canonico"].encode("utf-8") + b"X")
        rc, testo = openssl("ts", "-verify", "-data", p_falso, "-in", p_tok,
                            "-token_in", "-CAfile", _ca_bundle())
        check("O5", "documento-alterato-mai-verificato-%s" % nome,
              "Verification: OK" not in testo, testo.strip()[:200])
        if not serve_radice_propria:
            check("O5", "openssl-dice-proprio-impronta-diversa-%s" % nome,
                  "mismatch" in testo.lower(), testo.strip()[:200])
    if mute:
        print("      (non hanno risposto in questo giro: %s)" % ", ".join(mute))
    check("O5", "almeno-un-prestatore-QUALIFICATO-risponde", qualificate >= 1,
          "nessuna Autorita' qualificata raggiungibile")
    check("O5", "almeno-due-Autorita-raggiungibili", risposte >= 2,
          "solo %d su %d hanno risposto" % (risposte, len(mt.TSA_PREDEFINITE)))
    shutil.rmtree(d, ignore_errors=True)
    return prodotti


_CA = {"path": None}


def _ca_bundle():
    if _CA["path"]:
        return _CA["path"]
    for c in [r"C:\Program Files\Git\mingw64\etc\ssl\certs\ca-bundle.crt",
              r"C:\Program Files\Git\mingw64\ssl\certs\ca-bundle.crt",
              "/etc/ssl/certs/ca-certificates.crt", "/etc/ssl/cert.pem"]:
        if os.path.exists(c):
            _CA["path"] = c
            return c
    _CA["path"] = ""
    return ""


# ═══════════════════════════════════════════════════════════════════════════════
def o6_resistenza():
    """Marche ripetute: ogni singola deve reggere il giudizio esterno."""
    if not CON_RETE:
        print("   O6 saltato (serve --con-rete)")
        return
    d = tempfile.mkdtemp()
    arch = mt.crea_archivio_marche(os.path.join(d, "m.db"))

    class R:
        def __init__(self, n):
            self.n = n

        def sigillo(self):
            return {"sigillo": hashlib.sha256(b"giro-%d" % self.n).hexdigest(),
                    "righe": self.n}

    riusciti = 0
    for n in range(6):
        esito = mt.marca_i_registri(arch, accettazioni=R(n), finanza=None,
                                    giorno="2026-09-%02d" % (n + 1))
        if not esito.get("ok"):
            # stessa logica: un intoppo di rete non e' un difetto della macchina.
            # Il requisito (almeno 4 marche su 6) si verifica in fondo.
            continue
        riusciti += 1
        riga = [r for r in arch.elenco() if r["id"] == esito["id"]][0]
        p_tok, p_dat = f("res_%d.tsr" % n), f("res_%d.txt" % n)
        open(p_tok, "wb").write(arch.token(esito["id"]))
        open(p_dat, "wb").write(riga["canonico"].encode("utf-8"))
        rc, testo = openssl("ts", "-verify", "-data", p_dat, "-in", p_tok,
                            "-token_in", "-CAfile", _ca_bundle())
        check("O6", "ogni-marca-regge-il-giudice", "Verification: OK" in testo,
              testo.strip()[:160])
        check("O6", "riverifica-interna-concorde", arch.verifica(esito["id"]).get("ok"))
        # IL CONTROLLO DI POLITICA: senza indicare nulla, la macchina deve ottenere una
        # marca QUALIFICATA. Se qui comparisse una marca ordinaria vorrebbe dire che i
        # prestatori europei non rispondono piu' e stiamo silenziosamente ripiegando.
        check("O6", "in-condizioni-normali-la-marca-e-QUALIFICATA",
              esito.get("qualificata"),
              "ottenuta da %s senza dichiarazione ETSI" % esito.get("tsa"))
        check("O6", "qualifica-archiviata-coerente",
              bool(riga["qualificata"]) == bool(esito.get("qualificata")))
    check("O6", "la-grande-maggioranza-delle-marche-riesce", riusciti >= 4,
          "solo %d su 6: non e' piu' un intoppo passeggero" % riusciti)
    shutil.rmtree(d, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════════
def _token_veri():
    """Procura token VERI da ogni Autorita' (o li rigenera dal vivo)."""
    fuori = []
    dato = b"BookinVIP - super collaudo marca temporale"
    impronta = hashlib.sha256(dato).digest()
    open(f("oracolo.txt"), "wb").write(dato)
    if not CON_RETE:
        return fuori
    for url in mt.TSA_PREDEFINITE:
        nome = url.split("//")[1].split("/")[0]
        e = mt.chiedi_marca(impronta, url=url, timeout=20)
        if e.get("ok"):
            p = f("vero_%s.tsr" % nome.replace(".", "_"))
            open(p, "wb").write(e["token"])
            fuori.append((nome, p, impronta))
    return fuori


if __name__ == "__main__":
    print("=" * 78)
    print("SUPER COLLAUDO — il mio codice giudicato da OpenSSL%s"
          % ("  (CON RETE VERA)" if CON_RETE else ""))
    rc, ver = openssl("version")
    print("giudice esterno: %s" % ver.strip())
    print("archivio CA:     %s" % (_ca_bundle() or "NON TROVATO"))
    print("=" * 78)
    t0 = time.time()
    for giro in range(1, GIRI + 1):
        print("\n-- giro %d di %d --" % (giro, GIRI))
        veri = _token_veri()
        if CON_RETE:
            print("   token veri ottenuti: %d" % len(veri))
        for nome, fn, arg in [("O1 oracolo andata", o1_oracolo_andata, None),
                              ("O2 oracolo ritorno", o2_oracolo_ritorno, None),
                              ("O3 oracolo risposte", o3_oracolo_risposte, veri),
                              ("O4 mutazione", o4_mutazione, veri),
                              ("O5 catena reale", o5_catena_reale, None),
                              ("O6 resistenza", o6_resistenza, None)]:
            prima = len(VIOL)
            if nome.startswith("O5"):
                prodotti = fn()
                if prodotti:
                    o3_oracolo_risposte(prodotti)
            elif arg is None:
                fn()
            else:
                fn(arg)
            print("   %-22s %s" % (nome, "OK" if len(VIOL) == prima
                                   else "%d VIOLAZIONI" % (len(VIOL) - prima)))
    print("\n" + "=" * 78)
    print("controlli: %d in %.1fs" % (CONTA["n"], time.time() - t0))
    shutil.rmtree(TMP, ignore_errors=True)
    if VIOL:
        print("VIOLAZIONI: %d" % len(VIOL))
        for v in VIOL[:50]:
            print("  X", v)
        sys.exit(1)
    print("VIOLAZIONI: 0 — il giudice esterno concorda su TUTTO")
    sys.exit(0)
