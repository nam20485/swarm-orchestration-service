# Grandparent upstream graft — syncing `swarm-context` with `intel-agency/agent-context`

**Status: PARKED (trigger-gated) — deferred by owner 2026-09-11**: *"document … and look at it some other time, if/when we run into an issue where we need something from our grandpa."* Do not execute without owner direction. Nothing below has been run beyond the safe, fetch-only prep in §3.

## 1. The chain

```
intel-agency/agent-context        (grandparent — public template, default branch development)
        └─ nam20485/swarm-context         (parent — the swarm-harness template we clone from)
                └─ nam20485/swarm-orchestration-service   (this repo)
```

- **This repo**: `origin` = `swarm-orchestration-service`, `upstream` = `nam20485/swarm-context`. Real shared ancestry (bootstrap graft, PR #1) — plain merges work; each sync is a reviewed PR (plan §5 Decision 8).
- **Parent** (local clone `~/src/github/nam20485/swarm-context`): `origin` = `nam20485/swarm-context`; `upstream` = `intel-agency/agent-context` — **added 2026-09-11, push URL DISABLEd**. But there is **no shared ancestry** with the grandparent (§2), so the first sync is not a plain merge.

## 2. Why a plain merge will fail (verified 2026-09-11)

`swarm-context` is a webui/template-route-style file-copy squash — the same class of seed this repo was before its bootstrap graft:

- Its root `1375d86a42b2f8ddfa9cf60656797f9d7a3ddfa8` ("Initial commit", no parents) does **not** exist in the grandparent (`gh api repos/intel-agency/agent-context/commits/1375d86a…` → 422).
- Its tree `dd79f4fd…` **exactly matches** grandparent commit `ba935fc4a8855c20ecd5073301da86be2f77c19a` — a clean one-point correspondence; everything before that point is byte-identical.
- Grandparent `development` was **27 commits ahead** of `ba935fc4` (as of 2026-09-10): memory-rules-system, powershell-rules-system, exploration-inhibitors branches landed, plan-notes cleanup/personal-notes removal, local-LLM + fnm setup guide (PR #24).
- `swarm-context` had **46 own commits** on top of the seed; this repo sat **58 commits** on top of the parent's then-HEAD `0d9c7dd` (both counts drift — re-derive before executing).

Consequence: `git merge upstream/development` in swarm-context refuses (unrelated histories). And unlike this repo's bootstrap graft (where the seed tree matched the parent's HEAD, so `remote add` + `fetch` + `reset --soft` + force-push sufficed), the parent now has real work since its seed — the graft must **replay** commits (rebase), and it **cascades to this repo**, which is rooted at the same squashed `1375d86`.

## 3. Already-done prep (safe, reversible)

In the swarm-context local clone:

- `git remote add upstream git@github.com:intel-agency/agent-context.git`
- `git fetch upstream` (brings `development`, `main`, `dev/*`, `mn/*` remote-tracking branches)
- `git remote set-url --push upstream DISABLE` — the grandparent is a third-party public repo; **never push to it**.

## 4. Option A — rebase graft (recommended; end-state matches this repo's)

**Preconditions**: clean working trees in both repos; no open PRs on either (swarm-context's three `dev/*` branches were all merged as of 2026-09-11; this repo's `dev/phase5-hardening` merged); execute each push/rewrite as a **standalone gated command** per the source-control rules — never batched.

**Re-derive drift-prone values first:**

```bash
git -C ~/src/github/nam20485/swarm-context fetch upstream
git -C ~/src/github/nam20485/swarm-context rev-list --count ba935fc4..upstream/development   # was 27
MB=$(git -C ~/src/github/nam20485/swarm-orchestration-service merge-base development upstream/development)  # was 0d9c7dd — capture BEFORE the parent rewrite
```

**Step 1 — rewrite the parent** (in `~/src/github/nam20485/swarm-context`):

```bash
git switch development
git rebase -r --onto ba935fc4a8855c20ecd5073301da86be2f77c19a 1375d86a42b2f8ddfa9cf60656797f9d7a3ddfa8 development
# conflicts expected where the grandparent's delta touched .agents/ template files that swarm-context also evolved
git range-diff 1375d86a..development@{1} ba935fc4..development   # sanity: same content changes replayed
git push --force-with-lease origin development                     # gated standalone command
```

**Step 2 — cascade to this repo** (in `~/src/github/nam20485/swarm-orchestration-service`):

```bash
git fetch upstream
git rebase -r --onto upstream/development "$MB" development
git range-diff "$MB"..development@{1} upstream/development..development
git push --force-with-lease origin development                     # gated; ruleset blocks non-ff (admin bypass exists)
```

Rebase or recreate any open feature branches off the new `development`.

**Step 3 — cold verification:**

- swarm-context: `git merge-base --is-ancestor ba935fc4 development` → true; `git diff development@{1} development` → empty modulo deliberate conflict resolutions.
- This repo: a merge-base with `upstream/development` now exists; `git diff development@{1} development` → empty modulo resolutions; full `validation.ps1 -Step all` green; PR CI green.
- Any other clones of either repo anywhere: `git fetch && git reset --hard origin/development` (destructive — gated per clone).

After this, `git merge upstream/development` is a normal merge in **both** repos forever; each future sync is a reviewed PR, same as this repo's convention today.

## 5. Option B — no-rewrite join (fallback)

One-time, in swarm-context:

```bash
git merge --allow-unrelated-histories upstream/development
```

Every file changed on both sides conflicts (there is no merge base), so this is one fat conflict-resolution session landed as a reviewed PR. It preserves all existing history and SHAs and needs no cascade — but leaves two disjoint roots forever. Use only if the force-push cascade of Option A is unacceptable.

## 6. Guardrails

- Never push to the grandparent (push URL already DISABLEd).
- Before grafting, review `git log --oneline ba935fc4..upstream/development` — confirm the grandparent's delta is actually wanted; some of it (personal-notes removal, template-plan cleanup) is aimed at template consumers like us, some may not apply.
- The `upstream` remote in the swarm-context clone is intentionally left in place while this is parked — future fetches are free and harmless.
