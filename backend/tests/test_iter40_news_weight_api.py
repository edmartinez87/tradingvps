# Iter40: ai_news_weight settings API (FX only), performance shadow.ai_by_news_risk, review keys
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")


@pytest.fixture(scope="module")
def s():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": "BlackCat2233@"})
    if r.status_code != 200:
        pytest.skip("login failed")
    ses = requests.Session()
    ses.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    yield ses
    ses.put(f"{BASE_URL}/api/fx/settings", json={"ai_news_weight": "normal"})


# Settings: default, persist, validation
def test_fx_settings_news_weight(s):
    r = s.get(f"{BASE_URL}/api/fx/settings")
    assert r.status_code == 200
    assert r.json().get("ai_news_weight") in ("normal", "bajo")
    r = s.put(f"{BASE_URL}/api/fx/settings", json={"ai_news_weight": "bajo"})
    assert r.status_code == 200
    assert s.get(f"{BASE_URL}/api/fx/settings").json()["ai_news_weight"] == "bajo"
    r = s.put(f"{BASE_URL}/api/fx/settings", json={"ai_news_weight": "alto"})
    assert r.status_code == 422
    assert s.get(f"{BASE_URL}/api/fx/settings").json()["ai_news_weight"] == "bajo"
    r = s.put(f"{BASE_URL}/api/fx/settings", json={"ai_news_weight": "normal"})
    assert r.status_code == 200
    assert s.get(f"{BASE_URL}/api/fx/settings").json()["ai_news_weight"] == "normal"


# Crypto settings untouched
def test_crypto_settings_no_news_weight(s):
    r = s.get(f"{BASE_URL}/api/settings")
    assert r.status_code == 200
    assert "ai_news_weight" not in r.json()


# Performance shadow breakdown
def test_performance_shadow_by_news_risk(s):
    r = s.get(f"{BASE_URL}/api/fx/performance")
    assert r.status_code == 200
    sh = r.json().get("shadow") or {}
    assert isinstance(sh.get("ai_by_news_risk"), list)


# Review keys (in-process)
def test_review_keys():
    import sys
    sys.path.insert(0, "/app/backend")
    from fx import review as fxr
    import review
    import ai_advisor
    assert "ai_news_weight" in fxr.ALLOWED_AI_KEYS
    assert "ai_news_weight" not in review.ALLOWED_AI_KEYS
    assert review.LABELS["ai_news_weight"] == "Peso de las noticias en la IA"
    txt = ai_advisor.advisor_system(__import__("fx.profiles", fromlist=["x"]).ai_policy(2), ai_advisor.FX_MARKET)
    assert "ai_news_weight" in txt and "ai_by_news_risk" in txt
