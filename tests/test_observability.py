from time import perf_counter
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.core.config import Settings
from app.core.observability import Observability


def test_observability_exposes_kpis_and_projection() -> None:
    telemetry = Observability(Settings())
    started = perf_counter() - 0.01

    with telemetry.chat_request():
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


def test_chat_cost_counts_requests_not_agents_and_excludes_other_endpoints() -> None:
    telemetry = Observability(Settings())
    started = perf_counter()
    telemetry.record_agent("image", "gemini", started, "x" * 4000, "x" * 4000)
    expected = 2 * telemetry._price("gemini", 100, 100)
    with telemetry.chat_request():
        for agent in ("router", "judge"):
            telemetry.record_agent(agent, "gemini", started, "x" * 400, "x" * 400)
        telemetry.record_request("standards", started, "success")
    with telemetry.chat_request():
        telemetry.record_request("unknown", started, "error")
    summary = telemetry.weekly_estimate(100, 5)
    assert summary["observed_requests"] == 2
    assert summary["estimated_cost_per_request_usd"] == pytest.approx(round(expected / 2, 8))
    assert summary["estimated_weekly_cost_usd"] == pytest.approx(round(expected / 2 * 500, 4))
    assert summary["observed_error_rate"] == 0.5
    assert summary["estimated_cost_per_resolution_usd"] is None
    assert summary["projected_operational_value_brl"] is None
    assert summary["agents"]["router"]["fallback_rate"] is None


def test_no_sample_does_not_invent_projection() -> None:
    summary = Observability(Settings()).weekly_estimate(100)
    assert summary["estimated_weekly_cost_usd"] is None
    assert summary["observed_error_rate"] is None


def test_request_accumulators_are_isolated_and_propagate_to_anyio_workers() -> None:
    import anyio

    telemetry = Observability(Settings())

    async def message(size):
        started = perf_counter()
        with telemetry.chat_request():
            await anyio.to_thread.run_sync(
                lambda: telemetry.record_agent("router", "gemini", started, "x" * size, "x" * size)
            )
            cost = telemetry._request_cost.get().estimated_cost_usd
            telemetry.record_request("standards", started, "success")
        assert telemetry._request_cost.get() is None
        return cost

    def run(size):
        return anyio.run(message, size)

    with ThreadPoolExecutor(max_workers=2) as executor:
        costs = list(executor.map(run, (400, 800)))
    assert costs == pytest.approx([
        telemetry._price("gemini", 100, 100), telemetry._price("gemini", 200, 200)
    ])
