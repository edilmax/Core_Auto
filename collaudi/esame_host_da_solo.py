"""L'ESAME DELLA CASELLA 1 DEL BLOCCO 7 — «un host si iscrive, carica un annuncio e incassa
SENZA che nessuno lo aiuti».

    python collaudi/esame_host_da_solo.py              percorre il viaggio e MOSTRA
    python collaudi/esame_host_da_solo.py --scrivi     misura e SCRIVE nella scheda
    python collaudi/esame_host_da_solo.py --con-guasto toglie un passo: deve gridare, e NON
                                                       scrive mai
    python collaudi/esame_host_da_solo.py --autoprova  si vede gridare e tacere, senza montare
                                                       il sistema (D18 punto 2)

⛔ LA CASELLA SI TROVA PER SOTTOSTRINGA («SENZA che nessuno lo aiuti»), e dev'essere UNA sola.

COSA MISURA. Monta il sistema vero in una cartella temporanea, crea il router con `crea_router`
e percorre **le rotte che usa un browser**, dalla prima all'ultima. Nessuna scorciatoia interna:
se un passo non si puo' fare da una rotta, la casella e' rossa — ed e' il risultato che
cerchiamo, non un ostacolo da aggirare.

  1  l'host legge il contratto            GET  /api/legale/contratto-host
  2  si registra con le TRE spunte        POST /api/host/registrazione
  3  entra col suo utente                 POST /api/host/login
  4  pubblica l'annuncio                  POST /api/host/pubblica          (con il SUO token)
  5  apre il calendario                   POST /api/host/disponibilita_range
  6  un ospite chiede il prezzo           POST /api/concierge/quote
  7  l'ospite prenota                     POST /api/concierge/book
  8  Stripe conferma il pagamento         POST /api/payments/webhook       (firma vera)
  9  l'ospite conferma il soggiorno       POST /api/garanzia/conferma
 10  l'host VEDE i suoi soldi             GET  /api/host/payout            (con il SUO token)

⛔ IL PASSO 4 SI FA COL **TOKEN DELL'HOST**, MAI CON LA CHIAVE GLOBALE `X-Host-Key`. La casella
   dice «senza che nessuno lo aiuti»: pubblicare con la chiave d'amministrazione sarebbe
   esattamente l'aiuto che la casella vieta, e un esame che la usasse direbbe verde su un
   prodotto in cui l'host da solo non pubblica. E' il modo piu' facile di barare qui dentro, e
   per questo c'e' un passo che lo verifica al contrario (passo 4-bis: la chiave globale NON
   dev'essere necessaria).

⛔ PERCHE' STRIPE E' FINTO, E PERCHE' NON E' UN CONDONO. `stripe_secret_key` vuota **spegne il
   cancello del pagamento**: la prenotazione si conferma senza che nessuno paghi, e il payout
   matura lo stesso. Misurato il 2026-09-06: con la chiave vuota il maturato era gia' 18000
   PRIMA del webhook. Un esame montato cosi' direbbe «l'host incassa» **senza aver mai provato
   un incasso** -- il verde piu' pericoloso possibile su questa casella. Percio' la chiave c'e'
   (finta) e il provider e' sostituito: il pagamento e' RICHIESTO, e il payout matura **solo**
   dopo il webhook. Il passo 7-bis lo verifica: prima del webhook il maturato dev'essere ZERO.

⛔ D18: 1. `precondizioni` · 2. `--autoprova` nelle due direzioni · 3. `NON_GUARDA` ·
   4. sotto guardia in `test_pipeline_ci.TestLEsameDellHostDaSoloNonPuoBARARE`.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time

QUI = os.path.dirname(os.path.abspath(__file__))
RADICE = os.path.dirname(QUI)
sys.path.insert(0, QUI)
sys.path.insert(0, RADICE)

import scheda  # noqa: E402
from piano import BLOCCHI  # noqa: E402

BLOCCO = 7
MARCA = "SENZA che nessuno lo aiuti"
COMANDO = "python collaudi/esame_host_da_solo.py --scrivi"
WH = "whsec_esame"

NON_GUARDA = (
    "non manda una email vera: il provider e' spento, quindi non dice se l'host RICEVE",
    "  l'avviso di benvenuto o di prenotazione (e' un'altra casella, e oggi non e' misurata)",
    "non parla con Stripe vero: il provider e' sostituito, quindi non dice se una carta vera",
    "  passa, ne' se il bonifico arriva davvero sul conto dell'host",
    "non fa il KYC: l'onboarding Connect (documenti, verifica identita') resta fuori",
    "non guarda le PAGINE: prova le rotte, non che i pulsanti del pannello le chiamino",
    "non misura il tempo ne' la fatica: dice che il percorso ESISTE, non che sia facile",
)

CHIAMATE_STRIPE = []


def _fetch_finto(url, body, headers):
    """Finto Stripe che REGISTRA: senza registrare non si distingue «ho chiesto il pagamento»
    da «ho scritto pagato nel database». Stessa forma del finto di `test_admin_rimborso_money`."""
    import secrets
    CHIAMATE_STRIPE.append({"url": url, "body": (body or b"").decode("utf-8", "replace")})
    if "/refunds" in url:
        return {"id": "re_" + secrets.token_hex(4), "status": "succeeded", "amount": 1}
    return {"url": "https://pagamento/" + secrets.token_hex(4), "id": "cs_" + secrets.token_hex(4)}


# --------------------------------------------------------------------------------------
#  LA CASELLA
# --------------------------------------------------------------------------------------
def caselle_candidate(blocchi=None):
    blocchi = BLOCCHI if blocchi is None else blocchi
    cond = [b for b in blocchi if b["ordine"] == BLOCCO][0]["finito_quando"]
    return [c for c in cond if MARCA in " ".join(str(c).split())]


def testo_della_casella(blocchi=None):
    trovate = caselle_candidate(blocchi)
    if len(trovate) != 1:
        raise LookupError("la casella con «%s» nel blocco %d: trovate %d, ne serve UNA"
                          % (MARCA, BLOCCO, len(trovate)))
    return trovate[0]


# --------------------------------------------------------------------------------------
#  IL VIAGGIO — ogni passo e' (nome, riuscito, dettaglio)
# --------------------------------------------------------------------------------------
def percorri(salta=None):
    """Percorre il viaggio dalle rotte vere. `salta` = nome di un passo da NON eseguire
    (serve a `--con-guasto`: un passo tolto deve far cadere il giudizio)."""
    import fase85_pagamenti_stripe as _stripe
    from fase81_bootstrap_casavip import ConfigCasaVIP, crea_sistema
    from fase83_server import crea_router
    from fase163_accettazioni import CONTRATTO_HOST_VERSIONE, doc_sha256
    from fase87_stripe_webhook import firma_di_test

    del CHIAMATE_STRIPE[:]
    passi = []

    def p(nome, riuscito, dettaglio=""):
        if nome == salta:
            return True
        passi.append((nome, bool(riuscito), str(dettaglio)[:120]))
        return bool(riuscito)

    originale = _stripe.ProviderStripe._fetch_reale
    _stripe.ProviderStripe._fetch_reale = staticmethod(_fetch_finto)
    d = tempfile.mkdtemp()
    try:
        sis = crea_sistema(ConfigCasaVIP(
            abilitato=True, segreto_hmac=b"S" * 32, con_registrazione_host=True,
            db_catalogo=d + "/c.db", db_inventario=d + "/i.db", db_registro_host=d + "/r.db",
            db_accettazioni=d + "/acc.db", db_pendenti=d + "/p.db", db_payout=d + "/pay.db",
            db_garanzia=d + "/g.db", db_tassa_comunale=d + "/t.db",
            commissione_bps=1000, psp_bps=0, stripe_secret_key="sk",
            stripe_webhook_secret=WH, stripe_success_url="https://x/ok",
            stripe_cancel_url="https://x/no"))
        r = crea_router(sis, host_key="hk", admin_key="ak", base_url="https://bookinvip.com")

        def g(m, path, corpo=None, intest=None, query=None):
            return r.gestisci(m, path, query or {},
                              json.dumps(corpo) if corpo is not None else None, intest or {})

        s, doc = g("GET", "/api/legale/contratto-host", None, None, {"lang": "it"})
        p("1 legge il contratto", s == 200 and doc.get("doc_sha256"), "http %s" % s)

        s, reg = g("POST", "/api/host/registrazione",
                   {"email": "host@esame.it", "password": "password1",
                    "ragione_sociale": "Casa Esame", "accetta_termini": True,
                    "accetta_clausole": True, "accetta_privacy": True,
                    "doc_sha256": doc_sha256(), "versione": CONTRATTO_HOST_VERSIONE})
        p("2 si registra con le 3 spunte", s == 201 and reg.get("host_id"), "http %s" % s)
        token = (reg or {}).get("token") or ""
        hid = (reg or {}).get("host_id") or ""
        HT = {"X-Host-Token": token}

        s, log = g("POST", "/api/host/login",
                   {"email": "host@esame.it", "password": "password1"})
        p("3 entra col suo utente", s == 200 and log.get("token"), "http %s" % s)

        annuncio = {"slug": "casa", "titolo": "Casa", "citta": "Roma", "descrizione": "x",
                    "prezzo_netto_cents": 10000, "prezzo_notte_cents": 10000, "capacita": 4,
                    "servizi": [], "immagini": [], "politica_cancellazione": "flessibile"}
        s, _ = g("POST", "/api/host/pubblica", annuncio, HT)
        p("4 pubblica col SUO token", s in (200, 201), "http %s" % s)

        s2, _ = g("POST", "/api/host/pubblica", dict(annuncio, slug="senza_token"), {})
        p("4-bis senza autenticazione NON pubblica", s2 not in (200, 201), "http %s" % s2)

        s, _ = g("POST", "/api/host/disponibilita_range",
                 {"alloggio_id": "casa", "da": "2026-11-01", "a": "2026-11-30",
                  "unita_totali": 1, "prezzo_netto_cents": 10000}, HT)
        p("5 apre il calendario", s == 200, "http %s" % s)

        s, q = g("POST", "/api/concierge/quote",
                 {"alloggio_id": "casa", "check_in": "2026-11-10",
                  "check_out": "2026-11-12", "party": 2})
        p("6 l'ospite chiede il prezzo", s == 200 and q.get("quote_token"), "http %s" % s)

        s, b = g("POST", "/api/concierge/book",
                 {"quote_token": (q or {}).get("quote_token"), "email": "ospite@esame.it"})
        p("7 l'ospite prenota", s in (200, 201) and b.get("riferimento"), "http %s" % s)

        chiesto = any("/checkout/sessions" in c["url"] or "/payment" in c["url"]
                      for c in CHIAMATE_STRIPE)
        p("7-bis il pagamento e' stato CHIESTO a Stripe", chiesto,
          "%d chiamate" % len(CHIAMATE_STRIPE))
        prima = sis.payout.riepilogo(hid)
        p("7-ter prima del pagamento il maturato e' ZERO",
          not any((v or {}).get("maturato") for v in (prima or {}).values()), json.dumps(prima))

        rif = (b or {}).get("riferimento") or ""
        pl = json.dumps({"type": "checkout.session.completed",
                         "data": {"object": {"id": "cs_esame", "payment_intent": "pi_esame",
                                             "metadata": {"riferimento": rif}}}})
        s, _ = r.gestisci("POST", "/api/payments/webhook", {}, pl,
                          {"Stripe-Signature": firma_di_test(pl, WH, int(time.time()))})
        p("8 Stripe conferma il pagamento", s == 200, "http %s" % s)

        dopo = sis.payout.riepilogo(hid)
        p("8-bis dopo il pagamento il maturato e' > 0",
          any((v or {}).get("maturato") for v in (dopo or {}).values()), json.dumps(dopo))

        s, c = g("POST", "/api/garanzia/conferma",
                 {"voucher_token": (b or {}).get("voucher_token")})
        p("9 l'ospite conferma il soggiorno", s == 200 and c.get("stato") == "rilasciato",
          "http %s %s" % (s, (c or {}).get("stato")))

        s, pay = g("GET", "/api/host/payout", None, HT)
        visto = any((v or {}).get("maturato") for v in (pay or {}).get("payout", {}).values())
        p("10 l'host VEDE i suoi soldi dal pannello", s == 200 and visto,
          "http %s %s" % (s, json.dumps((pay or {}).get("payout"))))
        return passi
    finally:
        _stripe.ProviderStripe._fetch_reale = originale
        shutil.rmtree(d, ignore_errors=True)


# --------------------------------------------------------------------------------------
#  GIUDIZIO
# --------------------------------------------------------------------------------------
# ⛔ IL CONTRATTO DEL VIAGGIO: i NOMI dei passi, non il loro NUMERO.
#    La prima versione diceva `ATTESI = 13` ed era sbagliata (i passi sono 14): un numero
#    scritto a mano che nessuno ricontrolla. Ma il difetto non era il valore, era la FORMA --
#    un conteggio non si accorge di un passo **rinominato**, ne' di uno sostituito con un
#    altro. L'elenco dei nomi si accorge di tutti e tre i casi, e per giunta e' la
#    documentazione del percorso: chi lo legge sa cosa promette l'esame.
PASSI_ATTESI = (
    "1 legge il contratto",
    "2 si registra con le 3 spunte",
    "3 entra col suo utente",
    "4 pubblica col SUO token",
    "4-bis senza autenticazione NON pubblica",
    "5 apre il calendario",
    "6 l'ospite chiede il prezzo",
    "7 l'ospite prenota",
    "7-bis il pagamento e' stato CHIESTO a Stripe",
    "7-ter prima del pagamento il maturato e' ZERO",
    "8 Stripe conferma il pagamento",
    "8-bis dopo il pagamento il maturato e' > 0",
    "9 l'ospite conferma il soggiorno",
    "10 l'host VEDE i suoi soldi dal pannello",
)


def giudica(passi, attesi=PASSI_ATTESI):
    denominatore = len(passi)
    if denominatore == 0:
        return False, 0, "nessun passo percorso: un verde senza viaggio e' cieco"
    nomi = [n for n, _, _ in passi]
    mancanti = [n for n in attesi if n not in nomi]
    estranei = [n for n in nomi if n not in attesi]
    if mancanti or estranei:
        return False, denominatore, (
            "il viaggio non e' quello dichiarato: %d passi su %d. Mancano: %s. Non previsti: %s"
            % (denominatore, len(attesi), mancanti[:3] or "-", estranei[:3] or "-"))
    caduti = [(n, dett) for n, ok, dett in passi if not ok]
    if caduti:
        return False, denominatore, ("l'host NON ce la fa da solo: %d passi su %d falliscono -> %s"
                                     % (len(caduti), denominatore,
                                        "; ".join("%s (%s)" % (n, d) for n, d in caduti[:3])))
    return True, denominatore, ""


# --------------------------------------------------------------------------------------
def precondizioni():
    fuori = []
    try:
        trovate = caselle_candidate()
        fuori.append(("la casella «%s» esiste nel piano, UNA sola" % MARCA, len(trovate) == 1,
                      "trovate %d" % len(trovate)))
    except Exception as e:
        fuori.append(("la casella esiste nel piano, UNA sola", False,
                      "%s: %s" % (type(e).__name__, e)))
    for modulo in ("fase81_bootstrap_casavip", "fase83_server", "fase85_pagamenti_stripe",
                   "fase87_stripe_webhook", "fase163_accettazioni"):
        try:
            __import__(modulo)
            fuori.append(("so importare %s" % modulo, True, "ok"))
        except Exception as e:
            fuori.append(("so importare %s" % modulo, False, "%s" % type(e).__name__))
    return fuori


def autoprova():
    n = len(PASSI_ATTESI)
    completo = [(nome, True, "") for nome in PASSI_ATTESI]
    rinominato = completo[:-1] + [(PASSI_ATTESI[-1] + " (ritoccato)", True, "")]
    casi = [
        ("viaggio completo, tutti i passi riusciti", completo, True, n),
        ("un passo TOLTO (viaggio corto)", completo[:-1], False, n - 1),
        ("un passo RINOMINATO (stesso numero!)", rinominato, False, n),
        ("nessun passo", [], False, 0),
        ("un passo fallito", completo[:-1] + [(PASSI_ATTESI[-1], False, "http 500")], False, n),
        ("tutti i passi falliti", [(nm, False, "x") for nm, _, _ in completo], False, n),
    ]
    print("AUTOPROVA — l'esame sa gridare E sa tacere (D18 punto 2)")
    tutto = True
    for nome, passi, atteso_verde, atteso_den in casi:
        verde, den, motivo = giudica(passi)
        bene = (verde == atteso_verde) and (den == atteso_den)
        tutto = tutto and bene
        print("  %-42s -> %-5s den=%-3d %s" % (nome[:42], "VERDE" if verde else "rosso", den,
                                               "OK" if bene else "⛔ ATTESO DIVERSO"))
        if motivo and not verde:
            print("        perche': %s" % motivo[:104])
    print("")
    print("  la casella si trova per sottostringa, e dev'essere UNA sola:")
    finti = {"una sola": ["x " + MARCA, "altro"], "nessuna": ["altro", "ancora"],
             "due (ambigua)": ["a " + MARCA, "b " + MARCA]}
    attesi = {"una sola": True, "nessuna": False, "due (ambigua)": False}
    for nome, cond in finti.items():
        try:
            testo_della_casella([{"ordine": BLOCCO, "finito_quando": cond}])
            esito = True
        except LookupError:
            esito = False
        bene = esito == attesi[nome]
        tutto = tutto and bene
        print("    %-16s -> %-9s %s" % (nome, "trovata" if esito else "si ferma",
                                        "OK" if bene else "⛔ ATTESO DIVERSO"))
    print("")
    print("VERDETTO AUTOPROVA: %s" % ("l'esame distingue tutti i casi"
                                      if tutto else "⛔ NON DISTINGUE: non fidarsi"))
    return 0 if tutto else 1


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--autoprova" in argv:
        return autoprova()

    print("=" * 92)
    try:
        print("L'ESAME DELL'HOST DA SOLO — «%s»"
              % " ".join(str(testo_della_casella()).split())[:70])
    except Exception:
        print("L'ESAME DELL'HOST DA SOLO — (casella non trovata nel piano)")
    print("=" * 92)

    fuori = precondizioni()
    print("PRECONDIZIONI (l'attrezzo misura prima se stesso)")
    for voce, esito, dett in fuori:
        print("  %-50s %-3s %s" % (voce[:50], "OK" if esito else "NO", str(dett)[:30]))
    if not all(e for _, e, _ in fuori):
        print("\n⛔ PRECONDIZIONI NON SODDISFATTE: mi fermo e NON scrivo nella scheda.")
        return 2

    salta = None
    if "--con-guasto" in argv:
        salta = "8 Stripe conferma il pagamento"
        print("\n⚠️  --con-guasto: tolgo il passo «%s». Deve gridare, e NON scrivere." % salta)

    print("\nIL VIAGGIO, dalle rotte vere")
    passi = percorri(salta=salta)
    for nome, ok, dett in passi:
        print("  %-46s %-3s %s" % (nome[:46], "OK" if ok else "NO", dett[:34]))

    verde, denominatore, motivo = giudica(passi)
    print("")
    print("MISURA")
    print("  passi percorsi (il denominatore) : %d su %d attesi" % (denominatore, len(PASSI_ATTESI)))
    print("  chiamate a Stripe registrate     : %d" % len(CHIAMATE_STRIPE))
    print("  esito                            : %s" % ("VERDE" if verde else "ROSSO"))
    if motivo:
        print("  perche'                          : %s" % motivo)

    print("")
    print("⚠️  COSA QUESTO ESAME **NON** GUARDA (D18 punto 3)")
    for r_ in NON_GUARDA:
        print("  · %s" % r_)

    if "--scrivi" in argv:
        if salta:
            print("\n⛔ --con-guasto NON scrive mai nella scheda.")
            return 1
        print("\nSCRITTURA NELLA SCHEDA")
        riga = scheda.registra(testo_della_casella(), esito=verde, denominatore=denominatore,
                               comando=COMANDO, ordine=BLOCCO, motivo=motivo or None)
        print("  scritta: blocco %d · esito %s · denominatore %d · impronta %s · motivo: %s"
              % (riga["blocco"], riga["esito"], riga["denominatore"], riga["impronta"],
                 riga.get("motivo") or "-"))
    return 0 if verde else 1


if __name__ == "__main__":
    sys.exit(main())
