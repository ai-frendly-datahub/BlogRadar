"""Public Reddit RSS collector.

Reddit's JSON listing, user-agent rotation, and old.reddit.com fallback are not
used. Those paths evade rate limits or imitate a browser. This collector reads
robots.txt first, requests at most one combined public RSS feed when that file
allows it, and never issues overlapping Reddit requests.

HTTP 429 is stored as a transient crawl-health failure. ``claim_retry`` only
runs for a disabled row, so one 429 arms that cooldown immediately. The source
stays eligible for a later probe; it is not switched off forever.
"""

from __future__ import annotations

import calendar
import html
import re
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import feedparser
import requests
from radar_core.crawl_health import CrawlHealthStore

from blogradar.exceptions import SourceError
from blogradar.models import Article, Source

REDDIT_USER_AGENT = (
    "BlogRadar/0.1 (+https://github.com/ai-frendly-datahub/BlogRadar; reddit public rss)"
)
REDDIT_ACCEPT = "application/atom+xml, application/rss+xml, application/xml;q=0.9, */*;q=0.1"
REDDIT_MIN_INTERVAL_SECONDS = 5.0
REDDIT_MAX_ATTEMPTS = 2
REDDIT_INLINE_RETRY_SECONDS = 30.0
REDDIT_COOLDOWN_SECONDS = 86400.0
REDDIT_ROBOTS_URL = "https://www.reddit.com/robots.txt"

_PUBLIC_HOSTS = frozenset({"www.reddit.com", "reddit.com"})
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_MAX_REDIRECTS = 2
_SUBREDDIT_NAME = re.compile(r"/r/([A-Za-z0-9_]{2,21})(?:/|$)")
_TRANSIENT_HTTP_ERROR = re.compile(r"^(408|429|500|502|503|504) (?:Client|Server) Error:")
_REDDIT_LOCK = threading.Lock()
_last_reddit_request_at = 0.0


def reset_reddit_request_clock() -> None:
    """Clear the inter-request gap. Tests use this so cases do not wait on each other."""
    global _last_reddit_request_at
    with _REDDIT_LOCK:
        _last_reddit_request_at = 0.0


def create_reddit_session() -> requests.Session:
    """Session for Reddit. No proxy env, no TLS bypass, no status retries."""
    session = requests.Session()
    session.trust_env = False
    session.verify = True
    session.headers["User-Agent"] = REDDIT_USER_AGENT
    session.headers["Accept"] = REDDIT_ACCEPT
    return session


def collect_reddit_public(
    sources: Sequence[Source],
    *,
    category: str,
    limit: int,
    timeout: int,
    health_store: CrawlHealthStore | None = None,
    min_interval: float = REDDIT_MIN_INTERVAL_SECONDS,
) -> tuple[list[Article], list[str]]:
    """Fetch Reddit sources serially, or skip them when robots.txt disallows the feed."""
    selected = [source for source in sources if source.enabled]
    if not selected:
        return [], []
    try:
        with _REDDIT_LOCK:
            return _collect_locked(
                selected,
                category=category,
                limit=limit,
                timeout=timeout,
                health_store=health_store,
                min_interval=max(0.0, min_interval),
            )
    except Exception as exc:
        message = f"Unexpected error - {type(exc).__name__}: {exc}"
        return [], [_source_error(source.name, message) for source in selected]


def _collect_locked(
    sources: list[Source],
    *,
    category: str,
    limit: int,
    timeout: int,
    health_store: CrawlHealthStore | None,
    min_interval: float,
) -> tuple[list[Article], list[str]]:
    articles: list[Article] = []
    errors: list[str] = []
    due: list[Source] = []
    for source in sources:
        if _public_rss_url(source) is None:
            errors.append(_source_error(source.name, f"unsupported reddit url: {source.url}"))
            continue
        if not _content_probe_due(health_store, source.name):
            errors.append(_waiting_error(health_store, source.name))
            continue
        due.append(source)
    if not due:
        return articles, errors

    session = create_reddit_session()
    try:
        robots_result = _fetch(
            session,
            REDDIT_ROBOTS_URL,
            timeout=timeout,
            min_interval=min_interval,
            robots=None,
        )
        if robots_result.rate_limited_text:
            _mark_group_rate_limited(
                due,
                health_store,
                robots_result.rate_limited_text,
                robots_result.retry_at,
                errors,
            )
            return articles, errors
        robots_failure = _robots_failure(robots_result)
        if robots_failure is not None:
            errors.extend(_source_error(source.name, robots_failure) for source in due)
            return articles, errors

        response = robots_result.response
        assert response is not None
        parser = _parse_robots(_response_text(response))
        if parser is None:
            errors.extend(
                _source_error(source.name, "robots_unavailable: robots.txt had no rules")
                for source in due
            )
            return articles, errors

        allowed: list[Source] = []
        for source in due:
            rss_url = _public_rss_url(source)
            if rss_url is None:
                errors.append(_source_error(source.name, f"unsupported reddit url: {source.url}"))
                continue
            if not parser.can_fetch(REDDIT_USER_AGENT, rss_url):
                errors.append(_source_error(source.name, f"robots_disallowed: {rss_url}"))
                continue
            allowed.append(source)
        probe, claim_errors = _claim_probe(allowed, health_store)
        errors.extend(claim_errors)
        if not probe:
            return articles, errors

        groups, group_errors = _feed_groups(probe, parser)
        errors.extend(group_errors)
        _fetch_groups(
            session,
            groups,
            parser=parser,
            category=category,
            limit=limit,
            timeout=timeout,
            min_interval=min_interval,
            health_store=health_store,
            articles=articles,
            errors=errors,
        )
        return articles, errors
    finally:
        session.close()


def _fetch_groups(
    session: requests.Session,
    groups: list[tuple[str, list[Source]]],
    *,
    parser: RobotFileParser,
    category: str,
    limit: int,
    timeout: int,
    min_interval: float,
    health_store: CrawlHealthStore | None,
    articles: list[Article],
    errors: list[str],
) -> None:
    stop_text: str | None = None
    stop_retry_at: datetime | None = None
    for url, group in groups:
        if stop_text is not None:
            _mark_group_rate_limited(group, health_store, stop_text, stop_retry_at, errors)
            continue
        result = _fetch(
            session,
            url,
            timeout=timeout,
            min_interval=min_interval,
            robots=parser,
        )
        if result.rate_limited_text:
            stop_text = result.rate_limited_text
            stop_retry_at = result.retry_at
            _mark_group_rate_limited(group, health_store, stop_text, stop_retry_at, errors)
            continue
        if result.error:
            errors.extend(_source_error(source.name, result.error) for source in group)
            continue
        response = result.response
        if response is None or response.status_code != 200:
            status = response.status_code if response is not None else 0
            target = response.url if response is not None and response.url else url
            message = f"Request failed: HTTP {status} for url: {target}"
            errors.extend(_source_error(source.name, message) for source in group)
            continue
        parsed, parse_errors, ok = _articles_from_feed(
            response.content,
            group,
            category=category,
            limit=limit,
        )
        articles.extend(parsed)
        errors.extend(parse_errors)
        if ok and health_store is not None:
            for source in group:
                health_store.record_success(source.name, REDDIT_MIN_INTERVAL_SECONDS)
                health_store.finish_retry(source.name)


def _mark_group_rate_limited(
    sources: Sequence[Source],
    health_store: CrawlHealthStore | None,
    http_error: str,
    retry_at: datetime | None,
    errors: list[str],
) -> None:
    for source in sources:
        if health_store is not None:
            _arm_rate_limit_cooldown(health_store, source.name, http_error, retry_at)
        errors.append(_source_error(source.name, f"rate_limited: {http_error}"))


def _arm_rate_limit_cooldown(
    health_store: CrawlHealthStore,
    source_name: str,
    http_error: str,
    retry_at: datetime | None,
) -> None:
    """Disable the row after one 429 so ``claim_retry`` can run after the cooldown.

    ``claim_retry`` ignores enabled rows. Repeating the failure up to the store
    threshold flips ``disabled`` without a second HTTP request. A later successful
    probe calls ``finish_retry``. ``postpone_retry`` keeps a long Retry-After.
    """
    if _TRANSIENT_HTTP_ERROR.match(http_error) is None:
        raise ValueError("rate limit records must use a transient HTTP error")
    budget = max(1, health_store.failure_threshold)
    for _ in range(budget):
        health_store.record_failure(source_name, http_error, REDDIT_MIN_INTERVAL_SECONDS)
        health_store.flush()
        record = health_store.get_health(source_name)
        if (
            record is not None
            and record.disabled
            and _TRANSIENT_HTTP_ERROR.match(record.last_error or "")
        ):
            break
    if retry_at is not None:
        health_store.postpone_retry(source_name, retry_at)


def _content_probe_due(health_store: CrawlHealthStore | None, source_name: str) -> bool:
    if health_store is None:
        return True
    record = health_store.get_health(source_name)
    if record is None or not record.disabled:
        return True
    if record.updated_at is None or _TRANSIENT_HTTP_ERROR.match(record.last_error or "") is None:
        return False
    updated = record.updated_at
    if updated.tzinfo is not None:
        updated = updated.astimezone(UTC).replace(tzinfo=None)
    now = datetime.now(UTC).replace(tzinfo=None)
    return updated <= now - timedelta(seconds=REDDIT_COOLDOWN_SECONDS)


def _claim_probe(
    sources: Sequence[Source],
    health_store: CrawlHealthStore | None,
) -> tuple[list[Source], list[str]]:
    probe: list[Source] = []
    errors: list[str] = []
    for source in sources:
        if health_store is not None and health_store.is_disabled(source.name):
            if not health_store.claim_retry(source.name, REDDIT_COOLDOWN_SECONDS):
                errors.append(_waiting_error(health_store, source.name))
                continue
        probe.append(source)
    return probe, errors


def _waiting_error(health_store: CrawlHealthStore | None, source_name: str) -> str:
    record = health_store.get_health(source_name) if health_store is not None else None
    if record is not None and _TRANSIENT_HTTP_ERROR.match(record.last_error or ""):
        return _source_error(source_name, "rate_limited: cooldown")
    return _source_error(source_name, "blocked: crawl health will not retry this error")


def _feed_groups(
    sources: Sequence[Source],
    robots: RobotFileParser,
) -> tuple[list[tuple[str, list[Source]]], list[str]]:
    errors: list[str] = []
    allowed: list[Source] = []
    for source in sources:
        rss_url = _public_rss_url(source)
        if rss_url is None:
            errors.append(_source_error(source.name, f"unsupported reddit url: {source.url}"))
            continue
        if not robots.can_fetch(REDDIT_USER_AGENT, rss_url):
            errors.append(_source_error(source.name, f"robots_disallowed: {rss_url}"))
            continue
        allowed.append(source)
    if not allowed:
        return [], errors
    combined = _combined_rss_url(allowed)
    if combined is not None and (
        len(allowed) == 1 or robots.can_fetch(REDDIT_USER_AGENT, combined)
    ):
        return [(combined, allowed)], errors
    serial: list[tuple[str, list[Source]]] = []
    for source in allowed:
        rss_url = _public_rss_url(source)
        if rss_url is not None:
            serial.append((rss_url, [source]))
    return serial, errors


def _public_rss_url(source: Source) -> str | None:
    name = _subreddit_name(source.url)
    if name is None:
        return None
    return f"https://www.reddit.com/r/{name}/.rss"


def _combined_rss_url(sources: Sequence[Source]) -> str | None:
    names: list[str] = []
    for source in sources:
        name = _subreddit_name(source.url)
        if name is None:
            return None
        names.append(name)
    if not names:
        return None
    if len(names) == 1:
        return f"https://www.reddit.com/r/{names[0]}/.rss"
    return "https://www.reddit.com/r/" + "+".join(names) + "/.rss"


def _subreddit_name(url: str) -> str | None:
    match = _SUBREDDIT_NAME.search(urlparse(url).path)
    if match is None:
        return None
    return match.group(1)


@dataclass
class _SendResult:
    response: requests.Response | None
    error: str | None
    retry_at: datetime | None
    rate_limited_text: str | None


def _fetch(
    session: requests.Session,
    url: str,
    *,
    timeout: int,
    min_interval: float,
    robots: RobotFileParser | None,
) -> _SendResult:
    current = url
    for _hop in range(_MAX_REDIRECTS + 1):
        blocked = _request_block_reason(current, robots)
        if blocked is not None:
            return _SendResult(None, blocked, None, None)
        result = _send(session, current, timeout=timeout, min_interval=min_interval)
        response = result.response
        if response is None or result.rate_limited_text or result.error:
            return result
        if response.status_code not in _REDIRECT_STATUSES:
            return result
        location = response.headers.get("Location")
        if not isinstance(location, str) or not location.strip():
            return _SendResult(None, f"redirect_blocked: {current}", None, None)
        current = urljoin(current, location.strip())
    return _SendResult(None, f"redirect_blocked: {current}", None, None)


def _send(
    session: requests.Session,
    url: str,
    *,
    timeout: int,
    min_interval: float,
) -> _SendResult:
    response: requests.Response | None = None
    for attempt in range(REDDIT_MAX_ATTEMPTS):
        _wait_for_slot(min_interval)
        try:
            response = session.get(
                url,
                timeout=timeout,
                allow_redirects=False,
                verify=True,
                headers={"User-Agent": REDDIT_USER_AGENT, "Accept": REDDIT_ACCEPT},
            )
        except requests.RequestException as exc:
            _mark_request()
            return _SendResult(None, str(exc), None, None)
        _mark_request()
        if response.status_code != 429 or attempt >= REDDIT_MAX_ATTEMPTS - 1:
            break
        delay = _retry_after_seconds(response.headers.get("Retry-After"))
        if delay is None or delay < 0 or delay > REDDIT_INLINE_RETRY_SECONDS:
            break
        time.sleep(delay)
    if response is None:
        return _SendResult(None, "Request failed: no response", None, None)
    if response.status_code != 429:
        return _SendResult(response, None, None, None)
    delay = _retry_after_seconds(response.headers.get("Retry-After"))
    retry_at = None
    if delay is not None and delay > REDDIT_INLINE_RETRY_SECONDS:
        retry_at = datetime.now(UTC) + timedelta(seconds=delay)
    return _SendResult(response, None, retry_at, _transient_http_error(response))


def _request_block_reason(url: str, robots: RobotFileParser | None) -> str | None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or host not in _PUBLIC_HOSTS:
        return f"redirect_blocked: {url}"
    if parsed.path.rstrip("/") == "/robots.txt":
        return None
    if robots is None or not robots.can_fetch(REDDIT_USER_AGENT, url):
        return f"robots_disallowed: {url}"
    return None


def _robots_failure(result: _SendResult) -> str | None:
    if result.rate_limited_text:
        return None
    if result.error:
        return f"robots_unavailable: {result.error}"
    response = result.response
    if response is None:
        return "robots_unavailable: no response"
    if response.status_code != 200:
        return f"robots_unavailable: HTTP {response.status_code}"
    return None


def _parse_robots(body: str) -> RobotFileParser | None:
    if "user-agent" not in body.lower():
        return None
    parser = RobotFileParser()
    parser.parse(body.splitlines())
    return parser


def _response_text(response: requests.Response) -> str:
    content = response.content if isinstance(response.content, bytes) else b""
    encoding = response.encoding or "utf-8"
    return content.decode(encoding, errors="replace")


def _transient_http_error(response: requests.Response) -> str:
    reason = response.reason or "Error"
    if isinstance(reason, bytes):
        reason = reason.decode("ascii", errors="replace")
    kind = "Client" if response.status_code < 500 else "Server"
    target = response.url or ""
    return f"{response.status_code} {kind} Error: {reason} for url: {target}"


def _retry_after_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if re.fullmatch(r"\d+", stripped):
        return float(stripped)
    try:
        parsed = parsedate_to_datetime(stripped)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return (parsed - datetime.now(UTC)).total_seconds()


def _wait_for_slot(min_interval: float) -> None:
    global _last_reddit_request_at
    if not _last_reddit_request_at or min_interval <= 0:
        return
    delay = min_interval - (time.monotonic() - _last_reddit_request_at)
    if delay > 0:
        time.sleep(delay)


def _mark_request() -> None:
    global _last_reddit_request_at
    _last_reddit_request_at = time.monotonic()


def _articles_from_feed(
    body: bytes | str,
    sources: Sequence[Source],
    *,
    category: str,
    limit: int,
) -> tuple[list[Article], list[str], bool]:
    payload = body if isinstance(body, bytes) else body.encode("utf-8")
    if not payload.strip() or not _looks_like_feed(payload):
        message = "Feed was not RSS/Atom"
        return [], [_source_error(source.name, message) for source in sources], False
    parsed: Any = feedparser.parse(payload)
    entries = parsed.entries if isinstance(getattr(parsed, "entries", None), list) else []
    if not entries:
        message = "Feed contained no entries"
        return [], [_source_error(source.name, message) for source in sources], False

    by_name: dict[str, Source] = {}
    for source in sources:
        subreddit_name = _subreddit_name(source.url)
        if subreddit_name is not None:
            by_name[subreddit_name.lower()] = source
    grouped: dict[str, list[Mapping[str, Any]]] = {name: [] for name in by_name}
    unmatched: list[Mapping[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        subreddit = _entry_subreddit(entry)
        if subreddit is not None and subreddit in grouped:
            grouped[subreddit].append(entry)
        else:
            unmatched.append(entry)
    if len(sources) == 1 and unmatched:
        only_name = next(iter(grouped))
        grouped[only_name].extend(unmatched)
        unmatched = []
    if len(sources) > 1 and not any(grouped.values()):
        message = "Feed entries could not be attributed to a subreddit"
        return [], [_source_error(source.name, message) for source in sources], False

    articles: list[Article] = []
    for name, source in by_name.items():
        articles.extend(
            _articles_for_source(grouped.get(name, []), source, category=category, limit=limit)
        )
    if not articles:
        message = "Feed contained no usable entries"
        return [], [_source_error(source.name, message) for source in sources], False
    return articles, [], True


def _articles_for_source(
    entries: Sequence[Mapping[str, Any]],
    source: Source,
    *,
    category: str,
    limit: int,
) -> list[Article]:
    articles: list[Article] = []
    for entry in entries:
        if len(articles) >= limit:
            break
        title = html.unescape(_entry_text(entry, "title")) or "(no title)"
        link = _entry_link(entry)
        if not title or title == "(no title)" or not link:
            continue
        summary = html.unescape(_entry_text(entry, "summary") or _entry_text(entry, "description"))
        articles.append(
            Article(
                title=title,
                link=link,
                summary=summary or title,
                published=_published(entry),
                source=source.name,
                category=category,
            )
        )
    return articles


def _entry_subreddit(entry: Mapping[str, Any]) -> str | None:
    for key in ("link", "id"):
        value = entry.get(key)
        if isinstance(value, str):
            match = _SUBREDDIT_NAME.search(value)
            if match:
                return match.group(1).lower()
    tags = entry.get("tags")
    if not isinstance(tags, list):
        return None
    for tag in tags:
        if not isinstance(tag, Mapping):
            continue
        raw = tag.get("term") or tag.get("label") or ""
        if not isinstance(raw, str):
            continue
        cleaned = raw.strip()
        if cleaned.lower().startswith("r/"):
            cleaned = cleaned[2:]
        if re.fullmatch(r"[A-Za-z0-9_]{2,21}", cleaned):
            return cleaned.lower()
    return None


def _entry_link(entry: Mapping[str, Any]) -> str:
    link = entry.get("link")
    if isinstance(link, str) and link.strip():
        return link.strip()
    links = entry.get("links")
    if not isinstance(links, list):
        return ""
    for item in links:
        if not isinstance(item, Mapping):
            continue
        href = item.get("href")
        rel = item.get("rel")
        if isinstance(href, str) and href.strip() and rel in (None, "alternate"):
            return href.strip()
    return ""


def _entry_text(entry: Mapping[str, Any], key: str) -> str:
    value = entry.get(key)
    return value.strip() if isinstance(value, str) else ""


def _published(entry: Mapping[str, Any]) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if isinstance(parsed, time.struct_time):
            return datetime.fromtimestamp(calendar.timegm(parsed), tz=UTC)
    return None


def _looks_like_feed(content: bytes) -> bool:
    head = content.lstrip()[:800].lower()
    return b"<rss" in head or b"<feed" in head or b"<rdf" in head


def _source_error(source_name: str, message: str) -> str:
    return str(SourceError(source_name, message))
