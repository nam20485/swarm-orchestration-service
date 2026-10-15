---
name: docker-service-monitor
description: Monitor a live orchestrator-service Docker Compose run in real time, give the user periodic status updates, and on completion (success, failure, or watchdog abort) produce a root-cause report. Use when the user asks to monitor a docker service run, watch an orchestrator run, tail docker compose logs, diagnose an aborted run, investigate a watchdog abort or permission deadlock, or generate a run report. Covers streaming orchestratorservice + webhook-receiver logs, correlating opencode session steps with watchdog signals, and writing a traces/<repo>-run-report.md with evidence-backed diagnosis.
---

# docker-service-monitor

Monitor an **in-progress** orchestrator-service Docker Compose orchestration run, narrate it to the user, and on completion diagnose the definitive root cause with evidence. This skill does NOT start the run — it attaches to a run that is already (or about to be) in flight.

## Stack facts (verified — use these exact values)

- Project repo: `orchestrator-service`. Runs via Docker Compose (NOT Swarm). Compose file: `compose.yaml` at repo root.
- All commands use `docker compose -f compose.yaml ...` run from the repo root.
- The three services:
  - `orchestratorservice` — the opencode headless server (port 4099). Hosts the agent session that does the real work. Logs agent steps, permission evaluations, and tool calls.
  - `webhook-receiver` — receives GitHub webhooks, dispatches the opencode run, and runs the **watchdog** that detects deadlocks and aborts stuck sessions.
  - `webhook-proxy` — Caddy fronting the webhook receiver (port 80). Rarely relevant for diagnosis; check only if webhooks are not arriving.
- Host `WORKSPACE_DIR` (in `.env`, default `/home/nam20485/orchestrator-workspace`) is mounted to `/workspace` in both `orchestratorservice` and `webhook-receiver`.
- The opencode server log is shared between containers via the `opencode-logs` volume: written at `/home/app/.local/share/opencode/log/opencode.log` by `orchestratorservice`, read read-only at `/var/log/opencode-server/opencode.log` by the `webhook-receiver` watchdog.

## When to use / NOT to use

USE when: a run is live or just finished and the user wants it watched, narrated, and/or diagnosed into a report.
DO NOT use to: start a run, edit app code, restart the stack, or tail logs indefinitely without a monitoring goal. For a one-off log glance, just run a logs command directly.

## Detection signals (what each phase looks like)

A run begins when a GitHub issue webhook arrives.

- **Start:** `webhook-receiver` logs `Webhook received delivery_id=... event=issues ...`, then the runner starts opencode.
- **Session created:** `orchestratorservice` logs `message="creating instance" directory=/workspace/<repo>` then `message=created id=ses_...` (the session id — capture it).
- **Work in progress:** `orchestratorservice` logs repeated `message=loop session.id=ses_... step=N` and `message=stream providerID=... modelID=...`.
- **Permission deadlock (the #1 failure mode):** `orchestratorservice` logs `message="asking id=per_... permission=<tool> patterns=[...]"` that never resolves; then `webhook-receiver` logs `[watchdog] PERMISSION DEADLOCK unanswered ask ask_age=...`.
- **Abort:** `webhook-receiver` logs `[watchdog] ... — terminating`, then `server session aborted url=.../session/<ses>/abort status=200`, then `orchestratorservice` logs `message=process ... error=Aborted`.
- **Success/completion:** `webhook-receiver` opencode output shows publish/close/comment actions; the runner posts a final comment and closes the issue. Look for `publish`, `closed`, or the run report being written.

## Workflow

1. **Confirm the stack is up and identify the active session.** Run a snapshot (do NOT tail yet):
   `docker compose -f compose.yaml ps`
   Then read the most recent activity to find the current `ses_...` and the triggering webhook:
   `docker compose -f compose.yaml logs --since=10m orchestratorservice webhook-receiver 2>&1 | grep -iE "Webhook received|creating instance|created id=|loop session|asking id=|PERMISSION DEADLOCK|abort|Aborted|publish|closed"`
   Capture: repo name, run/delivery id, session id, trigger (event + label/body), start time.

2. **Read the exemplar report FIRST if it exists** so your output matches house style:
   `traces/gap-miner-v2-golf38-run-report.md`
   Mirror its structure exactly (see "Report structure" below).

3. **Tail the live run.** Stream both relevant services (ctrl-C / stop the tail yourself between updates — do not leave it running forever):
   `docker compose -f compose.yaml logs -f --tail=50 orchestratorservice webhook-receiver`
   If you only need the server side:
   `docker compose -f compose.yaml logs -f --tail=100 orchestratorservice`

4. **Give the user periodic status updates** while the run is live (see "Status updates" below). Keep monitoring until the run reaches a terminal state (success, watchdog abort, dispatch timeout, or user kill).

5. **On completion, gather evidence for diagnosis.** Pull:
   - The `orchestratorservice` log tail around the abort/completion:
     `docker compose -f compose.yaml logs --since=30m orchestratorservice`
   - The `webhook-receiver` watchdog/runner lines:
     `docker compose -f compose.yaml logs --since=30m webhook-receiver 2>&1 | grep -iE "watchdog|PERMISSION DEADLOCK|abort|terminating|publish|closed|Webhook received"`
   - The merged key-event filter for the whole window:
     `docker compose -f compose.yaml logs --since=30m orchestratorservice webhook-receiver 2>&1 | grep -iE "loop session|asking id=|stream provider|PERMISSION DEADLOCK|abort|Aborted|Webhook received|publish|closed"`

6. **Run root-cause analysis** (see "Root-cause analysis" below). Determine the ONE definitive upstream cause with exact log lines as evidence. The watchdog abort is CORRECT behavior — say so and explain what it was protecting against.

7. **Collect config provenance** for the cause. Inspect the project-level and global opencode config and agent frontmatter (see "Config provenance commands").

8. **Write the report** to `traces/<repo-name>-run-report.md` using the structure below. Quote exact log lines (with timestamps) and cite the config file/line each conclusion comes from.

9. **Report back to the user:** give a 3-5 line summary — outcome, definitive root cause in one sentence, the recommendation, and the absolute path of the report file.

## Status updates (while live)

- Post a short progress line roughly every 1-2 minutes OR when a notable event occurs (new step, subagent delegation/spawn, permission ask, API error, completion/abort).
- ALWAYS quote the live `step=N` and `session.id=ses_...` so the user can correlate, e.g.: "`ses_072f0d...` step 7, reading plan assets…".
- Do NOT spam. One line per notable change. If the run is in a long generation stall (step not advancing, server log mtime stale), say so once and note the watchdog idle timers are climbing.
- Flag immediately when you see an `asking id=per_...` that does not resolve — that is the signature of the deadlock.

## Root-cause analysis

Gather the three evidence sources above, then check these known recurring failure classes IN ORDER. Identify the single upstream cause (not the symptom, not the watchdog's response).

1. **Permission deadlock (most common).** An `ask` on `bash` / `edit` / `external_directory` / `webfetch` that headless mode cannot answer. Signature: `orchestratorservice` `message="asking id=per_..."` with no follow-up resolution, then `webhook-receiver` `[watchdog] PERMISSION DEADLOCK`. Root cause is usually a project-level `.opencode/opencode.jsonc` `permission` object (e.g. `{ "websearch": "allow" }`) narrowing the global blanket `"allow"`, and/or agent frontmatter with `ask` values, and/or (for task-spawned subagents) the opencode v1.18.4 subagent-permission inheritance bug where `external_directory` rules are not inherited / are clobbered. Inspect the project config and agent files (see "Config provenance commands"). NOTE: a watchdog abort here is CORRECT — the cause is the upstream unanswerable prompt, not the kill.

2. **Dead `small_model`.** A project `small_model: google/gemini-3.5-flash` overriding the global working `zai-coding-plan/glm-4.5-air`, causing `AI_LoadAPIKeyError` on title dispatches. This is **non-fatal** (swallowed) — note it but do not mistake it for the cause of a stall.

3. **Transient API errors.** `AI_APICallError` / "service temporarily overloaded" on glm-5.2 — usually auto-retried and **non-fatal**. The run does not die here; it dies on what the model tried AFTER recovering. Distinguish the symptom from the cause.

If none match, examine the raw log tails for a different failure class (e.g. dispatch timeout `DISPATCH_TIMEOUT_SECS` at 2700s, hard ceiling `HARD_CEILING_SECS` at 5400s, runner crash, missing env var) and document with evidence.

## Config provenance commands

- Global opencode config inside the container:
  `docker compose -f compose.yaml exec -T orchestratorservice cat /home/app/.config/opencode/opencode.json`
- Project-level config (replace `<repo>`): `${WORKSPACE_DIR}/<repo>/.opencode/opencode.jsonc` on the host, or `/workspace/<repo>/.opencode/opencode.jsonc` in the container:
  `docker compose -f compose.yaml exec -T orchestratorservice cat /workspace/<repo>/.opencode/opencode.jsonc`
- Project agent definitions:
  `docker compose -f compose.yaml exec -T orchestratorservice ls /workspace/<repo>/.opencode/agents/` then `cat` each `*.md` (check frontmatter `permission` and `ask` values).
- Container/env state:
  `docker ps --filter "name=orchestrator-service"`

## Report structure (mirror `traces/gap-miner-v2-golf38-run-report.md`)

Write to `traces/<repo-name>-run-report.md`. Sections, in order:

1. **Title** — `# Run Report — <repo> (<short outcome>)`.
2. **Header block** (bold key/value): Repo, Run ID, Session, Trigger (event + label/body), Window (start -> end UTC, duration, how it ended), Outcome (one-line: success / aborted by watchdog / aborted by user / timed out).
3. **TL;DR table** of failure modes — columns: # / Failure / When / Recovered? / Fatal? One fatal row at most. Follow with a 2-3 sentence plain-English summary distinguishing symptom from cause.
4. **Sessions table** — Role / Session ID / Model / Steps reached.
5. **Definitive root cause (with evidence)** — quote EXACT log lines with timestamps; cite the config file + the provenance command that produced each claim. State plainly: the watchdog abort was correct behavior; the upstream cause was X.
6. **Solutions (options, recommendation, why)** — 2-4 options labeled (A)/(B)/(C), then a bolded RECOMMENDATION with rationale and version/robustness caveats.
7. **Timeline (annotated)** — numbered or table, UTC timestamps, every notable event from webhook-in to terminal state.
8. **Run progress vs completion state** — what actually got done (good) vs what the skill's deliverables were and how many were reached (gaps).
9. **Evidence sources** — bulleted list of the exact commands you ran and files you read.

Keep the report evidence-first: every claim ties to a quoted log line or a cited config line. No emojis. No speculation without a labeled assumption.
