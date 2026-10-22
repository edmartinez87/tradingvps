from models import now_iso
from profiles import profile_patch
from notify import notify as tg


async def _activo(engine, db):
    s = await engine.get_settings()
    if s.risk_profile != 3:
        return
    await engine.update_settings(profile_patch(2), "system", "Migración inicial: perfil Activo")
    await engine.log("INFO", "Perfil de riesgo bajado de Agresivo a Activo (ajuste acordado tras la actualización)")
    await tg("🎚 <b>Perfil de riesgo</b>: Agresivo → <b>Activo</b> (10 pares · 1h · criterios relajados · 1.5%/op · 5 posiciones · 5x), ajuste acordado tras la actualización.", "review")


async def _hfm_alert_180(engine, db):
    """Default HFM disconnection alert went 60 → 180 s (short demo-server restarts are normal); existing installs still store the old default."""
    await db.fx_config.update_one({"_id": "main", "hfm_alert_after_sec": 60}, {"$set": {"hfm_alert_after_sec": 180}})


MIGRATIONS = {"2026-10-20-activo": _activo, "2026-10-22-hfm-alert-180": _hfm_alert_180}


async def run(engine, db):
    done = {d["_id"] async for d in db.migrations.find({}, {"_id": 1})}
    for key, fn in MIGRATIONS.items():
        if key in done:
            continue
        await fn(engine, db)
        await db.migrations.insert_one({"_id": key, "at": now_iso()})
