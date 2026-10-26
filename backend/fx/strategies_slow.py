"""Low-frequency FX strategy: month-end London 4pm fix reversion (Melvin & Prins; Norges Bank). On the last business day of the month the hedging
flows compressed into the 15:00–16:00 London hour push prices away from equilibrium and ~70 % of that move reverts by the next morning.
The bot fades the pre-fix move right after the fix, SL beyond the fix extreme, TP = full reversal to the 15:00 price, time stop next day 12:00 London."""
from datetime import datetime, timedelta
import calendar
import numpy as np
from fx.market import LONDON
from fx.symbols import pips

SLOW_INFO = {
    "fix_reversion": {
        "name": "Reversión fin de mes (fix de Londres)", "tf": "15m", "bt_tf": "1h", "horizon": "long", "bars": 300,
        "rules": "Último día hábil del mes, tras el fix de las 16:00 de Londres: si el movimiento 15:00→16:00 supera 0,6×ATR(1h), se abre en contra "
                 "entre 16:00 y 16:20. SL en el extremo del movimiento + 0,3×ATR, TP en el precio de las 15:00 (reversión completa), cierre por tiempo "
                 "a las 12:00 de Londres del día siguiente. Solo mayores y cruces (no metales). No cuenta en «Máx. posiciones».",
        "basis": "Flujos de cobertura de fin de mes concentrados en la ventana del fix WM/Reuters: reversión media del 72 % del movimiento previo "
                 "(Melvin & Prins 2015; Norges Bank). Baja frecuencia: ~12 oportunidades al año por par.",
    }
}
SLOW_KEYS = list(SLOW_INFO)
MIN_MOVE_ATR = 0.6
ENTRY_WINDOW_MIN = 20
EXIT_HOUR_LONDON = 12


def last_business_day(d) -> bool:
    """True when `d` (London date) is the last weekday of its month."""
    if d.weekday() >= 5:
        return False
    last = calendar.monthrange(d.year, d.month)[1]
    for day in range(last, d.day, -1):
        if d.replace(day=day).weekday() < 5:
            return False
    return True


def fix_window(now_utc: datetime) -> dict | None:
    """Returns the London fix timestamp info when `now_utc` is within the entry window after a month-end fix."""
    ldn = now_utc.astimezone(LONDON)
    if not last_business_day(ldn.date()):
        return None
    fix = ldn.replace(hour=16, minute=0, second=0, microsecond=0)
    if not (fix <= ldn <= fix + timedelta(minutes=ENTRY_WINDOW_MIN)):
        return None
    pre = fix - timedelta(hours=1)
    exit_at = (fix + timedelta(days=1)).replace(hour=EXIT_HOUR_LONDON, minute=0)
    while exit_at.weekday() >= 5:
        exit_at += timedelta(days=1)
    return {"fix": fix, "pre": pre, "exit_at": exit_at}


def _price_at(rows: list, ts: datetime, field: int = 4):
    """Close (or chosen field) of the last candle that closed at or before `ts`."""
    t = ts.timestamp() * 1000
    ref = None
    for k in rows:
        if k[0] + 15 * 60_000 <= t + 1:
            ref = k
        else:
            break
    return ref[field] if ref else None


def fix_signal(symbol: str, rows15: list, atr_1h: float, now_utc: datetime, price_now: float) -> dict | None:
    """Evaluate the month-end fix reversion right after the fix. rows15 = 15m klines [ts_ms, o, h, l, c, v]."""
    w = fix_window(now_utc)
    if not w or not atr_1h or not price_now:
        return None
    pre = _price_at(rows15, w["pre"])
    fix_px = _price_at(rows15, w["fix"])
    if pre is None or fix_px is None:
        return None
    hour = [k for k in rows15 if w["pre"].timestamp() * 1000 <= k[0] < w["fix"].timestamp() * 1000]
    if len(hour) < 3:
        return None
    move = fix_px - pre
    if abs(move) < MIN_MOVE_ATR * atr_1h:
        return None
    side = "short" if move > 0 else "long"
    hi, lo = max(k[2] for k in hour), min(k[3] for k in hour)
    sl = hi + 0.3 * atr_1h if side == "short" else lo - 0.3 * atr_1h
    tp = pre
    if (side == "short" and not (tp < price_now < sl)) or (side == "long" and not (sl < price_now < tp)):
        return None
    return {"side": side, "strategy": "fix_reversion", "price": float(price_now), "sl": float(sl), "tp": float(tp), "atr": float(atr_1h),
            "score": 3, "key_ts": int(w["fix"].timestamp()), "expires_at": w["exit_at"].isoformat(),
            "reasons": [f"Último día hábil del mes · movimiento pre-fix {pips(symbol, move):+.1f} pips ({abs(move) / atr_1h:.1f}×ATR 1h)",
                        "Reversión esperada ≈ 72 % del movimiento hacia el precio de las 15:00 de Londres", "Cierre por tiempo: 12:00 Londres del día siguiente"],
            "indicators": {"pre_fix": pre, "fix": fix_px, "move_atr": round(abs(move) / atr_1h, 2)}}


def scan_fix(rows1h: list, atr_series) -> dict:
    """Backtest helper on 1h candles: {index_of_entry_bar: signal}. Entry at the close of the 16:00 London bar (bar covering 16:00–17:00 is i+1 → we
    enter at the open of that bar = close of the 15:00–16:00 bar)."""
    out = {}
    for i in range(2, len(rows1h) - 1):
        ts = datetime.fromtimestamp(rows1h[i][0] / 1000, tz=LONDON)
        if ts.hour != 15 or not last_business_day(ts.date()):
            continue
        atr = float(atr_series[i]) if not np.isnan(atr_series[i]) else None
        if not atr:
            continue
        pre, fix_px = rows1h[i][1], rows1h[i][4]
        move = fix_px - pre
        if abs(move) < MIN_MOVE_ATR * atr:
            continue
        side = "short" if move > 0 else "long"
        sl = rows1h[i][2] + 0.3 * atr if side == "short" else rows1h[i][3] - 0.3 * atr
        exit_at = (ts + timedelta(days=1)).replace(hour=EXIT_HOUR_LONDON, minute=0)
        while exit_at.weekday() >= 5:
            exit_at += timedelta(days=1)
        out[i] = {"side": side, "strategy": "fix_reversion", "price": float(fix_px), "sl": float(sl), "tp": float(pre), "atr": atr, "score": 3,
                  "key_ts": int(rows1h[i][0] // 1000), "expires_ts": int(exit_at.timestamp()), "reasons": [], "indicators": {}}
    return out
