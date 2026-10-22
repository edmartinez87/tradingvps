"""HFM live broker for the FX engine (REAL mode): MetaApi account info/positions cache, symbol mapping (suffix), lot quantization,
market orders with SL/TP, close, stop updates and realized result from history deals."""
import re
import time
import uuid
import asyncio
import logging
from fx.metaapi import MetaApi, MetaApiError
from fx.symbols import SPECS

logger = logging.getLogger("fx.live")
_REASON_RE = re.compile(r"\[(sl|tp)\b", re.I)
_LINK_RE = re.compile(r"^AIT_([0-9a-f]{8})_")
BALANCE_DEAL_TYPES = {"DEAL_TYPE_BALANCE", "DEAL_TYPE_CREDIT", "DEAL_TYPE_BONUS", "DEAL_TYPE_CORRECTION"}
BALANCE_DEAL_LABELS = {"DEAL_TYPE_BALANCE": "depósito/retiro", "DEAL_TYPE_CREDIT": "crédito del bróker", "DEAL_TYPE_BONUS": "bono", "DEAL_TYPE_CORRECTION": "corrección"}
RETRY_DELAYS = (4.0, 10.0)  # transient broker/terminal failures: 3 attempts in ~15 s


def new_link() -> str:
    """clientId in MetaApi's required `${strategyId}_${positionId}_${orderId}` format (≤ 31 chars, stored in the MT comment)."""
    return f"AIT_{uuid.uuid4().hex[:8]}_o"


def close_link(link_id: str) -> str:
    m = _LINK_RE.match(link_id or "")
    return f"AIT_{m.group(1) if m else uuid.uuid4().hex[:8]}_c"


def q_step(v: float, step: float) -> float:
    if not step or step <= 0:
        return v
    n = round(v / step)
    return round(n * step, 8)


def q_floor(v: float, step: float) -> float:
    if not step or step <= 0:
        return v
    import math
    return round(math.floor(v / step + 1e-9) * step, 8)


class FxLiveBroker:
    def __init__(self, token: str, account_id: str, region: str, base_url: str = "", suffix: str = ""):
        self.api = MetaApi(token, region, base_url)
        self.account_id, self.region, self.suffix = account_id, region, suffix or ""
        self._info = {"ts": 0.0, "data": None}
        self._positions = {"ts": 0.0, "data": []}
        self.last_error = None

    async def aclose(self):
        await self.api.aclose()

    def broker_symbol(self, symbol: str) -> str:
        return f"{symbol}{self.suffix}"

    def our_symbol(self, broker_symbol: str) -> str:
        return broker_symbol[:-len(self.suffix)] if self.suffix and broker_symbol.endswith(self.suffix) else broker_symbol

    def invalidate(self):
        self._info["ts"] = self._positions["ts"] = 0.0

    async def info(self, max_age: float = 10.0) -> dict:
        if self._info["data"] is None or time.time() - self._info["ts"] > max_age:
            raw = await self.api.account_info(self.account_id, self.region, refresh=max_age == 0)
            self._info = {"ts": time.time(), "data": {
                "balance": float(raw.get("balance") or 0), "equity": float(raw.get("equity") or 0), "margin": float(raw.get("margin") or 0),
                "available": float(raw.get("freeMargin") or 0), "leverage": int(raw.get("leverage") or 0), "currency": raw.get("currency") or "",
                "trade_allowed": raw.get("tradeAllowed", True), "broker": raw.get("broker") or "", "server": raw.get("server") or "",
                "unrealised": float(raw.get("equity") or 0) - float(raw.get("balance") or 0)}}
        return self._info["data"]

    @staticmethod
    def _pos(p: dict) -> dict:
        return {"id": str(p.get("id")), "symbol": p.get("symbol"), "side": "long" if str(p.get("type", "")).endswith("BUY") else "short",
                "volume": float(p.get("volume") or 0), "entry": float(p.get("openPrice") or 0), "mark": float(p.get("currentPrice") or 0),
                "sl": p.get("stopLoss"), "tp": p.get("takeProfit"), "profit": float(p.get("profit") or 0), "swap": float(p.get("swap") or 0),
                "commission": float(p.get("commission") or 0), "client_id": p.get("clientId"), "magic": p.get("magic"), "time": p.get("time")}

    async def positions(self, max_age: float = 4.0) -> list:
        if time.time() - self._positions["ts"] > max_age:
            raw = await self.api.positions(self.account_id, self.region, refresh=max_age == 0)
            self._positions = {"ts": time.time(), "data": [self._pos(p) for p in raw]}
        return self._positions["data"]

    async def position(self, position_id: str, max_age: float = 0.0) -> dict | None:
        return next((p for p in await self.positions(max_age) if p["id"] == str(position_id)), None)

    async def lot(self, symbol: str) -> dict:
        s = await self.api.spec(self.account_id, self.broker_symbol(symbol), self.region)
        return {"min": float(s.get("minVolume") or 0.01), "step": float(s.get("volumeStep") or 0.01), "max": float(s.get("maxVolume") or 100),
                "digits": int(s.get("digits") if s.get("digits") is not None else SPECS[symbol]["digits"]), "tick": float(s.get("tickSize") or 0),
                "contract": float(s.get("contractSize") or SPECS[symbol]["contract"]), "symbol": self.broker_symbol(symbol)}

    async def check_symbol(self, symbol: str) -> dict:
        try:
            lot = await self.lot(symbol)
            tick = await self.api.tick(self.account_id, self.broker_symbol(symbol), self.region)
            return {"ok": True, "broker_symbol": lot["symbol"], "min_lot": lot["min"], "lot_step": lot["step"], "digits": lot["digits"],
                    "contract": lot["contract"], "bid": tick.get("bid"), "ask": tick.get("ask"), "error": None}
        except MetaApiError as e:
            return {"ok": False, "broker_symbol": self.broker_symbol(symbol), "error": e.msg}

    async def _wait_position(self, position_id: str, tries: int = 6) -> dict | None:
        for i in range(tries):
            p = await self.position(position_id, max_age=0 if i == 0 else 0.5)
            if p and p["entry"]:
                return p
            await asyncio.sleep(0.8)
        return None

    async def _reconcile_open(self, link: str) -> dict | None:
        """Trade result unknown (timeout / connection dropped mid-trade): MetaApi may still have executed it. Looks for a position (then a filled
        order) carrying our clientId before deciding whether a retry is safe."""
        self.invalidate()
        pos = await self.api.find_position_by_client_id(self.account_id, link, self.region)
        if pos:
            return {"id": str(pos.get("id"))}
        try:
            order = await self.api.order_filled_by_client_id(self.account_id, link, self.region)
        except MetaApiError as e:
            logger.warning(f"hfm reconcile orders {link}: {e.msg}")
            order = None
        return {"id": str(order.get("positionId") or "")} if order and order.get("positionId") else None

    async def _with_retries(self, send, on_unknown):
        """Runs a trade request: 'unknown' results are verified with `on_unknown` (returns a result when it did execute), 'transient' failures are
        retried with backoff, definitive rejections propagate at once. The raised error carries `.attempts`."""
        attempts = 0
        while True:
            try:
                return await send(), attempts + 1, None
            except MetaApiError as e:
                if e.kind == "unknown":
                    done = await on_unknown()
                    if done is not None:
                        return done, attempts + 1, f"confirmada en HFM tras «{e.msg[:90]}»"
                    e.kind, e.msg = "transient", f"{e.msg} · verificado en HFM: no se ejecutó"
                if e.kind != "transient" or attempts >= len(RETRY_DELAYS):
                    e.attempts = attempts + 1
                    raise
                self.last_error = e.msg
                logger.warning(f"hfm transient ({attempts + 1}/{len(RETRY_DELAYS) + 1}): {e.msg}")
                await asyncio.sleep(e.retry_after or RETRY_DELAYS[attempts])
                attempts += 1

    async def open(self, symbol: str, side: str, lots: float, sl: float, tp: float) -> dict:
        lot = await self.lot(symbol)
        vol = q_floor(lots, lot["step"])
        if vol < lot["min"]:
            raise ValueError(f"{vol} lotes por debajo del lote mínimo del bróker ({lot['min']})")
        vol = min(vol, lot["max"])
        d = lot["digits"]
        links = []

        async def send():
            links.append(new_link())
            return await self.api.market_order(self.account_id, lot["symbol"], side, vol, round(sl, d), round(tp, d), links[-1], self.region)

        async def on_unknown():
            found = await self._reconcile_open(links[-1])
            return {"positionId": found["id"], "orderId": "", "reconciled": True} if found else None

        res, attempts, note = await self._with_retries(send, on_unknown)
        link = links[-1]
        self.invalidate()
        pos = await self._wait_position(res.get("positionId")) if res.get("positionId") else None
        return {"position_id": str(res.get("positionId") or ""), "order_id": str(res.get("orderId") or ""), "link_id": link, "lots": pos["volume"] if pos else vol,
                "entry": pos["entry"] if pos else 0.0, "commission": pos["commission"] if pos else 0.0, "filled": bool(pos),
                "sl": float(pos["sl"]) if pos and pos.get("sl") else round(sl, d), "tp": float(pos["tp"]) if pos and pos.get("tp") else round(tp, d),
                "attempts": attempts, "note": note}

    async def close(self, position_id: str, link_id: str = "") -> dict:
        async def send():
            return await self.api.close_position(self.account_id, position_id, self.region, close_link(link_id))

        async def on_unknown():
            self.invalidate()
            return {"orderId": "", "reconciled": True} if await self.position(position_id, max_age=0) is None else None

        res, attempts, note = await self._with_retries(send, on_unknown)
        self.invalidate()
        return {"order_id": str(res.get("orderId") or ""), "attempts": attempts, "note": note}

    async def set_stop(self, symbol: str, position_id: str, sl: float, tp: float):
        lot = await self.lot(symbol)
        d = lot["digits"]
        want_sl, want_tp = round(sl, d), round(tp, d)

        async def send():
            return await self.api.modify_position(self.account_id, position_id, want_sl, want_tp, self.region)

        async def on_unknown():
            self.invalidate()
            p = await self.position(position_id, max_age=0)
            ok = p is None or (p.get("sl") is not None and abs(float(p["sl"]) - want_sl) < 10 ** -d)
            return {"positionId": position_id, "reconciled": True} if ok else None

        await self._with_retries(send, on_unknown)
        self.invalidate()

    async def closed_result(self, position_id: str, tries: int = 4) -> dict | None:
        """Realized result of a closed position from its exit deals: net = profit + swap + commission (both legs)."""
        for i in range(tries):
            deals = await self.api.deals_by_position(self.account_id, position_id, self.region)
            outs = [d for d in deals if str(d.get("entryType", "")).endswith("OUT")]
            if outs:
                commission = sum(float(d.get("commission") or 0) for d in deals)
                swap = sum(float(d.get("swap") or 0) for d in deals)
                profit = sum(float(d.get("profit") or 0) for d in outs)
                last = max(outs, key=lambda d: d.get("time") or "")
                comment = " ".join(str(d.get("comment") or d.get("brokerComment") or "") for d in outs)
                m = _REASON_RE.search(comment)
                return {"exit": float(last.get("price") or 0), "pnl": round(profit + swap + commission, 4), "fees": round(-(commission + swap), 4),
                        "reason": m.group(1).upper() if m else None, "time": last.get("time")}
            if i < tries - 1:
                await asyncio.sleep(1.0)
        return None

    async def cash_flows(self, since_ms: int) -> list:
        """Balance operations of the account (deposits, withdrawals, credits, corrections) since `since_ms`, oldest first."""
        from datetime import datetime, timezone
        start = datetime.fromtimestamp(since_ms / 1000, timezone.utc).isoformat().replace("+00:00", "Z")
        end = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        deals = await self.api.deals_by_time(self.account_id, start, end, self.region)
        out = []
        for d in deals:
            if d.get("type") not in BALANCE_DEAL_TYPES:
                continue
            amount = float(d.get("profit") or 0)
            if not amount:
                continue
            out.append({"id": f"hfm:{d.get('id')}", "amount": amount, "ts": str(d.get("time") or end).replace("Z", "+00:00"),
                        "note": (d.get("comment") or d.get("brokerComment") or BALANCE_DEAL_LABELS.get(d.get("type"), "operación de balance"))[:80]})
        return sorted(out, key=lambda x: x["ts"])
