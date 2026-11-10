# Outstanding work

Only unfinished work and explicitly deferred proposals belong here. This is an
index of remaining work, not an instruction to implement every proposal.
Completed records live in [`../docs/`](../docs/README.md).

Reviewed on 2026-11-10:

| item | status | scope |
|---|---|---|
| [Restore local modl parity verification](MODL_PARITY.md) | Outstanding verification prerequisite | The sibling checkout has `js/editor.js` but lacks the standalone parser required by the current tests. |
| [Optional CLI modes](CLI_MODES.md) | Deferred; unimplemented | `--strict` and `--infer-style` are accepted but have no effect. Their removal from advertised options is complete. |
| [Bash preview in modl itself](MODL_EDITOR.md) | Deferred proposal | The gripeline editor already has a Bash pane; a pane in the separate modl editor was not part of the completed implementation. |

The original transpiler, modl phases 0–3, modl review A1–A8/B1–B10, and editor
phases 0–5 are recorded as completed in `docs/`. Their old open questions are
resolved there rather than carried forward as tasks.

For each new item, state what is missing, its status (planned, blocked, or
deferred), dependencies and a concrete completion check. When some work ships,
move that portion into `docs/` with evidence and reciprocal links. Remove an
item from this index when all of it is complete; avoid keeping a second copy of
the backlog in completed records or agent instructions.
