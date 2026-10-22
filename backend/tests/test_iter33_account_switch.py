"""Iteration 33 – HFM account switch without losing history (/account/rebase), DEMO/REAL account kind, trade period tags.
Uses the local MetaApi mock (:8012). Sequential."""
import os
import time
import subprocess
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
FX = f"{BASE_URL}/api/fx"
MOCK = "http://127.0.0.1:8012"
DEMO = {"metaapi_token": "mocktoken", "mt_login": "12345678", "mt_password": "masterpass", "mt_server": "HFMarketsGlobal-Demo", "mt_platform": "mt5",
        "metaapi_region": "new-york", "metaapi_base_url": MOCK, "mt_symbol_suffix": "", "metaapi_plan": "g2-high"}
LIVE = {**DEMO, "mt_login": "87654321", "mt_server": "HFMarketsGlobal-Live2"}


def _up():
    try:
        return requests.get(f"{MOCK}/mock/state", timeout=2).status_code == 200
    except Exception:
        return False


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
    s.post(f"{FX}/positions/close-all", timeout=60)
    yield
    s.post(f"{FX}/bot/stop", timeout=30)
    s.post(f"{FX}/mode", json={"mode": "paper", "confirm": "", "reset_stats": True}, timeout=60)
    s.put(f"{FX}/config", json={"clear_hfm": True}, timeout=30)
    s.put(f"{FX}/config", json={"metaapi_base_url": "", "mt_symbol_suffix": ""}, timeout=30)
    requests.post(f"{MOCK}/mock/reset", timeout=10)


def link_and_test(s, cfg):
    assert s.put(f"{FX}/config", json=cfg, timeout=30).status_code == 200
    assert s.post(f"{FX}/hfm/link", timeout=60).status_code == 200
    t = s.post(f"{FX}/hfm/test", json={}, timeout=60).json()
    assert t["info"], t
    return t


class TestAccountSwitch:
    def test_01_rebase_rejected_in_paper(self, s, saved):
        link_and_test(s, DEMO)
        r = s.post(f"{FX}/account/rebase", timeout=30)
        assert r.status_code == 409 and "modo REAL" in r.json()["detail"]
        st = s.get(f"{FX}/dashboard", timeout=30).json()["status"]
        assert st["account_kind"] is None

    def test_02_go_live_demo_kind(self, s, saved):
        r = s.post(f"{FX}/mode", json={"mode": "live", "confirm": "REAL", "reset_stats": True}, timeout=60)
        assert r.status_code == 200, r.text
        assert r.json()["account_kind"] == "demo"
        d = s.get(f"{FX}/dashboard", timeout=30).json()
        assert d["status"]["account_kind"] == "demo" and d["status"]["mode"] == "REAL"
        a = d["account"]
        assert a["account_ref"] == "12345678@HFMarketsGlobal-Demo" and a["account_changed"] is False and a["initial_balance"] == 1000.0
        assert any("cuenta DEMO" in l["message"] for l in d["logs"][:5])

    def test_03_seed_history_and_switch(self, s, saved):
        """Fake a demo-period history (2 closed trades, equity snapshots with a demo deposit) in the fx_ collections, then link a different account."""
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        from dotenv import load_dotenv
        load_dotenv("/app/backend/.env")

        async def seed():
            db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
            await db.fx_trades.insert_many([
                {"symbol": "EURUSD", "side": "long", "strategy": "trend", "entry_price": 1.1, "exit_price": 1.102, "qty": 0.1, "leverage": 100, "margin": 11.0,
                 "pnl": 20.0, "pnl_pct": 1.8, "fees": 0.3, "reason": "TP", "opened_at": "2026-06-01T10:00:00+00:00", "closed_at": "2026-06-01T12:00:00+00:00", "live": True},
                {"symbol": "XAUUSD", "side": "short", "strategy": "trend", "entry_price": 2300.0, "exit_price": 2305.0, "qty": 0.01, "leverage": 100, "margin": 23.0,
                 "pnl": -5.0, "pnl_pct": -0.2, "fees": 0.1, "reason": "SL", "opened_at": "2026-06-02T10:00:00+00:00", "closed_at": "2026-06-02T11:00:00+00:00", "live": True}])
            await db.fx_equity.delete_many({})
            await db.fx_equity.insert_many([{"ts": "2026-06-01T00:00:00+00:00", "equity": 1000.0, "balance": 1000.0, "net_deposits": 0.0},
                                            {"ts": "2026-06-02T00:00:00+00:00", "equity": 1020.0, "balance": 1020.0, "net_deposits": 0.0},
                                            {"ts": "2026-06-03T00:00:00+00:00", "equity": 1215.0, "balance": 1215.0, "net_deposits": 200.0}])
            await db.fx_account.update_one({"_id": "main"}, {"$set": {"net_deposits": 200.0, "max_drawdown": 3.5, "peak_equity": 1020.0}})
        asyncio.run(seed())
        before = s.get(f"{FX}/account", timeout=30).json()
        assert before["total_trades"] == 2 and before["net_deposits"] == 200.0

        link_and_test(s, LIVE)
        acc = s.get(f"{FX}/account", timeout=30).json()
        assert acc["account_changed"] is True and acc["account_ref"] == "12345678@HFMarketsGlobal-Demo" and acc["account_kind"] == "live"
        assert s.get(f"{FX}/dashboard", timeout=30).json()["status"]["account_kind"] == "live"
        requests.post(f"{MOCK}/mock/deposit", params={"amount": -700, "comment": "other account"}, timeout=10)  # new account equity 1000 → 300

    def test_05_rebase_guards(self, s, saved):
        assert s.post(f"{FX}/bot/start", timeout=60).status_code == 200
        try:
            r = s.post(f"{FX}/account/rebase", timeout=30)
            assert r.status_code == 409 and "Detén el bot" in r.json()["detail"]
        finally:
            s.post(f"{FX}/bot/stop", timeout=30)

    def test_06_rebase(self, s, saved):
        r = s.post(f"{FX}/account/rebase", timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["tagged"] == 2 and d["account_ref"] == "87654321@HFMarketsGlobal-Live2" and d["previous_account_ref"] == "12345678@HFMarketsGlobal-Demo"
        assert abs(d["equity"] - 300.0) < 0.01
        a = d["account"]
        assert a["initial_balance"] == 300.0 and a["net_deposits"] == 0.0 and a["account_changed"] is False and a["account_ref"] == d["account_ref"]
        assert a["total_trades"] == 2 and a["realized_pnl"] == 15.0 and a["max_drawdown"] == 3.5, "history and counters kept"
        assert abs(a["total_pnl"]) < 0.01 and a["capital"] == 300.0
        trades = s.get(f"{FX}/trades", timeout=30).json()
        assert all(t["period"] == "Periodo anterior · 12345678@HFMarketsGlobal-Demo" for t in trades) and len(trades) == 2
        curve = s.get(f"{FX}/dashboard", timeout=30).json()["equity"]
        # old points shifted so the curve is continuous: last old adjusted (1215-200=1015) → 300 ⇒ shift -715
        olds = [p for p in curve if p["ts"].startswith("2026-06-0")]
        assert [p["equity"] for p in olds] == [285.0, 305.0, 500.0] and all(p["net_deposits"] == 0 for p in curve)
        assert abs(curve[-1]["equity"] - 300.0) < 0.01
        logs = s.get(f"{FX}/dashboard", timeout=30).json()["logs"]
        assert any("Cuenta HFM cambiada a 87654321@HFMarketsGlobal-Live2" in l["message"] and "2 operaciones" in l["message"] for l in logs)

    def test_07_no_phantom_cashflow_after_rebase(self, s, saved):
        """The -700 balance deal of the new account predates the switch: it must not be registered as a withdrawal when the bot runs."""
        assert s.post(f"{FX}/bot/start", timeout=60).status_code == 200
        time.sleep(4)
        s.post(f"{FX}/bot/stop", timeout=30)
        a = s.get(f"{FX}/account", timeout=30).json()
        assert a["net_deposits"] == 0.0 and a["initial_balance"] == 300.0
        flows = s.get(f"{FX}/account/cashflows", timeout=30).json()["items"]
        assert not any(abs(float(f["amount"]) + 700) < 0.01 for f in flows)
