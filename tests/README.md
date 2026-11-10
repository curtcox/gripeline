# gripeline test harness

This directory encodes the [spec](../SPEC.md) as executable fixtures and a runner
that validates a gripeline transpiler against them.

```
tests/
  run.py            # the harness
  test_units.py     # unit tests: annotate, id quoting, sniffing, share links, modl parity corpus
  modl_parse.cjs    # runs modl's own parser (from $MODL_REPO) for parity checks
  cases/            # one *.case file per example (success cases)
  cases/errors/     # one *.case file per §9 not-executable condition
  stubs/            # (optional) fake commands on PATH for `runnable` cases
```

## Running

```bash
python3 tests/run.py                 # all cases
python3 tests/run.py 12.4 fanin      # only cases whose name matches a filter
python3 tests/run.py --list          # list cases without running
python3 tests/run.py -q              # quiet: only failing cases + summary
```

From the repo root, `make check` runs the fixtures (quiet) and the unit tests
together, using `../modl` for parity checks if it exists.

Point the harness at your transpiler with `GRIPELINE`:

```bash
GRIPELINE=./gripeline            python3 tests/run.py
GRIPELINE='python3 gripeline.py' python3 tests/run.py
```

Point `MODL_REPO` at a `curtcox/modl` checkout (needs `node`) to also check
that gripeline parses every `=== modl ===` source exactly as modl does:

```bash
MODL_REPO=../modl GRIPELINE='python3 gripeline.py' python3 tests/run.py
```

Unit tests cover what fixtures can't: `--annotate` output, modl id quoting,
unsupported CLI mode rejection before input or execution, language sniffing,
share links, line splitting, edge scoping, and parity with
modl's parser over modl's own examples (its gallery and docs snippets) plus a
set of lexer edge cases. The parity tests are skipped without `MODL_REPO`:

```bash
MODL_REPO=../modl python3 tests/test_units.py
```

The harness invokes `$GRIPELINE <subcmd> <file.dot|file.modl>`, where `<subcmd>`
defaults to `build` (override via `GRIPELINE_SUBCMD`; set it empty to omit).
`build` must print the transpiled bash to stdout, run the §9 static check first,
and exit non-zero with diagnostics on stderr for a non-executable graph.

**Without** `GRIPELINE` set, the runner defaults to `./gripeline` when present.
Otherwise transpile/run checks are skipped but every case
is still validated for dot/modl validity and (for exact cases) bash-lint — so the
fixtures themselves are always checked.

## What each case is checked for

| check            | when it runs                         | what it verifies |
|------------------|--------------------------------------|------------------|
| `dot-valid`      | when `=== dot ===` is present        | `=== dot ===` parses with Graphviz (`dot -Tcanon`); falls back to a brace check if `dot` is absent |
| `modl-valid`     | when `=== modl ===` is present       | `=== modl ===` parses with modl; with `$MODL_REPO` (a `curtcox/modl` checkout) and `node`, gripeline's parse must also match modl's own parser — same nodes, shapes, text and edges ([`modl_parse.cjs`](modl_parse.cjs)). Without it, only gripeline's parser runs. For `code: parse` cases, modl must report an error too |
| `lint`           | exact-bash cases                     | the `=== bash ===` expectation is itself valid bash (`bash -n`) |
| `transpile`      | when `GRIPELINE` is set              | transpiler output matches the expectation (see modes below) |
| `modl-transpile` | twin cases (`dot` + `modl`)          | `.modl` source transpiles to the same expected bash/error as `.dot` |
| `run`            | `runnable: true` + `GRIPELINE` set   | the produced bash, when executed, prints the `=== stdout ===` section |
| `modl-run`       | twin runnable cases                  | the bash produced from `=== modl ===` prints `=== stdout ===` |

## The `.case` file format

A case is a small text file: `key: value` headers, then one or more
`=== section ===` blocks. A case may contain `=== dot ===`, `=== modl ===`, or
both (a *twin* case that proves dot/modl parity against the same `=== bash ===`
and `=== stdout ===`).

```
name: 12.2-redirect-typed     # unique name (used for filtering & reporting)
mapping: typed                # informational: which mapping the example uses
spec: 12.2                    # informational: section of SPEC.md
expect: bash                  # bash | contains | error
=== dot ===
digraph { ... }               # the dot source
=== modl ===
in  hex    access.log         # the equivalent modl source
out hex    counts.txt
g   square grep 404
w   square wc -l
in -> g -> w -> out
=== bash ===
grep 404 < access.log | wc -l > counts.txt
```

### `expect` modes

- **`expect: bash`** — *exact* match. The transpiler's output, after
  normalization, must equal the `=== bash ===` section. Normalization strips
  blank lines, comment lines, the standard prologue (`set -euo pipefail`, …), and
  per-line leading/trailing whitespace — so indentation and boilerplate don't
  matter, but the statements must match. Use for deterministic emissions.
  Add `keep-prologue: true` to compare the prologue too.

- **`expect: contains`** — every non-blank line of the `=== bash ===` section
  must appear as a substring of the output. Use for emissions whose exact
  formatting is implementation-defined (fan-out via `tee`, functions, loops).
  Keep the patterns small and robust (`for f in *.txt`, not a whole `do…done`).

- **`expect: error`** — the transpiler must exit non-zero; the `code:` header (if
  present; `code: parse` requires exit status 2) and every line of the
  `=== error ===` section must appear in the diagnostics. Use for §9
  not-executable graphs and §14 modl parse errors.

### Optional headers / sections

- `runnable: true` + an `=== stdout ===` section (and optional `=== stdin ===`):
  the produced bash is executed and its stdout compared. Runnable cases here use
  only coreutils so no stubs are needed; drop fake commands into `tests/stubs/`
  if a case needs them.
- `keep-prologue: true` — include the prologue in exact comparison.
- `=== stderr ===` — expected warning/diagnostic substrings on stderr.

## Adding a case

Drop a new `*.case` file in `cases/` (or `cases/errors/`). No registration step —
the runner globs `cases/**/*.case`. Start from the closest existing file. Pick
`expect: bash` if you can predict the exact output, otherwise `contains`.

Editor/API regression tests in `test_units.py` compare the pure API against CLI
build results for every fixture in both languages, test stdin and CID inputs,
and check CID syntax and Bash discovery. `web/tests/` contains optional browser
checks; these use Node/Playwright only and are separate from `make check`.

Cases named `portable_*.case` carry `portable: true` and expected stdout for the
separate native portability check. They do not require t256 during `make check`.
`python3 scripts/check_portability.py` downloads a pinned, checksummed native
t256 into a temporary directory, verifies the environment's baseline commands,
executes both languages of every portable twin, and checks a saved CID envelope
and tampered-content rejection. `--release-dir PATH` uses a local release cache.
CI runs it on macOS, Linux and Windows.


For one-time acceptance after approving a real HashBin save of
`portable_t256_count.case`, dispatch the Pages workflow with `published_cid`.
The OS matrix downloads with its pinned native t256, verifies the diagram source
matches that fixture exactly, then runs the CID command and expects `6`.
Unrelated programs are rejected before execution; ordinary CI has no expiring
public-CID dependency.
