#!/usr/bin/env python3
"""
Kjører pnpm install i alle frontend-mapper på tvers av repos.

Bruk:
  python3 scripts/pnpm-install.py [--dry-run]
"""

import os
import subprocess
import sys
from pathlib import Path

DRY_RUN = "--dry-run" in sys.argv
REPOS_DIR = Path(__file__).parent.parent / "repos"


def run_streaming(cmd, cwd=None):
    """Run command and stream output line by line. Returns exit code."""
    env = os.environ.copy()
    env["NODE_NO_WARNINGS"] = "1"
    proc = subprocess.Popen(
        cmd, cwd=cwd, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    for line in proc.stdout:
        print(f"  {line}", end="", flush=True)
    proc.wait()
    return proc.returncode


def find_package_jsons(repo_path):
    results = []
    for p in repo_path.rglob("package.json"):
        parts = p.parts
        if "node_modules" in parts or ".pnpm" in parts:
            continue
        results.append(p.parent)
    return results


def main():
    repos = sorted(d for d in REPOS_DIR.iterdir() if d.is_dir())
    if not repos:
        print("Ingen repos funnet. Kjør 'make clone' først.")
        sys.exit(1)

    total, ok, failed = 0, 0, 0

    for repo_dir in repos:
        pkg_dirs = find_package_jsons(repo_dir)
        if not pkg_dirs:
            continue

        for pkg_dir in pkg_dirs:
            rel = pkg_dir.relative_to(REPOS_DIR)
            total += 1
            print(f"\n{'[DRY-RUN] ' if DRY_RUN else ''}⏳ pnpm install: {rel}", flush=True)
            if DRY_RUN:
                ok += 1
                continue

            rc = run_streaming(["pnpm", "install", "--no-frozen-lockfile"], cwd=pkg_dir)
            if rc == 0:
                print(f"  ✅ OK", flush=True)
                ok += 1
            else:
                print(f"  ❌ Feilet (exit {rc})", flush=True)
                failed += 1

    print(f"\nFerdig: {ok}/{total} OK" + (f", {failed} feilet" if failed else ""))


if __name__ == "__main__":
    main()
