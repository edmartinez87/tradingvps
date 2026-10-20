# Iteration 14: funding interval per pair (normalization to 8h, market intervals, watchlist) + server.py split into routers
# (cron / weekly / walk-forward keep the same contract). Run with: pytest tests/test_iter14_funding_interval_routers.py -n 0
import os
import sys
import uuid
import asyncio
from types import SimpleNamespace

import pytest
import requests
from dotenv import load_dotenv

sys.path.insert(0, "/app/backend")
load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

import funding  # noqa: E402

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
PASSWORD = "BlackCat2233@"
SECRET = os.environ.get("WEBHOOK_CRON_SECRET")


def cfg(**over):
    base = dict(funding_enabled=True, funding_block_pct=0.10, funding_reduce_pct=0.05, funding_reduce=True, funding_size_factor=0.5)
    return SimpleNamespace(**{**base, **over})


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"password": PASSWORD}, timeout=20)
    if r.status_code != 200:
        pytest.skip(f"login failed {r.status_code}")
    s.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return s


# ---------- Unit: normalization ----------
class TestNormalization:
    def test_per_8h(self):
        assert funding.per_8h(0.0005, 4) == pytest.approx(0.001)
        assert funding.per_8h(0.0005, 1) == pytest.approx(0.004)
        assert funding.per_8h(0.0005, 8) == pytest.approx(0.0005)
        assert funding.per_8h(0.0005, None) == pytest.approx(0.0005)
        assert funding.per_8h(0.0005, 0) == pytest.approx(0.0005)

    def test_level_uses_interval(self):
        c = cfg()
        assert funding.level(0.0006, c) == "ALTO"
        assert funding.level(0.0006, c, 4) == "EXTREMO"
        assert funding.level(0.0002, c, 1) == "EXTREMO"
        assert funding.level(0.0002, c, 8) == "NORMAL"
        assert funding.level(0.0003, c, 4) == "ALTO"

    def test_assess_fields(self):
        a = funding.assess(0.0005, "long", cfg(), 4)
        assert a["interval_h"] == 4 and a["rate_pct"] == 0.05 and a["rate_8h_pct"] == 0.1
        assert a["level"] == "EXTREMO" and a["against"] is True
        assert a["annualized_pct"] == pytest.approx(0.05 * 6 * 365, rel=1e-3)
        b = funding.assess(0.0005, "long", cfg(), 8)
        assert b["interval_h"] == 8 and b["rate_8h_pct"] == 0.05 and b["level"] == "ALTO"
        assert funding.assess(0.0005, "long", cfg(), 8.0)["interval_h"] == 8

    def test_gate_blocks_on_normalized_extreme(self):
        r, f = funding.gate(0.0006, "long", cfg(), 4)
        assert r == "funding extremo en contra (+0.0600%/4h ≈ +0.1200%/8h · largos pagan)" and f == 1.0
        assert funding.gate(0.0006, "long", cfg(), 8) == (None, 0.5)
        assert funding.gate(0.0003, "long", cfg(), 4) == (None, 0.5)
        assert funding.gate(0.0003, "long", cfg(), 8) == (None, 1.0)
        assert funding.gate(-0.0006, "short", cfg(), 1)[0].startswith("funding extremo en contra (-0.0600%/1h ≈ -0.4800%/8h")
        assert funding.gate(0.0006, "short", cfg(), 4) == (None, 1.0)

    def test_gate_8h_text_unchanged(self):
        r, _ = funding.gate(0.0012, "long", cfg())
        assert r == "funding extremo en contra (+0.1200%/8h · largos pagan)"

    def test_prompt_line_mentions_cycle(self):
        line = funding.prompt_line(funding.assess(0.0005, "long", cfg(), 4))
        assert "+0.0500%/4h ≈ +0.1000%/8h" in line and "se liquida cada 4h" in line and "nivel EXTREMO" in line and "EN CONTRA" in line
        line8 = funding.prompt_line(funding.assess(0.0005, "long", cfg(), 8))
        assert "/8h" in line8 and "≈ +" in line8 and "se liquida" not in line8 and "nivel ALTO" in line8
        assert funding.prompt_line(funding.assess(0.0, "short", cfg(), 4)) == "Funding rate: 0% (4h) · neutro"


# ---------- Market: intervals from the exchange ----------
class TestMarketIntervals:
    def test_fetch_intervals_and_tickers(self):
        from market import MarketData

        async def go():
            m = MarketData()
            try:
                await m.detect()
                iv = await m.fetch_funding_intervals()
                t = await m.fetch_tickers()
                ts = m._intervals_ts
                await m.fetch_funding_intervals()
                return iv, t, ts == m._intervals_ts
            finally:
                await m.client.aclose()

        iv, tickers, cached = asyncio.run(go())
        assert iv.get("BTCUSDT") == 8 and len(iv) > 100
        assert all(v in (1, 2, 4, 8) for v in iv.values())
        assert cached is True
        assert tickers["BTCUSDT"]["funding_interval_h"] == 8
        assert all("funding_interval_h" in t for t in tickers.values())

    def test_unknown_symbol_defaults_to_8h(self):
        from market import MarketData

        async def go():
            m = MarketData()
            try:
                m.provider = "bitget"
                m.funding_intervals, m._intervals_ts = {"BTCUSDT": 8}, 10 ** 12
                t = await m.fetch_tickers()
                return t["ETHUSDT"]["funding_interval_h"], t["BTCUSDT"]["funding_interval_h"]
            finally:
                await m.client.aclose()

        assert asyncio.run(go()) == (8, 8)


# ---------- API: dashboard watchlist ----------
class TestWatchlist:
    def test_watchlist_interval_and_level(self, client):
        c = client.get(f"{BASE_URL}/api/config", timeout=20).json()
        wl = client.get(f"{BASE_URL}/api/dashboard", timeout=30).json()["watchlist"]
        assert wl
        for w in wl:
            assert w["funding_interval_h"] in (1, 2, 4, 8)
            assert w["funding_level"] == funding.level(w["funding_rate"], SimpleNamespace(**c), w["funding_interval_h"])


# ---------- Routers: same contract after the split ----------
class TestRouters:
    def test_openapi_routes_present(self):
        try:
            paths = requests.get("http://localhost:8001/openapi.json", timeout=10).json()["paths"]
        except Exception:
            pytest.skip("backend not reachable on localhost:8001")
        for p in ("/api/cron/ai-review", "/api/cron/walk-forward", "/api/cron/weekly-summary", "/api/weekly-summary",
                  "/api/weekly-summary/send", "/api/optimize/walk-forward", "/api/walk-forward/check", "/api/dashboard", "/api/optimize"):
            assert p in paths, p

    def test_protected_routes_require_auth(self):
        for p in ("/api/weekly-summary", "/api/walk-forward/check"):
            assert requests.get(f"{BASE_URL}{p}", timeout=20).status_code in (401, 403), p
        assert requests.post(f"{BASE_URL}/api/optimize/walk-forward", json={"symbol": "BTCUSDT"}, timeout=20).status_code in (401, 403)

    def test_weekly_preview(self, client):
        d = client.get(f"{BASE_URL}/api/weekly-summary", timeout=60).json()
        assert "text" in d and "Resumen semanal" in d["text"] and "last_sent_at" in d

    def test_walk_forward_check_status(self, client):
        d = client.get(f"{BASE_URL}/api/walk-forward/check", timeout=20).json()
        assert set(d) >= {"job", "latest", "auto_remove"} and d["job"]["status"] in ("idle", "running", "done", "error")

    def test_walk_forward_invalid_symbol(self, client):
        assert client.post(f"{BASE_URL}/api/optimize/walk-forward", json={"symbol": "NOPEUSDT"}, timeout=20).status_code in (400, 422)

    def test_cron_auth_and_idempotency(self):
        assert requests.post(f"{BASE_URL}/api/cron/weekly-summary", json={}, timeout=20).status_code == 401
        assert requests.post(f"{BASE_URL}/api/cron/ai-review", json={}, headers={"Authorization": "Bearer nope"}, timeout=20).status_code == 401
        h = {"Authorization": f"Bearer {SECRET}"}
        assert requests.post(f"{BASE_URL}/api/cron/ai-review", json=[1, 2], headers=h, timeout=20).status_code == 400
        assert requests.post(f"{BASE_URL}/api/cron/walk-forward", data="not json", headers={**h, "Content-Type": "application/json"}, timeout=20).status_code == 400
        rid = f"iter14-{uuid.uuid4()}"
        r1 = requests.post(f"{BASE_URL}/api/cron/ai-review", json={"run_id": rid}, headers=h, timeout=20).json()
        r2 = requests.post(f"{BASE_URL}/api/cron/ai-review", json={"run_id": rid}, headers=h, timeout=20).json()
        assert r1["accepted"] is True and "scheduled" in r1 and r1.get("duplicate") is not True
        assert r2 == {"accepted": True, "duplicate": True}
        r3 = requests.post(f"{BASE_URL}/api/cron/weekly-summary", json={}, headers={**h, "X-Webhook-Id": rid}, timeout=20).json()
        assert r3 == {"accepted": True, "duplicate": True}
