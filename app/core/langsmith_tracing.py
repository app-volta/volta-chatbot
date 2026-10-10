"""Opt-in chat tracing; export operational data without conversation content."""

import logging
import re
from uuid import UUID

from langsmith import Client, tracing_context
from langchain_core.tracers.langchain import LangChainTracer

from app.core.config import Settings

logger = logging.getLogger(__name__)
_RUN_FIELDS = {
    "id", "trace_id", "parent_run_id", "dotted_order", "start_time", "end_time",
    "run_type", "session_name", "session_id",
}
_RUN_NAMES = {
    "volta_chat", "reset_turn", "input_guardrail", "router", "triage", "standards",
    "data", "performance", "judge", "orchestrator", "blocked", "output_guardrail",
    "ChatGroq", "ChatGoogleGenerativeAI", "RunnableSequence", "RunnableLambda",
    "ChatPromptTemplate", "PydanticOutputParser", "LangGraph", "model", "tools",
}


def _token_usage(outputs: dict) -> dict:
    usage = {}
    for row in outputs.get("generations", []):
        for generation in row if isinstance(row, list) else [row]:
            message = generation.get("message", {}) if isinstance(generation, dict) else {}
            # LangChain serializes AIMessage as a constructor with kwargs.
            counts = (message.get("kwargs") or message).get("usage_metadata") or {}
            for key in ("input_tokens", "output_tokens", "total_tokens"):
                value = counts.get(key)
                if type(value) is int and value >= 0:
                    usage[key] = usage.get(key, 0) + value
    return usage


def sanitize_run_ops(runs: list[dict]) -> list[dict]:
    """Allowlist every exported field, including child spans and error updates."""
    sanitized = []
    for run in runs:
        safe = {key: value for key, value in run.items() if key in _RUN_FIELDS}
        if "name" in run:
            safe["name"] = run["name"] if run["name"] in _RUN_NAMES else run.get("run_type", "step")
        if "inputs" in run:
            safe["inputs"] = {}
        if "outputs" in run:
            safe["outputs"] = {}
        if run.get("error"):
            safe["error"] = "Execution failed (details withheld)."
        original = (run.get("extra") or {}).get("metadata") or {}
        metadata = {}
        for key in ("ls_provider", "ls_model_name"):
            value = original.get(key)
            if isinstance(value, str) and re.fullmatch(r"[\w./:-]{1,128}", value):
                metadata[key] = value
        if original.get("environment") in {"qa", "prod"}:
            metadata["environment"] = original["environment"]
        if original.get("request_id"):
            try:
                metadata["request_id"] = str(UUID(str(original["request_id"])))
            except ValueError:
                pass
        if run.get("run_type") == "llm" and "outputs" in run:
            usage = _token_usage(run.get("outputs") or {})
            if "input_tokens" in usage and "output_tokens" in usage:
                metadata["usage_metadata"] = usage
                metadata["usage_missing"] = False
            else:
                metadata["usage_missing"] = True
        if metadata or "extra" in run:
            safe["extra"] = {"metadata": metadata}
        sanitized.append(safe)
    return sanitized


def create_tracing_client(settings: Settings) -> Client | None:
    if not settings.volta_langsmith_enabled:
        return None
    if not settings.langsmith_api_key or not settings.langsmith_api_key.get_secret_value():
        logger.warning("LangSmith disabled: API key missing.")
        return None
    try:
        return Client(
            api_key=settings.langsmith_api_key.get_secret_value(),
            api_url=str(settings.langsmith_endpoint).rstrip("/"),
            workspace_id=settings.langsmith_workspace_id,
            hide_inputs=True,
            process_buffered_run_ops=sanitize_run_ops,
            run_ops_buffer_size=1,
            omit_traced_runtime_info=True,
            timeout_ms=2000,
        )
    except Exception:
        logger.warning("LangSmith disabled: client initialization failed.")
        return None


def chat_tracer(client: Client, settings: Settings) -> LangChainTracer | None:
    try:
        return LangChainTracer(
            client=client,
            project_name=settings.langsmith_project or f"volta-chatbot-{settings.environment}",
        )
    except Exception:
        logger.warning("LangSmith disabled for request: tracer initialization failed.")
        return None


def invoke_chat_graph(graph, state: dict, config: dict, client: Client | None, settings: Settings):
    # Override the middleware's disabled context only with the filtered client.
    with tracing_context(
        enabled=client is not None and bool(config.get("callbacks")),
        client=client,
        project_name=settings.langsmith_project or f"volta-chatbot-{settings.environment}",
    ):
        return graph.invoke(state, config=config)


def flush_traces(client: Client) -> None:
    # shortcut: delivery is best effort; use durable collection if trace loss is unacceptable.
    try:
        client.flush()
    except Exception:
        logger.warning("LangSmith trace flush failed.")
