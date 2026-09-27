# ZCode Configuration

**Rule: never derive ZCode config syntax.** Agent-definition frontmatter, model pins and MCP server
blocks come from the official docs, a shipped template, or a known-good example — never inferred from
a registry, cache, or an adjacent layer's naming.

**Why (negative result, 2026-09-27):** the six `.zcode/agents/swarm-*.md` workers were re-pinned to
`builtin:zai-coding-plan/GLM-5.3-Flash`, derived from the provider keys in `~/.zcode/v2/config.json`.
ZCode rejected it at spawn:

```text
Cannot start subagent: Provider unavailable / 供应商不存在或不可用
[reason=provider-not-found; selection=builtin:zai-coding-plan/GLM-5.3-Flash]
```

`builtin:*` strings are **registry keys**, not selections. Corrected to
`account:zai-individual-coding-plan/GLM-5.3-Flash` in `ed24f51`. A second derivation in the same
session — probing invented doc hostnames, getting nothing, and recording "no public docs site" — was
also wrong; the docs are at `https://zcode.z.ai/en/docs/<slug>`. Search before concluding absence.

## Official documentation

Base: **`https://zcode.z.ai/en/docs/<slug>`** (`https://zcode-ai.com` 308-redirects to
`https://zcode.z.ai/cn`). Pages: `welcome`, `install`, `configuration` ("Connect Models"),
`feedback`, `agents`, `goal`, `browser-use`, `task-management`, `repo-wiki`, `memory`, `automations`,
`idle-time-tasks`, `edit-history`, `remote-development`, `remote-control`, `bot-channel`,
`subagents`, `plugin`, `skill`, `mcp-services`, `commands`, `hooks`, `usage-stats`, `safety-confirm`,
`ADE-tools`, `keyboard-shortcuts`, `qa`. Chinese: swap `en` for `cn`. Community: Discord
`https://discord.gg/z9aBcQXZQ3`; feedback form in `/opt/ZCode/resources/config/default.json`.

The three pages that govern this repo's `.zcode/` surfaces: **`subagents`** (definition frontmatter),
**`configuration`** (per-model thinking levels), **`mcp-services`** (server config).

## Subagent definitions (`/en/docs/subagents`)

Documented frontmatter: `name` and `description` (**both required** — a file missing either is
*ignored*, with a diagnostic), `model`, `thoughtLevel`, `color`, `tools` / `disallowedTools`,
`maxTurns`, `injectAgentsMd` (defaults **on**), `mcpServers`.

- `model` — "A specific model id; `inherit` or omitting it follows the primary Agent's current
  model." **The docs do not define the provider-scope syntax**; see the next section.
- `thoughtLevel` — "Reasoning level (e.g. `high`). **Only takes effect together with a specific
  `model`**, and the value must be a level that model supports. Note the key is not
  `reasoningEffort` — unrecognized keys are silently ignored, with no error."
- `mcpServers` — exact server names; **if a declared server is not connected, the invocation fails
  immediately.** (Contrast `/en/docs/mcp-services`: a server that fails at session start is only
  marked failed and the session carries on. The subagent declaration is the strict path.)
- Storage — the Beta's Settings manages **user-level** defs under `~/.zcode/agents/`; project-level
  editing is not available in Settings. Empirically this repo's `.zcode/agents/*.md` **is** loaded:
  the 2026-09-27 spawn error quoted `selection=builtin:zai-coding-plan/GLM-5.3-Flash` straight out of
  `.zcode/agents/swarm-agent.md`.
- Definitions are read at app startup — **fully quit and relaunch ZCode** after editing them.

## Thinking levels are per model (`/en/docs/configuration`)

| Model | Documented levels | Default |
|---|---|---|
| GLM-5.3 family | `low`, `high`, `max` | `max` |
| GLM-5.2 | `nothink`, `high`, `max` | `max` |
| GPT series | `low`, `medium`, `high`, `xhigh` | `medium` |
| Claude series | `low`, `medium`, `high`, `xhigh` (Opus 4.7 also `max`) | `medium` |
| Kimi K3 | `low`, `high`, `max` | `max` |
| DeepSeek V4 | `high`, `max` | `max` |
| other custom models | a simple on/off toggle, or none | per model config |

`off` is **not** a documented level for any of these, so `thoughtLevel: off` on `GLM-5.3-Flash` is
unsupported — which corroborates `.agents/memory.md:55` ("blocks GLM-5.3-Flash worker spawning
entirely", observed 2026-09-10) from documentation rather than from one old observation.

**That memory note's first remedy is wrong for our goal.** It suggests "drop it from the worker
defs" — but omitting `thoughtLevel` leaves the model default, which is `max` for GLM-5.3: the most
reasoning, not the least. The documented ways to reduce worker reasoning are `thoughtLevel: low` on
GLM-5.3-Flash, or a model whose list includes a no-thinking level (`nothink` on GLM-5.2). `maxTurns`
(25/50 in the worker defs) is the hard stop against meander and is independent of thinking.

Also documented: third-party models ignore manually added request parameters — "keys like
`reasoning_effort` added manually to config are silently ignored."

## Model-id selection syntax — a documented gap; resolve from examples

The docs say only "a specific model id", so the scope form must come from a shipped or working
example:

| Form | Status |
|---|---|
| `account:<plan>/<modelId>` | **Known good.** `account:zai-individual-coding-plan/GLM-5.3-Flash` is used by `~/.zcode/agents/developer.md` and `qa-tester.md`, and `account:` scopes are enumerated by the shipped template `/opt/ZCode/resources/config/provider/zcode-builtin.json` (`zai-individual-coding-plan`, `zai-team-coding-plan`, `zai-start-plan`, `zai-offpeak-idle-plan`, and the four `bigmodel-` equivalents) |
| bare `<modelId>` | Loads (`~/.zcode/agents/code-reviewer.md`: `model: GLM-5.3-Flash`) but resolves through the ambient default provider — ambiguous when several providers carry the same id (`GLM-5.3-Flash` appears under four) |
| `inherit` | Documented; follows the primary agent's model. Wrong for cost-pinned workers |
| `<uuid>/<modelId>` (custom provider) | **Unverified as a def string.** Used by `swarm-orchestrator.md` (`91b0a8e2-…/qwen3.8-max`). Telemetry resolves `providerId` to the bare UUID for real sessions, but no shipped or working def example exists |
| `custom:<urlencoded-provider>:<modelId>` | Legacy; still in the parent template `nam20485/swarm-context`. Do not write it into new defs |
| `builtin:<plan>` | **Registry key, not a selection** — fails with `provider-not-found` |

## MCP configuration (`/en/docs/mcp-services`)

| Scope | File | Key |
|---|---|---|
| user | `~/.zcode/cli/config.json` | `mcp.servers` |
| workspace | `<project root>/.zcode/config.json` | `mcp.servers` |
| user, `.agents` compatibility | `~/.agents/mcp.json` | `mcpServers` |
| workspace, `.agents` compatibility | `<project root>/.agents/mcp.json` | `mcpServers` |

stdio servers take `command`, `args`, `env`; HTTP/SSE servers take `url`, `headers`. ZCode also
accepts a pasted `{"mcpServers": {...}}` block. This repo's `.zcode/config.json` already follows the
workspace shape (`web-reader`, `zread`, `web-search-prime`, `exa`); copy
`.zcode/config.example.json` for the placeholder template.

## Other authorities, in order (when the docs are silent)

1. **Shipped templates** — `/opt/ZCode/resources/config/` (installed app v3.12.1):
   `provider/zcode-builtin.json` (`schemaVersion`, `revision`, `templateRules`, valid `account:`
   scopes, `builtinModelIds`, API base URLs), `default.json` (community/feedback URLs).
2. **Known-good defs** — `~/.zcode/agents/*.md`.
3. **Live telemetry** — `~/.zcode/cli/rollout/model-io-*.jsonl`: resolved `model.providerId` /
   `model.modelId`, the request body (including `thinking`), `durationMs`, `attempt`. Ground truth
   for what a session actually used.
4. **Registry — existence and entitlement only** — `~/.zcode/v2/config.json` `.provider` and
   `~/.zcode/v2/coding-plan-cache.json` (`available` vs `coding_plan_not_entitled`). Never read a
   selection string off these.

## Failure-mode catalogue

| Symptom | Cause | Remedy |
|---|---|---|
| `Cannot start subagent: Provider unavailable / 供应商不存在或不可用 [reason=provider-not-found; selection=…]` | the `model:` scope is not a valid selection | copy a scope from the shipped template or a working def; confirm from telemetry |
| A def appears not to exist / is skipped | `name` or `description` missing — the file is ignored with a diagnostic | both are required |
| A subagent invocation fails immediately while the session is otherwise healthy | it declares `mcpServers` and one is not connected | check the server's connection state, or drop it from the declaration |
| A `thoughtLevel` change has no effect | it only applies with a specific `model` (`inherit`/omitted ⇒ ignored), or the value is not a level that model supports | pin the model; use a documented level |
| A renamed frontmatter key silently does nothing | unrecognized keys are ignored, no error (`reasoningEffort` is not the key; it is `thoughtLevel`) | use the documented names |
| A worker meanders and burns tokens | reasoning level too high for the task, or no turn cap | lowest documented level for that model + `maxTurns` |
| An edited def has no effect | defs load at app startup | quit and relaunch ZCode |
| A session transcript appears as `.zcode/agents/<first line of prompt>.md` | ZCode export/save wrote into the roster, where it loads as a bogus def | move it out of `.zcode/agents/` |

## Verifying a change without spending a swarm run

Spawn **one** worker with a trivial read-only task (worker toolsets are `Read, Grep, Glob[, Bash]`,
so a Glob-plus-Grep question costs one or two calls), then read the newest
`~/.zcode/cli/rollout/model-io-sess_subagent_agent_*.jsonl` for `model.providerId` / `model.modelId`
and `request.body.thinking`. A rejected model id writes **no** subagent telemetry at all — the absence
is itself the signal that it failed before any model call.

## Open items

- **Custom-provider (UUID) def syntax unverified** — `swarm-orchestrator.md` uses
  `91b0a8e2-…/qwen3.8-max`. Cheapest discriminator: a throwaway def on `91b0a8e2-…/qwen3.8-flash`
  (same provider, cheap model) plus a one-line spawn — not a `$swarm` run on the king model.
- **Worker reasoning level is an owner decision** — `thoughtLevel: off` is unsupported for
  GLM-5.3-Flash; the documented choices are `low` on GLM-5.3-Flash or `nothink` on GLM-5.2.
- **`swarm-researcher.md` declares `mcpServers: [web-reader, web-search-prime, zread]`**, and those
  three Z.AI servers were observed failing to connect on 2026-09-27 (harness WARN `server unavailable
  key=web-reader|zread|web-search-prime type=remote status=failed`). Per the docs a disconnected
  declared server fails the invocation immediately, so the researcher is the worker most likely to
  die at spawn. Check ZCode's MCP connection state before the next swarm.
- `.agents/memory.md:55` needs correcting once the level decision is made (its "drop it" remedy
  yields `max`).
