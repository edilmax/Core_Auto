/**
 * IL CHECKOUT DELL'OSPITE, CRONOLOGICO, COL BROWSER VERO (Tappa 1/A1 della mappa).
 *
 * `percorso_ospite_host.js` attraversa il confine fra due persone (ospite prenota, host
 * vede). Questo percorso gemello resta DALLA PARTE DELL'OSPITE e percorre il checkout
 * UN PASSO ALLA VOLTA, nell'ordine in cui lo vive chi paga:
 *
 *   cerca -> apre l'annuncio -> LEVA IL PREVENTIVO (righe, conto alla rovescia, modi di
 *   pagamento) -> sbaglia l'email (il client lo deve fermare PRIMA del server) -> la
 *   corregge -> prenota -> legge l'esito -> APRE IL VOUCHER con il suo link.
 *
 * E IN DUE ATTI, come il gemello:
 *   ATTO 1 (ATTESO=conferma, banco con chiave VUOTA): la prenotazione diretta si
 *     conferma, il voucher si apre DAL LINK DELLA CONFERMA, e il PIN resta CHIUSO
 *     (🔒): nessun PIN senza incasso, visto dalla pagina che l'ospite ha davanti.
 *   ATTO 2 (ATTESO=rifiuto, banco con chiave FINTA): il gateway non puo' incassare,
 *     il rifiuto arriva PULITO (frase, mai codici interni) e niente voucher.
 *
 * ⛔ COSA NON PROVA, DICHIARATO: la pagina della carta e il ritorno da Stripe (regola D6:
 *    repo pubblico, niente chiavi nel giro automatico); l'IMPORTO del preventivo al
 *    centesimo (lo ricalcola da zero `test_oracolo_checkout.py`, il secondo conto: qui
 *    si prova la CRONOLOGIA e le porte, non l'aritmetica); l'aspetto grafico (a11y e
 *    test_visivo). La LINGUA e' pilotabile (LINGUA=it|en|es|fr|de|pt|ja|zh) perche' il
 *    domani questo stesso percorso deve girare otto volte.
 *
 * Uso:
 *     ATTO 1:  STRIPE_SECRET_KEY= python collaudi/avvia_server_visivo.py 8097
 *              BASE_VISIVO=http://127.0.0.1:8097 ATTESO=conferma node collaudi/ospite_checkout_paga.js
 *     ATTO 2:  python collaudi/avvia_server_visivo.py 8099        (chiave finta di serie)
 *              BASE_VISIVO=http://127.0.0.1:8099 ATTESO=rifiuto  node collaudi/ospite_checkout_paga.js
 * Uscita 0 = la cronologia e' andata come deve. Uscita 1 = si e' rotta, e dove.
 */
const { chromium } = require('playwright');

const BASE = process.env.BASE_VISIVO || 'http://127.0.0.1:8099';
const ATTESO = (process.env.ATTESO || 'conferma').trim();
const LINGUA = (process.env.LINGUA || 'it').trim();
// ⛔ LE DATE NON SONO FISSE: il banco semina UNITA' TOTALI LIMITATE (3) sul suo annuncio,
// e due giri sulle stesse notti si mangiano a vicenda: il quarto trova "Non disponibile"
// e il collaudo accusa il prodotto di un esaurimento CHE E' GIUSTO (provato in fr, 2026-09-19).
// Chi orchestra i giri (es. le 8 lingue) sposta `GIORNI_BASE` e le notti non si toccano.
const GIORNI_BASE = parseInt(process.env.GIORNI_BASE || '7', 10);
const EMAIL_OSPITE = 'ospite.checkout@visivo.it';
const CRED_HOST = { em: 'host@visivo.it', pw: 'password1' };

if (ATTESO !== 'conferma' && ATTESO !== 'rifiuto') {
  console.error(`ATTESO deve valere "conferma" o "rifiuto", non ${JSON.stringify(ATTESO)}`);
  process.exit(2);
}

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

/** Il pannello dell'host, con sessione separata: la stessa mano del percorso gemello. */
async function elencoDellHost(browser, sacco) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  sorveglia(page, 'HOST', sacco);
  await page.goto(BASE + '/entra-host', { waitUntil: 'networkidle', timeout: 20000 });
  await page.fill('#em', CRED_HOST.em);
  await page.fill('#pw', CRED_HOST.pw);
  await Promise.all([
    page.waitForNavigation({ waitUntil: 'networkidle', timeout: 20000 }).catch(() => {}),
    page.click('#go'),
  ]);
  await page.waitForSelector('#pren_lista', { timeout: 20000 });
  let testo = '', precedente = null;
  for (let i = 0; i < 12 && testo !== precedente; i++) {
    precedente = testo;
    await page.waitForTimeout(500);
    testo = ((await page.innerText('#pren_lista').catch(() => '')) || '').trim();
  }
  const collegato = ((await page.innerText('#au_who').catch(() => '')) || '').trim();
  await ctx.close();
  return { testo, collegato };
}

/** Il checkout dell'ospite, passaggio per passaggio. Torna cio' che ha letto e il link voucher. */
async function checkoutComeOspite(browser, sacco) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  sorveglia(page, 'OSPITE', sacco);
  const esito = { riferimento: null, messaggio: '', voucherHref: null, deciso: false };

  await page.goto(`${BASE}/?lang=${LINGUA}`, { waitUntil: 'domcontentloaded', timeout: 20000 });
  await page.waitForSelector('#citta', { timeout: 20000 });
  await page.fill('#citta', 'Roma');
  await page.fill('#checkin', fraOggiPiu(GIORNI_BASE));
  await page.fill('#checkout', fraOggiPiu(GIORNI_BASE + 3));
  await page.click('#btnCerca');

  const trovato = await page.waitForSelector('#risultati button[data-slug]', { timeout: 20000 })
    .then(() => true).catch(() => false);
  if (!esigi(trovato, 'la ricerca "Roma" non ha restituito nessun annuncio: il checkout si ferma qui')) {
    await ctx.close();
    return esito;
  }
  await page.click('#risultati button[data-slug]');
  if (!esigi(await page.waitForSelector('#modal.open', { timeout: 20000 })
    .then(() => true).catch(() => false),
  'il riquadro di prenotazione non si e\' aperto dopo il clic sull\'annuncio')) {
    await ctx.close();
    return esito;
  }

  // ── IL PREVENTIVO: righe piene E conto alla rovescia partito ──────────────────────
  const preventivo = ((await page.innerText('#mQuote').catch(() => '')) || '').trim();
  esigi(preventivo.length > 40,
    `il preventivo nel checkout e' quasi vuoto: ${JSON.stringify(preventivo.slice(0, 120))}`);
  esigi(preventivo.includes('€'),
    `il preventivo non mostra la valuta dell'addebito (€): ${JSON.stringify(preventivo.slice(0, 160))}`);
  const rovescia = ((await page.innerText('#cd').catch(() => '')) || '').trim();
  esigi(/\d/.test(rovescia),
    `il conto alla rovescia del blocco prezzo non mostra nessun numero: ${JSON.stringify(rovescia.slice(0, 60))}`);

  // ── I MODI DI PAGAMENTO: il banco accende il radio "in struttura" (PAGA_STRUTTURA_ATTIVO=1
  //    nell'avvio): l'ospite deve trovare DUE scelte, non una sola e nemmeno zero.
  const nModi = await page.locator('input[name="modopag"]').count();
  esigi(nModi === 2,
    `i modi di pagamento nel checkout sono ${nModi}, non 2: il radio "paga in struttura" manca o e' raddoppiato`);

  await page.click('#btnPrenota');
  await page.waitForSelector('#bkEmail', { timeout: 20000 });

  // ── L'EMAIL SBAGLIATA: il CLIENT la deve fermare prima che parta qualsiasi richiesta.
  //    Un form che spedisce al server anche l'indirizzo rotto sposta il controllo sul
  //    lato sbagliato del confine (e un giorno lo paga l'ospite con un attesa inutile).
  await page.fill('#bkEmail', 'senza-chiocciola');
  await page.click('#bkGo');
  await page.waitForTimeout(600);
  const rimprovero = ((await page.innerText('#bkMsg').catch(() => '')) || '').trim();
  const mMsgPre = ((await page.innerText('#mMsg').catch(() => '')) || '').trim();
  esigi(rimprovero.length > 0,
    'la email senza "@" e\' passata senza nemmeno un rimprovero a schermo (lato client)');
  esigi(!mMsgPre.includes('❌') && !mMsgPre.includes('✅'),
    `l'email rotta e\' arrivata al SERVER (mMsg dice: ${JSON.stringify(mMsgPre.slice(0, 120))})`);

  // ── L'EMAIL GIUSTA: ora la prenotazione parte davvero.
  await page.fill('#bkEmail', EMAIL_OSPITE);
  await page.click('#bkGo');
  let messaggio = '';
  for (let i = 0; i < 40 && !esito.deciso; i++) {
    await page.waitForTimeout(500);
    messaggio = ((await page.innerText('#mMsg').catch(() => '')) || '').trim();
    const m = messaggio.match(/\(([0-9a-zA-Z_-]{6,})\)/);
    if (m) { esito.riferimento = m[1]; esito.deciso = true; }
    else if (messaggio.includes('❌')) { esito.deciso = true; }
  }
  esito.messaggio = messaggio;
  esigi(esito.deciso,
    `dopo la richiesta di prenotazione l'ospite non ha ricevuto ne' conferma ne' rifiuto. A schermo: ${JSON.stringify(messaggio.slice(0, 300))}`);

  // ── IL LINK DEL VOUCHER: la conferma deve consegnare all'ospite la sua pagina,
  //    con un click, non con una copia-incolla di token.
  if (ATTESO === 'conferma' && esito.riferimento) {
    const href = await page.getAttribute('#mMsg a[href*="/voucher/"]', 'href').catch(() => null);
    esigi(!!href,
      `la conferma non contiene il link alla pagina voucher: ${JSON.stringify(messaggio.slice(0, 200))}`);
    esito.voucherHref = href;
  }
  await ctx.close();
  return esito;
}

/** La pagina voucher aperta DAL LINK della conferma: quello che l'ospite ci trova. */
async function apriVoucher(browser, href, riferimento, sacco) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  sorveglia(page, 'VOUCHER', sacco);
  let aperta = true;
  await page.goto(BASE + (href.startsWith('http') ? href.slice(BASE.length) : href),
    { waitUntil: 'domcontentloaded', timeout: 20000 }).catch(() => { aperta = false; });
  if (!esigi(aperta, `la pagina voucher non si e' aperta: ${href}`)) {
    await ctx.close();
    return;
  }
  const html = await page.content();
  // ⛔ IL PIN: nel modo diretto non c'e' stato incasso, quindi il PIN resta CHIUSO. La
  // riga e' quella definita in UN posto solo (fase83.riga_pin_voucher): cercare QUATTRO
  // CIFRE nude sarebbe ambiguo (la pagina e' piena di numeri), cercare LA RIGA no.
  esigi(html.includes('🔒'),
    'il voucher di una prenotazione SENZA incasso non mostra il lucchetto al posto del PIN');
  const pinNudo = html.match(/color:#1e3c72">(\d{4})</);
  esigi(!pinNudo,
    `IL PIN E' ESPOSTO in un voucher senza incasso: "${pinNudo && pinNudo[1]}"`);
  esigi(!html.includes('/api/garanzia/'),
    'il voucher senza incasso contiene link alle API della garanzia: la guardia fisica li vieta');
  const corpo = ((await page.innerText('body').catch(() => '')) || '');
  const soloAlfanumerico = t => (t || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
  esigi(soloAlfanumerico(corpo).includes(riferimento.slice(0, 8).toUpperCase()),
    'la pagina voucher non mostra il riferimento della prenotazione');
  await ctx.close();
}

(async () => {
  console.log(`====== IL CHECKOUT DELL'OSPITE (atto: ${ATTESO === 'conferma' ? 'LA PRENOTAZIONE DIRETTA ARRIVA IN FONDO' : 'IL GATEWAY MUTO NON CONSEGNA NIENTE'}, lingua: ${LINGUA}) ======`);
  console.log('server: ' + BASE);
  const sacco = [];
  const browser = await chromium.launch();

  const prima = await elencoDellHost(browser, sacco);
  esigi(prima.collegato.includes('@'),
    `l'host non risulta collegato al suo pannello (mostrato: ${JSON.stringify(prima.collegato)})`);
  console.log(`\n[PRIMA] host collegato come ${prima.collegato}`);

  const esito = await checkoutComeOspite(browser, sacco);
  console.log(`\n[OSPITE] riferimento: ${esito.riferimento || '(nessuno)'}`);
  console.log(`[OSPITE] messaggio a schermo: ${JSON.stringify(esito.messaggio.slice(0, 200))}`);

  const soloAlfanumerico = t => (t || '').toUpperCase().replace(/[^A-Z0-9]/g, '');

  if (ATTESO === 'conferma') {
    if (esigi(esito.riferimento,
      `la prenotazione diretta non ha prodotto nessun riferimento. A schermo: ${JSON.stringify(esito.messaggio.slice(0, 300))}`)) {
      const impronta = esito.riferimento.slice(0, 8).toUpperCase();
      esigi(!soloAlfanumerico(prima.testo).includes(impronta),
        `il pannello dell'host conteneva gia' ${impronta} PRIMA: la prova non dimostrerebbe niente`);

      if (esito.voucherHref) {
        await apriVoucher(browser, esito.voucherHref, esito.riferimento, sacco);
        console.log(`\n[VOUCHER] aperto dal link della conferma: ${esito.voucherHref.slice(0, 60)}...`);
      }

      const dopo = await elencoDellHost(browser, sacco);
      esigi(soloAlfanumerico(dopo.testo).includes(impronta),
        `L'OSPITE HA PRENOTATO (${esito.riferimento}) E L'HOST NON LA VEDE: il suo pannello dice ` +
        JSON.stringify(dopo.testo.slice(0, 300)));
      for (const giorno of [fraOggiPiu(GIORNI_BASE), fraOggiPiu(GIORNI_BASE + 3)]) {
        esigi(dopo.testo.includes(giorno),
          `l'host vede la prenotazione ma non la data ${giorno} scelta dall'ospite`);
      }
    }
  } else {
    esigi(!esito.riferimento,
      `IL GATEWAY NON PUO' INCASSARE E IL PRODOTTO HA CONFERMATO LO STESSO: riferimento ${esito.riferimento}`);
    esigi(esito.messaggio.includes('❌'),
      `l'ospite non ha ricevuto un rifiuto leggibile: ${JSON.stringify(esito.messaggio.slice(0, 200))}`);
    const gergo = esito.messaggio.match(/\b[a-z]+(?:_[a-z]+)+\b/);
    esigi(!gergo,
      `L'OSPITE LEGGE UN CODICE INTERNO invece di una frase: "${gergo && gergo[0]}"`);
    esigi(!esito.messaggio.includes('✅'),
      'l\'ospite legge una conferma mentre il pagamento non e\' andato');

    const dopo = await elencoDellHost(browser, sacco);
    esigi(dopo.testo === prima.testo,
      'il pannello dell\'host E\' CAMBIATO dopo una prenotazione RIFIUTATA');
  }

  await browser.close();

  if (sacco.length) {
    guasti.push(`errori JavaScript nel browser (${sacco.length}): ` + [...new Set(sacco)].slice(0, 6).join(' | '));
  }

  console.log('\n====== ESITO ======');
  if (!guasti.length) {
    console.log(ATTESO === 'conferma'
      ? 'PERCORSO COMPLETO: preventivo, email fermata dal client, conferma, voucher aperto col PIN chiuso, host che vede.'
      : 'REGOLA RISPETTATA: il gateway muto non consegna niente, il rifiuto e\' pulito, l\'host non vede niente.');
    process.exit(0);
  }
  console.log(`PERCORSO INTERROTTO — ${guasti.length} guasto/i:`);
  guasti.forEach(g => console.log('  - ' + g));
  process.exit(1);
})().catch(e => { console.error('CRASH del percorso:', e); process.exit(2); });
