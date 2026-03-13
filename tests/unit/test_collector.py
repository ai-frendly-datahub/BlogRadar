"""Unit tests for blogradar collector."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from blogradar.collector import _extract_datetime, collect_sources
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
def test_extract_datetime_none():
    entry = {}
    result = _extract_datetime(entry)
    assert result is None


@pytest.mark.unit
def test_collect_sources_network_error():
    source = Source(name="bad-source", type="rss", url="https://invalid-url-xyz.example.com/feed")
    with patch("blogradar.collector._fetch_url_with_retry", side_effect=Exception("Connection failed")):
        articles, errors = collect_sources([source], category="techblog")
    assert len(errors) == 1
