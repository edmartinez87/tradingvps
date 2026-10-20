"""Iteration 16 – HotForex backtest / optimizer / walk-forward (lots, spread, weekend flat, sessions) + 5-level FX risk profiles."""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
FX = f"{BASE_URL}/api/fx"
ALL = ["XAUUSD", "XAGUSD", "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD", "EURJPY", "GBPJPY", "EURCHF"]
BT_KEYS = ("return_pct", "total_trades", "rejected_lot", "weekend_closed", "win_rate", "profit_factor", "max_drawdown", "expectancy_r", "sqn",
           "total_pips", "avg_pips", "session_stats", "strategy_stats", "equity_curve", "trades", "spread_pips", "period_start", "period_end")


@pytest.fixture(scope="module")
def s():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": "BlackCat2233@"}, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"login failed {r.status_code}")
    sess = requests.Session()
    sess.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return sess


def post(s, url, body, timeout=180):
    for _ in range(3):
        r = s.post(url, json=body, timeout=timeout)
        if r.status_code != 424 or "429" not in r.text:
            return r
        time.sleep(5)
    return r


# ---------- unit: fx backtest kit ----------
def test_unit_simulate_contract_and_weekend():
    import sys
    sys.path.insert(0, "/app/backend")
    import numpy as np
    from fx.backtest import simulate, build_fx_df
    # synthetic 1h klines across two weeks with a weekend gap (Fri 21:00 → Sun 22:00 UTC)
    ts0 = 1_726_000_000_000  # 2024-09-10 ~20:26 UTC (Tuesday)
    rows, t, price = [], ts0 - ts0 % 3_600_000, 1.1000
    while len(rows) < 400:
        from datetime import datetime, timezone
        d = datetime.fromtimestamp(t / 1000, tz=timezone.utc)
        if not (d.weekday() == 5 or (d.weekday() == 4 and d.hour >= 21) or (d.weekday() == 6 and d.hour < 22)):
            price += 0.0003 * np.sin(len(rows) / 7)
            rows.append([t, price, price + 0.0005, price - 0.0005, price + 0.0001, 0])
        t += 3_600_000
    df = build_fx_df(rows)
    assert (df["vol_ratio"] == 1.5).all()  # Yahoo forex has no volume → neutral ratio
    sig = {"side": "long", "strategy": "trend_ema", "price": float(df["close"].iloc[250]), "atr": 0.0010, "key_ts": int(df["ts"].iloc[250])}
    sig["sl"], sig["tp"] = sig["price"] - 0.0015, sig["price"] + 0.0030
    res = simulate(df, {250: sig}, 1.0, 100, False, 500.0, "EURUSD", tickers={}, min_lot_max_risk=4.0, weekend_flat=True)
    for k in BT_KEYS:
        if k != "spread_pips":
            assert k in res, k
    assert res["total_trades"] == 1
    tr = res["trades"][0]
    assert tr["lots"] >= 0.01 and "pips" in tr and "session" in tr
    assert tr["reason"] in ("SL", "TP", "FIN_SEMANA")
    # the spread is charged on both legs → fees > 0 even on a flat exit
    assert abs(tr["pnl"] - tr["pips"] * tr["lots"] * 10) < 1.5  # 1 pip of 1 lot EURUSD = $10, minus spread


def test_unit_min_lot_rejection_counts():
    import sys
    sys.path.insert(0, "/app/backend")
    from fx.backtest import simulate, build_fx_df
    rows = [[1_726_000_000_000 + i * 3_600_000, 4000 + i * 0.1, 4001 + i * 0.1, 3999 + i * 0.1, 4000.5 + i * 0.1, 0] for i in range(300)]
    df = build_fx_df(rows)
    sig = {"side": "long", "strategy": "trend_ema", "price": 4025.0, "sl": 4025.0 - 30, "tp": 4025.0 + 60, "atr": 20.0, "key_ts": int(df["ts"].iloc[250])}
    # $500 · 1% → 0.0017 lots on gold; min lot risks $30 = 6% > cap 4% → rejected
    res = simulate(df, {250: sig}, 1.0, 100, False, 500.0, "XAUUSD", tickers={}, min_lot_max_risk=4.0, weekend_flat=False)
    assert res["total_trades"] == 0 and res["rejected_lot"] == 1
    res = simulate(df, {250: sig}, 1.0, 100, False, 500.0, "XAUUSD", tickers={}, min_lot_max_risk=8.0, weekend_flat=False, end=290)
    assert res["total_trades"] == 1 and res["trades"][0]["lots"] == 0.01 and res["trades"][0]["reason"] == "FIN"


def test_unit_profiles_consistency():
    import sys
    sys.path.insert(0, "/app/backend")
    from fx.profiles import PROFILES, detect_profile, profile_patch
    from fx.models import FxSettings, FxSettingsUpdate
    assert [p["level"] for p in PROFILES] == [0, 1, 2, 3, 4]
    assert detect_profile(FxSettings()) == 2, "default FX settings must equal level 2 (Activo)"
    for p in PROFILES:
        st = FxSettings.model_validate({**FxSettings().model_dump(), **profile_patch(p["level"])})
        assert detect_profile(st) == p["level"]
        FxSettingsUpdate(**{k: v for k, v in p["settings"].items() if k in FxSettingsUpdate.model_fields})  # within API limits
        assert set(p["settings"]["symbols"]) <= set(ALL)
    risks = [p["settings"]["risk_per_trade"] for p in PROFILES]
    assert risks == sorted(risks) and risks[0] < risks[-1]


# ---------- API ----------
def test_meta_has_profiles(s):
    d = s.get(f"{FX}/meta", timeout=30).json()
    assert d["profiles"] and len(d["profiles"]) == 5
    assert [p["name"] for p in d["profiles"]] == ["Conservador", "Moderado", "Activo", "Agresivo", "Máximo"]


def test_profile_apply_and_detect(s):
    orig = s.get(f"{FX}/settings", timeout=30).json()
    try:
        r = post(s, f"{FX}/profile", {"level": 0}, 60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["profile_active"] == 0 and d["settings"]["risk_per_trade"] == 0.5 and d["settings"]["max_positions"] == 2
        assert len(d["settings"]["symbols"]) == 6 and d["settings"]["risk_profile"] == 0
        assert s.get(f"{FX}/dashboard", timeout=60).json()["profile_active"] == 0
        # manual tweak → Personalizado
        s.put(f"{FX}/settings", json={"risk_per_trade": 0.7}, timeout=30)
        assert s.get(f"{FX}/dashboard", timeout=60).json()["profile_active"] is None
        r = post(s, f"{FX}/profile", {"level": 4}, 60)
        assert r.status_code == 200 and r.json()["profile_active"] == 4
        assert r.json()["settings"]["ai_enabled"] is False and r.json()["settings"]["leverage"] == 500 and r.json()["settings"]["timeframe"] == "15m"
        assert post(s, f"{FX}/profile", {"level": 5}, 30).status_code == 422
        assert post(s, f"{FX}/profile", {"level": -1}, 30).status_code == 422
    finally:
        post(s, f"{FX}/profile", {"level": 2}, 60)
        keys = ("symbols", "timeframe", "signal_mode", "htf_filter", "ai_enabled", "ai_min_confidence", "risk_per_trade", "max_positions",
                "leverage", "daily_loss_limit", "disabled_strategies", "min_lot_max_risk", "close_before_weekend")
        s.put(f"{FX}/settings", json={k: orig[k] for k in keys}, timeout=30)
    assert s.get(f"{FX}/settings", timeout=30).json()["risk_per_trade"] == orig["risk_per_trade"]


@pytest.mark.parametrize("symbol,tf", [("EURUSD", "1h"), ("XAUUSD", "1h"), ("USDJPY", "15m"), ("GBPJPY", "4h")])
def test_backtest(s, symbol, tf):
    r = post(s, f"{FX}/backtest", {"symbol": symbol, "strategy": "all", "timeframe": tf, "risk_per_trade": 1.0, "leverage": 100})
    assert r.status_code == 200, r.text[:300]
    d = r.json()
    for k in BT_KEYS:
        assert k in d, k
    assert "r_multiples" not in d
    assert d["symbol"] == symbol and d["timeframe"] == tf and d["candles"] > 300
    assert d["spread_pips"] > 0
    print(symbol, tf, {k: d[k] for k in ("total_trades", "rejected_lot", "weekend_closed", "return_pct", "total_pips")}, list(d["session_stats"])[:3])
    if d["total_trades"]:
        assert sum(x["trades"] for x in d["session_stats"].values()) == d["total_trades"]
        assert abs(sum(x["pips"] for x in d["session_stats"].values()) - d["total_pips"]) < 0.5
        t = d["trades"][0]
        for k in ("lots", "pips", "session", "reason", "entry", "exit", "pnl", "r"):
            assert k in t, k
        assert t["lots"] >= 0.01
        assert all(x["reason"] in ("SL", "TP", "TRAILING", "FIN_SEMANA", "FIN") for x in d["trades"])


def test_backtest_validation(s):
    assert post(s, f"{FX}/backtest", {"symbol": "BTCUSDT", "timeframe": "1h"}, 30).status_code == 400
    assert post(s, f"{FX}/backtest", {"symbol": "EURUSD", "timeframe": "1m"}, 30).status_code == 400
    assert post(s, f"{FX}/backtest", {"symbol": "EURUSD", "strategy": "nope"}, 30).status_code == 400
    assert post(s, f"{FX}/backtest", {"symbol": "EURUSD", "leverage": 501}, 30).status_code == 422
    assert post(s, f"{FX}/backtest", {"symbol": "EURUSD", "leverage": 500}, 120).status_code == 200


def test_optimize_and_apply(s):
    r = post(s, f"{FX}/optimize", {"symbol": "EURUSD"})
    assert r.status_code == 200, r.text[:300]
    d = r.json()
    assert d["combos"] == 54 and len(d["grid"]) == 54 and d["symbol"] == "EURUSD" and d["timeframe"]
    assert d["sl_grid"] == [1.0, 1.5, 2.0, 2.5, 3.0] and d["atr_grid"] == [10, 14, 20]
    for k in ("return_pct", "trades", "win_rate", "profit_factor", "max_drawdown", "expectancy_r", "sqn", "rejected_lot"):
        assert k in d["baseline"], k
    row = d["grid"][0]
    for k in ("atr_period", "sl_atr", "tp_atr", "robust", "neighbors", "trades"):
        assert k in row, k
    print("best", d["best"], "baseline", d["baseline"])
    if d["best"]:
        params = {"sl_atr": d["best"]["sl_atr"], "tp_atr": d["best"]["tp_atr"], "atr_period": d["best"]["atr_period"]}
        orig = s.get(f"{FX}/settings", timeout=30).json()["symbol_params"]
        try:
            r = s.put(f"{FX}/settings", json={"symbol_params": {**orig, "EURUSD": params}}, timeout=30)
            assert r.status_code == 200 and r.json()["symbol_params"]["EURUSD"] == params
            assert post(s, f"{FX}/optimize", {"symbol": "EURUSD"}).json()["applied"] == params
        finally:
            s.put(f"{FX}/settings", json={"symbol_params": orig}, timeout=30)
    assert post(s, f"{FX}/optimize", {"symbol": "BTCUSDT"}, 30).status_code == 400


def test_walk_forward(s):
    r = post(s, f"{FX}/optimize/walk-forward", {"symbol": "EURUSD"}, 300)
    assert r.status_code == 200, r.text[:300]
    d = r.json()
    for k in ("folds", "oos", "baseline_oos", "verdict", "verdict_text", "oos_curve", "baseline_curve", "is_len", "oos_len", "params_unique", "params_stable", "timeframe"):
        assert k in d, k
    assert d["verdict"] in ("ROBUSTO", "DUDOSO", "SOBREAJUSTADO", "NO_RENTABLE", "INSUFICIENTE")
    assert d["candles"] >= 1500 and d["oos_len"] == 250 and len(d["folds"]) >= 2
    f = d["folds"][0]
    for k in ("fold", "is_start", "split", "oos_end", "is_candles", "oos_candles", "oos", "baseline_oos"):
        assert k in f, k
    assert d["applied"] is None and d["applied_params"] is None
    print("wf", d["verdict"], d["oos"], "folds", len(d["folds"]))
    assert post(s, f"{FX}/optimize/walk-forward", {"symbol": "NOPE"}, 30).status_code == 400


def test_walk_forward_with_applied_params(s):
    orig = s.get(f"{FX}/settings", timeout=30).json()["symbol_params"]
    params = {"sl_atr": 2.0, "tp_atr": 4.0, "atr_period": 14}
    try:
        s.put(f"{FX}/settings", json={"symbol_params": {**orig, "GBPUSD": params}}, timeout=30)
        d = post(s, f"{FX}/optimize/walk-forward", {"symbol": "GBPUSD"}, 300).json()
        assert d["applied_params"] == params and d["applied"] is not None
        for k in ("params", "oos", "is_expectancy_r", "wfe", "verdict", "verdict_text", "curve", "beats_baseline"):
            assert k in d["applied"], k
        assert d["applied"]["params"] == params
    finally:
        s.put(f"{FX}/settings", json={"symbol_params": orig}, timeout=30)


def test_crypto_optimizer_untouched(s):
    r = post(s, f"{BASE_URL}/api/optimize", {"symbol": "BTCUSDT"}, 240)
    assert r.status_code == 200, r.text[:200]
    assert r.json()["combos"] == 54 and "weekend_closed" not in r.json()["baseline"]
    d = s.get(f"{BASE_URL}/api/dashboard", timeout=60).json()
    assert any(x["symbol"].endswith("USDT") for x in d["watchlist"])
