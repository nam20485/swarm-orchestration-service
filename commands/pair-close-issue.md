---
pair-skill: true
pair-version: 0.47.0
pair-template: 0.47.0 prod
---
# Close PaiR Issue with Commit Summary

Fermer une issue PaiR avec résumé des commits et mise à jour Redmine/GitHub optionnelle.

> Syntaxe `pair` CLI : voir `.pair/AGENTS.md` **à la racine du projet courant** (chemin relatif, varie par projet).

## Input

$ARGUMENTS - Issue ID (e.g., pair-ab12)

## Tasks

1. **Validate input**
   - Ensure an issue ID is provided in `$ARGUMENTS`.
   - If no ID provided, ask the user for the issue ID.

**1.5. Parent guard  -  inventory children before closing any issue with children**

   This rule applies to **any issue that has children** (epic, campaign, spec, or any parent issue)  -  not just type `epic`.

   Before running the close script, fetch the issue: `pair show <id> --json`. Inspect `children`:
   - Run `pair children <id>` to list them (if `pair show` doesn't already include them).
   - Filter children whose status is **not `closed`** (any of `open`, `in_progress`, `paused`, `blocked`, `deferred` qualifies).
   - **If at least one unfinished child exists**, do NOT proceed to step 2. Display the inventory and ask via AskUserQuestion:
     - Header: "Parent"
     - Question: "Le ticket <id> a N enfant(s) non terminé(s). Que faire ?"
     - Options:
       1. `Fermer parent + enfants`  -  "Cascade-close: ferme tous les enfants un par un, puis le parent"
       2. `Fermer parent seul`  -  "Laisse les enfants ouverts, ferme uniquement le parent"
       3. `Annuler`  -  "Ne rien fermer"
   - **If "Fermer parent + enfants"**: loop `/pair-close-issue <child-id>` (this same skill, recursive) on each unfinished child, sequentially. Each call preserves the full workflow per child (Redmine/GitHub sync, commit summary, version question). Only after all children are closed, proceed to step 2 for the parent itself.
   - **If "Fermer parent seul"**: proceed to step 2 directly.
   - **If "Annuler"**: stop, output "Fermeture annulée" and exit.
   - If all children are already closed, or the issue has no children, skip this step silently.

   Mirror of the delete-cascade UX in `useIssueDialogs.ts::confirmParentDelete`.

2. **Run the close-issue script in auto mode**

   ```bash
   python3 ~/.claude/scripts/close-issue.py <issue-id> --auto --cli pair
   ```

   This single call handles:
   - Collecting recent commits (uses issue checkpoint SHA if available, otherwise last 10 commits)
   - `pair comments add` to add commit summary
   - `pair close` to close the PaiR issue
   - Detects Redmine link via `external_ref` and emits `REDMINE_JSON:` for Claude to draft a summary + resolve the version (it no longer closes Redmine itself, so the note can carry an explanatory summary)
   - Detects GitHub link via `external_ref` (`github-<N>`)
   - Emits `GITHUB_JSON:` with `needs_comment: true` for Claude to handle comment drafting

3. **If the output contains `REDMINE_JSON:`** (always emitted when a Redmine link exists)

   Parse the JSON: `redmine_id`, `redmine_default_version`, `local_version`, `available_versions`, `needs_interaction`, `resolved_version`, `commit_summary`, `commit_messages`.

   **3a. Resolve the target version**
   - If `needs_interaction` is `false`: use `resolved_version` directly  -  **do NOT ask the user** (this is the `skip_version_question=true` auto path).
   - If `needs_interaction` is `true`: build **one** AskUserQuestion:
     - Header: "Version"
     - Question: "Quelle version cible pour Redmine #<redmine_id> ?"
     - Options (up to 4, prioritized in this order, max 4 total):
       1. `{redmine_default_version} (défaut Redmine)` - if available and in `available_versions`
       2. `{local_version}` - if different from redmine_default_version and still in `available_versions` (skip otherwise  -  it's likely obsolete)
       3. Up to 2 additional versions from `available_versions`, picked newest-first (natural sort descending) and excluding any already listed
       4. (User can always type "Other" for a custom version)
     - **Fallback** : if `available_versions` is empty (Redmine API unavailable), use the legacy options  -  `redmine_default_version`, `local_version`, and `Toujours {best_version}`  -  and let the user type a custom label via "Other".
     - **Note**: Only propose versions that are in `available_versions` (open status on Redmine). A locked/obsolete stored default must not be offered blindly.

   **3b. Build the explanatory summary FROM the commit message(s)** (always, no validation step)

   The commit body written at `/pair-review-to-commit` already explains what was done  -  **reuse it, do not re-analyze the issue from scratch**. Derive the `--summary` from `commit_messages` (full subjects + bodies of the commits closing this issue):
   - Take the body of the relevant commit(s), strip the conventional-commit prefix (`type(scope):`), and lightly rework it into a **formal, concise** closure note (FR) that reads as an answer to the bug  -  not as a git log.
   - If the commit body already reads well as-is, keep it nearly verbatim. Only remâcher (reword) where the git phrasing doesn't fit a Redmine reader.
   - Multiple commits → merge their bodies into a coherent note ("On a corrigé A, B et C"). Call out a specific point only if the commit body did.
   - No "commit #N" phrasing. The raw oneline commits are appended automatically as a footer by the script  -  no need to repeat them.

4. **Close Redmine with the resolved version + drafted summary**

   - Option "Toujours..." chosen in 3a → add `--always`
   - Pass `--version "<resolved_or_chosen_version>"` and `--summary "<drafted prose>"`

   ```bash
   python3 ~/.claude/scripts/close-issue.py <issue-id> --close-redmine --version "<version>" --summary "<prose>" [--always] --cli pair
   ```

   > **Champ "Verification"** : la fermeture passe le bug en "To be tested" (5), donc `redmine-api.py` pose automatiquement le champ perso "Verification" sur sa valeur par défaut (`verification_default`, fallback QA) si `verification_field_id` est configuré dans `.redmine.json`. `close-issue.py` n'expose pas d'override : pour forcer `Dev`, utiliser `/update-redmine-bug <redmine-id> verification=Dev` en direct.

5. **If the output contains `GITHUB_JSON:`**

   Parse the JSON to extract `github_number`, `repo`, `commit_summary`.

   **Draft a comment** for the GitHub issue:
   - Read the GitHub issue with `gh issue view <number> --repo <repo>` to understand the original request
   - Draft a meaningful response that addresses the user's request/question
   - Include what was implemented and any relevant usage instructions
   - The comment should be helpful to the issue author, not just a generic "resolved" message

   **Show the draft to the user** for validation via AskUserQuestion:
   - Header: "GitHub"
   - Question: "Envoyer ce commentaire sur GitHub #<number> ?"
   - Options:
     1. `Envoyer tel quel` - "Poster ce commentaire"
     2. `Modifier` - "Ajuster le texte avant envoi"
     3. `Ignorer` - "Ne rien faire sur GitHub"

   If the user chooses `Modifier`, incorporate their feedback and show the updated comment again.

6. **After user approves the comment**

   Post the comment:
   ```bash
   python3 ~/.claude/scripts/close-issue.py <issue-id> --close-github --comment "<approved_comment>" [--repo owner/repo] --cli pair
   ```

   Then ask about closing:
   - Header: "Fermer"
   - Question: "Fermer l'issue GitHub #<number> ?"
   - Options:
     1. `Oui, fermer` - "Fermer l'issue GitHub comme résolue"
     2. `Non, laisser ouverte` - "Garder l'issue ouverte"

   If the user chooses to close:
   ```bash
   python3 ~/.claude/scripts/close-issue.py <issue-id> --close-github --close [--repo owner/repo] --cli pair
   ```

7. **Epic parent auto-close**
   Après fermeture, vérifier si l'issue a un parent epic. Si c'est le cas et que **tous ses children sont fermés**, proposer à l'utilisateur : `/pair-close-issue <parent-id>`. Sinon, laisser le parent en `in_progress`.

8. **Display summary**
   Show confirmation of what was done (PaiR issue closed, Redmine updated if applicable, GitHub commented/closed if applicable, epic parent closed if applicable).

## Special flags

- `--skip-redmine`: Pass to the script to skip Redmine even if the issue is linked
  ```bash
  python3 ~/.claude/scripts/close-issue.py <issue-id> --skip-redmine --cli pair
  ```

- `--skip-github`: Pass to the script to skip GitHub even if the issue is linked
  ```bash
  python3 ~/.claude/scripts/close-issue.py <issue-id> --skip-github --cli pair
  ```

## Example flows

```
/pair-close-issue pair-ab12
```

Flux possibles (selon config et liens détectés) :
- **Auto** (`skip_version_question=true`) : aucune question à l'utilisateur ; Claude drafte le résumé explicatif et fait le 2e appel avec `resolved_version`.
- **Version interactive** : Claude pose 1 question sur la version cible, drafte le résumé, puis 2e appel script.
- **Avec GitHub** : Claude lit l'issue GitHub, draft un comment, demande validation (Envoyer tel quel / Modifier / Ignorer), puis propose de fermer l'issue.
- **Dual Redmine + GitHub** : les deux JSON peuvent apparaître simultanément  -  traiter séquentiellement (Redmine d'abord, GitHub après).
