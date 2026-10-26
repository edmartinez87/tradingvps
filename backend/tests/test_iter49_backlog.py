"""Iteration 49 – backlog round: (a) Bybit disconnection alert in REAL crypto mode (mock :8011 + /mock/connection), shared `broker_health`
state machine reused by the FX engine; (b) month-end fix reversion: 30-minute entry window + half-reversion guard; (c) `bybit_alert_after_sec` config.
Run sequentially: `python -m pytest tests/test_iter49_backlog.py -n 0` (switches the crypto bot to REAL against the mock and back to paper; both
transitions reset the paper statistics, so only run it on a disposable account)."""
import os
import sys
import time
import subprocess
from datetime import datetime, timedelta, timezone
import pytest
import requests

sys.path.insert(0, "/app/backend")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
MOCK_PORT = os.environ.get("BYBIT_MOCK_PORT", "8013")  # 8011 is taken by the platform's nginx in this pod
MOCK = f"http://127.0.0.1:{MOCK_PORT}"
CREDS = {"bybit_api_key": "mockkey", "bybit_api_secret": "mocksecret", "bybit_env": "testnet", "bybit_base_url": MOCK}


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
    r = requests.post(f"{API}/auth/login", json={"password": "BlackCat2233@"}, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"login failed {r.status_code}")
    sess = requests.Session()
    sess.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return sess


@pytest.fixture(scope="module")
def mock():
    if not _up():
        subprocess.Popen(["python3", "scripts/bybit_mock.py"], cwd="/app", env={**os.environ, "BYBIT_MOCK_PORT": MOCK_PORT},
                         stdout=open("/tmp/bybit_mock.log", "a"), stderr=subprocess.STDOUT)
        assert wait_for(_up, 20, 1), "bybit mock did not start"
    requests.post(f"{MOCK}/mock/reset", timeout=10)
    yield MOCK
    requests.post(f"{MOCK}/mock/connection", params={"connected": "true"}, timeout=10)


@pytest.fixture(scope="module")
def live(s, mock):
    """Crypto bot → REAL against the mock with a 15 s alert threshold; back to paper + credentials cleared at the end."""
    s.post(f"{API}/bot/stop", timeout=30)
    if s.get(f"{API}/positions", timeout=30).json():
        pytest.skip("crypto account has open positions: not switching modes")
    assert s.put(f"{API}/config", json={**CREDS, "bybit_alert_after_sec": 15}, timeout=30).status_code == 200
    assert s.post(f"{API}/bybit/test", json={}, timeout=60).status_code == 200
    r = s.post(f"{API}/mode", json={"mode": "live", "confirm": "REAL", "reset_stats": True}, timeout=60)
    assert r.status_code == 200, r.text
    yield s
    s.post(f"{API}/bot/stop", timeout=30)
    requests.post(f"{MOCK}/mock/connection", params={"connected": "true"}, timeout=10)
    s.post(f"{API}/mode", json={"mode": "paper", "confirm": "", "reset_stats": True}, timeout=60)
    s.put(f"{API}/config", json={"clear_bybit": True, "bybit_base_url": "", "bybit_env": "mainnet", "bybit_alert_after_sec": 180}, timeout=30)


def _status(s):
    return s.get(f"{API}/dashboard", timeout=30).json()["status"]


def _logs(s, n=60):
    return [l["message"] for l in s.get(f"{API}/dashboard", timeout=30).json()["logs"][:n]]


class TestBrokerHealthUnit:
    def test_01_state_machine(self):
        import broker_health as bh
        h = bh.fresh_health()
        assert bh.transition(h, True, "", 15, now=1000.0) == (None, 0.0) and h["ok"] is True
        assert bh.transition(h, False, "503", 15, now=1000.0) == (None, 0.0) and h["down_since"] == 1000.0 and h["error"] == "503"
        assert bh.transition(h, False, "503", 15, now=1010.0)[0] is None            # still inside the grace period
        ev, dur = bh.transition(h, False, "503", 15, now=1016.0)
        assert ev == "down" and dur == 16.0 and h["alerted_at"] == 1016.0
        assert bh.transition(h, False, "503", 15, now=2000.0)[0] is None            # alerted once, no spam
        ev, dur = bh.transition(h, False, "503", 15, now=1016.0 + bh.REMIND_SEC)
        assert ev == "remind" and dur == bh.REMIND_SEC + 16.0
        ev, dur = bh.transition(h, True, "", 15, now=1016.0 + bh.REMIND_SEC + 100)
        assert ev == "up" and dur == bh.REMIND_SEC + 116.0 and h["down_since"] is None and h["alerted_at"] is None and h["error"] is None
        # a short blip (down → up before the threshold) never produces an event
        bh.transition(h, False, "x", 15, now=5000.0)
        assert bh.transition(h, True, "", 15, now=5005.0) == (None, 0.0)

    def test_02_summary_and_fmt(self):
        import broker_health as bh
        from fx.engine import fmt_duration, _fresh_health
        assert fmt_duration is bh.fmt_duration and _fresh_health is bh.fresh_health
        assert bh.fmt_duration(45) == "45 s" and bh.fmt_duration(130) == "2 min" and bh.fmt_duration(3 * 3600 + 5 * 60) == "3 h 05 min"
        h = bh.fresh_health()
        out = bh.summary(h, 180)
        assert out["ok"] is True and out["down_since"] is None and out["down_sec"] == 0 and out["alerted"] is False and out["alert_after_sec"] == 180
        h.update(ok=False, down_since=time.time() - 30, alerted_at=time.time(), error="boom")
        out = bh.summary(h, 180)
        assert out["ok"] is False and out["down_since"] and 29 <= out["down_sec"] <= 35 and out["alerted"] is True and out["error"] == "boom"

    def test_03_crypto_engine_helpers(self):
        from engine import TradingEngine
        eng = TradingEngine.__new__(TradingEngine)
        eng.live, eng.broker, eng.cfg = False, None, None
        import broker_health as bh
        eng.bybit = bh.fresh_health()
        assert eng.broker_health() is None
        eng.live, eng.broker = True, object()
        assert eng.broker_health()["ok"] is True and eng.broker_health()["alert_after_sec"] is None
        eng.bybit.update(ok=False, down_since=time.time(), error="503")
        assert eng.broker_health()["ok"] is False


class TestFixReversionWindow:
    def test_window_two_candles(self):
        from fx.market import LONDON
        from fx.strategies_slow import fix_window, ENTRY_WINDOW_MIN, SLOW_INFO
        assert ENTRY_WINDOW_MIN == 30 and "16:30" in SLOW_INFO["fix_reversion"]["rules"]
        day = datetime(2026, 1, 30, 16, 0, tzinfo=LONDON)  # Friday 30 Jan 2026 = last business day
        assert fix_window(day.astimezone(timezone.utc))
        assert fix_window((day + timedelta(minutes=25)).astimezone(timezone.utc)), "a late scan inside the 2nd 15m candle must still see the window"
        assert fix_window((day + timedelta(minutes=30)).astimezone(timezone.utc))
        assert fix_window((day + timedelta(minutes=31)).astimezone(timezone.utc)) is None

    def _rows(self, fix):
        rows, px = [], 1.0800
        for k in range(28):
            ts = fix - timedelta(hours=6) + timedelta(minutes=15 * k)
            if fix - timedelta(hours=1) <= ts < fix:
                px += 0.0010
            rows.append([int(ts.timestamp() * 1000), px, px + 0.0003, px - 0.0003, px, 1])
        return rows, px

    def test_half_reversion_guard(self):
        from fx.market import LONDON
        from fx.strategies_slow import fix_signal
        fix = datetime(2026, 1, 30, 16, 0, tzinfo=LONDON).astimezone(timezone.utc)
        rows, fix_px = self._rows(fix)
        move = 0.0040  # 4 candles × 10 pips
        late = fix + timedelta(minutes=25)
        sig = fix_signal("EURUSD", rows, 0.0030, late, fix_px - 0.2 * move)
        assert sig and sig["side"] == "short" and sig["indicators"]["reverted_pct"] == 20.0 and "ya deshecho 20 %" in sig["reasons"][1]
        assert fix_signal("EURUSD", rows, 0.0030, late, fix_px - 0.6 * move) is None, "more than half already reverted → no edge"
        sig0 = fix_signal("EURUSD", rows, 0.0030, late, fix_px + 0.0002)  # price above the fix (move still extending) → 0 % reverted
        assert sig0 and sig0["indicators"]["reverted_pct"] == 0.0
        assert fix_signal("EURUSD", rows, 0.0030, fix + timedelta(minutes=31), fix_px - 0.0002) is None


class TestBybitAlertConfig:
    def test_field_and_validation(self, s):
        c = s.get(f"{API}/config", timeout=30).json()
        assert "bybit_alert_after_sec" in c and "system" in c["telegram_alerts"]
        assert s.put(f"{API}/config", json={"bybit_alert_after_sec": 5}, timeout=30).status_code == 422
        assert s.put(f"{API}/config", json={"bybit_alert_after_sec": 4000}, timeout=30).status_code == 422
        assert s.put(f"{API}/config", json={"bybit_alert_after_sec": 120}, timeout=30).json()["bybit_alert_after_sec"] == 120
        assert s.put(f"{API}/config", json={"bybit_alert_after_sec": 180}, timeout=30).json()["bybit_alert_after_sec"] == 180

    def test_paper_mode_has_no_health(self, s):
        st = _status(s)
        assert "broker_health" in st
        if st["mode"] == "PAPER":
            assert st["broker_health"] is None


class TestBybitDisconnectAlert:
    def test_01_live_connected_health(self, live):
        s = live
        st = wait_for(lambda: (lambda x: x if x["broker_health"] and x["broker_health"]["ok"] else None)(_status(s)), 30)
        assert st, "health never reported ok"
        h = st["broker_health"]
        assert h["ok"] is True and h["down_since"] is None and h["alerted"] is False and h["alert_after_sec"] == 15 and st["mode"] == "REAL"
        # saving the same env/base_url again (e.g. only changing the alert seconds) must not drop the verification
        assert s.put(f"{API}/config", json={"bybit_env": "testnet", "bybit_base_url": MOCK, "bybit_alert_after_sec": 15}, timeout=30).json()["bybit_verified_at"]

    def test_02_disconnect_alert_blocks_entries_and_recovers(self, live):
        s = live
        requests.post(f"{MOCK}/mock/connection", params={"connected": "false"}, timeout=10)
        st = wait_for(lambda: (lambda x: x if x["broker_health"] and x["broker_health"]["ok"] is False else None)(_status(s)), 30)
        assert st, "health did not flip to down"
        h = st["broker_health"]
        assert h["down_since"] and h["error"] and st["exchange_error"]
        st = wait_for(lambda: (lambda x: x if x["broker_health"] and x["broker_health"]["alerted"] else None)(_status(s)), 60)
        assert st, "alert never fired"
        assert any("Bybit sin respuesta desde hace" in m for m in _logs(s)), _logs(s)[:10]
        # a new signal is discarded as BLOQUEADA while down: no order reaches the exchange
        s.post(f"{API}/bot/start", timeout=30)
        out = subprocess.run(["python3", "scripts/inject_signal.py", "BTCUSDT", "long", "noai"], cwd="/app", capture_output=True, text=True, timeout=150)
        txt = out.stdout + out.stderr
        assert "mode: REAL broker: True" in txt and "open positions: 0" in txt and "Bybit sin respuesta" in txt, txt[-800:]
        s.post(f"{API}/bot/stop", timeout=30)
        assert s.get(f"{API}/positions", timeout=30).json() == []
        assert requests.get(f"{MOCK}/mock/state", timeout=10).json()["positions"] == {}
        # recovery → INFO log + health ok, no alert pending
        requests.post(f"{MOCK}/mock/connection", params={"connected": "true"}, timeout=10)
        st = wait_for(lambda: (lambda x: x if x["broker_health"] and x["broker_health"]["ok"] and not x["broker_health"]["alerted"] else None)(_status(s)), 60)
        assert st, "health did not recover"
        assert any("Conexión con Bybit restablecida" in m for m in _logs(s))
        assert st["exchange_error"] is None

    def test_03_short_blip_does_not_alert(self, live):
        s = live
        before = sum("Bybit sin respuesta desde hace" in m for m in _logs(s, 100))
        requests.post(f"{MOCK}/mock/connection", params={"connected": "false"}, timeout=10)
        time.sleep(6)
        requests.post(f"{MOCK}/mock/connection", params={"connected": "true"}, timeout=10)
        time.sleep(12)
        st = _status(s)
        assert st["broker_health"]["ok"] is True and st["broker_health"]["alerted"] is False
        assert sum("Bybit sin respuesta desde hace" in m for m in _logs(s, 100)) == before

    def test_04_back_to_paper_clears_health(self, live):
        s = live
        assert s.post(f"{API}/mode", json={"mode": "paper", "confirm": "", "reset_stats": True}, timeout=60).status_code == 200
        st = _status(s)
        assert st["mode"] == "PAPER" and st["broker_health"] is None
