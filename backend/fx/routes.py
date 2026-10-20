"""/api/fx/* — HotForex AI Trading bot (forex & metals, paper trading, MetaApi/HFM account link)."""
import time
import logging
from datetime import datetime
from fastapi import HTTPException, Request
from bson import ObjectId

from models import Position, Trade, Signal, LogEntry, ResetRequest, STRATEGY_KEYS, SIGNAL_MODES, now_iso
from strategies import MODE_INFO
from indicators import build_df
from performance import performance
from config import ConfigUpdate
from ai_advisor import current as ai_current
import notify
from deps import store, fx_engine as engine, fx_store, fx_news as news, protected_router
from routers.shared_routes import add_shared_routes
from fx.models import FxSettingsUpdate, HfmTestRequest, FX_TIMEFRAMES
from fx.config import FxConfigUpdate
from fx.symbols import SPECS, AVAILABLE, CURRENCIES, CURRENCY_NAMES, pips
from fx.market import TF_SECONDS, market_status
from fx.engine import FX_STRATEGY_INFO
from fx.metaapi import MetaApi, MetaApiError

logger = logging.getLogger(__name__)
router = protected_router()
router.prefix = "/api/fx"
add_shared_routes(router, engine, "HotForex AI Trading")


def _status() -> dict:
    return {"running": engine.running, "scanning": engine.scanning, "provider": "yahoo", "last_scan": engine.last_scan,
            "next_scan_in": max(0, int(engine.next_scan_ts - time.time())) if engine.next_scan_ts else None,
            "mode": engine.mode_label, "env": fx_store.cfg.mt_server or "HFM", "market": "Forex · Metales", "telegram": notify.is_on(), "ai": ai_current(),
            "exchange_error": engine.market.error, "market_hours": market_status()}


async def _equity_curve(limit: int = 1440) -> list:
    rows = await engine.db.equity.find({}, {"_id": 0}).sort("ts", -1).limit(limit).to_list(limit)
    rows.reverse()
    step = max(1, len(rows) // 300)
    return rows[::step] + (rows[-1:] if rows and (len(rows) - 1) % step else [])


@router.get("/meta")
async def meta():
    return {"symbols": AVAILABLE, "symbol_info": {s: {k: v for k, v in SPECS[s].items() if k in ("name", "group", "digits", "pip")} for s in AVAILABLE},
            "timeframes": FX_TIMEFRAMES, "strategies": STRATEGY_KEYS, "strategy_info": FX_STRATEGY_INFO, "signal_modes": SIGNAL_MODES, "mode_info": MODE_INFO,
            "profiles": None, "currencies": CURRENCIES, "currency_names": CURRENCY_NAMES}


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
            "signals": signals, "logs": logs, "watchlist": watchlist, "equity": await _equity_curve(), "profile_active": None, "news": news.summary(),
            "hfm": {"configured": fx_store.public()["hfm_configured"], "state": fx_store.cfg.hfm_state, "verified_at": fx_store.cfg.hfm_verified_at}}


@router.get("/klines")
async def klines(symbol: str, tf: str = "1h", limit: int = 300):
    if symbol not in AVAILABLE or tf not in TF_SECONDS:
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
    g = {k: v for k, v in body.items() if k in ConfigUpdate.model_fields}
    f = {k: v for k, v in body.items() if k in FxConfigUpdate.model_fields}
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
    login = (body.mt_login.strip() if body and body.mt_login else c.mt_login)
    server = (body.mt_server.strip() if body and body.mt_server is not None else c.mt_server)
    return MetaApi(token, region), use_saved, login, server


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
            out["account"] = {"id": acc.get("_id"), "login": acc.get("login"), "server": acc.get("server"), "state": acc.get("state"),
                              "connection": acc.get("connectionStatus"), "region": acc.get("region"), "platform": acc.get("platform") or acc.get("version")}
            if acc.get("state") == "DEPLOYED" and acc.get("connectionStatus") == "CONNECTED":
                out["info"] = await api.account_info(acc["_id"], acc.get("region") or api.region)
                out["positions"] = await api.positions(acc["_id"], acc.get("region") or api.region)
    except MetaApiError as e:
        raise HTTPException(424, e.msg)
    except Exception as e:
        raise HTTPException(424, f"No se pudo conectar con MetaApi: {str(e)[:160]}")
    finally:
        await api.aclose()
    if saved:
        patch = {"hfm_state": (out["account"] or {}).get("state") or ("TOKEN_OK" if out["token_valid"] else "")}
        if out["account"]:
            patch["metaapi_account_id"] = out["account"]["id"]
        if out["info"]:
            patch.update(hfm_verified_at=now_iso(), hfm_verified_equity=out["info"].get("equity"), hfm_currency=out["info"].get("currency", ""),
                         hfm_leverage=out["info"].get("leverage"))
            await engine.log("INFO", f"Cuenta HFM verificada vía MetaApi · {out['info'].get('broker', 'HFM')} {server} · equidad {out['info'].get('equity')} {out['info'].get('currency', '')}")
        await fx_store.update(patch)
    out["hint"] = (None if out["info"] else "Cuenta vinculada pero aún no conectada: espera unos minutos y vuelve a probar" if out["account"]
                   else "Token válido. La cuenta MT todavía no está vinculada en MetaApi: pulsa «Vincular cuenta»." if login else "Token válido. Guarda el login/servidor de HFM para vincular la cuenta.")
    return out


@router.post("/hfm/link")
async def hfm_link():
    c = fx_store.cfg
    if not (c.metaapi_token and c.mt_login and c.mt_password and c.mt_server):
        raise HTTPException(400, "Guarda primero el token de MetaApi, login, contraseña y servidor de HFM")
    api = MetaApi(c.metaapi_token, c.metaapi_region)
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
    await fx_store.update({"metaapi_account_id": acc["_id"], "hfm_state": acc.get("state", "")})
    return {"ok": True, "account": {"id": acc["_id"], "login": acc.get("login"), "server": acc.get("server"), "state": acc.get("state"),
                                    "connection": acc.get("connectionStatus"), "region": acc.get("region")},
            "hint": "Despliegue solicitado: la conexión tarda 1-3 minutos. Pulsa «Probar conexión» para ver el estado."}
