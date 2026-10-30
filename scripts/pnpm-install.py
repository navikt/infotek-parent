#!/usr/bin/env python3
"""
Kjører pnpm install i alle frontend-mapper i managed repos.

Bruk:
  python3 scripts/pnpm-install.py [--dry-run]
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

DRY_RUN = "--dry-run" in sys.argv
ROOT = Path(__file__).parent.parent
REPOS_DIR = ROOT / "repos"
REPOS_FILE = ROOT / "repos.yaml"


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


def managed_repo_names(repos_file: Path) -> list[str]:
    result = subprocess.run(
        ["yq", "e", ".repos[] | select(.managed == true) | .name", str(repos_file)],
        capture_output=True, text=True, check=True,
    )
    return [name for name in result.stdout.split() if name]


def find_package_jsons(repo_path):
    results = []
    for p in repo_path.rglob("package.json"):
        parts = p.parts
        if "node_modules" in parts or ".pnpm" in parts:
            continue
        results.append(p.parent)
    return results


def choose_targets(targets: list[tuple[Path, Path]], answer: str) -> list[tuple[Path, Path]]:
    answer = answer.strip().lower()
    if answer == "q":
        return []
    if not answer:
        return targets
    choices = [part.strip() for part in answer.split(",")]
    if any(not part.isdigit() or not 1 <= int(part) <= len(targets) for part in choices):
        raise ValueError("Oppgi ett eller flere numre fra listen, adskilt med komma")
    return [targets[int(part) - 1] for part in dict.fromkeys(choices)]


def main():
    managed = set(managed_repo_names(REPOS_FILE))
    repos = sorted(d for d in REPOS_DIR.iterdir() if d.is_dir() and d.name in managed)
    if not repos:
        print("Ingen managed repos funnet. Kjør 'make git-clone' først.")
        sys.exit(1)

    targets: list[tuple[Path, Path]] = []
    for repo_dir in repos:
        for pkg_dir in find_package_jsons(repo_dir):
            targets.append((repo_dir, pkg_dir))

    if not targets:
        print("Ingen package.json funnet i klonede repos.")
        return

    if sys.stdin.isatty():
        print("\nFrontender i managed repos:")
        for number, (_, pkg_dir) in enumerate(targets, start=1):
            print(f"  {number}) {pkg_dir.relative_to(REPOS_DIR)}")
        try:
            targets = choose_targets(targets, input("\nVelg (flere med komma, Enter = alle, q = avbryt): "))
        except ValueError as error:
            print(f"❌ {error}")
            sys.exit(1)
        if not targets:
            print("Avbrutt.")
            return

    total, ok, failed = 0, 0, 0
    for repo_dir, pkg_dir in targets:
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
