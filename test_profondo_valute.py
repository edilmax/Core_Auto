# -*- coding: utf-8 -*-
"""COLLAUDO PROFONDO — MULTI-VALUTA LUNGO TUTTO IL PERCORSO DEI SOLDI.

IL CONTRATTO (in 8 righe, cosi' e' chiaro cosa questo file difende)
    1. L'host prezza in una valuta X. L'ospite paga in X. L'host incassa in X. La nostra
       commissione e' in X. Nessuna conversione forzata (like-for-like, fase99).
    2. La riga "≈ nella tua moneta" e' SOLO display: non tocca ne' il totale ne' cio' che
       arriva a Stripe.
    3. Tutta l'aritmetica e' in UNITA' MINORI intere della valuta. Non esiste "il
       centesimo": su JPY/KRW l'unita' minima e' 1 yen/1 won, su BHD e' 1 fils (1/1000).
    4. In OGNI valuta vale l'identita' contabile
           totale = netto_host + commissione + tariffa tecnica (3%) + tassa di soggiorno
    5. Gli arrotondamenti cadono sempre dalla parte giusta: mai una perdita a nostro
       carico, mai un'unita' regalata all'ospite.

I CONFINI (dove il codice deve dire di no, non "arrangiarsi")
    · prezzo cosi' basso che la tariffa tecnica supera cio' che resta all'host
      -> 422 `prezzo_non_sostenibile` (non si fa sparire la differenza a nostro carico);
    · valuta ospite assente/uguale/senza tasso -> nessuna stima (0), mai un numero inventato;
    · valuta di un annuncio gia' venduto -> non si cambia (fase83 `_blinda_valuta`).

LE MODALITA' D'ERRORE CHE QUESTO FILE CACCIA (sono errori di SCALA, non di formato)
    a) ×100 / ÷100 su una valuta senza decimali (¥1.800.000 al posto di ¥18.000);
    b) valuta fissa "EUR" cablata da qualche parte nel percorso (Stripe, payout, giornale);
    c) somma di importi di valute diverse (¥ + € = un numero senza significato);
    d) una percentuale che arrotonda per eccesso a nostro sfavore o per difetto a favore
       dell'ospite, cioe' denaro creato dal nulla.

LA GRIGLIA (importi scelti perche' le divisioni NON tornino tonde)
    valute   EUR/USD/GBP (2 decimali) · JPY/KRW (0 decimali) · BHD (3 decimali)
    importi  1 · 99 · 100 · 12345 · 999999 unita' minori a notte
    notti    1 · 2 · 7 · 30
    L'attesa non e' copiata dal motore: e' ricalcolata da zero in `_oracolo` a partire dal
    contratto (ORACOLO INDIPENDENTE), e prevede anche i casi in cui il motore deve
    RIFIUTARE il preventivo.

VISTE ROSSE (regola aurea: nessun verde vale finche' non e' stato visto rosso)
  1. BUG VERO TROVATO QUI, non iniettato — `fase59._converti_indicativo` moltiplicava le
     unita' minori per il tasso SENZA cambiare scala fra le due valute: la stima "≈ nella
     tua moneta" usciva 100 volte sbagliata (¥36.800 mostrati come "≈ 2,30 €"; 412,00 €
     mostrati come "≈ ¥6.592.000"; 10 volte sbagliata verso il BHD). Solo display, mai
     addebitato — ma e' esattamente il difetto di SCALA che il fondatore ha visto in
     vetrina. `test_la_stima_nella_moneta_dell_ospite_ha_la_scala_giusta` era ROSSO prima
     della correzione (230 invece di 23000) e verde dopo.
  2. `fase59.quota`: tolta la sottrazione della tariffa tecnica dal netto host
     (`netto_host = max(0, netto_host)`) -> `test_identita_contabile_in_ogni_valuta` ROSSO
     in tutte e 6 le valute (il totale non e' piu' la somma delle parti).
  3. `fase85.crea_link`: valuta forzata a quella del provider invece che a quella
     dell'annuncio -> `test_a_stripe_va_la_valuta_dell_host` ROSSO su USD/GBP/JPY/KRW/BHD.
  4. `fase111.calcola_rimborso`: floor sostituito da ceil sul rimborso parziale ->
     `test_il_rimborso_parziale_non_regala_una_sola_unita` e
     `test_il_rimborso_e_sempre_il_floor_e_conserva_il_pagato` ROSSI (unita' regalata).
  5. `fase131.registra_in_attesa`/`registra_maturato`: valuta forzata a "EUR" ->
     `test_il_payout_non_mescola_le_valute` ROSSO (le sei valute collassano su una riga).
     MUTANTE SOPRAVVISSUTO, poi ucciso: rompendo la SOLA `registra_maturato` il cammino
     restava VERDE, perche' con pagamento online la riga la scrive `registra_in_attesa` e
     il webhook si limita a cambiarne lo stato. `registra_maturato` non e' codice morto
     (la usano conferma immediata, su-richiesta approvata e ri-blocco dopo pagamento
     tardivo): da qui `test_entrambe_le_porte_del_payout_conservano_la_valuta`, che ora
     e' ROSSO su quel mutante.
  6. `fase99.esponente`: JPY dichiarato a 2 decimali ->
     `test_nessuna_frazione_sulle_valute_senza_decimali` ROSSO ("368.00" invece di "36800").

Stdlib pura, zero rete (Stripe/email finti), DB su file temporanei, deterministico.
"""
import datetime
import json
import os
import shutil
import tempfile
import time
import unittest
import urllib.parse
from decimal import Decimal

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

WHSEC = "whsec_profondo_valute"
COMM_BPS = 1000            # 10% marketplace, a carico host


def _dal_motore(chiave):
    """Le tariffe tecniche VERE, lette dai default di `main_casavip.py`.

    Qui c'era `PSP_BPS = 300`, e l'ironia e' che proprio QUESTO file -- quello che
    collauda le valute -- non sapeva che il 2026-08-10 la tariffa tecnica e' diventata
    DIVERSA sugli annunci fuori euro (7%% invece di 5%%, perche' Stripe deve convertire
    e si prende un 2%% in piu'). Collaudava sei valute applicandone una sola. Ora le
    cifre vengono dal motore, e l'oracolo distingue i due casi.
    """
    import io as _io
    import re as _re
    _qui = os.path.dirname(os.path.abspath(__file__))
    with _io.open(os.path.join(_qui, "main_casavip.py"), encoding="utf-8") as f:
        _src = f.read()
    _m = _re.search(chiave + r'["\']\s*,\s*["\'](\d+)["\']', _src)
    assert _m, "main_casavip.py non dichiara piu' il default %s" % chiave
    return int(_m.group(1))


PSP_BPS = _dal_motore("PAGAMENTO_BPS")              # annunci nella valuta d'incasso
PSP_BPS_ESTERA = _dal_motore("PAGAMENTO_BPS_ESTERA")   # annunci in un'altra valuta
PSP_FISSO = _dal_motore("PAGAMENTO_FISSO_CENTS")    # quota fissa, in tutti e due i casi
VALUTA_INCASSO = "EUR"     # il default di ConfigCasaVIP: il conto Stripe tiene solo euro
OSPITI = 2


def _psp_di(valuta):
    """5%% se l'annuncio e' nella valuta in cui incassiamo, 7%% se Stripe deve convertire."""
    return PSP_BPS if str(valuta).upper() == VALUTA_INCASSO else PSP_BPS_ESTERA

# (valuta ISO, cifre decimali reali). Tre famiglie di esponente: 2, 0 e 3.
VALUTE = (("EUR", 2), ("USD", 2), ("GBP", 2), ("JPY", 0), ("KRW", 0), ("BHD", 3))
# importi in UNITA' MINORI a notte: 1 e 99 sono sotto la soglia dove le percentuali
# diventano 0, 12345 e 999999 fanno divisioni sporche.
IMPORTI = (1, 99, 100, 12345, 999999)
# tassa di soggiorno per-persona-notte dichiarata dall'host, diversa per importo cosi' la
# griglia attraversa sia il ramo "con tassa" sia quello "senza".
TASSA_DI = {1: 23, 99: 7, 100: 0, 12345: 137, 999999: 0}
NOTTI = (1, 2, 7, 30)
# il percorso completo si cammina su un prezzo che NON si divide in due parti uguali
PREZZO_PERCORSO = 12345
TASSA_PERCORSO = 137

# corpi grezzi delle richieste andate a Stripe (l'ADDEBITO vero)
_CHIAMATE = []


def _fake_stripe_fetch(url, body, headers):
    """Checkout Session finta: nessuna rete, e conserva il corpo per ispezionarlo."""
    import secrets
    _CHIAMATE.append(body)
    return {"url": "https://stripe.finto/" + secrets.token_hex(4),
            "id": "cs_" + secrets.token_hex(8)}


def _params_stripe():
    """I parametri dell'ULTIMA sessione di pagamento, come li riceve Stripe."""
    if not _CHIAMATE:
        return {}
    corpo = _CHIAMATE[-1]
    if isinstance(corpo, bytes):
        corpo = corpo.decode("utf-8", "replace")
    return dict(urllib.parse.parse_qsl(str(corpo)))


def _oracolo(prezzo, notti, ospiti, tassa_pp, valuta=VALUTA_INCASSO):
    """ORACOLO INDIPENDENTE: rifa' il conto da zero dal contratto, in interi.

    Non chiama il motore e non ne importa nulla: se motore e oracolo divergono, uno dei
    due ha torto e il test lo dice. Ritorna None quando il preventivo DEVE essere
    rifiutato (la tariffa tecnica non sta dentro cio' che resta all'host).
    """
    netto = prezzo * notti                       # soggiorno di listino
    comm = netto * COMM_BPS // 10000             # nostra commissione (dedotta all'host)
    tassa = tassa_pp * notti * ospiti            # pass-through verso la citta'
    totale = netto + tassa                       # quello che l'ospite paga DAVVERO
    # tariffa tecnica sul totale addebitato: percentuale (maggiorata se Stripe deve
    # convertire) PIU' la quota fissa che Stripe prende a ogni transazione.
    costo = totale * _psp_di(valuta) // 10000 + (PSP_FISSO if totale > 0 else 0)
    if netto - comm < costo:                     # confine: mai in perdita, si rifiuta
        return None
    return {"prezzo_netto_cents": netto,
            "commissione_cents": comm,
            "prezzo_guest_cents": netto,
            "tassa_soggiorno_cents": tassa,
            "totale_cents": totale,
            "costo_pagamento_cents": costo,
            "netto_host_cents": netto - comm - costo}


class _Posta:
    """Provider email finto: registra, non spedisce."""

    def __init__(self):
        self.inviate = []

    def invia(self, dest, oggetto, html):
        self.inviate.append((dest, oggetto, html))
        return True


class _Banco(unittest.TestCase):
    """Sistema VERO + router VERO + un host che pubblica annunci in piu' valute.

    Il banco si costruisce UNA volta per classe (crea_sistema costa ~0,3 s e la griglia ne
    userebbe centinaia): i test che prenotano lavorano su FINESTRE DI DATE DISGIUNTE
    (`finestra(slot)`) cosi' nessuno consuma l'inventario di un altro.
    """

    ANNUNCI = ()          # ((slug, valuta, prezzo, tassa_pp, politica), ...)
    GIORNI_RANGE = 50     # ampiezza del calendario aperto dall'host

    @classmethod
    def setUpClass(cls):
        cls._env0 = {k: os.environ.get(k) for k in
                     ("UPLOAD_DIR", "TASSE_SOGGIORNO", "PAGA_STRUTTURA_ATTIVO",
                      "BLOCCO_GLOBALE")}
        cls.dir = tempfile.mkdtemp(prefix="prof_valute_")
        os.environ["UPLOAD_DIR"] = cls.dir + "/uploads"
        os.environ["PAGA_STRUTTURA_ATTIVO"] = "0"   # deterministico: vetrina in-struttura OFF
        os.environ.pop("BLOCCO_GLOBALE", None)
        os.environ.pop("TASSE_SOGGIORNO", None)     # la tassa la dichiara l'annuncio
        cls._fetch0 = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_stripe_fetch)

        d = cls.dir
        cls.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"V" * 32, con_registrazione_host=True,
            db_catalogo=d + "/c.db", db_inventario=d + "/i.db", db_registro_host=d + "/r.db",
            db_accettazioni=d + "/a.db", db_pendenti=d + "/p.db", db_payout=d + "/po.db",
            db_garanzia=d + "/g.db", db_finanza=d + "/f.db", db_messaggi=d + "/m.db",
            db_checkin=d + "/ck.db", db_split=d + "/sp.db", db_tassa_comunale=d + "/t.db",
            db_recensioni=d + "/rec.db", db_viral=d + "/v.db", db_domanda=d + "/dom.db",
            commissione_bps=COMM_BPS, psp_bps=PSP_BPS,
            psp_bps_valuta_estera=PSP_BPS_ESTERA, psp_fisso_cents=PSP_FISSO,
            stripe_secret_key="sk",
            stripe_webhook_secret=WHSEC, stripe_success_url="https://x/ok",
            stripe_cancel_url="https://x/ko"))
        cls.posta = _Posta()
        cls.sis.email_provider = cls.posta
        cls.r = crea_router(cls.sis, host_key="hk", admin_key="ak",
                            base_url="https://bookinvip.com")
        if getattr(cls.sis, "connect", None) is not None:
            cls.sis.connect.trasferisci = lambda *a, **k: "tr_finto"    # mai rete

        def _g(metodo, path, corpo=None, headers=None, query=None):
            return cls.r.gestisci(metodo, path, query or {},
                                  json.dumps(corpo) if corpo is not None else None,
                                  headers or {})

        s, c = _g("POST", "/api/host/registrazione", {
            "email": "host@valute.it", "password": "password1", "accetta_termini": True,
            "accetta_clausole": True, "accetta_privacy": True, "doc_sha256": doc_sha256(),
            "versione": CONTRATTO_HOST_VERSIONE})
        assert s == 201, ("registrazione host fallita: %s %s" % (s, c))
        cls.host_id = c["host_id"]
        cls.tk = {"X-Host-Token": c["token"]}
        cls.admin = {"X-Admin-Key": "ak"}

        cls.oggi = datetime.date.today()
        da = (cls.oggi + datetime.timedelta(days=1)).isoformat()
        a = (cls.oggi + datetime.timedelta(days=cls.GIORNI_RANGE)).isoformat()
        for slug, valuta, prezzo, tassa_pp, politica in cls.ANNUNCI:
            # Madrid/ES: fuso Europe/Madrid = stesso scarto UTC di Roma (il fuso
            # dell'alloggio decide i "giorni all'arrivo" della cancellazione) e nessun
            # CIN obbligatorio, che qui sarebbe rumore estraneo alle valute.
            s, p = _g("POST", "/api/host/pubblica", {
                "slug": slug, "titolo": "Casa " + slug, "citta": "Madrid", "paese": "ES",
                "descrizione": "Appartamento luminoso con terrazza e vista sui tetti.",
                "prezzo_notte_cents": prezzo, "valuta": valuta, "capacita": 6,
                "tassa_pp_notte_cents": tassa_pp, "politica_cancellazione": politica,
                "servizi": [], "immagini": []}, cls.tk)
            assert s in (200, 201), ("pubblica %s (%s) fallita: %s %s"
                                     % (slug, valuta, s, p))
            s, disp = _g("POST", "/api/host/disponibilita_range", {
                "alloggio_id": slug, "da": da, "a": a,
                "unita_totali": 1, "prezzo_netto_cents": prezzo}, cls.tk)
            assert s == 200, ("calendario %s fallito: %s %s" % (slug, s, disp))

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._fetch0
        for k, v in cls._env0.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(cls.dir, ignore_errors=True)

    # ── utilita' ────────────────────────────────────────────────────────────────
    def g(self, metodo, path, corpo=None, headers=None, query=None):
        return self.r.gestisci(metodo, path, query or {},
                               json.dumps(corpo) if corpo is not None else None,
                               headers or {})

    def finestra(self, slot, notti=1):
        """Blocco di date DISGIUNTO dagli altri: ogni test prenota nel suo (passo 3
        giorni, soggiorni al massimo di 2 notti -> le finestre non si toccano mai)."""
        ci = self.oggi + datetime.timedelta(days=4 + slot * 3)
        return ci.isoformat(), (ci + datetime.timedelta(days=notti)).isoformat()

    def quote(self, slug, ci, co, party=OSPITI, **extra):
        corpo = {"alloggio_id": slug, "check_in": ci, "check_out": co, "party": party}
        corpo.update(extra)
        return self.g("POST", "/api/concierge/quote", corpo)

    def book(self, quote_token, email="ospite@valute.it"):
        del _CHIAMATE[:]
        return self.g("POST", "/api/concierge/book",
                      {"quote_token": quote_token, "email": email, "lang": "it"})

    def paga(self, riferimento):
        """Webhook Stripe FIRMATO sul corpo grezzo (come lo manda Stripe)."""
        grezzo = json.dumps({"type": "checkout.session.completed",
                             "data": {"object": {"id": "cs_" + riferimento[:8],
                                                 "metadata": {"riferimento": riferimento}}}})
        return self.r.gestisci("POST", "/api/payments/webhook", {}, grezzo,
                               {"Stripe-Signature": firma_di_test(grezzo, WHSEC,
                                                                  int(time.time()))})

    def cammina(self, slug, slot, notti=1, party=OSPITI):
        """Preventivo -> prenotazione -> pagamento confermato. Ritorna (q, b)."""
        ci, co = self.finestra(slot, notti)
        s, q = self.quote(slug, ci, co, party)
        self.assertEqual(s, 200, "preventivo %s: %s" % (slug, q))
        s, b = self.book(q["quote_token"])
        self.assertEqual(s, 201, "prenotazione %s: %s" % (slug, b))
        s, w = self.paga(b["riferimento"])
        self.assertEqual(s, 200, "webhook %s: %s" % (slug, w))
        self.assertEqual(self.sis.pagamenti_pendenti.info(b["riferimento"])["stato"],
                         "pagato")
        return q, b


# ══════════════════════════════════════════════════════════════════════════════════
# 1) LA GRIGLIA: l'aritmetica in unita' minori, valuta per valuta, importo per importo
# ══════════════════════════════════════════════════════════════════════════════════
class TestGrigliaAritmetica(_Banco):
    """6 valute × 5 importi × 4 durate, confrontate con un oracolo scritto a parte."""

    ANNUNCI = tuple(("g-%s-%d" % (v.lower(), p), v, p, TASSA_DI[p], "flessibile")
                    for v, _e in VALUTE for p in IMPORTI)
    GIORNI_RANGE = 45

    def _casi(self):
        for valuta, esp in VALUTE:
            for prezzo in IMPORTI:
                for notti in NOTTI:
                    yield ("g-%s-%d" % (valuta.lower(), prezzo), valuta, esp,
                           prezzo, notti, TASSA_DI[prezzo])

    def test_identita_contabile_in_ogni_valuta(self):
        """totale == netto_host + commissione + tariffa tecnica + tassa. In OGNI valuta.

        E' l'invariante che tiene in piedi la contabilita': se non vale, da qualche parte
        del preventivo c'e' denaro creato o perso — e su una valuta senza decimali quel
        "da qualche parte" vale un intero yen, non un centesimo.
        """
        ci = (self.oggi + datetime.timedelta(days=3)).isoformat()
        for slug, valuta, _esp, prezzo, notti, tassa_pp in self._casi():
            atteso = _oracolo(prezzo, notti, OSPITI, tassa_pp, valuta)
            if atteso is None:
                continue                                    # ramo del rifiuto: test a parte
            with self.subTest(valuta=valuta, prezzo=prezzo, notti=notti):
                co = (self.oggi + datetime.timedelta(days=3 + notti)).isoformat()
                s, q = self.quote(slug, ci, co)
                self.assertEqual(s, 200, q)
                self.assertEqual(q["valuta"], valuta)
                somma = (q["netto_host_cents"] + q["commissione_cents"]
                         + q["costo_pagamento_cents"] + q["tassa_soggiorno_cents"])
                self.assertEqual(
                    q["totale_cents"], somma,
                    "denaro creato o perso in %s: totale %d != host %d + noi %d + "
                    "tariffa tecnica %d + tassa %d (= %d, scarto %d unita' minori)"
                    % (valuta, q["totale_cents"], q["netto_host_cents"],
                       q["commissione_cents"], q["costo_pagamento_cents"],
                       q["tassa_soggiorno_cents"], somma, somma - q["totale_cents"]))

    def test_ogni_voce_coincide_con_l_oracolo_indipendente(self):
        """Un secondo calcolo, scritto separatamente, ricalcola tutto e confronta."""
        ci = (self.oggi + datetime.timedelta(days=3)).isoformat()
        for slug, valuta, _esp, prezzo, notti, tassa_pp in self._casi():
            atteso = _oracolo(prezzo, notti, OSPITI, tassa_pp, valuta)
            if atteso is None:
                continue
            with self.subTest(valuta=valuta, prezzo=prezzo, notti=notti):
                co = (self.oggi + datetime.timedelta(days=3 + notti)).isoformat()
                s, q = self.quote(slug, ci, co)
                self.assertEqual(s, 200, q)
                self.assertEqual(q["notti"], notti)
                ottenuto = {k: q[k] for k in atteso}
                self.assertEqual(
                    ottenuto, atteso,
                    "motore e oracolo divergono su %s %d x %d notti" % (valuta, prezzo, notti))

    def test_rifiuto_onesto_quando_la_tariffa_tecnica_non_sta_dentro(self):
        """Confine: se il 3% supera cio' che resta all'host, si RIFIUTA il preventivo.

        L'alternativa (incassare lo stesso e far sparire la differenza) sarebbe una
        perdita a nostro carico su ogni prenotazione micro. Deve capitare davvero nella
        griglia, altrimenti questo test non sta guardando niente.
        """
        ci = (self.oggi + datetime.timedelta(days=3)).isoformat()
        visti = 0
        for slug, valuta, _esp, prezzo, notti, tassa_pp in self._casi():
            if _oracolo(prezzo, notti, OSPITI, tassa_pp, valuta) is not None:
                continue
            visti += 1
            with self.subTest(valuta=valuta, prezzo=prezzo, notti=notti):
                co = (self.oggi + datetime.timedelta(days=3 + notti)).isoformat()
                s, q = self.quote(slug, ci, co)
                self.assertEqual((s, q), (422, {"errore": "prezzo_non_sostenibile"}))
        self.assertGreaterEqual(visti, 6, "la griglia non attraversa mai il rifiuto: "
                                          "il confine non e' sotto osservazione")

    def test_nessun_arrotondamento_a_nostro_carico(self):
        """Le percentuali arrotondano SEMPRE per difetto sulle nostre voci, mai per
        eccesso a carico dell'host; e la somma delle parti resta il soggiorno esatto."""
        ci = (self.oggi + datetime.timedelta(days=3)).isoformat()
        for slug, valuta, _esp, prezzo, notti, tassa_pp in self._casi():
            atteso = _oracolo(prezzo, notti, OSPITI, tassa_pp, valuta)
            if atteso is None:
                continue
            with self.subTest(valuta=valuta, prezzo=prezzo, notti=notti):
                co = (self.oggi + datetime.timedelta(days=3 + notti)).isoformat()
                s, q = self.quote(slug, ci, co)
                self.assertEqual(s, 200, q)
                netto, comm = q["prezzo_netto_cents"], q["commissione_cents"]
                costo, tot = q["costo_pagamento_cents"], q["totale_cents"]
                self.assertEqual(comm, netto * COMM_BPS // 10000,
                                 "commissione non e' il floor esatto del 10%%")
                _psp = _psp_di(valuta)
                self.assertEqual(costo, tot * _psp // 10000 + PSP_FISSO,
                                 "tariffa tecnica non e' il floor esatto di %d bps "
                                 "+ %d cent (valuta %s)" % (_psp, PSP_FISSO, valuta))
                self.assertLessEqual(comm * 10000, netto * COMM_BPS,
                                     "commissione arrotondata per ECCESSO: unita' presa "
                                     "all'host che non ci spetta")
                self.assertLessEqual((costo - PSP_FISSO) * 10000, tot * _psp,
                                     "tariffa tecnica arrotondata per ECCESSO")
                self.assertEqual(q["netto_host_cents"] + comm + costo, netto,
                                 "il soggiorno non si ripartisce esattamente fra host, "
                                 "noi e la carta")
                for chiave in ("prezzo_netto_cents", "commissione_cents",
                               "prezzo_guest_cents", "netto_host_cents",
                               "costo_pagamento_cents", "tassa_soggiorno_cents",
                               "totale_cents"):
                    self.assertGreaterEqual(q[chiave], 0, "%s negativo" % chiave)

    def test_nessuna_frazione_sulle_valute_senza_decimali(self):
        """Su JPY/KRW l'unita' minima E' l'unita': nessun campo puo' essere frazionario e
        nessun importo scritto per una persona puo' avere decimali.

        Su BHD (3 decimali) il controllo e' l'opposto: i decimali devono essere TRE. Il
        confronto fra i due lati prova che il sistema DISTINGUE le valute invece di
        applicare a tutte la stessa regola dei centesimi."""
        from fase83_server import _importo
        ci = (self.oggi + datetime.timedelta(days=3)).isoformat()
        co = (self.oggi + datetime.timedelta(days=5)).isoformat()
        for valuta, esp in VALUTE:
            for prezzo in IMPORTI:
                atteso = _oracolo(prezzo, 2, OSPITI, TASSA_DI[prezzo])
                if atteso is None:
                    continue
                with self.subTest(valuta=valuta, prezzo=prezzo):
                    s, q = self.quote("g-%s-%d" % (valuta.lower(), prezzo), ci, co)
                    self.assertEqual(s, 200, q)
                    for chiave, valore in q.items():
                        if chiave.endswith("_cents"):
                            self.assertIsInstance(valore, int,
                                                  "%s non e' intero: %r" % (chiave, valore))
                            self.assertNotIsInstance(valore, bool, chiave)
                    scritto = _importo(q["totale_cents"], valuta)
                    if esp == 0:
                        self.assertEqual(scritto, str(q["totale_cents"]),
                                         "%s non ha decimali, ma l'importo e' scritto "
                                         "'%s'" % (valuta, scritto))
                    else:
                        self.assertRegex(scritto, r"^\d+\.\d{%d}$" % esp,
                                         "%s ha %d decimali, ma l'importo e' scritto "
                                         "'%s'" % (valuta, esp, scritto))
                        intero, frazione = scritto.split(".")
                        self.assertEqual(int(intero) * 10 ** esp + int(frazione),
                                         q["totale_cents"],
                                         "l'importo scritto non vale l'importo addebitato")


# ══════════════════════════════════════════════════════════════════════════════════
# 2) IL PERCORSO: preventivo -> prenotazione -> pagamento -> rimborso -> payout
# ══════════════════════════════════════════════════════════════════════════════════
class TestPercorsoDeiSoldi(_Banco):
    """Lo stesso cammino di un ospite vero, ripetuto in tutte e sei le valute."""

    PREZZO = PREZZO_PERCORSO
    TASSA = TASSA_PERCORSO
    ANNUNCI = (tuple(("p-%s" % v.lower(), v, PREZZO_PERCORSO, TASSA_PERCORSO,
                      "flessibile") for v, _e in VALUTE)
               + tuple(("m-%s" % v.lower(), v, PREZZO_PERCORSO, TASSA_PERCORSO,
                        "moderata") for v, _e in VALUTE))
    GIORNI_RANGE = 120

    def test_a_stripe_va_la_valuta_dell_host_e_il_totale_esatto(self):
        """Like-for-like: l'addebito e' nella valuta dell'annuncio, mai convertito, e
        l'importo e' quello del preventivo senza un'unita' di scarto."""
        for i, (valuta, _esp) in enumerate(VALUTE):
            with self.subTest(valuta=valuta):
                ci, co = self.finestra(i, 2)
                s, q = self.quote("p-" + valuta.lower(), ci, co)
                self.assertEqual(s, 200, q)
                s, b = self.book(q["quote_token"])
                self.assertEqual(s, 201, b)
                p = _params_stripe()
                self.assertTrue(p, "nessuna chiamata a Stripe: l'anello non e' percorso")
                self.assertEqual(p["line_items[0][price_data][currency]"], valuta.lower(),
                                 "l'ospite verrebbe addebitato in un'altra valuta")
                self.assertEqual(p["line_items[0][price_data][unit_amount]"],
                                 str(q["totale_cents"]),
                                 "mostrato %d %s, addebitato %s: errore di scala"
                                 % (q["totale_cents"], valuta,
                                    p["line_items[0][price_data][unit_amount]"]))
                self.assertEqual(b["valuta"], valuta)
                self.assertEqual(b["totale_cents"], q["totale_cents"])
                self.assertEqual(b["netto_host_cents"], q["netto_host_cents"])

    def test_il_voucher_firmato_porta_la_valuta_dell_host(self):
        """La valuta viaggia DENTRO il gettone firmato: la cancellazione e le email non
        possono ricavarla da altro (ne' inventarla in EUR)."""
        for i, (valuta, _esp) in enumerate(VALUTE):
            with self.subTest(valuta=valuta):
                ci, co = self.finestra(6 + i, 2)
                s, q = self.quote("p-" + valuta.lower(), ci, co)
                self.assertEqual(s, 200, q)
                s, b = self.book(q["quote_token"])
                self.assertEqual(s, 201, b)
                v = self.sis.firma.decodifica(b["voucher_token"])
                self.assertEqual(v["tipo"], "voucher")
                self.assertEqual(v["valuta"], valuta)
                self.assertEqual(v["prezzo_guest_cents"], q["prezzo_guest_cents"])
                self.assertEqual(v["tassa_soggiorno_cents"], q["tassa_soggiorno_cents"])

    def test_dopo_il_webhook_giornale_e_payout_restano_nella_valuta_dell_host(self):
        """Il pagamento confermato scrive nel giornale immutabile e nel payout: entrambi
        devono portare la valuta dell'annuncio e gli importi esatti del preventivo."""
        for i, (valuta, _esp) in enumerate(VALUTE):
            with self.subTest(valuta=valuta):
                q, b = self.cammina("p-" + valuta.lower(), 12 + i, notti=2)
                rif = b["riferimento"]
                mov = self.sis.finanza.movimenti(rif)
                per_tipo = {m["tipo"]: m for m in mov}
                self.assertIn("incasso", per_tipo, "nessun incasso a giornale: %r" % (mov,))
                self.assertEqual(per_tipo["incasso"]["valuta"], valuta)
                self.assertEqual(per_tipo["incasso"]["importo_cents"], q["totale_cents"])
                self.assertEqual(per_tipo["commissione"]["valuta"], valuta)
                self.assertEqual(per_tipo["commissione"]["importo_cents"],
                                 q["commissione_cents"] + q["costo_pagamento_cents"])
                self.assertEqual(per_tipo["tassa_incassata"]["valuta"], valuta)
                self.assertEqual(per_tipo["tassa_incassata"]["importo_cents"],
                                 q["tassa_soggiorno_cents"])
                # e l'escrow tiene ESATTAMENTE il netto host, nella stessa valuta
                st = self.sis.garanzia.stato(rif)
                self.assertEqual(st["stato"], "in_garanzia")
                self.assertEqual(st["importo_host_cents"], q["netto_host_cents"])

    def test_il_payout_non_mescola_le_valute(self):
        """Lo STESSO host incassa in sei valute: il riepilogo deve tenerle separate.

        Sommarle darebbe un numero senza significato (¥ + € + BHD) e un bonifico sbagliato.
        """
        # si misura la VARIAZIONE: il banco e' condiviso dalla classe, e un totale
        # assoluto dipenderebbe da quali altri test hanno gia' prenotato.
        prima = {v: self.sis.payout.da_pagare(self.host_id, v) for v, _e in VALUTE}
        attesi = {}
        for i, (valuta, _esp) in enumerate(VALUTE):
            q, _b = self.cammina("p-" + valuta.lower(), 18 + i, notti=1)
            attesi[valuta] = q["netto_host_cents"]
        riepilogo = self.sis.payout.riepilogo(self.host_id)
        for valuta, netto in attesi.items():
            with self.subTest(valuta=valuta):
                self.assertIn(valuta, riepilogo,
                              "la valuta %s non esiste nel payout: %r" % (valuta, riepilogo))
                cresciuto = self.sis.payout.da_pagare(self.host_id, valuta) - prima[valuta]
                self.assertEqual(cresciuto, netto,
                                 "in %s l'host deve maturare %d unita' minori, ne ha "
                                 "maturate %d: %r" % (valuta, netto, cresciuto, riepilogo))
        self.assertEqual(sorted(riepilogo), sorted(attesi),
                         "il payout ha collassato le valute: %r" % (riepilogo,))

    def test_il_rimborso_totale_rende_tutto_nella_valuta_dell_host(self):
        """Cancellazione entro il ripensamento: torna il soggiorno E la tassa, al minimo
        indivisibile, e l'host non incassa piu' nulla."""
        for i, (valuta, _esp) in enumerate(VALUTE):
            with self.subTest(valuta=valuta):
                q, b = self.cammina("p-" + valuta.lower(), 24 + i, notti=2)
                s, c = self.g("POST", "/api/concierge/cancella",
                              {"voucher_token": b["voucher_token"]})
                self.assertEqual(s, 200, c)
                self.assertEqual(c["stato"], "cancellata")
                self.assertIs(c["ripensamento"], True)
                self.assertEqual(c["rimborso_soggiorno_cents"], q["prezzo_guest_cents"])
                self.assertEqual(c["tassa_rimborsata_cents"], q["tassa_soggiorno_cents"])
                self.assertEqual(c["rimborso_cents"], q["totale_cents"])
                self.assertEqual(c["trattenuto_cents"], 0)
                self.assertEqual(self.sis.garanzia.stato(b["riferimento"])["stato"],
                                 "annullato")
                self.assertEqual(self.sis.payout.stato_di(b["riferimento"]), "trattenuto")

    def test_il_rimborso_parziale_non_regala_una_sola_unita(self):
        """Politica moderata a 2 giorni dall'arrivo = 50% del soggiorno.

        12345 unita' minori non si dividono in due parti uguali: la meta' esatta e'
        6172,5. L'unita' indivisibile deve restare a NOI, mai andare in regalo: rimborso
        6172 e trattenuto 6173. La tassa di soggiorno invece torna SEMPRE per intero
        (niente soggiorno = niente tassa dovuta alla citta').
        """
        for i, (valuta, _esp) in enumerate(VALUTE):
            with self.subTest(valuta=valuta):
                ci = (self.oggi + datetime.timedelta(days=2)).isoformat()
                co = (self.oggi + datetime.timedelta(days=3)).isoformat()
                s, q = self.quote("m-" + valuta.lower(), ci, co)
                self.assertEqual(s, 200, q)
                self.assertEqual(q["prezzo_guest_cents"], self.PREZZO)   # 1 notte
                s, b = self.book(q["quote_token"], email="tardi%d@valute.it" % i)
                self.assertEqual(s, 201, b)
                self.assertEqual(self.paga(b["riferimento"])[0], 200)
                s, c = self.g("POST", "/api/concierge/cancella",
                              {"voucher_token": b["voucher_token"]})
                self.assertEqual(s, 200, c)
                # arrivo fra 2 giorni; il fuso dell'alloggio puo' far leggere "1" se in
                # quel posto e' gia' domani. Entrambi cadono nello scaglione 50% di
                # 'moderata' e nessuno dei due apre il ripensamento (che vuole >= 3).
                self.assertIn(c["giorni_all_arrivo"], (1, 2), c)
                self.assertIs(c["ripensamento"], False)
                self.assertEqual(c["politica"], "moderata")
                meta_bassa = self.PREZZO * 5000 // 10000            # 6172
                self.assertEqual(c["rimborso_soggiorno_cents"], meta_bassa)
                self.assertEqual(c["trattenuto_cents"], self.PREZZO - meta_bassa)  # 6173
                self.assertEqual(c["rimborso_soggiorno_cents"] + c["trattenuto_cents"],
                                 self.PREZZO,
                                 "rimborso + trattenuto non fa il pagato: unita' creata "
                                 "o persa in %s" % valuta)
                self.assertEqual(c["tassa_rimborsata_cents"], q["tassa_soggiorno_cents"])
                self.assertEqual(c["rimborso_cents"],
                                 meta_bassa + q["tassa_soggiorno_cents"])
                self.assertLessEqual(c["rimborso_soggiorno_cents"] * 10000,
                                     self.PREZZO * 5000,
                                     "rimborsata piu' della meta': un'unita' regalata "
                                     "a nostro carico in %s" % valuta)
        # NB: la stessa cifra in sei valute significa valori reali diversissimi
        # (12345 KRW ~ 8 EUR, 12345 BHD ~ 30000 EUR): l'aritmetica in unita' minori
        # non deve accorgersene, ed e' proprio questo il punto.

    def test_ogni_valuta_ha_il_suo_carrello_separato(self):
        """Due valute, due prenotazioni, due escrow: nessun importo migra fra le due."""
        q_eur, b_eur = self.cammina("p-eur", 30, notti=1)
        q_jpy, b_jpy = self.cammina("p-jpy", 31, notti=1)
        self.assertEqual(q_eur["totale_cents"], q_jpy["totale_cents"],
                         "il banco vuole due totali NUMERICAMENTE uguali per provare che "
                         "non si confondono per valore, ma solo per valuta")
        st_eur = self.sis.garanzia.stato(b_eur["riferimento"])
        st_jpy = self.sis.garanzia.stato(b_jpy["riferimento"])
        self.assertEqual(st_eur["importo_host_cents"], q_eur["netto_host_cents"])
        self.assertEqual(st_jpy["importo_host_cents"], q_jpy["netto_host_cents"])
        rec_eur = self.sis.pagamenti_pendenti.info(b_eur["riferimento"])
        rec_jpy = self.sis.pagamenti_pendenti.info(b_jpy["riferimento"])
        self.assertEqual(json.loads(rec_eur["corpo_json"])["valuta"], "EUR")
        self.assertEqual(json.loads(rec_jpy["corpo_json"])["valuta"], "JPY")


# ══════════════════════════════════════════════════════════════════════════════════
# 3) LA CONVERSIONE "≈ NELLA TUA MONETA": solo display, e con la SCALA giusta
# ══════════════════════════════════════════════════════════════════════════════════
class TestConversioneSoloDisplay(_Banco):
    """La stima nella valuta dell'ospite non deve toccare un'unita' dell'addebito."""

    ANNUNCI = (("d-jpy", "JPY", 18000, 0, "flessibile"),
               ("d-eur", "EUR", 20600, 0, "flessibile"))
    GIORNI_RANGE = 40
    # tassi mid inventati ma coerenti fra loro (nessuna rete): 1 EUR = 160 JPY
    TASSI = {("JPY", "EUR"): Decimal("0.00625"), ("EUR", "JPY"): Decimal("160"),
             ("EUR", "USD"): Decimal("1.1"), ("EUR", "BHD"): Decimal("0.41")}

    def setUp(self):
        self._tasso0 = self.sis.concierge._tasso
        self.sis.concierge._tasso = lambda da, a: self.TASSI.get((da, a))
        self.addCleanup(setattr, self.sis.concierge, "_tasso", self._tasso0)

    def test_la_stima_non_cambia_di_un_unita_cio_che_si_addebita(self):
        """Stesso preventivo con e senza `valuta_ospite`: totale identico, valuta identica,
        e a Stripe arriva lo stesso numero nella stessa moneta."""
        ci, co = self.finestra(0, 2)
        s, senza = self.quote("d-jpy", ci, co)
        self.assertEqual(s, 200, senza)
        s, con = self.quote("d-jpy", ci, co, valuta_ospite="EUR")
        self.assertEqual(s, 200, con)
        for chiave in ("valuta", "totale_cents", "prezzo_guest_cents",
                       "netto_host_cents", "commissione_cents", "costo_pagamento_cents"):
            self.assertEqual(con[chiave], senza[chiave],
                             "la stima in EUR ha alterato '%s' dell'addebito" % chiave)
        self.assertEqual(con["valuta"], "JPY")
        self.assertEqual(con["valuta_indicativa"], "EUR")
        s, b = self.book(con["quote_token"])
        self.assertEqual(s, 201, b)
        p = _params_stripe()
        self.assertEqual(p["line_items[0][price_data][currency]"], "jpy",
                         "la stima di cortesia e' diventata l'addebito")
        self.assertEqual(p["line_items[0][price_data][unit_amount]"],
                         str(con["totale_cents"]))
        self.assertNotEqual(p["line_items[0][price_data][unit_amount]"],
                            str(con["totale_indicativo_cents"]),
                            "a Stripe e' finito l'importo INDICATIVO")

    def test_la_stima_nella_moneta_dell_ospite_ha_la_scala_giusta(self):
        """La stima e' in unita' minori della valuta DI DESTINAZIONE.

        ¥36.000 valgono 225,00 EUR, cioe' 22500 centesimi — non 225 (2,25 EUR). Il numero
        che il server manda finisce dentro `BV.money(cents, valuta)` nel browser, che lo
        divide per 10^esponente della valuta di ARRIVO: se il server non cambia scala, la
        pagina mostra un prezzo sbagliato di cento volte. E' il difetto di scala del
        2026-07-21, sull'unica riga della vetrina che parla la moneta dell'ospite.
        """
        ci, co = self.finestra(3, 2)
        s, q = self.quote("d-jpy", ci, co, valuta_ospite="EUR")
        self.assertEqual(s, 200, q)
        self.assertEqual(q["totale_cents"], 36000)              # 2 notti a ¥18.000
        self.assertEqual(q["valuta_indicativa"], "EUR")
        self.assertEqual(
            q["totale_indicativo_cents"], 22500,
            "¥36.000 al tasso 0,00625 sono 225,00 EUR = 22500 centesimi; il server ne "
            "manda %d, che il browser mostrerebbe come %s EUR"
            % (q["totale_indicativo_cents"],
               Decimal(q["totale_indicativo_cents"]) / 100))
        # e la direzione opposta, sulla stessa rotta: 412,00 EUR al tasso 160 sono
        # ¥65.920 (yen INTERI), non ¥6.592.000.
        s, q2 = self.quote("d-eur", ci, co, valuta_ospite="JPY")
        self.assertEqual(s, 200, q2)
        self.assertEqual(q2["totale_cents"], 41200)             # 2 notti a 206,00 EUR
        self.assertEqual(q2["valuta_indicativa"], "JPY")
        self.assertEqual(
            q2["totale_indicativo_cents"], 65920,
            "412,00 EUR al tasso 160 sono 65.920 yen interi; il server ne manda %d"
            % q2["totale_indicativo_cents"])

    def test_la_scala_regge_in_tutte_e_tre_le_famiglie_di_esponente(self):
        """Le tre direzioni possibili: 0 -> 2, 2 -> 0, 2 -> 3, piu' il caso 2 -> 2 che
        NON deve cambiare (avere 'aggiustato' lo yen rompendo il dollaro sarebbe peggio)."""
        conv = self.sis.concierge._converti_indicativo
        self.assertEqual(conv("JPY", "EUR", 36800), 23000,
                         "0 decimali -> 2 decimali: ¥36.800 = 230,00 EUR")
        self.assertEqual(conv("EUR", "JPY", 41200), 65920,
                         "2 decimali -> 0 decimali: 412,00 EUR = ¥65.920")
        self.assertEqual(conv("EUR", "BHD", 10000), 41000,
                         "2 decimali -> 3 decimali: 100,00 EUR = 41,000 BHD")
        self.assertEqual(conv("EUR", "USD", 10000), 11000,
                         "2 decimali -> 2 decimali: la scala non cambia")

    def test_senza_tasso_nessun_numero_inventato(self):
        """Se il cambio non e' disponibile, la riga "≈" sparisce: meglio niente che una
        cifra sbagliata accanto a un prezzo vero."""
        conv = self.sis.concierge._converti_indicativo
        self.assertEqual(conv("JPY", "KRW", 36800), 0, "tasso ignoto -> stima 0")
        self.assertEqual(conv("JPY", "JPY", 36800), 0, "stessa valuta -> nessuna stima")
        ci, co = self.finestra(6, 1)
        s, q = self.quote("d-jpy", ci, co, valuta_ospite="KRW")
        self.assertEqual(s, 200, q)
        self.assertEqual(q["totale_indicativo_cents"], 0)
        self.assertEqual(q["valuta_indicativa"], "")
        self.assertEqual(q["totale_cents"], 18000)      # l'addebito non si e' mosso


# ══════════════════════════════════════════════════════════════════════════════════
# 4) LE FUNZIONI PURE: gli arrotondamenti, unita' minore per unita' minore
# ══════════════════════════════════════════════════════════════════════════════════
class TestArrotondamentiPuri(unittest.TestCase):
    """Senza server: la matematica del rimborso e del denaro tipizzato, sulla griglia."""

    def test_il_rimborso_e_sempre_il_floor_e_conserva_il_pagato(self):
        """Su ogni importo della griglia e ogni scaglione: rimborso + trattenuto ==
        pagato, e il rimborso non supera MAI la frazione dovuta (nessuna unita' regalata)."""
        from fase111_cancellazione import calcola_rimborso
        for pagato in IMPORTI:
            for politica, giorni, bps in (("flessibile", 5, 10000),
                                          ("flessibile", 0, 5000),
                                          ("moderata", 2, 5000),
                                          ("moderata", 0, 0),
                                          ("rigida", 10, 5000),
                                          ("non_rimborsabile", 99, 0)):
                with self.subTest(pagato=pagato, politica=politica, giorni=giorni):
                    r = calcola_rimborso(pagato, giorni, politica=politica)
                    self.assertEqual(r["bps"], bps)
                    self.assertEqual(r["rimborso_cents"], pagato * bps // 10000,
                                     "il rimborso non e' il floor esatto")
                    self.assertEqual(r["rimborso_cents"] + r["trattenuto_cents"], pagato,
                                     "unita' creata o persa nella cancellazione")
                    self.assertLessEqual(r["rimborso_cents"] * 10000, pagato * bps,
                                         "rimborsato piu' del dovuto: regalo a nostro "
                                         "carico")
                    self.assertGreaterEqual(r["rimborso_cents"], 0)
                    self.assertGreaterEqual(r["trattenuto_cents"], 0)

    def test_lo_stesso_numero_in_valute_diverse_non_e_lo_stesso_denaro(self):
        """1 unita' minore vale 0,01 EUR, 1 JPY intero e 0,001 BHD: chi somma o converte
        senza guardare l'esponente sbaglia di 10, 100 o 1000 volte."""
        from fase99_multicurrency import Denaro, esponente
        self.assertEqual([esponente(v) for v, _e in VALUTE], [e for _v, e in VALUTE])
        self.assertEqual(Denaro(12345, "EUR").formatta(), "123.45 EUR")
        self.assertEqual(Denaro(12345, "JPY").formatta(), "12345 JPY")
        self.assertEqual(Denaro(12345, "KRW").formatta(), "12345 KRW")
        self.assertEqual(Denaro(12345, "BHD").formatta(), "12.345 BHD")
        self.assertEqual(Denaro(12345, "JPY").maggiore(), Decimal(12345))
        self.assertEqual(Denaro(12345, "EUR").maggiore(), Decimal("123.45"))
        self.assertEqual(Denaro(12345, "BHD").maggiore(), Decimal("12.345"))

    def test_entrambe_le_porte_del_payout_conservano_la_valuta(self):
        """Nel payout si entra da DUE porte: `registra_in_attesa` (pagamento online da
        confermare) e `registra_maturato` (conferma immediata, su-richiesta approvata,
        ri-blocco dopo un pagamento tardivo). Il cammino d'insieme percorre solo la prima,
        quindi una valuta cablata nella seconda passerebbe inosservata: qui si guardano
        tutte e due, e si controlla che il passaggio a 'maturato' non riscriva la valuta.
        """
        from fase131_payout_dashboard import crea_payout_dashboard
        pd = crea_payout_dashboard(":memory:")
        pd.inizializza_schema()
        for i, (valuta, _esp) in enumerate(VALUTE):
            self.assertTrue(pd.registra_maturato("m%d" % i, "h1", 1000 + i, valuta))
            self.assertTrue(pd.registra_in_attesa("a%d" % i, "h1", 2000 + i, valuta))
        riepilogo = pd.riepilogo("h1")
        self.assertEqual(sorted(riepilogo), sorted(v for v, _e in VALUTE),
                         "le valute si sono fuse in una sola: %r" % (riepilogo,))
        for i, (valuta, _esp) in enumerate(VALUTE):
            with self.subTest(valuta=valuta):
                self.assertEqual(riepilogo[valuta],
                                 {"maturato": 1000 + i, "in_attesa": 2000 + i})
                self.assertEqual(pd.da_pagare("h1", valuta), 1000 + i,
                                 "il pendente non ancora pagato non e' 'da pagare'")
                self.assertTrue(pd.aggiorna_stato("a%d" % i, "maturato"))
                self.assertEqual(pd.info("a%d" % i)["valuta"], valuta,
                                 "la conferma del pagamento ha riscritto la valuta")
                self.assertEqual(pd.da_pagare("h1", valuta), 3000 + 2 * i)

    def test_la_ripartizione_like_for_like_resta_nella_valuta_di_partenza(self):
        """`ripartisci_pagamento` non converte nulla: ogni voce esce nella valuta d'ingresso
        e la somma delle parti e' esatta, in tutte e sei le valute."""
        from fase99_multicurrency import Denaro, ripartisci_pagamento
        for valuta, _esp in VALUTE:
            for importo in IMPORTI:
                with self.subTest(valuta=valuta, importo=importo):
                    r = ripartisci_pagamento(Denaro(importo, valuta))
                    for voce in r.values():
                        self.assertEqual(voce.valuta, valuta,
                                         "una voce e' uscita in un'altra valuta")
                        self.assertIsInstance(voce.minori, int)
                    self.assertEqual(r["nostra_commissione"].minori,
                                     r["host_fee"].minori + r["guest_fee"].minori)
                    self.assertEqual(r["totale_ospite"].minori - r["netto_host"].minori,
                                     r["nostra_commissione"].minori,
                                     "il denaro non si conserva nella ripartizione")


if __name__ == "__main__":
    unittest.main(verbosity=2)
