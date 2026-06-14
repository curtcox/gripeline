#!/usr/bin/env python3
"""gripeline transpiler conformance harness.

Runs the fixtures under tests/cases/ against a gripeline transpiler and checks,
for each case:

  1. dot-valid   -- the .dot source parses with Graphviz (`dot -Tcanon`).
  2. lint        -- the *expected* bash is itself valid bash (`bash -n`).
                    (proves the fixtures are sound even before a transpiler exists)
  3. transpile   -- the transpiler's output matches expectation:
                      expect: bash      exact match (after normalization)
                      expect: contains  every pattern line appears in the output
                      expect: error     non-zero exit + expected code/substrings
  4. run         -- (optional) the produced bash is executed and its stdout
                    compared to the case's expected stdout.

The transpiler under test is given by the GRIPELINE environment variable, e.g.

    GRIPELINE=./gripeline           python3 tests/run.py
    GRIPELINE='python3 gripeline.py' python3 tests/run.py

The harness invokes it as:   $GRIPELINE <subcmd> <file.dot>
where <subcmd> defaults to "build" (override with GRIPELINE_SUBCMD; empty = none).
`build` must print the transpiled bash to stdout, run the §9 static check first,
and exit non-zero with diagnostics on stderr for a non-executable graph.

If GRIPELINE is unset, the transpile/run checks are skipped but dot-valid and
lint still run, so the fixtures are always validated.

Usage:
    python3 tests/run.py [name-substring ...]   # filter cases by name
    python3 tests/run.py --list                 # list cases and exit
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CASES_DIR = ROOT / "cases"
STUBS_DIR = ROOT / "stubs"

DOT_BIN = shutil.which("dot")
BASH_BIN = shutil.which("bash") or "/bin/bash"
GRIPELINE = os.environ.get("GRIPELINE")
GRIPELINE_SUBCMD = os.environ.get("GRIPELINE_SUBCMD", "build")

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


def run_transpiler(case: Case):
    """Returns (returncode, stdout, stderr) or None if no transpiler configured."""
    if not GRIPELINE:
        return None
    dotfile = write_temp(case.dot, ".dot")
    cmd = shlex.split(GRIPELINE)
    if GRIPELINE_SUBCMD:
        cmd.append(GRIPELINE_SUBCMD)
    cmd.append(dotfile)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True)
    finally:
        os.unlink(dotfile)
    return p.returncode, p.stdout, p.stderr


def check_transpile(case: Case, result) -> CheckResult:
    if result is None:
        return CheckResult("transpile", "SKIP", "set GRIPELINE to enable")
    rc, out, err = result

    if case.expect == "error":
        if rc == 0:
            return CheckResult("transpile", "FAIL",
                               "expected non-zero exit, got 0")
        code = case.headers.get("code")
        if code and code not in (err + out):
            return CheckResult("transpile", "FAIL",
                               f"expected error code {code} in diagnostics")
        for pat in pattern_lines(case.sections.get("error", "")):
            if pat not in (err + out):
                return CheckResult("transpile", "FAIL",
                                   f"missing expected text: {pat!r}")
        return CheckResult("transpile", "PASS")

    # success expectations
    if rc != 0:
        return CheckResult("transpile", "FAIL",
                           f"transpiler exited {rc}: {err.strip()}")

    if case.expect == "contains":
        for pat in pattern_lines(case.sections.get("bash", "")):
            if pat not in out:
                return CheckResult("transpile", "FAIL",
                                   f"output missing: {pat!r}")
        return CheckResult("transpile", "PASS")

    # exact
    got = normalize_bash(out, case.keep_prologue)
    want = normalize_bash(case.sections.get("bash", ""), case.keep_prologue)
    if got != want:
        import difflib
        diff = "\n".join(difflib.unified_diff(want, got, "expected", "got",
                                              lineterm=""))
        return CheckResult("transpile", "FAIL", diff)
    return CheckResult("transpile", "PASS")


def check_run(case: Case, result) -> CheckResult:
    if not case.runnable:
        return CheckResult("run", "SKIP", "")
    if result is None:
        return CheckResult("run", "SKIP", "set GRIPELINE to enable")
    rc, out, err = result
    if rc != 0:
        return CheckResult("run", "SKIP", "transpile failed")
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
    # Compare line-by-line, stripping per-line whitespace: many tools (e.g. BSD
    # `wc`) pad numeric output, and that padding is not what we're testing here.
    want = [l.strip() for l in case.sections.get("stdout", "").strip("\n").splitlines()]
    got = [l.strip() for l in p.stdout.strip("\n").splitlines()]
    if got != want:
        return CheckResult("run", "FAIL",
                           f"stdout mismatch:\n  want: {want!r}\n  got:  {got!r}")
    return CheckResult("run", "PASS")


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------
def main(argv: list[str]) -> int:
    if "--list" in argv:
        for c0 in discover([a for a in argv if not a.startswith("--")]):
            print(f"{c0.name:40s} expect={c0.expect}  {c0.path.relative_to(ROOT)}")
        return 0

    filters = [a for a in argv if not a.startswith("--")]
    cases = discover(filters)
    if not cases:
        print("no cases found", file=sys.stderr)
        return 1

    print(BOLD(f"gripeline harness  ({len(cases)} cases)"))
    print(DIM(f"  dot      : {DOT_BIN or 'NOT FOUND (brace-check fallback)'}"))
    print(DIM(f"  bash     : {BASH_BIN}"))
    print(DIM(f"  gripeline: {GRIPELINE or 'unset (transpile/run skipped)'}"))
    print()

    n_pass = n_fail = n_skip = 0
    failures: list[tuple[str, CheckResult]] = []

    for case in cases:
        result = run_transpiler(case)
        checks = [
            check_dot_valid(case),
            check_lint(case),
            check_transpile(case, result),
            check_run(case, result),
        ]
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
