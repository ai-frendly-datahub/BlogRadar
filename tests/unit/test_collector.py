"""Unit tests for blogradar collector."""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from blogradar.collector import _collect_single, _extract_datetime, collect_sources
from blogradar.models import Source


@pytest.mark.unit
def test_collect_sources_empty():
    articles, errors = collect_sources([], category="techblog")
    assert articles == []
    assert errors == []


@pytest.mark.unit
def test_collect_sources_unsupported_type():
    source = Source(name="test", type="html", url="https://example.com")
    articles, errors = collect_sources([source], category="techblog")
    assert len(errors) == 1
    assert "test" in errors[0]


@pytest.mark.unit
def test_collect_sources_skips_disabled_sources():
    source = Source(name="disabled", type="html", url="https://example.com", enabled=False)
    articles, errors = collect_sources([source], category="techblog")
    assert articles == []
    assert errors == []


@pytest.mark.unit
def test_extract_datetime_none():
    entry = {}
    result = _extract_datetime(entry)
    assert result is None


@pytest.mark.unit
def test_collect_sources_network_error():
    source = Source(name="bad-source", type="rss", url="https://invalid-url-xyz.example.com/feed")
    with patch(
        "blogradar.collector._fetch_url_with_retry", side_effect=Exception("Connection failed")
    ):
        articles, errors = collect_sources([source], category="techblog")
    assert len(errors) == 1


@pytest.mark.unit
def test_collect_single_uses_title_as_missing_summary_fallback():
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
