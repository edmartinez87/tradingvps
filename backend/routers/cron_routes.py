"""/api/cron/* webhooks (Bearer WEBHOOK_CRON_SECRET). They ack 2xx immediately and run the work in background."""
import os
import hmac
import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

import notify
import wfcheck
import weekly
from review import run_auto_review
from deps import engine, db, store, fx_engine, fx_store
from fx.wfcheck import KIT as FX_WF_KIT

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cron")
_seen: list = []


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
    return request.headers.get("x-webhook-id") or (body or {}).get("run_id") or ""


async def _accept(request: Request) -> bool:
    """Auth + idempotency. Returns True when this run_id was already processed."""
    _auth(request)
    run_id = await _run_id(request)
    if run_id and run_id in _seen:
        return True
    if run_id:
        _seen.append(run_id)
        del _seen[:-200]
    return False


async def _safe_auto_review():
    try:
        await run_auto_review(engine, db, store)
    except Exception as e:
        logger.exception("scheduled auto review")
        await engine.log("ERROR", f"Revisión IA automática falló: {str(e)[:160]}")
        await notify.notify(f"⚠️ <b>Revisión IA automática falló</b>\n{str(e)[:300]}", "review")


async def _safe_weekly():
    try:
        last = await db.weekly.find_one({"_id": "latest"}, {"_id": 0, "sent_at": 1})
        if last and last.get("sent_at") and (datetime.now(timezone.utc) - datetime.fromisoformat(last["sent_at"])).days < 6:
            await engine.log("INFO", f"Resumen semanal omitido: ya se envió el {last['sent_at'][:10]}")
            return
        await weekly.send_weekly(engine, db)
    except Exception as e:
        logger.exception("weekly summary")
        await engine.log("ERROR", f"Resumen semanal falló: {str(e)[:160]}")


@router.post("/ai-review")
async def cron_ai_review(request: Request):
    if await _accept(request):
        return {"accepted": True, "duplicate": True}
    cfg = store.cfg
    now = datetime.now(timezone.utc)
    due = cfg.auto_review_enabled and (cfg.auto_review_frequency == "daily" or (now.weekday() + 1) % 7 == cfg.auto_review_day)
    if due and cfg.auto_review_last_at:
        due = (now - datetime.fromisoformat(cfg.auto_review_last_at)).total_seconds() > 20 * 3600
    if due:
        asyncio.create_task(_safe_auto_review())
    return {"accepted": True, "scheduled": bool(due)}


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
    if await _accept(request):
        return {"accepted": True, "duplicate": True}
    asyncio.create_task(_safe_weekly())
    return {"accepted": True, "scheduled": True}
