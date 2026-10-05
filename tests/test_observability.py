from time import perf_counter

import pytest

from app.core.config import Settings
from app.core.observability import Observability


def test_observability_exposes_kpis_and_projection() -> None:
    telemetry = Observability(Settings())
    started = perf_counter() - 0.01

    telemetry.record_agent("router", "groq:test", started, "pergunta", "resposta")
    telemetry.record_judge(approved=False, human_intervention=True)
    telemetry.record_request("standards", started, "success", resolved=False)

    summary = telemetry.weekly_estimate(active_users=100, requests_per_user=5)

    assert summary["estimated_weekly_cost_usd"] >= 0
    assert summary["observed_error_rate"] == 0
    assert summary["agents"]["router"]["calls"] == 1
    assert "fallback_rate" in summary["agents"]["router"]


def test_weekly_estimate_rejects_out_of_scope_user_count() -> None:
    telemetry = Observability(Settings())

    with pytest.raises(ValueError):
        telemetry.weekly_estimate(active_users=99)


def test_prometheus_payload_contains_volta_metrics() -> None:
    payload, content_type = Observability.prometheus_payload()

    assert content_type.startswith("text/plain")
    assert b"volta_requests_total" in payload
    assert b"volta_judge_results_total" in payload
