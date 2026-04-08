#!/usr/bin/env python3
"""Newsletter generator for BlogRadar.

Generates weekly newsletter from DuckDB articles data.
Groups articles by framework/language trends and outputs
both HTML and Markdown formats.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import yaml
from jinja2 import Environment, FileSystemLoader

# Default paths
DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "radar_data.duckdb"
DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.yaml"
DEFAULT_TEMPLATE_PATH = Path(__file__).parent / "template.html"
DEFAULT_OUTPUT_DIR = Path(__file__).parent / "output"


def load_config(config_path: Path) -> dict[str, Any]:
    """Load newsletter configuration from YAML file."""
    with config_path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_articles_from_db(
    db_path: Path,
    days: int = 7,
    category: str = "techblog",
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Fetch recent articles from DuckDB database."""
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        since = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)

        query = """
            SELECT
                category,
                source,
                title,
                link,
                summary,
                published,
                collected_at,
                entities_json
            FROM articles
            WHERE category = ?
              AND COALESCE(published, collected_at) >= ?
            ORDER BY COALESCE(published, collected_at) DESC
            LIMIT ?
        """

        result = conn.execute(query, [category, since, limit]).fetchall()

        articles = []
        for row in result:
            (
                cat,
                source,
                title,
                link,
                summary,
                published,
                collected_at,
                entities_json,
            ) = row

            # Parse entities
            entities: dict[str, list[str]] = {}
            if entities_json:
                try:
                    entities = json.loads(entities_json)
                except json.JSONDecodeError:
                    pass

            # Format date
            pub_date = published or collected_at
            if isinstance(pub_date, datetime):
                published_date = pub_date.strftime("%Y-%m-%d")
            else:
                published_date = "Unknown"

            articles.append(
                {
                    "category": cat,
                    "source": source,
                    "title": title,
                    "link": link,
                    "summary": summary or "",
                    "published": pub_date,
                    "published_date": published_date,
                    "entities": entities,
                }
            )

        return articles
    finally:
        conn.close()


def match_keywords(text: str, keywords: list[str]) -> bool:
    """Check if text contains any of the keywords (case-insensitive)."""
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)


def get_matched_groups(
    article: dict[str, Any],
    group_mapping: dict[str, list[str]],
) -> list[str]:
    """Get list of groups that match an article."""
    matched = []
    text = f"{article['title']} {article['summary']}"

    # Also check entities
    for entity_name, entity_keywords in article.get("entities", {}).items():
        text += " " + " ".join(entity_keywords)

    for group_name, keywords in group_mapping.items():
        if match_keywords(text, keywords):
            matched.append(group_name)

    return matched


def is_korean_source(source: str, korean_sources: list[str]) -> bool:
    """Check if source is from a Korean company."""
    source_lower = source.lower()
    return any(ks.lower() in source_lower for ks in korean_sources)


def is_global_source(source: str, global_sources: list[str]) -> bool:
    """Check if source is from a global company."""
    source_lower = source.lower()
    return any(gs.lower() in source_lower for gs in global_sources)


def extract_tags(article: dict[str, Any]) -> list[dict[str, str]]:
    """Extract tags from article entities for display."""
    tags = []
    entities = article.get("entities", {})

    tag_types = {
        "Domain": "domain",
        "Language": "language",
        "Framework": "framework",
    }

    for entity_name, keywords in entities.items():
        tag_type = tag_types.get(entity_name, "")
        if tag_type and keywords:
            # Take first 3 keywords as tags
            for kw in keywords[:3]:
                tags.append({"name": kw, "type": tag_type})

    return tags[:6]  # Limit to 6 tags total


def generate_newsletter(
    articles: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Generate newsletter data structure from articles."""
    newsletter_config = config.get("newsletter", {})
    entity_groups = config.get("entity_groups", {})
    language_groups = config.get("language_groups", {})
    korean_sources = config.get("korean_sources", [])
    global_sources = config.get("global_sources", [])

    # Calculate date range
    end_date = datetime.now(UTC)
    days = newsletter_config.get("data", {}).get("days", 7)
    start_date = end_date - timedelta(days=days)
    date_range = f"{start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}"

    # Add tags to articles
    for article in articles:
        article["tags"] = extract_tags(article)

    # Get top articles (first N by recency)
    max_top = 10
    for section in newsletter_config.get("sections", []):
        if section.get("id") == "top_articles":
            max_top = section.get("max_items", 10)
            break
    top_articles = articles[:max_top]

    # Group by domain
    domain_grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for article in articles:
        matched_domains = get_matched_groups(article, entity_groups)
        for domain in matched_domains:
            domain_grouped[domain].append(article)

    # Limit items per domain group
    domain_groups: dict[str, list[dict[str, Any]]] = {}
    for domain, items in domain_grouped.items():
        domain_groups[domain] = items[:5]

    # Group by language/framework
    lang_grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for article in articles:
        matched_langs = get_matched_groups(article, language_groups)
        for lang in matched_langs:
            lang_grouped[lang].append(article)

    # Limit items per language group
    lang_groups: dict[str, list[dict[str, Any]]] = {}
    for lang, items in lang_grouped.items():
        lang_groups[lang] = items[:3]

    # Korean company articles
    korean_articles = [
        a for a in articles if is_korean_source(a["source"], korean_sources)
    ][:10]

    # Global company articles
    global_articles = [
        a for a in articles if is_global_source(a["source"], global_sources)
    ][:10]

    # Calculate stats
    sources = set(a["source"] for a in articles)
    domain_counts = [(d, len(items)) for d, items in domain_grouped.items()]
    top_domain = max(domain_counts, key=lambda x: x[1])[0] if domain_counts else "N/A"

    # Layout settings
    layout = newsletter_config.get("layout", {})

    return {
        "title": newsletter_config.get("name", "Tech Blog Radar Weekly"),
        "description": newsletter_config.get(
            "description", "Weekly digest of trending tech blog articles"
        ),
        "date_range": date_range,
        "generated_at": end_date.isoformat(),
        "total_articles": len(articles),
        "total_sources": len(sources),
        "top_domain": top_domain,
        "top_articles": top_articles,
        "domain_groups": domain_groups,
        "language_groups": lang_groups,
        "korean_articles": korean_articles,
        "global_articles": global_articles,
        # Layout
        "primary_color": layout.get("primary_color", "#2563eb"),
        "secondary_color": layout.get("secondary_color", "#1e40af"),
        "background_color": layout.get("background_color", "#f8fafc"),
        "text_color": layout.get("text_color", "#1e293b"),
        "link_color": layout.get("link_color", "#3b82f6"),
        # URLs (placeholder)
        "unsubscribe_url": "#",
        "web_version_url": "#",
    }


def render_html(
    newsletter_data: dict[str, Any],
    template_path: Path,
) -> str:
    """Render newsletter as HTML using Jinja2 template."""
    template_dir = template_path.parent
    template_name = template_path.name

    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=True,
    )

    # Add truncate filter
    def truncate(s: str, length: int = 200) -> str:
        if len(s) <= length:
            return s
        return s[:length].rsplit(" ", 1)[0] + "..."

    env.filters["truncate"] = truncate

    template = env.get_template(template_name)
    return template.render(**newsletter_data)


def render_markdown(newsletter_data: dict[str, Any]) -> str:
    """Render newsletter as Markdown."""
    lines = []

    # Header
    lines.append(f"# {newsletter_data['title']}")
    lines.append("")
    lines.append(f"*{newsletter_data['description']}*")
    lines.append("")
    lines.append(f"**{newsletter_data['date_range']}**")
    lines.append("")

    # Stats
    lines.append("## Stats")
    lines.append("")
    lines.append(f"- **Total Articles**: {newsletter_data['total_articles']}")
    lines.append(f"- **Sources**: {newsletter_data['total_sources']}")
    lines.append(f"- **Top Domain**: {newsletter_data['top_domain']}")
    lines.append("")

    # Top Articles
    if newsletter_data.get("top_articles"):
        lines.append("## Top Articles This Week")
        lines.append("")
        for article in newsletter_data["top_articles"]:
            lines.append(f"### [{article['title']}]({article['link']})")
            lines.append(f"*{article['source']} | {article['published_date']}*")
            if article.get("summary"):
                summary = article["summary"][:200]
                if len(article["summary"]) > 200:
                    summary += "..."
                lines.append("")
                lines.append(summary)
            lines.append("")

    # Domain Groups
    if newsletter_data.get("domain_groups"):
        lines.append("## Trends by Domain")
        lines.append("")
        for domain, articles in newsletter_data["domain_groups"].items():
            if articles:
                lines.append(f"### {domain}")
                lines.append("")
                for article in articles:
                    lines.append(
                        f"- [{article['title']}]({article['link']}) "
                        f"*({article['source']})*"
                    )
                lines.append("")

    # Language Groups
    if newsletter_data.get("language_groups"):
        lines.append("## Language & Framework Highlights")
        lines.append("")
        for lang, articles in newsletter_data["language_groups"].items():
            if articles:
                lines.append(f"### {lang}")
                lines.append("")
                for article in articles:
                    lines.append(
                        f"- [{article['title']}]({article['link']}) "
                        f"*({article['source']})*"
                    )
                lines.append("")

    # Korean Articles
    if newsletter_data.get("korean_articles"):
        lines.append("## Korean Tech Company Updates")
        lines.append("")
        for article in newsletter_data["korean_articles"]:
            lines.append(
                f"- [{article['title']}]({article['link']}) "
                f"*({article['source']})*"
            )
        lines.append("")

    # Global Articles
    if newsletter_data.get("global_articles"):
        lines.append("## Global Tech Updates")
        lines.append("")
        for article in newsletter_data["global_articles"]:
            lines.append(
                f"- [{article['title']}]({article['link']}) "
                f"*({article['source']})*"
            )
        lines.append("")

    # Footer
    lines.append("---")
    lines.append("")
    lines.append(
        "*Generated by [BlogRadar](https://github.com/ai-frendly-datahub/BlogRadar)*"
    )

    return "\n".join(lines)


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate weekly newsletter from BlogRadar data"
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="Path to DuckDB database",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Path to newsletter config YAML",
    )
    parser.add_argument(
        "--template",
        type=Path,
        default=DEFAULT_TEMPLATE_PATH,
        help="Path to HTML template",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory",
    )
    parser.add_argument(
        "--category",
        default="techblog",
        help="Article category to filter",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days to include",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print stats without generating files",
    )

    args = parser.parse_args()

    # Load config
    print(f"Loading config from {args.config}")
    config = load_config(args.config)

    # Override days from config if specified
    days = args.days
    if days == 7:  # default
        days = config.get("newsletter", {}).get("data", {}).get("days", 7)

    # Fetch articles
    print(f"Fetching articles from {args.db} (last {days} days)")
    try:
        articles = get_articles_from_db(
            args.db,
            days=days,
            category=args.category,
        )
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return

    if not articles:
        print("No articles found. Exiting.")
        return

    print(f"Found {len(articles)} articles")

    # Generate newsletter data
    print("Generating newsletter...")
    newsletter_data = generate_newsletter(articles, config)

    if args.dry_run:
        print("\n--- Newsletter Summary (Dry Run) ---")
        print(f"Title: {newsletter_data['title']}")
        print(f"Date Range: {newsletter_data['date_range']}")
        print(f"Total Articles: {newsletter_data['total_articles']}")
        print(f"Total Sources: {newsletter_data['total_sources']}")
        print(f"Top Domain: {newsletter_data['top_domain']}")
        print(f"Top Articles: {len(newsletter_data['top_articles'])}")
        print(f"Domain Groups: {len(newsletter_data['domain_groups'])}")
        print(f"Language Groups: {len(newsletter_data['language_groups'])}")
        print(f"Korean Articles: {len(newsletter_data['korean_articles'])}")
        print(f"Global Articles: {len(newsletter_data['global_articles'])}")
        return

    # Create output directory
    args.output.mkdir(parents=True, exist_ok=True)

    # Generate filename
    date_str = datetime.now(UTC).strftime("%Y%m%d")
    base_name = f"newsletter_{date_str}"

    # Render and save HTML
    html_content = render_html(newsletter_data, args.template)
    html_path = args.output / f"{base_name}.html"
    html_path.write_text(html_content, encoding="utf-8")
    print(f"HTML saved to {html_path}")

    # Render and save Markdown
    md_content = render_markdown(newsletter_data)
    md_path = args.output / f"{base_name}.md"
    md_path.write_text(md_content, encoding="utf-8")
    print(f"Markdown saved to {md_path}")

    # Save JSON data
    json_path = args.output / f"{base_name}.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(newsletter_data, f, ensure_ascii=False, indent=2, default=str)
    print(f"JSON saved to {json_path}")

    print("\nNewsletter generation complete!")


if __name__ == "__main__":
    main()
