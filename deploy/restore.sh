#!/usr/bin/env bash
# Restaura una copia .json.gz creada por el bot (backup.sh, cron nocturno o el panel). Sobrescribe la base de datos actual;
# la clave de acceso actual se conserva y ambos bots quedan detenidos.
# Uso: bash restore.sh backups/cryptobot-2026-06-01_030000.json.gz
set -euo pipefail
cd "$(dirname "$0")"
FILE="${1:?Indica el archivo .json.gz a restaurar}"
[ -f "$FILE" ] || { echo "No existe $FILE"; exit 1; }
DB=$(grep '^DB_NAME=' backend.env | cut -d= -f2- | tr -d "'\"")
SECRET=$(grep '^WEBHOOK_CRON_SECRET=' backend.env | cut -d= -f2- | tr -d "'\"")
read -rp "Se reemplazará la base de datos '${DB:-cryptobot}' con $FILE (ambos bots quedarán detenidos). ¿Continuar? (escribe SI): " OK
[ "$OK" = "SI" ] || { echo "Cancelado"; exit 1; }
curl -fsS -X POST http://127.0.0.1:8001/api/cron/restore -H "Authorization: Bearer $SECRET" -F "file=@$FILE"
echo
echo "Restaurado. Revisa posiciones y ajustes en el panel antes de iniciar los bots."
