"""Iteration 41 – tolerant LLM JSON parsing (user log: «Agente de noticias: Respuesta IA no válida: {"market":{…"summary":"Bitcoin cae … por la aversi»).
Code fences, prose, raw newlines, unescaped inner double quotes, trailing commas and truncated answers must be repaired; the news agents back off
5 min after a failure instead of retrying (and paying) every minute."""
import sys
import pytest
sys.path.insert(0, "/app/backend")
from llm_json import parse_llm_json  # noqa: E402
import ai_advisor  # noqa: E402
import news  # noqa: E402
from fx import news as fx_news  # noqa: E402
from fx import ai as fx_ai  # noqa: E402

GOOD = '{"market":{"sentiment":-20,"risk":"MEDIO","summary":"Bitcoin cae"},"pairs":{"BTCUSDT":{"sentiment":-10,"risk":"MEDIO","note":"Cae"}},"alerts":[]}'


class TestParser:
    def test_plain_and_prose_and_fence(self):
        assert parse_llm_json(GOOD)["market"]["risk"] == "MEDIO"
        assert parse_llm_json("Claro, aquí tienes:\n" + GOOD + "\nEspero que ayude.")["pairs"]["BTCUSDT"]["note"] == "Cae"
        assert parse_llm_json("```json\n" + GOOD + "\n```")["alerts"] == []

    def test_inner_double_quotes_and_newlines(self):
        t = '{"market":{"summary":"El "halving" y la "aversión" al riesgo\npesan","risk":"ALTO"},"pairs":{"BTCUSDT":{"note":"Dijo "no" a todo"}}}'
        d = parse_llm_json(t)
        assert d["market"]["risk"] == "ALTO" and "'halving'" in d["market"]["summary"] and d["pairs"]["BTCUSDT"]["note"] == "Dijo 'no' a todo"

    def test_trailing_commas(self):
        assert parse_llm_json('{"market":{"summary":"x",},"pairs":{"A":{"note":"y"},},}')["pairs"]["A"]["note"] == "y"

    def test_truncated_answers_keep_complete_items(self):
        user_log = '{"market":{"sentiment":-20,"risk":"MEDIO","summary":"Bitcoin cae cerca de un 3% hasta la zona de 81.5K por la aversi'
        d = parse_llm_json(user_log)
        assert d["market"]["sentiment"] == -20 and d["market"]["risk"] == "MEDIO" and "summary" not in d["market"]
        d = parse_llm_json(GOOD[:-30] + ',"ETHUSDT":{"sentiment":-15,"risk":"ME')
        assert d["market"]["summary"] == "Bitcoin cae" and set(d["pairs"]) >= {"BTCUSDT"}
        d = parse_llm_json('{"market":{"risk":"ALTO","summary":"x"},"pairs":{},"alerts":[{"symbol":"MARKET","severity":"ALTA","title":"Guerra","why":"petr')
        assert d["alerts"][0]["title"] == "Guerra" and "why" not in d["alerts"][0]

    def test_no_object(self):
        assert parse_llm_json("No puedo responder.") is None and parse_llm_json("") is None and parse_llm_json(None) is None
        assert parse_llm_json("[1,2,3]") is None

    def test_news_uses_shared_parser_and_pipeline_tolerates_truncation(self):
        assert news._parse_json(GOOD) is not None and fx_news._parse_json is news._parse_json
        with pytest.raises(ValueError, match="Respuesta IA no válida"):
            ai_advisor.parse_json("nada", "test")
        d = fx_ai._parse('{"decision":"APROBAR","confidence":72,"reasoning":"Tendencia "fuerte" en 4h","risk_level":"MEDIO"}')
        assert d["decision"] == "APROBAR" and d["confidence"] == 72

    def test_backoff_after_failure(self):
        assert news.RETRY_AFTER_FAIL_SEC == 300 and fx_news.RETRY_AFTER_FAIL_SEC == 300
        a = news.NewsAgent(None, None)
        b = fx_news.FxNewsAgent(None, None)
        assert a._retry_at == 0.0 and b._retry_at == 0.0
