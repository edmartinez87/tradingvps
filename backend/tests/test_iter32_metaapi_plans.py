"""Iteration 32 – MetaApi account type selector (Cloud G2 high / G1 regular / G1 high): plans in config, provisioning with type+reliability,
plan mismatch detection on link/test/mode checks, /hfm/recreate (delete + create with the new plan), idempotent HFM save. Uses the local MetaApi mock (:8012)."""
import os
import sys
import time
import subprocess
import pytest
import requests

sys.path.insert(0, "/app/backend")
from fx.metaapi import PLANS, plan_key  # noqa: E402

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
FX = f"{BASE_URL}/api/fx"
MOCK = "http://127.0.0.1:8012"
CFG = {"metaapi_token": "mocktoken", "mt_login": "12345678", "mt_password": "masterpass", "mt_server": "HFMarketsGlobal-Demo", "mt_platform": "mt5",
       "metaapi_region": "new-york", "metaapi_base_url": MOCK, "mt_symbol_suffix": ""}


def _up():
    try:
        return requests.get(f"{MOCK}/mock/state", timeout=2).status_code == 200
    except Exception:
        return False


def mock_accounts():
    return requests.get(f"{MOCK}/mock/state", timeout=10).json()["accounts"]


@pytest.fixture(scope="module")
def s():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": "BlackCat2233@"}, timeout=30)
    assert r.status_code == 200, r.text
    sess = requests.Session()
    sess.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return sess


@pytest.fixture(scope="module")
def mock():
    if not _up():
        subprocess.Popen(["python3", "scripts/metaapi_mock.py"], cwd="/app", stdout=open("/tmp/metaapi_mock.log", "a"), stderr=subprocess.STDOUT)
        t0 = time.time()
        while time.time() - t0 < 20 and not _up():
            time.sleep(1)
        assert _up(), "mock did not start"
    requests.post(f"{MOCK}/mock/reset", timeout=10)
    return MOCK


@pytest.fixture(scope="module")
def saved(s, mock):
    s.post(f"{FX}/bot/stop", timeout=30)
    yield
    s.post(f"{FX}/bot/stop", timeout=30)
    s.put(f"{FX}/config", json={"clear_hfm": True}, timeout=30)
    s.put(f"{FX}/config", json={"metaapi_base_url": "", "mt_symbol_suffix": "", "metaapi_plan": "g2-high"}, timeout=30)


class TestPlansUnit:
    def test_plans_and_plan_key(self):
        assert set(PLANS) == {"g2-high", "g1-regular", "g1-high"}
        assert PLANS["g2-high"]["recommended"] and PLANS["g2-high"]["hour_usd"] < PLANS["g1-regular"]["hour_usd"] < PLANS["g1-high"]["hour_usd"]
        assert plan_key("cloud-g2", "high") == "g2-high" and plan_key("cloud", "") == "g2-high" and plan_key("cloud-g2", "regular") == "g2-high"
        assert plan_key("cloud-g1", "regular") == "g1-regular" and plan_key("cloud-g1", "high") == "g1-high" and plan_key("cloud-g1", "") == "g1-high"


class TestPlanFlow:
    def test_01_config_exposes_plans(self, s, saved):
        c = s.get(f"{FX}/config", timeout=30).json()
        keys = [p["key"] for p in c["metaapi_plans"]]
        assert keys == ["g2-high", "g1-regular", "g1-high"]
        g2 = c["metaapi_plans"][0]
        assert g2["hour_usd"] == 0.012 and g2["month_usd"] == 8.64 and g2["deploy_usd"] == 0.072 and g2["recommended"] is True
        assert c["metaapi_plan_common"] == {"account_month_usd": 2.1, "undeployed_hour_usd": 0.00105}
        assert c["metaapi_plan"] in PLANS and c["hfm_plan_mismatch"] is False and c["hfm_current_plan"] == ""

    def test_02_invalid_plan_rejected(self, s, saved):
        r = s.put(f"{FX}/config", json={"metaapi_plan": "g3-ultra"}, timeout=30)
        assert r.status_code == 422 and "Tipo de cuenta" in r.text

    def test_03_link_with_g1_regular(self, s, saved):
        r = s.put(f"{FX}/config", json={**CFG, "metaapi_plan": "g1-regular"}, timeout=30)
        assert r.status_code == 200, r.text
        r = s.post(f"{FX}/hfm/link", timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["plan_mismatch"] is False and d["account"]["type"] == "cloud-g1" and d["account"]["reliability"] == "regular" and d["account"]["plan"] == "g1-regular"
        accs = mock_accounts()
        assert len(accs) == 1 and accs[0]["type"] == "cloud-g1" and accs[0]["reliability"] == "regular"
        c = s.get(f"{FX}/config", timeout=30).json()
        assert c["hfm_account_type"] == "cloud-g1" and c["hfm_reliability"] == "regular" and c["hfm_current_plan"] == "g1-regular" and c["hfm_plan_mismatch"] is False
        assert c["metaapi_account_id"] == accs[0]["_id"]

    def test_04_saving_same_values_keeps_link(self, s, saved):
        r = s.put(f"{FX}/config", json={**CFG, "metaapi_plan": "g1-regular", "hfm_alert_after_sec": 60}, timeout=30)
        assert r.status_code == 200, r.text
        c = r.json()
        assert c["metaapi_account_id"] and c["hfm_current_plan"] == "g1-regular"

    def test_05_change_plan_flags_mismatch(self, s, saved):
        r = s.put(f"{FX}/config", json={**CFG, "metaapi_plan": "g2-high"}, timeout=30)
        assert r.status_code == 200, r.text
        c = r.json()
        assert c["metaapi_account_id"] and c["hfm_plan_mismatch"] is True and c["hfm_current_plan"] == "g1-regular"
        t = s.post(f"{FX}/hfm/test", json={}, timeout=60).json()
        assert t["plan_mismatch"] is True and "Recrear con el nuevo tipo" in t["hint"] and t["account"]["plan"] == "g1-regular"
        l = s.post(f"{FX}/hfm/link", timeout=60).json()
        assert l["plan_mismatch"] is True and "G1 regular" in l["hint"] and "G2 alta" in l["hint"]
        assert len(mock_accounts()) == 1  # link never silently recreates
        m = s.get(f"{FX}/mode", timeout=30).json()
        linked = next(x for x in m["checks"] if x["key"] == "linked")
        assert linked["warn"] is True and "G1 regular" in linked["detail"] and "recrear" in linked["detail"].lower()

    def test_06_recreate_requires_stopped_bot(self, s, saved):
        r = s.post(f"{FX}/bot/start", timeout=60)
        assert r.status_code == 200, r.text
        try:
            r = s.post(f"{FX}/hfm/recreate", timeout=60)
            assert r.status_code == 409 and "Detén el bot" in r.text
        finally:
            s.post(f"{FX}/bot/stop", timeout=30)

    def test_07_recreate_with_new_plan(self, s, saved):
        old_id = s.get(f"{FX}/config", timeout=30).json()["metaapi_account_id"]
        r = s.post(f"{FX}/hfm/recreate", timeout=90)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["account"]["plan"] == "g2-high" and d["account"]["id"] != old_id and "G1 regular" in d["removed"] and "Cloud G2" in d["hint"]
        accs = mock_accounts()
        assert len(accs) == 1 and accs[0]["type"] == "cloud-g2" and accs[0]["reliability"] == "high" and accs[0]["_id"] == d["account"]["id"]
        c = s.get(f"{FX}/config", timeout=30).json()
        assert c["metaapi_account_id"] == d["account"]["id"] and c["hfm_plan_mismatch"] is False and c["hfm_current_plan"] == "g2-high" and c["hfm_verified_at"] is None
        m = s.get(f"{FX}/mode", timeout=30).json()
        linked = next(x for x in m["checks"] if x["key"] == "linked")
        assert linked["ok"] is True and linked["warn"] is False and "G2 alta" in linked["detail"]
        logs = s.get(f"{FX}/dashboard", timeout=60).json()["logs"]
        assert any("recreada en MetaApi como Cloud G2" in l["message"] for l in logs)

    def test_08_test_connection_stores_plan(self, s, saved):
        t = s.post(f"{FX}/hfm/test", json={}, timeout=60).json()
        assert t.get("plan_mismatch") is None and t["account"]["plan"] == "g2-high" and t["info"]
        c = s.get(f"{FX}/config", timeout=30).json()
        assert c["hfm_verified_at"] and c["hfm_current_plan"] == "g2-high"

    def test_09_clear_resets_plan_tracking(self, s, saved):
        c = s.put(f"{FX}/config", json={"clear_hfm": True}, timeout=30).json()
        assert c["hfm_account_type"] == "" and c["hfm_reliability"] == "" and c["hfm_current_plan"] == "" and c["hfm_plan_mismatch"] is False
