#!/bin/sh
# Controlla COSA C'E' DENTRO i due pacchetti della chiavetta, aprendoli.
# Sta in un file apposta: passare questi motivi di ricerca dentro una riga
# ssh dentro PowerShell si mangia le barre rovesciate e stampa zeri finti.
cd /var/www/bookinvip || exit 1
P=/root/clone_progetto.tgz
D=/root/clone_dati.tgz

tar tzf "$P" > /tmp/_elenco_p.txt
tar tzf "$D" > /tmp/_elenco_d.txt

echo "COMMIT DEL SERVER: $(git rev-parse --short HEAD)"
echo
echo "=== PACCHETTO CODICE ==="
echo "  byte:             $(stat -c%s "$P")"
echo "  voci:             $(wc -l < /tmp/_elenco_p.txt)"
echo "  moduli fase*.py:  $(grep -c '^\./fase[0-9]' /tmp/_elenco_p.txt)"
echo "  file di test:     $(grep -c '^\./test_' /tmp/_elenco_p.txt)"
echo "  file in deploy/:  $(grep -c '^\./deploy/' /tmp/_elenco_p.txt)"
echo "  file in collaudi/: $(grep -c '^\./collaudi/' /tmp/_elenco_p.txt)"
echo
echo "  DEVE ESSERCI (1 = ok):"
for f in './.env.casavip' './docker-compose.casavip.yml' './Dockerfile.casavip' './main_casavip.py' './requirements.txt' './RIPRENDI_QUI.md' './CLAUDE.md'; do
  printf "    %-32s %s\n" "$f" "$(grep -cxF "$f" /tmp/_elenco_p.txt)"
done
echo
echo "  NON DEVE ESSERCI (0 = ok):"
printf "    %-32s %s\n" "copie .bak delle chiavi" "$(grep -c 'env\.casavip\.bak' /tmp/_elenco_p.txt)"
printf "    %-32s %s\n" ".git/" "$(grep -c '^\./\.git/' /tmp/_elenco_p.txt)"
printf "    %-32s %s\n" "venv/" "$(grep -c '^\./venv/' /tmp/_elenco_p.txt)"
printf "    %-32s %s\n" "video_pubblici/" "$(grep -c '^\./video_pubblici/' /tmp/_elenco_p.txt)"
printf "    %-32s %s\n" "__pycache__" "$(grep -c '__pycache__' /tmp/_elenco_p.txt)"
printf "    %-32s %s\n" "PRE_DEPLOY_*" "$(grep -c 'PRE_DEPLOY_' /tmp/_elenco_p.txt)"
echo
echo "=== PACCHETTO DATI ==="
echo "  byte:      $(stat -c%s "$D")"
echo "  database:  $(grep -c '\.db$' /tmp/_elenco_d.txt)"
echo "  elenco:"
sed 's/^/    /' /tmp/_elenco_d.txt | head -30
echo
echo "=== IMPRONTE ==="
sha256sum "$P" "$D"
rm -f /tmp/_elenco_p.txt /tmp/_elenco_d.txt
