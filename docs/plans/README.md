# Plans directory layout

Two states, two places:

- **Top level — still open.** A doc here is awaiting implementation or an owner
  decision. Each carries its own status header:
  - [`old-stack-decommission.md`](old-stack-decommission.md) — PLAN ONLY;
    executes on owner direction once the new listener has the Caddy route and
    has soaked.
  - [`grandparent-upstream-graft.md`](grandparent-upstream-graft.md) — PARKED,
    trigger-gated (only when something is needed from the grandparent repo).
  - [`turing-alpha-bot-account.md`](turing-alpha-bot-account.md) — PROPOSED;
    Phase A/B both need an explicit owner go/no-go.
  - [`dispatch-in-live-checkout.md`](dispatch-in-live-checkout.md) — LANDED
    (PR #23, merged 2026-09-19); retained at the top level as the living spec
    for the dual agent environments while M1/M2 items stay open.
  - [`SWARM_PARALLEL_COMPILATION_PLAN.md`](SWARM_PARALLEL_COMPILATION_PLAN.md) —
    upstream template surface (exists in `upstream/development` and is
    referenced by `.zcode/agents/swarm-orchestrator.md`). It stays at this path
    so upstream merges stay mechanical; its tiers 3–4 remain deferred upstream.
- [`completed/`](completed/) — landed and merged. Nothing here is pending; the
  docs are kept as the design history of the service, including the
  simplification plan that built it and the workflow-launch2 launcher fold
  (PR #20; its §9 follow-ups stay owner-gated).

When a top-level plan finishes (or a parked one is executed), move it into
`completed/` in the same change that lands the work, and repoint inbound
references.
