# Plan: modl as a second gripeline source language

**Status:** proposal, not started. **Date:** 2026-11-07.

Goal: `gripeline build|run|check foo.modl` works the way it does for `foo.dot`.
The same `.modl` file still opens and renders unchanged in the
[modl editor](https://modl.hashbin.page/), and running it means exactly what the
equivalent dot diagram means: **both front ends emit identical bash for the
same program.**

Decided so far (from the Q&A):

1. gripeline-only meaning goes in **`#gl` comment pragmas**. modl's lexer drops
   comments, so pragmas are invisible to the modl renderer, the same way
   Graphviz ignores `gl_*` attributes. **modl's grammar does not change.**
2. A small set of **modl shapes and line styles carries roles by default**
   (like dot's `shape=note`/`box`). Color, size, URL and background never do.
3. Delivery is **phased**: core features first, grouping (subshells,
   functions, loops, coproc) second.

---

## 1. What modl gives us, and what it lacks

| gripeline needs            | dot has                    | modl has                                  |
|----------------------------|----------------------------|-------------------------------------------|
| directed edges             | `digraph` vs `graph`       | always directed, so E01 can't occur       |
| node operation text        | `label` / id               | node text / id                            |
| edge operation text        | edge `label`               | edge text                                 |
| roles                      | `shape`, `gl_role`         | 6 shapes, no attributes → **pragmas**     |
| edge kinds                 | `gl_edge`                  | 4 line styles → **pragmas**               |
| ports / fds                | `a:err -> b:in`            | none (`:` is a legal id char) → **pragmas** |
| clusters                   | `subgraph cluster_*`       | none → **pragma blocks** (phase 2)        |
| graph attributes           | `gl_mapping=…`             | none → **whole-line pragmas**             |
| default-attr cascading     | `node [...]`, `edge [...]` | none (block pragmas can set defaults, phase 2) |

modl facts that matter for execution:

- Text outside quotes has its whitespace collapsed, and quotes are stripped from
  the text value (`"building $ver"` → `building $ver`). There are no escapes.
- A `#` after whitespace starts a comment; `->` anywhere outside quotes makes the
  line an edge line.
- On a chain `a -> b -> c attrs`, the trailing attributes and text apply to
  **every** edge in the chain. Words after the id in earlier segments are dropped.
- A word starting `/`, `http://`, `https://`, `www.` or `mailto:` fills the URL
  slot, so `/usr/bin/wc -l` is a link plus the text `-l` (gotcha).
- Lines with parse errors are skipped and the rest still renders.
- Node lines can repeat; later attributes win; line order otherwise doesn't matter.
- modl's parser is hash-locked (`engine-integrity.json`, checked by
  `scripts/check.mjs`). This plan never touches it.

---

## 2. Decisions to confirm before coding

These are my recommendations. Each one is a single line to change if you
disagree.

**D1. Operation text is the raw source slice, not modl's de-quoted value.**
gripeline takes a node's (or edge's) text as the exact source characters from the
first text word to the start of the comment, trailing whitespace trimmed. So

```modl
echo square echo "building $ver"
```

renders as `echo building $ver` but runs `echo "building $ver"`. This keeps
SPEC §13.4 ("label text is emitted literally; gripeline never re-quotes"): you
write bash quoting the way you would in bash. If we used modl's de-quoted value
instead, shell quoting couldn't be expressed without tricks like `'"…"'`.
*Cost:* the picture shows de-quoted text. That's cosmetic, and it is what a
reader expects anyway.

**D2. Shape → role table (modl only).**

| modl shape         | role                                                  |
|--------------------|-------------------------------------------------------|
| `square`           | `program`                                             |
| `hex`              | `file`                                                |
| `triangle`         | `stream`                                              |
| `diamond`          | `value`                                               |
| `circle` (default), `none` | mapping default (`program`; `value` in dataflow) |

`#gl role=…` always wins. Leaving `circle`/`none` neutral means an
unstyled modl diagram (`a -> b -> c`) is a plain Commands pipe.

**D3. Line style → edge kind (modl only).**

- `solid` (default), `bold`, `dotted` → data edge (pipe/redirect, decided by endpoint roles, as today).
- `dashed` → **control edge**. Its kind comes from the edge text in the commands
  and typed mappings: `&&` → `and`, `||` → `or`, `;` or no text → `seq`. Any other
  text on a dashed edge is an error, so a typo can't silently change meaning.
  In the dataflow mapping, edge text is the command, so control kinds there come
  from `#gl edge=and|or|seq` only.
- `#gl edge=…` always wins.

So `make -> inst dashed &&` is drawn as an edge labelled `&&` and runs as `&&`.
The picture says what the program does.

**D4. Format detection.** `.modl` → modl, `.dot`/`.gv` → dot, and `--lang=modl|dot`
overrides. Otherwise sniff: a first token of `strict`/`digraph`/`graph` means dot,
anything else means modl.

**D5. modl parse errors are fatal.** modl draws what it can, but gripeline refuses
to run a partly-parsed program. It reports modl's own messages
(`Line N: invalid node id "x"`, `empty node id`, `malformed edge line`) with
exit 2, the same as a dot parse error.

---

## 3. The `#gl` pragma language

A pragma is a modl comment whose body starts with `gl` followed by whitespace:
`#gl …` at the start of a line or after whitespace. The comment rule is modl's
own (§"Comments"), so modl always ignores it. Inside the pragma, words are
`key=value`, and values may be double-quoted with dot-style `\"` escapes. modl
never sees this text, so pragma quoting can be friendlier than modl's.

Keys are the SPEC §10 attribute names minus the `gl_` prefix. Unknown keys are
errors (new **E10**), so typos can't silently do nothing.

### 3.1 Trailing pragmas (attach to the line's element)

```modl
log hex access.log                     #gl append=true
g   square grep 404
w   square wc -l
ver diamond                            #gl name=ver
git square git describe --tags
git -> ver                             #gl name=ver
make -> errlog                         #gl from=err
make -> make                           #gl from=err to=out    # 2>&1
a -> b -> c                            #gl async=true          # applies to both edges
gen square                             #gl raw="cmd 3>&1 1>&2 2>&3 3>&-"
```

- On a node line, the pragma sets node attributes (`role`, `name`, `append`,
  `async`, `raw`).
- On an edge line, it sets edge attributes (`edge`, `stderr`, `fd`, `name`) plus
  **ports**: `from=` is the tail port and `to=` the head port, using the same
  names as SPEC §5 (`in/out/err/0/1/2/3…`). As with modl's own attributes, a
  trailing pragma applies to every edge in a chain.
- A node can get pragmas on several lines. Later lines win key by key, which
  mirrors modl's node-redefinition rule.

### 3.2 Whole-line pragmas

```modl
#gl mapping=dataflow
#gl prologue="set -eu"
#gl node errlog role=file append=true      # address a node without restyling it
```

- `#gl key=val…` with no subject sets graph attributes (`mapping`, `prologue`, `shell`).
- `#gl node ID key=val…` sets node attributes. This is useful when the node
  has no line of its own.
- Edges can't be addressed from a whole line, because repeated edges make
  endpoint addressing ambiguous. Use a trailing pragma.

### 3.3 Block pragmas: grouping (phase 2)

```modl
#gl begin each loop="for svc in api web worker"
build square docker build -t "$svc:$ver" "./$svc"
push  square docker push "$svc:$ver"
fail  square echo "FAILED $svc"
flog  hex failures.log                   #gl append=true
build -> push dashed &&
push  -> fail dashed ||
fail  -> flog
#gl end

each -> tee                              # an edge from the group = the loop's stdout
tee square tee
blog hex build.log
tee -> blog
ver -> each dashed                       # ordering: ver before loop
```

- `#gl begin ID key=val…` / `#gl end` open and close a cluster (nestable). Keys
  are the cluster attributes: `role=subshell|group|function`, `name=`, `loop=`,
  plus `default.role=` / `default.edge=` defaults for members (SPEC §4.4
  cascading).
- **Membership:** a node belongs to the innermost block where it is *first
  mentioned* (node line or edge endpoint). This matches the dot parser's
  first-appearance rule. Lines outside every block can still style a member node.
- **An id that names a group is that group** when used as an edge endpoint,
  like dot's `-> cluster_x`. modl draws the id as an ordinary node. That's a
  feature, because modl can't draw cluster boxes, so the stand-in node is the
  group's visible handle (style it, e.g. `each big diamond for each svc`). A
  group id that is also given a role is an error.
- An unbalanced `begin`/`end` is an error (E10).

---

## 4. Implementation (gripeline repo)

### Phase 0: refactor the seam (small, no behavior change)

1. Split `build_engine` into `parse_dot(src) -> Model` and a front-end
   dispatcher. `Model` is what `Engine` already reads (`nodes`, `edges`,
   `clusters`, `graph_attrs`, `directed`), so `Engine` only needs a small
   interface change from `Parser` to `Model`.
2. Give `Engine.role_of` and edge-kind resolution a **front-end hook**: the role
   shape table and the line-style table come from the model, not a global
   (`RESERVED_SHAPE` stays the dot table).
3. Make node/edge source positions part of the model (dot: token offset; modl:
   line number) so diagnostics can say `line 7` for modl.
4. Keep gripeline a single file (`gripeline.py`, stdlib only). The modl front end
   is about 300 lines in a new section.

### Phase 1: modl core

5. **modl lexer/parser in Python**, a faithful port of modl's EBNF
   (`docs/reference.html`): comments, strings, `->` splitting, background lines,
   greedy slot matching, chains, node redefinition, implicit nodes, and the
   three error messages. It records, per element, the **raw text slice** (D1)
   and the **comment text** (for pragmas).
6. **Pragma parser** (§3.1–3.2) → `gl_*` attributes on nodes, edges and the graph;
   `from`/`to` → `Edge.tail_port`/`head_port`.
7. **Translation to `Model`:** shape → role (D2); line style + text → `gl_edge`
   (D3); text → `label` (node) or edge `label`; size, color, URL and background
   are dropped.
8. **CLI:** `.modl` detection and `--lang` (D4); modl parse errors → exit 2 (D5).
9. **New diagnostics:**
   - **E10** bad pragma: unknown key, bad value, unbalanced block, bad port name.
   - **E11** dashed edge with text other than `&&`, `||`, `;` (D3).
   - **E12** value/function name isn't a valid shell identifier. This is a latent
     bug for dot too: `Engine` emits `f"{nd.id}={label}"`, and modl ids like
     `my-var` or `ns:x` would make bad bash. Check both front ends.
   - Add these to SPEC §9.
10. **`--annotate` for modl:** write `foo.annotated.modl`. Offending *nodes* get an
    appended `ID red` line (modl's redefinition rule recolors without touching
    anything else). Offending *edge* lines are rewritten with `red` in their color
    slot (we know the slot positions). Each problem is appended as a `# [Exx] …`
    comment. The result opens in the modl editor with the problems shown in red.

### Phase 2: grouping

11. Block pragmas (§3.3) → `Cluster` objects with the right parent chain;
    group-id endpoints → cluster endpoints; member defaults. Then subshell,
    group, function, `for`/`while`/`until`/`while read` loops and coproc all
    work through the existing `Engine` paths.

### Phase 3: optional extras

12. **Share-link input:** `gripeline run 'https://modl.hashbin.page/#h1=…'`
    decodes `base64url(JSON {src,pos})` locally. No network; 256t CID links are
    refused with a message, because they need HashBin.
13. **Lint warnings** (non-fatal): a solid edge whose text is `&&`/`||` (it looks
    like control but isn't), a URL slot swallowing an absolute command path
    (`/usr/bin/x`), a label over 22 chars (modl truncates it on screen).

---

## 5. Tests (gripeline repo)

14. **Extend the `.case` format:** a case may have `=== dot ===`, `=== modl ===`,
    or both. The harness transpiles each source present and compares **each**
    against the same `=== bash ===` / `=== stdout ===`. A twin case that passes
    proves dot/modl parity for that program. The harness writes the temp file
    with the matching suffix.
15. **Validity check for modl sources** (`modl-valid`, like `dot-valid`): when
    `MODL_REPO` is set, run modl's real parser (see §7, item 20) and require zero
    errors. Otherwise fall back to gripeline's own modl parser.
16. **Twins for every existing fixture** where modl can express it: phase 1
    covers 12.1–12.8 and the core `extra_*` cases; phase 2 covers 12.9–12.11,
    subshell, coproc and subgraph role defaults. Error twins for E02–E09. E01
    can't happen in modl, so SPEC records it as N/A.
17. **modl-only cases:** raw-text quoting (D1); `#` comment rules; quoted ids;
    chain attribute and pragma propagation; node redefinition; shape table (D2);
    dashed text kinds and E11 (D3); every pragma form and E10; modl parse errors
    and exit 2; the URL-slot gotcha; E12.
18. **Parser cross-check:** a corpus of modl snippets (including modl's own docs
    examples) whose parsed model from gripeline's Python parser must equal modl's
    JS parser output (via §7, item 20). Run in CI by checking out `curtcox/modl`.

---

## 6. Docs and site (gripeline repo)

19. - **SPEC.md:** bump to Draft 0.4. §2 says there are two source languages. A new
      **§14 "modl source"** covers D1–D5, the pragma language and the role tables,
      with the §12 gallery examples shown as modl twins. §3 gets one sentence
      noting the modl exception (D2/D3), and §9 gets E10–E12.
    - **README.md:** a modl taste next to the dot one.
    - **site/build.py:** render ```` ```modl ```` blocks and `=== modl ===` sections
      as highlighted source with an **"Open in modl editor"** link (an `h1=` URL
      built in Python; no renderer needed). Rendering modl SVGs headlessly would
      need modl's browser renderer plus Playwright, which isn't worth it for now.
    - **IMPLEMENTATION_PROMPT.md:** add the modl front end so the prompt still
      describes the whole tool.

---

## 7. modl repo changes (all optional; none touch the hash-locked engine)

You had no preference here. These are my recommendations, cheapest first:

20. **Parser export script** `scripts/export-parse.mjs` (dev-only, kept off the
    `public-assets.mjs` allowlist): it slices the engine block exactly as
    `check.mjs` does, evaluates it in `node:vm`, and prints `parseSource(src)` as
    JSON for each file given. This powers items 15 and 18. **Recommended**: it's
    small and gives real parity checking.
21. **Docs page** `docs-src/gripeline.html`: "Running a diagram as a pipeline",
    covering the reserved shapes and line styles, `#gl` pragmas, and a few
    Open-in-editor examples. Regenerate `docs/` with `npm run docs` and pass
    `npm test` and `npm run check`. **Recommended** once phase 1 has shipped.
22. **Not now:** a "Show bash" panel in the editor. It needs a JS port of the
    transpiler or a hosted service, and keeping two implementations in sync costs
    more than it's worth until the language settles.

Optional, cosmetic, and only if you want it later: syntax highlighting for `#gl`
pragmas in the editor. Highlighting lives outside the hash-locked parser block,
but it is UI code and needs the browser tests.

---

## 8. Order of work and size

| step | content                                    | rough size |
|------|--------------------------------------------|------------|
| 1    | Phase 0 refactor                           | S          |
| 2    | modl parser + pragmas + translation + CLI  | M          |
| 3    | E10–E12, annotate, twins + modl-only cases | M          |
| 4    | SPEC §14, README, site                     | S–M        |
| 5    | modl `export-parse.mjs` + cross-check in CI | S         |
| 6    | Phase 2 grouping + its twins               | M          |
| 7    | modl docs page; share-link input; lints    | S each     |

Each step leaves `python3 tests/run.py` green, and the existing dot output stays
byte-identical throughout. That's the regression guard for the refactor.

## 9. Still open (can be settled during implementation)

- Is `hex` the right "file" shape? modl has nothing note-like. `triangle` is the
  other candidate.
- Should a group's stand-in node supply the loop header from its own text
  (`each diamond for svc in api web worker` plus `#gl begin each loop`), so the
  header is visible in the picture? It's nice, but it's a second way to say the
  same thing.
- Should `#gl` be case-sensitive like the rest of modl? (Proposed: yes.)
