# Iteration 8: market.py Bybit error handling / Bitget fallback / stale cache + API regression
import os
import sys
import time
import asyncio
import logging
import pytest
import requests

sys.path.insert(0, "/app/backend")
from market import MarketData, BYBIT_URL, BITGET_URL  # noqa: E402

BASE_URL = "http://127.0.0.1:8001"
PASSWORD = "BlackCat2233@"


class FakeResp:
    def __init__(self, status, payload=None, bad_json=False):
        self.status_code = status
        self._p = payload
        self._bad = bad_json

    def json(self):
        if self._bad:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._p


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


def patch_client(md, bybit_resp=None, bitget_resp=None, counter=None):
    real_get = md.client.get

    async def fake_get(url, *a, **kw):
        if url.startswith(BYBIT_URL):
            if counter is not None:
                counter.append(url)
            if bybit_resp is not None:
                return bybit_resp
        if url.startswith(BITGET_URL) and bitget_resp is not None:
            return bitget_resp
        return await real_get(url, *a, **kw)

    md.client.get = fake_get


RATE_LIMIT = FakeResp(200, {"retCode": 10006, "retMsg": "Too many visits!", "result": {}})


def _check_klines(k, n=300):
    assert len(k) == n
    for c in k:
        assert len(c) == 6
        assert isinstance(c[0], int)
        assert all(isinstance(x, float) for x in c[1:])
    ts = [c[0] for c in k]
    assert ts == sorted(ts) and len(set(ts)) == len(ts)


# --- Bybit retCode 10006 -> Bitget fallback
def test_rate_limit_fallback_klines_and_tickers():
    async def go():
        md = MarketData()
        md.provider = "bybit"
        patch_client(md, bybit_resp=RATE_LIMIT)
        k = await md.fetch_klines("XRPUSDT", "1h", 300)
        t = await md.fetch_tickers()
        await md.client.aclose()
        return k, t
    k, t = asyncio.run(go())
    _check_klines(k)
    assert len(t) > 50
    assert "XRPUSDT" in t and t["XRPUSDT"]["price"] > 0


# --- Bybit 403 non-JSON -> Bitget fallback
def test_403_non_json_fallback():
    async def go():
        md = MarketData()
        md.provider = "bybit"
        patch_client(md, bybit_resp=FakeResp(403, bad_json=True))
        k = await md.fetch_klines("ADAUSDT", "1h", 300)
        await md.client.aclose()
        return k
    _check_klines(asyncio.run(go()))


# --- Both fail: stale cache used, else RuntimeError
@pytest.mark.parametrize("bitget_resp", [FakeResp(500, bad_json=True), FakeResp(200, {"code": "40001", "msg": "bad"})])
def test_both_fail_stale_cache(bitget_resp, caplog):
    stale = [[1, 1.0, 2.0, 0.5, 1.5, 10.0]]

    async def go():
        md = MarketData()
        md.provider = "bybit"
        patch_client(md, bybit_resp=RATE_LIMIT, bitget_resp=bitget_resp)
        md._kcache[("XRPUSDT", "1h", 300)] = (time.time() - 3600, stale)
        with caplog.at_level(logging.WARNING, logger="market"):
            got = await md.fetch_klines("XRPUSDT", "1h", 300)
        await md.client.aclose()
        return got
    got = asyncio.run(go())
    assert got is stale
    assert any("caché" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("bitget_resp", [FakeResp(500, bad_json=True), FakeResp(200, {"code": "40001", "msg": "bad"})])
def test_both_fail_no_cache_raises(bitget_resp):
    async def go():
        md = MarketData()
        md.provider = "bybit"
        patch_client(md, bybit_resp=RATE_LIMIT, bitget_resp=bitget_resp)
        try:
            await md.fetch_klines("XRPUSDT", "1h", 300)
        finally:
            await md.client.aclose()
    with pytest.raises(RuntimeError) as ei:
        asyncio.run(go())
    assert str(ei.value).startswith("sin datos de mercado para")
    assert "list" not in str(ei.value)


# --- _bybit retries exactly 2 times
def test_bybit_retries_twice():
    calls = []

    async def go():
        md = MarketData()
        md.provider = "bybit"
        patch_client(md, bybit_resp=RATE_LIMIT, counter=calls)
        await md.fetch_klines("BTCUSDT", "1h", 300)
        await md.client.aclose()
    asyncio.run(go())
    assert len(calls) == 2


# --- Happy path bitget
def test_bitget_happy_path():
    async def go():
        md = MarketData()
        md.provider = "bitget"
        k = await md.fetch_klines("BTCUSDT", "1h", 300)
        t = await md.fetch_tickers()
        await md.client.aclose()
        return k, t
    k, t = asyncio.run(go())
    _check_klines(k)
    assert "BTCUSDT" in t and t["BTCUSDT"]["price"] > 0


# --- API regression
@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"password": PASSWORD})
    if r.status_code != 200:
        pytest.skip(f"login failed {r.status_code}")
    s.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return s


def test_dashboard_watchlist(client):
    r = client.get(f"{BASE_URL}/api/dashboard")
    assert r.status_code == 200
    wl = r.json()["watchlist"]
    assert len(wl) == 6
    assert all(w["price"] is not None and w["price"] > 0 for w in wl)


def test_klines_api(client):
    r = client.get(f"{BASE_URL}/api/klines", params={"symbol": "BTCUSDT", "tf": "1h"})
    assert r.status_code == 200
    assert len(r.json()["candles"]) >= 100


def test_scan_no_list_errors(client):
    before = client.get(f"{BASE_URL}/api/dashboard").json()
    running = before["status"].get("running")
    prev_ids = {l.get("id") or (l.get("ts"), l.get("message")) for l in before["logs"]}
    r = client.post(f"{BASE_URL}/api/bot/scan")
    assert r.status_code == 200
    new = []
    for _ in range(10):
        time.sleep(1)
        logs = client.get(f"{BASE_URL}/api/dashboard").json()["logs"]
        new = [l for l in logs if (l.get("id") or (l.get("ts"), l.get("message"))) not in prev_ids]
        if any("completado" in l.get("message", "") for l in new):
            break
    print("running:", running, "new logs:", [(l.get("level"), l.get("message")) for l in new])
    assert not any(l.get("level") == "ERROR" and "'list'" in l.get("message", "") for l in logs)
    if running:
        assert any(l.get("level") == "SCAN" and "completado" in l.get("message", "") for l in new)


def test_backtest(client):
    r = client.post(f"{BASE_URL}/api/backtest", json={"symbol": "SOLUSDT", "strategy": "all", "timeframe": "1h",
                                                       "risk_per_trade": 1, "leverage": 3}, timeout=120)
    assert r.status_code == 200, r.text[:300]
