from typing import Optional
from models import Settings

BASE = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "AVAXUSDT", "LINKUSDT"]
TIER1 = BASE + ["BNBUSDT", "DOGEUSDT"]
TIER2 = TIER1 + ["ADAUSDT", "NEARUSDT"]
TIER3 = TIER2 + ["SUIUSDT", "LTCUSDT"]
NEW_STRATEGIES = ["supertrend_momentum", "ema_pullback"]

PROFILES = [
    {"level": 0, "name": "Conservador", "activity": "≈1-2 ops/día",
     "tagline": "El plan original: pocas operaciones, filtros estrictos y máxima protección del capital.",
     "warning": None,
     "settings": {"symbols": BASE, "timeframe": "1h", "signal_mode": "strict", "htf_filter": True, "ai_enabled": True,
                  "ai_min_confidence": 60, "risk_per_trade": 1.0, "max_positions": 3, "leverage": 3, "daily_loss_limit": 5.0,
                  "disabled_strategies": NEW_STRATEGIES}},
    {"level": 1, "name": "Moderado", "activity": "≈2-3 ops/día",
     "tagline": "Dos pares más y algo más de riesgo por operación; mismos criterios de entrada.",
     "warning": None,
     "settings": {"symbols": TIER1, "timeframe": "1h", "signal_mode": "strict", "htf_filter": True, "ai_enabled": True,
                  "ai_min_confidence": 55, "risk_per_trade": 1.25, "max_positions": 4, "leverage": 3, "daily_loss_limit": 6.0,
                  "disabled_strategies": NEW_STRATEGIES}},
    {"level": 2, "name": "Activo", "activity": "≈4-8 ops/día",
     "tagline": "10 pares, las 5 estrategias y criterios relajados: ideal para comparar métodos con datos reales.",
     "warning": "Más operaciones significa más comisiones y rachas de pérdidas más largas. El drawdown esperado se duplica respecto al nivel Conservador.",
     "settings": {"symbols": TIER2, "timeframe": "1h", "signal_mode": "relaxed", "htf_filter": True, "ai_enabled": True,
                  "ai_min_confidence": 50, "risk_per_trade": 1.5, "max_positions": 5, "leverage": 5, "daily_loss_limit": 8.0,
                  "disabled_strategies": []}},
    {"level": 3, "name": "Agresivo", "activity": "≈10-20 ops/día",
     "tagline": "12 pares en 15 minutos, sin filtro de tendencia superior y 2% de riesgo por operación.",
     "warning": "Con 2% por operación y 6 posiciones puedes tener un 12% del capital en riesgo a la vez. Una mala racha de 5 operaciones cuesta ~10%. El límite diario del 10% puede alcanzarse en pocas horas.",
     "settings": {"symbols": TIER3, "timeframe": "15m", "signal_mode": "relaxed", "htf_filter": False, "ai_enabled": True,
                  "ai_min_confidence": 40, "risk_per_trade": 2.0, "max_positions": 6, "leverage": 5, "daily_loss_limit": 10.0,
                  "disabled_strategies": []}},
    {"level": 4, "name": "Máximo", "activity": "20+ ops/día",
     "tagline": "Sin confirmación de IA, criterios mínimos, 3% por operación y 10x. Máxima acción, mínima protección.",
     "warning": "PUEDES QUEMAR LA CUENTA EN POCOS DÍAS. 3% por operación × 8 posiciones = 24% del capital en riesgo simultáneo con 10x de apalancamiento; "
                "las comisiones se multiplican y la IA ya no filtra nada. Pensado solo para explorar métodos en paper trading. Sin garantías de ningún tipo.",
     "settings": {"symbols": TIER3, "timeframe": "15m", "signal_mode": "minimal", "htf_filter": False, "ai_enabled": False,
                  "ai_min_confidence": 40, "risk_per_trade": 3.0, "max_positions": 8, "leverage": 10, "daily_loss_limit": 15.0,
                  "disabled_strategies": []}},
]
AI_CAPS_BASE = {"risk_per_trade": 1.5, "leverage": 5, "max_positions": 5}


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


def detect_profile(s: Settings) -> Optional[int]:
    d = s.model_dump()
    for p in PROFILES:
        if all(_eq(d[k], v) for k, v in p["settings"].items()):
            return p["level"]
    return None


def profile_patch(level: int) -> dict:
    return {**PROFILES[level]["settings"], "risk_profile": level}
