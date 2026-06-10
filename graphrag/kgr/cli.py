"""kgr command-line entrypoint."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .ingest import ingest_feed, ingest_path, ingest_url
from .ontology import backfill_labels, compound_edge_labels
from .schema import apply_all, apply_graph


def _cmd_init(_args: argparse.Namespace) -> None:
    summary = apply_all()
    print(json.dumps({
        "status": "ok",
        "applied": ["kgr.documents", "kgr.ontology", "kgr.nodes", "kgr.edges", "kgr.kg"],
        **summary,
    }))


def _cmd_ingest(args: argparse.Namespace) -> None:
    p = Path(args.path)
    if p.is_dir():
        files = sorted(f for f in p.rglob("*") if f.is_file())
    else:
        files = [p]
    for f in files:
        for r in ingest_path(f):
            print(json.dumps(r))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kgr",
        description="Knowledge graph ingest into Kinetica",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "────────────────────────────────────────────────────────────\n"
            "common:\n"
            "  kgr init                  set up schema + property graph\n"
            "  kgr ingest <path>         ingest a file or directory\n"
            "  kgr ask \"<question>\"       ask the graph in English (Cypher + answer)\n"
            "  kgr chat                  interactive Q&A REPL over the graph\n"
            "  kgr watch-feeds [--interval N] [--once]   poll threat feeds, ingest new (daemon)\n"
            "  kgr interrupt             stop the running watch-feeds job\n"
            "  kgr clear --yes           wipe graph + tables, start over\n"
            "\n"
            "env: KGR_COMPOUND_EDGES=on (unique <src>_<base>_<dst> edge labels; "
            "default off = bare base) · KGR_LLM=stub · KGR_RUNTIME_DIR\n"
            "full command + env reference: README.md"
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="Create schema + property graph (idempotent)")
    p_init.set_defaults(func=_cmd_init)

    p_ingest = sub.add_parser("ingest", help="Extract entities/relations from a file or directory")
    p_ingest.add_argument("path", help="Path to file or directory")
    p_ingest.set_defaults(func=_cmd_ingest)

    p_url = sub.add_parser("ingest-url", help="Fetch a web article and ingest it")
    p_url.add_argument("url", help="URL of the article")
    p_url.set_defaults(func=_cmd_ingest_url)

    p_feed = sub.add_parser("ingest-feed", help="Iterate an RSS/Atom feed and ingest each entry")
    p_feed.add_argument("feed_url", help="URL of the RSS/Atom feed")
    p_feed.add_argument("--limit", type=int, default=None, help="Process at most N entries (newest)")
    p_feed.set_defaults(func=_cmd_ingest_feed)

    p_back = sub.add_parser("backfill-labels", help="Fold existing kgr.nodes/edges LABELs to canonical form")
    p_back.set_defaults(func=_cmd_backfill)

    p_rec = sub.add_parser("recompose-edges", help="Rewrite kgr.edges LABELs to compound <srcLabel>_<baseLabel>_<dstLabel> form (or back to base with --base)")
    p_rec.add_argument("--base", action="store_true", help="Inverse: rewrite compound LABELs back to the bare base relation (declutters the schema graph)")
    p_rec.set_defaults(func=_cmd_recompose)

    p_watch = sub.add_parser("watch-feeds", help="Poll a list of RSS/Atom feeds on an interval and ingest new entries (daemon)")
    p_watch.add_argument("--feeds", default=None, help="Path to a file of feed URLs (one per line). Default: bundled threat/security feeds")
    p_watch.add_argument("--interval", type=int, default=900, help="Seconds between poll cycles (default 900)")
    p_watch.add_argument("--limit", type=int, default=None, help="Per-feed cap on entries inspected per cycle (newest)")
    p_watch.add_argument("--once", action="store_true", help="Run a single poll cycle and exit (for cron/testing)")
    p_watch.set_defaults(func=_cmd_watch)

    p_intr = sub.add_parser("interrupt", help="Stop a running watch-feeds daemon/sweep (SIGTERM, then SIGKILL)")
    p_intr.set_defaults(func=_cmd_interrupt)

    p_clr = sub.add_parser("clear", help="Interrupt any running job, then drop the graph + kgr tables (start over)")
    p_clr.add_argument("--yes", action="store_true", help="Perform the destructive wipe; without it, prints a dry run")
    p_clr.add_argument("--no-reinit", action="store_true", help="Leave the schema dropped instead of recreating an empty one")
    p_clr.add_argument("--keep-corpus", action="store_true", help="Do not delete corpus.txt")
    p_clr.set_defaults(func=_cmd_clear)

    p_ask = sub.add_parser("ask", help="Ask a natural-language question; kgr generates Cypher, runs it, and answers")
    p_ask.add_argument("question", help="The question, e.g. \"What threats involve Microsoft?\"")
    p_ask.add_argument("--show-cypher", action="store_true", help="Also print the generated Cypher and result rows")
    p_ask.add_argument("--json", action="store_true", help="Emit the full result as one JSON object")
    p_ask.set_defaults(func=_cmd_ask)

    p_chat = sub.add_parser("chat", help="Interactive Q&A REPL over the graph (reuses the ask pipeline)")
    p_chat.add_argument("--show-cypher", action="store_true", help="Print the generated Cypher each turn")
    p_chat.set_defaults(func=_cmd_chat)

    args = parser.parse_args(argv)
    args.func(args)
    return 0


def _cmd_ingest_url(args: argparse.Namespace) -> None:
    for r in ingest_url(args.url):
        print(json.dumps(r))


def _cmd_ingest_feed(args: argparse.Namespace) -> None:
    for r in ingest_feed(args.feed_url, limit=args.limit):
        print(json.dumps(r))


def _cmd_backfill(_args: argparse.Namespace) -> None:
    result = backfill_labels()
    apply_graph()  # CREATE OR REPLACE so the live graph picks up the new labels
    print(json.dumps(result))


def _cmd_recompose(args: argparse.Namespace) -> None:
    if args.base:
        from .ontology import base_edge_labels
        n = base_edge_labels()
        apply_graph()
        print(json.dumps({"based_edges": n}))
        return
    n = compound_edge_labels()
    apply_graph()
    print(json.dumps({"recomposed_edges": n}))


def _cmd_watch(args: argparse.Namespace) -> None:
    import signal

    from .watch import clear_pidfile, load_feed_list, watch_feeds, write_pidfile

    feeds = load_feed_list(args.feeds)
    if not feeds:
        print(json.dumps({"status": "no_feeds", "source": args.feeds or "bundled"}))
        return

    # Translate SIGTERM (what `kgr interrupt` sends) into KeyboardInterrupt so the
    # finally-block below runs and the pidfile is cleaned up on a graceful stop.
    def _term(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, _term)

    write_pidfile()
    print(json.dumps({"event": "watch_start", "feeds": len(feeds),
                      "interval": args.interval, "once": args.once}), flush=True)
    try:
        watch_feeds(feeds, interval=args.interval, limit=args.limit, once=args.once)
    except KeyboardInterrupt:
        print(json.dumps({"event": "stopped"}))
    finally:
        clear_pidfile()


def _cmd_interrupt(_args: argparse.Namespace) -> None:
    from .watch import interrupt
    print(json.dumps(interrupt()))


def _cmd_ask(args: argparse.Namespace) -> None:
    from .qa import answer

    res = answer(args.question, show_cypher=args.show_cypher)
    if args.json:
        print(json.dumps(res, default=str))
        return
    if args.show_cypher:
        print(f"\033[2mcypher:\033[0m {res['cypher']}")
        print(f"\033[2mrows:\033[0m {res['rows']}\n")
    print(res["answer"])


def _cmd_chat(args: argparse.Namespace) -> None:
    from .qa import answer

    print('kgr chat — ask about the graph. Ctrl-D or "exit" to quit.')
    history: list[str] = []
    while True:
        try:
            q = input("\n\033[1m? \033[0m").strip()
        except EOFError:
            print()
            break
        if not q:
            continue
        if q.lower() in {"exit", "quit", ":q"}:
            break
        res = answer(q, history="\n".join(history[-6:]), show_cypher=args.show_cypher)
        if args.show_cypher:
            print(f"\033[2m{res['cypher']}\033[0m  (\033[2m{res['rows']} rows\033[0m)")
        print(res["answer"])
        history.append(f"Q: {q}\nCypher: {res['cypher']}")


def _cmd_clear(args: argparse.Namespace) -> None:
    import os

    from .ingest import _CORPUS_DEFAULT
    from .schema import apply_all, drop_all
    from .watch import interrupt

    intr = interrupt()  # clear implicitly stops any running job first
    targets = ["kgr.kg (graph)", "kgr.edges", "kgr.nodes", "kgr.documents", "kgr.ontology"]
    if not args.keep_corpus:
        targets.append("corpus.txt")

    if not args.yes:
        print(json.dumps({"status": "dry_run", "interrupt": intr, "would_drop": targets,
                          "reinit": not args.no_reinit,
                          "hint": "re-run with --yes to perform the wipe"}))
        return

    dropped = drop_all()
    corpus_removed = False
    if not args.keep_corpus:
        path = Path(os.environ.get("KGR_CORPUS_PATH") or _CORPUS_DEFAULT)
        try:
            path.unlink()
            corpus_removed = True
        except FileNotFoundError:
            pass

    reinit = apply_all() if not args.no_reinit else None
    print(json.dumps({"status": "cleared", "interrupt": intr,
                      "dropped": dropped["dropped"], "drop_errors": dropped["errors"],
                      "corpus_removed": corpus_removed, "reinit": reinit}))


if __name__ == "__main__":
    sys.exit(main())
