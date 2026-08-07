#!/bin/sh
# «Dentro c'e' il commit giusto» NON si legge dal cartello: si DIMOSTRA, file per file.
#
# Si confronta l'impronta git di OGNI file tracciato dentro l'archivio con quella
# che lo stesso file ha in HEAD. Si fa QUI, sul server, perche' git e i file
# concordano sui fine-riga: farlo su Windows darebbe differenze finte su ogni
# file di testo (CRLF), e si passerebbe un'ora a inseguire un fantasma.
set -e
EST=/root/verifica_estratto
REPO=/var/www/bookinvip

rm -rf "$EST"; mkdir -p "$EST"
tar xzf /root/clone_progetto.tgz -C "$EST"

cd "$REPO"
COMMIT=$(git rev-parse --short HEAD)
git ls-tree -r HEAD --format='%(objectname) %(path)' | LC_ALL=C sort -k2 > /tmp/_attese.txt
TRACCIATI=$(wc -l < /tmp/_attese.txt)

cd "$EST"
UGUALI=0; DIVERSI=0; ASSENTI=0
: > /tmp/_diversi.txt
: > /tmp/_assenti.txt

while read -r atteso percorso; do
  if [ ! -f "$percorso" ]; then
    ASSENTI=$((ASSENTI+1)); echo "$percorso" >> /tmp/_assenti.txt; continue
  fi
  ottenuto=$(git hash-object --no-filters "$percorso")
  if [ "$ottenuto" = "$atteso" ]; then
    UGUALI=$((UGUALI+1))
  else
    DIVERSI=$((DIVERSI+1)); echo "$percorso" >> /tmp/_diversi.txt
  fi
done < /tmp/_attese.txt

echo "COMMIT DI RIFERIMENTO: $COMMIT"
echo "file tracciati in HEAD:      $TRACCIATI"
echo "  impronta IDENTICA:         $UGUALI"
echo "  impronta DIVERSA:          $DIVERSI"
echo "  non presenti nell archivio: $ASSENTI"
if [ "$DIVERSI" -gt 0 ]; then echo "--- DIVERSI (i primi 20): ---"; head -20 /tmp/_diversi.txt; fi
if [ "$ASSENTI" -gt 0 ]; then echo "--- ASSENTI (i primi 20, attesi solo quelli esclusi apposta): ---"; head -20 /tmp/_assenti.txt; fi

echo
echo "=== E I 25 DATABASE: si aprono davvero? ==="
rm -rf /root/verifica_dati; mkdir -p /root/verifica_dati
tar xzf /root/clone_dati.tgz -C /root/verifica_dati
OK=0; KO=0
for d in /root/verifica_dati/*.db; do
  e=$(python3 -c "import sqlite3,sys;c=sqlite3.connect(sys.argv[1]);print(c.execute('PRAGMA integrity_check').fetchone()[0]);c.close()" "$d" 2>/dev/null || echo ERRORE)
  if [ "$e" = "ok" ]; then OK=$((OK+1)); else KO=$((KO+1)); echo "  ROTTO: $(basename "$d") -> $e"; fi
done
echo "  database integri: $OK    rotti: $KO"

rm -rf "$EST" /root/verifica_dati /tmp/_attese.txt /tmp/_diversi.txt /tmp/_assenti.txt
[ "$DIVERSI" -eq 0 ] && [ "$KO" -eq 0 ]
