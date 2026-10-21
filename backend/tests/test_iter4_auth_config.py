# Iteration 4: auth gate, password change, config, AI test, telegram errors, auto-review, cron, regression
import os
import re
import pytest
import requests
import yaml

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
PW = "BlackCat2233@"
TMP = "TempPass2233@"
ST = {}


def _cron_secret():
    for line in open("/app/backend/.env"):
        if line.startswith("WEBHOOK_CRON_SECRET="):
            return line.split("=", 1)[1].strip().strip('"')


def H(tok=None):
    return {"Authorization": f"Bearer {tok or ST['token']}"}


def login(pw):
    return requests.post(f"{BASE_URL}/api/auth/login", json={"password": pw}, timeout=20)


@pytest.fixture(scope="module", autouse=True)
def _token():
    if "token" not in ST:
        r = login(PW)
        if r.status_code == 200:
            ST["token"] = r.json()["token"]


# ---- AUTH ----
class TestAuth:
    def test_root_public(self):
        r = requests.get(f"{BASE_URL}/api/", timeout=15)
        assert r.status_code == 200 and r.json()["mode"] == "PAPER"

    def test_dashboard_no_token(self):
        assert requests.get(f"{BASE_URL}/api/dashboard", timeout=15).status_code == 401

    def test_login_wrong(self):  # 1 wrong attempt
        r = login("wrong")
        assert r.status_code == 401
        assert "Intentos restantes" in r.json()["detail"]

    def test_login_ok(self):
        r = login(PW)
        assert r.status_code == 200
        ST["token"] = r.json()["token"]
        assert isinstance(ST["token"], str) and len(ST["token"]) > 20

    def test_with_token(self):
        assert requests.get(f"{BASE_URL}/api/dashboard", headers=H(), timeout=30).status_code == 200
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=H(), timeout=15)
        assert r.status_code == 200 and r.json()["ok"] is True

    def test_garbage_token(self):
        r = requests.get(f"{BASE_URL}/api/dashboard", headers=H("garbage.token.x"), timeout=15)
        assert r.status_code == 401


# ---- PASSWORD CHANGE ----
class TestPassword:
    def test_wrong_current(self):
        r = requests.post(f"{BASE_URL}/api/auth/password", json={"current": "wrong", "new": "Nueva12345"}, headers=H(), timeout=15)
        assert r.status_code == 401

    def test_short_new(self):
        r = requests.post(f"{BASE_URL}/api/auth/password", json={"current": PW, "new": "short"}, headers=H(), timeout=15)
        assert r.status_code == 422

    def test_change_and_restore(self):
        old = ST["token"]
        r = requests.post(f"{BASE_URL}/api/auth/password", json={"current": PW, "new": TMP}, headers=H(), timeout=15)
        assert r.status_code == 200
        new = r.json()["token"]
        r_old = requests.get(f"{BASE_URL}/api/auth/me", headers=H(old), timeout=15)
        assert r_old.status_code == 401 and "Sesión cerrada" in r_old.json()["detail"]
        assert requests.get(f"{BASE_URL}/api/auth/me", headers=H(new), timeout=15).status_code == 200
        r2 = login(TMP)
        assert r2.status_code == 200
        # restore
        r3 = requests.post(f"{BASE_URL}/api/auth/password", json={"current": TMP, "new": PW}, headers=H(r2.json()["token"]), timeout=15)
        assert r3.status_code == 200
        r4 = login(PW)
        assert r4.status_code == 200
        ST["token"] = r4.json()["token"]


# ---- CONFIG ----
class TestConfig:
    def put(self, body):
        return requests.put(f"{BASE_URL}/api/config", json=body, headers=H(), timeout=15)

    def test_get_defaults(self):
        d = requests.get(f"{BASE_URL}/api/config", headers=H(), timeout=15).json()
        assert d["ai_provider"] == "anthropic" and d["ai_model"] == "claude-sonnet-5-5"
        assert d["ai_source"] == "emergent" and d["gemini_api_key"] == "" and d["gemini_configured"] is False
        assert d["ai_active"]["source"] == "emergent" and d["ai_active"]["label"] == "Claude Sonnet 5.5"
        assert d["telegram_enabled"] is False and d["telegram_ready"] is False
        assert set(d["telegram_alerts"]) == {"orders", "ai", "daily", "plan", "review", "news"}
        assert d["auto_review_enabled"] is True and d["auto_review_frequency"] == "weekly"
        assert d["auto_review_day"] == 0 and d["auto_review_apply"] is True
        assert d["ai_providers"] == ["anthropic", "openai", "gemini"] and d["ai_sources"] == ["emergent", "gemini"]
        assert "password_hash" not in d and "token_version" not in d

    def test_gemini_key_masking(self):
        d = self.put({"gemini_api_key": "AIza-test-1234567890abcdef"}).json()
        assert d["gemini_configured"] is True and d["ai_source"] == "emergent"
        assert d["gemini_api_key"].endswith("cdef") and "1234567890" not in d["gemini_api_key"]
        d = self.put({"gemini_api_key": ""}).json()
        assert d["gemini_configured"] is True
        d = self.put({"clear_gemini_api_key": True}).json()
        assert d["gemini_configured"] is False and d["gemini_api_key"] == ""

    def test_bad_provider(self):
        assert self.put({"ai_provider": "foo"}).status_code == 422
        assert self.put({"ai_source": "foo"}).status_code == 422
        assert self.put({"ai_source": "gemini"}).status_code == 422

    def test_autoreview_fields(self):
        d = self.put({"auto_review_frequency": "daily", "auto_review_day": 3, "auto_review_apply": False}).json()
        assert (d["auto_review_frequency"], d["auto_review_day"], d["auto_review_apply"]) == ("daily", 3, False)
        g = requests.get(f"{BASE_URL}/api/config", headers=H(), timeout=15).json()
        assert g["auto_review_day"] == 3
        assert self.put({"auto_review_frequency": "monthly"}).status_code == 422
        assert self.put({"auto_review_day": 9}).status_code == 422
        d = self.put({"auto_review_frequency": "weekly", "auto_review_day": 0, "auto_review_apply": True}).json()
        assert (d["auto_review_frequency"], d["auto_review_day"], d["auto_review_apply"]) == ("weekly", 0, True)

    def test_telegram_fields(self):
        d = self.put({"telegram_chat_id": "123456", "telegram_alerts": {"orders": False}}).json()
        assert d["telegram_chat_id"] == "123456"
        assert d["telegram_alerts"] == {"orders": False, "ai": True, "daily": True, "plan": True, "review": True, "news": True}
        d = self.put({"telegram_chat_id": "", "telegram_alerts": {"orders": True}}).json()
        assert d["telegram_chat_id"] == "" and d["telegram_alerts"]["orders"] is True


# ---- AI TEST ----
class TestAi:
    def test_ai_ping_ok(self):
        r = requests.post(f"{BASE_URL}/api/ai/test", headers=H(), timeout=90)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is True and d["reply"] and d["provider"] == "anthropic" and d["model"] == "claude-sonnet-5-5" and d["source"] == "emergent"

    def test_ai_bogus_gemini_key_then_restore(self):
        requests.put(f"{BASE_URL}/api/config", json={"ai_source": "gemini", "gemini_api_key": "AIzaBogusKey123456789"}, headers=H(), timeout=15)
        try:
            r = requests.post(f"{BASE_URL}/api/ai/test", headers=H(), timeout=90)
            ST["bogus_status"] = r.status_code
            assert r.status_code == 424 and "Error IA" in r.json()["detail"], r.text
        finally:
            d = requests.put(f"{BASE_URL}/api/config", json={"clear_gemini_api_key": True}, headers=H(), timeout=15).json()
            assert d["ai_source"] == "emergent" and d["gemini_configured"] is False
        r = requests.post(f"{BASE_URL}/api/ai/test", headers=H(), timeout=90)
        assert r.status_code == 200 and r.json()["ok"] is True


# ---- TELEGRAM (unconfigured) ----
class TestTelegram:
    def test_chats_empty(self):
        r = requests.post(f"{BASE_URL}/api/telegram/chats", json={"token": ""}, headers=H(), timeout=20)
        assert r.status_code == 400 and "Introduce el token" in r.json()["detail"]

    def test_chats_bad(self):
        r = requests.post(f"{BASE_URL}/api/telegram/chats", json={"token": "123:badtoken"}, headers=H(), timeout=30)
        assert r.status_code == 424

    def test_send_unconfigured(self):
        r = requests.post(f"{BASE_URL}/api/telegram/test", headers=H(), timeout=20)
        assert r.status_code == 424


# ---- AUTO REVIEW (1 real call) ----
class TestAutoReview:
    def test_run_now(self):
        before = requests.get(f"{BASE_URL}/api/settings", headers=H(), timeout=15).json()
        r = requests.post(f"{BASE_URL}/api/ai/auto-review", headers=H(), timeout=180)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("summary", "changes", "notes", "applied", "previous", "ran_at"):
            assert k in d
        assert d["summary"]
        print("APPLIED:", d["applied"])
        if d["applied"]:
            body = {k: v for k, v in before.items() if k != "bot_running"}
            rr = requests.put(f"{BASE_URL}/api/settings", json=body, headers=H(), timeout=15)
            assert rr.status_code == 200
        g = requests.get(f"{BASE_URL}/api/config", headers=H(), timeout=15).json()
        assert g["auto_review_last_at"] == d["ran_at"] and g["auto_review_last_summary"]
        s = requests.get(f"{BASE_URL}/api/settings", headers=H(), timeout=15).json()
        assert s["symbols"] == before["symbols"] and s["risk_per_trade"] == before["risk_per_trade"]


# ---- CRON ----
class TestCron:
    def test_no_auth(self):
        r = requests.post(f"{BASE_URL}/api/cron/ai-review", json={"event": "x"}, timeout=15)
        assert r.status_code == 401

    def test_wrong_secret(self):
        r = requests.post(f"{BASE_URL}/api/cron/ai-review", json={"event": "x"}, headers=H("nope"), timeout=15)
        assert r.status_code == 401

    def test_valid_and_duplicate(self):
        h = {"Authorization": f"Bearer {_cron_secret()}"}
        import uuid
        body = {"event": "schedule.triggered", "run_id": f"qa-run-{uuid.uuid4().hex[:8]}"}
        r = requests.post(f"{BASE_URL}/api/cron/ai-review", json=body, headers=h, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["accepted"] is True and set(d) == {"accepted", "scheduled", "scheduled_fx"}
        r2 = requests.post(f"{BASE_URL}/api/cron/ai-review", json=body, headers=h, timeout=15)
        assert r2.json() == {"accepted": True, "duplicate": True}

    def test_invalid_json(self):
        h = {"Authorization": f"Bearer {_cron_secret()}", "Content-Type": "application/json"}
        r = requests.post(f"{BASE_URL}/api/cron/ai-review", data="{not json", headers=h, timeout=15)
        assert r.status_code == 400

    def test_crons_yaml(self):
        y = yaml.safe_load(open("/app/.emergent/crons.yml"))
        crons = {c["name"]: c for c in y["crons"]}
        assert set(crons) == {"ai-review-daily", "walk-forward-weekly", "weekly-summary"}
        assert crons["ai-review-daily"]["cron"] == "0 8 * * *" and crons["walk-forward-weekly"]["cron"] == "0 7 * * 1" and crons["weekly-summary"]["cron"] == "0 20 * * 0"
        for name, ep in (("ai-review-daily", "ai-review"), ("walk-forward-weekly", "walk-forward"), ("weekly-summary", "weekly-summary")):
            assert crons[name]["endpoint"] == f"{{{{BASE_URL}}}}/api/cron/{ep}" and crons[name]["method"] == "POST" and crons[name]["enabled"] is True


# ---- REGRESSION ----
class TestRegression:
    def test_settings_put(self):
        s = requests.get(f"{BASE_URL}/api/settings", headers=H(), timeout=15).json()
        r = requests.put(f"{BASE_URL}/api/settings", json={k: v for k, v in s.items() if k != "bot_running"}, headers=H(), timeout=15)
        assert r.status_code == 200 and r.json()["risk_per_trade"] == s["risk_per_trade"]

    def test_optimize(self):
        r = requests.post(f"{BASE_URL}/api/optimize", json={"symbol": "SOLUSDT"}, headers=H(), timeout=120)
        assert r.status_code == 200 and r.json()["symbol"] == "SOLUSDT"

    def test_plan_checkin_backtest(self):
        s = requests.get(f"{BASE_URL}/api/settings", headers=H(), timeout=15).json()
        r = requests.post(f"{BASE_URL}/api/plan", json={"initial_capital": 500, "target_monthly": s["plan_target_monthly"],
                          "monthly_deposit": s["plan_monthly_deposit"], "scenario": s["plan_scenario"]}, headers=H(), timeout=120)
        assert r.status_code == 200, r.text
        assert requests.get(f"{BASE_URL}/api/plan/checkin", headers=H(), timeout=30).status_code == 200
        r = requests.post(f"{BASE_URL}/api/backtest", json={"symbol": "BTCUSDT", "timeframe": "1h", "strategy": "all",
                          "risk_per_trade": 1.0, "leverage": 3}, headers=H(), timeout=120)
        assert r.status_code == 200, r.text

    def test_bot_stop_start(self):
        assert requests.post(f"{BASE_URL}/api/bot/stop", headers=H(), timeout=15).json()["running"] is False
        assert requests.post(f"{BASE_URL}/api/bot/start", headers=H(), timeout=15).json()["running"] is True
        acc = requests.get(f"{BASE_URL}/api/account", headers=H(), timeout=15).json()
        assert acc["initial_balance"] == 500.0
