"""Unit tests for blogradar config_loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from blogradar.config_loader import load_category_config, load_settings


@pytest.mark.unit
def test_load_settings_defaults(tmp_path: Path):
    config = tmp_path / "config.yaml"
    config.write_text(
        "database_path: data/test.duckdb\nreport_dir: reports\nraw_data_dir: data/raw\nsearch_db_path: data/search.db\n"
    )
    settings = load_settings(config)
    assert "test.duckdb" in str(settings.database_path)


@pytest.mark.unit
def test_load_category_config(tmp_path: Path):
    cat_dir = tmp_path / "categories"
    cat_dir.mkdir()
    (cat_dir / "techblog.yaml").write_text(
        "category_name: techblog\ndisplay_name: Tech Blog\nsources:\n  - name: TestBlog\n    type: rss\n    url: https://example.com/feed\nentities:\n  - name: Domain\n    display_name: Domain\n    keywords:\n      - python\n"
    )
    cfg = load_category_config("techblog", categories_dir=cat_dir)
    assert cfg.category_name == "techblog"
    assert len(cfg.sources) == 1
    assert len(cfg.entities) == 1
    assert cfg.sources[0].url == "https://example.com/feed"
