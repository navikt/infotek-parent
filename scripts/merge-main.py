#!/usr/bin/env python3
"""
Merger default-branch (main/master) inn i alle feature-branches på tvers av repos.
Skipper branches med merge-konflikter og rapporterer resultatet.

Bruk: python3 scripts/merge-main.py [--dry-run]
"""

import os
import subprocess
import sys
from pathlib import Path

REPOS_DIR = Path(__file__).parent.parent / "repos"
DRY_RUN = "--dry-run" in sys.argv


def run(cmd, cwd=None, check=True):
    env = os.environ.copy()
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=check, env=env)


def get_default_branch(repo_dir):
    result = run(
        ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
        cwd=repo_dir,
        check=False,
    )
    if result.returncode == 0:
        return result.stdout.strip().removeprefix("origin/")
    return "main"


def get_remote_feature_branches(repo_dir, default_branch):
    result = run(["git", "branch", "-r", "--format=%(refname:short)"], cwd=repo_dir)
    branches = []
    for line in result.stdout.splitlines():
        line = line.strip().removeprefix("origin/")
        if line and line != default_branch and not line.startswith("HEAD"):
            branches.append(line)
    return branches


def main():
    for repo_dir in sorted(REPOS_DIR.iterdir()):
        if not repo_dir.is_dir():
            continue

        result = run(["git", "rev-parse", "--git-dir"], cwd=repo_dir, check=False)
        if result.returncode != 0:
            continue

        run(["git", "fetch", "origin", "--prune"], cwd=repo_dir)

        default_branch = get_default_branch(repo_dir)
        feature_branches = get_remote_feature_branches(repo_dir, default_branch)

        if not feature_branches:
            continue

        repo_name = repo_dir.name
        print(f"\n{'[DRY-RUN] ' if DRY_RUN else ''}📦 {repo_name}  (default: {default_branch})")

        for branch in feature_branches:
            if DRY_RUN:
                print(f"  → ville merget {default_branch} inn i {branch}")
                continue

            # Checkout feature branch og sett den til remote-state
            run(["git", "checkout", branch], cwd=repo_dir, check=False)
            run(["git", "reset", "--hard", f"origin/{branch}"], cwd=repo_dir)

            # Sjekk om merge er nødvendig
            behind = run(
                ["git", "rev-list", "--count", f"HEAD..origin/{default_branch}"],
                cwd=repo_dir,
            )
            commits_behind = int(behind.stdout.strip() or "0")
            if commits_behind == 0:
                print(f"  ✅ {branch} — allerede oppdatert")
                continue

            # Merge default-branch inn i feature branch
            merge = run(
                ["git", "merge", f"origin/{default_branch}", "--no-edit"],
                cwd=repo_dir,
                check=False,
            )
            if merge.returncode != 0:
                run(["git", "merge", "--abort"], cwd=repo_dir, check=False)
                print(f"  ⚠️  {branch} — merge-konflikt, skipper")
                continue

            push = run(["git", "push", "origin", branch], cwd=repo_dir, check=False)
            if push.returncode == 0:
                print(f"  ✅ {branch} — merget {commits_behind} commit(s) fra {default_branch}")
            else:
                print(f"  ❌ {branch} — push feilet: {push.stderr.strip()}")

        # Gå tilbake til default-branch
        run(["git", "checkout", default_branch], cwd=repo_dir, check=False)


if __name__ == "__main__":
    main()
