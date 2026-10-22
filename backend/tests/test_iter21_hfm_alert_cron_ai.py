"""Iteration 21 – (a) Telegram alert when the HFM account loses its MetaApi connection in REAL mode (mock on :8012),
(d) cron run_ids persisted in Mongo (survive a backend restart), (e) clearing the Gemini key resets the model default.
Run sequentially: `python -m pytest tests/test_iter21_hfm_alert_cron_ai.py -n 0`."""
import os
import time
import uuid
import subprocess
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
FX = f"{BASE_URL}/api/fx"
MOCK = "http://127.0.0.1:8012"
CFG = {"metaapi_token": "mocktoken", "mt_login": "12345678", "mt_password": "masterpass", "mt_server": "HFMarketsGlobal-Demo", "mt_platform": "mt5",
       "metaapi_region": "new-york", "metaapi_base_url": MOCK, "mt_symbol_suffix": ""}


def _secret():
    for line in open("/app/backend/.env"):
        if line.startswith("WEBHOOK_CRON_SECRET="):
            return line.split("=", 1)[1].strip().strip('"')
    return ""


def wait_for(fn, timeout=60, step=2):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return None


def _up():
    try:
        return requests.get(f"{MOCK}/mock/state", timeout=2).status_code == 200
    except Exception:
        return False


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
    if not _up():
        subprocess.Popen(["python3", "scripts/metaapi_mock.py"], cwd="/app", stdout=open("/tmp/metaapi_mock.log", "a"), stderr=subprocess.STDOUT)
        assert wait_for(_up, 20, 1), "mock did not start"
    requests.post(f"{MOCK}/mock/reset", timeout=10)
    requests.post(f"{MOCK}/mock/connection", params={"connected": "true"}, timeout=10)
    yield MOCK
    requests.post(f"{MOCK}/mock/connection", params={"connected": "true"}, timeout=10)


@pytest.fixture(scope="module")
def live(s, mock):
    """Point the FX bot to the mock, go REAL with a short alert threshold; restore paper + clear HFM at the end."""
    s.post(f"{FX}/bot/stop", timeout=30)
    assert s.put(f"{FX}/config", json={**CFG, "hfm_alert_after_sec": 15}, timeout=30).status_code == 200
    assert s.post(f"{FX}/hfm/link", timeout=60).status_code == 200
    assert s.post(f"{FX}/hfm/test", json={}, timeout=60).status_code == 200
    r = s.post(f"{FX}/mode", json={"mode": "live", "confirm": "REAL", "reset_stats": True}, timeout=60)
    assert r.status_code == 200, r.text
    yield s
    s.post(f"{FX}/bot/stop", timeout=30)
    s.post(f"{FX}/mode", json={"mode": "paper", "confirm": "", "reset_stats": True}, timeout=60)
    s.put(f"{FX}/config", json={"clear_hfm": True}, timeout=30)
    s.put(f"{FX}/config", json={"metaapi_base_url": "", "mt_symbol_suffix": "", "hfm_alert_after_sec": 180}, timeout=30)


def _logs(s, n=40):
    return [l["message"] for l in s.get(f"{FX}/dashboard", timeout=30).json()["logs"][:n]]


class TestHfmDisconnectAlert:
    def test_01_unit_helpers(self):
        import sys
        import asyncio
        sys.path.insert(0, "/app/backend")
        from fx.engine import fmt_duration, _fresh_health, FxEngine
        from fx.models import FxSettings
        from fx.market import market_open
        from config import DEFAULT_ALERTS
        assert fmt_duration(45) == "45 s" and fmt_duration(130) == "2 min" and fmt_duration(3 * 3600 + 5 * 60) == "3 h 05 min"
        h = _fresh_health()
        assert h["ok"] is None and h["down_since"] is None and h["alerted_at"] is None
        assert DEFAULT_ALERTS["system"] is True

        class _Cur:
            async def to_list(self, n):
                return []

        class _Col:
            def find(self, *a, **k):
                return _Cur()

        class _DB:
            positions = _Col()

        eng = FxEngine.__new__(FxEngine)
        eng.db, eng.live, eng.hfm = _DB(), True, {**_fresh_health(), "down_since": time.time(), "error": "MetaApi 404"}
        eng.broker, eng.cfg = object(), None
        assert eng.broker_health() is not None and eng.broker_health()["ok"] is True  # ok is None → treated as not-down yet
        eng.hfm["ok"] = False
        assert eng.broker_health()["ok"] is False and eng.broker_health()["down_sec"] >= 0
        if market_open():
            block, kind, _ = asyncio.run(eng._blocks("EURUSD", FxSettings(sessions_allowed=[]), {"daily_paused": False}))
            assert kind == "BLOQUEADA" and "sin conexión" in block
        eng.live = False
        assert eng.broker_health() is None

    def test_02_config_field_and_validation(self, s):
        c = s.get(f"{FX}/config", timeout=30).json()
        assert "hfm_alert_after_sec" in c and "system" in c["telegram_alerts"]
        assert s.put(f"{FX}/config", json={"hfm_alert_after_sec": 5}, timeout=30).status_code == 422
        assert s.put(f"{FX}/config", json={"hfm_alert_after_sec": 4000}, timeout=30).status_code == 422
        assert s.put(f"{FX}/config", json={"hfm_alert_after_sec": 120}, timeout=30).json()["hfm_alert_after_sec"] == 120
        # crypto config is not touched by this FX-only key, and the system alert toggle round-trips
        assert "hfm_alert_after_sec" not in s.get(f"{BASE_URL}/api/config", timeout=30).json()
        r = s.put(f"{BASE_URL}/api/config", json={"telegram_alerts": {"system": False}}, timeout=30)
        assert r.status_code == 200 and r.json()["telegram_alerts"]["system"] is False
        assert s.put(f"{BASE_URL}/api/config", json={"telegram_alerts": {"system": True}}, timeout=30).json()["telegram_alerts"]["system"] is True

    def test_03_paper_mode_has_no_health(self, s):
        st = s.get(f"{FX}/dashboard", timeout=30).json()["status"]
        if st["mode"] == "PAPER":
            assert st["broker_health"] is None

    def test_04_live_connected_health(self, live):
        s = live
        st = wait_for(lambda: (lambda x: x if x["broker_health"] and x["broker_health"]["ok"] else None)(s.get(f"{FX}/dashboard", timeout=30).json()["status"]), 30)
        assert st, "health never reported ok"
        h = st["broker_health"]
        assert h["ok"] is True and h["down_since"] is None and h["alerted"] is False and h["alert_after_sec"] == 15
        # the periodic state check mirrors MetaApi's account state into the config
        c = wait_for(lambda: (lambda c: c if c["hfm_connection"] == "CONNECTED" else None)(s.get(f"{FX}/config", timeout=30).json()), 70, 5)
        assert c and c["hfm_state"] == "DEPLOYED"

    def test_05_disconnect_alert_blocks_entries_and_recovers(self, live):
        s = live
        requests.post(f"{MOCK}/mock/connection", params={"connected": "false"}, timeout=10)
        # health flips to not-ok within a couple of monitor ticks
        st = wait_for(lambda: (lambda x: x if x["broker_health"] and x["broker_health"]["ok"] is False else None)(s.get(f"{FX}/dashboard", timeout=30).json()["status"]), 30)
        assert st, "health did not flip to down"
        h = st["broker_health"]
        assert h["down_since"] and h["error"] and ("404" in h["error"] or "DISCONNECTED" in h["error"])
        # alert after hfm_alert_after_sec (15 s) → ERROR log, health.alerted
        st = wait_for(lambda: (lambda x: x if x["broker_health"] and x["broker_health"]["alerted"] else None)(s.get(f"{FX}/dashboard", timeout=30).json()["status"]), 60)
        assert st, "alert never fired"
        logs = _logs(s)
        assert any("Cuenta HFM sin conexión con MetaApi" in m for m in logs), logs[:10]
        # connection state mirrored into the config → mode checklist shows it
        c = wait_for(lambda: (lambda c: c if "DISCONNECTED" in (c["hfm_connection"] or "") else None)(s.get(f"{FX}/config", timeout=30).json()), 40, 3)
        assert c, "hfm_connection not mirrored"
        linked = next(x for x in s.get(f"{FX}/mode", timeout=30).json()["checks"] if x["key"] == "linked")
        assert "DISCONNECTED" in linked["detail"]
        # new entries are blocked while down (no AI call, no order): signal recorded as BLOQUEADA
        market_open = s.get(f"{FX}/market", timeout=30).json()["open"]
        if market_open:
            s.post(f"{FX}/bot/start", timeout=30)
            out = subprocess.run(["python3", "scripts/fx_inject_signal.py", "EURUSD", "long", "noai"], cwd="/app", capture_output=True, text=True, timeout=120)
            txt = out.stdout + out.stderr
            assert "'executed': True" not in txt and ("sin conexión" in txt or "BLOQUEADA" in txt), txt[-600:]
            s.post(f"{FX}/bot/stop", timeout=30)
            assert s.get(f"{FX}/positions", timeout=30).json() == []
        # recovery → INFO log, health ok again, no alert pending
        requests.post(f"{MOCK}/mock/connection", params={"connected": "true"}, timeout=10)
        st = wait_for(lambda: (lambda x: x if x["broker_health"] and x["broker_health"]["ok"] and not x["broker_health"]["alerted"] else None)(s.get(f"{FX}/dashboard", timeout=30).json()["status"]), 60)
        assert st, "health did not recover"
        assert any("Conexión con HFM restablecida" in m for m in _logs(s))
        c = wait_for(lambda: (lambda c: c if c["hfm_connection"] == "CONNECTED" else None)(s.get(f"{FX}/config", timeout=30).json()), 40, 3)
        assert c, "hfm_connection not restored"

    def test_06_short_blip_does_not_alert(self, live):
        s = live
        before = sum("Cuenta HFM sin conexión" in m for m in _logs(s, 100))
        requests.post(f"{MOCK}/mock/connection", params={"connected": "false"}, timeout=10)
        time.sleep(6)
        requests.post(f"{MOCK}/mock/connection", params={"connected": "true"}, timeout=10)
        time.sleep(12)
        st = s.get(f"{FX}/dashboard", timeout=30).json()["status"]
        assert st["broker_health"]["ok"] is True and st["broker_health"]["alerted"] is False
        assert sum("Cuenta HFM sin conexión" in m for m in _logs(s, 100)) == before

    def test_07_back_to_paper_clears_health(self, live):
        s = live
        assert s.post(f"{FX}/mode", json={"mode": "paper", "confirm": "", "reset_stats": True}, timeout=60).status_code == 200
        st = s.get(f"{FX}/dashboard", timeout=30).json()["status"]
        assert st["mode"] == "PAPER" and st["broker_health"] is None


class TestGeminiClearResetsModel:
    def test_clear_resets_gemini_model(self, s):
        orig = s.get(f"{BASE_URL}/api/config", timeout=30).json()
        r = s.put(f"{BASE_URL}/api/config", json={"ai_source": "gemini", "gemini_api_key": "AIzaBogusKey1234567890", "gemini_model": "gemini-2.5-flash"}, timeout=30)
        assert r.status_code == 200 and r.json()["gemini_model"] == "gemini-2.5-flash" and r.json()["gemini_configured"] is True
        r = s.put(f"{BASE_URL}/api/config", json={"clear_gemini_api_key": True}, timeout=30)
        c = r.json()
        assert c["ai_source"] == "emergent" and c["gemini_configured"] is False and c["gemini_model"] == "gemini-3.1-pro-preview"
        assert c["ai_active"]["source"] == "emergent"
        if orig["ai_source"] == "emergent":
            assert c["ai_provider"] == orig["ai_provider"] and c["ai_model"] == orig["ai_model"]


class TestCronRunIdPersistence:
    def test_01_duplicate_detected_and_stored(self):
        h = {"Authorization": f"Bearer {_secret()}"}
        rid = f"qa21-{uuid.uuid4().hex[:10]}"
        r1 = requests.post(f"{BASE_URL}/api/cron/ai-review", json={"run_id": rid}, headers=h, timeout=20)
        assert r1.status_code == 200 and r1.json()["accepted"] is True and "duplicate" not in r1.json()
        r2 = requests.post(f"{BASE_URL}/api/cron/ai-review", json={"run_id": rid}, headers=h, timeout=20)
        assert r2.json() == {"accepted": True, "duplicate": True}
        # header form shares the same store
        r3 = requests.post(f"{BASE_URL}/api/cron/weekly-summary", json={}, headers={**h, "X-Webhook-Id": rid}, timeout=20)
        assert r3.json() == {"accepted": True, "duplicate": True}
        # no run_id → never deduplicated; bad body → 400; wrong secret → 401 (unchanged contract)
        assert requests.post(f"{BASE_URL}/api/cron/ai-review", json={}, headers=h, timeout=20).json()["accepted"] is True
        assert requests.post(f"{BASE_URL}/api/cron/ai-review", json=[1], headers=h, timeout=20).status_code == 400
        assert requests.post(f"{BASE_URL}/api/cron/ai-review", json={"run_id": "x"}, headers={"Authorization": "Bearer nope"}, timeout=20).status_code == 401
        # stored in Mongo with a TTL index
        import sys
        sys.path.insert(0, "/app/backend")
        from pymongo import MongoClient
        env = dict(l.strip().split("=", 1) for l in open("/app/backend/.env") if "=" in l and not l.startswith("#"))
        db = MongoClient(env["MONGO_URL"].strip('"'))[env["DB_NAME"].strip('"')]
        doc = db.cron_runs.find_one({"_id": rid})
        assert doc and doc["path"] == "/api/cron/ai-review" and doc["at"]
        idx = db.cron_runs.index_information()
        assert any(v.get("expireAfterSeconds") == 30 * 86400 for v in idx.values())

    def test_02_survives_backend_restart(self):
        h = {"Authorization": f"Bearer {_secret()}"}
        rid = f"qa21r-{uuid.uuid4().hex[:10]}"
        assert "duplicate" not in requests.post(f"{BASE_URL}/api/cron/weekly-summary", json={"run_id": rid}, headers=h, timeout=20).json()
        subprocess.run(["sudo", "supervisorctl", "restart", "backend"], capture_output=True, timeout=60)

        def ready():
            try:
                return requests.get(f"{BASE_URL}/api/", timeout=5).status_code == 200
            except Exception:
                return False
        assert wait_for(ready, 60, 2), "backend did not come back"
        r = requests.post(f"{BASE_URL}/api/cron/weekly-summary", json={"run_id": rid}, headers=h, timeout=20)
        assert r.json() == {"accepted": True, "duplicate": True}
