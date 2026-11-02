/**
 * CLICK-THROUGH end-to-end dei 3 PANNELLI (host / admin / super-admin=bunker) su PC e Mobile.
 *
 * Simula un utente reale: login via gate REALE (host email+password, admin chiave, bunker
 * DOPPIA chiave admin+codice), poi clicca OGNI bottone/tab SICURO e registra difetti concreti:
 * errori JavaScript in console, pageerror, richieste fallite, risposte HTTP >=400. I bottoni
 * DISTRUTTIVI/di uscita non si cliccano a raffica (denylist) ma si conta che esistano e siano
 * abilitati (reattivi). Gira su due viewport: PC (1280x800) e Mobile (390x844).
 *
 * Serve il server VISIVO avviato a parte:
 *     python collaudi/avvia_server_visivo.py 8099     (accende anche il bunker: SuperPw@1)
 *     node   collaudi/clickthrough_pannelli.js
 *
 * ATTESI in ambiente OFFLINE (chiave Stripe finta sk_test_visivo): 3 endpoint di integrazione
 * Stripe rispondono 5xx con JSON d'errore PULITO (non crash) -> in produzione (sk_live) danno 200.
 * Sono in allowlist: NON contano come difetto. Ogni altro errore JS/HTTP = ROSSO.
 * Dipendenze: playwright (in package.json). node_modules resta fuori dal repo.
 */
const { chromium } = require('playwright');

const BASE = process.env.BASE_VISIVO || 'http://127.0.0.1:8099';
const VIEWPORTS = { PC: { width: 1280, height: 800 }, Mobile: { width: 390, height: 844 } };
const RUOLI = [
  { nome: 'HOST',        entra: '/entra-host',   fill: { '#em': 'host@visivo.it', '#pw': 'password1' }, panel: '/host' },
  { nome: 'ADMIN',       entra: '/entra-admin',  fill: { '#k': 'ak' },                                   panel: '/admin' },
  { nome: 'SUPER-ADMIN', entra: '/entra-bunker', fill: { '#k': 'ak', '#c': 'SuperPw@1' },                panel: '/bunker' },
];
const VIETATI = /elimina|cancella|delete|rimuov|logout|esci|storna|revoca|blocca|disattiv|sospend|kill|reset|azzera/i;
// esiti ATTESI in un click-through CIECO offline (NON difetti): integrazioni Stripe/OXR senza chiave
// reale (5xx pulito, in prod 200) + submit di form cliccati SENZA input (422 = validazione corretta).
const STRIPE_ATTESI = /\/api\/host\/(carta_link|stripe_link)|\/api\/bunker\/(riconciliazione|cambio_valuta|admin_accounts)/;

async function provaRuolo(browser, ruolo, vpNome, vp) {
  const ctx = await browser.newContext({ viewport: vp });
  const page = await ctx.newPage();
  const jsErr = [], httpErr = [], stripeAttesi = [];
  const isStripe = u => STRIPE_ATTESI.test(u);
  // "Failed to load resource: ... status NNN" e' il log browser di una risposta HTTP non-2xx:
  // gia' tracciata (con allowlist) dall'handler response qui sotto -> non e' un errore JS runtime.
  // Teniamo solo i VERI errori JS (pageerror/ReferenceError/TypeError...).
  page.on('console', m => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) jsErr.push(m.text().slice(0, 140)); });
  page.on('pageerror', e => jsErr.push('PAGEERROR: ' + String(e).slice(0, 140)));
  page.on('response', r => {
    const s = r.status(), u = r.url();
    if (s >= 400 && u.includes('/api/')) (isStripe(u) ? stripeAttesi : httpErr).push(`${s} ${r.request().method()} ${u.replace(BASE, '')}`);
  });

  await page.goto(BASE + ruolo.entra, { waitUntil: 'networkidle', timeout: 20000 });
  for (const [sel, val] of Object.entries(ruolo.fill)) await page.fill(sel, val);
  await Promise.all([page.waitForNavigation({ waitUntil: 'networkidle', timeout: 20000 }).catch(() => {}), page.click('#go')]);
  await page.waitForTimeout(800);
  if (!page.url().includes(ruolo.panel)) {
    await ctx.close();
    return { ruolo: ruolo.nome, vp: vpNome, login: false, url: page.url().replace(BASE, ''), jsErr, httpErr, stripeAttesi, bottoni: 0, cliccati: 0, disabilitati: 0 };
  }
  await page.waitForTimeout(600);

  const bottoni = await page.$$('button, [role="tab"], .tab, [onclick]');
  let cliccati = 0, disabilitati = 0, totVisibili = 0;
  for (const b of bottoni) {
    let testo;
    try {
      if (!(await b.isVisible())) continue;
      totVisibili++;
      testo = ((await b.innerText().catch(() => '')) || (await b.getAttribute('aria-label').catch(() => '')) || (await b.getAttribute('id').catch(() => '')) || '').trim();
      if (await b.isDisabled().catch(() => false)) { disabilitati++; continue; }
    } catch { continue; }
    if (VIETATI.test(testo)) continue;
    try { await b.click({ timeout: 1500 }); cliccati++; await page.waitForTimeout(250); } catch { /* coperto/staccato: non e' un errore JS */ }
    await page.keyboard.press('Escape').catch(() => {});
  }
  await ctx.close();
  return { ruolo: ruolo.nome, vp: vpNome, login: true, bottoni: totVisibili, cliccati, disabilitati, jsErr, httpErr, stripeAttesi };
}

// TELEGRAM SI AGGIORNA DA SOLO (2/11, il fondatore: «Telegram dice sempre Ricollega e due secondi fa
// l'ho collegato»). L'host si collega DAL TELEFONO: la pagina sul PC non riprende il fuoco e restava
// ferma su «Apri questo link». Lo stato del server lo finge `page.route`, l'orologio lo sposta
// Playwright. Due casi: il primo collegamento deve diventare «collegato» senza toccare la pagina;
// chi e' gia' collegato e chiede il link per un telefono nuovo deve leggere che e' collegato.
async function provaTelegramSiAggiorna(browser) {
  const difetti = [];
  for (const giaCollegato of [false, true]) {
    const ctx = await browser.newContext({ viewport: VIEWPORTS.PC });
    const page = await ctx.newPage();
    await page.clock.install();
    await page.addInitScript(() => { window.open = () => null; });
    let collegato = giaCollegato;
    await page.route('**/api/host/collegamenti', r => r.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ telegram: collegato, stripe: 'assente' }) }));
    await page.route('**/api/host/telegram_link', r => r.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ link: 'https://t.me/prova_bot?start=x' }) }));
    await page.goto(BASE + RUOLI[0].entra, { waitUntil: 'networkidle', timeout: 20000 });
    for (const [sel, val] of Object.entries(RUOLI[0].fill)) await page.fill(sel, val);
    await Promise.all([page.waitForNavigation({ waitUntil: 'networkidle', timeout: 20000 }).catch(() => {}), page.click('#go')]);
    await page.waitForTimeout(1500);
    await page.evaluate(() => document.getElementById('btnTgLink').click());
    await page.waitForTimeout(500);
    collegato = true;                      // l'host preme Avvia sul telefono
    // a passi, con un attimo vero in mezzo: in un salto solo da 70 s l'attesa massima di ogni
    // domanda al server scadrebbe prima della risposta, che arriva in tempo vero
    for (let i = 0; i < 6; i++) { await page.clock.runFor(15000); await page.waitForTimeout(400); }
    const [msg, ok] = await page.evaluate(() => [document.getElementById('tg_msg').textContent, T('tg_ok')]);
    const caso = giaCollegato ? 'gia collegato, link per un telefono nuovo' : 'primo collegamento';
    if (!msg.includes(ok)) difetti.push(`${caso}: il messaggio non dice «${ok}» -> «${msg.slice(0, 90)}»`);
    if (giaCollegato && !msg.includes('t.me/prova_bot')) difetti.push(`${caso}: il link per il telefono nuovo e' sparito`);
    await ctx.close();
  }
  return difetti;
}

(async () => {
  const browser = await chromium.launch();
  const risultati = [];
  for (const ruolo of RUOLI) for (const [vpNome, vp] of Object.entries(VIEWPORTS)) risultati.push(await provaRuolo(browser, ruolo, vpNome, vp));
  const difettiTg = await provaTelegramSiAggiorna(browser);
  await browser.close();

  console.log('====== CLICK-THROUGH 3 PANNELLI (PC + Mobile) ======');
  let totJs = 0, totHttp = 0, loginKo = 0;
  for (const r of risultati) {
    if (!r.login) { loginKo++; console.log(`\n[${r.ruolo} / ${r.vp}] LOGIN FALLITO -> ${r.url}`); }
    else console.log(`\n[${r.ruolo} / ${r.vp}] login ok · bottoni visibili=${r.bottoni} cliccati=${r.cliccati} disabilitati=${r.disabilitati}`);
    if (r.stripeAttesi && r.stripeAttesi.length) console.log(`   (info) Stripe assente in test, 5xx ATTESO: ${[...new Set(r.stripeAttesi)].join(', ')}`);
    if (r.jsErr.length) { totJs += r.jsErr.length; console.log(`   JS errori (${r.jsErr.length}):`); [...new Set(r.jsErr)].slice(0, 8).forEach(e => console.log('      - ' + e)); }
    if (r.httpErr.length) { totHttp += r.httpErr.length; console.log(`   HTTP >=400 NON attesi (${r.httpErr.length}):`); [...new Set(r.httpErr)].slice(0, 12).forEach(e => console.log('      - ' + e)); }
    if (r.login && !r.jsErr.length && !r.httpErr.length) console.log('   OK: nessun errore JS, nessuna risposta HTTP errata (oltre agli Stripe attesi)');
  }
  console.log('\n[TELEGRAM] lo stato si aggiorna da solo dopo il clic:');
  if (difettiTg.length) difettiTg.forEach(d => console.log('   ROSSO: ' + d));
  else console.log('   OK: primo collegamento e telefono nuovo dicono «collegato»');
  console.log(`\n====== TOTALE difetti VERI: loginKO=${loginKo} · erroriJS=${totJs} · httpErrati=${totHttp} · telegram=${difettiTg.length} ======`);
  process.exit(loginKo + totJs + totHttp + difettiTg.length > 0 ? 1 : 0);
})();
