"""Iteration 18 – HotForex REAL mode via MetaApi (local mock on :8012): link/test/symbols/redeploy, mode checklist & switch,
live orders with SL/TP, broker sync (trailing → broker, external SL close), manual close, close-all, guards. Sequential (single class)."""
import os
import time
import subprocess
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
FX = f"{BASE_URL}/api/fx"
MOCK = "http://127.0.0.1:8012"
CFG = {"metaapi_token": "mocktoken", "mt_login": "12345678", "mt_password": "masterpass", "mt_server": "HFMarketsGlobal-Demo", "mt_platform": "mt5",
       "metaapi_region": "new-york", "metaapi_base_url": MOCK, "mt_symbol_suffix": ""}


def mock_state():
    return requests.get(f"{MOCK}/mock/state", timeout=10).json()


def inject(sym, side):
    out = subprocess.run(["python3", "scripts/fx_inject_signal.py", sym, side, "noai"], cwd="/app", capture_output=True, text=True, timeout=120)
    return out.stdout + out.stderr


def wait_for(fn, timeout=40, step=2):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return None


@pytest.fixture(scope="module")
def s():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": "BlackCat2233@"}, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"login failed {r.status_code}")
    sess = requests.Session()
    sess.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return sess


@pytest.fixture(scope="module")
def mock():
    try:
        requests.get(f"{MOCK}/mock/state", timeout=3)
    except Exception:
        subprocess.Popen(["python3", "scripts/metaapi_mock.py"], cwd="/app", stdout=open("/tmp/metaapi_mock.log", "a"), stderr=subprocess.STDOUT)
        assert wait_for(lambda: _up(), 20, 1), "mock did not start"
    requests.post(f"{MOCK}/mock/reset", timeout=10)
    return MOCK


def _up():
    try:
        return requests.get(f"{MOCK}/mock/state", timeout=2).status_code == 200
    except Exception:
        return False


@pytest.fixture(scope="module")
def saved(s, mock):
    """Stop bot, clear sessions filter, point HFM config to the mock; restore paper + clear at the end."""
    s.post(f"{FX}/bot/stop", timeout=30)
    orig = s.get(f"{FX}/settings", timeout=30).json()
    s.put(f"{FX}/settings", json={"sessions_allowed": []}, timeout=30)
    market = s.get(f"{FX}/market", timeout=30).json()
    yield {"settings": orig, "market_open": market["open"]}
    s.post(f"{FX}/bot/stop", timeout=30)
    s.post(f"{FX}/positions/close-all", timeout=60)
    s.post(f"{FX}/mode", json={"mode": "paper", "confirm": "", "reset_stats": True}, timeout=60)
    s.put(f"{FX}/config", json={"clear_hfm": True}, timeout=30)
    s.put(f"{FX}/config", json={"metaapi_base_url": "", "mt_symbol_suffix": ""}, timeout=30)
    s.put(f"{FX}/settings", json={"sessions_allowed": orig.get("sessions_allowed", [])}, timeout=30)


class TestFxLive:
    def test_01_unit_live_helpers(self):
        import sys
        sys.path.insert(0, "/app/backend")
        from fx.live import q_floor, q_step, FxLiveBroker
        from fx.risk import position_size, round_lots
        from fx.metaapi import MetaApi, OK_CODES
        assert q_floor(0.0699, 0.01) == 0.06 and q_step(1.123456, 0.00001) == 1.12346
        b = FxLiveBroker("t", "a", "new-york", "", ".r")
        assert b.broker_symbol("EURUSD") == "EURUSD.r" and b.our_symbol("EURUSD.r") == "EURUSD" and b.our_symbol("XAUUSD") == "XAUUSD"
        assert round_lots(0.237, {"min": 0.1, "step": 0.1, "max": 5}) == 0.2 and round_lots(0.05, {"min": 0.1, "step": 0.1, "max": 5}) == 0.0
        lots, margin, risk = position_size(1000, 1000, 1.0, 1.1000, 1.0980, 100, "EURUSD", {}, 0, {"min": 0.01, "step": 0.01, "max": 100, "contract": 100000})
        assert lots == 0.05 and risk == 1.0 and margin > 0
        api = MetaApi("tok", "london", "http://127.0.0.1:9")
        assert api._cli() == "http://127.0.0.1:9" and api._prov() == "http://127.0.0.1:9"
        assert MetaApi("tok", "london")._cli() == "https://mt-client-api-v1.london.agiliumtrade.ai"
        assert "TRADE_RETCODE_DONE" in OK_CODES

    def test_02_mock_and_config(self, s, saved):
        r = s.put(f"{FX}/config", json=CFG, timeout=30)
        assert r.status_code == 200, r.text
        c = r.json()
        assert c["hfm_configured"] is True and c["metaapi_base_url"] == MOCK and "••••" in c["metaapi_token"] and c["mt_password"].startswith("••")
        assert c["trading_mode"] == "paper" and c["hfm_state"] == "" and c["metaapi_account_id"] == ""
        assert c["secrets_encrypted"] is True
        # crypto config untouched by FX-only keys
        assert "metaapi_token" not in s.get(f"{BASE_URL}/api/config", timeout=30).json()

    def test_03_bad_endpoint_validation(self, s):
        assert s.put(f"{FX}/config", json={"metaapi_base_url": "ftp://x"}, timeout=30).status_code == 422
        assert s.put(f"{FX}/config", json={"metaapi_base_url": MOCK}, timeout=30).status_code == 200

    def test_04_link_test_symbols(self, s):
        r = s.post(f"{FX}/hfm/link", timeout=60)
        assert r.status_code == 200, r.text
        assert r.json()["account"]["state"] == "DEPLOYED" and r.json()["account"]["platform"] == "mt5"
        r = s.post(f"{FX}/hfm/test", json={}, timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["token_valid"] and d["account"]["connection"] == "CONNECTED" and d["info"]["equity"] == 1000.0 and d["info"]["tradeAllowed"] is True
        c = s.get(f"{FX}/config", timeout=30).json()
        assert c["hfm_verified_at"] and c["hfm_verified_equity"] == 1000.0 and c["hfm_trade_allowed"] is True and c["hfm_state"] == "DEPLOYED" and c["metaapi_account_id"]
        # wrong token → 424 (unsaved credentials path)
        r = s.post(f"{FX}/hfm/test", json={"metaapi_token": "wrongtoken", "metaapi_base_url": MOCK}, timeout=60)
        assert r.status_code == 424 and "401" in r.json()["detail"]
        # symbols: all quoted; with a bogus suffix none → then restore
        r = s.post(f"{FX}/hfm/symbols", timeout=120)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["missing"] == [] and all(v["ok"] and v["bid"] and v["min_lot"] == 0.01 for v in d["symbols"].values())
        s.put(f"{FX}/config", json={"mt_symbol_suffix": ".zz"}, timeout=30)
        d = s.post(f"{FX}/hfm/symbols", timeout=120).json()
        assert len(d["missing"]) == len(d["symbols"]) and d["suffix"] == ".zz" and d["symbols"]["EURUSD"]["broker_symbol"] == "EURUSD.zz"
        assert s.put(f"{FX}/config", json={"mt_symbol_suffix": ""}, timeout=30).json()["mt_symbol_suffix"] == ""
        # redeploy keeps account and resets verification until re-tested
        r = s.post(f"{FX}/hfm/redeploy", timeout=60)
        assert r.status_code == 200 and r.json()["account"]["state"] == "DEPLOYED"
        assert s.get(f"{FX}/config", timeout=30).json()["hfm_verified_at"] is None
        assert s.post(f"{FX}/hfm/test", json={}, timeout=60).status_code == 200

    def test_05_mode_checklist_and_guards(self, s):
        d = s.get(f"{FX}/mode", timeout=30).json()
        assert d["mode"] == "paper" and d["env"] == "HFMarketsGlobal-Demo" and d["currency"] == "USD" and d["verified_equity"] == 1000.0
        keys = [c["key"] for c in d["checks"]]
        assert keys == ["keys", "linked", "verified", "trade_allowed", "stopped", "flat", "paper"]
        assert d["can_go_live"] is True
        assert s.post(f"{FX}/mode", json={"mode": "live", "confirm": "nope"}, timeout=30).status_code == 400
        assert s.post(f"{FX}/mode", json={"mode": "foo"}, timeout=30).status_code == 400
        s.post(f"{FX}/bot/start", timeout=30)
        r = s.post(f"{FX}/mode", json={"mode": "live", "confirm": "REAL"}, timeout=30)
        assert r.status_code == 409 and "Bot detenido" in r.json()["detail"]
        s.post(f"{FX}/bot/stop", timeout=30)
        # paper start still works regardless of HFM state
        assert s.post(f"{FX}/bot/start", timeout=30).json()["mode"] == "PAPER"
        s.post(f"{FX}/bot/stop", timeout=30)

    def test_06_go_live(self, s):
        r = s.post(f"{FX}/mode", json={"mode": "live", "confirm": "real", "reset_stats": True}, timeout=60)
        assert r.status_code == 200, r.text
        assert r.json()["mode"] == "live" and r.json()["live_since"]
        d = s.get(f"{FX}/dashboard", timeout=30).json()
        assert d["status"]["mode"] == "REAL" and d["status"]["env"] == "HFMarketsGlobal-Demo" and d["hfm"]["live"] is True
        a = d["account"]
        assert a["mode"] == "REAL" and a["exchange_synced"] is True and abs(a["equity"] - mock_state()["equity"]) < 0.01 and a["initial_balance"] == 1000.0
        assert s.get(f"{FX}/config", timeout=30).json()["trading_mode"] == "live"
        assert s.put(f"{FX}/config", json={"clear_hfm": True}, timeout=30).status_code == 409
        assert any("MODO REAL ACTIVADO" in l["message"] for l in d["logs"][:5])

    def test_07_live_order_and_sync(self, s, saved):
        if not saved["market_open"]:
            pytest.skip("forex market closed: live order flow needs market_open()")
        assert s.post(f"{FX}/bot/start", timeout=30).json()["mode"] == "REAL"
        out = inject("EURUSD", "long")
        assert "'executed': True" in out, out[-800:]
        pos = wait_for(lambda: [p for p in s.get(f"{FX}/positions", timeout=30).json() if p["symbol"] == "EURUSD"], 15)
        assert pos, "no live position recorded"
        p = pos[0]
        assert p["live"] is True and p["order_id"] and p["link_id"].startswith("bot-") and p["qty"] >= 0.01 and p["leverage"] == 100
        mp = [x for x in mock_state()["positions"] if x["id"] == p["order_id"]]
        assert mp, "position not found at the mock broker"
        mp = mp[0]
        assert mp["symbol"] == "EURUSD" and mp["volume"] == p["qty"] and mp["clientId"] == p["link_id"] and mp["magic"] == 777001
        assert abs(mp["stopLoss"] - p["sl"]) < 1e-6 and abs(mp["takeProfit"] - p["tp"]) < 1e-6 and abs(mp["openPrice"] - p["entry_price"]) < 1e-9
        logs = s.get(f"{FX}/dashboard", timeout=30).json()["logs"]
        assert any("ABIERTA REAL LONG EURUSD" in l["message"] for l in logs[:10])
        # reset blocked while a live position is open
        assert s.post(f"{FX}/account/reset", json={}, timeout=30).status_code == 409
        s.post(f"{FX}/bot/stop", timeout=30)
        # trailing: move price ≥ 1.5R in favour → breakeven stop pushed to the broker
        r_dist = abs(p["entry_price"] - p["sl"])
        requests.post(f"{MOCK}/mock/price/EURUSD", params={"price": round(p["entry_price"] + 1.6 * r_dist, 5)}, timeout=10)
        moved = wait_for(lambda: next((x for x in mock_state()["positions"] if x["id"] == p["order_id"] and x["stopLoss"] >= p["entry_price"]), None), 30)
        assert moved, "broker stop not moved to breakeven"
        db = next(x for x in s.get(f"{FX}/positions", timeout=30).json() if x["id"] == p["id"])
        assert db["breakeven"] is True and abs(db["sl"] - moved["stopLoss"]) < 1e-6 and db["unrealized_pnl"] > 0
        logs = s.get(f"{FX}/dashboard", timeout=30).json()["logs"]
        assert any("stop REAL movido" in l["message"] for l in logs[:10])
        # broker-side stop hit (external close) → detected after the grace period, trade recorded from deals
        requests.post(f"{MOCK}/mock/close/{p['order_id']}", params={"reason": "sl"}, timeout=10)
        gone = wait_for(lambda: not [x for x in s.get(f"{FX}/positions", timeout=30).json() if x["id"] == p["id"]], 60)
        assert gone, "external close not detected"
        t = s.get(f"{FX}/trades", timeout=30).json()[0]
        assert t["symbol"] == "EURUSD" and t["live"] is True and t["reason"] == "TRAILING" and abs(t["exit_price"] - moved["stopLoss"]) < 1e-6
        deals = mock_state()["deals"][p["order_id"]]
        expected = sum(d["profit"] + d["swap"] + d["commission"] for d in deals)
        assert abs(t["pnl"] - round(expected, 4)) < 0.011
        a = s.get(f"{FX}/account", timeout=30).json()
        assert abs(a["equity"] - mock_state()["equity"]) < 0.01 and a["total_trades"] >= 1

    def test_08_manual_close_and_close_all(self, s, saved):
        if not saved["market_open"]:
            pytest.skip("forex market closed")
        s.post(f"{FX}/bot/start", timeout=30)
        assert "'executed': True" in inject("USDJPY", "short")
        assert "'executed': True" in inject("GBPUSD", "long")
        s.post(f"{FX}/bot/stop", timeout=30)
        ps = s.get(f"{FX}/positions", timeout=30).json()
        assert len(ps) == 2 and all(p["live"] for p in ps)
        pid = next(p for p in ps if p["symbol"] == "USDJPY")
        r = s.post(f"{FX}/positions/{pid['id']}/close", timeout=60)
        assert r.status_code == 200, r.text
        t = r.json()
        assert t["live"] is True and t["reason"] == "MANUAL" and t["symbol"] == "USDJPY"
        assert not [x for x in mock_state()["positions"] if x["id"] == pid["order_id"]]
        r = s.post(f"{FX}/positions/close-all", timeout=60)
        assert r.json() == {"closed": 1, "failed": 0}
        assert mock_state()["positions"] == [] and s.get(f"{FX}/positions", timeout=30).json() == []

    def test_09_trade_disabled_and_rejections(self, s, saved):
        if not saved["market_open"]:
            pytest.skip("forex market closed")
        requests.post(f"{MOCK}/mock/trade-allowed", params={"allowed": "false"}, timeout=10)
        s.post(f"{FX}/bot/start", timeout=30)
        out = inject("AUDUSD", "long")
        assert "'executed': True" not in out and "No ejecutada" in out
        s.post(f"{FX}/bot/stop", timeout=30)
        requests.post(f"{MOCK}/mock/trade-allowed", params={"allowed": "true"}, timeout=10)
        assert s.get(f"{FX}/positions", timeout=30).json() == []
        # investor password detected on test → start blocked in REAL mode
        requests.post(f"{MOCK}/mock/trade-allowed", params={"allowed": "false"}, timeout=10)
        d = s.post(f"{FX}/hfm/test", json={}, timeout=60).json()
        assert d["info"]["tradeAllowed"] is False and "master" in d["hint"]
        assert s.get(f"{FX}/config", timeout=30).json()["hfm_trade_allowed"] is False
        r = s.post(f"{FX}/bot/start", timeout=30)
        assert r.status_code == 409 and "no permite operar" in r.json()["detail"]
        chk = s.get(f"{FX}/mode", timeout=30).json()
        assert next(c for c in chk["checks"] if c["key"] == "trade_allowed")["ok"] is False
        requests.post(f"{MOCK}/mock/trade-allowed", params={"allowed": "true"}, timeout=10)
        assert s.post(f"{FX}/hfm/test", json={}, timeout=60).json()["info"]["tradeAllowed"] is True

    def test_10_back_to_paper(self, s):
        r = s.post(f"{FX}/mode", json={"mode": "paper", "confirm": "", "reset_stats": True}, timeout=60)
        assert r.status_code == 200 and r.json()["mode"] == "paper" and r.json()["live_since"] is None
        d = s.get(f"{FX}/dashboard", timeout=30).json()
        assert d["status"]["mode"] == "PAPER" and d["account"]["exchange_synced"] is False and d["account"]["initial_balance"] == 500.0 and d["hfm"]["live"] is False
        assert s.put(f"{FX}/config", json={"clear_hfm": True}, timeout=30).json()["hfm_configured"] is False
        assert s.get(f"{FX}/mode", timeout=30).json()["can_go_live"] is False

    def test_11_crypto_untouched(self, s):
        c = s.get(f"{BASE_URL}/api/config", timeout=30).json()
        assert c["trading_mode"] in ("paper", "live") and "metaapi_account_id" not in c
        assert s.get(f"{BASE_URL}/api/mode", timeout=30).status_code == 200
