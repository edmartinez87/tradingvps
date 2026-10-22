"""Iteration 39 – zero-cost AI filter calibration in the AI review: `ai_news_weight` setting (normal|bajo) read by the per-signal prompt,
shadow trades tagged with the market news risk at rejection time (`news_risk`) + `ai_by_news_risk` breakdown, review allowed key + rule (7)."""
import os
import sys
import asyncio
import pytest
import requests
sys.path.insert(0, "/app/backend")
from fx.ai import _build_prompt  # noqa: E402
from fx.models import FxSettings, FxSettingsUpdate  # noqa: E402
from fx import review as fx_review  # noqa: E402
import review  # noqa: E402
from ai_advisor import advisor_system, FX_MARKET  # noqa: E402
from fx.profiles import ai_policy  # noqa: E402
from fx.shadow import shadow_stats  # noqa: E402

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
FX = f"{BASE_URL}/api/fx"
SIG = {"side": "long", "strategy": "trend_ema", "score": 6, "reasons": ["EMA"], "indicators": {"rsi": 55}, "price": 1.1, "sl": 1.09, "tp": 1.12, "atr": 0.003}


@pytest.fixture(scope="module")
def s():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": "BlackCat2233@"}, timeout=30)
    assert r.status_code == 200, r.text
    sess = requests.Session()
    sess.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return sess


class TestKnob:
    def test_model_default_and_validation(self):
        assert FxSettings().ai_news_weight == "normal"
        assert FxSettings(ai_news_weight="bajo").ai_news_weight == "bajo"
        with pytest.raises(Exception):
            FxSettings(ai_news_weight="alto")
        with pytest.raises(Exception):
            FxSettingsUpdate(ai_news_weight="alto")

    def test_prompt_mentions_weight_only_when_bajo(self):
        ctx = {"htf_tf": "4h", "htf_trend": "ALCISTA", "change_24h": 0.1, "sessions": [], "recent_changes": [], "open_positions": 0, "daily_pnl_pct": 0.0, "news": None}
        assert "Peso de las noticias: BAJO" not in _build_prompt("EURUSD", "1h", SIG, {**ctx, "news_weight": "normal"})
        p = _build_prompt("EURUSD", "1h", SIG, {**ctx, "news_weight": "bajo"})
        assert "Peso de las noticias: BAJO" in p and "solo deben restar confianza" in p and p.rstrip().endswith("¿Ejecutar esta operación?")

    def test_review_allows_and_sanitizes_key(self):
        assert "ai_news_weight" in fx_review.ALLOWED_AI_KEYS and "ai_news_weight" not in review.ALLOWED_AI_KEYS  # FX only
        assert review.LABELS["ai_news_weight"] == "Peso de las noticias en la IA"
        sysmsg = advisor_system(ai_policy(2), FX_MARKET)
        assert "ai_news_weight" in sysmsg and "ai_by_news_risk" in sysmsg and "≥ 30 sombras" in sysmsg and "≥ 20 sombras" in sysmsg
        assert "ai_news_weight ('normal'|'bajo')" in sysmsg

    def test_settings_endpoint_roundtrip(self, s):
        before = s.get(f"{FX}/settings", timeout=30).json()["ai_news_weight"]
        try:
            r = s.put(f"{FX}/settings", json={"ai_news_weight": "bajo"}, timeout=30)
            assert r.status_code == 200 and r.json()["ai_news_weight"] == "bajo", r.text
            assert s.put(f"{FX}/settings", json={"ai_news_weight": "alto"}, timeout=30).status_code == 422
            assert s.get(f"{FX}/settings", timeout=30).json()["ai_news_weight"] == "bajo"
        finally:
            s.put(f"{FX}/settings", json={"ai_news_weight": before}, timeout=30)


class TestShadowNewsRisk:
    def test_stats_breakdown_from_tagged_rows(self):
        class _Cur:
            def __init__(self, rows):
                self.rows = rows

            async def to_list(self, n):
                return self.rows

        class _Col:
            def __init__(self, rows):
                self.rows = rows

            def find(self, *a, **k):
                return _Cur(self.rows)

            async def count_documents(self, q):
                return 0

        rows = [{"kind": "RECHAZADA", "pnl": 12.0, "pips": 10, "ai_confidence": 70, "strategy": "trend_ema", "symbol": "EURUSD", "session": "london", "news_risk": "ALTO"},
                {"kind": "RECHAZADA", "pnl": 8.0, "pips": 6, "ai_confidence": 65, "strategy": "trend_ema", "symbol": "GBPUSD", "session": "london", "news_risk": "ALTO"},
                {"kind": "RECHAZADA", "pnl": -5.0, "pips": -4, "ai_confidence": 60, "strategy": "turtle", "symbol": "USDJPY", "session": "tokyo", "news_risk": "BAJO"},
                {"kind": "BLOQUEADA", "pnl": 3.0, "pips": 2, "ai_confidence": 0, "strategy": "turtle", "symbol": "USDJPY", "session": "tokyo", "news_risk": "ALTO"},
                {"kind": "RECHAZADA", "pnl": 1.0, "pips": 1, "ai_confidence": 50, "strategy": "turtle", "symbol": "XAUUSD", "session": "newyork"}]

        class _DB:
            shadow_trades = _Col(rows)
            shadow_positions = _Col([])

        st = asyncio.new_event_loop().run_until_complete(shadow_stats(_DB()))
        by = {r["key"]: r for r in st["ai_by_news_risk"]}
        assert set(by) == {"ALTO", "BAJO"}, "only AI-rejected rows with a news_risk tag"
        assert by["ALTO"]["trades"] == 2 and by["ALTO"]["pnl"] == 20.0 and by["BAJO"]["trades"] == 1 and by["BAJO"]["pnl"] == -5.0

    def test_performance_endpoint_exposes_breakdown(self, s):
        d = s.get(f"{FX}/performance", timeout=60).json()
        assert "ai_by_news_risk" in d["shadow"] and isinstance(d["shadow"]["ai_by_news_risk"], list)
