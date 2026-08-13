/* BookinVIP — app.js: FONTE UNICA (Single Source of Truth) delle funzioni condivise
   dalle 3 pagine (index=Ospite, host.html, admin.html).
   Prima ogni pagina aveva la SUA copia (3 tabelle valute, 5 funzioni di escape,
   3 involucri di rete, 3 rilevamenti lingua, 3 scudi): copie = divergenza garantita
   (lezione del semaforo). Le pagine importano da qui con ALIAS locali:
       const esc = BV.esc;   const money = BV.money;   ...
   cosi' i punti d'uso restano identici e la logica vive in UN posto solo.
   Zero dipendenze, vanilla JS, servito come statico da deploy/ (CSP: script-src 'self'). */
(function(){
  const BV = {};

  /* ── ESCAPE DI SICUREZZA (copertura piena: & < > " ') ─────────────────────────
     Regola della piattaforma: escape all'USCITA su TUTTO cio' che finisce in
     innerHTML o dentro un attributo (anche onclick). Le mezze-misure (togliere
     solo < e >) sono vietate: sembrano una difesa e non lo sono. */
  const _ESC = {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'};
  BV.esc = function(s){ return String(s==null?'':s).replace(/[&<>"']/g, function(c){ return _ESC[c]; }); };

  /* ── OCCHIELLO password (mostra/nascondi) — FONTE UNICA, coerente su OGNI pagina.
     Trova ogni <input type="password"> e ci mette accanto un 👁 che alterna
     password<->text. Idempotente (data-occhio), sicuro (nessun valore stampato).
     Chiamala una volta a fine pagina: vale per tutti gli input, anche futuri. ── */
  BV.occhielli = function(root){
    root = root || document;
    var lista = root.querySelectorAll('input[type="password"]');
    for(var i=0;i<lista.length;i++){ (function(inp){
      if(inp.getAttribute('data-occhio')) return;
      inp.setAttribute('data-occhio','1');
      var b = document.createElement('button');
      b.type='button'; b.textContent='👁';
      b.setAttribute('aria-label','Mostra o nascondi la password');
      b.title='Mostra/nascondi';
      b.style.cssText='margin-left:.3rem;background:transparent;border:0;cursor:pointer;font-size:1.05rem;opacity:.55;vertical-align:middle;padding:.1rem .2rem';
      b.onclick=function(){
        var mostra = inp.type==='password';
        inp.type = mostra ? 'text':'password';
        b.style.opacity = mostra ? '1':'.55';
        b.textContent = mostra ? '🙈':'👁';
      };
      if(inp.parentNode) inp.parentNode.insertBefore(b, inp.nextSibling);
    })(lista[i]); }
  };

  /* ── i18n MODULARE (fonte unica della RISOLUZIONE, i dizionari restano nelle pagine) ──
     Catena di fallback DICHIARATA NEI DATI, non cablata nel codice: il dizionario puo'
     portare `tr._fallback = {"pt-br":"pt", "*":"en"}` e aggiungere una lingua (anche
     parziale) = SOLO dati, zero modifiche al core. Risoluzione: lingua richiesta ->
     catena dichiarata -> '*' -> chiave nuda (mai stringhe vuote in pagina).
     Anti-ciclo: ogni lingua visitata una volta sola. */
  BV.t = function(tr, lang, chiave){
    if(!tr) return chiave;
    var fb = tr._fallback || {};
    var l = lang, visti = {};
    while(l && !visti[l]){
      visti[l] = 1;
      var d = tr[l];
      if(d && d[chiave] != null) return d[chiave];
      l = fb[l] || fb['*'] || null;
    }
    return chiave;
  };

  /* ── VALUTE (tabella unica: simbolo, esponente, nome) ──────────────────────────
     L'host prezza nella SUA moneta; l'ospite paga in quella (like-for-like).
     Esponente 0 per JPY/KRW/VND/CLP/ISK (niente decimali). */
  BV.VALUTE = {
    EUR:{s:'€',e:2,n:'Euro'}, USD:{s:'$',e:2,n:'US Dollar'}, GBP:{s:'£',e:2,n:'British Pound'},
    CHF:{s:'CHF',e:2,n:'Swiss Franc'}, THB:{s:'฿',e:2,n:'Thai Baht'}, JPY:{s:'¥',e:0,n:'Japanese Yen'},
    AUD:{s:'A$',e:2,n:'Australian Dollar'}, CAD:{s:'C$',e:2,n:'Canadian Dollar'},
    AED:{s:'AED',e:2,n:'UAE Dirham'}, SGD:{s:'S$',e:2,n:'Singapore Dollar'},
    CNY:{s:'CN¥',e:2,n:'Chinese Yuan'}, HKD:{s:'HK$',e:2,n:'Hong Kong Dollar'},
    MXN:{s:'MX$',e:2,n:'Mexican Peso'}, BRL:{s:'R$',e:2,n:'Brazilian Real'},
    ZAR:{s:'R',e:2,n:'South African Rand'}, IDR:{s:'Rp',e:2,n:'Indonesian Rupiah'},
    KRW:{s:'₩',e:0,n:'Korean Won'}, INR:{s:'₹',e:2,n:'Indian Rupee'},
    NZD:{s:'NZ$',e:2,n:'NZ Dollar'}, SEK:{s:'kr',e:2,n:'Swedish Krona'},
    NOK:{s:'kr',e:2,n:'Norwegian Krone'}, DKK:{s:'kr',e:2,n:'Danish Krone'},
    PLN:{s:'zł',e:2,n:'Polish Zloty'}, TRY:{s:'₺',e:2,n:'Turkish Lira'},
    VND:{s:'₫',e:0,n:'Vietnamese Dong'}, CLP:{s:'CLP$',e:0,n:'Chilean Peso'},
    ISK:{s:'kr',e:0,n:'Icelandic Krona'}
  };
  BV.valExp = function(v){ return (BV.VALUTE[v] && BV.VALUTE[v].e!=null) ? BV.VALUTE[v].e : 2; };
  BV.valSym = function(v){ return (BV.VALUTE[v] && BV.VALUTE[v].s) || v || ''; };
  BV.money = function(cents, v){ v=v||'EUR'; const e=BV.valExp(v); return BV.valSym(v)+' '+((cents||0)/Math.pow(10,e)).toFixed(e); };
  BV.toCents = function(maj, v){ const e=BV.valExp(v); return Math.round((parseFloat(maj)||0)*Math.pow(10,e)); };
  BV.fromCents = function(cents, v){ const e=BV.valExp(v); return (cents||0)/Math.pow(10,e); };

  /* ── DATE: 'YYYY-MM-DD' in ora LOCALE, oggi+N giorni. I default dei form si
     calcolano da QUI: mai date scritte fisse nell'HTML (invecchiano e diventano
     passate, e ogni ricerca partirebbe sbagliata). ── */
  BV.dataISO = function(giorni){
    const d = new Date(); d.setDate(d.getDate() + (giorni||0));
    const p = function(n){ return String(n).padStart(2,'0'); };
    return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate());
  };

  /* ── LINGUA iniziale: 1) scelta salvata 2) lingua del browser 3) inglese ───── */
  BV.linguaIniziale = function(supportate){
    try{ const s=localStorage.getItem('lang'); if(s && supportate.indexOf(s)>=0) return s; }catch(e){}
    const cand=(navigator.languages && navigator.languages.length)?navigator.languages:[navigator.language||'en'];
    for(const l of cand){ const b=String(l||'').slice(0,2).toLowerCase(); if(supportate.indexOf(b)>=0) return b; }
    return 'en';
  };

  /* ── RETE: timeout + esiti onesti ──────────────────────────────────────────────
     Senza tempo massimo una rete che "pende" lascia l'attesa per sempre: 15s poi
     abort -> 'rete_lenta'. __TEMPO_MAX_MS = override per i test di caos.
     getJson/post NON sollevano MAI: ogni esito e' un oggetto che il chiamante sa
     leggere (.errore / .status). Guardia !Array.isArray: un array JSON valido e'
     typeof 'object' e senza guardia diventava un "falso vuoto" nei chiamanti. */
  BV.fetchTempo = async function(url, opts){
    const ctl = new AbortController();
    const t = setTimeout(function(){ ctl.abort(); }, (window.__TEMPO_MAX_MS || 15000));
    try{ return await fetch(url, Object.assign({}, opts, {signal:ctl.signal})); }
    finally{ clearTimeout(t); }
  };
  BV.codRete = function(e){ return (e && e.name==='AbortError') ? 'rete_lenta' : 'rete_non_raggiungibile'; };
  BV.getJson = async function(url, opts){
    let r;
    try{ r = await BV.fetchTempo(url, opts); }
    catch(e){ return {ok:false, errore:BV.codRete(e), _http:0}; }
    let d = null;
    try{ d = await r.json(); }catch(e){ d = null; }
    if(d && typeof d === 'object' && !Array.isArray(d)){ d._http = r.status; return d; }
    return {ok:false, _http:r.status, errore: r.ok ? 'risposta_non_valida' : ('errore_server_'+r.status)};
  };
  BV.post = async function(url, body, headers){
    let res;
    try{
      res = await BV.fetchTempo(url, {method:'POST',
        headers:Object.assign({'Content-Type':'application/json'}, headers||{}),
        body:JSON.stringify(body)});
    }catch(e){ return {status:0, data:{errore:BV.codRete(e)}}; }
    let data = null;
    try{ data = await res.json(); }catch(e){ data = null; }
    if(!data || typeof data !== 'object' || Array.isArray(data)){
      data = {errore: res.ok ? 'risposta_non_valida' : ('errore_server_'+res.status)};
    }
    return {status:res.status, data:data};
  };

  /* frasi GENTILI (8 lingue) per i guasti di rete/server: l'utente non legge mai
     codici tecnici. I codici LOGICI del backend passano invariati (gia' onesti). */
  BV.ERR_FRASI = {
    it:{rete:'Non riesco a contattare il server. Controlla la connessione e riprova.',lenta:'La connessione è lenta: ci sta mettendo troppo. Riprova.',server:'Il servizio ha un problema momentaneo. Riprova tra poco.',risposta:'Risposta inattesa dal server. Riprova.'},
    en:{rete:'Cannot reach the server. Check your connection and try again.',lenta:'The connection is slow: it took too long. Please try again.',server:'The service has a temporary problem. Try again shortly.',risposta:'Unexpected reply from the server. Please try again.'},
    es:{rete:'No puedo contactar con el servidor. Comprueba tu conexión e inténtalo de nuevo.',lenta:'La conexión es lenta: tardó demasiado. Inténtalo de nuevo.',server:'El servicio tiene un problema temporal. Inténtalo en un momento.',risposta:'Respuesta inesperada del servidor. Inténtalo de nuevo.'},
    fr:{rete:'Impossible de joindre le serveur. Vérifiez votre connexion et réessayez.',lenta:'La connexion est lente : cela a pris trop de temps. Réessayez.',server:'Le service a un problème momentané. Réessayez dans un instant.',risposta:'Réponse inattendue du serveur. Réessayez.'},
    de:{rete:'Server nicht erreichbar. Prüfe deine Verbindung und versuche es erneut.',lenta:'Die Verbindung ist langsam: es hat zu lange gedauert. Bitte erneut versuchen.',server:'Der Dienst hat ein vorübergehendes Problem. Versuche es gleich noch einmal.',risposta:'Unerwartete Antwort vom Server. Bitte erneut versuchen.'},
    pt:{rete:'Não consigo contactar o servidor. Verifique a ligação e tente novamente.',lenta:'A ligação está lenta: demorou demasiado. Tente novamente.',server:'O serviço tem um problema momentâneo. Tente novamente daqui a pouco.',risposta:'Resposta inesperada do servidor. Tente novamente.'},
    ja:{rete:'サーバーに接続できません。通信環境を確認して、もう一度お試しください。',lenta:'接続が遅く、時間がかかりすぎました。もう一度お試しください。',server:'サービスに一時的な問題があります。しばらくしてからお試しください。',risposta:'サーバーから予期しない応答がありました。もう一度お試しください。'},
    zh:{rete:'无法连接服务器。请检查网络后重试。',lenta:'网络较慢，请求超时。请重试。',server:'服务暂时出现问题，请稍后重试。',risposta:'服务器返回了意外的响应。请重试。'}
  };
  // MESSAGGI DEI CODICI DEL SERVER (registrazione/login + i moduli pubblici): prima il
  // codice grezzo (es. 'credenziali_non_valide') finiva sotto gli occhi dell'utente. Ora
  // ogni codice ha una frase chiara che DICE COSA FARE, in 8 lingue. Distingue "email
  // gia' registrata" (-> accedi) da "credenziali non valide" (-> password dimenticata?).
  // 2026-07-28: aggiunti i 7 codici che restavano grezzi in faccia all'utente —
  // 'account_sospeso' (login di un host sospeso) e i sei del preventivo via email
  // (campi_mancanti, non_disponibile, gia_inviato_riprova_piu_tardi,
  // troppe_richieste_per_questa_email, email_non_disponibile, invio_fallito).
  // Guardia: test_happy_moduli.TestMessaggiErrorePagine (ogni codice, tutte e 8 le lingue).
  BV.ERR_AUTH = {
    it:{pieno:'Quelle date sono appena state prenotate da qualcun altro. Prova con date vicine.',chiuso:'L’host ha chiuso quelle date. Prova con un altro periodo.',min_notti:'Il soggiorno è troppo breve per quelle date: servono più notti.',giorno_non_caricato:'Il calendario non è ancora aperto per quelle date. Prova con altre date.',quote_scaduta:'Il preventivo è scaduto. Rifallo per vedere il prezzo aggiornato.',quote_non_valida:'Il preventivo non è più valido. Rifallo e riprova.',alloggio_non_disponibile:'Questo alloggio non è più prenotabile. Scegline un altro.',transazioni_sospese:'I pagamenti sono sospesi per un controllo tecnico. Riprova tra poco.',credito_gia_usato:'Il credito è già stato usato su un’altra prenotazione. Rifai il preventivo.',service_unavailable:'Il servizio ha un problema momentaneo. Riprova tra poco.',parametri_non_validi:'Alcuni dati non sono validi: controllali e riprova.',domanda_non_attiva:'La lista d’attesa non è attiva in questo momento. Riprova più tardi.',troppi_tentativi:'Troppi tentativi ravvicinati. Attendi un momento e riprova; se non ricordi la password usa «Password dimenticata?».',credenziali_non_valide:'Email o password non corretta. Controlla, oppure usa «Password dimenticata?».',email_gia_registrata:'Questa email è già registrata. Accedi qui sotto invece di registrarti.',email_non_valida:"L'email non sembra valida: controlla che sia scritta bene (niente spazi).",password_troppo_corta:'La password deve avere almeno 8 caratteri.',line_token_non_valido:"Il token LINE Notify non è valido: è un codice senza spazi né « @ » (non un'email né un link). Lascialo vuoto se non lo usi.",wechat_webhook_non_valido:"Il webhook WeChat dev'essere un indirizzo che inizia con https:// (non un'email). Lascialo vuoto se non lo usi.",consensi_mancanti:'Per registrarti devi accettare Contratto, clausole e Privacy (le tre caselle).',contratto_aggiornato:'Il contratto è stato aggiornato: ricarica la pagina e rileggilo prima di continuare.',account_sospeso:'Il tuo account è sospeso. Scrivi a info@bookinvip.com e lo riattiviamo.',campi_mancanti:'Mancano dei dati: controlla le date e riprova.',non_disponibile:'Per quelle date non è più disponibile. Prova con date vicine.',gia_inviato_riprova_piu_tardi:'Te lo abbiamo già mandato a questo indirizzo: controlla la posta (anche lo spam).',troppe_richieste_per_questa_email:'Troppe richieste per questo indirizzo. Riprova tra un’ora.',email_non_disponibile:'Le email sono momentaneamente non disponibili. Riprova tra poco.',invio_fallito:'Non siamo riusciti a inviare l’email. Controlla l’indirizzo e riprova.',alloggio_mancante:'Scegli prima un alloggio, poi riapri il calendario dei prezzi.',date_mancanti:'Indica la data di inizio e quella di fine per vedere il calendario.',non_tuo:'Questo alloggio non è tuo: puoi vedere solo i tuoi.',range_date_non_valido:'Periodo non valido: la fine deve venire dopo l’inizio, e non si può chiedere più di un anno alla volta.'},
    en:{pieno:'Those dates were just booked by someone else. Try nearby dates.',chiuso:'The host has closed those dates. Try another period.',min_notti:'The stay is too short for those dates: more nights are required.',giorno_non_caricato:'The calendar is not open yet for those dates. Try other dates.',quote_scaduta:'The quote has expired. Get a new one to see the updated price.',quote_non_valida:'The quote is no longer valid. Get a new one and try again.',alloggio_non_disponibile:'This place can no longer be booked. Please choose another one.',transazioni_sospese:'Payments are paused for a technical check. Try again shortly.',credito_gia_usato:'The credit was already used on another booking. Get a new quote.',service_unavailable:'The service has a temporary problem. Try again shortly.',parametri_non_validi:'Some details are not valid: check them and try again.',domanda_non_attiva:'The waiting list is not active right now. Please try again later.',troppi_tentativi:'Too many attempts in a row. Wait a moment and try again; if you forgot your password use “Forgot password?”.',credenziali_non_valide:'Wrong email or password. Check them, or use “Forgot password?”.',email_gia_registrata:'This email is already registered. Log in below instead of signing up.',email_non_valida:'That email doesn’t look valid: check the spelling (no spaces).',password_troppo_corta:'The password must be at least 8 characters.',line_token_non_valido:'The LINE Notify token isn’t valid: it’s a code with no spaces or “@” (not an email or a link). Leave it empty if you don’t use it.',wechat_webhook_non_valido:'The WeChat webhook must be an address starting with https:// (not an email). Leave it empty if you don’t use it.',consensi_mancanti:'To sign up you must accept the Agreement, the clauses and the Privacy notice (all three boxes).',contratto_aggiornato:'The agreement was updated: reload the page and read it again before continuing.',account_sospeso:'Your account is suspended. Write to info@bookinvip.com and we’ll reactivate it.',campi_mancanti:'Some details are missing: check the dates and try again.',non_disponibile:'It is no longer available for those dates. Try nearby dates.',gia_inviato_riprova_piu_tardi:'We already sent it to this address: check your inbox (and the spam folder).',troppe_richieste_per_questa_email:'Too many requests for this address. Please try again in an hour.',email_non_disponibile:'Email sending is temporarily unavailable. Try again shortly.',invio_fallito:'We could not send the email. Check the address and try again.',alloggio_mancante:'Pick a property first, then open the price calendar again.',date_mancanti:'Enter a start date and an end date to see the calendar.',non_tuo:'This property isn’t yours: you can only view your own.',range_date_non_valido:'Invalid period: the end date must come after the start date, and you can ask for at most one year at a time.'},
    es:{pieno:'Esas fechas acaban de ser reservadas por otra persona. Prueba fechas cercanas.',chiuso:'El anfitrión ha cerrado esas fechas. Prueba con otro periodo.',min_notti:'La estancia es demasiado corta para esas fechas: hacen falta más noches.',giorno_non_caricato:'El calendario aún no está abierto para esas fechas. Prueba otras fechas.',quote_scaduta:'El presupuesto ha caducado. Haz uno nuevo para ver el precio actualizado.',quote_non_valida:'El presupuesto ya no es válido. Haz uno nuevo e inténtalo de nuevo.',alloggio_non_disponibile:'Este alojamiento ya no se puede reservar. Elige otro.',transazioni_sospese:'Los pagos están pausados por una revisión técnica. Inténtalo en un momento.',credito_gia_usato:'El crédito ya se usó en otra reserva. Haz un presupuesto nuevo.',service_unavailable:'El servicio tiene un problema temporal. Inténtalo en un momento.',parametri_non_validi:'Algunos datos no son válidos: revísalos e inténtalo de nuevo.',domanda_non_attiva:'La lista de espera no está activa ahora mismo. Inténtalo más tarde.',troppi_tentativi:'Demasiados intentos seguidos. Espera un momento y reinténtalo; si olvidaste la contraseña usa «¿Contraseña olvidada?».',credenziali_non_valide:'Email o contraseña incorrectos. Compruébalos o usa «¿Contraseña olvidada?».',email_gia_registrata:'Este email ya está registrado. Inicia sesión abajo en vez de registrarte.',email_non_valida:'El email no parece válido: revisa que esté bien escrito (sin espacios).',password_troppo_corta:'La contraseña debe tener al menos 8 caracteres.',line_token_non_valido:'El token de LINE Notify no es válido: es un código sin espacios ni «@» (no un email ni un enlace). Déjalo vacío si no lo usas.',wechat_webhook_non_valido:'El webhook de WeChat debe ser una dirección que empiece por https:// (no un email). Déjalo vacío si no lo usas.',consensi_mancanti:'Para registrarte debes aceptar el Contrato, las cláusulas y la Privacidad (las tres casillas).',contratto_aggiornato:'El contrato se ha actualizado: recarga la página y léelo de nuevo antes de continuar.',account_sospeso:'Tu cuenta está suspendida. Escríbenos a info@bookinvip.com y la reactivamos.',campi_mancanti:'Faltan datos: revisa las fechas e inténtalo de nuevo.',non_disponibile:'Ya no está disponible en esas fechas. Prueba con fechas cercanas.',gia_inviato_riprova_piu_tardi:'Ya lo enviamos a esta dirección: revisa tu correo (y la carpeta de spam).',troppe_richieste_per_questa_email:'Demasiadas solicitudes para esta dirección. Inténtalo dentro de una hora.',email_non_disponibile:'El envío de correo no está disponible ahora mismo. Inténtalo en un momento.',invio_fallito:'No hemos podido enviar el correo. Revisa la dirección e inténtalo de nuevo.',alloggio_mancante:'Elige primero un alojamiento y vuelve a abrir el calendario de precios.',date_mancanti:'Indica la fecha de inicio y la de fin para ver el calendario.',non_tuo:'Este alojamiento no es tuyo: solo puedes ver los tuyos.',range_date_non_valido:'Periodo no válido: la fecha de fin debe ser posterior a la de inicio, y no se puede pedir más de un año a la vez.'},
    fr:{pieno:'Ces dates viennent d’être réservées par quelqu’un d’autre. Essayez des dates proches.',chiuso:'L’hôte a fermé ces dates. Essayez une autre période.',min_notti:'Le séjour est trop court pour ces dates : il faut plus de nuits.',giorno_non_caricato:'Le calendrier n’est pas encore ouvert pour ces dates. Essayez d’autres dates.',quote_scaduta:'Le devis a expiré. Refaites-le pour voir le prix à jour.',quote_non_valida:'Le devis n’est plus valable. Refaites-le et réessayez.',alloggio_non_disponibile:'Ce logement n’est plus réservable. Choisissez-en un autre.',transazioni_sospese:'Les paiements sont suspendus pour un contrôle technique. Réessayez bientôt.',credito_gia_usato:'Le crédit a déjà été utilisé sur une autre réservation. Refaites un devis.',service_unavailable:'Le service a un problème momentané. Réessayez dans un instant.',parametri_non_validi:'Certaines informations ne sont pas valides : vérifiez-les et réessayez.',domanda_non_attiva:'La liste d’attente n’est pas active pour le moment. Réessayez plus tard.',troppi_tentativi:'Trop de tentatives rapprochées. Attendez un instant puis réessayez ; si vous avez oublié le mot de passe, utilisez « Mot de passe oublié ? ».',credenziali_non_valide:'E-mail ou mot de passe incorrect. Vérifiez, ou utilisez « Mot de passe oublié ? ».',email_gia_registrata:'Cet e-mail est déjà enregistré. Connectez-vous ci-dessous au lieu de créer un compte.',email_non_valida:'Cet e-mail ne semble pas valide : vérifiez l’orthographe (sans espaces).',password_troppo_corta:'Le mot de passe doit comporter au moins 8 caractères.',line_token_non_valido:'Le jeton LINE Notify n’est pas valide : c’est un code sans espaces ni « @ » (ni e-mail ni lien). Laissez-le vide si vous ne l’utilisez pas.',wechat_webhook_non_valido:'Le webhook WeChat doit être une adresse commençant par https:// (pas un e-mail). Laissez-le vide si vous ne l’utilisez pas.',consensi_mancanti:'Pour vous inscrire, vous devez accepter le Contrat, les clauses et la Confidentialité (les trois cases).',contratto_aggiornato:'Le contrat a été mis à jour : rechargez la page et relisez-le avant de continuer.',account_sospeso:'Votre compte est suspendu. Écrivez à info@bookinvip.com et nous le réactivons.',campi_mancanti:'Des informations manquent : vérifiez les dates et réessayez.',non_disponibile:'Ce logement n’est plus disponible à ces dates. Essayez des dates proches.',gia_inviato_riprova_piu_tardi:'Nous l’avons déjà envoyé à cette adresse : vérifiez votre boîte (et les spams).',troppe_richieste_per_questa_email:'Trop de demandes pour cette adresse. Réessayez dans une heure.',email_non_disponibile:'L’envoi d’e-mails est momentanément indisponible. Réessayez bientôt.',invio_fallito:'Nous n’avons pas pu envoyer l’e-mail. Vérifiez l’adresse et réessayez.',alloggio_mancante:'Choisissez d’abord un logement, puis rouvrez le calendrier des prix.',date_mancanti:'Indiquez une date de début et une date de fin pour voir le calendrier.',non_tuo:'Ce logement n’est pas le vôtre : vous ne voyez que les vôtres.',range_date_non_valido:'Période non valide : la date de fin doit suivre celle de début, et on ne peut pas demander plus d’un an à la fois.'},
    de:{pieno:'Diese Daten wurden gerade von jemand anderem gebucht. Probieren Sie nahe Termine.',chiuso:'Der Gastgeber hat diese Daten geschlossen. Probieren Sie einen anderen Zeitraum.',min_notti:'Der Aufenthalt ist für diese Daten zu kurz: es sind mehr Nächte nötig.',giorno_non_caricato:'Der Kalender ist für diese Daten noch nicht geöffnet. Probieren Sie andere Termine.',quote_scaduta:'Das Angebot ist abgelaufen. Erstellen Sie es neu für den aktuellen Preis.',quote_non_valida:'Das Angebot ist nicht mehr gültig. Erstellen Sie es neu und versuchen Sie es erneut.',alloggio_non_disponibile:'Diese Unterkunft ist nicht mehr buchbar. Bitte wählen Sie eine andere.',transazioni_sospese:'Zahlungen sind wegen einer technischen Prüfung pausiert. Bitte gleich noch einmal versuchen.',credito_gia_usato:'Das Guthaben wurde bereits für eine andere Buchung genutzt. Bitte neu anfragen.',service_unavailable:'Der Dienst hat ein vorübergehendes Problem. Versuchen Sie es gleich noch einmal.',parametri_non_validi:'Einige Angaben sind ungültig: Bitte prüfen und erneut versuchen.',domanda_non_attiva:'Die Warteliste ist derzeit nicht aktiv. Bitte später erneut versuchen.',troppi_tentativi:'Zu viele Versuche hintereinander. Warten Sie einen Moment und versuchen Sie es erneut; bei vergessenem Passwort „Passwort vergessen?“ nutzen.',credenziali_non_valide:'E-Mail oder Passwort falsch. Prüfen Sie es oder nutzen Sie „Passwort vergessen?“.',email_gia_registrata:'Diese E-Mail ist bereits registriert. Melden Sie sich unten an, statt sich zu registrieren.',email_non_valida:'Die E-Mail sieht ungültig aus: Prüfen Sie die Schreibweise (keine Leerzeichen).',password_troppo_corta:'Das Passwort muss mindestens 8 Zeichen haben.',line_token_non_valido:'Das LINE-Notify-Token ist ungültig: ein Code ohne Leerzeichen und ohne „@“ (keine E-Mail, kein Link). Leer lassen, wenn nicht genutzt.',wechat_webhook_non_valido:'Der WeChat-Webhook muss eine Adresse sein, die mit https:// beginnt (keine E-Mail). Leer lassen, wenn nicht genutzt.',consensi_mancanti:'Zum Registrieren müssen Sie Vertrag, Klauseln und Datenschutz akzeptieren (alle drei Kästchen).',contratto_aggiornato:'Der Vertrag wurde aktualisiert: Seite neu laden und erneut lesen, bevor Sie fortfahren.',account_sospeso:'Ihr Konto ist gesperrt. Schreiben Sie an info@bookinvip.com, wir schalten es wieder frei.',campi_mancanti:'Es fehlen Angaben: Prüfen Sie die Daten und versuchen Sie es erneut.',non_disponibile:'Für diese Daten nicht mehr verfügbar. Probieren Sie Termine in der Nähe.',gia_inviato_riprova_piu_tardi:'Wir haben sie an diese Adresse bereits gesendet: Prüfen Sie Ihr Postfach (auch Spam).',troppe_richieste_per_questa_email:'Zu viele Anfragen für diese Adresse. Versuchen Sie es in einer Stunde erneut.',email_non_disponibile:'Der E-Mail-Versand ist vorübergehend nicht verfügbar. Bitte gleich noch einmal versuchen.',invio_fallito:'Die E-Mail konnte nicht gesendet werden. Prüfen Sie die Adresse und versuchen Sie es erneut.',alloggio_mancante:'Wählen Sie zuerst eine Unterkunft und öffnen Sie dann den Preiskalender erneut.',date_mancanti:'Geben Sie ein Startdatum und ein Enddatum an, um den Kalender zu sehen.',non_tuo:'Diese Unterkunft gehört Ihnen nicht: Sie sehen nur Ihre eigenen.',range_date_non_valido:'Ungültiger Zeitraum: Das Enddatum muss nach dem Startdatum liegen, und es ist höchstens ein Jahr auf einmal möglich.'},
    pt:{pieno:'Essas datas acabaram de ser reservadas por outra pessoa. Experimenta datas próximas.',chiuso:'O anfitrião fechou essas datas. Experimenta outro período.',min_notti:'A estadia é demasiado curta para essas datas: são precisas mais noites.',giorno_non_caricato:'O calendário ainda não está aberto para essas datas. Experimenta outras datas.',quote_scaduta:'O orçamento expirou. Faz um novo para veres o preço atualizado.',quote_non_valida:'O orçamento já não é válido. Faz um novo e tenta de novo.',alloggio_non_disponibile:'Este alojamento já não pode ser reservado. Escolhe outro.',transazioni_sospese:'Os pagamentos estão suspensos por uma verificação técnica. Tenta daqui a pouco.',credito_gia_usato:'O crédito já foi usado noutra reserva. Faz um novo orçamento.',service_unavailable:'O serviço tem um problema momentâneo. Tenta novamente daqui a pouco.',parametri_non_validi:'Alguns dados não são válidos: verifica-os e tenta de novo.',domanda_non_attiva:'A lista de espera não está ativa neste momento. Tenta mais tarde.',troppi_tentativi:'Demasiadas tentativas seguidas. Aguarda um momento e tenta de novo; se esqueceste a palavra-passe usa «Palavra-passe esquecida?».',credenziali_non_valide:'Email ou palavra-passe incorretos. Verifica, ou usa «Palavra-passe esquecida?».',email_gia_registrata:'Este email já está registado. Inicia sessão abaixo em vez de te registares.',email_non_valida:'O email não parece válido: verifica a escrita (sem espaços).',password_troppo_corta:'A palavra-passe deve ter pelo menos 8 caracteres.',line_token_non_valido:'O token LINE Notify não é válido: é um código sem espaços nem «@» (não um email nem um link). Deixa vazio se não o usas.',wechat_webhook_non_valido:'O webhook WeChat deve ser um endereço que começa por https:// (não um email). Deixa vazio se não o usas.',consensi_mancanti:'Para te registares tens de aceitar o Contrato, as cláusulas e a Privacidade (as três caixas).',contratto_aggiornato:'O contrato foi atualizado: recarrega a página e lê-o de novo antes de continuar.',account_sospeso:'A tua conta está suspensa. Escreve para info@bookinvip.com e reativamos.',campi_mancanti:'Faltam dados: verifica as datas e tenta de novo.',non_disponibile:'Já não está disponível nessas datas. Experimenta datas próximas.',gia_inviato_riprova_piu_tardi:'Já enviámos para este endereço: verifica o teu email (e a pasta de spam).',troppe_richieste_per_questa_email:'Demasiados pedidos para este endereço. Tenta daqui a uma hora.',email_non_disponibile:'O envio de email está indisponível de momento. Tenta daqui a pouco.',invio_fallito:'Não conseguimos enviar o email. Verifica o endereço e tenta de novo.',alloggio_mancante:'Escolhe primeiro um alojamento e volta a abrir o calendário de preços.',date_mancanti:'Indica a data de início e a de fim para veres o calendário.',non_tuo:'Este alojamento não é teu: só podes ver os teus.',range_date_non_valido:'Período inválido: a data de fim tem de ser depois da de início, e não podes pedir mais de um ano de cada vez.'},
    ja:{pieno:'その日程は先ほど他のお客様のご予約が入りました。前後の日程をお試しください。',chiuso:'ホストがその日程を閉じています。別の期間をお試しください。',min_notti:'その日程には滞在が短すぎます。もう少し長い泊数でお試しください。',giorno_non_caricato:'その日程はまだカレンダーが公開されていません。別の日程をお試しください。',quote_scaduta:'お見積りの有効期限が切れました。もう一度お取りいただくと最新の料金が表示されます。',quote_non_valida:'お見積りは無効になりました。もう一度お取りください。',alloggio_non_disponibile:'この宿はご予約いただけなくなりました。別の宿をお選びください。',transazioni_sospese:'技術的な確認のため、お支払いを一時停止しています。しばらくしてからお試しください。',credito_gia_usato:'クレジットは別のご予約で使用済みです。お見積りを取り直してください。',service_unavailable:'サービスに一時的な問題があります。しばらくしてからお試しください。',parametri_non_validi:'入力内容に誤りがあります。ご確認のうえ、もう一度お試しください。',domanda_non_attiva:'ただいまキャンセル待ちの受付を行っていません。しばらくしてからお試しください。',troppi_tentativi:'短時間に試行が多すぎます。少し待ってからお試しください。パスワードをお忘れの場合は「パスワードをお忘れですか？」をご利用ください。',credenziali_non_valide:'メールアドレスまたはパスワードが違います。ご確認いただくか、「パスワードをお忘れですか？」をご利用ください。',email_gia_registrata:'このメールアドレスは登録済みです。新規登録ではなく、下からログインしてください。',email_non_valida:'メールアドレスが正しくないようです（スペースがないかご確認ください）。',password_troppo_corta:'パスワードは8文字以上にしてください。',line_token_non_valido:'LINE Notify トークンが正しくありません。スペースや「@」を含まないコードです（メールやリンクではありません）。使わない場合は空欄で結構です。',wechat_webhook_non_valido:'WeChat の Webhook は https:// で始まるアドレスである必要があります（メールではありません）。使わない場合は空欄で結構です。',consensi_mancanti:'登録には、契約・条項・プライバシーの3つすべてに同意する必要があります。',contratto_aggiornato:'契約が更新されました。ページを再読み込みして、もう一度お読みください。',account_sospeso:'アカウントは停止中です。info@bookinvip.com までご連絡ください。再開いたします。',campi_mancanti:'情報が不足しています。日付をご確認のうえ、もう一度お試しください。',non_disponibile:'その日程ではご利用いただけなくなりました。前後の日程をお試しください。',gia_inviato_riprova_piu_tardi:'このアドレスへは送信済みです。受信トレイ（迷惑メールも）をご確認ください。',troppe_richieste_per_questa_email:'このアドレスへの送信が多すぎます。1時間ほどおいてからお試しください。',email_non_disponibile:'ただいまメール送信をご利用いただけません。しばらくしてからお試しください。',invio_fallito:'メールを送信できませんでした。アドレスをご確認のうえ、もう一度お試しください。',alloggio_mancante:'まず宿を選んでから、料金カレンダーを開いてください。',date_mancanti:'開始日と終了日を入力すると、カレンダーが表示されます。',non_tuo:'この宿はお客様のものではありません。ご自身の宿のみ表示できます。',range_date_non_valido:'期間が正しくありません。終了日は開始日より後にし、一度に1年を超える期間は指定できません。'},
    zh:{pieno:'这些日期刚被其他客人预订。请尝试相近的日期。',chiuso:'房东已关闭这些日期。请尝试其他时间段。',min_notti:'所选日期的入住晚数太少，请增加入住晚数后重试。',giorno_non_caricato:'这些日期的日历尚未开放。请尝试其他日期。',quote_scaduta:'报价已过期。请重新获取以查看最新价格。',quote_non_valida:'报价已失效。请重新获取后再试。',alloggio_non_disponibile:'该房源已无法预订。请选择其他房源。',transazioni_sospese:'支付因技术检查暂时暂停。请稍后再试。',credito_gia_usato:'该抵扣额度已用于其他预订。请重新获取报价。',service_unavailable:'服务暂时出现问题，请稍后重试。',parametri_non_validi:'部分信息无效，请检查后重试。',domanda_non_attiva:'候补名单目前未开放。请稍后再试。',troppi_tentativi:'短时间内尝试次数过多。请稍候再试；若忘记密码，请使用“忘记密码？”。',credenziali_non_valide:'邮箱或密码有误。请检查，或使用“忘记密码？”。',email_gia_registrata:'该邮箱已注册。请在下方登录，而不是重新注册。',email_non_valida:'邮箱似乎无效：请检查拼写（不要有空格）。',password_troppo_corta:'密码至少需要 8 个字符。',line_token_non_valido:'LINE Notify 令牌无效：它是一段不含空格和“@”的代码（不是邮箱或链接）。不使用可留空。',wechat_webhook_non_valido:'WeChat Webhook 必须是以 https:// 开头的地址（不是邮箱）。不使用可留空。',consensi_mancanti:'注册需同意合同、条款和隐私（三个复选框）。',contratto_aggiornato:'合同已更新：请刷新页面并重新阅读后再继续。',account_sospeso:'您的账户已被暂停。请联系 info@bookinvip.com，我们会为您恢复。',campi_mancanti:'资料不完整：请检查日期后重试。',non_disponibile:'该日期已无法预订。请尝试相近的日期。',gia_inviato_riprova_piu_tardi:'我们已向该邮箱发送过：请查看收件箱（含垃圾邮件）。',troppe_richieste_per_questa_email:'该邮箱的请求过多。请一小时后再试。',email_non_disponibile:'邮件发送暂时不可用。请稍后再试。',invio_fallito:'邮件发送失败。请检查邮箱地址后重试。',alloggio_mancante:'请先选择一个房源，然后再打开价格日历。',date_mancanti:'请填写开始日期和结束日期，以查看日历。',non_tuo:'该房源不属于您：您只能查看自己的房源。',range_date_non_valido:'时间段无效：结束日期必须晚于开始日期，且一次最多查询一年。'}
  };
  BV.fraseErrore = function(cod, lang){
    const D = BV.ERR_FRASI[lang] || BV.ERR_FRASI.en;
    if(cod==='rete_non_raggiungibile') return D.rete;
    if(cod==='rete_lenta') return D.lenta;
    if(cod==='risposta_non_valida') return D.risposta;
    if(/^errore_server_\d+$/.test(String(cod))) return D.server+' ('+String(cod).slice(14)+')';
    const A = BV.ERR_AUTH[lang] || BV.ERR_AUTH.en;   // messaggi chiari per gli errori auth
    if(A && A[cod]) return A[cod];
    return String(cod==null?'':cod);
  };

  /* ── SCUDO ANTI-DOPPIO-CLIC ────────────────────────────────────────────────────
     Mentre la chiamata e' in volo il tasto si spegne e mostra ⏳ alla STESSA
     larghezza (min-width bloccata: la riga non salta); si riaccende SEMPRE nel
     finally (anche su errore). Un tasto gia' spento non riparte. Se fn vuole che
     il tasto RESTI spento dopo il successo: btn.dataset.restaSpento='1'. */
  BV.conScudo = async function(btn, fn){
    if(!btn || btn.disabled) return;
    const label = btn.innerHTML, w = btn.offsetWidth;
    btn.disabled = true; if(w) btn.style.minWidth = w+'px';
    btn.innerHTML = '⏳';
    try{ await fn(); }
    finally{
      btn.innerHTML = label; btn.style.minWidth = '';
      if(!btn.dataset.restaSpento) btn.disabled = false;
    }
  };
  /* Avvolge i tasti GIA' cablati (l'handler originale resta la fonte): chiamare
     DOPO che tutti gli onclick sono assegnati. I tasti creati al volo nelle righe
     si avvolgono inline con conScudo. */
  BV.scudoTasti = function(ids){
    ids.forEach(function(id){ const b=document.getElementById(id);
      if(!b || typeof b.onclick!=='function') return;
      const orig=b.onclick; b.onclick=function(){ return BV.conScudo(b, function(){ return orig.call(b); }); };
    });
  };

  window.BV = BV;
})();
