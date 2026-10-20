"""Funding-rate filter: avoid opening against extreme funding, size down when it is high, and explain it to Claude.
Thresholds are expressed per 8h; pairs that settle every 4h/1h are normalized to the 8h equivalent."""
INTERVAL_H = 8
LEVEL_TXT = {"NORMAL": "normal", "ALTO": "ALTO", "EXTREMO": "EXTREMO"}


def _hours(interval_h) -> float:
    return interval_h if interval_h and interval_h > 0 else INTERVAL_H


def per_8h(rate, interval_h=INTERVAL_H):
    return rate * INTERVAL_H / _hours(interval_h)


def level(rate, cfg, interval_h=INTERVAL_H) -> str:
    if rate is None or cfg is None:
        return "NORMAL"
    mag = abs(per_8h(rate, interval_h)) * 100
    return "EXTREMO" if mag >= cfg.funding_block_pct else "ALTO" if mag >= cfg.funding_reduce_pct else "NORMAL"


def assess(rate, side: str, cfg, interval_h=INTERVAL_H) -> dict | None:
    if rate is None:
        return None
    h = _hours(interval_h)
    pct = rate * 100
    pays = "largos" if rate > 0 else "cortos" if rate < 0 else None
    against = (side == "long" and rate > 0) or (side == "short" and rate < 0)
    return {"rate_pct": round(pct, 4), "rate_8h_pct": round(per_8h(rate, h) * 100, 4), "annualized_pct": round(pct * (24 / h) * 365, 1),
            "level": level(rate, cfg, h), "pays": pays, "against": against, "interval_h": int(h) if float(h).is_integer() else h}


def fmt_rate(a: dict) -> str:
    s = f"{a['rate_pct']:+.4f}%/{a['interval_h']}h"
    return s if a["interval_h"] == INTERVAL_H else f"{s} ≈ {a['rate_8h_pct']:+.4f}%/8h"


def gate(rate, side: str, cfg, interval_h=INTERVAL_H):
    """Returns (block_reason | None, size_factor) for a signal about to be executed."""
    if cfg is None or not cfg.funding_enabled:
        return None, 1.0
    a = assess(rate, side, cfg, interval_h)
    if not a or not a["against"]:
        return None, 1.0
    if a["level"] == "EXTREMO":
        return f"funding extremo en contra ({fmt_rate(a)} · {a['pays']} pagan)", 1.0
    if a["level"] == "ALTO" and cfg.funding_reduce:
        return None, cfg.funding_size_factor
    return None, 1.0


def prompt_line(a: dict | None) -> str:
    if not a:
        return "Funding rate: no disponible"
    if a["pays"] is None:
        return f"Funding rate: 0% ({a['interval_h']}h) · neutro"
    stance = ("EN CONTRA de la señal: la posición pagaría funding y el lado está sobrecargado" if a["against"]
              else "A FAVOR de la señal: la posición cobraría funding")
    cycle = "" if a["interval_h"] == INTERVAL_H else f" · se liquida cada {a['interval_h']}h"
    return (f"Funding rate: {fmt_rate(a)} (≈ {a['annualized_pct']:+.1f}% anual{cycle}) · nivel {LEVEL_TXT[a['level']]} · "
            f"{a['pays']} pagan → {stance}")
