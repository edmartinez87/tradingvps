import time
import logging
import httpx

logger = logging.getLogger("market")

BYBIT_URL = "https://api.bybit.com"
BITGET_URL = "https://api.bitget.com"
TF_MAP = {"1m": ("1", "1m"), "5m": ("5", "5m"), "15m": ("15", "15m"), "1h": ("60", "1H"), "4h": ("240", "4H"), "1d": ("D", "1D")}
TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
HTF = {"1m": "15m", "5m": "1h", "15m": "1h", "1h": "4h", "4h": "1d"}


class MarketData:
    """Bybit public data with automatic Bitget USDT-perp mirror when Bybit is geo-blocked."""

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=12)
        self.provider = None
        self.tickers = {}
        self.tickers_ts = 0.0
        self._kcache = {}

    async def detect(self):
        try:
            r = await self.client.get(f"{BYBIT_URL}/v5/market/time")
            if r.status_code == 200 and r.json().get("retCode") == 0:
                self.provider = "bybit"
                return self.provider
        except Exception as e:
            logger.warning(f"Bybit no accesible: {e}")
        self.provider = "bitget"
        return self.provider

    async def fetch_tickers(self) -> dict:
        out = {}
        if self.provider == "bybit":
            r = await self.client.get(f"{BYBIT_URL}/v5/market/tickers", params={"category": "linear"})
            for t in r.json()["result"]["list"]:
                out[t["symbol"]] = {
                    "symbol": t["symbol"], "price": float(t["lastPrice"]),
                    "change_pct": float(t.get("price24hPcnt") or 0) * 100,
                    "high": float(t.get("highPrice24h") or 0), "low": float(t.get("lowPrice24h") or 0),
                    "volume_usdt": float(t.get("turnover24h") or 0),
                    "funding_rate": float(t.get("fundingRate") or 0),
                }
        else:
            r = await self.client.get(f"{BITGET_URL}/api/v2/mix/market/tickers", params={"productType": "USDT-FUTURES"})
            for t in r.json()["data"]:
                out[t["symbol"]] = {
                    "symbol": t["symbol"], "price": float(t["lastPr"]),
                    "change_pct": float(t.get("change24h") or 0) * 100,
                    "high": float(t.get("high24h") or 0), "low": float(t.get("low24h") or 0),
                    "volume_usdt": float(t.get("quoteVolume") or 0),
                    "funding_rate": float(t.get("fundingRate") or 0),
                }
        self.tickers = out
        self.tickers_ts = time.time()
        return out

    async def fetch_klines(self, symbol: str, tf: str, limit: int = 300, cache_sec: int = 8) -> list:
        key = (symbol, tf, limit)
        hit = self._kcache.get(key)
        if hit and time.time() - hit[0] < cache_sec:
            return hit[1]
        bybit_tf, bitget_tf = TF_MAP[tf]
        if self.provider == "bybit":
            r = await self.client.get(f"{BYBIT_URL}/v5/market/kline", params={
                "category": "linear", "symbol": symbol, "interval": bybit_tf, "limit": limit})
            rows = list(reversed(r.json()["result"]["list"]))
        else:
            r = await self.client.get(f"{BITGET_URL}/api/v2/mix/market/candles", params={
                "symbol": symbol, "granularity": bitget_tf, "limit": limit, "productType": "USDT-FUTURES"})
            rows = r.json()["data"]
        data = [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])] for k in rows]
        self._kcache[key] = (time.time(), data)
        return data
