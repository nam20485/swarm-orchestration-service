---
pair-skill: true
pair-version: 0.47.0
pair-template: 0.47.0 prod
---
# Run PaiR Issue

Launch and work on an issue from the PaiR issue tracker.

> Syntaxe `pair` CLI : voir `.pair/AGENTS.md` **à la racine du projet courant** (chemin relatif, varie par projet).

## Input

$ARGUMENTS - The issue ID to work on (e.g., `pair-1a2b`)  -  OPTIONAL

## Tasks

1. **Get the issue ID**
   - Si `$ARGUMENTS` fourni, l'utiliser.
   - Sinon : lister les issues ouvertes (`pair list -s open`) et laisser l'utilisateur choisir via `AskUserQuestion`.

2. **Fetch issue + set in_progress** (peut tourner en parallèle avec step 3)
   - Récupérer les détails (garder l'ID pour step 10).
   - Passer le statut en `in_progress`.
   - **Epic parent propagation** : si `parent` est un epic en `open`, le passer en `in_progress` aussi.

3. **Check for child issues**
   - Via `pair show --json`, parser les children. S'il y en a, les enchaîner séquentiellement dans step 7.

4. **Analyze**
   - Title, description, labels, priority.
   - Attachments dans `.pair/attachments/{short-id}/` (extensions supportées : voir AGENTS.md).
   - `external-ref` pour liens Redmine/GitHub (pas de file paths  -  les attachments sont filesystem-only).

5. **MANDATORY  -  Read codebase maps before any source exploration**

   Si `.map/` existe à la racine du projet :
   - **Toujours** lire `codebase-map.md`. S'il s'agit d'un index renvoyant vers des sous-cartes (`.map/codebase/`), lire l'index PUIS la seule sous-carte du domaine concerné : charger les autres coûte des milliers de tokens sans rien apporter.
   - `reactivity-map.md` si l'issue touche UI/state/computed/watchers (index puis la sous-carte du domaine, comme ci-dessus).
   - `consumption-map.md` si elle touche performance/polling/memory.
   - `cross-platform-map.md` si comportement OS-spécifique.

   Les maps sont la source de vérité  -  lues une fois, pas re-vérifiées via grep.

6. **Enter Plan Mode  -  discipline d'exploration**
   - **Grep avant Read** : localiser les symboles via `Grep -n`, jamais scanner par Read intégral.
   - **Read borné** : `offset` + `limit` pour les fichiers > 200 lignes.
   - **Pas d'Explore agent** pour < 15 fichiers déjà identifiés (inutile et coûteux).
   - Attacher le plan à l'issue en commentaire (pas dans `.claude/plans/`).
   - Attendre l'approbation user avant d'implémenter.

7. **Execute** (après approbation du plan)
   - Pour chaque child : passer `in_progress` avant, `close` après.
   - Suivre les conventions du CLAUDE.md projet.

8. **Progress comments** (optionnel, pour tâches longues)
   - Ajouter un commentaire `pair` avec le résumé d'avancement.

9. **Verify build** (optionnel  -  demander via `AskUserQuestion`)
   - Si oui : `python3 ~/.claude/scripts/build-project.py`. Fix les erreurs avant de fermer.

10. **Close**
    - `/pair-close-issue <id>`  -  automatique après `/pair-review-to-commit`, ne pas attendre un rappel user.

## Notes

- Toujours passer par `/pair-review-to-commit` pour les commits (jamais `git commit` direct).
- `.pair/` et code → commits séparés.
- Epic parent : si tous les children sont fermés, proposer de fermer l'epic (géré côté `/pair-close-issue`).
