# Despliegue en VPS (Docker)

```bash
sudo apt-get update && sudo apt-get install -y git
git clone <URL_DEL_REPO> cryptobot && cd cryptobot/deploy
sudo bash install.sh
```

El instalador: instala Docker, crea `backend.env` con secretos aleatorios, construye los
contenedores (Mongo + backend FastAPI + Caddy sirviendo el frontend y proxy `/api`),
programa los crons de revisión IA (08:00 UTC), walk-forward semanal (lunes 07:00 UTC) y resumen semanal por Telegram (domingo 20:00 UTC) y abre los puertos 80/443.

| Comando | Para qué |
|---|---|
| `docker compose ps` | estado de los servicios |
| `docker compose logs -f backend` | logs del bot |
| `docker compose restart backend` | reiniciar el bot |
| `./update.sh` | traer la última versión y reconstruir |
| `bash cron-ai-review.sh` | disparar la revisión IA manualmente (Bybit y HotForex) |
| `bash cron-walk-forward.sh` | revalidar ahora con walk-forward los pares con SL/TP optimizados (Bybit y HotForex) |
| `bash cron-weekly-summary.sh` | enviar ahora el resumen semanal por Telegram (Bybit y HotForex) |

Archivos sensibles (no se suben a git): `deploy/.env`, `deploy/backend.env`.
**Haz copia de `backend.env`**: `CREDENTIAL_ENCRYPTION_KEY` cifra las claves de Bybit guardadas;
si se pierde habrá que volver a introducirlas.

Backup de la base de datos:
```bash
docker compose exec mongo mongodump --archive --db cryptobot > backup-$(date +%F).archive
```
