# Editor and run-anywhere plan

Status: **implementation in progress** (2026-11-07). Compiler, editor, native
installers and the Apptron overlay are committed and pushed. t256 v0.1.0 and
the immutable Apptron runtime are released. HashBin publishing and dedicated
hosting remain in progress. GitHub Pages recovered from its stale deployment lock;
Apptron’s verified runtime is live at `https://apptron.hashbin.page/`.

| phase | current implementation | remaining acceptance work |
|---|---|---|
| 0 | Pure API, stdin/CID inputs, Windows Bash discovery, installers and launchers | Linux, macOS and Windows CI pass, including native CID round trips and Windows installer execution |
| 1 | Responsive editor, real Python worker, shared modl renderer, Graphviz, review dialog, share/QR, draft recovery, verified offline cache | Chromium and WebKit pass locally; Firefox passes all nine original tests in Linux CI. A long-gallery-name phone layout regression was reproduced and fixed |
| 2 | t256 producers/sinks, canonical CID validation, guard, E14, twin fixtures and spec | Complete |
| 3 | Verified linux/386 t256, released overlay, exact checked compiler and local CID store in inert txtar handoff | Nine real VM boot tests and four origin-isolation tests pass. All six portable gallery executions pass in the VM. Public runtime lock and manifest verify successfully; the editor enables handoff only after that verification |
| 4 | Verified CID loading, typed modl envelopes, CID local commands, hosted Publish UI, large Apptron snapshot fallback, public-asset hosting and source-only migration | Register the actual public client ID; deploy canonical editor and mirror recovery notice; real paid-save acceptance requires the owner’s signed-in session |
| 5 | requires/env, missing-tool guards, --portable advice, command inventories and environment badges | All three native CI platforms and the real Apptron VM pass the portable gallery, local saved-envelope execution and tamper rejection |

Verification: `make check` (89 fixtures, 47 unit tests), site build, vendored
asset verification, 10 Node contract tests and 26 passing Chromium/WebKit tests cover fixture parity, sharing, offline,
review, phone controls and mocked HashBin saves including oversized Apptron snapshots. Graphviz and sibling modl parity tools were available locally;
no optional checks skipped locally. In native CI, macOS/Windows use the documented
Graphviz brace-check fallback; Windows skips the POSIX executable-stub unit,
with its native t256 run covered separately. Firefox fails to start on this Mac before loading
an application; Linux CI verifies it independently. HashBin passes 1,003 unit
tests and lint with zero errors; real cross-origin draft transfers pass for gripeline
and the three existing recovery consumers. Modl passes
33 unit tests, native Chromium zoom/drag/export checks and all 17 shared
Fragment Kit contracts. Apptron passes 36 unit tests and its build checks.

Goal: the gripeline site lets you **construct, view, and run** gripeline
diagrams.

- You edit and view them the way you edit and view modl diagrams on
  <https://modl.hashbin.page/>.
- You run them from a local filesystem on macOS, Linux, or Windows, given the
  right tools.
- You run them in the browser under <https://apptron.hashbin.page/> (the existing canonical Apptron host).
- `t256` works in every one of those places and is the tool for writing
  pipelines that move data the same way everywhere.

Not every diagram has to run everywhere. A diagram can declare what it needs,
and the editor shows where it can run.

## Decisions already made

| # | decision | source |
|---|---|---|
| D1 | The editor's code lives **in this repo** (`web/`). It takes parts from other repos (modl, apptron, Fragment Kit, Pyodide), pinned by commit and hash. | user |
| D2 | It deploys to **GitHub Pages or a HashBin-managed domain**, depending on the security requirements in §6. | user |
| D3 | The browser transpiles by running the **real `gripeline.py` under Pyodide**. There is no JS port, so there's nothing to keep in parity. | user |
| D4 | The plan includes changes to **curtcox/apptron** (a gripeline overlay) and **curtcox/256t.org** (a `linux/386` t256 build). | user |
| D5 | t256 is first-class in four ways: it's on `PATH` everywhere, `t256:` file nodes exist, `gripeline run` resolves CID share links with it, and pipelines ship by CID. | user |

## 1. Where things run

| environment | transpile | execute | t256 |
|---|---|---|---|
| Editor page (Pages or hashbin.page) | Pyodide + `gripeline.py` | **never** (it shows the bash and the static check only) | the browser fetches and verifies CIDs to load diagrams |
| Apptron VM (i386 Alpine) | `python3 gripeline.py` in the VM (and Pyodide in the editor) | `bash` in the VM | `t256-linux-386` in the overlay. Offline, it uses inline CIDs plus a local store; with a user-configured relay, it uses the network. |
| macOS / Linux | `gripeline.py` | `bash` | native binary |
| Windows | `py gripeline.py` | Git for Windows `bash` (the supported path). WSL works if you run gripeline *inside* WSL. | `t256.exe` (also callable from Git Bash) |

The page itself can't run bash. "Run" in the editor always hands off, either to
apptron or to a command you copy and run locally. Following the modl and
apptron convention, opening a link never runs anything automatically.

## 2. Changes to `gripeline.py` (phase 0, prerequisites)

All of these are standard library only, tested by `make check`, and
spec-documented where they change behavior.

1. **Pure API for the browser.** Add
   `gripeline_api(src: str, lang: str | None) -> dict` returning
   `{lang, bash, problems:[{code,message,line,node}], warnings, marks}`. It does
   no I/O and no `sys.exit`. `main()` calls it. Pyodide calls only this, so the
   page and the CLI share one code path. Unit tests compare it against the CLI
   for every fixture.
2. **More kinds of input:** `-` (stdin), `t256:CID…` / bare CID, and
   `https://modl.hashbin.page/#CID`. CID inputs shell out to `t256 load`, which
   verifies the content. Then the `hashbin-diagram` JSON envelope
   (`{format:"hashbin-diagram",version:1,src,pos}`, ported from modl's
   `fragment-config.js`) is unwrapped. Without `t256` on `PATH`, the input fails
   with exit 2 and an install hint. This replaces today's "256t CID share links
   require network access" error.
3. **A bash locator that works on Windows.** `run` currently does
   `subprocess.run(["bash", tmpfile])`. Change it to:
   - honor `GRIPELINE_BASH`, then `bash` on `PATH`, then the standard Git for
     Windows locations;
   - pass the temp path with forward slashes;
   - when the only `bash` found is the WSL launcher (`System32\bash.exe`),
     refuse with a clear message instead of running a path that WSL can't see.

   The script stays in a temp file, not on stdin, because the pipeline may need
   stdin itself.
4. **Windows shims.** Add `gripeline.cmd` and `gripeline.ps1` next to the bash
   shim, and an `install.sh` / `install.ps1` pair modeled on t256's that puts
   `gripeline.py` plus its shim on `PATH`.
5. **CI matrix.** The `test` job adds `macos-latest` and `windows-latest`
   (Git Bash). Fixtures whose `run` check relies on GNU-only behavior get an
   explicit skip reason, not a silent pass. Report those skips like the
   existing optional-tool skips.

## 3. t256 in the language (phase 2, SPEC change)

This is new behavior, so it needs `SPEC.md` (§ on file nodes and §14 pragmas)
and twin dot/modl fixtures, written first so we can watch them fail.

- **Source node:** a file/data node whose label is `t256:CID[.ext]` (or a bare
  CID with `#gl t256`) produces `t256 load CID` as its producer. It reads like a
  file, but there's no file on disk. Where a plain file would emit `< path`,
  this emits `t256 load CID | …`. In fan-in positions it emits
  `<(t256 load CID)`.
- **Sink node:** a file node labeled `t256:` (no CID) consumes its input with
  `t256 save -f t256 -` and prints the reference on stdout. Later stages or the
  user can pick it up from there.
- **Guard:** when a pipeline uses t256 nodes, the emitted bash starts with
  `command -v t256 >/dev/null || { echo "gripeline: t256 not found" >&2; exit 127; }`.
- **Static check E14:** a malformed `t256:` reference. This is a syntactic check
  only (base64url alphabet and length rules from `cid/cid.go`, ported, stdlib
  only). It never touches the network.
- **Portability vocabulary in the docs.** Show t256 as the portable
  replacement for `curl`/`wget`/`Invoke-WebRequest` (`load`),
  `sha256sum`/`shasum`/`certutil` (`cid`, `verify`), and ad-hoc uploads
  (`save`). Those are where macOS, Alpine busybox, Git Bash and Linux differ
  most.

**Compatibility cost:** a label that happens to start with `t256:` changes
meaning. Today it would be a file literally named `t256:…`, which is very
unlikely and isn't a valid filename on Windows anyway. Say so in the spec
change.

## 4. Declaring where a diagram can run (phase 5)

Add a `#gl requires` pragma (dot: a graph attribute `gl_requires`). It lists
tools such as `#gl requires jq python3 t256` and, optionally,
`#gl env linux macos windows apptron`.

- The emitted bash checks each tool up front with `command -v` and exits 127
  with a list of what's missing, so a failure isn't a confusing one halfway
  through the pipeline.
- The editor shows a badge per environment (runs / needs X / not supported) and
  disables Run targets that can't work.
- An optional `--portable` warning (not an error) flags command words outside a
  documented portable set: POSIX utilities common to busybox, macOS, and Git
  Bash, plus t256. This is advice, not a rule, so it never fails `check`.

## 5. The editor (`web/`, phases 1 and 4)

### Layout

```
web/
  index.html          editor shell
  src/app.js          wiring: source ⇄ diagram ⇄ bash ⇄ diagnostics
  src/transpile.js    Pyodide worker: loads gripeline.py, calls gripeline_api
  src/run-targets.js  "Run in Apptron", "Run locally", downloads
  src/dot-render.js   dot → SVG via vendored Graphviz wasm (@viz-js/viz)
  vendor/             pinned copies; vendor.lock.json = {repo, commit, path, sha256}
  tests/              Playwright (Node dev-only; make check stays Python-only)
scripts/vendor.py     fetch + verify vendored files from vendor.lock.json (stdlib)
```

`site/build.py` copies `web/` and the current `gripeline.py` into
`_site/editor/`, so the editor always transpiles with the gripeline that the
site's tests just checked. The spec and test pages get an **Edit** link that
opens their diagram in the editor, alongside the existing modl link.

### What it borrows

| from | what | notes |
|---|---|---|
| curtcox/modl | `js/parse.js`, the SVG renderer, `diagram-features.js`, the `h1=` share format, the `hashbin-diagram` envelope | The renderer is currently inside `editor.js`'s startup closure. **modl change needed:** extract it to `js/render.js` exporting `renderDiagram(svg, model, opts)`, and have modl's own editor import it. Then the vendored copy matches modl byte for byte. |
| Fragment Kit v0.3.4 (via modl) | shell, mobile tabs, share/QR dialogs, `LocalDrafts`, `HashBinPanel`, offline client | same pinned version modl and apptron use |
| curtcox/apptron | `lz-string` (for `?compressed=` links), the txtar writer | |
| Pyodide (pinned, self-hosted) | CPython in wasm | Self-hosted rather than from a CDN, so offline use and hash verification work like modl's. The core is about 10 MB and lazy-loaded on first transpile. The CSP needs `'wasm-unsafe-eval'`. |
| @viz-js/viz (pinned) | Graphviz wasm for dot diagrams | only loaded for dot sources |

### Features

- **Panels:** Source | Diagram | Bash | Diagnostics, with split, tab, and mobile
  layouts from Fragment Kit. It edits both languages, sniffed by `detect_lang`
  as in the CLI. modl gets the modl renderer and draggable positions. dot gets
  Graphviz layout and is read-only in the diagram pane.
- **Live check:** on every edit (debounced, in a worker), it shows the bash or
  the `E##` diagnostics. Offending nodes and edges are highlighted using the
  same `marks` that `--annotate --link` produces today.
- **Share links:** `#h1=` stays compatible with modl, so a gripeline link
  opens in modl and the reverse. CID links (`#<CID>`) load through HashBin with
  verification.
- **Run → Apptron:** builds a txtar snapshot and opens
  `https://curtcox.github.io/apptron/?compressed=…` in a new tab, where the
  user presses Run (§7). If the link would be too long, it offers to save to
  HashBin and opens `…/apptron/#CID` instead.
- **Run → Locally:** shows the bash first, then commands to copy for
  bash/zsh, PowerShell, and cmd:
  - `gripeline run 't256:CID'` once the diagram is saved by CID. t256 verifies
    that you run exactly what you reviewed, and the command has no quoting
    differences between shells.
  - `gripeline run 'https://…#h1=…'` as the offline fallback.
  - Download `.sh` / `.modl` / `.dot`.
- **Gallery:** `tests/cases` twins and the §12 examples, plus new
  cross-platform examples built on t256.

## 6. Hosting and security (decides D2)

The deciding fact: **`curtcox.github.io` is one browser origin for every
Pages project, including apptron, which runs untrusted VM code there.**
apptron's own docs say that, and its separate VM origin is prepared but
disabled.

| condition | host |
|---|---|
| The editor holds no credentials, stores nothing that later feeds execution without review, and saves to HashBin only through the HashBin Publish redirect | GitHub Pages is acceptable |
| Any of: HashBin save (needs a registered client with a fixed redirect URI), remembered drafts that "Run locally" copies, t256/HashBin settings, a relay setting | dedicated origin: **`gripeline.hashbin.page`**, deployed by HashBin's owned-app deployment tool like modl |

Plan:

- **Phases 1–3 ship on Pages** at `/gripeline/editor/`. Drafts are marked as
  unverified on load, and the local-run command is always regenerated from the
  visible source, never from storage.
- **Phase 4 (HashBin save and CID links)** registers the client and makes
  `gripeline.hashbin.page` canonical. Pages keeps the spec, the tests, and a
  mirror editor that links to the canonical one, using modl's move-saved-work
  pattern.

Invariants on every host:

- Links never auto-run.
- The editor never holds HashBin credentials.
- Shared links carry no relay or network settings.
- The local-run UI always shows the bash before the copy button.

## 7. apptron integration (phase 3, D4)

**curtcox/256t.org**

- Add `linux/386` to the `t256-cli.yml` release matrix (`CGO_ENABLED=0`, so it
  builds trivially), plus a test leg. Cut a release.

**curtcox/apptron**

- New overlay `examples/overlays/gripeline.packages` with `bash`, `python3`, and
  `coreutils`. Teach `scripts/build-overlays.sh` to add one **pinned, verified
  binary**: `t256-linux-386` at a fixed release, checked against that release's
  `SHA256SUMS`, installed to `/usr/local/bin/t256`. Overlays rebuild with the
  runtime, so this lands through apptron's normal Runtime release workflow
  (CI time and a new runtime commit are the costs).
- A `gripeline.txtar` gallery example.

**The snapshot the editor generates:**

```
# apptron snapshot v1
overlay: gallery/gripeline
-- .apptron/envrc --
cd /project
export T256_CONFIG=/project/.t256/config.json
python3 gripeline.py check pipeline.modl && echo "Try: python3 gripeline.py run pipeline.modl"
-- pipeline.modl --
…the diagram…
-- gripeline.py --
…the exact gripeline.py the editor used (~100 KB of the 1 MiB cap)…
-- .t256/config.json --
{ local directory provider at /project/.t256/store, first in the source list }
-- .t256/store/<CID> (base64) --
…content of each non-inline CID the diagram references…
```

- Shipping `gripeline.py` in the snapshot keeps the VM's transpiler identical to
  the editor's without rebuilding the overlay for each gripeline change.
- **t256 offline:** the VM has no network by default. Inline CIDs (≤64 bytes)
  always work. For larger referenced CIDs, the editor fetches and verifies them
  in the browser and embeds them in the snapshot's local store, within the
  1 MiB cap. Past the cap, it says so and suggests a relay, which apptron
  already supports under More → Network.
- **Same-origin note:** the editor and apptron share `curtcox.github.io`, but
  the editor only *links* to apptron (new tab). There's no iframe, so apptron's
  COOP/COEP service-worker setup is untouched.

## 8. Phases

| phase | delivers | repos | done when |
|---|---|---|---|
| 0 | `gripeline_api`, stdin/CID inputs, Windows bash locator and shims, installers, macOS/Windows CI | gripeline | `make check` is green on 3 OSes, and `gripeline run t256:CID` works with a stub t256 in tests |
| 1 | Editor MVP on Pages: modl/dot editing, Pyodide transpile, diagnostics, `h1=` links, Run locally (h1 + download) | gripeline, modl (`render.js` extraction) | Playwright: every fixture's bash in the page equals the CLI's; modl's own tests still pass |
| 2 | `t256:` source/sink nodes, E14, spec text, twin fixtures | gripeline | fixtures added first and seen failing, then passing |
| 3 | `linux/386` t256 release; `gallery/gripeline` overlay; Run → Apptron with an embedded t256 store | 256t.org, apptron, gripeline | apptron boot check runs a gripeline twin fixture in the VM and gets the expected output |
| 4 | HashBin save/load, CID links, `gripeline run t256:CID` copy command, canonical `gripeline.hashbin.page` | gripeline, hashbin.org (app registration and deploy) | the save → copy → run round trip verified on macOS, Linux, Windows |
| 5 | `#gl requires` / `#gl env`, environment badges, `--portable` advice, cross-platform t256 gallery | gripeline | each gallery example's badges are correct, checked by running it in each CI OS and in apptron |

Phases 0 and the modl renderer extraction can proceed in parallel. Phases 2 and
3 depend on 0. Phase 4 depends on 1.

## 9. Open questions

1. **`gripeline.hashbin.page`**: is that the right name, and is the HashBin
   owned-app deploy tool available for a new app? The current upstream `hashbin.org` checkout provides it; the older local checkout did not.
2. **Is the modl renderer extraction acceptable in modl**, or should gripeline
   vendor `editor.js` and drive it through `globalThis.ModlApp`? The second
   avoids a modl change but makes the editor modl's UI plus extras rather than
   gripeline's own.
3. **`t256:` sink output:** should it print the reference on stdout (so it can
   feed later stages), or on stderr / to a named variable, so the pipeline's
   stdout stays the data?
4. **Windows support level:** is Git Bash only acceptable, or is
   "run gripeline inside WSL" also a supported, CI-tested configuration?
5. **Pyodide size:** is a roughly 10 MB first-transpile download acceptable on
   phones, or should the editor show the bash pane only on demand?
