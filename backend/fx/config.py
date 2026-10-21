"""HotForex bot configuration (MetaApi/HFM credentials, forex news agent, news trading) stored in db.fx_config."""
from typing import Optional, List, Dict
from pydantic import BaseModel, ConfigDict, Field
from config import _enc, _dec, mask, _fernet
from fx.symbols import CURRENCIES

SECRET_FIELDS = ("metaapi_token", "mt_password")
REGIONS = ["new-york", "london"]
PLATFORMS = ["mt5", "mt4"]


class FxConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    trading_mode: str = "paper"
    live_since: Optional[str] = None
    metaapi_token: str = ""
    mt_login: str = ""
    mt_password: str = ""
    mt_server: str = ""
    mt_platform: str = "mt5"
    mt_symbol_suffix: str = ""
    metaapi_region: str = "new-york"
    metaapi_base_url: str = ""
    metaapi_account_id: str = ""
    hfm_state: str = ""
    hfm_connection: str = ""
    hfm_broker: str = ""
    hfm_trade_allowed: Optional[bool] = None
    hfm_verified_at: Optional[str] = None
    hfm_verified_equity: Optional[float] = None
    hfm_currency: str = ""
    hfm_leverage: Optional[int] = None
    hfm_alert_after_sec: int = 60
    news_enabled: bool = True
    news_interval_min: int = 15
    news_countries: List[str] = list(CURRENCIES)
    news_block_events: bool = True
    news_event_before_min: int = 30
    news_event_after_min: int = 15
    news_block_critical: bool = True
    news_reduce_on_high_risk: bool = True
    news_size_factor: float = 0.5
    news_trading_enabled: bool = True
    news_trade_min_confidence: int = 75
    news_trade_confirm_price: bool = True
    news_trade_window_min: int = 12
    news_trade_max_hours: int = 4
    news_trade_risk_factor: float = 1.0
    news_trade_sl_atr: float = 1.5
    news_trade_tp_atr: float = 3.0
    news_trade_max_per_event: int = 2
    wf_auto_remove: bool = True
    auto_review_enabled: bool = True
    auto_review_frequency: str = "weekly"
    auto_review_day: int = 0
    auto_review_apply: bool = True
    auto_review_last_at: Optional[str] = None
    auto_review_last_summary: str = ""
    auto_review_last_changes: Dict[str, dict] = {}


class FxConfigUpdate(BaseModel):
    metaapi_token: Optional[str] = Field(default=None, max_length=4000)
    mt_login: Optional[str] = Field(default=None, max_length=40)
    mt_password: Optional[str] = Field(default=None, max_length=200)
    mt_server: Optional[str] = Field(default=None, max_length=80)
    mt_platform: Optional[str] = None
    mt_symbol_suffix: Optional[str] = Field(default=None, max_length=12)
    metaapi_region: Optional[str] = None
    metaapi_base_url: Optional[str] = Field(default=None, max_length=200)
    hfm_alert_after_sec: Optional[int] = Field(default=None, ge=10, le=3600)
    news_enabled: Optional[bool] = None
    news_interval_min: Optional[int] = Field(default=None, ge=5, le=240)
    news_countries: Optional[List[str]] = None
    news_block_events: Optional[bool] = None
    news_event_before_min: Optional[int] = Field(default=None, ge=0, le=240)
    news_event_after_min: Optional[int] = Field(default=None, ge=0, le=240)
    news_block_critical: Optional[bool] = None
    news_reduce_on_high_risk: Optional[bool] = None
    news_size_factor: Optional[float] = Field(default=None, ge=0.1, le=1.0)
    news_trading_enabled: Optional[bool] = None
    news_trade_min_confidence: Optional[int] = Field(default=None, ge=50, le=100)
    news_trade_confirm_price: Optional[bool] = None
    news_trade_window_min: Optional[int] = Field(default=None, ge=3, le=60)
    news_trade_max_hours: Optional[int] = Field(default=None, ge=1, le=48)
    news_trade_risk_factor: Optional[float] = Field(default=None, ge=0.1, le=1.5)
    news_trade_sl_atr: Optional[float] = Field(default=None, ge=0.5, le=5)
    news_trade_tp_atr: Optional[float] = Field(default=None, ge=1, le=10)
    news_trade_max_per_event: Optional[int] = Field(default=None, ge=1, le=4)
    wf_auto_remove: Optional[bool] = None
    auto_review_enabled: Optional[bool] = None
    auto_review_frequency: Optional[str] = None
    auto_review_day: Optional[int] = Field(default=None, ge=0, le=6)
    auto_review_apply: Optional[bool] = None
    clear_hfm: bool = False


class FxConfigStore:
    def __init__(self, db):
        self.db = db
        self.cfg = FxConfig()
        self.listeners = []

    async def load(self):
        doc = await self.db.fx_config.find_one({"_id": "main"})
        if not doc:
            doc = {"_id": "main", **FxConfig().model_dump()}
            await self.db.fx_config.insert_one(doc)
        self.cfg = FxConfig.model_validate({k: (_dec(v) if k in SECRET_FIELDS else v) for k, v in doc.items()})
        await self._apply()

    async def update(self, patch: dict):
        data = self.cfg.model_dump()
        data.update(patch)
        self.cfg = FxConfig.model_validate(data)
        stored = {k: (_enc(v) if k in SECRET_FIELDS else v) for k, v in patch.items()}
        await self.db.fx_config.update_one({"_id": "main"}, {"$set": stored}, upsert=True)
        await self._apply()

    async def _apply(self):
        for fn in self.listeners:
            await fn(self.cfg)

    def public(self) -> dict:
        d = self.cfg.model_dump()
        for k in SECRET_FIELDS:
            d[k] = mask(d[k])
        d["hfm_configured"] = bool(self.cfg.metaapi_token and self.cfg.mt_login and self.cfg.mt_password and self.cfg.mt_server)
        d["metaapi_regions"] = REGIONS
        d["mt_platforms"] = PLATFORMS
        d["news_currencies"] = CURRENCIES
        d["secrets_encrypted"] = _fernet is not None
        return d

    def patch_from(self, body: FxConfigUpdate) -> dict:
        patch = {}
        for k, v in body.model_dump(exclude={"clear_hfm"}).items():
            if v is None or (k in SECRET_FIELDS and (v == "" or v.startswith("••"))):
                continue
            patch[k] = v.strip() if isinstance(v, str) else v
        if body.clear_hfm:
            patch.update(metaapi_token="", mt_login="", mt_password="", mt_server="", metaapi_account_id="", metaapi_base_url="", mt_symbol_suffix="",
                         hfm_state="", hfm_connection="", hfm_broker="",
                         hfm_trade_allowed=None, hfm_verified_at=None, hfm_verified_equity=None, hfm_currency="", hfm_leverage=None)
        if "mt_platform" in patch and patch["mt_platform"] not in PLATFORMS:
            raise ValueError("Plataforma inválida (mt4 o mt5)")
        if "metaapi_region" in patch and patch["metaapi_region"] not in REGIONS:
            raise ValueError("Región de MetaApi inválida")
        if "auto_review_frequency" in patch and patch["auto_review_frequency"] not in ("daily", "weekly"):
            raise ValueError("Frecuencia de revisión inválida (daily o weekly)")
        if "metaapi_base_url" in patch and patch["metaapi_base_url"] and not patch["metaapi_base_url"].startswith(("http://", "https://")):
            raise ValueError("El endpoint de MetaApi debe empezar por http:// o https://")
        if "mt_login" in patch and patch["mt_login"] and not patch["mt_login"].isdigit():
            raise ValueError("El login de MetaTrader debe ser numérico")
        if "news_countries" in patch:
            patch["news_countries"] = [c for c in dict.fromkeys(patch["news_countries"]) if c in CURRENCIES] or list(CURRENCIES)
        if any(k in patch for k in ("metaapi_token", "mt_login", "mt_password", "mt_server", "mt_platform", "metaapi_region", "metaapi_base_url")) and not body.clear_hfm:
            patch.update(hfm_verified_at=None, hfm_verified_equity=None, hfm_state="", hfm_connection="", hfm_trade_allowed=None)
            if any(k in patch for k in ("mt_login", "mt_server", "mt_platform", "metaapi_region", "metaapi_base_url")):
                patch["metaapi_account_id"] = ""
        return patch
