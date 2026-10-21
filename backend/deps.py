"""Shared application state (db, engine, config store, news agent, auth) used by server.py and the routers."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from fastapi import APIRouter, Depends  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from engine import TradingEngine  # noqa: E402
from config import ConfigStore  # noqa: E402
from news import NewsAgent  # noqa: E402
from auth import make_require_auth  # noqa: E402
from ai_usage import AiUsage  # noqa: E402
import ai_advisor  # noqa: E402

client = AsyncIOMotorClient(os.environ["MONGO_URL"])
db = client[os.environ["DB_NAME"]]
engine = TradingEngine(db)
store = ConfigStore(db)
news = NewsAgent(db, engine)
engine.news = news
require_auth = make_require_auth(lambda: store.cfg.token_version)
ai_usage = AiUsage(db)
ai_advisor.set_usage_hook(ai_usage.record)

from fx.engine import FxEngine  # noqa: E402
from fx.config import FxConfigStore  # noqa: E402
from fx.news import FxNewsAgent  # noqa: E402

fx_engine = FxEngine(db)
fx_store = FxConfigStore(db)
fx_engine.store = fx_store
fx_news = FxNewsAgent(fx_engine.db, fx_engine)
fx_engine.news = fx_news


def protected_router() -> APIRouter:
    return APIRouter(prefix="/api", dependencies=[Depends(require_auth)])
