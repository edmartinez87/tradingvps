"""Iteration 60 — Yahoo appends the forming bar a second time stamped with the last trade time: candles must be snapped to the bucket and folded."""
import os
import pytest
import requests

from fx.market import _normalize, TF_SECONDS

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")


@pytest.fixture(scope="module")
def s():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": "BlackCat2233@"}, timeout=30)
    assert r.status_code == 200, r.text
    sess = requests.Session()
    sess.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return sess


def test_normalize_folds_yahoo_tail():
    t0 = 1_793_170_800_000  # 06:45 UTC bucket start (15m)
    rows = [[t0, 1.0, 1.2, 0.9, 1.1, 10.0], [t0 + 900_000, 1.1, 1.15, 1.05, 1.12, 5.0], [t0 + 900_000 + 429_000, 1.13, 1.13, 1.13, 1.13, 7.0]]
    out = _normalize(rows, 900)
    assert [r[0] for r in out] == [t0, t0 + 900_000]
    assert out[1][1:] == [1.1, 1.15, 1.05, 1.13, 7.0]  # open kept, high/low merged, close = last trade, volume = max
    assert _normalize([], 900) == []
    # a lone unaligned stamp is snapped to its bucket
    assert _normalize([[t0 + 61_000, 1, 1, 1, 1, 0]], 60)[0][0] == t0 + 60_000


@pytest.mark.parametrize("bot", ["fx", "pepper"])
@pytest.mark.parametrize("tf", ["5m", "15m", "1h", "4h"])
def test_api_klines_aligned_and_unique(s, bot, tf):
    r = s.get(f"{BASE_URL}/api/{bot}/klines", params={"symbol": "USDJPY", "tf": tf}, timeout=90)
    assert r.status_code == 200, r.text
    times = [c["time"] for c in r.json()["candles"]]
    assert times and len(set(times)) == len(times) and times == sorted(times)
    assert all(t % TF_SECONDS[tf] == 0 for t in times), "every candle must sit on its bucket start"
    assert all(b - a >= TF_SECONDS[tf] for a, b in zip(times, times[1:]))


def test_api_klines_stable_between_polls(s):
    a = s.get(f"{BASE_URL}/api/pepper/klines", params={"symbol": "EURUSD", "tf": "15m"}, timeout=90).json()["candles"]
    b = s.get(f"{BASE_URL}/api/pepper/klines", params={"symbol": "EURUSD", "tf": "15m"}, timeout=90).json()["candles"]
    # two consecutive polls never introduce a new timestamp inside the same bucket (that was the 02:12 / 02:13 / 02:15 artefact)
    assert set(c["time"] for c in b) - set(c["time"] for c in a) <= {max(c["time"] for c in a) + 900}
