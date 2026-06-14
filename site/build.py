#!/usr/bin/env python3
"""Static-site generator for the gripeline project (stdlib only).

Builds, into an output directory (default: ``site/_site``):

  index.html        landing page
  spec.html         SPEC.md rendered to HTML, with every ```dot``` block shown
                    as source *and* a rendered SVG (via the `dot` CLI)
  tests.html        the conformance test index, with pass/fail per case
  tests/<name>.html one page per test case: source dot, rendered SVG, the
                    expected bash/error, the transpiler's actual output, and a
                    per-check (dot-valid / lint / transpile / run) breakdown

The test results are produced by importing the conformance harness in
``tests/run.py`` and running its checks against the transpiler named by the
GRIPELINE environment variable (default: ``python3 <repo>/gripeline.py``).

Usage:
    python3 site/build.py [output-dir]

Requires the `dot` CLI (Graphviz) on PATH to render diagrams; without it the
diagrams degrade to a "source only" note.
"""
from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = ROOT / "tests"
SPEC_MD = ROOT / "SPEC.md"
DOT_BIN = shutil.which("dot")

# Point the harness at the bundled transpiler unless the caller overrides it.
os.environ.setdefault("GRIPELINE", f"python3 {ROOT / 'gripeline.py'}")

# Import the conformance harness so we reuse its parsing and checks verbatim.
sys.path.insert(0, str(TESTS_DIR))
import run as harness  # noqa: E402


# ==========================================================================
# Graphviz rendering
# ==========================================================================
# A block is already a full graph if it declares one anywhere (a leading
# /* comment */ may precede the `digraph` keyword); otherwise it is a fragment
# (e.g. a routing snippet) and we wrap it in `digraph { ... }` to render it.
_GRAPH_DECL = re.compile(r"\b(strict\s+)?(di)?graph\b", re.IGNORECASE)


def render_dot_svg(src: str) -> str | None:
    """Render dot source to an inline <svg> string, or None on failure.

    Fragments that are not already a full ``(di)graph { ... }`` are wrapped in a
    ``digraph { ... }`` so the routing-example snippets in the spec render too.
    """
    if not DOT_BIN:
        return None
    source = src if _GRAPH_DECL.search(src) else f"digraph {{\n{src}\n}}"
    try:
        p = subprocess.run(
            [DOT_BIN, "-Tsvg"], input=source,
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    svg = p.stdout
    i = svg.find("<svg")
    return svg[i:] if i != -1 else None


def diagram_block(src: str, *, with_source: bool = True) -> str:
    """HTML for a dot snippet: optional source plus its rendered SVG."""
    parts = []
    if with_source:
        parts.append(
            '<div class="dot-source"><div class="label">dot source</div>'
            f"<pre><code>{html.escape(src)}</code></pre></div>"
        )
    svg = render_dot_svg(src)
    if svg is not None:
        parts.append(f'<div class="dot-render"><div class="label">rendered</div>'
                     f'<div class="svg-wrap">{svg}</div></div>')
    else:
        note = ("rendering unavailable (install Graphviz)" if not DOT_BIN
                else "this snippet did not render")
        parts.append(f'<div class="dot-render"><div class="note">{note}</div></div>')
    return f'<div class="diagram">{"".join(parts)}</div>'


# ==========================================================================
# Minimal Markdown -> HTML (covers what SPEC.md actually uses)
# ==========================================================================
def slug(text: str) -> str:
    """GitHub-style heading anchor: lowercase, drop punctuation, spaces->'-'."""
    s = text.strip().lower()
    s = re.sub(r"[^\w\- ]", "", s)   # strip punctuation (keep word chars, -, space)
    s = s.replace(" ", "-")
    return s


_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC = re.compile(r"(?<![\w*])[*_]([^*_\n]+)[*_](?![\w*])")


def inline(text: str) -> str:
    """Render inline markdown to HTML, escaping everything else."""
    codes: list[str] = []

    def stash_code(m: re.Match) -> str:
        codes.append(html.escape(m.group(1)))
        return f"\x00{len(codes) - 1}\x00"

    text = re.sub(r"`([^`]+)`", stash_code, text)
    text = html.escape(text)

    # Links: escape the URL but keep it functional.
    def link(m: re.Match) -> str:
        label, url = m.group(1), m.group(2)
        return f'<a href="{html.escape(url, quote=True)}">{label}</a>'

    text = _LINK.sub(link, text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)

    text = re.sub(r"\x00(\d+)\x00", lambda m: f"<code>{codes[int(m.group(1))]}</code>", text)
    return text


def _list_item_html(text: str) -> str:
    return inline(text)


def render_markdown(md: str) -> str:
    """Block-level markdown renderer. Returns an HTML fragment."""
    lines = md.splitlines()
    out: list[str] = []
    i = 0
    n = len(lines)

    def is_table_sep(s: str) -> bool:
        return bool(re.match(r"^\s*\|?[\s:|-]+\|?\s*$", s)) and "-" in s

    while i < n:
        line = lines[i]

        # blank
        if not line.strip():
            i += 1
            continue

        # fenced code block
        m = re.match(r"^```(\w*)\s*$", line)
        if m:
            lang = m.group(1)
            j = i + 1
            body: list[str] = []
            while j < n and not re.match(r"^```\s*$", lines[j]):
                body.append(lines[j])
                j += 1
            code = "\n".join(body)
            if lang == "dot":
                out.append(diagram_block(code))
            else:
                cls = f' class="lang-{lang}"' if lang else ""
                out.append(f"<pre><code{cls}>{html.escape(code)}</code></pre>")
            i = j + 1
            continue

        # heading
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            anchor = slug(text)
            out.append(f'<h{level} id="{anchor}">{inline(text)}</h{level}>')
            i += 1
            continue

        # horizontal rule
        if re.match(r"^(\*\s*){3,}$|^(-\s*){3,}$|^(_\s*){3,}$", line.strip()):
            out.append("<hr>")
            i += 1
            continue

        # blockquote (possibly multi-line)
        if line.lstrip().startswith(">"):
            quote: list[str] = []
            while i < n and lines[i].lstrip().startswith(">"):
                quote.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            inner = render_markdown("\n".join(quote))
            out.append(f"<blockquote>{inner}</blockquote>")
            continue

        # table (GFM pipe table: header row, separator, body rows)
        if "|" in line and i + 1 < n and is_table_sep(lines[i + 1]):
            def split_row(s: str) -> list[str]:
                s = s.strip()
                s = re.sub(r"^\|", "", s)
                s = re.sub(r"\|$", "", s)
                return [c.strip() for c in s.split("|")]

            header = split_row(line)
            i += 2  # skip header + separator
            rows: list[list[str]] = []
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append(split_row(lines[i]))
                i += 1
            th = "".join(f"<th>{inline(c)}</th>" for c in header)
            trs = []
            for r in rows:
                tds = "".join(f"<td>{inline(c)}</td>" for c in r)
                trs.append(f"<tr>{tds}</tr>")
            out.append(f"<table><thead><tr>{th}</tr></thead>"
                       f"<tbody>{''.join(trs)}</tbody></table>")
            continue

        # lists (ordered / unordered, with indentation-based nesting)
        if re.match(r"^\s*([-*+]|\d+\.)\s+", line):
            block: list[str] = []
            while i < n and (re.match(r"^\s*([-*+]|\d+\.)\s+", lines[i])
                             or (lines[i].strip() and lines[i].startswith((" ", "\t"))
                                 and block)):
                block.append(lines[i])
                i += 1
            out.append(render_list(block))
            continue

        # paragraph: gather until blank or a block starter
        para: list[str] = []
        while i < n and lines[i].strip() and not _starts_block(lines[i], lines, i):
            para.append(lines[i])
            i += 1
        if para:
            out.append(f"<p>{inline(' '.join(s.strip() for s in para))}</p>")
        else:
            i += 1  # safety: avoid infinite loop

    return "\n".join(out)


def _starts_block(line: str, lines: list[str], idx: int) -> bool:
    if re.match(r"^```", line):
        return True
    if re.match(r"^#{1,6}\s", line):
        return True
    if line.lstrip().startswith(">"):
        return True
    if re.match(r"^(\*\s*){3,}$|^(-\s*){3,}$|^(_\s*){3,}$", line.strip()):
        return True
    if re.match(r"^\s*([-*+]|\d+\.)\s+", line):
        return True
    if "|" in line and idx + 1 < len(lines) and \
       re.match(r"^\s*\|?[\s:|-]+\|?\s*$", lines[idx + 1]) and "-" in lines[idx + 1]:
        return True
    return False


_ITEM = re.compile(r"^(\s*)([-*+]|\d+\.)\s+(.*)$")


def render_list(block: list[str]) -> str:
    """Render a (possibly nested) list block to HTML."""
    # Determine the indent of the top level.
    base_indent = len(re.match(r"^(\s*)", block[0]).group(1))
    ordered = bool(re.match(r"^\s*\d+\.", block[0]))
    tag = "ol" if ordered else "ul"

    items: list[str] = []
    k = 0
    while k < len(block):
        m = _ITEM.match(block[k])
        if not m:
            k += 1
            continue
        indent = len(m.group(1))
        if indent > base_indent:
            # belongs to a nested list handled by a previous item; skip
            k += 1
            continue
        text = m.group(3)
        # gather child lines (deeper indent or continuation) for this item
        children: list[str] = []
        k += 1
        while k < len(block):
            mm = _ITEM.match(block[k])
            cur_indent = len(re.match(r"^(\s*)", block[k]).group(1))
            if mm and len(mm.group(1)) <= base_indent:
                break
            children.append(block[k])
            k += 1
        item_html = _list_item_html(text)
        if children:
            # children may include a nested list and/or continuation text
            nested = [c for c in children if _ITEM.match(c)]
            if nested:
                item_html += render_list(children)
        items.append(f"<li>{item_html}</li>")
    return f"<{tag}>{''.join(items)}</{tag}>"


# ==========================================================================
# Page template
# ==========================================================================
CSS = """
:root { --fg:#1b1f24; --muted:#57606a; --bg:#ffffff; --border:#d0d7de;
        --code-bg:#f6f8fa; --accent:#0969da; --pass:#1a7f37; --fail:#cf222e;
        --skip:#9a6700; }
* { box-sizing:border-box; }
body { margin:0; color:var(--fg); background:var(--bg);
       font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif; }
.wrap { max-width:960px; margin:0 auto; padding:2rem 1.25rem 5rem; }
nav.top { border-bottom:1px solid var(--border); background:#fafbfc; }
nav.top .wrap { padding:.75rem 1.25rem; display:flex; gap:1.25rem; align-items:center; }
nav.top a { text-decoration:none; color:var(--fg); font-weight:600; }
nav.top a:hover { color:var(--accent); }
nav.top .brand { font-weight:700; }
nav.top .spacer { flex:1; }
a { color:var(--accent); }
h1,h2,h3,h4 { line-height:1.25; margin-top:1.8rem; }
h1 { font-size:1.9rem; } h2 { font-size:1.45rem; padding-bottom:.3rem;
     border-bottom:1px solid var(--border); } h3 { font-size:1.2rem; }
code { background:var(--code-bg); padding:.15em .35em; border-radius:4px;
       font:.88em ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }
pre { background:var(--code-bg); border:1px solid var(--border); border-radius:8px;
      padding:.9rem 1rem; overflow:auto; }
pre code { background:none; padding:0; }
table { border-collapse:collapse; width:100%; margin:1rem 0; display:block;
        overflow:auto; }
th,td { border:1px solid var(--border); padding:.45rem .7rem; text-align:left;
        vertical-align:top; }
th { background:var(--code-bg); }
blockquote { margin:1rem 0; padding:.4rem 1rem; color:var(--muted);
             border-left:.25rem solid var(--border); }
hr { border:none; border-top:1px solid var(--border); margin:2rem 0; }
.diagram { display:grid; grid-template-columns:1fr 1fr; gap:1rem; margin:1.2rem 0;
           align-items:start; }
@media (max-width:720px){ .diagram { grid-template-columns:1fr; } }
.diagram .label { font-size:.72rem; text-transform:uppercase; letter-spacing:.05em;
                  color:var(--muted); margin-bottom:.3rem; }
.dot-source pre { margin:0; }
.svg-wrap { border:1px solid var(--border); border-radius:8px; padding:1rem;
            background:#fff; overflow:auto; }
.svg-wrap svg { max-width:100%; height:auto; display:block; }
.note { color:var(--muted); font-style:italic; border:1px dashed var(--border);
        border-radius:8px; padding:1rem; }
.badge { display:inline-block; padding:.1em .55em; border-radius:999px;
         font-size:.78rem; font-weight:600; color:#fff; }
.badge.pass { background:var(--pass); } .badge.fail { background:var(--fail); }
.badge.skip { background:var(--skip); }
.summary { display:flex; gap:1rem; flex-wrap:wrap; margin:1rem 0 1.5rem; }
.summary .stat { border:1px solid var(--border); border-radius:8px; padding:.6rem 1rem;
                 min-width:6rem; }
.summary .stat .num { font-size:1.6rem; font-weight:700; }
.summary .stat .lbl { font-size:.78rem; color:var(--muted); text-transform:uppercase; }
.checks { display:flex; gap:.5rem; flex-wrap:wrap; }
.test-row td:first-child { font-family:ui-monospace,Menlo,monospace; font-size:.9rem; }
details.detail { margin:.5rem 0; }
.muted { color:var(--muted); }
.spec-meta { color:var(--muted); }
"""


def page(title: str, body: str, *, depth: int = 0) -> str:
    """Wrap a body fragment in the full HTML page with nav."""
    up = "../" * depth
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>{CSS}</style>
</head>
<body>
<nav class="top"><div class="wrap">
  <a class="brand" href="{up}index.html">gripeline</a>
  <a href="{up}spec.html">Spec</a>
  <a href="{up}tests.html">Tests</a>
  <span class="spacer"></span>
  <a href="https://github.com/curtcox/gripeline">GitHub</a>
</div></nav>
<main class="wrap">
{body}
</main>
</body>
</html>
"""


# ==========================================================================
# Test pages
# ==========================================================================
STATUS_BADGE = {"PASS": "pass", "FAIL": "fail", "SKIP": "skip"}


def case_anchor(case) -> str:
    return re.sub(r"[^\w.-]", "_", case.name)


def run_transpiler_clean(case):
    """Invoke the transpiler like the harness does, but with a stable filename.

    The harness writes the dot to a random temp file, so diagnostics echo a path
    like ``/tmp/tmpXXXX.dot``. For published output we want a readable, stable
    reference, so we use ``<name>.dot`` and scrub the directory from the
    captured stdout/stderr. Returns a (rc, out, err) tuple shaped exactly like
    ``harness.run_transpiler`` so the harness check functions can consume it.
    """
    if not harness.GRIPELINE:
        return None
    import shlex
    import tempfile
    safe = re.sub(r"[^\w.-]", "_", case.name) + ".dot"
    with tempfile.TemporaryDirectory() as d:
        dotfile = os.path.join(d, safe)
        with open(dotfile, "w") as f:
            f.write(case.dot if case.dot.endswith("\n") else case.dot + "\n")
        cmd = shlex.split(harness.GRIPELINE)
        if harness.GRIPELINE_SUBCMD:
            cmd.append(harness.GRIPELINE_SUBCMD)
        cmd.append(dotfile)
        p = subprocess.run(cmd, capture_output=True, text=True)
        out = p.stdout.replace(d + os.sep, "").replace(dotfile, safe)
        err = p.stderr.replace(d + os.sep, "").replace(dotfile, safe)
        return p.returncode, out, err


def run_case_checks(case):
    """Run the harness checks for one case; return (result, checks list)."""
    result = run_transpiler_clean(case)
    checks = [
        harness.check_dot_valid(case),
        harness.check_lint(case),
        harness.check_transpile(case, result),
        harness.check_run(case, result),
    ]
    return result, checks


def case_status(checks) -> str:
    if any(c.status == "FAIL" for c in checks):
        return "FAIL"
    if any(c.status == "PASS" for c in checks):
        return "PASS"
    return "SKIP"


def build_test_pages(out_dir: Path) -> dict:
    cases = harness.discover([])
    tests_out = out_dir / "tests"
    tests_out.mkdir(parents=True, exist_ok=True)

    rows = []
    n_pass = n_fail = n_skip = 0
    per_check_totals = {"PASS": 0, "FAIL": 0, "SKIP": 0}

    for case in cases:
        result, checks = run_case_checks(case)
        status = case_status(checks)
        if status == "PASS":
            n_pass += 1
        elif status == "FAIL":
            n_fail += 1
        else:
            n_skip += 1
        for c in checks:
            per_check_totals[c.status] += 1

        anchor = case_anchor(case)
        page_name = f"{anchor}.html"
        rel = case.path.relative_to(TESTS_DIR)

        # --- per-test page ---
        body = [f"<h1>{html.escape(case.name)}</h1>"]
        meta = []
        for k in ("mapping", "spec", "expect"):
            v = case.headers.get(k)
            if v:
                meta.append(f"<strong>{k}:</strong> {html.escape(v)}")
        meta.append(f'<strong>source:</strong> <code>tests/{html.escape(str(rel))}</code>')
        body.append(f'<p class="spec-meta">{" &nbsp;·&nbsp; ".join(meta)}</p>')
        body.append(f'<p>Status: <span class="badge {STATUS_BADGE[status]}">{status}</span></p>')

        # checks breakdown
        body.append("<h2>Checks</h2>")
        chk_rows = []
        for c in checks:
            detail = f"<br><span class='muted'>{html.escape(c.detail)}</span>" if c.detail else ""
            chk_rows.append(
                f"<tr><td>{c.label}</td>"
                f"<td><span class='badge {STATUS_BADGE[c.status]}'>{c.status}</span>{detail}</td></tr>"
            )
        body.append("<table><thead><tr><th>check</th><th>result</th></tr></thead>"
                     f"<tbody>{''.join(chk_rows)}</tbody></table>")

        # the diagram
        body.append("<h2>Diagram</h2>")
        body.append(diagram_block(case.dot))

        # expectation
        if case.expect == "error":
            body.append("<h2>Expected error</h2>")
            err = case.sections.get("error", "")
            code = case.headers.get("code")
            if code:
                body.append(f"<p class='spec-meta'><strong>code:</strong> <code>{html.escape(code)}</code></p>")
            body.append(f"<pre><code>{html.escape(err)}</code></pre>")
        else:
            body.append("<h2>Expected bash</h2>")
            body.append(f"<pre><code>{html.escape(case.sections.get('bash', ''))}</code></pre>")
            if "stdout" in case.sections:
                body.append("<h3>Expected stdout</h3>")
                body.append(f"<pre><code>{html.escape(case.sections['stdout'])}</code></pre>")

        # actual transpiler output
        body.append("<h2>Transpiler output</h2>")
        if result is None:
            body.append("<p class='note'>Transpiler not configured.</p>")
        else:
            rc, sout, serr = result
            body.append(f"<p class='spec-meta'>exit code: <code>{rc}</code></p>")
            if sout.strip():
                body.append("<div class='label'>stdout</div>")
                body.append(f"<pre><code>{html.escape(sout)}</code></pre>")
            if serr.strip():
                body.append("<div class='label'>stderr</div>")
                body.append(f"<pre><code>{html.escape(serr)}</code></pre>")

        (tests_out / page_name).write_text(
            page(f"{case.name} — gripeline test", "\n".join(body), depth=1)
        )

        # --- index row ---
        check_badges = " ".join(
            f"<span class='badge {STATUS_BADGE[c.status]}' title='{html.escape(c.detail)}'>{c.label}</span>"
            for c in checks
        )
        rows.append(
            f"<tr class='test-row'><td><a href='tests/{page_name}'>{html.escape(case.name)}</a></td>"
            f"<td>{html.escape(case.headers.get('mapping',''))}</td>"
            f"<td>{html.escape(case.headers.get('expect',''))}</td>"
            f"<td><span class='badge {STATUS_BADGE[status]}'>{status}</span></td>"
            f"<td><div class='checks'>{check_badges}</div></td></tr>"
        )

    # --- index page ---
    summary = (
        "<div class='summary'>"
        f"<div class='stat'><div class='num'>{len(cases)}</div><div class='lbl'>cases</div></div>"
        f"<div class='stat'><div class='num' style='color:var(--pass)'>{n_pass}</div><div class='lbl'>passed</div></div>"
        f"<div class='stat'><div class='num' style='color:var(--fail)'>{n_fail}</div><div class='lbl'>failed</div></div>"
        f"<div class='stat'><div class='num' style='color:var(--skip)'>{n_skip}</div><div class='lbl'>skipped</div></div>"
        "</div>"
    )
    body = [
        "<h1>Conformance test results</h1>",
        f"<p class='muted'>Transpiler under test: <code>{html.escape(os.environ.get('GRIPELINE',''))}</code>. "
        "Each case is checked for dot-validity, bash lint (exact cases), transpile match, and (where applicable) runtime stdout.</p>",
        summary,
        "<table><thead><tr><th>case</th><th>mapping</th><th>expect</th><th>status</th><th>checks</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>",
    ]
    (out_dir / "tests.html").write_text(page("gripeline — test results", "\n".join(body)))

    return {"cases": len(cases), "pass": n_pass, "fail": n_fail, "skip": n_skip}


# ==========================================================================
# Spec + index pages
# ==========================================================================
def build_spec_page(out_dir: Path) -> None:
    md = SPEC_MD.read_text()
    body = render_markdown(md)
    (out_dir / "spec.html").write_text(page("gripeline — specification", body))


def build_index_page(out_dir: Path, stats: dict) -> None:
    readme = (ROOT / "README.md").read_text()
    # Use the README intro but render through our markdown.
    body = [render_markdown(readme)]
    body.append("<hr>")
    body.append(
        "<p>This site publishes the "
        "<a href='spec.html'>specification</a> with rendered Graphviz diagrams, "
        "and the <a href='tests.html'>conformance test results</a> "
        f"({stats['pass']} passed, {stats['fail']} failed, {stats['skip']} skipped "
        f"of {stats['cases']} cases).</p>"
    )
    (out_dir / "index.html").write_text(page("gripeline", "\n".join(body)))


# ==========================================================================
# Main
# ==========================================================================
def main(argv: list[str]) -> int:
    out_dir = Path(argv[0]).resolve() if argv else (ROOT / "site" / "_site")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"build: output -> {out_dir}")
    print(f"build: dot     -> {DOT_BIN or 'NOT FOUND (diagrams degrade)'}")
    print(f"build: gripeline -> {os.environ.get('GRIPELINE')}")

    stats = build_test_pages(out_dir)
    build_spec_page(out_dir)
    build_index_page(out_dir, stats)

    print(f"build: {stats['cases']} cases "
          f"({stats['pass']} pass, {stats['fail']} fail, {stats['skip']} skip)")
    print("build: wrote index.html, spec.html, tests.html, tests/*.html")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
