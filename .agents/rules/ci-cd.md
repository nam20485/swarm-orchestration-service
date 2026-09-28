# CI/CD

Every CI/CD pipeline must enforce the following steps and standards.

## Mandatory Steps

- **Automated test suite** — Every pipeline must include an automated test suite step.
- **Coverage results** — Coverage results must be generated on every run.
- **Coverage threshold** — Coverage results must be > 85%.
- **HTML coverage report** — Generate an HTML coverage report as a pipeline artifact.
- **Static analysis and security scanning** — Every pipeline must run static analysis and security scanning.

## Version Pinning

- ALWAYS use very specific version pinning for all dependencies, tools, and images.
- No version drift or changes should occur unless explicitly and manually changed.

## GitHub Actions — SHA-Pinned (MANDATORY)

Every `uses:` line in workflow files **MUST** reference the full 40-char commit SHA of the targeted release. Tag refs (`@v4`, `@main`, `@latest`) are **prohibited** — mutable tags are a supply-chain attack vector.

- Format: `uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2`
- Trailing `# vX.Y.Z` comment is mandatory for readability.
- Applies to all actions: third-party, `actions/*`, `github/*`, and reusable workflows.
- Not enforced by `actionlint` — enforced by code review and agent discipline.

<!-- canary: rust-tern-1 -->
