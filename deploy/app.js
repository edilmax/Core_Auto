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
  BV.fraseErrore = function(cod, lang){
    const D = BV.ERR_FRASI[lang] || BV.ERR_FRASI.en;
    if(cod==='rete_non_raggiungibile') return D.rete;
    if(cod==='rete_lenta') return D.lenta;
    if(cod==='risposta_non_valida') return D.risposta;
    if(/^errore_server_\d+$/.test(String(cod))) return D.server+' ('+String(cod).slice(14)+')';
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
