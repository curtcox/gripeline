# Implementation prompt — build the `gripeline` transpiler

You are implementing **gripeline**, a transpiler that turns an ordinary Graphviz
`dot` file into a `bash` script. The full language is defined in
[`SPEC.md`](SPEC.md) (Draft 0.3). Read it end to end before writing code — the
emitted bash is the *normative* meaning of a graph, so the spec is the
authority, and this prompt only orients you and pins down the contract.

## Goal

Produce a single, self-contained **Python 3 (standard library only)** program,
`gripeline.py`, plus an executable `gripeline` shim, that passes the conformance
harness in [`tests/`](tests/) and implements the spec in full (§§4–9). No third
party packages, no `pip install`, no `pydot`/`graphviz` — write your own `dot`
parser.

Definition of done:

```bash
GRIPELINE='python3 gripeline.py' python3 tests/run.py
```
prints all-green: every case passes the `transpile` check, every `runnable: true`
case passes `run`, and every `errors/*.case` exits non-zero with the documented
code and substrings. The harness must also pass `./gripeline` directly:

```bash
GRIPELINE=./gripeline python3 tests/run.py
```

Do not edit anything under `tests/` to make cases pass — the fixtures are the
spec made executable. If you believe a fixture is wrong, stop and flag it rather
than editing it.

## The harness contract (read `tests/run.py` and `tests/README.md` first)

- The harness invokes `$GRIPELINE build <file.dot>`. `build` must print the
  transpiled bash to **stdout** and exit `0` for an executable graph.
- For a **non-executable** graph (§9), `build` must run the static check
  *before* emitting anything, write diagnostics to **stderr**, and exit
  non-zero. The diagnostics must contain the error **code** (e.g. `E04`) and the
  reason substrings the matching `errors/*.case` lists.
- Output normalization (see `normalize_bash` in `tests/run.py`): blank lines,
  `#` comment lines, and standard prologue lines (`set -euo pipefail`, etc.) are
  stripped, and each line is whitespace-trimmed, before an `expect: bash` exact
  comparison. So **boilerplate and indentation are free, but the statements must
  match exactly.** `expect: contains` only requires each pattern line to appear
  as a substring somewhere in the output. `runnable: true` cases execute your
  output under `bash` and compare stdout.
- Exit codes (§9): `0` ran/built OK; `65` not executable (static check failed);
  other non-zero codes from `run` propagate the pipeline's status.

## CLI surface (implement all of it)

```
gripeline build  <file.dot>     # print transpiled bash to stdout (harness uses this)
gripeline run    <file.dot>     # transpile then exec under bash; propagate exit status
gripeline check  <file.dot>     # run only the §9 static check; exit 0 or 65
  --annotate[=out.dot]          # also write a diagnostic-annotated dot copy (§9): offending
                                #   elements get color=red, tooltip, gl_error="..."
  --strict                      # ordering ambiguity (multiple valid topo orders) is an error
  --infer-style                 # also read the recommended visual conventions (§3); OFF by default
```
Default prologue is `set -euo pipefail`, overridable by the graph attribute
`gl_prologue` (§10). `build` should emit the prologue (the harness strips it
unless a case sets `keep-prologue: true`).

## Architecture (mirror SPEC §2)

1. **Parse** real `dot` into an AST. Support: `digraph`/`graph`, `subgraph` /
   `cluster_*` nesting, node statements, edge statements with chains
   (`a -> b -> c`), **ports** (`a:1 -> b:out`), attribute lists `[k=v, ...]`,
   `node`/`edge`/`graph` default statements that **cascade** into subgraphs
   (§4.4), quoted strings with escapes (`\"`), and comments `//`, `/* */`, `#`.
   Don't shell out to `dot`; parse it yourself.
2. **Extract** the execution graph (§3): node identities + cluster nesting, edge
   endpoints + ports, node/edge operation text (`label` else id; edge label for
   Dataflow), reserved `gl_*` attrs, and role-bearing `shape` values. **Ignore
   all rendering-only attributes** (`color`, `style`, `pos`, `fontname`, …) —
   behavior must not change based on them unless `--infer-style` is passed.
3. **Resolve roles & mapping** (§4). `gl_mapping` is file-level only (default
   `typed`); it changes only defaults. Roles come from `gl_role`, else from the
   reserved `shape` set (§4.3: `box`→program, `note`→file, `cds`→stream,
   `oval`+`gl_role=value`→value), else from the mapping default. Cascading
   `gl_role`/`gl_edge` subgraph defaults must work (§4.4).
4. **Static check** (§9) → emit diagnostics + optional `--annotate` copy, or
   proceed.
5. **Transpile** to bash via a deterministic topological order (§6.1: order is
   consistent with both control and data edges; ties broken by **source
   order**; independent nodes run sequentially in source order unless
   `gl_async=true`).

## Semantics you must get right (anchored to the fixtures)

Work case-by-case against `tests/cases/`. The exact-match (`expect: bash`) cases
pin the canonical emission; reproduce them precisely:

- **Pipe** (program→program): `a | b`. A straight chain is an n-stage pipe.
- **Redirect**: file→program is `cmd < file`; program→file is `cmd > file`
  (`>>` when the file node has `gl_append=true`). A pipeline that begins at a
  file and ends at a file emits as one line:
  `grep 404 < access.log | wc -l > counts.txt` (`12_02_typed`, `extra_append`).
- **Ports → fds** (§5): tail default port `out`(1), head default `in`(0).
  `make:err -> errlog` → `make 2> build.err`. A numbered/`err` port to a file is
  a plain redirect (`gen:3 -> trace` → `gen 3> trace.out`). An edge between two
  ports **on the same node** is an fd dup; only the order-independent `2>&1`
  shape is allowed (`make:err -> make:out` → `make 2>&1`, possibly fused onto a
  following pipe as in `12_03_stderr_case2`). More than one dup, or a dup vs. a
  redirect of the same fd, is **E09**.
- **Fan-out** (one program, several data out-edges) → `tee` + process
  substitution; the "main" output edge to a file is the trailing `> file`
  (`12_04_fanout_typed`, `expect: contains`).
- **Fan-in** → an `op` node (`gl_role=op`, or a program with multiple typed
  inputs) → `cat <(…) <(…)` (`12_05_fanin_typed`). Two plain data edges into the
  same fd of a non-op node is **E03**.
- **Control edges** (§6.1): `gl_edge=seq|and|or` → `;` / `&&` / `||`
  (`12_06_conditionals` → `make && make install || echo FAIL`). Control cycles
  are **E05**.
- **Grouping** (§6.2): `subgraph cluster_*` with `gl_role` → `( … )` (subshell,
  default), `{ …; }` (group), or `name() { …; }` (function + `gl_name`; then
  callable by a node whose label is the name) — `12_07_function`,
  `extra_subshell`.
- **Variables** (§7): `gl_role=value` node → shell var; program→value edge with
  `gl_name` captures stdout (`git -> ver [gl_name="ver"]` → `ver=$(git describe
  --tags)`); the assignment must be ordered before any use. In Dataflow a node
  *is* a value. Two captures into one value is **E08**.
- **Loops** (§8): a `cluster_*` with `gl_loop` is a loop body; the attribute is
  the header (`for VAR in WORDS`, `while COND`, `until COND`, `while read VAR`).
  A data edge into the cluster feeds the loop's stdin; `while read` wires it to
  `done < input` (`12_10_while_read`, `12_11_full_script`). A `coproc`-declared
  data cycle → `coproc` (`extra_coproc_cycle`); an **undeclared** data cycle is
  **E04**.
- **`gl_async=true`** → trailing `&` with a `wait` at the join (`extra_async`).
- **`gl_raw`** → emit the string verbatim, no re-quoting (`extra_gl_raw`). Label
  text is *never* re-quoted (§13.4) — pass `$VAR`, quotes, and `$(...)` through
  literally.
- **Dataflow mapping** (§4.2): node = value, edge `label` = program; `gl_stderr`
  / `gl_fd` express fd routing on a program edge (`12_*_dataflow`).

### Static checks (§9) — implement E01–E09 exactly

E01 not a `digraph`; E02 program node with empty operation text; E03 two data
edges into one fd without a merge; E04 undeclared data cycle; E05 control cycle;
E06 edge whose endpoint roles have no transpilation (e.g. file→file); E07 port
naming an fd on a node that has none (file/value); E08 conflicting/duplicate
value capture; E09 ambiguous/order-sensitive fd dup. Each diagnostic must carry
its code and a reason matching the relevant `errors/*.case` substring. Follow the
output contract format shown in §9.

## Engineering guidance

- One file, `gripeline.py`, stdlib only. Add an executable `./gripeline` shim
  (`#!/usr/bin/env python3` wrapper or `exec python3 .../gripeline.py "$@"`),
  `chmod +x`. Both `GRIPELINE='python3 gripeline.py'` and `GRIPELINE=./gripeline`
  invocations of the harness must pass.
- Structure it as clear stages (parse → extract → resolve → check → emit) with
  small dataclasses for `Node`, `Edge`, `Graph`. Keep the parser robust to the
  dot constructs the fixtures actually use, then generalize.
- Determinism is required: stable source-order tie-breaking, no set-iteration
  nondeterminism in output.
- Build incrementally and run the harness continuously, filtering to the case
  you're on: `GRIPELINE='python3 gripeline.py' python3 tests/run.py 12.2`.
  Land the exact-match (`expect: bash`) cases first — they constrain canonical
  output — then the `contains`, `runnable`, and `errors` cases.
- Run the **whole** suite before declaring done; confirm all-green under both
  invocation forms. Don't special-case fixtures or pattern-match on case names;
  implement the general rule the spec states.

## Deliverables

1. `gripeline.py` — the transpiler (stdlib only).
2. `gripeline` — executable shim on PATH-style usage.
3. A short note in `README.md` updating the "transpiler is not built yet" line
   to reflect that it now exists and how to run it.
4. A green run of `python3 tests/run.py` under both `GRIPELINE` forms, pasted as
   evidence.
