"""Synthetic USD index regime for the HotForex bot: equal-weight geometric mean of USD against EUR, JPY, GBP, CAD and CHF on daily closes
(Yahoo), compared with its SMA 50/200 using closed candles only. USD-quote pairs trade only short when USD is strong, USD-base pairs only long."""
import time
import numpy as np
from fx.symbols import currencies

INDEX_PAIRS = {"EURUSD": -1, "USDJPY": 1, "GBPUSD": -1, "USDCAD": 1, "USDCHF": 1}
CACHE_SEC = 600
_cache = {"ts": 0.0, "sma": None, "data": None}


def index_series(rows_by_pair: dict) -> dict:
    """Aligned daily USD index (ts → value) from per-pair klines. Value = exp(mean(sign · log(close)))."""
    series = {}
    for pair, sign in INDEX_PAIRS.items():
        rows = rows_by_pair.get(pair) or []
        series[pair] = {int(r[0] // 86_400_000): float(r[4]) for r in rows if r[4]}
    if any(not s for s in series.values()):
        return {}
    days = sorted(set.intersection(*(set(s) for s in series.values())))
    return {d: float(np.exp(np.mean([INDEX_PAIRS[p] * np.log(series[p][d]) for p in INDEX_PAIRS]))) for d in days}


def regime_from_index(index: dict, sma: int) -> dict:
    vals = [index[d] for d in sorted(index)]
    if len(vals) < sma + 1:
        return {"state": "N/D", "sma": sma, "value": vals[-1] if vals else None, "sma_value": None, "distance_pct": None}
    closed = vals[:-1]  # the last point is today's unfinished candle
    sma_v = float(np.mean(closed[-sma:]))
    value = closed[-1]
    return {"state": "USD FUERTE" if value > sma_v else "USD DÉBIL", "sma": sma, "value": round(value, 5), "sma_value": round(sma_v, 5),
            "distance_pct": round((value / sma_v - 1) * 100, 2)}


async def usd_regime(market, sma: int) -> dict:
    now = time.time()
    if _cache["data"] and _cache["sma"] == sma and now - _cache["ts"] < CACHE_SEC:
        return _cache["data"]
    rows = {}
    for pair in INDEX_PAIRS:
        try:
            rows[pair] = await market.fetch_klines(pair, "1d", 260, cache_sec=CACHE_SEC)
        except Exception:
            rows[pair] = []
    data = regime_from_index(index_series(rows), sma)
    _cache.update(ts=now, sma=sma, data=data)
    return data


def regime_block(regime: dict | None, symbol: str, side: str):
    """USD-quote pairs (EURUSD…) only short in USD FUERTE / only long in USD DÉBIL; USD-base pairs the opposite. Crosses and metals untouched."""
    if not regime or regime.get("state") == "N/D":
        return None
    base, quote = currencies(symbol)
    if quote == "USD" and base in ("XAU", "XAG"):
        return None
    strong = regime["state"] == "USD FUERTE"
    if quote == "USD":
        allowed = "short" if strong else "long"
    elif base == "USD":
        allowed = "long" if strong else "short"
    else:
        return None
    if side != allowed:
        return f"régimen USD {regime['state']} (índice vs SMA{regime['sma']} diaria {regime['distance_pct']:+.2f} %): {symbol} solo {'largos' if allowed == 'long' else 'cortos'}"
    return None
