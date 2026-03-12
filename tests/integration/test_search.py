from __future__ import annotations

from pathlib import Path

import pytest

from blogradar.models import Article
from blogradar.search_index import SearchIndex


@pytest.mark.integration
def test_search_index_integration(
    tmp_path: Path,
    sample_articles: list[Article],
) -> None:
    search_db = tmp_path / "search.db"

    with SearchIndex(search_db) as index:
        for article in sample_articles:
            index.upsert(
                link=article.link,
                title=article.title,
                body=article.summary,
            )

        results_python = index.search("Python", limit=10)
        assert len(results_python) >= 1
        assert any("Python" in r.title for r in results_python)

        results_react = index.search("React", limit=10)
        assert len(results_react) >= 1

        results_empty = index.search("nonexistent_keyword_xyz_abc_123", limit=10)
        assert len(results_empty) == 0


@pytest.mark.integration
def test_search_upsert_deduplication(
    tmp_path: Path,
    sample_articles: list[Article],
) -> None:
    search_db = tmp_path / "search_dedup.db"
    article = sample_articles[0]

    with SearchIndex(search_db) as index:
        index.upsert(link=article.link, title=article.title, body=article.summary)
        index.upsert(link=article.link, title="Updated Title", body="Updated body")

        results = index.search("Updated", limit=10)
        assert len(results) >= 1
