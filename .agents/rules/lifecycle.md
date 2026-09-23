# Repository & Clone Lifecycle

The approved map of who seeds whom (owner-approved 2026-09-23, provenance
report: [docs/4-repo-system-lifecycle.md](../../docs/4-repo-system-lifecycle.md)) —
load this before touching the launcher, the templates, the dispatch chain,
or hunting for anything "missing" inside a clone. Per-script inventory and
stage-by-stage pipeline detail live in [scripts.md](scripts.md); the
dispatch plan of record in
[docs/plans/dispatch-in-live-checkout.md](../../docs/plans/dispatch-in-live-checkout.md).

## Five roles (who seeds whom)

1. **This repo** — `nam20485/swarm-orchestration-service`: the lifecycle
   owner. The launcher (`scripts/create-repo-agent-context.ps1` and stage
   scripts), the webhook receiver (`src/webhook_receiver`), the ACP
   dispatch host, the SwarmSandbox solution (`src/SwarmSandbox` — the
   service runs it, the parent template does not carry it), and the ZCode
   swarm system (`.zcode/agents/`, [swarm.md](swarm.md)) live here.
   `isTemplate: false` — never a stamper itself.
2. **`nam20485/swarm-context`** — **the parent template (the clone
   stamper)**: `isTemplate: true`, public, default branch `development`,
   pruned to **"agent-context base + swarm surfaces"** (owner decision
   2026-09-23): the full ZCode swarm set (`.zcode/agents/swarm-*.md` —
   byte-identical to this repo's), `.agents/rules/swarm.md` +
   `swarm-workers.md`, the `$swarm` and `swarm-plan` skills, and the
   agent-context base tree — nothing service-side.
3. **`intel-agency/agent-context`** — the grandparent: the upstream base
   of the parent (one-way reviewed-PR flow; the parent's `upstream` push
   is DISABLEd). Historical note: **it was the stamper before the
   2026-09-23 flip** — every clone minted before then (all
   `gap-miner-v2-*`) carries its tree, which is why they have no
   `.zcode/` and `default_agent: "orchestrator"`.
4. **`nam20485/workflow-launch2`** — the `plan_docs/` app-plan slug store
   (read via `-PlanDocsRoot` from the sibling checkout; deliberately not
   folded in). **Stale launcher copies still sit in its `scripts/`** —
   always run the launcher from this repo, never from there.
5. **The dispatch clones** — `intel-agency/<slug>-<suffix>` (suffix = NATO
   word + number: `alpha61`, `charlie11`, …), checked out at
   `~/src/github/nam20485/dynamic_workflows/<repo>`. Lived-in opencode
   workspaces; the ACP host's dispatch sessions run inside them
   (`ACP_CLONE_ROOT`).

## Launch chain (minting a repo)

```text
./scripts/create-repo-agent-context.ps1 -Slug <app_plan_doc_slug> -Yes
  ===> intel-agency/<slug>-<suffix>   (suffix ∈ NATO: alpha, bravo, charlie, …)
```

Stage 1 stamps the base tree from `nam20485/swarm-context` (GitHub
template route ⇒ squashed seed, no git ancestry; `gh repo view <clone>
--json templateRepository` records the source), copies the slug's plan
docs, rewrites placeholders + AGENTS.md instance identity, then:
Class-2 cleanup → headless permissions → model-pin strip → amend seed
commit → labels import → dispatch issue #1 (`/gh-issue-tracking-init`
under `gh-issue-tracking:direct-body`) awaiting relabel.

## Envelope path (webhook → agent session)

org webhook (intel-agency) → funnel (tailscale) → Caddy (`webhook-proxy`)
→ receiver (`webhook-receiver`, compose; **listener-only**,
`ACP_ENABLED=false` — the image has no opencode) → PromptInfo queue →
consumer. Dispatch executes **host-side**: host-run receiver with
`ACP_ENABLED=true` +
`ACP_CLONE_ROOT=~/src/github/nam20485/dynamic_workflows`, one cold opencode
session per envelope, cwd = the clone (cwd-is-clone is load-bearing for
`/gh-issue-tracking-init`).

## What a minted clone contains

Post-flip clones (stamped from swarm-context) carry the agent-context base
(template opencode octet, `default_agent: "orchestrator"`, helper
scripts, `.agents/` system) **plus the full swarm surfaces** —
`.zcode/agents/` (ZCode parity), swarm rules, `$swarm` / `swarm-plan`
skills — plus `plan_docs/`, the 32 dispatch labels, and issue #1.

Pre-flip clones (every `gap-miner-v2-*` minted before 2026-09-23) carry
the agent-context tree only: **no `.zcode/` — never seeded, never
deleted**; their stamper simply didn't have it. That was the answer to
the original "who killed `.zcode/`" question: nobody — it was never
there.

## ACP client parity rule (owner decision, 2026-09-22)

Two ACP clients are in play and **both are kept**: opencode (clone-mode
dispatch, the first client) and ZCode (the sandbox runs ZCode with its
`.zcode/` config). Everything stays in parity between them — agent
definitions and client configs exist on both sides, mirrored. Rule for any
additional ACP client: (1) **additive** — adding a client never removes or
breaks the ones already driven; (2) **mirror the existing ACP client
configs** — same agent set, same rules and intent, expressed in the new
client's native format. Swarm-surface edits land in the **parent template**
(so they stamp into clones) and sync down here via the reviewed-PR
upstream flow.

## Agent-definition map (which harness reads which directory)

| Harness | Directory | Swarm defs? |
| --- | --- | --- |
| ZCode — swarm workers | `.zcode/agents/` (parent template + this repo, byte-identical) | yes — the `swarm-*.md` set |
| ZCode — global | `~/.zcode/agents/` | no (octet only) |
| opencode — user level | `~/.config/opencode/agent/` | no |
| opencode — clone level | `<clone>/.opencode/agents/` | no (template octet) |

The ACP dispatch path drives **opencode** — ZCode definitions are invisible
to it. The M1 king (opencode `swarm-agent.md` + `default_agent` flip) is
still to author — per the parity rule, author both client sides in one
move and land them in the parent template so they stamp into clones.
