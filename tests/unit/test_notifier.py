from __future__ import annotations

from datetime import UTC, datetime
from email.message import Message
from types import TracebackType
from typing import cast

import pytest

from blogradar.notifier import (
    CompositeNotifier,
    EmailNotifier,
    NotificationPayload,
    WebhookNotifier,
)

pytestmark = pytest.mark.unit


def _payload() -> NotificationPayload:
    return NotificationPayload(
        category_name="techblog",
        sources_count=10,
        collected_count=20,
        matched_count=7,
        errors_count=1,
        timestamp=datetime(2026, 5, 20, 12, 0, tzinfo=UTC),
        report_url="reports/techblog.html",
    )


def test_notification_payload_to_dict_serializes_timestamp() -> None:
    data = _payload().to_dict()

    assert data["category_name"] == "techblog"
    assert data["timestamp"] == "2026-05-20T12:00:00+00:00"
    assert data["report_url"] == "reports/techblog.html"


def test_email_notifier_send_builds_and_sends_message(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSMTP:
        instances: list[FakeSMTP] = []

        def __init__(self, host: str, port: int) -> None:
            self.host = host
            self.port = port
            self.logged_in: tuple[str, str] | None = None
            self.sent_message: Message | None = None
            FakeSMTP.instances.append(self)

        def __enter__(self) -> FakeSMTP:
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: TracebackType | None,
        ) -> None:
            return None

        def starttls(self) -> None:
            return None

        def login(self, user: str, password: str) -> None:
            self.logged_in = (user, password)

        def send_message(self, msg: Message) -> None:
            self.sent_message = msg

    monkeypatch.setattr("blogradar.notifier.smtplib.SMTP", FakeSMTP)

    sender = EmailNotifier(
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_user="user",
        smtp_password="secret",
        from_addr="from@example.com",
        to_addrs=["to@example.com"],
    )

    assert sender.send(_payload()) is True

    smtp = FakeSMTP.instances[0]
    assert (smtp.host, smtp.port) == ("smtp.example.com", 587)
    assert smtp.logged_in == ("user", "secret")
    assert smtp.sent_message is not None
    assert smtp.sent_message["Subject"] == "Radar Pipeline Complete: techblog"
    assert "Collected: 20" in smtp.sent_message.get_payload()


def test_email_notifier_send_returns_false_on_smtp_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingSMTP:
        def __init__(self, _host: str, _port: int) -> None:
            raise OSError("smtp unavailable")

    monkeypatch.setattr("blogradar.notifier.smtplib.SMTP", FailingSMTP)

    sender = EmailNotifier(
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_user="user",
        smtp_password="secret",
        from_addr="from@example.com",
        to_addrs=["to@example.com"],
    )

    assert sender.send(_payload()) is False


def test_webhook_notifier_posts_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    class Response:
        status_code = 204

    def fake_post(url: str, **kwargs: object) -> Response:
        calls["url"] = url
        calls["json"] = kwargs["json"]
        calls["headers"] = kwargs["headers"]
        calls["timeout"] = kwargs["timeout"]
        return Response()

    monkeypatch.setattr("blogradar.notifier.requests.post", fake_post)

    sender = WebhookNotifier("https://hooks.example.com", headers={"X-Test": "1"})

    assert sender.send(_payload()) is True
    assert calls["url"] == "https://hooks.example.com"
    assert cast(dict[str, object], calls["json"])["category_name"] == "techblog"
    assert calls["headers"] == {"X-Test": "1"}
    assert calls["timeout"] == 10


def test_webhook_notifier_get_and_failure_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class OkResponse:
        status_code = 200

    class ErrorResponse:
        status_code = 500

    def fake_get(url: str, **_kwargs: object) -> OkResponse:
        calls.append(url)
        return OkResponse()

    def fake_post(_url: str, **_kwargs: object) -> ErrorResponse:
        return ErrorResponse()

    monkeypatch.setattr("blogradar.notifier.requests.get", fake_get)
    monkeypatch.setattr("blogradar.notifier.requests.post", fake_post)

    assert WebhookNotifier("https://hooks.example.com", method="GET").send(_payload()) is True
    assert calls == ["https://hooks.example.com"]
    assert WebhookNotifier("https://hooks.example.com", method="POST").send(_payload()) is False
    assert WebhookNotifier("https://hooks.example.com", method="PATCH").send(_payload()) is False


def test_webhook_notifier_returns_false_on_request_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(_url: str, **_kwargs: object) -> object:
        raise RuntimeError("network down")

    monkeypatch.setattr("blogradar.notifier.requests.post", fake_post)

    assert WebhookNotifier("https://hooks.example.com").send(_payload()) is False


def test_composite_notifier_aggregates_results_and_exceptions() -> None:
    class FakeNotifier:
        def __init__(self, result: bool | BaseException) -> None:
            self.result = result

        def send(self, _payload: NotificationPayload) -> bool:
            if isinstance(self.result, BaseException):
                raise self.result
            return self.result

    payload = _payload()

    assert CompositeNotifier([]).send(payload) is True
    assert CompositeNotifier([FakeNotifier(True), FakeNotifier(True)]).send(payload) is True
    assert CompositeNotifier([FakeNotifier(True), FakeNotifier(False)]).send(payload) is False
    assert CompositeNotifier([FakeNotifier(RuntimeError("boom"))]).send(payload) is False
