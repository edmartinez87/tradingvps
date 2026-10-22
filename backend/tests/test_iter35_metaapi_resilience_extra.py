"""Iteration 35 – extra coverage for the MetaApi ReadTimeout fix: _call retry semantics with an httpx MockTransport (429 recommendedRetryTime,
5xx, 404 NotSynchronized, 401, trade sent once), _retry_after clamping, reconcile failure edge case, and engine-level rejection / manual close
with a transient failure / trade disabled against the MetaApi mock (:8012). Run sequentially (-n 0); needs forex market open."""
import os
import re
import time
import json
import asyncio
import subprocess
import sys
from datetime import datetime, timedelta, timezone
import httpx
import pytest
import requests

sys.path.insert(0, "/app/backend")
from fx.metaapi import MetaApi, MetaApiError, _retry_after  # noqa: E402
from fx.live import FxLiveBroker  # noqa: E402
from fx.config import FxConfig  # noqa: E402

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
FX = f"{BASE_URL}/api/fx"
MOCK = "http://127.0.0.1:8012"
CFG = {"metaapi_token": "mocktoken", "mt_login": "12345678", "mt_password": "masterpass", "mt_server": "HFMarketsGlobal-Demo", "mt_platform": "mt5",
       "metaapi_region": "new-york", "metaapi_base_url": MOCK, "mt_symbol_suffix": "", "metaapi_plan": "g2-high"}
LOOP = asyncio.new_event_loop()


def run(coro):
    return LOOP.run_until_complete(coro)


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


def api_with(handler, **kw):
    api = MetaApi("tok", "new-york", "http://fake", **kw)
    api.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return api


# ---------- _call semantics (no network) ----------
class TestCallSemantics:
    def test_429_recommended_retry_time_then_ok(self):
        calls = []

        def h(req):
            calls.append(time.time())
            if len(calls) == 1:
                t = (datetime.now(timezone.utc) + timedelta(seconds=1.2)).isoformat().replace("+00:00", "Z")
                return httpx.Response(429, json={"error": "TooManyRequestsError", "metadata": {"recommendedRetryTime": t}})
            return httpx.Response(200, json=[{"id": "1"}])
        api = api_with(h)
        out = run(api.positions("acc"))
        run(api.aclose())
        assert out == [{"id": "1"}] and len(calls) == 2 and 0.5 <= calls[1] - calls[0] <= 3

    def test_429_on_trade_not_retried(self):
        calls = []

        def h(req):
            calls.append(1)
            return httpx.Response(429, headers={"Retry-After": "3"}, json={})
        api = api_with(h)
        with pytest.raises(MetaApiError) as ei:
            run(api.market_order("acc", "EURUSD", "long", 0.01, 1.0, 1.2, "AIT_deadbeef_o"))
        run(api.aclose())
        assert len(calls) == 1 and ei.value.kind == "transient" and ei.value.retry_after == 3.0

    def test_503_get_retried_trade_unknown(self):
        calls = []

        def h(req):
            calls.append(req.method)
            return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json={"balance": 1})
        api = api_with(h)
        assert run(api.account_info("acc"))["balance"] == 1 and len(calls) == 3
        calls.clear()
        api2 = api_with(lambda req: (calls.append(1), httpx.Response(503))[1])
        with pytest.raises(MetaApiError) as ei:
            run(api2.trade("acc", {"actionType": "ORDER_TYPE_BUY"}))
        run(api.aclose()), run(api2.aclose())
        assert len(calls) == 1 and ei.value.kind == "unknown"

    def test_network_error_trade_sent_once_unknown(self):
        calls = []

        def h(req):
            calls.append(1)
            raise httpx.ReadTimeout("timed out", request=req)
        api = api_with(h)
        with pytest.raises(MetaApiError) as ei:
            run(api.trade("acc", {"actionType": "ORDER_TYPE_BUY"}))
        run(api.aclose())
        assert len(calls) == 1 and ei.value.kind == "unknown" and "ReadTimeout" in ei.value.msg

    def test_404_not_synchronized_transient_401_clear(self):
        api = api_with(lambda req: httpx.Response(404, json={"error": "NotSynchronizedError", "message": "not synchronized"}))
        with pytest.raises(MetaApiError) as ei:
            run(api.positions("acc"))
        assert ei.value.kind == "transient"
        api2 = api_with(lambda req: httpx.Response(404, json={"error": "NotFoundError", "message": "Symbol not found"}))
        with pytest.raises(MetaApiError) as e2:
            run(api2.positions("acc"))
        assert e2.value.kind == "rejected"
        api3 = api_with(lambda req: httpx.Response(401, json={"message": "unauth"}))
        with pytest.raises(MetaApiError) as e3:
            run(api3.positions("acc"))
        assert e3.value.status == 401 and "token" in e3.value.msg
        for a in (api, api2, api3):
            run(a.aclose())

    def test_retry_after_clamped(self):
        class R:
            def __init__(self, body):
                self._b, self.headers = body, {}

            def json(self):
                return self._b
        past = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat().replace("+00:00", "Z")
        fut = (datetime.now(timezone.utc) + timedelta(seconds=600)).isoformat().replace("+00:00", "Z")
        assert _retry_after(R({"metadata": {"recommendedRetryTime": past}})) == 0.5
        assert _retry_after(R({"metadata": {"recommendedRetryTime": fut}})) == 30.0

    def test_config_default_alert_180(self):
        assert FxConfig().hfm_alert_after_sec == 180


# ---------- reconcile edge case against the mock ----------
@pytest.fixture(scope="module")
def acc():
    requests.post(f"{MOCK}/mock/reset", timeout=10)
    api = MetaApi("mocktoken", "new-york", MOCK)
    created = run(api.provision("12345678", "masterpass", "HFMarketsGlobal-Demo", "mt5"))
    run(api.aclose())
    return created["id"]


class TestReconcileEdge:
    def test_unknown_then_reconcile_reads_fail(self, acc):
        """Trade executed but HTTP timed out AND the reconcile GET /positions also fails: the error must NOT be presented as a
        'verified not executed' transient (the engine would log 'verificado: no quedó ninguna orden abierta' while a position exists)."""
        b = FxLiveBroker("mocktoken", acc, "new-york", MOCK)
        b.api.trade_timeout, b.api.read_timeout = 1.5, 0.5
        tick = requests.get(f"{MOCK}/users/current/accounts/x/symbols/EURUSD/current-tick", headers={"auth-token": "mocktoken"}, timeout=10).json()
        p = (tick["bid"] + tick["ask"]) / 2
        run(b.lot("EURUSD"))  # cache spec before faults
        n0 = len(mstate()["positions"])
        fault(trade_hang=3, times=1, positions_hang=3, positions_times=100)
        err = None
        try:
            run(b.open("EURUSD", "long", 0.05, p - 0.01, p + 0.02))
        except MetaApiError as e:
            err = e
        finally:
            clear_fault()
            run(b.aclose())
        n1 = len(mstate()["positions"])
        print("positions before/after:", n0, n1, "err:", err and (err.kind, err.attempts, err.msg))
        assert n1 == n0 + 1, "mock executed the order"
        assert err is not None
        assert err.kind == "unknown", f"order exists at broker but error kind={err.kind}: engine would claim 'no quedó ninguna orden abierta'"
        assert err.attempts == 1 and "no se pudo verificar en HFM" in err.msg
        assert re.fullmatch(r"AIT_[0-9a-f]{8}_o", getattr(err, "link_id", "")), "engine needs the clientId to adopt the position later"
        assert any(p.get("clientId") == err.link_id for p in mstate()["positions"])
        requests.post(f"{MOCK}/mock/reset", timeout=10)


# ---------- engine level ----------
@pytest.fixture(scope="module")
def s():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": "BlackCat2233@"}, timeout=30)
    assert r.status_code == 200, r.text
    sess = requests.Session()
    sess.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return sess


@pytest.fixture(scope="module")
def live(s):
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
    requests.post(f"{MOCK}/mock/trade-allowed", params={"allowed": "true"}, timeout=10)
    s.post(f"{FX}/bot/stop", timeout=30)
    s.post(f"{FX}/positions/close-all", timeout=60)
    s.post(f"{FX}/mode", json={"mode": "paper", "confirm": "", "reset_stats": True}, timeout=60)
    s.put(f"{FX}/config", json={"clear_hfm": True}, timeout=30)
    s.put(f"{FX}/config", json={"metaapi_base_url": "", "mt_symbol_suffix": ""}, timeout=30)
    requests.post(f"{MOCK}/mock/reset", timeout=10)


def inject(sym, side):
    out = subprocess.run(["python3", "scripts/fx_inject_signal.py", sym, side, "noai"], cwd="/app", capture_output=True, text=True, timeout=180)
    return out.stdout + out.stderr


def logs(s, since: str = ""):
    return [l["message"] for l in s.get(f"{FX}/dashboard", timeout=60).json()["logs"] if l["ts"] >= since]


class TestEngineExtra:
    def test_01_broker_rejection_immediate(self, s, live):
        fault(trade_code="TRADE_RETCODE_INVALID_STOPS", trade_code_num=10016, times=1)
        t0 = time.time()
        out = inject("EURUSD", "long")
        dt = time.time() - t0
        msgs = logs(s)
        assert "'executed': True" not in out, out[-600:]
        assert any("EURUSD: orden REAL rechazada" in m and "stops inválidos" in m for m in msgs), msgs[:8]
        assert not any("EURUSD: orden REAL no enviada" in m for m in msgs)
        assert mstate()["positions"] == [] and mstate()["faults"]["trade_times"] == 0
        sig = next(x for x in s.get(f"{FX}/signals", timeout=30).json() if x["symbol"] == "EURUSD")
        assert "rechazada" in (sig.get("note") or ""), sig
        print("rejection inject duration", round(dt, 1))

    def test_02_trade_disabled(self, s, live):
        requests.post(f"{MOCK}/mock/trade-allowed", params={"allowed": "false"}, timeout=10)
        try:
            out = inject("GBPUSD", "short")
        finally:
            requests.post(f"{MOCK}/mock/trade-allowed", params={"allowed": "true"}, timeout=10)
        msgs = logs(s)
        assert "'executed': True" not in out
        assert any("GBPUSD" in m and ("no permite operar" in m or "rechazada" in m) for m in msgs), msgs[:8]
        assert mstate()["positions"] == []

    def test_03_manual_close_transient_retried(self, s, live):
        out = inject("EURUSD", "long")
        assert "'executed': True" in out, out[-600:]
        pos = s.get(f"{FX}/positions", timeout=30).json()
        assert len(pos) == 1
        fault(trade_code="TRADE_RETCODE_DISCONNECTED_BEFORE_TRADE", trade_code_num=-10, times=1)
        r = s.post(f"{FX}/positions/{pos[0]['id']}/close", timeout=120)
        assert r.status_code == 200, r.text
        time.sleep(1)
        assert mstate()["positions"] == [] and s.get(f"{FX}/positions", timeout=30).json() == []
        assert any("EURUSD: cierre REAL ejecutado en el intento 2" in m for m in logs(s))

    def test_04_unknown_not_executed_engine_retries(self, s, live):
        fault(trade_code="TRADE_RETCODE_DISCONNECTED_DURING_TRADE", trade_code_num=-11, times=1)
        out = inject("USDJPY", "long")
        assert "'executed': True" in out, out[-600:]
        assert len(mstate()["positions"]) == 1, "no duplicate"
        assert any("USDJPY: orden REAL ejecutada en el intento 2" in m for m in logs(s))

    def test_05_close_all_persistent_failure_keeps_position(self, s, live):
        fault(trade_code="TRADE_RETCODE_CONNECTION", trade_code_num=10031, times=3)
        r = s.post(f"{FX}/positions/close-all", timeout=120)
        print("close-all with outage:", r.status_code, r.text[:200])
        assert len(mstate()["positions"]) == 1 and len(s.get(f"{FX}/positions", timeout=30).json()) == 1
        assert any("HFM/MetaApi no disponible tras varios intentos" in m for m in logs(s))
        clear_fault()
        r = s.post(f"{FX}/positions/close-all", timeout=120)
        assert r.status_code == 200 and mstate()["positions"] == []

    def test_06_unknown_unverifiable_then_adopted(self, s, live):
        """User's exact scenario: the order executes at HFM, the answer is lost AND MetaApi keeps failing while we verify → the signal is NOT
        reported as 'verificado: no quedó ninguna orden', a pending record is kept and the position is adopted on the next sync."""
        fault(trade_code="TRADE_RETCODE_DISCONNECTED_DURING_TRADE", trade_code_num=-11, trade_execute="true", times=1, positions_after_trade=40, positions_status=503)
        t0, since = time.time(), datetime.now(timezone.utc).isoformat()
        out = inject("EURUSD", "long")
        dt = time.time() - t0
        print("unknown+unverifiable inject duration", round(dt, 1))
        assert "'executed': True" not in out, out[-600:]
        msgs = logs(s, since)
        assert any("EURUSD: orden REAL con resultado desconocido" in m and "no se pudo verificar en HFM" in m and "adoptará por su identificador AIT_" in m for m in msgs), msgs[:8]
        assert not any("verificado: no quedó ninguna orden abierta" in m and "EURUSD" in m for m in msgs), "must not claim a false verification"
        assert not any("EURUSD: orden REAL rechazada" in m for m in msgs)
        assert len(mstate()["positions"]) == 1
        clear_fault()
        t0 = time.time()
        while time.time() - t0 < 40 and not s.get(f"{FX}/positions", timeout=30).json():
            time.sleep(2)
        pos = s.get(f"{FX}/positions", timeout=30).json()
        assert len(pos) == 1, "position with our clientId must be adopted"
        p, mp = pos[0], mstate()["positions"][0]
        assert p["live"] and p["order_id"] == mp["id"] and p["link_id"] == mp["clientId"] and p["strategy"] != "adoptada" and p["signal_id"]
        assert abs(p["sl"] - mp["stopLoss"]) < 1e-6 and abs(p["tp"] - mp["takeProfit"]) < 1e-6 and p["qty"] == mp["volume"]
        msgs = logs(s)
        assert any("ADOPTADA REAL LONG EURUSD" in m and "resultado desconocido confirmada en HFM" in m for m in msgs), msgs[:8]
        sig = next(x for x in s.get(f"{FX}/signals", timeout=30).json() if x["symbol"] == "EURUSD" and x["created_at"] >= since)
        assert sig.get("executed") is True and "confirmada por su identificador" in (sig.get("note") or ""), sig
        perf_db = _db()
        assert perf_db.fx_shadow_positions.count_documents({"signal_id": sig["id"]}) == 0, "shadow of the 'non-executed' signal removed"
        assert s.post(f"{FX}/positions/{p['id']}/close", timeout=120).status_code == 200
        time.sleep(1)
        assert mstate()["positions"] == [] and s.get(f"{FX}/positions", timeout=30).json() == []
        tr = [t for t in s.get(f"{FX}/trades", timeout=30).json() if t["symbol"] == "EURUSD" and t["closed_at"] >= since]
        assert tr and tr[0]["live"], "adopted position closes like any other live position"

    def test_07_orphan_with_our_client_id_adopted(self, s, live):
        """A broker position tagged with our clientId but without DB record (e.g. restored backup) is adopted with broker data."""
        tick = requests.get(f"{MOCK}/users/current/accounts/x/symbols/GBPUSD/current-tick", headers={"auth-token": "mocktoken"}, timeout=10).json()
        p0 = (tick["bid"] + tick["ask"]) / 2
        acc = mstate()["accounts"][0]["_id"]
        link, since = "AIT_deadbeef_o", datetime.now(timezone.utc).isoformat()
        r = requests.post(f"{MOCK}/users/current/accounts/{acc}/trade", headers={"auth-token": "mocktoken"},
                          json={"actionType": "ORDER_TYPE_SELL", "symbol": "GBPUSD", "volume": 0.02, "stopLoss": round(p0 + 0.01, 5), "takeProfit": round(p0 - 0.02, 5),
                                "clientId": link, "magic": 777001}, timeout=10)
        assert r.status_code == 200 and r.json()["stringCode"] in ("TRADE_RETCODE_DONE", "ERR_NO_ERROR"), r.text
        t0 = time.time()
        while time.time() - t0 < 40 and not s.get(f"{FX}/positions", timeout=30).json():
            time.sleep(2)
        pos = s.get(f"{FX}/positions", timeout=30).json()
        assert len(pos) == 1 and pos[0]["link_id"] == link and pos[0]["strategy"] == "adoptada" and pos[0]["side"] == "short" and pos[0]["qty"] == 0.02
        assert any("ADOPTADA REAL SHORT GBPUSD" in m and "sin registro local" in m for m in logs(s, since))
        assert not any("GBPUSD: posición externa detectada" in m for m in logs(s, since))
        assert s.post(f"{FX}/positions/close-all", timeout=120).status_code == 200
        time.sleep(1)
        assert mstate()["positions"] == []

    def test_08_pending_cleared_on_reset_and_migration(self, s, live):
        assert s.post(f"{FX}/account/reset", json={}, timeout=60).status_code in (200, 409)
        db = _db()
        assert db.fx_pending_orders.count_documents({}) == 0
        assert db.migrations.find_one({"_id": "2026-10-22-hfm-alert-180"})
        assert db.fx_config.find_one({"_id": "main"})["hfm_alert_after_sec"] != 60
