"""
Runner OPERATIVO acquisizione host BookinVIP (il pezzo che mancava per LANCIARE l'outreach).
Trova host via OpenStreetMap (dati business PUBBLICI, zero scraping) -> gate giurisdizioni
fail-closed (UE esclusa di default) -> email 'Prima Emilia' localizzata con opt-out -> invia
(SMTP gated) o DRY-RUN. Default = DRY-RUN (NON spedisce). Sicurezza cablata: solo business
pubblici, allow-list giurisdizioni, opt-out durevole rispettato. NIENTE scraping/proxy.

  python outreach_runner.py --paese US --limit 50          # anteprima (NON invia)
  python outreach_runner.py --paese US --limit 50 --invia  # invia davvero (richiede SMTP)

ENV: OUTREACH_GIURISDIZIONI (default US), OUTREACH_CONCORRENTI_BPS (default 2500),
     OUTREACH_OPTOUT_FILE, BASE_URL, SMTP_HOST/PORT/USER/PASSWORD, EMAIL_MITTENTE.
"""
from __future__ import annotations

import argparse
import os
from typing import Any, List, Optional, Tuple


def costruisci_runner(*, optout_file: Optional[str], giurisdizioni: List[str],
                      link_optout: str, smtp: Optional[Tuple] = None, fetch: Any = None):
    """Assembla fonte (OSM) + motore outreach durevole + invio email reale (se SMTP)."""
    from fase96_fonte_osm import crea_fonte_osm
    from fase95_outreach_email import crea_motore_outreach_durevole, adatta_invio_email
    fonte = crea_fonte_osm(fetch=fetch)
    motore = crea_motore_outreach_durevole(percorso_optout=optout_file,
                                           giurisdizioni_permesse=giurisdizioni,
                                           link_opt_out=link_optout)
    invia_reale = None
    if smtp:
        from fase86_email import crea_provider_email
        ep = crea_provider_email(*smtp)
        if ep is not None:
            invia_reale = adatta_invio_email(ep)
    return fonte, motore, invia_reale


def esegui_outreach(runner, *, paese: str, limit: int = 50, settore: str = "hospitality",
                    concorrenti_bps: Optional[List[int]] = None, invia_live: bool = False):
    """Esegue una passata. DRY-RUN raccoglie i destinatari senza spedire (anteprima)."""
    fonte, motore, invia_reale = runner
    anteprima: List[str] = []

    def invia_dry(email, oggetto, corpo, lingua):
        anteprima.append(email)
        return True

    live = bool(invia_live and invia_reale)
    invia = invia_reale if live else invia_dry
    rep = motore.esegui(fonte, paese=paese, concorrenti_bps=concorrenti_bps or [2500],
                        invia=invia, settore=settore, limit=limit)
    rep["modalita"] = "LIVE" if live else "DRY-RUN"
    if not live:
        rep["anteprima_destinatari"] = anteprima
    return rep


def _smtp_da_env() -> Optional[Tuple]:
    if not os.environ.get("SMTP_HOST"):
        return None
    return (os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587")),
            os.environ.get("SMTP_USER", ""), os.environ.get("SMTP_PASSWORD", ""),
            os.environ.get("EMAIL_MITTENTE", ""))


def main(argv=None):
    p = argparse.ArgumentParser(description="Acquisizione host BookinVIP (OSM -> outreach legale)")
    p.add_argument("--paese", required=True, help="ISO-2 (es. US). UE esclusa di default.")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--settore", default="hospitality")
    p.add_argument("--invia", action="store_true", help="invia davvero (default: DRY-RUN)")
    a = p.parse_args(argv)
    giuris = [x.strip().upper() for x in
              os.environ.get("OUTREACH_GIURISDIZIONI", "US").split(",") if x.strip()]
    conc = [int(x) for x in os.environ.get("OUTREACH_CONCORRENTI_BPS", "2500").split(",")
            if x.strip().isdigit()] or [2500]
    base = os.environ.get("BASE_URL", "https://bookinvip.com")
    runner = costruisci_runner(
        optout_file=os.environ.get("OUTREACH_OPTOUT_FILE", ".outreach_optout.json"),
        giurisdizioni=giuris, link_optout=base + "/stop", smtp=_smtp_da_env())
    rep = esegui_outreach(runner, paese=a.paese, limit=a.limit, settore=a.settore,
                          concorrenti_bps=conc, invia_live=a.invia)
    print("[OUTREACH %s] paese=%s trovati=%s inviati=%s bloccati=%s motivi=%s" % (
        rep.get("modalita"), a.paese, rep.get("trovati"), rep.get("inviati"),
        rep.get("bloccati"), rep.get("motivi")))
    if rep.get("modalita") == "DRY-RUN" and rep.get("anteprima_destinatari"):
        print("  anteprima destinatari:", rep["anteprima_destinatari"])
    return rep


if __name__ == "__main__":
    main()
