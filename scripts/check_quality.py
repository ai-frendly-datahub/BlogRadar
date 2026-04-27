"""Quality check script for BlogRadar."""

from __future__ import annotations

from datetime import UTC, date, datetime
import sys
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = PROJECT_ROOT.parent
RADAR_CORE_ROOT = WORKSPACE_ROOT / "radar-core"
if RADAR_CORE_ROOT.exists():
    sys.path.insert(0, str(RADAR_CORE_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))


def _project_path(project_root: Path, raw_path: str | Path) -> Path:
    path = Path(raw_path)
    return path if path.is_absolute() else project_root / path


def _load_runtime_config(project_root: Path) -> dict[str, Any]:
    raw = yaml.safe_load((project_root / "config" / "config.yaml").read_text(encoding="utf-8")) or {}
    return raw if isinstance(raw, dict) else {}


def _coerce_date(value: object) -> date | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.date()
        return value.astimezone(UTC).date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return date.fromisoformat(text[:10])
            except ValueError:
                return None
    return None


def _latest_article_date(db_path: Path, category_name: str) -> date | None:
    if not db_path.exists():
        return None
    try:
        import duckdb

        with duckdb.connect(str(db_path), read_only=True) as con:
            row = con.execute(
                """
                SELECT MAX(COALESCE(published, collected_at))
                FROM articles
                WHERE category = ?
                """,
                [category_name],
            ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    return _coerce_date(row[0])


def _lookback_days(target_date: date | None, *, minimum_days: int = 7) -> int:
    if target_date is None:
        return minimum_days
    age_days = (datetime.now(UTC).date() - target_date).days + 1
    return max(minimum_days, age_days)


def _dedupe_articles(articles: list[object]) -> list[object]:
    deduped: dict[str, object] = {}
    for article in articles:
        key = getattr(article, "link", None) or f"{getattr(article, 'source', '')}:{getattr(article, 'title', '')}"
        deduped.setdefault(str(key), article)
    return list(deduped.values())


def generate_quality_artifacts(
    project_root: Path = PROJECT_ROOT,
    *,
    category_name: str = "techblog",
) -> tuple[dict[str, Path], dict[str, Any]]:
    from blogradar.config_loader import load_category_config, load_category_quality_config
    from blogradar.quality_report import build_quality_report, write_quality_report
    from blogradar.relevance import apply_source_context_entities, filter_relevant_articles
    from blogradar.storage import RadarStorage

    runtime_config = _load_runtime_config(project_root)
    db_path = _project_path(
        project_root,
        str(runtime_config.get("database_path", "data/radar_data.duckdb")),
    )
    report_dir = _project_path(
        project_root,
        str(runtime_config.get("report_dir", "reports")),
    )
    categories_dir = project_root / "config" / "categories"
    category_cfg = load_category_config(category_name, categories_dir=categories_dir)
    quality_cfg = load_category_quality_config(category_name, categories_dir=categories_dir)
    lookback_days = _lookback_days(_latest_article_date(db_path, category_cfg.category_name))

    with RadarStorage(db_path) as storage:
        articles = _dedupe_articles(
            [
                *storage.recent_articles(category_cfg.category_name, days=lookback_days, limit=1000),
                *storage.recent_articles_by_collected_at(
                    category_cfg.category_name,
                    days=lookback_days,
                    limit=1000,
                ),
            ]
        )

    classified_articles = apply_source_context_entities(articles, category_cfg.sources)
    scoped_articles = filter_relevant_articles(classified_articles, category_cfg.sources)
    report = build_quality_report(
        category=category_cfg,
        articles=scoped_articles or classified_articles,
        quality_config=quality_cfg,
    )
    paths = write_quality_report(
        report,
        output_dir=report_dir,
        category_name=category_cfg.category_name,
    )
    return paths, report


def main() -> None:
    import duckdb

    from blogradar.common.quality_checks import run_all_checks

    runtime_config = _load_runtime_config(PROJECT_ROOT)
    db_path = _project_path(
        PROJECT_ROOT,
        str(runtime_config.get("database_path", "data/radar_data.duckdb")),
    )
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        sys.exit(1)

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        run_all_checks(
            con,
            table_name="articles",
            null_conditions={
                "title": "title IS NULL OR title = ''",
                "link": "link IS NULL OR link = ''",
                "summary": "summary IS NULL OR summary = ''",
                "published": "published IS NULL",
            },
            text_columns=["title", "summary"],
            language_column="language",
            allowed_languages={"ko", "en"},
            url_column="link",
            date_column="published",
        )
    finally:
        con.close()

    paths, report = generate_quality_artifacts(PROJECT_ROOT)
    print(f"quality_report={paths['latest']}")
    print(f"tracked_sources={report['summary']['tracked_sources']}")
    print(f"fresh_sources={report['summary']['fresh_sources']}")
    print(f"stale_sources={report['summary']['stale_sources']}")
    print(f"missing_sources={report['summary']['missing_sources']}")
    print(f"not_tracked_sources={report['summary']['not_tracked_sources']}")
    print(f"operational_adoption_event_count={report['summary']['operational_adoption_event_count']}")
    print("\nQuality checks passed")


if __name__ == "__main__":
    main()
