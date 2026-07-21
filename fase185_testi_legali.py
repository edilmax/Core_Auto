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
"es": """TERMINOS Y CONDICIONES DEL SERVICIO — BOOKINVIP
Version {VER} · Ultima actualizacion: {VER}
Titular: {SOC}, NIF/IVA {PIVA}, {IND} — {EMAIL}

1. OBJETO Y FUNCION DE BOOKINVIP
BookinVIP es una plataforma tecnologica de intermediacion que pone en contacto a
Anfitriones (propietarios o gestores de alojamientos) y Huespedes para la reserva de
estancias. BookinVIP NO posee, no gestiona y no controla los alojamientos. El contrato de
alojamiento se celebra DIRECTAMENTE entre Anfitrion y Huesped; BookinVIP aporta las
herramientas (escaparate, reserva, pago, bono, registro digital de entrada).

2. ACEPTACION
Al usar la Plataforma aceptas estos Terminos y la Politica de Privacidad. Si no los
aceptas, no utilices el servicio.

3. OBLIGACIONES DEL ANFITRION
El Anfitrion garantiza que: tiene titulo para ofrecer el alojamiento y cumple la
normativa local (licencias, registro de huespedes, impuesto turistico, seguridad); la
informacion y las fotos del anuncio son veraces y estan actualizadas; la disponibilidad
mostrada es real; las declaraciones vinculantes (p. ej. "sin alergenos", "admite
mascotas") son ciertas. Si resultan falsas, el Huesped tiene derecho al reembolso y el
Anfitrion a una penalizacion segun el mecanismo de la Plataforma.

4. RESERVA Y PAGO (HUESPED)
El precio mostrado lo calcula y lo firma el sistema: no puede modificarse desde el
navegador. El Huesped paga el precio limpio: no soporta ninguna comision de plataforma.
El pago se realiza mediante un proveedor autorizado (Stripe); BookinVIP no conserva los
datos de la tarjeta.

5. COSTES A CARGO DEL ANFITRION
Comision de plataforma: {PROMO}% durante los primeros {GG} dias desde el registro,
despues {FASE1}% hasta un ano y {REGIME}% en regimen ordinario, sobre las reservas
procedentes del marketplace; {DIRETTO}% sobre las reservas procedentes del enlace directo
del Anfitrion.
TARIFA TECNICA: ademas de la comision, queda a cargo exclusivo del Anfitrion una tarifa
tecnica fija igual al {TECNICA}% del importe de la transaccion, SIEMPRE DEBIDA en
cualquier periodo — tambien cuando la comision es del {PROMO}% — para cubrir los costes
del proveedor de pago. La Plataforma no obtiene ningun margen sobre este concepto.

6. COBROS Y TRANSFERENCIAS
La parte del Anfitrion permanece en garantia hasta la confirmacion del Huesped o hasta la
liberacion automatica prevista por la Plataforma; despues se transfiere a la cuenta
vinculada. Las transferencias pueden retenerse cuando la ley lo exige (obligaciones de
identificacion fiscal), hasta su regularizacion.

7. CANCELACIONES Y PENALIZACIONES
Las condiciones de cancelacion se indican en cada anuncio. Si el Anfitrion cancela una
reserva ya pagada, o el alojamiento resulta no disponible, se devenga una penalizacion
igual al {PENALE}% del importe, compensada con los cobros futuros del Anfitrion o
registrada como deuda.

8. VALORACIONES
Las valoraciones solo se admiten tras una estancia real y concluida, una sola vez por
reserva. Los contenidos ofensivos, falsos o comerciales pueden ser retirados.

9. LIMITACION DE RESPONSABILIDAD
BookinVIP responde del correcto funcionamiento de la Plataforma. No responde de la
calidad del alojamiento, del comportamiento de Anfitriones y Huespedes, ni de hechos no
imputables a la Plataforma, dentro de los limites permitidos por la ley aplicable.

10. LEY APLICABLE
Se aplica la ley italiana. Quedan a salvo los derechos irrenunciables reconocidos al
consumidor por la ley de su pais de residencia.

11. MODIFICACIONES
Las modificaciones se publican en esta pagina con una nueva version. El uso continuado de
la Plataforma tras la publicacion equivale a su aceptacion.

12. IDIOMA
Estos Terminos se facilitan en varios idiomas por comodidad. En caso de divergencia
prevalece la version ITALIANA.
""",
"fr": """CONDITIONS GENERALES DE SERVICE — BOOKINVIP
Version {VER} · Derniere mise a jour : {VER}
Exploitant : {SOC}, N° TVA {PIVA}, {IND} — {EMAIL}

1. OBJET ET ROLE DE BOOKINVIP
BookinVIP est une plateforme technologique d'intermediation qui met en relation des Hotes
(proprietaires ou gestionnaires de logements) et des Voyageurs pour la reservation de
sejours. BookinVIP NE possede pas, ne gere pas et ne controle pas les logements. Le
contrat de sejour est conclu DIRECTEMENT entre l'Hote et le Voyageur ; BookinVIP fournit
les outils (vitrine, reservation, paiement, bon, enregistrement numerique).

2. ACCEPTATION
En utilisant la Plateforme, vous acceptez les presentes Conditions et la Politique de
confidentialite. Si vous ne les acceptez pas, n'utilisez pas le service.

3. OBLIGATIONS DE L'HOTE
L'Hote garantit que : il a qualite pour proposer le logement et respecte la
reglementation locale (licences, declaration des voyageurs, taxe de sejour, securite) ;
les informations et les photos de l'annonce sont exactes et a jour ; la disponibilite
affichee est reelle ; les declarations contraignantes (p. ex. "sans allergenes", "animaux
acceptes") sont veridiques. Si elles se revelent fausses, le Voyageur a droit au
remboursement et l'Hote est redevable d'une penalite selon le mecanisme de la Plateforme.

4. RESERVATION ET PAIEMENT (VOYAGEUR)
Le prix affiche est calcule et signe par le systeme : il n'est pas modifiable depuis le
navigateur. Le Voyageur paie le prix net : aucune commission de plateforme n'est a sa
charge. Le paiement est effectue via un prestataire agree (Stripe) ; BookinVIP ne
conserve pas les donnees de la carte.

5. COUTS A LA CHARGE DE L'HOTE
Commission de plateforme : {PROMO}% pendant les {GG} premiers jours suivant
l'inscription, puis {FASE1}% jusqu'a un an, puis {REGIME}% en regime courant, sur les
reservations issues de la place de marche ; {DIRETTO}% sur les reservations issues du
lien direct de l'Hote.
FRAIS TECHNIQUES : outre la commission, restent a la charge exclusive de l'Hote des frais
techniques fixes egaux a {TECNICA}% du montant de la transaction, TOUJOURS DUS quelle que
soit la periode — y compris lorsque la commission est de {PROMO}% — afin de couvrir les
couts du prestataire de paiement. La Plateforme ne realise aucune marge sur ce poste.

6. ENCAISSEMENTS ET VIREMENTS
La part de l'Hote reste sous sequestre jusqu'a la confirmation du Voyageur ou jusqu'a la
liberation automatique prevue par la Plateforme ; elle est ensuite virée sur le compte
associe. Les virements peuvent etre retenus lorsque la loi l'impose (obligations
d'identification fiscale), jusqu'a regularisation.

7. ANNULATIONS ET PENALITES
Les conditions d'annulation sont indiquees sur chaque annonce. Si l'Hote annule une
reservation deja payee, ou si le logement se revele indisponible, une penalite egale a
{PENALE}% du montant est due, compensee sur les encaissements futurs de l'Hote ou
enregistree comme dette.

8. AVIS
Les avis ne sont admis qu'apres un sejour reel et acheve, une seule fois par reservation.
Les contenus injurieux, faux ou commerciaux peuvent etre supprimes.

9. LIMITATION DE RESPONSABILITE
BookinVIP repond du bon fonctionnement de la Plateforme. Elle ne repond pas de la qualite
du logement, du comportement des Hotes et des Voyageurs, ni des evenements qui ne lui
sont pas imputables, dans les limites permises par la loi applicable.

10. DROIT APPLICABLE
Le droit italien s'applique. Demeurent reserves les droits imperatifs reconnus au
consommateur par la loi de son pays de residence.

11. MODIFICATIONS
Les modifications sont publiees sur cette page avec un nouveau numero de version.
L'utilisation continue de la Plateforme apres publication vaut acceptation.

12. LANGUE
Les presentes Conditions sont fournies en plusieurs langues par commodite. En cas de
divergence, la version ITALIENNE fait foi.
""",
"de": """ALLGEMEINE GESCHAEFTSBEDINGUNGEN — BOOKINVIP
Version {VER} · Letzte Aktualisierung: {VER}
Betreiber: {SOC}, USt-IdNr. {PIVA}, {IND} — {EMAIL}

1. GEGENSTAND UND ROLLE VON BOOKINVIP
BookinVIP ist eine technologische Vermittlungsplattform, die Gastgeber (Eigentuemer oder
Verwalter von Unterkuenften) und Gaeste fuer die Buchung von Aufenthalten zusammenbringt.
BookinVIP besitzt, verwaltet und kontrolliert die Unterkuenfte NICHT. Der Beherbergungs-
vertrag kommt UNMITTELBAR zwischen Gastgeber und Gast zustande; BookinVIP stellt die
Werkzeuge bereit (Schaufenster, Buchung, Zahlung, Gutschein, digitaler Check-in).

2. ANNAHME
Mit der Nutzung der Plattform akzeptieren Sie diese Bedingungen und die
Datenschutzerklaerung. Wenn Sie sie nicht akzeptieren, nutzen Sie den Dienst nicht.

3. PFLICHTEN DES GASTGEBERS
Der Gastgeber sichert zu, dass: er berechtigt ist, die Unterkunft anzubieten, und die
oertlichen Vorschriften einhaelt (Genehmigungen, Gaestemeldung, Kurtaxe, Sicherheit); die
Angaben und Fotos des Inserats wahrheitsgemaess und aktuell sind; die angezeigte
Verfuegbarkeit tatsaechlich besteht; verbindliche Angaben (z. B. "allergenfrei",
"haustierfreundlich") zutreffen. Erweisen sie sich als unrichtig, hat der Gast Anspruch
auf Erstattung und der Gastgeber schuldet eine Vertragsstrafe nach dem Mechanismus der
Plattform.

4. BUCHUNG UND ZAHLUNG (GAST)
Der angezeigte Preis wird vom System berechnet und signiert: er ist ueber den Browser
nicht veraenderbar. Der Gast zahlt den reinen Preis: ihn trifft keine Plattformprovision.
Die Zahlung erfolgt ueber einen zugelassenen Zahlungsdienstleister (Stripe); BookinVIP
speichert keine Kartendaten.

5. KOSTEN ZULASTEN DES GASTGEBERS
Plattformprovision: {PROMO}% in den ersten {GG} Tagen ab der Registrierung, danach
{FASE1}% bis zu einem Jahr, danach {REGIME}% im Regelbetrieb, auf Buchungen aus dem
Marktplatz; {DIRETTO}% auf Buchungen ueber den Direktlink des Gastgebers.
TECHNISCHES ENTGELT: neben der Provision traegt ausschliesslich der Gastgeber ein festes
technisches Entgelt in Hoehe von {TECNICA}% des Transaktionsbetrags, das in JEDEM
Zeitraum STETS GESCHULDET ist — auch wenn die Provision {PROMO}% betraegt — zur Deckung
der Kosten des Zahlungsdienstleisters. Die Plattform erzielt hierauf keine Marge.

6. EINNAHMEN UND UEBERWEISUNGEN
Der Anteil des Gastgebers verbleibt bis zur Bestaetigung durch den Gast oder bis zur von
der Plattform vorgesehenen automatischen Freigabe in Verwahrung; danach wird er auf das
verknuepfte Konto ueberwiesen. Ueberweisungen koennen einbehalten werden, soweit das
Gesetz dies vorschreibt (steuerliche Identifizierungspflichten), bis zur Regularisierung.

7. STORNIERUNGEN UND VERTRAGSSTRAFEN
Die Stornobedingungen sind bei jedem Inserat angegeben. Storniert der Gastgeber eine
bereits bezahlte Buchung oder ist die Unterkunft nicht verfuegbar, faellt eine
Vertragsstrafe in Hoehe von {PENALE}% des Betrags an, die mit kuenftigen Einnahmen des
Gastgebers verrechnet oder als Verbindlichkeit erfasst wird.

8. BEWERTUNGEN
Bewertungen sind nur nach einem tatsaechlichen und abgeschlossenen Aufenthalt zulaessig,
einmal je Buchung. Beleidigende, unwahre oder werbliche Inhalte koennen entfernt werden.

9. HAFTUNGSBESCHRAENKUNG
BookinVIP haftet fuer das ordnungsgemaesse Funktionieren der Plattform. Sie haftet nicht
fuer die Qualitaet der Unterkunft, fuer das Verhalten von Gastgebern und Gaesten oder
fuer nicht von ihr zu vertretende Ereignisse, soweit das anwendbare Recht dies zulaesst.

10. ANWENDBARES RECHT
Es gilt italienisches Recht. Unberuehrt bleiben die zwingenden Rechte, die dem
Verbraucher nach dem Recht seines Wohnsitzstaates zustehen.

11. AENDERUNGEN
Aenderungen werden auf dieser Seite mit einer neuen Version veroeffentlicht. Die weitere
Nutzung der Plattform nach der Veroeffentlichung gilt als Zustimmung.

12. SPRACHE
Diese Bedingungen werden aus Gruenden der Bequemlichkeit in mehreren Sprachen
bereitgestellt. Bei Abweichungen ist die ITALIENISCHE Fassung massgeblich.
""",
"pt": """TERMOS E CONDICOES DE SERVICO — BOOKINVIP
Versao {VER} · Ultima atualizacao: {VER}
Operador: {SOC}, NIF/IVA {PIVA}, {IND} — {EMAIL}

1. OBJETO E FUNCAO DA BOOKINVIP
A BookinVIP e uma plataforma tecnologica de intermediacao que coloca em contacto
Anfitrioes (proprietarios ou gestores de alojamentos) e Hospedes para a reserva de
estadias. A BookinVIP NAO possui, nao gere e nao controla os alojamentos. O contrato de
alojamento e celebrado DIRETAMENTE entre Anfitriao e Hospede; a BookinVIP fornece as
ferramentas (montra, reserva, pagamento, voucher, check-in digital).

2. ACEITACAO
Ao utilizar a Plataforma aceitas estes Termos e a Politica de Privacidade. Se nao os
aceitares, nao utilizes o servico.

3. OBRIGACOES DO ANFITRIAO
O Anfitriao garante que: tem titulo para oferecer o alojamento e cumpre a legislacao
local (licencas, registo de hospedes, taxa turistica, seguranca); as informacoes e as
fotografias do anuncio sao verdadeiras e atualizadas; a disponibilidade apresentada e
real; as declaracoes vinculativas (p. ex. "sem alergenios", "aceita animais") sao
verdadeiras. Se se revelarem falsas, o Hospede tem direito ao reembolso e o Anfitriao
fica sujeito a uma penalizacao nos termos do mecanismo da Plataforma.

4. RESERVA E PAGAMENTO (HOSPEDE)
O preco apresentado e calculado e assinado pelo sistema: nao pode ser alterado a partir
do navegador. O Hospede paga o preco limpo: nao suporta qualquer comissao de plataforma.
O pagamento e efetuado atraves de prestador autorizado (Stripe); a BookinVIP nao conserva
os dados do cartao.

5. CUSTOS A CARGO DO ANFITRIAO
Comissao de plataforma: {PROMO}% nos primeiros {GG} dias apos o registo, depois {FASE1}%
ate um ano e {REGIME}% em regime normal, sobre as reservas provenientes do marketplace;
{DIRETTO}% sobre as reservas provenientes da ligacao direta do Anfitriao.
TAXA TECNICA: alem da comissao, fica a cargo exclusivo do Anfitriao uma taxa tecnica fixa
igual a {TECNICA}% do montante da transacao, SEMPRE DEVIDA em qualquer periodo — tambem
quando a comissao e de {PROMO}% — para cobrir os custos do prestador de pagamento. A
Plataforma nao obtem qualquer margem sobre esta rubrica.

6. RECEBIMENTOS E TRANSFERENCIAS
A parte do Anfitriao permanece em garantia ate a confirmacao do Hospede ou ate a
libertacao automatica prevista pela Plataforma; e depois transferida para a conta
associada. As transferencias podem ser retidas quando a lei o exija (obrigacoes de
identificacao fiscal), ate a regularizacao.

7. CANCELAMENTOS E PENALIZACOES
As condicoes de cancelamento sao indicadas em cada anuncio. Se o Anfitriao cancelar uma
reserva ja paga, ou se o alojamento nao estiver disponivel, e devida uma penalizacao
igual a {PENALE}% do montante, compensada com os recebimentos futuros do Anfitriao ou
registada como divida.

8. AVALIACOES
As avaliacoes so sao admitidas apos uma estadia real e concluida, uma unica vez por
reserva. Conteudos ofensivos, falsos ou comerciais podem ser removidos.

9. LIMITACAO DE RESPONSABILIDADE
A BookinVIP responde pelo correto funcionamento da Plataforma. Nao responde pela
qualidade do alojamento, pelo comportamento de Anfitrioes e Hospedes, nem por
acontecimentos que nao lhe sejam imputaveis, nos limites permitidos pela lei aplicavel.

10. LEI APLICAVEL
Aplica-se a lei italiana. Ficam ressalvados os direitos irrenunciaveis reconhecidos ao
consumidor pela lei do seu pais de residencia.

11. ALTERACOES
As alteracoes sao publicadas nesta pagina com uma nova versao. A utilizacao continuada da
Plataforma apos a publicacao vale como aceitacao.

12. LINGUA
Estes Termos sao disponibilizados em varias linguas por comodidade. Em caso de
divergencia prevalece a versao ITALIANA.
""",
"ja": """利用規約 — BOOKINVIP
バージョン {VER} ・ 最終更新: {VER}
運営者: {SOC}、付加価値税登録番号 {PIVA}、{IND} — {EMAIL}

1. 目的および BOOKINVIP の役割
BookinVIP は、宿泊施設の所有者または運営者（以下「ホスト」）と宿泊を予約する利用者（以下「ゲスト」）を結びつける技術的仲介プラットフォームです。
BookinVIP は宿泊施設を所有・運営・管理しません。宿泊契約はホストとゲストの間で直接締結され、BookinVIP はその手段（掲載、予約、決済、バウチャー、デジタルチェックイン）を提供します。

2. 同意
本プラットフォームを利用することにより、本規約およびプライバシーポリシーに同意したものとみなされます。同意しない場合は本サービスを利用しないでください。

3. ホストの義務
ホストは次の事項を保証します。宿泊施設を提供する正当な権限を有し、現地の法令（許認可、宿泊者名簿、宿泊税、安全基準）を遵守していること。掲載情報および写真が真実かつ最新であること。表示された空室状況が実際のものであること。拘束力のある表示（例：「アレルゲン不使用」「ペット可」）が真実であること。これらが虚偽であった場合、ゲストは返金を受ける権利を有し、ホストは本プラットフォームの定める違約金を負います。

4. 予約および支払（ゲスト）
表示価格はシステムが算出し署名したものであり、ブラウザから変更することはできません。ゲストは追加のプラットフォーム手数料を一切負担せず、提示価格のみを支払います。決済は認可された決済代行会社（Stripe）を通じて行われ、BookinVIP はカード情報を保存しません。

5. ホストが負担する費用
プラットフォーム手数料：登録から {GG} 日間は {PROMO}%、その後1年までは {FASE1}%、以降は {REGIME}%（マーケットプレイス経由の予約）。ホストの直接リンク経由の予約は {DIRETTO}%。
技術手数料：上記手数料に加え、取引金額の {TECNICA}% に相当する固定の技術手数料をホストが専ら負担します。これは手数料が {PROMO}% の期間を含むすべての期間において常に発生し、決済代行会社の実費を賄うものです。本項目についてプラットフォームは利益を得ません。

6. 入金および送金
ホストの取り分は、ゲストの確認または本プラットフォームが定める自動解除まで保管され、その後連携口座へ送金されます。法令が要求する場合（税務上の本人確認義務等）、送金は規定の履行まで保留されることがあります。

7. キャンセルおよび違約金
キャンセル条件は各掲載に表示されます。ホストが支払済みの予約を取り消した場合、または宿泊施設が利用できない場合、金額の {PENALE}% に相当する違約金が発生し、ホストの将来の入金から相殺されるか、債務として記録されます。

8. レビュー
レビューは、実際に完了した宿泊の後に、予約ごとに1回のみ投稿できます。侮辱的、虚偽または宣伝目的の内容は削除されることがあります。

9. 責任の制限
BookinVIP は本プラットフォームの適正な動作について責任を負います。適用法が許容する範囲内で、宿泊施設の品質、ホストおよびゲストの行為、並びに本プラットフォームの責に帰しない事象については責任を負いません。

10. 準拠法
イタリア法を準拠法とします。消費者が居住国の法令により認められる強行規定上の権利は影響を受けません。

11. 変更
変更は新しいバージョンとして本ページに公表されます。公表後も本プラットフォームの利用を継続した場合、変更に同意したものとみなされます。

12. 言語
本規約は便宜のため複数の言語で提供されます。解釈に相違がある場合はイタリア語版が優先します。
""",
"zh": """服务条款 — BOOKINVIP
版本 {VER} · 最后更新：{VER}
运营者：{SOC}，增值税号 {PIVA}，{IND} — {EMAIL}

1. 目的与 BOOKINVIP 的角色
BookinVIP 是一个技术中介平台，为房东（住宿的所有者或管理者）与房客建立联系以便预订住宿。
BookinVIP 不拥有、不经营也不控制任何住宿。住宿合同直接在房东与房客之间订立；BookinVIP 仅提供工具（展示、预订、支付、凭证、数字入住登记）。

2. 接受
使用本平台即表示您接受本条款及隐私政策。若您不接受，请勿使用本服务。

3. 房东的义务
房东保证：其有权提供该住宿并遵守当地法规（许可、旅客登记、住宿税、安全规定）；房源信息与照片真实且保持更新；所展示的可预订情况真实；具有约束力的声明（如“无致敏原”、“可携宠物”）属实。如经查不实，房客有权获得退款，房东应按平台机制承担违约金。

4. 预订与支付（房客）
所示价格由系统计算并签名，无法通过浏览器修改。房客支付的是“干净价格”：无需承担任何平台佣金。支付通过持牌支付机构（Stripe）完成；BookinVIP 不保存银行卡信息。

5. 房东承担的费用
平台佣金：自注册起前 {GG} 天为 {PROMO}%，其后至一年为 {FASE1}%，之后为 {REGIME}%（适用于来自平台市场的预订）；来自房东专属链接的预订为 {DIRETTO}%。
技术服务费：除佣金外，房东需单独承担相当于交易金额 {TECNICA}% 的固定技术服务费，在任何时期均应支付——包括佣金为 {PROMO}% 的期间——用以支付支付机构的成本。平台在该项上不获取任何利润。

6. 收款与转账
房东应得款项将托管至房客确认或平台规定的自动释放为止，随后转入已绑定账户。当法律要求时（税务身份识别义务），转账可能被暂缓，直至完成合规手续。

7. 取消与违约金
取消条件在每个房源页面列明。若房东取消已付款的预订，或住宿实际不可用，应支付相当于订单金额 {PENALE}% 的违约金，该款项将从房东未来收入中抵扣或记录为欠款。

8. 评价
仅允许在真实且已完成的住宿之后发表评价，每笔预订限一次。侮辱性、虚假或商业推广内容可能被删除。

9. 责任限制
BookinVIP 对平台的正常运行承担责任。在适用法律允许的范围内，平台不对住宿质量、房东与房客的行为，以及不可归责于平台的事件承担责任。

10. 适用法律
适用意大利法律。消费者根据其居住国法律享有的强制性权利不受影响。

11. 修改
修改将以新版本形式发布于本页面。发布后继续使用本平台即视为接受修改。

12. 语言
本条款为方便起见提供多种语言版本。若各版本之间存在差异，以意大利语版本为准。
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
