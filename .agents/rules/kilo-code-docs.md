# Kilo Code Documentation Lookup

Rule: whenever a task involves **Kilo Code** — the CLI or the IDE extension — answer from the official Kilo documentation site, not from memory. This covers questions about Kilo Code features, configuration, and setup, and instructions to configure or set it up.

Machine-readable access points:

- **Full documentation** — a single text file containing every docs page, formatted for LLMs and agents: `https://kilo.ai/docs/llms.txt`
- **Individual pages** — raw Markdown via the API: `https://kilo.ai/docs/api/raw-markdown?path=<url-encoded-path>`. The `path` parameter is the URL-encoded path of the docs page **without** the `/docs` prefix; e.g. to fetch the "Code with AI" overview page use `https://kilo.ai/docs/api/raw-markdown?path=%2Fcode-with-ai`.

Decision points:

- Broad or unknown-scope question → fetch `llms.txt` and locate the relevant section.
- Known page path (or one discovered from `llms.txt`) → fetch just that page via the raw-markdown API to save context.

Source: [docs/using-docs-with-agents.md](../../docs/using-docs-with-agents.md)

<!-- canary: copper-shrike-19 -->
