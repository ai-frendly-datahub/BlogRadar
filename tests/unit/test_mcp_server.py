from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest


def _init_articles_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE articles (
                id BIGINT PRIMARY KEY,
                category TEXT NOT NULL,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                link TEXT NOT NULL UNIQUE,
                summary TEXT,
                published TIMESTAMP,
                collected_at TIMESTAMP NOT NULL,
                entities_json TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO articles (id, category, source, title, link, summary, published, collected_at, entities_json)
            VALUES (1, 'techblog', 'Test', 'Snapshot article', 'https://example.com/1', 'summary', NULL, ?, '{}')
            """,
            [datetime.now(UTC).replace(tzinfo=None)],
        )
    finally:
        conn.close()


def _init_crawl_health_only_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE crawl_health (source TEXT, status TEXT)")
        conn.execute("INSERT INTO crawl_health VALUES ('test', 'ok')")
    finally:
        conn.close()


@pytest.mark.unit
def test_mcp_db_path_falls_back_to_latest_daily_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from blogradar.mcp_server import server

    db_path = tmp_path / "data" / "radar_data.duckdb"
    older = tmp_path / "data" / "daily" / "2026-04-09.duckdb"
    newer = tmp_path / "data" / "daily" / "2026-04-10.duckdb"
    _init_crawl_health_only_db(db_path)
    _init_articles_db(older)
    _init_articles_db(newer)

    monkeypatch.delenv("RADAR_DB_PATH", raising=False)
    monkeypatch.setattr(server, "load_settings", lambda: SimpleNamespace(database_path=db_path))

    assert server._db_path() == newer
