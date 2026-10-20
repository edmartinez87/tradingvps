"""Forex/metals backtest: same signals as the live FX engine, sized in lots with HFM spreads (no commission),
weekend flat like the bot, and per-session attribution. Mirrors backtest.simulate()'s contract so the optimizer can reuse it."""
from datetime import datetime, timezone
import numpy as np
from indicators import build_df
from backtest import scan_signals, _levels, _iso
from risk import check_exit as bar_exit
from fx import risk
from fx.market import sessions as fx_sessions
from fx.symbols import SPECS, pips

WEEKEND_GAP = 3  # a gap wider than 3 candles only happens over the weekend close


def build_fx_df(klines: list, atr_period: int = 14):
    """Yahoo reports no volume for spot forex → neutral volume ratio so volume filters don't silently block every signal."""
    df = build_df(klines, atr_period)
    if df["volume"].fillna(0).sum() == 0:
        df["vol_ratio"] = 1.5
    return df


def session_name(ts_ms: int) -> str:
    names = [s["name"] for s in fx_sessions(datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)) if s["open"]]
    return "/".join(names) if names else "Fuera de sesión"


def simulate(df, signals: dict, risk_pct: float, leverage: int, trailing: bool, initial: float, symbol: str,
             sl_atr: float = None, tp_atr: float = None, start: int = 210, end: int = None, *,
             tickers: dict = None, min_lot_max_risk: float = 4.0, weekend_flat: bool = True) -> dict:
    tickers = tickers or {}
    spread = SPECS[symbol]["spread"]
    highs, lows, closes, ts = df["high"].values, df["low"].values, df["close"].values, df["ts"].values
    n = len(df)
    end = end or n
    step_ms = float(np.median(np.diff(ts[:200]))) if n > 2 else 0
    balance, peak, max_dd = initial, initial, 0.0
    trades, curve, pos, rejected, weekend_closed = [], [], None, 0, 0

    def before_weekend(i):
        return weekend_flat and i + 1 < n and ts[i + 1] - ts[i] > WEEKEND_GAP * step_ms

    def close(price, reason, i):
        nonlocal balance, pos
        if reason == "SL" and pos["be"]:
            reason = "TRAILING"
        fee = risk.spread_cost(symbol, pos["lots"], tickers)
        gross = risk.pnl(symbol, pos["side"], pos["entry"], price, pos["lots"], tickers)
        net = gross - pos["fee"] - fee
        balance += gross - fee
        move = (price - pos["entry"]) if pos["side"] == "long" else (pos["entry"] - price)
        trades.append({"side": pos["side"], "strategy": pos["strategy"], "entry": pos["entry"], "exit": float(price), "lots": pos["lots"],
                       "pnl": round(float(net), 2), "r": round(float(net / pos["risk_amt"]), 3) if pos["risk_amt"] else 0.0,
                       "pips": round(pips(symbol, move), 1), "reason": reason, "session": pos["session"],
                       "opened_at": pos["opened_at"], "closed_at": _iso(ts[i])})
        pos = None

    for i in range(start, end):
        if pos:
            price, reason = bar_exit(pos["side"], pos["sl"], pos["tp"], highs[i], lows[i])
            if price is not None:
                close(price, reason, i)
            elif trailing:
                pos["sl"], pos["be"] = risk.update_trailing(pos["side"], pos["entry"], pos["sl"], pos["init_sl"], pos["atr"], closes[i], spread)
        weekend = before_weekend(i)
        if pos and weekend:
            close(closes[i], "FIN_SEMANA", i)
            weekend_closed += 1
        if not pos and not weekend and i in signals:
            sig = signals[i]
            sl, tp = _levels(sig, sl_atr, tp_atr)
            if sl is not None:
                lots, _, _ = risk.position_size(balance, balance, risk_pct, sig["price"], sl, leverage, symbol, tickers, min_lot_max_risk)
                if lots > 0:
                    fee = risk.spread_cost(symbol, lots, tickers)
                    balance -= fee
                    pos = {"side": sig["side"], "strategy": sig["strategy"], "entry": sig["price"], "sl": sl, "init_sl": sl, "tp": tp,
                           "atr": sig["atr"], "lots": lots, "fee": fee, "risk_amt": abs(sig["price"] - sl) * risk.usd_per_unit(symbol, lots, tickers),
                           "be": False, "opened_at": _iso(ts[i]), "session": session_name(int(ts[i]))}
                else:
                    rejected += 1
        if pos and i == end - 1 and end < n:
            close(closes[i], "FIN", i)
        equity = balance + (risk.pnl(symbol, pos["side"], pos["entry"], closes[i], pos["lots"], tickers) if pos else 0)
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
    by_strategy, by_session = {}, {}
    for t in trades:
        s = by_strategy.setdefault(t["strategy"], {"trades": 0, "wins": 0, "pnl": 0.0, "r_sum": 0.0, "gw": 0.0, "gl": 0.0})
        s["trades"] += 1
        s["wins"] += int(t["pnl"] > 0)
        s["pnl"] += t["pnl"]
        s["r_sum"] += t["r"]
        s["gw" if t["pnl"] > 0 else "gl"] += abs(t["pnl"])
        se = by_session.setdefault(t["session"], {"trades": 0, "wins": 0, "pnl": 0.0, "pips": 0.0})
        se["trades"] += 1
        se["wins"] += int(t["pnl"] > 0)
        se["pnl"] += t["pnl"]
        se["pips"] += t["pips"]
    return {
        "initial": initial,
        "final_equity": round(final, 2),
        "return_pct": round((final - initial) / initial * 100, 2),
        "total_trades": len(trades),
        "rejected_lot": rejected,
        "weekend_closed": weekend_closed,
        "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else 0,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else (round(gross_win, 2) if gross_win else 0),
        "max_drawdown": round(max_dd, 2),
        "avg_win": round(gross_win / len(wins), 2) if wins else 0,
        "avg_loss": round(-gross_loss / len(losses), 2) if losses else 0,
        "expectancy_r": round(float(R.mean()), 3) if len(R) else 0,
        "sqn": round(sqn, 2),
        "total_pips": round(sum(t["pips"] for t in trades), 1),
        "avg_pips": round(sum(t["pips"] for t in trades) / len(trades), 1) if trades else 0,
        "period_start": _iso(ts[start]) if n > start else None,
        "period_end": _iso(ts[end - 1]),
        "candles": n,
        "equity_curve": curve,
        "r_multiples": [t["r"] for t in trades],
        "strategy_stats": {k: {f: round(v, 3) for f, v in s.items()} for k, s in by_strategy.items()},
        "session_stats": {k: {f: round(v, 2) for f, v in s.items()} for k, s in sorted(by_session.items(), key=lambda kv: -kv[1]["trades"])},
        "trades": trades[-50:][::-1],
    }


def run_backtest(klines: list, strategy: str, risk_pct: float, leverage: int, trailing: bool, initial: float, symbol: str,
                 mode: str, disabled, tickers: dict, min_lot_max_risk: float, weekend_flat: bool) -> dict:
    df = build_fx_df(klines)
    return simulate(df, scan_signals(df, strategy, None, mode, disabled), risk_pct, leverage, trailing, initial, symbol,
                    tickers=tickers, min_lot_max_risk=min_lot_max_risk, weekend_flat=weekend_flat)
