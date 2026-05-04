#!/usr/bin/env python3
"""Render Kinetica graph endpoint schemas as standalone HTML pages.

Source schemas live in `~/gpudb-dev/gpudb-schemas/endpoint-schemas/` as JSON
files with one quirk — string values may span multiple raw newlines (not
`\\n`). We normalize that, parse, then emit one self-contained HTML file per
endpoint into `schemas/`.

Output pages share the User Guide's dark/light theme and are linked from the
guide's Section 7 (Graph Grammar and API).
"""
from __future__ import annotations
import html
import json
import re
from pathlib import Path

SRC = Path.home() / "gpudb-dev" / "gpudb-schemas" / "endpoint-schemas"
OUT = Path(__file__).parent / "schemas"
OUT.mkdir(parents=True, exist_ok=True)

ENDPOINTS = [
    ("create_graph",       "/create/graph",        "Create Graph"),
    ("query_graph",        "/query/graph",         "Query Graph"),
    ("solve_graph",        "/solve/graph",         "Solve Graph"),
    ("match_graph",        "/match/graph",         "Match Graph"),
    ("show_graph",         "/show/graph",          "Show Graph"),
    ("alter_graph",        "/alter/graph",         "Alter Graph"),
    ("get_graph_entities", "/get/graph/entities",  "Get Graph Entities"),
]

# Pages that aren't request/response schema pairs but live in the same dir.
EXTRA_PAGES = [
    ("show_graph_grammar", "/show/graph/grammar", "Graph Grammar (live JSON tree)"),
]


def normalize_jsonish(text: str) -> str:
    """Convert raw newlines inside string literals to escaped \\n."""
    out = []
    in_str = False
    esc = False
    for ch in text:
        if in_str:
            if esc:
                out.append(ch)
                esc = False
                continue
            if ch == "\\":
                out.append(ch)
                esc = True
                continue
            if ch == '"':
                out.append(ch)
                in_str = False
                continue
            if ch == "\n":
                out.append("\\n")
                continue
            if ch == "\r":
                continue
            if ch == "\t":
                out.append("\\t")
                continue
            out.append(ch)
        else:
            if ch == '"':
                in_str = True
            out.append(ch)
    return "".join(out)


def load_schema(name: str) -> dict:
    raw = (SRC / f"{name}.json").read_text()
    return json.loads(normalize_jsonish(raw))


# ── Doc-string formatting ─────────────────────────────────────────────────
# gpudb docs use {text}@{link /path/} markers and {value}@{choice ...} markers.
LINK_RE   = re.compile(r"\{([^{}]*)\}@\{link\s+([^{}\s]+)\s*\}")
CHOICE_RE = re.compile(r"\{([^{}]*)\}@\{choice[^{}]*\}")
ENDPOINT_RE = re.compile(r"\{([^{}]*)\}@\{endpoint[^{}]*\}")
DEFAULT_RE = re.compile(r"\{([^{}]*)\}@\{default[^{}]*\}")
# Strip any remaining @{...} tag markers, keeping the {label} text
GENERIC_RE = re.compile(r"\{([^{}]*)\}@\{[^{}]*\}")


def render_doc(s: str | None) -> str:
    if not s:
        return ""
    s = html.escape(s)
    # Re-substitute the curly braces (they got escaped)
    s = s.replace("&#x27;", "'")
    # Markers were escaped — re-find using escaped braces
    def link_repl(m):
        text, target = m.group(1), m.group(2)
        # External docs: keep as inline-code reference
        return f"<code>{text}</code>"
    s = re.sub(r"\{([^{}]*)\}@\{link\s+([^{}\s]+)\s*\}", link_repl, s)
    s = re.sub(r"\{([^{}]*)\}@\{choice[^{}]*\}",   r"<code>\1</code>", s)
    s = re.sub(r"\{([^{}]*)\}@\{endpoint[^{}]*\}", r"<code>\1</code>", s)
    s = re.sub(r"\{([^{}]*)\}@\{default[^{}]*\}",  r"<code>\1</code>", s)
    s = re.sub(r"\{([^{}]*)\}@\{[^{}]*\}",         r"<code>\1</code>", s)
    # Inline code for {bare} braces
    s = re.sub(r"\{([^{}]+)\}", r"<code>\1</code>", s)
    # Newlines → <br>; collapse runs
    s = re.sub(r"(\\n\s*)+", "<br>", s)
    s = re.sub(r"(\n\s*)+", "<br>", s)
    return s


def render_type(t) -> str:
    """Render an Avro-style type to a short string."""
    if isinstance(t, str):
        return f"<code>{html.escape(t)}</code>"
    if isinstance(t, list):
        return " | ".join(render_type(x) for x in t)
    if isinstance(t, dict):
        kind = t.get("type")
        if kind == "array":
            return f"array&lt;{render_type(t.get('items',''))}&gt;"
        if kind == "map":
            return f"map&lt;string,{render_type(t.get('values',''))}&gt;"
        if kind == "record":
            return f"record"
        return f"<code>{html.escape(str(kind))}</code>"
    return f"<code>{html.escape(str(t))}</code>"


def render_value(v) -> str:
    """Render the {value:{...}} block — defaults, valid choices, etc."""
    if not isinstance(v, dict) or not v:
        return ""
    parts = []
    if "default" in v:
        parts.append(f"<span class='kv'>default:</span> <code>{html.escape(str(v['default']))}</code>")
    if "valid_choices" in v:
        choices = v["valid_choices"]
        if isinstance(choices, dict):
            items = []
            for key, meta in choices.items():
                doc = (meta or {}).get("doc", "") if isinstance(meta, dict) else ""
                if doc:
                    items.append(f"<li><code>{html.escape(str(key))}</code> — {render_doc(doc)}</li>")
                else:
                    items.append(f"<li><code>{html.escape(str(key))}</code></li>")
            parts.append("<details><summary><span class='kv'>valid_choices</span></summary><ul class='choices'>" + "".join(items) + "</ul></details>")
    return "<div class='value-block'>" + "<br>".join(parts) + "</div>" if parts else ""


def render_field_row(field: dict) -> str:
    name = html.escape(field.get("name", ""))
    doc = render_doc(field.get("doc", ""))
    typ = render_type(field.get("type", ""))
    val = render_value(field.get("value", {}))
    return f"""
    <tr>
      <td class='fname'><code>{name}</code></td>
      <td class='ftype'>{typ}</td>
      <td class='fdoc'>{doc}{val}</td>
    </tr>"""


PAGE_CSS = r"""
:root {
  --bg: #ffffff; --bg-alt: #f6f8fa; --text: #24292f; --muted: #57606a;
  --border: #d0d7de; --accent: #2563eb; --code-bg: #eff1f3;
}
:root[data-theme="dark"] {
  --bg: #0d1117; --bg-alt: #161b22; --text: #c9d1d9; --muted: #8b949e;
  --border: #30363d; --accent: #58a6ff; --code-bg: #21262d;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #0d1117; --bg-alt: #161b22; --text: #c9d1d9; --muted: #8b949e;
    --border: #30363d; --accent: #58a6ff; --code-bg: #21262d;
  }
}
* { box-sizing: border-box; }
body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
       background: var(--bg); color: var(--text); line-height: 1.55; }
.wrap { max-width: 1100px; margin: 0 auto; padding: 32px 28px 80px; }
h1 { margin: 0 0 4px; font-size: 28px; }
h2 { margin: 36px 0 12px; font-size: 20px; border-bottom: 1px solid var(--border); padding-bottom: 6px; }
.crumbs { color: var(--muted); font-size: 13px; margin-bottom: 20px; }
.crumbs a { color: var(--accent); text-decoration: none; }
.crumbs a:hover { text-decoration: underline; }
.endpoint { display: inline-block; background: var(--code-bg); color: var(--accent);
            padding: 2px 8px; border-radius: 4px; font-family: SFMono-Regular,Consolas,monospace; font-size: 13px; }
.short { font-size: 16px; color: var(--muted); margin: 4px 0 16px; }
.intro { background: var(--bg-alt); border: 1px solid var(--border); border-radius: 6px;
         padding: 12px 14px; margin: 0 0 24px; font-size: 14px; }
table { width: 100%; border-collapse: collapse; margin: 8px 0 24px; font-size: 14px; }
th { text-align: left; background: var(--bg-alt); padding: 8px 10px; border-bottom: 1px solid var(--border);
     position: sticky; top: 0; }
td { padding: 10px; border-bottom: 1px solid var(--border); vertical-align: top; }
td.fname { white-space: nowrap; min-width: 180px; }
td.ftype { white-space: nowrap; min-width: 110px; color: var(--muted); }
td.fdoc { line-height: 1.5; }
code { background: var(--code-bg); color: var(--text); padding: 1px 5px;
       border-radius: 3px; font-family: SFMono-Regular,Consolas,monospace; font-size: 92%; }
.kv { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; }
.value-block { margin-top: 6px; font-size: 13px; }
ul.choices { margin: 6px 0 0 16px; padding: 0; }
ul.choices li { margin: 2px 0; }
details summary { cursor: pointer; color: var(--muted); font-size: 12px; }
.theme-btn { position: fixed; top: 16px; right: 16px; padding: 6px 12px; border: 1px solid var(--border);
             background: var(--bg-alt); color: var(--text); border-radius: 6px; cursor: pointer; font-size: 13px; }
"""

PAGE_JS = r"""
(function(){
  const saved = localStorage.getItem('schema-theme');
  const theme = saved || 'dark';
  document.documentElement.setAttribute('data-theme', theme);
  document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('themeBtn');
    function update() {
      const t = document.documentElement.getAttribute('data-theme');
      btn.textContent = t === 'dark' ? '☀ Light' : '☾ Dark';
    }
    update();
    btn.addEventListener('click', () => {
      const t = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', t);
      localStorage.setItem('schema-theme', t);
      update();
    });
  });
})();
"""


def render_schema_section(schema: dict, title: str) -> str:
    fields = schema.get("fields", [])
    rows = "".join(render_field_row(f) for f in fields)
    doc = render_doc(schema.get("doc", ""))
    return f"""
    <h2>{title}</h2>
    <div class='intro'>{doc}</div>
    <table>
      <thead><tr><th>Field</th><th>Type</th><th>Description</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>"""


def render_page(name: str, endpoint: str, title: str) -> str:
    req = load_schema(f"{name}_request")
    resp = load_schema(f"{name}_response")
    short = req.get("short_doc", "")
    body = render_schema_section(req, "Request") + render_schema_section(resp, "Response")
    return f"""<!DOCTYPE html>
<html lang='en'>
<head>
<meta charset='UTF-8'/>
<meta name='viewport' content='width=device-width, initial-scale=1.0'/>
<title>{html.escape(title)} — Kinetica Graph API</title>
<link rel='icon' type='image/png' href='../favicon.png'/>
<style>{PAGE_CSS}</style>
</head>
<body>
<button id='themeBtn' class='theme-btn'>☀ Light</button>
<div class='wrap'>
  <div class='crumbs'><a href='../Kinetica_Graph_User_Guide.html'>← Back to User Guide</a> · Graph API Reference</div>
  <h1>{html.escape(title)}</h1>
  <div><span class='endpoint'>{html.escape(endpoint)}</span></div>
  <p class='short'>{html.escape(short)}</p>
  {body}
</div>
<script>{PAGE_JS}</script>
</body>
</html>
"""


def render_index() -> str:
    rows = "".join(
        f"<tr><td><a href='{n}.html'>{html.escape(t)}</a></td><td><span class='endpoint'>{html.escape(e)}</span></td></tr>"
        for n, e, t in ENDPOINTS + EXTRA_PAGES
    )
    return f"""<!DOCTYPE html>
<html lang='en'>
<head>
<meta charset='UTF-8'/>
<title>Kinetica Graph API — Schema Reference</title>
<link rel='icon' type='image/png' href='../favicon.png'/>
<style>{PAGE_CSS}</style>
</head>
<body>
<button id='themeBtn' class='theme-btn'>☀ Light</button>
<div class='wrap'>
  <div class='crumbs'><a href='../Kinetica_Graph_User_Guide.html'>← Back to User Guide</a></div>
  <h1>Graph API — Schema Reference</h1>
  <p class='short'>Request and response schemas for the Kinetica graph endpoints, generated from <code>gpudb-schemas/endpoint-schemas/</code>.</p>
  <table>
    <thead><tr><th>Endpoint</th><th>Path</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</div>
<script>{PAGE_JS}</script>
</body>
</html>
"""


def main() -> int:
    for name, endpoint, title in ENDPOINTS:
        page = render_page(name, endpoint, title)
        (OUT / f"{name}.html").write_text(page)
        print(f"  wrote schemas/{name}.html")
    (OUT / "index.html").write_text(render_index())
    print(f"  wrote schemas/index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
