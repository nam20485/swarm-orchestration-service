# Turing-Alpha Bot Account — Non-Interactive Signing Strategy

Status: PROPOSED (owner decision required before Phase A; Phase B is a separate owner decision)
Date: 2026-09-10 (overnight run; strategy requested by owner)

## 1. Goal

A dedicated bot identity — the existing GitHub account **`turing-alpha`** (email forwards to the owner's real address) — for agent-authored work on this machine, ending all dependency on the owner's personal GPG passphrase and personal PATs for automation. Root causes this eliminates: passphrase-cache TTL management, agents inheriting over-scoped personal tokens, and commits that impersonate the owner.

## 2. Design: strict division of labor (Phase A — no access changes)

| Concern | Who | How |
|---|---|---|
| Commit authorship + signing | **turing-alpha** | per-repo `user.name` / `user.email` / `user.signingkey`; dedicated GPG key (below) |
| Push transport | nam20485 (unchanged) | existing SSH remote; transport auth ≠ commit authorship |
| gh API (PRs, merges, admin) | nam20485 keyring token (unchanged) | `gho_` with full scopes; admin bypass under the branch-protection ruleset |

Nothing about repo access changes in Phase A — the bot never authenticates to GitHub for push/API; it only *signs*. GitHub renders the commits "Verified" once the key and its UID email are on the account.

## 3. Phase A steps

1. **Verify the forwarding email on `turing-alpha`** (Settings → Emails). GPG key upload requires the key's UID email to match a *verified* address — the forward makes verification reachable from the owner's inbox.
2. **Generate the dedicated key non-interactively** (signing-only Ed25519, empty passphrase, machine-local):

   ```sh
   gpg --batch --pinentry-mode loopback --passphrase '' \
       --quick-generate-key "turing-alpha <bot@…>" ed25519 sign 0
   ```

3. **Upload the public key** to turing-alpha (Settings → SSH and GPG keys). Never upload — or export — the private key anywhere.
4. **Per-repo wiring** (this repo only; global config untouched):

   ```sh
   git config user.name "turing-alpha"
   git config user.email "bot@…"        # the forwarding address
   git config user.signingkey <KEYID>
   ```

5. **Smoke:** one test commit on a scratch branch → GitHub shows `Verified` + authored by turing-alpha; `git log --show-signature` verifies locally. Revert the branch.

Rollback at any point: delete the key from the account, unset the three config values. Nothing else holds state.

## 4. Phase B (separate owner decision — NOT done without sign-off)

Promote turing-alpha to collaborator with its own token (fine-grained PAT scoped to this repo). Consequences the owner must accept explicitly:

- **Governance improves**: bot PRs then require the owner's 1-approval review under the existing ruleset — human gate on agent-authored merges.
- **Policy changes**: overnight self-merge via admin bypass ends (the bot is not an admin and cannot bypass). Delegated autonomous runs would land work as *open PRs* for morning review instead of merged code.
- Token storage: `gh auth login` under a host alias (e.g. `github-turing-alpha`) or per-service env in compose — **never** a user-global file (see the GITHUB_TOKEN split-brain incident, 2026-09-10: two live PATs in `environment.d` + `~/.api-keys-export.sh` shadowed the better-scoped keyring token).

## 5. Security posture (honest trade-offs)

- An **empty-passphrase key** means machine compromise ⇒ attacker can forge bot-signed commits. Mitigations: the key grants *zero* push/API rights (Phase A), is instantly revocable on the account, and never leaves this machine. This is the same trust boundary as the existing plaintext PATs in dotfiles — strictly narrower blast radius.
- Phase B's token inherits whatever scopes it's given; keep it repo-scoped fine-grained, and never place it in `~/.api-keys-export.sh` or `environment.d`.
- The forwarding address becomes part of the commit metadata (public). If that's undesirable, register a noreply-style address on the account instead.

## 6. Prerequisites checklist

- [ ] Forwarding address added + verified on turing-alpha
- [ ] Owner decision: Phase A go/no-go
- [ ] (Later, independent) Owner decision: Phase B go/no-go
