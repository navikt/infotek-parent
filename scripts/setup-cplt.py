#!/usr/bin/env python3
from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path


MACHINE_CONFIG = (
    ("allow.read", Path.home() / ".m2/settings.xml"),
    ("allow.read", Path.home() / ".npmrc"),
    ("sandbox.allow_cache_exec", "ms-playwright"),
    ("sandbox.allow_cache_exec", "pnpm/dlx"),
)


def run_cplt(*args: str | Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["cplt", *(str(arg) for arg in args)],
        check=False,
        text=True,
        capture_output=True,
    )

    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)

    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, ["cplt", *map(str, args)])

    return result


def configure_cplt() -> None:
    for key, value in MACHINE_CONFIG:
        run_cplt("config", "set", key, value)
    run_cplt("config", "validate")


def confirm(question: str) -> bool:
    try:
        return input(f"{question} [j/N] ").strip().lower() == "j"
    except EOFError:
        return False


def print_doctor_guidance() -> None:
    print("\n⚠️  cplt doctor rapporterte blockerende problemer i dette miljøet.")
    print("Fiks disse før du fortsetter med agenten:")
    print("  - Installer Node/npm inni WSL, ikke via Windows interop: ")
    print("      sudo apt-get update && sudo apt-get install -y nodejs npm")
    print("    eller bruk nvm for en Linux-installasjon av Node.")
    print("  - Logg inn i GitHub CLI i WSL: gh auth login")
    print("  - Opprett ~/.m2/settings.xml og ~/.npmrc om de mangler, eller kjør")
    print("    python3 scripts/merge-npmrc.py platform/npm/.npmrc ~/.npmrc")
    print("    og legg inn GitHub Packages-tokenet i ~/.m2/settings.xml")
    print("  - Deretter kan du kjøre: python3 scripts/setup-cplt.py --skip-doctor")


def configure_repo_trust() -> None:
    print("\n→ Kontrollerer forslagene i .cplt.toml...")
    run_cplt("trust", "show")

    print(
        "\n[1/3] allow_jvm_attach: tillater JVM attach API for Mockito/MockK og lignende "
        "verktøy. Dette gjør at en agent kan koble til andre Java-prosesser som "
        "kjører lokalt. Godkjenn bare på en maskin du stoler på."
    )
    if confirm("Godkjenn JVM attach for Mockito/MockK?"):
        run_cplt("trust", "accept", "allow_jvm_attach")

    if platform.system() == "Linux":
        print(
            "\n[2/3] allow_localhost_any: tillater direkte TCP-forbindelser til "
            "lokale og eksterne porter. På Linux deaktiveres Landlock sin "
            "TCP connect-filtrering når denne godkjennes. Bruk dette bare hvis "
            "du vil at test-/byggeverktøy skal kunne nå lokale tjenester på "
            "dynamiske porter."
        )
    else:
        print(
            "\n[2/3] allow_localhost_any: tillater dynamiske localhost-porter for "
            "test- og byggeverktøy. Dette åpner TCP-connect til localhost/andre "
            "verter som verktøyet trenger for å teste eller kjøre lokalt."
        )
    if confirm("Godkjenn dynamiske localhost-porter for test- og byggeverktøy?"):
        run_cplt("trust", "accept", "allow_localhost_any")

    print(
        "\n[3/3] allow_docker: tillater Docker/Podman-daemonen. Dette er i praksis "
        "root-tilgang til vertsmaskinen, fordi containere kan montere eller lese "
        "vertens filer via Docker-socketen. Godkjenn kun hvis du aksepterer den "
        "risikoen på denne maskinen."
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
        result = run_cplt("doctor", check=False)
        if result.returncode != 0:
            print_doctor_guidance()
    if not args.skip_trust:
        configure_repo_trust()

    print("✓ cplt er konfigurert for Maven, pnpm og Playwright")
    if not args.skip_shell_install:
        print("Restart shellen hvis cplt oppdaterte shell-integrasjonen.")


if __name__ == "__main__":
    main()
