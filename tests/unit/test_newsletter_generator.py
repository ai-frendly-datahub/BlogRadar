from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pytest
import yaml

from newsletter import generator

pytestmark = pytest.mark.unit


def _article(
    *,
    title: str,
    source: str = "Kakao Tech",
    summary: str = "React and FastAPI platform update",
    entities: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "link": f"https://example.com/{title.lower().replace(' ', '-')}",
        "source": source,
        "summary": summary,
        "published_date": "2026-05-20",
        "entities": entities
        or {
            "Domain": ["frontend"],
            "Language": ["Python"],
            "Framework": ["React", "FastAPI"],
        },
    }


def _config() -> dict[str, Any]:
    return {
        "newsletter": {
            "name": "BlogRadar Weekly",
            "description": "Weekly engineering digest",
            "data": {"days": 14},
            "sections": [{"id": "top_articles", "max_items": 1}],
            "layout": {
                "primary_color": "#111111",
                "secondary_color": "#222222",
                "background_color": "#ffffff",
                "text_color": "#333333",
                "link_color": "#444444",
            },
        },
        "entity_groups": {
            "Frontend": ["react", "frontend"],
            "Backend": ["fastapi"],
        },
        "language_groups": {
            "Python": ["python", "fastapi"],
            "JavaScript": ["react"],
        },
        "korean_sources": ["kakao", "naver"],
        "global_sources": ["github", "meta"],
    }


def _create_articles_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute("""
            CREATE TABLE articles (
                category TEXT,
                source TEXT,
                title TEXT,
                link TEXT,
                summary TEXT,
                published TIMESTAMP,
                collected_at TIMESTAMP,
                entities_json TEXT
            )
            """)
        now = datetime.now(UTC).replace(tzinfo=None)
        conn.executemany(
            """
            INSERT INTO articles
            (category, source, title, link, summary, published, collected_at, entities_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "techblog",
                    "Kakao Tech",
                    "React platform migration",
                    "https://example.com/react",
                    "Frontend migration with React",
                    now,
                    now,
                    json.dumps({"Framework": ["React"], "Domain": ["frontend"]}),
                ),
                (
                    "techblog",
                    "GitHub Blog",
                    "FastAPI release",
                    "https://example.com/fastapi",
                    "Python API release",
                    now,
                    now,
                    "{bad json",
                ),
                (
                    "other",
                    "Other",
                    "Ignored",
                    "https://example.com/ignored",
                    "Ignored",
                    now,
                    now,
                    "{}",
                ),
            ],
        )
    finally:
        conn.close()


def test_load_config_reads_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({"newsletter": {"name": "Radar"}}), encoding="utf-8")

    assert generator.load_config(config_path) == {"newsletter": {"name": "Radar"}}


def test_get_articles_from_db_reads_recent_articles_and_parses_entities(tmp_path: Path) -> None:
    db_path = tmp_path / "radar.duckdb"
    _create_articles_db(db_path)

    articles = generator.get_articles_from_db(db_path, days=7, category="techblog", limit=10)

    assert [article["title"] for article in articles] == [
        "React platform migration",
        "FastAPI release",
    ]
    assert articles[0]["entities"] == {"Framework": ["React"], "Domain": ["frontend"]}
    assert articles[1]["entities"] == {}
    assert articles[0]["published_date"] != "Unknown"


def test_get_articles_from_db_raises_for_missing_database(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        generator.get_articles_from_db(tmp_path / "missing.duckdb")


def test_get_articles_from_db_uses_unknown_for_non_datetime_dates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "radar.duckdb"
    db_path.touch()

    class FakeConnection:
        closed = False

        def execute(self, _query: str, _params: list[object]) -> FakeConnection:
            return self

        def fetchall(self) -> list[tuple[object, ...]]:
            return [
                (
                    "techblog",
                    "Mock Source",
                    "Undated article",
                    "https://example.com/undated",
                    "No date metadata",
                    "not-a-datetime",
                    None,
                    None,
                )
            ]

        def close(self) -> None:
            self.closed = True

    fake_conn = FakeConnection()
    monkeypatch.setattr("newsletter.generator.duckdb.connect", lambda *_args, **_kwargs: fake_conn)

    articles = generator.get_articles_from_db(db_path)

    assert articles[0]["published_date"] == "Unknown"
    assert fake_conn.closed is True


def test_matching_source_and_tag_helpers() -> None:
    article = _article(title="React frontend update")

    assert generator.match_keywords("React Server Components", ["server", "django"]) is True
    assert generator.get_matched_groups(
        article, {"Frontend": ["react"], "Ops": ["kubernetes"]}
    ) == ["Frontend"]
    assert generator.is_korean_source("Kakao Tech", ["kakao"]) is True
    assert generator.is_global_source("GitHub Blog", ["github"]) is True
    assert generator.extract_tags(article) == [
        {"name": "frontend", "type": "domain"},
        {"name": "Python", "type": "language"},
        {"name": "React", "type": "framework"},
        {"name": "FastAPI", "type": "framework"},
    ]


def test_generate_newsletter_groups_articles_and_applies_layout() -> None:
    articles = [
        _article(title="React frontend update", source="Kakao Tech"),
        _article(title="FastAPI backend update", source="GitHub Blog"),
    ]

    newsletter = generator.generate_newsletter(articles, _config())

    assert newsletter["title"] == "BlogRadar Weekly"
    assert newsletter["description"] == "Weekly engineering digest"
    assert newsletter["total_articles"] == 2
    assert newsletter["total_sources"] == 2
    assert newsletter["top_articles"] == [articles[0]]
    assert newsletter["domain_groups"]["Frontend"] == articles[:2]
    assert newsletter["language_groups"]["Python"] == articles[:2]
    assert newsletter["korean_articles"] == [articles[0]]
    assert newsletter["global_articles"] == [articles[1]]
    assert newsletter["primary_color"] == "#111111"


def test_render_markdown_and_html(tmp_path: Path) -> None:
    newsletter = generator.generate_newsletter([_article(title="React frontend update")], _config())
    template_path = tmp_path / "template.html"
    template_path.write_text(
        "<h1>{{ title }}</h1>{{ description|truncate(12) }} {{ title|truncate(100) }}",
        encoding="utf-8",
    )

    html = generator.render_html(newsletter, template_path)
    markdown = generator.render_markdown(newsletter)

    assert "<h1>BlogRadar Weekly</h1>" in html
    assert "Weekly..." in html
    assert "BlogRadar Weekly" in html
    assert "# BlogRadar Weekly" in markdown
    assert "React frontend update" in markdown
    assert "Korean Tech Company Updates" in markdown


def test_render_markdown_truncates_long_summaries() -> None:
    newsletter = generator.generate_newsletter(
        [
            _article(
                title="Long summary article",
                summary="x" * 210,
            )
        ],
        _config(),
    )

    markdown = generator.render_markdown(newsletter)

    assert f"{'x' * 200}..." in markdown


def test_main_dry_run_prints_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = tmp_path / "radar.duckdb"
    config_path = tmp_path / "config.yaml"
    _create_articles_db(db_path)
    config_path.write_text(yaml.safe_dump(_config()), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generator.py",
            "--db",
            str(db_path),
            "--config",
            str(config_path),
            "--category",
            "techblog",
            "--dry-run",
        ],
    )

    generator.main()

    output = capsys.readouterr().out
    assert "Newsletter Summary (Dry Run)" in output
    assert "Total Articles: 2" in output


def test_main_writes_newsletter_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "radar.duckdb"
    config_path = tmp_path / "config.yaml"
    template_path = tmp_path / "template.html"
    output_dir = tmp_path / "out"
    _create_articles_db(db_path)
    config_path.write_text(yaml.safe_dump(_config()), encoding="utf-8")
    template_path.write_text("<h1>{{ title }}</h1>", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generator.py",
            "--db",
            str(db_path),
            "--config",
            str(config_path),
            "--template",
            str(template_path),
            "--output",
            str(output_dir),
            "--category",
            "techblog",
        ],
    )

    generator.main()

    assert len(list(output_dir.glob("newsletter_*.html"))) == 1
    assert len(list(output_dir.glob("newsletter_*.md"))) == 1
    assert len(list(output_dir.glob("newsletter_*.json"))) == 1


def test_main_exits_when_database_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(_config()), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generator.py",
            "--db",
            str(tmp_path / "missing.duckdb"),
            "--config",
            str(config_path),
        ],
    )

    generator.main()

    assert "Database not found" in capsys.readouterr().out


def test_main_exits_when_no_articles_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = tmp_path / "radar.duckdb"
    config_path = tmp_path / "config.yaml"
    _create_articles_db(db_path)
    config_path.write_text(yaml.safe_dump(_config()), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generator.py",
            "--db",
            str(db_path),
            "--config",
            str(config_path),
            "--category",
            "missing",
        ],
    )

    generator.main()

    assert "No articles found. Exiting." in capsys.readouterr().out
