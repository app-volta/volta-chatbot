"""Collect provider usage without retaining prompts, responses or credentials."""

from threading import Lock

from langchain_core.callbacks import BaseCallbackHandler


class ModelUsage(BaseCallbackHandler):
    def __init__(self, default_model: str):
        self.default_model = default_model
        self.calls: list[dict] = []
        self._models: dict = {}
        self._missing = False
        self._lock = Lock()

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        identifier = ".".join(serialized.get("id", [])).casefold()
        provider = "groq" if "groq" in identifier else "gemini" if "google" in identifier else self.default_model.split(":")[0]
        params = kwargs.get("invocation_params") or {}
        name = params.get("model_name") or params.get("model") or self.default_model.split(":")[-1]
        with self._lock:
            self._models[run_id] = f"{provider}:{name}"

    def on_llm_end(self, response, *, run_id, **kwargs):
        generation = response.generations[0][0] if response.generations and response.generations[0] else None
        message = getattr(generation, "message", None)
        usage = getattr(message, "usage_metadata", None) or {}
        input_tokens, output_tokens = usage.get("input_tokens"), usage.get("output_tokens")
        with self._lock:
            if not isinstance(input_tokens, int) or not isinstance(output_tokens, int) or input_tokens < 0 or output_tokens < 0:
                self._missing = True
                return
            self.calls.append({
                "model": self._models.get(run_id, self.default_model),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            })

    def measurement(self) -> dict:
        with self._lock:
            models = list(self._models.values())
            fallback = any(model.split(":")[0] != self.default_model.split(":")[0] for model in models) if models else None
            return {
                "model": self.calls[-1]["model"] if self.calls else self.default_model,
                "fallback_used": fallback,
                "usage": list(self.calls) if self.calls else None,
                "usage_complete": not self._missing,
            }
