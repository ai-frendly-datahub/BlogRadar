"""Unit tests for blogradar storage."""
from __future__ import annotations

import pytest
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from blogradar.storage import RadarStorage
from blogradar.models import Article


def _make_article(link: str = "https://example.com/1") -> Article:
    return Article(
        title="Test Post",
        link=link,
        summary="A test article about python and kubernetes",
        published=datetime.now(timezone.utc),
        source="test-source",
        category="techblog",
        matched_entities={"Language": ["python"]},
    )


@pytest.mark.unit
def test_upsert_and_query():
    with tempfile.NamedTemporaryFile(suffix=".duckdb", delete=True) as f:
        db_path = Path(f.name)
    storage = RadarStorage(db_path)
    article = _make_article()
    storage.upsert_articles([article])
    results = storage.recent_articles("techblog", days=1)
    assert len(results) == 1
    assert results[0].title == "Test Post"
    storage.close()
    db_path.unlink(missing_ok=True)


@pytest.mark.unit
def test_upsert_deduplication():
    with tempfile.NamedTemporaryFile(suffix=".duckdb", delete=True) as f:
        db_path = Path(f.name)
    storage = RadarStorage(db_path)
    article = _make_article()
    storage.upsert_articles([article])
    storage.upsert_articles([article])  # duplicate
    results = storage.recent_articles("techblog", days=1)
    assert len(results) == 1
    storage.close()
    db_path.unlink(missing_ok=True)


@pytest.mark.unit
def test_empty_upsert():
    with tempfile.NamedTemporaryFile(suffix=".duckdb", delete=True) as f:
        db_path = Path(f.name)
    storage = RadarStorage(db_path)
    storage.upsert_articles([])
    results = storage.recent_articles("techblog", days=7)
    assert results == []
    storage.close()
    db_path.unlink(missing_ok=True)
