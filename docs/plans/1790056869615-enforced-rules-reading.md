# Plan: Enforced Rules Reading via Progressive Disclosure

Status: implementation-ready design · Date: 2026-10-27
Repo: `swarm-orchestration-service` (lineage child of `nam20485/swarm-context`)
Companion prompt: `docs/plans/rules-systemissues-prompt.md.md` (owner)

**Contamination rule for this document:** no canary token *values* appear anywhere in this plan (shape `<colour>-<animal>-<n>` only). Any session that has seen the registry or real tokens certifies nothing.

---

## 1. Problem and evidence (the documentation the owner asked for)

The rules system is progressive disclosure **by convention only**: AGENTS.md (auto-injected in all 4 clients) carries 1–2-line briefs; `.agents/rules/*.md` bodies load only if the agent chooses to open them. Nothing auto-loads them.

**Measured (Qwen sessions, 30-day window, `scripts/rules-metrics.ps1 -Days 30`, 2026-10-27):**
- AGENTS.md injected **226×** · rule files read **16× across 6 sessions** · **10 of 20 files NEVER READ** (incl. `coding-style.md`, `ci-cd.md`, `swarm.md`, `swarm-workers.md`, `zcode-config.md`, `lifecycle.md`) · decoys untouched (metric sound).
- The measurement is Qwen-only; Kilo/ZCode/opencode sessions are invisible to it — the real picture is likely worse. Swarm workers (`injectAgentsMd: false`) don't even get the TOC.

**Owner-cited symptoms, verified:**
- Push/PR policy: `source-control.md` obligations SC1–SC12 are **prose-only** — zero mechanical backing (no git hooks exist at all: only `.sample` files, no `core.hooksPath`, no husky).
- **Commit signing**: ON in `~/.gitconfig` (`commit.gpgsign = true`), documented **nowhere** (zero prose, zero enforcement). The exact "agents don't know it" profile. In-repo deliberate exception: `src/SwarmSandbox/scripts/e2e-sandbox.ps1:310` and `src/SwarmSandbox/sandbox/smoke-test.ps1:111` commit with `-c commit.gpgsign=false` (keyless ephemeral workspaces) — any hard local signing gate must not break these.
- Propagation is broken too: the `$num`/`$Num` case-insensitivity gotcha (found 2026-10-23) never landed in `validation.md`, which still says "Two" pitfalls. `memory.md:12` is its only home.
- The parent's AGENTS.md preview **omits the merge-gate line** this repo carries — clones are born without it.

**Tier ladder (compliance strength):**

| Tier | Mechanism | Cost | Examples today |
|---|---|---|---|
| 1 Documented | rules files | 0 tokens | most of the corpus — empirically ignored |
| 2 Resident | AGENTS.md section | tokens every request | TOC briefs (+700 tok precedent) |
| 3 Conditional | `.qwen/rules/` `paths:` gates | 0 until touch | **unused** |
| 4 Mechanical | hooks / git hooks / CI / rulesets | 0 context | validation.ps1 in CI; branch ruleset (partial) |

**Client capability matrix (researched, evidence in research transcripts):**

| Capability | Qwen | Kilo | ZCode | opencode |
|---|---|---|---|---|
| Path-gated injection (`.qwen/rules/` `paths:`) | YES (unused) | no | no | no |
| Unconditional residency | AGENTS.md + `@import` (unused) | AGENTS.md | `injectAgentsMd` bool | AGENTS.md (inescapable) |
| Block actions | PreToolUse hook (code-verified, unused) | permission globs | tools/maxTurns | permission maps + ACP policy |
| Silent read observation | **deployed** (PostToolUse→`rule-reads.jsonl`) | plugin only | none | plugin only |

**Honest framing (red-team F13):** this system enforces **exposure, not obedience**. Knowledge gaps (signing, parent's missing merge-gate line) are fixed by residency; obedience gaps (merge gate violated while resident) are fixed **only** by mechanical gates. The design does both, and claims only that.

## 2. Design (layers, red-team fixes integrated)

```
L1  AGENTS.md "Critical rules" section      — resident ALL clients (~480 tok, AC-capped)
L2  .qwen/rules/*.md pointer gates          — Qwen, path-fired, 0 resident, pointer-only
L3a PreToolUse gate (Qwen)                  — warn→block; TWO checks:
      (i)  read-gate: git commit/push/gh pr create require a logged read of
           source-control.md this session (oracle: rule-reads.jsonl)
      (ii) NO-oracle compound-command block (SC4/SC6): gh pr merge / git push --delete /
           force-push denied when the command string contains && ; | or a
           gh run watch/view prefix — mechanically checkable, highest value per line
L3b .githooks/ pre-commit/pre-push (repo-scope core.hooksPath) — ALL local clients;
      gpgsign check ADVISORY locally (hard only in CI/branch protection)
L3c CI: commit-signature check (PR-introduced commits only) + agentskills validate
L4  canary "critical" subset — per-repo registry map + script Critical column +
      advisory -Enforce; real enforcement lives in L3a hook
L5  worker read-receipts = sha256 digest + line-count of the rule file (NOT canary
      tokens — blocker fix); king verifies against file body
L6  opencode king def carries the same mandate (digest receipts, never token values)
```

**Key decisions from review:**
- **No canary tokens in receipts (F2 blocker).** Digest+linecount proves content access without planting answer keys; canary tokens stay confined to `.agents/rules` bodies + Qwen measurement. Anti-theater rule: orchestrator/king must never paste digests into task inputs either.
- **L1 trimmed to deltas (F1):** signing statement (genuinely new), mandatory-reads table (the new contract), the standalone-merge-command one-liner. It does NOT re-print the already-resident-and-ignored SC previews; those stay in the TOC. Anti-bloat is mechanical: AC7 caps the section.
- **`-Enforce` advisory-only in the script (F8); the hook is the enforcer.** Per-repo critical map + existence guard (F7) — a critical file absent in a repo shows `critical-absent`, never trips enforcement.
- **L3b repo-scope only, advisory gpgsign (F5)** — never `--global core.hooksPath`; the SwarmSandbox unsigned-commit pattern must keep working; `--no-verify` escape noted (CI is the backstop).
- **Hook hygiene (F3/F12):** read-logger made synchronous; join key = `(session_id, git-root-canonicalized cwd)` so worktree sessions count; `enforcement-skipped` telemetry row when the hook errors (fail-open is detectable); tool id confirmed in Phase 0 (`run_shell_command` per live docs).
- **Post-enforcement reads are coerced (F11)** — report labels them; `--safe-mode` probes remain the baseline control.

## 3. File-level changes

### PR-A — content + L1 (branch `mn/critical-rules-core`)
1. **`AGENTS.md`** — insert `### Critical rules (read before acting)` after the `### Rules` TOC: (a) 3 hard invariants (signing statement — new; merge-on-read-green standalone-command; destructive-ops standalone-command), (b) mandatory-reads table (commit/push/branch/PR → `source-control.md`; tests/validation → `validation.md`; scripts → `coding-style.md`; skills → `skills.md`; workflows/validation.ps1 → `ci-cd.md`), (c) `<!-- critical-core:end -->` delimiter; repo-local addendum below it only (the `.zcode/**`/`.opencode/agents/**` → `zcode-config.md` row — parent lacks that file). ≤ 45 lines / ≤ 2,400 chars. No token values.
2. **`.agents/rules/validation.md`** — "Two pitfalls" → "Three"; add the `$num`/`$Num` case-insensitive collision gotcha from `memory.md`.
3. **`.agents/rules/source-control.md`** — new `## Commit signing` section: gpgsign on in `~/.gitconfig`; never `--no-gpg-sign`; enforced by CI + branch protection (name both); document the SwarmSandbox keyless-workspace exception.
4. **`.agents/rules/rules-metrics.md`** — document: `critical` registry key (per-repo), Critical column, advisory `-Enforce`, the L3a gate + phase ladder, digest receipts, coerced-read labeling; refresh § Decision gate.
5. **`.agents/rules/swarm-workers.md`** (shared surface) — § Report contract: for every rules file the task's Constraints named, include `RULES-READ: <relpath>: sha256(body)[:12] @ <line-count>`; missing/mismatched receipt fails the task.
6. **`.opencode/agents/swarm-orchestrator.md`** (repo-local, L6) — delegation contract: Constraints name rule files; never paste digests/tokens into task inputs; verify receipts at verdict time; activate `.githooks` as first action of any committing dispatch.
7. **`docs/plans/rules-enforcement.md`** — land §1 of this plan (problem, metrics, tier table, options analysis) as the repo doc.

### Machine-scope runbook (no PR; per-machine, documented in rules-metrics.md)
8. **`~/.qwen/metrics/canary-registry.json`** — add sibling key (values stay strings; do NOT object-ify — breaks script L116/L166):
   `"critical": { "swarm-orchestration-service": ["source-control.md","validation.md","coding-style.md","skills.md","ci-cd.md","zcode-config.md"], "swarm-context": ["source-control.md","validation.md","coding-style.md","skills.md","ci-cd.md"] }`
9. **`~/.qwen/hooks/rules-metrics/gate-consequential-git.sh`** — new PreToolUse hook: phase knob (`RULES_GATE=off|warn|enforce`, default from `~/.qwen/metrics/gate-phase`); position-anchored regex `(^|[;&|]\s*)(git (commit|push|merge)\b|gh pr (create|merge)\b)`; read-gate via `jq` over `rule-reads.jsonl` (session + canonicalized git-root join); **compound-command block** for `gh pr merge`/`git push --delete`/force-push when the command contains `&&`/`;`/`|` or `gh run watch|view` prefix (no oracle); attempts logged to `~/.qwen/metrics/consequential-git-attempts.jsonl`; `enforcement-skipped` row on internal error; warn phase emits `additionalContext` only; enforce emits block + reason naming the file.
10. **`~/.qwen/settings.json`** — add `PreToolUse` wiring (matcher from Phase-0 capture; apply-next-session semantics documented).
11. **`~/.qwen/hooks/rules-metrics/log-rule-read.sh`** — make synchronous (`"sequential": true` in settings).
12. **`~/.qwen/hooks/rules-metrics/verify-rules-ac.sh`** — add AC7 (critical section present, ≤45 lines/≤2,400 chars, contains "Mandatory reads"), AC8 (zero token values under `.qwen/rules/`), AC9 (**repo-wide** leak scan: any tracked file outside `.agents/rules/**` quoting a token value fails — extends today's AGENTS.md-only check).

### PR-B — mechanics (branch `mn/rules-enforcement`, stacks on PR-A)
13. **`.qwen/rules/*.md`** ×5 — pointer-only bodies (3 lines, no rule content, no HTML comments): `code-change-gate` (`scripts/**`, `src/**`, `*.ps1`, `*.sh` → read `validation.md` + `coding-style.md`), `skill-authoring-gate` (`.agents/skills/**`, `.kilo/skills/**` → `skills.md`), `agent-config-gate` (`.zcode/**`, `.opencode/agents/**` → `zcode-config.md`), `ci-gate` (`.github/workflows/**`, `validation.ps1` → `ci-cd.md` + `validation.md`), `rules-system-gate` (`.agents/rules/**`, `AGENTS.md` → `rules-metrics.md`). Confirm frontmatter field names against Qwen docs at implementation.
14. **`.githooks/pre-commit` + `.githooks/pre-push`** (bash, chmod +x): signing **advisory** (warn if `commit.gpgsign != true`, never block locally — SwarmSandbox exception); branch-naming check (advisory in pre-commit, blocking pattern only for clearly-invalid names); gitleaks-if-present staged scan (blocking); SC1/SC2/SC4 reminders. Pre-push: signing/branch guards + merge-gate reminder.
15. **`scripts/validation.ps1`** — `Step-Build`: idempotent `git config core.hooksPath .githooks` (repo-scope) + echo the current value (clobber-visibility).
16. **`scripts/create-repo-agent-context.ps1`** (or its stage script) — same hooksPath activation at clone mint time.
17. **`.github/workflows/ci.yml`** — (a) commit-signature verification over **PR-introduced commits only** (`github.event.pull_request.commits` range / push `before..sha` with new-branch handling; `G`/`U` pass, `N` fail); (b) `agentskills validate` over `.agents/skills/*/` via pinned `uvx --from skills-ref==<pin>`. **Precondition step 0:** audit `git log --show-signature` history + decide web-flow/bot policy before enabling (a).
18. **`scripts/rules-metrics.ps1`** — per-repo critical map load (existence-guarded: missing file → `critical-absent`, not a finding), `Crit` column, `!! CRITICAL NEVER READ` (yellow advisory; red only under `-Enforce`), audit-finding count captured, `-Enforce` advisory exit 1 (documented: Qwen-sessions-on-this-machine only).
19. **`.markdownlint-cli2.jsonc`** — add `.qwen/rules/*.md` globs.

### Parent PR → `nam20485/swarm-context` (after PR-A/B verified; owner nod on new shared surfaces)
20. Word-for-word mirrors of shared surfaces ONLY: `scripts/rules-metrics.ps1` (byte-identical), `rules-metrics.md`, `swarm-workers.md`, the L1 shared block **without** the zcode row, `.githooks/` (new shared surface — owner decision, default include), `.qwen/rules/` generic gates (default include; `agent-config-gate.md` per parent's `.opencode/` presence). Then sync down here; `git diff` proves byte-identity.

## 4. Rollout order

| Step | Track | Gate to proceed |
|---|---|---|
| 0 | Precondition: audit signing history (`git log --show-signature origin/development`, decide web-flow policy); verify `uvx --from skills-ref agentskills validate` runs and pin it | facts recorded in PR-B description |
| 1 | Machine-scope: registry `critical` key; gate script in **capture** mode; PreToolUse wiring; AC7–AC9 | Phase-0 log confirms tool id + payload schema |
| 2 | PR-A (content + L1 + receipts contract + docs) | full source-control flow: `/safe-commit`, validation green, milestone + Projects v2, threads resolved |
| 3 | PR-B (gates, hooks, CI, script) | same; the two new CI steps green on the PR itself |
| 4 | Verification window ≥ 7 days: probe matrix §5; `rules-metrics.ps1 -Days 7` twice weekly; zero unexplained gate misfires in `consequential-git-attempts.jsonl` | all probes pass |
| 5 | Machine: flip gate **warn → enforce**; owner enables branch-protection *require signed commits* (with web-flow/robot allowlist) | step-4 gate |
| 6 | Parent PR; sync down; byte-identity diff | parent review flow |
| 7 | Follow-up commit: rules-metrics.md § Baseline records post-rollout measurements (L1 token cost, critical-read ratios, first gate blocks, coerced-read labels) | — |

PR-A and PR-B may collapse into one PR with grouped commits if the owner prefers.

## 5. Validation (probe matrix, fresh sessions, `-ExcludedSession` exclusions)

| # | Probe | Pass |
|---|---|---|
| P1 | "commit these changes", no prior read | warn: context injected + attempt row; enforce: blocked, reason names `source-control.md` |
| P2 | Same after the model reads the file | proceeds; exactly one attempt row per block |
| P3 | `echo "git push"` / `grep 'git commit'` | never fires (position-anchored) |
| P4 | `gh run watch … && gh pr merge` | **blocked in every phase** (compound-command, no oracle) |
| P5 | Touch `scripts/foo.ps1` → inspect context | `code-change-gate` injected on touch only (transcript fence / `RULES_DISCOVERY`) |
| P6 | Fresh session: "what must you read before merging?" | answered from L1 alone |
| P7 | Decoy recitation probe | still refused (harness integrity) |
| P8 | Clone with `commit.gpgsign false`: commit | advisory warning, commit proceeds; SwarmSandbox e2e scripts still pass |
| P9 | Stage fake `AKIA…` key | pre-commit gitleaks blocks |
| P10 | Push `--no-gpg-sign` commit to scratch branch | CI signature step fails |
| P11 | Spec-violating SKILL.md on a branch | `agentskills validate` CI step fails |
| P12 | Swarm drill: Constraints name `coding-style.md`; one worker told to skip | compliant worker's digest receipt verifies vs file body; skipping worker marked `failed` |
| P13 | `rules-metrics.ps1 -Days 7` | Critical column live; parent run shows `critical-absent` for zcode row, no false alarm |
| P14 | Token pasted into `.qwen/rules/` file / grown L1 section / token in a committed doc | AC8 / AC7 / AC9 fail respectively |
| P15 | Token budget | `wc -c AGENTS.md` delta ≤ 2,400; headless probe shows context grew by exactly that; `.qwen/rules` payloads ≤ 400 B each, injected only after touch |

**Per-client honest outcome:** Qwen = full stack. Kilo/ZCode primaries = L1 residency + L3b advisory + L3c CI (their reads unobservable — L1 makes reads unnecessary by construction). ZCode workers = L5 digest receipts. opencode dispatch clones = L6 mandate + L3b (once activated) + L3c. Safe-mode/bare Qwen sessions lose L2/L3a/L4 observation but keep L3b/L3c.

## 6. Risks and accepted limits

- Exposure ≠ obedience (stated in §1; the mechanical gates target the two most-violated rules precisely because prose residency already failed there).
- Safe-mode/`disableAllHooks` bypass the Qwen gate — accepted; the actor who disables hooks owns the machine; CI + branch protection remain.
- Coerced reads post-enforcement — labeled; `--safe-mode` baseline probes preserved.
- `--no-verify` escapes local git hooks — CI backstop covers.
- Registry/hooks/settings are machine-scope: every machine (and the per-machine registry) updated by runbook, not PR.
- Contamination discipline: no token values in this plan, AGENTS.md, `.qwen/rules/`, task inputs, or receipts; AC6+AC8+AC9 grep mechanically; king/worker digest checks never touch the registry.

## 7. Open items for owner (non-blocking, defaults chosen)

1. Branch-protection *require signed commits* (GitHub settings action, step 5) — needs the web-flow/robot allowlist decision.
2. `.githooks/` + `.qwen/rules/` as **new parent shared surfaces** (step 6) — default: include.
3. Collapse PR-A/PR-B into one PR — default: keep two.
