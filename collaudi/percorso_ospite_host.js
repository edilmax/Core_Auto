/**
 * IL PERCORSO — UNO SOLO, MA INTERO, COL BROWSER VERO. E IN DUE ATTI.
 *
 * ATTO 1 (ATTESO=conferma) — banco SENZA gateway configurato:
 *     cerca -> apri l'annuncio -> prenota -> l'HOST la vede nel suo pannello.
 * ATTO 2 (ATTESO=rifiuto)  — banco CON un gateway che non risponde:
 *     cerca -> apri l'annuncio -> prenota -> il prodotto RIFIUTA, e all'host NON
 *     compare niente. E' la regola dei soldi vista dal lato dell'ospite:
 *     **nessun voucher senza incasso.**
 *
 * Un ospite (browser 1) e un host (browser 2, sessione separata) sulla stessa macchina.
 *
 * PERCHE' ESISTE (2026-08-18). I 5845 collaudi parlano col server in Python: nessuno apre
 * una pagina, quindi `deploy/app.js` + `deploy/index.html` + `deploy/host.html` -- cioe'
 * TUTTO il codice che gira nel browser del cliente -- non venivano mai eseguiti. E anche
 * `collaudi/clickthrough_pannelli.js`, che il browser lo usa, guarda UN pannello alla volta:
 * non attraversa mai il confine fra due persone diverse. Il difetto che nessuno dei due
 * puo' vedere e' proprio quello che conta: **l'ospite prenota e all'host non arriva niente**.
 *
 * LA PROVA E' IN DUE TEMPI, e il primo tempo e' la meta' che di solito manca:
 *   PRIMA  della prenotazione: il pannello dell'host NON deve contenere quel riferimento;
 *   DOPO   la prenotazione:    lo deve contenere (atto 1) o NON deve essere cambiato (atto 2).
 * Cosi' il verde non puo' venire da una pagina che mostra sempre qualcosa: si misura la
 * DIFFERENZA, non la presenza. (Modo di rompersi n. 1, "dati effimeri": una schermata che
 * elenca cio' che trova sembra sana anche quando non ha letto niente.)
 *
 * ⛔ PERCHE' IL PAGAMENTO NON E' DENTRO NESSUNO DEI DUE ATTI, e non e' una dimenticanza.
 *    Per digitare una carta servirebbe una chiave Stripe di prova dentro il giro
 *    automatico. Questo repository e' PUBBLICO (lo e' perche' serve a CodeQL) e la regola
 *    D6 dice che le chiavi non si chiedono e non si stampano: una credenziale dentro la CI
 *    e' la cosa meno sicura che si potesse fare oggi, e vale piu' la proprieta' dell'ATTO 2
 *    -- che senza incasso non esce un voucher -- di quanto valga vedere una carta passare.
 *    Restano quindi NON provati qui, dichiarati: la pagina della carta; il ramo "paga in
 *    struttura" (il suo anticipo passa dal gateway); il bonifico verso l'host.
 *    L'aspetto delle pagine non lo guarda questo: lo fanno `test_visivo.js` e `a11y_static.js`.
 *
 * ⛔ E I DUE BANCHI NON SONO LO STESSO BANCO CON UN INTERRUTTORE:
 *    · chiave VUOTA  -> il gateway non e' configurato: il prodotto prevede il modo diretto
 *      (fase59_concierge lo dichiara: "il modo diretto SENZA Stripe configurato resta
 *      legittimo e invariato") e la prenotazione si conferma;
 *    · chiave FINTA  -> il gateway c'e' ma non risponde: scatta il fail-safe «Stripe giu' =
 *      soggiorno gratis», il blocco della stanza viene RILASCIATO e si risponde 503.
 *    Sono due configurazioni vere, non un trucco: percio' l'una fa da prova al contrario
 *    dell'altra, senza rompere niente a mano.
 *
 * Uso:
 *     ATTO 1:  STRIPE_SECRET_KEY= python collaudi/avvia_server_visivo.py 8097
 *              BASE_VISIVO=http://127.0.0.1:8097 ATTESO=conferma node collaudi/percorso_ospite_host.js
 *     ATTO 2:  python collaudi/avvia_server_visivo.py 8099        (chiave finta di serie)
 *              BASE_VISIVO=http://127.0.0.1:8099 ATTESO=rifiuto  node collaudi/percorso_ospite_host.js
 * Uscita 0 = il percorso e' andato come deve. Uscita 1 = si e' rotto, e dove.
 */
const { chromium } = require('playwright');

const BASE = process.env.BASE_VISIVO || 'http://127.0.0.1:8099';
const ATTESO = (process.env.ATTESO || 'conferma').trim();
const EMAIL_OSPITE = 'ospite.percorso@visivo.it';
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

// Ogni pagina porta con se' il proprio raccoglitore di errori JavaScript: un TypeError in
// un gestore di click non fa cadere il browser, e senza questo passerebbe inosservato.
function sorveglia(page, dove, sacco) {
  page.on('pageerror', e => sacco.push(`${dove}: ${String(e).slice(0, 160)}`));
  page.on('console', m => {
    if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) {
      sacco.push(`${dove} (console): ${m.text().slice(0, 160)}`);
    }
  });
}

/** Apre il pannello dell'host con una sessione tutta sua e ne restituisce l'elenco prenotazioni. */
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
  // l'elenco si riempie con una chiamata dopo il caricamento: si aspetta che smetta di cambiare
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

/** L'ospite: cerca, apre l'annuncio, prenota. Torna il riferimento (se c'e') e cio' che legge. */
async function prenotaComeOspite(browser, sacco) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  sorveglia(page, 'OSPITE', sacco);
  const fallito = { riferimento: null, messaggio: '', arrivatoInFondo: false };

  await page.goto(BASE + '/?lang=it', { waitUntil: 'domcontentloaded', timeout: 20000 });
  await page.waitForSelector('#citta', { timeout: 20000 });
  await page.fill('#citta', 'Roma');
  await page.fill('#checkin', fraOggiPiu(7));
  await page.fill('#checkout', fraOggiPiu(10));
  await page.click('#btnCerca');

  const trovato = await page.waitForSelector('#risultati button[data-slug]', { timeout: 20000 })
    .then(() => true).catch(() => false);
  if (!esigi(trovato, 'la ricerca "Roma" non ha restituito nessun annuncio: il percorso si ferma qui')) {
    await ctx.close();
    return fallito;
  }
  await page.click('#risultati button[data-slug]');

  const modale = await page.waitForSelector('#modal.open', { timeout: 20000 })
    .then(() => true).catch(() => false);
  if (!esigi(modale, 'il riquadro di prenotazione non si e\' aperto dopo il clic sull\'annuncio')) {
    await ctx.close();
    return fallito;
  }

  // Il riquadro del prezzo dev'esserci ed essere pieno: se il preventivo non arriva,
  // "Prenota" prenoterebbe il nulla (`QUOTE` vuoto fa uscire subito da prenota()).
  const preventivo = ((await page.innerText('#mQuote').catch(() => '')) || '').trim();
  esigi(preventivo.length > 40, `il preventivo nel checkout e' quasi vuoto: ${JSON.stringify(preventivo.slice(0, 120))}`);

  await page.click('#btnPrenota');
  await page.waitForSelector('#bkEmail', { timeout: 20000 });
  await page.fill('#bkEmail', EMAIL_OSPITE);
  await page.click('#bkGo');

  // La risposta arriva dentro #mMsg: o la conferma "✅ ... (riferimento)", o un "❌ motivo".
  // Si aspetta finche' UNA delle due compare: NON si prende la prima lettura, che sarebbe
  // ancora il modulo dell'email, e non si smette al primo giro, che direbbe "ne' l'una ne'
  // l'altra" solo perche' la rete e' stata lenta.
  let messaggio = '', riferimento = null, deciso = false;
  for (let i = 0; i < 40 && !deciso; i++) {
    await page.waitForTimeout(500);
    messaggio = ((await page.innerText('#mMsg').catch(() => '')) || '').trim();
    const m = messaggio.match(/\(([0-9a-zA-Z_-]{6,})\)/);
    if (m) { riferimento = m[1]; deciso = true; }
    else if (messaggio.includes('❌')) { deciso = true; }
  }
  esigi(deciso, `dopo la richiesta di prenotazione l'ospite non ha ricevuto ne' una conferma ne' un rifiuto. A schermo: ${JSON.stringify(messaggio.slice(0, 300))}`);
  await ctx.close();
  return { riferimento, messaggio, arrivatoInFondo: deciso };
}

(async () => {
  console.log(`====== IL PERCORSO (atto: ${ATTESO === 'conferma' ? 'LA PRENOTAZIONE ARRIVA ALL\'HOST' : 'SENZA INCASSO NON ESCE NIENTE'}) ======`);
  console.log('server: ' + BASE);
  const sacco = [];
  const browser = await chromium.launch();

  // ---- TEMPO 1: com'e' il pannello dell'host PRIMA -----------------------------------
  const prima = await elencoDellHost(browser, sacco);
  esigi(prima.collegato.includes('@'),
    `l'host non risulta collegato al suo pannello (mostrato: ${JSON.stringify(prima.collegato)})`);
  console.log(`\n[PRIMA] host collegato come ${prima.collegato}`);
  console.log(`[PRIMA] elenco prenotazioni: ${JSON.stringify(prima.testo.slice(0, 200))}`);

  // ---- L'OSPITE PROVA A PRENOTARE ------------------------------------------------------
  const esito = await prenotaComeOspite(browser, sacco);
  console.log(`\n[OSPITE] riferimento: ${esito.riferimento || '(nessuno)'}`);
  console.log(`[OSPITE] messaggio a schermo: ${JSON.stringify(esito.messaggio.slice(0, 200))}`);

  // L'host NON vede il riferimento grezzo: vede il codice che l'ospite si porta al
  // check-in, raggruppato per essere leggibile (es. "BVIP-C69D-0E20"). Si confronta
  // quindi la SOSTANZA -- le cifre -- e non la punteggiatura, che e' presentazione e puo'
  // cambiare senza che niente sia rotto. Un collaudo che pretende la formattazione esatta
  // diventa rosso al primo ritocco grafico e insegna a ignorare il rosso.
  const soloAlfanumerico = t => (t || '').toUpperCase().replace(/[^A-Z0-9]/g, '');

  if (ATTESO === 'conferma') {
    if (esigi(esito.riferimento,
      `la prenotazione non ha prodotto nessun riferimento. Messaggio a schermo: ${JSON.stringify(esito.messaggio.slice(0, 300))}`)) {
      const impronta = esito.riferimento.slice(0, 8).toUpperCase();
      esigi(!soloAlfanumerico(prima.testo).includes(impronta),
        `il pannello dell'host conteneva gia' ${impronta} PRIMA che l'ospite prenotasse: ` +
        'la seconda meta\' della prova non dimostrerebbe niente');

      const dopo = await elencoDellHost(browser, sacco);
      console.log(`\n[DOPO] elenco prenotazioni: ${JSON.stringify(dopo.testo.slice(0, 400))}`);
      esigi(soloAlfanumerico(dopo.testo).includes(impronta),
        `L'OSPITE HA PRENOTATO (${esito.riferimento}) E L'HOST NON LA VEDE: il suo pannello dice ` +
        JSON.stringify(dopo.testo.slice(0, 300)));
      esigi(dopo.testo !== prima.testo,
        'il pannello dell\'host mostra ESATTAMENTE lo stesso testo di prima: non ha riletto niente');
      // Non basta che compaia UNA riga: devono essere LE DATE che l'ospite ha scelto. E' il
      // controllo che smaschera un pannello che mostra la prenotazione sbagliata.
      for (const giorno of [fraOggiPiu(7), fraOggiPiu(10)]) {
        esigi(dopo.testo.includes(giorno),
          `l'host vede la prenotazione ma non la data ${giorno} scelta dall'ospite`);
      }
    }
  } else {
    // ATTO 2 — la regola dei soldi vista dall'ospite: se l'incasso non si puo' fare,
    // non deve uscire NIENTE che valga come prenotazione.
    esigi(!esito.riferimento,
      `IL GATEWAY NON PUO' INCASSARE E IL PRODOTTO HA CONFERMATO LO STESSO: ` +
      `riferimento ${esito.riferimento} consegnato all'ospite. E' "soggiorno gratis": ` +
      'camera bloccata, voucher valido, incasso zero.');
    esigi(esito.messaggio.includes('❌'),
      `l'ospite non ha ricevuto un rifiuto leggibile: a schermo c'e' ${JSON.stringify(esito.messaggio.slice(0, 200))}`);
    // ⛔ E "leggibile" vuol dire in ITALIANO, non in gergo nostro. Il 2026-08-18 qui c'era
    // scritto `pagamento_non_disponibile` -- il codice interno -- in faccia a chi stava
    // pagando. I nostri codici hanno tutti la stessa forma (parole minuscole unite da un
    // trattino basso) e nessuna frase vera ne contiene: percio' basta cercarla. E' una
    // guardia sulla CLASSE, non su quel codice: vale anche per i codici che non esistono
    // ancora, ed e' l'unico modo di non riscoprirlo da un cliente.
    const gergo = esito.messaggio.match(/\b[a-z]+(?:_[a-z]+)+\b/);
    esigi(!gergo,
      `L'OSPITE LEGGE UN CODICE INTERNO invece di una frase: "${gergo && gergo[0]}" ` +
      `(messaggio intero: ${JSON.stringify(esito.messaggio.slice(0, 200))})`);
    esigi(!esito.messaggio.includes('✅'),
      'l\'ospite legge una conferma mentre il pagamento non e\' andato: due messaggi opposti nella stessa schermata');

    const dopo = await elencoDellHost(browser, sacco);
    console.log(`\n[DOPO] elenco prenotazioni: ${JSON.stringify(dopo.testo.slice(0, 400))}`);
    esigi(dopo.testo === prima.testo,
      'il pannello dell\'host E\' CAMBIATO dopo una prenotazione RIFIUTATA: ' +
      `prima ${JSON.stringify(prima.testo.slice(0, 200))} · dopo ${JSON.stringify(dopo.testo.slice(0, 200))}`);
  }

  await browser.close();

  if (sacco.length) {
    guasti.push(`errori JavaScript nel browser (${sacco.length}): ` + [...new Set(sacco)].slice(0, 6).join(' | '));
  }

  console.log('\n====== ESITO ======');
  if (!guasti.length) {
    console.log(ATTESO === 'conferma'
      ? 'PERCORSO COMPLETO: l\'ospite ha prenotato e l\'host la vede nel suo pannello.'
      : 'REGOLA RISPETTATA: senza incasso l\'ospite non riceve niente e all\'host non compare niente.');
    process.exit(0);
  }
  console.log(`PERCORSO INTERROTTO — ${guasti.length} guasto/i:`);
  guasti.forEach(g => console.log('  - ' + g));
  process.exit(1);
})().catch(e => { console.error('CRASH del percorso:', e); process.exit(2); });
