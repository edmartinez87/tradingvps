FEE_RATE = 0.00055
SLIPPAGE = 0.0002


def position_size(equity: float, available: float, risk_pct: float, entry: float, sl: float, leverage: int):
    dist = abs(entry - sl)
    if dist <= 0 or entry <= 0:
        return 0.0, 0.0
    qty = (equity * risk_pct / 100) / dist
    max_notional = available * leverage * 0.95
    qty = min(qty, max_notional / entry)
    return qty, qty * entry / leverage


def pnl(side: str, entry: float, price: float, qty: float) -> float:
    return (price - entry) * qty if side == "long" else (entry - price) * qty


def check_exit(side: str, sl: float, tp: float, high: float, low: float):
    if side == "long":
        if low <= sl:
            return sl, "SL"
        if high >= tp:
            return tp, "TP"
    else:
        if high >= sl:
            return sl, "SL"
        if low <= tp:
            return tp, "TP"
    return None, None


def update_trailing(side: str, entry: float, sl: float, initial_sl: float, atr: float, price: float):
    """Breakeven at +1R, ATR trailing from +1.5R. Returns (new_sl, breakeven_flag)."""
    r = abs(entry - initial_sl)
    if r <= 0:
        return sl, False
    move = (price - entry) if side == "long" else (entry - price)
    new_sl = sl
    if side == "long":
        if move >= r:
            new_sl = max(new_sl, entry * (1 + 2 * FEE_RATE))
        if move >= 1.5 * r:
            new_sl = max(new_sl, price - atr)
    else:
        if move >= r:
            new_sl = min(new_sl, entry * (1 - 2 * FEE_RATE))
        if move >= 1.5 * r:
            new_sl = min(new_sl, price + atr)
    be = (new_sl >= entry) if side == "long" else (new_sl <= entry)
    return new_sl, be
