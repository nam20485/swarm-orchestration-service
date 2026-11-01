# Revert new rules reading enforcement changes

**Status:** EXECUTING (owner go 2026-11-01) — investigation complete, dry-run verified.
**Date:** 2026-11-01 · **Target base:** `origin/development` @ `6aed9c8` · **Branch:** `mn/revert-rules-enforcement`

> **Base note (found at execution time):** local `development` sits one commit ahead of `origin/development` — `70b315e` (opencode.jsonc v2 migration, committed 2026-11-01 12:36, unpushed owner/parallel-session work). The revert branch is cut from `origin/development` so the PR carries only the revert; `70b315e` is untouched and merges/rebases independently (its only file, `.opencode/opencode.jsonc`, is disjoint from the revert delta). The dry run below was performed at `70b315e` and is equally valid at `6aed9c8` for the same reason.
>
> **Scope note:** part of the rollout was deployed **machine-scope, outside the repo** (per the rollout memory entry): the qwen PreToolUse gate `~/.qwen/hooks/rules-metrics/gate-consequential-git.sh` (live in **warn** phase), the registry `critical` key, and `settings.json` PreToolUse wiring. Those are not "merged into development" and are **not** reverted here; disabling them is an owner decision flagged in the report.

## Task (verbatim)

> I want to revert all of the new rules reading enforcement changes that were megred into `development`, i.e. PR 54 and 55.
>
> It should be roughly these commits:
>
> e8d4d78
> 1a65c4d
> 904173b
> 34c4066
> b6a4dce
> 3eaf6a9
> bf16005
> 8efb6f1
> 4701975
> 6570223
> c76c81a
> c0cc272
> 4978ad0
> 5ea4c9d
> 3eff8e9
> fcd89b5
> 523c78a
>
> Investigate and create a plan to smoothly revert these changes without causing any issues.

## Recommendation (TL;DR)

Revert both PRs with two `git revert -m 1` commits (PR #55 first, then PR #54), followed by one **preservation commit** that keeps back the run-history and memory content that rode those branches but is *not* rules-enforcement. This is verified conflict-free and byte-exact by a dry run in a throwaway worktree (evidence below). One PR, four commits, then two small local cleanups (`core.hooksPath` unset; memory bookkeeping rides the PR).

**Do not** revert the 17 commits individually — the branch topology (a stacked branch plus an in-flight `origin/development` merge, `e8d4d78`) makes per-commit reverts conflict-prone and incomplete. Reverting the two merge commits against mainline parent 1 is the canonical, complete inverse.

## What the changes were (verified inventory)

PR #54 `mn/critical-rules-core` (merge `5151ab7`, parents `5c996c3` + `c0cc272`) — branch commits:
`ff9d113`, `523c78a`, `fcd89b5`, `3eff8e9`, `5ea4c9d`, `4978ad0`, `c0cc272`.

PR #55 `mn/rules-enforcement` (merge `6aed9c8`, parents `5151ab7` + `e8d4d78`) — branch commits:
`3eaf6a9`, `8efb6f1`, `4701975`, `6570223`, `c76c81a`, `bf16005`, `b6a4dce`, `34c4066`, `904173b`, `1a65c4d`, plus the branch-side merge `e8d4d78`.

Note: the user's list of 17 SHAs omits `ff9d113` ("Document enforced rules reading plan") — it is part of PR #54's delta and is included automatically by the merge-revert. It is also the commit that carried the preservation concerns below.

| Layer | Content | Files | Disposition |
| --- | --- | --- | --- |
| L1 resident core | Critical-rules block + mandatory-reads table in AGENTS.md | `AGENTS.md` | revert |
| L2 pointer rules | Path-gated gates; `.qwen/rules` unignored | `.qwen/rules/*` (6 files), `.gitignore`, `.secretscan-allow`, 2× `.markdownlint-cli2.jsonc` | revert |
| L3a receipts | King verifies RULES-READ digest receipts; dispatches activate `.githooks` first | `.zcode/agents/swarm-orchestrator.md`, `.opencode/agents/swarm-orchestrator.md` (ACP parity: both together) | revert |
| L3b hooks | Advisory/blocking pre-commit + pre-push | `.githooks/pre-commit`, `.githooks/pre-push` | revert |
| Activation | `core.hooksPath` armed in validation Step-Build + at clone-mint | `validation.ps1`, `scripts/create-repo-agent-context.ps1` | revert |
| CI | Signature verification over PR-introduced commits; agentskills pin | `.github/workflows/ci.yml` | revert |
| Metrics | Per-repo critical map, Crit column, `-Enforce` | `scripts/rules-metrics.ps1`, `.agents/rules/rules-metrics.md` | revert |
| Rules docs | Signing §, `$num/$Num` pitfall, enforcement gate, worker receipts | `.agents/rules/{source-control,validation,swarm-workers}.md` | revert (returns to pre-#54 text wholesale) |
| Initiative docs | The enforcement plan/problem docs | `docs/plans/1790056869615-enforced-rules-reading.md`, `docs/plans/rules-enforcement.md`, `docs/plans/rules-systemissues-prompt.md.md` | revert (delete) |
| **Run history (not enforcement)** | Abort-report cleanup; restart-plan findings renumbering, F5 maxSubagents→MaxConcurrent redesign, owner NEGATIVE port-squatter directive | `docs/runs/Swarm-run-20261026-021751-{abort-report,analysis-and-restart-plan}.md` | **PRESERVE at current HEAD state** |
| **Memory (mixed)** | Rollout record lines (c76c81a/b6a4dce/34c4066) **and** two unrelated PaiR/herdr integration entries that rode `ff9d113` | `.agents/memory.md` | **PRESERVE file at HEAD, then edit editorially** |

## Verified facts (dry-run evidence, 2026-11-01)

Executed in a throwaway worktree at `HEAD` (`70b315e`) under `/tmp/kilo/swarm-orchestration-service/revert-probe` (removed after):

1. `git revert --no-commit -m 1 6aed9c8` → **clean, no conflicts**.
2. `git revert --no-commit -m 1 5151ab7` (after the first) → **clean, no conflicts**.
3. Completeness proof: `git diff --cached 5c996c3 --stat` after both reverts shows **exactly one file — `.opencode/opencode.jsonc`** — i.e. every byte both PRs changed returns to the pre-#54 state; the only remaining delta is `70b315e`'s post-merge opencode v2 migration, which the PRs never touched.
4. Restoring the two run docs to `70b315e` state then leaves exactly the intended end state (opencode.jsonc + 2 run docs vs `5c996c3`).
5. `core.hooksPath` **is armed in this checkout right now** (`.githooks`) — post-revert cleanup required (below).
6. Parent template `swarm-context` has **no enforcement mirrors** (no `.qwen/rules`, no `.githooks`; log greps hit only unrelated old commits). Scope is this repo only. Nothing to do in the parent or in `agent-context`.
7. The two run docs at HEAD contain **zero references** to the enforcement machinery (grep for githooks/RULES-READ/hooksPath/critical-core/rules-enforce → none), so preserving them whole dangles nothing.
8. `.qwen/rules` contains only the 6 tracked files (no untracked strays) — deletion is complete and the restored `.gitignore` entry hides nothing.
9. Open PR **#53** (`dev/restore-rev2-clause-table`) shares exactly one file with the revert delta: `.agents/memory.md`. Everything else in #53 is disjoint. Sequencing note below.
10. No GitHub-side cleanup: no Actions secrets were created for the signature-verification job (the `.secretscan-allow` line covered an ephemeral-token literal inside the workflow file, which the revert deletes).

## Execution plan

Branch `mn/revert-rules-enforcement` off `origin/development` @ `6aed9c8` (see base note). Four commits, one PR. Hooks stay armed during the branch until the revert deletes them (the pre-commit staged gitleaks scan and signing warn pass: commits are signed, content is deletions + docs). Governing rules: `.agents/rules/source-control.md` (safe-commit before each commit, merge ritual), `.agents/rules/validation.md` (gate before PR). Local gate run uses `-SkipE2E` (port-8765 squatter, pre-existing, environmental; CI runs e2e authoritatively).

### Commit 1 — this plan doc

```
docs(plans): revert plan for rules-enforcement changes (PRs #54/#55)
```

### Commit 2 — revert PR #55 (order matters: newer merge first)

```
git revert -m 1 6aed9c8
# default message: Revert "Merge pull request #55 from nam20485/mn/rules-enforcement"
```

### Commit 3 — revert PR #54

```
git revert -m 1 5151ab7
# default message: Revert "Merge pull request #54 from nam20485/mn/critical-rules-core"
```

**Why this order:** reverting #54 first would fight content that #54 and #55 both touched (`ci.yml`, `validation.ps1`, `source-control.md`, `rules-metrics` files) in its intermediate state; #55-then-#54 walks the tree back through each PR's exact post-merge state. The dry run proves both apply clean in this order. Reversing the order is *not* proven and is expected to conflict.

### Commit 4 — preservation + memory bookkeeping

```
docs: preserve run-history and unrelated memory from the enforcement revert
```

1. Restore the two run-history docs to their pre-revert state (keeps the F5 maxSubagents→MaxConcurrent redesign, the owner's port-squatter NEGATIVE directive, review fixes, findings renumbering):
   ```
   git checkout 6aed9c8 -- docs/runs/Swarm-run-20261026-021751-abort-report.md docs/runs/Swarm-run-20261026-021751-analysis-and-restart-plan.md
   ```
2. Restore `.agents/memory.md` to pre-revert state (keeps the two PaiR/herdr integration entries from `ff9d113`), then edit:
   - rewrite the "Enforced-rules-reading plan implemented end-to-end (2026-10-29…)" entry to past tense: *implemented, then reverted by owner directive 2026-11-01 (this PR) — mechanics removed, see `docs/plans/revert-new-rules-reading-changes.md`*;
   - add a **Decisions** entry: owner directed full revert of the rules-reading enforcement rollout (PRs #54/#55) on 2026-11-01; enforcement returns to convention-only progressive disclosure; run-history docs were deliberately preserved.
   - Markdownlint-clean the new text (the `ghp_` MD037 incident in `34c4066` was exactly this class of failure; `.agents/memory.md` is linted).

### Gate + PR

1. `pwsh ./validation.ps1` on the branch (redirect to a log, read `$?` directly — piped exit codes lie). Known environmental caveat: the local e2e step fails on this host only (8765 squatter, pre-existing); CI is authoritative there.
2. `/safe-commit` ritual per source-control rules.
3. Open PR → `development`, title "Revert rules-enforcement changes (PRs #54/#55)", body links this plan, milestone **maintenance (#8)** (Projects v2 board rule lapsed — milestone only, flag the gap). CI runs the branch's post-revert `ci.yml` (the pre-#54 workflow, green for months); the deleted signature-verification job simply doesn't run on this PR.
4. Merge per ritual: explicitly-read `conclusion == success` on the head SHA, merge as its own standalone command (owner-gated — likely owner-bypass per standing authorization), re-read post-merge CI green on `development`, then delete the branch.

### Local cleanup (after merge)

1. **`git config --local --unset core.hooksPath`** — required. The revert deletes `.githooks/`; a stale `core.hooksPath` makes git silently skip hooks (missing hook file), which is harmless but confusing later. Nothing re-arms it afterwards (the arming code in `validation.ps1` and the clone-mint script is itself reverted).
2. Optional: prune `.swarm/pr54-review/` and `.swarm/pr55-wt/` (gitignored run state from the enforcement PRs; keep for history if preferred).
3. Any clone minted between 2026-10-29 and the revert that ran `create-repo-agent-context.ps1` will have `core.hooksPath` armed with a `.githooks` dir — if any are ever touched again, same one-liner unset + delete `.githooks`. (None are known to exist.)

## Sequencing and risks

| # | Risk | Handling |
| --- | --- | --- |
| R1 | Revert order wrong → conflicts | Fixed order #55→#54, dry-run proven clean (facts 1–2) |
| R2 | Wholesale revert deletes non-enforcement history (F5 redesign, owner port directive, PaiR memory entries) | Preservation commit 4 (facts 4, 7; memory diff shows the PaiR lines came from `ff9d113`) |
| R3 | Stale armed `core.hooksPath` post-revert | Explicit post-merge unset (fact 5); no re-arm path remains |
| R4 | PR #53 interleaves on `.agents/memory.md` | Whichever merges second merges `development` in first and reconciles memory.md (trivial, both edits small). Recommended: land this revert PR first — it is the owner's current priority and #53's restart consumes post-revert rules state |
| R5 | Fresh rev2 swarm restart briefs workers against reverted rules (RULES-READ receipts, `.githooks`-first dispatch) | Land the revert **before** the restart; worker dispatch templates then come from reverted `development` |
| R6 | markdownlint fails on new memory/plan text | Lint locally before push; keep new text lint-clean (MD037 class) |
| R7 | Local validation e2e fails (8765 squatter) | Pre-existing, environmental; `-Port` override locally, CI authoritative — unaffected by this revert |

Coverage: no `src/` code is touched by the delta — the >85% floor is unaffected.

## Done-when (verification checklist)

1. Post-merge `development` tree vs `5c996c3` differs in **exactly** these files: `.opencode/opencode.jsonc` (70b315e), the two preserved `docs/runs/Swarm-run-20261026-021751-*.md` docs, `.agents/memory.md` (PaiR entries + revert records), and this plan doc. Everything else byte-equal:
   ```
   git diff 5c996c3 origin/development --stat
   git diff 5c996c3 origin/development -- AGENTS.md .githooks .qwen .github scripts/rules-metrics.ps1 scripts/create-repo-agent-context.ps1 validation.ps1 .secretscan-allow .gitignore   # expect empty
   ```
2. `AGENTS.md` at HEAD is byte-identical to `5c996c3:AGENTS.md` (critical-core block gone).
3. `.githooks/` and `.qwen/rules/` absent from the tree; `git status` clean; `git config --get core.hooksPath` → unset.
4. Validation gate green on the branch (CI authoritative for e2e); post-merge CI green on `development`.
5. `.agents/memory.md` records the revert decision (rewritten entry + Decisions entry); PaiR/herdr entries intact.
6. PR merged per ritual (green conclusion read explicitly, standalone merge, post-merge green, branch deleted); #53 reconciled with `development` before its own merge.
