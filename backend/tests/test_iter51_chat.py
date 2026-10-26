"""Iteration 51 – «Chatea con IA expert»: /api/chat/* (state, async message jobs with tool calling, proposals Aplicar/Descartar, memory, new conversation, code reader guards)."""
import os
import sys
import time

import pytest
import requests

sys.path.insert(0, "/app/backend")
from chat import code_reader  # noqa: E402

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
CHAT = f"{API}/chat"


@pytest.fixture(scope="module")
def s():
    r = requests.post(f"{API}/auth/login", json={"password": "BlackCat2233@"}, timeout=30)
    assert r.status_code == 200, r.text
    sess = requests.Session()
    sess.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return sess


def ask(s, text, panel="crypto", timeout=240):
    r = s.post(f"{CHAT}/message", json={"text": text, "panel": panel}, timeout=30)
    assert r.status_code == 200, r.text
    jid = r.json()["id"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(2)
        j = s.get(f"{CHAT}/jobs/{jid}", timeout=30).json()
        if j["status"] != "running":
            return j
    raise AssertionError("la IA no respondió a tiempo")


class TestCodeReaderGuards:
    def test_denied_paths(self):
        for p in ("/app/backend/.env", "/etc/passwd", "/app/frontend/node_modules", "/app/backend/backups", "../../etc/hosts"):
            with pytest.raises(ValueError):
                code_reader._resolve(p)

    def test_read_and_search(self):
        d = code_reader.list_dir("/app/backend/chat")
        assert any(e["name"] == "service.py" for e in d["entries"])
        f = code_reader.read_file("backend/chat/knowledge.md", 1, 5)
        assert f["from"] == 1 and f["to"] == 5 and "AI Trading" in f["content"]
        hits = code_reader.search("def snapshot", "/app/backend/chat")
        assert any(h["file"].endswith("context.py") for h in hits["hits"])


class TestChatApi:
    def test_requires_auth(self):
        assert requests.get(CHAT, timeout=30).status_code == 401

    def test_state_shape(self, s):
        d = s.get(CHAT, timeout=30).json()
        for k in ("session", "messages", "memory", "pending", "job", "config", "ai", "ai_health"):
            assert k in d
        assert d["config"] == {"summary_every": 40, "keep_last": 10}
        assert d["ai"]["label"]

    def test_message_validation(self, s):
        assert s.post(f"{CHAT}/message", json={"text": "", "panel": "crypto"}, timeout=30).status_code == 422
        assert s.get(f"{CHAT}/jobs/nope", timeout=30).status_code == 404

    def test_message_with_tool_and_proposal(self, s):
        assert s.post(f"{CHAT}/new", timeout=30).status_code == 200  # fresh conversation so earlier runs don't bias the model
        before = s.get(f"{API}/settings", timeout=30).json()["scan_interval_sec"]
        target = 75 if before != 75 else 80
        j = ask(s, f"Propón cambiar el intervalo de escaneo del bot cripto (scan_interval_sec) a {target} segundos. Solo la propuesta, sin consultar nada más.")
        assert j["status"] == "done", j
        a = j["result"]["assistant"]
        assert j["result"]["user"]["role"] == "user" and a["role"] == "assistant" and not a["error"], a
        assert "propose_settings_change" in a["tools"], a["tools"]
        assert a["proposals"] and a["proposals"][0]["status"] == "pending"
        p = a["proposals"][0]
        assert p["kind"] == "settings" and p["bot"] == "crypto" and p["diff"]["scan_interval_sec"]["despues"] == target
        # settings untouched until the user confirms
        assert s.get(f"{API}/settings", timeout=30).json()["scan_interval_sec"] == before
        # a second message while idle is accepted; busy → 409 is covered by starting two in a row
        r1 = s.post(f"{CHAT}/message", json={"text": "¿Qué hora es en UTC según el snapshot? Responde en una línea.", "panel": "fx"}, timeout=30)
        r2 = s.post(f"{CHAT}/message", json={"text": "otra", "panel": "fx"}, timeout=30)
        assert r1.status_code == 200 and r2.status_code == 409
        while s.get(f"{CHAT}/jobs/{r1.json()['id']}", timeout=30).json()["status"] == "running":
            time.sleep(2)
        # apply → settings change + event recorded; second apply → 409
        r = s.post(f"{CHAT}/proposals/{p['id']}/apply", timeout=60)
        assert r.status_code == 200, r.text
        assert r.json()["proposal"]["status"] == "applied" and r.json()["event"]["role"] == "event" and "APLICÓ" in r.json()["event"]["content"]
        assert s.get(f"{API}/settings", timeout=30).json()["scan_interval_sec"] == target
        assert s.post(f"{CHAT}/proposals/{p['id']}/apply", timeout=30).status_code == 409
        # revert for the user
        assert s.put(f"{API}/settings", json={"scan_interval_sec": before}, timeout=30).status_code == 200
        ev = s.get(f"{API}/evolution", timeout=30).json()
        assert any(e["source"] == "chat" for e in ev["events"]), "el cambio aplicado desde el chat debe aparecer en Evolución"

    def test_discard_action_proposal(self, s):
        j = ask(s, "Propón un escaneo inmediato (acción scan) del bot cripto. Solo la propuesta.")
        assert j["status"] == "done"
        a = j["result"]["assistant"]
        assert a["proposals"], a
        p = a["proposals"][0]
        assert p["kind"] == "action" and p["action"] == "scan"
        r = s.post(f"{CHAT}/proposals/{p['id']}/discard", timeout=30)
        assert r.status_code == 200 and r.json()["proposal"]["status"] == "discarded" and "DESCARTÓ" in r.json()["event"]["content"]
        assert s.post(f"{CHAT}/proposals/{p['id']}/discard", timeout=30).status_code == 409
        assert s.post(f"{CHAT}/proposals/000000000000000000000000/discard", timeout=30).status_code == 404

    def test_history_persists(self, s):
        d = s.get(CHAT, timeout=30).json()
        roles = [m["role"] for m in d["messages"]]
        assert "user" in roles and "assistant" in roles and "event" in roles
        assert d["session"]["n_messages"] == len(d["messages"]) or d["session"]["n_messages"] >= len(d["messages"])
        assert d["pending"] == []

    def test_memory_crud(self, s):
        r = s.put(f"{CHAT}/memory", json={"notes": ["Prefiere respuestas cortas (test)", {"text": "Objetivo: $1.000/mes (test)", "ts": "2026-01-01T00:00:00+00:00"}, "  "]}, timeout=30)
        assert r.status_code == 200
        notes = r.json()["notes"]
        assert [n["text"] for n in notes] == ["Prefiere respuestas cortas (test)", "Objetivo: $1.000/mes (test)"]
        assert notes[1]["ts"] == "2026-01-01T00:00:00+00:00"
        assert s.get(f"{CHAT}/memory", timeout=30).json()["notes"] == notes
        assert s.get(CHAT, timeout=30).json()["memory"] == notes

    def test_summarize_and_new_conversation(self, s):
        r = s.post(f"{CHAT}/summarize", timeout=180)
        assert r.status_code == 200 and "summarized" in r.json() and "session" in r.json()
        mem_before = s.get(f"{CHAT}/memory", timeout=30).json()["notes"]
        r = s.post(f"{CHAT}/new", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["session"]["n_messages"] == 0 and d["messages"] == [] and d["session"]["summary"] == ""
        assert d["memory"] == mem_before, "la memoria duradera se conserva al empezar de cero"
        s.put(f"{CHAT}/memory", json={"notes": [n for n in mem_before if "(test)" not in n["text"]]}, timeout=30)
