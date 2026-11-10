# Restore local modl parity verification

Status: **complete** (2026-11-10). Related completed work:
[modl review B1–B5](MODL_REVIEW_PLAN.md). Remaining proposals are indexed in
[todo/README.md](../todo/README.md).

The sibling `../modl` checkout was clean at
`bde3a23` but lacked `js/parse.js`, `js/gallery-catalog.js` and
`js/legacy-examples.js`. The Makefile detects `js/editor.js`, so this old
checkout is selected automatically even though it cannot run current parity
checks. This was a local verification gap, not a missing parser feature.

After reviewing the sibling state, checked the remote and cloned a separate
compatible checkout into `/tmp/gripeline-modl-parity-20261110`, leaving the
sibling unchanged. Verified against `curtcox/modl` revision
`afa751117cd2d8d8bd25022ade0f1d7762212af5`, containing the standalone parser,
vocabulary and example corpus. No companion source changes were needed.

Verification on 2026-11-10:

```bash
make check MODL_REPO=/tmp/gripeline-modl-parity-20261110
```

- Conformance: **344 passed, 0 failed, 192 skipped**, across 89 cases.
- Units: **51 passed, no skips**, including real parser/vocabulary parity,
  modl's gallery/docs corpus, lexer edge cases, quoting and annotation tests,
  and the [unsupported CLI mode regressions](CLI_MODES.md).
- Graphviz `dot` and Node were installed; neither optional tool was skipped.
  Conformance skips are inapplicable lint/run checks for non-exact or
  non-runnable fixtures, including intentional error cases.

The temporary checkout may be removed by the operating system. To reproduce,
use a checkout at the verified revision (or another compatible revision) and
set `MODL_REPO` explicitly. Plain `make check` still selects the older sibling
until it is updated or the environment supplies a compatible `MODL_REPO`.
Disabling optional parity with `MODL_REPO=` does not establish parser parity.
This evidence describes the local suite, not deployment or remote CI status.
