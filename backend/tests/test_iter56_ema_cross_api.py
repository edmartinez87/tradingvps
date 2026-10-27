"""Iteration 56 — ema_cross API regression across the 3 bots: 422 all-off, profiles keep it off, backtest all, optimizer, chat."""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
BOTS = {"crypto": f"{BASE_URL}/api", "fx": f"{BASE_URL}/api/fx", "pepper": f"{BASE_URL}/api/pepper"}
KEEP = ("symbols", "timeframe", "signal_mode", "htf_filter", "ai_enabled", "ai_min_confidence", "risk_per_trade", "max_positions",
        "leverage", "daily_loss_limit", "disabled_strategies", "trailing_enabled", "partial_tp_enabled", "strategy")


@pytest.fixture(scope="module")
def s():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": "BlackCat2233@"}, timeout=30)
    assert r.status_code == 200, r.text
    sess = requests.Session()
    sess.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return sess


# Meta texts
@pytest.mark.parametrize("bot", list(BOTS))
def test_meta_info_texts(s, bot):
    m = s.get(f"{BOTS[bot]}/meta", timeout=30).json()
    info = m["strategy_info"]["ema_cross"]
    assert info["name"] == "Cruce EMA 10/20"
    assert isinstance(info.get("rules"), str) and len(info["rules"]) > 20
    assert isinstance(info.get("basis"), str) and len(info["basis"]) > 20


# All strategies disabled → 422
@pytest.mark.parametrize("bot", list(BOTS))
def test_all_disabled_422(s, bot):
    base = BOTS[bot]
    st = s.get(f"{base}/settings", timeout=30).json()
    keys = s.get(f"{base}/meta", timeout=30).json()["strategy_keys"]
    keys = [k for k in keys if k != "all"]
    r = s.put(f"{base}/settings", json={"disabled_strategies": keys}, timeout=30)
    after = s.get(f"{base}/settings", timeout=30).json()
    if after["disabled_strategies"] != st["disabled_strategies"]:
        s.put(f"{base}/settings", json={"disabled_strategies": st["disabled_strategies"]}, timeout=30)
    assert r.status_code == 422, f"{r.status_code} {r.text[:200]} keys={keys}"
    assert after["disabled_strategies"] == st["disabled_strategies"]


# Profile level 2 keeps ema_cross off, then restore
@pytest.mark.parametrize("bot", list(BOTS))
def test_profile2_keeps_off(s, bot):
    base = BOTS[bot]
    st = s.get(f"{base}/settings", timeout=30).json()
    try:
        r = s.post(f"{base}/profile", json={"level": 2}, timeout=30)
        assert r.status_code == 200, r.text
        assert "ema_cross" in s.get(f"{base}/settings", timeout=30).json()["disabled_strategies"]
    finally:
        if st.get("risk_profile") in range(5):
            s.post(f"{base}/profile", json={"level": st["risk_profile"]}, timeout=30)
        keep = {k: st[k] for k in KEEP if k in st}
        r = s.put(f"{base}/settings", json=keep, timeout=30)
        assert r.status_code == 200, r.text
        now = s.get(f"{base}/settings", timeout=30).json()
        assert now.get("risk_profile") == st.get("risk_profile")
        assert now["disabled_strategies"] == st["disabled_strategies"]


# Backtest with strategy 'all'
@pytest.mark.parametrize("bot,symbol", [("crypto", "BTCUSDT"), ("fx", "EURUSD")])
def test_backtest_all(s, bot, symbol):
    r = s.post(f"{BOTS[bot]}/backtest", json={"symbol": symbol, "strategy": "all", "timeframe": "1h"}, timeout=240)
    assert r.status_code == 200, r.text[:300]
    d = r.json()
    assert d["total_trades"] >= 0 and isinstance(d["strategy_stats"], dict)


# Optimizer + walk-forward
@pytest.mark.parametrize("url,symbol", [("/api/optimize", "BTCUSDT"), ("/api/fx/optimize", "EURUSD"), ("/api/fx/optimize/walk-forward", "EURUSD")])
def test_optimizer(s, url, symbol):
    r = s.post(f"{BASE_URL}{url}", json={"symbol": symbol}, timeout=280)
    assert r.status_code == 200, r.text[:300]
    assert isinstance(r.json(), dict) and "timeframe" in r.json()


# Chat awareness (one real LLM call)
def test_chat_ema_cross(s):
    assert s.get(f"{BASE_URL}/api/chat", timeout=30).status_code == 200
    r = s.post(f"{BASE_URL}/api/chat/message", json={"text": "¿Qué es la estrategia Cruce EMA 10/20 y está activada en el bot Pepperstone?", "panel": "pepper"}, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    jid = d.get("job_id") or d.get("id") or (d.get("job") or {}).get("id")
    assert jid, d
    j = {}
    for _ in range(45):
        time.sleep(3)
        j = s.get(f"{BASE_URL}/api/chat/jobs/{jid}", timeout=30).json()
        if j.get("status") in ("done", "error", "failed"):
            break
    print("CHAT JOB:", str(j)[:2500])
    assert j.get("status") == "done", j
    txt = str(j).lower()
    assert any(w in txt for w in ("apagad", "desactivad", "no está activ")), "no mention it is off"
    assert "cruce" in txt
