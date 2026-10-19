# 4-repo-system-lifecycle

OK here is what I was writing BUT THEN I wnet and started digging into the repos and scripts and found that what i've been telling you may not be accurate.

1. `nam20485/swarm-orchestration-service` this repo was cloned from an intermediate template called `nam20485/swarm-context` (which is itself a clone of the `intel-agency/agent-context` template). So its a "grand-child clone" of `agent-context`. It even has an add'l remote called `upstream` which points to `nam20485/swarm-context`.
2. I created `nam20485/swarm-context` to be the parent template of any clones that will be based off an `swarm-context` seed (much like `agent-context` is the parent template of orchestration apps). So that they can be used in the newest `swarm-orchestration-service` orchestratin workflow.
3. The `create-repo-agent-context.ps1` script was moved out of `nam20485/workflow-launch2` and into this repo. Its used to make the new clone repos that the swarm orchestration service workflow will init issue tracking in and the imple,ent the new app.

The below contains (some) inaccuracies and was written before I dug into the repos and scripts....

- NO: `agent-context` is not used in this system- it is a relic of a legacy system and no longer relevant (WRONG)
- Yes- but they are intertwined and they meet again:
  - the script clones the template, names it, runs the string replacement, commits the original plan files into `plan_docs/`, at the END: it prompts w/ `/gh-issue-tracking-init`
  ====> creates everything: issues, projecdts, labels, milestones, and at the END:  creates an issue in the repo and labels it with ~ `dispatch:track-issue-complete`  ===> fires `issue.labelled` event `E` ===> org webhook fires w/ payload E ====> (well you know the rest)

---

A. Does `scripts/create-repo-agent-context.ps1` clone from `intel-agency/agent-context` or `nam20485/swarm-context`?
B. If it doesn't is `nam20485/swarm-context` ready to become the parent template for this swarm orchestration service?

---

## Report — verified provenance & lifecycle (2026-09-23, for approval)

> **Status: APPROVED 2026-09-23 — applied.** Parent prune: `nam20485/swarm-context` PR #7
> (`dev/template-prune`). Wrapper flip + lifecycle docs + this memory: this repo, branch
> `dev/lifecycle-flip`. Corrections below applied to `.agents/rules/lifecycle.md`, AGENTS.md,
> and `.agents/memory.md`. One correction to the report itself: this repo's query-fix PR was
> **#22** (merged), not "#6 still open" — that was the *parent's* PR #6 misread through gh's
> dual-remote repo ambiguity; the chain was already fully synced.

Every claim below is backed by a first-hand source: local git (remotes, roots,
tree diffs), the GitHub API (`isTemplate`, `templateRepository`, commit
listings), or the scripts' own source. Nothing is from memory alone.

## The chain as it actually is

| Repo | Role (verified) | GitHub state | Key content |
| --- | --- | --- | --- |
| `intel-agency/agent-context` | grandparent; **the template that stamps every clone today** | `isTemplate: true`, public | base template surface only: agent octet (`.opencode/agents/`), `.agents/` system, 7 helper scripts, `agent-context.code-workspace`. **No** `.zcode/`, no swarm rules/skills, no `src/` |
| `nam20485/swarm-context` | parent; **prepared but unused template** | `isTemplate: true`, public, default branch `development` | base + **full swarm surfaces** (all 7 `.zcode/agents/swarm-*.md`, `.agents/rules/swarm.md` + `swarm-workers.md`, `swarm` + `swarm-plan` skills, `config.example.json` committed / real `config.json` untracked) **plus** a 76-file `src/` tree (SwarmSandbox), +34 docs files, opencode octet diffs — 150 files / +8172 −5166 vs the grandparent |
| `nam20485/swarm-orchestration-service` (this repo) | the service + the launcher home | `isTemplate: false` | fork-style child of the parent (same squash root `1375d86` 2026-09-05; `upstream` remote → `nam20485/swarm-context`, push enabled — note: parent's own `upstream` → agent-context has push DISABLEd). 89 files / +13120 vs parent = the service (`src/webhook_receiver`, `compose.yaml`, `Dockerfile.webhook`, `Caddyfile`, tests, e2e) + the launcher (moved here from workflow-launch2). Shared surfaces (`.zcode`, `.agents`, `.opencode`) diverge in only 3 files (`memory.md`, `rules/scripts.md`, `rules/source-control.md`); **`.zcode/agents/` is byte-identical to the parent's** |
| `nam20485/workflow-launch2` | `plan_docs/` slug store (read via `-PlanDocsRoot`) | — | **stale launcher copies still in `scripts/`**: `create-repo-agent-context.ps1`, `create-repo-with-plan-docs.ps1`, `create-repo-from-slug.ps1` (run-by-mistake hazard; teardown already parked owner-gated) |
| `intel-agency/<slug>-<suffix>` clones | dispatch clones; checkout at `~/src/github/nam20485/dynamic_workflows/` | minted by this repo's launcher | today's stamped base = agent-context (no `src/`, no `.zcode/`, `agent-context.code-workspace` → `<repo>.code-workspace` rename fingerprint, AGENTS.md attribution "cloned from the `intel-agency/agent-context` GitHub template"). Suffix = NATO word + number (`Get-RandomSuffix`) |

Chain-sync state right now: the query-reply-route fix is merged in the parent
(`#6`, merge `594b5d8`, 2026-09-22 22:26 UTC) and the grandparent (`#27`,
merge `b70a235`, 2026-09-23 09:01 UTC) — both out-of-band. **This repo's PR
`#6` (same fix) is the only one still open**; this repo is the chain laggard.

## Answer A — what the script actually clones from

**`intel-agency/agent-context` (the grandparent).** Three independent
proofs:

1. The wrapper hardcodes it — `scripts/create-repo-agent-context.ps1:185-187`:
   `$TemplateRepoName = 'agent-context'`, `$TemplateOwner = 'intel-agency'`
   (comment: "Agent-context template identity — hardcoded").
2. GitHub's own record: `gh repo view intel-agency/gap-miner-v2-charlie11
   --json templateRepository` → `intel-agency/agent-context` (charlie11 was
   minted 2026-09-22, so this is current behavior, not history).
3. The stamped fingerprints: clones carry `agent-context.code-workspace`
   (renamed), zero `src/` and zero `.zcode/`, and their AGENTS.md
   attribution names agent-context.

So: the launcher **runs from** this repo, but the clone's file tree
**stamps from** the grandparent. Neither "clones come from this repo" nor
"agent-context is a relic no longer used" is true; agent-context is the
only thing currently seeding clone trees.

## Answer B — is swarm-context ready to become the parent template?

**Mechanically yes; content-wise there are two decisions to make first.**

Already ready (verified):

- `isTemplate: true`, public, default branch `development` — the GitHub
  template route can stamp from it today, cross-owner (the launcher's PAT
  is nam20485's, who owns the template) — no access obstacle.
- The stage scripts transform the same surfaces the parent carries
  (cleanup / headless-permissions / strip-model-settings are
  template-agnostic), and the identity rewrite is parameterized
  (`create-repo-with-plan-docs.ps1:350` — "**project instance** cloned
  from the `$TemplateOwner/$TemplateRepoName` GitHub template"), so a
  flipped template name auto-corrects the stamped attribution.
- It carries the **complete ZCode parity surface** — all 7 swarm defs,
  identical to this repo's — exactly what the "swarm-context seed"
  intent and the ACP-parity rule need clones to receive.

Decision 1 — **what should the parent's template tree contain?** Stamping
from the parent as-is ships 76 `src/` files (SwarmSandbox harness) + 34
docs files + octet diffs into *every* app clone. Options:
(a) prune the parent back to "agent-context base + swarm surfaces" (the
clean template its stated purpose implies — SwarmSandbox service code
stays here, where it's actually run); (b) add a post-stamp prune stage to
the launcher; (c) accept the bloat. Recommendation: (a).

Decision 2 — **identity + residual literals.** The parent's own AGENTS.md
identity paragraph still reads "This repository — intel-agency/agent-context
— is the GitHub template repo" (never rewritten after the fork), and
"agent-context" literals remain in its `.gitleaks.toml`, `README.md`,
`.agents/memory.md`, and one plan doc. If the parent becomes the stamper,
its identity text must be rewritten to name itself, and the literals
audited (placeholder replacement only replaces the template *name*
configured in the wrapper).

Flip mechanics (small): wrapper lines 185-187 → `swarm-context` /
`nam20485`; labels file + bootstrap still source from this repo
(unchanged); suggested order — merge this repo's PR #6 first so the chain
is synced before the fork point moves.

Effect of the flip: clones gain `.zcode/agents` (7 defs — ZCode parity),
`swarm.md` + `swarm-workers.md` rules, and the `$swarm` / `$swarm-plan`
skills — the "based off a swarm-context seed" goal. The opencode king
(M1) is still unauthored; per the parity rule it lands in the parent (so
it stamps into clones) authored for both clients at once.

## Corrections this dig produced (to apply to memories/instructions after approval)

1. "The swarm defs exist only in this repo" — **wrong**. They live fully in
   the parent (and `.zcode/agents` here is byte-identical to it). The
   earlier probe queried `intel-agency/swarm-context`, a repo that does
   not exist; swarm-context is under `nam20485/`.
2. `.zcode/` "never seeded, never deleted" in clones — **stands** (the
   stamper, agent-context, doesn't carry it), and post-flip it would be
   seeded by design.
3. The lifecycle docs' mechanism section should say: stamper today =
   agent-context; intended stamper = swarm-context (parent, already
   flagged `isTemplate`), pending Decisions 1-2 above.
4. This repo's `upstream` push is **enabled** while the parent's own
   upstream push is DISABLEd — asymmetric guardrails worth aligning
   (push-disable this repo's `upstream` too, or accept as the designated
   sync direction).
