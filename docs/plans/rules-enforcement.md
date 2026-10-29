# Rules Enforcement: Problem, Evidence, and Options

Status: living record (problem statement + measurement + options analysis) · Landed: 2026-10-29
Design and rollout of record: [`1790056869615-enforced-rules-reading.md`](1790056869615-enforced-rules-reading.md) ·
Operator docs: [`.agents/rules/rules-metrics.md`](../../.agents/rules/rules-metrics.md)

**Contamination rule:** no canary token values appear in this document (shape
`<colour>-<animal>-<n>` only). Any session that has seen the registry or real tokens certifies
nothing.

## 1. Problem

The rules system is progressive disclosure **by convention only**: AGENTS.md (auto-injected in all
four clients — Qwen, Kilo, ZCode, opencode) carries 1–2-line briefs per rules file; the
`.agents/rules/*.md` bodies load only if the agent chooses to open them. Nothing auto-loads them,
and until the canary harness existed nothing measured whether they were opened.

## 2. Measured evidence (Qwen sessions, 30-day window, `scripts/rules-metrics.ps1 -Days 30`, 2026-10-27)

- AGENTS.md injected **226×** · rule bodies read **16× across 6 sessions**.
- **10 of 20 rule files NEVER READ** — including `coding-style.md`, `ci-cd.md`, `swarm.md`,
  `swarm-workers.md`, `zcode-config.md`, `lifecycle.md`.
- Both decoy files untouched — the metric is sound (no over-loading, no fabrication).
- The measurement is **Qwen-only**; Kilo/ZCode/opencode sessions are invisible to it, so the real
  picture is likely worse. Swarm workers run `injectAgentsMd: false` — they don't even get the TOC.

### Owner-cited symptoms, verified

- **Push/PR policy:** `source-control.md` obligations SC1–SC12 were prose-only — zero mechanical
  backing. No git hooks existed at all (only `.sample` files, no `core.hooksPath`, no husky).
- **Commit signing:** ON in `~/.gitconfig` (`commit.gpgsign = true`), documented **nowhere** — the
  exact "agents don't know it" profile. Deliberate in-repo exception:
  `src/SwarmSandbox/scripts/e2e-sandbox.ps1` and `sandbox/smoke-test.ps1` commit with
  `-c commit.gpgsign=false` (keyless ephemeral workspaces); any signing gate must not break them.
- **Propagation broken:** the `$num`/`$Num` PowerShell case-insensitivity gotcha (found 2026-10-23)
  never reached `validation.md`, which still said "Two" pitfalls; `memory.md` was its only home.
- **Clone drift:** the parent template's AGENTS.md preview omits the merge-gate line this repo
  carries — clones are born without it.

## 3. Tier ladder (compliance strength)

| Tier | Mechanism | Cost | Examples before this work |
| --- | --- | --- | --- |
| 1 Documented | rules files | 0 tokens | most of the corpus — empirically ignored |
| 2 Resident | AGENTS.md section | tokens every request | TOC briefs (+700 tok precedent) |
| 3 Conditional | `.qwen/rules/` `paths:` gates | 0 until touch | unused |
| 4 Mechanical | hooks / git hooks / CI / rulesets | 0 context | `validation.ps1` in CI; branch ruleset (partial) |

## 4. Client capability matrix (researched)

| Capability | Qwen | Kilo | ZCode | opencode |
| --- | --- | --- | --- | --- |
| Path-gated injection (`.qwen/rules/` `paths:`) | YES (was unused) | no | no | no |
| Unconditional residency | AGENTS.md + `@import` | AGENTS.md | `injectAgentsMd` bool | AGENTS.md (inescapable) |
| Block actions | PreToolUse hook | permission globs | tools/maxTurns | permission maps + ACP policy |
| Silent read observation | deployed (PostToolUse → `rule-reads.jsonl`) | plugin only | none | plugin only |

## 5. Options analysis

- **Do nothing** — rejected: the 30-day measurement shows the convention is not honored, and two
  violations touched merge policy (the highest-consequence surface).
- **`@import` rule bodies into AGENTS.md** (tier 2, strongest Qwen-local residency) — rejected as a
  blanket move: the full corpus is ~96k resident tokens (measured analog: the symlink analysis in
  `rules-metrics.md`). Kept as a lever for single genuinely-universal obligations.
- **Baseline `~/.qwen/rules/` rule** — rejected: machine-scope, single-client, duplicates the TOC.
- **Chosen stack** (design doc §2): L1 resident *deltas-only* critical section (AC-capped ≤ 45
  lines / ≤ 2,400 chars); L2 path-gated pointer rules; L3a PreToolUse gate (read-gate +
  no-oracle compound-command block); L3b repo-scope `.githooks/` (advisory signing locally);
  L3c CI (signature check over PR-introduced commits, `agentskills validate`); L4 `critical`
  registry subset in the metrics script (advisory `-Enforce`); L5 swarm-worker digest receipts
  (`sha256(body)[:12] @ line-count` — never canary tokens); L6 the same mandate in the opencode/
  ZCode king definitions.

**Honest framing:** this system enforces **exposure, not obedience**. Knowledge gaps (signing,
parent's missing merge-gate line) are fixed by residency; obedience gaps (merge gate violated while
resident) are fixed only by mechanical gates. The design does both, and claims only that.

## 6. Per-client outcome

| Client | Layers live |
| --- | --- |
| Qwen | full stack (L1–L4 + observation) |
| Kilo / ZCode primaries | L1 residency + L3b advisory + L3c CI (reads unobservable — L1 makes reads unnecessary by construction) |
| ZCode/opencode swarm workers | L5 digest receipts |
| opencode dispatch clones | L6 king mandate + L3b (once activated) + L3c |
| Safe-mode / bare Qwen | L3b + L3c only (all hooks disabled by design) |

Accepted limits and the rollout ladder (capture → warn → enforce, ≥ 7-day verification window,
branch-protection flip) live in the design doc §4–§6.
