"""Métricas operacionais e estimativas de custo para a rubrica de SRE."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from threading import Lock
from time import perf_counter

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from app.config import Settings

REQUESTS = Counter("volta_requests_total", "Requisições do VOLTA", ["route", "status"])
ERRORS = Counter("volta_errors_total", "Erros do VOLTA", ["component"])
AGENT_LATENCY = Histogram("volta_agent_latency_seconds", "Latência por agente", ["agent"])
TOTAL_LATENCY = Histogram("volta_total_latency_seconds", "Latência ponta a ponta")
ESTIMATED_COST = Counter("volta_estimated_cost_usd_total", "Custo estimado de inferência", ["model"])


@dataclass
class AgentMeasurement:
    calls: int = 0
    errors: int = 0
    total_latency_seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0


class Observability:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = Lock()
        self._agents: dict[str, AgentMeasurement] = defaultdict(AgentMeasurement)
        self._resolved_cases = 0

    @staticmethod
    def timer() -> float:
        return perf_counter()

    def _price(self, model: str, input_tokens: int, output_tokens: int) -> float:
        if "groq" in model.lower() or "llama" in model.lower():
            return (input_tokens * self.settings.groq_input_usd_per_million + output_tokens * self.settings.groq_output_usd_per_million) / 1_000_000
        return (input_tokens * self.settings.gemini_input_usd_per_million + output_tokens * self.settings.gemini_output_usd_per_million) / 1_000_000

    def record_agent(self, agent: str, model: str, started_at: float, prompt_text: str, response_text: str, failed: bool = False) -> None:
        latency = perf_counter() - started_at
        # Estimativa conservadora quando o provider não devolve usage_metadata.
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
        AGENT_LATENCY.labels(agent=agent).observe(latency)
        ESTIMATED_COST.labels(model=model).inc(cost)
        if failed:
            ERRORS.labels(component=agent).inc()

    def record_request(self, route: str, started_at: float, status: str, resolved: bool = False) -> None:
        latency = perf_counter() - started_at
        TOTAL_LATENCY.observe(latency)
        REQUESTS.labels(route=route, status=status).inc()
        with self._lock:
            self._resolved_cases += int(resolved)

    def weekly_estimate(self, active_users: int, requests_per_user: int = 5) -> dict:
        if not 100 <= active_users <= 1000:
            raise ValueError("A estimativa acadêmica aceita entre 100 e 1.000 usuários semanais.")
        with self._lock:
            calls = sum(item.calls for item in self._agents.values())
            total_cost = sum(item.estimated_cost_usd for item in self._agents.values())
            cost_per_resolution = total_cost / self._resolved_cases if self._resolved_cases else 0.0
            request_cost = total_cost / calls if calls else 0.002
            estimated_requests = active_users * requests_per_user
            estimated_cost = estimated_requests * request_cost
            errors = sum(item.errors for item in self._agents.values())
            agent_calls = max(1, calls)
            agents = {
                name: {
                    "calls": value.calls,
                    "average_latency_ms": round(1000 * value.total_latency_seconds / value.calls, 2) if value.calls else 0,
                    "error_rate": round(value.errors / value.calls, 4) if value.calls else 0,
                }
                for name, value in self._agents.items()
            }
        projected_value = active_users * requests_per_user * self.settings.value_per_resolved_case_brl
        return {
            "assumptions": {"weekly_active_users": active_users, "requests_per_user": requests_per_user, "token_estimation": "caracteres/4 quando o provider não informa tokens"},
            "estimated_weekly_cost_usd": round(estimated_cost, 4),
            "estimated_cost_per_resolution_usd": round(cost_per_resolution or request_cost, 5),
            "observed_error_rate": round(errors / agent_calls, 4),
            "projected_operational_value_brl": round(projected_value, 2),
            "projected_cost_roi_note": "ROI final deve usar economia/receita validada pela planta; este valor é uma projeção configurável.",
            "agents": agents,
        }

    @staticmethod
    def prometheus_payload() -> tuple[bytes, str]:
        return generate_latest(), CONTENT_TYPE_LATEST
