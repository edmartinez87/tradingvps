"""BTC daily regime filter (price vs SMA 50/200) and the weekly volume-weighted momentum rotation of the watchlist.
Evidence: price > SMA50/200 daily cuts BTC drawdowns (−83 % → −57 %) and ~54 % of altcoin moves are explained by BTC; volume-weighted
time-series momentum (Huang, Sangiorgi & Urquhart 2024) beats equal weighting, which turns negative."""
import math
import time
from datetime import datetime, timezone, timedelta
from models import now_iso

REGIME_TTL = 600
ROTATION_TTL_SEC = 7 * 86400
_cache: dict = {}


def regime_from_rows(rows: list, sma_n: int) -> dict:
    closes = [r[4] for r in rows]
    if len(closes) < sma_n + 1:
        return {"state": "N/D", "sma": sma_n, "price": closes[-1] if closes else None, "sma_value": None, "distance_pct": None, "ts": now_iso()}
    price = closes[-1]
    sma = sum(closes[-sma_n - 1:-1]) / sma_n  # last closed daily candles
    return {"state": "ALCISTA" if price > sma else "BAJISTA", "sma": sma_n, "price": price, "sma_value": round(sma, 2),
            "distance_pct": round((price / sma - 1) * 100, 2), "ts": now_iso()}


async def btc_regime(market, sma_n: int) -> dict:
    hit = _cache.get(("regime", sma_n))
    if hit and time.time() - hit[0] < REGIME_TTL:
        return hit[1]
    rows = await market.fetch_history("BTCUSDT", "1d", sma_n + 10, cache_sec=REGIME_TTL)
    out = regime_from_rows(rows, sma_n)
    _cache[("regime", sma_n)] = (time.time(), out)
    return out


def regime_block(regime: dict, side: str):
    """Longs only while BTC trades above its daily SMA, shorts only below it."""
    if not regime or regime.get("state") not in ("ALCISTA", "BAJISTA"):
        return None
    if regime["state"] == "BAJISTA" and side == "long":
        return f"BTC bajo su SMA{regime['sma']} diaria ({regime['distance_pct']:+.1f} %): solo cortos"
    if regime["state"] == "ALCISTA" and side == "short":
        return f"BTC sobre su SMA{regime['sma']} diaria ({regime['distance_pct']:+.1f} %): solo largos"
    return None


def rank(rows_by_symbol: dict, lookback_days: int) -> list:
    """Ranking by lookback return; top third → long bias, bottom third → short bias; the less liquid half trades at 75 % size."""
    items = []
    for sym, rows in rows_by_symbol.items():
        closed = rows[:-1] if len(rows) > lookback_days + 1 else rows
        if len(closed) < lookback_days + 1:
            continue
        ret = closed[-1][4] / closed[-1 - lookback_days][4] - 1
        vol_usd = sum(r[5] * r[4] for r in closed[-lookback_days:])
        items.append({"symbol": sym, "ret_pct": round(ret * 100, 2), "volume_usd": round(vol_usd, 0)})
    items.sort(key=lambda x: x["ret_pct"], reverse=True)
    n = len(items)
    if not n:
        return []
    third = max(1, math.ceil(n / 3)) if n >= 3 else 1
    vols = sorted(x["volume_usd"] for x in items)
    median = vols[n // 2]
    for idx, it in enumerate(items):
        it["rank"] = idx + 1
        it["bias"] = "long" if idx < third else "short" if idx >= n - third else "both"
        if n == 1:
            it["bias"] = "both"
        it["size_factor"] = 1.0 if it["volume_usd"] >= median else 0.75
    return items


async def compute_rotation(market, symbols: list, lookback_days: int) -> dict:
    rows = {}
    for sym in symbols:
        try:
            rows[sym] = await market.fetch_klines(sym, "1d", lookback_days + 5, cache_sec=600)
        except Exception:
            continue
    now = datetime.now(timezone.utc)
    return {"_id": "latest", "computed_at": now.isoformat(), "next_at": (now + timedelta(seconds=ROTATION_TTL_SEC)).isoformat(),
            "lookback_days": lookback_days, "symbols": list(symbols), "ranking": rank(rows, lookback_days)}


async def current_rotation(engine, settings, force: bool = False) -> dict:
    doc = await engine.db.rotation.find_one({"_id": "latest"})
    stale = (not doc or force or set(doc.get("symbols") or []) != set(settings.symbols)
             or doc.get("lookback_days") != settings.rotation_lookback_days
             or datetime.fromisoformat(doc["computed_at"]) < datetime.now(timezone.utc) - timedelta(seconds=ROTATION_TTL_SEC))
    if stale:
        doc = await compute_rotation(engine.market, settings.symbols, settings.rotation_lookback_days)
        await engine.db.rotation.replace_one({"_id": "latest"}, doc, upsert=True)
        top = ", ".join(f"{r['symbol'].replace('USDT', '')} {r['ret_pct']:+.1f}%" for r in doc["ranking"][:3])
        await engine.log("INFO", f"Rotación semanal recalculada ({settings.rotation_lookback_days} d) · líderes: {top or '—'}")
    doc.pop("_id", None)
    return doc


def rotation_gate(rotation: dict, symbol: str, side: str):
    """(block reason or None, size factor) for a signal under the current weekly ranking."""
    row = next((r for r in (rotation or {}).get("ranking") or [] if r["symbol"] == symbol), None)
    if not row:
        return None, 1.0
    if row["bias"] == "long" and side == "short":
        return f"par en el tercio ganador de la semana (#{row['rank']}, {row['ret_pct']:+.1f} %): solo largos", row["size_factor"]
    if row["bias"] == "short" and side == "long":
        return f"par en el tercio perdedor de la semana (#{row['rank']}, {row['ret_pct']:+.1f} %): solo cortos", row["size_factor"]
    return None, row["size_factor"]
