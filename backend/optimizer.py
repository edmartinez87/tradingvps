from indicators import build_df
from backtest import scan_signals, simulate, run_backtest

SL_GRID = [1.0, 1.5, 2.0, 2.5, 3.0]
TP_GRID = [2.0, 3.0, 4.0, 5.0, 6.0]
ATR_GRID = [10, 14, 20]
MIN_RR = 1.5
MIN_TRADES = 10
METRIC_KEYS = ("return_pct", "total_trades", "win_rate", "profit_factor", "max_drawdown", "expectancy_r", "sqn", "rejected_lot")


def _metrics(res: dict) -> dict:
    m = {k: res[k] for k in METRIC_KEYS}
    m["trades"] = m.pop("total_trades")
    return m


def optimize(klines: list, strategy: str, risk_pct: float, leverage: int, trailing: bool, initial: float, symbol: str) -> dict:
    rows = []
    for ap in ATR_GRID:
        df = build_df(klines, ap)
        sigs = scan_signals(df, strategy)
        for sl in SL_GRID:
            for tp in TP_GRID:
                if tp < sl * MIN_RR:
                    continue
                res = simulate(df, sigs, risk_pct, leverage, trailing, initial, symbol, sl, tp)
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
    base_res = run_backtest(build_df(klines, 14), strategy, risk_pct, leverage, trailing, initial, symbol)
    return {
        "symbol": symbol, "strategy": strategy, "candles": len(klines),
        "period_start": base_res["period_start"], "period_end": base_res["period_end"],
        "sl_grid": SL_GRID, "tp_grid": TP_GRID, "atr_grid": ATR_GRID, "min_rr": MIN_RR,
        "grid": rows, "best": best, "baseline": _metrics(base_res), "combos": len(rows),
    }
