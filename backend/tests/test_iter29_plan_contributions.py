"""Iteration 29 – the plan check-in recognises real deposits as monthly contributions (`contributions` block, per calendar month, capital vs
plan) and the equity snapshots feed a deposit-adjusted curve. Run with `-n 0` (uses the HotForex paper account: deposits are withdrawn again
and the test rows removed)."""
import os
import sys
import asyncio
from datetime import datetime, timezone, timedelta
import pytest
import requests

sys.path.insert(0, "/app/backend")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
FX = f"{BASE_URL}/api/fx"


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


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def to_list(self, n):
        return self.rows[:n]


class _Col:
    def __init__(self, rows):
        self.rows = rows

    def find(self, flt=None, proj=None):
        return _Cursor([dict(r) for r in self.rows])


class _Db:
    def __init__(self, flows):
        self.cash_flows = _Col(flows)


class _Settings:
    def __init__(self, dep, target=1000.0, scenario="base"):
        self.plan_monthly_deposit = dep
        self.plan_target_monthly = target
        self.plan_scenario = scenario
        self.plan_phase = 0


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


class TestContributionsUnit:
    def test_months_targets_and_message(self):
        import plan
        now = datetime.now(timezone.utc)
        created = (now.replace(day=15) - timedelta(days=75)).isoformat()  # account started ~2.5 months ago
        this_month = now.strftime("%Y-%m")
        prev = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        flows = [{"ts": f"{prev}-10T10:00:00+00:00", "amount": 500.0}, {"ts": f"{prev}-20T10:00:00+00:00", "amount": -100.0},
                 {"ts": f"{this_month}-02T10:00:00+00:00", "amount": 200.0}]
        acc = {"created_at": created, "initial_balance": 1000.0, "net_deposits": 600.0}
        c = asyncio.run(plan.contributions(_Db(flows), acc, _Settings(500.0), 4.0, "USD"))
        assert c["target"] == 500.0 and c["currency"] == "USD" and 3 <= c["months_total"] <= 4
        by = {m["month"]: m for m in c["months"]}
        assert by[prev]["deposited"] == 500.0 and by[prev]["withdrawn"] == 100.0 and by[prev]["met"] is True and by[prev]["current"] is False
        assert by[this_month]["deposited"] == 200.0 and by[this_month]["met"] is False and by[this_month]["current"] is True
        assert c["this_month"]["month"] == this_month and c["months_met"] == 1
        assert c["total_deposited"] == 700.0 and c["total_withdrawn"] == 100.0 and c["net_deposits"] == 600.0
        assert c["expected_to_date"] == 500.0 * c["months_total"] and c["elapsed_months"] == 2
        assert c["expected_capital"] > 1000.0 + 2 * 500.0  # projection: deposits + compounding
        assert c["message"] == f"Este mes llevas $200.00 de $500.00 (faltan $300.00) · 1 de {c['months_total']} meses cumplidos"
        # month met
        flows.append({"ts": f"{this_month}-05T10:00:00+00:00", "amount": 300.0})
        c2 = asyncio.run(plan.contributions(_Db(flows), acc, _Settings(500.0), 4.0, "USD"))
        assert c2["this_month"]["met"] is True and c2["months_met"] == 2 and c2["message"].startswith("Aporte de este mes cumplido ($500.00 de $500.00)")
        # no monthly deposit in the plan
        c3 = asyncio.run(plan.contributions(_Db(flows), acc, _Settings(0.0), 4.0, "USD"))
        assert c3["target"] == 0 and c3["months_met"] == 0 and "no incluye aporte mensual" in c3["message"] and "+600.00 USD" in c3["message"]
        assert c3["expected_capital"] > 1000.0  # compounding only, no deposits
        c4 = asyncio.run(plan.contributions(_Db([]), acc, _Settings(0.0), 4.0, "USD"))
        assert c4["message"] == "El plan no incluye aporte mensual."
        c5 = asyncio.run(plan.contributions(_Db([]), {**acc, "created_at": _iso(3)}, _Settings(500.0), 0, "USD"))
        assert c5["elapsed_months"] == 0 and c5["expected_capital"] == 1000.0 and c5["months_total"] == 1

    def test_build_checkin_carries_contributions(self):
        import plan
        s = {"profit_factor": None, "realized_pnl": 0, "equity": 1250.0, "total_trades": 0, "max_drawdown": 0, "daily_paused": False}
        acc = {"initial_balance": 1000.0}
        contrib = {"target": 500.0, "expected_capital": 1200.0, "message": "x", "this_month": {"met": False}}
        out = plan.build_checkin(s, acc, {"pnl": 0, "trades": 0, "win_rate": 0, "profit_factor": None, "return_pct": 0}, _Settings(500.0), 4.0, 10, "USD", contrib)
        assert out["contributions"]["capital_vs_plan"] == 50.0 and out["contributions"]["target"] == 500.0
        assert plan.build_checkin(s, acc, {"pnl": 0, "trades": 0, "win_rate": 0, "profit_factor": None, "return_pct": 0}, _Settings(0.0), 4.0, 10)["contributions"] is None

    def test_weekly_prints_contributions(self):
        import weekly
        w = {"week": {"trades": 0, "win_rate": 0, "profit_factor": None, "fees": 0}, "equity": 1000, "week_pnl": 0, "week_return_pct": 0, "total_return_pct": 0, "max_drawdown": 0,
             "mode": "PAPER", "best": [], "worst": [], "by_strategy": [], "signals": {"total": 0, "by_decision": {}}, "shadow": {"trades": 0, "filter_value": 0, "ai_trades": 0, "ai_value": 0, "by_kind": {}},
             "plan": {"message": "ok", "last_30d": {"pnl": 1, "trades": 2, "profit_factor": None}, "days_running": 3, "warnings": [],
                      "contributions": {"target": 500.0, "total_deposited": 200.0, "total_withdrawn": 0, "message": "Este mes llevas $200.00 de $500.00 (faltan $300.00) · 0 de 1 meses cumplidos", "capital_vs_plan": -12.5}},
             "news": None}
        txt = weekly.format_weekly(w, "USD")
        assert "💰 Aportes: Este mes llevas $200.00 de $500.00 (faltan $300.00) · 0 de 1 meses cumplidos · capital -12.50 USD vs plan" in txt
        w["plan"]["contributions"] = {"target": 0, "total_deposited": 0, "total_withdrawn": 0, "message": "El plan no incluye aporte mensual.", "capital_vs_plan": 0}
        assert "💰 Aportes" not in weekly.format_weekly(w, "USD")
        w["plan"]["contributions"] = None
        assert "💰 Aportes" not in weekly.format_weekly(w, "USD")


class TestContributionsApi:
    def test_fx_checkin_tracks_paper_deposits(self, s):
        db = _mongo()
        settings0 = s.get(f"{FX}/settings", timeout=30).json()
        orig_dep = settings0["plan_monthly_deposit"]
        start = datetime.now(timezone.utc).isoformat()
        try:
            assert s.put(f"{FX}/settings", json={"plan_monthly_deposit": 500}, timeout=30).status_code == 200
            c = s.get(f"{FX}/plan/checkin", timeout=60).json()["contributions"]
            base_dep = c["this_month"]["deposited"]
            assert c["target"] == 500.0 and c["currency"] == "USD" and c["this_month"]["current"] is True and c["months"][-1]["month"] == c["this_month"]["month"]
            assert s.post(f"{FX}/account/cashflow", json={"amount": 300, "note": "iter29"}, timeout=30).status_code == 200
            c = s.get(f"{FX}/plan/checkin", timeout=60).json()["contributions"]
            assert abs(c["this_month"]["deposited"] - (base_dep + 300)) < 0.01 and c["total_deposited"] >= 300
            if base_dep + 300 < 500:
                assert c["this_month"]["met"] is False and c["message"].startswith(f"Este mes llevas ${base_dep + 300:,.2f} de $500.00")
            assert s.post(f"{FX}/account/cashflow", json={"amount": 200, "note": "iter29"}, timeout=30).status_code == 200
            ck = s.get(f"{FX}/plan/checkin", timeout=60).json()
            c = ck["contributions"]
            assert c["this_month"]["met"] is True and c["months_met"] >= 1 and c["message"].startswith("Aporte de este mes cumplido")
            assert "capital_vs_plan" in c and isinstance(c["expected_capital"], float)
            assert ck["phases"][ck["phase"]]["total"] == len(ck["phases"][ck["phase"]]["criteria"])  # contributions never block advancing
            dash = s.get(f"{FX}/dashboard", timeout=60).json()
            assert dash["checkin"]["contributions"]["this_month"]["met"] is True
            # withdrawals do not undo a fulfilled contribution but are reported
            assert s.post(f"{FX}/account/cashflow", json={"amount": -500, "note": "iter29"}, timeout=30).status_code == 200
            c = s.get(f"{FX}/plan/checkin", timeout=60).json()["contributions"]
            assert c["this_month"]["met"] is True and c["this_month"]["withdrawn"] >= 500 and c["total_withdrawn"] >= 500
            w = s.get(f"{FX}/weekly-summary", timeout=60).json()
            assert "💰 Aportes: Aporte de este mes cumplido" in w["text"]
        finally:
            s.put(f"{FX}/settings", json={"plan_monthly_deposit": orig_dep}, timeout=30)
            db.fx_cash_flows.delete_many({"note": "iter29", "ts": {"$gte": start}})
            db.fx_account.update_one({"_id": "main"}, {"$inc": {}})
        a = s.get(f"{FX}/dashboard", timeout=60).json()["account"]
        assert a["net_deposits"] == 0.0

    def test_crypto_checkin_has_contributions_and_equity_snapshots_carry_deposits(self, s):
        ck = s.get(f"{API}/plan/checkin", timeout=60).json()
        assert "contributions" in ck
        if ck["contributions"] is not None:
            assert set(ck["contributions"]) >= {"target", "months", "this_month", "months_met", "months_total", "total_deposited", "expected_capital", "capital_vs_plan", "message"}
        rows = s.get(f"{API}/dashboard", timeout=60).json()["equity"]
        assert rows and "equity" in rows[-1] and "net_deposits" in rows[-1]
