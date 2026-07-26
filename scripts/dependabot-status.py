#!/usr/bin/env python3
"""
Viser alle åpne Dependabot-PRer og CI-status på tvers av managed repos.

Nyttig for å få oversikt før du kjører make dependabot-next.
Repos med dependabot_skip: true i repos.yaml hoppes over.

Bruk: python3 scripts/dependabot-status.py
"""

import json
import os
import subprocess
import sys
from pathlib import Path

REPOS_FILE = Path(__file__).parent.parent / "repos.yaml"

BOLD   = "\033[1m"
GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
DIM    = "\033[2m"
RESET  = "\033[0m"


def detect_bump_type(pr: dict) -> str:
    """Returner 'MAJOR', 'minor' eller 'patch' basert på branch-navn og tittel."""
    import re
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
        return "\033[35m\033[1mMAJOR\033[0m"
    if bump == "minor":
        return CYAN + "minor" + RESET
    return DIM + "patch" + RESET


def supports_osc8() -> bool:
    term_program = os.environ.get("TERM_PROGRAM", "")
    if term_program in {"iTerm.app", "WarpTerminal", "WezTerm", "vscode", "Hyper"}:
        return True
    if os.environ.get("VTE_VERSION"):
        return True
    if os.environ.get("ALACRITTY_SOCKET") or os.environ.get("ALACRITTY_LOG"):
        return True
    if os.environ.get("TERM") == "xterm-kitty":
        return True
    return False


OSC8_SUPPORTED = supports_osc8()


def link(url: str, text: str = None, style: str = None) -> str:
    label = text or url
    if OSC8_SUPPORTED:
        inner = f"{style}{label}{RESET}" if style else f"{DIM}{label}{RESET}"
        return f"\033]8;;{url}\007{inner}\033]8;;\007"
    return f"{style}{label}{RESET}" if (style and text) else url


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


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


def ci_status(checks: list) -> tuple[str, str]:
    if not checks:
        return DIM + "—" + RESET, "ingen checks"
    statuses    = {c.get("status") for c in checks}
    conclusions = {c.get("conclusion") for c in checks if c.get("conclusion")}

    if "IN_PROGRESS" in statuses or "QUEUED" in statuses or "WAITING" in statuses:
        running = [c["name"] for c in checks if c.get("status") in ("IN_PROGRESS", "QUEUED", "WAITING")]
        return YELLOW + "⏳" + RESET, f"kjører: {', '.join(running[:2])}"
    if "FAILURE" in conclusions or "TIMED_OUT" in conclusions or "ERROR" in conclusions:
        failed = [c["name"] for c in checks if c.get("conclusion") in ("FAILURE", "TIMED_OUT", "ERROR")]
        return RED + "❌" + RESET, f"{', '.join(failed[:2])}"
    if conclusions and all(c in ("SUCCESS", "NEUTRAL", "SKIPPED") for c in conclusions):
        return GREEN + "✅" + RESET, ""
    return DIM + "?" + RESET, ""


def mergeable_label(mergeable: str) -> str:
    if mergeable == "MERGEABLE":
        return GREEN + "up-to-date" + RESET
    if mergeable == "CONFLICTING":
        return RED + "konflikt" + RESET
    return YELLOW + "utdatert" + RESET


def fetch_dependabot_prs(org: str, name: str) -> list:
    result = run([
        "gh", "pr", "list",
        "--repo", f"{org}/{name}",
        "--author", "app/dependabot",
        "--state", "open",
        "--json", "number,title,headRefName,statusCheckRollup,mergeable,url",
        "--limit", "20",
    ])
    if result.returncode != 0:
        return []
    try:
        prs = json.loads(result.stdout)
        return sorted(prs, key=lambda p: p["number"])
    except json.JSONDecodeError:
        return []


def main():
    repos = parse_repos()
    print(f"\n{BOLD}Dependabot PRer{RESET}\n")

    total = 0
    for repo in repos:
        name = repo["name"]
        org  = repo.get("org", "navikt")
        prs  = fetch_dependabot_prs(org, name)
        if not prs:
            continue

        total += len(prs)
        repo_url = f"https://github.com/{org}/{name}"
        print(f"  {link(repo_url, name, BOLD)}  {DIM}({len(prs)} PR{'er' if len(prs) > 1 else ''}){RESET}")

        for pr in prs:
            ci_icon, ci_detail = ci_status(pr.get("statusCheckRollup", []))
            m_label = mergeable_label(pr.get("mergeable", "UNKNOWN"))
            bump    = detect_bump_type(pr)
            blabel  = bump_label(bump)
            number  = f"{DIM}#{pr['number']}{RESET}"
            title   = pr["title"][:55] + ("…" if len(pr["title"]) > 55 else "")
            detail  = f"  {DIM}{ci_detail}{RESET}" if ci_detail else ""

            print(f"    {ci_icon} {blabel:<25}  {number}  {title}")
            print(f"       {m_label}{detail}")
            print(f"       {link(pr['url'])}")

        print()

    if total == 0:
        print(f"  {DIM}Ingen åpne Dependabot-PRer{RESET}\n")
    else:
        print(f"  {total} åpen(e) Dependabot-PR(er) totalt\n")


if __name__ == "__main__":
    main()
