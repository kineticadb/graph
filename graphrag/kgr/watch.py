"""Polling daemon: periodically walk configured feeds and ingest new entries.

`kgr ingest-feed` is a one-shot walk. This is the dynamic counterpart: keep
polling a list of feeds on an interval and ingest entries as they appear.

No separate state file is needed — `kgr.documents` already stores a content
sha256 per doc_uri, so a re-seen article returns `{"status": "unchanged"}` and
is never re-extracted. On top of that durable layer we keep an in-memory set of
entry URLs already handled *this run*, so a still-present feed entry isn't even
re-fetched over HTTP on the next cycle.
"""
from __future__ import annotations

import errno
import json
import os
import signal
import time
from pathlib import Path
from typing import Optional

from .ingest import ingest_url
from .sources import feed as feed_src

_DEFAULT_FEEDS = Path(__file__).resolve().parent / "sources" / "security_feeds.txt"
_DEFAULT_INTERVAL = 900  # 15 minutes
# Statuses ingest_url returns when an entry is definitively handled (nothing
# more to do for it) vs. transient failures we want to retry next cycle.
_TERMINAL = {"unchanged", "no_text_extracted"}


def load_feed_list(path: str | Path | None = None) -> list[str]:
    """Read feed URLs from `path` (one per line; '#' comments + blanks skipped).

    Defaults to the bundled `sources/security_feeds.txt`.
    """
    p = Path(path) if path else _DEFAULT_FEEDS
    feeds: list[str] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            feeds.append(s)
    return feeds


def _emit(rec: dict) -> None:
    print(json.dumps(rec), flush=True)


# --- process tracking / interrupt -------------------------------------------
# The daemon records its PID so `kgr interrupt` (and `kgr clear`) can stop it.
# A /proc scan is the fallback so a job started without a live pidfile is still
# catchable.

def _pidfile() -> Path:
    return Path(os.environ.get("KGR_RUNTIME_DIR") or (Path.home() / ".kgr")) / "watch.pid"


def write_pidfile() -> None:
    p = _pidfile()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(os.getpid()))


def clear_pidfile() -> None:
    try:
        _pidfile().unlink()
    except FileNotFoundError:
        pass


def _read_pid() -> Optional[int]:
    try:
        return int(_pidfile().read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError as e:
        return e.errno == errno.EPERM  # exists but not ours
    return True


def _argv(pid: int) -> list[str]:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return []
    return [p.decode("utf-8", "replace") for p in raw.split(b"\x00") if p]


def _is_watch_proc(pid: int) -> bool:
    # Match on exact argv *tokens*, not a substring of the joined command line:
    # 'watch-feeds' must be its own argument (rules out `bash -c '...kgr
    # watch-feeds...'` wrappers and `pgrep` patterns that merely mention it),
    # and some token must be the kgr entrypoint.
    argv = _argv(pid)
    return "watch-feeds" in argv and any(Path(a).name == "kgr" for a in argv)


def _scan_watch_pids() -> set[int]:
    me = os.getpid()
    proc = Path("/proc")
    if not proc.is_dir():
        return set()
    found: set[int] = set()
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid != me and _is_watch_proc(pid):
            found.add(pid)
    return found


def interrupt(*, timeout: float = 10.0) -> dict:
    """Stop any running watch-feeds job: SIGTERM, then SIGKILL if it lingers."""
    pids: set[int] = set()
    pid = _read_pid()
    if pid is not None and _alive(pid) and _is_watch_proc(pid):
        pids.add(pid)
    pids |= _scan_watch_pids()
    if not pids:
        clear_pidfile()
        return {"status": "no_running_job"}

    for p in list(pids):
        try:
            os.kill(p, signal.SIGTERM)
        except ProcessLookupError:
            pids.discard(p)

    waited = 0.0
    while waited < timeout and any(_alive(p) for p in pids):
        time.sleep(0.25)
        waited += 0.25

    sigkilled: list[int] = []
    for p in pids:
        if _alive(p):
            try:
                os.kill(p, signal.SIGKILL)
                sigkilled.append(p)
            except ProcessLookupError:
                pass
    clear_pidfile()
    return {"status": "interrupted", "pids": sorted(pids), "sigkilled": sorted(sigkilled)}


def watch_feeds(
    feeds: list[str],
    *,
    interval: int = _DEFAULT_INTERVAL,
    limit: Optional[int] = None,
    once: bool = False,
) -> None:
    """Poll `feeds` forever (or one cycle if `once`), ingesting new entries.

    Emits one JSON line per event (ingested / *_error / cycle_done) to stdout.
    Raises KeyboardInterrupt up to the caller for clean Ctrl-C shutdown.
    """
    seen: set[str] = set()
    cycle = 0
    while True:
        cycle += 1
        new_total = 0
        for feed_url in feeds:
            try:
                entries = list(feed_src.iter_entries(feed_url, limit=limit))
            except Exception as e:
                _emit({"event": "feed_error", "feed": feed_url, "error": str(e)[:200]})
                continue
            for entry in entries:
                if entry.url in seen:
                    continue
                try:
                    results = ingest_url(entry.url)
                except Exception as e:
                    # Not marked seen — retried on the next cycle.
                    _emit({"event": "ingest_error", "feed": feed_url,
                           "uri": entry.url, "error": str(e)[:200]})
                    continue
                seen.add(entry.url)
                status = results[0].get("status") if results else None
                if status in _TERMINAL:
                    continue
                new_total += 1
                _emit({
                    "event": "ingested",
                    "feed": feed_url,
                    "uri": entry.url,
                    "title": entry.title,
                    "paragraphs": sum(1 for r in results if "paragraph" in r),
                    "nodes": sum(r.get("nodes", 0) for r in results),
                    "edges": sum(r.get("edges", 0) for r in results),
                })
        _emit({"event": "cycle_done", "cycle": cycle,
               "feeds": len(feeds), "new_articles": new_total, "seen_urls": len(seen)})
        if once:
            return
        time.sleep(interval)
