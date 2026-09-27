"""L'ESAME DELLA CASELLA «CHI PAGA COSA IN UN RIMBORSO E' SCRITTO» — blocco SOLDI.

    python collaudi/esame_rimborso_scritto.py               misura e MOSTRA, senza scrivere
    python collaudi/esame_rimborso_scritto.py --scrivi      misura e SCRIVE la casella
    python collaudi/esame_rimborso_scritto.py --autoprova   si vede gridare e tacere (D18 p.2)

La casella chiede tre cose insieme, e l'esame le misura tutte e tre:
  1. SCRITTO ALL'OSPITE, in tutte le lingue dei termini (fase185, capitolo 7): gli torna il
     prezzo secondo la politica e la tassa di soggiorno per intero, senza trattenute; e
     siccome il motore applica il ripensamento, anche quello (48 ore, almeno 3 giorni
     all'arrivo): scrivere «secondo la politica» e basta sarebbe impreciso.
  2. SCRITTO ALL'HOST, nel contratto (fase163, tutte le sue lingue): sulla parte trattenuta
     commissione e tariffa tecnica restano dovute pro quota, e il costo del gestore di
     pagamento non torna a nessuno.
  3. COINCIDE COL MOTORE: le cifre scritte (48, 3) sono lette dal codice; la regola del
     rimborso (fase111) si prova su tutte le politiche; i fatti del percorso di
     cancellazione (fase83) si leggono dal sorgente; le guardie vere si ESEGUONO.

⛔ Il testo della casella non si ricopia: si cerca in `piano.py` per contenuto e si pretende
   unico. ⛔ D18: precondizioni, autoprova, NON_GUARDA, guardia in test_pipeline_ci.
"""
import io
import os
import re
import sys
import unittest

QUI = os.path.dirname(os.path.abspath(__file__))
RADICE = os.path.dirname(QUI)
for _p in (RADICE, QUI):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from piano import BLOCCHI  # noqa: E402
import scheda  # noqa: E402

BLOCCO_SOLDI = 1
SEGNALE = "chi paga cosa in un rimborso"
COMANDO = "python collaudi/esame_rimborso_scritto.py --scrivi"
GUARDIE = ("test_tassa_storno", "test_fase111_cancellazione", "test_fase111_endpoint",
           "test_fase160_escrow_garanzia")

# Cio' che il capitolo 7 dei termini deve DIRE in ogni lingua. {ORE} e {GIORNI} si
# riempiono con i numeri letti dal motore: una cifra scritta diversa non passa.
ALL_OSPITE = {
    "it": ("tassa di soggiorno per intero", "senza alcuna trattenuta", "{ORE} ore",
           "{GIORNI} giorni"),
    "en": ("tourist tax in full", "no deduction", "{ORE} hours", "{GIORNI} days"),
    "es": ("impuesto turistico integro", "sin ninguna retencion", "{ORE} horas",
           "{GIORNI} dias"),
    "fr": ("taxe de sejour en totalite", "sans aucune retenue", "{ORE} heures",
           "{GIORNI} jours"),
    "de": ("Kurtaxe vollstaendig", "ohne jeden Abzug", "{ORE} Stunden", "{GIORNI} Tage"),
    "pt": ("taxa turistica na totalidade", "sem qualquer retencao", "{ORE} horas",
           "{GIORNI} dias"),
    "ja": ("宿泊税の全額", "差し引かれることはありません", "{ORE}時間", "{GIORNI}日"),
    "zh": ("住宿税全额", "不作任何扣除", "{ORE}小时", "{GIORNI}天"),
}
# Cio' che il contratto dell'host deve DIRE in ogni sua lingua.
ALL_HOST = {
    "it": ("pro quota", "gestore di pagamento", "non torna a nessuna delle parti",
           "tassa di soggiorno per intero"),
    "en": ("pro rata", "payment processor", "is not returned to either party",
           "tourist tax in full"),
}
NON_GUARDA = (
    "legge le PAROLE, non il senso: una frase che contiene le parole giuste e dice il "
    "contrario passerebbe. Le parole cercate sono scelte perche' dicano la cosa (per intero, "
    "senza trattenuta, pro quota), ma la rilettura di un avvocato resta fuori da qui",
    "non segue un rimborso vero con Stripe: il denaro che torna davvero lo misura "
    "`esame_rimborsi.py` (casella «i soldi tornano da OGNI strada»); qui si misura che "
    "cio' che e' SCRITTO sia cio' che il motore FA",
    "i casi di bordo del percorso (pagamento in struttura, tetto di cassa quando la garanzia "
    "e' gia' stata liquidata, credito viaggio) non sono scritti nei termini e l'esame non li "
    "pretende: la casella chiede la regola, non ogni eccezione",
)


def testo_casella():
    condizioni = BLOCCHI[BLOCCO_SOLDI - 1]["finito_quando"]
    trovate = [" ".join(str(c).split()) for c in condizioni if SEGNALE in str(c)]
    if len(trovate) != 1:
        raise ValueError("nel blocco %d le caselle che dicono %r sono %d, non 1: il piano e' "
                         "cambiato e questo esame non sa piu' a cosa punta"
                         % (BLOCCO_SOLDI, SEGNALE, len(trovate)))
    return trovate[0]


def sorgente(nome):
    with io.open(os.path.join(RADICE, nome), encoding="utf-8") as f:
        return f.read()


def numeri_del_motore():
    """Le due cifre che il testo promette, lette dal CODICE che le applica."""
    server = sorgente("fase83_server.py")
    m_ore = re.search(r"^SECONDI_RIPENSAMENTO\s*=\s*(\d+)\s*\*\s*3600", server, re.M)
    m_giorni = re.search(r"ripensamento = _entro_ripensamento\(v\) and \(giorni >= (\d+)\)",
                         server)
    if not (m_ore and m_giorni):
        raise ValueError("fase83 non dice piu' dove stanno le 48 ore o i 3 giorni: il "
                         "testo non si puo' confrontare col motore")
    return int(m_ore.group(1)), int(m_giorni.group(1))


def capitolo_7(testo):
    """Il capitolo 7 dei termini: da «7.» a «8.» (le sole righe che iniziano cosi')."""
    m = re.search(r"(?ms)^7\. .*?(?=^8\. )", testo)
    return m.group(0) if m else ""


def mancanze_scritte(termini, contratto, ore, giorni):
    """Elenco di (dove, lingua, parola mancante). Vuoto = tutto scritto."""
    fuori = []
    for lang, parole in ALL_OSPITE.items():
        cap = " ".join(capitolo_7(termini(lang)).split())
        if not cap:
            fuori.append(("termini", lang, "capitolo 7 non trovato"))
            continue
        for p in parole:
            p = p.format(ORE=ore, GIORNI=giorni)
            if p.lower() not in cap.lower():
                fuori.append(("termini", lang, p))
    for lang, parole in ALL_HOST.items():
        testo = " ".join(contratto(lang).split())
        for p in parole:
            if p.lower() not in testo.lower():
                fuori.append(("contratto", lang, p))
    return fuori


def regola_del_motore():
    """fase111 su TUTTE le politiche: rimborso + trattenuto = pagato (nessuna trattenuta
    nascosta a carico dell'ospite), e col ripensamento il rimborso e' intero."""
    from fase111_cancellazione import POLITICHE, calcola_rimborso
    errori, casi = [], 0
    for nome in POLITICHE:
        for pagato in (1, 999, 10000, 123457):
            for g in range(0, 41):
                casi += 1
                r = calcola_rimborso(pagato, g, politica=nome)
                if r["rimborso_cents"] + r["trattenuto_cents"] != pagato:
                    errori.append("%s/%d/%dg: rimborso+trattenuto != pagato" % (nome, pagato, g))
                r2 = calcola_rimborso(pagato, g, politica=nome, entro_ripensamento=True)
                if r2["rimborso_cents"] != pagato:
                    errori.append("%s/%d/%dg: ripensamento non intero" % (nome, pagato, g))
    return errori, casi


def fatti_del_percorso():
    """Cio' che il percorso di cancellazione dell'ospite (fase83) fa, letto dal sorgente."""
    s = sorgente("fase83_server.py")
    return {
        "la tassa si somma intera al rimborso":
            bool(re.search(r"rimborso_totale = r\.get\(\"rimborso_cents\", 0\) \+ tassa", s)),
        "all'host resta la sua quota in proporzione al trattenuto":
            bool(re.search(r"host_tiene = \(imp \* tratt // pagato\)", s)),
        "la base del rimborso e' il prezzo pagato dall'ospite":
            bool(re.search(r"pagato = v\.get\(\"prezzo_guest_cents\", 0\)", s)),
    }


def guardie():
    fuori = []
    for nome in GUARDIE:
        suite = unittest.TestLoader().loadTestsFromName(nome)
        flusso = io.StringIO()
        esito = unittest.TextTestRunner(stream=flusso, verbosity=0).run(suite)
        fuori.append((nome, esito.wasSuccessful(), esito.testsRun,
                      len(esito.failures) + len(esito.errors)))
    return fuori


def precondizioni():
    righe = []
    try:
        testo_casella()
        righe.append(("la casella si legge dal piano, una volta sola", True, SEGNALE))
    except Exception as e:
        righe.append(("la casella si legge dal piano, una volta sola", False, str(e)))
    try:
        ore, giorni = numeri_del_motore()
        righe.append(("le cifre si leggono dal motore", ore > 0 and giorni > 0,
                      "%d ore, %d giorni" % (ore, giorni)))
    except Exception as e:
        righe.append(("le cifre si leggono dal motore", False, str(e)))
    try:
        import fase163_accettazioni as c
        import fase185_testi_legali as t
        lingue_ok = set(ALL_OSPITE) == set(t.LINGUE) and set(ALL_HOST) == set(c.LINGUE_CONTRATTO)
        righe.append(("l'esame copre TUTTE le lingue dei documenti", lingue_ok,
                      "termini %s · contratto %s" % (",".join(t.LINGUE),
                                                     ",".join(c.LINGUE_CONTRATTO))))
    except Exception as e:
        righe.append(("l'esame copre TUTTE le lingue dei documenti", False, str(e)))
    for nome in GUARDIE:
        ok = os.path.isfile(os.path.join(RADICE, nome + ".py"))
        righe.append(("la guardia %s esiste" % nome, ok, nome if ok else "MANCA"))
    return all(ok for _, ok, _ in righe), righe


def misura():
    import fase163_accettazioni as c
    import fase185_testi_legali as t
    ore, giorni = numeri_del_motore()
    mancanze = mancanze_scritte(t.testo_termini, c.testo_contratto, ore, giorni)
    errori_regola, casi = regola_del_motore()
    fatti = fatti_del_percorso()
    g = guardie()
    motivi = []
    if mancanze:
        motivi.append("%d parole mancanti: %s" % (len(mancanze), "; ".join(
            "%s/%s «%s»" % m for m in mancanze[:12])))
    if errori_regola:
        motivi.append("regola del rimborso: %s" % "; ".join(errori_regola[:5]))
    falsi = [k for k, v in fatti.items() if not v]
    if falsi:
        motivi.append("percorso di cancellazione: non trovato %s" % ", ".join(falsi))
    rosse = [nome for nome, ok, _, _ in g if not ok]
    if rosse:
        motivi.append("guardie rosse: %s" % ", ".join(rosse))
    denominatore = (sum(len(v) for v in ALL_OSPITE.values())
                    + sum(len(v) for v in ALL_HOST.values()) + casi + len(fatti)
                    + sum(n for _, _, n, _ in g))
    return (not motivi), denominatore, " | ".join(motivi), mancanze, g


def autoprova():
    """D18 punto 2: su testi costruiti apposta la verifica delle parole deve GRIDARE se
    manca la tassa intera e TACERE sul testo completo."""
    ore, giorni = numeri_del_motore()

    def termini_completi(lang):
        return "7. X\n%s\n\n8. Y\n" % " ".join(p.format(ORE=ore, GIORNI=giorni)
                                              for p in ALL_OSPITE[lang])

    def contratto_completo(lang):
        return " ".join(ALL_HOST[lang])

    def termini_senza_tassa(lang):
        return termini_completi(lang).replace(ALL_OSPITE[lang][0], "")

    def termini_ora_sbagliata(lang):
        return termini_completi(lang).replace(str(ore), str(ore + 24))

    tace = mancanze_scritte(termini_completi, contratto_completo, ore, giorni) == []
    grida_tassa = len(mancanze_scritte(termini_senza_tassa, contratto_completo, ore,
                                       giorni)) == len(ALL_OSPITE)
    grida_ora = len(mancanze_scritte(termini_ora_sbagliata, contratto_completo, ore,
                                     giorni)) == len(ALL_OSPITE)
    return (grida_tassa and grida_ora), tace


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    tutte_ok, righe = precondizioni()
    print("=" * 86)
    print("🧾 ESAME RIMBORSO SCRITTO — «chi paga cosa in un rimborso» (blocco SOLDI)")
    print("=" * 86)
    for nome, ok, dettaglio in righe:
        print("  %-6s %s  %s" % ("OK" if ok else "ROSSO", nome, dettaglio))
    if not tutte_ok:
        print("VERDETTO: ⛔ NON ESEGUIBILE — le precondizioni non reggono (S7): niente "
              "scritture, niente numeri")
        return 2
    if "--autoprova" in argv:
        grida, tace = autoprova()
        print("  AUTOPROVA: grida col guasto=%s · tace a testo completo=%s" % (grida, tace))
        return 0 if (grida and tace) else 1
    esito, denominatore, motivo, mancanze, g = misura()
    for dove, lang, parola in mancanze:
        print("  MANCA  %-9s %-2s «%s»" % (dove, lang, parola))
    for nome, ok, n, rossi in g:
        print("  guardia %-32s %s (%d test, %d rossi)" % (nome, "VERDE" if ok else "ROSSA",
                                                         n, rossi))
    print("  casella %s  (denominatore %d)%s" % (
        "☑" if esito else "☐", denominatore, ("\n     perche': %s" % motivo) if motivo else ""))
    print("  ⛔ COSA NON GUARDA:")
    for r in NON_GUARDA:
        print("     · %s" % r)
    if "--scrivi" in argv:
        scheda.registra(testo_casella(), esito=esito, denominatore=denominatore,
                        comando=COMANDO, ordine=BLOCCO_SOLDI, motivo=motivo or None)
        print("  🗂️  casella scritta%s" % ("" if esito else " (falsa, col motivo)"))
    print("VERDETTO: %s — %d parole mancanti" % ("✅" if esito else "⛔", len(mancanze)))
    return 0 if esito else 1


if __name__ == "__main__":
    sys.exit(main())
