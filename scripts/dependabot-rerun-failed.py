#!/usr/bin/env python3
"""
Finner åpne Dependabot-PRer med feilede CI-sjekker og rerunner dem.
Viser major/minor/patch-type og spør om bekreftelse per PR.

Alternativt: bruk [r] Rerun CI direkte i make dependabot-next.
Repos med dependabot_skip: true i repos.yaml hoppes over.

Bruk: python3 scripts/dependabot-rerun-failed.py [--dry-run]
  --dry-run  Vis hva som ville skjedd uten å gjøre endringer
"""

import json
import re
import subprocess
import sys
from pathlib import Path

REPOS_FILE = Path(__file__).parent.parent / "repos.yaml"
DRY_RUN = "--dry-run" in sys.argv

BOLD    = "\033[1m"
GREEN   = "\033[32m"
RED     = "\033[31m"
YELLOW  = "\033[33m"
CYAN    = "\033[36m"
MAGENTA = "\033[35m"
DIM     = "\033[2m"
RESET   = "\033[0m"


def detect_bump_type(pr: dict) -> str:
    branch = pr.get("headRefName", "").lower()
    if "-major" in branch:
        return "MAJOR"
    if "-minor" in branch:
        return "minor"
    if "-patch" in branch:
        return "patch"
    m = re.search(r"from\s+(\d+)\.\S+\s+to\s+(\d+)\.", pr.get("title", ""), re.IGNORECASE)
    if m and int(m.group(2)) > int(m.group(1)):
        return "MAJOR"
    return "minor"


def bump_label(bump: str) -> str:
    if bump == "MAJOR":
        return MAGENTA + BOLD + "MAJOR" + RESET
    if bump == "minor":
        return CYAN + "minor" + RESET
    return DIM + "patch" + RESET


def run(cmd, check=False):
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def parse_repos():
    repos = []
    in_repos = False
    current = {}
    for line in REPOS_FILE.read_text().splitlines():
        stripped = line.strip().split("#")[0].strip()
        if stripped.startswith("repos:"):
            in_repos = True
            continue
        if not in_repos or not stripped:
            continue
        if stripped.startswith("- name:"):
            if current.get("name") and current.get("managed", True) and not current.get("dependabot_skip"):
                repos.append(current)
            current = {"name": stripped.split(":", 1)[1].strip(), "managed": True}
        elif ":" in stripped:
            key, _, val = stripped.partition(":")
            key, val = key.strip(), val.strip()
            if key == "org":
                current["org"] = val
            elif key == "managed":
                current["managed"] = val.lower() != "false"
            elif key == "dependabot_skip":
                current["dependabot_skip"] = val.lower() == "true"
    if current.get("name") and current.get("managed", True) and not current.get("dependabot_skip"):
        repos.append(current)
    return repos


def fetch_dependabot_prs(org: str, name: str) -> list:
    result = run([
        "gh", "pr", "list",
        "--repo", f"{org}/{name}",
        "--author", "app/dependabot",
        "--state", "open",
        "--json", "number,title,headRefName,statusCheckRollup,url",
        "--limit", "20",
    ])
    if result.returncode != 0:
        return []
    try:
        prs = json.loads(result.stdout)
        return sorted(prs, key=lambda p: p["number"])
    except json.JSONDecodeError:
        return []


def failed_checks(pr: dict) -> list[str]:
    return [
        c["name"] for c in pr.get("statusCheckRollup", [])
        if c.get("conclusion") in ("FAILURE", "TIMED_OUT", "ERROR")
    ]


def find_latest_run_id(org: str, name: str, branch: str) -> str | None:
    """Finn nyeste run-ID for en gitt branch."""
    result = run([
        "gh", "run", "list",
        "--repo", f"{org}/{name}",
        "--branch", branch,
        "--json", "databaseId,status,conclusion",
        "--limit", "5",
    ])
    if result.returncode != 0:
        return None
    try:
        runs = json.loads(result.stdout)
        # Foretrekk runs som faktisk feilet
        for r in runs:
            if r.get("conclusion") in ("failure", "timed_out"):
                return str(r["databaseId"])
        # Ellers bruk nyeste
        return str(runs[0]["databaseId"]) if runs else None
    except (json.JSONDecodeError, IndexError):
        return None


def ask_confirm(prompt: str) -> bool:
    print(f"     {prompt} [{CYAN}j{RESET}/N] ", end="", flush=True)
    try:
        ans = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return ans in ("j", "ja", "y", "yes")


def main():
    repos = parse_repos()
    prefix = f"{YELLOW}[DRY-RUN]{RESET} " if DRY_RUN else ""
    print(f"\n{BOLD}{prefix}Dependabot — rerun feilede checks{RESET}\n")

    total_rerun = 0
    total_skipped = 0

    for repo in repos:
        name = repo["name"]
        org  = repo.get("org", "navikt")
        prs  = fetch_dependabot_prs(org, name)
        if not prs:
            continue

        failing = [(pr, failed_checks(pr)) for pr in prs if failed_checks(pr)]
        if not failing:
            continue

        repo_full = f"{org}/{name}"
        print(f"  {BOLD}{name}{RESET}")

        for pr, checks in failing:
            bump   = detect_bump_type(pr)
            number = f"#{pr['number']}"
            title  = pr["title"][:55] + ("…" if len(pr["title"]) > 55 else "")
            print(f"    {RED}❌{RESET} {bump_label(bump):<25}  {DIM}{number}{RESET}  {title}")
            print(f"       Feilede checks: {RED}{', '.join(checks[:4])}{RESET}")
            print(f"       {pr['url']}")

            if DRY_RUN:
                print(f"       {DIM}→ ville rerunnet feilede jobs{RESET}")
                total_rerun += 1
                continue

            if not ask_confirm("Rerun feilede jobs?"):
                print(f"       {DIM}→ skippet{RESET}")
                total_skipped += 1
                continue

            run_id = find_latest_run_id(org, name, pr["headRefName"])
            if not run_id:
                print(f"       {YELLOW}⚠️  Fant ingen run for branch {pr['headRefName']}{RESET}")
                total_skipped += 1
                continue

            result = run(["gh", "run", "rerun", run_id, "--failed", "--repo", repo_full])
            if result.returncode == 0:
                print(f"       {GREEN}→ rerun startet (run {run_id}){RESET}")
                total_rerun += 1
            else:
                err = result.stderr.strip()
                print(f"       {RED}→ rerun feilet: {err}{RESET}")
                total_skipped += 1

        print()

    if total_rerun == 0 and total_skipped == 0:
        print(f"  {DIM}Ingen feilede Dependabot-PRer funnet{RESET}\n")
    else:
        parts = []
        if total_rerun:
            parts.append(f"{GREEN}{total_rerun} rerun startet{RESET}")
        if total_skipped:
            parts.append(f"{DIM}{total_skipped} skippet{RESET}")
        print(f"  {' · '.join(parts)}\n")


if __name__ == "__main__":
    main()
