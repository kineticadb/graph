#!/usr/bin/env python3
"""Generate `schemas/show_graph_grammar.html` — an interactive collapsible JSON-tree
view of the live response from `/show/graph/grammar`.

Run with the project venv so `gpudb` is available:
    .venv/bin/python generate_grammar_page.py
"""
from __future__ import annotations
import json
import os
from pathlib import Path

ROOT = Path(__file__).parent
OUT  = ROOT / "schemas" / "show_graph_grammar.html"


def load_env(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v)


def fetch_grammar() -> dict:
    """Live call to /show/graph/grammar; returns the parsed components_json dict."""
    load_env()
    from gpudb import GPUdb
    db = GPUdb(
        host=os.environ["KINETICA_DB_SKILL_URL"],
        username=os.environ["KINETICA_DB_SKILL_USER"],
        password=os.environ["KINETICA_DB_SKILL_PASS"],
    )
    r = db.show_graph_grammar()
    if r.get("status_info", {}).get("status") != "OK":
        raise RuntimeError(f"show_graph_grammar failed: {r}")
    return json.loads(r["components_json"])


PAGE_TMPL = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>/show/graph/grammar — Kinetica Graph API</title>
<link rel="icon" type="image/png" href="../favicon.png"/>
<style>
:root {
  --bg: #ffffff; --bg-alt: #f6f8fa; --text: #24292f; --muted: #57606a;
  --border: #d0d7de; --accent: #2563eb; --code-bg: #eff1f3;
  --string: #032f62; --number: #005cc5; --bool: #b31d28; --key: #6f42c1;
}
:root[data-theme="dark"] {
  --bg: #0d1117; --bg-alt: #161b22; --text: #c9d1d9; --muted: #8b949e;
  --border: #30363d; --accent: #58a6ff; --code-bg: #21262d;
  --string: #a5d6ff; --number: #79c0ff; --bool: #ff7b72; --key: #d2a8ff;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #0d1117; --bg-alt: #161b22; --text: #c9d1d9; --muted: #8b949e;
    --border: #30363d; --accent: #58a6ff; --code-bg: #21262d;
    --string: #a5d6ff; --number: #79c0ff; --bool: #ff7b72; --key: #d2a8ff;
  }
}
* { box-sizing: border-box; }
body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
       background: var(--bg); color: var(--text); line-height: 1.55; }
.wrap { max-width: 1200px; margin: 0 auto; padding: 32px 28px 80px; }
h1 { margin: 0 0 4px; font-size: 28px; }
.crumbs { color: var(--muted); font-size: 13px; margin-bottom: 20px; }
.crumbs a { color: var(--accent); text-decoration: none; }
.crumbs a:hover { text-decoration: underline; }
.endpoint { display: inline-block; background: var(--code-bg); color: var(--accent);
            padding: 2px 8px; border-radius: 4px;
            font-family: SFMono-Regular,Consolas,monospace; font-size: 13px; }
.short { color: var(--muted); margin: 4px 0 16px; }
.intro { background: var(--bg-alt); border: 1px solid var(--border); border-radius: 6px;
         padding: 12px 14px; margin: 0 0 20px; font-size: 14px; }
.toolbar { display: flex; gap: 8px; align-items: center; margin: 12px 0 18px;
           flex-wrap: wrap; }
.toolbar button { padding: 6px 12px; border: 1px solid var(--border);
                  background: var(--bg-alt); color: var(--text); border-radius: 6px;
                  cursor: pointer; font-size: 13px; }
.toolbar button:hover { border-color: var(--accent); color: var(--accent); }
.toolbar input[type=text] { padding: 6px 10px; border: 1px solid var(--border);
                            background: var(--bg-alt); color: var(--text);
                            border-radius: 6px; font-size: 13px; min-width: 220px; }
.tree { font-family: SFMono-Regular,Consolas,monospace; font-size: 13px;
        line-height: 1.6; padding: 16px 18px; background: var(--bg-alt);
        border: 1px solid var(--border); border-radius: 8px; overflow-x: auto; }
.tree ul { list-style: none; margin: 0; padding-left: 18px; border-left: 1px dashed transparent; }
.tree > ul { padding-left: 0; }
.tree li { position: relative; padding: 0; }
.toggle { display: inline-block; width: 14px; cursor: pointer; user-select: none;
          color: var(--muted); transition: transform 0.15s; }
.toggle.expanded { transform: rotate(90deg); }
.collapsed > ul { display: none; }
.collapsed .summary { color: var(--muted); }
.key { color: var(--key); }
.string { color: var(--string); }
.number { color: var(--number); }
.bool { color: var(--bool); }
.null { color: var(--muted); font-style: italic; }
.bracket { color: var(--text); }
.summary { color: var(--muted); font-style: italic; margin-left: 6px; }
.match { background: rgba(255, 200, 0, 0.25); border-radius: 2px; padding: 0 1px; }
.theme-btn { position: fixed; top: 16px; right: 16px; padding: 6px 12px;
             border: 1px solid var(--border); background: var(--bg-alt);
             color: var(--text); border-radius: 6px; cursor: pointer; font-size: 13px; }
</style>
</head>
<body>
<button id="themeBtn" class="theme-btn">☀ Light</button>
<div class="wrap">
  <div class="crumbs"><a href="../Kinetica_Graph_User_Guide.html">← Back to User Guide</a> · <a href="index.html">Schema Reference</a></div>
  <h1>Graph Grammar</h1>
  <div><span class="endpoint">/show/graph/grammar</span></div>
  <p class="short">Live response captured on <strong>__TIMESTAMP__</strong> from the local Kinetica instance. Lists every endpoint's components, valid identifier configurations, solve methods, and option specifications.</p>
  <div class="intro">
    The grammar is the source of truth for what column-to-grammar mappings are accepted. Each component (e.g. <code>NODES</code>) lists its allowed <code>identifiers</code>, then enumerates the <code>configurations</code> — concrete identifier combinations the engine will accept (e.g. <code>NODE_ID</code> alone, or <code>NODE_ID + NODE_X + NODE_Y</code>). For solve/match, the same record carries every solver/matcher's options and per-option <code>valid_choices</code>.
  </div>
  <div class="toolbar">
    <button id="expandAll">Expand all</button>
    <button id="collapseAll">Collapse all</button>
    <button id="expandTwo">Expand 2 levels</button>
    <input type="text" id="search" placeholder="Filter (e.g. SHORTEST_PATH, NODE_WKTPOINT)…"/>
    <span id="searchHits" style="color:var(--muted); font-size:12px;"></span>
    <a href="_grammar_pretty.json" style="margin-left:auto; color:var(--accent); font-size:13px;">Download raw JSON</a>
  </div>
  <div id="tree" class="tree"></div>
</div>
<script id="grammarData" type="application/json">__JSON__</script>
<script>
(function(){
  // ── Theme ──
  const saved = localStorage.getItem('schema-theme') || 'dark';
  document.documentElement.setAttribute('data-theme', saved);
  const themeBtn = document.getElementById('themeBtn');
  function updateBtn() {
    const t = document.documentElement.getAttribute('data-theme');
    themeBtn.textContent = t === 'dark' ? '☀ Light' : '☾ Dark';
  }
  updateBtn();
  themeBtn.addEventListener('click', () => {
    const t = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', t);
    localStorage.setItem('schema-theme', t);
    updateBtn();
  });

  // ── Tree builder ──
  const data = JSON.parse(document.getElementById('grammarData').textContent);
  const root = document.getElementById('tree');

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
  }

  function renderValue(val) {
    if (val === null) return '<span class="null">null</span>';
    if (typeof val === 'string') return '<span class="string">"' + escapeHtml(val) + '"</span>';
    if (typeof val === 'number') return '<span class="number">' + val + '</span>';
    if (typeof val === 'boolean') return '<span class="bool">' + val + '</span>';
    return '';
  }

  function isObject(v) { return v && typeof v === 'object' && !Array.isArray(v); }

  function summary(val) {
    if (Array.isArray(val)) return '[' + val.length + ' item' + (val.length === 1 ? '' : 's') + ']';
    if (isObject(val)) {
      const keys = Object.keys(val);
      return '{' + keys.length + ' key' + (keys.length === 1 ? '' : 's') + '}';
    }
    return '';
  }

  function build(key, val, depth, isLast) {
    const li = document.createElement('li');
    const isComplex = Array.isArray(val) || isObject(val);
    const keyHtml = key !== null
      ? (Array.isArray(key) ? key.join('') : '<span class="key">"' + escapeHtml(key) + '"</span>: ')
      : '';
    if (!isComplex) {
      li.innerHTML = keyHtml + renderValue(val) + (isLast ? '' : ',');
      return li;
    }
    const open = Array.isArray(val) ? '[' : '{';
    const close = Array.isArray(val) ? ']' : '}';
    const tog = document.createElement('span');
    tog.className = 'toggle expanded';
    tog.textContent = '▶';
    const head = document.createElement('span');
    head.innerHTML = keyHtml + '<span class="bracket">' + open + '</span>';
    const sum = document.createElement('span');
    sum.className = 'summary';
    sum.textContent = summary(val);
    li.appendChild(tog);
    li.appendChild(head);
    li.appendChild(sum);
    const ul = document.createElement('ul');
    const entries = Array.isArray(val) ? val.map((v,i)=>[i,v]) : Object.entries(val);
    entries.forEach(([k, v], i) => {
      const childKey = Array.isArray(val) ? null : k;
      ul.appendChild(build(childKey, v, depth+1, i === entries.length-1));
    });
    li.appendChild(ul);
    const closeSpan = document.createElement('div');
    closeSpan.innerHTML = '<span class="bracket">' + close + '</span>' + (isLast ? '' : ',');
    li.appendChild(closeSpan);
    tog.addEventListener('click', () => {
      li.classList.toggle('collapsed');
      tog.classList.toggle('expanded');
      tog.textContent = li.classList.contains('collapsed') ? '▶' : '▶';
    });
    return li;
  }

  const rootUl = document.createElement('ul');
  rootUl.appendChild(build(null, data, 0, true));
  root.appendChild(rootUl);

  // Initial: expand 2 levels (root + endpoints) for a useful overview.
  function setDepth(maxDepth) {
    root.querySelectorAll('li').forEach(li => {
      let d = 0; let p = li;
      while (p && p !== root) { if (p.tagName === 'LI') d++; p = p.parentElement; }
      const collapse = d > maxDepth;
      li.classList.toggle('collapsed', collapse);
      const tog = li.firstChild;
      if (tog && tog.classList && tog.classList.contains('toggle')) {
        tog.classList.toggle('expanded', !collapse);
      }
    });
  }
  setDepth(2);

  document.getElementById('expandAll').onclick = () => {
    root.querySelectorAll('li').forEach(li => {
      li.classList.remove('collapsed');
      const tog = li.firstChild;
      if (tog && tog.classList && tog.classList.contains('toggle')) tog.classList.add('expanded');
    });
  };
  document.getElementById('collapseAll').onclick = () => setDepth(1);
  document.getElementById('expandTwo').onclick   = () => setDepth(2);

  // ── Search / filter ──
  const search = document.getElementById('search');
  const hits = document.getElementById('searchHits');
  let searchTimer;
  search.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(runSearch, 120);
  });
  function runSearch() {
    const q = search.value.trim().toLowerCase();
    // Clear previous highlights
    root.querySelectorAll('.match').forEach(m => {
      const parent = m.parentNode;
      parent.replaceChild(document.createTextNode(m.textContent), m);
      parent.normalize();
    });
    if (!q) { hits.textContent = ''; return; }
    let count = 0;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(node => {
      const idx = node.textContent.toLowerCase().indexOf(q);
      if (idx === -1) return;
      const before = node.textContent.slice(0, idx);
      const match = node.textContent.slice(idx, idx + q.length);
      const after = node.textContent.slice(idx + q.length);
      const span = document.createElement('span');
      span.className = 'match';
      span.textContent = match;
      const frag = document.createDocumentFragment();
      if (before) frag.appendChild(document.createTextNode(before));
      frag.appendChild(span);
      if (after) frag.appendChild(document.createTextNode(after));
      node.parentNode.replaceChild(frag, node);
      count++;
      // Expand all ancestors of this match
      let li = span.closest('li');
      while (li && li !== root) {
        li.classList.remove('collapsed');
        const tog = li.firstChild;
        if (tog && tog.classList && tog.classList.contains('toggle')) tog.classList.add('expanded');
        li = li.parentElement.closest('li');
      }
    });
    hits.textContent = count + ' match' + (count === 1 ? '' : 'es');
  }
})();
</script>
</body>
</html>
"""


def main() -> int:
    grammar = fetch_grammar()
    pretty = json.dumps(grammar, indent=2)
    (ROOT / "schemas" / "_grammar_pretty.json").write_text(pretty)
    from datetime import date
    page = (PAGE_TMPL
            .replace("__TIMESTAMP__", date.today().isoformat())
            .replace("__JSON__", json.dumps(grammar)))
    OUT.write_text(page)
    print(f"  wrote {OUT.relative_to(ROOT)}  ({len(page)//1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
