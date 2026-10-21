"""Iteration 22 – plan scenario names (Prudente/Realista/Ambicioso, keys unchanged), news agent AI savings (fingerprint skip + idle cadence),
AI call counter (ai_usage) in both dashboards. Run with `-n 0`."""
import os
import sys
import asyncio
import pytest
import requests

sys.path.insert(0, "/app/backend")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
FX = f"{BASE_URL}/api/fx"


@pytest.fixture(scope="module")
def s():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": "BlackCat2233@"}, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"login failed {r.status_code}")
    sess = requests.Session()
    sess.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return sess


class TestPlanScenarioNames:
    def test_backend_names_keys_unchanged(self):
        import plan
        from fx import plan as fx_plan
        for mod in (plan, fx_plan):
            assert list(mod.SCENARIOS) == ["conservador", "base", "optimista"]
            assert [v["name"] for v in mod.SCENARIOS.values()] == ["Prudente", "Realista", "Ambicioso"]
            assert not any(n in ("Conservador", "Base", "Optimista") for n in (v["name"] for v in mod.SCENARIOS.values()))
        assert plan.SCENARIOS["optimista"]["rate"] == 6.0 and fx_plan.SCENARIOS["optimista"]["rate"] == 5.0

    def test_api_plan_names(self, s):
        r = s.post(f"{BASE_URL}/api/plan", json={"initial_capital": 500, "monthly_deposit": 0, "target_monthly": 1000, "scenario": "optimista"}, timeout=240)
        assert r.status_code == 200, r.text
        d = r.json()
        names = {x["key"]: x["name"] for x in d["scenarios"]}
        assert names["conservador"] == "Prudente" and names["base"] == "Realista" and names["optimista"] == "Ambicioso" and names["backtest"] == "Según backtest"
        assert d["selected"] == "optimista" and d["projection"]["rate_pct"] == 6.0
        # saved scenario key still "optimista" → restore base
        assert s.get(f"{BASE_URL}/api/settings", timeout=30).json()["plan_scenario"] == "optimista"
        s.post(f"{BASE_URL}/api/plan", json={"initial_capital": 500, "monthly_deposit": 0, "target_monthly": 1000, "scenario": "base"}, timeout=240)


class _FakeCol:
    def __init__(self):
        self.ops = []

    async def update_one(self, *a, **k):
        self.ops.append(("update", a, k))

    async def insert_one(self, *a, **k):
        self.ops.append(("insert", a, k))

    async def delete_many(self, *a, **k):
        self.ops.append(("delete", a, k))

    async def find_one(self, *a, **k):
        return None


class _FakeDB:
    def __init__(self):
        self.news, self.news_history, self.ai_usage = _FakeCol(), _FakeCol(), _FakeCol()


class _FakeEngine:
    running = True

    def __init__(self, symbols):
        self._symbols = symbols
        self.logs = []

    async def get_settings(self):
        from types import SimpleNamespace
        return SimpleNamespace(symbols=self._symbols)

    async def log(self, level, msg):
        self.logs.append((level, msg))

    async def tg(self, *a, **k):
        pass


HEADLINES = [{"source": "CoinDesk", "title": "Bitcoin steady as ETF inflows continue", "summary": "", "published": "2026-10-21T10:00:00+00:00", "symbols": []},
             {"source": "The Block", "title": "ETH staking hits record", "summary": "x", "published": "2026-10-21T09:00:00+00:00", "symbols": []}]
EVENTS = [{"title": "CPI m/m", "time": "2026-10-22T12:30:00+00:00", "impact": "ALTO", "forecast": "0.2%", "previous": "0.1%", "country": "USD"}]
ANALYSIS = {"market": {"sentiment": 10, "risk": "MEDIO", "summary": "ok"}, "pairs": {}, "alerts": []}


def _agent(cls, symbols=("BTCUSDT",), headlines=HEADLINES, events=EVENTS):
    import ai_advisor
    a = cls(_FakeDB(), _FakeEngine(list(symbols)))
    from types import SimpleNamespace
    a.cfg = SimpleNamespace(news_enabled=True, news_interval_min=20, news_countries=["USD"])
    a.calls = {"analyze": 0}
    a.usage = []

    async def fh():
        return [dict(h) for h in headlines]

    async def fe():
        return [dict(e) for e in events]

    async def an(h, e, sym):
        a.calls["analyze"] += 1
        return {**ANALYSIS, "pairs": {}, "alerts": list(ANALYSIS["alerts"])}

    async def hook(kind, skipped=False):
        a.usage.append((kind, skipped))

    a.fetch_headlines, a.fetch_events, a.analyze = fh, fe, an
    ai_advisor.set_usage_hook(hook)
    return a


class TestNewsAgentSavings:
    def test_fingerprint_stable_and_sensitive(self):
        from news import NewsAgent
        fp = NewsAgent.fingerprint
        base = fp(HEADLINES, EVENTS, ["BTCUSDT"])
        aged = [{**h, "published": "2026-10-21T08:00:00+00:00"} for h in HEADLINES]  # only ages differ → same
        assert fp(aged, EVENTS, ["BTCUSDT"]) == base
        assert fp(list(reversed(HEADLINES)), EVENTS, ["BTCUSDT"]) == base  # order-insensitive
        assert fp(HEADLINES[:1], EVENTS, ["BTCUSDT"]) != base  # headline dropped
        assert fp(HEADLINES, [{**EVENTS[0], "actual": "0.4%"}], ["BTCUSDT"]) != base  # result published
        assert fp(HEADLINES, EVENTS, ["BTCUSDT", "ETHUSDT"]) != base  # pairs changed

    @pytest.mark.parametrize("cls_path", ["news.NewsAgent", "fx.news.FxNewsAgent"])
    def test_refresh_skips_ai_when_unchanged(self, cls_path):
        import importlib
        mod, name = cls_path.rsplit(".", 1)
        cls = getattr(importlib.import_module(mod), name)
        a = _agent(cls)
        try:
            d1 = asyncio.run(a.refresh())
            assert a.calls["analyze"] == 1 and d1["skipped_ai"] == 0 and d1["analysis_at"] == d1["updated_at"] and d1["fingerprint"]
            d2 = asyncio.run(a.refresh())
            assert a.calls["analyze"] == 1, "AI was called although nothing changed"
            assert d2["skipped_ai"] == 1 and d2["market"] == d1["market"] and d2["analysis_at"] == d1["analysis_at"] and d2["updated_at"] >= d1["updated_at"]
            assert (a.KIND, True) in a.usage
            # manual refresh forces a new analysis
            d3 = asyncio.run(a.refresh(force=True))
            assert a.calls["analyze"] == 2 and d3["skipped_ai"] == 0
            # new headline → analysed again
            a2 = _agent(cls, headlines=HEADLINES + [{"source": "Decrypt", "title": "Exchange halts withdrawals", "summary": "", "published": "2026-10-21T11:00:00+00:00", "symbols": []}])
            a2.latest = d3
            asyncio.run(a2.refresh())
            assert a2.calls["analyze"] == 1
        finally:
            import ai_advisor
            ai_advisor.set_usage_hook(None)

    def test_idle_cadence(self):
        from news import NewsAgent, IDLE_INTERVAL_MIN
        from fx.news import FxNewsAgent
        for cls in (NewsAgent, FxNewsAgent):
            a = _agent(cls)
            a.engine.running = True
            assert a.interval_min() == 20
            a.engine.running = False
            assert a.interval_min() == IDLE_INTERVAL_MIN == 60
            a.cfg.news_interval_min = 90
            assert a.interval_min() == 90  # never faster than configured

    def test_ai_usage_snapshot(self):
        from ai_usage import AiUsage
        u = AiUsage(_FakeDB())
        for k in ("signal", "signal", "news", "advisor", "fx-signal", "fx-news", "fx-news-trade", "fx-advisor", "ping"):
            asyncio.run(u.record(k))
        asyncio.run(u.record("news", skipped=True))
        c = u.snapshot("crypto")
        assert (c["signals"], c["news"], c["news_trades"], c["reviews"], c["skipped_news"], c["total"], c["total_all"]) == (2, 1, 0, 1, 1, 4, 9)
        f = u.snapshot("fx")
        assert (f["signals"], f["news"], f["news_trades"], f["reviews"], f["skipped_news"], f["total"]) == (1, 1, 1, 1, 0, 4)
        assert u.db.ai_usage.ops and u.db.ai_usage.ops[-1][1][1]["$inc"] == {"skipped.news": 1}

    def test_advisor_kind_per_market(self):
        import ai_advisor
        c = ai_advisor._chat("sys", "signal")
        assert c._kind == "signal"
        src = open("/app/backend/ai_advisor.py").read()
        assert '"fx-advisor" if market is FX_MARKET else "advisor"' in src


class TestUsageApi:
    def test_status_has_usage_and_news_fields(self, s):
        d = s.get(f"{BASE_URL}/api/dashboard", timeout=30).json()
        u = d["status"]["ai_usage"]
        assert set(u) >= {"signals", "news", "news_trades", "reviews", "skipped_news", "total", "total_all", "date"}
        assert "interval_min" in d["news"] and "analysis_at" in d["news"]
        f = s.get(f"{FX}/dashboard", timeout=30).json()
        assert set(f["status"]["ai_usage"]) >= {"signals", "news", "total", "total_all"}
        assert "interval_min" in f["news"]
        # idle cadence visible: FX bot stopped → 60 (unless the user left it running)
        if not f["status"]["running"] and f["news"].get("ready"):
            assert f["news"]["interval_min"] == 60

    def test_manual_refresh_counts_and_forces(self, s):
        before = s.get(f"{BASE_URL}/api/dashboard", timeout=30).json()["status"]["ai_usage"]
        r = s.post(f"{BASE_URL}/api/news/refresh", timeout=150)
        if r.status_code != 200:
            pytest.skip(f"news refresh unavailable: {r.status_code} {r.text[:120]}")
        latest = r.json()["latest"]
        assert latest["skipped_ai"] == 0 and latest["analysis_at"] == latest["updated_at"] and latest["fingerprint"]
        after = s.get(f"{BASE_URL}/api/dashboard", timeout=30).json()["status"]["ai_usage"]
        assert after["news"] == before["news"] + 1 and after["total_all"] >= before["total_all"] + 1
