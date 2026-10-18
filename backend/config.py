import os
from typing import Optional, Dict
from pydantic import BaseModel, ConfigDict, Field
import ai_advisor
import notify
from auth import hash_password

SECRET_FIELDS = ("ai_api_key", "telegram_bot_token")
AI_PROVIDERS = ["anthropic", "openai", "gemini"]
DEFAULT_ALERTS = {"orders": True, "ai": True, "daily": True, "plan": True, "review": True}


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


class ConfigUpdate(BaseModel):
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
    clear_ai_api_key: bool = False
    clear_telegram_bot_token: bool = False


def mask(v: str) -> str:
    return f"••••••••{v[-4:]}" if v and len(v) > 8 else ("••••" if v else "")


class ConfigStore:
    def __init__(self, db):
        self.db = db
        self.cfg = AppConfig()

    async def load(self):
        doc = await self.db.config.find_one({"_id": "main"})
        if not doc:
            doc = {"_id": "main", **AppConfig(password_hash=hash_password(os.environ["INITIAL_PASSWORD"])).model_dump()}
            await self.db.config.insert_one(doc)
        self.cfg = AppConfig.model_validate(doc)
        self._apply()

    async def update(self, patch: dict):
        data = self.cfg.model_dump()
        data.update(patch)
        self.cfg = AppConfig.model_validate(data)
        await self.db.config.update_one({"_id": "main"}, {"$set": patch}, upsert=True)
        self._apply()

    def _apply(self):
        c = self.cfg
        ai_advisor.configure(c.ai_api_key or os.environ.get("EMERGENT_LLM_KEY", ""), c.ai_provider, c.ai_model)
        notify.configure(c.telegram_enabled, c.telegram_bot_token, c.telegram_chat_id, c.telegram_alerts)

    def public(self) -> dict:
        d = self.cfg.model_dump(exclude={"password_hash", "token_version"})
        for k in SECRET_FIELDS:
            d[k] = mask(d[k])
        d["ai_key_source"] = "custom" if self.cfg.ai_api_key else "emergent"
        d["ai_providers"] = AI_PROVIDERS
        d["telegram_ready"] = notify.is_on()
        return d

    def patch_from(self, body: ConfigUpdate) -> dict:
        patch = {}
        for k, v in body.model_dump(exclude={"clear_ai_api_key", "clear_telegram_bot_token"}).items():
            if v is None or (k in SECRET_FIELDS and (v == "" or v.startswith("••"))):
                continue
            patch[k] = v.strip() if isinstance(v, str) else v
        if body.clear_ai_api_key:
            patch["ai_api_key"] = ""
        if body.clear_telegram_bot_token:
            patch["telegram_bot_token"] = ""
        if "ai_provider" in patch and patch["ai_provider"] not in AI_PROVIDERS:
            raise ValueError("Proveedor de IA inválido")
        if "auto_review_frequency" in patch and patch["auto_review_frequency"] not in ("daily", "weekly"):
            raise ValueError("Frecuencia inválida")
        if "telegram_alerts" in patch:
            patch["telegram_alerts"] = {k: bool(patch["telegram_alerts"].get(k, True)) for k in DEFAULT_ALERTS}
        return patch
