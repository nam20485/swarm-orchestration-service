# ZCode Configuration

**Rule: never derive ZCode config syntax.** Model selections, agent-definition frontmatter and MCP
server blocks are copied from a shipped template or a known-good example, or read out of the
vendor's docs — never inferred from a registry, cache, or an adjacent layer's naming.

**Why (negative result, 2026-09-27):** the six `.zcode/agents/swarm-*.md` workers were re-pinned to
`builtin:zai-coding-plan/GLM-5.3-Flash`, derived from the provider keys in `~/.zcode/v2/config.json`.
ZCode rejected it at spawn:

```text
Cannot start subagent: Provider unavailable / 供应商不存在或不可用
[reason=provider-not-found; selection=builtin:zai-coding-plan/GLM-5.3-Flash]
```

`builtin:*` strings are **registry keys**, not selections. The registry says what exists; it says
nothing about what a `model:` value must look like. Corrected to
`account:zai-individual-coding-plan/GLM-5.3-Flash` in `ed24f51`, which the shipped template lists.

## There is no public docs site (checked 2026-09-27)

| URL | Result |
|---|---|
| `https://zcode.z.ai/cn` | 200 — marketing site (`https://zcode-ai.com` 308-redirects here) |
| `https://docs.zcode-ai.com` | does not resolve |
| `https://www.zcode-ai.com/docs` | 503 |
| community / feedback | Discord `https://discord.gg/z9aBcQXZQ3`; Feishu feedback form and community links in `/opt/ZCode/resources/config/default.json` |

Unlike Kilo (`.agents/rules/kilo-code-docs.md`) and Qwen Code (`.agents/rules/qwen-code-docs.md`),
there is no LLM dump or raw-markdown endpoint to consult. Shipped files and working examples are the
authority.

## Authoritative local sources, in order

1. **Shipped templates** — `/opt/ZCode/resources/config/` (installed app v3.12.1):
   `provider/zcode-builtin.json` (`schemaVersion`, `revision`, `templateRules`, the valid `account:`
   scopes, `builtinModelIds`, API base URLs) and `default.json` (community/feedback URLs). These ship
   with the version actually running, so they beat any memory of a form.
2. **Known-good agent definitions** — `~/.zcode/agents/*.md` (the owner's working global agents).
3. **Live telemetry** — `~/.zcode/cli/rollout/model-io-*.jsonl`: what a session *actually* resolved
   (`model.providerId`, `model.modelId`), the request body (including `thinking`), `durationMs`,
   `attempt`. Ground truth for "did this work", and the cheapest way to check reasoning on/off.
4. **MCP servers** — this repo's `.zcode/config.example.json`: `mcp.servers.<name> = {type: "http",
   url, headers}`. Copy that shape; the live `.zcode/config.json` holds the same four servers
   (`web-reader`, `zread`, `web-search-prime`, `exa`) with real credentials.
5. **Registry — existence and entitlement only** — `~/.zcode/v2/config.json` `.provider` (which
   providers and model ids exist) and `~/.zcode/v2/coding-plan-cache.json` (which plans are
   `available` vs `coding_plan_not_entitled`). Never read a selection string off these.

## Verified `model:` vocabulary (agent definitions)

- `<scope>/<modelId>` with scope `account:<plan>`. The shipped template lists exactly:
  `account:zai-individual-coding-plan`, `account:zai-team-coding-plan`, `account:zai-start-plan`,
  `account:zai-offpeak-idle-plan`, and the four `account:bigmodel-*` equivalents.
- A bare `<modelId>` also loads (`~/.zcode/agents/code-reviewer.md`: `model: GLM-5.3-Flash`) but
  resolves through the ambient default provider, and is ambiguous when several providers carry the
  same model id — `GLM-5.3-Flash` appears under four of them.
- Custom providers (UUID keys in the registry, e.g. `91b0a8e2-…` = "QwenCloud Token Plan"):
  **not verified as a def string** — see Open items.
- Legacy `custom:<urlencoded-provider>:<modelId>` (e.g.
  `custom:builtin%3Azai-coding-plan:GLM-5.3-Flash`) still appears in the parent template
  `nam20485/swarm-context`. Superseded — do not write it into new defs.
- `builtin:<plan>` is a registry key, **not** a valid selection.

## Failure-mode catalogue

| Symptom | Cause | Remedy |
|---|---|---|
| `Cannot start subagent: Provider unavailable / 供应商不存在或不可用 [reason=provider-not-found; selection=…]` | the `model:` scope is not a valid selection (a registry key, or a stale legacy form) | copy a scope from the shipped template or a working def; confirm from telemetry afterwards |
| Subagent spawns but meanders / burns tokens on one search | reasoning enabled for that model | `thoughtLevel: off` in the def, then verify `request.body.thinking` in that subagent's `model-io` JSONL rather than trusting the label |
| A session transcript turns up as `.zcode/agents/<first line of the prompt>.md` | ZCode's export/save wrote into the agent roster, where it then loads as a bogus agent definition | move it out of `.zcode/agents/`; the roster should contain only real defs |
| An edited def appears to have no effect | agent definitions are read at app startup | fully quit and relaunch ZCode — a new session is not enough |

## Verifying a change without spending a swarm run

Spawn **one** worker with a trivial read-only task (its own toolset is `Read, Grep, Glob`, so a
Glob-plus-Grep question costs one or two calls), then read the newest
`~/.zcode/cli/rollout/model-io-sess_subagent_agent_*.jsonl` for `model.providerId` / `model.modelId`
and `request.body.thinking`. A failed spawn writes **no** subagent telemetry at all — which is itself
the signal that the model id was rejected before any model call.

## Open items

- **Custom-provider (UUID) def syntax is unverified.** Candidates: `custom:<uuid>:<modelId>` (parent
  template) vs `<uuid>/<modelId>` (this repo's `swarm-orchestrator.md`). Telemetry resolves
  `providerId` to the bare UUID for real sessions, and the shipped template covers only `account:`
  scopes, so neither form is backed by a shipped example. Cheapest discriminator: a throwaway def
  pinned to `<uuid>/qwen3.8-flash` (cheap model, same provider) plus a one-line spawn — not a
  `$swarm` run on the expensive king model.
- **Whether `thoughtLevel: off` is honoured for GLM-5.3-Flash.** `.agents/memory.md:55` records a
  2026-09-10 observation that it blocks spawning entirely; every test so far died on the model id
  first, so the claim is still untested. Settle it from the subagent's `model-io` JSONL once a spawn
  succeeds.
