"""Iteration 58 — Lab mode (Pepperstone): full-key snapshot/restore, profile-ends-lab, evolution source, HotForex untouched."""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
PEP = f"{BASE_URL}/api/pepper"
FX = f"{BASE_URL}/api/fx"
VOLATILE = {"updated_at", "ts"}


@pytest.fixture(scope="module")
def s():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": "BlackCat2233@"}, timeout=30)
    assert r.status_code == 200, r.text
    sess = requests.Session()
    sess.headers["Authorization"] = f"Bearer {r.json()['token']}"
    yield sess
    sess.post(f"{PEP}/lab/stop", timeout=30)


def _diff(a, b):
    out = []
    for k in set(a) | set(b):
        if k in VOLATILE:
            continue
        va, vb = a.get(k), b.get(k)
        if isinstance(va, list) and isinstance(vb, list):
            try:
                if sorted(map(str, va)) == sorted(map(str, vb)):
                    continue
            except Exception:
                pass
        if va != vb:
            out.append((k, va, vb))
    return out


# Lab: shape + auth
def test_lab_state_shape(s):
    assert requests.get(f"{PEP}/lab", timeout=30).status_code in (401, 403)
    st = s.get(f"{PEP}/lab", timeout=30).json()
    assert st["active"] is False and st["strategy"] == "ema_cross" and st["name"] == "Cruce EMA 10/20"
    assert isinstance(st["summary"], str) and isinstance(st["preset"], dict) and isinstance(st["kept"], list)
    assert s.get(f"{FX}/lab", timeout=30).status_code == 200


# Lab: start/alter/stop with full-key restore of settings + config; HotForex untouched
def test_full_restore(s):
    before = s.get(f"{PEP}/settings", timeout=30).json()
    cfg_before = s.get(f"{PEP}/config", timeout=30).json()
    fx_before = s.get(f"{FX}/settings", timeout=30).json()
    st = s.post(f"{PEP}/lab/start", timeout=30).json()
    assert st["active"] is True and st["altered"] == []
    for k in ("trades", "wins", "win_rate", "pnl", "pips", "profit_factor", "reasons", "cross_exits", "open"):
        assert k in st["stats"], k
    a = s.get(f"{PEP}/settings", timeout=30).json()
    assert a["strategy"] == "ema_cross" and a["timeframe"] == "15m" and a["signal_mode"] == "relaxed" and a["ai_enabled"] is True
    assert len(a["symbols"]) == 12 and a["sessions_allowed"] == []
    for k in ("htf_filter", "trailing_enabled", "partial_tp_enabled", "vol_filter_enabled", "seasonality_bias", "usd_regime_filter", "fomc_rule", "rollover_guard"):
        assert a[k] is False, k
    for k in ("risk_per_trade", "daily_loss_limit", "max_positions", "min_lot_max_risk", "close_before_weekend", "ai_min_confidence", "leverage"):
        assert a.get(k) == before.get(k), k
    c = s.get(f"{PEP}/config", timeout=30).json()
    for k in ("news_block_events", "news_block_critical", "news_reduce_on_high_risk", "news_trading_enabled", "auto_review_enabled"):
        assert c[k] is False, k
    assert not _diff(fx_before, s.get(f"{FX}/settings", timeout=30).json())
    s.put(f"{PEP}/settings", json={"htf_filter": True}, timeout=30)
    assert "htf_filter" in s.get(f"{PEP}/lab", timeout=30).json()["altered"]
    assert s.post(f"{PEP}/lab/stop", timeout=30).json()["active"] is False
    d1 = _diff(before, s.get(f"{PEP}/settings", timeout=30).json())
    d2 = _diff(cfg_before, s.get(f"{PEP}/config", timeout=30).json())
    assert not d1, f"settings diff: {d1}"
    assert not d2, f"config diff: {d2}"
    assert s.post(f"{PEP}/lab/bogus", timeout=30).status_code == 404


# Lab: profile ends lab, then restore original settings
def test_profile_ends_lab(s):
    before = s.get(f"{PEP}/settings", timeout=30).json()
    assert s.post(f"{PEP}/lab/start", timeout=30).json()["active"] is True
    r = s.post(f"{PEP}/profile", json={"level": 2}, timeout=30)
    assert r.status_code == 200
    assert s.get(f"{PEP}/lab", timeout=30).json()["active"] is False
    a = s.get(f"{PEP}/settings", timeout=30).json()
    assert a["strategy"] == before["strategy"] == "all" and "ema_cross" in a["disabled_strategies"]
    c = s.get(f"{PEP}/config", timeout=30).json()
    assert c["news_block_events"] is True and c["auto_review_enabled"] is True
    keep = {k: v for k, v in before.items() if k not in VOLATILE}
    assert s.put(f"{PEP}/settings", json=keep, timeout=30).status_code == 200
    d = s.get(f"{PEP}/dashboard", timeout=60).json()
    assert d["profile_active"] == 2 and d["lab"]["active"] is False
    assert not _diff(before, s.get(f"{PEP}/settings", timeout=30).json())


# Evolution has lab events
def test_evolution_lab(s):
    r = s.get(f"{PEP}/evolution", timeout=30)
    assert r.status_code == 200
    body = r.json()
    events = body if isinstance(body, list) else body.get("events", body.get("items", []))
    labs = [e for e in events if e.get("source") == "lab"]
    assert labs and labs[0].get("source_label") == "Modo laboratorio"
