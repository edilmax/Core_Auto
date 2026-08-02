#!/bin/sh
# Accende i ganci versionati di questo progetto. Da eseguire UNA VOLTA per computer:
#     sh deploy/installa_hook.sh
#
# I ganci di git vivono in `.git/hooks`, che NON viaggia col repository: chi clona il
# progetto non li ha. Per questo stanno in `deploy/hooks` (versionati) e qui si dice a git
# di guardare li'.
set -e
cd "$(dirname "$0")/.."
chmod +x deploy/hooks/* 2>/dev/null || true
git config core.hooksPath deploy/hooks
echo "ganci accesi: $(git config core.hooksPath)"
echo "attivi:"
ls deploy/hooks
echo ""
echo "prova subito che funzioni:  python collaudi/guardia_commit.py ; echo \$?"
echo "  0 = si puo' salvare · 1 = un giro di mutazione e' rimasto aperto"
