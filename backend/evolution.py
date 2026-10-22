"""Evolution log: every settings change (AI reviews, optimizer, walk-forward, risk profile, manual) is recorded with the account state at that
moment; the timeline then measures how the bot performed between consecutive changes (after vs. before)."""
from datetime import datetime, timezone, timedelta
from models import now_iso

IGNORE = {"bot_running", "plan_scenario", "plan_target_monthly", "plan_monthly_deposit"}
SOURCES = {"auto_review": "Revisión IA automática", "optimize_all": "Optimizar todo con IA", "optimizer": "IA sobre el optimizador", "plan": "IA sobre el plan",
           "walk_forward": "Revalidación walk-forward", "profile": "Perfil de riesgo", "manual": "Ajuste manual", "system": "Sistema"}
AI_SOURCES = ("auto_review", "optimize_all", "optimizer", "plan")
MIN_TRADES = 5


def diff(before: dict, after: dict) -> dict:
    return {k: {"antes": before.get(k), "despues": after[k]} for k in after if k not in IGNORE and before.get(k) != after.get(k)}


async def record(engine, source: str, changes: dict, summary: str = ""):
    if not changes:
        return None
    acc = await engine.account_summary()
    doc = {"ts": now_iso(), "source": source if source in SOURCES else "manual", "summary": (summary or "")[:600], "changes": changes,
           "equity": acc["equity"], "total_trades": acc["total_trades"], "mode": acc["mode"]}
    await engine.db.changes.insert_one(doc)
    return doc


def _agg(rows: list) -> dict:
    n = len(rows)
    pnl = sum(r["pnl"] for r in rows)
    wins = [r for r in rows if r["pnl"] > 0]
    gw = sum(r["pnl"] for r in wins)
    gl = sum(r["pnl"] for r in rows if r["pnl"] <= 0)
    return {"trades": n, "pnl": round(pnl, 2), "win_rate": round(len(wins) / n * 100, 1) if n else 0,
            "avg_pnl": round(pnl / n, 2) if n else 0, "profit_factor": round(gw / abs(gl), 2) if gl else None}


def verdict(before: dict, after: dict) -> str:
    if after["trades"] < MIN_TRADES:
        return "PENDIENTE"
    if before["trades"] < MIN_TRADES:
        return "MEJOR" if after["pnl"] > 0 else "PEOR" if after["pnl"] < 0 else "IGUAL"
    delta = after["avg_pnl"] - before["avg_pnl"]
    tol = max(0.02 * max(abs(before["avg_pnl"]), abs(after["avg_pnl"])), 0.01)
    return "MEJOR" if delta > tol else "PEOR" if delta < -tol else "IGUAL"


async def timeline(engine, limit: int = 40) -> dict:
    db = engine.db
    events = await db.changes.find({}, {"_id": 0}).sort("ts", -1).limit(limit).to_list(limit)
    trades = await db.trades.find({}, {"_id": 0, "closed_at": 1, "pnl": 1}).to_list(20000)
    acc = await engine.account_summary()
    now = now_iso()
    out = []
    for i, ev in enumerate(events):
        end = events[i - 1]["ts"] if i > 0 else now
        prev_ts = events[i + 1]["ts"] if i + 1 < len(events) else None
        dur = datetime.fromisoformat(end) - datetime.fromisoformat(ev["ts"])
        before_start = prev_ts or (datetime.fromisoformat(ev["ts"]) - max(dur, timedelta(days=7))).isoformat()
        after = _agg([t for t in trades if ev["ts"] <= t["closed_at"] < end])
        before = _agg([t for t in trades if before_start <= t["closed_at"] < ev["ts"]])
        equity_end = events[i - 1]["equity"] if i > 0 else acc["equity"]
        out.append({**ev, "source_label": SOURCES.get(ev["source"], ev["source"]), "ai": ev["source"] in AI_SOURCES, "window_end": end,
                    "window_days": round(dur.total_seconds() / 86400, 1), "ongoing": i == 0, "after": after, "before": before,
                    "equity_end": equity_end, "equity_delta_pct": round((equity_end - ev["equity"]) / ev["equity"] * 100, 2) if ev["equity"] else 0,
                    "verdict": verdict(before, after)})
    verdicts = [e["verdict"] for e in out]
    ai_verdicts = [e["verdict"] for e in out if e["ai"]]
    return {"events": out, "total": await db.changes.count_documents({}), "ai_changes": len(ai_verdicts),
            "better": verdicts.count("MEJOR"), "worse": verdicts.count("PEOR"), "pending": verdicts.count("PENDIENTE"),
            "ai_better": ai_verdicts.count("MEJOR"), "ai_worse": ai_verdicts.count("PEOR"), "ai_pending": ai_verdicts.count("PENDIENTE"),
            "first_at": events[-1]["ts"] if events else None, "equity": acc["equity"], "min_trades": MIN_TRADES}
