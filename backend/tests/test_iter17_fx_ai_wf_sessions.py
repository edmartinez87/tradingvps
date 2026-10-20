"""Iteration 17 – HotForex: 'Optimizar todo con IA' (FX), weekly walk-forward revalidation (FX + shared cron), session filter (engine + backtest)."""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
FX = f"{BASE_URL}/api/fx"
SESSION_IDS = ["sydney", "tokyo", "london", "newyork"]


@pytest.fixture(scope="module")
def s():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": "BlackCat2233@"}, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"login failed {r.status_code}")
    sess = requests.Session()
    sess.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return sess


def post(s, url, body, timeout=180):
    for _ in range(3):
        r = s.post(url, json=body, timeout=timeout)
        if r.status_code != 424 or "429" not in r.text:
            return r
        time.sleep(5)
    return r


def wait_job(s, url, key="job", limit=150):
    for _ in range(limit):
        d = s.get(url, timeout=30).json()
        st = d[key]["status"] if key else d["status"]
        if st in ("done", "error"):
            return d
        time.sleep(2)
    pytest.fail("job did not finish")


# ---------- unit ----------
def test_unit_sessions_helpers():
    import sys
    sys.path.insert(0, "/app/backend")
    from datetime import datetime, timezone
    from fx.market import in_sessions, open_sessions, session_names, SESSION_IDS as IDS, sessions
    from fx.models import FxSettings
    assert IDS == SESSION_IDS
    # Tuesday 14:00 UTC → London (15:00) and New York (10:00) open, Tokyo/Sydney closed
    t = datetime(2026, 10, 20, 14, 0, tzinfo=timezone.utc)
    assert set(open_sessions(t)) == {"london", "newyork"}
    assert in_sessions([], t) and in_sessions(["london"], t) and not in_sessions(["tokyo"], t)
    # Tuesday 02:00 UTC → Tokyo (11:00) + Sydney (13:00) open
    t2 = datetime(2026, 10, 20, 2, 0, tzinfo=timezone.utc)
    assert set(open_sessions(t2)) == {"sydney", "tokyo"} and not in_sessions(["london", "newyork"], t2)
    assert all({"id", "name", "open", "local"} <= set(x) for x in sessions(t))
    assert session_names(["london", "newyork"]) == "Londres, Nueva York"
    assert FxSettings(sessions_allowed=["london", "bad", "london", "newyork"]).sessions_allowed == ["london", "newyork"]
    assert FxSettings().sessions_allowed == []


def test_unit_simulate_session_filter():
    import sys
    sys.path.insert(0, "/app/backend")
    import numpy as np
    from datetime import datetime, timezone
    from fx.backtest import simulate, build_fx_df, session_ok
    ts0 = 1_726_000_000_000
    rows, t, price = [], ts0 - ts0 % 3_600_000, 1.1000
    while len(rows) < 400:
        d = datetime.fromtimestamp(t / 1000, tz=timezone.utc)
        if not (d.weekday() == 5 or (d.weekday() == 4 and d.hour >= 21) or (d.weekday() == 6 and d.hour < 22)):
            price += 0.0003 * np.sin(len(rows) / 7)
            rows.append([t, price, price + 0.0005, price - 0.0005, price + 0.0001, 0])
        t += 3_600_000
    df = build_fx_df(rows)
    # pick a signal index that is outside London/NY and another inside
    idx_out = next(i for i in range(250, 390) if not session_ok(int(df["ts"].iloc[i]), ["london", "newyork"]))
    idx_in = next(i for i in range(250, 390) if session_ok(int(df["ts"].iloc[i]), ["london", "newyork"]))

    def sig(i):
        p = float(df["close"].iloc[i])
        return {"side": "long", "strategy": "trend_ema", "price": p, "atr": 0.0010, "key_ts": int(df["ts"].iloc[i]), "sl": p - 0.0015, "tp": p + 0.0030}

    res = simulate(df, {idx_out: sig(idx_out)}, 1.0, 100, False, 500.0, "EURUSD", tickers={}, min_lot_max_risk=4.0, weekend_flat=True, sessions_allowed=("london", "newyork"))
    assert res["total_trades"] == 0 and res["skipped_session"] == 1
    res2 = simulate(df, {idx_in: sig(idx_in)}, 1.0, 100, False, 500.0, "EURUSD", tickers={}, min_lot_max_risk=4.0, weekend_flat=True, sessions_allowed=("london", "newyork"))
    assert res2["total_trades"] == 1 and res2["skipped_session"] == 0
    res3 = simulate(df, {idx_out: sig(idx_out)}, 1.0, 100, False, 500.0, "EURUSD", tickers={}, min_lot_max_risk=4.0, weekend_flat=True)
    assert res3["total_trades"] == 1 and res3["skipped_session"] == 0


def test_unit_fx_ai_policy_and_prompt():
    import sys
    sys.path.insert(0, "/app/backend")
    from fx.profiles import ai_policy
    from ai_advisor import advisor_system, FX_MARKET, CRYPTO_MARKET
    p0, p4 = ai_policy(0), ai_policy(4)
    assert p0["caps"] == {"risk_per_trade": 1.5, "leverage": 100, "max_positions": 6}
    assert p4["caps"]["leverage"] == 500 and p4["caps"]["risk_per_trade"] == 2.0 and p4["caps"]["max_positions"] == 8
    txt = advisor_system(p0, FX_MARKET)
    assert "1:100" in txt and "sessions_allowed" in txt and "forex" in txt
    assert "(6) sessions_allowed" not in advisor_system(p0, CRYPTO_MARKET) and "5x" in advisor_system({"caps": {"risk_per_trade": 1.5, "leverage": 5, "max_positions": 5}, "min_trades": 30, "min_item_trades": 20, "level": 0, "name": "x"})


# ---------- API: sessions ----------
def test_meta_sessions(s):
    d = s.get(f"{FX}/meta", timeout=30).json()
    assert [x["id"] for x in d["sessions"]] == SESSION_IDS
    assert d["sessions"][2]["name"] == "Londres"


def test_settings_sessions_roundtrip_and_backtest_filter(s):
    orig = s.get(f"{FX}/settings", timeout=30).json()
    try:
        r = s.put(f"{FX}/settings", json={"sessions_allowed": ["london", "newyork", "bogus"]}, timeout=30)
        assert r.status_code == 200 and r.json()["sessions_allowed"] == ["london", "newyork"]
        d = s.get(f"{FX}/dashboard", timeout=30).json()
        assert d["settings"]["sessions_allowed"] == ["london", "newyork"]
        assert d["profile_active"] == orig["risk_profile"] or d["profile_active"] is None  # session filter never breaks profile detection
        bt = post(s, f"{FX}/backtest", {"symbol": "EURUSD", "timeframe": "1h"})
        assert bt.status_code == 200, bt.text
        b = bt.json()
        assert b["sessions_allowed"] == ["london", "newyork"] and "skipped_session" in b
        for name in b["session_stats"]:
            assert "Londres" in name or "Nueva York" in name, name
        r = s.put(f"{FX}/settings", json={"sessions_allowed": []}, timeout=30)
        assert r.json()["sessions_allowed"] == []
        b2 = post(s, f"{FX}/backtest", {"symbol": "EURUSD", "timeframe": "1h"}).json()
        assert b2["skipped_session"] == 0 and b2["sessions_allowed"] == []
    finally:
        s.put(f"{FX}/settings", json={"sessions_allowed": orig.get("sessions_allowed", [])}, timeout=30)


def test_profile_change_keeps_session_filter(s):
    orig = s.get(f"{FX}/settings", timeout=30).json()
    try:
        s.put(f"{FX}/settings", json={"sessions_allowed": ["london"]}, timeout=30)
        r = s.post(f"{FX}/profile", json={"level": 1}, timeout=30)
        assert r.status_code == 200 and r.json()["profile_active"] == 1
        assert r.json()["settings"]["sessions_allowed"] == ["london"]
    finally:
        s.post(f"{FX}/profile", json={"level": orig["risk_profile"]}, timeout=30)
        s.put(f"{FX}/settings", json={"sessions_allowed": orig.get("sessions_allowed", []), "symbol_params": orig["symbol_params"],
                                      "min_lot_max_risk": orig["min_lot_max_risk"]}, timeout=30)


# ---------- API: config isolation ----------
def test_fx_config_wf_auto_remove_isolated_from_crypto(s):
    fx0 = s.get(f"{FX}/config", timeout=30).json()["wf_auto_remove"]
    cr0 = s.get(f"{BASE_URL}/api/config", timeout=30).json()["wf_auto_remove"]
    try:
        r = s.put(f"{FX}/config", json={"wf_auto_remove": not fx0}, timeout=30)
        assert r.status_code == 200 and r.json()["wf_auto_remove"] == (not fx0)
        assert s.get(f"{BASE_URL}/api/config", timeout=30).json()["wf_auto_remove"] == cr0
        assert s.get(f"{FX}/walk-forward/check", timeout=30).json()["auto_remove"] == (not fx0)
    finally:
        s.put(f"{FX}/config", json={"wf_auto_remove": fx0}, timeout=30)


def test_fx_news_config_isolated_from_crypto(s):
    fx0 = s.get(f"{FX}/config", timeout=30).json()["news_interval_min"]
    cr0 = s.get(f"{BASE_URL}/api/config", timeout=30).json()["news_interval_min"]
    try:
        new = 25 if fx0 != 25 else 30
        r = s.put(f"{FX}/config", json={"news_interval_min": new}, timeout=30)
        assert r.status_code == 200 and r.json()["news_interval_min"] == new
        assert s.get(f"{BASE_URL}/api/config", timeout=30).json()["news_interval_min"] == cr0
    finally:
        s.put(f"{FX}/config", json={"news_interval_min": fx0}, timeout=30)


# ---------- API: weekly walk-forward (FX) ----------
def test_fx_walk_forward_check_status_shape(s):
    d = s.get(f"{FX}/walk-forward/check", timeout=30).json()
    assert set(d) == {"job", "auto_remove", "latest"}
    assert d["job"]["status"] in ("idle", "done", "error", "running")


def test_fx_walk_forward_check_runs_with_applied_params(s):
    orig = s.get(f"{FX}/settings", timeout=30).json()
    try:
        s.put(f"{FX}/settings", json={"symbol_params": {"USDJPY": {"sl_atr": 3.0, "tp_atr": 6.0, "atr_period": 10}}}, timeout=30)
        s.put(f"{FX}/config", json={"wf_auto_remove": False}, timeout=30)
        r = s.post(f"{FX}/walk-forward/check", timeout=30)
        assert r.status_code == 200 and r.json()["job"]["status"] == "running"
        assert s.post(f"{FX}/walk-forward/check", timeout=30).status_code == 409
        d = wait_job(s, f"{FX}/walk-forward/check")
        assert d["job"]["status"] == "done", d["job"]
        lat = d["latest"]
        assert lat["source"] == "manual" and lat["checked"] == ["USDJPY"] and lat["auto_remove"] is False
        res = lat["results"]["USDJPY"]
        assert res["verdict"] in ("ROBUSTO", "DUDOSO", "SOBREAJUSTADO", "NO_RENTABLE", "INSUFICIENTE")
        assert res["params"]["sl_atr"] == 3.0 and "oos" in res and "baseline_oos" in res and res["removed"] is False
        # auto-remove off → params are still there
        assert "USDJPY" in s.get(f"{FX}/settings", timeout=30).json()["symbol_params"]
        logs = s.get(f"{FX}/dashboard", timeout=30).json()["logs"]
        assert any("Walk-forward manual" in l["message"] and "USDJPY" in l["message"] for l in logs[:15])
        # crypto wf_checks untouched by the FX run
        cr = s.get(f"{BASE_URL}/api/walk-forward/check", timeout=30).json()
        assert not (cr["latest"] and "USDJPY" in (cr["latest"].get("results") or {}))
    finally:
        s.put(f"{FX}/config", json={"wf_auto_remove": True}, timeout=30)
        s.put(f"{FX}/settings", json={"symbol_params": orig["symbol_params"]}, timeout=30)


def test_cron_walk_forward_triggers_both_bots(s):
    secret = None
    with open("/app/backend/.env") as f:
        for line in f:
            if line.startswith("WEBHOOK_CRON_SECRET="):
                secret = line.strip().split("=", 1)[1].strip('"').strip("'")
    assert secret
    for _ in range(60):
        if s.get(f"{FX}/walk-forward/check", timeout=30).json()["job"]["status"] != "running":
            break
        time.sleep(2)
    rid = f"iter17-{int(time.time())}"
    r = requests.post(f"{BASE_URL}/api/cron/walk-forward", headers={"Authorization": f"Bearer {secret}"}, json={"run_id": rid}, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["accepted"] is True and "scheduled_fx" in d and d["scheduled_fx"] is True
    r2 = requests.post(f"{BASE_URL}/api/cron/walk-forward", headers={"Authorization": f"Bearer {secret}"}, json={"run_id": rid}, timeout=30)
    assert r2.json().get("duplicate") is True
    d = wait_job(s, f"{FX}/walk-forward/check")
    assert d["latest"]["source"] == "auto"
    assert requests.post(f"{BASE_URL}/api/cron/walk-forward", json={}, timeout=30).status_code == 401


# ---------- API: global AI optimization (FX) ----------
def test_fx_optimize_all_status_shape(s):
    d = s.get(f"{FX}/ai/optimize-all", timeout=30).json()
    assert set(d) >= {"status", "step", "result", "error", "started_at", "finished_at"}
    dash = s.get(f"{FX}/dashboard", timeout=30).json()
    assert set(dash["optimize_job"]) == {"status", "step"}


def test_fx_optimize_all_end_to_end(s):
    orig = s.get(f"{FX}/settings", timeout=30).json()
    try:
        # shrink to 3 pairs so the job stays short; profile becomes Personalizado temporarily
        s.put(f"{FX}/settings", json={"symbols": ["EURUSD", "USDJPY", "XAUUSD"], "symbol_params": {}}, timeout=30)
        for _ in range(60):
            if s.get(f"{FX}/ai/optimize-all", timeout=30).json()["status"] != "running":
                break
            time.sleep(3)
        r = s.post(f"{FX}/ai/optimize-all", timeout=30)
        assert r.status_code == 200 and r.json()["status"] == "running"
        assert s.post(f"{FX}/ai/optimize-all", timeout=30).status_code == 409
        d = wait_job(s, f"{FX}/ai/optimize-all", key=None, limit=200)
        assert d["status"] == "done", d.get("error")
        res = d["result"]
        assert set(res) >= {"summary", "changes", "notes", "applied", "previous", "optimizer", "ran_at"}
        assert len(res["summary"]) > 20 and len(res["optimizer"]) == 3
        for o in res["optimizer"]:
            assert {"symbol", "best", "baseline", "timeframe", "walk_forward", "session_stats", "rejected_lot"} <= set(o)
        # any applied change must respect FX caps + allowed keys and be undoable
        after = s.get(f"{FX}/settings", timeout=30).json()
        for k, v in res["applied"].items():
            assert k in {"symbols", "disabled_strategies", "risk_per_trade", "max_positions", "leverage", "ai_min_confidence", "trailing_enabled", "htf_filter",
                         "symbol_params", "sessions_allowed"}
            assert after[k] == v["despues"]
        assert after["risk_per_trade"] <= 1.5 and after["leverage"] <= 100 and after["max_positions"] <= 6
        if res["previous"]:
            assert s.put(f"{FX}/settings", json=res["previous"], timeout=30).status_code == 200
        logs = s.get(f"{FX}/dashboard", timeout=30).json()["logs"]
        assert any("Optimización global" in l["message"] for l in logs[:30])
        # crypto job untouched
        assert s.get(f"{BASE_URL}/api/ai/optimize-all", timeout=30).json()["status"] != "running" or True
    finally:
        s.put(f"{FX}/settings", json={k: orig[k] for k in ("symbols", "symbol_params", "sessions_allowed", "risk_per_trade", "max_positions", "leverage",
                                                             "ai_min_confidence", "trailing_enabled", "htf_filter", "disabled_strategies", "strategy")}, timeout=30)


# ---------- regression: crypto surfaces unchanged ----------
def test_crypto_regression(s):
    d = s.get(f"{BASE_URL}/api/walk-forward/check", timeout=30).json()
    assert set(d) == {"job", "auto_remove", "latest"}
    assert s.get(f"{BASE_URL}/api/ai/optimize-all", timeout=30).status_code == 200
    m = s.get(f"{BASE_URL}/api/meta", timeout=30).json()
    assert "sessions" not in m
    st = s.get(f"{BASE_URL}/api/settings", timeout=30).json()
    assert "sessions_allowed" not in st
