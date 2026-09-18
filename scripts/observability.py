#!/usr/bin/env python3
"""Sjekk og oppdater observability-oppsett i managed repoer."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPOS_FILE = ROOT / "repos.yaml"
REPOS_DIR = ROOT / "repos"
APM_VERSION = "0.6.3"
IGNORED_PARTS = {"build", "dist", "node_modules", "target"}
ENTRYPOINTS = (
    "src/main.tsx",
    "src/main.ts",
    "src/index.tsx",
    "src/index.ts",
)
CUSTOM_CODE_PATTERNS = {
    "FrontendLoggerController": re.compile(r"\bFrontendLoggerController\b"),
    "LoggingInterceptor": re.compile(r"\bLoggingInterceptor\b"),
    "LogFilter": re.compile(r"\b(?:class|object)\s+LogFilter\b"),
    "MetricsInterceptorFactory": re.compile(r"\bMetricsInterceptorFactory\b"),
}


@dataclass(frozen=True)
class Repository:
    name: str
    namespace: str
    default_branch: str
    environments: tuple[str, ...]
    frontend_observability: bool = True
    nais_app: str | None = None

    @property
    def has_gcp(self) -> bool:
        return any(environment.endswith("-gcp") for environment in self.environments)


@dataclass
class Result:
    repository: str
    status: str = "compliant"
    changes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def needs_changes(self, message: str) -> None:
        self.changes.append(message)
        if self.status == "compliant":
            self.status = "changes-needed"

    def manual_review(self, message: str) -> None:
        self.warnings.append(message)
        if self.status == "compliant":
            self.status = "manual-review"


def parse_scalar(value: str) -> str:
    return value.strip().strip("\"'")


def parse_environments(value: str) -> tuple[str, ...]:
    stripped = value.strip()
    if not stripped.startswith("[") or not stripped.endswith("]"):
        return ()
    return tuple(
        parse_scalar(item)
        for item in stripped[1:-1].split(",")
        if parse_scalar(item)
    )


def parse_repositories(path: Path = REPOS_FILE) -> list[Repository]:
    repositories: list[Repository] = []
    current: dict[str, str] = {}

    def append_current() -> None:
        if current.get("managed") != "true":
            return
        repositories.append(
            Repository(
                name=current["name"],
                namespace=current["namespace"],
                default_branch=current.get("default_branch", "main"),
                environments=parse_environments(current.get("environments", "[]")),
                frontend_observability=current.get("frontend_observability", "true") != "false",
                nais_app=current.get("nais_app"),
            )
        )

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if line.startswith("- name:"):
            append_current()
            current = {"name": parse_scalar(line.split(":", 1)[1])}
        elif current and ":" in line and not line.startswith("#"):
            key, value = line.split(":", 1)
            current[key.strip()] = parse_scalar(value.split("#", 1)[0])
    append_current()
    return repositories


def is_ignored(path: Path) -> bool:
    return bool(IGNORED_PARTS.intersection(path.parts))


def files_named(repo_dir: Path, name: str) -> list[Path]:
    return sorted(path for path in repo_dir.rglob(name) if not is_ignored(path))


def read_json(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path} inneholder ikke et JSON-objekt")
    return data


def frontend_packages(repo_dir: Path) -> list[Path]:
    packages: list[Path] = []
    for path in files_named(repo_dir, "package.json"):
        try:
            package = read_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        dependencies = package.get("dependencies", {})
        dev_dependencies = package.get("devDependencies", {})
        if not isinstance(dependencies, dict) or not isinstance(dev_dependencies, dict):
            continue
        all_dependencies = {**dependencies, **dev_dependencies}
        if (
            "react" in all_dependencies
            or "vite" in all_dependencies
            or "next" in all_dependencies
        ):
            packages.append(path)
    return packages


def java_repository(repo_dir: Path) -> bool:
    return bool(files_named(repo_dir, "pom.xml"))


def nais_manifests(repo_dir: Path) -> list[Path]:
    manifests: list[Path] = []
    for suffix in ("*.yml", "*.yaml"):
        for path in repo_dir.rglob(suffix):
            if is_ignored(path):
                continue
            content = path.read_text(errors="ignore")
            if re.search(r"(?m)^\s*kind:\s*[\"']?Application[\"']?\s*$", content):
                manifests.append(path)
    return sorted(set(manifests))


def git_status(repo_dir: Path) -> tuple[str, bool]:
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo_dir,
        check=False,
        capture_output=True,
        text=True,
    ).stdout.strip() or "detached"
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_dir,
            check=False,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    return branch, dirty


def detect_indent(path: Path) -> int:
    for line in path.read_text().splitlines():
        match = re.match(r"^(\s+)\"", line)
        if match:
            return len(match.group(1))
    return 2


def ensure_apm_dependency(package_path: Path, apply: bool, result: Result) -> bool:
    package = read_json(package_path)
    dependencies = package.setdefault("dependencies", {})
    if not isinstance(dependencies, dict):
        result.manual_review(f"{package_path}: dependencies er ikke et objekt")
        return False
    current = dependencies.get("@nais/apm")
    if current == APM_VERSION:
        return False
    result.needs_changes(
        f"{package_path}: @nais/apm {current or 'mangler'} -> {APM_VERSION}"
    )
    if apply:
        dependencies["@nais/apm"] = APM_VERSION
        package_path.write_text(
            json.dumps(package, ensure_ascii=False, indent=detect_indent(package_path)) + "\n"
        )
    return True


def ensure_npmrc(frontend_dir: Path, apply: bool, result: Result) -> bool:
    path = frontend_dir / ".npmrc"
    existing = path.read_text().splitlines() if path.is_file() else []
    additions = [
        line
        for line in (
            "@nais:registry=https://npm.pkg.github.com/",
            "//npm.pkg.github.com/:_authToken=${NODE_AUTH_TOKEN}",
        )
        if line not in existing
    ]
    if not additions:
        return False
    result.needs_changes(f"{path}: legg til @nais-registry")
    if apply:
        content = path.read_text() if path.is_file() else ""
        separator = "" if not content or content.endswith("\n") else "\n"
        path.write_text(content + separator + "\n".join(additions) + "\n")
    return True


def find_entrypoint(frontend_dir: Path) -> Path | None:
    for relative_path in ENTRYPOINTS:
        candidate = frontend_dir / relative_path
        if candidate.is_file():
            return candidate
    return None


def observability_module() -> str:
    return (
        'import { init } from "@nais/apm";\n\n'
        "export function initializeObservability() {\n"
        "    init();\n"
        "}\n"
    )


def observability_test() -> str:
    return (
        'import { beforeEach, expect, test, vi } from "vitest";\n\n'
        "const { init } = vi.hoisted(() => ({ init: vi.fn() }));\n\n"
        'vi.mock("@nais/apm", () => ({ init }));\n\n'
        'import { initializeObservability } from "./observability";\n\n'
        "beforeEach(() => {\n"
        "    vi.clearAllMocks();\n"
        "});\n\n"
        'test("initialiserer Nais frontend-observability", () => {\n'
        "    initializeObservability();\n\n"
        "    expect(init).toHaveBeenCalledOnce();\n"
        "});\n"
    )


def ensure_frontend_initialization(
    package_path: Path,
    repository: Repository,
    apply: bool,
    result: Result,
) -> bool:
    frontend_dir = package_path.parent
    entrypoint = find_entrypoint(frontend_dir)
    if entrypoint is None:
        result.manual_review(f"{frontend_dir}: fant ikke støttet frontend-entrypoint")
        return False

    source_dir = entrypoint.parent
    module_path = source_dir / "observability.ts"
    test_path = source_dir / "observability.test.ts"
    changed = False

    expected_module = observability_module()
    if not module_path.is_file():
        result.needs_changes(f"{module_path}: opprett @nais/apm-initialisering")
        changed = True
        if apply:
            module_path.write_text(expected_module)
    else:
        module_content = module_path.read_text()
        if (
            "@nais/apm" not in module_content
            or "export function initializeObservability" not in module_content
        ):
            result.manual_review(
                f"{module_path}: eksisterende observability-modul må vurderes"
            )
            return changed

    if not test_path.is_file():
        result.needs_changes(f"{test_path}: legg til initialiseringstest")
        changed = True
        if apply:
            test_path.write_text(observability_test())

    content = entrypoint.read_text()
    import_line = 'import { initializeObservability } from "./observability";'
    if import_line not in content:
        content = import_line + "\n" + content
        result.needs_changes(f"{entrypoint}: importer initializeObservability")
        changed = True
    if "initializeObservability();" not in content:
        lines = content.splitlines()
        last_import = max(
            (index for index, line in enumerate(lines) if line.startswith("import ")),
            default=-1,
        )
        lines[last_import + 1:last_import + 1] = ["", "initializeObservability();"]
        content = "\n".join(lines) + ("\n" if entrypoint.read_text().endswith("\n") else "")
        result.needs_changes(f"{entrypoint}: initialiser observability før React")
        changed = True
    if apply and content != entrypoint.read_text():
        entrypoint.write_text(content)
    return changed


def remove_elastic_destination(content: str) -> tuple[str, bool]:
    lines = content.splitlines(keepends=True)
    updated = [
        line
        for line in lines
        if not re.match(r"^\s*-\s+id:\s*[\"']?elastic[\"']?\s*(?:#.*)?$", line.rstrip("\n"))
    ]
    return "".join(updated), len(updated) != len(lines)


def ensure_java_auto_instrumentation(content: str) -> tuple[str, str]:
    runtime_match = re.search(r"(?m)^\s*runtime:\s*[\"']?(\w+)[\"']?\s*$", content)
    if runtime_match:
        runtime = runtime_match.group(1)
        return content, "compliant" if runtime == "java" else f"runtime:{runtime}"

    lines = content.splitlines(keepends=True)
    observability_index = next(
        (
            index
            for index, line in enumerate(lines)
            if re.match(r"^  observability:\s*(?:#.*)?$", line.rstrip("\n"))
        ),
        None,
    )
    block = [
        "    autoInstrumentation:\n",
        "      enabled: true\n",
        "      runtime: java\n",
    ]
    if observability_index is not None:
        lines[observability_index + 1:observability_index + 1] = block
        return "".join(lines), "changed"

    spec_index = next(
        (
            index
            for index, line in enumerate(lines)
            if re.match(r"^spec:\s*(?:#.*)?$", line.rstrip("\n"))
        ),
        None,
    )
    if spec_index is None:
        return content, "invalid"
    lines[spec_index + 1:spec_index + 1] = [
        "  observability:\n",
        *block,
    ]
    return "".join(lines), "changed"


def update_manifest(path: Path, apply: bool, java: bool, result: Result) -> None:
    content = path.read_text()
    updated, removed_elastic = remove_elastic_destination(content)
    if removed_elastic:
        result.needs_changes(f"{path}: fjern Elastic-loggdestinasjon")

    if java:
        updated, instrumentation = ensure_java_auto_instrumentation(updated)
        if instrumentation == "changed":
            result.needs_changes(f"{path}: aktiver Java auto-instrumentering")
        elif instrumentation.startswith("runtime:"):
            result.manual_review(
                f"{path}: behold {instrumentation.removeprefix('runtime:')}-runtime til manuell vurdering"
            )
        elif instrumentation == "invalid":
            result.manual_review(f"{path}: fant ikke spec-blokk")

    if apply and updated != content:
        path.write_text(updated)


def custom_code_candidates(repo_dir: Path) -> list[str]:
    candidates: set[str] = set()
    for suffix in ("*.kt", "*.java", "*.ts", "*.tsx"):
        for path in repo_dir.rglob(suffix):
            if is_ignored(path) or "/src/test/" in path.as_posix():
                continue
            content = path.read_text(errors="ignore")
            for label, pattern in CUSTOM_CODE_PATTERNS.items():
                if pattern.search(content):
                    candidates.add(f"{label}: {path.relative_to(repo_dir)}")
    return sorted(candidates)


def package_manager_command(package_path: Path) -> list[str] | None:
    package = read_json(package_path)
    package_manager = package.get("packageManager")
    if isinstance(package_manager, str):
        manager = package_manager.split("@", 1)[0]
        commands = {
            "pnpm": ["pnpm", "install", "--lockfile-only"],
            "npm": ["npm", "install", "--package-lock-only"],
            "yarn": ["yarn", "install", "--mode=update-lockfile"],
        }
        if manager in commands:
            return commands[manager]
    for lockfile, command in (
        ("pnpm-lock.yaml", ["pnpm", "install", "--lockfile-only"]),
        ("package-lock.json", ["npm", "install", "--package-lock-only"]),
        ("yarn.lock", ["yarn", "install", "--mode=update-lockfile"]),
    ):
        if (package_path.parent / lockfile).is_file():
            return command
    return None


def update_lockfile(package_path: Path, result: Result) -> None:
    command = package_manager_command(package_path)
    if command is None:
        result.manual_review(f"{package_path.parent}: fant ikke package manager for lockfil")
        return
    completed = subprocess.run(
        command,
        cwd=package_path.parent,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        result.status = "blocked"
        result.warnings.append(
            f"{package_path.parent}: {' '.join(command)} feilet med exit {completed.returncode}"
        )


def process_repository(
    repository: Repository,
    apply: bool,
    update_lockfiles: bool,
    repos_dir: Path = REPOS_DIR,
) -> Result:
    result = Result(repository.name)
    repo_dir = repos_dir / repository.name
    if not (repo_dir / ".git").is_dir():
        result.status = "blocked"
        result.warnings.append(f"{repo_dir}: mangler lokal arbeidskopi")
        return result

    branch, dirty = git_status(repo_dir)
    if apply and dirty:
        result.status = "blocked"
        result.warnings.append(
            f"{repo_dir}: {branch} har lokale endringer"
        )
        return result
    if apply and branch in {"detached", repository.default_branch}:
        result.status = "blocked"
        result.warnings.append(
            f"{repo_dir}: opprett en feature-branch fra {repository.default_branch} før --apply"
        )
        return result

    packages = frontend_packages(repo_dir)
    changed_packages: list[Path] = []
    if packages and repository.has_gcp and repository.frontend_observability:
        for package_path in packages:
            dependency_changed = ensure_apm_dependency(package_path, apply, result)
            config_changed = ensure_npmrc(package_path.parent, apply, result)
            source_changed = ensure_frontend_initialization(
                package_path, repository, apply, result
            )
            if dependency_changed or config_changed or source_changed:
                changed_packages.append(package_path)
    elif packages and not repository.frontend_observability:
        result.warnings.append("frontend-observability er eksplisitt deaktivert")
    elif packages and not repository.has_gcp:
        result.warnings.append("FSS-frontend ignoreres")

    java = java_repository(repo_dir)
    for manifest in nais_manifests(repo_dir):
        update_manifest(manifest, apply, java, result)

    for candidate in custom_code_candidates(repo_dir):
        result.manual_review(f"custom observability-kandidat: {candidate}")

    if apply and update_lockfiles:
        for package_path in changed_packages:
            update_lockfile(package_path, result)

    return result


def print_result(result: Result, json_output: bool) -> None:
    if json_output:
        print(
            json.dumps(
                {
                    "repository": result.repository,
                    "status": result.status,
                    "changes": result.changes,
                    "warnings": result.warnings,
                },
                ensure_ascii=False,
            )
        )
        return
    print(f"{result.repository}: {result.status}")
    for change in result.changes:
        print(f"  -> {change}")
    for warning in result.warnings:
        print(f"  ! {warning}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="skriv sikre endringer")
    parser.add_argument("--repo", help="kjør bare ett managed repo")
    parser.add_argument(
        "--update-lockfiles",
        action="store_true",
        help="oppdater lockfiler etter package.json-endringer",
    )
    parser.add_argument("--json", action="store_true", help="skriv JSON lines")
    args = parser.parse_args()

    repositories = parse_repositories()
    if args.repo:
        repositories = [
            repository for repository in repositories if repository.name == args.repo
        ]
        if not repositories:
            print(f"Ukjent eller unmanaged repo: {args.repo}", file=sys.stderr)
            return 2

    results = [
        process_repository(repository, args.apply, args.update_lockfiles)
        for repository in repositories
    ]
    for result in results:
        print_result(result, args.json)

    return 1 if any(result.status == "blocked" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
