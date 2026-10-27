"""Iteration 53 — Pepperstone AI trading: second FX engine instance (/api/pepper/*, pep_* collections, broker profile + account types)."""
import os
import pytest
import requests

from fx.broker import HFM, PEPPERSTONE, PROFILES, BY_PANEL

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
FX = f"{BASE_URL}/api/fx"
PEP = f"{BASE_URL}/api/pepper"


@pytest.fixture(scope="module")
def s():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": "BlackCat2233@"}, timeout=30)
    assert r.status_code == 200, r.text
    sess = requests.Session()
    sess.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return sess


def test_profiles():
    assert set(PROFILES) == {"hfm", "pepperstone"} and BY_PANEL["fx"] is HFM and BY_PANEL["pepper"] is PEPPERSTONE
    assert PEPPERSTONE.prefix == "pep_" and PEPPERSTONE.api_prefix == "/api/pepper"
    razor, std = PEPPERSTONE.costs("razor"), PEPPERSTONE.costs("standard")
    assert razor.commission_lot_usd == 7.0 and razor.spread_factor < std.spread_factor and std.commission_lot_usd == 0
    assert PEPPERSTONE.costs("nope") == PEPPERSTONE.costs()  # unknown → default
    assert HFM.costs().commission_lot_usd == 0 and HFM.costs().spread_factor == 1.0


@pytest.mark.parametrize("path", ["/dashboard", "/config", "/overview", "/positions", "/signals", "/settings"])
def test_pepper_requires_auth(path):
    assert requests.get(f"{PEP}{path}", timeout=30).status_code in (401, 403)


def test_pepper_overview_and_dashboard(s):
    r = s.get(f"{PEP}/overview", timeout=30)
    assert r.status_code == 200 and set(r.json()) >= {"running", "mode", "equity", "open_positions"}
    d = s.get(f"{PEP}/dashboard", timeout=60).json()
    st = d["status"]
    assert st["broker"] == "Pepperstone" and st["bot_name"] == "Pepperstone AI trading"
    assert st["costs"]["commission_lot_usd"] in (7.0, 0.0) and "label" in st["costs"]
    fx = s.get(f"{FX}/dashboard", timeout=60).json()["status"]
    assert fx["broker"] == "HFM" and fx["costs"]["commission_lot_usd"] == 0.0


def test_pepper_config_broker_block(s):
    c = s.get(f"{PEP}/config", timeout=30).json()
    b = c["broker"]
    assert b["key"] == "pepperstone" and b["server_hint"].startswith("Pepperstone")
    assert {t["key"] for t in b["account_types"]} == {"razor", "standard"}
    assert b["servers"]["mt5"] and b["suffixes"][0]["suffix"] == ""
    f = s.get(f"{FX}/config", timeout=30).json()["broker"]
    assert f["key"] == "hfm" and len(f["account_types"]) == 1 and len(f["suffixes"]) >= 4


def test_pepper_account_type_switch(s):
    r = s.put(f"{PEP}/config", json={"account_type": "standard"}, timeout=30)
    assert r.status_code == 200 and r.json()["broker"]["account_type"] == "standard"
    assert s.get(f"{PEP}/dashboard", timeout=60).json()["status"]["costs"]["commission_lot_usd"] == 0.0
    assert s.put(f"{PEP}/config", json={"account_type": "nope"}, timeout=30).status_code in (400, 422)
    r = s.put(f"{PEP}/config", json={"account_type": "razor"}, timeout=30)
    assert r.json()["broker"]["account_type"] == "razor"
    assert s.get(f"{PEP}/dashboard", timeout=60).json()["status"]["costs"]["commission_lot_usd"] == 7.0
    # HFM profile has a single account type → changing it is rejected
    assert s.put(f"{FX}/config", json={"account_type": "razor"}, timeout=30).status_code in (400, 422)


def test_pepper_settings_independent_from_hfm(s):
    fx0 = s.get(f"{FX}/settings", timeout=30).json()
    pp0 = s.get(f"{PEP}/settings", timeout=30).json()
    new = 0.9 if abs(pp0["risk_per_trade"] - 0.9) > 1e-9 else 0.8
    r = s.put(f"{PEP}/settings", json={"risk_per_trade": new}, timeout=30)
    assert r.status_code == 200, r.text
    assert abs(s.get(f"{PEP}/settings", timeout=30).json()["risk_per_trade"] - new) < 1e-9
    assert abs(s.get(f"{FX}/settings", timeout=30).json()["risk_per_trade"] - fx0["risk_per_trade"]) < 1e-9
    s.put(f"{PEP}/settings", json={"risk_per_trade": pp0["risk_per_trade"]}, timeout=30)


def test_pepper_hfm_routes_branded(s):
    r = s.post(f"{PEP}/hfm/link", timeout=30)
    assert r.status_code in (400, 409, 424), r.text
    assert "Pepperstone" in r.json()["detail"] or "MetaApi" in r.json()["detail"]
    r = s.post(f"{PEP}/hfm/test", json={}, timeout=30)
    assert r.status_code in (400, 424)


def test_pepper_start_stop(s):
    r = s.post(f"{PEP}/bot/start", timeout=30)
    assert r.status_code == 200, r.text
    assert s.get(f"{PEP}/overview", timeout=30).json()["running"] is True
    assert s.get(f"{FX}/overview", timeout=30).json()["running"] is False
    r = s.post(f"{PEP}/bot/stop", timeout=30)
    assert r.status_code == 200 and s.get(f"{PEP}/overview", timeout=30).json()["running"] is False


def test_backup_info_three_bots(s):
    r = s.get(f"{BASE_URL}/api/backup", timeout=30)
    assert r.status_code == 200
    assert set(r.json()["bots_running"]) == {"crypto", "fx", "pepper"}


def test_chat_knows_pepper(s):
    r = s.get(f"{BASE_URL}/api/chat", params={"bot": "pepper"}, timeout=30)
    assert r.status_code == 200 and "session" in r.json()
    r = s.post(f"{BASE_URL}/api/chat/proposals/000000000000000000000000/apply", timeout=30)
    assert r.status_code in (404, 400)
