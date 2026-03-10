from __future__ import annotations

# pyright: reportPrivateUsage=false

import pytest
import requests
from unittest.mock import Mock, patch

from blogradar.collector import _collect_single, collect_sources
from blogradar.models import Article, Source


class TestCollectorRetryLogic:
    """Test HTTP retry logic with exponential backoff."""

    def test_retry_on_timeout(self) -> None:
        """Should retry on request timeout and eventually succeed."""
        source = Source(name="test_feed", type="rss", url="http://example.com/feed")

        with patch("radar.collector.requests.get") as mock_get:
            mock_response = Mock()
            mock_response.content = b"""<?xml version="1.0"?>
<rss version="2.0">
    <channel>
        <item>
            <title>Test Article</title>
            <link>http://example.com/article</link>
            <description>Test summary</description>
            <pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate>
        </item>
    </channel>
</rss>"""
            mock_response.raise_for_status = Mock()

            mock_get.side_effect = [
                requests.exceptions.Timeout("timeout"),
                requests.exceptions.Timeout("timeout"),
                mock_response,
            ]

            articles = _collect_single(source, category="test", limit=10, timeout=15)

            assert len(articles) == 1
            assert articles[0].title == "Test Article"
            assert isinstance(articles[0], Article)
            assert mock_get.call_count == 3
            assert collect_sources([], category="test") == ([], [])

    def test_retry_on_5xx_error(self) -> None:
        """Should retry on 5xx server errors."""
        source = Source(name="test_feed", type="rss", url="http://example.com/feed")

        with patch("radar.collector.requests.get") as mock_get:
            mock_response = Mock()
            mock_response.content = b"""<?xml version="1.0"?>
<rss version="2.0">
    <channel>
        <item>
            <title>Test Article</title>
            <link>http://example.com/article</link>
            <description>Test summary</description>
            <pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate>
        </item>
    </channel>
</rss>"""
            mock_response.raise_for_status = Mock()

            error_response = Mock()
            error_response.status_code = 503
            error_response.raise_for_status = Mock(
                side_effect=requests.exceptions.HTTPError("503 Service Unavailable")
            )

            mock_get.side_effect = [
                error_response,
                error_response,
                mock_response,
            ]

            articles = _collect_single(source, category="test", limit=10, timeout=15)

            assert len(articles) == 1
            assert articles[0].title == "Test Article"
            assert mock_get.call_count == 3

    def test_4xx_error_retries_and_raises(self) -> None:
        """Should retry on 4xx errors (RequestException) and raise after max retries."""
        source = Source(name="test_feed", type="rss", url="http://example.com/feed")

        with patch("radar.collector.requests.get") as mock_get:
            mock_get.side_effect = requests.exceptions.HTTPError("404 Not Found")

            with pytest.raises(requests.exceptions.HTTPError):
                _ = _collect_single(source, category="test", limit=10, timeout=15)

            assert mock_get.call_count == 3

    def test_max_retries_exceeded(self) -> None:
        """Should raise after 3 failed attempts."""
        source = Source(name="test_feed", type="rss", url="http://example.com/feed")

        with patch("radar.collector.requests.get") as mock_get:
            mock_get.side_effect = requests.exceptions.Timeout("timeout")

            with pytest.raises(requests.exceptions.Timeout):
                _ = _collect_single(source, category="test", limit=10, timeout=15)

            assert mock_get.call_count == 3

    def test_connection_error_retry(self) -> None:
        """Should retry on connection errors."""
        source = Source(name="test_feed", type="rss", url="http://example.com/feed")

        with patch("radar.collector.requests.get") as mock_get:
            mock_response = Mock()
            mock_response.content = b"""<?xml version="1.0"?>
<rss version="2.0">
    <channel>
        <item>
            <title>Test Article</title>
            <link>http://example.com/article</link>
            <description>Test summary</description>
            <pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate>
        </item>
    </channel>
</rss>"""
            mock_response.raise_for_status = Mock()

            mock_get.side_effect = [
                requests.exceptions.ConnectionError("connection failed"),
                requests.exceptions.ConnectionError("connection failed"),
                mock_response,
            ]

            articles = _collect_single(source, category="test", limit=10, timeout=15)

            assert len(articles) == 1
            assert mock_get.call_count == 3
