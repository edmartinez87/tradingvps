# Iteration 11: weekly walk-forward revalidation (cron webhook, manual check job, wfcheck unit w/ notify monkeypatch,
# review.build_context walk_forward_pares_aplicados, crons.yml/deploy artifacts, quick regression)
import os
import sys
import time
import asyncio
import subprocess
from types import SimpleNamespace

import pytest
import requests
import yaml
from dotenv import load_dotenv

sys.path.insert(0, "/app/backend")
load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
PASSWORD = "BlackCat2233@"
SECRET = os.environ.get("WEBHOOK_CRON_SECRET")
VERDICTS = {"ROBUSTO", "DUDOSO", "SOBREAJUSTADO", "NO_RENTABLE", "INSUFICIENTE"}
PARAMS = {"BTCUSDT": {"sl_atr": 3, "tp_atr": 6, "atr_period": 10}, "ETHUSDT": {"sl_atr": 2.5, "tp_atr": 5, "atr_period": 14}}


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


# ---------- API: cron + manual check (sequential, shared state) ----------
class TestWalkForwardCheckAPI:
    def test_00_disable_auto_remove(self, client):
        # iter12: keep iter11 behaviour (no auto-removal) for this class
        assert client.put(f"{BASE_URL}/api/config", json={"wf_auto_remove": False}, timeout=20).status_code == 200

    def test_01_cron_no_auth(self):
        r = requests.post(f"{BASE_URL}/api/cron/walk-forward", json={"run_id": "x"}, timeout=20)
        assert r.status_code == 401

    def test_02_cron_bad_body(self):
        r = requests.post(f"{BASE_URL}/api/cron/walk-forward", data="notjson",
                          headers={"Authorization": f"Bearer {SECRET}", "Content-Type": "application/json"}, timeout=20)
        assert r.status_code == 400

    def test_03_cron_empty_params(self, client):
        assert client.put(f"{BASE_URL}/api/settings", json={"symbol_params": {}}, timeout=20).status_code == 200
        wait_done(client)
        rid = f"qa-wf-{int(time.time())}"
        t = time.time()
        r = requests.post(f"{BASE_URL}/api/cron/walk-forward", json={"run_id": rid},
                          headers={"Authorization": f"Bearer {SECRET}"}, timeout=20)
        assert time.time() - t < 2.5
        assert r.status_code == 200 and r.json() == {"accepted": True, "scheduled": True}
        r2 = requests.post(f"{BASE_URL}/api/cron/walk-forward", json={"run_id": rid},
                           headers={"Authorization": f"Bearer {SECRET}"}, timeout=20)
        assert r2.json() == {"accepted": True, "duplicate": True}
        d = wait_done(client)
        assert d["job"]["status"] == "done"
        lt = d["latest"]
        assert lt["source"] == "auto" and lt["checked"] == [] and lt["results"] == {}
        logs = client.get(f"{BASE_URL}/api/dashboard", timeout=30).json()["logs"]
        assert any(l.get("level") == "PLAN" and "nada que revalidar" in l.get("message", "") for l in logs[:30])

    def test_04_manual_check_with_params(self, client):
        assert client.put(f"{BASE_URL}/api/settings", json={"symbol_params": PARAMS}, timeout=20).status_code == 200
        r = client.post(f"{BASE_URL}/api/walk-forward/check", timeout=20)
        assert r.status_code == 200 and r.json()["job"]["status"] == "running"
        r2 = client.post(f"{BASE_URL}/api/walk-forward/check", timeout=20)
        assert r2.status_code == 409
        d = wait_done(client)
        assert d["job"]["status"] == "done", d["job"]
        lt = d["latest"]
        syms = client.get(f"{BASE_URL}/api/settings", timeout=20).json()["symbols"]
        assert lt["source"] == "manual"
        assert lt["checked"] == [s for s in syms if s in PARAMS]
        for s in lt["checked"]:
            r = lt["results"][s]
            assert r["verdict"] in VERDICTS and r["verdict_text"]
            for k in ("trades", "expectancy_r", "profit_factor", "return_pct", "win_rate"):
                assert k in r["oos"] and k in r["baseline_oos"]
            assert isinstance(r["folds"], int) and r["folds"] > 0
            assert {k: float(v) for k, v in r["params"].items()} == {k: float(v) for k, v in PARAMS[s].items()}
            # previous run was the empty one → no previous verdicts
            assert r["previous_verdict"] is None and r["changed"] is False
        logs = client.get(f"{BASE_URL}/api/dashboard", timeout=30).json()["logs"]
        assert any(l.get("level") == "PLAN" and "Walk-forward manual · 2 pares" in l.get("message", "") for l in logs[:30])
        TestWalkForwardCheckAPI.first = lt

    def test_05_second_run_previous_verdict_and_consistency(self, client):
        first = TestWalkForwardCheckAPI.first
        assert client.post(f"{BASE_URL}/api/walk-forward/check", timeout=20).status_code == 200
        lt = wait_done(client)["latest"]
        for s in lt["checked"]:
            r = lt["results"][s]
            assert r["previous_verdict"] == first["results"][s]["verdict"]
            assert r["changed"] == (r["previous_verdict"] != r["verdict"])
            m = client.post(f"{BASE_URL}/api/optimize/walk-forward", json={"symbol": s}, timeout=90).json()
            assert m["verdict"] == r["process_verdict"], f"{s}: manual {m['verdict']} vs check {r['process_verdict']}"
            assert m["applied"]["verdict"] == r["verdict"], f"{s}: applied {m['applied']['verdict']} vs check {r['verdict']}"

    def test_06_restore_auto_remove(self, client):
        assert client.put(f"{BASE_URL}/api/config", json={"wf_auto_remove": True}, timeout=20).json()["wf_auto_remove"] is True


# ---------- Unit: wfcheck.run_check telegram message ----------
class _Coll:
    def __init__(self, doc=None):
        self.doc = doc

    async def find_one(self, q, proj=None):
        return self.doc

    async def update_one(self, q, upd, upsert=False):
        self.doc = {**(self.doc or {}), **upd["$set"]}


def _fake(params, symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT")):
    settings = SimpleNamespace(symbols=list(symbols), symbol_params=params, timeframe="1h", strategy="all", risk_per_trade=1,
                               leverage=3, trailing_enabled=False, signal_mode="x", disabled_strategies=[])
    logs = []

    async def get_settings():
        return settings

    async def fetch_history(*a):
        return []

    async def log(level, msg):
        logs.append((level, msg))

    engine = SimpleNamespace(get_settings=get_settings, market=SimpleNamespace(fetch_history=fetch_history), log=log)
    db = SimpleNamespace(wf_checks=_Coll(), account=_Coll({"initial_balance": 1000}))
    return engine, db, logs


def _wf(verdict):
    agg = {"trades": 20, "expectancy_r": 0.2, "profit_factor": 1.3, "return_pct": 4.0, "win_rate": 50.0}
    return {"verdict": verdict, "verdict_text": "t", "wfe": 0.7, "is_expectancy_r": 0.3, "oos": agg, "baseline_oos": agg, "folds": [1, 2, 3],
            "applied": {"verdict": verdict, "verdict_text": "t", "wfe": 0.7, "is_expectancy_r": 0.3, "oos": agg}}


class TestWfcheckUnit:
    def _run(self, monkeypatch, verdicts, params):
        import wfcheck
        sent = []

        async def fake_notify(msg, kind=None):
            sent.append((msg, kind))
        monkeypatch.setattr(wfcheck.notify, "notify", fake_notify)
        it = iter(verdicts)
        monkeypatch.setattr(wfcheck, "walk_forward", lambda *a, **k: _wf(next(it)))
        engine, db, logs = _fake(params)
        store = SimpleNamespace(cfg=SimpleNamespace(wf_auto_remove=False))
        doc = asyncio.run(wfcheck.run_check(engine, db, store, "auto"))
        return sent, logs, doc

    def test_bad_message(self, monkeypatch):
        sent, logs, doc = self._run(monkeypatch, ["SOBREAJUSTADO", "ROBUSTO"], PARAMS)
        assert len(sent) == 1
        msg, kind = sent[0]
        assert kind == "review"
        assert msg.startswith("⚠️ <b>Walk-forward:")
        assert "Recomendación" in msg and "BTC" in msg
        assert doc["checked"] == ["BTCUSDT", "ETHUSDT"]
        assert any("semanal" in m for _, m in logs)

    def test_ok_message(self, monkeypatch):
        sent, _, _ = self._run(monkeypatch, ["ROBUSTO", "DUDOSO"], PARAMS)
        assert len(sent) == 1
        assert sent[0][0].startswith("🧪 <b>Walk-forward semanal · todo en orden</b>")
        assert "Recomendación" not in sent[0][0]

    def test_no_params_no_notify(self, monkeypatch):
        sent, logs, doc = self._run(monkeypatch, [], {})
        assert sent == [] and doc["checked"] == [] and doc["results"] == {}
        assert any("nada que revalidar" in m for _, m in logs)


# ---------- Unit: review.build_context ----------
class TestBuildContext:
    def _ctx(self, monkeypatch, wf_doc):
        import review

        async def perf(db):
            return {"shadow": {}}

        async def rej(db):
            return []
        monkeypatch.setattr(review, "performance", perf)
        monkeypatch.setattr(review, "recent_rejections", rej)

        async def checkin(s, a):
            return {}
        from models import Settings as BotSettings
        engine = SimpleNamespace(checkin=checkin, news=None)
        db = SimpleNamespace(wf_checks=_Coll(wf_doc))
        return asyncio.run(review.build_context(engine, db, BotSettings(), {"initial_balance": 1000}, False))

    def test_included(self, monkeypatch):
        r = {"verdict": "ROBUSTO", "wfe": 0.8, "oos": {"trades": 3}, "previous_verdict": None, "extra": 1}
        ctx = self._ctx(monkeypatch, {"ran_at": "2026-10-20", "results": {"BTCUSDT": r}})
        w = ctx["walk_forward_pares_aplicados"]
        assert w["revisado"] == "2026-10-20" and w["_explicacion"]
        assert w["pares"]["BTCUSDT"] == {"verdict": "ROBUSTO", "wfe": 0.8, "oos": {"trades": 3}, "previous_verdict": None}

    def test_excluded_when_empty(self, monkeypatch):
        assert "walk_forward_pares_aplicados" not in self._ctx(monkeypatch, {"ran_at": "x", "results": {}})
        assert "walk_forward_pares_aplicados" not in self._ctx(monkeypatch, None)


# ---------- Artifacts ----------
class TestArtifacts:
    def test_crons_yml(self):
        d = yaml.safe_load(open("/app/.emergent/crons.yml"))
        names = {c["name"]: c for c in d["crons"]}
        assert {"ai-review-daily", "walk-forward-weekly"} <= set(names)
        assert all(len(n) <= 21 for n in names)
        w = names["walk-forward-weekly"]
        assert w["cron"] == "0 7 * * 1" and w["endpoint"] == "{{BASE_URL}}/api/cron/walk-forward" and w["method"] == "POST"

    def test_deploy_scripts(self):
        p = "/app/deploy/cron-walk-forward.sh"
        assert os.access(p, os.X_OK)
        assert "/api/cron/walk-forward" in open(p).read()
        assert subprocess.run(["bash", "-n", p]).returncode == 0
        inst = open("/app/deploy/install.sh").read()
        assert "0 7 * * 1" in inst and "cron-walk-forward.sh" in inst


# ---------- Regression ----------
class TestRegression:
    def test_dashboard(self, client):
        assert client.get(f"{BASE_URL}/api/dashboard", timeout=30).status_code == 200

    def test_optimize(self, client):
        r = client.post(f"{BASE_URL}/api/optimize", json={"symbol": "BTCUSDT"}, timeout=90)
        assert r.status_code == 200
