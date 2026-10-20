# Iteration 9: news agent (API + config + gate unit), shadow trades lifecycle, performance.shadow, dashboard.news
import os
import sys
import time
from datetime import datetime, timezone, timedelta

import pytest
import requests
from dotenv import load_dotenv

sys.path.insert(0, "/app/backend")
load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
PASSWORD = "BlackCat2233@"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"password": PASSWORD}, timeout=20)
    if r.status_code != 200:
        pytest.skip(f"login failed {r.status_code}")
    s.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return s


# ---------- Unit: NewsAgent.gate / parse_feed / relevant ----------
def _agent(**cfg_over):
    import news
    import config
    a = news.NewsAgent(None, None)
    cfg = config.AppConfig()
    for k, v in cfg_over.items():
        setattr(cfg, k, v)
    a.cfg = cfg
    return a


def _latest(events=None, alerts=None, pairs=None, risk="BAJO"):
    return {"market": {"sentiment": 0, "risk": risk, "summary": "x"}, "pairs": pairs or {}, "alerts": alerts or [],
            "events": events or [], "headlines": [], "updated_at": datetime.now(timezone.utc).isoformat()}


def _ev(minutes, impact="ALTO"):
    return {"title": "CPI m/m", "time": (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat(), "impact": impact}


class TestGateUnit:
    def test_event_within_window_blocks(self):
        a = _agent(); a.latest = _latest(events=[_ev(30)])
        block, f = a.gate("BTCUSDT")
        assert block and "evento macro de alto impacto" in block and f == 1.0

    def test_event_far_no_block(self):
        a = _agent(); a.latest = _latest(events=[_ev(120)])
        assert a.gate("BTCUSDT") == (None, 1.0)

    def test_medium_event_no_block(self):
        a = _agent(); a.latest = _latest(events=[_ev(10, "MEDIO")])
        assert a.gate("BTCUSDT") == (None, 1.0)

    def test_critical_alert_blocks_pair(self):
        a = _agent()
        a.latest = _latest(alerts=[{"symbol": "XRPUSDT", "severity": "CRITICA", "title": "Ripple hack", "at": datetime.now(timezone.utc).isoformat()}])
        block, f = a.gate("XRPUSDT")
        assert block and "noticia crítica" in block
        assert a.gate("BTCUSDT")[0] is None

    def test_pair_high_risk_factor(self):
        a = _agent(); a.latest = _latest(pairs={"SOLUSDT": {"risk": "ALTO"}})
        assert a.gate("SOLUSDT") == (None, 0.5)
        assert a.gate("BTCUSDT") == (None, 1.0)

    def test_disabled(self):
        a = _agent(news_enabled=False); a.latest = _latest(events=[_ev(5)], risk="ALTO")
        assert a.gate("BTCUSDT") == (None, 1.0)

    def test_critical_and_reduce_off(self):
        a = _agent(news_block_critical=False, news_reduce_on_high_risk=False)
        a.latest = _latest(alerts=[{"symbol": "XRPUSDT", "severity": "CRITICA", "title": "t", "at": datetime.now(timezone.utc).isoformat()}],
                           pairs={"XRPUSDT": {"risk": "ALTO"}}, risk="ALTO")
        assert a.gate("XRPUSDT") == (None, 1.0)

    def test_parse_feed_rss_and_atom(self):
        import news
        rss = "<rss><channel><item><title>Bitcoin up</title><link>http://a</link><pubDate>Mon, 05 Jan 2026 10:00:00 GMT</pubDate><description>d</description></item></channel></rss>"
        atom = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Solana down</title><link href="http://b"/>'
                "<published>2026-01-05T10:00:00Z</published><summary>s</summary></entry></feed>")
        r = news.parse_feed("X", rss); a = news.parse_feed("Y", atom)
        assert r[0]["title"] == "Bitcoin up" and r[0]["link"] == "http://a" and r[0]["published"].startswith("2026-01-05T10:00")
        assert a[0]["title"] == "Solana down" and a[0]["link"] == "http://b" and a[0]["published"].startswith("2026-01-05T10:00")

    def test_relevant(self):
        import news
        h = {"title": "Solana ETF approved as Bitcoin dips", "summary": ""}
        out = news.relevant(h, ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"])
        assert set(out) == {"BTCUSDT", "SOLUSDT"}


# ---------- API: news ----------
class TestNewsAPI:
    def test_get_news_structure(self, client):
        r = client.get(f"{BASE_URL}/api/news", timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert "latest" in d and "summary" in d
        for k in ("enabled", "ready"):
            assert k in d["summary"]

    def test_refresh_news(self, client):
        before = (client.get(f"{BASE_URL}/api/news", timeout=20).json().get("latest") or {}).get("updated_at", "")
        t = time.time()
        r = client.post(f"{BASE_URL}/api/news/refresh", timeout=90)
        assert r.status_code == 200, r.text
        assert time.time() - t <= 60
        d = r.json(); L = d["latest"]
        assert L["updated_at"] > before
        assert -100 <= L["market"]["sentiment"] <= 100
        assert L["market"]["risk"] in ("BAJO", "MEDIO", "ALTO")
        assert L["market"]["summary"]
        assert isinstance(L["pairs"], dict) and isinstance(L["alerts"], list) and isinstance(L["events"], list)
        for e in L["events"]:
            assert e["impact"] in ("ALTO", "MEDIO") and datetime.fromisoformat(e["time"]) and e["title"]
        assert 10 < len(L["headlines"]) <= 40
        for h in L["headlines"]:
            assert {"source", "title", "link", "published", "symbols"} <= set(h)
        s = d["summary"]
        for k in ("enabled", "ready", "risk", "sentiment", "blocked", "critical", "next_event", "alerts"):
            assert k in s
        assert s["ready"] is True

    def test_dashboard_news(self, client):
        r = client.get(f"{BASE_URL}/api/dashboard", timeout=30)
        assert r.status_code == 200
        n = r.json()["news"]
        assert n["enabled"] is True and n["ready"] is True


# ---------- API: config news_* ----------
class TestNewsConfig:
    def test_config_fields(self, client):
        c = client.get(f"{BASE_URL}/api/config", timeout=20).json()
        for k in ("news_enabled", "news_interval_min", "news_block_events", "news_event_before_min", "news_event_after_min",
                  "news_block_critical", "news_reduce_on_high_risk", "news_size_factor", "telegram_alerts"):
            assert k in c, k

    def test_telegram_news_toggle(self, client):
        c = client.get(f"{BASE_URL}/api/config", timeout=20).json()
        alerts = dict(c["telegram_alerts"]); alerts["news"] = True
        r = client.put(f"{BASE_URL}/api/config", json={"telegram_alerts": alerts}, timeout=20)
        assert r.status_code == 200, r.text
        assert client.get(f"{BASE_URL}/api/config", timeout=20).json()["telegram_alerts"].get("news") is True

    def test_update_and_validation(self, client):
        try:
            r = client.put(f"{BASE_URL}/api/config", json={"news_interval_min": 30, "news_size_factor": 0.7}, timeout=20)
            assert r.status_code == 200, r.text
            c = client.get(f"{BASE_URL}/api/config", timeout=20).json()
            assert c["news_interval_min"] == 30 and c["news_size_factor"] == 0.7
            assert client.put(f"{BASE_URL}/api/config", json={"news_interval_min": 2}, timeout=20).status_code == 422
            assert client.put(f"{BASE_URL}/api/config", json={"news_size_factor": 1.5}, timeout=20).status_code == 422
        finally:
            r = client.put(f"{BASE_URL}/api/config", json={"news_interval_min": 20, "news_size_factor": 0.5}, timeout=20)
            assert r.status_code == 200


# ---------- Integration: shadow lifecycle ----------
class TestShadowLifecycle:
    def test_shadow_sl_close_and_performance(self, client):
        from pymongo import MongoClient
        db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        try:
            wl = client.get(f"{BASE_URL}/api/dashboard", timeout=30).json()["watchlist"]
            row = next(w for w in wl if w["symbol"] == "BTCUSDT")
            p = float(row.get("price") or row.get("last") or 0)
            assert p > 0
            db.shadow_positions.insert_one({
                "signal_id": "qa", "symbol": "BTCUSDT", "side": "long", "strategy": "breakout_turtle", "timeframe": "1h",
                "kind": "BLOQUEADA", "ai_confidence": 0, "ai_risk": "-", "entry_price": p, "qty": 0.01, "leverage": 3,
                "margin": p * 0.01 / 3, "sl": p * 1.005, "tp": p * 1.03, "initial_sl": p * 1.005, "atr": p * 0.01,
                "fees": p * 0.01 * 0.00055, "breakeven": False, "mark_price": p, "unrealized_pnl": 0.0,
                "opened_at": datetime.now(timezone.utc).isoformat()})
            closed = None
            for _ in range(15):
                time.sleep(1)
                closed = db.shadow_trades.find_one({"signal_id": "qa"})
                if closed:
                    break
            assert closed, "shadow not closed in 15s"
            assert db.shadow_positions.count_documents({"signal_id": "qa"}) == 0
            assert closed["reason"] == "SL" and closed["pnl"] < 0 and "pnl_pct" in closed and closed["closed_at"]
            perf = client.get(f"{BASE_URL}/api/performance", timeout=30).json()
            sh = perf["shadow"]
            assert sh["total"]["trades"] >= 1
            assert any(k["key"] == "BLOQUEADA" for k in sh["by_kind"])
            assert sh["filter_value"] == round(-sh["total"]["pnl"], 2)
            assert len(sh["by_confidence"]) == 4
        finally:
            db.shadow_trades.delete_many({"signal_id": "qa"})
            db.shadow_positions.delete_many({"signal_id": "qa"})
