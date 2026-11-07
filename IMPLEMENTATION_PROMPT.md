# Implementation prompt — build the `gripeline` transpiler

You are implementing **gripeline**, a transpiler that turns an ordinary Graphviz
`dot` file or [`modl`](https://modl.hashbin.page/) diagram into a `bash` script.
The full language is defined in [`SPEC.md`](SPEC.md) (Draft 0.4). Read it end to
end before writing code — the emitted bash is the *normative* meaning of a
graph, so the spec is the authority, and this prompt only orients you and pins
down the contract.

## Goal

Produce a single, self-contained **Python 3 (standard library only)** program,
`gripeline.py`, plus an executable `gripeline` shim, that passes the conformance
harness in [`tests/`](tests/) and implements the spec in full (§§4–9, §14) for
both `dot` and `modl`. No third-party packages, no `pip install`, no
`pydot`/`graphviz` — write your own `dot` and `modl` parsers.

Definition of done:

```bash
GRIPELINE='python3 gripeline.py' python3 tests/run.py
```
prints all-green: every case passes `dot-valid`/`modl-valid`, `transpile` (and
`modl-transpile` for twin cases), every `runnable: true` case passes `run` (and
`modl-run`), and every `errors/*.case` exits non-zero with the documented code
and substrings. The harness must also pass `./gripeline` directly:

```bash
GRIPELINE=./gripeline python3 tests/run.py
```

Do not edit anything under `tests/` to make cases pass — the fixtures are the
spec made executable. If you believe a fixture is wrong, stop and flag it rather
than editing it.

## The harness contract (read `tests/run.py` and `tests/README.md` first)

- The harness invokes `$GRIPELINE build <file.dot|file.modl>`. `build` must
  print the transpiled bash to **stdout** and exit `0` for an executable graph.
- For a **non-executable** graph (§9), `build` must run the static check
  *before* emitting anything, write diagnostics to **stderr**, and exit
  non-zero (`65` for §9 static check errors; `2` for syntax/parse errors). The
  diagnostics must contain the error **code** (e.g. `E04`, `E10`, `E11`, `E12`)
  and the reason substrings the matching `errors/*.case` lists.
- Output normalization (see `normalize_bash` in `tests/run.py`): blank lines,
  `#` comment lines, and standard prologue lines (`set -euo pipefail`, etc.) are
  stripped, and each line is whitespace-trimmed, before an `expect: bash` exact
  comparison. So **boilerplate and indentation are free, but the statements must
  match exactly.** `expect: contains` only requires each pattern line to appear
  as a substring somewhere in the output. `runnable: true` cases execute your
  output under `bash` and compare stdout.
- Exit codes (§9): `0` ran/built OK; `2` parse/CLI error; `65` not executable
  (static check failed); other non-zero codes from `run` propagate the
  pipeline's status.

## CLI surface (implement all of it)

```
gripeline build  <file.dot|file.modl|url>   # print transpiled bash to stdout (harness uses this)
gripeline run    <file.dot|file.modl|url>   # transpile then exec under bash; propagate exit status
gripeline check  <file.dot|file.modl|url>   # run only the §9 static check; exit 0 or 65
  --lang=dot|modl                           # override file-extension / token format detection
  --annotate[=out]                          # also write a diagnostic-annotated .dot or .modl copy (§9, §14.3)
  --strict                                  # ordering ambiguity (multiple valid topo orders) is an error
  --infer-style                             # also read the recommended visual conventions (§3); OFF by default
```
Default prologue is `set -euo pipefail`, overridable by the graph attribute
`gl_prologue` (or `#gl prologue="…"` in `modl`). `build` should emit the
prologue (the harness strips it unless a case sets `keep-prologue: true`).

## Architecture (mirror SPEC §2 & §14)

1. **Parse** `dot` or `modl` into a common `Model` (`nodes`, `edges`,
   `clusters`, `graph_attrs`, `directed`, role-shape and line-style tables):
   - **`dot` parser:** `digraph`/`graph`, `subgraph` / `cluster_*` nesting, node
     statements, edge statements with chains (`a -> b -> c`), **ports**
     (`a:1 -> b:out`), attribute lists `[k=v, ...]`, `node`/`edge`/`graph`
     default statements that **cascade** into subgraphs (§4.4), quoted strings
     with escapes (`\"`), and comments `//`, `/* */`, `#`.
   - **`modl` parser (§14):** line-oriented syntax with `#` comments, double
     quotes, `->` edge chains, background lines, greedy attribute slot matching
     (node `size`/`color`/`shape`/`url`; edge `style`/`color`/`url`), node
     redefinition, raw source text slices (D1), fatal parse errors with exit 2
     (D5), `#gl` comment pragmas (trailing, whole-line `#gl key=val`,
     `#gl node ID …`, and `#gl begin ID …` / `#gl end` blocks), and `#h1=`
     share-link decoding.
2. **Extract** the execution graph (§3, §14): node identities + cluster nesting,
   edge endpoints + ports, node/edge operation text (`label` else id; edge label
   for Dataflow), reserved `gl_*` attrs, role-bearing shapes (`box`/`note`/`cds`
   in `dot`; `square`/`hex`/`triangle`/`diamond` in `modl`), and `dashed`
   control edges in `modl` (D3). **Ignore all rendering-only attributes**
   (`color`, `pos`, `fontname`, `size`, `url`, `background`).
3. **Resolve roles & mapping** (§4, §14.1). `gl_mapping` is file-level only
   (default `typed`); it changes only defaults. Cascading `gl_role`/`gl_edge`
   subgraph defaults (`default.role`/`default.edge` in `modl`) must work.
4. **Static check** (§9) → emit diagnostics (E01–E12) + optional `--annotate`
   copy, or proceed.
5. **Transpile** to bash via a deterministic topological order (§6.1: order is
   consistent with both control and data edges; ties broken by **source
   order**; independent nodes run sequentially in source order unless
   `gl_async=true`).

## Static checks (§9) — implement E01–E12

E01 not a `digraph` (`dot` only); E02 program node with empty operation text;
E03 two data edges into one fd without a merge; E04 undeclared data cycle;
E05 control cycle; E06 edge whose endpoint roles have no transpilation (e.g.
file→file); E07 port naming an fd on a node that has none (file/value);
E08 conflicting/duplicate value capture; E09 ambiguous/order-sensitive fd dup;
E10 bad `#gl` pragma (unknown key, bad value/port, unbalanced block, or group
id given a node role); E11 `dashed` edge in `modl` with text other than `&&`,
`||`, `;`, or empty; E12 value or function name that is not a valid shell
identifier (`[A-Za-z_][A-Za-z0-9_]*`).

## Deliverables

1. `gripeline.py` — the transpiler (stdlib only, `dot` + `modl` front ends).
2. `gripeline` — executable shim on PATH-style usage.
3. A green run of `python3 tests/run.py` under both `GRIPELINE` forms.
