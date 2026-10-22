"""Iteration 36 (testing agent) – independent checks for the 'unknown result + unverifiable' fix: reconcile budget (45 s), pending order doc
in Mongo for the user's exact scenario, adoption consuming the pending, external 'manual-1' position NOT adopted, pending expiry (2 h).
Run sequentially (-n 0) against the MetaApi mock (:8012); needs forex market open."""
import os
import re
import sys
import time
import asyncio
import subprocess
from datetime import datetime, timedelta, timezone
import pytest
import requests

sys.path.insert(0, "/app/backend")
from fx.metaapi import MetaApi, MetaApiError  # noqa: E402
from fx.live import FxLiveBroker, is_our_link, RECONCILE_BUDGET_SEC  # noqa: E402

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
FX = f"{BASE_URL}/api/fx"
MOCK = "http://127.0.0.1:8012"
H = {"auth-token": "mocktoken"}
CFG = {"metaapi_token": "mocktoken", "mt_login": "12345678", "mt_password": "masterpass", "mt_server": "HFMarketsGlobal-Demo", "mt_platform": "mt5",
       "metaapi_region": "new-york", "metaapi_base_url": MOCK, "mt_symbol_suffix": "", "metaapi_plan": "g2-high"}
LOOP = asyncio.new_event_loop()


def run(c):
    return LOOP.run_until_complete(c)


def mstate():
    return requests.get(f"{MOCK}/mock/state", timeout=10).json()


def fault(**kw):
    assert requests.post(f"{MOCK}/mock/fault", params=kw, timeout=10).status_code == 200


def clear_fault():
    requests.post(f"{MOCK}/mock/fault", params={"times": 0}, timeout=10)


def _db():
    from pymongo import MongoClient
    from dotenv import dotenv_values
    env = dotenv_values("/app/backend/.env")
    return MongoClient(env["MONGO_URL"])[env["DB_NAME"]]


def mid(sym):
    t = requests.get(f"{MOCK}/users/current/accounts/x/symbols/{sym}/current-tick", headers=H, timeout=10).json()
    return (t["bid"] + t["ask"]) / 2


# ---------- helper / unit ----------
def test_is_our_link():
    assert is_our_link("AIT_deadbeef_o") and is_our_link("AIT_0123abcd_o")
    for bad in ("AIT_deadbeef_c", "manual-1", "", None, "AIT_DEADBEEF_o", "AIT_deadbee_o", "xAIT_deadbeef_o"):
        assert not is_our_link(bad), bad
    assert RECONCILE_BUDGET_SEC == 45.0


@pytest.fixture(scope="module")
def acc():
    requests.post(f"{MOCK}/mock/reset", timeout=10)
    api = MetaApi("mocktoken", "new-york", MOCK)
    created = run(api.provision("12345678", "masterpass", "HFMarketsGlobal-Demo", "mt5"))
    run(api.aclose())
    return created["id"]


def test_reconcile_budget_enforced(acc):
    """Verification that never answers (GET /positions hangs past read timeout repeatedly) must stop at ~45 s, keep kind='unknown'."""
    b = FxLiveBroker("mocktoken", acc, "new-york", MOCK)
    b.api.trade_timeout, b.api.read_timeout = 1.5, 20
    p = mid("EURUSD")
    run(b.lot("EURUSD"))
    fault(trade_hang=3, times=1, positions_hang=25, positions_times=100)
    t0, err = time.time(), None
    try:
        run(b.open("EURUSD", "long", 0.03, p - 0.01, p + 0.02))
    except MetaApiError as e:
        err = e
    finally:
        dt = time.time() - t0
        clear_fault()
        run(b.aclose())
    print("budget run:", round(dt, 1), err and (err.kind, err.attempts, err.msg))
    assert err is not None and err.kind == "unknown" and err.attempts == 1
    assert "no se pudo verificar en HFM" in err.msg and "sin respuesta en 45 s" in err.msg
    assert re.fullmatch(r"AIT_[0-9a-f]{8}_o", err.link_id)
    assert 44 <= dt <= 52, dt
    pos = mstate()["positions"]
    assert len(pos) == 1 and pos[0]["clientId"] == err.link_id, "executed once, never re-sent"
    requests.post(f"{MOCK}/mock/reset", timeout=10)


# ---------- engine ----------
@pytest.fixture(scope="module")
def s():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": "BlackCat2233@"}, timeout=30)
    assert r.status_code == 200, r.text
    sess = requests.Session()
    sess.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return sess


@pytest.fixture(scope="module")
def live(s, acc):
    requests.post(f"{MOCK}/mock/reset", timeout=10)
    s.post(f"{FX}/bot/stop", timeout=30)
    s.post(f"{FX}/positions/close-all", timeout=60)
    assert s.put(f"{FX}/config", json=CFG, timeout=30).status_code == 200
    assert s.post(f"{FX}/hfm/link", timeout=60).status_code == 200
    assert s.post(f"{FX}/hfm/test", json={}, timeout=60).json()["info"]
    r = s.post(f"{FX}/mode", json={"mode": "live", "confirm": "REAL", "reset_stats": True}, timeout=60)
    assert r.status_code == 200, r.text
    yield
    clear_fault()
    s.post(f"{FX}/positions/close-all", timeout=60)
    s.post(f"{FX}/mode", json={"mode": "paper", "confirm": "", "reset_stats": True}, timeout=60)
    s.put(f"{FX}/config", json={"clear_hfm": True}, timeout=30)
    s.put(f"{FX}/config", json={"metaapi_base_url": "", "mt_symbol_suffix": ""}, timeout=30)
    requests.post(f"{MOCK}/mock/reset", timeout=10)
    _db().fx_pending_orders.delete_many({})


def inject(sym, side):
    out = subprocess.run(["python3", "scripts/fx_inject_signal.py", sym, side, "noai"], cwd="/app", capture_output=True, text=True, timeout=240)
    return out.stdout + out.stderr


def logs(s, since=""):
    return [(l["level"] if "level" in l else "", l["message"]) for l in s.get(f"{FX}/dashboard", timeout=60).json()["logs"] if l["ts"] >= since]


def wait_positions(s, n, secs=40):
    t0 = time.time()
    while time.time() - t0 < secs:
        pos = s.get(f"{FX}/positions", timeout=30).json()
        if len(pos) >= n:
            return pos, time.time() - t0
        time.sleep(2)
    return s.get(f"{FX}/positions", timeout=30).json(), time.time() - t0


class TestEngine:
    def test_01_user_scenario_pending_doc_then_adopted(self, s, live):
        db = _db()
        since = datetime.now(timezone.utc).isoformat()
        fault(trade_code="TRADE_RETCODE_DISCONNECTED_DURING_TRADE", trade_code_num=-11, trade_execute="true", times=1, positions_after_trade=40, positions_status=503)
        t0 = time.time()
        out = inject("EURUSD", "long")
        print("inject took", round(time.time() - t0, 1), out[-300:])
        assert "'executed': True" not in out
        msgs = logs(s, since)
        err = [m for lv, m in msgs if "EURUSD: orden REAL con resultado desconocido" in m]
        assert err and "no se pudo verificar en HFM" in err[0], msgs[:6]
        link = re.search(r"AIT_[0-9a-f]{8}_o", err[0]).group(0)
        assert not any("no quedó ninguna orden abierta" in m or "orden REAL rechazada" in m for _, m in msgs)
        pend = db.fx_pending_orders.find_one({"_id": link})
        assert pend, "pending doc must exist while the result is unknown"
        for k in ("symbol", "side", "strategy", "signal_id", "atr", "sl", "tp", "lots", "leverage", "expires_at", "created_at"):
            assert k in pend, k
        assert pend["symbol"] == "EURUSD" and pend["side"] == "long"
        mp = mstate()["positions"]
        assert len(mp) == 1 and mp[0]["clientId"] == link
        assert s.get(f"{FX}/positions", timeout=30).json() == [], "not registered locally yet"
        clear_fault()
        pos, dt = wait_positions(s, 1)
        print("adopted after", round(dt, 1), "s")
        assert len(pos) == 1
        p = pos[0]
        assert p["order_id"] == mp[0]["id"] and p["link_id"] == link and p["strategy"] == pend["strategy"] != "adoptada" and p["signal_id"] == pend["signal_id"]
        assert abs(p["sl"] - mp[0]["stopLoss"]) < 1e-6 and abs(p["tp"] - mp[0]["takeProfit"]) < 1e-6 and p["qty"] == mp[0]["volume"]
        assert db.fx_pending_orders.count_documents({}) == 0
        assert db.fx_shadow_positions.count_documents({"signal_id": pend["signal_id"]}) == 0
        sig = next(x for x in s.get(f"{FX}/signals", timeout=30).json() if x["id"] == pend["signal_id"])
        assert sig["executed"] is True and "confirmada por su identificador" in sig["note"]
        assert sum("ADOPTADA REAL LONG EURUSD" in m and "resultado desconocido confirmada en HFM" in m for _, m in logs(s, since)) == 1
        time.sleep(12)  # several monitor cycles: no duplicate adoption
        assert len(s.get(f"{FX}/positions", timeout=30).json()) == 1
        r = s.post(f"{FX}/positions/{p['id']}/close", timeout=120)
        assert r.status_code == 200, r.text
        time.sleep(1)
        assert mstate()["positions"] == [] and s.get(f"{FX}/positions", timeout=30).json() == []
        tr = [t for t in s.get(f"{FX}/trades", timeout=30).json() if t["closed_at"] >= since and t["symbol"] == "EURUSD"]
        assert tr and tr[0]["live"] and tr[0]["strategy"] == pend["strategy"]

    def test_02_orphan_ours_adopted_external_not(self, s, live, acc):
        since = datetime.now(timezone.utc).isoformat()
        p0 = mid("GBPUSD")
        for cid in ("AIT_deadbeef_o", "manual-1"):
            r = requests.post(f"{MOCK}/users/current/accounts/{acc}/trade", headers=H, json={"actionType": "ORDER_TYPE_SELL", "symbol": "GBPUSD", "volume": 0.02,
                              "stopLoss": round(p0 + 0.01, 5), "takeProfit": round(p0 - 0.02, 5), "clientId": cid, "magic": 777001}, timeout=10)
            assert r.status_code == 200, r.text
        pos, dt = wait_positions(s, 1)
        time.sleep(8)
        pos = s.get(f"{FX}/positions", timeout=30).json()
        print("orphan adopted after", round(dt, 1), pos)
        assert len(pos) == 1, "only our clientId adopted"
        p = pos[0]
        assert p["link_id"] == "AIT_deadbeef_o" and p["strategy"] == "adoptada" and p["side"] == "short" and p["qty"] == 0.02 and p["live"]
        msgs = [m for _, m in logs(s, since)]
        assert any("ADOPTADA REAL SHORT GBPUSD" in m and "sin registro local" in m for m in msgs)
        ext = [m for m in msgs if "posición externa detectada en HFM (no gestionada por el bot)" in m]
        assert len(ext) == 1, ext
        assert s.post(f"{FX}/positions/{p['id']}/close", timeout=120).status_code == 200
        time.sleep(1)
        left = mstate()["positions"]
        assert len(left) == 1 and left[0]["clientId"] == "manual-1", "bot must not touch the external position"
        requests.post(f"{MOCK}/mock/close/{left[0]['id']}", params={"reason": "tp"}, timeout=10)

    def test_03_pending_expires_after_2h(self, s, live):
        db = _db()
        since = datetime.now(timezone.utc).isoformat()
        old = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        fresh = datetime.now(timezone.utc).isoformat()
        db.fx_pending_orders.insert_many([{"_id": "AIT_0badc0de_o", "symbol": "USDJPY", "side": "long", "created_at": old},
                                          {"_id": "AIT_0000beef_o", "symbol": "USDJPY", "side": "long", "created_at": fresh}])
        t0 = time.time()
        while time.time() - t0 < 40 and db.fx_pending_orders.find_one({"_id": "AIT_0badc0de_o"}):
            time.sleep(2)
        assert db.fx_pending_orders.find_one({"_id": "AIT_0badc0de_o"}) is None
        assert db.fx_pending_orders.find_one({"_id": "AIT_0000beef_o"}), "fresh pending kept"
        assert any("AIT_0badc0de_o" in m and "se da por no ejecutada" in m for _, m in logs(s, since))
        assert s.post(f"{FX}/account/reset", json={}, timeout=60).status_code in (200, 409)
        print("pending after reset:", db.fx_pending_orders.count_documents({}))
        db.fx_pending_orders.delete_many({})
