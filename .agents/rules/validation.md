# Validation

All changes must be validated.

- Changes should be validated as they are implemented.
- All changes must be validated before committing.

## Steps

The following steps must be run as part of validation:

- build
- scan
- test

A validation script must be maintained to run these steps automatically (i.e. `validation.sh`, `validation.ps1`, etc.).

- It should mirror exactly what is run in the CI/CD pipeline.
- Update the local and CI/CD copies to keep them in sync with any changes.

## Missing Validation Script

If an agent needs to run validation and the expected script (e.g. `validation.ps1`, `validation.sh`) does not exist:

1. **Create the script** before proceeding with any validation. Write it at the repository root with the platform-appropriate extension (`.ps1` for Windows, `.sh` for Unix).
2. **Implement the three steps** — `build`, `scan`, `test` — in the order listed. Each step must fail fast (non-zero exit) on error so the script stops immediately.
3. **Make it executable** (`chmod +x validation.sh` on Unix; on Windows ensure the execution policy allows it).
4. **Commit the script** as its own change before running it, so CI/CD picks it up on the same branch.
5. **Mirror CI/CD** — inspect any existing pipeline configuration (e.g. `.github/workflows/`, `azure-pipelines.yml`) and ensure the script commands match what CI runs. If no CI config exists, choose sensible defaults for the project's language/framework and document the choices in a comment at the top of the script.

## Testing

An automated test suite must be maintained.

- Test results and coverage reports should be generated automatically.
- Test Coverage levels must be maintained as new code is added.
- Test coverage level must be > 85% at all times.

### Pester 5 gotchas (repo-verified)

Two PowerShell-testing pitfalls found in this repo's suites — both produce silently-wrong tests, not obvious failures:

1. **Never use more than one `BeforeAll` block in a `Describe`.** A second `BeforeAll` breaks `$script:`-scoped variable visibility for the whole block: variables set in the first block read as `$null` inside `It` blocks, so every test relying on them fails with "got $null". Merge setup into a single `BeforeAll` per `Describe` (`BeforeAll` inside nested `Context` blocks is fine).
2. **Never put markdown code-fence lines (```` ``` ````) inside a double-quoted here-string `@"…"@`.** Backticks are escape characters in double-quoted strings: `` `` `` collapses to one literal backtick and a trailing backtick before a newline becomes a line continuation, silently corrupting the fixture. Use a single-quoted here-string `@'…'@` for any content containing backticks, and interpolate afterwards if needed.

Symptom signature for (1): every test in one `Describe` fails with `Cannot bind argument to parameter 'Path' because it is null` (or similar `$null`-binding errors) while the `BeforeAll` visibly assigns the variable.

### Test Driven Development (TDD)

When implementing new features, TDD should be used.

- Implement failing tests to cover the required functionality.
- Implement changes to make the tests pass.
- Iterate creating tests and implementing changes to make them pass until the required functionality is implemented.

<!-- canary: vermillion-otter-9 -->
