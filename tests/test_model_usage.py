from uuid import uuid4

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from app.core.model_usage import ModelUsage


def test_usage_includes_tool_loop_calls_and_the_actual_fallback_provider():
    collector = ModelUsage("gemini:primary")
    for provider, model, input_tokens in [("google", "primary", 300), ("groq", "fallback", 200)]:
        run_id = uuid4()
        collector.on_chat_model_start({"id": [provider]}, [], run_id=run_id, invocation_params={"model": model})
        message = AIMessage(content="", usage_metadata={"input_tokens": input_tokens, "output_tokens": 40, "total_tokens": input_tokens + 40})
        collector.on_llm_end(LLMResult(generations=[[ChatGeneration(message=message)]]), run_id=run_id)
    measurement = collector.measurement()
    assert measurement["fallback_used"] is True
    assert measurement["model"] == "groq:fallback"
    assert sum(item["input_tokens"] for item in measurement["usage"]) == 500


def test_partial_usage_remains_an_estimate_and_successful_fallback_usage_is_kept():
    collector = ModelUsage("gemini:primary")
    run_id = uuid4()
    collector.on_chat_model_start({"id": ["google"]}, [], run_id=run_id)
    collector.on_llm_end(LLMResult(generations=[[ChatGeneration(message=AIMessage(content=""))]]), run_id=run_id)
    assert collector.measurement()["usage"] is None
    assert collector.measurement()["fallback_used"] is False
    fallback_id = uuid4()
    collector.on_chat_model_start({"id": ["groq"]}, [], run_id=fallback_id, invocation_params={"model": "fallback"})
    message = AIMessage(content="", usage_metadata={"input_tokens": 9, "output_tokens": 4, "total_tokens": 13})
    collector.on_llm_end(LLMResult(generations=[[ChatGeneration(message=message)]]), run_id=fallback_id)
    assert collector.measurement()["usage"] == [
        {"model": "groq:fallback", "input_tokens": 9, "output_tokens": 4}
    ]
