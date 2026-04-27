from __future__ import annotations

import re
from collections.abc import Iterable

from .models import Article, Source


SOURCE_CONTEXT_PURPOSES = {
    "api_update",
    "breaking_change",
    "changelog",
    "deprecation",
    "developer_adoption",
    "enterprise_adoption",
    "framework_adoption",
    "migration",
    "platform_update",
    "release",
    "rollout",
    "version",
}
AUTHORITATIVE_SOURCE_NAMES = {
    "Cloudflare Blog",
    "Go Blog",
    "Google Project Zero",
    "Kubernetes Blog",
    "OpenAI News",
    "PyTorch Blog",
    "Rust Blog",
}
BROAD_SOURCE_PREFIXES = ("Dev.to", "Hacker News", "r/")
BROAD_SOURCE_NAMES = {
    "ByteByteGo",
    "Fireship",
    "InfoQ",
    "Krebs on Security",
    "Sequoia Capital",
    "Software Engineering Daily",
    "Syntax.fm",
    "The New Stack",
    "The Pragmatic Engineer",
    "Theo - t3.gg",
    "Y Combinator Blog",
}
TECH_ENTITY_NAMES = {"Domain", "Framework", "Language", "Topic"}
WEAK_TOPIC_VALUES = {"설계"}
WEAK_DOMAIN_VALUES = {"platform", "플랫폼"}
TECH_TITLE_TERMS = {
    "agent",
    "ai",
    "api",
    "architecture",
    "backend",
    "build",
    "changelog",
    "cloud",
    "code",
    "coding",
    "copilot",
    "css",
    "developer",
    "development",
    "devops",
    "engineering",
    "framework",
    "frontend",
    "fuzzing",
    "github",
    "infrastructure",
    "kubernetes",
    "llm",
    "machine learning",
    "migration",
    "open source",
    "performance",
    "programming",
    "pytorch",
    "python",
    "release",
    "rust",
    "scaling",
    "security",
    "serverless",
    "software",
    "terraform",
    "개발",
    "기술",
    "리뷰",
    "머신러닝",
    "보안",
    "인프라",
    "프런트엔드",
    "프론트엔드",
}
SPAM_TERMS = {
    "buy verified",
    "kucoin account",
    "okx account",
    "plus-size lingerie",
    "telegram:",
    "underwear",
    "verified okx",
    "verified kucoin",
    "whatsapp:",
}


def apply_source_context_entities(
    articles: Iterable[Article],
    sources: Iterable[Source],
) -> list[Article]:
    source_map = {source.name: source for source in sources if source.enabled}
    classified: list[Article] = []
    for article in articles:
        if article.category != "techblog":
            classified.append(article)
            continue

        source = source_map.get(article.source)
        if source is None:
            continue

        tags = _source_context_tags(source)
        if not tags and _has_strong_text_signal(article):
            if _is_broad_source(source):
                tags.append("community_tech_signal")
            elif _is_korean_company_blog(source):
                tags.append("tech_blog_signal")
        if tags:
            existing = article.matched_entities.get("SourceSignal", [])
            existing_values = existing if isinstance(existing, list) else [existing]
            article.matched_entities["SourceSignal"] = sorted(
                {str(value) for value in existing_values} | set(tags)
            )
        classified.append(article)
    return classified


def filter_relevant_articles(
    articles: Iterable[Article],
    sources: Iterable[Source],
) -> list[Article]:
    source_map = {source.name: source for source in sources if source.enabled}
    filtered: list[Article] = []
    for article in articles:
        if article.category != "techblog":
            filtered.append(article)
            continue

        source = source_map.get(article.source)
        if source is None:
            continue
        if _is_spam_or_invalid(article):
            continue
        if _has_tech_signal(article, source):
            filtered.append(article)
    return filtered


def _has_tech_signal(article: Article, source: Source) -> bool:
    if _has_source_context(source):
        return True
    if _is_broad_source(source):
        return _has_strong_text_signal(article) or _has_strong_entity_signal(article)
    if _is_korean_company_blog(source):
        return _has_strong_entity_signal(article) or _has_strong_text_signal(article)
    return _has_strong_entity_signal(article) or _has_strong_text_signal(article)


def _has_source_context(source: Source) -> bool:
    return bool(_source_context_tags(source))


def _has_strong_entity_signal(article: Article) -> bool:
    for entity_name, values in article.matched_entities.items():
        if entity_name not in TECH_ENTITY_NAMES or not isinstance(values, list):
            continue
        normalized = {str(value).strip().lower() for value in values if str(value).strip()}
        if not normalized:
            continue
        if entity_name == "Topic" and normalized <= WEAK_TOPIC_VALUES:
            continue
        if entity_name == "Domain" and normalized <= WEAK_DOMAIN_VALUES:
            continue
        return True
    return False


def _has_strong_text_signal(article: Article) -> bool:
    text = f"{article.title} {article.summary}".lower()
    return any(_contains_term(text, term) for term in TECH_TITLE_TERMS)


def _source_context_tags(source: Source) -> list[str]:
    tags = {purpose for purpose in source.info_purpose if purpose in SOURCE_CONTEXT_PURPOSES}
    event_model = _source_event_model(source)
    if event_model:
        tags.add(event_model)
    if source.name in AUTHORITATIVE_SOURCE_NAMES:
        tags.add("authoritative_tech_source")
    if source.producer_role in {"open_source_maintainer", "model_platform", "vendor_platform"}:
        tags.add(source.producer_role)
    if source.content_type in {"changelog", "model_release", "product_update", "release_note"}:
        tags.add(source.content_type)
    if "Engineering" in source.name or "엔지니어링" in source.name:
        tags.add("engineering_blog")
    return sorted(tags)


def _source_event_model(source: Source) -> str:
    raw = source.config.get("event_model")
    if raw is not None and str(raw).strip():
        return str(raw).strip()
    purposes = set(source.info_purpose)
    if source.content_type in {"changelog", "model_release", "product_update", "release_note"}:
        return "repository_release"
    if purposes & {
        "api_update",
        "breaking_change",
        "changelog",
        "deprecation",
        "migration",
        "platform_update",
        "release",
        "rollout",
        "version",
    }:
        return "repository_release"
    if "skill_demand" in purposes:
        return "skill_demand"
    return ""


def _is_broad_source(source: Source) -> bool:
    return source.name in BROAD_SOURCE_NAMES or source.name.startswith(BROAD_SOURCE_PREFIXES)


def _is_korean_company_blog(source: Source) -> bool:
    return "기술블로그" in source.name


def _is_spam_or_invalid(article: Article) -> bool:
    text = f"{article.title} {article.summary}".lower()
    if any(term in text for term in SPAM_TERMS):
        return True
    return any(
        marker in text
        for marker in (
            "404",
            "access denied",
            "not found",
            "page not found",
            "service unavailable",
        )
    )


def _contains_term(text: str, term: str) -> bool:
    normalized = term.lower()
    if normalized.isascii() and re.fullmatch(r"[a-z0-9][a-z0-9.+#-]*", normalized):
        return re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", text) is not None
    return normalized in text
