# Orchestration-Cycle Label Trigger — Options for a Plan

**Archive status:** HISTORICAL — design analysis dated 2026-07-21, kept as design history.
**Imported:** 2026-09-15 from `nam20485/workflow-launch2/docs/` during the launcher fold (`docs/plans/fold-workflow-launch2-into-service.md` §5.6); it would otherwise have been lost in that repo's teardown (plan §9).
**Landed as:** the label-driven orchestration cycle this service now implements in `src/webhook_receiver/filters.py` and `src/webhook_receiver/prompt_builder.py`; Axis A1's skill-completion label shipped as `gh-issue-tracking:init-success`.

---

**Status:** Draft / options analysis (not finalized)
**Date:** 2026-07-21
**Scope:** `scripts/create-repo-agent-context.ps1` pipeline and the `gh-issue-tracking-init` skill
**Related:** `scripts/trigger-gh-issue-tracking-init.ps1`, `scripts/create-dispatch-issue.ps1`, `scripts/dispatch-labels.ps1`, `scripts/trigger-project-setup.ps1` (legacy), skill `gh-issue-tracking-init-global`

---

## 1. Context & Problem

The agent-context clone pipeline currently ends like this:

```
create-repo-with-plan-docs.ps1  →  cleanup-template-state.ps1  →  trigger-gh-issue-tracking-init.ps1
                                                                           │
                                                           creates a BARE dispatch issue
                                                           (body: /gh-issue-tracking-init)
                                                                           │
                                                           an agent runs the skill and
                                                           builds the plan→epic→story→task
                                                           hierarchy (+ Projects v2 board,
                                                           milestones, labels)
                                                                           │
                                                                      ◾ stops here
```

The dispatch issue is now labeled `gh-issue-tracking:direct-body` by default (the orchestrator runs the body verbatim as a prompt), with the legacy `orchestration:dispatch` available via `-Labels 'orchestration:dispatch'` — reflecting that **the `gh-issue-tracking-init` skill does not need that legacy label**, it manages its own taxonomy.

**The gap:** nothing currently *drives implementation* of the issues the skill created. The old orchestration method had a final trigger that started an implementation loop; the new method ends at skill dispatch. We need a new step, **after the skill completes successfully**, that invokes the new orchestration/implementation cycle.

### Analogy vs. divergence from the old method

| | Old method | New method |
|---|---|---|
| Trigger placement | End of repo creation (single trigger script) | After the skill runs (second phase) |
| Dispatch body | `/orchestrate-dynamic-workflow $workflow_name = project-setup` | `/gh-issue-tracking-init` (skill) **then** a new orchestration command |
| Routing label | `orchestration:dispatch` (legacy) | TBD — likely label-driven, sourced from the skill's own taxonomy |
| What it bootstraps | The whole setup in one shot | Skill builds the hierarchy; a *later* trigger starts implementation |

### Proven event-driven pattern to mirror (old method)

The old method already implements the exact pattern Design 1 proposes, via a **case-matching GitHub Actions workflow** triggered on the `issues: [labeled]` event. The chain is:

1. `orchestrate-project-setup` (started by the final dispatch issue) runs — among other things, it **creates the application plan issue**.
2. At the end of its run it adds the label **`orchestration-plan-approved`** to that plan issue.
3. The `labeled` event is matched by the **case-matching orchestration GHA workflow**, which invokes the **first step of the implementation orchestration cycle**: find the next (here, the first) phase in the plan and **create an epic** for it.
4. That step adds **`orchestration:epic-created`** to the new epic → matched → **epic implementation** runs → … and the cycle continues label-by-label.

**Implication for the new method:** the orchestration GHA + match-clause infrastructure already exists and is working. The new method does **not** need to rebuild it — it only needs a **new entry signal**: a terminal skill-completion label set by `gh-issue-tracking-init`, which the same case-matching workflow matches to start the implementation cycle. No changes are required in this repo beyond the legacy-label toggle already implemented; the orchestrator-side wiring lives elsewhere.

---

## 2. Goals & Constraints

**Goals**
- After `gh-issue-tracking-init` succeeds, start an orchestration cycle that drives implementation of the created issues.
- Obtain a reliable **result signal** from the skill (full success vs. partial/failure) before firing.
- Support **label-driven case matching** (mirrors the proven old-method pattern; keeps the orchestrator's match-clause design).
- Reuse the skill's **existing label-import method** (`ensure-labels.ps1` + `labels.json`) so triggering labels already exist post-skill — no separate bootstrap.

**Constraints**
- The skill runs as an **autonomous agent**, asynchronously from the PowerShell trigger. There is no in-process return value to `trigger-gh-issue-tracking-init.ps1`.
- Do not regress the agent-context pipeline or re-couple it to legacy labels.
- Keep dual-method support possible (the `-Labels` parameter is the precedent: default `gh-issue-tracking:direct-body`, pass `orchestration:dispatch` for the old method).

---

## 3. Design Axes & Options

### Axis A — Detecting the skill's result (the crux)

How do we know the skill finished **and** succeeded?

| Option | Signal | Pros | Cons |
|---|---|---|---|
| **A1** Completion **label** on the dispatch issue | Skill sets e.g. `gh-issue-tracking:done` (or reuses a status label) | Simple, label-native, matches "case matching"; easy to watch | Requires the skill to set it reliably on both success/failure |
| **A2** **Close** the dispatch issue | Skill closes it on success | Unambiguous terminal state; GitHub-native | Closes the audit trail; need a separate failure signal |
| **A3** **Projects v2 Status = Done** | Skill sets the board Status field | Uses the board the skill already builds | Couples trigger to board field semantics; API polling |
| **A4** **Summary comment / result issue** | Skill posts a structured comment or creates a result issue | Carries rich outcome detail (counts, errors) | More moving parts; parsing needed |
| **A5** **Detect hierarchy exists** | Trigger verifies plan/epic/story/task issues + milestones exist | Outcome-based (no skill cooperation needed) | Brittle thresholds (how many issues = "done"?); partial success ambiguous |
| **A6** **Skill chains directly** | `gh-issue-tracking-init` fires the next step at its own end | Trivial result-passing (in-process); no watcher | Couples skill to orchestration; skill must know the next phase |

> **Recommendation leaning:** **A1 (completion label) + a failure variant** as the primary signal, optionally cross-checked with **A5** for outcome validation. It is the most consistent with label-driven case matching and the least coupling.

### Axis B — Where the orchestration-trigger step lives

| Option | Location | Notes |
|---|---|---|
| **B1** Extend `trigger-gh-issue-tracking-init.ps1` | After dispatch-issue creation | Script returns immediately; would need to long-poll the skill — **not ideal** |
| **B2** **New dedicated script** `trigger-orchestration-cycle.ps1` | Separate, runs after skill completes | Clean separation; mirrors the `trigger-*` family; testable in isolation |
| **B3** Inside the skill | Skill invokes orchestration at its end | Tightest coupling (see A6) |
| **B4** **GitHub Actions** on the target repo | Workflow fires on the completion signal | Event-driven, no long-running process; needs workflow authoring |

> **Recommendation leaning:** **B2** (new `trigger-orchestration-cycle.ps1`), possibly orchestrated by a thin **B4** watcher if event-driven execution is desired.

### Axis C — Mechanism that starts the cycle

| Option | Mechanism | Notes |
|---|---|---|
| **C1** **Label-driven dispatch issue** (mirror old method) | `create-dispatch-issue.ps1` with a new command + triggering label; orchestrator match-clause picks it up | Proven pattern; consistent with "label driven case matching" |
| **C2** Direct skill/agent invocation | Call the orchestration skill directly | Skips the dispatch/audit trail |
| **C3** `workflow_dispatch` | Manual/automated GH Actions dispatch | Requires a workflow that runs the cycle |
| **C4** `repository_dispatch` | Event-driven | Needs a receiver workflow |

> **Recommendation leaning:** **C1** — reuses `create-dispatch-issue.ps1` and the orchestrator's existing match-clause architecture.

### Axis D — How the triggering label is created

| Option | Source | Notes |
|---|---|---|
| **D1** **Skill's `ensure-labels.ps1` + `labels.json`** | Add the triggering label to the skill's canonical taxonomy | Since the skill already ran, the label exists — **no separate bootstrap** (matches your instinct) |
| **D2** Separate bootstrap (legacy `Ensure-DispatchBootstrapLabel` style) | Standalone label creation | Re-introduces the bootstrap complexity we just decoupled |
| **D3** Dispatch issue carries a brand-new label created on the fly | Inline `gh label create` | Scattered; not canonical |

> **Recommendation leaning:** **D1** — add the triggering label to the skill's `labels.json` so `ensure-labels.ps1` creates it during the skill run. The trigger then only needs to *attach* it (it already exists).

---

## 4. Candidate End-to-End Designs

### Design 1 — Label-signal + new dispatch script *(recommended direction)*
```
trigger-gh-issue-tracking-init.ps1   →  bare dispatch issue (/gh-issue-tracking-init)
        │
   agent runs skill, builds hierarchy, sets label `gh-issue-tracking:done` (or `:failed`)
        │
   [watcher: B4 GitHub Action on `issues` labeled, OR poller in B2 script]
        │
   on `:done` → trigger-orchestration-cycle.ps1
        │
   create-dispatch-issue.ps1  -Body '/<new-impl-cycle-command>' -Label '<trigger-label from skill taxonomy>'
        │
   orchestrator match-clause drives implementation loop
```
- **Pros:** decoupled, label-native, reuses existing scripts, dual-method friendly, auditable.
- **Cons:** needs (a) the skill to emit the completion label, (b) a watcher/poller, (c) a chosen impl-cycle command + label.

### Design 2 — Skill chains directly (simplest, most coupled)
```
gh-issue-tracking-init skill → on success, itself calls create-dispatch-issue.ps1 to start the cycle
```
- **Pros:** no watcher, trivial result-passing, fewest moving parts.
- **Cons:** couples the skill to the orchestration phase; harder to test/disable; violates the skill's "build hierarchy only" responsibility.

### Design 3 — Board-status driven (no extra labels)
```
skill sets Projects v2 Status=Done → a scheduled/polling trigger detects it → starts cycle
```
- **Pros:** no new label taxonomy; uses the board the skill builds.
- **Cons:** polling; board-field semantics coupling; partial-success ambiguity.

---

## 5. The Skill-Result Signal — Deeper Dive

This is the part flagged as not-yet-solved ("we would need to add it in a place after the skill runs where [we] can obtain the result"). Concrete sub-decisions:

1. **Where the signal is produced.** The cleanest is a small addition to the `gh-issue-tracking-init` skill: on completion, set a terminal label on the dispatch issue — e.g. `gh-issue-tracking:done` (full success) / `gh-issue-tracking:failed` (partial/error). These labels should be part of the skill's `labels.json` so `ensure-labels.ps1` creates them (D1).
2. **Where the signal is consumed.**
   - **Event-driven:** a GitHub Actions workflow `on: issues: [labeled]` filters for the terminal label and invokes `trigger-orchestration-cycle.ps1` (or runs the dispatch inline). No long-running process.
   - **Polled:** `trigger-orchestration-cycle.ps1` (or a wrapper) polls `gh issue view` for the terminal label with a timeout.
3. **Validation before firing.** Even with a `:done` label, the trigger should optionally cross-check outcome (A5): confirm at least the plan + ≥1 epic/story issues exist, so a partially-failed skill doesn't kick off implementation prematurely.
4. **Failure path.** On `:failed` (or timeout), the trigger must **not** start the cycle — and should surface a clear error (avoid the silent-skip class of bug seen earlier).

---

## 6. Label Strategy Notes

- The new triggering label(s) should live in the **skill's `labels.json`** and be created by `ensure-labels.ps1` during the skill run — no separate bootstrap, no `.github/.labels.json` dependency (which `agent-context` doesn't ship).
- Candidate label scheme (illustrative, to be decided):
  - `gh-issue-tracking:done` / `gh-issue-tracking:failed` — skill completion signal (Axis A1).
  - `orchestration:implement` (or reuse a new `orchestration:*` value) — the triggering label the orchestrator's match clause recognizes (Axis C1/D1).
- Keep the legacy `orchestration:dispatch` import available via `-Labels 'orchestration:dispatch'` (default is `gh-issue-tracking:direct-body`) so old-method repos still work.

---

## 7. Open Questions / Decisions Needed

1. **Completion signal contract:** will the `gh-issue-tracking-init` skill be extended to set a terminal label? (Required for Design 1 / A1.) If not, fall back to A5/A6.
2. **Event-driven vs polled:** GitHub Action watcher (B4) vs. a polling script (B2)? *(Lean: event-driven — reuse the existing case-matching GHA.)*
3. **Implementation-cycle command + label:** what dispatch body and triggering label does the orchestrator's match clause expect? *(Infra exists; only a new terminal label + a new case are needed.)*
4. **Ownership of the new trigger:** new `trigger-orchestration-cycle.ps1` (B2) vs. inline in the existing workflow (B4)?
5. **Validation strictness:** how much outcome cross-checking (A5) before firing?
6. **Timeout/backoff:** how long to wait for the skill signal, and what to do on timeout?
7. **Scope boundary:** confirm no changes are needed in THIS repo (orchestrator-side wiring lives in the target repos / shared workflow infra).

---

## 8. Recommendation (light)

Pursue **Design 1**, explicitly reusing the **existing event-driven case-matching GHA** rather than building a new watcher. The only new artifacts are:

- **A terminal skill-completion label** set by `gh-issue-tracking-init` on success (and a `:failed` variant) — sourced from the skill's own `labels.json` so `ensure-labels.ps1` creates it (**A1 + D1**).
- **A new case in the existing case-matching workflow** that matches that terminal label and starts the implementation cycle — mirroring exactly how `orchestration-plan-approved` → epic creation → `orchestration:epic-created` → epic implementation already works.

This requires **no changes in this repo** beyond the `-Labels` parameter already implemented (default `gh-issue-tracking:direct-body`; `orchestration:dispatch` for legacy); it keeps each phase decoupled, reuses `create-dispatch-issue.ps1` and the proven match-clause architecture, and preserves dual-method support.

Defer coupling the skill directly to orchestration (**Design 2 / A6**) unless reusing the watcher proves unjustified.

---

## 9. Appendix — Relevant Files

- `scripts/trigger-gh-issue-tracking-init.ps1` — dispatch-issue trigger (labeled `gh-issue-tracking:direct-body` by default; pass `-Labels 'orchestration:dispatch'` for the old method).
- `scripts/create-dispatch-issue.ps1` — reusable issue creator (supports arbitrary `-Body`/`-Labels`).
- `scripts/dispatch-labels.ps1` — shared label-bootstrap helpers (legacy `Ensure-DispatchBootstrapLabel`).
- `scripts/trigger-project-setup.ps1` — legacy dispatch pattern reference (`/orchestrate-dynamic-workflow $workflow_name = project-setup` + `orchestration:dispatch`).
- `scripts/create-repo-agent-context.ps1` — pipeline orchestrator (where a post-skill hook would attach).
- Skill `gh-issue-tracking-init-global`: `ensure-labels.ps1`, `labels.json`, `ensure-issue.ps1` — the canonical label-import method and hierarchy builders.
