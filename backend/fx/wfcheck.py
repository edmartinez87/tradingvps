"""Weekly walk-forward revalidation kit for HotForex (shares wfcheck.run_check with the crypto bot)."""
import asyncio
from types import SimpleNamespace
from fx.optimizer import walk_forward, WF_CANDLES

job = {"status": "idle", "step": "", "started_at": None, "finished_at": None, "error": None}


async def _wf(engine, settings, initial: float, sym: str) -> dict:
    klines = await engine.market.fetch_klines(sym, settings.timeframe, WF_CANDLES, cache_sec=600)
    return await asyncio.to_thread(walk_forward, klines, settings, initial, sym, dict(engine.market.tickers))


async def _notify(engine, msg: str):
    await engine.tg(msg, "review")


KIT = SimpleNamespace(wf=_wf, job=job, notify=_notify)
