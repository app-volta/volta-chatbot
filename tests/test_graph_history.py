from langgraph.checkpoint.memory import MemorySaver

from app.ai.graph import build_volta_graph
from app.db.models import CorporateAnswer, JudgeVerdict, RouteDecision, RouteName, SpecialistResult


class FakeRag:
    def retrieve_for_route(self, route, message, tenant_id=None):
        return []


class FakeTeam:
    def __init__(self):
        self.received_history = None

    def route(self, message):
        return RouteDecision(route=RouteName.TRIAGE, rationale="Teste")

    def specialist(self, route, message, evidence, data=None, *, tenant_id, history=None):
        self.received_history = history
        return SpecialistResult(metrics_summary={"answer": "Resposta de teste"})

    def judge_result(self, specialist, evidence, data=None):
        return JudgeVerdict(approved=True)

    def format_answer(self, route, specialist, judge, direct_reply=None):
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
