from threading import Condition
from uuid import uuid4

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from langsmith import Client, tracing_context

from app.core.config import Settings
from app.core.langsmith_tracing import (
    chat_tracer, create_tracing_client, invoke_chat_graph, sanitize_run_ops,
)
from app.core.model_usage import ModelUsage


def test_filter_removes_private_fields_but_preserves_tokens_and_correlation():
    identifier = str(uuid4())
    private = "PRIVATE_SENTINEL"
    run = {
        "id": identifier, "run_type": "llm", "name": "ChatGroq",
        "inputs": {"prompt": private},
        "outputs": {"generations": [[{"message": {"kwargs": {
            "content": private,
            "usage_metadata": {"input_tokens": 10, "output_tokens": 3, "total_tokens": 13},
        }}}]]},
        "serialized": {"api_key": private}, "error": private,
        "events": [private], "tags": [private], "attachments": {"file": private},
        "extra": {"runtime": private, "metadata": {
            "request_id": identifier, "environment": "qa", "thread_id": private,
            "tenant_id": private, "ls_provider": "groq", "ls_model_name": "test-model",
        }},
    }
    result = sanitize_run_ops([run, dict(run, name=private)])
    assert private not in repr(result)
    assert [item["id"] for item in result] == [identifier, identifier]
    metadata = result[0]["extra"]["metadata"]
    assert metadata["request_id"] == identifier
    assert metadata["usage_metadata"] == {"input_tokens": 10, "output_tokens": 3, "total_tokens": 13}
    assert metadata["usage_missing"] is False
    assert run["inputs"]["prompt"] == private


def test_missing_usage_is_not_reported_as_zero_cost():
    run = {"id": str(uuid4()), "run_type": "llm", "outputs": {}}
    metadata = sanitize_run_ops([run])[0]["extra"]["metadata"]
    assert metadata["usage_missing"] is True
    assert "usage_metadata" not in metadata


def test_disabled_or_missing_key_does_not_create_client(monkeypatch):
    def forbidden_client(**_kwargs):
        pytest.fail("Disabled tracing must not create a client")

    monkeypatch.setattr("app.core.langsmith_tracing.Client", forbidden_client)
    assert create_tracing_client(Settings(_env_file=None, volta_langsmith_enabled=False)) is None
    assert create_tracing_client(Settings(_env_file=None, volta_langsmith_enabled=True, langsmith_api_key=None)) is None


def test_tracer_failure_disables_observer_without_logging_secret(monkeypatch, caplog):
    def broken_tracer(**_kwargs):
        raise RuntimeError("PRIVATE_SENTINEL")

    monkeypatch.setattr("app.core.langsmith_tracing.LangChainTracer", broken_tracer)
    assert chat_tracer(object(), Settings(_env_file=None)) is None
    assert "PRIVATE_SENTINEL" not in caplog.text


class RecordingClient(Client):
    """Capture SDK payloads at the send boundary; never contact a server."""

    def __init__(self):
        self.sent = []
        self.condition = Condition()
        super().__init__(
            api_key="synthetic-test-key", api_url="http://127.0.0.1:1",
            auto_batch_tracing=False, process_buffered_run_ops=sanitize_run_ops,
            run_ops_buffer_size=1, hide_inputs=True, omit_traced_runtime_info=True,
        )

    def _capture(self, run):
        with self.condition:
            self.sent.append(run)
            self.condition.notify_all()

    def _create_run(self, run, **_kwargs):
        self._capture(run)

    def _update_run(self, run, **_kwargs):
        self._capture(run)


def test_sdk_exports_filtered_child_calls_with_local_usage_callback(monkeypatch):
    monkeypatch.setenv("LANGSMITH_HIDE_OUTPUTS", "false")
    client = RecordingClient()
    settings = Settings(_env_file=None)
    model = FakeMessagesListChatModel(responses=[AIMessage(
        content="PRIVATE_SENTINEL",
        usage_metadata={"input_tokens": 10, "output_tokens": 3, "total_tokens": 13},
    )])
    collector = ModelUsage("groq:test-model")
    graph = RunnableLambda(lambda state: model.invoke(
        state["messages"], config={"callbacks": [collector]},
    ))
    config = {
        "run_name": "volta_chat", "callbacks": [chat_tracer(client, settings)],
        "metadata": {"request_id": str(uuid4()), "environment": "qa", "thread_id": "PRIVATE_SENTINEL"},
    }
    with tracing_context(enabled=False):
        response = invoke_chat_graph(graph, {"messages": ["PRIVATE_SENTINEL"]}, config, client, settings)
    assert response.content == "PRIVATE_SENTINEL"
    with client.condition:
        assert client.condition.wait_for(lambda: len(client.sent) >= 4, timeout=5)
    assert "PRIVATE_SENTINEL" not in repr(client.sent)
    child_updates = [run for run in client.sent if run.get("run_type") == "llm" and run.get("end_time") is not None]
    assert len(child_updates) == 1
    assert child_updates[0]["parent_run_id"] is not None
    assert child_updates[0]["extra"]["metadata"]["usage_metadata"]["input_tokens"] == 10
    assert collector.measurement()["usage"][0]["input_tokens"] == 10
