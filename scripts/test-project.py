#!/usr/bin/env python3
# pair-template: 0.47.0 prod
"""
Test project  -  universal test runner for Claude Code sessions.

Auto-detects project type and runs the appropriate test suites.
Captures output and returns a compact summary to minimize token usage.

Supported test suites:
- Frontend: pnpm test (Vitest)
- Backend: cargo test (Rust)

Usage:
    python3 ~/.claude/scripts/test-project.py              # Run all tests
    python3 ~/.claude/scripts/test-project.py --frontend    # Frontend only
    python3 ~/.claude/scripts/test-project.py --backend     # Backend (Rust) only
    python3 ~/.claude/scripts/test-project.py -C /path      # Specify project dir
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# Ensure cargo/rustup are in PATH (not always inherited in subprocess)
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
    """Detect project type and available test targets."""
    info = {
        "dir": str(project_dir),
        "has_nuxt": (project_dir / "nuxt.config.ts").exists() or (project_dir / "nuxt.config.js").exists(),
        "has_tauri": (project_dir / "src-tauri" / "Cargo.toml").exists(),
        "has_cargo": (project_dir / "Cargo.toml").exists(),
        "has_package_json": (project_dir / "package.json").exists(),
        "has_vitest": (project_dir / "vitest.config.ts").exists() or (project_dir / "vitest.config.js").exists(),
        "pkg_manager": "pnpm",
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

    # Check if test script exists in package.json
    if info["has_package_json"]:
        try:
            import json
            pkg = json.loads((project_dir / "package.json").read_text())
            info["has_test_script"] = "test" in pkg.get("scripts", {})
        except Exception:
            info["has_test_script"] = False
    else:
        info["has_test_script"] = False

    return info


# ---------------------------------------------------------------------------
# Test runners
# ---------------------------------------------------------------------------

def run_frontend_tests(project: dict) -> dict | None:
    """Run frontend tests (pnpm test / vitest)."""
    if not project["has_test_script"]:
        return None

    pkg = project["pkg_manager"]
    cmd = [pkg, "test"]
    cwd = project["dir"]

    print(f"{CYAN}{BOLD}▸ Frontend tests ({pkg} test){RESET}", flush=True)
    start = time.time()

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=120,
        )
        elapsed = time.time() - start
        success = result.returncode == 0
        output = result.stdout + "\n" + result.stderr

        # Parse Vitest output
        parsed = parse_vitest_output(output)

        if success:
            print(f"  {GREEN}✓ {parsed['summary']}{RESET} {DIM}({elapsed:.1f}s){RESET}")
        else:
            print(f"  {RED}✗ {parsed['summary']}{RESET} {DIM}({elapsed:.1f}s){RESET}")
            # Show failed tests
            for fail in parsed["failures"][:10]:
                print(f"  {RED}  ✗ {fail}{RESET}")

        return {
            "suite": "frontend",
            "success": success,
            "elapsed_s": round(elapsed, 1),
            "passed": parsed["passed"],
            "failed": parsed["failed"],
            "total": parsed["total"],
            "files": parsed["files"],
            "failures": parsed["failures"][:10],
        }

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start
        print(f"  {RED}✗ TIMEOUT{RESET} {DIM}(>120s){RESET}")
        return {
            "suite": "frontend",
            "success": False,
            "elapsed_s": round(elapsed, 1),
            "passed": 0,
            "failed": 0,
            "total": 0,
            "files": 0,
            "failures": ["Timeout after 120s"],
        }


def run_backend_tests(project: dict) -> dict | None:
    """Run Rust/Tauri backend tests (cargo test)."""
    if project["has_tauri"]:
        cwd = str(Path(project["dir"]) / "src-tauri")
    elif project["has_cargo"]:
        cwd = project["dir"]
    else:
        return None

    if not (Path(cwd) / "Cargo.toml").exists():
        return None

    cmd = ["cargo", "test"]

    print(f"{CYAN}{BOLD}▸ Backend tests (cargo test){RESET}", flush=True)
    start = time.time()

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=300,
        )
        elapsed = time.time() - start
        success = result.returncode == 0
        output = result.stdout + "\n" + result.stderr

        # Parse cargo test output
        parsed = parse_cargo_test_output(output)

        if success:
            print(f"  {GREEN}✓ {parsed['summary']}{RESET} {DIM}({elapsed:.1f}s){RESET}")
        else:
            print(f"  {RED}✗ {parsed['summary']}{RESET} {DIM}({elapsed:.1f}s){RESET}")
            # Show failed tests
            for fail in parsed["failures"][:10]:
                print(f"  {RED}  ✗ {fail}{RESET}")
            # Show compiler errors if no test results
            if parsed["total"] == 0:
                errors = [l for l in output.split("\n") if "error" in l.lower() and "warning" not in l.lower()]
                for err in errors[:10]:
                    print(f"  {RED}  {err.strip()}{RESET}")

        return {
            "suite": "backend",
            "success": success,
            "elapsed_s": round(elapsed, 1),
            "passed": parsed["passed"],
            "failed": parsed["failed"],
            "total": parsed["total"],
            "files": 0,
            "failures": parsed["failures"][:10],
        }

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start
        print(f"  {RED}✗ TIMEOUT{RESET} {DIM}(>300s){RESET}")
        return {
            "suite": "backend",
            "success": False,
            "elapsed_s": round(elapsed, 1),
            "passed": 0,
            "failed": 0,
            "total": 0,
            "files": 0,
            "failures": ["Timeout after 300s"],
        }


# ---------------------------------------------------------------------------
# Output parsers
# ---------------------------------------------------------------------------

def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return re.sub(r'\x1b\[[0-9;]*m', '', text)


def parse_vitest_output(output: str) -> dict:
    """Parse Vitest output to extract test counts and failures."""
    output = strip_ansi(output)
    passed = 0
    failed = 0
    total = 0
    files = 0
    failures = []

    for line in output.split("\n"):
        # Test Files  10 passed (10)
        m = re.search(r"Test Files\s+(\d+) passed", line)
        if m:
            files = int(m.group(1))

        # Tests  215 passed (215)
        m = re.search(r"Tests\s+(?:(\d+) failed[^|]*\|\s*)?(\d+) passed\s*\((\d+)\)", line)
        if m:
            failed = int(m.group(1)) if m.group(1) else 0
            passed = int(m.group(2))
            total = int(m.group(3))

        # Also catch simpler format: Tests  215 passed (215)
        if total == 0:
            m = re.search(r"Tests\s+(\d+) passed\s*\((\d+)\)", line)
            if m:
                passed = int(m.group(1))
                total = int(m.group(2))

        # Catch failures: Tests  3 failed | 212 passed (215)
        if total == 0:
            m = re.search(r"Tests\s+(\d+) failed\s*\|\s*(\d+) passed\s*\((\d+)\)", line)
            if m:
                failed = int(m.group(1))
                passed = int(m.group(2))
                total = int(m.group(3))

        # FAIL tests/utils/foo.test.ts > suite > test name
        m = re.match(r"\s*(?:×|✗|FAIL)\s+(.+)", line)
        if m:
            failures.append(m.group(1).strip())

    summary = f"{passed} passed"
    if failed > 0:
        summary = f"{failed} failed, {passed} passed"
    summary += f" ({total} total, {files} files)"

    return {
        "passed": passed,
        "failed": failed,
        "total": total,
        "files": files,
        "failures": failures,
        "summary": summary,
    }


def parse_cargo_test_output(output: str) -> dict:
    """Parse cargo test output to extract test counts and failures."""
    output = strip_ansi(output)
    total_passed = 0
    total_failed = 0
    total_total = 0
    failures = []

    for line in output.split("\n"):
        # test result: ok. 82 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out
        m = re.search(r"test result:.*?(\d+) passed;\s*(\d+) failed", line)
        if m:
            total_passed += int(m.group(1))
            total_failed += int(m.group(2))
            total_total += int(m.group(1)) + int(m.group(2))

        # ---- test_name stdout ---- (failure output)
        m = re.match(r"---- (.+?) stdout ----", line)
        if m:
            failures.append(m.group(1))

        # test module::test_name ... FAILED
        m = re.match(r"test (.+?) \.\.\. FAILED", line)
        if m:
            failures.append(m.group(1))

    summary = f"{total_passed} passed"
    if total_failed > 0:
        summary = f"{total_failed} failed, {total_passed} passed"
    summary += f" ({total_total} total)"

    return {
        "passed": total_passed,
        "failed": total_failed,
        "total": total_total,
        "failures": failures,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Run project tests for Claude Code")
    parser.add_argument("-C", "--project-dir", default=os.getcwd(),
                        help="Project directory (default: cwd)")
    parser.add_argument("--frontend", action="store_true",
                        help="Run frontend tests only")
    parser.add_argument("--backend", action="store_true",
                        help="Run backend (Rust) tests only")
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()
    project = detect_project(project_dir)

    run_all = not args.frontend and not args.backend

    print(f"\n{BOLD}Testing: {project_dir.name}{RESET}")
    print(f"{'─' * 50}")

    results = []
    start_total = time.time()

    # Frontend tests
    if run_all or args.frontend:
        r = run_frontend_tests(project)
        if r:
            results.append(r)

    # Backend tests
    if run_all or args.backend:
        r = run_backend_tests(project)
        if r:
            results.append(r)

    total_elapsed = time.time() - start_total

    if not results:
        print(f"  {YELLOW}No test suites found{RESET}")
        sys.exit(0)

    # Summary
    print(f"{'─' * 50}")
    all_ok = all(r["success"] for r in results)
    total_passed = sum(r["passed"] for r in results)
    total_failed = sum(r["failed"] for r in results)
    total_tests = sum(r["total"] for r in results)

    if all_ok:
        status = f"{GREEN}{BOLD}✓ ALL TESTS PASSED{RESET}"
    else:
        status = f"{RED}{BOLD}✗ TESTS FAILED{RESET}"

    parts = [status, f"{DIM}{total_elapsed:.1f}s{RESET}"]
    parts.append(f"{GREEN}{total_passed} passed{RESET}")
    if total_failed > 0:
        parts.append(f"{RED}{total_failed} failed{RESET}")
    parts.append(f"{DIM}{total_tests} total{RESET}")

    print(f" {' | '.join(parts)}")

    # Show failures
    for r in results:
        if r["failures"]:
            print(f"\n  {RED}{r['suite']} failures:{RESET}")
            for fail in r["failures"]:
                print(f"    ✗ {fail}")
    print()

    if not all_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
