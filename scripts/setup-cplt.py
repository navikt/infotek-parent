#!/usr/bin/env python3
from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
from pathlib import Path


MACHINE_CONFIG = (
    ("allow.read", Path.home() / ".m2/settings.xml"),
    ("allow.read", Path.home() / ".npmrc"),
    ("sandbox.allow_cache_exec", "ms-playwright"),
    ("sandbox.allow_cache_exec", "pnpm/dlx"),
)


def run_cplt(*args: str | Path) -> None:
    subprocess.run(["cplt", *(str(arg) for arg in args)], check=True)


def configure_cplt() -> None:
    for key, value in MACHINE_CONFIG:
        run_cplt("config", "set", key, value)
    run_cplt("config", "validate")


def confirm(question: str) -> bool:
    try:
        return input(f"{question} [j/N] ").strip().lower() == "j"
    except EOFError:
        return False


def configure_repo_trust() -> None:
    print("\n→ Kontrollerer forslagene i .cplt.toml...")
    run_cplt("trust", "show")

    if confirm("Godkjenn JVM attach for Mockito/MockK?"):
        run_cplt("trust", "accept", "allow_jvm_attach")

    if platform.system() == "Linux":
        print(
            "ADVARSEL: allow_localhost_any deaktiverer Landlock sin "
            "TCP connect-filtrering på Linux."
        )
    if confirm("Godkjenn dynamiske localhost-porter for test- og byggeverktøy?"):
        run_cplt("trust", "accept", "allow_localhost_any")

    print(
        "ADVARSEL: Docker-socketen er i praksis root-tilgang til vertsmaskinen. "
        "Containere kan omgå cplt-sandboxen."
    )
    if confirm("Godkjenn Docker Compose og Testcontainers?"):
        run_cplt("trust", "accept", "allow_docker")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Konfigurer cplt for Infoteks Maven- og pnpm-prosjekter."
    )
    parser.add_argument("--skip-shell-install", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--skip-doctor", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--skip-trust", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if shutil.which("cplt") is None:
        parser.error("cplt er ikke installert. Kjør 'brew install navikt/tap/cplt'.")

    print("→ Setter maskinspesifikk cplt-konfigurasjon...")
    configure_cplt()

    if not args.skip_shell_install:
        run_cplt("--shell-install")
    if not args.skip_doctor:
        run_cplt("doctor")
    if not args.skip_trust:
        configure_repo_trust()

    print("✓ cplt er konfigurert for Maven, pnpm og Playwright")
    if not args.skip_shell_install:
        print("Restart shellen hvis cplt oppdaterte shell-integrasjonen.")


if __name__ == "__main__":
    main()
