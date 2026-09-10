# Phase 0.1 — ACP Spike (opencode over Agent Client Protocol)

Proves the ACP round-trip from a Python host against a real agent CLI (`opencode acp`),
with the headless permission-DENY path as the critical deliverable (plan §5 Decision 3).
This gated Phase 2 (ACP host). **Status: PASS — all three modes, 2026-09-10.**

## Layout

- `host_spike.py` — the host. One script, three modes (see below). Exits non-zero on
  protocol error/timeout or failed mode verdict; writes a JSON-lines transcript to
  `/tmp/acp-spike/<mode>-<timestamp>.log` (opencode stderr is drained into it, with a
  light regex redaction over `key/token/secret/authorization` values).
- `requirements.txt` — exact pin: `agent-client-protocol==0.12.1` (official SDK, pre-1.0).

## How to re-run

```bash
# from the repo root; the spike venv is separate from the repo-root .venv
python3 -m venv spikes/acp/.venv
spikes/acp/.venv/bin/pip install -r spikes/acp/requirements.txt

opencode --version   # spike verified on 1.18.30; floor is v0.15.10 (see below)

# mode 1: happy path (initialize -> new_session -> trivial prompt -> stopReason)
spikes/acp/.venv/bin/python spikes/acp/host_spike.py --mode happy

# mode 2: host auto-REJECTS session/request_permission (opencode permission.bash=ask
#         in the scratch cwd forces the request; the host picks reject_once)
spikes/acp/.venv/bin/python spikes/acp/host_spike.py --mode deny

# mode 3: belt-and-braces (opencode permission.bash=deny -> no request ever fires)
spikes/acp/.venv/bin/python spikes/acp/host_spike.py --mode deny-config
```

Each mode uses its own scratch cwd under `/tmp/acp-spike/<mode>/`; `deny`/`deny-config`
write a minimal `opencode.json` (`{"permission": {"bash": "ask"|"deny"}}`) into it. The
repo itself is never used as the agent cwd. All subprocess/network interactions have
timeouts (30 s per protocol step, 180 s per prompt, one overall deadline) and the spawned
opencode process is killed on every exit path.

## Observed results (opencode 1.18.30, 2026-09-10)

### happy — PASS

`initialize(PROTOCOL_VERSION=1)` → protocolVersion 1, loadSession/prompt(image)/mcp(http,sse)
capabilities, authMethods `["Login with opencode"]` (t=1.9 s) → `session/new` (t=3.9 s) →
prompt "Reply with exactly: ACP-OK" → `session/update` kinds seen: `available_commands_update`,
`agent_thought_chunk` x8, `agent_message_chunk` ("ACP-" + "OK"), `usage_update` →
**stopReason `end_turn` at t=6.2 s**, agent exited rc=0.

### deny — PASS (the critical deliverable)

Scratch `opencode.json` with `permission.bash = "ask"`; prompt asks the agent to run
`echo acp-deny-probe` via bash. Timeline:

- t=5.9 s: `tool_call` (bash, `pending` → `in_progress`)
- t=6.14 s: **`session/request_permission`** with options `allow_once | allow_always |
  reject_once` (no `reject_always` offered for bash); host auto-selected `reject_once`
  (optionId `reject`)
- t=6.19 s: tool call → `status: failed` (nothing executed)
- t=6.23 s: prompt returned **stopReason `end_turn`** — 94 ms after the reject; agent
  reported the denial in its reply and finished cleanly; process exit rc=0. No hang.

### deny-config — PASS (belt-and-braces)

Scratch `opencode.json` with `permission.bash = "deny"`. **Zero `request_permission`
requests fired.** Nuance worth knowing: opencode enforces the deny-list by *removing the
tool from the agent's toolset* — the model's bash call came back as a tool_call titled
"Invalid Tool" with `error: Model tried to call unavailable tool 'bash'`, the command was
never executed, and the session continued to **stopReason `end_turn`** (t=11.2 s, rc=0).
So the config route is not "auto-deny at the permission prompt" — it is stronger
(pre-prompt interception), which is exactly what an autonomous host wants for destructive
tools.

## Residual unknowns from plan §6 — resolved

1. **Minimum opencode version shipping `acp`:** **v0.15.10**, released 2025-10-20
   (release notes: "Added ACP (Agent Client Protocol) support"; PR #2947 merged the same
   day). Verified working on local 1.18.30.
2. **Does the TUI `--auto` flag apply to `acp` mode?** **No.** `opencode acp --help`
   has no `--auto` (it exists on the TUI and `opencode run`: "auto-approve permissions
   that are not explicitly denied (dangerous!)"). Over ACP, permission behavior is
   config-only (`permission` in `opencode.json`) plus the host's
   `session/request_permission` responses — confirmed empirically by the deny modes.
3. **What are `acp --port/--hostname/--mdns/--cors` for?** They expose the ACP agent
   over **HTTP as a companion endpoint** alongside stdio. Verified: `opencode acp --port
   N` binds an HTTP listener on that port (curl → `200 OK`, HTML). Default `--port 0` =
   listener off (stdio only). `--mdns` advertises the service via mDNS and defaults the
   hostname to `0.0.0.0`; `--cors` allows additional browser origins. Relevant only if a
   remote/web host ever drives opencode; our host uses stdio.

## Deviations / notes

- The SDK wheel ships no `examples/client.py` (that lives in the GitHub repo); the host
  was written against the installed package source (`acp.client.connection`,
  `acp.stdio.spawn_agent_process`, `acp.schema`). API notes: rejection is an
  `AllowedOutcome(outcome="selected", optionId=<reject option>)`; a bare
  `DeniedOutcome(outcome="cancelled")` is the "dismissed" answer.
- opencode's tools/model/MCP servers come entirely from its own config (global +
  scratch-cwd `opencode.json`) — Decision 10 (no host-side pins) observed in practice.
- Zed/ACP protocol version negotiated: 1. The SDK waits for in-flight `session/update`s
  to drain before `prompt()` returns, so the transcript is complete at stopReason.
- An unrelated `opencode serve` process was already running on this machine before the
  spike (not spawned by, or parented to, it); it was left untouched. `pgrep opencode acp`
  is clean after runs.
- Nothing was LLM-blocked: credentials were present, so the full happy path plus both
  deny paths ran against a real model. `session/cancel` was therefore not exercised
  (only needed in the LLM-blocked fallback).
