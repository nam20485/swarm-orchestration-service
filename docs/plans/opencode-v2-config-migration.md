# Plan: opencode v2 Config Migration

Status: PLAN — owner-approved direction 2026-10-16 ("the system has already upgraded to > v2");
tracking epic + stories filed on this repo
Date: 2026-10-16
Evidence base: everything below was observed or hand-probed live on 2026-10-16 against the
installed opencode **v2.0.31**, the running receiver (post-PR #38), and the
`intel-agency/gap-miner-v2-romeo37` clone. Line references are to those trees as of that date.
Related: PR #38 (spawn-side v2 fixes, merged `f156af6`), [`harness-trace-parity.md`](harness-trace-parity.md)
(S3–S6 remain), [`docs/plans/dispatch-in-live-checkout.md`](dispatch-in-live-checkout.md).

## Problem

The host's opencode CLI jumped 1.18.x → **2.0.31**, a breaking rewrite. PR #38 fixed the
receiver's spawn path (process cwd, lowercase `--log-level`, full env minus
`OS_WEBHOOK_SECRET`), and a dispatched session now runs end-to-end — but only because of
**live one-off workarounds applied to the romeo37 clone**. The launcher still stamps
v1-shaped config into every new clone, and v2 silently ignores most of it. Until the
template and credential strategy are migrated, every freshly stamped clone dispatch will
fail at model resolution, and the existing `gap-miner-v2-*` clones carry the same dead config.

## Findings (all first-hand, 2026-10-16)

1. **Project config moved to the repo root.** v2 loads `opencode.json`/`opencode.jsonc`
   from the project root (cwd upward to the git root), merged global → project. The
   `.opencode/` directory now supplies only `agents/`, `commands/`, `modes/`, `plugins/`,
   `skills/` — **`.opencode/opencode.jsonc` is no longer a config location**. The stamped
   clone config (providers, `default_agent`, permissions, MCP servers) was silently not
   loaded. (`opencode debug config` lists the loaded documents — the clone's file never
   appears.)
2. **The stamped file is also invalid JSON(C).** The template writes trailing commas
   (e.g. `"Authorization": "{env:Z_AI_API_KEY}",` + `}`) that v1's parser tolerated and
   v2 rejects.
3. **v2 ACP sessions start with no agent/model.** `session/new` rows land in the state DB
   with empty `agent`/`model`; resolution happens at prompt time. With no config loaded,
   the fallback is the **models.dev catalog default** — currently an nvidia model the host
   has no credentials for, failing as `Cannot initialize nvidia/…: Route.model requires an
   endpoint baseURL`. Once the config actually loads, `model`, `default_agent`, per-agent
   overrides (including the hidden `title`/`summary` agents, or the `small_model` key),
   and agent-def `model:` pins all work.
4. **Config `apiKey` is not a v2 credential source.** A custom provider block with a
   literal, verified-valid key still fails with `provider authentication required`;
   v2 takes credentials from auth.json (`/connect`, `opencode auth login`) or the
   provider facade's env chain (`Auth.optional(options.apiKey)` is reserved for the
   built-in facades). Proven live workaround: **override the catalog `anthropic` provider's
   `options.baseURL`** to the token-plan endpoint and pass the key via
   `ANTHROPIC_API_KEY` in the receiver env — the facade sends `x-api-key`, which the
   endpoint accepts (verified 200 with a real completion).
5. **The receiver env is the credential channel.** The ACP SDK's spawner trims the child
   env to an MCP-safe list (fixed in #38 by passing the env explicitly). The receiver's
   generated env file (`~/.config/webhook-receiver/env`) now carries the provider keys —
   and `Z_AI_API_KEY` must hold the **full `Bearer <key>` header value** there
   (`.agents/rules/tools.md`), or the Z.AI MCP endpoints answer a non-JSON-RPC error body
   and fail to connect.
6. **Long workflows hit the hard ladder.** The 2026-10-16 init dispatch (2.4k thought
   chunks, 50 tool calls, live gh queries) was killed cleanly at `acp run timed out after
   690s` (`ACP_STEP_TIMEOUT×3 + ACP_PROMPT_TIMEOUT`). The ceiling works; the knob may be
   too small for tracking-init workflows — and the harness-trace S5 idle watchdog is the
   right way to tell "working slowly" from "stalled".

## Workstreams (stories on the tracking epic)

**S1 — template & launcher: stamp v2-shaped config.** Parent template + launcher stamp a
root `opencode.json` (valid JSON — no trailing commas; v2 schema): `default_agent`,
`model` pin, agent overrides incl. `title`/`summary` (or `small_model`), provider blocks
(baseURL only — no secrets in the file), MCP servers. `.opencode/` keeps agents/commands/
skills. `strip-model-settings.ps1` updated for the new file layout. `.env.example`,
READMEs, docs mirrors updated. *Done when* a freshly stamped clone's `opencode debug
config` shows the root doc loaded, and a hand-run session picks the pinned agent+model.

**S2 — credential strategy (owner decision folded into the story):** env-facade pattern
(proven: provider override + facade env var in the receiver env file; survives clone
stamping, no secrets in git) vs auth.json seeding (`opencode auth login --method …
--answer key=…` headless, per host). Record the decision in `.agents/rules/tools.md` +
`lifecycle.md`. *Done when* a dispatched session on a freshly stamped clone reaches a
real model call with no manual clone edits.

**S3 — existing clones.** The `gap-miner-v2-*` fleet (and `romeo37`) carries dead v1
config. Decide: regenerate from the migrated template vs a small migration script vs
leave-and-document (dispatches to old clones fail at model resolution until touched).
romeo37 already carries the live workaround (root `opencode.json` + provider override +
king pin) — keep as the reference specimen.

**S4 — receiver knobs + watchdog.** Evaluate `ACP_PROMPT_TIMEOUT` (600 → larger) for
tracking-init workflows; land harness-trace **S5 idle watchdog** so stalls die early
instead of at the hard ceiling; fold S3 (noise filter) so the pane stays readable on long
runs. *Done when* a full init dispatch either completes or idle-times with a precise
reason in `prompt_consumed`.

**S5 — verification.** Fire a fresh relabel e2e on a newly stamped clone: issues created,
the Projects step runs (the `read:org` wall is confirmed gone — `gh project list --owner
intel-agency` returns data on the receiver token since 2026-10-16), artifacts complete in
the webui. *Done when* one dispatch completes the tracking-init workflow unattended.

## Non-goals

- No change to the sandbox path (SwarmSandbox provisioning is unaffected).
- No A2A, no new providers, no UI work beyond the webui width fix (PR #39).

## Effort & rollback

S1 is the bulk (~half a day with template plumbing + PRs across the chain); S2 is a
decision plus documentation; S3 depends on S2; S4 is the harness-trace remnant; S5 is the
gate. Everything is additive config — rollback is reverting the template PR; the receiver
side (#38) is already merged and independently correct.
