#!/usr/bin/env python3
"""gripeline transpiler conformance harness.

Runs the fixtures under tests/cases/ against a gripeline transpiler and checks,
for each case:

  1. dot-valid   -- the .dot source parses with Graphviz (`dot -Tcanon`).
  2. modl-valid  -- the .modl source parses with modl, and (when $MODL_REPO
                    points at a curtcox/modl checkout and node is installed)
                    gripeline's parse matches modl's own parser: same nodes,
                    shapes, text and edges. Without MODL_REPO, only
                    gripeline's own modl parser is used.
  3. lint        -- the *expected* bash is itself valid bash (`bash -n`).
                    (proves the fixtures are sound even before a transpiler exists)
  4. transpile   -- the transpiler's output matches expectation (for each
                    source language present in the case: === dot === and/or
                    === modl ===):
                      expect: bash      exact match (after normalization)
                      expect: contains  every pattern line appears in the output
                      expect: error     non-zero exit + expected code/substrings
  5. run         -- (optional) the produced bash is executed and its stdout
                    compared to the case's expected stdout.

The transpiler under test is given by the GRIPELINE environment variable, e.g.

    GRIPELINE=./gripeline            python3 tests/run.py
    GRIPELINE='python3 gripeline.py' python3 tests/run.py

The harness invokes it as:   $GRIPELINE <subcmd> <file.dot|file.modl>
where <subcmd> defaults to "build" (override with GRIPELINE_SUBCMD; empty = none).
`build` must print the transpiled bash to stdout, run the §9 static check first,
and exit non-zero with diagnostics on stderr for a non-executable graph.

If GRIPELINE is unset, ./gripeline is used when present; otherwise the
transpile/run checks are skipped but dot-valid,
modl-valid, and lint still run, so the fixtures are always validated.

Usage:
    python3 tests/run.py [name-substring ...]   # filter cases by name
    python3 tests/run.py --list                 # list cases and exit
    python3 tests/run.py -q                     # quiet: print only failures + summary
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
CASES_DIR = ROOT / "cases"
STUBS_DIR = ROOT / "stubs"

sys.path.insert(0, str(REPO_ROOT))
import gripeline as gl_mod  # noqa: E402

DOT_BIN = shutil.which("dot")
NODE_BIN = shutil.which("node")
BASH_BIN = shutil.which("bash") or "/bin/bash"
GRIPELINE = os.environ.get("GRIPELINE", "./gripeline" if Path("./gripeline").is_file() else None)
GRIPELINE_SUBCMD = os.environ.get("GRIPELINE_SUBCMD", "build")
MODL_REPO = os.environ.get("MODL_REPO")
if MODL_REPO and not (Path(MODL_REPO) / "js" / "editor.js").is_file():
    print(f"warning: MODL_REPO={MODL_REPO} has no js/editor.js; modl parity check disabled",
          file=sys.stderr)
    MODL_REPO = None

# Prologue lines that normalization strips so fixtures can omit boilerplate.
PROLOGUE = {
    "set -e", "set -u", "set -eu", "set -euo pipefail", "set -eo pipefail",
    "set -uo pipefail", "set -o pipefail",
}

# ---- ANSI (disabled when not a tty) ----
_TTY = sys.stdout.isatty()
def c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if _TTY else s
GREEN = lambda s: c("32", s)
RED = lambda s: c("31", s)
YELLOW = lambda s: c("33", s)
DIM = lambda s: c("2", s)
BOLD = lambda s: c("1", s)


# --------------------------------------------------------------------------
# Case file parsing
# --------------------------------------------------------------------------
@dataclass
class Case:
    path: Path
    headers: dict
    sections: dict
    name: str = ""

    def __post_init__(self):
        self.name = self.headers.get("name", self.path.stem)

    @property
    def expect(self) -> str:
        return self.headers.get("expect", "bash")

    @property
    def dot(self) -> str:
        return self.sections.get("dot", "")

    @property
    def modl(self) -> str:
        return self.sections.get("modl", "")

    @property
    def has_dot(self) -> bool:
        return bool(self.dot.strip())

    @property
    def has_modl(self) -> bool:
        return bool(self.modl.strip())

    @property
    def runnable(self) -> bool:
        return self.headers.get("runnable", "").lower() in ("1", "true", "yes")

    @property
    def keep_prologue(self) -> bool:
        return self.headers.get("keep-prologue", "").lower() in ("1", "true", "yes")


SECTION_RE = re.compile(r"^===\s*([a-z0-9_-]+)\s*===\s*$")


def parse_case(path: Path) -> Case:
    headers: dict = {}
    sections: dict = {}
    current = None
    buf: list[str] = []

    def flush():
        if current is not None:
            sections[current] = "\n".join(buf).strip("\n")

    for line in path.read_text().splitlines():
        m = SECTION_RE.match(line)
        if m:
            flush()
            current = m.group(1)
            buf = []
            continue
        if current is None:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip()] = v.strip()
        else:
            buf.append(line)
    flush()
    return Case(path=path, headers=headers, sections=sections)


def discover(filters: list[str]) -> list[Case]:
    cases = [parse_case(p) for p in sorted(CASES_DIR.rglob("*.case"))]
    if filters:
        cases = [c for c in cases if any(f in c.name for f in filters)]
    return cases


# --------------------------------------------------------------------------
# Normalization & helpers
# --------------------------------------------------------------------------
def normalize_bash(text: str, keep_prologue: bool = False) -> list[str]:
    out = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if not keep_prologue and s in PROLOGUE:
            continue
        out.append(s)
    return out


def pattern_lines(text: str) -> list[str]:
    return [l.strip() for l in text.splitlines()
            if l.strip() and not l.strip().startswith("#")]


@dataclass
class CheckResult:
    label: str
    status: str  # PASS / FAIL / SKIP
    detail: str = ""


def write_temp(text: str, suffix: str) -> str:
    fd, name = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w") as f:
        f.write(text if text.endswith("\n") else text + "\n")
    return name


# --------------------------------------------------------------------------
# Individual checks
# --------------------------------------------------------------------------
def check_dot_valid(case: Case) -> CheckResult:
    dot = case.dot
    if not dot.strip():
        if case.has_modl:
            return CheckResult("dot-valid", "SKIP", "modl-only case")
        return CheckResult("dot-valid", "FAIL", "no === dot === section")
    if DOT_BIN:
        p = subprocess.run([DOT_BIN, "-Tcanon"], input=dot,
                           capture_output=True, text=True)
        if p.returncode != 0:
            return CheckResult("dot-valid", "FAIL", p.stderr.strip())
        return CheckResult("dot-valid", "PASS")
    # Fallback: minimal sanity check when Graphviz is absent.
    if "digraph" not in dot and "graph" not in dot:
        return CheckResult("dot-valid", "FAIL", "no graph keyword (no `dot` to verify)")
    if dot.count("{") != dot.count("}"):
        return CheckResult("dot-valid", "FAIL", "unbalanced braces (no `dot` to verify)")
    return CheckResult("dot-valid", "PASS", "(brace check only; install graphviz)")


MODL_PARSE_JS = ROOT / "modl_parse.cjs"


def _run_modl_repo_parser(src: str) -> dict | None:
    """Parse `src` with modl's real parser (tests/modl_parse.cjs over
    $MODL_REPO/js/editor.js). None when MODL_REPO or node is unavailable."""
    if not MODL_REPO or not NODE_BIN:
        return None
    p = subprocess.run([NODE_BIN, str(MODL_PARSE_JS), MODL_REPO],
                       input=json.dumps({"src": src}), capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"modl_parse.cjs failed: {p.stderr.strip()}")
    return json.loads(p.stdout)["src"]


def _modl_display(raw: str | None) -> str:
    """What modl shows for a raw text slice: word values joined by spaces."""
    if not raw:
        return ""
    return " ".join(w.val for w in gl_mod._lex_modl_line(raw) if w.kind == "word")


def modl_parity_diffs(src: str, js: dict) -> list[str]:
    """Differences between gripeline's modl parse and modl's own parse:
    node set, shapes, node text, and the edge list (endpoints, line style,
    text). These are exactly the facts that decide what runs, so any
    difference means the picture and the program disagree."""
    m = gl_mod.parse_modl(src)
    diffs = []
    jn = js["nodes"]
    for nid in jn:
        if nid not in m.nodes and nid not in m.clusters:
            diffs.append(f"modl draws node {nid!r} but gripeline has no such node or group")
    for nid in m.nodes:
        if nid not in jn:
            diffs.append(f"gripeline has node {nid!r} that modl does not draw")
    for nid, nd in m.nodes.items():
        if nid not in jn:
            continue
        shape = nd.attrs.get("shape", "circle")
        if shape != jn[nid]["shape"]:
            diffs.append(f"node {nid!r}: shape gripeline={shape!r} modl={jn[nid]['shape']!r}")
        gt, mt = _modl_display(nd.attrs.get("label")), jn[nid]["text"]
        if gt != mt and not (gt.strip() == "" and mt.strip() == ""):
            diffs.append(f"node {nid!r}: text gripeline={gt!r} modl={mt!r}")
    ge = [(e.tail, e.head, e.attrs.get("style", "solid"), _modl_display(e.attrs.get("label")))
          for e in m.edges]
    je = [(e["from"], e["to"], e["style"], e["text"]) for e in js["edges"]]
    for edge, parsed in zip(m.edges, js["edges"]):
        if parsed.get("rawText", "") != edge.attrs.get("label", ""):
            diffs.append(f"edge {edge.tail} -> {edge.head}: raw source text differs")
        for key, port in (("fromPort", edge.tail_port), ("toPort", edge.head_port)):
            if parsed.get(key) is not None and parsed[key] != port:
                diffs.append(f"edge {edge.tail} -> {edge.head}: {key} differs")
    if ge != je:
        diffs.append(f"edges differ:\n  gripeline={ge}\n  modl     ={je}")
    return diffs


def check_modl_valid(case: Case) -> CheckResult:
    modl = case.modl
    if not modl.strip():
        return CheckResult("modl-valid", "SKIP", "dot-only case")
    try:
        js_res = _run_modl_repo_parser(modl)
    except RuntimeError as e:
        return CheckResult("modl-valid", "FAIL", str(e))
    if case.headers.get("code") == "parse":
        # gripeline must only reject what modl itself reports as an error.
        if js_res is None:
            return CheckResult("modl-valid", "SKIP", "intentional modl parse error case")
        if not js_res["errors"]:
            return CheckResult("modl-valid", "FAIL",
                               "case expects a modl parse error, but modl parses it cleanly")
        return CheckResult("modl-valid", "PASS", "modl reports: " + "; ".join(js_res["errors"]))
    if js_res is not None and js_res["errors"]:
        return CheckResult("modl-valid", "FAIL", "; ".join(str(e) for e in js_res["errors"]))
    try:
        gl_mod.parse_modl(modl)
    except gl_mod.GripError as e:
        return CheckResult("modl-valid", "FAIL", str(e))
    if js_res is None:
        return CheckResult("modl-valid", "PASS", "(gripeline parser only; set MODL_REPO for parity)")
    diffs = modl_parity_diffs(modl, js_res)
    if diffs:
        return CheckResult("modl-valid", "FAIL", "\n".join(diffs))
    return CheckResult("modl-valid", "PASS", "matches modl's parser")


def check_lint(case: Case) -> CheckResult:
    if case.expect != "bash":
        return CheckResult("lint", "SKIP", "only exact-bash fixtures are linted")
    expected = case.sections.get("bash", "")
    name = write_temp(expected, ".sh")
    try:
        p = subprocess.run([BASH_BIN, "-n", name], capture_output=True, text=True)
    finally:
        os.unlink(name)
    if p.returncode != 0:
        return CheckResult("lint", "FAIL", p.stderr.strip())
    return CheckResult("lint", "PASS")


def run_transpiler(case: Case, lang: str = "dot"):
    """Returns (returncode, stdout, stderr) or None if no transpiler/source."""
    if not GRIPELINE:
        return None
    src = case.dot if lang == "dot" else case.modl
    if not src.strip():
        return None
    suffix = ".dot" if lang == "dot" else ".modl"
    srcfile = write_temp(src, suffix)
    cmd = shlex.split(GRIPELINE)
    if GRIPELINE_SUBCMD:
        cmd.append(GRIPELINE_SUBCMD)
    cmd.append(srcfile)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True)
    finally:
        os.unlink(srcfile)
    return p.returncode, p.stdout, p.stderr


def check_transpile(case: Case, result, label: str = "transpile") -> CheckResult:
    if result is None:
        return CheckResult(label, "SKIP", "set GRIPELINE to enable")
    rc, out, err = result

    if case.expect == "error":
        if rc == 0:
            return CheckResult(label, "FAIL",
                               "expected non-zero exit, got 0")
        code = case.headers.get("code")
        if code == "parse":
            if rc != 2:
                return CheckResult(label, "FAIL",
                                   f"expected exit 2 for parse error, got {rc}")
        elif code and code not in (err + out):
            return CheckResult(label, "FAIL",
                               f"expected error code {code} in diagnostics")
        for pat in pattern_lines(case.sections.get("error", "")):
            if pat not in (err + out):
                return CheckResult(label, "FAIL",
                                   f"missing expected text: {pat!r}")
        for pat in pattern_lines(case.sections.get("stderr", "")):
            if pat not in err:
                return CheckResult(label, "FAIL",
                                   f"missing expected stderr: {pat!r}")
        return CheckResult(label, "PASS")

    # success expectations
    if rc != 0:
        return CheckResult(label, "FAIL",
                           f"transpiler exited {rc}: {err.strip()}")

    for pat in pattern_lines(case.sections.get("stderr", "")):
        if pat not in err:
            return CheckResult(label, "FAIL",
                               f"stderr missing warning: {pat!r}")

    if case.expect == "contains":
        for pat in pattern_lines(case.sections.get("bash", "")):
            if pat not in out:
                return CheckResult(label, "FAIL",
                                   f"output missing: {pat!r}")
        return CheckResult(label, "PASS")

    # exact
    got = normalize_bash(out, case.keep_prologue)
    want = normalize_bash(case.sections.get("bash", ""), case.keep_prologue)
    if got != want:
        import difflib
        diff = "\n".join(difflib.unified_diff(want, got, "expected", "got",
                                              lineterm=""))
        return CheckResult(label, "FAIL", diff)
    return CheckResult(label, "PASS")


def check_run(case: Case, result, label: str = "run") -> CheckResult:
    if not case.runnable:
        return CheckResult(label, "SKIP", "")
    if result is None:
        return CheckResult(label, "SKIP", "set GRIPELINE to enable")
    rc, out, err = result
    if rc != 0:
        return CheckResult(label, "SKIP", "transpile failed")
    script = write_temp(out, ".sh")
    env = dict(os.environ)
    if STUBS_DIR.is_dir():
        env["PATH"] = f"{STUBS_DIR}{os.pathsep}{env['PATH']}"
    stdin = case.sections.get("stdin", "")
    try:
        p = subprocess.run([BASH_BIN, script], input=stdin,
                           capture_output=True, text=True, env=env,
                           cwd=tempfile.gettempdir())
    finally:
        os.unlink(script)
    want = [l.strip() for l in case.sections.get("stdout", "").strip("\n").splitlines()]
    got = [l.strip() for l in p.stdout.strip("\n").splitlines()]
    if got != want:
        return CheckResult(label, "FAIL",
                           f"stdout mismatch:\n  want: {want!r}\n  got:  {got!r}")
    return CheckResult(label, "PASS")


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------
def evaluate_case(case: Case) -> list[CheckResult]:
    checks: list[CheckResult] = []
    if case.has_dot:
        dot_res = run_transpiler(case, "dot")
        checks.append(check_dot_valid(case))
        checks.append(check_lint(case))
        checks.append(check_transpile(case, dot_res, "transpile"))
        checks.append(check_run(case, dot_res, "run"))
        if case.has_modl:
            modl_res = run_transpiler(case, "modl")
            checks.append(check_modl_valid(case))
            checks.append(check_transpile(case, modl_res, "modl-transpile"))
            checks.append(check_run(case, modl_res, "modl-run"))
    elif case.has_modl:
        modl_res = run_transpiler(case, "modl")
        checks.append(check_modl_valid(case))
        checks.append(check_lint(case))
        checks.append(check_transpile(case, modl_res, "transpile"))
        checks.append(check_run(case, modl_res, "run"))
    else:
        checks.append(CheckResult("dot-valid", "FAIL", "no === dot === or === modl === section"))
    return checks


def main(argv: list[str]) -> int:
    if "--list" in argv:
        for c0 in discover([a for a in argv if not a.startswith("--")]):
            langs = "+".join([l for l, ok in (("dot", c0.has_dot), ("modl", c0.has_modl)) if ok])
            print(f"{c0.name:40s} [{langs:8s}] expect={c0.expect}  {c0.path.relative_to(ROOT)}")
        return 0

    quiet = "-q" in argv or "--quiet" in argv
    filters = [a for a in argv if not a.startswith("-")]
    cases = discover(filters)
    if not cases:
        print("no cases found", file=sys.stderr)
        return 1

    print(BOLD(f"gripeline harness  ({len(cases)} cases)"))
    print(DIM(f"  dot      : {DOT_BIN or 'NOT FOUND (brace-check fallback)'}"))
    print(DIM(f"  modl_repo: {MODL_REPO or 'unset (using gripeline modl parser)'}"))
    print(DIM(f"  bash     : {BASH_BIN}"))
    print(DIM(f"  gripeline: {GRIPELINE or 'unset (transpile/run skipped)'}"))
    print()

    n_pass = n_fail = n_skip = 0
    failures: list[tuple[str, CheckResult]] = []

    for case in cases:
        checks = evaluate_case(case)
        marks = []
        case_failed = False
        for chk in checks:
            if chk.status == "PASS":
                marks.append(GREEN("✓") + DIM(chk.label))
                n_pass += 1
            elif chk.status == "FAIL":
                marks.append(RED("✗" + chk.label))
                n_fail += 1
                case_failed = True
                failures.append((case.name, chk))
            else:
                marks.append(DIM("•" + chk.label))
                n_skip += 1
        if quiet and not case_failed:
            continue
        head = RED("FAIL") if case_failed else GREEN("ok  ")
        print(f"  {head} {case.name:38s} {' '.join(marks)}")

    print()
    for name, chk in failures:
        print(RED(f"FAIL {name} [{chk.label}]"))
        if chk.detail:
            for line in chk.detail.splitlines():
                print("    " + line)
    print()
    print(BOLD(f"{n_pass} passed, {n_fail} failed, {n_skip} skipped"))
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
