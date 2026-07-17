#!/usr/bin/env python3
"""
Kjører Biome-sjekk og typesjekk i alle frontend-repos på tvers av repos/.

Bruk:
  python3 scripts/pnpm-biome-check.py           # sjekk, rapport + spør om fix
  python3 scripts/pnpm-biome-check.py --fix     # kjør biome:write direkte uten å spørre
  python3 scripts/pnpm-biome-check.py --verbose # vis full biome-output ved feil
  python3 scripts/pnpm-biome-check.py --dry-run

Forutsetning: pnpm install er kjørt (make pnpm-install).
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

FIX_ALL = "--fix" in sys.argv
DRY_RUN = "--dry-run" in sys.argv
VERBOSE = "--verbose" in sys.argv
REPOS_DIR = Path(__file__).parent.parent / "repos"

TYPECHECK_SCRIPTS = ["typecheck", "check-types", "tsc"]  # check-types-watch utelatt (blokkerer)

# Matcher Biomes output-format: "path/file.ts:linje:kol lint/kategori/regel ━━━"
_ERROR_RE = re.compile(r"^(\S+:\d+:\d+)\s+(lint/\S+|format)", re.MULTILINE)
# Fjerner ANSI escape-sekvenser (Biome skriver disse selv til pipe)
_ANSI_RE = re.compile(r"\x1b(?:\[[0-9;]*m|\]8;;[^\x1b]*\x1b\\)")


def capture(cmd, cwd=None) -> tuple[int, str]:
    """Kjør kommando stille og returnerer (exit_code, output)."""
    env = os.environ.copy()
    env["NODE_NO_WARNINGS"] = "1"
    env["NO_COLOR"] = "1"  # deaktiver ANSI-fargekoder (støttes av Biome og de fleste CLI-er)
    result = subprocess.run(
        cmd, cwd=cwd, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True,
    )
    return result.returncode, _ANSI_RE.sub("", result.stdout)


def run_streaming(cmd, cwd=None) -> int:
    """Kjør kommando og stream output (brukes bare ved --fix og --verbose)."""
    env = os.environ.copy()
    env["NODE_NO_WARNINGS"] = "1"
    proc = subprocess.Popen(
        cmd, cwd=cwd, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    for line in proc.stdout:
        print(f"    {line}", end="", flush=True)
    proc.wait()
    return proc.returncode


def read_scripts(pkg_dir: Path) -> dict:
    pkg_json = pkg_dir / "package.json"
    if not pkg_json.exists():
        return {}
    try:
        return json.loads(pkg_json.read_text()).get("scripts", {})
    except Exception:
        return {}


def summarize_biome_errors(output: str, max_lines: int = 6) -> list[str]:
    """Trekk ut unike feil-linjer på kompakt format: fil:linje  regel."""
    seen = set()
    lines = []
    for m in _ERROR_RE.finditer(output):
        file_loc, rule = m.group(1), m.group(2)
        key = f"{file_loc}  {rule}"
        if key not in seen:
            seen.add(key)
            lines.append(f"    {file_loc}  {rule}")
    total = len(lines)
    if total > max_lines:
        lines = lines[:max_lines]
        lines.append(f"    … og {total - max_lines} til")
    return lines


def ask_fix(label: str) -> bool:
    try:
        ans = input("  → Kjøre biome:write for å fikse? [j/N] ").strip().lower()
        return ans in ("j", "ja", "y", "yes")
    except (EOFError, KeyboardInterrupt):
        print()  # linjeskift etter prompt ved non-interaktiv kjøring
        return False


def check_repo(repo_dir: Path) -> tuple[int, int]:
    """Returnerer (biome_feil, tsc_feil)."""
    frontend = repo_dir / "frontend"
    if not frontend.is_dir():
        return 0, 0

    scripts = read_scripts(frontend)
    name = repo_dir.name
    biome_feil = tsc_feil = 0
    biome_errors_out: list[str] = []
    tsc_errors_out: list[str] = []

    # --- Biome ---
    biome_ok = None
    if "biome" in scripts:
        if DRY_RUN:
            print(f"  [dry-run] {name}: pnpm run biome + tsc", flush=True)
            return 0, 0
        rc, output = capture(["pnpm", "run", "biome"], cwd=frontend)
        biome_ok = rc == 0
        if not biome_ok:
            biome_feil = 1
            biome_errors_out = summarize_biome_errors(output)
            fixable = "FIXABLE" in output
            if fixable:
                biome_errors_out.append(f"    → FIXABLE — kjør: make pnpm-biome-check --fix")
            if VERBOSE:
                biome_errors_out.append(output)

    # --- Typesjekk ---
    tsc_script = next((s for s in TYPECHECK_SCRIPTS if s in scripts), None)
    tsc_ok = None
    if tsc_script:
        rc, output = capture(["pnpm", "run", tsc_script], cwd=frontend)
        tsc_ok = rc == 0
        if not tsc_ok:
            tsc_feil = 1
            tsc_errors_out = [f"    {l}" for l in output.splitlines() if "error TS" in l][:10]
            if VERBOSE:
                tsc_errors_out.append(output)

    # --- Skriv to linjer per repo ---
    if biome_ok is not None:
        icon = "✅" if biome_ok else "❌"
        print(f"  {icon}  {name}  biome", flush=True)
        for line in biome_errors_out:
            print(line, flush=True)
    if tsc_ok is not None:
        icon = "✅" if tsc_ok else "❌"
        print(f"  {icon}  {name}  tsc", flush=True)
        for line in tsc_errors_out:
            print(line, flush=True)

    # --- Tilby fix ---
    if biome_feil and "biome:write" in scripts and "FIXABLE" in (biome_errors_out[-1] if biome_errors_out else ""):
        if FIX_ALL or ask_fix(name):
            rc2, out2 = capture(["pnpm", "run", "biome:write"], cwd=frontend)
            summary = next(
                (l.strip() for l in reversed(out2.splitlines()) if "Checked" in l or "error" in l.lower()),
                None,
            )
            status = "✅ fikset" if rc2 == 0 else "⚠️  gjenstår feil"
            print(f"    {status}" + (f"  ({summary})" if summary else ""), flush=True)
            if rc2 != 0 and VERBOSE:
                print(out2, flush=True)

    return biome_feil, tsc_feil


def main():
    repos = sorted(d for d in REPOS_DIR.iterdir() if d.is_dir() and (d / ".git").is_dir())
    if not repos:
        print("Ingen repos funnet. Kjør 'make git-clone' først.")
        sys.exit(1)

    prefix = "[DRY-RUN] " if DRY_RUN else ""
    hint = "  (--verbose for full output)" if not VERBOSE else ""
    print(f"\n{prefix}Biome + tsc på tvers av repos{hint}\n")

    biome_feil_repos, tsc_feil_repos = [], []

    for repo_dir in repos:
        b, t = check_repo(repo_dir)
        if b:
            biome_feil_repos.append(repo_dir.name)
        if t:
            tsc_feil_repos.append(repo_dir.name)

    print()
    if not biome_feil_repos and not tsc_feil_repos:
        print("✅  Alt OK")
    else:
        if biome_feil_repos:
            print(f"❌  Biome:  {', '.join(biome_feil_repos)}")
        if tsc_feil_repos:
            print(f"❌  tsc:    {', '.join(tsc_feil_repos)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
