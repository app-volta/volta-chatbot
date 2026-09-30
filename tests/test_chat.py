import asyncio
import time

import anyio
from fastapi import FastAPI
from langgraph.errors import GraphRecursionError
from httpx import ASGITransport, AsyncClient

from app.api.chat import _enforce_judge_verdict, _mongo_call
from app.api.chat import router as chat_router
from app.core.auth import RequestIdentity, get_current_identity
from app.core.dependencies import get_graph, get_sessions, get_telemetry
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


class FakeSessions:
    def __init__(self, delay=0):
        self.delay = delay

    def _wait(self):
        if self.delay:
            time.sleep(self.delay)

    def ensure_session_owner(self, *_args):
        self._wait()

    def audit_security_event(self, *_args):
        self._wait()

    def recent_history(self, *_args):
        self._wait()
        return []

    def append_message(self, *_args):
        self._wait()


class FakeChatTelemetry:
    def __init__(self):
        self.requests = []

    def record_request(self, *args, **kwargs):
        self.requests.append((args, kwargs))

    def record_judge(self, *_args, **_kwargs):
        pass


class FakeChatGraph:
    def __init__(self, delay=0, error=None):
        self.delay = delay
        self.error = error
        self.config = None

    def invoke(self, _input, *, config):
        self.config = config
        if self.error:
            raise self.error
        if self.delay:
            time.sleep(self.delay)
        return {
            "corporate_answer": {"answer": "Resposta direta."},
            "route": "direct",
            "evidence": [],
        }


def _chat_test_app(sessions, graph, telemetry):
    app = FastAPI()
    app.include_router(chat_router, prefix="/v1/chat")
    app.dependency_overrides[get_current_identity] = lambda: RequestIdentity(
        tenant_id="tenant", user_id="user"
    )
    app.dependency_overrides[get_sessions] = lambda: sessions
    app.dependency_overrides[get_graph] = lambda: graph
    app.dependency_overrides[get_telemetry] = lambda: telemetry
    return app


def test_chat_offloads_sync_mongo_calls_and_limits_graph_steps():
    async def run():
        sessions = FakeSessions(delay=0.04)
        graph = FakeChatGraph(delay=0.04)
        telemetry = FakeChatTelemetry()
        app = _chat_test_app(sessions, graph, telemetry)
        stop_heartbeat = asyncio.Event()
        ticks = 0

        async def heartbeat():
            nonlocal ticks
            while not stop_heartbeat.is_set():
                ticks += 1
                await asyncio.sleep(0.005)

        heartbeat_task = asyncio.create_task(heartbeat())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/v1/chat", json={"session_id": "s-1", "message": "oi"})
        stop_heartbeat.set()
        await heartbeat_task

        assert response.status_code == 200
        assert ticks >= 10
        assert graph.config["recursion_limit"] == 25

    asyncio.run(run())


def test_cancelled_mongo_call_finishes_before_cancellation_propagates():
    async def run():
        completed = False

        def slow_write():
            nonlocal completed
            time.sleep(0.04)
            completed = True

        started = time.perf_counter()
        with anyio.move_on_after(0.005) as scope:
            await _mongo_call(slow_write)

        assert scope.cancel_called
        assert completed
        assert time.perf_counter() - started >= 0.04

    asyncio.run(run())


def test_chat_graph_recursion_limit_is_reported_as_service_error():
    async def run():
        telemetry = FakeChatTelemetry()
        graph = FakeChatGraph(error=GraphRecursionError("recursion limit reached"))
        app = _chat_test_app(FakeSessions(), graph, telemetry)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/v1/chat", json={"session_id": "s-1", "message": "oi"})
        assert response.status_code == 503
        assert graph.config["recursion_limit"] == 25
        assert telemetry.requests[-1][0][2] == "error"

    asyncio.run(run())


def test_chat_provider_timeout_is_reported_and_counted_as_error():
    async def run():
        telemetry = FakeChatTelemetry()
        app = _chat_test_app(FakeSessions(), FakeChatGraph(error=TimeoutError()), telemetry)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/v1/chat", json={"session_id": "s-1", "message": "oi"})
        assert response.status_code == 503
        assert telemetry.requests[-1][0][2] == "error"

    asyncio.run(run())
