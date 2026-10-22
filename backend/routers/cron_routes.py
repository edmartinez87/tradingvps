"""/api/cron/* webhooks (Bearer WEBHOOK_CRON_SECRET). They ack 2xx immediately and run the work in background."""
import os
import hmac
import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from pymongo.errors import DuplicateKeyError

import notify
import wfcheck
import weekly
from review import run_auto_review
from deps import engine, db, store, fx_engine, fx_store
from fx.wfcheck import KIT as FX_WF_KIT
from fx import review as fx_review
from fx import weekly as fx_weekly

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cron")
RUN_ID_TTL_DAYS = 30
CRYPTO = {"engine": engine, "db": db, "store": store, "review": run_auto_review, "weekly": weekly.send_weekly, "label": "", "prefix": ""}
FX = {"engine": fx_engine, "db": fx_engine.db, "store": fx_store, "review": fx_review.run_auto_review, "weekly": fx_weekly.send, "label": " HotForex", "prefix": fx_weekly.PREFIX}


async def init():
    """Processed run_ids live in db.cron_runs (survive restarts); Mongo expires them after RUN_ID_TTL_DAYS."""
    await db.cron_runs.create_index("at", expireAfterSeconds=RUN_ID_TTL_DAYS * 86400)


def _auth(request: Request):
    auth = request.headers.get("authorization", "")
    secret = os.environ.get("WEBHOOK_CRON_SECRET", "")
    if not (auth.lower().startswith("bearer ") and secret and hmac.compare_digest(auth[7:], secret)):
        raise HTTPException(401, "No autorizado")


async def _run_id(request: Request) -> str:
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Cuerpo inválido")
    if body is not None and not isinstance(body, dict):
        raise HTTPException(400, "Cuerpo inválido")
    return str(request.headers.get("x-webhook-id") or (body or {}).get("run_id") or "")[:200]


async def _accept(request: Request) -> bool:
    """Auth + idempotency. Returns True when this run_id was already processed (persisted in Mongo)."""
    _auth(request)
    run_id = await _run_id(request)
    if not run_id:
        return False
    try:
        await db.cron_runs.insert_one({"_id": run_id, "path": request.url.path, "at": datetime.now(timezone.utc)})
    except DuplicateKeyError:
        return True
    return False


async def _safe_auto_review(bot: dict):
    try:
        await bot["review"](bot["engine"], bot["db"], bot["store"])
    except Exception as e:
        logger.exception("scheduled auto review")
        await bot["engine"].log("ERROR", f"Revisión IA automática falló: {str(e)[:160]}")
        await notify.notify(f"{bot['prefix']}⚠️ <b>Revisión IA automática{bot['label']} falló</b>\n{str(e)[:300]}", "review")


async def _safe_weekly(bot: dict):
    eng, d = bot["engine"], bot["db"]
    try:
        last = await d.weekly.find_one({"_id": "latest"}, {"_id": 0, "sent_at": 1})
        if last and last.get("sent_at") and (datetime.now(timezone.utc) - datetime.fromisoformat(last["sent_at"])).days < 6:
            await eng.log("INFO", f"Resumen semanal omitido: ya se envió el {last['sent_at'][:10]}")
            return
        await bot["weekly"](eng, d)
    except Exception as e:
        logger.exception("weekly summary")
        await eng.log("ERROR", f"Resumen semanal falló: {str(e)[:160]}")


def _review_due(cfg) -> bool:
    now = datetime.now(timezone.utc)
    due = cfg.auto_review_enabled and (cfg.auto_review_frequency == "daily" or (now.weekday() + 1) % 7 == cfg.auto_review_day)
    if due and cfg.auto_review_last_at:
        due = (now - datetime.fromisoformat(cfg.auto_review_last_at)).total_seconds() > 20 * 3600
    return bool(due)


@router.post("/ai-review")
async def cron_ai_review(request: Request):
    """Daily 08:00 UTC trigger for both bots; each one decides if a review is due (frequency/day, > 20 h since the last)."""
    if await _accept(request):
        return {"accepted": True, "duplicate": True}
    due, due_fx = _review_due(store.cfg), _review_due(fx_store.cfg)
    if due:
        asyncio.create_task(_safe_auto_review(CRYPTO))
    if due_fx:
        asyncio.create_task(_safe_auto_review(FX))
    return {"accepted": True, "scheduled": due, "scheduled_fx": due_fx}


@router.post("/walk-forward")
async def cron_walk_forward(request: Request):
    """Weekly revalidation of applied SL/TP for both bots (crypto on Bybit/Bitget data, HotForex on Yahoo data)."""
    if await _accept(request):
        return {"accepted": True, "duplicate": True}
    started = await wfcheck.start_check(engine, db, store, "auto")
    started_fx = await wfcheck.start_check(fx_engine, fx_engine.db, fx_store, "auto", FX_WF_KIT)
    return {"accepted": True, "scheduled": started, "scheduled_fx": started_fx}


@router.post("/weekly-summary")
async def cron_weekly_summary(request: Request):
    """Sunday 20:00 UTC: weekly Telegram summary of both bots."""
    if await _accept(request):
        return {"accepted": True, "duplicate": True}
    asyncio.create_task(_safe_weekly(CRYPTO))
    asyncio.create_task(_safe_weekly(FX))
    return {"accepted": True, "scheduled": True, "scheduled_fx": True}



TELEGRAM_MAX_MB = 49


@router.post("/backup")
async def cron_backup(request: Request, file: UploadFile = File(...)):
    """deploy/backup.sh uploads the nightly mongodump archive here (weekly) so the backend can forward it to Telegram as a document."""
    _auth(request)
    data = await file.read()
    if not data:
        raise HTTPException(400, "Archivo vacío")
    size_mb = round(len(data) / 1048576, 2)
    name = (file.filename or "backup.archive.gz")[:120]
    rec = {"_id": "backup", "last_at": datetime.now(timezone.utc).isoformat(), "filename": name, "size_mb": size_mb, "sent": False, "error": None}
    if not notify.is_on("system"):
        rec["error"] = "Telegram desactivado o aviso 'system' apagado"
        await db.meta.update_one({"_id": "backup"}, {"$set": rec}, upsert=True)
        return {"sent": False, "size_mb": size_mb, "reason": rec["error"]}
    if size_mb > TELEGRAM_MAX_MB:
        rec["error"] = f"{size_mb} MB supera el límite de Telegram ({TELEGRAM_MAX_MB} MB)"
        await db.meta.update_one({"_id": "backup"}, {"$set": rec}, upsert=True)
        await notify.notify(f"🗄 <b>Copia de seguridad</b> {name} generada ({size_mb} MB) pero supera el límite de Telegram; queda guardada en el VPS (deploy/backups/).", "system")
        raise HTTPException(413, rec["error"])
    caption = (f"🗄 <b>Copia de seguridad semanal</b> · {name} · {size_mb} MB\n"
               "Restaurar en el VPS: <code>cd deploy && bash restore.sh &lt;archivo&gt;</code>")
    try:
        await notify.send_document(data, name, caption)
    except Exception as e:
        rec["error"] = str(e)[:200]
        await db.meta.update_one({"_id": "backup"}, {"$set": rec}, upsert=True)
        raise HTTPException(424, f"Telegram: {rec['error']}")
    rec["sent"] = True
    await db.meta.update_one({"_id": "backup"}, {"$set": rec}, upsert=True)
    for bot in (CRYPTO, FX):
        await bot["engine"].log("INFO", f"Copia de seguridad {name} ({size_mb} MB) enviada por Telegram")
    return {"sent": True, "size_mb": size_mb}
