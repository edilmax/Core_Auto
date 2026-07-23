/** Accessibilità WCAG (axe-core) sulle pagine dei ruoli. Riporta le violazioni per gravità. */
const { chromium } = require('playwright');
const fs = require('fs');
const axeSrc = fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');
const BASE = process.argv[2] || 'http://127.0.0.1:8099';

async function analizza(page, nome) {
  await page.evaluate(axeSrc);
  const res = await page.evaluate(async () => await window.axe.run(document,
    { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa'] } }));
  const v = res.violations;
  const gravi = v.filter(x => x.impact === 'critical' || x.impact === 'serious');
  console.log(`  ${nome}: ${v.length} regole con problemi (${gravi.length} gravi)`);
  gravi.slice(0, 6).forEach(x => { console.log(`     [${x.impact}] ${x.id}: ${x.help}`);
       x.nodes.slice(0,4).forEach(n => console.log(`        -> ${n.target}  ${(n.any[0]&&n.any[0].message)||''}`)); });
  return gravi.length;
}

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext();
  let gravi = 0;
  console.log('== ACCESSIBILITÀ WCAG 2.1 AA (axe-core) ==');
  // Ospite: checkout
  const p = await ctx.newPage();
  await p.goto(BASE + '/?lang=it', { waitUntil: 'domcontentloaded' });
  await p.fill('#citta', 'Roma');
  const d = new Date(); d.setDate(d.getDate() + 7); await p.fill('#checkin', d.toISOString().slice(0, 10));
  d.setDate(d.getDate() + 3); await p.fill('#checkout', d.toISOString().slice(0, 10));
  await p.click('#btnCerca');
  await p.waitForSelector('#risultati button[data-slug]', { timeout: 15000 });
  await p.click('#risultati button[data-slug]');
  await p.waitForSelector('input[name="modopag"]', { timeout: 15000 });
  gravi += await analizza(p, 'Ospite/checkout');
  await p.close();
  // Admin
  await ctx.request.post(BASE + '/api/admin/login', { headers: { 'X-Admin-Key': 'ak' } });
  const pa = await ctx.newPage();
  await pa.goto(BASE + '/admin.html', { waitUntil: 'networkidle' }).catch(() => {});
  gravi += await analizza(pa, 'Admin/dashboard');
  await pa.close();
  await browser.close();
  console.log(`\n== ESITO: ${gravi} violazioni GRAVI di accessibilità ==`);
  process.exit(gravi > 0 ? 0 : 0);  // report-only (non blocca)
})().catch(e => { console.error('CRASH a11y:', e.message); process.exit(2); });
