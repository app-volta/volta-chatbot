import asyncio
from io import BytesIO
from uuid import UUID

import pytest
from fastapi import HTTPException
from pydantic import SecretStr, ValidationError
from starlette.datastructures import Headers, UploadFile

from app.api import occurrences
from app.ai.visual_weight import EPA_SOURCE, VisualWeightAnalysis, calculate_visual_weight
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


@pytest.mark.parametrize(("case", "waste", "expected"), [
    ("flattened_cardboard", "papelao", 6.29),
    ("loose_pet_hdpe_bottles", "plastico", 1.90),
    ("food_waste", "organico", 27.47),
])
def test_visual_weight_uses_matching_epa_factor(case, waste, expected):
    data = _analysis().model_dump()
    data.update(waste_types=[waste], volume_liters=100, volume_reference="caixa de 100 litros identificada", density_case=case)
    result = calculate_visual_weight(VisualWeightAnalysis(**data))
    assert result.estimated_quantity_kg == expected
    assert "EPA" in result.report_text


@pytest.mark.parametrize("changes", [
    {"volume_liters": None},
    {"volume_reference": None},
    {"waste_types": ["outro"]},
    {"waste_types": ["papelao", "plastico"]},
])
def test_visual_weight_does_not_infer_when_evidence_is_missing(changes):
    data = _analysis().model_dump()
    data.update(waste_types=["papelao"], volume_liters=100, volume_reference="referência visível", density_case="flattened_cardboard")
    data.update(changes)
    assert calculate_visual_weight(VisualWeightAnalysis(**data)).estimated_quantity_kg is None


@pytest.mark.parametrize("volume", [-1, 0, float("inf"), float("nan")])
def test_visual_weight_rejects_invalid_volume(volume):
    with pytest.raises(ValidationError):
        VisualWeightAnalysis(**_analysis().model_dump(), volume_liters=volume)


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
        if self.schema is VisualWeightAnalysis:
            return VisualWeightAnalysis(**_analysis().model_dump())
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


def test_calculated_weight_reaches_judge_and_signed_response(monkeypatch):
    judge_inputs = []

    class StructuredModel(FakeStructuredModel):
        async def ainvoke(self, messages, **kwargs):
            if self.schema is VisualWeightAnalysis:
                data = _analysis().model_dump()
                data.update(waste_types=["papelao"], volume_liters=100, volume_reference="caixa de 100 litros", density_case="flattened_cardboard")
                return VisualWeightAnalysis(**data)
            judge_inputs.append(messages[0].content[0]["text"])
            return JudgeVerdict(approved=True)

    class Model(FakeModel):
        def with_structured_output(self, schema):
            return StructuredModel(schema)

    monkeypatch.setattr(occurrences, "get_settings", _settings)
    monkeypatch.setattr(occurrences, "ChatGoogleGenerativeAI", Model)
    identity = RequestIdentity(TENANT, USER)
    upload = UploadFile(BytesIO(b"fake-image"), filename="residuo.png", headers=Headers({"content-type": "image/png"}))
    result = asyncio.run(occurrences.predict_waste(upload, identity, FakeTelemetry()))
    assert '"estimated_quantity_kg":6.29' in judge_inputs[0]
    assert result.estimated_quantity_kg == 6.29
    assert EPA_SOURCE in result.report_text
    assert occurrences._has_valid_visual_provenance(result, identity, "provenance-test")


def test_rejected_visual_judge_suppresses_unverified_claims():
    identity = RequestIdentity(TENANT, USER)
    result = occurrences._finalize_visual_analysis(
        _analysis().model_copy(update={"estimated_quantity_kg": 300, "waste_types": ["metal"], "item_count": 2, "suggested_priority": "HIGH"}),
        JudgeVerdict(approved=False, reason="Peso sem escala visual."),
        identity,
        "provenance-test",
    )

    assert result.detected_waste_type == "Não confirmado pelo juiz"
    assert result.ai_contamination_level == "INDETERMINADO"
    assert result.estimated_quantity_kg is None
    assert result.waste_types == []
    assert result.item_count is None
    assert result.suggested_priority is None
    assert result.judge and result.judge.approved is False
    assert result.requires_human_validation is True


def test_visual_structured_fields_and_provenance():
    identity = RequestIdentity(TENANT, USER)
    analysis = _analysis().model_copy(update={"waste_types": ["papelao", "plastico"], "item_count": 3, "suggested_priority": "HIGH"})
    result = occurrences._finalize_visual_analysis(analysis, JudgeVerdict(approved=True), identity, "secret")
    assert result.waste_types == ["papelao", "plastico"]
    assert result.item_count == 3
    assert result.suggested_priority == "HIGH"
    assert occurrences._has_valid_visual_provenance(result, identity, "secret")
    tampered = result.model_copy(update={"item_count": 4})
    assert not occurrences._has_valid_visual_provenance(tampered, identity, "secret")


def test_legacy_visual_signature_and_omitted_new_fields():
    identity = RequestIdentity(TENANT, USER)
    result = occurrences._finalize_visual_analysis(_analysis(), JudgeVerdict(approved=True), identity, "secret")
    old_data = result.model_dump(exclude={"waste_types", "item_count", "suggested_priority"})
    old_data["provenance_token"] = occurrences._sign_visual_analysis(result, identity, "secret", legacy=True)
    assert occurrences._has_valid_visual_provenance(AnaliseResiduoIA(**old_data), identity, "secret")
    old_data["item_count"] = 3
    assert not occurrences._has_valid_visual_provenance(AnaliseResiduoIA(**old_data), identity, "secret")


def test_invalid_visual_types_rejected():
    for types in (["nenhum", "metal"], ["metal", "metal"], ["nao_reciclavel"]):
        with pytest.raises(ValidationError):
            AnaliseResiduoIA(**_analysis().model_dump(exclude={"waste_types"}), waste_types=types)


def test_unknown_contamination_is_not_presented_as_a_valid_level():
    result = occurrences._finalize_visual_analysis(
        _analysis().model_copy(update={"ai_contamination_level": "desconhecido"}),
        JudgeVerdict(approved=True), RequestIdentity(TENANT, USER), "secret",
    )
    assert result.ai_contamination_level == "INDETERMINADO"


def test_accented_contamination_is_normalized():
    result = occurrences._finalize_visual_analysis(
        _analysis().model_copy(update={"ai_contamination_level": "médio"}),
        JudgeVerdict(approved=True), RequestIdentity(TENANT, USER), "secret",
    )
    assert result.ai_contamination_level == "MEDIO"


def test_approved_visual_weight_estimate_is_preserved():
    identity = RequestIdentity(TENANT, USER)
    analysis = _analysis().model_copy(update={
        "estimated_quantity_kg": 5.5,
        "report_text": "Peso aproximado de 5,5 kg, sujeito a confirmação por pesagem.",
    })

    result = occurrences._finalize_visual_analysis(
        analysis, JudgeVerdict(approved=True), identity, "provenance-test"
    )

    assert result.estimated_quantity_kg == 5.5
    assert "aproximado" in result.report_text
    assert occurrences._has_valid_visual_provenance(result, identity, "provenance-test")


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
