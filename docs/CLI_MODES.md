# Reject unsupported CLI modes

Status: **complete** (2026-11-10). Resolves the optional CLI modes todo split
from the [original brief](IMPLEMENTATION_PROMPT.md) and
[review A8](MODL_REVIEW_PLAN.md). Remaining work is indexed in
[todo/README.md](../todo/README.md).

The CLI previously accepted `--strict` and `--infer-style`, stored their flags,
and never used them. The selected disposition is to reject both modes rather
than define new ordering ambiguity rules or infer execution from visual style.
Source ordering stays deterministic, and explicit roles and edges retain their
existing meaning. SPEC §§3, 6.1, 13 and 14.4 now consistently describe this.

Both flags report `gripeline: <flag> is not implemented` on stderr and exit 2
before reading input, emitting Bash, writing annotations, or executing commands.
This applies to build, check, run and implicit build, including options after
the input. Compatibility cost: scripts that supplied either ignored flag now
fail and must remove it. No graph grammar or generated Bash changes.

Regression tests in `tests/test_units.py` cover both source languages, command
forms and option positions, and assert that input and execution are untouched.
Written first, both tests failed with 24 subtest failures because the old CLI
returned 0. Full-suite verification is recorded in
[the modl parity record](MODL_PARITY.md).
