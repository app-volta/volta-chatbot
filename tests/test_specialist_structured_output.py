import json

from langchain_core.messages import AIMessage

from app.ai.agents import AgentTeam
from app.db.models import SpecialistResult


class FakeTelemetry:
    def timer(self):
        return 0

    def record_agent(self, *args, **kwargs):
        pass


class FakeExecutor:
    def __init__(self, content):
        self.content = content
        self.config = None

    def invoke(self, _input, *, config=None):
        self.config = config
        return {"messages": [AIMessage(content=self.content)]}


def _team():
    team = object.__new__(AgentTeam)
    team.telemetry = FakeTelemetry()
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


def test_invalid_specialist_json_uses_structured_output_fallback(monkeypatch):
    expected = SpecialistResult(metrics_summary={"answer": "Resultado"})

    class FakeStructuredOutput:
        def invoke(self, _prompt):
            return expected

    team = _team()
    monkeypatch.setattr(team, "_structured_specialist", lambda _schema: FakeStructuredOutput(), raising=False)

    result = team._invoke_specialist("standards", FakeExecutor("not-json"), "fake:model", "payload")

    assert result == expected
