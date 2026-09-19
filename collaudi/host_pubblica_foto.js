/**
 * L'HOST PUBBLICA, L'OSPITE TROVA — il confine nell'altro verso, col browser vero (Tappa 2/A2).
 *
 * `percorso_ospite_host.js` e `ospite_checkout_paga.js` attraversano il confine OSPITE->HOST
 * (l'ospite prenota, l'host la vede). Qui si percorre il VERSO OPPOSTO, quello con cui tutto
 * comincia: l'host compila il suo annuncio NEL PANNELLO, carica una FOTO VERA dal disco,
 * apre le date col form del periodo -- e l'OSPITE, in un ALTRO browser, deve trovare
 * l'annuncio in ricerca, con la foto dell'host e un preventivo che risponde.
 *
 *   HOST (browser 1):  login -> form "Pubblica alloggio" (titolo, citta', CIN, prezzo in
 *                      euro, tassa, sconto settimana) -> setInputFiles della foto (il primo
 *                      `setInputFiles` di tutto collaudi/: l'upload era mai stato cliccato)
 *                      -> Pubblica -> seleziona il nuovo annuncio -> "Apri periodo".
 *   OSPITE (browser 2): cerca "Milano" nelle date appena aperte -> la card c'e', porta la
 *                      FOTO caricata dall'host (/uploads/), e il preventivo risponde.
 *
 * ⛔ LA PROVA E' IN DUE TEMPI, come nel gemello: le opzioni del pannello host PRIMA (senza
 *    il nuovo annuncio) e DOPO (con): il verde non puo' venire da una pagina che mostra
 *    sempre qualcosa. E la ricerca e' per "Milano" -- citta' dove il banco NON ha seminato
 *    niente -- cosi' trovare la card prova che e' QUELLA dell'host a essere arrivata.
 *
 * ⛔ COSA NON PROVA, DICHIARATO: la pubblicazione senza CIN (422, provato in suite), la
 *    geolocalizzazione "vicino a me", l'import annunci da OTA, iCal (tappa 6 della mappa),
 *    il prezzo al centesimo (oracolo di Tappa 1). La FOTO e' un PNG di un pixel generato
 *    dal collaudo stesso: si prova il TRASPORTO (file -> base64 -> magic bytes -> nome
 *    casuale -> /uploads/ -> thumbnail dell'ospite), non la fotografia.
 *
 * Uso:
 *     python collaudi/avvia_server_visivo.py 8097            (o 8099: niente gateway qui)
 *     BASE_VISIVO=http://127.0.0.1:8097 node collaudi/host_pubblica_foto.js
 * Uscita 0 = l'host ha pubblicato e l'ospite ha trovato. Uscita 1 = si e' rotto, e dove.
 */
const { chromium } = require('playwright');

const BASE = process.env.BASE_VISIVO || 'http://127.0.0.1:8097';
const LINGUA = (process.env.LINGUA || 'it').trim();
const CRED_HOST = { em: 'host@visivo.it', pw: 'password1' };
const CITTA_NUOVA = 'Milano';
const TITOLO = 'Loft A2 Visivo';
const CIN = 'IT020309A2VIS00001';        // alfanumerico maiuscolo 6-30: il formato del motore

// Un PNG di un pixel, fatto a mano: quel che serve e' che i MAGIC BYTES siano veri.
const PNG_UN_PIXEL = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==',
  'base64');

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

(async () => {
  console.log(`====== L'HOST PUBBLICA, L'OSPITE TROVA (lingua: ${LINGUA}) ======`);
  console.log('server: ' + BASE);
  const sacco = [];
  const browser = await chromium.launch();

  // ── TEMPO 1: l'host entra, e il suo pannello NON ha ancora l'annuncio nuovo -----------
  const host = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const ph = await host.newPage();
  sorveglia(ph, 'HOST', sacco);
  await ph.goto(BASE + '/entra-host', { waitUntil: 'networkidle', timeout: 20000 });
  await ph.fill('#em', CRED_HOST.em);
  await ph.fill('#pw', CRED_HOST.pw);
  await Promise.all([
    ph.waitForNavigation({ waitUntil: 'networkidle', timeout: 20000 }).catch(() => {}),
    ph.click('#go'),
  ]);
  await ph.waitForSelector('#au_who', { timeout: 20000 });
  const chi = ((await ph.innerText('#au_who').catch(() => '')) || '').trim();
  esigi(chi.includes('@'), `l'host non risulta collegato (mostrato: ${JSON.stringify(chi)})`);
  console.log(`\n[HOST] collegato come ${chi}`);

  const opzioniPrima = await ph.evaluate(() =>
    [...document.querySelectorAll('#al_corrente option')].map(o => o.value));
  console.log(`[HOST] alloggi PRIMA: ${JSON.stringify(opzioniPrima)}`);
  esigi(!opzioniPrima.some(s => s.includes('loft-a2') || s.includes('a2-visivo')),
    'il pannello conteneva gia\' un annuncio A2: la prova non dimostrerebbe niente');

  // ── IL FORM: tutti i campi che un host vero riempirebbe ------------------------------
  await ph.fill('#p_titolo', TITOLO);
  await ph.fill('#p_citta', CITTA_NUOVA);
  await ph.selectOption('#p_paese', 'IT');
  await ph.fill('#p_cin', CIN);
  await ph.fill('#p_descr', 'Loft di collaudo: luminoso, centro, per il percorso A2.');
  await ph.fill('#p_prezzo', '95.50');       // euro col decimale: toCents() fa la conversione
  await ph.fill('#p_tax_pp', '200');
  await ph.fill('#p_tax_max', '5');
  await ph.fill('#p_sc_sett', '10');
  await ph.fill('#p_cap', '3');
  await ph.fill('#p_serv', 'wifi,aria_condizionata');

  // ── LA FOTO: il primo setInputFiles della cassetta degli attrezzi --------------------
  // Il trasporto e' lungo: FileReader -> base64 -> POST /api/host/upload_foto -> magic
  // bytes -> nome casuale su disco -> thumbnail nel pannello. Se un anello si rompe, la
  // thumbnail con /uploads/ non arriva: e' l'assert piu' pagamento-di-debito di tutto il giro.
  await ph.setInputFiles('#p_files', { name: 'a2.png', mimeType: 'image/png', buffer: PNG_UN_PIXEL });
  const thumb = await ph.waitForSelector('#p_thumbs img[src*="/uploads/"]', { timeout: 20000 })
    .then(() => true).catch(() => false);
  const srcThumb = thumb ? await ph.getAttribute('#p_thumbs img[src*="/uploads/"]', 'src') : '';
  esigi(thumb, `la foto caricata non ha prodotto nessuna thumbnail /uploads/ nel pannello host`);
  console.log(`[HOST] foto caricata: ${String(srcThumb).slice(0, 60)}`);

  await ph.click('#btnPubblica');
  let msgPub = '';
  let decisoPub = false;
  for (let i = 0; i < 40 && !decisoPub; i++) {
    await ph.waitForTimeout(500);
    msgPub = ((await ph.innerText('#msgPub').catch(() => '')) || '').trim();
    if (msgPub.includes('✅') || msgPub.includes('❌')) decisoPub = true;
  }
  esigi(decisoPub, `dopo "Pubblica" nessun esito a schermo: ${JSON.stringify(msgPub.slice(0, 200))}`);
  esigi(msgPub.includes('✅') && !msgPub.includes('❌'),
    `la pubblicazione e' FALLITA sul pannello host: ${JSON.stringify(msgPub.slice(0, 300))}`);
  console.log(`[HOST] pubblicazione: ${msgPub.slice(0, 120)}`);

  // Lo SLUG nuovo: l'opzione che prima non c'era. Se la select non si e' aggiornata da sola,
  // la forza "Il mio elenco"; il valore dev'esserci, perche' la prova dell'ospite lo nomina.
  let opzioniDopo = opzioniPrima;
  for (let i = 0; i < 10; i++) {
    opzioniDopo = await ph.evaluate(() =>
      [...document.querySelectorAll('#al_corrente option')].map(o => o.value));
    if (opzioniDopo.length > opzioniPrima.length) break;
    await ph.click('#btnMiei').catch(() => {});
    await ph.waitForTimeout(700);
  }
  const nuovi = opzioniDopo.filter(s => !opzioniPrima.includes(s));
  if (!esigi(nuovi.length === 1,
    `dopo la pubblicazione le opzioni dell'host sono cambiate in modo strano: prima ` +
    `${JSON.stringify(opzioniPrima)} dopo ${JSON.stringify(opzioniDopo)}`)) {
    await browser.close(); chiudi(guasti, sacco);
  }
  const slug = nuovi[0];
  console.log(`[HOST] nuovo annuncio: ${slug}`);

  // ── APRI IL PERIODO: la select del corrente riempie r_slug, poi il form del range ------
  await ph.selectOption('#al_corrente', slug);
  await ph.fill('#r_da', fraOggiPiu(20));
  await ph.fill('#r_a', fraOggiPiu(50));
  await ph.fill('#r_unita', '2');
  await ph.fill('#r_prezzo', '95.50');
  await ph.click('#btnRange');
  let msgRange = '';
  let decisoRange = false;
  for (let i = 0; i < 40 && !decisoRange; i++) {
    await ph.waitForTimeout(500);
    msgRange = ((await ph.innerText('#msgRange').catch(() => '')) || '').trim();
    if (msgRange.includes('✅') || msgRange.includes('❌')) decisoRange = true;
  }
  esigi(msgRange.includes('✅') && !msgRange.includes('❌'),
    `l'apertura del periodo e' FALLITA sul pannello host: ${JSON.stringify(msgRange.slice(0, 300))}`);
  console.log(`[HOST] periodo aperto: ${msgRange.slice(0, 120)}`);
  await host.close();

  // ── L'OSPITE, in un ALTRO browser: cerca Milano e deve trovare QUELLO ----------------
  const ospite = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const po = await ospite.newPage();
  sorveglia(po, 'OSPITE', sacco);
  await po.goto(`${BASE}/?lang=${LINGUA}`, { waitUntil: 'domcontentloaded', timeout: 20000 });
  await po.waitForSelector('#citta', { timeout: 20000 });
  await po.fill('#citta', CITTA_NUOVA);
  await po.fill('#checkin', fraOggiPiu(25));     // DENTRO il periodo appena aperto
  await po.fill('#checkout', fraOggiPiu(27));
  await po.click('#btnCerca');

  const card = await po.waitForSelector(`#risultati button[data-slug="${slug}"]`, { timeout: 20000 })
    .then(() => true).catch(() => false);
  if (!esigi(card,
    `l'OSPITE NON TROVA L'ANNUNCIO "${slug}" pubblicato dall'host a ${CITTA_NUOVA}: ` +
    'il confine host->ospite e\' rotto')) {
    await browser.close(); chiudi(guasti, sacco);
  }

  // LA FOTO DELL'HOST deve arrivare fino al browser dell'ospite: il trasporto intero.
  // (il selettore guarda la CARD che CONTIENE il bottone data-slug: l'img sta nella card,
  //  non dentro il bottone -- il primo giro lo ha imparato alla vecchia way, con null.)
  const srcCard = await po.getAttribute(
    `#risultati .card:has(button[data-slug="${slug}"]) img.thumb`, 'src').catch(() => null);
  esigi(!!srcCard && String(srcCard).includes('/uploads/'),
    `la card dell'ospite non mostra la foto caricata dall'host (src: ${JSON.stringify(srcCard)})`);
  console.log(`[OSPITE] card trovata con foto: ${String(srcCard).slice(0, 60)}`);

  await po.click(`#risultati button[data-slug="${slug}"]`);
  const modale = await po.waitForSelector('#modal.open', { timeout: 20000 })
    .then(() => true).catch(() => false);
  esigi(modale, 'il riquadro di prenotazione non si e\' aperto sull\'annuncio nuovo');
  const preventivo = ((await po.innerText('#mQuote').catch(() => '')) || '').trim();
  esigi(preventivo.length > 40,
    `il preventivo sull'annuncio appena pubblicato e' quasi vuoto: ${JSON.stringify(preventivo.slice(0, 120))}`);

  await ospite.close();
  await browser.close();
  chiudi(guasti, sacco);
})().catch(e => { console.error('CRASH del percorso:', e); process.exit(2); });

function chiudi(guasti, sacco) {
  if (sacco.length) {
    guasti.push(`errori JavaScript nel browser (${sacco.length}): ` + [...new Set(sacco)].slice(0, 6).join(' | '));
  }
  console.log('\n====== ESITO ======');
  if (!guasti.length) {
    console.log('PERCORSO COMPLETO: l\'host ha pubblicato con la foto, aperto il periodo, e l\'ospite ha trovato annuncio, foto e preventivo.');
    process.exit(0);
  }
  console.log(`PERCORSO INTERROTTO — ${guasti.length} guasto/i:`);
  guasti.forEach(g => console.log('  - ' + g));
  process.exit(1);
}
