"""Weekly Telegram summary: preview and manual send."""
from fastapi import HTTPException

import weekly
from deps import engine, db, protected_router

router = protected_router()


@router.get("/weekly-summary")
async def weekly_summary_preview():
    w = await weekly.build_weekly(engine, db)
    last = await db.weekly.find_one({"_id": "latest"}, {"_id": 0, "sent_at": 1})
    return {**w, "text": weekly.format_weekly(w), "last_sent_at": (last or {}).get("sent_at")}


@router.post("/weekly-summary/send")
async def weekly_summary_send():
    try:
        return await weekly.send_weekly(engine, db, force=True)
    except Exception as e:
        raise HTTPException(424, str(e)[:200])
