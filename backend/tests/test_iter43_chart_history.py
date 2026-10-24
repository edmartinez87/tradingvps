"""Iteration 43 – chart infinite history (`before`), 1D timeframe, exact indicator lines (warm-up) and the HFM/MetaApi candle source for FX
(mock on :8012). Run with -n 0 (shares the mock + fx_config)."""
import os
import subprocess
import sys
import time
import pytest
import requests
sys.path.insert(0, "/app/backend")
import chart  # noqa: E402

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API, FX, MOCK = f"{BASE_URL}/api", f"{BASE_URL}/api/fx", "http://127.0.0.1:8012"
CFG = {"metaapi_token": "mocktoken", "mt_login": "12345678", "mt_password": "masterpass", "mt_server": "HFMarketsGlobal-Demo", "mt_platform": "mt5",
       "metaapi_region": "new-york", "metaapi_base_url": MOCK, "mt_symbol_suffix": "", "metaapi_plan": "g2-high"}
STEP = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
KEYS = ("candles", "volume", "ema9", "ema21", "ema200", "rsi", "markers", "lines", "source", "has_more", "symbol", "tf")


def _up():
    try:
        return requests.get(f"{MOCK}/mock/state", timeout=2).status_code == 200
    except Exception:
        return False


@pytest.fixture(scope="module")
def s():
    r = requests.post(f"{API}/auth/login", json={"password": "BlackCat2233@"}, timeout=30)
    assert r.status_code == 200, r.text
    sess = requests.Session()
    sess.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return sess


@pytest.fixture(scope="module")
def mock():
    if not _up():
        subprocess.Popen(["python3", "scripts/metaapi_mock.py"], cwd="/app", stdout=open("/tmp/metaapi_mock.log", "a"), stderr=subprocess.STDOUT)
        for _ in range(20):
            if _up():
                break
            time.sleep(1)
    assert _up(), "mock did not start"
    requests.post(f"{MOCK}/mock/reset", timeout=10)
    return MOCK


def klines(s, base, **params):
    r = s.get(f"{base}/klines", params=params, timeout=90)
    assert r.status_code == 200, r.text
    return r.json()


def _check_shape(d, symbol, tf):
    assert all(k in d for k in KEYS), set(KEYS) - set(d)
    assert d["symbol"] == symbol and d["tf"] == tf
    n = len(d["candles"])
    assert n > 0
    # warm-up: every indicator line covers every visible candle (no 50/14-candle hole at the left edge)
    assert len(d["ema200"]) == n and len(d["rsi"]) == n and len(d["ema9"]) == n and len(d["volume"]) == n
    assert d["ema200"][0]["time"] == d["candles"][0]["time"] and d["rsi"][0]["time"] == d["candles"][0]["time"]
    times = [c["time"] for c in d["candles"]]
    assert times == sorted(times) and len(set(times)) == n
    assert all(0 <= p["value"] <= 100 for p in d["rsi"])


class TestChartUnit:
    def test_clamp(self):
        assert chart.clamp(10) == 100 and chart.clamp(300) == 300 and chart.clamp(5000) == chart.MAX_LIMIT


class TestCrypto:
    def test_latest(self, s):
        d = klines(s, API, symbol="BTCUSDT", tf="1h")
        _check_shape(d, "BTCUSDT", "1h")
        assert len(d["candles"]) == 300 and d["has_more"] is True and d["source"] in ("bybit", "bitget")

    def test_before_contiguous(self, s):
        d = klines(s, API, symbol="BTCUSDT", tf="1h")
        first = d["candles"][0]["time"]
        o = klines(s, API, symbol="BTCUSDT", tf="1h", before=first, limit=500)
        _check_shape(o, "BTCUSDT", "1h")
        assert len(o["candles"]) == 500 and o["has_more"] is True
        assert all(c["time"] < first for c in o["candles"])
        assert o["candles"][-1]["time"] + STEP["1h"] == first  # crypto trades 24/7 → no gap
        assert o["lines"] == []  # entry/SL/TP lines only on the live page

    def test_before_second_page(self, s):
        d = klines(s, API, symbol="ETHUSDT", tf="15m")
        o1 = klines(s, API, symbol="ETHUSDT", tf="15m", before=d["candles"][0]["time"], limit=500)
        o2 = klines(s, API, symbol="ETHUSDT", tf="15m", before=o1["candles"][0]["time"], limit=500)
        assert len(o2["candles"]) == 500 and o2["candles"][-1]["time"] + STEP["15m"] == o1["candles"][0]["time"]

    def test_daily(self, s):
        d = klines(s, API, symbol="BTCUSDT", tf="1d")
        _check_shape(d, "BTCUSDT", "1d")
        assert len(d["candles"]) >= 200 and d["has_more"] is True  # Bitget caps 1D at 90/request → topped up by paging

    def test_invalid(self, s):
        assert s.get(f"{API}/klines", params={"symbol": "BTCUSDT", "tf": "2h"}, timeout=30).status_code == 400
        assert s.get(f"{API}/klines", params={"symbol": "BTCUSDT", "tf": "1h", "before": "abc"}, timeout=30).status_code == 422


class TestFxYahoo:
    def test_latest_and_before(self, s):
        d = klines(s, FX, symbol="EURUSD", tf="1h")
        _check_shape(d, "EURUSD", "1h")
        assert d["source"] == "yahoo" and d["has_more"] is True
        first = d["candles"][0]["time"]
        o = klines(s, FX, symbol="EURUSD", tf="1h", before=first, limit=500)
        _check_shape(o, "EURUSD", "1h")
        assert len(o["candles"]) == 500 and all(c["time"] < first for c in o["candles"])
        assert first - o["candles"][-1]["time"] <= 3 * 86400  # at most a weekend gap

    def test_daily(self, s):
        d = klines(s, FX, symbol="XAUUSD", tf="1d")
        _check_shape(d, "XAUUSD", "1d")
        assert d["has_more"] is True

    def test_history_cap(self, s):
        """Yahoo serves 15m candles for ~60 days only → asking further back ends the history cleanly (empty page, has_more False)."""
        d = klines(s, FX, symbol="EURUSD", tf="15m", before=int(time.time()) - 70 * 86400, limit=500)
        assert d["candles"] == [] and d["has_more"] is False

    def test_invalid(self, s):
        assert s.get(f"{FX}/klines", params={"symbol": "EURUSD", "tf": "1m"}, timeout=30).status_code == 400


class TestFxHfm:
    @pytest.fixture(scope="class", autouse=True)
    def hfm(self, s, mock):
        s.post(f"{FX}/bot/stop", timeout=30)
        orig = s.get(f"{FX}/settings", timeout=30).json()["symbols"]
        if "XAUUSD" not in orig:
            s.put(f"{FX}/settings", json={"symbols": orig + ["XAUUSD"]}, timeout=30)
        assert s.put(f"{FX}/config", json=CFG, timeout=30).status_code == 200
        assert s.post(f"{FX}/hfm/link", timeout=60).status_code == 200
        assert s.get(f"{FX}/config", timeout=30).json()["hfm_state"] == "DEPLOYED"
        yield
        s.put(f"{FX}/config", json={"clear_hfm": True}, timeout=30)
        s.put(f"{FX}/config", json={"metaapi_base_url": "", "mt_symbol_suffix": ""}, timeout=30)
        s.put(f"{FX}/settings", json={"symbols": orig}, timeout=30)
        requests.post(f"{MOCK}/mock/reset", timeout=10)

    def test_source_hfm(self, s):
        d = klines(s, FX, symbol="EURUSD", tf="1h")
        _check_shape(d, "EURUSD", "1h")
        assert d["source"] == "hfm" and len(d["candles"]) == 300 and d["has_more"] is True

    def test_before_hfm_contiguous(self, s):
        d = klines(s, FX, symbol="GBPUSD", tf="15m")
        assert d["source"] == "hfm"
        first = d["candles"][0]["time"]
        o = klines(s, FX, symbol="GBPUSD", tf="15m", before=first, limit=500)
        assert o["source"] == "hfm" and len(o["candles"]) == 500 and o["has_more"] is True
        assert all(c["time"] < first for c in o["candles"]) and o["candles"][-1]["time"] + STEP["15m"] == first

    def test_odd_metal_name_and_suffix(self, s):
        """Zero group: after «Comprobar símbolos» resolves the broker's real name (XAUUSD → GOLDb), the chart asks MetaApi for GOLDb."""
        requests.post(f"{MOCK}/mock/account-group", params={"suffix": "b"}, timeout=10)
        assert s.put(f"{FX}/config", json={"mt_symbol_suffix": "b"}, timeout=30).status_code == 200
        try:
            r = s.post(f"{FX}/hfm/symbols", json={}, timeout=120)
            assert r.status_code == 200, r.text
            assert r.json()["symbols"]["XAUUSD"]["broker_symbol"] == "GOLDb", r.json()["symbols"]["XAUUSD"]
            d = klines(s, FX, symbol="XAUUSD", tf="1h")
            assert d["source"] == "hfm" and len(d["candles"]) == 300
            e = klines(s, FX, symbol="EURUSD", tf="1h")
            assert e["source"] == "hfm"  # EURUSDb via plain suffix
        finally:
            requests.post(f"{MOCK}/mock/account-group", params={"suffix": ""}, timeout=10)
            s.put(f"{FX}/config", json={"mt_symbol_suffix": ""}, timeout=30)

    def test_fallback_to_yahoo_when_disconnected(self, s):
        requests.post(f"{MOCK}/mock/connection", params={"connected": "false"}, timeout=10)
        try:
            d = klines(s, FX, symbol="USDJPY", tf="1h")
            assert d["source"] == "yahoo" and len(d["candles"]) == 300
        finally:
            requests.post(f"{MOCK}/mock/connection", params={"connected": "true"}, timeout=10)
