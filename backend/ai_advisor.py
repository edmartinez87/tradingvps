import os
import re
import json
import uuid
import logging
from emergentintegrations.llm.chat import LlmChat, UserMessage, TextDelta, StreamDone
import funding

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
    "con volatilidad anormal o funding rate extremo en contra. Funding: si la señal va EN CONTRA del funding y el nivel es ALTO baja la confianza "
    "de forma clara (el lado está sobrecargado y la posición paga por mantenerse); si es EXTREMO en contra, rechaza salvo confluencia excepcional. "
    "Un funding A FAVOR es un pequeño punto positivo, nunca suficiente por sí solo para aprobar. "
    "El nivel del funding ya está normalizado a 8h: en pares que liquidan cada 4h o 1h el valor por periodo parece menor pero se cobra más veces. "
    "Si se incluye contexto de noticias, úsalo como factor de riesgo: "
    "una noticia grave sobre el par o un evento macro inminente justifican rechazar o bajar la confianza; un sentimiento favorable no basta por sí solo para aprobar. "
    "Aprueba solo setups con confluencia clara. "
    "Responde EXCLUSIVAMENTE con un objeto JSON válido, sin texto adicional, con este formato: "
    '{"decision":"APROBAR" o "RECHAZAR","confidence":entero 0-100,"risk":"BAJO"|"MEDIO"|"ALTO","reasoning":"máximo 3 frases en español"}'
)


def _news_lines(n) -> str:
    if not n:
        return ""
    m = n["mercado"]
    out = [f"Noticias (hace {n['actualizado_hace_min']} min): sentimiento mercado {m['sentiment']:+d} · riesgo {m['risk']} · {m['summary']}"]
    if n.get("par"):
        out.append(f"Noticias del par: sentimiento {n['par']['sentiment']:+d} · riesgo {n['par']['risk']} · {n['par']['note']}")
    if n.get("alertas"):
        out.append("Alertas: " + " | ".join(n["alertas"]))
    if n.get("eventos_proximos"):
        out.append("Eventos macro próximos: " + " | ".join(n["eventos_proximos"]))
    if n.get("titulares_del_par"):
        out.append("Titulares del par: " + " | ".join(n["titulares_del_par"]))
    return "\n".join(out) + "\n"


def _build_prompt(symbol, timeframe, sig, ctx) -> str:
    return (
        f"SEÑAL: {sig['side'].upper()} {symbol} | Estrategia: {sig['strategy']} | TF: {timeframe}\n"
        f"Entrada: {sig['price']} | SL: {sig['sl']:.6g} | TP: {sig['tp']:.6g} | R:R {abs(sig['tp']-sig['price'])/max(abs(sig['price']-sig['sl']),1e-12):.2f}\n"
        f"Confirmaciones ({sig['score']}): {'; '.join(sig['reasons'])}\n"
        f"Indicadores: {json.dumps(sig['indicators'])}\n"
        f"Tendencia TF superior ({ctx.get('htf_tf')}): {ctx.get('htf_trend')}\n"
        f"Cambio 24h: {ctx.get('change_24h', 0):.2f}% | {funding.prompt_line(ctx.get('funding'))}\n"
        f"Últimos cierres (% cambio por vela, más reciente al final): {ctx.get('recent_changes')}\n"
        f"Cuenta: {ctx.get('open_positions')} posiciones abiertas, PnL diario {ctx.get('daily_pnl_pct', 0):.2f}%\n"
        + _news_lines(ctx.get("news")) +
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


DEFAULT_POLICY = {"caps": {"risk_per_trade": 1.5, "leverage": 5, "max_positions": 5}, "min_trades": 30, "min_item_trades": 20, "level": 0, "name": "Conservador"}
STRATEGY_KEYS_TXT = "trend_ema, mean_reversion, breakout_turtle, supertrend_momentum, ema_pullback"
CRYPTO_MARKET = {"desc": "un bot cuantitativo de futuros perpetuos USDT en modo paper trading", "lev": lambda v: f"{v}x", "extra_rule": "", "extra_keys": ""}
FX_MARKET = {
    "desc": "un bot cuantitativo de forex y metales (cuenta HFM, lotes de 0.01, spread como único coste, horario forex con sesiones Sídney/Tokio/Londres/Nueva York) en modo paper trading",
    "lev": lambda v: f"1:{v}",
    "extra_rule": ("(6) sessions_allowed es la lista de sesiones en las que el bot puede ABRIR posiciones (ids válidos: sydney, tokyo, london, newyork; "
                   "lista vacía = todas). Solo restringe sesiones con evidencia: session_stats del backtest con ≥ 15 operaciones por sesión descartada "
                   "o rendimiento_real; Londres y Nueva York concentran la liquidez y suelen ser las mejores. "),
    "extra_keys": ", sessions_allowed (lista de ids)",
}


def advisor_system(policy: dict, market: dict = CRYPTO_MARKET) -> str:
    caps, lev = policy["caps"], market["lev"]
    return (
        f"Eres el director de inversiones de {market['desc']}. "
        "Recibes métricas reales y de backtest y debes DECIDIR cambios concretos de configuración para mejorar la expectativa "
        f"y proteger el capital. El usuario eligió el perfil de riesgo '{policy['name']}' (nivel {policy['level']} de 4): respeta ese nivel de actividad, "
        "no lo vuelvas más conservador ni más agresivo de lo que el usuario pidió; tu trabajo es podar lo que pierde y reforzar lo que gana dentro de ese perfil. "
        f"Reglas estrictas: (1) los cambios estructurales (quitar pares, apagar estrategias, bajar o subir el riesgo, máximo de posiciones, apalancamiento) "
        f"requieren evidencia REAL del bot: al menos {policy['min_trades']} operaciones cerradas en rendimiento_real y ≥ {policy['min_item_trades']} por par o "
        "estrategia afectada; el backtest por sí solo NO justifica esos cambios, solo recomendaciones en notes. (2) El backtest y el optimizador sí "
        "justifican aplicar symbol_params (SL/TP/ATR) cuando el óptimo robusto supera claramente a la línea base con ≥ 20 operaciones Y la validación "
        "walk_forward del par (si existe) es ROBUSTO o DUDOSO; si es SOBREAJUSTADO o NO_RENTABLE no apliques symbol_params en ese par. "
        "symbol_params es el diccionario COMPLETO que debe quedar activo (omite un par para devolverlo a los valores por defecto). "
        f"(3) Nunca subas el riesgo por operación por encima de {caps['risk_per_trade']}% ni el apalancamiento por encima de {lev(caps['leverage'])} ni el máximo de "
        f"posiciones por encima de {caps['max_positions']}; mantén al menos 2 pares activos y al menos 1 estrategia activa. "
        f"(4) Para apagar una estrategia usa disabled_strategies (lista completa de claves apagadas; claves válidas: {STRATEGY_KEYS_TXT}) y deja strategy en 'all'. "
        "(5) Si no hay evidencia suficiente, changes debe ser {} y explica en notes qué esperar antes de cambiar. "
        + market["extra_rule"] +
        "Redacta summary y notes para el usuario final: frases completas y breves (máximo 2 por nota), en español claro y sin claves internas "
        "(di «SL/TP optimizados» en vez de symbol_params, «sesiones permitidas» en vez de sessions_allowed, «sobreajustado» en vez de SOBREAJUSTADO). "
        "Responde EXCLUSIVAMENTE con un objeto JSON válido con este formato: "
        '{"summary":"2-4 frases en español explicando el diagnóstico","changes":{<claves opcionales: symbols (lista), disabled_strategies (lista), risk_per_trade, '
        f'max_positions, leverage, ai_min_confidence, trailing_enabled, htf_filter, symbol_params (dict símbolo→{{sl_atr,tp_atr,atr_period}}){market["extra_keys"]}>}},'
        '"notes":["recomendaciones adicionales en español que no son cambios de configuración"]}'
    )


def _clip(text: str, limit: int) -> str:
    text = str(text)
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:.") + "…"


async def advise(scope: str, context: dict, policy: dict = None, market: dict = CRYPTO_MARKET) -> dict:
    prompt = f"ÁMBITO: {scope}\nCONTEXTO (JSON):\n{json.dumps(context, ensure_ascii=False, default=str)}\n\nDecide los cambios de configuración."
    text = await _ask(_chat(advisor_system(policy or DEFAULT_POLICY, market), "advisor"), prompt)
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError(f"Respuesta IA no válida: {text[:200]}")
    data = json.loads(match.group(0))
    changes = data.get("changes") or {}
    return {
        "summary": _clip(data.get("summary", ""), 1200),
        "changes": changes if isinstance(changes, dict) else {},
        "notes": [_clip(n, 420) for n in (data.get("notes") or [])][:6],
    }
