"""Iteration 54 — Pepperstone extra checks: endpoints mirror, settings independence both ways, scan/reset, cron scheduled_pepper, chat panel=pepper (real LLM)."""
import os
import time
import pytest
import requests
from dotenv import dotenv_values

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
FX = f"{BASE_URL}/api/fx"
PEP = f"{BASE_URL}/api/pepper"
CRON = dotenv_values("/app/backend/.env").get("WEBHOOK_CRON_SECRET")


@pytest.fixture(scope="module")
def s():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": "BlackCat2233@"}, timeout=30)
    assert r.status_code == 200, r.text
    sess = requests.Session()
    sess.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return sess


# Mirror endpoints
@pytest.mark.parametrize("path", ["/logs", "/trades", "/positions", "/signals", "/settings", "/account", "/meta"])
def test_pepper_get_endpoints(s, path):
    r = s.get(f"{PEP}{path}", timeout=60)
    if path == "/logs" and r.status_code == 405:
        pytest.skip("no GET /logs")
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("path", ["/logs", "/trades", "/account"])
def test_pepper_auth_extra(path):
    assert requests.get(f"{PEP}{path}", timeout=30).status_code in (401, 403, 405)


def test_pepper_config_details(s):
    b = s.get(f"{PEP}/config", timeout=30).json()["broker"]
    assert b["server_hint"] == "Pepperstone-MT5-Live01"
    assert len(b["suffixes"]) == 1 and b["suffixes"][0]["suffix"] == ""
    assert b["servers"]["mt5"] and b["servers"]["mt4"]
    assert b.get("account_type") == "razor"


def test_fx_settings_change_does_not_affect_pepper(s):
    fx0 = s.get(f"{FX}/settings", timeout=30).json()
    pp0 = s.get(f"{PEP}/settings", timeout=30).json()
    new = 0.7 if abs(fx0["risk_per_trade"] - 0.7) > 1e-9 else 0.6
    try:
        assert s.put(f"{FX}/settings", json={"risk_per_trade": new}, timeout=30).status_code == 200
        assert abs(s.get(f"{FX}/settings", timeout=30).json()["risk_per_trade"] - new) < 1e-9
        assert abs(s.get(f"{PEP}/settings", timeout=30).json()["risk_per_trade"] - pp0["risk_per_trade"]) < 1e-9
    finally:
        s.put(f"{FX}/settings", json={"risk_per_trade": fx0["risk_per_trade"]}, timeout=30)
    assert abs(s.get(f"{FX}/settings", timeout=30).json()["risk_per_trade"] - fx0["risk_per_trade"]) < 1e-9


def test_pepper_scan(s):
    r = s.post(f"{PEP}/bot/scan", timeout=30)
    assert r.status_code in (200, 202) and r.json().get("ok") is True


def test_pepper_hfm_test_detail_branding(s):
    r = s.post(f"{PEP}/hfm/test", json={}, timeout=30)
    assert r.status_code in (400, 424)
    d = r.json()["detail"]
    assert "HFM" not in d, d
    r = s.post(f"{PEP}/hfm/link", timeout=30)
    assert "HFM" not in r.json()["detail"], r.json()["detail"]


def test_pepper_account_reset_independent(s):
    fx_before = s.get(f"{FX}/account", timeout=30).json()
    r = s.post(f"{PEP}/account/reset", json={"initial_balance": 500}, timeout=30)
    assert r.status_code == 200, r.text
    assert abs(r.json()["equity"] - 500) < 1e-6
    fx_after = s.get(f"{FX}/account", timeout=30).json()
    assert fx_after["initial_balance"] == fx_before["initial_balance"]


def test_cron_ai_review_scheduled_pepper():
    assert CRON
    r = requests.post(f"{BASE_URL}/api/cron/ai-review", headers={"Authorization": f"Bearer {CRON}"}, json={"run_id": f"TEST_pep_{int(time.time())}"}, timeout=60)
    assert r.status_code in (200, 202), r.text
    d = r.json()
    assert {"accepted", "scheduled", "scheduled_fx", "scheduled_pepper"} <= set(d), d


def test_cron_requires_secret():
    assert requests.post(f"{BASE_URL}/api/cron/ai-review", headers={"Authorization": "Bearer wrong"}, timeout=30).status_code in (401, 403)


def test_chat_pepper_real_llm(s):
    r = s.post(f"{BASE_URL}/api/chat/message", json={"text": "Resume en 3 líneas el estado del bot Pepperstone y su tipo de cuenta", "panel": "pepper"}, timeout=30)
    assert r.status_code == 200, r.text
    jid = r.json()["id"]
    j = None
    for _ in range(60):
        time.sleep(3)
        j = s.get(f"{BASE_URL}/api/chat/jobs/{jid}", timeout=30).json()
        if j["status"] != "running":
            break
    assert j and j["status"] == "done", j
    res = j["result"]
    content = res["assistant"]["content"]
    print("PANEL user msg:", res["user"].get("panel"), "\nANSWER:", content[:800])
    assert "Pepperstone" in content
    st = s.get(f"{BASE_URL}/api/chat", timeout=30).json()
    msgs = [m for m in st.get("messages", []) if m.get("id") == res["user"]["id"]]
    if msgs and "panel" in msgs[0]:
        assert msgs[0]["panel"] == "pepper", f"panel stored as {msgs[0]['panel']}"
