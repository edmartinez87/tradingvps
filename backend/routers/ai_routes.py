"""AI routes for the crypto bot: manual auto-review, global optimization job and scoped advice (optimizer | plan)."""
import logging
from fastapi import HTTPException

from models import AdviseRequest
from ai_advisor import advise, label as ai_label, friendly_error
from review import build_context, apply_ai_changes, run_auto_review, start_global_optimization, job_state
from profiles import ai_policy
from deps import db, engine, store, protected_router

logger = logging.getLogger(__name__)
router = protected_router()


@router.post("/ai/auto-review")
async def ai_auto_review_now():
    try:
        return await run_auto_review(engine, db, store)
    except Exception as e:
        logger.exception("auto review")
        raise HTTPException(424, f"Error IA: {friendly_error(e)}")


@router.post("/ai/optimize-all")
async def ai_optimize_all():
    if not await start_global_optimization(engine, db):
        raise HTTPException(409, "Ya hay una optimización global en curso")
    return job_state()


@router.get("/ai/optimize-all")
async def ai_optimize_all_status():
    return job_state()


@router.post("/ai/advise")
async def ai_advise(req: AdviseRequest):
    if req.scope not in ("optimizer", "plan"):
        raise HTTPException(400, "Ámbito inválido")
    settings = await engine.get_settings()
    before = settings.model_dump(exclude={"bot_running"})
    acc = await engine.account_summary()
    ctx = await build_context(engine, db, settings, acc, req.scope == "plan")
    if req.scope == "optimizer":
        ctx["optimizador"] = [{k: r.get(k) for k in ("symbol", "best", "baseline", "timeframe")} for r in (req.optimizer_results or [])]
    await engine.log("AI_EVAL", f"{ai_label()} analizando {'optimizador' if req.scope == 'optimizer' else 'plan'} y rendimiento real...")
    try:
        res = await advise(req.scope, ctx, ai_policy(settings.risk_profile))
    except Exception as e:
        logger.exception("advise")
        raise HTTPException(424, f"Error IA: {friendly_error(e)}")
    applied, previous = await apply_ai_changes(engine, res, before, settings, source=req.scope)
    await engine.log("AI_EVAL", f"IA: {res['summary'][:160]}" + (f" · cambios: {', '.join(applied)}" if applied else " · sin cambios"))
    return {**res, "applied": applied, "previous": previous}
