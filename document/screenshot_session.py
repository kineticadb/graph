#!/usr/bin/env python3
"""Drive the KineticaGraphExplorer headlessly to screenshot live query results.

For each query in the session JSON, this script:
  1. starts a local http.server in the explorer directory
  2. launches Chrome via Playwright (uses the system /usr/bin/google-chrome)
  3. turns Auto-run Queries ON, clicks Connect, loads the session file
  4. waits for the query result to render
  5. saves a full-page PNG to out/<graph>/query_<i>.explorer.png

Usage:
    python3 screenshot_session.py <session.json> [-o out/]
"""
from __future__ import annotations
import argparse
import contextlib
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

EXPLORER_DIR = Path("/home/kkaramete/gpudb-dev/gpudb-core-graph/graph/explorer")
EXPLORER_FILE = "KineticaGraphExplorer.html"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.contextmanager
def http_server(directory: Path, port: int):
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=str(directory),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Wait for port to accept connections
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    try:
        yield
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def run(session_path: Path, out_dir: Path) -> None:
    from playwright.sync_api import sync_playwright

    session = json.loads(session_path.read_text())
    graph_name = (session.get("graph") or {}).get("name") or "session"
    safe = graph_name.replace(".", "_").replace("/", "_")
    out = out_dir / safe
    out.mkdir(parents=True, exist_ok=True)

    port = free_port()
    url = f"http://127.0.0.1:{port}/{EXPLORER_FILE}"
    num_queries = len(session.get("queries") or [])
    print(f"Session graph: {graph_name}  ({num_queries} queries)")
    print(f"Serving {EXPLORER_DIR} on {url}")

    with http_server(EXPLORER_DIR, port), sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome",
            headless=True,
            args=["--no-sandbox"],
        )
        ctx = browser.new_context(viewport={"width": 1600, "height": 1100})
        page = ctx.new_page()
        page.set_default_timeout(60_000)
        page.on("console", lambda m: print(f"  [console.{m.type}] {m.text}"))
        page.on("pageerror", lambda e: print(f"  [pageerror] {e}"))
        page.on("requestfailed", lambda r: print(f"  [requestfailed] {r.url} — {r.failure}"))
        # Explorer pulls React/Babel/d3/etc. from CDNs and compiles JSX in-browser;
        # don't wait for full "load" — DOM-ready is enough, then we poll for UI.
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)

        # Babel-standalone compiles the JSX at runtime; give React a moment to mount.
        page.wait_for_selector("text=Connect & List Graphs", timeout=90_000)

        # Default profile = Localhost / admin / ***REMOVED*** — just click Connect.
        page.get_by_role("button", name="Connect & List Graphs").click()

        # Wait for the "Connected." status to appear — that's our signal that the
        # graphs list has been fetched. We don't wait on the specific graph row
        # because long lists scroll it out of view and text= matchers can be flaky.
        try:
            page.wait_for_selector("text=Connected.", timeout=60_000)
        except Exception:
            dbg = out / "debug_connect_failed.png"
            page.screenshot(path=str(dbg), full_page=True)
            print(f"  debug screenshot → {dbg}")
            raise

        # Poll for the graphs list to populate and include our target graph.
        # The list is fetched async after "Connected." status flips.
        deadline = time.time() + 30
        present = False
        graph_count = 0
        while time.time() < deadline:
            info = page.evaluate(
                """name => {
                    const hits = Array.from(document.querySelectorAll('div'))
                        .filter(d => d.children.length === 0)
                        .map(d => (d.textContent || '').trim())
                        .filter(t => (t.includes('.') && !t.includes(' ') && t.length < 120));
                    return { count: hits.length, present: hits.includes(name), sample: hits.slice(0,3) };
                }""",
                graph_name,
            )
            graph_count = info["count"]
            if info["present"]:
                present = True
                break
            time.sleep(0.5)
        print(f"  graphs loaded: {graph_count} (target present: {present})")
        if not present:
            dbg = out / "debug_graphs_missing.png"
            page.screenshot(path=str(dbg), full_page=True)
            print(f"  debug screenshot → {dbg}")
            raise RuntimeError(f"Graph '{graph_name}' not found after 30s")

        # Auto-run Queries defaults to ON (useState(true) in the Explorer source),
        # so no toggle needed — loaded sessions execute their queries automatically.

        # Feed the hidden file input inside the "Load Session" label.
        page.locator('input[type="file"][accept=".json"]').set_input_files(str(session_path))

        # Wait for the query panel(s) to render — each shows "Query N" label + an editor.
        page.wait_for_selector('textarea[placeholder^="Enter SQL query"]', timeout=30_000)

        # Wait for every query panel to finish: no Run button in "Running…" state.
        deadline = time.time() + 300
        while time.time() < deadline:
            running = page.locator('button:has-text("Running")').count()
            if running == 0:
                break
            time.sleep(1)
        else:
            print("  (timeout waiting for queries — screenshotting anyway)")

        # Let animations settle, then take the whole-UI screenshot.
        page.wait_for_timeout(1500)
        shot = out / "explorer_session.png"
        page.screenshot(path=str(shot), full_page=True)
        print(f"  session view → {shot}")

        # Per-query screenshots. Panels are draggable floating windows; React
        # renders them in query-order so DOM order matches. Later-rendered panels
        # paint on top (same zIndex). Process in REVERSE so the current target is
        # always the topmost panel and its `.last` locator wins over peers.
        # For each query we capture TWO screenshots: one of the View Results
        # table and one of the Visualization force-graph (when available).
        # Active tab background = rgb(108, 92, 231) = #6c5ce7.
        ACTIVE_BG = "108, 92, 231"
        for i in reversed(range(num_queries)):
            max_btn = page.locator('button[title="Maximize window"]').last
            if max_btn.count() == 0:
                print(f"  query {i}: no more panels to screenshot")
                break
            # 1. Maximize FIRST and let the DOM reflow to full window size.
            max_btn.click()
            page.wait_for_timeout(800)

            # 2. Results tab snapshot.
            results_btn = page.locator("button:has-text('View Results (')").last
            if results_btn.count() > 0:
                res_bg = results_btn.evaluate("el => getComputedStyle(el).backgroundColor")
                if ACTIVE_BG not in res_bg:
                    results_btn.click()
                    page.wait_for_timeout(600)
                shot_r = out / f"query_{i}.results.png"
                page.screenshot(path=str(shot_r), full_page=True)
                print(f"  query {i} (results) → {shot_r}")

            # 3. Visualization tab snapshot. Force a remount inside the
            # maximized container by toggling OFF→ON so the onEngineStop →
            # zoomToFit(400, 40) fits the graph to the full viewport.
            viz_btn = page.locator("button:has-text('Visualization (')").last
            if viz_btn.count() > 0:
                viz_bg = viz_btn.evaluate("el => getComputedStyle(el).backgroundColor")
                if ACTIVE_BG in viz_bg:
                    viz_btn.click()  # toggle OFF
                    page.wait_for_timeout(300)
                viz_btn.click()  # toggle ON at max size
                # Wait for the physics engine to settle. Larger graphs
                # (thousands of nodes) take 5-6s; smaller graphs faster.
                page.wait_for_timeout(6000)
                shot_g = out / f"query_{i}.graph.png"
                page.screenshot(path=str(shot_g), full_page=True)
                print(f"  query {i} (graph) → {shot_g}")

            # Close this panel so the one underneath becomes topmost.
            close_btn = page.locator('button:has-text("✕")').last
            if close_btn.count() > 0:
                close_btn.click()
                page.wait_for_timeout(300)

        browser.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("session", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=Path("out"))
    args = ap.parse_args()
    run(args.session, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
