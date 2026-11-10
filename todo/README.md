# Outstanding work

Only unfinished work and explicitly deferred proposals belong here. This is an
index of remaining work, not an instruction to implement every proposal.
Completed records live in [`../docs/`](../docs/README.md).

Reviewed on 2026-11-10:

No implementation-ready items remain. The [open questions](OPEN_QUESTIONS.md)
capture the decisions needed to specify the remaining proposal.

| item | status | scope |
|---|---|---|
| [Bash preview in modl itself](MODL_EDITOR.md) | Awaiting product decisions | Choose whether to retire the proposal, link to gripeline, or embed a preview; see the [open questions](OPEN_QUESTIONS.md). |

The original transpiler, modl phases 0–3, modl review A1–A8/B1–B10, and editor
phases 0–5 are recorded as completed in `docs/`. Their old open questions are
resolved there rather than carried forward as tasks.
The optional CLI modes were resolved by
[rejecting the unsupported flags](../docs/CLI_MODES.md).
[Local modl parity verification](../docs/MODL_PARITY.md) passed against a
separate compatible checkout; the older sibling still needs an explicit
`MODL_REPO` override.

For each new item, state what is missing, its status (planned, blocked, or
deferred), dependencies and a concrete completion check. When some work ships,
move that portion into `docs/` with evidence and reciprocal links. Remove an
item from this index when all of it is complete; avoid keeping a second copy of
the backlog in completed records or agent instructions.
