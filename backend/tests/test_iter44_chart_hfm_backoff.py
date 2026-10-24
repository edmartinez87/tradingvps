"""Iteration 44 – HFM chart source back-off: once the MetaApi connection recovers (or the account is relinked) the chart should go back to
HFM candles instead of staying on Yahoo for 120 s globally. Run with -n 0 AFTER test_iter43 (shares mock + fx_config)."""
import os
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
FX, MOCK = f"{BASE_URL}/api/fx", "http://127.0.0.1:8012"
CFG = {"metaapi_token": "mocktoken", "mt_login": "12345678", "mt_password": "masterpass", "mt_server": "HFMarketsGlobal-Demo", "mt_platform": "mt5",
       "metaapi_region": "new-york", "metaapi_base_url": MOCK, "mt_symbol_suffix": "", "metaapi_plan": "g2-high"}


@pytest.fixture(scope="module")
def s():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": "BlackCat2233@"}, timeout=30)
    assert r.status_code == 200
    sess = requests.Session()
    sess.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    requests.post(f"{MOCK}/mock/reset", timeout=10)
    assert sess.put(f"{FX}/config", json=CFG, timeout=30).status_code == 200
    assert sess.post(f"{FX}/hfm/link", timeout=60).status_code == 200
    yield sess
    requests.post(f"{MOCK}/mock/connection", params={"connected": "true"}, timeout=10)
    sess.put(f"{FX}/config", json={"clear_hfm": True}, timeout=30)
    sess.put(f"{FX}/config", json={"metaapi_base_url": "", "mt_symbol_suffix": ""}, timeout=30)
    requests.post(f"{MOCK}/mock/reset", timeout=10)


def test_hfm_source_recovers_after_reconnect(s):
    requests.post(f"{MOCK}/mock/connection", params={"connected": "false"}, timeout=10)
    assert s.get(f"{FX}/klines", params={"symbol": "USDJPY", "tf": "1h"}, timeout=90).json()["source"] == "yahoo"
    requests.post(f"{MOCK}/mock/connection", params={"connected": "true"}, timeout=10)
    # relink (user action) should clear the back-off
    assert s.post(f"{FX}/hfm/link", timeout=60).status_code == 200
    d = s.get(f"{FX}/klines", params={"symbol": "EURUSD", "tf": "1h"}, timeout=90).json()
    assert d["source"] == "hfm", "global 120 s back-off (_hfm_chart.fail_ts) keeps the chart on Yahoo after reconnect/relink"
