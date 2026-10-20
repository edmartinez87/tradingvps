"""MetaApi.cloud REST bridge for MetaTrader (HFM) accounts. Phase 1: token validation, account lookup/provision/deploy, account info & positions."""
import uuid
import asyncio
import httpx

PROV = "https://mt-provisioning-api-v1.agiliumtrade.agiliumtrade.ai"


def client_base(region: str) -> str:
    return f"https://mt-client-api-v1.{region}.agiliumtrade.ai"


class MetaApiError(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status, self.msg = status, msg


class MetaApi:
    def __init__(self, token: str, region: str = "new-york"):
        self.token, self.region = token, region
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(25.0, connect=8.0))

    async def _call(self, method: str, url: str, json: dict = None, tx: str = None):
        headers = {"auth-token": self.token, "Accept": "application/json"}
        if json is not None:
            headers["Content-Type"] = "application/json"
        if tx:
            headers["transaction-id"] = tx
        r = await self.client.request(method, url, headers=headers, json=json)
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
        return None if r.status_code == 204 else r.json()

    async def list_accounts(self) -> list:
        res = await self._call("GET", f"{PROV}/users/current/accounts")
        return res if isinstance(res, list) else (res or {}).get("items", [])

    async def account(self, account_id: str) -> dict:
        return await self._call("GET", f"{PROV}/users/current/accounts/{account_id}")

    async def find_account(self, login: str, server: str = "") -> dict | None:
        for a in await self.list_accounts():
            if str(a.get("login")) == str(login) and (not server or str(a.get("server", "")).lower() == server.lower()):
                return a
        return None

    async def provision(self, login: str, password: str, server: str, platform: str, name: str = "hotforex-ai-trading") -> dict:
        payload = {"login": str(login), "password": password, "name": name, "server": server, "platform": platform, "magic": 0,
                   "type": "cloud-g2", "region": self.region, "manualTrades": False, "keywords": ["HFM", "HotForex"]}
        tx = uuid.uuid4().hex[:32]
        for _ in range(6):
            res = await self._call("POST", f"{PROV}/users/current/accounts", json=payload, tx=tx)
            if not (isinstance(res, dict) and res.get("_retry")):
                return res or {}
            await asyncio.sleep(min(res["retry_after"], 10))
        raise MetaApiError(202, "MetaApi sigue validando la cuenta; vuelve a probar en un minuto")

    async def deploy(self, account_id: str):
        return await self._call("POST", f"{PROV}/users/current/accounts/{account_id}/deploy", json={})

    async def account_info(self, account_id: str, region: str = None) -> dict:
        return await self._call("GET", f"{client_base(region or self.region)}/users/current/accounts/{account_id}/account-information")

    async def positions(self, account_id: str, region: str = None) -> list:
        return await self._call("GET", f"{client_base(region or self.region)}/users/current/accounts/{account_id}/positions") or []

    async def aclose(self):
        await self.client.aclose()
