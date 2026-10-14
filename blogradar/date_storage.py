from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)


def snapshot_database(
    db_path: Path,
    *,
    snapshot_date: date | None = None,
    snapshot_root: Path | None = None,
) -> Path | None:
    if not db_path.exists():
        return None

    if snapshot_date is None:
        snapshot_date = datetime.now(UTC).date()

    if snapshot_root is None:
        snapshot_root = db_path.parent / "daily"

    snapshot_root.mkdir(parents=True, exist_ok=True)
    snapshot_path = snapshot_root / f"{snapshot_date.isoformat()}.duckdb"

    shutil.copy2(db_path, snapshot_path)
    return snapshot_path


def _has_article_rows(db_path: Path) -> bool:
    if not db_path.exists():
        return False

    try:
        conn = duckdb.connect(str(db_path), read_only=True)
        try:
            row = conn.execute("SELECT COUNT(*) FROM articles").fetchone()
        finally:
            conn.close()
    except duckdb.Error:
        return False

    return bool(row and int(row[0]) > 0)


def latest_snapshot_path(db_path: Path, *, snapshot_root: Path | None = None) -> Path | None:
    target_root = snapshot_root or db_path.parent / "daily"
    if not target_root.exists():
        return None

    snapshots: list[tuple[date, Path]] = []
    for candidate in target_root.glob("*.duckdb"):
        try:
            snapshot_date = date.fromisoformat(candidate.stem)
        except ValueError:
            continue
        snapshots.append((snapshot_date, candidate))

    if not snapshots:
        return None

    return max(snapshots, key=lambda item: item[0])[1]


def resolve_read_database_path(db_path: Path, *, snapshot_root: Path | None = None) -> Path:
    if _has_article_rows(db_path):
        return db_path

    snapshot_path = latest_snapshot_path(db_path, snapshot_root=snapshot_root)
    if snapshot_path is not None and _has_article_rows(snapshot_path):
        return snapshot_path

    if db_path.exists():
        return db_path
    if snapshot_path is not None:
        return snapshot_path
    return db_path


def cleanup_date_directories(base_dir: Path, *, keep_days: int, today: date | None = None) -> int:
    if today is None:
        today = datetime.now(UTC).date()

    cutoff = today - timedelta(days=keep_days)
    removed = 0

    if not base_dir.exists():
        return 0

    for item in base_dir.iterdir():
        if not item.is_dir():
            continue

        try:
            stamp: date | None = None
            if len(item.name) == 10 and item.name.count("-") == 2:
                stamp = date.fromisoformat(item.name)
        except ValueError:
            continue

        if stamp and stamp < cutoff:
            shutil.rmtree(item)
            removed += 1

    return removed


def cleanup_dated_reports(report_dir: Path, *, keep_days: int, today: date | None = None) -> int:
    if today is None:
        today = datetime.now(UTC).date()

    cutoff = today - timedelta(days=keep_days)
    removed = 0

    if not report_dir.exists():
        return 0

    for item in report_dir.glob("*_[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].html"):
        try:
            date_str = item.stem.split("_")[-1]
            if len(date_str) == 8:
                stamp = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=UTC).date()
                if stamp < cutoff:
                    item.unlink()
                    removed += 1
        except (ValueError, IndexError):
            continue

    return removed


def _load_compactor() -> Callable[..., dict[str, object]]:
    """Return radar-core's DuckDB compactor.

    BlogRadar copies ``database_path`` in ``snapshot_database`` before git add.
    ``compact_duckdb_file`` has to run on that path first. ``RADAR_DUCKDB_MAX_BYTES``
    and ``RADAR_DUCKDB_COMPACT`` are read inside radar-core (default budget 90 MiB).
    """
    from radar_core.db_compact import compact_duckdb_file

    return compact_duckdb_file


def _compact_database(database_path: Path) -> dict[str, object]:
    """Shrink ``database_path`` before it is copied or committed.

    Compaction failure must not block the report or the snapshot. The file
    already on disk is left in place.
    """
    bytes_now = database_path.stat().st_size if database_path.exists() else 0
    fallback: dict[str, object] = {
        "compacted": False,
        "reason": "missing" if not database_path.exists() else "skipped",
        "bytes": bytes_now,
        "bytes_before": bytes_now,
        "rows_deleted": 0,
    }
    if not database_path.exists():
        return fallback
    try:
        compact_duckdb_file = _load_compactor()
    except ImportError as exc:
        logger.warning("duckdb_compact_unavailable path=%s error=%s", database_path, exc)
        fallback["reason"] = "unavailable"
        return fallback
    try:
        result = compact_duckdb_file(database_path)
    except Exception as exc:
        logger.warning("duckdb_compact_failed path=%s error=%s", database_path, exc)
        fallback["reason"] = "failed"
        fallback["bytes"] = database_path.stat().st_size if database_path.exists() else 0
        return fallback
    if isinstance(result, dict):
        return result
    fallback["reason"] = "invalid_result"
    return fallback


def apply_date_storage_policy(
    *,
    database_path: Path,
    raw_data_dir: Path,
    report_dir: Path,
    keep_raw_days: int,
    keep_report_days: int,
    snapshot_db: bool,
) -> dict[str, object]:
    """Apply date-based storage policy: compact, snapshot, cleanup raw data and reports."""
    # Compact first so the snapshot is a copy of the file that will be committed.
    compact = _compact_database(database_path)
    logger.info(
        "duckdb_compact path=%s reason=%s bytes_before=%s bytes=%s rows_deleted=%s",
        database_path,
        compact.get("reason"),
        compact.get("bytes_before"),
        compact.get("bytes"),
        compact.get("rows_deleted"),
    )
    snapshot_path = snapshot_database(database_path) if snapshot_db else None
    raw_removed = cleanup_date_directories(raw_data_dir, keep_days=keep_raw_days)
    report_removed = cleanup_dated_reports(report_dir, keep_days=keep_report_days)
    return {
        "snapshot_path": str(snapshot_path) if snapshot_path is not None else None,
        "raw_removed": raw_removed,
        "report_removed": report_removed,
        "db_bytes": compact.get("bytes"),
        "db_bytes_before": compact.get("bytes_before"),
        "db_compacted": compact.get("compacted"),
        "db_rows_deleted": compact.get("rows_deleted"),
        "db_reason": compact.get("reason"),
    }
