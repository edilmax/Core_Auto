"""FASE 185 — TESTI LEGALI MULTILINGUA: termini e privacy in tutte le lingue.

PERCHE' ESISTE (fondatore, 2026-07-21: «privacy e termini e altre cose del genere tutte
le lingue per coerenza»).

Fino a oggi:
  · il CONTRATTO host viveva in `fase163` in due lingue (it, en) — bene;
  · la PRIVACY viveva in `fase163` in UNA sola lingua;
  · i TERMINI non vivevano in nessun modulo: erano HTML piatto, solo in italiano.

Il capitolato non se ne accorgeva perche' saltava le pagine SENZA traduzioni: il caso
peggiore trattato come "non applicabile". Difetto chiuso; da qui in poi vale la regola
**assenza non e' conformita'**.

Il modello e' quello del contratto, che funziona:
  · il testo vive in un MODULO, non nell'HTML (si versiona, si firma, si confronta);
  · ogni lingua ha la sua versione, con IMPRONTA SHA-256 del testo servito;
  · la pagina diventa un guscio che chiede il testo e mostra il selettore lingua;
  · si dichiara SEMPRE quale lingua **fa fede** in caso di divergenza (l'italiano),
    come prescrivono le buone pratiche per i testi contrattuali tradotti.

ZERO DIPENDENZE: solo stdlib, come tutto il resto del progetto.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("core_auto.testi_legali")

# Le lingue che il prodotto dichiara di parlare. Aggiungerne una qui SENZA fornire i
# testi fa fallire la guardia: e' voluto — una bandiera che apre una pagina vuota e'
# peggio di una bandiera che non c'e'.
LINGUE = ("it", "en", "es", "fr", "de", "pt", "ja", "zh")

LINGUA_CHE_FA_FEDE = "it"

TERMINI_VERSIONE = "2026-07-21"
PRIVACY_VERSIONE = "2026-07-21"

# Dati del titolare: UNA sola volta, riusati in tutte le lingue. Se cambiano, cambiano
# ovunque insieme — impossibile che una traduzione resti con l'indirizzo vecchio.
GESTORE = {
    "ragione_sociale": "Edil Max di Foti Massimo",
    "piva": "11795700969",
    "indirizzo": "Via Paletro 11, 20821 Meda (MB), Italia",
    "email": "info@bookinvip.com",
}

# Percentuali: si prendono dal motore, mai scritte a mano qui (era la causa della
# bugia "10%" rimasta per mesi in contraddizione col 13% realmente addebitato).
def _percentuali() -> Dict[str, int]:
    try:
        import os
        from fase98_policy_commissione import (BPS_DIRETTO, LANCIO_BPS_FASE1,
                                               LANCIO_BPS_REGIME,
                                               LANCIO_GIORNI_GRATIS)
        tecnica = int(os.environ.get("PAGAMENTO_BPS", "300") or 300)
        return {"promo": 0, "giorni_promo": LANCIO_GIORNI_GRATIS,
                "fase1": LANCIO_BPS_FASE1 // 100, "regime": LANCIO_BPS_REGIME // 100,
                "diretto": BPS_DIRETTO // 100, "tecnica": tecnica // 100}
    except Exception:
        logger.warning("percentuali non leggibili dal motore", exc_info=True)
        return {"promo": 0, "giorni_promo": 90, "fase1": 8, "regime": 10,
                "diretto": 5, "tecnica": 3}


def _penale() -> int:
    try:
        from fase83_server import PENALE_HOST_BPS
        return PENALE_HOST_BPS // 100
    except Exception:
        return 15


# ═════════════════════════════════════════════════════════════════════════════════
#  TERMINI DI SERVIZIO
# ═════════════════════════════════════════════════════════════════════════════════
_TERMINI = {
"it": """TERMINI E CONDIZIONI DI SERVIZIO — BOOKINVIP
Versione {VER} · Ultimo aggiornamento: {VER}
Gestore: {SOC}, P.IVA {PIVA}, {IND} — {EMAIL}

1. OGGETTO E RUOLO DI BOOKINVIP
BookinVIP e' una piattaforma tecnologica di intermediazione che mette in contatto Host
(proprietari o gestori di alloggi) e Ospiti per la prenotazione di soggiorni.
BookinVIP NON possiede, non gestisce e non controlla gli alloggi. Il contratto di
soggiorno e' concluso DIRETTAMENTE tra Host e Ospite; BookinVIP fornisce gli strumenti
(vetrina, prenotazione, pagamento, voucher, check-in digitale).

2. ACCETTAZIONE
Usando la Piattaforma accetti questi Termini e l'Informativa Privacy. Se non li accetti,
non usare il servizio.

3. OBBLIGHI DELL'HOST
L'Host garantisce che: ha titolo per offrire l'alloggio e rispetta le normative locali
(licenze, registrazione ospiti, tassa di soggiorno, sicurezza); le informazioni e le foto
dell'annuncio sono veritiere e aggiornate; la disponibilita' mostrata e' reale; le
dichiarazioni vincolanti (es. "no allergeni", "pet-friendly") sono vere. Se risultano
false, l'Ospite ha diritto al rimborso e l'Host a una penale come da meccanismo della
Piattaforma.

4. PRENOTAZIONE E PAGAMENTO (OSPITE)
Il prezzo mostrato e' calcolato e firmato dal sistema: non e' modificabile dal browser.
L'Ospite paga il prezzo pulito: nessuna commissione di piattaforma e' a suo carico.
Il pagamento avviene tramite gestore autorizzato (Stripe); BookinVIP non conserva i dati
della carta.

5. COSTI A CARICO DELL'HOST
Commissione di piattaforma: {PROMO}% per i primi {GG} giorni dalla registrazione, poi
{FASE1}% fino a un anno, poi {REGIME}% a regime, sulle prenotazioni provenienti dal
marketplace; {DIRETTO}% sulle prenotazioni provenienti dal link diretto dell'Host.
TARIFFA TECNICA: oltre alla commissione, resta a carico esclusivo dell'Host una tariffa
tecnica fissa pari al {TECNICA}% dell'importo della transazione, SEMPRE DOVUTA in ogni
periodo — anche quando la commissione e' {PROMO}% — a copertura dei costi del gestore di
pagamento. Su tale voce la Piattaforma non consegue alcun margine.

6. INCASSI E BONIFICI
La quota dell'Host resta in garanzia fino alla conferma dell'Ospite o al rilascio
automatico previsto dalla Piattaforma; viene poi trasferita sul conto collegato.
I bonifici possono essere trattenuti quando la legge lo impone (obblighi di identificazione
fiscale), fino alla regolarizzazione.

7. CANCELLAZIONI E PENALI
Le condizioni di cancellazione sono indicate su ogni annuncio. Se l'Host cancella una
prenotazione gia' pagata, o l'alloggio risulta non disponibile, e' dovuta una penale pari
al {PENALE}% dell'importo, compensata dagli incassi futuri dell'Host o registrata come
debito.

8. RECENSIONI
Le recensioni sono ammesse solo dopo un soggiorno reale e concluso, una sola volta per
prenotazione. Contenuti offensivi, falsi o commerciali possono essere rimossi.

9. LIMITAZIONE DI RESPONSABILITA'
BookinVIP risponde del corretto funzionamento della Piattaforma. Non risponde della
qualita' dell'alloggio, del comportamento di Host e Ospiti, ne' di eventi non imputabili
alla Piattaforma, nei limiti consentiti dalla legge applicabile.

10. LEGGE APPLICABILE
Si applica la legge italiana. Restano impregiudicati i diritti inderogabili riconosciuti
al consumatore dalla legge del suo paese di residenza.

11. MODIFICHE
Le modifiche sono pubblicate su questa pagina con una nuova versione. L'uso continuato
della Piattaforma dopo la pubblicazione vale come accettazione.

12. LINGUA
Questi Termini sono forniti in piu' lingue per comodita'. In caso di divergenza fa fede
la versione ITALIANA.
""",

"en": """TERMS AND CONDITIONS OF SERVICE — BOOKINVIP
Version {VER} · Last updated: {VER}
Operator: {SOC}, VAT {PIVA}, {IND} — {EMAIL}

1. PURPOSE AND ROLE OF BOOKINVIP
BookinVIP is a technology intermediation platform connecting Hosts (owners or managers of
accommodation) and Guests for stay bookings. BookinVIP does NOT own, operate or control
the accommodation. The stay contract is concluded DIRECTLY between Host and Guest;
BookinVIP provides the tools (listing, booking, payment, voucher, digital check-in).

2. ACCEPTANCE
By using the Platform you accept these Terms and the Privacy Notice. If you do not accept
them, do not use the service.

3. HOST OBLIGATIONS
The Host warrants that: they are entitled to offer the accommodation and comply with local
rules (licences, guest registration, tourist tax, safety); listing information and photos
are truthful and up to date; the availability shown is real; binding statements (e.g. "no
allergens", "pet-friendly") are true. If they prove false, the Guest is entitled to a
refund and the Host owes a penalty under the Platform mechanism.

4. BOOKING AND PAYMENT (GUEST)
The price shown is calculated and signed by the system: it cannot be altered from the
browser. The Guest pays the clean price: no platform commission is charged to the Guest.
Payment is processed by an authorised provider (Stripe); BookinVIP does not store card
data.

5. COSTS BORNE BY THE HOST
Platform commission: {PROMO}% for the first {GG} days from registration, then {FASE1}% up
to one year, then {REGIME}% thereafter, on bookings originating from the marketplace;
{DIRETTO}% on bookings originating from the Host's own direct link.
TECHNICAL FEE: in addition to the commission, a fixed technical fee of {TECNICA}% of the
transaction amount is borne solely by the Host and is ALWAYS DUE in every period —
including while the commission is {PROMO}% — to cover payment provider costs. The Platform
earns no margin on this item.

6. PAYOUTS
The Host's share is held in guarantee until the Guest's confirmation or the automatic
release provided by the Platform; it is then transferred to the connected account.
Payouts may be withheld where the law so requires (tax identification obligations) until
the position is regularised.

7. CANCELLATIONS AND PENALTIES
Cancellation conditions are shown on each listing. If the Host cancels an already paid
booking, or the accommodation turns out to be unavailable, a penalty equal to {PENALE}% of
the amount is due, offset against the Host's future earnings or recorded as a debt.

8. REVIEWS
Reviews are allowed only after a real, completed stay, once per booking. Offensive, false
or commercial content may be removed.

9. LIMITATION OF LIABILITY
BookinVIP is responsible for the proper functioning of the Platform. It is not responsible
for the quality of the accommodation, the conduct of Hosts and Guests, or events not
attributable to the Platform, to the extent permitted by applicable law.

10. GOVERNING LAW
Italian law applies. Mandatory consumer rights under the law of the consumer's country of
residence remain unaffected.

11. CHANGES
Changes are published on this page with a new version. Continued use of the Platform after
publication constitutes acceptance.

12. LANGUAGE
These Terms are provided in several languages for convenience. In case of discrepancy, the
ITALIAN version prevails.
""",
}


def _componi(modello: str, versione: str) -> str:
    p = _percentuali()
    return modello.format(
        VER=versione, SOC=GESTORE["ragione_sociale"], PIVA=GESTORE["piva"],
        IND=GESTORE["indirizzo"], EMAIL=GESTORE["email"],
        PROMO=p["promo"], GG=p["giorni_promo"], FASE1=p["fase1"],
        REGIME=p["regime"], DIRETTO=p["diretto"], TECNICA=p["tecnica"],
        PENALE=_penale())


def lingue_disponibili(documento: str = "termini") -> Tuple[str, ...]:
    """Le lingue REALMENTE fornite per quel documento. Non quelle dichiarate: quelle
    che esistono davvero — cosi' il selettore non puo' offrire una pagina vuota."""
    tabella = _TERMINI if documento == "termini" else _PRIVACY
    return tuple(l for l in LINGUE if l in tabella)


def testo_termini(lang: str = "it") -> str:
    modello = _TERMINI.get(str(lang or "it").lower()[:2]) or _TERMINI["it"]
    return _componi(modello, TERMINI_VERSIONE)


def testo_privacy(lang: str = "it") -> str:
    modello = _PRIVACY.get(str(lang or "it").lower()[:2]) or _PRIVACY["it"]
    return _componi(modello, PRIVACY_VERSIONE)


def impronta(testo: str) -> str:
    return hashlib.sha256(str(testo).encode("utf-8")).hexdigest()


def documento(nome: str, lang: str = "it") -> Dict[str, Any]:
    """Il documento pronto da servire: testo, versione, impronta, lingue disponibili
    e QUALE FA FEDE. Non solleva mai."""
    try:
        nome = "privacy" if str(nome).lower().startswith("priv") else "termini"
        testo = testo_privacy(lang) if nome == "privacy" else testo_termini(lang)
        versione = PRIVACY_VERSIONE if nome == "privacy" else TERMINI_VERSIONE
        disponibili = lingue_disponibili(nome)
        chiesta = str(lang or "it").lower()[:2]
        return {
            "documento": nome, "versione": versione, "testo": testo,
            "doc_sha256": impronta(testo),
            "lang": chiesta if chiesta in disponibili else LINGUA_CHE_FA_FEDE,
            "lingue": list(disponibili),
            "lingua_che_fa_fede": LINGUA_CHE_FA_FEDE,
            "tradotto": chiesta in disponibili,
        }
    except Exception:
        logger.error("documento legale non componibile (ISOLATO)", exc_info=True)
        return {"documento": str(nome), "errore": "non_disponibile"}


# ═════════════════════════════════════════════════════════════════════════════════
#  INFORMATIVA PRIVACY (GDPR artt. 13-14)
# ═════════════════════════════════════════════════════════════════════════════════
_PRIVACY: Dict[str, str] = {
"de": """DATENSCHUTZERKLAERUNG — BOOKINVIP
Version {VER} · Letzte Aktualisierung: {VER}
Verantwortlicher: {SOC}, USt-IdNr. {PIVA}, {IND} — {EMAIL}

Diese Erklaerung erfolgt gemaess Art. 13 und 14 der Verordnung (EU) 2016/679 (DSGVO).

1. WELCHE DATEN WIR VERARBEITEN
Registrierungsdaten: E-Mail, Passwort (verschluesselt und nicht umkehrbar gespeichert),
Firmenname, Land.
Buchungsdaten: Zeitraum, Anzahl der Gaeste, Betraege, Nachrichten mit der Gegenseite.
Steuerdaten des Gastgebers: Steuernummer oder USt-IdNr., Anschrift, IBAN — nur dann
erhoben, wenn das Gesetz es verlangt (EU-Richtlinie 2021/514, DAC7).
Technische Daten: IP-Adresse, Geraetetyp, Datum und Uhrzeit relevanter Vorgaenge.
Wir verarbeiten KEINE Kartendaten: die Zahlung erfolgt beim zugelassenen Anbieter
(Stripe), der sie unmittelbar verwahrt.
Wir speichern KEINE Ausweisdokumente: die Identitaetspruefung, sofern sie stattfindet,
wird von einem Dritten durchgefuehrt, der uns nur das Ergebnis zurueckmeldet.

2. WARUM UND AUF WELCHER RECHTSGRUNDLAGE
Zur Vertragserfuellung (Art. 6.1.b): Konto anlegen, Buchungen und Zahlungen abwickeln.
Zur Erfuellung rechtlicher Pflichten (Art. 6.1.c): Steuer, Buchhaltung, Geldwaesche,
Meldungen an Behoerden.
Aus berechtigtem Interesse (Art. 6.1.f): Sicherheit der Plattform, Betrugspraevention,
Nachweis vertraglicher Zustimmungen.
Mit Ihrer Einwilligung (Art. 6.1.a), soweit erforderlich: Werbemitteilungen.

3. DIE NACHWEISE DER ZUSTIMMUNG
Wenn Sie den Vertrag, die missbraeuchlichen Klauseln oder diese Erklaerung annehmen,
speichern wir einen signierten Eintrag mit: Version des Dokuments, dessen kryptografischem
Fingerabdruck, IP-Adresse, Geraetebeschreibung, Datum und Uhrzeit. Er dient dem Nachweis,
was Sie wann angenommen haben. Rechtsgrundlage ist das berechtigte Interesse am Nachweis.

4. WIE LANGE
Kontodaten: solange das Konto besteht, danach 12 Monate.
Buchhaltungs- und Steuerdaten: 10 Jahre, wie gesetzlich vorgeschrieben.
Zustimmungsnachweise: fuer die Dauer der Beziehung und die Verjaehrungsfrist.
Technische Sicherheitsdaten: 12 Monate.

5. AN WEN WIR SIE WEITERGEBEN
An den Zahlungsdienstleister (Stripe), den E-Mail-Anbieter, den Anbieter der
Identitaetspruefung sofern genutzt, an Behoerden soweit gesetzlich vorgeschrieben, und an
die Gegenseite der Buchung nur im fuer den Aufenthalt erforderlichen Umfang.
Wir verkaufen Ihre Daten an niemanden.

6. UEBERMITTLUNGEN AUSSERHALB DER EUROPAEISCHEN UNION
Einige Anbieter koennen Daten ausserhalb des Europaeischen Wirtschaftsraums verarbeiten.
In diesem Fall erfolgt die Uebermittlung auf Grundlage von Angemessenheitsbeschluessen
oder von der Europaeischen Kommission genehmigten Standardvertragsklauseln.

7. IHRE RECHTE
Sie koennen jederzeit verlangen: Auskunft ueber Ihre Daten, Berichtigung, Loeschung,
Einschraenkung der Verarbeitung, Datenuebertragbarkeit, sowie der auf berechtigtem
Interesse beruhenden Verarbeitung widersprechen.
Sie koennen eine Einwilligung widerrufen, ohne die Rechtmaessigkeit der bisherigen
Verarbeitung zu beruehren.
Schreiben Sie an {EMAIL}. Sie haben zudem das Recht auf Beschwerde bei einer
Aufsichtsbehoerde.

8. AUTOMATISIERTE ENTSCHEIDUNGEN
Wir treffen keine ausschliesslich automatisierten Entscheidungen mit Rechtswirkung Ihnen
gegenueber. Preise koennen automatisch berechnet werden, ohne Sie als Person zu
profilieren.

9. SICHERHEIT
Passwoerter werden nie im Klartext gespeichert. Die Kommunikation ist verschluesselt.
Rechtliche Nachweise sind kryptografisch signiert; jede Manipulation ist nachweisbar.

10. SPRACHE
Diese Erklaerung wird der Bequemlichkeit halber in mehreren Sprachen bereitgestellt. Bei
Abweichungen ist die ITALIENISCHE Fassung massgeblich.
""",

"pt": """AVISO DE PRIVACIDADE — BOOKINVIP
Versao {VER} · Ultima atualizacao: {VER}
Responsavel pelo tratamento: {SOC}, NIF/IVA {PIVA}, {IND} — {EMAIL}

Este aviso e prestado nos termos dos artigos 13.o e 14.o do Regulamento (UE) 2016/679
(RGPD).

1. QUE DADOS TRATAMOS
Dados de registo: email, palavra-passe (guardada cifrada e nao reversivel), denominacao
social, pais.
Dados de reserva: datas, numero de hospedes, montantes, comunicacoes com a outra parte.
Dados fiscais do anfitriao: numero de identificacao fiscal ou de IVA, morada, IBAN —
solicitados apenas quando a lei o exige (Diretiva UE 2021/514, DAC7).
Dados tecnicos: endereco IP, tipo de dispositivo, data e hora das acoes relevantes.
NAO tratamos os dados do seu cartao: o pagamento ocorre no prestador autorizado (Stripe),
que os guarda diretamente.
NAO conservamos documentos de identidade: a verificacao de identidade, quando ocorre, e
realizada por um prestador terceiro que apenas nos devolve o resultado.

2. PORQUE OS TRATAMOS E COM QUE FUNDAMENTO
Para execucao do contrato (art. 6.1.b): criar a conta, gerir reservas e pagamentos.
Para cumprir obrigacoes legais (art. 6.1.c): fiscais, contabilisticas, branqueamento de
capitais, comunicacoes as autoridades.
Por interesse legitimo (art. 6.1.f): seguranca da plataforma, prevencao de fraude, prova
das aceitacoes contratuais.
Com o seu consentimento (art. 6.1.a), quando exigido: comunicacoes promocionais.

3. AS PROVAS DE ACEITACAO
Quando aceita o contrato, as clausulas abusivas ou este aviso, conservamos um registo
assinado com: versao do documento, a sua impressao criptografica, endereco IP, descricao
do dispositivo, data e hora. Serve para provar o que aceitou e quando. O fundamento e o
interesse legitimo na prova.

4. DURANTE QUANTO TEMPO
Dados de conta: enquanto a conta existir, depois 12 meses.
Dados contabilisticos e fiscais: 10 anos, conforme a lei exige.
Provas de aceitacao: durante toda a relacao e o prazo de prescricao.
Dados tecnicos de seguranca: 12 meses.

5. A QUEM OS COMUNICAMOS
Ao prestador de pagamentos (Stripe), ao prestador de correio eletronico, ao prestador de
verificacao de identidade quando utilizado, as autoridades quando a lei o exige, e a outra
parte da reserva apenas no necessario para a estadia.
Nao vendemos os seus dados a ninguem.

6. TRANSFERENCIAS PARA FORA DA UNIAO EUROPEIA
Alguns prestadores podem tratar dados fora do Espaco Economico Europeu. Nesse caso a
transferencia assenta em decisoes de adequacao ou em clausulas contratuais-tipo aprovadas
pela Comissao Europeia.

7. OS SEUS DIREITOS
A qualquer momento pode solicitar: acesso aos seus dados, retificacao, apagamento,
limitacao do tratamento, portabilidade, e opor-se ao tratamento baseado no interesse
legitimo.
Pode retirar o consentimento quando o tratamento nele se basear, sem afetar a licitude do
tratamento anterior.
Escreva para {EMAIL}. Tem ainda direito de reclamar junto da autoridade de controlo (em
Portugal, a CNPD).

8. DECISOES AUTOMATIZADAS
Nao tomamos decisoes exclusivamente automatizadas que produzam efeitos juridicos sobre si.
Os precos podem ser calculados automaticamente, sem elaborar o seu perfil.

9. SEGURANCA
As palavras-passe nunca sao guardadas em texto simples. As comunicacoes sao cifradas. As
provas legais sao assinadas criptograficamente e qualquer adulteracao e demonstravel.

10. IDIOMA
Este aviso e prestado em varios idiomas por comodidade. Em caso de divergencia prevalece a
versao ITALIANA.
""",

"ja": """プライバシーポリシー — BOOKINVIP
バージョン {VER} · 最終更新日：{VER}
管理者：{SOC}、付加価値税番号 {PIVA}、{IND} — {EMAIL}

本ポリシーは、EU一般データ保護規則（GDPR、規則(EU)2016/679）第13条および第14条に基づき提供
されます。

1. 取り扱うデータ
登録情報：メールアドレス、パスワード（暗号化され復元不可能な形で保存）、事業者名、国。
予約情報：日程、宿泊人数、金額、相手方とのやり取り。
ホストの税務情報：納税者番号または付加価値税番号、住所、IBAN — 法律が求める場合にのみ取得
します（EU指令2021/514、DAC7）。
技術情報：IPアドレス、端末の種類、重要な操作の日時。
カード情報は取り扱いません：決済は認可された決済事業者（Stripe）で行われ、同社が直接保管し
ます。
本人確認書類は保存しません：本人確認を行う場合、第三者事業者が実施し、当社には結果のみが返
されます。

2. 利用目的と法的根拠
契約の履行のため（第6条1項b）：アカウント作成、予約および決済の処理。
法的義務の遵守のため（第6条1項c）：税務、会計、マネーロンダリング防止、当局への報告。
正当な利益のため（第6条1項f）：プラットフォームの安全性、不正防止、契約同意の証明。
同意に基づく場合（第6条1項a）：販売促進のご案内。

3. 同意の証拠
契約、不当条項、または本ポリシーに同意された際、当社は次を含む署名付きの記録を保存します：
文書のバージョン、その暗号学的ハッシュ値、IPアドレス、端末の説明、日時。何にいつ同意したか
を証明するためのものです。法的根拠は証拠に関する正当な利益です。

4. 保存期間
アカウント情報：アカウントが存在する間、その後12か月。
会計・税務情報：法律の定めにより10年。
同意の証拠：関係の継続期間および時効期間。
技術的な安全性の情報：12か月。

5. 提供先
決済事業者（Stripe）、メール送信事業者、本人確認事業者（利用する場合）、法律が求める場合の
当局、および滞在に必要な範囲での予約の相手方。
当社はお客様のデータを誰にも販売しません。

6. 欧州連合域外への移転
一部の事業者は欧州経済領域外でデータを取り扱う場合があります。その場合、移転は十分性認定
または欧州委員会が承認した標準契約条項に基づいて行われます。

7. お客様の権利
いつでも次を請求できます：データへのアクセス、訂正、削除、処理の制限、データポータビリティ、
および正当な利益に基づく処理への異議。
同意に基づく処理については同意を撤回できます。撤回前の処理の適法性には影響しません。
{EMAIL} までご連絡ください。監督機関へ苦情を申し立てる権利もあります。

8. 自動化された決定
お客様に法的効果を生じさせる、完全に自動化された決定は行いません。価格は自動的に計算される
ことがありますが、お客様個人のプロファイリングは行いません。

9. 安全管理
パスワードは平文で保存しません。通信は暗号化されます。法的証拠は暗号署名されており、改ざん
は証明可能です。

10. 言語
本ポリシーは利便性のため複数の言語で提供されます。相違がある場合は、イタリア語版が優先しま
す。
""",

"zh": """隐私政策 — BOOKINVIP
版本 {VER} · 最后更新：{VER}
数据控制者：{SOC}，增值税号 {PIVA}，{IND} — {EMAIL}

本政策依据《欧盟通用数据保护条例》（GDPR，条例(EU)2016/679）第13条和第14条提供。

1. 我们处理哪些数据
注册数据：电子邮箱、密码（以加密且不可还原的方式保存）、企业名称、国家。
预订数据：日期、入住人数、金额、与对方的沟通记录。
房东税务数据：税号或增值税号、地址、IBAN — 仅在法律要求时收集（欧盟指令2021/514，DAC7）。
技术数据：IP地址、设备类型、重要操作的日期和时间。
我们不处理您的银行卡数据：付款在获授权的支付服务商（Stripe）完成，由其直接保管。
我们不保存身份证件：如需身份验证，由第三方服务商执行，仅将结果返回给我们。

2. 处理目的与法律依据
为履行合同（第6.1.b条）：创建账户、处理预订与付款。
为遵守法律义务（第6.1.c条）：税务、会计、反洗钱、向主管机关报告。
基于正当利益（第6.1.f条）：平台安全、防范欺诈、合同同意的证据。
在需要时基于您的同意（第6.1.a条）：推广信息。

3. 同意的证据
当您接受合同、不公平条款或本政策时，我们保存一条签名记录，包含：文件版本、其加密指纹、IP
地址、设备说明、日期和时间。用于证明您接受了什么以及何时接受。法律依据是对证据的正当利益。

4. 保存多久
账户数据：账户存续期间，之后12个月。
会计与税务数据：依法保存10年。
同意证据：关系存续期间及诉讼时效期间。
技术安全数据：12个月。

5. 我们向谁提供
支付服务商（Stripe）、邮件服务商、使用时的身份验证服务商、法律要求时的主管机关，以及预订
的对方（仅限入住所必需的范围）。
我们不会将您的数据出售给任何人。

6. 向欧盟境外的传输
部分服务商可能在欧洲经济区以外处理数据。此时，传输依据充分性决定或欧盟委员会批准的标准合同
条款进行。

7. 您的权利
您可随时要求：访问您的数据、更正、删除、限制处理、数据可携，并可反对基于正当利益的处理。
在处理基于同意时，您可撤回同意，且不影响撤回前处理的合法性。
请联系 {EMAIL}。您还有权向监管机关投诉。

8. 自动化决策
我们不会作出仅基于自动化处理、对您产生法律效力的决定。价格可能自动计算，但不会对您本人进行
画像。

9. 安全
密码绝不以明文保存。通信均经加密传输。法律证据经过密码学签名，任何篡改均可被证明。

10. 语言
本政策为方便起见提供多种语言版本。如有分歧，以意大利语版本为准。
""",

"it": """INFORMATIVA SULLA PRIVACY — BOOKINVIP
Versione {VER} · Ultimo aggiornamento: {VER}
Titolare del trattamento: {SOC}, P.IVA {PIVA}, {IND} — {EMAIL}

Questa informativa e' resa ai sensi degli artt. 13 e 14 del Regolamento (UE) 2016/679
(GDPR).

1. QUALI DATI TRATTIAMO
Dati di registrazione: email, password (conservata in forma cifrata e non reversibile),
ragione sociale, paese.
Dati di prenotazione: date, numero di ospiti, importi, comunicazioni con la controparte.
Dati fiscali dell'Host: codice fiscale o partita IVA, indirizzo, IBAN — richiesti solo
quando la legge lo impone (Direttiva UE 2021/514, DAC7).
Dati tecnici: indirizzo IP, tipo di dispositivo, data e ora delle azioni rilevanti.
NON trattiamo i dati della tua carta: il pagamento avviene presso il gestore autorizzato
(Stripe), che li custodisce direttamente.
NON conserviamo documenti d'identita': la verifica dell'identita', quando avviene, e'
eseguita da un fornitore terzo che ci restituisce solo l'esito.

2. PERCHE' LI TRATTIAMO E CON QUALE BASE GIURIDICA
Per eseguire il contratto che ci lega (art. 6.1.b): creare l'account, gestire prenotazioni
e pagamenti.
Per adempiere a obblighi di legge (art. 6.1.c): fiscali, contabili, antiriciclaggio,
comunicazioni alle autorita'.
Per un legittimo interesse (art. 6.1.f): sicurezza della piattaforma, prevenzione delle
frodi, prova delle accettazioni contrattuali.
Con il tuo consenso (art. 6.1.a), quando richiesto: comunicazioni promozionali.

3. LE PROVE DI ACCETTAZIONE
Quando accetti il contratto, le clausole vessatorie o questa informativa, conserviamo una
riga firmata con: versione del documento, sua impronta crittografica, indirizzo IP,
descrizione del dispositivo, data e ora. Serve a dimostrare cosa hai accettato e quando.
La base giuridica e' il legittimo interesse alla prova.

4. PER QUANTO TEMPO
Dati di account: finche' l'account esiste, poi 12 mesi.
Dati contabili e fiscali: 10 anni, come impone la legge.
Prove di accettazione: per tutta la durata del rapporto e per il periodo di prescrizione.
Dati tecnici di sicurezza: 12 mesi.

5. A CHI LI COMUNICHIAMO
Al gestore dei pagamenti (Stripe), al fornitore di posta elettronica, al fornitore di
verifica identita' quando usato, alle autorita' quando la legge lo impone, e alla
controparte della prenotazione limitatamente a cio' che serve per il soggiorno.
Non vendiamo i tuoi dati a nessuno.

6. TRASFERIMENTI FUORI DALL'UNIONE EUROPEA
Alcuni fornitori possono trattare dati fuori dallo Spazio Economico Europeo. In tal caso
il trasferimento avviene sulla base di decisioni di adeguatezza o di clausole contrattuali
standard approvate dalla Commissione Europea.

7. I TUOI DIRITTI
Puoi chiedere in ogni momento: accesso ai tuoi dati, rettifica, cancellazione, limitazione
del trattamento, portabilita', e opporti al trattamento fondato sul legittimo interesse.
Puoi revocare il consenso quando il trattamento si fonda su di esso, senza pregiudicare la
liceita' del trattamento precedente.
Scrivi a {EMAIL}. Hai inoltre diritto di reclamo all'autorita' di controllo (in Italia, il
Garante per la protezione dei dati personali).

8. DECISIONI AUTOMATIZZATE
Non prendiamo decisioni interamente automatizzate che producano effetti giuridici su di
te. I prezzi possono essere calcolati automaticamente, ma non profilano la tua persona.

9. SICUREZZA
Le password non sono conservate in chiaro. Le comunicazioni viaggiano cifrate. Le prove
legali sono firmate crittograficamente e ogni manomissione e' dimostrabile.

10. LINGUA
Questa informativa e' fornita in piu' lingue per comodita'. In caso di divergenza fa fede
la versione ITALIANA.
""",

"en": """PRIVACY NOTICE — BOOKINVIP
Version {VER} · Last updated: {VER}
Data controller: {SOC}, VAT {PIVA}, {IND} — {EMAIL}

This notice is provided pursuant to Articles 13 and 14 of Regulation (EU) 2016/679 (GDPR).

1. WHAT DATA WE PROCESS
Registration data: email, password (stored encrypted and non-reversible), business name,
country.
Booking data: dates, number of guests, amounts, messages with the other party.
Host tax data: tax code or VAT number, address, IBAN — requested only where the law
requires it (EU Directive 2021/514, DAC7).
Technical data: IP address, device type, date and time of relevant actions.
We do NOT process your card details: payment takes place with the authorised provider
(Stripe), which holds them directly.
We do NOT store identity documents: identity verification, where it occurs, is performed
by a third-party provider that returns only the outcome to us.

2. WHY WE PROCESS THEM AND ON WHAT LEGAL BASIS
To perform our contract (Art. 6.1.b): creating the account, handling bookings and payments.
To comply with legal obligations (Art. 6.1.c): tax, accounting, anti-money-laundering,
reporting to authorities.
For a legitimate interest (Art. 6.1.f): platform security, fraud prevention, evidence of
contractual acceptances.
With your consent (Art. 6.1.a), where required: promotional communications.

3. EVIDENCE OF ACCEPTANCE
When you accept the agreement, the unfair-terms clauses or this notice, we keep a signed
record containing: document version, its cryptographic fingerprint, IP address, device
description, date and time. It serves to prove what you accepted and when. The legal basis
is the legitimate interest in evidence.

4. HOW LONG WE KEEP THEM
Account data: as long as the account exists, then 12 months.
Accounting and tax data: 10 years, as required by law.
Evidence of acceptance: for the duration of the relationship and the limitation period.
Technical security data: 12 months.

5. WHO WE SHARE THEM WITH
The payment provider (Stripe), the email provider, the identity verification provider when
used, the authorities where the law requires it, and the other party to the booking, only
to the extent needed for the stay.
We do not sell your data to anyone.

6. TRANSFERS OUTSIDE THE EUROPEAN UNION
Some providers may process data outside the European Economic Area. In that case the
transfer takes place on the basis of adequacy decisions or standard contractual clauses
approved by the European Commission.

7. YOUR RIGHTS
At any time you may request: access to your data, rectification, erasure, restriction of
processing, portability, and object to processing based on legitimate interest.
You may withdraw consent where processing is based on it, without affecting the lawfulness
of prior processing.
Write to {EMAIL}. You also have the right to lodge a complaint with a supervisory
authority (in Italy, the Garante per la protezione dei dati personali).

8. AUTOMATED DECISIONS
We do not take solely automated decisions producing legal effects concerning you. Prices
may be computed automatically, but they do not profile you as a person.

9. SECURITY
Passwords are never stored in clear text. Communications travel encrypted. Legal evidence
is cryptographically signed and any tampering is demonstrable.

10. LANGUAGE
This notice is provided in several languages for convenience. In case of discrepancy, the
ITALIAN version prevails.
""",

"es": """AVISO DE PRIVACIDAD — BOOKINVIP
Version {VER} · Ultima actualizacion: {VER}
Responsable del tratamiento: {SOC}, NIF/IVA {PIVA}, {IND} — {EMAIL}

Este aviso se facilita conforme a los articulos 13 y 14 del Reglamento (UE) 2016/679
(RGPD).

1. QUE DATOS TRATAMOS
Datos de registro: correo electronico, contrasena (guardada cifrada y no reversible),
razon social, pais.
Datos de reserva: fechas, numero de huespedes, importes, comunicaciones con la otra parte.
Datos fiscales del anfitrion: NIF o numero de IVA, direccion, IBAN — solicitados solo
cuando la ley lo exige (Directiva UE 2021/514, DAC7).
Datos tecnicos: direccion IP, tipo de dispositivo, fecha y hora de las acciones relevantes.
NO tratamos los datos de tu tarjeta: el pago se realiza en el proveedor autorizado
(Stripe), que los custodia directamente.
NO conservamos documentos de identidad: la verificacion de identidad, cuando se produce,
la realiza un proveedor externo que solo nos devuelve el resultado.

2. POR QUE LOS TRATAMOS Y CON QUE BASE JURIDICA
Para ejecutar el contrato (art. 6.1.b): crear la cuenta, gestionar reservas y pagos.
Para cumplir obligaciones legales (art. 6.1.c): fiscales, contables, prevencion del
blanqueo, comunicaciones a las autoridades.
Por interes legitimo (art. 6.1.f): seguridad de la plataforma, prevencion del fraude,
prueba de las aceptaciones contractuales.
Con tu consentimiento (art. 6.1.a), cuando proceda: comunicaciones promocionales.

3. LAS PRUEBAS DE ACEPTACION
Cuando aceptas el contrato, las clausulas abusivas o este aviso, conservamos un registro
firmado con: version del documento, su huella criptografica, direccion IP, descripcion del
dispositivo, fecha y hora. Sirve para demostrar que aceptaste y cuando. La base juridica es
el interes legitimo en la prueba.

4. DURANTE CUANTO TIEMPO
Datos de cuenta: mientras exista la cuenta, despues 12 meses.
Datos contables y fiscales: 10 anos, como exige la ley.
Pruebas de aceptacion: durante toda la relacion y el plazo de prescripcion.
Datos tecnicos de seguridad: 12 meses.

5. A QUIEN LOS COMUNICAMOS
Al proveedor de pagos (Stripe), al proveedor de correo, al proveedor de verificacion de
identidad cuando se usa, a las autoridades cuando la ley lo exige, y a la otra parte de la
reserva unicamente en lo necesario para la estancia.
No vendemos tus datos a nadie.

6. TRANSFERENCIAS FUERA DE LA UNION EUROPEA
Algunos proveedores pueden tratar datos fuera del Espacio Economico Europeo. En tal caso la
transferencia se basa en decisiones de adecuacion o en clausulas contractuales tipo
aprobadas por la Comision Europea.

7. TUS DERECHOS
En cualquier momento puedes solicitar: acceso a tus datos, rectificacion, supresion,
limitacion del tratamiento, portabilidad, y oponerte al tratamiento basado en el interes
legitimo.
Puedes retirar el consentimiento cuando el tratamiento se base en el, sin afectar a la
licitud del tratamiento anterior.
Escribe a {EMAIL}. Tambien tienes derecho a reclamar ante la autoridad de control (en
Espana, la Agencia Espanola de Proteccion de Datos).

8. DECISIONES AUTOMATIZADAS
No adoptamos decisiones exclusivamente automatizadas que produzcan efectos juridicos sobre
ti. Los precios pueden calcularse automaticamente, pero no elaboran un perfil tuyo.

9. SEGURIDAD
Las contrasenas nunca se guardan en claro. Las comunicaciones viajan cifradas. Las pruebas
legales estan firmadas criptograficamente y cualquier manipulacion es demostrable.

10. IDIOMA
Este aviso se facilita en varios idiomas por comodidad. En caso de discrepancia prevalece
la version ITALIANA.
""",

"fr": """POLITIQUE DE CONFIDENTIALITE — BOOKINVIP
Version {VER} · Derniere mise a jour : {VER}
Responsable du traitement : {SOC}, TVA {PIVA}, {IND} — {EMAIL}

La presente politique est fournie conformement aux articles 13 et 14 du Reglement (UE)
2016/679 (RGPD).

1. QUELLES DONNEES NOUS TRAITONS
Donnees d'inscription : adresse e-mail, mot de passe (conserve chiffre et non reversible),
raison sociale, pays.
Donnees de reservation : dates, nombre de voyageurs, montants, echanges avec l'autre partie.
Donnees fiscales de l'hote : numero fiscal ou de TVA, adresse, IBAN — demandes uniquement
lorsque la loi l'exige (Directive UE 2021/514, DAC7).
Donnees techniques : adresse IP, type d'appareil, date et heure des actions pertinentes.
Nous ne traitons PAS les donnees de votre carte : le paiement a lieu chez le prestataire
agree (Stripe), qui les conserve directement.
Nous ne conservons PAS de pieces d'identite : la verification d'identite, lorsqu'elle a
lieu, est effectuee par un prestataire tiers qui ne nous renvoie que le resultat.

2. POURQUOI ET SUR QUELLE BASE LEGALE
Pour executer le contrat (art. 6.1.b) : creer le compte, gerer reservations et paiements.
Pour respecter des obligations legales (art. 6.1.c) : fiscales, comptables, lutte contre le
blanchiment, communications aux autorites.
Pour un interet legitime (art. 6.1.f) : securite de la plateforme, prevention de la fraude,
preuve des acceptations contractuelles.
Avec votre consentement (art. 6.1.a), lorsque requis : communications promotionnelles.

3. LES PREUVES D'ACCEPTATION
Lorsque vous acceptez le contrat, les clauses abusives ou la presente politique, nous
conservons un enregistrement signe comportant : version du document, son empreinte
cryptographique, adresse IP, description de l'appareil, date et heure. Il sert a prouver ce
que vous avez accepte et quand. La base legale est l'interet legitime a la preuve.

4. PENDANT COMBIEN DE TEMPS
Donnees de compte : tant que le compte existe, puis 12 mois.
Donnees comptables et fiscales : 10 ans, comme l'impose la loi.
Preuves d'acceptation : pendant toute la relation et le delai de prescription.
Donnees techniques de securite : 12 mois.

5. A QUI NOUS LES COMMUNIQUONS
Au prestataire de paiement (Stripe), au prestataire de messagerie, au prestataire de
verification d'identite lorsqu'il est utilise, aux autorites lorsque la loi l'exige, et a
l'autre partie de la reservation, uniquement dans la mesure necessaire au sejour.
Nous ne vendons vos donnees a personne.

6. TRANSFERTS HORS DE L'UNION EUROPEENNE
Certains prestataires peuvent traiter des donnees hors de l'Espace economique europeen. Le
transfert repose alors sur des decisions d'adequation ou des clauses contractuelles types
approuvees par la Commission europeenne.

7. VOS DROITS
A tout moment vous pouvez demander : l'acces a vos donnees, leur rectification, leur
effacement, la limitation du traitement, la portabilite, et vous opposer au traitement
fonde sur l'interet legitime.
Vous pouvez retirer votre consentement lorsque le traitement s'y fonde, sans porter atteinte
a la liceite du traitement anterieur.
Ecrivez a {EMAIL}. Vous avez egalement le droit d'introduire une reclamation aupres d'une
autorite de controle (en France, la CNIL).

8. DECISIONS AUTOMATISEES
Nous ne prenons pas de decisions exclusivement automatisees produisant des effets
juridiques a votre egard. Les prix peuvent etre calcules automatiquement, sans profilage de
votre personne.

9. SECURITE
Les mots de passe ne sont jamais conserves en clair. Les communications sont chiffrees. Les
preuves legales sont signees cryptographiquement et toute alteration est demontrable.

10. LANGUE
La presente politique est fournie en plusieurs langues par commodite. En cas de divergence,
la version ITALIENNE prevaut.
""",

}
