# Optional CLI modes

Status: **deferred; neither mode is implemented** (reviewed 2026-11-10).
Split from the [original implementation brief](../docs/IMPLEMENTATION_PROMPT.md)
and [review item A8](../docs/MODL_REVIEW_PLAN.md).

`main()` still accepts `--strict` and `--infer-style`, stores their flags, and
does not use them. Removing their advertisement is complete; accepting a flag
does not mean that its proposed behavior exists. SPEC §14.4 calls these future
capabilities. No runtime change is part of this documentation reorganization.

- [ ] Decide whether to implement or reject the dormant flags. If implementing
  `--strict`, define which scopes and topological choices count as ambiguity
  and how the diagnostic is reported (SPEC §§6.1 and 13).
- [ ] If implementing `--infer-style`, define exactly which visual conventions
  affect execution and how they interact with explicit roles/edges (SPEC §3).
- [ ] Add failing fixtures or unit tests before implementing behavior; keep
  dot/modl parity and deterministic default output. Update SPEC, CLI docs and
  agent instructions to match the selected behavior.

Completion check: the chosen behavior is documented and tested, no accepted
flag silently promises an unavailable mode, and `make check` reports zero
failures. These optional modes do not block the completed front end or editor.
