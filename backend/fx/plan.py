"""Growth plan for HotForex: the same compounding phases as crypto with forex-realistic scenarios, backtests in lots/pips
(spread, lot-minimum and weekend/session rules of the bot) and Monte Carlo on the resulting R-multiples."""
import time
import asyncio
import plan as core
from fx.optimizer import kit

CURRENCY = "USD"
SCENARIOS = {
    "conservador": {"name": "Conservador", "rate": 1.5, "desc": "≈20% anual · lo que sostienen los sistemas forex consistentes con riesgo bajo"},
    "base": {"name": "Base", "rate": 3.0, "desc": "≈43% anual · bot con profit factor > 1.3 arriesgando 1% por operación"},
    "optimista": {"name": "Optimista", "rate": 5.0, "desc": "≈80% anual · solo en rachas de tendencia fuerte en oro y mayores, no sostenible"},
}
_cache: dict = {}


def _bt(klines: list, settings, initial: float, symbol: str, params: dict, tickers: dict) -> dict:
    k = kit(settings, tickers)
    df = k.build_df(klines, int(params.get("atr_period", 14)))
    sigs = k.scan_signals(df, settings.strategy, None, settings.signal_mode, settings.disabled_strategies)
    return k.simulate(df, sigs, settings.risk_per_trade, settings.leverage, settings.trailing_enabled, initial, symbol, params.get("sl_atr"), params.get("tp_atr"))


async def backtest_stats(engine, settings, initial: float) -> dict:
    tickers = dict(engine.market.tickers)
    results = []
    for sym in settings.symbols:
        params = settings.symbol_params.get(sym) or {}
        klines = await engine.market.fetch_klines(sym, settings.timeframe, 1000, cache_sec=300)
        results.append((sym, await asyncio.to_thread(_bt, klines, settings, initial, sym, params, tickers)))
    out = core.summarize(results, settings, ("total_pips", "avg_pips", "weekend_closed", "skipped_session"))
    out["total_pips"] = round(sum(p["total_pips"] for p in out["per_symbol"]), 1)
    out["rejected_lot"] = sum(p["rejected_lot"] for p in out["per_symbol"])
    return out


async def plan_stats(engine, settings, initial: float) -> dict:
    key = (tuple(settings.symbols), settings.timeframe, settings.strategy, settings.risk_per_trade, settings.leverage, settings.trailing_enabled,
           settings.max_positions, initial, str(settings.symbol_params), settings.signal_mode, tuple(settings.disabled_strategies),
           settings.min_lot_max_risk, settings.close_before_weekend, tuple(settings.sessions_allowed))
    hit = _cache.get(key)
    if not hit or time.time() - hit["ts"] > 300:
        hit = {"ts": time.time(), "data": await backtest_stats(engine, settings, initial)}
        _cache.clear()
        _cache[key] = hit
    return hit["data"]


def build_plan(req: dict, bt: dict) -> dict:
    return {**core.build_plan(req, bt, SCENARIOS), "currency": CURRENCY}


def build_checkin(s: dict, acc: dict, last30: dict, settings, days: int) -> dict:
    rate = SCENARIOS.get(settings.plan_scenario, SCENARIOS["base"])["rate"]
    return core.build_checkin(s, acc, last30, settings, rate, days, CURRENCY)
