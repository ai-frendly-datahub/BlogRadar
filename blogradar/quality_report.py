from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .models import Article, CategoryConfig, Source


TRACKED_EVENT_MODEL_ORDER = [
    "repository_release",
    "package_download",
    "github_activity",
    "skill_demand",
]
TRACKED_EVENT_MODELS = set(TRACKED_EVENT_MODEL_ORDER)
REQUIRED_FIELDS = {
    "repository_release": ["repository", "release_tag", "source_url"],
    "package_download": ["package_name", "registry", "download_count"],
    "github_activity": ["repository", "stars", "forks"],
    "skill_demand": ["skill", "employer", "source_url"],
}
SUMMARY_LABELS = [
    "Repository",
    "Repo",
    "GitHub repository",
    "Release tag",
    "Version",
    "Tag",
    "Package name",
    "Package",
    "Registry",
    "Download count",
    "Downloads",
    "Stars",
    "Forks",
    "Skill",
    "Employer",
    "Technology",
    "Ecosystem",
]
KNOWN_SOURCE_REPOSITORIES = {
    "Kubernetes Blog": "github.com/kubernetes/kubernetes",
    "Helm Blog": "github.com/helm/helm",
    "Go Blog": "github.com/golang/go",
    "Rust Blog": "github.com/rust-lang/rust",
    "PyTorch Blog": "github.com/pytorch/pytorch",
    "TensorFlow Blog": "github.com/tensorflow/tensorflow",
}
KNOWN_SOURCE_TECHNOLOGIES = {
    "Kubernetes Blog": "kubernetes",
    "Helm Blog": "helm",
    "Go Blog": "go",
    "Rust Blog": "rust",
    "PyTorch Blog": "pytorch",
    "TensorFlow Blog": "tensorflow",
    "OpenAI News": "openai",
    "Vercel Blog": "vercel",
    "Cloudflare Blog": "cloudflare",
    "HashiCorp Blog": "terraform",
    "GitHub Blog Engineering": "github",
}
ECOSYSTEM_BY_TERM = {
    "aws": "cloud",
    "cloudflare": "cloud",
    "docker": "cloud-native",
    "fastapi": "python",
    "go": "go",
    "golang": "go",
    "gpt": "ai",
    "helm": "cloud-native",
    "k8s": "cloud-native",
    "kubernetes": "cloud-native",
    "llm": "ai",
    "next.js": "javascript",
    "openai": "ai",
    "pytorch": "python",
    "python": "python",
    "react": "javascript",
    "rust": "rust",
    "tensorflow": "python",
    "terraform": "infrastructure",
    "typescript": "javascript",
    "vercel": "javascript",
}


def build_quality_report(
    *,
    category: CategoryConfig,
    articles: Iterable[Article],
    errors: Iterable[str] | None = None,
    quality_config: Mapping[str, object] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated = _as_utc(generated_at or datetime.now(UTC))
    articles_list = list(articles)
    errors_list = [str(error) for error in (errors or [])]
    quality = _dict(quality_config or {}, "data_quality")
    freshness_sla = _dict(quality, "freshness_sla")
    tracked_event_models = _tracked_event_models(quality)

    events = _build_event_rows(
        sources=category.sources,
        articles=articles_list,
        tracked_event_models=tracked_event_models,
    )
    source_rows = [
        _build_source_row(
            source=source,
            articles=articles_list,
            event_rows=events,
            errors=errors_list,
            freshness_sla=freshness_sla,
            tracked_event_models=tracked_event_models,
            generated_at=generated,
        )
        for source in category.sources
    ]

    status_counts = Counter(str(row["status"]) for row in source_rows)
    event_counts = Counter(str(row["event_model"]) for row in events)
    summary = {
        "total_sources": len(source_rows),
        "tracked_sources": sum(1 for row in source_rows if row["tracked"]),
        "fresh_sources": status_counts.get("fresh", 0),
        "stale_sources": status_counts.get("stale", 0),
        "missing_sources": status_counts.get("missing", 0),
        "missing_event_sources": status_counts.get("missing_event", 0),
        "unknown_event_date_sources": status_counts.get("unknown_event_date", 0),
        "not_tracked_sources": status_counts.get("not_tracked", 0),
        "skipped_disabled_sources": status_counts.get("skipped_disabled", 0),
        "collection_error_count": len(errors_list),
    }
    for event_model in TRACKED_EVENT_MODEL_ORDER:
        summary[f"{event_model}_events"] = event_counts.get(event_model, 0)
    summary.update(_event_quality_summary(events, source_rows, quality_config or {}))
    daily_review_items = _daily_review_items(events, source_rows, quality_config or {})
    summary["daily_review_item_count"] = len(daily_review_items)

    return {
        "category": category.category_name,
        "generated_at": generated.isoformat(),
        "scope_note": (
            "Blog and community mention volume is separated from operational "
            "adoption signals. Current repository/package/github/skill rows are "
            "article-level proxies until API-backed sources are activated."
        ),
        "summary": summary,
        "sources": source_rows,
        "events": events,
        "daily_review_items": daily_review_items,
        "source_backlog": (quality_config or {}).get("source_backlog", {}),
        "errors": errors_list,
    }


def write_quality_report(
    report: Mapping[str, object],
    *,
    output_dir: Path,
    category_name: str,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = _parse_datetime(str(report.get("generated_at") or "")) or datetime.now(UTC)
    date_stamp = _as_utc(generated_at).strftime("%Y%m%d")
    latest_path = output_dir / f"{category_name}_quality.json"
    dated_path = output_dir / f"{category_name}_{date_stamp}_quality.json"
    encoded = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    latest_path.write_text(encoded + "\n", encoding="utf-8")
    dated_path.write_text(encoded + "\n", encoding="utf-8")
    return {"latest": latest_path, "dated": dated_path}


def _build_event_rows(
    *,
    sources: list[Source],
    articles: list[Article],
    tracked_event_models: set[str],
) -> list[dict[str, Any]]:
    source_map = {source.name: source for source in sources}
    rows: list[dict[str, Any]] = []
    for article in articles:
        source = source_map.get(article.source)
        if source is None:
            continue
        event_models = _article_event_models(article, source, tracked_event_models)
        event_at = _event_datetime(article, source)
        for event_model in event_models:
            rows.append(_event_row(article, source, event_model, event_at))
    return rows


def _event_row(
    article: Article,
    source: Source,
    event_model: str,
    event_at: datetime | None,
) -> dict[str, Any]:
    repository = _repository(article, source)
    host, owner, repo_name = _repository_parts(repository)
    package_name = _package_name(article)
    registry = _registry(article, source, package_name)
    technology = _technology(article, source, package_name, repo_name)
    ecosystem = _ecosystem(article, source, technology, registry)
    skill = _skill(article, source, technology)
    employer = _employer(article, source)
    row: dict[str, Any] = {
        "source": source.name,
        "source_type": source.type,
        "trust_tier": source.trust_tier,
        "producer_role": source.producer_role,
        "event_model": event_model,
        "title": article.title,
        "url": article.link,
        "source_url": article.link,
        "event_at": event_at.isoformat() if event_at else None,
        "event_key": _event_key(article, source, event_model, event_at),
        "repository": repository,
        "repository_host": host,
        "repository_owner": owner,
        "repository_name": repo_name,
        "release_tag": _release_tag(article),
        "package_name": package_name,
        "registry": registry,
        "download_count": _int_value(_summary_value(article, "Download count", "Downloads")),
        "stars": _int_value(_summary_value(article, "Stars")),
        "forks": _int_value(_summary_value(article, "Forks")),
        "skill": skill,
        "employer": employer,
        "technology": technology,
        "ecosystem": ecosystem,
        "domain": _matches(article, "Domain"),
        "language": _matches(article, "Language"),
        "framework": _matches(article, "Framework"),
        "topic": _matches(article, "Topic"),
        "source_signal": _matches(article, "SourceSignal"),
        "signal_basis": _signal_basis(article, source, event_model),
    }
    canonical_key, canonical_status = _canonical_key(row)
    row["canonical_key"] = canonical_key
    row["canonical_key_status"] = canonical_status
    row["required_field_gaps"] = _required_field_gaps(event_model, row)
    return row


def _build_source_row(
    *,
    source: Source,
    articles: list[Article],
    event_rows: list[dict[str, Any]],
    errors: list[str],
    freshness_sla: Mapping[str, object],
    tracked_event_models: set[str],
    generated_at: datetime,
) -> dict[str, Any]:
    source_articles = [article for article in articles if article.source == source.name]
    source_errors = [error for error in errors if error.startswith(f"{source.name}:")]
    event_model = _source_event_model(source)
    source_event_rows = [
        row
        for row in event_rows
        if row["source"] == source.name and row["event_model"] == event_model
    ]
    latest_event = _latest_event(source_event_rows)
    latest_event_at = _parse_datetime(str(latest_event.get("event_at") or "")) if latest_event else None
    sla_days = _source_sla_days(source, event_model, freshness_sla)
    age_days = _age_days(generated_at, latest_event_at) if latest_event_at else None
    status = _source_status(
        source=source,
        event_model=event_model,
        tracked_event_models=tracked_event_models,
        article_count=len(source_articles),
        event_count=len(source_event_rows),
        latest_event_at=latest_event_at,
        sla_days=sla_days,
        age_days=age_days,
    )

    return {
        "source": source.name,
        "source_type": source.type,
        "enabled": source.enabled,
        "trust_tier": source.trust_tier,
        "content_type": source.content_type,
        "collection_tier": source.collection_tier,
        "producer_role": source.producer_role,
        "info_purpose": source.info_purpose,
        "tracked": event_model in tracked_event_models,
        "event_model": event_model,
        "freshness_sla_days": sla_days,
        "status": status,
        "article_count": len(source_articles),
        "event_count": len(source_event_rows),
        "latest_event_at": latest_event_at.isoformat() if latest_event_at else None,
        "age_days": round(age_days, 2) if age_days is not None else None,
        "latest_title": str(latest_event.get("title", "")) if latest_event else "",
        "latest_url": str(latest_event.get("url", "")) if latest_event else "",
        "latest_domain": latest_event.get("domain", []) if latest_event else [],
        "latest_language": latest_event.get("language", []) if latest_event else [],
        "latest_framework": latest_event.get("framework", []) if latest_event else [],
        "latest_topic": latest_event.get("topic", []) if latest_event else [],
        "latest_source_signal": latest_event.get("source_signal", []) if latest_event else [],
        "latest_canonical_key": str(latest_event.get("canonical_key", "")) if latest_event else "",
        "latest_required_field_gaps": latest_event.get("required_field_gaps", []) if latest_event else [],
        "errors": source_errors,
    }


def _article_event_models(
    article: Article,
    source: Source,
    tracked_event_models: set[str],
) -> list[str]:
    values: set[str] = set()
    source_event_model = _source_event_model(source)
    if source_event_model in tracked_event_models:
        values.add(source_event_model)
    for entity_key in ("OperationalEvent", "SourceSignal"):
        for event_model in _matches(article, entity_key):
            if event_model in tracked_event_models:
                values.add(event_model)
    return [event_model for event_model in TRACKED_EVENT_MODEL_ORDER if event_model in values]


def _event_quality_summary(
    events: list[dict[str, Any]],
    source_rows: list[dict[str, Any]],
    quality_config: Mapping[str, object],
) -> dict[str, int]:
    backlog = _source_backlog_items(quality_config)
    return {
        "operational_adoption_event_count": len(events),
        "authoritative_event_count": sum(
            1 for row in events if str(row.get("trust_tier", "")).startswith(("T1", "T2"))
        ),
        "community_event_count": sum(
            1
            for row in events
            if row.get("source_type") == "reddit"
            or str(row.get("trust_tier", "")).startswith("T4")
        ),
        "repository_canonical_key_present_count": sum(
            1
            for row in events
            if row.get("event_model") in {"repository_release", "github_activity"}
            and str(row.get("canonical_key", "")).startswith("repository:")
        ),
        "package_canonical_key_present_count": sum(
            1
            for row in events
            if row.get("event_model") == "package_download"
            and str(row.get("canonical_key", "")).startswith("package:")
        ),
        "technology_proxy_key_count": sum(
            1 for row in events if row.get("canonical_key_status") == "technology_proxy"
        ),
        "missing_canonical_key_count": sum(
            1 for row in events if row.get("canonical_key_status") == "missing"
        ),
        "event_required_field_gap_count": sum(
            len(row.get("required_field_gaps", []))
            for row in events
            if isinstance(row.get("required_field_gaps"), list)
        ),
        "tracked_source_gap_count": sum(
            1
            for row in source_rows
            if row.get("tracked")
            and row.get("status") in {"missing", "missing_event", "unknown_event_date", "stale"}
        ),
        "source_backlog_candidate_count": len(backlog),
        "missing_event_model_count": sum(
            1
            for event_model in TRACKED_EVENT_MODEL_ORDER
            if not any(row.get("event_model") == event_model for row in events)
        ),
    }


def _daily_review_items(
    events: list[dict[str, Any]],
    source_rows: list[dict[str, Any]],
    quality_config: Mapping[str, object],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in events:
        gaps = row.get("required_field_gaps")
        if isinstance(gaps, list) and gaps:
            items.append(
                {
                    "reason": "missing_required_fields",
                    "event_model": row.get("event_model"),
                    "source": row.get("source"),
                    "title": row.get("title"),
                    "event_key": row.get("event_key"),
                    "required_field_gaps": gaps,
                }
            )
        if row.get("canonical_key_status") == "missing":
            items.append(
                {
                    "reason": "missing_canonical_key",
                    "event_model": row.get("event_model"),
                    "source": row.get("source"),
                    "title": row.get("title"),
                    "event_key": row.get("event_key"),
                }
            )
        elif row.get("canonical_key_status") == "technology_proxy":
            items.append(
                {
                    "reason": "technology_proxy_canonical_key",
                    "event_model": row.get("event_model"),
                    "source": row.get("source"),
                    "title": row.get("title"),
                    "event_key": row.get("event_key"),
                    "canonical_key": row.get("canonical_key"),
                }
            )

    for row in source_rows:
        if row.get("tracked") and row.get("status") in {
            "missing",
            "missing_event",
            "unknown_event_date",
            "stale",
        }:
            items.append(
                {
                    "reason": f"source_{row.get('status')}",
                    "event_model": row.get("event_model"),
                    "source": row.get("source"),
                    "latest_title": row.get("latest_title"),
                    "age_days": row.get("age_days"),
                }
            )

    for event_model in TRACKED_EVENT_MODEL_ORDER:
        if not any(row.get("event_model") == event_model for row in events):
            items.append({"reason": "missing_event_model", "event_model": event_model})

    for backlog_item in _source_backlog_items(quality_config):
        items.append(
            {
                "reason": "source_backlog_pending",
                "event_model": backlog_item.get("signal_type", ""),
                "source": backlog_item.get("name", ""),
                "activation_gate": backlog_item.get("activation_gate", ""),
            }
        )
    return items[:50]


def _source_backlog_items(quality_config: Mapping[str, object]) -> list[Mapping[str, Any]]:
    backlog = _dict(quality_config, "source_backlog")
    candidates = backlog.get("operational_candidates")
    if not isinstance(candidates, list):
        return []
    return [item for item in candidates if isinstance(item, Mapping)]


def _source_status(
    *,
    source: Source,
    event_model: str,
    tracked_event_models: set[str],
    article_count: int,
    event_count: int,
    latest_event_at: datetime | None,
    sla_days: int | None,
    age_days: float | None,
) -> str:
    if not source.enabled:
        return "skipped_disabled"
    if event_model not in tracked_event_models:
        return "not_tracked"
    if article_count == 0:
        return "missing"
    if event_count == 0:
        return "missing_event"
    if latest_event_at is None or age_days is None:
        return "unknown_event_date"
    if sla_days is not None and age_days > sla_days:
        return "stale"
    return "fresh"


def _tracked_event_models(quality: Mapping[str, object]) -> set[str]:
    outputs = _dict(quality, "quality_outputs")
    raw = outputs.get("tracked_event_models")
    if isinstance(raw, list):
        values = {str(item).strip() for item in raw if str(item).strip()}
        return values & TRACKED_EVENT_MODELS or set(TRACKED_EVENT_MODELS)
    return set(TRACKED_EVENT_MODELS)


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


def _source_sla_days(
    source: Source,
    event_model: str,
    freshness_sla: Mapping[str, object],
) -> int | None:
    raw_source_sla = source.config.get("freshness_sla_days")
    parsed_source_sla = _as_int(raw_source_sla)
    if parsed_source_sla is not None:
        return parsed_source_sla

    by_key = freshness_sla.get(event_model)
    if isinstance(by_key, Mapping):
        return _as_int(by_key.get("max_age_days"))

    suffixed = freshness_sla.get(f"{event_model}_days")
    return _as_int(suffixed)


def _latest_event(event_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    dated: list[tuple[datetime, dict[str, Any]]] = []
    undated: list[dict[str, Any]] = []
    for row in event_rows:
        event_at = _parse_datetime(str(row.get("event_at") or ""))
        if event_at is not None:
            dated.append((event_at, row))
        else:
            undated.append(row)
    if dated:
        return max(dated, key=lambda item: item[0])[1]
    return undated[0] if undated else None


def _event_datetime(article: Article, source: Source) -> datetime | None:
    field = str(
        source.config.get("observed_date_field")
        or source.config.get("event_date_field")
        or ""
    )
    if field == "collected_at":
        return _as_utc(article.collected_at) if article.collected_at else None
    article_time = article.published or article.collected_at
    return _as_utc(article_time) if article_time else None


def _repository(article: Article, source: Source) -> str:
    configured = _first_non_empty(
        source.config.get("repository"),
        source.config.get("canonical_repository"),
        source.config.get("github_repository"),
    )
    if configured:
        return _clean_repository(configured)

    labeled = _summary_value(article, "Repository", "Repo", "GitHub repository")
    if labeled:
        return _clean_repository(labeled)

    text = f"{article.title} {article.summary} {article.link}"
    match = re.search(
        r"(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return _clean_repository(f"github.com/{match.group(1)}/{match.group(2)}")

    return KNOWN_SOURCE_REPOSITORIES.get(source.name, "")


def _repository_parts(repository: str) -> tuple[str, str, str]:
    if not repository:
        return "", "", ""
    value = repository.strip()
    if "/" in value and not value.startswith(("http://", "https://")):
        value = f"https://{value}" if "." in value.split("/", 1)[0] else f"https://github.com/{value}"
    parsed = urlparse(value)
    host = parsed.netloc.lower()
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2:
        return host, "", ""
    return host, parts[0], parts[1].removesuffix(".git")


def _package_name(article: Article) -> str:
    labeled = _summary_value(article, "Package name", "Package")
    if labeled:
        return labeled
    match = re.search(
        r"\b(?:npm|pypi|crate|package)\s+([@A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+|[@A-Za-z0-9_.-]+)\b",
        f"{article.title} {article.summary}",
        flags=re.IGNORECASE,
    )
    return match.group(1) if match else ""


def _registry(article: Article, source: Source, package_name: str) -> str:
    configured = _first_non_empty(source.config.get("registry"), source.config.get("package_registry"))
    if configured:
        return configured.lower()
    labeled = _summary_value(article, "Registry")
    if labeled:
        return labeled.lower()
    text = f"{article.title} {article.summary} {article.link}".lower()
    if "npm" in text:
        return "npm"
    if "pypi" in text or "python package" in text:
        return "pypi"
    if "crates.io" in text or "crate" in text:
        return "crates.io"
    if package_name:
        return "unknown"
    return ""


def _technology(
    article: Article,
    source: Source,
    package_name: str,
    repository_name: str,
) -> str:
    configured = _first_non_empty(
        source.config.get("technology"),
        source.config.get("normalized_technology_name"),
    )
    if configured:
        return configured
    labeled = _summary_value(article, "Technology")
    if labeled:
        return labeled
    if package_name:
        return package_name
    if source.name in KNOWN_SOURCE_TECHNOLOGIES:
        return KNOWN_SOURCE_TECHNOLOGIES[source.name]
    for key in ("Framework", "Language", "Domain"):
        value = _first_match(article, key)
        if value:
            return value
    return repository_name


def _ecosystem(
    article: Article,
    source: Source,
    technology: str,
    registry: str,
) -> str:
    configured = _first_non_empty(source.config.get("ecosystem"), source.config.get("tech_ecosystem"))
    if configured:
        return configured.lower()
    labeled = _summary_value(article, "Ecosystem")
    if labeled:
        return labeled.lower()
    if registry and registry != "unknown":
        return registry
    normalized = technology.lower()
    if normalized in ECOSYSTEM_BY_TERM:
        return ECOSYSTEM_BY_TERM[normalized]
    for key in ("Framework", "Language", "Domain"):
        value = _first_match(article, key).lower()
        if value in ECOSYSTEM_BY_TERM:
            return ECOSYSTEM_BY_TERM[value]
    if source.producer_role == "open_source_maintainer":
        return "open-source"
    if source.producer_role in {"model_platform", "vendor_platform"}:
        return "vendor-platform"
    return "tech"


def _skill(article: Article, source: Source, technology: str) -> str:
    labeled = _summary_value(article, "Skill")
    if labeled:
        return labeled
    if _source_event_model(source) == "skill_demand":
        return technology
    return ""


def _employer(article: Article, source: Source) -> str:
    labeled = _summary_value(article, "Employer")
    if labeled:
        return labeled
    if _source_event_model(source) == "skill_demand":
        return source.name
    return ""


def _release_tag(article: Article) -> str:
    labeled = _summary_value(article, "Release tag", "Version", "Tag")
    if labeled:
        return labeled
    text = f"{article.title} {article.summary}"
    match = re.search(
        r"(?<![A-Za-z0-9])v?\d+\.\d+(?:\.\d+)?(?:[-+][0-9A-Za-z.-]+)?(?![A-Za-z0-9])",
        text,
    )
    return match.group(0) if match else ""


def _signal_basis(article: Article, source: Source, event_model: str) -> str:
    if event_model in _matches(article, "OperationalEvent"):
        return "article_operational_event"
    if event_model in _matches(article, "SourceSignal"):
        return "source_context_signal"
    if _source_event_model(source) == event_model:
        return "source_contract_signal"
    return "inferred_signal"


def _canonical_key(row: Mapping[str, Any]) -> tuple[str, str]:
    event_model = str(row.get("event_model") or "")
    repository = str(row.get("repository") or "")
    host = str(row.get("repository_host") or "")
    owner = str(row.get("repository_owner") or "")
    repo_name = str(row.get("repository_name") or "")
    package_name = str(row.get("package_name") or "")
    registry = str(row.get("registry") or "")
    technology = str(row.get("technology") or "")
    ecosystem = str(row.get("ecosystem") or "")
    skill = str(row.get("skill") or "")
    employer = str(row.get("employer") or "")

    if event_model in {"repository_release", "github_activity"} and repository and owner and repo_name:
        return f"repository:{_slug(host)}:{_slug(owner)}:{_slug(repo_name)}", "complete"
    if event_model == "package_download" and package_name and registry:
        return f"package:{_slug(registry)}:{_slug(package_name)}", "complete"
    if event_model == "skill_demand" and skill and employer:
        return f"skill:{_slug(ecosystem)}:{_slug(skill)}:{_slug(employer)}", "complete"
    if technology:
        return f"technology:{_slug(ecosystem)}:{_slug(technology)}", "technology_proxy"
    return "", "missing"


def _required_field_gaps(event_model: str, row: Mapping[str, Any]) -> list[str]:
    gaps: list[str] = []
    for field in REQUIRED_FIELDS.get(event_model, []):
        value = row.get(field)
        if value is None:
            gaps.append(field)
            continue
        if isinstance(value, str) and not value.strip():
            gaps.append(field)
        elif isinstance(value, list) and not value:
            gaps.append(field)
    return gaps


def _event_key(
    article: Article,
    source: Source,
    event_model: str,
    event_at: datetime | None,
) -> str:
    date_text = _as_utc(event_at).strftime("%Y-%m-%d") if event_at else "undated"
    basis = article.link or f"{source.name}:{article.title}"
    return f"{event_model}:{_slug(source.name)}:{_digest(basis)}:{date_text}"


def _summary_value(article: Article, *labels: str) -> str:
    text = " ".join(f"{article.title} {article.summary}".split())
    for label in labels:
        match = re.search(rf"\b{re.escape(label)}\s*[:=]\s*", text, flags=re.IGNORECASE)
        if not match:
            continue
        start = match.end()
        end = len(text)
        for next_label in SUMMARY_LABELS:
            next_match = re.search(
                rf"\b{re.escape(next_label)}\s*[:=]\s*",
                text[start:],
                flags=re.IGNORECASE,
            )
            if next_match:
                end = min(end, start + next_match.start())
        return text[start:end].strip(" \t\r\n.;,")
    return ""


def _first_match(article: Article, key: str) -> str:
    values = _matches(article, key)
    return values[0] if values else ""


def _first_non_empty(*values: object) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _int_value(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        match = re.search(r"\d[\d,]*", value)
        if match:
            return int(match.group(0).replace(",", ""))
    return None


def _clean_repository(value: str) -> str:
    cleaned = value.strip().strip("`'\" ")
    cleaned = re.sub(r"[).,;]+$", "", cleaned)
    cleaned = cleaned.removesuffix(".git")
    parsed = urlparse(cleaned if "://" in cleaned else f"https://{cleaned}")
    if parsed.netloc:
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(parts) >= 2:
            return f"{parsed.netloc.lower()}/{parts[0]}/{parts[1].removesuffix('.git')}"
    return cleaned


def _slug(value: object) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9._-]+", "-", text).strip("-")
    if text:
        return text
    return f"u-{_digest(str(value))}"


def _digest(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def _matches(article: Article, key: str) -> list[str]:
    values = article.matched_entities.get(key, [])
    if isinstance(values, list):
        return [str(value) for value in values]
    return []


def _dict(mapping: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = mapping.get(key)
    return value if isinstance(value, Mapping) else {}


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _age_days(generated_at: datetime, event_at: datetime) -> float:
    return max(0.0, (_as_utc(generated_at) - _as_utc(event_at)).total_seconds() / 86400)


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _parse_datetime(value: str) -> datetime | None:
    if not value or value == "None":
        return None
    try:
        return _as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None
