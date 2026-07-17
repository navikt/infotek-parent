#!/usr/bin/env python3
"""
Interaktiv Dependabot-behandler på tvers av alle managed repos.

Arbeidsflyt:
  1. Kjør: make dependabot-behandle
  2. Oversikt over alle repos vises (repos uten PRer er dimmet)
  3. Velg hvilke repos du vil behandle (Enter=alle med PRer)
  4. Per repo: velg hvilken PR du vil behandle
  5. Per PR: diff vises automatisk, deretter:
       [a] Godkjenn + auto-merge   — approve + sett auto-merge (brukes når godkjenning mangler)
       [m] Merge                   — sett auto-merge direkte (når allerede godkjent)
       [u] Update-branch           — oppdater branch mot main, starter CI på nytt
       [r] Rerun CI                — rerun feilede jobs
       [v] Åpne i nettleser        — åpner PR i nettleser (alltid tilgjengelig)
       [d] Se diff i nettleser     — åpner PR-diff i nettleser (vises kun når diff er trunkert)
       [s] Skip                    — hopp over denne PRen

Kun én PR per repo kan ha aktiv auto-merge om gangen.
PRer som venter tilbyr kun: [u] Update-branch  [v] Åpne  [r] Rerun CI  [s] Skip

Kjør kommandoen gjentatte ganger til alle PRer er merget:
  make dependabot-behandle   →  merge klare + update-branch utdaterte
  (vent på CI)
  make dependabot-behandle   →  neste runde

Repos med dependabot_skip: true i repos.yaml hoppes over.

Bruk: python3 scripts/dependabot-behandle.py [--dry-run]
  --dry-run  Vis hva som ville skjedd uten å gjøre endringer
"""

import json
import os
import re
import subprocess
import sys
import webbrowser
from pathlib import Path

REPOS_FILE = Path(__file__).parent.parent / "repos.yaml"
DRY_RUN = "--dry-run" in sys.argv

BOLD   = "\033[1m"
GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
MAGENTA = "\033[35m"
DIM    = "\033[2m"
RESET  = "\033[0m"

DIFF_MAX_LINES = 40


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


def run(cmd, check=False):
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def parse_repos():
    repos = []
    in_repos = False
    current = {}
    for line in REPOS_FILE.read_text().splitlines():
        stripped = line.strip().split("#")[0].strip()  # fjern inline-kommentarer
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


def detect_bump_type(pr: dict) -> str:
    """Returner 'MAJOR', 'minor' eller 'patch' basert på branch-navn og tittel."""
    branch = pr.get("headRefName", "").lower()
    if "-major" in branch:
        return "MAJOR"
    if "-minor" in branch:
        return "minor"
    if "-patch" in branch:
        return "patch"
    # Heuristikk: "from X to Y" der major-nummer endres
    title = pr.get("title", "")
    m = re.search(r"from\s+(\d+)\.\S+\s+to\s+(\d+)\.", title, re.IGNORECASE)
    if m and int(m.group(2)) > int(m.group(1)):
        return "MAJOR"
    return "minor"


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
        "waiting":    DIM    + "⏸" + RESET,
        "auto_merge": CYAN   + "⚙" + RESET,
        "unknown":    DIM    + "?" + RESET,
    }.get(state, DIM + "?" + RESET)


def bump_label(bump: str) -> str:
    if bump == "MAJOR":
        return MAGENTA + BOLD + "MAJOR" + RESET
    if bump == "minor":
        return CYAN + "minor" + RESET
    return DIM + "patch" + RESET


def fetch_dependabot_prs(org: str, name: str) -> list:
    result = run([
        "gh", "pr", "list",
        "--repo", f"{org}/{name}",
        "--author", "app/dependabot",
        "--state", "open",
        "--json", "number,title,headRefName,statusCheckRollup,mergeable,reviewDecision,url,autoMergeRequest",
        "--limit", "20",
    ])
    if result.returncode != 0:
        return []
    try:
        return sorted(json.loads(result.stdout), key=lambda p: p["number"])
    except json.JSONDecodeError:
        return []


def show_diff(org: str, name: str, pr_number: int) -> bool:
    """Viser trunkert diff. Returnerer True hvis difffen ble trunkert."""
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
        "--limit", "5",
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


def prompt(msg: str) -> str:
    print(msg, end="", flush=True)
    try:
        return input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return "s"


def show_cmd(args: list):
    print(f"     {DIM}$ {' '.join(args)}{RESET}")


def handle_pr(org: str, name: str, pr: dict, state: str, bump: str, counts: dict):
    repo_full      = f"{org}/{name}"
    number         = pr["number"]
    title          = pr["title"][:60] + ("…" if len(pr["title"]) > 60 else "")
    pr_url         = pr["url"]
    review_decision = pr.get("reviewDecision", "")
    needs_approval  = review_decision not in ("APPROVED", "")
    # Underliggende CI/mergeable-state uavhengig av auto_merge/waiting-overlay
    actual_state   = pr_state(pr)

    status_parts = []
    if state == "green":
        status_parts.append(GREEN + "grønn" + RESET)
    elif state == "behind":
        status_parts.append(CYAN + "utdatert" + RESET)
    elif state == "running":
        status_parts.append(YELLOW + "CI kjører" + RESET)
    elif state == "failed":
        status_parts.append(RED + "CI feilet" + RESET)
    elif state in ("waiting", "auto_merge") and actual_state != "green":
        hint = {"behind": CYAN + "utdatert" + RESET, "running": YELLOW + "CI kjører" + RESET,
                "failed": RED + "CI feilet" + RESET}.get(actual_state)
        if hint:
            status_parts.append(hint)
    if needs_approval:
        status_parts.append(YELLOW + "⚠️  trenger godkjenning" + RESET)

    print(f"\n  {state_icon(state)} {bump_label(bump)}  {BOLD}{name}{RESET}  {DIM}#{number}{RESET}  {title}")
    print(f"     Status: {' · '.join(status_parts)}")
    print(f"     {link(pr_url)}")
    print(f"     {DIM}gh pr view --web {number} --repo {repo_full}{RESET}")

    print()
    print(f"     {DIM}Diff — {pr['title'][:70]}{RESET}")
    print()
    diff_truncated = show_diff(org, name, number)
    print()

    # Tilgjengelige valg basert på tilstand
    if state in ("waiting", "auto_merge"):
        if state == "auto_merge":
            print(f"     {CYAN}⚙  Auto-merge er aktivert — venter på at GitHub merger.{RESET}")
        else:
            print(f"     {YELLOW}⏸  Venter — en annen PR i dette repoet har aktiv auto-merge.{RESET}")
        print(f"     {DIM}Merge/approve ikke tilgjengelig.{RESET}\n")
        is_behind = actual_state == "behind"
        options = ["[v] Åpne i nettleser", "[r] Rerun CI", "[s] Skip"]
        if is_behind:
            options.insert(0, "[u] Update-branch")
        if diff_truncated:
            options.insert(0, "[d] Se diff i nettleser")
        while True:
            choice = prompt(f"     {'  '.join(options)}  > ")
            if choice == "d":
                webbrowser.open(pr_url)
                continue
            if choice == "v":
                webbrowser.open(pr_url)
                counts["skippet"] += 1
                break
            if choice == "u" and is_behind:
                update_cmd = ["gh", "pr", "update-branch", str(number), "--repo", repo_full]
                show_cmd(update_cmd)
                result = run(update_cmd)
                if result.returncode == 0:
                    print(f"     {CYAN}→ update-branch sendt ✓{RESET}")
                    counts["oppdatert"] += 1
                else:
                    print(f"     {RED}→ feilet: {result.stderr.strip()}{RESET}")
                break
            if choice == "r":
                run_id = find_latest_failed_run_id(org, name, pr["headRefName"])
                if not run_id:
                    print(f"     {YELLOW}⚠️  Fant ingen failed run for denne branchen{RESET}")
                else:
                    rerun_cmd = ["gh", "run", "rerun", run_id, "--failed", "--repo", repo_full]
                    show_cmd(rerun_cmd)
                    result = run(rerun_cmd)
                    if result.returncode == 0:
                        print(f"     {GREEN}→ rerun startet ✓{RESET}")
                        counts["rerun"] += 1
                    else:
                        print(f"     {RED}→ rerun feilet: {result.stderr.strip()}{RESET}")
                break
            counts["skippet"] += 1
            break
        return

    options = ["[s] Skip"]
    if diff_truncated:
        options.insert(0, "[d] Se diff i nettleser")
    if state in ("green", "running"):
        options.insert(1, "[m] Merge")
    if needs_approval and state in ("green", "behind", "unknown", "running"):
        options.insert(1, "[a] Godkjenn + auto-merge")
    if state == "behind":
        options.insert(1, "[u] Update-branch")
    if state == "failed":
        options.insert(1, "[r] Rerun CI")
    options.insert(-1, "[v] Åpne i nettleser")

    while True:
        choice = prompt(f"     {'  '.join(options)}  > ")

        if choice == "d":
            webbrowser.open(pr_url)
            continue

        if choice == "a" and needs_approval and state in ("green", "behind", "unknown", "running"):
            if DRY_RUN:
                print(f"     {DIM}→ ville godkjent + aktivert auto-merge{RESET}")
                counts["merget"] += 1
                counts[f"merget_{bump.lower()}"] = counts.get(f"merget_{bump.lower()}", 0) + 1
            else:
                approve_cmd = ["gh", "pr", "review", str(number), "--approve", "--repo", repo_full]
                show_cmd(approve_cmd)
                approve = run(approve_cmd)
                if approve.returncode != 0:
                    print(f"     {RED}→ godkjenning feilet: {approve.stderr.strip()}{RESET}")
                    break
                print(f"     {GREEN}→ godkjent ✓{RESET}")
                merge_cmd = ["gh", "pr", "merge", str(number), "--repo", repo_full, "--squash", "--auto", "--delete-branch"]
                show_cmd(merge_cmd)
                merge = run(merge_cmd)
                if merge.returncode == 0:
                    print(f"     {GREEN}→ auto-merge aktivert ✓{RESET}")
                    print(f"     {DIM}GitHub merger når alle krav er oppfylt. Kjør 'make dependabot-behandle' igjen etterpå.{RESET}")
                    counts["merget"] += 1
                    counts[f"merget_{bump.lower()}"] = counts.get(f"merget_{bump.lower()}", 0) + 1
                else:
                    print(f"     {RED}→ auto-merge feilet: {merge.stderr.strip()}{RESET}")
            break

        if choice == "m" and state in ("green", "running"):
            if DRY_RUN:
                print(f"     {DIM}→ ville merget #{number}{RESET}")
                counts["merget"] += 1
                counts[f"merget_{bump.lower()}"] = counts.get(f"merget_{bump.lower()}", 0) + 1
            else:
                merge_cmd = ["gh", "pr", "merge", str(number), "--repo", repo_full, "--squash", "--auto", "--delete-branch"]
                show_cmd(merge_cmd)
                result = run(merge_cmd)
                if result.returncode == 0:
                    print(f"     {GREEN}→ auto-merge aktivert ✓{RESET}")
                    print(f"     {DIM}GitHub merger når alle krav er oppfylt. Kjør 'make dependabot-behandle' igjen etterpå.{RESET}")
                    counts["merget"] += 1
                    counts[f"merget_{bump.lower()}"] = counts.get(f"merget_{bump.lower()}", 0) + 1
                else:
                    print(f"     {RED}→ feilet: {result.stderr.strip()}{RESET}")
            break

        if choice == "u" and state == "behind":
            if DRY_RUN:
                print(f"     {DIM}→ ville kjørt update-branch{RESET}")
                counts["oppdatert"] += 1
            else:
                update_cmd = ["gh", "pr", "update-branch", str(number), "--repo", repo_full]
                show_cmd(update_cmd)
                result = run(update_cmd)
                if result.returncode == 0:
                    print(f"     {CYAN}→ update-branch sendt ✓{RESET}")
                    print(f"     {DIM}CI starter nå. Vent til den er grønn, så kjør 'make dependabot-behandle' igjen.{RESET}")
                    counts["oppdatert"] += 1
                else:
                    print(f"     {RED}→ feilet: {result.stderr.strip()}{RESET}")
            break

        if choice == "r" and state == "failed":
            run_id = find_latest_failed_run_id(org, name, pr["headRefName"])
            if not run_id:
                print(f"     {YELLOW}⚠️  Fant ingen failed run for denne branchen{RESET}")
                break
            if DRY_RUN:
                print(f"     {DIM}→ ville rerunnet run {run_id}{RESET}")
                counts["rerun"] += 1
            else:
                rerun_cmd = ["gh", "run", "rerun", run_id, "--failed", "--repo", repo_full]
                show_cmd(rerun_cmd)
                result = run(rerun_cmd)
                if result.returncode == 0:
                    print(f"     {GREEN}→ rerun startet ✓{RESET}")
                    print(f"     {DIM}Vent til CI er grønn, så kjør 'make dependabot-behandle' igjen.{RESET}")
                    counts["rerun"] += 1
                else:
                    print(f"     {RED}→ rerun feilet: {result.stderr.strip()}{RESET}")
            break

        if choice == "v":
            webbrowser.open(pr_url)
            counts["skippet"] += 1
            break

        if choice == "s":
            print(f"     {DIM}→ skippet{RESET}")
            counts["skippet"] += 1
            break

        print(f"     {YELLOW}Ugyldig valg — prøv igjen{RESET}")


def fetch_all(repos: list) -> tuple[list, list]:
    """Hent alle Dependabot-PRer og bygg repo_groups. Returnerer (repo_groups, active_groups)."""
    repo_groups = []
    total = len(repos)
    for i, repo in enumerate(repos, 1):
        name = repo["name"]
        org  = repo.get("org", "navikt")
        name_padded = name[:35].ljust(35)
        print(f"\r{DIM}Henter {name_padded} ({i:>2}/{total})…{RESET}", end="", flush=True)
        prs = fetch_dependabot_prs(org, name)
        auto_merge_prs = [p for p in prs if p.get("autoMergeRequest")]
        actionable_prs = [p for p in prs if not p.get("autoMergeRequest")]
        entries = []
        for pr in actionable_prs:
            state = "waiting" if auto_merge_prs else pr_state(pr)
            entries.append({"org": org, "name": name, "pr": pr,
                            "state": state, "bump": detect_bump_type(pr)})
        for pr in auto_merge_prs:
            entries.append({"org": org, "name": name, "pr": pr,
                            "state": "auto_merge", "bump": detect_bump_type(pr)})
        repo_groups.append({"org": org, "name": name, "entries": entries,
                             "blocked": bool(auto_merge_prs)})
    print(f"\r{' ' * 60}\r", end="", flush=True)
    active_groups = [g for g in repo_groups if g["entries"]]
    return repo_groups, active_groups


def main():
    repos  = parse_repos()
    prefix = f"{YELLOW}[DRY-RUN] {RESET}" if DRY_RUN else ""

    repo_groups, active_groups = fetch_all(repos)

    if not active_groups:
        print(f"  {DIM}Ingen åpne Dependabot-PRer — alt er ferdig! 🎉{RESET}\n")
        return

    total_prs = sum(len(g["entries"]) for g in repo_groups)
    counts    = {"merget": 0, "oppdatert": 0, "rerun": 0, "skippet": 0}

    STATE_HINT = {
        "green":      GREEN  + "klar til merge" + RESET,
        "behind":     CYAN   + "trenger update-branch" + RESET,
        "running":    YELLOW + "CI kjører" + RESET,
        "failed":     RED    + "CI feilet" + RESET,
        "waiting":    DIM    + "venter på auto-merge" + RESET,
        "auto_merge": CYAN   + "auto-merge aktivert ⚙" + RESET,
        "unknown":    DIM    + "ukjent" + RESET,
    }

    def print_entry_row(j, e):
        pr     = e["pr"]
        title  = pr["title"][:55] + ("…" if len(pr["title"]) > 55 else "")
        blabel = bump_label(e["bump"])
        hint   = STATE_HINT.get(e["state"], "")
        needs_approval = pr.get("reviewDecision", "") not in ("APPROVED", "")
        approval = f"  {YELLOW}· godkjenning mangler{RESET}" if needs_approval and e["state"] == "green" else ""
        print(f"   {BOLD}{j}{RESET}  {blabel}  {DIM}#{pr['number']}{RESET}  {title}  {hint}{approval}")

    def print_overview():
        print(f"{BOLD}{prefix}Dependabot PRer — {len(repo_groups)} repos, {total_prs} PRer totalt{RESET}\n")
        for i, group in enumerate(repo_groups, 1):
            entries = group["entries"]
            if entries:
                print(f"  {i:>2}  {BOLD}{group['name']}{RESET}")
                for e in entries:
                    pr     = e["pr"]
                    title  = pr["title"][:50] + ("…" if len(pr["title"]) > 50 else "")
                    blabel = bump_label(e["bump"])
                    hint   = STATE_HINT.get(e["state"], "")
                    needs_approval = pr.get("reviewDecision", "") not in ("APPROVED", "")
                    approval = f"  {YELLOW}· godkjenning mangler{RESET}" if needs_approval and e["state"] == "green" else ""
                    print(f"       {blabel}  {DIM}#{pr['number']}{RESET}  {title}  {hint}{approval}")
            else:
                print(f"  {i:>2}  {DIM}{group['name']}  ingen PRer{RESET}")
        print()

    # Vis alltid oversikt over alle repos
    print_overview()

    while True:
        print(f"{DIM}Velg repos (f.eks. 1,3 / alle / Enter=alle / q=avslutt — kun repos med PRer):{RESET} ", end="", flush=True)
        try:
            raw = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{YELLOW}Avbrutt.{RESET}\n")
            break
        if raw == "q":
            break
        if raw == "" or raw == "alle":
            selected_indices = [repo_groups.index(g) for g in active_groups]
        else:
            selected_indices = []
            for part in raw.split(","):
                try:
                    idx = int(part.strip()) - 1
                    if 0 <= idx < len(repo_groups) and repo_groups[idx]["entries"]:
                        selected_indices.append(idx)
                except ValueError:
                    pass
        if not selected_indices:
            print(f"\n  {DIM}Ingen repos valgt.{RESET}\n")
            continue

        treated_repo_names = set()

        for idx in selected_indices:
            group   = repo_groups[idx]
            entries = group["entries"]
            if group.get("blocked"):
                auto_prs = [e for e in entries if e["state"] == "auto_merge"]
                auto_nums = ", ".join(f"#{e['pr']['number']}" for e in auto_prs)
                print(f"  {DIM}⏸  {auto_nums} har aktiv auto-merge — andre PRer har begrensede valg{RESET}\n")

            print(f"  {BOLD}{group['name']}{RESET}  {DIM}({len(entries)} PRer){RESET}\n")
            for j, e in enumerate(entries, 1):
                print_entry_row(j, e)
            print()
            print(f"  {DIM}Hvilken PR vil du behandle? (Enter=skip, q=avslutt):{RESET} ", end="", flush=True)
            try:
                pick = input().strip().lower()
            except (EOFError, KeyboardInterrupt):
                print(f"\n{YELLOW}Avbrutt.{RESET}\n")
                break
            if not pick or pick == "q":
                print(f"  {DIM}→ skippet{RESET}\n")
                counts["skippet"] += 1
                continue
            try:
                pr_idx = int(pick) - 1
                if pr_idx < 0 or pr_idx >= len(entries):
                    raise ValueError
            except ValueError:
                print(f"  {YELLOW}Ugyldig valg — skippet.{RESET}\n")
                counts["skippet"] += 1
                continue
            chosen = entries[pr_idx]
            print()

            before_action = (counts["merget"], counts["oppdatert"], counts["rerun"])
            handle_pr(group["org"], group["name"], chosen["pr"], chosen["state"], chosen["bump"], counts)
            if (counts["merget"], counts["oppdatert"], counts["rerun"]) != before_action:
                treated_repo_names.add(group["name"])

        # Re-hent kun repos som ble behandlet
        for repo in repos:
            name = repo["name"]
            if name not in treated_repo_names:
                continue
            org = repo.get("org", "navikt")
            print(f"\r{DIM}Oppdaterer {name[:35].ljust(35)}…{RESET}", end="", flush=True)
            prs = fetch_dependabot_prs(org, name)
            auto_merge_prs = [p for p in prs if p.get("autoMergeRequest")]
            actionable_prs = [p for p in prs if not p.get("autoMergeRequest")]
            entries = []
            for pr in actionable_prs:
                state = "waiting" if auto_merge_prs else pr_state(pr)
                entries.append({"org": org, "name": name, "pr": pr,
                                "state": state, "bump": detect_bump_type(pr)})
            for pr in auto_merge_prs:
                entries.append({"org": org, "name": name, "pr": pr,
                                "state": "auto_merge", "bump": detect_bump_type(pr)})
            for g in repo_groups:
                if g["name"] == name:
                    g["entries"] = entries
                    g["blocked"] = bool(auto_merge_prs)
                    break
        if treated_repo_names:
            print(f"\r{' ' * 60}\r", end="", flush=True)

        active_groups = [g for g in repo_groups if g["entries"]]
        if not active_groups:
            print(f"  {DIM}Ingen åpne Dependabot-PRer igjen — alt er ferdig! 🎉{RESET}\n")
            break
        print_overview()

    # Oppsummering
    print()
    parts = []
    major_merget = counts.get("merget_major", 0)
    minor_merget = counts["merget"] - major_merget
    if counts["merget"]:
        detail = []
        if major_merget: detail.append(f"{major_merget} MAJOR")
        if minor_merget: detail.append(f"{minor_merget} minor/patch")
        parts.append(f"{GREEN}{counts['merget']} merget ({', '.join(detail)}){RESET}")
    if counts["oppdatert"]:
        parts.append(f"{CYAN}{counts['oppdatert']} update-branch{RESET}")
    if counts["rerun"]:
        parts.append(f"{YELLOW}{counts['rerun']} rerun startet{RESET}")
    if counts["skippet"]:
        parts.append(f"{DIM}{counts['skippet']} skippet{RESET}")
    print(f"  {' · '.join(parts) if parts else DIM + 'Ingen endringer' + RESET}\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Avbrutt.{RESET}\n")
        sys.exit(0)
