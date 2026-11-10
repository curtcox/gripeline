# Restore local modl parity verification

Status: **outstanding verification prerequisite** (observed 2026-11-10).
Related completed work: [modl review B1–B5](../docs/MODL_REVIEW_PLAN.md).

The local `../modl` checkout contains `js/editor.js` but lacks `js/parse.js`.
`tests/modl_parse.cjs` imports the standalone parser, and the unit corpus also
uses `js/gallery-catalog.js`, `js/legacy-examples.js` and `docs-src/`. The
Makefile auto-selects a sibling checkout based on the presence of `editor.js`,
so it selects this incompatible checkout rather than skipping parity.

Verification on 2026-11-10: default `make check` stopped at conformance with
256 passed, 88 failed and 192 skipped; the failures reported the missing
`js/parse.js`. With the optional checkout disabled, `make check MODL_REPO=`
reported 340 passed, zero failed and 196 skipped conformance checks, followed
by 49 unit tests with six modl-dependent tests skipped. Graphviz was available.

- [ ] Point `MODL_REPO` at a compatible checkout, or update the sibling checkout
  to a revision containing the completed companion changes after reviewing its
  working-tree state. Do not infer that the remote branch lacks those changes
  from this local checkout.
- [ ] Run `make check MODL_REPO=/path/to/compatible/modl` with Node installed and
  record the parser/vocabulary parity result.

Completion check: the complete suite reports zero failures with real modl
parser and vocabulary parity enabled. `make check MODL_REPO=` is available for
checks without the optional companion repository, but does not complete this
item. This item records a local verification gap, not an unimplemented parser
feature; it makes no claim about current deployment or remote CI status.
