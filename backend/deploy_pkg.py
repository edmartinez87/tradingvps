"""Builds the downloadable source package (zip) for self-hosting the app on a VPS. Secrets, databases, node_modules and builds are never included."""
import io
import json
import os
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

PKG_NAME = "ai-trader"
INCLUDE_DIRS = ("backend", "frontend", "deploy", "scripts")
INCLUDE_ROOT_FILES = (".dockerignore",)
EXCLUDE_DIRS = {"node_modules", "__pycache__", ".git", "build", "build_vps", "backups", "tests", ".pytest_cache", ".ruff_cache", "coverage", ".cache"}
EXCLUDE_FILES = {"backend.env", ".DS_Store", "VERSION"}
EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".log", ".enc")
README = ("# AI Trader · Bybit AI Trader + HotForex AI Trading\n\n"
          "Paquete completo del código fuente para instalarlo en tu propio servidor (VPS).\n\n"
          "Guía paso a paso: `deploy/INSTALACION.md` (también está en el panel, botón «Instalar en tu VPS»).\n\n"
          "Resumen: sube este zip a tu VPS, descomprímelo y ejecuta `sudo bash deploy/install.sh`.\n")


def source_root() -> Optional[Path]:
    """Repo root (contains backend/, frontend/ and deploy/). Overridable with APP_SOURCE_DIR (Docker mounts the tree read-only)."""
    env = os.environ.get("APP_SOURCE_DIR")
    candidates = [Path(env)] if env else []
    candidates.append(Path(__file__).resolve().parents[1])
    for c in candidates:
        if all((c / d).is_dir() for d in ("backend", "frontend", "deploy")):
            return c
    return None


def version(root: Optional[Path] = None) -> dict:
    root = root or source_root()
    if root is None:
        return {"version": "desconocida", "commit_date": None, "source": "none"}
    try:
        out = subprocess.run(["git", "-C", str(root), "log", "-1", "--format=%h|%cI"], capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and "|" in out.stdout:
            h, d = out.stdout.strip().split("|", 1)
            return {"version": h, "commit_date": d, "source": "git"}
    except (OSError, subprocess.SubprocessError):
        pass
    vf = root / "VERSION"
    if vf.is_file():
        try:
            data = json.loads(vf.read_text())
            return {"version": str(data.get("version", "desconocida")), "commit_date": data.get("commit_date"), "source": "file"}
        except (ValueError, OSError):
            pass
    return {"version": "dev", "commit_date": None, "source": "none"}


def _skip(rel: Path) -> bool:
    parts = rel.parts
    if any(p in EXCLUDE_DIRS for p in parts[:-1]):
        return True
    name = parts[-1]
    if name in EXCLUDE_FILES or name == ".env" or name.startswith(".env.") or name.endswith(EXCLUDE_SUFFIXES):
        return True
    return False


def iter_files(root: Path):
    for d in INCLUDE_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file() and not p.is_symlink():
                rel = p.relative_to(root)
                if not _skip(rel):
                    yield rel, p
    for f in INCLUDE_ROOT_FILES:
        p = root / f
        if p.is_file():
            yield Path(f), p


def info() -> dict:
    root = source_root()
    v = version(root)
    if root is None:
        return {"available": False, **v, "files": 0, "source_mb": 0, "package": None,
                "reason": "Esta instalación no incluye el código fuente: descarga el paquete desde el panel de desarrollo (preview) o monta el código en APP_SOURCE_DIR."}
    files = list(iter_files(root))
    size = sum(p.stat().st_size for _, p in files)
    return {"available": True, **v, "files": len(files), "source_mb": round(size / 1048576, 2), "package": filename(v),
            "contents": [f"{d}/" for d in INCLUDE_DIRS if (root / d).is_dir()] + list(INCLUDE_ROOT_FILES) + ["VERSION", "README.md"],
            "excluded": ["archivos .env y backend.env (secretos)", "base de datos y copias de seguridad", "node_modules y builds", "tests y cachés"]}


def filename(v: dict) -> str:
    return f"{PKG_NAME}-{v['version']}-{datetime.now(timezone.utc).strftime('%Y%m%d')}.zip"


def build() -> tuple[bytes, str, dict]:
    """Returns (zip_bytes, filename, version). Everything is placed under a top-level `ai-trader/` folder."""
    root = source_root()
    if root is None:
        raise FileNotFoundError("código fuente no disponible")
    v = version(root)
    lock = root / "frontend" / "yarn.lock"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for rel, p in iter_files(root):
            if rel.as_posix() == "deploy/frontend.yarn.lock" and lock.is_file():
                continue
            z.write(p, f"{PKG_NAME}/{rel.as_posix()}")
        if lock.is_file():
            z.write(lock, f"{PKG_NAME}/deploy/frontend.yarn.lock")
        z.writestr(f"{PKG_NAME}/VERSION", json.dumps({**v, "built_at": datetime.now(timezone.utc).isoformat()}, indent=2) + "\n")
        z.writestr(f"{PKG_NAME}/README.md", README)
    return buf.getvalue(), filename(v), v
