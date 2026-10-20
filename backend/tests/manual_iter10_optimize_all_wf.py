# Manual (not collected by pytest): runs 'Optimizar todo con IA' once, checks result.optimizer[*].walk_forward, restores settings
import requests, os, time, json
from dotenv import load_dotenv
load_dotenv('/app/frontend/.env'); B = os.environ['REACT_APP_BACKEND_URL']
t = requests.post(B + '/api/auth/login', json={"password": "BlackCat2233@"}).json()['token']; H = {"Authorization": "Bearer " + t}
before = requests.get(B + '/api/settings', headers=H).json()
r = requests.post(B + '/api/ai/optimize-all', headers=H); print("start", r.status_code)
for _ in range(55):
    time.sleep(5); j = requests.get(B + '/api/ai/optimize-all', headers=H).json()
    if j['status'] != 'running': break
print(j['status'], j.get('error'))
res = j.get('result') or {}
for r in res.get('optimizer', []):
    w = r.get('walk_forward'); print(r['symbol'], None if w is None else (w['verdict'], w['wfe'], w['folds'], w['oos']['trades'], set(w) >= {"verdict", "wfe", "oos", "folds"}))
print("applied:", json.dumps(res.get('applied'))[:400])
after = requests.get(B + '/api/settings', headers=H).json()
diff = {k: before[k] for k in before if k != 'bot_running' and before.get(k) != after.get(k)}
print("changed keys:", list(diff))
if diff:
    rr = requests.put(B + '/api/settings', headers=H, json=diff); print("restore", rr.status_code)
    a2 = requests.get(B + '/api/settings', headers=H).json(); print("still diff:", [k for k in diff if a2.get(k) != before[k]])
