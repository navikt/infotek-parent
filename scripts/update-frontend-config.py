#!/usr/bin/env python3
"""
Bumper @navikt/infotek-frontend-config til siste versjon i alle migrerte frontend-repos.

Gjør for hvert repo med @navikt/infotek-frontend-config i devDependencies:
  1. Sjekker om versjonen allerede er oppdatert
  2. Oppdaterer package.json til ny versjon fra katalogen
  3. Kjører pnpm install --no-frozen-lockfile
  4. Committer og lager PR

Bruk:
  python3 scripts/update-frontend-config.py [--dry-run]

Forutsetning: Ny versjon av @navikt/infotek-frontend-config er publisert til GitHub Packages.
"""

import json
import os
import re
import sys
from pathlib import Path
import subprocess

DRY_RUN = "--dry-run" in sys.argv
REPOS_DIR = Path(__file__).parent.parent / "repos"
CATALOG_PATH = Path(__file__).parent.parent / "platform" / "pnpm" / "package.json"
PACKAGE_NAME = "@navikt/infotek-frontend-config"


def load_catalog_version() -> str:
    data = json.loads(CATALOG_PATH.read_text())
    version = data.get("devDependencies", {}).get(PACKAGE_NAME, "")
    if not version:
        raise SystemExit(f"❌ Fant ikke {PACKAGE_NAME} i {CATALOG_PATH}")
    return version


def run(cmd, cwd=None, check=True, capture=True):
    env = os.environ.copy()
    env["NODE_NO_WARNINGS"] = "1"
    return subprocess.run(
        cmd, cwd=cwd,
        capture_output=capture,
        text=True,
        check=check,
        env=env,
    )


def run_streaming(cmd, cwd=None):
    env = os.environ.copy()
    env["NODE_NO_WARNINGS"] = "1"
    proc = subprocess.Popen(
        cmd, cwd=cwd, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    for line in proc.stdout:
        print(f"     {line}", end="", flush=True)
    proc.wait()
    return proc.returncode


def find_frontend_repos() -> list[tuple[Path, Path]]:
    """Returner liste med (repo_dir, frontend_dir) for alle repos med frontend/package.json."""
    results = []
    if not REPOS_DIR.exists():
        raise SystemExit(f"❌ {REPOS_DIR} finnes ikke — kjør 'make git-clone' først")
    for repo_dir in sorted(REPOS_DIR.iterdir()):
        if not (repo_dir / ".git").exists():
            continue
        frontend_dir = repo_dir / "frontend"
        if (frontend_dir / "package.json").exists():
            results.append((repo_dir, frontend_dir))
    return results


def get_installed_version(frontend_dir: Path) -> str | None:
    data = json.loads((frontend_dir / "package.json").read_text())
    return data.get("devDependencies", {}).get(PACKAGE_NAME)


def get_default_branch(repo_dir: Path) -> str:
    result = run(
        ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
        cwd=repo_dir, check=False,
    )
    if result.returncode == 0:
        return result.stdout.strip().split("/")[-1]
    result = run(["git", "branch", "-r"], cwd=repo_dir, check=False)
    for line in result.stdout.splitlines():
        line = line.strip()
        if line in ("origin/main", "origin/master"):
            return line.split("/")[-1]
    return "main"


def update_package_json(frontend_dir: Path, new_version: str) -> bool:
    pkg_path = frontend_dir / "package.json"
    data = json.loads(pkg_path.read_text())
    dev_deps = data.get("devDependencies", {})
    if dev_deps.get(PACKAGE_NAME) == new_version:
        return False
    dev_deps[PACKAGE_NAME] = new_version
    data["devDependencies"] = dict(sorted(dev_deps.items()))
    pkg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return True


def process_repo(repo_dir: Path, frontend_dir: Path, new_version: str) -> None:
    repo_name = repo_dir.name
    installed = get_installed_version(frontend_dir)

    if installed is None:
        print(f"  ⏭  {repo_name} — ikke migrert, kjør 'make pnpm-migrate-frontend-config'")
        return

    if installed == new_version:
        print(f"  ✅ {repo_name} — allerede på {new_version}")
        return

    print(f"\n{'[DRY-RUN] ' if DRY_RUN else ''}🔄 {repo_name}  {installed} → {new_version}")

    if DRY_RUN:
        print(f"  → Vil oppdatere {PACKAGE_NAME}: {installed} → {new_version}")
        print(f"  → Vil kjøre pnpm install og lage PR")
        return

    status = run(["git", "status", "--porcelain"], cwd=repo_dir)
    if status.stdout.strip():
        print(f"  ⚠️  Skipper — ikke ren arbeidstre")
        return

    default_branch = get_default_branch(repo_dir)
    bare_version = new_version.lstrip("^~")
    branch = f"chore/bump-frontend-config-{bare_version}"

    run(["git", "fetch", "origin"], cwd=repo_dir)
    run(["git", "checkout", default_branch], cwd=repo_dir)
    run(["git", "reset", "--hard", f"origin/{default_branch}"], cwd=repo_dir)
    run(["git", "branch", "-D", branch], cwd=repo_dir, check=False)
    run(["git", "checkout", "-b", branch], cwd=repo_dir)

    changed = update_package_json(frontend_dir, new_version)
    if not changed:
        print(f"  ⏭  Ingen endringer etter oppdatering")
        run(["git", "checkout", default_branch], cwd=repo_dir)
        return

    print(f"  ⏳ pnpm install...")
    rc = run_streaming(["pnpm", "install", "--no-frozen-lockfile"], cwd=frontend_dir)
    if rc != 0:
        print(f"  ⚠️  pnpm install feilet (fortsetter uten lockfile-oppdatering)")

    run(["git", "add", "-A"], cwd=repo_dir)
    run(
        ["git", "commit", "-m",
         f"chore(frontend): bump @navikt/infotek-frontend-config til {new_version}\n\n"
         f"Oppdaterer pakken fra {installed} til {new_version}.\n"
         f"Se CHANGELOG i infotek-parent for endringer."],
        cwd=repo_dir,
    )

    run(["git", "push", "--force-with-lease", "-u", "origin", branch], cwd=repo_dir)

    pr_body = (
        f"## Bump `@navikt/infotek-frontend-config` → `{new_version}`\n\n"
        f"Oppdaterer pakken fra `{installed}` til `{new_version}`.\n\n"
        f"Se [CHANGELOG](https://github.com/navikt/infotek-parent/blob/main/platform/pnpm/CHANGELOG.md) "
        f"for hva som er endret i ny versjon."
    )

    result = run(
        [
            "gh", "pr", "create",
            "--title", f"chore(frontend): bump @navikt/infotek-frontend-config til {new_version}",
            "--body", pr_body,
            "--base", default_branch,
            "--head", branch,
        ],
        cwd=repo_dir,
        check=False,
    )
    if result.returncode == 0:
        print(f"  🔗 PR: {result.stdout.strip()}")
    elif "already exists" in result.stderr:
        m = re.search(r"https://\S+", result.stderr)
        url = m.group(0) if m else result.stderr.strip()
        print(f"  🔗 PR eksisterer allerede: {url}")
    else:
        print(f"  ❌ PR feilet: {result.stderr.strip()}")


def main():
    new_version = load_catalog_version()
    repos = find_frontend_repos()

    print(f"{'[DRY-RUN] ' if DRY_RUN else ''}Bumper {PACKAGE_NAME} til {new_version} i {len(repos)} frontend-repos\n")

    for repo_dir, frontend_dir in repos:
        try:
            process_repo(repo_dir, frontend_dir, new_version)
        except Exception as e:
            print(f"  ❌ {repo_dir.name} feilet: {e}")

    print("\nFerdig.")
    if DRY_RUN:
        print("Kjør uten --dry-run for å faktisk utføre endringene.")


if __name__ == "__main__":
    main()
