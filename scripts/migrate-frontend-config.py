#!/usr/bin/env python3
"""
Migrer managed frontend-repos til eksplisitt lokal TypeScript- og Biome-konfig.

Skriptet gjør lokale filendringer og stopper etter validering av pnpm install.
Det oppretter ikke commit, push eller PR. Utvikleren publiserer selv.

Bruk:
  python3 scripts/migrate-frontend-config.py [--dry-run] [--repo-filter <navn>]
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys

REPOS_DIR = Path(__file__).parent.parent / "repos"
REPOS_YAML = Path(__file__).parent.parent / "repos.yaml"
TSCONFIG_BASE_PATH = Path(__file__).parent.parent / "platform" / "pnpm" / "tsconfig.base.json"
BIOME_BASE_PATH = Path(__file__).parent.parent / "platform" / "pnpm" / "biome.base.json"
PACKAGE_NAME = "@navikt/infotek-frontend-config"
NPM_REGISTRY = "https://registry.npmjs.org/"
GITHUB_PACKAGES_REGISTRY = "https://npm.pkg.github.com/"
INTERNAL_SCOPES = {
    "@navikt": GITHUB_PACKAGES_REGISTRY,
    "@nais": GITHUB_PACKAGES_REGISTRY,
}
DEFAULT_INSTALL_TIMEOUT_SECONDS = 900


REPO_CONFIGS: dict[str, dict] = {
    "historisk-avstandskalkulator": {
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
    },
    "historisk-valutakalkulator": {
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
    },
    "historisk-gravferdkalkulator": {
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
    },
    "historisk-riddler": {
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
    },
    "infotek-statistikk": {
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
    },
    "historisk-pensjon": {
        "tsconfig_new": {
            "extends": "@navikt/infotek-frontend-config/tsconfig.base.json",
            "compilerOptions": {
                "useDefineForClassFields": True,
                "noFallthroughCasesInSwitch": True,
                "types": ["vite/client", "vitest/globals"],
            },
            "include": ["src"],
        },
        "add_scripts": {
            "lint": "biome check .",
            "format": "biome format --write .",
        },
    },
    "historisk-regnskap": {
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
        "add_scripts": {
            "lint": "biome check .",
            "format": "biome format --write .",
        },
    },
    "historisk-tidsbegrenset-uforestonad": {
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
        "remove_deps": ["eslint"],
        "remove_inline_eslint_config": True,
        "add_scripts": {
            "lint": "biome check .",
            "format": "biome format --write .",
        },
    },
    "infotek-databaseuttrekk": {
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


@dataclass
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass
class FileSnapshot:
    existed: bool
    content: bytes | None


class FileTransaction:
    def __init__(self) -> None:
        self._snapshots: dict[Path, FileSnapshot] = {}

    def watch(self, path: Path) -> None:
        if path in self._snapshots:
            return
        if path.exists():
            self._snapshots[path] = FileSnapshot(True, path.read_bytes())
        else:
            self._snapshots[path] = FileSnapshot(False, None)

    def rollback(self) -> None:
        for path, snapshot in reversed(list(self._snapshots.items())):
            if snapshot.existed:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(snapshot.content or b"")
            elif path.exists():
                path.unlink()

    def snapshot_for(self, path: Path) -> FileSnapshot | None:
        return self._snapshots.get(path)


def run_pnpm_install(frontend_dir: Path, timeout_seconds: int) -> CommandResult:
    env = os.environ.copy()
    env["NODE_NO_WARNINGS"] = "1"
    print("     pnpm-output følger under:", flush=True)
    try:
        process = subprocess.Popen(
            ["pnpm", "install", "--no-frozen-lockfile"],
            cwd=frontend_dir,
            env=env,
            stdout=None,
            stderr=None,
            text=True,
        )
        try:
            return CommandResult(process.wait(timeout=timeout_seconds))
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            return CommandResult(124, stderr=f"pnpm install overskred {timeout_seconds} sekunder")
    except OSError as exc:
        return CommandResult(1, stderr=str(exc))


def load_jsonc(path: Path) -> dict:
    """Les JSON og JSONC uten å bruke ekstern parser."""
    text = path.read_text()
    result: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            result.append(c)
            i += 1
            while i < n:
                sc = text[i]
                result.append(sc)
                if sc == "\\":
                    i += 1
                    if i < n:
                        result.append(text[i])
                elif sc == '"':
                    break
                i += 1
        elif c == "/" and i + 1 < n:
            if text[i + 1] == "/":
                while i < n and text[i] != "\n":
                    i += 1
                continue
            if text[i + 1] == "*":
                i += 2
                while i < n - 1 and not (text[i] == "*" and text[i + 1] == "/"):
                    i += 1
                i += 2
                continue
            result.append(c)
        else:
            result.append(c)
        i += 1
    return json.loads("".join(result))


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def load_base_configs(
    tsconfig_path: Path = TSCONFIG_BASE_PATH,
    biome_path: Path = BIOME_BASE_PATH,
) -> tuple[dict, dict]:
    return load_jsonc(tsconfig_path), load_jsonc(biome_path)


def load_managed_repo_names(path: Path = REPOS_YAML) -> set[str]:
    managed: set[str] = set()
    current_name: str | None = None
    current_managed = False
    in_repos = False

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line == "repos:":
            in_repos = True
            continue
        if not in_repos:
            continue
        if line.startswith("- name:"):
            if current_name and current_managed:
                managed.add(current_name)
            current_name = line.split(":", 1)[1].strip()
            current_managed = False
            continue
        if line.startswith("managed:"):
            current_managed = line.split(":", 1)[1].strip().lower() == "true"

    if current_name and current_managed:
        managed.add(current_name)
    return managed


def select_repositories(
    repo_configs: dict[str, dict],
    managed_names: set[str],
    repo_filter: str | None = None,
) -> dict[str, dict]:
    selected: dict[str, dict] = {}
    for repo_name, config in repo_configs.items():
        if repo_name not in managed_names:
            continue
        if repo_filter and repo_filter != repo_name:
            continue
        selected[repo_name] = config
    return selected


def safe_relative(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def find_effective_npmrc(frontend_dir: Path, repo_dir: Path) -> Path | None:
    current = frontend_dir
    while True:
        candidate = current / ".npmrc"
        if candidate.exists():
            return candidate
        if current == repo_dir:
            return None
        current = current.parent


def parse_npmrc(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        entries[key.strip()] = value.strip()
    return entries


def ensure_internal_package_registries(
    frontend_dir: Path,
    repo_dir: Path,
    tx: FileTransaction,
) -> tuple[Path, bool]:
    npmrc_path = find_effective_npmrc(frontend_dir, repo_dir)
    if npmrc_path is None:
        npmrc_path = frontend_dir / ".npmrc"

    entries = parse_npmrc(npmrc_path) if npmrc_path.exists() else {}
    wanted = {
        **{f"{scope}:registry": registry for scope, registry in INTERNAL_SCOPES.items()},
        "registry": NPM_REGISTRY,
    }
    package_registry_absent = f"{PACKAGE_NAME}:registry" not in entries
    if all(entries.get(key, "").rstrip("/") == value.rstrip("/") for key, value in wanted.items()) and package_registry_absent:
        return npmrc_path, False

    tx.watch(npmrc_path)
    lines = npmrc_path.read_text().splitlines() if npmrc_path.exists() else []
    updated: list[str] = []
    replaced: set[str] = set()
    for line in lines:
        stripped = line.strip()
        key = stripped.split("=", 1)[0] if "=" in stripped else ""
        if key == f"{PACKAGE_NAME}:registry":
            continue
        if key in wanted:
            updated.append(f"{key}={wanted[key]}")
            replaced.add(key)
            continue
        updated.append(line)
    missing = [key for key in wanted if key not in replaced]
    if missing and updated and updated[-1]:
        updated.append("")
    updated.extend(f"{key}={wanted[key]}" for key in missing)
    npmrc_path.parent.mkdir(parents=True, exist_ok=True)
    npmrc_path.write_text("\n".join(updated) + "\n")
    return npmrc_path, True


def update_package_json(frontend_dir: Path, config: dict, tx: FileTransaction) -> tuple[bool, bool]:
    pkg_path = frontend_dir / "package.json"
    tx.watch(pkg_path)
    data = load_jsonc(pkg_path)
    changed = False
    requires_install = False

    dev_deps = data.setdefault("devDependencies", {})
    if PACKAGE_NAME in dev_deps:
        del dev_deps[PACKAGE_NAME]
        changed = True
        requires_install = True

    for dep in config.get("remove_deps", []):
        if dep in dev_deps:
            del dev_deps[dep]
            changed = True
            requires_install = True

    if config.get("remove_inline_eslint_config") and "eslintConfig" in data:
        del data["eslintConfig"]
        changed = True

    scripts = data.setdefault("scripts", {})
    for name, command in config.get("add_scripts", {}).items():
        if scripts.get(name) != command:
            scripts[name] = command
            changed = True

    pnpm_overrides = data.get("pnpm", {}).get("overrides")
    if pnpm_overrides:
        workspace_path = frontend_dir / "pnpm-workspace.yaml"
        tx.watch(workspace_path)
        _write_pnpm_workspace(workspace_path, pnpm_overrides)
        if len(data["pnpm"]) == 1:
            del data["pnpm"]
        else:
            del data["pnpm"]["overrides"]
        changed = True
        requires_install = True

    if changed:
        data["devDependencies"] = dict(sorted(dev_deps.items()))
        write_json(pkg_path, data)

    return changed, requires_install


def _write_pnpm_workspace(path: Path, overrides: dict) -> None:
    existing = path.read_text().splitlines() if path.exists() else []
    override_lines = ["overrides:"]
    override_lines.extend(f'  "{package}": "{version}"' for package, version in overrides.items())

    start = next((index for index, line in enumerate(existing) if line.strip() == "overrides:"), None)
    if start is None:
        if existing and existing[-1]:
            existing.append("")
        existing.extend(override_lines)
    else:
        end = start + 1
        while end < len(existing) and (not existing[end].strip() or existing[end].startswith((" ", "\t"))):
            end += 1
        existing[start:end] = override_lines

    path.write_text("\n".join(existing) + "\n")


def write_biome_json(frontend_dir: Path, base_config: dict, tx: FileTransaction) -> bool:
    biome_path = frontend_dir / "biome.json"
    new_content = base_config
    if biome_path.exists():
        existing = load_jsonc(biome_path)
        if existing == new_content:
            return False
    tx.watch(biome_path)
    write_json(biome_path, new_content)
    return True


def merge_tsconfig(base_config: dict, configured: dict) -> dict:
    return {
        **base_config,
        **{key: value for key, value in configured.items() if key not in {"extends", "compilerOptions"}},
        "compilerOptions": {
            **base_config.get("compilerOptions", {}),
            **configured.get("compilerOptions", {}),
        },
    }


def write_tsconfig(frontend_dir: Path, config: dict, base_config: dict, tx: FileTransaction) -> bool:
    tsconfig_path = frontend_dir / config.get("tsconfig_file", "tsconfig.json")
    new_content = merge_tsconfig(base_config, config["tsconfig_new"])
    if tsconfig_path.exists():
        existing = load_jsonc(tsconfig_path)
        if existing == new_content:
            return False
    tx.watch(tsconfig_path)
    write_json(tsconfig_path, new_content)
    return True


def remove_eslint_files(frontend_dir: Path, config: dict, tx: FileTransaction) -> bool:
    changed = False
    for file_name in config.get("eslint_files", []):
        path = frontend_dir / file_name
        if not path.exists():
            continue
        tx.watch(path)
        path.unlink()
        changed = True
    return changed


def planned_changes(
    frontend_dir: Path,
    config: dict,
    tsconfig_base: dict,
    biome_base: dict,
) -> tuple[list[str], bool]:
    changed_files: list[str] = []
    requires_install = False

    package_data = load_jsonc(frontend_dir / "package.json")
    dev_dependencies = package_data.get("devDependencies", {})
    scripts = package_data.get("scripts", {})
    package_changed = (
        PACKAGE_NAME in dev_dependencies
        or any(dep in dev_dependencies for dep in config.get("remove_deps", []))
        or (config.get("remove_inline_eslint_config") and "eslintConfig" in package_data)
        or any(scripts.get(name) != command for name, command in config.get("add_scripts", {}).items())
        or bool(package_data.get("pnpm", {}).get("overrides"))
    )
    if package_changed:
        changed_files.append("package.json")
        requires_install = (
            PACKAGE_NAME in dev_dependencies
            or any(dep in dev_dependencies for dep in config.get("remove_deps", []))
            or bool(package_data.get("pnpm", {}).get("overrides"))
        )

    biome_path = frontend_dir / "biome.json"
    if not biome_path.exists() or load_jsonc(biome_path) != biome_base:
        changed_files.append("biome.json")

    tsconfig_name = config.get("tsconfig_file", "tsconfig.json")
    tsconfig_path = frontend_dir / tsconfig_name
    expected_tsconfig = merge_tsconfig(tsconfig_base, config["tsconfig_new"])
    if not tsconfig_path.exists() or load_jsonc(tsconfig_path) != expected_tsconfig:
        changed_files.append(tsconfig_name)

    changed_files.extend(
        file_name
        for file_name in config.get("eslint_files", [])
        if (frontend_dir / file_name).exists()
    )
    npmrc_path = find_effective_npmrc(frontend_dir, frontend_dir.parent)
    npmrc_entries = parse_npmrc(npmrc_path) if npmrc_path else {}
    wanted_registries = {
        **{f"{scope}:registry": registry for scope, registry in INTERNAL_SCOPES.items()},
        "registry": NPM_REGISTRY,
    }
    if (
        any(
            npmrc_entries.get(key, "").rstrip("/") != value.rstrip("/")
            for key, value in wanted_registries.items()
        )
        or f"{PACKAGE_NAME}:registry" in npmrc_entries
    ):
        changed_files.append(".npmrc")
    return changed_files, requires_install


def print_change_summary(repo_name: str, changed_files: list[str]) -> None:
    print(f"\n🔄 {repo_name}")
    print(f"  → fjerner {PACKAGE_NAME} og skriver eksplisitt lokal konfig")
    for file_name in changed_files:
        print(f"  → oppdaterer {file_name}")


def migrate_repo(
    repo_name: str,
    config: dict,
    repos_dir: Path = REPOS_DIR,
    tsconfig_base: dict | None = None,
    biome_base: dict | None = None,
    dry_run: bool = False,
    install_timeout_seconds: int = DEFAULT_INSTALL_TIMEOUT_SECONDS,
) -> bool:
    repo_dir = repos_dir / repo_name
    frontend_dir = repo_dir / "frontend"

    if not frontend_dir.exists():
        print(f"  ⏭  {repo_name} — ingen frontend-mappe")
        return True

    if tsconfig_base is None or biome_base is None:
        tsconfig_base, biome_base = load_base_configs()

    changed_files, requires_install = planned_changes(frontend_dir, config, tsconfig_base, biome_base)
    if not changed_files:
        print(f"  ✅ {repo_name} — har allerede eksplisitt lokal konfig")
        return True

    print_change_summary(repo_name, changed_files)

    if dry_run:
        print("  → vil kontrollere at @navikt- og @nais-pakker hentes fra GitHub Packages")
        if requires_install:
            print(f"  → vil kjøre pnpm install --no-frozen-lockfile med timeout {install_timeout_seconds}s")
        else:
            print("  → pnpm install er ikke nødvendig")
        print("  → stopper etter validering. Publiser selv.")
        return True

    tx = FileTransaction()

    try:
        npmrc_path, npmrc_changed = ensure_internal_package_registries(frontend_dir, repo_dir, tx)
        if npmrc_changed:
            print(f"  ✅ oppdaterte package-registry i {safe_relative(npmrc_path, repo_dir)}")
        else:
            print(f"  ✅ registry ok i {safe_relative(npmrc_path, repo_dir)}")

        package_changed, requires_install = update_package_json(frontend_dir, config, tx)
        biome_changed = write_biome_json(frontend_dir, biome_base, tx)
        tsconfig_changed = write_tsconfig(frontend_dir, config, tsconfig_base, tx)
        eslint_changed = remove_eslint_files(frontend_dir, config, tx)

        changed_files: list[str] = []
        if package_changed:
            changed_files.append("package.json")
        if biome_changed:
            changed_files.append("biome.json")
        if tsconfig_changed:
            changed_files.append(config.get("tsconfig_file", "tsconfig.json"))
        if eslint_changed:
            changed_files.extend(config.get("eslint_files", []))

        if not changed_files:
            print("  ⏭  ingen endringer")
            return True

        if not requires_install:
            print("  ✅ lokale filer er oppdatert. pnpm install er ikke nødvendig.")
            print("  → stoppet etter validering. Publiser selv.")
            return True

        lockfile = frontend_dir / "pnpm-lock.yaml"
        tx.watch(lockfile)
        lockfile_snapshot = tx.snapshot_for(lockfile)

        print(f"  ⏳ pnpm install --no-frozen-lockfile i {safe_relative(frontend_dir, repo_dir)}")
        result = run_pnpm_install(frontend_dir, install_timeout_seconds)
        if result.stdout.strip():
            print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")

        if result.returncode != 0:
            print("  ❌ pnpm install feilet. Rydder repoet for denne kjøringen.")
            if result.stderr.strip():
                print(result.stderr)
            tx.rollback()
            return False

        if not lockfile.exists():
            print("  ❌ pnpm-lock.yaml mangler etter pnpm install. Rydder repoet.")
            tx.rollback()
            return False

        if lockfile_snapshot is not None and lockfile_snapshot.existed and lockfile.read_bytes() == (lockfile_snapshot.content or b""):
            print("  ❌ pnpm install oppdaterte ikke pnpm-lock.yaml. Rydder repoet.")
            tx.rollback()
            return False

        print("  ✅ pnpm-lock.yaml er oppdatert")
        print("  → stoppet etter validering. Publiser selv.")
        return True
    except Exception as exc:
        tx.rollback()
        print(f"  ❌ {repo_name} feilet: {exc}")
        return False


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrer managed frontend-repos til eksplisitt lokal TypeScript- og Biome-konfig."
    )
    parser.add_argument("--dry-run", action="store_true", help="Vis hva som skjer uten å skrive filer")
    parser.add_argument(
        "--repo-filter",
        "--repo",
        dest="repo_filter",
        help="Begrens kjøringen til dette eksakte repo-navnet",
    )
    parser.add_argument(
        "--install-timeout",
        type=int,
        default=DEFAULT_INSTALL_TIMEOUT_SECONDS,
        help="Timeout i sekunder for pnpm install",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    tsconfig_base, biome_base = load_base_configs()
    managed_names = load_managed_repo_names()
    targets = select_repositories(REPO_CONFIGS, managed_names, args.repo_filter)

    if not targets:
        if args.repo_filter:
            print(f"Ingen managed repos matcha filteret {args.repo_filter!r}")
        else:
            print("Ingen managed frontend-repos funnet i repos.yaml")
        return 1

    print(
        f"{'[DRY-RUN] ' if args.dry_run else ''}"
        f"Migrerer {len(targets)} repos til eksplisitt lokal frontend-konfig\n"
    )

    for repo_name, config in targets.items():
        ok = migrate_repo(
            repo_name,
            config,
            repos_dir=REPOS_DIR,
            tsconfig_base=tsconfig_base,
            biome_base=biome_base,
            dry_run=args.dry_run,
            install_timeout_seconds=args.install_timeout,
        )
        if not ok:
            return 1

    print("\nFerdig. Gjennomgå endringene og publiser selv.")
    if args.dry_run:
        print("Kjør uten --dry-run for å skrive filer.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
