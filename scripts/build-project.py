#!/usr/bin/env python3
# pair-template: 0.47.0 prod
"""
Build project  -  universal build script for Claude Code sessions.

Auto-detects project type and runs the appropriate build steps.
Captures output and returns a compact summary to minimize token usage.

Supported project types:
- Nuxt/Vue (pnpm generate)
- Rust/Tauri (cargo build)
- Combined Nuxt + Tauri

Usage:
    python3 ~/.claude/scripts/build-project.py              # Auto-detect & build all (debug)
    python3 ~/.claude/scripts/build-project.py --dev         # Launch app in dev mode (tauri dev)
    python3 ~/.claude/scripts/build-project.py --prod        # Production build (DMG/installer)
    python3 ~/.claude/scripts/build-project.py --frontend    # Frontend only
    python3 ~/.claude/scripts/build-project.py --backend     # Backend (Rust) only
    python3 ~/.claude/scripts/build-project.py --release     # Release build
    python3 ~/.claude/scripts/build-project.py --check       # Type-check only, no build
    python3 ~/.claude/scripts/build-project.py -C /path      # Specify project dir
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure cargo/rustup are in PATH (not always inherited in subprocess)
# ---------------------------------------------------------------------------
_cargo_bin = Path.home() / ".cargo" / "bin"
if _cargo_bin.is_dir() and str(_cargo_bin) not in os.environ.get("PATH", ""):
    os.environ["PATH"] = f"{_cargo_bin}:{os.environ.get('PATH', '')}"

# ---------------------------------------------------------------------------
# ANSI colors
# ---------------------------------------------------------------------------
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


# ---------------------------------------------------------------------------
# Project detection
# ---------------------------------------------------------------------------

def detect_project(project_dir: Path) -> dict:
    """Detect project type and available build targets."""
    info = {
        "dir": str(project_dir),
        "has_nuxt": (project_dir / "nuxt.config.ts").exists() or (project_dir / "nuxt.config.js").exists(),
        "has_tauri": (project_dir / "src-tauri" / "Cargo.toml").exists(),
        "has_cargo": (project_dir / "Cargo.toml").exists(),
        "has_package_json": (project_dir / "package.json").exists(),
        "has_node_modules": (project_dir / "node_modules").exists(),
        "pkg_manager": "pnpm",  # default
    }

    # Detect package manager
    if (project_dir / "pnpm-lock.yaml").exists():
        info["pkg_manager"] = "pnpm"
    elif (project_dir / "yarn.lock").exists():
        info["pkg_manager"] = "yarn"
    elif (project_dir / "bun.lockb").exists():
        info["pkg_manager"] = "bun"
    elif (project_dir / "package-lock.json").exists():
        info["pkg_manager"] = "npm"

    # Determine project type
    if info["has_nuxt"] and info["has_tauri"]:
        info["type"] = "nuxt-tauri"
    elif info["has_nuxt"]:
        info["type"] = "nuxt"
    elif info["has_tauri"]:
        info["type"] = "tauri"
    elif info["has_cargo"]:
        info["type"] = "rust"
    elif info["has_package_json"]:
        info["type"] = "node"
    else:
        info["type"] = "unknown"

    return info


# ---------------------------------------------------------------------------
# Build steps
# ---------------------------------------------------------------------------

def run_step(label: str, cmd: list[str], cwd: str, timeout: int = 600) -> dict:
    """Run a build step, capture output, return summary."""
    print(f"{CYAN}{BOLD}▸ {label}{RESET}", flush=True)
    start = time.time()

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
        )
        elapsed = time.time() - start
        success = result.returncode == 0

        # Extract only error/warning lines for compact output
        stderr_lines = result.stderr.strip().split("\n") if result.stderr.strip() else []
        stdout_lines = result.stdout.strip().split("\n") if result.stdout.strip() else []

        errors = [l for l in stderr_lines if "error" in l.lower() and "warning" not in l.lower()]
        warnings = [l for l in stderr_lines + stdout_lines if "warning" in l.lower() or "warn" in l.lower()]

        if success:
            print(f"  {GREEN}✓ OK{RESET} {DIM}({elapsed:.1f}s){RESET}")
        else:
            print(f"  {RED}✗ FAILED{RESET} {DIM}({elapsed:.1f}s){RESET}")
            # Show last 20 lines of output for debugging
            all_output = (result.stdout + "\n" + result.stderr).strip().split("\n")
            tail = all_output[-20:]
            for line in tail:
                print(f"  {DIM}{line}{RESET}")

        return {
            "step": label,
            "success": success,
            "elapsed_s": round(elapsed, 1),
            "exit_code": result.returncode,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "errors": errors[:10],  # Cap at 10
            "warnings": warnings[:5],  # Cap at 5
        }

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start
        print(f"  {RED}✗ TIMEOUT{RESET} {DIM}(>{timeout}s){RESET}")
        return {
            "step": label,
            "success": False,
            "elapsed_s": round(elapsed, 1),
            "exit_code": -1,
            "error_count": 1,
            "warning_count": 0,
            "errors": [f"Timeout after {timeout}s"],
            "warnings": [],
        }
    except FileNotFoundError as e:
        print(f"  {RED}✗ NOT FOUND{RESET}: {e}")
        return {
            "step": label,
            "success": False,
            "elapsed_s": 0,
            "exit_code": -1,
            "error_count": 1,
            "warning_count": 0,
            "errors": [str(e)],
            "warnings": [],
        }


def install_deps(project: dict) -> dict | None:
    """Install dependencies if node_modules is missing."""
    if not project["has_package_json"]:
        return None
    if project["has_node_modules"]:
        return None

    pkg = project["pkg_manager"]
    return run_step(
        f"Install dependencies ({pkg})",
        [pkg, "install"],
        project["dir"],
    )


def build_frontend(project: dict, check_only: bool = False) -> dict | None:
    """Build frontend (Nuxt generate or type-check)."""
    if not project["has_nuxt"]:
        return None

    pkg = project["pkg_manager"]
    if check_only:
        return run_step(
            "Type-check (vue-tsc)",
            ["npx", "vue-tsc", "--noEmit"],
            project["dir"],
        )

    return run_step(
        "Build frontend (nuxt generate)",
        [pkg, "generate"],
        project["dir"],
        timeout=300,
    )


def build_backend(project: dict, release: bool = False) -> dict | None:
    """Build Rust/Tauri backend."""
    if project["has_tauri"]:
        cwd = str(Path(project["dir"]) / "src-tauri")
        cargo_toml = Path(cwd) / "Cargo.toml"
    elif project["has_cargo"]:
        cwd = project["dir"]
        cargo_toml = Path(cwd) / "Cargo.toml"
    else:
        return None

    if not cargo_toml.exists():
        return None

    cmd = ["cargo", "build"]
    if release:
        cmd.append("--release")

    label = f"Build backend (cargo {'release' if release else 'debug'})"
    return run_step(label, cmd, cwd, timeout=600)


def run_dev(project: dict) -> None:
    """Launch the app in dev mode (interactive, blocks until stopped)."""
    if not project["has_package_json"]:
        print(f"{RED}✗ No package.json found  -  cannot run dev mode{RESET}")
        sys.exit(1)

    # Install deps first if needed
    if not project["has_node_modules"]:
        r = install_deps(project)
        if r and not r["success"]:
            sys.exit(1)

    pkg = project["pkg_manager"]

    # Rebuild the CLI sidecar before launching dev, so /usr/local/bin/pair
    # (symlinked to target/debug/pair) stays in sync with the Rust sources.
    # tauri dev only rebuilds the main app binary, not auxiliary bins.
    if project["has_tauri"]:
        print(f"\n{BOLD}Rebuilding debug CLI (keep symlink in sync){RESET}")
        print(f"{'─' * 50}")
        r = run_step(
            "Rebuild debug binary (cargo build --bin pair)",
            ["cargo", "build", "--bin", "pair"],
            str(Path(project["dir"]) / "src-tauri"),
            timeout=600,
        )
        if not r["success"]:
            print(f"{RED}✗ CLI rebuild failed  -  aborting dev launch{RESET}")
            sys.exit(1)
        debug_bin = Path(project["dir"]) / "src-tauri" / "target" / "debug" / "pair"
        if debug_bin.exists():
            debug_bin.chmod(debug_bin.stat().st_mode | 0o111)
            print(f"  {GREEN}✓ chmod +x{RESET} {DIM}{debug_bin}{RESET}")

    if project["has_tauri"]:
        cmd = [pkg, "tauri", "dev"]
        label = "Launching Tauri dev mode"
    elif project["has_nuxt"]:
        cmd = [pkg, "dev"]
        label = "Launching Nuxt dev mode"
    else:
        cmd = [pkg, "dev"]
        label = "Launching dev mode"

    print(f"\n{CYAN}{BOLD}▸ {label}{RESET}")
    print(f"  {DIM}Command: {' '.join(cmd)}{RESET}")
    print(f"  {DIM}Press Ctrl+C to stop{RESET}\n")

    # Run interactively  -  pass through stdio
    try:
        proc = subprocess.run(cmd, cwd=project["dir"])
        sys.exit(proc.returncode)
    except KeyboardInterrupt:
        print(f"\n{YELLOW}▸ Dev server stopped{RESET}")
        sys.exit(0)


def check_linux_vm_available() -> bool:
    """Check if the OrbStack pair-builder VM is running and available."""
    try:
        result = subprocess.run(
            ["orb", "list"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return False
        return "pair-builder" in result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def ask_linux_build() -> bool:
    """Ask the user if they want to also build the Linux .deb package."""
    print(f"\n{CYAN}{BOLD}?{RESET} {BOLD}Also build Linux .deb package via OrbStack?{RESET} (y/N) ", end="", flush=True)
    try:
        answer = input().strip().lower()
        return answer in ("y", "yes", "o", "oui")
    except (EOFError, KeyboardInterrupt):
        return False


def build_linux_deb(project: dict) -> dict:
    """Build Linux .deb via OrbStack pair-builder VM."""
    script_path = Path(project["dir"]) / "scripts" / "build-linux.sh"
    if not script_path.exists():
        return {
            "step": "Linux .deb (OrbStack)",
            "success": False,
            "elapsed_s": 0,
            "exit_code": -1,
            "error_count": 1,
            "warning_count": 0,
            "errors": [f"Script not found: {script_path}"],
            "warnings": [],
        }

    return run_step(
        "Linux .deb (OrbStack pair-builder)",
        ["bash", str(script_path)],
        project["dir"],
        timeout=900,
    )


def build_prod(project: dict) -> list[dict]:
    """Production build (creates DMG/installer for Tauri apps)."""
    results = []

    # Install deps first if needed
    if not project["has_node_modules"]:
        r = install_deps(project)
        if r:
            results.append(r)
            if not r["success"]:
                return results

    pkg = project["pkg_manager"]

    if project["has_tauri"]:
        # macOS DMG
        r = run_step(
            "Production build (tauri build  -  DMG only)",
            [pkg, "tauri", "build", "--bundles", "dmg"],
            project["dir"],
            timeout=900,
        )
        results.append(r)

        # Propose Linux .deb build if OrbStack VM is available
        if r["success"] and check_linux_vm_available():
            if ask_linux_build():
                r_linux = build_linux_deb(project)
                results.append(r_linux)
            else:
                print(f"  {DIM}Skipping Linux build.{RESET}")
        elif r["success"]:
            print(f"  {DIM}Linux build skipped (OrbStack pair-builder VM not found).{RESET}")
    else:
        # Frontend-only prod build
        if project["has_nuxt"]:
            r = build_frontend(project)
            if r:
                results.append(r)

    return results


def run_tests(project: dict) -> dict | None:
    """Run project tests."""
    if not project["has_package_json"]:
        return None

    pkg = project["pkg_manager"]
    return run_step(
        "Run tests",
        [pkg, "test"],
        project["dir"],
        timeout=120,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Build project for Claude Code")
    parser.add_argument("-C", "--project-dir", default=os.getcwd(),
                        help="Project directory (default: cwd)")
    parser.add_argument("--dev", action="store_true",
                        help="Launch app in dev mode (interactive)")
    parser.add_argument("--prod", action="store_true",
                        help="Production build (DMG/installer)")
    parser.add_argument("--frontend", action="store_true",
                        help="Build frontend only")
    parser.add_argument("--backend", action="store_true",
                        help="Build backend only")
    parser.add_argument("--release", action="store_true",
                        help="Release build (optimized)")
    parser.add_argument("--check", action="store_true",
                        help="Type-check only, no build")
    parser.add_argument("--test", action="store_true",
                        help="Run tests after build")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON only")
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()
    project = detect_project(project_dir)

    if project["type"] == "unknown":
        print(f"{RED}✗ Could not detect project type in {project_dir}{RESET}")
        sys.exit(1)

    # --dev: launch app interactively (blocks until stopped)
    if args.dev:
        print(f"\n{BOLD}Dev mode: {project_dir.name}{RESET} ({project['type']})")
        print(f"{'─' * 50}")
        run_dev(project)
        return  # run_dev calls sys.exit

    # --prod: production build (DMG/installer)
    if args.prod:
        print(f"\n{BOLD}Production build: {project_dir.name}{RESET} ({project['type']})")
        print(f"{'─' * 50}")
        start_total = time.time()
        results = build_prod(project)
        prod_failed = any(not r["success"] for r in results)

        # Auto-recompile debug binary after prod build (keeps CLI symlink in sync)
        if not prod_failed and project["has_tauri"]:
            print(f"\n{BOLD}Recompiling debug binary (keep CLI in sync){RESET}")
            print(f"{'─' * 50}")
            r = run_step(
                "Rebuild debug binary (cargo build --bin pair)",
                ["cargo", "build", "--bin", "pair"],
                str(Path(project["dir"]) / "src-tauri"),
                timeout=600,
            )
            results.append(r)
            if r["success"]:
                debug_bin = Path(project["dir"]) / "src-tauri" / "target" / "debug" / "pair"
                if debug_bin.exists():
                    debug_bin.chmod(debug_bin.stat().st_mode | 0o111)
                    print(f"  {GREEN}✓ chmod +x{RESET} {DIM}{debug_bin}{RESET}")

        total_elapsed = time.time() - start_total
        print_summary(results, total_elapsed, args.json)
        if prod_failed:
            sys.exit(1)
        return

    # Default: debug build (compile check)
    build_all = not args.frontend and not args.backend

    if not args.json:
        print(f"\n{BOLD}Building: {project_dir.name}{RESET} ({project['type']})")
        print(f"{'─' * 50}")

    results = []
    start_total = time.time()

    # 1. Install deps if needed
    if build_all or args.frontend:
        r = install_deps(project)
        if r:
            results.append(r)
            if not r["success"]:
                print_summary(results, time.time() - start_total, args.json)
                sys.exit(1)

    # 2. Frontend
    if build_all or args.frontend:
        r = build_frontend(project, check_only=args.check)
        if r:
            results.append(r)
            if not r["success"]:
                print_summary(results, time.time() - start_total, args.json)
                sys.exit(1)

    # 3. Backend
    if build_all or args.backend:
        r = build_backend(project, release=args.release)
        if r:
            results.append(r)
            if not r["success"]:
                print_summary(results, time.time() - start_total, args.json)
                sys.exit(1)

    # 4. Tests (optional)
    if args.test:
        r = run_tests(project)
        if r:
            results.append(r)

    total_elapsed = time.time() - start_total
    print_summary(results, total_elapsed, args.json)

    # Exit with failure if any step failed
    if any(not r["success"] for r in results):
        sys.exit(1)


def print_summary(results: list[dict], total_elapsed: float, as_json: bool):
    """Print compact build summary."""
    all_ok = all(r["success"] for r in results)
    total_warnings = sum(r["warning_count"] for r in results)
    total_errors = sum(r["error_count"] for r in results)

    if as_json:
        print(json.dumps({
            "success": all_ok,
            "elapsed_s": round(total_elapsed, 1),
            "steps": results,
            "total_errors": total_errors,
            "total_warnings": total_warnings,
        }, indent=2))
        return

    print(f"{'─' * 50}")
    if all_ok:
        status = f"{GREEN}{BOLD}✓ BUILD OK{RESET}"
    else:
        status = f"{RED}{BOLD}✗ BUILD FAILED{RESET}"

    parts = [status, f"{DIM}{total_elapsed:.1f}s{RESET}"]
    if total_warnings > 0:
        parts.append(f"{YELLOW}{total_warnings} warnings{RESET}")
    if total_errors > 0:
        parts.append(f"{RED}{total_errors} errors{RESET}")

    print(f" {' | '.join(parts)}")

    # Show errors if any
    for r in results:
        if r["errors"]:
            print(f"\n  {RED}{r['step']}:{RESET}")
            for err in r["errors"]:
                print(f"    {err}")
    print()


if __name__ == "__main__":
    main()
