# Iteration 10: walk-forward optimizer (API + unit), fetch_history pagination, optimize/backtest/plan regression,
# shadow risk_factor sizing, news first-seen alerts / 24h critical TTL / risk validation / 30d history cap
import os
import sys
import time
import asyncio
from datetime import datetime, timezone, timedelta

import pytest
import requests
from dotenv import load_dotenv

sys.path.insert(0, "/app/backend")
load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
PASSWORD = "BlackCat2233@"
VERDICTS = {"ROBUSTO", "DUDOSO", "SOBREAJUSTADO", "NO_RENTABLE", "INSUFICIENTE"}
FOLD_METRICS = ("trades", "expectancy_r", "return_pct", "profit_factor", "max_drawdown", "sqn", "win_rate")
AGG_METRICS = ("trades", "win_rate", "expectancy_r", "sqn", "total_r", "profit_factor", "return_pct", "max_drawdown")


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"password": PASSWORD}, timeout=20)
    if r.status_code != 200:
        pytest.skip(f"login failed {r.status_code}")
    s.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return s


@pytest.fixture(scope="module")
def wf_btc(client):
    t = time.time()
    r = client.post(f"{BASE_URL}/api/optimize/walk-forward", json={"symbol": "BTCUSDT"}, timeout=90)
    elapsed = time.time() - t
    assert r.status_code == 200, r.text[:300]
    return r.json(), elapsed


# ---------- API: walk-forward ----------
class TestWalkForwardAPI:
    def test_structure(self, wf_btc):
        d, elapsed = wf_btc
        assert elapsed < 60
        assert d["symbol"] == "BTCUSDT" and d["timeframe"]
        assert d["candles"] > 1000, f"pagination failed: {d['candles']}"
        assert d["oos_len"] == 250
        assert d["is_len"] == max(600, min(1000, d["candles"] // 2))
        assert d["verdict"] in VERDICTS and d["verdict_text"]
        assert isinstance(d["beats_baseline"], bool)
        assert isinstance(d["params_unique"], int) and isinstance(d["params_stable"], bool)
        assert d["wfe"] is None or isinstance(d["wfe"], (int, float))
        if d["is_expectancy_r"] <= 0:
            assert d["wfe"] is None
        for agg in ("oos", "baseline_oos"):
            for k in AGG_METRICS:
                assert k in d[agg], f"{agg}.{k}"
        for c in ("oos_curve", "baseline_curve"):
            assert isinstance(d[c], list) and 0 < len(d[c]) <= 245
            assert {"time", "equity"} <= set(d[c][0])
        assert "applied" in d

    def test_folds(self, wf_btc):
        d, _ = wf_btc
        folds = d["folds"]
        assert len(folds) >= 1
        if d["candles"] == 2000:
            assert len(folds) == 4
        for i, f in enumerate(folds):
            assert f["fold"] == i + 1
            for k in ("is_start", "split", "oos_end", "is_candles", "oos_candles", "params", "is", "oos", "baseline_oos"):
                assert k in f
            if f["params"] is not None:
                assert set(f["params"]) == {"sl_atr", "tp_atr", "atr_period"}
            for k in FOLD_METRICS:
                assert k in f["oos"] and k in f["baseline_oos"]
            assert f["oos_candles"] == 250
            assert f["split"] < f["oos_end"] and f["is_start"] < f["split"]
        # contiguous: next split is one candle after previous oos_end (1h)
        for a, b in zip(folds, folds[1:]):
            gap = datetime.fromisoformat(b["split"]) - datetime.fromisoformat(a["oos_end"])
            assert gap == timedelta(hours=1), gap
        assert sum(f["oos"]["trades"] for f in folds) == d["oos"]["trades"]

    def test_verdict_consistent(self, wf_btc):
        import optimizer
        d, _ = wf_btc
        assert optimizer._verdict(d["oos"], d["baseline_oos"], d["is_expectancy_r"], d["wfe"]) == d["verdict"]

    def test_invalid_symbol(self, client):
        r = client.post(f"{BASE_URL}/api/optimize/walk-forward", json={"symbol": "FOOUSDT"}, timeout=20)
        assert r.status_code == 400

    def test_requires_auth(self):
        r = requests.post(f"{BASE_URL}/api/optimize/walk-forward", json={"symbol": "BTCUSDT"}, timeout=20)
        assert r.status_code in (401, 403)

    def test_cached_second_call_fast(self, client, wf_btc):
        t = time.time()
        r = client.post(f"{BASE_URL}/api/optimize/walk-forward", json={"symbol": "BTCUSDT"}, timeout=90)
        assert r.status_code == 200 and r.json()["candles"] == wf_btc[0]["candles"]
        assert time.time() - t < 30


# ---------- Unit: _verdict rules ----------
def _o(trades, exp, pf):
    return {"trades": trades, "expectancy_r": exp, "profit_factor": pf}


class TestVerdictUnit:
    def test_rules(self):
        from optimizer import _verdict
        b = _o(20, 0, 1)
        assert _verdict(_o(9, 1.0, 3), b, 0.5, 2) == "INSUFICIENTE"
        assert _verdict(_o(10, 0.2, 1.1), b, 0.3, 0.66) == "ROBUSTO"
        assert _verdict(_o(10, 0.2, 1.5), b, -0.1, None) == "DUDOSO"
        assert _verdict(_o(10, 0.1, 1.5), b, 0.5, 0.2) == "DUDOSO"
        assert _verdict(_o(10, 0.05, 1.05), b, 0.1, 0.5) == "DUDOSO"
        assert _verdict(_o(10, -0.1, 0.8), b, 0.3, None) == "SOBREAJUSTADO"
        assert _verdict(_o(10, -0.1, 0.8), b, 0.0, None) == "NO_RENTABLE"
        assert _verdict(_o(10, 0.0, 1.0), b, -0.2, None) == "NO_RENTABLE"


# ---------- Unit: fetch_history + walk_forward with real candles ----------
@pytest.fixture(scope="module")
def history():
    from market import MarketData

    async def go():
        md = MarketData()
        await md.detect()
        a = await md.fetch_history("ETHUSDT", "1h", 2000)
        t = time.time()
        b = await md.fetch_history("ETHUSDT", "1h", 2000)
        dt = time.time() - t
        prov = md.provider
        await md.client.aclose()
        return a, b, dt, prov
    return asyncio.run(go())


class TestHistoryAndWalkForwardUnit:
    def test_fetch_history(self, history):
        a, b, dt, prov = history
        assert len(a) >= 1900, len(a)
        ts = [k[0] for k in a]
        assert ts == sorted(ts) and len(set(ts)) == len(ts)
        assert all(y - x == 3600_000 for x, y in zip(ts, ts[1:])), "gaps in history"
        assert b == a and dt < 0.05

    def test_walk_forward_unit(self, history):
        import optimizer
        k = history[0]
        d = optimizer.walk_forward(k, "all", 1.0, 3, True, 10000.0, "ETHUSDT")
        n = len(k)
        assert d["candles"] == n and d["is_len"] == max(600, min(1000, n // 2))
        assert len(d["folds"]) == len(range(d["is_len"], n - 250 + 1, 250))
        assert d["verdict"] == optimizer._verdict(d["oos"], d["baseline_oos"], d["is_expectancy_r"], d["wfe"])

    def test_walk_forward_short_history(self, history):
        import optimizer
        d = optimizer.walk_forward(history[0][:700], "all", 1.0, 3, True, 10000.0, "ETHUSDT")
        assert d["folds"] == [] and d["verdict"] == "INSUFICIENTE"


# ---------- Regression: optimize / backtest / plan ----------
class TestRegression:
    def test_optimize(self, client):
        r = client.post(f"{BASE_URL}/api/optimize", json={"symbol": "SOLUSDT"}, timeout=90)
        assert r.status_code == 200, r.text[:200]
        d = r.json()
        assert d["combos"] == 54 and len(d["grid"]) == 54 and d["candles"] == 1000
        assert d["period_start"] and d["period_end"] and d["baseline"] and "best" in d

    def test_backtest(self, client):
        r = client.post(f"{BASE_URL}/api/backtest", json={"symbol": "BTCUSDT"}, timeout=90)
        assert r.status_code == 200, r.text[:200]
        d = r.json()
        assert d["period_start"] and d["period_end"]
        assert datetime.fromisoformat(d["period_end"]) > datetime.fromisoformat(d["period_start"])

    def test_plan(self, client):
        st = client.get(f"{BASE_URL}/api/settings", timeout=20).json()
        body = {"initial_capital": 500, "monthly_deposit": st.get("plan_monthly_deposit", 0),
                "target_monthly": st.get("plan_target_monthly", 1000), "scenario": st.get("plan_scenario", "base")}
        r = client.post(f"{BASE_URL}/api/plan", json=body, timeout=120)
        assert r.status_code == 200, r.text[:200]
        assert isinstance(r.json(), dict) and r.json()

    def test_simulate_defaults(self, history):
        from indicators import build_df
        from backtest import simulate, scan_signals, _iso
        df = build_df(history[0][-1000:], 14)
        res = simulate(df, scan_signals(df, "all", None, "strict", ()), 1.0, 3, True, 10000.0, "ETHUSDT")
        assert res["period_start"] == _iso(df["ts"].values[210])
        assert res["period_end"] == _iso(df["ts"].values[-1])


# ---------- Unit: shadow risk_factor ----------
class _Mkt:
    def __init__(self, p):
        self.tickers = {"BTCUSDT": {"price": p}}


class _Settings:
    risk_per_trade = 1.0
    leverage = 3
    timeframe = "1h"


def _test_db():
    from motor.motor_asyncio import AsyncIOMotorClient
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return c, c[os.environ["DB_NAME"] + "_iter10_tests"]


class TestShadowRiskFactor:
    def test_qty_halved(self):
        import shadow

        async def go():
            c, db = _test_db()
            eng = type("E", (), {})()
            eng.market, eng.db = _Mkt(60000.0), db
            sig = {"side": "long", "price": 60000.0, "sl": 59000.0, "tp": 62000.0, "atr": 500.0, "strategy": "trend"}
            a = await shadow.open_shadow(eng, "TEST_1", "BTCUSDT", sig, _Settings(), "NOTICIAS", 10000.0, risk_factor=1.0)
            b = await shadow.open_shadow(eng, "TEST_2", "BTCUSDT", sig, _Settings(), "NOTICIAS", 10000.0, risk_factor=0.5)
            stored = await db.shadow_positions.find_one({"signal_id": "TEST_2"})
            await db.shadow_positions.delete_many({})
            c.close()
            return a, b, stored
        a, b, stored = asyncio.run(go())
        assert a and b
        assert a["risk_factor"] == 1.0 and stored["risk_factor"] == 0.5
        assert abs(b["qty"] / a["qty"] - 0.5) < 0.05, (a["qty"], b["qty"])


# ---------- Unit: news first-seen, history cap, 24h TTL, risk validation ----------
def _agent(db=None, engine=None):
    import news
    import config
    a = news.NewsAgent(db, engine)
    a.cfg = config.AppConfig()
    return a


class TestNewsUnit:
    def test_risk(self):
        from news import _risk
        assert _risk("EXTREMO") == "MEDIO" and _risk(None) == "MEDIO" and _risk("alto") == "ALTO" and _risk("BAJO") == "BAJO"

    def test_analyze_invalid_pair_risk(self, monkeypatch):
        import news

        async def fake_ask(chat, prompt):
            return ('{"market":{"sentiment":10,"risk":"EXTREMO","summary":"s"},"pairs":{"BTCUSDT":{"sentiment":5,"risk":"EXTREMO","note":"n"},'
                    '"ETHUSDT":{"sentiment":5,"risk":null},"SOLUSDT":{"risk":"alto"},"FOOUSDT":{"risk":"ALTO"}},"alerts":[]}')
        monkeypatch.setattr(news, "_ask", fake_ask)
        monkeypatch.setattr(news, "_chat", lambda *a, **k: None)
        a = _agent()
        out = asyncio.run(a.analyze([], [], ["BTCUSDT", "ETHUSDT", "SOLUSDT"]))
        assert out["market"]["risk"] == "MEDIO"
        assert out["pairs"]["BTCUSDT"]["risk"] == "MEDIO" and out["pairs"]["ETHUSDT"]["risk"] == "MEDIO"
        assert out["pairs"]["SOLUSDT"]["risk"] == "ALTO" and "FOOUSDT" not in out["pairs"]

    def test_critical_ttl_24h(self):
        a = _agent()
        now = datetime.now(timezone.utc)
        a.latest = {"market": {"sentiment": 0, "risk": "BAJO", "summary": ""}, "pairs": {}, "events": [], "headlines": [],
                    "updated_at": now.isoformat(),
                    "alerts": [{"symbol": "XRPUSDT", "severity": "CRITICA", "title": "old", "at": (now - timedelta(hours=25)).isoformat()},
                               {"symbol": "SOLUSDT", "severity": "CRITICA", "title": "new", "at": (now - timedelta(hours=23)).isoformat()}]}
        s = a.summary()
        assert s["critical"] == ["SOLUSDT"]
        assert a.gate("XRPUSDT")[0] is None
        assert a.gate("SOLUSDT")[0] and "noticia crítica" in a.gate("SOLUSDT")[0]

    def test_refresh_first_seen_and_history_cap(self, monkeypatch):
        import news
        import models

        t0 = "2026-01-01T00:00:00+00:00"

        async def fake_analyze(self, h, e, s):
            return {"market": {"sentiment": 0, "risk": "BAJO", "summary": "x"}, "pairs": {},
                    "alerts": [{"symbol": "BTCUSDT", "severity": "ALTA", "title": "A", "why": "", "key": "K1", "at": models.now_iso()},
                               {"symbol": "ETHUSDT", "severity": "ALTA", "title": "B", "why": "", "key": "K2", "at": models.now_iso()}]}

        async def empty(self):
            return []

        async def noop(*a, **k):
            return None

        monkeypatch.setattr(news.NewsAgent, "analyze", fake_analyze)
        monkeypatch.setattr(news.NewsAgent, "fetch_headlines", empty)
        monkeypatch.setattr(news.NewsAgent, "fetch_events", empty)
        monkeypatch.setattr(news.notify, "notify", noop)

        class Eng:
            async def get_settings(self):
                return type("S", (), {"symbols": ["BTCUSDT", "ETHUSDT"]})()
            log = staticmethod(noop)

        async def go():
            c, db = _test_db()
            await db.news_history.delete_many({})
            await db.news_history.insert_one({"at": "2020-01-01T00:00:00+00:00", "market": {}, "alerts": []})
            a = _agent(db, Eng())
            a.latest = {"alerts": [{"key": "K1", "at": t0}]}
            doc = await a.refresh()
            old = await db.news_history.count_documents({"at": "2020-01-01T00:00:00+00:00"})
            total = await db.news_history.count_documents({})
            await db.news_history.delete_many({})
            await db.news.delete_many({})
            await a.client.aclose()
            c.close()
            return doc, old, total
        doc, old, total = asyncio.run(go())
        by = {x["key"]: x["at"] for x in doc["alerts"]}
        assert by["K1"] == t0
        assert by["K2"] != t0 and datetime.fromisoformat(by["K2"]) > datetime.fromisoformat(t0)
        assert old == 0 and total == 1
