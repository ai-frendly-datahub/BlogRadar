"""Unit tests for blogradar analyzer."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone

from blogradar.analyzer import apply_entity_rules
from blogradar.models import Article, EntityDefinition


def _make_article(title: str = "", summary: str = "") -> Article:
    return Article(
        title=title,
        link="https://example.com/post",
        summary=summary,
        published=datetime.now(timezone.utc),
        source="test",
        category="techblog",
    )


@pytest.mark.unit
def test_entity_match_in_title():
    articles = [_make_article(title="Using Python for data engineering")]
    entities = [EntityDefinition(name="Language", display_name="Language", keywords=["python"])]
    result = apply_entity_rules(articles, entities)
    assert "Language" in result[0].matched_entities
    assert "python" in result[0].matched_entities["Language"]


@pytest.mark.unit
def test_entity_match_case_insensitive():
    articles = [_make_article(summary="We use KUBERNETES for orchestration")]
    entities = [EntityDefinition(name="Framework", display_name="Framework", keywords=["kubernetes"])]
    result = apply_entity_rules(articles, entities)
    assert "Framework" in result[0].matched_entities


@pytest.mark.unit
def test_no_match_returns_empty():
    articles = [_make_article(title="A random post")]
    entities = [EntityDefinition(name="Domain", display_name="Domain", keywords=["rust", "go"])]
    result = apply_entity_rules(articles, entities)
    assert result[0].matched_entities == {}


@pytest.mark.unit
def test_empty_articles():
    result = apply_entity_rules([], [])
    assert result == []
