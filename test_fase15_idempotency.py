"""
Test FASE 15 - Idempotency Manager + decoratore @idempotent.

Copre: acquisizione/lock, conflitto fingerprint, replay in cache, scoping per
token, concorrenza (exactly-once), sweep lock morti, TTL/purge, e l'integrazione
del decoratore con Flask (replay, conflitto, passthrough, no-cache sui 5xx).
"""
import hashlib
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
import uuid

from flask import Flask, jsonify

from fase15_idempotency import IdempotencyManager, EsitoAcquisizione
from fase23_datastore import PostgresDatastore


class _BaseIdem(unittest.TestCase):
    """Setup comune: DB temporaneo isolato + singleton azzerato per ogni test."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "idem.db")
        os.environ["CORE_AUTO_DB"] = self.db
        os.environ["IDEMPOTENCY_TTL_HOURS"] = "24"
        os.environ["IDEMPOTENCY_LOCK_TIMEOUT_MIN"] = "5"
        IdempotencyManager._reset_instance()
        self.mgr = IdempotencyManager(self.db)
        self.fp = self.mgr.fingerprint("POST", "/api/v1/escrow/create",
                                       b'{"importo":100}')

    def tearDown(self) -> None:
        IdempotencyManager._reset_instance()
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestManager(_BaseIdem):

    def test_prima_acquire_acquisito_con_token(self):
        r = self.mgr.acquire("k1", self.fp, "corr-1")
        self.assertEqual(r.esito, EsitoAcquisizione.ACQUISITO)
        self.assertTrue(r.token)

    def test_seconda_acquire_in_corso_con_retry_after(self):
        self.mgr.acquire("k1", self.fp)
        r = self.mgr.acquire("k1", self.fp)
        self.assertEqual(r.esito, EsitoAcquisizione.IN_CORSO)
        self.assertGreater(r.retry_after, 0)

    def test_conflitto_su_body_diverso(self):
        self.mgr.acquire("k1", self.fp)
        fp2 = self.mgr.fingerprint("POST", "/api/v1/escrow/create",
                                   b'{"importo":999}')
        r = self.mgr.acquire("k1", fp2)
        self.assertEqual(r.esito, EsitoAcquisizione.CONFLITTO)

    def test_store_e_replay_in_cache(self):
        r1 = self.mgr.acquire("k1", self.fp)
        self.assertTrue(self.mgr.store("k1", r1.token, 201, '{"escrow_id":7}',
                                       {"Content-Type": "application/json"}))
        r2 = self.mgr.acquire("k1", self.fp)
        self.assertEqual(r2.esito, EsitoAcquisizione.IN_CACHE)
        self.assertEqual(r2.risposta["status"], 201)
        self.assertEqual(r2.risposta["body"], '{"escrow_id":7}')
        self.assertEqual(r2.risposta["headers"]["Content-Type"], "application/json")

    def test_store_con_token_errato_rifiutato(self):
        self.mgr.acquire("k1", self.fp)
        self.assertFalse(self.mgr.store("k1", "token-falso", 500, "x"))

    def test_release_token_scoped(self):
        r = self.mgr.acquire("k1", self.fp)
        self.assertFalse(self.mgr.release("k1", "altro-token"))
        self.assertTrue(self.mgr.release("k1", r.token))
        # dopo il release (nessuna risposta) -> ri-acquisibile
        self.assertEqual(self.mgr.acquire("k1", self.fp).esito,
                         EsitoAcquisizione.ACQUISITO)

    def test_concorrenza_exactly_once(self):
        risultati = []
        barriera = threading.Barrier(20)

        def worker():
            barriera.wait()
            risultati.append(self.mgr.acquire("conc", self.fp).esito)

        ts = [threading.Thread(target=worker) for _ in range(20)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(
            sum(1 for e in risultati if e == EsitoAcquisizione.ACQUISITO), 1)

    def test_sweep_lock_morto_e_riacquisizione(self):
        self.mgr.acquire("morto", self.fp)
        conn = self.mgr._conn()
        conn.execute("UPDATE idempotency_keys SET locked_at="
                     "'2000-01-01T00:00:00+00:00' WHERE idempotency_key='morto'")
        conn.close()
        self.assertGreaterEqual(self.mgr.sweep(), 1)
        self.assertEqual(self.mgr.acquire("morto", self.fp).esito,
                         EsitoAcquisizione.ACQUISITO)

    def test_ttl_scaduto_riacquisisce_non_replay(self):
        IdempotencyManager._reset_instance()
        mgr = IdempotencyManager(self.db)
        r = mgr.acquire("ttl", self.fp)
        mgr.store("ttl", r.token, 200, "{}")
        # scadenza DETERMINISTICA (retrodatata, come test_sweep): con TTL=0 il record
        # scadeva "nello stesso istante" della store e l'esito dipendeva dal microsecondo
        # (now > expires_at falso se i due passi cadono nello stesso timestamp) -> flaky.
        conn = mgr._conn()
        conn.execute("UPDATE idempotency_keys SET expires_at="
                     "'2000-01-01T00:00:00+00:00' WHERE idempotency_key='ttl'")
        conn.close()
        self.assertEqual(mgr.acquire("ttl", self.fp).esito,
                         EsitoAcquisizione.ACQUISITO)

    def test_purge_expired(self):
        IdempotencyManager._reset_instance()
        mgr = IdempotencyManager(self.db)
        r = mgr.acquire("ttl", self.fp)
        mgr.store("ttl", r.token, 200, "{}")
        # scadenza retrodatata (stesso motivo di test_ttl_scaduto: TTL=0 era sul filo
        # del microsecondo -> flaky)
        conn = mgr._conn()
        conn.execute("UPDATE idempotency_keys SET expires_at="
                     "'2000-01-01T00:00:00+00:00' WHERE idempotency_key='ttl'")
        conn.close()
        self.assertGreaterEqual(mgr.purge_expired(), 1)

    def test_singleton_ignora_db_path_diverso(self):
        altro = IdempotencyManager("/un/altro/path.db")
        self.assertIs(altro, self.mgr)

    def test_fingerprint_deterministico_e_sensibile(self):
        a = self.mgr.fingerprint("POST", "/x", b"body")
        b = self.mgr.fingerprint("POST", "/x", b"body")
        c = self.mgr.fingerprint("POST", "/x", b"BODY")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertEqual(len(a), 64)  # SHA-256 esadecimale completo

    def test_acquire_ritenta_su_busy_poi_riesce(self):
        from unittest import mock
        self.mgr._acquire_backoff = 0.0  # niente attese nel test
        chiamate = {"n": 0}
        reale = self.mgr._acquire_once

        def flaky(*a, **k):
            chiamate["n"] += 1
            if chiamate["n"] < 3:
                raise sqlite3.OperationalError("database is locked")
            return reale(*a, **k)

        with mock.patch.object(self.mgr, "_acquire_once", side_effect=flaky):
            r = self.mgr.acquire("retry", self.fp)
        self.assertEqual(r.esito, EsitoAcquisizione.ACQUISITO)
        self.assertEqual(chiamate["n"], 3)  # ha ritentato fino al successo

    def test_acquire_non_ritenta_errori_non_busy(self):
        from unittest import mock
        self.mgr._acquire_backoff = 0.0
        with mock.patch.object(self.mgr, "_acquire_once",
                               side_effect=sqlite3.OperationalError("no such table")):
            with self.assertRaises(sqlite3.OperationalError):
                self.mgr.acquire("x", self.fp)


class TestDecoratore(_BaseIdem):
    """Verifica il decoratore @idempotent isolato (senza fortress)."""

    def _make_app(self):
        from app import idempotent
        app = Flask(__name__)
        app.extensions["core_auto"] = {"idempotency": self.mgr}
        contatore = {"n": 0}

        @app.route("/op", methods=["POST"])
        @idempotent
        def op():
            contatore["n"] += 1
            return jsonify({"n": contatore["n"]}), 201

        @app.route("/boom", methods=["POST"])
        @idempotent
        def boom():
            contatore["n"] += 1
            return jsonify({"err": True}), 500

        return app, contatore

    def test_replay_exactly_once(self):
        app, contatore = self._make_app()
        c = app.test_client()
        h = {"Idempotency-Key": "abc"}
        r1 = c.post("/op", headers=h, json={"a": 1})
        r2 = c.post("/op", headers=h, json={"a": 1})
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 201)
        self.assertEqual(r1.get_json(), r2.get_json())   # stessa risposta
        self.assertEqual(contatore["n"], 1)              # eseguito una sola volta
        self.assertEqual(r2.headers.get("Idempotent-Replay"), "true")

    def test_conflitto_body_diverso(self):
        app, _ = self._make_app()
        c = app.test_client()
        h = {"Idempotency-Key": "abc"}
        c.post("/op", headers=h, json={"a": 1})
        r = c.post("/op", headers=h, json={"a": 2})
        self.assertEqual(r.status_code, 422)

    def test_senza_header_passthrough(self):
        app, contatore = self._make_app()
        c = app.test_client()
        c.post("/op", json={"a": 1})
        c.post("/op", json={"a": 1})
        self.assertEqual(contatore["n"], 2)  # nessuna idempotenza -> 2 esecuzioni

    def test_5xx_non_in_cache(self):
        app, contatore = self._make_app()
        c = app.test_client()
        h = {"Idempotency-Key": "boom-key"}
        r1 = c.post("/boom", headers=h, json={})
        r2 = c.post("/boom", headers=h, json={})
        self.assertEqual(r1.status_code, 500)
        self.assertEqual(r2.status_code, 500)
        self.assertEqual(contatore["n"], 2)  # 5xx rilascia il lock -> retry esegue

    def test_replay_preserva_location_header(self):
        # FASE 18: il replay deve restituire anche il Location di un 201 Created.
        from app import idempotent
        app = Flask(__name__)
        app.extensions["core_auto"] = {"idempotency": self.mgr}
        cont = {"n": 0}

        @app.route("/crea", methods=["POST"])
        @idempotent
        def crea():
            cont["n"] += 1
            resp = jsonify({"id": 7})
            resp.headers["Location"] = "/escrow/7"
            return resp, 201

        c = app.test_client()
        h = {"Idempotency-Key": "loc-" + uuid.uuid4().hex}
        r1 = c.post("/crea", headers=h, json={"a": 1})
        r2 = c.post("/crea", headers=h, json={"a": 1})
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 201)
        self.assertEqual(r1.headers.get("Location"), "/escrow/7")
        self.assertEqual(r2.headers.get("Location"), "/escrow/7")  # preservato!
        self.assertEqual(r2.headers.get("Idempotent-Replay"), "true")
        self.assertEqual(cont["n"], 1)


class TestIntegrazionePagamenti(unittest.TestCase):
    """End-to-end: fortress (HMAC) + @idempotent sulla route reale /payments/split."""

    def setUp(self):
        from app import create_app
        IdempotencyManager._reset_instance()
        self.app = create_app()
        self.client = self.app.test_client()

    def tearDown(self):
        IdempotencyManager._reset_instance()

    def _headers(self, method, path, body, idem_key):
        """Costruisce header fortress validi (nonce/timestamp freschi) + key."""
        from fase13_protocollo_finale import SecurityManager, _canonical_string
        ts = str(int(time.time()))
        nonce = uuid.uuid4().hex
        rid = uuid.uuid4().hex
        body_hash = hashlib.sha256(body).hexdigest()
        full_path = path + "?"  # Werkzeug.full_path aggiunge sempre '?'
        canonical = _canonical_string(
            [method, full_path, rid, ts, nonce, body_hash]).decode("utf-8")
        sig = SecurityManager.generate_signature(canonical, ts)
        return {
            "X-Request-ID": rid, "X-Timestamp": ts, "X-Nonce": nonce,
            "X-Body-Hash": body_hash, "X-Signature": sig,
            "Idempotency-Key": idem_key, "Content-Type": "application/json",
        }

    def test_payments_split_replay_idempotente(self):
        path = "/api/v1/payments/split"
        body = b"{}"  # payload incompleto -> 400 deterministico
        key = "it-" + uuid.uuid4().hex
        r1 = self.client.post(path, data=body, headers=self._headers("POST", path, body, key))
        r2 = self.client.post(path, data=body, headers=self._headers("POST", path, body, key))
        self.assertEqual(r1.status_code, 400)
        self.assertEqual(r2.status_code, 400)
        self.assertEqual(r2.headers.get("Idempotent-Replay"), "true")
        self.assertEqual(r1.get_json(), r2.get_json())

    def test_payments_split_conflitto_body_diverso(self):
        path = "/api/v1/payments/split"
        key = "it-" + uuid.uuid4().hex
        b1, b2 = b"{}", b'{"x":1}'
        self.client.post(path, data=b1, headers=self._headers("POST", path, b1, key))
        r2 = self.client.post(path, data=b2, headers=self._headers("POST", path, b2, key))
        self.assertEqual(r2.status_code, 422)  # stessa key, fingerprint diverso

    def test_fortress_attivo_senza_header(self):
        # Senza header fortress la route resta protetta (401), idempotenza a parte.
        r = self.client.post("/api/v1/payments/split", data=b"{}",
                             headers={"Content-Type": "application/json"})
        self.assertEqual(r.status_code, 401)

    def test_release_senza_admin_token_403(self):
        # FASE 18: autenticato (fortress) ma SENZA privilegio admin -> 403.
        path = "/api/v1/escrow/999999/release"
        h = self._headers("POST", path, b"", "adm-" + uuid.uuid4().hex)
        r = self.client.post(path, data=b"", headers=h)
        self.assertEqual(r.status_code, 403)

    def test_refund_senza_admin_token_403(self):
        path = "/api/v1/escrow/999999/refund"
        h = self._headers("POST", path, b"", "adm-" + uuid.uuid4().hex)
        r = self.client.post(path, data=b"", headers=h)
        self.assertEqual(r.status_code, 403)

    def test_release_con_admin_token_supera_authz(self):
        from fase13_protocollo_finale import Config
        path = "/api/v1/escrow/999999/release"
        h = self._headers("POST", path, b"", "adm-" + uuid.uuid4().hex)
        h["X-Admin-Token"] = Config.ADMIN_TOKEN
        r = self.client.post(path, data=b"", headers=h)
        self.assertNotEqual(r.status_code, 403)   # privilegio concesso
        self.assertEqual(r.status_code, 409)      # escrow inesistente

    def test_security_headers_presenti(self):
        r = self.client.get("/api/v1/health")
        self.assertEqual(r.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(r.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(r.headers.get("Referrer-Policy"), "no-referrer")
        self.assertIn("geolocation=()", r.headers.get("Permissions-Policy", ""))
        self.assertIn("default-src 'none'",
                      r.headers.get("Content-Security-Policy", ""))

    def test_correlation_id_generato_se_assente(self):
        r = self.client.get("/api/v1/health")
        cid = r.headers.get("X-Correlation-ID")
        self.assertTrue(cid)            # generato
        self.assertGreaterEqual(len(cid), 16)

    def test_correlation_id_propagato_dal_client(self):
        r = self.client.get("/api/v1/health", headers={"X-Request-ID": "abc123-XYZ_9"})
        self.assertEqual(r.headers.get("X-Correlation-ID"), "abc123-XYZ_9")

    def test_correlation_id_sanitizzato(self):
        # Caratteri non sicuri rimossi (anti log/header injection).
        r = self.client.get("/api/v1/health", headers={"X-Request-ID": "abc def!@#x"})
        self.assertEqual(r.headers.get("X-Correlation-ID"), "abcdefx")


class TestPortabilitaPostgres(unittest.TestCase):
    """BLOCCO 1.3: idempotency genera SQL dialetto-Postgres corretta col backend
    PG. Hermetico: datastore-spia + monkeypatch, nessun server reale."""

    def _spy(self, captured):
        class _Cur:
            rowcount = 1
            def execute(self, q, p=()):
                captured.append(q)
            def fetchone(self):
                return {"id": 1}
            def fetchall(self):
                return []
        class _Conn:
            def cursor(self):
                return _Cur()
            def close(self):
                pass
        class _SpyPG(PostgresDatastore):
            def __init__(self):
                pass
            def _connect_raw(self):
                return _Conn()
            def _begin(self, c):
                pass
            def _commit(self, c):
                pass
            def _rollback(self, c):
                pass
        return _SpyPG()

    def test_schema_dialetto_postgres(self):
        from unittest import mock
        captured = []
        spy = self._spy(captured)
        IdempotencyManager._reset_instance()
        try:
            with mock.patch("fase15_idempotency.get_datastore", return_value=spy):
                IdempotencyManager("ignorato_per_pg")  # _init_schema via spy PG
            ddl = " ".join(captured)
            self.assertIn("now()", ddl)
            self.assertNotIn("datetime('now')", ddl)
        finally:
            IdempotencyManager._reset_instance()

    def test_upsert_acquire_on_conflict_postgres(self):
        spy = self._spy([])
        sql = spy.upsert_ignore_sql(
            "idempotency_keys",
            ["idempotency_key", "request_fingerprint"], "idempotency_key")
        self.assertIn("ON CONFLICT (idempotency_key) DO NOTHING", sql)
        self.assertIn("%s", sql)
        self.assertNotIn("?", sql)


class _OraFinta:
    """Orologio bloccato per il modulo dell'idempotenza.

    Serve perche' due dei buchi stanno ESATTAMENTE sul confine (`<` contro `<=`,
    `>` contro `>=`): differiscono solo nell'istante preciso della scadenza, che con
    l'orologio vero non si colpisce mai. Si sostituisce il nome `datetime` dentro il
    modulo -- che lo ha importato nel proprio spazio -- e lo si rimette a posto dopo.
    """

    def __init__(self, istante):
        self.istante = istante

    def __enter__(self):
        import fase15_idempotency as m
        self._vero = m.datetime
        finta = self

        class _DT(self._vero):
            @classmethod
            def now(cls, tz=None):
                return finta.istante

        m.datetime = _DT
        return self

    def __exit__(self, *a):
        import fase15_idempotency as m
        m.datetime = self._vero
        return False


class TestIdempotenzaUndiciBuchiTrovatiDallaMutazione(_BaseIdem):
    """⛔ UNDICI BUCHI VERI NELL'ANTI-DOPPIO-ADDEBITO (mutazione, 2026-08-02).

    Campagna su tutti e 26 i punti di `fase15_idempotency`: 15 uccisi, 11 sopravvissuti
    -- il 42% scoperto. Il modulo ha UN SOLO file di prove (questo) e la campagna l'ha
    usato tutto: nessuna scorciatoia, sono buchi reali.

    E' il modulo che garantisce «esattamente una volta» su escrow, split e rimborsi:
    quando sbaglia, o si addebita due volte, o non si addebita mai piu'.
    """

    def _riga(self, key):
        import sqlite3 as s
        con = s.connect(self.db)
        con.row_factory = s.Row
        try:
            r = con.execute("SELECT * FROM idempotency_keys WHERE idempotency_key=?",
                            (key,)).fetchone()
            return dict(r) if r else None
        finally:
            con.close()

    def _sposta_lock_indietro(self, key, minuti):
        import datetime as dt
        import sqlite3 as s
        quando = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minuti)).isoformat()
        con = s.connect(self.db)
        try:
            with con:
                con.execute("UPDATE idempotency_keys SET locked_at=? WHERE idempotency_key=?",
                            (quando, key))
        finally:
            con.close()
        return quando

    # ── I DUE CHE POSSONO FAR PAGARE DUE VOLTE ──────────────────────────────────────
    def test_un_lock_MORTO_viene_recuperato_e_chi_lo_prende_lo_SA(self):
        """⛔ IL PEGGIORE DEI UNDICI.

            steal = UPDATE ... WHERE idempotency_key=? AND locked_by=? AND locked_at IS ?
            if steal.rowcount == 1: return ACQUISITO

        E' il recupero di un lock lasciato da un worker morto. Con `!=` al posto di `==`
        la logica si ROVESCIA: chi RIESCE a prendere il lock si sente dire «occupato», e
        chi FALLISCE si sente dire «e' tuo». Due worker che perdono la gara crederebbero
        entrambi di avere il lock ed eseguirebbero entrambi l'operazione: **doppio
        addebito**, cioe' esattamente cio' che questo modulo esiste per impedire.

        E il gemello alla riga 262 (`and` -> `or`): il lock morto non verrebbe MAI
        recuperato, e quella chiave resterebbe bloccata per sempre -- l'operazione non si
        potrebbe piu' ritentare.
        """
        r1 = self.mgr.acquire("K-MORTO", self.fp)
        self.assertEqual(EsitoAcquisizione.ACQUISITO, r1.esito)
        # il worker "muore": non chiama ne' store ne' release. Il lock invecchia oltre
        # la soglia (5 minuti configurati in setUp).
        self._sposta_lock_indietro("K-MORTO", 6)
        r2 = self.mgr.acquire("K-MORTO", self.fp)
        self.assertEqual(EsitoAcquisizione.ACQUISITO, r2.esito,
                         "un lock morto da 6 minuti NON e' stato recuperato: quella chiave "
                         "resta bloccata per sempre e l'operazione non si puo' piu' fare "
                         "(esito visto: %r)" % (r2.esito,))
        self.assertTrue(r2.token, "recupero dichiarato senza dare il token del lock")
        self.assertNotEqual(r1.token, r2.token, "ha restituito il token del worker morto")
        # ...e il verso opposto: un lock VIVO non si ruba
        r3 = self.mgr.acquire("K-MORTO", self.fp)
        self.assertEqual(EsitoAcquisizione.IN_CORSO, r3.esito,
                         "ha rubato un lock ancora vivo: due worker in esecuzione insieme")

    def test_il_confine_ESATTO_del_lock_morto(self):
        """`(now - locked_at) < lock_timeout` con `<=`: nell'istante PRECISO in cui il lock
        compie la soglia, il codice sano lo considera morto (e lo recupera), il codice
        guasto lo considera ancora vivo. Un istante di differenza, ma e' l'unico punto in
        cui le due versioni si distinguono: provare «prima» e «dopo» lascia vivo il guasto
        (lezione del 2026-08-01 sul backoff della carta).
        """
        import datetime as dt
        self.assertEqual(EsitoAcquisizione.ACQUISITO,
                         self.mgr.acquire("K-CONFINE", self.fp).esito)
        riga = self._riga("K-CONFINE")
        bloccato = dt.datetime.fromisoformat(riga["locked_at"])
        # adesso = esattamente locked_at + soglia
        esatto = bloccato + dt.timedelta(minutes=5)
        with _OraFinta(esatto):
            r = self.mgr.acquire("K-CONFINE", self.fp)
        self.assertEqual(EsitoAcquisizione.ACQUISITO, r.esito,
                         "all'istante esatto della soglia il lock e' morto e va recuperato; "
                         "invece: %r" % (r.esito,))

    def test_il_confine_ESATTO_della_risposta_in_cache(self):
        """`now > expires_at` con `>=`: nell'istante preciso della scadenza, la risposta in
        cache e' ancora valida (si replica) oppure e' gia' scaduta (si riesegue). Riesguire
        una volta di troppo su un rimborso significa **rimborsare due volte**."""
        import datetime as dt
        r = self.mgr.acquire("K-TTL", self.fp)
        self.mgr.store("K-TTL", r.token, 200, '{"ok": true}', {})
        riga = self._riga("K-TTL")
        scadenza = dt.datetime.fromisoformat(riga["expires_at"])
        with _OraFinta(scadenza):          # adesso == scadenza, al microsecondo
            esito = self.mgr.acquire("K-TTL", self.fp)
        self.assertEqual(EsitoAcquisizione.IN_CACHE, esito.esito,
                         "all'istante esatto della scadenza la risposta e' ancora valida e "
                         "va replicata, non rieseguita: %r" % (esito.esito,))
        with _OraFinta(scadenza + dt.timedelta(seconds=1)):
            dopo = self.mgr.acquire("K-TTL", self.fp)
        self.assertEqual(EsitoAcquisizione.ACQUISITO, dopo.esito,
                         "un secondo DOPO la scadenza la chiave va riacquisita")

    # ── LA CONFIGURAZIONE: quale database, davvero ──────────────────────────────────
    def test_il_percorso_PASSATO_vince_sull_ambiente(self):
        """`db_path or os.environ.get("CORE_AUTO_DB", ...)` con un `and`: chi passa un
        percorso esplicito si ritrova a scrivere **nel database dell'ambiente**. Le chiavi
        di idempotenza finirebbero in un archivio diverso da quello che il chiamante crede:
        la protezione dal doppio addebito continua a «funzionare»... su un altro libro.
        """
        import os
        altro = os.path.join(self.tmp, "AMBIENTE.db")
        os.environ["CORE_AUTO_DB"] = altro
        IdempotencyManager._reset_instance()
        mgr = IdempotencyManager(self.db)          # esplicito: deve vincere questo
        self.assertEqual(self.db, mgr._db_path,
                         "ha usato il database dell'ambiente invece di quello passato")
        mgr.acquire("K-DOVE", mgr.fingerprint("POST", "/x", b"{}"))
        self.assertIsNotNone(self._riga("K-DOVE"),
                             "la chiave non e' finita nel database indicato")
        self.assertFalse(os.path.exists(altro),
                         "ha creato (e usato) il database dell'ambiente: %s" % altro)

    def test_un_secondo_percorso_viene_IGNORATO_e_lo_dice(self):
        """Il manager e' un singleton: un secondo `IdempotencyManager(altro_db)` NON cambia
        database -- ed e' giusto -- ma **deve dirlo**, se no chi scrive quella riga crede di
        aver cambiato archivio e non lo saprà mai. E non deve gridare quando non c'e' niente
        da segnalare: `if db_path and db_path != self._db_path` con un `or` avvisa anche
        quando nessun percorso e' stato passato, con `==` avvisa quando e' lo STESSO."""
        import logging
        import os
        altro = os.path.join(self.tmp, "SECONDO.db")
        with self.assertLogs("core_auto.idempotency", level="WARNING") as reg:
            m2 = IdempotencyManager(altro)
        self.assertIs(self.mgr, m2, "il singleton e' stato duplicato")
        self.assertEqual(self.db, m2._db_path, "il secondo percorso ha cambiato archivio")
        self.assertTrue(any("IGNORATO" in r.getMessage() for r in reg.records),
                        "non ha avvisato che il secondo percorso viene ignorato: %r"
                        % (reg.output,))
        # ...e TACE quando non c'e' niente da dire (stesso percorso, o nessun percorso)
        for uguale in (self.db, None):
            with self.assertRaises(AssertionError):
                with self.assertLogs("core_auto.idempotency", level="WARNING"):
                    IdempotencyManager(uguale)

    def test_il_singleton_NON_si_reinizializza(self):
        """`self._initialized = True` con `False`: ogni costruzione rifarebbe l'intero
        avvio -- schema compreso -- e soprattutto ricreerebbe la connessione al database
        sotto i piedi di chi la sta usando."""
        ds_prima = self.mgr._ds
        self.assertTrue(self.mgr._initialized)
        m2 = IdempotencyManager(self.db)
        self.assertTrue(m2._initialized, "il manager si e' dichiarato NON inizializzato")
        self.assertIs(ds_prima, m2._ds,
                      "la connessione al database e' stata ricreata a ogni costruzione: "
                      "chi la stava usando se la vede cambiare sotto i piedi")

    # ── ROBUSTEZZA ──────────────────────────────────────────────────────────────────
    def test_il_risultato_di_acquire_e_IMMUTABILE(self):
        """`@dataclass(frozen=True)` con `False`: il risultato diventa modificabile. Il
        chiamante potrebbe cambiare l'esito o il token *dopo* averlo ricevuto -- e in un
        percorso dove «ACQUISITO» significa «puoi addebitare», un esito modificabile e' un
        permesso che si puo' riscrivere."""
        import dataclasses
        r = self.mgr.acquire("K-FROZEN", self.fp)
        with self.assertRaises(dataclasses.FrozenInstanceError,
                               msg="il risultato di acquire si puo' modificare"):
            r.esito = EsitoAcquisizione.IN_CACHE
        with self.assertRaises(dataclasses.FrozenInstanceError):
            r.token = "token-inventato"

    def test_un_errore_NON_ritentabile_non_viene_ritentato(self):
        """`if not _is_locked_error(exc) or tentativo == self._acquire_retries: raise` con un
        `and`: un errore che non c'entra niente col database occupato (una tabella che non
        esiste, un file corrotto) verrebbe **ritentato tre volte con attesa**, invece di
        emergere subito. Su un percorso che tiene fermo un pagamento, tre attese inutili
        sono tre secondi in cui il cliente non sa se ha pagato."""
        tentativi = {"n": 0}
        vero = self.mgr._acquire_once

        def _rompi(*a, **k):
            tentativi["n"] += 1
            raise sqlite3.OperationalError("no such table: idempotency_keys")

        self.mgr._acquire_once = _rompi
        try:
            with self.assertRaises(sqlite3.OperationalError):
                self.mgr.acquire("K-ROTTA", self.fp)
        finally:
            self.mgr._acquire_once = vero
        self.assertEqual(1, tentativi["n"],
                         "un errore non ritentabile e' stato ritentato %d volte"
                         % tentativi["n"])

    def test_un_errore_ISOLATO_lascia_la_traccia(self):
        """L'ultimo respiro di `acquire` prima di rilanciare: senza la traccia, il registro
        dice «idempotency acquire fallita» e nessuno sapra' mai perche' -- su un modulo che
        decide se un pagamento e' gia' stato fatto.

        ⚠️ Osservabile FORTE: con `exc_info=False` il campo vale `False`, che NON e' `None`.
        """
        # ⛔ SI ROMPE AL GRADINO GIUSTO. Quel `logger.error` sta DENTRO `_acquire_once`,
        # non in `acquire`: sostituire `_acquire_once` (come facevo prima) salta proprio il
        # codice che deve gridare, e la prova diventa verde senza aver provato niente.
        # Qui si rompe il gradino sotto -- il datastore -- cosi' l'eccezione nasce dove il
        # modulo se l'aspetta.
        vero = self.mgr._ds.transaction

        def _rompi(*a, **k):
            raise sqlite3.OperationalError("disco pieno")

        self.mgr._ds.transaction = _rompi
        try:
            with self.assertLogs("core_auto.idempotency", level="ERROR") as reg:
                with self.assertRaises(sqlite3.OperationalError):
                    self.mgr.acquire("K-TRACCIA", self.fp)
        finally:
            self.mgr._ds.transaction = vero
        tracce = [r.exc_info for r in reg.records if r.exc_info not in (None, False)]
        self.assertTrue(tracce, "nessuna traccia dell'errore: %r" % (reg.output,))
        self.assertIsInstance(tracce[0], tuple)
        self.assertIsInstance(tracce[0][1], BaseException)


if __name__ == "__main__":
    unittest.main()
