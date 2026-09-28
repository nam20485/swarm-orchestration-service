# Qwen Code Documentation Lookup

Rule: whenever a task involves **Qwen Code** — questions about its usage, features, configuration, setup, or troubleshooting — answer from the official Qwen Code documentation, not from memory.

Machine-readable access points:

- **Documentation index** — a markdown `llms.txt` listing every docs page (user guide, IDE integrations, features, configuration, developer guide, support) with title and one-line description: `https://qwenlm.github.io/qwen-code-docs/llms.txt`. It is an index only (links + descriptions, ~4.6 KB); there is **no** `llms-full.txt` full-content dump.
- **Individual pages** — raw Markdown from the upstream repo's `docs/` directory (`QwenLM/qwen-code`): `https://raw.githubusercontent.com/QwenLM/qwen-code/main/docs/<path>.md`. Derive `<path>` from the site URL by stripping the `/en/` prefix and the trailing slash, then appending `.md`; e.g. page `https://qwenlm.github.io/qwen-code-docs/en/users/features/mcp/` → `https://raw.githubusercontent.com/QwenLM/qwen-code/main/docs/users/features/mcp.md`.

Decision points:

- Broad or unknown-scope question → fetch `llms.txt` and locate the relevant page.
- Known page path (or one discovered from `llms.txt`) → fetch just that page's raw Markdown to save context.
- Raw path returns 404 (generated pages such as the blog index) → fall back to fetching the rendered site page.

## Measured context-loading contract (2026-09-27/28, this host's installed bundle)

Established by tracing the shipped CLI JS (`"<install>/lib/chunks/*.js"`; here
`/usr/lib/Qwen Code Desktop/runtime/qwen-code/lib`) and by capturing what real sessions actually
loaded via the `InstructionsLoaded` hook — **not** inferred from a config registry or from
`~/AGENTS.md`'s tier table, both of which were wrong.

| Mechanism | What actually loads | Evidence |
| --- | --- | --- |
| Context files | default filename set is **`["QWEN.md", "AGENTS.md"]`** (`currentMemoryFilename=[DEFAULT_CONTEXT_FILENAME, AGENT_CONTEXT_FILENAME]`), plus `QWEN.local.md` at the git root when trusted | `chunk-L4HJV7W3.js` initializer; `loadCliConfig`: `if(settings.context?.fileName){setMemoryFilename(...)}else{setMemoryFilename(getAllMemoryFilenames())}` |
| Where it searches | `$QWEN_HOME`/`~/.qwen/<name>` and `<home>/<name>` **only when the searched dir is home**; otherwise a walk from cwd **up to and including the parent of the git root**, then it stops (`ultimateStopDir = dirname(projectRoot)`; without a git root, `dirname(home)`) | `getMemoryFilePathsInternalForEachDir` loop in `chunk-VNLU7PR6.js` |
| Rules | `~/.qwen/rules/**` then `<gitRoot>/.qwen/rules/**`; only `paths:` and `description` frontmatter keys are read; no `paths:` ⇒ baseline (every request); `paths:` are picomatch `{dot:true}` on **project-root-relative** paths and inject **once per registry lifetime**; project rules require folder trust (which defaults to **trusted** unless `security.folderTrust.enabled` is set) | `loadRules` / `ConditionalRulesRegistry` |
| `.agents/` | **not** a context or rules source — but it **IS** a skills root: `SKILL_PROVIDER_CONFIG_DIRS = [".qwen", ".agents"]` → `<project>/.agents/skills` and `~/.agents/skills` are scanned | `chunk-TNRA7AQQ.js` + `getSkillsBaseDirs` |
| `.cursorrules`, `.cursor/rules/*.mdc` | **no support at all** — the string appears nowhere in the bundle, code or prose | grep over `lib/` → 0 matches |
| `@` prompt completion | crawls **only the session cwd** (`config.getTargetDir()`), max 24 fetched / 8 shown, honoring `.gitignore`, `.qwenignore`, `.agentignore`, `.aiignore` | `useAtCompletion` + `FileSearchFactory` |

Corrections to claims that were too strong:

- `context.fileName` **replaces** the whole set (`setMemoryFilename` assigns, never merges), so listing
  a custom name without also listing `AGENTS.md` silently drops the file that carries the TOC.
  (`getContextFileNames()`, which defaults to `["QWEN.md"]`, is used only to locate an **extension's**
  own context file — it is not the project/global loader.)
- `@import` **does** expand inside `AGENTS.md` — `processImports` runs on every loaded context file's
  content with no basename test (also recursive to depth 5, cycle-guarded, no size cap, relative to
  the *importing file's* directory). **But traversal is refused above the importing file's git root**
  (`validateImportPath` + `isSubpath`), rendered as `<!-- Import failed: … - Path traversal attempt -->`
  in tree mode and silently skipped in flat mode. So a repo `AGENTS.md` **can** inline
  `@.agents/rules/validation.md`, and **cannot** reach `~/.qwen/…` or a sibling repo.
- Rules files get **no** `@import` processing, and their bodies are passed through `stripHtmlComments`
  before injection — so an HTML-comment canary is invisible inside `.qwen/rules/`. Canary tokens live
  in `.agents/rules/*.md`, which are read as ordinary files; keep them there.
- There is no per-rule size cap; the only guard is a soft warning when always-on context exceeds
  `min(15% of the window, 10000 tokens)`.

Live result of the above on this host, captured mechanically over 5 repo-rooted sessions: a session
rooted in a repo loads **only** `<repo>/AGENTS.md` + `~/.qwen/output-language.md` — `~/AGENTS.md` does
**not** load, because the walk stops at the git root's parent. (Hook payloads label
`output-language.md` as `memory_type: "extension"`.)

Verified negatives, not open questions anymore (build 0.24.6, traced in code):

- **`InstructionsLoaded` does NOT fire for `.qwen/rules/`.** `loadRules(projectRoot, folderTrust,
  excludes, extensionRuleSources)` takes no `onInstructionsLoaded` callback, and rules are concatenated
  into `memoryContent` *after* every context-file notification has been emitted. Conditional injection at
  runtime is likewise silent (`ConditionalRulesRegistry.matchAndConsume` logs only
  `[RULES_DISCOVERY] Injecting conditional rule: <path>`). Proof channels that do exist: the canary
  recital, and the transcript fences — context files are wrapped `--- Context from: <rel> ---`, rules
  `--- Rule from: <displayPath> ---`, so the two are distinguishable in a transcript.
- **No documented UI surface proves what loaded.** The "footer shows the count of loaded context files"
  (`settings.md:911`) and "`/memory` shows which files are loaded" (`memory.md:248`) are not implemented
  in 0.24.6; `qwen hooks` prints nothing and exits 0; `/context detail` cannot itemize rules because its
  parser regex matches only `--- Context from:`. The real (undocumented) surface is the first-turn
  `Read context files: …` banner. The only machine-readable proof is this repo's hook log.
- `context.fileName` replace-vs-augment is **undocumented** — code only. Same for
  `QWEN_CODE_TRUSTED_FOLDERS_PATH`, the `mergeStrategy: "concat"` / `requiresRestart: false` hook schema,
  child-before-parent import ordering, the `maxDepth: 5` import cap, and `--session-id`.
- Docs drift to distrust: `headless.md`'s example shows `subtype: "session_start"` where the code emits
  `subtype: "init"`; `-p/--prompt` is presented as the headless entry point but `--help` marks it
  deprecated in favour of the positional prompt.

One item remains **unverified**: whether `contextRuleExcludes` is ever populated from a setting in this
build (the plumbing exists; no schema key was found). Do not design around it.

<!-- canary: cobalt-swift-3 -->