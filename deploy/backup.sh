#!/usr/bin/env bash
# Copia de seguridad de MongoDB (mongodump comprimido) en deploy/backups/, conservando 14 días.
# Uso: bash backup.sh            → copia local (cron nocturno 03:00 UTC)
#      bash backup.sh --telegram → además la envía por Telegram (el cron lo hace solo los domingos)
set -euo pipefail
cd "$(dirname "$0")"
DIR="${BACKUP_DIR:-$(pwd)/backups}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
DB=$(grep '^DB_NAME=' backend.env | cut -d= -f2- | tr -d "'\"")
STAMP=$(date -u +%F)
FILE="$DIR/${DB:-cryptobot}-$STAMP.archive.gz"
mkdir -p "$DIR"

docker compose exec -T mongo mongodump --quiet --archive --gzip --db "${DB:-cryptobot}" > "$FILE.tmp"
mv "$FILE.tmp" "$FILE"
find "$DIR" -name "${DB:-cryptobot}-*.archive.gz" -mtime +"$KEEP_DAYS" -delete
echo "$(date -u +%FT%TZ) backup OK $FILE ($(du -h "$FILE" | cut -f1))"

if [ "${1:-}" = "--telegram" ] || [ "$(date -u +%u)" = "7" ]; then
  SECRET=$(grep '^WEBHOOK_CRON_SECRET=' backend.env | cut -d= -f2- | tr -d "'\"")
  SEND="$FILE"
  if [ -n "${BACKUP_PASSWORD:-}" ]; then
    # Cifrado opcional antes de salir del VPS: descifrar con  openssl enc -d -aes-256-cbc -pbkdf2 -in archivo.enc -out archivo
    openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:BACKUP_PASSWORD -in "$FILE" -out "$FILE.enc"
    SEND="$FILE.enc"
  fi
  curl -fsS -X POST http://127.0.0.1:8001/api/cron/backup -H "Authorization: Bearer $SECRET" -F "file=@$SEND" && echo " · enviado por Telegram"
  [ "$SEND" != "$FILE" ] && rm -f "$SEND"
fi
exit 0
