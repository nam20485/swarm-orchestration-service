---
pair-skill: true
pair-version: 0.47.0
pair-template: 0.47.0 prod
---
# Review Changes and Create Commit

Review the current branch changes, run quality gates, and generate a commit message.

## Tasks

1. **Analyze changes**
   - Run `git status` to see all modified, staged, and untracked files
   - Run `git diff` (staged + unstaged) to understand what changed
   - Run `git log --oneline -5` to see recent commit style
   - Categorize files: **code** (Rust, TypeScript, Vue, etc.) vs **tracker** (`.pair/`)

2. **Run tests** (if code files changed)
   - Run `python3 ~/.claude/scripts/test-project.py` before committing
   - If tests fail, fix the errors before proceeding
   - Skip this step if only `.pair/` files changed

3. **Propose dev verification** (if UI/frontend code changed)
   - Ask the user if they want to launch the dev server for visual verification before committing
   - If yes: `python3 ~/.claude/scripts/build-project.py --dev` (background)
   - Wait for user confirmation that everything looks good before proceeding

4. **Tracker et code sont déjà séparés**
   - `.pair/` est un worktree de la branche tracker : ses fichiers n'apparaissent jamais dans le `git status` de la branche de code, il n'y a donc rien à démêler.
   - Si le projet n'est pas suivi par git (case "Track issues in git" décochée), `.pair/` est ignoré et ne peut pas non plus arriver dans un commit de code.

5. **Generate commit message**
   - Use conventional commits format: `type(scope): description`
   - Types: `feat`, `fix`, `refactor`, `chore`, `docs`, `test`, `perf`, `style`
   - Summary line: max 72 chars, imperative mood
   - Body (if needed): explain **why**, not what  -  the diff shows what
   - Do NOT include `Co-Authored-By` or `Generated with` lines  -  they add noise to the git history
   - Use HEREDOC format for the commit command:
     ```bash
     git commit -m "$(cat <<'EOF'
     type(scope): summary

     Optional body explaining why.
     EOF
     )"
     ```

6. **Present and confirm**
   - Show the proposed commit message(s) to the user
   - Show the list of files that will be in each commit
   - Ask for confirmation before executing
   - If the user wants to adjust, incorporate feedback

7. **Execute commits**
   - Stage relevant files (`git add <specific files>`  -  never `git add -A`)
   - Run the commit command
   - If pre-commit hook fails: fix the issue, re-stage, create a **new** commit (never `--amend`)

8. **Rebuild CLI binary if the commit affects it** (PaiR projects only)
   - The `pair` CLI binary is a separate `[[bin]]` target  -  `tauri dev`/`build-project.py --dev` does NOT rebuild it. Without this step, hooks and skills end up running a stale CLI for days.
   - Skip silently if `src-tauri/Cargo.toml` doesn't exist at the repo root (skill is global, only PaiR projects need this).
   - Otherwise, check whether the just-committed change touched the CLI's source:
     ```bash
     git diff --name-only HEAD~1 HEAD | grep -qE '^src-tauri/src/(bin/pair\.rs|pair/|state\.rs|lib\.rs)' && \
       ~/.cargo/bin/cargo build --manifest-path src-tauri/Cargo.toml --bin pair && \
       chmod +x src-tauri/target/debug/pair
     ```
   - Run only on **code** commits  -  skip after `chore(pair): update issues` (`.pair/`-only commits never affect the binary).

9. **After commit  -  Close issue if applicable**
   - If this commit is related to a `/pair-run-issue` session, proactively run `/pair-close-issue <issue-id>`
   - Do NOT wait for the user to ask  -  if you know the issue ID, close it

## Notes

- **Never skip tests**  -  quality gates run before every code commit
- **Never mix `.pair/` and code**  -  always separate commits
- **Always confirm**  -  show the message and file list before committing
