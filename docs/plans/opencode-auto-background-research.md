# Research: opencode 2.3.2 shell-tool background conversion + the mcp-agent-mail config source

Status: **COMPLETE (2026-11-20)** — researcher-subagent report, read-only, no changes made
by the research itself. Feeds Decisions 13/14
([`rev2-state-map-design.md`](rev2-state-map-design.md)) and the turn-bounded standing
mechanics row. Follow-up actions taken separately after review: the map row's timeout
lever (PR #62) and the removal of the dead MCP entry (host-local, see §3).

Baseline: opencode **v2.3.2**, binary `/home/nam20485/.opencode/bin/opencode`
(252 MB Bun-compiled ELF; embedded minified JS inspected via `strings`). A managed
`opencode serve --service` was running. Official docs: **opencode.ai** (opencode.com is
an unrelated company).

## 1. The stall mechanism — confirmed, exact

**Yes: opencode automatically converts a foreground shell-tool command to a background
job when the command's per-call timeout expires. The default is 120000 ms (2 minutes),
hardcoded. On conversion the tool returns immediately AND explicitly instructs the model
to end its turn. There is NO configuration option that disables the conversion or raises
the default.**

Verbatim from the embedded JS of the installed binary:

- Constants: `Id="shell",Ex=120000,Ix=600000` — 120000 ms foreground default.
- Tool description sent to the model: *"Commands still running after their timeout move
  to the background."* / *"Background commands return immediately, and you will be
  notified when they complete."*
- Timeout parameter description: *"Optional timeout in milliseconds (default 120000).
  When it expires, a foreground command moves to the background and a background command
  is stopped."*
- Default resolution: `ie=ee.timeout||(X?Ix:Ex)` — no config/env lookup; the default
  comes only from the constant (and a model-supplied `timeout: 0` falls back to 120000,
  so foreground commands always have a deadline).
- What the model receives on conversion: *"Command moved to the background (shell ID:
  …)."* + *"The command did not finish within its timeout of N seconds…"* + — the line
  that explains all three of our stalls — **"You will be notified automatically when the
  command finishes. … If you have nothing else to do, end your response; you will be
  resumed automatically when the command finishes."**
- Completion delivery: a synthetic session message resumes the agent loop — but only
  while the session lives; if the session is gone it is swallowed
  (`Session.NotFoundError` → swallowed). Our host kills the process tree at `end_turn`,
  so the result can never arrive. This is why prompt rules lost: they compete with the
  harness's own in-band instruction to end the turn, delivered at the moment of
  conversion.

Output files: `~/.local/share/opencode/shell/<40-hex>/sh_<id>.out` (one directory per
server instance). The "Output file is external-blocked" error one session hit is
opencode's `external_directory` permission check (the file lives outside the session's
project root; reads outside the active Location are gated).

### No config kill-switch — definitive

Checked: the official config schema (`https://opencode.ai/config.json` — full key list;
the only timeout-like keys are MCP/provider/location timeouts; the `shell` key is a
string for the shell binary; `tool_output` is truncation only), the binary (constant
with no config lookup), the complete `OPENCODE_*` env-var list in the binary, and the
docs. No option exists to disable or re-limit the conversion.

### The one lever

The model supplies `timeout` (ms) **per tool call** — e.g. `timeout: 900000` for a
command that legitimately needs 15 minutes. That is the only supported way to keep a
long command in the foreground (on expiry a foreground command is *converted*; a
command explicitly started background *with* a timeout is *stopped*). This lever is now
stated in the map's turn-bounded row. Secondary hardening: redirect output to a file
INSIDE the project workspace so even a converted command leaves a readable artifact.

Upstream context: [anomalyco/opencode#36424](https://github.com/anomalyco/opencode/issues/36424)
("v2: shell: no way to stop a running background command", OPEN) confirms the exact
conversion message since v2.0.0; PR #48352 adds a `shell_stop` tool (a stop tool, still
not a disable switch).

## 2. Consequences for the receiver design (documented for later, nothing built)

- The synthetic notification exists only as an in-process future: if we ever want
  "resume on completion" semantics for genuinely long jobs, the receiver would have to
  keep the session alive and re-drive it (a second `prompt()` after `end_turn`) — that
  is fix-option C, deliberately not built.
- Pinning the opencode binary version (the host auto-updated 2.1.4 → 2.3.2 mid-train)
  via `ACP_OPENCODE_BIN` pointing at a fixed binary remains a standing recommendation.

## 3. The mcp-agent-mail source — found and fixed

**Source: `/home/nam20485/opencode.json`** — a home-directory-level config file.
opencode merges every `opencode.json` found walking from the CWD **up to the filesystem
root** ([docs — config](https://opencode.ai/docs/config/)), so every project under
`/home/nam20485` inherits it. The file's only content was the dead server entry
(`http://127.0.0.1:8765/mcp/` — the unit disabled 2026-11-10 — with a Bearer token,
redacted here):

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "mcp-agent-mail": {
      "type": "remote",
      "url": "http://127.0.0.1:8765/mcp/",
      "headers": { "Authorization": "Bearer <redacted>" },
      "enabled": true
    }
  }
}
```

Proof: a hermetic `opencode debug config --standalone` run with an isolated HOME and a
probe server in `~/.claude.json` listed exactly five config sources — the
`/home/nam20485/opencode.json` entry was the only source containing `mcp-agent-mail`,
and the claude.json probe did **not** appear (also disproving a claude-config
auto-import). The same server IS in `~/.claude.json` (the agent-mail installer wrote
both files) but feeds Claude Code only.

**Fix applied (2026-11-20, after the owner's MCP-cleanup direction):** the `mcp` object
removed from `/home/nam20485/opencode.json` (backup kept beside it:
`opencode.json.bak-20261120-agentmail`; removal also deletes the credential from disk),
the long-running `opencode serve --service` holding the pre-edit config was stopped
(opencode respawns it on demand), and `opencode debug config` in the xray45 clone now
shows zero `agent-mail` references. New dispatched sessions start clean.

## Sources

- [opencode.ai/docs/tools](https://opencode.ai/docs/tools/) — timeout parameter,
  background semantics, `external_directory` check
- [opencode.ai/docs/config](https://opencode.ai/docs/config/) — config discovery
  (CWD → filesystem root), `shell` key
- [opencode.ai/config.json](https://opencode.ai/config.json) — full schema (no
  conversion/timeout option)
- [anomalyco/opencode#36424](https://github.com/anomalyco/opencode/issues/36424) —
  conversion behavior since v2.0.0; PR #48352 `shell_stop`
- Local: `/home/nam20485/.opencode/bin/opencode` (embedded JS, quoted verbatim);
  `/home/nam20485/opencode.json`; `~/.local/share/opencode/shell/`;
  hermetic `opencode debug config --standalone` experiment
