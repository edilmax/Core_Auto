"""
CORE_AUTO - Fase 83: Server HTTP (la COLLA che fa uscire la Ferrari dal garage).

Critica accettata: avevamo 24 moduli backend ma NESSUN server che li espone come API, e
nessuna faccia. Questo modulo e' il collante eseguibile: cabla il SistemaCasaVIP (fase81)
e lo espone via HTTP, MULTILINGUA (clienti E host), a ZERO dipendenze (solo stdlib -
niente Flask, fedele a "gratuito e autonomo").

Due strati:
  1. RouterHTTP: PURO e testabile - `gestisci(metodo, path, query, body, headers)` ->
     (status, corpo_dict). Nessun socket: si testa come una funzione. Rotte:
       GET  /api/health
       GET  /api/lingue                      -> lingue supportate
       GET  /api/i18n?lang=xx                 -> dizionario UI+servizi+stati (per il frontend)
       GET  /api/catalogo?citta=..&lang=..    -> vetrina (servizi tradotti se lang)
       GET  /api/catalogo/<slug>?lang=..      -> dettaglio
       POST /api/concierge/quote              -> preventivo firmato (fase59)
       POST /api/concierge/book               -> prenotazione (fase59)
       POST /api/mcp                          -> JSON-RPC agenti IA (fase60)
       POST /api/host/pubblica  (X-Host-Key)  -> pubblica un alloggio (fase57)
       POST /api/host/disponibilita (X-Host-Key) -> imposta disponibilita' (fase58)
  2. server HTTP stdlib (http.server) che instrada /api/* al router e serve i file
     statici (index.html, host.html) - NON testato (I/O), thin wrapper.

I18N: il backend e' lingua-agnostico (codici servizio, cents, ISO); il frontend chiede
/api/i18n?lang=xx e rende l'interfaccia nella lingua scelta. Le risposte del catalogo
includono `servizi_label` tradotti via fase61. Cosi' clienti E host vedono tutto nella
loro lingua, a costo zero.

SOPRAVVIVENZA TOTALE: il router NON solleva MAI (eccezione -> 500); body JSON invalido ->
400; rotta ignota -> 404; host senza chiave -> 401; CORS aperto per il frontend. Stateless.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional, Tuple

from fase61_localizzazione import Localizzatore, LINGUE_SUPPORTATE

logger = logging.getLogger("core_auto.server")


# Stringhe UI per il frontend (chrome), multilingua. Fallback -> 'en' -> chiave.
ETICHETTE_UI: Dict[str, Dict[str, str]] = {
    # --- ricerca / risultati ---
    "cerca": {"it": "Cerca", "en": "Search", "es": "Buscar", "fr": "Rechercher", "de": "Suchen", "pt": "Buscar", "ja": "検索", "zh": "搜索"},
    "citta": {"it": "Città", "en": "City", "es": "Ciudad", "fr": "Ville", "de": "Stadt", "pt": "Cidade", "ja": "都市", "zh": "城市"},
    "checkin": {"it": "Check-in", "en": "Check-in", "es": "Entrada", "fr": "Arrivée", "de": "Anreise", "pt": "Entrada", "ja": "チェックイン", "zh": "入住"},
    "checkout": {"it": "Check-out", "en": "Check-out", "es": "Salida", "fr": "Départ", "de": "Abreise", "pt": "Saída", "ja": "チェックアウト", "zh": "退房"},
    "ospiti": {"it": "Ospiti", "en": "Guests", "es": "Huéspedes", "fr": "Voyageurs", "de": "Gäste", "pt": "Hóspedes", "ja": "人数", "zh": "入住人数"},
    "max_prezzo": {"it": "Max €", "en": "Max €", "es": "Máx €", "fr": "Max €", "de": "Max €", "pt": "Máx €", "ja": "上限 €", "zh": "最高 €"},
    "ph_prezzomax": {"it": "es. 150", "en": "e.g. 150", "es": "ej. 150", "fr": "ex. 150", "de": "z. B. 150", "pt": "ex. 150", "ja": "例: 150", "zh": "如 150"},
    "raggio": {"it": "Raggio", "en": "Radius", "es": "Radio", "fr": "Rayon", "de": "Umkreis", "pt": "Raio", "ja": "範囲", "zh": "范围"},
    "vicino_a_me": {"it": "Vicino a me", "en": "Near me", "es": "Cerca de mí", "fr": "Près de moi", "de": "In meiner Nähe", "pt": "Perto de mim", "ja": "現在地周辺", "zh": "附近"},
    "filtro_gratuita": {"it": "Solo cancellazione gratuita", "en": "Only free cancellation", "es": "Solo cancelación gratuita", "fr": "Uniquement annulation gratuite", "de": "Nur kostenlose Stornierung", "pt": "Só cancelamento grátis", "ja": "無料キャンセルのみ", "zh": "仅限免费取消"},
    "non_rimb": {"it": "Non rimborsabile −12%", "en": "Non-refundable −12%", "es": "No reembolsable −12%", "fr": "Non remboursable −12%", "de": "Nicht erstattbar −12%", "pt": "Não reembolsável −12%", "ja": "返金不可 −12%", "zh": "不可退款 −12%"},
    "gia_cercano": {"it": "persone cercano già a", "en": "people are already searching in", "es": "personas ya buscan en", "fr": "personnes cherchent déjà à", "de": "Personen suchen bereits in", "pt": "pessoas já procuram em", "ja": "人がすでに探しています：", "zh": "人已经在这里寻找："},
    "vicino_title": {"it": "Trova alloggi vicino a dove ti trovi ora", "en": "Find stays near where you are now", "es": "Encuentra alojamientos cerca de donde estás", "fr": "Trouvez des logements près de vous", "de": "Unterkünfte in deiner Nähe finden", "pt": "Encontre acomodações perto de você", "ja": "現在地周辺の宿泊施設を探す", "zh": "查找您当前位置附近的住宿"},
    "notte": {"it": "notte", "en": "night", "es": "noche", "fr": "nuit", "de": "Nacht", "pt": "noite", "ja": "泊", "zh": "晚"},
    "dettaglio": {"it": "Vedi dettaglio", "en": "View details", "es": "Ver detalles", "fr": "Voir détails", "de": "Details ansehen", "pt": "Ver detalhes", "ja": "詳細を見る", "zh": "查看详情"},
    "prenota": {"it": "Prenota ora", "en": "Book now", "es": "Reservar", "fr": "Réserver", "de": "Buchen", "pt": "Reservar", "ja": "今すぐ予約", "zh": "立即预订"},
    "totale": {"it": "Totale", "en": "Total", "es": "Total", "fr": "Total", "de": "Gesamt", "pt": "Total", "ja": "合計", "zh": "总计"},
    "netto": {"it": "Alloggio", "en": "Lodging", "es": "Alojamiento", "fr": "Logement", "de": "Unterkunft", "pt": "Hospedagem", "ja": "宿泊", "zh": "住宿"},
    "commissione": {"it": "Commissione", "en": "Fee", "es": "Comisión", "fr": "Commission", "de": "Gebühr", "pt": "Taxa", "ja": "手数料", "zh": "手续费"},
    "tassa": {"it": "Tassa soggiorno", "en": "City tax", "es": "Tasa turística", "fr": "Taxe de séjour", "de": "Kurtaxe", "pt": "Taxa de turismo", "ja": "宿泊税", "zh": "城市税"},
    "nessun_risultato": {"it": "Nessun alloggio trovato", "en": "No lodging found", "es": "Sin resultados", "fr": "Aucun résultat", "de": "Keine Treffer", "pt": "Nenhum resultado", "ja": "宿泊施設が見つかりません", "zh": "未找到住宿"},
    "caricamento": {"it": "Caricamento...", "en": "Loading...", "es": "Cargando...", "fr": "Chargement...", "de": "Laden...", "pt": "Carregando...", "ja": "読み込み中...", "zh": "加载中..."},
    "errore": {"it": "Errore", "en": "Error", "es": "Error", "fr": "Erreur", "de": "Fehler", "pt": "Erro", "ja": "エラー", "zh": "错误"},
    "email": {"it": "Email", "en": "Email", "es": "Correo", "fr": "E-mail", "de": "E-Mail", "pt": "E-mail", "ja": "メール", "zh": "邮箱"},
    "conferma": {"it": "Prenotazione confermata!", "en": "Booking confirmed!", "es": "¡Reserva confirmada!", "fr": "Réservation confirmée !", "de": "Buchung bestätigt!", "pt": "Reserva confirmada!", "ja": "予約が確定しました！", "zh": "预订已确认！"},
        "richiesta_inviata": {"it": "Richiesta inviata: l'host conferma entro 24h", "en": "Request sent: the host confirms within 24h", "es": "Solicitud enviada: el anfitrión confirma en 24h", "fr": "Demande envoyée : l'hôte confirme sous 24h", "de": "Anfrage gesendet: der Gastgeber bestätigt innerhalb von 24h", "pt": "Pedido enviado: o anfitrião confirma em 24h", "ja": "リクエストを送信しました：ホストが24時間以内に確定します", "zh": "请求已发送：房东将在24小时内确认"},
        "prezzo_bloccato": {"it": "Prezzo e disponibilità bloccati per te ancora", "en": "Price & availability locked for you for", "es": "Precio y disponibilidad reservados para ti aún", "fr": "Prix et disponibilité bloqués pour vous encore", "de": "Preis & Verfügbarkeit für dich reserviert noch", "pt": "Preço e disponibilidade reservados para si ainda", "ja": "価格と空室をあと", "zh": "价格与空房为您锁定还剩"},
        "affrettati": {"it": "affrettati!", "en": "hurry!", "es": "¡date prisa!", "fr": "dépêchez-vous !", "de": "beeil dich!", "pt": "despache-se!", "ja": "お急ぎください！", "zh": "抓紧！"},
        "offerta_scaduta": {"it": "Offerta scaduta — aggiorna la ricerca", "en": "Offer expired — refresh your search", "es": "Oferta caducada — actualiza la búsqueda", "fr": "Offre expirée — actualisez la recherche", "de": "Angebot abgelaufen — Suche aktualisieren", "pt": "Oferta expirada — atualize a pesquisa", "ja": "オファーの有効期限が切れました — 検索を更新してください", "zh": "优惠已过期 — 请刷新搜索"},
    "non_disp": {"it": "Non disponibile", "en": "Not available", "es": "No disponible", "fr": "Indisponible", "de": "Nicht verfügbar", "pt": "Indisponível", "ja": "空きなし", "zh": "不可预订"},
    "verificata": {"it": "verificata", "en": "verified", "es": "verificada", "fr": "vérifiée", "de": "verifiziert", "pt": "verificada", "ja": "確認済み", "zh": "已验证"},
    "dividi_amici": {"it": "Dividi tra amici:", "en": "Split with friends:", "es": "Divide con amigos:", "fr": "Partager entre amis :", "de": "Mit Freunden teilen:", "pt": "Dividir com amigos:", "ja": "友達と割り勘：", "zh": "与好友分摊："},
    "a_testa": {"it": "a testa", "en": "each", "es": "por persona", "fr": "par personne", "de": "pro Person", "pt": "por pessoa", "ja": "1人あたり", "zh": "每人"},
    "indicativo": {"it": "indicativo · la tua banca applica il suo cambio", "en": "approx. · your bank applies its own rate", "es": "aprox. · tu banco aplica su cambio", "fr": "indicatif · votre banque applique son taux", "de": "ca. · deine Bank nutzt ihren Kurs", "pt": "aprox. · seu banco aplica o câmbio dele", "ja": "目安 · 実際のレートは銀行によります", "zh": "约 · 以银行汇率为准"},
    "ota_pre": {"it": "Su un OTA pagheresti ~", "en": "On an OTA you'd pay ~", "es": "En una OTA pagarías ~", "fr": "Sur une OTA vous paieriez ~", "de": "Bei einem OTA zahltest du ~", "pt": "Numa OTA você pagaria ~", "ja": "OTAなら約", "zh": "在OTA上你要付约"},
    "risparmi": {"it": "risparmi", "en": "you save", "es": "ahorras", "fr": "vous économisez", "de": "du sparst", "pt": "você economiza", "ja": "お得", "zh": "省下"},
    # --- hero / slogan ---
    "hero_titolo": {"it": "Il tuo viaggio, senza sorprese", "en": "Your trip, no surprises", "es": "Tu viaje, sin sorpresas", "fr": "Votre voyage, sans surprises", "de": "Deine Reise, ohne Überraschungen", "pt": "Sua viagem, sem surpresas", "ja": "サプライズのない、あなたの旅", "zh": "你的旅行，没有意外"},
    "hero_sub": {"it": "Alloggi certificati · paghi il prezzo pulito · cancellazione gratuita", "en": "Certified stays · pay the clean price · free cancellation", "es": "Alojamientos certificados · pagas el precio limpio · cancelación gratuita", "fr": "Logements certifiés · payez le prix net · annulation gratuite", "de": "Zertifizierte Unterkünfte · fairer Endpreis · kostenlose Stornierung", "pt": "Acomodações certificadas · pague o preço limpo · cancelamento grátis", "ja": "認証済みの宿泊施設 · 追加料金なしの価格 · 無料キャンセル", "zh": "认证住宿 · 支付透明价格 · 免费取消"},
    "badge_commissioni": {"it": "0% commissioni all'ospite", "en": "0% guest fees", "es": "0% comisiones al huésped", "fr": "0% de frais pour le voyageur", "de": "0% Gästegebühren", "pt": "0% de taxas para o hóspede", "ja": "ゲスト手数料0%", "zh": "房客0手续费"},
    "badge_cancellazione": {"it": "Cancellazione gratuita", "en": "Free cancellation", "es": "Cancelación gratuita", "fr": "Annulation gratuite", "de": "Kostenlose Stornierung", "pt": "Cancelamento grátis", "ja": "無料キャンセル", "zh": "免费取消"},
    "badge_pagamenti": {"it": "Pagamenti sicuri", "en": "Secure payments", "es": "Pagos seguros", "fr": "Paiements sécurisés", "de": "Sichere Zahlungen", "pt": "Pagamentos seguros", "ja": "安全な決済", "zh": "安全支付"},
    "badge_antirimpianto": {"it": "Anti-Rimpianto: i soldi tornano come credito", "en": "Regret-free: money back as credit", "es": "Sin arrepentimiento: dinero de vuelta como crédito", "fr": "Sans regret : argent rendu en crédit", "de": "Ohne Reue: Geld zurück als Guthaben", "pt": "Sem arrependimento: dinheiro de volta como crédito", "ja": "後悔なし：返金はクレジットで", "zh": "无悔保障：退款以积分返还"},
    "footer_slogan": {"it": "zero commissioni nascoste", "en": "zero hidden fees", "es": "cero comisiones ocultas", "fr": "zéro frais cachés", "de": "keine versteckten Gebühren", "pt": "zero taxas ocultas", "ja": "隠れた手数料はゼロ", "zh": "零隐藏费用"},
    # --- stato vuoto / lista d'attesa ---
    "empty_titolo": {"it": "Stiamo aprendo presto!", "en": "Opening soon!", "es": "¡Abrimos pronto!", "fr": "Bientôt disponible !", "de": "Bald verfügbar!", "pt": "Em breve!", "ja": "まもなくオープン！", "zh": "即将开通！"},
    "empty_lascia": {"it": "Lascia la tua email: ti avvisiamo appena ci sono alloggi e ricevi un Credito Fondatore di benvenuto per la tua prima prenotazione.", "en": "Leave your email: we'll notify you as soon as stays are available and you'll get a welcome Founder Credit for your first booking.", "es": "Deja tu correo: te avisaremos en cuanto haya alojamientos y recibirás un Crédito Fundador de bienvenida para tu primera reserva.", "fr": "Laissez votre e-mail : nous vous préviendrons dès que des logements seront disponibles et vous recevrez un Crédit Fondateur de bienvenue pour votre première réservation.", "de": "Hinterlasse deine E-Mail: Wir benachrichtigen dich, sobald Unterkünfte verfügbar sind, und du erhältst ein Willkommens-Gründerguthaben für deine erste Buchung.", "pt": "Deixe o seu e-mail: avisamos assim que houver acomodações e você ganha um Crédito Fundador de boas-vindas para a sua primeira reserva.", "ja": "メールアドレスを登録してください。宿泊施設が利用可能になり次第お知らせし、初回予約に使える創設者クレジットをプレゼントします。", "zh": "留下您的邮箱：一旦有房源我们会立即通知您，并赠送创始人礼遇积分用于您的首次预订。"},
    "ph_email": {"it": "latua@email.com", "en": "you@email.com", "es": "tu@email.com", "fr": "vous@email.com", "de": "du@email.com", "pt": "voce@email.com", "ja": "you@email.com", "zh": "you@email.com"},
    "avvisami": {"it": "Avvisami", "en": "Notify me", "es": "Avísame", "fr": "Prévenez-moi", "de": "Benachrichtige mich", "pt": "Avise-me", "ja": "通知を受け取る", "zh": "通知我"},
    "inserisci_email": {"it": "Inserisci la tua email.", "en": "Enter your email.", "es": "Introduce tu correo.", "fr": "Saisissez votre e-mail.", "de": "Gib deine E-Mail ein.", "pt": "Digite o seu e-mail.", "ja": "メールアドレスを入力してください。", "zh": "请输入您的邮箱。"},
    "sei_host": {"it": "Sei un host?", "en": "Are you a host?", "es": "¿Eres anfitrión?", "fr": "Vous êtes hôte ?", "de": "Bist du Gastgeber?", "pt": "É anfitrião?", "ja": "ホストの方はこちら", "zh": "您是房东吗？"},
    "pubblica_primo": {"it": "Pubblica il primo alloggio", "en": "Publish the first listing", "es": "Publica el primer alojamiento", "fr": "Publiez le premier logement", "de": "Veröffentliche die erste Unterkunft", "pt": "Publique a primeira acomodação", "ja": "最初の宿泊施設を掲載", "zh": "发布第一个房源"},
    "errore_server": {"it": "Errore server:", "en": "Server error:", "es": "Error del servidor:", "fr": "Erreur serveur :", "de": "Serverfehler:", "pt": "Erro do servidor:", "ja": "サーバーエラー：", "zh": "服务器错误："},
    "servizio_non_ragg": {"it": "Servizio non raggiungibile, riprova.", "en": "Service unavailable, please try again.", "es": "Servicio no disponible, inténtalo de nuevo.", "fr": "Service indisponible, réessayez.", "de": "Dienst nicht erreichbar, bitte erneut versuchen.", "pt": "Serviço indisponível, tente novamente.", "ja": "サービスに接続できません。もう一度お試しください。", "zh": "服务暂不可用，请重试。"},
    "nessun_raggio_pre": {"it": "Nessun alloggio entro", "en": "No stays within", "es": "Sin alojamientos en un radio de", "fr": "Aucun logement dans un rayon de", "de": "Keine Unterkünfte im Umkreis von", "pt": "Nenhuma acomodação num raio de", "ja": "この範囲内に宿泊施設はありません：", "zh": "该范围内没有住宿："},
    "allarga_raggio": {"it": "Allarga il raggio qui sopra, oppure cerca per città.", "en": "Widen the radius above, or search by city.", "es": "Amplía el radio arriba, o busca por ciudad.", "fr": "Élargissez le rayon ci-dessus, ou cherchez par ville.", "de": "Erweitere oben den Umkreis oder suche nach Stadt.", "pt": "Aumente o raio acima, ou pesquise por cidade.", "ja": "上で範囲を広げるか、都市名で検索してください。", "zh": "请在上方扩大范围，或按城市搜索。"},
    "geo_non_supp": {"it": "Geolocalizzazione non supportata dal browser", "en": "Geolocation not supported by the browser", "es": "Geolocalización no compatible con el navegador", "fr": "Géolocalisation non prise en charge par le navigateur", "de": "Standortbestimmung vom Browser nicht unterstützt", "pt": "Geolocalização não suportada pelo navegador", "ja": "お使いのブラウザは位置情報に対応していません", "zh": "浏览器不支持定位"},
    "geo_non_disp": {"it": "Posizione non disponibile (permesso negato?)", "en": "Location unavailable (permission denied?)", "es": "Ubicación no disponible (¿permiso denegado?)", "fr": "Position indisponible (autorisation refusée ?)", "de": "Standort nicht verfügbar (Zugriff verweigert?)", "pt": "Localização indisponível (permissão negada?)", "ja": "位置情報を取得できません（許可が拒否された可能性）", "zh": "无法获取位置（是否拒绝了权限？）"},
    # --- politiche di cancellazione ---
    "pol_flessibile": {"it": "✓ Cancellazione gratuita fino a 24h prima", "en": "✓ Free cancellation up to 24h before", "es": "✓ Cancelación gratuita hasta 24 h antes", "fr": "✓ Annulation gratuite jusqu'à 24 h avant", "de": "✓ Kostenlose Stornierung bis 24 Std. vorher", "pt": "✓ Cancelamento grátis até 24h antes", "ja": "✓ 24時間前まで無料キャンセル", "zh": "✓ 入住前24小时可免费取消"},
    "pol_moderata": {"it": "✓ Cancellazione gratuita fino a 5 giorni prima", "en": "✓ Free cancellation up to 5 days before", "es": "✓ Cancelación gratuita hasta 5 días antes", "fr": "✓ Annulation gratuite jusqu'à 5 jours avant", "de": "✓ Kostenlose Stornierung bis 5 Tage vorher", "pt": "✓ Cancelamento grátis até 5 dias antes", "ja": "✓ 5日前まで無料キャンセル", "zh": "✓ 入住前5天可免费取消"},
    "pol_rigida": {"it": "Cancellazione gratuita fino a 14 giorni prima (poi 50%)", "en": "Free cancellation up to 14 days before (then 50%)", "es": "Cancelación gratuita hasta 14 días antes (luego 50%)", "fr": "Annulation gratuite jusqu'à 14 jours avant (puis 50 %)", "de": "Kostenlose Stornierung bis 14 Tage vorher (danach 50%)", "pt": "Cancelamento grátis até 14 dias antes (depois 50%)", "ja": "14日前まで無料キャンセル（以降50%）", "zh": "入住前14天可免费取消（之后收取50%）"},
    "pol_non_rimborsabile": {"it": "Tariffa non rimborsabile", "en": "Non-refundable rate", "es": "Tarifa no reembolsable", "fr": "Tarif non remboursable", "de": "Nicht erstattbarer Tarif", "pt": "Tarifa não reembolsável", "ja": "返金不可の料金", "zh": "不可退款价格"},
    # --- host ---
    "pannello_host": {"it": "Pannello Host", "en": "Host Panel", "es": "Panel Anfitrión", "fr": "Espace Hôte", "de": "Gastgeber-Panel", "pt": "Painel do Anfitrião", "ja": "ホストパネル", "zh": "房东面板"},
    "pubblica": {"it": "Pubblica alloggio", "en": "Publish listing", "es": "Publicar", "fr": "Publier", "de": "Veröffentlichen", "pt": "Publicar", "ja": "宿泊施設を掲載", "zh": "发布房源"},
    "salva_disp": {"it": "Salva disponibilità", "en": "Save availability", "es": "Guardar disponibilidad", "fr": "Enregistrer", "de": "Speichern", "pt": "Guardar disponibilidade", "ja": "空き状況を保存", "zh": "保存可预订情况"},
    "prezzo_notte": {"it": "Prezzo/notte (cent)", "en": "Price/night (cents)", "es": "Precio/noche", "fr": "Prix/nuit", "de": "Preis/Nacht", "pt": "Preço/noite", "ja": "1泊の料金", "zh": "每晚价格"},
    "accedi_registrati": {"it": "Accedi o Registrati", "en": "Log in or Sign up", "es": "Entrar o Registrarse", "fr": "Connexion ou Inscription", "de": "Anmelden oder Registrieren", "pt": "Entrar ou Registar", "ja": "ログインまたは登録", "zh": "登录或注册"},
    "accedi": {"it": "Accedi", "en": "Log in", "es": "Entrar", "fr": "Connexion", "de": "Anmelden", "pt": "Entrar", "ja": "ログイン", "zh": "登录"},
    "registrati": {"it": "Registrati", "en": "Sign up", "es": "Registrarse", "fr": "S'inscrire", "de": "Registrieren", "pt": "Registar", "ja": "登録", "zh": "注册"},
    "esci": {"it": "Esci", "en": "Log out", "es": "Salir", "fr": "Déconnexion", "de": "Abmelden", "pt": "Sair", "ja": "ログアウト", "zh": "退出"},
    "miei_alloggi": {"it": "I miei alloggi", "en": "My listings", "es": "Mis alojamientos", "fr": "Mes logements", "de": "Meine Unterkünfte", "pt": "As minhas acomodações", "ja": "マイリスティング", "zh": "我的房源"},
    "invita_host": {"it": "Invita altri host", "en": "Invite other hosts", "es": "Invita anfitriones", "fr": "Inviter des hôtes", "de": "Andere Gastgeber einladen", "pt": "Convide outros anfitriões", "ja": "他のホストを招待", "zh": "邀请其他房东"},
    "link_diretto": {"it": "Il tuo link prenotazione diretta", "en": "Your direct booking link", "es": "Tu enlace de reserva directa", "fr": "Votre lien de réservation directe", "de": "Dein Direktbuchungs-Link", "pt": "O seu link de reserva direta", "ja": "直接予約リンク", "zh": "您的直接预订链接"},
    "messaggi_ospite": {"it": "Messaggi con l'ospite", "en": "Messages with the guest", "es": "Mensajes con el huésped", "fr": "Messages avec le voyageur", "de": "Nachrichten mit dem Gast", "pt": "Mensagens com o hóspede", "ja": "ゲストとのメッセージ", "zh": "与房客的消息"},
    "prezzo_dinamico": {"it": "Prezzo dinamico suggerito", "en": "Suggested dynamic price", "es": "Precio dinámico", "fr": "Prix dynamique", "de": "Dynamischer Preis", "pt": "Preço dinâmico sugerido", "ja": "推奨ダイナミック価格", "zh": "建议动态价格"},
    # --- voucher ---
    "voucher_ok": {"it": "Prenotazione confermata", "en": "Booking confirmed", "es": "Reserva confirmada", "fr": "Réservation confirmée", "de": "Buchung bestätigt", "pt": "Reserva confirmada", "ja": "予約確定", "zh": "预订已确认"},
    "rif": {"it": "Riferimento", "en": "Reference", "es": "Referencia", "fr": "Référence", "de": "Referenz", "pt": "Referência", "ja": "予約番号", "zh": "参考号"},
    "dal": {"it": "Dal", "en": "From", "es": "Desde", "fr": "Du", "de": "Von", "pt": "De", "ja": "から", "zh": "从"},
    "al": {"it": "Al", "en": "To", "es": "Hasta", "fr": "Au", "de": "Bis", "pt": "Até", "ja": "まで", "zh": "至"},
    "self_pass": {"it": "Check-in autonomo: mostra questo codice alla serratura", "en": "Self check-in: show this code at the lock", "es": "Auto check-in: muestra este código en la cerradura", "fr": "Auto check-in : montrez ce code à la serrure", "de": "Self-Check-in: diesen Code am Schloss zeigen", "pt": "Check-in autónomo: mostre este código na fechadura", "ja": "セルフチェックイン：このコードを鍵に提示してください", "zh": "自助入住：向门锁出示此代码"},
    # --- lista d'attesa (messaggio server) + link post-prenotazione ---
    "wl_dest_generica": {"it": "questa destinazione", "en": "this destination", "es": "este destino", "fr": "cette destination", "de": "dieses Ziel", "pt": "este destino", "ja": "ご希望の目的地", "zh": "该目的地"},
    "wl_msg_tpl": {"it": "Ti avvisiamo appena ci sono alloggi a %s. Hai un Credito Fondatore per la tua prima prenotazione.", "en": "We'll notify you as soon as stays are available in %s. You have a Founder Credit for your first booking.", "es": "Te avisaremos en cuanto haya alojamientos en %s. Tienes un Crédito Fundador para tu primera reserva.", "fr": "Nous vous préviendrons dès que des logements seront disponibles à %s. Vous avez un Crédit Fondateur pour votre première réservation.", "de": "Wir benachrichtigen dich, sobald in %s Unterkünfte verfügbar sind. Du hast ein Gründerguthaben für deine erste Buchung.", "pt": "Avisamos assim que houver acomodações em %s. Você tem um Crédito Fundador para a sua primeira reserva.", "ja": "%sに宿泊施設が用意でき次第お知らせします。初回予約に使える創設者クレジットをご利用いただけます。", "zh": "一旦%s有房源，我们会立即通知您。您可享创始人礼遇积分用于首次预订。"},
    "contratto_pdf": {"it": "Contratto PDF", "en": "PDF contract", "es": "Contrato PDF", "fr": "Contrat PDF", "de": "PDF-Vertrag", "pt": "Contrato PDF", "ja": "契約書（PDF）", "zh": "合同PDF"},
    "voucher_label": {"it": "Voucher", "en": "Voucher", "es": "Voucher", "fr": "Bon", "de": "Voucher", "pt": "Voucher", "ja": "バウチャー", "zh": "预订凭证"},
}


def _ui(chiave: str, lingua: str) -> str:
    tab = ETICHETTE_UI.get(chiave, {})
    return tab.get(lingua) or tab.get("en") or chiave


def _dizionario_i18n(lingua: str) -> Dict[str, Any]:
    from fase61_localizzazione import ETICHETTE_SERVIZI, ETICHETTE_STATI
    loc = Localizzatore()
    return {
        "lingua": lingua,
        "ui": {k: _ui(k, lingua) for k in ETICHETTE_UI},
        "servizi": {c: loc.servizio(c, lingua) for c in ETICHETTE_SERVIZI},
        "stati": {c: loc.stato(c, lingua) for c in ETICHETTE_STATI},
    }


def _lingua(query: Dict[str, str]) -> str:
    lng = (query or {}).get("lang", "")
    return lng if lng in LINGUE_SUPPORTATE else "en"


# ─────────────────────────────────────────────────────────────────────────────
# SEO / discoverability (gratis): pagina crawlabile per alloggio + JSON-LD + sitemap.
# Funzioni PURE e testabili. base_url = dominio (vuoto = relativo finche' non c'e').
# ─────────────────────────────────────────────────────────────────────────────
def _euro(cents: Any) -> str:
    if not isinstance(cents, int) or isinstance(cents, bool) or cents < 0:
        return "0.00"
    return "%d.%02d" % (cents // 100, cents % 100)        # no float, deterministico


def jsonld_alloggio(dettaglio: Dict[str, Any], base_url: str = "",
                    recensioni: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Schema.org per un alloggio (rich results Google + leggibile dagli agenti).
    Se ci sono recensioni, aggiunge aggregateRating (stelle nei risultati Google)."""
    servizi = dettaglio.get("servizi", []) or []
    ld = {
        "@context": "https://schema.org",
        "@type": "Apartment",
        "name": dettaglio.get("titolo", ""),
        "description": dettaglio.get("descrizione", ""),
        "url": base_url + "/alloggio/" + str(dettaglio.get("slug", "")),
        "address": {"@type": "PostalAddress",
                    "addressLocality": dettaglio.get("citta", ""),
                    "addressCountry": dettaglio.get("paese", "")},
        "numberOfRooms": dettaglio.get("camere", 1),
        "occupancy": {"@type": "QuantitativeValue",
                      "maxValue": dettaglio.get("capacita", 1)},
        "amenityFeature": [{"@type": "LocationFeatureSpecification",
                            "name": s, "value": True} for s in servizi],
        "offers": {"@type": "Offer",
                   "price": _euro(dettaglio.get("prezzo_notte_cents", 0)),
                   "priceCurrency": dettaglio.get("valuta", "EUR")},
    }
    if isinstance(recensioni, dict) and recensioni.get("conteggio", 0) > 0:
        media = recensioni.get("media_centesimi", 0)
        ld["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": "%d.%02d" % (media // 100, media % 100),  # es. 4.25, no float
            "reviewCount": int(recensioni["conteggio"]),
            "bestRating": "5", "worstRating": "1",
        }
    return ld


def pagina_alloggio_html(sistema: Any, slug: str, base_url: str = "") -> Optional[str]:
    """Pagina HTML crawlabile (server-rendered) con JSON-LD. None se assente. Le SPA
    sono indicizzate male: questa rende il contenuto a Google e agli agenti SENZA JS."""
    import html
    try:
        d = sistema.catalogo.dettaglio(slug)
    except Exception:
        return None
    if d is None:
        return None
    e = html.escape
    rie = None
    if getattr(sistema, "recensioni", None) is not None:
        try:
            rr = sistema.recensioni.riepilogo(slug)
            rie = {"conteggio": rr["conteggio"], "media_centesimi": rr["media_centesimi"]}
        except Exception:
            rie = None
    servizi = "".join("<li>%s</li>" % e(str(s)) for s in d.get("servizi", []) or [])
    ld = json.dumps(jsonld_alloggio(d, base_url, rie), ensure_ascii=False)
    # neutralizza la chiusura del tag <script> dentro il JSON-LD (anti-XSS): unicode-escape
    ld = ld.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return (
        "<!DOCTYPE html><html lang=\"it\"><head><meta charset=\"UTF-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>%s - BookinVIP</title>"
        "<meta name=\"description\" content=\"%s\">"
        "<link rel=\"canonical\" href=\"%s/alloggio/%s\">"
        "<script type=\"application/ld+json\">%s</script></head><body>"
        "<h1>%s</h1><p><strong>%s</strong>%s</p><p>%s</p>"
        "<p>Prezzo: %s %s / notte</p><ul>%s</ul>"
        "<p><a href=\"/?slug=%s\">Prenota su BookinVIP</a></p></body></html>"
    ) % (
        e(d.get("titolo", "")), e(d.get("descrizione", ""))[:160],
        e(base_url), e(slug), ld,
        e(d.get("titolo", "")), e(d.get("citta", "")),
        ", " + e(d.get("paese", "")) if d.get("paese") else "",
        e(d.get("descrizione", "")),
        e(_euro(d.get("prezzo_notte_cents", 0))), e(d.get("valuta", "EUR")),
        servizi, e(slug),
    )


def sitemap_xml(sistema: Any, base_url: str = "") -> str:
    """sitemap.xml con tutte le schede pubblicate (per Google)."""
    from fase57_vetrina import CriteriRicerca, PAGINA_MAX
    slugs: List[str] = []
    offset = 0
    try:
        while offset < 10000:
            res = sistema.catalogo.cerca(CriteriRicerca(limit=PAGINA_MAX, offset=offset))
            righe = res.get("risultati", [])
            if not righe:
                break
            slugs.extend(str(r.get("slug", "")) for r in righe if r.get("slug"))
            if len(righe) < PAGINA_MAX:
                break
            offset += PAGINA_MAX
    except Exception:
        pass
    urls = "".join("<url><loc>%s/alloggio/%s</loc></url>" % (base_url, s) for s in slugs)
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            '<url><loc>%s/</loc></url>%s</urlset>' % (base_url, urls))


def robots_txt(base_url: str = "") -> str:
    # Due sitemap: alloggi (vetrina) + landing host inbound SEO (fase97).
    return ("User-agent: *\nAllow: /\nSitemap: %s/sitemap.xml\n"
            "Sitemap: %s/sitemap-host.xml\n" % (base_url, base_url))


# ─────────────────────────────────────────────────────────────────────────────
# SUPERFICIE AI-AGENT (scoperta standard): oltre a /api/mcp (MCP JSON-RPC, fase60) e
# /llms.txt (fase97), esponiamo il manifest di scoperta /.well-known/ai-plugin.json e
# uno spec OpenAPI /openapi.json -> QUALSIASI agente (Claude/Gemini/ChatGPT/browser
# agentici) trova e usa il flusso 'cerca -> preventivo firmato -> prenota' senza integrazione
# custom. Il prezzo e' FIRMATO: il modello non puo' alterarlo. Funzioni PURE (testabili).
# ─────────────────────────────────────────────────────────────────────────────
def ai_plugin_manifest(base_url: str = "") -> Dict[str, Any]:
    b = base_url or "https://bookinvip.com"
    return {
        "schema_version": "v1",
        "name_for_human": "BookinVIP",
        "name_for_model": "bookinvip",
        "description_for_human": ("Prenota alloggi certificati: prezzo pulito tutto-incluso, "
                                  "0% commissioni all'ospite, cancellazione gratuita."),
        "description_for_model": ("Cerca e prenota alloggi. JSON machine-clean, prezzi in CENTESIMI "
                                  "interi, preventivi FIRMATI (il modello non puo' alterare il prezzo). "
                                  "Flusso: cerca GET /api/catalogo -> preventivo POST /api/concierge/quote "
                                  "-> prenota POST /api/concierge/book. Anche via MCP JSON-RPC su /api/mcp."),
        "auth": {"type": "none"},
        "api": {"type": "openapi", "url": b + "/openapi.json"},
        "mcp": {"type": "jsonrpc", "url": b + "/api/mcp"},
        "logo_url": b + "/icon.svg",
        "contact_email": "info@bookinvip.com",
        "legal_info_url": b + "/",
    }


def openapi_agent_spec(base_url: str = "") -> Dict[str, Any]:
    b = base_url or "https://bookinvip.com"
    _q = lambda n, t="string", d=None: {"name": n, "in": "query",
                                        "schema": {"type": t}, "description": d or ""}
    return {
        "openapi": "3.0.3",
        "info": {"title": "BookinVIP Booking API", "version": "1.0.0",
                 "description": ("Prenotazione alloggi machine-clean. Prezzi in centesimi interi. "
                                 "Flusso: cerca -> preventivo (quote firmato) -> prenota. Il modello "
                                 "NON puo' alterare il prezzo. 0% commissioni ospite, prezzo pulito.")},
        "servers": [{"url": b}],
        "paths": {
            "/api/catalogo": {"get": {"operationId": "cercaAlloggi",
                "summary": "Cerca alloggi disponibili (JSON machine-clean)",
                "parameters": [_q("citta"), _q("check_in", "string", "YYYY-MM-DD"),
                               _q("check_out", "string", "YYYY-MM-DD"),
                               _q("prezzo_max_cents", "integer", "tetto prezzo in centesimi"),
                               _q("servizi", "string", "codici separati da virgola"),
                               _q("solo_gratuita", "string", "1 = solo cancellazione gratuita"),
                               _q("lang", "string", "it,en,es,fr,de,pt,ja,zh")],
                "responses": {"200": {"description": "Elenco schede alloggio"}}}},
            "/api/concierge/quote": {"post": {"operationId": "preventivo",
                "summary": "Preventivo FIRMATO (prezzo bloccato in un token)",
                "requestBody": {"required": True, "content": {"application/json": {"schema": {
                    "type": "object", "required": ["alloggio_id", "check_in", "check_out"],
                    "properties": {"alloggio_id": {"type": "string"}, "check_in": {"type": "string"},
                                   "check_out": {"type": "string"}, "party": {"type": "integer"}}}}}},
                "responses": {"200": {"description": "quote_token + prezzo_guest_cents + totale_cents"}}}},
            "/api/concierge/book": {"post": {"operationId": "prenota",
                "summary": "Prenota col quote_token (prezzo gia' firmato, non alterabile)",
                "requestBody": {"required": True, "content": {"application/json": {"schema": {
                    "type": "object", "required": ["quote_token", "email"],
                    "properties": {"quote_token": {"type": "string"}, "email": {"type": "string"}}}}}},
                "responses": {"201": {"description": "confermata + voucher_token"}}}},
            "/api/i18n": {"get": {"operationId": "traduzioni",
                "summary": "Dizionario UI per lingua",
                "parameters": [_q("lang", "string", "it,en,es,fr,de,pt,ja,zh")],
                "responses": {"200": {"description": "ui + servizi + stati"}}}},
            "/api/domanda/citta": {"get": {"operationId": "mappaDomanda",
                "summary": "Citta con piu' persone in attesa (domanda aggregata)",
                "responses": {"200": {"description": "elenco citta/richieste"}}}},
            "/api/mcp": {"post": {"operationId": "mcp",
                "summary": "Endpoint MCP (JSON-RPC 2.0) per agenti IA",
                "responses": {"200": {"description": "risposta JSON-RPC"}}}},
        },
    }


def _notti_count(ci: Any, co: Any) -> int:
    import datetime
    try:
        return (datetime.date.fromisoformat(str(co))
                - datetime.date.fromisoformat(str(ci))).days
    except (ValueError, TypeError):
        return 0


def genera_csv_prenotazioni(righe: Any) -> str:
    """CSV delle prenotazioni per la contabilita' (stdlib csv, niente dipendenze)."""
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["alloggio", "check_in", "check_out", "notti", "origine", "stato",
                "revenue_eur", "riferimento"])
    for r in (righe or []):
        if not isinstance(r, dict):
            continue
        rev = r.get("revenue_cents", 0)
        rev = rev if isinstance(rev, int) and not isinstance(rev, bool) else 0
        w.writerow([
            r.get("alloggio_id", ""), r.get("check_in", ""), r.get("check_out", ""),
            _notti_count(r.get("check_in"), r.get("check_out")),
            r.get("origine", ""), "rimborsata" if r.get("rimborsato") else "attiva",
            "%d.%02d" % (rev // 100, rev % 100), str(r.get("idem_key", ""))[:16],
        ])
    return buf.getvalue()


# Mostrare il codice "serratura smart" sul voucher? OFF finché non c'è integrazione hardware
# reale (nessun host ha serrature smart al lancio): evita di confondere il cliente con un codice
# lungo e inutile. Riattivare (True) quando esisterà una vera serratura/QR per l'ospite.
MOSTRA_PASS_SERRATURA = False


def pagina_voucher_html(sistema: Any, token: Any, lingua: str = "it") -> Optional[str]:
    """Voucher di conferma (server-rendered, stampabile, multilingua). Verifica la firma
    del token (non falsificabile). None se assente/manomesso/non un voucher."""
    import html
    firma = getattr(sistema, "firma", None)
    if firma is None:
        return None
    dati = firma.decodifica(token)
    if not isinstance(dati, dict) or dati.get("tipo") != "voucher":
        return None
    lng = lingua if lingua in LINGUE_SUPPORTATE else "it"
    e = html.escape
    prezzo = "%d.%02d" % (dati.get("prezzo_guest_cents", 0) // 100,
                          dati.get("prezzo_guest_cents", 0) % 100)
    # CODICE prenotazione leggibile (BVIP-XXXX-XXXX) + PIN check-in, uguali per cliente e host
    from fase59_concierge import codice_prenotazione
    _ref = str(dati.get("riferimento", ""))
    _codice_pren = codice_prenotazione(_ref)
    _pin_checkin = firma.pin_checkin(_ref)
    # Codice "serratura smart" (self check-in): NASCOSTO di default. È un pass firmato utile
    # SOLO se l'host ha una serratura elettronica compatibile (hardware, che al lancio nessuno
    # ha) -> mostrarlo confonderebbe il cliente. Resta emesso nel token (riattivabile in futuro,
    # es. QR sull'app della serratura). Per riattivare la visualizzazione: MOSTRA_PASS_SERRATURA=True.
    pass_code = e(str(dati.get("smart_pass", "")))
    blocco_pass = ("<div style='margin-top:1.2rem;padding:1rem;background:#f0f4fe;"
                   "border-radius:1rem'><strong>%s</strong><br>"
                   "<code style='word-break:break-all;font-size:.8rem'>%s</code></div>"
                   ) % (e(_ui("self_pass", lng)), pass_code) \
        if (MOSTRA_PASS_SERRATURA and pass_code) else ""
    # cancellazione self-service (token preso dall'URL, niente da incollare)
    blocco_pass = blocco_pass + (
        "<button id='btnCanc' style='margin-top:1.2rem;width:100%;padding:.8rem;border:0;"
        "border-radius:.8rem;background:#b00020;color:#fff;font-weight:700;cursor:pointer'>"
        "Cancella prenotazione</button>"
        "<div id='cancMsg' style='margin-top:.6rem;font-size:.85rem'></div>"
        "<script>document.getElementById('btnCanc').onclick=async function(){"
        "if(!confirm('Cancellare la prenotazione?'))return;"
        "var tk=decodeURIComponent((location.pathname.split('/voucher/')[1]||''));"
        "var r=await fetch('/api/concierge/cancella',{method:'POST',"
        "headers:{'Content-Type':'application/json'},body:JSON.stringify({voucher_token:tk})});"
        "var d=await r.json();var m=document.getElementById('cancMsg');"
        "if(d.stato==='cancellata'){m.style.color='#155724';"
        "m.textContent='Cancellata. Rimborso '+(d.rimborso_cents/100).toFixed(2)+' EUR';"
        "this.style.display='none';}else{m.style.color='#b00020';"
        "m.textContent='Cancellazione non riuscita';}};</script>")
    # Escrow di garanzia: l'ospite conferma "tutto ok" (sblocca il pagamento) o segnala un problema
    blocco_pass = blocco_pass + (
        "<div style='margin-top:1rem;padding-top:1rem;border-top:1px solid #eef2f7'>"
        "<div style='font-size:.82rem;color:#5e6f8d;margin-bottom:.5rem'>Dopo il check-in:</div>"
        "<button id='btnOk' style='width:100%;padding:.8rem;border:0;border-radius:.8rem;"
        "background:#155724;color:#fff;font-weight:700;cursor:pointer'>&#10003; Confermo: tutto "
        "come descritto</button>"
        "<button id='btnProblema' style='width:100%;margin-top:.5rem;padding:.7rem;border:0;"
        "border-radius:.8rem;background:#e0a800;color:#1e3c72;font-weight:700;cursor:pointer'>"
        "&#9888; Segnala un problema</button>"
        "<div id='gMsg' style='margin-top:.6rem;font-size:.85rem'></div></div>"
        "<script>(function(){var tk=decodeURIComponent((location.pathname.split('/voucher/')[1]||''));"
        "function call(p,btn,ok){return async function(){btn.disabled=true;"
        "var r=await fetch(p,{method:'POST',headers:{'Content-Type':'application/json'},"
        "body:JSON.stringify({voucher_token:tk})});var d=await r.json();var m=document.getElementById('gMsg');"
        "if(d&&d.ok){m.style.color='#155724';m.textContent=ok;}else{m.style.color='#b00020';"
        "m.textContent='Operazione non riuscita';btn.disabled=false;}};}"
        "document.getElementById('btnOk').onclick=call('/api/garanzia/conferma',document.getElementById('btnOk'),'Grazie! Pagamento sbloccato per l host.');"
        "document.getElementById('btnProblema').onclick=call('/api/garanzia/contesta',document.getElementById('btnProblema'),'Segnalazione ricevuta: pagamento sospeso, ti ricontattiamo.');"
        "})();</script>")
    return (
        "<!DOCTYPE html><html lang=\"%s\"><head><meta charset=\"UTF-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>Voucher BookinVIP</title><style>body{font-family:system-ui,sans-serif;"
        "background:#f4f6fa;color:#1a1e2b;padding:2rem;max-width:480px;margin:0 auto}"
        ".v{background:#fff;border-radius:1.5rem;padding:2rem;box-shadow:0 8px 24px "
        "rgba(0,0,0,.06)}h1{color:#1e3c72}.r{display:flex;justify-content:space-between;"
        "padding:.3rem 0;border-bottom:1px solid #eef2f7}</style></head><body><div class=\"v\">"
        "<div style=\"font-weight:700;color:#1e3c72;font-size:1.3rem\">BookinVIP</div>"
        "<h1>✓ %s</h1>"
        "<div class=\"r\"><span>%s</span><strong style=\"letter-spacing:.05em\">%s</strong></div>"
        "<div class=\"r\"><span>PIN check-in</span><strong style=\"font-size:1.15rem;color:#1e3c72\">%s</strong></div>"
        "<div class=\"r\"><span>%s</span><strong>%s</strong></div>"
        "<div class=\"r\"><span>%s</span><strong>%s</strong></div>"
        "<div class=\"r\"><span>%s</span><strong>%s %s</strong></div>"
        "%s</div></body></html>"
    ) % (
        e(lng), e(_ui("voucher_ok", lng)),
        e(_ui("rif", lng)), e(_codice_pren),
        e(_pin_checkin),
        e(_ui("dal", lng)), e(str(dati.get("check_in", ""))),
        e(_ui("al", lng)), e(str(dati.get("check_out", ""))),
        e(_ui("totale", lng)), e(prezzo), e(str(dati.get("valuta", "EUR"))),
        blocco_pass,
    )


class RouterHTTP:
    """Router PURO (testabile): cabla il SistemaCasaVIP (fase81) sulle rotte HTTP."""

    def __init__(self, sistema: Any, *, host_key: Optional[str] = None,
                 admin_key: Optional[str] = None, base_url: str = "") -> None:
        self._sys = sistema
        self._host_key = host_key
        self._admin_key = admin_key
        self._base_url = base_url or ""
        self._loc = Localizzatore()

    def gestisci(self, metodo: str, path: str, query: Optional[Dict[str, str]] = None,
                 body: Optional[str] = None,
                 headers: Optional[Dict[str, str]] = None) -> Tuple[int, Dict[str, Any]]:
        query = query or {}
        headers = headers or {}
        try:
            return self._instrada(metodo, path, query, body, headers)
        except Exception:
            logger.error("RouterHTTP: eccezione ISOLATA (-> 500)", exc_info=True)
            return 500, {"errore": "errore_interno"}

    def _instrada(self, metodo, path, query, body, headers):
        if not self._sys.attivo:
            return 503, {"errore": "sistema_spento"}
        if metodo == "GET" and path == "/api/health":
            return 200, {"status": "ok", "money_unit": "cents_integer"}
        if metodo == "GET" and path == "/api/lingue":
            return 200, {"lingue": list(LINGUE_SUPPORTATE)}
        if metodo == "GET" and path == "/api/i18n":
            return 200, _dizionario_i18n(_lingua(query))
        if metodo == "GET" and path == "/api/legale/contratto-host":
            return self._contratto_host(query)
        if metodo == "GET" and path == "/api/trasparenza":
            return self._trasparenza(query)
        if metodo == "POST" and path == "/api/domanda":
            return self._domanda_registra(body)
        if metodo == "GET" and path == "/api/domanda/conta":
            return self._domanda_conta(query)
        if metodo == "GET" and path == "/api/domanda/citta":
            return self._domanda_per_citta(query)
        if metodo == "GET" and path == "/api/catalogo":
            return self._catalogo(query)
        if metodo == "GET" and path.startswith("/api/catalogo/"):
            return self._dettaglio(path[len("/api/catalogo/"):], _lingua(query))
        if metodo == "POST" and path == "/api/concierge/quote":
            return self._concierge_quote(body)
        if metodo == "POST" and path == "/api/concierge/book":
            return self._book(body)
        if metodo == "POST" and path == "/api/concierge/cancella":
            return self._cancella_prenotazione(body)
        if metodo == "POST" and path == "/api/split/preview":
            return self._split_preview(body)
        if metodo == "POST" and path == "/api/contratto":
            return self._contratto(body)
        if metodo == "POST" and path == "/api/garanzia/conferma":
            return self._garanzia_conferma(body)
        if metodo == "POST" and path == "/api/garanzia/contesta":
            return self._garanzia_contesta(body)
        if metodo == "GET" and path == "/api/garanzia/stato":
            return self._garanzia_stato(query, headers)
        if metodo == "GET" and path.startswith("/api/recensioni/"):
            return self._recensioni(path[len("/api/recensioni/"):])
        if metodo == "POST" and path == "/api/recensioni":
            return self._invia_recensione(body)
        if metodo == "POST" and path == "/api/mcp":
            return self._mcp(body)
        if metodo == "POST" and path == "/api/payments/webhook":
            return self._webhook_stripe(body, headers)
        if metodo == "POST" and path == "/api/marketing/campagna":
            return self._marketing_campagna(body, headers)
        if metodo == "GET" and path == "/api/tassa":
            return self._tassa(query)
        if metodo == "POST" and path == "/api/split/crea":
            return self._split_crea(body)
        if metodo == "POST" and path == "/api/split/paga":
            return self._split_paga(body)
        if metodo == "GET" and path == "/api/split/stato":
            return self._split_stato(query)
        if metodo == "POST" and path == "/api/messaggi":
            return self._msg_invia(body, headers)
        if metodo == "GET" and path == "/api/messaggi":
            return self._msg_thread(query, headers)
        if metodo == "GET" and path == "/api/host/invito":
            return self._host_invito(headers)
        if metodo == "GET" and path == "/api/host/prezzo_suggerito":
            return self._prezzo_suggerito(query, headers)
        if metodo == "POST" and path == "/api/host/invito/registra":
            return self._host_invito_registra(body)
        if metodo == "POST" and path == "/api/host/invito/qualifica":
            return self._host_invito_qualifica(body, headers)
        if metodo == "POST" and path == "/api/host/pubblica":
            return self._host_pubblica(body, headers)
        if metodo == "POST" and path == "/api/host/upload_foto":
            return self._upload_foto(body, headers)
        if metodo == "POST" and path == "/api/host/disponibilita":
            return self._host_disponibilita(body, headers)
        if metodo == "POST" and path == "/api/host/disponibilita_range":
            return self._host_disponibilita_range(body, headers)
        if metodo == "POST" and path == "/api/host/registrazione":
            return self._host_registrazione(body, headers)
        if metodo == "POST" and path == "/api/host/login":
            return self._host_login(body)
        if metodo == "GET" and path == "/api/host/referral":
            return self._host_referral(query, headers)
        if metodo == "GET" and path == "/api/host/link_diretto":
            return self._host_link_diretto(query, headers)
        if metodo == "GET" and path == "/api/host/richieste":
            return self._host_richieste(query, headers)
        if metodo == "GET" and path == "/api/host/payout":
            return self._host_payout(query, headers)
        if metodo == "POST" and path == "/api/host/richieste/approva":
            return self._host_richiesta_decisione(body, headers, True)
        if metodo == "POST" and path == "/api/host/richieste/rifiuta":
            return self._host_richiesta_decisione(body, headers, False)
        if metodo == "POST" and path == "/api/host/ical":
            return self._host_ical(body, headers)
        if metodo == "GET" and path == "/api/host/metriche":
            return self._host_metriche(query, headers)
        if metodo == "GET" and path == "/api/host/calendario":
            return self._host_calendario(query, headers)
        if metodo == "GET" and path == "/api/host/export":
            return self._host_export(query, headers)
        if metodo == "GET" and path == "/api/host/alloggi":
            return self._host_alloggi(query, headers)
        if metodo == "GET" and path == "/api/host/accettazioni":
            return self._host_accettazioni(query, headers)
        if metodo == "POST" and path == "/api/host/stato":
            return self._host_stato(body, headers)
        if metodo == "GET" and path == "/api/admin/prenotazioni":
            return self._admin_prenotazioni(query, headers)
        if metodo == "POST" and path == "/api/admin/rimborso":
            return self._admin_rimborso(body, headers)
        if metodo == "POST" and path == "/api/admin/cancella_attivita":
            return self._admin_cancella_attivita(body, headers)
        return 404, {"errore": "rotta_non_trovata"}

    # --- helper ---
    @staticmethod
    def _json(body: Optional[str]) -> Optional[Dict[str, Any]]:
        try:
            d = json.loads(body) if body else None
            return d if isinstance(d, dict) else None
        except (ValueError, TypeError):
            return None

    def _host_id_da_token(self, headers: Dict[str, str]) -> Optional[str]:
        """host_id se la richiesta porta un token host self-service valido, altrimenti None."""
        reg = getattr(self._sys, "registro_host", None)
        if reg is None:
            return None
        tok = headers.get("X-Host-Token", "") or headers.get("x-host-token", "")
        if not tok:
            return None
        try:
            return reg.verifica_token(tok)
        except Exception:
            return None

    def _auth_host(self, headers: Dict[str, str]) -> bool:
        # 1) token host self-service valido
        if self._host_id_da_token(headers):
            return True
        # 2) chiave condivisa dell'operatore (o dev aperto se non configurata)
        if self._host_key is None:
            return True
        import hmac
        fornita = headers.get("X-Host-Key", "") or headers.get("x-host-key", "")
        return hmac.compare_digest(str(fornita), str(self._host_key))

    def _upload_foto(self, body, headers):
        """Upload foto alloggio (base64) -> salva su UPLOAD_DIR -> ritorna l'URL /uploads/<nome>,
        che il catalogo/vetrina mostra come qualsiasi immagine. Host-auth. BLINDATO: valida il
        TIPO dai byte (mai fidarsi del content_type), tetto 5MB, nome casuale (no path/collisioni)."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        dati = self._json(body)
        if not isinstance(dati, dict):
            return 400, {"errore": "json_non_valido"}
        import base64 as _b64, os as _os, secrets as _sec
        raw64 = dati.get("image_base64") or ""
        if isinstance(raw64, str) and raw64.startswith("data:") and "," in raw64:
            raw64 = raw64.split(",", 1)[1]        # data URI -> tieni solo il payload base64
        try:
            raw = _b64.b64decode(raw64, validate=True)
        except Exception:
            return 422, {"errore": "immagine_non_valida"}
        if not raw or len(raw) > 5 * 1024 * 1024:
            return 422, {"errore": "dimensione_non_valida"}      # vuota o > 5MB
        ext = None                                                # tipo dai MAGIC BYTES
        if raw[:3] == b"\xff\xd8\xff":
            ext = "jpg"
        elif raw[:8] == b"\x89PNG\r\n\x1a\n":
            ext = "png"
        elif raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
            ext = "webp"
        elif raw[:6] in (b"GIF87a", b"GIF89a"):
            ext = "gif"
        if ext is None:
            return 422, {"errore": "formato_non_supportato"}
        updir = _os.environ.get("UPLOAD_DIR", "data/uploads")
        try:
            _os.makedirs(updir, exist_ok=True)
            nome = _sec.token_hex(16) + "." + ext
            with open(_os.path.join(updir, nome), "wb") as f:
                f.write(raw)
        except Exception:
            logger.error("upload foto: salvataggio fallito (ISOLATO)", exc_info=True)
            return 503, {"errore": "storage_non_disponibile"}
        return 201, {"url": "/uploads/" + nome}

    def _auth_admin(self, headers: Dict[str, str]) -> bool:
        if self._admin_key is None:
            return True            # nessuna chiave configurata = aperto (dev)
        import hmac
        fornita = headers.get("X-Admin-Key", "") or headers.get("x-admin-key", "")
        return hmac.compare_digest(str(fornita), str(self._admin_key))

    # --- admin: dashboard rimborsi ---
    def _admin_prenotazioni(self, query, headers):
        if not self._auth_admin(headers):
            return 401, {"errore": "unauthorized"}
        alloggio = query.get("alloggio") or None
        try:
            el = self._sys.inventario.elenco_prenotazioni(alloggio_id=alloggio, limit=100)
        except Exception:
            logger.error("admin prenotazioni: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        return 200, {"prenotazioni": el}

    def _admin_cancella_attivita(self, body, headers):
        """TASTO 'cancella tutto': rimuove un host da OGNI archivio (fase156) e VERIFICA che
        non resti nulla. 200 se ok (0 residui), 409 se qualcosa e' rimasto (con il dettaglio)."""
        if not self._auth_admin(headers):
            return 401, {"errore": "unauthorized"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        host_id = dati.get("host_id")
        if not (isinstance(host_id, str) and host_id):
            return 422, {"errore": "host_id_mancante"}
        try:
            from fase156_erasure import cancella_attivita_host
            rep = cancella_attivita_host(self._sys, host_id)
        except Exception:
            logger.error("admin cancella attivita: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        return (200 if rep.get("ok") else 409), rep

    def _admin_rimborso(self, body, headers):
        """Rimborso = cancellazione: libera le date sull'inventario (fase58.rilascia).
        Il rimborso Stripe vero si esegue quando il PSP e' attivo (gated)."""
        if not self._auth_admin(headers):
            return 401, {"errore": "unauthorized"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        alloggio = dati.get("alloggio_id")
        ci, co = dati.get("check_in"), dati.get("check_out")
        idem = dati.get("idem_key")
        if not all(isinstance(x, str) and x for x in (alloggio, ci, co, idem)):
            return 422, {"errore": "campi_non_validi"}
        try:
            e = self._sys.inventario.rilascia(alloggio, ci, co, idem_key=idem)
        except Exception:
            logger.error("admin rimborso: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        if not getattr(e, "ok", False):
            return 409, {"stato": "rifiutato", "motivo": getattr(e, "motivo", "")}
        return 200, {"stato": "rimborsato", "date_liberate": True,
                     "idempotente": bool(getattr(e, "idempotente", False)),
                     "nota": "date liberate; rimborso PSP da eseguire quando Stripe e' live"}

    def _traduci_servizi(self, item: Dict[str, Any], lingua: str) -> Dict[str, Any]:
        if isinstance(item.get("servizi"), list):
            item = dict(item)
            item["servizi_label"] = [self._loc.servizio(c, lingua)
                                     for c in item["servizi"]]
        return item

    # --- rotte cliente ---
    def _catalogo(self, query):
        from fase57_vetrina import CriteriRicerca, PAGINA_MAX
        lingua = _lingua(query)

        def _int(k):
            try:
                return int(query[k]) if query.get(k) not in (None, "") else None
            except (ValueError, TypeError):
                return None
        servizi = tuple(s for s in query.get("servizi", "").split(",") if s)
        # "VICINO A ME": il cliente passa la SUA posizione (microgradi interi) + raggio km.
        # Il CORE calcola un bounding-box (fase121), filtra in SQL, poi ordina per distanza
        # haversine REALE (cerchio, non quadrato) e taglia. La geo non si delega: l'IA/frontend
        # propone la posizione, il CORE decide cosa e' "vicino". Geo SEMPRE intera.
        geo = self._centro_geo(query)
        bbox_t = None
        if geo is not None:
            from fase121_geo_ricerca import bbox as _bbox
            b = _bbox(geo[0], geo[1], geo[2])
            if b is not None:
                bbox_t = (b["lat_min"], b["lat_max"], b["lon_min"], b["lon_max"])
            else:
                geo = None
        limit_req = _int("limit") or 24
        criteri = CriteriRicerca(
            citta=query.get("citta") or None,
            prezzo_min_cents=_int("prezzo_min_cents"),
            prezzo_max_cents=_int("prezzo_max_cents"),
            capacita_min=_int("capacita_min"), servizi=servizi,
            ordine=query.get("ordine", "recente"),
            # con geo prendo TUTTO il box (poi riordino per distanza qui sotto)
            limit=(PAGINA_MAX if geo is not None else limit_req),
            offset=(0 if geo is not None else (_int("offset") or 0)),
            bbox=bbox_t,
            check_in=query.get("check_in") or None,
            check_out=query.get("check_out") or None)
        res = self._sys.catalogo.cerca(criteri)
        res = dict(res)
        cards = []
        for r in res["risultati"]:
            card = self._traduci_servizi(r, lingua)
            rie = self._riepilogo_recensioni(card.get("slug"))
            if rie:
                card["recensioni"] = rie
            cards.append(card)
        # Politica di cancellazione + badge "cancellazione gratuita" (leva di conversione, come i
        # colossi). 'gratuita' = flessibile/moderata (annullabile con rimborso pieno per tempo).
        for card in cards:
            pol = card.get("politica_cancellazione") or self._politica_alloggio(card.get("slug"))
            card["politica_cancellazione"] = pol
            card["cancellazione_gratuita"] = pol in ("flessibile", "moderata")
        if str(query.get("solo_gratuita", "")).lower() in ("1", "true", "yes", "on"):
            cards = [c for c in cards if c.get("cancellazione_gratuita")]
            if geo is None:
                res["totale"] = len(cards)
        if geo is not None:
            vicini = self._entro_raggio(cards, geo)   # filtrati+ordinati, NON tagliati
            res["totale"] = len(vicini)
            cards = vicini[:limit_req]
            res["ordine"] = "vicinanza"
        res["risultati"] = cards
        res["lingua"] = lingua
        return 200, res

    @staticmethod
    def _centro_geo(query):
        """(lat_micro, lon_micro, raggio_km) se la query chiede 'vicino a me', altrimenti None.
        Geo in microgradi INTERI; coordinate fuori dalla Terra -> None (ricerca normale).
        raggio default 5km, clamp [0.1, 200] (niente query assurde che scaricano il DB)."""
        def _int(k):
            try:
                v = query.get(k)
                return int(v) if v not in (None, "") else None
            except (ValueError, TypeError):
                return None
        lat, lon = _int("lat_micro"), _int("lon_micro")
        if lat is None or lon is None:
            return None
        if not (-90_000_000 <= lat <= 90_000_000) or not (-180_000_000 <= lon <= 180_000_000):
            return None
        try:
            raggio = float(query.get("raggio_km") or 5)
        except (ValueError, TypeError):
            raggio = 5.0
        if raggio != raggio or raggio <= 0:          # NaN o non positivo -> default
            raggio = 5.0
        return (lat, lon, max(0.1, min(200.0, raggio)))

    @staticmethod
    def _entro_raggio(cards, geo):
        """Filtra le card entro il raggio (cerchio REALE, haversine fase121) e le ordina per
        distanza crescente, aggiungendo 'distanza_m' (metri interi). Card senza coordinate o
        oltre il raggio -> escluse: 'vicino a me' mostra solo cio' che e' davvero vicino."""
        from fase121_geo_ricerca import distanza_m
        lat, lon, raggio = geo
        raggio_m = int(raggio * 1000)
        out = []
        for c in cards:
            la, lo = c.get("lat_micro"), c.get("lon_micro")
            if not isinstance(la, int) or isinstance(la, bool):
                continue
            if not isinstance(lo, int) or isinstance(lo, bool):
                continue
            d = distanza_m(lat, lon, la, lo)
            if 0 <= d <= raggio_m:
                c = dict(c)
                c["distanza_m"] = d
                out.append(c)
        out.sort(key=lambda x: x["distanza_m"])
        return out

    # --- recensioni verificate (fase63) ---
    def _riepilogo_recensioni(self, slug: Any) -> Optional[Dict[str, Any]]:
        if self._sys.recensioni is None or not isinstance(slug, str):
            return None
        try:
            r = self._sys.recensioni.riepilogo(slug)
            return {"conteggio": r["conteggio"], "media_centesimi": r["media_centesimi"]}
        except Exception:
            return None

    def _recensioni(self, slug):
        if self._sys.recensioni is None:
            return 503, {"errore": "recensioni_disattivate"}
        try:
            rie = self._sys.recensioni.riepilogo(slug)
            elenco = self._sys.recensioni.elenco(slug, 20)
        except Exception:
            logger.error("recensioni: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        return 200, {"riepilogo": rie, "recensioni": elenco}

    def _invia_recensione(self, body):
        if self._sys.recensioni is None:
            return 503, {"errore": "recensioni_disattivate"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        e = self._sys.recensioni.invia(dati.get("token"), dati.get("voto"),
                                       dati.get("testo", ""), dati.get("lingua", "en"))
        status = 201 if e.ok else (409 if e.motivo == "gia_recensita" else 400)
        return status, {"ok": e.ok, "motivo": e.motivo, "verificata": e.verificata}

    def _book(self, body):
        """Prenotazione (fase59) + emissione del DIRITTO di recensione (fase63)."""
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        r = self._sys.concierge.prenota(dati)
        status = int(getattr(r, "status", 200))
        corpo = dict(getattr(r, "corpo", {}) or {})
        if status == 201:
            allog = corpo.get("alloggio_id", "")
            if self._modalita_alloggio(allog) == "su_richiesta":
                # SU RICHIESTA: la stanza e' tenuta, l'host deve APPROVARE. Niente voucher/
                # escrow/pagamento/email finche' non approva -> cliente e host rispettati.
                self._registra_richiesta(corpo, dati)
                corpo["stato"] = "in_attesa_host"
                corpo.pop("payment_url", None)
                return status, corpo
            corpo = self._finalizza_prenotazione(corpo, dati)
        return status, corpo

    def _modalita_alloggio(self, slug):
        try:
            m = self._sys.catalogo.modalita_prenotazione_di(slug)
            return m if m in ("immediata", "su_richiesta") else "immediata"
        except Exception:
            return "immediata"

    def _finalizza_prenotazione(self, corpo, dati):
        """Emette voucher/smart-pass/diritto, apre l'escrow, avvisa l'host, gestisce l'hold
        pagamento. Usato dall'instant-book E dopo l'approvazione su-richiesta. Idempotente
        sui token (rigenera dagli stessi dati)."""
        ref = corpo.get("riferimento", "")
        allog = corpo.get("alloggio_id", "")
        ci, co = corpo.get("check_in", ""), corpo.get("check_out", "")
        pass_token = None
        if self._sys.emettitore_pass is not None:
            try:
                pass_token = self._sys.emettitore_pass.emetti(ref, allog, ci, co)
                corpo["smart_pass"] = pass_token
            except Exception:
                logger.warning("emissione smart-pass fallita (ignorata)", exc_info=True)
        if getattr(self._sys, "firma", None) is not None:
            try:
                import datetime as _dt
                qt = dati.get("quote_token", "")
                corpo["voucher_token"] = self._sys.firma.codifica({
                    "tipo": "voucher", "riferimento": ref, "alloggio_id": allog,
                    "check_in": ci, "check_out": co,
                    "prezzo_guest_cents": corpo.get("prezzo_guest_cents", 0),
                    "valuta": corpo.get("valuta", "EUR"),
                    "smart_pass": pass_token or "",
                    "tassa_soggiorno_cents": corpo.get("tassa_soggiorno_cents", 0),
                    "politica": self._politica_alloggio(allog),
                    "prenotato_data": _dt.date.today().isoformat(),   # per il ripensamento 48h
                    "idem_key": (qt.split(".")[-1] if isinstance(qt, str) and qt else "")})
            except Exception:
                logger.warning("emissione voucher fallita (ignorata)", exc_info=True)
        if self._sys.emettitore_recensioni is not None:
            try:
                corpo["diritto_recensione"] = self._sys.emettitore_recensioni.emetti(ref, allog)
            except Exception:
                logger.warning("emissione diritto recensione fallita (ignorata)", exc_info=True)
        email = dati.get("email")
        if getattr(self._sys, "email_provider", None) is not None \
                and isinstance(email, str) and "@" in email:
            try:
                from fase86_email import corpo_voucher_html
                from fase59_concierge import codice_prenotazione
                # SEMPRE assoluto: un link relativo (/voucher/...) NON è cliccabile da un'email.
                # Fallback al dominio se BASE_URL non è configurato (come altri link, es. host.html).
                vurl = ((self._base_url or "https://bookinvip.com") + "/voucher/"
                        + corpo["voucher_token"]) if corpo.get("voucher_token") else ""
                _codice = codice_prenotazione(ref)
                _pin = self._sys.firma.pin_checkin(ref) if getattr(self._sys, "firma", None) else ""
                html = corpo_voucher_html(allog, _codice, ci, co, vurl, pin=_pin)
                # IN BACKGROUND: l'SMTP (rete) non deve MAI rallentare la conferma prenotazione.
                # Il provider e' gia' fail-safe (non solleva); il thread e' daemon (isolato).
                import threading
                threading.Thread(
                    target=self._sys.email_provider.invia,
                    args=(email, "BookinVIP - Prenotazione confermata", html),
                    daemon=True).start()
            except Exception:
                logger.warning("invio email voucher fallito (ignorato)", exc_info=True)
        self._avvisa_host_prenotazione(allog, ref, ci, co, corpo.get("fonte", ""))
        self._apri_garanzia(ref, corpo.get("netto_host_cents", 0), allog, ci)
        self._registra_payout(ref, allog, corpo)
        self._registra_hold(corpo, allog, ref, ci, co, dati.get("quote_token", ""))
        return corpo

    def _registra_richiesta(self, corpo, dati):
        """Su-richiesta: registra la prenotazione 'in_attesa_host' (stanza tenuta) col corpo
        completo, cosi' l'approvazione puo' finalizzarla. Best-effort isolato."""
        try:
            pp = getattr(self._sys, "pagamenti_pendenti", None)
            if pp is None:
                return
            import json as _j
            import time as _t
            allog = corpo.get("alloggio_id", "")
            ref = corpo.get("riferimento", "")
            host, comune = "", ""
            try:
                host = self._sys.catalogo.host_di_alloggio(allog) or ""
                d = self._sys.catalogo.dettaglio(allog)
                comune = d.get("citta", "") if isinstance(d, dict) else ""
            except Exception:
                pass
            qt = dati.get("quote_token", "")
            idem = qt.split(".")[-1] if isinstance(qt, str) and qt else ""
            pp.registra(ref, alloggio_id=allog, check_in=corpo.get("check_in", ""),
                        check_out=corpo.get("check_out", ""), idem_key=idem,
                        tassa_cents=corpo.get("tassa_soggiorno_cents", 0), comune=comune,
                        host_id=host, email=str(dati.get("email", "")), quote_token=qt,
                        corpo_json=_j.dumps(corpo), stato="in_attesa_host",
                        scadenza_ts=int(_t.time()) + 86400)   # 24h per approvare
        except Exception:
            logger.warning("registra richiesta su-richiesta fallita (ignorata)", exc_info=True)

    def _host_richieste(self, query, headers):
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        pp = getattr(self._sys, "pagamenti_pendenti", None)
        if pp is None:
            return 200, {"richieste": []}
        host_id = self._host_id_da_token(headers) or query.get("host_id")
        if not (isinstance(host_id, str) and host_id):
            return 422, {"errore": "host_id_mancante"}
        return 200, {"richieste": pp.da_approvare(host_id)}

    def _host_richiesta_decisione(self, body, headers, approva):
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        pp = getattr(self._sys, "pagamenti_pendenti", None)
        if pp is None:
            return 503, {"errore": "richieste_non_attive"}
        ref = dati.get("riferimento")
        rec = pp.info(ref) if isinstance(ref, str) else None
        if rec is None or rec.get("stato") != "in_attesa_host":
            return 404, {"errore": "richiesta_non_trovata"}
        host_id = self._host_id_da_token(headers) or dati.get("host_id")
        if rec.get("host_id") and host_id and rec["host_id"] != host_id:
            return 403, {"errore": "non_tua"}
        import json as _j
        if approva:
            pp.rimuovi(ref)                       # tolgo la richiesta, poi finalizzo
            try:
                corpo = _j.loads(rec.get("corpo_json") or "{}")
            except Exception:
                corpo = {}
            corpo["stato"] = "confermata"
            corpo = self._finalizza_prenotazione(
                corpo, {"email": rec.get("email", ""), "quote_token": rec.get("quote_token", "")})
            return 200, {"stato": "approvata", "riferimento": ref, "prenotazione": corpo}
        try:                                       # rifiuto: libero la stanza, zero addebito
            self._sys.inventario.rilascia(rec["alloggio_id"], rec["check_in"], rec["check_out"],
                                          idem_key=rec.get("idem_key") or ("hold_" + str(ref)))
        except Exception:
            logger.warning("rilascio su rifiuto richiesta fallito (ignorato)", exc_info=True)
        pp.rimuovi(ref)
        return 200, {"stato": "rifiutata", "riferimento": ref}

    def _registra_hold(self, corpo, allog, ref, ci, co, qt):
        if not corpo.get("payment_url"):
            return
        try:
            pp = getattr(self._sys, "pagamenti_pendenti", None)
            if pp is None or not ref:
                return
            comune = ""
            try:
                d = self._sys.catalogo.dettaglio(allog)
                comune = d.get("citta", "") if isinstance(d, dict) else ""
            except Exception:
                pass
            idem = qt.split(".")[-1] if isinstance(qt, str) and qt else ""
            host_id = ""
            try:
                host_id = self._sys.catalogo.host_di_alloggio(allog) or ""
            except Exception:
                host_id = ""
            import json as _j2
            # salvo i dati minimi per gestire un pagamento TARDIVO (re-blocco + payout) in sicurezza
            corpo_min = _j2.dumps({"netto_host_cents": corpo.get("netto_host_cents", 0),
                                   "valuta": corpo.get("valuta", "EUR"),
                                   "host_id": host_id})
            pp.registra(ref, alloggio_id=allog, check_in=ci, check_out=co, idem_key=idem,
                        tassa_cents=corpo.get("tassa_soggiorno_cents", 0), comune=comune,
                        host_id=host_id, corpo_json=corpo_min)
            corpo["stato"] = "in_attesa_pagamento"   # confermata SOLO dopo il webhook di pagamento
        except Exception:
            logger.warning("registrazione hold pagamento fallita (ignorata)", exc_info=True)

    def _apri_garanzia(self, ref, netto_host_cents, allog, ci):
        try:
            g = getattr(self._sys, "garanzia", None)
            if g is None or not ref:
                return
            import datetime
            try:
                ts = int(datetime.datetime.fromisoformat(ci + "T15:00:00").timestamp())
            except Exception:
                ts = None
            g.apri(ref, netto_host_cents, alloggio_id=allog, ora_checkin_ts=ts)
        except Exception:
            logger.warning("apertura garanzia fallita (ignorata)", exc_info=True)

    def _registra_payout(self, ref, allog, corpo):
        """Registra l'incasso ATTESO dell'host (stato 'maturato') nella dashboard payout
        (fase131), per valuta. Solo tracciamento per l'host; il payout vero e' gated (Stripe
        Connect). Isolato/fail-safe: se salta, la prenotazione resta intatta."""
        try:
            pd = getattr(self._sys, "payout", None)
            if pd is None or not (isinstance(ref, str) and ref):
                return
            netto = corpo.get("netto_host_cents", 0)
            if not isinstance(netto, int) or isinstance(netto, bool) or netto <= 0:
                return
            host = ""
            try:
                host = self._sys.catalogo.host_di_alloggio(allog) or ""
            except Exception:
                host = ""
            if not host:
                return
            valuta = corpo.get("valuta", "EUR")
            valuta = valuta if isinstance(valuta, str) else "EUR"
            # Se c'è un pagamento online pendente -> payout 'in_attesa' (NON conta come guadagno
            # finché non paga; se l'hold scade viene rimosso). Senza pagamento online (conferma
            # immediata / su-richiesta approvata) -> 'maturato'. Fine dei "guadagni" fantasma.
            if corpo.get("payment_url"):
                pd.registra_in_attesa(ref, host, netto, valuta)
            else:
                pd.registra_maturato(ref, host, netto, valuta)
        except Exception:
            logger.warning("registra payout fallito (ignorato)", exc_info=True)

    def _payout_trattieni(self, rif):
        """Prenotazione cancellata -> il payout atteso passa a 'trattenuto' (l'host non vede piu'
        un incasso che non arrivera'). Isolato."""
        try:
            pd = getattr(self._sys, "payout", None)
            if pd is not None and isinstance(rif, str) and rif:
                pd.aggiorna_stato(rif, "trattenuto")
        except Exception:
            logger.warning("payout trattieni fallito (ignorato)", exc_info=True)

    def _host_payout(self, query, headers):
        """Dashboard payout dell'host: incassi attesi/in-transito/pagati PER VALUTA (fase131)."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        pd = getattr(self._sys, "payout", None)
        if pd is None:
            return 200, {"payout": {}}
        host_id = self._host_id_da_token(headers) or query.get("host_id")
        if not (isinstance(host_id, str) and host_id):
            return 422, {"errore": "host_id_mancante"}
        return 200, {"payout": pd.riepilogo(host_id)}

    def _garanzia_da_voucher(self, body):
        dati = self._json(body)
        if dati is None:
            return None, (400, {"errore": "json_non_valido"})
        token = dati.get("voucher_token")
        firma = getattr(self._sys, "firma", None)
        if firma is None or not isinstance(token, str) or not token:
            return None, (400, {"errore": "voucher_mancante"})
        v = firma.decodifica(token)
        if not isinstance(v, dict) or v.get("tipo") != "voucher":
            return None, (400, {"errore": "voucher_non_valido"})
        ref = v.get("riferimento", "")
        if not ref:
            return None, (422, {"errore": "riferimento_mancante"})
        return (ref, dati), None

    def _garanzia_conferma(self, body):
        """L'ospite e' entrato e conferma 'tutto come dichiarato' -> i soldi vanno all'host."""
        res, err = self._garanzia_da_voucher(body)
        if err:
            return err
        g = getattr(self._sys, "garanzia", None)
        if g is None:
            return 503, {"errore": "garanzia_non_attiva"}
        out = g.conferma_ospite(res[0])
        return (200 if out.get("ok") else 409), out

    def _garanzia_contesta(self, body):
        """Servizio dichiarato mancante / non conforme -> i fondi NON vanno all'host (apre disputa)."""
        res, err = self._garanzia_da_voucher(body)
        if err:
            return err
        g = getattr(self._sys, "garanzia", None)
        if g is None:
            return 503, {"errore": "garanzia_non_attiva"}
        out = g.contesta(res[0], str(res[1].get("motivo", "")))
        return (200 if out.get("ok") else 409), out

    def _garanzia_stato(self, query, headers):
        if not self._auth_admin(headers):
            return 401, {"errore": "unauthorized"}
        g = getattr(self._sys, "garanzia", None)
        if g is None:
            return 503, {"errore": "garanzia_non_attiva"}
        st = g.stato(query.get("ref"))
        return (200, st) if st else (404, {"errore": "non_trovata"})

    def _cancella_prenotazione(self, body):
        """Cancellazione SELF-SERVICE dell'ospite: presenta il voucher firmato -> il sistema
        calcola il rimborso secondo la politica (fase111, in cents) e LIBERA le date
        (fase58.rilascia). Il rimborso PSP vero parte quando Stripe e' live (gated)."""
        import datetime
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        token = dati.get("voucher_token")
        firma = getattr(self._sys, "firma", None)
        if firma is None or not isinstance(token, str) or not token:
            return 400, {"errore": "voucher_mancante"}
        v = firma.decodifica(token)
        if not isinstance(v, dict) or v.get("tipo") != "voucher":
            return 400, {"errore": "voucher_non_valido"}
        allog = v.get("alloggio_id", "")
        ci, co = v.get("check_in", ""), v.get("check_out", "")
        rif = v.get("riferimento", "")
        pagato = v.get("prezzo_guest_cents", 0)
        if not all(isinstance(x, str) and x for x in (allog, ci, co)):
            return 422, {"errore": "voucher_incompleto"}
        try:
            giorni = (datetime.date.fromisoformat(ci) - datetime.date.today()).days
        except Exception:
            giorni = 0
        giorni = giorni if giorni > 0 else 0
        # POLITICA dal VOUCHER FIRMATO (scelta dall'host, anti-furbata) - NON dalla richiesta
        politica = v.get("politica") or self._politica_alloggio(allog)
        # RIPENSAMENTO 48h: se annulli entro 2 giorni dall'acquisto e l'arrivo è >=72h -> 100%
        # (copre e SUPERA California SB 644 [24h] + diritto di pentimento Brasile art.49). Vince
        # su qualunque politica; NON si applica a soggiorni imminenti/passati (arrivo < 3 giorni).
        ripensamento = False
        try:
            _pren = v.get("prenotato_data")
            if isinstance(_pren, str) and _pren:
                _gg_pren = (datetime.date.today() - datetime.date.fromisoformat(_pren)).days
                ripensamento = (0 <= _gg_pren <= 2) and (giorni >= 3)
        except Exception:
            ripensamento = False
        try:
            from fase111_cancellazione import calcola_rimborso
            r = calcola_rimborso(pagato, giorni, politica=politica,
                                 entro_ripensamento=ripensamento)
            idem = v.get("idem_key") or ("cancel_" + (rif or token[-16:]))
            e = self._sys.inventario.rilascia(allog, ci, co, idem_key=idem)
        except Exception:
            logger.error("cancella prenotazione: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        if not getattr(e, "ok", False):
            return 409, {"stato": "rifiutato", "motivo": getattr(e, "motivo", "")}
        self._payout_trattieni(rif)            # cancellata -> niente payout all'host
        # CREDITO VIAGGIO ANTI-RIMPIANTO: se hai perso qualcosa, una parte torna come credito
        # (non-cashabile, riscattabile su una prossima prenotazione; ci costa solo margine futuro).
        # la tassa di soggiorno (pass-through) si rimborsa SEMPRE per intero: niente soggiorno = niente tassa
        tassa = v.get("tassa_soggiorno_cents", 0)
        tassa = tassa if (isinstance(tassa, int) and not isinstance(tassa, bool) and tassa > 0) else 0
        rimborso_totale = r.get("rimborso_cents", 0) + tassa
        cv_cents, cv_token = self._credito_anti_rimpianto(r.get("trattenuto_cents", 0))
        try:                                      # escrow: l'host TIENE la sua penale, il resto torna all'ospite
            gz = getattr(self._sys, "garanzia", None)
            if gz is not None:
                st = gz.stato(rif)
                imp = st.get("importo_host_cents", 0) if isinstance(st, dict) else 0
                tratt = r.get("trattenuto_cents", 0)
                host_tiene = (imp * tratt // pagato) if (imp and pagato and tratt) else 0
                if host_tiene > 0:
                    gz.chiudi_proporzionale(rif, host_tiene)
                else:
                    gz.annulla(rif)               # rimborso pieno -> host 0
        except Exception:
            logger.warning("chiusura garanzia su cancellazione fallita (ignorato)", exc_info=True)
        return 200, {"stato": "cancellata", "riferimento": rif,
                     "giorni_all_arrivo": giorni, "date_liberate": True,
                     "rimborso_cents": rimborso_totale,                 # soggiorno + tassa
                     "rimborso_soggiorno_cents": r["rimborso_cents"],
                     "tassa_rimborsata_cents": tassa,
                     "trattenuto_cents": r["trattenuto_cents"],
                     "politica": r["politica"], "money_unit": "cents_integer",
                     "ripensamento": bool(r.get("ripensamento")),
                     "credito_viaggio_cents": cv_cents, "credito_viaggio_token": cv_token,
                     "nota": ("date liberate; rimborso PSP da eseguire quando Stripe e' live."
                              + (" Hai un Credito Viaggio per la prossima prenotazione."
                                 if cv_cents else ""))}

    def _politica_alloggio(self, slug):
        try:
            return self._sys.catalogo.politica_cancellazione_di(slug)
        except Exception:
            return "flessibile"

    def _credito_anti_rimpianto(self, trattenuto_cents):
        """Trasforma il 50% della penale in un Credito Viaggio firmato (tetto 5000 cents).
        Riusa il riscatto floor-guarded del concierge (tipo 'credito_fondatore')."""
        import time
        firma = getattr(self._sys, "firma", None)
        t = trattenuto_cents if isinstance(trattenuto_cents, int) and trattenuto_cents > 0 else 0
        cv = min(5000, t // 2)
        if firma is None or cv <= 0:
            return 0, ""
        try:
            tok = firma.codifica({"tipo": "credito_fondatore", "email": "", "citta": "",
                                  "credito_cents": cv, "exp": int(time.time()) + 365 * 86400})
            return cv, tok
        except Exception:
            return 0, ""

    def _avvisa_host_prenotazione(self, allog, ref, ci, co, origine):
        """Notifica l'host della nuova prenotazione (email + WhatsApp gated). Best-effort:
        ogni errore e' ISOLATO, non blocca mai la prenotazione gia' confermata."""
        try:
            notif = getattr(self._sys, "notificatore_prenotazione", None)
            reg = getattr(self._sys, "registro_host", None)
            if notif is None or not notif.attivo() or reg is None:
                return
            hid = self._sys.catalogo.host_di_alloggio(allog)
            contatti = reg.info_host(hid) if hid else None
            if not contatti:
                return
            d = self._sys.catalogo.dettaglio(allog) or {}
            from fase152_notifiche_prenotazione import componi_avviso_host
            from fase61_localizzazione import Localizzatore, lingua_da_telefono
            from fase59_concierge import codice_prenotazione
            lingua = (lingua_da_telefono(contatti.get("telefono"))
                      if contatti.get("telefono") else "it")
            titolo = (d.get("titolo") if isinstance(d, dict) else None) or allog
            # stesso codice + PIN che vede il cliente (per il check-in)
            _pin = self._sys.firma.pin_checkin(ref) if getattr(self._sys, "firma", None) else ""
            ogg, testo = componi_avviso_host(
                Localizzatore(), alloggio=titolo, ci=ci, co=co, origine=origine,
                riferimento=codice_prenotazione(ref), pin=_pin,
                link_pannello=(self._base_url or "https://bookinvip.com") + "/host.html",
                lingua=lingua)
            notif.avvisa(contatti, ogg, testo)
        except Exception:
            logger.warning("avviso host prenotazione fallito (ignorato)", exc_info=True)

    def _domanda_registra(self, body):
        """Lista d'attesa anti-vuoto: l'ospite lascia email+citta quando non trova nulla ->
        riceve il Credito Fondatore (token firmato). Pubblico (nessuna auth)."""
        dom = getattr(self._sys, "domanda", None)
        if dom is None:
            return 503, {"errore": "domanda_non_attiva"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        email, citta = dati.get("email"), dati.get("citta")
        # città mancante NON deve bloccare la cattura email (è il cuore del cold-start):
        # fallback "(qualsiasi)" -> una email valida si registra SEMPRE. Fallisce solo se l'email
        # è davvero invalida (errore onesto, non più "email_o_citta").
        citta_eff = citta.strip() if isinstance(citta, str) and citta.strip() else "(qualsiasi)"
        if not dom.registra(email, citta_eff, check_in=str(dati.get("check_in", "")),
                            check_out=str(dati.get("check_out", "")),
                            party=dati.get("party", 1)):
            return 422, {"errore": "email_non_valida"}
        from fase158_domanda import CREDITO_FONDATORE_CENTS
        credito = dom.emette_credito_fondatore(email, citta_eff)
        # ALLARME DOMANDA: se la città supera la soglia, avvisa gli host (UNA volta, best-effort)
        try:
            if citta_eff != "(qualsiasi)":
                n_att = dom.conta(citta_eff)
                if self._allarme_domanda().controlla(citta_eff, n_att):
                    self._notifica_host_domanda(citta_eff, n_att)
        except Exception:
            logger.warning("allarme domanda fallito (ignorato)", exc_info=True)
        lang = dati.get("lang")
        lang = lang if lang in LINGUE_SUPPORTATE else "it"
        dest = citta_eff if citta_eff != "(qualsiasi)" else _ui("wl_dest_generica", lang)
        return 201, {"ok": True, "credito_token": credito or "",
                     "credito_cents": CREDITO_FONDATORE_CENTS,
                     "messaggio": _ui("wl_msg_tpl", lang) % dest}

    def _domanda_conta(self, query):
        """Prova sociale per gli host: quante persone cercano (totale o per citta)."""
        dom = getattr(self._sys, "domanda", None)
        if dom is None:
            return 503, {"errore": "domanda_non_attiva"}
        citta = query.get("citta")
        return 200, {"citta": citta or "", "richieste": dom.conta(citta)}

    def _domanda_per_citta(self, query):
        """Mappa della DOMANDA: città con più persone in attesa. Arma cold-start per gli host
        ('N persone cercano già a X') e prova sociale per gli ospiti. Pubblico (aggregato, no email)."""
        dom = getattr(self._sys, "domanda", None)
        if dom is None:
            return 503, {"errore": "domanda_non_attiva"}
        try:
            limit = max(1, min(100, int(query.get("limit", "20"))))
        except (ValueError, TypeError):
            limit = 20
        soglia = self._allarme_domanda().soglia
        citta = dom.per_citta(limit=limit)
        for c in citta:
            c["oltre_soglia"] = bool(c.get("richieste", 0) >= soglia)
        return 200, {"soglia": soglia, "citta": citta}

    def _allarme_domanda(self):
        a = getattr(self, "_allarme_cache", None)
        if a is None:
            import os
            from fase161_domanda_allarme import AllarmeDomanda
            try:
                soglia = int(os.environ.get("DOMANDA_SOGLIA", "5"))
            except (ValueError, TypeError):
                soglia = 5
            a = AllarmeDomanda(os.environ.get("DOMANDA_ALLARME_FILE", ""), soglia=soglia)
            self._allarme_cache = a
        return a

    def _notifica_host_domanda(self, citta, conteggio):
        """Best-effort: soglia domanda superata in 'citta' -> avvisa gli host con alloggi lì
        ('N cercano casa, aggiorna disponibilità'). ISOLATO, gated all'email (no-op se spento)."""
        try:
            notif = getattr(self._sys, "notificatore_prenotazione", None)
            reg = getattr(self._sys, "registro_host", None)
            if notif is None or not notif.attivo() or reg is None:
                return
            from fase57_vetrina import CriteriRicerca
            res = self._sys.catalogo.cerca(CriteriRicerca(citta=citta, limit=50)) or {}
            visti = set()
            nome = str(citta).title()
            base = self._base_url or "https://bookinvip.com"
            for card in (res.get("risultati") or []):
                hid = self._sys.catalogo.host_di_alloggio(card.get("slug"))
                if not hid or hid in visti:
                    continue
                visti.add(hid)
                contatti = reg.info_host(hid)
                if not contatti:
                    continue
                ogg = "🔥 Domanda in crescita a %s" % nome
                testo = ("%d persone stanno cercando casa a %s proprio ora su BookinVIP. "
                         "Aggiorna disponibilità e prezzi per ricevere prenotazioni: %s/host.html"
                         % (int(conteggio), nome, base))
                notif.avvisa(contatti, ogg, testo)
        except Exception:
            logger.warning("notifica domanda host fallita (ignorata)", exc_info=True)

    def _trasparenza(self, query):
        """Confronto noi-vs-OTA (fase69): 'con Booking incassi X, con noi Y'."""
        from fase69_trasparenza import confronta_piattaforma
        try:
            prezzo = int(query.get("prezzo_cents", "0"))
        except (ValueError, TypeError):
            prezzo = 0
        ota = query.get("ota", "booking")
        return 200, confronta_piattaforma(prezzo, ota).as_dict()

    def _dettaglio(self, slug, lingua):
        d = self._sys.catalogo.dettaglio(slug)
        if d is None:
            return 404, {"errore": "not_found"}
        d = self._traduci_servizi(d, lingua)
        rie = self._riepilogo_recensioni(slug)
        if rie:
            d["recensioni"] = rie
        return 200, d

    def _contratto(self, body):
        """Contratto di locazione breve PDF (fase145) precompilato dal VOUCHER FIRMATO: il
        prezzo e le date vengono dalla firma (non manomettibili). Ritorna le righe + il PDF in
        base64 (download lato client). Isolato/fail-safe."""
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        firma = getattr(self._sys, "firma", None)
        token = dati.get("voucher_token")
        v = firma.decodifica(token) if (firma and isinstance(token, str) and token) else None
        if not isinstance(v, dict) or v.get("tipo") != "voucher":
            return 400, {"errore": "voucher_non_valido"}
        allog = v.get("alloggio_id", "")
        host, citta = "", ""
        try:
            d = self._sys.catalogo.dettaglio(allog)
            citta = d.get("citta", "") if isinstance(d, dict) else ""
            host = self._sys.catalogo.host_di_alloggio(allog) or ""
        except Exception:
            pass
        lingua = dati.get("lingua") if dati.get("lingua") in ("it", "en") else "it"
        info = {"host": host, "alloggio": allog, "citta": citta,
                "check_in": v.get("check_in", ""), "check_out": v.get("check_out", ""),
                "prezzo_cents": v.get("prezzo_guest_cents", 0), "valuta": v.get("valuta", "EUR"),
                "riferimento": v.get("riferimento", "")}
        try:
            from fase145_contratto_pdf import genera_pdf, componi_contratto
            import base64
            pdf = genera_pdf(info, lingua=lingua)
            return 200, {"righe": componi_contratto(info, lingua=lingua),
                         "pdf_base64": base64.b64encode(pdf).decode("ascii"),
                         "filename": "contratto_%s.pdf" % (info["riferimento"] or "bookinvip")}
        except Exception:
            logger.error("contratto: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}

    def _split_preview(self, body):
        """Dividi un totale fra N amici in quote UGUALI a conservazione esatta (fase133).
        Puro/read-only: nessun denaro mosso, solo anteprima."""
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        from fase133_split_quote_uguali import riparti_uguale
        quote = riparti_uguale(dati.get("totale_cents"), dati.get("n"))
        if not quote:
            return 400, {"errore": "parametri_non_validi"}
        return 200, {"quote": quote, "n": len(quote), "totale_cents": sum(quote),
                     "per_persona_min_cents": min(quote),
                     "per_persona_max_cents": max(quote), "money_unit": "cents_integer"}

    def _concierge(self, fn, body):
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        r = fn(dati)
        return int(getattr(r, "status", 200)), getattr(r, "corpo", {}) or {}

    def _concierge_quote(self, body):
        """Preventivo firmato (fase59) + CONFRONTO OTA lato ospite (fase125): a parita' di
        soggiorno, quanto pagherebbe su un OTA (markup host + guest fee + DCC). Voce 'risparmio'
        per piu' conversioni. Isolato e fail-safe: se salta, la quote resta intatta."""
        status, corpo = self._concierge(self._sys.concierge.quota, body)
        if status == 200 and isinstance(corpo, dict):
            try:
                from fase125_confronto_guest import confronta_guest
                base = corpo.get("prezzo_guest_cents")
                if isinstance(base, int) and not isinstance(base, bool) and base > 0:
                    valuta = corpo.get("valuta", "EUR")
                    vi = corpo.get("valuta_indicativa") or ""
                    c = confronta_guest(base, valuta_diversa=bool(vi and vi != valuta))
                    if c.get("risparmio_guest_cents", 0) > 0:
                        corpo["confronto_ota"] = {
                            "ota_totale_cents": c["ota_totale_cents"],
                            "nostro_totale_cents": c["nostro_totale_cents"],
                            "risparmio_guest_cents": c["risparmio_guest_cents"],
                            "risparmio_bps": c["risparmio_bps"]}
            except Exception:
                logger.warning("confronto OTA quote fallito (ignorato)", exc_info=True)
        return status, corpo

    def _marketing_campagna(self, body, headers):
        """Genera + pubblica una campagna sui canali configurati (gated da env).
        Admin-only. Senza canali -> report con tutti saltati (niente rete)."""
        if not self._auth_admin(headers):
            return 401, {"errore": "unauthorized"}
        mk = getattr(self._sys, "marketing", None)
        if mk is None:
            return 503, {"errore": "marketing_non_attivo"}
        d = self._json(body) or {}
        lingue = d.get("lingue") if isinstance(d.get("lingue"), list) else ["it", "en"]
        try:
            rep = mk.esegui_campagna([str(l) for l in lingue][:5])
        except Exception:
            logger.error("marketing campagna: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        return 200, rep

    # --- motori: tassa di soggiorno (66) + split-payment (65) ---
    def _tassa(self, query):
        eng = getattr(self._sys, "tasse", None)
        if eng is None:
            return 503, {"errore": "tassa_non_attiva"}
        try:
            notti = int(query.get("notti", "0"))
            ospiti = int(query.get("ospiti", "0"))
            imp = int(query.get("imponibile_cents", "0"))
            esenti = int(query.get("esenti", "0"))
        except (ValueError, TypeError):
            return 422, {"errore": "parametri_non_validi"}
        giur = query.get("giurisdizione") or query.get("citta") or ""
        return 200, eng.calcola(giur, notti=notti, ospiti=ospiti,
                                imponibile_cents=imp, esenti=esenti).as_dict()

    def _split_crea(self, body):
        eng = getattr(self._sys, "split", None)
        if eng is None:
            return 503, {"errore": "split_non_attivo"}
        d = self._json(body)
        if d is None:
            return 400, {"errore": "json_non_valido"}
        try:
            cid = eng.crea_conto(
                str(d.get("prenotazione_id", "")), str(d.get("alloggio_id", "")),
                d.get("totale_cents"), d.get("partecipanti") or [],
                metodo=str(d.get("metodo", "equo")), importi=d.get("importi"))
        except Exception:
            logger.error("split crea: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        if not cid:
            return 422, {"errore": "conto_non_valido"}
        return 201, {"conto_id": cid, "stato": eng.stato_conto(cid)}

    def _split_paga(self, body):
        eng = getattr(self._sys, "split", None)
        if eng is None:
            return 503, {"errore": "split_non_attivo"}
        d = self._json(body)
        if d is None:
            return 400, {"errore": "json_non_valido"}
        conto = str(d.get("conto_id", ""))
        part = str(d.get("partecipante_id", ""))
        idem = d.get("idem_key") or (conto + ":" + part)   # idempotente per partecipante
        try:
            e = eng.registra_pagamento(conto, part, idem_key=str(idem))
        except Exception:
            logger.error("split paga: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        if not e.ok:
            return 409, {"stato": "rifiutato", "motivo": e.motivo}
        return 200, {"stato": "pagato", "completato": bool(e.completato),
                     "idempotente": bool(getattr(e, "idempotente", False))}

    def _split_stato(self, query):
        eng = getattr(self._sys, "split", None)
        if eng is None:
            return 503, {"errore": "split_non_attivo"}
        st = eng.stato_conto(query.get("conto_id", ""))
        if st is None:
            return 404, {"errore": "conto_inesistente"}
        return 200, st

    def _webhook_stripe(self, body, headers):
        """Webhook Stripe (conferma pagamento): verifica la FIRMA sul body GREZZO prima di
        credere all'evento. GATED dal webhook secret."""
        secret = getattr(getattr(self._sys, "config", None), "stripe_webhook_secret", "")
        if not secret:
            return 503, {"errore": "webhook_non_configurato"}
        from fase87_stripe_webhook import gestisci_webhook
        sig = headers.get("Stripe-Signature", "") or headers.get("stripe-signature", "")
        ok, tipo, dati = gestisci_webhook(body or "", sig, secret)
        if not ok:
            return 400, {"errore": "firma_non_valida"}
        if tipo == "checkout.session.completed":
            rif = ""
            try:
                rif = (dati or {}).get("object", {}).get("metadata", {}).get(
                    "riferimento", "")
            except Exception:
                rif = ""
            logger.info("Stripe: pagamento CONFERMATO per riferimento '%s'", rif)
            self._conferma_pagamento(rif)
        return 200, {"ricevuto": True, "tipo": tipo}

    def _conferma_pagamento(self, rif):
        """Pagamento riuscito. Gestisce la GARA (chi paga prima se la prende):
        - hold ancora attivo ('in_attesa') -> conferma normale (stanza già bloccata).
        - hold SCADUTO (pagamento tardivo, oltre i 2 min) -> ri-tenta il blocco stanza:
            * se libera -> ancora sua (conferma + ricrea payout/garanzia);
            * se presa da chi ha pagato prima -> NON conferma, segnala il RIMBORSO (mai
              'soldi senza stanza', mai doppia prenotazione)."""
        if not (isinstance(rif, str) and rif):
            return
        try:
            pp = getattr(self._sys, "pagamenti_pendenti", None)
            rec = pp.info(rif) if pp is not None else None
            if rec is None:
                logger.warning("pagamento per riferimento sconosciuto '%s' (ignorato)", rif)
                return
            stato = rec.get("stato", "")
            if stato == "pagato":
                return                                    # webhook duplicato: idempotente
            if stato == "scaduto":
                # PAGAMENTO TARDIVO: la stanza era stata liberata. Ri-tento il blocco.
                inv = getattr(self._sys, "inventario", None)
                idem = rec.get("idem_key") or ("hold_" + rif)
                esito = None
                try:
                    esito = inv.blocca(rec["alloggio_id"], rec["check_in"], rec["check_out"],
                                       idem_key=idem, origine="pagamento_tardivo") if inv else None
                except Exception:
                    esito = None
                if not getattr(esito, "ok", False):
                    logger.error("RIMBORSARE: pagamento tardivo su stanza già presa - rif '%s' "
                                 "(alloggio %s %s->%s). Il cliente va rimborsato.",
                                 rif, rec.get("alloggio_id"), rec.get("check_in"), rec.get("check_out"))
                    try:
                        pp.marca_da_rimborsare(rif)
                    except Exception:
                        pass
                    return
                # ri-bloccata con successo: ricreo payout maturato + garanzia dai dati salvati
                import json as _j3
                try:
                    dj = _j3.loads(rec.get("corpo_json") or "{}")
                except Exception:
                    dj = {}
                pd = getattr(self._sys, "payout", None)
                if pd is not None and dj.get("host_id") and int(dj.get("netto_host_cents", 0)) > 0:
                    pd.registra_maturato(rif, dj["host_id"], int(dj["netto_host_cents"]),
                                         dj.get("valuta", "EUR"))
                self._apri_garanzia(rif, int(dj.get("netto_host_cents", 0)),
                                    rec.get("alloggio_id", ""), rec.get("check_in", ""))
            # comune a 'in_attesa' e 'scaduto-ribloccato': segna pagato + tassa + payout maturato
            pp.conferma(rif)
            if rec.get("tassa_cents", 0) > 0:
                led = getattr(self._sys, "tassa_comunale", None)
                if led is not None:
                    led.registra_riscossione(rif, rec.get("comune", ""), rec["tassa_cents"])
            pd = getattr(self._sys, "payout", None)
            if pd is not None:
                pd.aggiorna_stato(rif, "maturato")        # in_attesa -> maturato (guadagno vero)
        except Exception:
            logger.warning("conferma pagamento/ledger tassa fallita (ignorata)", exc_info=True)

    def _mcp(self, body):
        if self._sys.mcp is None:
            return 503, {"errore": "mcp_disattivato"}
        out = self._sys.mcp.gestisci_raw(body or "")
        if out is None:
            return 204, {}
        try:
            return 200, json.loads(out)
        except (ValueError, TypeError):
            return 200, {"raw": out}

    # --- rotte host ---
    @staticmethod
    def _client_ip(headers):
        """IP reale dell'host dietro nginx (X-Forwarded-For ha priorita', primo hop)."""
        h = headers or {}
        xff = h.get("X-Forwarded-For") or h.get("x-forwarded-for") or ""
        if xff:
            return xff.split(",")[0].strip()[:64]
        return (h.get("X-Real-IP") or h.get("x-real-ip") or "")[:64]

    @staticmethod
    def _user_agent(headers):
        h = headers or {}
        return (h.get("User-Agent") or h.get("user-agent") or "")[:400]

    def _contratto_host(self, query):
        """Serve il testo VIVO del contratto host + versione + hash vincolante (per l'accettazione)."""
        try:
            from fase163_accettazioni import documento_corrente
            return 200, documento_corrente(_lingua(query))
        except Exception:
            logger.error("contratto host: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}

    def _host_accettazioni(self, query, headers):
        """Le prove d'accettazione dell'host (ognuna con flag `integra` = non manomessa)."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        acc = getattr(self._sys, "accettazioni", None)
        if acc is None:
            return 200, {"accettazioni": []}
        host_id = self._host_id_da_token(headers) or query.get("host_id")
        if not (isinstance(host_id, str) and host_id):
            return 422, {"errore": "host_id_mancante"}
        try:
            return 200, {"accettazioni": acc.elenco(host_id)}
        except Exception:
            logger.error("host accettazioni: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}

    def _host_registrazione(self, body, headers=None):
        """L'host crea il proprio account DA SOLO (self-service): niente onboarding manuale.
        Registra ANCHE la PROVA d'accettazione del contratto (versione+hash+IP+dispositivo+
        approvazione clausole vessatorie) nel registro firmato fase163 -> opponibile in causa."""
        headers = headers or {}
        reg = getattr(self._sys, "registro_host", None)
        if reg is None:
            return 503, {"errore": "registrazione_non_attiva"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        # ANTI-MANOMISSIONE: se il client dichiara l'hash del contratto letto, deve combaciare
        # con quello VIVO (altrimenti ha letto una versione diversa/vecchia -> 409, rileggi).
        hash_vivo, ver_viva = "", ""
        try:
            from fase163_accettazioni import doc_sha256 as _doc_hash, CONTRATTO_HOST_VERSIONE
            hash_vivo, ver_viva = _doc_hash(), CONTRATTO_HOST_VERSIONE
        except Exception:
            pass
        hash_client = dati.get("doc_sha256")
        if isinstance(hash_client, str) and hash_client and hash_vivo \
                and hash_client != hash_vivo:
            return 409, {"errore": "contratto_aggiornato",
                         "doc_sha256": hash_vivo, "versione": ver_viva}
        e = reg.registra(dati.get("email"), dati.get("password"),
                         accetta_termini=bool(dati.get("accetta_termini")),
                         ragione_sociale=str(dati.get("ragione_sociale", "")),
                         telefono=str(dati.get("telefono", "")),
                         line_token=str(dati.get("line_token", "")),
                         wechat_webhook=str(dati.get("wechat_webhook", "")))
        out = e.as_dict()
        # PROVA D'ACCETTAZIONE firmata (best-effort MA loggata: l'account e' gia' creato con
        # versione+ts nel registro host; qui aggiungiamo la prova forte hash+IP+dispositivo).
        if e.ok:
            acc = getattr(self._sys, "accettazioni", None)
            if acc is not None:
                try:
                    r = acc.registra(
                        e.host_id, lang=str(dati.get("lang", "it")),
                        ip=self._client_ip(headers),
                        user_agent=self._user_agent(headers),
                        vessatorie=bool(dati.get("accetta_clausole")))
                    out["accettazione"] = {"registrata": bool(r.get("ok")),
                                           "versione": r.get("versione"),
                                           "vessatorie": r.get("vessatorie")}
                except Exception:
                    logger.error("PROVA accettazione contratto FALLITA per host %s",
                                 getattr(e, "host_id", "?"), exc_info=True)
        # viral loop: se è arrivato con un codice referral, accredita referente+referee
        if e.ok:
            codice = dati.get("codice_referral")
            viral = getattr(self._sys, "viral", None)
            if viral is not None and isinstance(codice, str) and codice:
                try:
                    r = viral.registra_referee(codice, e.host_id)
                    out["referral"] = {"ok": r.ok,
                                       "credito_cents": r.credito_referee_cents if r.ok else 0}
                except Exception:
                    logger.warning("referral su registrazione fallito (ignorato)",
                                   exc_info=True)
        return (201 if e.ok else 422), out

    def _host_login(self, body):
        reg = getattr(self._sys, "registro_host", None)
        if reg is None:
            return 503, {"errore": "registrazione_non_attiva"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        e = reg.login(dati.get("email"), dati.get("password"))
        return (200 if e.ok else 401), e.as_dict()

    def _host_referral(self, query, headers):
        """Link di invito dell'host + credito disponibile (viral loop fase76)."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        viral = getattr(self._sys, "viral", None)
        if viral is None:
            return 503, {"errore": "viral_non_attivo"}
        host_id = self._host_id_da_token(headers) or query.get("host_id")
        if not (isinstance(host_id, str) and host_id):
            return 422, {"errore": "host_id_mancante"}
        try:
            codice = viral.genera_codice(host_id, tipo="host")
            credito = viral.credito_disponibile(host_id)
        except Exception:
            logger.error("host referral: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        if not codice:
            return 503, {"errore": "codice_non_generato"}
        from urllib.parse import quote
        link = (self._base_url or "https://bookinvip.com") + "/diventa-host.html?ref=" + quote(codice)
        return 200, {"codice": codice, "link": link, "credito_cents": int(credito)}

    def _prezzo_suggerito(self, query, headers):
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        import fase106_dynamic_pricing as dyn

        def _qi(k, d):
            try:
                return int(query.get(k, d))
            except (TypeError, ValueError):
                return d
        base = _qi("prezzo_base_cents", 0)
        if base <= 0:
            return 422, {"errore": "prezzo_base_non_valido"}
        return 200, dyn.calcola_prezzo(
            base, occupazione_bps=_qi("occupazione_bps", 5000),
            data=query.get("data", ""), giorni_all_arrivo=_qi("giorni", 30))

    def _host_invito(self, headers):
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        ref = getattr(self._sys, "referral", None)
        if ref is None:
            return 503, {"errore": "referral_non_attivo"}
        hid = self._host_id_da_token(headers) or "host"
        codice = ref.genera_codice(hid)
        if not codice:
            return 422, {"errore": "codice_non_generato"}
        from urllib.parse import quote
        link = (self._base_url or "https://bookinvip.com") + "/diventa-host.html?ref=" + quote(codice)
        return 200, {"codice": codice, "link": link, "crediti_cents": ref.crediti(hid)}

    def _host_invito_registra(self, body):
        ref = getattr(self._sys, "referral", None)
        if ref is None:
            return 503, {"errore": "referral_non_attivo"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        codice = dati.get("codice")
        nuovo = dati.get("nuovo_host_id")
        if not (isinstance(codice, str) and isinstance(nuovo, str)):
            return 422, {"errore": "campi_non_validi"}
        ok = ref.registra_referral(codice, nuovo)
        return (201, {"stato": "registrato"}) if ok else (409, {"errore": "non_registrabile"})

    def _host_invito_qualifica(self, body, headers):
        if not self._auth_admin(headers):
            return 401, {"errore": "unauthorized"}
        ref = getattr(self._sys, "referral", None)
        if ref is None:
            return 503, {"errore": "referral_non_attivo"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        nuovo = dati.get("nuovo_host_id")
        if not isinstance(nuovo, str):
            return 422, {"errore": "campi_non_validi"}
        bonus = ref.conferma_qualifica(nuovo)
        return 200, {"bonus_cents": bonus}

    def _msg_invia(self, body, headers):
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        msg = getattr(self._sys, "messaggistica", None)
        if msg is None:
            return 503, {"errore": "messaggistica_non_attiva"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        pren = dati.get("prenotazione_id")
        guest = dati.get("guest_id")
        testo = dati.get("testo")
        mittente = self._host_id_da_token(headers) or "host"
        if not (isinstance(pren, str) and isinstance(guest, str) and isinstance(testo, str)):
            return 422, {"errore": "campi_non_validi"}
        ok = msg.invia(pren, mittente, guest, mittente, testo)
        return (201, {"stato": "inviato"}) if ok else (422, {"errore": "non_inviato"})

    def _msg_thread(self, query, headers):
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        msg = getattr(self._sys, "messaggistica", None)
        if msg is None:
            return 503, {"errore": "messaggistica_non_attiva"}
        pren = query.get("prenotazione_id", "")
        richiedente = self._host_id_da_token(headers) or "host"
        return 200, {"messaggi": msg.thread(pren, richiedente)}

    def _host_pubblica(self, body, headers):
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        # se autenticato con token self-service, l'host pubblica SOLO sotto il proprio id
        hid = self._host_id_da_token(headers)
        if hid:
            dati = dict(dati)
            dati["host_id"] = hid
        from fase57_vetrina import Immagine, SchedaAlloggio, valida_scheda
        ok, codice, scheda = valida_scheda(dati)
        if not ok:
            return 422, {"errore": "scheda_non_valida", "dettaglio": codice}
        imgs = [Immagine(u, i) for i, u in enumerate(dati.get("immagini", []))
                if isinstance(u, str)]
        self._sys.catalogo.pubblica(scheda, imgs)
        return 201, {"stato": "pubblicato", "slug": scheda.slug}

    def _host_disponibilita(self, body, headers):
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        alloggio = dati.get("alloggio_id")
        giorno = dati.get("giorno")
        unita = dati.get("unita_totali")
        prezzo = dati.get("prezzo_netto_cents")
        if not (isinstance(alloggio, str) and isinstance(giorno, str)
                and isinstance(unita, int) and not isinstance(unita, bool)
                and isinstance(prezzo, int) and not isinstance(prezzo, bool)):
            return 422, {"errore": "campi_non_validi"}
        ok = self._sys.inventario.imposta_disponibilita(
            alloggio, giorno, unita_totali=unita, prezzo_netto_cents=prezzo,
            chiuso=bool(dati.get("chiuso", False)))
        return (200 if ok else 422), {"stato": "ok" if ok else "rifiutato"}

    def _host_disponibilita_range(self, body, headers):
        """Apre un INTERO periodo (onboarding): imposta unita+prezzo per ogni notte
        [da, a). Max 366 giorni."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        import datetime
        alloggio = dati.get("alloggio_id")
        da, a = dati.get("da"), dati.get("a")
        unita, prezzo = dati.get("unita_totali"), dati.get("prezzo_netto_cents")
        if not (isinstance(alloggio, str) and isinstance(da, str) and isinstance(a, str)
                and isinstance(unita, int) and not isinstance(unita, bool)
                and isinstance(prezzo, int) and not isinstance(prezzo, bool)):
            return 422, {"errore": "campi_non_validi"}
        try:
            d0 = datetime.date.fromisoformat(da)
            d1 = datetime.date.fromisoformat(a)
        except (ValueError, TypeError):
            return 422, {"errore": "date_non_valide"}
        n = (d1 - d0).days
        if n <= 0 or n > 366:
            return 422, {"errore": "intervallo_non_valido"}
        impostati = 0
        for i in range(n):
            g = (d0 + datetime.timedelta(days=i)).isoformat()
            if self._sys.inventario.imposta_disponibilita(
                    alloggio, g, unita_totali=unita, prezzo_netto_cents=prezzo):
                impostati += 1
        return 200, {"giorni_impostati": impostati}

    def _host_metriche(self, query, headers):
        """Dashboard host: revenue/occupazione (fase58) + prenotazioni + recensioni."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        alloggio = query.get("alloggio") or None
        da, a = query.get("da") or None, query.get("a") or None
        try:
            inv = self._sys.inventario.metriche(alloggio_id=alloggio, da=da, a=a)
            pren = self._sys.inventario.elenco_prenotazioni(alloggio_id=alloggio,
                                                            limit=500)
        except Exception:
            logger.error("host metriche: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        attive = sum(1 for p in pren if not p["rimborsato"])
        out = {
            "revenue_cents": inv["revenue_cents"],
            "occupazione_bps": inv["occupazione_bps"],
            "notti_occupate": inv["notti_occupate"],
            "notti_totali": inv["notti_totali"],
            "prenotazioni_attive": attive,
            "prenotazioni_rimborsate": len(pren) - attive,
            "valuta": self._valuta_sys(),
            "money_unit": "cents_integer",
        }
        rie = self._riepilogo_recensioni(alloggio) if alloggio else None
        if rie:
            out["recensioni"] = rie
        return 200, out

    def _valuta_sys(self) -> str:
        return getattr(getattr(self._sys, "config", None), "valuta", "EUR")

    def _revenue_prenotazione(self, p: Dict[str, Any]) -> int:
        if p.get("rimborsato"):
            return 0
        try:
            cal = self._sys.inventario.calendario(p.get("alloggio_id", ""),
                                                  p.get("check_in", ""),
                                                  p.get("check_out", ""))
            return sum(g.get("prezzo_netto_cents", 0) for g in cal
                       if isinstance(g.get("prezzo_netto_cents"), int))
        except Exception:
            return 0

    def _host_export(self, query, headers):
        """Export CSV delle prenotazioni (contabilita'). Il CSV viaggia come stringa nel
        JSON; il frontend lo scarica come file."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        alloggio = query.get("alloggio") or None
        try:
            righe = self._sys.inventario.elenco_prenotazioni(alloggio_id=alloggio,
                                                             limit=500)
        except Exception:
            logger.error("host export: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        for r in righe:
            r["revenue_cents"] = self._revenue_prenotazione(r)
        return 200, {"csv": genera_csv_prenotazioni(righe), "righe": len(righe)}

    def _host_link_diretto(self, query, headers):
        """Link di prenotazione DIRETTA dell'host (fonte=diretto -> 5%). Da condividere sui
        propri canali: le prenotazioni che arrivano da qui pagano solo il 5%, non il 10%."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        host_id = self._host_id_da_token(headers) or query.get("host_id")
        if not (isinstance(host_id, str) and host_id):
            return 422, {"errore": "host_id_mancante"}
        base = self._base_url or "https://bookinvip.com"
        try:
            el = self._sys.catalogo.alloggi_host(host_id, limit=200)
        except Exception:
            logger.error("host link diretto: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        from urllib.parse import quote
        alloggi = []
        for a in (el or []):
            slug = a.get("slug") if isinstance(a, dict) else None
            if slug:
                alloggi.append({
                    "slug": slug,
                    "titolo": (a.get("titolo") if isinstance(a, dict) else None) or slug,
                    "link": base + "/?fonte=diretto&apri=" + quote(slug)})
        return 200, {"link_generale": base + "/?fonte=diretto",
                     "alloggi": alloggi, "commissione_bps": 500, "commissione": "5%"}

    def _host_alloggi(self, query, headers):
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        host_id = query.get("host_id")
        if not (isinstance(host_id, str) and host_id):
            return 422, {"errore": "host_id_mancante"}
        try:
            el = self._sys.catalogo.alloggi_host(host_id, limit=200)
        except Exception:
            logger.error("host alloggi: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        return 200, {"alloggi": el}

    def _host_stato(self, body, headers):
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        slug, stato = dati.get("slug"), dati.get("stato")
        if not (isinstance(slug, str) and slug and isinstance(stato, str)):
            return 422, {"errore": "campi_non_validi"}
        ok = self._sys.catalogo.imposta_stato(slug, stato)
        return (200 if ok else 422), {"stato": stato if ok else "rifiutato"}

    def _host_calendario(self, query, headers):
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        alloggio = query.get("alloggio")
        da, a = query.get("da"), query.get("a")
        if not (isinstance(alloggio, str) and alloggio and isinstance(da, str)
                and isinstance(a, str)):
            return 422, {"errore": "campi_non_validi"}
        try:
            cal = self._sys.inventario.calendario(alloggio, da, a)
        except Exception:
            logger.error("host calendario: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        return 200, {"giorni": cal}

    def _host_ical(self, body, headers):
        """Importa il calendario iCal (Airbnb/Booking/Vrbo): blocca le date occupate
        sull'inventario (fase82). La vera portabilita' cross-canale."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        alloggio, ical = dati.get("alloggio_id"), dati.get("ical")
        if not (isinstance(alloggio, str) and alloggio and isinstance(ical, str)):
            return 422, {"errore": "campi_non_validi"}
        from fase82_ical_sync import sincronizza
        return 200, sincronizza(self._sys.inventario, alloggio, ical)


def crea_router(sistema: Any, *, host_key: Optional[str] = None,
                admin_key: Optional[str] = None, base_url: str = "") -> RouterHTTP:
    return RouterHTTP(sistema, host_key=host_key, admin_key=admin_key, base_url=base_url)


def percorso_statico_sicuro(path: str, cartella: str) -> Optional[str]:
    """Risolve un path statico DENTRO `cartella`, neutralizzando il path-traversal.
    Ritorna un percorso contenuto in `cartella`, o None (dotfile / fuori radice).
    PURO e testabile -> la difesa anti-`../`/`%00` e' un invariante, non uno slogan."""
    import os
    if not isinstance(path, str):
        return None
    nome = "index.html" if path in ("/", "") else path.lstrip("/")
    base = os.path.basename(nome)          # strip di ogni componente di directory
    if not base or base.startswith(".") or "\x00" in base:
        return None                         # niente dotfile (.env, .git...), niente NUL
    candidato = os.path.join(cartella, base)
    cart_real = os.path.realpath(cartella)
    cand_real = os.path.realpath(candidato)
    try:
        if os.path.commonpath([cart_real, cand_real]) != cart_real:
            return None                     # doppia cintura: mai fuori dalla radice
    except ValueError:
        return None
    return candidato


# ─────────────────────────────────────────────────────────────────────────────
# Server HTTP stdlib (thin wrapper, NON testato - I/O)
# ─────────────────────────────────────────────────────────────────────────────
def servi(sistema: Any, *, host: str = "127.0.0.1", porta: int = 8080,
          cartella_statica: str = "deploy", host_key: Optional[str] = None,
          base_url: str = "", admin_key: Optional[str] = None
          ) -> None:  # pragma: no cover
    import os
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import urlparse, parse_qs, unquote

    router = crea_router(sistema, host_key=host_key, admin_key=admin_key,
                         base_url=base_url)

    # --- Auto-pubblicazione campagna (GATED, default-off): parte solo se nel .env c'è
    #     CAMPAGNA_AUTO_GIORNI e il sistema ha un motore marketing. Isolato: se fallisce,
    #     il server parte lo stesso.
    _giorni = os.environ.get("CAMPAGNA_AUTO_GIORNI", "").strip()
    if _giorni and getattr(sistema, "marketing", None) is not None:
        try:
            from fase94_scheduler_campagna import crea_scheduler_campagna
            sched = crea_scheduler_campagna(
                sistema.marketing, percorso=os.environ.get(
                    "CAMPAGNA_STATO_FILE", ".campagna_stato.json"),
                cadenza_giorni=int(_giorni))
            sched.avvia_in_thread(intervallo_sec=3600.0)
            logging.getLogger("core_auto.server").info(
                "Scheduler campagna AVVIATO: ogni %s giorni", _giorni)
        except Exception:
            logging.getLogger("core_auto.server").warning(
                "Scheduler campagna NON avviato (ISOLATO)", exc_info=True)

    class Handler(BaseHTTPRequestHandler):
        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Host-Key")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

        def _scrivi(self, status, corpo):
            dati = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self._cors()
            self.end_headers()
            self.wfile.write(dati)

        def _serve_upload(self, path):
            updir = os.environ.get("UPLOAD_DIR", "data/uploads")
            fpath = percorso_statico_sicuro(path, updir)   # anti-traversal (basename only)
            if fpath is None or not os.path.isfile(fpath):
                self._scrivi(404, {"errore": "file_non_trovato"})
                return
            with open(fpath, "rb") as f:
                dati = f.read()
            import mimetypes
            ctype = mimetypes.guess_type(fpath)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "public, max-age=31536000")
            self._cors()
            self.end_headers()
            self.wfile.write(dati)

        def _statico(self, path):
            fpath = percorso_statico_sicuro(path, cartella_statica)
            if fpath is None or not os.path.isfile(fpath):
                self._scrivi(404, {"errore": "file_non_trovato"})
                return
            with open(fpath, "rb") as f:
                dati = f.read()
            import mimetypes
            ctype = mimetypes.guess_type(fpath)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/json",
                                                       "application/javascript",
                                                       "image/svg+xml"):
                ctype += "; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Service-Worker-Allowed", "/")
            self._cors()
            self.end_headers()
            self.wfile.write(dati)

        def _testo(self, status, ctype, testo):
            dati = testo.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self._cors()
            self.end_headers()
            self.wfile.write(dati)

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self):
            u = urlparse(self.path)
            if u.path.startswith("/api/"):
                query = {k: v[0] for k, v in parse_qs(u.query).items()}
                s, c = router.gestisci("GET", u.path, query, None, dict(self.headers))
                self._scrivi(s, c)
            elif u.path == "/sitemap.xml":
                self._testo(200, "application/xml", sitemap_xml(sistema, base_url))
            elif u.path == "/robots.txt":
                self._testo(200, "text/plain", robots_txt(base_url))
            elif u.path.startswith("/alloggio/"):
                slug = unquote(u.path[len("/alloggio/"):])
                html = pagina_alloggio_html(sistema, slug, base_url)
                if html is None:
                    self._scrivi(404, {"errore": "not_found"})
                else:
                    self._testo(200, "text/html", html)
            elif u.path.startswith("/voucher/"):
                query = {k: v[0] for k, v in parse_qs(u.query).items()}
                lng = query.get("lang", "it")
                html = pagina_voucher_html(sistema, unquote(u.path[len("/voucher/"):]), lng)
                if html is None:
                    self._scrivi(404, {"errore": "voucher_non_valido"})
                else:
                    self._testo(200, "text/html", html)
            elif u.path.startswith("/affitta/"):
                # Inbound SEO/AEO (fase97): landing host per città (server-rendered,
                # crawlabile). Solo città note → niente thin-content da slug arbitrari.
                try:
                    from fase97_inbound_seo import (CITTA_SEED, citta_da_slug,
                                                    genera_landing_host)
                    query = {k: v[0] for k, v in parse_qs(u.query).items()}
                    citta = citta_da_slug(unquote(u.path[len("/affitta/"):]))
                    if citta is None:
                        self._scrivi(404, {"errore": "citta_non_trovata"})
                    else:
                        bps = int(os.environ.get("COMMISSIONE_BPS", "1000"))
                        self._testo(200, "text/html", genera_landing_host(
                            citta, lingua=query.get("lang", "it"), base_url=base_url,
                            commissione_bps=bps, citta_correlate=CITTA_SEED[:8]))
                except Exception:
                    self._scrivi(500, {"errore": "interno"})
            elif u.path == "/llms.txt":
                from fase97_inbound_seo import llms_txt
                bps = int(os.environ.get("COMMISSIONE_BPS", "1000"))
                self._testo(200, "text/plain",
                            llms_txt(base_url, commissione_bps=bps))
            elif u.path == "/.well-known/ai-plugin.json":
                self._scrivi(200, ai_plugin_manifest(base_url))   # scoperta agenti IA
            elif u.path == "/openapi.json":
                self._scrivi(200, openapi_agent_spec(base_url))   # spec per agenti non-MCP
            elif u.path.startswith("/uploads/"):
                self._serve_upload(u.path)                        # foto alloggi caricate
            elif u.path == "/sitemap-host.xml":
                from fase97_inbound_seo import sitemap_inbound
                self._testo(200, "application/xml", sitemap_inbound(base_url))
            elif u.path == "/stop":
                # Disiscrizione PUBBLICA (link nelle email outreach). Nessuna auth: il
                # destinatario deve poter dire stop. Opt-out scritto in modo DUREVOLE.
                query = {k: v[0] for k, v in parse_qs(u.query).items()}
                email = (query.get("e") or query.get("email") or "").strip()
                fatto = False
                try:
                    from fase95_outreach_email import StoreOptOut
                    StoreOptOut(os.environ.get("OUTREACH_OPTOUT_FILE",
                                               ".outreach_optout.json")).aggiungi(email)
                    fatto = bool(email)
                except Exception:
                    logging.getLogger("core_auto.server").warning(
                        "opt-out /stop fallito (ISOLATO)", exc_info=True)
                msg = ("✅ Disiscritto. Non riceverai più nostre email." if fatto
                       else "Indirizzo email mancante o non valido.")
                self._testo(200, "text/html",
                            "<!doctype html><meta charset=utf-8><title>BookinVIP</title>"
                            "<body style='font-family:system-ui;max-width:32rem;margin:4rem "
                            "auto;text-align:center'><h1>BookinVIP</h1><p style='font-size:"
                            "1.1rem'>%s</p></body>" % msg)
            else:
                self._statico(u.path)

        def do_POST(self):
            u = urlparse(self.path)
            lung = int(self.headers.get("Content-Length", 0) or 0)
            body = self.rfile.read(lung).decode("utf-8") if lung else ""
            s, c = router.gestisci("POST", u.path, {}, body, dict(self.headers))
            self._scrivi(s, c)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer((host, porta), Handler)
    logger.info("BookinVIP server su http://%s:%d", host, porta)

    # auto-rilascio escrow: ogni ora sblocca le garanzie con finestra post check-in scaduta
    gz = getattr(sistema, "garanzia", None)
    if gz is not None and hasattr(gz, "auto_rilascia"):
        import threading as _th

        def _tick_garanzia():
            while True:
                try:
                    gz.auto_rilascia()
                except Exception:
                    logger.warning("auto_rilascia garanzia fallito (ignorato)", exc_info=True)
                __import__("time").sleep(3600)
        _th.Thread(target=_tick_garanzia, daemon=True).start()

    # sweeper HOLD: libera le stanze delle prenotazioni non pagate entro la scadenza
    pp = getattr(sistema, "pagamenti_pendenti", None)
    inv = getattr(sistema, "inventario", None)
    if pp is not None and inv is not None:
        import threading as _th2

        def _tick_hold():
            while True:
                try:
                    for rec in pp.scaduti():
                        try:
                            inv.rilascia(rec["alloggio_id"], rec["check_in"], rec["check_out"],
                                         idem_key=(rec.get("idem_key") or ("hold_" + rec["riferimento"])))
                            if gz is not None:
                                gz.annulla(rec["riferimento"])
                            # non pagato entro i 2 min -> via il payout 'in_attesa' (niente guadagno
                            # fantasma) + libera le date. NON cancello il record: lo marco 'scaduto'
                            # per gestire un eventuale pagamento tardivo (re-blocco/rimborso).
                            _pd = getattr(sistema, "payout", None)
                            if _pd is not None:
                                _pd.rimuovi(rec["riferimento"])
                            pp.scadi(rec["riferimento"])
                        except Exception:
                            logger.warning("sweep hold singolo fallito (ignorato)", exc_info=True)
                    try:
                        pp.pulisci_vecchi()      # housekeeping: via i record scaduti vecchi (>1h)
                    except Exception:
                        pass
                except Exception:
                    logger.warning("sweep hold fallito (ignorato)", exc_info=True)
                __import__("time").sleep(120)
        _th2.Thread(target=_tick_hold, daemon=True).start()

    srv.serve_forever()
