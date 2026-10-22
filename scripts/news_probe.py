"""QA: runs one crypto news analysis against the real LLM and prints the raw answer + parse result (cost: 1 call)."""
import asyncio
import json
import sys
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
import ai_advisor  # noqa: E402
import news  # noqa: E402
from news import NewsAgent, _parse_json, SYSTEM  # noqa: E402


class _E:
    async def log(self, *a, **k):
        print("LOG", a)

    async def tg(self, *a, **k):
        pass


async def main():
    agent = NewsAgent(None, _E())
    heads = await agent.fetch_headlines()
    events = await agent.fetch_events()
    print("headlines", len(heads), "events", len(events))
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT"]
    lines = [f"- [{h['source']} · hace {news._age_min(h['published'])} min] {h['title']}" + (f" — {h['summary'][:120]}" if h['summary'] else "") for h in heads[:45]]
    ev = [f"- {e['time'][:16]} UTC · {e['title']} · impacto {e['impact']}" for e in events[:10]] or ["- ninguno en 72h"]
    prompt = (f"PARES ACTIVOS: {', '.join(symbols)}\n\nTITULARES (más recientes primero):\n" + "\n".join(lines) +
              "\n\nCALENDARIO MACRO USD (UTC):\n" + "\n".join(ev) +
              "\n\nDevuelve solo el JSON. Dentro de los textos no uses comillas dobles (usa comillas simples) ni saltos de línea.")
    print("prompt chars", len(prompt))
    chat = ai_advisor._chat(SYSTEM, "news")
    text = await ai_advisor._ask(chat, prompt)
    print("RAW LEN", len(text))
    print(text[:300])
    print("...")
    print(text[-400:])
    d = _parse_json(text)
    print("PARSED:", d is not None)
    if d is None:
        try:
            json.loads(text)
        except Exception as e:
            print("json error:", e)
    open("/tmp/news_raw.txt", "w").write(text)


asyncio.run(main())
