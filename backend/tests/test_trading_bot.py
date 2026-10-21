# Regression tests for the paper-trading crypto bot API (dashboard, meta, klines, bot control, settings,
# position lifecycle via inject script, AI confirmation, risk rules, backtest, account reset, logs)
import os
import time
import subprocess
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
DEFAULTS = {"strategy": "all", "timeframe": "1h", "risk_per_trade": 1, "max_positions": 3, "leverage": 3,
            "daily_loss_limit": 5, "ai_enabled": True, "ai_min_confidence": 60, "scan_interval_sec": 60,
            "trailing_enabled": True, "htf_filter": True,
            "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "AVAXUSDT", "LINKUSDT"]}


def inject(symbol, side, noai=True, timeout=90):
    args = ["python3", "/app/scripts/inject_signal.py", symbol, side] + (["noai"] if noai else [])
    return subprocess.run(args, cwd="/app/backend", capture_output=True, text=True, timeout=timeout)


@pytest.fixture(scope="session")
def s():
    sess = requests.Session()
    sess.headers["Authorization"] = "Bearer " + requests.post(f"{API}/auth/login", json={"password": "BlackCat2233@"}, timeout=20).json()["token"]
    yield sess
    sess.put(f"{API}/settings", json=DEFAULTS)
    sess.post(f"{API}/bot/stop")
    sess.post(f"{API}/account/reset")


# Health / dashboard / meta
class TestRead:
    def test_dashboard(self, s):
        r = s.get(f"{API}/dashboard")
        assert r.status_code == 200
        d = r.json()
        if not all("trend" in w for w in d["watchlist"]):  # fresh backend: analysis is filled by the first scan
            s.post(f"{API}/bot/scan")
            time.sleep(25)
            d = s.get(f"{API}/dashboard").json()
        for k in ("status", "settings", "account", "positions", "trades", "signals", "logs", "watchlist", "equity"):
            assert k in d
        assert d["status"]["provider"] in ("bitget", "bybit")
        assert "next_scan_in" in d["status"]
        assert len(d["watchlist"]) == len(d["settings"]["symbols"])
        w = d["watchlist"][0]
        assert isinstance(w["price"], (int, float)) and w["price"] > 0
        for k in ("change_pct", "trend", "rsi"):
            assert k in w, f"missing {k} in watchlist"

    def test_meta(self, s):
        d = s.get(f"{API}/meta").json()
        assert "BTCUSDT" in d["symbols"] and "1h" in d["timeframes"]
        assert set(d["strategies"]) == {"all", "trend_ema", "mean_reversion", "breakout_turtle", "supertrend_momentum", "ema_pullback"}
        assert "trend_ema" in d["strategy_info"]

    def test_klines(self, s):
        r = s.get(f"{API}/klines", params={"symbol": "BTCUSDT", "tf": "1h"})
        assert r.status_code == 200
        d = r.json()
        for k in ("candles", "volume", "ema9", "ema21", "ema200", "rsi", "markers", "lines"):
            assert k in d
        assert len(d["candles"]) >= 100
        c = d["candles"][-1]
        assert c["high"] >= c["low"] > 0

    def test_klines_invalid(self, s):
        assert s.get(f"{API}/klines", params={"symbol": "FOOUSDT", "tf": "1h"}).status_code == 400
        assert s.get(f"{API}/klines", params={"symbol": "BTCUSDT", "tf": "2h"}).status_code == 400


# Bot control
class TestBot:
    def test_start_stop_scan(self, s):
        r = s.post(f"{API}/bot/start")
        assert r.status_code == 200 and r.json()["running"] is True
        assert s.get(f"{API}/settings").json()["bot_running"] is True
        assert s.post(f"{API}/bot/scan").json()["ok"] is True
        found = False
        for _ in range(15):
            time.sleep(3)
            logs = s.get(f"{API}/dashboard").json()["logs"]
            if any(l["level"] == "SCAN" for l in logs[:20]):
                found = True
                break
        r = s.post(f"{API}/bot/stop")
        assert r.json()["running"] is False
        assert s.get(f"{API}/settings").json()["bot_running"] is False
        logs = s.get(f"{API}/dashboard").json()["logs"]
        assert any("DETENIDO" in l["message"] for l in logs[:5])
        assert found, "No SCAN log after manual scan with bot running"


# Settings
class TestSettings:
    def test_update_persist(self, s):
        payload = {"risk_per_trade": 2, "max_positions": 4, "leverage": 5, "daily_loss_limit": 6, "timeframe": "15m",
                   "strategy": "trend_ema", "symbols": ["BTCUSDT", "ETHUSDT"], "ai_enabled": False,
                   "trailing_enabled": False, "htf_filter": False}
        r = s.put(f"{API}/settings", json=payload)
        assert r.status_code == 200
        g = s.get(f"{API}/settings").json()
        for k, v in payload.items():
            assert g[k] == v, k
        assert s.put(f"{API}/settings", json=DEFAULTS).status_code == 200

    @pytest.mark.parametrize("bad", [{"leverage": 50}, {"symbols": []}, {"strategy": "foo"},
                                     {"timeframe": "3h"}, {"risk_per_trade": 10}, {"symbols": ["FOO"]}])
    def test_validation(self, s, bad):
        assert s.put(f"{API}/settings", json=bad).status_code == 422
        assert s.get(f"{API}/settings").json()["leverage"] == 3


# Position lifecycle + risk rules
class TestPositions:
    def test_lifecycle(self, s):
        s.post(f"{API}/account/reset")
        s.put(f"{API}/settings", json=DEFAULTS)
        bal0 = s.get(f"{API}/account").json()["balance"]
        out = inject("XRPUSDT", "long", noai=True)
        assert out.returncode == 0, out.stderr[-500:]
        pos = s.get(f"{API}/positions").json()
        xrp = [p for p in pos if p["symbol"] == "XRPUSDT"]
        assert len(xrp) == 1
        p = xrp[0]
        assert p["side"] == "long" and p["sl"] < p["entry_price"] < p["tp"] and p["leverage"] == 3
        acc = s.get(f"{API}/account").json()
        assert abs(acc["balance"] - (bal0 - p["fees"])) < 0.02
        # risk ~1% of equity ($500 paper account → ~$5; lot-size rounding allowed)
        risk = abs(p["entry_price"] - p["sl"]) * p["qty"]
        assert 4 < risk < 6, risk
        time.sleep(11)
        p2 = [x for x in s.get(f"{API}/positions").json() if x["id"] == p["id"]][0]
        assert p2["mark_price"] > 0
        bal1 = s.get(f"{API}/account").json()["balance"]
        r = s.post(f"{API}/positions/{p['id']}/close")
        assert r.status_code == 200
        t = r.json()
        assert t["reason"] == "MANUAL"
        exp_fee = p["fees"] + t["exit_price"] * t["qty"] * 0.00055
        assert abs(t["fees"] - exp_fee) < 0.01
        gross = (t["exit_price"] - t["entry_price"]) * t["qty"]
        assert abs(t["pnl"] - (gross - exp_fee)) < 0.02
        bal2 = s.get(f"{API}/account").json()["balance"]
        assert abs(bal2 - (bal1 + gross - t["exit_price"] * t["qty"] * 0.00055)) < 0.05
        assert abs(bal2 - (bal0 + t["pnl"])) < 0.05
        trades = s.get(f"{API}/trades").json()
        assert trades[0]["id"] == t["id"]
        assert not [x for x in s.get(f"{API}/positions").json() if x["id"] == p["id"]]
        assert s.post(f"{API}/positions/{p['id']}/close").status_code == 404

    def test_close_invalid(self, s):
        assert s.post(f"{API}/positions/abc/close").status_code == 400
        assert s.post(f"{API}/positions/0123456789abcdef01234567/close").status_code == 404

    def test_max_positions_and_duplicate(self, s):
        s.post(f"{API}/account/reset")
        s.put(f"{API}/settings", json={"max_positions": 1})
        assert inject("ETHUSDT", "long").returncode == 0
        assert len(s.get(f"{API}/positions").json()) == 1
        assert inject("AVAXUSDT", "short").returncode == 0
        assert len(s.get(f"{API}/positions").json()) == 1
        logs = s.get(f"{API}/dashboard").json()["logs"]
        assert any(l["level"] == "RISK" and "máximo de posiciones" in l["message"] for l in logs[:10])
        s.put(f"{API}/settings", json={"max_positions": 3})
        assert inject("ETHUSDT", "short").returncode == 0
        assert len(s.get(f"{API}/positions").json()) == 1
        logs = s.get(f"{API}/dashboard").json()["logs"]
        assert any(l["level"] == "RISK" and "ya existe" in l["message"] for l in logs[:10])
        s.put(f"{API}/settings", json=DEFAULTS)


# AI confirmation with Claude
class TestAI:
    def test_ai_signal(self, s):
        out = inject("LINKUSDT", "short", noai=False, timeout=120)
        assert out.returncode == 0, out.stderr[-800:]
        sig = [x for x in s.get(f"{API}/signals").json() if x["symbol"] == "LINKUSDT"][0]
        print(sig["ai_decision"], sig["ai_confidence"], sig["ai_risk"], sig["ai_reasoning"], sig["executed"], sig["note"])
        assert sig["ai_decision"] in ("APROBADA", "RECHAZADA"), sig
        assert 0 <= sig["ai_confidence"] <= 100 and len(sig["ai_reasoning"]) > 10
        exp = sig["ai_decision"] == "APROBADA" and sig["ai_confidence"] >= 60
        assert sig["executed"] == exp


# Backtest
class TestBacktest:
    def test_backtest(self, s):
        r = s.post(f"{API}/backtest", json={"symbol": "BTCUSDT", "strategy": "all", "timeframe": "1h"})
        assert r.status_code == 200
        d = r.json()
        for k in ("return_pct", "total_trades", "win_rate", "profit_factor", "max_drawdown", "equity_curve", "trades"):
            assert k in d
        assert len(d["equity_curve"]) > 10

    def test_backtest_invalid(self, s):
        assert s.post(f"{API}/backtest", json={"symbol": "FOO", "strategy": "all", "timeframe": "1h"}).status_code == 400


# Reset + logs
class TestReset:
    def test_reset_and_logs(self, s):
        r = s.post(f"{API}/account/reset")
        assert r.status_code == 200 and r.json()["balance"] == 500
        d = s.get(f"{API}/dashboard").json()
        assert d["positions"] == [] and d["trades"] == [] and d["signals"] == []
        assert s.delete(f"{API}/logs").json()["ok"] is True
        assert len(s.get(f"{API}/dashboard").json()["logs"]) <= 1
