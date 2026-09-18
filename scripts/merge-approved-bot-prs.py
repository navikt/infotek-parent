#!/usr/bin/env python3
"""Merge approved bot PRs one at a time per managed repository."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REPOS_FILE = ROOT / "repos.yaml"
CONFIG_FILE = ROOT / "config.json"
ALLOWED_CONCLUSIONS = {"SUCCESS", "NEUTRAL", "SKIPPED"}
REPORT_SCHEMA_VERSION = 7


@dataclass(frozen=True)
class Repository:
    slug: str
    name: str


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def load_pr_config() -> dict[str, object]:
    try:
        config = json.loads(CONFIG_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(config, dict):
        return {}
    pr_config = config.get("pr")
    return pr_config if isinstance(pr_config, dict) else {}


PR_CONFIG = load_pr_config()
MERGE_STRATEGY = str(PR_CONFIG.get("merge_strategy", "squash"))
DELETE_BRANCH_ON_MERGE = bool(PR_CONFIG.get("delete_branch_on_merge", True))


def gh_json(*arguments: str) -> object:
    result = run(["gh", *arguments])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "gh-kommandoen feilet")
    return json.loads(result.stdout)


def gh_text(*arguments: str) -> str:
    result = run(["gh", *arguments])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "gh-kommandoen feilet")
    return result.stdout.strip()


def managed_repositories() -> list[Repository]:
    result = run(
        [
            "yq",
            "-r",
            ".repos[] | select(.managed == true and (.dependabot_skip // false) == false and (.pr_skip // false) == false) | [.org, .name] | @tsv",
            str(REPOS_FILE),
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"Kunne ikke lese {REPOS_FILE}")

    return [
        Repository(f"{org}/{name}", name)
        for line in result.stdout.splitlines()
        if (parts := line.split("\t", 1)) and len(parts) == 2
        for org, name in [parts]
    ]


def current_user() -> str:
    return gh_text("api", "user", "--jq", ".login")


def is_bot(pr: dict[str, object]) -> bool:
    author = pr.get("author") or {}
    login = (
        author.get("login", "")
        if isinstance(author, dict)
        else author
        if isinstance(author, str)
        else ""
    )
    return isinstance(login, str) and (login.endswith("[bot]") or login == "app/dependabot")


def checks_are_green(checks: object) -> bool:
    return isinstance(checks, list) and bool(checks) and all(
        isinstance(check, dict)
        and check.get("status") == "COMPLETED"
        and check.get("conclusion") in ALLOWED_CONCLUSIONS
        for check in checks
    )


def user_approved(pr: dict[str, object], login: str) -> bool:
    reviews = [
        review
        for review in pr.get("reviews") or []
        if isinstance(review, dict)
        and isinstance(review.get("author"), dict)
        and review["author"].get("login") == login
        and review.get("state") in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}
    ]
    if not reviews:
        return False
    latest = max(reviews, key=lambda review: review.get("submittedAt", ""))
    return latest.get("state") == "APPROVED"


def eligible_prs(repository: Repository, login: str) -> list[dict[str, object]]:
    prs = gh_json(
        "pr",
        "list",
        "--repo",
        repository.slug,
        "--state",
        "open",
        "--limit",
        "100",
        "--json",
        (
            "number,title,url,author,mergeable,mergeStateStatus,reviewDecision,"
            "statusCheckRollup,reviews,isDraft"
        ),
    )
    if not isinstance(prs, list):
        return []
    return [
        pr
        for pr in prs
        if isinstance(pr, dict)
        and not pr.get("isDraft")
        and is_bot(pr)
        and pr.get("mergeable") == "MERGEABLE"
        and pr.get("mergeStateStatus") == "CLEAN"
        and user_approved(pr, login)
        and checks_are_green(pr.get("statusCheckRollup", []))
    ]


def repositories_from_report(report: dict[str, object]) -> list[Repository]:
    scope = report.get("scope")
    entries = scope.get("repositories", []) if isinstance(scope, dict) else []
    repositories = []
    if not isinstance(entries, list):
        return repositories
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("managed", True):
            continue
        if entry.get("dependabot_skip") or entry.get("pr_skip"):
            continue
        name = entry.get("name")
        org = entry.get("org", "navikt")
        if isinstance(name, str) and isinstance(org, str):
            repositories.append(Repository(f"{org}/{name}", name))
    return repositories


def report_eligible_prs(
    report: dict[str, object], repositories: list[Repository]
) -> list[tuple[Repository, dict[str, object]]]:
    report_repositories = report.get("repositories", {})
    if not isinstance(report_repositories, dict):
        return []

    candidates = []
    for repository in repositories:
        details = report_repositories.get(repository.name, {})
        if not isinstance(details, dict):
            continue
        dependabot = details.get("dependabot_prs", {})
        prs = dependabot.get("items", []) if isinstance(dependabot, dict) else []
        if not isinstance(prs, list):
            continue
        for pr in prs:
            if (
                isinstance(pr, dict)
                and not pr.get("isDraft")
                and is_bot(pr)
                and pr.get("mergeable") == "MERGEABLE"
                and pr.get("mergeStateStatus") == "CLEAN"
                and pr.get("reviewDecision") == "APPROVED"
                and checks_are_green(pr.get("statusCheckRollup"))
            ):
                candidates.append((repository, pr))
    return candidates


def load_report(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Kunne ikke lese rapporten {path}: {error}") from error
    if not isinstance(value, dict):
        raise RuntimeError(f"Rapporten {path} har ugyldig format.")
    if value.get("schema_version") != REPORT_SCHEMA_VERSION:
        raise RuntimeError(
            f"Rapporten {path} har feil schema_version "
            f"({value.get('schema_version')}, forventet {REPORT_SCHEMA_VERSION})."
        )
    scope = value.get("scope")
    repositories = value.get("repositories")
    if not isinstance(scope, dict) or not isinstance(scope.get("repositories"), list) or not isinstance(repositories, dict):
        raise RuntimeError(f"Rapporten {path} mangler forventet struktur for sheriff-rapport.")
    return value


def describe(pr: dict[str, object], repository: Repository) -> None:
    print(
        f"{repository.slug}#{pr.get('number')}: {pr.get('title', '-')}\n"
        f"  {pr.get('url', '-')}\n"
        f"  mergeable={pr.get('mergeable', '-')} "
        f"state={pr.get('mergeStateStatus', '-')}"
    )


def merge_pr(pr: dict[str, object], repository: Repository) -> None:
    strategy_flag = f"--{MERGE_STRATEGY}"
    if strategy_flag not in {"--merge", "--squash", "--rebase"}:
        strategy_flag = "--squash"
    result = run(
        [
            "gh",
            "pr",
            "merge",
            str(pr["number"]),
            "--repo",
            repository.slug,
            strategy_flag,
            *(["--delete-branch"] if DELETE_BRANCH_ON_MERGE else ["--delete-branch=false"]),
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Merge feilet")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Finn og merger godkjente bot-PRer sekvensielt per managed repo."
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="Utfør merge. Uten dette flagget vises bare kandidater.",
    )
    parser.add_argument(
        "--report",
        "--from-report",
        dest="report",
        type=Path,
        help="Bruk lagret sheriff-rapport som lokal dry-run-kilde.",
    )
    args = parser.parse_args()

    try:
        if args.report and not args.merge:
            report = load_report(args.report)
            repositories = repositories_from_report(report)
            candidates = report_eligible_prs(report, repositories)
            for repository, pr in candidates:
                describe(pr, repository)
            if not candidates:
                print("Ingen godkjente, mergeable bot-PRer med grønn CI funnet i rapporten.")
            else:
                print(
                    f"\nDry-run fra rapport: {len(candidates)} kandidat(er). "
                    "Ingen GitHub-oppslag eller muterende handlinger utført."
                )
            return 0

        if args.report:
            print(
                "Rapporten brukes ikke som merge-kilde; henter fersk status før hver merge."
            )
        login = current_user()
        repositories = managed_repositories()
        candidates = []
        for repository in repositories:
            while True:
                prs = eligible_prs(repository, login)
                if not prs:
                    break
                pr = sorted(prs, key=lambda item: int(item["number"]))[0]
                candidates.append((repository, pr))
                describe(pr, repository)
                if not args.merge:
                    break
                merge_pr(pr, repository)
                print("  ✓ Merget. Henter ny status før neste PR i samme repo.")
    except (RuntimeError, KeyError, TypeError, ValueError) as error:
        print(f"❌ {error}", file=sys.stderr)
        return 1

    if not candidates:
        print("Ingen godkjente, mergeable bot-PRer med grønn CI funnet.")
    elif not args.merge:
        print("\nDry-run: bruk --merge for å utføre merge.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
