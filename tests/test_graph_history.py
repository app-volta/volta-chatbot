from contextlib import contextmanager
from langgraph.checkpoint.memory import MemorySaver

from app.ai.graph import build_volta_graph
from app.db.models import CorporateAnswer, JudgeVerdict, RouteDecision, RouteName, SourceCitation, SpecialistResult
from app.ai.prompts import ORCHESTRATOR_PROMPT


class FakeRag:
    def retrieve_for_route(self, route, message, tenant_id=None, user_id=None):
        return []


class FakeTeam:
    def __init__(self):
        self.received_history = None
        self.received_verdict = None

    def route(self, message):
        return RouteDecision(route=RouteName.TRIAGE, rationale="Teste")

    def specialist(self, route, message, evidence, data=None, *, history=None):
        self.received_history = history
        return SpecialistResult(metrics_summary={"answer": "Resposta de teste"})

    def judge_result(self, specialist, evidence, data=None, *, route=None, question=None):
        self.received_route = route
        self.received_question = question
        return JudgeVerdict(approved=True)

    @contextmanager
    def collect_rag_citations(self):
        yield []

    def format_answer(self, route, specialist, judge, direct_reply=None, *, question=None):
        self.received_verdict = judge
        self.received_format_question = question
        return CorporateAnswer(answer="Resposta de teste")


def test_graph_passes_prior_session_history_to_specialist():
    team = FakeTeam()
    graph = build_volta_graph(team, FakeRag(), MemorySaver())
    history = [{"role": "user", "content": "A ocorrência anterior era no setor A."}]

    graph.invoke(
        {
            "messages": [{"role": "user", "content": "Qual a recomendação agora?"}],
            "request_id": "request-1",
            "user_id": "user-1",
            "tenant_id": "tenant-1",
            "session_id": "session-1",
            "input_text": "Qual a recomendação agora?",
            "history": history,
        },
        config={"configurable": {"thread_id": "session-1"}},
    )

    assert team.received_history == history
    assert team.received_question == "Qual a recomendação agora?"
    assert team.received_format_question == "Qual a recomendação agora?"


class FakeStandardsTeam(FakeTeam):
    def route(self, message):
        return RouteDecision(route=RouteName.STANDARDS, rationale="Teste")

    @contextmanager
    def collect_norm_citations(self):
        yield [SourceCitation(source_id="mma-1", title="Norma MMA", corpus="regulatory", excerpt="Ementa")]

    @contextmanager
    def collect_rag_citations(self):
        yield [SourceCitation(source_id="rag-1", title="Guia", corpus="operational", excerpt="Orientação")]


def test_graph_adds_mcp_norm_citations_to_response_evidence():
    graph = build_volta_graph(FakeStandardsTeam(), FakeRag(), MemorySaver())
    result = graph.invoke(
        {
            "messages": [{"role": "user", "content": "Qual norma se aplica?"}],
            "request_id": "request-2",
            "user_id": "user-1",
            "tenant_id": "tenant-1",
            "session_id": "session-2",
            "input_text": "Qual norma se aplica?",
        },
        config={"configurable": {"thread_id": "session-2"}},
    )

    assert [item.source_id for item in result["evidence"]] == ["rag-1", "mma-1"]


class FakeRejectedTeam(FakeTeam):
    def judge_result(self, specialist, evidence, data=None, *, route=None, question=None):
        self.received_route = route
        return JudgeVerdict(approved=False, reason="Rascunho contém status sem fonte.")


def test_graph_passes_rejected_verdict_to_orchestrator():
    team = FakeRejectedTeam()
    graph = build_volta_graph(team, FakeRag(), MemorySaver())
    result = graph.invoke(
        {
            "messages": [{"role": "user", "content": "Explique a norma."}],
            "request_id": "request-3",
            "user_id": "user-1",
            "tenant_id": "tenant-1",
            "session_id": "session-3",
            "input_text": "Explique a norma.",
        },
        config={"configurable": {"thread_id": "session-3"}},
    )

    assert result["judge"].approved is False
    assert team.received_verdict.approved is False
    assert team.received_verdict.reason == "Rascunho contém status sem fonte."
    assert "judge.reason" in ORCHESTRATOR_PROMPT
    assert "use judge.reason para localizar a lacuna" in ORCHESTRATOR_PROMPT


def test_evidence_merge_preserves_distinct_chunks_from_same_source():
    from app.ai.graph import _merge_evidence

    first = SourceCitation(
        source_id="guide", title="Guia", corpus="regulatory", location="página web", excerpt="Primeiro trecho"
    )
    second = SourceCitation(
        source_id="guide", title="Guia", corpus="regulatory", location="página web", excerpt="Segundo trecho"
    )

    assert _merge_evidence([first], [second]) == [first, second]


class FakeStandardsNeedsReviewTeam(FakeRejectedTeam):
    def route(self, message):
        return RouteDecision(route=RouteName.STANDARDS, rationale="Teste")

    @contextmanager
    def collect_norm_citations(self):
        yield []

    def format_answer(self, route, specialist, judge, direct_reply=None, *, question=None):
        return CorporateAnswer(answer="A decisão requer análise técnica.", requires_human_validation=True)


def test_rejected_standards_keeps_explicit_human_validation_requirement():
    graph = build_volta_graph(FakeStandardsNeedsReviewTeam(), FakeRag(), MemorySaver())
    result = graph.invoke(
        {
            "messages": [{"role": "user", "content": "Posso aplicar este procedimento na planta?"}],
            "request_id": "request-standards-review",
            "user_id": "user-1",
            "tenant_id": "tenant-1",
            "session_id": "session-standards-review",
            "input_text": "Posso aplicar este procedimento na planta?",
        },
        config={"configurable": {"thread_id": "session-standards-review"}},
    )

    assert result["judge"].approved is False
    assert result["corporate_answer"].requires_human_validation is True
    assert "Validação obrigatória" in result["corporate_answer"].answer


class AlternatingTeam(FakeTeam):
    def route(self, message):
        if message == "primeiro turno":
            return RouteDecision(route=RouteName.TRIAGE, rationale="Teste")
        return RouteDecision(route=RouteName.DIRECT, rationale="Teste", direct_reply="Olá.")

    def format_answer(self, route, specialist, judge, direct_reply=None, *, question=None):
        self.received_verdict = judge
        self.received_specialist = specialist
        return CorporateAnswer(answer=direct_reply or "Resposta de teste")


def test_graph_clears_specialist_judge_and_evidence_between_turns():
    team = AlternatingTeam()
    graph = build_volta_graph(team, FakeRag(), MemorySaver())
    config = {"configurable": {"thread_id": "session-stale"}}

    graph.invoke(
        {
            "messages": [{"role": "user", "content": "primeiro turno"}],
            "request_id": "request-1",
            "user_id": "user-1",
            "tenant_id": "tenant-1",
            "session_id": "session-stale",
            "input_text": "primeiro turno",
        },
        config=config,
    )
    result = graph.invoke(
        {
            "messages": [{"role": "user", "content": "segundo turno"}],
            "request_id": "request-2",
            "user_id": "user-1",
            "tenant_id": "tenant-1",
            "session_id": "session-stale",
            "input_text": "segundo turno",
        },
        config=config,
    )

    assert result["route"] == RouteName.DIRECT.value
    assert result["specialist"] is None
    assert result["judge"] is None
    assert result["evidence"] == []
    assert team.received_specialist is None
    assert team.received_verdict is None
