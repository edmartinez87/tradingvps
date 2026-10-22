"""Iteration 38 (testing agent) – extra edge cases for the HFM symbol-suffix feature: guards without linked account, idempotent suffix PUT,
clear_hfm resets new fields, behaviour of «Comprobar símbolos» when MetaApi/broker is unreachable. Run with -n 0."""
import os
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
FX = f"{BASE_URL}/api/fx"
MOCK = "http://127.0.0.1:8012"
CFG = {"metaapi_token": "mocktoken", "mt_login": "12345678", "mt_password": "masterpass", "mt_server": "HFMarketsGlobal-Demo", "mt_platform": "mt5",
       "metaapi_region": "new-york", "metaapi_base_url": MOCK, "mt_symbol_suffix": "", "metaapi_plan": "g2-high"}


@pytest.fixture(scope="module")
def s():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": "BlackCat2233@"}, timeout=30)
    assert r.status_code == 200
    sess = requests.Session()
    sess.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    yield sess
    sess.put(f"{FX}/config", json={"clear_hfm": True}, timeout=30)
    sess.put(f"{FX}/config", json={"metaapi_base_url": "", "mt_symbol_suffix": ""}, timeout=30)
    requests.post(f"{MOCK}/mock/reset", timeout=10)


# Guards: endpoints require a linked account
def test_01_guards_without_account(s):
    requests.post(f"{MOCK}/mock/reset", timeout=10)
    s.put(f"{FX}/config", json={"clear_hfm": True}, timeout=30)
    for ep in ("hfm/symbols", "hfm/detect-suffix"):
        r = s.post(f"{FX}/{ep}", timeout=30)
        assert r.status_code == 400 and "Vincula" in r.text, (ep, r.text)
    cfg = s.get(f"{FX}/config", timeout=30).json()
    assert cfg["hfm_symbols_bad"] is None and cfg["hfm_suffix_kind"] == "" and cfg["mt_symbol_suffix"] == ""


# Same suffix PUT keeps check result; clear_hfm wipes the new fields
def test_02_idempotent_put_and_clear(s):
    requests.post(f"{MOCK}/mock/account-group", params={"suffix": "b"}, timeout=10)
    assert s.put(f"{FX}/config", json=CFG, timeout=30).status_code == 200
    assert s.post(f"{FX}/hfm/link", timeout=60).status_code == 200
    d = s.post(f"{FX}/hfm/test", json={}, timeout=180).json()
    assert d["suffix"]["suffix"] == "b" and d["symbols"]["disabled"] == []
    assert s.put(f"{FX}/config", json={"mt_symbol_suffix": "b"}, timeout=30).status_code == 200
    assert s.get(f"{FX}/config", timeout=30).json()["hfm_symbols_bad"] == []
    # second test → matches, no re-apply
    d = s.post(f"{FX}/hfm/test", json={}, timeout=180).json()
    assert d["suffix"]["matches"] is True and not d["suffix"].get("applied") and "correcto" in d["suffix"]["hint"]


# Broker unreachable during «Comprobar símbolos»: are pairs persisted as bad (and then blocked by the engine)?
def test_03_symbols_check_when_broker_down(s):
    requests.post(f"{MOCK}/mock/connection", params={"connected": "false"}, timeout=10)
    try:
        r = s.post(f"{FX}/hfm/symbols", timeout=180)
        print("status", r.status_code, r.text[:600])
        cfg = s.get(f"{FX}/config", timeout=30).json()
        print("hfm_symbols_bad after outage:", cfg["hfm_symbols_bad"])
    finally:
        requests.post(f"{MOCK}/mock/connection", params={"connected": "true"}, timeout=10)
    # documented behaviour check: a transient outage should not permanently mark every pair as non-tradable
    assert not cfg["hfm_symbols_bad"], f"outage persisted as non-tradable pairs: {cfg['hfm_symbols_bad']}"
