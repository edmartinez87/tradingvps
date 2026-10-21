"""Iteration 19 – HotForex growth plan (pips/lots), daily AI auto-review for FX and weekly Telegram summary for FX.
Unit (plan helpers, FX weekly format) + API e2e (plan, checkin, settings, config isolation, auto-review, weekly, cron both bots)."""
import os
import sys
import time
import pytest
import requests

sys.path.insert(0, "/app/backend")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
FX = f"{BASE_URL}/api/fx"
SECRET = None
for line in open("/app/backend/.env"):
    if line.startswith("WEBHOOK_CRON_SECRET="):
        SECRET = line.strip().split("=", 1)[1]


@pytest.fixture(scope="module")
def s():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": "BlackCat2233@"}, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"login failed {r.status_code}")
    sess = requests.Session()
    sess.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return sess


# ---------- unit ----------
def test_unit_plan_core_parametrized():
    import plan as core
    from fx import plan as fx_plan
    from types import SimpleNamespace
    assert fx_plan.SCENARIOS["base"]["rate"] < core.SCENARIOS["base"]["rate"]
    bt = {"monte_carlo": {"monthly_median": 2.0}}
    req = {"initial_capital": 500, "monthly_deposit": 0, "target_monthly": 1000, "scenario": "base"}
    p = fx_plan.build_plan(req, bt)
    assert p["currency"] == "USD" and p["selected"] == "base" and [x["key"] for x in p["scenarios"]] == ["conservador", "base", "optimista", "backtest"]
    assert p["scenarios"][1]["rate_pct"] == 3.0 and p["projection"]["reachable"] and p["projection"]["rate_pct"] == 3.0
    c = core.build_plan(req, bt)
    assert "currency" not in c and c["scenarios"][1]["rate_pct"] == 4.0
    settings = SimpleNamespace(plan_target_monthly=1000.0, plan_phase=1, plan_scenario="base")
    acc = {"initial_balance": 500.0}
    summ = {"profit_factor": 1.4, "realized_pnl": 50, "total_trades": 10, "max_drawdown": 3.0, "equity": 550.0, "daily_paused": False}
    last30 = {"pnl": 50.0, "trades": 10, "win_rate": 50, "profit_factor": 1.4, "return_pct": 10}
    fxc = fx_plan.build_checkin(summ, acc, last30, settings, 5)
    assert fxc["phase_key"] == "semilla" and fxc["phases"][1]["criteria"][0]["label"] == "Equidad (USD)"
    cc = core.build_checkin(summ, acc, last30, settings, 4.0, 5)
    assert cc["phases"][1]["criteria"][0]["label"] == "Equidad (USDT)"
    assert fxc["target_capital"] > cc["target_capital"]  # lower monthly rate → more capital needed


def test_unit_summarize_and_fx_weekly_format():
    import plan as core
    from fx import weekly as fx_weekly
    from types import SimpleNamespace
    res = {"return_pct": 5.0, "total_trades": 12, "win_rate": 50.0, "profit_factor": 1.5, "expectancy_r": 0.2, "max_drawdown": 2.0, "rejected_lot": 1,
           "total_pips": 40.5, "avg_pips": 3.4, "weekend_closed": 2, "skipped_session": 0, "r_multiples": [1.0, -1.0] * 6,
           "strategy_stats": {"trend_ema": {"trades": 12, "wins": 6, "pnl": 10.0, "r_sum": 0.0, "gw": 30.0, "gl": 20.0}},
           "period_start": "2026-09-01T00:00:00+00:00", "period_end": "2026-10-01T00:00:00+00:00"}
    out = core.summarize([("EURUSD", res)], SimpleNamespace(max_positions=5, symbols=["EURUSD"], timeframe="1h", strategy="all", risk_per_trade=1.0),
                         ("total_pips", "avg_pips"))
    assert out["per_symbol"][0]["total_pips"] == 40.5 and out["by_strategy"][0]["strategy"] == "trend_ema" and out["total_trades"] == 12
    assert out["monte_carlo"] and out["days"] == 30.0
    w = {"mode": "PAPER", "equity": 510.0, "week_pnl": 10.0, "week_return_pct": 2.0, "total_return_pct": 2.0, "max_drawdown": 1.0,
         "week": {"trades": 3, "win_rate": 66.7, "profit_factor": 2.1, "fees": 0.9}, "best": [{"key": "EURUSD", "pnl": 8.0, "trades": 2, "win_rate": 100}],
         "worst": [], "by_strategy": [], "signals": {"total": 4, "by_decision": {"APROBADA": 3, "SESION": 1}}, "shadow": {"trades": 0, "filter_value": 0, "ai_trades": 0, "ai_value": 0},
         "plan": {"message": "Fase actual: Validación en paper", "warnings": [], "last_30d": {"pnl": 10.0, "trades": 3, "profit_factor": 2.1}, "days_running": 3},
         "news": None, "pips": 12.3, "shadow_supported": False}
    txt = fx_weekly.fmt(w)
    assert "Pips netos de la semana: <b>+12.3</b>" in txt and "USD" in txt and "USDT" not in txt and "operaciones sombra" not in txt
    assert "EURUSD +8.00 USD" in txt


# ---------- API ----------
def test_fx_settings_have_plan_fields(s):
    d = s.get(f"{FX}/settings", timeout=30).json()
    for k in ("plan_scenario", "plan_target_monthly", "plan_monthly_deposit", "plan_phase"):
        assert k in d
    assert s.put(f"{FX}/settings", json={"plan_target_monthly": 10}, timeout=30).status_code == 422
    assert s.put(f"{FX}/settings", json={"plan_phase": 9}, timeout=30).status_code == 422


def test_fx_plan_checkin_and_dashboard(s):
    c = s.get(f"{FX}/plan/checkin", timeout=30).json()
    assert c["phase_key"] in ("validacion", "semilla", "crecimiento", "consolidacion", "ingreso") and len(c["phases"]) == 5
    assert any(cr["label"] == "Equidad (USD)" for cr in c["phases"][1]["criteria"])
    d = s.get(f"{FX}/dashboard", timeout=30).json()
    assert d["checkin"]["phase_key"] == c["phase_key"] and "message" in d["checkin"]


def test_fx_plan_endpoint_persists_and_returns_pips(s):
    orig = s.get(f"{FX}/settings", timeout=30).json()
    try:
        r = s.post(f"{FX}/plan", json={"initial_capital": 500, "monthly_deposit": 25, "target_monthly": 800, "scenario": "conservador"}, timeout=240)
        assert r.status_code == 200, r.text
        p = r.json()
        assert p["currency"] == "USD" and p["selected"] == "conservador"
        keys = [x["key"] for x in p["scenarios"]]
        assert keys == ["conservador", "base", "optimista", "backtest"] and p["scenarios"][0]["rate_pct"] == 1.5
        bt = p["backtest"]
        assert "total_pips" in bt and "rejected_lot" in bt and bt["timeframe"] == orig["timeframe"]
        assert len(bt["per_symbol"]) == len(orig["symbols"]) and all("total_pips" in x and "avg_pips" in x for x in bt["per_symbol"])
        assert p["projection"]["timeline"][0]["key"] == "semilla" and p["phase_info"]["ingreso"]["risk"] == 1.5
        st = s.get(f"{FX}/settings", timeout=30).json()
        assert (st["plan_scenario"], st["plan_target_monthly"], st["plan_monthly_deposit"]) == ("conservador", 800.0, 25.0)
        # crypto plan settings untouched
        cs = s.get(f"{BASE_URL}/api/settings", timeout=30).json()
        assert not (cs["plan_scenario"] == "conservador" and cs["plan_target_monthly"] == 800.0 and cs["plan_monthly_deposit"] == 25.0)
        # unknown scenario falls back to base; cached second call is fast
        t = time.time()
        r = s.post(f"{FX}/plan", json={"initial_capital": 500, "monthly_deposit": 25, "target_monthly": 800, "scenario": "foo"}, timeout=240)
        assert r.json()["selected"] == "base" and time.time() - t < 5
    finally:
        s.put(f"{FX}/settings", json={k: orig[k] for k in ("plan_scenario", "plan_target_monthly", "plan_monthly_deposit", "plan_phase")}, timeout=30)


def test_fx_auto_review_config_isolated_from_crypto(s):
    crypto_before = s.get(f"{BASE_URL}/api/config", timeout=30).json()
    fx_before = s.get(f"{FX}/config", timeout=30).json()
    try:
        r = s.put(f"{FX}/config", json={"auto_review_enabled": False, "auto_review_frequency": "daily", "auto_review_apply": False}, timeout=30)
        assert r.status_code == 200, r.text
        c = r.json()
        assert c["auto_review_enabled"] is False and c["auto_review_frequency"] == "daily" and c["auto_review_apply"] is False
        cc = s.get(f"{BASE_URL}/api/config", timeout=30).json()
        assert (cc["auto_review_enabled"], cc["auto_review_frequency"], cc["auto_review_apply"]) == \
               (crypto_before["auto_review_enabled"], crypto_before["auto_review_frequency"], crypto_before["auto_review_apply"])
        assert s.put(f"{FX}/config", json={"auto_review_frequency": "monthly"}, timeout=30).status_code == 422
        assert s.put(f"{FX}/config", json={"auto_review_day": 7}, timeout=30).status_code == 422
    finally:
        s.put(f"{FX}/config", json={k: fx_before[k] for k in ("auto_review_enabled", "auto_review_frequency", "auto_review_day", "auto_review_apply")}, timeout=30)


def test_cron_ai_review_reports_both_bots():
    r = requests.post(f"{BASE_URL}/api/cron/ai-review", json={"run_id": f"qa19-{int(time.time())}"}, headers={"Authorization": f"Bearer {SECRET}"}, timeout=20)
    assert r.status_code == 200
    d = r.json()
    assert d["accepted"] is True and "scheduled" in d and "scheduled_fx" in d
    r = requests.post(f"{BASE_URL}/api/cron/weekly-summary", json={"run_id": f"qa19w-{int(time.time())}"}, headers={"Authorization": f"Bearer {SECRET}"}, timeout=20)
    assert r.json() == {"accepted": True, "scheduled": True, "scheduled_fx": True}


def test_fx_weekly_preview_and_send_without_telegram(s):
    r = s.get(f"{FX}/weekly-summary", timeout=60)
    assert r.status_code == 200, r.text
    w = r.json()
    assert w["text"].startswith("🏦 <b>HotForex AI</b>") and "Resumen semanal" in w["text"] and "pips" in w and "USDT" not in w["text"]
    assert "plan" in w and "last_sent_at" in w and w["shadow_supported"] is False
    cfg = s.get(f"{FX}/config", timeout=30).json()
    if not cfg.get("telegram_ready"):
        assert s.post(f"{FX}/weekly-summary/send", timeout=60).status_code == 424


def test_fx_auto_review_runs_with_claude(s):
    fx_before = s.get(f"{FX}/config", timeout=30).json()
    settings_before = s.get(f"{FX}/settings", timeout=30).json()
    crypto_last = s.get(f"{BASE_URL}/api/config", timeout=30).json()["auto_review_last_at"]
    try:
        s.put(f"{FX}/config", json={"auto_review_apply": False}, timeout=30)
        r = s.post(f"{FX}/ai/auto-review", timeout=240)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["summary"] and d["applied"] == {} and d["ran_at"]
        c = s.get(f"{FX}/config", timeout=30).json()
        assert c["auto_review_last_at"] == d["ran_at"] and c["auto_review_last_summary"] == d["summary"]
        assert s.get(f"{BASE_URL}/api/config", timeout=30).json()["auto_review_last_at"] == crypto_last
        logs = s.get(f"{FX}/dashboard", timeout=30).json()["logs"]
        assert any("Revisión automática:" in l["message"] for l in logs[:10])
        after = s.get(f"{FX}/settings", timeout=30).json()
        assert {k: after[k] for k in settings_before if k != "bot_running"} == {k: settings_before[k] for k in settings_before if k != "bot_running"}
    finally:
        s.put(f"{FX}/config", json={"auto_review_apply": fx_before["auto_review_apply"]}, timeout=30)


def test_fx_ai_advise_plan_scope(s):
    assert s.post(f"{FX}/ai/advise", json={"scope": "nope"}, timeout=30).status_code == 400
    r = s.post(f"{FX}/ai/advise", json={"scope": "plan"}, timeout=240)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["summary"] and "applied" in d and "previous" in d and isinstance(d["notes"], list)


def test_crypto_untouched(s):
    d = s.get(f"{BASE_URL}/api/dashboard", timeout=30).json()
    assert "checkin" in d and d["checkin"]["phases"][1]["criteria"][0]["label"] == "Equidad (USDT)"
    w = s.get(f"{BASE_URL}/api/weekly-summary", timeout=60).json()
    assert "USDT" in w["text"] and not w["text"].startswith("🏦")
