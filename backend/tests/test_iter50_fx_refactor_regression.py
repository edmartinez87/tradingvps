# Iteration 50: black-box regression of HotForex API after engine/routes split (routes_analysis, routes_hfm, engine mixins)
import os
import pytest
import requests

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


# Auth enforced on moved endpoints
@pytest.mark.parametrize("method,path", [("get", "/mode"), ("get", "/walk-forward/check"), ("get", "/market/context"),
                                         ("post", "/backtest"), ("post", "/hfm/test"), ("get", "/plan/checkin"),
                                         ("get", "/weekly-summary"), ("get", "/ai/optimize-all"), ("post", "/mode")])
def test_auth_required(method, path):
    r = getattr(requests, method)(f"{FX}{path}", json={}, timeout=30)
    assert r.status_code == 401, f"{path} -> {r.status_code}"


# HFM sub-router
def test_mode_get(s):
    d = s.get(f"{FX}/mode", timeout=30).json()
    assert d["mode"] == "paper"
    keys = [c["key"] for c in d["checks"]]
    assert keys == ["keys", "linked", "verified", "trade_allowed", "symbols", "stopped", "flat", "paper"]
    assert d["can_go_live"] is False


def test_hfm_unconfigured(s):
    r = s.post(f"{FX}/hfm/test", json={}, timeout=30)
    assert r.status_code == 400 and "token de MetaApi" in r.json()["detail"]
    for p in ("/hfm/link", "/hfm/symbols", "/hfm/detect-suffix"):
        assert s.post(f"{FX}{p}", timeout=30).status_code == 400, p


def test_mode_switch(s):
    r = s.post(f"{FX}/mode", json={"mode": "live", "confirm": "REAL"}, timeout=30)
    assert r.status_code == 409, r.text
    r = s.post(f"{FX}/mode", json={"mode": "paper"}, timeout=30)
    assert r.status_code == 200 and r.json()["mode"] == "paper"
    assert s.post(f"{FX}/mode", json={"mode": "bogus"}, timeout=30).status_code == 400


def test_rebase_paper_409(s):
    assert s.post(f"{FX}/account/rebase", timeout=30).status_code == 409


# Analysis sub-router
def test_walk_forward_check(s):
    d = s.get(f"{FX}/walk-forward/check", timeout=30).json()
    assert {"job", "auto_remove", "latest"} <= set(d)


def test_plan_checkin_weekly(s):
    r = s.get(f"{FX}/plan/checkin", timeout=60)
    assert r.status_code == 200 and isinstance(r.json(), dict)
    w = s.get(f"{FX}/weekly-summary", timeout=60)
    assert w.status_code == 200 and isinstance(w.json()["text"], str) and w.json()["text"]


def test_plan(s):
    r = s.post(f"{FX}/plan", json={"initial_capital": 500}, timeout=60)
    assert r.status_code in (200, 422), r.text


def test_backtest(s):
    r = s.post(f"{FX}/backtest", json={"symbol": "EURUSD", "timeframe": "1h", "strategy": "all", "risk_per_trade": 1, "leverage": 100}, timeout=120)
    assert r.status_code == 200, r.text
    d = r.json()
    for k in ("total_trades", "profit_factor", "session_stats"):
        assert k in d
    r = s.post(f"{FX}/backtest", json={"symbol": "XAUUSD", "strategy": "fix_reversion"}, timeout=60)
    assert r.status_code == 400
    assert s.post(f"{FX}/backtest", json={"symbol": "FOO"}, timeout=30).status_code == 400


def test_optimize(s):
    r = s.post(f"{FX}/optimize", json={"symbol": "EURUSD"}, timeout=180)
    assert r.status_code == 200, r.text
    assert "timeframe" in r.json()


def test_ai(s):
    assert s.post(f"{FX}/ai/advise", json={"scope": "bogus"}, timeout=30).status_code == 400
    d = s.get(f"{FX}/ai/optimize-all", timeout=30).json()
    assert "status" in d


def test_market_context(s):
    r = s.get(f"{FX}/market/context", timeout=180)
    assert r.status_code == 200, r.text
    d = r.json()
    assert "fix_reversion" in d and "watch" in d and "open_positions" in d and "fomc" in d


# Core routes
def test_meta(s):
    d = s.get(f"{FX}/meta", timeout=30).json()
    assert len(d["strategy_keys"]) == 6 and "long_horizon_keys" in d


def test_dashboard(s):
    d = s.get(f"{FX}/dashboard", timeout=60).json()
    assert d["status"]["mode"] == "PAPER"
    assert "watchlist" in d and "settings" in d and "hfm" in d


def test_settings_roundtrip(s):
    cur = s.get(f"{FX}/settings", timeout=30)
    assert cur.status_code == 200
    r = s.put(f"{FX}/settings", json=cur.json(), timeout=30)
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("path", ["/config", "/evolution", "/news", "/overview", "/market", "/klines?symbol=EURUSD&tf=1h",
                                  "/positions", "/trades", "/signals", "/account"])
def test_core_gets(s, path):
    r = s.get(f"{FX}{path}", timeout=60)
    assert r.status_code == 200, f"{path} {r.status_code} {r.text[:200]}"


def test_performance(s):
    d = s.get(f"{FX}/performance", timeout=60).json()
    assert "excursion" in d and "shadow" in d


def test_klines_bad_tf(s):
    assert s.get(f"{FX}/klines?symbol=EURUSD&tf=1m", timeout=30).status_code == 400


def test_bot_roundtrip(s):
    try:
        r = s.post(f"{FX}/bot/start", timeout=60)
        assert r.status_code == 200 and r.json().get("status", r.json())["running"] is True, r.text
    finally:
        r = s.post(f"{FX}/bot/stop", timeout=60)
    assert r.status_code == 200 and r.json().get("status", r.json())["running"] is False, r.text
    r = s.post(f"{FX}/bot/scan", timeout=120)
    assert r.status_code == 200 and r.json().get("ok") is True, r.text
