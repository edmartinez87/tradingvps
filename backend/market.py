import time
import asyncio
import logging
import httpx

logger = logging.getLogger("market")

BYBIT_URL = "https://api.bybit.com"
BITGET_URL = "https://api.bitget.com"
TF_MAP = {"1m": ("1", "1m"), "5m": ("5", "5m"), "15m": ("15", "15m"), "1h": ("60", "1H"), "4h": ("240", "4H"), "1d": ("D", "1D")}
TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
HTF = {"1m": "15m", "5m": "1h", "15m": "1h", "1h": "4h", "4h": "1d"}


class MarketData:
    """Bybit public data with automatic Bitget USDT-perp mirror when Bybit is geo-blocked or fails."""

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=12)
        self.provider = None
        self.tickers = {}
        self.tickers_ts = 0.0
        self._kcache = {}
        self._fallback_warned = 0.0

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

    async def _bybit(self, path: str, params: dict):
        err = "Bybit sin respuesta"
        for attempt in range(2):
            try:
                r = await self.client.get(f"{BYBIT_URL}{path}", params=params)
                data = r.json()
                if r.status_code == 200 and data.get("retCode") == 0:
                    return data["result"]
                err = f"Bybit {data.get('retCode', r.status_code)}: {data.get('retMsg') or 'error'}"
            except Exception as e:
                err = f"Bybit: {type(e).__name__} {str(e)[:80]}"
            await asyncio.sleep(0.4 * (attempt + 1))
        raise RuntimeError(err)

    async def _bitget(self, path: str, params: dict):
        r = await self.client.get(f"{BITGET_URL}{path}", params=params)
        data = r.json()
        if r.status_code != 200 or str(data.get("code")) != "00000":
            raise RuntimeError(f"Bitget {data.get('code', r.status_code)}: {data.get('msg') or 'error'}")
        return data["data"]

    def _warn_fallback(self, what: str, err: str):
        if time.time() - self._fallback_warned > 300:
            self._fallback_warned = time.time()
            logger.warning(f"{what}: {err} → usando espejo Bitget")

    async def fetch_tickers(self) -> dict:
        out = {}
        if self.provider == "bybit":
            try:
                rows = (await self._bybit("/v5/market/tickers", {"category": "linear"}))["list"]
            except RuntimeError as e:
                self._warn_fallback("tickers", str(e))
                rows = None
            if rows is not None:
                for t in rows:
                    out[t["symbol"]] = {
                        "symbol": t["symbol"], "price": float(t["lastPrice"]),
                        "change_pct": float(t.get("price24hPcnt") or 0) * 100,
                        "high": float(t.get("highPrice24h") or 0), "low": float(t.get("lowPrice24h") or 0),
                        "volume_usdt": float(t.get("turnover24h") or 0),
                        "funding_rate": float(t.get("fundingRate") or 0),
                    }
        if not out:
            for t in await self._bitget("/api/v2/mix/market/tickers", {"productType": "USDT-FUTURES"}):
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
        rows = None
        if self.provider == "bybit":
            try:
                rows = list(reversed((await self._bybit("/v5/market/kline", {
                    "category": "linear", "symbol": symbol, "interval": bybit_tf, "limit": limit}))["list"]))
            except RuntimeError as e:
                self._warn_fallback(f"klines {symbol} {tf}", str(e))
        if rows is None:
            try:
                rows = await self._bitget("/api/v2/mix/market/candles", {
                    "symbol": symbol, "granularity": bitget_tf, "limit": limit, "productType": "USDT-FUTURES"})
            except Exception as e:
                if hit:
                    logger.warning(f"klines {symbol} {tf}: {e} → usando caché de hace {int(time.time() - hit[0])}s")
                    return hit[1]
                raise RuntimeError(f"sin datos de mercado para {symbol} {tf}: {e}")
        data = [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])] for k in rows]
        self._kcache[key] = (time.time(), data)
        return data

    async def fetch_history(self, symbol: str, tf: str, total: int = 2000, cache_sec: int = 600) -> list:
        """Up to `total` candles paginating backwards (Bybit `end` / Bitget history-candles). Returns what it could get (≥ 1 page)."""
        key = (symbol, tf, "history", total)
        hit = self._kcache.get(key)
        if hit and time.time() - hit[0] < cache_sec:
            return hit[1]
        data = list(await self.fetch_klines(symbol, tf, 1000, cache_sec=300))
        bybit_tf, bitget_tf = TF_MAP[tf]
        while len(data) < total:
            oldest, end = data[0][0], data[0][0] - 1
            rows = None
            if self.provider == "bybit":
                try:
                    rows = (await self._bybit("/v5/market/kline", {"category": "linear", "symbol": symbol, "interval": bybit_tf,
                                                                    "limit": min(1000, total - len(data)), "end": end}))["list"]
                except RuntimeError as e:
                    self._warn_fallback(f"historial {symbol} {tf}", str(e))
            if rows is None:
                try:
                    rows = await self._bitget("/api/v2/mix/market/history-candles", {"symbol": symbol, "granularity": bitget_tf, "limit": min(200, total - len(data)),
                                                                                       "productType": "USDT-FUTURES", "endTime": end})
                except Exception as e:
                    logger.warning(f"historial {symbol} {tf}: {e} → usando {len(data)} velas")
                    break
            older = [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])] for k in rows if int(k[0]) < oldest]
            if not older:
                break
            data = sorted(older) + data
        self._kcache[key] = (time.time(), data[-total:])
        return data[-total:]
