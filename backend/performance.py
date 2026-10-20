from shadow import shadow_stats


def _row(r: dict) -> dict:
    n, gl = r["n"], abs(r["gl"])
    return {
        "key": r["_id"], "trades": n, "wins": r["wins"],
        "win_rate": round(r["wins"] / n * 100, 1) if n else 0,
        "pnl": round(r["pnl"], 2), "fees": round(r["fees"], 2),
        "avg_pnl": round(r["pnl"] / n, 2) if n else 0,
        "profit_factor": round(r["gw"] / gl, 2) if gl else None,
    }


async def _group(db, field: str) -> list:
    pipe = [{"$group": {
        "_id": f"${field}", "n": {"$sum": 1}, "pnl": {"$sum": "$pnl"}, "fees": {"$sum": "$fees"},
        "wins": {"$sum": {"$cond": [{"$gt": ["$pnl", 0]}, 1, 0]}},
        "gw": {"$sum": {"$cond": [{"$gt": ["$pnl", 0]}, "$pnl", 0]}},
        "gl": {"$sum": {"$cond": [{"$lte": ["$pnl", 0]}, "$pnl", 0]}},
    }}, {"$sort": {"pnl": -1}}]
    return [_row(r) for r in await db.trades.aggregate(pipe).to_list(50)]


async def performance(db) -> dict:
    decisions = {r["_id"]: r["n"] async for r in db.signals.aggregate([{"$group": {"_id": "$ai_decision", "n": {"$sum": 1}}}])}
    return {
        "by_strategy": await _group(db, "strategy"), "by_symbol": await _group(db, "symbol"),
        "by_side": await _group(db, "side"), "by_reason": await _group(db, "reason"),
        "signals": {"total": sum(decisions.values()), "executed": await db.signals.count_documents({"executed": True}),
                    "by_decision": decisions},
        "shadow": await shadow_stats(db),
    }
