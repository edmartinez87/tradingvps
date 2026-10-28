# VPS package (deploy routes) content review: zip contents, exclusions and 'tres bots' wording
import io
import os
import zipfile

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": "BlackCat2233@"}, timeout=20)
    if r.status_code != 200:
        pytest.skip("login failed")
    return r.json()["token"]


@pytest.fixture(scope="module")
def zf(token):
    r = requests.get(f"{BASE_URL}/api/deploy/package", headers={"Authorization": f"Bearer {token}"}, timeout=120)
    assert r.status_code == 200
    assert 500_000 < len(r.content) < 3_000_000
    return zipfile.ZipFile(io.BytesIO(r.content))


def test_info(token):
    r = requests.get(f"{BASE_URL}/api/deploy/info", headers={"Authorization": f"Bearer {token}"}, timeout=20)
    assert r.status_code == 200
    d = r.json()
    assert d["available"] is True and isinstance(d["version"], str) and d["package"].endswith(".zip")


def test_package_requires_auth():
    assert requests.get(f"{BASE_URL}/api/deploy/package", timeout=20).status_code == 401


@pytest.mark.parametrize("path", ["backend/fx/lab.py", "backend/fx/broker.py", "frontend/src/fx/LabModeCard.jsx",
                                  "frontend/src/fx/brand.js", "deploy/INSTALACION.md", "README.md"])
def test_contains(zf, path):
    assert f"ai-trader/{path}" in zf.namelist()


def test_readme_first_line(zf):
    first = zf.read("ai-trader/README.md").decode().splitlines()[0]
    assert first == "# AI Trader · Bybit AI Trader + HotForex AI Trading + Pepperstone AI trading"


def test_exclusions(zf):
    for n in zf.namelist():
        parts = n.split("/")
        assert "tests" not in parts and "node_modules" not in parts and "__pycache__" not in parts
        assert not parts[-1].startswith(".env") and parts[-1] != "backend.env"


@pytest.mark.parametrize("path", ["deploy/INSTALACION.md", "deploy/README.md", "deploy/backup.sh", "deploy/restore.sh"])
def test_tres_bots_wording(zf, path):
    t = zf.read(f"ai-trader/{path}").decode()
    assert "tres bots" in t
    for bad in ["ambos bots", "Ambos bots", "dos bots"]:
        assert bad not in t
