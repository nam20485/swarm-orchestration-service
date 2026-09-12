# Old-Stack Decommission Plan — `orchestrator-service`

Status: PLAN ONLY — nothing here has been executed. Execute only on owner
direction, after the new listener has taken the Caddy route and soaked.
Date: 2026-09-11
Related: [`completed/orchestrator-service-simplification.md`](./completed/orchestrator-service-simplification.md)
(§2 old-stack map, §7 Phase 5)

## 1. Scope

What gets retired when `nam20485/swarm-orchestration-service` becomes the
webhook target:

| Old component (orchestrator-service @2bd6d06) | Disposition |
|---|---|
| `orchestratorservice` compose service (always-on `opencode serve`, :4099) | **Delete** — the new ACP host spawns one-shot `opencode acp` per envelope; no agent server exists in the new repo |
| old `webhook-receiver` compose service (bespoke dispatch, BackgroundTasks + Popen) | **Stop, then remove** — replaced by the new listener (PromptInfo queue → ACP host) |
| old `webhook-proxy` (Caddy: `/webhooks/github` + `/health` only) | **Stop, then remove** once the GitHub App webhook URL points at the new stack's Caddy |
| old repo working tree | **Freeze read-only** — stays as the reference implementation at `2bd6d06` (plan §2); no deletes, no force-pushes, no new branches |

Not in scope: anything in `nam20485/swarm-orchestration-service`, SwarmSandbox
deployment, GitHub App credential lifecycle (only its webhook URL/secret
change).

## 2. Preconditions (all must hold before cutover)

- [ ] New stack deployed and reachable: compose up, Caddy healthy
      (`GET /health` -> 200 through the public route).
- [ ] Full validation green on the deployed revision
      (`pwsh -NoProfile -File ./validation.ps1`).
- [ ] One signed test delivery accepted end-to-end on the new stack (the
      `scripts/e2e-orchestration.ps1` scenarios pass against the deployment,
      or a manual ping + labeled webhook against a scratch repo).
- [ ] `OS_WEBHOOK_SECRET` value chosen for the cutover (see §3 step 3) and
      staged in the new stack's `.env` — never committed.
- [ ] Rollback path rehearsed on paper (§4) and the old compose project name
      / directories recorded.
- [ ] A quiet window chosen: no in-flight orchestration label workflows on
      any tracked repo (in-flight runs belong to the old stack's semantics).

## 3. Cutover steps (in order; each step is its own verified action)

1. **Quiesce the old stack.** `docker compose stop webhook-receiver` in the
   old deployment so no delivery is processed by both stacks mid-cutover.
   Leave the old Caddy up for the moment so GitHub gets a hard failure
   rather than a connection refused if it delivers during the window (GH
   retries on non-2xx anyway).
2. **Point the GitHub App webhook at the new stack.** In the GitHub App
   settings, set the webhook URL to the new stack's public route (same path
   `/webhooks/github`; the new Caddy exposes the identical contract, plus a
   404 catch-all).
3. **Rotate the webhook secret (recommended).** Set a fresh
   `OS_WEBHOOK_SECRET` in the new stack's `.env` and the same value in the
   App settings, then `docker compose up -d webhook-receiver` on the new
   stack. Rotation is cheap now and guarantees the frozen old stack could
   not act on a replayed delivery even if it were restarted by accident.
4. **Verify the handshake.** `GET <new-public-route>/health` -> 200; deliver
   a GitHub **ping** (App settings "Redeliver" a ping or re-save the App
   settings to trigger one) and confirm `pong` and a `webhook_received`-free
   log (pings emit no events) plus HTTP 200 in the App's recent-deliveries
   view.
5. **Canary with a real dispatch.** Apply a workflow label
   (`orchestration:*` or `implementation:ready`) to an issue on a scratch
   repo and confirm the new stack's `GET /events` shows the full
   `webhook_accepted` -> `prompt_queued` -> `prompt_consumed` sequence with
   an agent session (ACP enabled in that deployment).
6. **Take the old stack down.** In the old deployment:
   `docker compose down` (removes `orchestratorservice`, old
   `webhook-receiver`, old `webhook-proxy` and their networks). No volumes
   need preserving — the old stack kept no state the new stack depends on.
7. **Freeze the old repo.** Confirm `nam20485/orchestrator-service` is at
   `2bd6d06` (or its then-current default), archive/mark read-only, and add
   a short README note pointing at this repo. Keep it cloned somewhere as
   the regression reference (the old clause-table prompt is the Phase 3
   regression checklist per plan §8).
8. **Record the cutover.** Note the date, the App webhook URL change, the
   secret rotation, and the old compose project removal in this repo's
   memory file (`.agents/memory.md`).

## 4. Rollback procedure

Trigger if the new stack cannot healthily receive deliveries and the old
stack is still intact (steps 1-6 of §3 are individually reversible until
`compose down`):

1. **Repoint.** In the GitHub App settings, set the webhook URL back to the
   old stack's public route.
2. **Restore the secret the old stack knows.** If step 3 of §3 rotated it,
   set the App's webhook secret back to the old stack's `OS_WEBHOOK_SECRET`
   value. (If the old stack was left with its original secret, this is a
   no-op — which is exactly why rotation and rollback must be decided
   together before cutover.)
3. **Bring the old stack back.** `docker compose up -d` in the old
   deployment (all three services; the `orchestratorservice` container
   starts cold in seconds).
4. **Verify** with a ping and a canary label on the scratch repo, then stop
   the new listener (`docker compose stop webhook-receiver`) so the two
   stacks never run concurrently on the same secret.
5. Post-mortem in this repo before re-attempting cutover.

After `compose down` (step 6 of §3) rollback is no longer hot: it requires
rebuilding the old containers from the frozen repo — acceptable only because
the window before that step is where instability would surface.

## 5. Final checklist

- [ ] GitHub App webhook URL -> new stack; recent deliveries all 2xx
- [ ] Webhook secret rotated; old stack's value no longer valid anywhere
- [ ] `GET <new-route>/health` -> 200; `/events` streams on the internal path
- [ ] Canary label produced a full accepted -> queued -> consumed -> agent
      session run on the new stack
- [ ] Old compose project down (`docker compose ps` empty in that directory)
- [ ] Old repo frozen read-only at its reference revision; README pointer
      added
- [ ] New stack's `validation.ps1` green on the deployed revision
- [ ] Cutover recorded in `.agents/memory.md`
