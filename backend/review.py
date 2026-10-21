import time
import asyncio
import logging
from models import SettingsUpdate, AVAILABLE_SYMBOLS, STRATEGY_KEYS, now_iso
from performance import performance
from plan import backtest_stats
from ai_advisor import advise, label as ai_label
from optimizer import optimize, walk_forward, WF_CANDLES
from profiles import ai_policy, PROFILES
from shadow import recent_rejections
from fx.market import SESSION_NAMES
import notify

logger = logging.getLogger("review")
ALLOWED_AI_KEYS = {"symbols", "disabled_strategies", "risk_per_trade", "max_positions", "leverage", "ai_min_confidence",
                   "trailing_enabled", "htf_filter", "symbol_params"}
LABELS = {"symbols": "Pares", "strategy": "Estrategia", "disabled_strategies": "Estrategias apagadas", "risk_per_trade": "Riesgo/op %",
          "max_positions": "Máx. posiciones", "leverage": "Apalancamiento", "ai_min_confidence": "Confianza mín. IA", "trailing_enabled": "Trailing",
          "htf_filter": "Filtro TF superior", "symbol_params": "Parámetros SL/TP", "sessions_allowed": "Sesiones permitidas"}
STRATEGY_NAMES = {"trend_ema": "Tendencia EMA", "mean_reversion": "Reversión media", "breakout_turtle": "Turtle",
                  "supertrend_momentum": "Supertrend", "ema_pullback": "Pullback EMA21"}
_plan_cache: dict = {}
job: dict = {"status": "idle", "started_at": None, "finished_at": None, "result": None, "error": None, "step": ""}


async def plan_stats(engine, settings, initial: float) -> dict:
    key = (tuple(settings.symbols), settings.timeframe, settings.strategy, settings.risk_per_trade, settings.leverage,
           settings.trailing_enabled, settings.max_positions, initial, str(settings.symbol_params), settings.signal_mode,
           tuple(settings.disabled_strategies))
    hit = _plan_cache.get(key)
    if not hit or time.time() - hit["ts"] > 300:
        hit = {"ts": time.time(), "data": await backtest_stats(engine.market.fetch_klines, settings, initial)}
        _plan_cache.clear()
        _plan_cache[key] = hit
    return hit["data"]


async def build_context(engine, db, settings, acc: dict, with_backtest: bool) -> dict:
    pol = ai_policy(settings.risk_profile)
    ctx = {"settings_actuales": settings.model_dump(exclude={"bot_running"}), "cuenta": acc,
           "perfil_riesgo": {"nivel": pol["level"], "nombre": pol["name"], "topes_ia": pol["caps"]},
           "rendimiento_real": await performance(db), "chequeo_plan": await engine.checkin(settings, acc),
           "motivos_rechazo_recientes_ia": await recent_rejections(db)}
    ctx["rendimiento_real"]["shadow"]["_explicacion"] = ("Operaciones sombra: qué habría pasado si se hubieran ejecutado las señales rechazadas por la IA "
                                                         "(RECHAZADA, BAJA_CONFIANZA), bloqueadas por riesgo (BLOQUEADA), por noticias (NOTICIAS) o por funding extremo en contra (FUNDING). "
                                                         "filter_value > 0 = el filtro evitó pérdidas netas; < 0 = el filtro dejó escapar ganancias. "
                                                         "by_confidence sirve para calibrar ai_min_confidence con evidencia.")
    if engine.news and engine.news.latest:
        ctx["noticias"] = {"mercado": engine.news.latest["market"], "alertas": engine.news.latest.get("alerts", [])[:5]}
    wf_latest = await db.wf_checks.find_one({"_id": "latest"}, {"_id": 0, "ran_at": 1, "results": 1})
    if wf_latest and wf_latest.get("results"):
        ctx["walk_forward_pares_aplicados"] = {"revisado": wf_latest["ran_at"], "pares": {s: {k: r[k] for k in ("verdict", "wfe", "oos", "previous_verdict")}
                                                                                       for s, r in wf_latest["results"].items()},
                                               "_explicacion": "Revalidación walk-forward de los pares con symbol_params aplicados; SOBREAJUSTADO/NO_RENTABLE = quitar sus symbol_params."}
    if with_backtest:
        bt = await plan_stats(engine, settings, acc["initial_balance"])
        ctx["backtest"] = {k: bt[k] for k in ("per_symbol", "by_strategy", "monte_carlo", "trades_per_month", "days")}
    return ctx


async def apply_ai_changes(engine, res: dict, before: dict, settings, *, policy: dict = None, available=AVAILABLE_SYMBOLS,
                           model=SettingsUpdate, allowed=ALLOWED_AI_KEYS):
    patch = {k: v for k, v in res["changes"].items() if k in allowed}
    for k, cap in (policy or ai_policy(settings.risk_profile))["caps"].items():
        if k in patch:
            patch[k] = min(float(patch[k]), cap)
    if "symbols" in patch and (not isinstance(patch["symbols"], list) or len([x for x in patch["symbols"] if x in available]) < 2):
        patch.pop("symbols")
    if "sessions_allowed" in patch and not isinstance(patch["sessions_allowed"], list):
        patch.pop("sessions_allowed")
    if "disabled_strategies" in patch:
        dis = [x for x in (patch["disabled_strategies"] if isinstance(patch["disabled_strategies"], list) else []) if x in STRATEGY_KEYS and x != "all"]
        if len(dis) >= len(STRATEGY_KEYS) - 1:
            patch.pop("disabled_strategies")
        else:
            patch["disabled_strategies"] = dis
            patch["strategy"] = "all"
    applied = {}
    if patch:
        try:
            after = (await engine.update_settings(model.model_validate(patch).model_dump())).model_dump(exclude={"bot_running"})
            applied = {k: {"antes": before[k], "despues": after[k]} for k in patch if before.get(k) != after.get(k)}
        except Exception as e:
            res["notes"].append(f"Cambios propuestos no válidos y descartados: {str(e)[:120]}")
    return applied, {k: before[k] for k in applied}


def _fmt(k, v) -> str:
    if isinstance(v, bool):
        return "sí" if v else "no"
    if isinstance(v, list):
        if k == "disabled_strategies":
            return ", ".join(STRATEGY_NAMES.get(s, s) for s in v) or "ninguna"
        if k == "sessions_allowed":
            return ", ".join(SESSION_NAMES.get(s, s) for s in v) or "todas"
        return ", ".join(s.replace("USDT", "") for s in v) or "ninguno"
    if isinstance(v, dict):
        return "; ".join(f"{s.replace('USDT', '')} SL {p.get('sl_atr')}× TP {p.get('tp_atr')}× ATR {p.get('atr_period')}" for s, p in v.items()) or "por defecto"
    return str(v)


def changes_text(applied: dict) -> str:
    return "\n".join(f"• <b>{LABELS.get(k, k)}</b>: {_fmt(k, v['antes'])} → {_fmt(k, v['despues'])}" for k, v in applied.items())


def _footer(acc: dict) -> str:
    return f"\n\n💰 Equidad ${acc['equity']:,.2f} · {acc['total_trades']} ops · PF {acc['profit_factor'] or '—'} · DD {acc['max_drawdown']}%"


async def run_auto_review(engine, db, store) -> dict:
    settings = await engine.get_settings()
    acc = await engine.account_summary()
    before = settings.model_dump(exclude={"bot_running"})
    await engine.log("AI_EVAL", "Revisión IA automática iniciada...")
    ctx = await build_context(engine, db, settings, acc, True)
    res = await advise("revision_automatica_programada", ctx, ai_policy(settings.risk_profile))
    applied, previous = ({}, {})
    if store.cfg.auto_review_apply:
        applied, previous = await apply_ai_changes(engine, res, before, settings)
    await store.update({"auto_review_last_at": now_iso(), "auto_review_last_summary": res["summary"], "auto_review_last_changes": applied})
    await engine.log("AI_EVAL", f"Revisión automática: {res['summary'][:160]}" + (f" · cambios: {', '.join(applied)}" if applied else " · sin cambios"))
    msg = (f"🧠 <b>Revisión IA automática</b>\n{res['summary']}\n\n"
           + (f"<b>Cambios aplicados</b>\n{changes_text(applied)}" if applied else ("<b>Sin cambios</b> en la configuración" if store.cfg.auto_review_apply else "<b>Modo solo aviso</b>: no se aplicó nada"))
           + (("\n\n" + "\n".join(f"– {n}" for n in res["notes"])) if res["notes"] else "")
           + _footer(acc))
    await notify.notify(msg, "review")
    return {**res, "applied": applied, "previous": previous, "ran_at": store.cfg.auto_review_last_at}


async def _safe_walk_forward(engine, settings, initial: float, sym: str):
    """Compact walk-forward verdict for the AI context; never breaks the global job."""
    try:
        klines = await engine.market.fetch_history(sym, settings.timeframe, WF_CANDLES)
        wf = await asyncio.to_thread(walk_forward, klines, settings.strategy, settings.risk_per_trade, settings.leverage,
                                     settings.trailing_enabled, initial, sym, settings.signal_mode, settings.disabled_strategies, settings.symbol_params.get(sym))
        out = {k: wf[k] for k in ("verdict", "verdict_text", "wfe", "oos", "baseline_oos", "is_expectancy_r", "beats_baseline", "params_stable", "params_unique")} | {"folds": len(wf["folds"])}
        if wf["applied"]:
            out["symbol_params_aplicados"] = {k: wf["applied"][k] for k in ("params", "verdict", "verdict_text", "wfe", "oos")}
        return out
    except Exception as e:
        logger.warning(f"walk-forward {sym}: {e}")
        return None


async def run_global_optimization(engine, db) -> dict:
    settings = await engine.get_settings()
    acc = await engine.account_summary()
    before = settings.model_dump(exclude={"bot_running"})
    initial = acc["initial_balance"]
    await engine.log("AI_EVAL", f"Optimización global IA iniciada · {len(settings.symbols)} pares · perfil {PROFILES[settings.risk_profile]['name']}")
    results = []
    for sym in settings.symbols:
        job["step"] = f"Optimizando {sym}"
        klines = await engine.market.fetch_klines(sym, settings.timeframe, 1000, cache_sec=300)
        res = await asyncio.to_thread(optimize, klines, settings.strategy, settings.risk_per_trade, settings.leverage,
                                      settings.trailing_enabled, initial, sym, settings.signal_mode, settings.disabled_strategies)
        job["step"] = f"Validando {sym} (walk-forward)"
        wf = await _safe_walk_forward(engine, settings, initial, sym)
        results.append({**res, "timeframe": settings.timeframe, "applied": settings.symbol_params.get(sym), "walk_forward": wf})
    job["step"] = f"{ai_label()} analizando todos los datos"
    ctx = await build_context(engine, db, settings, acc, True)
    ctx["optimizador"] = [{k: r.get(k) for k in ("symbol", "best", "baseline", "timeframe", "applied", "walk_forward")} for r in results]
    res = await advise("optimizacion_global_boton_usuario", ctx, ai_policy(settings.risk_profile))
    applied, previous = await apply_ai_changes(engine, res, before, settings)
    await engine.log("AI_EVAL", f"Optimización global: {res['summary'][:160]}" + (f" · cambios: {', '.join(applied)}" if applied else " · sin cambios"))
    msg = (f"🎯 <b>Optimización global con IA</b> (perfil {PROFILES[settings.risk_profile]['name']})\n{res['summary']}\n\n"
           + (f"<b>Cambios aplicados</b>\n{changes_text(applied)}" if applied else "<b>Sin cambios</b> en la configuración")
           + (("\n\n" + "\n".join(f"– {n}" for n in res["notes"])) if res["notes"] else "")
           + _footer(acc))
    await notify.notify(msg, "review")
    return {**res, "applied": applied, "previous": previous, "optimizer": results, "ran_at": now_iso()}


async def start_global_optimization(engine, db, runner=None, state: dict = None) -> bool:
    state = job if state is None else state
    runner = runner or run_global_optimization
    if state["status"] == "running":
        return False
    state.update(status="running", started_at=now_iso(), finished_at=None, result=None, error=None, step="Preparando")

    async def _run():
        try:
            state["result"] = await runner(engine, db)
            state["status"] = "done"
        except Exception as e:
            logger.exception("global optimization")
            state.update(status="error", error=str(e)[:300])
            await engine.log("ERROR", f"Optimización global IA falló: {str(e)[:160]}")
        finally:
            state["finished_at"] = now_iso()
            state["step"] = ""

    asyncio.create_task(_run())
    return True


def job_state(state: dict = None) -> dict:
    return dict(job if state is None else state)
