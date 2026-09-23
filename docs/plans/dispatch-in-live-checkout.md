# Dispatch into the live checkout (M1/M2)

Status: LANDED — M1 landed via PR #23 (merged 2026-09-19 as `5df5c59`);
retained at the top level as the living spec for the dual agent
environments; M1/M2 leftovers open.
Owner decision 2026-09-16 (this doc records it): dispatched sessions run
**sandbox-less, in the launcher-minted clone**, and the clone's primary
agent is a new **swarm-agent** (king) — the template `orchestrator` stops
being `default_agent`. The swarm-agent **runs dispatches himself** (the
init skill is a solo run — *not* swarmed); he escalates to a subagent swarm
only when the task earns it.

## Context

The 2026-09-15/16 incident ended with the receiver chain live (org webhook →
funnel → Caddy → receiver → queue; sender gate open for
`nam20485,intelagentone`). The remaining gap: envelopes must execute where
opencode + `gh` auth exist — the host, not the compose image (listener-only
by design; `ACP_ENABLED` now defaults false there). Old-topology lesson: the
orchestration agent worked *in the repo's clone*; the direct-body prompt is
bare (`/gh-issue-tracking-init`) and the skill defaults its target repo to
the cwd's GitHub repo — so **cwd = the checkout is load-bearing**, and a
scratch dir cannot work for this dispatch class.

## Research findings (2026-09-16)

- Clone `opencode.jsonc` sets `default_agent: "orchestrator"` (template
  default). Orchestrator is coordinator-managed: `edit: deny`, bash
  catch-all **deny** (headless rule: an `ask` is unanswerable — DENY steers
  to delegation), `skill: allow`. Works, but forces delegation even for a
  trivial skill run → the pivot below.
- Skills are discovered from `.agents/skills/` (also `.opencode/skills/`,
  `~/.agents/skills/`) and surface to the agent as invocable skills; a
  prompt naming one resolves via the skill tool. The TUI slash palette is a
  client nicety (optional `slash: true` frontmatter) — not needed over ACP.
- ACP host answers every permission ask programmatically (deny-regex →
  reject; read-only kinds → allow; else `ACP_DEFAULT_PERMISSION`), so the
  historical interactive-freeze cannot recur; worst case is a clean denial.
- `gh-issue-tracking-init` is self-contained (vendored scripts, templates,
  labels) and idempotent.

## M1 — init dispatch completes in the minted checkout

1. **This PR** (`dev/acp-clone-workspace`): `ACP_CLONE_ROOT` seam — session
   cwd = `<root>/<repo name>` (fail-closed if missing; deny-config skipped
   outright — a lived-in checkout is never written into, seeded config or
   not; the runtime permission policy is the backstop); compose pins
   `ACP_ENABLED=false`; docs/env surface synced; tests.
2. **swarm-agent seeding** (follow-up, launcher scripts in this repo):
   seed `.opencode/agents/swarm-agent.md` into clones and switch
   `default_agent` to it in the post-clone transforms (the launcher already
   rewrites `opencode.jsonc` — permission shorthand, model-pin strip; the
   template repos stay untouched). Sketch of the king's rules:

   - Every dispatch lands on you. You are the agent-in-charge of this repo —
     run it yourself by default: execute skills, make edits, run scripts,
     publish branches/PRs/labels.
   - Do **not** auto-swarm. Escalate to a subagent swarm on exactly two
     triggers: **(a)** the work is genuinely large or parallelizable, or
     **(b)** the dispatch explicitly directs a swarm. Neither alone is
     required — a directive swarms even a modest task; huge work with no
     directive is your judgment call. If one session can finish it and
     nobody said swarm, finish it.
   - The `/gh-issue-tracking-init` dispatch is always a solo run.
   - Post-init epic implementation dispatches are the expected swarm case:
     the launcher-seeded `plan_docs/` are agent-team handoff specs
     (e.g. gap-miner-v2: an 810-line development plan of atomic,
     context-window-sized tasks) — those dispatches will carry the swarm
     directive; fan out across the story/task boundaries the plan defines.
   - End every turn with a short status (done / blocked / next).
   - Permissions: author it allow-first (bash/edit allow) with targeted
     denies; the seeder's coordinator-skip must not apply to it.

   > **LANDED 2026-09-23, differently than sketched (owner direction):** the
   > king already existed — `swarm-orchestrator` in `.zcode/agents/` is the
   > king of the swarm; dispatches land on him and he runs them himself
   > (init always solo). Seeding = **opencode ports** of the whole
   > `swarm-*` roster into `.opencode/agents/` (native opencode frontmatter,
   > `mode: primary` king + `mode: subagent` workers, rules mirrored
   > word-for-word) + `default_agent: swarm-orchestrator` in
   > `opencode.jsonc`, landed in the parent template (swarm-context) so
   > clones stamp with them — no launcher seeding stage needed. The
   > coordinator quartet stays available (additive rule). The allow-first
   > bash/edit permission shape landed as sketched.
3. **Host-run cutover** (ops, owner-witnessed): `.env` gains
   `ACP_CLONE_ROOT=~/src/github/nam20485/dynamic_workflows`; run the
   receiver host-side (`.venv/bin/python -m webhook_receiver`, env loaded);
   repoint the funnel to the host listener (`127.0.0.1:8080`) and stop the
   compose receiver — or keep Caddy and proxy to the host (decision below).
4. **Fire**: relabel `gh-issue-tracking:direct-body` on
   `intel-agency/gap-miner-v2-papa26` issue #1. Done when: the session runs
   the skill in the checkout; labels/milestones/Plan/Epic/Stories appear;
   the completion label event arrives back at the receiver (chain closes).

## Dual agent environments (owner decision, 2026-09-16)

Exactly two mutually exclusive environments; chosen at repo init and fixed —
nothing chooses per dispatch, and modes never mix:

1. **clone** — the launcher's main checkout; no sandbox, no worktree.
2. **sandbox** — SwarmSandbox-provisioned workspaces.

- Recorded once by the launcher at repo creation in two places so every
  reader sees the same fact: a GitHub repo variable (e.g.
  `AGENT_ENVIRONMENT=clone|sandbox`) — the service resolves the workspace
  per envelope from it (cached; missing/unknown fails closed) — and a line
  in the repo's AGENTS.md instance section for in-repo readers (the
  swarm-agent and skills: lived-in checkout vs disposable workspace).
- Today's host knobs (`ACP_CLONE_ROOT`, `SANDBOX_ENABLED`) remain the
  boot-time global posture; wiring the per-repo marker as the authority is a
  small follow-up at the existing `AcpHost.run` seam (variable lookup +
  cache; the sandbox bridge already exists behind it).
- The earlier worktree-per-impl idea is **not** a third environment — if it
  survives at all it is a clone-mode refinement for parallel impl streams
  (the king swarming inside a lived-in clone), decided separately.
- Open (owner): the criteria for initializing a repo as sandbox, and the
  default for new repos.

## M2 — swarm implementation dispatches

Same mechanism, heavier payloads: `implementation:ready` /
`orchestration:*` labels build orchestration prompts (Phase 3 builder) that
the swarm-agent executes — solo or swarmed per his rules. The expected swarm
case is post-init epic/implementation dispatches: the seeded
`plan_docs/` development plans are atomic agent-team handoff specs sized for
fan-out, and those dispatches will carry explicit swarm directives. The
single FIFO consumer serializes bursts (no `.git/index.lock` collisions); a
**worktree-per-impl-dispatch** remains the deferred isolation option, with a
natural seam in the label-class branch of `prompt_builder` → workspace
policy — with the king swarming inside a lived-in clone, per-worker
worktrees become the way parallel impl streams stop colliding. Sandbox
revival stays parked (trigger: true throwaway isolation need).

## Open questions

- Funnel repoint ownership (owner's tailscale) — direct `:8080` (simpler,
  but `/events` becomes publicly reachable) vs Caddy-to-host (keeps the
  minimal public surface; needs a Caddyfile/compose tweak).
- Agent name (`swarm-agent`? something else) and whether the coordinator
  quartet (orchestrator/team-lead/team-orchestrator/planner) stays available
  to the king as subagents or gets pruned from clones.
- Envelope-branch checkout: M1 ignores it (fresh clones sit on their seed
  branch); worktree mode (M2) should make it explicit.
