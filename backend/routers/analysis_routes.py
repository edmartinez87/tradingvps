"""Analysis routes for the crypto bot: growth plan + check-in, per-pair optimizer and backtest."""
from fastapi import HTTPException

from models import BacktestRequest, PlanRequest, OptimizeRequest, AVAILABLE_SYMBOLS, TIMEFRAMES, STRATEGY_KEYS
from indicators import build_df
from backtest import run_backtest
from plan import build_plan, SCENARIOS
from optimizer import optimize
from review import plan_stats
from deps import db, engine, protected_router

router = protected_router()


@router.post("/plan")
async def growth_plan(req: PlanRequest):
    settings = await engine.get_settings()
    if req.scenario not in SCENARIOS and req.scenario != "backtest":
        req.scenario = "base"
    if (settings.plan_scenario, settings.plan_target_monthly, settings.plan_monthly_deposit) != (req.scenario, req.target_monthly, req.monthly_deposit):
        await engine.update_settings({"plan_scenario": req.scenario, "plan_target_monthly": req.target_monthly,
                                      "plan_monthly_deposit": req.monthly_deposit})
    return build_plan(req.model_dump(), await plan_stats(engine, settings, req.initial_capital))


@router.get("/plan/checkin")
async def plan_checkin():
    return await engine.checkin()


@router.post("/optimize")
async def optimize_symbol(req: OptimizeRequest):
    if req.symbol not in AVAILABLE_SYMBOLS:
        raise HTTPException(400, "Símbolo inválido")
    s = await engine.get_settings()
    acc = await db.account.find_one({"_id": "main"}, {"initial_balance": 1})
    klines = await engine.market.fetch_klines(req.symbol, s.timeframe, 1000, cache_sec=300)
    res = optimize(klines, s.strategy, s.risk_per_trade, s.leverage, s.trailing_enabled, acc["initial_balance"], req.symbol, s.signal_mode, s.disabled_strategies)
    return {**res, "timeframe": s.timeframe, "applied": s.symbol_params.get(req.symbol)}


@router.post("/backtest")
async def backtest(req: BacktestRequest):
    if req.symbol not in AVAILABLE_SYMBOLS or req.timeframe not in TIMEFRAMES or req.strategy not in STRATEGY_KEYS:
        raise HTTPException(400, "Parámetros inválidos")
    df = build_df(await engine.market.fetch_klines(req.symbol, req.timeframe, 1000, cache_sec=60))
    acc = await db.account.find_one({"_id": "main"}, {"initial_balance": 1})
    s = await engine.get_settings()
    result = run_backtest(df, req.strategy, req.risk_per_trade, req.leverage, initial=acc["initial_balance"], symbol=req.symbol,
                          mode=s.signal_mode, disabled=s.disabled_strategies)
    result.pop("r_multiples", None)
    return {"symbol": req.symbol, "strategy": req.strategy, "timeframe": req.timeframe, **result}
