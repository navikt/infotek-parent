#!/usr/bin/env python3
"""
Interaktiv bot-/Dependabot-PR-flyt med persistent, gjenopptakbar tilstand.
Scriptet skiller GODKJENNING (ubegrenset per repo) fra den tunge OPPDATER/
MERGE-fasen (kjøres via en state-fil, én ikke-blokkerende handling per PR per
kjøring), slik at kjøringen trygt kan avbrytes (Ctrl-C) og fortsettes senere
med en ny kjøring av scriptet.

Bruk:
  python3 scripts/sheriff-interactive.py                       # velg lagret/fersk rapport, godkjenn nye kandidater, sjekk/oppdater/merge ventende
  python3 scripts/sheriff-interactive.py --output tmp/x.json    # skriv fersk rapport til egen fil
  python3 scripts/sheriff-interactive.py --report tmp/sheriff-report.json  # bruk lagret rapport, ikke kjør ny (godkjenning/oppdater/merge bruker likevel alltid fersk gh-status)
  python3 scripts/sheriff-interactive.py --dry-run              # vis/spør, men kjør aldri gh review/merge/update-branch, og skriv aldri til state-filen
  python3 scripts/sheriff-interactive.py --status               # skriv bare ut statustabellen fra state-filen — ingen rapport, ingen gh-kall, ingen spørsmål

Kandidater fra rapporten er åpne bot-/Dependabot-PR-er som ikke er draft, er
`MERGEABLE` og har grønn CI. De prioriteres i denne rekkefølgen: (1)
security-relevante non-major-oppdateringer (advisory/CVE/GHSA/dependency-
treff mot GitHub-alerts, eller "security"/"sikkerhet" i tittel/body), (2)
øvrige non-major-oppdateringer, (3) major-version-oppdateringer sist —
uansett security-relevans. Major-bumps gjenkjennes via "major" som eget ord
i tittel/branch-navn (Dependabot-grupper heter ofte f.eks. "npm-major"/
"maven-major") eller ved at selve major-tallet endres i et "Bumps X from A
to B"-mønster i tittel/body. Innenfor hver gruppe sorteres det stabilt på
repo og PR-nummer. Denne prioriterte rekkefølgen brukes både i
godkjenningsrunden og i oppdater/merge-sveipen.

**State-fil:** `tmp/sheriff-interactive-state.json` (opprettes automatisk —
`tmp/` er allerede gitignored). For hver PR brukeren har godkjent lagres
repo, PR-nummer, url, tittel, base-branch, godkjent-tidspunkt, status og
sist-sjekket-tidspunkt (samt eventuell feilmelding). Statuser:
`approved_pending_update` → `waiting_ci` → `merged`, eller `blocked` (feilet/
konflikt/rød CI — krever manuell håndtering) og `skipped` (bruker svarte
nei). `merged`/`blocked`/`skipped` er sluttilstander og røres ikke automatisk
igjen — slett/rediger raden i state-filen manuelt for å ta en `blocked`-PR
opp på nytt.

**1. Godkjenningsrunde (ubegrenset antall PR-er per repo):**
For hver kandidat i rapporten som IKKE allerede finnes i state-filen (uansett
status), vises repo, PR, tittel, URL, base-branch (PR-ens faktiske
`baseRefName` — aldri antatt til å være main/master), dependency-/body-
sammendrag, filer/diffstat, CI- og reviewstatus, samt en terminaltilpasset diff. En piltastmeny viser relevante handlinger på
hver sin linje; full diff og GitHubs Files-fane åpnes eksplisitt ved behov.

Svares det nei/hopp over: ingen kommando kjøres, PR-en lagres i state-filen
som `skipped` (spørres ikke igjen senere kjøringer). Svares det avslutt:
scriptet stopper umiddelbart, uten å gå videre til oppdater/merge-sveipen
under. Svares det ja: `gh pr review --approve` kjøres (hoppes over hvis
PR-en allerede er godkjent), og fersk `mergeStateStatus`/mergeable-status
sjekkes med én gang:

- Er PR-en verken bak base (`mergeStateStatus != BEHIND`) OG har den
  allerede grønn, ferdig CI og `mergeable == MERGEABLE`: den merges MED ÉN
  GANG her (`gh pr merge --merge --delete-branch=false`), uten noe ekstra
  spørsmål og uten å vente på oppdater/merge-sveipen. Lagres i state-filen
  direkte som `merged` (kun for oversikt), eller `blocked` hvis selve merget
  uventet feiler rett etter godkjenning.
- Trenger den derimot oppdatering mot base (`mergeStateStatus == BEHIND`)
  eller venter fortsatt på CI/mergeable-status: PR-en lagres i state-filen
  som `approved_pending_update` og behandles av den ikke-blokkerende
  oppdater/merge-sveipen under.

Det er INGEN grense på antall PR-er per repo som kan godkjennes (og evt.
merges med én gang) i én kjøring. Oppdater/merge-sveipen har heller ingen
egen per-repo-grense — den prosesserer alle state-rader som ikke er
avsluttet, ett ikke-blokkerende steg (update-branch ELLER merge) per PR per
kjøring, uansett repo.

**2. Oppdater/merge-sveip (én ikke-blokkerende handling per PR per kjøring):**
Etter godkjenningsrunden går scriptet gjennom ALLE rader i state-filen som
ikke er `merged`/`blocked`/`skipped`, én om gangen, og henter fersk status fra
`gh` for hver. Er PR-en bak base (`mergeStateStatus == BEHIND`), kjøres
`gh pr update-branch` og statusen settes til `waiting_ci` — scriptet venter
ALDRI på at ny CI skal bli ferdig, det går videre til neste PR med én gang.
Er PR-en allerede oppdatert mens CI fortsatt kjører, beholdes `waiting_ci`.
Er CI ferdig og grønn og PR-en mergeable, kjøres `gh pr merge --merge
--delete-branch=false` automatisk (siden PR-en allerede er godkjent) og
statusen settes til `merged`. Er CI rødt, er det konflikt, eller feiler
update-branch/merge, settes statusen til `blocked` med en feilmelding.
State-filen skrives til disk etter HVER statusendring (ikke bare til slutt),
slik at et avbrutt script (Ctrl-C) aldri mister fremgang.

Fordi hver PR maks får én handling (update ELLER merge) per kjøring, avslutter
standardkjøringen etter sveipen. Kjør scriptet på nytt for å følge opp PR-er
som fortsatt står i `waiting_ci`; `--watch` er et eksplisitt valg for gjentatte
sveip.

Til slutt i hver kjøring skrives en statustabell over ALLE rader i
state-filen (ikke bare denne kjøringens nye kandidater): repo, PR, tittel,
status og sist sjekket. Bruk `--status` for å se denne tabellen alene, uten
å gjøre noe annet.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import webbrowser
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from terminal_ui import choose, choose_cached_report, clear_screen, enter_alt_screen, exit_alt_screen, format_age, github_alert_counts, nais_alert_counts, print_table

ROOT = Path(__file__).resolve().parent.parent
REPOS_DIR = ROOT / "repos"
REPORT_SCRIPT = ROOT / "scripts" / "nais-vulnerability-report.py"
DEFAULT_REPORT = ROOT / "tmp" / "sheriff-report.json"
STATE_PATH = ROOT / "tmp" / "sheriff-interactive-state.json"
CONFIG_FILE = ROOT / "config.json"
REPORT_FRESHNESS_SECONDS = 15 * 60
REPORT_SCHEMA_VERSION = 7


def _load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


# Samme config.json-nøkler som scripts/pr-behandle.py bruker, slik at
# merge-oppførselen er konsistent på tvers av begge verktøyene.
_PR_CFG = _load_config().get("pr", {})
MERGE_STRATEGY = _PR_CFG.get("merge_strategy", "squash")
DELETE_BRANCH_ON_MERGE = _PR_CFG.get("delete_branch_on_merge", True)

ALLOWED_CONCLUSIONS = {"SUCCESS", "NEUTRAL", "SKIPPED"}
ADVISORY_PATTERN = re.compile(
    r"\b(CVE-\d{4}-\d+|GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4})\b", re.IGNORECASE
)
BUMP_PATTERN = re.compile(r"[Bb]umps?\s+(\S+)\s+from\s+([\w.\-]+)\s+to\s+([\w.\-]+)")
MAJOR_KEYWORD_PATTERN = re.compile(r"\bmajor\b", re.IGNORECASE)
FRESH_PR_FIELDS = (
    "number,title,url,isDraft,mergeable,mergeStateStatus,reviewDecision,"
    "statusCheckRollup,reviews,baseRefName,headRefName,state,mergedAt,closed"
)

STATUS_APPROVED_PENDING_UPDATE = "approved_pending_update"
STATUS_WAITING_CI = "waiting_ci"
STATUS_MERGED = "merged"
STATUS_BLOCKED = "blocked"
STATUS_SKIPPED = "skipped"
TERMINAL_STATUSES = {STATUS_MERGED, STATUS_BLOCKED, STATUS_SKIPPED}

BOLD = "\033[1m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
DIM = "\033[2m"
RESET = "\033[0m"

# Samme ikonspråk som scripts/pr-behandle.py sin state_icon(), gjenbrukt her
# for gjenkjennelig status på tvers av begge verktøyene.
STATUS_ICONS = {
    STATUS_MERGED: GREEN + "✅" + RESET,
    STATUS_WAITING_CI: YELLOW + "🔄" + RESET,
    STATUS_APPROVED_PENDING_UPDATE: CYAN + "⬆️ " + RESET,
    STATUS_BLOCKED: RED + "🔒" + RESET,
    STATUS_SKIPPED: DIM + "⏸" + RESET,
}


def status_icon(status: str) -> str:
    return STATUS_ICONS.get(status, DIM + "?" + RESET)


@dataclass(frozen=True)
class Candidate:
    org: str
    name: str
    pr: dict

    @property
    def slug(self) -> str:
        return f"{self.org}/{self.name}"

    @property
    def number(self) -> int:
        return int(self.pr["number"])

    @property
    def base_ref(self) -> str:
        return str(self.pr.get("baseRefName") or "ukjent base")


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def gh_json(*arguments: str) -> object:
    result = run(["gh", *arguments])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "gh-kommandoen feilet")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Klarte ikke å tolke gh-svaret: {error}") from error


def is_bot(pr: dict) -> bool:
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


def checks_are_completed(checks: object) -> bool:
    return isinstance(checks, list) and bool(checks) and all(
        isinstance(check, dict) and check.get("status") == "COMPLETED" for check in checks
    )


def failed_check_names(pr: dict) -> list[str]:
    checks = pr.get("statusCheckRollup") or []
    return [
        c.get("name", "ukjent")
        for c in checks
        if isinstance(c, dict) and c.get("conclusion") in ("FAILURE", "TIMED_OUT", "ERROR")
    ]


def is_mergeable_candidate(pr: dict) -> bool:
    """Avgjør om en PR skal tas med som kandidat for *godkjenning* i det hele
    tatt. Krever bevisst IKKE grønn CI eller `mergeable == MERGEABLE` her —
    de kravene gjelder kun for selve merge-øyeblikket (sjekkes separat rett
    før `gh pr merge`, både i godkjenningsrundens hurtigmerge og i
    oppdater/merge-sveipen). En PR med rød/feilet CI, som er BEHIND, eller
    som er CONFLICTING, skal fortsatt vises og kunne godkjennes her — akkurat
    som scripts/pr-behandle.py viser og lar brukeren godkjenne slike PR-er
    (med [r] rerun CI/[u] update-branch tilgjengelig via den senere
    blocked-menyen). Uten denne relaxeringen ble PR-er med feilet CI aldri
    plukket opp av scriptet i det hele tatt."""
    return isinstance(pr, dict) and not pr.get("isDraft") and is_bot(pr)


def describe_blocked_reason(fresh: dict) -> str | None:
    """Gjenkjenner GitHubs eget `mergeStateStatus == 'BLOCKED'` (typisk
    uløste review-tråder eller manglende påkrevde godkjenninger utover det
    scriptet selv har gitt) FØR merge forsøkes, slik at diagnosen matcher
    samme kategori som scripts/pr-behandle.py sin `pr_state()`/`STATE_HINT`
    ('blokkert — uleste kommentarer') i stedet for en generisk
    'merge feilet'-melding etter et mislykket forsøk. Returnerer None hvis
    PR-en ikke er GitHub-blokkert."""
    if fresh.get("mergeStateStatus") != "BLOCKED":
        return None
    return (
        "GitHub rapporterer mergeStateStatus=BLOCKED — sannsynligvis uløste "
        "review-kommentarer/tråder eller manglende påkrevde godkjenninger "
        "utover denne godkjenningen (samme diagnose som 'make pr' viser som "
        "🔒 blokkert — uleste kommentarer). Krever manuell håndtering i "
        "GitHub-UI-et før merge er mulig."
    )


def load_report(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Kunne ikke lese rapporten {path}: {error}") from error
    if not isinstance(data, dict):
        raise RuntimeError(f"Rapporten {path} har ugyldig format.")
    if data.get("schema_version") != REPORT_SCHEMA_VERSION:
        raise RuntimeError(
            f"Rapporten {path} har feil versjon. Lag en ny rapport med make sheriff eller make review."
        )
    if not isinstance(data.get("scope", {}).get("repositories"), list) or not isinstance(data.get("repositories"), dict):
        raise RuntimeError(
            f"Rapporten {path} mangler repository-data. Lag en ny rapport med make sheriff eller make review."
        )
    return data


def managed_repositories(report: dict) -> list[dict]:
    entries = (report.get("scope") or {}).get("repositories") or []
    if not isinstance(entries, list):
        return []
    return [
        entry
        for entry in entries
        if isinstance(entry, dict)
        and entry.get("managed", True)
        and not entry.get("dependabot_skip")
        and not entry.get("pr_skip")
    ]


def advisory_terms(details: dict) -> set[str]:
    terms: set[str] = set()
    github = details.get("github") or {}
    dependabot = github.get("dependabot") or {}
    if dependabot.get("status") == "ok":
        for alert in dependabot.get("items") or []:
            if not isinstance(alert, dict):
                continue
            for key in ("dependency", "cve", "ghsa"):
                value = alert.get(key)
                if isinstance(value, str) and value.strip():
                    terms.add(value.strip().lower())
    return terms


def is_security_relevant(pr: dict, terms: set[str]) -> bool:
    haystack = f"{pr.get('title', '')}\n{pr.get('body', '')}".lower()
    if ADVISORY_PATTERN.search(haystack):
        return True
    if "security" in haystack or "sikkerhet" in haystack:
        return True
    return any(term and term in haystack for term in terms)


def leading_major(version: str) -> str | None:
    match = re.match(r"\d+", version.strip())
    return match.group(0) if match else None


def is_major_version_bump(pr: dict) -> bool:
    """Gjenkjenner major-version-oppdateringer for nedprioritering.

    To signaler brukes: (1) "major" som eget ord i tittel eller branch-navn
    (Dependabot-grupper heter ofte f.eks. "npm-major"/"maven-major"), og
    (2) et "Bumps X from A to B"-mønster (i tittel eller body) der selve
    major-tallet i versjonen faktisk endres.
    """
    title = pr.get("title") or ""
    branch = pr.get("headRefName") or ""
    if MAJOR_KEYWORD_PATTERN.search(f"{title}\n{branch}"):
        return True
    for text_source in (title, pr.get("body") or ""):
        match = BUMP_PATTERN.search(text_source)
        if not match:
            continue
        _, old_version, new_version = match.groups()
        old_major, new_major = leading_major(old_version), leading_major(new_version)
        if old_major is not None and new_major is not None and old_major != new_major:
            return True
    return False


def build_candidates(report: dict) -> list[tuple[Candidate, bool, bool]]:
    """Returnerer (candidate, security_relevant, is_major_bump) sortert med
    major-version-oppdateringer sist: security-relevante non-major først,
    deretter øvrige non-major, deretter major-bumps til slutt (stabilt på
    repo og PR-nummer innenfor hver gruppe)."""
    repositories = report.get("repositories") or {}
    candidates: list[tuple[Candidate, bool, bool]] = []
    for entry in managed_repositories(report):
        name = entry.get("name")
        if not isinstance(name, str):
            continue
        org = entry.get("org", "navikt")
        details = repositories.get(name)
        if not isinstance(details, dict):
            continue
        prs_result = details.get("dependabot_prs") or {}
        if prs_result.get("status") != "ok":
            continue
        terms = advisory_terms(details)
        for pr in prs_result.get("items") or []:
            if not is_mergeable_candidate(pr):
                continue
            candidates.append((
                Candidate(org, name, pr),
                is_security_relevant(pr, terms),
                is_major_version_bump(pr),
            ))
    candidates.sort(key=lambda item: (item[2], not item[1], item[0].slug, item[0].number))
    return candidates


def alert_counts(report: dict, candidate: Candidate) -> tuple[int, int]:
    repository = (
        report.get("repositories", {})
        .get(candidate.name, {})
    )
    return github_alert_counts(repository)


def candidate_table_rows(report: dict, candidates: list[tuple[Candidate, bool, bool]]) -> tuple[tuple[str, ...], list[tuple[str, ...]]]:
    rows = []
    for candidate, security_relevant, is_major in candidates:
        priority = "Sikkerhet" if security_relevant else "Vanlig"
        if is_major:
            priority = "Major sist"
        critical, high = alert_counts(report, candidate)
        nais_critical, nais_high = nais_alert_counts(report.get("repositories", {}).get(candidate.name, {}))
        rows.append((
            priority,
            candidate.name,
            f"#{candidate.number}",
            str(candidate.pr.get("title", "-")),
            f"{critical}/{high}",
            f"{nais_critical if nais_critical is not None else '-'}/{nais_high if nais_high is not None else '-'}",
        ))
    return ("Prioritet", "Repo", "PR", "Tittel", "GH C/H", "Nais C/H"), rows


def show_candidate_table(report: dict, candidates: list[tuple[Candidate, bool, bool]]) -> str:
    headers, rows = candidate_table_rows(report, candidates)
    print_table(
        f"Sheriff — {len(rows)} kandidater i prioritert rekkefølge",
        headers,
        rows,
        "Sikkerhetsrelevante oppdateringer behandles først. Major-oppdateringer behandles sist.",
    )
    return choose(
        "Sheriff",
        [
            ("start", "Start review i prioritert rekkefølge", "s"),
            ("summary", "Vis sammendragsrapport", "o"),
            ("refresh", "Hent ny rapport", "r"),
            ("quit", "Avslutt", "q"),
        ],
    )


def show_report_summary(report_path: Path) -> bool:
    subprocess.run([sys.executable, str(REPORT_SCRIPT), "--show", "--output", str(report_path)], check=False)
    return choose(
        "Sammendragsrapport",
        [("back", "Tilbake til sheriff", "b"), ("quit", "Avslutt", "q")],
    ) != "quit"


def dependency_summary(pr: dict) -> str:
    match = BUMP_PATTERN.search(pr.get("title") or "")
    if match:
        dependency, old, new = match.groups()
        return f"{dependency}: {old} → {new}"
    body = (pr.get("body") or "").strip()
    first_line = next((line.strip() for line in body.splitlines() if line.strip()), "")
    return first_line[:160] if first_line else "(ingen tittel-/bodymønster funnet)"


def summarize_files(pr: dict) -> tuple[str, list[str]]:
    files = pr.get("files") or []
    names = [f.get("path") for f in files if isinstance(f, dict) and f.get("path")]
    changed = pr.get("changedFiles")
    additions = pr.get("additions")
    deletions = pr.get("deletions")
    stat = (
        f"{changed} fil(er), +{additions}/-{deletions}"
        if changed is not None
        else "diffstat ukjent"
    )
    if names:
        return stat, names
    return stat, []


def fetch_pr_diff(candidate: Candidate) -> str:
    result = run(["gh", "pr", "diff", str(candidate.number), "--repo", candidate.slug])
    if result.returncode != 0:
        return f"(kunne ikke hente diff: {result.stderr.strip() or 'ukjent feil'})"
    return result.stdout


def colorize_diff(lines: list[str]) -> str:
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
    return "\n".join(colored)


def format_diff_full(diff: str) -> str:
    lines = diff.splitlines()
    if not lines:
        return f"  {DIM}Ingen diff tilgjengelig.{RESET}"
    return colorize_diff(lines)


def fetch_pr_status(candidate: Candidate) -> dict:
    data = gh_json(
        "pr", "view", str(candidate.number), "--repo", candidate.slug, "--json", FRESH_PR_FIELDS
    )
    if not isinstance(data, dict):
        raise RuntimeError("Uventet svar fra gh pr view.")
    return data


def print_header(text: str) -> None:
    print(f"\n{BOLD}{text}{RESET}")


def print_candidate(
    candidate: Candidate, index: int, total: int, security_relevant: bool, is_major: bool
) -> None:
    pr = candidate.pr
    print_header(f"Kandidat {index}/{total}: {candidate.slug}#{candidate.number}")

    diff = fetch_pr_diff(candidate)
    print_header(f"Diff ({len(diff.splitlines())} linjer)")
    print(format_diff_full(diff))
    checks = pr.get("statusCheckRollup") or []
    ci_state = f"{GREEN}grønn{RESET}" if checks_are_green(checks) else f"{RED}ikke grønn{RESET}"
    review = pr.get("reviewDecision") or "ingen"
    priority = "security" if security_relevant else "vanlig"
    if is_major:
        priority = f"{YELLOW}major sist{RESET}"
    file_stat, files = summarize_files(pr)
    print_header("Sammendrag")
    print(f"  {pr.get('title', '-')}  {DIM}→ {candidate.base_ref}{RESET}")
    print(
        f"  CI {ci_state} ({len(checks)})  ·  review {review}  ·  "
        f"merge {pr.get('mergeable', '-')} / {pr.get('mergeStateStatus', '-')}"
    )
    print(f"  {dependency_summary(pr)}  ·  {file_stat}  ·  prioritet {priority}")
    if files:
        print(f"  {DIM}Endrede filer:{RESET}")
        for path in files:
            print(f"    {path}")
    return diff


def prompt_approval_action(candidate: Candidate, question: str, pr: dict, diff: str) -> str:
    """Ja/nei/avslutt-spørsmål om godkjenning, men tilbyr i tillegg
    handlinger man ofte trenger for å avgjøre om en PR som IKKE er i
    ferdig-til-update/godkjenne/merge-tilstand skal godkjennes nå: åpne i
    nettleser, sjekke ut branchen lokalt, rerun av feilede sjekker (når CI
    faktisk er fullført og rød) og update-branch (når PR-en er BEHIND) —
    samme handlinger som scripts/pr-behandle.py tilbyr. Vises uansett hvilken
    av disse grunnene som gjør at PR-en ikke er klar ennå.

    En vellykket `[u]`/`[r]`-handling tar tid å bli synlig hos GitHub (ny CI-
    kjøring/omregnet mergeability), så i stedet for å spørre om akkurat
    samme PR igjen med én gang, returneres sentinelen `'senere'` — chargeren
    (run_approval_round) skal da legge kandidaten bakerst i køen og gå videre
    til neste kandidat/repo, og komme tilbake til denne senere i samme
    kjøring.

    Svarer brukeren 'ja' mens PR-en fortsatt har kjente mangler (BEHIND eller
    merge-konflikt — CI-feil blokkerer godkjenning helt, se under), skrives
    en eksplisitt advarsel ut FØR svaret returneres, slik at brukeren ikke
    godkjenner et åpenbart ikke-klart PR ved et uhell.

    `[j]` (godkjenn) tilbys kun som valg når forrige fullførte CI-kjøring gikk
    grønn — er siste fullførte kjøring rød, er 'j' ikke et gyldig svar før
    brukeren har kjørt `[r]` (rerun CI) og den nye kjøringen er grønn (eller
    fortsatt kjører). CI som ennå ikke er fullført blokkerer ikke godkjenning
    i seg selv (vi vet ikke ennå om den blir rød), men gir fortsatt en
    advarsel ved 'ja'.

    Returnerer 'ja', 'nei', 'avslutt' eller 'senere'."""
    while True:
        checks = pr.get("statusCheckRollup") or []
        checks_running = not checks_are_completed(checks)
        checks_failed = checks_are_completed(checks) and not checks_are_green(checks)
        is_behind = pr.get("mergeStateStatus") == "BEHIND"
        is_conflicting = pr.get("mergeable") == "CONFLICTING"
        approve_allowed = not checks_failed
        if checks_failed:
            failed = failed_check_names(pr)
            if failed:
                print(f"  {RED}Feilet: {', '.join(failed)}{RESET}")
            print(
                f"  {RED}✗ Godkjenning er ikke tilgjengelig — forrige fullførte CI-kjøring var "
                f"rød. Kjør [r] rerun CI først.{RESET}"
            )
        if is_conflicting:
            print(f"  {RED}⚡ merge-konflikt med base{RESET}")
        options = []
        if approve_allowed:
            options.append(("ja", "Godkjenn", "g"))
        options.append(("nei", "Hopp over", "h"))
        options.append(("nettleser", "Åpne PR i nettleser", "n"))
        options.append(("sjekk-ut", "Sjekk ut branchen lokalt", "s"))
        if is_behind:
            options.append(("oppdater", "Oppdater branch mot base", "o"))
        if checks_failed:
            options.append(("rerun", "Kjør feilede CI-sjekker på nytt", "r"))
        options.append(("avslutt", "Avslutt sheriff", "q"))
        try:
            action = choose(question, options)
        except (EOFError, KeyboardInterrupt):
            return "avslutt"
        if action == "nettleser":
            webbrowser.open(pr.get("url") or "")
            continue
        if action == "sjekk-ut":
            checkout_pr_locally(candidate)
            continue
        if action == "oppdater":
            update_ok, _ = do_update_branch(candidate, False)
            if update_ok:
                print(
                    f"  {CYAN}→ Update-branch sendt. Går videre til neste kandidat — kommer "
                    f"tilbake til denne senere i denne kjøringen.{RESET}"
                )
                return "senere"
            continue
        if action == "rerun":
            rerun_ok, _ = do_rerun_failed_checks(candidate)
            if rerun_ok:
                print(
                    f"  {CYAN}→ Rerun startet. Går videre til neste kandidat — kommer tilbake "
                    f"til denne senere i denne kjøringen.{RESET}"
                )
                return "senere"
            continue
        if action == "ja":
            resolved = "ja"
            if checks_running or is_behind or is_conflicting:
                problems = []
                if checks_running:
                    problems.append("CI kjører fortsatt")
                if is_behind:
                    problems.append("branchen er bak base (BEHIND)")
                if is_conflicting:
                    problems.append("merge-konflikt med base")
                print(
                    f"  {YELLOW}⚠️  Godkjenner en PR som ikke er klar ennå: {', '.join(problems)}."
                    f"{RESET}"
                )
            return resolved
        return action


def show_command(command: list[str]) -> str:
    return " ".join(command)


def do_update_branch(candidate: Candidate, dry_run: bool) -> tuple[bool, str | None]:
    """Oppdaterer PR-branchen mot PR-ens faktiske base (`gh pr update-branch`).
    Returnerer (suksess, feilmelding)."""
    command = ["gh", "pr", "update-branch", str(candidate.number), "--repo", candidate.slug]
    print(f"  Oppdaterer {candidate.slug}#{candidate.number} mot base '{candidate.base_ref}'.")
    print(f"  Kommando: {show_command(command)}")
    if dry_run:
        print(f"  {YELLOW}DRY-RUN{RESET}: kjører ikke kommandoen.")
        return False, None
    try:
        result = run(command)
    except OSError as error:
        message = f"Kunne ikke kjøre gh (sandbox/blokkert?): {error}"
        print(f"  ⚠️  {message}")
        print(f"  Kjør kommandoen selv: {show_command(command)}")
        return False, message
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip() or "gh pr update-branch feilet uten meldingstekst."
        print(f"  ⚠️  gh pr update-branch feilet: {message}")
        print(f"  Kjør kommandoen selv om nødvendig: {show_command(command)}")
        return False, message
    print(f"  {GREEN}✓ Update-branch sendt.{RESET}")
    return True, None


def do_approve(candidate: Candidate, dry_run: bool) -> tuple[bool, str | None]:
    """Godkjenner PR-en (`gh pr review --approve`). Returnerer (suksess, feilmelding)."""
    command = ["gh", "pr", "review", str(candidate.number), "--repo", candidate.slug, "--approve"]
    print(f"  Kommando: {show_command(command)}")
    if dry_run:
        print(f"  {YELLOW}DRY-RUN{RESET}: kjører ikke kommandoen.")
        return False, None
    try:
        result = run(command)
    except OSError as error:
        message = f"Kunne ikke kjøre gh (sandbox/blokkert?): {error}"
        print(f"  ⚠️  {message}")
        print(f"  Kjør kommandoen selv: {show_command(command)}")
        return False, message
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip() or "gh pr review feilet uten meldingstekst."
        print(f"  ⚠️  gh pr review feilet: {message}")
        print(f"  Kjør kommandoen selv om nødvendig: {show_command(command)}")
        return False, message
    print(f"  {GREEN}✓ Godkjent.{RESET}")
    return True, None


def do_merge(candidate: Candidate, dry_run: bool) -> tuple[bool, str | None]:
    """Merger PR-en med samme merge-strategi/delete-branch-config som
    scripts/pr-behandle.py bruker (config.json: pr.merge_strategy,
    pr.delete_branch_on_merge). Returnerer (suksess, feilmelding)."""
    command = [
        "gh", "pr", "merge", str(candidate.number), "--repo", candidate.slug,
        f"--{MERGE_STRATEGY}",
    ]
    command.append("--delete-branch" if DELETE_BRANCH_ON_MERGE else "--delete-branch=false")
    print(f"  Kommando: {show_command(command)}")
    if dry_run:
        print(f"  {YELLOW}DRY-RUN{RESET}: kjører ikke kommandoen.")
        return False, None
    try:
        result = run(command)
    except OSError as error:
        message = f"Kunne ikke kjøre gh (sandbox/blokkert?): {error}"
        print(f"  ⚠️  {message}")
        print(f"  Kjør kommandoen selv: {show_command(command)}")
        return False, message
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip() or "gh pr merge feilet uten meldingstekst."
        print(f"  ⚠️  gh pr merge feilet: {message}")
        print(f"  Kjør kommandoen selv om nødvendig: {show_command(command)}")
        return False, message
    print(f"  {GREEN}✓ Merget.{RESET}")
    return True, None


def checkout_pr_locally(candidate: Candidate) -> tuple[bool, str | None]:
    """Henter PR-branchen ned lokalt i repos/<name> (samme layout som
    `make git-clone` bruker), slik at PR-en kan inspiseres/fikses manuelt.
    Bruker `gh pr checkout`, som fungerer også når repoet fra før er klonet
    med en annen remote-konfigurasjon. Returnerer (suksess, feilmelding)."""
    repo_dir = REPOS_DIR / candidate.name
    if not repo_dir.is_dir():
        message = (
            f"{repo_dir} finnes ikke lokalt. Klon parent-oppsettet først med "
            "`make git-clone`."
        )
        print(f"  ⚠️  {message}")
        return False, message
    command = ["gh", "pr", "checkout", str(candidate.number), "--repo", candidate.slug]
    print(f"  Kommando (i {repo_dir}): {show_command(command)}")
    try:
        result = subprocess.run(command, cwd=repo_dir, capture_output=True, text=True, check=False)
    except OSError as error:
        message = f"Kunne ikke kjøre gh (sandbox/blokkert?): {error}"
        print(f"  ⚠️  {message}")
        return False, message
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip() or "gh pr checkout feilet uten meldingstekst."
        print(f"  ⚠️  gh pr checkout feilet: {message}")
        return False, message
    print(f"  {GREEN}✓ Byttet til PR-branchen lokalt i {repo_dir}.{RESET}")
    return True, None


def do_rerun_failed_checks(candidate: Candidate) -> tuple[bool, str | None]:
    """Rerunner alle feilede/timeoutede checks for PR-branchen, samme
    mønster som scripts/pr-behandle.py sin `[r] Rerun CI`."""
    branch = candidate.pr.get("headRefName")
    if not branch:
        return False, "Fant ikke headRefName for PR-en."
    runs_result = run(
        [
            "gh", "run", "list", "--repo", candidate.slug, "--branch", str(branch),
            "--json", "databaseId,conclusion", "--limit", "20",
        ]
    )
    if runs_result.returncode != 0:
        message = (runs_result.stderr or runs_result.stdout or "").strip() or "gh run list feilet."
        print(f"  ⚠️  {message}")
        return False, message
    try:
        runs = json.loads(runs_result.stdout)
    except json.JSONDecodeError as error:
        return False, f"Klarte ikke å tolke gh run list-svaret: {error}"
    failed_ids = [str(r["databaseId"]) for r in runs if r.get("conclusion") in ("failure", "timed_out")]
    if not failed_ids:
        print(f"  {YELLOW}Fant ingen feilede runs å kjøre på nytt.{RESET}")
        return False, "Ingen feilede runs funnet."
    ok = True
    error_message = None
    for run_id in failed_ids:
        command = ["gh", "run", "rerun", run_id, "--failed", "--repo", candidate.slug]
        print(f"  Kommando: {show_command(command)}")
        result = run(command)
        if result.returncode != 0:
            ok = False
            error_message = (result.stderr or result.stdout or "").strip() or "gh run rerun feilet."
            print(f"  ⚠️  {error_message}")
        else:
            print(f"  {GREEN}✓ Rerun startet for run {run_id}.{RESET}")
    return ok, error_message


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def state_key(org: str, name: str, number: int) -> str:
    return f"{org}/{name}#{number}"


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"prs": {}}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        print(f"⚠️  Kunne ikke lese state-filen {path}: {error}. Starter med tom state.", file=sys.stderr)
        return {"prs": {}}
    if not isinstance(data, dict) or not isinstance(data.get("prs"), dict):
        print(f"⚠️  State-filen {path} har uventet format. Starter med tom state.", file=sys.stderr)
        return {"prs": {}}
    return data


def save_state(path: Path, state: dict) -> None:
    """Skriver state-filen atomisk (temp-fil + replace), slik at Ctrl-C aldri
    kan etterlate en delvis skrevet/korrupt state-fil."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    tmp_path.replace(path)


def new_state_entry(
    candidate: Candidate,
    known: dict,
    status: str,
    approved_at: str | None,
    security_relevant: bool,
    major_bump: bool,
) -> dict:
    return {
        "org": candidate.org,
        "repo": candidate.name,
        "number": candidate.number,
        "url": known.get("url") or candidate.pr.get("url"),
        "title": known.get("title") or candidate.pr.get("title"),
        "base_ref": known.get("baseRefName") or candidate.base_ref,
        "approved_at": approved_at,
        "status": status,
        "last_checked_at": now_iso(),
        "error": None,
        "security_relevant": security_relevant,
        "major_bump": major_bump,
    }


def candidate_from_state_entry(entry: dict) -> Candidate:
    pr = {
        "number": entry["number"],
        "baseRefName": entry.get("base_ref"),
        "title": entry.get("title"),
        "url": entry.get("url"),
    }
    return Candidate(entry["org"], entry["repo"], pr)


def print_status_table(state: dict) -> None:
    entries: dict = state.get("prs") or {}
    if not entries:
        print("\nIngen PR-er i state-filen ennå.")
        return
    headers = ("Repo", "PR", "Tittel", "Major", "Status", "Sist sjekket")
    rows = []
    blocked_rows = []
    for key in sorted(entries):
        entry = entries[key]
        title = (entry.get("title") or "-")
        if len(title) > 50:
            title = title[:47] + "..."
        status = entry.get("status", "?")
        rows.append((
            f"{entry.get('org', '?')}/{entry.get('repo', '?')}",
            f"#{entry.get('number', '?')}",
            title,
            "ja" if entry.get("major_bump") else "nei",
            status,
            entry.get("last_checked_at") or "-",
        ))
        if status == STATUS_BLOCKED and entry.get("error"):
            blocked_rows.append((key, entry.get("url") or "-", entry.get("error")))
    widths = [
        max(len(headers[i]), max((len(row[i]) for row in rows), default=0))
        for i in range(len(headers))
    ]

    def fmt_row(row: tuple[str, ...], icon: str = "") -> str:
        return icon + "  ".join(str(value).ljust(width) for value, width in zip(row, widths))

    print_header(f"Statustabell ({len(rows)} PR-er i state-filen: {STATE_PATH.relative_to(ROOT)})")
    print("   " + fmt_row(headers))
    print("   " + fmt_row(tuple("-" * w for w in widths)))
    for key, row in zip(sorted(entries), rows):
        icon = status_icon(entries[key].get("status", "?"))
        print(f"{icon} {fmt_row(row)}")

    if blocked_rows:
        print(f"\n{RED}Blokkerte PR-er — krever manuell håndtering:{RESET}")
        for key, url, error in blocked_rows:
            print(f"  {RED}✗{RESET} {key}: {error}")
            print(f"    {DIM}{url}{RESET}")



def run_approval_round(
    candidates: list[tuple[Candidate, bool, bool]], state: dict, state_path: Path, dry_run: bool
) -> bool:
    """Spør om godkjenning for alle kandidater som ikke allerede finnes i
    state-filen, i prioritert rekkefølge (security-relevante non-major
    først, deretter øvrige non-major, deretter major-bumps sist — se
    build_candidates). Ubegrenset antall PR-er per repo. Er en PR verken bak
    base eller venter på CI når den godkjennes, merges den med én gang her —
    ellers lagres den som `approved_pending_update` og behandles av den
    ikke-blokkerende oppdater/merge-sveipen etterpå.

    Svarer prompt_approval_action med `'senere'` (etter en vellykket
    `[u]`/`[r]`-handling som trenger tid før den er synlig hos GitHub),
    legges kandidaten bakerst i køen i stedet for å spørres på nytt med én
    gang — brukeren går videre til neste kandidat/repo og kommer tilbake til
    denne senere i samme kjøring, når CI/mergeability forhåpentligvis har
    rukket å oppdatere seg.

    Returnerer True hvis brukeren ba om å avslutte hele scriptet."""
    known_keys = set(state["prs"])
    queue: deque = deque(
        (candidate, security_relevant, is_major)
        for candidate, security_relevant, is_major in candidates
        if state_key(candidate.org, candidate.name, candidate.number) not in known_keys
    )

    if not queue:
        print("\nIngen nye, ukjente kandidater å vurdere for godkjenning denne kjøringen.")
        return False

    total = len(queue)
    print(
        f"\n{total} ny(e) kandidat(er) å vurdere for godkjenning, i prioritert "
        "rekkefølge (security-relevante non-major først, major-bumps sist). Ingen grense per "
        "repo for godkjenning."
    )

    processed = 0
    deferred_keys: set[str] = set()
    while queue:
        candidate, security_relevant, is_major = queue.popleft()
        key = state_key(candidate.org, candidate.name, candidate.number)
        processed += 1
        clear_screen()
        diff = print_candidate(candidate, processed, max(total, processed + len(queue)), security_relevant, is_major)

        try:
            known = fetch_pr_status(candidate)
        except RuntimeError as error:
            print(f"  ⚠️  Kunne ikke hente fersk PR-status: {error}")
            known = candidate.pr

        already_approved = known.get("reviewDecision") == "APPROVED"
        if already_approved:
            print(f"\n  Status: {GREEN}allerede godkjent{RESET}.")

        choice = prompt_approval_action(
            candidate, f"Velg handling for {candidate.slug}#{candidate.number}", known, diff
        )

        if choice == "avslutt":
            return True

        if choice == "senere":
            if key in deferred_keys:
                print(
                    f"  {YELLOW}⚠️  {candidate.slug}#{candidate.number} er allerede utsatt én gang "
                    f"denne kjøringen uten andre kandidater igjen å behandle i mellomtiden — "
                    f"spør likevel på nytt med én gang.{RESET}"
                )
                queue.appendleft((candidate, security_relevant, is_major))
            else:
                deferred_keys.add(key)
                queue.append((candidate, security_relevant, is_major))
            continue

        if choice == "nei":
            print("  Hopper over — lagres som 'skipped' i state-filen (spørres ikke igjen).")
            if not dry_run:
                state["prs"][key] = new_state_entry(
                    candidate, known, STATUS_SKIPPED, None, security_relevant, is_major
                )
                save_state(state_path, state)
            continue

        if already_approved:
            print("  Allerede godkjent — hopper over gh pr review --approve.")
        else:
            approve_ok, _approve_error = do_approve(candidate, dry_run)
            if not approve_ok:
                if dry_run:
                    pass
                else:
                    print(
                        f"  {RED}✗ Godkjenning feilet — hopper over denne PR-en denne kjøringen "
                        f"(spørres på nytt neste kjøring).{RESET}"
                    )
                    continue

        if dry_run:
            print(
                f"  {YELLOW}DRY-RUN{RESET}: skriver ikke til state-filen, sjekker/merger ikke "
                "direkte."
            )
            continue

        # Sjekk fersk mergeable-status rett etter godkjenning: er PR-en verken
        # bak base ELLER venter på CI, merges den med én gang her — uten å
        # gå veien om den senere oppdater/merge-sveipen.
        try:
            fresh = fetch_pr_status(candidate)
        except RuntimeError as error:
            print(f"  ⚠️  Kunne ikke hente fersk status etter godkjenning: {error}.")
            fresh = known

        checks = fresh.get("statusCheckRollup") or []
        blocked_reason = describe_blocked_reason(fresh)
        ready_to_merge_now = (
            blocked_reason is None
            and fresh.get("mergeStateStatus") != "BEHIND"
            and fresh.get("mergeable") == "MERGEABLE"
            and checks_are_completed(checks)
            and checks_are_green(checks)
        )

        if blocked_reason:
            entry = new_state_entry(
                candidate, fresh, STATUS_BLOCKED, now_iso(), security_relevant, is_major
            )
            entry["error"] = blocked_reason
            state["prs"][key] = entry
            save_state(state_path, state)
            print(f"  {RED}✗ Godkjent, men {blocked_reason}{RESET}")
            continue

        if ready_to_merge_now:
            print("  PR-en er allerede oppdatert mot base og har grønn CI.")
            try:
                ans = input("  Merge nå? [J/n] ").strip().lower()
            except EOFError:
                print("  … stdin tom — hopper over merge nå.")
                ans = "n"
            if ans and ans != "j":
                state["prs"][key] = new_state_entry(
                    candidate,
                    fresh,
                    STATUS_APPROVED_PENDING_UPDATE,
                    now_iso(),
                    security_relevant,
                    is_major,
                )
                save_state(state_path, state)
                print(
                    f"  {GREEN}✓ Godkjent.{RESET} Merge ble ikke bekreftet — "
                    f"lagt til som '{STATUS_APPROVED_PENDING_UPDATE}'."
                )
                continue
            merge_ok, merge_error = do_merge(candidate, False)
            if merge_ok:
                state["prs"][key] = new_state_entry(
                    candidate, fresh, STATUS_MERGED, now_iso(), security_relevant, is_major
                )
                save_state(state_path, state)
                print(f"  {GREEN}✓ Godkjent og merget med én gang.{RESET}")
            else:
                entry = new_state_entry(
                    candidate, fresh, STATUS_BLOCKED, now_iso(), security_relevant, is_major
                )
                entry["error"] = merge_error or "merge feilet rett etter godkjenning."
                state["prs"][key] = entry
                save_state(state_path, state)
                print(
                    f"  {RED}✗ Merge feilet rett etter godkjenning — lagret som 'blocked', "
                    f"krever manuell håndtering.{RESET}"
                )
            continue

        state["prs"][key] = new_state_entry(
            candidate, fresh, STATUS_APPROVED_PENDING_UPDATE, now_iso(), security_relevant, is_major
        )
        save_state(state_path, state)
        reason = (
            "bak base"
            if fresh.get("mergeStateStatus") == "BEHIND"
            else "venter fortsatt på CI/mergeable-status"
        )
        print(
            f"  {GREEN}✓ Godkjent.{RESET} PR-en {reason} — lagt til i state-filen som "
            f"'{STATUS_APPROVED_PENDING_UPDATE}', behandles i oppdater/merge-sveipen."
        )

    return False


def process_pending_entry(entry: dict, dry_run: bool, state: dict, state_path: Path) -> None:
    """Behandler én ventende state-oppføring med maks én handling (update-
    branch ELLER merge). Blokkerer aldri på CI. Skriver state til disk etter
    hver reell statusendring (ikke i dry-run)."""
    candidate = candidate_from_state_entry(entry)
    label = f"{candidate.slug}#{candidate.number}"

    try:
        fresh = fetch_pr_status(candidate)
    except RuntimeError as error:
        if not dry_run:
            entry["last_checked_at"] = now_iso()
            entry["error"] = str(error)
            save_state(state_path, state)
        print(f"  ⚠️  {label}: kunne ikke hente fersk status ({error}). Prøver igjen neste kjøring.")
        return

    if not dry_run:
        entry["title"] = fresh.get("title") or entry.get("title")
        entry["url"] = fresh.get("url") or entry.get("url")
        entry["base_ref"] = fresh.get("baseRefName") or entry.get("base_ref")
        entry["last_checked_at"] = now_iso()

    checks = fresh.get("statusCheckRollup") or []

    if fresh.get("mergeable") == "CONFLICTING":
        if dry_run:
            print(f"  {YELLOW}DRY-RUN{RESET}: {label} har konflikt med base — ville blitt 'blocked'.")
            return
        entry["status"] = STATUS_BLOCKED
        entry["error"] = "Konflikt med base-branch."
        save_state(state_path, state)
        print(f"  {RED}✗ {label}: konflikt med base — merket 'blocked', krever manuell håndtering.{RESET}")
        return

    blocked_reason = describe_blocked_reason(fresh)
    if blocked_reason:
        if dry_run:
            print(f"  {YELLOW}DRY-RUN{RESET}: {label} — {blocked_reason} — ville blitt 'blocked'.")
            return
        entry["status"] = STATUS_BLOCKED
        entry["error"] = blocked_reason
        save_state(state_path, state)
        print(f"  {RED}✗ {label}: {blocked_reason}{RESET}")
        return

    if fresh.get("mergeStateStatus") == "BEHIND":
        if dry_run:
            print(
                f"  {YELLOW}DRY-RUN{RESET}: {label} er bak base — ville kjørt update-branch "
                "og satt 'waiting_ci'."
            )
            do_update_branch(candidate, dry_run)
            return
        update_ok, update_error = do_update_branch(candidate, False)
        if update_ok:
            entry["status"] = STATUS_WAITING_CI
            entry["error"] = None
            save_state(state_path, state)
            print(f"  {label}: branch oppdatert, venter på ny CI (sjekkes neste kjøring).")
        else:
            entry["status"] = STATUS_BLOCKED
            entry["error"] = update_error or "update-branch feilet."
            save_state(state_path, state)
            print(f"  {RED}✗ {label}: update-branch feilet — merket 'blocked'.{RESET}")
        return

    if not checks_are_completed(checks):
        if not dry_run:
            entry["status"] = STATUS_WAITING_CI
            save_state(state_path, state)
        print(f"  … {label}: CI kjører fortsatt. Fortsatt 'waiting_ci'.")
        return

    if not checks_are_green(checks):
        if dry_run:
            print(f"  {YELLOW}DRY-RUN{RESET}: {label} har rød CI — ville blitt 'blocked'.")
            return
        entry["status"] = STATUS_BLOCKED
        entry["error"] = "CI er ferdig, men ikke grønn."
        save_state(state_path, state)
        print(f"  {RED}✗ {label}: CI rød — merket 'blocked', krever manuell håndtering.{RESET}")
        return

    if fresh.get("mergeable") != "MERGEABLE":
        if not dry_run:
            entry["status"] = STATUS_WAITING_CI
            save_state(state_path, state)
        print(f"  … {label}: ikke mergeable ennå ({fresh.get('mergeable')}). Fortsatt 'waiting_ci'.")
        return

    if dry_run:
        print(f"  {YELLOW}DRY-RUN{RESET}: {label} er klar — ville merget automatisk nå.")
        do_merge(candidate, dry_run)
        return

    merge_ok, merge_error = do_merge(candidate, False)
    if merge_ok:
        entry["status"] = STATUS_MERGED
        entry["error"] = None
        save_state(state_path, state)
        print(f"  {GREEN}✓ {label}: klar — merget automatisk.{RESET}")
    else:
        entry["status"] = STATUS_BLOCKED
        entry["error"] = merge_error or "merge feilet."
        save_state(state_path, state)
        print(f"  {RED}✗ {label}: merge feilet — merket 'blocked', krever manuell håndtering.{RESET}")


def run_pending_sweep(state: dict, state_path: Path, dry_run: bool) -> None:
    """Går gjennom alle ikke-avsluttede state-rader én gang (ikke-blokkerende
    sveip, maks én handling per rad), i samme prioriterte rekkefølge som
    godkjenningsrunden: security-relevante non-major først, deretter øvrige
    non-major, deretter major-bumps sist (stabilt på nøkkel innenfor hver
    gruppe). Dette er uavhengig av de per-repo-begrensningene som allerede
    gjelder for selve update/merge-handlingene."""
    entries: dict = state.get("prs") or {}
    pending_keys = [key for key, entry in entries.items() if entry.get("status") not in TERMINAL_STATUSES]
    if not pending_keys:
        print("\nIngen ventende PR-er i state-filen å sjekke.")
        return
    pending_keys.sort(
        key=lambda key: (
            bool(entries[key].get("major_bump")),
            not entries[key].get("security_relevant"),
            key,
        )
    )
    print(
        f"\nSjekker {len(pending_keys)} ventende PR-er fra state-filen, i prioritert rekkefølge "
        "(security-relevante non-major først, major-bumps sist — én handling per PR, "
        "ikke-blokkerende):"
    )
    for key in pending_keys:
        entry = entries[key]
        print(f"\n--- {key} (status: {entry.get('status')}) ---")
        process_pending_entry(entry, dry_run, state, state_path)


def count_pending(state: dict) -> int:
    entries: dict = state.get("prs") or {}
    return sum(1 for entry in entries.values() if entry.get("status") not in TERMINAL_STATUSES)


def sync_merged_or_closed_blocked_entries(state: dict, state_path: Path, dry_run: bool) -> int:
    """Kjøres tidlig (rett etter state-filen lastes), FØR godkjenningsrunden.
    Henter fersk status for alle 'blocked'-rader og oppdaterer STILLE (uten
    spørsmål, uten per-rad-utskrift) alle rader der PR-en faktisk allerede er
    merget eller lukket hos GitHub — dette skjer typisk når selve merget
    lyktes, men scriptet feilaktig registrerte det som mislykket (f.eks. en
    midlertidig `gh`-feil), og GitHub deretter aldri regner ut mergeability
    på nytt for en lukket PR (vises evig som `mergeable=UNKNOWN` ellers).
    Rader som fortsatt er reelt blokkert/åpne røres ikke her — de håndteres
    av den interaktive `reconcile_blocked_entries` senere i kjøringen.
    Returnerer antall rader som ble oppdatert stille."""
    entries: dict = state.get("prs") or {}
    blocked_keys = [key for key, entry in entries.items() if entry.get("status") == STATUS_BLOCKED]
    updated = 0
    for key in blocked_keys:
        entry = entries[key]
        candidate = candidate_from_state_entry(entry)
        try:
            fresh = fetch_pr_status(candidate)
        except RuntimeError:
            continue
        if fresh.get("state") == "MERGED":
            entry["status"] = STATUS_MERGED
            entry["approved_at"] = entry.get("approved_at") or fresh.get("mergedAt") or now_iso()
            entry["last_checked_at"] = now_iso()
            entry["error"] = None
            updated += 1
        elif fresh.get("state") == "CLOSED":
            entry["status"] = STATUS_SKIPPED
            entry["last_checked_at"] = now_iso()
            entry["error"] = None
            updated += 1
    if updated and not dry_run:
        save_state(state_path, state)
    if updated:
        print(
            f"{GREEN}✓ {updated} 'blocked'-rad(er) var allerede merget/lukket hos GitHub — "
            f"oppdatert stille i state-filen.{RESET}"
        )
    return updated


def reconcile_blocked_entries(state: dict, state_path: Path, interactive: bool) -> None:
    """Henter fersk status for alle rader som fortsatt er 'blocked' i
    state-filen (etter at sync_merged_or_closed_blocked_entries allerede har
    fjernet dem som viste seg å være merget/lukket), og viser en
    sammenligning mellom den lagrede (potensielt utdaterte) grunnen og
    GitHubs faktiske status nå — samme kategorier som `make pr` viser
    (behind/blocked/failed/conflict). Endrer aldri state-filen på egen hånd:
    en PR som fortsatt er reelt blokkert, eller som nå har endret seg (f.eks.
    bare BEHIND igjen), forblir 'blocked' med mindre brukeren eksplisitt
    velger å fjerne raden i menyen under (kun i interaktiv modus)."""
    entries: dict = state.get("prs") or {}
    blocked_keys = sorted(key for key, entry in entries.items() if entry.get("status") == STATUS_BLOCKED)
    if not blocked_keys:
        return
    print(f"\n{BOLD}Sjekker om {len(blocked_keys)} 'blocked'-rad(er) fortsatt stemmer med live GitHub-status:{RESET}")
    for key in blocked_keys:
        entry = entries[key]
        candidate = candidate_from_state_entry(entry)
        label = f"{candidate.slug}#{candidate.number}"

        while True:
            try:
                fresh = fetch_pr_status(candidate)
            except RuntimeError as error:
                print(f"  ⚠️  {label}: kunne ikke hente fersk status ({error}).")
                break

            if fresh.get("state") == "MERGED":
                entry["status"] = STATUS_MERGED
                entry["approved_at"] = entry.get("approved_at") or fresh.get("mergedAt") or now_iso()
                entry["last_checked_at"] = now_iso()
                entry["error"] = None
                save_state(state_path, state)
                print(
                    f"  {label}: {GREEN}✓ var faktisk merget hos GitHub "
                    f"({fresh.get('mergedAt', '?')}) — oppdatert stille i state-filen.{RESET}"
                )
                break

            if fresh.get("state") == "CLOSED":
                entry["status"] = STATUS_SKIPPED
                entry["last_checked_at"] = now_iso()
                entry["error"] = None
                save_state(state_path, state)
                print(
                    f"  {label}: {YELLOW}var lukket uten merge hos GitHub — oppdatert stille "
                    f"til 'skipped' i state-filen.{RESET}"
                )
                break

            checks = fresh.get("statusCheckRollup") or []
            live_blocked_reason = describe_blocked_reason(fresh)
            is_behind = fresh.get("mergeStateStatus") == "BEHIND"
            checks_failed = checks_are_completed(checks) and not checks_are_green(checks)
            is_computing = fresh.get("mergeable") == "UNKNOWN"
            ready_to_merge = False
            if fresh.get("mergeable") == "CONFLICTING":
                live_summary = "fortsatt konflikt med base-branch"
            elif live_blocked_reason:
                live_summary = "fortsatt GitHub-blokkert (BLOCKED) — samme kategori som lagret"
            elif is_behind:
                live_summary = "ikke lenger 'blocked' hos GitHub — er nå bare BEHIND (trenger update-branch)"
            elif not checks_are_completed(checks):
                live_summary = "ikke lenger 'blocked' hos GitHub — CI kjører fortsatt"
            elif checks_failed:
                live_summary = "ikke lenger 'blocked' hos GitHub, men CI er rød"
            elif is_computing:
                live_summary = (
                    f"{YELLOW}GitHub regner fortsatt ut mergeability (mergeable=UNKNOWN). Er "
                    "dette rett etter en push/update-branch, løser det seg normalt i løpet av "
                    "noen sekunder ([f] hent på nytt). Har det stått slik en stund uten ny "
                    "aktivitet, kan GitHub la den stå UNKNOWN til noe faktisk trigger en ny "
                    "beregning — da hjelper det ofte mer å åpne PR-en i nettleseren ([w]) enn å "
                    f"bare hente på nytt.{RESET}"
                )
            elif fresh.get("mergeable") == "MERGEABLE" and checks_are_green(checks):
                live_summary = f"{GREEN}ikke lenger 'blocked' hos GitHub — ser nå klar til merge{RESET}"
                ready_to_merge = True
            else:
                live_summary = f"ukjent (mergeable={fresh.get('mergeable')}, mergeStateStatus={fresh.get('mergeStateStatus')})"
                ready_to_merge = False
            print(f"  {label}: lagret grunn: {entry.get('error') or '-'}")
            print(f"    live nå:     {live_summary}")

            if not interactive:
                break

            # Sjekk om PR-en er godkjent
            is_approved = fresh.get("reviewDecision") == "APPROVED"
            if not is_approved:
                reviews = fresh.get("reviews") or []
                is_approved = any(
                    r.get("state") == "APPROVED" and not is_bot({"author": r.get("author", {})})
                    for r in reviews
                )

            menu_options: list[tuple[str, str, str]] = []
            if ready_to_merge and is_approved:
                menu_options.append(("merge", "Merge nå", "m"))
            elif ready_to_merge and not is_approved:
                menu_options.append(("approve", "Godkjenn", "a"))
            menu_options.extend([
                ("nettleser", "Åpne PR i nettleser", "w"),
                ("sjekk-ut", "Sjekk ut branchen lokalt", "c"),
                ("refetch", "Hent status på nytt", "f"),
            ])
            if is_behind:
                menu_options.append(("oppdater", "Update-branch", "u"))
            if checks_failed:
                menu_options.append(("rerun", "Kjør feilede CI-sjekker på nytt", "r"))
            menu_options.append(("fjern", "Fjern rad (ta opp på nytt neste kjøring)", "d"))
            menu_options.append(("hopp", "Hopp over", "s"))
            menu_options.append(("avslutt", "Avslutt sheriff", "q"))

            # Standard: merge hvis klar og godkjent, ellers hopp over
            if ready_to_merge and is_approved:
                default_index = next(i for i, (key, _, _) in enumerate(menu_options) if key == "merge")
            else:
                default_index = next(i for i, (key, _, _) in enumerate(menu_options) if key == "hopp")

            refetch = False
            while True:
                try:
                    action = choose(
                        f"Velg handling for {label}",
                        menu_options,
                        default=default_index,
                    )
                except (EOFError, KeyboardInterrupt):
                    print("\nAvsluttet av bruker.")
                    sys.exit(0)
                if action == "avslutt":
                    print("\nAvsluttet av bruker.")
                    sys.exit(0)
                if action == "hopp":
                    break
                if action == "merge" and ready_to_merge and is_approved:
                    merge_ok, merge_error = do_merge(candidate, False)
                    if merge_ok:
                        entry["status"] = STATUS_MERGED
                        entry["approved_at"] = entry.get("approved_at") or now_iso()
                        entry["last_checked_at"] = now_iso()
                        entry["error"] = None
                        save_state(state_path, state)
                        print(f"    {GREEN}✓ Merget!{RESET}")
                    else:
                        entry["status"] = STATUS_BLOCKED
                        entry["last_checked_at"] = now_iso()
                        entry["error"] = merge_error or "merge feilet."
                        save_state(state_path, state)
                        print(f"    {RED}✗ Merge feilet — fortsatt 'blocked'.{RESET}")
                    break
                if action == "approve" and ready_to_merge and not is_approved:
                    approve_ok, approve_error = do_approve(candidate, False)
                    if approve_ok:
                        print(f"    {GREEN}✓ Godkjent — prøver merge...{RESET}")
                        merge_ok, merge_error = do_merge(candidate, False)
                        if merge_ok:
                            entry["status"] = STATUS_MERGED
                            entry["approved_at"] = now_iso()
                            entry["last_checked_at"] = now_iso()
                            entry["error"] = None
                            save_state(state_path, state)
                            print(f"    {GREEN}✓ Merget!{RESET}")
                        else:
                            entry["status"] = STATUS_BLOCKED
                            entry["last_checked_at"] = now_iso()
                            entry["error"] = merge_error or "merge feilet etter godkjenning."
                            save_state(state_path, state)
                            print(f"    {RED}✗ Merge feilet — fortsatt 'blocked'.{RESET}")
                    else:
                        print(f"    {RED}✗ Godkjenning feilet: {approve_error}{RESET}")
                    break
                if action == "nettleser":
                    webbrowser.open(candidate.pr.get("url") or entry.get("url") or "")
                    continue
                if action == "sjekk-ut":
                    checkout_pr_locally(candidate)
                    continue
                if action == "refetch":
                    refetch = True
                    break
                if action == "oppdater" and is_behind:
                    update_ok, _ = do_update_branch(candidate, False)
                    if update_ok:
                        print(f"    {GREEN}✓ Update-branch sendt for {label} — henter fersk status.{RESET}")
                        entry["last_checked_at"] = now_iso()
                        save_state(state_path, state)
                        refetch = True
                        break
                    continue
                if action == "rerun" and checks_failed:
                    rerun_ok, _ = do_rerun_failed_checks(candidate)
                    if rerun_ok:
                        print(f"    {GREEN}✓ Rerun startet for {label} — henter fersk status.{RESET}")
                        entry["last_checked_at"] = now_iso()
                        save_state(state_path, state)
                        refetch = True
                        break
                    continue
                if action == "fjern":
                    del entries[key]
                    save_state(state_path, state)
                    print(f"    {GREEN}✓ Rad fjernet — {label} tas opp på nytt neste kjøring.{RESET}")
                    break
            if refetch:
                continue
            break


def generate_fresh_report(output: Path | None) -> Path:
    report_path = output or DEFAULT_REPORT
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = report_path.with_name(f"{report_path.name}.tmp.{os.getpid()}")
    command = [sys.executable, str(REPORT_SCRIPT), "--output", str(temp_path)]
    print(f"Kjører fersk sheriff-rapport: {show_command(command)}")
    result = subprocess.run(command)
    try:
        if not temp_path.exists():
            raise RuntimeError(
                "Kunne ikke generere fersk sheriff-rapport (ingen rapportfil ble skrevet)."
            )
        load_report(temp_path)
        temp_path.replace(report_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    if result.returncode != 0:
        print(
            "\u26a0\ufe0f  nais-vulnerability-report.py returnerte feilkode "
            f"{result.returncode} (blokkerte/feilede oppslag) \u2014 "
            "fortsetter med rapporten som ble skrevet til "
            f"{report_path}."
        )
    return report_path


def report_summary(path: Path) -> tuple[int, int]:
    try:
        report = load_report(path)
        candidates = len(build_candidates(report))
    except RuntimeError:
        candidates = 0
    age_seconds = max(0, int(datetime.now().timestamp() - path.stat().st_mtime))
    return age_seconds, candidates


def choose_report_source(args: argparse.Namespace) -> Path:
    if args.report:
        print(f"Bruker lagret rapport: {args.report} (ingen ny rapport genereres).")
        return args.report
    if args.output:
        return generate_fresh_report(args.output)
    if DEFAULT_REPORT.exists():
        try:
            load_report(DEFAULT_REPORT)
        except RuntimeError as error:
            print(f"⚠️  {error}")
            return generate_fresh_report(None)
    report_choice = choose_cached_report(
        DEFAULT_REPORT,
        "Sheriff-rapport",
        lambda: f"{report_summary(DEFAULT_REPORT)[1]} PR-er",
        REPORT_FRESHNESS_SECONDS,
    )
    if report_choice == "quit":
        raise KeyboardInterrupt
    if report_choice == "fortsett":
        return DEFAULT_REPORT
    return generate_fresh_report(None)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Interaktiv bot-/Dependabot-PR-flyt med persistent, gjenopptakbar tilstand. "
            "Godkjenning spørres ett ja/nei-spørsmål per ny kandidat (ubegrenset per repo) "
            "og lagres i en state-fil. Oppdater-mot-base og merge kjøres deretter som en "
            "ikke-blokkerende sveip over state-filen — maks én handling per PR per kjøring "
            "— slik at kjøringen kan avbrytes og fortsettes senere."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Skriv fersk rapport hit (videreføres til nais-vulnerability-report.py). "
            f"Standard: {DEFAULT_REPORT.relative_to(ROOT)}"
        ),
    )
    parser.add_argument(
        "--report",
        "--from-report",
        dest="report",
        type=Path,
        default=None,
        help=(
            "Bruk en lagret sheriff-rapport til kandidatlisten i stedet for å kjøre en ny "
            "rapport. Godkjenning, update-branch og merge henter likevel alltid fersk "
            "PR-status fra gh."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Vis kandidater og spørsmål, men kjør aldri gh review/merge/update-branch, og "
            "skriv aldri til state-filen."
        ),
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help=(
            f"Skriv bare ut statustabellen fra state-filen ({STATE_PATH.relative_to(ROOT)}) "
            "og avslutt. Ingen rapport kjøres, ingen gh-kall gjøres, ingen spørsmål stilles."
        ),
    )
    parser.add_argument(
        "--watch",
        dest="watch",
        action="store_true",
        default=False,
        help=(
            "Gjenta oppfølgingssveipen til ventende PR-er er ferdige. Uten flagget kjører "
            "sheriff én sveip og avslutter."
        ),
    )
    parser.add_argument(
        "--no-watch",
        dest="watch",
        action="store_false",
        help="Kompatibilitetsflagg: avslutt etter én sveip (dette er standard).",
    )
    parser.add_argument(
        "--watch-interval",
        type=int,
        default=30,
        metavar="SEKUNDER",
        help="Sekunder mellom hver sjekk i venteløkken. Standard: 30.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    state = load_state(STATE_PATH)
    state.setdefault("prs", {})

    if args.status:
        print_status_table(state)
        return 0

    enter_alt_screen()

    report_path: Path | None = None
    report: dict | None = None
    candidates: list | None = None

    while True:
        # --- Rapportvalg ---
        if report_path is None:
            # Første runde: velg rapport
            try:
                report_path = choose_report_source(args)
            except RuntimeError as error:
                print(f"❌ {error}", file=sys.stderr)
                return 1
            try:
                report = load_report(report_path)
                candidates = build_candidates(report)
            except RuntimeError as error:
                print(f"❌ {error}", file=sys.stderr)
                return 1
        else:
            # Tilbakekomst: spør om ny rapport hvis gammel
            age, _ = report_summary(report_path)
            if age > REPORT_FRESHNESS_SECONDS:
                refresh_choice = choose(
                    f"Rapporten er {format_age(age)} — hente ny?",
                    [
                        ("ny", "Lag ny rapport", "n"),
                        ("fortsett", "Bruk lagret rapport", "f"),
                        ("quit", "Avslutt", "q"),
                    ],
                    default=1,
                )
                if refresh_choice == "quit":
                    break
                if refresh_choice == "ny":
                    try:
                        report_path = generate_fresh_report(args.output)
                        report = load_report(report_path)
                        candidates = build_candidates(report)
                    except RuntimeError as error:
                        print(f"❌ {error}", file=sys.stderr)
                        continue

        # --- Sync blocked først ---
        try:
            sync_merged_or_closed_blocked_entries(state, STATE_PATH, args.dry_run)
        except (RuntimeError, KeyError, TypeError, ValueError) as error:
            print(f"⚠️  Kunne ikke synkronisere 'blocked'-rader: {error}", file=sys.stderr)

        if args.dry_run:
            print(
                f"{YELLOW}DRY-RUN: ingen gh review/merge/update-branch-kommandoer kjøres, og "
                f"state-filen skrives ikke.{RESET}"
            )

        # --- Hovedmeny ---
        if not candidates:
            print("Ingen kandidater i rapporten: ingen åpne, ikke-draft bot-/Dependabot-PR-er funnet.")
        else:
            while True:
                candidate_choice = show_candidate_table(report, candidates)
                if candidate_choice == "start":
                    break
                if candidate_choice == "summary" and show_report_summary(report_path):
                    continue
                if candidate_choice == "refresh":
                    try:
                        report_path = generate_fresh_report(args.output)
                        report = load_report(report_path)
                        candidates = build_candidates(report)
                    except RuntimeError as error:
                        print(f"❌ {error}", file=sys.stderr)
                    continue
                if candidate_choice == "quit":
                    break
            if candidate_choice == "quit":
                break

            # --- Godkjenningsrunde ---
            try:
                quit_requested = run_approval_round(candidates, state, STATE_PATH, args.dry_run)
            except (RuntimeError, KeyError, TypeError, ValueError) as error:
                print(f"❌ {error}", file=sys.stderr)
                continue  # tilbake til hovedmeny, ikke exit 1

            if quit_requested:
                break  # bruker valgte [q] inne i approval-runden — drep appen

        # --- Pending sweep ---
        try:
            run_pending_sweep(state, STATE_PATH, args.dry_run)
        except (RuntimeError, KeyError, TypeError, ValueError) as error:
            print(f"❌ {error}", file=sys.stderr)
            continue

        # --- Reconcile blocked ---
        if not args.dry_run:
            reconcile_blocked_entries(state, STATE_PATH, interactive=True)
            # NB: [q] her gjør sys.exit(0) — dreper appen (uendret)

        # --- Kort sammendrag før tilbake til hovedmeny ---
        pending_count = count_pending(state)
        merged_count = sum(1 for e in state.get("prs", {}).values() if e.get("status") == STATUS_MERGED)
        blocked_count = sum(1 for e in state.get("prs", {}).values() if e.get("status") == STATUS_BLOCKED)
        print(
            f"\n{BOLD}Sammendrag:{RESET} {GREEN}{merged_count} merget{RESET} · "
            f"{YELLOW}{pending_count} venter{RESET} · {RED}{blocked_count} blokkert{RESET}"
        )
        # loop tilbake til hovedmeny

    exit_alt_screen()
    print("Avslutter.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        # Bytt tilbake til hovedskjermen, men skriv en kort, ren melding i
        # stedet for en full traceback — Ctrl-C er en normal avbrytelse,
        # ikke en feil.
        exit_alt_screen()
        print("\nAvbrutt av bruker.")
        raise SystemExit(130)
    except BaseException:
        # Bytt tilbake til hovedskjermen FØR tracebacken skrives — ellers
        # forsvinner feilmeldingen i alternate-screen-bufferen når atexit
        # bytter skjerm etter at exceptionen allerede er skrevet ut.
        exit_alt_screen()
        raise
