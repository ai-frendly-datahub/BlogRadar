from __future__ import annotations

from unittest.mock import patch

import pytest

from blogradar.models import Article, Source
from blogradar.storage import RadarStorage


@pytest.mark.integration
def test_collection_workflow(sample_articles: list[Article]) -> None:
    with patch("blogradar.collector.collect_sources") as mock_collect:
        mock_collect.return_value = (sample_articles, [])

        articles, errors = mock_collect(
            [Source(name="python_blog", type="rss", url="https://techblog.example.com/feed")],
            category="techblog",
            limit_per_source=30,
        )

        assert len(articles) == 5
        assert len(errors) == 0
        assert all(isinstance(a, Article) for a in articles)
        assert all(a.category == "techblog" for a in articles)


@pytest.mark.integration
def test_storage_persistence(
    tmp_storage: RadarStorage,
    sample_articles: list[Article],
) -> None:
    tmp_storage.upsert_articles(sample_articles)

    articles = tmp_storage.recent_articles(category="techblog", days=30, limit=100)

    assert len(articles) == 5
    assert all(a.category == "techblog" for a in articles)
    links = {a.link for a in articles}
    assert "https://techblog.example.com/python-3-13-features" in links
    assert "https://techblog.example.com/rust-web-server" in links


@pytest.mark.integration
def test_duplicate_handling(
    tmp_storage: RadarStorage,
    sample_articles: list[Article],
) -> None:
    tmp_storage.upsert_articles(sample_articles[:2])
    result1 = tmp_storage.recent_articles(category="techblog", days=30, limit=100)
    assert len(result1) == 2

    tmp_storage.upsert_articles(sample_articles[:2])
    result2 = tmp_storage.recent_articles(category="techblog", days=30, limit=100)
    assert len(result2) == 2

    tmp_storage.upsert_articles(sample_articles[2:])
    result3 = tmp_storage.recent_articles(category="techblog", days=30, limit=100)
    assert len(result3) == 5
