import time
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from bson import ObjectId
from models import Settings, Position, Trade, Signal, LogEntry, now_iso
from market import MarketData, HTF
from indicators import build_df, trend_label, htf_trend
from strategies import evaluate, STRATEGY_INFO
from risk import FEE_RATE, SLIPPAGE, position_size, pnl, check_exit, update_trailing
from ai_advisor import evaluate_signal
from plan import SCENARIOS, build_checkin

logger = logging.getLogger("engine")
INITIAL_BALANCE = 500.0


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class TradingEngine:
    def __init__(self, db):
        self.db = db
        self.market = MarketData()
        self.lock = asyncio.Lock()
        self.running = False
        self.scanning = False
        self.last_scan = None
        self.next_scan_ts = None
        self.analysis = {}
        self.signal_keys = set()
        self.scan_event = asyncio.Event()
        self.tasks = []
        self._last_snapshot = 0.0

    async def init(self):
        await self.market.detect()
        if not await self.db.settings.find_one({"_id": "main"}):
            await self.db.settings.insert_one({"_id": "main", **Settings().model_dump()})
        if not await self.db.account.find_one({"_id": "main"}):
            await self._new_account()
        self.running = (await self.get_settings()).bot_running
        async for s in self.db.signals.find({}, {"key": 1}).sort("_id", -1).limit(500):
            if s.get("key"):
                self.signal_keys.add(s["key"])
        await self.log("INFO", f"Motor iniciado · fuente de datos {self.market.provider.upper()} · bot {'ACTIVO' if self.running else 'DETENIDO'}")
        self.tasks = [asyncio.create_task(self._monitor_loop()), asyncio.create_task(self._scan_loop())]

    async def shutdown(self):
        for t in self.tasks:
            t.cancel()
        await self.market.client.aclose()

    async def _new_account(self, initial: float = INITIAL_BALANCE):
        await self.db.account.replace_one({"_id": "main"}, {
            "_id": "main", "initial_balance": initial, "balance": initial,
            "peak_equity": initial, "max_drawdown": 0.0, "day": today(),
            "day_start_equity": initial, "daily_paused": False, "created_at": now_iso(),
        }, upsert=True)

    async def get_settings(self) -> Settings:
        return Settings.model_validate(await self.db.settings.find_one({"_id": "main"}))

    async def update_settings(self, patch: dict) -> Settings:
        current = (await self.get_settings()).model_dump()
        current.update({k: v for k, v in patch.items() if v is not None})
        s = Settings.model_validate(current)
        await self.db.settings.update_one({"_id": "main"}, {"$set": s.model_dump()})
        await self.log("INFO", "Configuración actualizada")
        self.scan_event.set()
        return s

    async def log(self, level: str, message: str):
        await self.db.logs.insert_one(LogEntry(level=level, message=message).to_mongo())
        logger.info(f"[{level}] {message}")

    async def start(self):
        self.running = True
        await self.db.settings.update_one({"_id": "main"}, {"$set": {"bot_running": True}})
        await self.log("INFO", "Bot ACTIVADO · operando 24/7 en modo paper trading")
        self.scan_event.set()

    async def stop(self):
        self.running = False
        await self.db.settings.update_one({"_id": "main"}, {"$set": {"bot_running": False}})
        await self.log("INFO", "Bot DETENIDO · las posiciones abiertas siguen protegidas por SL/TP")

    async def reset_account(self, initial: float = None):
        initial = initial or INITIAL_BALANCE
        async with self.lock:
            for col in ("positions", "trades", "signals", "equity"):
                await self.db[col].delete_many({})
            await self._new_account(initial)
        await self.log("INFO", f"Cuenta paper reiniciada a ${initial:,.0f} USDT")

    async def account_summary(self) -> dict:
        acc = await self.db.account.find_one({"_id": "main"})
        positions = await self.db.positions.find({}, {"unrealized_pnl": 1, "margin": 1}).to_list(100)
        unreal = sum(p["unrealized_pnl"] for p in positions)
        used = sum(p["margin"] for p in positions)
        equity = acc["balance"] + unreal
        agg = await self.db.trades.aggregate([{"$group": {
            "_id": None, "n": {"$sum": 1}, "realized": {"$sum": "$pnl"},
            "wins": {"$sum": {"$cond": [{"$gt": ["$pnl", 0]}, 1, 0]}},
            "gw": {"$sum": {"$cond": [{"$gt": ["$pnl", 0]}, "$pnl", 0]}},
            "gl": {"$sum": {"$cond": [{"$lte": ["$pnl", 0]}, "$pnl", 0]}},
        }}]).to_list(1)
        st = agg[0] if agg else {"n": 0, "realized": 0, "wins": 0, "gw": 0, "gl": 0}
        daily = equity - acc["day_start_equity"]
        return {
            "initial_balance": acc["initial_balance"], "balance": round(acc["balance"], 2),
            "equity": round(equity, 2), "unrealized_pnl": round(unreal, 2),
            "unrealized_pct": round(unreal / acc["balance"] * 100, 2) if acc["balance"] else 0,
            "used_margin": round(used, 2), "available": round(acc["balance"] - used, 2),
            "daily_pnl": round(daily, 2), "daily_pnl_pct": round(daily / acc["day_start_equity"] * 100, 2),
            "daily_paused": acc["daily_paused"], "total_trades": st["n"], "wins": st["wins"],
            "win_rate": round(st["wins"] / st["n"] * 100, 1) if st["n"] else 0,
            "realized_pnl": round(st["realized"], 2),
            "profit_factor": round(st["gw"] / abs(st["gl"]), 2) if st["gl"] else None,
            "total_return_pct": round((equity - acc["initial_balance"]) / acc["initial_balance"] * 100, 2),
            "max_drawdown": round(acc["max_drawdown"], 2), "peak_equity": round(acc["peak_equity"], 2),
            "open_positions": len(positions),
        }

    async def checkin(self, settings: Settings = None, summary: dict = None) -> dict:
        settings = settings or await self.get_settings()
        s = summary or await self.account_summary()
        acc = await self.db.account.find_one({"_id": "main"})
        since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        agg = await self.db.trades.aggregate([{"$match": {"closed_at": {"$gte": since}}}, {"$group": {
            "_id": None, "n": {"$sum": 1}, "pnl": {"$sum": "$pnl"},
            "wins": {"$sum": {"$cond": [{"$gt": ["$pnl", 0]}, 1, 0]}},
            "gw": {"$sum": {"$cond": [{"$gt": ["$pnl", 0]}, "$pnl", 0]}},
            "gl": {"$sum": {"$cond": [{"$lte": ["$pnl", 0]}, "$pnl", 0]}},
        }}]).to_list(1)
        a = agg[0] if agg else {"n": 0, "pnl": 0.0, "wins": 0, "gw": 0.0, "gl": 0.0}
        last30 = {"trades": a["n"], "pnl": round(a["pnl"], 2), "win_rate": round(a["wins"] / a["n"] * 100, 1) if a["n"] else 0,
                  "profit_factor": round(a["gw"] / abs(a["gl"]), 2) if a["gl"] else None,
                  "return_pct": round(a["pnl"] / (s["equity"] - a["pnl"]) * 100, 2) if s["equity"] - a["pnl"] > 0 else 0}
        days = (datetime.now(timezone.utc) - datetime.fromisoformat(acc["created_at"])).days
        rate = SCENARIOS.get(settings.plan_scenario, SCENARIOS["base"])["rate"]
        return build_checkin(s, acc, last30, settings, rate, days)

    async def _monitor_loop(self):
        while True:
            try:
                await self._monitor_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception(f"monitor error: {e}")
            await asyncio.sleep(5)

    async def _monitor_once(self):
        tickers = await self.market.fetch_tickers()
        settings = await self.get_settings()
        async for doc in self.db.positions.find():
            p = Position.from_mongo(doc)
            t = tickers.get(p.symbol)
            if not t:
                continue
            price = t["price"]
            hit, reason = check_exit(p.side, p.sl, p.tp, price, price)
            if hit is not None:
                if reason == "SL" and p.breakeven:
                    reason = "TRAILING"
                await self.close_position(p.id, price, reason)
                continue
            updates = {"mark_price": price, "unrealized_pnl": round(pnl(p.side, p.entry_price, price, p.qty), 4)}
            if settings.trailing_enabled:
                new_sl, be = update_trailing(p.side, p.entry_price, p.sl, p.initial_sl, p.atr, price)
                if new_sl != p.sl:
                    updates.update(sl=new_sl, breakeven=be)
                    if be and not p.breakeven:
                        await self.log("RISK", f"{p.symbol}: stop movido a breakeven ({new_sl:.6g})")
            await self.db.positions.update_one({"_id": ObjectId(p.id)}, {"$set": updates})
        await self._update_account_metrics(settings)

    async def _update_account_metrics(self, settings: Settings):
        s = await self.account_summary()
        acc = await self.db.account.find_one({"_id": "main"})
        upd = {}
        if acc["day"] != today():
            upd.update(day=today(), day_start_equity=s["equity"], daily_paused=False)
            await self.log("INFO", f"Nuevo día de trading · equidad inicial ${s['equity']:,.2f}")
            c = await self.checkin(settings, s)
            await self.log("PLAN", c["message"] + (" · ".join([""] + c["warnings"]) if c["warnings"] else ""))
        elif not acc["daily_paused"] and s["daily_pnl_pct"] <= -settings.daily_loss_limit:
            upd["daily_paused"] = True
            await self.log("RISK", f"Límite de pérdida diaria ({settings.daily_loss_limit}%) alcanzado · nuevas entradas pausadas hasta mañana (UTC)")
        peak = max(acc["peak_equity"], s["equity"])
        dd = (peak - s["equity"]) / peak * 100 if peak else 0
        upd.update(peak_equity=peak, max_drawdown=max(acc["max_drawdown"], dd))
        await self.db.account.update_one({"_id": "main"}, {"$set": upd})
        if time.time() - self._last_snapshot >= 60:
            self._last_snapshot = time.time()
            await self.db.equity.insert_one({"ts": now_iso(), "equity": s["equity"], "balance": s["balance"]})

    async def open_position(self, symbol: str, sig: dict, settings: Settings, signal_id: str):
        async with self.lock:
            open_syms = [p["symbol"] for p in await self.db.positions.find({}, {"symbol": 1}).to_list(100)]
            if symbol in open_syms or len(open_syms) >= settings.max_positions:
                await self.log("RISK", f"{symbol}: apertura cancelada · límite de posiciones o par ya abierto")
                return None
            price = self.market.tickers.get(symbol, {}).get("price") or sig["price"]
            long = sig["side"] == "long"
            entry = price * (1 + SLIPPAGE) if long else price * (1 - SLIPPAGE)
            sl = entry - (sig["price"] - sig["sl"])
            tp = entry + (sig["tp"] - sig["price"])
            s = await self.account_summary()
            qty, margin = position_size(s["equity"], s["available"], settings.risk_per_trade, entry, sl, settings.leverage, symbol)
            if qty <= 0 or margin < 1:
                await self.log("RISK", f"{symbol}: tamaño por debajo del lote mínimo de Bybit o margen insuficiente · aumenta capital o riesgo")
                return None
            fee = entry * qty * FEE_RATE
            pos = Position(symbol=symbol, side=sig["side"], strategy=sig["strategy"], entry_price=entry, qty=qty,
                           leverage=settings.leverage, margin=margin, sl=sl, tp=tp, initial_sl=sl, atr=sig["atr"],
                           fees=fee, mark_price=price, signal_id=signal_id)
            res = await self.db.positions.insert_one(pos.to_mongo())
            pos.id = str(res.inserted_id)
            await self.db.account.update_one({"_id": "main"}, {"$inc": {"balance": -fee}})
        await self.log("ORDER", f"ABIERTA {sig['side'].upper()} {symbol} @ {entry:.6g} · qty {qty:.6g} · {settings.leverage}x · SL {sl:.6g} · TP {tp:.6g}")
        return pos

    async def close_position(self, pos_id: str, price: float = None, reason: str = "MANUAL"):
        async with self.lock:
            doc = await self.db.positions.find_one_and_delete({"_id": ObjectId(pos_id)})
            if not doc:
                return None
            p = Position.from_mongo(doc)
            price = price or self.market.tickers.get(p.symbol, {}).get("price") or p.mark_price
            if reason != "TP":
                price = price * (1 - SLIPPAGE) if p.side == "long" else price * (1 + SLIPPAGE)
            exit_fee = price * p.qty * FEE_RATE
            gross = pnl(p.side, p.entry_price, price, p.qty)
            net = gross - p.fees - exit_fee
            await self.db.account.update_one({"_id": "main"}, {"$inc": {"balance": gross - exit_fee}})
            trade = Trade(symbol=p.symbol, side=p.side, strategy=p.strategy, entry_price=p.entry_price, exit_price=price,
                          qty=p.qty, leverage=p.leverage, margin=p.margin, pnl=round(net, 4),
                          pnl_pct=round(net / p.margin * 100, 2), fees=round(p.fees + exit_fee, 4),
                          reason=reason, opened_at=p.opened_at)
            res = await self.db.trades.insert_one(trade.to_mongo())
            trade.id = str(res.inserted_id)
        await self.log("ORDER", f"CERRADA {p.side.upper()} {p.symbol} @ {price:.6g} · {reason} · PnL {net:+.2f} USDT")
        return trade

    async def _scan_loop(self):
        await asyncio.sleep(2)
        while True:
            settings = await self.get_settings()
            try:
                await self.scan_once(settings)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception("scan error")
                await self.log("ERROR", f"Error en escaneo: {e}")
            self.next_scan_ts = time.time() + settings.scan_interval_sec
            try:
                await asyncio.wait_for(self.scan_event.wait(), timeout=settings.scan_interval_sec)
            except asyncio.TimeoutError:
                pass
            self.scan_event.clear()

    async def scan_once(self, settings: Settings):
        self.scanning = True
        found = 0
        htf_tf = HTF[settings.timeframe]
        try:
            for symbol in settings.symbols:
                try:
                    params = settings.symbol_params.get(symbol) or {}
                    df = build_df(await self.market.fetch_klines(symbol, settings.timeframe, 300), int(params.get("atr_period", 14)))
                    i = len(df) - 2
                    row = df.iloc[i]
                    htf = None
                    if settings.htf_filter:
                        htf = htf_trend(build_df(await self.market.fetch_klines(symbol, htf_tf, 200, cache_sec=120)))
                    sig = evaluate(df, i, settings.strategy, htf, params)
                    self.analysis[symbol] = {
                        "trend": trend_label(row), "rsi": round(float(row["rsi"]), 1),
                        "macd_hist": float(row["macd_hist"]), "adx": round(float(row["adx"]), 1),
                        "htf": htf, "signal": sig["side"] if sig else None,
                        "signal_strategy": sig["strategy"] if sig else None, "updated_at": now_iso(),
                    }
                    if sig and self.running:
                        found += 1
                        await self._handle_signal(symbol, sig, settings, df, htf, htf_tf)
                except Exception as e:
                    logger.exception(f"scan {symbol}")
                    await self.log("ERROR", f"{symbol}: {e}")
            self.last_scan = now_iso()
            if self.running:
                await self.log("SCAN", f"Escaneo {settings.timeframe} completado · {len(settings.symbols)} pares · {found} señales")
        finally:
            self.scanning = False

    async def _handle_signal(self, symbol, sig, settings: Settings, df, htf, htf_tf):
        key = f"{symbol}:{sig['strategy']}:{sig['side']}:{sig['key_ts']}"
        if key in self.signal_keys:
            return
        self.signal_keys.add(key)
        name = STRATEGY_INFO[sig["strategy"]]["name"]
        await self.log("SIGNAL", f"{symbol} {sig['side'].upper()} · {name} · {sig['score']} confirmaciones")
        acc = await self.account_summary()
        open_syms = [p["symbol"] for p in await self.db.positions.find({}, {"symbol": 1}).to_list(100)]
        block = None
        if symbol in open_syms:
            block = "ya existe una posición abierta en el par"
        elif len(open_syms) >= settings.max_positions:
            block = f"máximo de posiciones alcanzado ({settings.max_positions})"
        elif acc["daily_paused"]:
            block = "límite de pérdida diaria alcanzado"
        if block:
            await self.log("RISK", f"{symbol}: señal descartada · {block}")
            await self.db.signals.insert_one(Signal(
                symbol=symbol, side=sig["side"], strategy=sig["strategy"], timeframe=settings.timeframe,
                price=sig["price"], sl=sig["sl"], tp=sig["tp"], score=sig["score"], reasons=sig["reasons"],
                indicators=sig["indicators"], ai_decision="BLOQUEADA", note=f"Bloqueada por riesgo: {block}", key=key,
            ).to_mongo())
            return

        signal = Signal(symbol=symbol, side=sig["side"], strategy=sig["strategy"], timeframe=settings.timeframe,
                        price=sig["price"], sl=sig["sl"], tp=sig["tp"], score=sig["score"], reasons=sig["reasons"],
                        indicators=sig["indicators"], ai_decision="SIN_IA", key=key)
        approve = True
        if settings.ai_enabled:
            await self.log("AI_EVAL", f"Claude Sonnet evaluando {symbol} {sig['side'].upper()}...")
            closes = df["close"].iloc[-22:-1]
            t = self.market.tickers.get(symbol, {})
            ctx = {
                "htf_tf": htf_tf, "htf_trend": {1: "ALCISTA", -1: "BAJISTA", 0: "NEUTRAL"}.get(htf, "N/D"),
                "change_24h": t.get("change_pct", 0), "funding_rate": t.get("funding_rate", 0),
                "recent_changes": [round(x, 3) for x in (closes.pct_change().dropna() * 100).tolist()],
                "open_positions": len(open_syms), "daily_pnl_pct": acc["daily_pnl_pct"],
            }
            try:
                res = await evaluate_signal(symbol, settings.timeframe, sig, ctx)
                signal.ai_decision, signal.ai_confidence = res["decision"], res["confidence"]
                signal.ai_risk, signal.ai_reasoning = res["risk"], res["reasoning"]
                approve = res["decision"] == "APROBADA" and res["confidence"] >= settings.ai_min_confidence
                if res["decision"] == "APROBADA" and not approve:
                    signal.note = f"Confianza {res['confidence']}% menor al mínimo ({settings.ai_min_confidence}%)"
            except Exception as e:
                logger.exception("ai error")
                signal.ai_decision, signal.note, approve = "ERROR", f"Error IA: {str(e)[:180]}", False
            await self.log("AI_EVAL", f"{symbol}: {signal.ai_decision} · confianza {signal.ai_confidence}% · riesgo {signal.ai_risk}")
        res = await self.db.signals.insert_one(signal.to_mongo())
        sid = str(res.inserted_id)
        if approve:
            pos = await self.open_position(symbol, sig, settings, sid)
            if pos:
                await self.db.signals.update_one({"_id": res.inserted_id}, {"$set": {"executed": True}})
