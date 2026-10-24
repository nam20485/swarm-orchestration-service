# Plans directory layout

Two states, two places:

- **Top level — still open.** A doc here is awaiting implementation or an owner
  decision. Each carries its own status header:
  - [`old-stack-decommission.md`](old-stack-decommission.md) — PLAN ONLY;
    executes on owner direction once the new listener has the Caddy route and
    has soaked.
  - [`charlie68-incident-followups.md`](charlie68-incident-followups.md) —
<<<<<<< HEAD
    DECIDED 2026-10-24, ready for implementation (D1 a+b driver liveness +
    chunking; D2 = migration S1 with `zai-coding-plan/glm-5.3`; D3 template
    case-guard; D4 canary; D6 autonomous PR cycle — 3-round budget, green +
    zero-threads merge). Out of the 2026-10-23 charlie68 incident.
  - [`rev2-state-map-design.md`](rev2-state-map-design.md) — IN OWNER
    FEEDBACK (final pass pending): the C-design orchestration prompt — one
    compact rev2 state map + canonical contracts replacing the vague Phase-3
    directions (mechanical knowledge, dynamic execution), absorbing D6's
    autonomous PR cycle, adding durable memory/rules division of labor, and
    sequencing Stages 0–5 across the charlie68 follow-ups. Supersedes PR
    #53's mechanical design (kept for posterity).
  - [`grandparent-upstream-graft.md`](grandparent-upstream-graft.md) — PARKED,
    trigger-gated (only when something is needed from the grandparent repo).
  - [`turing-alpha-bot-account.md`](turing-alpha-bot-account.md) — PROPOSED;
    Phase A/B both need an explicit owner go/no-go.
  - [`webui-plan.md`](webui-plan.md) — COMPLETE (W0–W2 merged as #35–#37 on
    2026-10-15/16); W3 exposure is owner-parked — the page stays
    listener-local (loopback/SSH tunnel only).
  - [`opencode-v2-config-migration.md`](opencode-v2-config-migration.md) — PLAN
    (owner-approved direction 2026-10-16); migrate the stamped clone config
    surface to opencode v2: root `opencode.json`, credential strategy, the
    existing clone fleet. PR #38 already fixed the receiver's spawn side.
  - [`harness-trace-parity.md`](harness-trace-parity.md) — IN PROGRESS;
    S1 (stderr trace capture), S2, and S5 (idle watchdog) landed; the S3
    noise filter, S4 golden `harness.log` rendering, and S6 docs are
    unstarted.
  - [`qwen-code-features-for-the-swarm.md`](qwen-code-features-for-the-swarm.md)
    — NEEDS PLANS; a harvested shortlist of Qwen Code features to evaluate
    for the swarm (e.g. the evidence-based verification policy), each item
    awaiting its own plan.
  - [`skill-plan.md`](skill-plan.md) — REVISED (Option A selected; the owner
    answers are recorded under Design decisions); the natural-language
    orchestration skill awaits implementation.
  - [`skill-plan-review.md`](skill-plan-review.md) — companion cross-check
    review of `skill-plan.md`'s claims against the tree; kept alongside the
    plan it audits.
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
