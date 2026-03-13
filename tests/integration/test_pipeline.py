from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from blogradar.models import Article
from main import run


_FAKE_ARTICLE = Article(
    title="Arabica market update",
    link="https://example.com/article-1",
    summary="arabica demand is up",
    published=datetime.now(UTC),
    source="Mock RSS",
    category="test_cat",
)


@pytest.mark.integration
def test_full_pipeline_creates_all_outputs(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    categories_dir = tmp_path / "categories"
    categories_dir.mkdir(parents=True, exist_ok=True)

    db_path = tmp_path / "data" / "radar_data.duckdb"
    report_dir = tmp_path / "reports"
    raw_dir = tmp_path / "data" / "raw"
    search_db_path = tmp_path / "data" / "search_index.db"

    _ = config_path.write_text(
        yaml.safe_dump(
            {
                "database_path": str(db_path),
                "report_dir": str(report_dir),
                "raw_data_dir": str(raw_dir),
                "search_db_path": str(search_db_path),
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    category_file = categories_dir / "test_cat.yaml"
    _ = category_file.write_text(
        yaml.safe_dump(
            {
                "category_name": "test_cat",
                "display_name": "Test Category",
                "sources": [
                    {
                        "name": "Mock RSS",
                        "type": "rss",
                        "url": "https://example.com/feed.xml",
                    }
                ],
                "entities": [
                    {
                        "name": "Bean",
                        "display_name": "Bean",
                        "keywords": ["arabica"],
                    }
                ],
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    # Patch collect_sources at the main module level (where it's imported/used).
    # Mocking _collect_single doesn't work because the circuit breaker in
    # blogradar/resilience.py captures the original function reference at import
    # time and the mock is never invoked through the breaker.call() wrapper.
    with patch("main.collect_sources", return_value=([_FAKE_ARTICLE], [])):
        output_path = run(
            category="test_cat",
            config_path=config_path,
            categories_dir=categories_dir,
            per_source_limit=5,
            recent_days=7,
            timeout=5,
            keep_days=30,
        )

    assert db_path.exists()
    assert raw_dir.exists()
    assert list(raw_dir.rglob("*.jsonl"))
    assert search_db_path.exists()
    assert output_path.exists()
    assert output_path.suffix == ".html"
