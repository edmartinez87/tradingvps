"""Local MetaApi.cloud mock (provisioning + client API) for end-to-end testing of the HotForex REAL executor.
Run: python3 scripts/metaapi_mock.py  (port 8012)  · token: mocktoken · accepts any MT login/server.
Helpers: POST /mock/price/{symbol}?price=X · POST /mock/close/{position_id}?reason=sl|tp · POST /mock/connection?connected=false · GET /mock/state · POST /mock/reset
"""
import sys
import time
import uuid
from datetime import datetime, timezone
import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

sys.path.insert(0, "/app/backend")
from fx.symbols import SPECS  # noqa: E402

TOKEN = "mocktoken"
BALANCE = 1000.0
COMMISSION_PER_LOT = -3.0
app = FastAPI()
state = {}


def reset():
    state.clear()
    state.update({"accounts": {}, "balance": BALANCE, "positions": {}, "deals": {}, "prices": {}, "seq": 1000, "trade_allowed": True, "connected": True,
                  "balance_deals": []})


reset()


def _not_connected():
    return JSONResponse({"id": 1, "error": "NotSynchronizedError", "message": "Account is not connected to the broker"}, status_code=404)


def now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def nid():
    state["seq"] += 1
    return str(state["seq"])


async def price_of(symbol: str) -> float:
    base = symbol.rstrip(".").replace(".r", "")
    if base in state["prices"]:
        return state["prices"][base]
    spec = SPECS.get(base)
    try:
        async with httpx.AsyncClient(timeout=6, headers={"User-Agent": "Mozilla/5.0"}) as c:
            r = await c.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{spec['yahoo']}", params={"interval": "1m", "range": "1d"})
        p = float(r.json()["chart"]["result"][0]["meta"]["regularMarketPrice"])
    except Exception:
        p = {"XAUUSD": 2650.0, "XAGUSD": 31.0, "USDJPY": 150.0, "EURJPY": 162.0, "GBPJPY": 195.0}.get(base, 1.1)
    state["prices"][base] = p
    return p


def _spec(symbol: str):
    base = symbol.replace(".r", "")
    return base, SPECS.get(base)


def _pnl(p: dict, price: float) -> float:
    base, spec = _spec(p["symbol"])
    move = (price - p["openPrice"]) if p["type"] == "POSITION_TYPE_BUY" else (p["openPrice"] - price)
    usd = move * spec["contract"] * p["volume"]
    return round(usd / price if spec["quote"] != "USD" else usd, 2)


def _retcode(code: str, num: int, msg: str, **extra):
    return {"numericCode": num, "stringCode": code, "message": msg, **extra}


@app.middleware("http")
async def auth(request: Request, call_next):
    if request.url.path.startswith("/mock"):
        return await call_next(request)
    if request.headers.get("auth-token") != TOKEN:
        return JSONResponse({"id": 1, "error": "UnauthorizedError", "message": "Authorization failed"}, status_code=401)
    return await call_next(request)


# ---------- provisioning ----------
@app.get("/users/current/accounts")
async def list_accounts():
    return list(state["accounts"].values())


@app.post("/users/current/accounts", status_code=201)
async def create_account(request: Request):
    body = await request.json()
    acc_id = uuid.uuid4().hex[:24]
    state["accounts"][acc_id] = {"_id": acc_id, "login": str(body.get("login")), "server": body.get("server"), "platform": body.get("platform", "mt5"),
                                 "state": "DEPLOYED", "connectionStatus": "CONNECTED", "region": body.get("region", "new-york"), "name": body.get("name"),
                                 "magic": body.get("magic", 0), "type": body.get("type", "cloud-g2"), "reliability": body.get("reliability", "high")}
    return {"id": acc_id, "state": "DEPLOYED"}


@app.get("/users/current/accounts/{acc_id}")
async def get_account(acc_id: str):
    acc = state["accounts"].get(acc_id)
    return acc if acc else JSONResponse({"message": "Account not found"}, status_code=404)


@app.post("/users/current/accounts/{acc_id}/undeploy", status_code=204)
async def undeploy(acc_id: str):
    acc = state["accounts"].get(acc_id)
    if acc:
        acc.update(state="UNDEPLOYED", connectionStatus="DISCONNECTED")
    return Response(status_code=204)


@app.delete("/users/current/accounts/{acc_id}", status_code=204)
async def delete_account(acc_id: str):
    if acc_id not in state["accounts"]:
        return JSONResponse({"message": "Account not found"}, status_code=404)
    del state["accounts"][acc_id]
    return Response(status_code=204)


@app.post("/users/current/accounts/{acc_id}/deploy", status_code=204)
@app.post("/users/current/accounts/{acc_id}/redeploy", status_code=204)
async def deploy(acc_id: str):
    acc = state["accounts"].get(acc_id)
    if acc:
        acc.update(state="DEPLOYED", connectionStatus="CONNECTED")
    return Response(status_code=204)


# ---------- client API ----------
def _equity():
    return round(state["balance"] + sum(p["profit"] + p["swap"] + p["commission"] for p in state["positions"].values()), 2)


@app.get("/users/current/accounts/{acc_id}/account-information")
async def account_information(acc_id: str):
    if acc_id not in state["accounts"]:
        return JSONResponse({"message": "Account not found"}, status_code=404)
    if not state["connected"]:
        return _not_connected()
    margin = round(sum(p["margin"] for p in state["positions"].values()), 2)
    eq = _equity()
    return {"platform": "mt5", "broker": "HF Markets (SV) Ltd", "currency": "USD", "server": state["accounts"][acc_id]["server"], "balance": round(state["balance"], 2),
            "equity": eq, "margin": margin, "freeMargin": round(eq - margin, 2), "leverage": 100, "marginLevel": None, "tradeAllowed": state["trade_allowed"],
            "investorMode": not state["trade_allowed"], "marginMode": "ACCOUNT_MARGIN_MODE_RETAIL_HEDGING", "name": "Mock HFM", "login": int(state["accounts"][acc_id]["login"])}


@app.get("/users/current/accounts/{acc_id}/positions")
async def positions(acc_id: str):
    if not state["connected"]:
        return _not_connected()
    out = []
    for p in state["positions"].values():
        price = await price_of(p["symbol"])
        p["currentPrice"], p["profit"] = price, _pnl(p, price)
        out.append({k: v for k, v in p.items() if k != "margin"})
    return out


@app.get("/users/current/accounts/{acc_id}/symbols/{symbol}/specification")
async def specification(acc_id: str, symbol: str):
    base, spec = _spec(symbol)
    if not spec:
        return JSONResponse({"message": f"Symbol {symbol} not found"}, status_code=404)
    return {"symbol": symbol, "tickSize": spec["pip"] / 10, "minVolume": 0.01, "maxVolume": 100, "volumeStep": 0.01, "digits": spec["digits"],
            "contractSize": spec["contract"], "baseCurrency": spec["base"], "quoteCurrency": spec["quote"], "tradeMode": "SYMBOL_TRADE_MODE_FULL"}


@app.get("/users/current/accounts/{acc_id}/symbols/{symbol}/current-tick")
async def tick(acc_id: str, symbol: str):
    base, spec = _spec(symbol)
    if not spec:
        return JSONResponse({"message": f"Symbol {symbol} not found"}, status_code=404)
    p = await price_of(base)
    return {"symbol": symbol, "time": now_iso(), "bid": round(p - spec["spread"] / 2, spec["digits"]), "ask": round(p + spec["spread"] / 2, spec["digits"])}


def _close(p: dict, price: float, comment: str = "") -> dict:
    profit = _pnl(p, price)
    state["balance"] += profit + p["swap"] + p["commission"]
    deal = {"id": nid(), "platform": "mt5", "type": "DEAL_TYPE_SELL" if p["type"] == "POSITION_TYPE_BUY" else "DEAL_TYPE_BUY", "entryType": "DEAL_ENTRY_OUT",
            "symbol": p["symbol"], "positionId": p["id"], "orderId": nid(), "volume": p["volume"], "price": price, "profit": profit, "swap": p["swap"],
            "commission": 0.0, "time": now_iso(), "comment": comment, "magic": p["magic"]}
    state["deals"][p["id"]].append(deal)
    del state["positions"][p["id"]]
    return deal


@app.post("/users/current/accounts/{acc_id}/trade")
async def trade(acc_id: str, request: Request):
    body = await request.json()
    action = body.get("actionType")
    if not state["connected"]:
        return _not_connected()
    if not state["trade_allowed"]:
        return _retcode("TRADE_RETCODE_TRADE_DISABLED", 10027, "Trade disabled")
    if action in ("ORDER_TYPE_BUY", "ORDER_TYPE_SELL"):
        symbol = body.get("symbol", "")
        base, spec = _spec(symbol)
        if not spec:
            return JSONResponse({"message": f"Symbol {symbol} not found"}, status_code=404)
        vol = float(body.get("volume") or 0)
        if vol < 0.01 or round(vol / 0.01) * 0.01 - vol > 1e-9:
            return _retcode("TRADE_RETCODE_INVALID_VOLUME", 10014, "Invalid volume")
        price = await price_of(base)
        long = action == "ORDER_TYPE_BUY"
        entry = round(price + (spec["spread"] / 2 if long else -spec["spread"] / 2), spec["digits"])
        sl, tp = body.get("stopLoss"), body.get("takeProfit")
        if sl is not None and ((long and sl >= entry) or (not long and sl <= entry)):
            return _retcode("TRADE_RETCODE_INVALID_STOPS", 10016, "Invalid stops")
        pid, oid = nid(), nid()
        margin = vol * spec["contract"] * (entry if spec["quote"] == "USD" and spec["base"] != "USD" else 1.0) / 100
        state["positions"][pid] = {"id": pid, "platform": "mt5", "type": "POSITION_TYPE_BUY" if long else "POSITION_TYPE_SELL", "symbol": symbol, "magic": body.get("magic", 0),
                                   "time": now_iso(), "updateTime": now_iso(), "openPrice": entry, "currentPrice": price, "volume": vol, "swap": 0.0,
                                   "profit": _pnl({"type": "POSITION_TYPE_BUY" if long else "POSITION_TYPE_SELL", "openPrice": entry, "volume": vol, "symbol": symbol}, price),
                                   "commission": round(COMMISSION_PER_LOT * vol, 2), "stopLoss": sl, "takeProfit": tp, "clientId": body.get("clientId"), "margin": margin}
        state["deals"][pid] = [{"id": nid(), "type": "DEAL_TYPE_BUY" if long else "DEAL_TYPE_SELL", "entryType": "DEAL_ENTRY_IN", "symbol": symbol, "positionId": pid,
                                "orderId": oid, "volume": vol, "price": entry, "profit": 0.0, "swap": 0.0, "commission": round(COMMISSION_PER_LOT * vol, 2), "time": now_iso()}]
        return _retcode("TRADE_RETCODE_DONE", 10009, "Request completed", orderId=oid, positionId=pid)
    pid = str(body.get("positionId") or "")
    p = state["positions"].get(pid)
    if action == "POSITION_CLOSE_ID":
        if not p:
            return _retcode("TRADE_RETCODE_POSITION_CLOSED", 10045, "Position already closed")
        deal = _close(p, await price_of(p["symbol"]), "")
        return _retcode("TRADE_RETCODE_DONE", 10009, "Request completed", orderId=deal["orderId"], positionId=pid)
    if action == "POSITION_MODIFY":
        if not p:
            return _retcode("TRADE_RETCODE_INVALID", 10013, "Position not found")
        if body.get("stopLoss") is not None:
            p["stopLoss"] = body["stopLoss"]
        if body.get("takeProfit") is not None:
            p["takeProfit"] = body["takeProfit"]
        return _retcode("TRADE_RETCODE_DONE", 10009, "Request completed", positionId=pid)
    return _retcode("TRADE_RETCODE_INVALID", 10013, f"Unsupported action {action}")


@app.get("/users/current/accounts/{acc_id}/history-deals/position/{pid}")
async def deals(acc_id: str, pid: str):
    return state["deals"].get(pid, [])


@app.get("/users/current/accounts/{acc_id}/history-deals/time/{start}/{end}")
async def deals_by_time(acc_id: str, start: str, end: str, limit: int = 1000):
    if not state["connected"]:
        return _not_connected()
    rows = state["balance_deals"] + [d for ds in state["deals"].values() for d in ds]
    rows = [d for d in rows if start <= d["time"].replace("+00:00", "Z") <= end]
    return sorted(rows, key=lambda d: d["time"])[:limit]


@app.get("/users/current/accounts/{acc_id}/history-orders/position/{pid}")
async def orders(acc_id: str, pid: str):
    return []


# ---------- helpers ----------
@app.post("/mock/price/{symbol}")
async def set_price(symbol: str, price: float):
    state["prices"][symbol] = price
    return {"ok": True, "symbol": symbol, "price": price}


@app.post("/mock/close/{pid}")
async def force_close(pid: str, reason: str = "sl"):
    p = state["positions"].get(pid)
    if not p:
        return JSONResponse({"message": "position not found"}, status_code=404)
    price = p["stopLoss"] if reason == "sl" else p["takeProfit"]
    deal = _close(p, float(price), f"[{reason} {price}]")
    return {"ok": True, "deal": deal}


@app.post("/mock/trade-allowed")
async def set_trade_allowed(allowed: bool = True):
    state["trade_allowed"] = allowed
    return {"ok": True, "trade_allowed": allowed}


@app.post("/mock/deposit")
async def mock_deposit(amount: float, comment: str = ""):
    """Simulates a balance operation on the MT account (deposit > 0, withdrawal < 0) as a DEAL_TYPE_BALANCE deal."""
    state["balance"] += amount
    deal = {"id": nid(), "platform": "mt5", "type": "DEAL_TYPE_BALANCE", "entryType": "DEAL_ENTRY_IN", "time": now_iso(), "profit": amount,
            "swap": 0.0, "commission": 0.0, "comment": comment or ("Deposit" if amount > 0 else "Withdrawal")}
    state["balance_deals"].append(deal)
    return {"ok": True, "balance": round(state["balance"], 2), "deal": deal}


@app.post("/mock/connection")
async def set_connection(connected: bool = True):
    """Simulates the terminal losing/recovering its broker connection (provisioning status + client API errors)."""
    state["connected"] = connected
    for acc in state["accounts"].values():
        acc["connectionStatus"] = "CONNECTED" if connected else "DISCONNECTED_FROM_BROKER"
    return {"ok": True, "connected": connected}


@app.get("/mock/state")
async def mock_state():
    return {"balance": round(state["balance"], 2), "equity": _equity(), "positions": list(state["positions"].values()), "accounts": list(state["accounts"].values()),
            "deals": state["deals"], "prices": state["prices"], "trade_allowed": state["trade_allowed"], "connected": state["connected"]}


@app.post("/mock/reset")
async def mock_reset():
    reset()
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8012, log_level="warning")
