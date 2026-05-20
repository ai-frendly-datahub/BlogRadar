from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import duckdb
import pytest

from blogradar.common import quality_checks

pytestmark = pytest.mark.unit


@pytest.fixture
def quality_db() -> Generator[duckdb.DuckDBPyConnection]:
    con = duckdb.connect(":memory:")
    con.execute("""
        CREATE TABLE articles (
            url TEXT,
            title TEXT,
            summary TEXT,
            language TEXT,
            published_at TIMESTAMP
        )
        """)
    now = datetime.now(UTC).replace(tzinfo=None)
    future = now + timedelta(days=1)
    con.executemany(
        "INSERT INTO articles VALUES (?, ?, ?, ?, ?)",
        [
            ("https://example.com/a", "Alpha", "short", "ko", now),
            ("https://example.com/a", "", "longer summary", "xx", future),
            (None, None, None, None, None),
        ],
    )
    try:
        yield con
    finally:
        con.close()


def test_run_all_checks_prints_all_sections(
    quality_db: duckdb.DuckDBPyConnection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    quality_checks.run_all_checks(
        quality_db,
        table_name="articles",
        null_conditions={"title": "title IS NULL OR title = ''"},
        text_columns=["title", "summary"],
        language_column="language",
        allowed_languages={"ko", "en"},
        url_column="url",
        date_column="published_at",
    )

    output = capsys.readouterr().out
    assert "Total records: 3" in output
    assert "title: 2 / 3" in output
    assert "2x: https://example.com/a" in output
    assert "Invalid language values:" in output
    assert "xx: 1" in output
    assert "future dates: 1" in output


def test_run_all_checks_skips_missing_optional_columns(
    capsys: pytest.CaptureFixture[str],
) -> None:
    con = duckdb.connect(":memory:")
    try:
        con.execute("CREATE TABLE minimal (url TEXT, title TEXT)")
        quality_checks.run_all_checks(
            con,
            table_name="minimal",
            null_conditions={"title": "title IS NULL"},
            text_columns=[],
            language_column="language",
            date_column="published_at",
        )
    finally:
        con.close()

    output = capsys.readouterr().out
    assert "No records found." in output
    assert "No duplicate URLs found." in output
    assert "No text columns provided." in output
    assert "Skipping language check: missing column 'language'" in output
    assert "Skipping date check: missing column 'published_at'" in output


def test_language_check_accepts_allowed_values_and_empty_table(
    capsys: pytest.CaptureFixture[str],
) -> None:
    con = duckdb.connect(":memory:")
    try:
        con.execute("CREATE TABLE languages (language TEXT)")
        quality_checks.check_language_values(
            con,
            table_name="languages",
            allowed_languages={"ko"},
        )
        con.execute("INSERT INTO languages VALUES ('ko')")
        quality_checks.check_language_values(
            con,
            table_name="languages",
            allowed_languages={"ko"},
        )
    finally:
        con.close()

    output = capsys.readouterr().out
    assert "No language values found." in output
    assert "All language values are allowed." in output


def test_text_lengths_prints_na_for_empty_table(capsys: pytest.CaptureFixture[str]) -> None:
    con = duckdb.connect(":memory:")
    try:
        con.execute("CREATE TABLE empty_text (body TEXT)")
        quality_checks.check_text_lengths(con, table_name="empty_text", text_columns=["body"])
    finally:
        con.close()

    assert "body: avg/min/max = N/A / None / None" in capsys.readouterr().out


def test_conversion_helpers_reject_invalid_values() -> None:
    with pytest.raises(TypeError):
        quality_checks._to_int(object())
    with pytest.raises(TypeError):
        quality_checks._to_optional_float(object())
    with pytest.raises(ValueError):
        quality_checks._to_int("not-a-number")


def test_fetchone_required_raises_when_query_returns_no_row() -> None:
    con = duckdb.connect(":memory:")
    try:
        with pytest.raises(RuntimeError):
            quality_checks._fetchone_required(con, "SELECT 1 WHERE FALSE")
    finally:
        con.close()
