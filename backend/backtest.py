from datetime import datetime, timezone
import numpy as np
from strategies import evaluate
from risk import FEE_RATE, position_size, pnl, check_exit, update_trailing


def _iso(ts_ms) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()


def scan_signals(df, strategy: str, params: dict = None, mode: str = "strict", disabled=()) -> dict:
    """Signal detection is independent of SL/TP → scan once, simulate many times."""
    out, used = {}, set()
    for i in range(210, len(df)):
        sig = evaluate(df, i, strategy, None, params, mode, disabled)
        if sig and (sig["strategy"], sig["key_ts"]) not in used:
            used.add((sig["strategy"], sig["key_ts"]))
            out[i] = sig
    return out


def _levels(sig, sl_atr, tp_atr):
    if sl_atr is None:
        return sig["sl"], sig["tp"]
    long, p, atr = sig["side"] == "long", sig["price"], sig["atr"]
    sl = p - sl_atr * atr if long else p + sl_atr * atr
    if sig.get("tp_mode") == "fixed":
        tp = sig["tp"]
        if abs(tp - p) < abs(p - sl):
            return None, None
    else:
        tp = p + tp_atr * atr if long else p - tp_atr * atr
    return sl, tp


def simulate(df, signals: dict, risk_pct: float, leverage: int, trailing: bool, initial: float,
             symbol: str = None, sl_atr: float = None, tp_atr: float = None, start: int = 210, end: int = None) -> dict:
    highs, lows, closes, ts = df["high"].values, df["low"].values, df["close"].values, df["ts"].values
    balance, peak, max_dd = initial, initial, 0.0
    trades, curve, pos, rejected = [], [], None, 0
    n = len(df)
    end = end or n
    for i in range(start, end):
        if pos:
            price, reason = check_exit(pos["side"], pos["sl"], pos["tp"], highs[i], lows[i])
            if price is not None:
                if reason == "SL" and pos["be"]:
                    reason = "TRAILING"
                fee = price * pos["qty"] * FEE_RATE
                gross = pnl(pos["side"], pos["entry"], price, pos["qty"])
                net = gross - pos["fee"] - fee
                balance += gross - fee
                trades.append({"side": pos["side"], "strategy": pos["strategy"], "entry": pos["entry"], "exit": float(price),
                               "pnl": round(float(net), 2), "r": round(float(net / pos["risk_amt"]), 3), "reason": reason,
                               "opened_at": pos["opened_at"], "closed_at": _iso(ts[i])})
                pos = None
            elif trailing:
                pos["sl"], pos["be"] = update_trailing(pos["side"], pos["entry"], pos["sl"], pos["init_sl"], pos["atr"], closes[i])
        if not pos and i in signals:
            sig = signals[i]
            sl, tp = _levels(sig, sl_atr, tp_atr)
            if sl is not None:
                qty, _ = position_size(balance, balance, risk_pct, sig["price"], sl, leverage, symbol)
                if qty > 0:
                    fee = sig["price"] * qty * FEE_RATE
                    balance -= fee
                    pos = {"side": sig["side"], "strategy": sig["strategy"], "entry": sig["price"], "sl": sl, "init_sl": sl,
                           "tp": tp, "atr": sig["atr"], "qty": qty, "fee": fee, "risk_amt": qty * abs(sig["price"] - sl),
                           "be": False, "opened_at": _iso(ts[i])}
                else:
                    rejected += 1
        equity = balance + (pnl(pos["side"], pos["entry"], closes[i], pos["qty"]) if pos else 0)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100 if peak else 0)
        if i % 5 == 0 or i == end - 1:
            curve.append({"time": _iso(ts[i]), "equity": round(float(equity), 2)})

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    gross_win = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    final = curve[-1]["equity"] if curve else initial
    R = np.array([t["r"] for t in trades]) if trades else np.zeros(0)
    sqn = float(R.mean() / R.std() * np.sqrt(len(R))) if len(R) > 1 and R.std() > 0 else 0.0
    by_strategy = {}
    for t in trades:
        s = by_strategy.setdefault(t["strategy"], {"trades": 0, "wins": 0, "pnl": 0.0, "r_sum": 0.0, "gw": 0.0, "gl": 0.0})
        s["trades"] += 1
        s["wins"] += int(t["pnl"] > 0)
        s["pnl"] += t["pnl"]
        s["r_sum"] += t["r"]
        s["gw" if t["pnl"] > 0 else "gl"] += abs(t["pnl"])
    return {
        "initial": initial,
        "final_equity": round(final, 2),
        "return_pct": round((final - initial) / initial * 100, 2),
        "total_trades": len(trades),
        "rejected_lot": rejected,
        "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else 0,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else (round(gross_win, 2) if gross_win else 0),
        "max_drawdown": round(max_dd, 2),
        "avg_win": round(gross_win / len(wins), 2) if wins else 0,
        "avg_loss": round(-gross_loss / len(losses), 2) if losses else 0,
        "expectancy_r": round(float(R.mean()), 3) if len(R) else 0,
        "sqn": round(sqn, 2),
        "period_start": _iso(ts[start]) if n > start else None,
        "period_end": _iso(ts[end - 1]),
        "candles": n,
        "equity_curve": curve,
        "r_multiples": [t["r"] for t in trades],
        "strategy_stats": {k: {f: round(v, 3) for f, v in s.items()} for k, s in by_strategy.items()},
        "trades": trades[-50:][::-1],
    }


def run_backtest(df, strategy: str, risk_pct: float, leverage: int, trailing: bool = True,
                 initial: float = 10000.0, symbol: str = None, params: dict = None, mode: str = "strict", disabled=()) -> dict:
    return simulate(df, scan_signals(df, strategy, params, mode, disabled), risk_pct, leverage, trailing, initial, symbol)
