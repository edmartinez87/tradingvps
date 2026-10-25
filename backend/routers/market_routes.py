"""Crypto bot market context: BTC daily regime, weekly momentum rotation and pending maker entries."""
from deps import db, engine, protected_router
import regime
import maker

router = protected_router()


@router.get("/market/context")
async def market_context():
    s = await engine.get_settings()
    rot = await regime.current_rotation(engine, s)
    return {"regime": {**await regime.btc_regime(engine.market, s.btc_regime_sma), "enabled": s.btc_regime_filter},
            "rotation": {**rot, "enabled": s.rotation_enabled}, "pending_entries": await maker.pending_view(db),
            "entry_order_type": s.entry_order_type, "maker_wait_bars": s.maker_wait_bars, "max_long_positions": s.max_long_positions}


@router.post("/rotation/refresh")
async def rotation_refresh():
    s = await engine.get_settings()
    return await regime.current_rotation(engine, s, force=True)


@router.delete("/pending-entries")
async def cancel_pending():
    return {"cancelled": await maker.cancel_all(engine, "cancelación manual")}
