"""Risk/execution gates for the HotForex bot: net currency exposure, the 17:00 New York rollover window, ATR volatility regime,
intraday seasonality bias (Breedon & Ranaldo) and the FOMC no-continuation rule. Every gate returns (block_reason | None, size_factor)."""
from datetime import datetime, timezone, timedelta, time as dtime
import numpy as np
from fx.symbols import SPECS, currencies
from fx.market import NY

ROLLOVER_START, ROLLOVER_END = dtime(16, 50), dtime(17, 15)   # New York local time
ROLLOVER_SPREAD_MULT = 4.0
VOL_LOOKBACK = 200
VOL_HIGH_FACTOR = 0.5
FOMC_HOURS = 24
FOMC_WORDS = ("fomc", "fed interest rate", "federal funds", "fed funds", "interest rate decision")
# local business hours in UTC (winter-ish; the effect is broad enough for a 1 h shift not to matter)
LOCAL_HOURS = {"EUR": (7, 15), "CHF": (7, 15), "GBP": (7, 15), "USD": (13, 21), "CAD": (13, 21), "JPY": (0, 8), "AUD": (22, 6), "NZD": (22, 6)}


# ---------- rollover ----------
def in_rollover(now: datetime = None) -> bool:
    t = (now or datetime.now(timezone.utc)).astimezone(NY).time()
    return ROLLOVER_START <= t <= ROLLOVER_END


def rollover_block(enabled: bool, now: datetime = None):
    if enabled and in_rollover(now):
        return "ventana de rollover (17:00 Nueva York): spreads ampliados y liquidez mínima"
    return None


def rollover_status(now: datetime = None) -> dict:
    now = now or datetime.now(timezone.utc)
    ny = now.astimezone(NY)
    start = ny.replace(hour=ROLLOVER_START.hour, minute=ROLLOVER_START.minute, second=0, microsecond=0)
    if ny.time() > ROLLOVER_END:
        start += timedelta(days=1)
    return {"active": in_rollover(now), "next_start": start.astimezone(timezone.utc).isoformat(), "window_ny": "16:50–17:15",
            "spread_mult": ROLLOVER_SPREAD_MULT, "triple_swap": ny.weekday() == 2}


# ---------- volatility regime ----------
def vol_percentile(atr_series, i: int = None, lookback: int = VOL_LOOKBACK) -> float | None:
    """Percentile rank (0-100) of the current ATR within the last `lookback` closed candles (causal)."""
    arr = np.asarray(atr_series, dtype=float)
    i = len(arr) - 1 if i is None else i
    window = arr[max(0, i - lookback + 1): i + 1]
    window = window[~np.isnan(window)]
    if len(window) < 50:
        return None
    return round(float((window < window[-1]).mean() * 100), 1)


def vol_gate(pct: float | None, settings):
    """(block, size_factor): dead market below vol_min_pct blocks; extreme above vol_high_pct halves the size."""
    if not getattr(settings, "vol_filter_enabled", False) or pct is None:
        return None, 1.0
    if pct < settings.vol_min_pct:
        return f"volatilidad en el percentil {pct:g} (mínimo {settings.vol_min_pct}): el spread se come la señal", 1.0
    if pct >= settings.vol_high_pct:
        return None, VOL_HIGH_FACTOR
    return None, 1.0


def vol_label(pct: float | None, settings) -> str:
    if pct is None:
        return "N/D"
    if pct < settings.vol_min_pct:
        return "MUERTO"
    if pct >= settings.vol_high_pct:
        return "EXTREMO"
    return "NORMAL"


# ---------- intraday seasonality ----------
def _in_hours(hour: int, span: tuple) -> bool:
    a, b = span
    return a <= hour < b if a < b else (hour >= a or hour < b)


def seasonality_bias(symbol: str, now: datetime = None) -> str:
    """'short' while the base currency is in its local hours (it tends to depreciate), 'long' during the quote currency's hours, else 'both'."""
    base, quote = currencies(symbol)
    if base not in LOCAL_HOURS or quote not in LOCAL_HOURS:
        return "both"
    h = (now or datetime.now(timezone.utc)).hour
    b, q = _in_hours(h, LOCAL_HOURS[base]), _in_hours(h, LOCAL_HOURS[quote])
    if b and not q:
        return "short"
    if q and not b:
        return "long"
    return "both"


def seasonality_gate(symbol: str, side: str, settings, now: datetime = None):
    if not getattr(settings, "seasonality_bias", False):
        return None, 1.0
    bias = seasonality_bias(symbol, now)
    if bias == "both" or bias == side:
        return None, 1.0
    cur = currencies(symbol)[0] if bias == "short" else currencies(symbol)[1]
    why = f"estacionalidad intradía: horario local de {cur}, sesgo {'bajista' if bias == 'short' else 'alcista'} en el par"
    if symbol in settings.seasonality_block_pairs:
        return why, 1.0
    return None, settings.seasonality_size_factor


# ---------- currency exposure ----------
def exposure_counts(open_docs: list) -> dict:
    """Net directional count per currency: long EURUSD = +1 EUR, −1 USD."""
    out = {}
    for p in open_docs:
        if p["symbol"] not in SPECS:
            continue
        base, quote = currencies(p["symbol"])
        sign = 1 if p["side"] == "long" else -1
        out[base] = out.get(base, 0) + sign
        out[quote] = out.get(quote, 0) - sign
    return out


def exposure_block(open_docs: list, symbol: str, side: str, limit: int):
    """Blocks when the new trade would push any currency's net directional count beyond `limit`."""
    counts = exposure_counts(open_docs)
    base, quote = currencies(symbol)
    sign = 1 if side == "long" else -1
    for cur, delta in ((base, sign), (quote, -sign)):
        new = counts.get(cur, 0) + delta
        if abs(new) > limit and abs(new) > abs(counts.get(cur, 0)):
            return f"exposición neta en {cur} llegaría a {abs(new)} posiciones en la misma dirección (tope {limit})"
    return None


# ---------- FOMC ----------
def fomc_event(events: list, now: datetime = None) -> dict | None:
    """The most recent USD rate-decision event released within the last FOMC_HOURS, if any."""
    now = now or datetime.now(timezone.utc)
    best = None
    for e in events or []:
        if e.get("country") != "USD" or not any(w in (e.get("title") or "").lower() for w in FOMC_WORDS):
            continue
        try:
            t = datetime.fromisoformat(e["time"])
        except (KeyError, ValueError):
            continue
        if t <= now < t + timedelta(hours=FOMC_HOURS) and (best is None or t > best["t"]):
            best = {"t": t, "title": e.get("title"), "time": e["time"]}
    return best


def post_event_direction(klines: list, event_ts: datetime, price_now: float) -> str | None:
    """'long' if price_now is above the last close before the event, 'short' if below (klines = [ts_ms, o, h, l, c, v])."""
    ref = None
    for k in klines:
        if k[0] / 1000 <= event_ts.timestamp():
            ref = k[4]
        else:
            break
    if ref is None or not price_now:
        return None
    return "long" if price_now > ref else ("short" if price_now < ref else None)


def fomc_block(symbol: str, side: str, event: dict | None, direction: str | None, enabled: bool):
    if not enabled or not event or direction is None or "USD" not in currencies(symbol):
        return None
    if side == direction:
        hrs = FOMC_HOURS
        return f"regla FOMC: sin operar la continuación del movimiento en las {hrs} h posteriores a «{event['title']}»"
    return None
