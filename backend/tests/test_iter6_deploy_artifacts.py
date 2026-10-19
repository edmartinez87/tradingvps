# Iteration 6: static/semi-dynamic validation of the /app/deploy Docker deployment kit (no docker in pod)
import fnmatch
import re
import subprocess
import time
from pathlib import Path

import pytest
import requests
import yaml
from cryptography.fernet import Fernet
from dotenv import dotenv_values

DEPLOY = Path("/app/deploy")
LOCAL_BACKEND = "http://127.0.0.1:8001"  # cron script targets host-local backend by design


# --- install.sh ---
class TestInstallScript:
    src = (DEPLOY / "install.sh").read_text()

    def test_bash_syntax(self):
        for f in ["install.sh", "cron-ai-review.sh", "update.sh"]:
            r = subprocess.run(["bash", "-n", str(DEPLOY / f)], capture_output=True, text=True)
            assert r.returncode == 0, f"{f}: {r.stderr}"

    def test_idempotent_guards(self):
        assert "if [ ! -f .env ]; then" in self.src
        assert "if [ ! -f backend.env ]; then" in self.src
        # reads only happen inside guarded blocks
        env_block = self.src.split("if [ ! -f .env ]; then")[1].split("fi\n")[0]
        assert "read -rp" in env_block
        benv_block = self.src.split("if [ ! -f backend.env ]; then")[1].split("\nfi\n")[0]
        assert benv_block.count("read -r") == 2
        assert self.src.count("read -r") == 3

    def test_password_printed_before_build_and_at_end(self):
        idx_create = self.src.index("> backend.env")
        idx_print = self.src.index('echo "    Contraseña del panel: $PW')
        idx_build = self.src.index("docker compose up -d --build")
        idx_final = self.src.index('[ -n "$NEW_PW" ] && echo "Contraseña del panel: $NEW_PW')
        assert idx_create < idx_print < idx_build < idx_final

    def test_initial_password_single_quoted(self):
        assert "echo \"INITIAL_PASSWORD='$PW'\"" in self.src
        assert "PW=\"${PW//\\'/}\"" in self.src

    def test_fernet_key_generation_valid(self):
        for _ in range(20):
            key = subprocess.run("openssl rand -base64 32 | tr '+/' '-_'", shell=True,
                                 capture_output=True, text=True).stdout.strip()
            Fernet(key.encode())  # raises if invalid
            assert len(key) == 44

    def test_generated_backend_env_parses(self, tmp_path):
        # Run the exact backend.env generation block with a nasty password
        block = self.src.split("  {\n    echo \"MONGO_URL")[1].split("  } > backend.env")[0]
        script = (
            "set -euo pipefail\nPW=\"ab'c\\$d x#y\"\nPW=\"${PW//\\'/}\"\nLLM=\"\"\n{\n    echo \"MONGO_URL"
            + block + "  } > backend.env\n"
        )
        r = subprocess.run(["bash", "-c", script], cwd=tmp_path, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        vals = dotenv_values(tmp_path / "backend.env")
        assert vals["INITIAL_PASSWORD"] == "abc$d x#y"
        assert vals["MONGO_URL"] == "mongodb://mongo:27017"
        assert vals["DB_NAME"] == "cryptobot"
        assert re.fullmatch(r"[0-9a-f]{64}", vals["JWT_SECRET"])
        assert re.fullmatch(r"[0-9a-f]{48}", vals["WEBHOOK_CRON_SECRET"])
        Fernet(vals["CREDENTIAL_ENCRYPTION_KEY"].encode())
        # every required env var used by backend is present
        for k in ["MONGO_URL", "DB_NAME", "JWT_SECRET", "INITIAL_PASSWORD", "CORS_ORIGINS",
                  "WEBHOOK_CRON_SECRET", "CREDENTIAL_ENCRYPTION_KEY", "EMERGENT_LLM_KEY"]:
            assert k in vals


# --- cron endpoint (same request as cron-ai-review.sh) ---
class TestCronEndpoint:
    @pytest.fixture(scope="class")
    def secret(self):
        s = dotenv_values("/app/backend/.env").get("WEBHOOK_CRON_SECRET")
        if not s:
            pytest.skip("WEBHOOK_CRON_SECRET missing")
        return s.strip().strip("'\"")

    def test_cron_valid_secret(self, secret):
        r = requests.post(f"{LOCAL_BACKEND}/api/cron/ai-review",
                          headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
                          json={"run_id": f"test-{int(time.time())}"}, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["accepted"] is True
        assert "scheduled" in d

    def test_cron_duplicate_run_id(self, secret):
        rid = f"test-dup-{int(time.time())}"
        h = {"Authorization": f"Bearer {secret}"}
        requests.post(f"{LOCAL_BACKEND}/api/cron/ai-review", headers=h, json={"run_id": rid}, timeout=15)
        r = requests.post(f"{LOCAL_BACKEND}/api/cron/ai-review", headers=h, json={"run_id": rid}, timeout=15)
        assert r.status_code == 200 and r.json().get("duplicate") is True

    def test_cron_wrong_secret(self):
        r = requests.post(f"{LOCAL_BACKEND}/api/cron/ai-review",
                          headers={"Authorization": "Bearer wrong-secret"}, json={"run_id": "x"}, timeout=15)
        assert r.status_code == 401

    def test_cron_no_auth(self):
        r = requests.post(f"{LOCAL_BACKEND}/api/cron/ai-review", json={"run_id": "x"}, timeout=15)
        assert r.status_code == 401

    def test_cron_script_shape(self):
        s = (DEPLOY / "cron-ai-review.sh").read_text()
        assert "grep '^WEBHOOK_CRON_SECRET=' backend.env | cut -d= -f2-" in s
        assert "http://127.0.0.1:8001/api/cron/ai-review" in s
        assert 'Authorization: Bearer $SECRET' in s


# --- docker-compose.yml + Dockerfiles ---
class TestCompose:
    c = yaml.safe_load((DEPLOY / "docker-compose.yml").read_text())

    def test_services(self):
        assert set(self.c["services"]) == {"mongo", "backend", "web"}

    def test_ports(self):
        web = self.c["services"]["web"]["ports"]
        assert "80:80" in web and "443:443" in web
        assert self.c["services"]["backend"]["ports"] == ["127.0.0.1:8001:8001"]
        assert "ports" not in self.c["services"]["mongo"]

    def test_backend_env_file_and_build(self):
        b = self.c["services"]["backend"]
        assert b["env_file"] == "backend.env"
        for name in ["backend", "web"]:
            bld = self.c["services"][name]["build"]
            assert bld["context"] == ".."
            assert re.fullmatch(r"deploy/\w+\.Dockerfile", bld["dockerfile"])
            assert (Path("/app") / bld["dockerfile"]).exists()

    def test_backend_requirements_filter(self):
        df = (DEPLOY / "backend.Dockerfile").read_text()
        cmd = re.search(r"grep -vE '([^']+)' requirements.txt", df).group(1)
        r = subprocess.run(["grep", "-vE", cmd, "/app/backend/requirements.txt"], capture_output=True, text=True)
        names = [re.split(r"[=<>\[ ]", ln)[0].lower() for ln in r.stdout.splitlines() if ln.strip()]
        for bad in ["pytest", "pytest-xdist", "black", "isort", "flake8", "mypy"]:
            assert bad not in names
        for good in ["fastapi", "uvicorn", "motor", "emergentintegrations", "cryptography", "bcrypt", "pandas"]:
            assert good in names

    def test_frontend_dockerfile(self):
        df = (DEPLOY / "frontend.Dockerfile").read_text()
        assert "COPY frontend/package.json deploy/frontend.yarn.loc[k] ./" in df
        assert 'REACT_APP_BACKEND_URL=""' in df
        assert "COPY --from=build /app/build /srv" in df


# --- .dockerignore ---
def _ignored(path, patterns):
    hit = False
    for p in patterns:
        neg = p.startswith("!")
        pat = p[1:] if neg else p
        regs = [pat, pat + "/*"]
        if pat.startswith("**/"):
            regs += [pat[3:], pat[3:] + "/*"]
        if any(fnmatch.fnmatch(path, r.replace("**/", "*/")) or fnmatch.fnmatch(path, r) for r in regs):
            hit = not neg
    return hit


class TestDockerignore:
    pats = [l.strip() for l in Path("/app/.dockerignore").read_text().splitlines() if l.strip() and not l.startswith("#")]

    def test_excludes(self):
        for p in [".git/config", "frontend/node_modules/react/index.js", "backend/.env", "frontend/.env",
                  "frontend/build/index.html"]:
            assert _ignored(p, self.pats), p

    def test_includes(self):
        for p in ["deploy/frontend.yarn.lock", "backend/server.py", "backend/config.py", "frontend/src/App.js",
                  "frontend/package.json", "deploy/Caddyfile", "backend/requirements.txt"]:
            assert not _ignored(p, self.pats), p
