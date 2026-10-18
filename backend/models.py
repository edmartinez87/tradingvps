from datetime import datetime, timezone
from typing import Annotated, Optional, List, Dict, Any
from bson import ObjectId
from pydantic import BaseModel, BeforeValidator, Field, ConfigDict, field_validator

PyObjectId = Annotated[str, BeforeValidator(lambda v: str(v) if isinstance(v, ObjectId) else v)]

AVAILABLE_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT",
    "AVAXUSDT", "LINKUSDT", "ADAUSDT", "NEARUSDT", "SUIUSDT", "LTCUSDT",
]
TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h"]
STRATEGY_KEYS = ["all", "trend_ema", "mean_reversion", "breakout_turtle"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class BaseDocument(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")
    id: Optional[PyObjectId] = Field(default=None, alias="_id")

    @classmethod
    def from_mongo(cls, doc):
        return cls.model_validate(doc) if doc else None

    def to_mongo(self) -> dict:
        data = self.model_dump(exclude={"id"})
        if self.id:
            data["_id"] = ObjectId(self.id)
        return data


class Settings(BaseModel):
    model_config = ConfigDict(extra="ignore")
    strategy: str = "all"
    timeframe: str = "1h"
    symbols: List[str] = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "AVAXUSDT", "LINKUSDT"]
    risk_per_trade: float = 1.0
    max_positions: int = 3
    leverage: int = 3
    daily_loss_limit: float = 5.0
    ai_enabled: bool = True
    ai_min_confidence: int = 60
    scan_interval_sec: int = 60
    trailing_enabled: bool = True
    htf_filter: bool = True
    bot_running: bool = False

    @field_validator("strategy")
    @classmethod
    def _strategy(cls, v):
        if v not in STRATEGY_KEYS:
            raise ValueError("Estrategia inválida")
        return v

    @field_validator("timeframe")
    @classmethod
    def _tf(cls, v):
        if v not in TIMEFRAMES:
            raise ValueError("Temporalidad inválida")
        return v

    @field_validator("symbols")
    @classmethod
    def _symbols(cls, v):
        v = [s for s in dict.fromkeys(v) if s in AVAILABLE_SYMBOLS]
        if not v:
            raise ValueError("Selecciona al menos un símbolo")
        return v


class SettingsUpdate(BaseModel):
    strategy: Optional[str] = None
    timeframe: Optional[str] = None
    symbols: Optional[List[str]] = None
    risk_per_trade: Optional[float] = Field(default=None, ge=0.1, le=5)
    max_positions: Optional[int] = Field(default=None, ge=1, le=10)
    leverage: Optional[int] = Field(default=None, ge=1, le=20)
    daily_loss_limit: Optional[float] = Field(default=None, ge=1, le=20)
    ai_enabled: Optional[bool] = None
    ai_min_confidence: Optional[int] = Field(default=None, ge=0, le=100)
    scan_interval_sec: Optional[int] = Field(default=None, ge=30, le=900)
    trailing_enabled: Optional[bool] = None
    htf_filter: Optional[bool] = None


class Position(BaseDocument):
    symbol: str
    side: str
    strategy: str
    entry_price: float
    qty: float
    leverage: int
    margin: float
    sl: float
    tp: float
    initial_sl: float
    atr: float
    fees: float
    mark_price: float
    unrealized_pnl: float = 0.0
    breakeven: bool = False
    signal_id: Optional[str] = None
    opened_at: str = Field(default_factory=now_iso)


class Trade(BaseDocument):
    symbol: str
    side: str
    strategy: str
    entry_price: float
    exit_price: float
    qty: float
    leverage: int
    margin: float
    pnl: float
    pnl_pct: float
    fees: float
    reason: str
    opened_at: str
    closed_at: str = Field(default_factory=now_iso)


class Signal(BaseDocument):
    symbol: str
    side: str
    strategy: str
    timeframe: str
    price: float
    sl: float
    tp: float
    score: int
    reasons: List[str]
    indicators: Dict[str, Any]
    ai_decision: str
    ai_confidence: int = 0
    ai_risk: str = "-"
    ai_reasoning: str = ""
    executed: bool = False
    note: str = ""
    key: str = ""
    created_at: str = Field(default_factory=now_iso)


class LogEntry(BaseDocument):
    level: str
    message: str
    ts: str = Field(default_factory=now_iso)


class BacktestRequest(BaseModel):
    symbol: str
    strategy: str = "all"
    timeframe: str = "15m"
    risk_per_trade: float = Field(default=1.0, ge=0.1, le=5)
    leverage: int = Field(default=3, ge=1, le=20)


class ResetRequest(BaseModel):
    initial_balance: Optional[float] = Field(default=None, ge=10, le=10_000_000)


class PlanRequest(BaseModel):
    initial_capital: float = Field(default=500, ge=50, le=10_000_000)
    monthly_deposit: float = Field(default=0, ge=0, le=1_000_000)
    target_monthly: float = Field(default=1000, ge=50, le=10_000_000)
    scenario: str = "base"
