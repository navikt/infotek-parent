#!/usr/bin/env python3
"""Gjør valgte managed frontend-apper uavhengige av infotek-frontend-config."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
REPOS = ROOT / "repos"
PACKAGE = "@navikt/infotek-frontend-config"
FRONTEND_PATHS = ("frontend", "backend-for-frontend/frontend")


def read_jsonc(path: Path) -> dict:
    text = path.read_text()
    result: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == '"':
            start = index
            index += 1
            while index < len(text):
                if text[index] == "\\":
                    index += 2
                elif text[index] == '"':
                    index += 1
                    break
                else:
                    index += 1
            result.append(text[start:index])
            continue
        if text.startswith("//", index):
            index = text.find("\n", index)
            if index == -1:
                break
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            if end == -1:
                raise ValueError(f"Uavsluttet kommentar i {path}")
            index = end + 2
            continue
        result.append(char)
        index += 1
    data = json.loads("".join(result))
    if not isinstance(data, dict):
        raise ValueError(f"Forventet JSON-objekt i {path}")
    return data


def encoded(data: dict) -> bytes:
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode()


def managed_repos(path: Path) -> set[str]:
    names: set[str] = set()
    name: str | None = None
    managed = False
    for line in path.read_text().splitlines():
        if line.startswith("  - name: "):
            if name and managed:
                names.add(name)
            name = line.split(":", 1)[1].strip()
            managed = False
        elif name and line.startswith("    managed: "):
            managed = line.split(":", 1)[1].strip() == "true"
    if name and managed:
        names.add(name)
    return names


def frontend_for(repo: Path) -> Path | None:
    if repo.is_symlink() or not repo.resolve().is_relative_to(REPOS.resolve()):
        raise ValueError(f"Repo peker utenfor repos/: {repo}")
    if (repo / "backend-for-frontend").is_symlink():
        raise ValueError(f"Frontend inneholder symbolsk lenke: {repo}")
    paths = [repo / relative for relative in FRONTEND_PATHS if (repo / relative / "package.json").is_file()]
    if any(path.is_symlink() or path.parent.is_symlink() or (path / "package.json").is_symlink() for path in paths):
        raise ValueError(f"Frontend inneholder symbolsk lenke: {repo}")
    if len(paths) > 1:
        raise ValueError(f"{repo.name} har flere frontend-apper; velg en eksplisitt løsning")
    return paths[0] if paths else None


def choose_repos(candidates: list[str], answer: str) -> list[str]:
    choices = [part.strip() for part in answer.split(",")]
    if not choices or any(not part.isdigit() or not 1 <= int(part) <= len(candidates) for part in choices):
        raise ValueError("Oppgi ett eller flere numre fra menyen, adskilt med komma")
    return list(dict.fromkeys(candidates[int(part) - 1] for part in choices))


def merge(base: dict, local: dict) -> dict:
    result = dict(base)
    for key, value in local.items():
        if key == "extends":
            continue
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = value
    return result


def standalone_json(path: Path, base: dict) -> bytes | None:
    local = read_jsonc(path)
    extends = local.get("extends")
    if extends is None:
        if PACKAGE in path.read_text():
            raise ValueError(f"Ukjent referanse til {PACKAGE} i {path}")
        return None
    entries = [extends] if isinstance(extends, str) else extends
    if not isinstance(entries, list) or any(not isinstance(entry, str) for entry in entries):
        raise ValueError(f"Ukjent extends-format i {path}")
    references = [entry for entry in entries if PACKAGE in entry]
    if not references:
        return None
    if len(entries) != 1 or len(references) != 1 or not references[0].startswith(PACKAGE + "/"):
        raise ValueError(f"Kan ikke slå sammen flere extends i {path}")
    if path.name.startswith("tsconfig") and references[0] != PACKAGE + "/tsconfig.base.json":
        raise ValueError(f"Ukjent TypeScript-base i {path}")
    if path.name.startswith("biome") and references[0] != PACKAGE + "/biome.base.json":
        raise ValueError(f"Ukjent Biome-base i {path}")
    result = merge(base, local)
    if path.name == "biome.json" and "includes" in local.get("files", {}):
        result["files"]["includes"] = list(dict.fromkeys(
            base.get("files", {}).get("includes", []) + local["files"]["includes"]
        ))
    return encoded(result)


def remove_package_lines(path: Path) -> bytes | None:
    if not path.exists() or PACKAGE not in path.read_text():
        return None
    lines = path.read_text().splitlines(keepends=True)
    kept = []
    for line in lines:
        if PACKAGE not in line:
            kept.append(line)
        elif path.name == ".npmrc":
            if line.lstrip().startswith((PACKAGE + ":", "minimum-release-age-exclude[]=" + PACKAGE, "#")):
                continue
            raise ValueError(f"Ukjent pakkehenvisning i {path}")
        elif re.fullmatch(r"\s*-\s*['\"]?" + re.escape(PACKAGE) + r"['\"]?\s*(?:#.*)?\n?", line):
            continue
        else:
            raise ValueError(f"Ukjent pakkehenvisning i {path}")
    if path.name == "pnpm-workspace.yaml":
        kept = [line for index, line in enumerate(kept) if not (
            line.strip() == "minimumReleaseAgeExclude:"
            and (index + 1 == len(kept) or not kept[index + 1].startswith((" ", "\t")))
        )]
    return "".join(kept).encode()


def planned_files(frontend: Path, ts_base: dict, biome_base: dict) -> tuple[dict[Path, bytes], bool]:
    changes: dict[Path, bytes] = {}
    pkg_path = frontend / "package.json"
    paths = sorted(frontend.glob("tsconfig*.json")) + [
        pkg_path, frontend / "biome.json", frontend / "pnpm-workspace.yaml",
        frontend / ".npmrc", frontend / "pnpm-lock.yaml", frontend / "package-lock.json",
    ]
    if any(path.is_symlink() or not path.resolve().is_relative_to(frontend.resolve()) for path in paths):
        raise ValueError(f"Frontend inneholder fil som peker utenfor appen: {frontend}")
    package = read_jsonc(pkg_path)
    for section in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        deps = package.get(section, {})
        if PACKAGE in deps:
            del deps[PACKAGE]
            changes[pkg_path] = encoded(package)
    if PACKAGE in json.dumps(package):
        raise ValueError(f"Ukjent pakkehenvisning i {pkg_path}")

    for path in sorted(frontend.glob("tsconfig*.json")) + [frontend / "biome.json"]:
        if not path.exists():
            continue
        replacement = standalone_json(path, biome_base if path.name == "biome.json" else ts_base)
        if replacement is not None:
            changes[path] = replacement

    for path in (frontend / "pnpm-workspace.yaml", frontend / ".npmrc"):
        replacement = remove_package_lines(path)
        if replacement is not None and replacement != path.read_bytes():
            changes[path] = replacement

    lockfile = frontend / "pnpm-lock.yaml"
    if (frontend / "package-lock.json").exists():
        changes[frontend / "package-lock.json"] = b""
    needs_install = bool(changes) or (lockfile.exists() and PACKAGE in lockfile.read_text())
    if needs_install:
        if not lockfile.exists():
            raise ValueError(f"Mangler pnpm-lock.yaml i {frontend}")
        if not read_jsonc(pkg_path).get("scripts", {}).get("build"):
            raise ValueError(f"Mangler build-script i {pkg_path}")
        modules = frontend / "node_modules"
        if modules.is_symlink() or (modules.exists() and not modules.is_dir()):
            raise ValueError(f"Ugyldig node_modules i {frontend}")
        changes[lockfile] = lockfile.read_bytes()
    return changes, needs_install


def assert_safe_paths(repo: Path, frontend: Path, changes: dict[Path, bytes]) -> None:
    if repo.is_symlink() or frontend.is_symlink() or frontend.parent.is_symlink() or not repo.is_dir():
        raise ValueError(f"Ugyldig repo- eller frontend-sti: {repo}")
    for path in changes:
        if path.is_symlink() or not path.resolve().is_relative_to(frontend.resolve()):
            raise ValueError(f"Fil peker utenfor frontend: {path}")


def assert_clean(repo: Path) -> None:
    result = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True)
    if result.stdout.strip():
        raise ValueError(f"{repo.name} har lokale endringer; rydd arbeidskopien først")


def restore(frontend: Path, snapshots: dict[Path, bytes], backup: Path | None, cleanup_modules: bool = True) -> None:
    modules = frontend / "node_modules"
    if cleanup_modules and backup is not None:
        if modules.is_symlink():
            raise ValueError(f"node_modules ble erstattet med en symbolsk lenke i {frontend}")
        if modules.exists():
            shutil.rmtree(modules)
        backup.rename(modules)
    elif cleanup_modules and modules.exists():
        if modules.is_symlink():
            raise ValueError(f"node_modules ble erstattet med en symbolsk lenke i {frontend}")
        shutil.rmtree(modules)
    for path, content in snapshots.items():
        path.write_bytes(content)


def apply_changes(frontend: Path, changes: dict[Path, bytes], needs_install: bool) -> tuple[dict[Path, bytes], Path | None]:
    snapshots = {path: path.read_bytes() for path in changes}
    modules = frontend / "node_modules"
    backup: Path | None = None
    started = False
    try:
        if needs_install:
            package_manager = read_jsonc(frontend / "package.json").get("packageManager")
            if package_manager:
                expected = package_manager.removeprefix("pnpm@").split("+", 1)[0]
                if not package_manager.startswith("pnpm@"):
                    raise ValueError(f"Uventet packageManager i {frontend / 'package.json'}")
                version = subprocess.run(
                    ["pnpm", "--version"], cwd=frontend, check=True, capture_output=True, text=True, timeout=30,
                ).stdout.strip()
                if version != expected:
                    raise ValueError(f"{frontend}: forventet pnpm {expected}, fant {version}")
            if modules.is_symlink():
                raise ValueError(f"node_modules er en symbolsk lenke i {frontend}")
            if modules.exists():
                backup = frontend / f".node_modules-detach-backup-{uuid4().hex}"
                if backup.exists() or backup.is_symlink():
                    raise ValueError(f"Backup-sti finnes allerede: {backup}")
                modules.rename(backup)
        started = True
        for path, content in changes.items():
            if path.name == "package-lock.json":
                path.unlink()
            elif path.name != "pnpm-lock.yaml":
                path.write_bytes(content)
        if needs_install:
            (frontend / "pnpm-lock.yaml").unlink()
            subprocess.run(
                ["pnpm", "install", "--ignore-scripts", "--no-frozen-lockfile"],
                cwd=frontend, check=True, timeout=900,
            )
            lockfile = frontend / "pnpm-lock.yaml"
            if not lockfile.is_file() or lockfile.is_symlink():
                raise ValueError(f"pnpm-lock.yaml mangler eller er en symbolsk lenke i {frontend}")
            if PACKAGE in lockfile.read_text():
                raise ValueError(f"{PACKAGE} finnes fortsatt i {lockfile}")
            subprocess.run(
                ["pnpm", "install", "--ignore-scripts", "--frozen-lockfile"],
                cwd=frontend, check=True, timeout=900,
            )
            subprocess.run(["pnpm", "run", "build"], cwd=frontend, check=True, timeout=900)
        return snapshots, backup
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
        restore(frontend, snapshots, backup, cleanup_modules=started)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", action="append", help="Velg repo uten meny; kan oppgis flere ganger")
    parser.add_argument("--dry-run", action="store_true", help="Vis endringer uten å skrive filer")
    parser.add_argument("--yes", action="store_true", help="Bekreft endringer uten spørsmål")
    args = parser.parse_args(argv)
    env_repo = os.environ.get("FRONTEND_DETACH_REPO")
    if env_repo:
        if args.repo:
            parser.error("Bruk enten REPO eller --repo")
        args.repo = [env_repo]

    try:
        available = managed_repos(ROOT / "repos.yaml")
        candidates = sorted(
            name for name in available if (REPOS / name).is_dir() and frontend_for(REPOS / name)
        )
        if not candidates:
            raise ValueError("Ingen lokale managed frontend-repoer funnet")
        if args.repo:
            selected = list(dict.fromkeys(args.repo))
            if any(name not in candidates for name in selected):
                raise ValueError("Ukjent eller unmanaged repo, eller manglende frontend: " + ", ".join(
                    name for name in selected if name not in candidates
                ))
        else:
            if not sys.stdin.isatty():
                raise ValueError("Valgmenyen krever terminal; bruk REPO=<navn>")
            for index, name in enumerate(candidates, 1):
                print(f"{index}. {name}")
            selected = choose_repos(candidates, input("Velg repo (flere med komma): "))

        ts_base = read_jsonc(ROOT / "platform/pnpm/tsconfig.base.json")
        biome_base = read_jsonc(ROOT / "platform/pnpm/biome.base.json")
        work = []
        for name in selected:
            repo = REPOS / name
            frontend = frontend_for(repo)
            if frontend is None:
                raise ValueError(f"Fant ikke frontend i {name}")
            assert_clean(repo)
            changes, needs_install = planned_files(frontend, ts_base, biome_base)
            assert_safe_paths(repo, frontend, changes)
            work.append((name, frontend, changes, needs_install))

        for name, frontend, changes, needs_install in work:
            print(f"{name}: " + (", ".join(str(path.relative_to(frontend)) for path in changes) if changes else "allerede selvstendig"))
            if needs_install:
                print("  → regenererer pnpm-lock.yaml, erstatter node_modules og kjører pnpm run build")
        if args.dry_run or not any(changes for _, _, changes, _ in work):
            return 0
        if not args.yes:
            if not sys.stdin.isatty():
                raise ValueError("Bekreftelse krever terminal; bruk --yes for ikke-interaktiv kjøring")
            if input("Skriv lokale endringer? [j/N] ").strip().lower() != "j":
                print("Avbrutt")
                return 0
        completed: list[tuple[Path, dict[Path, bytes], Path | None]] = []
        try:
            for name, frontend, changes, needs_install in work:
                if changes:
                    snapshots, backup = apply_changes(frontend, changes, needs_install)
                    completed.append((frontend, snapshots, backup))
                    print(f"{name}: lokale frontend-filer oppdatert")
        except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            for frontend, snapshots, backup in reversed(completed):
                restore(frontend, snapshots, backup)
            raise
        for _, _, backup in completed:
            if backup is not None:
                if backup.is_symlink():
                    raise ValueError(f"Backup ble erstattet med symbolsk lenke: {backup}")
                shutil.rmtree(backup)
        return 0
    except (OSError, ValueError, EOFError, KeyboardInterrupt, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"Feil: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
