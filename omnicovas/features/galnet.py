"""Opt-in public RSS reader. No commander data, scraping or general URL fetcher.

Frontier's published GalNet RSS endpoint supplies the article text for readers.
Keep only a short plain-text feed excerpt and link; copyright remains Frontier's.
The generic SourceQueue has no production dispatcher: this one fixed flow owns
its bounded single-flight request, using the existing source plan/cache contracts.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import httpx

from omnicovas.core.activity_log import ActivityEntry, ActivityLog
from omnicovas.core.provenance import FreshnessLabel
from omnicovas.core.source_cache import CacheKey, SourceCache
from omnicovas.core.source_plan import ExternalRequestBundle
from omnicovas.core.source_registry import (
    SourceCapability,
    SourceDefinition,
    SourceRegistry,
    SourceState,
)
from omnicovas.core.source_router import SourceRouter

FEED_URL = "https://www.elitedangerous.com/news/galnet/feed.xml"
ARTICLE_PREFIX = "https://www.elitedangerous.com/news/galnet/"
SOURCE_ID = "frontier_galnet_rss"
TTL_SECONDS = 900
MAX_BYTES = 524288
MAX_ITEMS = 16
CACHE_KEY = CacheKey(SOURCE_ID, "galnet_news", None)


def article_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return (
        value
        if re.fullmatch(re.escape(ARTICLE_PREFIX) + r"[a-z0-9-]{1,220}", value)
        else None
    )


class _PlainText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in {"script", "style"}:
            self.skip += 1
        self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.skip = max(0, self.skip - 1)
        self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)


def plain_text(value: str) -> str:
    parser = _PlainText()
    parser.feed(unescape(value))
    return " ".join("".join(parser.parts).split())


def _time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def normalize_feed(data: bytes) -> list[dict[str, str]]:
    if b"\x00" in data:
        raise ValueError("Only the publisher's UTF-8 XML is supported")
    if len(data) > MAX_BYTES or re.search(rb"<!\s*(DOCTYPE|ENTITY)\b", data, re.I):
        raise ValueError("RSS size or document declaration rejected")
    root = ElementTree.fromstring(data)
    if root.tag != "rss" or root.find("channel") is None:
        raise ValueError("Not a published RSS channel")
    items: dict[str, dict[str, str]] = {}
    nodes = root.findall("channel/item")
    for node in nodes[:128]:
        url = article_url((node.findtext("link") or "").strip())
        title = plain_text(node.findtext("title") or "")[:240]
        try:
            date = parsedate_to_datetime(node.findtext("pubDate") or "")
        except (TypeError, ValueError, OverflowError):
            continue
        if not url or not title or date.tzinfo is None:
            continue
        # GalNet publication dates use the fictional galactic calendar (e.g.
        # 3312). Preserve them; do not misread them as real fetch times or age.
        published = date.date().isoformat()
        body = plain_text(node.findtext("description") or "")
        excerpt = " ".join(body.split()[:60])[:420].rstrip()
        if len(excerpt) < len(body):
            excerpt = excerpt.rsplit(" ", 1)[0] + "…"
        # Canonical article URL is the stable deduplication identity. No claim
        # that a publisher GUID is a commander/event identifier.
        record = {
            "id": hashlib.sha256(url.encode()).hexdigest()[:24],
            "title": title,
            "published_date": published,
            "excerpt": excerpt,
            "url": url,
        }
        previous = items.get(url)
        if previous is None or published > previous["published_date"]:
            items[url] = record
    if nodes and not items:
        raise ValueError("No valid articles in RSS response")
    return sorted(items.values(), key=lambda x: x["published_date"], reverse=True)[
        :MAX_ITEMS
    ]


async def download_feed(bundle: ExternalRequestBundle) -> bytes:
    if not bundle.plan.primary_source_id == SOURCE_ID or bundle.request_payload != {
        "url": FEED_URL
    }:
        raise ValueError("Only the planned public GalNet feed is permitted")
    # No cookies, authorization, commander state, query or environment proxy.
    # Redirects are not followed: a changed publisher location needs review.
    async with httpx.AsyncClient(
        timeout=12, follow_redirects=False, trust_env=False
    ) as client:
        async with client.stream(
            "GET",
            FEED_URL,
            headers={
                "User-Agent": "OmniCOVAS-GalNet/1.0",
                "Accept": "application/rss+xml, application/xml",
                "Accept-Encoding": "identity",
            },
        ) as response:
            response.raise_for_status()
            if response.headers.get("content-encoding", "identity") != "identity":
                raise ValueError("Unexpected feed encoding")
            if response.is_redirect:
                raise ValueError("Feed redirect needs verification")
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > MAX_BYTES:
                    raise ValueError("Feed too large")
            return bytes(content)


class GalnetReader:
    def __init__(
        self,
        *,
        cache_path: Path,
        enabled: Callable[[], bool],
        registry: SourceRegistry,
        activity_log: ActivityLog | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.path, self.enabled, self.registry = cache_path, enabled, registry
        self.log, self.clock = activity_log, clock
        self.cache = SourceCache()
        self.next_attempt: datetime | None = None
        self.last_error: str | None = None
        self.task: asyncio.Task[None] | None = None
        self._load()
        self._source()

    def _source(self) -> None:
        self.registry.register(
            SourceDefinition(
                source_id=SOURCE_ID,
                display_name="Frontier GalNet RSS",
                description=(
                    "Public GalNet headlines and short feed excerpts; "
                    "no commander data."
                ),
                capabilities=frozenset({SourceCapability.GALNET_NEWS}),
                state=SourceState.ENABLED
                if self.enabled()
                else SourceState.REQUIRES_CONSENT,
                is_local=False,
                requires_auth=False,
                requires_consent=True,
            )
        )

    def _load(self) -> None:
        try:
            if self.path.stat().st_size > MAX_BYTES:
                return
            data = json.loads(self.path.read_text(encoding="utf-8"))
            fetched = _time(data.get("fetched_at"))
            records = data.get("items")
            self.next_attempt = _time(data.get("next_update_at"))
            if (
                self.next_attempt
                and not self.clock()
                <= self.next_attempt
                <= self.clock() + timedelta(days=365)
            ):
                self.next_attempt = None
            if (
                data.get("version") != 1
                or fetched is None
                or fetched > self.clock()
                or not isinstance(records, list)
                or len(records) > MAX_ITEMS
            ):
                return
            valid = []
            for item in records:
                if not isinstance(item, dict) or not article_url(item.get("url")):
                    return
                if any(
                    not isinstance(item.get(k), str)
                    for k in ("id", "title", "excerpt", "published_date")
                ):
                    return
                datetime.fromisoformat(item["published_date"])
                if (
                    len(item["title"]) > 240
                    or len(item["excerpt"]) > 421
                    or len(item["id"]) > 64
                ):
                    return
                valid.append(item)
            self.cache.set(CACHE_KEY, {"items": valid}, FreshnessLabel.STALE, fetched)
        except (OSError, ValueError, TypeError, AttributeError):
            return

    def _save(self) -> bool:
        entry = self.cache.get(CACHE_KEY)
        data = {
            "version": 1,
            "fetched_at": entry.fetched_at.isoformat() if entry else None,
            "next_update_at": self.next_attempt.isoformat()
            if self.next_attempt
            else None,
            "items": entry.data["items"] if entry else [],
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self.path)
            return True
        except OSError:
            return False

    def snapshot(self) -> dict[str, Any]:
        self._source()
        entry = self.cache.get(CACHE_KEY)
        age = (self.clock() - entry.fetched_at).total_seconds() if entry else None
        fresh = age is not None and 0 <= age < TTL_SECONDS and not self.last_error
        running = self.task is not None and not self.task.done()
        return {
            "source_id": SOURCE_ID,
            "source_name": "Frontier GalNet RSS",
            "attribution": "GalNet © Frontier Developments",
            "enabled": self.enabled(),
            "updating": running,
            "state": "fresh" if fresh else "cached" if entry else "not_loaded",
            "items": entry.data["items"] if entry else [],
            "fetched_at": entry.fetched_at.isoformat() if entry else None,
            "next_update_at": self.next_attempt.isoformat()
            if self.next_attempt
            else None,
            "error": self.last_error,
            "can_update": self.enabled()
            and not running
            and (self.next_attempt is None or self.clock() >= self.next_attempt),
            "publication_calendar": (
                "GalNet dates as published; update times use your local clock."
            ),
        }

    def start_update(self) -> asyncio.Task[None] | None:
        if not self.snapshot()["can_update"]:
            return self.task
        self.task = asyncio.create_task(self._update())
        return self.task

    async def _update(self) -> None:
        self.next_attempt = self.clock() + timedelta(seconds=TTL_SECONDS)
        # Persist the budget before sending, including across restart/failure.
        if not self._save():
            self.last_error = "cache_unavailable"
            return
        self._source()
        plan = SourceRouter(self.registry).resolve(
            "galnet_news", workflow_id="galnet-public-feed"
        )
        if not plan.is_supported or not self.enabled():
            return
        from omnicovas.api.source import register_plan

        register_plan(plan.plan)
        bundle = ExternalRequestBundle.make(plan.plan, {"url": FEED_URL})
        try:
            records = normalize_feed(await asyncio.wait_for(download_feed(bundle), 15))
            if not self.enabled():
                return
            self.cache.set(
                CACHE_KEY, {"items": records}, FreshnessLabel.FRESH, self.clock()
            )
            self.next_attempt = self.clock() + timedelta(seconds=TTL_SECONDS)
            self.last_error = None
            if not self._save():
                self.last_error = "cache_unavailable"
            kind = "GALNET_UPDATE_SUCCEEDED"
        except httpx.HTTPStatusError as error:
            self.last_error = "update_failed"
            retry = error.response.headers.get("retry-after", "")
            try:
                until = self.clock() + timedelta(seconds=max(TTL_SECONDS, int(retry)))
            except (ValueError, OverflowError):
                try:
                    until = parsedate_to_datetime(retry)
                except (ValueError, TypeError, OverflowError):
                    until = None
            if (
                until
                and until.tzinfo
                and self.next_attempt
                and until > self.next_attempt
            ):
                self.next_attempt = until
                self._save()
            kind = "GALNET_UPDATE_FAILED"
        except (
            httpx.HTTPError,
            ValueError,
            ElementTree.ParseError,
            OSError,
            TimeoutError,
        ):
            self.last_error = "update_failed"
            kind = "GALNET_UPDATE_FAILED"
        if self.log:
            self.log.append(
                ActivityEntry(
                    event_type=kind,
                    timestamp=self.clock().isoformat(),
                    summary="Public GalNet feed update; no commander data sent.",
                )
            )
