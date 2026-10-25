# Iteration 7: risk profiles (/api/profile, /api/meta), disabled_strategies, signal_mode, new strategies, global AI optimization job
# Run serially: tests share the single settings document
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
PASSWORD = "BlackCat2233@"
S = requests.Session()
BASE6 = {"BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "AVAXUSDT", "LINKUSDT"}


@pytest.fixture(scope="module", autouse=True)
def auth():
    r = S.post(f"{BASE_URL}/api/auth/login", json={"password": PASSWORD}, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"login failed {r.status_code}")
    S.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    yield
    S.post(f"{BASE_URL}/api/profile", json={"level": 0}, timeout=30)
    S.put(f"{BASE_URL}/api/settings", json={"symbol_params": {}}, timeout=30)


def profile(level):
    return S.post(f"{BASE_URL}/api/profile", json={"level": level}, timeout=30)


def dash():
    return S.get(f"{BASE_URL}/api/dashboard", timeout=60).json()


# Meta
class TestMeta:
    def test_meta(self):
        d = S.get(f"{BASE_URL}/api/meta", timeout=30).json()
        assert len(d["strategies"]) == 8 and "all" in d["strategies"]
        assert {"supertrend_momentum", "ema_pullback", "multi_horizon", "double_divergence"} <= set(d["strategies"])
        assert d["signal_modes"] == ["strict", "relaxed", "minimal"]
        assert set(d["mode_info"]) == {"strict", "relaxed", "minimal"}
        assert [p["level"] for p in d["profiles"]] == [0, 1, 2, 3, 4]
        for p in d["profiles"]:
            for k in ("level", "name", "activity", "tagline", "warning", "settings"):
                assert k in p


# Profiles
class TestProfiles:
    def test_level2(self):
        r = profile(2)
        assert r.status_code == 200
        d = r.json(); s = d["settings"]
        assert len(s["symbols"]) == 10 and s["timeframe"] == "1h" and s["signal_mode"] == "relaxed"
        assert s["risk_per_trade"] == 1.5 and s["max_positions"] == 5 and s["leverage"] == 5 and s["daily_loss_limit"] == 8
        assert s["disabled_strategies"] == [] and s["risk_profile"] == 2 and d["profile_active"] == 2
        assert dash()["profile_active"] == 2

    def test_level3(self):
        d = profile(3).json(); s = d["settings"]
        assert len(s["symbols"]) == 12 and s["timeframe"] == "15m" and s["htf_filter"] is False
        assert s["ai_min_confidence"] == 40 and s["risk_per_trade"] == 2 and s["max_positions"] == 6
        assert d["profile_active"] == 3

    def test_level4(self):
        d = profile(4).json(); s = d["settings"]
        assert s["ai_enabled"] is False and s["risk_per_trade"] == 3 and s["max_positions"] == 8
        assert s["leverage"] == 10 and s["signal_mode"] == "minimal" and d["profile_active"] == 4

    def test_level5_invalid(self):
        assert profile(5).status_code == 422
        assert profile(-1).status_code == 422

    def test_level0_restore(self):
        d = profile(0).json(); s = d["settings"]
        assert set(s["symbols"]) == BASE6 and s["signal_mode"] == "strict"
        assert s["risk_per_trade"] == 1.0 and s["max_positions"] == 3 and s["leverage"] == 3 and s["daily_loss_limit"] == 5
        assert set(s["disabled_strategies"]) == {"supertrend_momentum", "ema_pullback"}
        assert d["profile_active"] == 0 and dash()["profile_active"] == 0


# Settings: disabled_strategies & signal_mode
class TestSettingsStrategies:
    def test_disable_one_custom(self):
        r = S.put(f"{BASE_URL}/api/settings", json={"strategy": "all", "disabled_strategies": ["ema_pullback"]}, timeout=30)
        assert r.status_code == 200
        assert r.json()["disabled_strategies"] == ["ema_pullback"]
        assert dash()["profile_active"] is None

    def test_disable_all_422(self):
        r = S.put(f"{BASE_URL}/api/settings", json={"disabled_strategies": ["trend_ema", "mean_reversion", "breakout_turtle", "supertrend_momentum", "ema_pullback", "multi_horizon", "double_divergence"]}, timeout=30)
        assert r.status_code == 422

    def test_invalid_mode_422(self):
        assert S.put(f"{BASE_URL}/api/settings", json={"signal_mode": "invalido"}, timeout=30).status_code == 422

    def test_filter_unknown(self):
        r = S.put(f"{BASE_URL}/api/settings", json={"disabled_strategies": ["all", "xxx", "trend_ema"]}, timeout=30)
        assert r.status_code == 200
        assert r.json()["disabled_strategies"] == ["trend_ema"]
        assert profile(0).json()["profile_active"] == 0


# New strategies in backtest + optimizer
class TestNewStrategies:
    @pytest.mark.parametrize("strat", ["supertrend_momentum", "ema_pullback"])
    def test_backtest(self, strat):
        r = S.post(f"{BASE_URL}/api/backtest", json={"symbol": "SOLUSDT", "strategy": strat, "timeframe": "1h", "risk_per_trade": 1, "leverage": 3}, timeout=120)
        assert r.status_code == 200, r.text
        d = r.json()
        print(strat, d.get("total_trades"), d.get("win_rate"), d.get("return_pct"))
        assert d["strategy"] == strat and d["total_trades"] > 0
        for k in ("win_rate", "profit_factor", "max_drawdown", "equity_curve", "trades"):
            assert k in d

    def test_optimize(self):
        r = S.post(f"{BASE_URL}/api/optimize", json={"symbol": "SOLUSDT"}, timeout=120)
        assert r.status_code == 200
        d = r.json()
        assert "best" in d and "baseline" in d and len(d["grid"]) == 54


# Global AI optimization job
class TestOptimizeAll:
    def test_job(self):
        r = S.post(f"{BASE_URL}/api/ai/optimize-all", timeout=30)
        assert r.status_code == 200 and r.json()["status"] == "running"
        assert S.post(f"{BASE_URL}/api/ai/optimize-all", timeout=30).status_code == 409
        st = None
        for _ in range(60):
            time.sleep(3)
            st = S.get(f"{BASE_URL}/api/ai/optimize-all", timeout=30).json()
            if st["status"] != "running":
                break
        assert st["status"] == "done", st
        res = st["result"]
        print("summary:", res["summary"][:300]); print("applied:", res["applied"]); print("notes:", res["notes"])
        assert isinstance(res["summary"], str) and res["summary"]
        for k in ("changes", "applied", "previous", "notes", "optimizer", "ran_at"):
            assert k in res
        assert isinstance(res["applied"], dict) and isinstance(res["notes"], list)
        syms = set(dash()["settings"]["symbols"]) if not res["applied"] else None
        assert len(res["optimizer"]) == 6
        for o in res["optimizer"]:
            for k in ("symbol", "best", "baseline", "grid", "timeframe"):
                assert k in o
        if res["applied"]:
            assert S.put(f"{BASE_URL}/api/settings", json=res["previous"], timeout=30).status_code == 200
        assert dash()["optimize_job"] == "done"
        _ = syms


# Regression
class TestRegression:
    def test_dashboard(self):
        d = dash()
        for k in ("settings", "account", "positions", "checkin"):
            assert k in d

    def test_advise_plan(self):
        r = S.post(f"{BASE_URL}/api/ai/advise", json={"scope": "plan"}, timeout=150)
        assert r.status_code == 200, r.text
        d = r.json()
        print("advise applied:", d["applied"])
        for k in ("summary", "applied", "previous"):
            assert k in d
        if d["applied"]:
            S.put(f"{BASE_URL}/api/settings", json=d["previous"], timeout=30)
