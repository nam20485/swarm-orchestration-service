---
pair-skill: true
pair-version: 0.47.0
pair-template: 0.47.0 prod
---
# Create Issue

Create a new issue in the project issue tracker using the `pair` CLI.

> Syntaxe `pair create` / `pair attach` : voir `.pair/AGENTS.md` **à la racine du projet courant** (source de vérité, auto-synchronisée avec le binaire  -  chemin relatif, varie par projet).

## Input

$ARGUMENTS - The issue description/detail

## Tasks

1. **Parse input**
   - Utiliser `$ARGUMENTS` comme description.
   - Si aucun argument : demander la description à l'utilisateur.

2. **Determine issue type**

   **Règle d'or** : si l'utilisateur nomme explicitement un type (ex: "cree une spec", "c'est un bug"), l'utiliser directement sans re-analyser. Sinon, détecter via mots-clés :

   | Type | Keywords (EN) | Keywords (FR) |
   |------|---------------|---------------|
   | spec | spec, specification, document, guide, write up | spec, specification, document, guide, rediger |
   | epic | epic, multiple pages, separate issues, umbrella | epique, plusieurs pages, issues separees, regrouper |
   | bug | fix, bug, broken, error, issue, crash, doesn't work | fix, bug, erreur, probleme, ne fonctionne pas, casse |
   | feature | add, implement, create, feature, improve, new | ajouter, implementer, creer, fonctionnalite, ameliorer, nouveau |
   | campaign | campaign, test plan, validation, rollout | campagne, plan de test, validation, deploiement |
   | task | refactor, update, change, move, rename | refactorer, mettre a jour, changer, deplacer, renommer |

   Si le CLI rejette un type (selon la version), fallback sur `task` et informer l'utilisateur.

3. **Confirm with user before creating**
   Présenter un résumé (type détecté, titre proposé, liste des children si epic). En cas de doute (single feature vs epic avec children), poser la question plutôt que deviner. Ne procéder qu'après confirmation explicite.

4. **Epic avec children**
   Si la description implique plusieurs work items distincts :
   - **Toujours** créer le parent en `-t epic` d'abord.
   - Créer chaque child avec `--parent <epic-id>` (type child : feature/bug/task).
   - **Jamais l'inverse** : ne pas créer les children puis reparent.

5. **Create & attach**
   - Single non-epic : `pair create -t <type>` avec description + titre (5-10 mots).
   - Attachments (images, markdown) : `pair attach`  -  sanitization, dedup, push notification gérés par le CLI.
   - **Ne pas modifier `external-ref`**  -  réservé aux refs externes réelles (Redmine IDs, GitHub URLs).

6. **Show summary**
   - Issue ID(s), type, relations parent/child, attachments.

## Examples

```
# Spec
/pair-create-issue Redige une spec securite sur la gestion des credentials
→ spec "Spec securite  -  gestion des credentials"

# Bug
/pair-create-issue Fix the login form validation not showing error messages
→ bug "Fix login form validation errors"

# Feature
/pair-create-issue Add dark mode toggle to settings page
→ feature "Add dark mode toggle to settings"

# Epic + 3 children
/pair-create-issue Integrer le listener EdgeBot dans scan, monitoring et services. Creer une epic avec 3 issues separees.
→ epic "EPIC: ..." + 3 feature children via --parent

# Bug + image attachment
/pair-create-issue Le bouton ne fonctionne pas [+ image jointe]
→ bug + pair attach <id> screenshot.png

# Feature + markdown attachment
/pair-create-issue Implementer les specs du document [+ fichier .md joint]
→ feature + pair attach <id> specs.md
```
