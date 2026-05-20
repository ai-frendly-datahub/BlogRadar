from __future__ import annotations

import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

import main
from blogradar.models import Article, Source
from blogradar.notifier import NotificationPayload

pytestmark = pytest.mark.unit


def test_parse_args_accepts_pipeline_options(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--category",
            "techblog",
            "--config",
            "custom.yaml",
            "--categories-dir",
            "cats",
            "--per-source-limit",
            "5",
            "--recent-days",
            "3",
            "--max-age-days",
            "10",
            "--timeout",
            "2",
            "--keep-days",
            "30",
            "--keep-raw-days",
            "40",
            "--keep-report-days",
            "50",
            "--snapshot-db",
            "--generate-report",
            "--max-sources",
            "7",
            "--exclude-source",
            "one",
            "--exclude-source",
            "two",
        ],
    )

    args = main.parse_args()

    assert args.category == "techblog"
    assert args.config == Path("custom.yaml")
    assert args.categories_dir == Path("cats")
    assert args.per_source_limit == 5
    assert args.recent_days == 3
    assert args.max_age_days == 10
    assert args.timeout == 2
    assert args.keep_days == 30
    assert args.keep_raw_days == 40
    assert args.keep_report_days == 50
    assert args.snapshot_db is True
    assert args.generate_report is True
    assert args.max_sources == 7
    assert args.exclude_source == ["one", "two"]


def test_cli_conversion_helpers() -> None:
    assert main._to_path(Path("x")) == Path("x")
    assert main._to_path("x") is None

    assert main._to_int(3, 1) == 3
    assert main._to_int("4", 1) == 4
    assert main._to_int("bad", 1) == 1
    assert main._to_int(True, 1) == 1
    assert main._to_int(None, 1) == 1

    assert main._to_optional_int(None) is None
    assert main._to_optional_int(False) is None
    assert main._to_optional_int(5) == 5
    assert main._to_optional_int("6") == 6
    assert main._to_optional_int("bad") is None
    assert main._to_optional_int(object()) is None

    assert main._to_str_list(["a", 2, "b"]) == ["a", "b"]
    assert main._to_str_list(("a", "b")) == []


def test_send_notifications_returns_when_no_channels(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NOTIFICATION_EMAIL", raising=False)
    monkeypatch.delenv("NOTIFICATION_WEBHOOK", raising=False)

    main._send_notifications(
        category_name="techblog",
        sources_count=1,
        collected_count=2,
        matched_count=3,
        errors_count=0,
        report_path=Path("report.html"),
    )


def test_send_notifications_builds_email_webhook_and_composite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: dict[str, Any] = {}

    class FakeEmailNotifier:
        def __init__(self, **kwargs: object) -> None:
            created["email"] = kwargs

        def send(self, _payload: object) -> bool:
            return True

    class FakeWebhookNotifier:
        def __init__(self, **kwargs: object) -> None:
            created["webhook"] = kwargs

        def send(self, _payload: object) -> bool:
            return True

    class FakeCompositeNotifier:
        def __init__(self, notifiers: list[object]) -> None:
            created["notifier_count"] = len(notifiers)

        def send(self, payload: object) -> bool:
            created["payload"] = payload
            return True

    monkeypatch.setenv("NOTIFICATION_EMAIL", "to@example.com")
    monkeypatch.setenv("NOTIFICATION_WEBHOOK", "https://hooks.example.com")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("SMTP_USER", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("SMTP_FROM", "from@example.com")
    monkeypatch.setattr("blogradar.notifier.EmailNotifier", FakeEmailNotifier)
    monkeypatch.setattr("blogradar.notifier.WebhookNotifier", FakeWebhookNotifier)
    monkeypatch.setattr("blogradar.notifier.CompositeNotifier", FakeCompositeNotifier)

    main._send_notifications(
        category_name="techblog",
        sources_count=1,
        collected_count=2,
        matched_count=3,
        errors_count=4,
        report_path=Path("report.html"),
    )

    assert created["email"] == {
        "smtp_host": "smtp.example.com",
        "smtp_port": 2525,
        "smtp_user": "user",
        "smtp_password": "secret",
        "from_addr": "from@example.com",
        "to_addrs": ["to@example.com"],
    }
    assert created["webhook"] == {"url": "https://hooks.example.com"}
    assert created["notifier_count"] == 2
    payload = cast(NotificationPayload, created["payload"])
    assert payload.category_name == "techblog"
    assert payload.matched_count == 3


def test_select_report_articles_dedupes_and_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = Article(
        title="First",
        link="https://example.com/1",
        summary="python",
        published=datetime.now(UTC),
        source="Source",
        category="techblog",
    )
    duplicate = Article(
        title="Duplicate",
        link="https://example.com/1",
        summary="duplicate",
        published=datetime.now(UTC),
        source="Source",
        category="techblog",
    )
    second = Article(
        title="Second",
        link="https://example.com/2",
        summary="rust",
        published=datetime.now(UTC),
        source="Source",
        category="techblog",
    )

    class FakeStorage:
        def recent_articles(self, _category: str, *, days: int, limit: int) -> list[Article]:
            assert (days, limit) == (7, 1000)
            return [first, duplicate]

        def recent_articles_by_collected_at(
            self, _category: str, *, days: int, limit: int
        ) -> list[Article]:
            assert (days, limit) == (7, 1000)
            return [duplicate, second]

    def fake_apply(articles: Iterable[Article], _sources: list[Source]) -> list[Article]:
        return list(articles)

    def fake_filter(articles: Iterable[Article], _sources: list[Source]) -> list[Article]:
        return list(articles)

    monkeypatch.setattr("main.apply_source_context_entities", fake_apply)
    monkeypatch.setattr("main.filter_relevant_articles", fake_filter)

    selected = main._select_report_articles(
        cast(Any, FakeStorage()),
        "techblog",
        recent_days=7,
        sources=[Source(name="Source", type="rss", url="https://example.com/feed")],
    )

    assert selected == [first, second]
