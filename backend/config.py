import os
from typing import Optional, Dict
from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, ConfigDict, Field
import ai_advisor
import notify
from auth import hash_password

SECRET_FIELDS = ("ai_api_key", "telegram_bot_token", "bybit_api_key", "bybit_api_secret")
ENCRYPTED_FIELDS = ("bybit_api_secret", "bybit_api_key", "ai_api_key", "telegram_bot_token")
AI_PROVIDERS = ["anthropic", "openai", "gemini"]
BYBIT_ENVS = ["mainnet", "testnet", "demo"]
DEFAULT_ALERTS = {"orders": True, "ai": True, "daily": True, "plan": True, "review": True, "news": True}
_fernet = Fernet(os.environ["CREDENTIAL_ENCRYPTION_KEY"].encode()) if os.environ.get("CREDENTIAL_ENCRYPTION_KEY") else None


def _enc(v: str) -> str:
    return f"enc:{_fernet.encrypt(v.encode()).decode()}" if _fernet and v else v


def _dec(v: str) -> str:
    if isinstance(v, str) and v.startswith("enc:") and _fernet:
        try:
            return _fernet.decrypt(v[4:].encode()).decode()
        except InvalidToken:
            return ""
    return v or ""


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    password_hash: str = ""
    token_version: int = 1
    ai_api_key: str = ""
    ai_provider: str = "anthropic"
    ai_model: str = "claude-sonnet-5-5"
    telegram_enabled: bool = False
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_alerts: Dict[str, bool] = dict(DEFAULT_ALERTS)
    auto_review_enabled: bool = True
    auto_review_frequency: str = "weekly"
    auto_review_day: int = 0
    auto_review_apply: bool = True
    auto_review_last_at: Optional[str] = None
    auto_review_last_summary: str = ""
    auto_review_last_changes: Dict[str, dict] = {}
    trading_mode: str = "paper"
    bybit_api_key: str = ""
    bybit_api_secret: str = ""
    bybit_env: str = "mainnet"
    bybit_base_url: str = ""
    bybit_verified_at: Optional[str] = None
    bybit_verified_equity: Optional[float] = None
    live_since: Optional[str] = None
    news_enabled: bool = True
    news_interval_min: int = 20
    news_block_events: bool = True
    news_event_before_min: int = 45
    news_event_after_min: int = 30
    news_block_critical: bool = True
    news_reduce_on_high_risk: bool = True
    news_size_factor: float = 0.5
    wf_auto_remove: bool = True
    funding_enabled: bool = True
    funding_block_pct: float = 0.10
    funding_reduce_pct: float = 0.05
    funding_reduce: bool = True
    funding_size_factor: float = 0.5


class ConfigUpdate(BaseModel):
    wf_auto_remove: Optional[bool] = None
    funding_enabled: Optional[bool] = None
    funding_block_pct: Optional[float] = Field(default=None, ge=0.01, le=2.0)
    funding_reduce_pct: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    funding_reduce: Optional[bool] = None
    funding_size_factor: Optional[float] = Field(default=None, ge=0.1, le=1.0)
    news_enabled: Optional[bool] = None
    news_interval_min: Optional[int] = Field(default=None, ge=5, le=240)
    news_block_events: Optional[bool] = None
    news_event_before_min: Optional[int] = Field(default=None, ge=0, le=240)
    news_event_after_min: Optional[int] = Field(default=None, ge=0, le=240)
    news_block_critical: Optional[bool] = None
    news_reduce_on_high_risk: Optional[bool] = None
    news_size_factor: Optional[float] = Field(default=None, ge=0.1, le=1.0)
    ai_api_key: Optional[str] = None
    ai_provider: Optional[str] = None
    ai_model: Optional[str] = Field(default=None, min_length=2, max_length=80)
    telegram_enabled: Optional[bool] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = Field(default=None, max_length=40)
    telegram_alerts: Optional[Dict[str, bool]] = None
    auto_review_enabled: Optional[bool] = None
    auto_review_frequency: Optional[str] = None
    auto_review_day: Optional[int] = Field(default=None, ge=0, le=6)
    auto_review_apply: Optional[bool] = None
    bybit_api_key: Optional[str] = Field(default=None, max_length=120)
    bybit_api_secret: Optional[str] = Field(default=None, max_length=200)
    bybit_env: Optional[str] = None
    bybit_base_url: Optional[str] = Field(default=None, max_length=200)
    clear_ai_api_key: bool = False
    clear_telegram_bot_token: bool = False
    clear_bybit: bool = False


def mask(v: str) -> str:
    return f"••••••••{v[-4:]}" if v and len(v) > 8 else ("••••" if v else "")


class ConfigStore:
    def __init__(self, db):
        self.db = db
        self.cfg = AppConfig()
        self.listeners = []

    async def load(self):
        doc = await self.db.config.find_one({"_id": "main"})
        if not doc:
            doc = {"_id": "main", **AppConfig(password_hash=hash_password(os.environ["INITIAL_PASSWORD"])).model_dump()}
            await self.db.config.insert_one(doc)
        self.cfg = AppConfig.model_validate({k: (_dec(v) if k in ENCRYPTED_FIELDS else v) for k, v in doc.items()})
        await self._apply()

    async def update(self, patch: dict):
        data = self.cfg.model_dump()
        data.update(patch)
        self.cfg = AppConfig.model_validate(data)
        stored = {k: (_enc(v) if k in ENCRYPTED_FIELDS else v) for k, v in patch.items()}
        await self.db.config.update_one({"_id": "main"}, {"$set": stored}, upsert=True)
        await self._apply()

    async def _apply(self):
        c = self.cfg
        ai_advisor.configure(c.ai_api_key or os.environ.get("EMERGENT_LLM_KEY", ""), c.ai_provider, c.ai_model)
        notify.configure(c.telegram_enabled, c.telegram_bot_token, c.telegram_chat_id, c.telegram_alerts)
        for fn in self.listeners:
            await fn(c)

    def public(self) -> dict:
        d = self.cfg.model_dump(exclude={"password_hash", "token_version"})
        for k in SECRET_FIELDS:
            d[k] = mask(d[k])
        d["ai_key_source"] = "custom" if self.cfg.ai_api_key else "emergent"
        d["ai_providers"] = AI_PROVIDERS
        d["bybit_envs"] = BYBIT_ENVS
        d["bybit_configured"] = bool(self.cfg.bybit_api_key and self.cfg.bybit_api_secret)
        d["telegram_ready"] = notify.is_on()
        d["secrets_encrypted"] = _fernet is not None
        return d

    def patch_from(self, body: ConfigUpdate) -> dict:
        patch = {}
        for k, v in body.model_dump(exclude={"clear_ai_api_key", "clear_telegram_bot_token", "clear_bybit"}).items():
            if v is None or (k in SECRET_FIELDS and (v == "" or v.startswith("••"))):
                continue
            patch[k] = v.strip() if isinstance(v, str) else v
        if body.clear_ai_api_key:
            patch["ai_api_key"] = ""
        if body.clear_telegram_bot_token:
            patch["telegram_bot_token"] = ""
        if body.clear_bybit:
            patch.update(bybit_api_key="", bybit_api_secret="", bybit_verified_at=None, bybit_verified_equity=None)
        if "ai_provider" in patch and patch["ai_provider"] not in AI_PROVIDERS:
            raise ValueError("Proveedor de IA inválido")
        if "bybit_env" in patch and patch["bybit_env"] not in BYBIT_ENVS:
            raise ValueError("Entorno de Bybit inválido")
        if "bybit_base_url" in patch and patch["bybit_base_url"] and not patch["bybit_base_url"].startswith("http"):
            raise ValueError("El endpoint personalizado debe empezar por http(s)://")
        if any(k in patch for k in ("bybit_api_key", "bybit_api_secret", "bybit_env", "bybit_base_url")):
            patch.update(bybit_verified_at=None, bybit_verified_equity=None)
        if "auto_review_frequency" in patch and patch["auto_review_frequency"] not in ("daily", "weekly"):
            raise ValueError("Frecuencia inválida")
        block = patch.get("funding_block_pct", self.cfg.funding_block_pct)
        reduce = patch.get("funding_reduce_pct", self.cfg.funding_reduce_pct)
        if ("funding_block_pct" in patch or "funding_reduce_pct" in patch) and reduce > block:
            raise ValueError("El umbral de reducción debe ser menor o igual que el de bloqueo")
        if "telegram_alerts" in patch:
            merged = {**self.cfg.telegram_alerts, **patch["telegram_alerts"]}
            patch["telegram_alerts"] = {k: bool(merged.get(k, True)) for k in DEFAULT_ALERTS}
        return patch
