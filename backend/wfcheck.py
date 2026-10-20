import asyncio
import logging
from models import now_iso
from optimizer import walk_forward, WF_CANDLES
import notify

logger = logging.getLogger("wfcheck")
BAD = ("SOBREAJUSTADO", "NO_RENTABLE")
ICON = {"ROBUSTO": "✅", "DUDOSO": "🟡", "SOBREAJUSTADO": "⚠️", "NO_RENTABLE": "⚠️", "INSUFICIENTE": "⏳"}
job = {"status": "idle", "step": "", "started_at": None, "finished_at": None, "error": None}


def job_state() -> dict:
    return dict(job)


def _compact(wf: dict, params: dict, previous: str | None) -> dict:
    pick = ("trades", "expectancy_r", "profit_factor", "return_pct", "win_rate")
    a = wf["applied"] or wf
    return {"verdict": a["verdict"], "verdict_text": a["verdict_text"], "wfe": a["wfe"], "is_expectancy_r": a["is_expectancy_r"],
            "oos": {k: a["oos"][k] for k in pick}, "baseline_oos": {k: wf["baseline_oos"][k] for k in pick}, "process_verdict": wf["verdict"],
            "folds": len(wf["folds"]), "params": params, "previous_verdict": previous, "changed": previous is not None and previous != a["verdict"]}


def _line(sym: str, r: dict) -> str:
    o, p = r["oos"], r["params"]
    prev = f" (antes {r['previous_verdict']})" if r["changed"] else ""
    wfe = f" · WFE {r['wfe']:.2f}" if r["wfe"] is not None else ""
    return (f"{ICON.get(r['verdict'], '•')} <b>{sym.replace('USDT', '')}</b> SL {p.get('sl_atr')}× TP {p.get('tp_atr')}× ATR {int(p.get('atr_period') or 14)} · "
            f"{r['verdict']}{prev}{wfe} · OOS {o['expectancy_r']:+.2f}R en {o['trades']} ops (base {r['baseline_oos']['expectancy_r']:+.2f}R)")


async def run_check(engine, db, source: str = "auto") -> dict:
    settings = await engine.get_settings()
    acc = await db.account.find_one({"_id": "main"}, {"initial_balance": 1})
    prev = (await db.wf_checks.find_one({"_id": "latest"}) or {}).get("results", {})
    symbols = [s for s in settings.symbols if s in settings.symbol_params]
    results = {}
    for sym in symbols:
        job["step"] = f"Validando {sym}"
        klines = await engine.market.fetch_history(sym, settings.timeframe, WF_CANDLES)
        wf = await asyncio.to_thread(walk_forward, klines, settings.strategy, settings.risk_per_trade, settings.leverage,
                                     settings.trailing_enabled, acc["initial_balance"], sym, settings.signal_mode, settings.disabled_strategies,
                                     settings.symbol_params[sym])
        results[sym] = _compact(wf, settings.symbol_params[sym], prev.get(sym, {}).get("verdict"))
    doc = {"ran_at": now_iso(), "source": source, "timeframe": settings.timeframe, "checked": symbols, "results": results}
    await db.wf_checks.update_one({"_id": "latest"}, {"$set": doc}, upsert=True)
    bad = [s for s, r in results.items() if r["verdict"] in BAD]
    if not symbols:
        await engine.log("PLAN", "Walk-forward semanal: ningún par tiene SL/TP optimizados aplicados · nada que revalidar")
        return doc
    await engine.log("PLAN", f"Walk-forward {'semanal' if source == 'auto' else 'manual'} · {len(symbols)} pares con SL/TP aplicados · "
                             + ", ".join(f"{s.replace('USDT', '')} {results[s]['verdict']}" for s in symbols))
    head = (f"⚠️ <b>Walk-forward: {len(bad)} par{'es' if len(bad) > 1 else ''} sobreajustado{'s' if len(bad) > 1 else ''}</b>" if bad
            else "🧪 <b>Walk-forward semanal · todo en orden</b>")
    msg = head + f"\nRevalidación de {len(symbols)} pares con SL/TP optimizados · {settings.timeframe}\n\n" + "\n".join(_line(s, results[s]) for s in symbols)
    if bad:
        msg += ("\n\n<b>Recomendación</b>: los parámetros optimizados de " + ", ".join(s.replace("USDT", "") for s in bad)
                + " ya no se sostienen fuera de muestra. Quítalos en Optimizador → «Volver a valores por defecto» o deja que la revisión IA lo decida.")
    await notify.notify(msg, "review")
    return doc


async def start_check(engine, db, source: str = "manual") -> bool:
    if job["status"] == "running":
        return False
    job.update(status="running", started_at=now_iso(), finished_at=None, error=None, step="Preparando")

    async def _run():
        try:
            await run_check(engine, db, source)
            job["status"] = "done"
        except Exception as e:
            logger.exception("walk-forward check")
            job.update(status="error", error=str(e)[:300])
            await engine.log("ERROR", f"Revalidación walk-forward falló: {str(e)[:160]}")
            if source == "auto":
                await notify.notify(f"⚠️ <b>Revalidación walk-forward falló</b>\n{str(e)[:300]}", "review")
        finally:
            job["finished_at"] = now_iso()
            job["step"] = ""

    asyncio.create_task(_run())
    return True


async def latest(db):
    return await db.wf_checks.find_one({"_id": "latest"}, {"_id": 0})
