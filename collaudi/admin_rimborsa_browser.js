/**
 * «RIMBORSA» DAL PANNELLO ADMIN, COL BROWSER VERO (pw1, 24/10/2026).
 *
 * Il compito 23 di GML (inventario dei pannelli) ha misurato che i pulsanti dei SOLDI non li
 * preme nessun browser: il clickthrough li salta per regola (VIETATI) e senza prenotazioni la
 * riga col pulsante non esiste nemmeno. Le prove della rotta parlano col server, non con la
 * pagina -- ed e' la pagina che l'admin legge per sapere se i soldi sono tornati all'ospite.
 *
 *   BANCO (STRIPE_FINTO=1): due prenotazioni pagate col webhook firmato, come Stripe vera.
 *     A: col payment_intent -> il rimborso parte e il provider del banco risponde re_test_...
 *     B: SENZA payment_intent -> il server non sa a chi restituire: «da restituire A MANO».
 *   ADMIN (browser): chiave -> Bunker sbloccato -> l'elenco delle prenotazioni -> «Rimborsa»
 *     sulla riga di A, conferma -> la pagina, A COSE FERME, deve dire il rimborso eseguito;
 *     poi «Rimborsa» sulla riga di B -> la pagina, a cose ferme, deve dire l'ERRORE (rosso,
 *     mai «✅ Rimborsato») e il «da restituire A MANO».
 *   SERVER (riletto): le due righe non sono piu' rimborsabili (l'effetto, non solo la frase).
 *   E DUE RISPOSTE FINTE DEL BROWSER (revisione K1 di Kimi, 24/10): un 200 senza `passi_falliti`
 *     non e' un «✅» (C); e se durante il rimborso di B la ricarica degli annunci fallisce (500),
 *     il riquadro dice l'esito E il guasto (D). Dopo i rimborsi veri la riga DEVE sparire dallo
 *     schermo: e' un'asserzione (vista rossa togliendo la ricarica con l'editor).
 *
 * ⛔ «A COSE FERME»: dopo il rimborso il pannello ricarica l'elenco, e la ricarica scrive a sua
 *    volta nello stesso riquadro. Si legge il riquadro DOPO che l'elenco si e' ricaricato,
 *    cioe' quello che l'admin ha davanti quando guarda, non il lampo di un istante.
 * ⛔ SE MANCA LA PREMESSA NON E' VERDE (sbaglio S7): se le righe col pulsante non compaiono, la
 *    prova non ha premuto niente ed esce 2, «NON ESEGUITO».
 * ⛔ COSA NON PROVA, DICHIARATO: la risposta di Stripe vera (il provider del banco risponde
 *    sempre «riuscito»; il rifiuto vero lo provano test_rimborso_arriva_al_gateway e
 *    test_fase83_server); gli altri pulsanti dei soldi (Lo pago io a mano, Storna penale,
 *    Risolvi controversia, Esegui rimborso dovuto: aperti in pw1); le altre 7 lingue.
 *
 * Uso:
 *     STRIPE_SECRET_KEY=sk_test_visivo STRIPE_FINTO=1 python collaudi/avvia_server_visivo.py 8095
 *     BASE_VISIVO=http://127.0.0.1:8095 node collaudi/admin_rimborsa_browser.js
 * Uscita 0 = la pagina dice il vero nei due casi. 1 = si e' rotto, e dove. 2 = non eseguito.
 */
const { chromium } = require('playwright');
const crypto = require('crypto');

const BASE = process.env.BASE_VISIVO || 'http://127.0.0.1:8095';
const WHSEC = process.env.STRIPE_WEBHOOK_SECRET || 'whsec_v';   // il segreto del banco (avvia)
const ADMIN_KEY = 'ak';                                          // avvia_server_visivo.py
const BUNKER_PW = process.env.BUNKER_PASSWORD || 'SuperPw@1';    // avvia_server_visivo.py
const ALLOGGIO = 'attico-roma-visivo';

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

/** Prenota (preventivo + prenotazione) e paga col webhook firmato, come voucher_pin_checkin.js. */
async function prenotaEPaga(ci, co, email, conPaymentIntent) {
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
  const oggetto = { id: 'cs_test_' + h.slice(0, 16),
                    metadata: { riferimento, client_reference_id: riferimento } };
  if (conPaymentIntent) oggetto.payment_intent = 'pi_test_' + h.slice(16, 32);
  const payload = JSON.stringify({ id: 'evt_rimb_' + h.slice(0, 8),
                                   type: 'checkout.session.completed', data: { object: oggetto } });
  const ts = Math.floor(Date.now() / 1000);
  const mac = crypto.createHmac('sha256', WHSEC).update(`${ts}.${payload}`).digest('hex');
  const w = await api('POST', '/api/payments/webhook', payload,
    { 'Stripe-Signature': `t=${ts},v1=${mac}` });
  if (w.status !== 200) return { errore: `webhook ${riferimento}: ${w.status} ${JSON.stringify(w.corpo)}` };
  return { riferimento };
}

(async () => {
  console.log('====== «RIMBORSA» DAL PANNELLO ADMIN (STRIPE_FINTO) ======');
  console.log('server: ' + BASE);
  const A = { ci: fraOggiPiu(30), co: fraOggiPiu(32), nome: 'A (col payment_intent)' };
  const B = { ci: fraOggiPiu(34), co: fraOggiPiu(36), nome: 'B (senza payment_intent)' };
  for (const [p, email, conPi] of [[A, 'ospite.rimb.a@visivo.it', true],
                                   [B, 'ospite.rimb.b@visivo.it', false]]) {
    const esito = await prenotaEPaga(p.ci, p.co, email, conPi);
    if (esito.errore) {
      console.log(`\nNON ESEGUITO: la prenotazione ${p.nome} non e' stata preparata (${esito.errore})`);
      process.exit(2);
    }
    p.rif = esito.riferimento;
    console.log(`[BANCO] ${p.nome} prenotata e pagata: ${p.rif} ${p.ci} -> ${p.co}`);
  }

  const sacco = [];
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const p = await ctx.newPage();
  p.on('pageerror', e => sacco.push(`pagina: ${String(e).slice(0, 160)}`));
  p.on('dialog', d => d.accept());          // «Rimborsare e liberare le date …?» -> Si'

  // L'ingresso vero dell'admin (come clickthrough_pannelli.js), poi il Bunker dal suo riquadro.
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
  // stessa scheda: la sessione del Bunker vive in sessionStorage e torna con lei
  await p.goto(BASE + '/admin.html', { waitUntil: 'networkidle', timeout: 20000 });
  if (!(await p.inputValue('#adminkey').catch(() => ''))) await p.fill('#adminkey', ADMIN_KEY);

  const riga = q => `#tbody button.danger[data-ci="${q.ci}"][data-co="${q.co}"]`;
  const carica = async () => {
    await p.click('#btnCarica');
    return p.waitForSelector(riga(A), { state: 'visible', timeout: 20000 }).then(() => true).catch(() => false);
  };
  if (!(await carica()) || !(await p.$(riga(B)))) {
    console.log('\nNON ESEGUITO: le righe con «Rimborsa» delle due prenotazioni pagate non sono comparse.');
    await browser.close();
    process.exit(2);
  }
  console.log('[ADMIN] le due righe con «Rimborsa» sono nell\'elenco');

  const [okTesto, nPren, err500] = await p.evaluate(
    () => [T('rimb_ok'), T('n_pren'), fraseErrore('errore_server_500')]);
  // Preme e aspetta che il pannello si FERMI: la rete tace, poi si legge quello che l'admin ha
  // davanti. Con `sparisce` la riga DEVE essere sparita dallo schermo (l'elenco ricaricato non
  // la ha piu' rimborsabile): e' un'asserzione, non un'attesa (rilievo 2 di Kimi, K1).
  const premi = async (q, sparisce) => {
    await p.click(riga(q));
    await p.waitForLoadState('networkidle').catch(() => {});
    if (sparisce) {
      const via = await p.waitForSelector(riga(q), { state: 'detached', timeout: 20000 })
        .then(() => true).catch(() => false);
      esigi(via, `dopo «Rimborsa» su ${q.nome} la riga col pulsante e' ancora sullo schermo`);
    }
    await p.waitForTimeout(800);
    return p.evaluate(() => {
      const m = document.getElementById('msg');
      return { testo: (m.textContent || '').trim(), classe: m.className };
    });
  };

  // C) RISPOSTA 200 MALFORMATA (rilievo 6 di Kimi): senza `passi_falliti` la pagina non sa se i
  //    soldi sono partiti, e allora NON e' un «✅». Risposta finta del browser: il server non la
  //    vede, la riga resta e il giro vero di A sotto resta il primo.
  await p.route('**/api/admin/rimborso', r => r.fulfill({
    status: 200, contentType: 'application/json', body: '{}' }));
  const c = await premi(A, false);
  await p.unroute('**/api/admin/rimborso');
  console.log(`[ADMIN] risposta finta 200 {} -> [${c.classe}] ${JSON.stringify(c.testo)}`);
  esigi(c.classe.split(' ').includes('err') && !c.testo.startsWith(okTesto),
    `con una risposta 200 senza passi_falliti la pagina dice [${c.classe}] ${JSON.stringify(c.testo)}`);
  if (!(await p.$(riga(A)))) {
    console.log('\nNON ESEGUITO: dopo la risposta finta la riga di A non c\'e\' piu\'.');
    await browser.close(); process.exit(2);
  }

  const a = await premi(A, true);
  console.log(`[ADMIN] dopo «Rimborsa» su ${A.nome}: [${a.classe}] ${JSON.stringify(a.testo)}`);
  esigi(a.classe.split(' ').includes('ok') && a.testo.startsWith(okTesto),
    `rimborso RIUSCITO, ma a cose ferme la pagina non dice ${JSON.stringify(okTesto)}: `
    + `[${a.classe}] ${JSON.stringify(a.testo)}`
    + (a.testo.endsWith(nPren) ? ' (l\'esito e\' stato coperto dalla ricarica dell\'elenco)' : ''));
  esigi(a.testo.includes('re_test_'),
    `rimborso RIUSCITO, ma la pagina non mostra l'identificativo del rimborso: ${JSON.stringify(a.testo)}`);

  // D) LA RICARICA CHE FALLISCE (rilievi 4 e 5 di Kimi): durante il rimborso vero di B l'elenco
  //    degli annunci risponde 500. L'admin deve leggere TUTTE E DUE le cose: l'esito del
  //    rimborso e il guasto della ricarica -- nessuna delle due copre l'altra.
  await p.route('**/api/admin/alloggi**', r => r.fulfill({
    status: 500, contentType: 'application/json', body: '{"errore":"finto"}' }));
  const b = await premi(B, true);
  await p.unroute('**/api/admin/alloggi**');
  console.log(`[ADMIN] dopo «Rimborsa» su ${B.nome}: [${b.classe}] ${JSON.stringify(b.testo)}`);
  esigi(b.testo.includes(err500),
    `la ricarica degli annunci e' fallita (500) ma la pagina non lo dice: ${JSON.stringify(b.testo)}`);
  esigi(b.classe.split(' ').includes('err'),
    `i soldi NON sono tornati all'ospite, ma a cose ferme il riquadro e' verde: `
    + `[${b.classe}] ${JSON.stringify(b.testo)}`);
  esigi(!b.testo.startsWith(okTesto),
    `i soldi NON sono tornati all'ospite, ma la pagina dice ${JSON.stringify(okTesto)}`);
  esigi(/A MANO/.test(b.testo),
    `i soldi NON sono tornati all'ospite, ma la pagina non dice di restituirli a mano: `
    + JSON.stringify(b.testo)
    + (b.testo.endsWith(nPren) ? ' (l\'esito e\' stato coperto dalla ricarica dell\'elenco)' : ''));

  // L'EFFETTO: il server, riletto, non offre piu' il rimborso su nessuna delle due.
  const el = await api('GET', '/api/admin/prenotazioni?page=1&limit=100', undefined, { 'X-Admin-Key': ADMIN_KEY });
  const righe = ((el.corpo && el.corpo.prenotazioni) || []).filter(Boolean);
  for (const q of [A, B]) {
    const r = righe.find(x => x.check_in === q.ci && x.check_out === q.co);
    console.log(`[SERVER] ${q.nome}: stato=${r && r.stato} rimborsabile=${r && r.rimborsabile}`);
    esigi(r && r.rimborsabile !== true, `il server offre ancora il rimborso su ${q.nome}: ${JSON.stringify(r)}`);
  }
  await fine(browser, sacco);
})().catch(e => { console.error('CRASH del percorso:', e); process.exit(2); });

async function fine(browser, sacco) {
  sacco.forEach(e => guasti.push(e));
  await browser.close();
  console.log('\n====== ESITO ======');
  if (!guasti.length) {
    console.log('RIMBORSA: la pagina dice il vero, a rimborso riuscito e a soldi da restituire a mano.');
    process.exit(0);
  }
  console.log(`PERCORSO INTERROTTO — ${guasti.length} guasto/i:`);
  guasti.forEach(g => console.log('  - ' + g));
  process.exit(1);
}
