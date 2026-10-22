"""Iteration 25 – Evolution timeline (every settings change recorded with equity; after-vs-before performance per change) for both bots,
and the VPS backup kit (nightly mongodump, weekly Telegram upload through POST /api/cron/backup). Run with `-n 0`."""
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


def _secret():
    for line in open("/app/backend/.env"):
        if line.startswith("WEBHOOK_CRON_SECRET="):
            return line.split("=", 1)[1].strip().strip('"')
    return ""


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
    """Settings flips made by these tests are artefacts: remove the evolution events they created in both bots."""
    start = datetime.now(timezone.utc).isoformat()
    yield
    from pymongo import MongoClient
    env = dict(l.strip().split("=", 1) for l in open("/app/backend/.env") if "=" in l and not l.startswith("#"))
    db = MongoClient(env["MONGO_URL"].strip('"'))[env["DB_NAME"].strip('"')]
    for col in ("changes", "fx_changes"):
        db[col].delete_many({"ts": {"$gte": start}})


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
        return list(self.rows)


class _Col:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def find(self, flt=None, proj=None):
        return _Cursor([{k: v for k, v in r.items() if not (proj and proj.get(k) == 0)} for r in self.rows])

    async def insert_one(self, doc):
        self.rows.append(dict(doc))

    async def count_documents(self, flt):
        return len(self.rows)


class _Engine:
    def __init__(self, changes, trades, equity=1000.0):
        class DB:
            pass
        self.db = DB()
        self.db.changes, self.db.trades = _Col(changes), _Col(trades)
        self._equity = equity

    async def account_summary(self):
        return {"equity": self._equity, "total_trades": len(self.db.trades.rows), "mode": "PAPER"}


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


class TestEvolutionUnit:
    def test_diff_ignores_plan_and_running(self):
        import evolution
        before = {"max_positions": 5, "plan_scenario": "base", "bot_running": False, "symbols": ["A", "B"], "risk_per_trade": 1.0}
        after = {"max_positions": 4, "plan_scenario": "optimista", "bot_running": True, "symbols": ["A", "B"], "risk_per_trade": 1.0}
        assert evolution.diff(before, after) == {"max_positions": {"antes": 5, "despues": 4}}
        assert evolution.diff(before, before) == {}

    def test_record_skips_empty_and_stores_state(self):
        import evolution
        eng = _Engine([], [], equity=1234.5)
        assert asyncio.run(evolution.record(eng, "manual", {}, "x")) is None and eng.db.changes.rows == []
        doc = asyncio.run(evolution.record(eng, "auto_review", {"ai_min_confidence": {"antes": 60, "despues": 65}}, "resumen IA"))
        assert doc["source"] == "auto_review" and doc["equity"] == 1234.5 and doc["summary"] == "resumen IA" and doc["mode"] == "PAPER" and len(eng.db.changes.rows) == 1
        assert asyncio.run(evolution.record(eng, "weird", {"a": {"antes": 1, "despues": 2}}))["source"] == "manual"

    def test_verdicts(self):
        import evolution
        a = lambda n, pnl, avg: {"trades": n, "pnl": pnl, "avg_pnl": avg, "win_rate": 50, "profit_factor": 1}  # noqa: E731
        assert evolution.verdict(a(10, 5, 0.5), a(2, 9, 4.5)) == "PENDIENTE"
        assert evolution.verdict(a(0, 0, 0), a(6, 9, 1.5)) == "MEJOR" and evolution.verdict(a(0, 0, 0), a(6, -9, -1.5)) == "PEOR"
        assert evolution.verdict(a(8, 4, 0.5), a(8, 12, 1.5)) == "MEJOR"
        assert evolution.verdict(a(8, 12, 1.5), a(8, 4, 0.5)) == "PEOR"
        assert evolution.verdict(a(8, 8, 1.0), a(8, 8.05, 1.006)) == "IGUAL"

    def test_timeline_windows_and_summary(self):
        import evolution
        changes = [
            {"ts": _iso(20), "source": "manual", "summary": "", "changes": {"max_positions": {"antes": 5, "despues": 4}}, "equity": 900.0, "total_trades": 3, "mode": "PAPER"},
            {"ts": _iso(10), "source": "auto_review", "summary": "sube confianza", "changes": {"ai_min_confidence": {"antes": 60, "despues": 70}}, "equity": 950.0, "total_trades": 10, "mode": "PAPER"},
            {"ts": _iso(2), "source": "walk_forward", "summary": "wf", "changes": {"symbol_params": {"antes": {"X": {}}, "despues": {}}}, "equity": 1010.0, "total_trades": 18, "mode": "PAPER"},
        ]
        trades = [{"closed_at": _iso(d), "pnl": p} for d, p in ((25, -3), (18, 2), (15, 1), (14, -1), (13, 2), (12, 1), (11, -2),  # before the AI change: 6 trades
                                                                   (9, 3), (8, 2), (7, 4), (6, -1), (5, 3), (4, 2), (3, 1),  # after AI change (7 trades), before WF
                                                                   (1, 1), (0.5, -2))]  # after WF (2 trades)
        from bson import ObjectId
        for c in changes:
            c["_id"] = ObjectId()
        eng = _Engine(changes, trades, equity=1005.0)
        tl = asyncio.run(evolution.timeline(eng))
        assert tl["total"] == 3 and tl["ai_changes"] == 1 and tl["first_at"] == changes[0]["ts"] and tl["equity"] == 1005.0
        ev = tl["events"]
        assert [e["source"] for e in ev] == ["walk_forward", "auto_review", "manual"]
        wf, ai, man = ev
        assert wf["ongoing"] is True and wf["after"]["trades"] == 2 and wf["verdict"] == "PENDIENTE" and wf["equity_end"] == 1005.0 and wf["before"]["trades"] == 7
        assert ai["ongoing"] is False and ai["after"]["trades"] == 7 and ai["after"]["pnl"] == 14 and ai["before"]["trades"] == 6 and ai["verdict"] == "MEJOR"
        assert ai["equity_end"] == 1010.0 and ai["equity_delta_pct"] == pytest.approx(6.32, abs=0.01) and ai["ai"] is True and ai["source_label"] == "Revisión IA automática"
        assert man["before"]["trades"] == 1 and man["after"]["trades"] == 6 and man["window_days"] == pytest.approx(10, abs=0.1)
        assert tl["ai_better"] == 1 and tl["ai_worse"] == 0 and tl["ai_pending"] == 0
        assert tl["better"] == 2 and tl["worse"] == 0 and tl["pending"] == 1  # manual (6 ops, +2) + AI improved; walk-forward pending


class TestEvolutionApi:
    @pytest.mark.parametrize("base,key,val", [(f"{BASE_URL}/api", "scan_interval_sec", 61), (FX, "scan_interval_sec", 121)])
    def test_manual_change_is_recorded_with_window(self, s, base, key, val):
        orig = s.get(f"{base}/settings", timeout=30).json()
        before_total = s.get(f"{base}/evolution", timeout=30).json()["total"]
        try:
            r = s.put(f"{base}/settings", json={key: val}, timeout=30)
            assert r.status_code == 200 and r.json()[key] == val
            # no-op save → no event
            s.put(f"{base}/settings", json={key: val}, timeout=30)
            tl = s.get(f"{base}/evolution", timeout=30).json()
            assert tl["total"] == before_total + 1
            ev = tl["events"][0]
            assert ev["source"] == "manual" and ev["source_label"] == "Ajuste manual" and ev["changes"] == {key: {"antes": orig[key], "despues": val}}
            assert ev["ongoing"] is True and ev["verdict"] == "PENDIENTE" and "equity" in ev and ev["after"]["trades"] == 0 and "window_days" in ev
            assert set(tl) >= {"events", "total", "ai_changes", "better", "worse", "pending", "ai_better", "ai_worse", "ai_pending", "first_at", "equity", "min_trades"}
            assert tl["pending"] >= 1
        finally:
            s.put(f"{base}/settings", json={key: orig[key]}, timeout=30)

    def test_profile_change_recorded_as_profile(self, s):
        orig = s.get(f"{BASE_URL}/api/settings", timeout=30).json()
        level = orig["risk_profile"]
        other = 1 if level != 1 else 2
        try:
            r = s.post(f"{BASE_URL}/api/profile", json={"level": other}, timeout=30)
            assert r.status_code == 200, r.text
            ev = s.get(f"{BASE_URL}/api/evolution", timeout=30).json()["events"][0]
            assert ev["source"] == "profile" and "Perfil de riesgo aplicado" in ev["summary"] and "risk_profile" in ev["changes"]
        finally:
            s.post(f"{BASE_URL}/api/profile", json={"level": level}, timeout=30)
            # a profile has fixed values; restore any user-customised keys too
            s.put(f"{BASE_URL}/api/settings", json={k: orig[k] for k in ("symbols", "risk_per_trade", "max_positions", "leverage", "ai_min_confidence", "timeframe", "signal_mode",
                                                                       "disabled_strategies", "daily_loss_limit", "htf_filter", "trailing_enabled", "symbol_params") if k in orig}, timeout=30)

    def test_plan_changes_are_not_recorded(self, s):
        before = s.get(f"{FX}/evolution", timeout=30).json()["total"]
        st = s.get(f"{FX}/settings", timeout=30).json()
        new_target = st["plan_target_monthly"] + 1
        r = s.post(f"{FX}/plan", json={"initial_capital": 500, "monthly_deposit": st["plan_monthly_deposit"], "target_monthly": new_target, "scenario": st["plan_scenario"]}, timeout=240)
        assert r.status_code == 200
        s.post(f"{FX}/plan", json={"initial_capital": 500, "monthly_deposit": st["plan_monthly_deposit"], "target_monthly": st["plan_target_monthly"], "scenario": st["plan_scenario"]}, timeout=240)
        assert s.get(f"{FX}/evolution", timeout=30).json()["total"] == before


class TestBackupKit:
    def test_cron_backup_auth_and_native_archive(self):
        import backup
        h = {"Authorization": f"Bearer {_secret()}"}
        assert requests.post(f"{BASE_URL}/api/cron/backup", headers={"Authorization": "Bearer nope"}, json={}, timeout=30).status_code == 401
        r = requests.post(f"{BASE_URL}/api/cron/backup", headers=h, json={"telegram": True}, timeout=60)
        assert r.status_code == 200
        out = r.json()
        assert out["filename"].endswith(".json.gz") and out["size_mb"] >= 0 and out["sent"] is False and "Telegram" in out["reason"]
        assert (backup.DIR / out["filename"]).is_file()
        from pymongo import MongoClient
        env = dict(l.strip().split("=", 1) for l in open("/app/backend/.env") if "=" in l and not l.startswith("#"))
        meta = MongoClient(env["MONGO_URL"].strip('"'))[env["DB_NAME"].strip('"')].meta.find_one({"_id": "backup"})
        assert meta and meta["filename"] == out["filename"] and meta["sent"] is False and meta["last_at"] and meta["source"] == "auto"
        (backup.DIR / out["filename"]).unlink()

    def test_notify_send_document_exists(self):
        import notify
        import inspect
        assert inspect.iscoroutinefunction(notify.send_document)
        notify.configure(False, "", "", {})
        with pytest.raises(RuntimeError):
            asyncio.run(notify.send_document(b"x", "a.gz", "c"))

    def test_scripts_and_docs(self):
        for f in ("backup.sh", "restore.sh", "install.sh"):
            assert subprocess.run(["bash", "-n", f"/app/deploy/{f}"], capture_output=True).returncode == 0, f
            assert os.access(f"/app/deploy/{f}", os.X_OK)
        bk = open("/app/deploy/backup.sh").read()
        assert "/api/cron/backup" in bk and '"telegram": true' in bk and "mongodump" not in bk
        rs = open("/app/deploy/restore.sh").read()
        assert "/api/cron/restore" in rs and "mongorestore" not in rs and 'read -rp' in rs
        inst = open("/app/deploy/install.sh").read()
        assert "0 3 * * *" in inst and "backup.sh" in inst and "grep -v 'backup.sh'" in inst and "mkdir -p backups" in inst
        compose = open("/app/deploy/docker-compose.yml").read()
        assert "BACKUP_DIR=/data/backups" in compose and "./backups:/data/backups" in compose
        readme = open("/app/deploy/README.md").read()
        assert "backup.sh" in readme and "restore.sh" in readme and "Telegram" in readme and "14 días" in readme and "Copias de seguridad" in readme
        gi = open("/app/.gitignore").read()
        assert "deploy/backups/" in gi and "backend/backups/" in gi
        assert "backup-nightly" in open("/app/.emergent/crons.yml").read()
