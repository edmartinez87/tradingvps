"""«Modo laboratorio»: run ONE strategy alone (ema_cross) in an FX bot to collect clean data. Snapshot → apply preset → restore on exit."""
from models import now_iso
from fx.symbols import AVAILABLE
from strategies import STRATEGY_INFO, EXIT_REASON

LAB_STRATEGY = "ema_cross"
# Layers switched off: HTF filter, exit management (breakeven/trailing/partial), market gates, news blocks/trading and the scheduled AI review.
# Kept: AI signal filter (user choice), risk per trade, daily loss limit, max positions, min-lot guard, currency exposure, weekend flat.
SETTINGS_PATCH = {"strategy": LAB_STRATEGY, "timeframe": "15m", "signal_mode": "relaxed", "symbols": list(AVAILABLE), "ai_enabled": True,
                  "htf_filter": False, "trailing_enabled": False, "partial_tp_enabled": False, "vol_filter_enabled": False, "seasonality_bias": False,
                  "usd_regime_filter": False, "fomc_rule": False, "rollover_guard": False, "sessions_allowed": []}
CONFIG_PATCH = {"news_block_events": False, "news_block_critical": False, "news_reduce_on_high_risk": False, "news_trading_enabled": False, "auto_review_enabled": False}
KEPT = ["risk_per_trade", "daily_loss_limit", "max_positions", "min_lot_max_risk", "currency_exposure_limit", "close_before_weekend", "ai_min_confidence"]
SUMMARY = ("Solo «Cruce EMA 10/20» en 15 m, criterios relajados (EMA200 + ADX>15), 12 pares, filtro IA activo. Apagados: filtro TF superior, breakeven/trailing/cierre parcial "
           "(las salidas son SL 2×ATR, TP 6×ATR o cruce contrario), régimen USD, volatilidad, estacionalidad, FOMC, rollover, bloqueos y trading por noticias y la revisión IA automática. "
           "Se mantienen riesgo por operación, límite diario, máx. posiciones, lote mínimo, exposición por divisa y cierre antes del fin de semana.")


def _col(engine):
    return engine.db.lab


async def _stats(engine, since: str) -> dict:
    rows = await engine.db.trades.find({"strategy": LAB_STRATEGY, "closed_at": {"$gte": since}}, {"pnl": 1, "pips": 1, "reason": 1}).to_list(5000)
    wins = [t for t in rows if t["pnl"] > 0]
    reasons = {}
    for t in rows:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1
    gw, gl = sum(t["pnl"] for t in wins), abs(sum(t["pnl"] for t in rows if t["pnl"] <= 0))
    return {"trades": len(rows), "wins": len(wins), "win_rate": round(len(wins) / len(rows) * 100, 1) if rows else 0.0,
            "pnl": round(sum(t["pnl"] for t in rows), 2), "pips": round(sum(t.get("pips") or 0 for t in rows), 1),
            "profit_factor": round(gw / gl, 2) if gl else (round(gw, 2) if gw else 0.0), "reasons": reasons, "cross_exits": reasons.get(EXIT_REASON, 0),
            "open": await engine.db.positions.count_documents({"strategy": LAB_STRATEGY})}


async def state(engine, settings=None) -> dict:
    doc = await _col(engine).find_one({"_id": "main"})
    settings = settings or await engine.get_settings()
    base = {"strategy": LAB_STRATEGY, "name": STRATEGY_INFO[LAB_STRATEGY]["name"], "summary": SUMMARY, "preset": SETTINGS_PATCH, "kept": KEPT}
    if not doc:
        return {**base, "active": False}
    altered = [k for k, v in SETTINGS_PATCH.items() if k != "symbols" and getattr(settings, k) != v]
    return {**base, "active": True, "since": doc["since"], "altered": altered, "stats": await _stats(engine, doc["since"])}


async def start(engine, store) -> dict:
    if await _col(engine).find_one({"_id": "main"}):
        return await state(engine)
    settings = await engine.get_settings()
    prev = {k: settings.model_dump()[k] for k in SETTINGS_PATCH}
    prev_cfg = {k: getattr(store.cfg, k) for k in CONFIG_PATCH}
    await _col(engine).insert_one({"_id": "main", "since": now_iso(), "prev_settings": prev, "prev_config": prev_cfg})
    await store.update(dict(CONFIG_PATCH))
    s = await engine.update_settings(dict(SETTINGS_PATCH), "lab", "Modo laboratorio activado: solo Cruce EMA 10/20")
    await engine.log("INFO", "Modo laboratorio ACTIVADO · solo «Cruce EMA 10/20» en 15 m · filtros de mercado, TF superior, trailing/parcial, noticias y revisión IA automática apagados · filtro IA activo")
    await engine.tg(f"🧪 <b>Modo laboratorio activado</b> · {STRATEGY_INFO[LAB_STRATEGY]['name']}\n{SUMMARY}", "review")
    return await state(engine, s)


async def stop(engine, store) -> dict:
    doc = await _col(engine).find_one_and_delete({"_id": "main"})
    if not doc:
        return await state(engine)
    await store.update(doc["prev_config"])
    s = await engine.update_settings(doc["prev_settings"], "lab", "Modo laboratorio desactivado: ajustes anteriores restaurados")
    st = await _stats(engine, doc["since"])
    await engine.log("INFO", f"Modo laboratorio DESACTIVADO · ajustes anteriores restaurados · {st['trades']} operaciones recogidas ({st['win_rate']}% acierto · {st['pnl']:+.2f} USD)")
    await engine.tg(f"🧪 <b>Modo laboratorio desactivado</b> · ajustes restaurados\n{st['trades']} operaciones · acierto {st['win_rate']}% · PnL {st['pnl']:+.2f} USD · {st['cross_exits']} cierres por cruce contrario", "review")
    return await state(engine, s)


async def end_by_profile(engine, store) -> dict:
    """A risk profile replaces the lab settings. Profiles define neither `strategy` nor the news/auto-review config → those go back to the pre-lab values."""
    doc = await _col(engine).find_one_and_delete({"_id": "main"})
    if not doc:
        return {}
    await store.update(doc["prev_config"])
    return {"strategy": doc["prev_settings"]["strategy"]}
