"""Iteration 27 – native backups (dump/parse/restore, panel API with chunked upload, cron create/restore) and the evolution block of the
weekly Telegram summary. Run with `-n 0`: the restore round-trip stops both bots for a few seconds and starts again the ones that were running."""
import os
import sys
import gzip
import json
import time
import asyncio
import uuid
from datetime import datetime, timezone, timedelta
import pytest
import requests

sys.path.insert(0, "/app/backend")
from tests.test_iter25_evolution_backup import _Engine, _iso, _secret  # noqa: E402

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
FX = f"{BASE_URL}/api/fx"


def _env():
    return dict(l.strip().split("=", 1) for l in open("/app/backend/.env") if "=" in l and not l.startswith("#"))


def _mongo():
    from pymongo import MongoClient
    env = _env()
    return MongoClient(env["MONGO_URL"].strip('"'))[env["DB_NAME"].strip('"')]


def _motor():
    from motor.motor_asyncio import AsyncIOMotorClient
    env = _env()
    return AsyncIOMotorClient(env["MONGO_URL"].strip('"'))[env["DB_NAME"].strip('"')]


@pytest.fixture(scope="module")
def s():
    r = requests.post(f"{API}/auth/login", json={"password": "BlackCat2233@"}, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"login failed {r.status_code}")
    sess = requests.Session()
    sess.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return sess


def _upload(s, data: bytes, chunk: int = 64 * 1024, upload_id: str = None) -> str:
    upload_id = upload_id or str(uuid.uuid4())
    total = max(1, -(-len(data) // chunk))
    for i in range(total):
        r = s.post(f"{API}/backup/upload", data=data[i * chunk:(i + 1) * chunk], timeout=60,
                   headers={"Content-Type": "application/octet-stream", "X-Upload-Id": upload_id, "X-Chunk-Index": str(i), "X-Chunk-Total": str(total)})
        assert r.status_code == 200, r.text
        assert r.json()["received"] == i + 1 and r.json()["complete"] == (i + 1 == total)
    return upload_id


class TestBackupUnit:
    def test_dump_parse_roundtrip_keeps_types(self):
        import backup
        from bson import ObjectId
        db = _motor()
        data = asyncio.run(backup.dump(db))
        header, docs = backup.parse(data)
        assert header["format"] == "aitrader-backup" and header["version"] == 1 and header["db"] == db.name
        assert "cron_runs" not in header["collections"] and "cron_runs" not in docs and "backup_uploads" not in docs
        sync = _mongo()
        for name, n in header["collections"].items():
            assert len(docs.get(name, [])) == n, name
            assert abs(sync[name].count_documents({}) - n) <= 3, name  # live collections may grow a little while dumping
        assert docs["settings"][0]["_id"] == "main" and isinstance(docs["settings"][0]["symbols"], list)
        oid_docs = docs.get("logs") or docs.get("fx_logs")
        assert oid_docs and isinstance(oid_docs[0]["_id"], ObjectId)

    def test_parse_rejects_bad_archives(self):
        import backup
        with pytest.raises(ValueError, match="no es una copia válida"):
            backup.parse(b"not gzip at all")
        with pytest.raises(ValueError, match="cabecera"):
            backup.parse(gzip.compress(b"{broken\n"))
        with pytest.raises(ValueError, match="no es una copia de este bot"):
            backup.parse(gzip.compress(json.dumps({"format": "other"}).encode() + b"\n"))
        with pytest.raises(ValueError, match="más reciente"):
            backup.parse(gzip.compress(json.dumps({"format": "aitrader-backup", "version": 99}).encode() + b"\n"))
        with pytest.raises(ValueError, match="dañada"):
            backup.parse(gzip.compress(json.dumps({"format": "aitrader-backup", "version": 1}).encode() + b"\n{nope\n"))
        hdr, docs = backup.parse(gzip.compress(json.dumps({"format": "aitrader-backup", "version": 1, "collections": {}}).encode() + b"\n\n"))
        assert docs == {}

    def test_prune_keeps_newest_three(self, tmp_path, monkeypatch):
        import backup
        monkeypatch.setattr(backup, "DIR", tmp_path)
        old = time.time() - 40 * 86400
        for i in range(5):
            p = tmp_path / f"db-2026-01-0{i + 1}_000000.json.gz"
            p.write_bytes(b"x")
            os.utime(p, (old + i, old + i))
        fresh = tmp_path / "db-2026-06-01_000000.json.gz"
        fresh.write_bytes(b"x")
        removed = backup.prune()
        left = sorted(p.name for p in tmp_path.glob("*.json.gz"))
        assert len(left) == 3 and fresh.name in left and len(removed) == 3
        with pytest.raises(ValueError):
            backup.safe_path("../etc/passwd")
        with pytest.raises(ValueError):
            backup.safe_path("db.tar.gz")
        with pytest.raises(FileNotFoundError):
            backup.safe_path("missing-2026.json.gz")
        for bad in ("", "x" * 70, "ZZZZZZZZ", "abc"):
            with pytest.raises(ValueError):
                backup.check_upload_id(bad)
        backup.check_upload_id(str(uuid.uuid4()))


class TestBackupApi:
    def test_status_create_download_and_validation(self, s):
        import backup
        st = s.get(f"{API}/backup", timeout=30).json()
        assert set(st) >= {"backups", "last", "keep_days", "max_upload_mb", "bots_running", "telegram", "confirm_word"} and st["confirm_word"] == "RESTAURAR"
        rec = s.post(f"{API}/backup/create", timeout=120).json()
        assert rec["filename"].endswith(".json.gz") and rec["source"] == "manual" and (backup.DIR / rec["filename"]).is_file()
        st = s.get(f"{API}/backup", timeout=30).json()
        assert st["backups"][0]["filename"] == rec["filename"] and st["last"]["filename"] == rec["filename"] and st["last"]["source"] == "manual"
        r = s.get(f"{API}/backup/download/{rec['filename']}", timeout=60)
        assert r.status_code == 200 and r.headers["content-type"].startswith("application/gzip") and rec["filename"] in r.headers.get("content-disposition", "")
        header, docs = backup.parse(r.content)
        assert header["format"] == "aitrader-backup" and docs["settings"][0]["_id"] == "main"
        assert s.get(f"{API}/backup/download/..%2F..%2Fetc%2Fpasswd", timeout=30).status_code in (400, 404)
        assert s.get(f"{API}/backup/download/nope.json.gz", timeout=30).status_code == 404
        assert s.get(f"{API}/backup/download/nope.tar.gz", timeout=30).status_code == 400
        assert requests.get(f"{API}/backup", timeout=30).status_code in (401, 403)
        (backup.DIR / rec["filename"]).unlink()

    def test_upload_validation_and_restore_guards(self, s):
        import backup
        data = gzip.compress(json.dumps({"format": "aitrader-backup", "version": 1, "collections": {}}).encode() + b"\n")
        h = {"Content-Type": "application/octet-stream", "X-Upload-Id": "bad id", "X-Chunk-Index": "0", "X-Chunk-Total": "1"}
        assert s.post(f"{API}/backup/upload", data=data, headers=h, timeout=30).status_code == 400
        uid = str(uuid.uuid4())
        h.update({"X-Upload-Id": uid, "X-Chunk-Index": "1", "X-Chunk-Total": "2"})
        assert s.post(f"{API}/backup/upload", data=data, headers=h, timeout=30).status_code == 409  # out of order (nothing received yet)
        h.update({"X-Chunk-Index": "0", "X-Chunk-Total": "2"})
        assert s.post(f"{API}/backup/upload", data=b"", headers=h, timeout=30).status_code == 400  # empty chunk
        assert s.post(f"{API}/backup/upload", data=data[:10], headers=h, timeout=30).json()["complete"] is False
        h.update({"X-Chunk-Index": "1"})
        assert s.post(f"{API}/backup/upload", data=data[10:], headers=h, timeout=30).json()["complete"] is True
        assert _mongo()[backup.UPLOADS].count_documents({"upload_id": uid}) == 2
        assert s.post(f"{API}/backup/restore", json={"confirm": "no", "upload_id": uid}, timeout=30).status_code == 400
        assert s.post(f"{API}/backup/restore", json={"confirm": "RESTAURAR"}, timeout=30).status_code in (400, 409)
        incomplete = str(uuid.uuid4())
        h2 = {"Content-Type": "application/octet-stream", "X-Upload-Id": incomplete, "X-Chunk-Index": "0", "X-Chunk-Total": "3"}
        assert s.post(f"{API}/backup/upload", data=b"abc", headers=h2, timeout=30).status_code == 200
        r = s.post(f"{API}/backup/restore", json={"confirm": "RESTAURAR", "upload_id": incomplete}, timeout=30)
        assert r.status_code in (400, 409)  # 409 while a bot runs, 400 incomplete upload otherwise
        garbage = _upload(s, b"not a backup at all" * 100)
        running = s.get(f"{API}/backup", timeout=30).json()["bots_running"]
        r = s.post(f"{API}/backup/restore", json={"confirm": "RESTAURAR", "upload_id": garbage}, timeout=30)
        if running["crypto"] or running["fx"]:
            assert r.status_code == 409 and "Detén ambos bots" in r.json()["detail"]
        else:
            assert r.status_code == 400 and "no es una copia" in r.json()["detail"]
        _mongo()[backup.UPLOADS].delete_many({"upload_id": {"$in": [uid, incomplete, garbage]}})

    def test_restore_roundtrip_via_upload(self, s):
        """Full cycle: backup → add a marker doc → stop bots → chunked upload → restore → marker gone, auth kept, bots stopped → re-start."""
        import backup
        db = _mongo()
        was = {"crypto": s.get(f"{API}/backup", timeout=30).json()["bots_running"]}
        was["fx"] = was["crypto"]["fx"]
        was["crypto"] = was["crypto"]["crypto"]
        cron_before = db.cron_runs.count_documents({})
        rec = s.post(f"{API}/backup/create", timeout=120).json()
        data = (backup.DIR / rec["filename"]).read_bytes()
        marker = {"level": "INFO", "message": f"marker-{uuid.uuid4()}", "ts": datetime.now(timezone.utc).isoformat()}
        db.logs.insert_one(dict(marker))
        db.fx_logs.insert_one(dict(marker))
        db.settings.update_one({"_id": "main"}, {"$set": {"scan_interval_sec": 777}})
        try:
            if was["crypto"]:
                assert s.post(f"{API}/bot/stop", timeout=30).status_code == 200
            if was["fx"]:
                assert s.post(f"{FX}/bot/stop", timeout=30).status_code == 200
            uid = _upload(s, data, chunk=32 * 1024)
            r = s.post(f"{API}/backup/restore", json={"confirm": "restaurar", "upload_id": uid}, timeout=300)
            assert r.status_code == 200, r.text
            out = r.json()
            assert out["bots_stopped"] is True and out["documents"] > 0 and out["collections"]["settings"] == 1 and out["origin"].startswith("archivo subido")
            assert db.logs.count_documents({"message": marker["message"]}) == 0 and db.fx_logs.count_documents({"message": marker["message"]}) == 0
            assert db.settings.find_one({"_id": "main"})["scan_interval_sec"] != 777
            assert db.settings.find_one({"_id": "main"})["bot_running"] is False and db.fx_settings.find_one({"_id": "main"})["bot_running"] is False
            assert db.cron_runs.count_documents({}) == cron_before  # not part of the archive, left untouched
            assert db[backup.UPLOADS].count_documents({"upload_id": uid}) == 0
            st = s.get(f"{API}/backup", timeout=30).json()  # the session token still works (auth fields preserved)
            assert st["bots_running"] == {"crypto": False, "fx": False}
            dash = s.get(f"{API}/dashboard", timeout=60)
            assert dash.status_code == 200 and s.get(f"{FX}/dashboard", timeout=60).status_code == 200
            assert s.get(f"{API}/evolution", timeout=30).status_code == 200
            assert any("Copia de seguridad restaurada" in l["message"] for l in dash.json()["logs"])
            assert requests.get(f"{API}/", timeout=30).json()["running"] is False
        finally:
            if was["crypto"]:
                s.post(f"{API}/bot/start", timeout=30)
            if was["fx"]:
                s.post(f"{FX}/bot/start", timeout=30)
            (backup.DIR / rec["filename"]).unlink(missing_ok=True)
        if was["crypto"]:
            assert requests.get(f"{API}/", timeout=30).json()["running"] is True

    def test_cron_restore_validation(self):
        h = {"Authorization": f"Bearer {_secret()}"}
        files = {"file": ("x.json.gz", b"garbage", "application/octet-stream")}
        assert requests.post(f"{API}/cron/restore", headers={"Authorization": "Bearer nope"}, files=files, timeout=30).status_code == 401
        assert requests.post(f"{API}/cron/restore", headers=h, files={"file": ("e.gz", b"", "application/octet-stream")}, timeout=30).status_code == 400
        r = requests.post(f"{API}/cron/restore", headers=h, files=files, timeout=30)
        assert r.status_code == 400 and "no es una copia" in r.json()["detail"]


class TestWeeklyEvolution:
    def test_week_summary_counts(self):
        import evolution
        trades = [{"closed_at": _iso(2.5 - i * 0.1), "pnl": 3.0} for i in range(6)] + [{"closed_at": _iso(1.5 - i * 0.1), "pnl": -2.0} for i in range(6)]
        changes = [
            {"_id": "old", "ts": _iso(20), "source": "manual", "summary": "", "changes": {"leverage": {"antes": 3, "despues": 5}}, "equity": 1000},
            {"_id": "ai", "ts": _iso(3), "source": "auto_review", "summary": "sube riesgo", "changes": {"risk_per_trade": {"antes": 1, "despues": 1.5}}, "equity": 1000},
            {"_id": "man", "ts": _iso(2), "source": "manual", "summary": "", "changes": {"max_positions": {"antes": 3, "despues": 5}}, "equity": 1010,
             "reverted_at": _iso(1), "reverted_by": "auto_review"},
            {"_id": "rev", "ts": _iso(1), "source": "auto_review", "summary": "Deshecho", "changes": {"max_positions": {"antes": 5, "despues": 3}}, "equity": 1000,
             "revert_of": "man", "revert_of_ts": _iso(2), "revert_of_source": "manual"},
        ]
        eng = _Engine(changes, trades)
        w = asyncio.run(evolution.week_summary(eng, _iso(7)))
        assert w["total"] == 2 and w["ai_changes"] == 1 and w["reverted_by_ai"] == 1 and w["reverted_manual"] == 0
        by = {c["id"]: c for c in w["changes"]}
        assert set(by) == {"ai", "man", "rev"} and by["rev"]["is_revert"] and by["man"]["reverted_by"] == "auto_review"
        assert by["ai"]["verdict"] == "MEJOR" and by["man"]["verdict"] == "PEOR" and w["better"] == 1 and w["worse"] == 1 and w["pending"] == 0

    def test_format_weekly_lists_changes(self):
        import weekly
        ev = {"total": 2, "ai_changes": 1, "better": 1, "worse": 1, "pending": 0, "reverted_by_ai": 1, "reverted_manual": 0, "changes": [
            {"id": "a", "ts": _iso(3), "source": "auto_review", "source_label": "Revisión IA automática", "ai": True, "keys": ["risk_per_trade"], "verdict": "MEJOR",
             "after": {"trades": 6, "pnl": 18.0, "avg_pnl": 3, "win_rate": 100, "profit_factor": None}, "before": {"trades": 0, "pnl": 0, "avg_pnl": 0, "win_rate": 0, "profit_factor": None},
             "reverted_at": None, "reverted_by": None, "is_revert": False},
            {"id": "b", "ts": _iso(2), "source": "manual", "source_label": "Ajuste manual", "ai": False, "keys": ["max_positions", "timeframe"], "verdict": "PEOR",
             "after": {"trades": 6, "pnl": -12.0, "avg_pnl": -2, "win_rate": 0, "profit_factor": 0}, "before": {"trades": 6, "pnl": 18, "avg_pnl": 3, "win_rate": 100, "profit_factor": None},
             "reverted_at": _iso(1), "reverted_by": "auto_review", "is_revert": False},
            {"id": "c", "ts": _iso(1), "source": "auto_review", "source_label": "Revisión IA automática", "ai": True, "keys": ["max_positions"], "verdict": "PENDIENTE",
             "after": {"trades": 0, "pnl": 0, "avg_pnl": 0, "win_rate": 0, "profit_factor": None}, "before": {"trades": 6, "pnl": -12, "avg_pnl": -2, "win_rate": 0, "profit_factor": 0},
             "reverted_at": None, "reverted_by": None, "is_revert": True, "revert_of_ts": _iso(2), "revert_of_source": "manual"},
        ]}
        w = {"week": {"trades": 2, "win_rate": 50, "profit_factor": 1.2, "fees": 0.5}, "equity": 1000, "week_pnl": 5, "week_return_pct": 0.5, "total_return_pct": 1, "max_drawdown": 2,
             "mode": "PAPER", "best": [], "worst": [], "by_strategy": [], "signals": {"total": 0, "by_decision": {}}, "shadow": {"trades": 0, "filter_value": 0, "ai_trades": 0, "ai_value": 0, "by_kind": {}},
             "plan": {"message": "ok", "last_30d": {"pnl": 1, "trades": 2, "profit_factor": None}, "days_running": 3, "warnings": []}, "news": None, "evolution": ev}
        txt = weekly.format_weekly(w, "USDT")
        assert "🧬 <b>Evolución</b> · 2 cambios esta semana (1 por la IA · 1 mejoraron · 1 empeoraron · 1 deshecho por la IA)" in txt
        assert "🟢 Mejoró · " in txt and "Revisión IA automática · Riesgo/op % · +18.00 USDT en 6 ops" in txt
        assert "🔴 Empeoró · " in txt and "Ajuste manual · Máx. posiciones, Temporalidad · -12.00 USDT en 6 ops → deshecho por la IA" in txt
        assert "↩️ " in txt and "Deshecho por la IA del " in txt and "(Ajuste manual) · Máx. posiciones" in txt
        assert txt.index("🧬") < txt.index("📋 <b>Plan</b>")
        w["evolution"] = {"changes": [], "total": 0}
        assert "🧬" not in weekly.format_weekly(w, "USDT")
        del w["evolution"]
        assert "🧬" not in weekly.format_weekly(w, "USDT")

    def test_weekly_preview_api_includes_evolution(self, s):
        for base in (API, FX):
            w = s.get(f"{base}/weekly-summary", timeout=60).json()
            assert set(w["evolution"]) >= {"changes", "total", "ai_changes", "better", "worse", "pending", "reverted_by_ai", "reverted_manual"}
            assert isinstance(w["text"], str) and "Resumen semanal" in w["text"]
