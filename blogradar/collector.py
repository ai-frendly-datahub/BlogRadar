from __future__ import annotations

import calendar
import html
import os
import re
import threading
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

import feedparser
import requests
from pybreaker import CircuitBreakerError
from radar_core import AdaptiveThrottler, CrawlHealthStore
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .exceptions import NetworkError, ParseError, SourceError
from .models import Article, Source
from .raw_logger import RawLogger
from .resilience import get_circuit_breaker_manager

# Identifying client name. Some public feeds reject the default python-requests
# agent. This is a fixed product name, not a browser impersonation list.
BLOGRADAR_USER_AGENT = (
    "BlogRadar/0.1 (+https://github.com/ai-frendly-datahub/BlogRadar; public-rss)"
)
_ENV_VAR_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": BLOGRADAR_USER_AGENT,
}
_DEFAULT_HEALTH_DB_PATH = "data/radar_data.duckdb"
_COLLECTION_CONTROL_LOCK = threading.Lock()
_ACTIVE_THROTTLER: AdaptiveThrottler | None = None
_ACTIVE_HEALTH_STORE: CrawlHealthStore | None = None


def _set_collection_controls(throttler: AdaptiveThrottler, health_store: CrawlHealthStore) -> None:
    global _ACTIVE_THROTTLER, _ACTIVE_HEALTH_STORE
    with _COLLECTION_CONTROL_LOCK:
        _ACTIVE_THROTTLER = throttler
        _ACTIVE_HEALTH_STORE = health_store


def _clear_collection_controls() -> None:
    global _ACTIVE_THROTTLER, _ACTIVE_HEALTH_STORE
    with _COLLECTION_CONTROL_LOCK:
        _ACTIVE_THROTTLER = None
        _ACTIVE_HEALTH_STORE = None


def _get_collection_controls() -> tuple[AdaptiveThrottler | None, CrawlHealthStore | None]:
    with _COLLECTION_CONTROL_LOCK:
        return _ACTIVE_THROTTLER, _ACTIVE_HEALTH_STORE


class RateLimiter:
    def __init__(self, min_interval: float = 0.5):
        self._min_interval: float = min_interval
        self._last_request: float = 0.0
        self._lock: threading.Lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_request = time.monotonic()


def _resolve_max_workers(max_workers: int | None = None) -> int:
    if max_workers is None:
        raw_value = os.environ.get("RADAR_MAX_WORKERS", "5")
        try:
            parsed = int(raw_value)
        except ValueError:
            parsed = 5
    else:
        parsed = max_workers

    return max(1, min(parsed, 10))


def _create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(_DEFAULT_HEADERS)

    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[408, 429, 500, 502, 503, 504, 522, 524],
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    return session


def _fetch_url_with_retry(
    url: str,
    timeout: int,
    headers: dict[str, str] | None = None,
    session: requests.Session | None = None,
    source_name: str | None = None,
    throttler: AdaptiveThrottler | None = None,
    health_store: CrawlHealthStore | None = None,
    max_attempts: int = 3,
) -> requests.Response:
    """Fetch URL with retry logic on transient errors."""
    merged = {**_DEFAULT_HEADERS, **(headers or {})}
    if throttler is None or health_store is None:
        active_throttler, active_health_store = _get_collection_controls()
        throttler = throttler or active_throttler
        health_store = health_store or active_health_store

    retryable_errors = (
        requests.exceptions.Timeout,
        requests.exceptions.ConnectionError,
        requests.exceptions.HTTPError,
    )

    for attempt in range(max_attempts):
        if source_name is not None and throttler is not None:
            throttler.acquire(source_name)

        try:
            if session is not None:
                response = session.get(url, timeout=timeout, headers=merged, verify=True)
            else:
                response = requests.get(url, timeout=timeout, headers=merged, verify=True)
            response.raise_for_status()

            if source_name is not None and throttler is not None:
                throttler.record_success(source_name)
                if health_store is not None:
                    delay = throttler.get_current_delay(source_name)
                    health_store.record_success(source_name, delay)

            return response
        except retryable_errors as exc:
            if source_name is not None and throttler is not None:
                retry_after: int | str | None = None
                if isinstance(exc, requests.exceptions.HTTPError):
                    response = exc.response
                    if response is not None and response.status_code == 429:
                        retry_after = _parse_retry_after(response.headers.get("Retry-After"))

                throttler.record_failure(source_name, retry_after=retry_after)
                if health_store is not None:
                    delay = throttler.get_current_delay(source_name)
                    health_store.record_failure(source_name, str(exc), delay)

            if attempt == max_attempts - 1:
                raise

    raise RuntimeError("Retry loop exited unexpectedly")


def _parse_retry_after(value: str | None) -> int | str | None:
    if value is None:
        return None

    stripped = value.strip()
    if not stripped:
        return None

    if stripped.isdigit():
        return int(stripped)

    return stripped


def _source_bool(source: Source, key: str) -> bool:
    value = source.config.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _env_var_names(value: object) -> list[str]:
    raw_names: list[str] = []
    if isinstance(value, str):
        raw_names = [value]
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        raw_names = [str(item) for item in value]
    names: list[str] = []
    for item in raw_names:
        candidate = item.strip()
        if not candidate:
            continue
        if _ENV_VAR_NAME.fullmatch(candidate) is None:
            raise ValueError("required_env must be an environment variable name")
        names.append(candidate)
    return names


def missing_required_env(source: Source) -> list[str]:
    """Return required env var names that are unset. Values are never returned."""
    configured = source.config.get("required_env", source.config.get("required_env_vars"))
    missing: list[str] = []
    for name in _env_var_names(configured):
        if not os.environ.get(name, "").strip():
            missing.append(name)
    return missing


def emit_missing_secret_warning(source_name: str, env_name: str) -> None:
    """Warn that a source was skipped. Prints the env var name, never a value."""
    if _ENV_VAR_NAME.fullmatch(env_name) is None:
        raise ValueError("required_env must be an environment variable name")
    message = f"{source_name} skipped; required env {env_name}"
    print(f"::warning title=BlogRadar missing secret::{message}", flush=True)


def _is_feed_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith((".rss", ".xml", ".atom")) or path.rstrip("/").endswith("/feed")


def _looks_like_feed(content: bytes) -> bool:
    head = content.lstrip()[:800].lower()
    return b"<rss" in head or b"<feed" in head or b"<rdf" in head


def collect_sources(
    sources: list[Source],
    *,
    category: str,
    limit_per_source: int = 30,
    timeout: int = 15,
    min_interval_per_host: float = 0.5,
    max_workers: int | None = None,
    health_db_path: str | None = None,
    max_age_days: int | None = None,
    raw_logger: RawLogger | None = None,
) -> tuple[list[Article], list[str]]:
    """Fetch items from all configured sources, returning articles and errors."""
    articles: list[Article] = []
    errors: list[str] = []
    manager = get_circuit_breaker_manager()
    workers = _resolve_max_workers(max_workers)
    enabled_sources = [source for source in sources if source.enabled]
    runnable_sources: list[Source] = []
    for source in enabled_sources:
        try:
            missing_env = missing_required_env(source)
        except ValueError:
            errors.append(f"{source.name}: required_env must be an environment variable name")
            continue
        if missing_env:
            for env_name in missing_env:
                emit_missing_secret_warning(source.name, env_name)
            if raw_logger is not None:
                raw_logger.log_skip(source_name=source.name, required_env=missing_env)
            errors.append(f"{source.name}: skipped_missing_env {', '.join(missing_env)}")
            continue
        runnable_sources.append(source)

    _reddit_types = {"reddit"}
    feed_sources = [
        source
        for source in runnable_sources
        if source.type.lower() == "rss"
        or (source.type.lower() in _reddit_types and _is_feed_url(source.url))
    ]
    reddit_sources = [
        source
        for source in runnable_sources
        if source.type.lower() in _reddit_types and source not in feed_sources
    ]
    unsupported_sources = [
        source for source in runnable_sources if source.type.lower() not in {"rss", *_reddit_types}
    ]
    source_hosts: dict[str, str] = {
        source.name: (urlparse(source.url).netloc.lower() or source.name) for source in feed_sources
    }
    rate_limiters: dict[str, RateLimiter] = {
        host: RateLimiter(min_interval=min_interval_per_host) for host in set(source_hosts.values())
    }
    throttler = AdaptiveThrottler(min_delay=max(0.001, min_interval_per_host))
    health_store = CrawlHealthStore(
        health_db_path or os.environ.get("RADAR_CRAWL_HEALTH_DB_PATH", _DEFAULT_HEALTH_DB_PATH)
    )
    _set_collection_controls(throttler, health_store)

    def _collect_for_source(source: Source) -> tuple[list[Article], list[str]]:
        if not _source_bool(source, "bypass_crawl_health") and health_store.is_disabled(
            source.name
        ):
            return [], [f"{source.name}: Source disabled (crawl health threshold reached)"]

        host = source_hosts[source.name]
        rate_limiters[host].acquire()

        session = _create_session()
        try:
            breaker = manager.get_breaker(source.name)
            result = breaker.call(
                _collect_single,
                source,
                category=category,
                limit=limit_per_source,
                timeout=timeout,
                session=session,
            )
            return result, []
        except CircuitBreakerError:
            return [], [f"{source.name}: Circuit breaker open (source unavailable)"]
        except SourceError as exc:
            return [], [str(exc)]
        except (NetworkError, ParseError) as exc:
            return [], [f"{source.name}: {exc}"]
        except Exception as exc:
            return [], [f"{source.name}: Unexpected error - {type(exc).__name__}: {exc}"]
        finally:
            session.close()

    try:
        if workers == 1:
            for source in feed_sources:
                source_articles, source_errors = _collect_for_source(source)
                articles.extend(source_articles)
                errors.extend(source_errors)
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_map: list[Future[tuple[list[Article], list[str]]]] = [
                    executor.submit(_collect_for_source, source) for source in feed_sources
                ]

                for future in future_map:
                    source_articles, source_errors = future.result()
                    articles.extend(source_articles)
                    errors.extend(source_errors)

        if reddit_sources:
            try:
                from radar_core import collect_reddit_sources

                reddit_articles, reddit_errors = collect_reddit_sources(
                    reddit_sources,
                    category=category,
                    limit=limit_per_source,
                    timeout=timeout,
                    health_db_path=health_db_path
                    or os.environ.get("RADAR_CRAWL_HEALTH_DB_PATH", _DEFAULT_HEALTH_DB_PATH),
                )
                articles.extend(reddit_articles)
                errors.extend(reddit_errors)
            except ImportError:
                errors.append(
                    f"Reddit collection unavailable for {len(reddit_sources)} source(s). "
                    "Ensure radar-core reddit support is installed."
                )

        for source in unsupported_sources:
            errors.append(
                f"{source.name}: Source type '{source.type}' is cataloged but not collected by "
                "the standard pipeline"
            )
    finally:
        health_store.close()
        _clear_collection_controls()

    # Filter out articles older than max_age_days (freshness gate)
    if max_age_days is not None:
        cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
        before = len(articles)
        articles = [a for a in articles if a.published is None or a.published >= cutoff]
        filtered = before - len(articles)
        if filtered > 0:
            errors.append(
                f"Freshness filter: removed {filtered} articles older than {max_age_days} days"
            )

    return articles, errors


def _collect_single(
    source: Source,
    *,
    category: str,
    limit: int,
    timeout: int,
    session: requests.Session | None = None,
) -> list[Article]:
    feed_type = source.type.lower() in {"rss", "reddit"} and (
        source.type.lower() == "rss" or _is_feed_url(source.url)
    )
    if not feed_type:
        raise SourceError(source.name, f"Unsupported source type '{source.type}'")

    try:
        response = _fetch_url_with_retry(
            source.url,
            timeout,
            session=session,
            source_name=source.name,
        )
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
        raise NetworkError(f"Network error fetching {source.name}: {exc}") from exc
    except requests.exceptions.RequestException as exc:
        raise SourceError(source.name, f"Request failed: {exc}", exc) from exc

    try:
        body = response.content if isinstance(response.content, bytes) else bytes(response.content)
        if not body.strip() or (not _looks_like_feed(body)):
            raise ParseError(f"Feed from {source.name} was not RSS/Atom")
        feed = feedparser.parse(body)
        if not feed.entries:
            raise ParseError(f"Feed from {source.name} contained no entries")
        items: list[Article] = []

        for entry in feed.entries[:limit]:
            published = _extract_datetime(entry)
            summary = _entry_text(entry, "summary") or _entry_text(entry, "description")
            if not summary:
                _content = entry.get("content", [])
                if isinstance(_content, list) and _content:
                    first_item = _content[0]
                    if isinstance(first_item, Mapping):
                        value = first_item.get("value")
                        if isinstance(value, str):
                            summary = value

            title = html.unescape(_entry_text(entry, "title").strip()) or "(no title)"
            link = _entry_text(entry, "link").strip()
            # Data validation: skip entries without title or link
            if not title or title == "(no title)" or not link:
                continue
            summary = summary.strip() or title

            items.append(
                Article(
                    title=title,
                    link=link,
                    summary=html.unescape(summary),
                    published=published,
                    source=source.name,
                    category=category,
                )
            )

        if not items:
            raise ParseError(f"Feed from {source.name} contained no usable entries")
        return items
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError(f"Failed to parse feed from {source.name}: {exc}") from exc


def _extract_datetime(entry: Mapping[str, Any]) -> datetime | None:
    """Parse a feed entry date into a timezone-aware datetime."""
    published_parsed = entry.get("published_parsed")
    if isinstance(published_parsed, time.struct_time):
        return datetime.fromtimestamp(calendar.timegm(published_parsed), tz=UTC)

    updated_parsed = entry.get("updated_parsed")
    if isinstance(updated_parsed, time.struct_time):
        return datetime.fromtimestamp(calendar.timegm(updated_parsed), tz=UTC)

    for key in ("published", "updated", "date"):
        raw = entry.get(key)
        if raw:
            try:
                dt = parsedate_to_datetime(str(raw))
                if dt and dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                return dt
            except Exception:
                continue
    return None


def _entry_text(entry: Mapping[str, Any], key: str) -> str:
    value = entry.get(key)
    return value if isinstance(value, str) else ""
