"""Iteration 57 — «Modo laboratorio» (Pepperstone): run only ema_cross with the chosen layers off; snapshot/restore of settings + config."""
import os
import pytest
import requests

from fx.lab import SETTINGS_PATCH, CONFIG_PATCH, LAB_STRATEGY

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
PEP = f"{BASE_URL}/api/pepper"
FX = f"{BASE_URL}/api/fx"


@pytest.fixture(scope="module")
def s():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": "BlackCat2233@"}, timeout=30)
    assert r.status_code == 200, r.text
    sess = requests.Session()
    sess.headers["Authorization"] = f"Bearer {r.json()['token']}"
    yield sess
    sess.post(f"{PEP}/lab/stop", timeout=30)  # never leave the lab on after the tests


def test_preset_definition():
    assert SETTINGS_PATCH["strategy"] == LAB_STRATEGY == "ema_cross" and SETTINGS_PATCH["timeframe"] == "15m" and SETTINGS_PATCH["signal_mode"] == "relaxed"
    assert SETTINGS_PATCH["ai_enabled"] is True and len(SETTINGS_PATCH["symbols"]) == 12
    assert all(SETTINGS_PATCH[k] is False for k in ("htf_filter", "trailing_enabled", "partial_tp_enabled", "vol_filter_enabled", "seasonality_bias", "usd_regime_filter", "fomc_rule", "rollover_guard"))
    assert all(v is False for v in CONFIG_PATCH.values()) and "auto_review_enabled" in CONFIG_PATCH and "news_trading_enabled" in CONFIG_PATCH


def test_requires_auth():
    assert requests.get(f"{PEP}/lab", timeout=30).status_code in (401, 403)
    assert requests.post(f"{PEP}/lab/start", timeout=30).status_code in (401, 403)


def test_start_apply_stop_restore(s):
    assert s.post(f"{PEP}/lab/stop", timeout=30).status_code == 200
    before = s.get(f"{PEP}/settings", timeout=30).json()
    cfg_before = s.get(f"{PEP}/config", timeout=30).json()
    st0 = s.get(f"{PEP}/lab", timeout=30).json()
    assert st0["active"] is False and st0["strategy"] == "ema_cross" and "summary" in st0

    r = s.post(f"{PEP}/lab/start", timeout=30)
    assert r.status_code == 200, r.text
    st = r.json()
    assert st["active"] is True and st["since"] and st["altered"] == [] and st["stats"]["trades"] >= 0 and "cross_exits" in st["stats"]
    after = s.get(f"{PEP}/settings", timeout=30).json()
    for k, v in SETTINGS_PATCH.items():
        assert (set(after[k]) == set(v)) if isinstance(v, list) else after[k] == v, k
    for k in ("risk_per_trade", "daily_loss_limit", "max_positions", "min_lot_max_risk", "close_before_weekend", "ai_min_confidence"):
        assert after[k] == before[k], k
    cfg = s.get(f"{PEP}/config", timeout=30).json()
    for k, v in CONFIG_PATCH.items():
        assert cfg[k] == v, k
    d = s.get(f"{PEP}/dashboard", timeout=60).json()
    assert d["lab"]["active"] is True and d["settings"]["strategy"] == "ema_cross"
    # idempotent start, HotForex untouched
    assert s.post(f"{PEP}/lab/start", timeout=30).json()["active"] is True
    assert s.get(f"{FX}/lab", timeout=30).json()["active"] is False

    # a manual change is flagged as "altered"
    s.put(f"{PEP}/settings", json={"htf_filter": True}, timeout=30)
    assert "htf_filter" in s.get(f"{PEP}/lab", timeout=30).json()["altered"]

    r = s.post(f"{PEP}/lab/stop", timeout=30)
    assert r.status_code == 200 and r.json()["active"] is False
    restored = s.get(f"{PEP}/settings", timeout=30).json()
    for k in SETTINGS_PATCH:
        assert (set(restored[k]) == set(before[k])) if isinstance(before[k], list) else restored[k] == before[k], k
    cfg2 = s.get(f"{PEP}/config", timeout=30).json()
    for k in CONFIG_PATCH:
        assert cfg2[k] == cfg_before[k], k
    assert s.post(f"{PEP}/lab/stop", timeout=30).json()["active"] is False  # idempotent
    assert s.post(f"{PEP}/lab/bogus", timeout=30).status_code == 404


def test_profile_ends_lab_without_restore(s):
    before = s.get(f"{PEP}/settings", timeout=30).json()
    assert s.post(f"{PEP}/lab/start", timeout=30).json()["active"] is True
    level = before.get("risk_profile") if before.get("risk_profile") in range(5) else 2
    assert s.post(f"{PEP}/profile", json={"level": level}, timeout=30).status_code == 200
    assert s.get(f"{PEP}/lab", timeout=30).json()["active"] is False
    after = s.get(f"{PEP}/settings", timeout=30).json()
    assert after["strategy"] == "all" and "ema_cross" in after["disabled_strategies"]
    cfg = s.get(f"{PEP}/config", timeout=30).json()  # news/auto-review config restored even when a profile ends the lab
    assert cfg["auto_review_enabled"] is True and cfg["news_block_events"] is True
    keep = {k: before[k] for k in ("symbols", "timeframe", "signal_mode", "htf_filter", "ai_enabled", "ai_min_confidence", "risk_per_trade", "max_positions",
                                   "leverage", "daily_loss_limit", "disabled_strategies", "trailing_enabled", "partial_tp_enabled", "sessions_allowed", "strategy") if k in before}
    assert s.put(f"{PEP}/settings", json=keep, timeout=30).status_code == 200


def test_evolution_records_lab_source(s):
    r = s.get(f"{PEP}/evolution", timeout=30)
    if r.status_code != 200:
        pytest.skip("no evolution route")
    body = r.json()
    events = body if isinstance(body, list) else body.get("events", [])
    assert any(e.get("source") == "lab" for e in events)
