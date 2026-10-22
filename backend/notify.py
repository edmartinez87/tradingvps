import logging
import httpx

logger = logging.getLogger("notify")
TG = "https://api.telegram.org/bot{token}/{method}"
_cfg = {"enabled": False, "token": "", "chat_id": "", "alerts": {}}


def configure(enabled: bool, token: str, chat_id: str, alerts: dict):
    _cfg.update(enabled=enabled, token=token or "", chat_id=str(chat_id or ""), alerts=alerts or {})


def is_on(kind: str = None) -> bool:
    return bool(_cfg["enabled"] and _cfg["token"] and _cfg["chat_id"] and (kind is None or _cfg["alerts"].get(kind, True)))


async def send(text: str, token: str = None, chat_id: str = None) -> bool:
    token, chat_id = token or _cfg["token"], chat_id or _cfg["chat_id"]
    if not token or not chat_id:
        raise RuntimeError("Telegram no configurado: faltan token o chat ID")
    async with httpx.AsyncClient(timeout=12) as c:
        r = await c.post(TG.format(token=token, method="sendMessage"),
                         json={"chat_id": chat_id, "text": text[:4000], "parse_mode": "HTML", "disable_web_page_preview": True})
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("description", "Error de Telegram"))
    return True


async def notify(text: str, kind: str):
    """Fire-and-forget alert honouring the per-kind toggles; never raises."""
    if not is_on(kind):
        return False
    try:
        return await send(text)
    except Exception as e:
        logger.warning(f"telegram {kind}: {e}")
        return False


async def send_document(data: bytes, filename: str, caption: str = "") -> bool:
    """Uploads a file to the configured chat (Telegram bots accept up to 50 MB)."""
    token, chat_id = _cfg["token"], _cfg["chat_id"]
    if not token or not chat_id:
        raise RuntimeError("Telegram no configurado: faltan token o chat ID")
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(TG.format(token=token, method="sendDocument"), data={"chat_id": chat_id, "caption": caption[:1000], "parse_mode": "HTML"},
                         files={"document": (filename, data, "application/octet-stream")})
    out = r.json()
    if not out.get("ok"):
        raise RuntimeError(out.get("description", "Error de Telegram"))
    return True


async def get_chats(token: str) -> list:
    async with httpx.AsyncClient(timeout=12) as c:
        r = await c.get(TG.format(token=token, method="getUpdates"), params={"limit": 100})
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("description", "Token de Telegram inválido"))
    chats = {}
    for u in data.get("result", []):
        msg = u.get("message") or u.get("channel_post") or u.get("my_chat_member", {}).get("chat") and {"chat": u["my_chat_member"]["chat"]}
        chat = (msg or {}).get("chat")
        if chat:
            name = chat.get("title") or " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x) or chat.get("username") or str(chat["id"])
            chats[chat["id"]] = {"id": str(chat["id"]), "name": name, "type": chat.get("type", "private")}
    return list(chats.values())


async def get_me(token: str) -> dict:
    async with httpx.AsyncClient(timeout=12) as c:
        r = await c.get(TG.format(token=token, method="getMe"))
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("description", "Token de Telegram inválido"))
    return {"username": data["result"].get("username"), "name": data["result"].get("first_name")}
