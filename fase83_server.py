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
import re
from typing import Any, Dict, List, Optional, Tuple

from fase61_localizzazione import Localizzatore, LINGUE_SUPPORTATE

logger = logging.getLogger("core_auto.server")

# La FORMA di un riferimento di prenotazione. MISURATA, non supposta: su 300 riferimenti
# generati dal vero (`fase59:547`, `idem[:24]` della firma) l'esito e' sempre
# `hmac-sha256:e9a39409f6d8` -- 24 caratteri, alfabeto `[0-9a-f:-]`. Qui si accetta un po'
# piu' largo perche' altre strade usano prefissi (`reblock:`, `cancel_`), ma MAI spazi,
# a-capo o byte di controllo: e' quello il punto.
_RIFERIMENTO_VALIDO = re.compile(r"\A[A-Za-z0-9:_.-]{1,64}\Z")


def _rif_per_registro(rif: Any) -> str:
    """Rende un riferimento SICURO da scrivere nel registro -- sempre, chiunque lo passi.

    ⛔ NON e' un doppione del controllo al confine: quello dice cosa ACCETTIAMO, questo dice
    cosa SCRIVIAMO. Il primo mette in sicurezza una rotta; il secondo mette in sicurezza il
    REGISTRO, anche il giorno in cui nascera' un secondo chiamante che non convalida niente --
    e quel giorno nessuno tocchera' questa funzione, quindi nessuno si accorgera' che la
    garanzia e' caduta (D19: una difesa non deve dipendere dal comportamento di un altro).

    Perche' vale la pena: il registro e' dove il Guardiano (fase186) guarda ogni giorno per
    sapere se un guasto sui soldi e' avvenuto. Una riga FABBRICATA li' dentro non e' un
    difetto qualunque: e' un difetto nello strumento con cui si vedono i difetti."""
    pulito = re.sub(r"[^A-Za-z0-9:_.-]", "", str(rif))[:64]
    # ⛔ RIDONDANTE PER IL PRODOTTO, NECESSARIA PER CHI SORVEGLIA -- e non e' un vezzo.
    # La `re.sub` qui sopra ha gia' tolto tutto cio' che non e' lettera, cifra o uno dei
    # quattro segni ammessi: gli a-capo, in tutte e dieci le loro forme, sono gia' spariti.
    # Ma CodeQL riconosce UNA SOLA forma di barriera -- `ReplaceLineBreaksSanitizer`, in
    # `LogInjectionCustomizations.qll` del repository `github/codeql`: una `.replace(...)`
    # col primo argomento uguale a "\n" o "\r\n". Senza quella forma l'analisi vede il
    # veleno attraversare una difesa che funziona: misurato il 2026-08-18, la richiesta #66
    # e' tornata ROSSA (10 allarmi) sul file GIA' riparato, stessa impronta `8a28c8f`.
    # ⛔ La `re.sub` NON si toglie per tenere solo questa: la prima e' la difesa vera (un
    # elenco di cio' che si AMMETTE, il piu' severo dei due), la seconda e' la sua
    # dimostrazione all'analizzatore. Una difesa ha due destinatari: il programma, che deve
    # restare sano, e lo strumento che sorveglia, che deve poterlo vedere.
    # Guardie: `TestLaPuliziaDelRegistroDEVEESSEREVISIBILEACHIANALIZZA` (test_pipeline_ci).
    pulito = pulito.replace("\r\n", "").replace("\n", "")
    return pulito or "riferimento_vuoto_o_illeggibile"


# Stringhe UI per il frontend (chrome), multilingua. Fallback -> 'en' -> chiave.
ETICHETTE_UI: Dict[str, Dict[str, str]] = {
    # --- ricerca / risultati ---
    "flex": {"it": "Date flessibili (± 3 giorni)", "en": "Flexible dates (± 3 days)", "es": "Fechas flexibles (± 3 días)", "fr": "Dates flexibles (± 3 jours)", "de": "Flexible Daten (± 3 Tage)", "pt": "Datas flexíveis (± 3 dias)", "ja": "柔軟な日付（±3日）", "zh": "灵活日期（±3天）"},
    "b1": {"it": "Siamo in fase di test e costruzione — apriamo a breve.", "en": "We are in test & build phase — opening soon.", "es": "Estamos en fase de prueba y construcción — abrimos pronto.", "fr": "Nous sommes en phase de test et construction — ouverture bientôt.", "de": "Wir sind in der Test- und Aufbauphase — bald geöffnet.", "pt": "Estamos em fase de teste e construção — abrimos em breve.", "ja": "現在テスト・構築中です — まもなくオープン。", "zh": "我们正在测试和建设中 — 即将开放。"},
    "b2": {"it": "Stiamo preparando un servizio più avanzato e più conveniente per te. Nel frattempo è già aperto agli host:", "en": "We are preparing a more advanced and cheaper service for you. Meanwhile it is already open to hosts:", "es": "Preparamos un servicio más avanzado y económico para ti. Mientras tanto ya está abierto a anfitriones:", "fr": "Nous préparons un service plus avancé et plus économique. En attendant, c’est déjà ouvert aux hôtes :", "de": "Wir bereiten einen fortschrittlicheren und günstigeren Service vor. Für Gastgeber ist schon offen:", "pt": "Estamos a preparar um serviço mais avançado e económico. Entretanto já está aberto a anfitriões:", "ja": "より高度でお得なサービスを準備中です。ホストの皆様は既にご利用いただけます：", "zh": "我们正在为您打造更先进、更实惠的服务。房东现已可以入驻："},
    "b3": {"it": "pubblica il tuo alloggio ora →", "en": "publish your place now →", "es": "publica tu alojamiento ahora →", "fr": "publiez votre logement maintenant →", "de": "jetzt Unterkunft einstellen →", "pt": "publique o seu alojamento agora →", "ja": "今すぐ宿を掲載 →", "zh": "立即发布您的房源 →"},
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
        "regola_garanzia": {"it": "L'host viene pagato solo DOPO il tuo soggiorno. Hai 24 ore dal check-in per segnalare un problema: passate le 24h senza segnalazioni, il soggiorno è considerato regolare e l'host viene pagato.", "en": "The host is paid only AFTER your stay. You have 24 hours from check-in to report a problem: after 24h with no report, the stay is considered fine and the host is paid.", "es": "El anfitrión cobra solo DESPUÉS de tu estancia. Tienes 24 horas desde el check-in para reportar un problema: pasadas las 24h sin avisos, la estancia se considera correcta y el anfitrión cobra.", "fr": "L'hôte n'est payé qu'APRÈS votre séjour. Vous avez 24 heures après l'arrivée pour signaler un problème : passé ce délai sans signalement, le séjour est considéré conforme et l'hôte est payé.", "de": "Der Gastgeber wird erst NACH deinem Aufenthalt bezahlt. Du hast 24 Stunden ab Check-in, um ein Problem zu melden: danach ohne Meldung gilt der Aufenthalt als in Ordnung und der Gastgeber wird bezahlt.", "pt": "O anfitrião só recebe DEPOIS da tua estadia. Tens 24 horas após o check-in para relatar um problema: passadas 24h sem aviso, a estadia é considerada correta e o anfitrião recebe.", "ja": "ホストへの支払いは滞在後のみ。チェックインから24時間以内に問題を報告できます。報告がなければ滞在は正常とみなされ、ホストに支払われます。", "zh": "房东只在您入住之后才收款。您有24小时（自入住起）报告问题：24小时内无报告，则视为一切正常，房东收款。"},
        "regola_accetto": {"it": "Prenotando accetti i Termini, la politica di cancellazione mostrata sopra e le regole del soggiorno.", "en": "By booking you accept the Terms, the cancellation policy shown above and the stay rules.", "es": "Al reservar aceptas los Términos, la política de cancelación mostrada arriba y las reglas de la estancia.", "fr": "En réservant, vous acceptez les Conditions, la politique d'annulation indiquée ci-dessus et les règles du séjour.", "de": "Mit der Buchung akzeptierst du die AGB, die oben gezeigte Stornierungsrichtlinie und die Aufenthaltsregeln.", "pt": "Ao reservar aceitas os Termos, a política de cancelamento acima e as regras da estadia.", "ja": "予約すると、利用規約・上記のキャンセルポリシー・滞在ルールに同意したものとみなされます。", "zh": "预订即表示您接受条款、上方的取消政策及入住规则。"},
        "regola_termini_link": {"it": "Termini", "en": "Terms", "es": "Términos", "fr": "Conditions", "de": "AGB", "pt": "Termos", "ja": "利用規約", "zh": "条款"},
        "host_mete": {"it": "🏠 Diventa host nelle mete più richieste", "en": "🏠 Become a host in the top destinations", "es": "🏠 Conviértete en anfitrión en los destinos top", "fr": "🏠 Devenez hôte dans les destinations phares", "de": "🏠 Werde Gastgeber in den Top-Reisezielen", "pt": "🏠 Torne-se anfitrião nos destinos mais procurados", "ja": "🏠 人気の観光地でホストになろう", "zh": "🏠 成为热门目的地的房东"},
    "non_disp": {"it": "Non disponibile", "en": "Not available", "es": "No disponible", "fr": "Indisponible", "de": "Nicht verfügbar", "pt": "Indisponível", "ja": "空きなし", "zh": "不可预订"},
    "verificata": {"it": "verificata", "en": "verified", "es": "verificada", "fr": "vérifiée", "de": "verifiziert", "pt": "verificada", "ja": "確認済み", "zh": "已验证"},
    "dividi_amici": {"it": "Dividi tra amici:", "en": "Split with friends:", "es": "Divide con amigos:", "fr": "Partager entre amis :", "de": "Mit Freunden teilen:", "pt": "Dividir com amigos:", "ja": "友達と割り勘：", "zh": "与好友分摊："},
    "a_testa": {"it": "a testa", "en": "each", "es": "por persona", "fr": "par personne", "de": "pro Person", "pt": "por pessoa", "ja": "1人あたり", "zh": "每人"},
    "invia_preventivo": {"it": "Inviami il preventivo via email", "en": "Email me this quote", "es": "Envíame el presupuesto por correo", "fr": "Recevoir ce devis par e-mail", "de": "Angebot per E-Mail senden", "pt": "Enviar orçamento por e-mail", "ja": "見積もりをメールで受け取る", "zh": "把报价发送到我的邮箱"},
    "prev_inviato": {"it": "Preventivo inviato! Controlla la posta", "en": "Quote sent! Check your inbox", "es": "¡Presupuesto enviado! Revisa tu correo", "fr": "Devis envoyé ! Vérifiez vos e-mails", "de": "Angebot gesendet! Prüfe dein Postfach", "pt": "Orçamento enviado! Verifique seu e-mail", "ja": "送信しました！メールをご確認ください", "zh": "已发送！请查收邮件"},
    "prev_errore": {"it": "Invio non riuscito, riprova", "en": "Sending failed, try again", "es": "Error de envío, reintenta", "fr": "Échec de l'envoi, réessayez", "de": "Senden fehlgeschlagen, bitte erneut versuchen", "pt": "Falha no envio, tente novamente", "ja": "送信に失敗しました。もう一度お試しください", "zh": "发送失败，请重试"},
    "indicativo": {"it": "indicativo · la tua banca applica il suo cambio", "en": "approx. · your bank applies its own rate", "es": "aprox. · tu banco aplica su cambio", "fr": "indicatif · votre banque applique son taux", "de": "ca. · deine Bank nutzt ihren Kurs", "pt": "aprox. · seu banco aplica o câmbio dele", "ja": "目安 · 実際のレートは銀行によります", "zh": "约 · 以银行汇率为准"},
    "ota_pre": {"it": "Su un OTA pagheresti ~", "en": "On an OTA you'd pay ~", "es": "En una OTA pagarías ~", "fr": "Sur une OTA vous paieriez ~", "de": "Bei einem OTA zahltest du ~", "pt": "Numa OTA você pagaria ~", "ja": "OTAなら約", "zh": "在OTA上你要付约"},
    "risparmi": {"it": "risparmi", "en": "you save", "es": "ahorras", "fr": "vous économisez", "de": "du sparst", "pt": "você economiza", "ja": "お得", "zh": "省下"},
    # --- hero / slogan ---
    "hero_titolo": {"it": "Il tuo viaggio,", "en": "Your trip,", "es": "Tu viaje,", "fr": "Votre voyage,", "de": "Deine Reise,", "pt": "Sua viagem,", "ja": "あなたの旅は、", "zh": "你的旅行，"},
    "hero_titolo2": {"it": "senza sorprese.", "en": "no surprises.", "es": "sin sorpresas.", "fr": "sans surprises.", "de": "ohne Überraschungen.", "pt": "sem surpresas.", "ja": "サプライズなし。", "zh": "没有意外。"},
    "hero_sub": {"it": "Alloggi certificati · paghi il prezzo pulito · cancellazione gratuita", "en": "Certified stays · pay the clean price · free cancellation", "es": "Alojamientos certificados · pagas el precio limpio · cancelación gratuita", "fr": "Logements certifiés · payez le prix net · annulation gratuite", "de": "Zertifizierte Unterkünfte · fairer Endpreis · kostenlose Stornierung", "pt": "Acomodações certificadas · pague o preço limpo · cancelamento grátis", "ja": "認証済みの宿泊施設 · 追加料金なしの価格 · 無料キャンセル", "zh": "认证住宿 · 支付透明价格 · 免费取消"},
    "badge_commissioni": {"it": "0% commissioni all'ospite", "en": "0% guest fees", "es": "0% comisiones al huésped", "fr": "0% de frais pour le voyageur", "de": "0% Gästegebühren", "pt": "0% de taxas para o hóspede", "ja": "ゲスト手数料0%", "zh": "房客0手续费"},
    "badge_cancellazione": {"it": "Cancellazione gratuita", "en": "Free cancellation", "es": "Cancelación gratuita", "fr": "Annulation gratuite", "de": "Kostenlose Stornierung", "pt": "Cancelamento grátis", "ja": "無料キャンセル", "zh": "免费取消"},
    "badge_pagamenti": {"it": "Pagamenti sicuri", "en": "Secure payments", "es": "Pagos seguros", "fr": "Paiements sécurisés", "de": "Sichere Zahlungen", "pt": "Pagamentos seguros", "ja": "安全な決済", "zh": "安全支付"},
    "badge_antirimpianto": {"it": "Anti-Rimpianto: i soldi tornano come credito", "en": "Regret-free: money back as credit", "es": "Sin arrepentimiento: dinero de vuelta como crédito", "fr": "Sans regret : argent rendu en crédit", "de": "Ohne Reue: Geld zurück als Guthaben", "pt": "Sem arrependimento: dinheiro de volta como crédito", "ja": "後悔なし：返金はクレジットで", "zh": "无悔保障：退款以积分返还"},
    "footer_slogan": {"it": "zero commissioni nascoste", "en": "zero hidden fees", "es": "cero comisiones ocultas", "fr": "zéro frais cachés", "de": "keine versteckten Gebühren", "pt": "zero taxas ocultas", "ja": "隠れた手数料はゼロ", "zh": "零隐藏费用"},
    # --- barra dei MOTORI (verticali della stessa macchina) ---
    "hero_claim": {"it": "Una sola macchina, tanti modi di trovare casa", "en": "One engine, many ways to find a home", "es": "Un solo motor, muchas formas de encontrar casa", "fr": "Un seul moteur, plusieurs façons de trouver un logement", "de": "Eine Maschine, viele Wege zur passenden Unterkunft", "pt": "Um só motor, muitas formas de encontrar casa", "ja": "ひとつのエンジンで、住まい探しをいろいろな形で", "zh": "一个引擎，多种找房方式"},
    "m_soggiorni": {"it": "Soggiorni", "en": "Stays", "es": "Estancias", "fr": "Séjours", "de": "Aufenthalte", "pt": "Estadias", "ja": "宿泊", "zh": "住宿"},
    "m_soggiorni_s": {"it": "a notte", "en": "per night", "es": "por noche", "fr": "par nuit", "de": "pro Nacht", "pt": "por noite", "ja": "1泊単位", "zh": "按夜"},
    "m_affitti": {"it": "Affitti brevi", "en": "Short lets", "es": "Alquileres cortos", "fr": "Locations courtes", "de": "Kurzzeitmiete", "pt": "Aluguéis curtos", "ja": "短期賃貸", "zh": "短租"},
    "m_affitti_s": {"it": "1–3 mesi", "en": "1–3 months", "es": "1–3 meses", "fr": "1–3 mois", "de": "1–3 Monate", "pt": "1–3 meses", "ja": "1〜3か月", "zh": "1–3个月"},
    "m_ville": {"it": "Ville VIP", "en": "VIP Villas", "es": "Villas VIP", "fr": "Villas VIP", "de": "VIP-Villen", "pt": "Villas VIP", "ja": "VIPヴィラ", "zh": "VIP别墅"},
    "m_ville_s": {"it": "di pregio", "en": "premium", "es": "de lujo", "fr": "de prestige", "de": "exklusiv", "pt": "de luxo", "ja": "高級", "zh": "高端"},
    "m_business": {"it": "Business", "en": "Business", "es": "Business", "fr": "Business", "de": "Business", "pt": "Business", "ja": "ビジネス", "zh": "商务"},
    "m_business_s": {"it": "trasferte", "en": "work trips", "es": "viajes de trabajo", "fr": "voyages d'affaires", "de": "Geschäftsreisen", "pt": "viagens de trabalho", "ja": "出張", "zh": "商务出行"},
    "motore_presto": {"it": "Presto disponibile", "en": "Coming soon", "es": "Próximamente", "fr": "Bientôt disponible", "de": "Bald verfügbar", "pt": "Em breve", "ja": "近日公開", "zh": "即将上线"},
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
    "ps_anticipo_pagato": {"it": "Pagato online (anticipo)", "en": "Paid online (deposit)", "es": "Pagado online (anticipo)", "fr": "Payé en ligne (acompte)", "de": "Online bezahlt (Anzahlung)", "pt": "Pago online (adiantamento)", "ja": "オンライン決済済み（前金）", "zh": "已在线支付（订金）"},
    "ps_saldo_nota": {"it": "Saldo da pagare in struttura all'arrivo:", "en": "Balance to pay at the property on arrival:", "es": "Saldo a pagar en el alojamiento a la llegada:", "fr": "Solde à payer sur place à l'arrivée :", "de": "Restbetrag bei Ankunft vor Ort zu zahlen:", "pt": "Saldo a pagar no alojamento à chegada:", "ja": "到着時に現地でお支払いいただく残額：", "zh": "抵达时在住处支付的余款："},
    "rif": {"it": "Riferimento", "en": "Reference", "es": "Referencia", "fr": "Référence", "de": "Referenz", "pt": "Referência", "ja": "予約番号", "zh": "参考号"},
    "dal": {"it": "Dal", "en": "From", "es": "Desde", "fr": "Du", "de": "Von", "pt": "De", "ja": "から", "zh": "从"},
    "al": {"it": "Al", "en": "To", "es": "Hasta", "fr": "Au", "de": "Bis", "pt": "Até", "ja": "まで", "zh": "至"},
    "self_pass": {"it": "Check-in autonomo: mostra questo codice alla serratura", "en": "Self check-in: show this code at the lock", "es": "Auto check-in: muestra este código en la cerradura", "fr": "Auto check-in : montrez ce code à la serrure", "de": "Self-Check-in: diesen Code am Schloss zeigen", "pt": "Check-in autónomo: mostre este código na fechadura", "ja": "セルフチェックイン：このコードを鍵に提示してください", "zh": "自助入住：向门锁出示此代码"},
    # --- lista d'attesa (messaggio server) + link post-prenotazione ---
    "wl_dest_generica": {"it": "questa destinazione", "en": "this destination", "es": "este destino", "fr": "cette destination", "de": "dieses Ziel", "pt": "este destino", "ja": "ご希望の目的地", "zh": "该目的地"},
    "wl_msg_tpl": {"it": "Ti avvisiamo appena ci sono alloggi a %s. Hai un Credito Fondatore per la tua prima prenotazione.", "en": "We'll notify you as soon as stays are available in %s. You have a Founder Credit for your first booking.", "es": "Te avisaremos en cuanto haya alojamientos en %s. Tienes un Crédito Fundador para tu primera reserva.", "fr": "Nous vous préviendrons dès que des logements seront disponibles à %s. Vous avez un Crédit Fondateur pour votre première réservation.", "de": "Wir benachrichtigen dich, sobald in %s Unterkünfte verfügbar sind. Du hast ein Gründerguthaben für deine erste Buchung.", "pt": "Avisamos assim que houver acomodações em %s. Você tem um Crédito Fundador para a sua primeira reserva.", "ja": "%sに宿泊施設が用意でき次第お知らせします。初回予約に使える創設者クレジットをご利用いただけます。", "zh": "一旦%s有房源，我们会立即通知您。您可享创始人礼遇积分用于首次预订。"},
    "contratto_pdf": {"it": "Contratto PDF", "en": "PDF contract", "es": "Contrato PDF", "fr": "Contrat PDF", "de": "PDF-Vertrag", "pt": "Contrato PDF", "ja": "契約書（PDF）", "zh": "合同PDF"},
    "voucher_label": {"it": "Voucher", "en": "Voucher", "es": "Voucher", "fr": "Bon", "de": "Voucher", "pt": "Voucher", "ja": "バウチャー", "zh": "预订凭证"},
    # --- recensioni stile Booking/Agoda (voto generale + sotto-voti) ---
    "rec_titolo": {"it": "Com'è andata? Lascia una recensione", "en": "How was your stay? Leave a review", "es": "¿Qué tal tu estancia? Deja una reseña", "fr": "Comment était votre séjour ? Laissez un avis", "de": "Wie war Ihr Aufenthalt? Bewertung abgeben", "pt": "Como foi a estadia? Deixe uma avaliação", "ja": "ご滞在はいかがでしたか？レビューを書く", "zh": "住得怎么样？留下点评"},
    "rec_generale": {"it": "Voto generale", "en": "Overall rating", "es": "Valoración general", "fr": "Note globale", "de": "Gesamtbewertung", "pt": "Avaliação geral", "ja": "総合評価", "zh": "总体评分"},
    "rec_pulizia": {"it": "Pulizia", "en": "Cleanliness", "es": "Limpieza", "fr": "Propreté", "de": "Sauberkeit", "pt": "Limpeza", "ja": "清潔さ", "zh": "清洁度"},
    "rec_comfort": {"it": "Comfort", "en": "Comfort", "es": "Confort", "fr": "Confort", "de": "Komfort", "pt": "Conforto", "ja": "快適さ", "zh": "舒适度"},
    "rec_posizione": {"it": "Posizione", "en": "Location", "es": "Ubicación", "fr": "Emplacement", "de": "Lage", "pt": "Localização", "ja": "ロケーション", "zh": "位置"},
    "rec_servizi": {"it": "Servizi", "en": "Facilities", "es": "Servicios", "fr": "Équipements", "de": "Ausstattung", "pt": "Comodidades", "ja": "設備", "zh": "设施"},
    "rec_host": {"it": "Host", "en": "Host", "es": "Anfitrión", "fr": "Hôte", "de": "Gastgeber", "pt": "Anfitrião", "ja": "ホスト", "zh": "房东"},
    "rec_qualita_prezzo": {"it": "Qualità/prezzo", "en": "Value for money", "es": "Calidad/precio", "fr": "Rapport qualité-prix", "de": "Preis-Leistung", "pt": "Custo-benefício", "ja": "コスパ", "zh": "性价比"},
    "rec_testo_ph": {"it": "Racconta com'è andata (facoltativo)", "en": "Tell us how it went (optional)", "es": "Cuéntanos qué tal (opcional)", "fr": "Racontez votre séjour (facultatif)", "de": "Erzählen Sie davon (optional)", "pt": "Conte como foi (opcional)", "ja": "感想をどうぞ（任意）", "zh": "说说体验（选填）"},
    "rec_invia": {"it": "Invia recensione", "en": "Submit review", "es": "Enviar reseña", "fr": "Envoyer votre avis", "de": "Bewertung senden", "pt": "Enviar avaliação", "ja": "レビューを送信", "zh": "提交点评"},
    "rec_grazie": {"it": "Grazie! La tua recensione verificata è pubblicata.", "en": "Thank you! Your verified review is published.", "es": "¡Gracias! Tu reseña verificada está publicada.", "fr": "Merci ! Votre avis vérifié est publié.", "de": "Danke! Ihre verifizierte Bewertung ist online.", "pt": "Obrigado! A sua avaliação verificada foi publicada.", "ja": "ありがとうございます！認証済みレビューを公開しました。", "zh": "谢谢！您的验证点评已发布。"},
    "rec_nuovo": {"it": "Nuovo", "en": "New", "es": "Nuevo", "fr": "Nouveau", "de": "Neu", "pt": "Novo", "ja": "新着", "zh": "新上线"},
    # --- pagina VOUCHER (server-rendered): era l'ultimo pezzo di macchina rimasto in
    #     italiano fisso. E' il documento che l'ospite straniero apre e mostra al
    #     check-in: bottoni, avvisi e istruzioni devono parlare la SUA lingua.
    "v_pin_label": {"it": "PIN check-in", "en": "Check-in PIN", "es": "PIN de entrada", "fr": "PIN d'arrivée", "de": "Check-in-PIN", "pt": "PIN de check-in", "ja": "チェックインPIN", "zh": "入住 PIN"},
    "v_cancella": {"it": "Cancella prenotazione", "en": "Cancel booking", "es": "Anular reserva", "fr": "Annuler la réservation", "de": "Buchung stornieren", "pt": "Cancelar reserva", "ja": "予約をキャンセル", "zh": "取消预订"},
    "v_dopo_checkin": {"it": "Dopo il check-in:", "en": "After check-in:", "es": "Después de la entrada:", "fr": "Après l'arrivée :", "de": "Nach dem Check-in:", "pt": "Depois do check-in:", "ja": "チェックイン後：", "zh": "入住之后："},
    "v_tutto_ok": {"it": "Confermo: tutto come descritto", "en": "I confirm: everything as described", "es": "Confirmo: todo como se describe", "fr": "Je confirme : tout est conforme", "de": "Ich bestätige: alles wie beschrieben", "pt": "Confirmo: tudo como descrito", "ja": "確認しました：記載どおりです", "zh": "我确认：与描述一致"},
    "v_segnala_problema": {"it": "Segnala un problema", "en": "Report a problem", "es": "Informar de un problema", "fr": "Signaler un problème", "de": "Problem melden", "pt": "Comunicar um problema", "ja": "問題を報告", "zh": "报告问题"},
    "v_chat_intro": {"it": "Chatta con l'host (per domande o per chiarire un problema; puoi allegare FOTO come prova)", "en": "Chat with the host (for questions or to clear up a problem; you can attach PHOTOS as evidence)", "es": "Chatea con el anfitrión (para dudas o para aclarar un problema; puedes adjuntar FOTOS como prueba)", "fr": "Discutez avec l'hôte (pour des questions ou pour clarifier un problème ; vous pouvez joindre des PHOTOS comme preuve)", "de": "Chatten Sie mit dem Gastgeber (für Fragen oder zur Klärung eines Problems; Sie können FOTOS als Nachweis anhängen)", "pt": "Converse com o anfitrião (para dúvidas ou para esclarecer um problema; podes anexar FOTOS como prova)", "ja": "ホストとチャット（ご質問や問題の確認に。証拠として写真を添付できます）", "zh": "与房东聊天（咨询或说明问题；可附上照片作为凭证）"},
    "v_scrivi_ph": {"it": "Scrivi un messaggio...", "en": "Write a message...", "es": "Escribe un mensaje...", "fr": "Écrivez un message...", "de": "Nachricht schreiben...", "pt": "Escreve uma mensagem...", "ja": "メッセージを入力...", "zh": "写一条消息..."},
    "v_invia": {"it": "Invia", "en": "Send", "es": "Enviar", "fr": "Envoyer", "de": "Senden", "pt": "Enviar", "ja": "送信", "zh": "发送"},
    "v_foto_prova": {"it": "Foto prova", "en": "Photo evidence", "es": "Foto de prueba", "fr": "Photo preuve", "de": "Beweisfoto", "pt": "Foto de prova", "ja": "証拠写真", "zh": "凭证照片"},
    "v_checkin_online": {"it": "Check-in online (prima dell'arrivo): registra gli ospiti", "en": "Online check-in (before arrival): register the guests", "es": "Check-in online (antes de llegar): registra a los huéspedes", "fr": "Enregistrement en ligne (avant l'arrivée) : enregistrez les voyageurs", "de": "Online-Check-in (vor der Anreise): Gäste registrieren", "pt": "Check-in online (antes da chegada): regista os hóspedes", "ja": "オンラインチェックイン（到着前）：宿泊者を登録", "zh": "在线登记（抵达前）：登记入住人"},
    "v_nome_ph": {"it": "Nome e cognome", "en": "First and last name", "es": "Nombre y apellidos", "fr": "Nom et prénom", "de": "Vor- und Nachname", "pt": "Nome e apelido", "ja": "氏名", "zh": "姓名"},
    "v_doc_ph": {"it": "Numero documento", "en": "ID document number", "es": "Número de documento", "fr": "Numéro de pièce d'identité", "de": "Ausweisnummer", "pt": "Número do documento", "ja": "身分証番号", "zh": "证件号码"},
    "v_aggiungi": {"it": "+ Aggiungi", "en": "+ Add", "es": "+ Añadir", "fr": "+ Ajouter", "de": "+ Hinzufügen", "pt": "+ Adicionar", "ja": "＋ 追加", "zh": "＋ 添加"},
    "v_invia_checkin": {"it": "Invia check-in", "en": "Send check-in", "es": "Enviar check-in", "fr": "Envoyer l'enregistrement", "de": "Check-in senden", "pt": "Enviar check-in", "ja": "チェックインを送信", "zh": "提交登记"},
    "v_ricevuta": {"it": "Ricevuta di pagamento", "en": "Payment receipt", "es": "Recibo de pago", "fr": "Reçu de paiement", "de": "Zahlungsbeleg", "pt": "Recibo de pagamento", "ja": "支払い領収書", "zh": "付款收据"},
    "v_completa_prima": {"it": "Completa il pagamento per attivare il voucher", "en": "Complete the payment to activate the voucher", "es": "Completa el pago para activar el bono", "fr": "Finalisez le paiement pour activer le bon", "de": "Zahlung abschließen, um den Gutschein zu aktivieren", "pt": "Conclui o pagamento para ativar o voucher", "ja": "お支払いを完了するとバウチャーが有効になります", "zh": "完成付款以激活凭证"},
    "v_pin_dopo_pagamento": {"it": "Il PIN di check-in e le opzioni di gestione si sbloccano dopo il pagamento.", "en": "The check-in PIN and the management options unlock after payment.", "es": "El PIN de entrada y las opciones de gestión se desbloquean tras el pago.", "fr": "Le PIN d'arrivée et les options de gestion se débloquent après le paiement.", "de": "Check-in-PIN und Verwaltungsoptionen werden nach der Zahlung freigeschaltet.", "pt": "O PIN de check-in e as opções de gestão desbloqueiam-se após o pagamento.", "ja": "チェックインPINと管理メニューはお支払い後に利用できます。", "zh": "入住 PIN 与管理选项将在付款后解锁。"},
    # --- messaggi che il voucher mostra DOPO un clic (finivano nel codice, in italiano) ---
    "v_js_conferma_canc": {"it": "Cancellare la prenotazione?", "en": "Cancel this booking?", "es": "¿Anular la reserva?", "fr": "Annuler la réservation ?", "de": "Buchung wirklich stornieren?", "pt": "Cancelar a reserva?", "ja": "予約をキャンセルしますか？", "zh": "确定要取消预订吗？"},
    "v_js_cancellata": {"it": "Cancellata. Rimborso", "en": "Cancelled. Refund", "es": "Anulada. Reembolso", "fr": "Annulée. Remboursement", "de": "Storniert. Erstattung", "pt": "Cancelada. Reembolso", "ja": "キャンセルしました。返金", "zh": "已取消。退款"},
    "v_js_canc_ko": {"it": "Cancellazione non riuscita", "en": "Cancellation failed", "es": "No se pudo anular", "fr": "Échec de l'annulation", "de": "Stornierung fehlgeschlagen", "pt": "Cancelamento falhou", "ja": "キャンセルできませんでした", "zh": "取消失败"},
    "v_js_op_ko": {"it": "Operazione non riuscita", "en": "Operation failed", "es": "Operación fallida", "fr": "Opération échouée", "de": "Vorgang fehlgeschlagen", "pt": "Operação falhou", "ja": "操作に失敗しました", "zh": "操作失败"},
    "v_js_ok_sbloccato": {"it": "Grazie! Pagamento sbloccato per l'host.", "en": "Thank you! Payment released to the host.", "es": "¡Gracias! Pago liberado al anfitrión.", "fr": "Merci ! Paiement débloqué pour l'hôte.", "de": "Danke! Zahlung für den Gastgeber freigegeben.", "pt": "Obrigado! Pagamento libertado ao anfitrião.", "ja": "ありがとうございます！ホストへの支払いを解除しました。", "zh": "谢谢！已向房东释放付款。"},
    "v_js_segnalato": {"it": "Segnalazione ricevuta: pagamento sospeso, ti ricontattiamo.", "en": "Report received: payment on hold, we'll get back to you.", "es": "Incidencia recibida: pago en espera, te contactaremos.", "fr": "Signalement reçu : paiement suspendu, nous vous recontactons.", "de": "Meldung erhalten: Zahlung ausgesetzt, wir melden uns.", "pt": "Comunicação recebida: pagamento suspenso, entraremos em contacto.", "ja": "ご報告を受け付けました：お支払いを保留し、追ってご連絡します。", "zh": "已收到反馈：付款已暂停，我们会与您联系。"},
    "v_js_nessun_msg": {"it": "Nessun messaggio ancora.", "en": "No messages yet.", "es": "Aún no hay mensajes.", "fr": "Aucun message pour l'instant.", "de": "Noch keine Nachrichten.", "pt": "Ainda sem mensagens.", "ja": "まだメッセージはありません。", "zh": "暂无消息。"},
    "v_js_apri_foto": {"it": "apri foto", "en": "open photo", "es": "abrir foto", "fr": "ouvrir la photo", "de": "Foto öffnen", "pt": "abrir foto", "ja": "写真を開く", "zh": "查看照片"},
    "v_js_prova_ok": {"it": "Prova caricata: è nella conversazione.", "en": "Evidence uploaded: it's in the conversation.", "es": "Prueba subida: está en la conversación.", "fr": "Preuve envoyée : elle est dans la conversation.", "de": "Nachweis hochgeladen: er ist im Chat.", "pt": "Prova carregada: está na conversa.", "ja": "証拠をアップロードしました：会話に表示されます。", "zh": "凭证已上传：已加入对话。"},
    "v_js_foto_ko": {"it": "Foto non valida (max 5MB, jpg/png).", "en": "Invalid photo (max 5MB, jpg/png).", "es": "Foto no válida (máx 5MB, jpg/png).", "fr": "Photo non valide (max 5 Mo, jpg/png).", "de": "Ungültiges Foto (max. 5 MB, jpg/png).", "pt": "Foto inválida (máx 5MB, jpg/png).", "ja": "無効な写真です（最大5MB、jpg/png）。", "zh": "照片无效（最大 5MB，jpg/png）。"},
    "v_js_foto_limite": {"it": "Hai raggiunto il limite di prove caricabili.", "en": "You've reached the limit of uploadable evidence.", "es": "Has alcanzado el límite de pruebas subibles.", "fr": "Vous avez atteint la limite de preuves téléversables.", "de": "Sie haben das Limit hochladbarer Nachweise erreicht.", "pt": "Atingiste o limite de provas carregáveis.", "ja": "アップロードできる証拠の上限に達しました。", "zh": "已达到可上传凭证的上限。"},
    "v_js_riprova": {"it": "Non riuscito in questo momento: riprova tra qualche istante.", "en": "Not possible right now: please try again in a moment.", "es": "No ha sido posible ahora: inténtalo en un momento.", "fr": "Impossible pour le moment : réessayez dans un instant.", "de": "Gerade nicht möglich: bitte gleich erneut versuchen.", "pt": "Não foi possível agora: tenta daqui a pouco.", "ja": "現在実行できません。しばらくしてからお試しください。", "zh": "当前无法完成：请稍后再试。"},
    "v_js_ck_completato": {"it": "Check-in online completato", "en": "Online check-in completed", "es": "Check-in online completado", "fr": "Enregistrement en ligne terminé", "de": "Online-Check-in abgeschlossen", "pt": "Check-in online concluído", "ja": "オンラインチェックイン完了", "zh": "在线登记已完成"},
    "v_js_ck_almeno_uno": {"it": "Aggiungi almeno un ospite", "en": "Add at least one guest", "es": "Añade al menos un huésped", "fr": "Ajoutez au moins un voyageur", "de": "Mindestens einen Gast hinzufügen", "pt": "Adiciona pelo menos um hóspede", "ja": "少なくとも1名を追加してください", "zh": "请至少添加一位入住人"},
    "v_js_ck_ok": {"it": "Check-in completato: al tuo arrivo basta il PIN.", "en": "Check-in completed: on arrival the PIN is enough.", "es": "Check-in completado: al llegar basta el PIN.", "fr": "Enregistrement terminé : à l'arrivée, le PIN suffit.", "de": "Check-in abgeschlossen: bei Ankunft genügt die PIN.", "pt": "Check-in concluído: à chegada basta o PIN.", "ja": "チェックイン完了：到着時はPINだけで大丈夫です。", "zh": "登记完成：抵达时只需 PIN。"},
    "v_js_ck_ko": {"it": "Dati non validi: controlla nomi/documenti. Gli ospiti non possono superare le persone della prenotazione.", "en": "Invalid data: check names/documents. Guests cannot exceed the people in the booking.", "es": "Datos no validos: revisa nombres/documentos. Los huespedes no pueden superar las personas de la reserva.", "fr": "Donnees invalides : verifiez noms/documents. Les voyageurs ne peuvent pas depasser les personnes de la reservation.", "de": "Ungueltige Daten: Namen/Ausweise pruefen. Die Gaeste duerfen die Personen der Buchung nicht ueberschreiten.", "pt": "Dados invalidos: verifica nomes/documentos. Os hospedes nao podem exceder as pessoas da reserva.", "ja": "データが無効です：氏名・書類をご確認ください。ご予約の人数を超えて登録することはできません。", "zh": "数据无效：请检查姓名/证件。入住人数不能超过预订人数。"},
    # --- RICEVUTA di pagamento (era interamente in italiano, per chiunque) ---
    "ric_alloggio": {"it": "Alloggio", "en": "Property", "es": "Alojamiento", "fr": "Logement", "de": "Unterkunft", "pt": "Alojamento", "ja": "宿泊施設", "zh": "住宿"},
    "ric_soggiorno": {"it": "Soggiorno", "en": "Stay", "es": "Estancia", "fr": "Séjour", "de": "Aufenthalt", "pt": "Estadia", "ja": "滞在", "zh": "住宿费"},
    "ric_totale_pagato": {"it": "Totale pagato", "en": "Total paid", "es": "Total pagado", "fr": "Total payé", "de": "Gesamt bezahlt", "pt": "Total pago", "ja": "お支払い合計", "zh": "已付总额"},
    "ric_nota_stripe": {"it": "Pagamento elaborato da Stripe. Gestore della piattaforma:", "en": "Payment processed by Stripe. Platform operator:", "es": "Pago procesado por Stripe. Operador de la plataforma:", "fr": "Paiement traité par Stripe. Exploitant de la plateforme :", "de": "Zahlung abgewickelt von Stripe. Betreiber der Plattform:", "pt": "Pagamento processado pela Stripe. Operador da plataforma:", "ja": "決済はStripeが処理します。プラットフォーム運営者：", "zh": "付款由 Stripe 处理。平台运营方："},
    "ric_nota_fattura": {"it": "Questa ricevuta attesta il pagamento e non costituisce fattura fiscale.", "en": "This receipt attests the payment and is not a tax invoice.", "es": "Este recibo acredita el pago y no constituye factura fiscal.", "fr": "Ce reçu atteste le paiement et ne constitue pas une facture fiscale.", "de": "Dieser Beleg bestätigt die Zahlung und ist keine Steuerrechnung.", "pt": "Este recibo comprova o pagamento e não constitui fatura fiscal.", "ja": "この領収書はお支払いを証明するもので、税務上の請求書ではありません。", "zh": "此收据用于证明付款，不构成税务发票。"},
    "ric_stampa": {"it": "Stampa / salva PDF", "en": "Print / save PDF", "es": "Imprimir / guardar PDF", "fr": "Imprimer / enregistrer en PDF", "de": "Drucken / als PDF speichern", "pt": "Imprimir / guardar PDF", "ja": "印刷 / PDFで保存", "zh": "打印 / 保存 PDF"},
    # --- pagina RECENSIONE (era bilingue it/en: un tedesco leggeva italiano) ---
    "rec_dopo_soggiorno": {"it": "Potrai lasciare la recensione al termine del soggiorno.", "en": "You'll be able to review once your stay is over.", "es": "Podrás dejar tu reseña cuando termine la estancia.", "fr": "Vous pourrez laisser un avis une fois le séjour terminé.", "de": "Sie können nach Ende Ihres Aufenthalts bewerten.", "pt": "Poderás avaliar quando a estadia terminar.", "ja": "ご滞在の終了後にレビューを書けます。", "zh": "入住结束后即可评价。"},
    "rec_domanda": {"it": "Com'è andato il tuo soggiorno a", "en": "How was your stay at", "es": "¿Qué tal tu estancia en", "fr": "Comment s'est passé votre séjour à", "de": "Wie war Ihr Aufenthalt in", "pt": "Como foi a tua estadia em", "ja": "こちらのご滞在はいかがでしたか：", "zh": "您在此的入住体验如何："},
    "rec_solo_veri": {"it": "Solo chi ha soggiornato davvero può recensire: la tua opinione è verificata.", "en": "Only real guests can review: your opinion is verified.", "es": "Solo quien se ha alojado de verdad puede opinar: tu opinión está verificada.", "fr": "Seuls les vrais voyageurs peuvent laisser un avis : votre opinion est vérifiée.", "de": "Nur echte Gäste können bewerten: Ihre Meinung ist verifiziert.", "pt": "Só quem ficou mesmo pode avaliar: a tua opinião é verificada.", "ja": "実際に滞在した方だけがレビューできます。あなたの声は認証済みです。", "zh": "只有真正入住过的客人才能评价：您的意见经过验证。"},
    # --- pagina LINK VOUCHER NON VALIDO (era bilingue it/en) ---
    "lnv_titolo": {"it": "Link non valido", "en": "Link not valid", "es": "Enlace no válido", "fr": "Lien non valide", "de": "Link ungültig", "pt": "Link inválido", "ja": "リンクが無効です", "zh": "链接无效"},
    "lnv_h1": {"it": "Questo link del voucher non è valido", "en": "This voucher link isn't valid", "es": "Este enlace del bono no es válido", "fr": "Ce lien de bon n'est pas valide", "de": "Dieser Gutschein-Link ist ungültig", "pt": "Este link do voucher não é válido", "ja": "このバウチャーのリンクは無効です", "zh": "此凭证链接无效"},
    "lnv_p1": {"it": "Il link potrebbe essere vecchio, incompleto o scaduto.", "en": "The link may be old, incomplete or expired.", "es": "El enlace puede ser antiguo, incompleto o estar caducado.", "fr": "Le lien peut être ancien, incomplet ou expiré.", "de": "Der Link kann alt, unvollständig oder abgelaufen sein.", "pt": "O link pode estar antigo, incompleto ou expirado.", "ja": "リンクが古い、不完全、または期限切れの可能性があります。", "zh": "该链接可能过旧、不完整或已过期。"},
    "lnv_p2": {"it": "Apri il link dall'ultima email di conferma che hai ricevuto, oppure scrivici e ti aiutiamo subito.", "en": "Please open the link from your latest confirmation email, or contact us and we'll help right away.", "es": "Abre el enlace desde el último correo de confirmación que recibiste, o escríbenos y te ayudamos enseguida.", "fr": "Ouvrez le lien depuis votre dernier e-mail de confirmation, ou écrivez-nous et nous vous aidons tout de suite.", "de": "Öffnen Sie den Link aus Ihrer letzten Bestätigungs-E-Mail, oder schreiben Sie uns — wir helfen sofort.", "pt": "Abre o link a partir do último e-mail de confirmação, ou escreve-nos e ajudamos já.", "ja": "最新の確認メールからリンクを開いてください。ご不明な場合はご連絡いただければすぐに対応します。", "zh": "请从您最近收到的确认邮件中打开链接，或联系我们，我们会立即协助。"},
    "lnv_home": {"it": "Torna su BookinVIP", "en": "Back to BookinVIP", "es": "Volver a BookinVIP", "fr": "Retour sur BookinVIP", "de": "Zurück zu BookinVIP", "pt": "Voltar à BookinVIP", "ja": "BookinVIPに戻る", "zh": "返回 BookinVIP"},
}


def _lingua_pagina(lingua: Any, voucher: Any = None) -> str:
    """La lingua di una pagina server-rendered, con la gerarchia giusta:
    1) quella chiesta nell'URL, se la parliamo;
    2) altrimenti quella FIRMATA nel gettone del voucher (catturata al momento del book:
       e' la lingua vera dell'ospite, e nessuno puo' manometterla);
    3) altrimenti INGLESE.
    Non ripiega MAI sull'italiano: era il difetto per cui un ospite giapponese apriva in
    italiano il documento che deve mostrare al check-in."""
    if lingua in LINGUE_SUPPORTATE:
        return lingua
    if isinstance(voucher, dict):
        firmata = voucher.get("lang")
        if firmata in LINGUE_SUPPORTATE:
            return firmata
    return "en"


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


# Fasce orarie estreme del pianeta: da UTC-12 a UTC+14 (Kiribati).
ORE_FUSO_MIN, ORE_FUSO_MAX = -12, 14
ORA_CHECKIN_LOCALE = 15          # convenzione: check-in alle 15:00 ORA LOCALE


def _istante_checkin_prudente(check_in: str) -> Optional[int]:
    """L'istante da cui contare le 24 ore di contestazione, SENZA sapere il fuso.

    L'alloggio non ha un fuso orario nel modello dati. Prima si faceva
    `fromisoformat(ci + "T15:00:00").timestamp()`, cioe' si assumeva che ogni alloggio
    del mondo facesse il check-in alle 15:00 **del fuso del server** (UTC in produzione).
    Per chi sta a ovest di Greenwich quell'istante cade PRIMA dell'arrivo reale, e la
    finestra di 24 ore in cui l'ospite puo' contestare si chiude quando ha passato in
    casa appena 14 ore: dieci ore di tutela in meno, su soldi gia' pagati.

    Qui si prende l'istante piu' TARDI in cui possa essere check-in da qualche parte
    (le 15:00 a UTC-12). Il motivo e' che `fase160` calcola la scadenza come
    `questo istante + 24h`: quindi cio' che conta e' **quando la finestra si CHIUDE**,
    non quando si apre. Aprirla presto non allunga niente — anzi la chiude prima, ed e'
    l'errore che avevo fatto alla prima stesura (Tokyo scendeva a 19 ore). Ancorandola
    all'ultimo arrivo possibile al mondo, la scadenza cade sempre almeno 24 ore dopo
    l'arrivo VERO di chiunque. L'host viene pagato al massimo un giorno dopo: fra
    accorciare la tutela di chi ha appena pagato e ritardare un incasso, si sceglie il
    secondo.

    Quando l'alloggio avra' un fuso (derivabile da citta'/paese), questa approssimazione
    va sostituita dall'ora locale vera.
    """
    import datetime as _d
    try:
        giorno = _d.date.fromisoformat(str(check_in))
    except Exception:
        return None
    piu_a_ovest = _d.timezone(_d.timedelta(hours=ORE_FUSO_MIN))
    return int(_d.datetime(giorno.year, giorno.month, giorno.day,
                           ORA_CHECKIN_LOCALE, 0, 0, tzinfo=piu_a_ovest).timestamp())


def _istante_fine_tutela(check_in: str, ore_finestra: int = 24) -> Optional[int]:
    """L'istante entro cui la tutela deve valere per CHIUNQUE: le 24 ore contate
    dall'ultimo check-in possibile al mondo (le 15:00 a UTC-12)."""
    import datetime as _d
    try:
        giorno = _d.date.fromisoformat(str(check_in))
    except Exception:
        return None
    piu_a_ovest = _d.timezone(_d.timedelta(hours=ORE_FUSO_MIN))
    inizio = _d.datetime(giorno.year, giorno.month, giorno.day,
                         ORA_CHECKIN_LOCALE, 0, 0, tzinfo=piu_a_ovest)
    return int((inizio + _d.timedelta(hours=int(ore_finestra))).timestamp())


def _line_token_valido(s: str) -> bool:
    """Un LINE Notify token e' una stringa-token: lettere/cifre/-/_ , niente spazi, niente
    '@' (un'email non e' un token), non un URL. Vuoto = valido (campo OPZIONALE)."""
    t = str(s or "").strip()
    if not t:
        return True
    if " " in t or "@" in t or t.lower().startswith(("http://", "https://")):
        return False
    import re as _re
    return bool(_re.fullmatch(r"[A-Za-z0-9_\-]{8,200}", t))


def _wechat_webhook_valido(s: str) -> bool:
    """Un webhook WeChat Work e' un URL HTTPS (es. https://qyapi.weixin.qq.com/...).
    Vuoto = valido (campo OPZIONALE). Si rifiuta un'email o testo a caso."""
    u = str(s or "").strip()
    if not u:
        return True
    if " " in u or "@" in u.split("://")[-1].split("/")[0]:
        return False
    return u.lower().startswith("https://") and "." in u.split("://")[-1].split("/")[0]


def _valida_canali_opzionali(dati: Dict[str, Any]):
    """Ritorna (400, {...}) se un canale opzionale e' compilato MALE, altrimenti None.
    Serve a dare all'host un errore CHIARO sul campo giusto, senza far nascere un account
    con un webhook rotto (che poi fallirebbe in silenzio al primo avviso)."""
    if not _line_token_valido(dati.get("line_token", "")):
        return (422, {"errore": "line_token_non_valido", "campo": "line_token"})
    if not _wechat_webhook_valido(dati.get("wechat_webhook", "")):
        return (422, {"errore": "wechat_webhook_non_valido", "campo": "wechat_webhook"})
    return None


def _istante_checkin(check_in: str, fuso: str = "") -> Optional[int]:
    """L'istante (epoch UTC) del check-in alle 15:00 ORA LOCALE DELL'ALLOGGIO.

    Se l'alloggio ha un fuso vero (`Asia/Tokyo`, `Pacific/Honolulu`, ...) l'istante e'
    ESATTO. Se non ce l'ha, si ricade sull'approssimazione prudente (l'ultimo check-in
    possibile al mondo), che non stringe mai la tutela di nessuno. Cosi' l'aggiunta del
    fuso all'alloggio migliora la precisione senza rischiare regressioni dove manca."""
    if fuso:
        try:
            from fase187_fuso_orario import istante_locale
            preciso = istante_locale(check_in, ORA_CHECKIN_LOCALE, fuso)
            if preciso is not None:
                return preciso
        except Exception:
            pass
    return _istante_checkin_prudente(check_in)


def _mezzanotte_checkout(check_out: str, fuso: str = "") -> Optional[int]:
    """Mezzanotte del giorno di CHECK-OUT nel fuso dell'alloggio: da qui si puo'
    recensire (dopo il soggiorno, ora locale). Senza fuso, la mezzanotte piu' TARDI al
    mondo (UTC-12), cosi' nessuno recensisce prima del proprio giorno di check-out."""
    if fuso:
        try:
            from fase187_fuso_orario import mezzanotte_locale
            preciso = mezzanotte_locale(check_out, fuso)
            if preciso is not None:
                return preciso
        except Exception:
            pass
    import datetime as _d
    try:
        g = _d.date.fromisoformat(str(check_out))
    except Exception:
        return None
    piu_a_ovest = _d.timezone(_d.timedelta(hours=ORE_FUSO_MIN))
    return int(_d.datetime(g.year, g.month, g.day, 0, 0, 0, tzinfo=piu_a_ovest).timestamp())


SECONDI_RIPENSAMENTO = 48 * 3600          # 172.800: quarantotto ore VERE


def _entro_ripensamento(voucher: Dict[str, Any]) -> bool:
    """Vero se dalla prenotazione sono passati meno di 172.800 secondi.

    Prima si contavano i GIORNI DI CALENDARIO (`date.today() - prenotato_data <= 2`) col
    giorno del SERVER. Chi prenotava alle 23:50 aveva diritto al rimborso pieno anche 26
    ore dopo; chi prenotava alle 00:10 ce l'aveva ancora dopo 49. La finestra reale
    andava da 48 a 72 ore secondo l'ora della prenotazione, e cambiava a seconda del fuso
    dell'utente — su un diritto legale (California SB 644, art. 49 del codice del
    consumatore brasiliano).

    L'istante sta nel gettone FIRMATO, quindi non e' manomettibile dal browser.

    I voucher emessi PRIMA di questa modifica non hanno l'istante e non si possono
    riscrivere (sono firmati): per quelli si ricade sul vecchio conteggio a giorni, che
    e' piu' largo. Un diritto gia' comunicato non lo si restringe a cose fatte.
    """
    import datetime as _d
    import time as _t
    ts = voucher.get("prenotato_ts")
    if isinstance(ts, int) and not isinstance(ts, bool) and ts > 0:
        trascorsi = int(_t.time()) - ts
        return 0 <= trascorsi <= SECONDI_RIPENSAMENTO
    pren = voucher.get("prenotato_data")           # gettoni vecchi: conteggio storico
    if isinstance(pren, str) and pren:
        try:
            giorni = (_d.date.today() - _d.date.fromisoformat(pren)).days
            return 0 <= giorni <= 2
        except Exception:
            return False
    return False


def _lingua(query: Dict[str, str]) -> str:
    lng = (query or {}).get("lang", "")
    return lng if lng in LINGUE_SUPPORTATE else "en"


# ─────────────────────────────────────────────────────────────────────────────
# SEO / discoverability (gratis): pagina crawlabile per alloggio + JSON-LD + sitemap.
# Funzioni PURE e testabili. base_url = dominio (vuoto = relativo finche' non c'e').
# ─────────────────────────────────────────────────────────────────────────────
def _importo(cents: Any, valuta: Any = "EUR") -> str:
    """Importo secondo i decimali VERI della valuta (JPY 0, KWD 3), chiesti al motore.

    Si chiamava `_euro` e divideva per cento sempre. Su un annuncio in yen produceva
    "540.00" per ¥54.000: sbagliato di cento volte sulla pagina pubblica E dentro il
    JSON-LD, cioe' nel prezzo che Google mostra nei risultati di ricerca.
    Nessun float: il motore lavora su interi.
    """
    if not isinstance(cents, int) or isinstance(cents, bool) or cents < 0:
        cents = 0
    v = str(valuta or "EUR").strip().upper() or "EUR"
    try:
        from fase99_multicurrency import Denaro
        return Denaro(cents, v).formatta().rsplit(" ", 1)[0]
    except Exception:
        return "%d" % cents


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
        "numberOfBathroomsTotal": dettaglio.get("bagni", 1),
        "occupancy": {"@type": "QuantitativeValue",
                      "maxValue": dettaglio.get("capacita", 1)},
        "amenityFeature": [{"@type": "LocationFeatureSpecification",
                            "name": s, "value": True} for s in servizi],
        "offers": {"@type": "Offer",
                   "price": _importo(dettaglio.get("prezzo_notte_cents", 0),
                                     dettaglio.get("valuta", "EUR")),
                   "priceCurrency": dettaglio.get("valuta", "EUR")},
    }
    # geo: coordinate di ZONA (gia' pubbliche nella mappa; MAI l'indirizzo). Da microgradi
    # interi a stringa decimale senza float (segno + divmod).
    lat, lon = dettaglio.get("lat_micro"), dettaglio.get("lon_micro")
    if isinstance(lat, int) and isinstance(lon, int):
        def _gradi(micro: int) -> str:
            segno = "-" if micro < 0 else ""
            g, resto = divmod(abs(micro), 1_000_000)
            return "%s%d.%06d" % (segno, g, resto)
        ld["geo"] = {"@type": "GeoCoordinates",
                     "latitude": _gradi(lat), "longitude": _gradi(lon)}
    # image[]: le foto reali dell'annuncio (rich result + prova visiva dei fatti)
    foto = [i.get("url") for i in (dettaglio.get("immagini") or ())
            if isinstance(i, dict) and isinstance(i.get("url"), str)]
    if foto:
        ld["image"] = foto
    if isinstance(recensioni, dict) and recensioni.get("conteggio", 0) > 0:
        media = recensioni.get("media_centesimi", 0)
        ld["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": "%d.%02d" % (media // 100, media % 100),  # es. 4.25, no float
            "reviewCount": int(recensioni["conteggio"]),
            "bestRating": "5", "worstRating": "1",
        }
    return ld


def _og_image_url(d: Any) -> str:
    """URL immagine per l'anteprima social (og:image). La 1a foto dell'annuncio se c'e';
    altrimenti un'immagine GRATIS generata da Pollinations (titolo+citta), formato OG 1200x630.
    Cosi' ogni link condiviso mostra SEMPRE una foto (mai un'anteprima nuda)."""
    from urllib.parse import quote as _q
    try:
        imgs = d.get("immagini") or d.get("foto") or []
        if isinstance(imgs, (list, tuple)) and imgs:
            primo = imgs[0]
            u = primo.get("url") if isinstance(primo, dict) else getattr(primo, "url", "")
            if u and str(u).startswith("http"):
                return str(u)
    except Exception:
        pass
    prompt = ("%s %s alloggio, fotografia realistica, luce naturale"
              % (d.get("titolo", "") if isinstance(d, dict) else "",
                 d.get("citta", "") if isinstance(d, dict) else "")).strip()
    return ("https://image.pollinations.ai/prompt/%s?width=1200&height=630&nologo=true"
            % _q(prompt[:200]))


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

    # FAQ da FATTI REALI (motore SEO fase173): la pagina diventa LA RISPOSTA (ponte AEO).
    # FAQPage JSON-LD (rich result) + <details> VISIBILI e COERENTI col markup (Google penalizza
    # la FAQ strutturata non visibile). ISOLATO: mai rompe la pagina; POI da cache calda post-publish.
    faq_ld_script, faq_html = "", ""
    try:
        from fase173_motore_seo import crea_motore_da_sistema, genera_faq, faq_jsonld
        rapporto = crea_motore_da_sistema(sistema).valuta(d)
        faq = genera_faq(rapporto, d)
        fld = faq_jsonld(faq)
        if fld:
            fl = (json.dumps(fld, ensure_ascii=False)
                  .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))
            faq_ld_script = "<script type=\"application/ld+json\">%s</script>" % fl
            faq_html = ("<section aria-labelledby=\"faq\"><h2 id=\"faq\">Domande frequenti</h2>"
                        + "".join("<details><summary>%s</summary><p>%s</p></details>"
                                  % (e(x["q"]), e(x["a"])) for x in faq)
                        + "</section>")
    except Exception:
        faq_ld_script, faq_html = "", ""

    # OPEN GRAPH + Twitter Card: link condiviso -> anteprima RICCA (foto+titolo+prezzo). Costruito
    # per concatenazione (gia' escapato) per non toccare gli argomenti % della pagina.
    _ogimg = _og_image_url(d)
    _ogtit = e((str(d.get("titolo", "")) + " · " + str(d.get("citta", ""))).strip(" ·"))
    _ogdesc = e(str(d.get("descrizione", ""))[:200])
    _ogprice = e(_importo(d.get("prezzo_notte_cents", 0), d.get("valuta", "EUR")))
    og = (
        "<meta property=\"og:type\" content=\"website\">"
        "<meta property=\"og:site_name\" content=\"BookinVIP\">"
        "<meta property=\"og:title\" content=\"" + _ogtit + "\">"
        "<meta property=\"og:description\" content=\"" + _ogdesc + "\">"
        "<meta property=\"og:url\" content=\"" + e(base_url) + "/alloggio/" + e(slug) + "\">"
        "<meta property=\"og:image\" content=\"" + e(_ogimg) + "\">"
        "<meta property=\"og:image:width\" content=\"1200\">"
        "<meta property=\"og:image:height\" content=\"630\">"
        "<meta property=\"product:price:amount\" content=\"" + _ogprice + "\">"
        "<meta property=\"product:price:currency\" content=\"" + e(d.get("valuta", "EUR")) + "\">"
        "<meta name=\"twitter:card\" content=\"summary_large_image\">"
        "<meta name=\"twitter:title\" content=\"" + _ogtit + "\">"
        "<meta name=\"twitter:image\" content=\"" + e(_ogimg) + "\">"
    )

    return (
        "<!DOCTYPE html><html lang=\"it\"><head><meta charset=\"UTF-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>%s - BookinVIP</title>"
        "<meta name=\"description\" content=\"%s\">%s"
        "<link rel=\"canonical\" href=\"%s/alloggio/%s\">"
        "<script type=\"application/ld+json\">%s</script>%s</head><body>"
        "<h1>%s</h1><p><strong>%s</strong>%s</p><p>%s</p>"
        "<p>Prezzo: %s %s / notte</p><ul>%s</ul>%s"
        "<p><a href=\"/?slug=%s\">Prenota su BookinVIP</a></p></body></html>"
    ) % (
        e(d.get("titolo", "")), e(d.get("descrizione", ""))[:160], og,
        e(base_url), e(slug), ld, faq_ld_script,
        e(d.get("titolo", "")), e(d.get("citta", "")),
        ", " + e(d.get("paese", "")) if d.get("paese") else "",
        e(d.get("descrizione", "")),
        e(_importo(d.get("prezzo_notte_cents", 0), d.get("valuta", "EUR"))),
        e(d.get("valuta", "EUR")),
        servizi, faq_html, e(slug),
    )


def feed_rss_xml(sistema: Any, base_url: str = "") -> str:
    """Feed RSS 2.0 degli annunci recenti (GRATIS, sempre-attivo, zero chiave). Ogni voce porta a
    /alloggio/slug (con Open Graph). Serve alla SYNDICATION autonoma: aggregatori, lettori RSS,
    IFTTT/Zapier che ri-postano ovunque. Isolato: errore su un annuncio -> saltato, mai rompe."""
    from xml.sax.saxutils import escape as _x
    base = base_url or "https://bookinvip.com"
    items: List[str] = []
    try:
        from fase57_vetrina import CriteriRicerca
        res = sistema.catalogo.cerca(CriteriRicerca(limit=40))
        for r in (res.get("risultati", []) if isinstance(res, dict) else []):
            try:
                slug = str(r.get("slug", ""))
                if not slug:
                    continue
                titolo = _x(str(r.get("titolo", "") or slug))
                citta = _x(str(r.get("citta", "")))
                desc = _x(str(r.get("descrizione", ""))[:300])
                link = _x("%s/alloggio/%s" % (base, slug))
                img = _x(_og_image_url(r))
                prezzo = _x(_importo(r.get("prezzo_notte_cents", 0), r.get("valuta", "EUR")))
                items.append(
                    "<item><title>%s — %s</title><link>%s</link><guid isPermaLink=\"true\">%s</guid>"
                    "<description>%s (da %s a notte)</description>"
                    "<enclosure url=\"%s\" type=\"image/jpeg\"/></item>"
                    % (titolo, citta, link, link, desc, prezzo, img))
            except Exception:
                continue
    except Exception:
        pass
    canale = ("<title>BookinVIP — nuovi alloggi</title><link>%s</link>"
              "<description>Alloggi dal marketplace BookinVIP (commissioni oneste)</description>"
              "<language>it</language>" % _x(base))
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<rss version="2.0"><channel>%s%s</channel></rss>' % (canale, "".join(items)))


def sitemap_xml(sistema: Any, base_url: str = "") -> str:
    """sitemap.xml con tutte le schede pubblicate (per Google). Ogni <url> porta il <lastmod>
    REALE della scheda (data di `aggiornato_ts`): i crawler ricrawlano solo ciò che è cambiato
    → budget di scansione. Il lastmod cambia SOLO quando la scheda cambia, mai a ogni richiesta."""
    coppie: List[Tuple[str, str]] = []      # (slug, 'YYYY-MM-DD' | "")
    try:
        metodo = getattr(sistema.catalogo, "slug_lastmod_pubblicati", None)
        if callable(metodo):
            coppie = [(str(s), str(lm or "")[:10]) for s, lm in (metodo(limit=10000) or []) if s]
        else:                                # fallback difensivo (catalogo senza il metodo)
            from fase57_vetrina import CriteriRicerca, PAGINA_MAX
            offset = 0
            while offset < 10000:
                res = sistema.catalogo.cerca(CriteriRicerca(limit=PAGINA_MAX, offset=offset))
                righe = res.get("risultati", [])
                if not righe:
                    break
                coppie.extend((str(r.get("slug", "")), "") for r in righe if r.get("slug"))
                if len(righe) < PAGINA_MAX:
                    break
                offset += PAGINA_MAX
    except Exception:
        pass

    def _riga(slug: str, lm: str) -> str:
        # lm = solo data 'YYYY-MM-DD' da isoformat → caratteri sicuri per l'XML
        tag = ("<lastmod>%s</lastmod>" % lm) if lm else ""
        return "<url><loc>%s/alloggio/%s</loc>%s</url>" % (base_url, slug, tag)

    urls = "".join(_riga(s, lm) for s, lm in coppie)
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            '<url><loc>%s/</loc></url>%s</urlset>' % (base_url, urls))


def robots_txt(base_url: str = "") -> str:
    # Entry-point = sitemap-INDEX (scala oltre 50k URL) + le due sitemap dirette per compat.
    return ("User-agent: *\nAllow: /\nSitemap: %s/sitemap-index.xml\n"
            "Sitemap: %s/sitemap.xml\nSitemap: %s/sitemap-host.xml\n"
            "Sitemap: %s/sitemap-blog.xml\n"
            % (base_url, base_url, base_url, base_url))


def etag_di(dati: bytes) -> str:
    """ETag forte sul CONTENUTO (sha1 troncato): stesso contenuto → stesso ETag. Il crawler che
    rimanda l'If-None-Match riceve 304 e NON riscarica (risparmio di budget di scansione)."""
    import hashlib
    # usedforsecurity=False: e' un'impronta di CONTENUTO per la cache HTTP (ETag/304), NON un
    # uso crittografico -> SHA1 va bene qui, e lo dichiariamo esplicito (ambienti FIPS + scanner).
    return '"%s"' % hashlib.sha1(dati, usedforsecurity=False).hexdigest()[:16]


def etag_combacia(etag: str, if_none_match: str) -> bool:
    """True se l'ETag è fra quelli in If-None-Match (lista separata da virgole) o se è '*'."""
    if not if_none_match:
        return False
    inm = if_none_match.strip()
    if inm == "*":
        return True
    return etag in [t.strip() for t in inm.split(",")]


def _citta_inventario(sistema: Any) -> List[str]:
    """Città con inventario reale dal catalogo (per il registro anti-doorway). BLINDATO → []."""
    try:
        m = getattr(sistema.catalogo, "citta_pubblicate", None)
        return list(m()) if callable(m) else []
    except Exception:
        return []


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
            "/api/legale/documento": {"get": {"operationId": "documentoLegale",
                "summary": "Termini o Privacy nella lingua richiesta (versione + impronta)",
                "parameters": [_q("doc", "string", "termini|privacy"),
                               _q("lang", "string", "it,en,es,fr,de,pt,ja,zh")],
                "responses": {"200": {"description": "testo + versione + doc_sha256"}}}},
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
    # "revenue_eur" dava l'euro per scontato: un host giapponese esportava i suoi
    # incassi con l'intestazione sbagliata e il numero diviso per cento. Ora la valuta
    # e' una colonna, e l'importo rispetta i suoi decimali.
    w.writerow(["alloggio", "check_in", "check_out", "notti", "origine", "stato",
                "revenue", "valuta", "riferimento"])
    for r in (righe or []):
        if not isinstance(r, dict):
            continue
        rev = r.get("revenue_cents", 0)
        rev = rev if isinstance(rev, int) and not isinstance(rev, bool) else 0
        w.writerow([
            r.get("alloggio_id", ""), r.get("check_in", ""), r.get("check_out", ""),
            _notti_count(r.get("check_in"), r.get("check_out")),
            r.get("origine", ""), "rimborsata" if r.get("rimborsato") else "attiva",
            _importo(rev, r.get("valuta", "EUR")), str(r.get("valuta", "EUR")),
            str(r.get("idem_key", ""))[:16],
        ])
    return buf.getvalue()


# Mostrare il codice "serratura smart" sul voucher? OFF finché non c'è integrazione hardware
# reale (nessun host ha serrature smart al lancio): evita di confondere il cliente con un codice
# lungo e inutile. Riattivare (True) quando esisterà una vera serratura/QR per l'ospite.
MOSTRA_PASS_SERRATURA = False

# Penale a carico dell'HOST se annulla una prenotazione già pagata (deterrente, come i colossi):
# 15% del valore. Il cliente è comunque rimborsato al 100%.
PENALE_HOST_BPS = 1500

# Su-richiesta APPROVATA: quanto tempo ha il cliente per pagare (dall'email). ~24h come i
# colossi (Airbnb request-to-book), dentro il massimo Stripe (sessione <= 24h): 23h55m.
# L'hold stanza e la sessione Stripe scadono INSIEME (niente "link vivo, stanza persa").
HOLD_APPROVAZIONE_SEC = 86100


def riga_pin_voucher(valore: Any) -> str:
    """LA RIGA DEL PIN DEL VOUCHER, DEFINITA IN UN POSTO SOLO.

    Esiste perche' questa forma la conoscevano in TRE posti -- la pagina che la disegna, la
    rete difensiva che la sorveglia, e `collaudi/gare_micro.py` che la verifica -- ognuno con
    la sua copia. Una cosa vera scritta in piu' posti resta vera solo finche' nessuno ne
    cambia uno: il giorno che lo stile cambia, la rete smette di catturare **in silenzio**.

    Serve anche a chi sorveglia: cercare il PIN come QUATTRO CIFRE NUDE dentro l'HTML e'
    ambiguo, perche' una pagina e' piena di cifre (prezzi, date, totali) e un PIN di 4 cifre
    ci finisce dentro per caso ~1 volta su 1500 (misurato il 2026-08-15). Cercare questa riga
    invece toglie l'ambiguita': o c'e' il PIN messo come PIN, o non c'e'.
    """
    return "<strong style=\"font-size:1.15rem;color:#1e3c72\">%s</strong>" % valore


def pagina_voucher_html(sistema: Any, token: Any, lingua: Any = None) -> Optional[str]:
    """Voucher di conferma (server-rendered, stampabile, multilingua). Verifica la firma
    del token (non falsificabile). None se assente/manomesso/non un voucher.

    LINGUA: quella chiesta nell'URL; se manca o non la parliamo si usa quella FIRMATA
    nel gettone (catturata al book), e solo come ultima spiaggia l'inglese. Mai
    l'italiano per difetto: e' il documento che l'ospite mostra al check-in."""
    import html
    firma = getattr(sistema, "firma", None)
    if firma is None:
        return None
    dati = firma.decodifica(token)
    if not isinstance(dati, dict) or dati.get("tipo") != "voucher":
        return None
    lng = _lingua_pagina(lingua, dati)
    e = html.escape
    prezzo = _importo(dati.get("prezzo_guest_cents", 0), dati.get("valuta", "EUR"))
    # CODICE prenotazione leggibile (BVIP-XXXX-XXXX) + PIN check-in, uguali per cliente e host
    from fase59_concierge import codice_prenotazione
    _ref = str(dati.get("riferimento", ""))
    _codice_pren = codice_prenotazione(_ref)
    _pin_checkin = firma.pin_checkin(_ref)
    # ═══ GATE STATO-PAGAMENTO (correttezza del viaggio cliente, direttiva fondatore) ═══
    # PIN d'accesso, pass serratura, TASTI CONTROVERSIA/segnalazione, chat e check-in online si
    # SBLOCCANO SOLO a pagamento avvenuto (stato 'pagato' = CAPTURED). Prima del pagamento il
    # voucher mostra SOLO riepilogo costi + date + invito a completare il pagamento. Doppia difesa:
    # (1) qui NON si generano i blocchi sensibili se non pagato; (2) guardia fisica a fine funzione.
    _pp_stato = getattr(sistema, "pagamenti_pendenti", None)
    _rec_stato = _pp_stato.info(_ref) if _pp_stato is not None else None
    _pagato = bool(_rec_stato) and _rec_stato.get("stato") == "pagato"
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
    # DIZIONARIO per il JS della pagina: i messaggi che l'ospite legge DOPO un clic
    # (conferme, errori, avvisi) vivevano dentro il codice, in italiano fisso. Ora
    # escono da qui, nella lingua della pagina. ensure_ascii: dentro <script> le entita'
    # HTML non si decodificano, quindi il JSON esce in \uXXXX ed e' sempre sicuro.
    _js_txt = json.dumps(
        {k[len("v_js_"):]: _ui(k, lng) for k in ETICHETTE_UI if k.startswith("v_js_")},
        ensure_ascii=True, sort_keys=True)
    blocco_pass = blocco_pass + ("<script>var BVL=%s;</script>" % _js_txt)
    # cancellazione self-service (token preso dall'URL, niente da incollare)
    blocco_pass = blocco_pass + (
        "<button id='btnCanc' style='margin-top:1.2rem;width:100%;padding:.8rem;border:0;"
        "border-radius:.8rem;background:#b00020;color:#fff;font-weight:700;cursor:pointer'>"
        + e(_ui("v_cancella", lng)) + "</button>"
        "<div id='cancMsg' style='margin-top:.6rem;font-size:.85rem'></div>"
        "<script>document.getElementById('btnCanc').onclick=async function(){"
        "if(!confirm(BVL.conferma_canc))return;"
        "var tk=decodeURIComponent((location.pathname.split('/voucher/')[1]||''));"
        "var r=await fetch('/api/concierge/cancella',{method:'POST',"
        "headers:{'Content-Type':'application/json'},body:JSON.stringify({voucher_token:tk})});"
        "var d=await r.json();var m=document.getElementById('cancMsg');"
        "if(d.stato==='cancellata'){m.style.color='#155724';"
        "m.textContent=BVL.cancellata+' '+(d.rimborso_cents/100).toFixed(2)+' EUR';"
        "this.style.display='none';}else{m.style.color='#b00020';"
        "m.textContent=BVL.canc_ko;}};</script>")
    # Escrow di garanzia: l'ospite conferma "tutto ok" (sblocca il pagamento) o segnala un problema
    blocco_pass = blocco_pass + (
        "<div style='margin-top:1rem;padding-top:1rem;border-top:1px solid #eef2f7'>"
        "<div style='font-size:.82rem;color:#5e6f8d;margin-bottom:.5rem'>"
        + e(_ui("v_dopo_checkin", lng)) + "</div>"
        "<button id='btnOk' style='width:100%;padding:.8rem;border:0;border-radius:.8rem;"
        "background:#155724;color:#fff;font-weight:700;cursor:pointer'>&#10003; "
        + e(_ui("v_tutto_ok", lng)) + "</button>"
        "<button id='btnProblema' style='width:100%;margin-top:.5rem;padding:.7rem;border:0;"
        "border-radius:.8rem;background:#e0a800;color:#1e3c72;font-weight:700;cursor:pointer'>"
        "&#9888; " + e(_ui("v_segnala_problema", lng)) + "</button>"
        "<div id='gMsg' style='margin-top:.6rem;font-size:.85rem'></div></div>"
        "<script>(function(){var tk=decodeURIComponent((location.pathname.split('/voucher/')[1]||''));"
        "function call(p,btn,ok){return async function(){btn.disabled=true;"
        "var r=await fetch(p,{method:'POST',headers:{'Content-Type':'application/json'},"
        "body:JSON.stringify({voucher_token:tk})});var d=await r.json();var m=document.getElementById('gMsg');"
        "if(d&&d.ok){m.style.color='#155724';m.textContent=ok;}else{m.style.color='#b00020';"
        "m.textContent=BVL.op_ko;btn.disabled=false;}};}"
        "document.getElementById('btnOk').onclick=call('/api/garanzia/conferma',document.getElementById('btnOk'),BVL.ok_sbloccato);"
        "document.getElementById('btnProblema').onclick=call('/api/garanzia/contesta',document.getElementById('btnProblema'),BVL.segnalato);"
        "})();</script>")
    # CHAT COL TUO HOST + PROVE FOTO (per chiarire; in controversia le vede anche l'arbitro)
    blocco_pass = blocco_pass + (
        "<div style='margin-top:1rem;padding-top:1rem;border-top:1px solid #eef2f7'>"
        "<div style='font-size:.82rem;color:#5e6f8d;margin-bottom:.5rem'>&#128172; "
        + e(_ui("v_chat_intro", lng)) + "</div>"
        "<div id='chBox' style='max-height:180px;overflow-y:auto;font-size:.85rem;"
        "background:#f7faf8;border-radius:.6rem;padding:.5rem .7rem;margin-bottom:.45rem'></div>"
        "<textarea id='chTxt' rows='2' placeholder=\"" + e(_ui("v_scrivi_ph", lng))
        + "\" style='width:100%;"
        "padding:.55rem;border:1px solid #dce1ed;border-radius:.6rem'></textarea>"
        "<div style='display:flex;gap:2%;margin-top:.4rem'>"
        "<button id='chSend' style='flex:1;padding:.6rem;border:0;border-radius:.7rem;"
        "background:#0f4c3a;color:#fff;font-weight:700;cursor:pointer'>"
        + e(_ui("v_invia", lng)) + "</button>"
        "<label style='flex:1;display:block;text-align:center;padding:.6rem;border-radius:.7rem;"
        "background:#eef7f2;color:#0f4c3a;font-weight:700;cursor:pointer'>&#128206; "
        + e(_ui("v_foto_prova", lng)) +
        "<input id='chFile' type='file' accept='image/*' style='display:none'></label></div>"
        "<div id='chMsg' style='margin-top:.4rem;font-size:.82rem'></div></div>"
        "<script>(function(){var tk=decodeURIComponent((location.pathname.split('/voucher/')[1]||''));"
        "function esc(x){return String(x).replace(/[<>&]/g,function(c){return {'<':'&lt;','>':'&gt;','&':'&amp;'}[c];});}"
        "function rendi(ms){var b=document.getElementById('chBox');"
        "b.innerHTML=(ms||[]).map(function(m){var mio=(m.mittente==='ospite');"
        "var t=esc(m.testo||'');t=t.replace(/(\\/uploads\\/[a-z0-9]+\\.[a-z]+)/g,"
        "\"<a href='$1' target='_blank'>&#128247; \"+BVL.apri_foto+\"</a>\");"
        "return \"<div style='margin:.2rem 0;text-align:\"+(mio?'right':'left')+\"'><span style='display:inline-block;"
        "padding:.3rem .6rem;border-radius:.7rem;background:\"+(mio?'#d7e8e0':'#fff')+\"'>\"+t+\"</span></div>\";}).join('')"
        "||\"<span style='color:#8a9bb5'>\"+BVL.nessun_msg+\"</span>\";b.scrollTop=b.scrollHeight;}"
        "function carica(){fetch('/api/voucher/messaggi?voucher_token='+encodeURIComponent(tk))"
        ".then(function(r){return r.json();}).then(function(d){rendi(d.messaggi);});}"
        "document.getElementById('chSend').onclick=async function(){var t=document.getElementById('chTxt').value.trim();"
        "if(!t)return;var r=await fetch('/api/voucher/messaggio',{method:'POST',headers:{'Content-Type':'application/json'},"
        "body:JSON.stringify({voucher_token:tk,testo:t})});if(r.status===201){document.getElementById('chTxt').value='';carica();}};"
        "document.getElementById('chFile').onchange=function(){var f=this.files[0];if(!f)return;"
        "var rd=new FileReader();rd.onload=async function(){"
        "var r=await fetch('/api/voucher/prova',{method:'POST',headers:{'Content-Type':'application/json'},"
        "body:JSON.stringify({voucher_token:tk,image_base64:rd.result})});"
        "var m=document.getElementById('chMsg');if(r.status===201){m.style.color='#155724';"
        "m.textContent='\\u2713 '+BVL.prova_ok;carica();}"
        "else{var em=BVL.foto_ko;"
        "if(r.status===429)em=BVL.foto_limite;"
        "else if(r.status>=500)em=BVL.riprova;"
        "m.style.color='#b00020';m.textContent=em;}};"
        "rd.readAsDataURL(f);};carica();})();</script>")
    # CHECK-IN DIGITALE (fase127): pre-registrazione ospiti prima dell'arrivo -> sblocco ok
    blocco_pass = blocco_pass + (
        "<div id='ckBox' style='margin-top:1rem;padding-top:1rem;border-top:1px solid #eef2f7'>"
        "<div style='font-size:.82rem;color:#5e6f8d;margin-bottom:.5rem'>"
        + e(_ui("v_checkin_online", lng)) + "</div>"
        "<div id='ckList' style='font-size:.85rem;margin-bottom:.4rem'></div>"
        "<input id='ckNome' placeholder=\"" + e(_ui("v_nome_ph", lng))
        + "\" style='width:100%;padding:.55rem;"
        "border:1px solid #dce1ed;border-radius:.6rem;margin-bottom:.35rem'>"
        "<input id='ckDoc' placeholder=\"" + e(_ui("v_doc_ph", lng))
        + "\" style='width:100%;padding:.55rem;"
        "border:1px solid #dce1ed;border-radius:.6rem;margin-bottom:.45rem'>"
        "<button id='ckAdd' style='width:49%;padding:.6rem;border:0;border-radius:.7rem;"
        "background:#eef2f7;color:#1e3c72;font-weight:700;cursor:pointer'>"
        + e(_ui("v_aggiungi", lng)) + "</button> "
        "<button id='ckSend' style='width:49%;padding:.6rem;border:0;border-radius:.7rem;"
        "background:#1e3c72;color:#fff;font-weight:700;cursor:pointer'>"
        + e(_ui("v_invia_checkin", lng)) + "</button>"
        "<div id='ckMsg' style='margin-top:.5rem;font-size:.85rem'></div></div>"
        "<script>(function(){var tk=decodeURIComponent((location.pathname.split('/voucher/')[1]||''));"
        "var os=[];function rend(){document.getElementById('ckList').textContent="
        "os.length?os.map(function(o){return o.nome;}).join(', '):'';}"
        "fetch('/api/checkin/stato?voucher_token='+encodeURIComponent(tk)).then(function(r){return r.json();})"
        ".then(function(d){if(d&&d.completato){document.getElementById('ckBox').innerHTML="
        "\"<div style='color:#155724;font-weight:700'>&#10003; \"+BVL.ck_completato+\"</div>\";}});"
        "document.getElementById('ckAdd').onclick=function(){var n=document.getElementById('ckNome').value.trim(),"
        "c=document.getElementById('ckDoc').value.trim();if(!n||!c)return;os.push({nome:n,documento:c});"
        "document.getElementById('ckNome').value='';document.getElementById('ckDoc').value='';rend();};"
        "document.getElementById('ckSend').onclick=async function(){"
        "var n=document.getElementById('ckNome').value.trim(),c=document.getElementById('ckDoc').value.trim();"
        "if(n&&c){os.push({nome:n,documento:c});rend();}"
        "if(!os.length){document.getElementById('ckMsg').textContent=BVL.ck_almeno_uno;return;}"
        "var r=await fetch('/api/checkin/pre_registra',{method:'POST',headers:{'Content-Type':'application/json'},"
        "body:JSON.stringify({voucher_token:tk,ospiti:os})});var d=await r.json();"
        "var m=document.getElementById('ckMsg');if(d&&d.ok){m.style.color='#155724';"
        "m.textContent='\\u2713 '+BVL.ck_ok;}"
        "else{m.style.color='#b00020';m.textContent=BVL.ck_ko;}};"
        "})();</script>")
    # RECENSIONE POST-SOGGIORNO stile Booking/Agoda (fase63, 2026-07-20): voto generale +
    # sotto-voti (pulizia, comfort, ...). Il form appare SOLO dopo il check-out e solo se la
    # prenotazione non e' cancellata; il diritto firmato (nbf=check-out) e' emesso QUI dal
    # server e incorporato nella pagina: l'ospite non copia nulla. Gia' recensita -> grazie.
    try:
        _rif_v = str(dati.get("riferimento", ""))
        _allog_v = str(dati.get("alloggio_id", ""))
        _co_v = str(dati.get("check_out", ""))
        _reg = getattr(sistema, "recensioni", None)
        _emet = getattr(sistema, "emettitore_recensioni", None)
        if _reg is not None and _emet is not None and _rif_v and _allog_v and _co_v:
            import datetime as _dtv
            import json as _jsv
            _co_data = _dtv.date.fromisoformat(_co_v)
            _cancellata = False
            try:
                _pp = getattr(sistema, "pagamenti_pendenti", None)
                _st = _pp.info(_rif_v) if _pp is not None else None
                _cancellata = bool(_st is not None and _st.get("stato")
                                   in ("rimborsato", "cancellata_host"))
            except Exception:
                _cancellata = False
            if _dtv.date.today() >= _co_data and not _cancellata:
                if _reg.gia_recensita(_rif_v):
                    blocco_pass = blocco_pass + (
                        "<div style='margin-top:1rem;padding-top:1rem;border-top:1px solid "
                        "#eef2f7;color:#155724;font-weight:700'>&#11088; %s</div>"
                        % e(_ui("rec_grazie", lng)))
                else:
                    _nbf = int(_dtv.datetime.combine(_co_data, _dtv.time.min).timestamp())
                    _diritto = _emet.emetti(_rif_v, _allog_v, non_prima_ts=_nbf)
                    _cats = _jsv.dumps(
                        [[c, _ui("rec_" + c, lng)] for c in
                         ("pulizia", "comfort", "posizione", "servizi", "host",
                          "qualita_prezzo")], ensure_ascii=True)
                    # testi per il JS via JSON (dentro <script> le entita' HTML NON si
                    # decodificano: un apostrofo escapato romperebbe la stringa)
                    _txt = _jsv.dumps({"gen": _ui("rec_generale", lng),
                                       "grazie": _ui("rec_grazie", lng),
                                       "err": _ui("errore", lng),
                                       "tok": _diritto, "lng": lng}, ensure_ascii=True)
                    blocco_pass = blocco_pass + (
                        "<div id='recBox' style='margin-top:1rem;padding-top:1rem;"
                        "border-top:1px solid #eef2f7'>"
                        "<div style='font-weight:700;margin-bottom:.5rem'>&#11088; " + e(_ui("rec_titolo", lng)) + "</div>"
                        "<div id='recRows'></div>"
                        "<textarea id='recTxt' rows='3' maxlength='2000' placeholder='" + e(_ui("rec_testo_ph", lng)) + "' "
                        "style='width:100%;padding:.55rem;border:1px solid #dce1ed;border-radius:.6rem;margin-top:.5rem'></textarea>"
                        "<button id='recSend' style='width:100%;margin-top:.5rem;padding:.8rem;border:0;border-radius:.8rem;"
                        "background:#0f4c3a;color:#fff;font-weight:700;cursor:pointer'>" + e(_ui("rec_invia", lng)) + "</button>"
                        "<div id='recMsg' style='margin-top:.5rem;font-size:.85rem'></div></div>"
                        "<script>(function(){"
                        "var TXT=" + _txt + ";"
                        "var CATS=" + _cats + ";var voti={gen:0},rows=document.getElementById('recRows');"
                        "function riga(k,lbl){var d=document.createElement('div');"
                        "d.style.cssText='display:flex;justify-content:space-between;align-items:center;margin:.15rem 0';"
                        "var s=document.createElement('span');s.textContent=lbl;"
                        "if(k==='gen')s.style.fontWeight='700';d.appendChild(s);"
                        "var box=document.createElement('span');"
                        "for(var i=1;i<=5;i++){(function(v){var b=document.createElement('button');"
                        "b.type='button';b.textContent='\\u2606';"
                        "b.style.cssText='border:0;background:none;font-size:1.25rem;cursor:pointer;"
                        "padding:.05rem .1rem;color:#c9c9c9';"
                        "b.onclick=function(){voti[k]=v;var bs=box.children;"
                        "for(var j=0;j<5;j++){bs[j].textContent=(j<v)?'\\u2605':'\\u2606';"
                        "bs[j].style.color=(j<v)?'#e0a800':'#c9c9c9';}};"
                        "box.appendChild(b);})(i);}d.appendChild(box);rows.appendChild(d);}"
                        "riga('gen',TXT.gen);for(var i=0;i<CATS.length;i++)riga(CATS[i][0],CATS[i][1]);"
                        "function grazie(){var b=document.getElementById('recBox');b.innerHTML='';"
                        "var w=document.createElement('div');w.style.cssText='color:#155724;font-weight:700';"
                        "w.textContent='\\u2B50 '+TXT.grazie;b.appendChild(w);}"
                        "document.getElementById('recSend').onclick=async function(){"
                        "var m=document.getElementById('recMsg');"
                        "if(!voti.gen){m.style.color='#b00020';m.textContent=TXT.gen+': \\u2605 1-5';return;}"
                        "this.disabled=true;var cats={};"
                        "for(var i=0;i<CATS.length;i++){var k=CATS[i][0];if(voti[k])cats[k]=voti[k];}"
                        "try{var r=await fetch('/api/recensioni',{method:'POST',"
                        "headers:{'Content-Type':'application/json'},body:JSON.stringify("
                        "{token:TXT.tok,voto:voti.gen,testo:document.getElementById('recTxt').value.trim(),"
                        "lingua:TXT.lng,categorie:cats})});"
                        "if(r.status===201||r.status===409){grazie();}"
                        "else{m.style.color='#b00020';m.textContent=TXT.err;this.disabled=false;}"
                        "}catch(_){m.style.color='#b00020';m.textContent=TXT.err;this.disabled=false;}};"
                        "})();</script>")
    except Exception:
        logger.warning("blocco recensione voucher fallito (ISOLATO)", exc_info=True)
    # RICEVUTA DI PAGAMENTO (C3 2026-07-20): link visibile SOLO se risulta pagata
    # (la pagina /ricevuta/ rifiuta comunque le non pagate: doppia guardia).
    try:
        _ppr = getattr(sistema, "pagamenti_pendenti", None)
        _rr = _ppr.info(str(dati.get("riferimento", ""))) if _ppr is not None else None
        if _rr is not None and _rr.get("stato") == "pagato":
            from urllib.parse import quote as _q
            blocco_pass = blocco_pass + (
                "<a href='/ricevuta/%s' style='display:block;margin-top:1rem;"
                "text-align:center;padding:.7rem;border-radius:.8rem;background:#eef7f2;"
                "color:#0f4c3a;font-weight:700;text-decoration:none'>&#129534; "
                + e(_ui("v_ricevuta", lng)) + "</a>") % _q(str(token), safe="")
    except Exception:
        logger.warning("link ricevuta voucher fallito (ISOLATO)", exc_info=True)
    # PAGA IN STRUTTURA: se questa prenotazione e' "in struttura" (firmato nel token), mostra
    # il SALDO da pagare all'host DI PERSONA all'arrivo + quanto e' gia' stato pagato online.
    # E' cio' che l'host legge sul voucher per sapere quanto incassare. Assente sull'online.
    blocco_saldo = ""
    _modo_v = str(dati.get("modo_pagamento", ""))
    _saldo_v = dati.get("saldo_in_loco_cents", 0)
    if _modo_v == "in_struttura" and isinstance(_saldo_v, int) and not isinstance(_saldo_v, bool) \
            and _saldo_v > 0:
        _val_v = str(dati.get("valuta", "EUR"))
        _ant_v = dati.get("anticipo_online_cents", 0)
        _ant_v = _ant_v if isinstance(_ant_v, int) and not isinstance(_ant_v, bool) else 0
        blocco_saldo = (
            "<div class=\"r\"><span>%s</span><strong>%s %s</strong></div>"
            "<div style='margin-top:.5rem;padding:.7rem .8rem;background:#fff4e5;"
            "border:1px solid #ffd9a8;border-radius:.8rem;color:#8a5200'>"
            "<div style='font-size:.8rem'>%s</div>"
            "<strong style='font-size:1.15rem'>%s %s</strong></div>"
        ) % (e(_ui("ps_anticipo_pagato", lng)), e(_importo(_ant_v, _val_v)), e(_val_v),
             e(_ui("ps_saldo_nota", lng)), e(_importo(_saldo_v, _val_v)), e(_val_v))
    if not _pagato:
        # NON pagato: niente PIN, niente controversia, niente check-in — solo l'invito a pagare.
        blocco_pass = ("<div style='margin-top:1.2rem;padding:1rem;background:#fff6e6;"
                       "border:1px solid #ffd9a8;border-radius:.9rem;color:#8a5200;text-align:center'>"
                       "<strong>" + e(_ui("v_completa_prima", lng)) + "</strong><br>"
                       "<span style='font-size:.9rem'>"
                       + e(_ui("v_pin_dopo_pagamento", lng)) + "</span></div>")
    pagina = (
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
        "<div class=\"r\"><span>%s</span>%s</div>"
        "<div class=\"r\"><span>%s</span><strong>%s</strong></div>"
        "<div class=\"r\"><span>%s</span><strong>%s</strong></div>"
        "<div class=\"r\"><span>%s</span><strong>%s %s</strong></div>"
        "%s"
        "%s</div></body></html>"
    ) % (
        e(lng), e(_ui("voucher_ok", lng)),
        e(_ui("rif", lng)), e(_codice_pren),
        e(_ui("v_pin_label", lng)),
        riga_pin_voucher(e(_pin_checkin) if _pagato else "\U0001F512"),  # PIN SOLO se pagato
        e(_ui("dal", lng)), e(str(dati.get("check_in", ""))),
        e(_ui("al", lng)), e(str(dati.get("check_out", ""))),
        e(_ui("totale", lng)), e(prezzo), e(str(dati.get("valuta", "EUR"))),
        blocco_saldo,
        blocco_pass,
    )
    # ═══ GUARDIA FISICA (direttiva fondatore): un voucher NON pagato non deve MAI contenere il PIN
    # reale né i tasti di controversia/garanzia. Se — per qualunque motivo — trapelassero, li togliamo
    # e lo denunciamo nei log. Con il gate a monte questa non scatta mai: è la seconda rete.
    # ⛔ Si cerca la RIGA del PIN, non le quattro cifre nude: una pagina e' piena di cifre e un
    # PIN di 4 ci finisce dentro per caso (~1 su 1500, misurato il 2026-08-15). Col confronto
    # ingenuo questa rete gridava al lupo su pagine sane E sostituiva il prezzo o la data che
    # aveva coinciso -- cioe' corrompeva un numero che l'ospite legge, per difendersi da niente.
    _pin_esposto = riga_pin_voucher(_pin_checkin)
    if not _pagato and (_pin_esposto in pagina or "/api/garanzia/" in pagina):
        logger.error("VOUCHER non pagato con PIN/controversia esposti (rif=%s): rimozione difensiva", _ref)
        pagina = pagina.replace(_pin_esposto, riga_pin_voucher("\U0001F512")).replace("/api/garanzia/", "#")
    return pagina


def pagina_ricevuta_html(sistema: Any, token: Any, lingua: Any = None) -> Optional[str]:
    """RICEVUTA DI PAGAMENTO stampabile (C3 2026-07-20: prima chi pagava con soldi veri
    non riceveva alcun documento). Autenticata dal voucher firmato, SOLO prenotazioni
    PAGATE. Nota onesta in calce: non è una fattura fiscale (quella arriverà col regime
    IVA del gestore). None se token invalido o non pagata.

    LINGUA: non ne aveva nessuna — la prova di pagamento usciva in italiano anche per
    chi aveva prenotato in giapponese. Ora segue la stessa gerarchia del voucher
    (URL -> lingua firmata nel gettone -> inglese)."""
    import html as _h
    firma = getattr(sistema, "firma", None)
    if firma is None:
        return None
    v = firma.decodifica(token)
    if not isinstance(v, dict) or v.get("tipo") != "voucher":
        return None
    lng = _lingua_pagina(lingua, v)
    rif = str(v.get("riferimento", ""))
    pp = getattr(sistema, "pagamenti_pendenti", None)
    rec = pp.info(rif) if pp is not None else None
    if rec is None or rec.get("stato") != "pagato":
        return None
    import json as _j
    try:
        dj = _j.loads(rec.get("corpo_json") or "{}")
    except Exception:
        dj = {}
    e = _h.escape
    from fase59_concierge import codice_prenotazione
    valuta = dj.get("valuta") or v.get("valuta", "EUR")

    def soldi(c):
        try:
            c = int(c)
        except Exception:
            c = 0
        return _importo(c, valuta) + " " + str(valuta or "EUR")

    totale = int(dj.get("prezzo_guest_cents", 0) or v.get("prezzo_guest_cents", 0) or 0)
    tassa = int(v.get("tassa_soggiorno_cents", 0) or 0)
    soggiorno = max(0, totale - tassa)
    righe = ("<div class='r'><span>%s</span><strong>%s</strong></div>"
             % (e(_ui("ric_soggiorno", lng)), e(soldi(soggiorno)))
             + (("<div class='r'><span>%s</span><strong>%s</strong></div>"
                 % (e(_ui("tassa", lng)), e(soldi(tassa)))) if tassa else "")
             + "<div class='r' style='font-size:1.1rem'><span><strong>%s</strong>"
               "</span><strong>%s</strong></div>"
               % (e(_ui("ric_totale_pagato", lng)), e(soldi(totale))))
    return (
        "<!DOCTYPE html><html lang=\"%s\"><head><meta charset=\"UTF-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>%s · BookinVIP</title><style>body{font-family:system-ui,sans-serif;"
        "background:#f4f6fa;color:#1a1e2b;padding:2rem;max-width:480px;margin:0 auto}"
        ".v{background:#fff;border-radius:1.5rem;padding:2rem;box-shadow:0 8px 24px "
        "rgba(0,0,0,.06)}h1{color:#0f4c3a;font-size:1.3rem}.r{display:flex;"
        "justify-content:space-between;padding:.3rem 0;border-bottom:1px solid #eef2f7}"
        "@media print{body{background:#fff}.noprint{display:none}}</style></head><body>"
        "<div class=\"v\">"
        "<div style=\"font-weight:700;color:#0f4c3a;font-size:1.2rem\">BookinVIP</div>"
        "<h1>🧾 %s</h1>"
        "<div class=\"r\"><span>%s</span><strong>%s</strong></div>"
        "<div class=\"r\"><span>%s</span><strong>%s</strong></div>"
        "<div class=\"r\"><span>%s</span><strong>%s</strong></div>"
        "<div class=\"r\"><span>%s</span><strong>%s</strong></div>"
        "%s"
        "<p style=\"color:#5e6f8d;font-size:.82rem;margin-top:1rem\">%s "
        "Edil Max di Foti Massimo — P.IVA 11795700969 — "
        "Via Paletro 11, 20821 Meda (MB) — info@bookinvip.com.<br>%s</p>"
        "<button class=\"noprint\" onclick=\"window.print()\" style=\"width:100%%;padding:.7rem;"
        "border:0;border-radius:.8rem;background:#0f4c3a;color:#fff;font-weight:700;"
        "cursor:pointer\">🖨️ %s</button>"
        "</div></body></html>"
    ) % (e(lng), e(_ui("v_ricevuta", lng)), e(_ui("v_ricevuta", lng)),
         e(_ui("rif", lng)), e(codice_prenotazione(rif)),
         e(_ui("ric_alloggio", lng)), e(dj.get("titolo") or rec.get("alloggio_id", "")),
         e(_ui("dal", lng)), e(str(v.get("check_in", ""))),
         e(_ui("al", lng)), e(str(v.get("check_out", ""))), righe,
         e(_ui("ric_nota_stripe", lng)), e(_ui("ric_nota_fattura", lng)),
         e(_ui("ric_stampa", lng)))


def pagina_recensione_html(sistema: Any, token: Any, lingua: Any = None) -> Optional[str]:
    """PAGINA DI SOLA VALUTAZIONE (2026-07-20). Il cliente ci arriva dall'email
    post-soggiorno e vede SOLTANTO la valutazione — voto generale + categorie — senza
    voucher/cancella/prezzo/check-in/chat. Usa lo STESSO motore (fase63) e lo STESSO
    endpoint /api/recensioni del voucher: cambia solo la VETRINA, non il meccanismo. Il
    diritto firmato (nbf=check-out) e' emesso qui dal server (il cliente non copia nulla).
    Il voucher NON viene toccato. None se il token non e' un voucher valido (la rotta
    mostra la pagina gentile)."""
    import html
    firma = getattr(sistema, "firma", None)
    if firma is None:
        return None
    dati = firma.decodifica(token)
    if not isinstance(dati, dict) or dati.get("tipo") != "voucher":
        return None
    lng = _lingua_pagina(lingua, dati)
    e = html.escape
    rif = str(dati.get("riferimento", ""))
    allog = str(dati.get("alloggio_id", ""))
    co = str(dati.get("check_out", ""))
    reg = getattr(sistema, "recensioni", None)
    emet = getattr(sistema, "emettitore_recensioni", None)
    if reg is None or emet is None or not (rif and allog and co):
        return None
    import datetime as _dtv
    import json as _jsv
    try:
        co_data = _dtv.date.fromisoformat(co)
    except Exception:
        return None
    # titolo + stato dalla STESSA fonte della ricevuta (una sola query)
    titolo, cancellata = allog, False
    try:
        pp = getattr(sistema, "pagamenti_pendenti", None)
        st = pp.info(rif) if pp is not None else None
        if st:
            titolo = _jsv.loads(st.get("corpo_json") or "{}").get("titolo") or allog
            cancellata = st.get("stato") in ("rimborsato", "cancellata_host")
    except Exception:
        pass
    # corpo centrale: "dopo il soggiorno" / gia' fatta / il form (STESSO del voucher)
    if _dtv.date.today() < co_data or cancellata:
        corpo = "<p style='color:#5e6f8d'>%s</p>" % e(_ui("rec_dopo_soggiorno", lng))
    elif reg.gia_recensita(rif):
        corpo = ("<div style='color:#155724;font-weight:800;font-size:1.1rem'>"
                 "&#11088; %s</div>" % e(_ui("rec_grazie", lng)))
    else:
        nbf = int(_dtv.datetime.combine(co_data, _dtv.time.min).timestamp())
        diritto = emet.emetti(rif, allog, non_prima_ts=nbf)   # STESSA emissione del voucher
        cats = _jsv.dumps([[c, _ui("rec_" + c, lng)] for c in
                           ("pulizia", "comfort", "posizione", "servizi", "host",
                            "qualita_prezzo")], ensure_ascii=True)
        txt = _jsv.dumps({"gen": _ui("rec_generale", lng), "grazie": _ui("rec_grazie", lng),
                          "err": _ui("errore", lng), "tok": diritto, "lng": lng},
                         ensure_ascii=True)
        corpo = (
            "<div id='recBox'><div id='recRows'></div>"
            "<textarea id='recTxt' rows='3' maxlength='2000' placeholder='" + e(_ui("rec_testo_ph", lng)) + "' "
            "style='width:100%;padding:.6rem;border:1px solid #dce1ed;border-radius:.6rem;margin-top:.8rem'></textarea>"
            "<button id='recSend' style='width:100%;margin-top:.6rem;padding:.9rem;border:0;border-radius:.8rem;"
            "background:#0f4c3a;color:#fff;font-weight:800;font-size:1rem;cursor:pointer'>" + e(_ui("rec_invia", lng)) + "</button>"
            "<div id='recMsg' style='margin-top:.6rem;font-size:.9rem'></div></div>"
            "<script>(function(){var TXT=" + txt + ";var CATS=" + cats + ";"
            "var voti={gen:0},rows=document.getElementById('recRows');"
            "function riga(k,lbl){var d=document.createElement('div');"
            "d.style.cssText='display:flex;justify-content:space-between;align-items:center;margin:.35rem 0';"
            "var s=document.createElement('span');s.textContent=lbl;"
            "if(k==='gen'){s.style.fontWeight='800';s.style.fontSize='1.05rem';}d.appendChild(s);"
            "var box=document.createElement('span');"
            "for(var i=1;i<=5;i++){(function(v){var b=document.createElement('button');"
            "b.type='button';b.textContent='\\u2606';"
            "b.style.cssText='border:0;background:none;font-size:1.5rem;cursor:pointer;padding:.05rem .12rem;color:#c9c9c9';"
            "b.onclick=function(){voti[k]=v;var bs=box.children;"
            "for(var j=0;j<5;j++){bs[j].textContent=(j<v)?'\\u2605':'\\u2606';"
            "bs[j].style.color=(j<v)?'#e0a800':'#c9c9c9';}};"
            "box.appendChild(b);})(i);}d.appendChild(box);rows.appendChild(d);}"
            "riga('gen',TXT.gen);for(var i=0;i<CATS.length;i++)riga(CATS[i][0],CATS[i][1]);"
            "function grazie(){var b=document.getElementById('recBox');b.innerHTML='';"
            "var w=document.createElement('div');w.style.cssText='color:#155724;font-weight:800;font-size:1.1rem';"
            "w.textContent='\\u2B50 '+TXT.grazie;b.appendChild(w);}"
            "document.getElementById('recSend').onclick=async function(){"
            "var m=document.getElementById('recMsg');"
            "if(!voti.gen){m.style.color='#b00020';m.textContent=TXT.gen+': \\u2605 1-5';return;}"
            "this.disabled=true;var cats={};"
            "for(var i=0;i<CATS.length;i++){var k=CATS[i][0];if(voti[k])cats[k]=voti[k];}"
            "try{var r=await fetch('/api/recensioni',{method:'POST',"
            "headers:{'Content-Type':'application/json'},body:JSON.stringify("
            "{token:TXT.tok,voto:voti.gen,testo:document.getElementById('recTxt').value.trim(),"
            "lingua:TXT.lng,categorie:cats})});"
            "if(r.status===201||r.status===409){grazie();}"
            "else{m.style.color='#b00020';m.textContent=TXT.err;this.disabled=false;}"
            "}catch(_){m.style.color='#b00020';m.textContent=TXT.err;this.disabled=false;}};"
            "})();</script>")
    dom = _ui("rec_domanda", lng)
    nota = _ui("rec_solo_veri", lng)
    return (
        "<!DOCTYPE html><html lang=\"%s\"><head><meta charset=\"UTF-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<meta name=\"robots\" content=\"noindex\">"
        "<title>%s</title><style>body{font-family:system-ui,sans-serif;"
        "background:#f4f6fa;color:#1a1e2b;padding:2rem;max-width:440px;margin:0 auto}"
        ".v{background:#fff;border-radius:1.5rem;padding:2rem;box-shadow:0 8px 24px "
        "rgba(0,0,0,.06)}.bm{font-weight:800;color:#0f4c3a;font-size:1.2rem}"
        "h1{color:#0f4c3a;font-size:1.25rem;line-height:1.3;margin:.6rem 0 1.2rem}"
        "</style></head><body><div class=\"v\"><div class=\"bm\">BookinVIP</div>"
        "<h1>&#11088; %s %s?</h1>%s"
        "<p style=\"color:#8a9bb5;font-size:.8rem;margin-top:1.4rem\">%s</p>"
        "</div></body></html>"
    ) % (e(lng), e(_ui("rec_titolo", lng)), e(dom), e(titolo), corpo, e(nota))


def pagina_voucher_non_valido_html(lingua: str = "en") -> str:
    """Pagina GENTILE quando un link voucher non è valido/scaduto/manomesso (invece di un
    errore tecnico): rassicura e indirizza il cliente. In tutte e 8 le lingue.

    Era bilingue it/en con una regola sola — «comincia per en? inglese, altrimenti
    ITALIANO» — quindi un tedesco, un giapponese o un cinese col link rotto leggevano
    italiano. Ora ogni lingua ha il suo testo e l'ignota ripiega sull'inglese."""
    lng = _lingua_pagina(lingua)
    tit = _ui("lnv_titolo", lng)
    h1 = _ui("lnv_h1", lng)
    p1 = _ui("lnv_p1", lng)
    p2 = _ui("lnv_p2", lng)
    mail = "info@bookinvip.com"
    home = _ui("lnv_home", lng)
    return (
        "<!DOCTYPE html><html lang=\"%s\"><head><meta charset=\"UTF-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>%s · BookinVIP</title><style>body{font-family:system-ui,-apple-system,"
        "Segoe UI,sans-serif;background:#f4f6fb;color:#1e2b45;margin:0;min-height:100vh;"
        "display:flex;align-items:center;justify-content:center;padding:1.2rem}"
        ".c{background:#fff;border-radius:1.5rem;box-shadow:0 12px 40px rgba(20,40,80,.1);"
        "padding:2.4rem 2rem;max-width:460px;text-align:center}"
        ".logo{font-weight:800;font-size:1.4rem;color:#1e3c72;margin-bottom:1rem}"
        ".i{width:74px;height:74px;border-radius:50%%;background:#fff4e5;color:#8a5200;"
        "display:flex;align-items:center;justify-content:center;font-size:2.3rem;margin:0 auto 1rem}"
        "h1{font-size:1.35rem;margin:.2rem 0 .6rem}p{color:#5e6f8d;line-height:1.6;margin:.4rem 0}"
        "a.b{display:inline-block;margin-top:1.2rem;background:#1e3c72;color:#fff;"
        "text-decoration:none;padding:.7rem 1.5rem;border-radius:2rem;font-weight:600}"
        "a.m{color:#1e3c72;font-weight:600}</style></head><body><div class=\"c\">"
        "<div class=\"logo\">BookinVIP</div><div class=\"i\">🔎</div><h1>%s</h1>"
        "<p>%s</p><p>%s</p><p><a class=\"m\" href=\"mailto:%s\">%s</a></p>"
        "<a class=\"b\" href=\"/\">%s</a></div></body></html>"
    ) % (lng, tit, h1, p1, p2, mail, mail, home)


def pagina_azione_html(esito: Dict[str, Any]) -> str:
    """Pagina GENTILE dopo che l'host clicca Approva/Rifiuta da un messaggio. Verde=approvata,
    rossa=rifiutata, arancio=link scaduto/già gestito."""
    ok = bool(esito.get("ok"))
    stato = esito.get("stato")
    if ok and stato == "approvata":
        col, bg, ic, h1 = "#155724", "#d4edda", "✅", "Prenotazione approvata"
        p1 = "Ottimo! Il calendario e il tuo pannello si aggiornano da soli."
        p2 = "Il cliente riceve la conferma. Non devi fare altro."
    elif ok and stato == "rifiutata":
        col, bg, ic, h1 = "#842029", "#f8d7da", "✖️", "Prenotazione rifiutata"
        p1 = "La richiesta è stata rifiutata e le date sono di nuovo libere."
        p2 = "Puoi gestire tutto dal tuo pannello host quando vuoi."
    else:
        col, bg, ic = "#8a5200", "#fff4e5", "⚠️"
        motivo = esito.get("motivo", "")
        if motivo == "link_scaduto":
            h1, p1 = "Link scaduto", "Questo link non è più valido (oltre le 24h)."
        elif motivo == "pagamento_non_disponibile":
            h1 = "Riprova tra qualche minuto"
            p1 = ("Non siamo riusciti a preparare il pagamento per il cliente (servizio "
                  "momentaneamente non disponibile). La richiesta è ancora lì: riapri il "
                  "link e riprova tra poco.")
        elif motivo == "richiesta_non_trovata":
            h1, p1 = "Richiesta già gestita", "Questa richiesta è già stata approvata, rifiutata o è scaduta."
        elif motivo == "non_tua":
            h1, p1 = "Non autorizzato", "Questo link non corrisponde al tuo account."
        else:
            h1, p1 = "Link non valido", "Non riusciamo a leggere questo link."
        p2 = "Apri il pannello host per gestire le tue prenotazioni."
    pannello = "https://bookinvip.com/host.html"
    return (
        "<!DOCTYPE html><html lang=\"it\"><head><meta charset=\"UTF-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>%s · BookinVIP</title><style>body{font-family:system-ui,-apple-system,"
        "Segoe UI,sans-serif;background:#f4f6fb;color:#1e2b45;margin:0;min-height:100vh;"
        "display:flex;align-items:center;justify-content:center;padding:1.2rem}"
        ".c{background:#fff;border-radius:1.5rem;box-shadow:0 12px 40px rgba(20,40,80,.1);"
        "padding:2.4rem 2rem;max-width:460px;text-align:center}"
        ".logo{font-weight:800;font-size:1.4rem;color:#1e3c72;margin-bottom:1rem}"
        ".i{width:74px;height:74px;border-radius:50%%;background:%s;color:%s;"
        "display:flex;align-items:center;justify-content:center;font-size:2.3rem;margin:0 auto 1rem}"
        "h1{font-size:1.35rem;margin:.2rem 0 .6rem}p{color:#5e6f8d;line-height:1.6;margin:.4rem 0}"
        "a.b{display:inline-block;margin-top:1.2rem;background:#1e3c72;color:#fff;"
        "text-decoration:none;padding:.7rem 1.5rem;border-radius:2rem;font-weight:600}"
        "</style></head><body><div class=\"c\"><div class=\"logo\">BookinVIP</div>"
        "<div class=\"i\">%s</div><h1>%s</h1><p>%s</p><p>%s</p>"
        "<a class=\"b\" href=\"%s\">Vai al pannello host</a></div></body></html>"
    ) % (h1, bg, col, ic, h1, p1, p2, pannello)


def pagina_login_gate(livello: str, base_url: str = "") -> str:
    """PAGINA DI LOGIN pubblica del gatekeeper (server-rendered). Contiene SOLO il form del
    ruolo: nessun bottone/struttura della dashboard finisce nel sorgente per chi non è loggato.
    Al successo salva la credenziale dove la dashboard la cerca (localStorage/sessionStorage) e
    reindirizza: così le dashboard esistenti restano invariate. Marcata no-store dall'handler."""
    if livello not in ("admin", "host", "bunker"):
        livello = "host"
    # (titolo, sottotitolo, HTML dei campi, JS di invio) per ruolo
    sotto = sotto_js = ""          # footer (Registrati / Password dimenticata) — solo per l'host
    if livello == "admin":
        titolo, sub = "Area amministrazione", "Accesso riservato"
        campi = ('<input id="k" type="password" placeholder="Chiave admin" '
                 'autocomplete="current-password" aria-label="Chiave admin">')
        js = ("var k=document.getElementById('k').value;"
              "if(!k){msg('Inserisci la chiave.');return;}btn(true);try{"
              "var r=await fetch('/api/admin/login',{method:'POST',headers:{'X-Admin-Key':k}});"
              "if(r.status===200){try{localStorage.setItem('bookinvip_admin_key',k);}catch(e){}"
              "location.replace('/admin.html');}"
              "else if(r.status===429){msg('Troppi tentativi, riprova tra poco.');btn(false);}"
              "else{msg('Chiave errata.');btn(false);}"
              "}catch(e){msg('Errore di rete.');btn(false);}")
    elif livello == "bunker":
        titolo, sub = "Bunker · super-admin", "Doppia chiave richiesta"
        campi = ('<input id="k" type="password" placeholder="Chiave admin" '
                 'autocomplete="current-password" aria-label="Chiave admin">'
                 '<input id="c" type="password" placeholder="Codice super-admin" '
                 'autocomplete="one-time-code" aria-label="Codice super-admin">')
        js = ("var k=document.getElementById('k').value,c=document.getElementById('c').value;"
              "if(!k||!c){msg('Inserisci chiave admin e codice super-admin.');return;}btn(true);try{"
              "var r=await fetch('/api/bunker/login',{method:'POST',headers:"
              "{'Content-Type':'application/json','X-Admin-Key':k},body:JSON.stringify({codice:c})});"
              "var d=null;try{d=await r.json();}catch(_){}"
              "if(r.status===200&&d&&d.sessione){try{sessionStorage.setItem('bv_bunker_sess',d.sessione);"
              "sessionStorage.setItem('bv_bunker_exp',String(Date.now()+1000*(d.scade_tra_sec||900)));}catch(e){}"
              "location.replace('/bunker.html');}"
              "else if(r.status===429){msg('Troppi tentativi, riprova tra poco.');btn(false);}"
              "else if(r.status===503){msg('Bunker non configurato.');btn(false);}"
              "else{msg('Chiave o codice errato.');btn(false);}"
              "}catch(e){msg('Errore di rete.');btn(false);}")
    else:
        # Il gate host fa LOGIN e REGISTRAZIONE sulla stessa pagina PUBBLICA (la dashboard host.html
        # resta gated). Prima 'Registrati' rimandava a /diventa-host.html i cui bottoni tornavano a
        # /host.html (gated) → /entra-host: LOOP infinito, e il form di registrazione (dentro host.html
        # gated) era IRRAGGIUNGIBILE. Ora la registrazione avviene QUI. doc_sha256/versione del
        # contratto sono iniettati dal server (la firma d'accettazione resta verificabile).
        from fase163_accettazioni import CONTRATTO_HOST_VERSIONE as _CV, doc_sha256 as _ds
        _dsha, _cver = _ds(), str(_CV)
        titolo, sub = "Area host", "Accedi o registrati"
        campi = ('<input id="em" type="email" placeholder="Email" autocomplete="username" '
                 'aria-label="Email"><input id="pw" type="password" placeholder="Password (min 8)" '
                 'autocomplete="current-password" aria-label="Password">'
                 '<div id="regx" style="display:none">'
                 '<input id="rs" placeholder="Nome struttura / ragione sociale (facoltativo)" '
                 'aria-label="Nome struttura">'
                 '<label style="display:block;text-align:left;font-size:.8rem;color:#9aa7bd;'
                 'margin:.35rem 0"><input type="checkbox" id="c1"> Accetto il '
                 '<a href="/termini.html" target="_blank" style="color:#c8a24a">Contratto Host</a></label>'
                 '<label style="display:block;text-align:left;font-size:.8rem;color:#9aa7bd;'
                 'margin:.35rem 0"><input type="checkbox" id="c2"> Approvo le clausole ex '
                 'artt. 1341-1342 c.c. (trattenute, penali, foro)</label>'
                 '<label style="display:block;text-align:left;font-size:.8rem;color:#9aa7bd;'
                 'margin:.35rem 0"><input type="checkbox" id="c3"> Accetto la '
                 '<a href="/privacy.html" target="_blank" style="color:#c8a24a">Privacy</a> (GDPR)</label>'
                 '</div>')
        js = ("var em=document.getElementById('em').value,pw=document.getElementById('pw').value;"
              "if(!em||!pw){msg('Inserisci email e password.');return;}"
              "if(window._reg){if(!(document.getElementById('c1').checked&&"
              "document.getElementById('c2').checked&&document.getElementById('c3').checked)){"
              "msg('Per registrarti spunta le tre caselle (Contratto, clausole, Privacy).');return;}"
              "if(pw.length<8){msg('La password deve avere almeno 8 caratteri.');return;}btn(true);try{"
              "var rr=await fetch('/api/host/registrazione',{method:'POST',headers:"
              "{'Content-Type':'application/json'},body:JSON.stringify({email:em,password:pw,"
              "ragione_sociale:document.getElementById('rs').value,accetta_termini:true,"
              "accetta_clausole:true,accetta_privacy:true,doc_sha256:'%s',versione:'%s',"
              "codice_referral:(new URLSearchParams(location.search).get('ref')||'')})});"
              "var dd=null;try{dd=await rr.json();}catch(_){}"
              "if(rr.status===201&&dd&&dd.token){try{localStorage.setItem('bookinvip_host_token',dd.token);"
              "localStorage.setItem('bookinvip_host_email',em);}catch(e){}location.replace('/host.html');}"
              "else if(rr.status===409){msg('Esiste gia un account con questa email: accedi.');btn(false);}"
              "else{msg((dd&&dd.errore)?('Registrazione: '+dd.errore):'Registrazione non riuscita.');"
              "btn(false);}}catch(e){msg('Errore di rete.');btn(false);}return;}"
              "btn(true);try{var r=await fetch('/api/host/login',{method:'POST',headers:"
              "{'Content-Type':'application/json'},body:JSON.stringify({email:em,password:pw})});"
              "var d=null;try{d=await r.json();}catch(_){}"
              "if(r.status===200&&d&&d.token){try{localStorage.setItem('bookinvip_host_token',d.token);"
              "localStorage.setItem('bookinvip_host_email',em);}catch(e){}location.replace('/host.html');}"
              "else if(r.status===429){msg('Troppi tentativi, riprova tra poco.');btn(false);}"
              "else{msg('Email o password errata.');btn(false);}"
              "}catch(e){msg('Errore di rete.');btn(false);}") % (_dsha, _cver)
        # Toggle registrazione + recupero password (niente più link che rimandano ad altre pagine).
        sotto = ('<div style="margin-top:1.1rem;text-align:center;font-size:.92rem">'
                 '<a href="#" id="toreg" style="color:#c8a24a;font-weight:600;'
                 'text-decoration:none">Non hai un account? Registrati</a>'
                 '<br><a href="#" id="pwlost" style="color:#9aa7bd;text-decoration:none;'
                 'display:inline-block;margin-top:.5rem">Password dimenticata?</a></div>')
        sotto_js = ("var _tr=document.getElementById('toreg');window._reg=false;if(_tr){"
                    "_tr.onclick=function(ev){ev.preventDefault();window._reg=!window._reg;"
                    "document.getElementById('regx').style.display=window._reg?'block':'none';"
                    "document.getElementById('go').textContent=window._reg?'Registrati':'Entra';"
                    "_tr.textContent=window._reg?'Hai gia un account? Accedi':"
                    "'Non hai un account? Registrati';msg('');};}"
                    "var _pl=document.getElementById('pwlost');if(_pl){_pl.onclick="
                    "async function(ev){ev.preventDefault();var e=document.getElementById('em');"
                    "var em=(e&&e.value)||prompt('Inserisci la tua email:');if(!em)return;try{"
                    "await fetch('/api/host/password_dimenticata',{method:'POST',headers:"
                    "{'Content-Type':'application/json'},body:JSON.stringify({email:em})});}catch(_){}"
                    "msg('Se l\\'email e registrata, ti abbiamo inviato il link per la nuova password.');"
                    "};}"
                    # RESET dal link email (#reset=<token> nel fragment: mai nei log): chiede la
                    # nuova password e la applica, poi manda al pannello.
                    "(function(){var _h=location.hash||'';if(_h.indexOf('#reset=')!==0)return;"
                    "var _t=decodeURIComponent(_h.slice(7));"
                    "var _p=prompt('Scegli la NUOVA password (minimo 8 caratteri):');"
                    "if(!_p)return;if(_p.length<8){msg('La password deve avere almeno 8 caratteri.');return;}"
                    "fetch('/api/host/password_reset',{method:'POST',headers:{'Content-Type':"
                    "'application/json'},body:JSON.stringify({token:_t,password:_p})}).then(function(r){"
                    "return r.json().then(function(d){return{s:r.status,d:d};});}).then(function(o){"
                    "if(o.s===200&&o.d&&o.d.ok){msg('Password cambiata! Ora accedi con la nuova password.');"
                    "location.hash='';setTimeout(function(){location.replace('/host.html');},1400);}"
                    "else{msg('Link non valido o scaduto: richiedi un nuovo link.');}}).catch(function(){"
                    "msg('Errore di rete.');});})();")
    esc_t = titolo.replace("&", "&amp;").replace("<", "&lt;")
    esc_s = sub.replace("&", "&amp;").replace("<", "&lt;")
    return (
        '<!DOCTYPE html><html lang="it"><head><meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex, nofollow">'
        '<title>' + esc_t + ' · BookinVIP</title><style>'
        'body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:#0f1420;'
        'color:#e6ebf3;margin:0;min-height:100vh;display:flex;align-items:center;'
        'justify-content:center;padding:1.2rem}'
        '.c{background:#171d2b;border:1px solid #26304a;border-radius:1.2rem;'
        'box-shadow:0 12px 40px rgba(0,0,0,.35);padding:2.2rem 1.9rem;max-width:380px;width:100%}'
        '.logo{font-weight:800;font-size:1.25rem;margin-bottom:.2rem}.logo b{color:#c8a24a}'
        '.sub{color:#9aa7bd;font-size:.9rem;margin-bottom:1.3rem}'
        'input{display:block;width:100%;box-sizing:border-box;background:#0c111b;'
        'border:1px solid #2a3550;color:#e6ebf3;border-radius:.6rem;padding:.7rem .8rem;'
        'margin-bottom:.7rem;font-size:1rem}'
        'button{width:100%;background:#c8a24a;color:#0f1420;font-weight:700;border:0;'
        'border-radius:.6rem;padding:.8rem;font-size:1rem;cursor:pointer}'
        'button:disabled{opacity:.6;cursor:default}'
        '.m{color:#ff8f8f;font-size:.88rem;min-height:1.1rem;margin-top:.7rem;text-align:center}'
        '.eye{float:right;margin-top:-2.55rem;margin-right:.5rem;position:relative;'
        'cursor:pointer;font-size:1.05rem;opacity:.7}'
        '</style></head><body><div class="c">'
        '<div class="logo">🏰 Bookin<b>VIP</b></div><div class="sub">' + esc_s + '</div>'
        '<form id="f" autocomplete="on">' + campi +
        '<button id="go" type="submit">Entra</button></form>'
        '<div class="m" id="m"></div>' + sotto +
        '<script>'
        'function msg(t){document.getElementById("m").textContent=t||"";}'
        'function btn(b){document.getElementById("go").disabled=b;'
        'document.getElementById("go").textContent=b?"…":"Entra";}'
        'document.querySelectorAll(\'input[type=password]\').forEach(function(p){'
        'var e=document.createElement("span");e.className="eye";e.textContent="👁";'
        'e.onclick=function(){p.type=p.type==="password"?"text":"password";};'
        'p.insertAdjacentElement("afterend",e);});'
        'document.getElementById("f").addEventListener("submit",async function(ev){'
        'ev.preventDefault();' + js + '});' + sotto_js +
        '</script></body></html>')


def _punteggio_consigliato(c: Dict[str, Any]) -> int:
    """Punteggio di qualità di un annuncio per l'ordinamento 'consigliati' (i migliori in cima,
    come i colossi). PURO/deterministico, usa SOLO segnali già disponibili nella card (nessun
    dato esterno): foto, recensioni (numero+voto), cancellazione gratuita, ricchezza servizi.
    Più alto = meglio. A pari punteggio l'ordinamento stabile lascia i recenti prima."""
    s = 0
    if not isinstance(c, dict):
        return 0
    if c.get("thumbnail"):
        s += 40                                   # ha una foto: segnale fortissimo di completezza
    rec = c.get("recensioni")
    if isinstance(rec, dict):
        n = rec.get("conteggio")
        if isinstance(n, int) and n > 0:
            s += min(30, n * 3)                   # più recensioni = più fiducia (cap 30)
        media = rec.get("media_centesimi")
        if isinstance(media, int) and media > 0:
            s += min(25, media // 20)             # voto 0..500 -> 0..25
    if c.get("cancellazione_gratuita"):
        s += 10                                   # leva di conversione
    serv = c.get("servizi")
    if isinstance(serv, (list, tuple)):
        s += min(10, len(serv) * 2)               # più servizi dichiarati = annuncio curato
    return s


def finestra_flessibile(check_in: Any, check_out: Any, flex_giorni: Any):
    """Range di ricerca a DATE FLESSIBILI: da [check_in - flex] a [check_out + flex] e il
    numero di notti richieste. PURA/deterministica (nessun I/O) -> testabile in isolamento.
    Ritorna (da_iso, a_iso, n_notti) oppure None se l'input non è valido (date non ISO,
    check_out<=check_in, flex non intero o <=0).

    Estratta da _catalogo (audit resilienza comp.3): prima era inline dentro un
    'try/except: _n=0' che, su un errore di parsing, DISATTIVAVA la ricerca flessibile IN
    SILENZIO -> l'ospite non trovava nulla e nessuno sapeva perché. Ora il caso invalido è
    esplicito (None) e la funzione è coperta da test unitari sui bordi (±1 giorno)."""
    import datetime as _d
    try:
        ci = _d.date.fromisoformat(str(check_in))
        co = _d.date.fromisoformat(str(check_out))
    except (ValueError, TypeError):
        return None
    n = (co - ci).days
    if n <= 0 or not isinstance(flex_giorni, int) or isinstance(flex_giorni, bool) \
            or flex_giorni <= 0:
        return None
    return ((ci - _d.timedelta(days=flex_giorni)).isoformat(),
            (co + _d.timedelta(days=flex_giorni)).isoformat(), n)


def _ext_da_magic(raw: bytes) -> Optional[str]:
    """Tipo immagine dai MAGIC BYTES (mai fidarsi del content-type/estensione). None se
    non e' un'immagine supportata."""
    if not raw:
        return None
    if raw[:3] == b"\xff\xd8\xff":
        return "jpg"
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "webp"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return None


def _ip_host_pubblico(host: str) -> bool:
    """True SOLO se tutti gli indirizzi risolti dell'host sono PUBBLICI. Blocca loopback/
    privati/link-local/riservati (anti-SSRF: niente fetch verso servizi interni o metadata
    cloud). Risoluzione fallita -> False (fail-closed)."""
    import ipaddress
    import socket
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return False
    if not infos:
        return False
    for info in infos:
        sockaddr = info[4]
        ip = sockaddr[0].split("%", 1)[0]            # via eventuale zona IPv6
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        if (addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_reserved or addr.is_multicast or addr.is_unspecified):
            return False
    return True


# Tetto anti-abuso: quante email di preventivo puo' ricevere UN indirizzo in un'ora.
# 3 e' generoso per un utente vero (che ne chiede una, forse due) e stretto per un abusante.
MAX_PREVENTIVI_EMAIL_ORA = 3
# Tetto prove-foto per prenotazione: il limite di 5MB era PER FILE, non sul NUMERO -> con una
# sola prenotazione valida si riempiva il disco (= sito giu'). 10 e' abbondante per una
# controversia vera. Il prefisso identifica le prove nel thread (serve anche a contarle).
MAX_PROVE_FOTO = 10
_PREFISSO_PROVA = "📎 PROVA FOTO:"


class RouterHTTP:
    """Router PURO (testabile): cabla il SistemaCasaVIP (fase81) sulle rotte HTTP."""

    def __init__(self, sistema: Any, *, host_key: Optional[str] = None,
                 admin_key: Optional[str] = None, base_url: str = "") -> None:
        self._sys = sistema
        self._host_key = host_key
        self._admin_key = admin_key
        self._base_url = base_url or ""
        self._loc = Localizzatore()
        # RATE LIMIT autenticazione (fase179), RICALIBRATO il 2026-07-22 dopo che un host
        # VERO e' finito in lockout provando la password (log di produzione). Difende dal
        # brute-force ma NON deve punire chi sbaglia in buona fede (caps-lock, password
        # salvata vecchia, refuso):
        #   - soglia 8/min (era 5): margine per un umano che sbaglia; per un attaccante 8
        #     tentativi al minuto contro una password >=8 caratteri sono comunque inutili;
        #   - primo blocco 30s (era 60): fastidio breve, non una porta sbattuta;
        #   - blocco MASSIMO 10 min (era 60): un host onesto non resta MAI chiuso fuori
        #     un'ora. Anche a regime, ~8 tentativi ogni 10 min = ~48/ora: brute-force
        #     online impraticabile, ma l'utente vero recupera in fretta.
        # Resta PER IP (mai per-email: bloccare un account con password sbagliate da un IP
        # qualsiasi sarebbe un DoS sull'host onesto).
        try:
            from fase179_rate_limit import crea_rate_limiter
            self._rate = crea_rate_limiter(soglia=8, finestra_sec=60,
                                           base_blocco_sec=30, max_blocco_sec=600)
        except Exception:
            self._rate = None

    def _rate_chiave_login(self, headers):
        """Chiave di throttle del login = PER IP (policy fondatore: 5/min per IP). NON
        blocco per-email di proposito: bloccare un account dopo N fallimenti da qualsiasi
        IP sarebbe un 'account-lockout DoS' (un attaccante zittisce un host onesto con 5
        password sbagliate). La minaccia distribuita si vede nell'audit log, non col blocco.
        IP vuoto (chiamata non attribuibile, es. test diretti) -> nessuna chiave."""
        ip = self._client_ip(headers)
        return ("login-ip:" + ip) if ip else ""

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

    def _salute_db(self) -> Tuple[bool, Dict[str, str]]:
        """Salute di OGNI archivio configurato: connessione a parte + SELECT 1 (READ-ONLY,
        veloce, ISOLATA per DB: un archivio rotto non nasconde gli altri). Enumera i campi
        'db_*' di ConfigCasaVIP -> nessun nome scritto a mano; :memory:/vuoti saltati."""
        import sqlite3 as _sq
        cfg = getattr(self._sys, "config", None)
        campi = getattr(type(cfg), "__dataclass_fields__", {}) if cfg is not None else {}
        out: Dict[str, str] = {}
        tutto_ok = True
        for nome in campi:
            if not nome.startswith("db_"):
                continue
            perc = getattr(cfg, nome, "")
            if not (isinstance(perc, str) and perc) or perc == ":memory:":
                continue
            try:
                con = _sq.connect(perc, timeout=5)
                try:
                    # PRAGMA schema_version LEGGE l'intestazione del file: fallisce su un file
                    # non-sqlite/corrotto (un banale SELECT 1 non tocca il file e non se ne accorge).
                    con.execute("PRAGMA schema_version").fetchone()
                finally:
                    con.close()
                out[nome] = "ok"
            except Exception:
                out[nome] = "ERRORE"
                tutto_ok = False
        return tutto_ok, out

    def _instrada(self, metodo, path, query, body, headers):
        # SONDE DI SALUTE, prima del gate 'sistema_spento': la LIVENESS deve rispondere ANCHE
        # durante avvio/spegnimento (l'orchestratore distingue "processo vivo ma non pronto" da
        # "processo morto"); READY e DB danno un esito PROPRIO invece del generico 503. READ-ONLY.
        if metodo == "GET" and path == "/api/health/live":
            return 200, {"status": "live", "money_unit": "cents_integer"}
        if metodo == "GET" and path == "/api/health/ready":
            pronto = bool(getattr(self._sys, "attivo", False))
            return (200 if pronto else 503), {"status": "ready" if pronto else "not_ready"}
        if metodo == "GET" and path == "/api/health/db":
            ok, dettaglio = self._salute_db()
            return (200 if ok else 503), {"status": "ok" if ok else "degraded", "db": dettaglio}
        if not self._sys.attivo:
            return 503, {"errore": "sistema_spento"}
        if metodo == "GET" and path == "/api/health":
            return 200, {"status": "ok", "money_unit": "cents_integer",
                         "guardiano": self._stato_battito_guardiano()}
        if metodo == "GET" and path == "/api/lingue":
            return 200, {"lingue": list(LINGUE_SUPPORTATE)}
        if metodo == "GET" and path == "/api/i18n":
            return 200, _dizionario_i18n(_lingua(query))
        if metodo == "GET" and path == "/api/legale/documento":
            return self._documento_legale(query)
        if metodo == "GET" and path == "/api/legale/contratto-host":
            return self._contratto_host(query)
        if metodo == "GET" and path == "/api/trasparenza":
            return self._trasparenza(query, headers)
        if metodo == "POST" and path == "/api/domanda":
            return self._domanda_registra(body)
        if metodo == "POST" and path == "/api/partner":
            return self._partner_registra(body)
        if metodo == "GET" and path == "/api/admin/partner":
            return self._admin_partner(query, headers)
        if metodo == "GET" and path == "/api/domanda/conta":
            return self._domanda_conta(query)
        if metodo == "GET" and path == "/api/domanda/citta":
            return self._domanda_per_citta(query)
        if metodo == "GET" and path == "/api/catalogo":
            return self._catalogo(query)
        if metodo == "GET" and path == "/api/mappa":
            return self._mappa(query)
        if metodo == "GET" and path.startswith("/api/catalogo/"):
            return self._dettaglio(path[len("/api/catalogo/"):], _lingua(query))
        if metodo == "POST" and path == "/api/concierge/quote":
            return self._concierge_quote(body)
        if metodo == "POST" and path == "/api/concierge/book":
            return self._book(body)
        if metodo == "POST" and path == "/api/concierge/cancella":
            return self._cancella_prenotazione(body)
        if metodo == "GET" and path == "/api/concierge/manifest":
            return self._concierge_manifest()
        if metodo == "POST" and path == "/api/preventivo/email":
            return self._preventivo_email(body)
        if metodo == "POST" and path == "/api/split/preview":
            return self._split_preview(body)
        if metodo == "POST" and path == "/api/contratto":
            return self._contratto(body)
        if metodo == "GET" and path == "/api/host/conversazioni":
            return self._host_conversazioni(headers)
        if metodo == "POST" and path == "/api/voucher/messaggio":
            return self._voucher_msg_invia(body)
        if metodo == "GET" and path == "/api/voucher/messaggi":
            return self._voucher_msg_thread(query)
        if metodo == "POST" and path == "/api/voucher/prova":
            return self._voucher_prova(body)
        if metodo == "GET" and path == "/api/admin/messaggi":
            return self._admin_messaggi(query, headers)
        if metodo == "POST" and path == "/api/checkin/pre_registra":
            return self._checkin_pre_registra(body)
        if metodo == "GET" and path == "/api/checkin/stato":
            return self._checkin_stato(query)
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
        if metodo == "GET" and path == "/api/host/seo_report":
            return self._host_seo_report(query, headers)
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
        if metodo == "POST" and path == "/api/host/foto_elimina":
            return self._foto_elimina(body, headers)
        if metodo == "POST" and path == "/api/host/importa":
            return self._host_importa(body, headers)
        if metodo == "POST" and path == "/api/host/disponibilita":
            return self._host_disponibilita(body, headers)
        if metodo == "POST" and path == "/api/host/disponibilita_range":
            return self._host_disponibilita_range(body, headers)
        if metodo == "POST" and path == "/api/host/registrazione":
            return self._host_registrazione(body, headers)
        if metodo == "POST" and path == "/api/host/password_dimenticata":
            return self._host_password_dimenticata(body)
        if metodo == "POST" and path == "/api/host/password_reset":
            return self._host_password_reset(body)
        if metodo == "POST" and path == "/api/host/cambia_password":
            return self._host_cambia_password(body, headers)
        if metodo == "POST" and path == "/api/host/login":
            return self._host_login(body, headers)
        if metodo == "GET" and path == "/api/host/referral":
            return self._host_referral(query, headers)
        if metodo == "GET" and path == "/api/host/link_diretto":
            return self._host_link_diretto(query, headers)
        if metodo == "GET" and path == "/api/host/telegram_link":
            return self._host_telegram_link(headers)
        if metodo == "GET" and path == "/api/host/ical_link":
            return self._ical_link(query, headers)
        if metodo == "GET" and path == "/api/host/calendario_prezzi":
            return self._host_calendario_prezzi(query, headers)
        if metodo == "GET" and path == "/api/host/calendario_tutti":
            return self._host_calendario_tutti(query, headers)
        if metodo == "GET" and path == "/api/host/metriche_avanzate":
            return self._host_metriche_avanzate(headers)
        if metodo == "POST" and path == "/api/host/alloggio_elimina":
            return self._host_alloggio_elimina(body, headers)
        if metodo == "GET" and path == "/api/host/stripe_link":
            return self._host_stripe_link(headers)
        if metodo == "POST" and path == "/api/host/carta_link":
            return self._host_carta_link(headers)      # Scatto ③: salva carta (hosted)
        if metodo == "GET" and path == "/api/host/carta_stato":
            return self._host_carta_stato(headers)
        if metodo == "POST" and path == "/api/telegram/webhook":
            return self._telegram_webhook(body, headers)
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
        if metodo == "GET" and path == "/api/host/prenotazioni":
            return self._host_prenotazioni(query, headers)
        if metodo == "GET" and path == "/api/host/alloggio":
            return self._host_alloggio_dettaglio(query, headers)
        if metodo == "GET" and path == "/api/host/geocode":
            return self._host_geocode(query, headers)
        if metodo == "GET" and path == "/api/host/accettazioni":
            return self._host_accettazioni(query, headers)
        if metodo == "GET" and path == "/api/host/contratto_stato":
            return self._host_contratto_stato(headers)
        if metodo == "POST" and path == "/api/host/riaccetta":
            return self._host_riaccetta(body, headers)
        if metodo == "POST" and path == "/api/host/stato":
            return self._host_stato(body, headers)
        if metodo == "POST" and path == "/api/host/cancella":
            return self._host_cancella(body, headers)
        if metodo == "GET" and path == "/api/admin/prenotazioni":
            return self._admin_prenotazioni(query, headers)
        if metodo == "GET" and path == "/api/admin/search":
            return self._admin_search(query, headers)   # ricerca operativa unificata (Incr.7)
        if metodo == "GET" and path == "/api/admin/audit":
            return self._admin_audit(query, headers)    # scheda contabile + semaforo (fase181)
        if metodo == "POST" and path == "/api/admin/storno_penale":
            return self._admin_storno_penale(body, headers)   # 5ª distruttiva (Bunker-gated)
        if metodo == "GET" and path == "/api/admin/verifiche":
            return self._admin_verifiche(query, headers)      # KYC dashboard (Incr.10)
        if metodo == "GET" and path == "/api/admin/verifiche/dettaglio":
            return self._admin_verifiche_dettaglio(query, headers)
        if metodo == "GET" and path == "/api/admin/verifiche/fascicolo":
            return self._admin_verifiche_fascicolo(query, headers)   # Bunker-gated
        if metodo == "POST" and path == "/api/admin/verifica_stato":
            return self._admin_verifica_stato(body, headers)         # Bunker-gated
        if metodo == "GET" and path == "/api/admin/alloggi":
            return self._admin_alloggi(query, headers)
        if metodo == "POST" and path == "/api/admin/alloggio_stato":
            return self._admin_alloggio_stato(body, headers)
        if metodo == "POST" and path == "/api/admin/rimborso":
            return self._admin_rimborso(body, headers)
        if metodo == "GET" and path == "/api/admin/rimborsi_dovuti":
            return self._admin_rimborsi_dovuti(query, headers)   # chi aspetta i suoi soldi
        if metodo == "POST" and path == "/api/admin/rimborsa_dovuto":
            return self._admin_rimborsa_dovuto(body, headers)    # il pulsante, uno per volta
        if metodo == "GET" and path == "/api/admin/controversie":
            return self._admin_controversie(query, headers)
        if metodo == "POST" and path == "/api/admin/controversia/risolvi":
            return self._admin_controversia_risolvi(body, headers)
        if metodo == "POST" and path == "/api/admin/cancella_attivita":
            return self._admin_cancella_attivita(body, headers)
        if metodo == "GET" and path == "/api/admin/diagnosi":
            return self._admin_diagnosi(query, headers)
        if metodo == "POST" and path == "/api/bunker/login":
            return self._bunker_login(body, headers)
        if metodo == "GET" and path == "/api/bunker/stato":
            return self._bunker_stato(query, headers)
        if metodo == "GET" and path == "/api/bunker/export_legale":
            return self._bunker_export_legale(query, headers)
        if metodo == "GET" and path == "/api/bunker/scaglioni_host":
            return self._bunker_scaglioni(query, headers)
        if metodo == "GET" and path == "/api/bunker/prove_legali":
            return self._bunker_prove_legali(query, headers)
        if metodo == "GET" and path == "/api/bunker/costi_tecnici":
            return self._bunker_costi_tecnici(query, headers)
        if metodo == "GET" and path == "/api/bunker/marche_temporali":
            return self._bunker_marche(query, headers)
        if metodo == "POST" and path == "/api/bunker/marca_ora":
            return self._bunker_marca_ora(body, headers)
        if metodo == "GET" and path == "/api/bunker/integrita":
            return self._bunker_integrita(query, headers)
        if metodo == "GET" and path == "/api/bunker/log":
            return self._bunker_log(query, headers)
        if metodo == "POST" and path == "/api/bunker/logout":
            return self._bunker_logout(body, headers)
        if metodo == "POST" and path == "/api/admin/login":
            return self._admin_login(body, headers)      # gatekeeper: cookie sessione admin
        if metodo == "POST" and path == "/api/gate/logout":
            return self._gate_logout(body, headers)      # gatekeeper: cancella i cookie
        if metodo == "GET" and path == "/api/bunker/export_contabile":
            return self._bunker_export_contabile(query, headers)
        if metodo == "GET" and path == "/api/bunker/riconciliazione":
            return self._bunker_riconciliazione(query, headers)   # fase182 (pre-mortem)
        if metodo == "GET" and path == "/api/bunker/invarianti":
            return self._bunker_invarianti(query, headers)        # fase199 auditor invarianti
        if metodo == "GET" and path == "/api/bunker/guardiano":
            return self._bunker_guardiano(headers)                # fase186 (a richiesta)
        if metodo == "GET" and path == "/api/bunker/dac7_conformita":
            return self._bunker_dac7_conformita(query, headers)
        if metodo == "GET" and path == "/api/bunker/dac7_report":
            return self._bunker_dac7_report(query, headers)
        if metodo == "GET" and path == "/api/bunker/blocco_globale":
            return self._bunker_blocco_globale_stato(headers)
        if metodo == "POST" and path == "/api/bunker/blocco_globale":
            return self._bunker_blocco_globale_imposta(body, headers)
        if metodo == "GET" and path == "/api/bunker/cambio_valuta":
            return self._bunker_cambio_valuta(headers)
        if metodo == "POST" and path == "/api/bunker/cambio_valuta/aggiorna":
            return self._bunker_cambio_valuta_aggiorna(headers)
        if metodo == "GET" and path == "/api/bunker/admin_accounts":
            return self._bunker_admin_accounts(headers)
        if metodo == "POST" and path == "/api/bunker/admin_accounts":
            return self._bunker_admin_accounts_gestisci(body, headers)
        if metodo == "POST" and path == "/api/host/dati_fiscali":
            return self._host_dati_fiscali(body, headers)
        if metodo == "GET" and path == "/api/host/dac7_stato":
            return self._host_dac7_stato(query, headers)   # avviso hold payout nel pannello
        if metodo == "GET" and path == "/api/host/kyc_stato":
            return self._host_kyc_stato(query, headers)    # verifica identita' (Incr.11)
        if metodo == "POST" and path == "/api/host/kyc_avvia":
            return self._host_kyc_avvia(body, headers)     # avvia Stripe Identity (gated)
        return 404, {"errore": "rotta_non_trovata"}

    # --- helper ---
    @staticmethod
    def _json(body: Optional[str]) -> Optional[Dict[str, Any]]:
        try:
            d = json.loads(body) if body else None
            return d if isinstance(d, dict) else None
        except (ValueError, TypeError, RecursionError):
            # RecursionError: corpo con annidamento profondissimo ('[[[[...') -> il parser
            # sfonda lo stack. NON e' un errore nostro: e' corpo malformato -> 400, mai 500.
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
        fornita = headers.get("X-Host-Key", "") or headers.get("x-host-key", "")
        return self._auth_con_rate("host", str(fornita), str(self._host_key), headers)

    def pulizia_uploads_orfani(self, *, eta_min_s=7 * 86400, adesso=None):
        """PULIZIA AUTOMATICA dei file orfani in UPLOAD_DIR (audit "10 moduli" 2026-07-19):
        un upload mai agganciato a un annuncio ne' citato in chat resta su disco PER
        SEMPRE (residuo). Cancella SOLO file (a) piu' vecchi di eta_min_s (default 7gg:
        un host a meta' pubblicazione non viene mai toccato) e (b) non citati da NESSUNA
        fonte. FAIL-CLOSED: censimento in errore -> zero cancellazioni; PARACADUTE: se
        gli "orfani" superano meta' dei file (e >5) il censimento e' sospetto -> annulla
        con log CRITICO. Kill-switch: PULIZIA_UPLOADS=0."""
        import os as _os
        import time as _t
        if _os.environ.get("PULIZIA_UPLOADS", "1") == "0":
            return {"saltata": "kill_switch"}
        updir = _os.environ.get("UPLOAD_DIR", "data/uploads")
        if not _os.path.isdir(updir):
            return {"saltata": "no_dir"}
        try:
            riferiti = set()
            cat = getattr(self._sys, "catalogo", None)
            msg = getattr(self._sys, "messaggistica", None)
            if cat is not None:
                riferiti |= cat.nomi_uploads()
            if msg is not None:
                riferiti |= msg.nomi_uploads()
        except Exception:
            logger.warning("pulizia uploads: censimento riferimenti in errore -> "
                           "NESSUNA cancellazione (fail-closed)", exc_info=True)
            return {"saltata": "censimento_in_errore"}
        adesso = adesso if adesso is not None else _t.time()
        tutti = [n for n in _os.listdir(updir)
                 if _os.path.isfile(_os.path.join(updir, n))]
        candidati = []
        for n in tutti:
            if n in riferiti:
                continue
            try:
                if adesso - _os.path.getmtime(_os.path.join(updir, n)) < eta_min_s:
                    continue
            except OSError:
                continue
            candidati.append(n)
        if tutti and len(candidati) > max(5, len(tutti) // 2):
            logger.error("CRITICO pulizia uploads: %d/%d 'orfani' = censimento sospetto, "
                         "ANNULLATA (nessun file toccato)", len(candidati), len(tutti))
            return {"saltata": "paracadute", "candidati": len(candidati),
                    "totale": len(tutti)}
        rimossi = 0
        for n in candidati:
            try:
                _os.remove(_os.path.join(updir, n))
                rimossi += 1
            except OSError:
                pass
        if rimossi:
            logger.warning("PULIZIA_UPLOADS | rimossi %d file orfani (>%d gg, mai citati "
                           "da annunci/chat) su %d totali", rimossi,
                           eta_min_s // 86400, len(tutti))
        return {"rimossi": rimossi, "totale": len(tutti), "riferiti": len(riferiti)}

    def _pulizia_uploads_se_ora(self):
        """Gancio per il tick orario: esegue la pulizia al massimo una volta ogni 24h."""
        import time as _t
        if _t.time() - getattr(self, "_pulizia_uploads_ts", 0) < 86400:
            return None
        self._pulizia_uploads_ts = _t.time()
        return self.pulizia_uploads_orfani()

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
        ext = _ext_da_magic(raw)                                  # tipo dai MAGIC BYTES
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

    def _salva_foto_raw(self, raw64):
        """Salva un'immagine base64 in UPLOAD_DIR (magic-bytes, 5MB). -> (status, dict)."""
        import base64 as _b64, os as _os, secrets as _sec
        if isinstance(raw64, str) and raw64.startswith("data:") and "," in raw64:
            raw64 = raw64.split(",", 1)[1]
        try:
            raw = _b64.b64decode(raw64 or "", validate=True)
        except Exception:
            return 422, {"errore": "immagine_non_valida"}
        if not raw or len(raw) > 5 * 1024 * 1024:
            return 422, {"errore": "dimensione_non_valida"}
        ext = _ext_da_magic(raw)
        if ext is None:
            return 422, {"errore": "formato_non_supportato"}
        updir = _os.environ.get("UPLOAD_DIR", "data/uploads")
        try:
            _os.makedirs(updir, exist_ok=True)
            nome = _sec.token_hex(16) + "." + ext
            with open(_os.path.join(updir, nome), "wb") as f:
                f.write(raw)
        except Exception:
            logger.error("salvataggio foto fallito (ISOLATO)", exc_info=True)
            return 503, {"errore": "storage_non_disponibile"}
        return 201, {"url": "/uploads/" + nome}

    # --- CHAT DAL VOUCHER (cliente<->host, zero password: autentica il voucher firmato) ---
    def _voucher_chat_ctx(self, token):
        """(rif, host_id) dal voucher firmato, o None. guest_id canonico = 'ospite'."""
        v = self._voucher_valido(token)
        if v is None:
            return None
        rif, allog = v.get("riferimento", ""), v.get("alloggio_id", "")
        if not (rif and allog):
            return None
        try:
            hid = self._sys.catalogo.host_di_alloggio(allog) or "host"
        except Exception:
            hid = "host"
        return rif, hid

    def _host_conversazioni(self, headers):
        """Le conversazioni dell'host, caricate DA SOLE nel pannello (zero codici)."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        hid = self._host_id_da_token(headers)
        msg = getattr(self._sys, "messaggistica", None)
        if msg is None or not hid:
            return 200, {"conversazioni": []}
        return 200, {"conversazioni": msg.conversazioni_host(hid)}

    def _voucher_msg_invia(self, body):
        """Il CLIENTE scrive all'host dal voucher (per chiarire, es. una controversia)."""
        msg = getattr(self._sys, "messaggistica", None)
        if msg is None:
            return 503, {"errore": "messaggistica_non_attiva"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        ctx = self._voucher_chat_ctx(dati.get("voucher_token"))
        if ctx is None:
            return 400, {"errore": "voucher_non_valido"}
        rif, hid = ctx
        ok = msg.invia(rif, hid, "ospite", "ospite", dati.get("testo"))
        return (201, {"stato": "inviato"}) if ok else (422, {"errore": "non_inviato"})

    def _voucher_msg_thread(self, query):
        msg = getattr(self._sys, "messaggistica", None)
        if msg is None:
            return 503, {"errore": "messaggistica_non_attiva"}
        ctx = self._voucher_chat_ctx(query.get("voucher_token"))
        if ctx is None:
            return 400, {"errore": "voucher_non_valido"}
        rif, _hid = ctx
        return 200, {"messaggi": msg.thread(rif, "ospite")}

    def _voucher_prova(self, body):
        """Il CLIENTE carica una FOTO come PROVA (controversia): la foto entra nella CHAT
        della prenotazione -> cliente, host e admin la vedono nello stesso posto."""
        msg = getattr(self._sys, "messaggistica", None)
        if msg is None:
            return 503, {"errore": "messaggistica_non_attiva"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        ctx = self._voucher_chat_ctx(dati.get("voucher_token"))
        if ctx is None:
            return 400, {"errore": "voucher_non_valido"}
        rif, hid = ctx
        # TETTO PER PRENOTAZIONE (collaudo 2026-07-15). C'era il limite di 5MB per FILE ma
        # NESSUNO sul numero: con UNA prenotazione valida si potevano caricare foto all'infinito
        # -> disco pieno (44GB liberi = ~9000 file) -> SQLite non scrive piu' -> SITO GIU'.
        # Basta anche un client con un ciclo sbagliato: non serve un malintenzionato.
        # Il controllo sta PRIMA di _salva_foto_raw: se si e' oltre, non si scrive affatto.
        try:
            esistenti = msg.thread(rif, "ospite") or []
            n_prove = sum(1 for m in esistenti
                          if str((m or {}).get("testo", "")).startswith(_PREFISSO_PROVA))
        except Exception:
            n_prove = 0                      # isolato: un errore di lettura non blocca l'ospite
        if n_prove >= MAX_PROVE_FOTO:
            return 429, {"errore": "troppe_prove_caricate"}
        st, out = self._salva_foto_raw(dati.get("image_base64"))
        if st != 201:
            return st, out
        # ESITO DELLA BOLLA VERIFICATO (fix 2026-07-19): prima msg.invia era IGNORATO ->
        # con DB occupato (fase113 ritorna False, mai solleva) il cliente leggeva
        # "caricata" ma la prova NON esisteva in chat (l'arbitro non l'avrebbe mai vista)
        # e la foto restava ORFANA su disco. Niente bolla -> file rimosso + 503 onesto.
        try:
            ok = bool(msg.invia(rif, hid, "ospite", "ospite",
                                _PREFISSO_PROVA + " " + out["url"]))
        except Exception:
            logger.error("prova foto: bolla non scritta (ISOLATO)", exc_info=True)
            ok = False
        if not ok:
            import os as _os
            try:
                _os.remove(_os.path.join(_os.environ.get("UPLOAD_DIR", "data/uploads"),
                                         out["url"].rsplit("/", 1)[1]))
            except Exception:
                logger.warning("prova foto: pulizia file non riuscita", exc_info=True)
            return 503, {"errore": "prova_non_registrata"}
        return 201, {"stato": "caricata", "url": out["url"]}

    def _admin_messaggi(self, query, headers):
        """L'ARBITRO (admin) legge la conversazione + prove di una prenotazione contestata."""
        if not self._auth_admin(headers):
            return 401, {"errore": "unauthorized"}
        msg = getattr(self._sys, "messaggistica", None)
        rif = query.get("riferimento")
        if msg is None or not (isinstance(rif, str) and rif):
            return 422, {"errore": "campi_non_validi"}
        return 200, {"messaggi": msg.thread(rif, "ospite")}

    def _auth_admin(self, headers: Dict[str, str]) -> bool:
        if self._admin_key is None:
            return True            # nessuna chiave configurata = aperto (dev)
        # OPERATORE admin (fase192) con TOKEN firmato (X-Admin-Op): additivo. Va provato PRIMA, cosi'
        # una richiesta legittima d'operatore (senza X-Admin-Key) NON conta come tentativo-chiave
        # fallito nel buttafuori per IP. Guardato da `tok` per NON deviare la ROOT: la chiave root
        # deve ripassare da `_auth_con_rate` (che, sulla chiave giusta, AZZERA il contatore dei
        # fallimenti -> il legittimo non e' mai penalizzato). Deviarla romperebbe quel reset.
        tok = headers.get("X-Admin-Op", "") or headers.get("x-admin-op", "")
        if tok and self._ruolo_operatore(headers) is not None:
            return True
        fornita = headers.get("X-Admin-Key", "") or headers.get("x-admin-key", "")
        return self._auth_con_rate("admin", str(fornita), str(self._admin_key), headers)

    def _firma_op(self, email, ruolo, ttl_sec=28800):
        """Token operatore admin firmato 'op|email|ruolo|exp|nonce|hmac' (HMAC-SHA256, segreto)."""
        import base64
        import hashlib
        import hmac as _h
        import os as _os
        import time as _t
        exp = int(_t.time()) + int(ttl_sec)
        nonce = base64.urlsafe_b64encode(_os.urandom(9)).decode("ascii").rstrip("=")
        corpo = "op|%s|%s|%d|%s" % (email, ruolo, exp, nonce)
        sig = _h.new(self._gate_segreto(), corpo.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
        return corpo + "|" + sig

    def _verifica_op(self, token):
        """Verifica firma (costante-tempo) + scadenza del token operatore. -> {email, ruolo} o None."""
        import hashlib
        import hmac as _h
        import time as _t
        try:
            parti = str(token).split("|")
            if len(parti) != 6 or parti[0] != "op":
                return None
            _, email, ruolo, exp, nonce, sig = parti
            corpo = "op|%s|%s|%s|%s" % (email, ruolo, exp, nonce)
            atteso = _h.new(self._gate_segreto(), corpo.encode("utf-8"),
                            hashlib.sha256).hexdigest()[:32]
            if not _h.compare_digest(atteso, str(sig)):
                return None
            if int(exp) < int(_t.time()):
                return None
            return {"email": email, "ruolo": ruolo}
        except Exception:
            return None

    def _ruolo_operatore(self, headers):
        """Ruolo di CHI agisce: 'admin' con la ROOT key; altrimenti il ruolo CORRENTE dell'operatore
        del token X-Admin-Op (ri-letto dal DB fase192 -> revoca/cambio-ruolo ISTANTANEI); None se
        non autenticato. Serve per i permessi per-ruolo."""
        import hmac as _h
        if self._admin_key is None:
            # Nessuna chiave configurata = modalita' APERTA (dev): _auth_admin (riga ~2244)
            # lascia passare CHIUNQUE come root. I due strati devono dire la STESSA cosa: se
            # qui tornassimo None, _puo_azione negherebbe rimborso/arbitrato/moderazione a un
            # chiamante che _auth_admin ha appena riconosciuto come amministratore pieno --
            # porta spalancata e, insieme, controversie irrisolvibili. Con la chiave
            # configurata (produzione) questo ramo non si attiva mai e il gate di ruolo resta
            # intatto: 'supporto' continua a non toccare i soldi.
            return "admin"
        fornita = headers.get("X-Admin-Key", "") or headers.get("x-admin-key", "")
        if fornita and _h.compare_digest(str(fornita), str(self._admin_key)):
            return "admin"                       # ROOT = admin pieno
        tok = headers.get("X-Admin-Op", "") or headers.get("x-admin-op", "")
        if not tok:
            return None
        d = self._verifica_op(tok)
        if not d:
            return None
        aa = getattr(self._sys, "admin_accounts", None)
        if aa is not None:
            return aa.ruolo_attivo(d["email"])   # revocato/cambiato -> None/nuovo ruolo, all'istante
        return d.get("ruolo")

    def _puo_azione(self, headers, azione):
        """Il RUOLO di chi agisce puo' compiere questa azione? (fase192: 'supporto' fa letture e
        assistenza ma NON soldi/moderazione distruttiva; 'admin'/root = tutto). La ROOT resta piena."""
        try:
            from fase192_admin_accounts import puo
            return puo(self._ruolo_operatore(headers), azione)
        except Exception:
            return True

    def _auth_con_rate(self, tipo, fornita, atteso, headers) -> bool:
        """Confronto costante della chiave + BUTTAFUORI per IP sui TENTATIVI FALLITI
        (brute-force della chiave via header). Controlla il lockout PRIMA: un IP che ha
        gia' sbagliato N volte e' negato in blocco finche' non scade (anche se il 6°
        tentativo fosse la chiave giusta: chi ha la chiave non la indovina a raffica).
        La chiave giusta AZZERA il contatore -> il legittimo non e' mai penalizzato per
        quanti request faccia. IP diverso = non toccato. IP vuoto (test diretti) = nessun
        throttle (in prod nginx passa sempre X-Forwarded-For)."""
        import hmac
        rl = self._rate
        ip = self._client_ip(headers)
        if rl is None or not ip:
            return hmac.compare_digest(fornita.encode("utf-8", "surrogatepass"), atteso.encode("utf-8", "surrogatepass"))
        chiave = "authkey-%s:%s" % (tipo, ip)
        consentito, attesa = rl.consenti(chiave)
        if not consentito:
            logger.warning("RATE-LIMIT %s-key BLOCCATO 429: ip=%s attesa=%ds",
                           tipo, ip, attesa)
            return False           # IP in lockout: negato in blocco
        ok = hmac.compare_digest(fornita.encode("utf-8", "surrogatepass"), atteso.encode("utf-8", "surrogatepass"))
        if ok:
            rl.riuscito(chiave)    # chiave giusta: azzera lo storico dei fallimenti
            return True
        bloccato, dur = rl.fallito(chiave)
        if bloccato:
            logger.warning("RATE-LIMIT %s-key: SOGLIA superata, lockout %ds ip=%s",
                           tipo, dur, ip)
        return False

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

    def _admin_alloggi(self, query, headers):
        """FIELD operativo PAGINATO + FILTRATO: annunci di ogni host/stato, 20 per pagina,
        filtri [id][host_id][stato] fatti DAL DATABASE (WHERE + COUNT + LIMIT/OFFSET). Al
        client arrivano solo 20 record, mai la piattaforma intera. AUDIT: ogni ricerca su
        app.log persistente (chi ha filtrato per cosa)."""
        if not self._auth_admin(headers):
            return 401, {"errore": "unauthorized"}

        def _int(v):
            try:
                return int(str(v))
            except Exception:
                return None
        page = _int(query.get("page")) or 1
        page = max(1, min(page, 10 ** 6))
        limit = _int(query.get("limit")) or 20
        limit = max(1, min(20, limit))          # Field: MAI più di 20 per pagina
        id_num = _int(query.get("id"))
        host_id = query.get("host_id") or None
        stato = query.get("stato") or None
        citta = query.get("citta") or None
        try:
            rep = self._sys.catalogo.tutti_alloggi_pagina(
                id_num=id_num, host_id=host_id, stato=stato, citta=citta,
                limit=limit, offset=(page - 1) * limit)
        except Exception:
            logger.error("admin alloggi: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        totale = int(rep.get("totale", 0))
        # AUDIT immutabile della ricerca (Field): chi, da dove, con quali filtri.
        criteri = ",".join("%s=%s" % (k, v) for k, v in
                           (("id", id_num), ("host", host_id), ("stato", stato),
                            ("citta", citta)) if v)
        logger.info("AUDIT admin alloggi: ip=%s filtri=[%s] page=%d -> %d risultati",
                    self._client_ip(headers), criteri or "nessuno", page, totale)
        return 200, {"alloggi": rep.get("alloggi", []), "page": page, "limit": limit,
                     "totale": totale, "pagine": max(1, -(-totale // limit))}

    def _admin_search(self, query, headers):
        """RICERCA OPERATIVA unificata (Field, Incremento 7): UNA barra per annunci
        (slug/titolo/citta/ID), host (id/email/nome) e prenotazioni (riferimento/email
        ospite). PAGINATA per dominio (stessa pagina sui tre, prev/next lato UI).
        FILTRO DI SICUREZZA a WHITELIST: escono SOLO campi operativi — MAI dati fiscali
        (CF/P.IVA/IBAN), MAI log/hash/roba del Bunker. Wildcard neutralizzate negli store.
        AUDIT di ogni ricerca su app.log (chi, da dove, cosa)."""
        if not self._auth_admin(headers):
            return 401, {"errore": "unauthorized"}
        q = str(query.get("q") or "").strip()
        # minimo 2 caratteri (anti-scan), MA un ID numerico corto (es. "7") e' legittimo
        if len(q) < 2 and not q.isdigit():
            return 422, {"errore": "termine_troppo_corto", "minimo": 2}
        if len(q) > 120:
            q = q[:120]

        def _int(v, d):
            try:
                return max(1, min(int(str(v)), 10 ** 6))
            except Exception:
                return d
        pagina = _int(query.get("page"), 1)
        limit = min(20, _int(query.get("limit"), 10))
        off = (pagina - 1) * limit
        out = {"q": q, "page": pagina, "limit": limit,
               "annunci": [], "host": [], "prenotazioni": [],
               "totali": {"annunci": 0, "host": 0, "prenotazioni": 0}}
        cat = getattr(self._sys, "catalogo", None)
        reg = getattr(self._sys, "registro_host", None)
        pp = getattr(self._sys, "pagamenti_pendenti", None)
        try:
            if cat is not None and hasattr(cat, "cerca_annunci_admin"):
                r = cat.cerca_annunci_admin(q, limit=limit, offset=off)
                out["annunci"], out["totali"]["annunci"] = r["alloggi"], r["totale"]
            if reg is not None and hasattr(reg, "cerca_host"):
                r = reg.cerca_host(q, limit=limit, offset=off)
                out["host"], out["totali"]["host"] = r["host"], r["totale"]
            if pp is not None and hasattr(pp, "cerca_prenotazioni"):
                r = pp.cerca_prenotazioni(q, limit=limit, offset=off)
                out["prenotazioni"] = r["prenotazioni"]
                out["totali"]["prenotazioni"] = r["totale"]
        except Exception:
            logger.error("admin search: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        out["totale"] = sum(out["totali"].values())
        logger.info("AUDIT admin search: ip=%s q=%r page=%d -> %d risultati "
                    "(annunci=%d host=%d pren=%d)", self._client_ip(headers), q[:60],
                    pagina, out["totale"], out["totali"]["annunci"],
                    out["totali"]["host"], out["totali"]["prenotazioni"])
        return 200, out

    def _admin_audit(self, query, headers):
        """FINANCIAL AUDIT CONSOLE (fase181): scheda contabile unica da QUALSIASI id
        (riferimento/BVIP-code/ND-NC/host_id) + semaforo integrita' 4 stati + shadow-check
        Stripe (2s). READ-ONLY provato. Admin-auth; whitelist campi (mai dati fiscali)."""
        if not self._auth_admin(headers):
            return 401, {"errore": "unauthorized"}
        termine = str(query.get("id") or "").strip()
        if not termine:
            return 422, {"errore": "id_mancante"}
        try:
            from fase181_audit_console import componi, stripe_session_fetch
            sk = getattr(getattr(self._sys, "config", None), "stripe_secret_key", "") or ""
            check = ((lambda cs: stripe_session_fetch(sk, cs)) if sk else None)
            scheda = componi(self._sys, termine, stripe_check=check)
        except Exception:
            logger.error("audit console: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        sem = (scheda.get("semaforo") or {}).get("complessivo", "-")
        logger.info("AUDIT console: ip=%s id=%r tipo=%s semaforo=%s",
                    self._client_ip(headers), termine[:60], scheda.get("tipo"), sem)
        return 200, scheda

    # ── STRIPE IDENTITY (Incremento 11): verifica documentale AUTOMATICA ─────
    @staticmethod
    def _identity_key():
        import os as _os
        return _os.environ.get("STRIPE_IDENTITY_KEY", "").strip()

    def _kyc_sync(self, host_id):
        """Se la verifica e' 'in_corso', chiede a Stripe lo stato REALE (2s, read-only,
        MAI il report: quello contiene PII e resta da Stripe) e transita il registro.
        Ritorna lo stato aggiornato."""
        kyc = getattr(self._sys, "kyc", None)
        if kyc is None:
            return "non_disponibile"
        stato = kyc.stato(host_id)
        chiave = self._identity_key()
        if stato == "in_corso" and chiave:
            from fase143_kyc_host import stripe_identity_stato
            remoto = stripe_identity_stato(chiave, kyc.sessione(host_id))
            if remoto == "verified":
                kyc.conferma(host_id, "verificato")
                logger.warning("KYC IDENTITY VERIFICATO | HOST_ID: %s (Stripe)", host_id)
                # L'host si e' verificato DOPO aver firmato: chiudo ora il legame
                # identita↔contratto, cosi' la prova diventa completa comunque.
                self._lega_identita_se_possibile(
                    getattr(self._sys, "accettazioni", None), host_id)
            elif remoto == "canceled":
                kyc.conferma(host_id, "respinto")     # ritentabile (respinto -> in_corso)
            stato = kyc.stato(host_id)
        return stato

    def _host_kyc_stato(self, query, headers):
        """L'host vede il SUO stato di verifica identita' (+ sync live se in corso)."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        hid = self._host_id_da_token(headers)
        if not (isinstance(hid, str) and hid):
            return 422, {"errore": "host_id_mancante"}
        return 200, {"configurato": bool(self._identity_key()
                                         and getattr(self._sys, "kyc", None) is not None),
                     "stato": self._kyc_sync(hid)}

    def _host_kyc_avvia(self, body, headers):
        """L'host avvia la verifica documentale: sessione HOSTED Stripe Identity (il
        documento va dal suo telefono a Stripe, MAI da noi). GATED da STRIPE_IDENTITY_KEY:
        senza chiave -> 503 onesto (la macchina e' pronta, si accende con la chiave)."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        hid = self._host_id_da_token(headers)
        kyc = getattr(self._sys, "kyc", None)
        chiave = self._identity_key()
        if kyc is None or not chiave:
            return 503, {"errore": "identity_non_configurato"}
        if not (isinstance(hid, str) and hid):
            return 422, {"errore": "host_id_mancante"}
        if kyc.stato(hid) == "verificato":
            return 200, {"ok": True, "stato": "verificato", "url": ""}
        from fase143_kyc_host import stripe_identity_crea
        ritorno = (self._base_url or "https://bookinvip.com") + "/host.html?identity=fatto"
        esito = stripe_identity_crea(chiave, hid, ritorno)
        if not esito:
            return 503, {"errore": "sessione_non_creata"}
        if not kyc.registra_avvio(hid, esito["id"]):
            return 409, {"errore": "gia_in_corso", "stato": kyc.stato(hid)}
        logger.info("KYC IDENTITY AVVIATO | HOST_ID: %s | SESSIONE: %s", hid, esito["id"])
        return 200, {"ok": True, "stato": "in_corso", "url": esito["url"]}

    # ── KYC DASHBOARD "Verifiche & Legale" (Incremento 10) ──────────────────
    def _stato_documenti_host(self, h):
        """Stato composito dei 'documenti' che DAVVERO custodiamo (mai carte d'identita':
        quelle restano al provider — DSA art.30 ammette l'identificazione elettronica):
        contratto firmato (fase163), dati fiscali DAC7, Stripe Connect, verifica manuale."""
        acc = getattr(self._sys, "accettazioni", None)
        contratto = False
        if acc is not None:
            try:
                contratto = bool(acc.elenco(h["host_id"]))
            except Exception:
                contratto = False
        fiscale = not self._dac7_mancanti(h)
        stripe_ok = bool(h.get("stripe_account_id"))
        ver = h.get("verifica_stato") or ""
        # Incr.11: stato Stripe Identity (DOPPIA SICUREZZA: colonna informativa —
        # la verifica MANUALE del super-admin resta SOVRANA per l'in_regola)
        kyc = getattr(self._sys, "kyc", None)
        identity = kyc.stato(h["host_id"]) if kyc is not None else "non_disponibile"
        completo = contratto and fiscale and stripe_ok and ver == "verificato"
        return {"contratto": contratto, "fiscale": fiscale, "stripe": stripe_ok,
                "verifica": ver, "identity": identity, "in_regola": completo}

    def _admin_verifiche(self, query, headers):
        """LISTA 'Verifiche & Legale' (admin): ogni host con lo stato documenti composito
        + contatori. Filtri: q (id/email/nome via cerca_host) e stato
        (in_regola|incompleti|revocati|verificati). AUDIT di ogni consultazione."""
        if not self._auth_admin(headers):
            return 401, {"errore": "unauthorized"}
        reg = getattr(self._sys, "registro_host", None)
        if reg is None:
            return 503, {"errore": "registro_non_attivo"}
        q = str(query.get("q") or "").strip()
        filtro = str(query.get("stato") or "").strip()
        try:
            if q:
                # cerca_host trova gli id; il pieno (campi verifica) si ricarica per id
                base = []
                for r in reg.cerca_host(q, limit=50).get("host", []):
                    x = reg.info_host(r["host_id"])
                    if x:
                        x = dict(x)
                        x["host_id"] = r["host_id"]
                        base.append(x)
            else:
                base = reg.elenco_host()
            out, cont = [], {"in_regola": 0, "incompleti": 0, "revocati": 0,
                            "verificati": 0}
            for h in base:
                sd = self._stato_documenti_host(h)
                if sd["verifica"] == "revocato":
                    cont["revocati"] += 1
                elif sd["in_regola"]:
                    cont["in_regola"] += 1
                else:
                    cont["incompleti"] += 1
                if sd["verifica"] == "verificato":
                    cont["verificati"] += 1
                voce = {"host_id": h["host_id"], "email": h.get("email", ""),
                        "ragione_sociale": h.get("ragione_sociale", ""),
                        "tipo_soggetto": h.get("tipo_soggetto", ""), "documenti": sd}
                if filtro == "in_regola" and not sd["in_regola"]:
                    continue
                if filtro == "incompleti" and (sd["in_regola"]
                                               or sd["verifica"] == "revocato"):
                    continue
                if filtro == "revocati" and sd["verifica"] != "revocato":
                    continue
                if filtro == "verificati" and sd["verifica"] != "verificato":
                    continue
                out.append(voce)
        except Exception:
            logger.error("verifiche host: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        logger.info("ADMIN_ACTION | OGGETTO: verifiche_host | AZIONE: Lista (q=%r "
                    "stato=%r) | IP: %s", q[:40], filtro, self._client_ip(headers))
        return 200, {"host": out[:200], "totale": len(out), "contatori": cont}

    @staticmethod
    def _maschera(v, visibili=4):
        v = str(v or "")
        return ("*" * max(0, len(v) - visibili) + v[-visibili:]) if v else ""

    def _admin_verifiche_dettaglio(self, query, headers):
        """DETTAGLIO host (admin): prove del contratto firmato (fase163: quando, IP, hash
        documento, versione, integrita'), completezza fiscale (IBAN/CF MASCHERATI: i dati
        pieni stanno nel FASCICOLO Bunker-gated), Stripe, storia verifica. AUDIT."""
        if not self._auth_admin(headers):
            return 401, {"errore": "unauthorized"}
        hid = str(query.get("host_id") or "").strip()
        reg = getattr(self._sys, "registro_host", None)
        info = (reg.info_host(hid) or None) if (reg is not None and hid) else None
        if info is None:
            return 404, {"errore": "host_non_trovato"}
        acc = getattr(self._sys, "accettazioni", None)
        prove = []
        if acc is not None:
            try:
                # 2026-07-21: il Field (sola chiave admin) vede SOLO lo stato della prova.
                # IP, impronta del testo e firma HMAC sono dati legali/personali: si leggono
                # dal BUNKER (`/api/bunker/prove_legali` o il fascicolo), col secondo fattore.
                prove = [{k: r.get(k) for k in ("documento", "versione", "integra")}
                         for r in acc.elenco(hid)]
            except Exception:
                prove = []
        h = dict(info)
        h["host_id"] = hid
        logger.info("ADMIN_ACTION | OGGETTO: %s | AZIONE: Visualizzazione | IP: %s",
                    hid, self._client_ip(headers))
        return 200, {"host_id": hid, "email": info.get("email", ""),
                     "ragione_sociale": info.get("ragione_sociale", ""),
                     "tipo_soggetto": info.get("tipo_soggetto", ""),
                     "documenti": self._stato_documenti_host(h),
                     "contratto_prove": prove,
                     "fiscale": {"mancanti": self._dac7_mancanti(info),
                                 "paese": info.get("paese", ""),
                                 "iban_maschera": self._maschera(info.get("iban")),
                                 "cf_maschera": self._maschera(info.get("codice_fiscale"))},
                     "verifica": {"stato": info.get("verifica_stato", ""),
                                  "note": info.get("verifica_note", ""),
                                  "ts": info.get("verifica_ts", ""),
                                  "da": info.get("verifica_da", "")},
                     # Incr.11: stato Stripe Identity SINCRONIZZATO live (2s) all'apertura
                     "identity": self._kyc_sync(hid)}

    def _admin_verifiche_fascicolo(self, query, headers):
        """FASCICOLO LEGALE completo (BUNKER-gated: dati fiscali PIENI + prove contratto +
        storia verifica) — il "download batch" ONESTO: i documenti che DAVVERO custodiamo.
        AUDIT: Download."""
        if not self._auth_admin(headers):
            return 401, {"errore": "unauthorized"}
        if not self._bunker_ok_o_field(headers, azione="fascicolo_host"):
            return 403, {"errore": "bunker_richiesto"}
        hid = str(query.get("host_id") or "").strip()
        reg = getattr(self._sys, "registro_host", None)
        info = (reg.info_host(hid) or None) if (reg is not None and hid) else None
        if info is None:
            return 404, {"errore": "host_non_trovato"}
        acc = getattr(self._sys, "accettazioni", None)
        prove = []
        if acc is not None:
            try:
                prove = acc.elenco(hid)
            except Exception:
                prove = []
        fc = getattr(self._sys, "finanza", None)
        debiti = fc.debiti_host(hid) if fc is not None else []
        logger.warning("ADMIN_ACTION | OGGETTO: %s | AZIONE: Download fascicolo | IP: %s",
                       hid, self._client_ip(headers))
        return 200, {"fascicolo": {"host_id": hid, "identita": {
                         k: info.get(k, "") for k in ("email", "ragione_sociale",
                                                       "telefono", "tipo_soggetto")},
                     "fiscale": {k: info.get(k, "") for k in
                                 ("codice_fiscale", "partita_iva", "indirizzo_fiscale",
                                  "paese", "iban", "data_nascita")},
                     "contratto_prove": prove,
                     "verifica": {k: info.get("verifica_" + k, "") for k in
                                  ("stato", "note", "ts", "da")},
                     "stripe_account": info.get("stripe_account_id", ""),
                     "identity": {"stato": (getattr(self._sys, "kyc", None).stato(hid)
                                            if getattr(self._sys, "kyc", None) else
                                            "non_disponibile"),
                                  "session_ref": (getattr(self._sys, "kyc", None)
                                                  .sessione(hid)
                                                  if getattr(self._sys, "kyc", None)
                                                  else "")},
                     "debiti": debiti,
                     "nota_legale": ("Documenti d'identita' MAI conservati da BookinVIP: "
                                     "identificazione elettronica via provider (DSA art.30)"
                                     )}}

    def _admin_verifica_stato(self, body, headers):
        """APPROVA/REVOCA la verifica (BUNKER-gated: la revoca FERMA i bonifici).
        motivo obbligatorio per la revoca; alla ri-verifica i payout in hold RIPARTONO."""
        if not self._auth_admin(headers):
            return 401, {"errore": "unauthorized"}
        if not self._bunker_ok_o_field(headers, azione="verifica_host"):
            return 403, {"errore": "bunker_richiesto"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        hid = str(dati.get("host_id") or "").strip()
        stato = str(dati.get("stato") or "").strip()
        motivo = str(dati.get("motivo") or "").strip()
        if stato not in ("verificato", "revocato", ""):
            return 422, {"errore": "stato_non_valido"}
        if stato == "revocato" and not motivo:
            return 422, {"errore": "motivo_obbligatorio"}   # una revoca ha sempre un perche'
        reg = getattr(self._sys, "registro_host", None)
        if reg is None or not hid:
            return 422, {"errore": "host_id_mancante"}
        ip = self._client_ip(headers)
        if not reg.imposta_verifica(hid, stato, note=motivo, da="super-admin@" + ip):
            return 404, {"errore": "host_non_trovato"}
        logger.warning("ADMIN_ACTION | OGGETTO: %s | AZIONE: Verifica->%s | MOTIVO: %s | "
                       "IP: %s", hid, stato or "non_verificato", motivo or "-", ip)
        riprovati = 0
        if stato == "verificato":                # sblocco: i payout in hold ripartono
            pd = getattr(self._sys, "payout", None)
            if pd is not None:
                try:
                    for r in pd.elenca(hid, stato="maturato"):
                        self._trasferisci_all_host(r["prenotazione_id"], int(r["minori"]))
                        riprovati += 1
                    if riprovati:
                        logger.warning("PAYOUT_HOLD_RELEASED | HOST_ID: %s | RITENTATI: %d"
                                       " | MOTIVO: VERIFICA_RIPRISTINATA", hid, riprovati)
                except Exception:
                    logger.warning("retry payout post-verifica fallito (ISOLATO)",
                                   exc_info=True)
        return 200, {"ok": True, "host_id": hid, "stato": stato,
                     "payout_riprovati": riprovati}

    def _admin_storno_penale(self, body, headers):
        """STORNO PENALE (tool super-admin, 5ª operazione distruttiva): corregge una ND
        sbagliata con la NOTA DI CREDITO contraria (fase177.storna_penale: giornale mai
        modificato, debito azzerato, riscosso restituito in da_pagare per bonifico
        MANUALE). DOPPIO CANCELLO: chiave admin + sessione Bunker (come le altre 4)."""
        if not self._auth_admin(headers):
            return 401, {"errore": "unauthorized"}
        if not self._bunker_ok_o_field(headers, azione="storno_penale"):
            return 403, {"errore": "bunker_richiesto"}
        if not self._puo_azione(headers, "storno_penale"):   # ruolo 'supporto' non muove soldi
            return 403, {"errore": "permesso_negato_ruolo"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        nota_id = str(dati.get("nota_id") or "").strip()
        motivo = str(dati.get("motivo") or "").strip()
        if not nota_id:
            return 422, {"errore": "nota_id_mancante"}
        if not motivo:
            return 422, {"errore": "motivo_obbligatorio"}   # una correzione ha SEMPRE un perche'
        fc = getattr(self._sys, "finanza", None)
        if fc is None or not hasattr(fc, "storna_penale"):
            return 503, {"errore": "finanza_non_attiva"}
        esito = fc.storna_penale(nota_id=nota_id, motivo=motivo,
                                 payout=getattr(self._sys, "payout", None),
                                 emittente="super-admin@" + self._client_ip(headers))
        if esito is None:
            n = fc.nota(nota_id)
            if n is None or n.get("tipo") != "debito":
                return 404, {"errore": "nota_non_trovata_o_non_ND"}
            return 503, {"errore": "giornale_non_scrivibile"}
        return 200, esito

    def _admin_alloggio_stato(self, body, headers):
        """Admin: cambia lo stato di QUALSIASI annuncio (sospendi/ripubblica) per slug."""
        if not self._auth_admin(headers):
            return 401, {"errore": "unauthorized"}
        if not self._bunker_ok_o_field(headers, azione="alloggio_stato"):
            return 403, {"errore": "bunker_richiesto"}
        # SCALATA DI PRIVILEGI (difetto PROVATO 2026-07-28, test_ruoli_admin_adversarial):
        # 'alloggio_stato' e' in AZIONI_SOLO_ADMIN (fase192) ma il gate di RUOLO non veniva
        # MAI chiamato -> un operatore 'supporto' sospendeva/ripubblicava QUALSIASI annuncio.
        if not self._puo_azione(headers, "alloggio_stato"):   # 'supporto' non modera
            return 403, {"errore": "permesso_negato_ruolo"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        slug, stato = dati.get("slug"), dati.get("stato")
        if not (isinstance(slug, str) and slug and isinstance(stato, str)):
            return 422, {"errore": "campi_non_validi"}
        ok = self._sys.catalogo.imposta_stato(slug, stato)
        return (200 if ok else 422), {"stato": stato if ok else "rifiutato"}

    # ── BUNKER (super-admin, fase180): 2FA + sessione blindata ──────────────
    def _bunker_login(self, body, headers):
        """Ingresso nel Bunker: serve la chiave admin (Field) + il codice TOTP (2° fattore).
        Ritorna una SESSIONE firmata 15 min legata all'IP. AUDIT: ogni tentativo (riuscito
        o fallito) su app.log persistente; accesso non autorizzato/manomissione = CRITICO."""
        ip = self._client_ip(headers)
        bunker = getattr(self._sys, "bunker", None)
        if bunker is None or not bunker.configurato:
            return 503, {"errore": "bunker_non_configurato"}
        # rate-limit dedicato al bunker (per IP): il 2FA non si forza a raffica
        k = "bunker-login:" + ip if (self._rate is not None and ip) else ""
        if k:
            ok, attesa = self._rate.consenti(k)
            if not ok:
                logger.critical("BUNKER login BLOCCATO (rate-limit) ip=%s attesa=%ds", ip, attesa)
                return 429, {"errore": "troppi_tentativi", "riprova_tra_sec": attesa}
        # 1° fattore: chiave admin. Se sbagliata -> NON autorizzato (loggato critico).
        if not self._auth_admin(headers):
            logger.critical("BUNKER: chiave admin ERRATA (tentativo intrusione) ip=%s", ip)
            if k:
                self._rate.fallito(k)
            return 401, {"errore": "unauthorized"}
        dati = self._json(body) or {}
        esito = bunker.verifica_secondo_fattore(dati.get("codice"))
        if not esito:
            logger.critical("BUNKER: 2FA FALLITO (codice errato) ip=%s", ip)
            if k:
                self._rate.fallito(k)
            return 403, {"errore": "2fa_non_valido"}
        if esito == "break_glass":
            logger.critical("BUNKER: ingresso con BREAK-GLASS (recupero d'emergenza) ip=%s", ip)
        sess = bunker.crea_sessione(ip)
        if not sess:
            return 503, {"errore": "sessione_non_creata"}
        if k:
            self._rate.riuscito(k)
        logger.warning("BUNKER: ingresso OK (%s) ip=%s", esito, ip)
        ttl = self._GATE_TTL["bunker"]              # gatekeeper: cookie di pagina bunker (15 min)
        return 200, {"ok": True, "sessione": sess, "scade_tra_sec": 15 * 60, "modo": esito,
                     "_cookie": [("bv_bunker", self._gate_firma("bunker", ttl), ttl)]}

    def _bunker_auth(self, headers, *, azione=""):
        """True se il chiamante ha una sessione Bunker valida (X-Bunker-Session + IP).
        Ogni negazione su un'azione protetta e' loggata CRITICA (tentativo di operare senza
        bunker = possibile intrusione)."""
        bunker = getattr(self._sys, "bunker", None)
        ip = self._client_ip(headers)
        if bunker is None or not bunker.configurato:
            return False
        tok = headers.get("X-Bunker-Session", "") or headers.get("x-bunker-session", "")
        r = bunker.valida_sessione(tok, ip)
        if not r.get("ok"):
            logger.critical("BUNKER: accesso NEGATO azione=%s motivo=%s ip=%s",
                            azione or "?", r.get("motivo"), ip)
            return False
        logger.warning("BUNKER: azione '%s' autorizzata ip=%s", azione or "?", ip)
        return True

    def _bunker_ok_o_field(self, headers, *, azione):
        """ENFORCEMENT least-privilege sulle operazioni DISTRUTTIVE (Incremento 3).
        Ritorna True se l'operazione puo' procedere:
          - Bunker NON configurato (super-admin non ancora impostato) -> True: l'enforcement
            e' INATTIVO, resta la sola chiave admin (mai chiudersi fuori prima di aver messo
            in piedi il Bunker; i test che non configurano il Bunker restano invariati);
          - Bunker configurato -> serve una SESSIONE BUNKER valida (2° muro). Senza -> False
            (il chiamante risponde 403 'bunker_richiesto', loggato CRITICO da `_bunker_auth`).
        Cosi' 'nessuno esegue operazioni distruttive senza il bunker' vale appena il
        super-admin e' attivo, senza mai paralizzare la piattaforma prima."""
        bunker = getattr(self._sys, "bunker", None)
        if bunker is None or not bunker.configurato:
            return True
        return self._bunker_auth(headers, azione=azione)

    # ── DAC7 (reporting fiscale UE, Incremento 5) ───────────────────────────
    @staticmethod
    def _dac7_mancanti(h):
        """Campi fiscali DAC7 mancanti per un host (dict da elenco_host/info_host)."""
        manca = []
        if not (h.get("codice_fiscale") or h.get("partita_iva")):
            manca.append("codice_fiscale/partita_iva")
        for c in ("indirizzo_fiscale", "paese", "iban"):
            if not h.get(c):
                manca.append(c)
        return manca

    def _host_dati_fiscali(self, body, headers):
        """L'HOST fornisce i propri dati fiscali (DAC7). Host-auth: solo per sé stesso."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        reg = getattr(self._sys, "registro_host", None)
        if reg is None:
            return 503, {"errore": "registro_non_attivo"}
        hid = self._host_id_da_token(headers)
        dati = self._json(body)
        if not (isinstance(hid, str) and hid):
            return 422, {"errore": "host_id_mancante"}
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        ok = reg.imposta_dati_fiscali(hid, dati)
        info = reg.info_host(hid) or {}
        manca = self._dac7_mancanti(info)
        # SBLOCCO AUTOMATICO (Incremento 6): dati ora completi -> i payout rimasti in hold
        # ('maturato' + host bloccato) vengono RITENTATI subito. Idempotente e sicuro:
        # _trasferisci_all_host rifa' da solo TUTTE le guardie (pagato online? Stripe
        # collegato? non gia' partito?) e ignora in silenzio cio' che non e' trasferibile.
        riprovati = 0
        if ok and not manca:
            pd = getattr(self._sys, "payout", None)
            if pd is not None:
                try:
                    for r in pd.elenca(hid, stato="maturato"):
                        self._trasferisci_all_host(r["prenotazione_id"], int(r["minori"]))
                        riprovati += 1
                    if riprovati:
                        logger.warning("PAYOUT_HOLD_RELEASED | HOST_ID: %s | RITENTATI: %d "
                                       "| MOTIVO: DATI_FISCALI_COMPLETATI", hid, riprovati)
                except Exception:
                    logger.warning("sblocco payout post-dati-fiscali fallito (ISOLATO: "
                                   "restano 'maturato', nulla perso)", exc_info=True)
        return (200 if ok else 422), {"salvato": bool(ok), "mancanti": manca,
                                      "payout_riprovati": riprovati}

    def _host_dac7_stato(self, query, headers):
        """AVVISO nel pannello host (Incremento 6): l'host DEVE sapere perche' i bonifici
        non arrivano. Ritorna: dati mancanti, se i suoi payout sono in HOLD DAC7 e quanto
        c'e' fermo (somma dei 'maturato'). Host-auth, read-only, solo per se' stesso."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        hid = self._host_id_da_token(headers)
        if not (isinstance(hid, str) and hid):
            return 422, {"errore": "host_id_mancante"}
        reg = getattr(self._sys, "registro_host", None)
        info = (reg.info_host(hid) or {}) if reg is not None else {}
        manca = self._dac7_mancanti(info) if info else []
        bloccato, _m = self._dac7_payout_bloccato(hid)
        fermi = 0
        if bloccato:
            pd = getattr(self._sys, "payout", None)
            if pd is not None:
                try:
                    fermi = sum(int(r["minori"]) for r in pd.elenca(hid, stato="maturato"))
                except Exception:
                    fermi = 0
        return 200, {"mancanti": manca, "payout_bloccati": bool(bloccato),
                     "payout_fermi_cents": fermi,
                     "dati": {c: info.get(c, "") for c in
                              ("codice_fiscale", "partita_iva", "indirizzo_fiscale",
                               "paese", "iban", "tipo_soggetto")}}

    def _bunker_dac7_conformita(self, query, headers):
        """SALA CONTROLLO — STATO CONFORMITÀ HOST (DAC7): elenca gli host e segnala chi NON
        ha i dati fiscali completi, con il loro volume (prenotazioni/ricavi anno) e se sono
        REPORTABILI per legge (soglia UE 30 pren O €2000). Read-only, sessione Bunker."""
        if not self._bunker_auth(headers, azione="dac7_conformita"):
            return 403, {"errore": "bunker_richiesto"}
        reg = getattr(self._sys, "registro_host", None)
        fc = getattr(self._sys, "finanza", None)
        if reg is None:
            return 503, {"errore": "registro_non_attivo"}
        try:
            import datetime as _dt
            from fase100_dac7 import valuta_dac7
            anno = self._anno_valido(query.get("anno"))
            agg = fc.aggrega_dac7(anno) if fc is not None else {}
            out, tot_incompleti, tot_reportabili, tot_urgenti = [], 0, 0, 0
            for h in reg.elenco_host():
                a = agg.get(h["host_id"], {})
                n = int(a.get("n", 0))
                lordo = int(a.get("lordo", 0))
                manca = self._dac7_mancanti(h)
                rep = valuta_dac7(n, lordo, True).deve_segnalare   # solo soglia
                completo = not manca
                urgente = bool(rep and not completo)  # da segnalare per legge MA dati incompleti
                if not completo:
                    tot_incompleti += 1
                if rep:
                    tot_reportabili += 1
                if urgente:
                    tot_urgenti += 1
                # Incr.6: per gli URGENTI mostra anche i payout in HOLD (soldi fermi finche'
                # non completano i dati). Solo per loro: query mirata, il resto non pesa.
                fermi = 0
                if urgente:
                    pd = getattr(self._sys, "payout", None)
                    if pd is not None:
                        try:
                            fermi = sum(int(r["minori"])
                                        for r in pd.elenca(h["host_id"], stato="maturato"))
                        except Exception:
                            fermi = 0
                out.append({"host_id": h["host_id"], "ragione_sociale": h["ragione_sociale"],
                            "email": h["email"], "completo": completo, "mancanti": manca,
                            "prenotazioni": n, "ricavi_cents": lordo, "reportabile": rep,
                            "urgente": urgente, "payout_fermi_cents": fermi})
            out.sort(key=lambda x: (not x["urgente"], x["completo"], -x["ricavi_cents"]))
        except Exception:
            logger.error("dac7 conformita: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        return 200, {"anno": anno, "host": out, "totale": len(out),
                     "incompleti": tot_incompleti, "reportabili": tot_reportabili,
                     "urgenti": tot_urgenti}

    @staticmethod
    def _anno_valido(v):
        import datetime as _dt
        try:
            a = int(str(v))
            if 2020 <= a <= 2100:
                return a
        except Exception:
            pass
        return _dt.datetime.utcnow().year - 1        # default: anno fiscale precedente

    @staticmethod
    def _cella_csv_sicura(v):
        """ANTI FORMULA-INJECTION (OWASP CSV injection): i report fiscali si aprono in
        Excel/LibreOffice, e una cella che inizia con = + - @ (o tab/CR) viene ESEGUITA
        come formula — e ragione sociale / indirizzo / titoli immobili li scrive l'HOST.
        Prefisso apostrofo = testo. I numeri veri (anche negativi) passano intatti."""
        if not isinstance(v, str) or not v:
            return v
        import re as _re
        if v[0] in "=+-@\t\r" and not _re.match(r"^-?\d+([.,]\d+)?$", v):
            return "'" + v
        return v

    def genera_dac7_csv(self, *, anno, ip=""):
        """GENERATORE del report DAC7 in STREAMING (zero RAM, stesso stile dell'estratto):
        una riga per host REPORTABILE con identita' + dati fiscali + remunerazione annuale
        e per trimestre + immobili. Chiude col footer '# FINE REPORT DAC7 - INTEGRITÀ:
        <hash>' (hash di TUTTE le righe emesse) o '# NON CHIUSO / CORROTTO' su errore.
        Audit: DAC7_REPORT_GENERATED. Nessun file su disco (mai scritto)."""
        import csv as _csv
        import datetime as _dt
        import hashlib as _hl
        import io as _io
        from fase100_dac7 import valuta_dac7
        reg = getattr(self._sys, "registro_host", None)
        fc = getattr(self._sys, "finanza", None)
        cat = getattr(self._sys, "catalogo", None)
        gen = _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ")
        yield "# BookinVIP - Report DAC7 (Direttiva UE 2021/514) - anno %s\r\n" % anno
        yield "# generato_utc,%s\r\n" % gen
        yield "# nota,importi in EUR; reportabili = >=30 prenotazioni O >=2000 EUR\r\n\r\n"
        yield ("host_id,ragione_sociale,tipo_soggetto,codice_fiscale,partita_iva,paese,"
               "indirizzo_fiscale,iban,dati_completi,n_prenotazioni,"
               "corrispettivo_lordo_eur,commissioni_eur,tasse_soggiorno_eur,rimborsi_eur,"
               "Q1_eur,Q2_eur,Q3_eur,Q4_eur,notti_anno,immobili\r\n")
        acc = _hl.sha256()
        n_host = 0
        errore = False
        try:
            agg = fc.aggrega_dac7(anno) if fc is not None else {}
            pp = getattr(self._sys, "pagamenti_pendenti", None)
            for h in (reg.elenco_host() if reg is not None else []):
                a = agg.get(h["host_id"])
                if not a:
                    continue
                if not valuta_dac7(int(a["n"]), int(a["lordo"]), True).deve_segnalare:
                    continue                          # solo i REPORTABILI per legge
                # GIORNI-AFFITTO PER IMMOBILE (requisito DAC7): notti locate nell'anno,
                # dalla verita' del money-path (prenotazioni PAGATE, soggiorno nell'anno).
                notti = {}
                if pp is not None:
                    try:
                        notti = pp.notti_per_alloggio(h["host_id"], int(anno)) or {}
                    except Exception:
                        notti = {}
                notti_tot = sum(v.get("notti", 0) for v in notti.values())
                voci, visti = [], set()
                if cat is not None:
                    try:
                        for x in (cat.alloggi_host(h["host_id"], limit=50) or []):
                            slug = str(x.get("slug", ""))
                            visti.add(slug)
                            nx = notti.get(slug)
                            base = "%s (%s)" % (x.get("titolo", ""), x.get("citta", ""))
                            voci.append(base + (" - %d notti/%d pren" %
                                                (nx["notti"], nx["pren"]) if nx else ""))
                    except Exception:
                        voci = []
                # onesta': notti locate su annunci POI CANCELLATI vanno comunque dichiarate
                for slug, nx in sorted(notti.items()):
                    if slug not in visti:
                        voci.append("%s (annuncio rimosso) - %d notti/%d pren"
                                    % (slug, nx["notti"], nx["pren"]))
                immobili = " | ".join(voci)
                eur = lambda c: "%.2f" % (int(c) / 100.0)
                riga = [h["host_id"], h["ragione_sociale"], h.get("tipo_soggetto", ""),
                        h.get("codice_fiscale", ""), h.get("partita_iva", ""),
                        h.get("paese", ""), h.get("indirizzo_fiscale", ""), h.get("iban", ""),
                        "SI" if not self._dac7_mancanti(h) else "NO",
                        a["n"], eur(a["lordo"]), eur(a["commissioni"]), eur(a["tasse"]),
                        eur(a["rimborsi"]), eur(a["trim"][1]), eur(a["trim"][2]),
                        eur(a["trim"][3]), eur(a["trim"][4]), notti_tot, immobili]
                buf = _io.StringIO()
                _csv.writer(buf).writerow([self._cella_csv_sicura(x) for x in riga])
                testo = buf.getvalue()
                acc.update(testo.encode("utf-8"))
                n_host += 1
                yield testo
        except Exception:
            logger.error("dac7 report: errore durante lo streaming", exc_info=True)
            errore = True
        if errore:
            yield "\r\n# NON CHIUSO / CORROTTO - errore durante lo streaming\r\n"
        else:
            yield "\r\n# host_reportabili,%d\r\n" % n_host
            yield "# FINE REPORT DAC7 - INTEGRITÀ: %s\r\n" % acc.hexdigest()
        stato = "NON_CHIUSO_CORROTTO" if errore else "SUCCESS"
        logger.warning("DAC7_REPORT_GENERATED | DATA: %s | ANNO: %s | HOST: %d | STATUS: %s | IP: %s",
                       gen, anno, n_host, stato, ip or "?")

    def _bunker_dac7_report(self, query, headers):
        """Report DAC7 via router (test + fallback): concatena il generatore di streaming.
        In produzione l'handler intercetta la rotta e STREAMMA (zero RAM)."""
        if not self._bunker_auth(headers, azione="dac7_report"):
            return 403, {"errore": "bunker_richiesto"}
        anno = self._anno_valido(query.get("anno"))
        try:
            csv_txt = "".join(self.genera_dac7_csv(anno=anno,
                                                   ip=self._client_ip(headers)))
        except Exception:
            logger.error("dac7 report: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        return 200, {"csv": csv_txt, "anno": anno,
                     "integro": ("# FINE REPORT DAC7 - INTEGRITÀ:" in csv_txt)}

    def _stato_battito_guardiano(self) -> str:
        """«ok» · «muto» · «sconosciuto» — lo stato del battito del Guardiano dei soldi,
        esposto su `/api/health` perche' lo legga la testa ESTERNA.

        Perche' passa da qui e non dal file: una sentinella fuori dal server (GitHub Actions,
        o il PC) il volume Docker NON lo vede. Puo' solo fare una richiesta HTTP. Cosi' una
        sola richiesta dice due cose: il sito risponde, e la sentinella dei soldi e' viva.

        ⛔ NON tocca mai `status`. Un Guardiano muto non e' un sito giu': far credere il
        contrario a nginx e a `watchdog.sh` spegnerebbe un sito SANO dentro i monitoraggi, e
        un falso allarme di quel calibro fa piu' danno del difetto (regola ferrea 10).
        ⛔ Se non e' misurabile dice «sconosciuto», mai «ok»: dichiarare sano cio' che non si
        e' guardato e' lo sbaglio S7, e in questa stessa famiglia di indirizzi e' gia'
        costato caro -- `/api/health/db` «saltava i percorsi vuoti e continuava a dire ok»
        sopra una perdita di soldi.
        """
        try:
            import os as _osh
            from fase178_watchdog import (MAX_ETA_BATTITO_SEC,
                                          eta_battito_guardiano_sec)
            dbf = getattr(getattr(self._sys, "config", None), "db_finanza", "") or ""
            eta = eta_battito_guardiano_sec(_osh.path.dirname(dbf))
            if eta is None:
                return "sconosciuto"
            return "ok" if eta <= MAX_ETA_BATTITO_SEC else "muto"
        except Exception:
            # La salute non deve poter fallire per colpa di una diagnosi: un guasto QUI
            # trasformerebbe uno strumento di misura in un guasto del prodotto.
            logger.error("salute: stato del battito non leggibile (ISOLATO)", exc_info=True)
            return "sconosciuto"

    def _bunker_guardiano(self, headers):
        """IL GUARDIANO DEGLI STATI IMPOSSIBILI (fase186) a richiesta: lo stesso controllo
        che gira da solo ogni giorno, eseguito subito e restituito. READ-ONLY, bunker-gated.
        Cerca conti che non tornano con Stripe, escrow bloccati, bonifici fermi o orfani."""
        if not self._bunker_auth(headers, azione="guardiano"):
            return 403, {"errore": "bunker_richiesto"}
        try:
            from fase186_guardiano import scansiona
            return 200, scansiona(self._sys)
        except Exception:
            logger.error("guardiano a richiesta: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}

    def _bunker_invarianti(self, query, headers):
        """AUDITOR INVARIANTI (fase199): scansiona i DB reali e CONTA le violazioni degli invarianti
        di sistema (I1 no-doppia-conferma sovrapposta, ...). READ-ONLY, bunker-gated. Oracolo
        indipendente: NON ripara, DENUNCIA. `ok:true` + 0 violazioni = macchina in stato coerente."""
        if not self._bunker_auth(headers, azione="invarianti"):
            return 403, {"errore": "bunker_richiesto"}
        try:
            from fase199_invarianti import scansiona_db
            rap = scansiona_db(self._data_dir())
        except Exception:
            logger.error("bunker invarianti: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        viol = {k: len(v) for k, v in rap.get("violazioni", {}).items()}
        logger.warning("INVARIANTI_SCAN | letti=%d | violazioni=%r | IP: %s",
                       rap.get("prenotazioni_lette", 0), viol, self._client_ip(headers))
        return 200, {"ok": not viol, "violazioni": viol,
                     "prenotazioni_lette": rap.get("prenotazioni_lette", 0)}

    def _bunker_riconciliazione(self, query, headers):
        """RICONCILIAZIONE STRIPE (fase182, ultimo fantasma del pre-mortem): confronta il
        periodo intero — sessioni PAGATE di Stripe vs 'incasso' del giornale (per
        riferimento, al centesimo) + totali charge/refund/transfer vs giornale.
        READ-ONLY totale. Bunker-gated. GATED dalla chiave Stripe."""
        if not self._bunker_auth(headers, azione="riconciliazione"):
            return 403, {"errore": "bunker_richiesto"}
        sk = getattr(getattr(self._sys, "config", None), "stripe_secret_key", "") or ""
        fc = getattr(self._sys, "finanza", None)
        if not sk or fc is None:
            return 503, {"errore": "stripe_o_finanza_non_configurati"}

        def _int(v, d):
            try:
                return max(1, min(int(str(v)), 365))
            except Exception:
                return d
        giorni = _int(query.get("giorni"), 30)
        try:
            from fase182_riconciliazione import riconcilia
            rep = riconcilia(fc, sk, giorni=giorni)
        except Exception:
            logger.error("riconciliazione: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        logger.warning("RICONCILIAZIONE_ESEGUITA | GIORNI: %d | OK: %s | FANTASMI: "
                       "stripe=%d giornale=%d diversi=%d | IP: %s", giorni, rep["ok"],
                       len(rep["solo_stripe"]), len(rep["solo_giornale"]),
                       len(rep["importo_diverso"]), self._client_ip(headers))
        return 200, rep

    def puo_esportare(self, headers) -> bool:
        """True se il chiamante ha una sessione Bunker valida (usata dall'handler per lo
        streaming diretto sul socket dell'estratto fiscale)."""
        return self._bunker_auth(headers, azione="export_contabile")

    def puo_dac7(self, headers) -> bool:
        """Sessione Bunker valida per lo streaming del report DAC7 (dati PII+finanziari)."""
        return self._bunker_auth(headers, azione="dac7_report")

    def genera_estratto_csv(self, *, ip: str = ""):
        """GENERATORE dell'estratto contabile certificato in STREAMING (Incremento 4.1):
        legge il giornale riga per riga (fase177.stream_giornale, zero RAM), calcola la
        CATENA DI HASH ON-THE-FLY mentre i dati scorrono, e chiude col footer obbligatorio
        '# FINE ESTRATTO - INTEGRITÀ VERIFICATA: <hash>'. Se la catena e' rotta o accade un
        errore durante lo streaming, chiude con '# NON CHIUSO / CORROTTO ...' -> un file
        interrotto NON puo' mai essere preso per buono. Yielda stringhe: l'handler le scrive
        sul socket, i test le concatenano. Nessun file temporaneo (mai scritto su disco)."""
        import csv as _csv
        import datetime as _dt
        import hashlib as _hl
        import io as _io
        fc = getattr(self._sys, "finanza", None)
        gen = _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ")
        yield "# BookinVIP - Estratto contabile certificato (streaming)\r\n"
        yield "# generato_utc,%s\r\n\r\n" % gen
        yield ("seq,data_utc,tipo,riferimento,soggetto,conto_dare,conto_avere,"
               "importo_cents,importo,valuta,causale,emittente,hash\r\n")
        prev = "GENESI"
        n = 0
        rotta = None
        errore = False
        try:
            sorgente = fc.stream_giornale() if fc is not None else iter(())
            for r in sorgente:
                canon = "|".join([r["evento_id"], str(r["ts"]), r["tipo"], r["riferimento"],
                                  r["soggetto"], r["conto_dare"], r["conto_avere"],
                                  str(r["importo_cents"]), r["valuta"], r["causale"],
                                  r["emittente"], r["prev_hash"]])
                h = _hl.sha256(canon.encode("utf-8")).hexdigest()
                if r["prev_hash"] != prev or r["hash"] != h:
                    rotta = r["seq"]
                    break
                prev = r["hash"]
                n += 1
                try:
                    data = _dt.datetime.utcfromtimestamp(int(r["ts"])).strftime(
                        "%Y-%m-%d %H:%M:%S")
                except Exception:
                    data = str(r["ts"])
                imp = int(r["importo_cents"] or 0)
                buf = _io.StringIO()
                _csv.writer(buf).writerow([self._cella_csv_sicura(x) for x in (
                    r["seq"], data, r["tipo"], r["riferimento"], r["soggetto"],
                    r["conto_dare"], r["conto_avere"], imp, "%.2f" % (imp / 100.0),
                    r["valuta"], r["causale"], r["emittente"], r["hash"])])
                yield buf.getvalue()
        except Exception:
            logger.error("estratto streaming: errore durante lo scorrimento", exc_info=True)
            errore = True
        if errore:
            yield "\r\n# NON CHIUSO / CORROTTO - errore durante lo streaming (righe scritte: %d)\r\n" % n
        elif rotta is not None:
            yield "\r\n# NON CHIUSO / CORROTTO - manomissione alla riga %s (righe integre: %d)\r\n" % (rotta, n)
        else:
            yield "\r\n# righe,%d\r\n" % n
            yield "# FINE ESTRATTO - INTEGRITÀ VERIFICATA: %s\r\n" % (prev if n else "VUOTO")
        # AUDIT obbligatorio dell'esportazione (formato richiesto)
        stato = ("INTEGRITÀ_VERIFICATA" if (not errore and rotta is None)
                 else "NON_CHIUSO_CORROTTO")
        logger.warning("EXPORT_FISCALE_STREAM_COMPLETED | DATA: %s | RIGHE: %d | STATUS: %s | IP: %s",
                       gen, n, stato, ip or "?")

    def genera_dossier_legale(self, *, formato: str = "csv", ip: str = ""):
        """DOSSIER LEGALE-FISCALE CERTIFICATO (2026-07-21) — generatore in STREAMING.

        Un solo file che mette insieme cio' che prima era sparso o invisibile:
        anagrafica host · scaglione commissione APPLICATO (dalla fonte unica fase98, mai
        ricalcolato) · prova del contratto (versione, impronta SHA-256 del testo, **IP**,
        dispositivo, **ora UTC**, **firma HMAC-SHA256**, approvazione clausole vessatorie) ·
        prova privacy/GDPR · e in coda il prospetto della TARIFFA TECNICA Stripe, con le
        PERDITE sui rimborsi separate (voce per il commercialista).

        Valore probatorio: nulla e' troncato e il file si chiude con l'impronta SHA-256 di
        TUTTO il contenuto ('FINE DOSSIER'). Se manca quella riga il file NON e' valido.
        Se una prova risulta manomessa il dossier lo dichiara riga per riga (`integra=NO`).
        """
        import csv as _csv
        import datetime as _dt
        import hashlib as _hl
        import io as _io
        import json as _js
        # l'ora DEVE dichiarare il fuso: in un fascicolo legale un orario nudo
        # e' contestabile ("che fuso era?"). E' UTC: si scrive.
        gen = _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        impronta = _hl.sha256()

        def emetti(testo):
            impronta.update(testo.encode("utf-8"))
            return testo

        reg = getattr(self._sys, "registro_host", None)
        acc = getattr(self._sys, "accettazioni", None)
        pp = getattr(self._sys, "pagamenti_pendenti", None)
        cfg = getattr(self._sys, "config", None)
        base = getattr(cfg, "commissione_bps", 1000)
        base = base if isinstance(base, int) and not isinstance(base, bool) else 1000
        promo = bool(getattr(cfg, "promo_lancio_attiva", False))
        from fase98_policy_commissione import stato_scaglione

        def _utc(ts):
            try:
                return _dt.datetime.utcfromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S UTC")
            except Exception:
                return ""

        def riga_host(h):
            """Fotografia completa di UN host: tariffa + prove. Mai dati inventati."""
            st = stato_scaglione(h.get("giorni"), promo_attiva=promo, bps_regime_config=base)
            prove = acc.elenco(h["host_id"]) if acc is not None else []
            contratto = next((p for p in prove if p.get("documento") == "contratto_host"), {})
            privacy = next((p for p in prove if p.get("documento") == "privacy_gdpr"), {})
            try:
                ident = acc.identita_legata(h["host_id"]) if acc is not None else {}
            except Exception:
                ident = {}
            kyc = getattr(self._sys, "kyc", None)
            stato_kyc = ""
            try:
                stato_kyc = (kyc.riferimento(h["host_id"]) or {}).get("stato", "") if kyc else ""
            except Exception:
                stato_kyc = ""
            return {
                "host_id": h["host_id"], "email": h["email"],
                "ragione_sociale": h["ragione_sociale"], "stato_account": h["stato"],
                "registrato_utc": _utc(h.get("creato_ts")),
                "giorni_anzianita": h.get("giorni"),
                "scaglione": st["scaglione"],
                "commissione_marketplace_pct": "%.2f" % (st["bps"] / 100.0),
                "commissione_diretto_pct": "%.2f" % (st["bps_diretto"] / 100.0),
                "giorni_al_prossimo_scatto": st["giorni_al_prossimo"],
                "prossima_commissione_pct": ("" if st["prossimo_bps"] is None
                                             else "%.2f" % (st["prossimo_bps"] / 100.0)),
                "contratto_versione": contratto.get("versione", ""),
                "contratto_sha256": contratto.get("doc_sha256", ""),
                "contratto_accettato_utc": _utc(contratto.get("accettato_ts")),
                "contratto_ip": contratto.get("ip", ""),
                "contratto_dispositivo": contratto.get("user_agent", ""),
                "clausole_vessatorie": ("SI" if contratto.get("vessatorie") else "NO"),
                "contratto_firma_hmac_sha256": contratto.get("firma", ""),
                "contratto_integra": ("SI" if contratto.get("integra") else "NO"),
                "privacy_versione": privacy.get("versione", ""),
                "privacy_sha256": privacy.get("doc_sha256", ""),
                "privacy_accettata_utc": _utc(privacy.get("accettato_ts")),
                "privacy_ip": privacy.get("ip", ""),
                "privacy_firma_hmac_sha256": privacy.get("firma", ""),
                "privacy_integra": ("SI" if privacy.get("integra") else "NO"),
                # IDENTITA' VERIFICATA legata a QUESTO contratto: e' cio' che trasforma
                # "qualcuno da un IP" in "la persona con documento verificato da un terzo".
                "identita_verificata": ("SI" if ident.get("legata") else "NO"),
                "identita_sessione_stripe": ident.get("session_ref", ""),
                "identita_impronta_legame": ident.get("impronta_legame", ""),
                "identita_legame_verificabile": ("SI" if ident.get("verificabile") else "NO"),
                "identita_legata_utc": _utc(ident.get("accettato_ts")),
                "identita_stato_kyc": stato_kyc,
            }

        host = reg.anzianita_host(limit=5000) if reg is not None else []
        costi = pp.aggrega_costi_tecnici() if pp is not None else {}
        # MARCHE TEMPORALI (fase184): l'ora dei registri certificata da un TERZO. Nel
        # fascicolo servono perche' rispondono alla sola obiezione che resterebbe —
        # "l'ora di questi registri ve la siete scritta voi".
        marche = []
        try:
            arch = getattr(self._sys, "marche", None)
            if arch is not None:
                for m in arch.elenco(limit=400, solo_ok=True):
                    v = arch.verifica(m["id"])
                    marche.append({
                        "giorno": m["giorno"],
                        "ora_certificata_utc": _utc(m.get("gen_time")),
                        "autorita": m["tsa"], "policy_tsa": m["policy"],
                        "numero_serie": m["seriale"],
                        "qualificata_eidas": "SI" if v.get("qualificata") else "NO",
                        "impronta_marcata": m["impronta"],
                        "sigillo_leggibile": m["canonico"],
                        "token_riverificato": "SI" if v.get("ok") else "NO",
                        "ora_coerente": "SI" if v.get("coerente_con_archivio") else "NO"})
        except Exception:
            logger.error("dossier: marche temporali non leggibili (ISOLATO)", exc_info=True)
        manomesse = 0
        if str(formato).lower() == "json":
            righe = []
            for h in host:
                v = riga_host(h)
                if v["contratto_integra"] == "NO" or v["privacy_integra"] == "NO":
                    manomesse += 1
                righe.append(v)
            corpo = _js.dumps({
                "documento": "Dossier legale-fiscale BookinVIP",
                "generato_utc": gen, "host": righe, "totale_host": len(righe),
                "prove_manomesse": manomesse,
                "tariffa_tecnica": {
                    "bps": self._psp_bps(),
                    "incassata_cents": (costi.get("incassate") or {}).get("cents", 0),
                    "persa_su_rimborsi_cents": (costi.get("perdite") or {}).get("cents", 0),
                    "coperto_netto_cents": costi.get("coperto_cents", 0),
                    "per_valuta": costi.get("per_valuta", {}),
                    "nota": ("Le perdite sono la tariffa tecnica di prenotazioni poi "
                             "rimborsate: Stripe non restituisce la sua commissione.")},
                "marche_temporali": {
                    "totale": len(marche), "elenco": marche,
                    "qualificate_eidas": sum(1 for m in marche
                                             if m.get("qualificata_eidas") == "SI"),
                    "cosa_provano": ("Ogni riga e' un token RFC 3161 firmato da "
                                     "un'Autorita' di marcatura INDIPENDENTE: attesta che "
                                     "alla data indicata i registri contenevano gia' "
                                     "esattamente l'impronta riportata. L'ora non e' "
                                     "dichiarata da BookinVIP."),
                    "valore_della_qualifica": ("Le righe con qualificata_eidas=SI sono "
                                               "marche QUALIFICATE ai sensi del "
                                               "Regolamento (UE) 910/2014 (eIDAS) art. 42, "
                                               "emesse da prestatori iscritti nella lista "
                                               "di fiducia europea. L'art. 41 attribuisce "
                                               "loro la PRESUNZIONE di esattezza di data e "
                                               "ora e di integrita' dei dati: l'onere di "
                                               "provare il contrario grava su chi contesta."),
                    "come_verificare": ("openssl ts -verify -data <file con il sigillo "
                                        "leggibile> -in marca.tsr -token_in -CAfile "
                                        "<archivio CA di sistema>")},
            }, ensure_ascii=False, indent=2, default=str)
            yield emetti(corpo)
            yield "\n# FINE DOSSIER - INTEGRITÀ: %s\n" % impronta.hexdigest()
        else:
            yield emetti("# BookinVIP - Dossier legale-fiscale certificato\r\n")
            yield emetti("# generato_utc,%s\r\n" % gen)
            yield emetti("# commissione_regime_bps,%d,promo_attiva,%s,tariffa_tecnica_bps,%d\r\n\r\n"
                         % (base, "SI" if promo else "NO", self._psp_bps()))
            colonne = list(riga_host({"host_id": "", "email": "", "ragione_sociale": "",
                                      "stato": "", "creato_ts": None, "giorni": None}).keys())
            yield emetti(",".join(colonne) + "\r\n")
            for h in host:
                v = riga_host(h)
                if v["contratto_integra"] == "NO" or v["privacy_integra"] == "NO":
                    manomesse += 1
                buf = _io.StringIO()
                _csv.writer(buf).writerow(
                    [self._cella_csv_sicura(v[c]) for c in colonne])
                yield emetti(buf.getvalue())
            inc = (costi.get("incassate") or {}).get("cents", 0)
            per = (costi.get("perdite") or {}).get("cents", 0)
            # ⛔ CORRETTO IL 2026-08-17: questo prospetto dichiarava la NOSTRA tariffa come
            # «costo irrecuperabile deducibile». Sono due voci diverse — ricavo mancato contro
            # costo sostenuto — e il commercialista le deve leggere separate.
            _irr = costi.get("costo_stripe_irrecuperabile") or {}
            _ign = costi.get("costo_stripe_sconosciuto") or {}
            yield emetti("\r\n# PROSPETTO TARIFFA TECNICA - classificazione fiscale\r\n")
            yield emetti("voce,classificazione_fiscale,prenotazioni,importo_cents,importo\r\n")
            yield emetti("tariffa_tecnica_incassata,RICAVO TECNICO COPERTO (ribaltato all'host),"
                         "%d,%d,%.2f\r\n"
                         % ((costi.get("incassate") or {}).get("conteggio", 0), inc, inc / 100.0))
            yield emetti("tariffa_tecnica_non_incassata,RICAVO TECNICO MANCATO - NON e' un "
                         "costo sostenuto,%d,%d,%.2f\r\n"
                         % ((costi.get("perdite") or {}).get("conteggio", 0), per, per / 100.0))
            yield emetti("commissione_gestore_non_restituita,COSTO TECNICO IRRECUPERABILE - "
                         "perdita deducibile,%d,%d,%.2f\r\n"
                         % (_irr.get("conteggio", 0), _irr.get("cents", 0),
                            _irr.get("cents", 0) / 100.0))
            yield emetti("commissione_gestore_NON_DETERMINATA,DATO MANCANTE - non e' zero,"
                         "%d,,\r\n" % _ign.get("conteggio", 0))
            yield emetti("coperto_netto,saldo,,%d,%.2f\r\n"
                         % (inc - per, (inc - per) / 100.0))
            yield emetti("# nota,Il gestore di pagamento NON restituisce la sua commissione sui "
                         "rimborsi: QUELLA e' la perdita deducibile ed e' la riga "
                         "commissione_gestore_non_restituita. La tariffa tecnica non incassata "
                         "e' invece un RICAVO MANCATO e non va portata in deduzione: dichiararla "
                         "come costo gonfierebbe la voce (misurato: su 200 EUR 10,25 contro "
                         "~3,25 reali). Le prenotazioni NON DETERMINATE non valgono zero: "
                         "il dato va recuperato dal gestore prima di chiudere il periodo.\r\n")
            yield emetti("\r\n# MARCHE TEMPORALI - ora certificata da un'Autorita' terza "
                         "(RFC 3161)\r\n")
            yield emetti("# L'ora NON e' dichiarata da BookinVIP: ogni riga e' un token "
                         "firmato da un'Autorita' indipendente che attesta che a quella "
                         "data i registri contenevano gia' quell'impronta.\r\n")
            yield emetti("# Le righe con qualificata_eidas=SI sono marche QUALIFICATE "
                         "(Reg. UE 910/2014 art. 42) emesse da prestatori della lista di "
                         "fiducia europea: l'art. 41 attribuisce loro la PRESUNZIONE di "
                         "esattezza di data e ora e di integrita' dei dati, e l'onere "
                         "della prova contraria grava su chi contesta.\r\n")
            yield emetti("# verifica indipendente,openssl ts -verify -data <file col "
                         "sigillo leggibile> -in marca.tsr -token_in -CAfile <CA di "
                         "sistema>\r\n")
            if marche:
                col_m = list(marche[0].keys())
                yield emetti(",".join(col_m) + "\r\n")
                for m in marche:
                    buf = _io.StringIO()
                    _csv.writer(buf).writerow(
                        [self._cella_csv_sicura(m[c]) for c in col_m])
                    yield emetti(buf.getvalue())
            else:
                yield emetti("# nessuna marca temporale presente\r\n")
            yield emetti("\r\n# host,%d\r\n# prove_manomesse,%d\r\n# marche_temporali,%d\r\n"
                         "# marche_qualificate_eidas,%d\r\n"
                         % (len(host), manomesse, len(marche),
                            sum(1 for m in marche if m.get("qualificata_eidas") == "SI")))
            yield "# FINE DOSSIER - INTEGRITÀ: %s\r\n" % impronta.hexdigest()
        logger.warning("EXPORT_LEGALE_COMPLETED | DATA: %s | HOST: %d | MANOMESSE: %d | "
                       "FORMATO: %s | IP: %s", gen, len(host), manomesse, formato, ip or "?")

    def _bunker_export_legale(self, query, headers):
        """DOSSIER LEGALE-FISCALE — via router (test e fallback non-streaming). In produzione
        l'handler HTTP intercetta la rotta e streamma; qui si materializza per i chiamanti."""
        if not self._bunker_auth(headers, azione="export_legale"):
            return 403, {"errore": "bunker_richiesto"}
        formato = "json" if str(query.get("formato") or "").lower() == "json" else "csv"
        try:
            testo = "".join(self.genera_dossier_legale(
                formato=formato, ip=self._client_ip(headers)))
        except Exception:
            logger.error("dossier legale: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        return 200, {"formato": formato, "contenuto": testo,
                     "certificato": "# FINE DOSSIER - INTEGRITÀ:" in testo}

    def _bunker_export_contabile(self, query, headers):
        """ESTRATTO CONTABILE CERTIFICATO — via router (test + fallback non-streaming):
        concatena il GENERATORE di streaming (stessa identica uscita che l'handler manda
        sul socket). In PRODUZIONE l'handler intercetta questa rotta e STREAMMA riga per
        riga (zero RAM); qui si materializza per i chiamanti che vogliono il dict."""
        if not self._bunker_auth(headers, azione="export_contabile"):
            return 403, {"errore": "bunker_richiesto"}
        if getattr(self._sys, "finanza", None) is None:
            return 503, {"errore": "giornale_non_attivo"}
        try:
            csv_txt = "".join(self.genera_estratto_csv(ip=self._client_ip(headers)))
        except Exception:
            logger.error("bunker export contabile: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        integra = "# FINE ESTRATTO - INTEGRITÀ VERIFICATA:" in csv_txt
        return 200, {"csv": csv_txt, "catena_integra": integra,
                     "corrotto": ("# NON CHIUSO / CORROTTO" in csv_txt)}

    def _bunker_logout(self, body, headers):
        """LOGOUT SERVER-SIDE del Bunker: revoca la sessione (nonce in denylist) -> quel
        token e' morto SUBITO, non solo cancellato dal browser. Sempre 200 (idempotente:
        anche un token gia' morto va bene). Auditato."""
        bunker = getattr(self._sys, "bunker", None)
        tok = headers.get("X-Bunker-Session", "") or headers.get("x-bunker-session", "")
        revocata = True                    # niente sessione da revocare = niente da promettere
        if bunker is not None and tok:
            try:
                revocata = bool(bunker.revoca(tok))
                if revocata:
                    logger.warning("BUNKER: logout (sessione revocata) ip=%s",
                                   self._client_ip(headers))
            except Exception:
                # La promessa nella descrizione ("quel token e' morto SUBITO") diventerebbe
                # FALSA: il token resta VIVO. Conta proprio quando si fa logout perche' si
                # sospetta un furto -- l'unico momento in cui la revoca serve davvero, sul
                # pannello dei soldi. Non si dichiara un successo che non c'e' stato.
                revocata = False
                logger.error("BUNKER: REVOCA FALLITA al logout ip=%s -> il token resta VIVO "
                             "fino alla scadenza naturale", self._client_ip(headers),
                             exc_info=True)
        # gatekeeper: il cookie si toglie COMUNQUE (il browser non lo usa piu'), ma `revocata`
        # dice la verita' su cosa e' successo davvero lato server.
        return 200, {"ok": True, "revocata": revocata, "_cookie": [("bv_bunker", "", 0)]}

    def _bunker_stato(self, query, headers):
        """Sala di controllo (read-only): conferma di essere nel Bunker + auto-diagnosi
        del sistema (integrita' catena hash, backup, disco). Richiede sessione Bunker."""
        if not self._bunker_auth(headers, azione="stato_sistema"):
            return 403, {"errore": "bunker_richiesto"}
        rep = {"bunker": True}
        try:
            import os as _os
            from fase178_watchdog import diagnosi
            dati = _os.environ.get("DATA_DIR", "data")
            bkp = _os.environ.get("BACKUP_DIR", _os.path.join(dati, "backup"))
            rep["diagnosi"] = diagnosi(dir_dati=dati, dir_backup=bkp, uptime_ok=None)
        except Exception:
            logger.error("bunker stato: diagnosi fallita (ISOLATA)", exc_info=True)
            rep["diagnosi"] = {"ok": None, "errore": "diagnosi_non_disponibile"}
        return 200, rep

    @staticmethod
    def _data_dir():
        import os as _os
        return _os.environ.get("DATA_DIR") or _os.path.dirname(
            _os.environ.get("DB_FINANZA", "data/finanza.db")) or "data"

    # ══════════ SALA CONTROLLO: SCAGLIONI · PROVE LEGALI · COSTI TECNICI ══════════
    # Nate dall'audit del 2026-07-20: il super-admin era CIECO su tre fronti — a che
    # tariffa sta ogni host (e quando scatta la prossima), le prove di consenso complete
    # (IP/ora/firma), e quanto ci costa davvero la tariffa tecnica Stripe sui rimborsi.
    def _bunker_scaglioni(self, query, headers):
        """SCAGLIONI & PROMO: per ogni host data di registrazione, anzianita', scaglione
        ATTIVO (0/8/10% marketplace + 5% diretto), giorni al prossimo scatto e DATA esatta
        del cambio. Il numero NON viene ricalcolato qui: arriva da `fase98.stato_scaglione`,
        la stessa funzione che il motore usa per ADDEBITARE -> impossibile divergere.
        Filtri: `q` (host_id/email/ragione sociale) e `scaglione` (promo|fase1|regime)."""
        if not self._bunker_auth(headers, azione="scaglioni_host"):
            return 403, {"errore": "bunker_richiesto"}
        reg = getattr(self._sys, "registro_host", None)
        if reg is None:
            return 503, {"errore": "registro_non_attivo"}
        try:
            import datetime as _dt
            from fase98_policy_commissione import stato_scaglione
            cfg = getattr(self._sys, "config", None)
            base = getattr(cfg, "commissione_bps", 1000)
            base = base if isinstance(base, int) and not isinstance(base, bool) \
                and 0 <= base <= 10000 else 1000
            promo = bool(getattr(cfg, "promo_lancio_attiva", False))
            q = str(query.get("q") or "").strip().lower()
            filtro = str(query.get("scaglione") or "").strip().lower()
            acc = getattr(self._sys, "accettazioni", None)
            righe, conta = [], {"promo": 0, "fase1": 0, "regime": 0, "ignoti": 0}
            da_riaccettare = 0
            for h in reg.anzianita_host(limit=5000):
                st = stato_scaglione(h.get("giorni"), promo_attiva=promo,
                                     bps_regime_config=base)
                conta[st["scaglione"]] = conta.get(st["scaglione"], 0) + 1
                if not st["anzianita_nota"]:
                    conta["ignoti"] += 1
                data_reg, data_prossimo = "", ""
                if isinstance(h.get("creato_ts"), int):
                    d0 = _dt.datetime.utcfromtimestamp(h["creato_ts"]).date()
                    data_reg = d0.isoformat()
                    if st["giorni_al_prossimo"] is not None:
                        data_prossimo = (_dt.date.today() + _dt.timedelta(
                            days=int(st["giorni_al_prossimo"]))).isoformat()
                # CONSENSI (2026-07-21): chi non e' ancora in regola con la versione CORRENTE
                # del contratto. La ri-accettazione si ATTIVA cambiando la versione del testo
                # (fase163) — qui si VEDE chi e' rimasto indietro, prima invisibile a tutti.
                cons = {}
                if acc is not None:
                    try:
                        cons = acc.stato_consensi(h["host_id"]) or {}
                    except Exception:
                        cons = {}
                riacc = bool(cons.get("deve_riaccettare"))
                if riacc:
                    da_riaccettare += 1
                voce = {"host_id": h["host_id"], "email": h["email"],
                        "ragione_sociale": h["ragione_sociale"], "stato": h["stato"],
                        "registrato_il": data_reg, "giorni": h.get("giorni"),
                        "scaglione": st["scaglione"], "bps": st["bps"],
                        "percentuale": st["bps"] / 100.0,
                        "bps_diretto": st["bps_diretto"],
                        "giorni_al_prossimo": st["giorni_al_prossimo"],
                        "prossimo_bps": st["prossimo_bps"],
                        "prossimo_scatto_il": data_prossimo,
                        "deve_riaccettare": riacc,
                        "versione_accettata": cons.get("versione_accettata", ""),
                        "versione_contratto_corrente": cons.get("versione_corrente", "")}
                if q and q not in (voce["host_id"] + " " + voce["email"] + " "
                                   + voce["ragione_sociale"]).lower():
                    continue
                if filtro and filtro != st["scaglione"]:
                    continue
                righe.append(voce)
            logger.info("AUDIT | BUNKER scaglioni consultati | RIGHE: %d | IP: %s",
                        len(righe), self._client_ip(headers))
            from fase163_accettazioni import CONTRATTO_HOST_VERSIONE as _vc
            return 200, {"host": righe, "totale": len(righe), "conteggi": conta,
                         "promo_attiva": promo, "commissione_regime_bps": base,
                         "tariffa_tecnica_bps": self._psp_bps(),
                         "versione_contratto_corrente": _vc,
                         "da_riaccettare": da_riaccettare,
                         "nota_riaccettazione": (
                             "La ri-accettazione forzata si attiva alzando la versione del "
                             "contratto (fase163): da quel momento ogni host trova la richiesta "
                             "al login. Qui si vede chi e' ancora indietro.")}
        except Exception:
            logger.error("bunker scaglioni: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}

    def _psp_bps(self):
        """La tariffa tecnica configurata (bps). Letta dal concierge = quella VERA applicata."""
        try:
            c = getattr(self._sys, "concierge", None)
            v = getattr(c, "_psp_bps", None)
            if isinstance(v, int) and not isinstance(v, bool):
                return v
        except Exception:
            pass
        return 0

    def _bunker_prove_legali(self, query, headers):
        """PROVE LEGALI COMPLETE (accettazioni.db) — solo Bunker. Ogni prova con documento,
        versione, impronta SHA-256 del testo, **IP**, dispositivo, **data/ora UTC** e **firma
        HMAC-SHA256**, piu' il flag `integra` (falso = riga manomessa). Con `host_id` da' le
        prove di quell'host; senza, l'elenco completo + il conteggio delle righe NON integre
        (nessuno prima controllava l'integrita' delle prove: si vedeva solo aprendo un host)."""
        if not self._bunker_auth(headers, azione="prove_legali"):
            return 403, {"errore": "bunker_richiesto"}
        acc = getattr(self._sys, "accettazioni", None)
        reg = getattr(self._sys, "registro_host", None)
        if acc is None:
            return 503, {"errore": "registro_accettazioni_non_attivo"}
        try:
            import datetime as _dt
            hid = str(query.get("host_id") or "").strip()
            elenco = []
            if hid:
                sorgente = [(hid, acc.elenco(hid))]
            else:
                lim = 500
                sorgente = [(h["host_id"], acc.elenco(h["host_id"]))
                            for h in (reg.anzianita_host(limit=lim) if reg else [])]
            manomesse = 0
            for host_id, prove in sorgente:
                for p in prove:
                    if not p.get("integra"):
                        manomesse += 1
                    ts = p.get("accettato_ts")
                    elenco.append({
                        "host_id": host_id, "documento": p.get("documento"),
                        "versione": p.get("versione"), "doc_sha256": p.get("doc_sha256"),
                        "ip": p.get("ip"), "dispositivo": p.get("user_agent"),
                        "accettato_ts": ts,
                        "accettato_utc": (_dt.datetime.utcfromtimestamp(int(ts))
                                          .strftime("%Y-%m-%d %H:%M:%S UTC")
                                          if isinstance(ts, int) else ""),
                        "clausole_vessatorie": bool(p.get("vessatorie")),
                        # riferimento esterno: per `identita_stripe` e' la sessione di
                        # verifica documentale (vs_...) legata a QUESTO contratto
                        "riferimento": p.get("riferimento", ""),
                        "firma_hmac_sha256": p.get("firma"), "integra": bool(p.get("integra"))})
            logger.warning("ADMIN_ACTION | AZIONE: Consultazione prove legali | RIGHE: %d | "
                           "MANOMESSE: %d | IP: %s", len(elenco), manomesse,
                           self._client_ip(headers))
            return 200, {"prove": elenco, "totale": len(elenco), "manomesse": manomesse,
                         "integrita_ok": manomesse == 0}
        except Exception:
            logger.error("bunker prove legali: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}

    def _bunker_costi_tecnici(self, query, headers):
        """PROSPETTO TARIFFA TECNICA (5% + 0,25 €; 7% se l'annuncio non e' in euro) — solo
        Bunker. Separa quanto la tariffa ha
        davvero coperto da quanto e' andato PERSO sui rimborsi: Stripe non restituisce la sua
        fetta, quindi ogni prenotazione rimborsata lascia un costo a carico della piattaforma
        che prima non compariva da nessuna parte (buco trovato nell'audit del 2026-07-20)."""
        if not self._bunker_auth(headers, azione="costi_tecnici"):
            return 403, {"errore": "bunker_richiesto"}
        pp = getattr(self._sys, "pagamenti_pendenti", None)
        if pp is None:
            return 503, {"errore": "pagamenti_non_attivi"}
        try:
            rep = pp.aggrega_costi_tecnici()
            rep["tariffa_tecnica_bps"] = self._psp_bps()
            # ⛔ CORRETTA IL 2026-08-17. Questa nota diceva che `perdite` e' un «COSTO TECNICO
            # IRRECUPERABILE ... da portare in deduzione», ma `perdite` somma la NOSTRA tariffa
            # tecnica: e' un RICAVO CHE NON ABBIAMO INCASSATO, non un costo che abbiamo
            # sostenuto. Portarlo in deduzione gonfiava una voce fiscale — misurato sul primo
            # pagamento vero: noi 30, Stripe 27; su 200 EUR sarebbero 10,25 contro ~3,25.
            # Le due cose ora hanno due voci, e chi legge non deve piu' interpretare.
            rep["nota"] = (
                "DUE VOCI DIVERSE, e vanno tenute separate. (1) RICAVO TECNICO MANCATO: e' la "
                "nostra tariffa tecnica su prenotazioni poi rimborsate o cancellate — non e' "
                "un costo sostenuto, e' un guadagno che non c'e' stato. (2) COSTO TECNICO "
                "IRRECUPERABILE (perdita deducibile): e' la commissione che il GESTORE DI "
                "PAGAMENTO ha trattenuto e che sul rimborso NON restituisce — quella si', "
                "resta a carico della piattaforma. (3) NON DETERMINATO: prenotazioni "
                "rimborsate per cui quella commissione non e' stata letta dal gestore. NON e' "
                "zero: e' un dato mancante, e va recuperato prima di chiudere il periodo.")
            rep["classificazione_fiscale"] = {
                "incassate": rep["incassate"].get("voce_fiscale", ""),
                "perdite": rep["perdite"].get("voce_fiscale", ""),
                "costo_stripe_irrecuperabile":
                    rep.get("costo_stripe_irrecuperabile", {}).get("voce_fiscale", ""),
                "costo_stripe_sconosciuto":
                    rep.get("costo_stripe_sconosciuto", {}).get("voce_fiscale", "")}
            logger.info("AUDIT | BUNKER costi tecnici consultati | IP: %s",
                        self._client_ip(headers))
            return 200, rep
        except Exception:
            logger.error("bunker costi tecnici: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}

    def _bunker_marche(self, query, headers):
        """MARCHE TEMPORALI (fase184) — solo Bunker, read-only. Elenco delle marche
        ottenute da Autorita' esterne: giorno, ora certificata, chi l'ha firmata,
        numero di serie, e l'esito della RIVERIFICA del token archiviato (che smaschera
        una riga a cui qualcuno avesse cambiato l'impronta lasciando il token vecchio).

        Con `?scarica=<id>` restituisce il token grezzo `.tsr`: e' l'oggetto che si
        consegna a un perito o a un giudice, verificabile con `openssl ts -verify`
        SENZA di noi e SENZA il nostro software. E' il punto di tutta la faccenda."""
        if not self._bunker_auth(headers, azione="marche_temporali"):
            return 403, {"errore": "bunker_richiesto"}
        arch = getattr(self._sys, "marche", None)
        if arch is None:
            return 503, {"errore": "marca_temporale_non_attiva",
                         "come_si_accende": "MARCA_TEMPORALE=1 + riavvio"}
        try:
            import datetime as _dt
            righe = []
            for r in arch.elenco(limit=int(query.get("limit") or 60)):
                v = arch.verifica(r["id"]) if r["stato"] == "ok" else {"ok": False}
                gt = int(r.get("gen_time") or 0)
                righe.append({
                    "id": r["id"], "giorno": r["giorno"], "stato": r["stato"],
                    "autorita": r["tsa"], "policy": r["policy"], "seriale": r["seriale"],
                    "ora_certificata_utc": (_dt.datetime.utcfromtimestamp(gt)
                                            .strftime("%Y-%m-%d %H:%M:%S UTC")
                                            if gt else ""),
                    "impronta": r["impronta"], "sigillo_leggibile": r["canonico"],
                    "errore": r["errore"],
                    # QUALIFICATA (eIDAS art. 42): riletta DAL TOKEN, non dal database
                    "qualificata": bool(v.get("qualificata")),
                    "qualifica_coerente": bool(v.get("qualifica_coerente", True)),
                    "token_riverificato": bool(v.get("ok")),
                    "ora_coerente": bool(v.get("coerente_con_archivio")),
                    "scarica": "/api/bunker/marca.tsr?id=%d" % r["id"]})
            ok = [x for x in righe if x["stato"] == "ok"]
            qual = [x for x in ok if x["qualificata"]]
            return 200, {"marche": righe, "totale": len(righe), "riuscite": len(ok),
                         "qualificate": len(qual),
                         "tutte_qualificate": bool(ok) and len(qual) == len(ok),
                         "tutte_riverificate": all(x["token_riverificato"] for x in ok),
                         "ultima_ora_certificata": ok[0]["ora_certificata_utc"] if ok else "",
                         "cosa_significa_qualificata":
                             "eIDAS art. 41: la marca QUALIFICATA gode della presunzione "
                             "legale di esattezza di data e ora e di integrita' dei dati. "
                             "In giudizio non tocca a noi provare che l'ora e' giusta: "
                             "tocca a chi contesta provare il contrario.",
                         "come_verificare": "openssl ts -verify -data <file col sigillo "
                                            "leggibile> -in marca.tsr -token_in -CAfile "
                                            "<archivio CA di sistema>"}
        except Exception:
            logger.error("bunker marche temporali: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}

    def scarica_marca(self, marca_id, headers):
        """Il token grezzo `.tsr` di UNA marca, per il download dal Bunker.
        Ritorna (stato, byte_o_None). E' l'unico pezzo che esce in binario: si consegna
        tale e quale a un perito, che lo verifica con `openssl ts -verify` senza di noi."""
        if not self._bunker_auth(headers, azione="scarica_marca"):
            return 403, None
        arch = getattr(self._sys, "marche", None)
        if arch is None:
            return 503, None
        try:
            token = arch.token(int(marca_id))
        except Exception:
            return 400, None
        if not token:
            return 404, None
        logger.warning("ADMIN_ACTION | AZIONE: Scarico token marca temporale | ID: %s | "
                       "IP: %s", marca_id, self._client_ip(headers))
        return 200, token

    def _bunker_marca_ora(self, body, headers):
        """Forza SUBITO una marca temporale (fase184), senza aspettare il giro notturno.
        Serve quando si vuole congelare lo stato dei registri prima di un evento
        importante (una contestazione, un deposito, un'ispezione). Idempotente sul
        giorno: se oggi c'e' gia', risponde che c'e' gia' e non disturba la TSA."""
        if not self._bunker_auth(headers, azione="marca_ora"):
            return 403, {"errore": "bunker_richiesto"}
        arch = getattr(self._sys, "marche", None)
        if arch is None:
            return 503, {"errore": "marca_temporale_non_attiva"}
        try:
            from fase184_marca_temporale import marca_i_registri
            esito = marca_i_registri(arch,
                                     accettazioni=getattr(self._sys, "accettazioni", None),
                                     finanza=getattr(self._sys, "finanza", None))
            logger.warning("ADMIN_ACTION | AZIONE: Marca temporale su richiesta | "
                           "ESITO: %s | AUTORITA: %s | IP: %s",
                           "ok" if esito.get("ok") else esito.get("motivo"),
                           esito.get("tsa") or "-", self._client_ip(headers))
            return (200 if esito.get("ok") or esito.get("saltato") else 502), esito
        except Exception:
            logger.error("bunker marca ora: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}

    def _bunker_blocco_globale_stato(self, headers):
        """KILL-SWITCH GLOBALE (fase191) — stato, READ-ONLY. Solo super-admin."""
        if not self._bunker_auth(headers, azione="blocco_globale"):
            return 403, {"errore": "bunker_richiesto"}
        bg = getattr(self._sys, "blocco_globale", None)
        return 200, (bg.stato() if bg else {"attivo": False, "assente": True})

    def _bunker_blocco_globale_imposta(self, body, headers):
        """KILL-SWITCH GLOBALE d'emergenza: accende/spegne il FREEZE dei movimenti di denaro
        (book/rimborso/payout/carta). Solo super-admin. Body {attivo: bool, motivo: str}.
        L'azione e' registrata (chi/quando/motivo nel flag) e loggata CRITICO."""
        if not self._bunker_auth(headers, azione="blocco_globale"):
            return 403, {"errore": "bunker_richiesto"}
        bg = getattr(self._sys, "blocco_globale", None)
        if bg is None:
            return 503, {"errore": "blocco_globale_assente"}
        dati = self._json(body) or {}
        attivo = bool(dati.get("attivo"))
        motivo = str(dati.get("motivo", ""))[:200]
        ok = bg.imposta(attivo, motivo=motivo, chi="super-admin")
        logger.critical("KILL-SWITCH GLOBALE %s | motivo=%s",
                        "ATTIVATO (freeze soldi)" if attivo else "disattivato", motivo or "-")
        st = bg.stato()
        return (200 if ok else 500), {**st, "impostato": ok}

    def _bunker_admin_accounts(self, headers):
        """GESTIONE PERMESSI (fase192) — elenco operatori admin. Solo super-admin. Mai salt/hash."""
        if not self._bunker_auth(headers, azione="admin_accounts"):
            return 403, {"errore": "bunker_richiesto"}
        from fase192_admin_accounts import RUOLI
        aa = getattr(self._sys, "admin_accounts", None)
        return 200, {"account": (aa.lista() if aa is not None else []), "ruoli": list(RUOLI)}

    def _bunker_admin_accounts_gestisci(self, body, headers):
        """Crea/revoca/riattiva/cambia-ruolo un operatore admin. Solo super-admin.
        Body {azione: crea|revoca|riattiva|ruolo, email, password?, ruolo?}. La ADMIN_KEY root
        resta il super-potere; questi sono operatori aggiuntivi con permessi per ruolo."""
        if not self._bunker_auth(headers, azione="admin_accounts"):
            return 403, {"errore": "bunker_richiesto"}
        aa = getattr(self._sys, "admin_accounts", None)
        if aa is None:
            return 503, {"errore": "admin_accounts_assente"}
        dati = self._json(body) or {}
        azione = str(dati.get("azione", ""))
        email = dati.get("email", "")
        if azione == "crea":
            r = aa.crea(email, dati.get("password", ""), dati.get("ruolo", ""), creato_da="super-admin")
            logger.warning("ADMIN ACCOUNT creato/aggiornato %s ruolo=%s ok=%s",
                           email, dati.get("ruolo"), r.get("ok"))
            return (200 if r.get("ok") else 422), r
        if azione == "revoca":
            ok = aa.revoca(email)
            logger.warning("ADMIN ACCOUNT revocato %s ok=%s", email, ok)
            return (200 if ok else 404), {"ok": ok, "email": email}
        if azione == "riattiva":
            ok = aa.riattiva(email)
            return (200 if ok else 404), {"ok": ok, "email": email}
        if azione == "ruolo":
            ok = aa.imposta_ruolo(email, dati.get("ruolo", ""))
            logger.warning("ADMIN ACCOUNT ruolo %s -> %s ok=%s", email, dati.get("ruolo"), ok)
            return (200 if ok else 422), {"ok": ok, "email": email, "ruolo": dati.get("ruolo")}
        return 422, {"errore": "azione_non_valida"}

    def _bunker_cambio_valuta(self, headers):
        """CAMBIO VALUTA (fase99 ProviderTassi) — stato + tassi campione. Solo super-admin.
        READ-ONLY: la chiave OXR resta un segreto in .env (mai esposta/modificabile via UI)."""
        if not self._bunker_auth(headers, azione="cambio_valuta"):
            return 403, {"errore": "bunker_richiesto"}
        tassi = getattr(self._sys, "tassi", None)
        if tassi is None:
            return 200, {"configurato": False, "assente": True,
                         "nota": "convertitore spento (manca OXR_APP_ID in .env)"}
        try:
            st = dict(tassi.stato())
        except Exception:
            st = {"configurato": False}
        campioni = {}
        for o, d in (("EUR", "USD"), ("EUR", "GBP"), ("USD", "JPY")):
            try:
                t = tassi.tasso(o, d)
                if t is not None:
                    campioni["%s->%s" % (o, d)] = str(t)
            except Exception:
                pass
        st["campioni"] = campioni
        st["markup_bps"] = 100          # fee di conversione trasparente (1%), dichiarata
        return 200, st

    def _bunker_cambio_valuta_aggiorna(self, headers):
        """Forza SUBITO un rinfresco dei tassi da OXR (senza aspettare il giro giornaliero).
        Solo super-admin. Isolato: qualunque errore -> aggiornato False, mai solleva."""
        if not self._bunker_auth(headers, azione="cambio_valuta"):
            return 403, {"errore": "bunker_richiesto"}
        tassi = getattr(self._sys, "tassi", None)
        if tassi is None:
            return 503, {"errore": "convertitore_spento"}
        ok = False
        try:
            ok = bool(tassi.aggiorna())
        except Exception:
            ok = False
        try:
            st = dict(tassi.stato())
        except Exception:
            st = {}
        return 200, {"aggiornato": ok, **st}

    def _bunker_integrita(self, query, headers):
        """SALA CONTROLLO — INTEGRITA' (Incremento 4, read-only, sessione Bunker richiesta):
        verifica la CATENA HASH del giornale contabile (fase177) = prova che nessun movimento
        e' stato manomesso, + la diagnosi di sistema (backup/disco/db). La verita' contabile
        e la salute della macchina in un colpo d'occhio, solo dal Bunker."""
        if not self._bunker_auth(headers, azione="integrita"):
            return 403, {"errore": "bunker_richiesto"}
        rep = {}
        fc = getattr(self._sys, "finanza", None)
        try:
            rep["catena"] = fc.verifica_catena() if fc is not None else {"ok": None,
                                                                          "motivo": "spento"}
        except Exception:
            logger.error("bunker integrita catena: eccezione ISOLATA", exc_info=True)
            rep["catena"] = {"ok": None, "motivo": "errore"}
        try:
            import os as _os
            from fase178_watchdog import diagnosi
            dd = self._data_dir()
            rep["diagnosi"] = diagnosi(dir_dati=dd, dir_backup=_os.path.join(dd, "backup"),
                                       uptime_ok=None)
        except Exception:
            logger.error("bunker integrita diagnosi: eccezione ISOLATA", exc_info=True)
            rep["diagnosi"] = {"ok": None}
        # Debt Status (Scatto ②): quanto ci devono gli host (penali non ancora riscosse).
        # Si saldano DA SOLE alla fonte sui prossimi payout; qui la vista di controllo.
        try:
            aperti = fc.debiti_aperti() if fc is not None else []
            rep["debiti"] = {"aperti": len(aperti),
                             "totale_cents": sum(int(d.get("residuo_cents") or 0)
                                                 for d in aperti),
                             "host": sorted({str(d.get("host_id") or "") for d in aperti})}
        except Exception:
            rep["debiti"] = {"aperti": None}
        return 200, rep

    def _bunker_log(self, query, headers):
        """SALA CONTROLLO — LOG PERSISTENTI (Incremento 4, read-only, sessione Bunker):
        ultime N righe del log persistente (DATA_DIR/app.log, sopravvive ai deploy). E' il
        registro di chi-ha-fatto-cosa e degli allarmi (CRITICAL/BUNKER/RATE-LIMIT/AUDIT).
        N clampato 1..300: mai scaricare tutto."""
        if not self._bunker_auth(headers, azione="log"):
            return 403, {"errore": "bunker_richiesto"}
        import os as _os
        try:
            n = int(str(query.get("n") or 100))
        except Exception:
            n = 100
        n = max(1, min(300, n))
        path = _os.path.join(self._data_dir(), "app.log")
        righe = []
        try:
            if _os.path.isfile(path):
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    righe = f.readlines()[-n:]
        except Exception:
            logger.warning("bunker log: lettura fallita (ISOLATA)", exc_info=True)
        righe = [r.rstrip("\n")[:500] for r in righe]
        return 200, {"righe": righe, "n": len(righe), "file": "app.log"}

    def _admin_diagnosi(self, query, headers):
        """AUTO-DIAGNOSI on-demand (fase178): stessa lente del Watchdog, ma a richiesta
        dell'admin. READ-ONLY (non tocca alcun dato): catena hash del giornale, freschezza
        backup, disco, db presenti. La misura dell'uptime NON si fa da qui (un processo non
        puo' dire di essere morto): la fa il watchdog esterno."""
        if not self._auth_admin(headers):
            return 401, {"errore": "unauthorized"}
        try:
            import os as _os
            from fase178_watchdog import diagnosi
            # BUG SCOVATO AL COLLAUDO LIVE (Incr.10/11): nel container DATA_DIR esiste
            # ma e' VUOTA -> environ.get(..., "data") ritorna "" (il default scatta solo
            # se la chiave MANCA) -> diagnosi su cartelle inesistenti ("0 db, nessun
            # backup" con /data pieno). Fix: stesso fallback robusto di _data_dir().
            dati = self._data_dir()
            bkp = (_os.environ.get("BACKUP_DIR", "").strip()
                   or _os.path.join(dati, "backup"))
            rep = diagnosi(dir_dati=dati, dir_backup=bkp, uptime_ok=None)
        except Exception:
            logger.error("admin diagnosi: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        return 200, rep

    def _admin_cancella_attivita(self, body, headers):
        """TASTO 'cancella tutto': rimuove un host da OGNI archivio (fase156) e VERIFICA che
        non resti nulla. 200 se ok (0 residui), 409 se qualcosa e' rimasto (con il dettaglio)."""
        if not self._auth_admin(headers):
            return 401, {"errore": "unauthorized"}
        if not self._bunker_ok_o_field(headers, azione="cancella_attivita"):
            return 403, {"errore": "bunker_richiesto"}
        # SCALATA DI PRIVILEGI (difetto PROVATO 2026-07-28, test_ruoli_admin_adversarial):
        # 'cancella_attivita' e' in AZIONI_SOLO_ADMIN ma nessuno chiamava il gate di RUOLO ->
        # un operatore 'supporto' cancellava un host da OGNI archivio (200 + report), la piu'
        # distruttiva delle azioni. Ora il ruolo decide PRIMA di toccare qualsiasi cosa.
        if not self._puo_azione(headers, "cancella_attivita"):   # 'supporto' non cancella
            return 403, {"errore": "permesso_negato_ruolo"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        host_id = dati.get("host_id")
        if not (isinstance(host_id, str) and host_id):
            return 422, {"errore": "host_id_mancante"}
        # 'forza=True' serve solo per un obbligo legale inderogabile e va chiesto
        # esplicitamente: senza, un host con soldi o persone in ballo NON si cancella.
        forza = dati.get("forza") is True
        try:
            from fase156_erasure import cancella_attivita_host
            rep = cancella_attivita_host(self._sys, host_id, forza=forza)
        except Exception:
            logger.error("admin cancella attivita: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        if rep.get("errore") == "obblighi_pendenti":
            return 409, rep                         # bloccata: prima si sistema
        return (200 if rep.get("ok") else 409), rep

    def _admin_rimborso(self, body, headers):
        """Rimborso = cancellazione: libera le date sull'inventario (fase58.rilascia).
        Il rimborso Stripe vero si esegue quando il PSP e' attivo (gated)."""
        if not self._auth_admin(headers):
            return 401, {"errore": "unauthorized"}
        if not self._bunker_ok_o_field(headers, azione="rimborso"):
            return 403, {"errore": "bunker_richiesto"}
        if not self._puo_azione(headers, "rimborso"):   # ruolo 'supporto' non muove soldi
            return 403, {"errore": "permesso_negato_ruolo"}
        if self._transazioni_bloccate():           # kill-switch globale: niente rimborsi in freeze
            return 503, {"errore": "transazioni_sospese"}
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
        # COERENZA con la cancellazione ospite/host: rimborsare = mettere in sicurezza anche i
        # SOLDI, non solo liberare le date. Senza questi 3 passi (bug PROVATO): l'host restava
        # 'maturato' e l'escrow si auto-rilasciava a 24h -> PAGAVAMO L'HOST mentre rimborsavamo
        # l'ospite = PERDITA PIENA. riferimento = idem_key[:24] (come lo genera fase59.prenota);
        # payout/escrow/pendente sono chiavati sul riferimento. Idempotenti e isolati.
        # RE-BLOCK (bug PROVATO 2026-07-27, test_stateful_api): dopo un pagamento TARDIVO la
        # chiave attiva e' 'reblock:<rif>' (quella che il pannello mostra e che rilascia le
        # date) -> idem[:24] dava un rif SBAGLIATO e i 3 passi di sicurezza soldi diventavano
        # no-op silenziosi (host pagato + ospite rimborsato). Stesso strip di _host_prenotazioni.
        rif = idem[len("reblock:"):] if idem.startswith("reblock:") else idem[:24]
        # Ogni passo e' isolato (uno rotto non deve fermare gli altri) ma NON silenzioso: si
        # raccoglie chi ha fallito, perche' la risposta non puo' dichiarare cose non avvenute.
        _falliti = [nome for nome, ok in (
            ("payout_trattenuto", self._payout_trattieni(rif)),   # l'host non incassa una rimborsata
            ("tassa_stornata", self._storna_tassa(rif)),          # tassa fuori dal ledger citta'
            ("checkin_revocato", self._revoca_checkin(rif)),      # smart-pass revocato: la PORTA
        ) if not ok]
        gz = getattr(self._sys, "garanzia", None)
        if gz is not None:
            try:
                gz.annulla(rif)                        # niente auto-rilascio dell'escrow all'host
            except Exception:
                logger.warning("admin rimborso: chiusura garanzia fallita (ignorata)", exc_info=True)
                _falliti.append("escrow_annullato")
        _era_pagato, _pi, _tot, _valuta = False, "", 0, "EUR"
        pp = getattr(self._sys, "pagamenti_pendenti", None)
        if pp is not None:
            try:
                rec = pp.info(rif)
                if rec is not None and rec.get("stato") != "rimborsato":
                    _era_pagato = (rec.get("stato") == "pagato")
                    pp.marca_da_rimborsare(rif)        # blocca il transfer + nessuna conferma tardiva
                    # SCATOLA NERA del rimborso admin (importo = totale ospite dal record)
                    import json as _jr
                    try:
                        dj = _jr.loads(rec.get("corpo_json") or "{}")
                    except Exception:
                        dj = {}
                    tot = int(dj.get("totale_cents", 0) or dj.get("prezzo_guest_cents", 0) or 0)
                    _tot = tot
                    _valuta = dj.get("valuta") or "EUR"
                    _pi = str(dj.get("stripe_pi") or "")
                    if tot > 0:
                        self._giornale(tipo="rimborso", riferimento=rif, soggetto="ospite:" + rif,
                                       importo_cents=tot, valuta=_valuta,
                                       causale="rimborso disposto da admin")
            except Exception:
                logger.warning("admin rimborso: invalidazione pendente fallita (ignorata)",
                               exc_info=True)
                _falliti.append("pendente_invalidato")
        # ⛔ E QUI I SOLDI TORNANO DAVVERO INDIETRO. Fino al 2026-08-16 tutto quello che sta
        # sopra avveniva e poi la risposta diceva «il rimborso va eseguito A MANO»: per l'ospite
        # la differenza non e' tecnica, il database diceva 'rimborsato' e sul suo conto non
        # arrivava niente. `grep v1/refunds` dava zero su tutto il progetto.
        #
        # ⛔ SI RESTITUISCE SOLO SE I PASSI DI SICUREZZA SONO RIUSCITI (D16, mai in perdita).
        # Se `payout_trattenuto` e' fallito, l'host puo' essere gia' stato pagato: rimborsare
        # li' significa pagare DUE volte la stessa prenotazione, e la seconda la paghiamo noi.
        # Nel dubbio i soldi NON partono da soli: si grida e decide una persona.
        _rimborso = ""
        if not _era_pagato:
            _rimborso = "nessun incasso da restituire (la prenotazione non risulta pagata)"
        elif not _pi:
            # Incassata ma senza l'identificativo del pagamento: NON e' un silenzio innocuo.
            _rimborso = ("PAGATA ma pagamento non identificabile (nessun pi_): "
                         "da restituire A MANO dal pannello Stripe")
            _falliti.append("soldi_restituiti")
            logger.error("RIMBORSO: prenotazione %s risulta PAGATA ma senza stripe_pi: i soldi "
                         "vanno restituiti a mano", rif)
        elif _falliti:
            _rimborso = ("NON tentato: i passi di sicurezza non sono riusciti (%s), l'host "
                         "potrebbe essere gia' stato pagato" % ", ".join(_falliti))
        elif _tot <= 0:
            _rimborso = "importo non determinabile dal record: da restituire A MANO"
            _falliti.append("soldi_restituiti")
        else:
            _sp = getattr(self._sys, "stripe", None)
            if _sp is None or not hasattr(_sp, "rimborsa"):
                _rimborso = "provider Stripe assente: da restituire A MANO"
                _falliti.append("soldi_restituiti")
            else:
                # Chiave STABILE per questa prenotazione: un ritentativo di rete o un doppio
                # clic non possono restituire i soldi due volte (Stripe scarta il duplicato).
                _es = _sp.rimborsa(_pi, _tot, "rimborso:" + rif)
                if isinstance(_es, dict) and _es.get("ok"):
                    _rimborso = "eseguito (%s)" % (_es.get("id") or "")
                    logger.info("RIMBORSO ESEGUITO rif=%s importo=%d %s stripe=%s",
                                rif, _tot, _valuta, _es.get("id") or "")
                else:
                    motivo = (_es or {}).get("motivo") if isinstance(_es, dict) else "risposta_non_dict"
                    _rimborso = "NON eseguito (%s): da restituire A MANO" % motivo
                    _falliti.append("soldi_restituiti")
                    logger.error("RIMBORSO FALLITO rif=%s importo=%d %s -> %s",
                                 rif, _tot, _valuta, motivo)
        if _falliti:
            # Le date SONO libere (il rilascio e' riuscito, e' la prima cosa che si fa), ma i
            # passi che mettono in sicurezza i soldi e la PORTA no: va detto, non taciuto.
            logger.error("RIMBORSO ADMIN INCOMPLETO rif=%s passi FALLITI=%r -> rischio PERDITA "
                         "PIENA (host pagato + ospite rimborsato) e/o smart-pass ancora valido",
                         rif, _falliti)
        return 200, {"stato": "rimborsato", "date_liberate": True,
                     "idempotente": bool(getattr(e, "idempotente", False)),
                     "passi_falliti": _falliti,
                     "rimborso_stripe": _rimborso,
                     "nota": ("date liberate; payout trattenuto ed escrow chiuso; "
                              "soldi all'ospite: " + _rimborso) if not _falliti
                             else ("date liberate, ma ATTENZIONE: questi passi NON sono riusciti "
                                   "e vanno fatti a mano -> " + ", ".join(_falliti)
                                   + " | soldi all'ospite: " + _rimborso)}

    # Quante righe si esaminano a ogni apertura del pannello. Bounded per non trasformare
    # l'apertura in centinaia di chiamate a Stripe. Quante NON sono state guardate finisce
    # nella risposta: un taglio silenzioso fa sembrare «coperto» cio' che nessuno ha guardato
    # (D18 condizione 3).
    RIMBORSI_TETTO = 50

    def _rimborso_dovuto_scheda(self, rif):
        """LA SCHEDA DI UN RIMBORSO DOVUTO — e il giudizio sta QUI, in un posto solo.

        La lista e il pulsante fanno la STESSA domanda alla STESSA funzione. Se il giudizio
        vivesse in due posti, prima o poi la lista mostrerebbe un bottone che il pulsante
        rifiuta — o, molto peggio, il contrario.

        ⛔ LA RIGA NON SI SCRIVE, SI CALCOLA. La sua esistenza non dipende da nessuno che si
        sia ricordato di metterla in una coda: dipende dallo STATO. Se la cancellazione
        inserisse una riga da qualche parte, un errore o un riavvio in quel punto la farebbe
        sparire e nessuno lo saprebbe mai — il cliente aspetterebbe per sempre.

        ⛔ E SI REGGE SUL GIORNALE IMMUTABILE (fase177), non sui pendenti: `fase162.
        pulisci_vecchi()` cancella i record 'rimborsato' piu' vecchi di 26 ore, quindi una
        lista costruita li' sopra perderebbe per primo proprio chi ha aspettato di piu'.

        Ritorna `(riga, stripe_ok)`. `riga` e' None quando per quella prenotazione non risulta
        dovuto niente. `stripe_ok` False significa **«non lo so»**, MAI «nessun rimborso»:
        confondere le due cose e' il modo esatto in cui si rimborsa due volte la stessa
        persona (fonte: docs.stripe.com/api/refunds/list).
        """
        import time as _t
        fc = getattr(self._sys, "finanza", None)
        sp = getattr(self._sys, "stripe", None)
        if fc is None:
            return None, False
        try:
            movimenti = [m for m in fc.movimenti(str(rif))
                         if (m.get("tipo") or "") == "rimborso"]
        except Exception:
            logger.error("rimborsi dovuti: giornale illeggibile per %s",
                         _rif_per_registro(rif), exc_info=True)
            return None, False
        if not movimenti:
            return None, True          # niente da restituire: non e' un guasto, e' la pace
        mov = movimenti[-1]
        dovuto = int(mov.get("importo_cents") or 0)
        manca = []
        # ── cosa sappiamo del pagamento (il pendente puo' essere gia' stato purgato) ──
        pagato, pi_, date_liberate, rec = 0, "", False, None
        try:
            pp = getattr(self._sys, "pagamenti_pendenti", None)
            rec = pp.info(str(rif)) if pp is not None else None
        except Exception:
            logger.warning("rimborsi dovuti: pendente illeggibile per %s",
                           _rif_per_registro(rif), exc_info=True)
        if rec is not None:
            try:
                dj = json.loads(rec.get("corpo_json") or "{}")
            except Exception:
                dj = {}
            pagato = int(dj.get("totale_cents", 0) or dj.get("prezzo_guest_cents", 0) or 0)
            pi_ = str(dj.get("stripe_pi") or "")
            # Il rilascio delle date e' la PRIMA cosa che fa la cancellazione, e senza di
            # esso non si arriva mai a questi stati: se lo stato c'e', le date sono libere.
            date_liberate = rec.get("stato") in ("rimborsato", "cancellata_host")
        if not pi_:
            manca.append("payment_intent")
        if pagato <= 0:
            manca.append("importo_pagato")
        if not date_liberate:
            manca.append("date_liberate")
        if dovuto <= 0:
            manca.append("importo_dovuto")
        # ── FRENO 1: mai piu' di quanto ha pagato (aritmetica, non opinione) ──
        if 0 < pagato < dovuto:
            manca.append("dovuto_maggiore_del_pagato")
            logger.error("RIMBORSO DOVUTO INCOERENTE | rif %s | dovuto %d > pagato %d: la "
                         "differenza la metteremmo noi",
                         _rif_per_registro(rif), dovuto, pagato)
        # ── FRENO 3: se l'host e' gia' stato pagato, rimborsare paga DUE volte (D16) ──
        passi_ok = False
        try:
            pd = getattr(self._sys, "payout", None)
            stato_payout = str(pd.stato_di(str(rif)) or "") if pd is not None else ""
            passi_ok = stato_payout != "pagato"
            if not passi_ok:
                manca.append("payout_gia_pagato")
        except Exception:
            # Non sapere in che stato e' il payout NON e' un dettaglio: nel dubbio i soldi
            # non partono da soli, si grida e decide una persona.
            manca.append("stato_payout_sconosciuto")
            logger.warning("rimborsi dovuti: stato payout illeggibile per %s",
                           _rif_per_registro(rif), exc_info=True)
        # ── PUNTO 2: LA VERITA' LA DICE STRIPE, NON IL NOSTRO DATABASE ──
        gia, stripe_ok, motivo_stripe = False, False, "provider Stripe assente"
        if not pi_:
            stripe_ok, motivo_stripe = True, ""   # senza pagamento non c'e' nulla da chiedere
        elif sp is not None and hasattr(sp, "rimborsi_di"):
            esito = sp.rimborsi_di(pi_)
            stripe_ok = bool(isinstance(esito, dict) and esito.get("ok"))
            motivo_stripe = "" if stripe_ok else str((esito or {}).get("motivo") or "")
            gia = bool(stripe_ok and int((esito or {}).get("rimborsato_cents") or 0) > 0)
        if not stripe_ok:
            manca.append("verifica_stripe")
        riga = {"riferimento": str(rif), "pagato_cents": pagato, "dovuto_cents": dovuto,
                "valuta": str(mov.get("valuta") or "EUR"),
                "attesa_ore": max(0, (int(_t.time()) - int(mov.get("ts") or 0)) // 3600),
                "date_liberate": date_liberate, "passi_sicurezza_ok": passi_ok,
                "payment_intent": pi_, "gia_rimborsato": gia, "manca": manca,
                "motivo_stripe": motivo_stripe,
                # ⛔ «Se manca uno di questi il bottone NON c'e'» — non «c'e' ma sconsigliato»:
                # un bottone premibile quando non si deve, prima o poi si preme.
                "bottone": (not manca) and not gia}
        return riga, stripe_ok

    def _admin_rimborsi_dovuti(self, query, headers):
        """LA LISTA DI CHI ASPETTA I SUOI SOLDI. Read-only.

        Nasce il 2026-08-16, quando si e' scoperto che delle DUE strade che portano a un
        rimborso ne era stata riparata una sola: l'ospite che cancella da solo si vede
        liberare le date, riceve «cancellata» — e i soldi restano fermi finche' una persona
        non entra qui. Decisione del fondatore: all'inizio il rimborso si fa A MANO, con
        questa lista e un pulsante. L'automatico si accende dopo, quando la lista avra'
        funzionato molte volte di fila: prima si guadagna la fiducia, poi si toglie il dito.

        ⛔ LISTA VUOTA = «niente da fare». LISTA NON CARICATA = «non lo so». Confonderle e'
        il modo esatto in cui un cassiere si convince che la cassa e' a posto — percio' se
        non si riesce a interrogare Stripe (o il giornale e' spento) questa rotta NON
        risponde «zero»: risponde `controllabile: false` col motivo (D18 condizione 1)."""
        if not self._auth_admin(headers):
            return 401, {"errore": "unauthorized"}
        fc = getattr(self._sys, "finanza", None)
        sp = getattr(self._sys, "stripe", None)
        if fc is None:
            return 200, {"controllabile": False, "in_attesa": 0, "rimborsi": [], "allarmi": [],
                         "motivo_non_controllabile":
                             "il giornale immutabile (fase177) non e' attivo: la domanda «chi "
                             "aspetta un rimborso?» non si puo' nemmeno porre"}
        if sp is None or not hasattr(sp, "rimborsi_di"):
            return 200, {"controllabile": False, "in_attesa": 0, "rimborsi": [], "allarmi": [],
                         "motivo_non_controllabile":
                             "il provider Stripe non e' attivo: senza chiedere a lui non si sa "
                             "quali rimborsi sono gia' partiti, e la lista sarebbe un'opinione"}
        # ── i candidati vengono dal GIORNALE, che non perde una riga ──
        try:
            dovuti = [m for m in fc.stream_giornale() if (m.get("tipo") or "") == "rimborso"]
        except Exception:
            logger.error("rimborsi dovuti: giornale illeggibile", exc_info=True)
            return 200, {"controllabile": False, "in_attesa": 0, "rimborsi": [], "allarmi": [],
                         "motivo_non_controllabile": "il giornale non e' leggibile in questo "
                                                     "momento: la lista NON e' vuota, e' ignota"}
        esaminati = dovuti[-self.RIMBORSI_TETTO:]
        righe, controllabile, motivi = [], True, []
        visti = set()
        for mov in reversed(esaminati):            # i piu' recenti in cima
            rif = str(mov.get("riferimento") or "")
            if not rif or rif in visti:
                continue
            visti.add(rif)
            riga, stripe_ok = self._rimborso_dovuto_scheda(rif)
            if not stripe_ok:
                controllabile = False
                if riga is not None and riga.get("motivo_stripe"):
                    motivi.append("%s: %s" % (rif, riga["motivo_stripe"]))
            if riga is not None and not riga.get("gia_rimborsato"):
                righe.append(riga)
        # ⛔ NEI DUE SENSI: se Stripe ha restituito dei soldi su una prenotazione che per noi
        # e' ancora viva, i conti divergono e nessuno se ne accorgerebbe mai.
        allarmi = []
        try:
            pp = getattr(self._sys, "pagamenti_pendenti", None)
            recenti = pp.pagati_recenti(limit=self.RIMBORSI_TETTO) \
                if (pp is not None and hasattr(pp, "pagati_recenti")) else []
        except Exception:
            logger.warning("rimborsi dovuti: elenco pagati illeggibile", exc_info=True)
            recenti = []
        for rec in recenti:
            try:
                dj = json.loads(rec.get("corpo_json") or "{}")
            except Exception:
                continue
            pi_ = str(dj.get("stripe_pi") or "")
            if not pi_:
                continue
            esito = sp.rimborsi_di(pi_)
            if not (isinstance(esito, dict) and esito.get("ok")):
                controllabile = False
                motivi.append("%s: %s" % (rec.get("riferimento"),
                                          (esito or {}).get("motivo") or "lettura fallita"))
                continue
            quanto = int(esito.get("rimborsato_cents") or 0)
            if quanto <= 0:
                continue
            allarmi.append({"riferimento": rec.get("riferimento"), "payment_intent": pi_,
                            "rimborsato_su_stripe_cents": quanto,
                            "motivo": "Stripe ha restituito dei soldi su una prenotazione che "
                                      "per noi risulta PAGATA e mai cancellata: i conti "
                                      "divergono"})
            logger.error("DIVERGENZA CONTI | rif %s | Stripe ha rimborsato %d cents su una "
                         "prenotazione che per noi e' pagata e viva: verificare a mano",
                         rec.get("riferimento"), quanto)
        if not controllabile:
            for r in righe:
                r["bottone"] = False       # non si preme senza aver potuto verificare
        return 200, {
            "controllabile": controllabile,
            "motivo_non_controllabile": ("non si e' potuto verificare su Stripe: "
                                         + "; ".join(motivi[:5])) if not controllabile else "",
            "in_attesa": len(righe), "rimborsi": righe, "allarmi": allarmi,
            # D18 condizione 3: si dichiara cosa NON e' stato guardato.
            "tetto": self.RIMBORSI_TETTO,
            "non_esaminati": max(0, len(dovuti) - len(esaminati)),
            "nota": ("i soldi NON partono da soli: ogni riga si esegue a mano col pulsante. "
                     "Una riga senza pulsante non e' pronta: dice cosa manca.")}

    def _admin_rimborsa_dovuto(self, body, headers):
        """IL PULSANTE. Restituisce all'ospite l'importo DOVUTO di UNA prenotazione.

        ⛔ Non e' `_admin_rimborso`, e la differenza sono soldi: quello nasce da una decisione
        dell'admin e restituisce il TOTALE pagato; questo chiude una cancellazione gia'
        avvenuta e restituisce quanto la politica (fase111) ha calcolato allora — cifra che
        sta scritta nel giornale immutabile, non nella richiesta.

        I QUATTRO FRENI, tutti prima che esca un centesimo: mai piu' del pagato · mai due
        volte (si richiede a Stripe adesso, piu' `Idempotency-Key` stabile) · mai se il payout
        all'host e' gia' partito · mai una cifra scritta a mano."""
        if not self._auth_admin(headers):
            return 401, {"errore": "unauthorized"}
        if not self._bunker_ok_o_field(headers, azione="rimborso"):
            return 403, {"errore": "bunker_richiesto"}
        if not self._puo_azione(headers, "rimborso"):   # 'supporto' non muove soldi
            return 403, {"errore": "permesso_negato_ruolo"}
        if self._transazioni_bloccate():
            return 503, {"errore": "transazioni_sospese"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        rif = dati.get("riferimento")
        # ⛔ UN RIFERIMENTO CHE NON HA LA FORMA DI UN RIFERIMENTO NON ENTRA, e non e'
        # pignoleria sul formato: questo valore arriva dal CORPO della richiesta e finisce nel
        # REGISTRO, che il Guardiano (fase186) legge ogni giorno per accorgersi dei guasti sui
        # soldi. Un a-capo qui dentro fabbrica righe di allarme FALSE proprio nel posto dove
        # guardiamo per sapere se e' tutto a posto -- e rimbalzava anche nella risposta.
        # Trovato da CodeQL sulla richiesta di unione #59 (7 allarmi gravi), non da noi.
        # ⚠️ Che oggi sia sfruttabile non e' dimostrato: con un riferimento inventato il
        # giornale non trova niente e si esce prima. Ma «oggi non si raggiunge» dipende dal
        # comportamento di un'altra funzione, quindi e' una conclusione con una premessa e non
        # una proprieta' (D19): qui diventa una proprieta'.
        if not (isinstance(rif, str) and _RIFERIMENTO_VALIDO.match(rif)):
            return 422, {"errore": "campi_non_validi"}
        # ⛔ FRENO 4: la scheda si RICALCOLA adesso. Tutto quello che arriva dal browser --
        # importo compreso -- viene ignorato: una cifra che sceglie chi chiama la rotta e' una
        # cifra scritta a mano su soldi veri.
        riga, stripe_ok = self._rimborso_dovuto_scheda(rif)
        if riga is None:
            return 404, {"errore": "nessun_rimborso_dovuto", "riferimento": rif}
        if riga.get("gia_rimborsato"):
            # Doppio clic: non e' un errore, e' un lavoro gia' fatto. 200, e Stripe lo conferma.
            return 200, {"stato": "gia_rimborsato", "riferimento": rif,
                         "nota": "Stripe conferma che i soldi sono gia' tornati indietro: "
                                 "nessuna seconda richiesta inviata"}
        if not stripe_ok or not riga.get("bottone"):
            logger.error("RIMBORSO DOVUTO RIFIUTATO | rif %s | manca: %r",
                         _rif_per_registro(rif), riga.get("manca"))
            return 409, {"stato": "rifiutato", "riferimento": rif, "manca": riga.get("manca"),
                         "nota": "i soldi NON partono finche' manca uno di questi elementi: "
                                 "nel dubbio decide una persona"}
        sp = getattr(self._sys, "stripe", None)
        # Chiave STABILE: la stessa di `_admin_rimborso`, cosi' le due strade non possono
        # restituire due volte gli stessi soldi nemmeno usando rotte diverse.
        esito = sp.rimborsa(riga["payment_intent"], int(riga["dovuto_cents"]), "rimborso:" + rif)
        if not (isinstance(esito, dict) and esito.get("ok")):
            motivo = (esito or {}).get("motivo") if isinstance(esito, dict) else "risposta_non_dict"
            logger.error("RIMBORSO DOVUTO FALLITO rif=%s importo=%d %s -> %s",
                         _rif_per_registro(rif), riga["dovuto_cents"], riga["valuta"], motivo)
            return 502, {"stato": "non_eseguito", "riferimento": rif, "motivo": motivo,
                         "nota": "la riga resta in lista: nessun rimborso e' partito"}
        logger.info("RIMBORSO DOVUTO ESEGUITO rif=%s importo=%d %s stripe=%s",
                    _rif_per_registro(rif), riga["dovuto_cents"], riga["valuta"],
                    esito.get("id") or "")
        return 200, {"stato": "rimborsato", "riferimento": rif,
                     "importo_cents": riga["dovuto_cents"], "valuta": riga["valuta"],
                     "stripe_refund_id": esito.get("id") or "",
                     "nota": "soldi restituiti all'ospite; la riga esce dalla lista solo "
                             "perche' Stripe lo conferma, non perche' l'abbiamo tolta noi"}

    def _admin_controversie(self, query, headers):
        """Elenco delle CONTROVERSIE aperte (garanzie contestate): l'operatore le vede, sente
        le parti, e decide lo split del rimborso. Read-only."""
        if not self._auth_admin(headers):
            return 401, {"errore": "unauthorized"}
        g = getattr(self._sys, "garanzia", None)
        if g is None:
            return 200, {"controversie": []}
        try:
            lista = g.contestate()
        except Exception:
            logger.error("admin controversie: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        # arricchisco col titolo alloggio (best-effort)
        for c in lista:
            try:
                d = self._sys.catalogo.dettaglio(c.get("alloggio_id", ""))
                c["titolo"] = d.get("titolo", "") if isinstance(d, dict) else ""
            except Exception:
                c["titolo"] = ""
        return 200, {"controversie": lista}

    def _admin_controversia_risolvi(self, body, headers):
        """Risolve una controversia con lo SPLIT deciso dall'operatore: `percentuale_ospite`
        (0-100) della somma in garanzia va rimborsata al cliente, il resto all'host. In
        alternativa `rimborso_ospite_cents` esatto. Il movimento reale dei soldi resta manuale
        (rimborso Stripe controllato) — qui si registra la DECISIONE e si sblocca la garanzia."""
        if not self._auth_admin(headers):
            return 401, {"errore": "unauthorized"}
        if not self._bunker_ok_o_field(headers, azione="controversia_risolvi"):
            return 403, {"errore": "bunker_richiesto"}
        # SCALATA DI PRIVILEGI (difetto PROVATO 2026-07-28, test_ruoli_admin_adversarial):
        # qui si decide COME si spartisce la somma in garanzia (soldi veri) e 'supporto' non
        # muove soldi: l'azione e' in AZIONI_SOLO_ADMIN, ma il gate di RUOLO non c'era.
        if not self._puo_azione(headers, "controversia_risolvi"):   # 'supporto' non arbitra
            return 403, {"errore": "permesso_negato_ruolo"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        rif = dati.get("riferimento")
        g = getattr(self._sys, "garanzia", None)
        if g is None or not (isinstance(rif, str) and rif):
            return 400, {"errore": "riferimento_mancante"}
        st = g.stato(rif)
        if not isinstance(st, dict):
            return 404, {"errore": "controversia_non_trovata"}
        if st.get("stato") != "contestato":
            return 409, {"errore": "non_in_controversia", "stato": st.get("stato")}
        importo = int(st.get("importo_host_cents", 0))
        # calcolo il rimborso: da percentuale (0-100) oppure importo esatto
        rimborso = dati.get("rimborso_ospite_cents")
        if not (isinstance(rimborso, int) and not isinstance(rimborso, bool)):
            pct = dati.get("percentuale_ospite")
            if not (isinstance(pct, (int, float)) and not isinstance(pct, bool) and 0 <= pct <= 100):
                return 422, {"errore": "percentuale_o_importo_mancante"}
            rimborso = int(importo * pct / 100)
        rimborso = max(0, min(int(rimborso), importo))
        try:
            out = g.risolvi(rif, rimborso_ospite_cents=rimborso)
        except Exception:
            logger.error("admin controversia risolvi: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        if not out.get("ok"):
            return 409, out
        # payout dell'host: azzerato se il cliente prende tutto, altrimenti resta (parziale)
        if rimborso >= importo:
            pd = getattr(self._sys, "payout", None)
            if pd is not None:
                pd.rimuovi(rif)
        else:
            # SPLIT PARZIALE: il ledger payout va RIALLINEATO alla quota host PRIMA del
            # bonifico. Senza, il record restava all'importo PIENO: dashboard host gonfiata
            # e, per chi paga a mano da `da_pagare`, all'host arrivava ANCHE la quota
            # appena rimborsata all'ospite (perdita reale, stessa classe del bug #90).
            quota_host = out.get("host_riceve_cents", importo - rimborso)
            pd = getattr(self._sys, "payout", None)
            if pd is not None:
                # il payout era stato BLOCCATO ('trattenuto') all'apertura della disputa:
                # la quota decisa dall'arbitro torna PAGABILE ('maturato') ricostruendo il
                # record (trattenuto->maturato non e' una transizione ammessa: cosi' un
                # pagamento tardivo non riattiva mai un payout in disputa per sbaglio).
                riga = pd.info(rif)
                if riga is not None:
                    pd.rimuovi(rif)
                    pd.registra_maturato(rif, riga["host_id"], quota_host, riga["valuta"])
            # la parte che spetta all'host parte da sola verso il suo conto (Connect)
            self._trasferisci_all_host(rif, quota_host)
        # SCATOLA NERA DEL RIMBORSO. Senza questa riga la decisione dell'arbitro vive solo
        # nella risposta HTTP di questo istante, e il cliente non entra nella lista di chi
        # aspetta i suoi soldi: esiste solo nella memoria di chi ha arbitrato.
        # ⚠️ LIMITE DICHIARATO: la riga comparirà SENZA pulsante. Qui il soggiorno c'è stato
        # davvero, quindi le date sono legittimamente occupate e il freno «date liberate» non
        # passa; nello split parziale scatta anche «l'host è già stato pagato», perché la sua
        # quota parte subito qui sopra. È voluto: si chiude la cecità, non si allenta un freno
        # sui soldi. Il rimborso Stripe resta manuale, come dice già la `nota` qui sotto.
        try:
            _pp = getattr(self._sys, "pagamenti_pendenti", None)
            _dj = json.loads(((_pp.info(rif) if _pp is not None else None) or {})
                             .get("corpo_json") or "{}")
        except Exception:
            _dj = {}
        self._giornale(tipo="rimborso", riferimento=rif, soggetto="ospite:" + str(rif),
                       importo_cents=int(out.get("ospite_rimborso_cents", rimborso) or 0),
                       valuta=_dj.get("valuta") or "EUR",
                       evento_id="rimborso_controversia:" + str(rif),
                       causale="rimborso deciso dall'arbitro (controversia risolta)")
        self._email_esito_controversia(rif, out.get("ospite_rimborso_cents", rimborso))
        return 200, {"stato": "risolta", "riferimento": rif,
                     "rimborso_cliente_cents": out.get("ospite_rimborso_cents", rimborso),
                     "va_all_host_cents": out.get("host_riceve_cents", importo - rimborso),
                     "nota": "decisione registrata + garanzia sbloccata; esegui il rimborso "
                             "Stripe di questo importo (manuale, controllato)"}

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
        # ORDINAMENTO: default "consigliati" (i migliori in cima, come i colossi) — se l'ospite
        # non chiede un ordine esplicito. Per consigliati/geo prendo TUTTO e riordino qui.
        ordine_guest = query.get("ordine") or "consigliati"
        _ordine_db = ordine_guest if ordine_guest in ("recente", "prezzo_asc", "prezzo_desc") \
            else "recente"
        # DATE FLESSIBILI (± giorni): se attivo, NON filtro per le date esatte in SQL; cerco
        # per ogni annuncio una finestra libera dello stesso n. di notti dentro [ci-flex, co+flex].
        flex = _int("flex_giorni") or 0
        _ciq, _coq = query.get("check_in") or None, query.get("check_out") or None
        usa_flex = flex > 0 and bool(_ciq) and bool(_coq) and geo is None
        _tutto = (geo is not None) or (ordine_guest == "consigliati") or usa_flex
        criteri = CriteriRicerca(
            citta=query.get("citta") or None,
            prezzo_min_cents=_int("prezzo_min_cents"),
            prezzo_max_cents=_int("prezzo_max_cents"),
            capacita_min=_int("capacita_min"), servizi=servizi,
            ordine=_ordine_db,
            # con geo/consigliati prendo TUTTO (poi riordino qui sotto), altrimenti la pagina
            limit=(PAGINA_MAX if _tutto else limit_req),
            offset=(0 if _tutto else (_int("offset") or 0)),
            bbox=bbox_t,
            check_in=(None if usa_flex else _ciq),
            check_out=(None if usa_flex else _coq))
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
        _memo_centro = {}
        for card in cards:
            pol = card.get("politica_cancellazione") or self._politica_alloggio(card.get("slug"))
            card["politica_cancellazione"] = pol
            card["cancellazione_gratuita"] = pol in ("flessibile", "moderata")
            # distanza dal CENTRO città (automatica, cache-first): la mostrano card+dettaglio
            dc = self._distanza_centro(card.get("citta"), card.get("lat_micro"),
                                       card.get("lon_micro"), _memo_centro)
            if dc is not None:
                card["centro_distanza_m"] = dc
        if str(query.get("solo_gratuita", "")).lower() in ("1", "true", "yes", "on"):
            cards = [c for c in cards if c.get("cancellazione_gratuita")]
            if geo is None:
                res["totale"] = len(cards)
        if usa_flex:
            # per ogni annuncio trovo la prima finestra libera di N notti dentro [ci-flex, co+flex].
            # Il calcolo del range è ora una funzione PURA (testabile): None = input invalido.
            _fin_range = finestra_flessibile(_ciq, _coq, flex)
            _da, _a, _n = _fin_range if _fin_range else (None, None, 0)
            out = []
            for c in cards:
                fin = self._sys.inventario.prima_finestra(c.get("slug"), _da, _a, _n) if _n > 0 else None
                if fin:
                    c["finestra_ci"], c["finestra_co"], c["disponibile"] = fin[0], fin[1], True
                    out.append(c)
            out.sort(key=_punteggio_consigliato, reverse=True)
            res["totale"] = len(out)
            res["risultati"] = out[:limit_req]
            res["ordine"] = "flessibile"
            res["lingua"] = lingua
            return 200, res
        if geo is not None:
            vicini = self._entro_raggio(cards, geo)   # filtrati+ordinati, NON tagliati
            res["totale"] = len(vicini)
            cards = vicini[:limit_req]
            res["ordine"] = "vicinanza"
        elif ordine_guest == "consigliati":
            # i migliori in cima (foto, recensioni, cancellazione gratuita, completezza);
            # ordinamento STABILE: a pari punteggio resta l'ordine base (recenti prima)
            cards.sort(key=_punteggio_consigliato, reverse=True)
            cards = cards[:limit_req]
            res["ordine"] = "consigliati"
        res["risultati"] = cards
        res["lingua"] = lingua
        return 200, res

    def _mappa(self, query):
        """Alloggi come GeoJSON per la MAPPA nella ricerca (come i colossi). Stessi filtri del
        catalogo (città, prezzo, servizi, 'vicino a me'); solo quelli CON coordinate. Il popup
        ha titolo, prezzo (valuta reale), recensioni e link. Pin senza coordinate -> esclusi
        (annunci non ancora geocodificati)."""
        q = dict(query)
        try:
            lim = int(q.get("limit") or 300)
        except (ValueError, TypeError):
            lim = 300
        q["limit"] = str(max(1, min(lim, 500)))       # la mappa mostra molti pin
        st, res = self._catalogo(q)
        if st != 200:
            return st, res
        feats = []
        for c in res.get("risultati", []):
            la, lo = c.get("lat_micro"), c.get("lon_micro")
            if not (isinstance(la, int) and not isinstance(la, bool)
                    and isinstance(lo, int) and not isinstance(lo, bool)):
                continue
            prezzo = c.get("prezzo_notte_cents")
            if not isinstance(prezzo, int):
                prezzo = c.get("prezzo_cents")
            feats.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lo / 1_000_000, la / 1_000_000]},
                "properties": {
                    "slug": c.get("slug", ""), "titolo": c.get("titolo", ""),
                    "citta": c.get("citta", ""),
                    "prezzo_cents": prezzo, "valuta": c.get("valuta", "EUR"),
                    "foto": c.get("thumbnail") or c.get("foto") or "",
                    "recensioni": c.get("recensioni"),
                    "cancellazione_gratuita": c.get("cancellazione_gratuita")}})
        return 200, {"type": "FeatureCollection", "features": feats,
                     "totale": res.get("totale", len(feats)), "con_coordinate": len(feats),
                     "lingua": res.get("lingua")}

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
        # ANTI-FAKE (bug provato): il diritto di recensione e' emesso al BOOK, PRIMA del pagamento
        # -> senza questo controllo si recensiva GRATIS creando un hold mai pagato (recensioni
        # verificate finte a costo zero, per gonfiare la propria vetrina o bombardare un rivale,
        # e manipolare il ranking 'consigliati'). Una recensione "verificata" richiede una
        # prenotazione PAGATA.
        if not self._recensione_ammessa(dati.get("token")):
            return 402, {"ok": False, "motivo": "prenotazione_non_pagata", "verificata": False}
        e = self._sys.recensioni.invia(dati.get("token"), dati.get("voto"),
                                       dati.get("testo", ""), dati.get("lingua", "en"),
                                       categorie=dati.get("categorie"))
        status = 201 if e.ok else (409 if e.motivo == "gia_recensita" else 400)
        return status, {"ok": e.ok, "motivo": e.motivo, "verificata": e.verificata}

    def _recensione_ammessa(self, token):
        """True se la prenotazione del diritto e' stata PAGATA (o non c'era pagamento atteso).
        Il diritto e' firmato al book (pre-pagamento): qui si blocca la recensione se l'hold non
        e' mai stato pagato. Se esiste un pendente per il riferimento, dev'essere 'pagato';
        nessun pendente = conferma immediata senza pagamento -> consentita."""
        pp = getattr(self._sys, "pagamenti_pendenti", None)
        firma = getattr(self._sys, "firma", None)
        if pp is None or firma is None:
            return True                     # nessun pagamento atteso (deploy senza pagamenti)
        try:
            d = firma.decodifica(token)
            rif = d.get("prenotazione_id") if isinstance(d, dict) else None
            if not (isinstance(rif, str) and rif):
                return True                 # diritto illeggibile qui: lo respinge invia() a valle
            rec = pp.info(rif)
            if rec is not None:
                return rec.get("stato") == "pagato"
            # RECORD ASSENTE: o non c'era pagamento atteso (conferma immediata) o
            # l'housekeeping l'ha PURGATO (26h). BUG PROVATO: dopo la purga la guardia
            # falliva-aperta e una prenotazione CANCELLATA tornava recensibile
            # "verificata" (stessa classe del bug credito #95). Segnale DUREVOLE che
            # sopravvive alla purga: il flag `rilasciato` dei movimenti INVENTARIO —
            # blocco rilasciato = cancellata/rimborsata/scaduta -> niente recensione.
            inv = getattr(self._sys, "inventario", None)
            allog = d.get("alloggio_id") if isinstance(d, dict) else None
            if inv is None or not (isinstance(allog, str) and allog):
                return True
            trovato, attivo = False, False
            for p in inv.elenco_prenotazioni(alloggio_id=allog, limit=500):
                idem = str(p.get("idem_key") or "")
                pref = idem[len("reblock:"):] if idem.startswith("reblock:") else idem[:24]
                if pref == rif:
                    trovato = True
                    if not p.get("rimborsato"):
                        attivo = True       # basta UN blocco ancora vivo (es. re-block)
            if trovato:
                return attivo
            return True                     # nessuna traccia: conferma senza pagamento
        except Exception:
            logger.warning("verifica pagamento recensione fallita (ISOLATA)", exc_info=True)
            return True                     # errore di lookup: non bloccare (il token resta valido)

    def _transazioni_bloccate(self):
        """True se il KILL-SWITCH GLOBALE d'emergenza e' attivo (fase191): congela i movimenti
        di denaro (book/rimborso/payout/carta) lasciando il sito navigabile. Isolato: mai solleva
        (in dubbio NON blocca; la env resta la rete di sicurezza autorevole)."""
        try:
            bg = getattr(self._sys, "blocco_globale", None)
            return bool(bg and bg.attivo())
        except Exception:
            return False

    def _book(self, body):
        """Prenotazione (fase59) + emissione del DIRITTO di recensione (fase63)."""
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        if self._transazioni_bloccate():           # kill-switch globale: niente nuove prenotazioni
            return 503, {"errore": "transazioni_sospese"}
        r = self._sys.concierge.prenota(dati)
        status = int(getattr(r, "status", 200))
        corpo = dict(getattr(r, "corpo", {}) or {})
        if status == 201:
            # DOPPIO CLIC (stesso preventivo firmato ripresentato): fase59 ha riconosciuto il
            # REPLAY della idem-key e NON ha ri-bloccato niente. Da qui in poi gli effetti
            # derivati NON vanno rifatti: la risposta e' quella della prenotazione che c'e' gia'
            # (o un rifiuto pulito se non e' piu' prenotabile).
            if corpo.get("idempotente"):
                gia = self._replay_prenotazione(corpo)
                if gia is not None:
                    return gia
            allog = corpo.get("alloggio_id", "")
            if self._modalita_alloggio(allog) == "su_richiesta":
                # SU RICHIESTA: la stanza e' tenuta, l'host deve APPROVARE. Niente voucher/
                # escrow/pagamento/email finche' non approva -> cliente e host rispettati.
                self._registra_richiesta(corpo, dati)
                corpo["stato"] = "in_attesa_host"
                corpo.pop("payment_url", None)
                return status, corpo
            # PAGA IN STRUTTURA (FASE 2): solo instant-book. Se l'ospite ha scelto "in struttura"
            # e le condizioni valgono, sostituisce il link col Checkout dell'ANTICIPO. Fail-safe:
            # se qualcosa non va, resta il flusso ONLINE (nessuna prenotazione persa).
            self._forse_paga_struttura(corpo, dati)
            corpo = self._finalizza_prenotazione(corpo, dati)
            if corpo.get("_rifiuta_credito"):
                return 409, {"stato": "rifiutata", "errore": corpo["_rifiuta_credito"],
                             "messaggio": "Il credito non e' stato applicato: "
                                          "rifai il preventivo."}
        return status, corpo

    def _replay_prenotazione(self, corpo):
        """DOPPIO CLIC sul book. Il blocco inventario e' tornato `idempotente=True` (stessa
        idem-key = stesso preventivo firmato). Se per quel riferimento esiste GIA' un
        pendente, rifare la finalizzazione era un DIFETTO PROVATO (2026-07-28,
        test_profondo_idempotenza):
          · 'in_attesa'/'in_attesa_host' -> SECONDA email identica all'ospite e un NUOVO
            voucher_token con `prenotato_ts` fresco: le 48h di ripensamento ripartivano da
            zero a ogni clic (rimborso pieno oltre la finestra legale);
          · 'pagato' -> risposta con `payment_url` + email "completa il pagamento" a chi
            aveva GIA' pagato: invito al DOPPIO ADDEBITO (e il webhook del secondo
            pagamento non lo avrebbe nemmeno segnalato, il CAS e' gia' 'pagato');
          · 'scaduto' -> escrow e payout RIAPERTI su una prenotazione mai pagata e con le
            date gia' liberate dallo sweeper: l'auto-rilascio dell'escrow avrebbe
            bonificato all'host soldi mai incassati (`salta_se` copre solo le rimborsate);
          · 'rimborsato'/'cancellata_host' -> escrow riaperto 'in_garanzia' su una
            prenotazione gia' rimborsata all'ospite.
        Ritorna (status, corpo) da restituire SUBITO, oppure None = prosegui normalmente
        (nessun pendente: non c'e' niente da proteggere)."""
        pp = getattr(self._sys, "pagamenti_pendenti", None)
        ref = corpo.get("riferimento", "")
        if pp is None or not (isinstance(ref, str) and ref):
            return None
        try:
            rec = pp.info(ref)
        except Exception:
            logger.warning("replay book: lettura pendente fallita (ISOLATA)", exc_info=True)
            return None
        if not isinstance(rec, dict) or not rec:
            return None
        stato = rec.get("stato", "")
        if stato in ("rimborsato", "da_rimborsare", "cancellata_host"):
            return 409, {"stato": "rifiutata", "errore": "prenotazione_annullata",
                         "riferimento": ref,
                         "messaggio": "Questa prenotazione e' stata annullata: "
                                      "rifai la ricerca."}
        if stato == "scaduto":
            return 409, {"stato": "rifiutata", "errore": "preventivo_scaduto",
                         "riferimento": ref,
                         "messaggio": "Il tempo per pagare e' scaduto e le date sono di "
                                      "nuovo libere: rifai il preventivo."}
        fuori = dict(corpo)
        try:
            import json as _jr
            salvato = _jr.loads(rec.get("corpo_json") or "{}")
        except Exception:
            salvato = {}
        if isinstance(salvato, dict):
            # gli STESSI valori della prima volta: soprattutto il voucher_token (uno solo per
            # prenotazione, con l'istante d'acquisto ORIGINALE).
            for k in ("voucher_token", "netto_host_cents", "prezzo_guest_cents",
                      "totale_cents", "commissione_cents", "costo_pagamento_cents",
                      "tassa_soggiorno_cents", "sconto_credito_cents", "valuta",
                      "modo_pagamento", "saldo_in_loco_cents", "anticipo_online_cents"):
                if salvato.get(k) not in (None, ""):
                    fuori[k] = salvato[k]
        fuori["idempotente"] = True
        if stato == "pagato":
            fuori.pop("payment_url", None)     # MAI un secondo link di pagamento
            fuori["stato"] = "pagata"
        elif stato == "in_attesa_host":
            fuori.pop("payment_url", None)
            fuori["stato"] = "in_attesa_host"
        else:
            fuori["stato"] = "in_attesa_pagamento"
        return 201, fuori

    def _modalita_alloggio(self, slug):
        try:
            m = self._sys.catalogo.modalita_prenotazione_di(slug)
            return m if m in ("immediata", "su_richiesta") else "immediata"
        except Exception:
            return "immediata"

    def _valuta_estera(self, corpo):
        """Vero se l'ANNUNCIO non e' nella valuta in cui INCASSIAMO: in quel caso Stripe deve
        convertire e aggiunge il 2% (misurato il 2026-08-09 sull'API vera, due voci separate
        nella commissione; il conto e' italiano e tiene SOLO euro, quindi la conversione non
        e' evitabile). Serve a `fase188` per non tenere una copertura carta sotto costo.
        FAIL-SAFE DALLA PARTE GIUSTA: nel dubbio si assume ESTERA. Sbagliare per eccesso costa
        all'host una frazione di punto; sbagliare per difetto la conversione la paghiamo noi."""
        try:
            cfg = getattr(self._sys, "config", None)
            incasso = str(getattr(cfg, "valuta", "EUR") or "EUR").upper()
            annuncio = str((corpo or {}).get("valuta") or incasso).upper()
            return annuncio != incasso
        except Exception:
            return True

    def _forse_paga_struttura(self, corpo, dati):
        """FASE 2 - PAGA IN STRUTTURA (solo instant-book, DARK finche' PAGA_STRUTTURA_ATTIVO=1).
        Se l'ospite ha scelto 'in_struttura' E l'annuncio lo accetta E la feature e' accesa:
        ricalcola anticipo/saldo dal totale FIRMATO (fase188 — tamper-proof: MAI dai valori del
        client), crea il Checkout dell'ANTICIPO (fase85.crea_link_anticipo, che salva anche la
        carta) e SOSTITUISCE payment_url; marca corpo perche' a valle si salti escrow/payout.
        FAIL-SAFE: qualsiasi intoppo -> resta il flusso ONLINE (corpo intatto). True se attiva."""
        try:
            if str((dati or {}).get("modo_pagamento") or "") != "in_struttura":
                return False
            import os as _os
            if _os.environ.get("PAGA_STRUTTURA_ATTIVO", "0") != "1":
                return False                       # DARK: opzione non attiva in prod
            allog = corpo.get("alloggio_id", "")
            # l'annuncio DEVE accettare (ri-verifica server-side, non ci si fida del client)
            det = None
            try:
                det = self._sys.catalogo.dettaglio(allog)
            except Exception:
                det = None
            if not (isinstance(det, dict) and bool(det.get("paga_in_struttura", True))):
                return False
            stripe = getattr(self._sys, "stripe", None)
            if stripe is None or not hasattr(stripe, "crea_link_anticipo"):
                return False
            totale = corpo.get("totale_cents")
            if not (isinstance(totale, int) and not isinstance(totale, bool) and totale > 0):
                return False
            comm = corpo.get("commissione_cents", 0)
            comm = comm if isinstance(comm, int) and not isinstance(comm, bool) else 0
            import fase188_paga_struttura as _ps
            notti = _notti_count(corpo.get("check_in", ""), corpo.get("check_out", ""))
            r = _ps.calcola(totale, notti, comm,
                            valuta_estera=self._valuta_estera(corpo))
            link = stripe.crea_link_anticipo({
                "anticipo_cents": r["anticipo_online_cents"],
                "saldo_cents": r["saldo_in_loco_cents"],
                "valuta": corpo.get("valuta", "EUR"),
                "email": (dati or {}).get("email", ""),
                "riferimento": corpo.get("riferimento", "")})
            if not link:
                logger.warning("paga-struttura: link anticipo non creato -> resto ONLINE")
                return False
            corpo["payment_url"] = link
            corpo["modo_pagamento"] = "in_struttura"
            corpo["anticipo_online_cents"] = r["anticipo_online_cents"]
            corpo["saldo_in_loco_cents"] = r["saldo_in_loco_cents"]
            corpo["fee_cents"] = r["fee_cents"]
            return True
        except Exception:
            logger.warning("paga-struttura: ramo fallito (ISOLATO) -> ONLINE", exc_info=True)
            return False

    def _finalizza_prenotazione(self, corpo, dati, hold_sec=None):
        """Emette voucher/smart-pass/diritto, apre l'escrow, avvisa l'host, gestisce l'hold
        pagamento. Usato dall'instant-book E dopo l'approvazione su-richiesta. Idempotente
        sui token (rigenera dagli stessi dati). `hold_sec` = durata custom dell'hold."""
        ref = corpo.get("riferimento", "")
        allog = corpo.get("alloggio_id", "")
        ci, co = corpo.get("check_in", ""), corpo.get("check_out", "")
        # ═══ GUARDIA INVARIANTI RUNTIME (fase199): BLOCCO pre-commit su violazione MATEMATICA. ═══
        # I3 (prova-prima-del-commit): una CONFERMA senza preventivo FIRMATO non tocca il DB.
        # I4 (denaro mai negativo): importi corrotti/negativi bloccati prima della scrittura.
        # I1/I2 restano garantiti ai loro punti (disponibilita' atomica / webhook) e DIMOSTRATI con Z3.
        # FAIL-OPEN su errore PROPRIO: una guardia difettosa non deve MAI fermare un flusso valido.
        try:
            from fase199_invarianti import i3_prova_prima_del_commit, i4_denaro_non_negativo
            _neg = i4_denaro_non_negativo({
                "prezzo_guest": corpo.get("prezzo_guest_cents", 0),
                "tassa": corpo.get("tassa_soggiorno_cents", 0),
                "anticipo": corpo.get("anticipo_online_cents", 0),
                "saldo": corpo.get("saldo_in_loco_cents", 0)})
            _senza_prova = i3_prova_prima_del_commit([{"stato": "confermata", "rif": ref,
                                                       "prova_firmata": bool(dati.get("quote_token"))}])
            if _neg or _senza_prova:
                logger.error("INVARIANTE VIOLATO al finalizza %s (negativi=%r, senza_prova=%r) "
                             "-> BLOCCO scrittura DB", ref, _neg, _senza_prova)
                return {"stato": "rifiutata", "motivo": "invariante_violato", "riferimento": ref}
        except ImportError:
            # `pass` qui rendeva la sparizione INVISIBILE: una rinomina in fase199 spegneva
            # il blocco su denaro negativo e conferma-senza-prova, in produzione, con tutto
            # verde e nemmeno una riga di log. Provato: col nome cambiato passa un importo
            # NEGATIVO. Resta fail-open (una guardia rotta non ferma un flusso valido) ma
            # ora LO DICE.
            logger.error("GUARDIA INVARIANTI ASSENTE: fase199_invarianti non importabile -> "
                         "i controlli su denaro negativo e prova-firmata NON stanno girando",
                         exc_info=True)
        except Exception:
            logger.warning("guardia invarianti fase199 fallita (ISOLATA, fail-open)", exc_info=True)
        # SINGLE-USE del Credito Fondatore/Viaggio (fase167): la prenotazione e' CONFERMATA ->
        # consuma il credito applicato, cosi' lo stesso token non sconta piu' i preventivi
        # futuri (buco provato: era riusabile all'infinito). Consumo QUI (finalizzazione), non
        # al preventivo, cosi' il browsing non brucia il credito e il su-richiesta lo consuma
        # solo se APPROVATO.
        _esito_credito = self._consuma_credito(corpo, ref)
        if _esito_credito in ("diverso", "errore"):
            # DUE casi, stesso rimedio. 'diverso': il credito era GIA' speso su un'ALTRA
            # prenotazione (race di preventivi concorrenti generati PRIMA del primo book; il
            # caso sequenziale non arriva qui, il preventivo aveva gia' azzerato lo sconto).
            # 'errore': l'archivio e' guasto e NON abbiamo potuto bruciarlo -- era fail-open
            # (2026-07-30) e confermava con lo sconto applicato e il credito ancora spendibile
            # all'infinito. In ENTRAMBI siamo PRE-PAGAMENTO (nessun soldo mosso): RIFIUTA e
            # libera la stanza. Rifiutare e' recuperabile, regalare un credito riusabile no.
            self._rilascia_per_credito(dati, allog, ci, co, ref)
            _cod = "credito_gia_usato" if _esito_credito == "diverso" else "service_unavailable"
            return {"stato": "rifiutata", "motivo": _cod,
                    "riferimento": ref, "_rifiuta_credito": _cod}
        pass_token = None
        if self._sys.emettitore_pass is not None:
            try:
                pass_token = self._sys.emettitore_pass.emetti(
                    ref, allog, ci, co, fuso=self._fuso_alloggio(allog))
                corpo["smart_pass"] = pass_token
            except Exception:
                logger.warning("emissione smart-pass fallita (ignorata)", exc_info=True)
        if getattr(self._sys, "firma", None) is not None:
            try:
                import datetime as _dt
                import time as _t_pren
                qt = dati.get("quote_token", "")
                # NUMERO OSPITI: vive solo nel PREVENTIVO FIRMATO (`party`) e non arrivava
                # fin qui, cosi' il contratto di locazione (POST /api/contratto) stampava
                # sempre "Numero ospiti: 1" anche per un soggiorno prenotato per 3 persone:
                # un dato FALSO su un documento che le parti firmano e che l'host usa per la
                # comunicazione agli alloggiati. Si porta nel voucher (firmato: non
                # manomettibile) leggendolo dal preventivo, non dal corpo della richiesta.
                _party = 0
                try:
                    _qd = self._sys.firma.decodifica(qt) if qt else None
                    _p = (_qd or {}).get("party") if isinstance(_qd, dict) else None
                    if isinstance(_p, int) and not isinstance(_p, bool) and _p > 0:
                        _party = _p
                except Exception:
                    _party = 0
                # LINGUA DELL'OSPITE: sta qui perche' il gettone e' l'unico contenitore
                # che accompagna la prenotazione ovunque ed e' FIRMATO (non manomettibile).
                # Senza, ogni email e ogni pagina successiva ripiegherebbero sull'italiano:
                # e' il difetto per cui la pagina del voucher risultava tradotta per chi
                # arrivava dal sito e italiana per chi arrivava dall'email.
                _lang_osp = _lingua({"lang": dati.get("lang")})
                corpo["voucher_token"] = self._sys.firma.codifica({
                    "tipo": "voucher", "riferimento": ref, "alloggio_id": allog,
                    "lang": _lang_osp, "party": _party,
                    "check_in": ci, "check_out": co,
                    "prezzo_guest_cents": corpo.get("prezzo_guest_cents", 0),
                    "valuta": corpo.get("valuta", "EUR"),
                    "smart_pass": pass_token or "",
                    "tassa_soggiorno_cents": corpo.get("tassa_soggiorno_cents", 0),
                    # PAGA IN STRUTTURA: firmati nel voucher cosi' la pagina e l'email possono
                    # mostrare il SALDO da pagare in loco (assenti/0 sulle prenotazioni online).
                    "modo_pagamento": corpo.get("modo_pagamento", ""),
                    "saldo_in_loco_cents": corpo.get("saldo_in_loco_cents", 0),
                    "anticipo_online_cents": corpo.get("anticipo_online_cents", 0),
                    "politica": self._politica_alloggio(allog),
                    "prenotato_data": _dt.date.today().isoformat(),   # (storico)
                    # l'ISTANTE, in secondi epoch: le 48h di ripensamento sono un diritto
                    # legale e vanno contate in secondi veri, non in giorni di calendario
                    # (che durano da 48 a 72 ore secondo l'ora in cui si prenota) ne' col
                    # "giorno" del server, che cambia alle 09:00 per un giapponese.
                    "prenotato_ts": int(_t_pren.time()),
                    "idem_key": (qt.split(".")[-1] if isinstance(qt, str) and qt else "")})
            except Exception:
                logger.warning("emissione voucher fallita (ignorata)", exc_info=True)
        if self._sys.emettitore_recensioni is not None:
            try:
                # nbf = mezzanotte del CHECK-OUT nel FUSO DELL'ALLOGGIO: si recensisce DOPO
                # il soggiorno (stile Booking/Agoda), mai prima, e "dopo" e' l'ora del
                # posto — non del server, che per un giapponese cambia giorno alle 09:00.
                # Dentro il token firmato -> non aggirabile.
                try:
                    nbf = _mezzanotte_checkout(co, self._fuso_alloggio(allog))
                except Exception:
                    nbf = None
                corpo["diritto_recensione"] = self._sys.emettitore_recensioni.emetti(
                    ref, allog, non_prima_ts=nbf)
            except Exception:
                logger.warning("emissione diritto recensione fallita (ignorata)", exc_info=True)
        # NORMALIZZATA come quella dell'host (fase88 fa lo stesso): senza, la stessa
        # persona che scrive "Mario.Rossi@" e poi "mario.rossi@" diventa due persone, e i
        # controlli che confrontano in minuscolo non riconoscono la riga salvata.
        email = dati.get("email")
        if isinstance(email, str):
            email = email.strip().lower()
            dati["email"] = email
        if getattr(self._sys, "email_provider", None) is not None \
                and isinstance(email, str) and "@" in email:
            try:
                from fase86_email import corpo_voucher_html
                from fase59_concierge import codice_prenotazione
                # SEMPRE assoluto: un link relativo (/voucher/...) NON è cliccabile da un'email.
                # Fallback al dominio se BASE_URL non è configurato (come altri link, es. host.html).
                # `?lang=`: senza, la pagina del voucher ripiega su "it" e l'ospite
                # straniero apre in italiano il documento che dovra' mostrare al check-in.
                vurl = ((self._base_url or "https://bookinvip.com") + "/voucher/"
                        + corpo["voucher_token"] + "?lang=" + _lang_osp) \
                    if corpo.get("voucher_token") else ""
                _codice = codice_prenotazione(ref)
                _pin = self._sys.firma.pin_checkin(ref) if getattr(self._sys, "firma", None) else ""
                # se c'è un pagamento da completare, l'email DEVE contenere il link (per il
                # su-richiesta è l'unico canale: il cliente non è sul sito) + oggetto onesto.
                _purl = corpo.get("payment_url", "") or ""
                # il NOME dell'alloggio, non il suo slug: l'ospite non deve leggere
                # "attico-citta-studi" al posto di «Attico Citta' Studi»
                try:
                    _d = self._sys.catalogo.dettaglio(allog)
                    _nome = (_d.get("titolo") or allog) if isinstance(_d, dict) else allog
                except Exception:
                    _nome = allog
                from fase86_email import oggetto as _oggetto_email
                # GATE STATO-PAGAMENTO anche nell'EMAIL: se c'è un pagamento da completare (_purl),
                # l'email NON contiene il PIN — solo riepilogo + link di pagamento. Il PIN arriva
                # con l'email di conferma post-pagamento (e resta dietro al voucher, gateato). Coerente
                # col gate della pagina voucher: mai il PIN prima del pagamento.
                html = corpo_voucher_html(_nome, _codice, ci, co, vurl,
                                          pin=("" if _purl else _pin),
                                          payment_url=_purl, lingua=_lang_osp)
                _ogg = _oggetto_email("v_ogg_pay" if _purl else "v_ogg_conf", _lang_osp)
                # IN BACKGROUND: l'SMTP (rete) non deve MAI rallentare la conferma prenotazione.
                # Il provider e' gia' fail-safe (non solleva); il thread e' daemon (isolato).
                import threading
                threading.Thread(
                    target=self._sys.email_provider.invia,
                    args=(email, _ogg, html),
                    daemon=True).start()
            except Exception:
                logger.warning("invio email voucher fallito (ignorato)", exc_info=True)
        self._avvisa_host_prenotazione(allog, ref, ci, co, corpo.get("fonte", ""),
                                       pagamento_pendente=bool(corpo.get("payment_url")))
        # PAGA IN STRUTTURA: il saldo lo incassa l'host DI PERSONA (non passa da noi) e
        # l'anticipo online e' interamente NOSTRO -> nessun escrow di garanzia, nessun payout
        # da maturare. Si salta il denaro-a-valle; restano hold+voucher+email (col saldo).
        if corpo.get("modo_pagamento") != "in_struttura":
            self._apri_garanzia(ref, corpo.get("netto_host_cents", 0), allog, ci)
            self._registra_payout(ref, allog, corpo)
        self._registra_hold(corpo, allog, ref, ci, co, dati.get("quote_token", ""),
                            dati.get("email", ""), hold_sec=hold_sec)
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
            # avvisa l'host SUBITO col link Approva/Rifiuta (un tocco, da qualsiasi messaggio)
            self._avvisa_host_richiesta(allog, ref, corpo.get("check_in", ""),
                                        corpo.get("check_out", ""), host)
        except Exception:
            logger.warning("registra richiesta su-richiesta fallita (ignorata)", exc_info=True)

    def _avvisa_host_richiesta(self, allog, ref, ci, co, host_id):
        """Avvisa l'host di una richiesta DA APPROVARE con i link Approva/Rifiuta (un tocco,
        da qualsiasi canale) + il link al pannello. Best-effort isolato: non blocca mai."""
        try:
            notif = getattr(self._sys, "notificatore_prenotazione", None)
            reg = getattr(self._sys, "registro_host", None)
            if notif is None or not notif.attivo() or reg is None:
                return
            contatti = reg.info_host(host_id) if host_id else None
            if not contatti:
                return
            d = self._sys.catalogo.dettaglio(allog) or {}
            titolo = (d.get("titolo") if isinstance(d, dict) else None) or allog
            link_ok = self._link_azione(ref, host_id, "approva")
            link_no = self._link_azione(ref, host_id, "rifiuta")
            pannello = (self._base_url or "https://bookinvip.com") + "/host.html"
            ogg = "Nuova richiesta di prenotazione: %s (%s -> %s)" % (titolo, ci, co)
            testo = ("Hai una nuova richiesta per \"%s\" dal %s al %s.\n\n"
                     "APPROVA:  %s\nRIFIUTA:  %s\n\n"
                     "Hai 24 ore. Approvando, il calendario si aggiorna da solo.\n"
                     "Gestisci tutto anche dal pannello: %s"
                     % (titolo, ci, co, link_ok, link_no, pannello))
            notif.avvisa(contatti, ogg, testo)
        except Exception:
            logger.warning("avviso host richiesta fallito (ignorato)", exc_info=True)

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
        ref = dati.get("riferimento")
        host_id = self._host_id_da_token(headers) or dati.get("host_id")
        return self._decidi_richiesta(ref, host_id, approva)

    def _link_azione(self, ref, host_id, azione):
        """URL FIRMATO per approvare/rifiutare una richiesta da QUALSIASI messaggio (email/
        Telegram/WhatsApp): un tocco, niente login. Firmato HMAC (fase59.firma), scade 3gg."""
        firma = getattr(self._sys, "firma", None)
        if firma is None or not ref:
            return ""
        import time as _t
        try:
            tok = firma.codifica({"k": "az_richiesta", "rif": str(ref),
                                  "hid": str(host_id or ""), "az": azione,
                                  "exp": int(_t.time()) + 3 * 86400})
        except Exception:
            return ""
        from urllib.parse import quote as _q
        return (self._base_url or "https://bookinvip.com") + "/host/azione?t=" + _q(tok)

    def _azione_richiesta(self, token):
        """Verifica il link firmato ed esegue la decisione. Ritorna un esito per la pagina."""
        firma = getattr(self._sys, "firma", None)
        d = firma.decodifica(token) if (firma and token) else None
        if not (isinstance(d, dict) and d.get("k") == "az_richiesta"):
            return {"ok": False, "motivo": "link_non_valido"}
        import time as _t
        if int(d.get("exp", 0) or 0) < int(_t.time()):
            return {"ok": False, "motivo": "link_scaduto"}
        az = d.get("az")
        if az not in ("approva", "rifiuta"):
            return {"ok": False, "motivo": "link_non_valido"}
        status, esito = self._decidi_richiesta(d.get("rif"), d.get("hid") or None,
                                               az == "approva")
        if status == 200:
            return {"ok": True, "azione": az, "stato": esito.get("stato"),
                    "riferimento": d.get("rif")}
        return {"ok": False, "azione": az,
                "motivo": esito.get("errore", "richiesta_non_trovata")}

    def _decidi_richiesta(self, ref, host_id_atteso, approva):
        """Nucleo approva/rifiuta di una richiesta 'in_attesa_host'. Riusato dall'endpoint
        autenticato E dal link firmato. Se `host_id_atteso` è dato, verifica la proprietà.
        Approva -> finalizza (blocca le date: calendario+pannello si aggiornano). Rifiuta ->
        libera la stanza. Idempotente-ish: una richiesta già decisa -> 404 (già evasa)."""
        pp = getattr(self._sys, "pagamenti_pendenti", None)
        if pp is None:
            return 503, {"errore": "richieste_non_attive"}
        rec = pp.info(ref) if isinstance(ref, str) else None
        if rec is None or rec.get("stato") != "in_attesa_host":
            return 404, {"errore": "richiesta_non_trovata"}
        # OWNERSHIP FAIL-CLOSED (audit resilienza comp.2 - IDOR): NON fidarsi dell'host_id
        # MEMORIZZATO sulla richiesta -> può essere '' se al book la lookup dell'alloggio
        # fallì (annuncio sospeso/cancellato o eccezione). Prima: con host_id vuoto il check
        # era SALTATO -> qualsiasi host approvava/rifiutava una richiesta ALTRUI (bypass di
        # autorizzazione su azione che muove stato+soldi). Ora: ri-derivo il proprietario VERO
        # dall'alloggio; per un host self-service (host_id_atteso valorizzato) deve coincidere,
        # e se l'ownership NON è confermabile -> DENY. L'operatore (host_id_atteso None) resta
        # ammesso (back-office). Il link firmato porta l'hid reale -> continua a passare.
        owner = None
        try:
            owner = self._sys.catalogo.host_di_alloggio(rec.get("alloggio_id", "")) or None
        except Exception:
            owner = None
        owner = owner or (rec.get("host_id") or None)
        if host_id_atteso and owner != host_id_atteso:
            return 403, {"errore": "non_tua"}
        import json as _j
        if approva:
            try:
                corpo = _j.loads(rec.get("corpo_json") or "{}")
            except Exception:
                corpo = {}
            # PAGAMENTO: il link Stripe creato alla RICHIESTA scade in 30 min, ma l'host ha
            # 24h per approvare -> qui va rigenerato FRESCO. Il cliente non è sul sito: paga
            # dall'email, quindi hold e sessione Stripe durano entrambi ~24h (allineati).
            hold_sec = None
            stripe = getattr(self._sys, "stripe", None)
            if stripe is not None:
                nuovo = None
                try:
                    nuovo = stripe.crea_link({
                        "totale_cents": corpo.get("totale_cents"),
                        "prezzo_guest_cents": corpo.get("prezzo_guest_cents"),
                        "valuta": corpo.get("valuta"),   # like-for-like anche sul su-richiesta approvato
                        "riferimento": ref, "email": rec.get("email", ""),
                        "scade_secondi": HOLD_APPROVAZIONE_SEC})
                except Exception:
                    nuovo = None
                if not nuovo:
                    # FAIL-SAFE: niente conferma senza un link di pagamento valido. La
                    # richiesta RESTA in_attesa_host: l'host può ricliccare tra poco.
                    logger.error("approvazione %s: link pagamento NON creato -> riprovare", ref)
                    return 503, {"errore": "pagamento_non_disponibile"}
                corpo["payment_url"] = nuovo
                hold_sec = HOLD_APPROVAZIONE_SEC
            else:
                corpo.pop("payment_url", None)   # niente Stripe: conferma diretta (no link morto)
            # ACQUISIZIONE ATOMICA (CAS, dopo il fail-safe del link): la richiesta si toglie
            # SOLO se e' ancora 'in_attesa_host'. Se un rifiuto/doppio-approva/sweeper ha
            # vinto la gara un istante prima, qui si perde e NON si finalizza: mai una
            # conferma (escrow+email "paga") su date gia' liberate da un'altra decisione.
            if not pp.rimuovi_se_stato(ref, "in_attesa_host"):
                return 404, {"errore": "richiesta_non_trovata"}
            corpo["stato"] = "confermata"
            corpo = self._finalizza_prenotazione(
                corpo, {"email": rec.get("email", ""), "quote_token": rec.get("quote_token", "")},
                hold_sec=hold_sec)
            if corpo.get("_rifiuta_credito"):
                return 409, {"errore": corpo["_rifiuta_credito"],
                             "messaggio": "Il credito non e' stato applicato."}
            return 200, {"stato": "approvata", "riferimento": ref, "prenotazione": corpo}
        # rifiuto: PRIMA l'acquisizione atomica (CAS), POI il rilascio. Se il CAS perde
        # (approva/sweeper hanno gia' deciso) NON si rilascia niente: liberare le date di
        # una richiesta appena approvata era l'overbooking. Se il processo cade tra CAS e
        # rilascio, le date restano bloccate: lato sicuro (stesso ordine dello sweeper).
        if not pp.rimuovi_se_stato(ref, "in_attesa_host"):
            return 404, {"errore": "richiesta_non_trovata"}
        try:                                       # libero la stanza, zero addebito
            self._sys.inventario.rilascia(rec["alloggio_id"], rec["check_in"], rec["check_out"],
                                          idem_key=rec.get("idem_key") or ("hold_" + str(ref)))
        except Exception:
            logger.warning("rilascio su rifiuto richiesta fallito (ignorato)", exc_info=True)
        # il cliente ha diritto di saperlo SUBITO (prima: nessun avviso, aspettava a vuoto)
        self._email_esito_richiesta(rec, "rifiutata")
        return 200, {"stato": "rifiutata", "riferimento": ref}

    def _registra_hold(self, corpo, allog, ref, ci, co, qt, email="", hold_sec=None):
        """`hold_sec`: durata custom dell'hold (es. su-richiesta approvata = ~24h, il cliente
        paga dall'email); None = default fase162 (2 min, instant-book col cliente sul checkout)."""
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
            titolo = allog
            try:
                _d = self._sys.catalogo.dettaglio(allog)
                titolo = (_d.get("titolo") if isinstance(_d, dict) else None) or allog
            except Exception:
                titolo = allog
            corpo_min = _j2.dumps({"netto_host_cents": corpo.get("netto_host_cents", 0),
                                   "prezzo_guest_cents": corpo.get("prezzo_guest_cents", 0),
                                   "totale_cents": corpo.get("totale_cents", 0),
                                   "commissione_cents": corpo.get("commissione_cents", 0),
                                   # breakdown COMPLETO -> il record riconcilia da solo:
                                   # totale == netto_host + (comm - sconto) + tassa + costo_pagamento.
                                   # Senza questi 3 il record non tornava (i conti non quadravano).
                                   "costo_pagamento_cents": corpo.get("costo_pagamento_cents", 0),
                                   "sconto_credito_cents": corpo.get("sconto_credito_cents", 0),
                                   "credito_id": corpo.get("credito_id", ""),   # quale credito ha scontato (audit)
                                   "tassa_soggiorno_cents": corpo.get("tassa_soggiorno_cents", 0),
                                   "valuta": corpo.get("valuta", "EUR"),
                                   "host_id": host_id,
                                   "voucher_token": corpo.get("voucher_token", ""),
                                   # PAGA IN STRUTTURA: il webhook/conferma leggono di qui che
                                   # e' in struttura (niente payout/garanzia) + il saldo da
                                   # incassare in loco. Assente/"" sulle prenotazioni online.
                                   "modo_pagamento": corpo.get("modo_pagamento", ""),
                                   "saldo_in_loco_cents": corpo.get("saldo_in_loco_cents", 0),
                                   "anticipo_online_cents": corpo.get("anticipo_online_cents", 0),
                                   "titolo": titolo})
            import time as _t83
            scad = (int(_t83.time()) + hold_sec) if isinstance(hold_sec, int) \
                and not isinstance(hold_sec, bool) and hold_sec > 0 else None
            pp.registra(ref, alloggio_id=allog, check_in=ci, check_out=co, idem_key=idem,
                        tassa_cents=corpo.get("tassa_soggiorno_cents", 0), comune=comune,
                        host_id=host_id, email=str(email or ""), corpo_json=corpo_min,
                        scadenza_ts=scad)
            corpo["stato"] = "in_attesa_pagamento"   # confermata SOLO dopo il webhook di pagamento
        except Exception:
            # ⛔ ERROR, NON WARNING (2026-08-08, trovato dalla PROVA GENERALE).
            #    Se questa scrittura fallisce, la prenotazione prosegue e l'ospite paga,
            #    ma il record del pendente NON ESISTE. Conseguenza misurata sul banco:
            #    alla cancellazione, `_pp`/`_rec` sono vuoti (fase83:6117) e la marcatura
            #    «da rimborsare» non avviene -> le date si liberano, l'ospite riceve
            #    un'email che gli promette il rimborso, e da NESSUNA PARTE resta scritto
            #    che quei soldi vanno restituiti.
            #    Era un warning, e `fase186:263` dichiara di leggere SOLO gli ERROR:
            #    invisibile per costruzione, esattamente come i due gemelli chiusi il
            #    2026-08-07 (`fase81._comm_alloggio` e `fase88.giorni_da_registrazione`).
            #    Il riferimento nel messaggio non e' decorazione: senza, non si sa QUALE
            #    prenotazione andare a riparare a mano.
            logger.error("HOLD PAGAMENTO NON REGISTRATO per %s: la prenotazione prosegue "
                         "ma senza il record dei pendenti, quindi un'eventuale "
                         "cancellazione NON lascera' traccia del rimborso dovuto -> "
                         "verificare a mano questa prenotazione", ref, exc_info=True)

    def _apri_garanzia(self, ref, netto_host_cents, allog, ci):
        try:
            g = getattr(self._sys, "garanzia", None)
            if g is None or not ref:
                return
            try:
                # ANCORATO al fuso VERO dell'alloggio: le 24h di contestazione partono
                # dalle 15:00 ora locale del posto, non del server. Senza fuso, ripiego
                # prudente (mai una finestra piu' stretta del giusto).
                ts = _istante_checkin(ci, self._fuso_alloggio(allog))
            except Exception:
                ts = None
            g.apri(ref, netto_host_cents, alloggio_id=allog, ora_checkin_ts=ts)
        except Exception:
            # ERROR, non warning: la prenotazione prosegue CONFERMATA ma l'ospite NON e'
            # protetto, e nessun controllo cerca le prenotazioni SENZA cassaforte. Il
            # Guardiano legge gli ERROR del registro ogni giorno (fase186): e' l'unica cosa
            # che rende questo guasto visibile invece che invisibile per sempre.
            logger.error("CASSAFORTE NON APERTA per %s: la prenotazione prosegue ma l'ospite "
                         "NON e' protetto e l'host non e' trattenuto -> intervenire a mano",
                         ref, exc_info=True)

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
                # conferma immediata (no Stripe): scala subito il credito referral dell'host
                self._applica_credito_host(ref, host, corpo.get("commissione_cents", 0))
                self._forse_qualifica_referral(host, pd)
        except Exception:
            logger.warning("registra payout fallito (ignorato)", exc_info=True)

    def _giornale(self, *, tipo, riferimento, soggetto, importo_cents, valuta,
                  causale, evento_id=None):
        """Scrive UN movimento nel giornale immutabile (fase177), COMPLETAMENTE ISOLATO:
        il registro contabile e' la scatola nera dell'audit, NON deve MAI poter rompere il
        movimento di denaro reale (che e' gia' avvenuto). Gated: se il modulo e' spento,
        no-op silenzioso."""
        try:
            fc = getattr(self._sys, "finanza", None)
            if fc is None:
                return
            if not (isinstance(importo_cents, int) and not isinstance(importo_cents, bool)
                    and importo_cents > 0):
                return
            # ⛔⛔ UN RIMBORSO NON E' SOLO DENARO CHE ESCE: CHIUDE CIO' CHE LA PRENOTAZIONE
            # AVEVA APERTO. Prima di scrivere la riga di rimborso, cio' che dovevamo all'host
            # passa all'ospite e la commissione si storna (fase177.storna_prenotazione, che
            # legge gli importi DAL GIORNALE: nessun chiamante puo' far uscire un numero
            # diverso da quello registrato).
            #
            # ⛔ STA QUI, E NON NELLE SETTE ROTTE CHE RIMBORSANO, DI PROPOSITO. Le strade che
            # portano a un rimborso sono SETTE, e questo progetto le ha gia' dimenticate due
            # volte -- il 2026-08-16 ne era stata riparata una sola su due, il 2026-08-17 ne
            # mancavano quattro su sette. Un obbligo affidato a chi si ricorda di ripeterlo in
            # sette punti si rompe di nuovo: qui non puo' sfuggirne nessuna, perche' passano
            # tutte da questa riga. Idempotente sull'evento_id: retry e doppi clic non
            # raddoppiano niente.
            #
            # ⛔ E NON E' UN EFFETTO COLLATERALE NASCOSTO: e' l'altra meta' della stessa
            # scrittura contabile. Il difetto del 2026-08-17 e' nato proprio dall'averle
            # separate -- il libro segnava un RICAVO di 30 su una prenotazione annullata.
            if tipo == "rimborso" and hasattr(fc, "storna_prenotazione"):
                try:
                    esito = fc.storna_prenotazione(riferimento=str(riferimento),
                                                   rimborso_cents=int(importo_cents))
                    if esito.get("parziale"):
                        # ⛔ `_rif_per_registro`: il riferimento arriva dal CORPO della
                        # richiesta e finisce nel registro che il Guardiano (fase186) legge
                        # ogni giorno. Un a-capo qui dentro fabbrica righe di allarme FALSE
                        # proprio nello strumento con cui si vedono i difetti. Trovato da
                        # CodeQL sulla richiesta #66 (10 allarmi, 5 gravi) su codice scritto
                        # da me poche ore prima -- ed era la STESSA classe gia' chiusa sulla
                        # #59. Il rimedio esisteva e non l'avevo usato.
                        logger.info("RIMBORSO PARZIALE su %s: lo storno della commissione NON "
                                    "e' stato fatto (l'host trattiene una penale). Limite "
                                    "dichiarato, non una dimenticanza.",
                                    _rif_per_registro(riferimento))
                except Exception:
                    # ISOLATO come tutto il giornale: la scatola nera non ferma i soldi veri.
                    logger.warning("storno prenotazione fallito (ISOLATO) su %s",
                                   _rif_per_registro(riferimento), exc_info=True)
            fc.movimento(tipo=tipo, riferimento=str(riferimento),
                         soggetto=str(soggetto), importo_cents=int(importo_cents),
                         valuta=str(valuta or "EUR"), causale=str(causale),
                         evento_id=evento_id)
        except Exception:
            logger.warning("giornale movimento '%s' fallito (ISOLATO)", tipo, exc_info=True)

    def _costo_gateway_dal_gestore(self, riferimento, dati_json, host_id, valuta):
        """Chiede a Stripe quanto si e' preso DAVVERO su quel pagamento e lo scrive nel libro.

        ⛔ COMPLETAMENTE ISOLATO, come tutto il giornale: i soldi si sono gia' mossi, e la
        scatola nera non deve mai poterli fermare.
        ⛔ E SILENZIOSO SOLO SE NON C'E' NIENTE DA DIRE: se Stripe non risponde si REGISTRA il
        motivo (regola ferrea 9 — mai il solo stato, sempre codice e messaggio). Un buco
        dichiarato si puo' colmare dopo; un buco muto no.
        ⚠️ Il costo si sa solo DOPO l'incasso, e solo se abbiamo lo `stripe_pi` sul record:
        senza quello non si indovina. E' lo stesso identificativo su cui si regge il pulsante
        dei rimborsi, quindi se manca qui manca anche li' — e lo si vede.
        """
        try:
            fc = getattr(self._sys, "finanza", None)
            sp = getattr(self._sys, "stripe", None)
            if fc is None or sp is None or not hasattr(sp, "commissione_effettiva"):
                return
            if not hasattr(fc, "costo_gateway"):
                return
            # ⛔ TUTTO CIO' CHE ENTRA NEL REGISTRO PASSA DA `_rif_per_registro`: il riferimento
            # viene dal corpo della richiesta, e il registro e' dove il Guardiano cerca i
            # guasti sui soldi. Vedi la nota estesa in `_giornale`.
            _rif = _rif_per_registro(riferimento)
            pi = str((dati_json or {}).get("stripe_pi") or "")
            if not pi:
                logger.info("costo gateway non registrabile su %s: manca lo stripe_pi sul "
                            "record (lo stesso che serve al pulsante dei rimborsi)", _rif)
                return
            esito = sp.commissione_effettiva(pi)
            if not (isinstance(esito, dict) and esito.get("ok")):
                # ⛔ Anche il motivo si ripulisce: arriva da un servizio esterno, quindi non e'
                # nostro nemmeno lui, e finisce nella stessa riga di registro.
                logger.warning("costo gateway NON LETTO su %s: %s — il prospetto lo contera' "
                               "fra gli sconosciuti, non fra i costi", _rif,
                               _rif_per_registro((esito or {}).get("motivo")
                                                 or "motivo assente"))
                return
            fee = int(esito.get("fee_cents") or 0)
            fc.costo_gateway(riferimento=str(riferimento), soggetto="host:" + str(host_id),
                             fee_cents=fee,
                             valuta=str(esito.get("valuta") or valuta or "EUR"))
            # ⛔ LO STESSO NUMERO, DA UNA SOLA LETTURA, IN DUE POSTI CHE NON POSSONO DIVERGERE.
            # Il libro (fase177) serve alla contabilita'; il record (fase162) serve al prospetto
            # del commercialista, che legge i pendenti e non il giornale. Scriverli da due
            # letture diverse sarebbe la malattia di sempre -- lo stesso fatto in due posti, e
            # la copia che resta indietro. Qui la lettura e' UNA e i due scriventi la ricevono.
            pp = getattr(self._sys, "pagamenti_pendenti", None)
            if pp is not None and hasattr(pp, "salva_costo_gateway"):
                pp.salva_costo_gateway(str(riferimento), fee)
        except Exception:
            logger.warning("costo gateway fallito (ISOLATO) su %s",
                           _rif_per_registro(riferimento), exc_info=True)

    def _dac7_payout_bloccato(self, host_id):
        """ENFORCEMENT DAC7 (art. proc. dovuta diligenza, Dir. UE 2021/514): (bloccato,
        mancanti) — True SOLO se l'host e' REPORTABILE per legge (>=30 pren O >=2000 EUR
        nell'anno corrente O precedente) E i dati fiscali sono incompleti. La direttiva
        prevede proprio la trattenuta dei pagamenti come leva quando il venditore non
        fornisce i dati. FAIL-OPEN: qualunque errore interno -> NON bloccare (il payout e'
        denaro DOVUTO all'host; il blocco e' una leva di conformita', non un invariante di
        sicurezza — un bug del controllo non deve mai congelare bonifici legittimi).
        Kill-switch: env DAC7_BLOCCO_PAYOUT=0."""
        try:
            import os as _os
            if _os.environ.get("DAC7_BLOCCO_PAYOUT", "1") == "0":
                return False, []
            reg = getattr(self._sys, "registro_host", None)
            fc = getattr(self._sys, "finanza", None)
            if reg is None or fc is None or not (isinstance(host_id, str) and host_id):
                return False, []
            info = reg.info_host(host_id)
            if not info:
                return False, []
            manca = self._dac7_mancanti(info)
            if not manca:
                return False, []                      # dati completi -> mai bloccato
            import datetime as _dt
            from fase100_dac7 import valuta_dac7
            anno_ora = _dt.datetime.utcnow().year
            for anno in (anno_ora, anno_ora - 1):
                a = fc.aggrega_dac7(anno).get(host_id)
                if a and valuta_dac7(int(a["n"]), int(a["lordo"]), True).deve_segnalare:
                    return True, manca                # sopra soglia + incompleto = bloccato
            return False, []                          # sotto soglia: nessun obbligo, si paga
        except Exception:
            logger.warning("controllo DAC7 payout fallito (FAIL-OPEN: non blocco)",
                           exc_info=True)
            return False, []

    def _verifica_payout_bloccato(self, host_id):
        """KYC DASHBOARD (Incr.10): True se il super-admin ha REVOCATO la verifica
        dell'host -> i bonifici vanno in HOLD (derivato: payout resta 'maturato') finche'
        lo stato non torna 'verificato'. SOLO 'revocato' blocca: il semplice non-verificato
        NON blocca (bloccherebbe ogni host esistente = paralisi). FAIL-OPEN su errori."""
        try:
            reg = getattr(self._sys, "registro_host", None)
            if reg is None or not (isinstance(host_id, str) and host_id):
                return False
            info = reg.info_host(host_id)
            return bool(info and info.get("verifica_stato") == "revocato")
        except Exception:
            logger.warning("controllo verifica payout fallito (FAIL-OPEN)", exc_info=True)
            return False

    # ── EMAIL DI CICLO (C3 2026-07-20): prima il cliente pagava/cancellava/contestava
    #    nel SILENZIO. Tutte best-effort in background: mai bloccare i soldi. ──────────
    def _email_bg(self, dest, oggetto, html):
        try:
            prov = getattr(self._sys, "email_provider", None)
            if prov is None or not (isinstance(dest, str) and "@" in dest):
                return
            import threading
            threading.Thread(target=prov.invia, args=(dest, oggetto, html),
                             daemon=True).start()
        except Exception:
            logger.warning("email background fallita (ignorata)", exc_info=True)

    def _email_pagamento_confermato(self, rec):
        """Dopo il webhook 'pagato': conferma con importo e link voucher (grazie.html
        prometteva un'email che prima non partiva mai)."""
        try:
            import json as _j
            try:
                dj = _j.loads(rec.get("corpo_json") or "{}")
            except Exception:
                dj = {}
            vt = dj.get("voucher_token", "")
            vurl = ((self._base_url or "https://bookinvip.com") + "/voucher/" + vt) if vt else ""
            from fase86_email import corpo_pagamento_confermato_html, oggetto
            lang = self._lang_da_voucher(vt)
            vurl = (vurl + "?lang=" + lang) if vurl else vurl
            # PAGA IN STRUTTURA: online abbiamo incassato solo l'ANTICIPO -> mostra quello come
            # "pagato" + il SALDO da dare all'host in loco. Online: importo=prezzo, saldo=0.
            _in_str = dj.get("modo_pagamento") == "in_struttura"
            _importo_email = int(dj.get("anticipo_online_cents", 0) or 0) if _in_str \
                else int(dj.get("prezzo_guest_cents", 0) or 0)
            _saldo_email = int(dj.get("saldo_in_loco_cents", 0) or 0) if _in_str else 0
            self._email_bg(rec.get("email", ""),
                           oggetto("pc_ogg", lang),
                           corpo_pagamento_confermato_html(
                               dj.get("titolo") or rec.get("alloggio_id", ""), vurl,
                               _importo_email, dj.get("valuta", "EUR"), lingua=lang,
                               saldo_cents=_saldo_email))
        except Exception:
            logger.warning("email conferma pagamento fallita (ignorata)", exc_info=True)

    def _email_cancellazione(self, rif, rimborso_cents, valuta, credito_cents):
        """Conferma di cancellazione con l'importo del rimborso nero su bianco."""
        try:
            pp = getattr(self._sys, "pagamenti_pendenti", None)
            rec = pp.info(rif) if pp is not None else None
            if not rec:
                return
            import json as _j
            try:
                dj = _j.loads(rec.get("corpo_json") or "{}")
            except Exception:
                dj = {}
            from fase86_email import corpo_cancellazione_html, oggetto
            lang = self._lang_da_voucher(dj.get("voucher_token"))
            self._email_bg(rec.get("email", ""),
                           oggetto("c_ogg", lang),
                           corpo_cancellazione_html(
                               dj.get("titolo") or rec.get("alloggio_id", ""),
                               int(rimborso_cents or 0), valuta or "EUR",
                               int(credito_cents or 0), lingua=lang))
        except Exception:
            logger.warning("email cancellazione fallita (ignorata)", exc_info=True)

    def _email_esito_controversia(self, rif, rimborso_cents):
        """L'esito dell'arbitrato arriva all'ospite (prima era invisibile)."""
        try:
            pp = getattr(self._sys, "pagamenti_pendenti", None)
            rec = pp.info(rif) if pp is not None else None
            if not rec:
                return
            import json as _j
            try:
                dj = _j.loads(rec.get("corpo_json") or "{}")
            except Exception:
                dj = {}
            from fase86_email import corpo_esito_controversia_html, oggetto
            lang = self._lang_da_voucher(dj.get("voucher_token"))
            self._email_bg(rec.get("email", ""),
                           oggetto("d_ogg", lang),
                           corpo_esito_controversia_html(int(rimborso_cents or 0),
                                                         dj.get("valuta", "EUR"),
                                                         lingua=lang))
        except Exception:
            logger.warning("email esito controversia fallita (ignorata)", exc_info=True)

    def _trasferisci_all_host(self, rif, importo_cents):
        """SOLDI ALL'HOST IN AUTOMATICO (strategia fondatore): allo sblocco dell'escrow
        (ok cliente / 24h di silenzio / esito controversia), se l'host ha Stripe collegato
        e la prenotazione era PAGATA online, il netto parte da solo verso il suo conto.
        GATED (senza Connect/account: resta manuale, tracciato), IDEMPOTENTE (Idempotency-Key
        per riferimento + guardia stato payout), ISOLATO (mai blocca il rilascio).
        ENFORCEMENT DAC7: host reportabile senza dati fiscali -> il transfer NON parte, il
        payout resta 'maturato' (tracciato, mai perso) e si sblocca da solo quando l'host
        completa i dati (retry in _host_dati_fiscali)."""
        try:
            if self._transazioni_bloccate():          # kill-switch globale: nessun bonifico
                return                                # (payout resta 'maturato', mai perso; riparte a freeze off)
            connect = getattr(self._sys, "connect", None)
            pp = getattr(self._sys, "pagamenti_pendenti", None)
            reg = getattr(self._sys, "registro_host", None)
            pd = getattr(self._sys, "payout", None)
            if connect is None or pp is None or reg is None:
                return
            if not (isinstance(importo_cents, int) and not isinstance(importo_cents, bool)
                    and importo_cents > 0):
                return
            rec = pp.info(rif)
            if rec is None or rec.get("stato") != "pagato":
                return                                # nessun incasso online -> niente transfer
            host_id = rec.get("host_id") or ""
            info = reg.info_host(host_id) if host_id else None
            acct = (info or {}).get("stripe_account_id", "")
            if not acct:
                return                                # host non collegato -> bonifico manuale
            if pd is not None and pd.stato_di(rif) in ("in_transito", "pagato"):
                return                                # gia' partito (guardia anti-doppio)
            # SCATTO ② (Debt Status): PRIMA di pagare, i debiti 'aperto' dell'host si
            # saldano ALLA FONTE (riscossione sui maturato, fase177). Puo' ridurre o
            # consumare anche QUESTO payout. Isolata: se fallisce, si paga.
            fc_ = getattr(self._sys, "finanza", None)
            if fc_ is not None and pd is not None and hasattr(fc_, "riscuoti_debiti"):
                try:
                    ris = fc_.riscuoti_debiti(host_id=host_id, payout=pd)
                    if ris.get("riscossi_cents"):
                        logger.warning("DEBT_COLLECTED | HOST_ID: %s | RISCOSSI: %d cents "
                                       "| SALDATI: %d | ANCORA APERTI: %d", host_id,
                                       ris["riscossi_cents"], ris["debiti_saldati"],
                                       ris["debiti_aperti"])
                except Exception:
                    logger.warning("riscossione debiti fallita (ISOLATA: si paga)",
                                   exc_info=True)
            # UNA SOLA VERITA' PER L'IMPORTO (fix overpay): comanda il ledger payout.
            # Se l'offset penali (Scatto ①) o la riscossione (②) hanno ridotto/consumato
            # questo payout, il bonifico parte per il RESIDUO del ledger — non per
            # l'importo del chiamante (garanzia), che non sa delle compensazioni.
            if pd is not None:
                _rp = pd.info(rif)
                if _rp is None or int(_rp.get("minori") or 0) <= 0:
                    logger.warning("PAYOUT GIA' COMPENSATO/ASSENTE | RIF: %s | HOST_ID: %s"
                                   " | nessun bonifico da inviare", rif, host_id)
                    return
                if int(_rp["minori"]) != int(importo_cents):
                    logger.warning("IMPORTO RIALLINEATO AL LEDGER | RIF: %s | richiesto %d"
                                   " -> ledger %d cents (offset/riscossione)", rif,
                                   int(importo_cents), int(_rp["minori"]))
                importo_cents = int(_rp["minori"])
            if self._verifica_payout_bloccato(host_id):
                import datetime as _dtv
                logger.warning("PAYOUT_HOLD_TRIGGERED | HOST_ID: %s | RIF: %s | IMPORTO: %d"
                               " | MOTIVO: VERIFICA_REVOCATA | DATA: %s", host_id, rif,
                               int(importo_cents),
                               _dtv.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ"))
                return                     # resta 'maturato': si sblocca alla ri-verifica
            bloccato, manca = self._dac7_payout_bloccato(host_id)
            if bloccato:
                # HOLD DERIVATO, non scritto: payout resta 'maturato' (visibile in da_pagare,
                # IMPOSSIBILE perderlo) + host-bloccato => in hold. Niente stato 'trattenuto'
                # (e' delle controversie: riusarlo farebbe sbloccare al DAC7 soldi fermati da
                # un arbitro) e NIENTE riga nel giornale (nessun denaro si e' mosso).
                # Log formato kimi, finisce nei log del Bunker (app.log persistente).
                import datetime as _dt
                logger.warning("PAYOUT_HOLD_TRIGGERED | HOST_ID: %s | RIF: %s | IMPORTO: %d | "
                               "MOTIVO: MANCANZA_DATI_FISCALI (%s) | DATA: %s",
                               host_id, rif, int(importo_cents), ",".join(manca),
                               _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ"))
                return
            import json as _jt
            try:
                valuta = _jt.loads(rec.get("corpo_json") or "{}").get("valuta") or "EUR"
            except Exception:
                valuta = "EUR"
            tid = connect.trasferisci(acct, int(importo_cents), valuta, str(rif))
            if tid:
                if pd is not None:
                    pd.aggiorna_stato(rif, "in_transito")     # soldi partiti verso l'host
                logger.info("Connect: transfer %s -> host %s (%d %s) per %s",
                            tid, host_id, importo_cents, valuta, rif)
                # SCATOLA NERA: il bonifico e' partito -> riga immutabile e datata (risponde
                # per sempre a "ma il bonifico e' stato inviato?", anche dopo N deploy).
                self._giornale(tipo="payout_host", riferimento=rif,
                               soggetto="host:" + str(host_id), importo_cents=int(importo_cents),
                               valuta=valuta, causale="bonifico Connect %s all'host" % tid)
                try:                            # C3: l'host sa di essere stato pagato
                    from fase59_concierge import codice_prenotazione as _cp
                    from fase86_email import corpo_payout_host_html, oggetto
                    lang = self._lang_host(host_id)
                    self._email_bg((info or {}).get("email", ""),
                                   oggetto("p_ogg", lang),
                                   corpo_payout_host_html(int(importo_cents), valuta,
                                                          _cp(rif), lingua=lang))
                except Exception:
                    logger.warning("email payout host fallita (ignorata)", exc_info=True)
            else:
                logger.error("BONIFICO MANUALE RICHIESTO: transfer Connect fallito per '%s' "
                             "(%d %s a %s). Il payout resta tracciato.",
                             rif, importo_cents, valuta, acct)
                # ANCHE il fallimento va nel giornale: e' ESATTAMENTE lo scenario "non ho
                # ricevuto il bonifico" -> resta la prova che si e' tentato e serve il manuale.
                self._giornale(tipo="payout_manuale", riferimento=rif,
                               soggetto="host:" + str(host_id), importo_cents=int(importo_cents),
                               valuta=valuta, causale="transfer Connect FALLITO: bonifico manuale richiesto")
        except Exception:
            logger.warning("trasferimento automatico host fallito (ISOLATO)", exc_info=True)

    def _host_stripe_link(self, headers):
        """L'host collega il suo conto Stripe (Connect standard, GRATIS): da lì i suoi
        incassi arrivano IN AUTOMATICO allo sblocco della garanzia. Crea l'account se manca
        e ritorna il link di onboarding + lo stato (pronto = riceve i bonifici)."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        hid = self._host_id_da_token(headers)
        if not hid:
            return 422, {"errore": "host_id_mancante"}
        connect = getattr(self._sys, "connect", None)
        reg = getattr(self._sys, "registro_host", None)
        if connect is None or reg is None:
            return 503, {"errore": "pagamenti_automatici_non_attivi"}
        info = reg.info_host(hid) or {}
        acct = info.get("stripe_account_id", "")
        if not acct:
            acct = connect.crea_account(info.get("email", ""))
            if not acct:
                return 503, {"errore": "stripe_non_disponibile"}
            reg.imposta_stripe_account(hid, acct)
        ritorno = (self._base_url or "https://bookinvip.com") + "/host.html"
        link = connect.link_onboarding(acct, ritorno)
        stato = connect.stato_account(acct)
        return 200, {"account_id": acct, "link": link or "",
                     "pronto": bool(stato.get("pronto"))}

    def _host_cancella(self, body, headers):
        """L'HOST annulla una prenotazione. Come i colossi (Booking/Airbnb): è colpa dell'host,
        quindi il CLIENTE è rimborsato al 100% e l'HOST paga una PENALE (deterrente contro le
        cancellazioni: se accetti una prenotazione la devi onorare). Le date si liberano."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        ref = dati.get("riferimento")
        pp = getattr(self._sys, "pagamenti_pendenti", None)
        if pp is None or not (isinstance(ref, str) and ref):
            return 400, {"errore": "riferimento_mancante"}
        rec = pp.info(ref)
        if rec is None:
            return 404, {"errore": "prenotazione_non_trovata"}
        host_id = self._host_id_da_token(headers) or dati.get("host_id")
        if rec.get("host_id") and host_id and rec["host_id"] != host_id:
            return 403, {"errore": "non_tua"}       # solo il proprietario può cancellare la sua
        if rec.get("stato") in ("cancellata_host", "rimborsato"):
            return 409, {"errore": "gia_cancellata"}
        # ESCROW GIA' LIQUIDATO -> l'host NON puo' piu' auto-cancellare (bug PROVATO
        # 2026-07-28, test_escrow_gia_liquidato). Cammino: l'ospite paga e preme "tutto ok"
        # (o passano le 24h dal check-in) -> l'escrow si chiude e il netto e' gia' PARTITO
        # verso il conto dell'host; se poi l'host cancella, qui si rimborsava il cliente al
        # 100% mentre quei soldi erano gia' fuori: la differenza (netto - penale 15%) restava
        # una PERDITA SECCA nostra, farmabile all'infinito da una coppia host+ospite
        # complice. Uno stop netto PRIMA del CAS (nessun effetto, nessuna penale): un caso
        # cosi' — cancellare un soggiorno gia' iniziato/confermato — passa dall'assistenza,
        # che ha l'arbitrato e puo' recuperare dall'host. Fail-open su errore della guardia
        # (mai bloccare una cancellazione legittima per un bug nostro).
        try:
            _gz = getattr(self._sys, "garanzia", None)
            _st = _gz.stato(ref) if _gz is not None else None
            if isinstance(_st, dict) and _st.get("stato") in ("rilasciato", "risolto") \
                    and int(_st.get("host_riceve_cents", 0) or 0) > 0:
                logger.error("HOST CANCELLA BLOCCATA | RIF: %s | escrow '%s' gia' liquidato "
                             "all'host per %d: rimborsare il cliente qui sarebbe una perdita "
                             "a nostro carico. Serve l'assistenza (arbitrato/recupero).",
                             ref, _st.get("stato"), int(_st.get("host_riceve_cents", 0) or 0))
                return 409, {"errore": "escrow_gia_liquidato",
                             "gia_liquidato_cents": int(_st.get("host_riceve_cents", 0) or 0),
                             "nota": "il soggiorno risulta gia' confermato e il pagamento "
                                     "sbloccato: contatta l'assistenza per l'annullamento."}
        except Exception:
            logger.warning("guardia escrow su cancellazione host fallita (ignorata)",
                           exc_info=True)
        import json as _j
        try:
            dj = _j.loads(rec.get("corpo_json") or "{}")
        except Exception:
            dj = {}
        guest = int(dj.get("totale_cents", 0)) or int(dj.get("prezzo_guest_cents", 0))
        valuta = dj.get("valuta", "EUR")
        pagata = rec.get("stato") == "pagato"
        # PENALE host = 15% del valore prenotazione (solo se il cliente aveva PAGATO: se non
        # aveva ancora pagato, nessun danno al cliente -> nessuna penale).
        from fase98_policy_commissione import commissione_cents
        penale = commissione_cents(guest, PENALE_HOST_BPS) if pagata else 0
        # ACQUISIZIONE ATOMICA della decisione (CAS-FIRST, come lo sweeper): la marcatura
        # 'cancellata_host' vince PRIMA di ogni effetto. Se un'altra decisione ha chiuso il
        # record un istante prima (admin rimborso, doppio click, webhook tardivo), qui si
        # esce con 409 SENZA toccare date/soldi e SENZA penale: mai una multa all'host su
        # una prenotazione chiusa dall'admin (BUG provato in gara admin∥host: stato
        # 'rimborsato' con penale 15% registrata). Crash dopo il CAS = date ancora bloccate
        # (lato sicuro, zero overbooking; i passi sotto sono idempotenti e ripetibili).
        try:
            vinta = pp.marca_cancellata_host(ref, penale)
        except Exception:
            logger.warning("host cancella: marcatura fallita (trattata come persa)",
                           exc_info=True)
            vinta = False
        if not vinta:
            return 409, {"errore": "gia_cancellata"}
        # FINANCIAL CONTROLLER (fase177, scatto ①): la NOTA DI DEBITO 15% nasce nel
        # GIORNALE prima di ogni effetto sui soldi e della conferma al client — senza
        # registro contabile scrivibile, la cancellazione NON riceve il 200 (503
        # onesto: il CAS e' gia' vinto e la RIASSERZIONE dello sweeper completa
        # giornale+offset appena possibile, pattern #32). L'offset compensa subito
        # la penale dai payout maturati dell'host (contratto art. 6).
        esito_fin = None
        fc = getattr(self._sys, "finanza", None)
        if fc is not None and penale > 0:
            esito_fin = fc.processa_penale(
                riferimento=ref, host_id=(host_id or rec.get("host_id") or ""),
                penale_cents=penale, valuta=valuta,
                payout=getattr(self._sys, "payout", None))
            if esito_fin is None:
                logger.error("host cancella %s: GIORNALE non scrivibile, 503 (la "
                             "riasserzione dello sweeper completera')", ref)
                return 503, {"errore": "registro_contabile_non_disponibile"}
        try:
            self._sys.inventario.rilascia(rec["alloggio_id"], rec["check_in"], rec["check_out"],
                                          idem_key=(rec.get("idem_key") or ("hcanc_" + ref)))
        except Exception:
            logger.warning("host cancella: rilascio date fallito (ignorato)", exc_info=True)
        pd = getattr(self._sys, "payout", None)
        if pd is not None:
            pd.rimuovi(ref)                          # l'host non incassa (il cliente è rimborsato)
        self._storna_tassa(ref)                      # tassa restituita all'ospite -> fuori dal ledger citta'
        self._revoca_checkin(ref)                    # smart-pass revocato (no sblocco su cancellata host)
        gz = getattr(self._sys, "garanzia", None)
        if gz is not None:
            try:
                gz.annulla(ref)
            except Exception:
                pass
        if pagata and guest > 0:
            # SCATOLA NERA del RIMBORSO all'ospite (cancellazione host = rimborso 100%)
            self._giornale(tipo="rimborso", riferimento=ref, soggetto="ospite:" + ref,
                           importo_cents=int(guest), valuta=valuta,
                           causale="rimborso 100% per cancellazione host")
        logger.info("HOST ha cancellato %s: cliente rimborso %d, penale host %d %s",
                    ref, guest if pagata else 0, penale, valuta)
        corpo_ok = {"stato": "cancellata_host", "riferimento": ref,
                    "rimborso_cliente_cents": (guest if pagata else 0),
                    "penale_host_cents": penale, "valuta": valuta,
                    "nota": ("cliente rimborsato al 100%; penale a carico host; date liberate"
                             if pagata else "cliente non aveva pagato: nessuna penale; date liberate")}
        if esito_fin is not None:
            corpo_ok["nota_debito"] = esito_fin.get("nota_id")
            corpo_ok["penale_compensata_cents"] = esito_fin.get("offset_cents", 0)
            corpo_ok["penale_residua_cents"] = esito_fin.get("residuo_cents", 0)
        return 200, corpo_ok

    def _payout_trattieni(self, rif):
        """Prenotazione cancellata -> il payout atteso passa a 'trattenuto' (l'host non vede piu'
        un incasso che non arrivera'). Isolato. Ritorna True se fatto (o niente da fare),
        False se e' FALLITO: chi chiama deve poterlo DIRE invece di dichiarare 'fatto'."""
        try:
            pd = getattr(self._sys, "payout", None)
            if pd is not None and isinstance(rif, str) and rif:
                pd.aggiorna_stato(rif, "trattenuto")
            return True
        except Exception:
            logger.warning("payout trattieni fallito (ignorato)", exc_info=True)
            return False

    def _storna_tassa(self, rif):
        """Prenotazione rimborsata -> storna la tassa di soggiorno dal ledger citta' (pass-through
        restituito all'ospite, non piu' dovuto). Senza, `totale_riscosso` (rendicontazione)
        sovra-conta i rimborsati. Idempotente e isolato."""
        try:
            led = getattr(self._sys, "tassa_comunale", None)
            if led is not None and hasattr(led, "storna") and isinstance(rif, str) and rif:
                led.storna(rif)
            return True
        except Exception:
            logger.warning("storno tassa fallito (ignorato)", exc_info=True)
            return False

    def _revoca_checkin(self, rif):
        """Prenotazione cancellata/rimborsata -> REVOCA il check-in (fase127): lo smart-pass
        non e' piu' emettibile e i dati ospiti pre-registrati spariscono. BUG PROVATO in
        concorrenza (40/40 seed): un ospite che fa check-in e poi cancella manteneva
        `completato=True` -> sblocco porta indebito + ospiti-fantasma nell'export. Isolato."""
        try:
            ck = getattr(self._sys, "checkin", None)
            if ck is not None and hasattr(ck, "revoca") and isinstance(rif, str) and rif:
                ck.revoca(rif)
            return True
        except Exception:
            logger.warning("revoca check-in fallita (ignorata)", exc_info=True)
            return False

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
        # Debt Status (Scatto ②): l'host VEDE il suo debito aperto (penali non ancora
        # compensate) e sa che i prossimi bonifici lo saldano alla fonte. Trasparenza.
        debiti = {}
        fc = getattr(self._sys, "finanza", None)
        if fc is not None:
            try:
                for d in fc.debiti_host(host_id, stato="aperto"):
                    v = str(d.get("valuta") or "EUR")
                    debiti[v] = debiti.get(v, 0) + int(d.get("residuo_cents") or 0)
            except Exception:
                debiti = {}
        return 200, {"payout": pd.riepilogo(host_id), "debiti_aperti_cents": debiti}

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
        # GATE STATO-PAGAMENTO (bug PROVATO 2026-07-27, test_stateful_api): conferma/contesta
        # garanzia si sbloccano SOLO a pagamento avvenuto — la pagina voucher nasconde i tasti
        # (guardia fisica), ma l'API accettava la chiamata DIRETTA col token: un ospite MAI
        # pagato poteva contestare (payout host 'trattenuto' a costo zero = griefing) o
        # confermare "tutto ok" PRIMA del soggiorno (bruciando il proprio diritto di disputa).
        # Stessa regola e stessa forma della guardia sul check-in (_checkin_pre_registra):
        # nessun pendente (conferma diretta, senza pagamento online) -> ammesso. Fail-open
        # su errore PROPRIO della guardia (mai bloccare un flusso valido per un bug nostro).
        try:
            _pp = getattr(self._sys, "pagamenti_pendenti", None)
            _rec = _pp.info(ref) if _pp is not None else None
            if _rec is not None and _rec.get("stato") != "pagato":
                return None, (409, {"errore": "pagamento_non_confermato",
                                    "stato": _rec.get("stato")})
        except Exception:
            logger.warning("guardia pagamento su garanzia fallita (ignorata)", exc_info=True)
        return (ref, dati), None

    def _voucher_valido(self, token):
        """Decodifica un voucher firmato -> dict (tipo=voucher) o None."""
        firma = getattr(self._sys, "firma", None)
        v = firma.decodifica(token) if (firma and token) else None
        return v if (isinstance(v, dict) and v.get("tipo") == "voucher") else None

    def _checkin_pre_registra(self, body):
        """CHECK-IN DIGITALE (fase127): l'ospite pre-registra i dati degli ospiti dal suo
        voucher, PRIMA dell'arrivo. Verifica capacità e formato; completato -> sblocco abilitato."""
        ck = getattr(self._sys, "checkin", None)
        if ck is None:
            return 503, {"errore": "checkin_non_attivo"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        v = self._voucher_valido(dati.get("voucher_token"))
        if v is None:
            return 400, {"errore": "voucher_non_valido"}
        allog, rif = v.get("alloggio_id", ""), v.get("riferimento", "")
        if not (allog and rif):
            return 422, {"errore": "voucher_incompleto"}
        # REGOLA AUREA (Flow 3): il check-in porta `completato=True`, che ABILITA il pass della
        # porta (fase127.sblocca). Quindi si concede SOLO a PAGAMENTO CONFERMATO ('pagato'):
        #  - 'rimborsato'/'cancellata_host' -> cancellata (evita anche ospiti-fantasma nell'export);
        #  - 'in_attesa'/'scaduto'/'in_attesa_host' (NON pagato) -> NO: prima erano ammessi
        #    ("pagamento in volo"), ma cosi' un ospite che NON paga poteva abilitare il pass =
        #    soggiorno gratis con serratura vera. Chi paga davvero e' 'pagato' in pochi secondi
        #    (webhook), ben prima dell'arrivo -> nessun ostacolo per l'ospite legittimo.
        #  - NESSUN pendente (conferma diretta, senza pagamento online) -> ammesso.
        try:
            _pp = getattr(self._sys, "pagamenti_pendenti", None)
            _rec = _pp.info(rif) if _pp is not None else None
            _st = _rec.get("stato") if _rec is not None else None
            if _st in ("rimborsato", "cancellata_host"):
                return 409, {"errore": "prenotazione_cancellata"}
            if _rec is not None and _st != "pagato":
                return 409, {"errore": "pagamento_non_confermato", "stato": _st}
        except Exception:
            logger.warning("guardia pagamento su check-in fallita (ignorata)", exc_info=True)
        cap = 1
        try:
            d = self._sys.catalogo.dettaglio(allog)
            cap = int(d.get("capacita", 1)) if isinstance(d, dict) else 1
        except Exception:
            cap = 1
        # PAGANTI, non capienza: il tetto vero e' per quante persone si e' PAGATO (la tassa di
        # soggiorno e' incassata su `party`). `party` e' FIRMATO nel voucher -> non manomettibile
        # e non serve interrogare altri archivi. Se manca (voucher storici) resta la capienza.
        _pagati = v.get("party")
        if isinstance(_pagati, int) and not isinstance(_pagati, bool) and 0 < _pagati < cap:
            cap = _pagati
        out = ck.pre_registra(rif, allog, dati.get("ospiti"), cap)
        return (200 if out.get("ok") else 422), out

    def _checkin_stato(self, query):
        """Stato del check-in (completato?) dal voucher: per mostrare all'ospite se è a posto."""
        ck = getattr(self._sys, "checkin", None)
        if ck is None:
            return 503, {"errore": "checkin_non_attivo"}
        v = self._voucher_valido(query.get("voucher_token"))
        if v is None:
            return 400, {"errore": "voucher_non_valido"}
        return 200, {"completato": ck.completato(v.get("riferimento", ""))}

    def _garanzia_conferma(self, body):
        """L'ospite e' entrato e conferma 'tutto come dichiarato' -> i soldi vanno all'host."""
        res, err = self._garanzia_da_voucher(body)
        if err:
            return err
        g = getattr(self._sys, "garanzia", None)
        if g is None:
            return 503, {"errore": "garanzia_non_attiva"}
        out = g.conferma_ospite(res[0])
        if out.get("ok"):
            # sblocco confermato dal cliente -> il netto parte da solo verso l'host (Connect)
            self._trasferisci_all_host(res[0], out.get("host_riceve_cents", 0))
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
        if out.get("ok"):
            # DISPUTA APERTA -> il payout esce dal giro pagamenti ('trattenuto'). BUG
            # PROVATO: restava 'maturato' -> `da_pagare` lo includeva e il bonifico
            # MANUALE avrebbe pagato l'host con la controversia in corso. L'esito
            # (quota/rimozione) lo decide l'arbitro in _admin_controversia_risolvi.
            try:
                pd = getattr(self._sys, "payout", None)
                if pd is not None:
                    pd.aggiorna_stato(res[0], "trattenuto")
            except Exception:
                logger.warning("blocco payout su contestazione fallito (ignorato)",
                               exc_info=True)
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
        (fase58.rilascia).

        ⛔ IL RIMBORSO ALL'OSPITE NON PARTE DA QUI, ED E' UNA SCELTA, NON UNA DIMENTICANZA.
        Decisione del fondatore del 2026-08-16: all'inizio il rimborso si esegue A MANO, dalla
        lista del pannello (`GET /api/admin/rimborsi_dovuti` -> `POST /api/admin/rimborsa_
        dovuto`) — *«se la macchina sbaglia ci rimetto conti, fiducia, credibilita'»*.
        L'automatico si accende dopo, quando la lista avra' funzionato molte volte di fila.

        ⛔ MA LA RIGA IN QUELLA LISTA NON DIPENDE DA QUESTA FUNZIONE, e non deve mai
        dipenderne: la lista si CALCOLA dallo stato (giornale immutabile + Stripe), non si
        scrive. Se qui si inserisse una riga in una coda, un errore o un riavvio in questo
        punto la farebbe sparire e il cliente aspetterebbe per sempre.

        ⚠️ Fino al 2026-08-16 qui c'era scritto *«nessuna riga di questo progetto chiama l'API
        dei rimborsi di Stripe -- verificato l'8 agosto»*. Era vero l'8 agosto e NON lo e' piu':
        `fase85.rimborsa()` esiste, ed e' chiamata da `_admin_rimborso` e da
        `_admin_rimborsa_dovuto`. Lasciarla mandava fuori strada chi legge (sbaglio S10)."""
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
        # giorni all'arrivo -> fascia di penale. "Oggi" e' il giorno NEL FUSO DELL'ALLOGGIO,
        # non del server: per un ospite alle Hawaii che cancella all'alba, il server (UTC)
        # e' gia' al giorno dopo e gli conterebbe un giorno in meno, cioe' una penale piu'
        # severa. Ancorato al posto, il conto e' quello vero per l'ospite.
        try:
            import datetime as _dtc
            fuso = self._fuso_alloggio(allog)
            oggi_locale = _dtc.date.today()
            if fuso:
                try:
                    from zoneinfo import ZoneInfo
                    oggi_locale = _dtc.datetime.now(ZoneInfo(fuso)).date()
                except Exception:
                    pass
            giorni = (_dtc.date.fromisoformat(ci) - oggi_locale).days
        except Exception:
            giorni = 0
        giorni = giorni if giorni > 0 else 0
        # CONSAPEVOLE DEL PAGAMENTO: se il record pendenti esiste e NON è 'pagato', il cliente
        # non ha versato nulla -> NIENTE rimborso/penale/credito su soldi mai incassati.
        # Il record va comunque invalidato: il link di pagamento può restare vivo fino a 24h
        # e un pagamento su prenotazione cancellata non deve MAI confermarla.
        _pp = getattr(self._sys, "pagamenti_pendenti", None)
        _rec = None
        pagato_davvero = True
        try:
            _rec = _pp.info(rif) if (_pp is not None and rif) else None
            if _rec is not None and _rec.get("stato") != "pagato":
                pagato_davvero = False
        except Exception:
            pagato_davvero = True     # in dubbio, comportamento storico (il voucher fa fede)
        if not pagato_davvero:
            pagato = 0
        # POLITICA dal VOUCHER FIRMATO (scelta dall'host, anti-furbata) - NON dalla richiesta
        politica = v.get("politica") or self._politica_alloggio(allog)
        # PAGA IN STRUTTURA (FASE 3): online abbiamo incassato solo l'ANTICIPO (fee di servizio
        # nostra); il SALDO non e' mai passato da noi (lo incassa l'host in loco) -> non c'e'
        # nulla di suo da rimborsare. L'anticipo NON e' rimborsabile su cancellazione volontaria,
        # SALVO il diritto di ripensamento 48h (tutela consumatore). Quindi: la base del rimborso
        # e' l'ANTICIPO davvero pagato (non il prezzo pieno, MAI versato online: rimborsarlo
        # sarebbe regalare soldi mai incassati) e la politica diventa 'non_rimborsabile'. Il resto
        # del flusso (rilascio stanza, invalidazione pendente, idempotenza) resta identico.
        # Attivo solo su prenotazioni gia' in_struttura -> in prod (flag off) non ne esistono.
        if v.get("modo_pagamento") == "in_struttura":
            _ant = v.get("anticipo_online_cents", 0)
            pagato = (_ant if (pagato_davvero and isinstance(_ant, int)
                               and not isinstance(_ant, bool) and _ant > 0) else 0)
            politica = "non_rimborsabile"
        # RIPENSAMENTO 48h: se annulli entro 2 giorni dall'acquisto e l'arrivo è >=72h -> 100%
        # (copre e SUPERA California SB 644 [24h] + diritto di pentimento Brasile art.49). Vince
        # su qualunque politica; NON si applica a soggiorni imminenti/passati (arrivo < 3 giorni).
        ripensamento = _entro_ripensamento(v) and (giorni >= 3)
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
        if getattr(e, "idempotente", False):
            # REPLAY: la cancellazione era GIA' stata processata (il rilascio delle date e'
            # idempotente sulla idem_key del voucher). Qui si ESCE: NON riconiare il Credito
            # Viaggio, NON ri-toccare payout/escrow. BUG PROVATO al collaudo: la guardia
            # `pagato_davvero` azzera il rimborso sul replay SOLO finche' il record pendente
            # esiste; appena l'housekeeping lo purga (`_rec is None`) fallisce-aperta e ogni
            # replay coniava un nuovo credito (fino a 5000 cents) all'infinito. Il segnale
            # `idempotente` viene dal record "rilascio:" nel DB INVENTARIO (fase58), che la
            # purga dei pendenti (fase162) non tocca -> affidabile per sempre.
            return 200, {"stato": "gia_cancellata", "riferimento": rif, "date_liberate": True,
                         "rimborso_cents": 0, "credito_viaggio_cents": 0,
                         "credito_viaggio_token": "", "money_unit": "cents_integer",
                         "nota": "prenotazione gia' cancellata: nessun nuovo credito."}
        # ESCROW PRIMA del resto: serve sapere quanto TIENE l'host (quota-penale della
        # politica) per decidere il payout. host_tiene vale SOLO se la chiusura CAS riesce.
        host_tiene = 0
        gia_uscito = 0        # quota GIA' liquidata dall'escrow (host + rimborso d'arbitrato)
        try:
            gz = getattr(self._sys, "garanzia", None)
            if gz is not None:
                st = gz.stato(rif)
                imp = st.get("importo_host_cents", 0) if isinstance(st, dict) else 0
                # ESCROW GIA' DECISO: 'rilasciato' (l'ospite ha premuto "tutto ok" -> bonifico
                # Connect gia' partito) o 'risolto' (arbitrato: quota host + quota rimborsata).
                # Quei soldi NON sono piu' in cassa nostra.
                if isinstance(st, dict) and st.get("stato") in ("rilasciato", "risolto"):
                    gia_uscito = (int(st.get("host_riceve_cents", 0) or 0)
                                  + int(st.get("ospite_rimborso_cents", 0) or 0))
                tratt = r.get("trattenuto_cents", 0)
                host_tiene = (imp * tratt // pagato) if (imp and pagato and tratt) else 0
                if host_tiene > 0:
                    esito_gz = gz.chiudi_proporzionale(rif, host_tiene)
                    if not (isinstance(esito_gz, dict) and esito_gz.get("ok")):
                        host_tiene = 0     # escrow gia' deciso altrove: non pagare due volte
                else:
                    gz.annulla(rif)        # rimborso pieno -> host 0
        except Exception:
            host_tiene = 0
            gia_uscito = 0     # in dubbio NON si taglia: mai negare un rimborso legittimo
            # ERROR, non warning: se la cassaforte non si chiude resta APERTA su una
            # prenotazione cancellata e puo' auto-rilasciarsi all'host -> rimborsiamo
            # l'ospite E paghiamo l'host = PERDITA PIENA. Il Guardiano legge gli ERROR del
            # registro ogni giorno: e' cio' che rende il guasto visibile entro 24h.
            logger.error("CASSAFORTE NON CHIUSA sulla cancellazione di %s: l'escrow resta "
                         "aperto e puo' pagare l'host di una prenotazione cancellata "
                         "(PERDITA PIENA) -> chiuderlo a mano", rif, exc_info=True)
        # TETTO DI CASSA (bug PROVATO 2026-07-28, test_escrow_gia_liquidato): la cancellazione
        # ricalcolava il rimborso dalla SOLA politica, senza guardare se l'escrow era gia' stato
        # liquidato. Cammino: paga -> preme "tutto ok" (escrow 'rilasciato' + bonifico Connect
        # all'host) -> cancella con lo stesso voucher -> politica flessibile/ripensamento = 100%
        # -> promettevamo all'ospite l'INTERO prezzo mentre la quota host era gia' USCITA:
        # perdita secca a nostro carico (26100 su 30000 nel test), farmabile da host+ospite
        # complici. Stessa falla via 'risolto' (arbitrato) e per la quota gia' rimborsata
        # dall'arbitro (doppio rimborso). Ora il rimborso e' TAGLIATO a quanto ci resta
        # davvero in cassa. Il taglio scatta SOLO su escrow gia' chiuso a favore dell'host
        # (gia_uscito>0): i rimborsi legittimi (escrow 'in_garanzia') restano identici.
        tratt_originale = r.get("trattenuto_cents", 0)
        if gia_uscito > 0 and pagato > 0:
            tetto = max(0, pagato - gia_uscito)
            if int(r.get("rimborso_cents", 0)) > tetto:
                logger.error("RIMBORSO TAGLIATO AL TETTO DI CASSA | RIF: %s | politica avrebbe "
                             "reso %d | gia' liquidato dall'escrow %d | incassato %d | reso %d",
                             rif, int(r.get("rimborso_cents", 0)), gia_uscito, pagato, tetto)
                r = dict(r)
                r["rimborso_cents"] = tetto
                r["trattenuto_cents"] = pagato - tetto
                r["tetto_cassa_cents"] = tetto
                r["gia_liquidato_cents"] = gia_uscito
        if host_tiene > 0:
            # la quota-penale e' DELL'HOST. BUG PROVATO al collaudo: il payout finiva
            # 'trattenuto' PIENO (= "non incassi niente") mentre l'escrow diceva
            # host_riceve>0, e NESSUN bonifico partiva mai (l'auto-rilascio guarda solo
            # 'in_garanzia') -> la quota dell'host restava alla piattaforma, invisibile.
            # Ora: ledger riallineato alla quota VERA + bonifico automatico (gated
            # Connect; senza account resta 'maturato' = da_pagare giusto per il manuale).
            # PRIMA di marca_da_rimborsare: il transfer esige il pendente 'pagato'.
            try:
                pd = getattr(self._sys, "payout", None)
                if pd is not None:
                    pd.imposta_importo(rif, host_tiene)
            except Exception:
                logger.warning("riallineo payout su penale fallito (ignorato)", exc_info=True)
            self._trasferisci_all_host(rif, host_tiene)
        else:
            self._payout_trattieni(rif)        # nessuna quota host -> niente payout
        # STORNA SEMPRE (non solo se pagato_davvero): il tombstone del ledger tassa deve
        # essere posato anche quando il pagamento non risulta ancora incassato, perche' un
        # webhook CONCORRENTE potrebbe registrare la tassa un istante DOPO -> senza il
        # tombstone la tassa risorgeva su una prenotazione rimborsata (BUG di concorrenza).
        self._storna_tassa(rif)                # tassa fuori dal ledger citta' + tombstone anti-race
        self._revoca_checkin(rif)              # smart-pass revocato (no sblocco su cancellata)
        try:
            if _pp is not None and _rec is not None and _rec.get("stato") != "rimborsato":
                # invalida il pendente (stato 'rimborsato'): se era pagata = rimborso manuale
                # in corso; se NON pagata = il link morto non potrà mai più confermarla.
                _pp.marca_da_rimborsare(rif)
        except Exception:
            # ERROR: senza questa marcatura il LINK DI PAGAMENTO resta VIVO (lo dice il
            # commento qui sopra) e un pagamento tardivo puo' confermare una prenotazione
            # GIA' CANCELLATA -> soldi incassati per una stanza che abbiamo liberato.
            logger.error("PENDENTE NON INVALIDATO sulla cancellazione di %s: il link di "
                         "pagamento resta VIVO e un pagamento tardivo puo' resuscitare la "
                         "prenotazione -> invalidarlo a mano", rif, exc_info=True)
        # CREDITO VIAGGIO ANTI-RIMPIANTO: se hai perso qualcosa, una parte torna come credito
        # (non-cashabile, riscattabile su una prossima prenotazione; ci costa solo margine futuro).
        # la tassa di soggiorno (pass-through) si rimborsa SEMPRE per intero: niente soggiorno = niente tassa
        tassa = v.get("tassa_soggiorno_cents", 0)
        tassa = tassa if (isinstance(tassa, int) and not isinstance(tassa, bool) and tassa > 0) else 0
        if not pagato_davvero:
            tassa = 0                          # mai versata -> niente da rimborsare
        rimborso_totale = r.get("rimborso_cents", 0) + tassa
        # LA CONTABILITA' DEVE SAPERE CHE QUEI SOLDI SONO DOVUTI. Difetto MISURATO il
        # 2026-08-08 su banco fedele, 15 prenotazioni: 6 cancellate, e per tutte e 6 il
        # giornale aveva solo l'incasso e la commissione di quando furono pagate. L'email
        # qui sotto promette il rimborso all'ospite e i conti non ne sapevano niente:
        # alla domanda «dov'e' il mio rimborso» non c'era una lista dove guardare.
        # Quando rimborsa l'ADMIN una riga viene scritta (_admin_rimborso): due cammini
        # verso lo stesso stato, uno muto. Cablaggio mancante, non scelta di progetto.
        # ⛔ STESSO `tipo="rimborso"` DELLE ALTRE DUE STRADE, e non un attrezzo piu' raffinato.
        # `fase177.aggrega_dac7` somma per host SOLO quel tipo: con una nota di credito (in
        # astratto piu' corretta, perche' il denaro non e' ancora uscito) la STESSA
        # cancellazione finirebbe nel report fiscale se la fa l'host e NON se la fa l'ospite.
        # Due report diversi per lo stesso fatto e' peggio di un'imprecisione uniforme.
        # ⚠️ DICHIARATO: `evento_id` vale 'rimborso:<rif>' ed e' idempotente, quindi se poi
        # l'admin esegue un rimborso di importo DIVERSO il giornale tiene QUESTO. E' una
        # proprieta' che le altre due strade hanno gia': non nasce qui.
        if pagato_davvero and rimborso_totale > 0:
            self._giornale(tipo="rimborso", riferimento=rif, soggetto="ospite:" + str(rif),
                           importo_cents=int(rimborso_totale),
                           valuta=v.get("valuta", "EUR"),
                           causale="rimborso dovuto per cancellazione ospite")
            # E SI VERIFICA CHE SIA ATTERRATA, non che sia stata chiamata. `_giornale`
            # isola i guasti degradandoli a WARNING, e fase186:263 dichiara di leggere
            # SOLO gli ERROR: qui l'email ha gia' promesso i soldi all'ospite, quindi un
            # warning sarebbe un `pass` scritto piu' lungo. Guardare l'EFFETTO becca anche
            # il caso in cui il movimento torni None in silenzio.
            try:
                _fc = getattr(self._sys, "finanza", None)
                _scritta = (_fc is None or any(
                    m.get("tipo") == "rimborso" for m in _fc.movimenti(str(rif))))
            except Exception:
                _scritta = False
            if not _scritta:
                logger.error("RIMBORSO DOVUTO NON REGISTRATO NEI CONTI | rif %s | %d "
                             "cents promessi all'ospite via email: registrarlo A MANO dal "
                             "pannello, o quei soldi non risultano dovuti da nessuna parte",
                             rif, rimborso_totale)
        # il credito nasce dal trattenuto ORIGINALE della politica: il taglio anti-perdita
        # (tetto di cassa) non deve MAI coniare Credito Viaggio nuovo dal nulla.
        cv_cents, cv_token = self._credito_anti_rimpianto(tratt_originale,
                                                          v.get("valuta", "EUR"))
        if pagato_davvero:                     # C3: conferma cancellazione + rimborso in email
            self._email_cancellazione(rif, rimborso_totale, v.get("valuta", "EUR"), cv_cents)
        # PAGA IN STRUTTURA (FASE 3): PENALE tardiva. Regola fondatore: normale -> si trattiene
        # solo l'anticipo (gia' fatto: rimborso 0); a <24h dal check-in -> penale = PRIMA NOTTE
        # sulla carta salvata. Best-effort ISOLATO e GATED (dark): mai un addebito reale senza
        # flag/carta. Solo su prenotazioni pagate (l'anticipo c'e' e la carta e' stata salvata).
        penale_out = None
        if v.get("modo_pagamento") == "in_struttura" and pagato_davvero:
            penale_out = self._forse_penale_struttura(rif, v, giorni)
        return 200, {"stato": "cancellata", "riferimento": rif,
                     "penale_struttura": penale_out,
                     "giorni_all_arrivo": giorni, "date_liberate": True,
                     "rimborso_cents": rimborso_totale,                 # soggiorno + tassa
                     "rimborso_soggiorno_cents": r["rimborso_cents"],
                     "tassa_rimborsata_cents": tassa,
                     "trattenuto_cents": r["trattenuto_cents"],
                     "politica": r["politica"], "money_unit": "cents_integer",
                     "ripensamento": bool(r.get("ripensamento")),
                     "pagamento_mai_effettuato": (not pagato_davvero),
                     "credito_viaggio_cents": cv_cents, "credito_viaggio_token": cv_token,
                     "nota": (("nessun addebito: non avevi ancora pagato, non c'e' nulla da "
                               "rimborsare.") if not pagato_davvero else
                              # ⛔ Questo testo lo legge un CLIENTE, non un tecnico. Diceva «il
                              # rimborso va eseguito A MANO dal pannello admin»: gli raccontava
                              # un nostro processo interno e non gli diceva l'unica cosa che gli
                              # interessa -- se e quando rivede i suoi soldi. Niente promesse sui
                              # tempi che non dipendono da noi (la banca ci mette i suoi giorni).
                              ("Cancellazione registrata e date liberate. Il rimborso torna sul "
                               "metodo di pagamento che hai usato; la tua banca puo' impiegare "
                               "qualche giorno lavorativo per accreditarlo."
                               + (" Hai un Credito Viaggio per la prossima prenotazione."
                                  if cv_cents else "")))}

    def _forse_penale_struttura(self, rif, v, giorni):
        """PAGA IN STRUTTURA (FASE 3) — PENALE cancellazione TARDIVA / no-show. Regola del
        fondatore: se la cancellazione avviene a MENO di 24h dal check-in, si addebita la PRIMA
        NOTTE (prezzo_guest / notti) sulla carta salvata; altrimenti niente (si e' gia' trattenuto
        l'anticipo). GATED da PAGA_STRUTTURA_ATTIVO (dark: senza flag NON addebita), ISOLATO (mai
        rompe la cancellazione), IDEMPOTENTE (idem-key sul riferimento). Ritorna un dict d'esito
        o None se non applicabile. Le 24h contano sull'ISTANTE vero del check-in (15:00 nel fuso
        dell'alloggio), non sul 'giorno' del server."""
        try:
            import os as _os
            if _os.environ.get("PAGA_STRUTTURA_ATTIVO", "0") != "1":
                return None                        # DARK: nessun addebito senza la feature accesa
            if self._transazioni_bloccate():       # kill-switch globale: nessun addebito carta
                return {"applicata": False, "motivo": "blocco_globale"}
            allog = v.get("alloggio_id", "")
            try:
                ts_ci = _istante_checkin(v.get("check_in", ""), self._fuso_alloggio(allog))
            except Exception:
                ts_ci = None
            import time as _t
            ore = ((ts_ci - int(_t.time())) / 3600.0) if ts_ci else (max(0, giorni) * 24)
            if ore >= 24:
                return {"applicata": False, "motivo": "non_tardiva"}   # >=24h: solo anticipo
            # penale = PRIMA NOTTE dal voucher FIRMATO (prezzo_guest / notti), interi
            prezzo = v.get("prezzo_guest_cents", 0)
            if not (isinstance(prezzo, int) and not isinstance(prezzo, bool) and prezzo > 0):
                return {"applicata": False, "motivo": "prezzo_assente"}
            notti = max(1, _notti_count(v.get("check_in", ""), v.get("check_out", "")))
            penale = prezzo // notti
            if penale <= 0:
                return {"applicata": False, "motivo": "importo_zero"}
            carta = getattr(self._sys, "carta", None)
            pp = getattr(self._sys, "pagamenti_pendenti", None)
            if carta is None or pp is None:
                return {"applicata": False, "motivo": "carta_non_attiva"}
            # customer + payment_method dalla sessione dell'anticipo (cs_ salvato dal webhook)
            import json as _j
            cs = ""
            try:
                rec = pp.info(rif)
                dj = _j.loads(rec.get("corpo_json") or "{}") if isinstance(rec, dict) else {}
                cs = dj.get("stripe_cs", "") if isinstance(dj, dict) else ""
            except Exception:
                cs = ""
            det = carta.dettagli_pagamento_da_sessione(cs) if cs else None
            if not det:
                return {"applicata": False, "motivo": "carta_non_recuperata", "importo_cents": penale}
            res = carta.addebita(customer=det["customer"], payment_method=det["payment_method"],
                                 importo_cents=penale, valuta=v.get("valuta", "EUR"),
                                 riferimento=rif, idem="penale_struttura:" + str(rif))
            stato = res.get("stato") if isinstance(res, dict) else "fallito"
            if stato == "riuscito":
                logger.warning("PENALE STRUTTURA addebitata | rif %s | %d cents (prima notte)",
                               rif, penale)
            else:
                logger.error("PENALE STRUTTURA non riuscita | rif %s | stato=%s", rif, stato)
            return {"applicata": stato == "riuscito", "importo_cents": penale, "stato": stato,
                    "motivo": (res.get("motivo", "") if isinstance(res, dict) else "")}
        except Exception:
            logger.warning("penale struttura fallita (ISOLATA)", exc_info=True)
            return {"applicata": False, "motivo": "eccezione"}

    def _politica_alloggio(self, slug):
        try:
            return self._sys.catalogo.politica_cancellazione_di(slug)
        except Exception:
            return "flessibile"

    def _lang_da_voucher(self, vt):
        """La lingua dell'ospite, letta dal gettone FIRMATO del voucher. 'en' se assente
        (mai 'it' per difetto). E' la fonte affidabile: la lingua ci viene messa alla
        prenotazione e viaggia col voucher ovunque, quindi ogni email asincrona (conferma,
        rimborso, esito, promemoria) esce nella lingua giusta."""
        try:
            firma = getattr(self._sys, "firma", None)
            v = firma.decodifica(vt) if (firma and isinstance(vt, str) and vt) else None
            if isinstance(v, dict) and v.get("lang"):
                return v["lang"]
        except Exception:
            pass
        return "en"

    def _lang_host(self, host_id):
        """La lingua dell'host, dalla sua ultima accettazione contratto (dove la lingua e'
        registrata). 'en' se ignota — mai 'it' per difetto."""
        try:
            acc = getattr(self._sys, "accettazioni", None)
            righe = acc.elenco(host_id) if acc is not None else []
            for r in reversed(righe or []):
                if isinstance(r, dict) and r.get("lang"):
                    return r["lang"]
        except Exception:
            pass
        return "en"

    def _fuso_alloggio(self, slug):
        """Il fuso IANA dell'alloggio ('Asia/Tokyo', ...) o '' se non impostato. Serve ad
        ancorare check-in, pass serratura, recensioni e cancellazione all'ora LOCALE del
        posto, mai al fuso del server o dell'ospite. '' -> i calcoli usano il ripiego
        prudente (mai una tutela piu' stretta del giusto)."""
        try:
            d = self._sys.catalogo.dettaglio(slug)
            f = d.get("fuso") if isinstance(d, dict) else ""
            return f if isinstance(f, str) else ""
        except Exception:
            return ""

    def _consuma_credito(self, corpo, ref):
        """Segna come USATO il Credito Fondatore/Viaggio applicato a questa prenotazione (fase167).
        Ritorna l'esito dello store: 'nuovo' (prima volta), 'stesso' (replay idempotente dello
        STESSO book), 'diverso' (credito gia' speso su un'ALTRA prenotazione), 'errore'
        (l'archivio e' guasto e NON abbiamo potuto bruciarlo) — o None se non c'e' nulla da
        consumare / store assente.
        ⛔ NON e' fail-open, e questo commento lo diceva: 'diverso' e 'errore' fanno RIFIUTARE
        la prenotazione e liberare la stanza (vedi il chiamante, subito dopo la guardia
        invarianti). Il fail-open c'era davvero fino al 2026-07-30, e confermava con lo sconto
        gia' applicato mentre il credito restava spendibile all'infinito: la riparazione e'
        arrivata, il commento no. Rimasto falso fino al 2026-08-11 (sbaglio S10)."""
        store = getattr(self._sys, "credito_usati", None)
        if store is None:
            return None
        cid = corpo.get("credito_id") if isinstance(corpo, dict) else None
        sconto = corpo.get("sconto_credito_cents", 0) if isinstance(corpo, dict) else 0
        if not (isinstance(cid, str) and cid) or not (isinstance(sconto, int)
                                                      and not isinstance(sconto, bool) and sconto > 0):
            return None
        try:
            return store.consuma(cid, ref)
        except Exception:
            # NON e' "niente da consumare": e' "non ho potuto bruciarlo". Confonderli
            # significava confermare con lo sconto applicato e il credito ancora spendibile.
            logger.error("consumo credito single-use FALLITO: prenotazione RIFIUTATA "
                         "(sconto gia' applicato, credito NON bruciato)", exc_info=True)
            return "errore"

    def _rilascia_per_credito(self, dati, allog, ci, co, ref):
        """Libera la stanza quando una finalizzazione viene RIFIUTATA per credito gia' usato.
        Usa la stessa idem_key del blocco (firma del quote_token) -> rilascio idempotente."""
        idem = ""
        qt = dati.get("quote_token", "") if isinstance(dati, dict) else ""
        if isinstance(qt, str) and qt:
            idem = qt.rsplit(".", 1)[-1]
        try:
            self._sys.inventario.rilascia(allog, ci, co,
                                          idem_key=(idem or ("hold_" + str(ref))))
        except Exception:
            logger.warning("rilascio su credito_gia_usato fallito (ignorato)", exc_info=True)

    def _credito_anti_rimpianto(self, trattenuto_cents, valuta="EUR"):
        """Trasforma il 50% della penale in un Credito Viaggio firmato (tetto 5000 unita'
        minori DELLA VALUTA della prenotazione). Riusa il riscatto floor-guarded del
        concierge (tipo 'credito_fondatore'). Il credito porta la SUA valuta: senza,
        una penale in valuta debole coniava un credito spendibile come €50 su annunci
        EUR (leak cross-valuta farmabile con self-booking)."""
        import time
        firma = getattr(self._sys, "firma", None)
        t = trattenuto_cents if isinstance(trattenuto_cents, int) and trattenuto_cents > 0 else 0
        cv = min(5000, t // 2)
        if firma is None or cv <= 0:
            return 0, ""
        try:
            import secrets as _sec
            val = str(valuta or "EUR").upper()
            tok = firma.codifica({"tipo": "credito_fondatore", "email": "", "citta": "",
                                  "credito_cents": cv, "valuta": val,
                                  "exp": int(time.time()) + 365 * 86400,
                                  "nonce": _sec.token_hex(8)})   # firma univoca -> single-use (fase167)
            return cv, tok
        except Exception:
            return 0, ""

    def _avvisa_host_prenotazione(self, allog, ref, ci, co, origine, pagamento_pendente=False):
        """Notifica l'host della nuova prenotazione (email + WhatsApp gated). Best-effort:
        ogni errore e' ISOLATO, non blocca mai la prenotazione gia' confermata.
        GATE STATO-PAGAMENTO: il PIN check-in NON entra nella notifica se il pagamento è ancora
        pendente (coerente col cliente); l'host lo vede nel pannello al check-in (post-pagamento)."""
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
            # stesso codice + PIN che vede il cliente (per il check-in), MA non se il pagamento è
            # ancora pendente (gate: niente PIN prima del pagamento, nemmeno all'host).
            _pin = (self._sys.firma.pin_checkin(ref) if getattr(self._sys, "firma", None)
                    and not pagamento_pendente else "")
            ogg, testo = componi_avviso_host(
                Localizzatore(), alloggio=titolo, ci=ci, co=co, origine=origine,
                riferimento=codice_prenotazione(ref), pin=_pin,
                link_pannello=(self._base_url or "https://bookinvip.com") + "/host.html",
                lingua=lingua)
            notif.avvisa(contatti, ogg, testo)
        except Exception:
            logger.warning("avviso host prenotazione fallito (ignorato)", exc_info=True)

    def _partner_registra(self, body):
        """Candidatura al programma partner (fase201): pubblica, GDPR-gated (consenso
        obbligatorio), dedup per email, tetto orario anti-flooding."""
        par = getattr(self._sys, "partner", None)
        if par is None:
            return 503, {"errore": "partner_non_attivo"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        esito = par.registra(dati.get("nome"), dati.get("email"), dati.get("tipo"),
                             citta=dati.get("citta", ""), messaggio=dati.get("messaggio", ""),
                             consenso=dati.get("consenso") is True)
        if esito.get("ok"):
            return 201, {"ok": True}
        codice = 429 if esito.get("errore") == "riprova_piu_tardi" else 422
        return codice, esito

    def _admin_partner(self, query, headers):
        """Elenco candidature partner (solo admin)."""
        if not self._auth_admin(headers):
            return 401, {"errore": "non_autorizzato"}
        par = getattr(self._sys, "partner", None)
        if par is None:
            return 503, {"errore": "partner_non_attivo"}
        try:
            limite = int(query.get("limite", "200"))
        except (TypeError, ValueError):
            limite = 200
        return 200, {"totale": par.conta(), "candidati": par.candidati(limite)}

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
        # CITTA' RIPULITA UNA VOLTA SOLA, qui (difetto PROVATO 2026-07-28, live su socket,
        # test_input_velenoso_router): `{"citta":"Rom\ud800a"}` -> surrogato isolato. Il
        # gestore fase158 lo toglieva DENTRO `registra`, ma il router continuava a usare la
        # stringa GREZZA per `conta()` (UnicodeEncodeError in sqlite), per il TOKEN del credito
        # e per il `messaggio` di risposta -> `_scrivi` non riusciva a codificare il JSON e il
        # server chiudeva la connessione SENZA RISPOSTA (dietro nginx: 502). In piu' il credito
        # veniva emesso per una citta' DIVERSA da quella archiviata. Una sola normalizzazione.
        from fase158_domanda import pulisci_testo as _pulisci_citta
        citta = _pulisci_citta(citta, 120) if isinstance(citta, str) else citta
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

    def _avvisa_domanda_ospiti(self, citta, slug):
        """COLD-START FLYWHEEL: un host pubblica il PRIMO annuncio in 'citta' -> avvisa gli OSPITI
        in lista d'attesa per quella citta (fase158) col link all'annuncio + il loro Credito
        Fondatore di benvenuto. Cosi' la domanda RACCOLTA (email lasciate quando non c'era ancora
        nulla) diventa le PRIME PRENOTAZIONI appena arriva inventario. Solo al PRIMO annuncio della
        citta (0->1): niente re-spam ai successivi. ISOLATO + gated all'email (no-op se spento)."""
        try:
            dom = getattr(self._sys, "domanda", None)
            ep = getattr(self._sys, "email_provider", None)
            if dom is None or ep is None or not (isinstance(citta, str) and citta.strip()):
                return
            from fase57_vetrina import CriteriRicerca
            res = self._sys.catalogo.cerca(CriteriRicerca(citta=citta, limit=2)) or {}
            if len(res.get("risultati") or []) != 1:      # notifica SOLO al primo annuncio (0->1)
                return
            emails = dom.email_citta(citta)
            if not emails:
                return
            from html import escape as e            # escape locale (non e' a livello modulo)
            base = self._base_url or "https://bookinvip.com"
            nome = str(citta).strip().title()
            link = "%s/alloggio/%s" % (base, slug)
            for em in emails[:2000]:
                try:
                    cred = dom.emette_credito_fondatore(em, citta)
                    credlink = ("%s/?credito=%s" % (base, cred)) if cred else base
                    ogg = "🎉 %s è aperta su BookinVIP — col tuo Credito di benvenuto" % nome
                    html = ("<p>Ciao! Avevi chiesto di essere avvisato/a per <b>%s</b>: il primo "
                            "alloggio è ora prenotabile.</p>"
                            "<p><a href=\"%s\">Guardalo qui</a> — e usa il tuo <b>Credito "
                            "Fondatore</b> sulla prima prenotazione: <a href=\"%s\">attivalo</a>.</p>"
                            % (e(nome), e(link), e(credlink)))
                    ep.invia(em, ogg, html)
                except Exception:
                    continue
        except Exception:
            logger.warning("avviso domanda ospiti fallito (ISOLATO)", exc_info=True)

    def _trasparenza(self, query, headers=None):
        """Confronto noi-vs-OTA (fase69): 'con Booking incassi X, con noi Y'. La NOSTRA
        commissione mostrata riflette quella REALE (config + rampa di lancio per l'host loggato),
        NON un 10% fisso: altrimenti la trasparenza — l'arma che converte l'host — contraddice il
        prezzo vero (mostrava 10% mentre in lancio l'host paga 0%, o mentre con COMMISSIONE_BPS=15%
        ne paga 15% e la trasparenza lo sotto-stimava)."""
        from fase69_trasparenza import confronta_piattaforma
        try:
            prezzo = int(query.get("prezzo_cents", "0"))
        except (ValueError, TypeError):
            prezzo = 0
        ota = query.get("ota", "booking")
        bps = self._commissione_bps_display(headers)
        # LA TARIFFA TECNICA VA TOLTA DAL NETTO MOSTRATO. Fino al 2026-08-10 non veniva
        # passata (e non si poteva nemmeno): il prospetto prometteva all'host un netto piu'
        # alto di quello vero -- lo stesso difetto che la docstring qui sopra dichiara di
        # aver riparato per la COMMISSIONE, lasciato aperto sull'altra meta'.
        return 200, confronta_piattaforma(prezzo, ota, commissione_nostra_bps=bps,
                                          psp_bps=self._psp_bps()).as_dict()

    def _commissione_bps_display(self, headers):
        """bps della NOSTRA commissione MARKETPLACE da mostrare in trasparenza — coerente con la
        commissione REALE addebitata da `_comm_alloggio` (fase81): con promo di lancio attiva vale
        la RAMPA per anzianità dell'host loggato (0→8→10%), altrimenti la config. Generico (nessun
        host loggato) in promo → la tariffa a regime della rampa. Fail-safe: default config."""
        cfg = getattr(self._sys, "config", None)
        base = getattr(cfg, "commissione_bps", 1000)
        base = base if isinstance(base, int) and not isinstance(base, bool) \
            and 0 <= base <= 10000 else 1000
        try:
            if getattr(cfg, "promo_lancio_attiva", False):
                # FONTE UNICA (fase98.stato_scaglione), la STESSA del motore che addebita:
                # prima questa riga usava i default della rampa mentre il motore seguiva
                # COMMISSIONE_BPS -> con una config diversa da 10% la pagina MOSTRAVA un
                # numero e il preventivo ne ADDEBITAVA un altro. Ora non e' piu' possibile.
                from fase98_policy_commissione import stato_scaglione
                reg = getattr(self._sys, "registro_host", None)
                hid = self._host_id_da_token(headers) if headers else None
                giorni = reg.giorni_da_registrazione(hid) if (hid and reg is not None) else None
                return stato_scaglione(giorni, promo_attiva=True,
                                       bps_regime_config=base)["bps"]
        except Exception:
            pass
        return base

    def _dettaglio(self, slug, lingua):
        d = self._sys.catalogo.dettaglio(slug)
        if d is None:
            return 404, {"errore": "not_found"}
        d = self._traduci_servizi(d, lingua)
        rie = self._riepilogo_recensioni(slug)
        if rie:
            d["recensioni"] = rie
        dc = self._distanza_centro(d.get("citta"), d.get("lat_micro"), d.get("lon_micro"))
        if dc is not None:
            d["centro_distanza_m"] = dc
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
        host, citta, titolo = "", "", ""
        try:
            d = self._sys.catalogo.dettaglio(allog)
            if isinstance(d, dict):
                citta = d.get("citta", "")
                # IL NOME DEL BENE LOCATO. Prima qui finiva lo SLUG e il contratto diceva
                # "Immobile: attico-citta-studi": una stringa presa dall'indirizzo web al
                # posto del nome dell'immobile, su un documento che le parti firmano.
                # Il titolo era gia' in questo stesso `d`, e veniva buttato via.
                titolo = d.get("titolo", "") or ""
            host = self._sys.catalogo.host_di_alloggio(allog) or ""
        except Exception:
            pass
        # Il contratto esiste in it/en. Per ogni altra lingua si ripiegava su ITALIANO:
        # un ospite giapponese riceveva il contratto in italiano. Ora ripiega su INGLESE.
        # (Il PDF e' costruito coi font base, Latin-1: il giapponese diventerebbe "????",
        # quindi finche' non si incorpora un font CJK l'inglese e' la risposta onesta.)
        lingua = dati.get("lingua") if dati.get("lingua") in ("it", "en") else "en"
        # Se il nome non e' scrivibile in questo PDF (font base = Latin-1: il giapponese
        # diventerebbe "????"), si usa lo SLUG, che e' ASCII per costruzione. Su un
        # documento che le parti firmano, un identificativo tecnico ma leggibile e'
        # meglio di quattro punti interrogativi.
        _nome_bene = titolo or allog
        try:
            from fase145_contratto_pdf import rappresentabile
            if titolo and not rappresentabile(titolo):
                _nome_bene = allog
        except Exception:
            pass
        info = {"host": host, "alloggio": _nome_bene, "alloggio_slug": allog,
                "citta": citta,
                "check_in": v.get("check_in", ""), "check_out": v.get("check_out", ""),
                "prezzo_cents": v.get("prezzo_guest_cents", 0), "valuta": v.get("valuta", "EUR"),
                "riferimento": v.get("riferimento", "")}
        # NUMERO OSPITI dal voucher FIRMATO (non dal corpo della richiesta: e' un dato del
        # contratto, non un'opinione del client). Voucher vecchi senza il campo -> il
        # modulo mette il suo default.
        _osp = v.get("party")
        if isinstance(_osp, int) and not isinstance(_osp, bool) and _osp > 0:
            info["ospiti"] = _osp
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

    def _concierge_manifest(self):
        """MANIFEST machine-readable per AGENTI AI — PROMESSO da /llms.txt (fase97) e prima
        inesistente: gli agenti ricevevano 404 (trovato dall'ispezione collegamenti
        2026-07-20). Descrive il flusso concierge in 3 passi. Il prezzo vive DENTRO
        quote_token FIRMATO: l'agente non puo' alterarlo. Sola lettura, nessuna chiave."""
        base = (self._base_url or "").rstrip("/")
        return 200, {
            "nome": "BookinVIP Concierge",
            "versione": 1,
            "mcp": base + "/api/mcp",
            "moneta": "centesimi interi (cents), mai float",
            "catalogo": {"metodo": "GET", "path": "/api/catalogo",
                         "nota": "ricerca alloggi (citta', date, ospiti)"},
            "flusso": [
                {"passo": 1, "metodo": "POST", "path": "/api/concierge/quote",
                 "body": {"alloggio_id": "string", "check_in": "YYYY-MM-DD",
                          "check_out": "YYYY-MM-DD", "party": "int"},
                 "ritorna": ["quote_token (prezzo FIRMATO dal sistema)",
                             "prezzo_guest_cents", "valuta"]},
                {"passo": 2, "metodo": "POST", "path": "/api/concierge/book",
                 "body": {"quote_token": "string", "email": "string"},
                 "ritorna": ["riferimento", "voucher_token",
                             "payment_url (Stripe; assente se l'host deve approvare)"]},
                {"passo": 3, "metodo": "POST", "path": "/api/concierge/cancella",
                 "body": {"voucher_token": "string"},
                 "ritorna": ["rimborso calcolato dalla politica di cancellazione, in cents"]},
            ],
        }

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
            # PAGA IN STRUTTURA (fase188): se l'annuncio lo accetta, aggiunge l'alternativa
            # (anticipo ONLINE + saldo di persona all'host + fee 1.50/notte a carico ospite).
            # Solo display: l'addebito vero (Fase 2) resta ancorato alla valuta dell'alloggio.
            # Isolato e fail-safe: se salta, la quote resta intatta.
            # CONTRATTO STABILE: il default si scrive PRIMA del try, altrimenti un errore
            # dentro il blocco (es. catalogo.dettaglio che solleva) faceva SPARIRE del tutto
            # la chiave invece di lasciarla a {"accettato": False} -> forma della risposta
            # variabile a seconda dei guasti. La chiave c'e' sempre.
            corpo["paga_in_struttura"] = {"accettato": False}
            try:
                # lo slug si legge dal preventivo (corpo), NON da `body`: qui `body` e' ancora
                # la STRINGA JSON grezza (niente .get) -> l'avrebbe fatto saltare in silenzio.
                slug = str(corpo.get("alloggio_id") or "")
                cat = getattr(self._sys, "catalogo", None)
                det = cat.dettaglio(slug) if (cat is not None and slug) else None
                # DARK LAUNCH: la vetrina ospite resta SPENTA finche' la FASE 2 (carta +
                # addebito anticipo) non e' pronta -> PAGA_STRUTTURA_ATTIVO=1 la accende. Cosi'
                # il codice sta gia' su Desktop=GitHub=VPS, ma l'ospite non vede un'opzione che
                # non puo' ancora SCEGLIERE. Toggle host e calcolo restano attivi (innocui).
                import os as _os
                attivo = _os.environ.get("PAGA_STRUTTURA_ATTIVO", "0") == "1"
                accetta = attivo and (bool(det.get("paga_in_struttura", True))
                                      if isinstance(det, dict) else False)
                tot = corpo.get("totale_cents")
                comm = corpo.get("commissione_cents")
                nn = corpo.get("notti")
                if (accetta and isinstance(tot, int) and not isinstance(tot, bool) and tot > 0):
                    import fase188_paga_struttura as _ps
                    r = _ps.calcola(tot, nn,
                                    comm if isinstance(comm, int) and not isinstance(comm, bool) else 0,
                                    valuta_estera=self._valuta_estera(corpo))
                    corpo["paga_in_struttura"] = {
                        "accettato": True,
                        "ospite_paga_totale_cents": r["ospite_paga_totale_cents"],
                        "anticipo_online_cents": r["anticipo_online_cents"],
                        "saldo_in_loco_cents": r["saldo_in_loco_cents"],
                        "fee_cents": r["fee_cents"],
                    }
                else:
                    corpo["paga_in_struttura"] = {"accettato": False}
            except Exception:
                logger.warning("paga-in-struttura quote fallito (ignorato)", exc_info=True)
        return status, corpo

    def _fmt_importo(self, cents, valuta):
        """Centesimi -> stringa leggibile nella valuta (esponente fase99: JPY 0, BHD 3).
        Solo interi, mai float."""
        if not isinstance(cents, int) or isinstance(cents, bool):
            return ""
        v = str(valuta or "EUR")
        try:
            from fase99_multicurrency import esponente
            e = esponente(v)
        except Exception:
            e = 2
        if e <= 0:
            return "%d %s" % (cents, v)
        return "%d.%0*d %s" % (cents // 10 ** e, e, cents % 10 ** e, v)

    def _preventivo_email(self, body):
        """RECUPERO PREVENTIVO onesto (senza tracking): l'ospite CHIEDE la sua quote
        via email (consenso esplicito col clic) -> UNA email transazionale col
        riepilogo e il link per completare. L'indirizzo si usa per l'invio e basta:
        nessun archivio marketing, nessun promemoria. Anti-abuso: stesso preventivo
        alla stessa email al massimo 1 volta ogni 10 minuti. Il preventivo viene
        RICALCOLATO dal server (mai fidarsi dei numeri del client)."""
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        email = dati.get("email")
        # Validazione stretta a MONTE: il destinatario e' scelto dal chiamante -> niente
        # caratteri di controllo (\r\n = tentativo di header-injection SMTP: aggiungere Bcc a
        # terzi). Python blocca l'injection a valle (HeaderParseError), ma l'input sporco va
        # respinto qui con un 422 chiaro invece di far fallire l'invio in silenzio.
        if not (isinstance(email, str) and "@" in email and 3 <= len(email) <= 254
                and not any(ord(c) < 32 or c in " <>" for c in email)):
            return 422, {"errore": "email_non_valida"}
        prov = getattr(self._sys, "email_provider", None)
        if prov is None:
            return 503, {"errore": "email_non_disponibile"}
        slug = dati.get("alloggio_id") or dati.get("slug")
        ci = str(dati.get("check_in", "") or "")
        co = str(dati.get("check_out", "") or "")
        if not (isinstance(slug, str) and slug and ci and co):
            return 422, {"errore": "campi_mancanti"}
        # throttle in-process: 1 invio per (email, alloggio, date) ogni 10 minuti
        import time as _t
        mem = getattr(self, "_prev_email_ts", None)
        if mem is None:
            mem = {}
            self._prev_email_ts = mem
        ora = _t.time()
        for k in [k for k, ts in mem.items() if ora - ts > 3600]:
            mem.pop(k, None)
        chiave = (email.strip().lower(), slug, ci, co)
        if ora - mem.get(chiave, 0) < 600:
            return 429, {"errore": "gia_inviato_riprova_piu_tardi"}
        # TETTO PER INDIRIZZO (anti-abuso, collaudo 2026-07-15). Il throttle qui sopra e' per
        # (email, alloggio, DATE): si aggira BANALMENTE cambiando data -> PROVATO che si potevano
        # spedire N email a un estraneo. Questo endpoint manda posta a un indirizzo scelto dal
        # chiamante: senza tetto siamo un mezzo per bombardare terzi DAL NOSTRO dominio. Il danno
        # vero non e' lo spam: e' info@bookinvip.com in BLACKLIST -> voucher e avvisi host non
        # consegnati piu' (cioe' il prodotto muore in silenzio).
        em = email.strip().lower()
        storia = getattr(self, "_prev_email_storia", None)
        if storia is None:
            storia = {}
            self._prev_email_storia = storia
        recenti = [t for t in storia.get(em, []) if ora - t < 3600]
        storia[em] = recenti
        for k in [k for k, v in list(storia.items()) if not v]:
            storia.pop(k, None)                      # niente crescita infinita in memoria
        if len(recenti) >= MAX_PREVENTIVI_EMAIL_ORA:
            return 429, {"errore": "troppe_richieste_per_questa_email"}
        # ricalcolo dal server: se le date non reggono piu', niente email (onesto)
        try:
            r = self._sys.concierge.quota({
                "alloggio_id": slug, "check_in": ci, "check_out": co,
                "party": dati.get("party", dati.get("ospiti", 1)),
                "fonte": str(dati.get("fonte", "") or ""),
            })
            status, corpo = int(getattr(r, "status", 200)), getattr(r, "corpo", {}) or {}
        except Exception:
            logger.warning("preventivo email: quota ISOLATA fallita", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        if status != 200 or not corpo.get("quote_token"):
            return 422, {"errore": "non_disponibile"}
        titolo = slug
        try:
            det = self._sys.catalogo.dettaglio(slug)
            if isinstance(det, dict) and det.get("titolo"):
                titolo = str(det["titolo"])
        except Exception:
            pass
        # 8 LINGUE PIENE (ripiego EN), non piu' it/en binario: il template ha gia' tutte e 8
        # le lingue, prima le ETICHETTE righe + l'oggetto le annullavano a it/en.
        lang = _lingua({"lang": dati.get("lang")})
        from fase86_email import corpo_preventivo_html, T as _T, oggetto as _oggetto_email
        v = corpo.get("valuta", "EUR")
        notti = corpo.get("notti")
        et_sogg = _T("prev_sogg", lang) + (
            " (%s %s)" % (notti, _T("prev_notti", lang)) if notti else "")
        righe = [(et_sogg, self._fmt_importo(corpo.get("prezzo_guest_cents"), v))]
        if isinstance(corpo.get("tassa_soggiorno_cents"), int) and corpo["tassa_soggiorno_cents"] > 0:
            righe.append((_T("prev_tassa", lang),
                          self._fmt_importo(corpo["tassa_soggiorno_cents"], v)))
        tot = corpo.get("totale_cents") or corpo.get("prezzo_guest_cents")
        righe.append((_T("prev_totale", lang), self._fmt_importo(tot, v)))
        from urllib.parse import urlencode as _ue
        url = ((self._base_url or "https://bookinvip.com") + "/?" +
               _ue({"apri": slug, "ci": ci, "co": co}))
        html = corpo_preventivo_html(titolo, ci, co, righe, url, lingua=lang)
        oggetto = _oggetto_email("prev_ogg", lang, titolo)
        if not prov.invia(email.strip(), oggetto, html):
            return 502, {"errore": "invio_fallito"}
        mem[chiave] = ora
        storia.setdefault(em, []).append(ora)   # conta verso il tetto orario per indirizzo
        return 200, {"stato": "inviata"}

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
            obj0 = (dati or {}).get("object", {}) or {}
            meta0 = obj0.get("metadata", {}) or {}
            # SCATTO ③ (fase183): sessione di SALVATAGGIO CARTA (mode=setup), NON un pagamento.
            # Riconosciuta dallo scopo nel metadata -> salva customer+payment_method dell'host.
            if obj0.get("mode") == "setup" or meta0.get("scopo") == "mandato_penale_offsession":
                self._carta_salva_da_sessione(obj0)
                return 200, {"ricevuto": True, "tipo": tipo, "scopo": "carta"}
            rif = ""
            try:
                rif = meta0.get("riferimento", "")
            except Exception:
                rif = ""
            # AUDIT CONSOLE: salva l'id sessione (cs_...) -> shadow-check Stripe possibile
            # per sempre su questa prenotazione. ISOLATO: mai bloccare la conferma.
            try:
                cs_id = (dati or {}).get("object", {}).get("id", "")
                # E l'identificativo del PAGAMENTO (pi_...), che viaggia nello stesso evento
                # (Checkout Session in mode=payment): e' l'unico modo di sapere poi QUALE
                # pagamento restituire. Fino al 2026-08-16 non lo salvava nessuno, e il
                # rimborso all'ospite andava eseguito A MANO dal pannello Stripe.
                pi_id = (dati or {}).get("object", {}).get("payment_intent", "")
                pp_ = getattr(self._sys, "pagamenti_pendenti", None)
                if pp_ is not None and rif and hasattr(pp_, "salva_stripe_session"):
                    pp_.salva_stripe_session(rif, cs_id, pi_id)
            except Exception:
                logger.warning("salvataggio cs_ fallito (ISOLATO)", exc_info=True)
            logger.info("Stripe: pagamento CONFERMATO per riferimento '%s'", rif)
            self._conferma_pagamento(rif)
        elif str(tipo).startswith("identity.verification_session."):
            # STRIPE IDENTITY (Incr.11): il webhook porta l'ESITO (mai il documento).
            # ISOLATO: qualunque errore qui non tocca il resto del webhook.
            try:
                obj = (dati or {}).get("object", {}) or {}
                hid = (obj.get("metadata", {}) or {}).get("host_id", "")
                stato_s = str(obj.get("status") or "")
                kyc = getattr(self._sys, "kyc", None)
                if kyc is not None and hid:
                    if stato_s == "verified":
                        kyc.conferma(hid, "verificato")
                        logger.warning("KYC IDENTITY VERIFICATO | HOST_ID: %s (webhook)",
                                       hid)
                    elif stato_s == "canceled":
                        kyc.conferma(hid, "respinto")
            except Exception:
                logger.warning("webhook identity: errore ISOLATO", exc_info=True)
        return 200, {"ricevuto": True, "tipo": tipo}

    # ── SCATTO ③: carta host off-session (fase183) ──────────────────────────
    MANDATO_CARTA = ("Autorizzo BookinVIP ad addebitare su questa carta gli importi che "
                     "risultassi dovere per penali di cancellazione non coperte dai miei "
                     "incassi futuri. Solo debiti certi, con avviso; posso rimuovere la "
                     "carta quando non ho debiti aperti.")

    def _carta_salva_da_sessione(self, obj):
        """Webhook mode=setup completato -> salva gli id opachi (customer + payment_method)
        dell'host. ISOLATO: mai rompere il webhook."""
        try:
            meta = obj.get("metadata", {}) or {}
            hid = meta.get("host_id", "")
            carta = getattr(self._sys, "carta", None)
            reg = getattr(self._sys, "registro_host", None)
            if carta is None or reg is None or not hid:
                return
            det = None
            sid = obj.get("id", "")
            if sid and hasattr(carta, "dettagli_da_sessione"):
                det = carta.dettagli_da_sessione(sid)
            if not det:                       # fallback: gia' nell'evento
                cust, pm = obj.get("customer") or "", obj.get("payment_method") or ""
                det = {"customer": cust, "payment_method": pm} if (cust and pm) else None
            if det and det.get("customer") and det.get("payment_method"):
                reg.imposta_carta(hid, det["customer"], det["payment_method"])
                logger.warning("CARTA HOST SALVATA | HOST_ID: %s (mandato off-session)", hid)
        except Exception:
            logger.warning("salvataggio carta host fallito (ISOLATO)", exc_info=True)

    def _host_carta_link(self, headers):
        """L'host apre la pagina HOSTED per salvare una carta (badge Host Verificato+ e
        rete di sicurezza penali). La carta va da lui a Stripe, MAI da noi."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        carta = getattr(self._sys, "carta", None)
        reg = getattr(self._sys, "registro_host", None)
        if carta is None:
            return 503, {"errore": "carta_non_attiva"}      # Scatto ③ dormiente (no chiave)
        hid = self._host_id_da_token(headers)
        if not hid:
            return 422, {"errore": "host_id_mancante"}
        email = ""
        try:
            email = (reg.info_host(hid) or {}).get("email", "") if reg else ""
        except Exception:
            email = ""
        url = carta.crea_link_carta(host_id=hid, email=email)
        if not url:
            return 502, {"errore": "link_non_creato"}
        return 200, {"url": url, "mandato": self.MANDATO_CARTA}

    def _host_carta_stato(self, headers):
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        hid = self._host_id_da_token(headers)
        reg = getattr(self._sys, "registro_host", None)
        info = {}
        try:
            info = (reg.info_host(hid) or {}) if (reg and hid) else {}
        except Exception:
            info = {}
        # ⛔ NON SI OFFRE UNA GARANZIA CHE NON SI PUO' INCASSARE (2026-08-08, trovato
        # dal fondatore guardando il pannello). Prima bastava che ESISTESSE il provider
        # -- cioe' la chiave Stripe -- e la scheda «Aggiungi carta» compariva; ma
        # l'addebito vero e' gated da SCATTO3_ATTIVO, che in produzione NON e' impostata.
        # Risultato: si chiedeva all'host il numero di una carta che non avremmo potuto
        # addebitare. Ora i due interruttori dicono la stessa cosa. Stessa lettura usata
        # dallo sweep in `riscuoti_debiti_carta`, per non averne due che possono divergere.
        import os as _os
        _addebito_acceso = _os.environ.get("SCATTO3_ATTIVO", "0") == "1"
        return 200, {"carta_collegata": bool(info.get("stripe_payment_method")),
                     "attivo": (getattr(self._sys, "carta", None) is not None
                                and _addebito_acceso)}

    def riscuoti_debiti_carta(self):
        """SWEEP Scatto ③ (gated SCATTO3_ATTIVO): per gli host con debiti 'aperto' scoperti
        E una carta salvata, addebita off-session il residuo. DORMIENTE finche' il fondatore
        non mette SCATTO3_ATTIVO=1 in prod (money-move reale). Isolato/fail-safe."""
        import os as _os
        if _os.environ.get("SCATTO3_ATTIVO", "0") != "1":
            return {"saltato": "non_attivo"}
        fc = getattr(self._sys, "finanza", None)
        carta = getattr(self._sys, "carta", None)
        reg = getattr(self._sys, "registro_host", None)
        if fc is None or carta is None or reg is None:
            return {"saltato": "non_configurato"}
        esito = {"host": 0, "incassati_cents": 0, "saldati": 0}
        try:
            host_con_debiti = {}
            for deb in fc.debiti_aperti():
                hid = str(deb.get("host_id") or "")
                if hid:
                    host_con_debiti[hid] = True
            for hid in host_con_debiti:
                info = reg.info_host(hid) or {}
                cust = info.get("stripe_customer_id", "")
                pm = info.get("stripe_payment_method", "")
                if not (cust and pm):
                    continue                  # niente carta -> resta al just-in-time (email)
                r = fc.riscuoti_da_carta(host_id=hid, provider_carta=carta,
                                         customer=cust, payment_method=pm)
                esito["host"] += 1
                esito["incassati_cents"] += int(r.get("incassati_cents", 0))
                esito["saldati"] += int(r.get("debiti_saldati", 0))
        except Exception:
            logger.warning("sweep carta off-session fallito (ISOLATO)", exc_info=True)
        return esito

    def _riscuoti_carta_se_ora(self):
        """Gancio per il tick orario: sweep carta al massimo 1 volta ogni 12h."""
        import time as _t
        if _t.time() - getattr(self, "_carta_sweep_ts", 0) < 12 * 3600:
            return None
        self._carta_sweep_ts = _t.time()
        return self.riscuoti_debiti_carta()

    def _riasserisci_incasso(self, rec, rif):
        """Passi derivati IDEMPOTENTI del pagamento: tassa nel ledger + payout 'maturato'.
        Sicuri da rieseguire (registra_riscossione e aggiorna_stato('maturato') sono no-op
        se gia' fatti, e rispettano un eventuale tombstone/cancellazione avvenuta nel
        frattempo -> non risuscitano un rimborsato). Chiamati sia sulla PRIMA conferma sia
        sul webhook di RETRY, per SANARE un crash del primo handler a meta' (BUG #32:
        crash dopo il CAS 'pagato' ma prima di questi passi -> tassa persa dal ledger citta'
        + payout bloccato 'in_attesa' per sempre, con Stripe che ritenta a vuoto)."""
        try:
            if isinstance(rec, dict) and rec.get("tassa_cents", 0) > 0:
                led = getattr(self._sys, "tassa_comunale", None)
                if led is not None:
                    led.registra_riscossione(rif, rec.get("comune", ""), rec["tassa_cents"])
            pd = getattr(self._sys, "payout", None)
            if pd is not None:
                pd.aggiorna_stato(rif, "maturato")        # in_attesa -> maturato (guadagno vero)
            # SCATOLA NERA dell'INCASSO (idempotente su evento_id: il retry del webhook non
            # raddoppia). Importo = totale pagato dall'ospite; + riga tassa se dovuta.
            import json as _jg
            try:
                dj = _jg.loads(rec.get("corpo_json") or "{}") if isinstance(rec, dict) else {}
            except Exception:
                dj = {}
            val = dj.get("valuta") or "EUR"
            totale = int(dj.get("totale_cents", 0) or dj.get("prezzo_guest_cents", 0) or 0)
            hid = dj.get("host_id") or (rec.get("host_id") if isinstance(rec, dict) else "") or ""
            if totale > 0:
                self._giornale(tipo="incasso", riferimento=rif, soggetto="host:" + str(hid),
                               importo_cents=totale, valuta=val,
                               causale="pagamento ospite ricevuto")
                # COMMISSIONE NETTA trattenuta all'host, registrata ORA (al pagamento), non al
                # bonifico: comm + costo carta - credito fondatore = cio' che davvero tratteniamo.
                # Cosi' il report DAC7 (netto = lordo - commissione) e' corretto anche se il
                # bonifico e' in HOLD (host reportabile senza dati fiscali / verifica revocata).
                # Idempotente su evento_id: il retry del webhook non la raddoppia.
                _comm = int(dj.get("commissione_cents", 0) or 0)
                _costo = int(dj.get("costo_pagamento_cents", 0) or 0)
                _sconto = int(dj.get("sconto_credito_cents", 0) or 0)
                _comm_netta = _comm + _costo - _sconto
                if _comm_netta > 0:
                    self._giornale(tipo="commissione", riferimento=rif,
                                   soggetto="host:" + str(hid), importo_cents=_comm_netta,
                                   valuta=val, evento_id="commissione:" + str(rif),
                                   causale="commissione piattaforma (comm+costo carta-credito)")
                # ⛔ E QUANTO SI E' PRESO IL GESTORE: la riga che mancava, e senza la quale il
                # libro dichiara di avere in cassa soldi che non ci sono. `incasso` scrive il
                # LORDO; sul conto arriva il NETTO. Misurato sul primo pagamento vero:
                # incasso 100, in cassa 73, e i 27 di differenza non stavano in nessuna riga --
                # finche' il rimborso ha portato il saldo Stripe a **-0,27 EUR** mentre il
                # nostro libro diceva **0** e per giunta un ricavo di 30.
                # ⛔ IL NUMERO SI CHIEDE A CHI LI HA PRESI, non si stima con la nostra tariffa:
                # sono due voci diverse (costo sostenuto contro ricavo). Se Stripe non
                # risponde NON si scrive niente e resta il buco dichiarato -- il prospetto lo
                # conta fra gli «sconosciuti» invece di riempirlo con una cifra inventata.
                self._costo_gateway_dal_gestore(rif, dj, hid, val)
            if isinstance(rec, dict) and int(rec.get("tassa_cents", 0) or 0) > 0:
                self._giornale(tipo="tassa_incassata", riferimento=rif,
                               soggetto="comune:" + str(rec.get("comune", "")),
                               importo_cents=int(rec["tassa_cents"]), valuta=val,
                               causale="tassa di soggiorno trattenuta")
        except Exception:
            logger.warning("riasserisci incasso fallito (ignorato)", exc_info=True)

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
            # ACQUISIZIONE ATOMICA (anti-gara con lo sweeper): `conferma` è un CAS che
            # scrive 'pagato' SOLO da 'in_attesa'/'scaduto' e ritorna lo stato PRECEDENTE.
            # Decidere il ramo su una info() letta prima apriva la finestra: sweeper
            # libera le date tra lettura e scrittura -> pagato senza stanza garantita.
            rec = pp.conferma(rif) if pp is not None else None
            if rec is None:
                logger.warning("pagamento per riferimento sconosciuto '%s' (ignorato)", rif)
                return
            stato = rec.get("stato", "")
            if stato == "pagato":
                # WEBHOOK DUPLICATO/RETRY. NON basta uscire: se il PRIMO handler e' morto
                # DOPO il CAS 'pagato' ma PRIMA dei passi derivati (BUG #32 provato), la tassa
                # non sarebbe mai registrata e il payout resterebbe bloccato 'in_attesa'. Stripe
                # ritenta per giorni: sfrutto il retry per SANARE lo stato ri-asserendo i passi
                # IDEMPOTENTI (tassa + payout maturato). NON ri-eseguo credito/referral (non
                # idempotenti: doppio-apply = perdita); un crash prima di quelli perde solo il
                # bonus di quella prenotazione (degrado minimo vs incoerenza permanente).
                # PAGA IN STRUTTURA: NON ri-asserire! Per l'in-struttura non c'e' NIENTE di
                # derivato (niente tassa nostra, niente payout, niente incasso del totale: online
                # abbiamo preso solo l'anticipo, il saldo+tassa li incassa l'host in loco). Un
                # retry deve essere un NO-OP: senza questa guardia registreremmo il TOTALE come
                # nostro incasso + la tassa che non abbiamo mai incassato (bug provato dal test).
                if not self._rec_in_struttura(rec):
                    self._riasserisci_incasso(rec, rif)
                return
            # WHITELIST: si conferma SOLO 'in_attesa' (hold vivo) o 'scaduto' (re-block sotto).
            # Ogni altro stato (cancellata dal cliente/host, rimborsata, richiesta NON ancora
            # approvata) NON è confermabile (il CAS non ha scritto niente): senza questa
            # guardia un pagamento tardivo su una prenotazione cancellata diventava
            # 'pagato' -> soldi senza stanza + payout indebito.
            if stato not in ("in_attesa", "scaduto"):
                logger.error("RIMBORSARE: pagamento ricevuto per '%s' in stato '%s' (non "
                             "confermabile: prenotazione cancellata/non approvata). Rimborsare "
                             "manualmente dal dashboard Stripe.", rif, stato)
                # SCATOLA NERA DEL RIMBORSO. I soldi sono arrivati per una prenotazione che
                # non si può onorare: vanno restituiti per intero. Senza questa riga il
                # cliente non entra nella lista dei rimborsi dovuti (che nasce dal giornale)
                # e l'unica traccia resta il registro qui sopra — era la sola delle sette
                # strade a non lasciare nemmeno un segno nel database.
                # ⛔ NON si marca il pendente: in stato 'in_attesa_host' le date possono
                # essere ancora bloccate, e portarlo a 'rimborsato' lo toglierebbe allo
                # sweeper lasciandole occupate per sempre. La riga compare lo stesso e
                # dichiara da sé cosa manca perché il pulsante non ci sia.
                try:
                    _dj = json.loads(rec.get("corpo_json") or "{}")
                except Exception:
                    _dj = {}
                self._giornale(tipo="rimborso", riferimento=rif,
                               soggetto="ospite:" + str(rif),
                               importo_cents=int(_dj.get("totale_cents", 0)
                                                 or _dj.get("prezzo_guest_cents", 0) or 0),
                               valuta=_dj.get("valuta") or "EUR",
                               evento_id="rimborso_non_confermabile:" + str(rif),
                               causale="rimborso dovuto: pagamento su prenotazione non "
                                       "confermabile (stato %s)" % stato)
                return
            # PAGA IN STRUTTURA: percorso SEPARATO. L'anticipo e' nostro, il saldo (con la
            # tassa) lo incassa l'host DI PERSONA -> nessuna tassa da registrare, nessun payout
            # da maturare, nessun escrow. Se tardivo, ri-blocca come l'online (anti-gara).
            if self._rec_in_struttura(rec):
                self._conferma_struttura(rec, rif, stato)
                return
            if stato == "scaduto":
                # PAGAMENTO TARDIVO: la stanza era stata liberata. Ri-tento il blocco con
                # una CHIAVE FRESCA ("reblock:<rif>"): riusare la chiave del blocco
                # originale (già rilasciato dallo sweeper) era un REPLAY idempotente ->
                # 'ok' finto SENZA ribloccare davvero = doppia prenotazione possibile.
                inv = getattr(self._sys, "inventario", None)
                idem = "reblock:" + rif
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
                    # SCATOLA NERA DEL RIMBORSO. Senza questa riga il cliente non entra nella
                    # lista dei rimborsi dovuti -- che nasce dal giornale -- e l'unica traccia
                    # resta il registro qui sopra, che qualcuno deve RICORDARSI di leggere: un
                    # registro non è una coda di lavoro. Non ha avuto NIENTE in cambio, quindi
                    # gli spetta tutto il pagato. Idempotente su `evento_id`.
                    try:
                        _dj = json.loads(rec.get("corpo_json") or "{}")
                    except Exception:
                        _dj = {}
                    self._giornale(tipo="rimborso", riferimento=rif,
                                   soggetto="ospite:" + str(rif),
                                   importo_cents=int(_dj.get("totale_cents", 0)
                                                     or _dj.get("prezzo_guest_cents", 0) or 0),
                                   valuta=_dj.get("valuta") or "EUR",
                                   evento_id="rimborso_tardivo:" + str(rif),
                                   causale="rimborso dovuto: pagamento tardivo su stanza presa")
                    return
                # ri-bloccata con successo: i flussi futuri (cancellazione/rimborso) devono
                # accoppiarsi al blocco ATTIVO -> registro la chiave fresca sul record.
                try:
                    pp.aggiorna_idem(rif, idem)
                except Exception:
                    logger.warning("aggiorna_idem post-reblock fallito (ignorato)",
                                   exc_info=True)
                # ricreo payout maturato + garanzia dai dati salvati
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
            # comune a 'in_attesa' e 'scaduto-ribloccato': 'pagato' è GIÀ scritto dal CAS
            # in cima (acquisizione atomica); qui restano tassa + payout maturato (idempotenti,
            # ri-asseriti anche sul retry per sanare un crash del primo handler - BUG #32).
            self._riasserisci_incasso(rec, rif)
            self._email_pagamento_confermato(rec)      # C3: conferma col link voucher
            pd = getattr(self._sys, "payout", None)
            # REFERRAL: se l'host di questa prenotazione è stato INVITATO e raggiunge la soglia
            # di prenotazioni pagate -> premia il referente (una volta sola, mai in perdita).
            hid_pag = rec.get("host_id") if isinstance(rec, dict) else None
            # scala il credito referral dell'host sulla commissione di questa prenotazione
            try:
                import json as _jc
                dj = _jc.loads(rec.get("corpo_json") or "{}") if isinstance(rec, dict) else {}
            except Exception:
                dj = {}
            self._applica_credito_host(rif, hid_pag, dj.get("commissione_cents", 0))
            self._forse_qualifica_referral(hid_pag, pd)
        except Exception:
            logger.warning("conferma pagamento/ledger tassa fallita (ignorata)", exc_info=True)

    def _rec_in_struttura(self, rec):
        """True se la prenotazione pendente e' 'paga in struttura' (letto dal corpo_json che
        _registra_hold ha salvato). Isolato: dubbio -> False (percorso online standard)."""
        try:
            import json as _j
            dj = _j.loads(rec.get("corpo_json") or "{}") if isinstance(rec, dict) else {}
            return dj.get("modo_pagamento") == "in_struttura"
        except Exception:
            return False

    def _conferma_struttura(self, rec, rif, stato):
        """FASE 2 - conferma di un ANTICIPO 'paga in struttura'. L'anticipo (commissione+fee+
        gateway) e' interamente NOSTRO; il saldo, tassa inclusa, lo incassa l'host DI PERSONA ->
        NIENTE tassa da registrare, NIENTE payout da maturare, NIENTE escrow. 'pagato' e' gia'
        scritto dal CAS a monte. Se il pagamento e' TARDIVO (hold scaduto) ri-blocca la stanza
        con chiave fresca (stessa anti-gara dell'online); se e' gia' presa -> segnala rimborso.
        La carta e' salvata su Stripe (cs_ gia' registrato dal webhook) -> la penale no-show
        (FASE 3) recuperera' customer+payment_method da li'."""
        if stato == "scaduto":
            inv = getattr(self._sys, "inventario", None)
            idem = "reblock:" + rif
            esito = None
            try:
                esito = inv.blocca(rec["alloggio_id"], rec["check_in"], rec["check_out"],
                                   idem_key=idem, origine="anticipo_tardivo") if inv else None
            except Exception:
                esito = None
            if not getattr(esito, "ok", False):
                logger.error("RIMBORSARE anticipo: pagamento tardivo su stanza gia' presa - "
                             "rif '%s' (alloggio %s %s->%s). Rimborsare l'anticipo.",
                             rif, rec.get("alloggio_id"), rec.get("check_in"), rec.get("check_out"))
                try:
                    pp = getattr(self._sys, "pagamenti_pendenti", None)
                    if pp is not None:
                        pp.marca_da_rimborsare(rif)
                except Exception:
                    pass
                # SCATOLA NERA DEL RIMBORSO. ⛔ L'importo è l'ANTICIPO, non il totale: online
                # è arrivato solo quello, il saldo lo avrebbe incassato l'host di persona.
                # Restituire il totale renderebbe denaro mai ricevuto — una perdita nostra su
                # un disguido che non è colpa di nessuno. Idempotente su `evento_id`.
                try:
                    _dj = json.loads(rec.get("corpo_json") or "{}")
                except Exception:
                    _dj = {}
                self._giornale(tipo="rimborso", riferimento=rif,
                               soggetto="ospite:" + str(rif),
                               importo_cents=int(_dj.get("anticipo_online_cents", 0) or 0),
                               valuta=_dj.get("valuta") or "EUR",
                               evento_id="rimborso_anticipo_tardivo:" + str(rif),
                               causale="rimborso dovuto: anticipo su stanza già presa")
                return
            try:
                pp = getattr(self._sys, "pagamenti_pendenti", None)
                if pp is not None:
                    pp.aggiorna_idem(rif, idem)
            except Exception:
                logger.warning("aggiorna_idem post-reblock (struttura) fallito (ignorato)",
                               exc_info=True)
        # niente tassa/payout/garanzia: il saldo (tassa inclusa) lo gestisce l'host in loco.
        self._email_pagamento_confermato(rec)

    def _applica_credito_host(self, ref, host_id, commissione_cents):
        """Scala il credito referral dell'host sulla commissione di questa prenotazione:
        meno commissione paga l'host -> più incassa. Il credito è non-cashabile, si consuma qui.
        Ritorna quanti cent sono stati scalati."""
        try:
            viral = getattr(self._sys, "viral", None)
            pd = getattr(self._sys, "payout", None)
            if viral is None or pd is None or not (isinstance(host_id, str) and host_id):
                return 0
            comm = commissione_cents if isinstance(commissione_cents, int) and \
                not isinstance(commissione_cents, bool) and commissione_cents > 0 else 0
            if comm <= 0:
                return 0
            res = viral.usa_credito(host_id, comm)   # <- QUI il credito e' gia' COMMITTATO
            used = int(res.get("scontato_cents", 0)) if isinstance(res, dict) else 0
            if used > 0:
                try:
                    # ATTENZIONE al valore di ritorno: `aumenta_payout` fa un UPDATE e torna
                    # False (SENZA sollevare) se non esiste una riga payout per questa
                    # prenotazione -> il credito sarebbe gia' bruciato e l'aumento mai
                    # avvenuto, in SILENZIO. E' il caso piu' probabile: la riga la crea un
                    # passo precedente che a sua volta e' isolato. Trovato dal QUINTO LIBRO
                    # (riconciliazione credito<->payout) il 2026-07-31.
                    if not pd.aumenta_payout(ref, used):
                        raise RuntimeError("aumenta_payout non ha aggiornato nessuna riga "
                                           "(payout inesistente per %s)" % ref)
                except Exception:
                    # I due passi NON sono atomici: il credito e' gia' stato bruciato sopra.
                    # Se fallisce qui, l'host paga la commissione PIENA e ha perso il credito
                    # che si era guadagnato portando un altro host: a rimetterci e' LUI.
                    # Invertire l'ordine non salva (fallendo il consumo terrebbe sconto E
                    # credito: ci rimetteremmo noi). Serve una compensazione che RESTITUISCA
                    # il credito -> registrata come candidato. Qui si rende RIPARABILE A MANO:
                    # servono l'host e i centesimi esatti.
                    logger.error("CREDITO REFERRAL PERSO: host %s, %d cent gia' scalati dal suo "
                                 "credito ma NON applicati alla commissione di %s -> "
                                 "restituirglieli a mano", host_id, used, ref, exc_info=True)
                    return 0
                logger.info("Credito referral scalato: host %s -%d di commissione su %s",
                            host_id, used, ref)
            return used
        except Exception:
            logger.error("APPLICAZIONE CREDITO HOST FALLITA per %s su %s: l'host potrebbe non "
                         "aver ricevuto lo sconto che gli spetta", host_id, ref, exc_info=True)
            return 0

    def _forse_qualifica_referral(self, host_id, pd):
        """Alla N-esima prenotazione pagata dell'invitato, premia chi l'ha invitato."""
        try:
            viral = getattr(self._sys, "viral", None)
            cfg = getattr(self._sys, "config", None)
            if viral is None or pd is None or cfg is None or not (isinstance(host_id, str) and host_id):
                return
            soglia = getattr(cfg, "referral_soglia_prenotazioni", 3)
            premio = getattr(cfg, "referral_premio_cents", 4000)
            # scatta DALLA soglia in poi (>=): il "una volta sola" lo garantisce lo store
            # (qualifica_referee: BEGIN IMMEDIATE + dedup 'gia_qualificato'), non il
            # confronto. Con '==' esatto, due webhook CONCORRENTI (3a e 4a prenotazione
            # pagate insieme) contavano entrambi 4 -> il premio al referente non scattava
            # MAI piu' (finestra persa per sempre). '>= ' recupera al pagamento successivo.
            if pd.conta_pagati(host_id) >= max(1, int(soglia)):
                out = viral.qualifica_referee(host_id, premio_cents=int(premio))
                if out.get("ok"):
                    logger.info("Referral qualificato: host %s ha raggiunto %d prenotazioni -> "
                                "premio %d al referente %s", host_id, soglia, premio,
                                out.get("referente_id"))
        except Exception:
            # Ha un recupero (il `>=` fa riprovare a ogni pagamento successivo), ma un guasto
            # PERSISTENTE lascerebbe il referente senza il premio promesso, in silenzio.
            logger.error("PREMIO REFERRAL non assegnato per l'invitato %s: chi l'ha portato "
                         "non ha ricevuto il premio (si riprova al prossimo pagamento)",
                         host_id, exc_info=True)

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

    def _documento_legale(self, query):
        """Serve TERMINI e PRIVACY nella lingua chiesta, con versione e impronta.

        Il modulo `fase185` esisteva gia' completo, ma NON era collegato a nulla: le
        pagine pubbliche restavano quelle statiche in italiano. Il fondatore se n'e'
        accorto da solo — «clicco termini e lo leggo solo italiano» — ed e' il modo di
        rompersi n.2 della regola dei collaudi: **il pezzo e' perfetto e non e'
        collegato**. Questa rotta e' l'anello mancante.

        Restituisce anche `lingue` (quelle REALMENTE fornite, non quelle dichiarate) e
        `lingua_che_fa_fede`, perche' in caso di divergenza il testo italiano prevale e
        l'utente ha diritto di saperlo.
        """
        try:
            from fase185_testi_legali import documento
            nome = str((query or {}).get("doc") or "termini").strip().lower()
            if nome not in ("termini", "privacy"):
                return 400, {"errore": "documento_sconosciuto"}
            return 200, documento(nome, _lingua(query))
        except Exception:
            logger.error("documento legale: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}

    def _contratto_host(self, query):
        """Serve il testo VIVO del contratto host + versione + hash vincolante (per l'accettazione)."""
        try:
            from fase163_accettazioni import documento_corrente
            return 200, documento_corrente(_lingua(query))
        except Exception:
            logger.error("contratto host: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}

    def _registra_consensi(self, acc, host_id, lang, headers):
        """Scrive le DUE prove firmate: (1) contratto host CON approvazione specifica delle
        clausole vessatorie ex artt. 1341-1342 c.c., (2) informativa privacy/GDPR come
        documento SEPARATO (consenso specifico). Ogni riga porta versione + impronta del
        testo + IP + dispositivo + data/ora, sigillata con HMAC-SHA256."""
        from fase163_accettazioni import (DOCUMENTO_PRIVACY, PRIVACY_VERSIONE,
                                          privacy_sha256)
        ip = self._client_ip(headers)
        ua = self._user_agent(headers)
        r1 = acc.registra(host_id, lang=lang, ip=ip, user_agent=ua, vessatorie=True)
        r2 = acc.registra(host_id, documento=DOCUMENTO_PRIVACY, versione=PRIVACY_VERSIONE,
                          doc_sha256_=privacy_sha256(), lang=lang, ip=ip, user_agent=ua)
        if not (r1.get("ok") and r2.get("ok")):
            logger.error("PROVA consensi INCOMPLETA per host %s (contratto=%s privacy=%s)",
                         host_id, r1.get("ok"), r2.get("ok"))
        out = {"registrata": bool(r1.get("ok")), "versione": r1.get("versione"),
               "vessatorie": bool(r1.get("vessatorie")),
               "privacy_registrata": bool(r2.get("ok")),
               "privacy_versione": r2.get("versione")}
        # LEGAME IDENTITA' (se l'host si e' gia' verificato): trasforma "qualcuno da questo
        # IP" in "la persona con documento verificato da Stripe". Isolato: mai bloccante.
        out["identita_legata"] = self._lega_identita_se_possibile(acc, host_id, ip, ua, lang)
        return out

    def _lega_identita_se_possibile(self, acc, host_id, ip="", ua="", lang="it"):
        """Scrive il legame identita↔contratto SE esiste una sessione di verifica.
        Chiamato alla firma e di nuovo quando la verifica si completa DOPO (webhook), cosi'
        anche chi firma prima di verificarsi finisce per avere la prova completa."""
        try:
            kyc = getattr(self._sys, "kyc", None)
            if kyc is None or acc is None:
                return False
            info = kyc.riferimento(host_id) or {}
            ref = info.get("session_ref") or ""
            if not ref:
                return False
            r = acc.lega_identita(host_id, ref, info.get("stato", ""),
                                  ip=ip, user_agent=ua, lang=lang)
            return bool(r.get("ok"))
        except Exception:
            logger.warning("legame identita-contratto fallito (ISOLATO)", exc_info=True)
            return False

    def _host_contratto_stato(self, headers):
        """Serve alla schermata di RI-ACCETTAZIONE: dice se l'host e' in regola con la
        versione CORRENTE del contratto, con le clausole vessatorie e con la privacy."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        acc = getattr(self._sys, "accettazioni", None)
        host_id = self._host_id_da_token(headers)
        if acc is None or not (isinstance(host_id, str) and host_id):
            return 200, {"deve_riaccettare": False}
        try:
            from fase163_accettazioni import doc_sha256 as _dh, privacy_sha256 as _ph
            st = acc.stato_consensi(host_id)
            st["doc_sha256"] = _dh()
            st["privacy_sha256"] = _ph()
            return 200, st
        except Exception:
            logger.error("stato consensi: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}

    def _host_riaccetta(self, body, headers):
        """RI-ACCETTAZIONE del contratto aggiornato (art. 13): richiede di nuovo TUTTE E TRE
        le spunte e scrive prove NUOVE e firmate (le vecchie restano: registro append-only,
        si prova cosa era in vigore quando). Rifiuta a monte se ne manca una."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        acc = getattr(self._sys, "accettazioni", None)
        host_id = self._host_id_da_token(headers)
        if acc is None or not (isinstance(host_id, str) and host_id):
            return 422, {"errore": "host_id_mancante"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        mancanti = [k for k, v in (("accetta_termini", dati.get("accetta_termini")),
                                   ("accetta_clausole", dati.get("accetta_clausole")),
                                   ("accetta_privacy", dati.get("accetta_privacy")))
                    if not bool(v)]
        if mancanti:
            return 422, {"errore": "consensi_mancanti", "mancanti": mancanti}
        try:
            from fase163_accettazioni import CONTRATTO_HOST_VERSIONE as _v, doc_sha256 as _dh
            hc = dati.get("doc_sha256")
            if isinstance(hc, str) and hc and hc != _dh():
                return 409, {"errore": "contratto_aggiornato", "doc_sha256": _dh(),
                             "versione": _v}
            out = self._registra_consensi(acc, host_id, str(dati.get("lang", "it")), headers)
            logger.info("RI-ACCETTAZIONE | HOST_ID: %s | VERSIONE: %s", host_id, _v)
            return 200, {"ok": bool(out.get("registrata")), "accettazione": out}
        except Exception:
            logger.error("ri-accettazione: eccezione ISOLATA", exc_info=True)
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

    def _host_password_dimenticata(self, body):
        """PASSWORD DIMENTICATA (C2 2026-07-20 — prima: lock-out ETERNO, nessun reset).
        Risponde SEMPRE 200 (anti-enumerazione: mai rivelare se un'email esiste). Se
        esiste: magic-link firmato 30 min single-use via email, nel FRAGMENT dell'url
        (#reset=... non finisce nei log del server). Throttle 60s per email."""
        reg = getattr(self._sys, "registro_host", None)
        dati = self._json(body)
        if reg is None or dati is None:
            return 200, {"ok": True}
        email = dati.get("email")
        try:
            import time as _t
            if not hasattr(self, "_pw_reset_ts"):
                self._pw_reset_ts = {}
            k = str(email or "").strip().lower()
            if k and _t.time() - self._pw_reset_ts.get(k, 0) < 60:
                return 200, {"ok": True}            # troppo presto: niente seconda email
            tok = reg.token_reset_password(email)
            if tok and getattr(self._sys, "email_provider", None) is not None:
                self._pw_reset_ts[k] = _t.time()
                from fase86_email import corpo_reset_password_html, oggetto
                lang = dati.get("lang", "en")     # l'host e' sulla pagina: lingua corrente
                # Il link porta al GATE PUBBLICO (/entra-host), NON a /host.html che è gated
                # (302 senza sessione -> il reset non partiva mai: chi resetta è sempre sloggato).
                # Il token resta nel FRAGMENT (#) -> mai nei log del server. Il gate lo gestisce.
                link = ((self._base_url or "https://bookinvip.com")
                        + "/entra-host#reset=" + tok)
                import threading
                threading.Thread(target=self._sys.email_provider.invia,
                                 args=(k, oggetto("rp_ogg", lang),
                                       corpo_reset_password_html(link, lingua=lang)),
                                 daemon=True).start()
        except Exception:
            logger.warning("password dimenticata: invio fallito (ISOLATO)", exc_info=True)
        return 200, {"ok": True}

    def _host_password_reset(self, body):
        """Applica il magic-link: nuova password + accesso immediato (token+cookie)."""
        reg = getattr(self._sys, "registro_host", None)
        if reg is None:
            return 503, {"errore": "registrazione_non_attiva"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        e = reg.reset_password(dati.get("token"), dati.get("password"))
        corpo = e.as_dict()
        if e.ok:
            ttl = self._GATE_TTL["host"]
            corpo = dict(corpo)
            corpo["_cookie"] = [("bv_host", self._gate_firma("host", ttl), ttl)]
        return (200 if e.ok else 400), corpo

    def _host_cambia_password(self, body, headers):
        """Rotazione volontaria della password (host loggato col suo token)."""
        reg = getattr(self._sys, "registro_host", None)
        if reg is None:
            return 503, {"errore": "registrazione_non_attiva"}
        hid = self._host_id_da_token(headers)
        if not hid:
            return 401, {"errore": "unauthorized"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        e = reg.cambia_password(hid, dati.get("vecchia"), dati.get("nuova"))
        return (200 if e.ok else 400), e.as_dict()

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
        # LE 3 SPUNTE SONO OBBLIGATORIE **A MONTE** (2026-07-20): prima solo i Termini
        # bloccavano lato server e le clausole vessatorie erano controllate SOLO dal
        # browser -> una chiamata via API creava un account con `vessatorie=0`, cioe' con
        # trattenute/penali/foro NON opponibili. Ora l'account non nasce affatto: niente
        # account senza le tre prove (contratto, art. 1341-1342 c.c., privacy GDPR).
        mancanti = [k for k, v in (("accetta_termini", dati.get("accetta_termini")),
                                   ("accetta_clausole", dati.get("accetta_clausole")),
                                   ("accetta_privacy", dati.get("accetta_privacy")))
                    if not bool(v)]
        if mancanti:
            return 422, {"errore": "consensi_mancanti", "mancanti": mancanti}
        # CANALI OPZIONALI (Line/WeChat) compilati male -> errore CHIARO sul campo, e la
        # registrazione NON passa dal rate limiter del login: sbagliare un campo opzionale
        # non deve MAI consumare i tentativi d'accesso ne' far scattare 'troppi_tentativi'.
        errore_canali = _valida_canali_opzionali(dati)
        if errore_canali is not None:
            return errore_canali
        e = reg.registra(dati.get("email"), dati.get("password"),
                         accetta_termini=bool(dati.get("accetta_termini")),
                         ragione_sociale=str(dati.get("ragione_sociale", "")),
                         telefono=str(dati.get("telefono", "")),
                         line_token=str(dati.get("line_token", "")),
                         wechat_webhook=str(dati.get("wechat_webhook", "")))
        out = e.as_dict()
        # EMAIL DI BENVENUTO (C2 2026-07-20): conferma che l'account esiste e fa emergere
        # SUBITO un refuso nell'email (se non arriva, l'indirizzo e' sbagliato: meglio
        # accorgersene ORA che al primo reset password). Best-effort in background.
        if e.ok and getattr(self._sys, "email_provider", None) is not None:
            try:
                from fase86_email import corpo_benvenuto_host_html, oggetto
                lang = dati.get("lang", "en")     # lingua scelta in fase di registrazione
                import threading
                threading.Thread(
                    target=self._sys.email_provider.invia,
                    args=(str(dati.get("email", "")).strip().lower(),
                          oggetto("b_ogg", lang),
                          corpo_benvenuto_host_html(
                              (self._base_url or "https://bookinvip.com") + "/host.html",
                              lingua=lang)),
                    daemon=True).start()
            except Exception:
                logger.warning("email benvenuto host fallita (ignorata)", exc_info=True)
        # PROVA D'ACCETTAZIONE firmata (best-effort MA loggata: l'account e' gia' creato con
        # versione+ts nel registro host; qui aggiungiamo la prova forte hash+IP+dispositivo).
        if e.ok:
            acc = getattr(self._sys, "accettazioni", None)
            if acc is not None:
                try:
                    out["accettazione"] = self._registra_consensi(
                        acc, e.host_id, str(dati.get("lang", "it")), headers)
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

    def _host_login(self, body, headers=None):
        reg = getattr(self._sys, "registro_host", None)
        if reg is None:
            return 503, {"errore": "registrazione_non_attiva"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        email = dati.get("email")
        ip = self._client_ip(headers)
        k = self._rate_chiave_login(headers)
        # BUTTAFUORI: se questo IP e' gia' in lockout, rifiuta PRIMA di verificare la
        # password (429). AUDIT: ogni blocco su app.log (persistente) con l'email presa di
        # mira, per sapere se qualcuno sta forzando e quale account.
        if self._rate is not None and k:
            consentito, attesa = self._rate.consenti(k)
            if not consentito:
                logger.warning("RATE-LIMIT login BLOCCATO 429: ip=%s email=%r attesa=%ds",
                               ip, str(email)[:120], attesa)
                return 429, {"errore": "troppi_tentativi", "riprova_tra_sec": attesa}
        e = reg.login(email, dati.get("password"))
        if self._rate is not None and k:
            if e.ok:
                self._rate.riuscito(k)              # login riuscito: azzera (mai penalizzare il vero)
            else:
                bloccato, attesa = self._rate.fallito(k)
                if bloccato:
                    logger.warning("RATE-LIMIT login: SOGLIA superata, lockout %ds ip=%s "
                                   "email=%r", attesa, ip, str(email)[:120])
        corpo = e.as_dict()
        if e.ok:                                    # gatekeeper: emette il cookie di pagina host
            ttl = self._GATE_TTL["host"]
            corpo = dict(corpo)
            corpo["_cookie"] = [("bv_host", self._gate_firma("host", ttl), ttl)]
        return (200 if e.ok else 401), corpo

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

    def _alloggio_ha_prenotazioni(self, slug) -> bool:
        """Vero se sull'alloggio e' MAI stata fatta una prenotazione (anche rimborsata):
        le sue prove — voucher, contratto, registro incassi — sono nella valuta di allora,
        quindi quella valuta e' ormai storia e non si cambia. Fail-SAFE: se non si riesce a
        controllare, si risponde True (meglio rifiutare un cambio valuta che permetterlo
        alla cieca sopra delle prove gia' scritte)."""
        try:
            inv = getattr(self._sys, "inventario", None)
            if inv is None or not hasattr(inv, "elenco_prenotazioni"):
                return True
            return len(inv.elenco_prenotazioni(alloggio_id=slug, limit=1) or []) > 0
        except Exception:
            logger.warning("controllo prenotazioni alloggio fallito (ISOLATO)", exc_info=True)
            return True

    def _blinda_valuta(self, dati):
        """Protegge la valuta di un annuncio ESISTENTE. Ritorna (errore|None, dati).

        · campo valuta OMESSO su un annuncio che esiste -> si tiene la SUA valuta (mai il
          reset silenzioso a EUR);
        · cambio di valuta chiesto quando esistono gia' prenotazioni -> 409 rifiutato.
        Su un annuncio nuovo non fa nulla (la valuta nuova e' libera)."""
        slug = dati.get("slug")
        if not (isinstance(slug, str) and slug):
            return None, dati
        try:
            esistente = self._sys.catalogo.dettaglio(slug)
        except Exception:
            esistente = None
        if not (isinstance(esistente, dict) and esistente.get("valuta")):
            return None, dati                      # annuncio nuovo: valuta libera
        attuale = str(esistente["valuta"]).strip().upper()
        chiesta = dati.get("valuta")
        if not (isinstance(chiesta, str) and chiesta.strip()):
            dati = dict(dati)
            dati["valuta"] = attuale               # OMESSA -> tieni la sua, non EUR
            return None, dati
        if chiesta.strip().upper() != attuale and self._alloggio_ha_prenotazioni(slug):
            return (409, {"errore": "valuta_bloccata", "attuale": attuale,
                          "messaggio": "La valuta non si puo' cambiare: esistono gia' "
                                       "prenotazioni in %s, e i loro voucher e contratti "
                                       "sono in quella moneta." % attuale}), dati
        return None, dati

    def _blinda_stato(self, dati):
        """Protegge lo STATO (bozza/sospeso/pubblicato) di un annuncio ESISTENTE quando il
        corpo NON lo dichiara: si tiene il SUO, mai il default "pubblicato".

        Difetto PROVATO (2026-07-28, happy-path host): il pannello pre-riempie il form da
        /api/host/alloggio e ri-salva su /api/host/pubblica SENZA il campo `stato`;
        `valida_scheda` ricadeva sul default 'pubblicato', quindi un annuncio che l'host
        aveva SOSPESO (o lasciato in bozza) tornava ONLINE e PRENOTABILE al primo ritocco
        di prezzo/foto/titolo — una scelta dell'host distrutta da un salvataggio di
        routine, con il rischio di ricevere prenotazioni per una casa tolta apposta dalla
        vetrina. Stessa classe (e stessa forma) del reset silenzioso della valuta.
        Cambiare stato resta possibile, ma solo DICHIARANDOLO (/api/host/stato, oppure
        `stato` esplicito nel corpo). Su un annuncio nuovo non fa nulla."""
        slug = dati.get("slug")
        if not (isinstance(slug, str) and slug):
            return dati
        chiesto = dati.get("stato")
        if isinstance(chiesto, str) and chiesto.strip():
            return dati                            # stato dichiarato: comanda il chiamante
        try:
            # dettaglio_owner (non `dettaglio`): vede l'annuncio in QUALSIASI stato — un
            # sospeso/bozza dal dettaglio pubblico non si vedrebbe affatto.
            esistente = self._sys.catalogo.dettaglio_owner(slug)
        except Exception:
            esistente = None
        attuale = esistente.get("stato") if isinstance(esistente, dict) else None
        if isinstance(attuale, str) and attuale.strip():
            dati = dict(dati)
            dati["stato"] = attuale
        return dati

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
        # AUTO-ID: l'host NON deve inventarsi uno slug. Se non lo fornisce (nuovo alloggio),
        # lo generiamo noi dal titolo/città, numerato e UNIVOCO -> zero errori/collisioni.
        if not (isinstance(dati.get("slug"), str) and dati.get("slug").strip()):
            dati = dict(dati)
            dati["slug"] = self._slug_unico(dati.get("titolo"), dati.get("citta"))
        # SICUREZZA: la pubblicazione è un UPSERT per slug che RIASSEGNA host_id. In modalità
        # self-service (token) impedisci di pubblicare su uno slug ALTRUI (furto di annuncio).
        # slug nuovo/auto -> proprietario None -> consentito; slug proprio -> aggiorna.
        if not self._verifica_proprieta(headers, dati.get("slug")):
            return 403, {"errore": "non_tuo"}
        dati = self._geocodifica_se_serve(dati)   # coordinate dalla città (per la mappa)
        # VALUTA: su un annuncio GIA' ESISTENTE non si azzera e non si cambia alla leggera.
        # Due difetti dell'audit del 2026-07-22:
        #   1) se il form non manda la valuta, `da_dict` la metteva a EUR "per difetto" ->
        #      un annuncio in yen tornava in euro in silenzio a ogni modifica;
        #   2) cambiare la valuta quando esistono gia' delle prenotazioni renderebbe
        #      l'annuncio (JPY) diverso dal voucher/contratto/registro di quelle
        #      prenotazioni (EUR): lo stesso soggiorno raccontato in due monete.
        errore_valuta, dati = self._blinda_valuta(dati)
        if errore_valuta is not None:
            return errore_valuta
        # STATO: campo OMESSO su un annuncio ESISTENTE -> si tiene il SUO (mai il default
        # "pubblicato"): un salvataggio di routine non ri-mette MAI in vetrina cio' che
        # l'host aveva sospeso. Vedi _blinda_stato.
        dati = self._blinda_stato(dati)
        from fase57_vetrina import Immagine, SchedaAlloggio, valida_scheda
        ok, codice, scheda = valida_scheda(dati)
        if not ok:
            return 422, {"errore": "scheda_non_valida", "dettaglio": codice}
        # CIN OBBLIGATORIO per gli annunci ITALIANI (Reg. UE 2024/1028 + DL 145/2023,
        # vincolante per le piattaforme dal 20/05/2026: raccogliere ED esporre il codice,
        # multe 500-5.000EUR per annuncio senza). Policy del marketplace, il motore fase57
        # resta neutro. Vale solo per stato 'pubblicato': la bozza si puo' salvare.
        if (scheda.stato == "pubblicato" and not scheda.cin
                and scheda.paese.strip().upper() in ("IT", "ITA", "ITALIA", "ITALY")):
            return 422, {"errore": "cin_obbligatorio_italia"}
        # SOLO una vera lista: `get("immagini", [])` difende dalla chiave MANCANTE ma non
        # da un valore avvelenato (None/numero/bool -> enumerate esplodeva in 500; una
        # STRINGA veniva iterata carattere per carattere = immagini-spazzatura). BUG
        # provato dal collaudo punto 3 (input non validi su ogni casella).
        raw_imgs = dati.get("immagini")
        if not isinstance(raw_imgs, (list, tuple)):
            raw_imgs = []
        imgs = [Immagine(u, i) for i, u in enumerate(raw_imgs)
                if isinstance(u, str)]
        id_num = self._sys.catalogo.pubblica(scheda, imgs)
        # ANTI-RICICLO DELLA PROMOZIONE (buco MISURATO e chiuso il 2026-08-09). Il CIN lo
        # rilascia lo Stato: non si cambia con un'email nuova. Alla registrazione non
        # esiste ancora — li' si possono confrontare solo email e telefono (fase88:334) —
        # quindi il confronto con le impronte si rifa' QUI, la prima volta che quel codice
        # entra nel sistema. Senza questa riga bastava cancellarsi e tornare con contatti
        # nuovi sulla STESSA casa per riprendersi 90 giorni a commissione zero.
        # ISOLATO (un guasto non deve impedire di pubblicare) ma ERROR, non warning:
        # se tace, la piattaforma regala la commissione e non lo sa nessuno.
        try:
            _reg_ar = getattr(self._sys, "registro_host", None)
            _prop = hid or self._sys.catalogo.host_di_alloggio(scheda.slug)
            if _reg_ar is not None and _prop and scheda.cin:
                if _reg_ar.riconosci_ritorno(_prop, (scheda.cin,)):
                    logger.info("ANTI-RICICLO: host %s riconosciuto sulla struttura %s: "
                                "anzianita' riportata alla PRIMA iscrizione", _prop, scheda.slug)
        except Exception:
            logger.error("ANTI-RICICLO: rilettura impronte FALLITA sull'annuncio %r: una "
                         "ri-iscrizione sulla stessa struttura puo' aver riciclato la "
                         "promozione", scheda.slug, exc_info=True)
        # MOTORE SEO AUTONOMO (fase173): appena l'host pubblica, il motore valuta la pagina
        # e (se IndexNow e' acceso) avvisa i motori. ISOLATO: mai rompe la pubblicazione.
        try:
            det = self._sys.catalogo.dettaglio(scheda.slug)
            if det is not None:
                self._motore_seo().su_pubblicazione(det, self._base_url)
        except Exception:
            logger.warning("motore SEO su publish fallito (ISOLATO)", exc_info=True)
        # COLD-START: primo annuncio nella citta -> avvisa la lista d'attesa (fase158). ISOLATO.
        try:
            if getattr(scheda, "stato", "") == "pubblicato":
                # citta GREZZA (come l'ha digitata l'host / come il catalogo la memorizza): la
                # ricerca del catalogo e' case-sensitive, mentre email_citta normalizza da sola.
                self._avvisa_domanda_ospiti(dati.get("citta", "") or getattr(scheda, "citta", ""),
                                            scheda.slug)
        except Exception:
            logger.warning("avviso domanda ospiti su publish fallito (ISOLATO)", exc_info=True)
        return 201, {"stato": "pubblicato", "slug": scheda.slug, "id": id_num}

    def _motore_seo(self):
        """Motore SEO (fase173) costruito pigramente dai componenti del sistema."""
        if getattr(self, "_motore_seo_cache", None) is None:
            from fase173_motore_seo import crea_motore_da_sistema
            self._motore_seo_cache = crea_motore_da_sistema(self._sys)
        return self._motore_seo_cache

    def _host_seo_report(self, query, headers):
        """Rapporto SEO/AEO dell'annuncio per il PANNELLO host: punteggio, query
        vincibili, cosa migliorare (gap azionabili). Solo il proprietario."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        slug = query.get("alloggio_id", "")
        if not (isinstance(slug, str) and slug):
            return 422, {"errore": "campi_non_validi"}
        if not self._verifica_proprieta(headers, slug):
            return 403, {"errore": "non_tuo"}
        try:
            det = self._sys.catalogo.dettaglio_owner(slug)
        except Exception:
            det = None
        if det is None:
            return 404, {"errore": "alloggio_non_trovato"}
        from fase173_motore_seo import rapporto_host
        return 200, rapporto_host(self._motore_seo().valuta(det))

    def _distanza_centro(self, citta, lat_u, lon_u, memo=None):
        """Metri (int) dall'annuncio al CENTRO della sua città — in automatico (geocoder
        cache-first + haversine fase121). None se coordinate/centro mancanti. Isolato."""
        try:
            gc = getattr(self._sys, "geocoder", None)
            if gc is None or not (isinstance(citta, str) and citta.strip()):
                return None
            if not (isinstance(lat_u, int) and isinstance(lon_u, int)):
                return None
            chiave = citta.strip().lower()
            if memo is not None and chiave in memo:
                centro = memo[chiave]
            else:
                centro = gc.geocodifica(citta)
                if memo is not None:
                    memo[chiave] = centro
            if not centro:
                return None
            from fase121_geo_ricerca import distanza_m
            d = distanza_m(lat_u, lon_u, centro[0], centro[1])
            return d if isinstance(d, int) and d >= 0 else None
        except Exception:
            return None

    def _geocodifica_se_serve(self, dati):
        """Se l'annuncio non ha coordinate, le ricava dalla CITTÀ (best-effort, isolato) così
        compare sulla mappa. L'host non digita MAI coordinate. Cache-first (fase166): la prima
        volta per una città chiama Nominatim, poi è istantaneo."""
        try:
            gc = getattr(self._sys, "geocoder", None)
            if gc is None or not isinstance(dati, dict):
                return dati
            def _ok(x):
                return isinstance(x, int) and not isinstance(x, bool)
            citta = dati.get("citta")
            indir = str(dati.get("indirizzo", "") or "").strip()
            ha_coord = _ok(dati.get("lat_micro")) and _ok(dati.get("lon_micro"))
            # PIN MANUALE: l'host ha trascinato il segnaposto sulla mappa -> la sua
            # scelta VINCE su città e indirizzo (è la dichiarazione più esplicita).
            # Guardia anti-disastro: un pin a >100km dal centro della SUA città è
            # quasi certamente un errore (continente sbagliato, tocco involontario)
            # -> pin e coordinate scartati, si torna alla geocodifica normale.
            if dati.get("pin_manuale"):
                if not ha_coord:
                    dati = dict(dati)
                    dati["pin_manuale"] = False      # flag senza coordinate: non vale
                else:
                    centro = gc.geocodifica(citta) if (
                        isinstance(citta, str) and citta.strip()) else None
                    if not centro:
                        return dati                  # niente centro con cui confrontare
                    from fase121_geo_ricerca import distanza_m
                    d_m = distanza_m(dati["lat_micro"], dati["lon_micro"],
                                     centro[0], centro[1])
                    if not (isinstance(d_m, int) and d_m > 100_000):
                        return dati                  # pin sensato: parola all'host
                    dati = dict(dati)                # pin assurdo: via flag e coordinate
                    dati["pin_manuale"] = False
                    dati.pop("lat_micro", None)
                    dati.pop("lon_micro", None)
                    ha_coord = False
            # con INDIRIZZO -> geocodifica sempre da lì (fonte PRECISA, anche in modifica);
            # senza indirizzo -> solo se mancano le coordinate (non degradare una posizione
            # già precisa a centro-città). Cache-hit se l'indirizzo non è cambiato: istantaneo.
            if ha_coord and not indir:
                return dati
            if not ((isinstance(citta, str) and citta.strip()) or indir):
                return dati
            coord = gc.geocodifica(citta, indirizzo=indir,
                                   paese=str(dati.get("paese", "") or ""))
            # GUARDIA ANTI-ERRORE: se il geocode dell'INDIRIZZO cade a >30km dal centro
            # della sua città, l'indirizzo è stato interpretato male (omonimie) -> meglio
            # il centro città (onesto) che un pin nel posto sbagliato.
            if coord and indir and isinstance(citta, str) and citta.strip():
                centro = gc.geocodifica(citta)
                if centro:
                    try:
                        from fase121_geo_ricerca import distanza_m
                        d_m = distanza_m(coord[0], coord[1], centro[0], centro[1])
                        if isinstance(d_m, int) and d_m > 30000:
                            coord = centro
                    except Exception:
                        pass
            if coord:
                dati = dict(dati)
                dati["lat_micro"], dati["lon_micro"] = int(coord[0]), int(coord[1])
        except Exception:
            logger.warning("auto-geocodifica fallita (ignorata)", exc_info=True)
        return dati

    def _host_importa(self, body, headers):
        """Porta gli annunci dai colossi (Booking/Airbnb) DA NOI: ingerisce l'export
        machine-readable dell'host (suo diritto GDPR Art.20, NON scraping) e lo pubblica.
        Sicuro: proprietario dal TOKEN, slug generato da noi (no collisioni/furto), valuta
        preservata. Accetta un annuncio (dict) o una lista di annunci. Isolato per-annuncio."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        dati = self._json(body)
        if not isinstance(dati, dict):
            return 400, {"errore": "json_non_valido"}
        sorgente = dati.get("sorgente") or "canonico"
        if sorgente not in ("booking", "airbnb", "canonico"):
            sorgente = "canonico"
        payload = dati.get("dati")
        lista = payload if isinstance(payload, list) else [payload]
        if not lista or not all(isinstance(x, dict) for x in lista):
            return 422, {"errore": "export_non_valido"}
        if len(lista) > 200:
            return 422, {"errore": "troppi_annunci"}
        hid = self._host_id_da_token(headers)
        try:
            from fase77_portability import importa as _imp
        except Exception:
            logger.error("import portability: modulo non disponibile", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        risultati = []
        importati = 0
        for item in lista:
            try:
                rep = _imp(item, sorgente=sorgente, catalogo=self._sys.catalogo,
                           inventario=self._sys.inventario, host_id=hid,
                           genera_slug=self._slug_unico, rehost=self._scarica_immagine,
                           arricchisci=self._geocodifica_se_serve)
            except Exception:
                logger.error("import portability: eccezione ISOLATA su un annuncio",
                             exc_info=True)
                risultati.append({"ok": False, "slug": "", "errori": ["errore_interno"]})
                continue
            ok = bool(rep.ok and rep.catalogo_applicato)
            if ok:
                importati += 1
            risultati.append({
                "ok": ok, "slug": rep.slug,
                "titolo": (rep.scheda or {}).get("titolo"),
                "notti_applicate": rep.notti_applicate,
                "errori": rep.errori,
            })
        return 200, {"importati": importati, "totale": len(lista), "risultati": risultati}

    def _scarica_immagine(self, url, hop=0):
        """Scarica una foto da un URL (import dai colossi) e la salva su UPLOAD_DIR ->
        /uploads/<nome>. ANTI-SSRF (solo host pubblici), tetto 5MB, tipo dai MAGIC BYTES,
        timeout 10s. Redirect seguiti a mano (max 3) ri-validando l'host ogni volta.
        None se non affidabile (l'import scarta quella foto e prosegue)."""
        import urllib.error
        import urllib.request
        from urllib.parse import urljoin, urlparse
        if not (isinstance(url, str) and url) or hop > 3:
            return None
        try:
            p = urlparse(url)
        except Exception:
            return None
        if p.scheme not in ("http", "https") or not p.hostname:
            return None
        if not _ip_host_pubblico(p.hostname):
            return None                               # anti-SSRF: niente host interni

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None                           # non seguire in automatico (TOCTOU)

        opener = urllib.request.build_opener(_NoRedirect)
        req = urllib.request.Request(url, headers={"User-Agent": "BookinVIP-Import/1.0",
                                                   "Accept": "image/*"})
        try:
            resp = opener.open(req, timeout=10)
        except urllib.error.HTTPError as e:
            if 300 <= e.code < 400:                   # redirect: ri-valida l'host al prossimo hop
                loc = e.headers.get("Location")
                return self._scarica_immagine(urljoin(url, loc), hop + 1) if loc else None
            return None
        except Exception:
            return None
        try:
            raw = resp.read(5 * 1024 * 1024 + 1)      # tetto: legge al massimo 5MB+1
        except Exception:
            raw = b""
        finally:
            try:
                resp.close()
            except Exception:
                pass
        if not raw or len(raw) > 5 * 1024 * 1024:
            return None
        ext = _ext_da_magic(raw)
        if ext is None:
            return None                               # non e' un'immagine valida
        import os as _os
        import secrets as _sec
        updir = _os.environ.get("UPLOAD_DIR", "data/uploads")
        try:
            _os.makedirs(updir, exist_ok=True)
            nome = _sec.token_hex(16) + "." + ext
            with open(_os.path.join(updir, nome), "wb") as f:
                f.write(raw)
        except Exception:
            logger.warning("rehost foto: salvataggio fallito (ISOLATO)", exc_info=True)
            return None
        return "/uploads/" + nome

    def _slug_unico(self, titolo, citta):
        """Genera uno slug pubblico pulito dal titolo (o città), garantito UNIVOCO nel catalogo.
        L'host non lo vede/digita mai: serve solo come indirizzo interno stabile."""
        import re as _re, unicodedata as _ud, secrets as _s
        base = str(titolo or citta or "casa")
        base = _ud.normalize("NFKD", base).encode("ascii", "ignore").decode()
        base = _re.sub(r"[^a-zA-Z0-9]+", "-", base).strip("-").lower()[:40] or "casa"
        cat = getattr(self._sys, "catalogo", None)
        candidati = [base] + ["%s-%d" % (base, i) for i in range(2, 80)]
        for cand in candidati:
            try:
                if cat is None or cat.host_di_alloggio(cand) is None:
                    return cand
            except Exception:
                break
        return base + "-" + _s.token_hex(3)

    def _foto_elimina(self, body, headers):
        """Cancella una foto caricata per errore (file in UPLOAD_DIR). Host-auth. Path-safe:
        accetta solo /uploads/<nome> dentro la cartella upload; idempotente."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        dati = self._json(body)
        if not isinstance(dati, dict):
            return 400, {"errore": "json_non_valido"}
        import os as _os, posixpath as _pp
        url = dati.get("url") or ""
        if not (isinstance(url, str) and url.startswith("/uploads/")):
            return 422, {"errore": "url_non_valido"}
        nome = _pp.basename(url)
        if not nome or nome in (".", ".."):
            return 422, {"errore": "url_non_valido"}
        updir = _os.environ.get("UPLOAD_DIR", "data/uploads")
        percorso = _os.path.abspath(_os.path.join(updir, nome))
        try:
            if _os.path.commonpath([percorso, _os.path.abspath(updir)]) != _os.path.abspath(updir):
                return 422, {"errore": "url_non_valido"}       # fuori dalla cartella: rifiuta
            if _os.path.isfile(percorso):
                _os.remove(percorso)
            return 200, {"eliminata": True}
        except Exception:
            logger.warning("foto elimina fallita (ISOLATA)", exc_info=True)
            return 200, {"eliminata": False}

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
        if not self._verifica_proprieta(headers, alloggio):
            return 403, {"errore": "non_tuo"}
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
        # soggiorno MINIMO (facoltativo, default 1): lo rispettano ENTRAMBI la ricerca/quote
        # (disponibile) e il book (blocca) -> niente preventivi sotto la soglia.
        mn = dati.get("min_notti", 1)
        if not (isinstance(mn, int) and not isinstance(mn, bool) and 1 <= mn <= 366):
            return 422, {"errore": "min_notti_non_valido"}
        if not self._verifica_proprieta(headers, alloggio):
            return 403, {"errore": "non_tuo"}
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
                    alloggio, g, unita_totali=unita, prezzo_netto_cents=prezzo, min_notti=mn):
                impostati += 1
        return 200, {"giorni_impostati": impostati}

    def _host_metriche(self, query, headers):
        """Dashboard host: revenue/occupazione (fase58) + prenotazioni + recensioni."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        alloggio = query.get("alloggio") or None
        da, a = query.get("da") or None, query.get("a") or None
        # ISOLAMENTO (bug provato: data-leak/IDOR): con uno slug SPECIFICO va verificata la
        # proprieta' (senza, un host leggeva le metriche di un annuncio ALTRUI); SENZA slug si
        # aggregavano TUTTI gli annunci di TUTTA la piattaforma (`metriche(None)` = nessun WHERE)
        # -> ogni host vedeva l'incasso dell'intera piattaforma. Ora: solo i PROPRI annunci.
        if alloggio is not None and not self._verifica_proprieta(headers, alloggio):
            return 403, {"errore": "non_tuo"}
        try:
            if alloggio is not None:
                inv = self._sys.inventario.metriche(alloggio_id=alloggio, da=da, a=a)
                pren = self._sys.inventario.elenco_prenotazioni(alloggio_id=alloggio, limit=500)
            else:
                hid = self._host_id_da_token(headers)
                slugs = [al.get("slug") for al in
                         (self._sys.catalogo.alloggi_host(hid, limit=200) if hid else [])
                         if isinstance(al, dict) and al.get("slug")]
                inv = {"revenue_cents": 0, "notti_totali": 0, "notti_occupate": 0,
                       "giorni": 0, "occupazione_bps": 0}
                pren = []
                for s in slugs:                         # aggrego SOLO gli annunci dell'host
                    mi = self._sys.inventario.metriche(alloggio_id=s, da=da, a=a)
                    inv["revenue_cents"] += mi.get("revenue_cents", 0)
                    inv["notti_totali"] += mi.get("notti_totali", 0)
                    inv["notti_occupate"] += mi.get("notti_occupate", 0)
                    inv["giorni"] += mi.get("giorni", 0)
                    pren.extend(self._sys.inventario.elenco_prenotazioni(alloggio_id=s, limit=500))
                inv["occupazione_bps"] = (inv["notti_occupate"] * 10000 // inv["notti_totali"]) \
                    if inv["notti_totali"] else 0
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
        # ISOLAMENTO (stesso IDOR di _host_metriche): slug altrui -> 403; senza slug si
        # esportavano le prenotazioni di TUTTA la piattaforma. Ora: solo le proprie.
        if alloggio is not None and not self._verifica_proprieta(headers, alloggio):
            return 403, {"errore": "non_tuo"}
        try:
            if alloggio is not None:
                righe = self._sys.inventario.elenco_prenotazioni(alloggio_id=alloggio, limit=500)
            else:
                hid = self._host_id_da_token(headers)
                righe = []
                for al in (self._sys.catalogo.alloggi_host(hid, limit=200) if hid else []):
                    s = al.get("slug") if isinstance(al, dict) else None
                    if s:
                        righe.extend(self._sys.inventario.elenco_prenotazioni(alloggio_id=s,
                                                                              limit=500))
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

    def _tg_firma_payload(self, host_id):
        """Payload FIRMATO per il deep-link Telegram (start): host_id + HMAC corto. Compatto
        (<64 char, solo [a-z0-9_-] ammessi da Telegram) e DUREVOLE (non serve stato in memoria
        -> sopravvive ai riavvii del server). Ricavabile SOLO via endpoint autenticato."""
        import hashlib
        import hmac as _h
        seg = getattr(getattr(self._sys, "config", None), "segreto_hmac", b"") or b""
        if isinstance(seg, str):
            seg = seg.encode("utf-8")
        sig = _h.new(seg, str(host_id).encode("utf-8"), hashlib.sha256).hexdigest()[:16]
        return "%s-%s" % (host_id, sig)

    def _tg_verifica_payload(self, payload):
        """host_id se il payload è firmato correttamente, altrimenti None."""
        import hashlib
        import hmac as _h
        if not (isinstance(payload, str) and "-" in payload):
            return None
        hid, _, sig = payload.rpartition("-")
        if not (hid and sig):
            return None
        seg = getattr(getattr(self._sys, "config", None), "segreto_hmac", b"") or b""
        if isinstance(seg, str):
            seg = seg.encode("utf-8")
        atteso = _h.new(seg, hid.encode("utf-8", "surrogatepass"), hashlib.sha256).hexdigest()[:16]
        return hid if _h.compare_digest(sig, atteso) else None

    # ── GATEKEEPER: sessione-PAGINA firmata (cookie) per servire le pagine riservate ──
    # Il denaro/i dati erano gia' protetti sull'API (ogni azione verifica il token). Questo
    # e' l'hardening in piu': la STRUTTURA delle pagine admin/bunker/host NON viene servita a
    # chi non ha una sessione valida (zero information leakage). Il cookie firma SOLO "questo
    # browser ha passato il login <livello>": stateless (come FirmaQuote), niente stato in RAM.
    # L'auth dell'API resta invariata (header token) -> immune a CSRF (un cookie SameSite=Lax
    # da solo non basta: le chiamate che muovono dati vogliono comunque l'header, non-settabile
    # cross-site). Il cookie e' HttpOnly (mai leggibile da JS/XSS) + Secure (solo HTTPS).
    def _gate_segreto(self):
        seg = getattr(getattr(self._sys, "config", None), "segreto_hmac", b"") or b""
        return seg.encode("utf-8") if isinstance(seg, str) else seg

    def _gate_firma(self, livello, ttl_sec=43200):
        """Cookie firmato 'livello|scadenza|nonce|hmac' (HMAC-SHA256, segreto del progetto)."""
        import base64
        import hashlib
        import hmac as _h
        import os as _os
        import time as _t
        exp = int(_t.time()) + int(ttl_sec)
        nonce = base64.urlsafe_b64encode(_os.urandom(9)).decode("ascii").rstrip("=")
        corpo = "%s|%d|%s" % (livello, exp, nonce)
        sig = _h.new(self._gate_segreto(), corpo.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
        return corpo + "|" + sig

    def _gate_valida(self, valore, livello_atteso):
        """True se il cookie e' firmato bene, del livello giusto e NON scaduto. Costante-tempo."""
        import hashlib
        import hmac as _h
        import time as _t
        if not (isinstance(valore, str) and valore.count("|") == 3):
            return False
        livello, exp, nonce, sig = valore.split("|")
        if livello != livello_atteso:
            return False
        corpo = "%s|%s|%s" % (livello, exp, nonce)
        atteso = _h.new(self._gate_segreto(), corpo.encode("utf-8", "surrogatepass"),
                        hashlib.sha256).hexdigest()[:32]
        if not _h.compare_digest(sig, atteso):
            return False
        try:
            return int(exp) > int(_t.time())
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _leggi_cookie(headers, nome):
        """Estrae UN cookie dal header 'Cookie' (parsing tollerante, senza dipendenze)."""
        raw = ""
        if isinstance(headers, dict):
            raw = headers.get("Cookie", "") or headers.get("cookie", "")
        for parte in str(raw).split(";"):
            k, _, v = parte.strip().partition("=")
            if k == nome:
                return v.strip()
        return ""

    # durata sessione-pagina per livello (secondi). Bunker corto = 15 min (come la sua sessione).
    _GATE_TTL = {"admin": 12 * 3600, "host": 12 * 3600, "bunker": 15 * 60}

    def _admin_login(self, body, headers):
        """Login di PAGINA per l'admin: verifica la chiave admin (rate-limited come le altre
        rotte admin) e, se giusta, emette il cookie di sessione 'bv_admin'. Non introduce una
        credenziale nuova: la chiave e' la stessa di sempre (inviata come X-Admin-Key)."""
        if self._admin_key is None:
            return 503, {"errore": "admin_non_configurato"}
        ttl = self._GATE_TTL["admin"]
        dati = self._json(body) if body else None
        # (A) OPERATORE (fase192) via email+password -> token operatore col RUOLO. Rate-limit per IP.
        if isinstance(dati, dict) and dati.get("email") and dati.get("password"):
            rl = self._rate
            ip = self._client_ip(headers)
            chiave = ("authop:%s" % ip) if ip else ""
            if rl is not None and chiave:
                consentito, attesa = rl.consenti(chiave)
                if not consentito:
                    return 429, {"errore": "troppi_tentativi", "attesa_sec": attesa}
            aa = getattr(self._sys, "admin_accounts", None)
            v = aa.verifica(dati.get("email"), dati.get("password")) if aa is not None else {"ok": False}
            if not v.get("ok"):
                if rl is not None and chiave:
                    rl.fallito(chiave)
                return 401, {"errore": "credenziali_non_valide"}
            if rl is not None and chiave:
                rl.riuscito(chiave)
            tok = self._firma_op(v["email"], v["ruolo"])
            return 200, {"ok": True, "ruolo": v["ruolo"], "operatore": v["email"], "op_token": tok,
                         "_cookie": [("bv_admin", self._gate_firma("admin", ttl), ttl)]}
        # (B) ROOT via X-Admin-Key (come sempre): super-potere pieno.
        if not self._auth_admin(headers):        # confronto costante-tempo + rate-limit dentro
            return 401, {"errore": "unauthorized"}
        return 200, {"ok": True, "ruolo": "admin",
                     "_cookie": [("bv_admin", self._gate_firma("admin", ttl), ttl)]}

    def _gate_logout(self, body, headers):
        """Logout di PAGINA: cancella TUTTI i cookie di sessione (Max-Age=0). Cosi' dopo il
        logout la ri-navigazione a una pagina riservata torna al login (con le pagine gia'
        marcate no-store, il browser non ne conserva copia)."""
        vuoti = [("bv_admin", "", 0), ("bv_host", "", 0), ("bv_bunker", "", 0)]
        return 200, {"ok": True, "_cookie": vuoti}

    def _host_calendario_prezzi(self, query, headers):
        """Calendario PREZZI giorno-per-giorno dell'alloggio (fase119): per ogni giorno stato +
        prezzo base + prezzo DINAMICO suggerito (fase106). L'host vede dove alzare/abbassare."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        slug = query.get("alloggio")
        if not (isinstance(slug, str) and slug):
            return 422, {"errore": "alloggio_mancante"}
        if not self._verifica_proprieta(headers, slug):
            return 403, {"errore": "non_tuo"}
        da, a = query.get("da"), query.get("a")
        if not (isinstance(da, str) and da and isinstance(a, str) and a):
            return 422, {"errore": "date_mancanti"}
        try:
            from fase119_calendario_prezzi import costruisci_calendario
            inv = self._sys.inventario
            stato_fn, occ_bps = inv.stato_giorno, 5000
            # PREFETCH (vincitrice benchmark): una query per l'intero range invece di
            # una CONNESSIONE per giorno (362ms->1.7ms; 2.4s->21ms sotto scrittura
            # concorrente multi-dispositivo). Dai dati gia' letti si calcola anche
            # l'occupazione REALE del range: prima era fissa a 5000 bps e il fattore
            # occupazione del prezzo dinamico (fase106) non scattava MAI.
            rng = getattr(inv, "stato_range", None)
            if callable(rng):
                byday = rng(slug, da, a)
                stato_fn = lambda _s, g: byday.get(g)
                # Occupazione = VENDUTO / VENDIBILE. Dal denominatore si tolgono
                # solo le notti FISICAMENTE invendibili -- e' la definizione di
                # settore (Preno, SiteMinder, RoomMaster 2026: «rooms available
                # excludes out-of-order») -- ma una notte GIA' VENDUTA resta
                # venduta anche se l'host l'ha poi chiusa, ed e' la stessa
                # priorita' «venduta vince su chiusa» del bug #35.
                # Prima spariva da entrambi i lati: 4 notti vendute e poi chiuse
                # facevano crollare il suggerito da 14300 a 11000 (-23,1%), e con
                # TUTTE chiuse il denominatore andava a zero e si ripiegava sul
                # default «mezzo pieno» mentre l'alloggio era pieno al 100%.
                tot_u = sum((r.get("unita_occupate", 0) if r.get("chiuso")
                             else r.get("unita_totali", 0))
                            for r in byday.values() if isinstance(r, dict))
                tot_o = sum(r.get("unita_occupate", 0) for r in byday.values()
                            if isinstance(r, dict))
                if isinstance(tot_u, int) and tot_u > 0 and isinstance(tot_o, int):
                    occ_bps = min(10000, max(0, tot_o * 10000 // tot_u))
            celle = costruisci_calendario(slug, da, a, stato_giorno=stato_fn,
                                          occupazione_bps=occ_bps)
        except Exception:
            logger.error("calendario prezzi: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        # Un range non valido (oltre il tetto di 366 giorni, date invertite, o
        # una stringa che non e' una data) produce ZERO celle: rispondere 200 con
        # una lista vuota lo rende indistinguibile da «non hai caricato nulla».
        # «Returning 200 OK with an error indicator is incorrect practice»
        # (DevEssentials; Ben Nadel; oneuptime 2026): la validazione fallita e'
        # un 422 con un codice leggibile, come gia' fa `date_mancanti` qui sopra.
        # Il giudizio NON e' duplicato: e' `costruisci_calendario` a decidere cosa
        # sia un range valido, cosi' il tetto resta scritto in un posto solo.
        if not celle:
            return 422, {"errore": "range_date_non_valido"}
        return 200, {"celle": celle}

    def _ical_link(self, query, headers):
        """URL .ics del calendario dell'alloggio: l'host lo incolla su Booking/Airbnb/Vrbo e
        le date prenotate QUI si bloccano LÌ (anti-overbooking). Firmato (contiene lo slug),
        senza scadenza. Solo il proprietario può generarlo."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        slug = query.get("alloggio")
        if not (isinstance(slug, str) and slug):
            return 422, {"errore": "alloggio_mancante"}
        if not self._verifica_proprieta(headers, slug):
            return 403, {"errore": "non_tuo"}
        firma = getattr(self._sys, "firma", None)
        if firma is None:
            return 503, {"errore": "non_disponibile"}
        from urllib.parse import quote as _q
        tok = firma.codifica({"k": "ical", "slug": slug})
        base = self._base_url or "https://bookinvip.com"
        return 200, {"url": base + "/ical/" + _q(tok) + ".ics"}

    def _ical_export(self, token):
        """Testo .ics (feed) delle date NON PRENOTABILI dell'alloggio, dal token firmato. None se
        il token non è valido. Serve alle piattaforme esterne che leggono il feed periodicamente."""
        firma = getattr(self._sys, "firma", None)
        d = firma.decodifica(token) if (firma and token) else None
        if not (isinstance(d, dict) and d.get("k") == "ical" and d.get("slug")):
            return None
        slug = d["slug"]
        try:
            occ = self._export_occupati(slug)
        except Exception:
            logger.warning("ical export: raccolta occupati fallita (ISOLATO)", exc_info=True)
            return None
        try:
            from fase135_ical_bidirezionale import genera_ical
            return genera_ical(occ)
        except Exception:
            logger.error("ical export: generazione fallita (ISOLATA)", exc_info=True)
            return None

    def _export_occupati(self, slug):
        """Tutte le date NON prenotabili [oggi, +365] da esportare verso gli OTA esterni. FONTE
        UNICA = la disponibilità REALE (fase58.calendario), NON solo le nostre prenotazioni:
        così un blocco IMPORTATO via iCal (Airbnb/Booking, `unita_totali=0`) e i giorni CHIUSI
        dall'host si propagano nel feed. Senza questo, una data presa su Airbnb non arrivava a
        Booking → overbooking cross-canale (il buco che il claim 'anti-overbooking' prometteva di
        chiudere). Giorni contigui coalizzati in intervalli [inizio, fine) con DTEND ESCLUSIVO."""
        import datetime as _dt
        oggi = _dt.date.today()
        # finestra 365 gg (cap MAX_NOTTI di fase58.calendario); gli OTA guardano ~1 anno avanti
        cal = self._sys.inventario.calendario(
            str(slug), oggi.isoformat(), (oggi + _dt.timedelta(days=365)).isoformat())
        bloccati = sorted(g["giorno"] for g in (cal or [])
                          if isinstance(g, dict) and g.get("stato") in ("pieno", "chiuso"))
        occ, inizio, prec = [], None, None
        for giorno in bloccati:
            try:
                gd = _dt.date.fromisoformat(giorno)
            except (ValueError, TypeError):
                continue
            if inizio is None:
                inizio = prec = gd
            elif gd == prec + _dt.timedelta(days=1):
                prec = gd                                  # estende il run contiguo
            else:
                occ.append({"slug": slug, "check_in": inizio.isoformat(),
                            "check_out": (prec + _dt.timedelta(days=1)).isoformat(),
                            "uid": "block-" + inizio.isoformat()})
                inizio = prec = gd
        if inizio is not None:
            occ.append({"slug": slug, "check_in": inizio.isoformat(),
                        "check_out": (prec + _dt.timedelta(days=1)).isoformat(),
                        "uid": "block-" + inizio.isoformat()})
        return occ

    def _host_telegram_link(self, headers):
        """Link per COLLEGARE il Telegram dell'host: aprendolo e premendo Start, il bot salva
        il suo chat_id -> riceve lì gli avvisi di prenotazione (coi tasti Approva/Rifiuta)."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        hid = self._host_id_da_token(headers)
        if not hid:
            return 422, {"errore": "host_id_mancante"}
        import os as _os
        bot = (_os.environ.get("TELEGRAM_BOT_USERNAME") or "BookinVipInfo_bot").lstrip("@")
        return 200, {"link": "https://t.me/%s?start=%s" % (bot, self._tg_firma_payload(hid))}

    def _tg_reply(self, chat_id, testo):
        """Risposta best-effort all'host su Telegram (isolata)."""
        import json as _j
        import os as _os
        import urllib.request as _u
        tokb = _os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not (tokb and chat_id):
            return
        try:
            corpo = _j.dumps({"chat_id": chat_id, "text": testo}).encode("utf-8")
            req = _u.Request("https://api.telegram.org/bot%s/sendMessage" % tokb, data=corpo,
                             method="POST", headers={"Content-Type": "application/json"})
            _u.urlopen(req, timeout=8).read()
        except Exception:
            logger.warning("telegram reply fallita (ISOLATA)", exc_info=True)

    def _telegram_webhook(self, body, headers):
        """Webhook Telegram: quando l'host preme Start col codice, salva il suo chat_id.
        GATED dal segreto TELEGRAM_WEBHOOK_SECRET se impostato. Risponde sempre 200 a Telegram."""
        import os as _os
        import time as _t
        segreto = _os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
        if segreto:
            fornito = (headers or {}).get("X-Telegram-Bot-Api-Secret-Token", "") or \
                (headers or {}).get("x-telegram-bot-api-secret-token", "")
            if fornito != segreto:
                return 403, {"errore": "forbidden"}
        dati = self._json(body)
        if not isinstance(dati, dict):
            return 200, {"ok": True}
        msg = dati.get("message") or dati.get("edited_message") or {}
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        testo = str(msg.get("text") or "").strip()
        if chat_id and testo.startswith("/start"):
            parti = testo.split(maxsplit=1)
            payload = parti[1].strip() if len(parti) > 1 else ""
            hid = self._tg_verifica_payload(payload)
            if hid:
                reg = getattr(self._sys, "registro_host", None)
                ok = reg.imposta_telegram_chat(hid, str(chat_id)) if reg is not None else False
                self._tg_reply(chat_id, "✅ Telegram collegato! Qui riceverai gli avvisi di "
                               "prenotazione, coi tasti Approva/Rifiuta." if ok else
                               "Non sono riuscito a collegare. Riprova dal pannello host.")
            else:
                self._tg_reply(chat_id, "Link non valido. Genera un nuovo collegamento dal "
                               "pannello host (\"Collega Telegram\").")
        return 200, {"ok": True}

    def _host_prenotazioni(self, query, headers):
        """'Le mie prenotazioni' con PAGINAZIONE SERVER-SIDE: filtro, conteggio e
        TAGLIO li fa il DATABASE (fase58 LIMIT/OFFSET) — al client viaggia SOLO la
        pagina richiesta, mai l'intera storia. Parametri: `vista` attive|archivio
        (default attive: le annullate non sporcano la vista), `page` 1-based,
        `limit` 1..50 (default 10). Parametri ostili -> default garbati, mai 5xx.
        Le richieste da approvare restano su /api/host/richieste (sono uno STATO del
        flusso: la UI le fonde in un'unica lista, il money-path approva/rifiuta non
        si tocca). ARCHIVIAZIONE LOGICA: nessun DELETE, i movimenti restano per
        l'audit (vista+archivio == tutto)."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        hid = self._host_id_da_token(headers) or query.get("host_id")
        if not (isinstance(hid, str) and hid):
            return 422, {"errore": "host_id_mancante"}

        def _n(v, default, mini, maxi):
            try:
                n = int(str(v))
            except Exception:
                return default
            return max(mini, min(maxi, n))

        vista = query.get("vista")
        if vista not in ("attive", "archivio"):
            vista = "attive"
        page = _n(query.get("page"), 1, 1, 10 ** 6)
        limit = _n(query.get("limit"), 10, 1, 50)
        try:
            import datetime as _dt
            from fase59_concierge import codice_prenotazione
            firma = getattr(self._sys, "firma", None)
            pp = getattr(self._sys, "pagamenti_pendenti", None)
            inv = self._sys.inventario
            oggi = _dt.date.today().isoformat()
            listings = self._sys.catalogo.alloggi_host(hid, limit=200)
            titoli, slugs = {}, []
            for a in listings:
                slug = a.get("slug") if isinstance(a, dict) else None
                if not slug:
                    continue
                slugs.append(slug)
                titoli[slug] = (a.get("titolo") if isinstance(a, dict) else None) or slug
            # le richieste 'su richiesta' ancora da approvare TENGONO la stanza (blocco
            # vivo) ma NON sono prenotazioni: sono uno STATO del flusso, mostrato come
            # riga-azione (fonte /api/host/richieste). Qui si ESCLUDONO in SQL, cosi'
            # non compaiono doppie e pagine/conteggi restano esatti.
            escludi = []
            if pp is not None:
                try:
                    escludi = [str(r.get("idem_key") or "")
                               for r in pp.da_approvare(hid) if r.get("idem_key")]
                except Exception:
                    escludi = []
            tot_attive = inv.conta_prenotazioni(alloggi=slugs, vista="attive",
                                                escludi_idem=escludi)
            tot_arch = inv.conta_prenotazioni(alloggi=slugs, vista="archivio")
            totale = tot_attive if vista == "attive" else tot_arch
            pagina = inv.elenco_prenotazioni_pagina(
                alloggi=slugs, vista=vista, limit=limit, offset=(page - 1) * limit,
                escludi_idem=(escludi if vista == "attive" else None))
            out = []
            for p in pagina:
                # CODICE + PIN check-in nel PANNELLO; riferimento = idem_key[:24]
                # (fase59); dopo un re-block tardivo la chiave attiva e'
                # 'reblock:<rif>' -> si estrae il rif originale.
                idem = str(p.get("idem_key") or "")
                ref = idem[len("reblock:"):] if idem.startswith("reblock:") else idem[:24]
                ci, co = p.get("check_in"), p.get("check_out")
                archiviata = bool(p.get("rimborsato"))
                if archiviata:
                    # distinzione fine SOLO sulle righe della pagina (<= limit lookup:
                    # mai N+1 sull'intera storia); pendente purgato (26h) -> resta
                    # 'rimborsata'. 'scaduto' = hold/richiesta MAI pagata scaduta da
                    # sola: etichettarla "rimborsata" era una bugia (niente da
                    # rimborsare) -> etichetta onesta 'scaduta'.
                    stato = "rimborsata"
                    if pp is not None and ref:
                        try:
                            rec = pp.info(ref)
                            if rec and rec.get("stato") == "cancellata_host":
                                stato = "cancellata"
                            elif rec and rec.get("stato") == "scaduto":
                                stato = "scaduta"
                        except Exception:
                            pass
                else:
                    # etichetta temporale della vista attiva; un soggiorno passato ma
                    # non rilasciato resta 'confermata' (soldi maturati all'host).
                    stato = "confermata"
                    if isinstance(ci, str) and isinstance(co, str) and ci and co:
                        if ci > oggi:
                            stato = "futura"
                        elif ci <= oggi < co:
                            stato = "attiva"
                out.append({"alloggio": titoli.get(p.get("alloggio_id"),
                                                   p.get("alloggio_id") or ""),
                            "slug": p.get("alloggio_id"),
                            "check_in": ci, "check_out": co,
                            "codice": codice_prenotazione(ref) if ref else "",
                            "pin": (firma.pin_checkin(ref) if (firma and ref) else ""),
                            "stato": stato, "archiviata": archiviata})
        except Exception:
            logger.error("host prenotazioni: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        return 200, {"prenotazioni": out, "vista": vista, "page": page,
                     "limit": limit, "totale": totale,
                     "pagine": max(1, -(-totale // limit)),
                     "totale_attive": tot_attive, "totale_archivio": tot_arch}

    def _host_alloggi(self, query, headers):
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        # host ricavato dal TOKEN (l'host non deve digitare il proprio id): vede solo i SUOI
        host_id = self._host_id_da_token(headers) or query.get("host_id")
        if not (isinstance(host_id, str) and host_id):
            return 422, {"errore": "host_id_mancante"}
        try:
            el = self._sys.catalogo.alloggi_host(host_id, limit=200)
        except Exception:
            logger.error("host alloggi: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        return 200, {"alloggi": el}

    def _verifica_proprieta(self, headers, slug) -> bool:
        """Self-service (token): l'host può modificare SOLO i propri alloggi. Operatore
        (X-Host-Key senza token): consentito (back-office piattaforma). Slug inesistente
        o errore infrastrutturale: non blocca qui (l'operazione a valle valida/no-op)."""
        hid = self._host_id_da_token(headers)
        if not hid:
            return True
        try:
            owner = self._sys.catalogo.host_di_alloggio(slug)
        except Exception:
            return True
        return owner is None or owner == hid

    def _host_alloggio_dettaglio(self, query, headers):
        """Dettaglio COMPLETO di un alloggio del proprietario (per pre-riempire il form di
        modifica). Host-auth + verifica proprietà."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        slug = query.get("slug")
        if not (isinstance(slug, str) and slug):
            return 422, {"errore": "slug_mancante"}
        if not self._verifica_proprieta(headers, slug):
            return 403, {"errore": "non_tuo"}
        try:
            d = self._sys.catalogo.dettaglio_owner(slug)
        except Exception:
            logger.error("host alloggio dettaglio: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        if d is None:
            return 404, {"errore": "non_trovato"}
        return 200, d

    def _host_geocode(self, query, headers):
        """Coordinate per centrare la mini-mappa del form host sui campi digitati
        (città/indirizzo), PRIMA di salvare. Host-auth (il geocoder non si espone
        ad anonimi); cache-first fase166 -> Nominatim al massimo 1 volta per chiave."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        gc = getattr(self._sys, "geocoder", None)
        if gc is None:
            return 503, {"errore": "geocoder_spento"}
        citta = str(query.get("citta", "") or "").strip()[:200]
        indir = str(query.get("indirizzo", "") or "").strip()[:200]
        paese = str(query.get("paese", "") or "").strip()[:200]
        if not (citta or indir):
            return 422, {"errore": "citta_o_indirizzo_richiesti"}
        try:
            coord = gc.geocodifica(citta, indirizzo=indir, paese=paese)
        except Exception:
            logger.warning("host geocode: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        if not coord:
            return 404, {"errore": "non_trovata"}
        return 200, {"lat_micro": int(coord[0]), "lon_micro": int(coord[1])}

    def _host_stato(self, body, headers):
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        slug, stato = dati.get("slug"), dati.get("stato")
        if not (isinstance(slug, str) and slug and isinstance(stato, str)):
            return 422, {"errore": "campi_non_validi"}
        if not self._verifica_proprieta(headers, slug):
            return 403, {"errore": "non_tuo"}
        ok = self._sys.catalogo.imposta_stato(slug, stato)
        return (200 if ok else 422), {"stato": stato if ok else "rifiutato"}

    def _cal_arricchito(self, alloggio, da, a, hold_prefetch=None):
        """Celle calendario di UN alloggio (libero/pieno/chiuso/non_caricato) + marcatura
        'in_trattativa' (arancione) dei giorni con hold VIVO. Riusato dal calendario singolo
        E da quello di TUTTI gli alloggi. Isolato: l'in_trattativa non blocca mai.
        hold_prefetch: se passato (mappa slug->[hold] dalla vista multi-alloggio), evita la
        query per-slug -> N+1 azzerato. Se None, ricade sulla query singola (path invariato)."""
        cal = self._sys.inventario.calendario(alloggio, da, a)
        try:
            pp = getattr(self._sys, "pagamenti_pendenti", None)
            if pp is not None and cal:
                import datetime as _dtc
                gg_hold = set()
                hold = hold_prefetch.get(alloggio, []) if hold_prefetch is not None \
                    else pp.attivi_per_alloggio(alloggio)
                for h in hold:
                    try:
                        d0 = _dtc.date.fromisoformat(h.get("check_in", ""))
                        d1 = _dtc.date.fromisoformat(h.get("check_out", ""))
                        for i in range(max(0, (d1 - d0).days)):
                            gg_hold.add((d0 + _dtc.timedelta(days=i)).isoformat())
                    except Exception:
                        continue
                for g in cal:
                    if isinstance(g, dict) and g.get("giorno") in gg_hold \
                            and g.get("stato") == "pieno":
                        g["stato"] = "in_trattativa"
        except Exception:
            logger.warning("marcatura in_trattativa fallita (ignorata)", exc_info=True)
        return cal

    def _email_esito_richiesta(self, rec, esito):
        """Il cliente ha DIRITTO di sapere come e' finita la sua richiesta su-richiesta:
        'rifiutata' dall'host o 'scaduta' senza risposta (24h). Prima: sul rifiuto NESSUN
        avviso (il cliente aspettava a vuoto), sulla scadenza partiva l'email 'il pagamento
        non e' andato a buon fine' — falsa e allarmante: il cliente non doveva pagare
        niente. UNA email onesta, transazionale, best-effort ISOLATA (mai blocca)."""
        try:
            ep = getattr(self._sys, "email_provider", None)
            email = (rec or {}).get("email", "")
            slug = (rec or {}).get("alloggio_id", "")
            if ep is None or not (isinstance(email, str) and "@" in email) or not slug:
                return
            base = self._base_url or "https://bookinvip.com"
            titolo = slug
            try:
                d = self._sys.catalogo.dettaglio(slug)
                titolo = (d.get("titolo") if isinstance(d, dict) else None) or slug
            except Exception:
                pass
            import html as _h
            if esito == "rifiutata":
                ogg = "BookinVIP - L'host non ha potuto accettare la tua richiesta"
                riga = "l'host non ha potuto accettare la tua richiesta"
            else:
                ogg = "BookinVIP - L'host non ha risposto alla tua richiesta"
                riga = "l'host non ha risposto entro 24 ore alla tua richiesta"
            corpo = ("<div style=\"font-family:sans-serif;max-width:480px\">"
                     "<h2 style=\"color:#1e3c72\">La tua richiesta non è stata confermata</h2>"
                     "<p>Purtroppo %s per <strong>%s</strong> (%s → %s).</p>"
                     "<p><strong>Nessun addebito è stato effettuato</strong>: per le "
                     "richieste si paga solo dopo la conferma dell'host.</p>"
                     "<p>Le date sono di nuovo libere per te altrove:</p>"
                     "<p><a href=\"%s\" style=\"background:#1e3c72;color:#fff;"
                     "padding:.7rem 1.4rem;border-radius:8px;text-decoration:none;"
                     "font-weight:bold\">Trova un altro alloggio</a></p>"
                     "<p style=\"color:#5e6f8d;font-size:.85rem\">Questa è un'email di "
                     "servizio, non riceverai promemoria.</p></div>"
                     ) % (_h.escape(riga), _h.escape(titolo),
                          _h.escape(rec.get("check_in", "")),
                          _h.escape(rec.get("check_out", "")), _h.escape(base + "/"))
            import threading
            threading.Thread(target=ep.invia, args=(email, ogg, corpo),
                             daemon=True).start()
        except Exception:
            logger.warning("email esito richiesta fallita (ISOLATA)", exc_info=True)

    def _email_recupero_hold(self, rec):
        """RECUPERO prenotazione fallita (hold scaduto senza pagamento): UNA email onesta al
        cliente — 'le date sono di nuovo libere, riprova' — con il link all'alloggio. NIENTE
        spam (evento transazionale, una sola volta: lo stato passa a 'scaduto' quindi il
        sweeper non ripassa). Best-effort ISOLATO: mai blocca lo sweep.
        Una RICHIESTA mai approvata ('in_attesa_host') NON e' un pagamento fallito: il
        cliente non doveva pagare niente -> email di esito richiesta, non di recupero."""
        if (rec or {}).get("stato") == "in_attesa_host":
            return self._email_esito_richiesta(rec, "scaduta")
        try:
            ep = getattr(self._sys, "email_provider", None)
            email = (rec or {}).get("email", "")
            slug = (rec or {}).get("alloggio_id", "")
            if ep is None or not (isinstance(email, str) and "@" in email) or not slug:
                return
            base = self._base_url or "https://bookinvip.com"
            url = base + "/alloggio/" + slug
            titolo = slug
            try:
                d = self._sys.catalogo.dettaglio(slug)
                titolo = (d.get("titolo") if isinstance(d, dict) else None) or slug
            except Exception:
                pass
            import html as _h
            corpo = ("<div style=\"font-family:sans-serif;max-width:480px\">"
                     "<h2 style=\"color:#1e3c72\">Il pagamento non è andato a buon fine</h2>"
                     "<p>La tua prenotazione per <strong>%s</strong> (%s → %s) non è stata "
                     "completata, quindi le date sono di nuovo <strong>libere</strong>.</p>"
                     "<p>Se le vuoi ancora, riprova subito (prima che le prenda qualcun altro):</p>"
                     "<p><a href=\"%s\" style=\"background:#1e3c72;color:#fff;padding:.7rem 1.4rem;"
                     "border-radius:8px;text-decoration:none;font-weight:bold\">Riprova ora</a></p>"
                     "<p style=\"color:#5e6f8d;font-size:.85rem\">Nessun addebito è stato "
                     "effettuato. Questa è un'email di servizio, non riceverai promemoria.</p></div>"
                     ) % (_h.escape(titolo), _h.escape(rec.get("check_in", "")),
                          _h.escape(rec.get("check_out", "")), _h.escape(url))
            import threading
            threading.Thread(target=ep.invia,
                             args=(email, "BookinVIP - Le tue date sono di nuovo libere", corpo),
                             daemon=True).start()
        except Exception:
            logger.warning("email recupero hold fallita (ISOLATA)", exc_info=True)

    def _host_alloggio_elimina(self, body, headers):
        """L'host ELIMINA un suo annuncio sbagliato (con doppia conferma nel pannello).
        SICURO: solo il proprietario; niente eliminazione se ci sono prenotazioni FUTURE
        confermate (prima vanno annullate: mai lasciare un cliente senza stanza)."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        dati = self._json(body)
        if dati is None:
            return 400, {"errore": "json_non_valido"}
        slug = dati.get("slug")
        if not (isinstance(slug, str) and slug):
            return 422, {"errore": "slug_mancante"}
        if not self._verifica_proprieta(headers, slug):
            return 403, {"errore": "non_tuo"}
        try:
            import datetime as _dte
            oggi = _dte.date.today().isoformat()
            future = [p for p in self._sys.inventario.elenco_prenotazioni(alloggio_id=slug,
                                                                          limit=200)
                      # chiave giusta: 'rimborsato' ('rilasciato' era sempre None -> anche
                      # le prenotazioni GIA' rimborsate bloccavano l'eliminazione)
                      if not p.get("rimborsato") and str(p.get("check_out", "")) >= oggi]
            if future:
                return 409, {"errore": "prenotazioni_attive", "quante": len(future)}
            # ANCHE un soggiorno GIA' PASSATO puo' avere l'escrow ancora aperto (in attesa
            # del rilascio automatico, o contestato): cancellare l'alloggio lascerebbe i
            # soldi dell'ospite in una riga orfana. Il controllo sulle prenotazioni future
            # non lo vedeva -> era un buco dell'audit del 2026-07-22.
            gar = getattr(self._sys, "garanzia", None)
            if gar is not None and hasattr(gar, "aperte_per_alloggio"):
                aperte = int(gar.aperte_per_alloggio(slug) or 0)
                if aperte:
                    return 409, {"errore": "escrow_aperto", "quanti": aperte}
            ok = self._sys.catalogo.elimina_alloggio(slug)
        except Exception:
            logger.error("elimina alloggio: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        return (200, {"stato": "eliminato", "slug": slug}) if ok else \
               (404, {"errore": "non_trovato"})

    def _host_metriche_avanzate(self, headers):
        """KPI avanzati dell'host (fase115, puro): calcolati sulle SUE prenotazioni reali
        (tutti i suoi alloggi). Host dal token."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        hid = self._host_id_da_token(headers)
        if not hid:
            return 422, {"errore": "host_id_mancante"}
        try:
            from fase115_dashboard_metriche import calcola_metriche
            pren = []
            for al in self._sys.catalogo.alloggi_host(hid, limit=200):
                slug = al.get("slug") if isinstance(al, dict) else None
                if not slug:
                    continue
                voti = self._voti_per_riferimento(slug)      # rif -> voto (recensioni verificate)
                for p in self._sys.inventario.elenco_prenotazioni(alloggio_id=slug, limit=500):
                    self._arricchisci_metrica(p, voti)        # aggiunge prezzo/valuta/voto (mancanti)
                    pren.append(p)
            # NON sommare valute diverse (¥ + € = numero senza senso): metriche PER valuta.
            valute = sorted({(p.get("valuta") or "EUR") for p in pren}) or ["EUR"]
            if len(valute) <= 1:
                return 200, {"metriche": calcola_metriche(pren), "valuta": valute[0],
                             "prenotazioni": len(pren)}
            per = {v: calcola_metriche([p for p in pren if (p.get("valuta") or "EUR") == v])
                   for v in valute}
            dom = max(per, key=lambda v: per[v].get("notti_vendute", 0))   # dominante nel riquadro
            m = dict(per[dom]); m["valuta"] = dom
            return 200, {"metriche": m, "metriche_per_valuta": per, "prenotazioni": len(pren)}
        except Exception:
            logger.error("metriche avanzate: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}

    def _voti_per_riferimento(self, slug):
        """Mappa riferimento -> voto delle recensioni verificate di un alloggio (per il rating)."""
        out: Dict[str, int] = {}
        r = getattr(self._sys, "recensioni", None)
        if r is None:
            return out
        try:
            for rr in (r.elenco(slug, 500) or []):
                rif = rr.get("prenotazione_id")
                if isinstance(rif, str) and rif:
                    out[rif] = rr.get("voto")
        except Exception:
            pass
        return out

    def _arricchisci_metrica(self, p, voti):
        """`elenco_prenotazioni` (dai movimenti) NON porta prezzo/valuta/voto -> senza questi le
        metriche fase115 (revenue/ADR/RevPAR/rating) erano SEMPRE 0 (bug provato: dashboard host
        mostrava incasso €0 con prenotazioni reali). Qui si arricchisce dal pendente PAGATO e dalle
        recensioni. Prezzo solo se 'pagato' (un hold non pagato non e' revenue). Isolato."""
        try:
            # RE-BLOCCO TARDIVO: dopo un pagamento in ritardo la chiave attiva del blocco e'
            # 'reblock:<rif>' (stesso caso gia' gestito in _host_prenotazioni). Senza togliere
            # il prefisso, `pp.info` non trova il pendente e quella prenotazione PAGATA valeva
            # ZERO in revenue/ADR/RevPAR del pannello host: un numero SBAGLIATO, non mancante.
            _idem = str(p.get("idem_key", ""))
            rif = _idem[len("reblock:"):] if _idem.startswith("reblock:") else _idem[:24]
            pp = getattr(self._sys, "pagamenti_pendenti", None)
            rec = pp.info(rif) if (pp is not None and rif) else None
            if rec is not None and rec.get("stato") == "pagato":
                import json as _j
                try:
                    cj = _j.loads(rec.get("corpo_json") or "{}")
                except Exception:
                    cj = {}
                p["prezzo_guest_cents"] = cj.get("prezzo_guest_cents", 0)
                p["valuta"] = cj.get("valuta") or "EUR"
            else:
                p["prezzo_guest_cents"] = 0        # non pagata -> niente revenue
            if rif in voti:
                p["voto"] = voti[rif]
        except Exception:
            logger.warning("arricchimento metrica fallito (ISOLATO)", exc_info=True)

    @staticmethod
    def _errore_range_notti(da, a):
        """UN SOLO CONTRATTO per i due campi data (`da`, `a`) di TUTTE le rotte che parlano
        di NOTTI: intervallo semi-aperto [da, a), massimo 366 notti — identico a
        POST /api/host/disponibilita_range e a `fase58.notti`. Ritorna il nome dell'errore
        (stesso vocabolario della POST) oppure None se il range e' buono.

        Prima le LETTURE non validavano nulla: un range assurdo (a<=da, data non ISO, oltre
        366 giorni) usciva **200 con la lista VUOTA**, e il pannello host mostrava "0 giorni"
        come se il calendario fosse vuoto invece di dire che le date erano sbagliate — mentre
        la SCRITTURA, con gli STESSI due campi, rispondeva 422 spiegando il motivo."""
        import datetime as _dtr
        try:
            d0 = _dtr.date.fromisoformat(da)
            d1 = _dtr.date.fromisoformat(a)
        except (ValueError, TypeError, AttributeError):
            return "date_non_valide"
        n = (d1 - d0).days
        if n <= 0 or n > 366:
            return "intervallo_non_valido"
        return None

    def _host_calendario(self, query, headers):
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        alloggio = query.get("alloggio")
        da, a = query.get("da"), query.get("a")
        if not (isinstance(alloggio, str) and alloggio and isinstance(da, str)
                and isinstance(a, str)):
            return 422, {"errore": "campi_non_validi"}
        # ISOLAMENTO (stesso IDOR): il calendario di un annuncio e' visibile solo al proprietario
        # (senza, un host spiava disponibilita'/occupazione di un rivale con lo slug).
        if not self._verifica_proprieta(headers, alloggio):
            return 403, {"errore": "non_tuo"}
        err = self._errore_range_notti(da, a)      # stesso contratto della POST (vedi sopra)
        if err:
            return 422, {"errore": err}
        try:
            cal = self._cal_arricchito(alloggio, da, a)
        except Exception:
            logger.error("host calendario: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        return 200, {"giorni": cal}

    def _host_calendario_tutti(self, query, headers):
        """VISTA D'INSIEME multi-alloggio: per OGNI alloggio dell'host, il suo calendario
        (colori) nel range. Con 10 alloggi l'host vede a colpo d'occhio QUALE è occupato in
        che data — griglia stile channel-manager. Solo i propri (host dal token)."""
        if not self._auth_host(headers):
            return 401, {"errore": "unauthorized"}
        hid = self._host_id_da_token(headers) or query.get("host_id")
        if not (isinstance(hid, str) and hid):
            return 422, {"errore": "host_id_mancante"}
        da, a = query.get("da"), query.get("a")
        if not (isinstance(da, str) and da and isinstance(a, str) and a):
            return 422, {"errore": "date_mancanti"}
        err = self._errore_range_notti(da, a)      # stesso contratto [da, a) delle altre rotte
        if err:
            return 422, {"errore": err}
        try:
            listings = self._sys.catalogo.alloggi_host(hid, limit=200)
            slugs = [al.get("slug") for al in listings
                     if isinstance(al, dict) and al.get("slug")]
            # BATCH: gli hold vivi di TUTTI gli alloggi in UNA query (prima: 1 per slug ->
            # N+1). La mappa passata a _cal_arricchito azzera le query per-slug degli hold.
            pp = getattr(self._sys, "pagamenti_pendenti", None)
            hold_map = pp.attivi_multi(slugs) \
                if (pp is not None and callable(getattr(pp, "attivi_multi", None))) else None
            out = []
            for al in listings:
                slug = al.get("slug") if isinstance(al, dict) else None
                if not slug:
                    continue
                out.append({"slug": slug,
                            "titolo": (al.get("titolo") if isinstance(al, dict) else None) or slug,
                            "giorni": self._cal_arricchito(slug, da, a, hold_prefetch=hold_map)})
        except Exception:
            logger.error("calendario tutti: eccezione ISOLATA", exc_info=True)
            return 503, {"errore": "service_unavailable"}
        return 200, {"alloggi": out}

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
        if not self._verifica_proprieta(headers, alloggio):
            return 403, {"errore": "non_tuo"}
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


def corpo_json_bytes(corpo: Any) -> bytes:
    """Serializza SEMPRE una risposta JSON in byte spedibili. PURA e testabile.

    Difetto PROVATO (2026-07-28, live su socket): un solo carattere non codificabile in UTF-8
    (surrogato isolato, es. `"\\ud800"` nel corpo di una POST pubblica) faceva alzare
    UnicodeEncodeError DENTRO `_scrivi`, PRIMA di `send_response` -> il server chiudeva la
    connessione senza spedire NEMMENO UNA RIGA di risposta (dietro nginx: 502). Nessuna rotta
    deve poter uccidere la risposta: qui i surrogati diventano il carattere di sostituzione e
    il client riceve comunque un JSON valido con lo stato giusto."""
    testo = json.dumps(corpo, ensure_ascii=False)
    try:
        return testo.encode("utf-8")
    except UnicodeEncodeError:
        # 'backslashreplace' non e' JSON-safe: si passa da surrogatepass -> decodifica
        # tollerante, cosi' il risultato resta UTF-8 valido e il JSON resta parsabile.
        return testo.encode("utf-8", "surrogatepass").decode("utf-8", "replace").encode("utf-8")


def lunghezza_corpo(valore: Any) -> int:
    """Content-Length -> intero >= 0, MAI un'eccezione. PURA e testabile.
    Difetto PROVATO (2026-07-28, live su socket): `Content-Length: abc` alzava ValueError in
    `do_POST` -> connessione chiusa senza risposta. Valore assurdo/negativo = nessun corpo."""
    try:
        n = int(str(valore).strip())
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


def corpo_richiesta_testo(grezzo: bytes) -> str:
    """Byte del corpo -> testo, MAI un'eccezione. PURA e testabile.
    Difetto PROVATO (2026-07-28, live su socket): un corpo POST con byte non-UTF8 (es. b'\\xff')
    alzava UnicodeDecodeError in `do_POST` -> connessione chiusa senza risposta. Ora i byte
    invalidi diventano U+FFFD: il JSON non si parsa -> 400 json_non_valido (errore onesto)."""
    if not isinstance(grezzo, (bytes, bytearray)):
        return ""
    return bytes(grezzo).decode("utf-8", "replace")


# ─────────────────────────────────────────────────────────────────────────────
# Server HTTP stdlib (thin wrapper, NON testato - I/O)
# ─────────────────────────────────────────────────────────────────────────────
def sweep_hold_una_passata(sistema: Any, router: Any) -> None:
    """UNA passata dello sweeper hold (estratta dal thread per essere testabile).
    ORDINE ANTI-GARA (fail-safe): prima l'ACQUISIZIONE del record col CAS
    `pp.scadi` (in_attesa->scaduto); date/garanzia/payout/email SOLO se il CAS
    riesce. Se un pagamento (o una cancellazione) ha vinto la gara un istante
    prima, il CAS fallisce e NON si tocca niente: mai liberare le date di una
    prenotazione appena pagata, mai email 'riprova' a chi ha appena pagato.
    (Se il processo cade tra CAS e rilascio, le date restano bloccate: il lato
    sicuro — zero overbooking; il pagamento tardivo le ri-blocca idempotente.)"""
    pp = getattr(sistema, "pagamenti_pendenti", None)
    inv = getattr(sistema, "inventario", None)
    gz = getattr(sistema, "garanzia", None)
    if pp is None or inv is None:
        return
    try:
        for rec in pp.scaduti():
            try:
                if not pp.scadi(rec["riferimento"]):
                    continue          # pagata/cancellata nel frattempo: non è più roba nostra
                inv.rilascia(rec["alloggio_id"], rec["check_in"], rec["check_out"],
                             idem_key=(rec.get("idem_key") or ("hold_" + rec["riferimento"])))
                if gz is not None:
                    gz.annulla(rec["riferimento"])
                # non pagato entro la scadenza -> via il payout 'in_attesa' (niente guadagno
                # fantasma). NON cancello il record: resta 'scaduto' per gestire un eventuale
                # pagamento tardivo (re-blocco/rimborso).
                _pd = getattr(sistema, "payout", None)
                if _pd is not None:
                    _pd.rimuovi(rec["riferimento"])
                # RECUPERO ONESTO (errore dei colossi = spam; noi UNA email transazionale):
                # pagamento non completato -> le date sono di nuovo libere, link per riprovare.
                router._email_recupero_hold(rec)
            except Exception:
                logger.warning("sweep hold singolo fallito (ignorato)", exc_info=True)
        try:
            pp.pulisci_vecchi()          # housekeeping: via i record scaduti vecchi (>1h)
        except Exception:
            pass
        # STANZA FANTASMA: notti occupate nell'inventario SENZA un pendente (crash fra il blocco
        # e la registrazione della prenotazione). Lo sweeper sopra non le vede: non c'e' pendente
        # da scadere. Le CHIUDE liberando le notti (rilascia idempotente). Grazia 1h -> non tocca
        # mai un checkout in corso (blocco e pendente nascono nello stesso istante).
        try:
            if hasattr(inv, "libera_orfani") and hasattr(pp, "idem_keys"):
                for _o in inv.libera_orfani(pp.idem_keys(), grazia_sec=3600):
                    logger.warning("STANZA FANTASMA chiusa: idem=%s alloggio=%s %s->%s",
                                   _o.get("idem_key"), _o.get("alloggio_id"),
                                   _o.get("check_in"), _o.get("check_out"))
        except Exception:
            logger.warning("chiusura stanze fantasma fallita (ignorata)", exc_info=True)
        # RIASSERZIONE PENALI (fase177, pattern #32): crash tra il CAS della
        # cancellazione-host e il giornale = penale annotata nel pendente ma senza
        # Nota di Debito -> qui si sana (idempotente: chi ce l'ha gia' viene saltato
        # con un lookup O(1); processa_penale replayato non tocca due volte i payout).
        try:
            fc = getattr(sistema, "finanza", None)
            if fc is not None and hasattr(pp, "cancellate_host"):
                import json as _j
                for rec in pp.cancellate_host(limit=50):
                    rif = rec.get("riferimento")
                    if not rif or fc.esiste_evento("penale:" + rif):
                        continue
                    try:
                        dj = _j.loads(rec.get("corpo_json") or "{}")
                    except Exception:
                        dj = {}
                    pen = dj.get("penale_host_cents")
                    if not (isinstance(pen, int) and pen > 0):
                        continue
                    fc.processa_penale(
                        riferimento=rif, host_id=str(rec.get("host_id") or ""),
                        penale_cents=pen, valuta=str(dj.get("valuta") or "EUR"),
                        payout=getattr(sistema, "payout", None))
                    logger.warning("riasserzione penale %s: ND emessa dallo sweeper", rif)
        except Exception:
            logger.warning("riasserzione penali fallita (ignorata)", exc_info=True)
    except Exception:
        logger.warning("sweep hold fallito (ignorato)", exc_info=True)


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
            # lingue dei post (CAMPAGNA_LINGUE="it,en"); vuoto -> default del motore (tutte).
            _lng = [x.strip() for x in os.environ.get("CAMPAGNA_LINGUE", "").split(",")
                    if x.strip()]
            _kw = {"intervallo_sec": 3600.0}
            if _lng:
                _kw["lingue"] = _lng
            sched.avvia_in_thread(**_kw)
            logging.getLogger("core_auto.server").info(
                "Scheduler campagna AVVIATO: ogni %s giorni, lingue=%s",
                _giorni, _lng or "tutte")
        except Exception:
            logging.getLogger("core_auto.server").warning(
                "Scheduler campagna NON avviato (ISOLATO)", exc_info=True)

    class Handler(BaseHTTPRequestHandler):
        # HEADER DI AUTENTICAZIONE davvero letti dal router: X-Host-Key/X-Host-Token
        # (`_auth_host`), X-Admin-Key/X-Admin-Op (`_auth_admin`), X-Bunker-Session
        # (`_bunker_auth`). DEVONO stare TUTTI in Access-Control-Allow-Headers: il preflight
        # CORS del browser autorizza SOLO gli header dichiarati qui, e un header non
        # dichiarato non viene spedito -> la richiesta cross-origin arriva SENZA credenziali
        # e torna 401. Prima erano dichiarati solo "Content-Type, X-Host-Key": ogni client
        # browser di altra origine (widget partner, pannello su altro dominio, agente AI in
        # pagina) poteva autenticarsi SOLO con la vecchia chiave d'operatore.
        # Nessun indebolimento: Allow-Origin e' "*" e Allow-Credentials NON e' impostato,
        # quindi il browser non allega mai cookie/sessioni ambientali; questi header vanno
        # scritti a mano da chi conosce gia' il segreto.
        AUTH_HEADERS = ("X-Host-Key", "X-Host-Token", "X-Admin-Key", "X-Admin-Op",
                        "X-Bunker-Session")

        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers",
                             "Content-Type, " + ", ".join(self.AUTH_HEADERS))
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

        def _cookie_secure(self):
            """Secure solo se la richiesta e' HTTPS (nginx setta X-Forwarded-Proto=https in
            prod -> sempre Secure; in locale su http resta off, cosi' il test manuale funziona)."""
            proto = (self.headers.get("X-Forwarded-Proto", "")
                     or self.headers.get("x-forwarded-proto", "")).lower()
            return "; Secure" if proto in ("", "https") else ""

        def _emetti_cookie(self, cookies):
            """Set-Cookie HttpOnly + SameSite=Lax (+ Secure in HTTPS). Max-Age=0 = cancella."""
            sec = self._cookie_secure()
            for nome, valore, max_age in cookies:
                self.send_header("Set-Cookie",
                                 "%s=%s; HttpOnly%s; SameSite=Lax; Path=/; Max-Age=%d"
                                 % (nome, valore, sec, int(max_age)))

        def _scrivi(self, status, corpo):
            cookies = None
            if isinstance(corpo, dict) and "_cookie" in corpo:
                corpo = dict(corpo)
                cookies = corpo.pop("_cookie")          # direttiva interna: non finisce nel JSON
            dati = corpo_json_bytes(corpo)   # non puo' fallire: la risposta parte SEMPRE
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            if cookies:
                self._emetti_cookie(cookies)
            self._cors()
            self.end_headers()
            if not getattr(self, '_solo_head', False):   # HEAD = header senza corpo
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
            if not getattr(self, '_solo_head', False):   # HEAD = header senza corpo
                self.wfile.write(dati)

        def _no_store(self):
            """Header anti-cache: il browser NON conserva la pagina (dopo il logout non
            riappare dalla cache/back). Requisito del gatekeeper."""
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, private")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")

        def _statico(self, path, no_store=False):
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
            if no_store:
                self._no_store()
            self._cors()
            self.end_headers()
            if not getattr(self, '_solo_head', False):   # HEAD = header senza corpo
                self.wfile.write(dati)

        # basename -> livello richiesto per le pagine RISERVATE (gatekeeper server-side)
        _PAGINE_GATED = {"admin.html": "admin", "bunker.html": "bunker", "host.html": "host"}

        def _servi_gated(self, path):
            """GATEKEEPER: serve una pagina riservata SOLO con cookie di sessione valido.
            Senza sessione: 302 al login del ruolo, NESSUN byte della dashboard spedito.
            Con sessione: serve la dashboard marcata no-store (post-logout non riappare)."""
            if os.environ.get("PAGE_GATE", "1") == "0":     # kill-switch d'emergenza
                self._statico(path, no_store=True)
                return
            base = os.path.basename(path).lower()
            livello = self._PAGINE_GATED.get(base)
            cookie = router._leggi_cookie(dict(self.headers), "bv_" + livello) if livello else ""
            if not (livello and router._gate_valida(cookie, livello)):
                # non autenticato -> la pagina, per lui, "non esiste": lo mandiamo al login
                self.send_response(302)
                self.send_header("Location", "/entra-" + (livello or "host"))
                self._no_store()
                self._cors()
                self.end_headers()
                return
            self._statico(path, no_store=True)              # autenticato: dashboard, mai cacheata

        def _testo(self, status, ctype, testo, no_store=False):
            dati = testo.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            if no_store:
                self._no_store()
            self._cors()
            self.end_headers()
            if not getattr(self, '_solo_head', False):   # HEAD = header senza corpo
                self.wfile.write(dati)

        def _testo_seo(self, status, ctype, testo, *, max_age=3600):
            """Come _testo ma con ETag + Cache-Control (CRAWL BUDGET): se il crawler rimanda l'ETag
            invariato (If-None-Match) → 304 senza corpo, non riscarica. Solo superfici PUBBLICHE
            (landing/sitemap/robots/llms)."""
            dati = testo.encode("utf-8")
            etag = etag_di(dati)
            inm = self.headers.get("If-None-Match", "") if getattr(self, "headers", None) else ""
            if status == 200 and etag_combacia(etag, inm):
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", "public, max-age=%d" % max_age)
                self._cors()
                self.end_headers()
                return
            self.send_response(status)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "public, max-age=%d" % max_age)
            self._cors()
            self.end_headers()
            if not getattr(self, '_solo_head', False):
                self.wfile.write(dati)

        def do_HEAD(self):
            """HEAD = GET ma senza corpo. Senza questo metodo BaseHTTPRequestHandler risponde
            **501 Unsupported method** a OGNI richiesta HEAD: i monitor di uptime (UptimeRobot
            e simili) usano HEAD di default -> direbbero "sito giu'" mentre il sito e' vivo
            (falso allarme). Riusa do_GET e scarta il corpo: stessi header, stesso status."""
            self._solo_head = True
            try:
                self.do_GET()
            finally:
                self._solo_head = False

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/api/bunker/marca.tsr":
                # TOKEN GREZZO della marca temporale: l'unico contenuto binario che esce.
                # E' il file che si consegna a un perito o si allega a un atto.
                qs = {k: v[0] for k, v in parse_qs(u.query).items()}
                stato, token = router.scarica_marca(qs.get("id", ""), dict(self.headers))
                if stato != 200 or not token:
                    self._scrivi(stato, {"errore": "non_disponibile"})
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/timestamp-reply")
                self.send_header("Content-Length", str(len(token)))
                self.send_header("Content-Disposition",
                                 'attachment; filename="marca_%s.tsr"'
                                 % str(qs.get("id", "")).replace('"', ""))
                self.send_header("Cache-Control", "no-store")
                self._cors()
                self.end_headers()
                if not getattr(self, "_solo_head", False):
                    self.wfile.write(token)
                return
            if u.path == "/api/bunker/export_legale":
                # DOSSIER LEGALE-FISCALE in STREAMING (zero RAM), come l'estratto contabile.
                hdrs = dict(self.headers)
                if not router.puo_esportare(hdrs):
                    self._scrivi(403, {"errore": "bunker_richiesto"})
                    return
                qs = {k: v[0] for k, v in parse_qs(u.query).items()}
                fmt = "json" if str(qs.get("formato", "")).lower() == "json" else "csv"
                self.send_response(200)
                self.send_header("Content-Type",
                                 "application/json; charset=utf-8" if fmt == "json"
                                 else "text/csv; charset=utf-8")
                self.send_header("Content-Disposition",
                                 'attachment; filename="dossier_legale_bookinvip.%s"' % fmt)
                self.send_header("Cache-Control", "no-store")
                self._cors()
                self.end_headers()
                if getattr(self, "_solo_head", False):
                    return
                try:
                    for pezzo in router.genera_dossier_legale(
                            formato=fmt, ip=router._client_ip(hdrs)):
                        self.wfile.write(pezzo.encode("utf-8"))
                except Exception:
                    # flusso interrotto: il file NON avra' la riga di chiusura -> non valido
                    logger.error("dossier legale: streaming interrotto", exc_info=True)
                return
            if u.path == "/api/bunker/export_contabile":
                # STREAMING diretto sul socket (Incremento 4.1): zero RAM, il CSV scorre
                # riga per riga dal DB al client. Auth Bunker prima di aprire il flusso.
                hdrs = dict(self.headers)
                if not router.puo_esportare(hdrs):
                    self._scrivi(403, {"errore": "bunker_richiesto"})
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition",
                                 'attachment; filename="estratto_contabile_bookinvip.csv"')
                self.send_header("Cache-Control", "no-store")
                self._cors()
                self.end_headers()
                if getattr(self, "_solo_head", False):
                    return
                try:
                    ip = router._client_ip(hdrs)
                    for pezzo in router.genera_estratto_csv(ip=ip):
                        self.wfile.write(pezzo.encode("utf-8"))
                except Exception:
                    # flusso interrotto (rete/DB): marca il file come NON valido, cosi'
                    # un download troncato non venga mai preso per buono.
                    try:
                        self.wfile.write(b"\r\n# NON CHIUSO / CORROTTO - streaming interrotto\r\n")
                    except Exception:
                        pass
                return
            if u.path == "/api/bunker/dac7_report":
                # STREAMING del report DAC7 (PII+finanziario) direttamente sul socket.
                hdrs = dict(self.headers)
                if not router.puo_dac7(hdrs):
                    self._scrivi(403, {"errore": "bunker_richiesto"})
                    return
                anno = router._anno_valido({k: v[0] for k, v in
                                            parse_qs(urlparse(self.path).query).items()}.get("anno"))
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition",
                                 'attachment; filename="dac7_report_%s.csv"' % anno)
                self.send_header("Cache-Control", "no-store")
                self._cors()
                self.end_headers()
                if getattr(self, "_solo_head", False):
                    return
                try:
                    for pezzo in router.genera_dac7_csv(anno=anno, ip=router._client_ip(hdrs)):
                        self.wfile.write(pezzo.encode("utf-8"))
                except Exception:
                    try:
                        self.wfile.write(b"\r\n# NON CHIUSO / CORROTTO - streaming interrotto\r\n")
                    except Exception:
                        pass
                return
            if u.path.startswith("/api/"):
                query = {k: v[0] for k, v in parse_qs(u.query).items()}
                s, c = router.gestisci("GET", u.path, query, None, dict(self.headers))
                self._scrivi(s, c)
            elif u.path == "/sitemap.xml":
                self._testo_seo(200, "application/xml", sitemap_xml(sistema, base_url))
            elif u.path in ("/feed.xml", "/rss", "/rss.xml"):
                self._testo_seo(200, "application/rss+xml", feed_rss_xml(sistema, base_url))
            elif u.path == "/robots.txt":
                self._testo_seo(200, "text/plain", robots_txt(base_url))
            elif u.path.startswith("/alloggio/"):
                slug = unquote(u.path[len("/alloggio/"):])
                html = pagina_alloggio_html(sistema, slug, base_url)
                if html is None:
                    self._scrivi(404, {"errore": "not_found"})
                else:
                    self._testo_seo(200, "text/html", html)
            elif u.path.startswith("/voucher/"):
                # LINGUA: nessun default cieco. Se `?lang=` manca o non la parliamo, le
                # pagine leggono la lingua FIRMATA nel gettone (catturata al book) e solo
                # come ultima spiaggia l'inglese — mai l'italiano per difetto.
                query = {k: v[0] for k, v in parse_qs(u.query).items()}
                lng = query.get("lang")
                html = pagina_voucher_html(sistema, unquote(u.path[len("/voucher/"):]), lng)
                if html is None:
                    # link non valido/scaduto -> pagina GENTILE (non un errore tecnico)
                    self._testo(404, "text/html", pagina_voucher_non_valido_html(lng))
                else:
                    self._testo(200, "text/html", html)
            elif u.path.startswith("/ricevuta/"):
                # RICEVUTA stampabile (C3): stesso token firmato del voucher, solo PAGATE
                query = {k: v[0] for k, v in parse_qs(u.query).items()}
                lng = query.get("lang")
                html = pagina_ricevuta_html(sistema, unquote(u.path[len("/ricevuta/"):]), lng)
                if html is None:
                    self._testo(404, "text/html", pagina_voucher_non_valido_html(lng))
                else:
                    self._testo(200, "text/html", html)
            elif u.path.startswith("/recensione/"):
                # SOLA VALUTAZIONE (2026-07-20): pagina pulita col SOLO voto; stesso token
                # firmato del voucher, stesso motore/endpoint. Il voucher resta intatto.
                query = {k: v[0] for k, v in parse_qs(u.query).items()}
                lng = query.get("lang")
                html = pagina_recensione_html(sistema, unquote(u.path[len("/recensione/"):]), lng)
                if html is None:
                    self._testo(404, "text/html", pagina_voucher_non_valido_html(lng))
                else:
                    self._testo(200, "text/html", html)
            elif u.path.startswith("/ical/") and u.path.endswith(".ics"):
                # feed .ics del calendario (letto da Booking/Airbnb): anti-overbooking
                ics = router._ical_export(unquote(u.path[len("/ical/"):-4]))
                if ics is None:
                    self._testo(404, "text/plain", "Not found")
                else:
                    # `_testo` aggiunge gia' "; charset=utf-8": ripeterlo qui produceva
                    # un Content-Type con il parametro DUPLICATO ("text/calendar;
                    # charset=utf-8; charset=utf-8"), malformato per RFC 9110 proprio
                    # sull'unica risposta che leggono i parser di Booking/Airbnb.
                    self._testo(200, "text/calendar", ics)
            elif u.path == "/host/azione":
                # APPROVA/RIFIUTA una richiesta da un messaggio (link firmato, un tocco).
                query = {k: v[0] for k, v in parse_qs(u.query).items()}
                esito = router._azione_richiesta(query.get("t", ""))
                self._testo(200 if esito.get("ok") else 400, "text/html",
                            pagina_azione_html(esito))
            elif u.path.startswith("/affitta/"):
                # Inbound SEO/AEO (fase97): landing host per città (server-rendered,
                # crawlabile). Solo città note → niente thin-content da slug arbitrari.
                try:
                    from fase97_inbound_seo import (citta_da_slug, genera_landing_host,
                                                    registro_citta, vicini_di)
                    query = {k: v[0] for k, v in parse_qs(u.query).items()}
                    # REGISTRO = seed curati ∪ città con inventario reale (gate anti-doorway):
                    # una città fuori dal registro → 404, mai pagina vuota da slug arbitrario.
                    registro = registro_citta(_citta_inventario(sistema))
                    citta = citta_da_slug(unquote(u.path[len("/affitta/"):]), registro)
                    if citta is None:
                        self._scrivi(404, {"errore": "citta_non_trovata"})
                    else:
                        bps = int(os.environ.get("COMMISSIONE_BPS", "1000"))
                        # SPOT VIDEO della città (gated da VIDEO_DIR): se esiste, la landing lo
                        # incorpora (player + og:video + VideoObject). ISOLATO: mai rompe la pagina.
                        v_url = v_poster = v_data = ""
                        try:
                            from fase97_inbound_seo import slug_citta, video_locale
                            vid = video_locale(slug_citta(citta))
                            if vid:
                                v_url = base_url + vid[0]
                                v_poster = (base_url + vid[1]) if vid[1] else ""
                                v_data = vid[2]
                        except Exception:
                            pass
                        # link interni = maglia small-world sul registro (non tutte le città)
                        self._testo_seo(200, "text/html", genera_landing_host(
                            citta, lingua=query.get("lang", "it"), base_url=base_url,
                            commissione_bps=bps, citta_correlate=vicini_di(citta, registro),
                            video_url=v_url, video_poster=v_poster, video_data=v_data))
                except Exception:
                    self._scrivi(500, {"errore": "interno"})
            elif u.path == "/blog" or u.path.startswith("/blog/"):
                # BLOG / GUIDA multilingua (fase198): hub di contenuti sempreverdi SEO.
                from fase198_blog import genera_articolo_html, genera_indice_blog
                query = {k: v[0] for k, v in parse_qs(u.query).items()}
                lng = query.get("lang", "it")
                slug = unquote(u.path[len("/blog/"):]).strip("/") if u.path != "/blog" else ""
                if not slug:
                    self._testo_seo(200, "text/html",
                                    genera_indice_blog(lingua=lng, base_url=base_url))
                else:
                    art = genera_articolo_html(slug, lingua=lng, base_url=base_url)
                    if art is None:
                        self._scrivi(404, {"errore": "articolo_non_trovato"})
                    else:
                        self._testo_seo(200, "text/html", art)
            elif u.path == "/sitemap-blog.xml":
                from fase198_blog import sitemap_blog
                self._testo_seo(200, "application/xml", sitemap_blog(base_url))
            elif u.path == "/llms.txt":
                from fase97_inbound_seo import llms_txt
                bps = int(os.environ.get("COMMISSIONE_BPS", "1000"))
                self._testo_seo(200, "text/plain",
                                llms_txt(base_url, commissione_bps=bps))
            elif (os.environ.get("INDEXNOW_KEY", "").strip()
                  and u.path == "/" + os.environ["INDEXNOW_KEY"].strip() + ".txt"):
                # IndexNow: file di verifica della proprietà (solo se la chiave è configurata)
                from fase169_indexnow import key_file_body
                self._testo(200, "text/plain",
                            key_file_body(os.environ["INDEXNOW_KEY"].strip()))
            elif u.path == "/.well-known/ai-plugin.json":
                self._scrivi(200, ai_plugin_manifest(base_url))   # scoperta agenti IA
            elif u.path == "/openapi.json":
                self._scrivi(200, openapi_agent_spec(base_url))   # spec per agenti non-MCP
            elif u.path.startswith("/uploads/"):
                self._serve_upload(u.path)                        # foto alloggi caricate
            elif u.path == "/sitemap-index.xml":
                # INDICE: referenzia la sitemap alloggi + le sitemap-host a SHARD (scala >50k URL)
                from fase97_inbound_seo import (registro_citta, shard_citta,
                                                sitemap_index, SEO_LASTMOD)
                reg = registro_citta(_citta_inventario(sistema))
                n_shard = len(shard_citta(reg))
                voci = [("/sitemap.xml", "")]
                voci += [("/sitemap-host-%d.xml" % i, SEO_LASTMOD) for i in range(n_shard)]
                self._testo_seo(200, "application/xml", sitemap_index(base_url, voci=voci))
            elif (u.path.startswith("/sitemap-host-") and u.path.endswith(".xml")):
                # una SHARD della sitemap landing
                from fase97_inbound_seo import (registro_citta, shard_citta, sitemap_inbound)
                reg = registro_citta(_citta_inventario(sistema))
                shards = shard_citta(reg)
                try:
                    i = int(u.path[len("/sitemap-host-"):-len(".xml")])
                except ValueError:
                    i = -1
                if 0 <= i < len(shards):
                    self._testo_seo(200, "application/xml",
                                    sitemap_inbound(base_url, citta=shards[i]))
                else:
                    self._scrivi(404, {"errore": "shard_inesistente"})
            elif u.path == "/sitemap-host.xml":
                from fase97_inbound_seo import sitemap_inbound, registro_citta
                # la sitemap elenca SOLO le città del registro (seed ∪ inventario reale)
                self._testo_seo(200, "application/xml", sitemap_inbound(
                    base_url, citta=registro_citta(_citta_inventario(sistema))))
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
            elif u.path in ("/entra-admin", "/entra-host", "/entra-bunker"):
                # PAGINA DI LOGIN pubblica: SOLO il form del ruolo, zero struttura dashboard.
                self._testo(200, "text/html",
                            pagina_login_gate(u.path[len("/entra-"):], base_url),
                            no_store=True)
            elif u.path in ("/grazie", "/annullato"):
                # PAGINE POST-PAGAMENTO Stripe (STRIPE_SUCCESS_URL/CANCEL_URL): senza estensione,
                # servono i .html. Erano un 404 -> l'ospite DOPO il pagamento vedeva pagina morta.
                self._statico(u.path + ".html")
            elif os.path.basename(u.path).lower() in ("admin.html", "bunker.html", "host.html"):
                self._servi_gated(u.path)            # GATEKEEPER server-side (cookie o 302 login)
            else:
                self._statico(u.path)

        def do_POST(self):
            u = urlparse(self.path)
            lung = lunghezza_corpo(self.headers.get("Content-Length", 0))
            body = corpo_richiesta_testo(self.rfile.read(lung)) if lung else ""
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

        # PREVENZIONE perdita: non versare l'escrow all'host se la prenotazione e' RIMBORSATA/
        # cancellata_host (il passo che chiude l'escrow nel rimborso puo' saltare in isolamento).
        # Fail-safe verso l'host: in dubbio -> non salta (rilascia). Il guardiano fase186 resta
        # la rete a valle; questa e' la prevenzione al momento esatto del rilascio.
        _pp_g = getattr(sistema, "pagamenti_pendenti", None)

        def _rimborsata(_rif):
            try:
                _i = _pp_g.info(_rif) if _pp_g is not None else None
                return bool(_i) and _i.get("stato") in ("rimborsato", "cancellata_host")
            except Exception:
                return False

        def _tick_garanzia():
            while True:
                try:
                    # 24h di silenzio = tutto ok -> rilascio + bonifico AUTOMATICO all'host
                    for _r in (gz.auto_rilascia(dettagli=True, salta_se=_rimborsata) or []):
                        try:
                            router._trasferisci_all_host(_r["prenotazione_id"],
                                                         _r["host_riceve_cents"])
                        except Exception:
                            logger.warning("transfer su auto-rilascio fallito (ignorato)",
                                           exc_info=True)
                except Exception:
                    logger.warning("auto_rilascia garanzia fallito (ignorato)", exc_info=True)
                try:
                    router._pulizia_uploads_se_ora()
                except Exception:
                    logger.warning("pulizia uploads fallita (ignorata)", exc_info=True)
                try:
                    router._riscuoti_carta_se_ora()     # Scatto ③ (gated SCATTO3_ATTIVO)
                except Exception:
                    logger.warning("sweep carta off-session fallito (ignorato)", exc_info=True)
                __import__("time").sleep(3600)
        _th.Thread(target=_tick_garanzia, daemon=True).start()

    # sweeper HOLD: libera le stanze delle prenotazioni non pagate entro la scadenza
    pp = getattr(sistema, "pagamenti_pendenti", None)
    inv = getattr(sistema, "inventario", None)
    if pp is not None and inv is not None:
        import threading as _th2

        # IL GUARDIANO (fase186): ogni giorno cerca gli STATI IMPOSSIBILI (conti che non
        # tornano con Stripe, escrow bloccati, bonifici fermi o orfani) e, se ne trova,
        # GRIDA con un'email all'amministratore. E' il paracadute che l'audit del
        # 2026-07-22 ha trovato mancante: fase182 esisteva ma era un bottone manuale.
        import threading as _thg

        def _tick_guardiano():
            import time as _tg
            while True:
                try:
                    from fase186_guardiano import scansiona, riassunto_html
                    # sonda OXR 1 volta/giorno (lo scan è read-only): così un tasso vecchio da
                    # traffico scarso non viene scambiato per "OXR giù". Isolato: mai rompe il giro.
                    try:
                        _t = getattr(sistema, "tassi", None)
                        if _t is not None:
                            _t.aggiorna()
                    except Exception:
                        pass
                    rep = scansiona(sistema)
                    if not rep.get("pulito"):
                        logger.critical("GUARDIANO: %d stato/i anomalo/i -> %s",
                                        rep.get("conta"), rep.get("anomalie"))
                        cfg = getattr(sistema, "config", None)
                        dest = (getattr(cfg, "email_alert", "")
                                or getattr(cfg, "email_mittente", "")
                                or "info@bookinvip.com")
                        prov = getattr(sistema, "email_provider", None)
                        if prov is not None and dest:
                            _thg.Thread(target=prov.invia,
                                        args=(dest, "BookinVIP - ALLARME Guardiano: stato "
                                              "anomalo rilevato", riassunto_html(rep)),
                                        daemon=True).start()
                    else:
                        logger.info("GUARDIANO: nessuno stato anomalo (tutto quadra)")
                    # IL BATTITO (dead man's switch), in fondo e SOLO se il giro e' arrivato
                    # fin qui: se `scansiona` esplode, l'except qui sotto prende il controllo
                    # e il battito NON viene lasciato. Cosi' `watchdog.sh` -- che gira ogni
                    # 10 minuti sul VPS e grida su Telegram -- se ne accorge entro 25 ore
                    # invece che MAI. Prima un Guardiano morto in silenzio era
                    # indistinguibile da un Guardiano che non trova niente: i log tacevano
                    # in tutti e due i casi, e il silenzio somiglia alla pace.
                    try:
                        import os as _osb
                        from fase178_watchdog import segna_battito_guardiano
                        _dbf = getattr(getattr(sistema, "config", None), "db_finanza", "") or ""
                        segna_battito_guardiano(_osb.path.dirname(_dbf))
                    except Exception:
                        # ISOLATO: un battito non lasciato non deve mai fermare il Guardiano.
                        # E sbaglia dalla parte giusta -- al massimo il watchdog grida, cioe'
                        # dice «non so se sta girando», che in quel momento e' la verita'.
                        logger.error("guardiano: battito non lasciato (ISOLATO)", exc_info=True)
                except Exception:
                    logger.error("guardiano: giro fallito (thread TENUTO VIVO)", exc_info=True)
                _tg.sleep(86400)                       # una volta al giorno
        _thg.Thread(target=_tick_guardiano, daemon=True).start()

        def _tick_hold():
            while True:
                # try/except NEL CICLO come gli altri due tick (garanzia/promemoria): qui
                # mancava. Oggi non e' un bug attivo — `sweep_hold_una_passata` si protegge da
                # sola — ma e' una fragilita': se un domani una modifica solleva fuori dai suoi
                # try interni, questo thread (daemon, nessuno lo riavvia) MUORE IN SILENZIO ->
                # gli hold non scadono piu' -> le stanze restano bloccate PER SEMPRE mentre il
                # sito sembra funzionare. E' il guasto silenzioso peggiore del money-path.
                try:
                    sweep_hold_una_passata(sistema, router)
                except Exception:
                    logger.error("sweep hold: giro fallito (thread TENUTO VIVO)", exc_info=True)
                __import__("time").sleep(120)
        _th2.Thread(target=_tick_hold, daemon=True).start()

    # PROMEMORIA post-check-in al cliente ('tutto ok? / segnala un problema entro 24h'):
    # aumenta la fiducia e dà al cliente il momento chiaro per agire prima dell'auto-rilascio.
    email_prov = getattr(sistema, "email_provider", None)
    if pp is not None and email_prov is not None:
        import threading as _th3, datetime as _dt3, json as _j3

        def _tick_promemoria():
            base = getattr(getattr(sistema, "config", None), "base_url", "") or "https://bookinvip.com"
            while True:
                try:
                    oggi = _dt3.date.today().isoformat()
                    for rec in pp.da_promemoriare(oggi=oggi):
                        try:
                            dj = _j3.loads(rec.get("corpo_json") or "{}")
                        except Exception:
                            dj = {}
                        vt = dj.get("voucher_token", "")
                        lang = router._lang_da_voucher(vt)
                        vurl = (base + "/voucher/" + vt + "?lang=" + lang) if vt else ""
                        titolo = dj.get("titolo") or rec.get("alloggio_id", "")
                        try:
                            from fase86_email import corpo_promemoria_checkin_html, oggetto
                            html = corpo_promemoria_checkin_html(titolo, vurl, lingua=lang)
                            email_prov.invia(rec.get("email", ""),
                                             oggetto("pr_ogg", lang), html)
                        except Exception:
                            logger.warning("invio promemoria fallito (ignorato)", exc_info=True)
                        pp.segna_promemoria(rec["riferimento"])
                except Exception:
                    logger.warning("sweep promemoria fallito (ignorato)", exc_info=True)
                __import__("time").sleep(3600)     # ogni ora
        _th3.Thread(target=_tick_promemoria, daemon=True).start()

        def _tick_invito_recensione():
            """C3: post-CHECK-OUT parte l'invito a recensire (stile Booking). Senza invito
            il motore recensioni resta a secco. Finestra 14gg, una sola volta per rif."""
            base = getattr(getattr(sistema, "config", None), "base_url", "") or "https://bookinvip.com"
            while True:
                try:
                    oggi = _dt3.date.today().isoformat()
                    for rec in pp.da_invitare_recensione(oggi=oggi):
                        try:
                            dj = _j3.loads(rec.get("corpo_json") or "{}")
                        except Exception:
                            dj = {}
                        vt = dj.get("voucher_token", "")
                        lang = router._lang_da_voucher(vt)
                        # RICOLLEGATO ALLA PAGINA DI SOLA VALUTAZIONE (2026-07-20): l'invito
                        # post-soggiorno porta a /recensione/ (solo il voto), NON al voucher
                        # pieno. Stesso token firmato, stesso motore: cambia solo la vetrina.
                        vurl = (base + "/recensione/" + vt + "?lang=" + lang) if vt else ""
                        titolo = dj.get("titolo") or rec.get("alloggio_id", "")
                        try:
                            from fase86_email import corpo_invito_recensione_html, oggetto
                            email_prov.invia(rec.get("email", ""),
                                             oggetto("r_ogg", lang),
                                             corpo_invito_recensione_html(titolo, vurl,
                                                                          lingua=lang))
                        except Exception:
                            logger.warning("invio invito recensione fallito (ignorato)",
                                           exc_info=True)
                        pp.segna_invito_recensione(rec["riferimento"])
                except Exception:
                    logger.warning("sweep invito recensione fallito (ignorato)", exc_info=True)
                __import__("time").sleep(3600)     # ogni ora
        _th3.Thread(target=_tick_invito_recensione, daemon=True).start()

    # ── MARCA TEMPORALE (fase184) — indipendente da tutto il resto ──────────────
    # DIFETTO CHIUSO 2026-07-21, trovato avviando main_casavip.py per davvero: questo
    # giro stava dentro il blocco `if pp is not None and email_prov is not None`, cioe'
    # partiva SOLO con SMTP configurato. In produzione SMTP c'e', quindi avrebbe
    # funzionato — ma il giorno in cui l'email si guasta le prove legali smetterebbero
    # di essere datate da un terzo IN SILENZIO. Datare i registri non ha niente a che
    # vedere con l'invio delle email: qui dipende solo da se stesso.
    _marche = getattr(sistema, "marche", None)
    if _marche is not None:
        import threading as _th4

        def _tick_marca_temporale():
            """Una volta al giorno riduce i registri (accettazioni + giornale) a una
            impronta e la fa datare da un'Autorita' ESTERNA (RFC 3161). Toglie l'ultima
            obiezione possibile — *"l'ora dei vostri registri ve la siete scritta voi"*.
            Idempotente sul giorno; se la rete o la TSA non rispondono, archivia il
            tentativo e riprova al giro dopo, senza fermare nulla."""
            from fase184_marca_temporale import marca_i_registri
            while True:
                try:
                    marca_i_registri(_marche,
                                     accettazioni=getattr(sistema, "accettazioni", None),
                                     finanza=getattr(sistema, "finanza", None))
                except Exception:
                    logger.warning("marca temporale: giro saltato (ignorato)",
                                   exc_info=True)
                __import__("time").sleep(3600)   # ogni ora, ma marca una volta al giorno
        _th4.Thread(target=_tick_marca_temporale, daemon=True).start()

    srv.serve_forever()
