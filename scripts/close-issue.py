#!/usr/bin/env python3
# pair-template: 0.47.0 prod
"""
Close a PaiR issue with commit summary and optional Redmine/GitHub integration.

Global script: lives in ~/.claude/scripts/ and works with any PaiR project.
Redmine integration is activated per-project via .claude/config/redmine-projects.md.
GitHub integration is auto-detected via external_ref containing 'github-<N>'.

Usage:
    # Mode auto (1 seul appel si skip_version_question=true)
    python3 ~/.claude/scripts/close-issue.py pair-ab12 --auto

    # Mode standard (retourne JSON si interaction requise)
    python3 ~/.claude/scripts/close-issue.py pair-ab12

    # Fermer Redmine apres interaction
    python3 ~/.claude/scripts/close-issue.py pair-ab12 --close-redmine --version "1.2.0"

    # Fermer Redmine + activer skip_version_question
    python3 ~/.claude/scripts/close-issue.py pair-ab12 --close-redmine --version "1.2.0" --always

    # Ignorer Redmine meme si lie
    python3 ~/.claude/scripts/close-issue.py pair-ab12 --skip-redmine

    # Commenter/fermer l'issue GitHub liee
    python3 ~/.claude/scripts/close-issue.py pair-ab12 --close-github --comment "Fixed"

    # Commenter + fermer l'issue GitHub
    python3 ~/.claude/scripts/close-issue.py pair-ab12 --close-github --comment "Fixed" --close

    # Ignorer GitHub meme si lie
    python3 ~/.claude/scripts/close-issue.py pair-ab12 --skip-github
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Import redmine_api module from ~/.claude/scripts/ (conditional - may not exist)
_global_scripts_dir = Path.home() / ".claude" / "scripts"

try:
    redmine_api_path = _global_scripts_dir / "redmine-api.py"
    spec = importlib.util.spec_from_file_location("redmine_api", redmine_api_path)
    redmine_api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(redmine_api)
except (FileNotFoundError, Exception):
    redmine_api = None


# Config file path (relative to project root)
CONFIG_PATH = ".claude/config/redmine-projects.md"


def run_cmd(cmd: list[str], capture: bool = True) -> tuple[int, str]:
    """Run a command and return (returncode, stdout)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            timeout=30,
        )
        return result.returncode, result.stdout.strip()
    except subprocess.TimeoutExpired:
        return 1, "Command timed out"
    except FileNotFoundError:
        return 1, f"Command not found: {cmd[0]}"


def get_project_root() -> Path:
    """Find the project root (where .pair/ exists)."""
    cwd = Path.cwd()
    # Check cwd and parents
    for p in [cwd] + list(cwd.parents):
        if (p / ".pair").is_dir():
            return p
    return cwd


def get_commits() -> str:
    """Get recent commit subjects (oneline)  -  used for the PaiR comment + footer."""
    rc, output = run_cmd(["git", "log", "--oneline", "-10"])
    return output


def get_commit_messages() -> str:
    """Get recent commit messages WITH bodies  -  the material Claude reworks into
    the Redmine summary (the explanatory text already written at /pair-review-to-commit).
    """
    rc, output = run_cmd(
        ["git", "log", "-10", "--pretty=format:--- %h %s%n%b"]
    )
    return output


def add_commit_comment(issue_id: str, commits: str, cli: str = "pair") -> bool:
    """Add commit summary as a comment to the PaiR issue."""
    comment = f"## Commits\n\n{commits}"
    rc, output = run_cmd([cli, "comments", "add", issue_id, comment])
    if rc != 0:
        print(f"  Comment added with commit summary", file=sys.stderr)
        return False
    print(f"  Comment added with commit summary")
    return True


def close_pair_issue(issue_id: str, cli: str = "pair") -> bool:
    """Close the PaiR issue (removes 'reopened' label if present)."""
    # Remove 'reopened' label before closing (silently ignore if not present)
    run_cmd([cli, "update", issue_id, "--remove-label", "reopened"])
    rc, output = run_cmd([cli, "close", issue_id])
    if rc != 0:
        print(f"  Failed to close issue: {output}", file=sys.stderr)
        return False
    print(f"  Issue {issue_id} closed")
    return True


def get_external_ref(issue_id: str, cli: str = "br") -> str | None:
    """Get external_ref from PaiR issue."""
    rc, output = run_cmd([cli, "show", issue_id, "--json"])
    if rc != 0:
        return None
    try:
        data = json.loads(output)
        if isinstance(data, list) and len(data) > 0:
            return data[0].get("external_ref")
        elif isinstance(data, dict):
            return data.get("external_ref")
    except json.JSONDecodeError:
        pass
    return None


def get_last_comment(issue_id: str, cli: str = "br") -> str:
    """Get the last comment from a PaiR issue (commit summary)."""
    rc, output = run_cmd([cli, "comments", issue_id, "--json"])
    if rc != 0:
        return ""
    try:
        comments = json.loads(output)
        if comments and len(comments) > 0:
            return comments[-1].get("text", "")
    except json.JSONDecodeError:
        pass
    return ""


def parse_redmine_id(external_ref: str) -> int | None:
    """Extract Redmine ID from external_ref (multi-line: checks each line)."""
    if not external_ref:
        return None
    for line in external_ref.split("\n"):
        line = line.strip()
        match = re.match(r"redmine-(\d+)", line)
        if match:
            return int(match.group(1))
    return None


def parse_github_id(external_ref: str) -> int | None:
    """Extract GitHub issue number from external_ref like 'github-42' (multi-line)."""
    if not external_ref:
        return None
    for line in external_ref.split("\n"):
        line = line.strip()
        match = re.match(r"github-(\d+)", line)
        if match:
            return int(match.group(1))
    return None


def config_repo(project_root: Path) -> str | None:
    """Read sync-repo from .pair/config.yaml if present.

    Users file public issues on a dedicated dist repo, not the current (often
    private) source repo, so a project can pin its sync target explicitly.
    Mirrors config_repo() in sync-github-to-pair.py.
    """
    path = project_root / ".pair" / "config.yaml"
    if not path.is_file():
        return None
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("sync-repo:"):
                value = stripped.split(":", 1)[1].strip()
                return value or None
    except OSError:
        return None
    return None


def detect_github_repo() -> str | None:
    """Auto-detect GitHub repo via gh CLI."""
    rc, output = run_cmd(["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"])
    if rc != 0 or not output:
        return None
    return output.strip()


def comment_github_issue(number: int, comment: str, repo: str | None = None) -> bool:
    """Add a comment to a GitHub issue."""
    cmd = ["gh", "issue", "comment", str(number), "--body", comment]
    if repo:
        cmd.extend(["--repo", repo])
    rc, output = run_cmd(cmd)
    if rc != 0:
        print(f"  Failed to comment on GitHub #{number}: {output}", file=sys.stderr)
        return False
    print(f"  Commented on GitHub #{number}")
    return True


def close_github_issue(number: int, repo: str | None = None) -> bool:
    """Close a GitHub issue."""
    cmd = ["gh", "issue", "close", str(number), "--reason", "completed"]
    if repo:
        cmd.extend(["--repo", repo])
    rc, output = run_cmd(cmd)
    if rc != 0:
        print(f"  Failed to close GitHub #{number}: {output}", file=sys.stderr)
        return False
    print(f"  GitHub #{number} closed")
    return True


def read_config(project_root: Path) -> dict:
    """Read redmine-projects.md config file.

    Parses: Version cible par defaut, skip_version_question, Redmine URL, Projet Redmine.
    """
    config_file = project_root / CONFIG_PATH
    if not config_file.exists():
        return {}

    content = config_file.read_text()
    config = {}

    # Parse Redmine URL
    match = re.search(r"\|\s*Redmine URL\s*\|\s*(.+?)\s*\|", content)
    if match:
        config["redmine_url"] = match.group(1).strip()

    # Parse Projet Redmine
    match = re.search(r"\|\s*Projet Redmine\s*\|\s*(.+?)\s*\|", content)
    if match:
        config["redmine_project"] = match.group(1).strip()

    # Parse Version cible par defaut
    match = re.search(r"\|\s*Version cible par défaut\s*\|\s*(.+?)\s*\|", content)
    if match:
        config["local_version"] = match.group(1).strip()

    # Parse skip_version_question
    match = re.search(r"\|\s*skip_version_question\s*\|\s*(.+?)\s*\|", content)
    if match:
        config["skip_version_question"] = match.group(1).strip().lower() == "true"
    else:
        config["skip_version_question"] = False

    return config


def update_config_version(project_root: Path, new_version: str) -> None:
    """Update the default version in config file."""
    config_file = project_root / CONFIG_PATH
    if not config_file.exists():
        return

    content = config_file.read_text()
    new_content = re.sub(
        r"(\|\s*Version cible par défaut\s*\|\s*).+?(\s*\|)",
        rf"\g<1>{new_version}\g<2>",
        content,
    )
    config_file.write_text(new_content)


def update_config_skip(project_root: Path, skip: bool) -> None:
    """Update skip_version_question in config file."""
    config_file = project_root / CONFIG_PATH
    if not config_file.exists():
        return

    content = config_file.read_text()
    value = "true" if skip else "false"
    new_content = re.sub(
        r"(\|\s*skip_version_question\s*\|\s*).+?(\s*\|)",
        rf"\g<1>{value}\g<2>",
        content,
    )
    config_file.write_text(new_content)


def close_redmine_bug(
    redmine_id: int,
    version_label: str,
    issue_id: str,
    summary: str | None = None,
    commits_block: str | None = None,
) -> bool:
    """Close a Redmine bug with version and an explanatory note.

    Note layout: header line, then the prose summary describing what was fixed
    (drafted by Claude, passed via --summary), then the raw commit block as a
    footer for traceability. Falls back to commits-only if no summary is given.
    """
    parts = [f"Corrige et a tester - PaiR issue {issue_id}"]
    if summary and summary.strip():
        parts.append(summary.strip())
    if commits_block and commits_block.strip():
        parts.append(f"---\n\n{commits_block.strip()}")
    note = "\n\n".join(parts)
    success = redmine_api.close_bug(redmine_id, note=note, version_label=version_label)
    return success


def main():
    parser = argparse.ArgumentParser(
        description="Close a PaiR issue with commit summary and optional Redmine integration"
    )
    parser.add_argument("issue_id", help="PaiR issue ID (e.g., pair-ab12)")
    parser.add_argument(
        "--cli",
        default="pair",
        help="PaiR CLI binary name",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Auto mode: use config if skip_version_question=true",
    )
    parser.add_argument(
        "--close-redmine",
        action="store_true",
        help="Close the linked Redmine bug",
    )
    parser.add_argument("--version", help="Target version label for Redmine")
    parser.add_argument(
        "--summary",
        help="Explanatory prose summary (drafted by Claude) for the Redmine note",
    )
    parser.add_argument(
        "--always",
        action="store_true",
        help="Enable skip_version_question in config",
    )
    parser.add_argument(
        "--skip-redmine",
        action="store_true",
        help="Skip Redmine even if linked",
    )
    # GitHub arguments
    parser.add_argument(
        "--close-github",
        action="store_true",
        help="Comment/close the linked GitHub issue",
    )
    parser.add_argument(
        "--comment",
        help="Comment text for GitHub issue",
    )
    parser.add_argument(
        "--close",
        action="store_true",
        help="Also close the GitHub issue (with --close-github)",
    )
    parser.add_argument(
        "--skip-github",
        action="store_true",
        help="Skip GitHub even if linked",
    )
    parser.add_argument(
        "--repo",
        help="GitHub repo override (owner/repo)",
    )

    args = parser.parse_args()
    issue_id = args.issue_id
    project_root = get_project_root()

    # Read config and configure Redmine if available
    config = read_config(project_root)
    redmine_url = config.get("redmine_url")
    redmine_project = config.get("redmine_project")

    if redmine_api and redmine_url and redmine_project:
        redmine_api.configure(redmine_url, redmine_project)
        has_redmine = True
    else:
        has_redmine = False

    # --- Phase 2: Close Redmine only (second call after user interaction) ---
    if args.close_redmine:
        if not has_redmine:
            print("  No Redmine configuration found in .claude/config/redmine-projects.md", file=sys.stderr)
            sys.exit(1)

        if not args.version:
            print("  --version is required with --close-redmine", file=sys.stderr)
            sys.exit(1)

        # Commit block (kept as a footer for traceability)
        commits_block = get_last_comment(issue_id, cli=args.cli)

        # Get Redmine ID
        external_ref = get_external_ref(issue_id, cli=args.cli)
        redmine_id = parse_redmine_id(external_ref)
        if not redmine_id:
            print("  No Redmine link found on this issue", file=sys.stderr)
            sys.exit(1)

        # Close Redmine with the drafted prose summary + commit footer
        success = close_redmine_bug(
            redmine_id, args.version, issue_id,
            summary=args.summary, commits_block=commits_block,
        )

        # If the target version was locked, redmine_api recovers the next open one
        recovered = None
        try:
            used = redmine_api.get_last_used_version()
            if used and used.get("recovered"):
                recovered = used["name"]
        except Exception:
            pass

        # Update config version if needed
        effective_version = recovered or args.version
        if config.get("local_version") != effective_version:
            update_config_version(project_root, effective_version)
            if recovered:
                print(f"  Config updated: version = {recovered} (auto-recovered from locked '{args.version}')")
            else:
                print(f"  Config updated: version = {effective_version}")

        # Update skip flag if --always
        if args.always:
            update_config_skip(project_root, True)
            print(f"  Config updated: skip_version_question = true")

        sys.exit(0 if success else 1)

    # --- Phase 2b: Close/comment GitHub only (second call after user interaction) ---
    if args.close_github:
        external_ref = get_external_ref(issue_id, cli=args.cli)
        github_number = parse_github_id(external_ref)
        if not github_number:
            print("  No GitHub link found on this issue", file=sys.stderr)
            sys.exit(1)

        repo = args.repo or config_repo(project_root) or detect_github_repo()
        if not repo:
            print("  Failed to detect GitHub repo. Use --repo owner/repo.", file=sys.stderr)
            sys.exit(1)

        success = True
        if args.comment:
            success = comment_github_issue(github_number, args.comment, repo)
        if args.close:
            success = close_github_issue(github_number, repo) and success

        sys.exit(0 if success else 1)

    # --- Phase 1: Close PaiR issue + detect Redmine + detect GitHub ---

    # Step 1: Get recent commits
    commits = get_commits()
    if not commits:
        print("  No commits found", file=sys.stderr)
        sys.exit(1)

    # Step 2: Add comment
    add_commit_comment(issue_id, commits, cli=args.cli)

    # Step 3: Close PaiR issue
    close_pair_issue(issue_id, cli=args.cli)

    # Step 4: Get external_ref for both Redmine and GitHub detection
    external_ref = get_external_ref(issue_id, cli=args.cli)

    # Step 5: Check for Redmine link
    if not args.skip_redmine and has_redmine:
        redmine_id = parse_redmine_id(external_ref)

        if redmine_id:
            # Get Redmine default version
            redmine_default_version = None
            try:
                dv = redmine_api.get_default_version()
                if dv:
                    redmine_default_version = dv.get("name")
            except Exception:
                pass

            # Read local config
            local_version = config.get("local_version", "")
            skip_version_question = config.get("skip_version_question", False)

            # Never auto-close here: the Redmine note must carry an explanatory
            # prose summary that only Claude can draft, so closing always happens
            # in the --close-redmine (Phase 2) call. When skip_version_question is
            # on, the version is pre-resolved and Claude skips the version question.
            skip_question = bool(args.auto and skip_version_question and local_version)
            resolved_version = local_version if skip_question else None

            open_versions = []
            try:
                open_versions = [v.get("name") for v in redmine_api.get_versions(only_open=True) if v.get("name")]
            except Exception:
                pass

            # Output JSON for Claude to draft a summary + handle the version
            interaction_data = {
                "redmine_id": redmine_id,
                "redmine_default_version": redmine_default_version,
                "local_version": local_version,
                "skip_version_question": skip_version_question,
                "needs_interaction": not skip_question,
                "resolved_version": resolved_version,
                "available_versions": open_versions,
                "needs_summary": True,
                "commit_summary": get_last_comment(issue_id, cli=args.cli),
                "commit_messages": get_commit_messages(),
            }
            print(f"\n  Redmine #{redmine_id} linked")
            print(f"REDMINE_JSON:{json.dumps(interaction_data)}")

    # Step 6: Check for GitHub link
    if not args.skip_github:
        github_number = parse_github_id(external_ref)

        if github_number:
            repo = args.repo or config_repo(project_root) or detect_github_repo()
            print(f"\n  GitHub #{github_number} linked")

            # Always emit JSON for Claude to handle comment drafting + validation
            # Never auto-comment  -  the user must review and approve the comment first
            commit_summary = get_last_comment(issue_id, cli=args.cli)
            github_data = {
                "github_number": github_number,
                "repo": repo,
                "needs_comment": True,
                "needs_close_decision": True,
                "commit_summary": commit_summary,
            }
            print(f"GITHUB_JSON:{json.dumps(github_data)}")


if __name__ == "__main__":
    main()
