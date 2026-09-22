# Review of `docs/plans/skill-plan.md`

Reviewed 2026-09-15 against the working tree on `dev/fold-launcher` (`a24b3e4`).
Every file path, line reference, count, and mechanism claim in the plan was read
and checked. Line refs (`app.py:262`, `prompt_queue.py:50`), the single-producer
claim, the label prefixes, the ring-buffer size (1000), `acp_smoke.py` /
`sandbox_probe.py` / `e2e-orchestration.ps1` / `query.ps1` / `swarm-state.ps1`
characterisations, and the `swarm-plan` → `plan_docs/application_plan.md` chain
all **verify correct**. The findings below are what does not.

## Overall Assessment

The investigation section is unusually solid and mostly true — the entry-point
table and the "one producer" structural fact are the plan's strongest asset and
should be kept nearly as-is. The risk is in **Proposed shape** and **Open
Questions**: the recommended option is built on a wrong launch delegate, a
status surface that is not network-reachable as described, a
self-containment rule the plan contradicts while claiming to follow it, and a
label count the repo has already formally retracted. Four of these would cause
implementation failure, not just confusion. Four of the seven Open Questions
are answerable today from existing repo evidence and should not be escalated.

---

### Critical Issues (Must Fix Before Implementation)

#### 1. `.github/.labels.json` is not "32 dispatch labels" — and the repo already retracted this claim

**Open Questions 7** says:
> `.github/.labels.json` (32 dispatch labels) vs. the gh-issue-tracking-init label set (19)

**The file itself** has 32 entries, of which exactly **9** are matched by
`filters.should_dispatch`:

```text
implementation:complete   implementation:ready   orchestration:dispatch
orchestration:epic-complete  orchestration:epic-implemented
orchestration:epic-ready     orchestration:epic-reviewed
orchestration:plan-approved  gh-issue-tracking:direct-body
```

The other 23 are GitHub defaults (`bug`, `wontfix`, `good first issue`…),
copilot/agent/state vocabulary (`agent:queued`, `state:planning`, …) and bare
hierarchy names (`epic`, `story`). None of them dispatch anything.

**`.agents/memory.md`** already corrected this exact mistake:
> `.github/.labels.json` (32) *contains* the dispatch vocabulary … but is a
> **superset** — `agent:*`, `state:*`, GitHub defaults and bare hierarchy labels
> are matched by nothing (**an earlier "exactly" claim here was corrected by the
> PR #20 review**)

**Why this matters:** the skill's first intent is "capabilities — label
taxonomy". Shipping 32 labels as the trigger set means users apply `bug` or
`epic`, get `202 ignored` + `webhook_filtered`, and conclude the system is
broken.

**Fix:** replace the OQ7 parenthetical with the precise framing already in
memory ("32 total / 9 dispatch-triggering"), and state in Goal §1 that the
taxonomy reference must enumerate **only** the `filters.py`-recognised set, with
the remaining 23 in a separate "non-triggering labels" section. The "19" for the
skill's `assets/labels.json` is correct.

---

#### 2. `GET /events` is not reachable from anywhere the skill runs

**Query surfaces** lists:
> `GET /events` SSE — listener-local ring buffer (1000 entries), replay + live
> fan-out; the only structured view of orchestration state.

**Proposed shape** commits to it:
> status: read `GET /events`, `gh` state, and optionally `logs/*.jsonl`.

**`Caddyfile`** routes only two paths and 404s everything else:
```
handle /webhooks/github { reverse_proxy webhook-receiver:8080 }
handle /health          { reverse_proxy webhook-receiver:8080 }
# Catch-all: nothing else is public.
handle { respond "Not Found" 404 }
```

**`compose.yaml:20`** uses `expose:` (container network), not `ports:` — so the
listener is not published on the host either. A status wrapper that does
`curl https://<host>/events` gets a literal `Not Found` body with a 404.

**`docs/usage.md` §6** already documents the constraint and the remedy, plus the
durability caveat the plan omits — the ring buffer is in-memory, so it is empty
after every restart:
> `/events` is listener-local by design — it is not routed through the public
> Caddy surface. Reach it on the listener port directly (host run), or via an
> SSH tunnel / tailnet serve.

**Fix:** add a preconditions note wherever `/events` is offered as a surface,
naming the three access paths (loopback on a host run, `docker compose exec`,
SSH/tailnet tunnel). Specify the read pattern: SSE is an open stream, so a
status command must connect, consume the replay backlog, and disconnect on an
idle/keepalive boundary (`WEBHOOK_EVENTS_KEEPALIVE`, default 15 s) rather than
block. Note the buffer is non-durable — `gh` issue state is the historical
record, `/events` only the recent window.

---

#### 3. Option A contradicts the very conventions line it claims to follow

**Proposed shape** says:
> New skill at `.agents/skills/<name>/` following repo conventions
> (`.agents/rules/skills.md`)

and then specifies:
> `scripts/` — thin wrappers, not re-implementations: launch: delegate to
> `scripts/create-repo-agent-context.ps1`

**`.agents/rules/skills.md`** forbids exactly that:
> The skill's whole job should still be reproducible from its directory alone —
> no external file dependencies outside the skill's own `scripts/` (see
> `skills_must_be_self_contained`)

The same rule decides **Open Question 4** against one of its three options:
"read `docs/` at invocation time (skill then only works from this repo)" is the
option the rule exists to prevent.

**There is established precedent for how to handle this legitimately.**
`.agents/skills/swarm-plan/SKILL.md` frontmatter declares its out-of-skill
dependencies rather than hiding them:
> `compatibility:` Requires the swarm skill (`.agents/skills/swarm/`),
> gh-issue-tracking-init (`.agents/skills/gh-issue-tracking-init/`), and the
> safe-commit skill … all in the target repo/session

**Fix:** (a) resolve OQ4 in-document — copy/generate into `references/`, never
read repo paths at invocation time; (b) keep the thin-wrapper design (it is
right — re-implementing the launcher would be far worse) but **declare the
repo-root scripts in the skill's `compatibility:` frontmatter**, following
`swarm-plan`; (c) note that the dangling `skills_must_be_self_contained`
identifier referenced by the rule resolves to nothing in this repo (grep: no
matches) — worth flagging separately so the rule cites a real validator.

---

#### 4. The plan names the wrong launch primitive, and the generic path as specified will fail

**Proposed shape** says:
> launch: delegate to `scripts/create-repo-agent-context.ps1` (and possibly
> `create-dispatch-issue.ps1` for the generic path)

**`scripts/create-repo-agent-context.ps1:327-338`** does not call
`create-dispatch-issue.ps1`. Its step 5 calls a script the plan never mentions:

```powershell
$triggerParams = @{
    Repo                = $repoFullName
    Labels              = @('gh-issue-tracking:direct-body')
    BootstrapLabelsFile = $sourceLabelsFile
}
& $triggerScript @triggerParams      # = trigger-gh-issue-tracking-init.ps1
```

**`scripts/trigger-gh-issue-tracking-init.ps1`** is the purpose-built entry
point, and its own header claims exclusivity:
> By default the issue is labeled `gh-issue-tracking:direct-body` so the
> orchestrator webhook runs the body verbatim as a prompt … Each label in
> -Labels is bootstrapped from -BootstrapLabelsFile (created on the target repo
> if missing) before being attached … this is the only dispatch trigger.

That bootstrapping is the load-bearing part. `create-dispatch-issue.ps1` files
an issue with labels; if `gh-issue-tracking:direct-body` does not yet exist on
the target repo, the labelling fails. A skill that goes straight to the raw
primitive — the plan's stated "generic path", Open Question 2's "arbitrary repo
+ label + body" — breaks on any repo that has not run `import-labels.ps1`.

**Fix:** add `trigger-gh-issue-tracking-init.ps1` to the entry-point inventory
as a fifth row (and to "Lesser-known feeders", replacing `create-dispatch-issue.ps1`
as the recommended generic primitive). Change Proposed shape to
`launch: delegate to create-repo-agent-context.ps1 (slug) /
trigger-gh-issue-tracking-init.ps1 (existing repo)`; keep
`create-dispatch-issue.ps1` documented as the lower-level primitive it wraps,
and correct row 2's "via `scripts/create-dispatch-issue.ps1`" to "via
`trigger-gh-issue-tracking-init.ps1`, which wraps it".

---

### Significant Gaps

#### 5. The plan depends on code that is not merged

All four launcher scripts the skill delegates to exist only on
`dev/fold-launcher`. `origin/development` HEAD is `8a92019` ("Merge pull request
#19"); the launcher landed in `ddc6037`, and `.agents/memory.md` records PR #20
as "**merge owner-gated**". The plan should state this dependency and its
sequencing constraint explicitly — build the skill before the fold merges and
`SKILL.md` points at scripts that do not exist on the default branch.

**Fix:** add a Dependencies line: blocked on PR #20 merging to `development`;
record the fallback (skill's `references/` documents the manual label path
until then).

#### 6. "Workflow catalog" (Goal §1) is undefined and does not exist as a static surface here

The plan's first capability is "label taxonomy, workflow catalog, run modes",
and it nominates `local_ai_instruction_modules/ai-*.md` as the source. Those
indexes contain **zero** `orchestration:` matches. Meanwhile:

- `.github/workflows/` in this repo is `ci.yml`, `droid.yml`,
  `droid-review.yml` — no orchestration workflow. The consumer named in
  `filters.py` ("the GitHub Actions `orchestrator-agent.yml` `orchestrate-job`
  `if:` guard") lives in the seeded clones, not here.
- `prompt_builder.py:8` says its design is "never from a hardcoded label→label
  clause table" — the repo deliberately removed the static catalog the plan
  wants to expose.

**Fix:** either scope Goal §1 to *what actually exists* (the four label classes
`prompt_builder.build_orchestration_prompt` documents: `direct-body`,
`gh-issue-tracking:*`, `orchestration:*`, `implementation:ready|complete`, plus
the no-match fallthrough) and name where each is consumed, or promote
"publish a canonical workflow catalog" to an explicit prerequisite work item. Do
not leave "workflow catalog" as an unqualified deliverable.

#### 7. `local_ai_instruction_modules/` must not be mirrored into `references/`

Both files, line 10:
> Agents MUST resolve dynamic workflows from the remote canonical repository.
> Do not use local mirrors.

**`ai-workflow-assignments.md:10`** adds "(by shortId)". The plan lists these as
a query surface with no such caveat, and Option A's `references/` is "distilled
capability docs … sourced from README/usage/architecture" — if that extends to
the modules, the skill violates a rule the modules themselves assert.

**Fix:** in `references/`, store only the *pointer* (repo
`nam20485/agent-instructions`, branch, `ai_instruction_modules/<dir>/`, resolve
by shortId) — never the content. Add this as an explicit exclusion in Proposed
shape so the drift mitigation (Option A's only listed con) does not silently
create a forbidden mirror.

#### 8. The stated Gap overstates what is missing; intent §2 is already written

**Gap** says:
> Capability knowledge is spread across `README.md`, `docs/usage.md`,
> `docs/architecture.md`, `.agents/rules/`, and the lookup tables

True, but it undersells the existing asset. `docs/usage.md` is already a
complete answer to the plan's intent §2 ("setup, endpoints, env vars,
troubleshooting"):
> §1 Pick a run mode · §2 Configure · §3 Expose it to the internet ·
> §4 Wire the GitHub App · §5 Trigger a run · §6 Observe · §7 Troubleshoot ·
> §8 Operational notes · §9 Verify changes before deploying

and `README.md` has a ready `## Endpoints` table. The genuine gap is *routing
and initiation*, not documentation authorship.

**Fix:** rewrite Gap to distinguish "material exists and is well-structured"
(usage.md, README) from "no conversational entry point". Then change Option A's
`references/` from "distilled capability docs" to "a thin index + the two facts
the docs do not state together", which materially reduces the drift risk Option
A lists as its only con.

#### 9. The direct-body gate's two most surprising behaviours are missing

Row 1 says:
> `direct-body` additionally needs the `DIRECT_BODY_ALLOWED_SENDERS` allowlist

`filters.py` says more, and both extras are troubleshooting-critical:

```python
if _DIRECT_BODY_LABEL in issue_labels or label_name.lower() == _DIRECT_BODY_LABEL:
    allowed_senders = _direct_body_allowed_senders()
    if not allowed_senders:
        return (False, "direct-body dispatch disabled "
                       "(set DIRECT_BODY_ALLOWED_SENDERS to enable)")
```

(a) **Fail-closed when unset** — the default state is *disabled*, so a fresh
install silently ignores every direct-body dispatch. This is the single most
likely cause of "nothing happened" and the first thing the skill should check.
(b) **The gate matches the issue's full label set**, not only the triggering
label, so a previously-denied `direct-body` label keeps gating every later
label event on that issue.

**Fix:** add both to row 1 and to a Pre-flight check in the skill's initiate
path (read `DIRECT_BODY_ALLOWED_SENDERS` presence before offering a
direct-body launch). Also worth one line: responses are `202` even when
filtered, so HTTP status never distinguishes accepted from ignored — only
`reason` / `/events` does.

#### 10. Owner/visibility policy gates every launch and is absent from the plan

**`scripts/create-repo-agent-context.ps1`** header:
> Owner/visibility policy: a private repo is only supported under `-Owner
> intel-agency` (an Organization on the Enterprise plan); every other owner must
> be `-Visibility public`. Enforced by `Test-OwnerVisibilityPolicy` … and it
> bails under `-DryRun` too

The consequence is non-obvious and decisive for the initiate path: a private
clone under `nam20485` is free-tier, gets **no GitHub Actions minutes**, so its
dispatch workflows can never run — the launch "succeeds" and then does nothing.
A skill that creates repos must encode this or it will produce silent failures.

**Fix:** add to Goal §3 / Proposed shape's launch wrapper as a validated input
pair (owner + visibility), and to `references/` troubleshooting. Note that
`-PlanDocsRoot` defaults to the sibling `../workflow-launch2` checkout, so the
slug store is an external path dependency the skill must surface when the slug
directory is missing.

---

### Minor Issues / Improvements

#### 11. No acceptance criteria, test plan, or validation step

The plan has Goal / Investigation / Options / Open Questions / Non-goals but
nothing testable. Repo convention (AGENTS.md → `.agents/rules/validation.md`)
requires >85% coverage via the `validation.ps1` gate, and both sibling skills
ship script tests (`.agents/skills/swarm/scripts/tests/`,
`.agents/skills/gh-issue-tracking-init/scripts/tests/`). Add: a `Done when` list
per intent, the Pester suite for any new `scripts/*.ps1`, whether
`validation.ps1 -Step all` needs a new step, and the
`uvx --from skills-ref agentskills validate ./<skill>` pass as a gate.

#### 12. No effort estimate and no rollback story

Neither the skill authoring (SKILL.md + references + N wrappers + tests) nor
what to do if the skill misleads (disable by removing from `.agents/skills/`?)
is covered. An estimate sized against the ~16 findings above would also force
the OQ resolutions into scope.

#### 13. Open Question 1 (name) is answerable now

Bare `orchestrate` collides in reading order with three already-installed
user-level skills — `orchestrate-dynamic-workflow`, `orchestrate-new-project`,
`orchestrate-project-setup` — none of which touch this service, which is the
confusion the plan wants to avoid. `swarm-orchestration` reads as swarm-owned,
the other thing the plan rules out. Constraints from `.agents/rules/skills.md`:
`name` must match the directory, lowercase `a-z0-9`+hyphens, no leading,
trailing or consecutive hyphens, ≤64 chars. Propose a service-scoped name (e.g.
`orchestrator-service`, `service-orchestration`) and record the rejected
candidates with the reason, converting OQ1 into a Design Decision.

#### 14. Open Question 5 (confirmation gates) is answerable from existing precedent

The launcher suite already implements two-layer gating: `-DryRun` (forwarded to
every stage, and deliberately validated to bail on the same failures as a real
run) plus `-Yes`/`ShouldProcess`. OQ5's "one approval vs per-stage" is therefore
already answered by the scripts it delegates to: the skill shows one `-DryRun`
preview, takes one confirmation, then runs without `-Yes`. Recommend that, and
say so.

#### 15. Open Questions 4 and 6 have evidence-backed answers (see #3 and #7)

OQ4 is decided by the self-containment rule; OQ6 is cheap and precedent-backed
(`swarm-plan`'s `compatibility:` cross-skill declaration shows the sanctioned way
to route to another skill). Resolve both in-document and drop them from the
owner-decision list, leaving only OQ2/OQ3/OQ7 as genuinely open.

#### 16. Surfaces and mechanics the inventory omits

- **`src/webhook_receiver/README.md`** — `app.py` names it as the mirror of the
  stable event-name table ("this table is the single source of truth, mirrored
  by …"); it is the authoritative capability doc for `/events` and is not in the
  plan's list.
- **Queue dedup window is 1024 deliveries** (`docs/usage.md` §7) — relevant to
  any "why didn't my re-label fire" answer.
- **`agent:*` / `state:*` labels are unwritten.** They exist in
  `.github/.labels.json`, but grep across the repo finds no code that applies or
  reads them, and `filters.py` does not match them. If the skill offers status
  via `gh`, the plan must say who owns these labels and when they appear — or
  drop the implication that they are a status surface today.
- **`scripts/create-repo-with-plan-docs.ps1`** — a second, distinct launcher
  (`-RepoName`/`-Owner`/`-PlanDocsDir`/`-CloneParentDir`, its own `-DryRun`/`-Yes`)
  that `create-repo-agent-context.ps1` wraps as stage 1. Worth one inventory row
  so the skill does not offer both as alternatives.
- **Second log location:** `.gitignore:4` ignores `gh-init-*.log` (the
  gh-issue-tracking-init forensic logs) in addition to `logs/` — the plan's
  "write-only today, no reader tooling" claim holds for both, but the list is
  incomplete.

---

### Summary Table

| # | Severity | Category | Description |
|---|----------|----------|-------------|
| 1 | **Critical** | Stale reference | `.github/.labels.json` is 32 labels / **9** dispatch triggers; memory already retracted the "exactly" claim |
| 2 | **Critical** | Technical bug | `GET /events` is 404'd by Caddy and unpublished by compose; status wrapper needs tunnel/loopback + SSE-read + non-durability notes |
| 3 | **Critical** | Contradiction | Plan cites `.agents/rules/skills.md` then specifies out-of-skill script and doc dependencies; also settles OQ4 |
| 4 | **Critical** | Gap | `trigger-gh-issue-tracking-init.ps1` omitted; generic path delegates to `create-dispatch-issue.ps1`, which lacks label bootstrap and fails |
| 5 | Significant | Gap | Launch scripts exist only on unmerged `dev/fold-launcher` (PR #20 owner-gated) |
| 6 | Significant | Gap | "Workflow catalog" undefined; no orchestration workflow here, no `orchestration:` in the modules, clause table was deliberately removed |
| 7 | Significant | Contradiction | `local_ai_instruction_modules/` says "Do not use local mirrors" — must not be copied into `references/` |
| 8 | Significant | Gap | Gap overstates: `docs/usage.md` §1–§9 + README Endpoints already answer intent §2 |
| 9 | Significant | Missing edge case | direct-body is fail-closed when unset and matches the issue's full label set; `202` never distinguishes accepted from filtered |
| 10 | Significant | Missing edge case | Owner/visibility policy (private ⇒ `intel-agency` only; free-tier has no Actions minutes) gates every launch |
| 11 | Minor | Test gap | No acceptance criteria, Pester suite, `validation.ps1` step, or validator gate |
| 12 | Minor | Process | No effort estimate, no rollback plan |
| 13 | Minor | Process | OQ1 (name) resolvable — `orchestrate*` already taken by three user-level skills |
| 14 | Minor | Process | OQ5 (gates) resolvable from existing `-DryRun` + `-Yes`/`ShouldProcess` precedent |
| 15 | Minor | Process | OQ4 and OQ6 resolvable from #3 and #7; only OQ2/OQ3/OQ7 need the owner |
| 16 | Minor | Gap | Omits `src/webhook_receiver/README.md`, dedup window 1024, unwritten `agent:*`/`state:*`, `create-repo-with-plan-docs.ps1`, `gh-init-*.log` |

**Counts:** 4 critical, 6 significant, 6 minor.

**Effort split:** all 16 are document fixes — none requires service changes, and
the Non-goals section stays valid. The implementation risk they represent is
real but entirely front-loaded: #2, #4, and #10 each describe a wrapper that
would ship broken or silently inert, and #3 determines the skill's directory
layout before any file is written. Fixing #3/#4/#7 also collapses four of the
seven Open Questions into decisions with evidence already in-repo.
