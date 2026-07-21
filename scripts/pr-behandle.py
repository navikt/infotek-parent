#!/usr/bin/env python3
"""
Interaktiv PR-behandler på tvers av alle managed repos.

Bruk:
  python3 scripts/pr-behandle.py              # alle åpne PRer (ekskl. Dependabot)
  python3 scripts/pr-behandle.py --alle        # alle åpne PRer inkl. Dependabot
  python3 scripts/pr-behandle.py --dependabot  # kun Dependabot-PRer
  python3 scripts/pr-behandle.py --mine        # kun egne PRer
  python3 scripts/pr-behandle.py --dry-run     # vis hva som ville skjedd

Valg per PR:
  [a] Godkjenn + auto-merge
  [m] Merge
  [u] Update-branch
  [r] Rerun CI
  [v] Åpne i nettleser
  [d] Se diff i nettleser  (kun ved trunkert diff)
  [s] Skip
"""

import json
import os
import re
import subprocess
import sys
import webbrowser
from pathlib import Path

REPOS_FILE  = Path(__file__).parent.parent / "repos.yaml"
CONFIG_FILE = Path(__file__).parent.parent / "config.json"

DEPENDABOT_MODE = "--dependabot" in sys.argv
ONLY_MINE       = "--mine" in sys.argv
ALL_MODE        = "--alle" in sys.argv
DRY_RUN         = "--dry-run" in sys.argv

def _load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

_cfg = _load_config().get("pr", {})

DIFF_MAX_LINES         = _cfg.get("diff_max_lines", 40)
MERGE_STRATEGY         = _cfg.get("merge_strategy", "squash")
DELETE_BRANCH          = _cfg.get("delete_branch_on_merge", True)
PR_LIST_LIMIT          = str(_cfg.get("pr_list_limit", 20))
RUN_LIST_LIMIT         = str(_cfg.get("run_list_limit", 5))
SKIP_REPOS             = set(_cfg.get("skip_repos", []))
DEPENDABOT_SKIP_REPOS  = set(_cfg.get("dependabot_skip_repos", []))

def _merge_flags(number: int, repo_full: str) -> list[str]:
    cmd = ["gh", "pr", "merge", str(number), "--repo", repo_full, "--auto"]
    cmd += [f"--{MERGE_STRATEGY}"]
    if DELETE_BRANCH:
        cmd += ["--delete-branch"]
    return cmd

BOLD    = "\033[1m"
GREEN   = "\033[32m"
RED     = "\033[31m"
YELLOW  = "\033[33m"
CYAN    = "\033[36m"
MAGENTA = "\033[35m"
DIM     = "\033[2m"
RESET   = "\033[0m"

def supports_osc8() -> bool:
    term = os.environ.get("TERM_PROGRAM", "")
    if term in {"iTerm.app", "WarpTerminal", "WezTerm", "vscode", "Hyper"}:
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
            if current.get("name") and current.get("managed", True):
                name = current["name"]
                if not (DEPENDABOT_MODE and name in DEPENDABOT_SKIP_REPOS):
                    if name not in SKIP_REPOS:
                        repos.append(current)
            current = {"name": stripped.split(":", 1)[1].strip(), "managed": True}
        elif ":" in stripped:
            key, _, val = stripped.partition(":")
            key, val = key.strip(), val.strip()
            if key == "org":
                current["org"] = val
            elif key == "managed":
                current["managed"] = val.lower() != "false"
    if current.get("name") and current.get("managed", True):
        name = current["name"]
        if not (DEPENDABOT_MODE and name in DEPENDABOT_SKIP_REPOS):
            if name not in SKIP_REPOS:
                repos.append(current)
    return repos


def prompt(msg: str) -> str:
    print(msg, end="", flush=True)
    try:
        return input().strip().lower()
    except EOFError:
        print()
        return "s"


def show_cmd(args: list):
    print(f"     {DIM}$ {' '.join(args)}{RESET}")


def pr_state(pr: dict) -> str:
    checks      = pr.get("statusCheckRollup", [])
    mergeable   = pr.get("mergeable", "UNKNOWN")
    statuses    = {c.get("status") for c in checks}
    conclusions = {c.get("conclusion") for c in checks if c.get("conclusion")}
    if "IN_PROGRESS" in statuses or "QUEUED" in statuses or "WAITING" in statuses:
        return "running"
    if "FAILURE" in conclusions or "TIMED_OUT" in conclusions or "ERROR" in conclusions:
        return "failed"
    all_ok = not checks or all(c in ("SUCCESS", "NEUTRAL", "SKIPPED") for c in conclusions)
    if all_ok and mergeable == "MERGEABLE":
        return "green"
    if mergeable != "MERGEABLE":
        return "behind"
    return "unknown"


def state_icon(state: str) -> str:
    return {
        "green":      GREEN  + "✅" + RESET,
        "running":    YELLOW + "⏳" + RESET,
        "failed":     RED    + "❌" + RESET,
        "behind":     CYAN   + "🔄" + RESET,
        "waiting":    DIM    + "⏸"  + RESET,
        "auto_merge": CYAN   + "⚙"  + RESET,
        "unknown":    DIM    + "?"  + RESET,
    }.get(state, DIM + "?" + RESET)


STATE_HINT = {
    "green":      GREEN  + "klar til merge"         + RESET,
    "behind":     CYAN   + "trenger update-branch"  + RESET,
    "running":    YELLOW + "CI kjører"               + RESET,
    "failed":     RED    + "CI feilet"               + RESET,
    "waiting":    DIM    + "venter på auto-merge"    + RESET,
    "auto_merge": CYAN   + "auto-merge aktivert ⚙"  + RESET,
    "unknown":    DIM    + "ukjent"                  + RESET,
}


def detect_bump_type(pr: dict) -> str:
    branch = pr.get("headRefName", "").lower()
    if "-major" in branch:
        return "MAJOR"
    if "-minor" in branch:
        return "minor"
    if "-patch" in branch:
        return "patch"
    title = pr.get("title", "")
    m = re.search(r"from\s+(\d+)\.\S+\s+to\s+(\d+)\.", title, re.IGNORECASE)
    if m and int(m.group(2)) > int(m.group(1)):
        return "MAJOR"
    return "minor"


def bump_label(bump: str) -> str:
    if bump == "MAJOR":
        return MAGENTA + BOLD + "MAJOR" + RESET
    if bump == "minor":
        return CYAN + "minor" + RESET
    return DIM + "patch" + RESET


def failed_check_names(pr: dict) -> list[str]:
    checks = pr.get("statusCheckRollup", [])
    return [
        c.get("name", "ukjent")
        for c in checks
        if c.get("conclusion") in ("FAILURE", "TIMED_OUT", "ERROR")
    ]


def show_diff(org: str, name: str, pr_number: int) -> bool:
    """Vis trunkert diff. Returnerer True hvis trunkert."""
    result = run(["gh", "pr", "diff", str(pr_number), "--repo", f"{org}/{name}"])
    if result.returncode != 0 or not result.stdout.strip():
        print(f"     {DIM}Ingen diff tilgjengelig{RESET}")
        return False
    lines  = result.stdout.splitlines()
    shown  = lines[:DIFF_MAX_LINES]
    hidden = len(lines) - DIFF_MAX_LINES
    for line in shown:
        if line.startswith("+") and not line.startswith("+++"):
            print(f"  {GREEN}{line}{RESET}")
        elif line.startswith("-") and not line.startswith("---"):
            print(f"  {RED}{line}{RESET}")
        elif line.startswith("@@"):
            print(f"  {CYAN}{line}{RESET}")
        else:
            print(f"  {DIM}{line}{RESET}")
    if hidden > 0:
        print(f"  {DIM}… +{hidden} linjer skjult{RESET}")
        return True
    return False


def find_latest_failed_run_id(org: str, name: str, branch: str) -> str | None:
    result = run([
        "gh", "run", "list", "--repo", f"{org}/{name}",
        "--branch", branch,
        "--json", "databaseId,conclusion",
        "--limit", RUN_LIST_LIMIT,
    ])
    if result.returncode != 0:
        return None
    try:
        runs = json.loads(result.stdout)
        for r in runs:
            if r.get("conclusion") in ("failure", "timed_out"):
                return str(r["databaseId"])
        return str(runs[0]["databaseId"]) if runs else None
    except (json.JSONDecodeError, IndexError):
        return None


def fetch_prs(org: str, name: str) -> tuple[list, bool]:
    """Returnerer (prs, has_more) der has_more=True betyr flere enn limit."""
    fetch_limit = str(int(PR_LIST_LIMIT) + 1)
    args = [
        "gh", "pr", "list",
        "--repo", f"{org}/{name}",
        "--state", "open",
        "--limit", fetch_limit,
        "--json", "number,title,headRefName,statusCheckRollup,author,isDraft,url,mergeable,reviewDecision,autoMergeRequest",
    ]
    if DEPENDABOT_MODE:
        args += ["--author", "app/dependabot"]
    elif ONLY_MINE:
        args += ["--author", "@me"]
    result = run(args)
    if result.returncode != 0:
        return [], False
    try:
        prs = json.loads(result.stdout)
        if not DEPENDABOT_MODE and not ALL_MODE:
            prs = [p for p in prs if p.get("author", {}).get("login", "") != "app/dependabot"]
        prs = sorted(prs, key=lambda p: p["number"])
        has_more = len(prs) > int(PR_LIST_LIMIT)
        return prs[:int(PR_LIST_LIMIT)], has_more
    except json.JSONDecodeError:
        return [], False


def handle_pr(org: str, name: str, pr: dict, state: str, counts: dict, bump: str = None):
    repo_full       = f"{org}/{name}"
    number          = pr["number"]
    title           = pr["title"][:60] + ("…" if len(pr["title"]) > 60 else "")
    pr_url          = pr["url"]
    review_decision = pr.get("reviewDecision", "")
    needs_approval  = review_decision not in ("APPROVED", "")
    actual_state    = pr_state(pr)

    # Vis header
    if bump:
        print(f"\n  {state_icon(state)} {bump_label(bump)}  {BOLD}{name}{RESET}  {DIM}#{number}{RESET}  {title}")
    else:
        draft = f"{DIM}[draft]{RESET} " if pr.get("isDraft") else ""
        author = pr.get("author", {}).get("login", "")
        author_str = f"  {DIM}{author}{RESET}" if author else ""
        conflict = f"  {RED}⚡ merge-konflikt{RESET}" if pr.get("mergeable") == "CONFLICTING" else ""
        print(f"\n  {state_icon(state)} {BOLD}{name}{RESET}  {DIM}#{number}{RESET}  {draft}{title}{conflict}{author_str}")

    status_parts = []
    hint = STATE_HINT.get(state, "")
    if hint:
        status_parts.append(hint)
    if needs_approval and state in ("green",):
        status_parts.append(YELLOW + "⚠️  trenger godkjenning" + RESET)
    if status_parts:
        print(f"     Status: {' · '.join(status_parts)}")
    if state == "failed":
        failed = failed_check_names(pr)
        if failed:
            print(f"     {RED}Feilet: {', '.join(failed)}{RESET}")
    print(f"     {link(pr_url)}")

    diff_truncated = False
    print(f"\n     {DIM}Diff — {pr['title'][:70]}{RESET}\n")
    diff_truncated = show_diff(org, name, number)
    print()

    # Begrensede valg for waiting/auto_merge
    if state in ("waiting", "auto_merge"):
        if state == "auto_merge":
            print(f"     {CYAN}⚙  Auto-merge er aktivert — venter på at GitHub merger.{RESET}")
        else:
            print(f"     {YELLOW}⏸  Venter — en annen PR i dette repoet har aktiv auto-merge.{RESET}")
        print(f"     {DIM}Merge/approve ikke tilgjengelig.{RESET}\n")
        is_behind = actual_state == "behind"
        options = ["[v] Åpne", "[r] Rerun CI", "[s] Skip"]
        if is_behind:
            options.insert(0, "[u] Update-branch")
        if diff_truncated:
            options.insert(0, "[d] Diff i nettleser")
        while True:
            choice = prompt(f"     {'  '.join(options)}  > ")
            if choice == "d":
                webbrowser.open(pr_url); continue
            if choice == "v":
                webbrowser.open(pr_url); counts["skippet"] += 1; break
            if choice == "u" and is_behind:
                cmd = ["gh", "pr", "update-branch", str(number), "--repo", repo_full]
                show_cmd(cmd)
                if not DRY_RUN:
                    r = run(cmd)
                    if r.returncode == 0:
                        print(f"     {CYAN}→ update-branch sendt ✓{RESET}")
                        counts["oppdatert"] += 1
                    else:
                        print(f"     {RED}→ feilet: {r.stderr.strip()}{RESET}")
                else:
                    print(f"     {DIM}→ ville kjørt update-branch{RESET}")
                    counts["oppdatert"] += 1
                break
            if choice == "r":
                run_id = find_latest_failed_run_id(org, name, pr["headRefName"])
                if not run_id:
                    print(f"     {YELLOW}⚠️  Fant ingen failed run{RESET}")
                else:
                    cmd = ["gh", "run", "rerun", run_id, "--failed", "--repo", repo_full]
                    show_cmd(cmd)
                    if not DRY_RUN:
                        r = run(cmd)
                        if r.returncode == 0:
                            print(f"     {GREEN}→ rerun startet ✓{RESET}")
                            counts["rerun"] += 1
                        else:
                            print(f"     {RED}→ rerun feilet: {r.stderr.strip()}{RESET}")
                    else:
                        print(f"     {DIM}→ ville rerunnet{RESET}")
                        counts["rerun"] += 1
                break
            counts["skippet"] += 1; break
        return

    is_dependabot = pr.get("author", {}).get("login", "") == "app/dependabot"

    # Normale valg
    options = ["[s] Skip"]
    if diff_truncated:
        options.insert(0, "[d] Diff i nettleser")
    if state in ("green", "running"):
        options.insert(0, "[m] Merge")
    if needs_approval and state in ("green", "behind", "unknown", "running"):
        options.insert(0, "[a] Godkjenn")
        if is_dependabot:
            options.insert(0, "[b] Godkjenn + auto-merge")
    if state == "behind":
        options.insert(0, "[u] Update-branch")
    if state == "failed":
        options.insert(0, "[r] Rerun CI")
        options.insert(0, "[p] Artifakter")
    options.insert(-1, "[v] Åpne")

    while True:
        choice = prompt(f"     {'  '.join(options)}  > ")

        if choice == "p" and state == "failed":
            pw_cmd = ["python3", str(Path(__file__).parent / "vis-artifakt.py"),
                      "--repo", repo_full, "--run", find_latest_failed_run_id(org, name, pr["headRefName"]) or ""]
            if not pw_cmd[-1]:
                print(f"     {YELLOW}⚠️  Fant ingen failed run{RESET}")
            else:
                show_cmd(pw_cmd)
                subprocess.run(pw_cmd, check=False)
            break

        if choice == "d":
            webbrowser.open(pr_url); continue

        if choice == "v":
            webbrowser.open(pr_url); counts["skippet"] += 1; break

        if choice == "s":
            print(f"     {DIM}→ skippet{RESET}"); counts["skippet"] += 1; break

        if choice == "a" and needs_approval and state in ("green", "behind", "unknown", "running"):
            if DRY_RUN:
                print(f"     {DIM}→ ville godkjent{RESET}")
            else:
                approve_cmd = ["gh", "pr", "review", str(number), "--approve", "--repo", repo_full]
                show_cmd(approve_cmd)
                ar = run(approve_cmd)
                if ar.returncode != 0:
                    print(f"     {RED}→ godkjenning feilet: {ar.stderr.strip()}{RESET}"); continue
                print(f"     {GREEN}→ godkjent ✓{RESET}")
            counts["godkjent"] = counts.get("godkjent", 0) + 1
            break

        if choice == "b" and is_dependabot and needs_approval and state in ("green", "behind", "unknown", "running"):
            if DRY_RUN:
                print(f"     {DIM}→ ville godkjent + aktivert auto-merge{RESET}")
            else:
                approve_cmd = ["gh", "pr", "review", str(number), "--approve", "--repo", repo_full]
                show_cmd(approve_cmd)
                ar = run(approve_cmd)
                if ar.returncode != 0:
                    print(f"     {RED}→ godkjenning feilet: {ar.stderr.strip()}{RESET}"); continue
                print(f"     {GREEN}→ godkjent ✓{RESET}")
                merge_cmd = _merge_flags(number, repo_full)
                show_cmd(merge_cmd)
                mr = run(merge_cmd)
                if mr.returncode == 0:
                    print(f"     {GREEN}→ auto-merge aktivert ✓{RESET}")
                else:
                    print(f"     {RED}→ auto-merge feilet: {mr.stderr.strip()}{RESET}"); continue
            counts["merget"] += 1
            if bump:
                counts[f"merget_{bump.lower()}"] = counts.get(f"merget_{bump.lower()}", 0) + 1
            break

        if choice == "m" and state in ("green", "running"):
            merge_cmd = _merge_flags(number, repo_full)
            show_cmd(merge_cmd)
            if DRY_RUN:
                print(f"     {DIM}→ ville merget #{number}{RESET}")
            else:
                mr = run(merge_cmd)
                if mr.returncode == 0:
                    print(f"     {GREEN}→ auto-merge aktivert ✓{RESET}")
                else:
                    print(f"     {RED}→ feilet: {mr.stderr.strip()}{RESET}"); continue
            counts["merget"] += 1
            if bump:
                counts[f"merget_{bump.lower()}"] = counts.get(f"merget_{bump.lower()}", 0) + 1
            break

        if choice == "u" and state == "behind":
            cmd = ["gh", "pr", "update-branch", str(number), "--repo", repo_full]
            show_cmd(cmd)
            if DRY_RUN:
                print(f"     {DIM}→ ville kjørt update-branch{RESET}")
            else:
                r = run(cmd)
                if r.returncode == 0:
                    print(f"     {CYAN}→ update-branch sendt ✓{RESET}")
                else:
                    print(f"     {RED}→ feilet: {r.stderr.strip()}{RESET}"); continue
            counts["oppdatert"] += 1; break

        if choice == "r" and state == "failed":
            run_id = find_latest_failed_run_id(org, name, pr["headRefName"])
            if not run_id:
                print(f"     {YELLOW}⚠️  Fant ingen failed run{RESET}"); continue
            cmd = ["gh", "run", "rerun", run_id, "--failed", "--repo", repo_full]
            show_cmd(cmd)
            if DRY_RUN:
                print(f"     {DIM}→ ville rerunnet run {run_id}{RESET}")
            else:
                r = run(cmd)
                if r.returncode == 0:
                    print(f"     {GREEN}→ rerun startet ✓{RESET}")
                else:
                    print(f"     {RED}→ rerun feilet: {r.stderr.strip()}{RESET}"); continue
            counts["rerun"] += 1; break

        print(f"     {YELLOW}Ugyldig valg — prøv igjen{RESET}")


def fetch_all(repos: list):
    """Hent PRer for alle repos. Returnerer (repo_groups, active_groups)."""
    repo_groups = []
    total = len(repos)
    for i, repo in enumerate(repos, 1):
        name = repo["name"]
        org  = repo.get("org", "navikt")
        print(f"\r{DIM}Henter {name[:35].ljust(35)} ({i:>2}/{total})…{RESET}", end="", flush=True)
        prs, has_more = fetch_prs(org, name)
        if DEPENDABOT_MODE:
            auto_merge_prs = [p for p in prs if p.get("autoMergeRequest")]
            actionable_prs = [p for p in prs if not p.get("autoMergeRequest")]
            entries = []
            for pr in actionable_prs:
                state = "waiting" if auto_merge_prs else pr_state(pr)
                entries.append({"org": org, "name": name, "pr": pr, "state": state, "bump": detect_bump_type(pr)})
            for pr in auto_merge_prs:
                entries.append({"org": org, "name": name, "pr": pr, "state": "auto_merge", "bump": detect_bump_type(pr)})
            repo_groups.append({"org": org, "name": name, "entries": entries, "blocked": bool(auto_merge_prs), "truncated": has_more})
        else:
            entries = []
            for pr in prs:
                entries.append({"org": org, "name": name, "pr": pr, "state": pr_state(pr)})
            repo_groups.append({"org": org, "name": name, "entries": entries, "truncated": has_more})
    print(f"\r{' ' * 60}\r", end="", flush=True)
    active_groups = [g for g in repo_groups if g["entries"]]
    return repo_groups, active_groups


def print_overview_dependabot(repo_groups: list, total_prs: int, prefix: str):
    print(f"{BOLD}{prefix}Dependabot PRer — {len(repo_groups)} repos, {total_prs} PRer totalt{RESET}\n")
    for i, group in enumerate(repo_groups, 1):
        entries = group["entries"]
        if entries:
            print(f"  {i:>2}  {BOLD}{group['name']}{RESET}")
            for e in entries:
                pr    = e["pr"]
                title = pr["title"][:50] + ("…" if len(pr["title"]) > 50 else "")
                approval = ""
                if pr.get("reviewDecision", "") not in ("APPROVED", "") and e["state"] == "green":
                    approval = f"  {YELLOW}· godkjenning mangler{RESET}"
                failed = ""
                if e["state"] == "failed":
                    names = failed_check_names(pr)
                    if names:
                        failed = f"  {RED}→ {', '.join(names)}{RESET}"
                print(f"       {bump_label(e['bump'])}  {DIM}#{pr['number']}{RESET}  {title}  {STATE_HINT.get(e['state'], '')}{approval}{failed}")
            if group.get("truncated"):
                print(f"       {DIM}… flere PRer — åpne GitHub for full liste{RESET}")
        else:
            print(f"  {i:>2}  {DIM}{group['name']}  ingen PRer{RESET}")
    print()


def pr_status_hints(pr: dict, state: str) -> str:
    """Bygg en kompakt statusstreng for standard-modus."""
    parts = []
    hint = STATE_HINT.get(state)
    if hint:
        parts.append(hint)
    review = pr.get("reviewDecision", "")
    if review == "APPROVED":
        parts.append(GREEN + "✓ godkjent" + RESET)
    elif review == "CHANGES_REQUESTED":
        parts.append(RED + "✗ endringer forespurt" + RESET)
    elif review == "REVIEW_REQUIRED":
        parts.append(YELLOW + "· trenger godkjenning" + RESET)
    if pr.get("mergeable") == "CONFLICTING":
        parts.append(RED + "⚡ merge-konflikt" + RESET)
    if state == "failed":
        failed = failed_check_names(pr)
        if failed:
            parts.append(RED + "→ " + ", ".join(failed) + RESET)
    return "  " + "  ".join(parts) if parts else ""


def print_overview_standard(repo_groups: list, active_groups: list, total_prs: int, filter_info: str):
    print(f"\n{BOLD}Åpne PRer{filter_info}{RESET}\n")
    total_failing = 0
    active_idx = 1
    for group in repo_groups:
        org  = group["org"]
        name = group["name"]
        repo_url = f"https://github.com/{org}/{name}"
        if not group["entries"]:
            print(f"  {DIM}    {name}  ingen PRer{RESET}")
            continue
        num_str = f"{BOLD}{active_idx:>2}{RESET}"
        active_idx += 1
        print(f"  {num_str}  {link(repo_url, name, BOLD)}")
        for e in group["entries"]:
            pr = e["pr"]
            if e["state"] == "failed":
                total_failing += 1
            draft   = f"{DIM}[draft]{RESET} " if pr.get("isDraft") else ""
            number  = f"{DIM}#{pr['number']}{RESET}"
            title   = pr["title"][:50] + ("…" if len(pr["title"]) > 50 else "")
            author  = pr.get("author", {}).get("login", "")
            author_str = f"  {DIM}@{author}{RESET}" if author else ""
            branch  = f"{CYAN}{pr['headRefName']}{RESET}"
            hints   = pr_status_hints(pr, e["state"])
            print(f"       {state_icon(e['state'])} {number} {draft}{title}{author_str}")
            print(f"          {branch}{hints}")
            print(f"          {link(pr['url'])}")
        if group.get("truncated"):
            print(f"       {DIM}… flere PRer — åpne {link(repo_url)} for full liste{RESET}")
        print()
    if total_prs == 0:
        print(f"  {DIM}Ingen åpne PRer{RESET}\n")
    else:
        summary = f"  {total_prs} åpen(e) PR(er)"
        if total_failing:
            summary += f"  {RED}· {total_failing} feiler{RESET}"
        print(summary + "\n")


def print_summary(counts: dict):
    print()
    parts = []
    major_merget = counts.get("merget_major", 0)
    minor_merget = counts.get("merget", 0) - major_merget
    if counts.get("godkjent"):
        parts.append(f"{GREEN}{counts['godkjent']} godkjent{RESET}")
    if counts.get("merget"):
        detail = []
        if major_merget: detail.append(f"{major_merget} MAJOR")
        if minor_merget: detail.append(f"{minor_merget} minor/patch")
        detail_str = f" ({', '.join(detail)})" if detail else ""
        parts.append(f"{GREEN}{counts['merget']} merget{detail_str}{RESET}")
    if counts.get("oppdatert"):
        parts.append(f"{CYAN}{counts['oppdatert']} update-branch{RESET}")
    if counts.get("rerun"):
        parts.append(f"{YELLOW}{counts['rerun']} rerun startet{RESET}")
    if counts.get("skippet"):
        parts.append(f"{DIM}{counts['skippet']} skippet{RESET}")
    print(f"  {' · '.join(parts) if parts else DIM + 'Ingen endringer' + RESET}\n")


def main_dependabot(repos: list):
    prefix = f"{YELLOW}[DRY-RUN] {RESET}" if DRY_RUN else ""
    repo_groups, active_groups = fetch_all(repos)

    if not active_groups:
        print(f"  {DIM}Ingen åpne Dependabot-PRer — alt er ferdig! 🎉{RESET}\n")
        return

    counts = {"merget": 0, "oppdatert": 0, "rerun": 0, "skippet": 0}

    while True:
        total_prs = sum(len(g["entries"]) for g in repo_groups)
        print_overview_dependabot(repo_groups, total_prs, prefix)

        print(f"{DIM}Velg repos (f.eks. 1,3 / alle / Enter=alle / q=avslutt):{RESET} ", end="", flush=True)
        try:
            raw = input().strip().lower()
        except EOFError:
            break
        if raw == "q":
            break
        if raw in ("", "alle"):
            selected = [repo_groups.index(g) for g in active_groups]
        else:
            selected = []
            for part in raw.split(","):
                try:
                    idx = int(part.strip()) - 1
                    if 0 <= idx < len(repo_groups) and repo_groups[idx]["entries"]:
                        selected.append(idx)
                except ValueError:
                    pass
        if not selected:
            print(f"\n  {DIM}Ingen repos valgt.{RESET}\n"); continue

        treated = set()
        for idx in selected:
            group   = repo_groups[idx]
            entries = group["entries"]
            if group.get("blocked"):
                auto_nums = ", ".join(f"#{e['pr']['number']}" for e in entries if e["state"] == "auto_merge")
                print(f"  {DIM}⏸  {auto_nums} har aktiv auto-merge — andre PRer har begrensede valg{RESET}\n")
            print(f"  {BOLD}{group['name']}{RESET}  {DIM}({len(entries)} PRer){RESET}\n")
            for j, e in enumerate(entries, 1):
                pr    = e["pr"]
                title = pr["title"][:55] + ("…" if len(pr["title"]) > 55 else "")
                approval = ""
                if pr.get("reviewDecision", "") not in ("APPROVED", "") and e["state"] == "green":
                    approval = f"  {YELLOW}· godkjenning mangler{RESET}"
                print(f"   {BOLD}{j}{RESET}  {bump_label(e['bump'])}  {DIM}#{pr['number']}{RESET}  {title}  {STATE_HINT.get(e['state'], '')}{approval}")
            print()
            print(f"  {DIM}Hvilken PR? (Enter=skip, q=avslutt):{RESET} ", end="", flush=True)
            try:
                pick = input().strip().lower()
            except EOFError:
                break
            if not pick or pick == "q":
                print(f"  {DIM}→ skippet{RESET}\n"); counts["skippet"] += 1; continue
            try:
                pr_idx = int(pick) - 1
                if pr_idx < 0 or pr_idx >= len(entries):
                    raise ValueError
            except ValueError:
                print(f"  {YELLOW}Ugyldig valg — skippet.{RESET}\n"); counts["skippet"] += 1; continue

            chosen = entries[pr_idx]
            before = (counts["merget"], counts["oppdatert"], counts["rerun"])
            handle_pr(group["org"], group["name"], chosen["pr"], chosen["state"], counts, bump=chosen["bump"])
            if (counts["merget"], counts["oppdatert"], counts["rerun"]) != before:
                treated.add(group["name"])

        # Re-hent behandlede repos
        for repo in repos:
            if repo["name"] not in treated:
                continue
            org  = repo.get("org", "navikt")
            name = repo["name"]
            print(f"\r{DIM}Oppdaterer {name[:35].ljust(35)}…{RESET}", end="", flush=True)
            prs, has_more = fetch_prs(org, name)
            auto_merge_prs = [p for p in prs if p.get("autoMergeRequest")]
            actionable_prs = [p for p in prs if not p.get("autoMergeRequest")]
            entries = []
            for pr in actionable_prs:
                state = "waiting" if auto_merge_prs else pr_state(pr)
                entries.append({"org": org, "name": name, "pr": pr, "state": state, "bump": detect_bump_type(pr)})
            for pr in auto_merge_prs:
                entries.append({"org": org, "name": name, "pr": pr, "state": "auto_merge", "bump": detect_bump_type(pr)})
            for g in repo_groups:
                if g["name"] == name:
                    g["entries"] = entries
                    g["blocked"] = bool(auto_merge_prs)
                    g["truncated"] = has_more
                    break
        if treated:
            print(f"\r{' ' * 60}\r", end="", flush=True)

        active_groups = [g for g in repo_groups if g["entries"]]
        if not active_groups:
            print(f"  {DIM}Ingen åpne Dependabot-PRer igjen — alt er ferdig! 🎉{RESET}\n")
            break

    print_summary(counts)


def main_standard(repos: list):
    filter_info = " (kun mine)" if ONLY_MINE else (" (alle inkl. dependabot)" if ALL_MODE else "")
    repo_groups, active_groups = fetch_all(repos)
    total_prs = sum(len(g["entries"]) for g in repo_groups)

    print_overview_standard(repo_groups, active_groups, total_prs, filter_info)

    if not active_groups:
        return

    counts = {"merget": 0, "oppdatert": 0, "rerun": 0, "skippet": 0}
    treated = set()

    while True:
        print(f"{DIM}Velg repo (f.eks. 1,3 / Enter=alle / q=avslutt):{RESET} ", end="", flush=True)
        try:
            raw = input().strip().lower()
        except EOFError:
            break
        if raw == "q":
            break
        if raw == "":
            selected = list(range(len(active_groups)))
        else:
            selected = []
            for part in raw.split(","):
                try:
                    idx = int(part.strip()) - 1
                    if 0 <= idx < len(active_groups):
                        selected.append(idx)
                except ValueError:
                    pass
        if not selected:
            print(f"\n  {DIM}Ingen repos valgt.{RESET}\n"); continue

        for idx in selected:
            group   = active_groups[idx]
            entries = group["entries"]
            print(f"\n  {BOLD}{group['name']}{RESET}  {DIM}({len(entries)} PRer){RESET}\n")
            for j, e in enumerate(entries, 1):
                pr    = e["pr"]
                draft = f"{DIM}[draft]{RESET} " if pr.get("isDraft") else ""
                title = pr["title"][:50] + ("…" if len(pr["title"]) > 50 else "")
                hints = pr_status_hints(pr, e["state"])
                print(f"   {BOLD}{j}{RESET}  {state_icon(e['state'])}  {DIM}#{pr['number']}{RESET}  {draft}{title}{hints}")
            print()
            print(f"  {DIM}Hvilken PR? (Enter=skip, q=avslutt):{RESET} ", end="", flush=True)
            try:
                pick = input().strip().lower()
            except EOFError:
                break
            if not pick or pick == "q":
                print(f"  {DIM}→ skippet{RESET}\n"); counts["skippet"] += 1; continue
            try:
                pr_idx = int(pick) - 1
                if pr_idx < 0 or pr_idx >= len(entries):
                    raise ValueError
            except ValueError:
                print(f"  {YELLOW}Ugyldig valg — skippet.{RESET}\n"); counts["skippet"] += 1; continue

            before = (counts["merget"], counts["oppdatert"], counts["rerun"])
            chosen = entries[pr_idx]
            handle_pr(group["org"], group["name"], chosen["pr"], chosen["state"], counts)
            if (counts["merget"], counts["oppdatert"], counts["rerun"]) != before:
                treated.add(group["name"])

        # Re-hent behandlede repos
        for repo in repos:
            if repo["name"] not in treated:
                continue
            org  = repo.get("org", "navikt")
            name = repo["name"]
            print(f"\r{DIM}Oppdaterer {name[:35].ljust(35)}…{RESET}", end="", flush=True)
            prs, has_more = fetch_prs(org, name)
            entries = [{"org": org, "name": name, "pr": p, "state": pr_state(p)} for p in prs]
            for g in repo_groups:
                if g["name"] == name:
                    g["entries"] = entries
                    g["truncated"] = has_more
                    break
        if treated:
            print(f"\r{' ' * 60}\r", end="", flush=True)
            treated.clear()

        active_groups = [g for g in repo_groups if g["entries"]]
        if not active_groups:
            print(f"  {DIM}Ingen åpne PRer igjen — alt er ferdig! 🎉{RESET}\n")
            break

        total_prs = sum(len(g["entries"]) for g in repo_groups)
        print_overview_standard(repo_groups, active_groups, total_prs, filter_info)

    print_summary(counts)


def main():
    repos = parse_repos()
    if not repos:
        print("Ingen managed repos funnet i repos.yaml")
        return
    if DEPENDABOT_MODE:
        main_dependabot(repos)
    else:
        main_standard(repos)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Avbrutt.{RESET}\n")
        sys.exit(0)
