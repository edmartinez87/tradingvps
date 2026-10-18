import os
import re
import json
import uuid
import logging
from emergentintegrations.llm.chat import LlmChat, UserMessage, TextDelta, StreamDone

logger = logging.getLogger("ai")
_cfg = {"api_key": os.environ.get("EMERGENT_LLM_KEY", ""), "provider": "anthropic", "model": "claude-sonnet-5-5"}


def configure(api_key: str, provider: str, model: str):
    _cfg.update(api_key=api_key, provider=provider, model=model)


def current() -> dict:
    return {"provider": _cfg["provider"], "model": _cfg["model"]}


def _chat(system: str, prefix: str) -> LlmChat:
    return LlmChat(api_key=_cfg["api_key"], session_id=f"{prefix}-{uuid.uuid4()}", system_message=system) \
        .with_model(_cfg["provider"], _cfg["model"])


async def _ask(chat: LlmChat, prompt: str) -> str:
    text = ""
    async for ev in chat.stream_message(UserMessage(text=prompt)):
        if isinstance(ev, TextDelta):
            text += ev.content
        elif isinstance(ev, StreamDone):
            break
    return text


async def ping() -> str:
    text = await _ask(_chat("Responde en español con una sola frase breve.", "ping"), "Confirma que estás operativo para analizar señales de trading.")
    return text.strip()[:200]

SYSTEM = (
    "Eres un gestor de riesgo cuantitativo senior especializado en futuros perpetuos USDT de criptomonedas. "
    "Evalúas señales generadas por un sistema algorítmico y decides si se ejecutan. Prioriza preservar capital: "
    "rechaza señales con indicadores contradictorios, entradas tardías (RSI extremo a favor), contra la tendencia mayor, "
    "con volatilidad anormal o funding rate extremo en contra. Aprueba solo setups con confluencia clara. "
    "Responde EXCLUSIVAMENTE con un objeto JSON válido, sin texto adicional, con este formato: "
    '{"decision":"APROBAR" o "RECHAZAR","confidence":entero 0-100,"risk":"BAJO"|"MEDIO"|"ALTO","reasoning":"máximo 3 frases en español"}'
)


def _build_prompt(symbol, timeframe, sig, ctx) -> str:
    return (
        f"SEÑAL: {sig['side'].upper()} {symbol} | Estrategia: {sig['strategy']} | TF: {timeframe}\n"
        f"Entrada: {sig['price']} | SL: {sig['sl']:.6g} | TP: {sig['tp']:.6g} | R:R {abs(sig['tp']-sig['price'])/max(abs(sig['price']-sig['sl']),1e-12):.2f}\n"
        f"Confirmaciones ({sig['score']}): {'; '.join(sig['reasons'])}\n"
        f"Indicadores: {json.dumps(sig['indicators'])}\n"
        f"Tendencia TF superior ({ctx.get('htf_tf')}): {ctx.get('htf_trend')}\n"
        f"Cambio 24h: {ctx.get('change_24h', 0):.2f}% | Funding rate: {ctx.get('funding_rate', 0):.5f}\n"
        f"Últimos cierres (% cambio por vela, más reciente al final): {ctx.get('recent_changes')}\n"
        f"Cuenta: {ctx.get('open_positions')} posiciones abiertas, PnL diario {ctx.get('daily_pnl_pct', 0):.2f}%\n"
        "¿Ejecutar esta operación?"
    )


async def evaluate_signal(symbol: str, timeframe: str, sig: dict, ctx: dict) -> dict:
    text = await _ask(_chat(SYSTEM, "signal"), _build_prompt(symbol, timeframe, sig, ctx))
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError(f"Respuesta IA no válida: {text[:200]}")
    data = json.loads(match.group(0))
    decision = str(data.get("decision", "RECHAZAR")).upper()
    return {
        "decision": "APROBADA" if decision.startswith("APROB") else "RECHAZADA",
        "confidence": int(max(0, min(100, int(data.get("confidence", 0))))),
        "risk": str(data.get("risk", "MEDIO")).upper(),
        "reasoning": str(data.get("reasoning", ""))[:600],
    }


ADVISOR_SYSTEM = (
    "Eres el director de inversiones de un bot cuantitativo de futuros perpetuos USDT en modo paper trading. "
    "Recibes métricas reales y de backtest y debes DECIDIR cambios concretos de configuración para mejorar la expectativa "
    "y proteger el capital. Reglas estrictas: (1) los cambios estructurales (quitar pares, cambiar de estrategia, bajar o subir el riesgo, "
    "máximo de posiciones, apalancamiento) requieren evidencia REAL del bot: al menos 30 operaciones cerradas en rendimiento_real y ≥ 20 por par o "
    "estrategia afectada; el backtest por sí solo NO justifica esos cambios, solo recomendaciones en notes. (2) El backtest y el optimizador sí "
    "justifican aplicar symbol_params (SL/TP/ATR) cuando el óptimo robusto supera claramente a la línea base con ≥ 20 operaciones. "
    "(3) Nunca subas el riesgo por operación por encima de 1.5% ni el apalancamiento por encima de 5x; mantén al menos 2 pares activos. "
    "(4) Si no hay evidencia suficiente, changes debe ser {} y explica en notes qué esperar antes de cambiar. "
    "Responde EXCLUSIVAMENTE con un objeto JSON válido con este formato: "
    '{"summary":"2-4 frases en español explicando el diagnóstico","changes":{<claves opcionales: symbols (lista), strategy, risk_per_trade, '
    'max_positions, leverage, ai_min_confidence, trailing_enabled, htf_filter, symbol_params (dict símbolo→{sl_atr,tp_atr,atr_period})>},'
    '"notes":["recomendaciones adicionales en español que no son cambios de configuración"]}'
)


async def advise(scope: str, context: dict) -> dict:
    prompt = f"ÁMBITO: {scope}\nCONTEXTO (JSON):\n{json.dumps(context, ensure_ascii=False, default=str)}\n\nDecide los cambios de configuración."
    text = await _ask(_chat(ADVISOR_SYSTEM, "advisor"), prompt)
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError(f"Respuesta IA no válida: {text[:200]}")
    data = json.loads(match.group(0))
    changes = data.get("changes") or {}
    return {
        "summary": str(data.get("summary", ""))[:1200],
        "changes": changes if isinstance(changes, dict) else {},
        "notes": [str(n)[:300] for n in (data.get("notes") or [])][:6],
    }
