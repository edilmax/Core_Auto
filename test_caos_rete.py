# -*- coding: utf-8 -*-
"""CAOS DI RETE + FUZZING sul VERO JavaScript delle 3 pagine (compartimento Gestione Errori).

Non guardie statiche: qui il JS di index/host/admin viene ESEGUITO dentro Node con un
DOM finto e bombardato con i protocolli chiesti dal fondatore:
  - Chaos/Network: richieste che PENDONO per sempre (latenza estrema -> deve scattare il
    timeout, non aspettare), rete rifiutata, 500/502/503 con HTML al posto del JSON,
    200 con corpo corrotto;
  - Boundary/Fuzzing: array JSON al posto dell'oggetto, righe null nelle liste, campi
    mancanti (niente "NaN"/"undefined" a schermo), codici d'errore con HTML dentro
    (devono uscire escapati), 200 con una stringa nuda.
Invarianti: MAI un falso vuoto ("non hai nulla" durante un guasto), MAI un codice
tecnico grezzo all'utente, il timeout scatta presto, lo scudo dei tasti si riapre.

Se Node non e' installato i test vengono saltati (skip), non falsi-verdi.
"""
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'deploy')
NODE = shutil.which('node')


def _estrai_js(nome):
    html = io.open(os.path.join(BASE, nome), encoding='utf-8').read()
    return re.findall(r'<script>(.*?)</script>', html, re.S)[0]


# DOM finto minimo ma fedele: elementi auto-vivificanti registrati per id, cosi' i test
# possono leggere DOPO cosa la pagina ha scritto (innerHTML/textContent/disabled...).
PRELUDIO = r"""
const CHECKS=[];
function check(nome, ok, note){ CHECKS.push({nome:nome, ok:!!ok, note:String(note==null?'':note).slice(0,300)}); }
process.on('unhandledRejection', function(e){ check('promessa NON gestita: '+(e&&e.message), false, ''); });

const REG = new Map();
function mkEl(id){
  const el = {
    id: id||'', value:'', innerHTML:'', textContent:'', className:'', checked:false,
    disabled:false, files:[], options:[], selectedIndex:0, firstChild:null, parentNode:null,
    offsetWidth: 80, hidden:false, style:{}, dataset:{},
    classList:{ add(){}, remove(){}, contains(){ return false; } },
    setAttribute(){}, getAttribute(){ return null; }, removeAttribute(){},
    appendChild(){ return el; }, removeChild(){}, insertBefore(){}, replaceWith(){},
    closest(){ return null; }, querySelectorAll(){ return []; }, querySelector(){ return null; },
    addEventListener(){}, removeEventListener(){}, select(){}, focus(){}, click(){},
    scrollIntoView(){},
  };
  return el;
}
const document = {
  getElementById(id){ if(!REG.has(id)) REG.set(id, mkEl(id)); return REG.get(id); },
  querySelectorAll(){ return []; }, querySelector(){ return null; },
  createElement(tag){ return mkEl('__nuovo_'+tag); },
  addEventListener(){}, removeEventListener(){},
  documentElement: mkEl('documentElement'), head: mkEl('head'), body: mkEl('body'),
  hidden:false,
};
const _store = new Map();
const localStorage = {
  getItem(k){ return _store.has(k)?_store.get(k):null; },
  setItem(k,v){ _store.set(k,String(v)); },
  removeItem(k){ _store.delete(k); },
};
const navigator = { language:'it-IT', languages:['it-IT'], clipboard:{ writeText(){} } };
const location = { origin:'https://test.bookinvip.local', search:'', href:'https://test.bookinvip.local/' };
const window = globalThis;
globalThis.addEventListener = function(){}; globalThis.removeEventListener = function(){};
globalThis.open = function(){};
window.__TEMPO_MAX_MS = 120;   // latenza estrema simulata: il timeout deve scattare QUI, non a 20s
const ALERTS=[]; const alert = function(m){ ALERTS.push(String(m)); };
const confirm = function(){ return true; }; const prompt = function(){ return null; };
const BLOBS=[]; class Blob{ constructor(parts){ BLOBS.push(parts); } }
URL.createObjectURL = function(){ return 'blob:finto'; }; URL.revokeObjectURL = function(){};

// rubinetto di rete pilotabile dagli scenari
let FETCH = async function(u,o){ return jsonRes(200, {ui:{},servizi:{}}); };
const fetch = function(url, opts){ return Promise.resolve().then(function(){ return FETCH(String(url), opts||{}); }); };
function jsonRes(status, body){ return {ok:status>=200&&status<300, status:status, json: async function(){ return JSON.parse(JSON.stringify(body)); }}; }
function corrotto(status){ return {ok:status>=200&&status<300, status:status, json: async function(){ throw new Error('corpo non-JSON'); }}; }
function pende(opts){ return new Promise(function(res,rej){ const s=opts&&opts.signal;
  if(s){ if(s.aborted) return rej(new DOMException('abortita','AbortError'));
         s.addEventListener('abort', function(){ rej(new DOMException('abortita','AbortError')); }); } }); }
function rifiuta(){ throw new TypeError('Failed to fetch'); }
"""

CODA = r"""
__main().then(function(){
  let ko=0;
  for(const c of CHECKS){ if(!c.ok) ko++; console.log('CHECK_JSON '+JSON.stringify(c)); }
  console.log('FINE ok='+(CHECKS.length-ko)+' ko='+ko);
  process.exit(ko?1:0);
}).catch(function(e){
  console.log('CHECK_JSON '+JSON.stringify({nome:'ECCEZIONE HARNESS: '+(e&&e.message), ok:false, note:String(e&&e.stack).slice(0,400)}));
  process.exit(1);
});
"""

SCENARI_INDEX = r"""
async function __main(){
  await new Promise(function(r){ setTimeout(r,250); });   // lascia finire il boot della pagina
  let t0=Date.now();
  FETCH = function(u,o){ return pende(o); };
  const r1 = await api('/api/prova');
  check('index: latenza infinita -> rete_lenta', r1.errore==='rete_lenta', JSON.stringify(r1));
  check('index: il timeout scatta presto (no attesa 20s)', (Date.now()-t0)<3000, (Date.now()-t0)+'ms');
  FETCH = function(){ return rifiuta(); };
  check('index: rete giu -> rete_non_raggiungibile', (await api('/x')).errore==='rete_non_raggiungibile');
  for(const s of [500,502,503]){
    FETCH = function(){ return corrotto(s); };
    const r=await api('/x');
    check('index: '+s+' con HTML -> errore_server_'+s, r.errore==='errore_server_'+s, JSON.stringify(r));
  }
  FETCH = function(){ return corrotto(200); };
  check('index: 200 corrotto -> risposta_non_valida', (await api('/x')).errore==='risposta_non_valida');
  FETCH = function(){ return jsonRes(200,[1,2,3]); };
  check('index: FUZZ array al posto di oggetto -> risposta_non_valida', (await api('/x')).errore==='risposta_non_valida');

  FETCH = function(u,o){ return u.indexOf('/api/catalogo')===0 ? corrotto(500) : jsonRes(200,{}); };
  await cerca();
  let ris = document.getElementById('risultati').innerHTML;
  check('index: cerca su 500 mostra la frase gentile', ris.indexOf(BV.ERR_FRASI.it.server)>=0, ris.slice(0,200));
  check('index: cerca su 500 NIENTE falso vuoto (waitlist)', ris.indexOf('wl_btn')===-1, '');
  check('index: cerca su 500 niente codice grezzo', ris.indexOf('errore_server_500')===-1, '');

  FETCH = function(u,o){ return u.indexOf('/api/catalogo')===0 ? pende(o) : jsonRes(200,{}); };
  await cerca();
  ris = document.getElementById('risultati').innerHTML;
  check('index: cerca che PENDE -> frase "connessione lenta"', ris.indexOf(BV.ERR_FRASI.it.lenta)>=0, ris.slice(0,200));

  FETCH = function(u,o){ return u.indexOf('/api/catalogo')===0
    ? jsonRes(200,{risultati:[null,{slug:'ok1',titolo:'CasaProva',prezzo_notte_cents:1000,valuta:'EUR'}]})
    : jsonRes(200,{}); };
  await cerca();
  ris = document.getElementById('risultati').innerHTML;
  check('index: FUZZ riga null ignorata, card buona resa', ris.indexOf('CasaProva')>=0, ris.slice(0,150));

  FETCH = function(u,o){ return u.indexOf('/api/catalogo')===0
    ? jsonRes(400,{errore:'<img src=x onerror=alert(1)>'}) : jsonRes(200,{}); };
  await cerca();
  ris = document.getElementById('risultati').innerHTML;
  check('index: FUZZ codice errore ostile ESCAPATO', ris.indexOf('<img')===-1 && ris.indexOf('&lt;img')>=0, ris.slice(0,200));

  const alertsPrima = ALERTS.length;
  FETCH = function(u,o){
    if(u.indexOf('/api/catalogo/')===0) return jsonRes(200,{slug:'x',titolo:'X',prezzo_notte_cents:100,valuta:'EUR',immagini:[]});
    if(u.indexOf('/api/recensioni/')===0) return jsonRes(200,{recensioni:[]});
    if(u.indexOf('/api/concierge/quote')===0) return pende(o);
    return jsonRes(200,{});
  };
  await apri('x');
  const mq = document.getElementById('mQuote').innerHTML;
  check('index: preventivo in timeout NON dice "non disponibile" (bugia)', mq.indexOf(BV.ERR_FRASI.it.lenta)>=0, mq.slice(0,200));
  check('index: apri() senza esplosioni (niente alert imprevisti)', ALERTS.length===alertsPrima, ALERTS.slice(alertsPrima).join('|'));

  for(const l of ['it','en','es','fr','de','pt','ja','zh']){
    LANG = l;
    const f = fraseErrore('rete_lenta');
    check('index: frase "lenta" esiste in '+l, !!f && f!=='rete_lenta', f);
  }
  LANG='it';
}
"""

SCENARI_HOST = r"""
async function __main(){
  await new Promise(function(r){ setTimeout(r,250); });
  let t0=Date.now();
  FETCH = function(u,o){ return pende(o); };
  const g = await getJson('/x');
  check('host: latenza infinita -> rete_lenta', g.errore==='rete_lenta', JSON.stringify(g));
  check('host: timeout presto', (Date.now()-t0)<3000, (Date.now()-t0)+'ms');
  FETCH = function(){ return rifiuta(); };
  check('host: rete giu (getJson)', (await getJson('/x')).errore==='rete_non_raggiungibile');
  const p = await post('/x',{});
  check('host: rete giu (post) -> status 0 + codice', p.status===0 && p.data.errore==='rete_non_raggiungibile', JSON.stringify(p));
  FETCH = function(){ return corrotto(503); };
  check('host: 503 con HTML', (await getJson('/x')).errore==='errore_server_503');
  FETCH = function(){ return jsonRes(200,['a']); };
  check('host: FUZZ array -> risposta_non_valida', (await getJson('/x')).errore==='risposta_non_valida');

  FETCH = function(){ return corrotto(500); };
  await caricaPrenotazioni();
  let box = document.getElementById('pren_lista').innerHTML;
  check('host: prenotazioni su 500 = frase, NON "nessuna prenotazione"',
        box.indexOf(BV.ERR_FRASI.it.server)>=0 && box.indexOf(T('pren_vuoto'))===-1, box.slice(0,200));
  FETCH = function(){ return corrotto(502); };
  await caricaPayout();
  box = document.getElementById('payout_lista').innerHTML;
  check('host: incassi su 502 = frase, NON "nessun incasso"',
        box.indexOf(BV.ERR_FRASI.it.server)>=0 && box.indexOf(T('no_pay'))===-1, box.slice(0,200));
  FETCH = function(u,o){ return pende(o); };
  await caricaRichieste();
  box = document.getElementById('richieste_lista').innerHTML;
  check('host: richieste (24h!) in timeout = frase, NON "nessuna richiesta"',
        box.indexOf(BV.ERR_FRASI.it.lenta)>=0 && box.indexOf(T('no_req'))===-1, box.slice(0,200));
  FETCH = function(){ return corrotto(200); };
  await caricaConversazioni();
  box = document.getElementById('cv_lista').innerHTML;
  check('host: conversazioni corrotte = frase', box.indexOf(BV.ERR_FRASI.it.risposta)>=0 && box.indexOf(T('cv_vuoto'))===-1, box.slice(0,200));

  CURRENT_SLUG='casa-mia'; MIEI=[{slug:'casa-mia',titolo:'Casa mia',valuta:'EUR'}];
  FETCH = function(){ return corrotto(500); };
  await caricaAlloggiSelettore();
  check('host: selettore su 500 NON azzera la scelta', CURRENT_SLUG==='casa-mia', CURRENT_SLUG);
  check('host: selettore su 500 avvisa (niente "non hai alloggi")',
        document.getElementById('al_vuoto').textContent.indexOf(BV.ERR_FRASI.it.server)>=0,
        document.getElementById('al_vuoto').textContent);

  localStorage.setItem('bookinvip_host_token','tok-vivo');
  FETCH = function(){ return rifiuta(); };
  await verificaSessione();
  check('host: rete giu NON slogga (token intatto)', localStorage.getItem('bookinvip_host_token')==='tok-vivo', '');
  check('host: rete giu avvisa in msgAuth', document.getElementById('msgAuth').textContent.indexOf(BV.ERR_FRASI.it.rete)>=0,
        document.getElementById('msgAuth').textContent);
  FETCH = function(){ return jsonRes(401,{errore:'token_scaduto'}); };
  await verificaSessione();
  check('host: 401 vero slogga', localStorage.getItem('bookinvip_host_token')===null, '');

  const mAuth = document.getElementById('msgAuth');
  mAuth.textContent='';
  FETCH = function(){ return rifiuta(); };
  await authPost('/api/host/login',{email:'a@b.c'},mAuth,'accesso_ok');
  check('host: login con rete giu = frase (prima: silenzio)', mAuth.textContent.indexOf(BV.ERR_FRASI.it.rete)>=0, mAuth.textContent);
  FETCH = function(){ return corrotto(500); };
  await authPost('/api/host/login',{},mAuth,'accesso_ok');
  check('host: login su 500-HTML = frase server', mAuth.textContent.indexOf(BV.ERR_FRASI.it.server)>=0, mAuth.textContent);
  FETCH = function(){ return jsonRes(200,'stringa-nuda'); };
  await authPost('/api/host/login',{},mAuth,'accesso_ok');
  check('host: FUZZ login 200-stringa = risposta non valida', mAuth.textContent.indexOf(BV.ERR_FRASI.it.risposta)>=0, mAuth.textContent);

  FETCH = function(u,o){ return u.indexOf('/api/host/metriche_avanzate')===0 ? jsonRes(200,{metriche:{}}) : jsonRes(200,{}); };
  const bm = document.getElementById('btnMetriche');
  await bm.onclick();
  check('host: FUZZ metriche con campi mancanti -> niente NaN',
        document.getElementById('d_revenue').textContent==='€ 0.00'
        && document.getElementById('d_occ').textContent.indexOf('NaN')===-1,
        document.getElementById('d_revenue').textContent+' / '+document.getElementById('d_occ').textContent);
  check('host: scudo riaperto dopo il giro metriche', bm.disabled===false, '');

  FETCH = function(){ return jsonRes(200,{righe:3}); };   // csv MANCANTE
  await document.getElementById('btnExport').onclick();
  check('host: export senza csv BLOCCATO (niente file "undefined")',
        BLOBS.length===0 && document.getElementById('msgMetriche').textContent.indexOf(BV.ERR_FRASI.it.risposta)>=0,
        document.getElementById('msgMetriche').textContent);
}
"""

SCENARI_ADMIN = r"""
async function __main(){
  await new Promise(function(r){ setTimeout(r,250); });
  document.getElementById('adminkey').value='chiave-prova';

  FETCH = function(){ return corrotto(500); };
  await caricaAlloggi();
  let mm = document.getElementById('msg').textContent;
  check('admin: annunci su 500 NON piu muto', mm.indexOf(BV.ERR_FRASI.it.server)>=0, mm);
  FETCH = function(){ return jsonRes(401,{}); };
  await caricaAlloggi();
  mm = document.getElementById('msg').textContent;
  check('admin: annunci su 401 = "chiave errata"', mm.indexOf(T('err_key'))>=0, mm);

  document.getElementById('tbody').innerHTML='SENTINELLA';
  FETCH = function(){ return corrotto(500); };
  await carica();
  check('admin: prenotazioni su 500 = frase, NIENTE "nessuna prenotazione"',
        document.getElementById('tbody').innerHTML==='SENTINELLA'
        && document.getElementById('msg').textContent.indexOf(BV.ERR_FRASI.it.server)>=0,
        document.getElementById('msg').textContent);
  FETCH = function(){ return jsonRes(200,[]); };
  await carica();
  check('admin: FUZZ corpo array = risposta non valida',
        document.getElementById('msg').textContent.indexOf(BV.ERR_FRASI.it.risposta)>=0,
        document.getElementById('msg').textContent);

  let t0=Date.now();
  FETCH = function(u,o){ return pende(o); };
  await caricaControversie();
  const cl = document.getElementById('ctr_lista').innerHTML;
  check('admin: controversie in timeout = frase lenta, NON "nessuna controversia"',
        cl.indexOf(BV.ERR_FRASI.it.lenta)>=0 && cl.indexOf(T('ctr_nessuna'))===-1, cl.slice(0,200));
  check('admin: timeout presto', (Date.now()-t0)<3000, (Date.now()-t0)+'ms');
}
"""


class TestGuardieStatiche(unittest.TestCase):
    """Guardie senza Node (valgono anche nell'immagine prod): i pattern anti-caos
    non possono sparire in una modifica futura senza far diventare rossa la suite."""

    PAGINE = ('index.html', 'host.html', 'admin.html')

    def _leggi(self, nome):
        with io.open(os.path.join(BASE, nome), encoding='utf-8') as f:
            return f.read()

    def _app(self):
        with io.open(os.path.join(BASE, 'app.js'), encoding='utf-8') as f:
            return f.read()

    def test_app_js_caricato_da_ogni_pagina(self):
        # FONTE UNICA (compartimento 3): ogni pagina carica app.js PRIMA dello script inline
        for p in self.PAGINE:
            html = self._leggi(p)
            self.assertIn('<script src="/app.js', html, p)
            self.assertLess(html.index('<script src="/app.js'), html.index('<script>\n'), p)

    def test_timeout_nella_fonte_unica(self):
        app = self._app()
        self.assertIn('__TEMPO_MAX_MS', app)
        self.assertIn('AbortController', app)
        self.assertIn("'rete_lenta'", app)

    def test_guardia_array_nella_fonte_unica(self):
        # un array JSON valido e' typeof 'object': senza questa guardia torna il falso vuoto
        self.assertIn('Array.isArray', self._app())

    def test_nessuna_fetch_nuda_fuori_dal_wrapper(self):
        # OGNI chiamata deve passare da BV.fetchTempo (=timeout+esito). L'unica
        # `await fetch(` ammessa in tutto il frontend e' quella DENTRO il wrapper in
        # app.js. E' la guardia che ha scovato la fuga del calendario singolo (btnCal).
        for p in self.PAGINE:
            n = self._leggi(p).count('await fetch(')
            self.assertEqual(n, 0, '%s: %d chiamate fetch nude (devono passare da BV.*)' % (p, n))
        self.assertEqual(self._app().count('await fetch('), 1, 'app.js: attesa SOLO quella nel wrapper')

    def test_frasi_gentili_fonte_unica_8_lingue_senza_copie(self):
        app = self._app()
        blocco = app.split('BV.ERR_FRASI = {', 1)[1].split('};', 1)[0]
        for lingua in ('it:', 'en:', 'es:', 'fr:', 'de:', 'pt:', 'ja:', 'zh:'):
            self.assertIn(lingua, blocco, 'app.js ERR_FRASI ' + lingua)
        # ANTI-DUPLICAZIONE: le copie per-pagina delle frasi NON devono tornare
        self.assertEqual(self._leggi('host.html').count('e_rete:'), 0, 'host: copia frasi vietata')
        self.assertEqual(self._leggi('admin.html').count('err_lenta:'), 0, 'admin: copia frasi vietata')
        self.assertNotIn('const ERR_T', self._leggi('index.html'), 'index: copia frasi vietata')

    def test_falsi_vuoti_sbarrati_sulle_card_host(self):
        host = self._leggi('host.html')
        # ogni caricatore di card deve avere il ramo d.errore PRIMA del ramo "vuoto"
        for fn in ('caricaPrenotazioni', 'caricaPayout', 'caricaRichieste',
                   'caricaConversazioni', 'caricaAlloggiSelettore', 'caricaMiei'):
            corpo = host.split('function ' + fn, 1)
            self.assertEqual(len(corpo), 2, fn + ' non trovata')
            self.assertIn('d.errore', corpo[1][:900], fn + ': manca il ramo errore≠vuoto')

    def test_sessione_non_sloggata_da_guasto_rete(self):
        host = self._leggi('host.html')
        corpo = host.split('async function verificaSessione', 1)[1][:1400]
        # il 401 vero slogga; il guasto di rete NO (avvisa e basta)
        self.assertIn("d._http===401", corpo)
        self.assertIn('GUASTO DI RETE', corpo)


@unittest.skipIf(NODE is None, 'Node non installato: caos-rete non eseguibile qui')
class TestCaosRete(unittest.TestCase):
    maxDiff = None

    def _esegui(self, pagina, scenari, minimo_check):
        # come nel browser: PRIMA app.js (fonte unica BV.*), POI lo script della pagina
        with io.open(os.path.join(BASE, 'app.js'), encoding='utf-8') as f:
            app_js = f.read()
        js = PRELUDIO + '\n' + app_js + '\n' + _estrai_js(pagina) + '\n' + scenari + CODA
        fd, path = tempfile.mkstemp(suffix='.js')
        os.close(fd)
        try:
            io.open(path, 'w', encoding='utf-8').write(js)
            r = subprocess.run([NODE, path], capture_output=True, text=True,
                               encoding='utf-8', errors='replace', timeout=90)
            righe = [l[len('CHECK_JSON '):] for l in (r.stdout or '').splitlines()
                     if l.startswith('CHECK_JSON ')]
            checks = [json.loads(x) for x in righe]
            falliti = [c for c in checks if not c.get('ok')]
            self.assertFalse(
                falliti,
                pagina + ' — check falliti:\n' + '\n'.join(
                    '  ✗ %s | %s' % (c['nome'], c.get('note', '')) for c in falliti)
                + '\n--- stderr ---\n' + (r.stderr or '')[:1500])
            self.assertGreaterEqual(len(checks), minimo_check,
                                    pagina + ': harness ha eseguito troppo pochi check (%d)' % len(checks))
            self.assertEqual(r.returncode, 0, pagina + ' exit=' + str(r.returncode) + '\n' + (r.stderr or '')[:1500])
        finally:
            os.remove(path)

    def test_caos_ospite(self):
        self._esegui('index.html', SCENARI_INDEX, 20)

    def test_caos_host(self):
        self._esegui('host.html', SCENARI_HOST, 21)

    def test_caos_admin(self):
        self._esegui('admin.html', SCENARI_ADMIN, 6)


if __name__ == '__main__':
    unittest.main()
