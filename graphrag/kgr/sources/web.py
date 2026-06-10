"""Fetch a web page and extract its main article body."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import requests
import trafilatura

_DEFAULT_UA = "kgr/0.1 (+https://github.com/kineticadb)  python-requests"
_DEFAULT_TIMEOUT = 30


@dataclass
class Article:
    url: str
    title: str
    text: str

    @property
    def empty(self) -> bool:
        return not self.text.strip()

    def as_document(self) -> str:
        """Render to a plain-text doc with title as the first paragraph."""
        head = self.title.strip()
        body = self.text.strip()
        return f"{head}\n\n{body}" if head and body else body or head


def fetch(url: str, *, timeout: Optional[int] = None) -> Article:
    """GET the URL and pull article body + title via trafilatura.

    Network errors raise. If trafilatura can't find article content (e.g. paywall
    page, JS-heavy site), the Article is returned with an empty text body — the
    caller decides whether to ingest the title alone or skip.
    """
    timeout = timeout or int(os.environ.get("KGR_WEB_TIMEOUT", str(_DEFAULT_TIMEOUT)))
    headers = {"User-Agent": os.environ.get("KGR_USER_AGENT", _DEFAULT_UA)}
    resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    html = resp.text
    text = trafilatura.extract(html, include_comments=False, include_tables=False) or ""
    meta = trafilatura.extract_metadata(html)
    title = (meta.title if meta and meta.title else "").strip()
    return Article(url=resp.url, title=title, text=text.strip())
