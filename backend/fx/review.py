"""'Optimizar todo con IA' for HotForex: FX optimizer + walk-forward + backtest sessions per pair → Claude decides within the FX risk profile."""
import asyncio
import logging
from models import now_iso
from performance import performance
from ai_advisor import advise, FX_MARKET
import review
from fx.models import FxSettingsUpdate
from fx.symbols import AVAILABLE
from fx.market import market_status, SESSION_NAMES
from fx.profiles import ai_policy, PROFILES
from fx.optimizer import optimize, walk_forward, WF_CANDLES
from fx.backtest import run_backtest

logger = logging.getLogger("fx.review")
ALLOWED_AI_KEYS = review.ALLOWED_AI_KEYS | {"sessions_allowed"}
job: dict = {"status": "idle", "started_at": None, "finished_at": None, "result": None, "error": None, "step": ""}


async def build_context(engine, settings, acc: dict) -> dict:
    pol = ai_policy(settings.risk_profile)
    ctx = {"mercado": "forex y metales (HFM, paper trading)", "settings_actuales": settings.model_dump(exclude={"bot_running"}), "cuenta": acc,
           "perfil_riesgo": {"nivel": pol["level"], "nombre": pol["name"], "topes_ia": pol["caps"]},
           "rendimiento_real": await performance(engine.db),
           "sesiones": {"ahora": market_status()["sessions"], "permitidas": settings.sessions_allowed or "todas", "ids": SESSION_NAMES}}
    ctx["rendimiento_real"].pop("shadow", None)
    if engine.news and engine.news.latest:
        ctx["noticias"] = {"mercado": engine.news.latest["market"], "alertas": engine.news.latest.get("alerts", [])[:5]}
    wf_latest = await engine.db.wf_checks.find_one({"_id": "latest"}, {"_id": 0, "ran_at": 1, "results": 1})
    if wf_latest and wf_latest.get("results"):
        ctx["walk_forward_pares_aplicados"] = {"revisado": wf_latest["ran_at"], "pares": {s: {k: r[k] for k in ("verdict", "wfe", "oos", "previous_verdict")}
                                                                                       for s, r in wf_latest["results"].items()},
                                               "_explicacion": "Revalidación walk-forward de los pares con symbol_params aplicados; SOBREAJUSTADO/NO_RENTABLE = quitar sus symbol_params."}
    return ctx


async def _safe_walk_forward(engine, settings, initial: float, sym: str):
    try:
        klines = await engine.market.fetch_klines(sym, settings.timeframe, WF_CANDLES, cache_sec=600)
        wf = await asyncio.to_thread(walk_forward, klines, settings, initial, sym, dict(engine.market.tickers))
        out = {k: wf[k] for k in ("verdict", "verdict_text", "wfe", "oos", "baseline_oos", "is_expectancy_r", "beats_baseline", "params_stable", "params_unique")} | {"folds": len(wf["folds"])}
        if wf["applied"]:
            out["symbol_params_aplicados"] = {k: wf["applied"][k] for k in ("params", "verdict", "verdict_text", "wfe", "oos")}
        return out
    except Exception as e:
        logger.warning(f"fx walk-forward {sym}: {e}")
        return None


async def run_global_optimization(engine, db) -> dict:
    settings = await engine.get_settings()
    acc = await engine.account_summary()
    before = settings.model_dump(exclude={"bot_running"})
    initial = acc["initial_balance"]
    tickers = dict(engine.market.tickers)
    await engine.log("AI_EVAL", f"Optimización global IA iniciada · {len(settings.symbols)} pares · perfil {PROFILES[settings.risk_profile]['name']}")
    results = []
    for sym in settings.symbols:
        job["step"] = f"Optimizando {sym}"
        klines = await engine.market.fetch_klines(sym, settings.timeframe, 1000, cache_sec=300)
        res = await asyncio.to_thread(optimize, klines, settings, initial, sym, tickers)
        bt = await asyncio.to_thread(run_backtest, klines, settings.strategy, settings.risk_per_trade, settings.leverage, settings.trailing_enabled, initial,
                                     sym, settings.signal_mode, settings.disabled_strategies, tickers, settings.min_lot_max_risk, settings.close_before_weekend)
        job["step"] = f"Validando {sym} (walk-forward)"
        wf = await _safe_walk_forward(engine, settings, initial, sym)
        results.append({**res, "timeframe": settings.timeframe, "applied": settings.symbol_params.get(sym), "walk_forward": wf,
                        "session_stats": bt["session_stats"], "rejected_lot": bt["rejected_lot"]})
    job["step"] = "Claude analizando todos los datos"
    ctx = await build_context(engine, settings, acc)
    ctx["optimizador"] = [{k: r.get(k) for k in ("symbol", "best", "baseline", "timeframe", "applied", "walk_forward", "session_stats", "rejected_lot")} for r in results]
    ctx["optimizador_explicacion"] = ("session_stats = operaciones del backtest (sin filtro de sesión) agrupadas por la sesión abierta al entrar; "
                                      "rejected_lot = señales sin operar porque el lote mínimo 0.01 arriesgaba más que min_lot_max_risk.")
    res = await advise("optimizacion_global_boton_usuario", ctx, ai_policy(settings.risk_profile), FX_MARKET)
    applied, previous = await review.apply_ai_changes(engine, res, before, settings, policy=ai_policy(settings.risk_profile), available=AVAILABLE,
                                                      model=FxSettingsUpdate, allowed=ALLOWED_AI_KEYS)
    await engine.log("AI_EVAL", f"Optimización global: {res['summary'][:160]}" + (f" · cambios: {', '.join(applied)}" if applied else " · sin cambios"))
    await engine.tg(f"🎯 <b>Optimización global con IA</b> (perfil {PROFILES[settings.risk_profile]['name']})\n{res['summary']}\n\n"
                    + (f"<b>Cambios aplicados</b>\n{review.changes_text(applied)}" if applied else "<b>Sin cambios</b> en la configuración")
                    + (("\n\n" + "\n".join(f"– {n}" for n in res["notes"])) if res["notes"] else "")
                    + review._footer(acc), "review")
    return {**res, "applied": applied, "previous": previous, "optimizer": results, "ran_at": now_iso()}


async def start(engine, db) -> bool:
    return await review.start_global_optimization(engine, db, runner=run_global_optimization, state=job)


def job_state() -> dict:
    return review.job_state(job)
