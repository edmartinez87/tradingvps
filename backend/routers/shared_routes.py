"""Endpoints shared by both bots (session, password, Telegram/AI connection tests). Registered on each protected router."""
from fastapi import HTTPException
from pydantic import BaseModel, Field

import notify
from auth import hash_password, verify_password, create_token
from ai_advisor import ping as ai_ping, current as ai_current
from deps import store


class PasswordChange(BaseModel):
    current: str = Field(min_length=1, max_length=200)
    new: str = Field(min_length=8, max_length=200)


class ChatsRequest(BaseModel):
    token: str = ""


def add_shared_routes(router, engine, label: str):
    @router.get("/auth/me")
    async def auth_me():
        return {"ok": True}

    @router.post("/auth/password")
    async def change_password(body: PasswordChange):
        if not verify_password(body.current, store.cfg.password_hash):
            raise HTTPException(401, "La clave actual no es correcta")
        version = store.cfg.token_version + 1
        await store.update({"password_hash": hash_password(body.new), "token_version": version})
        await engine.log("INFO", "Clave de acceso cambiada · sesiones anteriores cerradas")
        return {"token": create_token(version)}

    @router.post("/telegram/chats")
    async def telegram_chats(body: ChatsRequest):
        token = body.token.strip() if body.token and not body.token.startswith("••") else store.cfg.telegram_bot_token
        if not token:
            raise HTTPException(400, "Introduce el token del bot primero")
        try:
            return {"bot": await notify.get_me(token), "chats": await notify.get_chats(token)}
        except Exception as e:
            raise HTTPException(424, str(e)[:200])

    @router.post("/telegram/test")
    async def telegram_test():
        acc = await engine.account_summary()
        try:
            await notify.send(f"✅ <b>{label}</b> conectado.\nEquidad ${acc['equity']:,.2f} · {acc['open_positions']} posiciones abiertas · bot {'ACTIVO' if engine.running else 'DETENIDO'}")
        except Exception as e:
            raise HTTPException(424, str(e)[:200])
        return {"ok": True}

    @router.post("/ai/test")
    async def ai_test():
        try:
            return {"ok": True, "reply": await ai_ping(), **ai_current()}
        except Exception as e:
            raise HTTPException(424, f"Error IA: {str(e)[:200]}")
