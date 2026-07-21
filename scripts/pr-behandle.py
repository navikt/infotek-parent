#!/usr/bin/env python3
"""
Interaktiv PR-behandler på tvers av alle managed repos.

Bruk:
  python3 scripts/pr-behandle.py              # vis alle PRer (standard)
  python3 scripts/pr-behandle.py --dependabot  # start direkte i Dependabot-modus
  python3 scripts/pr-behandle.py --mine        # start med filter "kun mine"
  python3 scripts/pr-behandle.py --alle        # alle åpne PRer inkl. Dependabot
  python3 scripts/pr-behandle.py --dry-run     # vis hva som ville skjedd

Oversiktsskjermen:
  [f]         Bytt filter (alle / uten bot / bot / mine / andres)
  [b]         Vis kun bot-PRer (Dependabot)
  [v]         Vis detaljert oversikt i less
  [e]         Hent alle repos på nytt
  nummer      Gå inn på repo
  [q]         Avslutt

Valg per PR:
  [a]  Godkjenn
  [m]  Merge (auto-merge)
  [u]  Update-branch (når PR er bak base)
  [r]  Rerun CI — interaktiv velger
  [p]  Artifakter fra siste failed run
  [d]  Diff i less (lang diff: velg less / nettleser / avkortet)
  [v]  Åpne PR i nettleser
  [b]  Tilbake til repo
  [n]  Neste repo
  [q]  Avslutt

Ikoner:
  ✅ klar til merge   🔄 CI kjører   ❌ CI feilet
  ⬆️  trenger update   🔒 blokkert    ⏸ venter   ⚙ auto-merge
"""

import atexit
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import webbrowser
from pathlib import Path

REPOS_FILE  = Path(__file__).parent.parent / "repos.yaml"
CONFIG_FILE = Path(__file__).parent.parent / "config.json"

DEPENDABOT_MODE = "--dependabot" in sys.argv
ONLY_MINE       = "--mine" in sys.argv
ALL_MODE        = "--alle" in sys.argv or not any(a in sys.argv for a in ("--dependabot", "--mine"))
OTHERS_MODE     = False
DRY_RUN         = "--dry-run" in sys.argv
def _load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

_cfg = _load_config().get("pr", {})

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

# --- skjermhåndtering ---------------------------------------------------
_ALT_SCREEN_ACTIVE = False

def _supports_alt_screen() -> bool:
    return os.environ.get("TERM", "") not in ("dumb", "") and sys.stdout.isatty()

def enter_alt_screen() -> None:
    global _ALT_SCREEN_ACTIVE
    if _supports_alt_screen():
        sys.stdout.write("\033[?1049h\033[H")
        sys.stdout.flush()
        _ALT_SCREEN_ACTIVE = True

def exit_alt_screen() -> None:
    global _ALT_SCREEN_ACTIVE
    if _ALT_SCREEN_ACTIVE:
        sys.stdout.write("\033[?1049l")
        sys.stdout.flush()
        _ALT_SCREEN_ACTIVE = False

def clear_screen() -> None:
    if _ALT_SCREEN_ACTIVE:
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()

def _term_rows() -> int:
    try:
        return os.get_terminal_size().lines
    except OSError:
        return 40

def show_paged(content: str) -> None:
    """Vis innhold direkte eller via less -R hvis det ikke passer i terminalen."""
    if shutil.which("less") and content.count("\n") >= _term_rows() - 4:
        subprocess.run(["less", "-R", "-F"], input=content, text=True)
    else:
        sys.stdout.write(content)
        sys.stdout.flush()

atexit.register(exit_alt_screen)

def _exit_handler(sig, frame):
    exit_alt_screen()
    sys.exit(0)

signal.signal(signal.SIGTERM, _exit_handler)
# -----------------------------------------------------------------------

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
    return f"{style}{label}{RESET}" if style else label


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

def prompt_cs(msg: str) -> str:
    """Case-sensitiv prompt — bevarer stor/liten bokstav."""
    print(msg, end="", flush=True)
    try:
        return input().strip()
    except EOFError:
        print()
        return "n"


_current_user: str | None = None

def get_current_user() -> str:
    global _current_user
    if _current_user is None:
        r = run(["gh", "api", "user", "--jq", ".login"])
        _current_user = r.stdout.strip() if r.returncode == 0 else ""
    return _current_user


def get_filter_info() -> str:
    if ONLY_MINE:       return " (kun mine)"
    if DEPENDABOT_MODE: return " (kun dependabot)"
    if OTHERS_MODE:     return " (kun andres)"
    if ALL_MODE:        return " (alle inkl. dependabot)"
    return " (uten dependabot)"


def _current_filter_key() -> str:
    if ONLY_MINE:       return "mine"
    if DEPENDABOT_MODE: return "dependabot"
    if OTHERS_MODE:     return "andres"
    if ALL_MODE:        return "alle"
    return "uten_dependabot"

def _apply_filter_key(key: str) -> None:
    global DEPENDABOT_MODE, ONLY_MINE, ALL_MODE, OTHERS_MODE
    DEPENDABOT_MODE = key == "dependabot"
    ONLY_MINE       = key == "mine"
    ALL_MODE        = key == "alle"
    OTHERS_MODE     = key == "andres"

FILTER_VALUES = [
    ("alle",            "alle"),
    ("uten_dependabot", "uten bot"),
    ("dependabot",      "bot"),
    ("mine",            "mine"),
    ("andres",          "andres"),
]


def pick_filter_inline() -> None:
    """Vis kompakt filter-velger på én linje, sett filter."""
    opts = "  ".join(f"[{i}] {label}" for i, (_, label) in enumerate(FILTER_VALUES, 1))
    print(f"  {DIM}Filter:{RESET}  {opts}  > ", end="", flush=True)
    try:
        raw = input().strip()
    except EOFError:
        return
    if raw.isdigit() and 1 <= int(raw) <= len(FILTER_VALUES):
        _apply_filter_key(FILTER_VALUES[int(raw) - 1][0])



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
    merge_state = pr.get("mergeStateStatus", "")
    if merge_state == "BEHIND":
        return "behind"
    if merge_state == "BLOCKED":
        return "blocked"
    if all_ok and mergeable == "MERGEABLE":
        return "green"
    if mergeable not in ("MERGEABLE", "CONFLICTING"):
        return "behind"
    return "unknown"


def state_icon(state: str) -> str:
    return {
        "green":      GREEN  + "✅" + RESET,
        "running":    YELLOW + "🔄" + RESET,
        "failed":     RED    + "❌" + RESET,
        "blocked":    RED    + "🔒" + RESET,
        "behind":     CYAN   + "⬆️ " + RESET,
        "waiting":    DIM    + "⏸"  + RESET,
        "auto_merge": CYAN   + "⚙"  + RESET,
        "unknown":    DIM    + "?"  + RESET,
    }.get(state, DIM + "?" + RESET)


STATE_HINT = {
    "green":      GREEN  + "klar til merge"               + RESET,
    "blocked":    RED    + "blokkert — uleste kommentarer" + RESET,
    "behind":     CYAN   + "trenger update-branch"         + RESET,
    "running":    YELLOW + "CI kjører"                     + RESET,
    "failed":     RED    + "CI feilet"                     + RESET,
    "waiting":    DIM    + "venter på auto-merge"          + RESET,
    "auto_merge": CYAN   + "auto-merge aktivert ⚙"        + RESET,
    "unknown":    DIM    + "ukjent"                        + RESET,
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


def _fetch_diff(org: str, name: str, pr_number: int) -> tuple[str, list[str]]:
    """Hent og fargeleg diff. Returnerer (full_text, colored_lines)."""
    result = run(["gh", "pr", "diff", str(pr_number), "--repo", f"{org}/{name}"])
    if result.returncode != 0 or not result.stdout.strip():
        return "", []
    lines = result.stdout.splitlines()
    colored = []
    for line in lines:
        if line.startswith("+") and not line.startswith("+++"):
            colored.append(f"  {GREEN}{line}{RESET}")
        elif line.startswith("-") and not line.startswith("---"):
            colored.append(f"  {RED}{line}{RESET}")
        elif line.startswith("@@"):
            colored.append(f"  {CYAN}{line}{RESET}")
        else:
            colored.append(f"  {DIM}{line}{RESET}")
    return "\n".join(colored), colored


def pick_rerun_interactive(org: str, name: str, branch: str) -> list[str]:
    """Hent runs på branch, la bruker velge hvilke å rerunne. Returnerer liste av run-IDer."""
    result = run([
        "gh", "run", "list", "--repo", f"{org}/{name}",
        "--branch", branch,
        "--json", "databaseId,name,conclusion,status,startedAt",
        "--limit", RUN_LIST_LIMIT,
    ])
    if result.returncode != 0:
        print(f"     {RED}Kunne ikke hente runs{RESET}")
        return []
    try:
        runs = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    if not runs:
        print(f"     {YELLOW}Ingen runs funnet på {branch}{RESET}")
        return []

    icon_map = {
        "failure": RED + "❌" + RESET, "timed_out": RED + "⏱" + RESET,
        "success": GREEN + "✅" + RESET, "cancelled": DIM + "⊘" + RESET,
    }
    print(f"\n     {DIM}Runs på {branch}:{RESET}")
    failed_ids = []
    for i, r in enumerate(runs, 1):
        conc = r.get("conclusion") or r.get("status", "")
        icon = icon_map.get(conc, DIM + "?" + RESET)
        rname = r["name"][:40]
        print(f"     {BOLD}{i}{RESET}  {icon}  {DIM}#{r['databaseId']}{RESET}  {rname}")
        if conc in ("failure", "timed_out"):
            failed_ids.append(str(r["databaseId"]))

    all_ids = [str(r["databaseId"]) for r in runs]
    print(f"\n     {DIM}Enter=alle feilede / nummer(1,2) / q=avbryt:{RESET} ", end="", flush=True)
    try:
        raw = input().strip().lower()
    except EOFError:
        return []
    if raw == "q":
        return []
    if raw == "":
        return failed_ids
    selected = []
    for part in raw.split(","):
        try:
            idx = int(part.strip()) - 1
            if 0 <= idx < len(runs):
                selected.append(all_ids[idx])
        except ValueError:
            pass
    return selected


def apply_filter(prs: list) -> list:
    """Filtrer PRer basert på nåværende globale filtervariable."""
    if DEPENDABOT_MODE:
        return [p for p in prs if p.get("author", {}).get("login", "") == "app/dependabot"]
    result = prs
    if not ALL_MODE:
        result = [p for p in result if p.get("author", {}).get("login", "") != "app/dependabot"]
    if ONLY_MINE:
        me = get_current_user()
        if me:
            result = [p for p in result if p.get("author", {}).get("login", "") == me]
    elif OTHERS_MODE:
        me = get_current_user()
        if me:
            result = [p for p in result if p.get("author", {}).get("login", "") != me]
    return result


def fetch_prs(org: str, name: str) -> tuple[list, bool]:
    """Returnerer (raw_prs, has_more) — alle åpne PRer uten filtrering."""
    fetch_limit = str(int(PR_LIST_LIMIT) + 1)
    args = [
        "gh", "pr", "list",
        "--repo", f"{org}/{name}",
        "--state", "open",
        "--limit", fetch_limit,
        "--json", "number,title,headRefName,baseRefName,statusCheckRollup,author,isDraft,url,mergeable,mergeStateStatus,reviewDecision,autoMergeRequest",
    ]
    result = run(args)
    if result.returncode != 0:
        return [], False
    try:
        prs = sorted(json.loads(result.stdout), key=lambda p: p["number"])
        has_more = len(prs) > int(PR_LIST_LIMIT)
        return prs[:int(PR_LIST_LIMIT)], has_more
    except json.JSONDecodeError:
        return [], False


def handle_pr(org: str, name: str, pr: dict, state: str, counts: dict, bump: str = None) -> str:
    """Returnerer 'next_repo' hvis bruker vil hoppe til neste repo, ellers 'done'."""
    clear_screen()
    repo_full       = f"{org}/{name}"
    number          = pr["number"]
    title           = pr["title"][:60] + ("…" if len(pr["title"]) > 60 else "")
    pr_url          = pr["url"]
    review_decision = pr.get("reviewDecision", "")
    needs_approval  = review_decision not in ("APPROVED", "")
    actual_state    = pr_state(pr)

    # Vis header
    draft    = f"{DIM}[draft]{RESET} " if pr.get("isDraft") else ""
    author   = pr.get("author", {}).get("login", "")
    conflict = f"  {RED}⚡ merge-konflikt{RESET}" if pr.get("mergeable") == "CONFLICTING" else ""
    bump_str = f"  {bump_label(bump)}" if bump else ""
    print(f"\n  {state_icon(state)}{bump_str}  {BOLD}{name}{RESET}  {DIM}#{number}{RESET}  {draft}{title}{conflict}")

    # Branch + author
    head = pr.get("headRefName", "")
    base = pr.get("baseRefName", "main")
    author_str = f"  {DIM}@{author}{RESET}" if author else ""
    print(f"     {CYAN}{head}{RESET}  {DIM}→ {base}{RESET}{author_str}")

    # Checks-oppsummering
    checks      = pr.get("statusCheckRollup", [])
    n_ok        = sum(1 for c in checks if c.get("conclusion") in ("SUCCESS", "NEUTRAL", "SKIPPED"))
    n_fail      = sum(1 for c in checks if c.get("conclusion") in ("FAILURE", "TIMED_OUT", "ERROR"))
    n_running   = sum(1 for c in checks if c.get("status") in ("IN_PROGRESS", "QUEUED", "WAITING"))
    check_parts = []
    if checks:
        if n_ok:      check_parts.append(f"{GREEN}{n_ok} ✅{RESET}")
        if n_running: check_parts.append(f"{YELLOW}{n_running} ⏳{RESET}")
        if n_fail:    check_parts.append(f"{RED}{n_fail} ❌{RESET}")
        check_str = "  ".join(check_parts)
        print(f"     Checks: {check_str}")
    if review_decision == "APPROVED":
        print(f"     {GREEN}✓ godkjent{RESET}")
    elif needs_approval:
        print(f"     {YELLOW}⚠️  trenger godkjenning{RESET}")
    if state == "failed":
        failed = failed_check_names(pr)
        if failed:
            print(f"     {RED}Feilet: {', '.join(failed)}{RESET}")
    print(f"     {link(pr_url)}")

    # header er ca 6 linjer, meny ca 2, buffer 3 → resten til diff
    header_lines = 8 + (1 if checks else 0) + (1 if state == "failed" else 0)
    diff_max = max(5, _term_rows() - header_lines - 4)
    print(f"\n     {DIM}Diff — {pr['title'][:70]}{RESET}\n")
    full_diff, diff_lines = _fetch_diff(org, name, number)
    if not full_diff:
        print(f"     {DIM}Ingen diff tilgjengelig{RESET}")
    elif len(diff_lines) <= diff_max:
        print(full_diff)
    else:
        print(f"  {DIM}Diff er {len(diff_lines)} linjer (plass til {diff_max}).{RESET}")
    print()

    # Begrensede valg for waiting/auto_merge
    if state in ("waiting", "auto_merge"):
        if state == "auto_merge":
            print(f"     {CYAN}⚙  Auto-merge er aktivert — venter på at GitHub merger.{RESET}")
        else:
            print(f"     {YELLOW}⏸  Venter — en annen PR i dette repoet har aktiv auto-merge.{RESET}")
        print(f"     {DIM}Merge/approve ikke tilgjengelig.{RESET}\n")
        is_behind = actual_state == "behind"
        options = []
        if actual_state == "failed":
            options.append("[r] Rerun CI")
        if is_behind:
            options.append("[u] Update-branch")
        if full_diff:
            options += ["[l] less", "[w] nettleser", "[t] avkortet"]
        options += ["[v] Åpne", "[b] Tilbake til repo", "[n] Neste repo", "[q] Avslutt"]
        while True:
            choice = prompt_cs(f"     {'  '.join(options)}  > ")
            if choice.lower() == "q":
                print_summary(counts); exit_alt_screen(); sys.exit(0)
            if choice.lower() == "l" and full_diff:
                show_paged(full_diff); continue
            if choice.lower() == "w" and full_diff:
                webbrowser.open(f"https://github.com/{org}/{name}/pull/{number}/files"); continue
            if choice.lower() == "t" and full_diff:
                print("\n".join(diff_lines[:diff_max]))
                print(f"  {DIM}… +{len(diff_lines) - diff_max} linjer skjult{RESET}")
                continue
            if choice.lower() == "v":
                webbrowser.open(pr_url); continue
            if choice.lower() == "b":
                counts["skippet"] += 1; break
            if choice.lower() == "n":
                counts["skippet"] += 1
                return "next_repo"
            if choice.lower() == "u" and is_behind:
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
                continue
            if choice.lower() == "r":
                run_ids = pick_rerun_interactive(org, name, pr["headRefName"])
                for run_id in run_ids:
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
                continue
            print(f"     {YELLOW}Ugyldig valg — prøv igjen{RESET}")
        return "done"

    is_behind     = pr.get("mergeStateStatus") == "BEHIND"
    has_auto_merge = bool(pr.get("autoMergeRequest"))

    # Normale valg — navigasjon alltid til slutt
    options = []
    if has_auto_merge:
        options.append(f"{DIM}⚙ auto-merge aktivert{RESET}")
    if state == "failed":
        options.append("[p] Artifakter")
        options.append("[r] Rerun CI")
    if is_behind:
        options.append("[u] Update-branch")
    if needs_approval and state in ("green", "behind", "unknown", "running", "failed", "blocked"):
        options.append("[a] Godkjenn")
    if state in ("green", "running") and not has_auto_merge:
        options.append("[m] Merge")
    if full_diff:
        options += ["[l] less", "[w] nettleser", "[t] avkortet"]
    options += ["[v] Åpne", "[b] Tilbake til repo", "[n] Neste repo", "[q] Avslutt"]

    while True:
        choice = prompt_cs(f"     {'  '.join(options)}  > ")

        if choice.lower() == "q":
            print_summary(counts); exit_alt_screen(); sys.exit(0)

        if choice.lower() == "l" and full_diff:
            show_paged(full_diff); continue

        if choice.lower() == "w" and full_diff:
            webbrowser.open(f"https://github.com/{org}/{name}/pull/{number}/files"); continue

        if choice.lower() == "t" and full_diff:
            print("\n".join(diff_lines[:diff_max]))
            print(f"  {DIM}… +{len(diff_lines) - diff_max} linjer skjult{RESET}")
            continue

        if choice.lower() == "p" and state == "failed":
            branch = pr["headRefName"]
            runs_result = run(["gh", "run", "list", "--repo", repo_full, "--branch", branch,
                                "--json", "databaseId,conclusion", "--limit", RUN_LIST_LIMIT])
            run_id = ""
            if runs_result.returncode == 0:
                try:
                    for r in json.loads(runs_result.stdout):
                        if r.get("conclusion") in ("failure", "timed_out"):
                            run_id = str(r["databaseId"]); break
                except (json.JSONDecodeError, KeyError):
                    pass
            pw_cmd = ["python3", str(Path(__file__).parent / "vis-artifakt.py"),
                      "--repo", repo_full, "--run", run_id]
            if not run_id:
                print(f"     {YELLOW}⚠️  Fant ingen failed run{RESET}")
            else:
                show_cmd(pw_cmd)
                _prev = signal.signal(signal.SIGINT, signal.SIG_IGN)
                subprocess.run(pw_cmd, check=False)
                signal.signal(signal.SIGINT, _prev)
            continue

        if choice.lower() == "v":
            webbrowser.open(pr_url); continue

        if choice.lower() == "b":
            print(f"     {DIM}→ tilbake{RESET}"); counts["skippet"] += 1; break

        if choice.lower() == "n":
            counts["skippet"] += 1
            return "next_repo"

        if choice.lower() == "a" and needs_approval and state in ("green", "behind", "unknown", "running", "failed", "blocked"):
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
            continue

        if choice.lower() == "m" and state in ("green", "running"):
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

        if choice.lower() == "u" and is_behind:
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
            counts["oppdatert"] += 1; continue

        if choice.lower() == "r" and state == "failed":
            run_ids = pick_rerun_interactive(org, name, pr["headRefName"])
            for run_id in run_ids:
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
                counts["rerun"] += 1
            continue

        print(f"     {YELLOW}Ugyldig valg — prøv igjen{RESET}")
    return "done"


def fetch_all(repos: list):
    """Hent PRer for alle repos. Returnerer (repo_groups, active_groups)."""
    repo_groups = []
    total = len(repos)
    for i, repo in enumerate(repos, 1):
        name = repo["name"]
        org  = repo.get("org", "navikt")
        print(f"\r{DIM}Henter {name[:35].ljust(35)} ({i:>2}/{total})…{RESET}", end="", flush=True)
        raw_prs, has_more = fetch_prs(org, name)
        prs = apply_filter(raw_prs)
        if DEPENDABOT_MODE:
            auto_merge_prs = [p for p in prs if p.get("autoMergeRequest")]
            actionable_prs = [p for p in prs if not p.get("autoMergeRequest")]
            entries = []
            for pr in actionable_prs:
                state = "waiting" if auto_merge_prs else pr_state(pr)
                entries.append({"org": org, "name": name, "pr": pr, "state": state, "bump": detect_bump_type(pr)})
            for pr in auto_merge_prs:
                entries.append({"org": org, "name": name, "pr": pr, "state": "auto_merge", "bump": detect_bump_type(pr)})
            repo_groups.append({"org": org, "name": name, "raw_prs": raw_prs, "entries": entries, "blocked": bool(auto_merge_prs), "truncated": has_more})
        else:
            entries = [{"org": org, "name": name, "pr": p, "state": pr_state(p)} for p in prs]
            repo_groups.append({"org": org, "name": name, "raw_prs": raw_prs, "entries": entries, "truncated": has_more})
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


def _repo_state_icons(entries: list) -> str:
    return "".join(state_icon(e["state"]) for e in entries[:8])


def _icon_legend() -> str:
    entries = [
        ("✅", "klar"),
        ("🔄", "CI kjører"),
        ("❌", "feilet"),
        ("⬆️ ", "trenger update"),
        ("🔒", "blokkert"),
        ("⏸",  "venter"),
        ("⚙",  "auto-merge"),
    ]
    return DIM + "  ".join(f"{icon} {label}" for icon, label in entries) + RESET


def print_overview_compact(repo_groups: list, total_prs: int, filter_info: str):
    """Kompakt oversikt — én linje per repo, alltid plass i terminalen."""
    print(f"\n{BOLD}Åpne PRer{filter_info}{RESET}  {_icon_legend()}\n")
    total_failing = 0
    active_idx = 1
    empty_repos = 0
    for group in repo_groups:
        org  = group["org"]
        name = group["name"]
        repo_url = f"https://github.com/{org}/{name}"
        if not group["entries"]:
            empty_repos += 1
            pr_count = f"{DIM}0 PRer{RESET}"
            print(f"  {DIM}{active_idx:>2}  {link(repo_url, name):<40}  {pr_count}{RESET}")
            active_idx += 1
            continue
        entries = group["entries"]
        total_failing += sum(1 for e in entries if e["state"] == "failed")
        icons = _repo_state_icons(entries)
        pr_count = f"{DIM}{len(entries)} PR{'er' if len(entries) != 1 else ''}{RESET}"
        print(f"  {BOLD}{active_idx:>2}{RESET}  {link(repo_url, name, BOLD):<40}  {pr_count}  {icons}")
        active_idx += 1
    print()
    summary_parts = [f"{total_prs} åpen(e) PR(er)"]
    if total_failing:
        summary_parts.append(f"{RED}{total_failing} feiler{RESET}")
    if empty_repos:
        summary_parts.append(f"{DIM}{empty_repos} rene repos{RESET}")
    print("  " + "  ·  ".join(summary_parts) + "\n")


def build_overview_detailed(repo_groups: list, total_prs: int, filter_info: str) -> str:
    """Detaljert oversikt med branch, tittel og URL — vises i less."""
    out = [f"\n{BOLD}Åpne PRer{filter_info}{RESET}  {_icon_legend()}\n"]
    total_failing = 0
    active_idx = 1
    for group in repo_groups:
        org  = group["org"]
        name = group["name"]
        repo_url = f"https://github.com/{org}/{name}"
        if not group["entries"]:
            out.append(f"  {DIM}{active_idx:>2}  {link(repo_url, name)}  ingen PRer{RESET}")
            active_idx += 1
            continue
        num_str = f"{BOLD}{active_idx:>2}{RESET}"
        active_idx += 1
        out.append(f"  {num_str}  {link(repo_url, name, BOLD)}")
        for e in group["entries"]:
            pr = e["pr"]
            if e["state"] == "failed":
                total_failing += 1
            draft      = f"{DIM}[draft]{RESET} " if pr.get("isDraft") else ""
            number     = f"{DIM}#{pr['number']}{RESET}"
            title      = pr["title"][:50] + ("…" if len(pr["title"]) > 50 else "")
            author     = pr.get("author", {}).get("login", "")
            author_str = f"  {DIM}@{author}{RESET}" if author else ""
            branch     = f"{CYAN}{pr['headRefName']}{RESET}"
            hints      = pr_status_hints(pr, e["state"])
            out.append(f"       {state_icon(e['state'])} {number} {draft}{title}{author_str}")
            out.append(f"          {branch}{hints}")
            out.append(f"          {link(pr['url'])}")
        if group.get("truncated"):
            out.append(f"       {DIM}… flere PRer — åpne {link(repo_url)} for full liste{RESET}")
        out.append("")
    if total_prs == 0:
        out.append(f"  {DIM}Ingen åpne PRer{RESET}")
    else:
        summary = f"  {total_prs} åpen(e) PR(er)"
        if total_failing:
            summary += f"  {RED}· {total_failing} feiler{RESET}"
        out.append(summary)
    out.append("")
    return "\n".join(out)


def print_overview_standard(repo_groups: list, active_groups: list, total_prs: int, filter_info: str):
    total_prs = sum(len(g["entries"]) for g in repo_groups)
    detailed = build_overview_detailed(repo_groups, total_prs, filter_info)
    if detailed.count("\n") < _term_rows() - 4:
        sys.stdout.write(detailed)
        sys.stdout.flush()
    else:
        print_overview_compact(repo_groups, total_prs, filter_info)


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
        clear_screen()
        total_prs = sum(len(g["entries"]) for g in repo_groups)
        print_overview_dependabot(repo_groups, total_prs, prefix)

        print(f"{DIM}Velg repo (nummer / q=avslutt):{RESET} ", end="", flush=True)
        try:
            raw = input().strip().lower()
        except EOFError:
            break
        if raw == "q":
            break
        if raw == "":
            continue

        try:
            idx = int(raw) - 1
            if idx < 0 or idx >= len(repo_groups) or not repo_groups[idx]["entries"]:
                raise ValueError
        except ValueError:
            print(f"\n  {DIM}Ugyldig valg.{RESET}\n"); continue

        group = repo_groups[idx]
        org   = group["org"]
        name  = group["name"]

        # --- indre repo-løkke ---
        while True:
            entries = group["entries"]
            clear_screen()
            if group.get("blocked"):
                auto_nums = ", ".join(f"#{e['pr']['number']}" for e in entries if e["state"] == "auto_merge")
                print(f"  {DIM}⏸  {auto_nums} har aktiv auto-merge — andre PRer har begrensede valg{RESET}\n")
            print(f"  {BOLD}{name}{RESET}  {DIM}({len(entries)} PRer){RESET}\n")
            for j, e in enumerate(entries, 1):
                pr       = e["pr"]
                title    = pr["title"]
                branch   = pr.get("headRefName", "")
                approval = ""
                if pr.get("reviewDecision", "") not in ("APPROVED", "") and e["state"] == "green":
                    approval = f"  {YELLOW}· godkjenning mangler{RESET}"
                print(f"   {BOLD}{j}{RESET}  {bump_label(e['bump'])}  {DIM}#{pr['number']}{RESET}  {title}  {STATE_HINT.get(e['state'], '')}{approval}")
                print(f"      {DIM}{CYAN}{branch}{RESET}")
            print()
            print(f"  {DIM}Velg PR — nummer / [b] Tilbake / [q] Avslutt:{RESET} ", end="", flush=True)
            try:
                pick = input().strip().lower()
            except EOFError:
                pick = "q"
            if pick == "q":
                print_summary(counts)
                exit_alt_screen()
                sys.exit(0)
            if not pick or pick == "b":
                break
            try:
                pr_idx = int(pick) - 1
                if pr_idx < 0 or pr_idx >= len(entries):
                    raise ValueError
            except ValueError:
                print(f"  {YELLOW}Ugyldig valg.{RESET}"); continue

            chosen = entries[pr_idx]
            action = handle_pr(org, name, chosen["pr"], chosen["state"], counts, bump=chosen["bump"])

            # re-hent dette repoet
            print(f"\r{DIM}Oppdaterer {name[:35].ljust(35)}…{RESET}", end="", flush=True)
            raw_prs, has_more = fetch_prs(org, name)
            group["raw_prs"] = raw_prs
            prs = apply_filter(raw_prs)
            auto_merge_prs = [p for p in prs if p.get("autoMergeRequest")]
            actionable_prs = [p for p in prs if not p.get("autoMergeRequest")]
            new_entries = []
            for pr in actionable_prs:
                st = "waiting" if auto_merge_prs else pr_state(pr)
                new_entries.append({"org": org, "name": name, "pr": pr, "state": st, "bump": detect_bump_type(pr)})
            for pr in auto_merge_prs:
                new_entries.append({"org": org, "name": name, "pr": pr, "state": "auto_merge", "bump": detect_bump_type(pr)})
            group["entries"] = new_entries
            group["blocked"] = bool(auto_merge_prs)
            group["truncated"] = has_more
            print(f"\r{' ' * 60}\r", end="", flush=True)
            if not new_entries or action == "next_repo":
                break

        active_groups = [g for g in repo_groups if g["entries"]]
        if not active_groups:
            clear_screen()
            print(f"  {DIM}Ingen åpne Dependabot-PRer igjen — alt er ferdig! 🎉{RESET}\n")
            break

    print_summary(counts)


def main_standard(repos: list):
    repo_groups, active_groups = fetch_all(repos)
    total_prs = sum(len(g["entries"]) for g in repo_groups)

    clear_screen()
    print_overview_standard(repo_groups, active_groups, total_prs, get_filter_info())

    if not active_groups:
        return

    counts = {"merget": 0, "oppdatert": 0, "rerun": 0, "skippet": 0}
    _pre_bot_filter = _current_filter_key()

    def _apply_and_refresh(key: str):
        nonlocal active_groups, total_prs
        _apply_filter_key(key)
        for g in repo_groups:
            prs = apply_filter(g["raw_prs"])
            g["entries"] = [{"org": g["org"], "name": g["name"], "pr": p, "state": pr_state(p)} for p in prs]
        active_groups = [g for g in repo_groups if g["entries"]]
        total_prs = sum(len(g["entries"]) for g in repo_groups)
        clear_screen()
        print_overview_standard(repo_groups, active_groups, total_prs, get_filter_info())

    def _refetch_all():
        nonlocal repo_groups, active_groups, total_prs
        repo_groups, active_groups = fetch_all(repos)
        total_prs = sum(len(g["entries"]) for g in repo_groups)
        clear_screen()
        print_overview_standard(repo_groups, active_groups, total_prs, get_filter_info())

    def _toggle_bot():
        nonlocal _pre_bot_filter
        if _current_filter_key() == "dependabot":
            _apply_and_refresh(_pre_bot_filter)
        else:
            _pre_bot_filter = _current_filter_key()
            _apply_and_refresh("dependabot")

    while True:
        bot_label = "Alle PRer" if _current_filter_key() == "dependabot" else "Bot-PRer"
        print(f"{DIM}Velg repo (nummer / [f] Filter / [b] {bot_label} / [v] Detaljer / [e] Hent på nytt / q=avslutt):{RESET} ", end="", flush=True)
        try:
            raw = input().strip().lower()
        except EOFError:
            break
        if raw == "q":
            break
        if raw == "":
            continue
        if raw == "v":
            show_paged(build_overview_detailed(repo_groups, sum(len(g["entries"]) for g in repo_groups), get_filter_info()))
            clear_screen()
            print_overview_standard(repo_groups, active_groups, total_prs, get_filter_info())
            continue
        if raw == "b":
            _toggle_bot()
            continue
        if raw == "f":
            pick_filter_inline()
            _apply_and_refresh(_current_filter_key())
            continue
        if raw == "e":
            _refetch_all()
            continue

        try:
            idx = int(raw) - 1
            if idx < 0 or idx >= len(repo_groups):
                raise ValueError
        except ValueError:
            print(f"\n  {DIM}Ugyldig valg.{RESET}\n"); continue

        group = repo_groups[idx]
        if not group["entries"]:
            print(f"\n  {DIM}Ingen åpne PRer for {group['name']}.{RESET}\n"); continue
        org   = group["org"]
        name  = group["name"]

        # --- indre repo-løkke ---
        while True:
            entries = group["entries"]
            clear_screen()
            print(f"\n  {BOLD}{name}{RESET}  {DIM}({len(entries)} PRer){RESET}\n")
            for j, e in enumerate(entries, 1):
                pr     = e["pr"]
                draft  = f"{DIM}[draft]{RESET} " if pr.get("isDraft") else ""
                title  = pr["title"]
                branch = pr.get("headRefName", "")
                hints  = pr_status_hints(pr, e["state"])
                print(f"   {BOLD}{j}{RESET}  {state_icon(e['state'])}  {DIM}#{pr['number']}{RESET}  {draft}{title}{hints}")
                print(f"      {DIM}{CYAN}{branch}{RESET}")
            print()
            print(f"  {DIM}Velg PR — nummer / [b] Tilbake / [q] Avslutt:{RESET} ", end="", flush=True)
            try:
                pick = input().strip().lower()
            except EOFError:
                pick = "q"
            if pick == "q":
                print_summary(counts)
                exit_alt_screen()
                sys.exit(0)
            if not pick or pick == "b":
                break
            try:
                pr_idx = int(pick) - 1
                if pr_idx < 0 or pr_idx >= len(entries):
                    raise ValueError
            except ValueError:
                print(f"  {YELLOW}Ugyldig valg.{RESET}"); continue

            chosen = entries[pr_idx]
            action = handle_pr(org, name, chosen["pr"], chosen["state"], counts)

            # re-hent dette repoet for oppdatert liste
            print(f"\r{DIM}Oppdaterer {name[:35].ljust(35)}…{RESET}", end="", flush=True)
            raw_prs, has_more = fetch_prs(org, name)
            group["raw_prs"] = raw_prs
            filtered = apply_filter(raw_prs)
            group["entries"] = [{"org": org, "name": name, "pr": p, "state": pr_state(p)} for p in filtered]
            group["truncated"] = has_more
            print(f"\r{' ' * 60}\r", end="", flush=True)
            if not group["entries"] or action == "next_repo":
                break

        active_groups = [g for g in repo_groups if g["entries"]]
        total_prs = sum(len(g["entries"]) for g in repo_groups)
        clear_screen()
        if not active_groups:
            print(f"  {DIM}Ingen åpne PRer igjen — alt er ferdig! 🎉{RESET}\n")
            break
        print_overview_standard(repo_groups, active_groups, total_prs, get_filter_info())

    print_summary(counts)


def main():
    enter_alt_screen()
    repos = parse_repos()
    if not repos:
        exit_alt_screen()
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
        exit_alt_screen()
        print(f"\n{YELLOW}Avbrutt.{RESET}\n")
        sys.exit(0)
