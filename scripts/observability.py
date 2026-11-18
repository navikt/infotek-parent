#!/usr/bin/env python3
"""Sjekk og oppdater observability-oppsett i managed repoer."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPOS_FILE = ROOT / "repos.yaml"
REPOS_DIR = ROOT / "repos"
APM_VERSION = "0.6.3"
VITEST_VERSION = "^4.1.11"
IGNORED_PARTS = {"build", "dist", "node_modules", "target"}
ENTRYPOINTS = (
    "src/main.tsx",
    "src/main.ts",
    "src/index.tsx",
    "src/index.ts",
)
CUSTOM_CODE_PATTERNS = {
    "CallIdInterceptor": re.compile(r"\bCallIdInterceptor\b"),
    "MdcHelper": re.compile(r"\bMdcHelper\b"),
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
        if message not in self.changes:
            self.changes.append(message)
        if self.status == "compliant":
            self.status = "changes-needed"

    def manual_review(self, message: str) -> None:
        self.note(message)
        if self.status == "compliant":
            self.status = "manual-review"

    def note(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)


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


def version_tuple(spec: str) -> tuple[int, int, int] | None:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", spec)
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def ensure_apm_dependency(package_path: Path, apply: bool, result: Result) -> bool:
    package = read_json(package_path)
    dependencies = package.setdefault("dependencies", {})
    if not isinstance(dependencies, dict):
        result.manual_review(f"{package_path}: dependencies er ikke et objekt")
        return False
    current = dependencies.get("@nais/apm")
    if current is not None:
        current_version = version_tuple(current)
        if current_version is None:
            result.manual_review(f"{package_path}: ukjent @nais/apm-versjon {current}")
            return False
        if current_version >= version_tuple(APM_VERSION):
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


def ensure_vitest_dependency(package_path: Path, apply: bool, result: Result) -> bool:
    package = read_json(package_path)
    dependencies = package.get("dependencies", {})
    dev_dependencies = package.setdefault("devDependencies", {})
    if not isinstance(dependencies, dict) or not isinstance(dev_dependencies, dict):
        result.manual_review(f"{package_path}: dependencies/devDependencies er ikke objekter")
        return False
    if "vitest" in dependencies or "vitest" in dev_dependencies:
        return False
    result.needs_changes(f"{package_path}: legg til vitest {VITEST_VERSION} som devDependency")
    if apply:
        dev_dependencies["vitest"] = VITEST_VERSION
        package_path.write_text(
            json.dumps(package, ensure_ascii=False, indent=detect_indent(package_path)) + "\n"
        )
    return True


REGISTRY_LINE = "@nais:registry=https://npm.pkg.github.com/"
AUTH_TOKEN_LINE = "//npm.pkg.github.com/:_authToken=${NODE_AUTH_TOKEN}"
REGISTRY_PATTERN = re.compile(r"^@nais:registry=https://npm\.pkg\.github\.com/?\s*$")
GITHUB_PACKAGES_NPMRC_PATTERN = re.compile(
    r"^(?:@(?:nais|navikt):registry=https://npm\.pkg\.github\.com/?|"
    r"//npm\.pkg\.github\.com/:_authToken=\$\{[A-Z_]+\})\s*(?:#.*)?$"
)
AUTH_TOKEN_PATTERN = re.compile(
    r"^//npm\.pkg\.github\.com/:_authToken=\$\{(?P<var>[A-Z_]+)\}\s*$"
)
OUTDATED_TOKEN_VARS = {"NPM_TOKEN", "GITHUB_PACKAGES_TOKEN"}
NODE_PACKAGE_MANAGER_PATTERN = re.compile(r"(?<![\w./-])(npm|pnpm|yarn)(?![\w/-])")
NODE_INSTALL_COMMANDS = {
    "add",
    "ci",
    "dlx",
    "i",
    "install",
    "up",
    "update",
    "upgrade",
}
NODE_OPTIONS_WITH_VALUE = {"-C", "--dir", "--prefix", "--cwd", "--filter", "-F", "-w", "--workspace"}
SHELL_SEPARATORS = ("&&", "||", ";", "|")
NODE_AUTH_TOKEN_SECRET_PATTERN = re.compile(
    r"(?m)^\s*NODE_AUTH_TOKEN:\s*\$\{\{\s*secrets\.[A-Z0-9_]+\s*\}\}\s*(?:#.*)?$"
)
COMPOSITE_ACTION_TOKEN_INPUT_PATTERN = re.compile(
    r"(?m)^\s*node-auth-token:\s*\$\{\{\s*secrets\.[A-Z0-9_]+\s*\}\}\s*(?:#.*)?$"
)
LOCAL_COMPOSITE_ACTION_PATTERN = re.compile(
    r"^(?P<indent>\s*)-\s+uses:\s*(?P<path>\./[^\s#]+)\s*(?:#.*)?$"
)


def ensure_npmrc(frontend_dir: Path, apply: bool, result: Result) -> bool:
    path = frontend_dir / ".npmrc"
    existing = path.read_text().splitlines() if path.is_file() else []
    lines = list(existing)
    changed = False

    if not any(REGISTRY_PATTERN.match(line) for line in lines):
        lines.append(REGISTRY_LINE)
        changed = True
    else:
        lines = [
            REGISTRY_LINE if REGISTRY_PATTERN.match(line) and line != REGISTRY_LINE else line
            for line in lines
        ]
        if lines != existing:
            changed = True

    if not any(AUTH_TOKEN_PATTERN.match(line) for line in lines):
        lines.append(AUTH_TOKEN_LINE)
        changed = True
    else:
        normalized = []
        for line in lines:
            match = AUTH_TOKEN_PATTERN.match(line)
            if match and match.group("var") in OUTDATED_TOKEN_VARS:
                normalized.append(AUTH_TOKEN_LINE)
            else:
                normalized.append(line)
        if normalized != lines:
            changed = True
        lines = normalized

    if not changed:
        return False
    result.needs_changes(f"{path}: legg til/normaliser @nais-registry")
    if apply:
        path.write_text("\n".join(lines) + "\n")
    return True


def npmrc_uses_github_packages(frontend_dir: Path) -> bool:
    path = frontend_dir / ".npmrc"
    if not path.is_file():
        return False
    return any(
        GITHUB_PACKAGES_NPMRC_PATTERN.match(line.strip())
        for line in path.read_text().splitlines()
    )


def job_blocks(content: str) -> list[str]:
    jobs_match = re.search(r"(?m)^jobs:\s*(?:#.*)?$", content)
    if jobs_match is None:
        return []

    jobs_content = content[jobs_match.end():]
    matches = list(re.finditer(r"(?m)^  [A-Za-z0-9_-]+:\s*(?:#.*)?$", jobs_content))
    return [
        jobs_content[match.start(): matches[index + 1].start() if index + 1 < len(matches) else None]
        for index, match in enumerate(matches)
    ]


def command_installs_packages(command: str) -> bool:
    """Bare kommandoer som henter pakker fra registry trenger NODE_AUTH_TOKEN."""
    for match in NODE_PACKAGE_MANAGER_PATTERN.finditer(command):
        subcommand = None
        skip_value = False
        for token in command[match.end():].split():
            if token.startswith(SHELL_SEPARATORS):
                break
            if skip_value:
                skip_value = False
                continue
            if token.startswith("-"):
                skip_value = token in NODE_OPTIONS_WITH_VALUE
                continue
            subcommand = token.rstrip(";")
            break
        if subcommand is None:
            if match.group(1) == "yarn":
                return True
            continue
        if subcommand in NODE_INSTALL_COMMANDS:
            return True
    return False


def job_runs_node_package_manager(content: str) -> bool:
    lines = content.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^(\s*)(?:-\s+)?run:\s*(.*)$", line)
        if match is None:
            continue
        if command_installs_packages(match.group(2)):
            return True
        run_indent = len(match.group(1))
        for nested_line in lines[index + 1:]:
            if nested_line.strip() and len(nested_line) - len(nested_line.lstrip()) <= run_indent:
                break
            if command_installs_packages(nested_line):
                return True
    return False


def step_blocks(content: str) -> list[str]:
    lines = content.splitlines(keepends=True)
    starts = [
        index
        for index, line in enumerate(lines)
        if re.match(r"^\s*-\s+(?:name|run|uses):", line)
    ]
    return [
        "".join(lines[start: starts[index + 1] if index + 1 < len(starts) else None])
        for index, start in enumerate(starts)
    ]


def local_composite_action_runs_node_package_manager(repo_dir: Path, action_path: str) -> bool:
    action_dir = (repo_dir / action_path).resolve()
    try:
        action_dir.relative_to(repo_dir.resolve())
    except ValueError:
        return False
    for filename in ("action.yml", "action.yaml"):
        manifest = action_dir / filename
        if not manifest.is_file():
            continue
        content = manifest.read_text(errors="ignore")
        if job_runs_node_package_manager(content):
            return True
    return False


def local_composite_action_uses_node_auth_token(repo_dir: Path, action_path: str) -> bool:
    action_dir = (repo_dir / action_path).resolve()
    try:
        action_dir.relative_to(repo_dir.resolve())
    except ValueError:
        return False
    for filename in ("action.yml", "action.yaml"):
        manifest = action_dir / filename
        if not manifest.is_file():
            continue
        for step in step_blocks(manifest.read_text(errors="ignore")):
            if not job_runs_node_package_manager(step):
                continue
            if re.search(
                r"(?m)^\s*NODE_AUTH_TOKEN:\s*\$\{\{\s*inputs\.node-auth-token\s*\}\}\s*(?:#.*)?$",
                step,
            ):
                return True
    return False


def step_runs_node_package_manager(content: str) -> bool:
    return job_runs_node_package_manager(content)


def step_uses_node_composite_action(repo_dir: Path, content: str) -> bool:
    first_line = content.splitlines()[0]
    match = LOCAL_COMPOSITE_ACTION_PATTERN.match(first_line)
    return bool(
        match
        and local_composite_action_runs_node_package_manager(repo_dir, match.group("path"))
    )


def ensure_workflow_node_auth_token(
    frontend_dir: Path,
    repo_dir: Path,
    result: Result,
) -> None:
    if not npmrc_uses_github_packages(frontend_dir):
        return

    workflows_dir = repo_dir / ".github" / "workflows"
    if not workflows_dir.is_dir():
        result.manual_review(
            f"{frontend_dir}: GitHub Packages krever kontroll av NODE_AUTH_TOKEN i CI"
        )
        return

    for pattern in ("*.yml", "*.yaml"):
        for workflow in workflows_dir.glob(pattern):
            content = workflow.read_text(errors="ignore")
            for job in job_blocks(content):
                for step in step_blocks(job):
                    direct_package_manager = step_runs_node_package_manager(step)
                    local_composite_action = step_uses_node_composite_action(repo_dir, step)
                    if not direct_package_manager and not local_composite_action:
                        continue
                    step_token = NODE_AUTH_TOKEN_SECRET_PATTERN.search(step)
                    composite_input = COMPOSITE_ACTION_TOKEN_INPUT_PATTERN.search(step)
                    if step_token or (
                        local_composite_action
                        and composite_input
                        and local_composite_action_uses_node_auth_token(
                            repo_dir,
                            LOCAL_COMPOSITE_ACTION_PATTERN.match(
                                step.splitlines()[0]
                            ).group("path"),
                        )
                    ):
                        continue
                    result.manual_review(
                        f"{workflow.relative_to(repo_dir)}: npm/pnpm/yarn mangler NODE_AUTH_TOKEN"
                    )


SOURCE_SUFFIXES = (".js", ".jsx", ".ts", ".tsx")
LEGACY_REMOTE_LOGGING_PACKAGE = "loglevel-plugin-remote"
FRONTEND_LOGGER_ENDPOINT = "/api/frontendLogger"
RELATIVE_IMPORT_PATTERN = re.compile(
    r"""^\s*import\b[^;]*?\bfrom\s+["'](?P<spec>\.{1,2}/[^"']+)["'];?\s*$"""
)
EXPORTED_FUNCTION_PATTERN = re.compile(
    r"\bexport\s+(?:default\s+)?(?:async\s+)?function\s+(\w+)"
)


def is_test_source(path: Path) -> bool:
    return (
        ".test." in path.name
        or ".spec." in path.name
        or "__tests__" in path.parts
        or "/src/test/" in path.as_posix()
    )


def source_files(directory: Path, suffixes: tuple[str, ...] = SOURCE_SUFFIXES) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.rglob("*")
        if path.suffix in suffixes and path.is_file() and not is_ignored(path)
    )


def existing_apm_initialization(source_dir: Path) -> bool:
    for path in source_files(source_dir):
        if is_test_source(path):
            continue
        content = path.read_text(errors="ignore")
        if "@nais/apm" in content and re.search(r"\binit\(", content):
            return True
    return False


def import_resolves_to(importer: Path, spec: str, module: Path) -> bool:
    target = (importer.parent / spec).resolve()
    resolved_module = module.resolve()
    return target in {resolved_module, resolved_module.with_suffix("")}


def remove_legacy_frontend_logging(
    package_path: Path,
    apply: bool,
    result: Result,
) -> tuple[bool, bool]:
    """Fjern loglevel-plugin-remote-oppsett. Returnerer (package endret, ingen gammel logging igjen)."""
    source_dir = package_path.parent / "src"
    sources = source_files(source_dir)
    legacy_modules = [
        path
        for path in sources
        if not is_test_source(path)
        and re.search(
            rf"""["']{re.escape(LEGACY_REMOTE_LOGGING_PACKAGE)}["']""",
            path.read_text(errors="ignore"),
        )
    ]
    if not legacy_modules:
        return False, not any(
            FRONTEND_LOGGER_ENDPOINT in path.read_text(errors="ignore") for path in sources
        )

    deletions: list[Path] = []
    edits: dict[Path, str] = {}
    for module in legacy_modules:
        names = EXPORTED_FUNCTION_PATTERN.findall(module.read_text(errors="ignore"))
        if not names:
            result.manual_review(f"{module}: fant ikke eksportert funksjon i gammel frontend-logging")
            return False, False
        deletions.append(module)
        for suffix in SOURCE_SUFFIXES:
            for kind in ("test", "spec"):
                sibling = module.with_name(f"{module.stem}.{kind}{suffix}")
                if sibling.is_file():
                    deletions.append(sibling)

        call_pattern = re.compile(
            rf"^\s*(?:await\s+)?(?:{'|'.join(map(re.escape, names))})\(\)\s*;?\s*$"
        )
        name_pattern = re.compile(rf"\b(?:{'|'.join(map(re.escape, names))})\b")
        for importer in sources:
            if importer in legacy_modules or importer in deletions:
                continue
            content = edits.get(importer, importer.read_text(errors="ignore"))
            lines = content.splitlines(keepends=True)
            import_indexes = {
                index
                for index, line in enumerate(lines)
                if (match := RELATIVE_IMPORT_PATTERN.match(line.rstrip("\n")))
                and import_resolves_to(importer, match.group("spec"), module)
            }
            if not import_indexes:
                continue
            if is_test_source(importer):
                result.manual_review(f"{importer}: test bruker gammel frontend-logging")
                return False, False
            updated = "".join(
                line
                for index, line in enumerate(lines)
                if index not in import_indexes and not call_pattern.match(line.rstrip("\n"))
            )
            if name_pattern.search(updated):
                result.manual_review(
                    f"{importer}: fjern bruk av {', '.join(names)} manuelt"
                )
                return False, False
            edits[importer] = updated

    for path in sources:
        if path in deletions:
            continue
        content = edits.get(path, path.read_text(errors="ignore"))
        if LEGACY_REMOTE_LOGGING_PACKAGE in content or FRONTEND_LOGGER_ENDPOINT in content:
            result.manual_review(f"{path}: bruker fortsatt gammel frontend-logging")
            return False, False

    for module in legacy_modules:
        result.needs_changes(f"{module}: fjern gammel frontend-logging (erstattes av @nais/apm)")
    for importer in edits:
        result.needs_changes(f"{importer}: fjern kall til gammel frontend-logging")

    package = read_json(package_path)
    package_changed = False
    for section in ("dependencies", "devDependencies"):
        dependencies = package.get(section)
        if isinstance(dependencies, dict) and LEGACY_REMOTE_LOGGING_PACKAGE in dependencies:
            del dependencies[LEGACY_REMOTE_LOGGING_PACKAGE]
            package_changed = True
    if package_changed:
        result.needs_changes(f"{package_path}: fjern {LEGACY_REMOTE_LOGGING_PACKAGE}")

    if apply:
        for path, content in edits.items():
            path.write_text(content)
        for path in deletions:
            path.unlink()
        if package_changed:
            package_path.write_text(
                json.dumps(package, ensure_ascii=False, indent=detect_indent(package_path))
                + "\n"
            )
    return package_changed, True


def backend_sources(repo_dir: Path, test: bool) -> list[Path]:
    return [
        path
        for path in source_files(repo_dir, (".kt", ".java"))
        if ("/src/test/" in path.as_posix()) == test
    ]


def remove_frontend_logger_endpoint(
    repo_dir: Path,
    frontend_ready: bool,
    apply: bool,
    result: Result,
) -> None:
    main_sources = backend_sources(repo_dir, test=False)
    controllers = [
        path
        for path in main_sources
        if FRONTEND_LOGGER_ENDPOINT in (content := path.read_text(errors="ignore"))
        and re.search(r"@(?:Post|Request)Mapping", content)
    ]
    if not controllers:
        return
    if not frontend_ready:
        for controller in controllers:
            result.manual_review(
                f"{controller.relative_to(repo_dir)}: fjern {FRONTEND_LOGGER_ENDPOINT} "
                "når frontend ikke lenger sender logger dit"
            )
        return

    deletions: list[Path] = []
    for controller in controllers:
        class_names = re.findall(
            r"\b(?:data\s+|enum\s+)?(?:class|object|interface|record)\s+(\w+)",
            controller.read_text(errors="ignore"),
        )
        if not class_names:
            result.manual_review(f"{controller.relative_to(repo_dir)}: fant ikke klasse")
            return
        name_pattern = re.compile(rf"\b(?:{'|'.join(map(re.escape, class_names))})\b")
        for path in main_sources:
            if path not in controllers and name_pattern.search(path.read_text(errors="ignore")):
                result.manual_review(
                    f"{path.relative_to(repo_dir)}: bruker {controller.stem}; fjern manuelt"
                )
                return
        for path in backend_sources(repo_dir, test=True):
            if any(path.stem.startswith(name) for name in class_names):
                deletions.append(path)
            elif name_pattern.search(path.read_text(errors="ignore")):
                result.manual_review(
                    f"{path.relative_to(repo_dir)}: test bruker {controller.stem}; fjern manuelt"
                )
                return
        deletions.append(controller)
        result.needs_changes(
            f"{controller.relative_to(repo_dir)}: fjern ubeskyttet {FRONTEND_LOGGER_ENDPOINT} "
            "(erstattes av @nais/apm)"
        )

    for path in sorted(set(deletions) - set(controllers)):
        result.needs_changes(f"{path.relative_to(repo_dir)}: fjern test for {FRONTEND_LOGGER_ENDPOINT}")
    for path in source_files(repo_dir, (".md", ".json", ".yml", ".yaml", ".kt", ".java")):
        if path in deletions or ".github" in path.parts:
            continue
        if "frontendLogger" in path.read_text(errors="ignore"):
            result.note(
                f"{path.relative_to(repo_dir)}: nevner {FRONTEND_LOGGER_ENDPOINT}; oppdater teksten"
            )
    if apply:
        for path in deletions:
            path.unlink()


def error_response_trace_candidates(repo_dir: Path) -> list[str]:
    candidates: list[str] = []
    for path in backend_sources(repo_dir, test=False):
        content = path.read_text(errors="ignore")
        if not re.search(r"\bclass\s+\w*(?:Feil|Error|Problem)\w*", content):
            continue
        relative = path.relative_to(repo_dir)
        if re.search(r"""MDC\.get\(\s*["']traceId["']\s*\)""", content):
            candidates.append(
                f"{relative}: MDC traceId er tom uten Micrometer Tracing-autokonfigurasjon; "
                "bruk Span.current() fra Nais-agenten"
            )
        if re.search(r"\bval\s+callId\b(?![^\n]*Span\.current\(\))", content):
            candidates.append(f"{relative}: feilsvar bruker callId; teamstandard er traceId")
    return candidates


ALERTS_FILENAME = "alerts.yaml"
ALERT_SLACK_CHANNELS = {
    "infotek": "#infotek-sheriff",
    "historisk": "#infotek-sheriff",
}
PROMETHEUS_RULE_PATTERN = re.compile(r"(?m)^kind:\s*[\"']?PrometheusRule[\"']?\s*$")
NAIS_ALERT_PATTERN = re.compile(r"(?m)^kind:\s*[\"']?Alert[\"']?\s*$")
NAIS_ALERT_API_PATTERN = re.compile(r"(?m)^apiVersion:\s*[\"']?nais\.io/")
TEMPLATE_PATTERN = re.compile(r"\{\{\s*([\w.-]+)\s*\}\}")
DEPLOY_ACTION_PATTERN = re.compile(r"(?m)^\s*(?:-\s+)?uses:\s*nais/deploy/actions/deploy@")
CLUSTER_PATTERN = re.compile(r"(?m)^\s*CLUSTER:\s*[\"']?(?P<cluster>[\w-]+)[\"']?\s*(?:#.*)?$")
RESOURCE_PATTERN = re.compile(
    r"(?m)^\s*RESOURCE:\s*(?P<quote>[\"']?)(?P<value>[^\"'#\n]+?)(?P=quote)\s*(?:#.*)?$"
)


def repository_yaml_files(repo_dir: Path) -> list[Path]:
    return [
        path
        for path in source_files(repo_dir, (".yml", ".yaml"))
        if ".github" not in path.parts
    ]


def template_variables(manifest: Path, repo_dir: Path) -> dict[str, object]:
    candidates: list[Path] = []
    for directory in (manifest.parent, manifest.parent.parent):
        if directory == repo_dir.parent or repo_dir not in (directory, *directory.parents):
            continue
        candidates.extend(
            path
            for path in sorted(directory.glob("*.json"))
            if re.search(r"prod|dev|vars", path.name)
        )
    candidates.sort(key=lambda path: "prod" not in path.name)
    for path in candidates:
        try:
            return read_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return {}


def render_template(value: str, variables: dict[str, object]) -> str | None:
    missing = False

    def replace(match: re.Match[str]) -> str:
        nonlocal missing
        current: object = variables
        for part in match.group(1).split("."):
            if not isinstance(current, dict) or part not in current:
                missing = True
                return ""
            current = current[part]
        return str(current)

    rendered = TEMPLATE_PATTERN.sub(replace, value)
    return None if missing else rendered


def application_name(manifest: Path, repo_dir: Path) -> str | None:
    in_metadata = False
    for line in manifest.read_text(errors="ignore").splitlines():
        if re.match(r"^metadata:\s*$", line):
            in_metadata = True
            continue
        if in_metadata and re.match(r"^\S", line):
            break
        match = re.match(r"^  name:\s*(.+?)\s*$", line) if in_metadata else None
        if match:
            name = parse_scalar(match.group(1))
            if "{{" in name:
                return render_template(name, template_variables(manifest, repo_dir))
            return name
    return None


def manifest_has_spring_metrics(content: str) -> bool:
    return bool(
        re.search(r"(?m)^  prometheus:\s*$", content)
        and re.search(r"(?m)^    path:\s*[\"']?/actuator/prometheus", content)
    )


def alert_rules(app: str, namespace: str, spring_metrics: bool) -> list[str]:
    selector = f'namespace="{namespace}", app="{app}"'
    rules = [
        "        - alert: ApplikasjonNede\n"
        f'          expr: kube_deployment_status_replicas_available{{namespace="{namespace}", deployment="{app}"}} == 0\n'
        "          for: 5m\n"
        "          annotations:\n"
        f'            summary: "{app} har ingen tilgjengelige pods"\n'
        '            consequence: "Appen er utilgjengelig for brukerne."\n'
        f'            action: "Sjekk `kubectl describe pod -l app={app} -n {namespace}` og loggene i Grafana."\n'
        "          labels:\n"
        f"            namespace: {namespace}\n"
        "            severity: critical\n",
        "        - alert: MangeRestarter\n"
        f'          expr: sum(increase(kube_pod_container_status_restarts_total{{namespace="{namespace}", container="{app}"}}[30m])) > 3\n'
        "          for: 5m\n"
        "          annotations:\n"
        f'            summary: "{app} har startet på nytt mer enn tre ganger siste 30 minutter"\n'
        '            consequence: "Appen kan være ustabil eller gå tom for minne."\n'
        f'            action: "Sjekk `kubectl get events -n {namespace}` og loggene fra forrige pod."\n'
        "          labels:\n"
        f"            namespace: {namespace}\n"
        "            severity: warning\n",
    ]
    if spring_metrics:
        rules.extend(
            [
                "        - alert: HoyFeilrate\n"
                "          expr: |\n"
                f'            sum(rate(http_server_requests_seconds_count{{{selector}, status=~"5.."}}[5m]))\n'
                "            /\n"
                f"            sum(rate(http_server_requests_seconds_count{{{selector}}}[5m])) * 100 > 5\n"
                "          for: 10m\n"
                "          annotations:\n"
                f'            summary: "Mer enn 5 % av kallene til {app} feiler med 5xx"\n'
                '            consequence: "Brukerne får feil fra appen."\n'
                '            action: "Sjekk feillogger og traces i Grafana."\n'
                "          labels:\n"
                f"            namespace: {namespace}\n"
                "            severity: warning\n",
                "        - alert: MangeFeillogger\n"
                f'          expr: sum(increase(logback_events_total{{{selector}, level="error"}}[10m])) > 10\n'
                "          for: 5m\n"
                "          annotations:\n"
                f'            summary: "{app} har logget mer enn ti feil siste 10 minutter"\n'
                '            consequence: "Noe feiler gjentatte ganger i appen."\n'
                '            action: "Sjekk feilloggene i Grafana Loki."\n'
                "          labels:\n"
                f"            namespace: {namespace}\n"
                "            severity: warning\n",
            ]
        )
    return rules


def alerts_document(repository: Repository, apps: dict[str, bool]) -> str:
    groups = "".join(
        f"    - name: {app}\n      rules:\n"
        + "".join(alert_rules(app, repository.namespace, spring_metrics))
        for app, spring_metrics in sorted(apps.items())
    )
    return (
        "apiVersion: monitoring.coreos.com/v1\n"
        "kind: PrometheusRule\n"
        "metadata:\n"
        f"  name: {repository.name}-alerts\n"
        f"  namespace: {repository.namespace}\n"
        "  labels:\n"
        f"    team: {repository.namespace}\n"
        "spec:\n"
        "  groups:\n"
        f"{groups}"
    )


def alerts_directory(manifest: Path) -> Path:
    if manifest.parent.name in {"app", "dev", "prod"}:
        return manifest.parent.parent
    return manifest.parent


def ensure_alerts(
    repository: Repository,
    repo_dir: Path,
    java: bool,
    apply: bool,
    result: Result,
) -> None:
    manifests = nais_manifests(repo_dir)
    if not manifests:
        return

    existing: list[Path] = []
    for path in repository_yaml_files(repo_dir):
        content = path.read_text(errors="ignore")
        if PROMETHEUS_RULE_PATTERN.search(content):
            existing.append(path)
        elif NAIS_ALERT_PATTERN.search(content) and NAIS_ALERT_API_PATTERN.search(content):
            result.manual_review(
                f"{path.relative_to(repo_dir)}: migrer nais.io Alert til PrometheusRule"
            )

    if existing:
        alerts_path = existing[0]
    else:
        apps: dict[str, bool] = {}
        for manifest in manifests:
            name = application_name(manifest, repo_dir)
            if not name:
                result.manual_review(
                    f"{manifest.relative_to(repo_dir)}: fant ikke appnavn for varsler"
                )
                continue
            spring_metrics = java and manifest_has_spring_metrics(manifest.read_text())
            apps[name] = apps.get(name, False) or spring_metrics
        if not apps:
            return
        alerts_path = alerts_directory(manifests[0]) / ALERTS_FILENAME
        if alerts_path.exists():
            result.manual_review(
                f"{alerts_path.relative_to(repo_dir)}: finnes, men er ikke en PrometheusRule"
            )
            return
        result.needs_changes(
            f"{alerts_path.relative_to(repo_dir)}: opprett PrometheusRule med standardvarsler"
        )
        channel = ALERT_SLACK_CHANNELS.get(repository.namespace)
        if channel:
            result.note(
                f"Nais Console: kontroller at varsler for {repository.namespace} går til {channel}"
            )
        if apply:
            alerts_path.write_text(alerts_document(repository, apps))

    ensure_alert_deploy(repository, repo_dir, alerts_path, apply, result)


def ensure_alert_deploy(
    repository: Repository,
    repo_dir: Path,
    alerts_path: Path,
    apply: bool,
    result: Result,
) -> None:
    relative = alerts_path.relative_to(repo_dir).as_posix()
    workflows_dir = repo_dir / ".github" / "workflows"
    workflows = sorted(
        path for pattern in ("*.yml", "*.yaml") for path in workflows_dir.glob(pattern)
    )
    has_prod = any(environment.startswith("prod-") for environment in repository.environments)
    target_prefix = "prod-" if has_prod else "dev-"

    target_steps: list[tuple[Path, str, str, re.Match[str]]] = []
    for workflow in workflows:
        for job in job_blocks(workflow.read_text(errors="ignore")):
            for step in step_blocks(job):
                cluster = CLUSTER_PATTERN.search(step)
                resource = RESOURCE_PATTERN.search(step)
                if (
                    DEPLOY_ACTION_PATTERN.search(step)
                    and cluster
                    and resource
                    and cluster.group("cluster").startswith(target_prefix)
                ):
                    target_steps.append((workflow, cluster.group("cluster"), step, resource))

    if not target_steps:
        result.manual_review(
            f"fant ikke {target_prefix}deploy med RESOURCE; legg {relative} til deploy manuelt"
        )
        return

    covered = {
        (workflow, cluster)
        for workflow, cluster, _, resource in target_steps
        if relative in (item.strip() for item in resource.group("value").split(","))
    }
    for workflow, cluster, step, resource in target_steps:
        if (workflow, cluster) in covered:
            continue
        covered.add((workflow, cluster))
        result.needs_changes(
            f"{workflow.relative_to(repo_dir)}: deploy {relative} til {cluster}"
        )
        if apply:
            updated_step = (
                step[: resource.end("value")] + f",{relative}" + step[resource.end("value"):]
            )
            content = workflow.read_text()
            workflow.write_text(content.replace(step, updated_step, 1))


def find_entrypoint(frontend_dir: Path) -> Path | None:
    for relative_path in ENTRYPOINTS:
        candidate = frontend_dir / relative_path
        if candidate.is_file():
            return candidate
    return None


def observability_module(app: str, namespace: str) -> str:
    return (
        'import { init } from "@nais/apm";\n\n'
        "export function initializeObservability() {\n"
        "    // app og namespace kan ikke løses fra meta-tags eller build-time env her:\n"
        "    // BFF-en server statisk index.html uten SSR-templating, og\n"
        "    // nais.yaml har ikke spec.frontend.generatedConfig. Uten dette\n"
        '    // faller init() tilbake til "unknown-app" og "unknown-team". Begge er\n'
        "    // stabile på tvers av miljø, så de er trygge å hardkode.\n"
        f'    init({{ app: "{app}", namespace: "{namespace}", tracing: true }});\n'
        "}\n"
    )


def observability_test(app: str, namespace: str) -> str:
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
        "    expect(init).toHaveBeenCalledWith({\n"
        f'        app: "{app}",\n'
        f'        namespace: "{namespace}",\n'
        "        tracing: true,\n"
        "    });\n"
        "});\n"
    )


LEGACY_INIT_PATTERN = re.compile(
    r"""(?P<prefix>(?:\binit|toHaveBeenCalledWith)\(\{\s*)"""
    r"""(?P<rest>namespace:\s*["'][\w-]+["'],\s*tracing:\s*true\s*\}\))"""
)


def add_app_to_legacy_init(content: str, app: str) -> str:
    return LEGACY_INIT_PATTERN.sub(
        lambda match: f'{match["prefix"]}app: "{app}", {match["rest"]}', content
    )


def frontend_app_name(repo_dir: Path) -> str | None:
    names = {
        name
        for manifest in nais_manifests(repo_dir)
        if (name := application_name(manifest, repo_dir))
    }
    frontend_names = {name for name in names if "frontend" in name}
    if len(frontend_names) == 1:
        return frontend_names.pop()
    if len(names) == 1:
        return names.pop()
    return None


def ensure_frontend_initialization(
    package_path: Path,
    repository: Repository,
    apply: bool,
    result: Result,
    app: str | None = None,
) -> bool:
    app = app or repository.name
    frontend_dir = package_path.parent
    entrypoint = find_entrypoint(frontend_dir)
    if entrypoint is None:
        result.manual_review(f"{frontend_dir}: fant ikke støttet frontend-entrypoint")
        return False

    source_dir = entrypoint.parent
    module_path = source_dir / "observability.ts"
    test_path = source_dir / "observability.test.ts"
    changed = False

    expected_module = observability_module(app, repository.namespace)
    if not module_path.is_file():
        if existing_apm_initialization(source_dir):
            return False
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
        if "namespace:" not in module_content:
            result.manual_review(
                f"{module_path}: mangler namespace i init() — se manuell fiks i chore/observability"
            )
        elif "app:" not in module_content:
            if LEGACY_INIT_PATTERN.search(module_content):
                result.needs_changes(f"{module_path}: legg til app i init()")
                changed = True
                if apply:
                    module_path.write_text(add_app_to_legacy_init(module_content, app))
            else:
                result.manual_review(f"{module_path}: mangler app i init()")

    if not test_path.is_file():
        result.needs_changes(f"{test_path}: legg til initialiseringstest")
        changed = True
        if apply:
            test_path.write_text(observability_test(app, repository.namespace))
    elif LEGACY_INIT_PATTERN.search(test_content := test_path.read_text()):
        result.needs_changes(f"{test_path}: forvent app i init()")
        changed = True
        if apply:
            test_path.write_text(add_app_to_legacy_init(test_content, app))

    if not test_path.is_file() or re.search(
        r"""from\s+["']vitest["']""", test_path.read_text()
    ):
        changed = ensure_vitest_dependency(package_path, apply, result) or changed

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
    skip_alerts: bool = False,
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
        git_command = f"git -C {shlex.quote(str(repo_dir))}"
        if branch == "detached":
            result.warnings.append(
                f"{repo_dir}: detached HEAD; bytt først til {repository.default_branch} "
                "og kontroller status før du oppretter en feature-branch. "
                f"Kjør: {git_command} switch {shlex.quote(repository.default_branch)}"
            )
        else:
            result.warnings.append(
                f"{repo_dir}: står på default-branchen {repository.default_branch}; "
                "opprett en feature-branch i dette underrepoet før --apply. "
                f"Kjør: {git_command} switch -c chore/observability"
            )
        return result

    packages = frontend_packages(repo_dir)
    changed_packages: list[Path] = []
    frontend_ready = not packages
    if packages and repository.has_gcp and repository.frontend_observability:
        frontend_ready = True
        for package_path in packages:
            dependency_changed = ensure_apm_dependency(package_path, apply, result)
            config_changed = ensure_npmrc(package_path.parent, apply, result)
            ensure_workflow_node_auth_token(package_path.parent, repo_dir, result)
            legacy_changed, legacy_removed = remove_legacy_frontend_logging(
                package_path, apply, result
            )
            frontend_ready = frontend_ready and legacy_removed
            source_changed = ensure_frontend_initialization(
                package_path, repository, apply, result, frontend_app_name(repo_dir)
            )
            if dependency_changed or config_changed or legacy_changed or source_changed:
                changed_packages.append(package_path)
    elif packages and not repository.frontend_observability:
        result.warnings.append("frontend-observability er eksplisitt deaktivert")
    elif packages and not repository.has_gcp:
        result.warnings.append("FSS-frontend ignoreres")

    java = java_repository(repo_dir)
    for manifest in nais_manifests(repo_dir):
        update_manifest(manifest, apply, java, result)

    remove_frontend_logger_endpoint(repo_dir, frontend_ready, apply, result)
    if not skip_alerts:
        ensure_alerts(repository, repo_dir, java, apply, result)

    for candidate in error_response_trace_candidates(repo_dir):
        result.manual_review(candidate)
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
    parser.add_argument(
        "--skip-alerts",
        action="store_true",
        help="hopp over sjekk og oppretting av PrometheusRule-varsler",
    )
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
        process_repository(
            repository,
            args.apply,
            args.update_lockfiles,
            skip_alerts=args.skip_alerts,
        )
        for repository in repositories
    ]
    for result in results:
        print_result(result, args.json)

    return 1 if any(result.status == "blocked" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
