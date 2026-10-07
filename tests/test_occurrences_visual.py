import asyncio
from io import BytesIO
from uuid import UUID

import pytest
from fastapi import HTTPException
from pydantic import SecretStr
from starlette.datastructures import Headers, UploadFile

from app.api import occurrences
from app.core.auth import RequestIdentity
from app.core.config import Settings
from app.db.models import AnaliseResiduoIA, JudgeVerdict, OccurrenceDraftCreate
from app.db.storage import DuplicateAnalysisError


TENANT = "550e8400-e29b-41d4-a716-446655440001"
USER = "550e8400-e29b-41d4-a716-446655440002"
DRAFT = UUID("550e8400-e29b-41d4-a716-446655440003")


def _analysis() -> AnaliseResiduoIA:
    return AnaliseResiduoIA(
        detected_waste_type="Papelão",
        ai_contamination_level="BAIXO",
        estimated_quantity_kg=None,
        recommendations="Segregar e solicitar avaliação técnica.",
        report_text="Material compatível visualmente com papelão.",
        mobile_summary="Possível papelão; aguarde validação técnica.",
    )


class FakeTelemetry:
    def __init__(self):
        self.agents = []

    @staticmethod
    def timer():
        return 0.0

    def record_agent(self, agent, *_args, **_kwargs):
        self.agents.append(agent)


class FakeStructuredModel:
    def __init__(self, schema):
        self.schema = schema

    async def ainvoke(self, _messages, **_kwargs):
        if self.schema is AnaliseResiduoIA:
            return _analysis()
        if self.schema is JudgeVerdict:
            return JudgeVerdict(approved=True, reason="Afirmações limitadas ao conteúdo visível.")
        raise AssertionError(f"Schema inesperado: {self.schema}")


class FakeModel:
    def __init__(self, **_kwargs):
        pass

    def with_structured_output(self, schema):
        return FakeStructuredModel(schema)


class FakeRepository:
    def __init__(self):
        self.kwargs = None

    def create_occurrence_draft(self, **kwargs):
        self.kwargs = kwargs
        return DRAFT


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        gemini_api_key=SecretStr("gemini-test"),
        JWT_KEY="provenance-test",
    )


def test_visual_prediction_is_judged_guarded_and_signed(monkeypatch):
    monkeypatch.setattr(occurrences, "get_settings", _settings)
    monkeypatch.setattr(occurrences, "ChatGoogleGenerativeAI", FakeModel)
    identity = RequestIdentity(TENANT, USER)
    telemetry = FakeTelemetry()
    upload = UploadFile(
        BytesIO(b"fake-image"),
        filename="residuo.png",
        headers=Headers({"content-type": "image/png"}),
    )

    result = asyncio.run(occurrences.predict_waste(upload, identity, telemetry))

    assert result.requires_human_validation is True
    assert result.judge == JudgeVerdict(approved=True, reason="Afirmações limitadas ao conteúdo visível.")
    assert "responsável técnico" in result.report_text
    assert result.analysis_id is not None
    assert result.generated_at is not None
    assert occurrences._has_valid_visual_provenance(
        result,
        identity,
        _settings().jwt_key.get_secret_value(),
    )
    assert telemetry.agents == ["visual_triage", "visual_judge"]


def test_rejected_visual_judge_suppresses_unverified_claims():
    identity = RequestIdentity(TENANT, USER)
    result = occurrences._finalize_visual_analysis(
        _analysis().model_copy(update={"estimated_quantity_kg": 300}),
        JudgeVerdict(approved=False, reason="Peso sem escala visual."),
        identity,
        "provenance-test",
    )

    assert result.detected_waste_type == "Não confirmado pelo juiz"
    assert result.ai_contamination_level == "INDETERMINADO"
    assert result.estimated_quantity_kg is None
    assert result.judge and result.judge.approved is False
    assert result.requires_human_validation is True


def test_draft_requires_untampered_server_provenance(monkeypatch):
    monkeypatch.setattr(occurrences, "get_settings", _settings)
    identity = RequestIdentity(TENANT, USER)
    analysis = occurrences._finalize_visual_analysis(
        _analysis(),
        JudgeVerdict(approved=True),
        identity,
        _settings().jwt_key.get_secret_value(),
    )
    repository = FakeRepository()
    payload = OccurrenceDraftCreate(area_id=DRAFT, ai_data=analysis)

    response = occurrences.create_occurrence_draft(payload, identity, repository)

    assert response.draft_id == DRAFT
    assert "provenance_token" not in repository.kwargs["ai_data"]
    assert repository.kwargs["ai_data"]["analysis_id"] == analysis.analysis_id
    assert repository.kwargs["ai_data"]["generated_at"] == analysis.generated_at

    tampered = payload.model_copy(update={
        "ai_data": analysis.model_copy(update={"estimated_quantity_kg": 999}),
    })
    with pytest.raises(HTTPException) as exc:
        occurrences.create_occurrence_draft(tampered, identity, repository)
    assert exc.value.status_code == 422


def test_replayed_visual_analysis_returns_conflict(monkeypatch):
    monkeypatch.setattr(occurrences, "get_settings", _settings)
    identity = RequestIdentity(TENANT, USER)
    analysis = occurrences._finalize_visual_analysis(
        _analysis(), JudgeVerdict(approved=True), identity, _settings().jwt_key.get_secret_value()
    )

    class ReplayedRepository(FakeRepository):
        def create_occurrence_draft(self, **_kwargs):
            raise DuplicateAnalysisError("duplicate")

    with pytest.raises(HTTPException) as exc:
        occurrences.create_occurrence_draft(
            OccurrenceDraftCreate(area_id=DRAFT, ai_data=analysis), identity, ReplayedRepository()
        )

    assert exc.value.status_code == 409


def test_draft_rejects_analysis_rejected_by_judge(monkeypatch):
    monkeypatch.setattr(occurrences, "get_settings", _settings)
    identity = RequestIdentity(TENANT, USER)
    rejected = occurrences._finalize_visual_analysis(
        _analysis(), JudgeVerdict(approved=False), identity, _settings().jwt_key.get_secret_value()
    )

    with pytest.raises(HTTPException) as exc:
        occurrences.create_occurrence_draft(
            OccurrenceDraftCreate(area_id=DRAFT, ai_data=rejected), identity, FakeRepository()
        )

    assert exc.value.status_code == 422
