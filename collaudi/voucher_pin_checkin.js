/**
 * IL PIN CHE SI APRE SOLO COL PAGAMENTO — il voucher attraversa l'incasso ONLINE (Tappa 3/A3).
 *
 * I gemelli provano gia' le meta' opposte: ospite_checkout_paga.js, ATTO 1 (modo diretto):
 * voucher con 🔒 -- NESSUN PIN senza incasso. Qui si completa il cerchio con un pagamento
 * ONLINE VERO, che sul banco e' possibile grazie a STRIPE_FINTO=1 (avvia_server_visivo:
 * il provider crea sessioni deterministiche senza rete, id derivato dal riferimento).
 *
 *   OSPITE (browser): cerca -> prenota in modo ONLINE -> il server crea la sessione
 *     (cs_test_<hash del riferimento>) e il browser parte verso la pagina di pagamento
 *     -- che Playwright INTERCETTA (route) e soddisfa: il cliente ha "pagato".
 *   L'INCASSO: webhook Stripe firmato (checkout.session.completed con l'id cs_ che il
 *     banco ha creato, il payment_intent, e metadata.riferimento) -- la stessa firma
 *     HMAC di fase87.firma_di_test. Il server salva la sessione, conferma l'hold e il
 *     voucher diventa "pagato". Il browser NON finge niente: il webhook e' la stessa
 *     strada di Stripe vera (handler, firma, archivi identici).
 *   OSPITE riapre il voucher: 🔒 SPARITO, la riga PIN (quella di fase83.riga_pin_voucher,
 *     definita in UN posto solo) porta QUATTRO cifre.
 *   HOST (browser 2): la prenotazione pagata e le date sono nel pannello.
 *
 * ⛔ COSA NON PROVA, DICHIARATO: la pagina Stripe vera (D6: repo pubblico -- qui la pagina
 *    di pagamento e' una stub che il collaudo stesso serve); il pre-check-in digitale
 *    (fase127, provato in suite); il rimborso (oracoli gia' in suite). Le notti sono
 *    +14..+17: non toccano le unita' dei gemelli che usano +7..+10.
 *
 * Uso:
 *     STRIPE_SECRET_KEY=sk_test_visivo STRIPE_FINTO=1 python collaudi/avvia_server_visivo.py 8095
 *     BASE_VISIVO=http://127.0.0.1:8095 node collaudi/voucher_pin_checkin.js
 * Uscita 0 = il PIN si apre solo col pagamento, e l'host lo vede. Uscita 1 = si e' rotto.
 */
const { chromium } = require('playwright');
const crypto = require('crypto');

const BASE = process.env.BASE_VISIVO || 'http://127.0.0.1:8095';
const WHSEC = process.env.STRIPE_WEBHOOK_SECRET || 'whsec_v';   // il segreto del banco (avvia)
const EMAIL_OSPITE = 'ospite.pin@visivo.it';
const CRED_HOST = { em: 'host@visivo.it', pw: 'password1' };
const FINTO = 'https://pagamento.finto/';

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

/** La firma di fase87.firma_di_test, riscritta in Node: t=<ts>,v1=HMAC-SHA256(segreto,"ts.payload"). */
function firmaStripe(payload, secret, ts) {
  const mac = crypto.createHmac('sha256', secret).update(`${ts}.${payload}`).digest('hex');
  return `t=${ts},v1=${mac}`;
}

(async () => {
  console.log(`====== IL PIN SI APRE SOLO COL PAGAMENTO (online, STRIPE_FINTO) ======`);
  console.log('server: ' + BASE);
  const sacco = [];
  const browser = await chromium.launch();

  // L'ospite: cattura la risposta del book (voucher_token + riferimento) e intercetta
  // la pagina di pagamento finta: il "viaggio cliente" resta intero, senza rete vera.
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  sorveglia(page, 'OSPITE', sacco);
  let catturato = null;
  page.on('response', async (r) => {
    if (r.url().includes('/api/concierge/book') && !catturato) {
      try { catturato = await r.json(); } catch (e) { /* la risposta non-JSON non e' nostra */ }
    }
  });
  await page.route(`${FINTO}**`, (route) => route.fulfill({
    status: 200, contentType: 'text/html; charset=utf-8',
    body: '<html><body style="font-family:sans-serif;padding:3rem"><h1>💳 PAGAMENTO SIMULATO (banco)</h1>' +
          '<p>Questa pagina fa la parte di Stripe: il collaudo notifichera\' l\'esito col webhook firmato.</p></body></html>',
  }));

  await page.goto(`${BASE}/?lang=it`, { waitUntil: 'domcontentloaded', timeout: 20000 });
  await page.waitForSelector('#citta', { timeout: 20000 });
  await page.fill('#citta', 'Roma');
  await page.fill('#checkin', fraOggiPiu(14));
  await page.fill('#checkout', fraOggiPiu(17));
  await page.click('#btnCerca');
  const trovato = await page.waitForSelector('#risultati button[data-slug]', { timeout: 20000 })
    .then(() => true).catch(() => false);
  if (!esigi(trovato, 'la ricerca "Roma" non ha restituito annunci: il percorso del PIN si ferma')) {
    await browser.close(); chiudi(guasti, sacco);
  }
  await page.click('#risultati button[data-slug]');
  await page.waitForSelector('#modal.open', { timeout: 20000 });

  // Il preventivo deve esserci PRIMA di prenotare (niente prenotazione alla cieca)
  const preventivo = ((await page.innerText('#mQuote').catch(() => '')) || '').trim();
  esigi(preventivo.length > 40, `preventivo vuoto nel checkout: ${JSON.stringify(preventivo.slice(0, 120))}`);

  await page.click('#btnPrenota');
  await page.waitForSelector('#bkEmail', { timeout: 20000 });
  await page.fill('#bkEmail', EMAIL_OSPITE);
  // MODO ONLINE (radio di serie, vuoto): con STRIPE_FINTO il link esiste e il browser
  // parte verso la pagina di pagamento -- intercettata qui sopra.
  await page.click('#bkGo');
  const sulPagamento = await page.waitForURL(`${FINTO}*`, { timeout: 20000 })
    .then(() => true).catch(() => false);
  esigi(sulPagamento, 'dopo la prenotazione il browser non e\' arrivato sulla pagina di pagamento: ' +
    'il modo online non e\' partito (vedi #mMsg e il registro del banco)');

  if (!esigi(catturato && catturato.riferimento && catturato.voucher_token,
    `la risposta del book non ha consegnato riferimento/voucher: ${JSON.stringify(catturato || {}).slice(0, 200)}`)) {
    await browser.close(); chiudi(guasti, sacco);
  }
  const { riferimento, voucher_token: voucherToken } = catturato;
  const pagoUrl = page.url();
  esigi(pagoUrl.includes(encodeURIComponent(riferimento)) || pagoUrl.includes(riferimento),
    `la pagina di pagamento non porta il riferimento nell'URL: ${pagoUrl}`);
  console.log(`\n[OSPITE] prenotata ${riferimento} -- al pagamento finto: ${pagoUrl.slice(0, 60)}`);

  // ── 1) IL VOUCHER PRIMA DEL PAGAMENTO: 🔒, nessuna riga PIN ─────────────────────────
  const leggi = async () => {
    const p2 = await ctx.newPage();
    sorveglia(p2, 'VOUCHER', sacco);
    await p2.goto(`${BASE}/voucher/${encodeURIComponent(voucherToken)}?lang=it`,
      { waitUntil: 'domcontentloaded', timeout: 20000 });
    const html = await p2.content();
    await p2.close();
    return html;
  };
  const pre = await leggi();
  esigi(pre.includes('🔒'),
    'il voucher PRIMA del pagamento non mostra il lucchetto: il PIN e\' esposto senza incasso');
  esigi(!/color:#1e3c72">(\d{4})</.test(pre),
    'PIN ESPOSTO PRIMA del pagamento');
  console.log(`[VOUCHER pre] 🔒 al posto del PIN (come deve)`);

  // ── 2) L'INCASSO: webhook firmato con la sessione che il banco HA CREATO DAVVERO ────
  const h = crypto.createHash('sha256').update(riferimento).digest('hex');
  const csId = 'cs_test_' + h.slice(0, 16);
  const piId = 'pi_test_' + h.slice(16, 32);
  const payload = JSON.stringify({ id: 'evt_pin_' + h.slice(0, 8), type: 'checkout.session.completed',
    data: { object: { id: csId, payment_intent: piId,
             metadata: { riferimento, client_reference_id: riferimento } } } });
  const firma = firmaStripe(payload, WHSEC, Math.floor(Date.now() / 1000));
  const risposta = await fetch(`${BASE}/api/payments/webhook`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Stripe-Signature': firma },
    body: payload,
  });
  esigi(risposta.status === 200 || risposta.status === 409,
    `il webhook di pagamento ha risposto ${risposta.status}: l'incasso non e' stato applicato`);
  console.log(`[PAGAMENTO] webhook accettato: HTTP ${risposta.status} (${csId})`);

  // ── 3) RIAPRI IL VOUCHER: 🔒 sparito, la riga PIN con QUATTRO cifre ─────────────────
  const post2 = await leggi();
  esigi(!post2.includes('🔒'),
    'il voucher DOPO il pagamento mostra ancora il lucchetto: il PIN non si e\' aperto');
  const pinPost = post2.match(/color:#1e3c72">(\d{4})</);
  esigi(!!pinPost, 'il voucher DOPO il pagamento non ha nessuna riga PIN');
  esigi(/^\d{4}$/.test(pinPost && pinPost[1] || ''),
    `la riga PIN non contiene quattro cifre: ${JSON.stringify(pinPost && pinPost[1])}`);
  console.log(`[VOUCHER post] PIN APERTO: ${pinPost && pinPost[1]}`);
  await ctx.close();

  // ── 4) L'HOST VEDE LA PRENOTAZIONE PAGATA E LE DATE ──────────────────────────────────
  const hctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const hpage = await hctx.newPage();
  sorveglia(hpage, 'HOST', sacco);
  await hpage.goto(BASE + '/entra-host', { waitUntil: 'networkidle', timeout: 20000 });
  await hpage.fill('#em', CRED_HOST.em);
  await hpage.fill('#pw', CRED_HOST.pw);
  await Promise.all([
    hpage.waitForNavigation({ waitUntil: 'networkidle', timeout: 20000 }).catch(() => {}),
    hpage.click('#go'),
  ]);
  await hpage.waitForSelector('#pren_lista', { timeout: 20000 });
  let testo = '', precedente = null;
  for (let i = 0; i < 12 && testo !== precedente; i++) {
    precedente = testo;
    await hpage.waitForTimeout(500);
    testo = ((await hpage.innerText('#pren_lista').catch(() => '')) || '').trim();
  }
  await hctx.close();
  const soloAlfanumerico = t => (t || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
  const impronta = riferimento.slice(0, 8).toUpperCase();
  esigi(soloAlfanumerico(testo).includes(impronta),
    `l'host non vede la prenotazione pagata ${riferimento}: pannello = ` +
    JSON.stringify(testo.slice(0, 300)));
  for (const giorno of [fraOggiPiu(14), fraOggiPiu(17)]) {
    esigi(testo.includes(giorno), `l'host vede la prenotazione ma non la data ${giorno}`);
  }
  console.log(`[HOST] la prenotazione pagata e le date sono nel pannello`);

  await browser.close();
  chiudi(guasti, sacco);
})().catch(e => { console.error('CRASH del percorso:', e); process.exit(2); });

function chiudi(guasti, sacco) {
  if (sacco.length) {
    guasti.push(`errori JavaScript nel browser (${sacco.length}): ` + [...new Set(sacco)].slice(0, 6).join(' | '));
  }
  console.log('\n====== ESITO ======');
  if (!guasti.length) {
    console.log('PERCORSO COMPLETO: online, pagato via webhook firmato, PIN aperto a quattro cifre, l\'host lo vede.');
    process.exit(0);
  }
  console.log(`PERCORSO INTERROTTO — ${guasti.length} guasto/i:`);
  guasti.forEach(g => console.log('  - ' + g));
  process.exit(1);
}
