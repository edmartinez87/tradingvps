"""Position sizing in lots, PnL in USD and trailing logic for forex/metals (paper account in USD, HFM-style spreads, no commission)."""
import math
from fx.symbols import SPECS

LOT_STEP, MIN_LOT, MAX_LOT = 0.01, 0.01, 50.0


def quote_usd(symbol: str, tickers: dict) -> float:
    """USD value of 1 unit of the quote currency."""
    q = SPECS[symbol]["quote"]
    if q == "USD":
        return 1.0
    t = tickers.get(f"USD{q}")
    return 1.0 / t["price"] if t and t.get("price") else 1.0


def base_usd(symbol: str, tickers: dict, price: float) -> float:
    """USD value of 1 unit of the base asset (contract notional helper)."""
    b, q = SPECS[symbol]["base"], SPECS[symbol]["quote"]
    if b == "USD":
        return 1.0
    if q == "USD":
        return price
    t = tickers.get(f"{b}USD")
    if t and t.get("price"):
        return t["price"]
    t = tickers.get(f"USD{b}")
    return 1.0 / t["price"] if t and t.get("price") else price * quote_usd(symbol, tickers)


def usd_per_unit(symbol: str, lots: float, tickers: dict) -> float:
    """USD gained per 1.0 price unit move for `lots`."""
    return lots * SPECS[symbol]["contract"] * quote_usd(symbol, tickers)


def spread_cost(symbol: str, lots: float, tickers: dict) -> float:
    """Half-spread cost in USD (paid once at entry and once at exit)."""
    return SPECS[symbol]["spread"] / 2 * usd_per_unit(symbol, lots, tickers)


def round_lots(lots: float, lot: dict = None) -> float:
    mn, step, mx = (lot["min"], lot["step"], lot["max"]) if lot else (MIN_LOT, LOT_STEP, MAX_LOT)
    lots = math.floor(lots / step + 1e-9) * step
    return round(min(lots, mx), 8) if lots >= mn - 1e-9 else 0.0


def position_size(equity: float, available: float, risk_pct: float, entry: float, sl: float, leverage: int, symbol: str, tickers: dict,
                  min_lot_max_risk: float = 0.0, lot: dict = None):
    """Returns (lots, margin_usd, real_risk_pct). Risk = equity × risk% lost if SL is hit; margin = notional / leverage.
    If the ideal size is below the minimum lot, the minimum is used when its risk stays ≤ min_lot_max_risk % of equity.
    `lot` = {min, step, max, contract?} from the broker (REAL mode); defaults to HFM 0.01 lots."""
    dist = abs(entry - sl)
    if dist <= 0 or entry <= 0 or equity <= 0:
        return 0.0, 0.0, 0.0
    min_lot = lot["min"] if lot else MIN_LOT
    contract = lot.get("contract") if lot and lot.get("contract") else SPECS[symbol]["contract"]
    per_lot_loss = dist * contract * quote_usd(symbol, tickers)
    lots = (equity * risk_pct / 100) / per_lot_loss
    notional_per_lot = contract * base_usd(symbol, tickers, entry)
    max_affordable = available * leverage * 0.95 / notional_per_lot
    lots = min(lots, max_affordable)
    if lots < min_lot and max_affordable >= min_lot and per_lot_loss * min_lot / equity * 100 <= min_lot_max_risk:
        lots = min_lot
    lots = round_lots(lots, lot)
    if lots <= 0:
        return 0.0, 0.0, 0.0
    return lots, lots * notional_per_lot / leverage, round(per_lot_loss * lots / equity * 100, 2)


def min_lot_risk_pct(equity: float, entry: float, sl: float, symbol: str, tickers: dict, min_lot: float = MIN_LOT) -> float:
    """Risk (% of equity) of trading the minimum lot with this stop — used to explain rejected sizes."""
    if equity <= 0:
        return 0.0
    return round(abs(entry - sl) * usd_per_unit(symbol, min_lot, tickers) / equity * 100, 2)


def pnl(symbol: str, side: str, entry: float, price: float, lots: float, tickers: dict) -> float:
    move = (price - entry) if side == "long" else (entry - price)
    return move * usd_per_unit(symbol, lots, tickers)


def check_exit(side: str, sl: float, tp: float, price: float):
    if side == "long":
        if price <= sl:
            return sl, "SL"
        if price >= tp:
            return tp, "TP"
    else:
        if price >= sl:
            return sl, "SL"
        if price <= tp:
            return tp, "TP"
    return None, None


def update_trailing(side: str, entry: float, sl: float, initial_sl: float, atr: float, price: float, spread: float):
    """Breakeven (+spread) at +1R, ATR trailing from +1.5R. Returns (new_sl, breakeven_flag)."""
    r = abs(entry - initial_sl)
    if r <= 0:
        return sl, False
    move = (price - entry) if side == "long" else (entry - price)
    new_sl = sl
    if side == "long":
        if move >= r:
            new_sl = max(new_sl, entry + spread)
        if move >= 1.5 * r:
            new_sl = max(new_sl, price - atr)
    else:
        if move >= r:
            new_sl = min(new_sl, entry - spread)
        if move >= 1.5 * r:
            new_sl = min(new_sl, price + atr)
    be = (new_sl >= entry) if side == "long" else (new_sl <= entry)
    return new_sl, be
