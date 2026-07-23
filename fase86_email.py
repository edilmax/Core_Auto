"""
CORE_AUTO - Fase 86: Provider Email (voucher all'ospite via SMTP) + TESTI LOCALIZZATI.

Gemello di fase85 (Stripe): l'invio email era un'astrazione mai cablata. Questo modulo la
riempie con SMTP a ZERO dipendenze (smtplib + email.mime, stdlib - niente librerie di
terze parti). E' GATED dalla configurazione: senza host/credenziali SMTP il sistema non
invia nulla (come oggi); appena metti SMTP_HOST/SMTP_USER/SMTP_PASSWORD, ogni prenotazione
confermata manda all'ospite il voucher (con il link e la chiave di self check-in) - SENZA
toccare il codice.

L'invio e' ISOLATO: se l'SMTP e' giu', `invia` ritorna False e la prenotazione resta
valida (l'email e' best-effort, mai blocca l'incasso). Compone con fase83 (book) e il
voucher firmato (fase81/firma).

LOCALIZZAZIONE TOTALE (2026-07-22): tutte le email dell'ospite e dell'host escono nella
lingua dell'utente (8 lingue: it/en/es/fr/de/pt/ja/zh). La lingua viaggia gia' nel gettone
firmato del voucher e nel record della prenotazione. NESSUN ripiego implicito in italiano:
una lingua non prevista ricade sull'INGLESE, mai sull'italiano (un mercato mondiale non
puo' dire «non lo so» = «italiano»). Gli importi passano solo da `_soldi` (fase99), che
rispetta i decimali della valuta (¥54.000, non 540.00).

VINCITRICE DEL BENCHMARK (4 modi di mandare le email):
  V3 'provider iniettato gated da env + smtplib stdlib isolato'. Zero dipendenze,
  accensione senza modifiche, fail-safe.

RETRY ANTI-SINGHIOZZO (collaudo 2026-07-15): un errore di RETE viene ritentato UNA volta
con connessione fresca; un False "pulito" del provider NON viene ritentato.
"""
from __future__ import annotations

import html as _html
import logging
import time
from typing import Any, Callable, Optional

logger = logging.getLogger("core_auto.email")


class ProviderEmail:
    """Invia email via SMTP. `send(destinatario, oggetto, html) -> bool` e' iniettabile
    (default: smtplib reale) per testare senza un server SMTP. `sleep` iniettabile per
    testare il retry senza attese reali."""

    def __init__(self, host: str, port: int, user: str, password: str, mittente: str, *,
                 send: Optional[Callable[[str, str, str], bool]] = None,
                 tentativi: int = 2, pausa_s: float = 1.5,
                 sleep: Optional[Callable[[float], None]] = None) -> None:
        self._host = host
        self._port = port if isinstance(port, int) and not isinstance(port, bool) else 587
        self._user = user
        self._password = password
        self._mittente = mittente or user
        self._send = send or self._send_smtp
        ok_int = isinstance(tentativi, int) and not isinstance(tentativi, bool)
        self._tentativi = max(1, tentativi) if ok_int else 2
        self._pausa_s = pausa_s
        self._sleep = sleep or time.sleep

    def invia(self, destinatario: Any, oggetto: str, corpo_html: str) -> bool:
        """Invia una email. Best-effort: ritorna True/False, non solleva MAI.
        Errore di rete (eccezione) -> UN retry con connessione fresca; False pulito
        del provider -> nessun retry (il server ha gia' risposto)."""
        if not (isinstance(destinatario, str) and "@" in destinatario):
            return False
        # ANTI HEADER-INJECTION (choke-point unico, vale per OGNI provider): un a-capo
        # dentro destinatario/oggetto finirebbe negli header SMTP (es. "\r\nBcc: ...") ->
        # posta di massa dal nostro dominio -> blacklist. Il soggetto puo' contenere testo
        # scritto dall'host (titolo annuncio): qualunque whitespace collassa in spazio.
        destinatario = destinatario.strip()
        if "\r" in destinatario or "\n" in destinatario:
            logger.warning("Email: destinatario con a-capo RIFIUTATO (header injection)")
            return False
        oggetto = " ".join(str(oggetto).split())
        for tentativo in range(1, self._tentativi + 1):
            try:
                return bool(self._send(destinatario, oggetto, str(corpo_html)))
            except Exception:
                logger.warning("Email: invio fallito (tentativo %d/%d, ISOLATO)",
                               tentativo, self._tentativi, exc_info=True)
                if tentativo < self._tentativi:
                    try:
                        self._sleep(self._pausa_s)
                    except Exception:
                        pass  # perfino uno sleep rotto non deve far sollevare `invia`
        return False

    def _send_smtp(self, destinatario: str, oggetto: str,
                   html: str) -> bool:  # pragma: no cover
        import smtplib
        from email.mime.text import MIMEText
        msg = MIMEText(html, "html", "utf-8")
        msg["Subject"] = oggetto
        msg["From"] = self._mittente
        msg["To"] = destinatario
        # Porta 465 = SSL IMPLICITO (SMTPS) -> serve SMTP_SSL (con SMTP normale la connessione
        # appende fino al timeout). Porta 587/25 = SMTP + STARTTLS. Timeout corto: mai bloccare.
        if int(self._port) == 465:
            with smtplib.SMTP_SSL(self._host, self._port, timeout=10) as s:
                if self._user:
                    s.login(self._user, self._password)
                s.sendmail(self._mittente, [destinatario], msg.as_string())
        else:
            with smtplib.SMTP(self._host, self._port, timeout=10) as s:
                try:
                    s.starttls()
                except smtplib.SMTPException:
                    pass
                if self._user:
                    s.login(self._user, self._password)
                s.sendmail(self._mittente, [destinatario], msg.as_string())
        return True


def crea_provider_email(host: Optional[str], port: int = 587, user: str = "",
                        password: str = "", mittente: str = "", *,
                        send: Any = None) -> Optional[ProviderEmail]:
    """Factory GATED: provider solo se c'e' un host SMTP; altrimenti None (niente email)."""
    if not (isinstance(host, str) and host.strip()):
        return None
    return ProviderEmail(host.strip(), port, user, password, mittente or user, send=send)


# ═══════════════════════════════════════════════════════════════════════════════════
#  LOCALIZZAZIONE — tutte le email in 8 lingue. Ripiego su INGLESE, mai su italiano.
# ═══════════════════════════════════════════════════════════════════════════════════
LINGUE = ("it", "en", "es", "fr", "de", "pt", "ja", "zh")


def _lingua(l: Any) -> str:
    """La lingua da usare: quella chiesta se supportata, altrimenti INGLESE. Mai italiano
    per difetto — su un mercato mondiale «non lo so» non puo' voler dire «italiano»."""
    s = str(l or "").strip().lower()[:2]
    return s if s in LINGUE else "en"


# chiave semantica -> testo per lingua. Ogni chiave ha tutte e 8 le lingue.
_TR = {
    # --- email 'preventivo' (recupero hold): etichette righe + oggetto, 8 lingue ---
    "prev_sogg": {"it": "Soggiorno", "en": "Stay", "es": "Estancia", "fr": "Séjour",
                  "de": "Aufenthalt", "pt": "Estadia", "ja": "滞在", "zh": "住宿"},
    "prev_notti": {"it": "notti", "en": "nights", "es": "noches", "fr": "nuits",
                   "de": "Nächte", "pt": "noites", "ja": "泊", "zh": "晚"},
    "prev_tassa": {"it": "Tassa di soggiorno", "en": "Tourist tax", "es": "Tasa turística",
                   "fr": "Taxe de séjour", "de": "Kurtaxe", "pt": "Taxa de turismo",
                   "ja": "宿泊税", "zh": "旅游税"},
    "prev_totale": {"it": "Totale", "en": "Total", "es": "Total", "fr": "Total",
                    "de": "Gesamt", "pt": "Total", "ja": "合計", "zh": "总计"},
    "prev_ogg": {"it": "BookinVIP - Il tuo preventivo per %s",
                 "en": "BookinVIP - Your quote for %s",
                 "es": "BookinVIP - Tu presupuesto para %s",
                 "fr": "BookinVIP - Votre devis pour %s",
                 "de": "BookinVIP - Ihr Angebot für %s",
                 "pt": "BookinVIP - O teu orçamento para %s",
                 "ja": "BookinVIP - %s のお見積り", "zh": "BookinVIP - %s 的报价"},
    # --- voucher / conferma prenotazione ---
    "v_apri": {"it": "Apri il tuo voucher", "en": "Open your voucher",
               "es": "Abre tu bono", "fr": "Ouvrir votre bon",
               "de": "Gutschein öffnen", "pt": "Abre o teu voucher",
               "ja": "バウチャーを開く", "zh": "打开您的凭证"},
    "v_ogg_conf": {"it": "BookinVIP - Prenotazione confermata",
                   "en": "BookinVIP - Booking confirmed",
                   "es": "BookinVIP - Reserva confirmada",
                   "fr": "BookinVIP - Réservation confirmée",
                   "de": "BookinVIP - Buchung bestätigt",
                   "pt": "BookinVIP - Reserva confirmada",
                   "ja": "BookinVIP - ご予約確定", "zh": "BookinVIP - 预订已确认"},
    "v_ogg_pay": {"it": "BookinVIP - Approvata! Completa il pagamento",
                  "en": "BookinVIP - Approved! Complete the payment",
                  "es": "BookinVIP - ¡Aprobada! Completa el pago",
                  "fr": "BookinVIP - Approuvée ! Finalisez le paiement",
                  "de": "BookinVIP - Genehmigt! Zahlung abschließen",
                  "pt": "BookinVIP - Aprovada! Conclui o pagamento",
                  "ja": "BookinVIP - 承認されました！お支払いを完了してください",
                  "zh": "BookinVIP - 已批准！请完成付款"},
    "v_riservata": {"it": "La tua prenotazione è stata <strong>approvata e riservata</strong>: completa il pagamento per confermarla.",
                    "en": "Your booking has been <strong>approved and reserved</strong>: complete the payment to confirm it.",
                    "es": "Tu reserva ha sido <strong>aprobada y reservada</strong>: completa el pago para confirmarla.",
                    "fr": "Votre réservation a été <strong>approuvée et réservée</strong> : finalisez le paiement pour la confirmer.",
                    "de": "Ihre Buchung wurde <strong>genehmigt und reserviert</strong>: schließen Sie die Zahlung ab, um sie zu bestätigen.",
                    "pt": "A tua reserva foi <strong>aprovada e reservada</strong>: conclui o pagamento para a confirmar.",
                    "ja": "ご予約は<strong>承認され確保されました</strong>。お支払いを完了して確定してください。",
                    "zh": "您的预订已<strong>获批准并保留</strong>：请完成付款以确认。"},
    "v_completa_pay": {"it": "Completa il pagamento", "en": "Complete the payment",
                       "es": "Completar el pago", "fr": "Finaliser le paiement",
                       "de": "Zahlung abschließen", "pt": "Concluir o pagamento",
                       "ja": "お支払いを完了する", "zh": "完成付款"},
    "v_codice": {"it": "Codice prenotazione", "en": "Booking code",
                 "es": "Código de reserva", "fr": "Code de réservation",
                 "de": "Buchungscode", "pt": "Código de reserva",
                 "ja": "予約コード", "zh": "预订码"},
    "v_pin": {"it": "PIN check-in", "en": "Check-in PIN", "es": "PIN de entrada",
              "fr": "PIN d'arrivée", "de": "Check-in-PIN", "pt": "PIN de check-in",
              "ja": "チェックインPIN", "zh": "入住 PIN"},
    "v_dal_al": {"it": "Dal %s al %s", "en": "From %s to %s", "es": "Del %s al %s",
                 "fr": "Du %s au %s", "de": "Vom %s bis %s", "pt": "De %s a %s",
                 "ja": "%s から %s まで", "zh": "%s 至 %s"},
    "v_conserva": {"it": "Conserva questa email: mostra il codice (e il PIN) all'arrivo. Dal voucher puoi vedere o annullare la prenotazione.",
                   "en": "Keep this email: show the code (and PIN) on arrival. From the voucher you can view or cancel the booking.",
                   "es": "Guarda este correo: muestra el código (y el PIN) al llegar. Desde el bono puedes ver o anular la reserva.",
                   "fr": "Conservez cet e-mail : présentez le code (et le PIN) à l'arrivée. Depuis le bon, vous pouvez voir ou annuler la réservation.",
                   "de": "Bewahren Sie diese E-Mail auf: Zeigen Sie den Code (und die PIN) bei der Ankunft. Über den Gutschein können Sie die Buchung ansehen oder stornieren.",
                   "pt": "Guarda este e-mail: mostra o código (e o PIN) à chegada. A partir do voucher podes ver ou anular a reserva.",
                   "ja": "このメールを保管してください。到着時にコード（とPIN）をご提示ください。バウチャーから予約の確認・取消ができます。",
                   "zh": "请保留此邮件：抵达时出示预订码（及 PIN）。您可从凭证查看或取消预订。"},
    # --- pagamento confermato ---
    "pc_titolo": {"it": "✅ Pagamento ricevuto", "en": "✅ Payment received",
                  "es": "✅ Pago recibido", "fr": "✅ Paiement reçu",
                  "de": "✅ Zahlung erhalten", "pt": "✅ Pagamento recebido",
                  "ja": "✅ お支払いを受け付けました", "zh": "✅ 已收到付款"},
    "pc_ogg": {"it": "BookinVIP - Pagamento ricevuto", "en": "BookinVIP - Payment received",
               "es": "BookinVIP - Pago recibido", "fr": "BookinVIP - Paiement reçu",
               "de": "BookinVIP - Zahlung erhalten", "pt": "BookinVIP - Pagamento recebido",
               "ja": "BookinVIP - お支払い受領", "zh": "BookinVIP - 已收到付款"},
    "pc_importo": {"it": "Importo pagato", "en": "Amount paid", "es": "Importe pagado",
                   "fr": "Montant payé", "de": "Gezahlter Betrag", "pt": "Valor pago",
                   "ja": "お支払い金額", "zh": "已付金额"},
    "pc_saldo": {"it": "Saldo da pagare in struttura all'arrivo:", "en": "Balance to pay at the property on arrival:",
                 "es": "Saldo a pagar en el alojamiento a la llegada:", "fr": "Solde à payer sur place à l'arrivée :",
                 "de": "Restbetrag bei Ankunft vor Ort zu zahlen:", "pt": "Saldo a pagar no alojamento à chegada:",
                 "ja": "到着時に現地でお支払いいただく残額：", "zh": "抵达时在住处支付的余款："},
    "pc_ok": {"it": "Il pagamento per <strong>%s</strong> è andato a buon fine: la prenotazione è confermata.",
              "en": "The payment for <strong>%s</strong> was successful: your booking is confirmed.",
              "es": "El pago de <strong>%s</strong> se ha realizado: tu reserva está confirmada.",
              "fr": "Le paiement pour <strong>%s</strong> a réussi : votre réservation est confirmée.",
              "de": "Die Zahlung für <strong>%s</strong> war erfolgreich: Ihre Buchung ist bestätigt.",
              "pt": "O pagamento de <strong>%s</strong> foi efetuado: a tua reserva está confirmada.",
              "ja": "<strong>%s</strong> のお支払いが完了しました。ご予約は確定です。",
              "zh": "<strong>%s</strong> 的付款已成功：您的预订已确认。"},
    "pc_nota": {"it": "Nel voucher trovi PIN di check-in, chat con l'host e la ricevuta. Conserva questa email.",
                "en": "In the voucher you'll find the check-in PIN, chat with the host and the receipt. Keep this email.",
                "es": "En el bono encontrarás el PIN de entrada, el chat con el anfitrión y el recibo. Guarda este correo.",
                "fr": "Dans le bon, vous trouverez le PIN d'arrivée, la messagerie avec l'hôte et le reçu. Conservez cet e-mail.",
                "de": "Im Gutschein finden Sie die Check-in-PIN, den Chat mit dem Gastgeber und den Beleg. Bewahren Sie diese E-Mail auf.",
                "pt": "No voucher encontras o PIN de check-in, o chat com o anfitrião e o recibo. Guarda este e-mail.",
                "ja": "バウチャーにはチェックインPIN、ホストとのチャット、領収書があります。このメールを保管してください。",
                "zh": "凭证中包含入住 PIN、与房东的聊天和收据。请保留此邮件。"},
    # --- cancellazione ---
    "c_titolo": {"it": "Prenotazione cancellata", "en": "Booking cancelled",
                 "es": "Reserva anulada", "fr": "Réservation annulée",
                 "de": "Buchung storniert", "pt": "Reserva cancelada",
                 "ja": "予約をキャンセルしました", "zh": "预订已取消"},
    "c_ogg": {"it": "BookinVIP - Cancellazione confermata", "en": "BookinVIP - Booking cancelled",
              "es": "BookinVIP - Reserva anulada", "fr": "BookinVIP - Réservation annulée",
              "de": "BookinVIP - Buchung storniert", "pt": "BookinVIP - Reserva cancelada",
              "ja": "BookinVIP - 予約キャンセル", "zh": "BookinVIP - 预订已取消"},
    "c_rimborso": {"it": "Rimborso: <strong>%s</strong> sul metodo di pagamento originale (tempi bancari: di norma 5-10 giorni lavorativi).",
                   "en": "Refund: <strong>%s</strong> to your original payment method (bank times: usually 5-10 business days).",
                   "es": "Reembolso: <strong>%s</strong> a tu método de pago original (plazos bancarios: normalmente 5-10 días hábiles).",
                   "fr": "Remboursement : <strong>%s</strong> sur votre moyen de paiement d'origine (délais bancaires : en général 5 à 10 jours ouvrés).",
                   "de": "Erstattung: <strong>%s</strong> auf Ihr ursprüngliches Zahlungsmittel (Banklaufzeiten: in der Regel 5-10 Werktage).",
                   "pt": "Reembolso: <strong>%s</strong> no método de pagamento original (prazos bancários: normalmente 5-10 dias úteis).",
                   "ja": "返金: 元のお支払い方法へ <strong>%s</strong>（銀行処理: 通常5〜10営業日）。",
                   "zh": "退款：<strong>%s</strong> 退回原支付方式（银行处理：通常 5-10 个工作日）。"},
    "c_no_rimborso": {"it": "Per la politica di cancellazione scelta non è previsto rimborso.",
                      "en": "No refund is due under the chosen cancellation policy.",
                      "es": "Según la política de cancelación elegida no hay reembolso.",
                      "fr": "Aucun remboursement n'est prévu selon la politique d'annulation choisie.",
                      "de": "Nach der gewählten Stornobedingung ist keine Erstattung vorgesehen.",
                      "pt": "Segundo a política de cancelamento escolhida não há reembolso.",
                      "ja": "選択されたキャンセルポリシーでは返金はありません。",
                      "zh": "根据所选的取消政策，不予退款。"},
    "c_credito": {"it": "🎁 In più hai un <strong>Credito Viaggio di %s</strong> per la prossima prenotazione.",
                  "en": "🎁 Plus, you have a <strong>Travel Credit of %s</strong> for your next booking.",
                  "es": "🎁 Además, tienes un <strong>Crédito de Viaje de %s</strong> para tu próxima reserva.",
                  "fr": "🎁 En plus, vous avez un <strong>Crédit Voyage de %s</strong> pour votre prochaine réservation.",
                  "de": "🎁 Außerdem haben Sie ein <strong>Reiseguthaben von %s</strong> für Ihre nächste Buchung.",
                  "pt": "🎁 Além disso, tens um <strong>Crédito de Viagem de %s</strong> para a próxima reserva.",
                  "ja": "🎁 さらに、次回のご予約に使える<strong>%s の旅行クレジット</strong>があります。",
                  "zh": "🎁 此外，您有一笔可用于下次预订的<strong>旅行积分 %s</strong>。"},
    "c_liberata": {"it": "La tua prenotazione per <strong>%s</strong> è stata cancellata e le date sono state liberate.",
                   "en": "Your booking for <strong>%s</strong> has been cancelled and the dates freed up.",
                   "es": "Tu reserva de <strong>%s</strong> se ha anulado y las fechas han quedado libres.",
                   "fr": "Votre réservation pour <strong>%s</strong> a été annulée et les dates libérées.",
                   "de": "Ihre Buchung für <strong>%s</strong> wurde storniert und die Termine freigegeben.",
                   "pt": "A tua reserva de <strong>%s</strong> foi cancelada e as datas ficaram livres.",
                   "ja": "<strong>%s</strong> のご予約はキャンセルされ、日程は解放されました。",
                   "zh": "您对 <strong>%s</strong> 的预订已取消，日期已释放。"},
    "c_arrivederci": {"it": "Speriamo di rivederti presto su BookinVIP.",
                      "en": "We hope to see you again soon on BookinVIP.",
                      "es": "Esperamos verte pronto de nuevo en BookinVIP.",
                      "fr": "Au plaisir de vous revoir bientôt sur BookinVIP.",
                      "de": "Wir hoffen, Sie bald wieder auf BookinVIP zu sehen.",
                      "pt": "Esperamos ver-te em breve na BookinVIP.",
                      "ja": "またBookinVIPでお会いできますように。",
                      "zh": "期待很快在 BookinVIP 再次见到您。"},
    # --- invito recensione ---
    "r_link": {"it": "⭐ Lascia la tua recensione", "en": "⭐ Leave your review",
               "es": "⭐ Deja tu opinión", "fr": "⭐ Laissez votre avis",
               "de": "⭐ Bewertung abgeben", "pt": "⭐ Deixa a tua avaliação",
               "ja": "⭐ レビューを書く", "zh": "⭐ 留下您的评价"},
    "r_ogg": {"it": "BookinVIP - Com'è andato il soggiorno?",
              "en": "BookinVIP - How was your stay?",
              "es": "BookinVIP - ¿Qué tal tu estancia?",
              "fr": "BookinVIP - Comment s'est passé votre séjour ?",
              "de": "BookinVIP - Wie war Ihr Aufenthalt?",
              "pt": "BookinVIP - Como foi a estadia?",
              "ja": "BookinVIP - ご滞在はいかがでしたか？", "zh": "BookinVIP - 入住体验如何？"},
    "r_titolo": {"it": "Com'è andata a %s?", "en": "How was %s?",
                 "es": "¿Qué tal %s?", "fr": "Comment était %s ?",
                 "de": "Wie war %s?", "pt": "Como foi %s?",
                 "ja": "%s はいかがでしたか？", "zh": "%s 怎么样？"},
    "r_corpo": {"it": "Il tuo soggiorno è concluso: raccontalo a chi verrà dopo di te. Bastano due tocchi — voto generale e, se vuoi, pulizia, comfort, posizione…",
                "en": "Your stay is over: tell those who come after you. Just two taps — overall rating and, if you like, cleanliness, comfort, location…",
                "es": "Tu estancia ha terminado: cuéntala a quienes vengan después. Solo dos toques — valoración general y, si quieres, limpieza, comodidad, ubicación…",
                "fr": "Votre séjour est terminé : racontez-le à ceux qui viendront après. Deux clics suffisent — note globale et, si vous voulez, propreté, confort, emplacement…",
                "de": "Ihr Aufenthalt ist vorbei: Erzählen Sie es denen, die nach Ihnen kommen. Nur zwei Tipps — Gesamtbewertung und, wenn Sie möchten, Sauberkeit, Komfort, Lage…",
                "pt": "A tua estadia terminou: conta a quem vier depois. Bastam dois toques — nota geral e, se quiseres, limpeza, conforto, localização…",
                "ja": "ご滞在が終わりました。次に訪れる方のために感想をお寄せください。総合評価と、任意で清潔さ・快適さ・立地など、2タップで完了します。",
                "zh": "您的入住已结束：为后来者留下体验吧。只需两下——总体评分，以及（可选）清洁、舒适、位置……"},
    "r_nota": {"it": "Solo chi ha soggiornato davvero può recensire: la tua opinione vale, ed è verificata.",
               "en": "Only real guests can review: your opinion counts, and it's verified.",
               "es": "Solo quien se ha alojado de verdad puede opinar: tu opinión cuenta y está verificada.",
               "fr": "Seuls les vrais voyageurs peuvent laisser un avis : votre opinion compte, et elle est vérifiée.",
               "de": "Nur echte Gäste können bewerten: Ihre Meinung zählt und ist verifiziert.",
               "pt": "Só quem ficou mesmo pode avaliar: a tua opinião conta e é verificada.",
               "ja": "実際に滞在した方だけがレビューできます。あなたの声は確かに届き、認証済みです。",
               "zh": "只有真正入住的客人才能评价：您的意见很重要，且经过验证。"},
    # --- esito controversia ---
    "d_ogg": {"it": "BookinVIP - Esito della tua segnalazione",
              "en": "BookinVIP - Outcome of your report",
              "es": "BookinVIP - Resultado de tu incidencia",
              "fr": "BookinVIP - Résultat de votre signalement",
              "de": "BookinVIP - Ergebnis Ihrer Meldung",
              "pt": "BookinVIP - Resultado da tua comunicação",
              "ja": "BookinVIP - ご申告の結果", "zh": "BookinVIP - 申诉结果"},
    "d_titolo": {"it": "Esito della tua segnalazione", "en": "Outcome of your report",
                 "es": "Resultado de tu incidencia", "fr": "Résultat de votre signalement",
                 "de": "Ergebnis Ihrer Meldung", "pt": "Resultado da tua comunicação",
                 "ja": "ご申告の結果", "zh": "您的申诉结果"},
    "d_esaminato": {"it": "Abbiamo esaminato la tua segnalazione con le prove della conversazione.",
                    "en": "We reviewed your report together with the evidence from the conversation.",
                    "es": "Hemos examinado tu incidencia con las pruebas de la conversación.",
                    "fr": "Nous avons examiné votre signalement avec les preuves de la conversation.",
                    "de": "Wir haben Ihre Meldung zusammen mit den Nachweisen aus dem Chat geprüft.",
                    "pt": "Analisámos a tua comunicação com as provas da conversa.",
                    "ja": "会話の証拠とともにご申告を確認しました。",
                    "zh": "我们已结合对话中的证据审核了您的申诉。"},
    "d_rimborso": {"it": "Ti verrà rimborsato: <strong>%s</strong> (tempi bancari: di norma 5-10 giorni lavorativi).",
                   "en": "You will be refunded: <strong>%s</strong> (bank times: usually 5-10 business days).",
                   "es": "Se te reembolsará: <strong>%s</strong> (plazos bancarios: normalmente 5-10 días hábiles).",
                   "fr": "Vous serez remboursé : <strong>%s</strong> (délais bancaires : en général 5 à 10 jours ouvrés).",
                   "de": "Sie erhalten eine Erstattung: <strong>%s</strong> (Banklaufzeiten: in der Regel 5-10 Werktage).",
                   "pt": "Vais ser reembolsado: <strong>%s</strong> (prazos bancários: normalmente 5-10 dias úteis).",
                   "ja": "<strong>%s</strong> を返金します（銀行処理: 通常5〜10営業日）。",
                   "zh": "将向您退款：<strong>%s</strong>（银行处理：通常 5-10 个工作日）。"},
    "d_no_rimborso": {"it": "Dopo la verifica delle prove non è stato riconosciuto un rimborso.",
                      "en": "After reviewing the evidence, no refund was granted.",
                      "es": "Tras revisar las pruebas, no se ha concedido reembolso.",
                      "fr": "Après examen des preuves, aucun remboursement n'a été accordé.",
                      "de": "Nach Prüfung der Nachweise wurde keine Erstattung gewährt.",
                      "pt": "Após a análise das provas, não foi concedido reembolso.",
                      "ja": "証拠の確認の結果、返金は認められませんでした。",
                      "zh": "经审核证据，未予退款。"},
    "d_grazie": {"it": "Grazie per averci aiutato a tenere alta la qualità.",
                 "en": "Thank you for helping us keep the quality high.",
                 "es": "Gracias por ayudarnos a mantener la calidad.",
                 "fr": "Merci de nous aider à maintenir la qualité.",
                 "de": "Danke, dass Sie uns helfen, die Qualität hochzuhalten.",
                 "pt": "Obrigado por nos ajudares a manter a qualidade.",
                 "ja": "品質の維持にご協力いただきありがとうございます。",
                 "zh": "感谢您帮助我们保持高品质。"},
    # --- payout host ---
    "p_ogg": {"it": "BookinVIP - Pagamento in arrivo", "en": "BookinVIP - Payout on its way",
              "es": "BookinVIP - Pago en camino", "fr": "BookinVIP - Versement en route",
              "de": "BookinVIP - Auszahlung unterwegs", "pt": "BookinVIP - Pagamento a caminho",
              "ja": "BookinVIP - お支払い手続き中", "zh": "BookinVIP - 款项已在途"},
    "p_titolo": {"it": "💶 Pagamento in arrivo", "en": "💶 Payout on its way",
                 "es": "💶 Pago en camino", "fr": "💶 Versement en route",
                 "de": "💶 Auszahlung unterwegs", "pt": "💶 Pagamento a caminho",
                 "ja": "💶 お支払い手続き中", "zh": "💶 款项已在途"},
    "p_quota": {"it": "La tua quota per la prenotazione <strong>%s</strong> è partita verso il tuo conto: <strong>%s</strong>.",
                "en": "Your share for booking <strong>%s</strong> is on its way to your account: <strong>%s</strong>.",
                "es": "Tu parte por la reserva <strong>%s</strong> va hacia tu cuenta: <strong>%s</strong>.",
                "fr": "Votre part pour la réservation <strong>%s</strong> part vers votre compte : <strong>%s</strong>.",
                "de": "Ihr Anteil für die Buchung <strong>%s</strong> ist auf dem Weg zu Ihrem Konto: <strong>%s</strong>.",
                "pt": "A tua parte pela reserva <strong>%s</strong> segue para a tua conta: <strong>%s</strong>.",
                "ja": "予約 <strong>%s</strong> のあなたの取り分がご口座へ送金されました: <strong>%s</strong>。",
                "zh": "预订 <strong>%s</strong> 中属于您的份额已汇往您的账户：<strong>%s</strong>。"},
    "p_tempi": {"it": "I tempi di accredito dipendono dalla tua banca (di norma 1-3 giorni lavorativi). Dettagli nel pannello host, riquadro \"I tuoi incassi\".",
                "en": "Crediting times depend on your bank (usually 1-3 business days). Details in the host panel, \"Your earnings\" box.",
                "es": "Los plazos de abono dependen de tu banco (normalmente 1-3 días hábiles). Detalles en el panel de anfitrión, sección \"Tus ingresos\".",
                "fr": "Les délais de crédit dépendent de votre banque (en général 1 à 3 jours ouvrés). Détails dans l'espace hôte, encadré « Vos revenus ».",
                "de": "Die Gutschriftzeiten hängen von Ihrer Bank ab (in der Regel 1-3 Werktage). Details im Gastgeber-Panel, Bereich „Ihre Einnahmen“.",
                "pt": "Os prazos de crédito dependem do teu banco (normalmente 1-3 dias úteis). Detalhes no painel de anfitrião, secção \"Os teus ganhos\".",
                "ja": "入金までの日数はご利用の銀行によります（通常1〜3営業日）。詳細はホストパネルの「あなたの収入」をご覧ください。",
                "zh": "到账时间取决于您的银行（通常 1-3 个工作日）。详情见房东面板“您的收入”一栏。"},
    # --- reset password ---
    "rp_ogg": {"it": "BookinVIP - Reimposta la password", "en": "BookinVIP - Reset your password",
               "es": "BookinVIP - Restablece la contraseña", "fr": "BookinVIP - Réinitialiser le mot de passe",
               "de": "BookinVIP - Passwort zurücksetzen", "pt": "BookinVIP - Repor a palavra-passe",
               "ja": "BookinVIP - パスワードの再設定", "zh": "BookinVIP - 重置密码"},
    "rp_titolo": {"it": "BookinVIP - Reimposta la password", "en": "BookinVIP - Reset your password",
                  "es": "BookinVIP - Restablece la contraseña", "fr": "BookinVIP - Réinitialiser le mot de passe",
                  "de": "BookinVIP - Passwort zurücksetzen", "pt": "BookinVIP - Repor a palavra-passe",
                  "ja": "BookinVIP - パスワードの再設定", "zh": "BookinVIP - 重置密码"},
    "rp_chiesto": {"it": "Hai chiesto di reimpostare la password del tuo account host.",
                   "en": "You asked to reset the password of your host account.",
                   "es": "Has solicitado restablecer la contraseña de tu cuenta de anfitrión.",
                   "fr": "Vous avez demandé à réinitialiser le mot de passe de votre compte hôte.",
                   "de": "Sie haben angefragt, das Passwort Ihres Gastgeber-Kontos zurückzusetzen.",
                   "pt": "Pediste para repor a palavra-passe da tua conta de anfitrião.",
                   "ja": "ホストアカウントのパスワード再設定がリクエストされました。",
                   "zh": "您请求重置房东账户的密码。"},
    "rp_scegli": {"it": "Scegli la nuova password", "en": "Choose your new password",
                  "es": "Elige la nueva contraseña", "fr": "Choisir le nouveau mot de passe",
                  "de": "Neues Passwort wählen", "pt": "Escolhe a nova palavra-passe",
                  "ja": "新しいパスワードを設定", "zh": "设置新密码"},
    "rp_nota": {"it": "Il link vale <strong>30 minuti</strong> e funziona <strong>una sola volta</strong>. Se non hai chiesto tu il cambio, ignora questa email: la tua password resta quella di sempre.",
                "en": "The link is valid for <strong>30 minutes</strong> and works <strong>only once</strong>. If you didn't request the change, ignore this email: your password stays the same.",
                "es": "El enlace vale <strong>30 minutos</strong> y funciona <strong>una sola vez</strong>. Si no pediste el cambio, ignora este correo: tu contraseña sigue igual.",
                "fr": "Le lien est valable <strong>30 minutes</strong> et ne fonctionne <strong>qu'une fois</strong>. Si vous n'avez pas demandé ce changement, ignorez cet e-mail : votre mot de passe reste inchangé.",
                "de": "Der Link gilt <strong>30 Minuten</strong> und funktioniert <strong>nur einmal</strong>. Wenn Sie die Änderung nicht angefragt haben, ignorieren Sie diese E-Mail: Ihr Passwort bleibt unverändert.",
                "pt": "O link é válido <strong>30 minutos</strong> e funciona <strong>uma só vez</strong>. Se não pediste a alteração, ignora este e-mail: a tua palavra-passe fica na mesma.",
                "ja": "リンクは<strong>30分間</strong>有効で、<strong>1回のみ</strong>使用できます。心当たりがなければ、このメールは無視してください。パスワードは変わりません。",
                "zh": "该链接<strong>有效 30 分钟</strong>，且<strong>仅可使用一次</strong>。若非您本人申请，请忽略此邮件：您的密码保持不变。"},
    # --- benvenuto host ---
    "b_ogg": {"it": "Benvenuto su BookinVIP", "en": "Welcome to BookinVIP",
              "es": "Bienvenido a BookinVIP", "fr": "Bienvenue sur BookinVIP",
              "de": "Willkommen bei BookinVIP", "pt": "Bem-vindo à BookinVIP",
              "ja": "BookinVIPへようこそ", "zh": "欢迎加入 BookinVIP"},
    "b_titolo": {"it": "Benvenuto su BookinVIP! 👑", "en": "Welcome to BookinVIP! 👑",
                 "es": "¡Bienvenido a BookinVIP! 👑", "fr": "Bienvenue sur BookinVIP ! 👑",
                 "de": "Willkommen bei BookinVIP! 👑", "pt": "Bem-vindo à BookinVIP! 👑",
                 "ja": "BookinVIPへようこそ！👑", "zh": "欢迎加入 BookinVIP！👑"},
    "b_pronto": {"it": "Il tuo account host è pronto. In 3 passi sei online:",
                 "en": "Your host account is ready. Three steps and you're online:",
                 "es": "Tu cuenta de anfitrión está lista. En 3 pasos estás online:",
                 "fr": "Votre compte hôte est prêt. En 3 étapes, vous êtes en ligne :",
                 "de": "Ihr Gastgeber-Konto ist bereit. In 3 Schritten sind Sie online:",
                 "pt": "A tua conta de anfitrião está pronta. Em 3 passos estás online:",
                 "ja": "ホストアカウントの準備ができました。3ステップで公開できます:",
                 "zh": "您的房东账户已就绪。三步即可上线："},
    "b_p1": {"it": "Pubblica il tuo alloggio (titolo, prezzo, foto).",
             "en": "Publish your place (title, price, photos).",
             "es": "Publica tu alojamiento (título, precio, fotos).",
             "fr": "Publiez votre logement (titre, prix, photos).",
             "de": "Veröffentlichen Sie Ihre Unterkunft (Titel, Preis, Fotos).",
             "pt": "Publica o teu alojamento (título, preço, fotos).",
             "ja": "宿を掲載する（タイトル・料金・写真）。", "zh": "发布您的房源（标题、价格、照片）。"},
    "b_p2": {"it": "Apri le date libere sul calendario.",
             "en": "Open your free dates on the calendar.",
             "es": "Abre las fechas libres en el calendario.",
             "fr": "Ouvrez vos dates libres sur le calendrier.",
             "de": "Öffnen Sie freie Termine im Kalender.",
             "pt": "Abre as datas livres no calendário.",
             "ja": "カレンダーで空き日程を公開する。", "zh": "在日历上开放可预订日期。"},
    "b_p3": {"it": "Ricevi le prenotazioni e approva con un tocco.",
             "en": "Receive bookings and approve with one tap.",
             "es": "Recibe reservas y aprueba con un toque.",
             "fr": "Recevez les réservations et approuvez d'un clic.",
             "de": "Erhalten Sie Buchungen und bestätigen Sie mit einem Tipp.",
             "pt": "Recebe reservas e aprova com um toque.",
             "ja": "予約を受け取り、ワンタップで承認する。", "zh": "接收预订并一键批准。"},
    "b_pannello": {"it": "Apri il pannello host", "en": "Open the host panel",
                   "es": "Abre el panel de anfitrión", "fr": "Ouvrir l'espace hôte",
                   "de": "Gastgeber-Panel öffnen", "pt": "Abre o painel de anfitrião",
                   "ja": "ホストパネルを開く", "zh": "打开房东面板"},
    "b_commissioni": {"it": "Commissione <b>0% per i primi 90 giorni</b>, poi 8% fino a un anno, poi 10% dal marketplace. Sempre solo 5% sul tuo link diretto. L'ospite paga 0%. Nessun canone e nessun costo fisso: l'unica cosa sempre dovuta è una tariffa tecnica del 3% sull'importo, che copre il costo della carta.",
                      "en": "Commission <b>0% for the first 90 days</b>, then 8% up to one year, then 10% from the marketplace. Always just 5% on your direct link. The guest pays 0%. No subscription and no fixed cost: the only thing always due is a 3% technical fee on the amount, covering the card cost.",
                      "es": "Comisión <b>0% los primeros 90 días</b>, luego 8% hasta un año, después 10% desde el marketplace. Siempre solo 5% en tu enlace directo. El huésped paga 0%. Sin cuota ni coste fijo: lo único siempre debido es una tarifa técnica del 3% sobre el importe, que cubre el coste de la tarjeta.",
                      "fr": "Commission <b>0 % les 90 premiers jours</b>, puis 8 % jusqu'à un an, puis 10 % via la marketplace. Toujours 5 % seulement sur votre lien direct. Le voyageur paie 0 %. Aucun abonnement ni coût fixe : la seule chose toujours due est des frais techniques de 3 % sur le montant, qui couvrent le coût de la carte.",
                      "de": "Provision <b>0 % in den ersten 90 Tagen</b>, dann 8 % bis zu einem Jahr, dann 10 % über den Marktplatz. Über Ihren Direktlink immer nur 5 %. Der Gast zahlt 0 %. Keine Gebühr und keine Fixkosten: stets fällig ist nur ein technisches Entgelt von 3 % des Betrags, das die Kartenkosten deckt.",
                      "pt": "Comissão <b>0% nos primeiros 90 dias</b>, depois 8% até um ano, depois 10% via marketplace. No teu link direto, sempre só 5%. O hóspede paga 0%. Sem mensalidade e sem custo fixo: a única coisa sempre devida é uma taxa técnica de 3% sobre o valor, que cobre o custo do cartão.",
                      "ja": "手数料は<b>最初の90日間は0%</b>、その後1年まで8%、以降マーケットプレイス経由で10%。あなたの直接リンクなら常に5%のみ。ゲストの負担は0%。月額も固定費もありません。常に発生するのは金額の3%の技術手数料のみで、これはカード決済の費用を賄います。",
                      "zh": "佣金<b>前 90 天为 0%</b>，之后至一年为 8%，再之后经市场为 10%。通过您的专属直连链接始终仅 5%。房客支付 0%。无月费、无固定费用：唯一始终收取的是金额 3% 的技术服务费，用于支付银行卡成本。"},
    # --- promemoria check-in ---
    "pr_ogg": {"it": "BookinVIP - Com'è andata?", "en": "BookinVIP - How's it going?",
               "es": "BookinVIP - ¿Qué tal?", "fr": "BookinVIP - Tout se passe bien ?",
               "de": "BookinVIP - Wie läuft's?", "pt": "BookinVIP - Como está a correr?",
               "ja": "BookinVIP - ご滞在はいかがですか？", "zh": "BookinVIP - 一切还好吗？"},
    "pr_titolo": {"it": "BookinVIP - Com'è andata?", "en": "BookinVIP - How's it going?",
                  "es": "BookinVIP - ¿Qué tal?", "fr": "BookinVIP - Tout se passe bien ?",
                  "de": "BookinVIP - Wie läuft's?", "pt": "BookinVIP - Como está a correr?",
                  "ja": "BookinVIP - ご滞在はいかがですか？", "zh": "BookinVIP - 一切还好吗？"},
    "pr_ciao": {"it": "Ciao! Speriamo che il tuo soggiorno a <strong>%s</strong> stia andando bene.",
                "en": "Hi! We hope your stay at <strong>%s</strong> is going well.",
                "es": "¡Hola! Esperamos que tu estancia en <strong>%s</strong> vaya bien.",
                "fr": "Bonjour ! Nous espérons que votre séjour à <strong>%s</strong> se passe bien.",
                "de": "Hallo! Wir hoffen, Ihr Aufenthalt in <strong>%s</strong> läuft gut.",
                "pt": "Olá! Esperamos que a tua estadia em <strong>%s</strong> esteja a correr bem.",
                "ja": "こんにちは！<strong>%s</strong> でのご滞在が順調であることを願っています。",
                "zh": "您好！希望您在 <strong>%s</strong> 的入住一切顺利。"},
    "pr_ok": {"it": "✅ <strong>Se è tutto come descritto, non devi fare nulla.</strong>",
              "en": "✅ <strong>If everything is as described, you don't need to do anything.</strong>",
              "es": "✅ <strong>Si todo es como se describe, no tienes que hacer nada.</strong>",
              "fr": "✅ <strong>Si tout est conforme, vous n'avez rien à faire.</strong>",
              "de": "✅ <strong>Wenn alles wie beschrieben ist, müssen Sie nichts tun.</strong>",
              "pt": "✅ <strong>Se está tudo como descrito, não precisas de fazer nada.</strong>",
              "ja": "✅ <strong>記載どおりであれば、何もする必要はありません。</strong>",
              "zh": "✅ <strong>如果一切如描述所示，您无需任何操作。</strong>"},
    "pr_problema": {"it": "⚠️ <strong>Se c'è un problema, segnalalo ENTRO 24 ore</strong> dall'arrivo, dal tuo voucher (pulsante \"Segnala un problema\"). Passate le 24h senza segnalazioni, il soggiorno è considerato regolare.",
                    "en": "⚠️ <strong>If there's a problem, report it WITHIN 24 hours</strong> of arrival, from your voucher (\"Report a problem\" button). After 24h with no report, the stay is considered fine.",
                    "es": "⚠️ <strong>Si hay un problema, comunícalo DENTRO de 24 horas</strong> desde la llegada, desde tu bono (botón \"Informar de un problema\"). Pasadas 24h sin avisos, la estancia se considera correcta.",
                    "fr": "⚠️ <strong>En cas de problème, signalez-le DANS les 24 heures</strong> après l'arrivée, depuis votre bon (bouton « Signaler un problème »). Passé 24h sans signalement, le séjour est considéré conforme.",
                    "de": "⚠️ <strong>Bei einem Problem melden Sie es INNERHALB von 24 Stunden</strong> nach Ankunft über Ihren Gutschein (Schaltfläche „Problem melden“). Nach 24h ohne Meldung gilt der Aufenthalt als in Ordnung.",
                    "pt": "⚠️ <strong>Se houver um problema, comunica-o DENTRO de 24 horas</strong> da chegada, a partir do voucher (botão \"Comunicar um problema\"). Passadas 24h sem avisos, a estadia é considerada regular.",
                    "ja": "⚠️ <strong>問題がある場合は、到着から24時間以内に</strong>バウチャーの「問題を報告」ボタンからお知らせください。24時間報告がなければ、ご滞在は正常とみなされます。",
                    "zh": "⚠️ <strong>如有问题，请在抵达后 24 小时内</strong>通过凭证（“报告问题”按钮）反馈。24 小时内无反馈，则视为入住正常。"},
    "pr_grazie": {"it": "Grazie per aver scelto BookinVIP.", "en": "Thank you for choosing BookinVIP.",
                  "es": "Gracias por elegir BookinVIP.", "fr": "Merci d'avoir choisi BookinVIP.",
                  "de": "Danke, dass Sie BookinVIP gewählt haben.", "pt": "Obrigado por escolheres a BookinVIP.",
                  "ja": "BookinVIPをお選びいただきありがとうございます。", "zh": "感谢您选择 BookinVIP。"},
    "apri_voucher": {"it": "Apri il voucher", "en": "Open the voucher", "es": "Abrir el bono",
                     "fr": "Ouvrir le bon", "de": "Gutschein öffnen", "pt": "Abrir o voucher",
                     "ja": "バウチャーを開く", "zh": "打开凭证"},
}


def T(chiave: str, lingua: str) -> str:
    """Testo localizzato; ripiego INGLESE se manca la lingua (mai italiano)."""
    voce = _TR.get(chiave, {})
    return voce.get(lingua) or voce.get("en") or ""


def oggetto(chiave_ogg: str, lingua: Any, *fmt) -> str:
    """L'OGGETTO dell'email nella lingua giusta (per i chiamanti)."""
    testo = T(chiave_ogg, _lingua(lingua))
    return (testo % fmt) if fmt else testo


def _btn(url: str, testo: str, colore: str = "#0f4c3a", grande: bool = True) -> str:
    e = _html.escape
    pad = ".7rem 1.4rem" if grande else ".6rem 1.2rem"
    peso = "font-weight:700" if grande else ""
    return ('<p><a href="%s" style="background:%s;color:#fff;padding:%s;'
            'border-radius:8px;text-decoration:none;%s">%s</a></p>'
            % (e(url), colore, pad, peso, e(testo))) if url else ""


def _wrap(colore_h2: str, h2: str, *blocchi) -> str:
    """`h2` e' gia' HTML pronto: i titoli fissi sono stringhe nostre (sicure), e dove il
    titolo contiene testo dell'utente il chiamante lo ha GIA' passato da esc() (es.
    `r_titolo % e(titolo)`). Ri-escaparlo qui darebbe un doppio escape (&amp;lt; invece di
    &lt;): innocuo per la sicurezza, ma il testo uscirebbe sbagliato."""
    return ("<div style=\"font-family:sans-serif;max-width:480px\">"
            "<h2 style=\"color:%s\">%s</h2>%s</div>"
            % (colore_h2, h2, "".join(blocchi)))


def _nota(testo: str) -> str:
    return "<p style=\"color:#5e6f8d;font-size:.85rem\">%s</p>" % testo


def _soldi(cents: int, valuta: str) -> str:
    """Importo scritto secondo i decimali VERI della valuta.

    Prima questa funzione divideva per cento a mano, sempre, anche sulle valute che non
    hanno decimali. Un ospite giapponese che pagava ¥54.000 riceveva l'email con scritto
    **540.00 JPY** — cento volte meno del reale. Ora si chiede al motore
    (`fase99.Denaro.formatta`), la stessa fonte usata dal server."""
    try:
        c = int(cents)
    except Exception:
        c = 0
    v = str(valuta or "EUR").strip().upper() or "EUR"
    try:
        from fase99_multicurrency import Denaro
        return Denaro(c, v).formatta()
    except Exception:
        logger.warning("importo non formattabile (%r %r): scritto grezzo", cents, valuta)
        return "%d %s" % (c, v)


def corpo_voucher_html(titolo_alloggio: str, codice: str, check_in: str,
                       check_out: str, voucher_url: str, pin: str = "",
                       payment_url: str = "", lingua: Any = "en") -> str:
    """Email di conferma prenotazione, LOCALIZZATA. XSS-safe. `codice` = codice leggibile
    (BVIP-XXXX-XXXX); `pin` = PIN check-in; `payment_url`: se presente, la prenotazione e'
    riservata ma da pagare (bottone di pagamento in cima)."""
    e = _html.escape
    lg = _lingua(lingua)
    link = _btn(voucher_url, T("v_apri", lg), colore="#1e3c72", grande=False)
    blocco_pin = ('<br>%s: <strong style="font-size:1.1rem;color:#1e3c72">%s</strong>'
                  % (e(T("v_pin", lg)), e(str(pin)))) if pin else ""
    if payment_url:
        titolo_email = T("v_ogg_pay", lg)
        blocco_pagamento = (
            '<p style="background:#fff4e5;border-radius:10px;padding:.7rem 1rem;color:#8a5200">'
            + T("v_riservata", lg) + "</p>"
            + _btn(payment_url, "💳 " + T("v_completa_pay", lg), colore="#155724"))
    else:
        titolo_email = T("v_ogg_conf", lg)
        blocco_pagamento = ""
    corpo = ("%s<p>%s: <strong style=\"letter-spacing:.05em\">%s</strong>%s<br>%s</p>%s"
             % (blocco_pagamento, e(T("v_codice", lg)), e(codice), blocco_pin,
                (T("v_dal_al", lg) % (e(check_in), e(check_out))), link))
    return _wrap("#1e3c72", titolo_email,
                 "<p><strong>%s</strong></p>" % e(titolo_alloggio), corpo,
                 _nota(T("v_conserva", lg)))


def corpo_preventivo_html(titolo_alloggio: str, check_in: str, check_out: str,
                          righe: Any, url_prenota: str, lingua: Any = "en") -> str:
    """Email 'il tuo preventivo' (recupero ONESTO: parte solo se l'ospite la chiede col
    clic). `righe` = [(etichetta, importo_formattato), ...]. LOCALIZZATA. XSS-safe."""
    e = _html.escape
    lg = _lingua(lingua)
    testi = {
        "it": ("Il tuo preventivo", "Ecco il riepilogo che hai richiesto per",
               "Completa la prenotazione",
               "Nessun impegno e nessun addebito: le date restano libere finché qualcuno "
               "non prenota. Questa è l'unica email: niente promemoria."),
        "en": ("Your quote", "Here is the summary you requested for",
               "Complete your booking",
               "No commitment, no charge: the dates stay open until someone books. This is "
               "the only email: no reminders."),
        "es": ("Tu presupuesto", "Este es el resumen que pediste para",
               "Completar la reserva",
               "Sin compromiso ni cargo: las fechas quedan libres hasta que alguien "
               "reserve. Este es el único correo: sin recordatorios."),
        "fr": ("Votre devis", "Voici le récapitulatif demandé pour",
               "Finaliser la réservation",
               "Sans engagement ni frais : les dates restent libres jusqu'à ce que "
               "quelqu'un réserve. C'est le seul e-mail : aucun rappel."),
        "de": ("Ihr Angebot", "Hier ist die angeforderte Übersicht für",
               "Buchung abschließen",
               "Unverbindlich und kostenlos: die Termine bleiben frei, bis jemand bucht. "
               "Dies ist die einzige E-Mail: keine Erinnerungen."),
        "pt": ("O teu orçamento", "Aqui está o resumo que pediste para",
               "Concluir a reserva",
               "Sem compromisso e sem custo: as datas ficam livres até alguém reservar. "
               "Este é o único e-mail: sem lembretes."),
        "ja": ("お見積り", "ご依頼の概要はこちらです：", "予約を完了する",
               "拘束も料金もありません。誰かが予約するまで日程は空いたままです。メールはこの1通のみで、リマインダーはありません。"),
        "zh": ("您的报价", "这是您所请求的摘要：", "完成预订",
               "无需承诺、不收费用：在有人预订前日期保持开放。这是唯一一封邮件，不会有提醒。"),
    }
    titolo_email, sotto, btn, nota = testi.get(lg, testi["en"])
    corpo_righe = "".join(
        "<tr><td style=\"padding:.2rem 0;color:#4a5b7a\">%s</td>"
        "<td style=\"padding:.2rem 0 .2rem 1.2rem;text-align:right\"><strong>%s</strong>"
        "</td></tr>" % (e(str(k)), e(str(v)))
        for k, v in (righe or ()) if v)
    return _wrap(
        "#0f4c3a", titolo_email,
        "<p>%s <strong>%s</strong><br>%s → %s</p>" % (e(sotto), e(titolo_alloggio),
                                                      e(check_in), e(check_out)),
        "<table style=\"width:100%%;border-collapse:collapse\">%s</table>" % corpo_righe,
        _btn(url_prenota, btn), _nota(e(nota)))


def corpo_pagamento_confermato_html(titolo: str, voucher_url: str, importo_cents: int,
                                    valuta: str, lingua: Any = "en",
                                    saldo_cents: int = 0) -> str:
    """Email dopo il PAGAMENTO riuscito. LOCALIZZATA. XSS-safe.
    `saldo_cents` > 0 (PAGA IN STRUTTURA): mostra il SALDO da pagare all'host in loco.
    Default 0 (online) -> email invariata."""
    e = _html.escape
    lg = _lingua(lingua)
    riga_importo = ("<p>%s: <strong>%s</strong></p>"
                    % (e(T("pc_importo", lg)), e(_soldi(importo_cents, valuta)))
                    if importo_cents else "")
    # PAGA IN STRUTTURA: il saldo da pagare di persona, evidenziato (l'ospite deve saperlo).
    riga_saldo = ("<p style=\"background:#fff4e5;border-radius:10px;padding:.7rem 1rem;"
                  "color:#8a5200\">%s <strong>%s</strong></p>"
                  % (e(T("pc_saldo", lg)), e(_soldi(saldo_cents, valuta)))
                  if (isinstance(saldo_cents, int) and not isinstance(saldo_cents, bool)
                      and saldo_cents > 0) else "")
    return _wrap("#0f4c3a", T("pc_titolo", lg),
                 "<p>%s</p>" % (T("pc_ok", lg) % e(titolo)), riga_importo, riga_saldo,
                 _btn(voucher_url, T("v_apri", lg)), _nota(T("pc_nota", lg)))


def corpo_cancellazione_html(titolo: str, rimborso_cents: int, valuta: str,
                             credito_cents: int = 0, lingua: Any = "en") -> str:
    """Email di conferma CANCELLAZIONE con l'importo del rimborso nero su bianco.
    LOCALIZZATA."""
    e = _html.escape
    lg = _lingua(lingua)
    if rimborso_cents > 0:
        riga = ("<p style=\"background:#e7f6ec;border-radius:10px;padding:.7rem 1rem;"
                "color:#155724\">%s</p>"
                % (T("c_rimborso", lg) % e(_soldi(rimborso_cents, valuta))))
    else:
        riga = ("<p style=\"background:#fff4e5;border-radius:10px;padding:.7rem 1rem;"
                "color:#8a5200\">%s</p>" % T("c_no_rimborso", lg))
    credito = ("<p>%s</p>" % (T("c_credito", lg) % e(_soldi(credito_cents, valuta)))
               ) if credito_cents > 0 else ""
    return _wrap("#0f4c3a", T("c_titolo", lg),
                 "<p>%s</p>" % (T("c_liberata", lg) % e(titolo)), riga, credito,
                 _nota(T("c_arrivederci", lg)))


def corpo_invito_recensione_html(titolo: str, voucher_url: str, lingua: Any = "en") -> str:
    """Email post-CHECK-OUT: invito a recensire. LOCALIZZATA."""
    e = _html.escape
    lg = _lingua(lingua)
    return _wrap("#0f4c3a", T("r_titolo", lg) % e(titolo),
                 "<p>%s</p>" % e(T("r_corpo", lg)),
                 _btn(voucher_url, T("r_link", lg)), _nota(e(T("r_nota", lg))))


def corpo_esito_controversia_html(rimborso_cents: int, valuta: str,
                                  lingua: Any = "en") -> str:
    """Email all'ospite con l'ESITO della controversia. LOCALIZZATA."""
    e = _html.escape
    lg = _lingua(lingua)
    if rimborso_cents > 0:
        corpo = ("<p style=\"background:#e7f6ec;border-radius:10px;padding:.7rem 1rem;"
                 "color:#155724\">%s</p>"
                 % (T("d_rimborso", lg) % e(_soldi(rimborso_cents, valuta))))
    else:
        corpo = ("<p style=\"background:#fff4e5;border-radius:10px;padding:.7rem 1rem;"
                 "color:#8a5200\">%s</p>" % T("d_no_rimborso", lg))
    return _wrap("#0f4c3a", T("d_titolo", lg),
                 "<p>%s</p>" % e(T("d_esaminato", lg)), corpo,
                 _nota(e(T("d_grazie", lg))))


def corpo_payout_host_html(importo_cents: int, valuta: str, codice: str,
                           lingua: Any = "en") -> str:
    """Email all'HOST quando la sua quota parte verso il conto. LOCALIZZATA."""
    e = _html.escape
    lg = _lingua(lingua)
    return _wrap("#0f4c3a", T("p_titolo", lg),
                 "<p>%s</p>" % (T("p_quota", lg) % (e(codice),
                                                    e(_soldi(importo_cents, valuta)))),
                 _nota(T("p_tempi", lg)))


def corpo_reset_password_html(link: str, lingua: Any = "en") -> str:
    """Email 'password dimenticata': magic-link 30 minuti, single-use. LOCALIZZATA."""
    lg = _lingua(lingua)
    return _wrap("#0f4c3a", T("rp_titolo", lg),
                 "<p>%s</p>" % _html.escape(T("rp_chiesto", lg)),
                 _btn(link, T("rp_scegli", lg)), _nota(T("rp_nota", lg)))


def corpo_benvenuto_host_html(pannello_url: str, lingua: Any = "en") -> str:
    """Email di benvenuto all'host. LOCALIZZATA. La trasparenza sui costi (3% sempre
    dovuto) e' tradotta in tutte le lingue: e' la PRIMA cosa che un host legge."""
    e = _html.escape
    lg = _lingua(lingua)
    passi = ("<ol><li>%s</li><li>%s</li><li>%s</li></ol>"
             % (e(T("b_p1", lg)), e(T("b_p2", lg)), e(T("b_p3", lg))))
    return _wrap("#0f4c3a", T("b_titolo", lg),
                 "<p>%s</p>" % e(T("b_pronto", lg)), passi,
                 _btn(pannello_url, T("b_pannello", lg)),
                 _nota(T("b_commissioni", lg)))


def corpo_promemoria_checkin_html(titolo_alloggio: str, voucher_url: str,
                                  lingua: Any = "en") -> str:
    """Email post-check-in: 'com'è andata?'. LOCALIZZATA."""
    e = _html.escape
    lg = _lingua(lingua)
    link = _btn(voucher_url, T("apri_voucher", lg), colore="#1e3c72", grande=False)
    ok = ("<p style=\"background:#e7f6ec;border-radius:10px;padding:.7rem 1rem;"
          "color:#155724\">%s</p>" % T("pr_ok", lg))
    problema = ("<p style=\"background:#fff4e5;border-radius:10px;padding:.7rem 1rem;"
                "color:#8a5200\">%s</p>" % T("pr_problema", lg))
    return _wrap("#1e3c72", T("pr_titolo", lg),
                 "<p>%s</p>" % (T("pr_ciao", lg) % e(titolo_alloggio)), ok, problema,
                 link, "<p style=\"color:#5e6f8d;font-size:.82rem\">%s</p>"
                 % e(T("pr_grazie", lg)))
