from __future__ import annotations

import pytest

from blogradar.models import Article, EntityDefinition


def _apply_rules(articles: list[Article], entities: list[EntityDefinition]) -> list[Article]:
    analyzed: list[Article] = []
    lowered = [
        EntityDefinition(
            name=e.name,
            display_name=e.display_name,
            keywords=[kw.lower() for kw in e.keywords],
        )
        for e in entities
    ]
    for article in articles:
        haystack = f"{article.title}\n{article.summary}".lower()
        matches: dict[str, list[str]] = {}
        for entity, lowered_entity in zip(entities, lowered):
            hits = [kw for kw in lowered_entity.keywords if kw and kw in haystack]
            if hits:
                matches[entity.name] = hits
        article.matched_entities = matches
        analyzed.append(article)
    return analyzed


@pytest.mark.integration
def test_entity_extraction_integration(
    sample_articles: list[Article],
    sample_entities: list[EntityDefinition],
) -> None:
    analyzed = _apply_rules(sample_articles, sample_entities)

    assert len(analyzed) == 5
    assert all(isinstance(a, Article) for a in analyzed)

    python_article = analyzed[0]
    assert "language" in python_article.matched_entities
    assert "python" in python_article.matched_entities["language"]

    react_article = analyzed[1]
    assert "framework" in react_article.matched_entities
    assert "react" in react_article.matched_entities["framework"]

    k8s_article = analyzed[2]
    assert "domain" in k8s_article.matched_entities
    assert "kubernetes" in k8s_article.matched_entities["domain"]

    fastapi_article = analyzed[3]
    assert "framework" in fastapi_article.matched_entities
    assert "fastapi" in fastapi_article.matched_entities["framework"]

    rust_article = analyzed[4]
    assert "language" in rust_article.matched_entities
    assert "rust" in rust_article.matched_entities["language"]


@pytest.mark.integration
def test_no_false_positives(
    sample_articles: list[Article],
    sample_entities: list[EntityDefinition],
) -> None:
    analyzed = _apply_rules(sample_articles, sample_entities)

    for article in analyzed:
        for entity_name, keywords in article.matched_entities.items():
            haystack = f"{article.title}\n{article.summary}".lower()
            for kw in keywords:
                assert kw in haystack, f"Keyword '{kw}' not found in article: {article.title}"
