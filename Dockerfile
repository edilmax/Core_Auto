# CORE_AUTO - BLOCCO 5.0b: immagine applicazione (Variante C: multi-stage,
# slim, non-root, minima superficie d'attacco).
# syntax=docker/dockerfile:1

# ---- Stage 1: builder (isolato; le dipendenze si compilano/installano qui) ----
FROM python:3.11-slim AS builder
WORKDIR /app
COPY requirements.txt .
# psycopg2-binary e' un wheel precompilato -> niente gcc/build-essential.
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- Stage 2: runtime (slim, SENZA build tools, utente non privilegiato) ----
FROM python:3.11-slim
# Utente non-root dedicato (riduce l'impatto di un'eventuale compromissione).
RUN useradd -r -u 10001 appuser
WORKDIR /app
COPY --from=builder /install /usr/local
COPY --chown=appuser:appuser . /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FLASK_ENV=production \
    DB_PATH=/data/marketplace.db
# /data e' un volume persistente per il DB SQLite del core (vedi compose).
RUN mkdir -p /data && chown appuser:appuser /data
USER appuser
EXPOSE 8000
# Self-healing a livello container: healthcheck sull'endpoint pubblico /health.
HEALTHCHECK --interval=15s --timeout=5s --start-period=25s --retries=3 \
    CMD python -c "import sys,urllib.request; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status==200 else 1)"
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app:create_app()"]
