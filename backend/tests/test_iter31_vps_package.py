"""Iteration 31 – "Instalar en tu VPS": downloadable source package (deploy_pkg) + /api/deploy/* routes + deploy scripts shipped in the zip."""
import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import requests

sys.path.insert(0, "/app/backend")
import deploy_pkg  # noqa: E402

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
ROOT = Path("/app")


@pytest.fixture(scope="module")
def s():
    r = requests.post(f"{API}/auth/login", json={"password": "BlackCat2233@"}, timeout=30)
    assert r.status_code == 200, r.text
    sess = requests.Session()
    sess.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return sess


class TestPackageBuilder:
    def test_source_root_and_version(self):
        assert deploy_pkg.source_root() == ROOT
        v = deploy_pkg.version()
        assert v["source"] == "git" and len(v["version"]) >= 7 and v["commit_date"]
        assert deploy_pkg.filename(v).startswith(f"ai-trader-{v['version']}-") and deploy_pkg.filename(v).endswith(".zip")

    def test_version_fallbacks(self, tmp_path, monkeypatch):
        for d in ("backend", "frontend", "deploy"):
            (tmp_path / d).mkdir()
        monkeypatch.setenv("APP_SOURCE_DIR", str(tmp_path))
        assert deploy_pkg.source_root() == tmp_path
        assert deploy_pkg.version(tmp_path)["source"] == "none"  # no git, no VERSION
        (tmp_path / "VERSION").write_text(json.dumps({"version": "abc1234", "commit_date": "2026-01-01T00:00:00+00:00"}))
        v = deploy_pkg.version(tmp_path)
        assert v == {"version": "abc1234", "commit_date": "2026-01-01T00:00:00+00:00", "source": "file"}
        monkeypatch.setenv("APP_SOURCE_DIR", str(tmp_path / "nope"))
        assert deploy_pkg.source_root() == ROOT  # falls back to the repo layout

    def test_unavailable_when_no_sources(self, tmp_path, monkeypatch):
        monkeypatch.setenv("APP_SOURCE_DIR", str(tmp_path))
        monkeypatch.setattr(deploy_pkg, "source_root", lambda: None)
        info = deploy_pkg.info()
        assert info["available"] is False and "código fuente" in info["reason"]
        with pytest.raises(FileNotFoundError):
            deploy_pkg.build()

    def test_skip_rules(self):
        skip = deploy_pkg._skip
        assert skip(Path("backend/.env")) and skip(Path("deploy/backend.env")) and skip(Path("deploy/.env")) and skip(Path("frontend/.env.local"))
        assert skip(Path("frontend/node_modules/x/index.js")) and skip(Path("backend/__pycache__/a.pyc")) and skip(Path("backend/tests/t.py"))
        assert skip(Path("deploy/backups/x.json.gz")) and skip(Path("frontend/build/index.html")) and skip(Path("backend/x.log"))
        assert not skip(Path("backend/server.py")) and not skip(Path("deploy/install.sh")) and not skip(Path("frontend/src/App.js"))
        assert not skip(Path("deploy/frontend.yarn.lock")) and skip(Path("backend/.env.example"))  # any .env.* variant stays out

    def test_build_contents_and_secrets(self):
        data, name, v = deploy_pkg.build()
        z = zipfile.ZipFile(io.BytesIO(data))
        names = z.namelist()
        assert all(n.startswith("ai-trader/") for n in names)
        for must in ("ai-trader/backend/server.py", "ai-trader/backend/deploy_pkg.py", "ai-trader/frontend/package.json", "ai-trader/frontend/src/App.js",
                     "ai-trader/deploy/install.sh", "ai-trader/deploy/docker-compose.yml", "ai-trader/deploy/INSTALACION.md", "ai-trader/deploy/update-zip.sh",
                     "ai-trader/deploy/reset-password.sh", "ai-trader/deploy/frontend.yarn.lock", "ai-trader/scripts/bybit_mock.py", "ai-trader/.dockerignore",
                     "ai-trader/VERSION", "ai-trader/README.md"):
            assert must in names, must
        leaks = [n for n in names if n.endswith("/.env") or n.endswith("backend.env") or "/node_modules/" in n or "/__pycache__/" in n
                 or "/tests/" in n or "/backups/" in n or n.endswith(".pyc") or "/build/" in n]
        assert leaks == [], leaks
        ver = json.loads(z.read("ai-trader/VERSION"))
        assert ver["version"] == v["version"] and ver["built_at"]
        assert z.read("ai-trader/deploy/frontend.yarn.lock") == (ROOT / "frontend" / "yarn.lock").read_bytes()  # lockfile kept in sync
        env_text = (ROOT / "backend" / ".env").read_text()
        secret = next(l.split("=", 1)[1].strip().strip('"') for l in env_text.splitlines() if l.startswith("JWT_SECRET="))
        for n in names:
            if not n.endswith("/"):
                assert secret.encode() not in z.read(n), f"secret leaked in {n}"
        sh = z.getinfo("ai-trader/deploy/install.sh")
        assert (sh.external_attr >> 16) & 0o111, "install.sh must keep its executable bit"
        assert name == deploy_pkg.filename(v) and len(data) < 5 * 1048576


class TestDeployApi:
    def test_requires_auth(self):
        assert requests.get(f"{API}/deploy/info", timeout=30).status_code == 401
        assert requests.get(f"{API}/deploy/package", timeout=30).status_code == 401

    def test_info(self, s):
        r = s.get(f"{API}/deploy/info", timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["available"] is True and d["files"] > 100 and d["source_mb"] > 0.5
        assert d["package"].startswith(f"ai-trader-{d['version']}-")
        assert "deploy/" in d["contents"] and any("secretos" in x for x in d["excluded"])

    def test_package_download(self, s):
        r = s.get(f"{API}/deploy/package", timeout=120)
        assert r.status_code == 200, r.text[:200]
        assert r.headers["content-type"] == "application/zip"
        assert 'filename="ai-trader-' in r.headers["content-disposition"]
        assert r.headers["x-package-version"] == s.get(f"{API}/deploy/info", timeout=30).json()["version"]
        z = zipfile.ZipFile(io.BytesIO(r.content))
        assert z.testzip() is None
        assert "ai-trader/deploy/INSTALACION.md" in z.namelist()
        logs = s.get(f"{API}/dashboard", timeout=60).json()["logs"]
        assert any("Paquete de instalación descargado" in l["message"] for l in logs)

    def test_cors_exposes_download_headers(self, s):
        r = s.get(f"{API}/deploy/info", headers={"Origin": "https://example.com"}, timeout=30)
        exposed = r.headers.get("access-control-expose-headers", "").lower()
        assert "content-disposition" in exposed and "x-package-version" in exposed


class TestDeployScripts:
    def test_scripts_syntax_and_flags(self):
        for f in ("install.sh", "update.sh", "update-zip.sh", "reset-password.sh", "backup.sh", "restore.sh"):
            p = ROOT / "deploy" / f
            assert os.access(p, os.X_OK), f
            subprocess.run(["bash", "-n", str(p)], check=True)
        install = (ROOT / "deploy" / "install.sh").read_text()
        assert "update-zip.sh reset-password.sh" in install
        compose = (ROOT / "deploy" / "docker-compose.yml").read_text()
        assert "APP_SOURCE_DIR=/src" in compose and "..:/src:ro" in compose
        update = (ROOT / "deploy" / "update.sh").read_text()
        assert "../.git" in update and "update-zip.sh" in update
        guide = (ROOT / "deploy" / "INSTALACION.md").read_text()
        for must in ("install.sh", "update-zip.sh", "reset-password.sh", "scp ai-trader-*.zip", "unzip", "CREDENTIAL_ENCRYPTION_KEY", "RESTAURAR"):
            assert must in guide, must

    def test_update_zip_preserves_secrets_and_replaces_code(self, tmp_path):
        data, _, v = deploy_pkg.build()
        zip_path = tmp_path / "pkg.zip"
        zip_path.write_bytes(data)
        app = tmp_path / "app"
        (app / "deploy" / "backups").mkdir(parents=True)
        (app / "backend").mkdir()
        (app / "deploy" / ".env").write_text("SITE_ADDRESS=:80\n")
        (app / "deploy" / "backend.env").write_text("JWT_SECRET=keepme\n")
        (app / "deploy" / "backups" / "old.json.gz").write_bytes(b"x")
        (app / "backend" / "stale.py").write_text("old")
        (app / "VERSION").write_text('{"version": "old1"}')
        (app / "deploy" / "update-zip.sh").write_bytes((ROOT / "deploy" / "update-zip.sh").read_bytes())
        fake_bin = tmp_path / "bin"
        fake_bin.mkdir()
        (fake_bin / "docker").write_text("#!/bin/sh\necho docker $*\n")
        os.chmod(fake_bin / "docker", 0o755)
        out = subprocess.run(["bash", str(app / "deploy" / "update-zip.sh"), str(zip_path)], capture_output=True, text=True,
                             env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"})
        assert out.returncode == 0, out.stderr + out.stdout
        assert "Versión actual: old1" in out.stdout and f"Versión nueva:  {v['version']}" in out.stdout and "docker compose up -d --build" in out.stdout
        assert (app / "deploy" / "backend.env").read_text() == "JWT_SECRET=keepme\n"
        assert (app / "deploy" / ".env").read_text() == "SITE_ADDRESS=:80\n"
        assert (app / "deploy" / "backups" / "old.json.gz").exists()
        assert not (app / "backend" / "stale.py").exists() and (app / "backend" / "deploy_pkg.py").exists()
        assert (app / "frontend" / "src" / "App.js").exists() and (app / "deploy" / "INSTALACION.md").exists()
        assert json.loads((app / "VERSION").read_text())["version"] == v["version"]

    def test_update_zip_rejects_foreign_zip(self, tmp_path):
        bad = tmp_path / "bad.zip"
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr("other/readme.txt", "nope")
        app = tmp_path / "app"
        (app / "deploy").mkdir(parents=True)
        (app / "deploy" / "update-zip.sh").write_bytes((ROOT / "deploy" / "update-zip.sh").read_bytes())
        out = subprocess.run(["bash", str(app / "deploy" / "update-zip.sh"), str(bad)], capture_output=True, text=True)
        assert out.returncode == 1 and "no parece un paquete" in out.stdout
