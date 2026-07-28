# -*- coding: utf-8 -*-
"""STATEFUL PROPERTY-BASED TESTING sul ROUTER VERO (Hypothesis RuleBasedStateMachine).

Invece di sequenze scritte a mano (test_sequenze_avverse fissa le 12 note), qui Hypothesis
GENERA sequenze casuali di chiamate API — pubblica, apri/chiudi date, preventivo, prenota,
webhook (anche DOPPIO e in RITARDO su cancellata/scaduta), cancella ospite, rimborso admin,
controversia, candidatura partner — e dopo OGNI passo verifica gli INVARIANTI:

  I1  zero double-booking: occupate<=totali SEMPRE; #prenotazioni 'pagato' che coprono una
      notte <= unita' totali di quella notte; pagato-attivo -> notte occupata (mai la coppia
      "soldi incassati + stanza libera").
  I2  conservazione denaro AL CENTESIMO (interi, mai float):
      totale == netto_host + commissione + costo_carta + tassa - sconto  (quote E book);
      a giornale: al massimo UNA riga 'incasso' per prenotazione, di importo == totale ospite,
      e SOLO se la prenotazione e' stata davvero vista 'pagato'; catena hash integra.
  I3  nessun PIN check-in / smart-pass esposto sulla pagina voucher PRIMA del pagamento
      (controllo positivo incluso: a pagamento avvenuto il PIN DEVE comparire).
  I4  nessun importo negativo, in nessuna risposta (ogni campo *_cents) ne' a giornale.
  I5  nessuna risposta 5xx, mai (il router isola le eccezioni: 500 = bug).

Vista ROSSA (regola aurea, provata il 2026-07-27 e ripristinata):
  - whitelist di stato in _conferma_pagamento neutralizzata ('if stato not in (...)' -> if False)
    => sequenza book->cancella->webhook TARDIVO produce un 'incasso' a giornale su prenotazione
    mai pagata: I2 FALLISCE (pilota A e macchina).
  - gate stato-pagamento del voucher forzato (_pagato = True in pagina_voucher_html)
    => il PIN check-in compare prima del pagamento: I3 FALLISCE (pilota B e macchina).

Stripe/email FINTI come in test_sequenze_avverse/test_quote_coerenza (nessuna rete);
DB su file temporanei; deadline=None + max_examples calibrato per stare sotto ~60s.
"""
import datetime
import json
import shutil
import sqlite3
import tempfile
import time
import unittest

from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import (Bundle, RuleBasedStateMachine, consumes, invariant,
                                 multiple, rule)

import fase85_pagamenti_stripe as _stripe
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import crea_router, pagina_voucher_html, sweep_hold_una_passata
from fase87_stripe_webhook import firma_di_test
from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256

WH = "whsec_stateful"
_BASE = datetime.date.today() + datetime.timedelta(days=30)   # finestra futura, mai "oggi"
_FINESTRA = 14                                                # notti aperte per annuncio


def _giorno(i):
    return (_BASE + datetime.timedelta(days=i)).isoformat()


def _fake_fetch(url, body, headers):
    import secrets
    return {"url": "https://stripe.finto/" + secrets.token_hex(4),
            "id": "cs_" + secrets.token_hex(8)}


class _EmailStub:
    def __init__(self):
        self.inviate = []

    def invia(self, dest, oggetto, html):
        self.inviate.append((dest, oggetto, html))
        return True


class MacchinaBookinVIP(RuleBasedStateMachine):
    """Pilota il router VERO con mosse casuali; il MODELLO tiene solo cio' che serve a
    giudicare (prenotazioni conosciute + se sono mai state viste 'pagato')."""

    sequenze_esplorate = 0        # istanze macchina (mondi) create
    passi_eseguiti = 0            # regole eseguite in totale

    annunci = Bundle("annunci")
    preventivi = Bundle("preventivi")
    prenotazioni = Bundle("prenotazioni")

    def __init__(self):
        super().__init__()
        type(self).sequenze_esplorate += 1
        # si preleva dal __dict__ della classe: l'accesso per attributo srotola lo
        # @staticmethod in funzione nuda e il ripristino avrebbe rimesso un metodo
        # d'ISTANZA al suo posto (ripristino FINTO, latente finche' nessuno lo chiama).
        self._orig_fetch = _stripe.ProviderStripe.__dict__["_fetch_reale"]
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fake_fetch)
        d = self.d = tempfile.mkdtemp(prefix="stateful_api_")
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=f"{d}/c.db", db_inventario=f"{d}/i.db", db_registro_host=f"{d}/r.db",
            db_accettazioni=f"{d}/a.db", db_pendenti=f"{d}/p.db", db_payout=f"{d}/po.db",
            db_garanzia=f"{d}/g.db", db_finanza=f"{d}/f.db", db_partner=f"{d}/pa.db",
            db_tassa_comunale=f"{d}/t.db",
            commissione_bps=1000, psp_bps=300, stripe_secret_key="sk",
            stripe_webhook_secret=WH, stripe_success_url="https://x/ok",
            stripe_cancel_url="https://x/ko"))
        self.sis.email_provider = _EmailStub()          # mai rete, mai SMTP
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        self.sis.connect.trasferisci = lambda *a, **k: "tr_finto"
        s, c = self._g("POST", "/api/host/registrazione",
                       {"email": "host@stateful.it", "password": "password1",
                        "accetta_termini": True, "accetta_clausole": True,
                        "accetta_privacy": True, "doc_sha256": doc_sha256(),
                        "versione": CONTRATTO_HOST_VERSIONE})
        assert s == 201, "setup host: %r" % (c,)
        self.tok = {"X-Host-Token": c["token"]}
        self.host_id = c["host_id"]
        self._n_annunci = 0
        self._slugs = []
        self._pren = {}               # rif -> {vt, slug, ci, co, totale, visto_pagato}
        self._n_partner = 0
        self._partner_attesi = 0

    def teardown(self):
        _stripe.ProviderStripe._fetch_reale = self._orig_fetch
        shutil.rmtree(self.d, ignore_errors=True)

    # ── infrastruttura: ogni chiamata passa da qui -> I5 + I4 sulle risposte ────────
    def _controlla_risposta(self, stt, out, dove):
        assert stt < 500, "I5 VIOLATO (5xx): %s -> %d %r" % (dove, stt, out)
        self._non_negativi(out, dove)

    def _non_negativi(self, obj, dove):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if (isinstance(k, str) and k.endswith("_cents")
                        and isinstance(v, int) and not isinstance(v, bool)):
                    assert v >= 0, "I4 VIOLATO: %s=%d negativo in %s" % (k, v, dove)
                self._non_negativi(v, dove)
        elif isinstance(obj, list):
            for v in obj:
                self._non_negativi(v, dove)

    def _g(self, m, p, b=None, h=None):
        stt, out = self.r.gestisci(m, p, {}, json.dumps(b) if b is not None else None,
                                   h or {})
        self._controlla_risposta(stt, out, "%s %s" % (m, p))
        return stt, out

    def _raw(self, m, p, raw, h):
        stt, out = self.r.gestisci(m, p, {}, raw, h or {})
        self._controlla_risposta(stt, out, "%s %s" % (m, p))
        return stt, out

    def _passo(self):
        type(self).passi_eseguiti += 1

    def _stato(self, rif):
        rec = self.sis.pagamenti_pendenti.info(rif)
        return rec.get("stato") if rec else None

    # ── REGOLE (le mosse che Hypothesis combina a caso) ─────────────────────────────
    @rule(target=annunci,
          prezzo=st.sampled_from([700, 4900, 12000, 55000, 240000]),
          tassa=st.sampled_from([0, 150, 350]),
          politica=st.sampled_from(["flessibile", "moderata", "rigida",
                                    "non_rimborsabile"]),
          unita=st.integers(min_value=1, max_value=2))
    def pubblica_annuncio(self, prezzo, tassa, politica, unita):
        self._passo()
        self._n_annunci += 1
        slug = "casa%d" % self._n_annunci
        s, o = self._g("POST", "/api/host/pubblica",
                       {"slug": slug, "titolo": "Casa %d" % self._n_annunci,
                        "citta": "Roma", "prezzo_notte_cents": prezzo, "capacita": 4,
                        "politica_cancellazione": politica,
                        "tassa_pp_notte_cents": tassa}, self.tok)
        assert s == 201, "pubblica: %d %r" % (s, o)
        s, o = self._g("POST", "/api/host/disponibilita_range",
                       {"alloggio_id": slug, "da": _giorno(0), "a": _giorno(_FINESTRA),
                        "unita_totali": unita, "prezzo_netto_cents": prezzo}, self.tok)
        assert s == 200, "disponibilita: %d %r" % (s, o)
        self._slugs.append(slug)
        return slug

    @rule(slug=annunci, off=st.integers(min_value=0, max_value=10),
          giorni=st.integers(min_value=1, max_value=4),
          unita=st.integers(min_value=0, max_value=2),          # 0 = chiudi le date
          prezzo=st.sampled_from([700, 12000, 99000]))
    def apri_chiudi_date(self, slug, off, giorni, unita, prezzo):
        self._passo()
        s, o = self._g("POST", "/api/host/disponibilita_range",
                       {"alloggio_id": slug, "da": _giorno(off),
                        "a": _giorno(off + giorni), "unita_totali": unita,
                        "prezzo_netto_cents": prezzo}, self.tok)
        assert s == 200, "apri/chiudi: %d %r" % (s, o)

    @rule(target=preventivi, slug=annunci,
          off=st.integers(min_value=0, max_value=11),
          notti=st.integers(min_value=1, max_value=3),
          party=st.integers(min_value=1, max_value=5))
    def preventivo(self, slug, off, notti, party):
        self._passo()
        ci, co = _giorno(off), _giorno(off + notti)
        s, q = self._g("POST", "/api/concierge/quote",
                       {"alloggio_id": slug, "check_in": ci, "check_out": co,
                        "party": party})
        if s != 200:
            assert s in (400, 404, 409, 410, 422, 429), "quote status: %d %r" % (s, q)
            return multiple()
        self._conservazione_denaro(q, "quote %s" % slug)
        return {"slug": slug, "ci": ci, "co": co, "q": q}

    @rule(target=prenotazioni, pv=consumes(preventivi))
    def prenota(self, pv):
        self._passo()
        s, b = self._g("POST", "/api/concierge/book",
                       {"quote_token": pv["q"]["quote_token"],
                        "email": "ospite@stateful.it", "lang": "it"})
        if s != 201:
            assert s in (400, 404, 409, 410, 422, 429), "book status: %d %r" % (s, b)
            return multiple()
        rif, vt = b.get("riferimento"), b.get("voucher_token")
        assert rif and vt, "book 201 senza riferimento/voucher: %r" % (b,)
        # numeri IDENTICI alla quote (firmati, immutabili) + conservazione anche sul book
        for k in ("totale_cents", "prezzo_guest_cents", "netto_host_cents",
                  "commissione_cents", "tassa_soggiorno_cents"):
            assert b.get(k) == pv["q"].get(k), \
                "I2 VIOLATO: %s cambia tra quote e book (%r != %r)" % (k, pv["q"].get(k),
                                                                       b.get(k))
        self._pren[rif] = {"vt": vt, "slug": pv["slug"], "ci": pv["ci"], "co": pv["co"],
                           "totale": int(b.get("totale_cents", 0)),
                           "visto_pagato": False}
        return rif

    @rule(rif=prenotazioni, doppio=st.booleans())
    def webhook_pagamento(self, rif, doppio):
        """Webhook firmato: normale, DOPPIO (retry Stripe) e — se la prenotazione e' gia'
        cancellata/scaduta perche' un'altra regola e' passata prima — in RITARDO."""
        self._passo()
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"id": "cs_" + rif[:10],
                                             "metadata": {"riferimento": rif}}}})
        h = {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))}
        for _ in range(2 if doppio else 1):
            s, o = self._raw("POST", "/api/payments/webhook", pl, h)
            assert s == 200, "webhook firmato deve dare 200: %d %r" % (s, o)
        if self._stato(rif) == "pagato":
            self._pren[rif]["visto_pagato"] = True

    @rule()
    def scadenza_hold_e_sweep(self):
        """Il tempo passa: gli hold non pagati scadono e lo sweeper libera le stanze
        (prepara il terreno al webhook TARDIVO)."""
        self._passo()
        con = sqlite3.connect(self.d + "/p.db")
        try:
            con.execute("UPDATE pendenti SET scadenza_ts=? WHERE stato IN "
                        "('in_attesa','in_attesa_host')", (int(time.time()) - 5,))
            con.commit()
        finally:
            con.close()
        sweep_hold_una_passata(self.sis, self.r)

    @rule(rif=prenotazioni)
    def cancella(self, rif):
        self._passo()
        p = self._pren[rif]
        s, o = self._g("POST", "/api/concierge/cancella", {"voucher_token": p["vt"]})
        assert s in (200, 400, 404, 409, 410, 422), "cancella status: %d %r" % (s, o)
        if s == 200 and isinstance(o, dict):
            rimb = o.get("rimborso_cents", 0)
            assert isinstance(rimb, int) and 0 <= rimb <= p["totale"], \
                "rimborso fuori da [0, totale]: %r (totale %d)" % (o, p["totale"])

    @rule(rif=prenotazioni)
    def rimborsa_admin(self, rif):
        self._passo()
        p = self._pren[rif]
        rec = self.sis.pagamenti_pendenti.info(rif) or {}
        idem = rec.get("idem_key") or ""
        if not idem:
            return
        s, o = self._g("POST", "/api/admin/rimborso",
                       {"alloggio_id": p["slug"], "check_in": p["ci"],
                        "check_out": p["co"], "idem_key": idem}, {"X-Admin-Key": "ak"})
        assert s in (200, 409, 422), "rimborso admin status: %d %r" % (s, o)

    @rule(rif=prenotazioni)
    def apri_controversia(self, rif):
        self._passo()
        p = self._pren[rif]
        s, o = self._g("POST", "/api/garanzia/contesta",
                       {"voucher_token": p["vt"], "motivo": "problema segnalato"})
        assert s in (200, 400, 403, 404, 409, 410, 422), "contesta status: %d %r" % (s, o)
        if not p["visto_pagato"]:
            # gate del viaggio cliente: la controversia si apre SOLO a pagamento avvenuto
            assert s != 200, "controversia aperta PRIMA del pagamento (gate saltato)"

    @rule(consenso=st.sampled_from([True, False, "true"]),
          tipo=st.sampled_from(["creator", "agenzia", "property_manager", "altro"]))
    def candidatura_partner(self, consenso, tipo):
        self._passo()
        self._n_partner += 1
        s, o = self._g("POST", "/api/partner",
                       {"nome": "Partner Prova %d" % self._n_partner,
                        "email": "p%d@stateful.it" % self._n_partner,
                        "tipo": tipo, "citta": "Roma", "consenso": consenso})
        if consenso is True:
            assert s in (201, 429), "partner con consenso: %d %r" % (s, o)
            if s == 201:
                self._partner_attesi += 1
        else:
            # GDPR-gate: senza consenso booleano True NON si scrive nulla
            assert s == 422 and o.get("errore") == "consenso_richiesto", \
                "GDPR-gate saltato: %d %r" % (s, o)

    # ── INVARIANTI: verificati DOPO OGNI passo ──────────────────────────────────────
    def _conservazione_denaro(self, q, dove):
        """I2: la matematica del preventivo quadra al CENTESIMO (interi esatti)."""
        tot = q["totale_cents"]
        guest = q["prezzo_guest_cents"]
        netto = q["prezzo_netto_cents"]
        comm = q["commissione_cents"]
        nh = q["netto_host_cents"]
        cp = q["costo_pagamento_cents"]
        tassa = q["tassa_soggiorno_cents"]
        sc = q["sconto_credito_cents"]
        assert tot == guest + tassa, "I2 (%s): totale != guest+tassa: %r" % (dove, q)
        assert guest == netto - sc, "I2 (%s): guest != netto-sconto: %r" % (dove, q)
        assert nh == netto - comm - cp and nh >= 0, \
            "I2 (%s): netto_host != netto-comm-carta: %r" % (dove, q)
        assert tot == nh + comm + cp + tassa - sc, \
            "I2 VIOLATO (%s): totale ospite != netto_host+commissione+carta+tassa-sconto " \
            "(%d != %d+%d+%d+%d-%d)" % (dove, tot, nh, comm, cp, tassa, sc)

    @invariant()
    def invarianti_globali(self):
        pp = self.sis.pagamenti_pendenti
        stati = {rif: self._stato(rif) for rif in self._pren}

        # ── I1: zero double-booking ────────────────────────────────────────────────
        paganti = {}                      # (slug, giorno) -> n prenotazioni 'pagato'
        for rif, p in self._pren.items():
            if stati.get(rif) != "pagato":
                continue
            d0 = datetime.date.fromisoformat(p["ci"])
            d1 = datetime.date.fromisoformat(p["co"])
            for i in range((d1 - d0).days):
                g = (d0 + datetime.timedelta(days=i)).isoformat()
                paganti[(p["slug"], g)] = paganti.get((p["slug"], g), 0) + 1
        for slug in self._slugs:
            righe = self.sis.inventario.stato_range(slug, _giorno(0),
                                                    _giorno(_FINESTRA - 1))
            for g, r in righe.items():
                occ = int(r.get("unita_occupate", 0))
                tot = int(r.get("unita_totali", 0))
                npag = paganti.get((slug, g), 0)
                assert 0 <= occ <= tot, \
                    "I1 VIOLATO: overbooking fisico %s %s occ=%d > tot=%d" % (slug, g,
                                                                              occ, tot)
                assert npag <= tot, \
                    "I1 VIOLATO: %d prenotazioni PAGATE sulla notte %s %s con %d unita'" \
                    % (npag, slug, g, tot)
                assert occ >= npag, \
                    "I1 VIOLATO: prenotazione pagata ma notte libera (soldi senza " \
                    "stanza) %s %s occ=%d pagate=%d" % (slug, g, occ, npag)

        # ── I2 (giornale): incasso al massimo 1, solo se davvero pagata, == totale ─
        fin = getattr(self.sis, "finanza", None)
        if fin is not None:
            for rif, p in self._pren.items():
                movs = fin.movimenti(rif) or []
                for m in movs:
                    imp = int(m.get("importo_cents", 0))
                    assert imp >= 0, "I4 VIOLATO: movimento negativo a giornale %r" % (m,)
                incassi = [m for m in movs if m.get("tipo") == "incasso"]
                assert len(incassi) <= 1, \
                    "I2 VIOLATO: DOPPIO INCASSO a giornale per %s: %r" % (rif, incassi)
                if incassi:
                    assert p["visto_pagato"], \
                        "I2 VIOLATO: incasso a giornale su prenotazione MAI vista " \
                        "'pagato' (rif %s, stato %r) -> webhook tardivo/duplicato " \
                        "accettato su stato non confermabile" % (rif, stati.get(rif))
                    assert incassi[0].get("importo_cents") == p["totale"], \
                        "I2 VIOLATO: incasso %r != totale ospite %d (rif %s)" \
                        % (incassi[0].get("importo_cents"), p["totale"], rif)
            assert fin.verifica_catena().get("ok"), "giornale: catena hash ROTTA"

        # ── I3: PIN/smart-pass MAI esposti prima del pagamento ─────────────────────
        firma = self.sis.firma
        for rif, p in self._pren.items():
            pagina = pagina_voucher_html(self.sis, p["vt"], "it")
            assert pagina, "voucher non renderizzato per %s" % rif
            pin = firma.pin_checkin(rif)
            if stati.get(rif) == "pagato":
                assert pin in pagina, \
                    "controllo positivo I3: prenotazione PAGATA ma PIN assente (%s)" % rif
            else:
                assert pin not in pagina, \
                    "I3 VIOLATO: PIN check-in esposto PRIMA del pagamento (rif %s, " \
                    "stato %r)" % (rif, stati.get(rif))
                sp = (firma.decodifica(p["vt"]) or {}).get("smart_pass") or ""
                if sp:
                    assert sp not in pagina, \
                        "I3 VIOLATO: smart-pass esposto prima del pagamento (%s)" % rif
                assert "/api/garanzia/" not in pagina, \
                    "I3 VIOLATO: tasti garanzia/controversia attivi prima del pagamento"

        # ── I4 (payout): mai importi negativi nel riepilogo host ───────────────────
        pd = getattr(self.sis, "payout", None)
        if pd is not None:
            for val, voci in (pd.riepilogo(self.host_id) or {}).items():
                for k, v in (voci or {}).items():
                    if isinstance(v, int) and not isinstance(v, bool):
                        assert v >= 0, "I4 VIOLATO: payout %s %s=%d" % (val, k, v)

        # ── partner: conservazione del conteggio (GDPR: i no-consenso NON scrivono) ─
        s, o = self._g("GET", "/api/admin/partner", None, {"X-Admin-Key": "ak"})
        assert s == 200 and o.get("totale") == self._partner_attesi, \
            "partner: attesi %d, trovati %r (scrittura senza consenso?)" \
            % (self._partner_attesi, o.get("totale"))


# Budget: ~20 mondi x ~20 passi ≈ 20-40s tipici (sotto il minuto anche sotto carico: il
# wall-clock su Windows/CI oscilla parecchio, misurato 16-70s a parita' di budget).
# La PROFONDITA' di caccia non dipende solo da questo numero: i 4 piloti qui sotto fissano
# in modo DETERMINISTICO le sequenze critiche gia' scovate (sempre rosse sulla regressione).
MacchinaBookinVIP.TestCase.settings = settings(
    max_examples=20, stateful_step_count=20, deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large,
                           HealthCheck.filter_too_much])

TestMacchinaStateful = MacchinaBookinVIP.TestCase
TestMacchinaStateful.__doc__ = "Esplorazione casuale: sequenze API generate da Hypothesis."


class TestSequenzePilota(unittest.TestCase):
    """Le 2 sequenze avversarie CRITICHE, deterministiche (sempre rosse sui difetti
    iniettati per la vista-rossa, indipendenti dalla fortuna del generatore)."""

    def _macchina(self):
        m = MacchinaBookinVIP()
        self.addCleanup(m.teardown)
        return m

    def test_pilota_webhook_tardivo_su_cancellata(self):
        """book -> cancella -> webhook IN RITARDO: niente incasso, niente 'pagato'."""
        m = self._macchina()
        slug = m.pubblica_annuncio(prezzo=30000, tassa=150, politica="flessibile",
                                   unita=1)
        pv = m.preventivo(slug=slug, off=2, notti=2, party=2)
        self.assertIsInstance(pv, dict, "setup: preventivo rifiutato")
        rif = m.prenota(pv=pv)
        self.assertIsInstance(rif, str, "setup: book rifiutato")
        m.cancella(rif=rif)
        m.webhook_pagamento(rif=rif, doppio=False)      # pagamento TARDIVO su cancellata
        m.invarianti_globali()                          # I2: nessun incasso fantasma
        self.assertNotEqual(m._stato(rif), "pagato",
                            "pagamento tardivo CONFERMATO su prenotazione cancellata")

    def test_pilota_rimborso_admin_dopo_reblock(self):
        """BUG VERO trovato da questa macchina (2026-07-27): dopo un pagamento TARDIVO il
        blocco attivo ha idem_key 'reblock:<rif>'; l'admin rimborsa con QUELLA chiave (e' la
        chiave che mostra il pannello) ma _admin_rimborso derivava rif=idem[:24] SENZA
        togliere il prefisso -> payout NON trattenuto, escrow NON chiuso, pendente NON
        invalidato: rimborsavamo l'ospite E l'escrow auto-rilasciava i soldi all'host
        (PERDITA PIENA — stessa classe del bug 2026-07-16, ma sul percorso re-block).
        Rosso sul codice vecchio."""
        m = self._macchina()
        slug = m.pubblica_annuncio(prezzo=30000, tassa=0, politica="flessibile", unita=1)
        pv = m.preventivo(slug=slug, off=2, notti=2, party=2)
        self.assertIsInstance(pv, dict)
        rif = m.prenota(pv=pv)
        self.assertIsInstance(rif, str)
        m.scadenza_hold_e_sweep()                       # hold spira, stanza liberata
        m.webhook_pagamento(rif=rif, doppio=False)      # pagamento TARDIVO -> re-block
        rec = m.sis.pagamenti_pendenti.info(rif)
        self.assertEqual(rec.get("stato"), "pagato")
        self.assertEqual(rec.get("idem_key"), "reblock:" + rif,
                         "setup: il re-block deve aver registrato la chiave fresca")
        m.rimborsa_admin(rif=rif)                       # l'admin rimborsa (chiave attiva)
        # DOPO il rimborso: i soldi DEVONO essere in sicurezza (come sul percorso normale)
        self.assertEqual(m._stato(rif), "rimborsato",
                         "pendente ancora 'pagato' dopo il rimborso admin (re-block)")
        maturato = (m.sis.payout.riepilogo(m.host_id) or {}).get("EUR", {}).get("maturato", 0)
        self.assertEqual(maturato, 0,
                         "payout host NON trattenuto sul rimborso post-reblock -> perdita")
        self.assertEqual((m.sis.garanzia.stato(rif) or {}).get("stato"), "annullato",
                         "escrow ancora aperto -> si auto-rilascia all'host")
        ril = m.sis.garanzia.auto_rilascia(ora_ts=int(time.time()) + 10 ** 9, dettagli=True)
        self.assertEqual(ril, [], "l'escrow paga l'host su prenotazione rimborsata")
        m.invarianti_globali()                          # I1: mai 'pagato' con stanza libera

    def test_pilota_garanzia_gated_dal_pagamento(self):
        """BUG VERO trovato da questa macchina (2026-07-27): /api/garanzia/contesta e
        /api/garanzia/conferma accettavano la chiamata DIRETTA col voucher di una
        prenotazione MAI PAGATA (la pagina nascondeva i tasti, l'API no): controversia a
        costo zero (payout host 'trattenuto' = griefing) o "tutto ok" prima del soggiorno.
        Ora: pendente non 'pagato' -> 409 pagamento_non_confermato; dopo il webhook -> 200.
        Rosso sul codice vecchio (la macchina l'ha scovato da sola: book->contesta)."""
        m = self._macchina()
        slug = m.pubblica_annuncio(prezzo=30000, tassa=0, politica="flessibile", unita=1)
        pv = m.preventivo(slug=slug, off=2, notti=2, party=2)
        self.assertIsInstance(pv, dict)
        rif = m.prenota(pv=pv)
        self.assertIsInstance(rif, str)
        vt = m._pren[rif]["vt"]
        # PRIMA del pagamento: contesta E conferma rifiutate (409), garanzia intatta
        s, o = m._g("POST", "/api/garanzia/contesta",
                    {"voucher_token": vt, "motivo": "griefing"})
        self.assertEqual((s, o.get("errore")), (409, "pagamento_non_confermato"), o)
        s, o = m._g("POST", "/api/garanzia/conferma", {"voucher_token": vt})
        self.assertEqual((s, o.get("errore")), (409, "pagamento_non_confermato"), o)
        self.assertEqual((m.sis.garanzia.stato(rif) or {}).get("stato"), "in_garanzia",
                         "l'escrow non deve muoversi senza pagamento")
        self.assertNotEqual(m.sis.payout.stato_di(rif), "trattenuto",
                            "payout host 'trattenuto' da una controversia mai pagata")
        # DOPO il pagamento: il flusso legittimo resta intatto (controllo positivo)
        m.webhook_pagamento(rif=rif, doppio=False)
        s, o = m._g("POST", "/api/garanzia/contesta",
                    {"voucher_token": vt, "motivo": "problema vero"})
        self.assertEqual(s, 200, ("contesta legittima bloccata dopo il pagamento", o))
        m.invarianti_globali()

    def test_pilota_webhook_doppio_e_gate_pin(self):
        """PIN nascosto pre-pagamento; webhook DOPPIO -> un solo incasso; PIN visibile dopo."""
        m = self._macchina()
        slug = m.pubblica_annuncio(prezzo=55000, tassa=0, politica="rigida", unita=1)
        pv = m.preventivo(slug=slug, off=1, notti=1, party=2)
        self.assertIsInstance(pv, dict)
        rif = m.prenota(pv=pv)
        self.assertIsInstance(rif, str)
        m.invarianti_globali()                          # I3: PIN nascosto pre-pagamento
        m.webhook_pagamento(rif=rif, doppio=True)       # retry Stripe (DOPPIO)
        self.assertEqual(m._stato(rif), "pagato")
        m.invarianti_globali()                          # I2: 1 solo incasso; I3: PIN visibile


def tearDownModule():
    import sys
    print("\n[stateful_api] mondi esplorati: %d, passi eseguiti: %d"
          % (MacchinaBookinVIP.sequenze_esplorate, MacchinaBookinVIP.passi_eseguiti),
          file=sys.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
