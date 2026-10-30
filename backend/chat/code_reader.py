"""Read-only access to the project's source for the AI expert chat. Never serves .env, backups, lockfiles or anything outside the allowed roots.

Paths are *virtual*: the assistant always talks about /app/backend, /app/frontend/src and /app/deploy. They are mapped onto the real source
root — /app in the preview, the read-only mount (APP_SOURCE_DIR=/src) on a VPS — so the tools work in every deployment."""
import os
import re

from deploy_pkg import source_root

VIRTUAL_ROOT = "/app"
ROOTS = ("/app/backend", "/app/frontend/src", "/app/deploy", "/app/memory/PRD.md", "/app/README.md", "/app/.emergent/crons.yml")
DENY_PARTS = (".env", "backups", "node_modules", "__pycache__", ".git", "test_reports", "yarn.lock", ".pytest_cache", ".ruff_cache", ".runtime", "browser_runs")
TEXT_EXT = (".py", ".js", ".jsx", ".ts", ".tsx", ".css", ".md", ".yml", ".yaml", ".json", ".sh", ".txt", ".ini", ".cfg", ".toml", ".html", "Dockerfile", "Caddyfile")
MAX_LINES = 300
MAX_HITS = 40


def real_root() -> str:
    root = source_root()
    if root is None:
        raise ValueError("El código fuente no está montado en esta instalación (falta APP_SOURCE_DIR → carpeta con backend/, frontend/ y deploy/). "
                         "En el VPS el docker-compose monta el proyecto en /src; comprueba ese volumen. Mientras tanto razona con los datos guardados.")
    return str(root)


def _to_real(virtual: str) -> str:
    return os.path.join(real_root(), os.path.relpath(virtual, VIRTUAL_ROOT)) if virtual != VIRTUAL_ROOT else real_root()


def _to_virtual(real: str) -> str:
    rel = os.path.relpath(real, real_root())
    return VIRTUAL_ROOT if rel == "." else os.path.join(VIRTUAL_ROOT, rel)


def _allowed(virtual: str) -> bool:
    if any(part in virtual.split(os.sep) or part in os.path.basename(virtual) for part in DENY_PARTS):
        return False
    return any(virtual == r or virtual.startswith(r.rstrip("/") + "/") for r in ROOTS)


def _resolve(path: str) -> tuple:
    """→ (virtual, real) for an allowed path; accepts /app/..., app/..., backend/..., or paths relative to the virtual root."""
    path = (path or "").strip() or "/app/backend"
    if not path.startswith("/"):
        path = os.path.join(VIRTUAL_ROOT, path[4:] if path.startswith("app/") else path)
    virtual = os.path.normpath(path)
    if not _allowed(virtual):
        raise ValueError(f"Ruta no permitida: {path}. Zonas accesibles: {', '.join(ROOTS)} (nunca .env, backups ni node_modules)")
    real = os.path.realpath(_to_real(virtual))
    root = os.path.realpath(real_root())
    if os.path.commonpath([real, root]) != root:  # a symlink inside an allowed root must not escape the source tree
        raise ValueError(f"Ruta no permitida: {path} apunta fuera del código del proyecto")
    if not os.path.exists(real):
        raise ValueError(f"No existe {virtual} (código en {real_root()}). Usa list_code sobre {', '.join(ROOTS[:3])} para ver qué hay.")
    return virtual, real


def _is_text(name: str) -> bool:
    return name.endswith(TEXT_EXT) or name in TEXT_EXT


def list_dir(path: str) -> dict:
    virtual, real = _resolve(path)
    if os.path.isfile(real):
        return {"path": virtual, "type": "file", "lines": sum(1 for _ in open(real, errors="ignore"))}
    entries = []
    for name in sorted(os.listdir(real)):
        v, r = os.path.join(virtual, name), os.path.join(real, name)
        if not _allowed(v):
            continue
        if os.path.isdir(r):
            entries.append({"name": name + "/", "type": "dir"})
        elif _is_text(name):
            try:
                entries.append({"name": name, "type": "file", "lines": sum(1 for _ in open(r, errors="ignore"))})
            except OSError:
                pass
    return {"path": virtual, "type": "dir", "entries": entries[:200]}


def read_file(path: str, start: int = 1, end: int = None) -> dict:
    virtual, real = _resolve(path)
    if not os.path.isfile(real):
        raise ValueError(f"No es un archivo: {virtual}")
    if not _is_text(os.path.basename(real)):
        raise ValueError("Solo se pueden leer archivos de texto/código")
    with open(real, errors="ignore") as f:
        lines = f.read().splitlines()
    start = max(1, int(start or 1))
    end = min(len(lines), int(end) if end else start + MAX_LINES - 1, start + MAX_LINES - 1)
    body = "\n".join(f"{i:>5}| {lines[i - 1]}" for i in range(start, end + 1))
    return {"path": virtual, "total_lines": len(lines), "from": start, "to": end, "content": body,
            "note": f"Mostradas {end - start + 1} de {len(lines)} líneas; pide otro rango con start/end si necesitas más." if end < len(lines) else None}


def search(query: str, path: str = None, regex: bool = False) -> dict:
    if not query or len(query) < 2:
        raise ValueError("Indica un texto de al menos 2 caracteres")
    virtual, real = _resolve(path or "/app/backend")
    pat = re.compile(query if regex else re.escape(query), re.IGNORECASE)
    hits, scanned = [], 0
    files = [real] if os.path.isfile(real) else []
    if not files:
        for base, dirs, names in os.walk(real):
            vbase = _to_virtual(base)
            dirs[:] = [d for d in dirs if _allowed(os.path.join(vbase, d))]
            files.extend(os.path.join(base, f) for f in names if _is_text(f) and _allowed(os.path.join(vbase, f)))
    for fp in files:
        scanned += 1
        try:
            with open(fp, errors="ignore") as f:
                for i, line in enumerate(f, 1):
                    if pat.search(line):
                        hits.append({"file": _to_virtual(fp), "line": i, "text": line.rstrip()[:200]})
                        if len(hits) >= MAX_HITS:
                            return {"query": query, "root": virtual, "files_scanned": scanned, "hits": hits, "truncated": True}
        except OSError:
            continue
    return {"query": query, "root": virtual, "files_scanned": scanned, "hits": hits, "truncated": False}
