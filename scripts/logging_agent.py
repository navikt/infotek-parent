#!/usr/bin/env python3
"""Kjør logging-agenten kontrollert på alle managed-repoer."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

ROOT = Path(__file__).parent.parent
REPOS_FILE = ROOT / "repos.yaml"
REPOS_DIR = ROOT / "repos"
STATUS_FILE = ROOT / "docs" / "logging-agent-status.md"
TEST_RESULTS_FILE = ROOT / "docs" / "logging-agent-test-results.json"
BRANCH = "chore/logging-hygiene"
COMMIT_MESSAGE = "chore: rydd logging etter nav-logghygiene"
TEST_RESULTS_VERSION = 1


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


def detect_test_command(repo_dir: Path) -> list[str] | None:
    """Finn repoets standard testkommando."""
    if (repo_dir / "mvnw").is_file():
        return ["./mvnw", "test"]
    if (repo_dir / "pom.xml").is_file():
        return ["mvn", "test"]

    package_file = repo_dir / "package.json"
    if not package_file.is_file():
        return None
    try:
        package = json.loads(package_file.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(package.get("scripts"), dict) or "test" not in package["scripts"]:
        return None

    package_manager = package.get("packageManager", "")
    if isinstance(package_manager, str):
        manager = package_manager.split("@", 1)[0]
        if manager in {"pnpm", "yarn", "npm"}:
            return [manager, "test"]
    for lockfile, manager in (
        ("pnpm-lock.yaml", "pnpm"),
        ("yarn.lock", "yarn"),
        ("package-lock.json", "npm"),
    ):
        if (repo_dir / lockfile).is_file():
            return [manager, "test"]
    return ["npm", "test"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_test_results(path: Path = TEST_RESULTS_FILE) -> dict[str, object]:
    if not path.is_file():
        return {"version": TEST_RESULTS_VERSION, "repos": {}}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {"version": TEST_RESULTS_VERSION, "repos": {}}
    if not isinstance(data, dict) or not isinstance(data.get("repos"), dict):
        return {"version": TEST_RESULTS_VERSION, "repos": {}}
    return {"version": TEST_RESULTS_VERSION, "repos": data["repos"]}


def save_test_results(results: dict[str, object], path: Path = TEST_RESULTS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as temporary:
        json.dump(results, temporary, ensure_ascii=False, indent=2)
        temporary.write("\n")
        temporary_path = Path(temporary.name)
    temporary_path.replace(path)


def test_result_for(results: dict[str, object], name: str) -> dict[str, str]:
    repos = results.get("repos", {})
    if isinstance(repos, dict) and isinstance(repos.get(name), dict):
        result = repos[name]
        if all(isinstance(result.get(key), str) for key in ("command", "result", "timestamp")):
            return result
    return {"command": "-", "result": "-", "timestamp": "-"}


def record_test_result(
    results: dict[str, object],
    repository: Repository,
    command: list[str] | None,
    result: str,
    path: Path = TEST_RESULTS_FILE,
) -> None:
    repos = results.setdefault("repos", {})
    assert isinstance(repos, dict)
    repos[repository.name] = {
        "command": " ".join(command) if command else "ikke konfigurert",
        "result": result,
        "timestamp": now_iso(),
    }
    save_test_results(results, path)


def status_rows(repositories: list[Repository], test_results: dict[str, object]) -> list[str]:
    rows: list[str] = []
    for repository in repositories:
        repo_dir = REPOS_DIR / repository.name
        if not repo_dir.is_dir():
            state = "blokkert: ikke klonet"
            branch = "-"
        else:
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
        test = test_result_for(test_results, repository.name)
        rows.append(
            f"| {repository.name} | {state} | {branch} | {test['command']} | "
            f"{test['result']} | {test['timestamp']} |"
        )
    return rows


def write_status(repositories: list[Repository]) -> None:
    test_results = load_test_results()
    STATUS_FILE.write_text(
        "# Status for logging-agent\n\n"
        f"Sist oppdatert: {date.today().isoformat()}\n\n"
        "Statusen er menneskelesbar og inneholder ikke agentens rå output. "
        "Oppdater den etter agentkjøring, tester og PR-review.\n\n"
        "| Repo | Status | Branch | Testkommando | Testresultat | Tidspunkt |\n"
        "|---|---|---|---|---|---|\n"
        + "\n".join(status_rows(repositories, test_results))
        + "\n"
    )


def run_repository_test(repository: Repository, results: dict[str, object]) -> bool:
    """Kjør repoets testkommando og lagre kommando/exit-resultat/tidspunkt."""
    repo_dir = REPOS_DIR / repository.name
    command = detect_test_command(repo_dir)
    if command is None:
        print(f"  - {repository.name}: testkommando ikke konfigurert")
        record_test_result(results, repository, None, "ikke konfigurert")
        return False
    print(f"  → {repository.name}: kjører {' '.join(command)}")
    try:
        completed = subprocess.run(command, cwd=repo_dir, text=True, check=False)
    except OSError as error:
        print(f"  ✗ {repository.name}: kunne ikke starte testkommandoen: {error}", file=sys.stderr)
        record_test_result(results, repository, command, "exit 127")
        return False
    record_test_result(results, repository, command, f"exit {completed.returncode}")
    marker = "✓" if completed.returncode == 0 else "✗"
    print(f"  {marker} {repository.name}: tester avsluttet med exit {completed.returncode}")
    return completed.returncode == 0


def apply_repository(repository: Repository, results: dict[str, object]) -> bool:
    """Opprett branch, kjør agenten, og kjør deretter testene automatisk."""
    repo_dir = REPOS_DIR / repository.name
    if not repo_dir.is_dir():
        return False
    if is_dirty(repo_dir):
        print(f"  ⚠ {repository.name}: hopper over lokale endringer", file=sys.stderr)
        return False
    branch = current_branch(repo_dir)
    if branch != repository.default_branch:
        print(f"  ⚠ {repository.name}: står på {branch}, forventet {repository.default_branch}", file=sys.stderr)
        return False
    created = run(["git", "switch", "-c", BRANCH], repo_dir)
    if created.returncode != 0:
        print(f"  ✗ {repository.name}: kunne ikke opprette {BRANCH}: {created.stderr.strip()}", file=sys.stderr)
        return False
    print(f"  → {repository.name}: kjører logging-agent")
    result = run(agent_command(repo_dir, repository.name), ROOT)
    if result.returncode != 0:
        print(f"  ✗ {repository.name}: agenten feilet", file=sys.stderr)
        return False
    print(f"  ✓ {repository.name}: agenten fullførte")
    return run_repository_test(repository, results)


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

    apply_ok = True
    if args.apply:
        results = load_test_results()
        for repository in target_repositories:
            if not apply_repository(repository, results):
                apply_ok = False

    write_status(repositories)

    if not apply_ok:
        return 1

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
