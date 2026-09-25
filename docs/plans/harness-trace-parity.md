# Plan: Harness Trace Parity

Status: proposed — no code written yet; steps S1–S6 are unstarted
Date: 2026-09-25
Evidence base: everything below was read or executed live on 2026-09-25 against `development` @ `cf5b83d`, the running host service (systemd user unit `webhook-receiver`, PID 2385), and the frozen old stack at `~/src/github/nam20485/orchestrator-service`. Line references are to those trees as of that date.

## Problem

The service answers "what is the agent doing right now, and what did it do last run?" with nothing.

Two independent drops, both verified:

1. The ACP host reads the harness's stderr and discards it. `src/webhook_receiver/acp_host.py:261-275` — `drain_stderr()` reads every line and logs at `logger.debug`, while the service runs at the default `info` (`config.py:140`, `WEBHOOK_LOG_LEVEL` unset in `.env`). The pipe is drained so nothing blocks; the content goes nowhere.
2. The spawn never asks the harness to log. `acp_host.py:277-279` is `spawn_agent_process(client, bin_path, "acp", "--cwd", str(workspace))` — no `--print-logs`, no `--log-level`, although `opencode acp --help` (v1.18.32) offers both (`--print-logs` = "print logs to stderr"; `--log-level` = `DEBUG|INFO|WARN|ERROR`).

What survives today: the 14-name SSE event contract (`app.py:15-40`), an in-memory 1000-entry ring (`event_store.py:66-67`) that is empty after every restart and was empty when checked, journald at ~27 h retention, and — by accident, not by design — opencode's own stores (`~/.local/share/opencode/log/opencode.log`, 14 MB / 70,568 lines; `opencode.db`, 244 MB, 482 sessions / 4,824 messages) which do contain dispatched runs and are the only place the 2026-09-23 failure evidence still exists.

The 14 events are a lifecycle summary and will not carry the detail that made the old runs debuggable: model calls and provider selection, per-step loop progress, subagent and skill/context loading, the agent's stated intentions, tool calls with their output, and an early halt signal.

## The golden format

Reference capture, owner-designated: `orchestrator-service/traces/gap-miner-v2-papa85/gha_workflow_output.log` (2,382 lines / 497 KB, `docker compose logs`, 2026-07-11). Four line classes:

| Count | Line shape | Source | Carries |
|---|---|---|---|
| 1,802 | `orchestratorservice-1 \| timestamp=… level=INFO run=70c74cd7 message=…` | the serve container's own stdout (`Dockerfile:141`: `opencode serve --hostname 0.0.0.0 --port 4099 --log-level INFO --print-logs`) | harness internals — `message=evaluated permission=… action.action=allow` (516), `message=loop … step=` (183), `message=stream … modelID=… agent=…`, `llm runtime selected` |
| 217 | `webhook-receiver-1 \| 2026-07-11 07:30:55,999 INFO webhook_receiver.runner [opencode] …` | the receiver re-logging the client's stdout | the agent's voice — `Thinking: Now I have the full application plan issue template. Let me now delegate…`, then its numbered plan |
| 125 | `… runner [opencode-err] …` | same, stderr pipe | todo/plan state — `# Todos`, `[✓] Post status update on issue #1 — …` |
| 216 | `webhook-receiver-1 \| INFO: 172.24.0.4:56266 - "GET /api/dashboard/overview"` | uvicorn | request stream |

The value was one interleaved pane where harness decisions and agent intentions share a timeline, correlated by `run=<8hex>` and wall clock.

Two corrections to how this was remembered:

- **It was not a `sed` filter.** Filtering was Python, applied only at the logger boundary: `orchestrator-service/webhook_receiver/filters.py:6-27` `_DEFAULT_BLACKLIST` (12 regexes, env-overridable via `TRACE_BLACKLIST_PATTERNS` at `:30-36`), called from `runner.py:292-316` `_stream_to_logger_and_file`, which per line does: write raw to the file and flush, `state.record_line(line)` for the watchdog, then `if not should_filter(line): logger.info("[%s] %s", label, _format_log_line(line))`. The serve container's own stdout was never filtered — which is why 516 `evaluated permission` noise lines are in the golden capture.
- **No `[watchdog]` lines and no bracketed `[timestamp=…]` lines appear in that capture.** `_format_log_line` (`runner.py:262-291`) only fired on slog text returning through the client pipe; the watchdog series postdates this run.

## What the new stack does today

| Layer | State | Reference |
|---|---|---|
| Harness log channel | `opencode acp` subprocess; stdout is the JSON-RPC channel, so **stderr is the only free pipe** | `acp_host.py:6-8` ("No `opencode serve` container exists anywhere") |
| stderr handling | read, redacted, logged at `debug` → discarded at `info` level | `acp_host.py:261-275`, `:72-75` |
| Redaction | `_REDACT_RE` matches only `(api_key\|authorization\|token\|secret)\s*[=:]\s*\S+` — a bare `ghp_…`, `github_pat_…`, `sk-…` or `Bearer …` value passes through | `acp_host.py:72-75` |
| `session/update` mapping | 6 kinds mapped to events; **thought chunks, plan deltas, mode changes, available commands are consumed and ignored** | `acp_host.py:32-33`, `:142`, `:159` |
| Per-run artifacts | none — no `logs/runs/`, no manifest, no `.stdout`/`.stderr` | `logs/` holds only launcher JSONL |
| Noise filter | none — no `should_filter`, no blacklist anywhere in `src/webhook_receiver/` | `filters.py` is the webhook gate only |
| Halt detection | none — only `ACP_PROMPT_TIMEOUT=600` as a hard deadline, plus `ACP_STEP_TIMEOUT=30` for protocol steps | `config.py:60-61`; kill grace `_KILL_GRACE_SECONDS = 5.0` (`acp_host.py:77`) |
| Single pane | `journalctl --user -u webhook-receiver -f` (plain text, `__main__.py:21-23` format) + Caddy's JSON access log (`Caddyfile:23-28`) | verified live |
| Durable fallback | opencode's own log and SQLite store, shared with every interactive session on the host, no retention policy, nothing service-side records the join keys | verified live |

## Old mechanism inventory (what to lift)

All paths under `~/src/github/nam20485/orchestrator-service`:

- `Dockerfile:141` — serve with `--log-level INFO --print-logs`.
- `scripts/prompt.ps1:74,83,88,91` — client flags: `--attach`, `--log-level $LogLevel`, `--print-logs` (boolean flags take no argument).
- `webhook_receiver/runner.py:292-316` — `_stream_to_logger_and_file(pipe, file_handle, label, state)`: raw-to-file + watchdog signal + filtered-to-logger, with `label` = `opencode` / `opencode-err`; spawned as two daemon threads at `:819-826`.
- `runner.py:262-291` — `_SLOG_ENVELOPE_RE` + `_format_log_line`: groups `timestamp=… level=… run=…` into brackets so the payload stands out; non-slog lines pass through unchanged; the trace file always gets the raw line.
- `runner.py:760-761` — per-run `<stem>.stdout` / `<stem>.stderr`; `:119-141` — `<stem>.manifest.json` sidecar (repo, issue, workflow, pid, started/ended, exit_code, classification, tools, model, agent, log_dir).
- `filters.py:6-27` + `:30-36` — the 12-regex blacklist and its `TRACE_BLACKLIST_PATTERNS` override; in-code rationale "~73% of a run log is pure repetition", with ERROR/WARN and `exiting loop` deliberately kept.
- `runner.py` `_SECRET_PATTERNS` / `_sanitize_for_comment` — five patterns (`gh[pousr]_[A-Za-z0-9]{36,}`, `github_pat_[A-Za-z0-9]{22,}`, `sk-[A-Za-z0-9]{20,}`, `Bearer\s+…`, `(password|passwd|secret|api[_-]?key|token|auth)\s*[:=]\s*\S+`) scrubbed before stderr text reaches a GitHub issue comment.
- `watchdog.py` — `:386-390` thresholds (15-min idle, 90-min hard ceiling, 30-s tick), `:459` `REASON_IDLE_TIMEOUT`, `:497` + `:703-722` heartbeat `[watchdog] elapsed=%ds line_idle=%ds server_log_idle=%s` emitted once output has been silent ≥60 s, `:541/:591/:618/:651` kill reasons (exited on its own, hard ceiling, consecutive errors, permission deadlock), `:343` `record_line`, `:106-160` dispatch-scoped byte-growth monitor, `_dump_diagnostics` (last 20 stderr lines) before `:785-812` SIGTERM grace → process-group kill → server-session abort.
- `compose.yaml:13,66,111` — the shared `opencode-logs` volume, mounted read-only into the receiver, whose mtime the watchdog used as a second activity signal.

Do **not** port: the GHA-era `scripts/trace-extract.py` (it parses `service=llm … sessionID=…` keys; today's opencode log has zero `service=` keys — the format is `timestamp= level= run= message= key=value`), the beads events, the Sentry module (already deleted at old HEAD), and the dashboard.

## Mapping old → new

| Old channel | New equivalent | Note |
|---|---|---|
| serve container stdout slog | `opencode acp --print-logs --log-level INFO` → subprocess stderr | no container, no volume, no port |
| client stdout/stderr → `[opencode]` / `[opencode-err]` logger lines | ACP `session/update` (thought chunks, plan deltas, tool calls, message chunks) + the stderr tap | stdout is JSON-RPC now, so the glyph stream no longer exists as a separate pipe |
| `docker compose logs` single pane | `journalctl --user -u webhook-receiver -f` | already works; needs the content and ~27 h retention is short |
| `<stem>.stdout` / `.stderr` / `.manifest.json` in a bind-mounted `log_dir` | `logs/runs/<run_id>/harness.log` + `manifest.json` | `logs/` is already gitignored (`.gitignore:14`) |
| shared `opencode-logs` volume + mtime signal | read `~/.local/share/opencode/log/opencode.log` directly | growth must still be scoped per dispatch: that file is shared with every interactive session (807 of 70,568 lines relate to ACP workspaces) |
| `should_filter` blacklist at the logger boundary | same, re-seeded against today's measured noise | top offenders now: `duplicate skill name` 15,538 lines (22% of the file), `llm runtime selected` 3,042, `touching file` 1,445, `message=loop … step=` |
| `_SECRET_PATTERNS` before issue comments | replace `_REDACT_RE` with the five patterns, applied to both the logger and the file | narrowest gap in the current code |

## Design decisions

**D1 — stderr is the harness log channel.** There is no serve container; the ACP subprocess's stdout carries JSON-RPC, so `--print-logs` (which writes to stderr) plus the existing `drain_stderr()` reader is the whole tap. No new process, no pty, no volume.

**D2 — journald is the single pane, `logs/runs/<run_id>/` is the record.** The host-run analogue of `docker compose logs` already exists (`StandardOutput=journal` on the user unit). Live reading stays `journalctl --user -u webhook-receiver -f`; durable reading is per-run files, because journald retains ~27 h here and restarts empty the event ring.

**D3 — keep the raw/filtered split exactly.** The filter decides only what reaches the logger; the per-run file always gets every raw line, unfiltered and flushed. That is what made the old captures usable after the fact, and it is why the golden file still contains 516 noise lines.

**D4 — port the five secret patterns; do not rely on `_REDACT_RE`.** The current regex only catches `key=value` shapes and would pass a bare `ghp_…` token. Redaction applies to the logger, the file, and anything posted to a GitHub issue.

**D5 — port the watchdog thresholds, not just the timeout.** `ACP_PROMPT_TIMEOUT=600` cannot distinguish a stalled session from a working one. Carry over 900 s idle / 90-min ceiling / 30 s tick, the ≥60 s-silence heartbeat line, `_dump_diagnostics` before the kill, and both activity signals (line activity + dispatch-scoped `opencode.log` byte growth).

**D6 — the 14 SSE events stay the machine contract; trace detail is additive.** `app.py:15-16` permits additive changes only. New kinds (`agent_thought`, `agent_plan`) are added; existing names and fields are untouched, so `docs/usage.md` §6's event sequence and any consumer keep working.

**D7 — everything is behind a setting and revertible.** Trace capture is gated by config (default on for `INFO`, off-able without a code revert), because a chatty harness could otherwise flood journald on a host that already rotates in ~27 h.

**D8 — opencode's own log and database are a fallback, not a dependency.** They are internal to opencode, shared with interactive use, and their schema can change. We record the join keys (`session_id`, workspace path, discovered `run=<id>`) in the manifest so a slice can always be reconstructed, and we archive our own copy rather than relying on theirs.

## Steps

Implementation is delegated to `qwen3.8-flash` per the owner's standing cost rule; this session plans, reviews and verifies. Each step is separately commitable and lands behind `-Step build` + `-Step python` green.

**S1 — open the tap (~30 min).** In `acp_host.py:277-279` spawn `"acp", "--print-logs", "--log-level", <setting>, "--cwd", workspace`; add `ACP_HARNESS_LOG_LEVEL` (default `INFO`) and `ACP_TRACE_ENABLED` (default true) to `config.py`. Raise `drain_stderr()` from `logger.debug` to `logger.info` with a `[harness]` label, keeping `_REDACT_RE` for now. *Verification:* one dispatched run shows `[harness]` lines in `journalctl --user -u webhook-receiver -f`. This step also answers open question Q1.

**S2 — per-run artifacts (~45 min).** New `trace_log.py` (or a private helper in `acp_host.py`): on run start create `logs/runs/<run_id>/`, tee every raw stderr line to `harness.log` (flushed, unfiltered), write `manifest.json` with `run_id`, `delivery_id`, `repo`, `label`, `workspace`, `started_at`, and merge `session_id`, `ended_at`, `ok`, `stop_reason`, `error`, `exit_reason` on completion. Cap retention (see Q2). *Verification:* the directory exists after a run, `harness.log` is non-empty, and the manifest round-trips through a unit test.

**S3 — filter and redaction (~45 min).** Port `should_filter` + `_DEFAULT_BLACKLIST` (env-overridable, `TRACE_BLACKLIST_PATTERNS`) re-seeded against today's measured noise; port `_format_log_line` bracketing; replace `_REDACT_RE` with the five `_SECRET_PATTERNS`. Filter applies to the logger path only (D3). *Verification:* fixture tests — a blacklisted line reaches the file but not the logger; a raw line reaches both; each of the five credential shapes is redacted in the file, the logger, and the issue-comment path.

**S4 — recover the agent's voice (~45 min).** Extend the `session/update` mapping at `acp_host.py:32-33` to keep thought chunks and plan deltas: emit additive `agent_thought` / `agent_plan` events and render them into `harness.log` in the golden style (`[acp] Thinking: …`). *Verification:* the existing event-contract test still passes unchanged, a new test covers the two new names, and a real run's `harness.log` contains intention text.

**S5 — idle watchdog (~1 h).** Port the threshold set, the heartbeat line shape, `_dump_diagnostics`, and the two activity signals; wire the existing kill ladder (`_KILL_GRACE_SECONDS`, `acp_host.py:77`). Grow the `prompt_consumed` payload's failure `error` with the kill reason. *Verification:* a test double that goes silent is killed at the idle threshold with reason `idle_timeout`; heartbeat lines appear after ≥60 s silence; no orphan `opencode` process survives the ladder.

**S6 — docs and gate (~30 min).** `src/webhook_receiver/README.md` event table (additive rows only), `docs/usage.md` §6 (how to follow a live run and where the artifacts land) and §8 (retention), `docs/architecture.md` §Eventing (correct the "15-event contract" to the 14 names actually emitted), and wire the new tests into `validation.ps1`'s `$testPaths` (`:169`). *Verification:* `pwsh ./validation.ps1 -Step all` green.

## Acceptance criteria

Done when:

1. A dispatched run leaves `logs/runs/<run_id>/harness.log` (raw, unfiltered, non-empty) and `manifest.json` carrying `run_id`, `delivery_id`, `repo`, `label`, `session_id`, `workspace`, `started_at`, `ended_at`, `ok`, `stop_reason`.
2. During a run, `journalctl --user -u webhook-receiver -f` shows an interleaved pane in the golden line shape: harness slog lines labelled `[harness]`, agent intention text, and the receiver's own lifecycle lines, correlatable by `run_id`.
3. A blacklisted line is present in `harness.log` and absent from the logger; a non-blacklisted line is in both (filter-parity test).
4. Each of the five credential shapes (`ghp_`, `gho_`/`github_pat_`, `sk-`, `Bearer`, `key=value`) is redacted in the logger, in `harness.log`, and in any GitHub issue comment.
5. A session silent past the idle threshold is killed with reason `idle_timeout`, `[watchdog]` heartbeat lines appear once output has been silent ≥60 s, and the last-20-lines diagnostic dump precedes the kill.
6. The hard ceiling is enforced and the SIGTERM → SIGKILL ladder leaves no orphan `opencode` process.
7. The 14 existing event names and fields are unchanged; `agent_thought` and `agent_plan` are added; `docs/architecture.md` states 14.
8. `ACP_TRACE_ENABLED=false` disables capture with no other behaviour change, and `ACP_HARNESS_LOG_LEVEL` selects the harness verbosity — neither requires a code revert.
9. `logs/runs/` is gitignored and capped at the agreed retention; `pwsh ./validation.ps1 -Step all` exits 0.

## Effort, delegation and rollback

Roughly half a day for S1–S4 (the trace itself), about a day including S5–S6. Delegated to `qwen3.8-flash` step by step; each step is reviewed and verified here before the next.

Rollback: every change is additive inside `src/webhook_receiver/` plus a gitignored output directory. `ACP_TRACE_ENABLED=false` disables capture at runtime; reverting the commits removes it entirely. No schema, queue, endpoint or contract change, so no migration and no service impact. `logs/runs/` can be deleted at any time.

Biggest risk: unknown harness log volume at `--log-level INFO` on a host whose journald already rotates in about a day. D7 (settings-gated) and S2's retention cap are the mitigations; Q1 measures it.

## Non-goals

- No dashboard, no web UI (parked by owner decision 2026-09-23; `docs/architecture.md:122-123`).
- No metrics backend, no OpenTelemetry, no alerting — the old stack deliberately had none (`orchestrator-service/droid-wiki/how-to-monitor/index.md:115-119`).
- No changes to the webhook gate, queue schema, dedup window, or the `prompt_builder` label classes.
- No revival of the deleted opencode-stderr glyph parser or the beads event vocabulary; the ACP `session/update` stream is the source now.
- No container, volume, or serve process — the host-run posture stays as it is.

## Open questions

1. **Q1 — volume.** Does `opencode acp --print-logs --log-level INFO` emit usefully in v1.18.32, and how many lines per run? Not verified; S1 answers it on the first real dispatch. If `INFO` is thin, `ACP_HARNESS_LOG_LEVEL=DEBUG` is the fallback and the retention cap becomes load-bearing.
2. **Q2 — retention cap for `logs/runs/`.** Count-based (proposal: last 50 runs) or size-based (proposal: 500 MB)? Owner's call; default is count-based because run size varies with model chattiness.
3. **Q3 — heartbeat destination.** `[watchdog]` heartbeats to journald at `info` (matches the golden pane, adds noise) or only to `harness.log`? Proposal: journald at `info`, since catching a halt live is the point.
4. **Q4 — tool-call rendering.** The old pane showed the agent's todo list as text (`[✓] Post status update on issue #1 — …`). Do we render `agent_tool_call` titles into `harness.log` the same way, or leave them to the SSE contract only? Proposal: render them — it is the single most useful line class in the golden capture.
5. **Q5 — the unexplained poller.** Something on this host requests `GET /models` and `GET /props` on `127.0.0.1:8080` every few minutes (all 404; seen 07:42–08:26 on 2026-09-25). It looks like an opencode-serve-style client pointed at the listener port, possibly a leftover from the retired `orchestratorservice` container. Out of scope here, but it pollutes the pane this plan is building — identify it before S1 or accept the noise.

## Carry-forward state (outside this plan's scope)

Recorded here so it is not lost with session context:

- **PAT leaked into a session transcript on 2026-09-25** and must be treated as burned: the `GITHUB_TOKEN` from `~/.config/webhook-receiver/env` (a classic `ghp_` PAT, scopes `project, read:org, repo, write:discussion, write:packages`) was printed by a malformed presence check. Rotate it, regenerate that env file, then `systemctl --user restart webhook-receiver`. Transcript-only exposure — not written to a file, not committed.
- **The `read:org` diagnosis in `.agents/memory.md:10` and `:59` is wrong.** The recorded 2026-09-23 failure was `gh project list --owner intel-agency` → `your authentication token is missing required scopes [read:project]`, recovered from `opencode.db`; `read:org` was already present. Both the keyring token and the service PAT now carry `project`, and the read path was verified working with the service token. Untested: the write path (`gh project create` / `link` / `field-create`, `ensure-project.ps1:110/114/158`) and any end-to-end dispatch since.
- **Two unrelated dirty files were stashed on 2026-09-25**: `.zcode/agents/swarm-orchestrator.md` (model id reformatted to `91b0…/qwen3.8-max`, `thoughtLevel: xhigh`, `injectAgentsMd: false→true`) and `swarm-orchestration-service.code-workspace` (adds `dotrush.roslyn.projectOrSolutionFiles`). Recover with `git stash apply 4cbd3cb8` (`stash@{0}` on `development`). The `.zcode` change is half of an ACP-parity pair — `.opencode/agents/swarm-orchestrator.md` needs the matching edit before it is committed.
- **`gh` resolves this checkout to the upstream parent.** `gh repo view` reports `nam20485/swarm-context`; a bare `gh pr create` failed with `Head sha can't be blank … Head ref must be a branch`. Pass `-R nam20485/swarm-orchestration-service` on every `gh` call here, especially writes. The fix (`gh repo set-default …`) writes to `.git/config` and is deliberately not applied.
- **PR #31** (`dev/skill-plan-revision` → `development`) carries the `docs/plans/skill-plan.md` rewrite, milestone `maintenance`, label `documentation`.
