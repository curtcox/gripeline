# gripeline test harness

This directory encodes the [spec](../SPEC.md) as executable fixtures and a runner
that validates a gripeline transpiler against them.

```
tests/
  run.py            # the harness
  cases/            # one *.case file per example (success cases)
  cases/errors/     # one *.case file per §9 not-executable condition
  stubs/            # (optional) fake commands on PATH for `runnable` cases
```

## Running

```bash
python3 tests/run.py                 # all cases
python3 tests/run.py 12.4 fanin      # only cases whose name matches a filter
python3 tests/run.py --list          # list cases without running
```

Point the harness at your transpiler with `GRIPELINE`:

```bash
GRIPELINE=./gripeline            python3 tests/run.py
GRIPELINE='python3 gripeline.py' python3 tests/run.py
```

The harness invokes `$GRIPELINE <subcmd> <file.dot>`, where `<subcmd>` defaults
to `build` (override via `GRIPELINE_SUBCMD`; set it empty to omit). `build` must
print the transpiled bash to stdout, run the §9 static check first, and exit
non-zero with diagnostics on stderr for a non-executable graph.

**Without** `GRIPELINE` set, the transpile/run checks are skipped but every case
is still validated for dot-validity and (for exact cases) bash-lint — so the
fixtures themselves are always checked.

## What each case is checked for

| check       | when it runs                         | what it verifies |
|-------------|--------------------------------------|------------------|
| `dot-valid` | always                               | `=== dot ===` parses with Graphviz (`dot -Tcanon`); falls back to a brace check if `dot` is absent |
| `lint`      | exact-bash cases                     | the `=== bash ===` expectation is itself valid bash (`bash -n`) |
| `transpile` | when `GRIPELINE` is set              | transpiler output matches the expectation (see modes below) |
| `run`       | `runnable: true` + `GRIPELINE` set   | the produced bash, when executed, prints the `=== stdout ===` section |

## The `.case` file format

A case is a small text file: `key: value` headers, then one or more
`=== section ===` blocks.

```
name: 12.2-redirect-typed     # unique name (used for filtering & reporting)
mapping: typed                # informational: which mapping the example uses
spec: 12.2                    # informational: section of SPEC.md
expect: bash                  # bash | contains | error
=== dot ===
digraph { ... }               # the gripeline source
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
  present) and every line of the `=== error ===` section must appear in the
  diagnostics. Use for §9 not-executable graphs.

### Optional headers / sections

- `runnable: true` + an `=== stdout ===` section (and optional `=== stdin ===`):
  the produced bash is executed and its stdout compared. Runnable cases here use
  only coreutils so no stubs are needed; drop fake commands into `tests/stubs/`
  if a case needs them.
- `keep-prologue: true` — include the prologue in exact comparison.

## Adding a case

Drop a new `*.case` file in `cases/` (or `cases/errors/`). No registration step —
the runner globs `cases/**/*.case`. Start from the closest existing file. Pick
`expect: bash` if you can predict the exact output, otherwise `contains`.
