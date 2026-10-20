"""/api/fx/* — HotForex AI Trading bot (forex & metals, paper trading, MetaApi/HFM account link)."""
import time
import asyncio
import logging
from datetime import datetime
from fastapi import HTTPException, Request
from bson import ObjectId

from models import Position, Trade, Signal, LogEntry, ResetRequest, OptimizeRequest, ModeRequest, STRATEGY_KEYS, SIGNAL_MODES, now_iso
from strategies import MODE_INFO
from indicators import build_df
from performance import performance
from config import ConfigUpdate
from ai_advisor import current as ai_current
import notify
from deps import store, fx_engine as engine, fx_store, fx_news as news, protected_router
from routers.shared_routes import add_shared_routes
from fx.models import FxSettingsUpdate, HfmTestRequest, FxBacktestRequest, FxProfileRequest, FX_TIMEFRAMES
from fx.config import FxConfigUpdate
from fx.symbols import SPECS, AVAILABLE, CURRENCIES, CURRENCY_NAMES, pips
from fx.market import TF_SECONDS, market_status, SESSIONS
from fx.engine import FX_STRATEGY_INFO
from fx.metaapi import MetaApi, MetaApiError
from fx.live import FxLiveBroker
from fx.profiles import PROFILES, detect_profile, profile_patch
from fx.backtest import run_backtest
from fx.optimizer import optimize, walk_forward, WF_CANDLES
from fx import review as fx_review
from fx.wfcheck import KIT as WF_KIT
import wfcheck

logger = logging.getLogger(__name__)
router = protected_router()
router.prefix = "/api/fx"
add_shared_routes(router, engine, "HotForex AI Trading")
SESSION_LIST = [{"id": s[0], "name": s[1]} for s in SESSIONS]


def _status() -> dict:
    return {"running": engine.running, "scanning": engine.scanning, "provider": "yahoo", "last_scan": engine.last_scan,
            "next_scan_in": max(0, int(engine.next_scan_ts - time.time())) if engine.next_scan_ts else None,
            "mode": engine.mode_label, "env": engine.env, "market": "Forex · Metales", "telegram": notify.is_on(), "ai": ai_current(),
            "exchange_error": engine.market.error, "broker_error": engine.broker_error if engine.live else None, "market_hours": market_status()}


async def _equity_curve(limit: int = 1440) -> list:
    rows = await engine.db.equity.find({}, {"_id": 0}).sort("ts", -1).limit(limit).to_list(limit)
    rows.reverse()
    step = max(1, len(rows) // 300)
    return rows[::step] + (rows[-1:] if rows and (len(rows) - 1) % step else [])


@router.get("/meta")
async def meta():
    return {"symbols": AVAILABLE, "symbol_info": {s: {k: v for k, v in SPECS[s].items() if k in ("name", "group", "digits", "pip")} for s in AVAILABLE},
            "timeframes": FX_TIMEFRAMES, "strategies": STRATEGY_KEYS, "strategy_info": FX_STRATEGY_INFO, "signal_modes": SIGNAL_MODES, "mode_info": MODE_INFO,
            "profiles": PROFILES, "currencies": CURRENCIES, "currency_names": CURRENCY_NAMES, "sessions": SESSION_LIST}


@router.post("/profile")
async def set_profile(req: FxProfileRequest):
    settings = await engine.get_settings()
    p = PROFILES[req.level]
    before = PROFILES[settings.risk_profile]["name"] if detect_profile(settings) is not None else "Personalizado"
    s = await engine.update_settings(profile_patch(req.level))
    st = p["settings"]
    await engine.log("INFO", f"Perfil de riesgo: {before} → {p['name']} · {len(st['symbols'])} pares · {st['timeframe']} · riesgo {st['risk_per_trade']}% · 1:{st['leverage']}")
    await engine.tg(
        f"🎚 <b>Perfil de riesgo cambiado</b>: {before} → <b>{p['name']}</b>\n"
        f"• {len(st['symbols'])} pares · velas {st['timeframe']} · criterios {MODE_INFO[st['signal_mode']]['name'].lower()}\n"
        f"• Riesgo {st['risk_per_trade']}%/op · máx {st['max_positions']} posiciones · 1:{st['leverage']} · límite diario {st['daily_loss_limit']}%\n"
        f"• Filtro TF superior: {'sí' if st['htf_filter'] else 'no'} · IA: {'sí (≥' + str(st['ai_min_confidence']) + '%)' if st['ai_enabled'] else 'NO'}"
        + (f"\n⚠️ {p['warning']}" if p["warning"] else ""), "review")
    return {"settings": s.model_dump(), "profile_active": detect_profile(s)}


async def _initial_balance() -> float:
    acc = await engine.db.account.find_one({"_id": "main"}, {"initial_balance": 1})
    return acc["initial_balance"]


@router.post("/backtest")
async def backtest(req: FxBacktestRequest):
    if req.symbol not in AVAILABLE or req.timeframe not in FX_TIMEFRAMES or req.strategy not in STRATEGY_KEYS:
        raise HTTPException(400, "Parámetros inválidos")
    s = await engine.get_settings()
    klines = await engine.market.fetch_klines(req.symbol, req.timeframe, 1000, cache_sec=60)
    result = await asyncio.to_thread(run_backtest, klines, req.strategy, req.risk_per_trade, req.leverage, s.trailing_enabled, await _initial_balance(),
                                     req.symbol, s.signal_mode, s.disabled_strategies, dict(engine.market.tickers), s.min_lot_max_risk, s.close_before_weekend,
                                     tuple(s.sessions_allowed))
    result.pop("r_multiples", None)
    return {"symbol": req.symbol, "strategy": req.strategy, "timeframe": req.timeframe, "spread_pips": round(pips(req.symbol, SPECS[req.symbol]["spread"]), 1),
            "sessions_allowed": s.sessions_allowed, **result}


@router.post("/optimize")
async def optimize_symbol(req: OptimizeRequest):
    if req.symbol not in AVAILABLE:
        raise HTTPException(400, "Símbolo inválido")
    s = await engine.get_settings()
    klines = await engine.market.fetch_klines(req.symbol, s.timeframe, 1000, cache_sec=300)
    res = await asyncio.to_thread(optimize, klines, s, await _initial_balance(), req.symbol, dict(engine.market.tickers))
    return {**res, "timeframe": s.timeframe, "applied": s.symbol_params.get(req.symbol)}


@router.post("/optimize/walk-forward")
async def optimize_walk_forward(req: OptimizeRequest):
    if req.symbol not in AVAILABLE:
        raise HTTPException(400, "Símbolo inválido")
    s = await engine.get_settings()
    klines = await engine.market.fetch_klines(req.symbol, s.timeframe, WF_CANDLES, cache_sec=600)
    res = await asyncio.to_thread(walk_forward, klines, s, await _initial_balance(), req.symbol, dict(engine.market.tickers))
    return {**res, "timeframe": s.timeframe, "applied_params": s.symbol_params.get(req.symbol)}


def _check_payload():
    return {"job": wfcheck.job_state(WF_KIT), "auto_remove": fx_store.cfg.wf_auto_remove}


@router.get("/walk-forward/check")
async def walk_forward_check_status():
    return {**_check_payload(), "latest": await wfcheck.latest(engine.db)}


@router.post("/walk-forward/check")
async def walk_forward_check_run():
    if not await wfcheck.start_check(engine, engine.db, fx_store, "manual", WF_KIT):
        raise HTTPException(409, "Ya hay una revalidación en curso")
    return {**_check_payload(), "latest": await wfcheck.latest(engine.db)}


@router.post("/ai/optimize-all")
async def ai_optimize_all():
    if not await fx_review.start(engine, engine.db):
        raise HTTPException(409, "Ya hay una optimización global en curso")
    return fx_review.job_state()


@router.get("/ai/optimize-all")
async def ai_optimize_all_status():
    return fx_review.job_state()


@router.get("/dashboard")
async def dashboard():
    settings = await engine.get_settings()
    db = engine.db
    positions = [Position.from_mongo(d).model_dump() async for d in db.positions.find().sort("_id", -1)]
    trades = [Trade.from_mongo(d).model_dump() async for d in db.trades.find().sort("_id", -1).limit(50)]
    signals = [Signal.from_mongo(d).model_dump() async for d in db.signals.find().sort("_id", -1).limit(30)]
    logs = [LogEntry.from_mongo(d).model_dump() async for d in db.logs.find().sort("_id", -1).limit(100)]
    watchlist = []
    for sym in settings.symbols:
        t = engine.market.tickers.get(sym, {})
        watchlist.append({"symbol": sym, "name": SPECS[sym]["name"], "group": SPECS[sym]["group"], "price": t.get("price"), "change_pct": t.get("change_pct"),
                          "high": t.get("high"), "low": t.get("low"), "spread_pips": round(pips(sym, SPECS[sym]["spread"]), 1), "digits": SPECS[sym]["digits"],
                          **engine.analysis.get(sym, {})})
    return {"status": _status(), "settings": settings.model_dump(), "account": await engine.account_summary(), "positions": positions, "trades": trades,
            "signals": signals, "logs": logs, "watchlist": watchlist, "equity": await _equity_curve(), "profile_active": detect_profile(settings), "news": news.summary(),
            "optimize_job": {k: fx_review.job[k] for k in ("status", "step")},
            "hfm": {"configured": fx_store.public()["hfm_configured"], "state": fx_store.cfg.hfm_state, "connection": fx_store.cfg.hfm_connection,
                    "verified_at": fx_store.cfg.hfm_verified_at, "trade_allowed": fx_store.cfg.hfm_trade_allowed, "live": engine.live}}


@router.get("/klines")
async def klines(symbol: str, tf: str = "1h", limit: int = 300):
    if symbol not in AVAILABLE or tf not in FX_TIMEFRAMES:
        raise HTTPException(400, "Símbolo o temporalidad inválida")
    df = build_df(await engine.market.fetch_klines(symbol, tf, min(max(limit, 100), 1000), cache_sec=20))
    times = (df["ts"] // 1000).astype(int).tolist()

    def line(col, start=0):
        return [{"time": t, "value": round(float(v), 8)} for t, v in zip(times[start:], df[col].tolist()[start:])]

    candles = [{"time": t, "open": o, "high": h, "low": lo, "close": c} for t, o, h, lo, c in zip(times, df["open"], df["high"], df["low"], df["close"])]
    volume = [{"time": t, "value": v, "color": "rgba(16,185,129,0.35)" if c >= o else "rgba(239,68,68,0.35)"} for t, v, o, c in zip(times, df["volume"], df["open"], df["close"])]
    step, first = TF_SECONDS[tf], times[0]

    def snap(iso):
        ts = int(datetime.fromisoformat(iso).timestamp())
        return ts - ts % step

    markers = []
    async for d in engine.db.trades.find({"symbol": symbol}).sort("_id", -1).limit(100):
        t = Trade.from_mongo(d)
        long = t.side == "long"
        if snap(t.opened_at) >= first:
            markers.append({"time": snap(t.opened_at), "position": "belowBar" if long else "aboveBar", "color": "#10B981" if long else "#EF4444",
                            "shape": "arrowUp" if long else "arrowDown", "text": "LONG" if long else "SHORT"})
        if snap(t.closed_at) >= first:
            markers.append({"time": snap(t.closed_at), "position": "aboveBar" if long else "belowBar", "color": "#F7A600", "shape": "circle", "text": f"{t.reason} {t.pnl:+.1f}"})
    lines = []
    async for d in engine.db.positions.find({"symbol": symbol}):
        p = Position.from_mongo(d)
        long = p.side == "long"
        if snap(p.opened_at) >= first:
            markers.append({"time": snap(p.opened_at), "position": "belowBar" if long else "aboveBar", "color": "#10B981" if long else "#EF4444",
                            "shape": "arrowUp" if long else "arrowDown", "text": "LONG" if long else "SHORT"})
        lines = [{"price": p.entry_price, "title": "ENTRADA", "color": "#F8FAFC"}, {"price": p.sl, "title": "SL", "color": "#EF4444"}, {"price": p.tp, "title": "TP", "color": "#10B981"}]
    markers.sort(key=lambda m: m["time"])
    return {"symbol": symbol, "tf": tf, "candles": candles, "volume": volume, "ema9": line("ema9"), "ema21": line("ema21"), "ema200": line("ema200", 50),
            "rsi": line("rsi", 14), "markers": markers, "lines": lines}


@router.post("/bot/start")
async def bot_start():
    if engine.live:
        c = fx_store.cfg
        if not (c.metaapi_token and c.metaapi_account_id and c.hfm_verified_at):
            raise HTTPException(409, "Modo REAL: vincula y verifica la cuenta HFM (Ajustes → HotForex) antes de iniciar el bot")
        if c.hfm_trade_allowed is False:
            raise HTTPException(409, "Modo REAL: la cuenta HFM no permite operar (trading deshabilitado o contraseña investor)")
    await engine.start()
    return _status()


@router.post("/bot/stop")
async def bot_stop():
    await engine.stop()
    return _status()


@router.post("/bot/scan")
async def bot_scan():
    engine.scan_event.set()
    return {"ok": True, "message": "Escaneo solicitado"}


@router.get("/market")
async def market():
    return market_status()


@router.get("/overview")
async def overview():
    acc = await engine.account_summary()
    return {"running": engine.running, "mode": engine.mode_label, "equity": acc["equity"], "total_return_pct": acc["total_return_pct"],
            "open_positions": acc["open_positions"], "market_open": market_status()["open"]}


@router.get("/settings")
async def get_settings():
    return (await engine.get_settings()).model_dump()


@router.put("/settings")
async def put_settings(body: FxSettingsUpdate):
    try:
        s = await engine.update_settings(body.model_dump())
    except ValueError as e:
        raise HTTPException(422, str(e))
    return s.model_dump()


@router.get("/positions")
async def list_positions():
    return [Position.from_mongo(d).model_dump() async for d in engine.db.positions.find().sort("_id", -1)]


@router.post("/positions/{pos_id}/close")
async def close_pos(pos_id: str):
    if not ObjectId.is_valid(pos_id):
        raise HTTPException(400, "ID inválido")
    trade = await engine.close_position(pos_id, reason="MANUAL")
    if not trade:
        raise HTTPException(404, "Posición no encontrada")
    return trade.model_dump()


@router.post("/positions/close-all")
async def close_all():
    ids = [str(d["_id"]) async for d in engine.db.positions.find({}, {"_id": 1})]
    closed = [pid for pid in ids if await engine.close_position(pid, reason="MANUAL")]
    await engine.log("RISK", f"Cierre de emergencia · {len(closed)} posiciones cerradas")
    return {"closed": len(closed), "failed": len(ids) - len(closed)}


@router.get("/trades")
async def list_trades(limit: int = 100):
    return [Trade.from_mongo(d).model_dump() async for d in engine.db.trades.find().sort("_id", -1).limit(min(limit, 500))]


@router.get("/signals")
async def list_signals(limit: int = 50):
    return [Signal.from_mongo(d).model_dump() async for d in engine.db.signals.find().sort("_id", -1).limit(min(limit, 200))]


@router.get("/account")
async def account():
    return await engine.account_summary()


@router.post("/account/reset")
async def reset_account(body: ResetRequest = None):
    if await engine.db.positions.count_documents({"live": True}):
        raise HTTPException(409, "Hay posiciones REALES abiertas en HFM: ciérralas antes de reiniciar las estadísticas")
    await engine.reset_account(body.initial_balance if body else None)
    return await engine.account_summary()


@router.get("/performance")
async def get_performance():
    return await performance(engine.db)


@router.delete("/logs")
async def clear_logs():
    await engine.db.logs.delete_many({})
    return {"ok": True}


@router.get("/news")
async def get_news():
    return {"latest": news.latest, "summary": news.summary()}


@router.post("/news/refresh")
async def refresh_news():
    try:
        await news.refresh()
    except Exception as e:
        logger.exception("fx news refresh")
        raise HTTPException(424, f"No se pudo actualizar las noticias: {str(e)[:160]}")
    return {"latest": news.latest, "summary": news.summary()}


@router.get("/news/trades")
async def news_trades(limit: int = 20):
    return [{k: v for k, v in d.items() if k != "_id"} async for d in engine.db.news_trades.find().sort("_id", -1).limit(min(limit, 100))]


@router.get("/config")
async def get_config():
    return {**store.public(), **fx_store.public()}


@router.put("/config")
async def put_config(request: Request):
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(400, "Cuerpo inválido")
    g = {k: v for k, v in body.items() if k in ConfigUpdate.model_fields and k not in FxConfigUpdate.model_fields}
    f = {k: v for k, v in body.items() if k in FxConfigUpdate.model_fields}
    if body.get("clear_hfm") and fx_store.cfg.trading_mode == "live":
        raise HTTPException(409, "Vuelve a modo paper antes de quitar la cuenta HFM")
    try:
        gp = store.patch_from(ConfigUpdate(**g)) if g else {}
        fp = fx_store.patch_from(FxConfigUpdate(**f)) if f else {}
    except ValueError as e:
        raise HTTPException(422, str(e))
    if gp:
        await store.update(gp)
    if fp:
        await fx_store.update(fp)
    if gp or fp:
        await engine.log("INFO", f"Ajustes actualizados: {', '.join(list(gp) + list(fp))}")
    return {**store.public(), **fx_store.public()}


def _metaapi(body: HfmTestRequest = None):
    c = fx_store.cfg
    use_saved = not (body and body.metaapi_token and not body.metaapi_token.startswith("••"))
    token = c.metaapi_token if use_saved else body.metaapi_token.strip()
    if not token:
        raise HTTPException(400, "Introduce el token de MetaApi primero")
    region = (body.metaapi_region if body and body.metaapi_region else c.metaapi_region)
    base = (body.metaapi_base_url.strip() if body and body.metaapi_base_url is not None else c.metaapi_base_url)
    login = (body.mt_login.strip() if body and body.mt_login else c.mt_login)
    server = (body.mt_server.strip() if body and body.mt_server is not None else c.mt_server)
    return MetaApi(token, region, base), use_saved, login, server


def _acc_view(acc: dict) -> dict:
    return {"id": acc.get("_id") or acc.get("id"), "login": acc.get("login"), "server": acc.get("server"), "state": acc.get("state"),
            "connection": acc.get("connectionStatus"), "region": acc.get("region"), "platform": acc.get("platform") or acc.get("version")}


@router.post("/hfm/test")
async def hfm_test(body: HfmTestRequest = None):
    api, saved, login, server = _metaapi(body)
    out = {"ok": True, "token_valid": False, "account": None, "info": None, "positions": [], "saved_credentials": saved, "login": login, "server": server}
    try:
        accounts = await api.list_accounts()
        out["token_valid"] = True
        out["accounts_total"] = len(accounts)
        acc = next((a for a in accounts if str(a.get("login")) == str(login) and (not server or str(a.get("server", "")).lower() == server.lower())), None) if login else None
        if acc:
            out["account"] = _acc_view(acc)
            if acc.get("state") == "DEPLOYED" and acc.get("connectionStatus") == "CONNECTED":
                out["info"] = await api.account_info(acc["_id"], acc.get("region") or api.region, refresh=True)
                out["positions"] = await api.positions(acc["_id"], acc.get("region") or api.region)
    except MetaApiError as e:
        raise HTTPException(424, e.msg)
    except Exception as e:
        raise HTTPException(424, f"No se pudo conectar con MetaApi: {str(e)[:160]}")
    finally:
        await api.aclose()
    if saved:
        patch = {"hfm_state": (out["account"] or {}).get("state") or ("TOKEN_OK" if out["token_valid"] else ""),
                 "hfm_connection": (out["account"] or {}).get("connection") or ""}
        if out["account"]:
            patch["metaapi_account_id"] = out["account"]["id"]
        if out["info"]:
            info = out["info"]
            patch.update(hfm_verified_at=now_iso(), hfm_verified_equity=info.get("equity"), hfm_currency=info.get("currency", ""),
                         hfm_leverage=info.get("leverage"), hfm_broker=info.get("broker", ""), hfm_trade_allowed=bool(info.get("tradeAllowed", True)))
            await engine.log("INFO", f"Cuenta HFM verificada vía MetaApi · {info.get('broker', 'HFM')} {server} · equidad {info.get('equity')} {info.get('currency', '')}"
                                     + ("" if info.get("tradeAllowed", True) else " · SIN permiso de trading (contraseña investor)"))
        await fx_store.update(patch)
    out["hint"] = (None if out["info"] else "Cuenta vinculada pero aún no conectada: espera unos minutos y vuelve a probar" if out["account"]
                   else "Token válido. La cuenta MT todavía no está vinculada en MetaApi: pulsa «Vincular cuenta»." if login else "Token válido. Guarda el login/servidor de HFM para vincular la cuenta.")
    if out["info"] and not out["info"].get("tradeAllowed", True):
        out["hint"] = "La cuenta está conectada pero NO permite operar: usa la contraseña master (no investor) para el modo REAL."
    return out


@router.post("/hfm/link")
async def hfm_link():
    c = fx_store.cfg
    if not (c.metaapi_token and c.mt_login and c.mt_password and c.mt_server):
        raise HTTPException(400, "Guarda primero el token de MetaApi, login, contraseña y servidor de HFM")
    api = MetaApi(c.metaapi_token, c.metaapi_region, c.metaapi_base_url)
    try:
        acc = await api.find_account(c.mt_login, c.mt_server)
        if not acc:
            created = await api.provision(c.mt_login, c.mt_password, c.mt_server, c.mt_platform)
            acc = await api.account(created.get("id") or created.get("_id"))
            await engine.log("INFO", f"Cuenta HFM {c.mt_login} vinculada en MetaApi ({c.metaapi_region})")
        if acc.get("state") in ("UNDEPLOYED", "CREATED"):
            await api.deploy(acc["_id"])
            acc = await api.account(acc["_id"])
    except MetaApiError as e:
        raise HTTPException(424, e.msg)
    except Exception as e:
        raise HTTPException(424, f"No se pudo vincular la cuenta: {str(e)[:160]}")
    finally:
        await api.aclose()
    await fx_store.update({"metaapi_account_id": acc["_id"], "hfm_state": acc.get("state", ""), "hfm_connection": acc.get("connectionStatus", "")})
    return {"ok": True, "account": _acc_view(acc), "hint": "Despliegue solicitado: la conexión tarda 1-3 minutos. Pulsa «Probar conexión» para ver el estado."}


@router.post("/hfm/redeploy")
async def hfm_redeploy():
    c = fx_store.cfg
    if not (c.metaapi_token and c.metaapi_account_id):
        raise HTTPException(400, "Vincula primero la cuenta en MetaApi")
    api = MetaApi(c.metaapi_token, c.metaapi_region, c.metaapi_base_url)
    try:
        await api.redeploy(c.metaapi_account_id)
        acc = await api.account(c.metaapi_account_id)
    except MetaApiError as e:
        raise HTTPException(424, e.msg)
    finally:
        await api.aclose()
    await fx_store.update({"hfm_state": acc.get("state", ""), "hfm_connection": acc.get("connectionStatus", ""), "hfm_verified_at": None})
    await engine.log("INFO", "Redespliegue de la cuenta HFM en MetaApi solicitado")
    return {"ok": True, "account": _acc_view(acc), "hint": "Redespliegue en curso (1-3 minutos). Vuelve a «Probar conexión»."}


@router.post("/hfm/symbols")
async def hfm_symbols():
    c = fx_store.cfg
    if not (c.metaapi_token and c.metaapi_account_id):
        raise HTTPException(400, "Vincula y verifica primero la cuenta en MetaApi")
    s = await engine.get_settings()
    broker = engine.broker or FxLiveBroker(c.metaapi_token, c.metaapi_account_id, c.metaapi_region, c.metaapi_base_url, c.mt_symbol_suffix)
    try:
        rows = {sym: await broker.check_symbol(sym) for sym in s.symbols}
    finally:
        if broker is not engine.broker:
            await broker.aclose()
    bad = [sym for sym, r in rows.items() if not r["ok"]]
    await engine.log("INFO", f"Símbolos HFM comprobados · {len(rows) - len(bad)}/{len(rows)} disponibles" + (f" · sin cotización: {', '.join(bad)}" if bad else ""))
    return {"suffix": c.mt_symbol_suffix, "symbols": rows, "missing": bad}


async def _mode_checks() -> dict:
    c = fx_store.cfg
    open_pos = await engine.db.positions.count_documents({})
    acc = await engine.account_summary()
    checks = [
        {"key": "keys", "label": "Token de MetaApi y cuenta HFM guardados", "ok": bool(c.metaapi_token and c.mt_login and c.mt_password and c.mt_server), "required": True},
        {"key": "linked", "label": "Cuenta vinculada y desplegada en MetaApi", "ok": bool(c.metaapi_account_id and c.hfm_state == "DEPLOYED"), "required": True,
         "detail": f"{c.hfm_state or 'sin vincular'}{' · ' + c.hfm_connection if c.hfm_connection else ''}"},
        {"key": "verified", "label": f"Conexión verificada con HFM {c.mt_server or ''}".strip(), "ok": bool(c.hfm_verified_at), "required": True,
         "detail": f"equidad {c.hfm_verified_equity:,.2f} {c.hfm_currency}" if c.hfm_verified_equity is not None else None},
        {"key": "trade_allowed", "label": "La cuenta permite operar (contraseña master)", "ok": c.hfm_trade_allowed is not False, "required": True,
         "detail": None if c.hfm_trade_allowed is not False else "trading deshabilitado o contraseña investor"},
        {"key": "stopped", "label": "Bot detenido", "ok": not engine.running, "required": True},
        {"key": "flat", "label": "Sin posiciones abiertas", "ok": open_pos == 0, "required": True, "detail": f"{open_pos} abiertas" if open_pos else None},
        {"key": "paper", "label": "Validación en paper: ≥ 30 operaciones con profit factor ≥ 1.2", "required": False,
         "ok": acc["total_trades"] >= 30 and (acc["profit_factor"] or 0) >= 1.2, "detail": f"{acc['total_trades']} ops · PF {acc['profit_factor'] or '—'}"},
    ]
    return {"mode": c.trading_mode, "env": c.mt_server or "HFM", "live_since": c.live_since, "checks": checks,
            "can_go_live": all(x["ok"] for x in checks if x["required"]), "verified_equity": c.hfm_verified_equity, "currency": c.hfm_currency or "USD"}


@router.get("/mode")
async def get_mode():
    return await _mode_checks()


@router.post("/mode")
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
        await fx_store.update({"trading_mode": "live", "live_since": now_iso()})
        if body.reset_stats:
            await engine.reset_account(fx_store.cfg.hfm_verified_equity or None)
        await engine.log("RISK", f"MODO REAL ACTIVADO · HFM {fx_store.cfg.mt_server} vía MetaApi · el bot operará con dinero real al iniciarse")
        await engine.tg(f"🚨 <b>MODO REAL ACTIVADO</b> · HFM {fx_store.cfg.mt_server}\nEquidad {fx_store.cfg.hfm_verified_equity or 0:,.2f} {fx_store.cfg.hfm_currency}. "
                        "El bot operará con dinero real cuando lo inicies.", "orders")
    else:
        await fx_store.update({"trading_mode": "paper", "live_since": None})
        if body.reset_stats:
            await engine.reset_account()
        await engine.log("INFO", "Vuelta a modo PAPER · simulación con precios de Yahoo Finance")
        await engine.tg("📄 <b>Vuelta a modo PAPER</b> · simulación con precios de Yahoo Finance", "orders")
    return await _mode_checks()
