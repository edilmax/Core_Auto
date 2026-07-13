"""
Test anti-drift di ROADMAP_MANGO.md: il piano di riattivazione di Mango deve
esistere, coprire i 7 mattoni (fase43..fase49), il protocollo d'isolamento e il
fatto chiave che il motore booking NON viene toccato.
"""
import os
import unittest


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestRoadmapMango(unittest.TestCase):
    def setUp(self):
        self.doc = _read("ROADMAP_MANGO.md")

    def test_sette_mattoni(self):
        for n in range(43, 50):                      # fase43..fase49
            self.assertIn("fase{}".format(n), self.doc, "manca fase%d" % n)

    def test_protocollo_isolamento(self):
        for c in ("default-off", "lazy", "gate di regressione", "denaro dal SISTEMA",
                  "RicercaProvider", "492"):
            self.assertIn(c, self.doc, c)

    def test_correzione_presupposto(self):
        # deve chiarire che 24-33 sono gia' costruite e che Mango riusa l'esistente
        for c in ("Rana Inversa", "compliant", "non importano"):
            self.assertIn(c, self.doc, c)

    def _esiste(self, n):
        return any(f.startswith("fase{}_".format(n)) and f.endswith(".py")
                   for f in os.listdir("."))

    def test_mattoni_core_costruiti(self):
        # M1-M7: commissione, prezzo, split, esploratore, venditore, advertising,
        # ponte booking: fase43-49 (tutti i 7 mattoni Mango ora costruiti).
        for n in (43, 44, 45, 46, 47, 48, 49):
            self.assertTrue(self._esiste(n), "fase%d mancante" % n)

    def test_i_numeri_mango_futuri_sono_liberi(self):
        # mattoni a fase49; 50=orchestratore; 51=scheduler; 52=persistenza+metriche;
        # 53=health-guard; 54=loop; 55=bootstrap; 56=gateway tavoli;
        # 57=vetrina/catalogo pubblico (storefront);
        # 58=channel manager/inventario host tempo reale;
        # 59=protocollo concierge AI (agent-discoverable);
        # 60=MCP server (Model Context Protocol);
        # 61=localizzazione i18n a costo zero;
        # 62=predictive no-show + overbooking controllato;
        # 63=recensioni verificate (anti-fake);
        # 64=smart-pass d'ingresso/self check-in;
        # 65=split-payment di gruppo;
        # 66=tassa di soggiorno jurisdiction-agnostic;
        # 67=coda intelligente + cancellazione garantita;
        # 68=niche profiler (niche stacking);
        # 69=trasparenza commissionale (noi vs OTA);
        # 70=automated turnover (pulizie check-out->check-in);
        # 71=commitment engine (anti-cancellazione+cleaning+chargeback);
        # 72=digital twin (telemetria+manutenzione predittiva);
        # 73=firma agile (crypto-agility+anti-downgrade);
        # 74=sensory engine (sensory score);
        # 75=guardian engine (rilevamento pericoli+risposta);
        # 76=viral loop engine (crediti non-cashabili);
        # 77=portability import (GDPR/DMA data-portability);
        # 78=sleep guarantee (sleep-as-a-service money-back);
        # 79=dichiarazione vincolante (host dichiara, escrow paga);
        # 80=sentinel FIM+canary+catena integrita';
        # 81=bootstrap casa vip (composition root lodging);
        # 82=ical sync (portabilita' reale cross-canale);
        # 83=server HTTP (API + frontend, fase81+fase61);
        # 84=LIBERO (coordinatore multi-agente valutato e SCARTATO);
        # 85=provider pagamento Stripe (money-path);
        # 86=provider email voucher SMTP (gated);
        # 87=webhook Stripe (verifica firma + conferma pagamento);
        # 88=registro host self-service (registrazione/login/token firmato);
        # 89=jurisdiction B2B radar & outreach (gate giurisdizioni + email Prima Emilia);
        # 90=marketing & growth engine 360 (post multilingua + immagini SVG + calendario + canali);
        # 91=canali social reali (Telegram gratis + Meta FB/IG gated, da env, fetch iniettabile);
        # 92=canale X/Twitter (OAuth1 stdlib, gated, a pagamento); 93=canale TikTok (video-first, gated);
        # 94=scheduler auto-pubblicazione campagna (clock+store iniettabili, stato-file atomico, no-burst);
        # 95=outreach durevole (opt-out persistente file-atomico + adattatore invio email reale fase86);
        # 96=lead discovery mondiale da dati aperti OpenStreetMap/Overpass (no scraping/no proxy, innesto in fase89);
        # 97=inbound SEO/AEO (landing host per città + FAQ JSON-LD + llms.txt + sitemap, puro/XSS-safe, rotte /affitta /llms.txt);
        # 98=policy commissione (primi-1000-host via fase88.numero_host + split asimmetrico 3%host/12%ospite=15%, puro cents);
        # 99=multi-currency like-for-like ledger (Denaro tipizzato per valuta, no mix, split nella valuta annuncio, conversione trasparente anti-DCC);
        # 100=DAC7 gate (gated EU default-off, soglie configurabili 28pren/1800€ -> sospendi annuncio+blocca payout, registro durevole);
        # 101=Stripe Connect split-all'origine (destination charge: 85% al conto host, application_fee=nostra commissione; gated, fetch iniettabile);
        # 102=motore autonomo vendi+incassa (orchestra concierge59+inventario58+pagamento101+split65, duck-typed, isolato);
        # 103=adempimento reverse-charge (gated, autofattura TD17/TD18 + IVA 22% configurabile + scadenza F24 + registro durevole);
        # 104=gateway Asia (Alipay/WeChat Pay agganciati allo split 15% Stripe Connect fase101 + canale Weibo, gated);
        # 105=W3C identity gate (Verifiable Credential firmate HMAC per annunci host e recensioni guest, anti-truffa, puro);
        # 106=dynamic pricing (occupazione/domanda + stagionalità mese + weekend + last-minute/anticipo, bps interi, floor/cap, puro);
        # 107=i18n auto-traduzione annunci (default pass-through fase61 + backend LibreTranslate gratuito iniettabile + cache, isolato);
        # 109=referral host-porta-host (codice firmato + bonus crediti non-cashabili a scaglioni, anti-frode, durevole);
        # 111=cancellazione flessibile + rimborso automatico (scaglioni giorni->bps, fee pulizia sempre resa, puro cents);
        # 113=messaggistica host-guest in-app (thread per prenotazione, solo partecipanti, mascheramento PII, SQLite durevole);
        # 115=dashboard host metriche avanzate (revenue/occupazione/ADR/RevPAR/lead-time/cancellazione/rating, puro cents/bps);
        # 117=wishlist/preferiti guest (liste nominate per slug, idempotente, SQLite durevole);
        # 119=calendario prezzi visuale host (griglia giorno-per-giorno: stato + prezzo base + prezzo dinamico fase106, provider iniettato, HTML XSS-safe);
        # 121=mappa interattiva + geo-ricerca (microgradi interi, bbox+haversine+cluster+GeoJSON, puro);
        # 123=notifiche web push guest (subscription durevoli SQLite + invio VAPID gated, fetch/firma iniettabili);
        # 125=confronto OTA risparmio GUEST (prezzo finale ospite OTA markup+fee+DCC vs noi, puro cents/bps);
        # 127=check-in digitale guest (pre-registrazione ospiti+documenti validati, sblocco smart-pass fase64 solo se completato, SQLite durevole);
        # 129=traduzione recensioni multilingua (riusa fase107 pass-through+LibreTranslate gated + rileva-lingua euristica + conserva originale);
        # 131=host payout dashboard (tracciamento incassi/payout per valuta, stati maturato->in_transito->pagato/trattenuto, SQLite durevole);
        # 133=split-payment gruppo a quote uguali (largest-remainder conservazione esatta + pagamenti/completamento durevoli);
        # 135=iCal sync bidirezionale (export feed .ics DTEND-esclusivo RFC5545 + import fase82, roundtrip, puro);
        # 137=programma fedeltà guest (punti per soggiorno + livelli bronze/silver/gold/platinum moltiplicatore + riscatto sconto, idempotente, SQLite durevole);
        # 139=chatbot AI assistenza guest pre-prenotazione (router intento deterministico, prezzo SEMPRE dal concierge mai dall'IA, LLM opzionale solo fallback);
        # 141=host onboarding wizard guidato (macchina a stati passi+validazione+gate pubblicazione fail-closed, % completamento, SQLite durevole);
        # 143=verifica identità host KYC (handoff provider esterno, no PII sui ns server, stati con transizioni validate, gate payout, SQLite durevole);
        # 145=contratto locazione PDF precompilato (PDF 1.4 stdlib zero-dipendenze, xref corretti, IT/EN, cents interi, deterministico);
        # 147=tassa soggiorno comunale automatica (registro regole per-comune + calcolo + ledger riscossioni rendicontazione, comune-ignoto->0, SQLite durevole);
        # 149=deposito cauzionale pre-autorizzazione (hold no-addebito, cattura danno<=autorizzato + rilascio resto, conservazione esatta, PSP capture/release gated, SQLite durevole);
        # 151=export Alloggiati Web Questura (file larghezza-fissa 168char IT-gated, schedine ospiti, capo-con-documento, ASCII uppercase, deterministico).
        # 152=AVVISO PRENOTAZIONE ALL'HOST (notifica multi-canale email sempre + WhatsApp Cloud API gated, testo localizzato fase61, dispatcher isolato; +fase88 telefono/info_host, +fase57 host_di_alloggio).
        # 154=DB GIURISDIZIONI MARKETING mondiale (regime per nazione email/sms/whatsapp, opt-out lecito vs opt-in, fail-closed sconosciuto; cablato in outreach_runner).
        # 156=CANCELLAZIONE TOTALE host + verifica "da pertutto" (diritto oblio).
        # 158=DOMANDA/waitlist + CREDITO FONDATORE (cold-start anti-vuoto).
        # 160=ESCROW DI GARANZIA (i soldi all'host solo se l'ospite conferma o passa la finestra; endpoint garanzia/*).
        # 162=PAGAMENTI PENDENTI / hold prima del pagamento (book con Stripe -> in_attesa_pagamento + HOLD; webhook conferma->pagato + registra tassa nel ledger fase147; sweeper libera gli hold scaduti non pagati; senza Stripe resta confermata subito).
        # 164=POOL AI a rotazione con failover ("una funziona sempre": provider AI gratis usati a giro, cooldown+quota, stato durevole; libreria pura, adapter iniettati). Blocco pari 108..150 + 166+ libero.
        for n in (108, 110, 112, 114, 116, 118, 120, 122, 124, 126, 128, 130, 132, 134, 136, 138, 140, 142, 144, 146, 148, 150, 166):
            self.assertFalse(self._esiste(n), "fase%d gia' occupata: rinumerare" % n)


if __name__ == "__main__":
    unittest.main()
