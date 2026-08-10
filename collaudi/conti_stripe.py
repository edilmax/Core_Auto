"""
CORE_AUTO - I CONTI CONTRO STRIPE: la tariffa tecnica copre davvero il costo della carta?

PERCHE' ESISTE. `fase59_concierge.py:327` calcola il costo del pagamento come
`totale * psp_bps // 10000`: una PERCENTUALE SECCA. Stripe non funziona cosi': prende
una percentuale PIU' UNA QUOTA FISSA per transazione. Su una prenotazione piccola la
quota fissa si mangia tutto, e il commento accanto al codice -- "copre Stripe; ns 0
margine" -- diventa falso. Trovato il 2026-08-09 dal fondatore con un caso vero:
una stanza da 13 EUR nelle Filippine.

⛔ QUESTO STRUMENTO NON DECIDE NIENTE: misura e basta. Le riparazioni si fanno dopo,
una alla volta, col via del fondatore.

LE DUE DOMANDE, che sono diverse:
  (a) la tariffa tecnica copre il costo Stripe?  -> e' la promessa che il codice fa
      a se stesso ("ns 0 margine"). Se no, quella riga di commento dichiara il falso.
  (b) ci rimettiamo davvero?  -> commissione + tariffa tecnica meno il costo Stripe.
      Fuori promozione la commissione assorbe lo scarto. NEI PRIMI 90 GIORNI LA
      COMMISSIONE E' ZERO, quindi (a) e (b) coincidono: e' la finestra pericolosa,
      ed e' esattamente quella in cui stanno per entrare i primi host.

LE NOSTRE PERCENTUALI SI LEGGONO DAL CODICE, non si riscrivono qui (stessa tecnica di
`collaudi/audit_coerenza_tariffe.py`): se domani cambiano, questo conto cambia da solo.

I COSTI STRIPE SONO DICHIARATI, CON LA LORO FONTE (D22: un numero porta la sua misura):
  fonte: https://stripe.com/it/pricing  -- letta il 2026-08-09
  NB: sono le tariffe di LISTINO per un'azienda italiana. Il conto vero non e' stato
  possibile farlo: `GET /v1/balance_transactions` sul conto live ha risposto
  `"data": []` -- ZERO transazioni, nessun pagamento reale e' mai passato.
  Il giorno che ce ne saranno, la verita' va riletta da li'.

CIO' CHE QUESTO STRUMENTO NON GUARDA (dichiarato, D18 punto 3):
  · le tariffe negoziate: se il conto avesse condizioni diverse dal listino, questi
    numeri sono sbagliati e vanno rifatti sulle transazioni vere;
  · i rimborsi (Stripe non restituisce la commissione originale: peggiora tutto,
    ma e' un conto a parte);
  · le controversie/chargeback (15 EUR a botta) e i costi di Connect sui bonifici;
  · IVA sulle commissioni Stripe;
  · il "paga in struttura", dove l'incasso online e' solo l'anticipo.
"""
import io
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def leggi(p):
    return io.open(os.path.join(REPO, p), encoding="utf-8", errors="replace").read()


def _num(src, pat, default=None):
    m = re.search(pat, src)
    return int(m.group(1)) if m else default


# ── 1) LE NOSTRE PERCENTUALI, LETTE DAL CODICE ───────────────────────────────
_main = leggi("main_casavip.py")
_f98 = leggi("fase98_policy_commissione.py")

PSP_BPS = _num(_main, r'PAGAMENTO_BPS["\']\s*,\s*["\'](\d+)["\']')
PSP_BPS_ESTERA = _num(_main, r'PAGAMENTO_BPS_ESTERA["\']\s*,\s*["\'](\d+)["\']')
PSP_FISSO = _num(_main, r'PAGAMENTO_FISSO_CENTS["\']\s*,\s*["\'](\d+)["\']')
COMM_BPS = _num(_main, r'COMMISSIONE_BPS["\']\s*,\s*["\'](\d+)["\']')
BPS_DIRETTO = _num(_f98, r'BPS_DIRETTO\s*=\s*(\d+)')
LANCIO_BPS_FASE1 = _num(_f98, r'LANCIO_BPS_FASE1\s*=\s*(\d+)')
LANCIO_BPS_REGIME = _num(_f98, r'LANCIO_BPS_REGIME\s*=\s*(\d+)')
LANCIO_GIORNI_GRATIS = _num(_f98, r'LANCIO_GIORNI_GRATIS\s*=\s*(\d+)')

_mancanti = [n for n, v in (("PAGAMENTO_BPS", PSP_BPS),
                            ("PAGAMENTO_BPS_ESTERA", PSP_BPS_ESTERA),
                            ("PAGAMENTO_FISSO_CENTS", PSP_FISSO),
                            ("COMMISSIONE_BPS", COMM_BPS),
                            ("BPS_DIRETTO", BPS_DIRETTO),
                            ("LANCIO_BPS_FASE1", LANCIO_BPS_FASE1),
                            ("LANCIO_BPS_REGIME", LANCIO_BPS_REGIME)) if v is None]
if _mancanti:
    # D18 punto 1: lo strumento misura PRIMA se stesso. Se non sa leggere le nostre
    # percentuali non stampa un numero comodo: si ferma.
    print("FERMO: non riesco a leggere dal codice: " + ", ".join(_mancanti))
    print("USCITA: 2")
    sys.exit(2)

# ── 2) I COSTI STRIPE ────────────────────────────────────────────────────────
# (nome, percentuale in bps, quota fissa in centesimi, serve la conversione?)
#
# ⚠ IL 2026-08-10 QUESTA TABELLA DICEVA IL FALSO IN DUE PUNTI, ed e' la ragione per cui
#   lo strumento gridava "MAI IN PARI" su una tariffa che invece copre:
#   · la carta internazionale stava a 315 bps perche' cosi' dice il LISTINO. Misurata
#     sull'API vera (120 addebiti con `sk_test`) e' 325: 675 su 20000 e 67 su 1300 sono
#     esattamente 3,25% + 25. Il listino dichiara meno di quanto Stripe prende davvero.
#   · l'ultima riga non e' una carta diversa: e' la STESSA carta su un annuncio prezzato
#     fuori euro. La conversione (+2%, misurata esatta, e torna come voce separata) c'e'
#     solo li' -- e proprio li' noi non applichiamo il 5% ma il 7% (PAGAMENTO_BPS_ESTERA).
#     Confrontare quel costo col 5% significa confrontarlo con un prezzo che non pratichiamo.
CARTE = [
    ("europea standard",        150, 25, False),
    ("britannica",              250, 25, False),
    ("europea premium",         280, 25, False),
    ("internazionale",          325, 25, False),   # 3,25% MISURATO (il listino dice 3,15)
    ("internaz. + cambio val.", 525, 25, True),    # 3,25% + 2% conversione, misurati
]

# ── 3) LE ETA' DELL'HOST (la rampa) ──────────────────────────────────────────
CANALI = [
    ("promo, primi %d gg" % LANCIO_GIORNI_GRATIS, 0),
    ("link diretto host",                          BPS_DIRETTO),
    ("da 90 gg a 1 anno",                          LANCIO_BPS_FASE1),
    ("oltre 1 anno (regime)",                      LANCIO_BPS_REGIME),
]

IMPORTI = [1300, 2500, 5000, 10000, 20000, 50000]      # centesimi


def costo_stripe(importo, bps, fisso):
    return (importo * bps) // 10000 + fisso


def eur(c):
    return "%8.2f" % (c / 100.0)


def main():
    print("=" * 78)
    print("I CONTI CONTRO STRIPE -- la tariffa tecnica copre il costo della carta?")
    print("=" * 78)
    print("  LE NOSTRE PERCENTUALI, lette adesso dal codice:")
    print("    tariffa tecnica (PAGAMENTO_BPS) .. %d bps = %.2f%% + %.2f EUR fissi"
          % (PSP_BPS, PSP_BPS / 100.0, PSP_FISSO / 100.0))
    print("    ... su annunci NON in euro ....... %d bps = %.2f%% + %.2f EUR fissi"
          % (PSP_BPS_ESTERA, PSP_BPS_ESTERA / 100.0, PSP_FISSO / 100.0))
    print("    commissione a regime ............. %d bps = %.2f%%" % (COMM_BPS, COMM_BPS / 100.0))
    print("    link diretto ..................... %d bps = %.2f%%"
          % (BPS_DIRETTO, BPS_DIRETTO / 100.0))
    print("    rampa: 0%% per %d gg -> %.0f%% -> %.0f%%"
          % (LANCIO_GIORNI_GRATIS, LANCIO_BPS_FASE1 / 100.0, LANCIO_BPS_REGIME / 100.0))
    print("  I COSTI STRIPE: MISURATI sull'API vera il 2026-08-09 (chiave di prova,")
    print("    120 addebiti + 60 rimborsi). Extra-UE = 3,25% + 0,25 EUR, conversione +2%.")
    print("    Il listino (stripe.com/it/pricing) dichiara 3,15%: prende piu' di quanto dice.")

    # ── DOMANDA (a): la tariffa tecnica copre Stripe? ────────────────────────
    print("\n" + "=" * 78)
    print("(a) LA TARIFFA TECNICA COPRE STRIPE?  (%.0f%% in euro, %.0f%% fuori euro,"
          % (PSP_BPS / 100.0, PSP_BPS_ESTERA / 100.0))
    print("    piu' %.2f EUR fissi in tutti e due i casi)" % (PSP_FISSO / 100.0))
    print("=" * 78)
    print("%-26s%10s%10s%10s   %s" % ("carta", "noi", "Stripe", "diff", "su 13,00 EUR"))
    print("-" * 78)
    scoperte_sempre = []
    pareggi = {}
    for nome, bps, fisso, cambio in CARTE:
        # La riga col cambio NON e' una carta diversa: e' un annuncio prezzato fuori euro,
        # e li' la tariffa e' PSP_BPS_ESTERA. Confrontarla col 5% sarebbe confrontare il
        # costo con un prezzo che non pratichiamo -- l'errore che questo strumento faceva.
        nostro_bps = PSP_BPS_ESTERA if cambio else PSP_BPS
        nostro13 = (1300 * nostro_bps) // 10000 + PSP_FISSO
        loro13 = costo_stripe(1300, bps, fisso)
        d13 = nostro13 - loro13
        # Pareggio con la quota fissa da tutte e due le parti:
        #   noi = X*nostro/10000 + PSP_FISSO   loro = X*bps/10000 + fisso
        _dp, _df = nostro_bps - bps, PSP_FISSO - fisso
        if _dp > 0 and _df >= 0:
            pareggi[nome] = 0
            nota = "copre a QUALUNQUE importo"
        elif _dp > 0:
            pareggio = (-_df * 10000) // _dp
            pareggi[nome] = pareggio
            nota = "pari a %.2f EUR" % (pareggio / 100.0)
        else:
            pareggi[nome] = None
            scoperte_sempre.append(nome)
            nota = "MAI IN PARI (%.2f%% < %.2f%%)" % (nostro_bps / 100.0, bps / 100.0)
        print("%-26s%10s%10s%10s   %s" % (nome, eur(nostro13), eur(loro13), eur(d13), nota))
    print("-" * 78)
    print("  'pari a X' = sotto quell'importo la tariffa tecnica NON copre Stripe.")

    # ── DOMANDA (b): ci rimettiamo davvero? ──────────────────────────────────
    print("\n" + "=" * 78)
    print("(b) CI RIMETTIAMO DAVVERO?  (commissione + tariffa tecnica) - costo Stripe")
    print("=" * 78)
    rossi = []
    for etichetta, comm_bps in CANALI:
        print("\n  --- %s  (commissione %.0f%%) ---" % (etichetta, comm_bps / 100.0))
        print("  %-26s" % "carta" + "".join("%9.2f" % (i / 100.0) for i in IMPORTI))
        for nome, bps, fisso, cambio in CARTE:
            nostro_bps = PSP_BPS_ESTERA if cambio else PSP_BPS
            riga = []
            for imp in IMPORTI:
                incasso = ((imp * comm_bps) // 10000
                           + (imp * nostro_bps) // 10000 + PSP_FISSO)
                netto = incasso - costo_stripe(imp, bps, fisso)
                riga.append("%9.2f" % (netto / 100.0))
                if netto < 0:
                    rossi.append((etichetta, nome, imp, netto))
            print("  %-26s" % nome + "".join(riga))
    print("\n  (numeri in EUR: quanto ci resta in tasca dopo aver pagato Stripe)")

    # ── VERDETTO ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print("VERDETTO")
    print("=" * 78)
    if scoperte_sempre:
        print("  !! la tariffa tecnica NON copre Stripe A NESSUN IMPORTO per: "
              + ", ".join(scoperte_sempre))
    for nome, p in sorted((k, v) for k, v in pareggi.items() if v):
        print("  -> %-26s la copre solo sopra %8.2f EUR" % (nome, p / 100.0))
    print()
    if rossi:
        print("  CASI IN CUI CI RIMETTIAMO DAVVERO (tutto compreso): %d" % len(rossi))
        peggiori = sorted(rossi, key=lambda r: r[3])[:6]
        for et, carta, imp, netto in peggiori:
            print("    %-22s %-24s su %7.2f EUR -> %7.2f EUR"
                  % (et, carta, imp / 100.0, netto / 100.0))
    else:
        print("  Nessun caso in perdita piena.")
    uscita = 1 if (rossi or scoperte_sempre) else 0
    print("=" * 78)
    print("USCITA: %d" % uscita)
    return uscita


if __name__ == "__main__":
    sys.exit(main())
