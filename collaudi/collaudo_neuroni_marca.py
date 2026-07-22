"""COLLAUDO CHIRURGICO — MARCA TEMPORALE, neuroni sotto neuroni sotto sotto neuroni.

Non ripete i test unitari: li ATTRAVERSA con metodi diversi, cercando il punto dove
la catena si spezza. Sei livelli, ognuno dentro il precedente:

  N1  IL PROTOCOLLO      - il DER regge il fuzzing e i valori estremi?
  N2  LA SICUREZZA       - si puo' far accettare un token che NON e' nostro?
  N3  IL SIGILLO         - segue davvero i registri, senza falsi positivi/negativi?
  N4  LA PERSISTENZA     - l'archivio regge concorrenza, riavvii, manomissioni?
  N5  IL CABLAGGIO       - la catena prova->sigillo->token->dossier regge da capo a fondo?
  N6  LA REALTA'         - la stessa catena, con un'Autorita' VERA (rete).

Esce 0 solo se NON c'e' NESSUNA violazione.
"""
import hashlib
import os
import random
import sqlite3
import sys
import tempfile
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

# Windows: la console cp1252 non regge i box-drawing (──) del report e il collaudo moriva
# al primo 'giro' senza verificare NULLA della marca (legalmente critica). Uno strumento di
# collaudo non deve MAI cadere per un carattere: uscita UTF-8 tollerante.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
os.chdir(REPO)

import fase184_marca_temporale as mt          # noqa: E402
from test_fase184_marca_temporale import _risposta, _tstinfo, _token_cms  # noqa: E402
from test_marca_qualificata import _token_qualificato  # noqa: E402

VIOL = []
CONTA = {"controlli": 0}
CON_RETE = "--con-rete" in sys.argv
GIRI = 3
for a in sys.argv:
    if a.startswith("--giri="):
        GIRI = int(a.split("=")[1])


def check(livello, regola, condizione, dettaglio=""):
    CONTA["controlli"] += 1
    if not condizione:
        VIOL.append("[%s] %s %s" % (livello, regola, dettaglio))


def rete_fedele(url, richiesta, timeout):
    t = mt._leggi_tlv(richiesta, 0)
    c = mt._figli(richiesta, t[1], t[2])
    imp = mt._figli(richiesta, c[1][1], c[1][2])[1]
    return _risposta(richiesta[imp[1]:imp[2]],
                     nonce=mt._intero_da(richiesta, c[2][1], c[2][2]))


# ═══════════════════════════════════════════════════════════════════════════════
def n1_protocollo():
    """N1 — il protocollo binario. Fuzzing e valori estremi."""
    for n in [0, 1, 127, 128, 255, 256, 65535, 65536, 2**31, 2**63 - 1, 2**64 - 1]:
        d = mt._der_intero(n)
        t = mt._leggi_tlv(d, 0)
        check("N1", "intero-andata-ritorno", t is not None
              and mt._intero_da(d, t[1], t[2]) == n, str(n))
        check("N1", "intero-mai-negativo", d[2] < 0x80 or d[2] == 0x00, str(n))

    for lung in [0, 1, 127, 128, 255, 256, 1000, 70000]:
        d = mt._der(0x04, b"\x41" * lung)
        t = mt._leggi_tlv(d, 0)
        check("N1", "lunghezza-esatta", t is not None and (t[2] - t[1]) == lung, str(lung))

    # fuzzing: nessun input deve far esplodere il parser
    rnd = random.Random(20260721)
    for _ in range(4000):
        n = rnd.randint(0, 300)
        blob = bytes(rnd.randrange(256) for _ in range(n))
        try:
            mt._leggi_tlv(blob, 0)
            t = mt._leggi_tlv(blob, 0)
            if t and (t[0] & 0x20):
                mt._figli(blob, t[1], t[2])
                mt._tutti_octet_string(blob, t[1], t[2])
            mt.interpreta_risposta(blob, b"\x00" * 32)
        except RecursionError:
            check("N1", "fuzz-nessuna-ricorsione-infinita", False, blob[:20].hex())
            break
        except Exception as e:
            check("N1", "fuzz-nessuna-eccezione", False,
                  "%s su %s" % (type(e).__name__, blob[:20].hex()))
            break

    # bomba di annidamento: un DER malevolo profondo non deve mandare in stack overflow
    bomba = b"\x04\x00"
    for _ in range(400):
        bomba = mt._der(0x30, bomba)
    # (niente `True` scritto a mano: la guardia verifica un ESITO, non una costante)
    retto = False
    trovati = -1
    try:
        t = mt._leggi_tlv(bomba, 0)
        trovati = len(mt._tutti_octet_string(bomba, t[1], t[2]))
        retto = True
    except RecursionError:
        retto = False
    check("N1", "bomba-annidamento-reggetta", retto,
          "RecursionError su 400 livelli di annidamento")
    check("N1", "bomba-annidamento-limita-la-discesa", retto and trovati >= 0,
          "la discesa ricorsiva non ha prodotto un risultato leggibile")

    # la richiesta e' sempre DER valido e contiene esattamente la nostra impronta
    rnd2 = random.Random(7)
    for _ in range(300):
        imp = bytes(rnd2.randrange(256) for _ in range(32))
        nonce = rnd2.randrange(1, 2**64)
        req = mt.costruisci_richiesta(imp, nonce)
        t = mt._leggi_tlv(req, 0)
        check("N1", "richiesta-ben-formata", t is not None and t[3] == len(req))
        check("N1", "richiesta-contiene-impronta", imp in req)


# ═══════════════════════════════════════════════════════════════════════════════
def n2_sicurezza():
    """N2 — si puo' infilare un token che non certifica il nostro documento?"""
    nostra = hashlib.sha256(b"il nostro sigillo").digest()
    altra = hashlib.sha256(b"un altro documento").digest()

    check("N2", "token-di-altri-respinto",
          not mt.interpreta_risposta(_risposta(altra), nostra).get("ok"))
    check("N2", "replay-nonce-vecchio-respinto",
          not mt.interpreta_risposta(_risposta(nostra, nonce=111), nostra, 222).get("ok"))
    for stato in (2, 3, 4, 5):
        check("N2", "stato-rifiuto-non-passa-%d" % stato,
              not mt.interpreta_risposta(_risposta(nostra, stato=stato), nostra).get("ok"))

    # impronta troncata/allungata di un solo byte
    for falsa in [nostra[:31], nostra + b"\x00", nostra[:16] + nostra[:16]]:
        tst = _tstinfo(falsa)
        risp = mt._der(0x30, mt._der(0x30, mt._der_intero(0)) + _token_cms(tst))
        check("N2", "impronta-diversa-di-un-byte-respinta",
              not mt.interpreta_risposta(risp, nostra).get("ok"), falsa.hex()[:16])

    # bit-flip su ogni byte dell'impronta dentro un token altrimenti valido
    for i in range(0, 32, 3):
        girata = bytearray(nostra)
        girata[i] ^= 0x01
        check("N2", "bitflip-impronta-respinto",
              not mt.interpreta_risposta(_risposta(bytes(girata)), nostra).get("ok"),
              "byte %d" % i)

    # un token con DUE TSTInfo, di cui uno nostro: si accetta solo quello giusto
    doppio = mt._der(0x30, mt._der(0x30, mt._der_intero(0))
                     + mt._der(0x30, mt._der(0x04, _tstinfo(altra))
                               + mt._der(0x04, _tstinfo(nostra, seriale=777))))
    e = mt.interpreta_risposta(doppio, nostra)
    check("N2", "sceglie-il-tstinfo-giusto", e.get("ok") and e.get("seriale") == 777,
          str(e.get("motivo") or e.get("seriale")))

    # nessuna via silenziosa: ogni rifiuto deve dire perche'
    for cattiva in [b"", b"\x30\x00", os.urandom(80), _risposta(altra)]:
        e = mt.interpreta_risposta(cattiva, nostra)
        check("N2", "rifiuto-sempre-motivato",
              (not e.get("ok")) and bool(e.get("motivo")))


# ═══════════════════════════════════════════════════════════════════════════════
def n3_sigillo():
    """N3 — il sigillo segue i registri: nessun falso positivo, nessun falso negativo."""
    from fase163_accettazioni import crea_registro_accettazioni
    d = tempfile.mkdtemp()
    reg = crea_registro_accettazioni(os.path.join(d, "a.db"), b"k" * 32)

    visti = {}
    for i in range(40):
        reg.registra("host-%d" % i, ip="10.0.0.%d" % (i % 250), vessatorie=bool(i % 2))
        s = reg.sigillo()
        check("N3", "sigillo-sempre-sha256", len(s["sigillo"]) == 64
              and s["sigillo"] != "errore", s["sigillo"][:12])
        check("N3", "sigillo-mai-ripetuto", s["sigillo"] not in visti,
              "collisione con la prova %s" % visti.get(s["sigillo"]))
        check("N3", "conteggio-righe-esatto", s["righe"] == i + 1)
        visti[s["sigillo"]] = i

    stabile = reg.sigillo()["sigillo"]
    for _ in range(20):
        check("N3", "sigillo-stabile-a-riposo", reg.sigillo()["sigillo"] == stabile)

    # ogni singola manomissione deve emergere
    for colonna, valore in [("firma", "'falsificata'"), ("ip", "'0.0.0.0'"),
                            ("versione", "'1999-01-01'"), ("vessatorie", "0")]:
        d2 = tempfile.mkdtemp()
        r2 = crea_registro_accettazioni(os.path.join(d2, "a.db"), b"k" * 32)
        for i in range(6):
            r2.registra("h%d" % i, ip="1.1.1.1", vessatorie=True)
        prima = r2.sigillo()["sigillo"]
        con = sqlite3.connect(os.path.join(d2, "a.db"))
        con.execute("UPDATE accettazioni SET %s=%s WHERE id=3" % (colonna, valore))
        con.commit()
        con.close()
        dopo = r2.sigillo()["sigillo"]
        if colonna == "firma":
            check("N3", "manomissione-firma-emerge", dopo != prima)
        else:
            # cambiare un dato SENZA rifare la firma: il sigillo non cambia (usa le firme),
            # ma la prova risulta NON INTEGRA -> il buco e' comunque coperto
            prove = r2.elenco("h2") + r2.elenco("h3")
            check("N3", "dato-alterato-emerge-come-non-integro",
                  any(not p.get("integra") for p in prove) or dopo != prima,
                  "colonna %s" % colonna)

    # il sigillo del giorno reagisce a ogni ingrediente
    base = mt.componi_sigillo(giorno="2026-07-21", accettazioni_sigillo="a" * 64,
                              accettazioni_righe=1, giornale_testa="b" * 64,
                              giornale_righe=1)["impronta"]
    for k, v in [("giorno", "2026-07-22"), ("accettazioni_sigillo", "z" * 64),
                 ("accettazioni_righe", 2), ("giornale_testa", "z" * 64),
                 ("giornale_righe", 2)]:
        arg = dict(giorno="2026-07-21", accettazioni_sigillo="a" * 64,
                   accettazioni_righe=1, giornale_testa="b" * 64, giornale_righe=1)
        arg[k] = v
        check("N3", "sigillo-giorno-reattivo-" + k,
              mt.componi_sigillo(**arg)["impronta"] != base)
        check("N3", "sigillo-giorno-ricalcolabile",
              hashlib.sha256(mt.componi_sigillo(**arg)["canonico"].encode()).hexdigest()
              == mt.componi_sigillo(**arg)["impronta"])


# ═══════════════════════════════════════════════════════════════════════════════
def n4_persistenza():
    """N4 — l'archivio sotto stress: concorrenza, riavvii, manomissioni."""
    d = tempfile.mkdtemp()
    percorso = os.path.join(d, "m.db")
    arch = mt.crea_archivio_marche(percorso)
    imp = hashlib.sha256(b"x").digest()
    esito = mt.interpreta_risposta(_risposta(imp, nonce=1), imp, 1)

    # 30 thread scrivono lo STESSO giorno: ne deve restare UNA sola riuscita
    def scrivi(i):
        arch.scrivi(giorno="2026-07-21", ambito="registri", impronta=imp.hex(),
                    canonico="C", esito=esito)

    th = [threading.Thread(target=scrivi, args=(i,)) for i in range(30)]
    [t.start() for t in th]
    [t.join() for t in th]
    ok = [r for r in arch.elenco(limit=100) if r["stato"] == "ok"]
    check("N4", "una-sola-marca-riuscita-sotto-gara", len(ok) == 1,
          "trovate %d" % len(ok))

    # riavvio: l'archivio si riapre e i dati ci sono ancora
    arch2 = mt.crea_archivio_marche(percorso)
    check("N4", "sopravvive-al-riavvio", arch2.gia_marcato("2026-07-21"))
    idm = [r for r in arch2.elenco() if r["stato"] == "ok"][0]["id"]
    check("N4", "token-riverificabile-dopo-riavvio", arch2.verifica(idm).get("ok"))

    # manomissioni mirate all'archivio
    for colonna, valore, atteso_ok in [("impronta", "'" + "ff" * 32 + "'", False),
                                       ("gen_time", "1", True),
                                       ("token_b64", "''", False)]:
        d3 = tempfile.mkdtemp()
        p3 = os.path.join(d3, "m.db")
        a3 = mt.crea_archivio_marche(p3)
        r = a3.scrivi(giorno="2026-07-21", ambito="registri", impronta=imp.hex(),
                      canonico="C", esito=esito)
        con = sqlite3.connect(p3)
        con.execute("UPDATE marche SET %s=%s WHERE id=?" % (colonna, valore), (r["id"],))
        con.commit()
        con.close()
        v = a3.verifica(r["id"])
        check("N4", "manomissione-%s-rilevata" % colonna,
              bool(v.get("ok")) == atteso_ok, str(v))
        if colonna == "gen_time":
            check("N4", "ora-riscritta-segnalata", not v.get("coerente_con_archivio"))

    # i fallimenti si accumulano tutti (servono a provare che ci si e' provato)
    d4 = tempfile.mkdtemp()
    a4 = mt.crea_archivio_marche(os.path.join(d4, "m.db"))
    for i in range(15):
        a4.scrivi(giorno="2026-07-21", ambito="registri", impronta=imp.hex(),
                  canonico="C", esito={"ok": False, "motivo": "rete_giu"})
    check("N4", "tentativi-falliti-tutti-archiviati", a4.conta() == 15,
          "%d invece di 15" % a4.conta())
    check("N4", "fallimenti-non-contano-come-marcato",
          not a4.gia_marcato("2026-07-21"))


# ═══════════════════════════════════════════════════════════════════════════════
def n5_cablaggio():
    """N5 — la catena intera dentro la macchina vera."""
    import json
    import shutil
    from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
    from fase83_server import crea_router

    d = tempfile.mkdtemp()
    PW = "SuperPw@1"
    AK = {"X-Admin-Key": "ak", "X-Forwarded-For": "203.0.113.9", "User-Agent": "F"}
    sis = crea_sistema(ConfigCasaVIP(
        abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
        db_catalogo=d + "/c.db", db_inventario=d + "/i.db", db_registro_host=d + "/r.db",
        db_accettazioni=d + "/a.db", db_marche=d + "/m.db", db_pendenti=d + "/p.db",
        db_finanza=d + "/f.db", bunker_password=PW))
    r = crea_router(sis, host_key="hk", admin_key="ak", base_url="https://bookinvip.com")

    def g(m, p, b=None, h=None, q=None):
        return r.gestisci(m, p, q or {}, json.dumps(b) if b is not None else None, h or AK)

    st, o = g("POST", "/api/bunker/login", {"codice": PW})
    H = dict(AK)
    H["X-Bunker-Session"] = o["sessione"]

    check("N5", "archivio-cablato", sis.marche is not None)

    # prove vere, poi marca, poi verifica end-to-end
    for i in range(5):
        sis.accettazioni.registra("host-%d" % i, ip="9.9.9.%d" % i, vessatorie=True)
    esito = mt.marca_i_registri(sis.marche, accettazioni=sis.accettazioni,
                                finanza=sis.finanza, giorno="2026-07-21",
                                url="http://t.finto", trasporto=rete_fedele)
    check("N5", "marca-riuscita", esito.get("ok"), str(esito.get("motivo")))

    # il sigillo dichiarato nel canonico DEVE combaciare col registro vero, adesso
    riga = sis.marche.elenco()[0]
    atteso = mt.componi_sigillo(
        giorno="2026-07-21",
        accettazioni_sigillo=sis.accettazioni.sigillo()["sigillo"],
        accettazioni_righe=sis.accettazioni.sigillo()["righe"],
        giornale_testa=str(sis.finanza.verifica_catena().get("testa")),
        giornale_righe=int(sis.finanza.verifica_catena().get("righe") or 0))
    check("N5", "canonico-coincide-col-registro-vivo",
          riga["canonico"] == atteso["canonico"],
          "\n  archiviato: %s\n  ricalcolato: %s" % (riga["canonico"], atteso["canonico"]))
    check("N5", "impronta-coincide", riga["impronta"] == atteso["impronta"])

    # il token archiviato certifica proprio quella impronta
    v = sis.marche.verifica(riga["id"])
    check("N5", "token-certifica-il-sigillo",
          v.get("ok") and v.get("impronta_hex") == riga["impronta"], str(v))

    # rotte protette
    for metodo, rotta in [("GET", "/api/bunker/marche_temporali"),
                          ("POST", "/api/bunker/marca_ora")]:
        for testa in [{}, {"X-Admin-Key": "ak"}, {"X-Bunker-Session": "falsa"}]:
            st, _ = g(metodo, rotta, {} if metodo == "POST" else None, testa)
            check("N5", "rotta-protetta", st == 403, "%s %s -> %d" % (metodo, rotta, st))
    st, tok = r.scarica_marca(riga["id"], {})
    check("N5", "download-token-protetto", st == 403 and tok is None)

    # dossier CSV e JSON
    st, c = g("GET", "/api/bunker/export_legale", None, H, {"formato": "csv"})
    check("N5", "dossier-csv-contiene-marca",
          "MARCHE TEMPORALI" in c["contenuto"] and "# marche_temporali,1" in c["contenuto"])
    check("N5", "dossier-csv-sigillato", c["certificato"])
    st, c = g("GET", "/api/bunker/export_legale", None, H, {"formato": "json"})
    dati = json.loads(c["contenuto"].split("\n# FINE DOSSIER")[0])
    check("N5", "dossier-json-contiene-marca",
          dati["marche_temporali"]["totale"] == 1
          and dati["marche_temporali"]["elenco"][0]["token_riverificato"] == "SI")

    # LA PROVA CHIAVE: aggiungo una prova DOPO la marca -> il sigillo di oggi non torna piu'
    sigillo_marcato = sis.accettazioni.sigillo()["sigillo"]
    sis.accettazioni.registra("host-intruso", ip="6.6.6.6", vessatorie=True)
    check("N5", "aggiunta-postuma-rompe-il-sigillo-marcato",
          sis.accettazioni.sigillo()["sigillo"] != sigillo_marcato)
    check("N5", "il-token-vecchio-resta-valido-per-lo-stato-vecchio",
          sis.marche.verifica(riga["id"]).get("ok"),
          "il token deve continuare a certificare lo stato di ieri")

    # niente trapela
    for rotta in ["/api/trasparenza", "/api/salute"]:
        st, corpo = g("GET", rotta, None, {})
        if isinstance(corpo, dict):
            check("N5", "nessuna-marca-in-pubblico",
                  "marche" not in corpo and "marche_temporali" not in corpo, rotta)
    shutil.rmtree(d, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════════
def n6_realta():
    """N6 — la stessa catena contro un'Autorita' VERA."""
    if not CON_RETE:
        print("   N6 saltato (usa --con-rete per interrogare le Autorita' vere)")
        return
    d = tempfile.mkdtemp()
    arch = mt.crea_archivio_marche(os.path.join(d, "m.db"))

    class Reg:
        def sigillo(self):
            return {"sigillo": hashlib.sha256(b"collaudo reale").hexdigest(), "righe": 7}

    class Fin:
        def verifica_catena(self):
            return {"ok": True, "testa": "t" * 64, "righe": 3}

    risposte, qualificate, mute = 0, 0, []
    for i, url in enumerate(mt.TSA_PREDEFINITE):
        esito = mt.marca_i_registri(arch, accettazioni=Reg(), finanza=Fin(),
                                    giorno="2026-07-%02d" % (10 + i), url=url)
        nome_a = url.split("//")[1].split("/")[0]
        if not esito.get("ok"):
            # NON e' una violazione: un'Autorita' momentaneamente giu' e' esattamente
            # il caso per cui esiste il failover. Si annota e si va avanti.
            mute.append(nome_a)
            continue
        risposte += 1
        if esito.get("qualificata"):
            qualificate += 1
        v = arch.verifica(esito["id"])
        check("N6", "token-reale-riverificato", v.get("ok"), str(v))
        check("N6", "ora-certificata-plausibile",
              abs(int(esito["gen_time"]) - int(time.time())) < 7200,
              "scarto %ds" % abs(int(esito["gen_time"]) - int(time.time())))
        # scritto su disco e riletto: e' cio' che si consegna a un perito
        tok = arch.token(esito["id"])
        check("N6", "token-reale-e-asn1", tok and tok[0] == 0x30 and len(tok) > 1000,
              "%d byte" % (len(tok) if tok else 0))

    # IL REQUISITO VERO: non che tutte rispondano, ma che la prova si possa fare.
    if mute:
        print("      (non hanno risposto in questo giro: %s — e' il caso per cui "
              "esiste il failover)" % ", ".join(mute))
    check("N6", "almeno-un-prestatore-QUALIFICATO-risponde", qualificate >= 1,
          "nessuna Autorita' qualificata raggiungibile: qui si', c'e' un problema")
    check("N6", "almeno-due-Autorita-raggiungibili", risposte >= 2,
          "solo %d su %d hanno risposto: il failover si sta assottigliando"
          % (risposte, len(mt.TSA_PREDEFINITE)))


# ═══════════════════════════════════════════════════════════════════════════════
def n7_qualifica():
    """N7 — la QUALIFICA eIDAS: si legge, non si crede; e non si puo' falsificare."""
    nostra = hashlib.sha256(b"sigillo per la qualifica").digest()

    # il riconoscimento e' esatto nei due sensi
    q = mt.interpreta_risposta(_token_qualificato(nostra), nostra)
    o = mt.interpreta_risposta(_risposta(nostra), nostra)
    check("N7", "riconosce-la-qualificata", q.get("ok") and mt.e_qualificata(q["token"]))
    check("N7", "ordinaria-non-e-qualificata",
          o.get("ok") and not mt.e_qualificata(o["token"]))

    # l'OID dello standard, byte per byte
    check("N7", "oid-etsi-esatto",
          mt._der_oid(mt.OID_QTST_ETSI) == bytes.fromhex("0607040081975e0101"))

    # nessun input rompe il riconoscimento
    rnd = random.Random(4242)
    for _ in range(1500):
        blob = bytes(rnd.randrange(256) for _ in range(rnd.randint(0, 200)))
        try:
            mt.e_qualificata(blob)
        except Exception as e:
            check("N7", "riconoscimento-mai-esplode", False, type(e).__name__)
            break
    for cattivo in [None, "", 0, [], {}, b"", bytes([6, 7, 4, 0]),
                    bytes(range(8))]:
        try:
            check("N7", "riconoscimento-tollerante", mt.e_qualificata(cattivo) is False)
        except Exception as e:
            check("N7", "riconoscimento-tollerante", False, type(e).__name__)

    # un OID QUASI uguale non deve passare per qualificato
    for storto in [(0, 4, 0, 19422, 1, 2), (0, 4, 0, 19423, 1, 1), (0, 4, 0, 1862, 1, 1),
                   (0, 4, 0, 19422, 2, 1), (2, 4, 0, 19422, 1, 1)]:
        finto = mt._der(0x30, mt._der_oid(storto) + mt._der(0x05, b""))
        tst = _tstinfo(nostra)
        econtent = mt._der(0xA0, mt._der(0x04, tst))
        encap = mt._der(0x30, mt._der_oid((1, 2, 840, 113549, 1, 9, 16, 1, 4)) + econtent)
        signed = mt._der(0x30, mt._der_intero(3) + mt._der(0xA0, finto) + encap)
        tok = mt._der(0x30, mt._der_oid((1, 2, 840, 113549, 1, 7, 2))
                      + mt._der(0xA0, signed))
        check("N7", "oid-simile-non-passa", not mt.e_qualificata(tok), str(storto))

    # la politica: i qualificati sempre prima, mai un ripiego davanti
    lista = mt._tsa_configurate()
    primo_rip = min((lista.index(u) for u in mt.TSA_RIPIEGO if u in lista),
                    default=len(lista))
    ultimo_q = max((lista.index(u) for u in mt.TSA_QUALIFICATE if u in lista), default=-1)
    check("N7", "qualificati-interrogati-per-primi", primo_rip > ultimo_q)
    check("N7", "almeno-due-qualificati", len(mt.TSA_QUALIFICATE) >= 2)

    # la catena: archivio -> riverifica, con e senza qualifica
    d = tempfile.mkdtemp()
    arch = mt.crea_archivio_marche(os.path.join(d, "m.db"))
    for giorno, rete, atteso in [("2026-10-01", _rete_qualificata_finta, True),
                                 ("2026-10-02", rete_fedele, False)]:
        e = mt.marca_i_registri(arch, accettazioni=None, finanza=None, giorno=giorno,
                                url="http://t.finto", trasporto=rete)
        check("N7", "marca-riuscita-%s" % giorno, e.get("ok"), str(e.get("motivo")))
        if not e.get("ok"):
            continue
        check("N7", "qualifica-riportata-%s" % giorno, e["qualificata"] is atteso)
        riga = [r for r in arch.elenco() if r["id"] == e["id"]][0]
        check("N7", "qualifica-archiviata-%s" % giorno, bool(riga["qualificata"]) is atteso)
        v = arch.verifica(e["id"])
        check("N7", "qualifica-riletta-dal-token-%s" % giorno,
              bool(v["qualificata"]) is atteso)
        check("N7", "qualifica-coerente-%s" % giorno, v["qualifica_coerente"])

    # manomissione: flag alzato a mano nel database
    import sqlite3 as _s
    e = mt.marca_i_registri(arch, accettazioni=None, finanza=None, giorno="2026-10-03",
                            url="http://t.finto", trasporto=rete_fedele)
    con = _s.connect(os.path.join(d, "m.db"))
    con.execute("UPDATE marche SET qualificata=1 WHERE id=?", (e["id"],))
    con.commit()
    con.close()
    v = arch.verifica(e["id"])
    check("N7", "flag-alzato-a-mano-smascherato",
          (not v["qualificata"]) and (not v["qualifica_coerente"]))

    # divieto di ripiego
    vecchio = os.environ.get("MARCA_SOLO_QUALIFICATA")
    try:
        os.environ["MARCA_SOLO_QUALIFICATA"] = "1"
        check("N7", "col-divieto-spariscono-i-ripieghi",
              mt._tsa_configurate() == mt.TSA_QUALIFICATE)
        d2 = tempfile.mkdtemp()
        a2 = mt.crea_archivio_marche(os.path.join(d2, "m.db"))
        r = mt.marca_i_registri(a2, accettazioni=None, finanza=None, giorno="2026-10-04",
                                url="http://t.finto", trasporto=rete_fedele)
        check("N7", "col-divieto-niente-marca-ordinaria",
              (not r["ok"]) and not a2.gia_marcato("2026-10-04"), str(r.get("motivo")))
    finally:
        if vecchio is None:
            os.environ.pop("MARCA_SOLO_QUALIFICATA", None)
        else:
            os.environ["MARCA_SOLO_QUALIFICATA"] = vecchio


def _rete_qualificata_finta(url, richiesta, timeout):
    t = mt._leggi_tlv(richiesta, 0)
    c = mt._figli(richiesta, t[1], t[2])
    imp = mt._figli(richiesta, c[1][1], c[1][2])[1]
    return _token_qualificato(richiesta[imp[1]:imp[2]],
                              nonce=mt._intero_da(richiesta, c[2][1], c[2][2]))


# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 78)
    print("COLLAUDO CHIRURGICO — MARCA TEMPORALE  (%d giri%s)"
          % (GIRI, ", CON RETE VERA" if CON_RETE else ""))
    print("=" * 78)
    t0 = time.time()
    for giro in range(1, GIRI + 1):
        print("\n── giro %d di %d ──" % (giro, GIRI))
        for nome, fn in [("N1 protocollo", n1_protocollo), ("N2 sicurezza", n2_sicurezza),
                         ("N3 sigillo", n3_sigillo), ("N4 persistenza", n4_persistenza),
                         ("N5 cablaggio", n5_cablaggio), ("N6 realta'", n6_realta),
                         ("N7 qualifica", n7_qualifica)]:
            prima = len(VIOL)
            fn()
            print("   %-16s %s" % (nome, "OK" if len(VIOL) == prima
                                   else "%d VIOLAZIONI" % (len(VIOL) - prima)))
    print("\n" + "=" * 78)
    print("controlli eseguiti: %d in %.1fs" % (CONTA["controlli"], time.time() - t0))
    if VIOL:
        print("VIOLAZIONI: %d" % len(VIOL))
        for v in VIOL[:40]:
            print("  ✗", v)
        sys.exit(1)
    print("VIOLAZIONI: 0  —  catena integra a tutti i livelli")
    sys.exit(0)
