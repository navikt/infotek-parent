#!/usr/bin/env python3
"""
Oppdaterer frontend-avhengigheter i alle repos basert på platform/pnpm/package.json.
Lager én PR per repo som har avvik fra katalogen.

Bruk: python3 scripts/update-frontend-deps.py [--dry-run]
"""

import json
import os
import subprocess
import sys
from pathlib import Path

CATALOG_PATH = Path(__file__).parent.parent / "platform" / "pnpm" / "package.json"
REPOS_DIR = Path(__file__).parent.parent / "repos"

DRY_RUN = "--dry-run" in sys.argv


def run(cmd, cwd=None, check=True):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=check)


def load_catalog():
    data = json.loads(CATALOG_PATH.read_text())
    catalog = {}
    catalog.update(data.get("dependencies", {}))
    catalog.update(data.get("devDependencies", {}))
    return catalog


def find_package_jsons(repo_path):
    results = []
    for p in repo_path.rglob("package.json"):
        parts = p.parts
        if "node_modules" in parts or ".pnpm" in parts:
            continue
        results.append(p)
    return results


def strip_range(version):
    return version.lstrip("^~>=<").split("-")[0]


def needs_update(current, catalog_version):
    """Check if current version is behind catalog (ignoring ^ ~ prefix)."""
    current_clean = strip_range(current)
    catalog_clean = strip_range(catalog_version)
    return current_clean != catalog_clean


def compute_updates(pkg_json_path, catalog):
    data = json.loads(pkg_json_path.read_text())
    updates = {}
    for section in ("dependencies", "devDependencies"):
        if section not in data:
            continue
        for dep, current_ver in data[section].items():
            if dep in catalog and needs_update(current_ver, catalog[dep]):
                updates[dep] = {
                    "section": section,
                    "from": current_ver,
                    "to": catalog[dep],
                }
    return updates, data


def apply_updates(data, updates):
    for dep, info in updates.items():
        data[info["section"]][dep] = info["to"]
    return data


def main():
    catalog = load_catalog()
    print(f"Katalog lastet: {len(catalog)} pakker")

    for repo_dir in sorted(REPOS_DIR.iterdir()):
        if not repo_dir.is_dir():
            continue

        pkg_jsons = find_package_jsons(repo_dir)
        if not pkg_jsons:
            continue

        all_updates = {}
        for pkg_path in pkg_jsons:
            updates, _ = compute_updates(pkg_path, catalog)
            if updates:
                all_updates[pkg_path] = updates

        if not all_updates:
            continue

        repo_name = repo_dir.name
        print(f"\n{'[DRY-RUN] ' if DRY_RUN else ''}📦 {repo_name}")
        for pkg_path, updates in all_updates.items():
            rel = pkg_path.relative_to(repo_dir)
            for dep, info in updates.items():
                print(f"  {rel}: {dep} {info['from']} → {info['to']}")

        if DRY_RUN:
            continue

        # Check for clean working tree
        status = run(["git", "status", "--porcelain"], cwd=repo_dir)
        if status.stdout.strip():
            print(f"  ⚠️  Skipper {repo_name} — ikke ren arbeidstre")
            continue

        branch = f"infotek/update-frontend-deps"
        run(["git", "checkout", "-b", branch], cwd=repo_dir, check=False)

        for pkg_path, updates in all_updates.items():
            _, data = compute_updates(pkg_path, catalog)
            new_data = apply_updates(data, updates)
            pkg_path.write_text(json.dumps(new_data, indent=2, ensure_ascii=False) + "\n")

            # Run pnpm install in the same directory as package.json to update lockfile
            pkg_dir = pkg_path.parent
            print(f"  ⏳ pnpm install i {pkg_dir.relative_to(repo_dir)}...")
            install = run(["pnpm", "install", "--frozen-lockfile=false"], cwd=pkg_dir, check=False)
            if install.returncode != 0:
                print(f"  ⚠️  pnpm install feilet:\n{install.stderr[:500]}")

        run(["git", "add", "-A"], cwd=repo_dir)

        dep_names = sorted({dep for upds in all_updates.values() for dep in upds})
        short_list = ", ".join(dep_names[:3])
        if len(dep_names) > 3:
            short_list += f" og {len(dep_names) - 3} til"
        commit_msg = f"chore(deps): oppdater frontend-avhengigheter fra infotek-katalog\n\nOppdaterer: {short_list}"

        run(["git", "commit", "-m", commit_msg], cwd=repo_dir)
        run(["git", "push", "origin", branch], cwd=repo_dir)

        result = run(
            [
                "gh", "pr", "create",
                "--title", f"chore(deps): oppdater frontend-avhengigheter",
                "--body", f"Automatisk oppdatering fra [infotek-katalog](https://github.com/navikt/infotek-parent/blob/main/platform/pnpm/package.json).\n\n**Oppdaterte pakker:**\n" + "\n".join(f"- `{d}`" for d in dep_names),
                "--base", "main",
                "--head", branch,
            ],
            cwd=repo_dir,
            check=False,
        )
        if result.returncode == 0:
            print(f"  ✅ PR opprettet: {result.stdout.strip()}")
        else:
            print(f"  ❌ PR feilet: {result.stderr.strip()}")


if __name__ == "__main__":
    main()
