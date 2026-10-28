# Iter50: Yahoo FX candle alignment (no duplicated forming bar) on /api/pepper and /api/fx + regression
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
TFS = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400}
PREFIXES = ["pepper", "fx"]
SYMBOLS = ["USDJPY", "XAUUSD", "EURUSD"]
T = 90


@pytest.fixture(scope="module")
def s():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": "BlackCat2233@"}, timeout=30)
    if r.status_code != 200:
        pytest.skip("login failed")
    ses = requests.Session()
    ses.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return ses


def _get(s, p, sym, tf, **kw):
    r = s.get(f"{BASE_URL}/api/{p}/klines", params={"symbol": sym, "tf": tf, **kw}, timeout=T)
    assert r.status_code == 200, r.text
    return r.json()


def _check(c, step):
    ts = [x["time"] for x in c]
    assert len(ts) > 10
    assert len(set(ts)) == len(ts), "duplicates"
    assert ts == sorted(ts)
    bad = [t for t in ts if t % step]
    assert not bad, f"unaligned {bad[:5]}"
    gaps = [b - a for a, b in zip(ts, ts[1:]) if b - a < step]
    assert not gaps, f"spacing < step {gaps[:5]}"


# Alignment for all prefixes/symbols/tfs
@pytest.mark.parametrize("p", PREFIXES)
@pytest.mark.parametrize("sym", SYMBOLS)
@pytest.mark.parametrize("tf", list(TFS))
def test_aligned(s, p, sym, tf):
    d = _get(s, p, sym, tf)
    step = TFS[tf]
    c = d["candles"]
    _check(c, step)
    now = int(time.time())
    last = c[-1]["time"]
    # forming bucket (market open) — allow up to 1 bucket lag, or weekends for metals breaks
    assert now - last < step * 2 + 120, f"last candle stale: now-last={now - last}"
    # last candle never in the future and is at most the current bucket (flat aligned bars can be genuine 1-tick Yahoo bars)
    assert last <= now - now % step


# Repeated polling: the set must not grow except by one aligned bucket
@pytest.mark.parametrize("p", PREFIXES)
def test_poll_stable(s, p):
    sets = []
    for i in range(3):
        d = _get(s, p, "USDJPY", "15m")
        _check(d["candles"], 900)
        sets.append([x["time"] for x in d["candles"]])
        if i < 2:
            time.sleep(10)
    union = set().union(*sets)
    assert len(union) - len(set(sets[0])) <= 1, f"grew by {len(union) - len(set(sets[0]))}"
    assert all(t % 900 == 0 for t in union)


# Older pages via before
@pytest.mark.parametrize("p", PREFIXES)
@pytest.mark.parametrize("tf", ["15m", "4h"])
def test_before_join(s, p, tf):
    step = TFS[tf]
    d = _get(s, p, "USDJPY", tf)
    first = d["candles"][0]["time"]
    o = _get(s, p, "USDJPY", tf, before=first, limit=500)
    _check(o["candles"], step)
    assert o["candles"][-1]["time"] < first
    merged = sorted({x["time"] for x in o["candles"]} | {x["time"] for x in d["candles"]})
    _check([{"time": t} for t in merged], step)
    # join gap should be small (≤ weekend ~ 3 days)
    assert first - o["candles"][-1]["time"] <= 3 * 86400


@pytest.mark.parametrize("p", PREFIXES)
def test_dashboard(s, p):
    r = s.get(f"{BASE_URL}/api/{p}/dashboard", timeout=T)
    assert r.status_code == 200
    print(list(r.json().keys()))


@pytest.mark.parametrize("p", PREFIXES)
def test_scan(s, p):
    r = s.post(f"{BASE_URL}/api/{p}/bot/scan", timeout=T)
    assert r.status_code == 200 and r.json()["ok"] is True


def test_pepper_backtest(s):
    r = s.post(f"{BASE_URL}/api/pepper/backtest", json={"symbol": "USDJPY", "strategy": "ema_cross", "timeframe": "15m"}, timeout=180)
    assert r.status_code == 200, r.text
