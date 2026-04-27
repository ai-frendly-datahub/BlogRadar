"""Generate dashboard data from BlogRadar DuckDB database.

Extracts framework/language mention counts from matched_entities
and outputs JSON data for the static dashboard.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DOCS_DIR = PROJECT_ROOT / "docs"


def load_articles(db_path: Path) -> list[dict[str, Any]]:
    """Load articles from DuckDB database."""
    conn = duckdb.connect(str(db_path), read_only=True)
    result = conn.execute("""
        SELECT
            title,
            source,
            category,
            published,
            collected_at,
            entities_json
        FROM articles
        WHERE entities_json IS NOT NULL
        ORDER BY published DESC
    """).fetchall()
    conn.close()

    columns = ["title", "source", "category", "published", "collected_at", "entities_json"]
    return [dict(zip(columns, row)) for row in result]


def parse_entities(entities_json: str | None) -> dict[str, list[str]]:
    """Parse entities JSON safely."""
    if not entities_json:
        return {}
    try:
        return json.loads(entities_json)
    except (json.JSONDecodeError, TypeError):
        return {}


def aggregate_framework_counts(articles: list[dict]) -> dict[str, int]:
    """Aggregate framework mention counts."""
    counts: Counter[str] = Counter()
    for article in articles:
        entities = parse_entities(article.get("entities_json"))
        for fw in entities.get("Framework", []):
            counts[fw.lower()] += 1
    return dict(counts.most_common(50))


def aggregate_language_counts(articles: list[dict]) -> dict[str, int]:
    """Aggregate programming language mention counts."""
    counts: Counter[str] = Counter()
    for article in articles:
        entities = parse_entities(article.get("entities_json"))
        for lang in entities.get("Language", []):
            counts[lang.lower()] += 1
    return dict(counts.most_common(20))


def aggregate_company_counts(articles: list[dict]) -> dict[str, int]:
    """Aggregate company mention counts."""
    counts: Counter[str] = Counter()
    for article in articles:
        entities = parse_entities(article.get("entities_json"))
        for company in entities.get("Company", []):
            counts[company.lower()] += 1
    return dict(counts.most_common(20))


def aggregate_domain_counts(articles: list[dict]) -> dict[str, int]:
    """Aggregate domain mention counts."""
    counts: Counter[str] = Counter()
    for article in articles:
        entities = parse_entities(article.get("entities_json"))
        for domain in entities.get("Domain", []):
            counts[domain.lower()] += 1
    return dict(counts.most_common(20))


def aggregate_topic_counts(articles: list[dict]) -> dict[str, int]:
    """Aggregate topic mention counts."""
    counts: Counter[str] = Counter()
    for article in articles:
        entities = parse_entities(article.get("entities_json"))
        for topic in entities.get("Topic", []):
            counts[topic.lower()] += 1
    return dict(counts.most_common(20))


def aggregate_weekly_trends(articles: list[dict], weeks: int = 8) -> dict[str, dict[str, int]]:
    """Aggregate framework mentions by week."""
    weekly: dict[str, Counter[str]] = defaultdict(Counter)

    for article in articles:
        published = article.get("published")
        if not published:
            continue

        if isinstance(published, str):
            try:
                published = datetime.fromisoformat(published.replace("Z", "+00:00"))
            except ValueError:
                continue

        week_start = published.date() - timedelta(days=published.weekday())
        week_key = str(week_start)

        entities = parse_entities(article.get("entities_json"))
        for fw in entities.get("Framework", []):
            weekly[week_key][fw.lower()] += 1

    sorted_weeks = sorted(weekly.keys(), reverse=True)[:weeks]
    return {
        week: dict(weekly[week].most_common(10))
        for week in sorted(sorted_weeks)
    }


def aggregate_source_stats(articles: list[dict]) -> dict[str, dict[str, Any]]:
    """Aggregate statistics by source."""
    source_data: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "article_count": 0,
        "entity_count": 0,
        "frameworks": Counter(),
        "companies": Counter(),
    })

    for article in articles:
        source = article.get("source", "Unknown")
        source_data[source]["article_count"] += 1

        entities = parse_entities(article.get("entities_json"))
        if entities:
            source_data[source]["entity_count"] += 1
            for fw in entities.get("Framework", []):
                source_data[source]["frameworks"][fw.lower()] += 1
            for co in entities.get("Company", []):
                source_data[source]["companies"][co.lower()] += 1

    # Convert Counters to top items
    result = {}
    for source, data in source_data.items():
        result[source] = {
            "article_count": data["article_count"],
            "entity_count": data["entity_count"],
            "match_rate": round(data["entity_count"] / data["article_count"] * 100, 1) if data["article_count"] > 0 else 0,
            "top_frameworks": dict(data["frameworks"].most_common(5)),
            "top_companies": dict(data["companies"].most_common(3)),
        }

    return dict(sorted(result.items(), key=lambda x: x[1]["article_count"], reverse=True)[:20])


def get_company_tech_stacks(articles: list[dict]) -> dict[str, dict[str, int]]:
    """Analyze tech stacks by company based on co-occurrence."""
    company_frameworks: dict[str, Counter[str]] = defaultdict(Counter)

    for article in articles:
        entities = parse_entities(article.get("entities_json"))
        companies = entities.get("Company", [])
        frameworks = entities.get("Framework", [])

        for company in companies:
            for fw in frameworks:
                company_frameworks[company.lower()][fw.lower()] += 1

    return {
        company: dict(fws.most_common(5))
        for company, fws in sorted(
            company_frameworks.items(),
            key=lambda x: sum(x[1].values()),
            reverse=True
        )[:15]
    }


def generate_dashboard_data(db_path: Path) -> dict[str, Any]:
    """Generate complete dashboard data."""
    articles = load_articles(db_path)

    # Calculate basic stats
    total_articles = len(articles)
    articles_with_entities = sum(
        1 for a in articles
        if parse_entities(a.get("entities_json"))
    )

    # Get date range
    dates = [a["published"] for a in articles if a.get("published")]
    date_range = {
        "start": str(min(dates)) if dates else None,
        "end": str(max(dates)) if dates else None,
    }

    # Calculate entity match rate
    match_rate = round(articles_with_entities / total_articles * 100, 1) if total_articles > 0 else 0

    return {
        "generated_at": datetime.now().isoformat(),
        "stats": {
            "total_articles": total_articles,
            "articles_with_entities": articles_with_entities,
            "entity_match_rate": match_rate,
            "date_range": date_range,
        },
        "frameworks": aggregate_framework_counts(articles),
        "languages": aggregate_language_counts(articles),
        "companies": aggregate_company_counts(articles),
        "domains": aggregate_domain_counts(articles),
        "topics": aggregate_topic_counts(articles),
        "weekly_trends": aggregate_weekly_trends(articles),
        "source_stats": aggregate_source_stats(articles),
        "company_tech_stacks": get_company_tech_stacks(articles),
    }


def main() -> None:
    """Main entry point."""
    db_path = DATA_DIR / "radar_data.duckdb"
    output_path = DOCS_DIR / "dashboard_data.json"

    if not db_path.exists():
        print(f"Database not found: {db_path}")
        sys.exit(1)

    DOCS_DIR.mkdir(exist_ok=True)

    print(f"Loading data from: {db_path}")
    data = generate_dashboard_data(db_path)

    print(f"Total articles: {data['stats']['total_articles']}")
    print(f"Entity match rate: {data['stats']['entity_match_rate']}%")
    print(f"Top frameworks: {list(data['frameworks'].keys())[:5]}")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Dashboard data saved to: {output_path}")


if __name__ == "__main__":
    main()
