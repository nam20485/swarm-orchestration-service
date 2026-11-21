# Source Control

## Safe Commit

- Always run the `/safe-commit` skill before committing.

## Commit Workflow

When asked to commit the current set of changes in the working copy, always:

1. Run `validation.ps1` first; proceed only if it passes.
2. Break the changes into conceptual groups.
3. Commit each group with a meaningful message.

## Merge gate (user directive 2026-09-10)

Mechanical brakes on consequential git steps — never batch them into compound commands:

- **Merge only on an explicitly-read green conclusion.** The head branch's CI `conclusion` must be
  read and equal `success` before merging; the merge is issued as its own standalone command.
  Never chain a merge after `gh run watch` or a status query — a query that prints "failure" still
  exits 0.
- **Delete a merged branch only after post-merge CI on the base branch is green** — the branch
  pointer is the natural revert target while the merge is still unproven.
- **Destructive operations** (remote branch deletion, force-push, history rewrite, stash drop)
  require stating intent and consequence immediately before execution, as a standalone command.

## PR merge readiness protocol (owner directive 2026-11-20 — MUST ALWAYS BE FOLLOWED)

1. **Out-of-date head: update with a MERGE COMMIT only.** When GitHub reports "This branch is
   out-of-date with the base branch", update the head via "Update with merge commit"
   (`gh pr update-branch <N>` — merges the base into the head). **NEVER rebase a PR head onto
   the base.** (Distinct from a branch diverged from its OWN remote, which reconciles by rebase;
   PR-head-vs-base is merge-commit only.)
2. **Independent verification — NEVER self-check.** Before ANY merge, dispatch an independent
   objective subagent to verify merge readiness. It MUST present raw evidence (command output,
   not summaries) of each criterion's passing state. The orchestrator never checks merge
   readiness itself and never merges without the verifier's evidence-backed READY verdict.
3. **Auto-review green definition.** An auto-review (Kilo) passes only when:
   `unresolved threads == 0 AND (resolved threads > 0 OR (Kilo ran AND issues found == 0))`.
   Kilo MUST have run — a bare "pass" check bucket with no review activity is NOT green.

Criteria the independent verifier must evidence, all on the PR's exact current head SHA:

- `mergeable=MERGEABLE`, `mergeStateStatus=CLEAN`, `state=OPEN` (head up to date with base).
- Every workflow check COMPLETED with conclusion SUCCESS on that exact SHA (inert `droid`
  SKIPPED allowed); no failing workflow runs on the branch.
- Auto-review green per definition 3 (thread counts via GraphQL `reviewThreads`, Kilo check
  state, review-comment activity).
- `reviewDecision=APPROVED`, and the approving reviewer is a collaborator with WRITE access
  (a read-only account's approval is accepted by GitHub but does not satisfy the ruleset).
- No bypass required: a plain `gh pr merge --merge` would succeed. `--admin` only after a
  demonstrated unattainable blocker AND the owner's explicit permission.

## Monitor Workflows

- After pushing, monitor the workflows to ensure they are running as expected.
- If a workflow fails, run the `fix-failing-workflows` skill before any ad-hoc investigation (user
  directive 2026-09-10).
- Investigate and fix the issue before proceeding; repeat until all workflows pass.

## Branching

- Create a new branch for each feature or bug fix.
- Use a descriptive branch name that reflects the work being done.
- Use the form `<base-branch-prefix>/<branch-name>`, i.e. `mn/new-feature` or `dev/<branch-name>`.

## Pull Requests

- Create a pull request for each branch.
- Use a descriptive title and description that reflects the work being done.
- **Always set a milestone** when creating a pull request.
- **Always set the project** (assign to the active Projects v2 board) when creating a pull request.
- Request a review from the appropriate team member before merging.
- Once reviews have left comments, address all comments before merging.
- For each comment that is addressed, leave a comment explaining the resolution and mark the thread as RESOLVED state.
- ADDRESS ALL COMMENTS BEFORE MERGING.

## Resolving review comments

When resolving PR review comments (automatically or manually), follow this sequence for **every** unresolved thread:

1. **Analyze** the comment. If no code change is needed (functionality works as designed, comment is outdated, etc.), skip to step 3 and explain why no change is warranted.
2. **Make the code change**, commit, and push.
3. **Reply to the comment thread** with a summary of the fix or the reason no change was needed. Use the GraphQL `addPullRequestReviewThreadReply` mutation (or `gh pr comment` for non-thread comments) so the reply is attached to the thread.
4. **Mark the thread as RESOLVED** via the GraphQL `resolveReviewThread` mutation (or the GitHub REST API equivalent). Do not leave threads open after replying.

```graphql
# Reply to a review thread
mutation {
  addPullRequestReviewThreadReply(input: {
    pullRequestReviewThreadId: "<thread-id>"
    body: "Fixed: <summary of change>"
  }) { comment { id } }
}

# Resolve the thread
mutation {
  resolveReviewThread(input: {
    threadId: "<thread-id>"
  }) { thread { id isResolved } }
}
```

After resolving all threads, verify zero unresolved comments remain by querying `reviewThreads` and filtering `isResolved == false`. Leave a final summary comment on the PR listing all resolved threads and their fixes.

<!-- canary: indigo-badger-4 -->
