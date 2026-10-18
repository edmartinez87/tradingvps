import os
import time
import bcrypt
import jwt
from fastapi import Request, HTTPException

ALGO = "HS256"
TOKEN_TTL = 7 * 86400
MAX_ATTEMPTS = 5
LOCK_SEC = 900
_attempts: dict = {}


def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()


def verify_password(p: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(p.encode(), h.encode())
    except ValueError:
        return False


def create_token(version: int) -> str:
    now = int(time.time())
    return jwt.encode({"v": version, "iat": now, "exp": now + TOKEN_TTL}, os.environ["JWT_SECRET"], algorithm=ALGO)


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[-1].strip() if fwd else (request.client.host if request.client else "?")


_global = {"n": 0, "until": 0.0, "window": 0.0}
GLOBAL_MAX = 20


def check_locked(ip: str):
    now = time.time()
    if _global["until"] > now:
        raise HTTPException(429, f"Demasiados intentos fallidos. Espera {int(_global['until'] - now)} segundos.")
    rec = _attempts.get(ip)
    if rec and rec["until"] > now:
        raise HTTPException(429, f"Demasiados intentos fallidos. Espera {int(rec['until'] - now)} segundos.")


def register_failure(ip: str) -> int:
    now = time.time()
    if now - _global["window"] > LOCK_SEC:
        _global.update(n=0, window=now)
    _global["n"] += 1
    if _global["n"] >= GLOBAL_MAX:
        _global.update(until=now + LOCK_SEC, n=0)
    rec = _attempts.setdefault(ip, {"n": 0, "until": 0})
    rec["n"] += 1
    if rec["n"] >= MAX_ATTEMPTS:
        rec["until"], rec["n"] = now + LOCK_SEC, 0
        return 0
    return MAX_ATTEMPTS - rec["n"]


def clear_failures(ip: str):
    _attempts.pop(ip, None)


def make_require_auth(get_version):
    async def require_auth(request: Request) -> dict:
        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            raise HTTPException(401, "No autenticado")
        try:
            claims = jwt.decode(auth[7:], os.environ["JWT_SECRET"], algorithms=[ALGO])
        except jwt.PyJWTError:
            raise HTTPException(401, "Sesión inválida o expirada")
        if claims.get("v") != get_version():
            raise HTTPException(401, "Sesión cerrada: la clave de acceso cambió")
        return claims
    return require_auth
