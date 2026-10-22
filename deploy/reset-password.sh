#!/usr/bin/env bash
# Cambia la contraseña del panel si la has olvidado. Cierra todas las sesiones abiertas y reinicia el backend.
# Uso: bash reset-password.sh
set -euo pipefail
cd "$(dirname "$0")"
read -rsp "Nueva contraseña del panel (mínimo 8 caracteres): " PW; echo
[ "${#PW}" -ge 8 ] || { echo "Demasiado corta (mínimo 8 caracteres)"; exit 1; }
read -rsp "Repite la contraseña: " PW2; echo
[ "$PW" = "$PW2" ] || { echo "No coinciden"; exit 1; }
docker compose exec -T -e NEW_PW="$PW" backend python - <<'EOF'
import asyncio, os
from motor.motor_asyncio import AsyncIOMotorClient
from auth import hash_password

async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    r = await db.config.update_one({"_id": "main"}, {"$set": {"password_hash": hash_password(os.environ["NEW_PW"])}, "$inc": {"token_version": 1}})
    print("Contraseña actualizada" if r.matched_count else "Aún no hay configuración: arranca el backend una vez y repite")

asyncio.run(main())
EOF
docker compose restart backend >/dev/null
echo "Listo. Entra en el panel con la nueva contraseña."
