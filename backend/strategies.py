from typing import Optional
from indicators import snapshot

STRATEGY_INFO = {
    "trend_ema": {
        "name": "Tendencia Multi-Confirmación",
        "rules": "Cruce EMA9/EMA21 a favor de EMA200 + RSI 50-70 (long) / 30-50 (short) + MACD + ADX/Volumen. SL 1.5×ATR, TP 3×ATR (R:R 1:2).",
        "basis": "Trend following clásico (Dennis, Seykota): cortar pérdidas rápido y dejar correr ganancias con filtro de tendencia mayor.",
    },
    "mean_reversion": {
        "name": "Reversión a la Media",
        "rules": "Cierre fuera de Bandas de Bollinger(20,2) que regresa al interior + RSI extremo + ADX<25 (mercado lateral). TP en banda media, SL 1.5×ATR.",
        "basis": "Bollinger + RSI en rangos: alta tasa de acierto cuando no hay tendencia fuerte.",
    },
    "breakout_turtle": {
        "name": "Ruptura Turtle (Donchian 20)",
        "rules": "Ruptura del máximo/mínimo de 20 velas con volumen ≥1.5× y ADX>20 a favor de EMA50. SL 2×ATR (N), TP 4×ATR.",
        "basis": "Sistema de las Tortugas de Richard Dennis (1983), uno de los casos de éxito más documentados del trading sistemático.",
    },
}


def _signal(side, row, sl, tp, strategy, reasons, score, key_ts, tp_mode="atr"):
    return {
        "side": side, "strategy": strategy, "price": float(row["close"]), "sl": float(sl), "tp": float(tp),
        "atr": float(row["atr"]), "score": score, "reasons": reasons, "key_ts": int(key_ts), "tp_mode": tp_mode,
        "indicators": snapshot(row),
    }


def _k(params, key, default):
    return float((params or {}).get(key) or default)


def trend_ema(df, i, htf=None, params=None) -> Optional[dict]:
    r = df.iloc[i]
    cross = None
    for j in range(i, i - 3, -1):
        a, b = df.iloc[j], df.iloc[j - 1]
        if a["ema9"] > a["ema21"] and b["ema9"] <= b["ema21"]:
            cross = ("long", int(a["ts"]))
            break
        if a["ema9"] < a["ema21"] and b["ema9"] >= b["ema21"]:
            cross = ("short", int(a["ts"]))
            break
    if not cross:
        return None
    side, key_ts = cross
    long = side == "long"
    aligned = r["ema9"] > r["ema21"] if long else r["ema9"] < r["ema21"]
    trend_ok = r["close"] > r["ema200"] if long else r["close"] < r["ema200"]
    rsi_ok = 50 < r["rsi"] < 70 if long else 30 < r["rsi"] < 50
    macd_ok = r["macd_hist"] > 0 if long else r["macd_hist"] < 0
    if not (aligned and trend_ok and rsi_ok and macd_ok):
        return None
    if htf is not None and htf == (-1 if long else 1):
        return None
    reasons = [
        f"Cruce {'alcista' if long else 'bajista'} EMA9/EMA21",
        f"Precio {'sobre' if long else 'bajo'} EMA200",
        f"RSI {r['rsi']:.1f} en zona de momentum",
        f"MACD histograma {'positivo' if long else 'negativo'}",
    ]
    score = 4
    if r["adx"] > 20:
        score += 1
        reasons.append(f"ADX {r['adx']:.1f} (tendencia con fuerza)")
    if r["vol_ratio"] >= 1.0:
        score += 1
        reasons.append(f"Volumen {r['vol_ratio']:.2f}× el promedio")
    if htf is not None and htf == (1 if long else -1):
        score += 1
        reasons.append("Temporalidad superior a favor")
    if score < 5:
        return None
    atr = r["atr"]
    sl_k, tp_k = _k(params, "sl_atr", 1.5), _k(params, "tp_atr", 3.0)
    sl = r["close"] - sl_k * atr if long else r["close"] + sl_k * atr
    tp = r["close"] + tp_k * atr if long else r["close"] - tp_k * atr
    return _signal(side, r, sl, tp, "trend_ema", reasons, score, key_ts)


def mean_reversion(df, i, htf=None, params=None) -> Optional[dict]:
    r, p = df.iloc[i], df.iloc[i - 1]
    if r["adx"] >= 25:
        return None
    atr = r["atr"]
    sl_k = _k(params, "sl_atr", 1.5)
    if p["close"] < p["bb_low"] and r["close"] > r["bb_low"] and p["rsi"] < 35:
        side, sl, tp = "long", r["close"] - sl_k * atr, r["bb_mid"]
    elif p["close"] > p["bb_up"] and r["close"] < r["bb_up"] and p["rsi"] > 65:
        side, sl, tp = "short", r["close"] + sl_k * atr, r["bb_mid"]
    else:
        return None
    if abs(tp - r["close"]) < abs(r["close"] - sl):
        return None
    long = side == "long"
    reasons = [
        f"Reingreso a Bollinger desde banda {'inferior' if long else 'superior'}",
        f"RSI previo {p['rsi']:.1f} en {'sobreventa' if long else 'sobrecompra'}",
        f"ADX {r['adx']:.1f}: mercado lateral",
        "Objetivo en la media de 20 periodos",
    ]
    score = 4 + (1 if r["vol_ratio"] >= 1.0 else 0)
    return _signal(side, r, sl, tp, "mean_reversion", reasons, score, r["ts"], tp_mode="fixed")


def breakout_turtle(df, i, htf=None, params=None) -> Optional[dict]:
    r, p = df.iloc[i], df.iloc[i - 1]
    if r["vol_ratio"] < 1.5 or r["adx"] <= 20:
        return None
    if r["close"] > r["don_high"] and p["close"] <= p["don_high"] and r["close"] > r["ema50"]:
        side = "long"
    elif r["close"] < r["don_low"] and p["close"] >= p["don_low"] and r["close"] < r["ema50"]:
        side = "short"
    else:
        return None
    long = side == "long"
    if htf is not None and htf == (-1 if long else 1):
        return None
    atr = r["atr"]
    sl_k, tp_k = _k(params, "sl_atr", 2.0), _k(params, "tp_atr", 4.0)
    sl = r["close"] - sl_k * atr if long else r["close"] + sl_k * atr
    tp = r["close"] + tp_k * atr if long else r["close"] - tp_k * atr
    reasons = [
        f"Ruptura del {'máximo' if long else 'mínimo'} de 20 velas (Donchian)",
        f"Volumen {r['vol_ratio']:.2f}× el promedio",
        f"ADX {r['adx']:.1f}",
        f"Precio {'sobre' if long else 'bajo'} EMA50",
    ]
    score = 5 + (1 if htf == (1 if long else -1) else 0)
    return _signal(side, r, sl, tp, "breakout_turtle", reasons, score, r["ts"])


STRATEGIES = {"trend_ema": trend_ema, "mean_reversion": mean_reversion, "breakout_turtle": breakout_turtle}


def evaluate(df, i, strategy: str, htf=None, params=None) -> Optional[dict]:
    keys = list(STRATEGIES) if strategy == "all" else [strategy]
    for k in keys:
        sig = STRATEGIES[k](df, i, htf, params)
        if sig:
            return sig
    return None
