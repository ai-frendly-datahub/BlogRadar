"""Unit tests for blogradar config_loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from blogradar.config_loader import (
    load_category_config,
    load_category_quality_config,
    load_settings,
)


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


@pytest.mark.unit
def test_load_category_config_preserves_source_metadata(tmp_path: Path):
    cat_dir = tmp_path / "categories"
    cat_dir.mkdir()
    (cat_dir / "techblog.yaml").write_text(
        """
category_name: techblog
display_name: Tech Blog
sources:
  - name: GitHub Blog Engineering
    id: github_engineering
    type: rss
    url: https://github.blog/category/engineering/feed/
    enabled: false
    trust_tier: T1_authoritative
    weight: 1.5
    content_type: changelog
    collection_tier: C1_rss
    producer_role: vendor_platform
    info_purpose:
      - changelog
      - release
    notes: official changelog feed
    config:
      section: engineering
entities: []
""",
        encoding="utf-8",
    )

    cfg = load_category_config("techblog", categories_dir=cat_dir)
    source = cfg.sources[0]

    assert source.id == "github_engineering"
    assert source.enabled is False
    assert source.trust_tier == "T1_authoritative"
    assert source.weight == 1.5
    assert source.content_type == "changelog"
    assert source.collection_tier == "C1_rss"
    assert source.producer_role == "vendor_platform"
    assert source.info_purpose == ["changelog", "release"]
    assert source.notes == "official changelog feed"
    assert source.config == {"section": "engineering"}


@pytest.mark.unit
def test_load_category_quality_config_preserves_quality_overlay(tmp_path: Path):
    cat_dir = tmp_path / "categories"
    cat_dir.mkdir()
    (cat_dir / "techblog.yaml").write_text(
        """
category_name: techblog
display_name: Tech Blog
data_quality:
  quality_outputs:
    tracked_event_models:
      - repository_release
source_backlog:
  operational_candidates:
    - id: github_release_star_api
sources: []
entities: []
""",
        encoding="utf-8",
    )

    cfg = load_category_quality_config("techblog", categories_dir=cat_dir)

    assert cfg["data_quality"]["quality_outputs"]["tracked_event_models"] == [
        "repository_release"
    ]
    assert cfg["source_backlog"]["operational_candidates"][0]["id"] == "github_release_star_api"
