"""Métricas operacionais e estimativas de custo para a rubrica de SRE."""

from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import logging
from threading import Lock
from time import perf_counter

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from app.core.config import Settings

REQUESTS = Counter("volta_requests_total", "Requisições do VOLTA", ["route", "status"])
ERRORS = Counter("volta_errors_total", "Erros do VOLTA", ["component"])
AGENT_LATENCY = Histogram("volta_agent_latency_seconds", "Latência por agente", ["agent"])
TOTAL_LATENCY = Histogram("volta_total_latency_seconds", "Latência ponta a ponta", buckets=(0.25, 0.5, 1, 2, 5, 10, 20, 30, 60, 120, 180))
ESTIMATED_COST = Counter("volta_estimated_cost_usd_total", "Custo estimado de inferência", ["model"])
JUDGE_RESULTS = Counter("volta_judge_results_total", "Resultados do agente juiz", ["approved"])
HUMAN_INTERVENTIONS = Counter(
    "volta_human_interventions_total",
    "Casos encaminhados para validação humana",
    ["reason"],
)
FALLBACKS = Counter("volta_fallbacks_total", "Fallbacks de provedor utilizados", ["agent", "provider"])
CHAT_COST = Counter("volta_chat_estimated_cost_usd_total", "Custo estimado das mensagens concluídas", ["route", "status"])
logger = logging.getLogger(__name__)


@dataclass
class AgentMeasurement:
    calls: int = 0
    errors: int = 0
    total_latency_seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    fallback_calls: int = 0
    fallback_observations: int = 0


@dataclass
class ChatMeasurement:
    estimated_cost_usd: float = 0.0


class Observability:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = Lock()
        self._agents: dict[str, AgentMeasurement] = defaultdict(AgentMeasurement)
        self._resolved_cases = 0
        self._requests = 0
        self._request_errors = 0
        self._request_latency = 0.0
        self._chat_cost = 0.0
        self._request_cost: ContextVar[ChatMeasurement | None] = ContextVar("chat_measurement", default=None)

    @contextmanager
    def chat_request(self):
        """AnyIO/LangGraph propagate the context; each message owns its accumulator."""
        token = self._request_cost.set(ChatMeasurement())
        try:
            yield
        finally:
            self._request_cost.reset(token)

    @staticmethod
    def timer() -> float:
        return perf_counter()

    def _price(self, model: str, input_tokens: int, output_tokens: int) -> float:
        if "groq" in model.lower() or "llama" in model.lower():
            return (input_tokens * self.settings.groq_input_usd_per_million + output_tokens * self.settings.groq_output_usd_per_million) / 1_000_000
        return (input_tokens * self.settings.gemini_input_usd_per_million + output_tokens * self.settings.gemini_output_usd_per_million) / 1_000_000

    def record_agent(
        self,
        agent: str,
        model: str,
        started_at: float,
        prompt_text: str,
        response_text: str,
        failed: bool = False,
        fallback_used: bool | None = None,
    ) -> None:
        latency = perf_counter() - started_at
        # Approximation only: excludes tool loops, retries, embeddings and image tokens.
        input_tokens = max(1, len(prompt_text) // 4)
        output_tokens = max(1, len(response_text) // 4)
        cost = self._price(model, input_tokens, output_tokens)
        with self._lock:
            measurement = self._agents[agent]
            measurement.calls += 1
            measurement.errors += int(failed)
            measurement.total_latency_seconds += latency
            measurement.input_tokens += input_tokens
            measurement.output_tokens += output_tokens
            measurement.estimated_cost_usd += cost
            measurement.fallback_calls += int(bool(fallback_used))
            measurement.fallback_observations += int(fallback_used is not None)
            request = self._request_cost.get()
            if request is not None:
                request.estimated_cost_usd += cost
        AGENT_LATENCY.labels(agent=agent).observe(latency)
        ESTIMATED_COST.labels(model=model).inc(cost)
        if failed:
            ERRORS.labels(component=agent).inc()
        if fallback_used:
            FALLBACKS.labels(agent=agent, provider=model).inc()

    def record_judge(self, approved: bool, human_intervention: bool = False) -> None:
        """Registra o resultado do juiz sem armazenar conteúdo da conversa."""
        JUDGE_RESULTS.labels(approved=str(approved).lower()).inc()
        if human_intervention:
            self.record_human_intervention("judge_rejected")

    @staticmethod
    def record_human_intervention(reason: str) -> None:
        HUMAN_INTERVENTIONS.labels(reason=reason).inc()

    def record_request(self, route: str, started_at: float, status: str, resolved: bool = False) -> None:
        latency = perf_counter() - started_at
        TOTAL_LATENCY.observe(latency)
        REQUESTS.labels(route=route, status=status).inc()
        with self._lock:
            self._resolved_cases += int(resolved)
            self._requests += 1
            self._request_errors += int(status == "error")
            self._request_latency += latency
            request = self._request_cost.get()
            cost = request.estimated_cost_usd if request is not None else 0.0
            self._chat_cost += cost
        CHAT_COST.labels(route=route, status=status).inc(cost)
        logger.info("Chat completed route=%s status=%s duration_ms=%.2f estimated_cost_usd=%.8f", route, status, latency * 1000, cost)

    def weekly_estimate(self, active_users: int, requests_per_user: int = 5) -> dict:
        if not 100 <= active_users <= 1000:
            raise ValueError("A estimativa acadêmica aceita entre 100 e 1.000 usuários semanais.")
        if not 1 <= requests_per_user <= 100:
            raise ValueError("requests_per_user deve estar entre 1 e 100.")
        with self._lock:
            requests = self._requests
            total_cost = self._chat_cost
            cost_per_resolution = total_cost / self._resolved_cases if self._resolved_cases else None
            request_cost = total_cost / requests if requests else None
            estimated_requests = active_users * requests_per_user
            estimated_cost = estimated_requests * request_cost if request_cost is not None else None
            error_rate = self._request_errors / requests if requests else None
            average_latency_ms = 1000 * self._request_latency / requests if requests else None
            agents = {
                name: {
                    "calls": value.calls,
                    "average_latency_ms": round(1000 * value.total_latency_seconds / value.calls, 2) if value.calls else 0,
                    "error_rate": round(value.errors / value.calls, 4) if value.calls else 0,
                    "fallback_rate": round(value.fallback_calls / value.fallback_observations, 4) if value.fallback_observations else None,
                    "estimated_cost_usd": round(value.estimated_cost_usd, 8),
                    "estimated_input_tokens": value.input_tokens,
                    "estimated_output_tokens": value.output_tokens,
                }
                for name, value in self._agents.items()
            }
        return {
            "assumptions": {"weekly_active_users": active_users, "requests_per_user": requests_per_user, "scope": "chat; processo atual", "token_estimation": "caracteres/4; não é faturamento real"},
            "observed_requests": requests,
            "average_latency_ms": round(average_latency_ms, 2) if average_latency_ms is not None else None,
            "estimated_cost_per_request_usd": round(request_cost, 8) if request_cost is not None else None,
            "estimated_weekly_cost_usd": round(estimated_cost, 4) if estimated_cost is not None else None,
            "estimated_cost_per_resolution_usd": round(cost_per_resolution, 5) if cost_per_resolution is not None else None,
            "observed_error_rate": round(error_rate, 4) if error_rate is not None else None,
            "projected_operational_value_brl": None,
            "projected_cost_roi_note": "Aprovação do juiz não comprova resolução. ROI exige resultados operacionais e custos validados.",
            "agents": agents,
        }

    @staticmethod
    def prometheus_payload() -> tuple[bytes, str]:
        return generate_latest(), CONTENT_TYPE_LATEST
