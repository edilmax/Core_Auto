/**
 * LA RI-ACCETTAZIONE DEL CONTRATTO, COL BROWSER VERO (consegne 30, punto a).
 *
 * Il 1/10 sera il fondatore ha riaccettato contratto e privacy dal suo pannello: il server ha
 * risposto 200 tre volte e ha scritto le prove firmate tre volte (sei righe), ma la pagina
 * diceva «Non e' stato possibile registrare l'accettazione». La pagina leggeva `r.ok` sulla
 * busta che `post()` restituisce ({status, data}): quel campo non esiste, quindi l'esito era
 * SEMPRE «errore», qualunque cosa dicesse il server. Nessun collaudo aveva mai premuto quel
 * pulsante: le prove della rotta parlano col server, non con la pagina.
 *
 *   HOST (riaccetta@visivo.it, iscritto dal banco SENZA prove dei consensi):
 *   accesso -> la scheda della ri-accettazione compare -> tre spunte -> «Accetto»
 *   -> PRIMA due risposte finte del browser (200 con ok:false, 500): la pagina deve dire
 *      l'errore (`ra_err`) e lasciare il pulsante premibile -- un allarme si prova nei due versi
 *   -> poi la risposta vera: la pagina deve dire il successo (`ra_ok`), mai l'errore
 *   -> e il server, riletto, non chiede piu' di riaccettare (l'effetto, non solo la frase).
 *
 * ⛔ SE MANCA LA PREMESSA NON E' VERDE (sbaglio S7): se la scheda non compare, la prova non ha
 *    premuto niente ed esce 2, «NON ESEGUITO».
 * ⛔ COSA NON PROVA, DICHIARATO: il contenuto delle prove firmate (versione, impronta, IP:
 *    test_consensi_blindati e test_fase163), le altre 7 lingue, il 409 sul contratto cambiato
 *    mentre la pagina era aperta.
 *
 * Uso:
 *     python collaudi/avvia_server_visivo.py 8095
 *     BASE_VISIVO=http://127.0.0.1:8095 node collaudi/riaccetta_browser.js
 * Uscita 0 = riaccettato e la pagina lo dice. 1 = si e' rotto, e dove. 2 = non eseguito.
 */
const { chromium } = require('playwright');

const BASE = process.env.BASE_VISIVO || 'http://127.0.0.1:8095';
const CRED = { em: 'riaccetta@visivo.it', pw: 'password1' };
const SPUNTE = ['#ra_terms', '#ra_clausole', '#ra_privacy'];

const guasti = [];
const esigi = (cond, msg) => { if (!cond) guasti.push(msg); return !!cond; };

(async () => {
  console.log('====== LA RI-ACCETTAZIONE DEL CONTRATTO, DAL PANNELLO HOST ======');
  console.log('server: ' + BASE);
  const sacco = [];
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const p = await ctx.newPage();
  p.on('pageerror', e => sacco.push(`pagina: ${String(e).slice(0, 160)}`));

  await p.goto(BASE + '/entra-host', { waitUntil: 'networkidle', timeout: 20000 });
  await p.fill('#em', CRED.em);
  await p.fill('#pw', CRED.pw);
  await Promise.all([
    p.waitForNavigation({ waitUntil: 'networkidle', timeout: 20000 }).catch(() => {}),
    p.click('#go'),
  ]);
  const scheda = await p.waitForSelector('#cardRiaccetta', { state: 'visible', timeout: 20000 })
    .then(() => true).catch(() => false);
  if (!scheda) {
    console.log('\nNON ESEGUITO: la scheda della ri-accettazione non e\' comparsa per un host senza '
      + 'prove dei consensi (premessa mancante: nessun pulsante e\' stato premuto).');
    await browser.close();
    process.exit(2);
  }
  console.log('[HOST] la scheda della ri-accettazione e\' visibile');

  for (const s of SPUNTE) await p.check(s);
  const [ok, err] = await p.evaluate(() => [T('ra_ok'), T('ra_err')]);
  const premi = async () => {
    await p.evaluate(() => { document.getElementById('ra_msg').textContent = ''; });
    await p.click('#btnRiaccetta');
    const scritto = await p.waitForFunction(
      () => (document.getElementById('ra_msg').textContent || '').trim() !== '',
      null, { timeout: 15000 }).then(() => true).catch(() => false);
    return [scritto, ((await p.textContent('#ra_msg')) || '').trim()];
  };

  // L'ALTRA DIREZIONE (regola ferrea 10): un esito che il server NON ha dato come successo deve
  // dire «errore» e lasciare il pulsante premibile. Risposte finte del browser: il server non
  // le vede, quindi le prove firmate non si scrivono e il giro vero sotto resta il primo.
  for (const [stato, corpo] of [[200, { ok: false }], [500, { ok: true }]]) {
    await p.route('**/api/host/riaccetta', r => r.fulfill({
      status: stato, contentType: 'application/json', body: JSON.stringify(corpo) }));
    const [scritto, msg] = await premi();
    await p.unroute('**/api/host/riaccetta');
    console.log(`[HOST] risposta finta ${stato} ${JSON.stringify(corpo)} -> ${JSON.stringify(msg)}`);
    esigi(scritto && msg === err, `con la risposta ${stato} ${JSON.stringify(corpo)} la pagina dice `
      + `${JSON.stringify(msg)} invece di ${JSON.stringify(err)}`);
    esigi(!(await p.isDisabled('#btnRiaccetta')),
      `dopo la risposta ${stato} il pulsante resta disabilitato: non si puo' riprovare`);
    if (guasti.length) return fine(browser, sacco);   // il pulsante dopo non si puo' premere
  }

  const [scritto, msg] = await premi();
  console.log(`[HOST] la pagina dice: ${JSON.stringify(msg)}`);
  esigi(scritto, 'dopo «Accetto» la pagina non ha scritto nessun esito');
  esigi(msg === ok, `dopo «Accetto» la pagina dice ${JSON.stringify(msg)} invece di `
    + `${JSON.stringify(ok)}` + (msg === err ? ' (il testo dell\'ERRORE)' : ''));

  // L'EFFETTO: il server, riletto con la sessione della pagina, non chiede piu' di riaccettare.
  const st = await p.evaluate(async () => {
    const r = await fetch('/api/host/contratto_stato', { headers: authHeaders() });
    return { status: r.status, corpo: await r.json().catch(() => null) };
  });
  console.log(`[SERVER] contratto_stato: ${st.status} deve_riaccettare=`
    + `${st.corpo && st.corpo.deve_riaccettare}`);
  esigi(st.status === 200 && st.corpo && st.corpo.deve_riaccettare === false,
    `il server chiede ancora di riaccettare: ${JSON.stringify(st)}`);
  await fine(browser, sacco);
})().catch(e => { console.error('CRASH del percorso:', e); process.exit(2); });

async function fine(browser, sacco) {
  sacco.forEach(e => guasti.push(e));
  await browser.close();
  console.log('\n====== ESITO ======');
  if (!guasti.length) {
    console.log('RIACCETTATO: il server ha le prove e la pagina dice che e\' andata bene.');
    process.exit(0);
  }
  console.log(`PERCORSO INTERROTTO — ${guasti.length} guasto/i:`);
  guasti.forEach(g => console.log('  - ' + g));
  process.exit(1);
}
