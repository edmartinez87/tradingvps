import os
import time
import hmac
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request  # noqa: E402
from starlette.middleware.cors import CORSMiddleware  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from bson import ObjectId  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
from models import (  # noqa: E402
    Position, Trade, Signal, LogEntry, SettingsUpdate, BacktestRequest, ResetRequest, PlanRequest,
    OptimizeRequest, AdviseRequest, BybitTestRequest, ModeRequest, ProfileRequest, AVAILABLE_SYMBOLS, TIMEFRAMES, STRATEGY_KEYS, SIGNAL_MODES, now_iso,
)
from engine import TradingEngine  # noqa: E402
from market import TF_SECONDS  # noqa: E402
from indicators import build_df  # noqa: E402
from strategies import STRATEGY_INFO  # noqa: E402
from backtest import run_backtest  # noqa: E402
from performance import performance  # noqa: E402
from plan import build_plan, SCENARIOS  # noqa: E402
from optimizer import optimize, walk_forward, WF_CANDLES  # noqa: E402
from ai_advisor import advise, ping as ai_ping, current as ai_current  # noqa: E402
from auth import (  # noqa: E402
    hash_password, verify_password, create_token, client_ip, check_locked, register_failure, clear_failures, make_require_auth,
)
from config import ConfigStore, ConfigUpdate  # noqa: E402
from bybit import BybitClient, BybitError  # noqa: E402
import notify  # noqa: E402
from review import plan_stats, build_context, apply_ai_changes, run_auto_review, start_global_optimization, job_state  # noqa: E402
from profiles import PROFILES, detect_profile, profile_patch, ai_policy  # noqa: E402
from strategies import MODE_INFO  # noqa: E402
from news import NewsAgent  # noqa: E402
import migrations  # noqa: E402
import wfcheck  # noqa: E402
import weekly  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

client = AsyncIOMotorClient(os.environ["MONGO_URL"])
db = client[os.environ["DB_NAME"]]
engine = TradingEngine(db)
store = ConfigStore(db)
news = NewsAgent(db, engine)
engine.news = news
require_auth = make_require_auth(lambda: store.cfg.token_version)

app = FastAPI(title="Bybit AI Trading Bot")
public = APIRouter(prefix="/api")
api = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])
cron = APIRouter(prefix="/api/cron")


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=200)


class PasswordChange(BaseModel):
    current: str = Field(min_length=1, max_length=200)
    new: str = Field(min_length=8, max_length=200)


class ChatsRequest(BaseModel):
    token: str = ""


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


@api.get("/auth/me")
async def auth_me():
    return {"ok": True}


@api.post("/auth/password")
async def change_password(body: PasswordChange):
    if not verify_password(body.current, store.cfg.password_hash):
        raise HTTPException(401, "La clave actual no es correcta")
    version = store.cfg.token_version + 1
    await store.update({"password_hash": hash_password(body.new), "token_version": version})
    await engine.log("INFO", "Clave de acceso cambiada · sesiones anteriores cerradas")
    return {"token": create_token(version)}


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


@api.post("/telegram/chats")
async def telegram_chats(body: ChatsRequest):
    token = body.token.strip() if body.token and not body.token.startswith("••") else store.cfg.telegram_bot_token
    if not token:
        raise HTTPException(400, "Introduce el token del bot primero")
    try:
        return {"bot": await notify.get_me(token), "chats": await notify.get_chats(token)}
    except Exception as e:
        raise HTTPException(424, str(e)[:200])


@api.post("/telegram/test")
async def telegram_test():
    acc = await engine.account_summary()
    try:
        await notify.send(f"✅ <b>Bybit AI Trader</b> conectado.\nEquidad ${acc['equity']:,.2f} · {acc['open_positions']} posiciones abiertas · bot {'ACTIVO' if engine.running else 'DETENIDO'}")
    except Exception as e:
        raise HTTPException(424, str(e)[:200])
    return {"ok": True}


@api.post("/ai/test")
async def ai_test():
    try:
        return {"ok": True, "reply": await ai_ping(), **ai_current()}
    except Exception as e:
        raise HTTPException(424, f"Error IA: {str(e)[:200]}")


def _bybit_client(body: BybitTestRequest = None):
    c = store.cfg
    use_saved = not (body and body.api_key and body.api_secret and not body.api_key.startswith("••"))
    key, secret = (c.bybit_api_key, c.bybit_api_secret) if use_saved else (body.api_key.strip(), body.api_secret.strip())
    if not key or not secret:
        raise HTTPException(400, "Introduce la API key y el secret de Bybit")
    env = (body.env if body and body.env else c.bybit_env)
    base = body.base_url if body and body.base_url is not None else c.bybit_base_url
    return BybitClient(key, secret, env, base), use_saved


@api.post("/bybit/test")
async def bybit_test(body: BybitTestRequest = None):
    client, saved = _bybit_client(body)
    try:
        t0 = time.time()
        srv = await client.server_time()
        offset_ms = int((srv - t0) * 1000) if srv else None
        wallet = await client.wallet()
        positions = await client.positions()
    except BybitError as e:
        raise HTTPException(424, f"Bybit rechazó la conexión ({e.code}): {e.msg}")
    except Exception as e:
        raise HTTPException(424, f"No se pudo conectar con Bybit: {str(e)[:160]}")
    finally:
        await client.aclose()
    if saved:
        await store.update({"bybit_verified_at": now_iso(), "bybit_verified_equity": wallet["equity"]})
        await engine.log("INFO", f"Conexión Bybit {client.env} verificada · equidad ${wallet['equity']:,.2f}")
    return {"ok": True, "env": client.env, "base_url": client.base_url, "server_offset_ms": offset_ms,
            "wallet": wallet, "open_positions": len(positions), "positions": positions, "saved_credentials": saved}


async def _mode_checks() -> dict:
    c = store.cfg
    open_pos = await db.positions.count_documents({})
    checkin = await engine.checkin()
    phase0 = checkin["phases"][0]
    checks = [
        {"key": "keys", "label": "API key y secret de Bybit guardados", "ok": bool(c.bybit_api_key and c.bybit_api_secret), "required": True},
        {"key": "verified", "label": f"Conexión verificada con Bybit {c.bybit_env}", "ok": bool(c.bybit_verified_at), "required": True,
         "detail": f"equidad ${c.bybit_verified_equity:,.2f}" if c.bybit_verified_equity is not None else None},
        {"key": "stopped", "label": "Bot detenido", "ok": not engine.running, "required": True},
        {"key": "flat", "label": "Sin posiciones abiertas", "ok": open_pos == 0, "required": True, "detail": f"{open_pos} abiertas" if open_pos else None},
        {"key": "plan", "label": "Fase 0 del plan completada (validación en paper)", "ok": phase0["met"] == phase0["total"], "required": False,
         "detail": f"{phase0['met']}/{phase0['total']} criterios"},
    ]
    return {"mode": c.trading_mode, "env": c.bybit_env, "live_since": c.live_since, "checks": checks,
            "can_go_live": all(x["ok"] for x in checks if x["required"]), "verified_equity": c.bybit_verified_equity}


@api.get("/mode")
async def get_mode():
    return await _mode_checks()


@api.post("/mode")
async def set_mode(body: ModeRequest):
    if body.mode not in ("paper", "live"):
        raise HTTPException(400, "Modo inválido")
    checks = await _mode_checks()
    if body.mode == checks["mode"]:
        return checks
    blocked = [x["label"] for x in checks["checks"] if x["required"] and not x["ok"] and x["key"] in ("stopped", "flat")]
    if blocked:
        raise HTTPException(409, "Antes de cambiar de modo: " + " · ".join(blocked))
    if body.mode == "live":
        if body.confirm.strip().upper() != "REAL":
            raise HTTPException(400, "Escribe REAL para confirmar el cambio a modo real")
        if not checks["can_go_live"]:
            raise HTTPException(409, "Faltan requisitos: " + " · ".join(x["label"] for x in checks["checks"] if x["required"] and not x["ok"]))
        await store.update({"trading_mode": "live", "live_since": now_iso()})
        if body.reset_stats:
            await engine.reset_account(store.cfg.bybit_verified_equity or None)
        await engine.log("RISK", f"MODO REAL ACTIVADO · Bybit {store.cfg.bybit_env} · el bot operará con dinero real al iniciarse")
        await notify.notify(f"🚨 <b>MODO REAL ACTIVADO</b> · Bybit {store.cfg.bybit_env}\nEquidad ${store.cfg.bybit_verified_equity or 0:,.2f}. El bot operará con dinero real cuando lo inicies.", "orders")
    else:
        await store.update({"trading_mode": "paper", "live_since": None})
        if body.reset_stats:
            await engine.reset_account()
        await engine.log("INFO", "Vuelta a modo PAPER · simulación con precios reales")
        await notify.notify("📄 <b>Vuelta a modo PAPER</b> · simulación con precios reales", "orders")
    return await _mode_checks()


@api.post("/ai/auto-review")
async def ai_auto_review_now():
    try:
        return await run_auto_review(engine, db, store)
    except Exception as e:
        logger.exception("auto review")
        raise HTTPException(424, f"Error IA: {str(e)[:200]}")


_cron_seen: list = []


async def _safe_auto_review():
    try:
        await run_auto_review(engine, db, store)
    except Exception as e:
        logger.exception("scheduled auto review")
        await engine.log("ERROR", f"Revisión IA automática falló: {str(e)[:160]}")
        await notify.notify(f"⚠️ <b>Revisión IA automática falló</b>\n{str(e)[:300]}", "review")


@cron.post("/ai-review")
async def cron_ai_review(request: Request):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    auth = request.headers.get("authorization", "")
    secret = os.environ.get("WEBHOOK_CRON_SECRET", "")
    if not (auth.lower().startswith("bearer ") and secret and hmac.compare_digest(auth[7:], secret)):
        raise HTTPException(401, "No autorizado")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Cuerpo inválido")
    run_id = request.headers.get("x-webhook-id") or (body or {}).get("run_id") or ""
    if run_id and run_id in _cron_seen:
        return {"accepted": True, "duplicate": True}
    if run_id:
        _cron_seen.append(run_id)
        del _cron_seen[:-200]
    cfg = store.cfg
    now = datetime.now(timezone.utc)
    due = cfg.auto_review_enabled and (cfg.auto_review_frequency == "daily" or (now.weekday() + 1) % 7 == cfg.auto_review_day)
    if due and cfg.auto_review_last_at:
        due = (now - datetime.fromisoformat(cfg.auto_review_last_at)).total_seconds() > 20 * 3600
    if due:
        asyncio.create_task(_safe_auto_review())
    return {"accepted": True, "scheduled": bool(due)}


def _cron_auth(request: Request):
    auth = request.headers.get("authorization", "")
    secret = os.environ.get("WEBHOOK_CRON_SECRET", "")
    if not (auth.lower().startswith("bearer ") and secret and hmac.compare_digest(auth[7:], secret)):
        raise HTTPException(401, "No autorizado")


@cron.post("/walk-forward")
async def cron_walk_forward(request: Request):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    _cron_auth(request)
    run_id = await _cron_run_id(request)
    if run_id and run_id in _cron_seen:
        return {"accepted": True, "duplicate": True}
    if run_id:
        _cron_seen.append(run_id)
        del _cron_seen[:-200]
    started = await wfcheck.start_check(engine, db, store, "auto")
    return {"accepted": True, "scheduled": started}


async def _cron_run_id(request: Request) -> str:
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Cuerpo inválido")
    if body is not None and not isinstance(body, dict):
        raise HTTPException(400, "Cuerpo inválido")
    return request.headers.get("x-webhook-id") or (body or {}).get("run_id") or ""


async def _safe_weekly():
    try:
        await weekly.send_weekly(engine, db)
    except Exception as e:
        logger.exception("weekly summary")
        await engine.log("ERROR", f"Resumen semanal falló: {str(e)[:160]}")


@cron.post("/weekly-summary")
async def cron_weekly_summary(request: Request):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    _cron_auth(request)
    run_id = await _cron_run_id(request)
    if run_id and run_id in _cron_seen:
        return {"accepted": True, "duplicate": True}
    if run_id:
        _cron_seen.append(run_id)
        del _cron_seen[:-200]
    asyncio.create_task(_safe_weekly())
    return {"accepted": True, "scheduled": True}


@api.get("/meta")
async def meta():
    return {"symbols": AVAILABLE_SYMBOLS, "timeframes": TIMEFRAMES, "strategies": STRATEGY_KEYS, "strategy_info": STRATEGY_INFO,
            "signal_modes": SIGNAL_MODES, "mode_info": MODE_INFO, "profiles": PROFILES}


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


@api.post("/plan")
async def growth_plan(req: PlanRequest):
    settings = await engine.get_settings()
    if req.scenario not in SCENARIOS and req.scenario != "backtest":
        req.scenario = "base"
    if (settings.plan_scenario, settings.plan_target_monthly, settings.plan_monthly_deposit) != (req.scenario, req.target_monthly, req.monthly_deposit):
        await engine.update_settings({"plan_scenario": req.scenario, "plan_target_monthly": req.target_monthly,
                                      "plan_monthly_deposit": req.monthly_deposit})
    return build_plan(req.model_dump(), await plan_stats(engine, settings, req.initial_capital))


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
    res = optimize(klines, s.strategy, s.risk_per_trade, s.leverage, s.trailing_enabled, acc["initial_balance"], req.symbol, s.signal_mode, s.disabled_strategies)
    return {**res, "timeframe": s.timeframe, "applied": s.symbol_params.get(req.symbol)}


@api.post("/optimize/walk-forward")
async def optimize_walk_forward(req: OptimizeRequest):
    if req.symbol not in AVAILABLE_SYMBOLS:
        raise HTTPException(400, "Símbolo inválido")
    s = await engine.get_settings()
    acc = await db.account.find_one({"_id": "main"}, {"initial_balance": 1})
    klines = await engine.market.fetch_history(req.symbol, s.timeframe, WF_CANDLES)
    res = await asyncio.to_thread(walk_forward, klines, s.strategy, s.risk_per_trade, s.leverage, s.trailing_enabled, acc["initial_balance"],
                                  req.symbol, s.signal_mode, s.disabled_strategies, s.symbol_params.get(req.symbol))
    return {**res, "timeframe": s.timeframe, "applied_params": s.symbol_params.get(req.symbol)}


@api.get("/walk-forward/check")
async def walk_forward_check_status():
    return {"job": wfcheck.job_state(), "latest": await wfcheck.latest(db), "auto_remove": store.cfg.wf_auto_remove}


@api.post("/walk-forward/check")
async def walk_forward_check_run():
    if not await wfcheck.start_check(engine, db, store, "manual"):
        raise HTTPException(409, "Ya hay una revalidación en curso")
    return {"job": wfcheck.job_state(), "latest": await wfcheck.latest(db), "auto_remove": store.cfg.wf_auto_remove}


@api.get("/weekly-summary")
async def weekly_summary_preview():
    w = await weekly.build_weekly(engine, db)
    last = await db.weekly.find_one({"_id": "latest"}, {"_id": 0, "sent_at": 1})
    return {**w, "text": weekly.format_weekly(w), "last_sent_at": (last or {}).get("sent_at")}


@api.post("/weekly-summary/send")
async def weekly_summary_send():
    try:
        return await weekly.send_weekly(engine, db, force=True)
    except Exception as e:
        raise HTTPException(424, str(e)[:200])


@api.post("/ai/optimize-all")
async def ai_optimize_all():
    if not await start_global_optimization(engine, db):
        raise HTTPException(409, "Ya hay una optimización global en curso")
    return job_state()


@api.get("/ai/optimize-all")
async def ai_optimize_all_status():
    return job_state()


@api.post("/ai/advise")
async def ai_advise(req: AdviseRequest):
    if req.scope not in ("optimizer", "plan"):
        raise HTTPException(400, "Ámbito inválido")
    settings = await engine.get_settings()
    before = settings.model_dump(exclude={"bot_running"})
    acc = await engine.account_summary()
    ctx = await build_context(engine, db, settings, acc, req.scope == "plan")
    if req.scope == "optimizer":
        ctx["optimizador"] = [{k: r.get(k) for k in ("symbol", "best", "baseline", "timeframe")} for r in (req.optimizer_results or [])]
    await engine.log("AI_EVAL", f"Claude analizando {'optimizador' if req.scope == 'optimizer' else 'plan'} y rendimiento real...")
    try:
        res = await advise(req.scope, ctx, ai_policy(settings.risk_profile))
    except Exception as e:
        logger.exception("advise")
        raise HTTPException(424, f"Error IA: {str(e)[:160]}")
    applied, previous = await apply_ai_changes(engine, res, before, settings)
    await engine.log("AI_EVAL", f"IA: {res['summary'][:160]}" + (f" · cambios: {', '.join(applied)}" if applied else " · sin cambios"))
    return {**res, "applied": applied, "previous": previous}


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
    s = await engine.get_settings()
    result = run_backtest(df, req.strategy, req.risk_per_trade, req.leverage, initial=acc["initial_balance"], symbol=req.symbol,
                          mode=s.signal_mode, disabled=s.disabled_strategies)
    result.pop("r_multiples", None)
    return {"symbol": req.symbol, "strategy": req.strategy, "timeframe": req.timeframe, **result}


app.include_router(public)
app.include_router(api)
app.include_router(cron)
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


@app.on_event("shutdown")
async def shutdown():
    await news.aclose()
    await engine.shutdown()
    client.close()
