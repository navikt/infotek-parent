#!/usr/bin/env python3
"""
Interaktiv PR-oppretter for alle repos.

Bruk:
  python3 scripts/pr-all.py              # vis alle repos på feature-branch
  python3 scripts/pr-all.py BRANCH=navn  # filtrer på branch-navn
"""

import subprocess
import sys
from pathlib import Path

REPOS_FILE = Path(__file__).parent.parent / "repos.yaml"
REPOS_DIR = Path(__file__).parent.parent / "repos"

BOLD = "\033[1m"
GREEN = "\033[32m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
RESET = "\033[0m"


def run(cmd, cwd=None, check=False):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=check)


def parse_repos():
    repos = []
    current = {}
    for line in REPOS_FILE.read_text().splitlines():
        line = line.strip()
        if line.startswith("- name:"):
            if current:
                repos.append(current)
            current = {"name": line.split(":", 1)[1].strip()}
        elif ":" in line and current:
            key, _, val = line.partition(":")
            current[key.strip()] = val.strip().strip('"').strip("'")
    if current:
        repos.append(current)
    return [r for r in repos if r.get("managed", "false").lower() == "true"]


def get_repo_slug(repo_dir):
    r = run(["git", "remote", "get-url", "origin"], cwd=repo_dir)
    url = r.stdout.strip()
    for sep in ["github.com:", "github.com/"]:
        if sep in url:
            slug = url.split(sep, 1)[1].rstrip("/").removesuffix(".git")
            return slug
    return None


def get_current_branch(repo_dir):
    r = run(["git", "branch", "--show-current"], cwd=repo_dir)
    return r.stdout.strip()


def get_first_commit_title(repo_dir, default_branch, branch):
    # Prøv lokal ref, fall tilbake på origin
    for base in [default_branch, f"origin/{default_branch}"]:
        r = run(["git", "log", "--oneline", f"{base}..{branch}"], cwd=repo_dir)
        lines = [l for l in r.stdout.strip().splitlines() if l]
        if lines:
            return lines[-1].split(" ", 1)[1] if " " in lines[-1] else lines[-1]
    return None


def get_existing_pr(slug, branch):
    r = run(["gh", "pr", "list", "--repo", slug, "--head", branch, "--json", "url", "--jq", ".[0].url"])
    if r.returncode != 0:
        return "?"
    url = r.stdout.strip()
    return url if url and url != "null" else None



def prompt(label, default=None):
    if default:
        val = input(f"  {label} [{default}]: ").strip()
        return val if val else default
    else:
        return input(f"  {label}: ").strip()


def main():
    branch_filter = None
    for arg in sys.argv[1:]:
        if arg.startswith("BRANCH="):
            branch_filter = arg.split("=", 1)[1]

    repos = parse_repos()

    # Finn alle repos på feature-branch
    candidates = []
    for repo in repos:
        name = repo["name"]
        default_branch = repo.get("default_branch", "main")
        repo_dir = REPOS_DIR / name
        if not repo_dir.is_dir():
            continue
        branch = get_current_branch(repo_dir)
        if not branch or branch == default_branch:
            continue
        if branch_filter and branch != branch_filter:
            continue
        candidates.append({
            "name": name,
            "dir": repo_dir,
            "branch": branch,
            "default_branch": default_branch,
            "slug": get_repo_slug(repo_dir),
        })

    if not candidates:
        print("Ingen repos på feature-branch" + (f" '{branch_filter}'" if branch_filter else ""))
        return

    # Grupper etter branch-navn
    by_branch = {}
    for c in candidates:
        by_branch.setdefault(c["branch"], []).append(c)

    # Vis og la bruker velge
    print(f"\n{BOLD}Repos klare for PR:{RESET}\n")
    flat = []
    group_map = {}  # letter -> list of indices
    for i, (branch_name, items) in enumerate(sorted(by_branch.items())):
        letter = chr(ord("a") + i)
        group_indices = []
        print(f"  [{letter}] {CYAN}{branch_name}{RESET} ({len(items)} repo{'s' if len(items) > 1 else ''})")
        for item in items:
            existing = get_existing_pr(item["slug"], item["branch"])
            idx = len(flat) + 1
            if existing == "?":
                print(f"    [{idx}] {item['name']}  {YELLOW}(kunne ikke sjekke PR){RESET}")
            elif existing:
                print(f"    [{idx}] {item['name']}  {YELLOW}✓ PR finnes: {existing}{RESET}")
            else:
                print(f"    [{idx}] {item['name']}")
            flat.append({**item, "existing_pr": existing if existing != "?" else None})
            group_indices.append(idx)
        group_map[letter] = group_indices
        print()

    print(f"  Velg: tall (1,3), bokstav for hel gruppe (a,b), enter for alle, q for å avbryte")
    try:
        raw = input("  > ").strip()
    except KeyboardInterrupt:
        print("\n  Avbrutt.")
        return

    if raw.lower() == "q":
        print("  Avbrutt.")
        return

    if raw:
        selected_indices = set()
        for token in raw.split(","):
            token = token.strip()
            if token in group_map:
                selected_indices.update(group_map[token])
            else:
                try:
                    selected_indices.add(int(token))
                except ValueError:
                    print(f"  Ukjent valg: '{token}'")
                    return
        selected = [flat[i - 1] for i in sorted(selected_indices)]
    else:
        selected = flat

    if not selected:
        print("Ingen valgt")
        return

    # Hent standardtittel fra første commit i første repo uten eksisterende PR
    first = next((s for s in selected if not s["existing_pr"]), selected[0])
    default_title = get_first_commit_title(first["dir"], first["default_branch"], first["branch"])

    print()
    try:
        title = prompt("Tittel", default_title)
        body = prompt("Body (valgfri, enter for tom)", None)
    except KeyboardInterrupt:
        print("\n  Avbrutt.")
        return
    print()

    # Finn repos som trenger push
    needs_push = []
    for item in selected:
        if item["existing_pr"]:
            continue
        remote_check = run(["git", "ls-remote", "--heads", "origin", item["branch"]], cwd=item["dir"])
        if not remote_check.stdout.strip():
            needs_push.append(item)

    if needs_push:
        print(f"\n  Disse branches er ikke pushet ennå:")
        for item in needs_push:
            print(f"    {item['name']}  ({item['branch']})")
        try:
            ans = input("\n  Push og lag PRer? [j/N] ").strip().lower()
        except KeyboardInterrupt:
            print("\n  Avbrutt.")
            return
        if ans not in ("j", "ja"):
            print("  Avbrutt.")
            return

    for item in selected:
        if item["existing_pr"]:
            print(f"  {CYAN}→{RESET} {item['name']} — PR finnes allerede: {item['existing_pr']}")
            continue

        if item in needs_push:
            push = run(["git", "push", "-u", "origin", item["branch"]], cwd=item["dir"])
            if push.returncode != 0:
                print(f"  ❌ {item['name']} — push feilet: {push.stderr.strip()}")
                continue
            print(f"  ⏫ {item['name']} — pushet")

        r = run(
            ["gh", "pr", "create",
             "--repo", item["slug"],
             "--title", title,
             "--body", body or "",
             "--base", item["default_branch"],
             "--head", item["branch"]],
            check=False,
        )
        if r.returncode == 0:
            print(f"  {GREEN}+{RESET} {item['name']} — {r.stdout.strip()}")
        else:
            print(f"  ❌ {item['name']} — {r.stderr.strip()}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n  Avbrutt.")
        sys.exit(0)
