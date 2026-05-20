"""Unit tests for blogradar config_loader."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from blogradar.config_loader import (
    load_category_config,
    load_category_quality_config,
    load_notification_config,
    load_settings,
)


@pytest.mark.unit
def test_load_settings_defaults(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        "database_path: data/test.duckdb\nreport_dir: reports\nraw_data_dir: data/raw\nsearch_db_path: data/search.db\n"
    )
    settings = load_settings(config)
    assert "test.duckdb" in str(settings.database_path)


@pytest.mark.unit
def test_load_category_config(tmp_path: Path) -> None:
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
def test_load_category_config_preserves_source_metadata(tmp_path: Path) -> None:
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
def test_load_category_quality_config_preserves_quality_overlay(tmp_path: Path) -> None:
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

    cfg = cast(dict[str, Any], load_category_quality_config("techblog", categories_dir=cat_dir))

    assert cfg["data_quality"]["quality_outputs"]["tracked_event_models"] == ["repository_release"]
    assert cfg["source_backlog"]["operational_candidates"][0]["id"] == "github_release_star_api"


@pytest.mark.unit
def test_load_settings_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_settings(tmp_path / "missing.yaml")


@pytest.mark.unit
def test_load_category_config_raises_for_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_category_config("missing", categories_dir=tmp_path)


@pytest.mark.unit
def test_load_category_config_uses_defaults_and_filters_invalid_items(tmp_path: Path) -> None:
    cat_dir = tmp_path / "categories"
    cat_dir.mkdir()
    (cat_dir / "minimal.yaml").write_text(
        """
category_name: minimal
sources:
  - url: ""
  - name: TupleSource
    info_purpose: release
    weight: bad
    enabled: "yes"
  - ignored
entities:
  - display_name: Default Entity
  - name: Language
    keywords:
      - " python "
      - 123
      - ""
  - ignored
""",
        encoding="utf-8",
    )

    cfg = load_category_config("minimal", categories_dir=cat_dir)

    assert cfg.display_name == "minimal"
    assert [source.name for source in cfg.sources] == ["Unnamed Source", "TupleSource"]
    assert cfg.sources[0].type == "rss"
    assert cfg.sources[1].enabled is True
    assert cfg.sources[1].weight == 1.0
    assert cfg.sources[1].info_purpose == ["release"]
    assert [entity.name for entity in cfg.entities] == ["entity", "Language"]
    assert cfg.entities[1].keywords == ["python", "123"]


@pytest.mark.unit
def test_load_notification_config_missing_or_invalid_file_returns_disabled(
    tmp_path: Path,
) -> None:
    missing = load_notification_config(tmp_path / "missing.yaml")
    assert missing.enabled is False
    assert missing.channels == []

    invalid_path = tmp_path / "notifications.yaml"
    invalid_path.write_text("notifications: disabled\n", encoding="utf-8")
    invalid = load_notification_config(invalid_path)
    assert invalid.enabled is False
    assert invalid.channels == []


@pytest.mark.unit
def test_load_notification_config_resolves_channels_and_env_refs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("SMTP_USER", "user")
    monkeypatch.setenv("SMTP_PASS", "secret")
    monkeypatch.setenv("WEBHOOK_URL", "https://hooks.example.com")
    monkeypatch.setenv("TELEGRAM_TOKEN", "token")

    config = tmp_path / "notifications.yaml"
    config.write_text(
        """
notifications:
  enabled: true
  channels:
    - email
    - webhook
    - 3
  email:
    smtp_host: ${SMTP_HOST}
    smtp_port: ${SMTP_PORT}
    username: ${SMTP_USER}
    password: ${SMTP_PASS}
    from_address: radar@example.com
    to_addresses:
      - ops@example.com
      - 42
  webhook_url: ${WEBHOOK_URL}
  telegram:
    bot_token: ${TELEGRAM_TOKEN}
    chat_id: "1234"
  rules:
    high_error_rate: ${SMTP_USER}
""",
        encoding="utf-8",
    )

    loaded = load_notification_config(config)

    assert loaded.enabled is True
    assert loaded.channels == ["email", "webhook"]
    assert loaded.email is not None
    assert loaded.email.smtp_host == "smtp.example.com"
    assert loaded.email.smtp_port == 2525
    assert loaded.email.username == "user"
    assert loaded.email.password == "secret"
    assert loaded.email.to_addresses == ["ops@example.com"]
    assert loaded.webhook_url == "https://hooks.example.com"
    assert loaded.telegram is not None
    assert loaded.telegram.bot_token == "token"
    assert loaded.telegram.chat_id == "1234"
    assert loaded.rules == {"high_error_rate": "user"}


@pytest.mark.unit
def test_load_notification_config_handles_bad_email_and_empty_webhook(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MISSING_WEBHOOK", raising=False)
    config = tmp_path / "notifications.yaml"
    config.write_text(
        """
notifications:
  enabled: true
  channels: []
  email:
    smtp_host: smtp.example.com
    smtp_port: bad
  webhook_url: ${MISSING_WEBHOOK}
  telegram:
    bot_token: abc
    chat_id: def
  rules:
    nested:
      token: ${MISSING_WEBHOOK}
""",
        encoding="utf-8",
    )

    loaded = load_notification_config(config)

    assert loaded.enabled is True
    assert loaded.email is None
    assert loaded.webhook_url is None
    assert loaded.telegram is not None
    assert loaded.rules == {"nested": {"token": ""}}
