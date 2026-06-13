#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Smoke test dei moduli VISIONARY_OMEGA_V4 (schema esteso + moduli FASE 7).
Non sostituisce i 32 test unittest: verifica end-to-end le funzionalita' nuove
su un DB temporaneo. Esecuzione: python test_visionary.py"""

import datetime
import os
import sqlite3
import tempfile

import assistente_gestionale as ag

tmp = tempfile.mkdtemp()
dbp = os.path.join(tmp, "db.sqlite3")
db = ag.DatabaseCandidati(dbp)
audit = ag.AuditLog(os.path.join(tmp, "audit.jsonl"))

# --- Verifica colonne estese (FASE 5) ---
con = sqlite3.connect(dbp)
cols = [r[1] for r in con.execute("PRAGMA table_info(candidati)")]
attese = ["tipo_struttura", "servizi_json", "capienza_persone", "camere",
          "bagni", "host_email", "host_telefono", "host_nome", "stato",
          "modalita_ingresso", "data_scadenza", "ical_url", "ical_last_sync",
          "link_magico"]
assert all(c in cols for c in attese), [c for c in attese if c not in cols]

# --- Verifica tabelle nuove (FASE 6) ---
tab = [r[0] for r in
       con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
for t in ["prenotazioni", "link_magici_log", "ical_sync_log", "cache_scraping"]:
    assert t in tab, t

# --- Verifica indici sulle FK (FASE 6) ---
idx = [r[0] for r in
       con.execute("SELECT name FROM sqlite_master WHERE type='index'")]
for i in ["idx_prenotazioni_candidato", "idx_link_magici_candidato",
          "idx_ical_sync_candidato"]:
    assert i in idx, i

# --- WAL attivo (FASE 1) ---
assert con.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
con.close()
print("SCHEMA OK - colonne:", len(cols), "tabelle:", tab)

# --- FlashHostManager: scadenza a 7 giorni (FASE 7) ---
flash = ag.FlashHostManager(db, audit)
url = flash.crea_flash({"titolo": "Loft", "citta": "Milano", "prezzo": 120})
con = sqlite3.connect(dbp)
sc = con.execute("SELECT data_scadenza, stato FROM candidati "
                 "WHERE url_candidato=?", (url,)).fetchone()
con.close()
attesa = (datetime.date.today() + datetime.timedelta(days=7)).isoformat()
assert sc[0] == attesa, sc
assert sc[1] == "flash"
print("FLASH scadenza +7gg OK:", sc, url)

# --- LinkMagiciEngine: genera, risolvi, usa una sola volta (FASE 7) ---
le = ag.LinkMagiciEngine(db, audit)
link = le.genera_link_host(url)
dati = le.risolvi_link(link)
assert dati["ruolo"] == "host" and not dati["usato"]
assert le.esegui_azione(link, "conferma", nuovo_stato="confermato")
assert le.esegui_azione(link, "riuso") is False  # gia' usato
con = sqlite3.connect(dbp)
st = con.execute("SELECT stato FROM candidati WHERE url_candidato=?",
                 (url,)).fetchone()[0]
con.close()
assert st == "confermato", st
print("LINK MAGICI OK - stato candidato:", st)

# --- Cache scraping su filesystem + DB (FASE 3) ---
db.cache_scrivi("http://x/q", "<html>ok</html>",
                {"risultati": [{"url": "a"}]}, os.path.join(tmp, "cache"))
c = db.cache_leggi("http://x/q")
assert c and c["risultati"][0]["url"] == "a"
print("CACHE OK")

# --- iCal export: con icalendar installato produce un VCALENDAR; senza, "" ---
feed = ag.iCalSyncEngine(db, audit).genera_ical_uscita(url)
print("ICAL export:", repr(feed))

# --- IngestoreVIP senza geopy: inserisce comunque, punteggio forzato 2.0 ---
ing = ag.IngestoreVIP(db, audit)
r = ing.ingesta([{"titolo": "Villa VIP", "citta": "Roma",
                  "testo": "contatto host@vip.it +39 333 1234567"}])
assert r["inseriti"] == 1, r
con = sqlite3.connect(dbp)
row = con.execute("SELECT punteggio, host_email, host_telefono, "
                  "modalita_ingresso FROM candidati "
                  "WHERE modalita_ingresso='vip'").fetchone()
con.close()
assert row[0] == 2.0 and row[1] == "host@vip.it" and row[3] == "vip", row
print("INGEST VIP OK:", row)

# --- Flash pulisci scaduti (nessuno scaduto adesso) ---
print("FLASH pulisci scaduti:", flash.pulisci_scaduti())

print("\nTUTTI I MODULI NUOVI: OK")
