#!/usr/bin/env python3
"""
Last ned og åpne artifakter fra en feilet PR i CI.

Bruk:
  python3 scripts/vis-artifakt.py                        # velg repo og PR interaktivt
  python3 scripts/vis-artifakt.py --repo navikt/historisk-regnskap
  python3 scripts/vis-artifakt.py --repo navikt/historisk-regnskap --pr 258
  python3 scripts/vis-artifakt.py --run 29590969035 --repo navikt/historisk-regnskap

make vis-artifakt
make vis-artifakt REPO=navikt/historisk-regnskap PR=258
"""

import atexit
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import webbrowser
from pathlib import Path

REPOS_FILE  = Path(__file__).parent.parent / "repos.yaml"
CONFIG_FILE = Path(__file__).parent.parent / "config.json"

def _load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

_cfg = _load_config().get("artifakt", {})

ARTIFACT_PATTERNS = _cfg.get("patterns", ["playwright", "e2e", "report", "test-results", "pw-"])

BOLD   = "\033[1m"
GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
DIM    = "\033[2m"
RESET  = "\033[0m"

# --- prosess-rydding ---------------------------------------------------
_started_procs: list[subprocess.Popen] = []

def _cleanup_procs() -> None:
    for proc in _started_procs:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()

atexit.register(_cleanup_procs)

def _signal_handler(sig, frame):
    _cleanup_procs()
    sys.exit(0)

signal.signal(signal.SIGTERM, _signal_handler)
# SIGINT håndteres via KeyboardInterrupt i main()
# -----------------------------------------------------------------------


def run(cmd, check=False):
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def prompt(msg: str) -> str:
    print(msg, end="", flush=True)
    try:
        return input().strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)


def parse_arg(flag: str) -> str | None:
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == flag and i < len(sys.argv):
            return sys.argv[i + 1]
        if arg.startswith(f"{flag}="):
            return arg.split("=", 1)[1]
    return None


def parse_repos_for_artifacts() -> list:
    """Les repos.yaml og returner alle managed repos."""
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
        repos.append(current)
    return repos


def find_latest_run(repo_full: str, branch: str | None) -> str | None:
    """Finn siste run på branchen."""
    args = [
        "gh", "run", "list", "--repo", repo_full,
        "--json", "databaseId",
        "--limit", "1",
    ]
    if branch:
        args += ["--branch", branch]
    result = run(args)
    if result.returncode != 0:
        return None
    try:
        runs = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    return str(runs[0]["databaseId"]) if runs else None


def list_run_artifacts(repo_full: str, run_id: str) -> list[dict]:
    """List tilgjengelige artifakter for en run via API."""
    result = run(["gh", "api", f"repos/{repo_full}/actions/runs/{run_id}/artifacts",
                  "--jq", ".artifacts[] | {name: .name, id: .id, expired: .expired}"])
    if result.returncode != 0 or not result.stdout.strip():
        return []
    artifacts = []
    for line in result.stdout.strip().splitlines():
        try:
            artifacts.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return artifacts


def pick_artifact_name(artifacts: list[dict]) -> str | None:
    """Auto-match for intern bruk (ikke interaktiv)."""
    for pat in ARTIFACT_PATTERNS:
        for a in artifacts:
            if pat in a["name"].lower() and not a.get("expired"):
                return a["name"]
    return None


def pick_artifact_interactive(artifacts: list[dict]) -> str | None:
    """Vis liste over artifakter og la bruker velge. Auto-match vises som forslag."""
    non_expired = [a for a in artifacts if not a.get("expired")]
    expired_count = sum(1 for a in artifacts if a.get("expired"))

    if not non_expired:
        if expired_count:
            print(f"  {RED}Alle artifakter ({expired_count}) er utgått.{RESET}")
        else:
            print(f"  {RED}Ingen artifakter tilgjengelig.{RESET}")
        return None

    auto = pick_artifact_name(non_expired)
    default_idx = next((i for i, a in enumerate(non_expired) if a["name"] == auto), 0)

    print(f"\n  {BOLD}Tilgjengelige artifakter:{RESET}\n")
    for i, a in enumerate(non_expired, 1):
        tag = f"  {GREEN}← foreslått{RESET}" if a["name"] == auto else ""
        print(f"    {BOLD}{i}{RESET}  {a['name']}{tag}")
    if expired_count:
        print(f"\n    {DIM}({expired_count} utgåtte artifakter skjult){RESET}")
    print()

    raw = prompt(f"  {DIM}Velg artifact (nummer / Enter={default_idx + 1} / q=avbryt):{RESET} ")
    if raw.lower() == "q":
        return None
    idx = (int(raw) - 1) if raw.isdigit() else default_idx
    if 0 <= idx < len(non_expired):
        return non_expired[idx]["name"]
    print(f"  {YELLOW}Ugyldig valg.{RESET}")
    return None


def get_pr_branch(repo_full: str, pr_number: str) -> str | None:
    result = run(["gh", "pr", "view", pr_number, "--repo", repo_full, "--json", "headRefName"])
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout).get("headRefName")
    except json.JSONDecodeError:
        return None


def list_open_prs(repo_full: str) -> list:
    result = run([
        "gh", "pr", "list", "--repo", repo_full,
        "--state", "open",
        "--json", "number,title,headRefName,statusCheckRollup",
        "--limit", "10",
    ])
    if result.returncode != 0:
        return []
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return []


def find_playwright_bin(repo_name: str) -> str | None:
    """Finn playwright-binæren fra klonet repo sine node_modules."""
    repos_dir = Path(__file__).parent.parent / "repos" / repo_name
    for candidate in repos_dir.rglob("node_modules/.bin/playwright"):
        return str(candidate)
    return None


def _free_port(start: int = 9323) -> int:
    """Finn første ledige TCP-port fra og med start (sjekker både IPv4 og IPv6)."""
    port = start
    while port < start + 100:
        in_use = False
        for family, addr in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
            try:
                with socket.socket(family, socket.SOCK_STREAM) as s:
                    if s.connect_ex((addr, port)) == 0:
                        in_use = True
                        break
            except OSError:
                pass
        if not in_use:
            return port
        port += 1
    return start


TEXT_EXTENSIONS = {".log", ".txt", ".json", ".xml", ".csv", ".md", ".yaml", ".yml"}
LOG_MAX_LINES   = 500


def _open_downloaded_files(tmpdir: str) -> None:
    """Vis nedlastede filer og la bruker åpne én av dem."""
    all_files = sorted(Path(tmpdir).rglob("*"))
    files = [f for f in all_files if f.is_file()]
    if not files:
        print(f"  {YELLOW}Ingen filer i nedlastet artifact.{RESET}")
        print(f"  {DIM}Fjern med: rm -rf {tmpdir}{RESET}\n")
        return

    print(f"\n  {BOLD}Nedlastede filer:{RESET}\n")
    for i, f in enumerate(files, 1):
        rel = f.relative_to(tmpdir)
        size = f.stat().st_size
        size_str = f"{size // 1024} KB" if size >= 1024 else f"{size} B"
        print(f"    {BOLD}{i}{RESET}  {rel}  {DIM}({size_str}){RESET}")
    print()

    raw = prompt(f"  {DIM}Åpne fil (nummer / Enter=avbryt / q=avbryt):{RESET} ")
    if not raw or raw.lower() == "q":
        print(f"  {DIM}Midlertidig mappe: {tmpdir}{RESET}")
        print(f"  {DIM}Fjern med: rm -rf {tmpdir}{RESET}\n")
        return

    try:
        chosen = files[int(raw) - 1]
    except (ValueError, IndexError):
        print(f"  {YELLOW}Ugyldig valg.{RESET}")
        print(f"  {DIM}Fjern med: rm -rf {tmpdir}{RESET}\n")
        return

    if chosen.suffix.lower() in TEXT_EXTENSIONS:
        less_bin = shutil.which("less")
        if less_bin:
            subprocess.run([less_bin, "-R", str(chosen)], check=False)
        else:
            content = chosen.read_text(errors="replace")
            lines = content.splitlines()
            total = len(lines)
            print(f"\n  {DIM}— {chosen.name} ({total} linjer) —{RESET}\n")
            for line in lines[:LOG_MAX_LINES]:
                print(f"  {line}")
            if total > LOG_MAX_LINES:
                print(f"\n  {DIM}… +{total - LOG_MAX_LINES} linjer skjult. Åpne filen direkte: {chosen}{RESET}")
            print()
    else:
        webbrowser.open(chosen.as_uri())

    print(f"  {DIM}Midlertidig mappe: {tmpdir}{RESET}")
    print(f"  {DIM}Fjern med: rm -rf {tmpdir}{RESET}\n")


def download_and_open(repo_full: str, run_id: str):
    repo_name = repo_full.split("/")[-1]
    tmpdir = tempfile.mkdtemp(prefix="pw-report-")
    print(f"\n  {DIM}Henter artifakter for run {run_id}…{RESET}")

    artifacts = list_run_artifacts(repo_full, run_id)
    if not artifacts:
        print(f"  {RED}Ingen artifakter funnet for run {run_id}.{RESET}")
        shutil.rmtree(tmpdir, ignore_errors=True)
        return

    artifact_name = pick_artifact_interactive(artifacts)
    if not artifact_name:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return

    dl_args = ["gh", "run", "download", run_id, "--repo", repo_full,
               "-D", tmpdir, "--pattern", artifact_name]
    result = run(dl_args)
    if result.returncode != 0:
        print(f"  {RED}Kunne ikke laste ned «{artifact_name}»: {result.stderr.strip()}{RESET}")
        shutil.rmtree(tmpdir, ignore_errors=True)
        return

    # Finn index.html (ikke i trace/)
    candidates = sorted(Path(tmpdir).rglob("index.html"))
    report_html = next(
        (p for p in candidates if "trace" not in str(p)),
        candidates[0] if candidates else None,
    )

    if not report_html:
        _open_downloaded_files(tmpdir)
        return

    report_dir = report_html.parent
    pw_bin = find_playwright_bin(repo_name)

    if pw_bin:
        port = _free_port()
        print(f"  {GREEN}Starter Playwright-rapport:{RESET} {report_dir}")
        print(f"  {DIM}$ {pw_bin} show-report --port {port} {report_dir}{RESET}")
        print(f"  {DIM}(Trykk Ctrl+C for å stoppe serveren){RESET}\n")
        proc = subprocess.Popen(
            [pw_bin, "show-report", "--port", str(port), str(report_dir)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _started_procs.append(proc)
        try:
            proc.wait()
        except KeyboardInterrupt:
            _cleanup_procs()
            print(f"\n  {DIM}Server stoppet.{RESET}")
    else:
        print(f"  {YELLOW}Fant ikke playwright i {repo_name}/node_modules — repo klonet?{RESET}")
        print(f"  {DIM}Prøv: make git-clone, deretter make pnpm-install{RESET}")
        print(f"  {DIM}Åpner i nettleser som fallback…{RESET}")
        webbrowser.open(report_html.as_uri())

    print(f"  {DIM}Midlertidig mappe: {report_dir.parent}{RESET}")
    print(f"  {DIM}Fjern med: rm -rf {report_dir.parent}{RESET}\n")


def pick_repo(repos: list) -> str | None:
    if not repos:
        print(f"  {YELLOW}Ingen managed repos funnet i repos.yaml.{RESET}\n")
        return None
    print(f"\n{BOLD}Velg repo:{RESET}\n")
    for i, r in enumerate(repos, 1):
        print(f"  {BOLD}{i}{RESET}  {r['name']}")
    print()
    raw = prompt(f"{DIM}Repo (nummer / Enter=1 / q=avslutt):{RESET} ")
    if raw.lower() == "q":
        return None
    idx = int(raw) - 1 if raw.isdigit() else 0
    if idx < 0 or idx >= len(repos):
        return None
    r = repos[idx]
    return f"{r.get('org', 'navikt')}/{r['name']}"


def main():
    repo_arg = parse_arg("--repo")
    pr_arg   = parse_arg("--pr")
    run_arg  = parse_arg("--run")

    repos = parse_repos_for_artifacts()

    # Bestem repo
    if repo_arg:
        repo_full = repo_arg if "/" in repo_arg else f"navikt/{repo_arg}"
    else:
        repo_full = pick_repo(repos)
        if not repo_full:
            return

    print(f"\n  {BOLD}{repo_full}{RESET}")

    # Direkte run-ID oppgitt
    if run_arg:
        download_and_open(repo_full, run_arg)
        return

    # PR oppgitt — finn branch og siste feilede run
    if pr_arg:
        print(f"  {DIM}Henter branch for PR #{pr_arg}…{RESET}")
        branch = get_pr_branch(repo_full, pr_arg)
        if not branch:
            print(f"  {RED}Fant ikke PR #{pr_arg} i {repo_full}{RESET}")
            return
        print(f"  {DIM}Branch: {branch}{RESET}")
        run_id = find_latest_run(repo_full, branch)
    else:
        # Vis åpne PRer og la bruker velge
        print(f"  {DIM}Henter åpne PRer…{RESET}")
        prs = list_open_prs(repo_full)
        if not prs:
            print(f"  {YELLOW}Ingen åpne PRer i {repo_full}{RESET}\n")
            return
        print()
        for i, pr in enumerate(prs, 1):
            checks = pr.get("statusCheckRollup", [])
            conclusions = {c.get("conclusion") for c in checks}
            failed = "FAILURE" in conclusions or "TIMED_OUT" in conclusions
            icon = f"{RED}❌{RESET}" if failed else f"{DIM}•{RESET}"
            title = pr["title"][:60] + ("…" if len(pr["title"]) > 60 else "")
            print(f"  {BOLD}{i}{RESET}  {icon}  {DIM}#{pr['number']}{RESET}  {title}")
        print()
        raw = prompt(f"{DIM}Velg PR (nummer / q=avslutt):{RESET} ")
        if not raw or raw.lower() == "q":
            return
        try:
            pr_obj = prs[int(raw) - 1]
        except (ValueError, IndexError):
            print(f"  {YELLOW}Ugyldig valg.{RESET}")
            return
        pr_arg = str(pr_obj["number"])
        branch = pr_obj["headRefName"]
        print(f"  {DIM}Branch: {branch}{RESET}")
        run_id = find_latest_run(repo_full, branch)

    if not run_id:
        print(f"  {YELLOW}Fant ingen run på branchen.{RESET}\n")
        return

    print(f"  {DIM}Siste run: {run_id}{RESET}")
    download_and_open(repo_full, run_id)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Avbrutt.{RESET}\n")
        sys.exit(0)
