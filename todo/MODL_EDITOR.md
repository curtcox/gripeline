# Bash preview in the separate modl editor

Status: **deferred proposal, not scheduled** (reviewed 2026-11-10).
Split from §7 item 22 of the [modl front-end record](../docs/MODL_PLAN.md).

The original plan deferred a "Show bash" panel in the modl editor because it
would need another execution path for the compiler. The completed gripeline
editor instead runs the real Python compiler under Pyodide and already shows
Bash; see the [editor record](../docs/EDITOR_PLAN.md). That fulfills the
gripeline editor requirement. It does not implement a Bash panel in modl itself.

- [ ] Decide whether a separate modl-side panel is still wanted, or retire the
  proposal in favor of linking to the gripeline editor.
- [ ] If retained, plan the integration in `curtcox/modl`, using the existing
  Python/browser API as a candidate rather than assuming a new JavaScript port
  or hosted service is necessary.

Completion check: either record the decision to retire the proposal in `docs/`,
or ship the chosen integration with compiler parity, modl browser checks and
updated user documentation. This proposal does not reopen completed modl
syntax highlighting (review B10).
