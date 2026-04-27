from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from blogradar.models import Article
from blogradar.storage import RadarStorage


def _load_script_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "check_quality.py"
    spec = importlib.util.spec_from_file_location("blogradar_check_quality_script", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generate_quality_artifacts_uses_latest_stored_checkpoint(
    tmp_path: Path,
    capsys,
) -> None:
    project_root = tmp_path
    (project_root / "config" / "categories").mkdir(parents=True)

    (project_root / "config" / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "database_path": "data/radar_data.duckdb",
                "report_dir": "reports",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (project_root / "config" / "categories" / "techblog.yaml").write_text(
        yaml.safe_dump(
            {
                "category_name": "techblog",
                "display_name": "Tech Blog",
                "sources": [
                    {
                        "id": "kubernetes_blog",
                        "name": "Kubernetes Blog",
                        "type": "rss",
                        "url": "https://kubernetes.io/feed.xml",
                        "content_type": "release_note",
                        "enabled": True,
                        "producer_role": "open_source_maintainer",
                        "info_purpose": ["release", "version"],
                    }
                ],
                "entities": [],
                "data_quality": {
                    "quality_outputs": {
                        "tracked_event_models": ["repository_release"],
                    }
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    article_time = datetime.now(UTC) - timedelta(days=30)
    db_path = project_root / "data" / "radar_data.duckdb"
    with RadarStorage(db_path) as storage:
        storage.upsert_articles(
            [
                Article(
                    title="Kubernetes v1.36 Sneak Peek",
                    link="https://kubernetes.io/blog/v1-36",
                    summary="release notes",
                    published=article_time,
                    source="Kubernetes Blog",
                    category="techblog",
                    matched_entities={"Framework": ["kubernetes"]},
                )
            ]
        )
        storage.conn.execute(
            "UPDATE articles SET collected_at = ? WHERE link = ?",
            [article_time.replace(tzinfo=None), "https://kubernetes.io/blog/v1-36"],
        )

    module = _load_script_module()
    paths, report = module.generate_quality_artifacts(project_root)

    assert Path(paths["latest"]).exists()
    assert Path(paths["dated"]).exists()
    assert report["summary"]["tracked_sources"] == 1
    assert report["summary"]["repository_release_events"] == 1

    module.PROJECT_ROOT = project_root
    module.main()
    captured = capsys.readouterr()
    assert "quality_report=" in captured.out
    assert "tracked_sources=1" in captured.out
    assert "operational_adoption_event_count=1" in captured.out
