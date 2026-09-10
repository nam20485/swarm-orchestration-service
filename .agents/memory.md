# Project Memory

## Current Activity

Current project and its sub-work items that we are working on actively. Items move to "Completed Work Items" when done.

### Project: Swarm-orchestration-service (this repo, bootstrapped 2026-09-10)

- **Repo purpose**: implement [`docs/plans/orchestrator-service-simplification.md`](../docs/plans/orchestrator-service-simplification.md) (APPROVED; all §5 decisions folded; §6 unknowns resolved by the spike) — PromptInfo queue feeding an ACP host replacing the old `orchestrator-service` dispatch. Requirements source: [`docs/plans/orchestrator-service-integration.md`](../docs/plans/orchestrator-service-integration.md). Listener/GitHub-auth code ported from `nam20485/orchestrator-service` @`2bd6d06` (reference only, untouched).
- **Phase 0 (overnight delegated run, 2026-09-10)**: 0.0 and 0.1 LANDED (see Completed); 0.2 PromptInfo design doc landed this PR ([`docs/plans/promptinfo-design.md`](../docs/plans/promptinfo-design.md)) — typed export-ready envelope, in-process `asyncio.Queue`, delivery-id dedup, EventStore fed `prompt_queued`/`prompt_consumed`/`webhook_duplicate`, explicit no-durability posture (GitHub redelivery is the recovery path), consumer contract Phase 1→2. Also mirrors the owner directive "any failing workflow ⇒ run `fix-failing-workflows` skill" into source-control rules.
- **Next**: Phase 1 per plan §7 — queue seam (define `PromptInfo`, listener enqueues, consumer dequeues into the existing dispatch path, dashboard events; no behavior change).

## Completed Work Items

- **Phase 0.1 — ACP spike** (PR #3, merge `719c009`, CI green; cold-verified by coordinator re-runs): round-trip PASS on `agent-client-protocol==0.12.1` + opencode 1.18.30 (`initialize` → `session/new` → prompt → `session/update` stream → `end_turn`); **deny paths PASS** — host auto-`reject_once` on `session/request_permission` → tool `failed` → `end_turn` 94 ms later, no hang; `permission.bash:"deny"` intercepts pre-prompt (zero requests, "unavailable tool"). §6 unknowns resolved: `acp` floor **v0.15.10**; `--auto` does not exist for `acp` (permission is config + host responses only); `--port/--mdns/--cors` = HTTP companion endpoint (default port 0 = stdio only). Spike: `spikes/acp/` (re-run steps in its README). Notable: config-deny is *pre-prompt interception*, stronger than expected — Phase 2 can use it as the primary fail-closed layer.
- **Phase 0.0 — listener port + compose skeleton** (PR #2, merge `cdb3d4d`, CI green): `src/webhook_receiver/` — FastAPI app (verify 401 → ping 200 → JSON 400 → size 413 → store → gate), HMAC `github.py` verbatim from @`2bd6d06`, `should_dispatch` gate incl. fail-closed direct-body allowlist, SSE `EventStore`; pytest 47 @ 94.79%; compose = webhook-receiver + digest-pinned Caddy (`/webhooks/github` + `/health` only, 404 catch-all; **no** `orchestratorservice` container); `validation.ps1` python branch (venv bootstrap, ≥85% coverage gate, graceful skip). Dispatch stubbed → Phase 1.
- **Bootstrap** (PR #1, merge `06672c5`): clone de-contaminated (parent Class 2 plan docs pruned, swarm-metrics scaffold, memory reset, workspace file renamed); base grafted onto `upstream/development` `0d9c7dd` (fork-style per Decision 8 — template-route seeds land squashed; fixed via `remote add` + fetch + `reset --soft` + force-push while trees matched); branch-protection ruleset recreated (deletion + non-ff + 1-approval PRs, admin bypass); milestones `bootstrap`/`phase-0`.

## Decisions

- **Repo linking: fork-style upstream remote** (plan §5 Decision 8): swarm-context stays the swarm-harness source of truth; this repo merges `upstream/development` on demand, each sync a reviewed PR. Keep edits to shared template files (README, `.agents/rules/`, `.zcode/agents/`, AGENTS.md) minimal and upstream of product code so merges stay mechanical.
- **ZCode MCP config cannot be committed with secrets** (verified 2026-09-10): `config.json` supports no env-var interpolation — `env`/`headers` values are literal; http servers get no env fallback (endpoint 1001s without the header). Pattern: real `.zcode/config.json` gitignored; `.zcode/config.example.json` committed. OpenCode's `{env:VAR}` is why `.opencode/` config can be committed.

## Remember To Do

- **`thoughtLevel: off` blocks GLM-5.3-Flash worker spawning entirely** (carried from upstream, observed 2026-09-10): either drop it from the worker defs, pin worker models that support off, or get harness support. Resolve before the next swarm run.
- **Align `swarm-state.ps1` budget with concurrent-not-all-time semantics** (carried from upstream): track in-flight (pending/running) tasks; update `.agents/rules/swarm.md` § Budget + the skill.
- **Per-run telemetry archiving** (carried from upstream): automate copying worker model-io JSONLs to `.swarm/<run-id>/telemetry/`.
- **SwarmSandbox AppHost never run end-to-end by any gate** (carried known-gap): manual `dotnet run` smoke when next needed.
- **Projects board** still unset on this repo (token lacks `read:org`; milestones + ruleset done). PRs currently carry milestone only.
- **Owner cleanup list (morning)**: consolidate GITHUB_TOKEN sources (delete the line from environment.d and `~/.api-keys-export.sh`, let the keyring govern; `unset && gh auth login` ritual becomes unnecessary); optional PAT rotation (one token was echoed into a session's output once during diagnosis).
