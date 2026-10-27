"""/api/chat/* — AI expert chat shared by the three bots (panel JWT required)."""
from typing import List, Any, Literal
from fastapi import HTTPException
from pydantic import BaseModel, Field
from deps import protected_router
from chat import service, proposals

router = protected_router()


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=6000)
    panel: Literal["crypto", "fx", "pepper"] = "crypto"


class MemoryIn(BaseModel):
    notes: List[Any] = Field(max_length=service.MAX_MEMORY_NOTES)


@router.get("/chat")
async def chat_state():
    return await service.state()


@router.post("/chat/message")
async def chat_message(body: MessageIn):
    try:
        return service.start(body.text.strip(), body.panel)
    except service.Busy:
        raise HTTPException(409, "La IA todavía está respondiendo al mensaje anterior")


@router.get("/chat/jobs/{job_id}")
async def chat_job(job_id: str):
    j = service.job(job_id)
    if not j:
        raise HTTPException(404, "Respuesta no encontrada (caducó o el servidor se reinició): recarga el chat")
    return j


async def _resolve(pid: str, apply: bool) -> dict:
    p = await proposals.resolve(pid, apply)
    verb = {"applied": "APLICÓ", "discarded": "DESCARTÓ", "failed": "intentó aplicar (FALLÓ)"}[p["status"]]
    event = await service.record_event(p["session_id"], f"El usuario {verb} la propuesta «{proposals.describe(p)}» · {p['result']}")
    return {"proposal": p, "event": event}


@router.post("/chat/proposals/{pid}/apply")
async def apply_proposal(pid: str):
    return await _resolve(pid, True)


@router.post("/chat/proposals/{pid}/discard")
async def discard_proposal(pid: str):
    return await _resolve(pid, False)


@router.post("/chat/new")
async def new_chat():
    try:
        return await service.new_conversation()
    except service.Busy:
        raise HTTPException(409, "Espera a que la IA termine de responder")


@router.get("/chat/memory")
async def get_memory():
    return {"notes": (await service._memory()).get("notes") or []}


@router.put("/chat/memory")
async def put_memory(body: MemoryIn):
    return {"notes": await service.set_memory(body.notes)}


@router.post("/chat/summarize")
async def summarize_now():
    s = await service.get_session()
    done = await service.maybe_summarize(str(s["_id"]), force=True)
    return {"summarized": done, **{k: v for k, v in (await service.state()).items() if k in ("session", "memory")}}
