# AGENTS.md — working on gripeline

This is the shared guide for coding agents (Claude Code, Codex, Gemini CLI,
Cursor, Devin, Copilot, …) and people. `CLAUDE.md` and `GEMINI.md` only import
this file, so edit this one.

gripeline transpiles Graphviz `dot` files and [modl](https://modl.hashbin.page/)
diagrams into `bash`. The same file that draws a picture also runs as a
pipeline.

## Verify your change

```bash
make check                 # conformance fixtures + unit tests (same as CI's test job)
make test FILTER=fanin     # only fixtures whose name contains "fanin"
make units                 # unit tests only
```

`make check` takes about 20 seconds and needs only `python3` and `bash`.
Without `make`, run the same commands directly:

```bash
GRIPELINE='python3 gripeline.py' python3 tests/run.py -q
python3 tests/test_units.py
```

A change is done when `make check` reports `0 failed`. Some checks skip
instead of failing when an optional tool is missing. Report which ones
skipped:

| optional tool | without it | with it |
|---|---|---|
| Graphviz `dot` | `dot-valid` falls back to a brace check | `dot -Tcanon` validates every `=== dot ===` |
| `node` + `../modl` (a `curtcox/modl` checkout) | modl parity checks skip | gripeline's modl parse must match modl's own parser exactly |

The Makefile sets `MODL_REPO=../modl` automatically if that checkout exists.
CI ([`.github/workflows/pages.yml`](.github/workflows/pages.yml)) installs
both tools and runs on Python 3.12, so keep code compatible with 3.12.

Other useful commands:

```bash
python3 tests/run.py --list                    # list every fixture
./gripeline build path/to/file.modl            # print the generated bash
./gripeline check path/to/file.dot             # static check only (exit 0 or 65)
./gripeline build --annotate=out.modl in.modl  # write a copy with diagnostics marked
python3 site/build.py                          # build the Pages site into site/_site/
```

## Hard rules

1. **Python standard library only.** No `pip install`, no `pydot` or
   `graphviz` packages, no `requirements.txt`. The `dot` and modl parsers are
   hand-written on purpose.
2. **[SPEC.md](SPEC.md) is normative.** The bash a graph produces *is* its
   meaning. If you change behavior, update the spec in the same change.
3. **dot and modl must agree.** Twin fixtures (cases with both `=== dot ===`
   and `=== modl ===`) must produce identical bash.
4. **Never edit a fixture just to make it pass.** `tests/cases/**/*.case` is
   the spec in executable form. If you think a fixture is wrong, say so and
   explain why. Don't change it quietly.
5. **Every bug fix adds a fixture** (or a unit test in
   [`tests/test_units.py`](tests/test_units.py) when a `.case` file can't
   express it). Write it first and watch it fail.
6. **gripeline's modl parser must match modl's parser** (`js/editor.js` in
   `curtcox/modl`) token for token. Port modl's behavior; don't reinterpret
   it.
7. **modl's grammar may change.** Keeping existing `.modl` files valid with the
   same meaning is preferred but not required. Say what any grammar change
   costs in compatibility.

## Repository map

| path | what it is |
|---|---|
| [`gripeline.py`](gripeline.py) | the whole transpiler: one file, about 2,300 lines |
| [`gripeline`](gripeline) | bash shim: `exec python3 gripeline.py "$@"` |
| [`SPEC.md`](SPEC.md) | language spec (Draft 0.4). §9 = static checks, §12 = example gallery, §14 = modl front end and `#gl` pragmas |
| [`tests/run.py`](tests/run.py) | conformance harness. Runs every `tests/cases/**/*.case` |
| [`tests/README.md`](tests/README.md) | **`.case` file format**, expect modes, and the checks. Read it before adding fixtures |
| [`tests/cases/`](tests/cases/) | success fixtures; names start with the SPEC section (`12_04_…`), `modl_…`, `extra_…`, or `run_…` |
| [`tests/cases/errors/`](tests/cases/errors/) | one fixture per static-check error (`E01_…`–`E13_…`, `modl_parse_…`) |
| [`tests/test_units.py`](tests/test_units.py) | stdlib `unittest`: annotate, id quoting, sniffing, share links, modl parity corpus |
| [`tests/modl_parse.cjs`](tests/modl_parse.cjs) | runs modl's real parser from `$MODL_REPO` for parity checks |
| [`site/build.py`](site/build.py) | builds the GitHub Pages site (spec with rendered SVGs + per-test pages) |
| [`MODL_REVIEW_PLAN.md`](MODL_REVIEW_PLAN.md) | **current backlog**: Part A (gripeline bugs A1–A8), Part B (modl enhancements B1–B10). Not implemented yet |
| [`MODL_PLAN.md`](MODL_PLAN.md) | design record for the modl front end. Implemented. Decision 1 is superseded |
| [`IMPLEMENTATION_PROMPT.md`](IMPLEMENTATION_PROMPT.md) | the original brief used to build the transpiler. **Historical**: the work is done. Don't treat its "You are implementing…" as your task |

## Code map of `gripeline.py`

Sections are marked by `# ====` banners. Use `grep -n '^# ====' -A1 gripeline.py`
to find them. In pipeline order:

1. **Tokenizer (dot)**: `Tok`, `tokenize`.
2. **AST / model**: `Node`, `Edge`, `Cluster`, `Model`, `GripError`. The modl
   vocabulary tables (sizes, shapes, colors) must match modl's `js/editor.js`.
   `test_vocabulary_matches_modl` enforces this.
3. **Parser (dot front end)**: `Parser`, `parse_dot`. Handles subgraphs,
   ports, and attribute defaults that cascade.
4. **Parser (modl front end)**: `_lex_modl_line`, `_modl_parse_attrs`,
   `ModlParser`, `parse_modl`. These are ports of modl's lexer. The `#gl`
   pragma parsing is here.
5. **Port / fd helpers**: `port_to_fd`.
6. **Engine**: `Engine` resolves roles (`role_of`, `edge_kind`), runs the §9
   checks (`run_checks`, error codes `E01`–`E13`), and emits bash
   (`transpile`, `dataflow_transform`, `process_scope`, `render_cluster`).
   Most semantic bugs are here.
7. **Small utilities**: `UnionFind`, `topo` (ordering is stable and ties go
   to source order), `find_cycle`.
8. **Front-end dispatcher**: share-link decode/encode, `detect_lang`,
   `parse_source`, `build_engine`, `emit_diagnostics`, `annotate`, `main` (CLI).

## Contracts that are easy to break

- **Exit codes:** `0` OK. `2` parse or CLI error. `65` the static check failed
  (not executable). `run` passes through the pipeline's own exit status.
- **Diagnostics** go to stderr and contain the error code (`E04`, …). Error
  fixtures match on the code and on substrings of the message, so rewording a
  message can break them.
- **`build` emits nothing on stdout** when the static check fails.
- **Output comparison** strips blank lines, `#` comments, prologue lines, and
  leading and trailing whitespace on each line (`normalize_bash` in
  `tests/run.py`). Formatting is free, but the statements themselves must
  match exactly.
- **Determinism:** the same input must always give byte-identical output.
  Don't iterate over sets or unordered dicts when emitting.

## Common tasks

- **Fix a bug:** reproduce it with a small `.dot` or `.modl` file and
  `./gripeline build`. Add a fixture that fails, fix the bug in `Engine` or the
  front end, then run `make check`. If you're fixing a `MODL_REVIEW_PLAN.md`
  item, mark it done there.
- **Add a fixture:** copy the closest existing `.case`. No registration needed.
  Prefer twin dot+modl cases. Use `expect: bash` when the output is
  deterministic, and `contains` for implementation-defined formatting.
- **Add a static check:** pick the next `E` code. Add it to the §9 table in
  `SPEC.md`, add it to `Engine.run_checks`, and add an `errors/E##_….case`.
- **Change the CLI:** update the module docstring in `gripeline.py`, the CLI
  block in `README.md`, and this file.
- **Docs:** keep `README.md`, `tests/README.md`, and `site/README.md`
  consistent with any behavior you change. The site is built from them in CI.

## Git

- Commit subjects use the imperative mood and summarize the change (for
  example "Match modl's parser exactly, fix engine scoping bugs"). The body
  explains what changed and why.
- `main` deploys the Pages site on every push. Don't push unless asked.
- `site/_site/` is build output and is gitignored. Never commit it.
