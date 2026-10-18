import os
import time
import logging
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from fastapi import FastAPI, APIRouter, HTTPException  # noqa: E402
from starlette.middleware.cors import CORSMiddleware  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from bson import ObjectId  # noqa: E402
from models import (  # noqa: E402
    Position, Trade, Signal, LogEntry, SettingsUpdate, BacktestRequest, ResetRequest, PlanRequest,
    OptimizeRequest, AdviseRequest, AVAILABLE_SYMBOLS, TIMEFRAMES, STRATEGY_KEYS,
)
from engine import TradingEngine  # noqa: E402
from market import TF_SECONDS  # noqa: E402
from indicators import build_df  # noqa: E402
from strategies import STRATEGY_INFO  # noqa: E402
from backtest import run_backtest  # noqa: E402
from performance import performance  # noqa: E402
from plan import backtest_stats, build_plan, SCENARIOS  # noqa: E402
from optimizer import optimize  # noqa: E402
from ai_advisor import advise  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

client = AsyncIOMotorClient(os.environ["MONGO_URL"])
db = client[os.environ["DB_NAME"]]
engine = TradingEngine(db)

app = FastAPI(title="Bybit AI Trading Bot")
api = APIRouter(prefix="/api")


def _status() -> dict:
    return {
        "running": engine.running, "scanning": engine.scanning, "provider": engine.market.provider,
        "last_scan": engine.last_scan,
        "next_scan_in": max(0, int(engine.next_scan_ts - time.time())) if engine.next_scan_ts else None,
        "mode": "PAPER", "market": "USDT Perpetual",
    }


async def _equity_curve(limit: int = 1440) -> list:
    rows = await db.equity.find({}, {"_id": 0}).sort("ts", -1).limit(limit).to_list(limit)
    rows.reverse()
    step = max(1, len(rows) // 300)
    return rows[::step] + (rows[-1:] if rows and (len(rows) - 1) % step else [])


@api.get("/")
async def root():
    return {"message": "Bybit AI Trading Bot API", **_status()}


@api.get("/meta")
async def meta():
    return {"symbols": AVAILABLE_SYMBOLS, "timeframes": TIMEFRAMES, "strategies": STRATEGY_KEYS, "strategy_info": STRATEGY_INFO}


@api.get("/dashboard")
async def dashboard():
    settings = await engine.get_settings()
    positions = [Position.from_mongo(d).model_dump() async for d in db.positions.find().sort("_id", -1)]
    trades = [Trade.from_mongo(d).model_dump() async for d in db.trades.find().sort("_id", -1).limit(50)]
    signals = [Signal.from_mongo(d).model_dump() async for d in db.signals.find().sort("_id", -1).limit(30)]
    logs = [LogEntry.from_mongo(d).model_dump() async for d in db.logs.find().sort("_id", -1).limit(100)]
    watchlist = []
    for sym in settings.symbols:
        t = engine.market.tickers.get(sym, {})
        watchlist.append({"symbol": sym, "price": t.get("price"), "change_pct": t.get("change_pct"),
                          "volume_usdt": t.get("volume_usdt"), "funding_rate": t.get("funding_rate"),
                          **engine.analysis.get(sym, {})})
    return {
        "status": _status(), "settings": settings.model_dump(), "account": await engine.account_summary(),
        "positions": positions, "trades": trades, "signals": signals, "logs": logs,
        "watchlist": watchlist, "equity": await _equity_curve(), "checkin": await engine.checkin(settings),
    }


@api.get("/klines")
async def klines(symbol: str, tf: str = "15m", limit: int = 300):
    if symbol not in AVAILABLE_SYMBOLS or tf not in TIMEFRAMES:
        raise HTTPException(400, "Símbolo o temporalidad inválida")
    df = build_df(await engine.market.fetch_klines(symbol, tf, min(max(limit, 100), 1000)))
    times = (df["ts"] // 1000).astype(int).tolist()

    def line(col, start=0):
        return [{"time": t, "value": round(float(v), 8)} for t, v in zip(times[start:], df[col].tolist()[start:])]

    candles = [{"time": t, "open": o, "high": h, "low": lo, "close": c}
               for t, o, h, lo, c in zip(times, df["open"], df["high"], df["low"], df["close"])]
    volume = [{"time": t, "value": v, "color": "rgba(16,185,129,0.35)" if c >= o else "rgba(239,68,68,0.35)"}
              for t, v, o, c in zip(times, df["volume"], df["open"], df["close"])]
    step, first = TF_SECONDS[tf], times[0]

    def snap(iso):
        from datetime import datetime
        ts = int(datetime.fromisoformat(iso).timestamp())
        return ts - ts % step

    markers = []
    async for d in db.trades.find({"symbol": symbol}).sort("_id", -1).limit(100):
        t = Trade.from_mongo(d)
        long = t.side == "long"
        if snap(t.opened_at) >= first:
            markers.append({"time": snap(t.opened_at), "position": "belowBar" if long else "aboveBar",
                            "color": "#10B981" if long else "#EF4444", "shape": "arrowUp" if long else "arrowDown",
                            "text": "LONG" if long else "SHORT"})
        if snap(t.closed_at) >= first:
            markers.append({"time": snap(t.closed_at), "position": "aboveBar" if long else "belowBar",
                            "color": "#F7A600", "shape": "circle", "text": f"{t.reason} {t.pnl:+.1f}"})
    lines = []
    async for d in db.positions.find({"symbol": symbol}):
        p = Position.from_mongo(d)
        long = p.side == "long"
        if snap(p.opened_at) >= first:
            markers.append({"time": snap(p.opened_at), "position": "belowBar" if long else "aboveBar",
                            "color": "#10B981" if long else "#EF4444", "shape": "arrowUp" if long else "arrowDown",
                            "text": "LONG" if long else "SHORT"})
        lines = [{"price": p.entry_price, "title": "ENTRADA", "color": "#F8FAFC"},
                 {"price": p.sl, "title": "SL", "color": "#EF4444"},
                 {"price": p.tp, "title": "TP", "color": "#10B981"}]
    markers.sort(key=lambda m: m["time"])
    return {"symbol": symbol, "tf": tf, "candles": candles, "volume": volume, "ema9": line("ema9"),
            "ema21": line("ema21"), "ema200": line("ema200", 50), "rsi": line("rsi", 14),
            "markers": markers, "lines": lines}


@api.post("/bot/start")
async def bot_start():
    await engine.start()
    return _status()


@api.post("/bot/stop")
async def bot_stop():
    await engine.stop()
    return _status()


@api.post("/bot/scan")
async def bot_scan():
    engine.scan_event.set()
    return {"ok": True, "message": "Escaneo solicitado"}


@api.get("/settings")
async def get_settings():
    return (await engine.get_settings()).model_dump()


@api.put("/settings")
async def put_settings(body: SettingsUpdate):
    try:
        s = await engine.update_settings(body.model_dump())
    except ValueError as e:
        raise HTTPException(422, str(e))
    return s.model_dump()


@api.get("/positions")
async def list_positions():
    return [Position.from_mongo(d).model_dump() async for d in db.positions.find().sort("_id", -1)]


@api.post("/positions/{pos_id}/close")
async def close_pos(pos_id: str):
    if not ObjectId.is_valid(pos_id):
        raise HTTPException(400, "ID inválido")
    trade = await engine.close_position(pos_id, reason="MANUAL")
    if not trade:
        raise HTTPException(404, "Posición no encontrada")
    return trade.model_dump()


@api.get("/trades")
async def list_trades(limit: int = 100):
    return [Trade.from_mongo(d).model_dump() async for d in db.trades.find().sort("_id", -1).limit(min(limit, 500))]


@api.get("/signals")
async def list_signals(limit: int = 50):
    return [Signal.from_mongo(d).model_dump() async for d in db.signals.find().sort("_id", -1).limit(min(limit, 200))]


@api.get("/account")
async def account():
    return await engine.account_summary()


@api.post("/account/reset")
async def reset_account(body: ResetRequest = None):
    await engine.reset_account(body.initial_balance if body else None)
    return await engine.account_summary()


@api.get("/performance")
async def get_performance():
    return await performance(db)


_plan_cache = {}


async def _plan_stats(settings, initial: float) -> dict:
    key = (tuple(settings.symbols), settings.timeframe, settings.strategy, settings.risk_per_trade,
           settings.leverage, settings.trailing_enabled, settings.max_positions, initial)
    hit = _plan_cache.get(key)
    if not hit or time.time() - hit["ts"] > 300:
        hit = {"ts": time.time(), "data": await backtest_stats(engine.market.fetch_klines, settings, initial)}
        _plan_cache.clear()
        _plan_cache[key] = hit
    return hit["data"]


@api.post("/plan")
async def growth_plan(req: PlanRequest):
    settings = await engine.get_settings()
    if req.scenario not in SCENARIOS and req.scenario != "backtest":
        req.scenario = "base"
    if (settings.plan_scenario, settings.plan_target_monthly, settings.plan_monthly_deposit) != (req.scenario, req.target_monthly, req.monthly_deposit):
        await engine.update_settings({"plan_scenario": req.scenario, "plan_target_monthly": req.target_monthly,
                                      "plan_monthly_deposit": req.monthly_deposit})
    return build_plan(req.model_dump(), await _plan_stats(settings, req.initial_capital))


@api.get("/plan/checkin")
async def plan_checkin():
    return await engine.checkin()


@api.post("/optimize")
async def optimize_symbol(req: OptimizeRequest):
    if req.symbol not in AVAILABLE_SYMBOLS:
        raise HTTPException(400, "Símbolo inválido")
    s = await engine.get_settings()
    acc = await db.account.find_one({"_id": "main"}, {"initial_balance": 1})
    klines = await engine.market.fetch_klines(req.symbol, s.timeframe, 1000, cache_sec=300)
    res = optimize(klines, s.strategy, s.risk_per_trade, s.leverage, s.trailing_enabled, acc["initial_balance"], req.symbol)
    return {**res, "timeframe": s.timeframe, "applied": s.symbol_params.get(req.symbol)}


ALLOWED_AI_KEYS = {"symbols", "strategy", "risk_per_trade", "max_positions", "leverage", "ai_min_confidence",
                   "trailing_enabled", "htf_filter", "symbol_params"}
AI_CAPS = {"risk_per_trade": 1.5, "leverage": 5, "max_positions": 5}


@api.post("/ai/advise")
async def ai_advise(req: AdviseRequest):
    if req.scope not in ("optimizer", "plan"):
        raise HTTPException(400, "Ámbito inválido")
    settings = await engine.get_settings()
    before = settings.model_dump(exclude={"bot_running"})
    acc = await engine.account_summary()
    ctx = {"settings_actuales": before, "cuenta": acc, "rendimiento_real": await performance(db),
           "chequeo_plan": await engine.checkin(settings, acc)}
    if req.scope == "optimizer":
        ctx["optimizador"] = [{k: r.get(k) for k in ("symbol", "best", "baseline", "timeframe")} for r in (req.optimizer_results or [])]
    else:
        bt = await _plan_stats(settings, acc["initial_balance"])
        ctx["backtest"] = {k: bt[k] for k in ("per_symbol", "by_strategy", "monte_carlo", "trades_per_month", "days")}
    await engine.log("AI_EVAL", f"Claude analizando {'optimizador' if req.scope == 'optimizer' else 'plan'} y rendimiento real...")
    try:
        res = await advise(req.scope, ctx)
    except Exception as e:
        logger.exception("advise")
        raise HTTPException(502, f"Error IA: {str(e)[:160]}")
    patch = {k: v for k, v in res["changes"].items() if k in ALLOWED_AI_KEYS}
    for k, cap in AI_CAPS.items():
        if k in patch:
            patch[k] = min(float(patch[k]), cap)
    if "symbols" in patch and (not isinstance(patch["symbols"], list) or len([x for x in patch["symbols"] if x in AVAILABLE_SYMBOLS]) < 2):
        patch.pop("symbols")
    applied = {}
    if patch:
        try:
            after = (await engine.update_settings(SettingsUpdate.model_validate(patch).model_dump())).model_dump(exclude={"bot_running"})
            applied = {k: {"antes": before[k], "despues": after[k]} for k in patch if before.get(k) != after.get(k)}
        except Exception as e:
            res["notes"].append(f"Cambios propuestos no válidos y descartados: {str(e)[:120]}")
    await engine.log("AI_EVAL", f"IA: {res['summary'][:160]}" + (f" · cambios: {', '.join(applied)}" if applied else " · sin cambios"))
    return {**res, "applied": applied, "previous": {k: before[k] for k in applied}}


@api.delete("/logs")
async def clear_logs():
    await db.logs.delete_many({})
    return {"ok": True}


@api.post("/backtest")
async def backtest(req: BacktestRequest):
    if req.symbol not in AVAILABLE_SYMBOLS or req.timeframe not in TIMEFRAMES or req.strategy not in STRATEGY_KEYS:
        raise HTTPException(400, "Parámetros inválidos")
    df = build_df(await engine.market.fetch_klines(req.symbol, req.timeframe, 1000, cache_sec=60))
    acc = await db.account.find_one({"_id": "main"}, {"initial_balance": 1})
    result = run_backtest(df, req.strategy, req.risk_per_trade, req.leverage, initial=acc["initial_balance"], symbol=req.symbol)
    result.pop("r_multiples", None)
    return {"symbol": req.symbol, "strategy": req.strategy, "timeframe": req.timeframe, **result}


app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    await engine.init()


@app.on_event("shutdown")
async def shutdown():
    await engine.shutdown()
    client.close()
