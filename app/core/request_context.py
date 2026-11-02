from contextvars import ContextVar
import logging
import re


request_id_context: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_context.get()
        return True


def _safe_provider_error(exc: Exception) -> tuple[int | None, str | None, str | None]:
    current: BaseException | None = exc
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        status = getattr(current, "status_code", None)
        response_status = getattr(getattr(current, "response", None), "status_code", None)
        if not isinstance(status, int) or not 400 <= status <= 599:
            status = response_status
        if not isinstance(status, int) or not 400 <= status <= 599:
            status = None
        body = getattr(current, "body", None)
        detail = body.get("error") if isinstance(body, dict) else None
        if not isinstance(detail, dict):
            detail = {}

        def safe_label(value: object) -> str | None:
            if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", value):
                return value
            return None

        code = safe_label(detail.get("code") or getattr(current, "code", None))
        error_type = safe_label(detail.get("type"))
        if status is not None or code or error_type:
            return status, error_type, code
        current = current.__cause__ or current.__context__
    return None, None, None


def provider_error_code(exc: Exception) -> str | None:
    return _safe_provider_error(exc)[2]


def log_exception_without_details(
    logger: logging.Logger,
    message: str,
    exc: Exception,
    *,
    level: int = logging.ERROR,
) -> None:
    """Keep traceback frames while preventing exception text from leaking prompts or user data."""
    status, error_type, code = _safe_provider_error(exc)
    diagnostics = " ".join(
        part for part in (
            f"provider_status={status}" if status is not None else "",
            f"provider_error_type={error_type}" if error_type else "",
            f"provider_error_code={code}" if code else "",
        ) if part
    )
    if diagnostics:
        message = f"{message} {diagnostics}"
    try:
        raise RuntimeError(type(exc).__name__).with_traceback(exc.__traceback__) from None
    except RuntimeError:
        logger.log(level, message, exc_info=True)
