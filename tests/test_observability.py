from time import perf_counter
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.observability import ResolutionFeedback, resolution_feedback
from app.core.config import Settings
from app.core.observability import Observability


def test_observability_exposes_kpis_and_projection() -> None:
    telemetry = Observability(Settings())
    started = perf_counter() - 0.01

    with telemetry.chat_request():
        telemetry.record_agent("router", "groq:test", started, "pergunta", "resposta")
        telemetry.record_judge(approved=False, human_intervention=True)
        telemetry.record_request("standards", started, "success")

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


def test_resolution_feedback_is_explicit_idempotent_and_drives_roi() -> None:
    telemetry = Observability(Settings())
    expected_cost = telemetry._price("gemini", 100, 100)

    for request_id in ("resolved", "unresolved"):
        with telemetry.chat_request():
            telemetry.record_agent("router", "gemini", perf_counter(), "x" * 400, "x" * 400)
            telemetry.record_request("standards", perf_counter(), "success", request_id=request_id)

    assert telemetry.record_resolution("resolved", True) == "recorded"
    assert telemetry.record_resolution("resolved", True) == "duplicate"
    assert telemetry.record_resolution("resolved", False) == "conflict"
    assert telemetry.record_resolution("unresolved", False) == "recorded"
    assert telemetry.record_resolution("missing", True) == "unknown"

    summary = telemetry.weekly_estimate(100, 5, value_per_resolution_brl=10, usd_to_brl=5)
    assert summary["confirmed_resolutions"] == 1
    assert summary["resolution_feedback_count"] == 2
    assert summary["observed_resolution_rate"] == 0.5
    assert summary["estimated_cost_per_resolution_usd"] == pytest.approx(round(expected_cost * 2, 5))
    assert summary["projected_resolutions"] == 250
    assert summary["projected_operational_value_brl"] == 2500
    assert summary["projected_roi"] is not None


def test_usage_metadata_replaces_character_estimate_and_prices_each_model() -> None:
    telemetry = Observability(Settings())
    usage = [
        {"model": "groq:test", "input_tokens": 10, "output_tokens": 20},
        {"model": "gemini", "input_tokens": 30, "output_tokens": 40},
    ]
    expected = sum(telemetry._price(item["model"], item["input_tokens"], item["output_tokens"]) for item in usage)

    with telemetry.chat_request():
        telemetry.record_agent("router", "ignored", perf_counter(), "x" * 4000, "x" * 4000, usage=usage)
        telemetry.record_request("standards", perf_counter(), "success", request_id="usage")

    summary = telemetry.weekly_estimate(100)
    assert summary["estimated_cost_per_request_usd"] == pytest.approx(round(expected, 8))
    assert summary["agents"]["router"]["estimated_input_tokens"] == 40
    assert summary["agents"]["router"]["estimated_output_tokens"] == 60


def test_resolution_feedback_window_is_bounded() -> None:
    telemetry = Observability(Settings())
    telemetry._REQUEST_HISTORY_LIMIT = 2
    for request_id in ("one", "two", "three"):
        with telemetry.chat_request():
            telemetry.record_request("direct", perf_counter(), "success", request_id=request_id)

    assert telemetry.record_resolution("one", True) == "unknown"
    assert telemetry.record_resolution("two", True) == "recorded"


def test_failed_or_blocked_requests_cannot_be_counted_as_resolved() -> None:
    telemetry = Observability(Settings())
    for request_id, status in (("blocked", "blocked"), ("failed", "error"), ("forbidden", "forbidden")):
        with telemetry.chat_request():
            telemetry.record_request("direct", perf_counter(), status, request_id=request_id)

    assert telemetry.record_resolution("blocked", True) == "unknown"
    assert telemetry.record_resolution("failed", True) == "unknown"
    assert telemetry.record_resolution("forbidden", True) == "unknown"


def test_resolution_endpoint_reports_duplicate_conflict_and_unknown() -> None:
    telemetry = Observability(Settings())
    request_id = uuid4()
    with telemetry.chat_request():
        telemetry.record_request("direct", perf_counter(), "success", request_id=str(request_id))
    payload = ResolutionFeedback(request_id=request_id, resolved=True)

    assert resolution_feedback(payload, telemetry=telemetry)["status"] == "recorded"
    assert resolution_feedback(payload, telemetry=telemetry)["status"] == "duplicate"
    with pytest.raises(HTTPException, match="contraditório") as conflict:
        resolution_feedback(ResolutionFeedback(request_id=request_id, resolved=False), telemetry=telemetry)
    assert conflict.value.status_code == 409
    with pytest.raises(HTTPException, match="não encontrado") as unknown:
        resolution_feedback(ResolutionFeedback(request_id=uuid4(), resolved=True), telemetry=telemetry)
    assert unknown.value.status_code == 404
