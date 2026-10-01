/**
 * IL CHECK-IN DELLA QUESTURA, COMPILATO COME LO COMPILA UN OSPITE — browser vero (1 ottobre).
 *
 * In Italia il check-in raccoglie la schedina di Alloggiati Web (art. 109 TULPS): la rotta
 * rifiuta nome e documento soltanto, quindi il modulo della pagina e' la meta' che conta.
 * Le prove della suite guardano l'HTML; qui si guarda se un ospite riesce DAVVERO a usarlo:
 * le tendine si riempiono dalle tabelle ufficiali, il comune si trova scrivendo le prime
 * lettere, un errore dice quale ospite e quale campo, e alla fine il check-in risulta fatto.
 *
 *   OSPITE: cerca Roma -> prenota ONLINE (pagina di pagamento finta, intercettata) ->
 *   L'INCASSO: webhook Stripe firmato, come voucher_pin_checkin.js (STRIPE_FINTO=1) ->
 *   OSPITE apre il voucher: (1) manda il modulo quasi vuoto -> rifiuto che nomina l'ospite 1;
 *   (2) compila capofamiglia (nato a Roma, carta d'identita' rilasciata a Roma) e familiare
 *   (nata in Francia) -> «✓»; (3) il server dice check-in completato.
 *
 * ⛔ COSA NON PROVA, DICHIARATO: il file per l'host e la cancellazione dei dati (in suite,
 *    test_checkin_questura.py); la pagina Stripe vera (D6). Notti +20..+22: non toccano le
 *    unita' dei gemelli (+7..+10, +14..+17).
 *
 * Uso:
 *     STRIPE_SECRET_KEY=sk_test_visivo STRIPE_FINTO=1 python collaudi/avvia_server_visivo.py 8095
 *     BASE_VISIVO=http://127.0.0.1:8095 node collaudi/checkin_questura_browser.js
 * Uscita 0 = un ospite completa il check-in della Questura. Uscita 1 = non ci riesce.
 */
const { chromium } = require('playwright');
const crypto = require('crypto');

const BASE = process.env.BASE_VISIVO || 'http://127.0.0.1:8095';
const WHSEC = process.env.STRIPE_WEBHOOK_SECRET || 'whsec_v';   // il segreto del banco (avvia)
const FINTO = 'https://pagamento.finto/';
const ITALIA = '100000100', FRANCIA = '100000215';

const guasti = [];
const esigi = (cond, msg) => { if (!cond) guasti.push(msg); return !!cond; };

function fraOggiPiu(giorni) {
  const d = new Date();
  d.setDate(d.getDate() + giorni);
  return d.toISOString().slice(0, 10);
}

function sorveglia(page, dove, sacco) {
  page.on('pageerror', e => sacco.push(`${dove}: ${String(e).slice(0, 160)}`));
  page.on('console', m => {
    if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) {
      sacco.push(`${dove} (console): ${m.text().slice(0, 160)}`);
    }
  });
}

function firmaStripe(payload, secret, ts) {
  const mac = crypto.createHmac('sha256', secret).update(`${ts}.${payload}`).digest('hex');
  return `t=${ts},v1=${mac}`;
}

/** Scrive le prime lettere, aspetta che la tendina proponga il comune, e lo sceglie. */
async function scegliComune(page, campo, lista, lettere, voce) {
  await page.fill(campo, lettere);
  const proposto = await page.waitForFunction(([l, v]) => [...document.querySelectorAll(l + ' option')]
    .some(o => o.value === v), [lista, voce], { timeout: 15000 }).then(() => true).catch(() => false);
  esigi(proposto, `scrivendo "${lettere}" la tendina ${lista} non propone ${voce}`);
  await page.fill(campo, voce);
}

(async () => {
  console.log('====== IL CHECK-IN DELLA QUESTURA, COME LO COMPILA UN OSPITE ======');
  console.log('server: ' + BASE);
  const sacco = [];
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  sorveglia(page, 'OSPITE', sacco);

  let corpoBook = null;
  await page.route('**/api/concierge/book', async (route) => {
    const risposta = await route.fetch();
    try { corpoBook = await risposta.json(); } catch (e) { corpoBook = null; }
    await route.fulfill({ response: risposta });
  });
  await page.route(`${FINTO}**`, (route) => route.fulfill({
    status: 200, contentType: 'text/html; charset=utf-8',
    body: '<html><body><h1>PAGAMENTO SIMULATO (banco)</h1></body></html>',
  }));

  await page.goto(`${BASE}/?lang=it`, { waitUntil: 'domcontentloaded', timeout: 20000 });
  await page.waitForSelector('#citta', { timeout: 20000 });
  await page.fill('#citta', 'Roma');
  await page.fill('#checkin', fraOggiPiu(20));
  await page.fill('#checkout', fraOggiPiu(22));
  await page.click('#btnCerca');
  const trovato = await page.waitForSelector('#risultati button[data-slug]', { timeout: 20000 })
    .then(() => true).catch(() => false);
  if (!esigi(trovato, 'la ricerca "Roma" non ha restituito annunci')) { await browser.close(); chiudi(sacco); }
  await page.click('#risultati button[data-slug]');
  await page.waitForSelector('#modal.open', { timeout: 20000 });
  await page.click('#btnPrenota');
  await page.waitForSelector('#bkEmail', { timeout: 20000 });
  await page.fill('#bkEmail', 'ospite.questura@visivo.it');
  await page.click('#bkGo');
  await page.waitForURL(`${FINTO}*`, { timeout: 20000 }).catch(() => {});
  if (!esigi(corpoBook && corpoBook.riferimento && corpoBook.voucher_token,
    `la prenotazione non ha consegnato riferimento e voucher: ${JSON.stringify(corpoBook).slice(0, 200)}`)) {
    await browser.close(); chiudi(sacco);
  }
  const { riferimento, voucher_token: voucherToken } = corpoBook;

  // L'INCASSO: il webhook firmato con la sessione che il banco ha creato (come il gemello del PIN)
  const h = crypto.createHash('sha256').update(riferimento).digest('hex');
  const payload = JSON.stringify({ id: 'evt_q_' + h.slice(0, 8), type: 'checkout.session.completed',
    data: { object: { id: 'cs_test_' + h.slice(0, 16), payment_intent: 'pi_test_' + h.slice(16, 32),
             metadata: { riferimento, client_reference_id: riferimento } } } });
  const risp = await fetch(`${BASE}/api/payments/webhook`, { method: 'POST',
    headers: { 'Content-Type': 'application/json',
               'Stripe-Signature': firmaStripe(payload, WHSEC, Math.floor(Date.now() / 1000)) },
    body: payload });
  esigi(risp.status === 200, `il webhook di pagamento ha risposto ${risp.status}`);
  console.log(`[PAGAMENTO] ${riferimento}: webhook HTTP ${risp.status}`);

  const urlVoucher = `${BASE}/voucher/${encodeURIComponent(voucherToken)}?lang=it`;
  const v = await ctx.newPage();
  sorveglia(v, 'VOUCHER', sacco);

  // (0) SPENTO DI SERIE (decisione del fondatore, 1/10): il voucher non chiede niente
  await v.goto(urlVoucher, { waitUntil: 'domcontentloaded', timeout: 20000 });
  esigi((await v.$('#qBox')) === null && (await v.$('#ckBox')) === null,
    'a interruttore spento il voucher mostra un modulo di check-in');
  console.log('[SPENTO] il voucher non chiede i dati degli ospiti');

  // IL PULSANTE DEL BUNKER: si entra come super-admin e si preme «Accendi»
  const bctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const b = await bctx.newPage();
  sorveglia(b, 'BUNKER', sacco);
  b.on('dialog', d => d.accept(d.type() === 'prompt' ? 'collaudo del check-in' : undefined));
  const premi = async (tasto, atteso) => {
    await b.click(tasto);
    const ok = await b.waitForFunction(t => (document.getElementById('ckStato').textContent || '')
      .includes(t), atteso, { timeout: 15000 }).then(() => true).catch(() => false);
    esigi(ok, `premuto ${tasto}, lo stato nel bunker non dice «${atteso}»`);
  };
  await b.goto(BASE + '/entra-bunker', { waitUntil: 'networkidle', timeout: 20000 });
  await b.fill('#k', 'ak');
  await b.fill('#c', 'SuperPw@1');
  await Promise.all([b.waitForNavigation({ waitUntil: 'networkidle', timeout: 20000 }).catch(() => {}),
    b.click('#go')]);
  const scheda = await b.waitForSelector('#btnCkOn', { timeout: 20000 }).then(() => true).catch(() => false);
  if (!esigi(scheda, 'nel bunker non c\'e\' il pulsante del check-in online')) { await browser.close(); chiudi(sacco); }
  await premi('#btnCkOn', 'ACCESO');
  console.log('[BUNKER] check-in online ACCESO col pulsante');

  await v.goto(urlVoucher, { waitUntil: 'domcontentloaded', timeout: 20000 });
  const modulo = await v.waitForSelector('#qBox', { timeout: 15000 }).then(() => true).catch(() => false);
  if (!esigi(modulo, 'il voucher pagato di un alloggio in Italia non mostra il modulo della Questura')) {
    await browser.close(); chiudi(sacco);
  }
  const tendine = await v.waitForFunction(() => document.querySelectorAll('#qStato option').length > 100
    && document.querySelectorAll('#qTdoc option').length > 5, null, { timeout: 15000 })
    .then(() => true).catch(() => false);
  esigi(tendine, 'le tendine di stati e documenti non si sono riempite dalle tabelle ufficiali');
  esigi(await v.isHidden('#qComune'), 'il comune di nascita e\' visibile prima di scegliere l\'Italia');

  // (1) IL RIFIUTO DEVE DIRE CHI E COSA: solo cognome e nome
  await v.fill('#qCog', 'Rossi');
  await v.fill('#qNom', 'Mario');
  await v.click('#qSend');
  await v.waitForFunction(() => (document.getElementById('qMsg').textContent || '').length > 0,
    null, { timeout: 15000 }).catch(() => {});
  const rifiuto = (await v.textContent('#qMsg')) || '';
  esigi(/Ospite 1/.test(rifiuto) && !rifiuto.includes('✓'),
    `il modulo quasi vuoto non e' stato rifiutato nominando l'ospite: ${JSON.stringify(rifiuto)}`);
  esigi(/Sesso|Data di nascita|Stato di nascita/.test(rifiuto),
    `il rifiuto non nomina i campi da sistemare con le parole del modulo: ${JSON.stringify(rifiuto)}`);
  console.log(`[RIFIUTO] ${rifiuto.slice(0, 140)}`);

  // (2) LA FAMIGLIA COMPLETA, CON DATI A CASO (il fondatore: «mettili a caso i dati»):
  //     capofamiglia nato a Roma, familiare nata in Francia; nomi, date e numero inventati
  const seme = Number(process.env.SEME || Date.now() % 100000);
  let x = (seme % 2147483646) + 1;                 // Park-Miller: resta esatto nei numeri di JS
  const caso = n => { x = (x * 16807) % 2147483647; return x % n; };
  // ⛔ 16807 e' 7^5: coi semi piccoli la PRIMA estrazione su sette voci da' sempre 0 (visto il
  //    1/10: il primo cognome usciva sempre «Rossi»). Le prime si buttano.
  for (let i = 0; i < 8; i++) caso(2);
  const NOMI = ['Mario', 'Niccolò', 'José', 'Zoë', 'Anne-Marie', 'Sören', 'Ana Sofía', 'Li'];
  const COGNOMI = ['Rossi', "D'Angelo", 'De Luca', 'Müller', 'García López', "O'Brien", 'Ng'];
  const data = () => `${1935 + caso(80)}-${String(1 + caso(12)).padStart(2, '0')}-${String(1 + caso(28)).padStart(2, '0')}`;
  const capo = { cog: COGNOMI[caso(COGNOMI.length)], nom: NOMI[caso(NOMI.length)], nas: data(),
    doc: Array.from({ length: 5 + caso(16) }, () => 'ABCDEFGHJKLMNPQRSTUVWXYZ0123456789'[caso(34)]).join('') };
  const fam = { cog: COGNOMI[caso(COGNOMI.length)], nom: NOMI[caso(NOMI.length)], nas: data() };
  console.log(`[DATI A CASO] seme ${seme}: ${capo.cog} ${capo.nom} ${capo.nas} doc ${capo.doc} · ` +
    `${fam.cog} ${fam.nom} ${fam.nas}  (per rifarlo: SEME=${seme})`);
  await v.fill('#qCog', capo.cog);
  await v.fill('#qNom', capo.nom);
  await v.selectOption('#qSex', caso(2) ? 'm' : 'f');
  await v.fill('#qNas', capo.nas);
  await v.selectOption('#qStato', ITALIA);
  esigi(await v.isVisible('#qComune'), 'scelta l\'Italia, il comune di nascita non compare');
  await scegliComune(v, '#qComune', '#qComuni', 'ROM', 'ROMA (RM)');
  await v.selectOption('#qCitt', ITALIA);
  await v.selectOption('#qTdoc', 'IDENT');
  await v.fill('#qNdoc', capo.doc);
  await v.selectOption('#qLstato', ITALIA);
  await scegliComune(v, '#qLcomune', '#qComuni2', 'ROM', 'ROMA (RM)');
  await v.click('#qAdd');
  esigi(await v.isHidden('#qDoc'), 'dopo il primo ospite il documento si chiede ancora: serve solo a chi guida');
  await v.fill('#qCog', fam.cog);
  await v.fill('#qNom', fam.nom);
  await v.selectOption('#qSex', caso(2) ? 'm' : 'f');
  await v.fill('#qNas', fam.nas);
  await v.selectOption('#qStato', FRANCIA);
  await v.selectOption('#qCitt', FRANCIA);
  await v.click('#qSend');
  await v.waitForFunction(() => (document.getElementById('qMsg').textContent || '').includes('✓'),
    null, { timeout: 15000 }).catch(() => {});
  const esito = (await v.textContent('#qMsg')) || '';
  esigi(esito.includes('✓'), `il check-in completo non e' passato: ${JSON.stringify(esito)}`);
  console.log(`[CHECK-IN] ${esito.slice(0, 140)}`);

  // (3) IL SERVER LO SA
  const st = await (await fetch(`${BASE}/api/checkin/stato?voucher_token=` +
    encodeURIComponent(voucherToken))).json();
  esigi(st && st.completato === true, `il server non da' il check-in per fatto: ${JSON.stringify(st)}`);

  // (4) «SPEGNI» NEL BUNKER: il modulo sparisce dal voucher
  await premi('#btnCkOff', 'spento');
  await v.goto(urlVoucher, { waitUntil: 'domcontentloaded', timeout: 20000 });
  esigi((await v.$('#qBox')) === null, 'rispento dal bunker, il voucher mostra ancora il modulo');
  console.log('[BUNKER] spento col pulsante: il modulo non c\'e\' piu\'');

  await browser.close();
  chiudi(sacco);
})().catch(e => { console.error('CRASH del percorso:', e); process.exit(2); });

function chiudi(sacco) {
  if (sacco.length) {
    guasti.push(`errori JavaScript nel browser (${sacco.length}): ` + [...new Set(sacco)].slice(0, 6).join(' | '));
  }
  console.log('\n====== ESITO ======');
  if (!guasti.length) {
    console.log('CHECK-IN DELLA QUESTURA COMPLETO: tendine piene, comune trovato, rifiuto chiaro, check-in fatto.');
    process.exit(0);
  }
  console.log(`PERCORSO INTERROTTO — ${guasti.length} guasto/i:`);
  guasti.forEach(g => console.log('  - ' + g));
  process.exit(1);
}
