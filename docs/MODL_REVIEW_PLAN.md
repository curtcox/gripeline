# Completed: modl front-end fixes and enhancements

**Status:** A1–A8 and B1–B10 recorded as implemented on 2026-11-07 in
gripeline and the companion modl working tree.

Reviewed 2026-11-10. This is a completion record. The current workspace's
sibling checkout lacks the standalone parser; restoring local parity
verification is tracked in [todo/MODL_PARITY.md](../todo/MODL_PARITY.md).
The original findings and proposed remedies below are retained as historical
context. The final decisions in the last section describe what shipped.
Removing the advertised no-op flags completed A8; implementing those optional
modes remains [deferred](../todo/CLI_MODES.md).

This plan comes from a review of the modl front end in
[`gripeline.py`](../gripeline.py) (written after [MODL_PLAN.md](MODL_PLAN.md)
Phases 0–3 shipped). It has two parts:

- **Part A:** bugs and lints in gripeline. These don't depend on modl changes.
- **Part B:** general-purpose modl enhancements that gripeline would use.

**Changed decision:** MODL_PLAN.md decision 1 said "modl's grammar does not
change." That no longer holds. **modl's grammar may change.** Keeping changes
upward compatible (existing valid `.modl` files keep their meaning and picture)
is a *preference*, not a hard constraint. Each Part B item below says what it
costs in compatibility.

Every finding in Part A was reproduced with a probe file at the time of review.
All 272 conformance checks passed at review time (`GRIPELINE=./gripeline
MODL_REPO=../modl python3 tests/run.py`); the findings were gaps in that earlier
suite. Regression tests were added and observed failing before the fixes.

---

## Part A — gripeline fixes

### ✅ A1. Ports on program→program edges are ignored (engine; dot and modl)

```modl
a square make
b square cat
a -> b #gl from=err          # emits: make | cat     (stdout, not stderr)
a -> b #gl from=3 to=4       # emits: gen | consume  (both ports dropped)
```

The dot twin `a:err -> b` has the same bug. The pipe branch in
`Engine.process_scope` (`# pipe / fd routing between distinct proc-ish units`)
records `pipe_succ`/`pipe_pred` without looking at `tail_port`/`head_port`.
`extra_fd_routing.case` only covers a file head.

**Original proposed fix (final semantics recorded below):** use process substitution
for any non-default fd. It is order-independent, so it fits the "routing, not
dup ordering" rule in SPEC §5:

| edge                | bash                         |
|---------------------|------------------------------|
| `a -> b`            | `a \| b` (unchanged)          |
| `a:N -> b`, N ≠ 1   | `a N> >(b)`                  |
| `a -> b:M`, M ≠ 0   | `b M< <(a)`                  |
| `a:N -> b:M`        | `b M< <(a N>&1 >/dev/null)` *(or E-error; decide)* |

`a:err -> b` together with `a -> c` then becomes `a 2> >(b) | c`. Add SPEC §5
text and fixtures (dot+modl twins). One known cost: bash doesn't wait for a
process substitution, so state that in SPEC (or add `wait` handling the way
the `tee >(…)` fan-out does).

### ✅ A2. A repeated `#gl begin ID` silently merges blocks

```modl
#gl begin g role=subshell
a square echo 1
#gl end
#gl begin g role=group       # second block overwrites the first Cluster
b square echo 2
#gl end
a -> b dashed &&             # emits { echo 1 && echo 2 }; the subshell is gone
```

**Fix:** in `handle_whole_line_pragma` (`head == "begin"`), report E10
`duplicate block id "g" (first opened on line N)` when `cid in self.clusters`.

### ✅ A3. Words in non-final chain segments are dropped with no warning

```modl
a square cat x -> b square wc -l   # runs: a | b
p square echo a->b                 # node line becomes edge p -> b; runs: p | b
```

modl drops these words too, so picture and program agree, but the author's
intent is lost. **Fix:** in `_parse_edge_line`, lint every non-final segment
with more than one word:
`line N: warning: "square cat x" after "a" is ignored (attributes go after the last id; quote text containing ->)`.

### ✅ A4. Dataflow diagnostics and `--annotate` expose synthetic ids

In the dataflow mapping, `dataflow_transform` creates `__e{k}` and
`__merge_{x}` nodes. Diagnostics then say things like
`[E04] data cycle __e2 -> __e0 -> __e2`. `--annotate` appends `__e0 red` /
`__merge_out red`, which **adds phantom nodes to the modl picture**, and it
leaves the real offending edge lines uncolored.

**Fix:** keep a map from each synthetic node to its source edge (`pos`, tail,
head, label) or source node. Messages should name the user's elements (e.g.
`edge in -> out "sort" (line 4)`). In `run_checks`, `offending_nodes` that are
synthetic should become `offending_edges` entries for their source lines.
`annotate` must never write a node id that isn't in the source.

### ✅ A5. `--annotate` splits lines differently from the parser

`annotate` uses `src.splitlines()`. The parser uses `re.split(r"\r?\n", …)`
(modl's rule). `splitlines` also breaks on `\v \f \x1c-\x1e \x85 U+2028
U+2029`, and all of these are legal inside a modl quoted string. When one
appears, every later line number shifts: in the probe, `y hex g` became
`y hex  redg` and the offending edge stayed uncolored. CRLF files are also
rewritten as LF.

**Fix:** split with `re.split(r"(\r?\n)", src)` (keep the separators) and put
the original line endings back on write. Add a fixture with a `\f` inside a
quoted string.

### ✅ A6. Quoted control text on a dashed edge is rejected

`a -> b dashed "&&"` draws `&&`. Because of D1 the raw label is `"&&"`, so
`Engine.edge_kind` returns `invalid_control` and the message shows `""&&""`.

**Fix:** for modl control-kind matching (and the E11 message), use modl's
de-quoted display text. Store it on the edge (e.g. `attrs["modl_text"]`) next
to the raw `label`. The same applies to the `solid_control` lint
(`a -> b "&&"`).

### ✅ A7. Missing lints (non-fatal)

- **Near-miss pragmas.** A comment matching `^\s*gl\b` (`# gl …`), `^GL\s`,
  `^gl[:=]`, or `^gl\S` (`#glmapping=…`) is silently treated as a normal
  comment today. In the probe, `# gl mapping=dataflow` led to a baffling E06.
  Warn: `comment looks like a #gl pragma but is ignored (write "#gl key=…")`.
- **Non-ASCII whitespace in operation text.** modl splits words on NBSP and
  other `\s` characters, but bash doesn't. So `echo<NBSP>hi` shows as
  `echo hi` and runs as the single word `echo hi` (a command that doesn't
  exist). Warn when the raw text holds whitespace other than space and tab
  outside quotes.
- **Stand-in text on a non-loop group** (subshell, group, function) is
  silently thrown away. Warn that it is display-only.

### ✅ A8. Minor cleanups

- `--strict` and `--infer-style` are parsed and documented in `--help`, but
  nothing reads them. Either implement them (SPEC §3, §13) or remove them from
  the help text.
- The E04 message always prints two nodes (`a -> b -> a`). Print the whole
  cycle.
- A whole-line `#gl key=…` inside a `#gl begin` block always goes to the graph
  (`ScopeCtx.attr_target` is never used), so `#gl role=…` there is reported as
  an "unknown graph key". Either route block keys to the open block, or remove
  `attr_target` and say in SPEC §14.2 that whole-line pragmas are always
  graph-level.
- `port_to_fd(e.tail_port) or 1` (E09 redirect bookkeeping) turns fd 0 into
  fd 1. Use an explicit `None` check.
- `tests/run.py` skips every transpile/run step unless `GRIPELINE` is set
  (141 passed / 284 skipped), which makes it easy to think the full suite ran.
  Default to `./gripeline` when it exists, or print a loud banner.

---

## Part B — modl enhancements (general purpose)

Each item is useful to modl on its own, not only to gripeline. **Compat** says
whether an existing valid file changes meaning. **gripeline** records the integration proposed at review time; the final
decisions below record the implemented choices. Grammar items change modl's hash-locked parser, so each
one needs `engine-integrity.json` regenerated, `npm test`, `npm run check`, the
browser tests, and a docs-src page.

### ✅ B1. Parser as a standalone module, with source spans (do first)

Move `lexLine`/`parseAttrs`/`parseSource` and the vocabulary into one ES module
(e.g. `js/parse.js`) that `editor.js` imports. Keep it hash-locked. Add
optional column spans per word/attribute/text (`{start, end}`) to the result.

- **Compat:** none (no grammar change).
- **gripeline:** `tests/modl_parse.cjs` imports the module instead of cutting
  `editor.js` apart between comment markers. With spans, the parity check can
  also verify the D1 raw text slices and the `--annotate` color-slot columns.

### ✅ B2. Edge endpoint labels / ports: `a[err] -> b[3]`

`[` is not a legal id character today, so `a[err]` is currently a parse error.
The new syntax gives every valid file the same meaning as before. Render the
bracket text as a small label near that end of the edge (like dot's
`taillabel`/`headlabel`). Quoting works as it does for ids: `a["2>"]`.

- **Compat:** fully upward compatible.
- **General use:** port names, ER cardinality (`user[1] -> order[*]`),
  interface names.
- **gripeline:** `a[err] -> b` is equivalent to `#gl from=err`. fd routing
  becomes visible in the picture. Keep `from=`/`to=` as aliases.

### ✅ B3. Groups drawn as boxes

Proposed syntax: a node-like line whose last word is an unquoted `{` opens a
group with that id and its attributes (shape → box style, color, text →
title). A line holding only `}` closes it. Groups nest. Membership follows
modl's line order: a node joins the innermost group where it is first
mentioned (the rule gripeline already uses). A group id used as an edge
endpoint is drawn as an edge to the box.

```modl
each dashed blue for svc in api web worker {
  build square docker build -t "$svc:$ver" "./$svc"
  push  square docker push "$svc:$ver"
  build -> push dashed &&
}
each -> tee
```

- **Compat:** a line that is only `}` is an error today, so that part is safe.
  A node line whose text ends in a bare `{` changes meaning; that should be
  rare. **Fully compatible alternative:** `[each] …` / `[/each]` (`[` is
  illegal today), which is uglier. Decide before implementing.
- **Layout:** members are laid out inside the box; the box auto-sizes.
- **gripeline:** replaces `#gl begin`/`#gl end` and the stand-in node. The
  group's text supplies the loop header (resolving MODL_PLAN §9),
  and `#gl role=` on the `{` line sets subshell/group/function. Keep
  `#gl begin` as a deprecated alias for one release.

### ✅ B4. More node shapes (vocabulary)

Add standard flowchart shapes: `note` (document, folded corner), `cylinder`
(data store), `parallelogram` (input/output), `stadium` (start/end),
`subroutine` (box with double side bars), and optionally `oval`.

- **Compat:** a node line whose *text* starts with one of these words (e.g.
  `a note to self`) would now set the shape instead. That is uncommon, but
  modl could show a one-time notice. gripeline's slot-order lint already
  flags the reverse case.
- **gripeline role table (proposed):** `note` → file (matches dot's `note`;
  settles the "is `hex` right?" question), `parallelogram` → stream (dot's
  `cds` analog), `cylinder` → file, `subroutine` → function call. Keep `hex`
  → file for compatibility.

### ✅ B5. More line styles (vocabulary)

Add `double` (and possibly `wavy`) for a second kind of flow.

- **Compat:** the same text-collision caveat as B4, for edge text starting
  with these words.
- **gripeline:** `double` = stderr (`from=err` without a pragma), so stderr
  routing shows in the picture.

### ✅ B6. Full text instead of truncation

modl truncates node text at 22 characters and edge text at 28. Shell commands
are often longer. Options: wrap onto up to N lines and grow the node; show the
full text on hover/focus; or both.

- **Compat:** renderer only.
- **gripeline:** the label-length lint gets softer or goes away.

### ✅ B7. Show source text as written

D1 means the picture shows `echo building $ver` while bash runs
`echo "building $ver"`. Add an editor display option ("show text as written",
monospace, quotes kept), stored per document like other view settings. Prefer
this over a grammar keyword: a backtick syntax would clash with bash command
substitution.

- **Compat:** none (view setting).

### ✅ B8. Layered left-to-right auto-layout

Nodes with no saved position are placed on a circle in alphabetical order, so
any `.modl` file opened from disk (no `pos`) draws a pipeline as a ring. Add a
layered DAG layout (left to right, longest-path ranks, crossing reduction) as
the default for nodes without saved positions. Saved positions still win.

- **Compat:** first-open appearance changes for diagrams without positions;
  shared links with `pos` look the same.
- **gripeline:** pipelines look like pipelines. Clusters (B3) lay out as
  nested boxes.

### ✅ B9. Highlights in the share-link fragment

Allow `#h1=…&mark=a,b,L5` (node ids and/or line numbers) to highlight
elements without changing the source. Must follow the fragment-kit URL
contracts (`vendor/fragment-kit-*/docs/contracts.md`).

- **Compat:** additive.
- **General use:** review, teaching, "look at this node."
- **gripeline:** `--annotate --link` prints a share link that highlights the
  problems, as an alternative to writing `foo.annotated.modl`.

### ✅ B10. `#gl` syntax highlighting in the editor

This was already proposed in MODL_PLAN §7. It is UI code outside the parser
block. It becomes worth doing once B2/B3 take over most pragma uses.

---

## Completed implementation sequence

| step | repo      | content                                                     | size |
|------|-----------|-------------------------------------------------------------|------|
| 1    | gripeline | A2, A3, A5, A6, A7, A8 + fixtures                           | S–M  |
| 2    | gripeline | A4 (synthetic-id mapping)                                   | M    |
| 3    | gripeline | A1 process substitutions; SPEC §5                          | M    |
| 4    | modl      | B1 parser module + spans; switch `modl_parse.cjs` over      | S–M  |
| 5    | modl      | B2 ports → gripeline reads `a[err]`                         | M    |
| 6    | modl      | B8 layered layout                                           | M    |
| 7    | modl      | B3 groups → gripeline reads `{ … }`; deprecate `#gl begin`  | L    |
| 8    | modl      | B4/B5 vocabulary → gripeline role/edge tables               | S    |
| 9    | modl      | B6, B7, B9, B10                                             | S each |

Each gripeline step keeps `python3 tests/run.py` green, and dot output stays
byte-identical except where A1 deliberately changes it. Each modl grammar step
adds parity fixtures to gripeline's `tests/` and reruns the modl parity check.

## Resolved questions

1. A1 uses process substitution, including two non-default endpoints. Bash
   does not wait for substitution children; ambiguous/shared nesting reports E09.
2. B3 uses `ID … {` / `}`. Legacy pragma blocks remain aliases for this release.
3. B4 retains `hex` as a file alias alongside `note` and `cylinder`.
4. B5 makes `double` route stderr unless an explicit port overrides it.

## Implementation decisions and verification

- A1 uses process substitutions, including both non-default endpoints. Bash
  does not wait for substitution children. Shared/cyclic nesting and a
  substituted producer with a second pipe successor report E09, avoiding
  duplicate execution or silently dropped commands.
- A8 removes the advertised no-op strict/infer-style flags; whole-line pragmas
  remain graph-level even inside a block. The harness defaults to the local shim.
- B3 uses bare braces; pragma blocks remain aliases for this release.
- B4 keeps hex as a file alias; subroutine emits a program/function call.
- B5 double routes stderr, unless an explicit port overrides it.
- B6 uses full text on hover/focus; B7 adds a persistent raw-text view.
- B10 highlights pragmas in a preview beneath the source editor.
- Grammar compatibility costs are documented in SPEC §14.4 and modl's new
  docs-src/pipeline-features.html. A checkout used for parity must include
  those companion changes. The current
  local checkout prerequisite is tracked in [todo/MODL_PARITY.md](../todo/MODL_PARITY.md);
  this record does not establish the current remote CI state.

Verification recorded on 2026-11-07: regression tests were run failing before
the Part A fixes. Final checks covered
conformance, parser parity, modl unit/integrity/generated-asset checks, native
Chromium/WebKit browser tests and shared fragment-kit contracts. Firefox could
not launch its temporary profile in this environment.
