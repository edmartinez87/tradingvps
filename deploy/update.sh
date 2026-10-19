#!/usr/bin/env bash
# Actualiza el bot con la última versión del repositorio y reinicia los contenedores.
set -euo pipefail
cd "$(dirname "$0")"
git pull --ff-only
docker compose up -d --build
docker image prune -f >/dev/null
echo "Actualizado. Logs: docker compose logs -f backend"
