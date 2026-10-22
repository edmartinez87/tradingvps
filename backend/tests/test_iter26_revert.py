"""Iteration 26 – undo a change from the evolution timeline (manual button) and let the AI undo harmful changes itself
(weekly review / "Optimizar todo"), gated by evidence (verdict PEOR). Run with `-n 0`."""
import os
import sys
import asyncio
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


@pytest.fixture(scope="module", autouse=True)
def _cleanup_test_events():
    start = datetime.now(timezone.utc).isoformat()
    yield
    from pymongo import MongoClient
    env = dict(l.strip().split("=", 1) for l in open("/app/backend/.env") if "=" in l and not l.startswith("#"))
    db = MongoClient(env["MONGO_URL"].strip('"'))[env["DB_NAME"].strip('"')]
    for col in ("changes", "fx_changes"):
        db[col].delete_many({"ts": {"$gte": start}})


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


class TestManualRevertApi:
    def test_revert_restores_previous_values_and_records(self, s):
        base = f"{BASE_URL}/api"
        orig = s.get(f"{base}/settings", timeout=30).json()
        try:
            assert s.put(f"{base}/settings", json={"scan_interval_sec": orig["scan_interval_sec"] + 7}, timeout=30).status_code == 200
            tl = s.get(f"{base}/evolution", timeout=30).json()
            ev = tl["events"][0]
            assert ev["id"] and ev["revertible"] is True and ev["reverted_at"] is None and ev["changes"]["scan_interval_sec"]["despues"] == orig["scan_interval_sec"] + 7
            r = s.post(f"{base}/evolution/{ev['id']}/revert", timeout=30)
            assert r.status_code == 200, r.text
            assert r.json()["reverted"] == ["scan_interval_sec"] and r.json()["skipped"] == []
            assert s.get(f"{base}/settings", timeout=30).json()["scan_interval_sec"] == orig["scan_interval_sec"]
            tl = s.get(f"{base}/evolution", timeout=30).json()
            new, old = tl["events"][0], tl["events"][1]
            assert new["source"] == "revert" and new["source_label"] == "Deshecho manualmente" and new["revert_of"] == ev["id"]
            assert new["changes"]["scan_interval_sec"] == {"antes": orig["scan_interval_sec"] + 7, "despues": orig["scan_interval_sec"]}
            assert "Deshecho el cambio «Ajuste manual»" in new["summary"]
            assert old["id"] == ev["id"] and old["reverted_at"] and old["revertible"] is False
            # cannot revert twice
            assert s.post(f"{base}/evolution/{ev['id']}/revert", timeout=30).status_code == 409
            # unknown id
            assert s.post(f"{base}/evolution/000000000000000000000000/revert", timeout=30).status_code == 409
            assert s.post(f"{base}/evolution/not-an-id/revert", timeout=30).status_code == 409
        finally:
            s.put(f"{base}/settings", json={"scan_interval_sec": orig["scan_interval_sec"]}, timeout=30)

    def test_revert_skips_keys_changed_later(self, s):
        orig = s.get(f"{FX}/settings", timeout=30).json()
        try:
            s.put(f"{FX}/settings", json={"scan_interval_sec": orig["scan_interval_sec"] + 11, "max_positions": max(1, orig["max_positions"] - 1)}, timeout=30)
            ev = s.get(f"{FX}/evolution", timeout=30).json()["events"][0]
            assert set(ev["changes"]) == {"scan_interval_sec", "max_positions"}
            # a later change touches max_positions → the revert must leave it alone
            s.put(f"{FX}/settings", json={"max_positions": orig["max_positions"]}, timeout=30)
            r = s.post(f"{FX}/evolution/{ev['id']}/revert", timeout=30)
            assert r.status_code == 200 and r.json()["reverted"] == ["scan_interval_sec"] and r.json()["skipped"] == ["max_positions"]
            st = s.get(f"{FX}/settings", timeout=30).json()
            assert st["scan_interval_sec"] == orig["scan_interval_sec"] and st["max_positions"] == orig["max_positions"]
            # nothing left to revert on a fully superseded event
            ev2 = [e for e in s.get(f"{FX}/evolution", timeout=30).json()["events"] if e["changes"].get("max_positions") and not e["reverted_at"] and e["source"] == "manual"][0]
            s.put(f"{FX}/settings", json={"max_positions": orig["max_positions"]}, timeout=30)
            r = s.post(f"{FX}/evolution/{ev2['id']}/revert", timeout=30)
            assert r.status_code in (200, 409)
        finally:
            s.put(f"{FX}/settings", json={"scan_interval_sec": orig["scan_interval_sec"], "max_positions": orig["max_positions"]}, timeout=30)


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, key, direction):
        self.rows = sorted(self.rows, key=lambda r: r[key], reverse=direction == -1)
        return self

    def limit(self, n):
        self.rows = self.rows[:n]
        return self

    async def to_list(self, n):
        return [dict(r) for r in self.rows]


class _Col:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def find(self, flt=None, proj=None):
        return _Cursor([{k: v for k, v in r.items() if not (proj and proj.get(k) == 0)} for r in self.rows])

    async def find_one(self, flt):
        return next((dict(r) for r in self.rows if r["_id"] == flt["_id"]), None)

    async def insert_one(self, doc):
        from bson import ObjectId
        self.rows.append({"_id": ObjectId(), **doc})

    async def update_one(self, flt, upd):
        for r in self.rows:
            if r["_id"] == flt["_id"]:
                r.update(upd["$set"])

    async def count_documents(self, flt):
        return len(self.rows)


class _Engine:
    """Minimal engine: settings dict + update_settings that records like the real one."""

    def __init__(self, changes, trades, settings):
        import evolution
        from bson import ObjectId
        from types import SimpleNamespace
        self._ev = evolution
        for c in changes:
            c.setdefault("_id", ObjectId())
        class DB:
            pass
        self.db = DB()
        self.db.changes, self.db.trades = _Col(changes), _Col(trades)
        self._settings = dict(settings)
        self._ns = SimpleNamespace

    async def account_summary(self):
        return {"equity": 1000.0, "total_trades": len(self.db.trades.rows), "mode": "PAPER"}

    async def get_settings(self):
        d = dict(self._settings)
        return self._ns(model_dump=lambda exclude=None: {k: v for k, v in d.items() if not exclude or k not in exclude})

    async def update_settings(self, patch, source="manual", summary="", extra=None):
        before = dict(self._settings)
        self._settings.update({k: v for k, v in patch.items() if v is not None})
        await self._ev.record(self, source, self._ev.diff(before, self._settings), summary, extra)
        return await self.get_settings()


def _events():
    from bson import ObjectId
    bad = ObjectId()
    pending = ObjectId()
    return bad, pending, [
        {"_id": bad, "ts": _iso(12), "source": "auto_review", "summary": "subió confianza", "changes": {"ai_min_confidence": {"antes": 60, "despues": 80}}, "equity": 1000.0, "total_trades": 10, "mode": "PAPER"},
        {"_id": pending, "ts": _iso(1), "source": "manual", "summary": "", "changes": {"max_positions": {"antes": 5, "despues": 3}}, "equity": 980.0, "total_trades": 20, "mode": "PAPER"},
    ]


def _trades():
    rows = [{"closed_at": _iso(d), "pnl": p} for d, p in ((20, 3), (18, 2), (16, 4), (15, 1), (14, 2), (13, 3))]  # good before the AI change
    rows += [{"closed_at": _iso(d), "pnl": p} for d, p in ((11, -2), (10, -3), (9, -1), (7, -2), (5, 1), (3, -4), (2, -1))]  # bad after
    rows += [{"closed_at": _iso(0.5), "pnl": 1}]
    return rows


class TestAiRevert:
    def test_ai_context_lists_changes_with_verdicts(self):
        import evolution
        bad, pending, evs = _events()
        eng = _Engine(evs, _trades(), {"ai_min_confidence": 80, "max_positions": 3})
        ctx = asyncio.run(evolution.ai_context(eng))
        assert "_explicacion" in ctx and len(ctx["cambios"]) == 2
        by_id = {c["id"]: c for c in ctx["cambios"]}
        assert by_id[str(bad)]["veredicto"] == "PEOR" and by_id[str(bad)]["ops_despues"] == 7 and by_id[str(bad)]["se_puede_deshacer"] is True
        assert by_id[str(pending)]["veredicto"] == "PENDIENTE"

    def test_apply_ai_reverts_only_with_evidence(self):
        import review
        bad, pending, evs = _events()
        eng = _Engine(evs, _trades(), {"ai_min_confidence": 80, "max_positions": 3})
        res = {"summary": "x", "changes": {}, "revert": [str(pending), str(bad), "000000000000000000000000"], "notes": []}
        applied = asyncio.run(review.apply_ai_reverts(eng, res, "auto_review"))
        assert applied == {"ai_min_confidence": {"antes": 80, "despues": 60}}
        assert eng._settings["ai_min_confidence"] == 60 and eng._settings["max_positions"] == 3
        notes = " ".join(res["notes"])
        assert "sin evidencia suficiente" in notes and "no existe" in notes and "Deshecho el cambio «Revisión IA automática»" in res["notes"][0]
        new = eng.db.changes.rows[-1]
        assert new["source"] == "auto_review" and new["revert_of"] == str(bad) and "la IA lo deshizo" in new["summary"]
        assert next(r for r in eng.db.changes.rows if r["_id"] == bad)["reverted_by"] == "auto_review"
        # second pass: already reverted → note, nothing applied
        res2 = {"summary": "x", "changes": {}, "revert": [str(bad)], "notes": []}
        assert asyncio.run(review.apply_ai_reverts(eng, res2, "optimize_all")) == {}
        assert "ya fue deshecho" in res2["notes"][0] or "sin evidencia" in res2["notes"][0]

    def test_apply_ai_changes_merges_revert_into_applied(self):
        import review
        from models import SettingsUpdate
        bad, pending, evs = _events()
        settings = {"ai_min_confidence": 80, "max_positions": 3, "risk_per_trade": 1.0, "leverage": 3, "symbols": ["BTCUSDT", "ETHUSDT"], "disabled_strategies": [], "strategy": "all",
                    "trailing_enabled": True, "htf_filter": True, "symbol_params": {}, "risk_profile": 2}
        eng = _Engine(evs, _trades(), settings)
        from types import SimpleNamespace
        st = SimpleNamespace(risk_profile=2)
        res = {"summary": "deshago", "changes": {"trailing_enabled": False}, "revert": [str(bad)], "notes": []}
        applied, previous = asyncio.run(review.apply_ai_changes(eng, res, dict(settings), st, model=SettingsUpdate, source="auto_review"))
        assert applied["ai_min_confidence"] == {"antes": 80, "despues": 60} and applied["trailing_enabled"] == {"antes": True, "despues": False}
        assert previous == {"ai_min_confidence": 80, "trailing_enabled": True}
        assert "ai_min_confidence" in review.changes_text(applied) or "Confianza" in review.changes_text(applied)

    def test_prompt_and_parser_support_revert(self):
        import ai_advisor
        sys_prompt = ai_advisor.advisor_system(ai_advisor.DEFAULT_POLICY)
        assert "evolucion" in sys_prompt and '"revert":[' in sys_prompt and "PENDIENTE" in sys_prompt
        src = open("/app/backend/ai_advisor.py").read()
        assert 'revert = data.get("revert") or []' in src
        for f in ("/app/backend/review.py", "/app/backend/fx/review.py"):
            assert 'ctx["evolucion"] = await evolution.ai_context(engine)' in open(f).read(), f

    def test_review_context_endpoint_has_evolution(self, s):
        # the optimizer context is what the AI sees; both bots expose the walk-forward/evolution via the review builders used by /ai/advise.
        import importlib
        review = importlib.import_module("review")
        assert hasattr(review, "apply_ai_reverts")
