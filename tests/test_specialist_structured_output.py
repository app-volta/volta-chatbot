import json
from contextvars import ContextVar

from langchain_core.messages import AIMessage

from app.ai.agents import AgentTeam
from app.db.models import SpecialistResult


class FakeTelemetry:
    def __init__(self):
        self.records = []

    def timer(self):
        return 0

    def record_agent(self, *args, **kwargs):
        self.records.append((args, kwargs))


class FakeExecutor:
    def __init__(self, content=None, *, failure=None, before=None):
        self.content = content
        self.failure = failure
        self.before = before
        self.config = None
        self.input = None

    def invoke(self, _input, *, config=None):
        self.config = config
        self.input = _input
        if self.before:
            self.before()
        if self.failure:
            raise self.failure
        return {"messages": [AIMessage(content=self.content)]}


class FakeStructuredOutput:
    def __init__(self, value):
        self.value = value

    def invoke(self, _prompt, config=None):
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class FakeModel:
    def __init__(self, value):
        self.value = value
        self.methods = []

    def with_structured_output(self, _schema, **kwargs):
        self.methods.append(kwargs.get("method"))
        return FakeStructuredOutput(self.value)


def _team():
    team = object.__new__(AgentTeam)
    team.telemetry = FakeTelemetry()
    team._norm_citation_sink = ContextVar("test_norm_citations", default=None)
    team._rag_citation_sink = ContextVar("test_rag_citations", default=None)
    return team


def test_structured_specialist_response_skips_conversion_fallback(monkeypatch):
    payload = {
        "proposed_occurrence": {
            "description": "Papelão acumulado no setor B.",
            "category": "Papelão",
            "requires_sanitization": False,
        },
        "metrics_summary": None,
        "triage_analysis": {
            "tipo_material": "Papelão",
            "contaminacao": "Baixa",
            "quantidade_estimada": "10 kg",
            "unidades": None,
            "confianca_ia": 90,
            "recomendacao_automatica": "Armazenar em local seco.",
            "mobile_summary": "Papelão estimado para armazenamento seco.",
        },
    }
    team = _team()
    monkeypatch.setattr(
        team,
        "_structured_specialist",
        lambda _schema: (_ for _ in ()).throw(AssertionError("fallback chamado")),
        raising=False,
    )

    executor = FakeExecutor(json.dumps(payload, ensure_ascii=False))
    result = team._invoke_specialist(
        "triage",
        executor,
        "fake:model",
        "payload",
    )

    assert isinstance(result, SpecialistResult)
    assert result.proposed_occurrence.category == "Papelão"
    assert result.triage_analysis.confianca_ia == 90
    assert result.triage_analysis.mobile_summary == "Papelão estimado para armazenamento seco."
    assert executor.config["recursion_limit"] == 12


def test_invalid_specialist_json_uses_primary_structured_output():
    expected = SpecialistResult(metrics_summary={"answer": "Resultado"})
    team = _team()
    team._specialist_primary_model = FakeModel(expected)

    result = team._invoke_specialist("standards", FakeExecutor("not-json"), "fake:model", "payload")

    assert result == expected
    assert team._specialist_primary_model.methods == [None]


def test_failed_primary_restarts_fallback_with_clean_payload_and_citations():
    team = _team()
    base_citation, primary_citation, fallback_citation = object(), object(), object()
    citations = [base_citation]
    rag_citations = [base_citation]
    team._norm_citation_sink.set(citations)
    team._rag_citation_sink.set(rag_citations)
    payload = '{"question":"vidro"}'
    primary = FakeExecutor(
        failure=RuntimeError("provider error"),
        before=lambda: (citations.append(primary_citation), rag_citations.append(primary_citation)),
    )
    fallback = FakeExecutor(
        SpecialistResult(metrics_summary={"answer": "Resultado"}).model_dump_json(),
        before=lambda: (citations.append(fallback_citation), rag_citations.append(fallback_citation)),
    )

    result = team._invoke_specialist(
        "standards", primary, "gemini:test", payload,
        fallback_executor=fallback, fallback_model="groq:test",
    )

    assert result.metrics_summary == {"answer": "Resultado"}
    assert fallback.input == {"messages": [("user", payload)]}
    assert citations == [base_citation, fallback_citation]
    assert rag_citations == [base_citation, fallback_citation]
    assert len(team.telemetry.records) == 1
    assert team.telemetry.records[0][1]["fallback_used"] is True


def test_failed_primary_parser_restarts_with_groq_json_schema():
    expected = SpecialistResult(metrics_summary={"answer": "Resultado"})
    team = _team()
    team._specialist_primary_model = FakeModel(RuntimeError("primary parse failed"))
    team._specialist_fallback_model = FakeModel(expected)
    payload = '{"question":"vidro"}'
    fallback = FakeExecutor("not-json")

    result = team._invoke_specialist(
        "standards",
        FakeExecutor("not-json"),
        "gemini:test",
        payload,
        fallback_executor=fallback,
        fallback_model="groq:test",
    )

    assert result == expected
    assert team._specialist_fallback_model.methods == ["json_schema"]
    assert fallback.input == {"messages": [("user", payload)]}
