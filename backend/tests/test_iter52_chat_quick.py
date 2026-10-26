# Quick backend checks for chat IA expert (iteration 52) - errors / guards
import os, time, pytest, requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")


@pytest.fixture(scope="module")
def s():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": "BlackCat2233@"})
    assert r.status_code == 200, r.text
    tok = r.json().get("token") or r.json().get("access_token")
    ss = requests.Session()
    ss.headers.update({"Authorization": f"Bearer {tok}"})
    return ss


def test_no_token_401():
    assert requests.get(f"{BASE_URL}/api/chat").status_code == 401


def test_get_chat(s):
    r = s.get(f"{BASE_URL}/api/chat")
    assert r.status_code == 200
    d = r.json()
    assert "messages" in d and "memory" in d


def test_empty_text_422(s):
    assert s.post(f"{BASE_URL}/api/chat/message", json={"text": "", "panel": "crypto"}).status_code == 422


def test_job_404(s):
    assert s.get(f"{BASE_URL}/api/chat/jobs/inexistente").status_code == 404


def test_concurrent_409_and_resolved_409(s):
    r1 = s.post(f"{BASE_URL}/api/chat/message", json={"text": "Di solo 'ok'.", "panel": "crypto"})
    assert r1.status_code == 200, r1.text
    jid = r1.json()["id"]
    r2 = s.post(f"{BASE_URL}/api/chat/message", json={"text": "otro", "panel": "crypto"})
    assert r2.status_code == 409
    for _ in range(80):
        j = s.get(f"{BASE_URL}/api/chat/jobs/{jid}").json()
        if j["status"] != "running":
            break
        time.sleep(2)
    assert j["status"] != "running"
    # resolved proposal 409: find any non-pending proposal in history
    msgs = s.get(f"{BASE_URL}/api/chat").json()["messages"]
    resolved = [p for m in msgs for p in (m.get("proposals") or []) if p.get("status") != "pending"]
    if not resolved:
        pytest.skip("no resolved proposals in current conversation")
    assert s.post(f"{BASE_URL}/api/chat/proposals/{resolved[0]['id']}/discard").status_code == 409


def test_unknown_proposal(s):
    r = s.post(f"{BASE_URL}/api/chat/proposals/nope/apply")
    assert r.status_code in (400, 404)  # 400 = invalid ObjectId
