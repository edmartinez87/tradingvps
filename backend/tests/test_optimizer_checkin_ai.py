# Iteration 3: parameter optimizer, symbol_params, plan check-in, plan persistence, AI advisor, regression
# Run serially: pytest -n 0 (tests share the single settings document)
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
S = requests.Session()
ROW_KEYS = {"atr_period", "sl_atr", "tp_atr", "return_pct", "trades", "win_rate", "profit_factor",
            "max_drawdown", "expectancy_r", "sqn", "robust", "neighbors"}
_cache = {}


def put_settings(body):
    return S.put(f"{BASE_URL}/api/settings", json=body, timeout=30)


def get_settings():
    return S.get(f"{BASE_URL}/api/settings", timeout=30).json()


def optimize(sym="SOLUSDT"):
    t = time.time()
    r = S.post(f"{BASE_URL}/api/optimize", json={"symbol": sym}, timeout=90)
    return r, time.time() - t


@pytest.fixture(scope="module", autouse=True)
def restore():
    yield
    put_settings({"symbol_params": {}, "plan_phase": 0, "risk_per_trade": 1.0})
    S.post(f"{BASE_URL}/api/plan", json={"initial_capital": 500, "monthly_deposit": 0, "target_monthly": 1000, "scenario": "base"}, timeout=120)


# Optimizer
class TestOptimizer:
    def test_optimize_structure(self):
        put_settings({"symbol_params": {}})
        r, dt = optimize()
        assert r.status_code == 200, r.text
        print(f"optimize took {dt:.1f}s")
        d = r.json()
        _cache["opt"] = d
        assert d["symbol"] == "SOLUSDT" and d["combos"] == 54 and len(d["grid"]) == 54
        assert d["sl_grid"] == [1, 1.5, 2, 2.5, 3] and d["tp_grid"] == [2, 3, 4, 5, 6] and d["atr_grid"] == [10, 14, 20]
        for k in ("strategy", "timeframe", "candles", "baseline"):
            assert k in d
        assert d["applied"] is None
        for row in d["grid"]:
            assert ROW_KEYS <= set(row), set(row) ^ ROW_KEYS
            assert row["tp_atr"] >= 1.5 * row["sl_atr"]
            assert 1 <= row["neighbors"] <= 9
        if d["best"] is not None:
            assert d["best"] in d["grid"]
            assert d["best"]["trades"] >= 10 or all(x["trades"] < 10 for x in d["grid"])
        assert dt < 30

    def test_optimize_invalid_symbol(self):
        r, _ = optimize("FOOUSDT")
        assert r.status_code == 400


# symbol_params persistence + validator
class TestSymbolParams:
    def test_put_get_and_applied(self):
        p = {"sl_atr": 2.0, "tp_atr": 3.0, "atr_period": 20}
        r = put_settings({"symbol_params": {"SOLUSDT": p}})
        assert r.status_code == 200 and r.json()["symbol_params"]["SOLUSDT"] == p
        assert get_settings()["symbol_params"]["SOLUSDT"] == p
        r, _ = optimize()
        assert r.json()["applied"] == p

    def test_clear(self):
        r = put_settings({"symbol_params": {}})
        assert r.status_code == 200
        assert get_settings()["symbol_params"] == {}

    def test_invalid_dropped(self):
        r = put_settings({"symbol_params": {"SOLUSDT": {"sl_atr": 9, "tp_atr": 3, "atr_period": 14}, "FOOUSDT": {"sl_atr": 2}}})
        assert r.status_code == 200, r.text
        assert "SOLUSDT" not in get_settings()["symbol_params"]
        assert "FOOUSDT" not in get_settings()["symbol_params"]

    def test_non_numeric_param(self):
        r = put_settings({"symbol_params": {"SOLUSDT": {"sl_atr": "abc"}}})
        assert r.status_code in (200, 422), r.text


# Plan check-in
class TestCheckin:
    def test_checkin_fresh(self):
        d = S.get(f"{BASE_URL}/api/plan/checkin", timeout=30).json()
        assert d["phase"] == 0 and d["phase_key"] == "validacion" and d["ready_to_advance"] is False
        assert [p["key"] for p in d["phases"]] == ["validacion", "semilla", "crecimiento", "consolidacion", "ingreso"]
        for p in d["phases"]:
            for k in ("status", "criteria", "met", "total"):
                assert k in p
        crit = d["phases"][0]["criteria"]
        assert len(crit) == 4
        for c in crit:
            assert {"label", "value", "target", "kind", "met", "pct"} <= set(c)
        assert isinstance(d["warnings"], list)
        assert set(d["last_30d"]) >= {"trades", "pnl", "win_rate", "profit_factor", "return_pct"}
        assert isinstance(d["days_running"], int)
        assert isinstance(d["target_capital"], (int, float))
        assert isinstance(d["message"], str) and d["message"]
        print(d["message"])
        _cache["checkin"] = d

    def test_dashboard_has_checkin(self):
        d = S.get(f"{BASE_URL}/api/dashboard", timeout=30).json()
        assert d["checkin"]["phase_key"] == _cache["checkin"]["phase_key"]
        assert d["checkin"]["message"] == _cache["checkin"]["message"]

    def test_phase_advance_and_restore(self):
        r = put_settings({"plan_phase": 1, "risk_per_trade": 1.0})
        assert r.status_code == 200
        d = S.get(f"{BASE_URL}/api/plan/checkin", timeout=30).json()
        assert d["phase"] == 1
        assert d["phases"][0]["status"] == "done" and d["phases"][1]["status"] == "current"
        assert put_settings({"plan_phase": 7}).status_code == 422
        assert put_settings({"plan_phase": 0}).status_code == 200
        assert S.get(f"{BASE_URL}/api/plan/checkin", timeout=30).json()["phase"] == 0


# Plan persistence
class TestPlanPersist:
    def test_plan_persists(self):
        r = S.post(f"{BASE_URL}/api/plan", json={"initial_capital": 500, "monthly_deposit": 50, "target_monthly": 1200, "scenario": "optimista"}, timeout=120)
        assert r.status_code == 200, r.text
        s = get_settings()
        assert s["plan_scenario"] == "optimista" and s["plan_target_monthly"] == 1200 and s["plan_monthly_deposit"] == 50
        r = S.post(f"{BASE_URL}/api/plan", json={"initial_capital": 500, "monthly_deposit": 0, "target_monthly": 1000, "scenario": "base"}, timeout=120)
        assert r.status_code == 200
        s = get_settings()
        assert s["plan_scenario"] == "base" and s["plan_target_monthly"] == 1000 and s["plan_monthly_deposit"] == 0


# AI advisor (real Claude calls)
class TestAiAdvise:
    def _check(self, d):
        for k in ("summary", "changes", "notes", "applied", "previous"):
            assert k in d
        assert isinstance(d["summary"], str) and len(d["summary"]) > 10
        assert isinstance(d["changes"], dict) and isinstance(d["notes"], list)
        assert isinstance(d["applied"], dict) and isinstance(d["previous"], dict)
        assert set(d["previous"]) == set(d["applied"])
        print("AI summary:", d["summary"][:200], "| changes:", d["changes"], "| applied:", d["applied"])
        if d["applied"]:
            s = get_settings()
            for k, v in d["applied"].items():
                assert s[k] == v["despues"]
            assert s["risk_per_trade"] <= 5 and s["leverage"] <= 20
            assert put_settings(d["previous"]).status_code == 200
            s = get_settings()
            for k, v in d["previous"].items():
                assert s[k] == v

    def test_invalid_scope(self):
        r = S.post(f"{BASE_URL}/api/ai/advise", json={"scope": "xyz"}, timeout=30)
        assert r.status_code == 400

    def test_plan_scope(self):
        t = time.time()
        r = S.post(f"{BASE_URL}/api/ai/advise", json={"scope": "plan"}, timeout=150)
        print(f"plan advise {time.time()-t:.1f}s")
        assert r.status_code == 200, r.text
        self._check(r.json())

    def test_optimizer_scope(self):
        opt = _cache.get("opt") or optimize()[0].json()
        res = [{k: opt[k] for k in ("symbol", "best", "baseline", "timeframe")}]
        t = time.time()
        r = S.post(f"{BASE_URL}/api/ai/advise", json={"scope": "optimizer", "optimizer_results": res}, timeout=150)
        print(f"optimizer advise {time.time()-t:.1f}s")
        assert r.status_code == 200, r.text
        self._check(r.json())

    def test_ai_log(self):
        logs = S.get(f"{BASE_URL}/api/dashboard", timeout=30).json()["logs"]
        assert any(l["level"] == "AI_EVAL" and "IA:" in l["message"] for l in logs)


# Regression
class TestRegression:
    def test_backtest(self):
        r = S.post(f"{BASE_URL}/api/backtest", json={"symbol": "SOLUSDT", "timeframe": "1h", "strategy": "all", "risk_per_trade": 1, "leverage": 3}, timeout=90)
        assert r.status_code == 200, r.text
        assert "sqn" in r.json()

    def test_performance(self):
        assert S.get(f"{BASE_URL}/api/performance", timeout=30).status_code == 200

    def test_bot_start_stop(self):
        was = get_settings()["bot_running"]
        assert S.post(f"{BASE_URL}/api/bot/stop", timeout=30).json()["running"] is False
        assert S.post(f"{BASE_URL}/api/bot/start", timeout=30).json()["running"] is True
        if not was:
            S.post(f"{BASE_URL}/api/bot/stop", timeout=30)

    def test_account_500(self):
        assert S.get(f"{BASE_URL}/api/account", timeout=30).json()["initial_balance"] == 500
