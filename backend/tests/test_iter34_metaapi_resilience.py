"""Iteration 34 – MetaApi resilience per metaapi.cloud docs: retries with backoff for idempotent calls (network/429/5xx), trade result
classification (rejected / transient / unknown), reconciliation by clientId after timeouts, clientId format `${strategy}_${pos}_${order}`,
MT4 success codes, engine behaviour (retry, no false 'rechazada' alerts). Uses the local MetaApi mock (:8012) with fault injection. Sequential."""
import os
import re
import time
import asyncio
import subprocess
import sys
import pytest
import requests

sys.path.insert(0, "/app/backend")
from fx.metaapi import MetaApi, MetaApiError, OK_CODES, UNKNOWN_CODES, TRANSIENT_CODES, _retry_after  # noqa: E402
from fx.live import FxLiveBroker, new_link, close_link  # noqa: E402

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
FX = f"{BASE_URL}/api/fx"
MOCK = "http://127.0.0.1:8012"
CFG = {"metaapi_token": "mocktoken", "mt_login": "12345678", "mt_password": "masterpass", "mt_server": "HFMarketsGlobal-Demo", "mt_platform": "mt5",
       "metaapi_region": "new-york", "metaapi_base_url": MOCK, "mt_symbol_suffix": "", "metaapi_plan": "g2-high"}


def _up():
    try:
        return requests.get(f"{MOCK}/mock/state", timeout=2).status_code == 200
    except Exception:
        return False


def mstate():
    return requests.get(f"{MOCK}/mock/state", timeout=10).json()


def fault(**kw):
    r = requests.post(f"{MOCK}/mock/fault", params=kw, timeout=10)
    assert r.status_code == 200, r.text


LOOP = asyncio.new_event_loop()


def run(coro):
    return LOOP.run_until_complete(coro)


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
def acc(mock):
    api = MetaApi("mocktoken", "new-york", MOCK)
    created = run(api.provision("12345678", "masterpass", "HFMarketsGlobal-Demo", "mt5"))
    run(api.aclose())
    return created["id"]


@pytest.fixture
def broker(acc):
    b = FxLiveBroker("mocktoken", acc, "new-york", MOCK)
    yield b
    run(b.aclose())


def sltp(side="long"):
    tick = requests.get(f"{MOCK}/users/current/accounts/x/symbols/EURUSD/current-tick", headers={"auth-token": "mocktoken"}, timeout=10).json()
    p = (tick["bid"] + tick["ask"]) / 2
    return (p - 0.01, p + 0.02) if side == "long" else (p + 0.01, p - 0.02)


class TestUnits:
    def test_codes_and_links(self):
        assert {"ERR_NO_ERROR", "TRADE_RETCODE_NO_CHANGES", "TRADE_RETCODE_DONE"} <= OK_CODES
        assert "TRADE_RETCODE_DISCONNECTED_DURING_TRADE" in UNKNOWN_CODES and "ERR_TRADE_TIMED_OUT" in UNKNOWN_CODES
        assert "TRADE_RETCODE_DISCONNECTED_BEFORE_TRADE" in TRANSIENT_CODES and "ERR_NOT_SYNCHRONIZED" in TRANSIENT_CODES
        assert not (UNKNOWN_CODES & TRANSIENT_CODES) and not (OK_CODES & (UNKNOWN_CODES | TRANSIENT_CODES))
        link = new_link()
        assert re.fullmatch(r"AIT_[0-9a-f]{8}_o", link) and len(link) <= 31
        assert close_link(link) == f"AIT_{link[4:12]}_c" and re.fullmatch(r"AIT_[0-9a-f]{8}_c", close_link("bot-deadbeef"))

    def test_retry_after_parsing(self):
        class R:
            def __init__(self, body, headers=None):
                self._b, self.headers = body, headers or {}

            def json(self):
                if self._b is None:
                    raise ValueError
                return self._b
        from datetime import datetime, timedelta, timezone
        t = (datetime.now(timezone.utc) + timedelta(seconds=7)).isoformat().replace("+00:00", "Z")
        assert 6 <= _retry_after(R({"metadata": {"recommendedRetryTime": t}})) <= 7.5
        assert _retry_after(R({}, {"Retry-After": "5"})) == 5.0
        assert _retry_after(R(None)) == 2.0


class TestClientResilience:
    def test_get_retries_after_timeout(self, acc):
        fault(positions_hang=3, positions_times=1)
        api = MetaApi("mocktoken", "new-york", MOCK, read_timeout=1.0)
        t0 = time.time()
        out = run(api.positions(acc))
        run(api.aclose())
        assert isinstance(out, list) and 1.5 < time.time() - t0 < 12, "first call timed out, retried after backoff"
        fault(positions_hang=25, positions_times=4)
        api = MetaApi("mocktoken", "new-york", MOCK, read_timeout=0.5)
        with pytest.raises(MetaApiError) as ei:
            run(api.positions(acc))
        run(api.aclose())
        assert ei.value.kind == "transient" and ei.value.attempts == 4 and "no responde" in ei.value.msg
        requests.post(f"{MOCK}/mock/fault", params={"times": 0}, timeout=10)
        time.sleep(1)

    def test_trade_http_timeout_is_unknown_and_reconciled(self, broker):
        n0 = len(mstate()["positions"])
        broker.api.trade_timeout = 1.5
        fault(trade_hang=3, times=1)
        sl, tp = sltp()
        r = run(broker.open("EURUSD", "long", 0.05, sl, tp))
        assert r["note"] and "confirmada en HFM" in r["note"] and r["attempts"] == 1 and r["filled"] and r["position_id"]
        st = mstate()
        assert len(st["positions"]) == n0 + 1 and st["positions"][-1]["clientId"] == r["link_id"], "no duplicate order after timeout"
        time.sleep(2)

    def test_transient_code_retried_once(self, broker):
        n0 = len(mstate()["positions"])
        fault(trade_code="TRADE_RETCODE_DISCONNECTED_BEFORE_TRADE", trade_code_num=-10, times=1)
        sl, tp = sltp()
        t0 = time.time()
        r = run(broker.open("EURUSD", "long", 0.05, sl, tp))
        assert r["attempts"] == 2 and r["note"] is None and r["filled"] and 3.5 <= time.time() - t0 < 20
        assert len(mstate()["positions"]) == n0 + 1

    def test_unknown_code_executed_is_reconciled(self, broker):
        n0 = len(mstate()["positions"])
        fault(trade_code="ERR_TRADE_TIMED_OUT", trade_code_num=-7, trade_execute="true", times=1)
        sl, tp = sltp()
        r = run(broker.open("EURUSD", "long", 0.05, sl, tp))
        assert r["attempts"] == 1 and "confirmada en HFM" in r["note"] and r["filled"]
        assert len(mstate()["positions"]) == n0 + 1

    def test_unknown_code_not_executed_then_retry(self, broker):
        n0 = len(mstate()["positions"])
        fault(trade_code="TRADE_RETCODE_DISCONNECTED_DURING_TRADE", trade_code_num=-11, times=1)
        sl, tp = sltp()
        r = run(broker.open("EURUSD", "long", 0.05, sl, tp))
        assert r["attempts"] == 2 and r["note"] is None and r["filled"], "verified not executed → safe retry"
        assert len(mstate()["positions"]) == n0 + 1

    def test_rejected_is_immediate(self, broker):
        n0 = len(mstate()["positions"])
        fault(trade_code="TRADE_RETCODE_INVALID_STOPS", trade_code_num=10016, times=1)
        sl, tp = sltp()
        t0 = time.time()
        with pytest.raises(MetaApiError) as ei:
            run(broker.open("EURUSD", "long", 0.05, sl, tp))
        assert ei.value.kind == "rejected" and ei.value.attempts == 1 and "stops inválidos" in ei.value.msg and time.time() - t0 < 3
        assert len(mstate()["positions"]) == n0

    def test_persistent_transient_gives_up_without_order(self, broker):
        n0 = len(mstate()["positions"])
        fault(trade_code="TRADE_RETCODE_CONNECTION", trade_code_num=10031, times=3)
        sl, tp = sltp()
        with pytest.raises(MetaApiError) as ei:
            run(broker.open("EURUSD", "long", 0.05, sl, tp))
        assert ei.value.kind == "transient" and ei.value.attempts == 3 and "sin conexión con el servidor de HFM" in ei.value.msg
        assert len(mstate()["positions"]) == n0

    def test_close_and_set_stop_unknown_reconciled(self, broker):
        sl, tp = sltp()
        r = run(broker.open("EURUSD", "long", 0.05, sl, tp))
        pid = r["position_id"]
        fault(trade_code="ERR_TRADE_TIMED_OUT", trade_code_num=-7, trade_execute="true", times=1)
        run(broker.set_stop("EURUSD", pid, sl + 0.001, tp))
        assert abs(float(next(p for p in mstate()["positions"] if p["id"] == pid)["stopLoss"]) - round(sl + 0.001, 5)) < 1e-9
        fault(trade_code="TRADE_RETCODE_DISCONNECTED_DURING_TRADE", trade_code_num=-11, trade_execute="true", times=1)
        c = run(broker.close(pid, r["link_id"]))
        assert c["note"] and "confirmada en HFM" in c["note"]
        assert all(p["id"] != pid for p in mstate()["positions"])
        orders = mstate()["orders"]
        assert any(o["clientId"] == r["link_id"] for o in orders)

    def test_mt4_success_code_accepted(self, acc):
        api = MetaApi("mocktoken", "new-york", MOCK)
        fault(trade_code="ERR_NO_ERROR", trade_code_num=0, trade_execute="true", times=1)
        sl, tp = sltp()
        res = run(api.market_order(acc, "EURUSD", "long", 0.05, sl, tp, new_link()))
        run(api.aclose())
        assert res["stringCode"] == "ERR_NO_ERROR"


@pytest.fixture(scope="module")
def s():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": "BlackCat2233@"}, timeout=30)
    assert r.status_code == 200, r.text
    sess = requests.Session()
    sess.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return sess


@pytest.fixture(scope="module")
def live(s, mock):
    requests.post(f"{MOCK}/mock/reset", timeout=10)
    s.post(f"{FX}/bot/stop", timeout=30)
    s.post(f"{FX}/positions/close-all", timeout=60)
    assert s.put(f"{FX}/config", json=CFG, timeout=30).status_code == 200
    assert s.post(f"{FX}/hfm/link", timeout=60).status_code == 200
    assert s.post(f"{FX}/hfm/test", json={}, timeout=60).json()["info"]
    r = s.post(f"{FX}/mode", json={"mode": "live", "confirm": "REAL", "reset_stats": True}, timeout=60)
    assert r.status_code == 200, r.text
    yield
    s.post(f"{FX}/bot/stop", timeout=30)
    s.post(f"{FX}/positions/close-all", timeout=60)
    s.post(f"{FX}/mode", json={"mode": "paper", "confirm": "", "reset_stats": True}, timeout=60)
    s.put(f"{FX}/config", json={"clear_hfm": True}, timeout=30)
    s.put(f"{FX}/config", json={"metaapi_base_url": "", "mt_symbol_suffix": ""}, timeout=30)
    requests.post(f"{MOCK}/mock/reset", timeout=10)


def inject(sym, side):
    out = subprocess.run(["python3", "scripts/fx_inject_signal.py", sym, side, "noai"], cwd="/app", capture_output=True, text=True, timeout=180)
    return out.stdout + out.stderr


def logs(s):
    return [l["message"] for l in s.get(f"{FX}/dashboard", timeout=60).json()["logs"]]


class TestEngine:
    def test_01_transient_then_success(self, s, live):
        fault(trade_code="TRADE_RETCODE_DISCONNECTED_BEFORE_TRADE", trade_code_num=-10, times=1)
        out = inject("EURUSD", "long")
        assert "'executed': True" in out, out[-800:]
        msgs = logs(s)
        assert any("EURUSD: orden REAL ejecutada en el intento 2" in m for m in msgs), msgs[:10]
        assert not any("EURUSD: orden REAL rechazada" in m for m in msgs)
        assert len(mstate()["positions"]) == 1

    def test_02_timeout_executed_reconciled(self, s, live):
        fault(trade_code="ERR_TRADE_TIMED_OUT", trade_code_num=-7, trade_execute="true", times=1)
        out = inject("USDJPY", "short")
        assert "'executed': True" in out, out[-800:]
        msgs = logs(s)
        assert any("USDJPY: orden REAL confirmada en HFM" in m and "localizada por clientId" in m for m in msgs), msgs[:10]
        assert len(mstate()["positions"]) == 2
        pos = s.get(f"{FX}/positions", timeout=30).json()
        assert len(pos) == 2 and all(p["live"] and re.fullmatch(r"AIT_[0-9a-f]{8}_o", p["link_id"]) for p in pos)

    def test_03_persistent_outage_no_false_rejection(self, s, live):
        fault(trade_code="TRADE_RETCODE_CONNECTION", trade_code_num=10031, times=3)
        out = inject("GBPUSD", "long")
        assert "'executed': False" in out or "No ejecutada" in out, out[-800:]
        msgs = logs(s)
        assert any("GBPUSD: orden REAL no enviada" in m and "HFM/MetaApi no disponible tras 3 intento" in m for m in msgs), msgs[:10]
        assert not any("GBPUSD: orden REAL rechazada" in m for m in msgs), "an outage must not be reported as a broker rejection"
        assert len(mstate()["positions"]) == 2
        sig = next(x for x in s.get(f"{FX}/signals", timeout=30).json() if x["symbol"] == "GBPUSD")
        assert "HFM/MetaApi no disponible" in (sig.get("note") or "")

    def test_04_close_all_with_unknown_result(self, s, live):
        fault(trade_code="TRADE_RETCODE_DISCONNECTED_DURING_TRADE", trade_code_num=-11, trade_execute="true", times=1)
        r = s.post(f"{FX}/positions/close-all", timeout=120)
        assert r.status_code == 200, r.text
        time.sleep(1)
        assert mstate()["positions"] == [] and s.get(f"{FX}/positions", timeout=30).json() == []
        assert any("cierre REAL confirmada en HFM" in m for m in logs(s))
