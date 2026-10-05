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
