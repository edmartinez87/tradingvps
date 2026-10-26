# Iteration 47: trade path (MFE/MAE), configurable breakeven/trailing, partial take-profit (paper engine tick, backtest, API, AI keys).
# Run with: pytest tests/test_iter47_excursion_partial_tp.py -n 0 -q
import os
import sys
import math
import asyncio
import pytest
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, "/app/backend")
load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

import risk  # noqa: E402
from models import Settings, SettingsUpdate, Position  # noqa: E402
from backtest import simulate  # noqa: E402
from indicators import build_df  # noqa: E402
import review  # noqa: E402

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
PASSWORD = "BlackCat2233@"
QA = "QA iter47"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"password": PASSWORD})
    if r.status_code != 200:
        pytest.skip("login failed")
    s.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return s


def _db_run(coro_fn):
    async def go():
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        try:
            return await coro_fn(c[os.environ["DB_NAME"]])
        finally:
            c.close()
    return asyncio.run(go())


# ---------- risk helpers ----------
class TestRules:
    def test_defaults_match_classic(self):
        r = risk.trade_rules(True)
        assert r["be_start_r"] == 1.0 and r["trail_start_r"] == 1.5 and r["trail_atr_mult"] == 1.0 and not r["partial_tp_enabled"]
        assert risk.trade_rules(False)["trailing_enabled"] is False

    def test_from_settings(self):
        s = Settings(be_start_r=0.75, trail_start_r=2.0, trail_atr_mult=1.5, partial_tp_enabled=True, partial_tp_r=1.25, partial_tp_pct=40)
        r = risk.trade_rules(s)
        assert r == {"trailing_enabled": True, "be_start_r": 0.75, "trail_start_r": 2.0, "trail_atr_mult": 1.5, "partial_tp_enabled": True, "partial_tp_r": 1.25, "partial_tp_pct": 40}

    def test_update_trailing_params(self):
        # long entry 100, sl 98 (R=2), atr 1
        sl, be = risk.update_trailing("long", 100, 98, 98, 1.0, 101.5, be_r=1.0, trail_r=1.5, trail_atr=1.0)
        assert not be and sl == 98  # +0.75R: nothing
        sl, be = risk.update_trailing("long", 100, 98, 98, 1.0, 102.0, be_r=1.0, trail_r=1.5, trail_atr=1.0)
        assert be and math.isclose(sl, 100 * (1 + 2 * risk.FEE_RATE))
        sl, be = risk.update_trailing("long", 100, 98, 98, 1.0, 103.0, be_r=1.0, trail_r=1.5, trail_atr=1.0)
        assert be and sl == 102.0  # price - 1 ATR
        sl2, _ = risk.update_trailing("long", 100, 98, 98, 1.0, 103.0, be_r=1.0, trail_r=1.5, trail_atr=0.5)
        assert sl2 == 102.5
        sl3, be3 = risk.update_trailing("long", 100, 98, 98, 1.0, 103.0, be_r=2.0, trail_r=2.0, trail_atr=1.0)
        assert not be3 and sl3 == 98  # +1.5R below a 2R trigger

    def test_move_and_tp_in_r(self):
        assert risk.move_in_r("long", 100, 98, 103) == 1.5 and risk.move_in_r("short", 100, 102, 97) == 1.5
        assert risk.move_in_r("long", 100, 98, 99) == -0.5
        assert risk.tp_in_r("long", 100, 98, 106) == 3.0

    def test_partial_qty_lots(self):
        assert risk.partial_qty("BTCUSDT", 0.004, 50) == 0.002
        assert risk.partial_qty("BTCUSDT", 0.001, 50) == 0.0      # cannot split one lot
        assert risk.partial_qty("BTCUSDT", 0.003, 50) == 0.001    # floor to step, remainder 0.002
        assert risk.partial_qty("XRPUSDT", 7, 50) == 3 and risk.partial_qty("XRPUSDT", 1, 50) == 0

    def test_settings_validation(self):
        with pytest.raises(Exception):
            Settings(partial_tp_pct=90)
        with pytest.raises(Exception):
            Settings(trail_atr_mult=5)
        with pytest.raises(Exception):
            SettingsUpdate(be_start_r=0.1)
        assert SettingsUpdate(partial_tp_r=2.0).partial_tp_r == 2.0

    def test_ai_keys_and_ranges(self):
        assert {"be_start_r", "trail_start_r", "trail_atr_mult", "partial_tp_enabled", "partial_tp_r", "partial_tp_pct"} <= review.CRYPTO_AI_KEYS
        assert review.EXIT_RANGES["partial_tp_pct"] == (25, 75)


# ---------- backtest ----------
def _klines(path, ts0=1_700_000_000_000, step=3_600_000):
    out = []
    for k, (o, h, l, c) in enumerate(path):
        out.append([ts0 + k * step, o, h, l, c, 1000.0])
    return out


class TestBacktestPartial:
    def _df_and_signal(self):
        flat = [(100, 100.5, 99.5, 100)] * 215
        # entry bar then rally to +1.6R (R = 2 → +3.2) and back down to the breakeven
        path = flat + [(100, 100.5, 99.5, 100), (100, 103.3, 99.9, 103.0), (103, 103.4, 100.2, 100.3), (100.3, 100.4, 97.5, 97.8)]
        df = build_df(_klines(path))
        i = 215
        sig = {"side": "long", "strategy": "trend_ema", "price": 100.0, "sl": 98.0, "tp": 106.0, "atr": 1.0, "key_ts": int(df["ts"].iloc[i]), "score": 5, "reasons": [], "indicators": {}}
        return df, {i: sig}

    def test_partial_then_trailing(self):
        df, sigs = self._df_and_signal()
        rules = {"trailing_enabled": True, "be_start_r": 1.0, "trail_start_r": 1.5, "trail_atr_mult": 1.0, "partial_tp_enabled": True, "partial_tp_r": 1.5, "partial_tp_pct": 50}
        res = simulate(df, sigs, 1.0, 3, rules, 10000.0, None)
        assert res["total_trades"] == 1
        t = res["trades"][0]
        assert t["partial"] is True and t["reason"] == "TRAILING" and t["mfe_r"] >= 1.6 and t["mfe_tp_pct"] >= 50
        assert res["excursion"]["partial_closes"] == 1 and t["pnl"] > 0  # partial banked at +1.5R

    def test_no_partial_classic_bool(self):
        df, sigs = self._df_and_signal()
        res = simulate(df, sigs, 1.0, 3, True, 10000.0, None)
        t = res["trades"][0]
        assert t["partial"] is False and "excursion" in res and t["mfe_r"] >= 1.6

    def test_near_miss_counted(self):
        df, sigs = self._df_and_signal()
        sigs[215]["tp"] = 104.0  # TP at 2R, price reached 1.65R = 82 % of TP
        res = simulate(df, sigs, 1.0, 3, False, 10000.0, None)
        assert res["excursion"]["near_miss"] == 1 and res["trades"][0]["reason"] == "SL"


# ---------- paper engine tick ----------
async def _engine_tick(db):
    from engine import TradingEngine
    from config import ConfigStore
    eng = TradingEngine(db)
    store = ConfigStore(db)
    store.listeners.append(eng.apply_config)
    await store.load()
    acc0 = (await db.account.find_one({"_id": "main"}))["balance"]
    rules = {"trailing_enabled": True, "be_start_r": 1.0, "trail_start_r": 1.5, "trail_atr_mult": 1.0, "partial_tp_enabled": True, "partial_tp_r": 1.5, "partial_tp_pct": 50}
    pos = Position(symbol="XRPUSDT", side="long", strategy="trend_ema", entry_price=1.0, qty=100, initial_qty=100, leverage=3, margin=100 / 3,
                   sl=0.98, tp=1.06, initial_sl=0.98, atr=0.01, fees=0.055, mark_price=1.0, signal_id=None)
    res = await db.positions.insert_one(pos.to_mongo())
    pos.id = str(res.inserted_id)
    out = {}
    try:
        eng.market.tickers["XRPUSDT"] = {"price": 1.01}
        await eng._manage_paper_position(Position.from_mongo(await db.positions.find_one({"_id": res.inserted_id})), 1.01, rules)
        d = await db.positions.find_one({"_id": res.inserted_id})
        out["after_05r"] = {"mfe": d["mfe_r"], "partial": d["partial_done"], "sl": d["sl"], "qty": d["qty"]}
        await eng._manage_paper_position(Position.from_mongo(d), 1.032, rules)   # +1.6R → partial 50 % + BE + trailing
        d = await db.positions.find_one({"_id": res.inserted_id})
        out["after_16r"] = {"mfe": d["mfe_r"], "partial": d["partial_done"], "sl": d["sl"], "qty": d["qty"], "gross": d["partial_gross"], "be": d["breakeven"], "fees": d["fees"]}
        out["balance_delta"] = (await db.account.find_one({"_id": "main"}))["balance"] - acc0
        await eng._manage_paper_position(Position.from_mongo(d), 0.99, rules)    # drop → stop (now ≥ entry) → TRAILING close
        d = await db.positions.find_one({"_id": res.inserted_id})
        out["closed"] = d is None
        tr = await db.trades.find_one({"symbol": "XRPUSDT", "opened_at": pos.opened_at})
        out["trade"] = {k: tr.get(k) for k in ("reason", "pnl", "qty", "mfe_r", "mae_r", "mfe_tp_pct", "partial_tp", "hold_min")} if tr else None
        out["log"] = await db.logs.find_one({"message": {"$regex": "PARCIAL LONG XRPUSDT"}})
        return out
    finally:
        await db.positions.delete_one({"_id": res.inserted_id})
        tr = await db.trades.find_one({"symbol": "XRPUSDT", "opened_at": pos.opened_at})
        if tr:
            await db.trades.delete_one({"_id": tr["_id"]})
        await db.logs.delete_many({"message": {"$regex": "XRPUSDT: stop movido a breakeven|PARCIAL LONG XRPUSDT|CERRADA LONG XRPUSDT"}})
        await db.account.update_one({"_id": "main"}, {"$set": {"balance": acc0}})


@pytest.fixture(scope="module")
def tick():
    return _db_run(_engine_tick)


class TestEngineTick:
    def test_tracks_mfe_without_action(self, tick):
        a = tick["after_05r"]
        assert math.isclose(a["mfe"], 0.5) and not a["partial"] and a["sl"] == 0.98 and a["qty"] == 100

    def test_partial_and_trailing(self, tick):
        b = tick["after_16r"]
        assert b["partial"] and b["qty"] == 50 and b["be"] and b["sl"] >= 1.0
        assert math.isclose(b["mfe"], 1.6) and b["gross"] > 1.5  # 50 × (1.032·(1-slip) − 1) ≈ 1.59
        assert tick["balance_delta"] > 1.4 and tick["log"] is not None

    def test_close_records_full_path(self, tick):
        assert tick["closed"]
        t = tick["trade"]
        assert t and t["reason"] == "TRAILING" and t["partial_tp"] is True and t["qty"] == 100
        assert t["mfe_r"] >= 1.6 and t["mfe_tp_pct"] >= 50 and t["pnl"] > 0  # partial profit outweighs the breakeven exit


# ---------- API ----------
class TestApi:
    def test_settings_roundtrip(self, client):
        cur = client.get(f"{BASE_URL}/api/settings").json()
        try:
            r = client.put(f"{BASE_URL}/api/settings", json={"be_start_r": 0.75, "trail_atr_mult": 1.25, "partial_tp_pct": 40, "partial_tp_enabled": False})
            assert r.status_code == 200
            s = r.json()
            assert s["be_start_r"] == 0.75 and s["trail_atr_mult"] == 1.25 and s["partial_tp_pct"] == 40 and s["partial_tp_enabled"] is False
            assert client.put(f"{BASE_URL}/api/settings", json={"partial_tp_pct": 90}).status_code == 422
        finally:
            client.put(f"{BASE_URL}/api/settings", json={k: cur[k] for k in ("be_start_r", "trail_atr_mult", "partial_tp_pct", "partial_tp_enabled")})

    def test_performance_excursion(self, client):
        d = client.get(f"{BASE_URL}/api/performance").json()
        assert "excursion" in d and {"tracked", "by_reason", "near_miss", "near_miss_pct", "avg_mfe_r", "avg_mae_r", "partial"} <= set(d["excursion"])

    def test_backtest_has_excursion(self, client):
        r = client.post(f"{BASE_URL}/api/backtest", json={"symbol": "SOLUSDT", "strategy": "all", "timeframe": "1h", "risk_per_trade": 1, "leverage": 3}, timeout=120)
        assert r.status_code == 200
        d = r.json()
        assert {"avg_mfe_r", "near_miss", "partial_closes"} <= set(d["excursion"])
        if d["trades"]:
            assert {"mfe_r", "mae_r", "mfe_tp_pct", "partial"} <= set(d["trades"][0])

    def test_weekly_has_excursion(self, client):
        d = client.get(f"{BASE_URL}/api/weekly-summary").json()
        assert "excursion" in d
        fx = client.get(f"{BASE_URL}/api/fx/weekly-summary").json()
        assert "excursion" in fx and "text" in fx  # iteration 48: the FX bot tracks MFE/MAE too
