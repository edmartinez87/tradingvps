# Iteration 5: LIVE (REAL) trading mode against local Bybit V5 mock (port 8011). Run with -n 0 (sequential).
import os
import time
import subprocess
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
MOCK = "http://localhost:8011"
PWD = "BlackCat2233@"
CREDS = {"bybit_api_key": "mockkey", "bybit_api_secret": "mocksecret", "bybit_env": "testnet", "bybit_base_url": MOCK}


@pytest.fixture(scope="module")
def s():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": PWD})
    assert r.status_code == 200
    ses = requests.Session()
    ses.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return ses


def inject(sym, side):
    out = subprocess.run(["python3", "scripts/inject_signal.py", sym, side, "noai"], cwd="/app", capture_output=True, text=True, timeout=90)
    print(out.stdout[-600:], out.stderr[-600:])
    return out.stdout


def positions(s):
    return s.get(f"{BASE_URL}/api/positions").json()


def mock_state():
    return requests.get(f"{MOCK}/mock/state").json()


def logs_text(s):
    return " | ".join(x["message"] for x in s.get(f"{BASE_URL}/api/dashboard").json()["logs"])


# --- current state / config ---
class TestState:
    def test_mock_up(self):
        assert requests.get(f"{MOCK}/v5/market/time").json()["retCode"] == 0

    def test_stop_bot(self, s):
        assert s.post(f"{BASE_URL}/api/bot/stop").status_code == 200

    def test_config_masked(self, s):
        c = s.get(f"{BASE_URL}/api/config").json()
        assert c["bybit_configured"] is True
        assert "••••" in c["bybit_api_key"] and c["bybit_api_secret"].endswith("cret")
        assert c["bybit_env"] == "testnet" and c["bybit_base_url"] == MOCK
        assert c["secrets_encrypted"] is True and c["trading_mode"] == "live"

    def test_dashboard_live(self, s):
        d = s.get(f"{BASE_URL}/api/dashboard").json()
        assert d["status"]["mode"] == "REAL" and d["status"]["env"] == "testnet"
        a = d["account"]
        assert a["mode"] == "REAL" and a["exchange_synced"] is True
        assert abs(a["equity"] - mock_state()["wallet"]) < 1.0


# --- POST /api/bybit/test ---
class TestBybitTest:
    def test_saved(self, s):
        r = s.post(f"{BASE_URL}/api/bybit/test", json={})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] and d["env"] == "testnet" and d["saved_credentials"] is True
        assert d["wallet"]["account_type"] == "UNIFIED" and d["wallet"]["equity"] > 0
        assert d["open_positions"] == 0 and isinstance(d["server_offset_ms"], int)

    def test_wrong(self, s):
        r = s.post(f"{BASE_URL}/api/bybit/test", json={"api_key": "wrongkey123", "api_secret": "x1234567890", "env": "testnet", "base_url": MOCK})
        assert r.status_code == 424 and "Bybit rechazó la conexión (10004)" in r.json()["detail"]

    def test_unsaved_ok(self, s):
        r = s.post(f"{BASE_URL}/api/bybit/test", json={"api_key": "mockkey", "api_secret": "mocksecret", "env": "testnet", "base_url": MOCK})
        assert r.status_code == 200 and r.json()["saved_credentials"] is False


# --- live open / sync / trailing / exchange close ---
class TestLiveLifecycle:
    def test_open(self, s):
        out = inject("SOLUSDT", "long")
        assert "mode: REAL broker: True" in out and "open positions: 1" in out
        ps = positions(s)
        assert len(ps) == 1, ps
        p = ps[0]
        assert p["live"] is True and p["order_id"] and p["symbol"] == "SOLUSDT" and p["side"] == "long"
        assert p["qty"] > 0 and abs(round(p["qty"] * 10) - p["qty"] * 10) < 1e-6 and p["entry_price"] > 0
        m = mock_state()
        assert m["positions"]["SOLUSDT"]["sl"] > 0 and m["positions"]["SOLUSDT"]["tp"] > 0
        assert m["leverage"]["SOLUSDT"] == "3"

    def test_sync_after_wait(self, s):
        time.sleep(8)
        ps = positions(s)
        assert len(ps) == 1, f"position vanished after sync: {ps} logs: {logs_text(s)[:600]}"
        assert ps[0]["mark_price"] > 0

    def test_trailing(self, s):
        p = positions(s)[0]
        r = abs(p["entry_price"] - p["initial_sl"])
        target = max(p["entry_price"] * 1.03, p["entry_price"] + 1.1 * r)
        requests.post(f"{MOCK}/mock/price/SOLUSDT", params={"price": round(target, 2)})
        time.sleep(9)
        p2 = positions(s)[0]
        assert p2["sl"] > p["entry_price"] and p2["breakeven"] is True, p2
        assert abs(mock_state()["positions"]["SOLUSDT"]["sl"] - round(p2["sl"] - 0.005, 2)) <= 0.011
        assert "stop REAL movido" in logs_text(s)

    def test_exchange_close(self, s):
        assert requests.post(f"{MOCK}/mock/close/SOLUSDT", params={"reason": "sl"}).json()["ok"]
        time.sleep(9)
        assert positions(s) == []
        t = s.get(f"{BASE_URL}/api/trades?limit=1").json()[0]
        assert t["symbol"] == "SOLUSDT" and t["live"] is True and t["reason"] == "TRAILING" and t["pnl"] > 0, t
        assert "CERRADA REAL" in logs_text(s)

    def test_manual_close(self, s):
        requests.post(f"{MOCK}/mock/price/SOLUSDT", params={"price": _bitget("SOLUSDT")})
        inject("SOLUSDT", "short")
        ps = positions(s)
        assert len(ps) == 1
        n_closed = len(mock_state()["closed"])
        r = s.post(f"{BASE_URL}/api/positions/{ps[0]['id']}/close")
        assert r.status_code == 200, r.text
        assert r.json()["live"] is True and r.json()["reason"] == "MANUAL"
        m = mock_state()
        assert m["positions"] == {} and len(m["closed"]) == n_closed + 1

    def test_close_all(self, s):
        inject("SOLUSDT", "long")
        inject("ETHUSDT", "long")
        assert len(positions(s)) == 2
        r = s.post(f"{BASE_URL}/api/positions/close-all")
        assert r.status_code == 200 and r.json() == {"closed": 2, "failed": 0}
        assert positions(s) == []


def _bitget(sym):
    r = requests.get("https://api.bitget.com/api/v2/mix/market/ticker", params={"productType": "USDT-FUTURES", "symbol": sym}, timeout=8)
    return float(r.json()["data"][0]["lastPr"])


# --- guards ---
class TestGuards:
    def test_reset_blocked_with_live_pos(self, s):
        inject("SOLUSDT", "long")
        assert len(positions(s)) == 1
        assert s.post(f"{BASE_URL}/api/account/reset", json={}).status_code == 409
        assert s.post(f"{BASE_URL}/api/mode", json={"mode": "paper"}).status_code == 409
        assert s.post(f"{BASE_URL}/api/positions/close-all").json()["closed"] == 1

    def test_start_without_creds(self, s):
        assert s.put(f"{BASE_URL}/api/config", json={"clear_bybit": True}).status_code == 200
        r = s.post(f"{BASE_URL}/api/bot/start")
        assert r.status_code == 409 and "Modo REAL sin credenciales" in r.json()["detail"]
        assert s.put(f"{BASE_URL}/api/config", json=CREDS).status_code == 200
        assert s.post(f"{BASE_URL}/api/bybit/test", json={}).status_code == 200
        assert s.get(f"{BASE_URL}/api/config").json()["bybit_configured"] is True


# --- mode switching ---
class TestModeSwitch:
    def test_to_paper(self, s):
        r = s.post(f"{BASE_URL}/api/mode", json={"mode": "paper"})
        assert r.status_code == 200 and r.json()["mode"] == "paper"
        d = s.get(f"{BASE_URL}/api/dashboard").json()
        assert d["status"]["mode"] == "PAPER" and d["account"]["exchange_synced"] is False
        assert d["account"]["initial_balance"] == 500

    def test_mode_checklist(self, s):
        m = s.get(f"{BASE_URL}/api/mode").json()
        assert [c["key"] for c in m["checks"]] == ["keys", "verified", "stopped", "flat", "plan"]
        assert m["can_go_live"] is True

    def test_live_bad_confirm(self, s):
        assert s.post(f"{BASE_URL}/api/mode", json={"mode": "live", "confirm": "si"}).status_code == 400

    def test_live_ok(self, s):
        r = s.post(f"{BASE_URL}/api/mode", json={"mode": "live", "confirm": "REAL"})
        assert r.status_code == 200 and r.json()["mode"] == "live"
        a = s.get(f"{BASE_URL}/api/account").json()
        assert abs(a["initial_balance"] - r.json()["verified_equity"]) < 0.01
        assert abs(a["initial_balance"] - mock_state()["wallet"]) < 2

    def test_paper_blocked_when_running(self, s):
        assert s.post(f"{BASE_URL}/api/bot/start").status_code == 200
        r = s.post(f"{BASE_URL}/api/mode", json={"mode": "paper"})
        assert r.status_code == 409 and "Bot detenido" in r.json()["detail"]
        assert s.post(f"{BASE_URL}/api/bot/stop").status_code == 200
