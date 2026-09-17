#!/usr/bin/env python3
"""Kjør logging-agenten kontrollert på alle managed-repoer."""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
REPOS_FILE = ROOT / "repos.yaml"
REPOS_DIR = ROOT / "repos"
STATUS_FILE = ROOT / "docs" / "logging-agent-status.md"
BRANCH = "chore/logging-hygiene"
COMMIT_MESSAGE = "chore: rydd logging etter nav-logghygiene"


@dataclass(frozen=True)
class Repository:
    name: str
    default_branch: str


def parse_repositories(path: Path = REPOS_FILE) -> list[Repository]:
    """Les managed-repoer fra den kontrollerte repos.yaml-strukturen."""
    repositories: list[Repository] = []
    current: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if line.startswith("- name:"):
            if current.get("managed") == "true":
                repositories.append(Repository(current["name"], current.get("default_branch", "main")))
            current = {"name": line.split(":", 1)[1].strip()}
        elif ":" in line and current:
            key, value = line.split(":", 1)
            current[key.strip()] = value.strip().strip("\"'")
    if current.get("managed") == "true":
        repositories.append(Repository(current["name"], current.get("default_branch", "main")))
    return repositories


def run(command: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


def current_branch(repo_dir: Path) -> str:
    result = run(["git", "branch", "--show-current"], repo_dir)
    return result.stdout.strip() or "detached"


def is_dirty(repo_dir: Path) -> bool:
    return bool(run(["git", "status", "--porcelain"], repo_dir).stdout.strip())


def agent_command(repo_dir: Path, name: str) -> list[str]:
    prompt = (
        f"Gå gjennom logging i repoet {name} etter nav-logghygiene. "
        "Gjør bare nødvendige, minimale endringer. Ikke logg PII, tokens, headers, "
        "URI-query eller request-/response-body. Bevar API-statuskoder, fallbacks "
        "og separat auditlogg. Kjør relevante tester og rapporter kodebevis."
    )
    return [
        "copilot",
        "--agent",
        "logging-agent",
        "-p",
        prompt,
        "--allow-all-tools",
        "--add-dir",
        str(repo_dir),
        "-C",
        str(repo_dir),
        "--silent",
        "--output-format",
        "json",
    ]


def status_rows(repositories: list[Repository]) -> list[str]:
    rows: list[str] = []
    for repository in repositories:
        repo_dir = REPOS_DIR / repository.name
        if not repo_dir.is_dir():
            rows.append(f"| {repository.name} | blokkert | ikke klonet | - |")
            continue
        branch = current_branch(repo_dir)
        dirty = is_dirty(repo_dir)
        if branch == BRANCH and dirty:
            state = "endringer klare for review"
        elif branch == BRANCH:
            state = "branch uten endringer"
        elif dirty:
            state = "blokkert: lokale endringer"
        else:
            state = f"ikke startet ({branch})"
        rows.append(f"| {repository.name} | {state} | {branch} | - |")
    return rows


def write_status(repositories: list[Repository]) -> None:
    STATUS_FILE.write_text(
        "# Status for logging-agent\n\n"
        f"Sist oppdatert: {date.today().isoformat()}\n\n"
        "Statusen er menneskelesbar og inneholder ikke agentens rå output. "
        "Oppdater den etter agentkjøring, tester og PR-review.\n\n"
        "| Repo | Status | Branch | PR |\n"
        "|---|---|---|---|\n"
        + "\n".join(status_rows(repositories))
        + "\n"
    )


def apply_repository(repository: Repository) -> None:
    repo_dir = REPOS_DIR / repository.name
    if not repo_dir.is_dir():
        return
    if is_dirty(repo_dir):
        print(f"  ⚠ {repository.name}: hopper over lokale endringer", file=sys.stderr)
        return
    branch = current_branch(repo_dir)
    if branch != repository.default_branch:
        print(f"  ⚠ {repository.name}: står på {branch}, forventet {repository.default_branch}", file=sys.stderr)
        return
    created = run(["git", "switch", "-c", BRANCH], repo_dir)
    if created.returncode != 0:
        print(f"  ✗ {repository.name}: kunne ikke opprette {BRANCH}: {created.stderr.strip()}", file=sys.stderr)
        return
    print(f"  → {repository.name}: kjører logging-agent")
    result = run(agent_command(repo_dir, repository.name), ROOT)
    if result.returncode != 0:
        print(f"  ✗ {repository.name}: agenten feilet", file=sys.stderr)
    else:
        print(f"  ✓ {repository.name}: agenten fullførte")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="opprett branch og kjør agenten")
    parser.add_argument("--create-pr", action="store_true", help="start eksisterende interaktive PR-flyt etter kjøring")
    parser.add_argument("--repo", help="kjør bare på ett managed-repo, f.eks. infotek-statistikk")
    args = parser.parse_args()

    repositories = parse_repositories()
    if not repositories:
        print("Fant ingen managed-repoer.", file=sys.stderr)
        return 1

    if args.repo:
        matching = [r for r in repositories if r.name == args.repo]
        if not matching:
            print(
                f"'{args.repo}' er ikke et managed-repo i repos.yaml, eller er stavet feil.",
                file=sys.stderr,
            )
            return 1
        target_repositories = matching
    else:
        target_repositories = repositories

    if args.apply:
        for repository in target_repositories:
            apply_repository(repository)
    write_status(repositories)
    if args.create_pr:
        result = run(
            ["python3", str(ROOT / "scripts" / "pr-all.py"), f"BRANCH={BRANCH}", f"MSG={COMMIT_MESSAGE}"],
            ROOT,
        )
        print(result.stdout, end="")
        if result.returncode != 0:
            print(result.stderr, file=sys.stderr, end="")
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
