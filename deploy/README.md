# Despliegue en VPS (Docker)

```bash
sudo apt-get update && sudo apt-get install -y git
git clone <URL_DEL_REPO> cryptobot && cd cryptobot/deploy
sudo bash install.sh
```

El instalador: instala Docker, crea `backend.env` con secretos aleatorios, construye los
contenedores (Mongo + backend FastAPI + Caddy sirviendo el frontend y proxy `/api`),
programa los crons de revisión IA (08:00 UTC), walk-forward semanal (lunes 07:00 UTC), resumen semanal por Telegram (domingo 20:00 UTC)
y copia de seguridad nocturna de MongoDB (03:00 UTC, los domingos también por Telegram) y abre los puertos 80/443.

| Comando | Para qué |
|---|---|
| `docker compose ps` | estado de los servicios |
| `docker compose logs -f backend` | logs del bot |
| `docker compose restart backend` | reiniciar el bot |
| `./update.sh` | traer la última versión y reconstruir |
| `bash cron-ai-review.sh` | disparar la revisión IA manualmente (Bybit y HotForex) |
| `bash cron-walk-forward.sh` | revalidar ahora con walk-forward los pares con SL/TP optimizados (Bybit y HotForex) |
| `bash cron-weekly-summary.sh` | enviar ahora el resumen semanal por Telegram (Bybit y HotForex) |
| `bash backup.sh` | copia de seguridad ahora en `backups/` (añade `--telegram` para enviarla también por Telegram) |
| `bash restore.sh backups/<archivo>` | restaurar una copia (detiene el bot, reemplaza la base de datos y lo reinicia) |

Archivos sensibles (no se suben a git): `deploy/.env`, `deploy/backend.env`, `deploy/backups/`.
**Haz copia de `backend.env`**: `CREDENTIAL_ENCRYPTION_KEY` cifra las claves de Bybit guardadas;
si se pierde habrá que volver a introducirlas.

Copias de seguridad:
- Cada noche a las 03:00 UTC `backup.sh` guarda `backups/cryptobot-AAAA-MM-DD.archive.gz` (mongodump comprimido) y borra las de más de 14 días (`BACKUP_KEEP_DAYS`).
- Los domingos envía la copia del día por Telegram al chat configurado (aviso "Conexión/sistema"); el bot de Telegram admite hasta 50 MB.
- La copia contiene las claves API cifradas con `CREDENTIAL_ENCRYPTION_KEY` (sin esa clave no se pueden leer). Si quieres cifrar además el archivo antes de enviarlo,
  exporta `BACKUP_PASSWORD=...` en el cron (`BACKUP_PASSWORD=xxx /bin/bash backup.sh`); el archivo llegará como `.enc` y `restore.sh` pedirá la contraseña.
