import logging

from app.core.request_context import log_exception_without_details


def test_exception_logging_keeps_traceback_without_exception_message(caplog):
    logger = logging.getLogger("test.request_context")

    sensitive_input = "private user prompt must not reach logs"
    try:
        raise ValueError(sensitive_input)
    except ValueError as exc:
        with caplog.at_level(logging.ERROR, logger=logger.name):
            log_exception_without_details(logger, "Request failed", exc)

    assert "Request failed" in caplog.text
    assert "ValueError" in caplog.text
    assert "Traceback" in caplog.text
    assert "private user prompt" not in caplog.text


def test_provider_logging_keeps_safe_error_metadata_only(caplog):
    logger = logging.getLogger("test.provider_error")

    class ProviderError(Exception):
        status_code = 400
        body = {
            "error": {
                "type": "invalid_request_error",
                "code": "tool_use_failed",
                "message": "sensitive provider response body",
            }
        }

    sensitive_exception_text = "sensitive exception text"
    try:
        raise ProviderError(sensitive_exception_text)
    except ProviderError as exc:
        with caplog.at_level(logging.ERROR, logger=logger.name):
            log_exception_without_details(logger, "Fallback failed", exc)

    assert "provider_status=400" in caplog.text
    assert "provider_error_type=invalid_request_error" in caplog.text
    assert "provider_error_code=tool_use_failed" in caplog.text
    assert "sensitive provider response body" not in caplog.text
    assert "sensitive exception text" not in caplog.text
