/**
 * COLLAUDO VISIVO MULTI-RUOLO (Playwright, headless) — Ospite, Host, Admin, Super Admin.
 * Per ogni ruolo: verifica il GATE dei permessi (pagina riservata -> redirect al login senza
 * sessione) e, dov'e' possibile, autentica e verifica il RENDERING della schermata (desktop +
 * mobile), scatta screenshot, e controlla: nessun overflow orizzontale, nessun errore JS.
 * Serve il server locale (collaudi/avvia_server_visivo.py, che espone host@visivo.it/password1,
 * admin key 'ak'). Esce 1 al primo difetto visivo o di permessi.
 *
 * Uso:  node collaudi/test_visivo_ruoli.js [http://127.0.0.1:8099]
 */
const { chromium, devices } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = process.argv[2] || 'http://127.0.0.1:8099';
const OUT = path.join(__dirname, 'screenshot_visivi');
fs.mkdirSync(OUT, { recursive: true });
const problemi = [];
const R = (cond, msg) => { if (!cond) problemi.push(msg); };

function dISO(g) { const d = new Date(); d.setDate(d.getDate() + g); return d.toISOString().slice(0, 10); }
async function overflow(page) {
  return await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 2);
}
async function shot(page, nome) {
  const f = path.join(OUT, nome + '.png');
  await page.screenshot({ path: f, fullPage: true });
  return path.basename(f);
}

// GATE: senza sessione, una pagina riservata NON deve mostrarsi (redirect a /entra-*)
async function verificaGate(ctx, pagina, etichetta) {
  const page = await ctx.newPage();
  await page.goto(BASE + '/' + pagina, { waitUntil: 'domcontentloaded' });
  const url = page.url();
  R(/\/entra-/.test(url) || !url.endsWith(pagina),
    `[GATE/${etichetta}] ${pagina} accessibile SENZA login (permesso non protetto): ${url}`);
  await page.close();
}

// carica una schermata autenticata e controlla rendering
async function verificaSchermata(ctx, url, etichetta, viewport, attesoNelBody) {
  const page = await ctx.newPage();
  const errs = [];
  page.on('pageerror', e => errs.push(String(e)));
  await page.goto(BASE + url, { waitUntil: 'networkidle' }).catch(() => {});
  const body = (await page.textContent('body').catch(() => '')) || '';
  R(!(await overflow(page)), `[${etichetta}/${viewport}] overflow orizzontale (elementi tagliati)`);
  R(errs.length === 0, `[${etichetta}/${viewport}] errori JS: ${errs.join(' | ')}`);
  if (attesoNelBody) R(body.includes(attesoNelBody) || body.length > 60,
    `[${etichetta}/${viewport}] schermata vuota/non renderizzata`);
  const f = await shot(page, `ruolo_${etichetta}_${viewport}`);
  console.log(`  ${etichetta}/${viewport}: ${f}  (body ${body.length} char)`);
  await page.close();
}

async function perViewport(browser, nomeVp, opts) {
  console.log(`\n== VIEWPORT ${nomeVp} ==`);

  // 1) OSPITE — checkout con Paga in Struttura
  {
    const ctx = await browser.newContext(opts);
    const page = await ctx.newPage();
    const errs = []; page.on('pageerror', e => errs.push(String(e)));
    await page.goto(BASE + '/?lang=it', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#citta', { timeout: 15000 });
    await page.fill('#citta', 'Roma'); await page.fill('#checkin', dISO(7)); await page.fill('#checkout', dISO(10));
    await page.click('#btnCerca');
    await page.waitForSelector('#risultati button[data-slug]', { timeout: 15000 });
    await page.click('#risultati button[data-slug]');
    await page.waitForSelector('input[name="modopag"]', { timeout: 15000 });
    const radios = await page.$$('input[name="modopag"]');
    R(radios.length === 2, `[OSPITE/${nomeVp}] radio paga attesi 2, trovati ${radios.length}`);
    R(!(await overflow(page)), `[OSPITE/${nomeVp}] overflow checkout`);
    R(errs.length === 0, `[OSPITE/${nomeVp}] errori JS ospite`);
    console.log(`  OSPITE/${nomeVp}: ${await shot(page, 'ruolo_ospite_' + nomeVp)}`);
    await page.close(); await ctx.close();
  }

  // 2) GATE dei permessi — le riservate NON si aprono senza login
  {
    const ctx = await browser.newContext(opts);
    for (const [p, e] of [['host.html', 'host'], ['admin.html', 'admin'], ['bunker.html', 'bunker']])
      await verificaGate(ctx, p, e);
    await ctx.close();
  }

  // 3) ADMIN — login con chiave -> admin.html
  {
    const ctx = await browser.newContext(opts);
    const r = await ctx.request.post(BASE + '/api/admin/login', { headers: { 'X-Admin-Key': 'ak' } });
    R(r.ok(), `[ADMIN/${nomeVp}] login admin fallito (${r.status()})`);
    await verificaSchermata(ctx, '/admin.html', 'admin', nomeVp, null);
    await ctx.close();
  }

  // 4) HOST — login email/password -> token + cookie -> host.html
  {
    const ctx = await browser.newContext(opts);
    const r = await ctx.request.post(BASE + '/api/host/login',
      { data: { email: 'host@visivo.it', password: 'password1' } });
    R(r.ok(), `[HOST/${nomeVp}] login host fallito (${r.status()})`);
    let tok = ''; try { tok = (await r.json()).token || ''; } catch (e) {}
    const page = await ctx.newPage();
    const errs = []; page.on('pageerror', e => errs.push(String(e)));
    await page.addInitScript(t => { try { localStorage.setItem('bookinvip_host_token', t); } catch (e) {} }, tok);
    await page.goto(BASE + '/host.html', { waitUntil: 'networkidle' }).catch(() => {});
    R(page.url().endsWith('host.html'), `[HOST/${nomeVp}] host.html non caricata (gate?) : ${page.url()}`);
    R(!(await overflow(page)), `[HOST/${nomeVp}] overflow pannello host`);
    R(errs.length === 0, `[HOST/${nomeVp}] errori JS host: ${errs.join(' | ')}`);
    console.log(`  HOST/${nomeVp}: ${await shot(page, 'ruolo_host_' + nomeVp)}  (${tok ? 'token ok' : 'no token'})`);
    await page.close(); await ctx.close();
  }

  // 5) SUPER ADMIN (bunker) — pagina di login 2FA renderizzata (auth 2FA non automatizzabile qui)
  {
    const ctx = await browser.newContext(opts);
    await verificaSchermata(ctx, '/entra-bunker', 'bunker_login', nomeVp, null);
    await ctx.close();
  }
}

(async () => {
  const browser = await chromium.launch();
  console.log('== COLLAUDO VISIVO MULTI-RUOLO ==', BASE);
  await perViewport(browser, 'desktop', { viewport: { width: 1280, height: 900 } });
  await perViewport(browser, 'mobile', { ...devices['iPhone 13'] });
  await browser.close();

  console.log('\n== ESITO MULTI-RUOLO ==');
  if (problemi.length === 0) {
    console.log('NESSUN DIFETTO: 4 ruoli renderizzati bene (desktop+mobile), gate permessi OK.');
    process.exit(0);
  } else {
    console.log('DIFETTI (' + problemi.length + '):'); problemi.forEach(p => console.log('  - ' + p));
    process.exit(1);
  }
})().catch(e => { console.error('CRASH multi-ruolo:', e); process.exit(2); });
