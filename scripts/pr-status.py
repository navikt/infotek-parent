#!/usr/bin/env python3
"""
Viser åpne PRer og CI-tilstand for alle managed repos.

Bruk: python3 scripts/pr-status.py [--mine]
  --mine  Vis kun PRer opprettet av deg
"""

import json
import os
import subprocess
import sys
from pathlib import Path

REPOS_FILE = Path(__file__).parent.parent / "repos.yaml"

ONLY_MINE = "--mine" in sys.argv

BOLD  = "\033[1m"
GREEN = "\033[32m"
RED   = "\033[31m"
YELLOW = "\033[33m"
CYAN  = "\033[36m"
DIM   = "\033[2m"
RESET = "\033[0m"


def supports_osc8() -> bool:
    """Returner True dersom terminalen støtter OSC 8 hyperlenker."""
    term_program = os.environ.get("TERM_PROGRAM", "")
    supported = {"iTerm.app", "WarpTerminal", "WezTerm", "vscode", "Hyper"}
    if term_program in supported:
        return True
    if os.environ.get("VTE_VERSION"):  # GNOME Terminal og andre VTE-baserte
        return True
    if os.environ.get("ALACRITTY_SOCKET") or os.environ.get("ALACRITTY_LOG"):
        return True
    if os.environ.get("TERM") == "xterm-kitty":
        return True
    return False


OSC8_SUPPORTED = supports_osc8()


def link(url: str, text: str = None, style: str = None) -> str:
    """Lag klikkbar lenke. Bruker OSC 8 dersom terminalen støtter det, ellers ren URL."""
    label = text or url
    if OSC8_SUPPORTED:
        inner = f"{style}{label}{RESET}" if style else f"{DIM}{label}{RESET}"
        return f"\033]8;;{url}\007{inner}\033]8;;\007"
    return f"{style}{label}{RESET}" if (style and text) else url


def run(cmd, check=False):
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def parse_repos():
    repos = []
    in_repos = False
    current = {}
    for line in REPOS_FILE.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("repos:"):
            in_repos = True
            continue
        if not in_repos or stripped.startswith("#") or not stripped:
            continue
        if stripped.startswith("- name:"):
            if current.get("name") and current.get("managed", True):
                repos.append(current)
            current = {"name": stripped.split(":", 1)[1].strip(), "managed": True}
        elif ":" in stripped:
            key, _, val = stripped.partition(":")
            val = val.strip()
            if key.strip() == "org":
                current["org"] = val
            elif key.strip() == "managed":
                current["managed"] = val.lower() != "false"
    if current.get("name") and current.get("managed", True):
        repos.append(current)
    return repos


def ci_status(checks: list) -> tuple[str, str]:
    """Returner (ikon, label) basert på check-resultater."""
    if not checks:
        return DIM + "—" + RESET, ""
    statuses = {c.get("status") for c in checks}
    conclusions = {c.get("conclusion") for c in checks if c.get("conclusion")}

    if "IN_PROGRESS" in statuses or "QUEUED" in statuses or "WAITING" in statuses:
        return YELLOW + "⏳" + RESET, "kjører"
    if "FAILURE" in conclusions or "TIMED_OUT" in conclusions or "ERROR" in conclusions:
        failed = [c["name"] for c in checks if c.get("conclusion") in ("FAILURE", "TIMED_OUT", "ERROR")]
        return RED + "❌" + RESET, f"{', '.join(failed[:2])}"
    if conclusions and all(c in ("SUCCESS", "NEUTRAL", "SKIPPED") for c in conclusions):
        return GREEN + "✅" + RESET, ""
    return DIM + "?" + RESET, ""


def fetch_prs(org: str, name: str) -> list:
    args = [
        "gh", "pr", "list",
        "--repo", f"{org}/{name}",
        "--json", "number,title,headRefName,statusCheckRollup,author,isDraft,url,mergeable,isDraft",
        "--limit", "10",
        "--state", "open",
    ]
    if ONLY_MINE:
        args += ["--author", "@me"]
    result = run(args)
    if result.returncode != 0:
        return []
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return []


def main():
    repos = parse_repos()
    if not repos:
        print("Ingen managed repos funnet i repos.yaml")
        return

    filter_info = " (kun mine)" if ONLY_MINE else ""
    print(f"\n{BOLD}Åpne PRer{filter_info}{RESET}\n")

    total_prs = 0
    total_failing = 0

    for repo in repos:
        name = repo["name"]
        org = repo.get("org", "navikt")
        prs = fetch_prs(org, name)
        if not prs:
            continue

        total_prs += len(prs)
        repo_url = f"https://github.com/{org}/{name}"
        print(f"  {link(repo_url, name, BOLD)}")

        for pr in prs:
            icon, detail = ci_status(pr.get("statusCheckRollup", []))
            if RED + "❌" in icon:
                total_failing += 1

            draft = f"{DIM}[draft]{RESET} " if pr.get("isDraft") else ""
            number = f"{DIM}#{pr['number']}{RESET}"
            title = pr["title"][:55] + ("…" if len(pr["title"]) > 55 else "")
            branch = f"{CYAN}{pr['headRefName']}{RESET}"
            detail_str = f"  {DIM}{detail}{RESET}" if detail else ""
            conflict_str = f"  {RED}⚡ merge-konflikt{RESET}" if pr.get("mergeable") == "CONFLICTING" else ""
            url = pr.get("url", "")

            print(f"    {icon} {number} {draft}{title}{conflict_str}")
            print(f"       {branch}{detail_str}")
            print(f"       {link(url)}")

        print()

    if total_prs == 0:
        print(f"  {DIM}Ingen åpne PRer{RESET}\n")
    else:
        summary = f"  {total_prs} åpen(e) PR(er)"
        if total_failing:
            summary += f"  {RED}· {total_failing} feiler{RESET}"
        print(summary + "\n")


if __name__ == "__main__":
    main()
