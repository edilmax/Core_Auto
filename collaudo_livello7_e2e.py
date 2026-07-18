# -*- coding: utf-8 -*-
"""LIVELLO 7 — VIAGGIO E2E DAL VIVO su produzione (bookinvip.com), stdlib puro.

Il viaggio VERO, non simulato: un host usa-e-getta si registra -> pubblica -> apre le
date; un ospite lo TROVA nella ricerca, chiede il preventivo firmato e PRENOTA
(modalita' immediata, SENZA pagare: il link Stripe nasce e scade da solo, zero soldi
mossi, zero email a persone vere); poi si verifica che il calendario dell'host mostri
le notti IN TRATTATIVA (hold vivo). In coda stampa gli ID esatti per la PULIZIA
TOMBALE (fatta via SSH con la chiave admin, mai da qui).

REGOLE PROD-SAFE: mai email vere (dominio .invalid) · niente pagamento · niente
segreti stampati · citta' inventata (non inquina le ricerche vere) · pulizia per ID
esatti subito dopo.
"""
import datetime
import json
import secrets
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = 'https://bookinvip.com'
TOK = secrets.token_hex(4)
CITTA = 'Zzeta Prova ' + TOK          # inesistente: nessun cliente vero la cerca
EMAIL_HOST = 'e2e-host-%s@test.invalid' % TOK
EMAIL_GUEST = 'e2e-guest-%s@test.invalid' % TOK
CTX = ssl.create_default_context()

oggi = datetime.date.today()
CI = (oggi + datetime.timedelta(days=40)).isoformat()
CO = (oggi + datetime.timedelta(days=42)).isoformat()


def chiama(metodo, path, corpo=None, tok=None):
    req = urllib.request.Request(BASE + path, method=metodo)
    req.add_header('Content-Type', 'application/json')
    if tok:
        req.add_header('X-Host-Token', tok)
    dati = json.dumps(corpo).encode('utf-8') if corpo is not None else None
    try:
        with urllib.request.urlopen(req, dati, timeout=30, context=CTX) as r:
            return r.status, json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode('utf-8'))
        except Exception:
            return e.code, {}


PASSI = []


def passo(nome, ok, dett=''):
    PASSI.append(bool(ok))
    print(('OK ' if ok else 'KO ') + nome + ((' | ' + str(dett)[:200]) if dett else ''))
    if not ok:
        fine()


def fine():
    print('== LIVELLO 7:', 'VERDE' if all(PASSI) else 'ROSSO', '(%d passi) ==' % len(PASSI))
    sys.exit(0 if all(PASSI) else 1)


# 0) sito vivo
s, d = chiama('GET', '/api/health')
passo('produzione viva (/api/health)', s == 200, s)

# 1) contratto host vivo (impronta per l'accettazione firmata)
s, doc = chiama('GET', '/api/legale/contratto-host?lang=it')
passo('contratto host vivo (impronta SHA-256)', s == 200 and doc.get('doc_sha256'), s)

# 2) l'host si registra DA SOLO
s, d = chiama('POST', '/api/host/registrazione', {
    'email': EMAIL_HOST, 'password': 'E2e!' + secrets.token_hex(8),
    'ragione_sociale': 'E2E Livello7', 'telefono': '',
    'accetta_termini': True, 'accetta_clausole': True,
    'doc_sha256': doc.get('doc_sha256', ''), 'versione': doc.get('versione', ''),
    'lang': 'it', 'codice_referral': ''})
passo('host registrato (token ricevuto)', s in (200, 201) and d.get('token'), (s, d.get('errore')))
TOKH = d['token']

# 3) pubblica un annuncio VERO
s, d = chiama('POST', '/api/host/pubblica', {
    'titolo': 'Collaudo E2E ' + TOK, 'citta': CITTA,
    'descrizione': 'Annuncio di collaudo tecnico: sara\' rimosso subito.',
    'valuta': 'EUR', 'prezzo_notte_cents': 12000,
    'politica_cancellazione': 'flessibile', 'tassa_pp_notte_cents': 0,
    'tassa_max_notti': 0, 'sconto_settimana_bps': 0, 'sconto_mese_bps': 0,
    'modalita_prenotazione': 'immediata', 'capacita': 2,
    'servizi': ['wifi'], 'immagini': []}, TOKH)
passo('annuncio pubblicato', s == 201 and d.get('slug'), (s, d.get('errore'), d.get('dettaglio')))
SLUG = d['slug']
print('== DATI PULIZIA (subito, anche se poi fallisce) ==',
      json.dumps({'slug': SLUG, 'citta': CITTA, 'email_host': EMAIL_HOST}))

# 4) apre le date
s, d = chiama('POST', '/api/host/disponibilita_range', {
    'alloggio_id': SLUG, 'da': CI, 'a': CO,
    'unita_totali': 1, 'prezzo_netto_cents': 12000}, TOKH)
passo('date aperte (%s -> %s)' % (CI, CO), s == 200 and d.get('giorni_impostati') == 2, (s, d))

# 5) l'ospite lo TROVA nella ricerca pubblica
s, d = chiama('GET', '/api/catalogo?citta=' + urllib.parse.quote(CITTA)
              + '&check_in=%s&check_out=%s' % (CI, CO))
trovato = any(a and a.get('slug') == SLUG for a in (d.get('risultati') or []))
passo('l\'ospite lo trova nella ricerca', s == 200 and trovato, s)

# 6) preventivo firmato + conti al centesimo
s, q = chiama('POST', '/api/concierge/quote', {
    'alloggio_id': SLUG, 'check_in': CI, 'check_out': CO, 'party': 2,
    'fonte': 'marketplace'})
passo('preventivo firmato', s == 200 and q.get('quote_token'), (s, q.get('errore')))
passo('conti: totale == soggiorno + tassa (>0)',
      q.get('totale_cents') == (q.get('prezzo_guest_cents') or 0) + (q.get('tassa_soggiorno_cents') or 0)
      and (q.get('totale_cents') or 0) > 0, q.get('totale_cents'))

# 7) PRENOTA (immediata): nasce il link Stripe VERO ma NESSUNO paga (scade da solo)
s, b = chiama('POST', '/api/concierge/book', {'quote_token': q['quote_token'], 'email': EMAIL_GUEST})
passo('prenotazione creata (link pagamento nato, non pagato)',
      s in (200, 201) and (b.get('payment_url') or b.get('stato')), (s, b.get('errore'), b.get('stato')))
print('== RIFERIMENTO ==', json.dumps({'riferimento': b.get('riferimento', ''), 'stato': b.get('stato', '')}))

# 8) il calendario dell'host mostra le notti IN TRATTATIVA (hold vivo = semaforo arancione)
s, c = chiama('GET', '/api/host/calendario?alloggio=%s&da=%s&a=%s' % (SLUG, CI, CO), tok=TOKH)
stati = dict((g.get('giorno'), g.get('stato')) for g in (c.get('giorni') or []) if g)
passo('calendario host: notte in TRATTATIVA (hold vivo)', stati.get(CI) == 'in_trattativa', stati)

fine()
