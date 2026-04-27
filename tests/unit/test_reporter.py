from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from blogradar.models import Article, CategoryConfig, Source
from blogradar.reporter import generate_report


pytestmark = pytest.mark.unit


def test_generate_report_includes_blog_quality_panel(tmp_path: Path) -> None:
    category = CategoryConfig(
        category_name="techblog",
        display_name="Tech Blog",
        sources=[Source(name="Kubernetes Blog", type="rss", url="https://example.com")],
        entities=[],
    )
    article = Article(
        title="Kubernetes v1.36 Sneak Peek",
        link="https://example.com/kubernetes",
        summary="release notes",
        published=datetime(2026, 4, 13, tzinfo=UTC),
        source="Kubernetes Blog",
        category="techblog",
        matched_entities={"Framework": ["kubernetes"]},
    )
    quality_report = {
        "generated_at": "2026-04-13T00:00:00+00:00",
        "summary": {
            "operational_adoption_event_count": 1,
            "repository_canonical_key_present_count": 1,
            "package_canonical_key_present_count": 0,
            "technology_proxy_key_count": 0,
            "event_required_field_gap_count": 1,
            "daily_review_item_count": 1,
        },
        "events": [
            {
                "event_model": "repository_release",
                "source": "Kubernetes Blog",
                "canonical_key": "repository:github.com:kubernetes:kubernetes",
                "signal_basis": "source_contract_signal",
            }
        ],
        "daily_review_items": [
            {
                "reason": "missing_required_fields",
                "event_model": "repository_release",
                "source": "Kubernetes Blog",
                "required_field_gaps": ["release_tag"],
            }
        ],
    }

    output_path = tmp_path / "techblog_report.html"
    result = generate_report(
        category=category,
        articles=[article],
        output_path=output_path,
        stats={"sources": 1, "matched": 1},
        quality_report=quality_report,
    )

    html = result.read_text(encoding="utf-8")
    assert "Blog Quality" in html
    assert "repository_release" in html
    assert "repository:github.com:kubernetes:kubernetes" in html
    assert "missing_required_fields" in html

    dated_html = next(
        tmp_path.glob("techblog_[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].html")
    )
    dated_text = dated_html.read_text(encoding="utf-8")
    assert "Blog Quality" in dated_text
    assert "missing_required_fields" in dated_text

    summaries = sorted(
        tmp_path.glob("techblog_[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]_summary.json")
    )
    assert len(summaries) == 1
    summary = summaries[0].read_text(encoding="utf-8")
    assert '"repo": "BlogRadar"' in summary
    assert '"ontology_version": "0.1.0"' in summary
    assert '"tech.repository_release"' in summary
