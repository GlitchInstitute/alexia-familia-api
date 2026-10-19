"""The log is one line per event, readable by a person or a machine, and it holds only what the
server chose to put in it."""

import json
import logging
import logging.config
import sys
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from alexia_api.logs import LOG_FIELDS, JsonFormatter, PlainFormatter, log_config

MOMENT = datetime(2026, 10, 18, 20, 15, 3, tzinfo=UTC).timestamp()
CONFIGURED = ("", "alexia_api", "uvicorn", "uvicorn.access", "httpx", "httpcore")


def make_record(
    message: str = "GET /v1/accounts 200 12ms",
    *,
    level: int = logging.INFO,
    name: str = "alexia_api.access",
    exc_info: Any = None,
    **extra: object,
) -> logging.LogRecord:
    record = logging.LogRecord(name, level, __file__, 1, message, (), exc_info)
    record.created = MOMENT
    record.msecs = 0
    for field, value in extra.items():
        setattr(record, field, value)
    return record


def boom() -> None:
    raise ValueError("boom")


def caught_exception() -> Any:
    try:
        boom()
    except ValueError:
        return sys.exc_info()


@pytest.fixture
def restored_logging() -> Iterator[None]:
    saved = {
        name: (logger.level, list(logger.handlers), logger.propagate)
        for name in CONFIGURED
        for logger in [logging.getLogger(name)]
    }
    yield
    for name, (level, handlers, propagate) in saved.items():
        logger = logging.getLogger(name)
        logger.setLevel(level)
        logger.handlers[:] = handlers
        logger.propagate = propagate


@pytest.fixture
def far_from_utc(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    if not hasattr(time, "tzset"):
        pytest.skip("this platform cannot change its time zone while running")
    monkeypatch.setenv("TZ", "Pacific/Auckland")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def test_the_plain_line_has_the_time_the_level_the_logger_the_message_and_the_fields() -> None:
    record = make_record(request_id="abc12345", account="marta", key="phone", code="transport")

    assert PlainFormatter().format(record) == (
        "2026-10-18T20:15:03Z INFO    alexia_api.access GET /v1/accounts 200 12ms "
        "request_id=abc12345 account=marta key=phone code=transport"
    )


def test_the_plain_line_leaves_out_fields_that_are_missing_or_none() -> None:
    record = make_record(request_id="abc12345", account=None)

    assert PlainFormatter().format(record).endswith("12ms request_id=abc12345")


def test_a_warning_is_padded_so_that_the_columns_line_up() -> None:
    line = PlainFormatter().format(make_record("trouble", level=logging.WARNING))

    assert line == "2026-10-18T20:15:03Z WARNING alexia_api.access trouble"


def test_the_fields_stay_on_the_first_line_when_there_is_a_traceback() -> None:
    record = make_record("unhandled", exc_info=caught_exception(), request_id="abc12345")

    first, *rest = PlainFormatter().format(record).splitlines()

    assert first.endswith("unhandled request_id=abc12345")
    assert rest[0] == "Traceback (most recent call last):"
    assert rest[-1] == "ValueError: boom"


@pytest.mark.usefixtures("far_from_utc")
@pytest.mark.parametrize("formatter", [PlainFormatter(), JsonFormatter()])
def test_the_time_is_in_utc_wherever_the_server_runs(formatter: logging.Formatter) -> None:
    assert "2026-10-18T20:15:03Z" in formatter.format(make_record())


def test_the_json_line_is_one_object_with_the_same_fields() -> None:
    record = make_record(request_id="abc12345", account="marta", key="phone", code="transport")

    assert json.loads(JsonFormatter().format(record)) == {
        "time": "2026-10-18T20:15:03Z",
        "level": "INFO",
        "logger": "alexia_api.access",
        "message": "GET /v1/accounts 200 12ms",
        "request_id": "abc12345",
        "account": "marta",
        "key": "phone",
        "code": "transport",
    }


def test_the_json_line_has_no_empty_fields_and_stays_on_one_line() -> None:
    line = JsonFormatter().format(make_record("two\nlines", request_id=None))

    assert "\n" not in line
    assert set(json.loads(line)) == {"time", "level", "logger", "message"}


def test_the_json_line_keeps_accents_as_they_are() -> None:
    line = JsonFormatter().format(make_record("la lección de Lucía"))

    assert "la lección de Lucía" in line


def test_the_json_line_carries_a_traceback_in_one_field() -> None:
    record = make_record("unhandled", exc_info=caught_exception())

    entry = json.loads(JsonFormatter().format(record))

    assert entry["exception"].startswith("Traceback")
    assert entry["exception"].endswith("ValueError: boom")


@pytest.mark.parametrize("formatter", [PlainFormatter(), JsonFormatter()])
def test_a_field_the_server_did_not_choose_never_reaches_the_log(
    formatter: logging.Formatter,
) -> None:
    record = make_record(request_id="abc12345", password="hunter2", path="/v1/children/lucia")

    line = formatter.format(record)

    assert "hunter2" not in line
    assert "lucia" not in line


def test_the_fields_are_the_ones_the_request_log_writes() -> None:
    assert LOG_FIELDS == ("request_id", "account", "key", "code")


def test_the_level_sets_the_server_and_uvicorn_and_the_http_libraries_stay_quiet() -> None:
    config = log_config("debug", "text")["loggers"]

    assert config["alexia_api"] == {"level": "DEBUG"}
    assert config["uvicorn"] == {"level": "DEBUG"}
    assert config["httpx"] == {"level": "WARNING"}
    assert config["httpcore"] == {"level": "WARNING"}


def test_uvicorn_never_writes_an_access_line() -> None:
    assert log_config("info", "text")["loggers"]["uvicorn.access"] == {
        "handlers": [],
        "propagate": False,
    }


@pytest.mark.usefixtures("restored_logging")
def test_the_json_setup_writes_json_to_standard_error(capsys: pytest.CaptureFixture[str]) -> None:
    logging.config.dictConfig(log_config("info", "json"))

    logging.getLogger("alexia_api.access").info("GET / 200 1ms", extra={"request_id": "abc12345"})

    captured = capsys.readouterr()
    assert captured.out == ""
    entry = json.loads(captured.err)
    assert entry["message"] == "GET / 200 1ms"
    assert entry["request_id"] == "abc12345"


@pytest.mark.usefixtures("restored_logging")
def test_the_text_setup_writes_plain_lines_to_standard_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    logging.config.dictConfig(log_config("info", "text"))

    logging.getLogger("alexia_api.access").info("GET / 200 1ms", extra={"account": "marta"})

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.endswith(" INFO    alexia_api.access GET / 200 1ms account=marta\n")


@pytest.mark.usefixtures("restored_logging")
def test_the_chosen_level_decides_what_is_written(capsys: pytest.CaptureFixture[str]) -> None:
    logging.config.dictConfig(log_config("warning", "text"))

    logging.getLogger("alexia_api.access").info("a request")
    logging.getLogger("alexia_api.error").warning("a problem")

    assert capsys.readouterr().err.count("\n") == 1


@pytest.mark.usefixtures("restored_logging")
def test_uvicorn_access_lines_and_http_client_chatter_are_dropped(
    capsys: pytest.CaptureFixture[str],
) -> None:
    logging.config.dictConfig(log_config("debug", "text"))

    logging.getLogger("uvicorn.access").info("GET /v1/children/lucia")
    logging.getLogger("httpx").info("HTTP Request: GET https://portal.example.test/")
    logging.getLogger("httpcore").debug("connect_tcp.started")

    assert capsys.readouterr().err == ""


@pytest.mark.usefixtures("restored_logging")
def test_a_warning_from_a_library_is_still_written(capsys: pytest.CaptureFixture[str]) -> None:
    logging.config.dictConfig(log_config("info", "text"))

    logging.getLogger("httpx").warning("something odd")

    assert "something odd" in capsys.readouterr().err
