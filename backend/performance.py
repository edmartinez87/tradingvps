from shadow import shadow_stats
from risk import FEE_RATE, MAKER_FEE


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
    pipe = [{"$addFields": {"horizon": {"$ifNull": ["$horizon", "short"]}, "entry_type": {"$ifNull": ["$entry_type", "market"]}}}, {"$group": {
        "_id": f"${field}", "n": {"$sum": 1}, "pnl": {"$sum": "$pnl"}, "fees": {"$sum": "$fees"},
        "wins": {"$sum": {"$cond": [{"$gt": ["$pnl", 0]}, 1, 0]}},
        "gw": {"$sum": {"$cond": [{"$gt": ["$pnl", 0]}, "$pnl", 0]}},
        "gl": {"$sum": {"$cond": [{"$lte": ["$pnl", 0]}, "$pnl", 0]}},
    }}, {"$sort": {"pnl": -1}}]
    return [_row(r) for r in await db.trades.aggregate(pipe).to_list(50)]


async def maker_stats(db) -> dict:
    """Fill rate of the post-only entries and the fee saved vs. taker (closed trades + open positions)."""
    pipe = [{"$addFields": {"entry_type": {"$ifNull": ["$entry_type", "market"]}}},
            {"$group": {"_id": "$entry_type", "n": {"$sum": 1}, "notional": {"$sum": {"$multiply": ["$entry_price", "$qty"]}}}}]
    rows = {}
    for col in (db.trades, db.positions):
        for r in await col.aggregate(pipe).to_list(10):
            cur = rows.setdefault(r["_id"], {"n": 0, "notional": 0.0})
            cur["n"] += r["n"]
            cur["notional"] += r["notional"]
    maker, fb = rows.get("maker", {"n": 0, "notional": 0.0}), rows.get("market_fallback", {"n": 0, "notional": 0.0})
    attempts = maker["n"] + fb["n"]
    return {"maker_fills": maker["n"], "market_fallbacks": fb["n"], "market_direct": rows.get("market", {"n": 0})["n"],
            "fill_rate": round(maker["n"] / attempts * 100, 1) if attempts else None,
            "fee_saved": round(maker["notional"] * (FEE_RATE - MAKER_FEE), 2), "pending": await db.pending_entries.count_documents({})}


async def performance(db, shadow=shadow_stats) -> dict:
    decisions = {r["_id"]: r["n"] async for r in db.signals.aggregate([{"$group": {"_id": "$ai_decision", "n": {"$sum": 1}}}])}
    return {
        "by_strategy": await _group(db, "strategy"), "by_symbol": await _group(db, "symbol"),
        "by_side": await _group(db, "side"), "by_reason": await _group(db, "reason"),
        "by_horizon": await _group(db, "horizon"), "by_entry_type": await _group(db, "entry_type"),
        "maker": await maker_stats(db),
        "signals": {"total": sum(decisions.values()), "executed": await db.signals.count_documents({"executed": True}),
                    "by_decision": decisions},
        "shadow": await shadow(db),
    }
