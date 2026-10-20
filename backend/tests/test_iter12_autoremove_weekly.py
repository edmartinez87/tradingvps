# Iteration 12: walk-forward auto-remove of overfit SL/TP (API + unit), weekly Telegram summary (preview/send/cron),
# crons.yml/deploy artifacts. Run with: pytest -n 0
import os
import sys
import time
import asyncio
import subprocess
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import pytest
import requests
import yaml
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, "/app/backend")
load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
PASSWORD = "BlackCat2233@"
SECRET = os.environ.get("WEBHOOK_CRON_SECRET")
PARAMS = {"BTCUSDT": {"sl_atr": 3, "tp_atr": 6, "atr_period": 10}, "ETHUSDT": {"sl_atr": 2.5, "tp_atr": 5, "atr_period": 14}}
BAD = ("SOBREAJUSTADO", "NO_RENTABLE")


def _db_run(coro_fn):
    async def go():
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        try:
            return await coro_fn(c[os.environ["DB_NAME"]])
        finally:
            c.close()
    return asyncio.run(go())


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"password": PASSWORD}, timeout=20)
    if r.status_code != 200:
        pytest.skip(f"login failed {r.status_code}")
    s.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return s


def wait_done(client, timeout=90):
    t = time.time()
    while time.time() - t < timeout:
        d = client.get(f"{BASE_URL}/api/walk-forward/check", timeout=20).json()
        if d["job"]["status"] != "running":
            return d
        time.sleep(1.5)
    raise AssertionError("walk-forward check did not finish")


def fl(d):
    return {k: float(v) for k, v in d.items()}


# ---------- API: auto-remove on / off ----------
class TestAutoRemoveAPI:
    def test_01_auto_remove_on(self, client):
        wait_done(client)
        r = client.put(f"{BASE_URL}/api/config", json={"wf_auto_remove": True}, timeout=20)
        assert r.status_code == 200 and r.json()["wf_auto_remove"] is True
        assert client.put(f"{BASE_URL}/api/settings", json={"symbol_params": PARAMS}, timeout=20).status_code == 200
        r = client.post(f"{BASE_URL}/api/walk-forward/check", timeout=20)
        assert r.status_code == 200 and r.json()["auto_remove"] is True
        d = wait_done(client)
        assert d["job"]["status"] == "done", d["job"]
        lt = d["latest"]
        assert lt["auto_remove"] is True
        bad = [s for s in lt["checked"] if lt["results"][s]["verdict"] in BAD]
        print("verdicts:", {s: lt["results"][s]["verdict"] for s in lt["checked"]})
        for s in lt["checked"]:
            assert lt["results"][s]["removed"] == (s in bad)
        assert set(lt["removed"]) == set(bad)
        for s in bad:
            assert fl(lt["removed"][s]) == fl(PARAMS[s])
        sp = client.get(f"{BASE_URL}/api/settings", timeout=20).json()["symbol_params"]
        for s in PARAMS:
            assert (s in sp) == (s not in bad), f"{s} presence in symbol_params wrong: {sp}"
        logs = client.get(f"{BASE_URL}/api/dashboard", timeout=30).json()["logs"]
        if bad:
            assert any(l.get("level") == "PLAN" and "quitados por sobreajuste" in l.get("message", "") for l in logs[:30])
        TestAutoRemoveAPI.bad = bad

    def test_02_expected_btc_overfit(self):
        # with current 1h Bitget data BTC {3,6,10} is expected SOBREAJUSTADO
        assert "BTCUSDT" in TestAutoRemoveAPI.bad and "ETHUSDT" not in TestAutoRemoveAPI.bad

    def test_03_auto_remove_off(self, client):
        r = client.put(f"{BASE_URL}/api/config", json={"wf_auto_remove": False}, timeout=20)
        assert r.status_code == 200 and r.json()["wf_auto_remove"] is False
        assert client.get(f"{BASE_URL}/api/walk-forward/check", timeout=20).json()["auto_remove"] is False
        assert client.put(f"{BASE_URL}/api/settings", json={"symbol_params": PARAMS}, timeout=20).status_code == 200
        assert client.post(f"{BASE_URL}/api/walk-forward/check", timeout=20).status_code == 200
        d = wait_done(client)
        assert d["job"]["status"] == "done"
        lt = d["latest"]
        assert lt["auto_remove"] is False and lt["removed"] == {}
        assert all(r["removed"] is False for r in lt["results"].values())
        sp = client.get(f"{BASE_URL}/api/settings", timeout=20).json()["symbol_params"]
        assert "BTCUSDT" in sp and "ETHUSDT" in sp

    def test_04_restore(self, client):
        assert client.put(f"{BASE_URL}/api/config", json={"wf_auto_remove": True}, timeout=20).json()["wf_auto_remove"] is True
        assert client.put(f"{BASE_URL}/api/settings", json={"symbol_params": {}}, timeout=20).status_code == 200


# ---------- Unit: run_check with auto-remove ----------
class _Coll:
    def __init__(self, doc=None):
        self.doc = doc

    async def find_one(self, q, proj=None):
        return self.doc

    async def update_one(self, q, upd, upsert=False):
        self.doc = {**(self.doc or {}), **upd["$set"]}


def _fake(params):
    settings = SimpleNamespace(symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"], symbol_params=dict(params), timeframe="1h", strategy="all",
                               risk_per_trade=1, leverage=3, trailing_enabled=False, signal_mode="x", disabled_strategies=[])
    logs, updates = [], []

    async def get_settings():
        return settings

    async def update_settings(u):
        updates.append(u)

    async def fetch_history(*a):
        return []

    async def log(level, msg):
        logs.append((level, msg))

    engine = SimpleNamespace(get_settings=get_settings, update_settings=update_settings,
                             market=SimpleNamespace(fetch_history=fetch_history), log=log)
    db = SimpleNamespace(wf_checks=_Coll(), account=_Coll({"initial_balance": 1000}))
    return engine, db, logs, updates


def _wf(verdict, applied=True):
    agg = {"trades": 20, "expectancy_r": 0.2, "profit_factor": 1.3, "return_pct": 4.0, "win_rate": 50.0}
    a = {"verdict": verdict, "verdict_text": "t", "wfe": 0.7, "is_expectancy_r": 0.3, "oos": agg}
    return {**a, "baseline_oos": agg, "folds": [1, 2, 3], "applied": a if applied else None}


class TestAutoRemoveUnit:
    def _run(self, monkeypatch, verdicts, params, auto):
        import wfcheck
        sent = []

        async def fake_notify(msg, kind=None):
            sent.append((msg, kind))
        monkeypatch.setattr(wfcheck.notify, "notify", fake_notify)
        it = iter(verdicts)
        monkeypatch.setattr(wfcheck, "walk_forward", lambda *a, **k: _wf(next(it)))
        engine, db, logs, updates = _fake(params)
        store = SimpleNamespace(cfg=SimpleNamespace(wf_auto_remove=auto))
        doc = asyncio.run(wfcheck.run_check(engine, db, store, "auto"))
        return sent, logs, doc, updates

    def test_auto_on_removes(self, monkeypatch):
        sent, logs, doc, updates = self._run(monkeypatch, ["SOBREAJUSTADO", "ROBUSTO"], PARAMS, True)
        assert updates == [{"symbol_params": {"ETHUSDT": PARAMS["ETHUSDT"]}}]
        assert doc["removed"] == {"BTCUSDT": PARAMS["BTCUSDT"]} and doc["auto_remove"] is True
        assert doc["results"]["BTCUSDT"]["removed"] is True and doc["results"]["ETHUSDT"]["removed"] is False
        msg, kind = sent[0]
        assert kind == "review"
        assert msg.startswith("✂️ <b>Walk-forward: SL/TP quitados en 1 par</b>")
        assert "<b>Cambios aplicados</b>" in msg and "valores por defecto" in msg
        assert any("quitados por sobreajuste" in m for _, m in logs)

    def test_auto_on_plural_no_rentable(self, monkeypatch):
        sent, _, doc, updates = self._run(monkeypatch, ["SOBREAJUSTADO", "NO_RENTABLE"], PARAMS, True)
        assert updates == [{"symbol_params": {}}]
        assert sent[0][0].startswith("✂️ <b>Walk-forward: SL/TP quitados en 2 pares</b>")

    def test_auto_off_warns(self, monkeypatch):
        sent, _, doc, updates = self._run(monkeypatch, ["SOBREAJUSTADO", "ROBUSTO"], PARAMS, False)
        assert updates == [] and doc["removed"] == {} and doc["auto_remove"] is False
        assert sent[0][0].startswith("⚠️") and "Recomendación" in sent[0][0]

    def test_all_ok(self, monkeypatch):
        sent, _, doc, updates = self._run(monkeypatch, ["ROBUSTO", "ROBUSTO"], PARAMS, True)
        assert updates == [] and sent[0][0].startswith("🧪")

    def test_no_params(self, monkeypatch):
        sent, _, doc, updates = self._run(monkeypatch, [], {}, True)
        assert sent == [] and updates == [] and doc["checked"] == []

    def test_applied_none(self, monkeypatch):
        import wfcheck
        monkeypatch.setattr(wfcheck.notify, "notify", lambda *a, **k: asyncio.sleep(0))
        monkeypatch.setattr(wfcheck, "walk_forward", lambda *a, **k: _wf("ROBUSTO", applied=False))
        engine, db, _, _ = _fake({"BTCUSDT": PARAMS["BTCUSDT"]})
        doc = asyncio.run(wfcheck.run_check(engine, db, SimpleNamespace(cfg=SimpleNamespace(wf_auto_remove=True)), "auto"))
        assert doc["results"]["BTCUSDT"]["verdict"] == "ROBUSTO"


# ---------- API: weekly summary ----------
TAG = "TEST_iter12"


def _seed():
    now = datetime.now(timezone.utc)
    rec = (now - timedelta(hours=2)).isoformat()
    old = (now - timedelta(days=10)).isoformat()
    trades = [
        {"symbol": "SOLUSDT", "pnl": 12.5, "fees": 0.4, "strategy": "trend_ema", "reason": "TP", "side": "Buy", "closed_at": rec, "qa": TAG},
        {"symbol": "SOLUSDT", "pnl": -2.5, "fees": 0.3, "strategy": "trend_ema", "reason": "SL", "side": "Buy", "closed_at": rec, "qa": TAG},
        {"symbol": "XRPUSDT", "pnl": 4.0, "fees": 0.2, "strategy": "breakout_turtle", "reason": "TP", "side": "Sell", "closed_at": rec, "qa": TAG},
        {"symbol": "DOGEUSDT", "pnl": -7.0, "fees": 0.5, "strategy": "mean_reversion", "reason": "SL", "side": "Buy", "closed_at": rec, "qa": TAG},
        {"symbol": "ADAUSDT", "pnl": 99.0, "fees": 1.0, "strategy": "trend_ema", "reason": "TP", "side": "Buy", "closed_at": old, "qa": TAG},
    ]
    shadows = [{"kind": "RECHAZADA", "pnl": -5.0, "closed_at": rec, "qa": TAG},
               {"kind": "BLOQUEADA", "pnl": 3.0, "closed_at": rec, "qa": TAG}]

    import uuid
    for t in trades:
        t.update(id=uuid.uuid4().hex, entry_price=100.0, exit_price=101.0, qty=1.0, leverage=3, margin=33.0, pnl_pct=1.0,
                 opened_at=t["closed_at"], live=False)

    async def go(db):
        await db.trades.insert_many(trades)
        await db.shadow_trades.insert_many(shadows)
    _db_run(go)


def _cleanup():
    async def go(db):
        await db.trades.delete_many({"qa": TAG})
        await db.shadow_trades.delete_many({"qa": TAG})
    _db_run(go)


@pytest.fixture(scope="class")
def seeded():
    _cleanup()
    _seed()
    yield
    _cleanup()


class TestWeeklyAPI:
    def test_unauth(self):
        assert requests.get(f"{BASE_URL}/api/weekly-summary", timeout=20).status_code == 401

    def test_preview_fields_and_coherence(self, client, seeded):
        r = client.get(f"{BASE_URL}/api/weekly-summary", timeout=30)
        assert r.status_code == 200
        w = r.json()
        for k in ("from", "to", "mode", "equity", "start_equity", "week_pnl", "week_return_pct", "total_return_pct", "max_drawdown",
                  "open_positions", "week", "by_symbol", "by_strategy", "best", "worst", "signals", "shadow", "plan", "news",
                  "risk_profile", "text", "last_sent_at"):
            assert k in w, k
        for k in ("trades", "pnl", "wins", "win_rate", "profit_factor", "fees"):
            assert k in w["week"]
        for k in ("phase_name", "message", "warnings", "ready_to_advance", "days_running", "last_30d"):
            assert k in w["plan"]
        wk = w["week"]
        assert wk["trades"] == 4 and wk["pnl"] == 7.0 and wk["wins"] == 2 and wk["win_rate"] == 50.0
        assert wk["fees"] == 1.4 and wk["profit_factor"] == round(16.5 / 9.5, 2)
        assert [b["key"] for b in w["best"]] == ["SOLUSDT", "XRPUSDT"] and w["best"][0]["pnl"] == 10.0
        assert [b["key"] for b in w["worst"]] == ["DOGEUSDT"] and w["worst"][0]["pnl"] == -7.0
        assert all(b["pnl"] > 0 for b in w["best"]) and all(b["pnl"] < 0 for b in w["worst"])
        assert "ADAUSDT" not in [b["key"] for b in w["by_symbol"]]
        assert [s["key"] for s in w["by_strategy"]] == ["trend_ema", "breakout_turtle", "mean_reversion"]
        sh = w["shadow"]
        assert sh == {"trades": 2, "filter_value": 2.0, "ai_trades": 1, "ai_value": 5.0}
        t = w["text"]
        assert t.startswith("📈 <b>Resumen semanal") or t.startswith("📉 <b>Resumen semanal")
        assert "Equidad" in t and "📋 <b>Plan</b>" in t
        assert "Valor del filtro: evitó pérdidas por <b>2.00 USDT</b>" in t
        assert "<b>Mejores pares</b>" in t and "🟢 SOL +10.00 USDT" in t and "🔴 DOGE -7.00 USDT" in t
        if w["signals"]["total"]:
            assert "<b>Filtro IA</b>" in t

    def test_send_424(self, client):
        r = client.post(f"{BASE_URL}/api/weekly-summary/send", timeout=30)
        assert r.status_code == 424
        assert "Telegram" in r.json().get("detail", "")

    def test_cron_auth_and_body(self):
        assert requests.post(f"{BASE_URL}/api/cron/weekly-summary", json={"run_id": "x"}, timeout=20).status_code == 401
        assert requests.post(f"{BASE_URL}/api/cron/weekly-summary", json={"run_id": "x"},
                             headers={"Authorization": "Bearer wrong"}, timeout=20).status_code == 401
        r = requests.post(f"{BASE_URL}/api/cron/weekly-summary", data="notjson",
                          headers={"Authorization": f"Bearer {SECRET}", "Content-Type": "application/json"}, timeout=20)
        assert r.status_code == 400

    def test_cron_runs_and_idempotent(self, client):
        async def clear(db):
            await db.weekly.delete_many({})
        _db_run(clear)
        rid = f"qa-wk-{int(time.time())}"
        t = time.time()
        r = requests.post(f"{BASE_URL}/api/cron/weekly-summary", json={"run_id": rid},
                          headers={"Authorization": f"Bearer {SECRET}"}, timeout=20)
        assert time.time() - t < 2.5
        assert r.status_code == 200 and r.json() == {"accepted": True, "scheduled": True}
        r2 = requests.post(f"{BASE_URL}/api/cron/weekly-summary", json={"run_id": rid},
                           headers={"Authorization": f"Bearer {SECRET}"}, timeout=20)
        assert r2.json() == {"accepted": True, "duplicate": True}
        time.sleep(3)
        logs = client.get(f"{BASE_URL}/api/dashboard", timeout=30).json()["logs"]
        # Telegram is not configured in this pod → generated but NOT sent: no 'enviado' log, no last_sent_at
        assert any(l.get("level") == "INFO" and "Resumen semanal generado pero no enviado" in l.get("message", "") for l in logs[:30])
        assert not any("Resumen semanal enviado" in l.get("message", "") for l in logs[:30])

        async def get(db):
            return await db.weekly.find_one({"_id": "latest"})
        assert _db_run(get) is None
        assert client.get(f"{BASE_URL}/api/weekly-summary", timeout=30).json()["last_sent_at"] is None


# ---------- Artifacts ----------
class TestArtifacts:
    def test_crons_yml(self):
        d = yaml.safe_load(open("/app/.emergent/crons.yml"))
        names = {c["name"]: c for c in d["crons"]}
        assert set(names) == {"ai-review-daily", "walk-forward-weekly", "weekly-summary"}
        assert all(len(n) <= 21 for n in names)
        w = names["weekly-summary"]
        assert w["cron"] == "0 20 * * 0" and w["endpoint"] == "{{BASE_URL}}/api/cron/weekly-summary" and w["method"] == "POST"

    def test_deploy_script_executable(self):
        p = "/app/deploy/cron-weekly-summary.sh"
        assert os.access(p, os.X_OK), "cron-weekly-summary.sh is not executable"

    def test_deploy_script_content(self):
        p = "/app/deploy/cron-weekly-summary.sh"
        assert "/api/cron/weekly-summary" in open(p).read()
        assert subprocess.run(["bash", "-n", p]).returncode == 0
        inst = open("/app/deploy/install.sh").read()
        assert "0 20 * * 0" in inst and "cron-weekly-summary.sh" in inst
