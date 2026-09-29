"""Maven-delen av oppsettet for GitHub Packages. Kjøres via setup_github_packages."""

from __future__ import annotations

import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path
from xml.parsers import expat

from scripts.setup_node_package_token import SetupError, validate_gh
from scripts.setup_node_package_token import atomic_write as write_text

ZSHRC_START = "# --- infotek MAVEN_PASSWORD ---"
ZSHRC_END = "# --- slutt infotek MAVEN_PASSWORD ---"
GITHUB_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
SERVER = (
    "<server>\n"
    "  <id>github</id>\n"
    "  <username>${env.MAVEN_USERNAME}</username>\n"
    "  <password>${env.MAVEN_PASSWORD}</password>\n"
    "</server>"
)


def inspect_settings(
    data: bytes,
) -> tuple[bool, tuple[int, int, bytes] | None, tuple[int, int, bytes]]:
    parser = expat.ParserCreate(namespace_separator="}")
    stack: list[str] = []
    servers: tuple[int, int, bytes] | None = None
    root: tuple[int, int, bytes] | None = None
    github_found = False
    server_id = ""

    def start(name: str, _attributes: dict[str, str]) -> None:
        nonlocal server_id, servers, root
        local_name = name.rsplit("}", 1)[-1]
        stack.append(local_name)
        position = parser.CurrentByteIndex
        if len(stack) == 1:
            if local_name != "settings":
                raise SetupError("settings.xml må ha <settings> som rot.")
            root = (position, -1, tag_name(data, position))
        elif stack == ["settings", "servers"]:
            if servers is not None:
                raise SetupError("settings.xml har flere <servers>-elementer.")
            servers = (position, -1, tag_name(data, position))
        elif stack == ["settings", "servers", "server"]:
            server_id = ""

    def characters(text: str) -> None:
        nonlocal server_id
        if stack == ["settings", "servers", "server", "id"]:
            server_id += text

    def end(name: str) -> None:
        nonlocal servers, root, github_found
        if stack == ["settings", "servers", "server"]:
            github_found |= server_id.strip() == "github"
        elif stack == ["settings", "servers"]:
            assert servers is not None
            servers = (servers[0], parser.CurrentByteIndex, servers[2])
        elif stack == ["settings"]:
            assert root is not None
            root = (root[0], parser.CurrentByteIndex, root[2])
        stack.pop()

    def reject_doctype(*_args: object) -> None:
        raise SetupError("DOCTYPE støttes ikke i settings.xml.")

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = characters
    parser.StartDoctypeDeclHandler = reject_doctype
    try:
        data.decode("utf-8-sig")
        parser.Parse(data, True)
    except UnicodeError as error:
        raise SetupError("settings.xml må være UTF-8.") from error
    except expat.ExpatError as error:
        raise SetupError(f"Ugyldig XML i settings.xml (linje {error.lineno}).") from error
    if root is None:
        raise SetupError("settings.xml mangler <settings>.")
    return github_found, servers, root


def tag_name(data: bytes, position: int) -> bytes:
    match = re.match(rb"<([A-Za-z_][A-Za-z0-9_.:-]*)", data[position:])
    if match is None:
        raise SetupError("Kunne ikke lese XML-element i settings.xml.")
    return match.group(1)


def insert_child(data: bytes, element: tuple[int, int, bytes], child: bytes) -> bytes:
    start, end, name = element
    newline = b"\r\n" if b"\r\n" in data else b"\n"
    line_start = data.rfind(b"\n", 0, start) + 1
    indent = data[line_start:start] if data[line_start:start].strip() == b"" else b""
    child_indent = indent + b"  "
    formatted = newline.join(child_indent + line for line in child.split(b"\n"))
    if data[start:end].rstrip().endswith(b"/>"):
        opening = re.sub(rb"/\s*>$", b">", data[start:end])
        return (
            data[:start]
            + opening + newline + formatted + newline + indent
            + b"</" + name + b">" + data[end:]
        )
    closing_line = data.rfind(b"\n", 0, end) + 1
    if data[closing_line:end].strip() == b"" and closing_line > start:
        return data[:closing_line] + formatted + newline + data[closing_line:]
    return data[:end] + newline + formatted + newline + indent + data[end:]


def update_settings(data: bytes) -> tuple[bytes, bool]:
    exists, servers, root = inspect_settings(data)
    if exists:
        return data, False
    prefix = root[2].rpartition(b":")[0] + b":" if b":" in root[2] else b""
    if servers is None:
        server = re.sub(
            rb"<(/?)", lambda match: b"<" + match.group(1) + prefix, SERVER.encode()
        )
        servers_block = (
            b"<" + prefix + b"servers>\n"
            + b"  " + server.replace(b"\n", b"\n  ")
            + b"\n</" + prefix + b"servers>"
        )
        return insert_child(data, root, servers_block), True
    prefix = servers[2].rpartition(b":")[0] + b":" if b":" in servers[2] else b""
    server = re.sub(
        rb"<(/?)", lambda match: b"<" + match.group(1) + prefix, SERVER.encode()
    )
    return insert_child(data, servers, server), True


def zshrc_block(username: str) -> str:
    if not GITHUB_LOGIN.match(username):
        raise SetupError("Ugyldig GitHub-brukernavn for MAVEN_USERNAME.")
    return (
        f"{ZSHRC_START}\n"
        f'export MAVEN_USERNAME="{username}"\n'
        'export MAVEN_PASSWORD="$(gh auth token)"\n'
        f"{ZSHRC_END}\n"
    )


def update_zshrc(content: str, username: str) -> str:
    block = zshrc_block(username)
    start_count = content.count(ZSHRC_START)
    end_count = content.count(ZSHRC_END)
    if start_count != end_count or start_count > 1:
        raise SetupError("Ubalanserte MAVEN_PASSWORD-markører i .zshrc.")
    pattern = re.compile(
        rf"(?ms)^{re.escape(ZSHRC_START)}$.*?^{re.escape(ZSHRC_END)}$\n?"
    )
    if re.search(r"(?m)^\s*export\s+MAVEN_PASSWORD\s*=", pattern.sub("", content)):
        raise SetupError(
            ".zshrc setter allerede MAVEN_PASSWORD utenfor den administrerte blokken."
        )
    if start_count:
        return pattern.sub(lambda _match: block, content)
    separator = "" if not content or content.endswith("\n") else "\n"
    return content + separator + ("\n" if content else "") + block


def atomic_write(path: Path, data: bytes) -> None:
    if path.is_symlink():
        raise SetupError(f"{path} er en symlink; oppdater den manuelt.")
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def gh_username() -> str:
    result = subprocess.run(
        ["gh", "api", "user", "--jq", ".login"],
        text=True,
        capture_output=True,
        check=False,
    )
    username = result.stdout.strip() if result.returncode == 0 else ""
    if not username:
        raise SetupError("Fant ikke GitHub-brukernavnet. Kontroller innloggingen med gh auth status.")
    return username


def configure(home: Path) -> list[Path]:
    settings = home / ".m2" / "settings.xml"
    if settings.is_symlink():
        raise SetupError("settings.xml er en symlink; oppdater den manuelt.")
    original = settings.read_bytes() if settings.exists() else b"<settings>\n</settings>\n"
    updated, settings_changed = update_settings(original)

    validate_gh()
    zshrc = home / ".zshrc"
    current_zshrc = zshrc.read_text() if zshrc.exists() else ""
    zshrc_update = update_zshrc(current_zshrc, gh_username())

    changes = []
    if settings_changed:
        atomic_write(settings, updated)
        changes.append(settings)
    if not zshrc.exists() or current_zshrc != zshrc_update:
        write_text(zshrc, zshrc_update)
        changes.append(zshrc)
    return changes
