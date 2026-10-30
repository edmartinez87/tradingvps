"""Iteration 61 — chat code tools work in every deployment (virtual /app paths → real source root) + AI-gate clarity on the signal card."""
import os
import pathlib
import tempfile

import pytest
import requests

from chat import code_reader as cr
from models import Signal

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")


@pytest.fixture(scope="module")
def s():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": "BlackCat2233@"}, timeout=30)
    assert r.status_code == 200, r.text
    sess = requests.Session()
    sess.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return sess


def test_code_reader_preview_layout():
    assert cr.real_root() == "/app"
    d = cr.list_dir("/app/backend")
    assert d["type"] == "dir" and any(e["name"] == "server.py" for e in d["entries"])
    assert not any(e["name"].startswith((".ruff_cache", "__pycache__", ".env")) for e in d["entries"])
    assert cr.list_dir("frontend/src")["path"] == "/app/frontend/src" and cr.list_dir("app/deploy")["path"] == "/app/deploy"
    f = cr.read_file("/app/backend/fx/engine_signals.py", 1, 5)
    assert f["path"] == "/app/backend/fx/engine_signals.py" and f["from"] == 1 and f["to"] == 5 and "    1| " in f["content"]
    hits = cr.search("ai_min_confidence", "/app/backend/fx")
    assert hits["files_scanned"] > 10 and any(h["file"] == "/app/backend/fx/engine_signals.py" for h in hits["hits"])
    assert cr.search("ai_min_confidence", "/app/backend")["truncated"] is True  # capped at MAX_HITS, still answers
    assert all(h["file"].startswith("/app/") for h in hits["hits"])


@pytest.mark.parametrize("bad", ["/app/backend/.env", "/etc/passwd", "/app/backend/tests/../.env", "/app/backups", "/app/frontend/node_modules", "../../etc"])
def test_code_reader_denies(bad):
    with pytest.raises(ValueError):
        cr._resolve(bad)


def test_code_reader_vps_layout(monkeypatch):
    """On a VPS the backend runs from /app (no /app/backend) and the repo is mounted read-only at APP_SOURCE_DIR=/src."""
    tmp = tempfile.mkdtemp()
    for d in ("backend/fx", "frontend/src", "deploy"):
        os.makedirs(f"{tmp}/{d}")
    pathlib.Path(f"{tmp}/backend/fx/x.py").write_text("ai_min_confidence = 60\n")
    pathlib.Path(f"{tmp}/backend/.env").write_text("SECRET=1\n")
    monkeypatch.setenv("APP_SOURCE_DIR", tmp)
    assert cr.real_root() == tmp
    assert cr.search("ai_min_confidence")["hits"] == [{"file": "/app/backend/fx/x.py", "line": 1, "text": "ai_min_confidence = 60"}]
    assert cr.list_dir("/app/frontend/src") == {"path": "/app/frontend/src", "type": "dir", "entries": []}
    assert [e["name"] for e in cr.list_dir("/app/backend")["entries"]] == ["fx/"]  # .env never listed
    with pytest.raises(ValueError, match="No existe"):
        cr.list_dir("/app/backend/nope")


def test_code_reader_missing_source(monkeypatch):
    monkeypatch.setattr(cr, "source_root", lambda: None)
    with pytest.raises(ValueError, match="APP_SOURCE_DIR"):
        cr.list_dir("/app/backend")


def test_signal_model_keeps_threshold():
    sig = Signal(symbol="EURUSD", side="long", strategy="trend_ema", timeframe="15m", price=1.1, sl=1.09, tp=1.12, score=5, reasons=[],
                 indicators={}, ai_decision="APROBADA", ai_confidence=58, ai_min_confidence=60, ai_risk="MEDIO")
    d = sig.model_dump()
    assert d["ai_min_confidence"] == 60 and d["executed"] is False
    assert Signal(**{**d, "ai_min_confidence": None}).ai_min_confidence is None  # old documents still load


@pytest.mark.parametrize("bot", ["", "/fx", "/pepper"])
def test_signals_api_exposes_threshold_field(s, bot):
    d = s.get(f"{BASE_URL}/api{bot}/dashboard", timeout=60).json()
    assert "ai_min_confidence" in d["settings"]
    for sig in d["signals"]:
        assert "ai_min_confidence" in sig  # None for pre-existing signals, the threshold for new AI-evaluated ones
