#!/usr/bin/env python3
"""
Setter opp NPM_TOKEN fra gh CLI og kobler den til Maven (~/.m2/settings.xml)
og npm/pnpm (~/.npmrc) for autentisering mot GitHub Packages (@navikt).

- Henter token dynamisk via `gh auth token` — selve verdien lagres ALDRI i
  .npmrc eller settings.xml, kun en referanse til miljøvariabelen NPM_TOKEN.
- Krever read:packages-scope på gh-innloggingen. Mangler scopet, avbrytes
  scriptet uten å endre noen filer.
- Idempotent: kjøres scriptet flere ganger, overskrives kun egne merkede
  seksjoner/elementer — resten av filene bevares.

Bruk:
    python3 scripts/setup-npm-maven-token.py [--dry-run]
"""
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ZSHRC = Path.home() / ".zshrc"
NPMRC = Path.home() / ".npmrc"
MAVEN_SETTINGS = Path.home() / ".m2" / "settings.xml"

ZSHRC_MARKER_START = "# --- infotek NPM_TOKEN (github packages) — lagt til av setup-npm-maven-token.py ---"
ZSHRC_MARKER_END = "# --- slutt infotek NPM_TOKEN ---"
ZSHRC_BLOCK = f'{ZSHRC_MARKER_START}\nexport NPM_TOKEN="$(gh auth token)"\n{ZSHRC_MARKER_END}\n'

NPMRC_REGISTRY_KEY = "@navikt:registry"
NPMRC_REGISTRY_VALUE = "https://npm.pkg.github.com/"
NPMRC_AUTH_KEY = "//npm.pkg.github.com/:_authToken"
NPMRC_AUTH_VALUE = "${NPM_TOKEN}"

MAVEN_SERVER_ID = "github"


def run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Kommando feilet: {' '.join(cmd)}\n{result.stderr.strip()}")
    return result.stdout.strip()


def check_gh_scope() -> None:
    """Verifiser at gh-innloggingen har read:packages-scope. Avbryter uten
    filendringer hvis den mangler."""
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        print("❌ Fant ikke `gh` — installer med `brew install gh` og kjør `gh auth login`.", file=sys.stderr)
        sys.exit(1)

    output = result.stdout + result.stderr
    if result.returncode != 0 or "Logged in" not in output:
        print("❌ Ikke logget inn i gh — kjør `gh auth login` først.", file=sys.stderr)
        sys.exit(1)

    if "read:packages" not in output:
        if "(GH_TOKEN)" in output:
            print(
                "❌ gh-innloggingen mangler scope 'read:packages', OG token kommer fra\n"
                "   miljøvariabelen GH_TOKEN (satt i shell-sesjonen, ikke i .zshrc — trolig\n"
                "   av cplt/Copilot CLI-sandboxen). `gh auth refresh` virker IKKE mens\n"
                "   GH_TOKEN er satt, siden gh da alltid bruker env-var-tokenet i stedet\n"
                "   for sin egen lagrede innlogging.\n\n"
                "   Fix — kjør i din vanlige terminal (ikke inne i copilot/cplt-sesjonen):\n\n"
                "   unset GH_TOKEN\n"
                "   gh auth refresh -h github.com -s read:packages\n"
                "   make setup-npm-maven-token\n\n"
                "   Hvis GH_TOKEN blir satt på nytt automatisk hver gang du åpner et nytt\n"
                "   shell, er det satt av et oppstartsverktøy (cplt-integrasjon e.l.) — sjekk\n"
                "   `python3 scripts/setup-cplt.py`-konfigurasjonen eller spør i teamet.\n",
                file=sys.stderr,
            )
        else:
            print(
                "❌ gh-innloggingen mangler scope 'read:packages'.\n"
                "   Kjør denne kommandoen og prøv igjen:\n\n"
                "   gh auth refresh -h github.com -s read:packages\n",
                file=sys.stderr,
            )
        sys.exit(1)


def get_github_username() -> str:
    return run(["gh", "api", "user", "--jq", ".login"])


def backup(path: Path, dry_run: bool) -> None:
    if not path.exists():
        return
    bak = path.with_suffix(path.suffix + ".bak")
    if dry_run:
        print(f"  [dry-run] ville tatt backup: {path} → {bak}")
        return
    shutil.copy2(path, bak)
    print(f"  ✓ Backup: {bak}")


def update_zshrc(dry_run: bool) -> None:
    print(f"→ Oppdaterer {ZSHRC}")
    backup(ZSHRC, dry_run)

    existing = ZSHRC.read_text() if ZSHRC.exists() else ""
    pattern = re.compile(
        re.escape(ZSHRC_MARKER_START) + r".*?" + re.escape(ZSHRC_MARKER_END) + r"\n?",
        re.DOTALL,
    )

    if pattern.search(existing):
        new_content = pattern.sub(ZSHRC_BLOCK, existing)
    else:
        separator = "\n" if existing and not existing.endswith("\n") else ""
        new_content = existing + separator + ("\n" if existing else "") + ZSHRC_BLOCK

    if dry_run:
        print("  [dry-run] ville skrevet NPM_TOKEN-blokk til .zshrc")
        return

    ZSHRC.write_text(new_content)
    print("  ✓ NPM_TOKEN-blokk oppdatert")


def _parse_npmrc(text: str) -> tuple[list[str], dict[str, int]]:
    """Returnerer (linjer, {nøkkel: linjeindeks}) for ikke-kommenterte linjer."""
    lines = text.splitlines()
    keys: dict[str, int] = {}
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            m = re.match(r"^([^=]+)=", stripped)
            if m:
                keys[m.group(1).strip()] = i
    return lines, keys


def update_npmrc(dry_run: bool) -> None:
    print(f"→ Oppdaterer {NPMRC}")
    backup(NPMRC, dry_run)

    existing = NPMRC.read_text() if NPMRC.exists() else ""
    lines, keys = _parse_npmrc(existing)

    desired = {
        NPMRC_REGISTRY_KEY: f"{NPMRC_REGISTRY_KEY}={NPMRC_REGISTRY_VALUE}",
        NPMRC_AUTH_KEY: f"{NPMRC_AUTH_KEY}={NPMRC_AUTH_VALUE}",
    }

    for key, line in desired.items():
        if key in keys:
            lines[keys[key]] = line
        else:
            lines.append(line)

    new_content = "\n".join(lines)
    if not new_content.endswith("\n"):
        new_content += "\n"

    if dry_run:
        print("  [dry-run] ville satt @navikt:registry og _authToken-linjer")
        return

    NPMRC.write_text(new_content)
    print("  ✓ @navikt:registry og auth-token-referanse satt")


def update_maven_settings(username: str, dry_run: bool) -> None:
    print(f"→ Oppdaterer {MAVEN_SETTINGS}")
    backup(MAVEN_SETTINGS, dry_run)

    if MAVEN_SETTINGS.exists():
        tree = ET.parse(MAVEN_SETTINGS)
        root = tree.getroot()
    else:
        root = ET.Element("settings")
        tree = ET.ElementTree(root)

    servers = root.find("servers")
    if servers is None:
        servers = ET.SubElement(root, "servers")

    server = None
    for s in servers.findall("server"):
        id_el = s.find("id")
        if id_el is not None and id_el.text == MAVEN_SERVER_ID:
            server = s
            break

    if server is None:
        server = ET.SubElement(servers, "server")
        ET.SubElement(server, "id").text = MAVEN_SERVER_ID
        ET.SubElement(server, "username").text = username
        ET.SubElement(server, "password").text = "${env.NPM_TOKEN}"
    else:
        for tag, value in (("username", username), ("password", "${env.NPM_TOKEN}")):
            el = server.find(tag)
            if el is None:
                el = ET.SubElement(server, tag)
            el.text = value

    if dry_run:
        print(f"  [dry-run] ville satt <server id=\"{MAVEN_SERVER_ID}\"> med username={username}")
        return

    MAVEN_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(tree, space="  ")
    tree.write(MAVEN_SETTINGS, encoding="unicode", xml_declaration=False)
    MAVEN_SETTINGS.write_text(MAVEN_SETTINGS.read_text() + "\n")
    print(f"  ✓ <server id=\"{MAVEN_SERVER_ID}\"> oppdatert (username={username})")


def main() -> None:
    dry_run = "--dry-run" in sys.argv

    print("Sjekker gh-innlogging og read:packages-scope...", flush=True)
    check_gh_scope()
    username = get_github_username()
    print(f"  ✓ Logget inn som {username} med read:packages\n")

    update_zshrc(dry_run)
    update_npmrc(dry_run)
    update_maven_settings(username, dry_run)

    print(
        "\nFerdig! Neste steg:\n"
        "  1. source ~/.zshrc\n"
        "  2. npm whoami --registry=https://npm.pkg.github.com/   (verifiser npm-auth)\n"
        "  3. mvn dependency:get -Dartifact=<gruppeId>:<artifaktId>:<versjon>   (verifiser Maven-auth)\n"
    )


if __name__ == "__main__":
    main()
