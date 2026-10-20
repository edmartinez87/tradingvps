from typing import Optional, List, Dict
from pydantic import BaseModel, ConfigDict, Field, field_validator
from models import STRATEGY_KEYS, SIGNAL_MODES
from fx.symbols import AVAILABLE, DEFAULT_SYMBOLS

FX_TIMEFRAMES = ["5m", "15m", "1h", "4h"]


class FxSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")
    strategy: str = "all"
    timeframe: str = "1h"
    symbols: List[str] = list(DEFAULT_SYMBOLS)
    risk_per_trade: float = 1.0
    max_positions: int = 5
    leverage: int = 100
    daily_loss_limit: float = 5.0
    ai_enabled: bool = True
    ai_min_confidence: int = 60
    scan_interval_sec: int = 120
    trailing_enabled: bool = True
    htf_filter: bool = True
    symbol_params: Dict[str, Dict[str, float]] = {}
    signal_mode: str = "relaxed"
    disabled_strategies: List[str] = ["supertrend_momentum"]
    close_before_weekend: bool = True
    min_lot_max_risk: float = 4.0
    risk_profile: int = 2
    bot_running: bool = False

    @field_validator("signal_mode")
    @classmethod
    def _mode(cls, v):
        if v not in SIGNAL_MODES:
            raise ValueError("Modo de señales inválido")
        return v

    @field_validator("disabled_strategies")
    @classmethod
    def _disabled(cls, v):
        v = [s for s in dict.fromkeys(v or []) if s in STRATEGY_KEYS and s != "all"]
        if len(v) >= len(STRATEGY_KEYS) - 1:
            raise ValueError("Debe quedar al menos una estrategia activa")
        return v

    @field_validator("symbol_params")
    @classmethod
    def _params(cls, v):
        out = {}
        for sym, p in (v or {}).items():
            if sym in AVAILABLE and isinstance(p, dict):
                clean = {k: float(p[k]) for k in ("sl_atr", "tp_atr", "atr_period") if p.get(k) is not None}
                if clean and 0.5 <= clean.get("sl_atr", 1.5) <= 5 and 1 <= clean.get("tp_atr", 3) <= 10 and 5 <= clean.get("atr_period", 14) <= 50:
                    out[sym] = clean
        return out

    @field_validator("strategy")
    @classmethod
    def _strategy(cls, v):
        if v not in STRATEGY_KEYS:
            raise ValueError("Estrategia inválida")
        return v

    @field_validator("timeframe")
    @classmethod
    def _tf(cls, v):
        if v not in FX_TIMEFRAMES:
            raise ValueError("Temporalidad inválida")
        return v

    @field_validator("symbols")
    @classmethod
    def _symbols(cls, v):
        v = [s for s in dict.fromkeys(v) if s in AVAILABLE]
        if not v:
            raise ValueError("Selecciona al menos un par")
        return v


class FxSettingsUpdate(BaseModel):
    strategy: Optional[str] = None
    timeframe: Optional[str] = None
    symbols: Optional[List[str]] = None
    risk_per_trade: Optional[float] = Field(default=None, ge=0.1, le=5)
    max_positions: Optional[int] = Field(default=None, ge=1, le=12)
    leverage: Optional[int] = Field(default=None, ge=1, le=500)
    daily_loss_limit: Optional[float] = Field(default=None, ge=1, le=20)
    ai_enabled: Optional[bool] = None
    ai_min_confidence: Optional[int] = Field(default=None, ge=0, le=100)
    scan_interval_sec: Optional[int] = Field(default=None, ge=30, le=900)
    trailing_enabled: Optional[bool] = None
    htf_filter: Optional[bool] = None
    symbol_params: Optional[Dict[str, Dict[str, float]]] = None
    signal_mode: Optional[str] = None
    disabled_strategies: Optional[List[str]] = None
    close_before_weekend: Optional[bool] = None
    min_lot_max_risk: Optional[float] = Field(default=None, ge=0, le=10)


class HfmTestRequest(BaseModel):
    metaapi_token: str = ""
    mt_login: str = ""
    mt_password: str = ""
    mt_server: Optional[str] = None
    mt_platform: Optional[str] = None
    metaapi_region: Optional[str] = None


class FxBacktestRequest(BaseModel):
    symbol: str
    strategy: str = "all"
    timeframe: str = "1h"
    risk_per_trade: float = Field(default=1.0, ge=0.1, le=5)
    leverage: int = Field(default=100, ge=1, le=500)


class FxProfileRequest(BaseModel):
    level: int = Field(ge=0, le=4)
