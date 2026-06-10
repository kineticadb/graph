"""Iterate over an RSS/Atom feed and yield article URLs."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

import feedparser


@dataclass
class FeedEntry:
    url: str
    title: str
    published: Optional[str]   # ISO-ish date string from the feed if present


def iter_entries(feed_url: str, *, limit: Optional[int] = None) -> Iterable[FeedEntry]:
    """Parse `feed_url` and yield (url, title, published) per entry, oldest-first.

    Most feeds list newest-first; we reverse so a `--limit` consumes a contiguous
    historical window rather than just the latest N. Override with reverse=False
    if you want newest-first.
    """
    parsed = feedparser.parse(feed_url)
    entries = list(parsed.entries or [])
    entries.reverse()
    if limit is not None and limit > 0:
        entries = entries[-limit:]   # take the newest N after reversal
    for e in entries:
        url = getattr(e, "link", None)
        if not url:
            continue
        yield FeedEntry(
            url=url,
            title=getattr(e, "title", "") or "",
            published=getattr(e, "published", None),
        )
