#!/usr/bin/env python3
"""
Interaktiv selektor for massekommandoer.

Leser linjer fra en fil (typisk tmpfile fra Makefile), grupperer repos og lar
bruker velge med tall eller gruppebokstav ala pr-all.py.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RepoMeta:
    branch: str
    dirty: bool
    message: str


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)


def _repo_meta(repo_dir: Path) -> RepoMeta:
    if not (repo_dir / ".git").is_dir():
        return RepoMeta(branch="ukjent", dirty=False, message="(ikke klonet)")

    branch_res = _run(["git", "branch", "--show-current"], cwd=repo_dir)
    branch = branch_res.stdout.strip() or "detached"

    dirty = (
        _run(["git", "diff", "--quiet"], cwd=repo_dir).returncode != 0
        or _run(["git", "diff", "--cached", "--quiet"], cwd=repo_dir).returncode != 0
    )

    msg_res = _run(["git", "log", "-1", "--pretty=%s"], cwd=repo_dir)
    message = msg_res.stdout.strip() if msg_res.returncode == 0 and msg_res.stdout.strip() else "(ingen commits)"

    return RepoMeta(branch=branch, dirty=dirty, message=message)


def _group_token(index: int) -> str:
    # 0 -> a, 25 -> z, 26 -> aa
    index += 1
    token = ""
    while index > 0:
        index, rem = divmod(index - 1, 26)
        token = chr(ord("a") + rem) + token
    return token


def _read_rows(path: Path) -> list[str]:
    return [line.rstrip("\n") for line in path.read_text().splitlines() if line.strip()]


def _split_row(row: str) -> tuple[str, str]:
    parts = row.split()
    repo = parts[0]
    extra = " ".join(parts[1:])
    return repo, extra


def _pick(prompt: str, default: str, valid: set[str]) -> str:
    print(prompt, end="", flush=True, file=sys.stderr)
    try:
        raw = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        return "q"
    if raw == "q":
        return "q"
    if not raw:
        return default
    return raw if raw in valid else default


def _confirm_selected(selected: list[str], by_repo: dict[str, RepoMeta]) -> bool:
    print(f"\n  Valgt ({len(selected)}):", file=sys.stderr)
    for row in selected:
        repo, extra = _split_row(row)
        meta = by_repo[repo]
        dirty_label = "dirty" if meta.dirty else "clean"
        suffix = f"  {extra}" if extra else ""
        print(f"    - {repo}  [{meta.branch}]  {dirty_label}{suffix}", file=sys.stderr)
    print("\n  Kjør på disse? [j/N]", end=" ", flush=True, file=sys.stderr)
    try:
        ans = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return ans in {"j", "ja", "y", "yes"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Fil med kandidater")
    parser.add_argument("--repos-dir", default=str(Path(__file__).parent.parent / "repos"))
    parser.add_argument("--default-mode", choices=("d", "b", "m"), default="d")
    parser.add_argument("--default-filter", choices=("u", "c", "a"), default="u")
    args = parser.parse_args()

    rows = _read_rows(Path(args.input))
    if not rows:
        return 0

    repos_dir = Path(args.repos_dir)
    by_repo: dict[str, RepoMeta] = {}
    for row in rows:
        repo, _ = _split_row(row)
        if repo not in by_repo:
            by_repo[repo] = _repo_meta(repos_dir / repo)

    if not sys.stdin.isatty():
        print("\n".join(rows))
        return 0

    while True:
        print(
            "\n  Gruppering: [d] dirty  [b] branch  [m] commit-melding  [a] alle direkte  [q] avbryt",
            file=sys.stderr,
        )
        print("  > ", end="", flush=True, file=sys.stderr)
        try:
            mode_raw = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            return 0
        if mode_raw == "q":
            return 0
        if mode_raw in {"d", "b", "m", "a"}:
            break
        print("  Ugyldig valg.", file=sys.stderr)

    direct_all = mode_raw == "a"
    mode = "b" if direct_all else mode_raw
    flt = "a" if direct_all else ("u" if mode == "d" else args.default_filter)

    while True:
        if not direct_all:
            while True:
                print("  Filter: [u] kun dirty  [c] kun clean  [a] alle  [q] avbryt", file=sys.stderr)
                print("  > ", end="", flush=True, file=sys.stderr)
                try:
                    new_flt = input().strip().lower()
                except (EOFError, KeyboardInterrupt):
                    return 0
                if new_flt == "q":
                    return 0
                if new_flt in {"u", "c", "a"}:
                    flt = new_flt
                    break
                print("  Ugyldig valg.", file=sys.stderr)
        else:
            direct_all = False

        filtered_rows: list[str] = []
        for row in rows:
            repo, _ = _split_row(row)
            dirty = by_repo[repo].dirty
            if flt == "u" and not dirty:
                continue
            if flt == "c" and dirty:
                continue
            filtered_rows.append(row)

        if not filtered_rows:
            if flt == "u":
                print("  Ingen dirty repos. Bytter til filter [a] alle.", file=sys.stderr)
                flt = "a"
            else:
                print("  Ingen kandidater etter valgt filter.", file=sys.stderr)
            continue

        groups: OrderedDict[str, list[int]] = OrderedDict()
        for idx, row in enumerate(filtered_rows, start=1):
            repo, _ = _split_row(row)
            meta = by_repo[repo]
            if mode == "d":
                key = "dirty" if meta.dirty else "clean"
            elif mode == "b":
                key = meta.branch
            else:
                key = meta.message
            groups.setdefault(key, []).append(idx)

        group_lookup: dict[str, list[int]] = {}
        print("\n  Kandidater:\n", file=sys.stderr)
        for i, (group_key, indexes) in enumerate(groups.items()):
            token = _group_token(i)
            group_lookup[token] = indexes
            print(f"  [{token}] {group_key} ({len(indexes)})", file=sys.stderr)
            for idx in indexes:
                row = filtered_rows[idx - 1]
                repo, extra = _split_row(row)
                meta = by_repo[repo]
                dirty_label = "dirty" if meta.dirty else "clean"
                suffix = f"  {extra}" if extra else ""
                print(f"    [{idx}] {repo}  [{meta.branch}]  {dirty_label}{suffix}", file=sys.stderr)
            print(file=sys.stderr)

        print(
            "  Valg: <nummer[,nummer]> | <gruppebokstav[,gruppebokstav]> | Enter=alle | "
            "[f] bytt filter | [g] bytt gruppering | [q] avbryt",
            file=sys.stderr,
        )
        try:
            print("  Valg > ", end="", flush=True, file=sys.stderr)
            raw = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            return 0

        if raw == "q":
            return 0
        if raw == "f":
            continue
        if raw == "g":
            while True:
                print("\n  Gruppering: [d] dirty  [b] branch  [m] commit-melding  [q] avbryt", file=sys.stderr)
                print("  > ", end="", flush=True, file=sys.stderr)
                try:
                    new_mode = input().strip().lower()
                except (EOFError, KeyboardInterrupt):
                    return 0
                if new_mode == "q":
                    return 0
                if new_mode in {"d", "b", "m"}:
                    mode = new_mode
                    break
                print("  Ugyldig valg.", file=sys.stderr)
            continue

        if not raw:
            selected = filtered_rows
        else:
            selected_idx: set[int] = set()
            valid = True
            for token in raw.split(","):
                token = token.strip().lower()
                if token in group_lookup:
                    selected_idx.update(group_lookup[token])
                    continue
                if token.isdigit():
                    idx = int(token)
                    if 1 <= idx <= len(filtered_rows):
                        selected_idx.add(idx)
                        continue
                valid = False
                break
            if not valid:
                print("  Ugyldig valg.", file=sys.stderr)
                continue
            selected = [filtered_rows[i - 1] for i in sorted(selected_idx)]

        if selected and _confirm_selected(selected, by_repo):
            print("\n".join(selected))
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
