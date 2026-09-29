#!/usr/bin/env python3
"""Sett opp lokal tilgang til GitHub Packages for npm/pnpm og Maven."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable
from pathlib import Path
from xml.parsers import expat

from scripts import setup_maven_credentials as maven
from scripts import setup_node_package_token as node
from scripts.setup_node_package_token import SetupError

NPMRC_REFERENCE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*\}$")
MAVEN_REFERENCE = re.compile(r"^\$\{env\.[A-Za-z_][A-Za-z0-9_]*\}$")
MAVEN_PROPERTY_REFERENCE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_.]*\}$")
MAVEN_ENCRYPTED = re.compile(r"^\{.+\}$")
SHELL_REFERENCE = re.compile(r"""^["']?\$""")
NPMRC_AUTH_LINE = re.compile(r"^\s*(//[^=\s]+?)/?:_authToken\s*=\s*(.*?)\s*$")
GITHUB_NPM_HOST = "//npm.pkg.github.com"
MANAGED_ZSHRC_BLOCKS = (
    (node.ZSHRC_MARKER_START, node.ZSHRC_MARKER_END),
    (maven.ZSHRC_START, maven.ZSHRC_END),
)


def npmrc_warnings(content: str) -> list[str]:
    warnings = []
    for line in content.splitlines():
        match = NPMRC_AUTH_LINE.match(line)
        if match is None or NPMRC_REFERENCE.match(match.group(2)):
            continue
        host = match.group(1)
        if host == GITHUB_NPM_HOST:
            warnings.append(
                "~/.npmrc hadde et token lagret direkte for npm.pkg.github.com. "
                "Linjen er byttet til ${NODE_AUTH_TOKEN}. Slett tokenet på "
                "github.com/settings/tokens hvis du ikke bruker det andre steder."
            )
        else:
            warnings.append(
                f"~/.npmrc har et token lagret direkte for {host}. "
                "Bytt verdien til en miljøvariabel, for eksempel ${NPM_TOKEN}."
            )
    return warnings


def zshrc_warnings(content: str) -> list[str]:
    for start, end in MANAGED_ZSHRC_BLOCKS:
        content = re.sub(
            rf"(?ms)^{re.escape(start)}$.*?^{re.escape(end)}$\n?", "", content
        )
    warnings = []
    for variable in ("NODE_AUTH_TOKEN", "MAVEN_PASSWORD"):
        for match in re.finditer(
            rf"(?m)^\s*export\s+{variable}\s*=\s*(\S*)", content
        ):
            if not SHELL_REFERENCE.match(match.group(1)):
                warnings.append(
                    f"~/.zshrc eksporterer {variable} med en verdi som ser ut som "
                    "et token. Fjern linjen og bruk den administrerte blokken "
                    "med gh auth token."
                )
                break
    return warnings


def github_server_credentials(data: bytes) -> dict[str, str]:
    parser = expat.ParserCreate(namespace_separator="}")
    stack: list[str] = []
    current: dict[str, str] = {}
    found: dict[str, str] = {}

    def start(name: str, _attributes: dict[str, str]) -> None:
        stack.append(name.rsplit("}", 1)[-1])
        if stack == ["settings", "servers", "server"]:
            current.clear()

    def characters(text: str) -> None:
        if len(stack) == 4 and stack[:3] == ["settings", "servers", "server"]:
            current[stack[3]] = current.get(stack[3], "") + text

    def end(_name: str) -> None:
        if stack == ["settings", "servers", "server"] and (
            current.get("id", "").strip() == "github"
        ):
            found.update({key: value.strip() for key, value in current.items()})
        stack.pop()

    def reject_doctype(*_args: object) -> None:
        raise SetupError("DOCTYPE støttes ikke i settings.xml.")

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = characters
    parser.StartDoctypeDeclHandler = reject_doctype
    try:
        parser.Parse(data, True)
    except expat.ExpatError as error:
        raise SetupError(f"Ugyldig XML i settings.xml (linje {error.lineno}).") from error
    return found


def maven_warnings(data: bytes) -> list[str]:
    credentials = github_server_credentials(data)
    warnings = []
    for field, variable in (("username", "MAVEN_USERNAME"), ("password", "MAVEN_PASSWORD")):
        value = credentials.get(field, "")
        if not value or MAVEN_REFERENCE.match(value):
            continue
        if field == "password" and MAVEN_ENCRYPTED.match(value):
            continue
        if MAVEN_PROPERTY_REFERENCE.match(value):
            warnings.append(
                f"github-serveren i ~/.m2/settings.xml bruker {value} i <{field}>. "
                "Maven leser bare miljøvariabler med env.-prefiks. "
                f"Bytt til ${{env.{variable}}}."
            )
        else:
            warnings.append(
                f"github-serveren i ~/.m2/settings.xml har <{field}> lagret direkte. "
                f"Bytt til ${{env.{variable}}}."
            )
    return warnings


def setup_node(home: Path) -> tuple[list[Path], list[str]]:
    node.validate_gh()
    npmrc = home / ".npmrc"
    warnings = npmrc_warnings(npmrc.read_text()) if npmrc.exists() else []
    changed = node.configure(home)
    if not changed:
        print("npm/pnpm: NODE_AUTH_TOKEN er allerede satt opp.")
    return changed, warnings


def setup_maven(home: Path) -> tuple[list[Path], list[str]]:
    changed = maven.configure(home)
    settings = home / ".m2" / "settings.xml"
    data = settings.read_bytes()
    warnings = maven_warnings(data)
    if settings not in changed:
        print("Maven: github-serveren finnes allerede i ~/.m2/settings.xml og er ikke endret.")
        credentials = github_server_credentials(data)
        if all(
            MAVEN_REFERENCE.match(credentials.get(field, ""))
            for field in ("username", "password")
        ):
            print("Maven: brukernavn og passord leses fra miljøvariabler.")
    return changed, warnings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        choices=("node", "maven"),
        help="sett bare opp npm/pnpm eller Maven",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    home = Path.home()
    steps: list[tuple[str, Callable[[], tuple[list[Path], list[str]]]]] = []
    if args.only in (None, "node"):
        steps.append(("npm/pnpm", lambda: setup_node(home)))
    if args.only in (None, "maven"):
        steps.append(("Maven", lambda: setup_maven(home)))

    failed = False
    warnings: list[str] = []
    changed: list[Path] = []
    for name, step in steps:
        try:
            step_changed, step_warnings = step()
        except (OSError, SetupError) as error:
            print(f"Feil ({name}): {error}", file=sys.stderr)
            failed = True
            continue
        changed.extend(step_changed)
        warnings.extend(step_warnings)

    zshrc = home / ".zshrc"
    if zshrc.exists():
        warnings.extend(zshrc_warnings(zshrc.read_text()))

    for path in dict.fromkeys(changed):
        print(f"Oppdaterte {path}")
    for warning in warnings:
        print(f"Advarsel: {warning}", file=sys.stderr)
    if zshrc in changed:
        print("Start et nytt shell eller kjør: source ~/.zshrc")
    if args.only in (None, "node"):
        print(
            "Hvis GitHub Packages avviser tokenet, kjør "
            "gh auth refresh -h github.com -s read:packages i en vanlig terminal."
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
