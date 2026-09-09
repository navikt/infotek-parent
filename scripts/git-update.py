#!/usr/bin/env python3
"""Oppdater parent-repoet og alle managed repos til registrert default branch."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REPOS_FILE = ROOT / "repos.yaml"
REPOS_DIR = ROOT / "repos"


@dataclass(frozen=True)
class Repository:
    name: str
    path: Path
    default_branch: str | None


def run_git(repository: Repository, *arguments: str, quiet: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repository.path), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def managed_repositories() -> list[Repository]:
    result = subprocess.run(
        ["yq", "-r", '.repos[] | select(.managed == true) | [.name, .default_branch] | @tsv', str(REPOS_FILE)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Kunne ikke lese {REPOS_FILE} med yq:\n{result.stderr.strip()}", file=sys.stderr)
        raise SystemExit(result.returncode)

    repositories = [
        Repository(name, REPOS_DIR / name, branch)
        for line in result.stdout.splitlines()
        if (parts := line.split("\t", 1)) and len(parts) == 2
        for name, branch in [parts]
    ]
    return repositories


def parent_repository() -> Repository:
    result = subprocess.run(
        ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return Repository("infotek-parent", ROOT, None)
    branch = result.stdout.strip().removeprefix("origin/")
    return Repository("infotek-parent", ROOT, branch or None)


def is_dirty(repository: Repository) -> bool:
    result = run_git(repository, "status", "--porcelain")
    return bool(result.stdout.strip())


def remote_branch_exists(repository: Repository, branch: str) -> bool:
    return run_git(repository, "show-ref", "--verify", "--quiet", f"refs/remotes/origin/{branch}").returncode == 0


def remote_counts(repository: Repository, branch: str, local_ref: str = "HEAD") -> tuple[int, int] | None:
    result = run_git(repository, "rev-list", "--left-right", "--count", f"origin/{branch}...{local_ref}")
    if result.returncode != 0:
        return None
    values = result.stdout.split()
    if len(values) != 2:
        return None
    return int(values[0]), int(values[1])


def inspect(repository: Repository, actions: list[Repository]) -> int:
    label = repository.name
    if repository.default_branch is None:
        print(f"  ⚠️  {label} — kunne ikke fastslå default branch fra origin/HEAD (håndter manuelt)")
        return 1

    default_branch = repository.default_branch
    if not (repository.path / ".git").exists():
        print(f"  ⚠️  {label} — ikke klonet (kjør 'make git-clone')")
        return 1

    fetch = run_git(repository, "fetch", "--prune", "origin", quiet=True)
    if fetch.returncode != 0:
        print(f"  ⚠️  {label} — fetch feilet")
        return 1

    if is_dirty(repository):
        print(f"  ⚠️  {label} — lokale eller utrackede endringer (commit/stash eller håndter manuelt)")
        return 1

    current_branch = run_git(repository, "branch", "--show-current").stdout.strip()
    if not current_branch:
        print(f"  ⚠️  {label} — detached HEAD (checkout manuelt)")
        return 1

    if not remote_branch_exists(repository, default_branch):
        print(f"  ⚠️  {label} — origin/{default_branch} finnes ikke")
        return 1

    local_branch_exists = run_git(
        repository,
        "show-ref",
        "--verify",
        "--quiet",
        f"refs/heads/{default_branch}",
    ).returncode == 0
    if not local_branch_exists:
        print(f"  ⚠️  {label} — lokal default branch {default_branch} finnes ikke (håndter manuelt)")
        return 1

    if current_branch != default_branch:
        counts = remote_counts(repository, default_branch, f"refs/heads/{default_branch}")
        if counts is None:
            print(f"  ⚠️  {label} — kunne ikke fastslå status for lokal {default_branch}")
            return 1
        behind, ahead = counts
        if ahead and behind:
            print(f"  ⚠️  {label} — lokal {default_branch} divergerer fra origin (håndter manuelt)")
            return 1
        if ahead:
            print(f"  ⚠️  {label} — lokal {default_branch} er foran origin (ikke push automatisk)")
            return 1
        print(f"  → {label} — kan bytte til {default_branch}")
        actions.append(repository)
        return 0

    counts = remote_counts(repository, default_branch)
    if counts is None:
        print(f"  ⚠️  {label} — kunne ikke fastslå remote-status")
        return 1

    behind, ahead = counts
    if ahead and behind:
        print(f"  ⚠️  {label} — default branch divergerer fra origin (håndter manuelt)")
        return 1
    if ahead:
        print(f"  ⚠️  {label} — lokal default branch er foran origin (ikke push automatisk)")
        return 1
    if behind:
        print(f"  → {label} — kan oppdateres med pull --ff-only ({behind} commit(er) bak)")
        actions.append(repository)
    else:
        print(f"  ✓ {label} — {repository.default_branch}, ren og oppdatert")
    return 0


def update(repository: Repository) -> bool:
    assert repository.default_branch is not None
    checkout = run_git(repository, "checkout", repository.default_branch, quiet=True)
    pull = (
        run_git(repository, "pull", "--ff-only", "origin", repository.default_branch, quiet=True)
        if checkout.returncode == 0
        else checkout
    )
    if pull.returncode == 0:
        print(f"  ✓ {repository.name} — {repository.default_branch} oppdatert")
        return True
    print(f"  ⚠️  {repository.name} — oppdatering feilet, håndter manuelt")
    return False


def main() -> int:
    repositories = [parent_repository(), *managed_repositories()]
    actions: list[Repository] = []
    blockers = 0

    print("Oppdaterer parent og managed repos\n")
    for repository in repositories:
        blockers += inspect(repository, actions)

    if actions:
        print("\nFølgende repoer kan bytte til default branch og/eller oppdateres med pull --ff-only.")
        print("Lokale endringer, utrackede filer, divergens og lokale commits foran remote røres ikke.")
        answer = input("Vil du bytte disse repoene til default branch og oppdatere dem med pull --ff-only? [j/N] ")
        if answer.lower().startswith("j"):
            failed = sum(not update(repository) for repository in actions)
            blockers += failed
        else:
            print("  Avbrutt.")

    if blockers:
        print("\n⚠️  Noen repos er ikke oppdatert. Se forslagene over og håndter avvik manuelt ved behov.")
    else:
        print("\n✓ Parent og alle managed repos er oppdatert.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
