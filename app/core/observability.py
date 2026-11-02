"""Métricas operacionais e estimativas de custo para a rubrica de SRE."""

from __future__ import annotations

from collections import OrderedDict, defaultdict
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
    _REQUEST_HISTORY_LIMIT = 10_000

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = Lock()
        self._agents: dict[str, AgentMeasurement] = defaultdict(AgentMeasurement)
        self._resolved_cases = 0
        self._resolution_feedback = 0
        self._resolution_feedback_cost = 0.0
        self._requests = 0
        self._request_errors = 0
        self._request_latency = 0.0
        self._chat_cost = 0.0
        self._request_cost: ContextVar[ChatMeasurement | None] = ContextVar("chat_measurement", default=None)
        self._request_history: OrderedDict[str, tuple[float, bool | None]] = OrderedDict()

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
        usage: list[dict] | None = None,
        usage_complete: bool = True,
    ) -> None:
        latency = perf_counter() - started_at
        if usage is None or not usage_complete:
            input_tokens = max(1, len(prompt_text) // 4)
            output_tokens = max(1, len(response_text) // 4)
            billed_usage = [(model, input_tokens, output_tokens)]
        else:
            billed_usage = [
                (str(item["model"]), int(item["input_tokens"]), int(item["output_tokens"]))
                for item in usage
            ]
            input_tokens = sum(item[1] for item in billed_usage)
            output_tokens = sum(item[2] for item in billed_usage)
        cost = sum(self._price(*item) for item in billed_usage)
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
        for billed_model, billed_input, billed_output in billed_usage:
            ESTIMATED_COST.labels(model=billed_model).inc(self._price(billed_model, billed_input, billed_output))
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

    def record_request(self, route: str, started_at: float, status: str, request_id: str | None = None) -> None:
        latency = perf_counter() - started_at
        TOTAL_LATENCY.observe(latency)
        REQUESTS.labels(route=route, status=status).inc()
        with self._lock:
            self._requests += 1
            self._request_errors += int(status == "error")
            self._request_latency += latency
            request = self._request_cost.get()
            cost = request.estimated_cost_usd if request is not None else 0.0
            self._chat_cost += cost
            if request_id is not None and status == "success":
                key = str(request_id)
                if key not in self._request_history:
                    self._request_history[key] = (cost, None)
                    while len(self._request_history) > self._REQUEST_HISTORY_LIMIT:
                        self._request_history.popitem(last=False)
        CHAT_COST.labels(route=route, status=status).inc(cost)
        logger.info("Chat completed route=%s status=%s duration_ms=%.2f estimated_cost_usd=%.8f", route, status, latency * 1000, cost)

    def record_resolution(self, request_id: str, resolved: bool) -> str:
        """Registra o resultado operacional dentro da janela mantida em memória."""
        with self._lock:
            measurement = self._request_history.get(str(request_id))
            if measurement is None:
                return "unknown"
            cost, previous = measurement
            if previous is not None:
                return "duplicate" if previous == resolved else "conflict"
            self._request_history[str(request_id)] = (cost, resolved)
            self._resolution_feedback += 1
            self._resolution_feedback_cost += cost
            if resolved:
                self._resolved_cases += 1
            return "recorded"

    def weekly_estimate(
        self,
        active_users: int,
        requests_per_user: int = 5,
        value_per_resolution_brl: float | None = None,
        usd_to_brl: float | None = None,
    ) -> dict:
        if not 100 <= active_users <= 1000:
            raise ValueError("A estimativa acadêmica aceita entre 100 e 1.000 usuários semanais.")
        if not 1 <= requests_per_user <= 100:
            raise ValueError("requests_per_user deve estar entre 1 e 100.")
        if value_per_resolution_brl is not None and value_per_resolution_brl <= 0:
            raise ValueError("value_per_resolution_brl deve ser positivo.")
        if usd_to_brl is not None and usd_to_brl <= 0:
            raise ValueError("usd_to_brl deve ser positivo.")
        with self._lock:
            requests = self._requests
            total_cost = self._chat_cost
            confirmed_resolutions = self._resolved_cases
            cost_per_resolution = self._resolution_feedback_cost / confirmed_resolutions if confirmed_resolutions else None
            request_cost = total_cost / requests if requests else None
            estimated_requests = active_users * requests_per_user
            estimated_cost = estimated_requests * request_cost if request_cost is not None else None
            error_rate = self._request_errors / requests if requests else None
            average_latency_ms = 1000 * self._request_latency / requests if requests else None
            resolution_feedback = self._resolution_feedback
            resolution_rate = confirmed_resolutions / resolution_feedback if resolution_feedback else None
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
        projected_resolutions = estimated_requests * resolution_rate if resolution_rate is not None else None
        projected_value = (
            projected_resolutions * value_per_resolution_brl
            if projected_resolutions is not None and value_per_resolution_brl is not None
            else None
        )
        projected_cost_brl = estimated_cost * usd_to_brl if estimated_cost is not None and usd_to_brl is not None else None
        projected_roi = (
            (projected_value - projected_cost_brl) / projected_cost_brl
            if projected_value is not None and projected_cost_brl
            else None
        )
        return {
            "assumptions": {
                "weekly_active_users": active_users,
                "requests_per_user": requests_per_user,
                "value_per_resolution_brl": value_per_resolution_brl,
                "usd_to_brl": usd_to_brl,
                "scope": "chat; processo atual",
                "token_estimation": "provider metadata or characters/4 estimate; not billing",
                "resolution_rate": "feedback operacional explícito; não aprovação do juiz",
            },
            "observed_requests": requests,
            "average_latency_ms": round(average_latency_ms, 2) if average_latency_ms is not None else None,
            "estimated_cost_per_request_usd": round(request_cost, 8) if request_cost is not None else None,
            "estimated_weekly_cost_usd": round(estimated_cost, 4) if estimated_cost is not None else None,
            "estimated_cost_per_resolution_usd": round(cost_per_resolution, 5) if cost_per_resolution is not None else None,
            "confirmed_resolutions": confirmed_resolutions,
            "resolution_feedback_count": resolution_feedback,
            "observed_resolution_rate": round(resolution_rate, 4) if resolution_rate is not None else None,
            "observed_error_rate": round(error_rate, 4) if error_rate is not None else None,
            "projected_resolutions": round(projected_resolutions, 2) if projected_resolutions is not None else None,
            "projected_operational_value_brl": round(projected_value, 2) if projected_value is not None else None,
            "projected_cost_brl": round(projected_cost_brl, 2) if projected_cost_brl is not None else None,
            "projected_roi": round(projected_roi, 4) if projected_roi is not None else None,
            "projected_cost_roi_note": "ROI usa apenas os valores informados e a taxa observada de resoluções confirmadas.",
            "agents": agents,
        }

    @staticmethod
    def prometheus_payload() -> tuple[bytes, str]:
        return generate_latest(), CONTENT_TYPE_LATEST
