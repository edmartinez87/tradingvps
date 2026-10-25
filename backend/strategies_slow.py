"""Long-horizon strategies for the crypto bot, evaluated on their own timeframe (daily / 4h) whatever the chart timeframe is.
Evidence: Concretum «Catching Crypto Trends» (2015-2025, Donchian ensemble 5→360 d: BTC Sharpe 1.58, drawdown 80 % → 19 %) and the
double RSI+MACD divergence on 4h with a 200-period trend filter (75 % hit rate, PF 2.14, few signals)."""
from typing import Optional
import numpy as np
from strategies import _signal, _atr_levels

HORIZONS = (20, 55, 100, 200)
MIN_AGREE = 3
PIVOT_K = 3
SLOW_INFO = {
    "multi_horizon": {
        "name": "Tendencia Multi-Horizonte", "tf": "1d", "horizon": "long", "bars": 320,
        "rules": "Diario: cuatro canales Donchian (20/55/100/200 días) votan largo/corto; entra cuando al menos 3 de 4 giran a favor y el precio "
                 "está del mismo lado de la SMA200 diaria. SL 2,5×ATR(1d), TP 6×ATR + trailing; tamaño por volatilidad (riesgo fijo sobre la distancia al SL). "
                 "Operación de largo plazo: no cuenta en «Máx. posiciones», tiene su propio tope.",
        "basis": "Concretum «Catching Crypto Trends» (2015-2025): el conjunto multi-horizonte con tamaño por volatilidad dio CAGR 30 %, Sharpe 1,58 y "
                 "drawdown 80 % → 19 % en BTC; un solo horizonte es frágil, el conjunto no.",
    },
    "double_divergence": {
        "name": "Divergencia Doble RSI+MACD", "tf": "4h", "horizon": "long", "bars": 400,
        "rules": "4h: dos mínimos (máximos) pivote con precio más bajo (alto) pero RSI e histograma MACD más altos (bajos), vela de giro a favor y precio "
                 "sobre (bajo) la EMA200. SL bajo el pivote (1-4×ATR), TP a 2R. Pocas señales al año; operación de largo plazo.",
        "basis": "La divergencia RSI sola no bate al mercado (8 pares, 2017-2025); la doble RSI+MACD en 4h con filtro de tendencia dio 75 % de acierto y PF 2,14 en BTC/USDT.",
    },
}
SLOW_KEYS = list(SLOW_INFO)


def _don_states(df, n: int) -> np.ndarray:
    """+1 after a close above the previous n-bar high, -1 below the previous n-bar low, otherwise the previous state is kept."""
    hi = df["high"].rolling(n).max().shift(1).values
    lo = df["low"].rolling(n).min().shift(1).values
    c = df["close"].values
    st = np.zeros(len(df))
    for i in range(1, len(df)):
        if np.isnan(hi[i]):
            continue
        st[i] = 1 if c[i] > hi[i] else -1 if c[i] < lo[i] else st[i - 1]
    return st


def ensemble_votes(df):
    """(longs, shorts): number of Donchian horizons currently long / short at each bar."""
    states = np.array([_don_states(df, n) for n in HORIZONS])
    return (states == 1).sum(axis=0), (states == -1).sum(axis=0)


def multi_horizon(df, i: int, params=None) -> Optional[dict]:
    if i < 205 or i >= len(df):
        return None
    longs, shorts = ensemble_votes(df)
    r = df.iloc[i]
    sma200 = float(df["close"].rolling(200).mean().iloc[i])
    if np.isnan(sma200):
        return None
    if longs[i] >= MIN_AGREE and longs[i - 1] < MIN_AGREE and r["close"] > sma200:
        side, agree = "long", int(longs[i])
    elif shorts[i] >= MIN_AGREE and shorts[i - 1] < MIN_AGREE and r["close"] < sma200:
        side, agree = "short", int(shorts[i])
    else:
        return None
    long = side == "long"
    sl, tp = _atr_levels(r, long, params, 2.5, 6.0)
    reasons = [f"{agree} de {len(HORIZONS)} horizontes Donchian (20/55/100/200 d) en {'largo' if long else 'corto'}",
               f"Precio {'sobre' if long else 'bajo'} la SMA200 diaria ({sma200:.6g})",
               f"ATR diario {r['atr']:.4g}: tamaño ajustado a la volatilidad"]
    score = 4 + (agree - MIN_AGREE) + (1 if r["adx"] > 20 else 0)
    if r["adx"] > 20:
        reasons.append(f"ADX diario {r['adx']:.1f}")
    return _signal(side, r, sl, tp, "multi_horizon", reasons, score, r["ts"])


def _pivots(vals: np.ndarray, upto: int, k: int, low: bool) -> list:
    """Indexes j ≤ upto-k whose value is the extreme of the window [j-k, j+k] (confirmed k bars later)."""
    out = []
    for j in range(max(k, upto - 80), upto - k + 1):
        w = vals[j - k:j + k + 1]
        if (low and vals[j] <= w.min()) or (not low and vals[j] >= w.max()):
            out.append(j)
    return out


def double_divergence(df, i: int, params=None) -> Optional[dict]:
    if i < 210 or i >= len(df):
        return None
    r = df.iloc[i]
    lows, highs = df["low"].values, df["high"].values
    rsi, hist = df["rsi"].values, df["macd_hist"].values
    atr = float(r["atr"])
    for long in (True, False):
        piv = _pivots(lows if long else highs, i, PIVOT_K, low=long)
        if len(piv) < 2 or piv[-1] != i - PIVOT_K:
            continue
        p2 = piv[-1]
        older = [p for p in piv[:-1] if p2 - p >= 5]
        if not older:
            continue
        p1 = older[-1]
        if long:
            ok = (lows[p2] < lows[p1] and rsi[p2] > rsi[p1] + 1 and hist[p2] > hist[p1] and rsi[p2] < 45
                  and r["close"] > r["open"] and r["close"] > r["ema200"])
        else:
            ok = (highs[p2] > highs[p1] and rsi[p2] < rsi[p1] - 1 and hist[p2] < hist[p1] and rsi[p2] > 55
                  and r["close"] < r["open"] and r["close"] < r["ema200"])
        if not ok:
            continue
        close = float(r["close"])
        sl = min(lows[p2] - 0.2 * atr, close - atr) if long else max(highs[p2] + 0.2 * atr, close + atr)
        dist = abs(close - sl)
        if dist > 4 * atr or dist <= 0:
            return None
        tp = close + 2 * dist if long else close - 2 * dist
        reasons = [f"Divergencia {'alcista' if long else 'bajista'} doble: precio {'más bajo' if long else 'más alto'} con RSI {rsi[p1]:.0f}→{rsi[p2]:.0f} e histograma MACD a favor",
                   f"Pivotes confirmados hace {i - p2} y {i - p1} velas de 4h",
                   f"Vela de giro {'alcista' if long else 'bajista'} y precio {'sobre' if long else 'bajo'} la EMA200",
                   f"SL {'bajo' if long else 'sobre'} el pivote ({dist / atr:.1f}×ATR) · TP a 2R"]
        return _signal("long" if long else "short", r, sl, tp, "double_divergence", reasons, 5, int(df["ts"].iloc[p2]), tp_mode="fixed")
    return None


SLOW_STRATEGIES = {"multi_horizon": multi_horizon, "double_divergence": double_divergence}


def evaluate_slow(df, i: int, key: str, params=None) -> Optional[dict]:
    return SLOW_STRATEGIES[key](df, i, params)


def scan_slow(df, key: str, params=None) -> dict:
    out, used = {}, set()
    for i in range(210, len(df)):
        sig = SLOW_STRATEGIES[key](df, i, params)
        if sig and sig["key_ts"] not in used:
            used.add(sig["key_ts"])
            out[i] = sig
    return out
