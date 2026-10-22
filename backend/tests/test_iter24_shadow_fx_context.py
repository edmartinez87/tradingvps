"""Iteration 24 – shadow trades for HotForex (every non-executed signal is simulated), NO_EJECUTADA kind in both bots, Signal.context on every
signal, shadow stats in FX review/weekly. Run with `-n 0` (the FX end-to-end test injects a signal while the forex market is open)."""
import os
import sys
import asyncio
import subprocess
from datetime import datetime, timezone, timedelta
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


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def __aiter__(self):
        self._it = iter(list(self.rows))
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration

    async def to_list(self, n):
        return list(self.rows)


class _Col:
    def __init__(self):
        self.rows = []
        self.seq = 0

    async def insert_one(self, doc):
        self.seq += 1
        doc = {**doc, "_id": doc.get("_id", self.seq)}
        self.rows.append(doc)

    def find(self, flt=None, proj=None):
        return _Cursor([{k: v for k, v in r.items() if not (proj and proj.get(k) == 0)} for r in self.rows])

    async def delete_one(self, flt):
        self.rows = [r for r in self.rows if r["_id"] != flt["_id"]]

    async def update_one(self, flt, upd):
        for r in self.rows:
            if r["_id"] == flt["_id"]:
                r.update(upd["$set"])

    async def count_documents(self, flt):
        return len(self.rows)


class _DB:
    def __init__(self):
        self.shadow_positions, self.shadow_trades = _Col(), _Col()


class _Market:
    def __init__(self, tickers):
        self.tickers = tickers


class _Engine:
    def __init__(self, tickers, live=False):
        self.db, self.market, self.live = _DB(), _Market(tickers), live


def _settings(**kw):
    from fx.models import FxSettings
    return FxSettings(**kw)


TICK = {"EURUSD": {"price": 1.1000}, "USDJPY": {"price": 150.0}}
SIG = {"side": "long", "strategy": "trend_ema", "price": 1.1000, "sl": 1.0950, "tp": 1.1100, "atr": 0.0030, "score": 4, "reasons": [], "indicators": {}, "key_ts": 1}
ACC = {"equity": 1000.0, "available": 1000.0}


class TestFxShadowUnit:
    def test_open_shadow_sizes_like_a_paper_position(self):
        from fx.shadow import open_shadow
        from fx import risk
        eng = _Engine(TICK)
        st = _settings(risk_per_trade=1.0, leverage=100)
        d = asyncio.run(open_shadow(eng, "sig1", "EURUSD", SIG, st, "SESION", ACC, note="fuera de las sesiones permitidas (Londres)"))
        lots, margin, _ = risk.position_size(1000, 1000, 1.0, 1.1, 1.095, 100, "EURUSD", TICK, st.min_lot_max_risk)
        assert d["qty"] == lots == 0.02 and round(d["margin"], 2) == round(margin, 2) and d["undersized"] is False
        assert d["kind"] == "SESION" and d["note"].startswith("fuera de") and d["session"] and d["live"] is False
        assert d["sl"] == pytest.approx(1.095) and d["tp"] == pytest.approx(1.11) and d["fees"] == pytest.approx(risk.spread_cost("EURUSD", 0.02, TICK))
        assert len(eng.db.shadow_positions.rows) == 1

    def test_undersized_uses_min_lot_and_flags_it(self):
        from fx.shadow import open_shadow
        eng = _Engine(TICK)
        d = asyncio.run(open_shadow(eng, "sig2", "EURUSD", SIG, _settings(), "BLOQUEADA", {"equity": 5.0, "available": 5.0}, note="tope"))
        assert d["qty"] == 0.01 and d["undersized"] is True and d["risk_pct"] > 0

    def test_monitor_closes_on_sl_tp_timeout_and_weekend(self, monkeypatch):
        from fx import shadow
        from fx.symbols import SPECS
        eng = _Engine(dict(TICK))
        st = _settings(trailing_enabled=False, close_before_weekend=True)
        now = datetime.now(timezone.utc)
        for sid, kind in (("a", "RECHAZADA"), ("b", "BAJA_CONFIANZA"), ("c", "NO_EJECUTADA"), ("d", "ERROR")):
            asyncio.run(shadow.open_shadow(eng, sid, "EURUSD", SIG, st, kind, ACC, ai_confidence=55))
        rows = eng.db.shadow_positions.rows
        rows[2]["opened_at"] = (now - timedelta(hours=73)).isoformat()  # c → TIEMPO
        monkeypatch.setattr(shadow, "closing_soon", lambda m: False)
        # no exit yet: mark price refresh only
        asyncio.run(shadow.monitor_shadows(eng, {"EURUSD": {"price": 1.1010}}, st, now))
        assert len(eng.db.shadow_trades.rows) == 1 and eng.db.shadow_trades.rows[0]["reason"] == "TIEMPO" and eng.db.shadow_trades.rows[0]["signal_id"] == "c"
        assert all(r["mark_price"] == 1.1010 and r["unrealized_pnl"] > 0 for r in eng.db.shadow_positions.rows)
        # SL hit → all remaining long shadows close at the SL price with negative pnl and net pips ≈ -50 - spread
        asyncio.run(shadow.monitor_shadows(eng, {"EURUSD": {"price": 1.0940}}, st, now))
        sl_trades = [t for t in eng.db.shadow_trades.rows if t["reason"] == "SL"]
        assert len(sl_trades) == 3 and not eng.db.shadow_positions.rows
        t = sl_trades[0]
        assert t["exit_price"] == pytest.approx(1.095) and t["pnl"] < 0 and t["pips"] == pytest.approx(-50 - SPECS["EURUSD"]["spread"] * 10000, abs=0.2)
        assert t["pnl"] == pytest.approx(-0.005 * 100000 * 0.02 - t["fees"], abs=0.01) and t["ai_confidence"] == 55 and "closed_at" in t
        # TP
        asyncio.run(shadow.open_shadow(eng, "e", "EURUSD", SIG, st, "NOTICIAS", ACC))
        asyncio.run(shadow.monitor_shadows(eng, {"EURUSD": {"price": 1.1200}}, st, now))
        tp = [t for t in eng.db.shadow_trades.rows if t["reason"] == "TP"]
        assert len(tp) == 1 and tp[0]["pnl"] > 0 and tp[0]["pips"] > 90
        # weekend flat
        asyncio.run(shadow.open_shadow(eng, "f", "EURUSD", SIG, st, "SESION", ACC))
        monkeypatch.setattr(shadow, "closing_soon", lambda m: True)
        asyncio.run(shadow.monitor_shadows(eng, {"EURUSD": {"price": 1.1005}}, st, now))
        assert [t["reason"] for t in eng.db.shadow_trades.rows][-1] == "FIN_SEMANA"

    def test_trailing_moves_shadow_stop_and_tags_trailing_exit(self, monkeypatch):
        from fx import shadow
        eng = _Engine(dict(TICK))
        st = _settings(trailing_enabled=True)
        now = datetime.now(timezone.utc)
        monkeypatch.setattr(shadow, "closing_soon", lambda m: False)
        asyncio.run(shadow.open_shadow(eng, "g", "EURUSD", SIG, st, "RECHAZADA", ACC, ai_confidence=40))
        asyncio.run(shadow.monitor_shadows(eng, {"EURUSD": {"price": 1.1085}}, st, now))  # +1.7R → breakeven + ATR trail
        r = eng.db.shadow_positions.rows[0]
        assert r["breakeven"] is True and r["sl"] > 1.1
        asyncio.run(shadow.monitor_shadows(eng, {"EURUSD": {"price": r["sl"] - 0.0001}}, st, now))
        assert eng.db.shadow_trades.rows[-1]["reason"] == "TRAILING" and eng.db.shadow_trades.rows[-1]["pnl"] > 0

    def test_stats_grouping(self):
        from fx.shadow import shadow_stats
        db = _DB()
        rows = [
            {"kind": "RECHAZADA", "ai_confidence": 45, "pnl": -10.0, "strategy": "trend_ema", "symbol": "EURUSD", "session": "london", "pips": -40, "undersized": False},
            {"kind": "SESION", "ai_confidence": 0, "pnl": 12.0, "strategy": "ema_pullback", "symbol": "XAUUSD", "session": "tokyo", "pips": 30, "undersized": True},
            {"kind": "NO_EJECUTADA", "ai_confidence": 70, "pnl": 3.0, "strategy": "trend_ema", "symbol": "EURUSD", "session": "london+newyork", "pips": 8, "undersized": False},
        ]
        for r in rows:
            db.shadow_trades.rows.append({**r, "_id": len(db.shadow_trades.rows) + 1})
        st = asyncio.run(shadow_stats(db))
        assert st["total"]["trades"] == 3 and st["total"]["pips"] == -2 and st["filter_value"] == -5.0 and st["undersized"] == 1
        assert st["ai"]["trades"] == 1 and st["ai"]["filter_value"] == 10.0
        assert [k["key"] for k in st["by_kind"]] == ["RECHAZADA", "SESION", "NO_EJECUTADA"]
        assert {r["key"] for r in st["by_session"]} == {"london", "tokyo", "london+newyork"}
        assert st["by_confidence"][1]["key"] == "40-59%" and st["by_confidence"][1]["trades"] == 1


class TestSharedPieces:
    def test_kinds_and_signal_context_field(self):
        import shadow
        from fx import shadow as fxs
        from models import Signal
        assert "NO_EJECUTADA" in shadow.KINDS and "NO_EJECUTADA" in fxs.KINDS and "SESION" in fxs.KINDS and "FUNDING" not in fxs.KINDS
        sig = Signal(symbol="EURUSD", side="long", strategy="trend_ema", timeframe="1h", price=1, sl=0.9, tp=1.2, score=3, reasons=[], indicators={}, ai_decision="SIN_IA")
        assert sig.context == {} and Signal.from_mongo({**sig.to_mongo(), "_id": "x"}).context == {}

    def test_weekly_format_lists_filters(self):
        import weekly
        w = {"week": {"trades": 2, "win_rate": 50, "profit_factor": 1.2, "fees": 0.5}, "equity": 1000, "week_pnl": 5, "week_return_pct": 0.5, "total_return_pct": 1, "max_drawdown": 2,
             "mode": "PAPER", "best": [], "worst": [], "by_strategy": [], "signals": {"total": 6, "by_decision": {"APROBADA": 2, "RECHAZADA": 1, "SESION": 3}},
             "shadow": {"trades": 4, "filter_value": 7.5, "ai_trades": 1, "ai_value": 2.0, "by_kind": {"RECHAZADA": {"trades": 1, "value": 2.0}, "SESION": {"trades": 3, "value": 5.5}}},
             "plan": {"message": "ok", "last_30d": {"pnl": 1, "trades": 2, "profit_factor": None}, "days_running": 3, "warnings": []}, "news": None}
        txt = weekly.format_weekly(w, "USD")
        assert "Valor del filtro: evitó pérdidas por <b>7.50 USD</b> en 4 operaciones sombra (IA: +2.00 USD en 1)" in txt
        assert "Por filtro: sesiones +5.50" in txt

    def test_fx_weekly_no_longer_disables_shadow(self):
        src = open("/app/backend/fx/weekly.py").read()
        assert "shadow_supported" not in src

    def test_fx_review_context_includes_shadow(self):
        src = open("/app/backend/fx/review.py").read()
        assert 'pop("shadow"' not in src and "by_session" in src and "fx_shadow_stats" in src


class TestFxEndToEnd:
    """Forex market open required: force a SESION block (sessions_allowed = inactive sessions), inject a signal → signal with context + open shadow."""

    def test_blocked_signal_creates_shadow_with_context(self, s):
        mk = s.get(f"{FX}/market", timeout=30).json()
        if not mk["open"]:
            pytest.skip("forex market closed")
        inactive = [x["id"] for x in mk["sessions"] if not x["open"]]
        if not inactive:
            pytest.skip("all sessions open")
        orig = s.get(f"{FX}/settings", timeout=30).json()
        from pymongo import MongoClient
        env = dict(l.strip().split("=", 1) for l in open("/app/backend/.env") if "=" in l and not l.startswith("#"))
        db = MongoClient(env["MONGO_URL"].strip('"'))[env["DB_NAME"].strip('"')]
        before_open = s.get(f"{FX}/performance", timeout=60).json()["shadow"]["open"]
        try:
            assert s.put(f"{FX}/settings", json={"sessions_allowed": inactive[:1]}, timeout=30).status_code == 200
            out = subprocess.run(["python3", "scripts/fx_inject_signal.py", "EURUSD", "long", "noai"], cwd="/app", capture_output=True, text=True, timeout=180)
            assert "'ai_decision': 'SESION'" in out.stdout, out.stdout[-800:] + out.stderr[-800:]
            sig = db.fx_signals.find_one(sort=[("_id", -1)])
            assert sig["ai_decision"] == "SESION" and sig["executed"] is False and "fuera de las sesiones" in sig["note"]
            ctx = sig["context"]
            for k in ("mode", "sessions", "htf_tf", "htf_trend", "price_now", "spread_pips", "sl_pips", "open_positions", "max_positions", "daily_pnl_pct", "equity",
                      "news_risk", "news_size_factor", "ai_enabled", "ai_min_confidence"):
                assert k in ctx, k
            assert ctx["mode"] == "PAPER" and ctx["spread_pips"] > 0 and ctx["sl_pips"] > 0 and isinstance(ctx["sessions"], list)
            sh = db.fx_shadow_positions.find_one({"signal_id": str(sig["_id"])})
            assert sh and sh["kind"] == "SESION" and sh["qty"] > 0 and sh["session"] and sh["symbol"] == "EURUSD" and "sesiones" in sh["note"]
            perf = s.get(f"{FX}/performance", timeout=60).json()["shadow"]
            assert perf["open"] >= before_open + 1 and "by_session" in perf and "undersized" in perf
            # the dashboard signal feed exposes the context too
            feed = s.get(f"{FX}/dashboard", timeout=30).json()["signals"]
            assert feed and feed[0]["ai_decision"] == "SESION" and feed[0].get("context", {}).get("mode") == "PAPER"
        finally:
            s.put(f"{FX}/settings", json={"sessions_allowed": orig["sessions_allowed"]}, timeout=30)
            latest = db.fx_signals.find_one({"reasons": ["Señal de prueba inyectada manualmente"], "ai_decision": "SESION"}, sort=[("_id", -1)])
            if latest:
                db.fx_shadow_positions.delete_many({"signal_id": str(latest["_id"])})
                db.fx_signals.delete_one({"_id": latest["_id"]})
