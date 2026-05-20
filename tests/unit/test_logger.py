from __future__ import annotations

import logging
import sys
from typing import cast

import pytest
import structlog

from blogradar import logger

pytestmark = pytest.mark.unit


def test_configure_logging_uses_json_renderer(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_calls: dict[str, object] = {}
    basic_config_calls: list[dict[str, object]] = []

    def fake_configure(**kwargs: object) -> None:
        configure_calls.update(kwargs)

    def fake_basic_config(**kwargs: object) -> None:
        basic_config_calls.append(kwargs)

    monkeypatch.setattr(structlog, "configure", fake_configure)
    monkeypatch.setattr(logging, "basicConfig", fake_basic_config)

    logger.configure_logging(log_level="DEBUG", use_json=True)

    processors = cast(list[object], configure_calls["processors"])
    assert any(isinstance(processor, structlog.processors.JSONRenderer) for processor in processors)
    assert configure_calls["wrapper_class"] is structlog.BoundLogger
    assert basic_config_calls == [{"level": logging.DEBUG}]


def test_configure_logging_uses_console_renderer_when_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_calls: dict[str, object] = {}

    def fake_configure(**kwargs: object) -> None:
        configure_calls.update(kwargs)

    monkeypatch.setattr(structlog, "configure", fake_configure)

    logger.configure_logging(log_level="WARNING", use_json=False)

    processors = cast(list[object], configure_calls["processors"])
    assert any(isinstance(processor, structlog.dev.ConsoleRenderer) for processor in processors)


def test_configure_logging_autodetects_json_when_stderr_is_not_tty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_calls: dict[str, object] = {}

    class FakeStderr:
        def isatty(self) -> bool:
            return False

    def fake_configure(**kwargs: object) -> None:
        configure_calls.update(kwargs)

    monkeypatch.setattr(sys, "stderr", FakeStderr())
    monkeypatch.setattr(structlog, "configure", fake_configure)

    logger.configure_logging(log_level="INFO")

    processors = cast(list[object], configure_calls["processors"])
    assert any(isinstance(processor, structlog.processors.JSONRenderer) for processor in processors)


def test_configure_logging_reads_level_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    basic_config_calls: list[dict[str, object]] = []

    def fake_basic_config(**kwargs: object) -> None:
        basic_config_calls.append(kwargs)

    monkeypatch.setenv("RADAR_LOG_LEVEL", "ERROR")
    monkeypatch.setattr(logging, "basicConfig", fake_basic_config)

    logger.configure_logging(use_json=True)

    assert basic_config_calls == [{"level": logging.ERROR}]


def test_get_logger_delegates_to_structlog(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_logger = object()
    calls: list[str] = []

    def fake_get_logger(name: str) -> object:
        calls.append(name)
        return fake_logger

    monkeypatch.setattr(structlog, "get_logger", fake_get_logger)

    assert logger.get_logger("blogradar.test") is fake_logger
    assert calls == ["blogradar.test"]
