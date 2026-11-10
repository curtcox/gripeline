# Open questions for the remaining todo work

Status: **awaiting product decisions** (2026-11-10).
Related proposal: [Bash preview in the separate modl editor](MODL_EDITOR.md).

No implementation-ready items remain in the current todo index. The remaining
proposal leaves the preview experience undecided. The gripeline editor already
shows Bash and diagnostics using the real Python compiler; see the
[completed editor record](../docs/EDITOR_PLAN.md). The
[CLI mode disposition](../docs/CLI_MODES.md) and
[local parity verification](../docs/MODL_PARITY.md) are complete.

## Product scope

1. **Is a separate modl preview still wanted?** Choose whether to retire the
   proposal with documentation pointing to gripeline, add an action that opens
   the current diagram in gripeline, or add a Bash pane inside modl itself.
   This choice determines whether companion application code is needed.
2. **What should the preview help users do?** Is the goal to inspect Bash,
   inspect static diagnostics, or edit the diagram and return to modl? If an
   action opens gripeline, should it use the same tab or a new tab, and where
   should the action appear in modl?

## Diagram transfer if an editor link is chosen

3. **Which state must travel with the diagram?** Specify whether to include
   unsaved source, source edits made with rendering off, fractional node
   positions, diagnostic marks and display settings. The existing editors share
   the `h1` source/position format. Decide how oversized links and load failures
   should be presented, and whether users need a way to return edited content
   to modl.

## Compiler integration if an embedded pane is chosen

4. **How should modl obtain and update the compiler?** Decide whether to bundle
   gripeline's existing Python/Pyodide worker or use another integration with
   the real compiler. Specify who updates the compiler/runtime versions and
   what offline support, initial loading behavior and failure messages are
   required. The original proposal does not settle these distribution choices.
5. **When should compilation run?** Choose an explicit preview action or
   automatic updates, including how this interacts with modl's manual rendering
   mode. Specify how parse errors and non-executable diagrams appear alongside
   the drawing.

## Turning the decisions into specified work

Dependencies: a product-scope decision, answers to the questions for the chosen
option, and a compatible `curtcox/modl` checkout if companion code is needed.

Completion check: record the chosen experience, affected repositories, state
and compiler contracts, compatibility costs and concrete acceptance checks in
the [proposal](MODL_EDITOR.md) before implementing it. Existing compiler parity
requirements and each affected repository's verification instructions still
apply. If the proposal is retired, move that decision into `docs/` and update
both indexes. Until then, keep the proposal deferred.
