"""IL GIRO SUL BANCO — 15 host, 15 prenotazioni, e i pannelli che nessuno aveva mai provato.

A COSA SERVE, e perche' non basta una prenotazione ne' un host solo. Il 2026-08-08 la prova
generale fu fatta con UNA prenotazione e i numeri tornavano; il fondatore disse *«la nuova
chat rifà la prova con dieci prenotazioni, e siamo più sicuri»*, e la sera stessa *«15
prenotazioni diverse e 15 host, e vedi se funziona anche i pannelli admin e super admin,
controversie, voucher che arriva, calendario conferma»*. Ha ragione due volte:
  · una prenotazione puo' andare bene per caso, quindici no;
  · con UN host non si puo' nemmeno VEDERE l'errore che conta di piu' -- i soldi di un host
    che finiscono nel conto di un altro. Serve piu' di uno per accorgersene.

⛔ PRIMA DI SMONTARE IL BANCO, LEGGERE I REGISTRI:
    docker logs banco_prova_app 2>&1 | grep -iE "hold pagamento|warning|error"
   Il 2026-08-08 il banco fu smontato prima di leggerli, e si perse la prova di un difetto.

⛔ COSA QUESTO GIRO NON PROVA, dichiarato (D18 punto 3) -- un salto silenzioso fa sembrare
   «coperto» cio' che non e' stato nemmeno guardato:
   · il gesto di digitare la carta sulla pagina di Stripe: serve un browser. Qui si prova
     che la sessione la crea Stripe DAVVERO e si consegna il webhook firmato col nostro
     segreto, cioe' la stessa forma che manda Stripe;
   · il bonifico VERSO l'host: serve il conto Connect, oggi fermo sul questionario Stripe;
   · l'aspetto delle pagine: lo vede `collaudi/occhio_del_fondatore.py`, non questo;
   · i controlli che non si possono eseguire (es. bunker non configurato) NON vengono
     saltati in silenzio: finiscono nell'elenco «NON ESEGUITI» in fondo, e il giro lo dice.
"""
import datetime
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request

# ⛔ LA PORTA NON SI INCIDE NEL CODICE. Qui c'era `http://127.0.0.1:8080` scritto dentro, ed
# era l'unico strumento del banco a non leggere `BASE_VISIVO` — la stessa variabile che usano
# gia' `vicoli_ciechi.py` e `percorso_ospite_host.js`. Il danno di una porta che non si puo'
# spostare sta nel catalogo degli sbagli alla voce S12: un banco interrogato sulla porta
# sbagliata stampo' 21 rossi finti, che per un istante sembravano un disastro.
# 💡 E serve per una ragione concreta: `collaudi/batteria.py` accende il suo server sulla
# 8099, quindi con la porta incisa il banco non poteva entrare nel comando che lancia
# «tutti i test». Il valore storico resta come ripiego dichiarato: chi lo lancia a mano come
# ha sempre fatto non cambia niente.
# Guardia: `test_IL_BANCO_SI_PUO_PUNTARE_DOVE_IL_SERVER_STA_DAVVERO` (vista rossa prima).
BASE = os.environ.get("BASE_VISIVO", "http://127.0.0.1:8080")
PREZZO = 500                 # 5,00 EUR a notte
NOTTI = 2


def _default_di_main(nome, default):
    """Legge un default da `main_casavip.py` invece di riscriverlo qui: una cifra incisa in
    un banco invecchia col primo cambio e fa dichiarare rotto un sistema sano."""
    import io as _io
    import os as _os
    import re as _re
    p = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                      "main_casavip.py")
    try:
        with _io.open(p, encoding="utf-8", errors="replace") as f:
            m = _re.search(nome + r'["\']\s*,\s*["\'](\d+)["\']', f.read())
        return int(m.group(1)) if m else default
    except Exception:
        return default


def _psp_bps_del_motore():
    return _default_di_main("PAGAMENTO_BPS", 500)


def _psp_fisso_del_motore():
    return _default_di_main("PAGAMENTO_FISSO_CENTS", 25)


def _commissione_bps_del_banco():
    """La commissione che il SERVER DEL BANCO sta applicando davvero. Non e' per forza
    quella di produzione: l'avviatore locale non accende la rampa di lancio, quindi vale
    il regime. Si legge dall'ambiente perche' e' lo stesso da cui la prende il server."""
    import os as _os
    v = _os.environ.get("COMMISSIONE_BPS")
    if v and v.isdigit():
        return int(v)
    return 1000     # il valore che `avvia_server_visivo.py` passa a ConfigCasaVIP
QUANTE = int(os.environ.get("GIRI", "15"))
esiti = []
non_eseguiti = []


def chiama(m, p, corpo=None, testate=None, grezzo=None):
    d = grezzo.encode() if grezzo is not None else (
        json.dumps(corpo).encode() if corpo is not None else None)
    h = {"Content-Type": "application/json"}
    h.update(testate or {})
    r = urllib.request.Request(BASE + p, data=d, headers=h, method=m)
    try:
        with urllib.request.urlopen(r, timeout=30) as x:
            t = x.read().decode("utf-8", "replace")
            try:
                return x.status, json.loads(t)
            except Exception:
                return x.status, t[:400]
    except urllib.error.HTTPError as e:
        t = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(t)
        except Exception:
            return e.code, t[:400]
    except Exception as e:
        return 0, repr(e)


def passo(nome, ok, atteso="", ott=""):
    esiti.append(bool(ok))
    print("  %s %-58s %s" % ("OK " if ok else "NO ", nome,
                             "" if (ok and not atteso) else "(atteso %s / ottenuto %s)"
                             % (atteso, ott)))


def saltato(nome, perche):
    """Un controllo che NON si e' potuto eseguire. Non e' un OK e non e' un NO: e' un buco,
    e va detto. Un salto silenzioso e' la zona cieca che questo progetto ha gia' pagato."""
    non_eseguiti.append((nome, perche))
    print("  ??  %-58s NON ESEGUITO: %s" % (nome, perche))


def db(nome):
    # ⛔ `BANCO_DATI` PER PRIMA: e' la cartella che `avvia_server_visivo.py` dichiara all'avvio.
    # Prima qui c'erano solo le due di dentro il contenitore, e su una macchina senza Docker
    # questa funzione tornava SEMPRE `None`: cinque controlli sui soldi non erano misurabili
    # affatto, e la riga scritta accanto a loro («sta in /data») spiegava il buco col motivo
    # sbagliato. Restano dopo, perche' dentro il contenitore la cartella vera e' quella.
    for cartella in (os.environ.get("BANCO_DATI", ""), "/data", "/app/data"):
        if not cartella:
            continue
        p = os.path.join(cartella, nome + ".db")
        if os.path.exists(p):
            return sqlite3.connect("file:%s?mode=ro" % p, uri=True)
    return None


def db_fuori_posto(cartella):
    """I `.db` nati in una cartella dove non dovrebbero esserci — oppure `None` se quella
    cartella non esiste, cioe' se la domanda non si e' potuta nemmeno porre.

    ⛔ La distinzione fra «nessuno» e `None` e' tutto il punto. Prima il controllo [9]
    faceva `os.listdir("/app/data")` dentro un `try`, e su una macchina senza Docker
    l'eccezione lo riportava a lista vuota: il verdetto usciva OK **senza aver guardato
    niente**. E' lo sbaglio S7 — premessa mancante non e' un verde — lo stesso gia' tolto
    alla catena di impronte in questo stesso file, che li' era rimasto."""
    if not os.path.isdir(cartella):
        return None
    return sorted(n for n in os.listdir(cartella) if n.endswith(".db"))


def giornale():
    c = db("finanza")
    if c is None:
        return []
    try:
        return c.execute("SELECT seq,tipo,conto_dare,conto_avere,importo_cents,prev_hash,hash "
                         "FROM libro_giornale ORDER BY seq").fetchall()
    except Exception:
        return []
    finally:
        c.close()


def paga(rif):
    """Consegna il webhook di pagamento, costruito coi dati VERI della sessione Stripe."""
    k = os.environ.get("STRIPE_SECRET_KEY", "")
    req = urllib.request.Request("https://api.stripe.com/v1/checkout/sessions?limit=1",
                                 headers={"Authorization": "Bearer %s" % k,
                                          "User-Agent": "banco-prova"})
    with urllib.request.urlopen(req, timeout=25) as r:
        sess = json.load(r)["data"][0]
    if (sess.get("metadata") or {}).get("riferimento") != rif:
        return None, "la sessione piu' recente di Stripe non e' di questa prenotazione"
    from fase87_stripe_webhook import firma_di_test
    og = {"id": sess["id"], "mode": sess.get("mode", "payment"), "payment_status": "paid",
          "status": "complete", "amount_total": sess.get("amount_total"),
          "currency": sess.get("currency"), "metadata": sess.get("metadata") or {},
          "client_reference_id": sess.get("client_reference_id"),
          "payment_intent": sess.get("payment_intent") or ("pi_test_" + rif[:12])}
    carico = json.dumps({"type": "checkout.session.completed", "data": {"object": og}})
    f = firma_di_test(carico, os.environ.get("STRIPE_WEBHOOK_SECRET", ""), int(time.time()))
    s, _ = chiama("POST", "/api/payments/webhook", grezzo=carico,
                  testate={"Stripe-Signature": f})
    return s, sess


print("=" * 80)
print("GIRO SUL BANCO — %d host, %d prenotazioni, %d EUR a notte, %d notti"
      % (QUANTE, QUANTE, PREZZO / 100, NOTTI))
print("=" * 80)

# ---------------------------------------------------------------------------
# [1] I 15 HOST E I 15 ANNUNCI
# ---------------------------------------------------------------------------
print("\n-- [1] %d HOST DIVERSI, OGNUNO COL SUO ANNUNCIO --" % QUANTE)
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256   # noqa: E402

oggi = datetime.date.today()
host = []          # (host_id, token, slug)
for i in range(QUANTE):
    slug = "banco-h%02d" % (i + 1)
    s, c = chiama("POST", "/api/host/registrazione", {
        "email": "host%02d@prova.it" % (i + 1), "password": "password1",
        "accetta_termini": True, "accetta_clausole": True, "accetta_privacy": True,
        "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
    if s != 201 or not isinstance(c, dict) or not c.get("token"):
        passo("registrazione host %02d" % (i + 1), False, "201 + token", "%s %s" % (s, c))
        continue
    tk = {"X-Host-Token": c["token"]}
    s2, _ = chiama("POST", "/api/host/pubblica", {
        "slug": slug, "titolo": "Casa di prova %02d" % (i + 1), "citta": "Milano",
        "prezzo_notte_cents": PREZZO, "capacita": 2}, tk)
    s3, _ = chiama("POST", "/api/host/disponibilita_range", {
        "alloggio_id": slug, "da": oggi.isoformat(),
        "a": (oggi + datetime.timedelta(days=180)).isoformat(),
        "unita_totali": 1, "prezzo_netto_cents": PREZZO}, tk)
    if s2 in (200, 201) and s3 in (200, 201):
        host.append((c.get("host_id"), c["token"], slug))
    else:
        passo("annuncio+date host %02d" % (i + 1), False, "200/201", "%s / %s" % (s2, s3))

passo("%d host registrati con annuncio e date aperte" % QUANTE, len(host) == QUANTE,
      QUANTE, len(host))
passo("i %d token sono tutti DIVERSI" % QUANTE,
      len({h[1] for h in host}) == len(host), len(host), len({h[1] for h in host}))

# ISOLAMENTO: il calendario di un host non si vede col token di un altro.
if len(host) >= 2:
    da = oggi.isoformat()
    a = (oggi + datetime.timedelta(days=5)).isoformat()
    s, _ = chiama("GET", "/api/host/calendario?alloggio=%s&da=%s&a=%s" % (host[1][2], da, a),
                  None, {"X-Host-Token": host[0][1]})
    passo("un host NON vede il calendario di un altro", s == 403, 403, s)
    s, _ = chiama("GET", "/api/host/calendario?alloggio=%s&da=%s&a=%s" % (host[0][2], da, a),
                  None, {"X-Host-Token": host[0][1]})
    passo("ma vede BENISSIMO il proprio", s == 200, 200, s)
else:
    saltato("isolamento fra host", "servono almeno 2 host e non sono stati creati")

# ---------------------------------------------------------------------------
# [2] LE 15 PRENOTAZIONI
# ---------------------------------------------------------------------------
print("\n-- [2] LE %d PRENOTAZIONI (una per host) --" % QUANTE)
print("     pagate le pari · cancellate le dispari · la n.4 duplica le date della n.3")
print("     SULLO STESSO alloggio e deve essere RIFIUTATA · l'ultima resta NON pagata")
print("     · la n.2 finisce in CONTROVERSIA")

fatte = []            # (indice, rif, voucher, slug, pagata, cancellata)
pagate = cancellate = rifiutate = 0
for i in range(QUANTE):
    doppia = (i == 3 and QUANTE > 4)          # la n.4 duplica la n.3
    idx_alloggio = 2 if doppia else i
    if idx_alloggio >= len(host):
        continue
    slug = host[idx_alloggio][2]
    giorno = 10 + (2 if doppia else i) * 4
    ci = (oggi + datetime.timedelta(days=giorno)).isoformat()
    co = (oggi + datetime.timedelta(days=giorno + NOTTI)).isoformat()
    s, q = chiama("POST", "/api/concierge/quote",
                  {"alloggio_id": slug, "check_in": ci, "check_out": co, "party": 2})
    if s != 200 or not isinstance(q, dict) or not q.get("quote_token"):
        if doppia:
            rifiutate += 1
            print("  %2d  %s  %s  RIFIUTATA (date gia' occupate) -- ATTESO"
                  % (i + 1, slug, ci))
        else:
            passo("preventivo del giro %d" % (i + 1), False, 200, s)
        continue
    if q.get("prezzo_listino_cents") != PREZZO * NOTTI:
        passo("prezzo del giro %d" % (i + 1), False, PREZZO * NOTTI,
              q.get("prezzo_listino_cents"))
    s, b = chiama("POST", "/api/concierge/book",
                  {"quote_token": q["quote_token"], "email": "osp%02d@prova.it" % i,
                   "lang": "it"})
    if s != 201:
        if doppia:
            rifiutate += 1
            print("  %2d  %s  %s  RIFIUTATA in prenotazione -- ATTESO" % (i + 1, slug, ci))
        else:
            passo("prenotazione del giro %d" % (i + 1), False, 201, "%s %s" % (s, b))
        continue
    rif, vt = b.get("riferimento"), b.get("voucher_token")
    if i == QUANTE - 1:
        print("  %2d  %s  %s  prenotata, LASCIATA NON PAGATA -- voluto" % (i + 1, slug, ci))
        fatte.append((i, rif, vt, slug, False, False))
        continue
    st, _ = paga(rif)
    if st != 200:
        passo("pagamento del giro %d" % (i + 1), False, 200, st)
        fatte.append((i, rif, vt, slug, False, False))
        continue
    pagate += 1
    if i % 2 == 1 and i != 1:                 # dispari si cancellano, tranne la n.2
        s, canc = chiama("POST", "/api/concierge/cancella", {"voucher_token": vt})
        if s == 200 and isinstance(canc, dict) and canc.get("stato") in ("cancellata",
                                                                        "rimborsata"):
            cancellate += 1
            print("  %2d  %s  %s  pagata e CANCELLATA (rimborso %s)"
                  % (i + 1, slug, ci, canc.get("rimborso_cents")))
            fatte.append((i, rif, vt, slug, True, True))
        else:
            passo("cancellazione del giro %d" % (i + 1), False, 200, s)
            fatte.append((i, rif, vt, slug, True, False))
    else:
        print("  %2d  %s  %s  pagata" % (i + 1, slug, ci))
        fatte.append((i, rif, vt, slug, True, False))

passo("la doppia prenotazione sulle STESSE date e' stata RIFIUTATA", rifiutate >= 1,
      ">=1", rifiutate)

# ---------------------------------------------------------------------------
# [3] IL VOUCHER CHE ARRIVA
# ---------------------------------------------------------------------------
print("\n-- [3] IL VOUCHER CHE ARRIVA ALL'OSPITE --")
vive = [f for f in fatte if f[4] and not f[5]]
if vive:
    _, rif0, vt0, _, _, _ = vive[0]
    s, pagina = chiama("GET", "/voucher/" + vt0)
    passo("la pagina del voucher si apre ed e' una PAGINA, non un errore",
          s == 200 and isinstance(pagina, str), "200 + html", "%s + %s"
          % (s, type(pagina).__name__))
    s, _ = chiama("POST", "/api/voucher/messaggio",
                  {"voucher_token": vt0, "testo": "Buongiorno, a che ora posso entrare?"})
    passo("l'ospite scrive all'host dal voucher", s == 201, 201, s)
    s, th = chiama("GET", "/api/voucher/messaggi?voucher_token=" + vt0)
    quanti = len(th.get("messaggi", [])) if isinstance(th, dict) else 0
    passo("il messaggio si rilegge nella chat", s == 200 and quanti >= 1,
          "200 e >=1 messaggio", "%s e %d" % (s, quanti))
    s, _ = chiama("GET", "/voucher/token-inventato-che-non-esiste")
    passo("un voucher inventato NON apre niente", s != 200, "diverso da 200", s)
else:
    saltato("voucher e chat", "nessuna prenotazione pagata e viva")

# ---------------------------------------------------------------------------
# [4] IL CALENDARIO CONFERMA
# ---------------------------------------------------------------------------
print("\n-- [4] IL CALENDARIO DICE LA VERITA' --")


def occupati(slug, token, da, a):
    s, cal = chiama("GET", "/api/host/calendario?alloggio=%s&da=%s&a=%s" % (slug, da, a),
                    None, {"X-Host-Token": token})
    if s != 200 or not isinstance(cal, dict):
        return None
    n = 0
    for g in cal.get("giorni", []):
        if isinstance(g, dict) and (g.get("occupate") or g.get("occupati")
                                    or g.get("stato") in ("occupato", "pieno")):
            n += 1
    return n


if vive:
    i0, rif0, vt0, slug0, _, _ = vive[0]
    tok0 = [h[1] for h in host if h[2] == slug0][0]
    giorno = 10 + i0 * 4
    da = (oggi + datetime.timedelta(days=giorno)).isoformat()
    a = (oggi + datetime.timedelta(days=giorno + NOTTI)).isoformat()
    n = occupati(slug0, tok0, da, a)
    if n is None:
        saltato("calendario dopo la prenotazione", "il calendario non ha risposto 200")
    else:
        passo("dopo la prenotazione le %d notti risultano occupate" % NOTTI, n == NOTTI,
              NOTTI, n)
canc = [f for f in fatte if f[5]]
if canc:
    i1, rif1, vt1, slug1, _, _ = canc[0]
    tok1 = [h[1] for h in host if h[2] == slug1][0]
    giorno = 10 + i1 * 4
    da = (oggi + datetime.timedelta(days=giorno)).isoformat()
    a = (oggi + datetime.timedelta(days=giorno + NOTTI)).isoformat()
    n = occupati(slug1, tok1, da, a)
    if n is None:
        saltato("calendario dopo la cancellazione", "il calendario non ha risposto 200")
    else:
        passo("dopo la cancellazione le notti tornano LIBERE", n == 0, 0, n)
else:
    saltato("calendario dopo la cancellazione", "nessuna cancellazione riuscita")

# ---------------------------------------------------------------------------
# [5] LA CONTROVERSIA
# ---------------------------------------------------------------------------
print("\n-- [5] LA CONTROVERSIA: l'ospite contesta, i soldi si FERMANO --")
contesa = [f for f in fatte if f[0] == 1 and f[4] and not f[5]]
rif_contesa = None
if contesa:
    _, rif_contesa, vt_c, slug_c, _, _ = contesa[0]
    s, out = chiama("POST", "/api/garanzia/contesta",
                    {"voucher_token": vt_c, "motivo": "la stanza non e' come nell'annuncio"})
    passo("l'ospite apre la contestazione", s == 200, 200, "%s %s" % (s, out))
    c = db("payout")
    if c is None:
        # Stesso caso del libro giornale: senza il database, questo controllo non e' rosso
        # -- e' NON ESEGUITO. Segnarlo rosso insegnerebbe a ignorare i rossi, che e' il modo
        # di perdere quello vero.
        saltato("i soldi dell'host si FERMANO (payout trattenuto)",
                "nessun payout.db in BANCO_DATI (la cartella che il banco dichiara "
                "all'avvio) ne' in /data: non c'e' niente da leggere, quindi NON si misura")
    else:
        stato = None
        try:
            r = c.execute("SELECT stato FROM payout WHERE prenotazione_id=?",
                          (rif_contesa,)).fetchone()
            stato = r[0] if r else None
        finally:
            c.close()
        passo("i soldi dell'host si FERMANO (payout trattenuto)", stato == "trattenuto",
              "trattenuto", stato)
else:
    saltato("controversia", "la prenotazione n.2 non e' pagata e viva")

# ---------------------------------------------------------------------------
# [6] IL PANNELLO ADMIN
# ---------------------------------------------------------------------------
print("\n-- [6] IL PANNELLO ADMIN --")
CHIAVE = os.environ.get("ADMIN_KEY", "")       # letta dall'ambiente, MAI stampata
if not CHIAVE:
    saltato("pannello admin", "ADMIN_KEY non presente nell'ambiente del banco")
    admin = {}
else:
    admin = {"X-Admin-Key": CHIAVE}
    s, _ = chiama("POST", "/api/admin/login", {}, admin)
    passo("l'admin entra con la sua chiave", s == 200, 200, s)
    s, _ = chiama("POST", "/api/admin/login", {}, {"X-Admin-Key": "chiave-sbagliata"})
    passo("con la chiave SBAGLIATA la porta resta chiusa", s in (401, 429), "401/429", s)
    s, pren = chiama("GET", "/api/admin/prenotazioni", None, admin)
    quante = len(pren.get("prenotazioni", [])) if isinstance(pren, dict) else 0
    passo("l'admin vede l'elenco delle prenotazioni (%d)" % quante, s == 200, 200, s)
    # ⛔ NON si dichiara OK una controversia che non e' stata aperta: sarebbe un verde
    #    che non ha guardato niente. Se manca la premessa, il controllo e' un BUCO.
    if rif_contesa is None:
        saltato("la controversia compare nel pannello admin",
                "nessuna controversia e' stata aperta in questo giro")
    else:
        s, contro = chiama("GET", "/api/admin/controversie", None, admin)
        n_contro = len(contro.get("controversie", [])) if isinstance(contro, dict) else 0
        passo("la controversia compare nel pannello admin", s == 200 and n_contro >= 1,
              "200 e >=1", "%s e %d" % (s, n_contro))
    s, _ = chiama("GET", "/api/admin/prenotazioni")
    passo("senza chiave l'elenco NON si apre", s == 401, 401, s)

# ---------------------------------------------------------------------------
# [7] IL SUPER ADMIN (BUNKER)
# ---------------------------------------------------------------------------
print("\n-- [7] IL SUPER ADMIN (bunker): il secondo muro --")
sessione = None
if not CHIAVE:
    saltato("bunker", "senza ADMIN_KEY non si arriva nemmeno al secondo fattore")
else:
    codice = ""
    seg = os.environ.get("BUNKER_TOTP_SECRET", "").strip()
    if seg:
        try:
            from fase180_bunker import _codice_at
            codice = _codice_at(seg, int(time.time()) // 30)
        except Exception as e:
            print("     (codice TOTP non calcolabile: %r)" % (e,))
    if not codice:
        codice = os.environ.get("BUNKER_PASSWORD", "").strip()
    if not codice:
        saltato("bunker", "ne' TOTP ne' password super-admin presenti nell'ambiente")
    else:
        s, out = chiama("POST", "/api/bunker/login", {"codice": codice}, admin)
        sessione = out.get("sessione") if isinstance(out, dict) else None
        passo("il super-admin entra col secondo fattore", s == 200 and bool(sessione),
              "200 + sessione", s)
        s, _ = chiama("POST", "/api/bunker/login", {"codice": "0"}, admin)
        passo("col secondo fattore SBAGLIATO non si entra", s in (403, 429), "403/429", s)

if sessione:
    bk = dict(admin)
    bk["X-Bunker-Session"] = sessione
    for nome, rotta in (("stato del bunker", "/api/bunker/stato"),
                        ("guardiano degli stati impossibili", "/api/bunker/guardiano"),
                        ("invarianti (i teoremi sui soldi)", "/api/bunker/invarianti"),
                        ("integrita' dei database", "/api/bunker/integrita"),
                        ("riconciliazione con Stripe", "/api/bunker/riconciliazione"),
                        ("export contabile", "/api/bunker/export_contabile"),
                        ("scaglioni di commissione degli host", "/api/bunker/scaglioni_host")):
        s, _ = chiama("GET", rotta, None, bk)
        passo("super-admin: %s" % nome, s == 200, 200, s)
    s, _ = chiama("GET", "/api/bunker/guardiano", None, admin)   # senza sessione
    passo("senza sessione bunker il super-admin NON si apre", s in (401, 403), "401/403", s)
elif CHIAVE:
    saltato("le 7 letture del bunker", "non si e' ottenuta una sessione super-admin")

# ---------------------------------------------------------------------------
# [8] I CONTI, HOST PER HOST
# ---------------------------------------------------------------------------
print("\n-- [8] I CONTI, E QUESTA VOLTA HOST PER HOST --")
print("     (con UN host solo questo controllo non esisterebbe nemmeno)")
g = giornale()
# ⛔ SE IL LIBRO NON SI LEGGE, I TRE CONTROLLI QUI SOTTO SONO NON ESEGUITI, NON ROSSI:
# dichiarare guasto cio' che non si e' potuto guardare e' un falso allarme, e un falso
# allarme insegna a ignorare i rossi (regola ferrea 10).
# ⚠️ E FINO AL 2026-08-20 QUI C'ERA SCRITTO IL MOTIVO SBAGLIATO: «il giornale sta in /data,
# solo dentro il contenitore». Non era vero. Il banco (`avvia_server_visivo.py`) lasciava
# `db_finanza` a `:memory:`, cioe' il libro non esisteva su NESSUN disco -- e questa riga
# faceva sembrare Docker la causa di un buco che era nostro. Ora il banco lo scrive in
# `BANCO_DATI` e questi tre si misurano anche fuori dal contenitore.



def _perche_i_conti_non_si_misurano(libro_leggibile, righe_giornale):
    """Il motivo per cui i controlli contabili NON si possono misurare, o `None` se si puo'.

    ⛔ NASCE DA UN VERDE PER ASSENZA TROVATO IL 2026-08-21, e la guardia che c'era copriva
    meta' del problema. Con un giro su dati puliti e senza chiave Stripe il libro giornale
    ESISTE su disco ma ha ZERO righe: `inc == pagate * PREZZO * NOTTI` diventa `0 == 0` e
    quattro controlli sui soldi escono **OK senza aver letto una riga**. Zero righe non e'
    «i conti tornano»: e' «non ho guardato» — lo sbaglio S7, lo stesso gia' tolto al
    controllo [9] e rimasto qui.
    💡 Che il caso vuoto andasse dichiarato lo sapeva gia' questo file: il controllo della
    catena di impronte, sessanta righe piu' sotto, dice da sempre *«oppure e' vuoto: senza
    righe la catena non si verifica, quindi NON si misura»*. Era la stessa domanda con due
    risposte diverse a poche righe di distanza.
    """
    if not libro_leggibile:
        return ("nessun finanza.db in BANCO_DATI (la cartella che il banco dichiara "
                "all'avvio) ne' in /data: non c'e' niente da leggere, quindi NON si misura")
    if righe_giornale == 0:
        return ("il libro giornale c'e' ma e' VUOTO (zero righe): un OK su zero righe non "
                "direbbe «i conti tornano», direbbe «non ho guardato» -- e sarebbe il verde "
                "peggiore di tutti (sbaglio S7). Di solito significa che nessuna "
                "prenotazione ha pagato: senza chiave Stripe di prova il motore rifiuta")
    return None


_libro_leggibile = db("finanza") is not None
_non_misurabile = _perche_i_conti_non_si_misurano(_libro_leggibile, len(g))
if _non_misurabile:
    for _n in ("somma degli incassi = pagate x prezzo",
               "tariffa tecnica su ogni incasso",
               "ogni cancellazione pagata lascia la sua riga di rimborso nel giornale"):
        saltato(_n, _non_misurabile)
inc = sum(i for _, t, _, _, i, _, _ in g if t == "incasso")
com = sum(i for _, t, _, _, i, _, _ in g if t == "commissione")
if not _non_misurabile:
    passo("somma degli incassi = pagate x prezzo", inc == pagate * PREZZO * NOTTI,
          "%d (%d x %d)" % (pagate * PREZZO * NOTTI, pagate, PREZZO * NOTTI), inc)
# La riga del giornale "commissione" contiene commissione + tariffa tecnica.
# ⛔ La cifra si RICAVA dal motore: era scritta a mano (`pagate * 30`, cioe' il 3% di 10 EUR)
# e il 2026-08-10, passando al 5% + 0,25, avrebbe dichiarato rotto un banco sano.
# ⛔ E IL 2026-08-20, LA PRIMA VOLTA CHE QUESTO CONTROLLO HA POTUTO GUARDARE DAVVERO, E'
# USCITO ROSSO: atteso 975, misurato 2275. Il motore aveva ragione. Qui c'era scritto «l'host
# e' appena nato (promo, commissione 0%), quindi resta la sola tariffa tecnica», ma la rampa
# di lancio NON e' accesa sul banco: `ConfigCasaVIP.promo_lancio_attiva` vale `False` di
# serie e `avvia_server_visivo.py` non la accende (in produzione la accende `main_casavip.py`
# leggendo `PROMO_LANCIO`, che di serie e' «true»). Lo diceva gia' questo stesso file, nella
# docstring di `_commissione_bps_del_banco()` -- due frasi opposte a 440 righe di distanza,
# e quella giusta era usata solo dal controllo dei rimborsi. Misurato sul libro vero:
# 13 righe da 175 cents = 100 di commissione (10%) + 75 di tariffa tecnica.
# ⚠️ COSA QUESTO CONTROLLO NON GUARDA (D18 punto 3): il banco esercita il REGIME, non la
# rampa di lancio. Il caso «host appena nato, commissione 0%» qui non passa mai.
_atteso_tec = (PREZZO * NOTTI * _psp_bps_del_motore()) // 10000 + _psp_fisso_del_motore()
_atteso_riga = (PREZZO * NOTTI * _commissione_bps_del_banco()) // 10000 + _atteso_tec
if not _non_misurabile:
    passo("commissione + tariffa tecnica = %d cents su ogni incasso" % _atteso_riga,
          com == pagate * _atteso_riga, pagate * _atteso_riga, com)

# I SOLDI DI UN HOST NON FINISCONO A UN ALTRO. E' il controllo che con un host solo non
# si puo' fare, e sostituisce quello vecchio ("dovuto = incassi - commissioni"), che era
# vero PER COSTRUZIONE: sarebbe passato verde anche cancellando tutte le prenotazioni.
sballati = []
for _hid, tok, slug in host:
    s, out = chiama("GET", "/api/host/payout", None, {"X-Host-Token": tok})
    if s != 200 or not isinstance(out, dict):
        sballati.append((slug, "payout non leggibile (%s)" % s))
        continue
    mio = int(((out.get("payout") or {}).get("EUR") or {}).get("maturato", 0) or 0)
    # Quanto DEVE vedere l'host: il prezzo meno la commissione e meno la tariffa tecnica.
    # ⛔ Qui c'era `- 30` scritto a mano (il 3% di 10 EUR): il 2026-08-10, passando al
    # 5% + 0,25, questo controllo dichiarava sballati TUTTI e 15 gli host pur essendo i
    # conti giusti. Ora le due voci si RICAVANO dal motore, come tutto il resto.
    _tec = (PREZZO * NOTTI * _psp_bps_del_motore()) // 10000 + _psp_fisso_del_motore()
    _comm = (PREZZO * NOTTI * _commissione_bps_del_banco()) // 10000
    atteso = 0
    for (_i, rif, _vt, sl, pagata, cancellata) in fatte:
        if sl == slug and pagata and not cancellata and rif != rif_contesa:
            atteso += PREZZO * NOTTI - _comm - _tec
    if mio != atteso:
        sballati.append((slug, "vede %d, gli spetta %d" % (mio, atteso)))
# ⛔ L'ALTRA FACCIA DEL VERDE PER ASSENZA (2026-08-21). Questo controllo non legge il
# giornale ma l'API dei payout, quindi `_perche_i_conti_non_si_misurano` non lo copre: il
# suo denominatore sono le prenotazioni PAGATE. Con zero pagate ogni host vede 0 e gli
# spetta 0, e il confronto usciva OK **senza aver confrontato un solo importo** -- proprio
# il controllo che esiste per scoprire i soldi di un host finiti a un altro.
# 💡 Ma un payout ILLEGGIBILE resta rosso anche senza traffico: quello e' un guasto vero, e
# saltarlo insieme al resto nasconderebbe un'API rotta.
_letture_rotte = [s for s in sballati if "payout non leggibile" in s[1]]
if _letture_rotte or pagate:
    passo("ogni host vede SOLO i propri soldi", not sballati, "nessuno sballato",
          sballati[:4] if sballati else "nessuno")
else:
    saltato("ogni host vede SOLO i propri soldi",
            "nessuna prenotazione ha pagato: ogni host vede 0 e gli spetta 0, quindi il "
            "confronto non ha esaminato NIENTE. Un OK qui direbbe che i soldi di un host "
            "non finiscono a un altro senza aver visto muovere un centesimo (sbaglio S7)")

# LA TRACCIA DEL RIMBORSO (difetto chiuso il 2026-08-08): ogni cancellazione pagata deve
# lasciare la sua riga `rimborso` nel giornale — la STESSA che scrivono gia' il rimborso
# admin e la cancellazione dell'host. Prima non c'era: l'email prometteva i soldi e i conti
# non lo sapevano, e la stessa cancellazione finiva nel report fiscale solo se la faceva
# l'host. `-1` = la lettura e' fallita, che non e' «zero».
righe_rimborso = sum(1 for _, t, _, _, _, _, _ in g if t == "rimborso")
if not _non_misurabile:
    passo("ogni cancellazione pagata lascia la sua riga di rimborso nel giornale",
          righe_rimborso == cancellate, cancellate, righe_rimborso)

prev, rotta = "GENESI", None
for seq, _, _, _, _, ph, h in g:
    if ph != prev:
        rotta = seq
        break
    prev = h
# ⛔ SENZA RIGHE, QUESTO CONTROLLO PASSAVA SENZA GUARDARE NIENTE. Il 2026-08-10 il banco
# ha stampato «catena integra: OK» su un giornale di ZERO righe: il ciclo qui sopra non
# gira mai, `rotta` resta None e il verdetto e' verde. E' lo sbaglio S7 — premessa
# mancante = NON ESEGUITO, non verde — e in questo stesso file gli altri controlli che
# leggono il giornale lo dichiaravano gia'. Questo era rimasto indietro da solo.
if not _libro_leggibile or not g:
    saltato("catena di impronte del libro giornale",
            "il libro giornale non e' leggibile (nessun finanza.db in BANCO_DATI ne' in "
            "/data) oppure e' vuoto: senza righe la catena non si verifica, quindi NON si misura")
else:
    passo("catena di impronte del libro giornale", rotta is None, "integra",
          "rotta alla riga %s" % rotta if rotta is not None else "integra")

# ---------------------------------------------------------------------------
# [9] NESSUN DATABASE NATO NEL POSTO SBAGLIATO
# ---------------------------------------------------------------------------
print("\n-- [9] E DOPO TUTTO QUESTO, I DATABASE SONO ANCORA AL POSTO GIUSTO? --")
print("     (il controllo di fedelta' gira all'ACCENSIONE, quando i database creati alla")
print("      prima occorrenza non esistono ancora: questo chiude quel buco)")
# ⛔ QUESTO CONTROLLO ERA VERDE PER ASSENZA, e stava fra i 19 «OK». `os.listdir("/app/data")`
# su una macchina senza Docker solleva FileNotFoundError: la lista restava vuota e il
# verdetto usciva OK **senza aver guardato niente** (sbaglio S7, lo stesso gia' tolto alla
# catena di impronte poche righe sopra). Ora le domande sono DUE, e ognuna dice se ha
# guardato: dentro il contenitore si misura solo se quella cartella esiste davvero, e qui
# -- dove il banco sta girando -- si misura SEMPRE, perche' e' il caso che puo' capitare
# su questa macchina: un database nato nella cartella del progetto invece che in BANCO_DATI.
_RADICE_PROGETTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fuori = db_fuori_posto("/app/data")
if fuori is None:
    saltato("nessun database dentro il contenitore (muore col contenitore)",
            "/app/data non esiste su questa macchina: non c'e' niente da guardare, e "
            "dichiararlo verde sarebbe un verde per assenza")
else:
    passo("nessun database dentro il contenitore (muore col contenitore)", not fuori,
          "nessuno", fuori)
_in_casa = db_fuori_posto(_RADICE_PROGETTO)
passo("nessun database nato nella cartella del progetto", not _in_casa,
      "nessuno", _in_casa)

# ---------------------------------------------------------------------------
print("\n" + "=" * 80)
print("  pagate %d · cancellate %d · rifiutate %d · host %d · righe di giornale %d"
      % (pagate, cancellate, rifiutate, len(host), len(g)))
print("\n⛔ ORA, PRIMA DI SMONTARE IL BANCO:")
print("     docker logs banco_prova_app 2>&1 | grep -iE 'hold pagamento|warning|error'")
if non_eseguiti:
    print("\n⚠️  CONTROLLI NON ESEGUITI (%d) — non sono verdi, sono buchi dichiarati:"
          % len(non_eseguiti))
    for nome, perche in non_eseguiti:
        print("     · %-50s %s" % (nome, perche))
print("\n" + "=" * 80)
print("PASSI: %d   OK: %d   NON OK: %d   NON ESEGUITI: %d"
      % (len(esiti), sum(esiti), len(esiti) - sum(esiti), len(non_eseguiti)))
print("=" * 80)
sys.exit(0 if all(esiti) else 1)
