"""npm/pnpm-delen av oppsettet for GitHub Packages. Kjøres via setup_github_packages."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ZSHRC_MARKER_START = "# --- infotek NODE_AUTH_TOKEN ---"
ZSHRC_MARKER_END = "# --- slutt infotek NODE_AUTH_TOKEN ---"
ZSHRC_BLOCK = (
    f"{ZSHRC_MARKER_START}\n"
    'export NODE_AUTH_TOKEN="$(gh auth token)"\n'
    f"{ZSHRC_MARKER_END}\n"
)
NPMRC_REGISTRY_KEY = "@navikt:registry"
NPMRC_REGISTRY_LINE = f"{NPMRC_REGISTRY_KEY}=https://npm.pkg.github.com/"
NPMRC_NAIS_REGISTRY_KEY = "@nais:registry"
NPMRC_NAIS_REGISTRY_LINE = (
    f"{NPMRC_NAIS_REGISTRY_KEY}=https://npm.pkg.github.com/"
)
NPMRC_AUTH_KEY = "//npm.pkg.github.com/:_authToken"
NPMRC_AUTH_LINE = f"{NPMRC_AUTH_KEY}=${{NODE_AUTH_TOKEN}}"


class SetupError(RuntimeError):
    pass


def validate_gh() -> None:
    if shutil.which("gh") is None:
        raise SetupError("Fant ikke gh. Installer GitHub CLI og kjør gh auth login.")

    status = subprocess.run(
        ["gh", "auth", "status"],
        text=True,
        capture_output=True,
        check=False,
    )
    if status.returncode != 0:
        raise SetupError("GitHub CLI er ikke logget inn. Kjør gh auth login.")

    scopes = subprocess.run(
        ["gh", "api", "-i", "/user"],
        text=True,
        capture_output=True,
        check=False,
    )
    scope_match = re.search(
        r"(?im)^x-oauth-scopes:\s*(?P<scopes>.*)$",
        scopes.stdout,
    )
    if (
        scopes.returncode != 0
        or scope_match is None
        or "read:packages"
        not in {
            scope.strip()
            for scope in scope_match.group("scopes").split(",")
        }
    ):
        raise SetupError(
            "GitHub CLI-tokenet mangler read:packages. Kjør "
            "gh auth refresh -h github.com -s read:packages i en vanlig terminal."
        )

    token = subprocess.run(
        ["gh", "auth", "token"],
        text=True,
        capture_output=True,
        check=False,
    )
    if token.returncode != 0 or not token.stdout.strip():
        raise SetupError(
            "GitHub CLI kunne ikke hente token. Kontroller innloggingen med gh auth status."
        )


def replace_marked_block(content: str) -> str:
    start_count = len(
        re.findall(rf"(?m)^{re.escape(ZSHRC_MARKER_START)}$", content)
    )
    end_count = len(
        re.findall(rf"(?m)^{re.escape(ZSHRC_MARKER_END)}$", content)
    )
    if start_count != end_count or start_count > 1:
        raise SetupError(
            "Fant ubalanserte NODE_AUTH_TOKEN-markører i .zshrc. "
            "Rett markørblokken manuelt før du prøver igjen."
        )
    pattern = re.compile(
        rf"(?ms)^{re.escape(ZSHRC_MARKER_START)}$.*?"
        rf"^{re.escape(ZSHRC_MARKER_END)}$\n?",
    )
    if pattern.search(content):
        return pattern.sub(ZSHRC_BLOCK, content)
    separator = "" if not content or content.endswith("\n") else "\n"
    blank_line = "\n" if content else ""
    return f"{content}{separator}{blank_line}{ZSHRC_BLOCK}"


def update_npmrc_content(content: str) -> str:
    lines = content.splitlines()
    replacements = {
        NPMRC_REGISTRY_KEY: NPMRC_REGISTRY_LINE,
        NPMRC_NAIS_REGISTRY_KEY: NPMRC_NAIS_REGISTRY_LINE,
        NPMRC_AUTH_KEY: NPMRC_AUTH_LINE,
    }
    found: set[str] = set()
    updated: list[str] = []

    for line in lines:
        stripped = line.strip()
        key = next(
            (
                candidate
                for candidate in replacements
                if re.match(rf"^{re.escape(candidate)}\s*=", stripped)
            ),
            None,
        )
        if key is None or stripped.startswith("#"):
            updated.append(line)
            continue
        if key not in found:
            updated.append(replacements[key])
            found.add(key)

    for key, line in replacements.items():
        if key not in found:
            updated.append(line)

    return "\n".join(updated) + "\n"


def atomic_write(path: Path, content: str) -> None:
    if path.is_symlink():
        path = path.resolve(strict=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = path.stat().st_mode if path.exists() else None
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w") as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        if existing_mode is not None:
            os.chmod(temporary_path, existing_mode)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def configure(home: Path, dry_run: bool = False) -> list[Path]:
    zshrc = home / ".zshrc"
    npmrc = home / ".npmrc"
    updates = {
        zshrc: replace_marked_block(zshrc.read_text() if zshrc.exists() else ""),
        npmrc: update_npmrc_content(npmrc.read_text() if npmrc.exists() else ""),
    }
    changed = [
        path
        for path, content in updates.items()
        if not path.exists() or path.read_text() != content
    ]
    if not dry_run:
        for path in changed:
            atomic_write(path, updates[path])
    return changed
