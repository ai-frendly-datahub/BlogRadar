from __future__ import annotations

from pathlib import Path

import pytest

from blogradar.models import Article, CategoryConfig, EntityDefinition
from blogradar.reporter import generate_report


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
def test_report_generation(
    tmp_path: Path,
    sample_articles: list[Article],
    sample_entities: list[EntityDefinition],
    sample_config: CategoryConfig,
) -> None:
    analyzed = _apply_rules(sample_articles, sample_entities)

    output_path = tmp_path / "report.html"
    stats = {
        "sources": 1,
        "collected": len(analyzed),
        "matched": sum(1 for a in analyzed if a.matched_entities),
        "validated": len(analyzed),
        "window_days": 7,
    }

    result = generate_report(
        category=sample_config,
        articles=analyzed,
        output_path=output_path,
        stats=stats,
        errors=[],
    )

    assert result.exists()
    assert result.suffix == ".html"

    content = result.read_text(encoding="utf-8")
    assert "기술 블로그" in content
    assert "Python 3.13" in content
    assert "React 19" in content


@pytest.mark.integration
def test_report_generation_with_errors(
    tmp_path: Path,
    sample_articles: list[Article],
    sample_config: CategoryConfig,
) -> None:
    output_path = tmp_path / "report_with_errors.html"
    stats = {"sources": 1, "collected": 0, "matched": 0, "validated": 0, "window_days": 7}
    errors = ["python_blog: Connection timeout", "frontend_blog: HTTP 429"]

    result = generate_report(
        category=sample_config,
        articles=[],
        output_path=output_path,
        stats=stats,
        errors=errors,
    )

    assert result.exists()
    content = result.read_text(encoding="utf-8")
    assert content
