from app.api.chat import _enforce_judge_verdict
from app.db.models import CorporateAnswer, JudgeVerdict, ProposedOccurrence, SourceCitation, SpecialistResult, TriageAnalysis


def test_rejected_judge_suppresses_unverified_specialist_fields_and_citations():
    answer = CorporateAnswer(answer="Há 300 kg conforme CONAMA 275.")
    citations = [SourceCitation(source_id="norm", title="Norma", corpus="regulatory", excerpt="300 kg")]
    specialist = SpecialistResult(
        proposed_occurrence=ProposedOccurrence(
            description="300 kg de resíduo não validado.",
            category="Plástico",
        ),
        triage_analysis=TriageAnalysis(
            tipo_material="Plástico",
            contaminacao="Baixa",
            quantidade_estimada="300 kg",
            confianca_ia=90,
            recomendacao_automatica="Validar com responsável.",
            mobile_summary="Plástico estimado; requer validação humana.",
        ),
    )
    judge = JudgeVerdict(approved=False, reason="A norma 275 e a quantidade 300 kg não têm suporte.")

    safe_answer, safe_citations, safe_specialist, safe_judge = _enforce_judge_verdict(
        answer, citations, specialist, judge
    )

    assert "300" not in safe_answer.answer
    assert "275" not in safe_answer.answer
    assert safe_answer.requires_human_validation is True
    assert safe_citations == []
    assert safe_specialist is None
    assert safe_judge.reason is not None
    assert "300" not in safe_judge.reason
    assert "275" not in safe_judge.reason
