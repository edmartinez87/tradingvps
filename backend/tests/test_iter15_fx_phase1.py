"""Iteration 15 – HotForex AI Trading (FX Phase 1) backend tests + crypto regression/isolation."""
import os
import subprocess
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
FX = f"{BASE_URL}/api/fx"
SYMS = ["XAUUSD", "XAGUSD", "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD", "EURJPY", "GBPJPY", "EURCHF"]


@pytest.fixture(scope="module")
def s():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": "BlackCat2233@"}, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"login failed {r.status_code}")
    sess = requests.Session()
    sess.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return sess


def get(s, url, **kw):
    for _ in range(3):
        r = s.get(url, timeout=60, **kw)
        if r.status_code != 429:
            return r
        time.sleep(3)
    return r


def inject(sym, side):
    out = subprocess.run(["timeout", "100", "python3", "scripts/fx_inject_signal.py", sym, side, "noai"], cwd="/app",
                         capture_output=True, text=True, timeout=120)
    print(out.stdout[-800:], out.stderr[-800:])
    return out.stdout


# --- auth
def test_fx_requires_auth():
    assert requests.get(f"{FX}/overview", timeout=30).status_code in (401, 403)


# --- overview / dashboard / meta
def test_overview(s):
    r = get(s, f"{FX}/overview")
    assert r.status_code == 200
    d = r.json()
    for k in ("running", "mode", "equity", "total_return_pct", "open_positions", "market_open"):
        assert k in d
    assert d["mode"] == "PAPER"


def test_dashboard(s):
    r = get(s, f"{FX}/dashboard")
    assert r.status_code == 200
    d = r.json()
    for k in ("status", "settings", "account", "positions", "trades", "signals", "logs", "watchlist", "equity", "profile_active", "news", "hfm"):
        assert k in d, k
    wl = d["watchlist"]
    assert len(wl) == len(d["settings"]["symbols"])
    priced = [w for w in wl if isinstance(w["price"], (int, float))]
    print("priced", len(priced), "/", len(wl))
    assert len(priced) >= len(wl) - 1
    names = [x["name"] for x in d["status"]["market_hours"]["sessions"]]
    print(names)
    for n in ("Sídney", "Tokio", "Londres", "Nueva York"):
        assert any(n in x for x in names), n


def test_meta(s):
    d = get(s, f"{FX}/meta").json()
    assert sorted(d["symbols"]) == sorted(SYMS)
    assert set(d["symbol_info"]) == set(SYMS)
    assert d["timeframes"] == ["5m", "15m", "1h", "4h"]
    assert d["strategies"] and d["currency_names"]


@pytest.mark.parametrize("tf", ["5m", "15m", "1h", "4h"])
def test_klines(s, tf):
    r = get(s, f"{FX}/klines", params={"symbol": "XAUUSD", "tf": tf, "limit": 100})
    assert r.status_code == 200, r.text[:300]
    d = r.json()
    assert len(d["candles"]) > 20 and "rsi" in d and "ema21" in d


def test_klines_invalid(s):
    assert get(s, f"{FX}/klines", params={"symbol": "BTCUSDT", "tf": "1h"}).status_code == 400
    assert get(s, f"{FX}/klines", params={"symbol": "XAUUSD", "tf": "1m"}).status_code == 400


# --- settings
def test_settings_update_and_limits(s):
    orig = get(s, f"{FX}/settings").json()
    try:
        r = s.put(f"{FX}/settings", json={"risk_per_trade": 1.5, "max_positions": 4, "leverage": 200, "close_before_weekend": False,
                                          "symbols": ["XAUUSD", "EURUSD", "GBPUSD"]}, timeout=30)
        assert r.status_code == 200, r.text
        g = get(s, f"{FX}/settings").json()
        assert g["risk_per_trade"] == 1.5 and g["max_positions"] == 4 and g["leverage"] == 200
        assert g["close_before_weekend"] is False and g["symbols"] == ["XAUUSD", "EURUSD", "GBPUSD"]
        for bad in ({"max_positions": 0}, {"max_positions": 13}, {"leverage": 501}, {"leverage": 0}, {"risk_per_trade": 10},
                    {"symbols": ["BTCUSDT"]}, {"timeframe": "1m"}):
            rr = s.put(f"{FX}/settings", json=bad, timeout=30)
            assert rr.status_code == 422, (bad, rr.status_code, rr.text)
    finally:
        keys = ("risk_per_trade", "max_positions", "leverage", "close_before_weekend", "symbols")
        s.put(f"{FX}/settings", json={k: orig[k] for k in keys}, timeout=30)
    assert get(s, f"{FX}/settings").json()["symbols"] == orig["symbols"]


# --- bot control
def test_bot_start_stop_scan(s):
    assert s.post(f"{FX}/bot/start", timeout=30).json()["running"] is True
    assert get(s, f"{FX}/dashboard").json()["status"]["running"] is True
    assert s.post(f"{FX}/bot/scan", timeout=30).json()["ok"] is True
    assert s.post(f"{FX}/bot/stop", timeout=30).json()["running"] is False
    assert get(s, f"{FX}/overview").json()["running"] is False


# --- paper cycle
def test_paper_cycle_and_isolation(s):
    crypto_before = get(s, f"{BASE_URL}/api/dashboard").json()
    assert s.post(f"{FX}/account/reset", json={}, timeout=30).status_code == 200
    inject("EURUSD", "long")
    pos = get(s, f"{FX}/positions").json()
    assert len(pos) == 1 and pos[0]["symbol"] == "EURUSD", pos
    p = pos[0]
    print(p)
    for k in ("qty", "margin", "sl", "tp"):
        assert p[k] and p[k] > 0
    m1 = p.get("mark_price")
    time.sleep(8)
    p2 = get(s, f"{FX}/positions").json()[0]
    print("mark", m1, "->", p2.get("mark_price"), "upnl", p2.get("unrealized_pnl"))
    assert p2.get("mark_price") is not None

    # duplicate -> blocked
    inject("EURUSD", "long")
    assert len(get(s, f"{FX}/positions").json()) == 1
    sigs = get(s, f"{FX}/signals").json()
    assert sigs[0]["ai_decision"] == "BLOQUEADA", sigs[0]

    # crypto isolation
    crypto_now = get(s, f"{BASE_URL}/api/dashboard").json()
    assert not any(x["symbol"] == "EURUSD" for x in crypto_now["positions"])
    assert any(x["symbol"].endswith("USDT") for x in crypto_now["watchlist"])

    # close
    tr = s.post(f"{FX}/positions/{p['id']}/close", timeout=30)
    assert tr.status_code == 200, tr.text
    t = tr.json()
    assert t["reason"] == "MANUAL" and t["fees"] > 0
    trades = get(s, f"{FX}/trades").json()
    assert trades[0]["symbol"] == "EURUSD" and trades[0]["reason"] == "MANUAL"
    acc = get(s, f"{FX}/account").json()
    print("acc", acc)
    assert abs(acc["balance"] - (500 + t["pnl"])) < 0.05
    assert get(s, f"{FX}/positions").json() == []

    # XAUUSD short with $500 / 1% risk: ideal size < 0.01 lot → min-lot fallback (risk ≤ min_lot_max_risk, default 4%)
    s.put(f"{FX}/settings", json={"min_lot_max_risk": 8}, timeout=30)
    inject("XAUUSD", "short")
    xau = get(s, f"{FX}/positions").json()
    print("XAU positions:", xau)
    assert len(xau) == 1 and xau[0]["symbol"] == "XAUUSD" and xau[0]["qty"] == 0.01
    assert s.post(f"{FX}/positions/close-all", timeout=30).json()["closed"] == 1
    # with the fallback disabled the signal is rejected and the note explains why
    s.put(f"{FX}/settings", json={"min_lot_max_risk": 0}, timeout=30)
    try:
        inject("XAUUSD", "long")
        assert get(s, f"{FX}/positions").json() == []
        sig = get(s, f"{FX}/signals").json()[0]
        assert sig["symbol"] == "XAUUSD" and sig["executed"] is False and "lote mínimo" in sig["note"], sig
    finally:
        s.put(f"{FX}/settings", json={"min_lot_max_risk": 4}, timeout=30)
    assert s.put(f"{FX}/settings", json={"min_lot_max_risk": 11}, timeout=30).status_code == 422
    # close-all
    inject("GBPUSD", "short")
    assert len(get(s, f"{FX}/positions").json()) == 1
    ca = s.post(f"{FX}/positions/close-all", timeout=30).json()
    assert ca == {"closed": 1, "failed": 0}
    assert get(s, f"{FX}/positions").json() == []

    # reset with custom capital, then 500
    acc = s.post(f"{FX}/account/reset", json={"initial_balance": 1000}, timeout=30).json()
    assert acc["balance"] == 1000
    assert get(s, f"{FX}/trades").json() == [] and get(s, f"{FX}/signals").json() == []
    acc = s.post(f"{FX}/account/reset", json={}, timeout=30).json()
    assert acc["balance"] == 500
    crypto_after = get(s, f"{BASE_URL}/api/dashboard").json()
    assert crypto_after["account"]["initial_balance"] == crypto_before["account"]["initial_balance"]


def test_bad_position_ids(s):
    assert s.post(f"{FX}/positions/zzz/close", timeout=30).status_code == 400
    assert s.post(f"{FX}/positions/507f1f77bcf86cd799439011/close", timeout=30).status_code == 404


# --- news
def test_news(s):
    d = get(s, f"{FX}/news").json()
    assert "latest" in d and "summary" in d
    sm = d["summary"]
    print({k: sm.get(k) for k in ("risk", "next_event", "currencies")})
    assert "risk" in sm and "currencies" in sm and "next_event" in sm
    assert isinstance(get(s, f"{FX}/news/trades").json(), list)


def test_news_refresh(s):
    r = s.post(f"{FX}/news/refresh", timeout=150)
    print(r.status_code, r.text[:300])
    assert r.status_code in (200, 202, 409)


# --- config
def test_config(s):
    c = get(s, f"{FX}/config").json()
    for k in ("news_trade_min_confidence", "metaapi_token", "mt_password", "hfm_configured", "telegram_bot_token" if "telegram_bot_token" in c else "news_enabled"):
        assert k in c
    orig = c["news_trade_min_confidence"]
    try:
        r = s.put(f"{FX}/config", json={"news_trade_min_confidence": 80}, timeout=30)
        assert r.status_code == 200 and r.json()["news_trade_min_confidence"] == 80
        assert get(s, f"{FX}/config").json()["news_trade_min_confidence"] == 80
        for bad in ({"news_trade_min_confidence": 10}, {"mt_platform": "mt9"}, {"mt_login": "abc"}, {"metaapi_region": "mars"}):
            rr = s.put(f"{FX}/config", json=bad, timeout=30)
            assert rr.status_code == 422, (bad, rr.status_code, rr.text[:200])
    finally:
        s.put(f"{FX}/config", json={"news_trade_min_confidence": orig}, timeout=30)


# --- HFM / MetaApi
def test_hfm_errors(s):
    r = s.post(f"{FX}/hfm/test", json={}, timeout=60)
    print("empty", r.status_code, r.text[:200])
    assert 400 <= r.status_code < 500
    r = s.post(f"{FX}/hfm/test", json={"metaapi_token": "fake-token-123", "mt_login": "123456", "mt_server": "HFMarketsGlobal-Demo"}, timeout=60)
    print("fake", r.status_code, r.text[:200])
    assert 400 <= r.status_code < 500
    r = s.post(f"{FX}/hfm/link", timeout=60)
    print("link", r.status_code, r.text[:200])
    assert 400 <= r.status_code < 500


# --- logs / performance
def test_logs_and_performance(s):
    assert s.delete(f"{FX}/logs", timeout=30).json()["ok"] is True
    p = get(s, f"{FX}/performance")
    assert p.status_code == 200 and isinstance(p.json(), dict)


# --- crypto regression
@pytest.mark.parametrize("ep", ["overview", "dashboard", "meta", "settings", "news", "performance"])
def test_crypto_regression(s, ep):
    r = get(s, f"{BASE_URL}/api/{ep}")
    assert r.status_code == 200, r.text[:200]
    if ep == "settings":
        assert any(x.endswith("USDT") for x in r.json()["symbols"])
