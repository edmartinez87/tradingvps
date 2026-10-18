import math

FEE_RATE = 0.00055
SLIPPAGE = 0.0002
MIN_NOTIONAL = 5.0
# Bybit USDT perpetuals: (min order qty, qty step)
LOT_SIZES = {
    "BTCUSDT": (0.001, 0.001), "ETHUSDT": (0.01, 0.01), "SOLUSDT": (0.1, 0.1), "XRPUSDT": (1, 1),
    "BNBUSDT": (0.01, 0.01), "DOGEUSDT": (1, 1), "AVAXUSDT": (0.1, 0.1), "LINKUSDT": (0.1, 0.1),
    "ADAUSDT": (1, 1), "NEARUSDT": (0.1, 0.1), "SUIUSDT": (10, 10), "LTCUSDT": (0.1, 0.1),
}


def lot_qty(symbol: str, qty: float, lot: tuple = None) -> float:
    min_qty, step = lot or LOT_SIZES.get(symbol, (0.001, 0.001))
    qty = math.floor(qty / step + 1e-9) * step
    return round(qty, 8) if qty >= min_qty else 0.0


def position_size(equity: float, available: float, risk_pct: float, entry: float, sl: float, leverage: int,
                  symbol: str = None, lot: tuple = None):
    dist = abs(entry - sl)
    if dist <= 0 or entry <= 0:
        return 0.0, 0.0
    qty = (equity * risk_pct / 100) / dist
    max_notional = available * leverage * 0.95
    qty = min(qty, max_notional / entry)
    if symbol or lot:
        qty = lot_qty(symbol, qty, lot)
    if qty * entry < MIN_NOTIONAL:
        return 0.0, 0.0
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
