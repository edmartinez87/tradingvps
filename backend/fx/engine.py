"""HotForex AI Trading engine: 24/7 paper trading of forex & metals with the same pipeline as the crypto bot
(strategies → risk gates → news gate → Claude validation → paper execution), plus forex hours, weekend flatting and news trades."""
import time
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from bson import ObjectId
from models import Position, Trade, Signal, LogEntry, now_iso
from indicators import trend_label, htf_trend, snapshot
from strategies import evaluate, STRATEGY_INFO
import notify
from fx.models import FxSettings
from fx.market import FxMarket, HTF, market_open, market_status, closing_soon, in_sessions, session_names
from fx.symbols import SPECS, fmt_price, pips
from fx import risk
from fx.ai import evaluate_signal
from ai_advisor import label as ai_label
from fx.backtest import build_fx_df
from fx.live import FxLiveBroker
from fx import plan as fx_plan
from plan import last30_stats

logger = logging.getLogger("fx.engine")
INITIAL_BALANCE = 500.0
LIVE_GRACE_SEC = 20
BLOCK_BY = {"NOTICIAS": "noticias", "BLOQUEADA": "riesgo", "MERCADO": "mercado cerrado", "SESION": "sesión"}
NEWS_STRATEGY = {"news_event": {"name": "Noticia macro", "rules": "Dato de alto impacto publicado con sorpresa clara frente a la previsión; Claude fija la dirección y la confianza, el precio debe confirmar en los primeros minutos. SL/TP por ATR 15m y cierre máximo por tiempo.", "basis": "Trading de noticias: el flujo posterior a sorpresas macro (tipos, NFP, IPC) tiende a persistir durante horas."}}
FX_STRATEGY_INFO = {**STRATEGY_INFO, **NEWS_STRATEGY}


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class PrefixedDB:
    """Exposes db.<name> as db.<prefix><name> so the engine code stays collection-agnostic."""

    def __init__(self, db, prefix: str = "fx_"):
        self._db, self._prefix = db, prefix

    def __getattr__(self, name):
        return self._db[f"{self._prefix}{name}"]

    def __getitem__(self, name):
        return self._db[f"{self._prefix}{name}"]


class FxEngine:
    def __init__(self, db):
        self.db = PrefixedDB(db)
        self.market = FxMarket()
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
        self._closed_logged = False
        self._weekend_flat_day = None
        self.news = None
        self.cfg = None
        self.live = False
        self.broker = None
        self._broker_key = None
        self.broker_error = None
        self._external_warned = set()

    async def apply_config(self, cfg):
        self.cfg = cfg
        self.live = cfg.trading_mode == "live"
        key = (cfg.metaapi_token, cfg.metaapi_account_id, cfg.metaapi_region, cfg.metaapi_base_url, cfg.mt_symbol_suffix)
        if key != self._broker_key:
            if self.broker:
                await self.broker.aclose()
            self.broker = FxLiveBroker(*key) if cfg.metaapi_token and cfg.metaapi_account_id else None
            self._broker_key = key
            self.broker_error = None

    @property
    def mode_label(self) -> str:
        return "REAL" if self.live else "PAPER"

    @property
    def env(self) -> str:
        return (self.cfg.mt_server if self.cfg and self.cfg.mt_server else "HFM")

    async def tg(self, text: str, kind: str):
        await notify.notify(f"🏦 <b>HotForex AI</b>\n{text}", kind)

    async def init(self):
        await self.market.detect()
        if not await self.db.settings.find_one({"_id": "main"}):
            await self.db.settings.insert_one({"_id": "main", **FxSettings().model_dump()})
        if not await self.db.account.find_one({"_id": "main"}):
            await self._new_account()
        self.running = (await self.get_settings()).bot_running
        async for s in self.db.signals.find({}, {"key": 1}).sort("_id", -1).limit(500):
            if s.get("key"):
                self.signal_keys.add(s["key"])
        await self.log("INFO", f"Motor HotForex iniciado · datos Yahoo Finance · mercado {'ABIERTO' if market_open() else 'CERRADO'} · bot {'ACTIVO' if self.running else 'DETENIDO'}")
        self.tasks = [asyncio.create_task(self._monitor_loop()), asyncio.create_task(self._scan_loop())]

    async def shutdown(self):
        for t in self.tasks:
            t.cancel()
        await self.market.aclose()
        if self.broker:
            await self.broker.aclose()

    async def _new_account(self, initial: float = INITIAL_BALANCE):
        await self.db.account.replace_one({"_id": "main"}, {
            "_id": "main", "initial_balance": initial, "balance": initial, "peak_equity": initial, "max_drawdown": 0.0,
            "day": today(), "day_start_equity": initial, "daily_paused": False, "created_at": now_iso(),
        }, upsert=True)

    async def get_settings(self) -> FxSettings:
        return FxSettings.model_validate(await self.db.settings.find_one({"_id": "main"}))

    async def update_settings(self, patch: dict) -> FxSettings:
        current = (await self.get_settings()).model_dump()
        current.update({k: v for k, v in patch.items() if v is not None})
        s = FxSettings.model_validate(current)
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
        mode = f"REAL en HFM ({self.env})" if self.live else "paper trading"
        await self.log("INFO", f"Bot ACTIVADO · forex y metales en {mode}" + ("" if market_open() else " · el mercado está cerrado, operará al abrir"))
        await self.tg(f"▶️ <b>Bot ACTIVADO</b> · {mode} forex/metales", "orders")
        self.scan_event.set()

    async def stop(self):
        self.running = False
        await self.db.settings.update_one({"_id": "main"}, {"$set": {"bot_running": False}})
        await self.log("INFO", "Bot DETENIDO · las posiciones abiertas siguen protegidas por SL/TP")
        await self.tg("⏹ <b>Bot DETENIDO</b> · las posiciones abiertas siguen protegidas por SL/TP", "orders")

    async def reset_account(self, initial: float = None):
        if not initial and self.live:
            info = await self._broker_info(0)
            initial = info["equity"] if info else (self.cfg.hfm_verified_equity if self.cfg else None)
        initial = initial or INITIAL_BALANCE
        async with self.lock:
            for col in ("positions", "trades", "signals", "equity", "news_trades"):
                await self.db[col].delete_many({})
            await self._new_account(initial)
        await self.log("INFO", f"Estadísticas reiniciadas · capital inicial ${initial:,.2f} · modo {self.mode_label}")

    async def _broker_info(self, max_age: float = 10.0):
        if not (self.live and self.broker):
            return None
        try:
            info = await self.broker.info(max_age)
            self.broker_error = None
            return info
        except Exception as e:
            self.broker_error = str(e)[:160]
            logger.warning(f"hfm info: {e}")
            return None

    async def account_summary(self) -> dict:
        acc = await self.db.account.find_one({"_id": "main"})
        positions = await self.db.positions.find({}, {"unrealized_pnl": 1, "margin": 1}).to_list(100)
        unreal = sum(p["unrealized_pnl"] for p in positions)
        used = sum(p["margin"] for p in positions)
        balance, equity, available = acc["balance"], acc["balance"] + unreal, acc["balance"] - used
        info = await self._broker_info()
        if info:
            balance, equity, available, unreal, used = info["balance"], info["equity"], info["available"], info["unrealised"], info["margin"]
        agg = await self.db.trades.aggregate([{"$group": {
            "_id": None, "n": {"$sum": 1}, "realized": {"$sum": "$pnl"},
            "wins": {"$sum": {"$cond": [{"$gt": ["$pnl", 0]}, 1, 0]}},
            "gw": {"$sum": {"$cond": [{"$gt": ["$pnl", 0]}, "$pnl", 0]}},
            "gl": {"$sum": {"$cond": [{"$lte": ["$pnl", 0]}, "$pnl", 0]}},
        }}]).to_list(1)
        st = agg[0] if agg else {"n": 0, "realized": 0, "wins": 0, "gw": 0, "gl": 0}
        daily = equity - acc["day_start_equity"]
        return {
            "initial_balance": acc["initial_balance"], "balance": round(balance, 2), "equity": round(equity, 2),
            "unrealized_pnl": round(unreal, 2), "unrealized_pct": round(unreal / balance * 100, 2) if balance else 0,
            "used_margin": round(used, 2), "available": round(available, 2),
            "daily_pnl": round(daily, 2), "daily_pnl_pct": round(daily / acc["day_start_equity"] * 100, 2) if acc["day_start_equity"] else 0,
            "daily_paused": acc["daily_paused"], "total_trades": st["n"], "wins": st["wins"],
            "win_rate": round(st["wins"] / st["n"] * 100, 1) if st["n"] else 0, "realized_pnl": round(st["realized"], 2),
            "profit_factor": round(st["gw"] / abs(st["gl"]), 2) if st["gl"] else None,
            "total_return_pct": round((equity - acc["initial_balance"]) / acc["initial_balance"] * 100, 2) if acc["initial_balance"] else 0,
            "max_drawdown": round(acc["max_drawdown"], 2), "peak_equity": round(acc["peak_equity"], 2),
            "open_positions": len(positions), "mode": self.mode_label, "exchange_error": self.broker_error if self.live else None,
            "exchange_synced": info is not None, "currency": info["currency"] if info else "USD",
        }

    async def checkin(self, settings: FxSettings = None, summary: dict = None) -> dict:
        settings = settings or await self.get_settings()
        s = summary or await self.account_summary()
        acc = await self.db.account.find_one({"_id": "main"})
        last30 = await last30_stats(self.db, s["equity"])
        days = (datetime.now(timezone.utc) - datetime.fromisoformat(acc["created_at"])).days
        return fx_plan.build_checkin(s, acc, last30, settings, days)

    # ---------- monitor ----------
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
        settings = await self.get_settings()
        tickers = await self.market.fetch_tickers(settings.symbols)
        now = datetime.now(timezone.utc)
        if settings.close_before_weekend and closing_soon(30) and self._weekend_flat_day != today():
            self._weekend_flat_day = today()
            ids = [str(d["_id"]) async for d in self.db.positions.find({}, {"_id": 1})]
            if ids:
                await self.log("RISK", f"Cierre de fin de semana · {len(ids)} posiciones cerradas antes del cierre del mercado")
                for pid in ids:
                    await self.close_position(pid, reason="FIN_SEMANA")
        ex = None
        if self.live and self.broker:
            try:
                ex = {p["id"]: p for p in await self.broker.positions()}
                self.broker_error = None
            except Exception as e:
                self.broker_error = str(e)[:160]
                logger.warning(f"hfm positions sync: {e}")
        local_ids = set()
        async for doc in self.db.positions.find():
            p = Position.from_mongo(doc)
            if p.live:
                local_ids.add(p.order_id)
                if ex is not None:
                    await self._sync_live_position(p, ex.get(p.order_id), tickers.get(p.symbol), settings, now)
                continue
            t = tickers.get(p.symbol)
            if not t:
                continue
            price = t["price"]
            hit, reason = risk.check_exit(p.side, p.sl, p.tp, price)
            if hit is not None:
                if reason == "SL" and p.breakeven:
                    reason = "TRAILING"
                await self.close_position(p.id, hit, reason)
                continue
            if p.expires_at and now >= datetime.fromisoformat(p.expires_at):
                await self.close_position(p.id, price, "TIEMPO")
                continue
            updates = {"mark_price": price, "unrealized_pnl": round(risk.pnl(p.symbol, p.side, p.entry_price, price, p.qty, tickers), 4)}
            if settings.trailing_enabled:
                new_sl, be = risk.update_trailing(p.side, p.entry_price, p.sl, p.initial_sl, p.atr, price, SPECS[p.symbol]["spread"])
                if new_sl != p.sl:
                    updates.update(sl=new_sl, breakeven=be)
                    if be and not p.breakeven:
                        await self.log("RISK", f"{p.symbol}: stop movido a breakeven ({fmt_price(p.symbol, new_sl)})")
            await self.db.positions.update_one({"_id": ObjectId(p.id)}, {"$set": updates})
        if ex:
            for pid, xp in ex.items():
                if pid not in local_ids and pid not in self._external_warned:
                    self._external_warned.add(pid)
                    await self.log("RISK", f"{self.broker.our_symbol(xp['symbol'])}: posición externa detectada en HFM (no gestionada por el bot) · {xp['volume']:.2f} lotes")
        await self._update_account_metrics(settings)

    async def _sync_live_position(self, p: Position, ex: dict, ticker: dict, settings: FxSettings, now: datetime):
        if not ex:
            if (now - datetime.fromisoformat(p.opened_at)).total_seconds() < LIVE_GRACE_SEC:
                return
            try:
                fresh = await self.broker.position(p.order_id, max_age=0)
            except Exception as e:
                logger.warning(f"hfm recheck {p.symbol}: {e}")
                return
            if fresh:
                ex = fresh
            else:
                await self._close_live_from_broker(p)
                return
        price = ex["mark"] or (ticker or {}).get("price") or p.mark_price
        updates = {"mark_price": price, "unrealized_pnl": round(ex["profit"] + ex["swap"] + ex["commission"], 4)}
        if abs(ex["volume"] - p.qty) > 1e-9:
            updates["qty"] = ex["volume"]
        if p.expires_at and now >= datetime.fromisoformat(p.expires_at):
            await self.db.positions.update_one({"_id": ObjectId(p.id)}, {"$set": updates})
            await self.close_position(p.id, price, "TIEMPO")
            return
        if settings.trailing_enabled:
            new_sl, be = risk.update_trailing(p.side, p.entry_price, p.sl, p.initial_sl, p.atr, price, SPECS[p.symbol]["spread"])
            new_sl = round(new_sl, SPECS[p.symbol]["digits"])
            if new_sl != p.sl and abs(new_sl - p.sl) >= SPECS[p.symbol]["pip"]:
                try:
                    await self.broker.set_stop(p.symbol, p.order_id, new_sl, p.tp)
                    updates.update(sl=new_sl, breakeven=be)
                    await self.log("RISK", f"{p.symbol}: stop REAL movido a {fmt_price(p.symbol, new_sl)}{' (breakeven)' if be and not p.breakeven else ''}")
                except Exception as e:
                    await self.log("ERROR", f"{p.symbol}: no se pudo mover el stop en HFM · {str(e)[:120]}")
        await self.db.positions.update_one({"_id": ObjectId(p.id)}, {"$set": updates})

    async def _close_live_from_broker(self, p: Position):
        async with self.lock:
            if not await self.db.positions.find_one({"_id": ObjectId(p.id)}):
                return
            cr = None
            try:
                cr = await self.broker.closed_result(p.order_id)
            except Exception as e:
                logger.warning(f"hfm deals {p.symbol}: {e}")
            price = (cr or {}).get("exit") or p.mark_price
            fees = (cr or {}).get("fees") or p.fees
            net = cr["pnl"] if cr else risk.pnl(p.symbol, p.side, p.entry_price, price, p.qty, self.market.tickers) - p.fees
            reason = (cr or {}).get("reason") or ("TP" if abs(price - p.tp) <= abs(price - p.sl) else ("TRAILING" if p.breakeven else "SL"))
            if reason == "SL" and p.breakeven:
                reason = "TRAILING"
            await self.db.positions.delete_one({"_id": ObjectId(p.id)})
            trade = await self._record_trade(p, price, net, fees, reason)
        await self._announce_close(p, trade, reason, cr is None)

    async def _announce_close(self, p: Position, trade: Trade, reason: str, estimated: bool = False):
        tag = "REAL " if p.live else ""
        est = " · PnL estimado, pendiente de confirmar con HFM" if estimated else ""
        await self.log("ORDER", f"CERRADA {tag}{p.side.upper()} {p.symbol} @ {fmt_price(p.symbol, trade.exit_price)} · {reason} · PnL {trade.pnl:+.2f} USD{est}")
        await self.tg(f"{'✅' if trade.pnl >= 0 else '❌'} <b>CERRADA {tag}{p.side.upper()} {p.symbol}</b> @ {fmt_price(p.symbol, trade.exit_price)} · {reason}\n"
                      f"PnL <b>{trade.pnl:+.2f} USD</b> ({trade.pnl_pct:+.2f}%) · entrada {fmt_price(p.symbol, p.entry_price)}{est}", "orders")

    async def _record_trade(self, p: Position, price: float, net: float, fees: float, reason: str) -> Trade:
        trade = Trade(symbol=p.symbol, side=p.side, strategy=p.strategy, entry_price=p.entry_price, exit_price=price, qty=p.qty,
                      leverage=p.leverage, margin=p.margin, pnl=round(net, 4), pnl_pct=round(net / p.margin * 100, 2) if p.margin else 0,
                      fees=round(fees, 4), reason=reason, opened_at=p.opened_at, live=p.live)
        res = await self.db.trades.insert_one(trade.to_mongo())
        trade.id = str(res.inserted_id)
        return trade

    async def _update_account_metrics(self, settings: FxSettings):
        s = await self.account_summary()
        acc = await self.db.account.find_one({"_id": "main"})
        upd = {}
        if acc["day"] != today():
            upd.update(day=today(), day_start_equity=s["equity"], daily_paused=False)
            await self.log("INFO", f"Nuevo día de trading · equidad inicial ${s['equity']:,.2f}")
            c = await self.checkin(settings, s)
            await self.log("PLAN", c["message"] + (" · ".join([""] + c["warnings"]) if c["warnings"] else ""))
            await self.tg(f"📊 <b>Resumen diario</b>\nEquidad ${s['equity']:,.2f} ({s['total_return_pct']:+.2f}% total)\n"
                          f"PnL de ayer {s['daily_pnl']:+.2f} USD ({s['daily_pnl_pct']:+.2f}%)\n"
                          f"{s['total_trades']} ops · acierto {s['win_rate']}% · PF {s['profit_factor'] or '—'} · DD máx {s['max_drawdown']}%\n"
                          f"{s['open_positions']} posiciones abiertas\n\n📋 {c['message']}", "daily")
            if c["ready_to_advance"] or c["warnings"]:
                await self.tg(f"📋 <b>Plan</b>: {c['message']}" + ("\n⚠️ " + "\n⚠️ ".join(c["warnings"]) if c["warnings"] else ""), "plan")
        elif not acc["daily_paused"] and s["daily_pnl_pct"] <= -settings.daily_loss_limit:
            upd["daily_paused"] = True
            await self.log("RISK", f"Límite de pérdida diaria ({settings.daily_loss_limit}%) alcanzado · nuevas entradas pausadas hasta mañana (UTC)")
            await self.tg(f"🛑 <b>Límite de pérdida diaria alcanzado</b> ({s['daily_pnl_pct']:+.2f}%). Nuevas entradas pausadas hasta mañana (UTC).", "orders")
        peak = max(acc["peak_equity"], s["equity"])
        dd = (peak - s["equity"]) / peak * 100 if peak else 0
        upd.update(peak_equity=peak, max_drawdown=max(acc["max_drawdown"], dd))
        await self.db.account.update_one({"_id": "main"}, {"$set": upd})
        if time.time() - self._last_snapshot >= 60:
            self._last_snapshot = time.time()
            await self.db.equity.insert_one({"ts": now_iso(), "equity": s["equity"], "balance": s["balance"]})

    # ---------- execution ----------
    async def open_position(self, symbol: str, sig: dict, settings: FxSettings, signal_id: str, risk_factor: float = 1.0,
                            risk_reason: str = "noticias", expires_at: str = None):
        """Returns (Position | None, reason) — reason explains why nothing was opened."""
        risk_pct = settings.risk_per_trade * risk_factor
        tickers = self.market.tickers
        async with self.lock:
            open_syms = [p["symbol"] for p in await self.db.positions.find({}, {"symbol": 1}).to_list(100)]
            if symbol in open_syms or len(open_syms) >= settings.max_positions:
                await self.log("RISK", f"{symbol}: apertura cancelada · límite de posiciones o par ya abierto")
                return None, "límite de posiciones o par ya abierto"
            price = tickers.get(symbol, {}).get("price") or sig["price"]
            long = sig["side"] == "long"
            entry = price
            sl = entry - (sig["price"] - sig["sl"])
            tp = entry + (sig["tp"] - sig["price"])
            if self.live:
                if not self.broker:
                    await self.log("ERROR", f"{symbol}: modo REAL sin cuenta HFM vinculada · orden no enviada")
                    return None, "modo REAL sin cuenta HFM vinculada"
                try:
                    info = await self.broker.info(max_age=0)
                    if not info.get("trade_allowed", True):
                        await self.log("ERROR", f"{symbol}: la cuenta HFM no permite operar (trading deshabilitado o contraseña investor)")
                        return None, "la cuenta HFM no permite operar"
                    lot = await self.broker.lot(symbol)
                    leverage = info["leverage"] or settings.leverage
                    lots, margin, real_risk = risk.position_size(info["equity"], info["available"], risk_pct, entry, sl, leverage, symbol, tickers,
                                                                 settings.min_lot_max_risk, lot)
                    if lots <= 0 or margin < 1:
                        need = risk.min_lot_risk_pct(info["equity"], entry, sl, symbol, tickers, lot["min"])
                        reason = (f"tamaño por debajo del lote mínimo del bróker ({lot['min']:g}): con este stop arriesga el {need}% de la equidad real "
                                  f"(objetivo {risk_pct:g}%, tope {settings.min_lot_max_risk:g}%)")
                        await self.log("RISK", f"{symbol}: {reason}")
                        return None, reason
                    r = await self.broker.open(symbol, sig["side"], lots, sl, tp)
                except Exception as e:
                    await self.log("ERROR", f"{symbol}: orden REAL rechazada por HFM/MetaApi · {str(e)[:160]}")
                    await self.tg(f"⚠️ <b>Orden REAL rechazada · {symbol}</b>\n{str(e)[:300]}", "orders")
                    return None, f"orden REAL rechazada: {str(e)[:120]}"
                entry, lots, fee = (r["entry"] or entry), r["lots"], abs(r["commission"])
                sl, tp = r["sl"], r["tp"]
                margin = lots * SPECS[symbol]["contract"] * risk.base_usd(symbol, tickers, entry) / leverage
                pos = Position(symbol=symbol, side=sig["side"], strategy=sig["strategy"], entry_price=entry, qty=lots, leverage=leverage, margin=margin,
                               sl=sl, tp=tp, initial_sl=sl, atr=sig["atr"], fees=fee, mark_price=price, signal_id=signal_id, expires_at=expires_at,
                               live=True, order_id=r["position_id"], link_id=r["link_id"])
                res = await self.db.positions.insert_one(pos.to_mongo())
                pos.id = str(res.inserted_id)
                if not r["filled"]:
                    await self.log("RISK", f"{symbol}: orden enviada (posición {r['position_id']}) pero sin confirmación de llenado · se sincronizará con HFM")
            else:
                leverage = settings.leverage
                s = await self.account_summary()
                lots, margin, real_risk = risk.position_size(s["equity"], s["available"], risk_pct, entry, sl, settings.leverage, symbol, tickers,
                                                             settings.min_lot_max_risk)
                if lots <= 0 or margin < 1:
                    need = risk.min_lot_risk_pct(s["equity"], entry, sl, symbol, tickers)
                    reason = (f"tamaño por debajo del lote mínimo (0.01): con este stop el lote mínimo arriesga el {need}% de la equidad "
                              f"(objetivo {risk_pct:g}%, tope con lote mínimo {settings.min_lot_max_risk:g}%) · sube el capital, el tope o usa una temporalidad menor")
                    await self.log("RISK", f"{symbol}: {reason}")
                    return None, reason
                fee = risk.spread_cost(symbol, lots, tickers)
                pos = Position(symbol=symbol, side=sig["side"], strategy=sig["strategy"], entry_price=entry, qty=lots, leverage=settings.leverage,
                               margin=margin, sl=sl, tp=tp, initial_sl=sl, atr=sig["atr"], fees=fee, mark_price=price, signal_id=signal_id, expires_at=expires_at)
                res = await self.db.positions.insert_one(pos.to_mongo())
                pos.id = str(res.inserted_id)
                await self.db.account.update_one({"_id": "main"}, {"$inc": {"balance": -fee}})
        tag = "REAL " if self.live else ""
        reduced = f" · tamaño ajustado al {int(risk_factor * 100)}% por {risk_reason}" if risk_factor != 1 else ""
        if real_risk > risk_pct + 0.05:
            reduced += f" · lote mínimo: riesgo real {real_risk:g}% (objetivo {risk_pct:g}%)"
        f = lambda v: fmt_price(symbol, v)  # noqa: E731
        await self.log("ORDER", f"ABIERTA {tag}{sig['side'].upper()} {symbol} @ {f(entry)} · {lots:.2f} lotes · 1:{leverage} · SL {f(sl)} ({pips(symbol, abs(entry - sl)):.1f} pips) · TP {f(tp)}{reduced}")
        await self.tg(f"{'🟢' if long else '🔴'} <b>ABIERTA {tag}{sig['side'].upper()} {symbol}</b> @ {f(entry)}\n"
                      f"{lots:.2f} lotes · 1:{leverage} · margen ${margin:,.2f}\nSL {f(sl)} · TP {f(tp)}\n"
                      f"Estrategia: {FX_STRATEGY_INFO.get(sig['strategy'], {}).get('name', sig['strategy'])}{reduced}", "orders")
        return pos, None

    async def close_position(self, pos_id: str, price: float = None, reason: str = "MANUAL"):
        tickers = self.market.tickers
        async with self.lock:
            doc = await self.db.positions.find_one({"_id": ObjectId(pos_id)})
            if not doc:
                return None
            p = Position.from_mongo(doc)
            if p.live:
                if not self.broker:
                    await self.log("ERROR", f"{p.symbol}: cierre REAL imposible · sin cuenta HFM vinculada")
                    return None
                try:
                    await self.broker.close(p.order_id)
                except Exception as e:
                    if getattr(e, "code", "") != "TRADE_RETCODE_POSITION_CLOSED":
                        await self.log("ERROR", f"{p.symbol}: cierre REAL fallido · {str(e)[:160]}")
                        return None
                cr = None
                try:
                    cr = await self.broker.closed_result(p.order_id)
                except Exception as e:
                    logger.warning(f"hfm deals {p.symbol}: {e}")
                price = (cr or {}).get("exit") or tickers.get(p.symbol, {}).get("price") or p.mark_price
                fees = (cr or {}).get("fees") or p.fees
                net = cr["pnl"] if cr else risk.pnl(p.symbol, p.side, p.entry_price, price, p.qty, tickers) - p.fees
                await self.db.positions.delete_one({"_id": ObjectId(pos_id)})
                trade = await self._record_trade(p, price, net, fees, reason)
                estimated = cr is None
            else:
                await self.db.positions.delete_one({"_id": ObjectId(pos_id)})
                price = price or tickers.get(p.symbol, {}).get("price") or p.mark_price
                exit_fee = risk.spread_cost(p.symbol, p.qty, tickers)
                gross = risk.pnl(p.symbol, p.side, p.entry_price, price, p.qty, tickers)
                net = gross - p.fees - exit_fee
                await self.db.account.update_one({"_id": "main"}, {"$inc": {"balance": gross - exit_fee}})
                trade = await self._record_trade(p, price, net, p.fees + exit_fee, reason)
                estimated = False
        await self._announce_close(p, trade, reason, estimated)
        return trade

    # ---------- scanning ----------
    async def _scan_loop(self):
        await asyncio.sleep(3)
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

    @staticmethod
    def _df(klines: list, atr_period: int = 14):
        return build_fx_df(klines, atr_period)

    async def scan_once(self, settings: FxSettings):
        if not market_open():
            if not self._closed_logged:
                self._closed_logged = True
                nxt = market_status()["next_change"]
                await self.log("SCAN", f"Mercado forex cerrado · sin escaneos hasta {nxt[:16].replace('T', ' ')} UTC")
            return
        self._closed_logged = False
        self.scanning = True
        found = 0
        htf_tf = HTF[settings.timeframe]
        try:
            for symbol in settings.symbols:
                try:
                    params = settings.symbol_params.get(symbol) or {}
                    df = self._df(await self.market.fetch_klines(symbol, settings.timeframe, 300, cache_sec=60), int(params.get("atr_period", 14)))
                    i = len(df) - 2
                    row = df.iloc[i]
                    htf = None
                    if settings.htf_filter:
                        htf = htf_trend(self._df(await self.market.fetch_klines(symbol, htf_tf, 200, cache_sec=300)))
                    sig = evaluate(df, i, settings.strategy, htf, params, settings.signal_mode, settings.disabled_strategies)
                    self.analysis[symbol] = {
                        "trend": trend_label(row), "rsi": round(float(row["rsi"]), 1), "macd_hist": float(row["macd_hist"]),
                        "adx": round(float(row["adx"]), 1), "atr_pips": round(pips(symbol, float(row["atr"])), 1), "htf": htf,
                        "signal": sig["side"] if sig else None, "signal_strategy": sig["strategy"] if sig else None, "updated_at": now_iso(),
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

    async def _blocks(self, symbol: str, settings: FxSettings, acc: dict):
        open_syms = [p["symbol"] for p in await self.db.positions.find({}, {"symbol": 1}).to_list(100)]
        if not market_open():
            return "mercado cerrado", "MERCADO", open_syms
        if not in_sessions(settings.sessions_allowed):
            return f"fuera de las sesiones permitidas ({session_names(settings.sessions_allowed)})", "SESION", open_syms
        if symbol in open_syms:
            return "ya existe una posición abierta en el par", "BLOQUEADA", open_syms
        if len(open_syms) >= settings.max_positions:
            return f"máximo de posiciones alcanzado ({settings.max_positions})", "BLOQUEADA", open_syms
        if acc["daily_paused"]:
            return "límite de pérdida diaria alcanzado", "BLOQUEADA", open_syms
        return None, None, open_syms

    async def _handle_signal(self, symbol, sig, settings: FxSettings, df, htf, htf_tf):
        key = f"{symbol}:{sig['strategy']}:{sig['side']}:{sig['key_ts']}"
        if key in self.signal_keys:
            return
        self.signal_keys.add(key)
        await self.log("SIGNAL", f"{symbol} {sig['side'].upper()} · {FX_STRATEGY_INFO[sig['strategy']]['name']} · {sig['score']} confirmaciones")
        acc = await self.account_summary()
        block, kind, open_syms = await self._blocks(symbol, settings, acc)
        news_block, risk_factor = self.news.gate(symbol) if self.news else (None, 1.0)
        if not block and news_block:
            block, kind = news_block, "NOTICIAS"
        base = dict(symbol=symbol, side=sig["side"], strategy=sig["strategy"], timeframe=settings.timeframe, price=sig["price"], sl=sig["sl"], tp=sig["tp"],
                    score=sig["score"], reasons=sig["reasons"], indicators=sig["indicators"], key=key)
        if block:
            await self.log("RISK", f"{symbol}: señal descartada · {block}")
            await self.db.signals.insert_one(Signal(**base, ai_decision=kind, note=f"Bloqueada por {BLOCK_BY.get(kind, 'riesgo')}: {block}").to_mongo())
            return
        signal = Signal(**base, ai_decision="SIN_IA")
        approve = True
        if settings.ai_enabled:
            await self.log("AI_EVAL", f"{ai_label()} evaluando {symbol} {sig['side'].upper()}...")
            closes = df["close"].iloc[-22:-1]
            t = self.market.tickers.get(symbol, {})
            ctx = {
                "htf_tf": htf_tf, "htf_trend": {1: "ALCISTA", -1: "BAJISTA", 0: "NEUTRAL"}.get(htf, "N/D"),
                "change_24h": t.get("change_pct", 0), "sessions": market_status()["sessions"],
                "recent_changes": [round(x, 3) for x in (closes.pct_change().dropna() * 100).tolist()],
                "open_positions": len(open_syms), "daily_pnl_pct": acc["daily_pnl_pct"],
                "news": self.news.context(symbol) if self.news else None,
            }
            try:
                res = await evaluate_signal(symbol, settings.timeframe, sig, ctx)
                signal.ai_decision, signal.ai_confidence, signal.ai_risk, signal.ai_reasoning = res["decision"], res["confidence"], res["risk"], res["reasoning"]
                approve = res["decision"] == "APROBADA" and res["confidence"] >= settings.ai_min_confidence
                if res["decision"] == "APROBADA" and not approve:
                    signal.note = f"Confianza {res['confidence']}% menor al mínimo ({settings.ai_min_confidence}%)"
            except Exception as e:
                logger.exception("ai error")
                signal.ai_decision, signal.note, approve = "ERROR", f"Error IA: {str(e)[:180]}", False
            await self.log("AI_EVAL", f"{symbol}: {signal.ai_decision} · confianza {signal.ai_confidence}% · riesgo {signal.ai_risk}")
            await self.tg(f"🤖 <b>{ai_label()} · {symbol} {sig['side'].upper()}</b>: {signal.ai_decision} ({signal.ai_confidence}% · riesgo {signal.ai_risk})\n"
                          f"{signal.ai_reasoning[:300] or signal.note}", "ai")
        res = await self.db.signals.insert_one(signal.to_mongo())
        if approve:
            risk_reason = "riesgo de noticias" if risk_factor < 1 else ""
            pos, reason = await self.open_position(symbol, sig, settings, str(res.inserted_id), risk_factor, risk_reason)
            await self.db.signals.update_one({"_id": res.inserted_id}, {"$set": {"executed": True} if pos else {"note": f"No ejecutada: {reason}"}})

    # ---------- news trading ----------
    async def news_trade(self, symbol: str, side: str, confidence: int, reasoning: str, event: dict, cfg) -> dict:
        settings = await self.get_settings()
        if not self.running:
            return {"status": "OMITIDA", "reason": "bot detenido"}
        if symbol not in settings.symbols:
            return {"status": "OMITIDA", "reason": "par no activo en ajustes"}
        acc = await self.account_summary()
        block, _, _ = await self._blocks(symbol, settings, acc)
        if block:
            return {"status": "OMITIDA", "reason": block}
        tickers = await self.market.fetch_tickers(settings.symbols, cache_sec=5)
        price = tickers.get(symbol, {}).get("price")
        if not price:
            return {"status": "OMITIDA", "reason": "sin precio"}
        df = self._df(await self.market.fetch_klines(symbol, "15m", 200, cache_sec=20))
        row = df.iloc[-2]
        atr = float(row["atr"])
        t_event = datetime.fromisoformat(event["time"])
        ref = None
        for k in await self.market.fetch_klines(symbol, "5m", 300, cache_sec=20):
            if k[0] <= int(t_event.timestamp() * 1000):
                ref = k[1]
        move = (price - ref) if ref else 0.0
        confirmed = (move > 0) if side == "long" else (move < 0)
        move_txt = f"{pips(symbol, move):+.1f} pips desde la publicación"
        if cfg.news_trade_confirm_price and not confirmed:
            return {"status": "OMITIDA", "reason": f"el precio no confirma ({move_txt})"}
        long = side == "long"
        sl = price - cfg.news_trade_sl_atr * atr if long else price + cfg.news_trade_sl_atr * atr
        tp = price + cfg.news_trade_tp_atr * atr if long else price - cfg.news_trade_tp_atr * atr
        key = f"{symbol}:news_event:{side}:{event['key']}"
        if key in self.signal_keys:
            return {"status": "OMITIDA", "reason": "evento ya operado en este par"}
        self.signal_keys.add(key)
        label = f"{event['country']} {event['title']}"
        sig = {"side": side, "strategy": "news_event", "price": price, "sl": sl, "tp": tp, "atr": atr, "score": max(1, confidence // 10),
               "reasons": [f"Noticia: {label} · dato {event.get('actual') or 'n/d'} vs previsión {event.get('forecast') or 'n/d'} · sorpresa {event.get('surprise', '')}",
                           f"Precio confirma: {move_txt}", f"SL {cfg.news_trade_sl_atr}×ATR15m · TP {cfg.news_trade_tp_atr}×ATR15m · cierre máx. {cfg.news_trade_max_hours}h"],
               "key_ts": int(t_event.timestamp() * 1000), "indicators": snapshot(row)}
        signal = Signal(symbol=symbol, side=side, strategy="news_event", timeframe="15m", price=price, sl=sl, tp=tp, score=sig["score"], reasons=sig["reasons"],
                        indicators=sig["indicators"], ai_decision="APROBADA", ai_confidence=confidence, ai_risk="MEDIO", ai_reasoning=reasoning,
                        note=f"Operación de noticias · {label}", key=key)
        res = await self.db.signals.insert_one(signal.to_mongo())
        expires = (datetime.now(timezone.utc) + timedelta(hours=cfg.news_trade_max_hours)).isoformat()
        pos, reason = await self.open_position(symbol, sig, settings, str(res.inserted_id), cfg.news_trade_risk_factor, "operación de noticias", expires_at=expires)
        if not pos:
            await self.db.signals.update_one({"_id": res.inserted_id}, {"$set": {"note": f"No ejecutada: {reason}"}})
            return {"status": "OMITIDA", "reason": reason}
        await self.db.signals.update_one({"_id": res.inserted_id}, {"$set": {"executed": True}})
        return {"status": "EJECUTADA", "reason": move_txt, "position_id": pos.id, "entry": price, "sl": sl, "tp": tp, "lots": pos.qty}
