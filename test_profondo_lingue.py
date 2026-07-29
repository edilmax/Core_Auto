"""GUARDIA PROFONDA — LE 8 LINGUE, FINO IN FONDO (it/en/es/fr/de/pt/ja/zh).

CONTRATTO (cosa questo file pretende, in 8 righe)
  La lingua che l'utente sceglie deve attraversare TUTTA la macchina, non solo la vetrina:
  le risposte API che contengono testo, le pagine renderizzate dal server (landing citta',
  blog, voucher, recensione, link-non-valido, grazie/annullato) e TUTTE le email — quella
  di conferma come quelle che arrivano giorni dopo. La lingua scelta al momento della
  prenotazione viaggia dentro il gettone FIRMATO del voucher ed e' la fonte di verita' per
  ogni messaggio successivo. Una lingua che non conosciamo NON e' italiano: e' inglese.

CONFINI (la matrice provata qui sotto)
  · lingua supportata (8)            -> quella lingua, testo davvero diverso dalle altre
  · lingua ignota ('sw','klingon')   -> IDENTICA, byte per byte, alla versione INGLESE
  · lingua vuota / None / non-stringa-> INGLESE
  · variante di una lingua nota      -> quella lingua o inglese, MAI una terza lingua
  · nessuna lingua nella richiesta   -> la lingua firmata nel gettone (mai un default cieco)

MODALITA' DI ERRORE sorvegliate (i modi di rompersi #3 «testi che mentono» e #11 «lingua
congelata» del CLAUDE.md)
  1. la pagina dichiara <html lang="ja"> e il testo dentro e' italiano;
  2. una lingua non prevista ricade su ITALIANO (un mercato mondiale non puo' dire
     «non lo so» = «italiano»);
  3. la traduzione esiste ma non e' cablata: il testo NON cambia fra due lingue;
  4. un pezzo di italiano resta incollato dentro una pagina straniera (bottoni, avvisi);
  5. la lingua si perde per strada: giusta nell'email di conferma, persa in quelle dopo.

INVARIANTI (asserzioni forti: stato esatto + valori veri, mai «non e' 500»)
  I1  ogni etichetta esiste in tutte e 8 le lingue (nessun buco -> nessun ripiego mascherato)
  I2  il TESTO VISIBILE cambia davvero fra due lingue qualsiasi (28 coppie, non solo l'attributo)
  I3  ogni lingua contiene la sua parola-spia ESATTA (valore vero, non «una stringa qualsiasi»)
  I4  nessuna pagina/email non italiana contiene parole ESCLUSIVE dell'italiano
  I5  lingua ignota => output IDENTICO a quello inglese (uguaglianza byte a byte)
  I6  la lingua del book -> gettone firmato -> conferma, pagamento, cancellazione
"""

import datetime
import hashlib
import html.parser
import io
import json
import os
import re
import shutil
import socket
import tempfile
import threading
import time
import unittest

import fase83_server as SRV
import fase85_pagamenti_stripe as _stripe
import fase86_email as EM
import fase97_inbound_seo as SEO
import fase185_testi_legali as LEG
import fase198_blog as BLOG
from fase61_localizzazione import (ETICHETTE_SERVIZI, ETICHETTE_STATI,
                                   LINGUE_SUPPORTATE)
from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
from fase83_server import (crea_router, pagina_recensione_html, pagina_ricevuta_html,
                           pagina_voucher_html, pagina_voucher_non_valido_html)
from fase87_stripe_webhook import firma_di_test

OTTO = ("it", "en", "es", "fr", "de", "pt", "ja", "zh")
# lingue che il prodotto NON conosce: il ripiego deve essere l'INGLESE, mai l'italiano
IGNOTE = ("sw", "xx", "klingon", "zz", "", None, 42, [])
# varianti di una lingua NOTA (maiuscole, regione): possono restare in quella lingua
# oppure ripiegare sull'inglese, mai finire in una TERZA lingua.
VARIANTI = {"IT": "it", "it-CH": "it", "ES-MX": "es", "ja_JP": "ja", "DE": "de"}


# ─────────────────────────────────────────────────────────────────────────────────
#  Attrezzi: cosa LEGGE una persona (testo visibile) e cosa e' italiano per davvero
# ─────────────────────────────────────────────────────────────────────────────────
class _SoloTestoVisibile(html.parser.HTMLParser):
    """Il testo che un essere umano vede: niente CSS, niente codice, niente <head>.
    Prende anche i testi che vivono negli attributi (placeholder, title, alt): li si
    legge sullo schermo esattamente come il resto."""

    SALTA = {"script", "style", "head"}
    ATTR_VISIBILI = ("placeholder", "title", "alt", "aria-label")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pezzi = []
        self._muto = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SALTA:
            self._muto += 1
        if self._muto:
            return
        for chiave, valore in attrs:
            if chiave in self.ATTR_VISIBILI and valore:
                self.pezzi.append(valore)

    def handle_endtag(self, tag):
        if tag in self.SALTA and self._muto:
            self._muto -= 1

    def handle_data(self, dato):
        if not self._muto and dato.strip():
            self.pezzi.append(dato.strip())


def visibile(pagina):
    """Lista dei frammenti di testo che l'utente legge davvero."""
    lettore = _SoloTestoVisibile()
    lettore.feed(str(pagina))
    return lettore.pezzi


def piatto(pagina):
    return " ".join(visibile(pagina))


# Parole ESCLUSIVE dell'italiano: non esistono uguali in spagnolo/portoghese/francese/
# inglese/tedesco. Chi mette qui una parola condivisa (es. "pagamento", identico in
# portoghese, o "total") trasforma la guardia in un generatore di falsi allarmi.
PAROLE_ESCLUSIVE_IT = (
    "prenotazione", "prenotazioni", "prenota", "soggiorno", "alloggio", "alloggi",
    "rimborso", "recensione", "recensioni", "benvenuto", "cancella", "cancellazione",
    "cancellare", "cancellata", "commissione", "ospite", "ospiti", "notte", "notti",
    "prezzo", "messaggio", "messaggi", "conferma", "confermo", "segnala",
    "segnalazione", "ricevuta", "il tuo", "la tua", "i tuoi", "le tue", "chatta",
    "scrivi", "aggiungi", "riprova", "sblocca", "sbloccano", "arrivo",
)   # NB: "pagamento" (uguale in portoghese), "gratis" (spagnolo/tedesco) e "documento"
#      NON sono spie: metterle qui trasformerebbe la guardia in un falso allarme.
_RE_IT = re.compile(
    "|".join(r"(?<![0-9a-zà-ÿ])%s(?![0-9a-zà-ÿ])" % re.escape(p)
             for p in PAROLE_ESCLUSIVE_IT), re.IGNORECASE)


def italiano_dentro(pagina):
    """I frammenti VISIBILI che contengono parole esclusivamente italiane."""
    return [p for p in visibile(pagina) if _RE_IT.search(p)]


# ─────────────────────────────────────────────────────────────────────────────────
#  Parole-spia: il VALORE VERO che deve comparire in quella lingua (mai «c'e' testo»)
# ─────────────────────────────────────────────────────────────────────────────────
SPIA_EMAIL_VOUCHER = {          # da fase86 'v_codice' + 'v_pin'
    "it": "Codice prenotazione", "en": "Booking code", "es": "Código de reserva",
    "fr": "Code de réservation", "de": "Buchungscode", "pt": "Código de reserva",
    "ja": "予約コード", "zh": "预订码"}
SPIA_EMAIL_CANC = {             # da fase86 'c_titolo'
    "it": "Prenotazione cancellata", "en": "Booking cancelled", "es": "Reserva anulada",
    "fr": "Réservation annulée", "de": "Buchung storniert", "pt": "Reserva cancelada",
    "ja": "予約をキャンセルしました", "zh": "预订已取消"}
SPIA_EMAIL_PAGATO = {           # da fase86 'pc_titolo'
    "it": "Pagamento ricevuto", "en": "Payment received", "es": "Pago recibido",
    "fr": "Paiement reçu", "de": "Zahlung erhalten", "pt": "Pagamento recebido",
    "ja": "お支払いを受け付けました", "zh": "已收到付款"}
SPIA_UI_NOTTE = {               # ETICHETTE_UI['notte'] — tutte e 8 diverse fra loro
    "it": "notte", "en": "night", "es": "noche", "fr": "nuit", "de": "Nacht",
    "pt": "noite", "ja": "泊", "zh": "晚"}
SPIA_SERVIZIO_PARCHEGGIO = {    # ETICHETTE_SERVIZI['parcheggio'] — 8 valori distinti
    "it": "Parcheggio", "en": "Parking", "es": "Aparcamiento", "fr": "Parking",
    "de": "Parkplatz", "pt": "Estacionamento", "ja": "駐車場", "zh": "停车场"}
SPIA_LANDING = {                # fase97 _T['h1']
    "it": "Tieni di più su ogni notte", "en": "Keep more on every night",
    "es": "Gana más cada noche", "fr": "Gardez plus chaque nuit",
    "de": "Behalten Sie mehr pro Nacht", "pt": "Fique com mais em cada noite",
    "ja": "1泊ごとに手元に多く残しましょう", "zh": "每晚留存更多"}
SPIA_BLOG = {                   # fase198 _UI['cta'] — 8 valori distinti
    "it": "Pubblica il tuo alloggio gratis", "en": "List your place for free",
    "es": "Publica tu alojamiento gratis", "fr": "Publiez votre logement gratuitement",
    "de": "Inserieren Sie kostenlos", "pt": "Publique o seu alojamento grátis",
    "ja": "無料で掲載する", "zh": "免费发布你的房源"}
SPIA_BLOG_TITOLO = {            # fase198 _UI['blog']
    "it": "Guida BookinVIP", "en": "BookinVIP Guide", "es": "Guía BookinVIP",
    "fr": "Guide BookinVIP", "de": "BookinVIP-Ratgeber", "pt": "Guia BookinVIP",
    "ja": "BookinVIP ガイド", "zh": "BookinVIP 指南"}
SPIA_LEGALE = {                 # prima riga dei TERMINI in ogni lingua
    "it": "TERMINI E CONDIZIONI", "en": "TERMS AND CONDITIONS",
    "es": "TERMINOS Y CONDICIONES", "fr": "CONDITIONS GENERALES",
    "de": "ALLGEMEINE GESCHAEFTSBEDINGUNGEN", "pt": "TERMOS E CONDICOES",
    "ja": "利用規約", "zh": "服务条款"}
SPIA_RICEVUTA = {               # ETICHETTE_UI['ric_totale_pagato']
    "it": "Totale pagato", "en": "Total paid", "es": "Total pagado", "fr": "Total payé",
    "de": "Gesamt bezahlt", "pt": "Total pago", "ja": "お支払い合計", "zh": "已付总额"}
SPIA_VOUCHER_PAGINA = {         # ETICHETTE_UI['voucher_ok']
    "it": "Prenotazione confermata", "en": "Booking confirmed", "es": "Reserva confirmada",
    "fr": "Réservation confirmée", "de": "Buchung bestätigt", "pt": "Reserva confirmada",
    "ja": "予約確定", "zh": "预订已确认"}


def sha256_indipendente(testo):
    """L'impronta ricalcolata QUI, non chiesta al modulo che si sta collaudando: se si
    usasse `fase185.impronta` per verificare `fase185.impronta` il confronto sarebbe
    sempre vero anche con la funzione rotta (mutante M14, sopravvissuto alla prima
    stesura di questa guardia)."""
    return hashlib.sha256(str(testo).encode("utf-8")).hexdigest()


def tutte_le_email(lingua):
    """Ogni corpo email di fase86 reso nella lingua chiesta. (nome, html)."""
    return [
        ("voucher", EM.corpo_voucher_html("Zen House", "BVIP-1", "2026-09-05",
                                          "2026-09-08", "https://x/v", pin="1234",
                                          lingua=lingua)),
        ("voucher_da_pagare", EM.corpo_voucher_html("Zen House", "BVIP-1", "2026-09-05",
                                                    "2026-09-08", "https://x/v",
                                                    payment_url="https://x/pay",
                                                    lingua=lingua)),
        ("preventivo", EM.corpo_preventivo_html("Zen House", "2026-09-05", "2026-09-08",
                                                [("A", "100.00 EUR")], "https://x/b",
                                                lingua=lingua)),
        ("pagamento", EM.corpo_pagamento_confermato_html("Zen House", "https://x/v",
                                                         54000, "JPY", lingua=lingua)),
        ("pagamento_saldo", EM.corpo_pagamento_confermato_html(
            "Zen House", "https://x/v", 5000, "EUR", lingua=lingua, saldo_cents=12000)),
        ("cancellazione", EM.corpo_cancellazione_html("Zen House", 30000, "EUR", 0,
                                                      lingua=lingua)),
        ("cancellazione_zero", EM.corpo_cancellazione_html("Zen House", 0, "EUR", 5000,
                                                           lingua=lingua)),
        ("recensione", EM.corpo_invito_recensione_html("Zen House", "https://x/r",
                                                       lingua=lingua)),
        ("controversia", EM.corpo_esito_controversia_html(30000, "EUR", lingua=lingua)),
        ("controversia_zero", EM.corpo_esito_controversia_html(0, "EUR", lingua=lingua)),
        ("payout", EM.corpo_payout_host_html(25000, "EUR", "BVIP-1", lingua=lingua)),
        ("reset", EM.corpo_reset_password_html("https://x/reset", lingua=lingua)),
        ("benvenuto", EM.corpo_benvenuto_host_html("https://x/host", lingua=lingua)),
        ("promemoria", EM.corpo_promemoria_checkin_html("Zen House", "https://x/v",
                                                        lingua=lingua)),
    ]


# ═════════════════════════════════════════════════════════════════════════════════
#  1. NESSUN BUCO: se un'etichetta manca in una lingua, il ripiego e' invisibile
# ═════════════════════════════════════════════════════════════════════════════════
class TestNessunBucoNelleTabelle(unittest.TestCase):

    def test_I1_ogni_etichetta_ui_esiste_in_tutte_e_8_le_lingue(self):
        buchi = [(k, lg) for k, v in SRV.ETICHETTE_UI.items() for lg in OTTO
                 if not v.get(lg)]
        self.assertEqual(buchi, [], "etichette UI senza traduzione: %s" % buchi[:12])

    def test_I1_ogni_servizio_e_ogni_stato_esistono_in_tutte_e_8(self):
        buchi = [(k, lg) for tab in (ETICHETTE_SERVIZI, ETICHETTE_STATI)
                 for k, v in tab.items() for lg in OTTO if not v.get(lg)]
        self.assertEqual(buchi, [], "servizi/stati senza traduzione: %s" % buchi[:12])

    def test_I1_ogni_testo_email_esiste_in_tutte_e_8(self):
        buchi = [(k, lg) for k, v in EM._TR.items() for lg in OTTO if not v.get(lg)]
        self.assertEqual(buchi, [], "testi email senza traduzione: %s" % buchi[:12])

    def test_I1_le_8_lingue_del_prodotto_sono_le_stesse_ovunque(self):
        """Se un modulo ne dichiara 7 e un altro 8, qualcuno servira' un ripiego."""
        self.assertEqual(set(LINGUE_SUPPORTATE), set(OTTO))
        self.assertEqual(set(EM.LINGUE), set(OTTO))
        self.assertEqual(set(BLOG.BLOG_LINGUE), set(OTTO))
        self.assertEqual(set(LEG.LINGUE), set(OTTO))
        self.assertEqual(set(LEG.lingue_disponibili("termini")), set(OTTO))
        self.assertEqual(set(LEG.lingue_disponibili("privacy")), set(OTTO))
        self.assertTrue(set(OTTO).issubset(set(SEO.LINGUE)))


# ═════════════════════════════════════════════════════════════════════════════════
#  2. EMAIL: 14 corpi × 8 lingue. Testo diverso, spia esatta, zero italiano di ritorno
# ═════════════════════════════════════════════════════════════════════════════════
class TestEmailNelleOttoLingue(unittest.TestCase):

    def test_I3_ogni_email_porta_la_parola_spia_ESATTA_della_sua_lingua(self):
        for lg in OTTO:
            corpi = dict(tutte_le_email(lg))
            self.assertIn(SPIA_EMAIL_VOUCHER[lg], piatto(corpi["voucher"]),
                          "voucher/%s non contiene %r" % (lg, SPIA_EMAIL_VOUCHER[lg]))
            self.assertIn(SPIA_EMAIL_CANC[lg], piatto(corpi["cancellazione"]),
                          "cancellazione/%s non contiene %r" % (lg, SPIA_EMAIL_CANC[lg]))
            self.assertIn(SPIA_EMAIL_PAGATO[lg], piatto(corpi["pagamento"]),
                          "pagamento/%s non contiene %r" % (lg, SPIA_EMAIL_PAGATO[lg]))

    def test_I2_lo_stesso_corpo_email_e_diverso_in_tutte_le_28_coppie(self):
        for nome in dict(tutte_le_email("en")):
            resi = {lg: piatto(dict(tutte_le_email(lg))[nome]) for lg in OTTO}
            uguali = [(a, b) for i, a in enumerate(OTTO) for b in OTTO[i + 1:]
                      if resi[a] == resi[b]]
            self.assertEqual(uguali, [],
                             "email '%s': lingue con testo IDENTICO (traduzione non "
                             "cablata): %s" % (nome, uguali))

    def test_I4_nessuna_email_straniera_contiene_parole_italiane(self):
        perdite = []
        for lg in OTTO:
            if lg == "it":
                continue
            for nome, corpo in tutte_le_email(lg):
                for frammento in italiano_dentro(corpo):
                    perdite.append("%s/%s -> %r" % (lg, nome, frammento[:70]))
        self.assertEqual(perdite, [],
                         "italiano rimasto incollato nelle email straniere:\n  - "
                         + "\n  - ".join(perdite[:20]))

    def test_I5_lingua_ignota_da_una_email_IDENTICA_a_quella_inglese(self):
        inglese = dict(tutte_le_email("en"))
        for ignota in IGNOTE:
            resi = dict(tutte_le_email(ignota))
            for nome in inglese:
                self.assertEqual(resi[nome], inglese[nome],
                                 "email '%s' con lingua %r non e' l'inglese"
                                 % (nome, ignota))

    def test_I5_anche_gli_OGGETTI_ripiegano_sull_inglese(self):
        chiavi = ("v_ogg_conf", "v_ogg_pay", "pc_ogg", "c_ogg", "r_ogg", "d_ogg",
                  "p_ogg", "rp_ogg", "b_ogg", "pr_ogg")
        for chiave in chiavi:
            atteso = EM.oggetto(chiave, "en")
            for ignota in IGNOTE:
                self.assertEqual(EM.oggetto(chiave, ignota), atteso,
                                 "oggetto %s con lingua %r non e' inglese" % (chiave, ignota))
            # e in giapponese NON e' l'inglese (altrimenti la tabella non e' cablata)
            self.assertNotEqual(EM.oggetto(chiave, "ja"), atteso,
                                "oggetto %s: il giapponese esce in inglese" % chiave)

    def test_l_oggetto_col_titolo_dentro_esce_nella_lingua_giusta(self):
        self.assertEqual(EM.oggetto("prev_ogg", "de", "Villa"),
                         "BookinVIP - Ihr Angebot für Villa")
        self.assertEqual(EM.oggetto("prev_ogg", "ja", "Villa"),
                         "BookinVIP - Villa のお見積り")
        self.assertEqual(EM.oggetto("prev_ogg", "sw", "Villa"),
                         "BookinVIP - Your quote for Villa")

    def test_gli_importi_restano_giusti_in_ogni_lingua(self):
        """La localizzazione non deve toccare i soldi: ¥54.000 non diventa 540.00."""
        for lg in OTTO + ("sw",):
            yen = EM.corpo_pagamento_confermato_html("Z", "https://x/v", 54000, "JPY",
                                                     lingua=lg)
            self.assertIn("54000 JPY", yen, "%s: lo yen ha preso i decimali" % lg)
            self.assertNotIn("540.00", yen, "%s: ¥54.000 mostrato come 540.00" % lg)
            euro = EM.corpo_pagamento_confermato_html("Z", "https://x/v", 15000, "EUR",
                                                      lingua=lg)
            self.assertIn("150.00 EUR", euro, "%s: l'euro ha perso i decimali" % lg)


# ═════════════════════════════════════════════════════════════════════════════════
#  3. PAGINE RENDERIZZATE DAL SERVER: landing citta', blog, link-non-valido
# ═════════════════════════════════════════════════════════════════════════════════
def _attributo_lang(pagina):
    trovato = re.search(r"<html[^>]*\blang=\"([^\"]+)\"", str(pagina))
    return trovato.group(1) if trovato else None


class TestPagineServerRendered(unittest.TestCase):

    # ── landing host per citta' (fase97) ────────────────────────────────────────
    def test_I3_landing_citta_parla_la_lingua_chiesta(self):
        for lg in OTTO:
            pagina = SEO.genera_landing_host("Roma", lingua=lg, base_url="https://b.com")
            self.assertEqual(_attributo_lang(pagina), lg)
            self.assertIn(SPIA_LANDING[lg], piatto(pagina),
                          "landing/%s non contiene %r" % (lg, SPIA_LANDING[lg]))

    def test_I2_la_landing_ha_28_versioni_diverse(self):
        resi = {lg: piatto(SEO.genera_landing_host("Roma", lingua=lg))
                for lg in OTTO}
        uguali = [(a, b) for i, a in enumerate(OTTO) for b in OTTO[i + 1:]
                  if resi[a] == resi[b]]
        self.assertEqual(uguali, [], "landing con testo identico fra lingue: %s" % uguali)

    def test_I4_la_landing_straniera_non_contiene_italiano(self):
        perdite = []
        for lg in OTTO:
            if lg == "it":
                continue
            pagina = SEO.genera_landing_host("Berlino", lingua=lg, base_url="https://b.com")
            perdite += ["%s -> %r" % (lg, f[:70]) for f in italiano_dentro(pagina)]
        self.assertEqual(perdite, [], "italiano nella landing straniera: %s" % perdite[:10])

    def test_I5_landing_con_lingua_ignota_e_IDENTICA_all_inglese(self):
        inglese = SEO.genera_landing_host("Roma", lingua="en", base_url="https://b.com")
        for ignota in IGNOTE:
            self.assertEqual(SEO.genera_landing_host("Roma", lingua=ignota,
                                                     base_url="https://b.com"),
                             inglese, "landing con lingua %r non e' inglese" % ignota)

    def test_variante_regionale_resta_nella_sua_lingua(self):
        """'es-MX' e' spagnolo (con targeting Messico), non una terza lingua: il testo
        e' quello spagnolo, l'attributo lang porta il locale completo (BCP-47)."""
        pagina = SEO.genera_landing_host("Roma", lingua="es-MX", base_url="https://b.com")
        self.assertEqual(_attributo_lang(pagina), "es-MX")
        self.assertIn(SPIA_LANDING["es"], piatto(pagina))
        self.assertNotIn(SPIA_LANDING["it"], piatto(pagina))
        self.assertIn('hreflang="es-MX"', pagina)

    def test_una_variante_di_lingua_nota_non_finisce_MAI_in_una_terza_lingua(self):
        """'IT'/'it-CH'/'ja_JP': o quella lingua, o l'inglese. Mai un idioma estraneo."""
        for variante, base in VARIANTI.items():
            for reso, dove in (
                    (piatto(SEO.genera_landing_host("Roma", lingua=variante)),
                     "landing"),
                    (piatto(BLOG.genera_indice_blog(lingua=variante)), "blog"),
                    (piatto(EM.corpo_voucher_html("Z", "B", "a", "b", "u",
                                                        lingua=variante)), "email"),
                    (LEG.documento("termini", variante)["testo"], "termini")):
                spie = {"landing": SPIA_LANDING, "blog": SPIA_BLOG,
                        "email": SPIA_EMAIL_VOUCHER, "termini": SPIA_LEGALE}[dove]
                # una spia CONDIVISA con la lingua attesa (es. "Código de reserva",
                # identico in spagnolo e portoghese) non prova nulla: si scarta.
                estranee = [lg for lg in OTTO
                            if lg not in (base, "en")
                            and spie[lg] not in (spie[base], spie["en"])
                            and spie[lg] in reso]
                self.assertEqual(estranee, [],
                                 "%s con lingua %r risponde in %s (attese: %s o en)"
                                 % (dove, variante, estranee, base))

    # ── blog multilingua (fase198) ──────────────────────────────────────────────
    def test_I3_blog_indice_e_articolo_parlano_la_lingua_chiesta(self):
        slug = str(BLOG.ARTICOLI[0]["slug"])
        for lg in OTTO:
            indice = BLOG.genera_indice_blog(lingua=lg, base_url="https://b.com")
            self.assertEqual(_attributo_lang(indice), lg)
            self.assertIn(SPIA_BLOG[lg], piatto(indice),
                          "blog/%s non contiene %r" % (lg, SPIA_BLOG[lg]))
            self.assertIn(SPIA_BLOG_TITOLO[lg], piatto(indice),
                          "blog/%s non contiene %r" % (lg, SPIA_BLOG_TITOLO[lg]))
            articolo = BLOG.genera_articolo_html(slug, lingua=lg, base_url="https://b.com")
            self.assertEqual(_attributo_lang(articolo), lg)

    def test_I2_ogni_articolo_e_diverso_in_tutte_le_28_coppie(self):
        for voce in BLOG.ARTICOLI:
            slug = str(voce["slug"])
            resi = {lg: piatto(BLOG.genera_articolo_html(slug, lingua=lg))
                    for lg in OTTO}
            uguali = [(a, b) for i, a in enumerate(OTTO) for b in OTTO[i + 1:]
                      if resi[a] == resi[b]]
            self.assertEqual(uguali, [], "articolo '%s' identico fra %s" % (slug, uguali))

    def test_I4_il_blog_straniero_non_contiene_italiano(self):
        perdite = []
        for lg in OTTO:
            if lg == "it":
                continue
            pagine = [BLOG.genera_indice_blog(lingua=lg, base_url="https://b.com")]
            pagine += [BLOG.genera_articolo_html(str(a["slug"]), lingua=lg,
                                                 base_url="https://b.com")
                       for a in BLOG.ARTICOLI]
            for pagina in pagine:
                perdite += ["%s -> %r" % (lg, f[:70]) for f in italiano_dentro(pagina)]
        self.assertEqual(perdite, [], "italiano nel blog straniero:\n  - "
                         + "\n  - ".join(perdite[:20]))

    def test_I5_blog_con_lingua_ignota_e_IDENTICO_all_inglese(self):
        slug = str(BLOG.ARTICOLI[0]["slug"])
        indice_en = BLOG.genera_indice_blog(lingua="en", base_url="https://b.com")
        art_en = BLOG.genera_articolo_html(slug, lingua="en", base_url="https://b.com")
        for ignota in IGNOTE:
            self.assertEqual(BLOG.genera_indice_blog(lingua=ignota,
                                                     base_url="https://b.com"),
                             indice_en, "indice blog con lingua %r non e' inglese" % ignota)
            self.assertEqual(BLOG.genera_articolo_html(slug, lingua=ignota,
                                                       base_url="https://b.com"),
                             art_en, "articolo blog con lingua %r non e' inglese" % ignota)

    # ── termini e privacy (fase185) ─────────────────────────────────────────────
    def test_I3_termini_e_privacy_escono_nella_lingua_chiesta(self):
        for lg in OTTO:
            doc = LEG.documento("termini", lg)
            self.assertEqual(doc["lang"], lg)
            self.assertTrue(doc["tradotto"])
            self.assertIn(SPIA_LEGALE[lg], doc["testo"],
                          "termini/%s non contiene %r" % (lg, SPIA_LEGALE[lg]))
            # l'impronta e' quella del testo SERVITO, ricalcolata da un oracolo
            # indipendente: chi firma deve poterla verificare da solo
            self.assertEqual(doc["doc_sha256"], sha256_indipendente(doc["testo"]),
                             "termini/%s: l'impronta non e' quella del testo servito" % lg)

    def test_I2_termini_e_privacy_sono_diversi_in_tutte_le_28_coppie(self):
        for nome in ("termini", "privacy"):
            resi = {lg: LEG.documento(nome, lg)["testo"] for lg in OTTO}
            uguali = [(a, b) for i, a in enumerate(OTTO) for b in OTTO[i + 1:]
                      if resi[a] == resi[b]]
            self.assertEqual(uguali, [], "%s identico fra %s" % (nome, uguali))

    def test_I5_documento_legale_con_lingua_ignota_e_INGLESE(self):
        for nome in ("termini", "privacy"):
            inglese = LEG.documento(nome, "en")
            for ignota in ("sw", "xx", "klingon", "", None):
                doc = LEG.documento(nome, ignota)
                self.assertEqual(doc["testo"], inglese["testo"],
                                 "%s con lingua %r non e' inglese (il mondo non "
                                 "legge italiano)" % (nome, ignota))
                self.assertEqual(doc["lang"], "en",
                                 "%s con lingua %r dichiara %r ma serve inglese"
                                 % (nome, ignota, doc["lang"]))
            # la lingua che FA FEDE resta l'italiano: e' una scelta legale, va dichiarata
            self.assertEqual(LEG.documento(nome, "sw")["lingua_che_fa_fede"], "it")

    # ── pagina gentile del link voucher rotto ───────────────────────────────────
    def test_I3_la_pagina_link_non_valido_esiste_in_tutte_e_8_le_lingue(self):
        resi = {}
        for lg in OTTO:
            pagina = pagina_voucher_non_valido_html(lg)
            self.assertEqual(_attributo_lang(pagina), lg,
                             "link-non-valido/%s dichiara la lingua sbagliata" % lg)
            self.assertIn("info@bookinvip.com", pagina)
            resi[lg] = piatto(pagina)
        uguali = [(a, b) for i, a in enumerate(OTTO) for b in OTTO[i + 1:]
                  if resi[a] == resi[b]]
        self.assertEqual(uguali, [], "pagina link-non-valido identica fra %s" % uguali)

    def test_I4_la_pagina_link_non_valido_straniera_non_e_italiana(self):
        perdite = []
        for lg in OTTO:
            if lg == "it":
                continue
            perdite += ["%s -> %r" % (lg, f[:70])
                        for f in italiano_dentro(pagina_voucher_non_valido_html(lg))]
        self.assertEqual(perdite, [], "italiano nella pagina link-non-valido: %s" % perdite)

    def test_I5_link_non_valido_con_lingua_ignota_e_INGLESE(self):
        inglese = pagina_voucher_non_valido_html("en")
        for ignota in IGNOTE:
            self.assertEqual(pagina_voucher_non_valido_html(ignota), inglese,
                             "link-non-valido con lingua %r non e' inglese" % ignota)

    # ── pagine post-pagamento servite come file statici ─────────────────────────
    def test_grazie_e_annullato_hanno_le_8_lingue_e_ripiegano_su_inglese(self):
        for nome in ("grazie", "annullato"):
            percorso = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "deploy", nome + ".html")
            self.assertTrue(os.path.isfile(percorso), "manca deploy/%s.html" % nome)
            with io.open(percorso, encoding="utf-8") as f:
                sorgente = f.read()
            for lg in OTTO:
                self.assertRegex(sorgente, r"\b%s\s*:\s*\{" % lg,
                                 "deploy/%s.html non ha il blocco '%s'" % (nome, lg))
            # il ripiego finale della funzione lingua() e' l'inglese, non l'italiano
            self.assertRegex(sorgente, r"return\s+T\[n\]\s*\?\s*n\s*:\s*'en'",
                             "deploy/%s.html non ripiega sull'inglese" % nome)


# ═════════════════════════════════════════════════════════════════════════════════
#  4. API: dizionario UI, catalogo, documenti legali — via router VERO
# ═════════════════════════════════════════════════════════════════════════════════
class _Posta:
    """Provider email finto: le email di ciclo partono in thread, qui si attendono."""

    def __init__(self):
        self.inviate = []
        self._cv = threading.Condition()

    def invia(self, destinatario, oggetto, html):
        with self._cv:
            self.inviate.append((destinatario, oggetto, html))
            self._cv.notify_all()
        return True

    def attendi(self, quante=1, timeout=8):
        fine = time.time() + timeout
        with self._cv:
            while len(self.inviate) < quante:
                resta = fine - time.time()
                if resta <= 0:
                    return False
                self._cv.wait(resta)
        return True

    def ultima(self):
        return self.inviate[-1]

    def pulisci(self):
        with self._cv:
            self.inviate = []


def _fetch_finto(url, body, headers):
    import secrets
    return {"url": "https://x/" + secrets.token_hex(5), "id": "cs_" + secrets.token_hex(5)}


class _ConRouter(unittest.TestCase):
    """Sistema + router veri, un alloggio pubblicato e disponibile."""

    @classmethod
    def setUpClass(cls):
        cls._fetch_originale = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fetch_finto)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._fetch_originale

    def setUp(self):
        self.dir = d = tempfile.mkdtemp()
        self.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"L" * 32,
            db_catalogo=d + "/c.db", db_inventario=d + "/i.db",
            db_pendenti=d + "/p.db", db_messaggi=d + "/m.db",
            db_garanzia=d + "/g.db", db_recensioni=d + "/rec.db",
            db_payout=d + "/pay.db",
            commissione_bps=1000, psp_bps=300,
            stripe_secret_key="sk", stripe_webhook_secret="whsec_x",
            stripe_success_url="https://x/ok", stripe_cancel_url="https://x/no"))
        self.r = crea_router(self.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        oggi = datetime.date.today()
        s, c = self.g("POST", "/api/host/pubblica",
                      {"host_id": "h", "slug": "casa", "titolo": "Casa Test",
                       "citta": "Roma", "prezzo_notte_cents": 20000, "capacita": 4,
                       "servizi": ["wifi", "parcheggio"]}, {"X-Host-Key": "hk"})
        self.assertEqual(s, 201, c)
        s, c = self.g("POST", "/api/host/disponibilita_range",
                      {"alloggio_id": "casa", "da": oggi.isoformat(),
                       "a": (oggi + datetime.timedelta(days=40)).isoformat(),
                       "unita_totali": 30, "prezzo_netto_cents": 20000},
                      {"X-Host-Key": "hk"})
        self.assertEqual(s, 200, c)
        self.ci = (oggi + datetime.timedelta(days=3)).isoformat()
        self.co = (oggi + datetime.timedelta(days=5)).isoformat()
        self.posta = _Posta()
        self.sis.email_provider = self.posta

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def g(self, metodo, path, corpo=None, headers=None, query=None):
        return self.r.gestisci(metodo, path, query or {},
                               json.dumps(corpo) if corpo is not None else None,
                               headers or {})

    def prenota(self, lingua, email="ospite@x.com"):
        s, q = self.g("POST", "/api/concierge/quote",
                      {"alloggio_id": "casa", "check_in": self.ci,
                       "check_out": self.co, "party": 2})
        self.assertEqual(s, 200, q)
        s, b = self.g("POST", "/api/concierge/book",
                      {"quote_token": q["quote_token"], "email": email, "lang": lingua})
        self.assertEqual(s, 201, b)
        return b

    def webhook(self, riferimento):
        carico = json.dumps({"type": "checkout.session.completed",
                             "data": {"object": {"metadata":
                                                 {"riferimento": riferimento}}}})
        return self.r.gestisci("POST", "/api/payments/webhook", {}, carico,
                               {"Stripe-Signature": firma_di_test(carico, "whsec_x",
                                                                  int(time.time()))})


class TestApiConTesto(_ConRouter):

    def test_I3_dizionario_i18n_esce_nella_lingua_chiesta(self):
        for lg in OTTO:
            s, c = self.g("GET", "/api/i18n", query={"lang": lg})
            self.assertEqual(s, 200, c)
            self.assertEqual(c["lingua"], lg)
            self.assertEqual(c["ui"]["notte"], SPIA_UI_NOTTE[lg],
                             "i18n/%s: etichetta 'notte' sbagliata" % lg)
            self.assertEqual(c["servizi"]["parcheggio"], SPIA_SERVIZIO_PARCHEGGIO[lg],
                             "i18n/%s: servizio 'parcheggio' sbagliato" % lg)

    def test_I2_il_dizionario_e_diverso_in_tutte_le_28_coppie(self):
        resi = {}
        for lg in OTTO:
            _s, c = self.g("GET", "/api/i18n", query={"lang": lg})
            resi[lg] = json.dumps(c["ui"], sort_keys=True, ensure_ascii=False)
        uguali = [(a, b) for i, a in enumerate(OTTO) for b in OTTO[i + 1:]
                  if resi[a] == resi[b]]
        self.assertEqual(uguali, [], "dizionario UI identico fra %s" % uguali)

    def test_I5_i18n_con_lingua_ignota_e_INGLESE(self):
        _s, inglese = self.g("GET", "/api/i18n", query={"lang": "en"})
        for ignota in ("sw", "xx", "klingon", "", "IT", "it-CH"):
            _s, c = self.g("GET", "/api/i18n", query={"lang": ignota})
            self.assertEqual(c["lingua"], "en",
                             "i18n con lang=%r dichiara %r" % (ignota, c["lingua"]))
            self.assertEqual(c, inglese, "i18n con lang=%r non e' inglese" % ignota)
        # senza il parametro: inglese, non italiano (lingua franca del prodotto)
        _s, c = self.g("GET", "/api/i18n")
        self.assertEqual(c["lingua"], "en")

    def test_I3_il_catalogo_traduce_i_servizi_nella_lingua_chiesta(self):
        for lg in OTTO:
            s, c = self.g("GET", "/api/catalogo", query={"citta": "Roma", "lang": lg})
            self.assertEqual(s, 200, c)
            self.assertEqual(c["lingua"], lg)
            self.assertEqual(len(c["risultati"]), 1, c)
            etichette = c["risultati"][0]["servizi_label"]
            self.assertIn(SPIA_SERVIZIO_PARCHEGGIO[lg], etichette,
                          "catalogo/%s: servizi %r" % (lg, etichette))

    def test_I5_catalogo_con_lingua_ignota_da_etichette_INGLESI(self):
        for ignota in ("sw", "klingon", "", "IT"):
            s, c = self.g("GET", "/api/catalogo",
                          query={"citta": "Roma", "lang": ignota})
            self.assertEqual(s, 200, c)
            self.assertEqual(c["lingua"], "en",
                             "catalogo con lang=%r dichiara %r" % (ignota, c["lingua"]))
            self.assertIn("Parking", c["risultati"][0]["servizi_label"])
            self.assertNotIn("Parcheggio", c["risultati"][0]["servizi_label"])

    def test_I3_documento_legale_via_API_nella_lingua_chiesta(self):
        for lg in OTTO:
            for doc in ("termini", "privacy"):
                s, c = self.g("GET", "/api/legale/documento",
                              query={"doc": doc, "lang": lg})
                self.assertEqual(s, 200, c)
                self.assertEqual(c["lang"], lg)
                self.assertTrue(c["tradotto"])
                self.assertEqual(c["lingua_che_fa_fede"], "it")
                self.assertEqual(c["doc_sha256"], sha256_indipendente(c["testo"]),
                                 "%s/%s: impronta non del testo servito" % (doc, lg))
            self.assertIn(SPIA_LEGALE[lg],
                          self.g("GET", "/api/legale/documento",
                                 query={"doc": "termini", "lang": lg})[1]["testo"])

    def test_I5_documento_legale_via_API_con_lingua_ignota_e_INGLESE(self):
        _s, inglese = self.g("GET", "/api/legale/documento",
                             query={"doc": "termini", "lang": "en"})
        for ignota in ("sw", "klingon", "", "IT"):
            _s, c = self.g("GET", "/api/legale/documento",
                           query={"doc": "termini", "lang": ignota})
            self.assertEqual(c["lang"], "en",
                             "termini con lang=%r dichiarano %r" % (ignota, c["lang"]))
            self.assertEqual(c["testo"], inglese["testo"])

    def test_il_contratto_host_dichiara_SEMPRE_la_lingua_che_serve_davvero(self):
        """Il contratto esiste solo in it/en: qualunque cosa serva, deve DIRLO — mai
        dichiarare 'de' e stampare un altro idioma. E chi chiede una lingua che non
        abbiamo tradotto riceve l'INGLESE: un host giapponese leggeva in ITALIANO il
        documento che sta per firmare."""
        import fase163_accettazioni as ACC
        for lg in OTTO + ("sw", "klingon"):
            _s, c = self.g("GET", "/api/legale/contratto-host", query={"lang": lg})
            self.assertIn(c["lang"], ACC.LINGUE_CONTRATTO,
                          "contratto: lang=%r fuori dalle lingue esistenti" % c["lang"])
            self.assertEqual(c["testo"], ACC.CONTRATTO_HOST[c["lang"]],
                             "contratto: dichiara %r ma il testo e' un altro" % c["lang"])
            self.assertEqual(sorted(c["lingue"]), sorted(ACC.LINGUE_CONTRATTO))
            self.assertEqual(c["lingua_che_fa_fede"], "it")
            # l'italiano SOLO a chi l'ha chiesto: per tutti gli altri, inglese
            self.assertEqual(c["lang"], "it" if lg == "it" else "en",
                             "contratto: lang=%r serve %r" % (lg, c["lang"]))
            # l'impronta VINCOLANTE non cambia con la lingua mostrata
            self.assertEqual(c["doc_sha256"], ACC.doc_sha256())

    def test_la_lista_di_attesa_risponde_nella_lingua_chiesta(self):
        attesi = {"it": "Ti avvisiamo", "en": "We'll notify you", "de": "Wir benachrichtigen",
                  "ja": "お知らせします", "zh": "我们会立即通知您"}
        for lg, spia in attesi.items():
            s, c = self.g("POST", "/api/domanda",
                          {"email": "w-%s@x.com" % lg, "citta": "Firenze", "lang": lg})
            self.assertIn(s, (200, 201), c)
            self.assertIn(spia, c["messaggio"],
                          "lista d'attesa/%s: %r" % (lg, c["messaggio"]))


# ═════════════════════════════════════════════════════════════════════════════════
#  5. IL VIAGGIO DELLA LINGUA: book -> gettone firmato -> tutte le email successive
# ═════════════════════════════════════════════════════════════════════════════════
class TestViaggioDellaLingua(_ConRouter):

    def test_I6_la_lingua_del_book_finisce_nel_gettone_FIRMATO(self):
        for lg in OTTO:
            b = self.prenota(lg, email="g-%s@x.com" % lg)
            firmato = self.sis.firma.decodifica(b["voucher_token"])
            self.assertEqual(firmato["lang"], lg,
                             "book(lang=%s): il gettone porta %r" % (lg, firmato.get("lang")))

    def test_I6_lingua_ignota_al_book_diventa_INGLESE_nel_gettone(self):
        for ignota in ("sw", "klingon", "", "IT", "it-CH"):
            b = self.prenota(ignota, email="x@x.com")
            firmato = self.sis.firma.decodifica(b["voucher_token"])
            self.assertEqual(firmato["lang"], "en",
                             "book(lang=%r): il gettone porta %r (mai italiano per "
                             "difetto)" % (ignota, firmato.get("lang")))

    def test_I6_email_di_conferma_nella_lingua_del_book(self):
        for lg in OTTO:
            self.posta.pulisci()
            self.prenota(lg, email="conf-%s@x.com" % lg)
            self.assertTrue(self.posta.attendi(1), "email di conferma mai partita (%s)" % lg)
            destinatario, oggetto, corpo = self.posta.ultima()
            self.assertEqual(destinatario, "conf-%s@x.com" % lg)
            self.assertEqual(oggetto, EM.oggetto("v_ogg_pay", lg),
                             "conferma/%s: oggetto %r" % (lg, oggetto))
            self.assertIn(SPIA_EMAIL_VOUCHER[lg], piatto(corpo),
                          "conferma/%s: il corpo non e' in quella lingua" % lg)
            if lg != "it":
                self.assertEqual(italiano_dentro(corpo), [],
                                 "conferma/%s: italiano nel corpo" % lg)

    def test_I6_la_lingua_sopravvive_a_pagamento_e_cancellazione(self):
        """Il difetto storico: giusta nella conferma, persa in quelle che arrivano dopo."""
        for lg in ("ja", "de", "pt"):
            self.posta.pulisci()
            b = self.prenota(lg, email="ciclo-%s@x.com" % lg)
            self.assertTrue(self.posta.attendi(1))
            self.posta.pulisci()
            s, _c = self.webhook(b["riferimento"])
            self.assertEqual(s, 200)
            self.assertTrue(self.posta.attendi(1), "email di pagamento mai partita (%s)" % lg)
            _d, oggetto, corpo = self.posta.ultima()
            self.assertEqual(oggetto, EM.oggetto("pc_ogg", lg))
            self.assertIn(SPIA_EMAIL_PAGATO[lg], piatto(corpo),
                          "pagamento/%s: corpo nella lingua sbagliata" % lg)
            self.assertEqual(italiano_dentro(corpo), [],
                             "pagamento/%s: italiano nel corpo" % lg)
            self.posta.pulisci()
            s, c = self.g("POST", "/api/concierge/cancella",
                          {"voucher_token": b["voucher_token"]})
            self.assertEqual(s, 200, c)
            self.assertEqual(c["stato"], "cancellata")
            self.assertTrue(self.posta.attendi(1),
                            "email di cancellazione mai partita (%s)" % lg)
            _d, oggetto, corpo = self.posta.ultima()
            self.assertEqual(oggetto, EM.oggetto("c_ogg", lg))
            self.assertIn(SPIA_EMAIL_CANC[lg], piatto(corpo),
                          "cancellazione/%s: corpo nella lingua sbagliata" % lg)
            self.assertEqual(italiano_dentro(corpo), [],
                             "cancellazione/%s: italiano nel corpo" % lg)

    def test_I6_lingua_ignota_al_book_da_email_INGLESI_mai_italiane(self):
        self.posta.pulisci()
        b = self.prenota("klingon", email="sw@x.com")
        self.assertTrue(self.posta.attendi(1))
        _d, oggetto, corpo = self.posta.ultima()
        self.assertEqual(oggetto, EM.oggetto("v_ogg_pay", "en"))
        self.assertIn(SPIA_EMAIL_VOUCHER["en"], piatto(corpo))
        self.assertEqual(italiano_dentro(corpo), [], "email italiana per lingua ignota")
        self.posta.pulisci()
        self.webhook(b["riferimento"])
        self.assertTrue(self.posta.attendi(1))
        _d, oggetto, corpo = self.posta.ultima()
        self.assertEqual(oggetto, EM.oggetto("pc_ogg", "en"))
        self.assertEqual(italiano_dentro(corpo), [])

    def test_il_link_del_voucher_nell_email_porta_con_se_la_lingua(self):
        for lg in ("ja", "de"):
            self.posta.pulisci()
            self.prenota(lg, email="link-%s@x.com" % lg)
            self.assertTrue(self.posta.attendi(1))
            _d, _o, corpo = self.posta.ultima()
            self.assertIn("?lang=" + lg, corpo,
                          "il link del voucher non porta la lingua (%s)" % lg)


# ═════════════════════════════════════════════════════════════════════════════════
#  6. VOUCHER e RECENSIONE: le pagine che l'ospite straniero apre davvero
# ═════════════════════════════════════════════════════════════════════════════════
class TestPagineDelVoucher(_ConRouter):

    def _voucher_pagato(self, lingua_book="en"):
        b = self.prenota(lingua_book, email="v@x.com")
        s, _c = self.webhook(b["riferimento"])
        self.assertEqual(s, 200)
        stato = self.sis.pagamenti_pendenti.info(b["riferimento"])
        self.assertEqual(stato["stato"], "pagato")
        return b["voucher_token"]

    def test_I3_il_voucher_pagato_esce_in_tutte_e_8_le_lingue(self):
        token = self._voucher_pagato()
        resi = {}
        for lg in OTTO:
            pagina = pagina_voucher_html(self.sis, token, lg)
            self.assertIsNotNone(pagina, "voucher/%s non renderizzato" % lg)
            self.assertEqual(_attributo_lang(pagina), lg)
            self.assertIn(SPIA_VOUCHER_PAGINA[lg], piatto(pagina),
                          "voucher/%s non contiene %r" % (lg, SPIA_VOUCHER_PAGINA[lg]))
            resi[lg] = piatto(pagina)
        uguali = [(a, b) for i, a in enumerate(OTTO) for b in OTTO[i + 1:]
                  if resi[a] == resi[b]]
        self.assertEqual(uguali, [], "voucher identico fra lingue diverse: %s" % uguali)

    def test_I4_il_voucher_straniero_non_contiene_italiano(self):
        """Il documento che l'ospite mostra al check-in: se e' in tedesco, e' TUTTO
        in tedesco — bottoni, avvisi e istruzioni compresi."""
        token = self._voucher_pagato()
        perdite = []
        for lg in OTTO:
            if lg == "it":
                continue
            pagina = pagina_voucher_html(self.sis, token, lg)
            perdite += ["%s -> %r" % (lg, f[:80]) for f in italiano_dentro(pagina)]
        self.assertEqual(perdite, [], "italiano incollato nel voucher straniero:\n  - "
                         + "\n  - ".join(perdite[:20]))

    def test_I4_anche_il_voucher_NON_pagato_parla_la_lingua_dell_ospite(self):
        b = self.prenota("de", email="np@x.com")
        pagina = pagina_voucher_html(self.sis, b["voucher_token"], "de")
        self.assertIsNotNone(pagina)
        self.assertEqual(italiano_dentro(pagina), [],
                         "il voucher da pagare parla italiano a un tedesco")

    def test_I5_voucher_senza_lingua_usa_quella_FIRMATA_nel_gettone(self):
        """Nessun default cieco: la lingua e' gia' dentro il gettone, si usa quella."""
        token = self._voucher_pagato(lingua_book="ja")
        senza = pagina_voucher_html(self.sis, token)
        self.assertEqual(_attributo_lang(senza), "ja")
        self.assertEqual(senza, pagina_voucher_html(self.sis, token, "ja"))
        # e una lingua ignota nell'URL non riporta l'italiano
        ignoto = pagina_voucher_html(self.sis, token, "klingon")
        self.assertEqual(_attributo_lang(ignoto), "ja")

    def test_I5_voucher_di_lingua_ignota_ripiega_su_INGLESE(self):
        token = self._voucher_pagato(lingua_book="klingon")   # gettone -> 'en'
        pagina = pagina_voucher_html(self.sis, token, "xx")
        self.assertEqual(_attributo_lang(pagina), "en")
        self.assertEqual(italiano_dentro(pagina), [])

    def test_I3_la_RICEVUTA_di_pagamento_esce_in_tutte_e_8_le_lingue(self):
        """La prova di pagamento di chi ha speso soldi veri: era in italiano per tutti,
        e la funzione non aveva nemmeno un parametro lingua."""
        token = self._voucher_pagato(lingua_book="ja")
        resi = {}
        for lg in OTTO:
            pagina = pagina_ricevuta_html(self.sis, token, lg)
            self.assertIsNotNone(pagina, "ricevuta/%s non renderizzata" % lg)
            self.assertEqual(_attributo_lang(pagina), lg)
            self.assertIn(SPIA_RICEVUTA[lg], piatto(pagina),
                          "ricevuta/%s non contiene %r" % (lg, SPIA_RICEVUTA[lg]))
            # l'importo pagato resta lo stesso in ogni lingua (la lingua non tocca i soldi)
            self.assertIn("400.00 EUR", pagina, "ricevuta/%s: importo alterato" % lg)
            resi[lg] = piatto(pagina)
        uguali = [(a, b) for i, a in enumerate(OTTO) for b in OTTO[i + 1:]
                  if resi[a] == resi[b]]
        self.assertEqual(uguali, [], "ricevuta identica fra lingue diverse: %s" % uguali)
        # senza lingua nell'URL: quella FIRMATA nel gettone (giapponese), non italiano
        self.assertEqual(_attributo_lang(pagina_ricevuta_html(self.sis, token)), "ja")

    def test_I4_la_ricevuta_straniera_non_contiene_italiano(self):
        token = self._voucher_pagato()
        perdite = []
        for lg in OTTO:
            if lg == "it":
                continue
            perdite += ["%s -> %r" % (lg, f[:80])
                        for f in italiano_dentro(pagina_ricevuta_html(self.sis, token, lg))]
        self.assertEqual(perdite, [], "italiano nella ricevuta straniera:\n  - "
                         + "\n  - ".join(perdite[:20]))

    def test_I3_la_pagina_recensione_esce_in_tutte_e_8_le_lingue(self):
        token = self._token_recensibile()
        resi = {}
        for lg in OTTO:
            pagina = pagina_recensione_html(self.sis, token, lg)
            self.assertIsNotNone(pagina, "recensione/%s non renderizzata" % lg)
            self.assertEqual(_attributo_lang(pagina), lg)
            resi[lg] = piatto(pagina)
        uguali = [(a, b) for i, a in enumerate(OTTO) for b in OTTO[i + 1:]
                  if resi[a] == resi[b]]
        self.assertEqual(uguali, [], "pagina recensione identica fra %s" % uguali)

    def test_I4_la_pagina_recensione_straniera_non_contiene_italiano(self):
        token = self._token_recensibile()
        perdite = []
        for lg in OTTO:
            if lg == "it":
                continue
            perdite += ["%s -> %r" % (lg, f[:80])
                        for f in italiano_dentro(pagina_recensione_html(self.sis, token, lg))]
        self.assertEqual(perdite, [], "italiano nella pagina recensione:\n  - "
                         + "\n  - ".join(perdite[:20]))

    def test_I4_la_recensione_ancora_non_apribile_parla_la_lingua_dell_ospite(self):
        """Soggiorno non concluso: anche il messaggio «potrai recensire dopo» e' tradotto."""
        futuro = self._token_recensibile(giorni_da_oggi=+5)
        for lg in ("de", "ja", "zh", "fr"):
            pagina = pagina_recensione_html(self.sis, futuro, lg)
            self.assertIsNotNone(pagina)
            self.assertEqual(italiano_dentro(pagina), [],
                             "recensione-non-ancora/%s in italiano" % lg)

    def _token_recensibile(self, giorni_da_oggi=-1):
        """Un gettone voucher valido con check-out gia' passato (o futuro)."""
        b = self.prenota("en", email="rec@x.com")
        dati = self.sis.firma.decodifica(b["voucher_token"])
        co = datetime.date.today() + datetime.timedelta(days=giorni_da_oggi)
        dati["check_out"] = co.isoformat()
        dati["check_in"] = (co - datetime.timedelta(days=2)).isoformat()
        return self.sis.firma.codifica(dati)


# ═════════════════════════════════════════════════════════════════════════════════
#  7. CABLAGGIO: le rotte HTTP VERE passano davvero la lingua alle pagine
#     (il pezzo puo' essere perfetto e non essere collegato — modo di rompersi n.2)
# ═════════════════════════════════════════════════════════════════════════════════
def _porta_libera():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class TestRotteHTTPVere(unittest.TestCase):
    """Server VERO in un thread: `?lang=` arriva dall'handler, non dal router."""

    @classmethod
    def setUpClass(cls):
        cls._fetch_originale = _stripe.ProviderStripe._fetch_reale
        _stripe.ProviderStripe._fetch_reale = staticmethod(_fetch_finto)
        # Il server VERO avvia i suoi giri di fondo (marca temporale RFC 3161 verso una
        # TSA esterna, guardiano che interroga Stripe). Un collaudo non deve uscire in
        # rete: si spengono qui e si ripristinano dopo.
        cls._marca_prima = os.environ.get("MARCA_TEMPORALE")
        os.environ["MARCA_TEMPORALE"] = "0"
        import fase182_riconciliazione as _ric
        cls._ric_mod = _ric
        cls._ric_prima = _ric._fetch_reale
        _ric._fetch_reale = lambda *a, **k: {"data": [], "has_more": False}
        cls.dir = d = tempfile.mkdtemp()
        cls.sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"R" * 32,
            db_catalogo=d + "/c.db", db_inventario=d + "/i.db", db_pendenti=d + "/p.db",
            db_messaggi=d + "/m.db", db_garanzia=d + "/g.db", db_recensioni=d + "/rec.db",
            commissione_bps=1000, psp_bps=300, stripe_secret_key="sk",
            stripe_webhook_secret="whsec_x", stripe_success_url="https://x/ok",
            stripe_cancel_url="https://x/no"))
        router = crea_router(cls.sis, host_key="hk", admin_key="ak",
                             base_url="https://bookinvip.com")
        oggi = datetime.date.today()

        def g(metodo, path, corpo=None, headers=None):
            return router.gestisci(metodo, path, {},
                                   json.dumps(corpo) if corpo is not None else None,
                                   headers or {})

        g("POST", "/api/host/pubblica",
          {"host_id": "h", "slug": "casa", "titolo": "Casa Test", "citta": "Roma",
           "prezzo_notte_cents": 20000, "capacita": 4}, {"X-Host-Key": "hk"})
        g("POST", "/api/host/disponibilita_range",
          {"alloggio_id": "casa", "da": oggi.isoformat(),
           "a": (oggi + datetime.timedelta(days=20)).isoformat(),
           "unita_totali": 5, "prezzo_netto_cents": 20000}, {"X-Host-Key": "hk"})
        _s, q = g("POST", "/api/concierge/quote",
                  {"alloggio_id": "casa",
                   "check_in": (oggi + datetime.timedelta(days=3)).isoformat(),
                   "check_out": (oggi + datetime.timedelta(days=5)).isoformat(),
                   "party": 2})
        _s, b = g("POST", "/api/concierge/book",
                  {"quote_token": q["quote_token"], "email": "rotte@x.com", "lang": "ja"})
        cls.vt = b["voucher_token"]
        cls.sis.pagamenti_pendenti.conferma(b["riferimento"])
        cls.porta = _porta_libera()
        threading.Thread(
            target=SRV.servi,
            kwargs=dict(sistema=cls.sis, host="127.0.0.1", porta=cls.porta,
                        cartella_statica="deploy", host_key="hk", admin_key="ak"),
            daemon=True).start()
        for _ in range(200):
            try:
                if cls._get("/robots.txt")[0] == 200:
                    break
            except Exception:
                pass
            time.sleep(0.03)

    @classmethod
    def tearDownClass(cls):
        _stripe.ProviderStripe._fetch_reale = cls._fetch_originale
        cls._ric_mod._fetch_reale = cls._ric_prima
        if cls._marca_prima is None:
            os.environ.pop("MARCA_TEMPORALE", None)
        else:
            os.environ["MARCA_TEMPORALE"] = cls._marca_prima
        shutil.rmtree(cls.dir, ignore_errors=True)

    @classmethod
    def _get(cls, path):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", cls.porta, timeout=8)
        conn.request("GET", path)
        risposta = conn.getresponse()
        corpo = risposta.read().decode("utf-8", "replace")
        conn.close()
        return risposta.status, corpo

    def test_rotta_voucher_passa_la_lingua_alla_pagina(self):
        from urllib.parse import quote
        tk = quote(self.vt, safe="")
        for lg in OTTO:
            stato, corpo = self._get("/voucher/%s?lang=%s" % (tk, lg))
            self.assertEqual(stato, 200, corpo[:200])
            self.assertEqual(_attributo_lang(corpo), lg, "rotta /voucher/?lang=%s" % lg)
            self.assertIn(SPIA_VOUCHER_PAGINA[lg], piatto(corpo))
        # SENZA ?lang=: la lingua FIRMATA nel gettone (giapponese), non l'italiano
        stato, corpo = self._get("/voucher/" + tk)
        self.assertEqual(stato, 200)
        self.assertEqual(_attributo_lang(corpo), "ja",
                         "la rotta /voucher/ impone un default cieco invece di leggere "
                         "la lingua firmata nel gettone")
        # lingua ignota nell'URL: si resta sul giapponese del gettone, mai italiano
        _s, corpo = self._get("/voucher/%s?lang=klingon" % tk)
        self.assertEqual(_attributo_lang(corpo), "ja")

    def test_rotta_ricevuta_passa_la_lingua_alla_pagina(self):
        from urllib.parse import quote
        tk = quote(self.vt, safe="")
        for lg in ("de", "zh", "it"):
            stato, corpo = self._get("/ricevuta/%s?lang=%s" % (tk, lg))
            self.assertEqual(stato, 200, corpo[:200])
            self.assertEqual(_attributo_lang(corpo), lg)
            self.assertIn(SPIA_RICEVUTA[lg], piatto(corpo))
        self.assertEqual(_attributo_lang(self._get("/ricevuta/" + tk)[1]), "ja")

    def test_rotta_link_rotto_risponde_404_nella_lingua_chiesta(self):
        for lg, spia in (("de", "ungültig"), ("ja", "無効"), ("en", "isn't valid")):
            stato, corpo = self._get("/voucher/token-inventato?lang=" + lg)
            self.assertEqual(stato, 404)
            self.assertEqual(_attributo_lang(corpo), lg)
            self.assertIn(spia, corpo, "404 voucher/%s non tradotto" % lg)
        # senza lingua: inglese, non italiano
        _s, corpo = self._get("/voucher/token-inventato")
        self.assertEqual(_attributo_lang(corpo), "en")

    def test_rotta_landing_citta_e_blog_passano_la_lingua(self):
        for lg in OTTO:
            stato, corpo = self._get("/affitta/roma?lang=" + lg)
            self.assertEqual(stato, 200, corpo[:200])
            self.assertEqual(_attributo_lang(corpo), lg)
            self.assertIn(SPIA_LANDING[lg], piatto(corpo))
            stato, corpo = self._get("/blog?lang=" + lg)
            self.assertEqual(stato, 200, corpo[:200])
            self.assertEqual(_attributo_lang(corpo), lg)
            self.assertIn(SPIA_BLOG[lg], piatto(corpo))

    def test_rotta_i18n_e_catalogo_via_HTTP_vero(self):
        for lg in OTTO:
            stato, corpo = self._get("/api/i18n?lang=" + lg)
            self.assertEqual(stato, 200)
            dati = json.loads(corpo)
            self.assertEqual(dati["lingua"], lg)
            self.assertEqual(dati["ui"]["notte"], SPIA_UI_NOTTE[lg])
        stato, corpo = self._get("/api/i18n?lang=klingon")
        self.assertEqual(json.loads(corpo)["lingua"], "en")


if __name__ == "__main__":
    unittest.main(verbosity=2)
