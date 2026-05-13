"""Tests para app.core.logging_config."""

import json
import logging

from app.core import logging_config as lc


def _uvicorn_access_record(msg: str, args: tuple):
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="x",
        lineno=1,
        msg=msg,
        args=args,
        exc_info=None,
    )


def test_json_formatter_includes_extra_data():
    fmt = lc.JSONFormatter()
    rec = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="x",
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    rec.extra_data = {"k": "v"}
    raw = fmt.format(rec)
    data = json.loads(raw)
    assert data["message"] == "hello"
    assert data["extra"]["k"] == "v"


def test_json_formatter_with_exception():
    fmt = lc.JSONFormatter()
    try:
        1 / 0
    except ZeroDivisionError:
        import sys

        rec = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="x",
            lineno=1,
            msg="boom",
            args=(),
            exc_info=sys.exc_info(),
        )
    raw = fmt.format(rec)
    data = json.loads(raw)
    assert "exception" in data


def test_health_check_filter_blocks_uvicorn_health():
    flt = lc.HealthCheckFilter()
    rec = _uvicorn_access_record(
        '%s - "%s %s HTTP/%s" %s',
        ("1.1.1.1", "GET", "/health", "1.1", "200 OK"),
    )
    assert flt.filter(rec) is False


def test_health_check_filter_allows_other_paths():
    flt = lc.HealthCheckFilter()
    rec = _uvicorn_access_record(
        '%s - "%s %s HTTP/%s" %s',
        ("1.1.1.1", "GET", "/api/v1/devices", "1.1", "200 OK"),
    )
    assert flt.filter(rec) is True


def test_setup_logging_configures_root(caplog):
    with caplog.at_level(logging.INFO):
        lc.setup_logging("INFO")

    root = logging.getLogger()
    assert root.level <= logging.INFO


def test_get_logger_returns_named_logger():
    lg = lc.get_logger("my.module")
    assert lg.name == "my.module"
