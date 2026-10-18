from datetime import datetime, timezone
from strategies import evaluate
from risk import FEE_RATE, position_size, pnl, check_exit, update_trailing


def _iso(ts_ms) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()


def run_backtest(df, strategy: str, risk_pct: float, leverage: int, trailing: bool = True,
                 initial: float = 10000.0, symbol: str = None) -> dict:
    balance, peak, max_dd = initial, initial, 0.0
    trades, curve, pos, used_keys, rejected = [], [], None, set(), 0
    for i in range(210, len(df)):
        row = df.iloc[i]
        if pos:
            price, reason = check_exit(pos["side"], pos["sl"], pos["tp"], row["high"], row["low"])
            if price is not None:
                if reason == "SL" and pos["be"]:
                    reason = "TRAILING"
                fee = price * pos["qty"] * FEE_RATE
                net = pnl(pos["side"], pos["entry"], price, pos["qty"]) - pos["fee"] - fee
                balance += pnl(pos["side"], pos["entry"], price, pos["qty"]) - fee
                trades.append({"side": pos["side"], "strategy": pos["strategy"], "entry": pos["entry"], "exit": price,
                               "pnl": round(net, 2), "r": round(net / pos["risk_amt"], 3), "reason": reason,
                               "opened_at": pos["opened_at"], "closed_at": _iso(row["ts"])})
                pos = None
            elif trailing:
                pos["sl"], pos["be"] = update_trailing(pos["side"], pos["entry"], pos["sl"], pos["init_sl"], pos["atr"], row["close"])
        if not pos:
            sig = evaluate(df, i, strategy)
            if sig and (sig["strategy"], sig["key_ts"]) not in used_keys:
                used_keys.add((sig["strategy"], sig["key_ts"]))
                qty, _ = position_size(balance, balance, risk_pct, sig["price"], sig["sl"], leverage, symbol)
                if qty > 0:
                    fee = sig["price"] * qty * FEE_RATE
                    balance -= fee
                    pos = {"side": sig["side"], "strategy": sig["strategy"], "entry": sig["price"], "sl": sig["sl"],
                           "init_sl": sig["sl"], "tp": sig["tp"], "atr": sig["atr"], "qty": qty, "fee": fee,
                           "risk_amt": qty * abs(sig["price"] - sig["sl"]), "be": False, "opened_at": _iso(row["ts"])}
                else:
                    rejected += 1
        equity = balance + (pnl(pos["side"], pos["entry"], row["close"], pos["qty"]) if pos else 0)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100 if peak else 0)
        if i % 5 == 0 or i == len(df) - 1:
            curve.append({"time": _iso(row["ts"]), "equity": round(equity, 2)})

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    gross_win = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    final = curve[-1]["equity"] if curve else initial
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
        "expectancy_r": round(sum(t["r"] for t in trades) / len(trades), 3) if trades else 0,
        "period_start": _iso(df.iloc[210]["ts"]) if len(df) > 210 else None,
        "period_end": _iso(df.iloc[-1]["ts"]),
        "candles": len(df),
        "equity_curve": curve,
        "r_multiples": [t["r"] for t in trades],
        "strategy_stats": {k: {f: round(v, 3) for f, v in s.items()} for k, s in by_strategy.items()},
        "trades": trades[-50:][::-1],
    }
