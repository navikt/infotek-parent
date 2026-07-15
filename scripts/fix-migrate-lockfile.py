#!/usr/bin/env python3
"""
Engangsskript: Fikser pnpm-lock.yaml på migrate/frontend-config-branches.
Oppdaterer @biomejs/biome til 2.5.2 (eksakt pin) og kjører pnpm install.

Bruk: python3 scripts/fix-migrate-lockfile.py [--dry-run]
"""

import json
import os
import subprocess
import sys
from pathlib import Path

REPOS_DIR = Path(__file__).parent.parent / "repos"
CATALOG_PATH = Path(__file__).parent.parent / "platform" / "pnpm" / "package.json"
NPMRC_TEMPLATE = Path(__file__).parent.parent / "platform" / "npm" / ".npmrc"
BRANCH = "migrate/frontend-config"
DRY_RUN = "--dry-run" in sys.argv

GREEN = "\033[32m"
RED   = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"


def run(cmd, cwd=None, check=True):
    env = os.environ.copy()
    env["NODE_NO_WARNINGS"] = "1"
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=check, env=env)


def run_streaming(cmd, cwd=None):
    env = os.environ.copy()
    env["NODE_NO_WARNINGS"] = "1"
    proc = subprocess.Popen(cmd, cwd=cwd, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1)
    for line in proc.stdout:
        print(f"     {line}", end="", flush=True)
    proc.wait()
    return proc.returncode


def find_frontend_dirs(repo_dir: Path) -> list[Path]:
    results = []
    for p in repo_dir.rglob("package.json"):
        if "node_modules" in p.parts or ".pnpm" in p.parts:
            continue
        results.append(p.parent)
    return results


def main():
    catalog_data = json.loads(CATALOG_PATH.read_text())
    catalog_all = {}
    catalog_all.update(catalog_data.get("dependencies", {}))
    catalog_all.update(catalog_data.get("devDependencies", {}))
    biome_ver = catalog_all.get("@biomejs/biome", "2.5.2")
    print(f"{'[DRY-RUN] ' if DRY_RUN else ''}Fikser lockfiler på {BRANCH}  (biome → {biome_ver})\n")

    for repo_dir in sorted(REPOS_DIR.iterdir()):
        if not repo_dir.is_dir():
            continue

        # Sjekk om migrate-branch finnes lokalt
        local_branch = run(
            ["git", "branch", "--list", BRANCH],
            cwd=repo_dir, check=False,
        )
        if not local_branch.stdout.strip():
            continue

        # Les package.json fra lokal branch
        repo_dir_path = repo_dir
        pkg_candidates = [
            repo_dir / "frontend" / "package.json",
        ]
        # Finn alle package.json som har @biomejs/biome
        pkg_to_fix = []
        for p in repo_dir.rglob("package.json"):
            if "node_modules" in p.parts or ".pnpm" in p.parts:
                continue
            try:
                data = json.loads(p.read_text())
            except Exception:
                continue
            if "@biomejs/biome" in data.get("devDependencies", {}):
                current = data["devDependencies"]["@biomejs/biome"]
                if current != biome_ver:
                    pkg_to_fix.append((p, current))

        if not pkg_to_fix:
            print(f"  ✅ {repo_dir.name} — biome allerede {biome_ver} (eller ikke installert)")
            continue

        current_biome = pkg_to_fix[0][1]
        print(f"  {'[DRY-RUN] ' if DRY_RUN else ''}🔧 {repo_dir.name}  ({current_biome} → {biome_ver})")

        if DRY_RUN:
            continue

        # Checkout lokal branch
        run(["git", "checkout", BRANCH], cwd=repo_dir, check=False)

        # Oppdater biome-versjon i de identifiserte filene
        updated = False
        for pkg_path, _ in pkg_to_fix:
            data = json.loads(pkg_path.read_text())
            changed = False
            for section in ("dependencies", "devDependencies"):
                for dep in list(data.get(section, {})):
                    if dep in catalog_all and data[section][dep] != catalog_all[dep]:
                        data[section][dep] = catalog_all[dep]
                        changed = True
            pkg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

            # Sørg for at .npmrc har teamstandard-linjer (merge, ikke erstatt)
            # @navikt:registry MÅ peke på GitHub Packages for at infotek-pakker skal fungere
            npmrc_path = pkg_path.parent / ".npmrc"
            template_text = NPMRC_TEMPLATE.read_text()
            import re as _re
            template_keys = {}
            for line in template_text.splitlines():
                m = _re.match(r"^([^#\s][^=]*)=(.*)", line)
                if m:
                    template_keys[m.group(1).strip()] = line
            if npmrc_path.exists():
                existing_lines = npmrc_path.read_text().splitlines()
                result_lines = []
                existing_keys = {}
                for line in existing_lines:
                    m = _re.match(r"^([^#\s][^=]*)=(.*)", line)
                    if m:
                        existing_keys[m.group(1).strip()] = len(result_lines)
                    result_lines.append(line)
                # Overstyr @navikt:registry hvis den peker feil
                navikt_key = "@navikt:registry"
                if navikt_key in existing_keys:
                    idx = existing_keys[navikt_key]
                    if "npm.pkg.github.com" not in result_lines[idx]:
                        result_lines[idx] = template_keys[navikt_key]
                        print(f"  🔧 .npmrc: rettet @navikt:registry til GitHub Packages")
                        # Slett lockfilen — URL-er i den er basert på feil registry
                        lockfile = pkg_path.parent / "pnpm-lock.yaml"
                        if lockfile.exists():
                            lockfile.unlink()
                            print(f"  🔧 pnpm-lock.yaml slettet — regenereres med riktig registry")
                # Legg til manglende nøkler
                missing = [v for k, v in template_keys.items() if k not in existing_keys]
                if missing:
                    result_lines += missing
                    print(f"  🔧 .npmrc: la til {len(missing)} linje(r)")
                npmrc_path.write_text("\n".join(result_lines) + "\n")
            else:
                npmrc_path.write_text(template_text)
                print(f"  🔧 .npmrc opprettet fra teamstandard")

            # Kjør pnpm install for å oppdatere lockfilen
            frontend_dir = pkg_path.parent
            print(f"  ⏳ pnpm install i {frontend_dir.relative_to(repo_dir)}...")
            rc = run_streaming(["pnpm", "install", "--no-frozen-lockfile"], cwd=frontend_dir)
            if rc != 0:
                print(f"  {RED}❌ pnpm install feilet — hopper over{RESET}")
                run(["git", "checkout", "--", "."], cwd=repo_dir)
                break
            updated = True

        if not updated:
            continue

        run(["git", "add", "-A"], cwd=repo_dir)
        diff = run(["git", "diff", "--cached", "--stat"], cwd=repo_dir)
        if not diff.stdout.strip():
            print(f"  {YELLOW}⚠️  Ingen endringer å commite{RESET}")
            continue

        run(["git", "commit", "-m",
             f"fix(deps): pin biome til {biome_ver}, legg til npmrc-unntak og oppdater lockfile"],
            cwd=repo_dir)
        push = run(["git", "push", "--force-with-lease", "origin", BRANCH],
                   cwd=repo_dir, check=False)
        if push.returncode == 0:
            print(f"  {GREEN}✅ Pushet oppdatert lockfile{RESET}")
        else:
            print(f"  {RED}❌ Push feilet: {push.stderr.strip()}{RESET}")


if __name__ == "__main__":
    main()
