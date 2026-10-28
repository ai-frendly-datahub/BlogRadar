"""Reddit collection stays inside the public robots and rate-limit rules."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from radar_core.crawl_health import CrawlHealthStore

from blogradar.models import Article, CategoryConfig, Source
from blogradar.quality_report import build_quality_report
from blogradar.reddit_feed import (
    REDDIT_USER_AGENT,
    collect_reddit_public,
    create_reddit_session,
    reset_reddit_request_clock,
)

pytestmark = pytest.mark.unit

# Operative rules from https://www.reddit.com/robots.txt on 2026-10-28.
OBSERVED_ROBOTS = """\
# Welcome to Reddit's robots.txt
User-agent: *
Disallow: /
"""

ALLOW_RSS_ROBOTS = """\
User-agent: *
Allow: /r/
Disallow: /api/
"""

BLOCK_MULTI_ROBOTS = """\
User-agent: *
Disallow: /r/python+golang
Allow: /r/
"""


@pytest.fixture(autouse=True)
def _reset_reddit_clock() -> None:
    reset_reddit_request_clock()


class _Response:
    def __init__(
        self,
        status_code: int,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
        *,
        url: str = "",
        reason: str = "OK",
    ) -> None:
        self.status_code = status_code
        self.content = body
        self.headers = headers or {}
        self.url = url
        self.reason = reason
        self.encoding = "utf-8"


def _source(name: str, url: str | None = None) -> Source:
    slug = name.removeprefix("r/")
    return Source(
        name=name,
        type="reddit",
        url=url or f"https://www.reddit.com/r/{slug}/.rss",
    )


def _atom(subreddit: str, title: str) -> bytes:
    return f"""<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>{title}</title>
        <link href="https://www.reddit.com/r/{subreddit}/comments/abc/{title.replace(' ', '_').lower()}/"/>
        <updated>2026-10-27T03:04:05Z</updated>
      </entry>
    </feed>
    """.encode()


def _combined_atom() -> bytes:
    return b"""<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Python item</title>
        <link href="https://www.reddit.com/r/Python/comments/py1/python_item/"/>
        <updated>2026-10-27T03:04:05Z</updated>
      </entry>
      <entry>
        <title>Go item</title>
        <link href="https://www.reddit.com/r/golang/comments/go1/go_item/"/>
        <updated>2026-10-27T04:05:06Z</updated>
      </entry>
    </feed>
    """


def _install_get(monkeypatch: pytest.MonkeyPatch, handler: Any) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []

    def _get(_self: object, url: str, **kwargs: Any) -> _Response:
        calls.append((url, kwargs))
        return handler(url, kwargs)

    monkeypatch.setattr("blogradar.reddit_feed.requests.Session.get", _get)
    return calls


def _robots_response(url: str, body: str) -> _Response:
    return _Response(200, body.encode(), url=url, reason="OK")


def test_session_has_one_user_agent_and_does_not_retry_status() -> None:
    session = create_reddit_session()
    try:
        assert session.headers["User-Agent"] == REDDIT_USER_AGENT
        assert "BlogRadar/0.1" in session.headers["User-Agent"]
        assert "github.com/ai-frendly-datahub/BlogRadar" in session.headers["User-Agent"]
        assert session.verify is True
        assert session.trust_env is False
        assert session.proxies == {}
        assert "Authorization" not in session.headers
        retries = session.get_adapter("https://www.reddit.com/").max_retries
        assert retries.total == 0
        assert 429 not in (retries.status_forcelist or ())
    finally:
        session.close()


def test_observed_robots_blocks_content_fetches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_get(
        monkeypatch,
        lambda url, _kwargs: _robots_response(url, OBSERVED_ROBOTS),
    )
    sources = [_source("r/coding"), _source("r/golang"), _source("r/Python")]
    articles, errors = collect_reddit_public(
        sources,
        category="techblog",
        limit=5,
        timeout=5,
        min_interval=0,
    )
    assert articles == []
    assert len(errors) == 3
    assert all("robots_disallowed" in error for error in errors)
    assert [url for url, _kwargs in calls] == ["https://www.reddit.com/robots.txt"]
    assert all(".json" not in url and "old.reddit.com" not in url for url, _kwargs in calls)


def test_allowed_subreddits_share_one_rss_request(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_get(monkeypatch, _allow_combined)
    articles, errors = collect_reddit_public(
        [_source("r/Python"), _source("r/golang")],
        category="techblog",
        limit=5,
        timeout=5,
        min_interval=0,
    )
    assert errors == []
    by_source = {article.source: article.title for article in articles}
    assert by_source == {"r/Python": "Python item", "r/golang": "Go item"}
    content_urls = [url for url, _kwargs in calls if not url.endswith("/robots.txt")]
    assert content_urls == ["https://www.reddit.com/r/Python+golang/.rss"]
    for url, kwargs in calls:
        assert kwargs["verify"] is True
        assert kwargs["allow_redirects"] is False
        assert kwargs["headers"]["User-Agent"] == REDDIT_USER_AGENT
        assert "proxies" not in kwargs
        assert "Authorization" not in kwargs["headers"]
        assert ".json" not in url
        assert "old.reddit.com" not in url
        assert "oauth.reddit.com" not in url


def test_multi_feed_falls_back_to_serial_when_robots_blocks_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(
        "blogradar.reddit_feed.time.sleep",
        lambda seconds: sleeps.append(seconds),
    )

    def _handler(url: str, _kwargs: dict[str, Any]) -> _Response:
        if url.endswith("/robots.txt"):
            return _robots_response(url, BLOCK_MULTI_ROBOTS)
        if url.endswith("/python/.rss"):
            return _Response(200, _atom("python", "Py serial"), url=url)
        if url.endswith("/golang/.rss"):
            return _Response(200, _atom("golang", "Go serial"), url=url)
        raise AssertionError(url)

    calls = _install_get(monkeypatch, _handler)
    articles, errors = collect_reddit_public(
        [_source("r/python"), _source("r/golang")],
        category="techblog",
        limit=5,
        timeout=5,
        min_interval=5,
    )
    assert errors == []
    assert {article.title for article in articles} == {"Py serial", "Go serial"}
    content_urls = [url for url, _kwargs in calls if not url.endswith("/robots.txt")]
    assert content_urls == [
        "https://www.reddit.com/r/python/.rss",
        "https://www.reddit.com/r/golang/.rss",
    ]
    assert all("+" not in url for url in content_urls)
    assert len([item for item in sleeps if item >= 4]) >= 2


def test_short_retry_after_is_slept_and_attempts_stay_capped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(
        "blogradar.reddit_feed.time.sleep",
        lambda seconds: sleeps.append(seconds),
    )
    content_calls = {"count": 0}

    def _handler(url: str, _kwargs: dict[str, Any]) -> _Response:
        if url.endswith("/robots.txt"):
            return _robots_response(url, ALLOW_RSS_ROBOTS)
        content_calls["count"] += 1
        if content_calls["count"] == 1:
            return _Response(
                429,
                b"",
                {"Retry-After": "1"},
                url=url,
                reason="Too Many Requests",
            )
        return _Response(200, _atom("python", "After retry"), url=url)

    _install_get(monkeypatch, _handler)
    articles, errors = collect_reddit_public(
        [_source("r/python")],
        category="techblog",
        limit=5,
        timeout=5,
        min_interval=0,
    )
    assert errors == []
    assert [article.title for article in articles] == ["After retry"]
    assert content_calls["count"] == 2
    assert 1 in sleeps


def test_long_retry_after_is_not_retried_inline(monkeypatch: pytest.MonkeyPatch) -> None:
    content_calls = {"count": 0}

    def _handler(url: str, _kwargs: dict[str, Any]) -> _Response:
        if url.endswith("/robots.txt"):
            return _robots_response(url, ALLOW_RSS_ROBOTS)
        content_calls["count"] += 1
        return _Response(
            429,
            b"",
            {"Retry-After": "120"},
            url=url,
            reason="Too Many Requests",
        )

    calls = _install_get(monkeypatch, _handler)
    _articles, errors = collect_reddit_public(
        [_source("r/python")],
        category="techblog",
        limit=5,
        timeout=5,
        min_interval=0,
    )
    assert content_calls["count"] == 1
    assert any("rate_limited" in error and "429 Client Error:" in error for error in errors)
    assert all(kwargs["verify"] is True for _url, kwargs in calls)


def test_429_cooldown_retries_later_without_permanent_disable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    content_calls = {"count": 0}
    mode = {"value": "limit"}

    def _handler(url: str, _kwargs: dict[str, Any]) -> _Response:
        if url.endswith("/robots.txt"):
            return _robots_response(url, ALLOW_RSS_ROBOTS)
        content_calls["count"] += 1
        if mode["value"] == "limit":
            return _Response(
                429,
                b"",
                {"Retry-After": "120"},
                url=url,
                reason="Too Many Requests",
            )
        return _Response(200, _combined_atom(), url=url)

    calls = _install_get(monkeypatch, _handler)
    sources = [_source("r/Python"), _source("r/golang")]
    with CrawlHealthStore(str(tmp_path / "health.duckdb"), failure_threshold=10) as store:
        _articles, errors = collect_reddit_public(
            sources,
            category="techblog",
            limit=5,
            timeout=5,
            health_store=store,
            min_interval=0,
        )
        assert content_calls["count"] == 1
        assert any("Python+golang" in url for url, _kwargs in calls)
        assert all("rate_limited" in error for error in errors)
        for name in ("r/Python", "r/golang"):
            record = store.get_health(name)
            assert record is not None
            assert record.disabled
            assert record.last_error is not None
            assert record.last_error.startswith("429 Client Error:")

        calls.clear()
        content_calls["count"] = 0
        _articles, cooled = collect_reddit_public(
            sources,
            category="techblog",
            limit=5,
            timeout=5,
            health_store=store,
            min_interval=0,
        )
        assert calls == []
        assert all("rate_limited: cooldown" in error for error in cooled)
        assert store.is_disabled("r/Python")

        past = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=2)
        store.conn.execute("UPDATE crawl_health SET updated_at = ?", [past])
        mode["value"] = "ok"
        articles, recovered = collect_reddit_public(
            sources,
            category="techblog",
            limit=5,
            timeout=5,
            health_store=store,
            min_interval=0,
        )
        assert recovered == []
        assert {article.source for article in articles} == {"r/Python", "r/golang"}
        assert not store.is_disabled("r/Python")
        assert not store.is_disabled("r/golang")

        mode["value"] = "limit"
        _articles, limited_again = collect_reddit_public(
            sources,
            category="techblog",
            limit=5,
            timeout=5,
            health_store=store,
            min_interval=0,
        )
        assert any("rate_limited" in error for error in limited_again)
        assert store.is_disabled("r/Python")
        store.conn.execute("UPDATE crawl_health SET updated_at = ?", [past])
        mode["value"] = "ok"
        _articles, retried = collect_reddit_public(
            sources,
            category="techblog",
            limit=5,
            timeout=5,
            health_store=store,
            min_interval=0,
        )
        assert retried == []
        assert not store.is_disabled("r/Python")


def test_redirect_to_old_reddit_is_not_followed(monkeypatch: pytest.MonkeyPatch) -> None:
    def _handler(url: str, _kwargs: dict[str, Any]) -> _Response:
        if "old.reddit.com" in url:
            raise AssertionError(url)
        if url.endswith("/robots.txt"):
            return _robots_response(url, ALLOW_RSS_ROBOTS)
        return _Response(
            302,
            b"",
            {"Location": "https://old.reddit.com/r/python/.rss"},
            url=url,
            reason="Found",
        )

    calls = _install_get(monkeypatch, _handler)
    articles, errors = collect_reddit_public(
        [_source("r/python", "https://old.reddit.com/r/python/.rss")],
        category="techblog",
        limit=5,
        timeout=5,
        min_interval=0,
    )
    assert articles == []
    assert any("redirect_blocked" in error for error in errors)
    assert all("old.reddit.com" not in url for url, _kwargs in calls)
    assert all(not url.endswith(".json") for url, _kwargs in calls)


def test_missing_api_env_uses_public_rss(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from blogradar.collector import collect_sources

    calls = _install_get(monkeypatch, _allow_single)
    monkeypatch.delenv("BLOGRADAR_REDDIT_API_TOKEN", raising=False)
    source = Source(
        name="r/python",
        type="reddit",
        url="https://www.reddit.com/r/python/.json",
        config={"required_env": "BLOGRADAR_REDDIT_API_TOKEN"},
    )
    articles, errors = collect_sources([source], category="techblog", max_workers=1)
    warning = capsys.readouterr().out
    assert "BLOGRADAR_REDDIT_API_TOKEN" in warning
    assert "using public rss" in warning
    assert articles and articles[0].title == "Python item"
    assert not any("skipped_missing_env" in error for error in errors)
    requested = " ".join(url for url, _kwargs in calls)
    assert "/python/.rss" in requested
    assert ".json" not in requested
    assert "oauth.reddit.com" not in requested


def test_configured_token_is_not_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    from blogradar.collector import collect_sources

    calls = _install_get(monkeypatch, _allow_single)
    monkeypatch.setenv("BLOGRADAR_REDDIT_API_TOKEN", "dummy-token-value")
    source = Source(
        name="r/python",
        type="reddit",
        url="https://oauth.reddit.com/r/python/new",
        config={"required_env": "BLOGRADAR_REDDIT_API_TOKEN"},
    )
    collect_sources([source], category="techblog", max_workers=1)
    rendered = repr(calls)
    assert "dummy-token-value" not in rendered
    assert "oauth.reddit.com" not in rendered
    assert "/python/.rss" in rendered


def test_reddit_requests_are_not_concurrent(monkeypatch: pytest.MonkeyPatch) -> None:
    in_flight = {"count": 0, "max": 0}
    gate = threading.Lock()

    def _get(_self: object, url: str, **_kwargs: Any) -> _Response:
        with gate:
            in_flight["count"] += 1
            in_flight["max"] = max(in_flight["max"], in_flight["count"])
        try:
            time.sleep(0.05)
            if url.endswith("/robots.txt"):
                return _robots_response(url, ALLOW_RSS_ROBOTS)
            return _Response(200, _atom("python", "Threaded"), url=url)
        finally:
            with gate:
                in_flight["count"] -= 1

    monkeypatch.setattr("blogradar.reddit_feed.requests.Session.get", _get)
    errors: list[list[str]] = []

    def _run(name: str) -> None:
        _articles, run_errors = collect_reddit_public(
            [_source(name)],
            category="techblog",
            limit=1,
            timeout=5,
            min_interval=0,
        )
        errors.append(run_errors)

    threads = [
        threading.Thread(target=_run, args=("r/python",)),
        threading.Thread(target=_run, args=("r/golang",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert in_flight["max"] == 1
    assert errors == [[], []]


def test_rate_limited_source_keeps_window_articles() -> None:
    source = Source(
        name="r/golang",
        type="reddit",
        url="https://www.reddit.com/r/golang/.rss",
        config={"event_model": "blog_post"},
    )
    article = Article(
        title="Earlier golang post",
        link="https://www.reddit.com/r/golang/comments/old/earlier/",
        summary="Earlier golang post",
        published=datetime(2026, 10, 26, tzinfo=UTC),
        source="r/golang",
        category="techblog",
    )
    report = build_quality_report(
        category=CategoryConfig(
            category_name="techblog",
            display_name="Tech Blog",
            sources=[source],
            entities=[],
        ),
        articles=[article],
        errors=[
            "[r/golang] rate_limited: 429 Client Error: Too Many Requests "
            "for url: https://www.reddit.com/r/golang/.rss"
        ],
        quality_config={
            "data_quality": {"quality_outputs": {"tracked_event_models": ["repository_release"]}}
        },
        generated_at=datetime(2026, 10, 27, tzinfo=UTC),
    )
    row = report["sources"][0]
    assert row["status"] == "rate_limited"
    assert row["collection_status"] == "rate_limited"
    assert row["article_count"] == 1
    assert row["window_residual_count"] == 1
    assert row["errors"][0].startswith("[r/golang]")
    assert report["summary"]["rate_limited_sources"] == 1
    assert report["summary"]["not_tracked_sources"] == 0


def _allow_combined(url: str, _kwargs: dict[str, Any]) -> _Response:
    if url.endswith("/robots.txt"):
        return _robots_response(url, ALLOW_RSS_ROBOTS)
    if url.endswith("/Python+golang/.rss"):
        return _Response(200, _combined_atom(), url=url)
    raise AssertionError(url)


def _allow_single(url: str, _kwargs: dict[str, Any]) -> _Response:
    if url.endswith("/robots.txt"):
        return _robots_response(url, ALLOW_RSS_ROBOTS)
    if url.endswith("/python/.rss"):
        return _Response(200, _atom("Python", "Python item"), url=url)
    raise AssertionError(url)
