#!/usr/bin/env sh
# Casa VIP - genera un .env.casavip con segreti CRITTOGRAFICAMENTE SICURI.
# Uso:  sh deploy/genera_segreti.sh   (dalla radice del progetto)
# NON committare il file generato (.env.casavip e' gia' in .gitignore).
set -eu

OUT=".env.casavip"
if [ -f "$OUT" ]; then
  echo "ATTENZIONE: $OUT esiste gia'. Rinominalo o cancellalo prima di rigenerare." >&2
  exit 1
fi

# segreto sicuro: openssl se c'e', altrimenti Python stdlib (entrambi CSPRNG)
gen() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$1"
  else
    python3 -c "import secrets,sys; print(secrets.token_hex(int(sys.argv[1])))" "$1" 2>/dev/null \
      || python -c "import secrets,sys; print(secrets.token_hex(int(sys.argv[1])))" "$1"
  fi
}

SEGRETO="$(gen 32)"     # 64 hex = 256 bit per la firma HMAC
HOSTKEY="$(gen 24)"     # chiave pannello host

cat > "$OUT" <<EOF
# Generato da deploy/genera_segreti.sh - NON committare.
CASAVIP_SEGRETO=$SEGRETO
HOST_KEY=$HOSTKEY
VALUTA=EUR
SENTINEL=false
SENTINEL_DIR=/app
EOF

chmod 600 "$OUT"        # leggibile solo dal proprietario (no altri utenti del VPS)
echo "Creato $OUT (chmod 600). Segreti generati con CSPRNG."
