#!/usr/bin/env pwsh
# CORE_AUTO - BLOCCO 5: gestione isola Postgres di sviluppo (un solo comando).
#
# Uso:   ./pg.ps1 up | down | wipe | status | url | test
#   up     -> avvia Postgres (detached)
#   down   -> ferma (i dati restano nel volume core_auto_pgdata)
#   wipe   -> ferma e CANCELLA i dati (down -v)
#   status -> stato del container
#   url    -> stampa la DATABASE_URL da usare nell'app
#   test   -> esegue la validazione LIVE del dialetto contro il Postgres acceso
#
# Equivalente bash:  docker compose -f docker-compose.postgres.yml up -d
param(
    [Parameter(Position = 0)]
    [ValidateSet("up", "down", "wipe", "status", "url", "test")]
    [string]$Comando = "status"
)

$Compose = @("compose", "-f", "docker-compose.postgres.yml")
$Url = "postgresql://core:core@localhost:5432/core_auto"

switch ($Comando) {
    "up"     { docker @Compose up -d; "Postgres avviato. DATABASE_URL=$Url" }
    "down"   { docker @Compose down }
    "wipe"   { docker @Compose down -v }
    "status" { docker @Compose ps }
    "url"    { $Url }
    "test"   {
        $env:DB_BACKEND = "postgres"
        $env:DATABASE_URL = $Url
        python -m unittest test_postgres_live
    }
}
