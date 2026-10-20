import math
import numpy as np
from indicators import build_df
from backtest import scan_signals, simulate, _iso

SL_GRID = [1.0, 1.5, 2.0, 2.5, 3.0]
TP_GRID = [2.0, 3.0, 4.0, 5.0, 6.0]
ATR_GRID = [10, 14, 20]
MIN_RR = 1.5
MIN_TRADES = 10
METRIC_KEYS = ("return_pct", "total_trades", "win_rate", "profit_factor", "max_drawdown", "expectancy_r", "sqn", "rejected_lot")
WF_OOS = 250
WF_IS_MIN = 600
WF_CANDLES = 2000
WF_MIN_OOS_TRADES = 10
VERDICTS = {
    "ROBUSTO": "Los parámetros optimizados mantienen la ventaja fuera de muestra: la optimización es fiable en este par.",
    "DUDOSO": "Fuera de muestra sigue ganando pero bastante menos que in-sample: aplica el óptimo con cautela y vuelve a validar.",
    "SOBREAJUSTADO": "In-sample gana pero fuera de muestra pierde: el óptimo está sobreajustado al pasado. No apliques symbol_params en este par.",
    "NO_RENTABLE": "Ni in-sample ni fuera de muestra son rentables: el problema es el par/estrategia, no los parámetros. Considera desactivarlo.",
    "INSUFICIENTE": "Muy pocas operaciones fuera de muestra para concluir nada: espera más historial o usa un marco temporal menor.",
}


def _metrics(res: dict) -> dict:
    m = {k: res[k] for k in METRIC_KEYS}
    m["trades"] = m.pop("total_trades")
    return m


def _prepare(klines: list, strategy: str, mode: str, disabled):
    dfs = {ap: build_df(klines, ap) for ap in ATR_GRID}
    sigs = {ap: scan_signals(dfs[ap], strategy, None, mode, disabled) for ap in ATR_GRID}
    return dfs, sigs


def _search(dfs, sigs, risk_pct, leverage, trailing, initial, symbol, start=210, end=None):
    rows = []
    for ap in ATR_GRID:
        for sl in SL_GRID:
            for tp in TP_GRID:
                if tp < sl * MIN_RR:
                    continue
                res = simulate(dfs[ap], sigs[ap], risk_pct, leverage, trailing, initial, symbol, sl, tp, start, end)
                rows.append({"atr_period": ap, "sl_atr": sl, "tp_atr": tp, **_metrics(res)})
    idx = {(r["atr_period"], r["sl_atr"], r["tp_atr"]): r for r in rows}
    for r in rows:
        i, j = SL_GRID.index(r["sl_atr"]), TP_GRID.index(r["tp_atr"])
        neigh = [idx.get((r["atr_period"], SL_GRID[a], TP_GRID[b]))
                 for a in (i - 1, i, i + 1) for b in (j - 1, j, j + 1)
                 if 0 <= a < len(SL_GRID) and 0 <= b < len(TP_GRID)]
        neigh = [x for x in neigh if x]
        r["robust"] = round(sum(x["sqn"] for x in neigh) / len(neigh), 3)
        r["neighbors"] = len(neigh)
    valid = [r for r in rows if r["trades"] >= MIN_TRADES] or [r for r in rows if r["trades"] >= 5]
    best = max(valid, key=lambda r: (r["robust"], r["sqn"])) if valid else None
    return rows, best


def optimize(klines: list, strategy: str, risk_pct: float, leverage: int, trailing: bool, initial: float, symbol: str,
             mode: str = "strict", disabled=()) -> dict:
    dfs, sigs = _prepare(klines, strategy, mode, disabled)
    rows, best = _search(dfs, sigs, risk_pct, leverage, trailing, initial, symbol)
    base_res = simulate(dfs[14], sigs[14], risk_pct, leverage, trailing, initial, symbol)
    return {
        "symbol": symbol, "strategy": strategy, "candles": len(klines),
        "period_start": base_res["period_start"], "period_end": base_res["period_end"],
        "sl_grid": SL_GRID, "tp_grid": TP_GRID, "atr_grid": ATR_GRID, "min_rr": MIN_RR,
        "grid": rows, "best": best, "baseline": _metrics(base_res), "combos": len(rows),
    }


def _r_stats(R: list) -> dict:
    arr = np.array(R, dtype=float)
    n = len(arr)
    wins, losses = arr[arr > 0], arr[arr <= 0]
    sqn = float(arr.mean() / arr.std() * math.sqrt(n)) if n > 1 and arr.std() > 0 else 0.0
    return {"trades": n, "win_rate": round(len(wins) / n * 100, 1) if n else 0, "expectancy_r": round(float(arr.mean()), 3) if n else 0,
            "sqn": round(sqn, 2), "total_r": round(float(arr.sum()), 2),
            "profit_factor": round(float(wins.sum() / abs(losses.sum())), 2) if losses.sum() else (round(float(wins.sum()), 2) if n else 0)}


def _max_dd(curve: list) -> float:
    peak, dd = 0.0, 0.0
    for p in curve:
        peak = max(peak, p["equity"])
        dd = max(dd, (peak - p["equity"]) / peak * 100 if peak else 0)
    return round(dd, 2)


def _thin(curve: list, limit: int = 240) -> list:
    step = max(1, math.ceil(len(curve) / limit))
    return curve[::step] + ([curve[-1]] if curve and (len(curve) - 1) % step else [])


def _verdict(oos: dict, base: dict, is_exp: float, wfe) -> str:
    if oos["trades"] < WF_MIN_OOS_TRADES:
        return "INSUFICIENTE"
    if oos["expectancy_r"] > 0 and oos["profit_factor"] >= 1.1 and (wfe is None or wfe >= 0.5):
        return "ROBUSTO"
    if oos["expectancy_r"] > 0:
        return "DUDOSO"
    return "SOBREAJUSTADO" if is_exp > 0 else "NO_RENTABLE"


def walk_forward(klines: list, strategy: str, risk_pct: float, leverage: int, trailing: bool, initial: float, symbol: str,
                 mode: str = "strict", disabled=()) -> dict:
    n = len(klines)
    is_len = max(WF_IS_MIN, min(1000, n // 2))
    splits = list(range(is_len, n - WF_OOS + 1, WF_OOS))
    dfs, sigs = _prepare(klines, strategy, mode, disabled)
    ts = dfs[14]["ts"].values
    iso = lambda i: _iso(ts[i])  # noqa: E731
    folds, curve, base_curve, R, base_R, is_R = [], [], [], [], [], []
    bal, base_bal = initial, initial
    for k, split in enumerate(splits):
        is_start, oos_end = max(210, split - is_len), min(n, split + WF_OOS)
        _, best = _search(dfs, sigs, risk_pct, leverage, trailing, initial, symbol, is_start, split)
        ap, sl, tp = (best["atr_period"], best["sl_atr"], best["tp_atr"]) if best else (14, None, None)
        oos = simulate(dfs[ap], sigs[ap], risk_pct, leverage, trailing, bal, symbol, sl, tp, split, oos_end)
        base = simulate(dfs[14], sigs[14], risk_pct, leverage, trailing, base_bal, symbol, None, None, split, oos_end)
        bal, base_bal = oos["final_equity"], base["final_equity"]
        curve += oos["equity_curve"]
        base_curve += base["equity_curve"]
        R += oos["r_multiples"]
        base_R += base["r_multiples"]
        if best:
            is_R += [best["expectancy_r"]] * best["trades"]
        folds.append({"fold": k + 1, "is_start": iso(is_start), "split": iso(split), "oos_end": iso(oos_end - 1),
                      "is_candles": split - is_start, "oos_candles": oos_end - split, "params": {"sl_atr": sl, "tp_atr": tp, "atr_period": ap} if best else None,
                      "is": best, "oos": _metrics(oos), "baseline_oos": _metrics(base)})
    oos_stats = {**_r_stats(R), "return_pct": round((bal - initial) / initial * 100, 2), "max_drawdown": _max_dd(curve)}
    base_stats = {**_r_stats(base_R), "return_pct": round((base_bal - initial) / initial * 100, 2), "max_drawdown": _max_dd(base_curve)}
    is_exp = round(float(np.mean(is_R)), 3) if is_R else 0.0
    wfe = round(oos_stats["expectancy_r"] / is_exp, 2) if is_exp > 0 else None
    verdict = _verdict(oos_stats, base_stats, is_exp, wfe) if splits else "INSUFICIENTE"
    combos = {(f["params"]["sl_atr"], f["params"]["tp_atr"], f["params"]["atr_period"]) for f in folds if f["params"]}
    return {
        "symbol": symbol, "strategy": strategy, "candles": n, "is_len": is_len, "oos_len": WF_OOS, "folds": folds,
        "period_start": iso(210) if n > 210 else None, "period_end": iso(n - 1), "oos_start": iso(splits[0]) if splits else None,
        "oos": oos_stats, "baseline_oos": base_stats, "is_expectancy_r": is_exp, "wfe": wfe,
        "beats_baseline": oos_stats["expectancy_r"] > base_stats["expectancy_r"] and oos_stats["return_pct"] >= base_stats["return_pct"],
        "params_unique": len(combos), "params_stable": bool(folds) and len(combos) <= max(1, math.ceil(len(folds) / 2)),
        "verdict": verdict, "verdict_text": VERDICTS[verdict],
        "oos_curve": _thin(curve), "baseline_curve": _thin(base_curve),
    }
