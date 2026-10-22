"""Iteration 28 – deposits & withdrawals without distorting the statistics: manual paper flows (both bots), auto-detection in REAL mode
(Bybit transaction log via mock :8011, MetaApi balance deals via mock :8012) and their neutralisation in daily PnL / daily loss limit / return /
drawdown / weekly summary. Run with `-n 0` (the FX REAL test switches the HotForex bot to the MetaApi mock and back to paper)."""
import os
import sys
import time
import asyncio
import subprocess
import pytest
import requests

sys.path.insert(0, "/app/backend")
from tests.test_iter21_hfm_alert_cron_ai import CFG, MOCK, wait_for, _up  # noqa: E402

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
FX = f"{BASE_URL}/api/fx"
BYBIT_MOCK = "http://127.0.0.1:8011"


def _mongo():
    from pymongo import MongoClient
    env = dict(l.strip().split("=", 1) for l in open("/app/backend/.env") if "=" in l and not l.startswith("#"))
    return MongoClient(env["MONGO_URL"].strip('"'))[env["DB_NAME"].strip('"')]


@pytest.fixture(scope="module")
def s():
    r = requests.post(f"{API}/auth/login", json={"password": "BlackCat2233@"}, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"login failed {r.status_code}")
    sess = requests.Session()
    sess.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return sess


def _acc(s, base):
    return s.get(f"{base}/dashboard", timeout=60).json()["account"]


class TestUnit:
    def test_fields_and_jump(self):
        import cashflow
        acc = {"initial_balance": 500.0, "net_deposits": 1000.0, "peak_equity": 520.0}
        f = cashflow.fields(acc, 1550.0)
        assert f == {"net_deposits": 1000.0, "capital": 1500.0, "total_pnl": 50.0, "total_return_pct": 3.33, "peak_equity": 1520.0}
        assert cashflow.fields({"initial_balance": 500.0, "peak_equity": 500.0}, 450.0)["total_return_pct"] == -10.0
        assert cashflow.jumped(None, 1000) is False and cashflow.jumped(1000, 1004) is False and cashflow.jumped(1000, 1030) is True
        assert cashflow.jumped(10000, 10040) is False and cashflow.jumped(10000, 10060) is True

    def test_manual_rejected_in_live(self):
        import cashflow

        class E:
            live = True
        with pytest.raises(ValueError, match="modo REAL"):
            asyncio.run(cashflow.manual(E(), 100))

    def test_bybit_cash_flows_parsing(self):
        """LiveBroker.cash_flows against the signed Bybit mock: transfers in/out become signed flows, trades are ignored."""
        def up():
            try:
                return requests.get(f"{BYBIT_MOCK}/mock/state", timeout=2).status_code == 200
            except Exception:
                return False
        if not up():
            subprocess.Popen(["python3", "scripts/bybit_mock.py"], cwd="/app", stdout=open("/tmp/bybit_mock.log", "a"), stderr=subprocess.STDOUT)
            assert wait_for(up, 20, 1), "bybit mock did not start"
        requests.post(f"{BYBIT_MOCK}/mock/reset", timeout=10)
        since = int(time.time() * 1000) - 1000
        requests.post(f"{BYBIT_MOCK}/mock/deposit", params={"amount": 250}, timeout=10)
        requests.post(f"{BYBIT_MOCK}/mock/deposit", params={"amount": -40}, timeout=10)
        from bybit import BybitClient
        from live import LiveBroker

        async def run():
            broker = LiveBroker(BybitClient("mockkey", "mocksecret", "testnet", BYBIT_MOCK))
            try:
                return await broker.cash_flows(since)
            finally:
                await broker.aclose()
        flows = asyncio.run(run())
        assert [f["amount"] for f in flows] == [250.0, -40.0]
        assert flows[0]["id"].startswith("bybit:") and flows[0]["note"] == "transferencia entrante" and flows[1]["note"] == "transferencia saliente"
        assert flows[0]["ts"] < flows[1]["ts"] or flows[0]["ts"] == flows[1]["ts"]
        assert flows[0]["id"] != flows[1]["id"]


class TestPaperFlows:
    def test_fx_paper_deposit_and_withdrawal(self, s):
        from datetime import datetime, timezone
        db = _mongo()
        start = datetime.now(timezone.utc).isoformat()
        before = _acc(s, FX)
        acc0 = db.fx_account.find_one({"_id": "main"})
        r = s.post(f"{FX}/account/cashflow", json={"amount": 1000, "note": "aporte de prueba"}, timeout=30)
        assert r.status_code == 200, r.text
        out = r.json()
        a = out["account"]
        assert out["flow"]["kind"] == "deposit" and out["flow"]["source"] == "paper" and out["flow"]["amount"] == 1000 and out["flow"]["note"] == "aporte de prueba"
        assert a["net_deposits"] == before["net_deposits"] + 1000 and a["capital"] == before["capital"] + 1000
        assert abs(a["balance"] - (before["balance"] + 1000)) < 0.01 and abs(a["equity"] - (before["equity"] + 1000)) < 0.01
        assert abs(a["daily_pnl"] - before["daily_pnl"]) < 0.01, "a deposit must not count as daily PnL"
        assert abs(a["total_pnl"] - before["total_pnl"]) < 0.01 and a["total_return_pct"] <= before["total_return_pct"] + 0.01
        assert abs(a["peak_equity"] - (before["peak_equity"] + 1000)) < 0.01 and a["max_drawdown"] == before["max_drawdown"]
        acc1 = db.fx_account.find_one({"_id": "main"})
        assert abs(acc1["day_start_equity"] - acc0["day_start_equity"] - 1000) < 1e-6 and acc1["peak_equity"] == acc0["peak_equity"]
        time.sleep(6)  # a monitor tick must not create drawdown or daily loss out of the deposit
        a2 = _acc(s, FX)
        assert a2["max_drawdown"] == before["max_drawdown"] and abs(a2["daily_pnl"] - before["daily_pnl"]) < 0.01
        hist = s.get(f"{FX}/account/cashflows", timeout=30).json()
        assert hist["currency"] == "USD" and hist["net_deposits"] == a["net_deposits"] and hist["items"][0]["amount"] == 1000 and hist["items"][0]["id"] == out["flow"]["id"]
        # validations
        assert s.post(f"{FX}/account/cashflow", json={"amount": 0}, timeout=30).status_code == 422
        r = s.post(f"{FX}/account/cashflow", json={"amount": -(a["available"] + 100)}, timeout=30)
        assert r.status_code == 422 and "supera el disponible" in r.json()["detail"]
        # withdrawal back to the starting point
        r = s.post(f"{FX}/account/cashflow", json={"amount": -1000}, timeout=30)
        assert r.status_code == 200 and r.json()["flow"]["kind"] == "withdrawal"
        a3 = r.json()["account"]
        assert a3["net_deposits"] == before["net_deposits"] and abs(a3["balance"] - before["balance"]) < 0.01 and abs(a3["daily_pnl"] - before["daily_pnl"]) < 0.01
        assert a3["max_drawdown"] == before["max_drawdown"]
        logs = [l["message"] for l in s.get(f"{FX}/dashboard", timeout=60).json()["logs"][:10]]
        assert any("💰 Depósito en la cuenta paper +1,000.00 USD" in m and "aporte de prueba" in m for m in logs)
        assert any("💰 Retiro en la cuenta paper -1,000.00 USD" in m for m in logs)
        db.fx_cash_flows.delete_many({"source": "paper", "ts": {"$gte": start}})

    def test_crypto_paper_endpoint_and_isolation(self, s):
        db = _mongo()
        before = _acc(s, API)
        n_fx = db.fx_cash_flows.count_documents({})
        r = s.post(f"{API}/account/cashflow", json={"amount": 50, "note": "iter28"}, timeout=30)
        assert r.status_code == 200, r.text
        a = r.json()["account"]
        assert a["net_deposits"] == before["net_deposits"] + 50 and abs(a["daily_pnl"] - before["daily_pnl"]) < 0.01 and abs(a["total_pnl"] - before["total_pnl"]) < 0.01
        assert db.fx_cash_flows.count_documents({}) == n_fx and db.cash_flows.count_documents({"note": "iter28"}) == 1
        hist = s.get(f"{API}/account/cashflows", timeout=30).json()
        assert hist["currency"] == "USDT" and hist["items"][0]["note"] == "iter28"
        r = s.post(f"{API}/account/cashflow", json={"amount": -50, "note": "iter28"}, timeout=30)
        assert r.status_code == 200 and r.json()["account"]["net_deposits"] == before["net_deposits"]
        db.cash_flows.delete_many({"note": "iter28"})
        w = s.get(f"{API}/weekly-summary", timeout=60).json()
        assert "week_flows" in w


@pytest.fixture(scope="module")
def mock():
    if not _up():
        subprocess.Popen(["python3", "scripts/metaapi_mock.py"], cwd="/app", stdout=open("/tmp/metaapi_mock.log", "a"), stderr=subprocess.STDOUT)
        assert wait_for(_up, 20, 1), "mock did not start"
    requests.post(f"{MOCK}/mock/reset", timeout=10)
    requests.post(f"{MOCK}/mock/connection", params={"connected": "true"}, timeout=10)
    yield MOCK


@pytest.fixture(scope="module")
def live(s, mock):
    s.post(f"{FX}/bot/stop", timeout=30)
    assert s.put(f"{FX}/config", json=CFG, timeout=30).status_code == 200
    assert s.post(f"{FX}/hfm/link", timeout=60).status_code == 200
    assert s.post(f"{FX}/hfm/test", json={}, timeout=60).status_code == 200
    r = s.post(f"{FX}/mode", json={"mode": "live", "confirm": "REAL", "reset_stats": True}, timeout=60)
    assert r.status_code == 200, r.text
    yield s
    s.post(f"{FX}/bot/stop", timeout=30)
    s.post(f"{FX}/mode", json={"mode": "paper", "confirm": "", "reset_stats": True}, timeout=60)
    s.put(f"{FX}/config", json={"clear_hfm": True}, timeout=30)
    s.put(f"{FX}/config", json={"metaapi_base_url": "", "mt_symbol_suffix": ""}, timeout=30)


class TestRealDetection:
    def test_hfm_deposit_and_withdrawal_detected(self, live):
        s = live
        a0 = wait_for(lambda: (lambda a: a if a["mode"] == "REAL" and a["exchange_synced"] else None)(_acc(s, FX)), 30, 2)
        assert a0 and a0["net_deposits"] == 0 and a0["equity"] == a0["initial_balance"]
        assert s.post(f"{FX}/account/cashflow", json={"amount": 100}, timeout=30).status_code == 409  # manual flows only in paper
        requests.post(f"{MOCK}/mock/deposit", params={"amount": 2500, "comment": "Wire deposit"}, timeout=10)
        a1 = wait_for(lambda: (lambda a: a if a["net_deposits"] == 2500 and abs(a["equity"] - (a0["equity"] + 2500)) < 0.01 else None)(_acc(s, FX)), 40, 2)
        assert a1, "deposit not detected"
        assert a1["capital"] == a0["initial_balance"] + 2500
        assert abs(a1["daily_pnl"]) < 0.01 and abs(a1["total_pnl"]) < 0.01 and a1["total_return_pct"] == 0 and a1["max_drawdown"] == 0
        assert a1["peak_equity"] == a1["equity"] and a1["daily_paused"] is False
        hist = s.get(f"{FX}/account/cashflows", timeout=30).json()
        assert hist["items"][0]["source"] == "hfm" and hist["items"][0]["note"] == "Wire deposit" and hist["items"][0]["id"].startswith("hfm:")
        # a big withdrawal must not trigger the daily loss limit nor a drawdown
        requests.post(f"{MOCK}/mock/deposit", params={"amount": -3000}, timeout=10)
        a2 = wait_for(lambda: (lambda a: a if a["net_deposits"] == -500 and abs(a["equity"] - (a0["equity"] - 500)) < 0.01 else None)(_acc(s, FX)), 40, 2)
        assert a2, "withdrawal not detected"
        time.sleep(6)
        a2 = _acc(s, FX)
        assert abs(a2["daily_pnl"]) < 0.01 and a2["daily_paused"] is False and a2["max_drawdown"] == 0 and abs(a2["total_pnl"]) < 0.01
        assert a2["capital"] == a0["initial_balance"] - 500 and a2["total_return_pct"] == 0
        logs = [l["message"] for l in s.get(f"{FX}/dashboard", timeout=60).json()["logs"][:15]]
        assert any("💰 Depósito detectado en HFM +2,500.00 USD" in m for m in logs) and any("💰 Retiro detectado en HFM -3,000.00 USD" in m for m in logs)
        # idempotent: a second poll does not duplicate the flows
        time.sleep(3)
        assert len(s.get(f"{FX}/account/cashflows", timeout=30).json()["items"]) == 2
        snap = _mongo().fx_equity.find_one({}, sort=[("ts", -1)])
        assert snap is None or "net_deposits" in snap  # snapshots are taken every 60 s (collection was reset when going live)

    def test_back_to_paper_resets_flows(self, live):
        s = live
        assert s.post(f"{FX}/mode", json={"mode": "paper", "confirm": "", "reset_stats": True}, timeout=60).status_code == 200
        a = _acc(s, FX)
        assert a["mode"] == "PAPER" and a["net_deposits"] == 0 and a["capital"] == a["initial_balance"] == 500
        assert s.get(f"{FX}/account/cashflows", timeout=30).json()["items"] == []
