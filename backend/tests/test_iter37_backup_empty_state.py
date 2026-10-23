# Iteration 37: /api/backup listing tolerant (empty folder / error key), create/download/validation; never performs a real restore.
import os
import shutil
from pathlib import Path

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
BACKUP_DIR = Path("/app/backend/backups")
TMP_DIR = Path("/app/memory/tmp_backups_pytest")
ORIGINAL = "test_database-2026-10-22_042802.json.gz"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"password": "BlackCat2233@"})
    if r.status_code != 200:
        pytest.skip(f"login failed {r.status_code}")
    s.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return s


# Listing shape
def test_backup_status_shape(client):
    r = client.get(f"{BASE_URL}/api/backup")
    assert r.status_code == 200
    d = r.json()
    for k in ("backups", "last", "keep_days", "max_upload_mb", "error", "bots_running", "telegram", "confirm_word"):
        assert k in d, k
    assert d["error"] is None
    assert d["confirm_word"] == "RESTAURAR"
    assert set(d["bots_running"]) == {"crypto", "fx"}


# Empty folder → backups == [] and error null
def test_backup_status_empty_folder(client):
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    moved = []
    try:
        for f in BACKUP_DIR.glob("*.json.gz"):
            shutil.move(str(f), TMP_DIR / f.name)
            moved.append(f.name)
        r = client.get(f"{BASE_URL}/api/backup")
        assert r.status_code == 200
        d = r.json()
        assert d["backups"] == []
        assert d["error"] is None
    finally:
        for n in moved:
            shutil.move(str(TMP_DIR / n), BACKUP_DIR / n)
    assert (BACKUP_DIR / ORIGINAL).exists()


# Create → list → download → cleanup
def test_create_and_download(client):
    r = client.post(f"{BASE_URL}/api/backup/create", timeout=120)
    assert r.status_code == 200, r.text
    rec = r.json()
    fn = rec["filename"]
    assert isinstance(rec["size_mb"], (int, float))
    try:
        lst = client.get(f"{BASE_URL}/api/backup").json()
        assert lst["backups"][0]["filename"] == fn
        dl = client.get(f"{BASE_URL}/api/backup/download/{fn}", timeout=120)
        assert dl.status_code == 200
        assert "gzip" in dl.headers.get("content-type", "")
        assert dl.content[:2] == b"\x1f\x8b"
    finally:
        p = BACKUP_DIR / fn
        if p.exists() and fn != ORIGINAL:
            p.unlink()


def test_download_invalid_name(client):
    r = client.get(f"{BASE_URL}/api/backup/download/..%2Fx")
    assert r.status_code in (400, 404)
    r2 = client.get(f"{BASE_URL}/api/backup/download/..x.json.gz")
    assert r2.status_code in (400, 404)
    r3 = client.get(f"{BASE_URL}/api/backup/download/x.txt")
    assert r3.status_code == 400
    assert "inválido" in r3.json()["detail"]


def test_download_missing(client):
    r = client.get(f"{BASE_URL}/api/backup/download/test_database-2020-01-01_000000.json.gz")
    assert r.status_code == 404


def test_restore_without_confirm(client):
    r = client.post(f"{BASE_URL}/api/backup/restore", json={"filename": ORIGINAL})
    assert r.status_code == 400
    assert "RESTAURAR" in r.json()["detail"]


def test_unauthenticated():
    r = requests.get(f"{BASE_URL}/api/backup")
    assert r.status_code in (401, 403)
