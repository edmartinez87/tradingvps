# Iteration 48: HotForex gates (exposure, rollover, volatility, seasonality, USD regime, FOMC), month-end fix reversion, exit rules
# (MFE/MAE, partial TP, time stop) in paper engine + backtest + API. Run with: pytest tests/test_iter48_fx_filters_fix.py -n 0 -q
import os
import sys
import asyncio
from datetime import datetime, timezone, timedelta
import numpy as np
import pytest
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, "/app/backend")
load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

from fx import filters, risk  # noqa: E402
from fx import regime as fx_regime  # noqa: E402
from fx.strategies_slow import last_business_day, fix_window, fix_signal, scan_fix, SLOW_INFO  # noqa: E402
from fx.models import FxSettings, FxSettingsUpdate  # noqa: E402
from fx.backtest import simulate, build_fx_df  # noqa: E402
from fx.market import LONDON, NY  # noqa: E402
from models import Position  # noqa: E402
import fx.review as fx_review  # noqa: E402

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
FX = f"{BASE_URL}/api/fx"
PASSWORD = "BlackCat2233@"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"password": PASSWORD}, timeout=30)
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


def _ny(h, m, weekday_date="2026-03-10"):
    return datetime.fromisoformat(f"{weekday_date}T{h:02d}:{m:02d}:00").replace(tzinfo=NY).astimezone(timezone.utc)


# ---------- rollover ----------
class TestRollover:
    def test_window(self):
        assert filters.in_rollover(_ny(16, 50)) and filters.in_rollover(_ny(17, 0)) and filters.in_rollover(_ny(17, 15))
        assert not filters.in_rollover(_ny(16, 49)) and not filters.in_rollover(_ny(17, 16)) and not filters.in_rollover(_ny(9, 30))

    def test_block_and_status(self):
        assert filters.rollover_block(True, _ny(17, 0))
        assert filters.rollover_block(False, _ny(17, 0)) is None
        st = filters.rollover_status(_ny(17, 30))
        assert not st["active"] and st["spread_mult"] == 4.0 and st["window_ny"] == "16:50–17:15"
        assert datetime.fromisoformat(st["next_start"]) > _ny(17, 30)


# ---------- volatility ----------
class TestVolatility:
    def test_percentile_causal(self):
        atr = np.linspace(1, 2, 300)
        assert filters.vol_percentile(atr, 299) == 99.5
        assert filters.vol_percentile(atr, 30) is None
        atr2 = np.concatenate([np.linspace(1, 2, 299), [0.5]])
        assert filters.vol_percentile(atr2) == 0.0

    def test_gate(self):
        s = FxSettings(vol_filter_enabled=True, vol_min_pct=20, vol_high_pct=90)
        b, f = filters.vol_gate(10, s)
        assert b and f == 1.0
        assert filters.vol_gate(50, s) == (None, 1.0)
        assert filters.vol_gate(95, s) == (None, 0.5)
        assert filters.vol_gate(5, FxSettings(vol_filter_enabled=False)) == (None, 1.0)
        assert filters.vol_gate(None, s) == (None, 1.0)
        assert filters.vol_label(10, s) == "MUERTO" and filters.vol_label(95, s) == "EXTREMO" and filters.vol_label(50, s) == "NORMAL"


# ---------- seasonality ----------
class TestSeasonality:
    def test_bias(self):
        eu_morning = datetime(2026, 3, 10, 9, 0, tzinfo=timezone.utc)   # EUR hours only
        assert filters.seasonality_bias("EURUSD", eu_morning) == "short"
        us_afternoon = datetime(2026, 3, 10, 18, 0, tzinfo=timezone.utc)  # USD hours only
        assert filters.seasonality_bias("EURUSD", us_afternoon) == "long"
        assert filters.seasonality_bias("EURUSD", datetime(2026, 3, 10, 14, 0, tzinfo=timezone.utc)) == "both"  # overlap
        assert filters.seasonality_bias("XAUUSD", eu_morning) == "both"

    def test_gate(self):
        s = FxSettings(seasonality_bias=True, seasonality_block_pairs=["EURUSD"], seasonality_size_factor=0.75)
        eu = datetime(2026, 3, 10, 9, 0, tzinfo=timezone.utc)
        b, f = filters.seasonality_gate("EURUSD", "long", s, eu)
        assert b and "EUR" in b and f == 1.0
        assert filters.seasonality_gate("EURUSD", "short", s, eu) == (None, 1.0)
        b, f = filters.seasonality_gate("GBPUSD", "long", s, eu)
        assert b is None and f == 0.75
        assert filters.seasonality_gate("EURUSD", "long", FxSettings(seasonality_bias=False), eu) == (None, 1.0)


# ---------- exposure ----------
class TestExposure:
    def test_counts_and_block(self):
        docs = [{"symbol": "EURUSD", "side": "long"}, {"symbol": "GBPUSD", "side": "long"}]
        c = filters.exposure_counts(docs)
        assert c == {"EUR": 1, "USD": -2, "GBP": 1}
        assert filters.exposure_block(docs, "AUDUSD", "long", 2)  # USD would reach -3
        assert filters.exposure_block(docs, "AUDUSD", "short", 2) is None  # reduces USD exposure
        assert filters.exposure_block(docs, "EURJPY", "long", 2) is None
        assert filters.exposure_block(docs, "AUDUSD", "long", 3) is None
        assert filters.exposure_block([], "XAUUSD", "long", 1) is None


# ---------- USD regime ----------
class TestUsdRegime:
    def _rows(self, n, start, slope):
        day = 86_400_000
        return [[i * day, 0, 0, 0, start + slope * i, 1] for i in range(n)]

    def test_index_and_regime(self):
        rows = {"EURUSD": self._rows(260, 1.10, -0.0002), "USDJPY": self._rows(260, 140, 0.05), "GBPUSD": self._rows(260, 1.30, -0.0002),
                "USDCAD": self._rows(260, 1.30, 0.0002), "USDCHF": self._rows(260, 0.90, 0.0002)}
        idx = fx_regime.index_series(rows)
        assert len(idx) == 260
        rg = fx_regime.regime_from_index(idx, 200)
        assert rg["state"] == "USD FUERTE" and rg["distance_pct"] > 0
        assert fx_regime.regime_block(rg, "EURUSD", "long") and fx_regime.regime_block(rg, "EURUSD", "short") is None
        assert fx_regime.regime_block(rg, "USDJPY", "short") and fx_regime.regime_block(rg, "USDJPY", "long") is None
        assert fx_regime.regime_block(rg, "EURJPY", "long") is None and fx_regime.regime_block(rg, "XAUUSD", "long") is None
        assert fx_regime.regime_from_index(idx, 300)["state"] == "N/D"
        assert fx_regime.regime_block({"state": "N/D"}, "EURUSD", "long") is None

    def test_missing_pair(self):
        assert fx_regime.index_series({"EURUSD": self._rows(10, 1.1, 0)}) == {}


# ---------- FOMC ----------
class TestFomc:
    def test_event_and_block(self):
        now = datetime(2026, 3, 18, 20, 0, tzinfo=timezone.utc)
        events = [{"country": "USD", "title": "FOMC Statement", "time": "2026-03-18T18:00:00+00:00"},
                  {"country": "EUR", "title": "ECB Interest Rate Decision", "time": "2026-03-18T13:15:00+00:00"},
                  {"country": "USD", "title": "Federal Funds Rate", "time": "2026-03-17T18:00:00+00:00"}]
        ev = filters.fomc_event(events, now)
        assert ev and ev["title"] == "FOMC Statement"
        assert filters.fomc_event(events, now + timedelta(hours=30)) is None
        kl = [[int((ev["t"] - timedelta(hours=1)).timestamp() * 1000), 1, 1, 1, 1.0800, 1], [int((ev["t"] + timedelta(hours=1)).timestamp() * 1000), 1, 1, 1, 1.0850, 1]]
        assert filters.post_event_direction(kl, ev["t"], 1.0860) == "long"
        assert filters.fomc_block("EURUSD", "long", ev, "long", True)
        assert filters.fomc_block("EURUSD", "short", ev, "long", True) is None
        assert filters.fomc_block("EURJPY", "long", ev, "long", True) is None
        assert filters.fomc_block("EURUSD", "long", ev, "long", False) is None


# ---------- month-end fix ----------
class TestFixReversion:
    def test_last_business_day(self):
        assert last_business_day(datetime(2026, 1, 30).date())      # Friday 30 Jan 2026 (31st is Saturday)
        assert not last_business_day(datetime(2026, 1, 29).date())
        assert not last_business_day(datetime(2026, 1, 31).date())
        assert last_business_day(datetime(2026, 4, 30).date())

    def test_window(self):
        fix = datetime(2026, 1, 30, 16, 5, tzinfo=LONDON).astimezone(timezone.utc)
        w = fix_window(fix)
        assert w and w["pre"].hour == 15 and w["exit_at"].weekday() == 0 and w["exit_at"].hour == 12  # Saturday → Monday 12:00
        assert fix_window(fix + timedelta(minutes=30)) is None
        assert fix_window(datetime(2026, 1, 29, 16, 5, tzinfo=LONDON).astimezone(timezone.utc)) is None

    def test_signal_short_after_pre_fix_rally(self):
        fix = datetime(2026, 1, 30, 16, 0, tzinfo=LONDON).astimezone(timezone.utc)
        t0 = fix - timedelta(hours=6)
        rows = []
        px = 1.0800
        for k in range(28):
            ts = t0 + timedelta(minutes=15 * k)
            if fix - timedelta(hours=1) <= ts < fix:
                px += 0.0010
            rows.append([int(ts.timestamp() * 1000), px, px + 0.0003, px - 0.0003, px, 1])
        sig = fix_signal("EURUSD", rows, 0.0030, fix + timedelta(minutes=5), px - 0.0002)
        assert sig and sig["side"] == "short" and sig["strategy"] == "fix_reversion"
        assert sig["tp"] < sig["price"] < sig["sl"] and sig["expires_at"].startswith("2026-02-02T12:00")
        assert fix_signal("EURUSD", rows, 0.0100, fix + timedelta(minutes=5), px) is None  # move < 0.6 ATR
        assert fix_signal("EURUSD", rows, 0.0030, fix + timedelta(hours=2), px) is None    # outside window

    def test_scan_fix_backtest(self):
        start = datetime(2026, 1, 26, 0, 0, tzinfo=timezone.utc)
        rows, px = [], 1.3000
        for k in range(24 * 7):
            ts = start + timedelta(hours=k)
            o = px
            ldn = ts.astimezone(LONDON)
            if ldn.hour == 15 and ldn.date() == datetime(2026, 1, 30).date():
                px -= 0.0040
            rows.append([int(ts.timestamp() * 1000), o, max(o, px) + 0.0002, min(o, px) - 0.0002, px, 1])
        atr = np.full(len(rows), 0.0030)
        out = scan_fix(rows, atr)
        assert len(out) == 1
        (i, sig), = out.items()
        assert sig["side"] == "long" and sig["tp"] > sig["price"] > sig["sl"]
        assert datetime.fromtimestamp(sig["expires_ts"], tz=LONDON).hour == 12
        assert SLOW_INFO["fix_reversion"]["horizon"] == "long" and SLOW_INFO["fix_reversion"]["bt_tf"] == "1h"


# ---------- settings & rules ----------
class TestSettings:
    def test_defaults_and_rules(self):
        s = FxSettings()
        assert s.rollover_guard and s.vol_filter_enabled and s.seasonality_bias and s.usd_regime_filter and s.fomc_rule and s.partial_tp_enabled
        assert s.currency_exposure_limit == 2 and s.max_long_positions == 2 and s.seasonality_block_pairs == ["EURUSD"]
        r = risk.trade_rules(s)
        assert r["partial_tp_enabled"] and r["partial_tp_r"] == 1.5 and r["partial_tp_pct"] == 50 and r["be_start_r"] == 1.0

    def test_update_bounds(self):
        with pytest.raises(Exception):
            FxSettingsUpdate(currency_exposure_limit=9)
        with pytest.raises(Exception):
            FxSettingsUpdate(vol_min_pct=80)
        with pytest.raises(Exception):
            FxSettingsUpdate(partial_tp_pct=90)
        assert FxSettingsUpdate(usd_regime_sma=50).usd_regime_sma == 50
        for k in ("currency_exposure_limit", "vol_min_pct", "seasonality_size_factor", "usd_regime_sma", "partial_tp_r", "trail_atr_mult"):
            assert k in fx_review.FX_GATE_KEYS

    def test_partial_lots(self):
        assert risk.partial_lots(0.10, 50) == 0.05
        assert risk.partial_lots(0.01, 50) == 0.0
        assert risk.partial_lots(0.03, 50) == 0.01


# ---------- backtest ----------
class TestBacktest:
    def _klines(self, n=400, start=1.1000):
        day = 3_600_000
        rows, px = [], start
        rng = np.random.default_rng(3)
        for i in range(n):
            o = px
            px = o + rng.normal(0, 0.0012)
            rows.append([1_700_000_000_000 + i * day, o, max(o, px) + 0.0006, min(o, px) - 0.0006, px, 100])
        return rows

    def test_partial_and_excursion(self):
        rows = self._klines()
        df = build_fx_df(rows, 14)
        sigs = {i: {"side": "long", "strategy": "ema_trend", "price": float(df["close"].iloc[i]), "sl": float(df["close"].iloc[i]) - 0.0030,
                    "tp": float(df["close"].iloc[i]) + 0.0060, "atr": 0.0015, "score": 3, "key_ts": i, "reasons": [], "indicators": {}} for i in range(220, 380, 40)}
        rules = risk.trade_rules(FxSettings(partial_tp_enabled=True, partial_tp_r=1.0, partial_tp_pct=50))
        res = simulate(df, sigs, 2.0, 100, rules, 10000, "EURUSD", start=210, weekend_flat=False)
        assert res["total_trades"] >= 1
        assert "excursion" in res and "avg_mfe_r" in res["excursion"]
        for t in res["trades"]:
            assert "mfe_r" in t and "mae_r" in t and t["mfe_r"] >= 0 and t["mae_r"] >= 0
        res_b = simulate(df, sigs, 2.0, 100, True, 10000, "EURUSD", start=210, weekend_flat=False)
        assert res_b["excursion"]["partial_closes"] == 0

    def test_time_stop(self):
        rows = self._klines(300, 1.3)
        df = build_fx_df(rows, 14)
        i = 220
        px = float(df["close"].iloc[i])
        sig = {"side": "long", "strategy": "fix_reversion", "price": px, "sl": px - 0.0500, "tp": px + 0.0500, "atr": 0.0015, "score": 3, "key_ts": i,
               "expires_ts": int(df["ts"].iloc[i + 5] / 1000), "reasons": [], "indicators": {}}
        res = simulate(df, {i: sig}, 1.0, 100, False, 10000, "EURUSD", start=210, weekend_flat=False)
        assert res["total_trades"] == 1 and res["trades"][0]["reason"] == "TIEMPO"


# ---------- API ----------
class TestApi:
    def test_meta(self, client):
        m = client.get(f"{FX}/meta", timeout=30).json()
        assert "fix_reversion" in m["strategy_keys"] and m["long_horizon_keys"] == ["fix_reversion"]
        assert m["strategy_info"]["fix_reversion"]["horizon"] == "long"

    def test_settings_roundtrip(self, client):
        orig = client.get(f"{FX}/settings", timeout=30).json()
        r = client.put(f"{FX}/settings", json={"currency_exposure_limit": 3, "vol_min_pct": 25, "seasonality_block_pairs": ["EURUSD", "GBPUSD"], "partial_tp_pct": 40}, timeout=30)
        assert r.status_code == 200
        s = r.json()["settings"] if "settings" in r.json() else r.json()
        assert s["currency_exposure_limit"] == 3 and s["vol_min_pct"] == 25 and s["seasonality_block_pairs"] == ["EURUSD", "GBPUSD"] and s["partial_tp_pct"] == 40
        bad = client.put(f"{FX}/settings", json={"currency_exposure_limit": 9}, timeout=30)
        assert bad.status_code == 422
        bad2 = client.put(f"{FX}/settings", json={"seasonality_block_pairs": ["FOOBAR", "GBPUSD"]}, timeout=30)
        assert bad2.status_code == 200 and bad2.json()["seasonality_block_pairs"] == ["GBPUSD"]
        client.put(f"{FX}/settings", json={k: orig[k] for k in ("currency_exposure_limit", "vol_min_pct", "seasonality_block_pairs", "partial_tp_pct")}, timeout=30)

    def test_market_context(self, client):
        r = client.get(f"{FX}/market/context", timeout=60)
        assert r.status_code == 200
        c = r.json()
        for k in ("exposicion_por_divisa", "rollover", "volatilidad", "estacionalidad", "regimen_usd", "fomc", "fix_reversion", "watch", "open_positions"):
            assert k in c, k
        assert c["rollover"]["window_ny"] == "16:50–17:15" and "state" in c["regimen_usd"]
        assert c["fix_reversion"]["next_fix_london"].endswith("16:00") and "XAUUSD" not in c["fix_reversion"]["pairs"]

    def test_backtest_fix_reversion(self, client):
        r = client.post(f"{FX}/backtest", json={"symbol": "EURUSD", "timeframe": "1h", "strategy": "fix_reversion"}, timeout=180)
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["strategy"] == "fix_reversion" and "excursion" in b and b["timeframe"] == "1h"

    def test_performance_has_excursion(self, client):
        r = client.get(f"{FX}/performance", timeout=60)
        assert r.status_code == 200 and "excursion" in r.json()


# ---------- paper engine tick ----------
class TestPaperTick:
    def test_partial_time_stop_and_rollover_skip(self, client):
        import importlib
        import fx.engine as fxe
        importlib.reload(fxe)

        async def go(db):
            class M:
                tickers = {"EURUSD": {"price": 1.1000, "bid": 1.0999, "ask": 1.1001}}
            e = fxe.FxEngine.__new__(fxe.FxEngine)
            e.db = fxe.PrefixedDB(db, "qa48_")
            e.market = M()
            e.live = False
            e.logs = []

            async def log(level, msg):
                e.logs.append((level, msg))

            async def tg(text, kind):
                pass
            e.log, e.tg = log, tg
            closed = []

            async def close_position(pid, price=None, reason="MANUAL"):
                closed.append((pid, reason))
            e.close_position = close_position
            await e.db.positions.delete_many({})
            await e.db.account.delete_many({})
            await e.db.account.insert_one({"_id": "main", "balance": 1000.0})
            now = datetime.now(timezone.utc)
            p = Position(symbol="EURUSD", side="long", strategy="ema_trend", timeframe="15m", entry_price=1.0900, qty=0.10, leverage=100, margin=10.0,
                         sl=1.0870, tp=1.1200, initial_sl=1.0870, atr=0.0010, fees=0.0, mark_price=1.09, opened_at=(now - timedelta(hours=2)).isoformat())
            res = await e.db.positions.insert_one(p.to_mongo())
            p.id = str(res.inserted_id)
            rules = risk.trade_rules(FxSettings(partial_tp_enabled=True, partial_tp_r=1.5, partial_tp_pct=50))
            # +3.33R: partial should fire, MFE recorded, trailing moves SL
            await e._manage_paper_position(p, 1.1000, rules, now)
            d = await e.db.positions.find_one({"_id": res.inserted_id})
            acc = await e.db.account.find_one({"_id": "main"})
            out = {"qty": d["qty"], "partial": d["partial_done"], "mfe": d["mfe_r"], "sl": d["sl"], "balance": acc["balance"], "partial_gross": d["partial_gross"], "closed": list(closed)}
            # rollover: SL hit is NOT evaluated
            p2 = Position.from_mongo(d)
            await e._manage_paper_position(p2, 1.0800, rules, now, rollover=True)
            out["closed_rollover"] = list(closed)
            # same price outside rollover → closed as TRAILING (sl was moved to breakeven)
            await e._manage_paper_position(Position.from_mongo(await e.db.positions.find_one({"_id": res.inserted_id})), 1.0800, rules, now)
            out["closed_after"] = list(closed)
            # time stop
            p3 = Position(symbol="EURUSD", side="short", strategy="fix_reversion", timeframe="15m", entry_price=1.1000, qty=0.10, leverage=100, margin=10.0,
                          sl=1.1050, tp=1.0900, initial_sl=1.1050, atr=0.0010, fees=0.0, mark_price=1.09, opened_at=now.isoformat(), expires_at=(now - timedelta(minutes=1)).isoformat(), horizon="long")
            r3 = await e.db.positions.insert_one(p3.to_mongo())
            p3.id = str(r3.inserted_id)
            await e._manage_paper_position(p3, 1.1000, rules, now)
            out["closed_time"] = list(closed)
            await e.db.positions.delete_many({})
            await e.db.account.delete_many({})
            return out

        out = _db_run(go)
        assert out["qty"] == 0.05 and out["partial"] and out["mfe"] >= 3.3 and out["partial_gross"] > 0
        assert out["balance"] > 1000.0 and out["sl"] >= 1.0900 and out["closed"] == []
        assert out["closed_rollover"] == []
        assert len(out["closed_after"]) == 1 and out["closed_after"][0][1] == "TRAILING"
        assert len(out["closed_time"]) == 2 and out["closed_time"][1][1] == "TIEMPO"

    def test_blocks_exposure_and_slots(self):
        import fx.engine as fxe

        async def go(db):
            class M:
                tickers = {}
            e = fxe.FxEngine.__new__(fxe.FxEngine)
            e.db = fxe.PrefixedDB(db, "qa48b_")
            e.market = M()
            e.live = False
            e.cfg = None
            e.hfm = {"down_since": None}
            await e.db.positions.delete_many({})
            for sym in ("EURUSD", "GBPUSD"):
                await e.db.positions.insert_one(Position(symbol=sym, side="long", strategy="ema_trend", timeframe="15m", entry_price=1.1, qty=0.1, leverage=100,
                                                         margin=10, sl=1.09, tp=1.12, initial_sl=1.09, atr=0.001, fees=0.0, mark_price=1.1, opened_at=datetime.now(timezone.utc).isoformat()).to_mongo())
            s = FxSettings(sessions_allowed=[], max_positions=5, currency_exposure_limit=2, rollover_guard=False, max_long_positions=1)
            acc = {"daily_paused": False}
            from fx.market import market_open
            if not market_open():
                return None
            r1 = await e._blocks("AUDUSD", s, acc, "long")
            r2 = await e._blocks("AUDUSD", s, acc, "short")
            r3 = await e._blocks("EURUSD", s, acc, "short")
            await e.db.positions.insert_one(Position(symbol="USDJPY", side="long", strategy="fix_reversion", timeframe="15m", entry_price=150, qty=0.1, leverage=100,
                                                     margin=10, sl=149, tp=152, initial_sl=149, atr=0.5, fees=0.0, mark_price=150, opened_at=datetime.now(timezone.utc).isoformat(), horizon="long").to_mongo())
            r4 = await e._blocks("EURJPY", s, acc, "long", horizon="long")
            r5 = await e._blocks("EURJPY", s, acc, "long")
            await e.db.positions.delete_many({})
            return r1, r2, r3, r4, r5

        out = _db_run(go)
        if out is None:
            pytest.skip("market closed")
        r1, r2, r3, r4, r5 = out
        assert r1[1] == "EXPOSICION" and "USD" in r1[0]
        assert r2[0] is None
        assert r3[1] == "BLOQUEADA"
        assert r4[1] == "BLOQUEADA" and "largo" in r4[0].lower()
        assert r5[0] is None
