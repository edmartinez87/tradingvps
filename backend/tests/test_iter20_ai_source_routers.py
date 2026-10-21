# Iteration 20: AI source (Emergent universal key vs Google Gemini own key) + server.py split into routers (bybit/mode, ai, analysis)
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
PW = "BlackCat2233@"
ST = {}


def H():
    return {"Authorization": f"Bearer {ST['token']}"}


def put(body):
    return requests.put(f"{BASE_URL}/api/config", json=body, headers=H(), timeout=20)


@pytest.fixture(scope="module", autouse=True)
def _login():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": PW}, timeout=20)
    assert r.status_code == 200
    ST["token"] = r.json()["token"]
    yield
    put({"clear_gemini_api_key": True, "ai_source": "emergent", "ai_provider": "anthropic", "ai_model": "claude-sonnet-5-5", "gemini_model": "gemini-3.1-pro-preview"})


class TestAiSource:
    def test_config_exposes_choices(self):
        d = requests.get(f"{BASE_URL}/api/config", headers=H(), timeout=15).json()
        assert d["ai_sources"] == ["emergent", "gemini"]
        assert set(d["ai_models"]) == {"anthropic", "openai", "gemini"} and "claude-sonnet-5-5" in d["ai_models"]["anthropic"]
        assert "gemini-3.1-pro-preview" in d["gemini_models"] and d["gemini_key_url"].startswith("https://aistudio.google.com")
        assert {k: v for k, v in d["ai_active"].items() if k != "health"} == {"provider": "anthropic", "model": "claude-sonnet-5-5", "source": "emergent", "label": "Claude Sonnet 5.5"}
        assert "ai_api_key" not in d and "ai_key_source" not in d

    def test_gemini_requires_key(self):
        r = put({"ai_source": "gemini"})
        assert r.status_code == 422 and "API key de Google Gemini" in r.json()["detail"]

    def test_switch_to_gemini_and_status(self):
        d = put({"ai_source": "gemini", "gemini_api_key": "AIzaBogusKey1234567890", "gemini_model": "gemini-2.5-flash"}).json()
        assert d["ai_source"] == "gemini" and d["gemini_configured"] is True and d["gemini_api_key"].endswith("7890")
        assert {k: v for k, v in d["ai_active"].items() if k != "health"} == {"provider": "gemini", "model": "gemini-2.5-flash", "source": "gemini", "label": "Gemini 2.5 Flash"}
        for path in ("/api/dashboard", "/api/fx/dashboard"):
            s = requests.get(f"{BASE_URL}{path}", headers=H(), timeout=60).json()["status"]["ai"]
            assert s["source"] == "gemini" and s["label"] == "Gemini 2.5 Flash", path

    def test_gemini_bogus_key_friendly_error(self):
        r = requests.post(f"{BASE_URL}/api/ai/test", headers=H(), timeout=90)
        assert r.status_code == 424, r.text
        assert "API key inválida" in r.json()["detail"]
        r = requests.post(f"{BASE_URL}/api/fx/ai/test", headers=H(), timeout=90)
        assert r.status_code == 424 and "API key inválida" in r.json()["detail"]

    def test_test_with_unsaved_override_does_not_persist(self):
        r = requests.post(f"{BASE_URL}/api/ai/test", json={"ai_source": "emergent", "ai_provider": "anthropic", "ai_model": "claude-haiku-4-5-20251001"}, headers=H(), timeout=90)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] and d["source"] == "emergent" and d["model"] == "claude-haiku-4-5-20251001" and d["label"] == "Claude Haiku 4.5" and d["saved"] is False
        cfg = requests.get(f"{BASE_URL}/api/config", headers=H(), timeout=15).json()
        assert cfg["ai_source"] == "gemini" and cfg["ai_active"]["model"] == "gemini-2.5-flash"

    def test_masked_key_keeps_stored(self):
        d = put({"gemini_api_key": "••••••••7890", "gemini_model": "gemini-3.5-flash"}).json()
        assert d["gemini_configured"] is True and d["ai_active"]["model"] == "gemini-3.5-flash"
        r = requests.post(f"{BASE_URL}/api/ai/test", json={"ai_source": "gemini", "gemini_api_key": ""}, headers=H(), timeout=90)
        assert r.status_code == 424 and "API key inválida" in r.json()["detail"]

    def test_clear_key_falls_back_to_emergent(self):
        d = put({"clear_gemini_api_key": True}).json()
        assert d["ai_source"] == "emergent" and d["gemini_configured"] is False and d["gemini_api_key"] == ""
        assert d["ai_active"]["source"] == "emergent" and d["ai_active"]["model"] == "claude-sonnet-5-5"
        r = requests.post(f"{BASE_URL}/api/ai/test", headers=H(), timeout=90)
        assert r.status_code == 200 and r.json()["source"] == "emergent"

    def test_emergent_model_choice(self):
        d = put({"ai_source": "emergent", "ai_provider": "openai", "ai_model": "gpt-5.4-mini"}).json()
        assert {k: v for k, v in d["ai_active"].items() if k != "health"} == {"provider": "openai", "model": "gpt-5.4-mini", "source": "emergent", "label": "GPT 5.4 Mini"}
        d = put({"ai_provider": "anthropic", "ai_model": "claude-sonnet-5-5"}).json()
        assert d["ai_active"]["label"] == "Claude Sonnet 5.5"


class TestRouters:
    def test_bybit_and_mode(self):
        r = requests.post(f"{BASE_URL}/api/bybit/test", json={}, headers=H(), timeout=20)
        assert r.status_code == 400 and "API key" in r.json()["detail"]
        d = requests.get(f"{BASE_URL}/api/mode", headers=H(), timeout=30).json()
        assert d["mode"] in ("paper", "live") and {c["key"] for c in d["checks"]} == {"keys", "verified", "stopped", "flat", "plan"}
        assert requests.post(f"{BASE_URL}/api/mode", json={"mode": "x", "confirm": ""}, headers=H(), timeout=20).status_code == 400

    def test_ai_routes(self):
        assert requests.get(f"{BASE_URL}/api/ai/optimize-all", headers=H(), timeout=20).json()["status"] in ("idle", "running", "done", "error")
        assert requests.post(f"{BASE_URL}/api/ai/advise", json={"scope": "nope"}, headers=H(), timeout=20).status_code == 400

    def test_analysis_routes(self):
        assert requests.get(f"{BASE_URL}/api/plan/checkin", headers=H(), timeout=30).json()["phase_key"]
        assert requests.post(f"{BASE_URL}/api/optimize", json={"symbol": "NOPE"}, headers=H(), timeout=20).status_code == 400
        assert requests.post(f"{BASE_URL}/api/backtest", json={"symbol": "BTCUSDT", "timeframe": "3m", "strategy": "all", "risk_per_trade": 1, "leverage": 3}, headers=H(), timeout=20).status_code == 400
        r = requests.post(f"{BASE_URL}/api/backtest", json={"symbol": "BTCUSDT", "timeframe": "1h", "strategy": "all", "risk_per_trade": 1, "leverage": 3}, headers=H(), timeout=120)
        assert r.status_code == 200 and r.json()["symbol"] == "BTCUSDT"

    def test_routes_require_auth(self):
        for path in ("/api/mode", "/api/ai/optimize-all", "/api/plan/checkin"):
            assert requests.get(f"{BASE_URL}{path}", timeout=15).status_code == 401, path
