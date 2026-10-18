# Iteration 2: growth plan, performance, account reset w/ body, lot-size backtest, regression
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
S = requests.Session()
PLAN = {"initial_capital": 500, "monthly_deposit": 0, "target_monthly": 1000, "scenario": "base"}


def post_plan(**kw):
    r = S.post(f"{BASE_URL}/api/plan", json={**PLAN, **kw}, timeout=120)
    return r


# Account
class TestAccount:
    def test_account_500(self):
        d = S.get(f"{BASE_URL}/api/account", timeout=30).json()
        assert d["initial_balance"] == 500
        assert abs(d["balance"] - 500) < 50

    def test_reset_with_body_then_default(self):
        r = S.post(f"{BASE_URL}/api/account/reset", json={"initial_balance": 750}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["initial_balance"] == 750 and r.json()["balance"] == 750
        assert S.get(f"{BASE_URL}/api/account", timeout=30).json()["initial_balance"] == 750
        r = S.post(f"{BASE_URL}/api/account/reset", json={}, timeout=30)
        assert r.status_code == 200 and r.json()["initial_balance"] == 500
        r = S.post(f"{BASE_URL}/api/account/reset", json={"initial_balance": 750}, timeout=30)
        r = S.post(f"{BASE_URL}/api/account/reset", timeout=30)  # no body
        assert r.status_code == 200, r.text
        assert r.json()["initial_balance"] == 500 and r.json()["balance"] == 500

    def test_reset_invalid(self):
        r = S.post(f"{BASE_URL}/api/account/reset", json={"initial_balance": 1}, timeout=30)
        assert r.status_code == 422
        assert S.get(f"{BASE_URL}/api/account", timeout=30).json()["initial_balance"] == 500


# Performance
class TestPerformance:
    def test_structure(self):
        r = S.get(f"{BASE_URL}/api/performance", timeout=30)
        assert r.status_code == 200
        d = r.json()
        for k in ("by_strategy", "by_symbol", "by_side", "by_reason"):
            assert isinstance(d[k], list)
        assert {"total", "executed", "by_decision"} <= set(d["signals"])
        assert isinstance(d["signals"]["by_decision"], dict)


# Plan
class TestPlan:
    def test_plan_base(self):
        t = time.time()
        r = post_plan()
        print("first plan call", round(time.time() - t, 2), "s")
        assert r.status_code == 200, r.text
        d = r.json()
        keys = [s["key"] for s in d["scenarios"]]
        assert keys == ["conservador", "base", "optimista", "backtest"]
        for s in d["scenarios"]:
            assert {"rate_pct", "months", "target_capital", "reachable"} <= set(s)
        assert d["selected"] == "base"
        p = d["projection"]
        assert p["reachable"] is True and isinstance(p["months"], int)
        assert abs(p["target_capital"] - 20833.33) < 1
        assert abs(p["income_at_target"] - 1000) < 1
        assert p["series"] and {"month", "capital", "profit", "withdraw", "phase"} <= set(p["series"][0])
        assert p["timeline"] and {"key", "name", "risk", "rule", "advance", "start_month", "start_capital"} <= set(p["timeline"][0])
        print("timeline keys", [x["key"] for x in p["timeline"]], "months", p["months"])
        bt = d["backtest"]
        assert len(bt["per_symbol"]) == 6
        assert isinstance(bt["by_strategy"], list)
        mc = bt["monte_carlo"]
        assert mc is not None
        for k in ("monthly_median", "monthly_p10", "monthly_p90", "prob_positive_month", "annual_median",
                  "prob_loss_year", "prob_dd_over_15", "median_max_dd"):
            assert k in mc
        assert mc["sims"] == 3000
        assert "trades_per_month" in bt and bt["concurrency_factor"] == 0.5
        print("backtest scenario", d["scenarios"][3], "mc", mc, "by_strategy", bt["by_strategy"])

    def test_plan_cached(self):
        t = time.time()
        assert post_plan().status_code == 200
        assert time.time() - t < 3

    def test_deposit_faster(self):
        a = post_plan().json()
        b = post_plan(monthly_deposit=100).json()
        assert b["projection"]["months"] < a["projection"]["months"]
        assert all(s["total_deposited"] > 0 for s in b["scenarios"] if s["reachable"])
        print("months 0 dep", a["projection"]["months"], "100 dep", b["projection"]["months"])

    def test_optimista(self):
        d = post_plan(scenario="optimista").json()
        assert d["selected"] == "optimista" and d["projection"]["rate_pct"] == 6.0

    def test_invalid_scenario_fallback(self):
        r = post_plan(scenario="xyz")
        assert r.status_code == 200 and r.json()["selected"] == "base"

    def test_validation(self):
        assert post_plan(initial_capital=10).status_code == 422
        assert post_plan(target_monthly=10).status_code == 422


# Backtest
class TestBacktest:
    def test_sol_1h(self):
        r = S.post(f"{BASE_URL}/api/backtest", json={"symbol": "SOLUSDT", "timeframe": "1h", "strategy": "all",
                                                    "risk_per_trade": 1, "leverage": 3}, timeout=120)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["initial"] == 500
        for k in ("expectancy_r", "rejected_lot", "strategy_stats"):
            assert k in d
        assert "r_multiples" not in d
        print("SOL", d["final_equity"], d["total_trades"], d["rejected_lot"])

    def test_btc_15m(self):
        r = S.post(f"{BASE_URL}/api/backtest", json={"symbol": "BTCUSDT", "timeframe": "15m", "strategy": "all",
                                                    "risk_per_trade": 1, "leverage": 3}, timeout=120)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["initial"] == 500
        print("BTC", d["final_equity"], d["total_trades"], d["rejected_lot"])


# Regression
class TestRegression:
    def test_dashboard(self):
        r = S.get(f"{BASE_URL}/api/dashboard", timeout=30)
        assert r.status_code == 200 and r.json()["account"]["initial_balance"] == 500

    def test_bot_start_stop_restore(self):
        was = S.get(f"{BASE_URL}/api/", timeout=30).json()["running"]
        assert S.post(f"{BASE_URL}/api/bot/stop", timeout=30).json()["running"] is False
        assert S.post(f"{BASE_URL}/api/bot/start", timeout=30).json()["running"] is True
        if not was:
            S.post(f"{BASE_URL}/api/bot/stop", timeout=30)

    def test_settings_put(self):
        cur = S.get(f"{BASE_URL}/api/settings", timeout=30).json()
        r = S.put(f"{BASE_URL}/api/settings", json=cur, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["symbols"] == cur["symbols"]
