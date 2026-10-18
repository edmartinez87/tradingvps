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
    Position, Trade, Signal, LogEntry, SettingsUpdate, BacktestRequest,
    AVAILABLE_SYMBOLS, TIMEFRAMES, STRATEGY_KEYS,
)
from engine import TradingEngine  # noqa: E402
from market import TF_SECONDS  # noqa: E402
from indicators import build_df  # noqa: E402
from strategies import STRATEGY_INFO  # noqa: E402
from backtest import run_backtest  # noqa: E402

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
        "watchlist": watchlist, "equity": await _equity_curve(),
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
async def reset_account():
    await engine.reset_account()
    return await engine.account_summary()


@api.delete("/logs")
async def clear_logs():
    await db.logs.delete_many({})
    return {"ok": True}


@api.post("/backtest")
async def backtest(req: BacktestRequest):
    if req.symbol not in AVAILABLE_SYMBOLS or req.timeframe not in TIMEFRAMES or req.strategy not in STRATEGY_KEYS:
        raise HTTPException(400, "Parámetros inválidos")
    df = build_df(await engine.market.fetch_klines(req.symbol, req.timeframe, 1000, cache_sec=60))
    result = run_backtest(df, req.strategy, req.risk_per_trade, req.leverage)
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
