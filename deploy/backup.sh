#!/usr/bin/env bash
# Copia de seguridad de la base de datos (ambos bots) creada por el propio backend en backups/ (formato .json.gz propio, conserva 14 días).
# Uso: bash backup.sh            → copia local (cron nocturno 03:00 UTC; los domingos el backend la envía también por Telegram)
#      bash backup.sh --telegram → además la envía por Telegram ahora
# Las copias también se pueden crear, descargar y restaurar desde el panel: Ajustes → Copias de seguridad.
set -euo pipefail
cd "$(dirname "$0")"
SECRET=$(grep '^WEBHOOK_CRON_SECRET=' backend.env | cut -d= -f2- | tr -d "'\"")
BODY='{}'
[ "${1:-}" = "--telegram" ] && BODY='{"telegram": true}'
OUT=$(curl -fsS -X POST http://127.0.0.1:8001/api/cron/backup -H "Authorization: Bearer $SECRET" -H "Content-Type: application/json" -d "$BODY")
echo "$(date -u +%FT%TZ) backup OK $OUT"
exit 0
