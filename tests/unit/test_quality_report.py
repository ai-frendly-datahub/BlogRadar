from __future__ import annotations

from datetime import UTC, datetime

import pytest

from blogradar.models import Article, CategoryConfig, Source
from blogradar.quality_report import build_quality_report


pytestmark = pytest.mark.unit


def test_build_quality_report_tracks_repository_release_sources() -> None:
    source = Source(
        name="Kubernetes Blog",
        type="rss",
        url="https://kubernetes.io/feed.xml",
        content_type="release_note",
        producer_role="open_source_maintainer",
        info_purpose=["release", "version"],
    )
    category = CategoryConfig(
        category_name="techblog",
        display_name="Tech Blog",
        sources=[source],
        entities=[],
    )
    article = Article(
        title="Kubernetes v1.36 Sneak Peek",
        link="https://kubernetes.io/blog/v1-36",
        summary="release notes",
        published=datetime(2026, 4, 12, tzinfo=UTC),
        source="Kubernetes Blog",
        category="techblog",
        matched_entities={
            "Framework": ["kubernetes"],
            "SourceSignal": ["repository_release"],
        },
    )

    report = build_quality_report(
        category=category,
        articles=[article],
        quality_config={
            "data_quality": {
                "quality_outputs": {"tracked_event_models": ["repository_release"]},
                "freshness_sla": {"repository_release_days": 3},
            }
        },
        generated_at=datetime(2026, 4, 13, tzinfo=UTC),
    )

    assert report["summary"]["tracked_sources"] == 1
    assert report["summary"]["fresh_sources"] == 1
    assert report["summary"]["repository_release_events"] == 1
    assert report["summary"]["repository_canonical_key_present_count"] == 1
    assert report["summary"]["event_required_field_gap_count"] == 0
    assert report["sources"][0]["event_model"] == "repository_release"
    assert report["events"][0]["canonical_key"] == "repository:github.com:kubernetes:kubernetes"
    assert report["events"][0]["framework"] == ["kubernetes"]


def test_build_quality_report_marks_missing_tracked_source() -> None:
    source = Source(
        name="Go Blog",
        type="rss",
        url="https://go.dev/blog/feed.atom",
        content_type="release_note",
        info_purpose=["release"],
    )
    category = CategoryConfig(
        category_name="techblog",
        display_name="Tech Blog",
        sources=[source],
        entities=[],
    )

    report = build_quality_report(
        category=category,
        articles=[],
        quality_config={
            "data_quality": {
                "quality_outputs": {"tracked_event_models": ["repository_release"]}
            }
        },
        generated_at=datetime(2026, 4, 13, tzinfo=UTC),
    )

    assert report["summary"]["missing_sources"] == 1
    assert report["sources"][0]["status"] == "missing"


def test_source_level_freshness_sla_overrides_default_release_cadence() -> None:
    source = Source(
        name="Go Blog",
        type="rss",
        url="https://go.dev/blog/feed.atom",
        content_type="release_note",
        info_purpose=["release"],
        config={"freshness_sla_days": 45},
    )
    category = CategoryConfig(
        category_name="techblog",
        display_name="Tech Blog",
        sources=[source],
        entities=[],
    )
    article = Article(
        title="Go release notes",
        link="https://go.dev/blog/release",
        summary="Version: 1.25.",
        published=datetime(2026, 3, 23, tzinfo=UTC),
        source="Go Blog",
        category="techblog",
        matched_entities={"SourceSignal": ["repository_release"]},
    )

    report = build_quality_report(
        category=category,
        articles=[article],
        quality_config={
            "data_quality": {
                "quality_outputs": {"tracked_event_models": ["repository_release"]},
                "freshness_sla": {"repository_release_days": 3},
            }
        },
        generated_at=datetime(2026, 4, 22, tzinfo=UTC),
    )

    assert report["summary"]["fresh_sources"] == 1
    assert report["summary"]["stale_sources"] == 0
    assert report["sources"][0]["freshness_sla_days"] == 45


def test_build_quality_report_extracts_package_github_and_skill_signals() -> None:
    package_source = Source(
        name="npm downloads",
        type="api",
        url="https://api.npmjs.org/downloads/point/last-week/react",
        trust_tier="T2_institutional",
        config={"event_model": "package_download"},
    )
    github_source = Source(
        name="GitHub Metrics",
        type="api",
        url="https://api.github.com/repos/vercel/next.js",
        trust_tier="T1_authoritative",
        config={"event_model": "github_activity"},
    )
    skill_source = Source(
        name="Public Skill Index",
        type="api",
        url="https://example.com/skills",
        trust_tier="T3_professional",
        config={"event_model": "skill_demand"},
    )
    category = CategoryConfig(
        category_name="techblog",
        display_name="Tech Blog",
        sources=[package_source, github_source, skill_source],
        entities=[],
    )
    articles = [
        Article(
            title="React npm package download metric",
            link="https://example.com/npm/react",
            summary="Package name: react. Registry: npm. Download count: 1200.",
            published=datetime(2026, 4, 13, tzinfo=UTC),
            source="npm downloads",
            category="techblog",
            matched_entities={"Framework": ["react"]},
        ),
        Article(
            title="Next.js GitHub activity",
            link="https://example.com/github/vercel-next",
            summary="Repository: github.com/vercel/next.js. Stars: 130,000. Forks: 28,000.",
            published=datetime(2026, 4, 13, tzinfo=UTC),
            source="GitHub Metrics",
            category="techblog",
            matched_entities={"Framework": ["next.js"]},
        ),
        Article(
            title="Skill demand for FastAPI",
            link="https://example.com/skills/fastapi",
            summary="Skill: FastAPI. Employer: Example Analytics.",
            published=datetime(2026, 4, 13, tzinfo=UTC),
            source="Public Skill Index",
            category="techblog",
            matched_entities={"Framework": ["fastapi"]},
        ),
    ]

    report = build_quality_report(
        category=category,
        articles=articles,
        quality_config={
            "data_quality": {
                "quality_outputs": {
                    "tracked_event_models": [
                        "package_download",
                        "github_activity",
                        "skill_demand",
                    ]
                }
            },
            "source_backlog": {
                "operational_candidates": [
                    {
                        "name": "GitHub release and star API",
                        "signal_type": "github_activity",
                        "activation_gate": "token/quota policy",
                    }
                ]
            },
        },
        generated_at=datetime(2026, 4, 14, tzinfo=UTC),
    )

    summary = report["summary"]
    assert summary["package_download_events"] == 1
    assert summary["github_activity_events"] == 1
    assert summary["skill_demand_events"] == 1
    assert summary["package_canonical_key_present_count"] == 1
    assert summary["repository_canonical_key_present_count"] == 1
    assert summary["event_required_field_gap_count"] == 0
    assert summary["source_backlog_candidate_count"] == 1

    events = {event["event_model"]: event for event in report["events"]}
    assert events["package_download"]["canonical_key"] == "package:npm:react"
    assert events["package_download"]["download_count"] == 1200
    assert events["github_activity"]["canonical_key"] == "repository:github.com:vercel:next.js"
    assert events["github_activity"]["stars"] == 130000
    assert events["skill_demand"]["canonical_key"] == "skill:python:fastapi:example-analytics"
    assert any(
        item["reason"] == "source_backlog_pending"
        for item in report["daily_review_items"]
    )
