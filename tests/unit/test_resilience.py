from __future__ import annotations

from typing import Any, cast

import pytest

from blogradar import resilience
from blogradar.resilience import SourceCircuitBreakerListener, SourceCircuitBreakerManager

pytestmark = pytest.mark.unit


class _FakeLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def info(self, event: str, **kwargs: object) -> None:
        self.events.append((event, kwargs))

    def warning(self, event: str, **kwargs: object) -> None:
        self.events.append((event, kwargs))

    def debug(self, event: str, **kwargs: object) -> None:
        self.events.append((event, kwargs))


class _FakeBreaker:
    name = "Example Source"


class _FakeState:
    def __init__(self, name: str) -> None:
        self.name = name


def test_circuit_breaker_listener_logs_state_failure_and_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_logger = _FakeLogger()
    monkeypatch.setattr("blogradar.resilience.logger", fake_logger)
    listener = SourceCircuitBreakerListener()
    breaker = cast(Any, _FakeBreaker())

    listener.state_change(breaker, cast(Any, _FakeState("closed")), cast(Any, _FakeState("open")))
    listener.state_change(breaker, None, cast(Any, _FakeState("closed")))
    listener.failure(breaker, RuntimeError("network failed"))
    listener.success(breaker)
    listener.before_call(breaker, object())

    assert fake_logger.events == [
        (
            "circuit_breaker_state_change",
            {"source": "Example Source", "before": "closed", "after": "open"},
        ),
        (
            "circuit_breaker_state_change",
            {"source": "Example Source", "before": None, "after": "closed"},
        ),
        (
            "circuit_breaker_failure",
            {
                "source": "Example Source",
                "exception": "RuntimeError",
                "message": "network failed",
            },
        ),
        ("circuit_breaker_success", {"source": "Example Source"}),
    ]


def test_circuit_breaker_manager_caches_resets_and_reports_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_logger = _FakeLogger()
    monkeypatch.setattr("blogradar.resilience.logger", fake_logger)
    manager = SourceCircuitBreakerManager()

    first = manager.get_breaker("Example")
    second = manager.get_breaker("Example")
    other = manager.get_breaker("Other")

    assert first is second
    assert first is not other
    assert manager.get_status() == {"Example": "closed", "Other": "closed"}

    manager.reset_breaker("Example")
    manager.reset_breaker("Missing")
    manager.reset_all()

    assert ("circuit_breaker_reset", {"source": "Example"}) in fake_logger.events
    assert ("circuit_breaker_reset_all", {"count": 2}) in fake_logger.events


def test_get_circuit_breaker_manager_returns_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("blogradar.resilience._manager", None)

    first = resilience.get_circuit_breaker_manager()
    second = resilience.get_circuit_breaker_manager()

    assert first is second
