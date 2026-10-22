"""MetaApi.cloud REST bridge for MetaTrader 4/5 (HFM) accounts: provisioning (link/deploy/redeploy), account state, symbol specs/ticks,
trades (market order with SL/TP, close, modify), history deals. `base_url` overrides both hosts (local mock / custom endpoint)."""
import time
import uuid
import asyncio
import httpx
from urllib.parse import quote

PROV = "https://mt-provisioning-api-v1.agiliumtrade.agiliumtrade.ai"
MAGIC = 777001
# MetaApi pay-as-you-go infrastructure options (USD, excl. VAT; metaapi.cloud pricing). Type/reliability can't be changed on an existing account.
PLANS = {
    "g2-high": {"type": "cloud-g2", "reliability": "high", "label": "Cloud G2 · fiabilidad alta", "short": "G2 alta", "hour_usd": 0.012, "deploy_usd": 0.072,
                "recommended": True, "note": "La más barata y la más rápida (ticks < 2,5 s). Es la que MetaApi recomienda para producción: sirve igual para demo y para dinero real."},
    "g1-regular": {"type": "cloud-g1", "reliability": "regular", "label": "Cloud G1 · fiabilidad regular", "short": "G1 regular", "hour_usd": 0.019688, "deploy_usd": 0.118125,
                   "recommended": False, "note": "Infraestructura antigua sin redundancia. Solo tiene sentido si tu servidor de HFM no conecta en G2."},
    "g1-high": {"type": "cloud-g1", "reliability": "high", "label": "Cloud G1 · fiabilidad alta", "short": "G1 alta", "hour_usd": 0.039376, "deploy_usd": 0.23625,
                "recommended": False, "note": "La más cara: G1 con servidores redundantes. Útil solo si necesitas G1 y máxima estabilidad con dinero real."},
}
PLAN_COMMON = {"account_month_usd": 2.1, "undeployed_hour_usd": 0.00105}


def plan_key(acc_type: str, reliability: str) -> str:
    t = "cloud-g2" if (acc_type or "") in ("cloud", "cloud-g2") else "cloud-g1"
    r = "regular" if (reliability or "high") == "regular" and t == "cloud-g1" else "high"
    return next(k for k, p in PLANS.items() if p["type"] == t and p["reliability"] == r)
OK_CODES = {"TRADE_RETCODE_DONE", "TRADE_RETCODE_PLACED", "TRADE_RETCODE_DONE_PARTIAL"}
RETCODE_TXT = {
    "TRADE_RETCODE_REQUOTE": "recotización del precio", "TRADE_RETCODE_REJECT": "orden rechazada por el bróker", "TRADE_RETCODE_CANCEL": "orden cancelada",
    "TRADE_RETCODE_INVALID": "petición inválida", "TRADE_RETCODE_INVALID_VOLUME": "volumen inválido (lote mínimo/paso)", "TRADE_RETCODE_INVALID_PRICE": "precio inválido",
    "TRADE_RETCODE_INVALID_STOPS": "SL/TP demasiado cerca del precio (stops inválidos)", "TRADE_RETCODE_MARKET_CLOSED": "mercado cerrado",
    "TRADE_RETCODE_NO_MONEY": "margen insuficiente", "TRADE_RETCODE_PRICE_CHANGED": "el precio cambió", "TRADE_RETCODE_TOO_MANY_REQUESTS": "demasiadas peticiones",
    "TRADE_RETCODE_TRADE_DISABLED": "trading deshabilitado en la cuenta", "TRADE_RETCODE_POSITION_CLOSED": "la posición ya estaba cerrada",
}


def client_base(region: str) -> str:
    return f"https://mt-client-api-v1.{region}.agiliumtrade.ai"


class MetaApiError(Exception):
    def __init__(self, status: int, msg: str, code: str = ""):
        super().__init__(msg)
        self.status, self.msg, self.code = status, msg, code


class MetaApi:
    def __init__(self, token: str, region: str = "new-york", base_url: str = ""):
        self.token, self.region, self.base_url = token, region, (base_url or "").rstrip("/")
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(25.0, connect=8.0))
        self._specs = {}

    def _prov(self) -> str:
        return self.base_url or PROV

    def _cli(self, region: str = None) -> str:
        return self.base_url or client_base(region or self.region)

    async def _call(self, method: str, url: str, json: dict = None, tx: str = None, params: dict = None):
        headers = {"auth-token": self.token, "Accept": "application/json"}
        if json is not None:
            headers["Content-Type"] = "application/json"
        if tx:
            headers["transaction-id"] = tx
        try:
            r = await self.client.request(method, url, headers=headers, json=json, params=params)
        except httpx.HTTPError as e:
            raise MetaApiError(0, f"MetaApi no responde: {str(e)[:120] or type(e).__name__}")
        if r.status_code == 401:
            raise MetaApiError(401, "MetaApi rechazó el token (401): revisa el token en app.metaapi.cloud/token")
        if r.status_code == 429:
            raise MetaApiError(429, "MetaApi: límite de peticiones alcanzado, inténtalo en unos segundos")
        if r.status_code == 202:
            return {"_retry": True, "retry_after": int(r.headers.get("Retry-After") or 3)}
        if r.status_code >= 400:
            try:
                detail = r.json()
                msg = detail.get("message") or detail.get("error") or str(detail)
            except ValueError:
                msg = r.text[:300]
            raise MetaApiError(r.status_code, f"MetaApi {r.status_code}: {str(msg)[:300]}")
        return None if r.status_code == 204 or not r.content else r.json()

    # ---------- provisioning ----------
    async def list_accounts(self) -> list:
        res = await self._call("GET", f"{self._prov()}/users/current/accounts")
        return res if isinstance(res, list) else (res or {}).get("items", [])

    async def account(self, account_id: str) -> dict:
        return await self._call("GET", f"{self._prov()}/users/current/accounts/{account_id}")

    async def find_account(self, login: str, server: str = "") -> dict | None:
        for a in await self.list_accounts():
            if str(a.get("login")) == str(login) and (not server or str(a.get("server", "")).lower() == server.lower()):
                return a
        return None

    async def provision(self, login: str, password: str, server: str, platform: str, name: str = "hotforex-ai-trading", plan: str = "g2-high") -> dict:
        p = PLANS.get(plan) or PLANS["g2-high"]
        payload = {"login": str(login), "password": password, "name": name, "server": server, "platform": platform, "magic": MAGIC,
                   "type": p["type"], "reliability": p["reliability"], "region": self.region, "manualTrades": False, "keywords": ["HFM", "HotForex"]}
        tx = uuid.uuid4().hex[:32]
        for _ in range(6):
            res = await self._call("POST", f"{self._prov()}/users/current/accounts", json=payload, tx=tx)
            if not (isinstance(res, dict) and res.get("_retry")):
                return res or {}
            await asyncio.sleep(min(res["retry_after"], 10))
        raise MetaApiError(202, "MetaApi sigue validando la cuenta; vuelve a probar en un minuto")

    async def deploy(self, account_id: str):
        return await self._call("POST", f"{self._prov()}/users/current/accounts/{account_id}/deploy", json={})

    async def redeploy(self, account_id: str):
        return await self._call("POST", f"{self._prov()}/users/current/accounts/{account_id}/redeploy", json={}, params={"executeForAllReplicas": "true"})

    async def undeploy(self, account_id: str):
        return await self._call("POST", f"{self._prov()}/users/current/accounts/{account_id}/undeploy", json={}, params={"executeForAllReplicas": "true"})

    async def delete_account(self, account_id: str):
        return await self._call("DELETE", f"{self._prov()}/users/current/accounts/{account_id}", params={"executeForAllReplicas": "true"})

    # ---------- terminal state ----------
    def _acc(self, account_id: str, region: str = None) -> str:
        return f"{self._cli(region)}/users/current/accounts/{account_id}"

    async def account_info(self, account_id: str, region: str = None, refresh: bool = False) -> dict:
        return await self._call("GET", f"{self._acc(account_id, region)}/account-information", params={"refreshTerminalState": "true"} if refresh else None)

    async def positions(self, account_id: str, region: str = None, refresh: bool = False) -> list:
        return await self._call("GET", f"{self._acc(account_id, region)}/positions", params={"refreshTerminalState": "true"} if refresh else None) or []

    async def spec(self, account_id: str, symbol: str, region: str = None, max_age: float = 3600) -> dict:
        hit = self._specs.get(symbol)
        if hit and time.time() - hit[0] < max_age:
            return hit[1]
        s = await self._call("GET", f"{self._acc(account_id, region)}/symbols/{quote(symbol, safe='')}/specification")
        self._specs[symbol] = (time.time(), s)
        return s

    async def tick(self, account_id: str, symbol: str, region: str = None) -> dict:
        return await self._call("GET", f"{self._acc(account_id, region)}/symbols/{quote(symbol, safe='')}/current-tick")

    async def deals_by_position(self, account_id: str, position_id: str, region: str = None) -> list:
        return await self._call("GET", f"{self._acc(account_id, region)}/history-deals/position/{position_id}") or []

    async def deals_by_time(self, account_id: str, start_iso: str, end_iso: str, region: str = None, limit: int = 1000) -> list:
        return await self._call("GET", f"{self._acc(account_id, region)}/history-deals/time/{quote(start_iso, safe='')}/{quote(end_iso, safe='')}",
                                params={"limit": limit}) or []

    async def orders_by_position(self, account_id: str, position_id: str, region: str = None) -> list:
        return await self._call("GET", f"{self._acc(account_id, region)}/history-orders/position/{position_id}") or []

    # ---------- trading ----------
    async def trade(self, account_id: str, payload: dict, region: str = None) -> dict:
        res = await self._call("POST", f"{self._acc(account_id, region)}/trade", json=payload) or {}
        code = str(res.get("stringCode") or "")
        if code not in OK_CODES:
            txt = RETCODE_TXT.get(code, res.get("message") or code or "sin código de respuesta")
            raise MetaApiError(200, f"MetaTrader: {txt} ({code or res.get('numericCode', '?')})", code)
        return res

    async def market_order(self, account_id: str, symbol: str, side: str, volume: float, sl: float, tp: float, client_id: str, region: str = None) -> dict:
        payload = {"actionType": "ORDER_TYPE_BUY" if side == "long" else "ORDER_TYPE_SELL", "symbol": symbol, "volume": volume,
                   "stopLoss": sl, "takeProfit": tp, "clientId": client_id, "magic": MAGIC}
        return await self.trade(account_id, payload, region)

    async def close_position(self, account_id: str, position_id: str, region: str = None) -> dict:
        return await self.trade(account_id, {"actionType": "POSITION_CLOSE_ID", "positionId": str(position_id), "clientId": "bot-close"}, region)

    async def modify_position(self, account_id: str, position_id: str, sl: float, tp: float, region: str = None) -> dict:
        return await self.trade(account_id, {"actionType": "POSITION_MODIFY", "positionId": str(position_id), "stopLoss": sl, "takeProfit": tp}, region)

    async def aclose(self):
        await self.client.aclose()
