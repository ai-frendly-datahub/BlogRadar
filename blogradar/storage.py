from __future__ import annotations

import json
from datetime import date
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import duckdb

from radar_core.exceptions import StorageError
from radar_core.storage import RadarStorage as CoreRadarStorage

from .date_storage import cleanup_date_directories, snapshot_database
from .models import Article


def _utc_naive(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo:
        return dt.astimezone(UTC).replace(tzinfo=None)
    return dt


class RadarStorage(CoreRadarStorage):
    """BlogRadar storage wrapper with dated snapshot helpers."""

    def recent_articles_by_collected_at(
        self,
        category: str,
        *,
        days: int = 7,
        limit: int = 200,
    ) -> list[Article]:
        since = _utc_naive(datetime.now(UTC) - timedelta(days=days))
        cur = self.conn.execute(
            """
            SELECT
                category,
                source,
                title,
                link,
                summary,
                published,
                collected_at,
                entities_json,
                ontology_json
            FROM articles
            WHERE category = ? AND collected_at >= ?
            ORDER BY collected_at DESC, link DESC
            LIMIT ?
            """,
            [category, since, limit],
        )
        rows = cast(
            list[
                tuple[
                    str,
                    str,
                    str,
                    str,
                    str | None,
                    datetime | None,
                    datetime | None,
                    str | None,
                    str | None,
                ]
            ],
            cur.fetchall(),
        )
        return [_article_from_row(row) for row in rows]

    def create_daily_snapshot(
        self,
        *,
        snapshot_dir: str | Path | None = None,
        snapshot_date: date | None = None,
    ) -> Path | None:
        snapshot_root = Path(snapshot_dir) if snapshot_dir is not None else None
        _ = self.conn.execute("CHECKPOINT")
        self.conn.close()
        try:
            return snapshot_database(
                self.db_path,
                snapshot_date=snapshot_date,
                snapshot_root=snapshot_root,
            )
        finally:
            self.conn = duckdb.connect(str(self.db_path))
            self._ensure_tables()

    def cleanup_old_snapshots(
        self,
        *,
        keep_days: int,
        snapshot_dir: str | Path | None = None,
        today: date | None = None,
    ) -> int:
        snapshot_root = (
            Path(snapshot_dir)
            if snapshot_dir is not None
            else self.db_path.parent / "daily"
        )
        return cleanup_date_directories(
            snapshot_root,
            keep_days=keep_days,
            today=today,
        )


__all__ = ["RadarStorage", "StorageError"]


def _article_from_row(
    row: tuple[
        str,
        str,
        str,
        str,
        str | None,
        datetime | None,
        datetime | None,
        str | None,
        str | None,
    ],
) -> Article:
    (
        category_value,
        source,
        title,
        link,
        summary,
        published,
        collected_at,
        raw_entities,
        raw_ontology,
    ) = row

    entities: dict[str, list[str]] = {}
    if raw_entities:
        try:
            parsed = cast(object, json.loads(raw_entities))
            if isinstance(parsed, dict):
                for name, values in cast(dict[object, object], parsed).items():
                    if not isinstance(name, str) or not isinstance(values, list):
                        continue
                    entities[name] = [str(value) for value in cast(list[object], values)]
        except json.JSONDecodeError:
            entities = {}

    ontology: dict[str, object] = {}
    if raw_ontology:
        try:
            parsed_ontology = cast(object, json.loads(raw_ontology))
            if isinstance(parsed_ontology, dict):
                ontology = {
                    str(name): value
                    for name, value in cast(dict[object, object], parsed_ontology).items()
                    if str(name).strip()
                }
        except json.JSONDecodeError:
            ontology = {}

    return Article(
        title=str(title),
        link=str(link),
        summary=str(summary) if summary is not None else "",
        published=published if isinstance(published, datetime) else None,
        source=str(source),
        category=str(category_value),
        matched_entities=entities,
        collected_at=collected_at if isinstance(collected_at, datetime) else None,
        ontology=ontology,
    )
