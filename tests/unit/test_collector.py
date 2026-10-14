"""Unit tests for blogradar collector."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from blogradar.collector import (
    BLOGRADAR_USER_AGENT,
    _collect_single,
    _create_session,
    _extract_datetime,
    _fetch_url_with_retry,
    collect_sources,
)
from blogradar.models import Source
from blogradar.raw_logger import RawLogger


@pytest.mark.unit
def test_collect_sources_empty() -> None:
    articles, errors = collect_sources([], category="techblog")
    assert articles == []
    assert errors == []


@pytest.mark.unit
def test_collect_sources_unsupported_type() -> None:
    source = Source(name="test", type="html", url="https://example.com")
    articles, errors = collect_sources([source], category="techblog")
    assert len(errors) == 1
    assert "test" in errors[0]


@pytest.mark.unit
def test_collect_sources_skips_disabled_sources() -> None:
    source = Source(name="disabled", type="html", url="https://example.com", enabled=False)
    articles, errors = collect_sources([source], category="techblog")
    assert articles == []
    assert errors == []


@pytest.mark.unit
def test_extract_datetime_none() -> None:
    entry: dict[str, object] = {}
    result = _extract_datetime(entry)
    assert result is None


@pytest.mark.unit
def test_collect_sources_network_error() -> None:
    source = Source(name="bad-source", type="rss", url="https://invalid-url-xyz.example.com/feed")
    with patch(
        "blogradar.collector._fetch_url_with_retry", side_effect=Exception("Connection failed")
    ):
        articles, errors = collect_sources([source], category="techblog")
    assert len(errors) == 1


@pytest.mark.unit
def test_collect_single_uses_title_as_missing_summary_fallback() -> None:
    response = Mock()
    response.content = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <item>
          <title>Release notes without summary</title>
          <link>https://example.com/release</link>
          <pubDate>Mon, 01 Jan 2024 12:00:00 +0000</pubDate>
        </item>
      </channel>
    </rss>
    """
    session = Mock()
    session.get.return_value = response
    response.raise_for_status.return_value = None

    articles = _collect_single(
        Source(name="feed", type="rss", url="https://example.com/feed.xml"),
        category="techblog",
        limit=10,
        timeout=1,
        session=session,
    )

    assert len(articles) == 1
    assert articles[0].summary == "Release notes without summary"


@pytest.mark.unit
def test_session_uses_identifying_user_agent_and_verifies_tls() -> None:
    session = _create_session()
    try:
        assert session.headers["User-Agent"] == BLOGRADAR_USER_AGENT
        assert session.headers["User-Agent"].startswith("BlogRadar/0.1")
        assert session.verify is True
    finally:
        session.close()

    recorded: dict[str, object] = {}

    def _get(*_args: object, **kwargs: object) -> Mock:
        recorded.update(kwargs)
        response = Mock()
        response.raise_for_status.return_value = None
        response.content = b"<rss></rss>"
        return response

    fake_session = Mock()
    fake_session.get.side_effect = _get
    _fetch_url_with_retry("https://example.com/feed.xml", 5, session=fake_session)
    assert recorded["verify"] is True
    headers = recorded["headers"]
    assert isinstance(headers, dict)
    assert str(headers["User-Agent"]).startswith("BlogRadar/0.1")


@pytest.mark.unit
def test_non_feed_body_is_an_error() -> None:
    source = Source(name="html-feed", type="rss", url="https://example.com/feed")
    response = Mock()
    response.content = b"<!DOCTYPE html><html><title>home</title></html>"
    response.raise_for_status.return_value = None
    with patch("blogradar.collector._fetch_url_with_retry", return_value=response):
        articles, errors = collect_sources([source], category="techblog", max_workers=1)
    assert articles == []
    assert any("not RSS/Atom" in error for error in errors)


@pytest.mark.unit
def test_empty_feed_is_an_error() -> None:
    source = Source(name="empty-feed", type="rss", url="https://example.com/feed.xml")
    response = Mock()
    response.content = (
        b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Empty</title></channel></rss>"""
    )
    response.raise_for_status.return_value = None
    with patch("blogradar.collector._fetch_url_with_retry", return_value=response):
        articles, errors = collect_sources([source], category="techblog", max_workers=1)
    assert articles == []
    assert any("no entries" in error for error in errors)


@pytest.mark.unit
def test_reddit_rss_url_is_parsed_as_a_feed() -> None:
    source = Source(
        name="r/programming",
        type="reddit",
        url="https://www.reddit.com/r/programming/.rss",
        config={"bypass_crawl_health": True},
    )
    response = Mock()
    response.content = b"""<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Public atom item</title>
        <link href="https://example.com/item"/>
        <updated>2026-10-14T00:00:00Z</updated>
      </entry>
    </feed>
    """
    response.raise_for_status.return_value = None
    with (
        patch("blogradar.collector._fetch_url_with_retry", return_value=response),
        patch("radar_core.collect_reddit_sources", side_effect=AssertionError("json api")),
    ):
        articles, errors = collect_sources([source], category="techblog", max_workers=1)
    assert errors == []
    assert len(articles) == 1
    assert articles[0].title == "Public atom item"


@pytest.mark.unit
def test_missing_secret_is_warned_and_recorded(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = Source(
        name="Keyed API",
        type="rss",
        url="https://example.com/feed.xml",
        config={"required_env": "BLOGRADAR_TEST_TOKEN"},
    )
    logger = RawLogger(tmp_path)
    with patch.dict("os.environ", {"BLOGRADAR_TEST_TOKEN": ""}, clear=False):
        articles, errors = collect_sources(
            [source],
            category="techblog",
            raw_logger=logger,
            max_workers=1,
        )
    assert articles == []
    assert any("skipped_missing_env BLOGRADAR_TEST_TOKEN" in error for error in errors)
    warning = capsys.readouterr().out
    assert "::warning title=BlogRadar missing secret::" in warning
    assert "BLOGRADAR_TEST_TOKEN" in warning
    skip_files = list(tmp_path.rglob("*.skip.json"))
    assert len(skip_files) == 1
    text = skip_files[0].read_text(encoding="utf-8")
    assert "BLOGRADAR_TEST_TOKEN" in text
    assert "super-secret-value" not in text


@pytest.mark.unit
def test_invalid_required_env_is_not_written() -> None:
    source = Source(
        name="bad-config",
        type="rss",
        url="https://example.com/feed.xml",
        config={"required_env": "actual-secret-value"},
    )
    _articles, errors = collect_sources([source], category="techblog", max_workers=1)
    assert errors
    assert "actual-secret-value" not in errors[0]
    assert "environment variable name" in errors[0]
