"""Local Bybit V5 mock for end-to-end testing of the live executor (signature-verified).
Run: python3 scripts/bybit_mock.py  (port 8011)  · credentials: mockkey / mocksecret
"""
import hmac
import time
import json
import hashlib
import uuid
import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

API_KEY, API_SECRET = "mockkey", "mocksecret"
EQUITY = 1000.0
state = {"wallet": EQUITY, "positions": {}, "orders": {}, "closed": [], "leverage": {}, "prices": {}}
app = FastAPI()
INSTRUMENTS = {"BTCUSDT": ("0.001", "0.001", "0.1"), "ETHUSDT": ("0.01", "0.01", "0.01"), "SOLUSDT": ("0.1", "0.1", "0.01"),
               "XRPUSDT": ("1", "1", "0.0001"), "AVAXUSDT": ("0.1", "0.1", "0.001"), "LINKUSDT": ("0.1", "0.1", "0.001")}


def ok(result):
    return {"retCode": 0, "retMsg": "OK", "result": result, "time": int(time.time() * 1000)}


def err(code, msg, status=200):
    return JSONResponse({"retCode": code, "retMsg": msg, "result": {}}, status_code=status)


async def price_of(symbol: str) -> float:
    if symbol in state["prices"]:
        return state["prices"][symbol]
    try:
        async with httpx.AsyncClient(timeout=6) as c:
            r = await c.get("https://api.bitget.com/api/v2/mix/market/ticker", params={"productType": "USDT-FUTURES", "symbol": symbol})
        return float(r.json()["data"][0]["lastPr"])
    except Exception:
        return 100.0


async def verify(request: Request, body: bytes) -> bool:
    h = request.headers
    if h.get("x-bapi-api-key") != API_KEY:
        return False
    payload = request.url.query if request.method == "GET" else body.decode()
    expected = hmac.new(API_SECRET.encode(), (h.get("x-bapi-timestamp", "") + API_KEY + h.get("x-bapi-recv-window", "") + payload).encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, h.get("x-bapi-sign", ""))


@app.middleware("http")
async def auth_mw(request: Request, call_next):
    if request.url.path.startswith("/v5/") and not request.url.path.startswith("/v5/market/"):
        body = await request.body()
        if not await verify(request, body):
            return err(10004, "error sign! origin_string[...]", 200)
    return await call_next(request)


@app.get("/v5/market/time")
async def market_time():
    return ok({"timeSecond": str(int(time.time())), "timeNano": str(time.time_ns())})


@app.get("/v5/market/instruments-info")
async def instruments(symbol: str = None, category: str = "linear"):
    items = []
    for s, (minq, step, tick) in INSTRUMENTS.items():
        if symbol and s != symbol:
            continue
        items.append({"symbol": s, "status": "Trading", "lotSizeFilter": {"minOrderQty": minq, "qtyStep": step, "maxMktOrderQty": "100000", "minNotionalValue": "5"},
                      "priceFilter": {"tickSize": tick}})
    return ok({"category": category, "list": items})


def unreal(p, price):
    return (price - p["entry"]) * p["size"] if p["side"] == "Buy" else (p["entry"] - price) * p["size"]


@app.get("/v5/account/wallet-balance")
async def wallet(accountType: str = "UNIFIED"):
    upl = 0.0
    for s, p in state["positions"].items():
        upl += unreal(p, await price_of(s))
    used = sum(p["entry"] * p["size"] / p["leverage"] for p in state["positions"].values())
    eq = state["wallet"] + upl
    return ok({"list": [{"accountType": accountType, "totalEquity": f"{eq:.4f}", "totalWalletBalance": f"{state['wallet']:.4f}",
                         "totalAvailableBalance": f"{state['wallet'] - used:.4f}", "totalPerpUPL": f"{upl:.4f}", "totalMarginBalance": f"{eq:.4f}",
                         "coin": [{"coin": "USDT", "walletBalance": f"{state['wallet']:.4f}", "equity": f"{eq:.4f}"}]}]})


@app.post("/v5/position/set-leverage")
async def set_leverage(request: Request):
    b = await request.json()
    if state["leverage"].get(b["symbol"]) == b["buyLeverage"]:
        return err(110043, "leverage not modified")
    state["leverage"][b["symbol"]] = b["buyLeverage"]
    return ok({})


@app.post("/v5/order/create")
async def create_order(request: Request):
    b = await request.json()
    sym, side, qty = b["symbol"], b["side"], float(b["qty"])
    price = await price_of(sym)
    oid = uuid.uuid4().hex[:16]
    fee = price * qty * 0.00055
    pos = state["positions"].get(sym)
    if b.get("reduceOnly"):
        if not pos or pos["side"] == side:
            return err(110017, "reduce-only order has same side with current position")
        await _close(sym, price, "manual", fee, oid)
    else:
        if pos:
            return err(110001, "position already exists (mock: one position per symbol)")
        state["wallet"] -= fee
        state["positions"][sym] = {"side": side, "size": qty, "entry": price, "leverage": float(state["leverage"].get(sym, 3)),
                                   "sl": float(b.get("stopLoss") or 0), "tp": float(b.get("takeProfit") or 0), "opened": int(time.time() * 1000), "fee": fee}
    state["orders"][oid] = {"orderId": oid, "orderLinkId": b.get("orderLinkId", ""), "symbol": sym, "side": side, "orderStatus": "Filled",
                            "avgPrice": f"{price:.6f}", "cumExecQty": b["qty"], "cumExecFee": f"{fee:.6f}"}
    return ok({"orderId": oid, "orderLinkId": b.get("orderLinkId", "")})


async def _close(sym, price, reason, fee, oid):
    p = state["positions"].pop(sym)
    gross = unreal(p, price)
    state["wallet"] += gross - fee
    state["closed"].append({"symbol": sym, "orderId": oid, "side": "Sell" if p["side"] == "Buy" else "Buy", "qty": str(p["size"]),
                            "avgEntryPrice": f"{p['entry']:.6f}", "avgExitPrice": f"{price:.6f}", "closedPnl": f"{gross - fee - p['fee']:.6f}",
                            "openFee": f"{p['fee']:.6f}", "closeFee": f"{fee:.6f}", "updatedTime": str(int(time.time() * 1000)), "reason": reason})


@app.get("/v5/order/realtime")
@app.get("/v5/order/history")
async def order_status(orderId: str = None, symbol: str = None, category: str = "linear"):
    o = state["orders"].get(orderId)
    return ok({"list": [o] if o else []})


@app.post("/v5/position/trading-stop")
async def trading_stop(request: Request):
    b = await request.json()
    p = state["positions"].get(b["symbol"])
    if not p:
        return err(10001, "can not set tp/sl/ts for zero position")
    p["sl"] = float(b.get("stopLoss") or p["sl"])
    return ok({})


@app.get("/v5/position/list")
async def positions(symbol: str = None, settleCoin: str = None, category: str = "linear"):
    out = []
    for s, p in state["positions"].items():
        if symbol and s != symbol:
            continue
        price = await price_of(s)
        out.append({"symbol": s, "side": p["side"], "size": str(p["size"]), "avgPrice": f"{p['entry']:.6f}", "markPrice": f"{price:.6f}",
                    "unrealisedPnl": f"{unreal(p, price):.6f}", "leverage": str(p["leverage"]), "stopLoss": str(p["sl"]), "takeProfit": str(p["tp"]), "positionIdx": 0})
    return ok({"list": out})


@app.get("/v5/position/closed-pnl")
async def closed_pnl(symbol: str = None, startTime: int = None, limit: int = 20, category: str = "linear"):
    rows = [r for r in state["closed"] if (not symbol or r["symbol"] == symbol) and (not startTime or int(r["updatedTime"]) >= startTime)]
    return ok({"list": rows[-limit:][::-1]})


# --- test helpers (not part of Bybit) ---
@app.post("/mock/price/{symbol}")
async def set_price(symbol: str, price: float):
    state["prices"][symbol] = price
    return {"ok": True}


@app.post("/mock/close/{symbol}")
async def force_close(symbol: str, price: float = None, reason: str = "sl"):
    if symbol not in state["positions"]:
        return {"ok": False}
    p = state["positions"][symbol]
    px = price or (p["sl"] if reason == "sl" else p["tp"]) or await price_of(symbol)
    await _close(symbol, px, reason, px * p["size"] * 0.00055, uuid.uuid4().hex[:16])
    return {"ok": True, "exit": px}


@app.get("/mock/state")
async def mock_state():
    return state


@app.post("/mock/reset")
async def mock_reset():
    state.update(wallet=EQUITY, positions={}, orders={}, closed=[], leverage={}, prices={})
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8011, log_level="warning")
