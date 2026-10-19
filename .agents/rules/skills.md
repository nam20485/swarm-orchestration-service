# Skills

Skill creation conventions.

## Spec compliance is mandatory

**All skills must be strictly compliant with the [Agent Skills specification](https://agentskills.io/specification).** Before creating or modifying any skill, review the current spec at <https://agentskills.io/specification> and follow it exactly — do not work from memory of the spec, which may be stale. This applies to `SKILL.md` frontmatter (field names, constraints, `name` naming/length rules), the directory layout (`scripts/`, `references/`, `assets/`), progressive-disclosure token budgets, and file-reference conventions.

Validate with the official validator before finishing:

```bash
uvx --from skills-ref agentskills validate ./my-skill
```

(Package `skills-ref`, executable `agentskills` — the bare `skills-ref` command does not exist.)

If anything in this rules file conflicts with the spec, the spec wins — update this file.

## Standard directory layout

- `SKILL.md` — required: metadata (`name`, `description`, optional `license`/`compatibility`/`metadata`/`allowed-tools`) + the agent's instructions.
- `scripts/` — executable code only (Python, Bash, JavaScript, PowerShell, etc.).
- `references/` — on-demand documentation loaded into context as needed.
- `assets/` — static files used in output (templates, icons, schemas, lookup tables).

`name` must match the parent directory name: lowercase `a-z`, `0-9`, hyphens only; no leading/trailing/consecutive hyphens; ≤ 64 chars.

## Prefer scripts over prose for repeatable operations

**When a skill must perform a repeatable operation, encode it as a script under `scripts/` rather than as prose steps in `SKILL.md`.**

Determinism matters: a skill runs many times, often across different sessions, models, and contexts. Prose instructions are re-interpreted on every run, so they drift — an agent takes a slightly different path each time, produces slightly different output, or skips an edge case. A script executes the same steps in the same order on every run, giving a deterministic, reproducible outcome.

Apply this when the skill operation is:

- A multi-step procedure (e.g. scaffold a structure, transform a document, call a sequence of APIs).
- Something that must produce consistent, comparable output across runs.
- Stateful or order-dependent (create resources, then link them, then validate).
- Error-prone when done by hand (argument formatting, JSON/CSV building, escaping).

Keep `SKILL.md` for: triggers, decision points, when-to-use guidance, and the call site that invokes the script(s). Move the *how* into `scripts/`.

Script requirements (per the spec):

- Be self-contained or clearly document their dependencies.
- Include helpful error messages.
- Handle edge cases gracefully.
- Default to cross-platform PowerShell (`pwsh`) — see `.agents/rules/coding-style.md`. Use another language only when the task demands it and note the exception in the skill.

The skill's whole job should still be reproducible from its directory alone — no external file dependencies outside the skill's own `scripts/` (see `skills_must_be_self_contained`).

## Progressive disclosure

Skills load progressively: metadata (~100 tokens) at startup, then the full `SKILL.md` body on activation, then `scripts/`/`references/`/`assets/` only when the task calls for them. Keep `SKILL.md` under 500 lines; push detail into referenced files one level deep from `SKILL.md`.

<!-- canary: teal-lemur-2 -->
