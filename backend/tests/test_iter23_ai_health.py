"""Iteration 23 – AI provider health: classify auth/balance/rate/model/network errors, alert via Telegram 'system' + ERROR log in both bots,
expose status.ai.health (red banner/chip/settings), announce recovery. Run with `-n 0`."""
import os
import sys
import asyncio
import pytest
import requests

sys.path.insert(0, "/app/backend")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
FX = f"{BASE_URL}/api/fx"


@pytest.fixture(scope="module")
def s():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": "BlackCat2233@"}, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"login failed {r.status_code}")
    sess = requests.Session()
    sess.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return sess


class TestClassify:
    @pytest.mark.parametrize("msg,code", [
        ("AuthenticationError: Incorrect API key provided", "auth"),
        ("API key not valid. Please pass a valid API key.", "auth"),
        ("litellm.AuthenticationError: invalid x-api-key", "auth"),
        ("Error 401 Unauthorized", "auth"),
        ("Your credit balance is too low to access the Anthropic API", "balance"),
        ("RateLimitError: You exceeded your current quota, please check your plan and billing details (insufficient_quota)", "balance"),
        ("Budget has been exceeded! Current cost: 5.1, Max budget: 5.0", "balance"),
        ("HTTP 402 Payment Required", "balance"),
        ("RateLimitError: Too Many Requests 429", "rate"),
        ("RESOURCE_EXHAUSTED: rate limit", "rate"),
        ("NotFoundError: model `claude-x` does not exist", "model"),
        ("APIConnectionError: Connection refused", "network"),
        ("ReadTimeout: timed out", "network"),
        ("503 Service Unavailable / overloaded", "network"),
        ("Something weird happened", "other"),
    ])
    def test_codes(self, msg, code):
        import ai_advisor
        got, text = ai_advisor.classify(Exception(msg))
        assert got == code, (msg, got)
        assert text and (code != "balance" or "Add Balance" in text)
        assert ai_advisor.friendly_error(Exception(msg)) == text


class TestHealthStateMachine:
    def setup_method(self):
        import ai_advisor
        self.ai = ai_advisor
        self.events = []

        async def hook(event, h):
            self.events.append((event, dict(h)))
        ai_advisor.set_health_hook(hook)
        ai_advisor._health.update(ai_advisor._fresh_health())

    def teardown_method(self):
        self.ai.set_health_hook(None)
        self.ai._health.update(self.ai._fresh_health())

    def test_config_error_alerts_immediately_and_recovers(self):
        asyncio.run(self.ai._mark_failure(Exception("API key not valid")))
        h = self.ai.health()
        assert h["ok"] is False and h["code"] == "auth" and h["label"] == "API key inválida" and h["since"] and h["alerted_at"] and h["fails"] == 1
        assert [e for e, _ in self.events] == ["down"] and self.events[0][1]["code"] == "auth"
        asyncio.run(self.ai._mark_failure(Exception("API key not valid")))
        assert len(self.events) == 1, "no duplicate alert for the same outage"
        asyncio.run(self.ai._mark_ok())
        h = self.ai.health()
        assert h["ok"] is True and h["code"] is None and h["alerted_at"] is None and h["fails"] == 0 and h["last_ok"]
        assert [e for e, _ in self.events] == ["down", "up"] and self.events[1][1]["down_since"]
        assert self.ai.current()["health"]["ok"] is True

    def test_transient_errors_need_three_failures(self):
        for i in range(2):
            asyncio.run(self.ai._mark_failure(Exception("ReadTimeout: timed out")))
            assert self.ai.health()["ok"] is False and self.ai.health()["code"] == "network" and not self.events
        asyncio.run(self.ai._mark_failure(Exception("ReadTimeout: timed out")))
        assert [e for e, _ in self.events] == ["down"] and self.ai.health()["fails"] == 3
        asyncio.run(self.ai._mark_ok())
        assert [e for e, _ in self.events] == ["down", "up"]

    def test_transient_without_alert_recovers_silently(self):
        asyncio.run(self.ai._mark_failure(Exception("503 overloaded")))
        asyncio.run(self.ai._mark_ok())
        assert self.events == [] and self.ai.health()["ok"] is True

    def test_long_outage_alerts_even_with_few_calls(self):
        from datetime import datetime, timezone, timedelta
        asyncio.run(self.ai._mark_failure(Exception("503 overloaded")))
        self.ai._health["since"] = (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat()
        asyncio.run(self.ai._mark_failure(Exception("503 overloaded")))
        assert [e for e, _ in self.events] == ["down"]

    def test_configure_change_resets_but_keeps_recovery_announcement(self):
        cfg = dict(self.ai._cfg)
        try:
            asyncio.run(self.ai._mark_failure(Exception("API key not valid")))
            assert self.ai.health()["ok"] is False and len(self.events) == 1
            self.ai.configure("new-key", cfg["provider"], cfg["model"], "gemini")
            h = self.ai.health()
            assert h["ok"] is True and h["error"] is None and h["alerted_at"] is None and h["recovery_pending"] is True and h["since"]
            # a different failure on the new config alerts again
            asyncio.run(self.ai._mark_failure(Exception("Your credit balance is too low")))
            assert [e for e, _ in self.events] == ["down", "down"] and self.events[1][1]["code"] == "balance"
            asyncio.run(self.ai._mark_ok())
            assert [e for e, _ in self.events] == ["down", "down", "up"] and self.ai.health()["recovery_pending"] is False
            # unrelated configure (same key/model) does not touch the state
            asyncio.run(self.ai._mark_failure(Exception("timed out")))
            self.ai.configure("new-key", cfg["provider"], cfg["model"], "gemini")
            assert self.ai.health()["ok"] is False and self.ai.health()["fails"] == 1
        finally:
            self.ai.configure(cfg["api_key"], cfg["provider"], cfg["model"], cfg["source"])

    def test_probe_chats_do_not_affect_health(self):
        c = self.ai._chat("sys", "ping", {"api_key": "other", "provider": "gemini", "model": "gemini-2.5-flash", "source": "gemini"})
        assert c._probe is True
        assert self.ai._chat("sys", "ping")._probe is False
        assert self.ai._chat("sys", "ping", dict(self.ai._cfg))._probe is False


class TestEndToEnd:
    """Bogus Gemini key → the forced news refresh fails with an auth error → health down, ERROR logs in both bots; restoring Emergent + a
    successful ping announces the recovery."""

    def test_bogus_key_triggers_alert_and_recovery(self, s):
        orig = s.get(f"{BASE_URL}/api/config", timeout=30).json()
        try:
            r = s.put(f"{BASE_URL}/api/config", json={"ai_source": "gemini", "gemini_api_key": "AIzaBogusKeyForHealthTest000", "gemini_model": "gemini-2.5-flash"}, timeout=30)
            assert r.status_code == 200 and r.json()["ai_active"]["source"] == "gemini" and r.json()["ai_active"]["health"]["ok"] is True
            r = s.post(f"{BASE_URL}/api/news/refresh", timeout=120)
            assert r.status_code == 424, r.text
            st = s.get(f"{BASE_URL}/api/dashboard", timeout=30).json()
            h = st["status"]["ai"]["health"]
            assert h["ok"] is False and h["code"] in ("auth", "other") and h["error"] and h["since"]
            assert h["alerted_at"], f"config-type error must alert immediately: {h}"
            logs = [l["message"] for l in st["logs"][:30]]
            assert any("IA sin servicio" in m for m in logs), logs[:5]
            fx_logs = [l["message"] for l in s.get(f"{FX}/dashboard", timeout=30).json()["logs"][:30]]
            assert any("IA sin servicio" in m for m in fx_logs)
            assert s.get(f"{FX}/dashboard", timeout=30).json()["status"]["ai"]["health"]["ok"] is False
            assert s.get(f"{BASE_URL}/api/config", timeout=30).json()["ai_active"]["health"]["ok"] is False
            # settings test endpoint with the active (broken) config reports the friendly error
            t = s.post(f"{BASE_URL}/api/ai/test", json={}, timeout=120)
            assert t.status_code in (200, 424)
            # fix the key → state resets (banner gone) with recovery pending; a successful call announces recovery
            r = s.put(f"{BASE_URL}/api/config", json={"clear_gemini_api_key": True}, timeout=30)
            h = r.json()["ai_active"]["health"]
            assert r.json()["ai_source"] == "emergent" and h["ok"] is True and h["recovery_pending"] is True
            t = s.post(f"{BASE_URL}/api/ai/test", json={}, timeout=120)
            assert t.status_code == 200, t.text
            st = s.get(f"{BASE_URL}/api/dashboard", timeout=30).json()
            assert st["status"]["ai"]["health"]["ok"] is True and st["status"]["ai"]["health"]["recovery_pending"] is False
            logs = [l["message"] for l in st["logs"][:30]]
            assert any("IA operativa de nuevo" in m for m in logs), logs[:5]
        finally:
            s.put(f"{BASE_URL}/api/config", json={"clear_gemini_api_key": True}, timeout=30)
            s.put(f"{BASE_URL}/api/config", json={"ai_source": "emergent", "ai_provider": orig["ai_provider"], "ai_model": orig["ai_model"]}, timeout=30)
