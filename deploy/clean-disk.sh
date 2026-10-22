#!/usr/bin/env bash
# Libera espacio en el VPS sin tocar la base de datos, las posiciones ni la configuración. El bot sigue funcionando.
# Uso: bash clean-disk.sh          limpieza segura: caché de compilación no usada en 24 h, imágenes huérfanas, journald (200 MB), caché de apt
#      bash clean-disk.sh --all    además borra TODA la caché de compilación de Docker (la próxima actualización tardará algo más)
set -euo pipefail
cd "$(dirname "$0")"

echo "==> Antes:    $(df -h / | awk 'NR==2 {print $3" usados de "$2" ("$5")"}')"
docker system df 2>/dev/null || true
echo
echo "==> Datos del bot (no se tocan):"
printf '    Base de datos Mongo: %s\n' "$(docker compose exec -T mongo du -sh /data/db 2>/dev/null | cut -f1 || echo '?')"
printf '    Copias de seguridad: %s (%s archivos)\n' "$(du -sh backups 2>/dev/null | cut -f1 || echo 0)" "$(ls backups 2>/dev/null | wc -l)"
LOGS=$(du -shc /var/lib/docker/containers/*/*-json.log 2>/dev/null | tail -1 | cut -f1)
printf '    Logs de contenedores: %s\n' "${LOGS:-0}"
echo

echo "==> Limpiando caché de compilación de Docker"
if [ "${1:-}" = "--all" ]; then
  docker builder prune -af >/dev/null
else
  docker builder prune -af --filter "until=24h" >/dev/null 2>&1 || docker builder prune -af >/dev/null
fi
echo "==> Imágenes y contenedores huérfanos"
docker image prune -f >/dev/null
docker container prune -f >/dev/null
echo "==> Logs del sistema (journald ≤ 200 MB) y caché de apt"
mkdir -p /etc/systemd/journald.conf.d
[ -f /etc/systemd/journald.conf.d/ai-trader.conf ] || { printf '[Journal]\nSystemMaxUse=200M\n' > /etc/systemd/journald.conf.d/ai-trader.conf; systemctl restart systemd-journald 2>/dev/null || true; }
journalctl --vacuum-size=200M >/dev/null 2>&1 || true
apt-get clean 2>/dev/null || true

echo
echo "==> Después:  $(df -h / | awk 'NR==2 {print $3" usados de "$2" ("$5")"}')"
