from models import now_iso
from profiles import profile_patch
from notify import notify as tg


async def _activo(engine):
    s = await engine.get_settings()
    if s.risk_profile != 3:
        return
    await engine.update_settings(profile_patch(2))
    await engine.log("INFO", "Perfil de riesgo bajado de Agresivo a Activo (ajuste acordado tras la actualización)")
    await tg("🎚 <b>Perfil de riesgo</b>: Agresivo → <b>Activo</b> (10 pares · 1h · criterios relajados · 1.5%/op · 5 posiciones · 5x), ajuste acordado tras la actualización.", "review")


MIGRATIONS = {"2026-10-20-activo": _activo}


async def run(engine, db):
    done = {d["_id"] async for d in db.migrations.find({}, {"_id": 1})}
    for key, fn in MIGRATIONS.items():
        if key in done:
            continue
        await fn(engine)
        await db.migrations.insert_one({"_id": key, "at": now_iso()})
