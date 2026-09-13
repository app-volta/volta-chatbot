from pydantic import SecretStr

from app.api import occurrences
from app.core.auth import RequestIdentity
from app.core.config import Settings
from app.db.models import AIManagementSummary


class FakeRepository:
    def __init__(self):
        self.tenant_id = None

    def get_recent_incidents(self, limit, tenant_id):
        self.tenant_id = tenant_id
        return [{
            "employee_description": "Contato: alice@example.com",
            "contamination_level": "BAIXA",
            "estimated_quantity": 10,
            "priority": "MEDIA",
        }]


class FakeTelemetry:
    def __init__(self):
        self.response_text = None

    def timer(self):
        return 0.0

    def record_agent(self, agent, model, started, prompt, response, **kwargs):
        self.response_text = response


class FakeStructuredModel:
    def __init__(self):
        self.prompt = None

    def invoke(self, messages):
        self.prompt = messages[0].content
        return AIManagementSummary(
            problema_analisado="Há registros recentes de descarte.",
            recomendacoes=["Revisar a segregação na origem."],
        )


class FakeModel:
    structured = FakeStructuredModel()

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def with_structured_output(self, schema):
        assert schema is AIManagementSummary
        return self.structured


def test_ai_summary_calls_structured_model_with_scoped_sanitized_data(monkeypatch):
    repository = FakeRepository()
    telemetry = FakeTelemetry()
    settings = Settings(_env_file=None, gemini_api_key=SecretStr("test-key"), gemini_model="gemini-test")
    monkeypatch.setattr(occurrences, "get_settings", lambda: settings)
    monkeypatch.setattr(occurrences, "ChatGoogleGenerativeAI", FakeModel)

    result = occurrences.generate_ai_management_summary(
        RequestIdentity(
            tenant_id="550e8400-e29b-41d4-a716-446655440000",
            user_id="550e8400-e29b-41d4-a716-446655440002",
        ),
        repository,
        telemetry,
    )

    assert result.problema_analisado == "Há registros recentes de descarte."
    assert repository.tenant_id == "550e8400-e29b-41d4-a716-446655440000"
    assert "alice@example.com" not in FakeModel.structured.prompt
    assert "[EMAIL_1]" in FakeModel.structured.prompt
    assert telemetry.response_text
