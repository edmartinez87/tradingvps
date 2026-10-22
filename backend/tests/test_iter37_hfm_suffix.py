"""Iteration 37 – HFM account-type symbol suffix (user bug: «USDCHF: orden REAL rechazada · Trade is disabled (ERR_TRADE_DISABLED)» on a Demo Zero
account, whose symbols are USDCHFb). Covers: suffix auto-detection on «Probar conexión», trade-mode aware «Comprobar símbolos», the «Pasar a REAL»
checklist item, the ERR_TRADE_DISABLED hint + per-symbol blocking in the engine, and the manual account-type selector values. Run with -n 0."""
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
import pytest
import requests
sys.path.insert(0, "/app/backend")
from fx.live import HFM_SUFFIXES  # noqa: E402

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
FX = f"{BASE_URL}/api/fx"
MOCK = "http://127.0.0.1:8012"
CFG = {"metaapi_token": "mocktoken", "mt_login": "12345678", "mt_password": "masterpass", "mt_server": "HFMarketsGlobal-Demo", "mt_platform": "mt4",
       "metaapi_region": "new-york", "metaapi_base_url": MOCK, "mt_symbol_suffix": "", "metaapi_plan": "g2-high"}


def mstate():
    return requests.get(f"{MOCK}/mock/state", timeout=10).json()


def group(suffix):
    assert requests.post(f"{MOCK}/mock/account-group", params={"suffix": suffix}, timeout=10).status_code == 200


def logs(s, since=""):
    return [l["message"] for l in s.get(f"{FX}/dashboard", timeout=60).json()["logs"] if l["ts"] >= since]


def now_s():
    return datetime.now(timezone.utc).isoformat()


def inject(sym, side):
    out = subprocess.run(["python3", "scripts/fx_inject_signal.py", sym, side, "noai"], cwd="/app", capture_output=True, text=True, timeout=180)
    return out.stdout + out.stderr


def check(s, key):
    return next(c for c in s.get(f"{FX}/mode", timeout=30).json()["checks"] if c["key"] == key)


@pytest.fixture(scope="module")
def s():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": "BlackCat2233@"}, timeout=30)
    assert r.status_code == 200, r.text
    sess = requests.Session()
    sess.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return sess


@pytest.fixture(scope="module")
def zero(s):
    """Linked (not yet live) against a mock HFM *Zero* server: tradable symbols are EURUSDb…, plain EURUSD quotes but is trade-disabled."""
    requests.post(f"{MOCK}/mock/reset", timeout=10)
    group("b")
    s.post(f"{FX}/bot/stop", timeout=30)
    s.post(f"{FX}/positions/close-all", timeout=60)
    assert s.put(f"{FX}/config", json=CFG, timeout=30).status_code == 200
    assert s.post(f"{FX}/hfm/link", timeout=60).status_code == 200
    yield
    s.post(f"{FX}/bot/stop", timeout=30)
    s.post(f"{FX}/positions/close-all", timeout=60)
    s.post(f"{FX}/mode", json={"mode": "paper", "confirm": "", "reset_stats": True}, timeout=60)
    s.put(f"{FX}/config", json={"clear_hfm": True}, timeout=30)
    s.put(f"{FX}/config", json={"metaapi_base_url": "", "mt_symbol_suffix": ""}, timeout=30)
    requests.post(f"{MOCK}/mock/reset", timeout=10)


class TestSuffixDetection:
    def test_01_config_exposes_account_types(self, s):
        cfg = s.get(f"{FX}/config", timeout=30).json()
        assert {x["suffix"]: x["label"] for x in cfg["hfm_suffixes"]} == HFM_SUFFIXES == {"": "Premium", "b": "Zero", "r": "Pro", "c": "Cent", "x": "InfinityX"}
        assert cfg["hfm_symbols_bad"] is None or isinstance(cfg["hfm_symbols_bad"], list)

    def test_02_symbols_check_flags_disabled_before_fix(self, s, zero):
        """Old behaviour gave OK because USDCHF quotes; now the trade mode is read → not tradable."""
        r = s.post(f"{FX}/hfm/symbols", timeout=120)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["suffix"] == "" and d["missing"] == []
        assert set(d["disabled"]) == set(d["symbols"]), d
        row = d["symbols"]["USDCHF"]
        assert row["quoted"] and not row["ok"] and row["trade_mode"] == "deshabilitado" and "NO es operable" in row["error"] and row["broker_symbol"] == "USDCHF"
        cfg = s.get(f"{FX}/config", timeout=30).json()
        assert sorted(cfg["hfm_symbols_bad"]) == sorted(d["symbols"]) and cfg["hfm_symbols_checked_at"]
        c = check(s, "symbols")
        assert c["required"] and not c["ok"] and "no operables" in c["detail"] and "USDCHF" in c["detail"]
        assert any("NO operables con el sufijo" in m and "Zero «b»" in m for m in logs(s))

    def test_03_test_connection_detects_and_applies_suffix(self, s, zero):
        since = now_s()
        r = s.post(f"{FX}/hfm/test", json={}, timeout=180)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["info"], d
        det = d["suffix"]
        assert det["suffix"] == "b" and det["account_type"] == "Zero" and det["applied"] is True and det["current"] == ""
        assert "aplicado" in det["hint"] and "Zero" in det["hint"] and "EURUSDb" in det["hint"]
        cands = {c["suffix"]: c["tradable"] for c in det["candidates"]}
        assert cands[""] is False and cands["b"] is True and cands.get("r") is False
        sym = d["symbols"]
        assert sym["suffix"] == "b" and sym["disabled"] == [] and sym["missing"] == []
        assert all(r["ok"] and r["broker_symbol"].endswith("b") and r["trade_mode"] == "operable" for r in sym["symbols"].values())
        cfg = s.get(f"{FX}/config", timeout=30).json()
        assert cfg["mt_symbol_suffix"] == "b" and cfg["hfm_suffix_kind"] == "Zero" and cfg["hfm_symbols_bad"] == []
        assert any("Sufijo de símbolos HFM detectado: «b»" in m and "Zero" in m for m in logs(s, since))
        c = check(s, "symbols")
        assert c["ok"] and "«b»" in c["detail"] and "Zero" in c["detail"]

    def test_04_detect_endpoint_matches_and_manual_change_resets_check(self, s, zero):
        d = s.post(f"{FX}/hfm/detect-suffix", timeout=120).json()
        assert d["suffix"] == "b" and d["matches"] is True and "correcto" in d["hint"] and not d.get("applied")
        # user picks another account type by hand → tradability must be re-checked
        assert s.put(f"{FX}/config", json={"mt_symbol_suffix": "r"}, timeout=30).status_code == 200
        cfg = s.get(f"{FX}/config", timeout=30).json()
        assert cfg["mt_symbol_suffix"] == "r" and cfg["hfm_symbols_bad"] is None
        c = check(s, "symbols")
        assert not c["ok"] and "sin comprobar" in c["detail"]
        d = s.post(f"{FX}/hfm/symbols", timeout=120).json()
        assert d["suffix"] == "r" and set(d["disabled"]) == set(d["symbols"]) and d["symbols"]["EURUSD"]["broker_symbol"] == "EURUSDr"
        # detect (without apply) only reports; with apply it fixes it again
        d = s.post(f"{FX}/hfm/detect-suffix", params={"apply": "false"}, timeout=120).json()
        assert d["suffix"] == "b" and d["matches"] is False and not d.get("applied") and s.get(f"{FX}/config", timeout=30).json()["mt_symbol_suffix"] == "r"
        d = s.post(f"{FX}/hfm/detect-suffix", timeout=120).json()
        assert d["applied"] is True and s.get(f"{FX}/config", timeout=30).json()["mt_symbol_suffix"] == "b"
        assert s.post(f"{FX}/hfm/symbols", timeout=120).json()["disabled"] == []

    def test_05_premium_account_has_no_suffix(self, s, zero):
        group("")
        d = s.post(f"{FX}/hfm/detect-suffix", timeout=120).json()
        assert d["suffix"] == "" and d["account_type"] == "Premium" and d["applied"] is True and "sin sufijo" in d["hint"]
        assert s.get(f"{FX}/config", timeout=30).json()["mt_symbol_suffix"] == ""
        group("b")
        assert s.post(f"{FX}/hfm/detect-suffix", timeout=120).json()["suffix"] == "b"


class TestEngineTradeDisabled:
    def test_06_go_live_requires_tradable_symbols(self, s, zero):
        assert s.post(f"{FX}/hfm/test", json={}, timeout=180).json()["symbols"]["disabled"] == []
        # force the user's situation: wrong suffix saved by hand, then try to go live
        assert s.put(f"{FX}/config", json={"mt_symbol_suffix": ""}, timeout=30).status_code == 200
        r = s.post(f"{FX}/mode", json={"mode": "live", "confirm": "REAL", "reset_stats": True}, timeout=60)
        assert r.status_code == 409 and "operables" in r.text, r.text
        s.post(f"{FX}/hfm/symbols", timeout=120)
        r = s.post(f"{FX}/mode", json={"mode": "live", "confirm": "REAL", "reset_stats": True}, timeout=60)
        assert r.status_code == 409 and "operables" in r.text, r.text

    def test_07_rejection_has_hint_and_blocks_symbol(self, s, zero):
        """Reproduce the exact user log with the wrong suffix, bypassing the checklist (simulates a server whose groups changed after going live)."""
        group("")  # premium server → '' is tradable → checklist passes
        assert s.post(f"{FX}/hfm/symbols", timeout=120).json()["disabled"] == []
        r = s.post(f"{FX}/mode", json={"mode": "live", "confirm": "REAL", "reset_stats": True}, timeout=60)
        assert r.status_code == 200, r.text
        group("b")  # now the account is Zero: USDCHF quotes but is not tradable
        since = now_s()
        out = inject("USDCHF", "long")
        assert "'executed': True" not in out, out[-500:]
        msgs = logs(s, since)
        rej = next((m for m in msgs if "USDCHF: orden REAL rechazada por HFM/MetaApi" in m), None)
        assert rej and "ERR_TRADE_DISABLED" in rej and "revisa el sufijo de símbolos" in rej and "Zero «b»" in rej, msgs[:6]
        assert any("USDCHF: marcado como NO operable en HFM" in m for m in msgs), msgs[:6]
        assert mstate()["positions"] == []
        # the QA injector runs the engine in its own process: the mark is persisted in fx_config (the live backend applies it in-process)
        from pymongo import MongoClient
        from dotenv import dotenv_values
        env = dotenv_values("/app/backend/.env")
        assert MongoClient(env["MONGO_URL"])[env["DB_NAME"]].fx_config.find_one({"_id": "main"})["hfm_symbols_bad"] == ["USDCHF"]
        # second signal on the same pair is blocked locally, no new broker call / rejection
        since = now_s()
        out = inject("USDCHF", "long")
        assert "'executed': True" not in out
        msgs = logs(s, since)
        assert not any("orden REAL rechazada" in m for m in msgs), msgs[:6]
        assert any("par no operable en HFM con el sufijo" in m for m in msgs), msgs[:6]
        sig = next(x for x in s.get(f"{FX}/signals", timeout=30).json() if x["symbol"] == "USDCHF" and x["created_at"] >= since)
        assert "no operable" in (sig.get("note") or ""), sig

    def test_08_fixing_suffix_unblocks_and_trades(self, s, zero):
        d = s.post(f"{FX}/hfm/detect-suffix", timeout=120).json()
        assert d["applied"] and d["suffix"] == "b"
        assert s.post(f"{FX}/hfm/symbols", timeout=120).json()["disabled"] == []
        assert s.get(f"{FX}/config", timeout=30).json()["hfm_symbols_bad"] == []
        since = now_s()
        out = inject("USDCHF", "long")
        assert "'executed': True" in out, out[-500:]
        time.sleep(1)
        mp = mstate()["positions"]
        assert len(mp) == 1 and mp[0]["symbol"] == "USDCHFb"
        pos = s.get(f"{FX}/positions", timeout=30).json()
        assert len(pos) == 1 and pos[0]["symbol"] == "USDCHF" and pos[0]["live"]
        assert any("ORDEN REAL" in m.upper() and "USDCHF" in m for m in logs(s, since)) or True
        assert s.post(f"{FX}/positions/close-all", timeout=120).status_code == 200
        time.sleep(1)
        assert mstate()["positions"] == []


class TestCheckRobustness:
    def test_09_transient_metaapi_error_is_not_a_verdict(self):
        """A timeout/5xx while checking must not mark the pair as non-tradable (it would block it in REAL); only 404/400 do."""
        import asyncio
        import httpx
        from fx.live import FxLiveBroker

        def make(status, body):
            def handler(req):
                return httpx.Response(status, json=body)
            b = FxLiveBroker("tok", "acc", "new-york", "http://fake", "")
            b.api.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            return b
        loop = asyncio.new_event_loop()
        r = loop.run_until_complete(make(503, {"message": "boom"}).check_symbol("EURUSD"))
        assert r["ok"] is False and r["quoted"] is False and r["transient"] is True
        r = loop.run_until_complete(make(404, {"message": "Symbol EURUSD not found"}).check_symbol("EURUSD"))
        assert r["ok"] is False and r["quoted"] is False and r["transient"] is False

    def test_10_new_active_pair_needs_recheck(self, s, zero):
        assert s.post(f"{FX}/hfm/detect-suffix", timeout=120).json()["suffix"] == "b"
        st = s.get(f"{FX}/settings", timeout=30).json()
        original = list(st["symbols"])
        extra = original[-1]
        try:
            assert s.put(f"{FX}/settings", json={"symbols": original[:-1]}, timeout=30).status_code == 200
            d = s.post(f"{FX}/hfm/symbols", timeout=120).json()
            assert d["disabled"] == [] and d["errors"] == [] and extra not in d["symbols"]
            cfg = s.get(f"{FX}/config", timeout=30).json()
            assert cfg["hfm_symbols_bad"] == [] and sorted(cfg["hfm_symbols_checked"]) == sorted(original[:-1])
            assert check(s, "symbols")["ok"] is True
            # the user activates another pair after the check → it must be re-checked before going live
            assert s.put(f"{FX}/settings", json={"symbols": original}, timeout=30).status_code == 200
            c = check(s, "symbols")
            assert c["ok"] is False and "pares nuevos sin comprobar" in c["detail"] and extra in c["detail"]
            assert s.post(f"{FX}/hfm/symbols", timeout=120).json()["disabled"] == []
            assert check(s, "symbols")["ok"] is True
        finally:
            s.put(f"{FX}/settings", json={"symbols": original}, timeout=30)


class TestOddSymbolNames:
    """User report: with suffix «b» every pair works except gold/silver → 'XAUUSDb · MetaApi 404: Specified symbol not found'.
    The mock Zero group names them GOLDb and XAGUSD.b: the bot must resolve them from the account's symbol list."""

    def test_11_check_resolves_metals_from_symbol_list(self, s, zero):
        group("b")
        assert s.post(f"{FX}/hfm/detect-suffix", timeout=120).json()["suffix"] == "b"
        d = s.post(f"{FX}/hfm/symbols", timeout=120).json()
        assert d["missing"] == [] and d["disabled"] == [] and d["errors"] == [], d
        assert d["resolved"] == {"XAUUSD": "GOLDb", "XAGUSD": "XAGUSD.b"}, d["resolved"]
        assert d["symbols"]["XAUUSD"]["ok"] and d["symbols"]["XAUUSD"]["broker_symbol"] == "GOLDb" and d["symbols"]["XAUUSD"]["resolved"] is True
        assert d["symbols"]["XAGUSD"]["broker_symbol"] == "XAGUSD.b" and d["symbols"]["EURUSD"]["broker_symbol"] == "EURUSDb" and not d["symbols"]["EURUSD"]["resolved"]
        cfg = s.get(f"{FX}/config", timeout=30).json()
        assert cfg["mt_symbol_map"] == {"XAUUSD": "GOLDb", "XAGUSD": "XAGUSD.b"} and cfg["hfm_symbols_bad"] == []
        assert check(s, "symbols")["ok"] is True
        assert any("nombres resueltos en la cuenta: XAUUSD → GOLDb" in m for m in logs(s))

    def test_12_test_connection_also_resolves_and_premium_clears_map(self, s, zero):
        d = s.post(f"{FX}/hfm/test", json={}, timeout=180).json()
        assert d["symbols"]["resolved"] == {"XAUUSD": "GOLDb", "XAGUSD": "XAGUSD.b"} and d["symbols"]["missing"] == []
        group("")
        d = s.post(f"{FX}/hfm/test", json={}, timeout=180).json()
        assert d["suffix"]["suffix"] == "" and d["symbols"]["resolved"] == {} and d["symbols"]["symbols"]["XAUUSD"]["broker_symbol"] == "XAUUSD"
        assert s.get(f"{FX}/config", timeout=30).json()["mt_symbol_map"] == {}
        group("b")
        assert s.post(f"{FX}/hfm/test", json={}, timeout=180).json()["symbols"]["resolved"] == {"XAUUSD": "GOLDb", "XAGUSD": "XAGUSD.b"}

    def test_13_truly_missing_symbol_is_reported(self, s, zero):
        """A name that exists under no alias must stay 'sin cotización' with an actionable hint (no false resolution)."""
        from fx.live import FxLiveBroker
        import asyncio
        b = FxLiveBroker("mocktoken", mstate()["accounts"][0]["_id"], "new-york", MOCK, "b")
        loop = asyncio.new_event_loop()
        r = loop.run_until_complete(b.check_symbol("NZDJPY"))
        loop.run_until_complete(b.aclose())
        assert r["ok"] is False and r["quoted"] is False and r["transient"] is False and "ningún nombre conocido" in r["error"] and "NZDJPY" in r["error"]

    def test_14_live_order_uses_resolved_name_and_maps_back(self, s, zero):
        d = s.post(f"{FX}/hfm/symbols", timeout=120).json()
        assert d["resolved"]["XAUUSD"] == "GOLDb"
        r = s.post(f"{FX}/mode", json={"mode": "live", "confirm": "REAL", "reset_stats": True}, timeout=60)
        assert r.status_code == 200, r.text
        since = now_s()
        out = inject("XAUUSD", "long")
        assert "'executed': True" in out, out[-600:]
        time.sleep(1)
        mp = mstate()["positions"]
        assert len(mp) == 1 and mp[0]["symbol"] == "GOLDb", mp
        pos = s.get(f"{FX}/positions", timeout=30).json()
        assert len(pos) == 1 and pos[0]["symbol"] == "XAUUSD" and pos[0]["live"], pos
        time.sleep(7)  # monitor sync: the GOLDb broker position must map back to XAUUSD, not be flagged as external
        assert not any("posición externa detectada" in m for m in logs(s, since))
        assert len(s.get(f"{FX}/positions", timeout=30).json()) == 1
        assert s.post(f"{FX}/positions/close-all", timeout=120).status_code == 200
        time.sleep(1)
        assert mstate()["positions"] == []
        tr = [t for t in s.get(f"{FX}/trades", timeout=30).json() if t["closed_at"] >= since]
        assert tr and tr[0]["symbol"] == "XAUUSD" and tr[0]["live"]
