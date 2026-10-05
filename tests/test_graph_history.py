from contextlib import contextmanager
from langgraph.checkpoint.memory import MemorySaver

from app.ai.graph import build_volta_graph
from app.db.models import CorporateAnswer, JudgeVerdict, RouteDecision, RouteName, SourceCitation, SpecialistResult
from app.ai.prompts import ORCHESTRATOR_PROMPT


class FakeRag:
    def retrieve_for_route(self, route, message, tenant_id=None):
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

    def judge_result(self, specialist, evidence, data=None):
        return JudgeVerdict(approved=True)

    def format_answer(self, route, specialist, judge, direct_reply=None):
        self.received_verdict = judge
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


class FakeStandardsTeam(FakeTeam):
    def route(self, message):
        return RouteDecision(route=RouteName.STANDARDS, rationale="Teste")

    @contextmanager
    def collect_norm_citations(self):
        yield [SourceCitation(source_id="mma-1", title="Norma MMA", corpus="regulatory", excerpt="Ementa")]


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

    assert [item.source_id for item in result["evidence"]] == ["mma-1"]


class FakeRejectedTeam(FakeTeam):
    def judge_result(self, specialist, evidence, data=None):
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
    assert "requires_human_validation=true" in ORCHESTRATOR_PROMPT
    assert "números, normas ou afirmações contestados" in ORCHESTRATOR_PROMPT
