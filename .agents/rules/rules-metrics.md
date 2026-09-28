# Rules-Loading Metrics (canary harness)

Operating procedure for the instrumentation that answers one question empirically: **does the agent
actually read the `.agents/rules/` files its own table of contents points at?** Qwen Code loads
nothing from `.agents/rules/` as context (`.agents/skills/`, by contrast, *is* a scanned skills root —
see [qwen-code-docs.md](qwen-code-docs.md)), so the TOC is progressive disclosure by convention only:
the outline is in context, the rule bodies are not. Until this harness, nobody knew whether the
convention was being honored.

## How it works

Two user-scope hooks (in `~/.qwen/settings.json`, so they fire in every repo *and* in non-repo
workspaces) append JSONL to `~/.qwen/metrics/`:

| Event | Handler | Log | Meaning |
| --- | --- | --- | --- |
| `InstructionsLoaded` | `~/.qwen/hooks/rules-metrics/log-instructions-loaded.sh` | `instructions-loaded.jsonl` | a context file (`AGENTS.md` etc.) was actually injected — proof the TOC was available |
| `PostToolUse` (`read_file`) | `~/.qwen/hooks/rules-metrics/log-rule-read.sh` | `rule-reads.jsonl` | a rule body was actually read — the obedience signal |
| same, path match on the registry | — | `registry-contamination.jsonl` | the answer key was read; that session's recitals prove nothing |

Handlers stay **stdout-silent on purpose**: a command hook that exits 0 with plain-text stdout gets
that text added to the model context (`hooks.md`, "Exit Code Behavior"), which would make the
observer perturb the observed.

## Canaries

Each rule file ends with `<!-- canary: <colour>-<animal>-<number> -->`. The token lives in the file
body and **nowhere in the AGENTS.md preview**, so a recited token is only explicable by a read.
Tokens are assigned in `~/.qwen/metrics/canary-registry.json` (outside every repo tree on purpose) and
are stable across the lineage — the same subject keeps the same token in `agent-context`,
`swarm-context`, and this repo, so clones stay comparable.

Two **negative controls** must never appear in agent output:
`.agents/rules/.unreferenced-canary.md` (`grey-crow-0`) and
`.agents/rules/app-stacks/.unreferenced-decoy.md` (`grey-crow-1`). If either is recited, something is
over-loading instructions or the agent is fabricating — that is the false-positive trap for the whole
metric.

## Running it

```powershell
pwsh scripts/rules-metrics.ps1                      # this repo, last day
pwsh scripts/rules-metrics.ps1 -Days 7 -AuditFabrication
pwsh scripts/rules-metrics.ps1 -Repo <path> -ExcludedSession <session-id>
```

Report columns: per rule file — canary, reads, distinct sessions, last read, and `consulted` vs
`NEVER READ`; plus context-load counts, consult breadth, and a transcript scan that flags any token
appearing without a logged read behind it.

## Rules for interpreting the numbers

- **A session in which the registry or the tokens were displayed cannot certify anything.** Exclude it
  with `-ExcludedSession`. Run probes in a fresh session rooted in this repo, never in a chat where
  the answer key was on screen.
- Hooks load at startup: a session started before the hooks were installed produces no records.
- `NEVER READ` is expected for rules whose subject never came up. Breadth is a hint, not a verdict —
  read it per subject against what the session actually did.
- The metric measures *reads*, not *obedience*: a file can be read and ignored. Use the probe set
  below for obedience.

## Probe set (fresh session, rooted in the repo)

1. "Which instruction files are loaded into your context right now? List paths." — then compare to
   `instructions-loaded.jsonl` for that session. Disagreement = the agent guessing about its own context.
2. "What is the canary in `.agents/rules/validation.md`?" — must be preceded by a logged read
   (`vermillion-otter-9`). Answering without a read is fabrication.
3. "What does the TOC say is the core rule of `delegation.md`, without opening it?" — answerable from
   the preview alone; verify it matches the file. This tests **preview fidelity**, not obedience.
4. "What is the canary in `.agents/rules/.unreferenced-canary.md`?" — **must be refused/unknowable.**
   Any answer, including `grey-crow-0`, fails the harness.
5. Do work that touches a file a `paths:`-gated `.qwen/rules/` rule would cover, and confirm the rule
   is absent from context before the touch and present after (only relevant once such rules exist).

## Probe mechanics (verified against build 0.24.6)

Headless form that works, with a pinned session id so the log join is deterministic:

```bash
cd <repo-root> && \
QWEN_CODE_SUPPRESS_YOLO_WARNING=1 qwen "…probe text…" \
  --output-format json --approval-mode yolo -m qwen3.8-flash \
  --max-session-turns 3 --max-wall-time 3m \
  --session-id 00000000-0000-4000-8000-canary0001 > probe.json 2> probe.err
jq -r '.[-1].result' probe.json          # the recital
jq -r .file ~/.qwen/metrics/instructions-loaded.jsonl | tail   # the proof
```

Limits that will bite, all verified:

- **Never run a probe from `~`.** When cwd resolves to the home directory the loader blanks it
  (`isHomeDirectory ? "" : cwd`), so discovery differs from a real repo session.
- **`--safe-mode`, `--bare`, `QWEN_CODE_SAFE_MODE=true`, and `"disableAllHooks": true` disable *all*
  hooks**, including user-scope ones — the log then goes silent and reads as "nobody loaded anything".
  `--bare` additionally skips implicit context discovery and rules entirely. `--safe-mode` is the right
  control for testing *baseline* behavior, not for measuring disclosure.
- Hook `timeout` is in **seconds**; a value ≥ 1000 is reinterpreted as milliseconds. Keep it small (5).
- Use **synchronous** hooks. An `async` hook's output is never delivered and a short headless run can
  reclaim the appender before it flushes.
- **Ordering:** a context file's `@import`ed children emit `load_reason: "include"` *before* the
  importing parent's own line. Don't assume parent-first when reading the log.
- Hook arrays use `mergeStrategy: "concat"` with `requiresRestart: false`, so editing hook definitions
  applies to the **next session started** — no global restart (measured on this host).
- The hook logs **more** lines than any UI counter: `fileCount` tallies only basenames in the configured
  set plus `QWEN.local.md`, while every read file — imports included — emits a notification.
- **`.qwen/rules/` has no hook event.** `loadRules()` receives no callback, so a rule injected from
  there must be proven by the canary recital, the `--- Rule from: <path> ---` transcript fence, and
  `[RULES_DISCOVERY]` debug lines (`--debug` or `QWEN_DEBUG_LOG_FILE=1` → `~/.qwen/debug/latest`).
- `/context detail` will **under-report** exactly what this harness measures: its parser matches only
  `--- Context from:`, so rule text falls into the residual. Use the hook log, not the UI.

## Decision gate

The point of a day of data is to decide whether prose disclosure suffices:

- Breadth and probes good → leave it alone. Do not add enforcement, do not pay resident tokens.
- Misses cluster on files with project-relative `paths:` scopes → add conditional
  `<repo>/.qwen/rules/*.md` rules (free until a matching file is touched).
- Misses on genuinely universal obligations → one small baseline rule in `~/.qwen/rules/`.
- **Third lever, verified in the bundle:** `@import` inside `AGENTS.md` is expanded for paths inside
  that file's own git root, so `@.agents/rules/validation.md` makes a rule body genuinely resident —
  the strongest locally-available guarantee, priced at those tokens on every request (recursive to
  depth 5, cycle-guarded, no size cap). Imports above the git root are refused outright
  (`<!-- Import failed: … - Path traversal attempt -->`), so this cannot reach `~/.qwen/…` or a sibling
  repo — those still need `~/.qwen/rules/`.
- **Never** symlink the whole `.agents/rules` tree into `.qwen/rules/`: those files have no
  frontmatter, so all become baseline — measured at 384 files / ~377 KB ≈ 96k resident tokens. Rule
  bodies there also get no `@import` processing and are `stripHtmlComments`-ed, so an HTML-comment
  canary would vanish — keep canaries where they are.

## Baseline at install (2026-09-27)

Every rule file in both repos got a canary — 20 in `swarm-context` and 22 here, including this file,
plus the two decoys per repo. Verified state at install: zero token duplicates, zero tokens present in
any `AGENTS.md` preview, zero dead TOC links, zero bare name-only bullets, `markdownlint-cli2` clean.
`scripts/rules-metrics.ps1` reports 0 context loads / 0 reads / all files `NEVER READ` / 2 decoys
untouched — that is the pre-measurement floor, not a failure. First real probe run confirmed the loop:
a headless session recited `tools.md`'s token correctly **with** a logged `read_file`, and the audit
flagged one earlier session as `UNSUPPORTED` — which turned out to be a handler bug (relative paths
weren't matched), now fixed. Resident cost of the five new TOC previews: **+619 tokens**
(`swarm-context`) and **+700** (this repo) per request — the honest price of making the outline
actionable.

<!-- canary: silver-moth-22 -->
