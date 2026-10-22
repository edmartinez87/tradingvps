"""Iteration 36 report – HFM odd metal names (Zero group: XAUUSD → GOLDb, XAGUSD → XAGUSD.b). User scenario end-to-end via API + REAL order
with a resolved name + reverse mapping in the monitor. Run with -n 0 (shares the mock + fx_config)."""
import asyncio
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
import pytest
import requests
sys.path.insert(0, "/app/backend")
from fx.live import FxLiveBroker  # noqa: E402
from fx.market import market_open  # noqa: E402

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
FX = f"{BASE_URL}/api/fx"
MOCK = "http://127.0.0.1:8012"
CFG = {"metaapi_token": "mocktoken", "mt_login": "12345678", "mt_password": "masterpass", "mt_server": "HFMarketsGlobal-Demo", "mt_platform": "mt5",
       "metaapi_region": "new-york", "metaapi_base_url": MOCK, "mt_symbol_suffix": "", "metaapi_plan": "g2-high"}
METALS = {"XAUUSD": "GOLDb", "XAGUSD": "XAGUSD.b"}


def group(suffix):
    assert requests.post(f"{MOCK}/mock/account-group", params={"suffix": suffix}, timeout=10).status_code == 200


def now_s():
    return datetime.now(timezone.utc).isoformat()


def logs(s, since=""):
    return [l["message"] for l in s.get(f"{FX}/dashboard", timeout=60).json()["logs"] if l["ts"] >= since]


def cfg(s):
    return s.get(f"{FX}/config", timeout=30).json()


@pytest.fixture(scope="module")
def s():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": "BlackCat2233@"}, timeout=30)
    assert r.status_code == 200, r.text
    sess = requests.Session()
    sess.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return sess


@pytest.fixture(scope="module")
def zero(s):
    requests.post(f"{MOCK}/mock/reset", timeout=10)
    group("b")
    s.post(f"{FX}/bot/stop", timeout=30)
    s.post(f"{FX}/positions/close-all", timeout=60)
    assert s.put(f"{FX}/config", json=CFG, timeout=30).status_code == 200
    assert s.post(f"{FX}/hfm/link", timeout=60).status_code == 200
    yield
    s.post(f"{FX}/bot/stop", timeout=30)
    s.post(f"{FX}/positions/close-all", timeout=60)
    s.post(f"{FX}/mode", json={"mode": "paper", "confirm": "", "reset_stats": True}, timeout=60)
    s.put(f"{FX}/config", json={"clear_hfm": True}, timeout=30)
    s.put(f"{FX}/config", json={"metaapi_base_url": "", "mt_symbol_suffix": ""}, timeout=30)
    requests.post(f"{MOCK}/mock/reset", timeout=10)


class TestUserScenario:
    def test_01_detect_suffix_b(self, s, zero):
        r = s.post(f"{FX}/hfm/detect-suffix", json={}, timeout=90)
        assert r.status_code == 200, r.text
        assert r.json().get("suffix") == "b", r.json()

    def test_02_symbols_resolved(self, s, zero):
        since = now_s()
        r = s.post(f"{FX}/hfm/symbols", json={}, timeout=120)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["missing"] == [] and d["disabled"] == [] and d["errors"] == [], d
        assert d["resolved"] == METALS
        x = d["symbols"]["XAUUSD"]
        assert x["ok"] is True and x["broker_symbol"] == "GOLDb" and x["resolved"] is True
        assert d["symbols"]["XAGUSD"]["broker_symbol"] == "XAGUSD.b"
        e = d["symbols"]["EURUSD"]
        assert e["broker_symbol"] == "EURUSDb" and e["resolved"] is False
        c = cfg(s)
        assert c["mt_symbol_map"] == METALS and c["hfm_symbols_bad"] == []
        chk = next(c for c in s.get(f"{FX}/mode", timeout=30).json()["checks"] if c["key"] == "symbols")
        assert chk["ok"] is True, chk
        assert any("nombres resueltos en la cuenta: XAUUSD → GOLDb" in m for m in logs(s, since))

    def test_03_hfm_test_returns_resolved(self, s, zero):
        r = s.post(f"{FX}/hfm/test", json={}, timeout=120)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["symbols"]["resolved"] == METALS, d.get("symbols")

    def test_04_premium_then_back_to_zero(self, s, zero):
        group("")
        d = s.post(f"{FX}/hfm/test", json={}, timeout=120).json()
        assert d["suffix"]["suffix"] == "", d.get("suffix")
        assert d["symbols"]["resolved"] == {}
        assert cfg(s)["mt_symbol_map"] == {}
        group("b")
        d = s.post(f"{FX}/hfm/test", json={}, timeout=120).json()
        assert d["suffix"]["suffix"] == "b"
        assert d["symbols"]["resolved"] == METALS
        assert cfg(s)["mt_symbol_map"] == METALS

    def test_05_suffix_change_clears_map(self, s, zero):
        assert s.put(f"{FX}/config", json={"mt_symbol_suffix": "r"}, timeout=30).status_code == 200
        assert cfg(s)["mt_symbol_map"] == {}
        # restore for the REAL order test
        assert s.put(f"{FX}/config", json={"mt_symbol_suffix": "b"}, timeout=30).status_code == 200
        d = s.post(f"{FX}/hfm/symbols", json={}, timeout=120).json()
        assert d["resolved"] == METALS and cfg(s)["mt_symbol_map"] == METALS

    def test_06_truly_missing_symbol_not_invented(self, zero):
        acc = requests.get(f"{MOCK}/mock/state", timeout=10).json()["accounts"][0]["_id"]

        async def run():
            b = FxLiveBroker("mocktoken", acc, "new-york", MOCK, "b")
            try:
                return await b.check_symbol("NZDJPY")
            finally:
                await b.aclose()
        r = asyncio.run(run())
        assert r["ok"] is False and r["quoted"] is False and r["transient"] is False, r
        assert "ningún nombre conocido" in r["error"] and "NZDJPY" in r["error"], r

    def test_07_real_order_with_resolved_name(self, s, zero):
        if not market_open():
            pytest.skip("forex market closed")
        r = s.post(f"{FX}/mode", json={"mode": "live", "confirm": "REAL", "reset_stats": True}, timeout=120)
        assert r.status_code == 200, r.text
        out = subprocess.run(["python3", "scripts/fx_inject_signal.py", "XAUUSD", "long", "noai"], cwd="/app", capture_output=True, text=True, timeout=180)
        txt = out.stdout + out.stderr
        assert "'executed': True" in txt, txt[-1500:]
        st = requests.get(f"{MOCK}/mock/state", timeout=10).json()
        assert [p["symbol"] for p in st["positions"]] == ["GOLDb"], st["positions"]
        pos = s.get(f"{FX}/positions", timeout=30).json()
        pos = pos.get("positions", pos) if isinstance(pos, dict) else pos
        assert len(pos) == 1 and pos[0]["symbol"] == "XAUUSD", pos
        since = now_s()
        time.sleep(9)
        assert not any("posición externa detectada" in m for m in logs(s, since)), logs(s, since)
        pos = s.get(f"{FX}/positions", timeout=30).json()
        pos = pos.get("positions", pos) if isinstance(pos, dict) else pos
        assert len(pos) == 1
        assert s.post(f"{FX}/positions/close-all", timeout=60).status_code == 200
        time.sleep(1)
        assert requests.get(f"{MOCK}/mock/state", timeout=10).json()["positions"] == []
        tr = s.get(f"{FX}/trades", timeout=30).json()
        tr = tr.get("trades", tr) if isinstance(tr, dict) else tr
        assert any(t["symbol"] == "XAUUSD" and t.get("mode", "live") == "live" for t in tr[:5]), tr[:3]
