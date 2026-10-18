from datetime import datetime
import numpy as np
from backtest import run_backtest
from indicators import build_df

WITHDRAW_PCT = 80
GROWTH_CAP = 5000.0
SCENARIOS = {
    "conservador": {"name": "Conservador", "rate": 2.5, "desc": "≈34% anual · lo que sostienen los fondos sistemáticos consistentes"},
    "base": {"name": "Base", "rate": 4.0, "desc": "≈60% anual · bot con profit factor > 1.3 operando a 3x"},
    "optimista": {"name": "Optimista", "rate": 6.0, "desc": "≈100% anual · solo en rachas de tendencia fuerte, no sostenible"},
}
PHASE_INFO = {
    "semilla": {"name": "Capital semilla", "risk": 1.0,
                "rule": "Reinvertir el 100% de la ganancia. Cero retiros. Riesgo 1% por operación.",
                "advance": "Duplicar el capital inicial manteniendo el drawdown por debajo del 12%."},
    "crecimiento": {"name": "Crecimiento", "risk": 1.0,
                    "rule": "Seguir reinvirtiendo el 100%. Los aportes mensuales aceleran más esta fase que cualquier ajuste.",
                    "advance": "Llegar a $5.000 con profit factor ≥ 1.3 en al menos 100 operaciones."},
    "consolidacion": {"name": "Consolidación", "risk": 1.5,
                      "rule": "Subir el riesgo a 1.5% por operación (métricas ya probadas). Reinvertir el 100%.",
                      "advance": "Alcanzar el capital objetivo que genera la meta mensual."},
    "ingreso": {"name": "Ingreso mensual", "risk": 1.5,
                "rule": f"Retirar el {WITHDRAW_PCT}% de la ganancia de cada mes; el {100 - WITHDRAW_PCT}% se queda como colchón para meses negativos.",
                "advance": "Meta cumplida. Si el drawdown supera el 15%, volver a riesgo 1% y pausar retiros."},
}


def _phase(capital: float, initial: float, target_capital: float) -> str:
    if capital >= target_capital:
        return "ingreso"
    if capital >= max(GROWTH_CAP, 2 * initial):
        return "consolidacion"
    if capital >= 2 * initial:
        return "crecimiento"
    return "semilla"


def project(initial: float, rate_pct: float, target_monthly: float, deposit: float = 0.0, max_months: int = 360) -> dict:
    rate = rate_pct / 100
    base = {"rate_pct": rate_pct, "reachable": False, "months": None, "target_capital": None,
            "income_at_target": None, "total_deposited": 0, "series": [], "timeline": []}
    if rate <= 0:
        return base
    final_rate = rate * PHASE_INFO["ingreso"]["risk"]
    target_capital = target_monthly / (final_rate * WITHDRAW_PCT / 100)
    capital, series, timeline, reached, deposited = initial, [], [], None, 0.0
    for month in range(1, max_months + 1):
        key = _phase(capital, initial, target_capital)
        if not timeline or timeline[-1]["key"] != key:
            timeline.append({"key": key, **PHASE_INFO[key], "start_month": month - 1, "start_capital": round(capital, 2)})
        if key == "ingreso" and reached is None:
            reached = month - 1
        profit = capital * rate * PHASE_INFO[key]["risk"]
        withdraw = profit * WITHDRAW_PCT / 100 if key == "ingreso" else 0.0
        dep = 0.0 if key == "ingreso" else deposit
        capital += profit - withdraw + dep
        deposited += dep
        series.append({"month": month, "capital": round(capital, 2), "profit": round(profit, 2),
                       "withdraw": round(withdraw, 2), "phase": key})
        if reached is not None and month >= reached + 12:
            break
    return {**base, "reachable": reached is not None, "months": reached, "target_capital": round(target_capital, 2),
            "income_at_target": round(target_capital * final_rate * WITHDRAW_PCT / 100, 2),
            "total_deposited": round(deposited, 2), "series": series, "timeline": timeline}


def monte_carlo(r_multiples: list, trades_per_month: float, risk_pct: float, sims: int = 3000, months: int = 12):
    R = np.array(r_multiples, dtype=float)
    if len(R) < 10 or trades_per_month <= 0:
        return None
    rng = np.random.default_rng(42)
    counts = rng.poisson(trades_per_month, (sims, months))
    kmax = int(counts.max())
    samples = rng.choice(R, size=(sims, months, kmax))
    mask = np.arange(kmax)[None, None, :] < counts[..., None]
    logret = np.log1p(np.clip(risk_pct / 100 * samples, -0.95, None)) * mask
    monthly = np.expm1(logret.sum(-1))
    eq = np.cumprod(1 + monthly, axis=1)
    peak = np.maximum.accumulate(np.concatenate([np.ones((sims, 1)), eq], axis=1), axis=1)[:, 1:]
    dd = ((peak - eq) / peak).max(axis=1)
    m = monthly.ravel()
    p = lambda a, q: round(float(np.percentile(a, q)) * 100, 2)  # noqa: E731
    return {
        "sims": sims, "monthly_p10": p(m, 10), "monthly_p25": p(m, 25), "monthly_median": p(m, 50),
        "monthly_p75": p(m, 75), "monthly_p90": p(m, 90), "prob_positive_month": round(float((m > 0).mean()) * 100, 1),
        "annual_median": p(eq[:, -1] - 1, 50), "annual_p10": p(eq[:, -1] - 1, 10), "annual_p90": p(eq[:, -1] - 1, 90),
        "prob_loss_year": round(float((eq[:, -1] < 1).mean()) * 100, 1),
        "prob_dd_over_15": round(float((dd > 0.15).mean()) * 100, 1),
        "prob_dd_over_25": round(float((dd > 0.25).mean()) * 100, 1),
        "median_max_dd": round(float(np.median(dd)) * 100, 2),
    }


async def backtest_stats(fetch_klines, settings, initial: float) -> dict:
    per_symbol, agg, R, days = [], {}, [], 0.0
    for sym in settings.symbols:
        params = settings.symbol_params.get(sym) or {}
        df = build_df(await fetch_klines(sym, settings.timeframe, 1000, cache_sec=300), int(params.get("atr_period", 14)))
        res = run_backtest(df, settings.strategy, settings.risk_per_trade, settings.leverage, settings.trailing_enabled, initial, sym, params)
        R += res["r_multiples"]
        per_symbol.append({"symbol": sym, "return_pct": res["return_pct"], "trades": res["total_trades"],
                           "win_rate": res["win_rate"], "profit_factor": res["profit_factor"],
                           "expectancy_r": res["expectancy_r"], "max_drawdown": res["max_drawdown"],
                           "rejected_lot": res["rejected_lot"]})
        for k, s in res["strategy_stats"].items():
            a = agg.setdefault(k, {"trades": 0, "wins": 0, "pnl": 0.0, "r_sum": 0.0, "gw": 0.0, "gl": 0.0})
            for f in a:
                a[f] += s[f]
        if res["period_start"]:
            days = (datetime.fromisoformat(res["period_end"]) - datetime.fromisoformat(res["period_start"])).total_seconds() / 86400
    months = max(days / 30.44, 0.1)
    concurrency = min(1.0, settings.max_positions / max(len(settings.symbols), 1))
    trades_per_month = len(R) / months * concurrency
    by_strategy = [{"strategy": k, "trades": a["trades"], "win_rate": round(a["wins"] / a["trades"] * 100, 1),
                    "pnl": round(a["pnl"], 2), "expectancy_r": round(a["r_sum"] / a["trades"], 3),
                    "profit_factor": round(a["gw"] / a["gl"], 2) if a["gl"] else None}
                   for k, a in agg.items() if a["trades"]]
    return {
        "days": round(days, 1), "timeframe": settings.timeframe, "strategy": settings.strategy,
        "total_trades": len(R), "trades_per_month": round(trades_per_month, 1), "concurrency_factor": round(concurrency, 2),
        "expectancy_r": round(float(np.mean(R)), 3) if R else 0,
        "win_rate": round(float(np.mean(np.array(R) > 0)) * 100, 1) if R else 0,
        "per_symbol": sorted(per_symbol, key=lambda x: -x["return_pct"]),
        "by_strategy": sorted(by_strategy, key=lambda x: -x["pnl"]),
        "monte_carlo": monte_carlo(R, trades_per_month, settings.risk_per_trade),
    }


def build_plan(req: dict, bt: dict) -> dict:
    mc = bt.get("monte_carlo")
    rates = {k: v["rate"] for k, v in SCENARIOS.items()}
    rates["backtest"] = round(mc["monthly_median"], 2) if mc else None
    scenarios = []
    for key, rate in rates.items():
        info = SCENARIOS.get(key, {"name": "Según backtest", "desc": "Mediana Monte Carlo de tus propias estrategias sobre los últimos datos reales"})
        pr = project(req["initial_capital"], rate, req["target_monthly"], req["monthly_deposit"]) if rate is not None else project(req["initial_capital"], 0, req["target_monthly"])
        scenarios.append({"key": key, "name": info["name"], "desc": info["desc"], "rate_pct": rate,
                          "reachable": pr["reachable"], "months": pr["months"], "target_capital": pr["target_capital"],
                          "income_at_target": pr["income_at_target"], "total_deposited": pr["total_deposited"]})
    sel = req["scenario"] if rates.get(req["scenario"]) is not None else "base"
    return {"inputs": req, "scenarios": scenarios, "selected": sel,
            "projection": project(req["initial_capital"], rates[sel], req["target_monthly"], req["monthly_deposit"]),
            "backtest": bt, "phase_info": PHASE_INFO, "withdraw_pct": WITHDRAW_PCT}


PHASE_ORDER = ["validacion", "semilla", "crecimiento", "consolidacion", "ingreso"]
PHASE_NAMES = {"validacion": "Validación en paper", **{k: v["name"] for k, v in PHASE_INFO.items()}}


def _crit(label, value, target, kind="min", fmt="num"):
    met = value >= target if kind == "min" else value <= target
    if kind == "min":
        pct = 100 if met else (value / target * 100 if target else 0)
    else:
        pct = 100 if met else (target / value * 100 if value else 100)
    return {"label": label, "value": round(float(value), 2), "target": target, "kind": kind, "fmt": fmt,
            "met": bool(met), "pct": round(max(0.0, min(100.0, float(pct))), 1)}


def phase_criteria(key: str, s: dict, acc: dict, last30: dict, settings, target_capital: float, days: int) -> list:
    pf = s["profit_factor"] if s["profit_factor"] is not None else (9.99 if s["realized_pnl"] > 0 else 0)
    initial = acc["initial_balance"]
    if key == "validacion":
        return [_crit("Operaciones cerradas", s["total_trades"], 60), _crit("Profit factor", pf, 1.3),
                _crit("Drawdown máximo (%)", s["max_drawdown"], 10, "max", "pct"), _crit("Días operando", days, 28)]
    if key == "semilla":
        return [_crit("Equidad (USDT)", s["equity"], round(2 * initial, 2), fmt="usd"),
                _crit("Drawdown máximo (%)", s["max_drawdown"], 12, "max", "pct")]
    if key == "crecimiento":
        return [_crit("Equidad (USDT)", s["equity"], round(max(GROWTH_CAP, 2 * initial), 2), fmt="usd"),
                _crit("Profit factor", pf, 1.3), _crit("Operaciones cerradas", s["total_trades"], 100)]
    if key == "consolidacion":
        return [_crit("Equidad (USDT)", s["equity"], round(target_capital, 2), fmt="usd")]
    return [_crit("Ganancia últimos 30 días (USDT)", last30["pnl"], settings.plan_target_monthly, fmt="usd"),
            _crit("Drawdown máximo (%)", s["max_drawdown"], 15, "max", "pct")]


def build_checkin(s: dict, acc: dict, last30: dict, settings, rate_pct: float, days: int) -> dict:
    rate = rate_pct / 100 if rate_pct and rate_pct > 0 else SCENARIOS["base"]["rate"] / 100
    target_capital = settings.plan_target_monthly / (rate * PHASE_INFO["ingreso"]["risk"] * WITHDRAW_PCT / 100)
    cur = PHASE_ORDER[min(settings.plan_phase, len(PHASE_ORDER) - 1)]
    phases = []
    for i, key in enumerate(PHASE_ORDER):
        crit = phase_criteria(key, s, acc, last30, settings, target_capital, days)
        status = "done" if i < settings.plan_phase else "current" if i == settings.plan_phase else "pending"
        phases.append({"key": key, "index": i, "name": PHASE_NAMES[key], "status": status, "criteria": crit,
                       "met": sum(c["met"] for c in crit), "total": len(crit),
                       "risk": PHASE_INFO.get(key, {}).get("risk", 1.0)})
    current = phases[settings.plan_phase]
    ready = current["met"] == current["total"] and settings.plan_phase < len(PHASE_ORDER) - 1
    goal_met = current["met"] == current["total"] and settings.plan_phase == len(PHASE_ORDER) - 1
    warnings = []
    if s["max_drawdown"] > 15:
        warnings.append(f"Drawdown {s['max_drawdown']:.1f}% supera el 15%: reduce el riesgo a 1% y pausa retiros.")
    if s["total_trades"] >= 30 and s["profit_factor"] is not None and s["profit_factor"] < 1:
        warnings.append(f"Profit factor {s['profit_factor']} < 1 tras {s['total_trades']} operaciones: el sistema pierde dinero, revisa estrategias y pares.")
    if s["daily_paused"]:
        warnings.append("Límite de pérdida diaria alcanzado hoy: el bot no abrirá nuevas posiciones hasta mañana.")
    nxt = PHASE_NAMES[PHASE_ORDER[settings.plan_phase + 1]] if ready else None
    if goal_met:
        message = f"Meta cumplida: {fmt_usd(last30['pnl'])} en los últimos 30 días. Mantén el plan de retiros del {WITHDRAW_PCT}%."
    elif ready:
        message = f"Cumples los {current['total']} criterios de «{current['name']}». Puedes avanzar a «{nxt}»."
    else:
        message = f"Fase actual: {current['name']} · {current['met']} de {current['total']} criterios cumplidos."
    return {"phase": settings.plan_phase, "phase_key": cur, "phase_name": current["name"], "ready_to_advance": ready,
            "goal_met": goal_met, "next_phase_name": nxt, "next_phase_risk": phases[settings.plan_phase + 1]["risk"] if ready else None,
            "message": message, "phases": phases, "warnings": warnings, "days_running": days,
            "target_capital": round(target_capital, 2), "last_30d": last30}


def fmt_usd(v: float) -> str:
    return f"${v:,.2f}"
