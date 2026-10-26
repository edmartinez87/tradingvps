"""Read-only access to the project's source for the AI expert chat. Never serves .env, backups, lockfiles or anything outside the allowed roots."""
import os
import re

ROOTS = ("/app/backend", "/app/frontend/src", "/app/deploy", "/app/memory/PRD.md", "/app/README.md", "/app/.emergent/crons.yml")
DENY_PARTS = (".env", "backups", "node_modules", "__pycache__", ".git", "test_reports", "yarn.lock", ".pytest_cache", ".runtime", "browser_runs")
TEXT_EXT = (".py", ".js", ".jsx", ".ts", ".tsx", ".css", ".md", ".yml", ".yaml", ".json", ".sh", ".txt", ".ini", ".cfg", ".toml", ".html", "Dockerfile", "Caddyfile")
MAX_LINES = 300
MAX_HITS = 40


def _allowed(path: str) -> bool:
    p = os.path.realpath(path)
    if any(part in p.split(os.sep) or part in os.path.basename(p) for part in DENY_PARTS):
        return False
    return any(p == r or p.startswith(r.rstrip("/") + "/") for r in ROOTS)


def _resolve(path: str) -> str:
    path = (path or "").strip() or "/app/backend"
    if not path.startswith("/"):
        path = os.path.join("/app", path)
    p = os.path.realpath(path)
    if not _allowed(p):
        raise ValueError(f"Ruta no permitida: {path}. Zonas accesibles: {', '.join(ROOTS)} (nunca .env, backups ni node_modules)")
    return p


def list_dir(path: str) -> dict:
    p = _resolve(path)
    if os.path.isfile(p):
        return {"path": p, "type": "file", "lines": sum(1 for _ in open(p, errors="ignore"))}
    entries = []
    for name in sorted(os.listdir(p)):
        full = os.path.join(p, name)
        if not _allowed(full):
            continue
        if os.path.isdir(full):
            entries.append({"name": name + "/", "type": "dir"})
        elif name.endswith(TEXT_EXT) or name in TEXT_EXT:
            try:
                entries.append({"name": name, "type": "file", "lines": sum(1 for _ in open(full, errors="ignore"))})
            except OSError:
                pass
    return {"path": p, "type": "dir", "entries": entries[:200]}


def read_file(path: str, start: int = 1, end: int = None) -> dict:
    p = _resolve(path)
    if not os.path.isfile(p):
        raise ValueError(f"No es un archivo: {path}")
    if not (p.endswith(TEXT_EXT) or os.path.basename(p) in TEXT_EXT):
        raise ValueError("Solo se pueden leer archivos de texto/código")
    with open(p, errors="ignore") as f:
        lines = f.read().splitlines()
    start = max(1, int(start or 1))
    end = min(len(lines), int(end) if end else start + MAX_LINES - 1, start + MAX_LINES - 1)
    body = "\n".join(f"{i:>5}| {lines[i - 1]}" for i in range(start, end + 1))
    return {"path": p, "total_lines": len(lines), "from": start, "to": end, "content": body,
            "note": f"Mostradas {end - start + 1} de {len(lines)} líneas; pide otro rango con start/end si necesitas más." if end < len(lines) else None}


def search(query: str, path: str = None, regex: bool = False) -> dict:
    if not query or len(query) < 2:
        raise ValueError("Indica un texto de al menos 2 caracteres")
    root = _resolve(path or "/app/backend")
    pat = re.compile(query if regex else re.escape(query), re.IGNORECASE)
    hits, scanned = [], 0
    roots = [root] if os.path.isfile(root) else []
    if not roots:
        for base, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if _allowed(os.path.join(base, d))]
            roots.extend(os.path.join(base, f) for f in files if (f.endswith(TEXT_EXT) or f in TEXT_EXT) and _allowed(os.path.join(base, f)))
    for fp in roots:
        scanned += 1
        try:
            with open(fp, errors="ignore") as f:
                for i, line in enumerate(f, 1):
                    if pat.search(line):
                        hits.append({"file": fp, "line": i, "text": line.rstrip()[:200]})
                        if len(hits) >= MAX_HITS:
                            return {"query": query, "root": root, "files_scanned": scanned, "hits": hits, "truncated": True}
        except OSError:
            continue
    return {"query": query, "root": root, "files_scanned": scanned, "hits": hits, "truncated": False}
