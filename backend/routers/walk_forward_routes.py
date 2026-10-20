"""Walk-forward validation: per-pair run and the weekly revalidation job of applied SL/TP."""
import asyncio

from fastapi import HTTPException

import wfcheck
from models import OptimizeRequest, AVAILABLE_SYMBOLS
from optimizer import walk_forward, WF_CANDLES
from deps import engine, db, store, protected_router

router = protected_router()


def _check_payload():
    return {"job": wfcheck.job_state(), "auto_remove": store.cfg.wf_auto_remove}


@router.post("/optimize/walk-forward")
async def optimize_walk_forward(req: OptimizeRequest):
    if req.symbol not in AVAILABLE_SYMBOLS:
        raise HTTPException(400, "Símbolo inválido")
    s = await engine.get_settings()
    acc = await db.account.find_one({"_id": "main"}, {"initial_balance": 1})
    klines = await engine.market.fetch_history(req.symbol, s.timeframe, WF_CANDLES)
    res = await asyncio.to_thread(walk_forward, klines, s.strategy, s.risk_per_trade, s.leverage, s.trailing_enabled, acc["initial_balance"],
                                  req.symbol, s.signal_mode, s.disabled_strategies, s.symbol_params.get(req.symbol))
    return {**res, "timeframe": s.timeframe, "applied_params": s.symbol_params.get(req.symbol)}


@router.get("/walk-forward/check")
async def walk_forward_check_status():
    return {**_check_payload(), "latest": await wfcheck.latest(db)}


@router.post("/walk-forward/check")
async def walk_forward_check_run():
    if not await wfcheck.start_check(engine, db, store, "manual"):
        raise HTTPException(409, "Ya hay una revalidación en curso")
    return {**_check_payload(), "latest": await wfcheck.latest(db)}
