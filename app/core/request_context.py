from contextvars import ContextVar
import logging


request_id_context: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_context.get()
        return True


def log_exception_without_details(logger: logging.Logger, message: str, exc: Exception) -> None:
    """Keep traceback frames while preventing exception text from leaking prompts or user data."""
    try:
        raise RuntimeError(type(exc).__name__).with_traceback(exc.__traceback__) from None
    except RuntimeError:
        logger.exception(message)
