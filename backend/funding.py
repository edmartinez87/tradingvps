"""Funding-rate filter: avoid opening against extreme funding, size down when it is high, and explain it to Claude."""
INTERVAL_H = 8
LEVEL_TXT = {"NORMAL": "normal", "ALTO": "ALTO", "EXTREMO": "EXTREMO"}


def level(rate, cfg) -> str:
    if rate is None or cfg is None:
        return "NORMAL"
    mag = abs(rate) * 100
    return "EXTREMO" if mag >= cfg.funding_block_pct else "ALTO" if mag >= cfg.funding_reduce_pct else "NORMAL"


def assess(rate, side: str, cfg) -> dict | None:
    if rate is None:
        return None
    pct = rate * 100
    pays = "largos" if rate > 0 else "cortos" if rate < 0 else None
    against = (side == "long" and rate > 0) or (side == "short" and rate < 0)
    return {"rate_pct": round(pct, 4), "annualized_pct": round(pct * (24 / INTERVAL_H) * 365, 1), "level": level(rate, cfg),
            "pays": pays, "against": against, "interval_h": INTERVAL_H}


def gate(rate, side: str, cfg):
    """Returns (block_reason | None, size_factor) for a signal about to be executed."""
    if cfg is None or not cfg.funding_enabled:
        return None, 1.0
    a = assess(rate, side, cfg)
    if not a or not a["against"]:
        return None, 1.0
    if a["level"] == "EXTREMO":
        return f"funding extremo en contra ({a['rate_pct']:+.4f}%/{INTERVAL_H}h · {a['pays']} pagan)", 1.0
    if a["level"] == "ALTO" and cfg.funding_reduce:
        return None, cfg.funding_size_factor
    return None, 1.0


def prompt_line(a: dict | None) -> str:
    if not a:
        return "Funding rate: no disponible"
    if a["pays"] is None:
        return f"Funding rate: 0% ({INTERVAL_H}h) · neutro"
    stance = ("EN CONTRA de la señal: la posición pagaría funding y el lado está sobrecargado" if a["against"]
              else "A FAVOR de la señal: la posición cobraría funding")
    return (f"Funding rate: {a['rate_pct']:+.4f}%/{INTERVAL_H}h (≈ {a['annualized_pct']:+.1f}% anual) · nivel {LEVEL_TXT[a['level']]} · "
            f"{a['pays']} pagan → {stance}")
