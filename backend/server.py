import os
import time
import asyncio
import logging
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

from fastapi import FastAPI, APIRouter, HTTPException, Request  # noqa: E402
from starlette.middleware.cors import CORSMiddleware  # noqa: E402
from bson import ObjectId  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
from models import (  # noqa: E402
    Position, Trade, Signal, LogEntry, SettingsUpdate, ResetRequest, ProfileRequest, AVAILABLE_SYMBOLS, TIMEFRAMES, STRATEGY_KEYS, SIGNAL_MODES,
)
from market import TF_SECONDS  # noqa: E402
from indicators import build_df  # noqa: E402
from strategies import STRATEGY_INFO, MODE_INFO  # noqa: E402
from performance import performance  # noqa: E402
from ai_advisor import current as ai_current  # noqa: E402
from auth import verify_password, create_token, client_ip, check_locked, register_failure, clear_failures  # noqa: E402
from config import ConfigUpdate  # noqa: E402
import notify  # noqa: E402
from review import job_state  # noqa: E402
from profiles import PROFILES, detect_profile, profile_patch  # noqa: E402
import migrations  # noqa: E402
import funding  # noqa: E402
from deps import client, db, engine, store, news, protected_router, fx_engine, fx_store, fx_news  # noqa: E402
from routers import cron_routes, weekly_routes, walk_forward_routes, bybit_routes, ai_routes, analysis_routes  # noqa: E402
from routers.shared_routes import add_shared_routes  # noqa: E402
from fx import routes as fx_routes  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

app = FastAPI(title="Bybit AI Trading Bot")
public = APIRouter(prefix="/api")
api = protected_router()
add_shared_routes(api, engine, "Bybit AI Trader")


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=200)


def _status() -> dict:
    return {
        "running": engine.running, "scanning": engine.scanning, "provider": engine.market.provider,
        "last_scan": engine.last_scan,
        "next_scan_in": max(0, int(engine.next_scan_ts - time.time())) if engine.next_scan_ts else None,
        "mode": engine.mode_label, "env": engine.env, "market": "USDT Perpetual", "telegram": notify.is_on(), "ai": ai_current(),
        "exchange_error": engine.exchange_error,
    }


async def _equity_curve(limit: int = 1440) -> list:
    rows = await db.equity.find({}, {"_id": 0}).sort("ts", -1).limit(limit).to_list(limit)
    rows.reverse()
    step = max(1, len(rows) // 300)
    return rows[::step] + (rows[-1:] if rows and (len(rows) - 1) % step else [])


@public.get("/")
async def root():
    return {"message": "Bybit AI Trading Bot API", "running": engine.running, "mode": "PAPER"}


@public.post("/auth/login")
async def login(body: LoginRequest, request: Request):
    ip = client_ip(request)
    check_locked(ip)
    if not verify_password(body.password, store.cfg.password_hash):
        left = register_failure(ip)
        await engine.log("RISK", f"Intento de acceso fallido desde {ip}")
        raise HTTPException(401, f"Clave incorrecta. {'Cuenta bloqueada 15 minutos.' if left == 0 else f'Intentos restantes: {left}.'}")
    clear_failures(ip)
    await engine.log("INFO", f"Acceso al panel desde {ip}")
    return {"token": create_token(store.cfg.token_version)}


@api.get("/config")
async def get_config():
    return store.public()


@api.put("/config")
async def put_config(body: ConfigUpdate):
    try:
        patch = store.patch_from(body)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if patch:
        await store.update(patch)
        await engine.log("INFO", f"Ajustes actualizados: {', '.join(patch)}")
    return store.public()


@api.get("/meta")
async def meta():
    return {"symbols": AVAILABLE_SYMBOLS, "timeframes": TIMEFRAMES, "strategies": STRATEGY_KEYS, "strategy_info": STRATEGY_INFO,
            "signal_modes": SIGNAL_MODES, "mode_info": MODE_INFO, "profiles": PROFILES}


@api.get("/overview")
async def overview():
    acc = await engine.account_summary()
    return {"running": engine.running, "mode": engine.mode_label, "equity": acc["equity"], "total_return_pct": acc["total_return_pct"], "open_positions": acc["open_positions"]}


@api.post("/profile")
async def set_profile(req: ProfileRequest):
    settings = await engine.get_settings()
    if engine.live and req.level >= 3 and engine.running:
        raise HTTPException(409, "Detén el bot antes de pasar a un perfil agresivo en modo REAL")
    p = PROFILES[req.level]
    before = PROFILES[settings.risk_profile]["name"] if detect_profile(settings) is not None else "Personalizado"
    s = await engine.update_settings(profile_patch(req.level))
    st = p["settings"]
    await engine.log("INFO", f"Perfil de riesgo: {before} → {p['name']} · {len(st['symbols'])} pares · {st['timeframe']} · riesgo {st['risk_per_trade']}% · {st['leverage']}x")
    await notify.notify(
        f"🎚 <b>Perfil de riesgo cambiado</b>: {before} → <b>{p['name']}</b>\n"
        f"• {len(st['symbols'])} pares · velas {st['timeframe']} · criterios {MODE_INFO[st['signal_mode']]['name'].lower()}\n"
        f"• Riesgo {st['risk_per_trade']}%/op · máx {st['max_positions']} posiciones · {st['leverage']}x · límite diario {st['daily_loss_limit']}%\n"
        f"• Filtro 4h: {'sí' if st['htf_filter'] else 'no'} · IA: {'sí (≥' + str(st['ai_min_confidence']) + '%)' if st['ai_enabled'] else 'NO'}"
        + (f"\n⚠️ {p['warning']}" if p["warning"] else ""), "review")
    return {"settings": s.model_dump(), "profile_active": detect_profile(s)}


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
                          "funding_interval_h": t.get("funding_interval_h", 8),
                          "funding_level": funding.level(t.get("funding_rate"), store.cfg, t.get("funding_interval_h", 8)),
                          **engine.analysis.get(sym, {})})
    return {
        "status": _status(), "settings": settings.model_dump(), "account": await engine.account_summary(),
        "positions": positions, "trades": trades, "signals": signals, "logs": logs,
        "watchlist": watchlist, "equity": await _equity_curve(), "checkin": await engine.checkin(settings),
        "profile_active": detect_profile(settings), "optimize_job": job_state()["status"], "news": news.summary(),
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
    if engine.live and (not engine.broker or not store.cfg.bybit_verified_at):
        raise HTTPException(409, "Modo REAL sin credenciales de Bybit verificadas: pruébalas en Ajustes o vuelve a modo paper")
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
        raise HTTPException(424 if engine.live else 404, "No se pudo cerrar la posición en Bybit (revisa el registro)" if engine.live else "Posición no encontrada")
    return trade.model_dump()


@api.post("/positions/close-all")
async def close_all():
    ids = [str(d["_id"]) async for d in db.positions.find({}, {"_id": 1})]
    closed, failed = [], []
    for pid in ids:
        trade = await engine.close_position(pid, reason="MANUAL")
        (closed if trade else failed).append(pid)
    await engine.log("RISK", f"Cierre de emergencia · {len(closed)} posiciones cerradas" + (f" · {len(failed)} fallidas" if failed else ""))
    return {"closed": len(closed), "failed": len(failed)}


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
    if await db.positions.count_documents({"live": True}):
        raise HTTPException(409, "Hay posiciones reales abiertas: ciérralas antes de reiniciar las estadísticas")
    await engine.reset_account(body.initial_balance if body else None)
    return await engine.account_summary()


@api.get("/performance")
async def get_performance():
    return await performance(db)


@api.get("/news")
async def get_news():
    return {"latest": news.latest, "summary": news.summary()}


@api.post("/news/refresh")
async def refresh_news():
    try:
        await news.refresh()
    except Exception as e:
        logger.exception("news refresh")
        raise HTTPException(424, f"No se pudo actualizar las noticias: {str(e)[:160]}")
    return {"latest": news.latest, "summary": news.summary()}


@api.delete("/logs")
async def clear_logs():
    await db.logs.delete_many({})
    return {"ok": True}


app.include_router(public)
app.include_router(api)
app.include_router(bybit_routes.router)
app.include_router(ai_routes.router)
app.include_router(analysis_routes.router)
app.include_router(cron_routes.router)
app.include_router(weekly_routes.router)
app.include_router(walk_forward_routes.router)
app.include_router(fx_routes.router)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    store.listeners.append(engine.apply_config)
    store.listeners.append(news.configure)
    await store.load()
    await engine.init()
    await news.init()
    await migrations.run(engine, db)
    await cron_routes.init()
    fx_store.listeners.append(fx_engine.apply_config)
    fx_store.listeners.append(fx_news.configure)
    await fx_store.load()
    await fx_engine.init()
    await fx_news.init()


@app.on_event("shutdown")
async def shutdown():
    await fx_news.aclose()
    await fx_engine.shutdown()
    await news.aclose()
    await engine.shutdown()
    client.close()
