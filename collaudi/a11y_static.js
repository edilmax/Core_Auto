/**
 * Accessibilità WCAG + smoke VISIVO sulle pagine PUBBLICHE STATICHE (deploy/*.html), via file://.
 *
 * Perche' STATICO: le pagine di marketing/legali sono HTML autoconsistenti (CSS inline + i18n JS);
 * si auditano SENZA avviare il server -> deterministico, veloce, adatto a un GATE su ogni push.
 * Complementa collaudi/test_a11y.js (che invece fa il flusso dinamico checkout/admin su server vivo).
 *
 * GATE VERO (a differenza di test_a11y.js che e' report-only): esce 1 se una pagina ha violazioni
 * WCAG 'critical'/'serious' -> la CI diventa rossa. Le violazioni axe su file:// sono ACCURATE
 * (contrasto/label/nome-accessibile non dipendono dal JS esterno). Gli errori JS in console su
 * file:// sono invece FALSI POSITIVI (le pagine caricano /app.js con path ASSOLUTO, che sotto
 * file:// non risolve -> "BV is not defined"); percio' sono solo INFORMATIVI qui, e lo smoke JS
 * vero gira sul sito LIVE (http). Trovato ROSSO il 2026-07-24: 2 contrasti (diventa-host/commissioni)
 * + 2 critical su host.html (#lang select senza nome, #p_files upload senza label) -> corretti, ri-verdi.
 *
 * Uso: node collaudi/a11y_static.js   (dalla radice del repo)
 * Dipendenze: playwright + axe-core (gia' in package.json).
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');

const axeSrc = fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');
const DEPLOY = path.join(__dirname, '..', 'deploy');
// Pagine pubbliche che si renderizzano da sole (no sessione/gate app-driven).
const PAGINE = ['index.html', 'host.html', 'admin.html', 'diventa-host.html', 'commissioni.html',
  'guida-operativa.html', 'contratto-host.html', 'grazie.html', 'annullato.html'];

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext();
  let gravi = 0, jsErr = 0;
  console.log('== ACCESSIBILITA WCAG 2.1 A+AA + smoke JS (pagine statiche deploy/) ==');
  for (const nome of PAGINE) {
    const file = path.join(DEPLOY, nome);
    if (!fs.existsSync(file)) { console.log(`  ${nome}: ASSENTE (saltata)`); continue; }
    const page = await ctx.newPage();
    const errs = [];
    page.on('console', m => { if (m.type() === 'error') errs.push(m.text().slice(0, 120)); });
    page.on('pageerror', e => errs.push('PAGEERROR: ' + String(e).slice(0, 120)));
    try {
      await page.goto(pathToFileURL(file).href, { waitUntil: 'load', timeout: 20000 });
      await page.evaluate(axeSrc);
      const res = await page.evaluate(async () => await window.axe.run(document,
        { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] } }));
      const g = res.violations.filter(x => x.impact === 'critical' || x.impact === 'serious');
      gravi += g.length; jsErr += errs.length;
      console.log(`  ${nome.padEnd(22)} gravi=${g.length} jsErr=${errs.length}`);
      g.forEach(x => { console.log(`     [${x.impact}] ${x.id}: ${x.help}`);
        x.nodes.slice(0, 4).forEach(n => console.log(`        -> ${n.target} ${(n.any[0] && n.any[0].message) || ''}`)); });
      errs.forEach(e => console.log(`     JS  -> ${e}`));
    } catch (e) {
      console.log(`  ${nome}: ERRORE ${String(e).split('\n')[0]}`); gravi++;
    }
    await page.close();
  }
  await browser.close();
  console.log(`\n== ESITO: ${gravi} violazioni GRAVI axe (gate) · ${jsErr} note-JS (informative, file://) ==`);
  process.exit(gravi > 0 ? 1 : 0);   // GATE: rosso SOLO sulle violazioni axe (gli errori JS file:// sono artefatti)
})().catch(e => { console.error('CRASH a11y_static:', e.message); process.exit(2); });
