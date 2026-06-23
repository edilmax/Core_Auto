# CORE_AUTO / Casa VIP - immagine di produzione.
# Casa VIP gira su PURA STDLIB Python (zero dipendenze): nessuna installazione di
# pacchetti, niente build-tools, immagine minuscola, non-root. Server stdlib (fase83).

FROM python:3.11-slim

# Niente .pyc, output non bufferato (log immediati). TUTTI i dati durevoli su /data
# (il volume): DB + stato scheduler + opt-out outreach. Senza questo, account host,
# crediti referral e disiscrizioni andrebbero persi a ogni redeploy.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORTA=8080 \
    DB_CATALOGO=/data/catalogo.db \
    DB_INVENTARIO=/data/inventario.db \
    DB_REGISTRO_HOST=/data/registro_host.db \
    DB_VIRAL=/data/viral.db \
    CAMPAGNA_STATO_FILE=/data/campagna_stato.json \
    OUTREACH_OPTOUT_FILE=/data/outreach_optout.json \
    STATIC_DIR=/app/deploy

WORKDIR /app

# Solo i file di runtime (i moduli fase*.py sono puro Python; i test NON entrano).
COPY main_casavip.py ./
COPY fase*.py ./
COPY deploy ./deploy

# Utente non-root + volume dati
RUN useradd -r -u 10001 -m -d /home/app app \
    && mkdir -p /data \
    && chown -R app:app /app /data
USER app

EXPOSE 8080
VOLUME ["/data"]

# Healthcheck senza curl (slim non ce l'ha): urllib stdlib
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/health',timeout=4).status==200 else 1)"

CMD ["python", "main_casavip.py"]
