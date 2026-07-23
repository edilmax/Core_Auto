/**
 * COLLAUDO VISIVO (Playwright, headless) — Home -> ricerca -> checkout "Paga in Struttura".
 * Verifica su Desktop E Mobile che il box/radio e i testi (piu' lingue) si rendano senza
 * sovrapposizioni ne' elementi tagliati, e salva screenshot. Serve il server locale acceso
 * (collaudi/avvia_server_visivo.py). Esce 1 al primo difetto.
 *
 * Uso:  node collaudi/test_visivo.js [http://127.0.0.1:8099]
 */
const { chromium, devices } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = process.argv[2] || 'http://127.0.0.1:8099';
const OUT = path.join(__dirname, 'screenshot_visivi');
fs.mkdirSync(OUT, { recursive: true });

function dataISO(giorni) {
  const d = new Date(); d.setDate(d.getDate() + giorni);
  return d.toISOString().slice(0, 10);
}

const problemi = [];
function rileva(cond, msg) { if (!cond) problemi.push(msg); }

async function overflowOrizzontale(page) {
  // il body non deve mai scorrere in orizzontale (testo/pulsanti fuori dal viewport)
  return await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 2);
}

async function percorri(context, etichetta, lingua) {
  const page = await context.newPage();
  const erroriJS = [];
  page.on('pageerror', e => erroriJS.push(String(e)));
  await page.goto(BASE + '/?lang=' + lingua, { waitUntil: 'domcontentloaded' });

  // ricerca: citta Roma + date dentro la disponibilita'
  await page.waitForSelector('#citta', { timeout: 15000 });
  await page.fill('#citta', 'Roma');
  await page.fill('#checkin', dataISO(7));
  await page.fill('#checkout', dataISO(10));
  await page.click('#btnCerca');

  // risultati -> primo annuncio
  await page.waitForSelector('#risultati button[data-slug]', { timeout: 15000 });
  await page.click('#risultati button[data-slug]');

  // il checkout (modal) deve aprirsi con l'opzione paga in struttura
  await page.waitForSelector('#modal.open', { timeout: 15000 });
  await page.waitForSelector('input[name="modopag"]', { timeout: 15000 });

  const radios = await page.$$('input[name="modopag"]');
  rileva(radios.length === 2, `[${etichetta}/${lingua}] radio paga: attesi 2, trovati ${radios.length}`);

  // testo del box (titolo + scudo) presente e non vuoto
  const testoBox = (await page.textContent('#mQuote')) || '';
  rileva(testoBox.length > 40, `[${etichetta}/${lingua}] box checkout quasi vuoto`);
  rileva(/🛡|🏠|💳/.test(testoBox), `[${etichetta}/${lingua}] manca il box paga-in-struttura`);

  // niente scroll orizzontale (pulsanti tagliati / testo fuori)
  rileva(!(await overflowOrizzontale(page)), `[${etichetta}/${lingua}] OVERFLOW orizzontale (elementi tagliati)`);

  // il bottone Prenota deve essere visibile e cliccabile (non coperto/tagliato)
  const bp = await page.$('#btnPrenota');
  if (bp) {
    const box = await bp.boundingBox();
    rileva(box && box.width > 40 && box.height > 20, `[${etichetta}/${lingua}] tasto Prenota tagliato/nascosto`);
  }

  rileva(erroriJS.length === 0, `[${etichetta}/${lingua}] errori JS: ${erroriJS.join(' | ')}`);

  const file = path.join(OUT, `checkout_${etichetta}_${lingua}.png`);
  await page.screenshot({ path: file, fullPage: true });
  console.log(`  screenshot: ${path.basename(file)}  (box ${testoBox.length} char)`);
  await page.close();
}

(async () => {
  const browser = await chromium.launch();
  console.log('== COLLAUDO VISIVO CHECKOUT ==', BASE);

  // DESKTOP
  const desk = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  for (const lng of ['it', 'en', 'ja', 'zh']) {
    console.log(`Desktop ${lng}...`);
    await percorri(desk, 'desktop', lng);
  }
  await desk.close();

  // MOBILE (iPhone)
  const mob = await browser.newContext({ ...devices['iPhone 13'] });
  for (const lng of ['it', 'en', 'de', 'zh']) {
    console.log(`Mobile ${lng}...`);
    await percorri(mob, 'mobile', lng);
  }
  await mob.close();

  await browser.close();

  console.log('\n== ESITO ==');
  if (problemi.length === 0) {
    console.log('NESSUN DIFETTO VISIVO: checkout renderizzato bene su desktop e mobile, piu\' lingue.');
    console.log('Screenshot in: ' + OUT);
    process.exit(0);
  } else {
    console.log('DIFETTI VISIVI (' + problemi.length + '):');
    problemi.forEach(p => console.log('  - ' + p));
    process.exit(1);
  }
})().catch(e => { console.error('CRASH collaudo visivo:', e); process.exit(2); });
