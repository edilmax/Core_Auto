/**
 * «↩️ STORNA» LA PENALE DAL PANNELLO ADMIN, COL BROWSER VERO (7/11/2026).
 *
 * `admin_rimborsa_browser.js` dichiarava aperto («COSA NON PROVA») il pulsante «Storna penale»:
 * la catena 6 di `esame_catene_admin.py` prova la ROTTA, ma nessun browser aveva mai premuto il
 * pulsante, scritto il motivo nel riquadro e letto cosa dice la pagina. Il fondatore, 7/11: «se
 * c'e' un riquadro dove scrivi la motivazione e fai lo storno e' un'ottima idea, pero' deve
 * funzionare».
 *
 *   BANCO (STRIPE_FINTO=1): una prenotazione pagata col webhook firmato, poi l'HOST la cancella
 *     dal suo accesso: il server rimborsa l'ospite e scrive la penale (nota di debito).
 *   ADMIN (browser): chiave -> Bunker -> scheda Audit della prenotazione -> «↩️ Storna» sulla
 *     penale, in quattro modi:
 *       1. motivo VUOTO        -> la pagina chiede il motivo, il server non storna niente;
 *       2. riquadro ANNULLATO  -> niente di niente;
 *       3. motivo scritto ma conferma NEGATA -> niente di niente;
 *       4. motivo scritto e conferma DATA -> a cose ferme la pagina dice «stornata», la scheda
 *          si ricarica e la penale risulta 'stornata' SENZA piu' il pulsante.
 *   SERVER (riletto): la penale e' 'stornata' e c'e' UNA nota di credito contraria.
 *
 * ⛔ SE MANCA LA PREMESSA NON E' VERDE (sbaglio S7): se la penale o il pulsante non compaiono,
 *    la prova non ha premuto niente ed esce 2, «NON ESEGUITO».
 * ⛔ COSA NON PROVA, DICHIARATO: la RESTITUZIONE all'host di una penale gia' trattenuta (qui la
 *    penale non e' stata ancora riscossa: l'host del banco non ha altri bonifici maturati); la
 *    cifra la prova la catena 6 di `esame_catene_admin.py` (anello [soldi]). Le altre 7 lingue.
 *
 * Uso:
 *     STRIPE_SECRET_KEY=sk_test_visivo STRIPE_FINTO=1 python collaudi/avvia_server_visivo.py 8095
 *     BASE_VISIVO=http://127.0.0.1:8095 node collaudi/admin_storna_browser.js
 * Uscita 0 = il pulsante fa quello che dice in tutti e quattro i modi. 1 = si e' rotto, e dove.
 * 2 = non eseguito.
 */
const { chromium } = require('playwright');
const crypto = require('crypto');

const BASE = process.env.BASE_VISIVO || 'http://127.0.0.1:8095';
const WHSEC = process.env.STRIPE_WEBHOOK_SECRET || 'whsec_v';   // il segreto del banco (avvia)
const ADMIN_KEY = 'ak';                                          // avvia_server_visivo.py
const BUNKER_PW = process.env.BUNKER_PASSWORD || 'SuperPw@1';    // avvia_server_visivo.py
const ALLOGGIO = 'attico-roma-visivo';
const HOST = { email: 'host@visivo.it', password: 'password1' }; // avvia_server_visivo.py
const MOTIVO = 'prova del browser: penale emessa per sbaglio';

const guasti = [];
const esigi = (cond, msg) => { if (!cond) guasti.push(msg); return !!cond; };

function fraOggiPiu(giorni) {
  const d = new Date();
  d.setDate(d.getDate() + giorni);
  return d.toISOString().slice(0, 10);
}

async function api(metodo, percorso, corpo, intestazioni) {
  const r = await fetch(BASE + percorso, {
    method: metodo,
    headers: Object.assign({ 'Content-Type': 'application/json' }, intestazioni || {}),
    body: corpo === undefined ? undefined : (typeof corpo === 'string' ? corpo : JSON.stringify(corpo)),
  });
  let d = null; try { d = await r.json(); } catch (e) { d = null; }
  return { status: r.status, corpo: d };
}

/** Prenota e paga col webhook firmato, come admin_rimborsa_browser.js. */
async function prenotaEPaga(ci, co, email) {
  const q = await api('POST', '/api/concierge/quote',
    { alloggio_id: ALLOGGIO, check_in: ci, check_out: co, party: 2 });
  if (q.status !== 200 || !q.corpo || !q.corpo.quote_token) {
    return { errore: `preventivo ${ci}: ${q.status} ${JSON.stringify(q.corpo).slice(0, 160)}` };
  }
  const b = await api('POST', '/api/concierge/book',
    { quote_token: q.corpo.quote_token, email, lang: 'it' });
  if (b.status !== 201 || !b.corpo || !b.corpo.riferimento) {
    return { errore: `prenotazione ${ci}: ${b.status} ${JSON.stringify(b.corpo).slice(0, 160)}` };
  }
  const riferimento = b.corpo.riferimento;
  const h = crypto.createHash('sha256').update(riferimento).digest('hex');
  const oggetto = { id: 'cs_test_' + h.slice(0, 16), payment_intent: 'pi_test_' + h.slice(16, 32),
                    metadata: { riferimento, client_reference_id: riferimento } };
  const payload = JSON.stringify({ id: 'evt_storna_' + h.slice(0, 8),
                                   type: 'checkout.session.completed', data: { object: oggetto } });
  const ts = Math.floor(Date.now() / 1000);
  const mac = crypto.createHmac('sha256', WHSEC).update(`${ts}.${payload}`).digest('hex');
  const w = await api('POST', '/api/payments/webhook', payload,
    { 'Stripe-Signature': `t=${ts},v1=${mac}` });
  if (w.status !== 200) return { errore: `webhook ${riferimento}: ${w.status} ${JSON.stringify(w.corpo)}` };
  return { riferimento };
}

/** La scheda audit come la legge il server (la stessa che disegna la pagina). */
async function penaleDi(rif) {
  const a = await api('GET', '/api/admin/audit?id=' + encodeURIComponent(rif), undefined,
    { 'X-Admin-Key': ADMIN_KEY });
  const note = ((a.corpo && a.corpo.note) || []).filter(Boolean);
  return { debito: note.filter(n => n.tipo === 'debito'), credito: note.filter(n => n.tipo === 'credito') };
}

(async () => {
  console.log('====== «STORNA» LA PENALE DAL PANNELLO ADMIN (STRIPE_FINTO) ======');
  console.log('server: ' + BASE);
  const P = { ci: fraOggiPiu(40), co: fraOggiPiu(42) };
  const esito = await prenotaEPaga(P.ci, P.co, 'ospite.storna@visivo.it');
  if (esito.errore) {
    console.log(`\nNON ESEGUITO: la prenotazione non e' stata preparata (${esito.errore})`);
    process.exit(2);
  }
  P.rif = esito.riferimento;
  const login = await api('POST', '/api/host/login', HOST);
  const tok = login.corpo && login.corpo.token;
  const canc = tok ? await api('POST', '/api/host/cancella', { riferimento: P.rif }, { 'X-Host-Token': tok })
                   : { status: login.status, corpo: login.corpo };
  const prima = await penaleDi(P.rif);
  if (canc.status !== 200 || prima.debito.length !== 1 || prima.debito[0].stato === 'stornata') {
    console.log(`\nNON ESEGUITO: l'host non ha cancellato o la penale non e' nata `
      + `(login=${login.status} cancella=${canc.status} ${JSON.stringify(canc.corpo).slice(0, 160)} `
      + `penali=${JSON.stringify(prima.debito).slice(0, 200)})`);
    process.exit(2);
  }
  const ND = prima.debito[0];
  console.log(`[BANCO] ${P.rif} pagata e cancellata dall'host: penale ${ND.nota_id} `
    + `${ND.importo_cents} ${ND.valuta} stato=${ND.stato}`);

  const sacco = [];
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const p = await ctx.newPage();
  p.on('pageerror', e => sacco.push(`pagina: ${String(e).slice(0, 160)}`));
  //  Le risposte ai due riquadri del browser (motivo e conferma), decise per ogni giro.
  let risposte = { motivo: null, conferma: false };
  const visti = [];
  p.on('dialog', d => {
    visti.push(d.type());
    if (d.type() === 'prompt') {
      return risposte.motivo === null ? d.dismiss() : d.accept(risposte.motivo);
    }
    if (d.type() === 'confirm') return risposte.conferma ? d.accept() : d.dismiss();
    return d.accept();
  });

  // L'ingresso vero dell'admin (come admin_rimborsa_browser.js), poi il Bunker dal suo riquadro.
  await p.goto(BASE + '/entra-admin', { waitUntil: 'networkidle', timeout: 20000 });
  await p.fill('#k', ADMIN_KEY);
  await Promise.all([
    p.waitForNavigation({ waitUntil: 'networkidle', timeout: 20000 }).catch(() => {}),
    p.click('#go'),
  ]);
  if (!(await p.inputValue('#adminkey').catch(() => ''))) await p.fill('#adminkey', ADMIN_KEY);
  await p.fill('#bunkerpw', BUNKER_PW);
  await Promise.all([
    p.waitForNavigation({ waitUntil: 'networkidle', timeout: 20000 }).catch(() => {}),
    p.click('#btnBunker'),
  ]);
  const bunker = await p.evaluate(() => !!sessionStorage.getItem('bv_bunker_sess'));
  if (!bunker) {
    console.log('\nNON ESEGUITO: il Bunker non si e\' sbloccato dal pannello admin (nessuna sessione).');
    await browser.close();
    process.exit(2);
  }
  console.log('[ADMIN] Bunker sbloccato');
  await p.goto(BASE + '/admin.html', { waitUntil: 'networkidle', timeout: 20000 });
  if (!(await p.inputValue('#adminkey').catch(() => ''))) await p.fill('#adminkey', ADMIN_KEY);

  // La scheda Audit della prenotazione, dal campo di ricerca e dal bottone 🔬, come fa l'admin.
  const bottone = `#au_card button[onclick^="stornaPenale('${ND.nota_id}'"]`;
  await p.fill('#sr_q', P.rif);
  await p.click('#btnAudit');
  const c_e = await p.waitForSelector(bottone, { state: 'visible', timeout: 20000 })
    .then(() => true).catch(() => false);
  if (!c_e) {
    console.log(`\nNON ESEGUITO: nella scheda Audit di ${P.rif} non e' comparso «Storna» sulla penale.`);
    await browser.close();
    process.exit(2);
  }
  console.log(`[ADMIN] la scheda Audit mostra «Storna» sulla penale ${ND.nota_id}`);

  const [stornataTesto, chiediMotivo] = await p.evaluate(() => [T('au_stornata'), T('au_storna_mot')]);
  const stato = () => p.evaluate(() => (document.getElementById('sr_stat').textContent || '').trim());
  // Preme e aspetta che il pannello si FERMI, poi legge quello che l'admin ha davanti.
  const premi = async () => {
    visti.length = 0;
    await p.evaluate(() => { document.getElementById('sr_stat').textContent = ''; });
    await p.click(bottone);
    await p.waitForLoadState('networkidle').catch(() => {});
    await p.waitForTimeout(800);
    return stato();
  };
  const ancoraIntatta = async (giro) => {
    const s = await penaleDi(P.rif);
    esigi(s.debito.length === 1 && s.debito[0].stato !== 'stornata' && s.credito.length === 0,
      `${giro}: il server ha toccato la penale (${JSON.stringify(s)})`);
    esigi(!!(await p.$(bottone)), `${giro}: il pulsante «Storna» e' sparito senza nessuno storno`);
  };

  // 1. MOTIVO VUOTO: il perche' e' obbligatorio, e lo dice la pagina, non solo il server.
  risposte = { motivo: '   ', conferma: true };
  const t1 = await premi();
  console.log(`[ADMIN] 1. motivo vuoto -> ${JSON.stringify(t1)} riquadri=${visti}`);
  esigi(t1.includes(chiediMotivo) && !t1.includes(stornataTesto),
    `1. col motivo vuoto la pagina dice ${JSON.stringify(t1)} invece di chiedere il motivo`);
  esigi(!visti.includes('confirm'), '1. col motivo vuoto la pagina ha chiesto lo stesso la conferma');
  await ancoraIntatta('1. motivo vuoto');

  // 2. RIQUADRO ANNULLATO: l'admin ci ripensa, non succede niente.
  risposte = { motivo: null, conferma: true };
  const t2 = await premi();
  console.log(`[ADMIN] 2. riquadro annullato -> ${JSON.stringify(t2)} riquadri=${visti}`);
  esigi(!t2.includes(stornataTesto), `2. annullato il riquadro la pagina dice ${JSON.stringify(t2)}`);
  await ancoraIntatta('2. riquadro annullato');

  // 3. MOTIVO SCRITTO, CONFERMA NEGATA: ancora niente.
  risposte = { motivo: MOTIVO, conferma: false };
  const t3 = await premi();
  console.log(`[ADMIN] 3. conferma negata -> ${JSON.stringify(t3)} riquadri=${visti}`);
  esigi(visti.includes('prompt') && visti.includes('confirm'),
    `3. la pagina non ha chiesto motivo E conferma (riquadri visti: ${visti})`);
  esigi(!t3.includes(stornataTesto), `3. con la conferma negata la pagina dice ${JSON.stringify(t3)}`);
  await ancoraIntatta('3. conferma negata');

  // 4. MOTIVO E CONFERMA: lo storno vero.
  risposte = { motivo: MOTIVO, conferma: true };
  const t4 = await premi();
  console.log(`[ADMIN] 4. storno confermato -> ${JSON.stringify(t4)}`);
  esigi(t4.startsWith('✅') && t4.includes(stornataTesto),
    `4. storno confermato, ma a cose ferme la pagina dice ${JSON.stringify(t4)} e non ${JSON.stringify(stornataTesto)}`);
  const via = await p.waitForSelector(bottone, { state: 'detached', timeout: 20000 })
    .then(() => true).catch(() => false);
  esigi(via, '4. dopo lo storno la scheda mostra ancora «Storna» sulla stessa penale');
  const scheda = await p.evaluate(() => (document.getElementById('au_card').textContent || ''));
  esigi(scheda.includes(ND.nota_id) && scheda.includes('stornata'),
    `4. la scheda ricaricata non dice la penale ${ND.nota_id} 'stornata'`);

  // L'EFFETTO: il server, riletto.
  const dopo = await penaleDi(P.rif);
  console.log(`[SERVER] penale=${JSON.stringify(dopo.debito.map(n => [n.nota_id, n.stato]))} `
    + `note di credito=${JSON.stringify(dopo.credito.map(n => [n.nota_id, n.importo_cents]))}`);
  esigi(dopo.debito.length === 1 && dopo.debito[0].stato === 'stornata',
    `il server non ha la penale 'stornata': ${JSON.stringify(dopo.debito)}`);
  esigi(dopo.credito.length === 1 && dopo.credito[0].importo_cents === ND.importo_cents,
    `il server non ha UNA nota di credito della stessa cifra della penale: ${JSON.stringify(dopo.credito)}`);
  await fine(browser, sacco);
})().catch(e => { console.error('CRASH del percorso:', e); process.exit(2); });

async function fine(browser, sacco) {
  sacco.forEach(e => guasti.push(e));
  await browser.close();
  console.log('\n====== ESITO ======');
  if (!guasti.length) {
    console.log('STORNA: il pulsante chiede il motivo, rispetta i ripensamenti e storna davvero.');
    process.exit(0);
  }
  console.log(`PERCORSO INTERROTTO — ${guasti.length} guasto/i:`);
  guasti.forEach(g => console.log('  - ' + g));
  process.exit(1);
}
