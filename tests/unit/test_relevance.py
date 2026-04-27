from __future__ import annotations

import pytest

from blogradar.models import Article, Source
from blogradar.relevance import apply_source_context_entities, filter_relevant_articles


pytestmark = pytest.mark.unit


def _article(
    *,
    title: str,
    source: str,
    summary: str | None = None,
    matched_entities: dict[str, list[str]] | None = None,
) -> Article:
    return Article(
        title=title,
        link=f"https://example.com/{title}",
        summary=summary if summary is not None else title,
        published=None,
        source=source,
        category="techblog",
        matched_entities=matched_entities or {},
    )


def test_apply_source_context_entities_adds_release_signal() -> None:
    article = _article(title="Kubernetes v1.36 Sneak Peek", source="Kubernetes Blog")
    source = Source(
        name="Kubernetes Blog",
        type="rss",
        url="https://kubernetes.io/feed.xml",
        content_type="release_note",
        producer_role="open_source_maintainer",
        info_purpose=["release", "version"],
    )

    classified = apply_source_context_entities([article], [source])

    assert "repository_release" in classified[0].matched_entities["SourceSignal"]
    assert "open_source_maintainer" in classified[0].matched_entities["SourceSignal"]


def test_filter_relevant_articles_drops_dev_to_spam() -> None:
    source = Source(name="Dev.to - Open Source", type="rss", url="https://dev.to/feed/tag/opensource")
    article = _article(
        title="Top 4 Sites To Buy Verified Okx Accounts In 2026",
        source="Dev.to - Open Source",
        summary="Telegram: @progmbofficial WhatsApp: +1 984 verified OKX accounts",
        matched_entities={"Domain": ["security"], "Framework": ["rest"]},
    )

    assert filter_relevant_articles([article], [source]) == []


def test_filter_relevant_articles_keeps_unmatched_authoritative_tech_source() -> None:
    source = Source(
        name="OpenAI News",
        type="rss",
        url="https://openai.com/news/rss.xml",
        content_type="model_release",
        producer_role="model_platform",
        info_purpose=["release", "api_update"],
    )
    article = _article(
        title="Using projects in ChatGPT",
        source="OpenAI News",
        matched_entities={},
    )

    filtered = filter_relevant_articles(
        apply_source_context_entities([article], [source]),
        [source],
    )

    assert filtered == [article]


def test_filter_relevant_articles_drops_non_tech_hacker_news_row() -> None:
    source = Source(name="Hacker News Best", type="rss", url="https://hnrss.org/newest")
    article = _article(
        title="Costasiella kuroshimae - Solar Powered animals",
        source="Hacker News Best",
        summary="Wikipedia article about indirect photosynthesis",
        matched_entities={},
    )

    assert filter_relevant_articles([article], [source]) == []


def test_filter_relevant_articles_keeps_agent_coding_discussion() -> None:
    source = Source(name="r/coding", type="reddit", url="https://www.reddit.com/r/coding/")
    article = _article(
        title="Agent Skills Are Becoming the Best Way to Capture Institutional Knowledge",
        source="r/coding",
        matched_entities={},
    )

    assert filter_relevant_articles([article], [source]) == [article]


def test_filter_relevant_articles_drops_capital_ai_substring_false_positive() -> None:
    source = Source(name="Sequoia Capital", type="rss", url="https://www.sequoiacap.com/feed/")
    article = _article(
        title="From Hierarchy to Intelligence",
        source="Sequoia Capital",
        summary="A general capital market essay.",
        matched_entities={},
    )

    assert filter_relevant_articles([article], [source]) == []
