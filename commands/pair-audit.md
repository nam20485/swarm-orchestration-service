---
pair-skill: true
pair-version: 0.47.0
pair-template: 0.47.0 prod
---
# Audit

Audit qualité pré-commit : revue du code modifié, tests, mise à jour de la documentation technique.

## Input

$ARGUMENTS - Optional scope hint (e.g., "terminal only", "skip tests")

## Mode autonome : rôle d'orchestration (pair-1shw.6.25)

**Vérifie d'abord** : `printenv PAIR_ORCH_SCOPE_FILE`. Si la variable est présente, tu es un
**rôle d'orchestration** (le vérificateur `review`) - exécute cet audit en **MODE AUTONOME**, jamais
interactif, et NON en mode standard :

- **Zéro `AskUserQuestion`** : il n'y a pas d'humain dans une session de rôle. Applique des défauts
  sûrs, ne pose aucune question, ne t'arrête pas pour demander.
- **Zéro sous-agent** (`Task`/`Explore`) : le hook d'enforcement les bloque (pair-1shw.6.28). Fais la
  revue **inline** (Grep/Read bornés) même si le diff dépasse 15 fichiers.
- **Zéro écriture** : ton rôle **juge** le code, il ne corrige rien et ne met à jour ni maps ni docs
  (la finalisation - maps/docs/commit - est portée par le rôle `coder`, pas par toi). N'applique
  aucun fix. **Ignore les étapes 4 à 9** (maps/docs/template).
- **Périmètre** : étape 1 (diff) + étape 2 (revue de code) + relance des tests
  (`python3 ~/.claude/scripts/test-project.py`, sans en ajouter/écrire).
- **Sortie** : termine par **une ligne de verdict** - `AUDIT: PASS` si le code est correct, ou
  `AUDIT: FAIL` s'il y a de vraies erreurs de code (bug, régression, comportement faux) - suivie d'un
  résumé court des findings. Le rôle traduit ce verdict en `pair orchestrate verdict <ticket>
  pass|fail` (et poste les findings en commentaire du ticket avant un `fail`).

Sans `PAIR_ORCH_SCOPE_FILE`, ignore cette section : l'audit interactif standard ci-dessous s'applique.

## Règle transverse  -  Vérification des maps

Pour chaque map touchée par un changement, **vérification obligatoire** : grep le nom de chaque nouveau symbole ajouté (fonction, ref, computed, watcher, timer, listener, `#[cfg]`, `dirs::`, commande CLI) dans la map concernée. Si 0 résultat → mise à jour nécessaire. Ne jamais conclure "déjà à jour" sans ce grep.

## Tasks

1. **Identifier ce qui a changé**
   - `git diff --name-only` (staged + unstaged).
   - Ignorer `.pair/` (tracker data, pas du code).
   - Si aucun fichier code changé → informer l'utilisateur et stop.

2. **Revue de code**
   - Si `git diff --stat` montre **> 15 fichiers** : utiliser un Agent (`subagent_type=Explore`) pour la revue.
   - Sinon : revue directe via Grep + Read bornés.
   - Vérifier :
     - **Dead code** : imports inutilisés, branches inatteignables, `console.log`/`dbg!` oubliés, `TODO` sans ticket.
     - **Régressions** : erreurs logiques, null checks manquants, patterns cassés vs le code alentour.
     - **Consistance** : nommage, style conforme au reste du codebase.
     - **Sécurité** : injection, secrets hardcodés, opérations unsafe.
     - **Cross-platform** : si un fichier changé contient un pattern OS-spécifique (`env::var("HOME")`, paths `/` hardcodés, `std::os::unix` sans `#[cfg]`), grep le même pattern dans tout le codebase  -  le problème est probablement ailleurs aussi. Anti-patterns courants :
       - `env::var("HOME")` sans fallback Windows (`USERPROFILE`, `dirs::home_dir()`)
       - Paths Unix hardcodés (`/usr/local/bin`, `~/.local/`)
       - `std::os::unix` sans guard `#[cfg]`
       - Séparateur `/` au lieu de `Path::join()`
   - Présenter les findings avec chemins + lignes. Fix si l'utilisateur est OK, sinon noter pour plus tard.

3. **Tests**
   - Si les fichiers modifiés ont des tests correspondants (ex: `app/utils/foo.ts` → `tests/utils/foo.test.ts`) : vérifier que la couverture tient, sinon proposer des additions.
   - Si pas de tests et que le code = logique pure testable (utils, helpers, composables) : proposer d'en créer.
   - **Ne PAS** proposer de tests pour : rendu Vue template, code Tauri natif, glue code trivial.
   - Run après ajouts : `python3 ~/.claude/scripts/test-project.py`.

4. **Codebase map  -  `.map/codebase-map.md`**  -  index « où est quoi », PAS une doc.
   - **Contrat** : chaque entrée = **chemin + rôle en une ligne**. Seule fonction : signaler qu'un sous-système existe et par quel fichier l'attaquer. Le « comment/pourquoi » se lit dans le code une fois qu'on sait où.
   - **N'a PAS sa place ici** (retirer si présent, ne jamais ajouter) : historique de tickets, pivots/rationale de design, algorithmie des sous-modules, flux réactifs détaillés. → PaiR (journal/comments) pour historique+décisions ; maps de domaine (reactivity/consumption) pour les flux ; le code pour l'algorithmie.
   - Sur update : mettre à jour les sections affectées (nouveaux modules/symboles exportés, renames, suppressions) **sans gonfler les cellules**. Une cellule qui porte du « pourquoi » = drift à trimmer, pas à préserver.
   - **Structure éclatée** : si la map est déjà découpée (index + sous-fichiers par catégorie/concept), router l'update dans le bon sous-fichier et respecter le découpage  -  ne pas re-monolithiser.
   - Si n'existe pas : proposer sa création.

5. **Reactivity map  -  `.map/reactivity-map.md`**
   - Si existe : mettre à jour refs/computed/watchers/flows reactive affectés.
   - Si n'existe pas : proposer sa création.
   - Ne réécrire que les sections affectées.

6. **Consumption map  -  `.map/consumption-map.md`**
   - Si existe : mettre à jour polling/timers/deep watchers/listeners affectés.
   - Si n'existe pas : skip (optionnelle, ne pas proposer sa création).

7. **Cross-platform map  -  `.map/cross-platform-map.md`**
   - Si existe et les changements touchent Rust (`src-tauri/src/`) : mettre à jour `#[cfg]`, `dirs::`, stubs plateforme, coverage matrix.
   - Si n'existe pas : skip.

8. **In-app docs  -  `src-tauri/src/pair/docs/`** (PaiR uniquement)
   - Skip si le projet n'a pas `src-tauri/src/pair/docs/`.
   - Si du comportement user-facing a changé (UI, terminal, settings, shortcuts, workflow) : grep les doc files, mettre à jour EN + FR en sync.

9. **Agents template  -  `src-tauri/src/pair/agents_template.md`** (PaiR uniquement)
   - Skip si absent.
   - Si le code CLI Rust a changé (`src-tauri/src/bin/pair.rs`, `src-tauri/src/pair/*.rs`, `src-tauri/src/commands/*.rs`) : comparer `pair --help` (et subcommand `--help`) contre le template, aligner flags/subcommands/enum values.
   - Critique : ce template est déployé à chaque client project  -  drift = doc périmée partout.

10. **Summary**
    - Récap : code fixes, tests ajoutés (avec count), maps updated (quelles sections), in-app docs (quelles pages EN/FR), agents template (si PaiR).
    - Si rien à updater : le dire, ne pas inventer de travail.

## Notes

- Lancer **avant** `/pair-review-to-commit`  -  c'est le quality gate, pas le commit step.
- Ne pas committer, ne pas lancer le dev server.
- Focus sur ce qui a changé  -  ne pas auditer tout le codebase.
- `$ARGUMENTS` optionnel pour limiter le scope.
