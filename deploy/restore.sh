#!/usr/bin/env bash
# Restaura una copia creada por backup.sh (sobrescribe la base de datos actual).
# Uso: bash restore.sh backups/cryptobot-2026-06-01.archive.gz   (o un .enc: pide la contraseña)
set -euo pipefail
cd "$(dirname "$0")"
FILE="${1:?Indica el archivo .archive.gz a restaurar}"
DB=$(grep '^DB_NAME=' backend.env | cut -d= -f2- | tr -d "'\"")
SRC="$FILE"
if [[ "$FILE" == *.enc ]]; then
  SRC="${FILE%.enc}"
  openssl enc -d -aes-256-cbc -pbkdf2 -in "$FILE" -out "$SRC"
fi
read -rp "Se reemplazará la base de datos '${DB:-cryptobot}' con $SRC. ¿Continuar? (escribe SI): " OK
[ "$OK" = "SI" ] || { echo "Cancelado"; exit 1; }
docker compose stop backend >/dev/null
docker compose exec -T mongo mongorestore --quiet --archive --gzip --drop --nsInclude "${DB:-cryptobot}.*" < "$SRC"
docker compose start backend >/dev/null
echo "Restaurado. El bot se ha reiniciado."
