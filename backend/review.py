import time
import logging
from models import SettingsUpdate, AVAILABLE_SYMBOLS, now_iso
from performance import performance
from plan import backtest_stats
from ai_advisor import advise
import notify

logger = logging.getLogger("review")
ALLOWED_AI_KEYS = {"symbols", "strategy", "risk_per_trade", "max_positions", "leverage", "ai_min_confidence",
                   "trailing_enabled", "htf_filter", "symbol_params"}
AI_CAPS = {"risk_per_trade": 1.5, "leverage": 5, "max_positions": 5}
LABELS = {"symbols": "Pares", "strategy": "Estrategia", "risk_per_trade": "Riesgo/op %", "max_positions": "Máx. posiciones",
          "leverage": "Apalancamiento", "ai_min_confidence": "Confianza mín. IA", "trailing_enabled": "Trailing",
          "htf_filter": "Filtro TF superior", "symbol_params": "Parámetros SL/TP"}
_plan_cache: dict = {}


async def plan_stats(engine, settings, initial: float) -> dict:
    key = (tuple(settings.symbols), settings.timeframe, settings.strategy, settings.risk_per_trade,
           settings.leverage, settings.trailing_enabled, settings.max_positions, initial, str(settings.symbol_params))
    hit = _plan_cache.get(key)
    if not hit or time.time() - hit["ts"] > 300:
        hit = {"ts": time.time(), "data": await backtest_stats(engine.market.fetch_klines, settings, initial)}
        _plan_cache.clear()
        _plan_cache[key] = hit
    return hit["data"]


async def build_context(engine, db, settings, acc: dict, with_backtest: bool) -> dict:
    ctx = {"settings_actuales": settings.model_dump(exclude={"bot_running"}), "cuenta": acc,
           "rendimiento_real": await performance(db), "chequeo_plan": await engine.checkin(settings, acc)}
    if with_backtest:
        bt = await plan_stats(engine, settings, acc["initial_balance"])
        ctx["backtest"] = {k: bt[k] for k in ("per_symbol", "by_strategy", "monte_carlo", "trades_per_month", "days")}
    return ctx


async def apply_ai_changes(engine, res: dict, before: dict):
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
    return applied, {k: before[k] for k in applied}


def _fmt(v) -> str:
    if isinstance(v, bool):
        return "sí" if v else "no"
    if isinstance(v, list):
        return ", ".join(s.replace("USDT", "") for s in v) or "ninguno"
    if isinstance(v, dict):
        return "; ".join(f"{s.replace('USDT', '')} SL {p.get('sl_atr')}× TP {p.get('tp_atr')}× ATR {p.get('atr_period')}" for s, p in v.items()) or "por defecto"
    return str(v)


def changes_text(applied: dict) -> str:
    return "\n".join(f"• <b>{LABELS.get(k, k)}</b>: {_fmt(v['antes'])} → {_fmt(v['despues'])}" for k, v in applied.items())


async def run_auto_review(engine, db, store) -> dict:
    settings = await engine.get_settings()
    acc = await engine.account_summary()
    before = settings.model_dump(exclude={"bot_running"})
    await engine.log("AI_EVAL", "Revisión IA automática iniciada...")
    ctx = await build_context(engine, db, settings, acc, True)
    res = await advise("revision_automatica_programada", ctx)
    applied, previous = ({}, {})
    if store.cfg.auto_review_apply:
        applied, previous = await apply_ai_changes(engine, res, before)
    await store.update({"auto_review_last_at": now_iso(), "auto_review_last_summary": res["summary"], "auto_review_last_changes": applied})
    await engine.log("AI_EVAL", f"Revisión automática: {res['summary'][:160]}" + (f" · cambios: {', '.join(applied)}" if applied else " · sin cambios"))
    msg = (f"🧠 <b>Revisión IA automática</b>\n{res['summary']}\n\n"
           + (f"<b>Cambios aplicados</b>\n{changes_text(applied)}" if applied else ("<b>Sin cambios</b> en la configuración" if store.cfg.auto_review_apply else "<b>Modo solo aviso</b>: no se aplicó nada"))
           + (("\n\n" + "\n".join(f"– {n}" for n in res["notes"])) if res["notes"] else "")
           + f"\n\n💰 Equidad ${acc['equity']:,.2f} · {acc['total_trades']} ops · PF {acc['profit_factor'] or '—'} · DD {acc['max_drawdown']}%")
    await notify.notify(msg, "review")
    return {**res, "applied": applied, "previous": previous, "ran_at": store.cfg.auto_review_last_at}
