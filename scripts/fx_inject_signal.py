"""Inyecta una señal de prueba en el motor HotForex (QA). Uso: python fx_inject_signal.py XAUUSD long [noai]"""
import asyncio
import os
import sys
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv  # noqa: E402
load_dotenv("/app/backend/.env")
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from fx.engine import FxEngine  # noqa: E402
from fx.config import FxConfigStore  # noqa: E402
from strategies import _signal  # noqa: E402


async def main(symbol: str, side: str, ai: bool):
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    eng = FxEngine(db)
    store = FxConfigStore(db)
    store.listeners.append(eng.apply_config)
    await store.load()
    await eng.market.detect()
    s = await eng.get_settings()
    await eng.market.fetch_tickers(s.symbols)
    s.ai_enabled = ai
    if eng.live and eng.broker:
        await eng._monitor_once()  # sync broker health so the HFM connection gate applies like in the running engine
    df = eng._df(await eng.market.fetch_klines(symbol, s.timeframe, 300))
    row = df.iloc[-2]
    atr, c = row["atr"], row["close"]
    sl = c - 1.5 * atr if side == "long" else c + 1.5 * atr
    tp = c + 3 * atr if side == "long" else c - 3 * atr
    sig = _signal(side, row, sl, tp, "trend_ema", ["Señal de prueba inyectada manualmente"], 5, int(row["ts"]) + 1)
    await eng._handle_signal(symbol, sig, s, df, 0, "4h")
    print(await db.fx_signals.find_one(sort=[("_id", -1)], projection={"_id": 0, "indicators": 0}))
    print("open positions:", await db.fx_positions.count_documents({}))
    await eng.market.aclose()


if __name__ == "__main__":
    args = sys.argv[1:]
    asyncio.run(main(args[0] if args else "XAUUSD", args[1] if len(args) > 1 else "long", not (len(args) > 2 and args[2] == "noai")))
