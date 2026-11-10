# Completed work and design records

`docs/` holds completed implementation records and historical design briefs.
Outstanding work belongs in [`../todo/`](../todo/README.md). The language
authority remains [`../SPEC.md`](../SPEC.md); contributor instructions remain
in [`../AGENTS.md`](../AGENTS.md).

Reviewed against the checkout on 2026-11-10:

| record | completed scope |
|---|---|
| [Original implementation brief](IMPLEMENTATION_PROMPT.md) | The dot/modl transpiler and its conformance contract. Historical requirements are retained; unsupported optional CLI modes are now rejected. |
| [modl front end](MODL_PLAN.md) | Phases 0–3: parser, pragmas, grouping, diagnostics, annotation, links and parity tests. Later native grammar extensions supersede parts of the original design. |
| [modl review](MODL_REVIEW_PLAN.md) | A1–A8 fixes and B1–B10 enhancements, with final decisions recorded. Companion modl implementation was recorded as complete on 2026-11-07; fresh local parity evidence is recorded separately. |
| [Editor and portable execution](EDITOR_PLAN.md) | Phases 0–5 and their recorded deployment/acceptance evidence, plus the subsequent Fragment Kit 0.3.5 interface update. |
| [Unsupported CLI modes](CLI_MODES.md) | Reject `--strict` and `--infer-style` before input or execution, with regression coverage and compatibility notes. |
| [Local modl parity verification](MODL_PARITY.md) | Full conformance and unit suite passed with the real parser, vocabulary and corpus at a recorded compatible modl revision. |

Detailed briefs retain the original proposals for context. Their status notes
and final decisions distinguish shipped behavior from superseded proposals;
they are not instructions to repeat completed work. Verification and deployment
claims dated 2026-11-07 are historical evidence, not fresh checks of remote
services. Previous full revisions remain available in Git history.

When a task is finished, move its outcome, decisions, compatibility costs and
verification evidence here. For a partially completed plan, keep only remaining
work in `todo/` and link both halves. Keep repository and section READMEs close
to their subjects; this scheme does not require moving the spec or those guides.
