# Tools

Detailed tool guidance and decision points for this project.

## Discontinued: Sequential-Thinking and Memory knowledge-graph

Use of these MCP servers was discontinued on 2026-09-12 — both were deemed
redundant and inferior to the model's builtin reasoning and memory. Their server
definitions were removed from the MCP configs (`.opencode/opencode.jsonc` and,
where present, `.zcode/config*.json`) and the former usage guidance is withdrawn;
do not call their tools or re-add usage guidance.

## Semantic Search (Codebase Indexing)

The `semantic_search` tool (powered by Kilo Code's codebase indexing) finds code by **meaning**, not by exact text. It uses AI embeddings to rank semantic code blocks (functions, classes, methods, markdown sections) against a natural-language query, returning ranked matches with file paths and line ranges.

**Prerequisite:** Codebase indexing is enabled and available for this project. The tool errors only if the index is disabled or empty; otherwise assume it is ready.

**When to use `semantic_search` — prefer it as the first probe when you:**

- Are exploring an **unfamiliar** code area before you know exact identifiers.
- Are looking for a feature, behavior, or **intent** ("authentication logic", "database connection setup", "error handling patterns", "API endpoint definitions", "rate limiting").
- Want to locate **conceptually related** implementations or similar code patterns spread across the codebase.
- Need to **narrow a large codebase** before following up with `Grep` / `Glob` / `Read`.

**When NOT to use it — pick the specialized tool instead:**

- Exact symbol, regex, or keyword lookups → `Grep`.
- Finding files by name or extension (e.g. `**/*.ts`, `*.config.js`) → `Glob`.
- Reading a file whose path you already know → `Read`.
- Exploring files **outside** the current workspace → `Grep` / `Glob` / `Read` (`semantic_search` is workspace-scoped).

**How to query:**

- Write the query in **natural language, in English** (e.g. "where are user sessions validated before API access?").
- Prefer **specific, descriptive** phrasing over vague nouns. "Redis retry/backoff handling" beats "redis".
- To restrict results to a subdirectory, pass the `path` argument (relative to the workspace root). Leave it empty for a whole-workspace search.
- After getting ranked matches, follow up with `Read` (to inspect the returned line ranges) or `Grep` (to enumerate exact occurrences of an identifier you discovered).

**Tuning (optional, set in `indexing` under `kilo.jsonc`):**

- `searchMaxResults` (default `50`) — lower for faster, more focused results; raise for broader context.
- `searchMinScore` (default `0.4`) — raise to require closer matches; lower to surface tangentially related code.

Full guide: [Codebase Indexing](https://github.com/Kilo-Org/kilocode/blob/main/packages/kilo-docs/pages/customize/context/codebase-indexing.md).

## Web & Repository Research (Z.AI MCP)

These three **remote** Z.AI MCP servers (configured in [`.opencode/opencode.jsonc`](../../.opencode/opencode.jsonc)) authenticate via the `Authorization: {env:Z_AI_API_KEY}` header. Z.AI requires the `Bearer <api-key>` header format and opencode substitutes the env var verbatim as the full header value, so **`Z_AI_API_KEY` must be the full header value, `Bearer <api-key>`**. The servers require no local install; use them for reliable, structured external information retrieval instead of ad-hoc fetching.

### `web-search-prime` — web search

Tool: **`webSearchPrime`** — searches the web; returns page titles, URLs, summaries, site names, and site icons.

Features:

- Comprehensive web search to retrieve the latest web information and resources.
- Real-time updated information: news, stock prices, weather, and more.
- HTTP-based remote MCP service — no local installation required.

Key params: `content_size` (`medium` default, `high` for comprehensive), `location` (`cn` / `us`), `search_domain_filter` (whitelist a domain), `search_recency_filter` (`oneDay` / `oneWeek` / `oneMonth` / `oneYear` / `noLimit`). Keep queries ≤ 70 chars.

Example scenarios:

- Best-practice surveys, competitive analysis, and dependency/API research.
- Factual questions needing current external info (e.g. "find best practices for Python asynchronous programming").

### `web-reader` — URL reader

Tool: **`webReader`** — fetches a URL and converts it to large-model-friendly input (markdown / text / html). Prefer this over generic `webfetch` when available.

Features:

- **Web Content Reading** — fetch the complete content of any webpage, including text and links.
- **Structured Data** — extract structured data such as title, main body, and metadata.
- **Remote Service** — HTTP-based remote MCP service, no local installation required.

Example scenarios:

- **API documentation reading and summarization** — fetch official docs pages (titles, body, examples, release notes) and distill key takeaways to speed integration.
- **Open-source project page parsing** — parse project sites and repository pages (README, release notes, usage guides) into core info and link lists for evaluation.
- **Technical article knowledge extraction** — pull steps, commands, and caveats out of blogs/tutorials/guides into actionable developer notes and task lists.
- **Bug resolution from reference documentation** — read publicly documented fixes on a specified page and apply them as the reference solution.
- **Knowledge-base construction and synchronization** — convert pages to structured data and follow in-page links for incremental synchronization.

### `zread` — public GitHub repository reader

Reads **public** GitHub repositories without cloning (powered by zread.ai) — open-source repository Q&A: documentation, code structure, and file content.

Features:

- Search documentation, code, and comments in GitHub repositories.
- Get the directory structure and file list of a repository to quickly master project layout.
- Read the complete code content of specified files to deeply analyze implementation details.

Tools:

- **`search_doc`** — search a repository's knowledge documentation: repo knowledge, news, recent issues, PRs, and contributors.
- **`get_repo_structure`** — directory structure and file list; understand module splitting and organization.
- **`read_file`** — complete contents of a specified file; analyze implementation details in depth.

Constraints: requires `owner/repo` names; only **public** repositories are supported.

Example scenarios:

- **Learn a library fast** — `search_doc` + `get_repo_structure` for core concepts, installation steps, and code organization before writing code against it.
- **Mine issue/commit history** — find solutions or fix records for a problem you are hitting ("has anyone hit this before?").
- **Secondary development and debugging** — `read_file` the core files to analyze implementation logic before extending or fixing.
- **Pre-adoption dependency evaluation** — activity, code quality, and maintenance status before introducing a new dependency.

### Decision points

- Need current facts from the open web → `webSearchPrime`, then `webReader` to drill into a specific result.
- Need to understand an open-source repo → `zread` first (`get_repo_structure` + `search_doc`), then `read_file` for implementation details.
- For broad, multi-source surveys, delegate to the `researcher` subagent; use these tools directly for quick, single-shot lookups.

Sources: Z.AI DevPack docs — [Web Search](https://docs.z.ai/devpack/mcp/search-mcp-server) · [Web Reader](https://docs.z.ai/devpack/mcp/reader-mcp-server) · [Zread](https://docs.z.ai/devpack/mcp/zread-mcp-server) (overview → Example Scenarios sections).

## Exa Search (MCP)

The **remote** Exa MCP server authenticates via `exaApiKey={env:EXA_API_KEY}` and requires no local install. Use it as a complement to Z.AI when its neural search, code-context, or crawling fits better.

- **`web_search_exa`** — Keyword/neural web search. Fallback when Z.AI `webSearchPrime` is rate-limited.
- **`web_search_advanced_exa`** — Filtered search (date, domain, text-match, count). Scoped queries.
- **`web_fetch_exa`** — Fetch a URL to clean markdown/text. Alternative to Z.AI `webReader`.
- **`get_code_context_exa`** — Code context (functions, types, usage) for "how is X used?" before `zread` for full files.
- **`crawling_exa`** — Crawl multiple pages of a site; collect a doc subsite in one call.

Prefer Z.AI `webSearchPrime`/`webReader` as the default for single-shot lookups; reach for Exa when its neural search, code-context, or crawling fits better.

## Scratch Workspaces (per-run temp state)

Per-run scratch — composed drivers, rendered bodies, trace logs, throwaway diagnostics — lives namespaced **by repo slug** under `/tmp/kilo/<repo-slug>/`, **not** loose in a flat `/tmp/kilo/`. This isolates one repo's run from another's (a stale driver on disk hardcodes a specific repo + node set, so silent cross-run mis-targeting of a GitHub-mutating run is the risk) and makes cleanup a single `rm -rf /tmp/kilo/<repo-slug>`.

Standard layout:

```text
/tmp/kilo/<repo-slug>/
  ├─ driver.<ext>   # composed orchestration script for this run
  ├─ bodies/        # rendered file bodies passed to tools (e.g. issue -BodyFile)
  ├─ logs/          # trace / run logs
  └─ diag/          # throwaway diagnostic / experiment scripts
```

- **Root is `/tmp/kilo/`** — the bash tool's pre-approved external-work directory. Scratch goes **under** it (not directly under `/tmp/<slug>/`), so there is no external-dir approval prompt and no collision with the OS `/tmp`.
- **Create on demand** (`mkdir -p` / `New-Item -ItemType Directory -Force`). Never assume a previous run's scratch belongs to the current one — before reusing anything under `/tmp/kilo/`, confirm the slug matches the current repo.
- **Durable artifacts are not scratch.** Trace logs worth keeping, fix write-ups, and decision records go under `docs/plans/`, not `/tmp/kilo/`.
