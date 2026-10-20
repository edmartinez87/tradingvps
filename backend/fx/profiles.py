"""Five risk presets for the HotForex bot (forex hours, lots and 1:100-1:500 leverage). Level 2 equals the default FX settings."""
from typing import Optional
from fx.symbols import AVAILABLE

CORE = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD"]
TIER1 = CORE + ["XAGUSD", "USDCAD", "NZDUSD"]
ALL = list(AVAILABLE)
NEW_STRATEGIES = ["supertrend_momentum", "ema_pullback"]

PROFILES = [
    {"level": 0, "name": "Conservador", "activity": "≈0-1 ops/día",
     "tagline": "Oro y 5 mayores en 1h con criterios estrictos, medio punto de riesgo y solo 2 posiciones: protección máxima del capital.",
     "warning": None,
     "settings": {"symbols": CORE, "timeframe": "1h", "signal_mode": "strict", "htf_filter": True, "ai_enabled": True,
                  "ai_min_confidence": 65, "risk_per_trade": 0.5, "max_positions": 2, "leverage": 100, "daily_loss_limit": 3.0,
                  "disabled_strategies": NEW_STRATEGIES}},
    {"level": 1, "name": "Moderado", "activity": "≈1-2 ops/día",
     "tagline": "Añade plata, CAD y NZD; 1% por operación y hasta 3 posiciones con los mismos criterios estrictos.",
     "warning": None,
     "settings": {"symbols": TIER1, "timeframe": "1h", "signal_mode": "strict", "htf_filter": True, "ai_enabled": True,
                  "ai_min_confidence": 60, "risk_per_trade": 1.0, "max_positions": 3, "leverage": 100, "daily_loss_limit": 5.0,
                  "disabled_strategies": NEW_STRATEGIES}},
    {"level": 2, "name": "Activo", "activity": "≈2-5 ops/día",
     "tagline": "Los 12 pares (incluidos los cruces con yen) en 1h, criterios relajados, 4 estrategias y hasta 5 posiciones: la configuración por defecto.",
     "warning": "Los cruces con yen (EURJPY, GBPJPY) se mueven mucho más: con 5 posiciones abiertas el drawdown puede doblar al del nivel Moderado.",
     "settings": {"symbols": ALL, "timeframe": "1h", "signal_mode": "relaxed", "htf_filter": True, "ai_enabled": True,
                  "ai_min_confidence": 60, "risk_per_trade": 1.0, "max_positions": 5, "leverage": 100, "daily_loss_limit": 5.0,
                  "disabled_strategies": ["supertrend_momentum"]}},
    {"level": 3, "name": "Agresivo", "activity": "≈5-15 ops/día",
     "tagline": "12 pares en 15 minutos, sin filtro de tendencia superior, 1.5% por operación, 6 posiciones y 1:200.",
     "warning": "Con 1.5% por operación y 6 posiciones puedes tener un 9% del capital en riesgo a la vez; en 15m las noticias de alto impacto "
                "pueden saltar varios stops seguidos. El límite diario del 8% puede alcanzarse en una sesión.",
     "settings": {"symbols": ALL, "timeframe": "15m", "signal_mode": "relaxed", "htf_filter": False, "ai_enabled": True,
                  "ai_min_confidence": 50, "risk_per_trade": 1.5, "max_positions": 6, "leverage": 200, "daily_loss_limit": 8.0,
                  "disabled_strategies": []}},
    {"level": 4, "name": "Máximo", "activity": "15+ ops/día",
     "tagline": "Sin confirmación de IA, criterios mínimos, 2% por operación, 8 posiciones y 1:500. Máxima acción, mínima protección.",
     "warning": "PUEDES QUEMAR LA CUENTA EN POCOS DÍAS. 2% × 8 posiciones = 16% del capital en riesgo simultáneo con 1:500; un dato macro "
                "en contra puede cerrar varias posiciones a la vez y la IA ya no filtra nada. Solo para explorar métodos en paper trading.",
     "settings": {"symbols": ALL, "timeframe": "15m", "signal_mode": "minimal", "htf_filter": False, "ai_enabled": False,
                  "ai_min_confidence": 40, "risk_per_trade": 2.0, "max_positions": 8, "leverage": 500, "daily_loss_limit": 12.0,
                  "disabled_strategies": []}},
]
AI_CAPS_BASE = {"risk_per_trade": 1.5, "leverage": 100, "max_positions": 6}


def ai_policy(level: int) -> dict:
    p = PROFILES[max(0, min(level, 4))]["settings"]
    return {
        "caps": {k: max(AI_CAPS_BASE[k], p[k]) for k in AI_CAPS_BASE},
        "min_trades": 30 if level <= 1 else 20,
        "min_item_trades": 20 if level <= 1 else 15,
        "level": level, "name": PROFILES[level]["name"],
    }


def _eq(a, b) -> bool:
    return set(a) == set(b) if isinstance(a, list) else a == b


def detect_profile(settings) -> Optional[int]:
    d = settings.model_dump()
    for p in PROFILES:
        if all(_eq(d[k], v) for k, v in p["settings"].items()):
            return p["level"]
    return None


def profile_patch(level: int) -> dict:
    return {**PROFILES[level]["settings"], "risk_profile": level}
