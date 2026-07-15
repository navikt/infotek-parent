#!/usr/bin/env python3
"""
Engangs-migrasjon: migrer alle managed frontend-repos til @navikt/infotek-frontend-config.

Gjør for hvert repo:
  1. Legger til @navikt/infotek-frontend-config som devDependency
  2. Erstatter biome.json med extends-versjon
  3. Oppdaterer tsconfig.json (eller tsconfig.app.json) til extends-versjon
  4. Fjerner eslint-avhengigheter og konfig-filer
  5. Kjører pnpm install + biome format --write (for repos med avvikende format)
  6. Oppretter PR

Bruk:
  python3 scripts/migrate-frontend-config.py [--dry-run]

Forutsetning: infotek-frontend-config 1.1.0 er publisert til GitHub Packages.
"""

import json
import sys
from pathlib import Path
import subprocess

DRY_RUN = "--dry-run" in sys.argv
REPOS_DIR = Path(__file__).parent.parent / "repos"
PACKAGE_VERSION = "^1.0.0"
BRANCH = "migrate/frontend-config"

# ── Per-repo konfigurasjon ─────────────────────────────────────────────────

REPOS = {
    "historisk-avstandskalkulator": {
        "default_branch": "main",
        "tsconfig_new": {
            "extends": "@navikt/infotek-frontend-config/tsconfig.base.json",
            "compilerOptions": {
                "useDefineForClassFields": True,
                "types": ["vite/client", "node"],
                "paths": {
                    "~/*": ["./src/*"],
                    "@generated": ["./generated"],
                    "@generated/*": ["./generated/*"],
                },
            },
            "include": ["src", "vite-env.d.ts"],
            "references": [{"path": "./tsconfig.node.json"}],
        },
        "needs_reformat": False,
    },
    "historisk-valutakalkulator": {
        "default_branch": "main",
        "tsconfig_new": {
            "extends": "@navikt/infotek-frontend-config/tsconfig.base.json",
            "compilerOptions": {
                "useDefineForClassFields": True,
                "types": ["vite/client", "node"],
                "paths": {
                    "~/*": ["./src/*"],
                    "@generated": ["./generated"],
                    "@generated/*": ["./generated/*"],
                },
            },
            "include": ["src", "vite-env.d.ts"],
            "references": [{"path": "./tsconfig.node.json"}],
        },
        "needs_reformat": False,
    },
    "historisk-gravferdkalkulator": {
        "default_branch": "main",
        "tsconfig_new": {
            "extends": "@navikt/infotek-frontend-config/tsconfig.base.json",
            "compilerOptions": {
                "target": "ES2022",
                "lib": ["ES2022", "DOM", "DOM.Iterable"],
                "types": ["vite/client"],
                "paths": {
                    "~/*": ["./src/*"],
                    "@generated": ["./generated"],
                    "@generated/*": ["./generated/*"],
                },
            },
            "include": ["src"],
        },
        "needs_reformat": True,
    },
    "historisk-riddler": {
        "default_branch": "main",
        "tsconfig_new": {
            "extends": "@navikt/infotek-frontend-config/tsconfig.base.json",
            "compilerOptions": {
                "target": "ES2022",
                "lib": ["ES2022", "DOM", "DOM.Iterable"],
                "ignoreDeprecations": "6.0",
                "types": ["vite/client"],
                "paths": {
                    "~/*": ["./src/*"],
                    "@generated": ["./generated"],
                    "@generated/*": ["./generated/*"],
                },
            },
            "include": ["src"],
        },
        "needs_reformat": True,
    },
    "infotek-statistikk": {
        "default_branch": "main",
        "tsconfig_new": {
            "extends": "@navikt/infotek-frontend-config/tsconfig.base.json",
            "compilerOptions": {
                "target": "ES2022",
                "lib": ["ES2022", "DOM", "DOM.Iterable"],
                "useDefineForClassFields": True,
                "allowImportingTsExtensions": True,
                "moduleDetection": "force",
                "noUnusedLocals": True,
                "noUnusedParameters": True,
                "noFallthroughCasesInSwitch": True,
                "paths": {"~/*": ["./src/*"]},
            },
            "include": ["src"],
        },
        "needs_reformat": True,
    },
    "historisk-pensjon": {
        "default_branch": "master",
        "tsconfig_new": {
            "extends": "@navikt/infotek-frontend-config/tsconfig.base.json",
            "compilerOptions": {
                "useDefineForClassFields": True,
                "noFallthroughCasesInSwitch": True,
                "types": ["vite/client", "vitest/globals"],
            },
            "include": ["src"],
        },
        "needs_reformat": False,
        "add_scripts": {
            "lint": "biome check .",
            "format": "biome format --write .",
        },
    },
    "historisk-regnskap": {
        "default_branch": "master",
        "tsconfig_new": {
            "extends": "@navikt/infotek-frontend-config/tsconfig.base.json",
            "compilerOptions": {
                "useDefineForClassFields": True,
                "noFallthroughCasesInSwitch": True,
                "types": ["vite/client", "vitest/globals"],
            },
            "include": ["src"],
            "references": [{"path": "./tsconfig.node.json"}],
        },
        "needs_reformat": False,
        "add_scripts": {
            "lint": "biome check .",
            "format": "biome format --write .",
        },
    },
    "historisk-tidsbegrenset-uforestonad": {
        "default_branch": "master",
        "tsconfig_new": {
            "extends": "@navikt/infotek-frontend-config/tsconfig.base.json",
            "compilerOptions": {
                "useDefineForClassFields": True,
                "allowImportingTsExtensions": True,
                "noUnusedLocals": True,
                "noUnusedParameters": True,
                "noFallthroughCasesInSwitch": True,
            },
            "include": ["src"],
            "references": [{"path": "./tsconfig.node.json"}],
        },
        "needs_reformat": False,
        "remove_deps": ["eslint"],
        "remove_inline_eslint_config": True,
        "add_scripts": {
            "lint": "biome check .",
            "format": "biome format --write .",
        },
    },
    "infotek-databaseuttrekk": {
        "default_branch": "main",
        # tsconfig.json er project-references root — oppdater tsconfig.app.json
        "tsconfig_file": "tsconfig.app.json",
        "tsconfig_new": {
            "extends": "@navikt/infotek-frontend-config/tsconfig.base.json",
            "compilerOptions": {
                "tsBuildInfoFile": "./node_modules/.tmp/tsconfig.app.tsbuildinfo",
                "target": "ES2023",
                "lib": ["ES2023", "DOM"],
                "types": ["vite/client"],
                "allowImportingTsExtensions": True,
                "verbatimModuleSyntax": True,
                "moduleDetection": "force",
                "noUnusedLocals": True,
                "noUnusedParameters": True,
                "erasableSyntaxOnly": True,
                "noFallthroughCasesInSwitch": True,
            },
            "include": ["src"],
        },
        "needs_reformat": False,
        "eslint_files": ["eslint.config.js"],
        "remove_deps": [
            "@eslint/js",
            "eslint",
            "eslint-plugin-react-hooks",
            "eslint-plugin-react-refresh",
            "globals",
            "typescript-eslint",
        ],
        "add_scripts": {
            "lint": "biome check .",
            "format": "biome format --write .",
        },
    },
}

# ── Helpers ────────────────────────────────────────────────────────────────


def run(cmd, cwd=None, check=True, capture=True):
    return subprocess.run(
        cmd, cwd=cwd,
        capture_output=capture,
        text=True,
        check=check,
    )


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def already_migrated(frontend_dir: Path) -> bool:
    pkg = frontend_dir / "package.json"
    if not pkg.exists():
        return False
    data = json.loads(pkg.read_text())
    return "@navikt/infotek-frontend-config" in data.get("devDependencies", {})


def update_package_json(frontend_dir: Path, config: dict) -> bool:
    """Add devDep, remove eslint deps, update scripts. Returns True if changed."""
    pkg_path = frontend_dir / "package.json"
    data = json.loads(pkg_path.read_text())
    changed = False

    # Add @navikt/infotek-frontend-config
    dev_deps = data.setdefault("devDependencies", {})
    if "@navikt/infotek-frontend-config" not in dev_deps:
        dev_deps["@navikt/infotek-frontend-config"] = PACKAGE_VERSION
        # Also add @biomejs/biome if not present (for repos without it)
        if "@biomejs/biome" not in dev_deps:
            dev_deps["@biomejs/biome"] = "^2.5.4"
        changed = True

    # Remove eslint devDeps
    for dep in config.get("remove_deps", []):
        if dep in dev_deps:
            del dev_deps[dep]
            changed = True

    # Remove inline eslintConfig key
    if config.get("remove_inline_eslint_config") and "eslintConfig" in data:
        del data["eslintConfig"]
        changed = True

    # Sort devDependencies alphabetically
    if changed:
        data["devDependencies"] = dict(sorted(dev_deps.items()))

    # Add/replace scripts
    for name, cmd in config.get("add_scripts", {}).items():
        if data.get("scripts", {}).get(name) != cmd:
            data.setdefault("scripts", {})[name] = cmd
            changed = True

    if changed:
        write_json(pkg_path, data)
    return changed


def write_biome_json(frontend_dir: Path) -> bool:
    biome_path = frontend_dir / "biome.json"
    new_content = {
        "extends": ["@navikt/infotek-frontend-config/biome.base.json"]
    }
    if biome_path.exists():
        existing = json.loads(biome_path.read_text())
        if existing == new_content:
            return False
    write_json(biome_path, new_content)
    return True


def write_tsconfig(frontend_dir: Path, config: dict) -> bool:
    tsconfig_file = config.get("tsconfig_file", "tsconfig.json")
    tsconfig_path = frontend_dir / tsconfig_file
    new_content = config["tsconfig_new"]
    if tsconfig_path.exists():
        existing = json.loads(tsconfig_path.read_text())
        if existing == new_content:
            return False
    write_json(tsconfig_path, new_content)
    return True


def remove_eslint_files(frontend_dir: Path, config: dict) -> list[str]:
    removed = []
    for fname in config.get("eslint_files", []):
        fpath = frontend_dir / fname
        if fpath.exists():
            fpath.unlink()
            removed.append(fname)
    return removed


# ── Main ───────────────────────────────────────────────────────────────────


def migrate_repo(repo_name: str, config: dict) -> None:
    repo_dir = REPOS_DIR / repo_name
    frontend_dir = repo_dir / "frontend"

    if not frontend_dir.exists():
        print(f"  ⏭  {repo_name} — ingen frontend-mappe, skipper")
        return

    if already_migrated(frontend_dir):
        print(f"  ✅ {repo_name} — allerede migrert")
        return

    print(f"\n{'[DRY-RUN] ' if DRY_RUN else ''}🔄 {repo_name}")

    if DRY_RUN:
        print(f"  → Vil legge til @navikt/infotek-frontend-config {PACKAGE_VERSION}")
        print(f"  → Vil erstatte biome.json med extends-versjon")
        tsconfig_file = config.get("tsconfig_file", "tsconfig.json")
        print(f"  → Vil oppdatere {tsconfig_file} til extends-versjon")
        if config.get("needs_reformat"):
            print(f"  → Vil kjøre biome format --write (4-space → 2-space)")
        if config.get("eslint_files") or config.get("remove_deps"):
            print(f"  → Vil fjerne eslint-filer og avhengigheter")
        return

    # Guard: clean working tree
    status = run(["git", "status", "--porcelain"], cwd=repo_dir)
    if status.stdout.strip():
        print(f"  ⚠️  Skipper {repo_name} — ikke ren arbeidstre")
        return

    default_branch = config["default_branch"]
    run(["git", "checkout", default_branch], cwd=repo_dir)
    run(["git", "pull", "--quiet"], cwd=repo_dir)
    run(["git", "checkout", "-b", BRANCH], cwd=repo_dir, check=False)

    # Apply changes
    pkg_changed = update_package_json(frontend_dir, config)
    biome_changed = write_biome_json(frontend_dir)
    tsconfig_changed = write_tsconfig(frontend_dir, config)
    removed_files = remove_eslint_files(frontend_dir, config)

    if not any([pkg_changed, biome_changed, tsconfig_changed, removed_files]):
        print(f"  ⏭  Ingen endringer")
        run(["git", "checkout", default_branch], cwd=repo_dir)
        return

    # pnpm install to update lockfile
    print(f"  ⏳ pnpm install...")
    install = run(
        ["pnpm", "install", "--frozen-lockfile=false"],
        cwd=frontend_dir,
        check=False,
    )
    if install.returncode != 0:
        print(f"  ⚠️  pnpm install feilet (fortsetter uten lockfile-oppdatering)")
        print(f"     {install.stderr[:300]}")

    run(["git", "add", "-A"], cwd=repo_dir)
    run(
        ["git", "commit", "-m",
         "ci(frontend): migrer til @navikt/infotek-frontend-config\n\n"
         "- Erstatter inline biome.json og tsconfig.json med extends\n"
         "- Legger til @navikt/infotek-frontend-config som devDependency\n"
         "- Fjerner eslint-konfig og avhengigheter (der aktuelt)\n\n"
         "Dependabot håndterer videre oppdateringer av pakken."],
        cwd=repo_dir,
    )
    print(f"  ✅ Commit 1: konfig-migrasjon")

    # Reformat pass for repos with style deviations
    if config.get("needs_reformat"):
        biome_bin = frontend_dir / "node_modules" / ".bin" / "biome"
        if biome_bin.exists():
            print(f"  ⏳ biome format --write (4-space → 2-space)...")
            run(
                [str(biome_bin), "format", "--write", "."],
                cwd=frontend_dir,
                check=False,
            )
            run(["git", "add", "-A"], cwd=repo_dir)
            diff = run(["git", "diff", "--cached", "--stat"], cwd=repo_dir)
            if diff.stdout.strip():
                run(
                    ["git", "commit", "-m",
                     "style(frontend): reformat med biome 2.5.4\n\n"
                     "Automatisk reformat etter migrasjon til standardisert konfig.\n"
                     "Endringer: innrykk 4 → 2 mellomrom, linjelengde 120 → 100."],
                    cwd=repo_dir,
                )
                print(f"  ✅ Commit 2: reformat")
        else:
            print(f"  ⚠️  biome ikke installert — kjør 'pnpm install && biome format --write .' manuelt")

    # Push and create PR
    run(["git", "push", "-u", "origin", BRANCH], cwd=repo_dir)

    pr_body = (
        "## Migrasjon til `@navikt/infotek-frontend-config`\n\n"
        "Legger til pakken som `devDependency` slik at Dependabot håndterer "
        "fremtidige oppdateringer av biome- og tsconfig-konfig automatisk.\n\n"
        "**Endringer:**\n"
        "- `biome.json` → `extends: @navikt/infotek-frontend-config/biome.base.json`\n"
        "- `tsconfig.json` → `extends: @navikt/infotek-frontend-config/tsconfig.base.json`\n"
    )
    if removed_files or config.get("remove_deps"):
        pr_body += "- Fjerner eslint-konfig og avhengigheter\n"
    if config.get("needs_reformat"):
        pr_body += "- Reformaterer kildekoden til ny standard (2-space, linje 100)\n"

    result = run(
        [
            "gh", "pr", "create",
            "--title", "ci(frontend): migrer til @navikt/infotek-frontend-config",
            "--body", pr_body,
            "--base", default_branch,
            "--head", BRANCH,
        ],
        cwd=repo_dir,
        check=False,
    )
    if result.returncode == 0:
        print(f"  🔗 PR: {result.stdout.strip()}")
    else:
        print(f"  ❌ PR feilet: {result.stderr.strip()}")


def main():
    print(f"{'[DRY-RUN] ' if DRY_RUN else ''}Migrerer {len(REPOS)} repos til @navikt/infotek-frontend-config {PACKAGE_VERSION}\n")

    for repo_name, config in REPOS.items():
        try:
            migrate_repo(repo_name, config)
        except Exception as e:
            print(f"  ❌ {repo_name} feilet: {e}")

    print("\nFerdig.")
    if DRY_RUN:
        print("Kjør uten --dry-run for å faktisk utføre endringene.")


if __name__ == "__main__":
    main()
