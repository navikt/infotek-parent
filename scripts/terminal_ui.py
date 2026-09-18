from __future__ import annotations

import atexit
import os
import re
import select
import signal
import sys
import time
from pathlib import Path
from typing import Callable, Sequence

BOLD = "\033[1m"
CYAN = "\033[36m"
DIM = "\033[2m"
RESET = "\033[0m"
_ALT_SCREEN_ACTIVE = False
REPORT_CHOICE_TIMEOUT_SECONDS = 10
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def supports_alt_screen() -> bool:
    return os.environ.get("TERM", "") not in ("", "dumb") and sys.stdout.isatty()


def enter_alt_screen() -> None:
    global _ALT_SCREEN_ACTIVE
    if supports_alt_screen():
        sys.stdout.write("\033[?1049h\033[H")
        sys.stdout.flush()
        _ALT_SCREEN_ACTIVE = True


def exit_alt_screen() -> None:
    global _ALT_SCREEN_ACTIVE
    if _ALT_SCREEN_ACTIVE:
        sys.stdout.write("\033[?1049l")
        sys.stdout.flush()
        _ALT_SCREEN_ACTIVE = False


def clear_screen() -> None:
    if supports_alt_screen():
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()


def format_age(age_seconds: int) -> str:
    if age_seconds < 60:
        return f"{age_seconds} sekunder gammel"
    return f"{age_seconds // 60} minutter gammel"


def github_alert_counts(repository: dict) -> tuple[int, int]:
    """Returnerer åpne GitHub-varsler med kritisk og høy alvorlighetsgrad."""
    alerts = [
        alert
        for result in repository.get("github", {}).values()
        if isinstance(result, dict)
        for alert in result.get("items", [])
        if isinstance(alert, dict) and alert.get("state") in {"open", "OPEN"}
    ]
    return (
        sum(str(alert.get("severity", "")).lower() == "critical" for alert in alerts),
        sum(str(alert.get("severity", "")).lower() == "high" for alert in alerts),
    )


def nais_alert_counts(repository: dict) -> tuple[int | None, int | None]:
    vulnerabilities = repository.get("nais_vulnerabilities", {})
    return vulnerabilities.get("critical"), vulnerabilities.get("high")


def terminal_width() -> int:
    return os.get_terminal_size().columns if sys.stdout.isatty() else 80


def visible_length(value: str) -> int:
    return len(ANSI_RE.sub("", value))


def truncate(value: str, width: int) -> str:
    if visible_length(value) <= width:
        return value
    limit = max(0, width - 1)
    parts: list[str] = []
    visible = 0
    index = 0
    while index < len(value) and visible < limit:
        match = ANSI_RE.match(value, index)
        if match:
            parts.append(match.group(0))
            index = match.end()
            continue
        parts.append(value[index])
        visible += 1
        index += 1
    while index < len(value):
        match = ANSI_RE.match(value, index)
        if not match:
            break
        parts.append(match.group(0))
        index = match.end()
    truncated = "".join(parts) + "…"
    return truncated + (RESET if ANSI_RE.search(truncated) and not truncated.endswith(RESET) else "")


def pad(value: str, width: int) -> str:
    return value + " " * max(0, width - visible_length(value))


def fit_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    maximum_width: int | None = None,
) -> tuple[tuple[str, ...], list[tuple[str, ...]], list[int]]:
    """Tilpasser tabellkolonner til terminalbredden med avkortede felt."""
    maximum_width = maximum_width or terminal_width()
    compact_headers = tuple(headers)
    values = [tuple(str(value) for value in row) for row in rows]
    widths = [
        max(visible_length(header), max((visible_length(row[index]) for row in values), default=0))
        for index, header in enumerate(compact_headers)
    ]
    minimum_widths = {
        "Tast": 4,
        "Prioritet": 7,
        "Repo": 8,
        "PR": 4,
        "Branch": 8,
        "Tittel": 14,
        "Forfatter": 8,
        "Status": 6,
        "GH C/H": 6,
        "Nais C/H": 8,
    }
    minimums = [min(len(header), minimum_widths.get(header, len(header))) for header in compact_headers]
    overflow = sum(widths) + 2 * (len(widths) - 1) - maximum_width
    for index in sorted(range(len(widths)), key=lambda item: widths[item] - minimums[item], reverse=True):
        if overflow <= 0:
            break
        reduction = min(overflow, widths[index] - minimums[index])
        widths[index] -= reduction
        overflow -= reduction
    compact_headers = tuple(truncate(header, widths[index]) for index, header in enumerate(compact_headers))
    compact_rows = [
        tuple(truncate(value, widths[index]) for index, value in enumerate(row))
        for row in values
    ]
    return compact_headers, compact_rows, widths


def choose_cached_report(path: Path, title: str, summary: Callable[[], str], freshness_seconds: int = 15 * 60) -> str:
    """Returnerer reuse, new eller quit for valg av rapport."""
    if not path.exists():
        return choose(
            title,
            [("ny", "Lag ny rapport", "n"), ("quit", "Avslutt", "q")],
            clear=True,
            timeout_seconds=REPORT_CHOICE_TIMEOUT_SECONDS,
        )
    age_seconds = max(0, int(time.time() - path.stat().st_mtime))
    return choose(
        title,
        [
            ("fortsett", f"Vis lagret tabell ({format_age(age_seconds)}, {summary()})", "f"),
            ("ny", "Lag ny rapport", "n"),
            ("quit", "Avslutt", "q"),
        ],
        default=0 if age_seconds < freshness_seconds else 1,
        clear=True,
        timeout_seconds=REPORT_CHOICE_TIMEOUT_SECONDS,
    )


def print_table(title: str, headers: Sequence[str], rows: Sequence[Sequence[str]], footer: str = "") -> None:
    headers, rows, widths = fit_table(headers, rows)
    print(f"\n{BOLD}{title}{RESET}\n")
    print("  ".join(pad(header, width) for header, width in zip(headers, widths)))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(pad(value, width) for value, width in zip(row, widths)))
    if footer:
        print(f"\n{footer}")


def choose_table(
    title: str,
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    global_options: Sequence[tuple[str, str, str]],
    default: int = 0,
) -> str:
    """Velger en tabellrad eller global handling med piltaster og snarveier."""
    options = [(f"row-{index}", "", str(index + 1)) for index in range(len(rows))] + list(global_options)
    if not sys.stdin.isatty() or not sys.stdout.isatty() or os.environ.get("TERM", "") in ("", "dumb"):
        print_table(title, headers, rows)
        return choose("Velg rad eller handling", options, default=len(rows) + default)

    import termios
    import tty

    selected = 0 if rows else len(rows) + default
    shortcuts = {shortcut: key for key, _, shortcut in options}
    while True:
        clear_screen()
        compact_headers, compact_rows, widths = fit_table(headers, rows)
        print(f"\n{BOLD}{title}{RESET}\n")
        print("  ".join(pad(header, width) for header, width in zip(compact_headers, widths)))
        print("  ".join("-" * width for width in widths))
        for index, row in enumerate(compact_rows):
            prefix = f"{CYAN}❯ {RESET}" if selected == index else "  "
            print(prefix + "  ".join(pad(value, width) for value, width in zip(row, widths)))
        print()
        for index, (_, label, shortcut) in enumerate(global_options):
            option_index = len(rows) + index
            prefix = f"{CYAN}❯ {RESET}" if selected == option_index else "  "
            print(f"{prefix}[{shortcut}] {label}")
        print(f"\n{DIM}Bruk ↑/↓ og Enter, eller snarvei. Ctrl-C avslutter.{RESET}", end="", flush=True)

        descriptor = sys.stdin.fileno()
        previous = termios.tcgetattr(descriptor)
        try:
            tty.setraw(descriptor)
            key = sys.stdin.read(1)
            if key == "\x1b":
                key += sys.stdin.read(2)
            elif key == "\x03":
                raise KeyboardInterrupt
            elif key.isdigit():
                while select.select([sys.stdin], [], [], 0.25)[0]:
                    key += sys.stdin.read(1)
        finally:
            termios.tcsetattr(descriptor, termios.TCSADRAIN, previous)

        if key in ("\r", "\n"):
            return options[selected][0]
        if key in shortcuts:
            return shortcuts[key]
        if key == "\x1b[A":
            selected = (selected - 1) % len(options)
        elif key == "\x1b[B":
            selected = (selected + 1) % len(options)


atexit.register(exit_alt_screen)


def _exit_on_sigterm(_signal: int, _frame: object) -> None:
    exit_alt_screen()
    raise SystemExit(0)


signal.signal(signal.SIGTERM, _exit_on_sigterm)


def choose(
    title: str,
    options: Sequence[tuple[str, str] | tuple[str, str, str]],
    default: int = 0,
    clear: bool = False,
    timeout_seconds: float | None = None,
) -> str:
    """Returnerer nøkkelen for et valg, med piltaster når terminalen støtter det."""
    if not options:
        raise ValueError("Menyen må ha minst ett valg.")
    normalized = [(option[0], option[1], option[2] if len(option) == 3 else "") for option in options]
    shortcuts = {shortcut.lower(): key for key, _, shortcut in normalized if shortcut}
    if len(shortcuts) != len([shortcut for _, _, shortcut in normalized if shortcut]):
        raise ValueError("Snarveier må være unike.")

    if not (sys.stdin.isatty() and sys.stdout.isatty() and os.environ.get("TERM", "") not in ("", "dumb")):
        print(f"\n{BOLD}{title}{RESET}")
        for index, (_, label, shortcut) in enumerate(normalized, 1):
            marker = " (standard)" if index - 1 == default else ""
            shortcut_label = f"[{shortcut}] " if shortcut else ""
            print(f"  {index}. {shortcut_label}{label}{marker}")
        while True:
            try:
                raw = input(f"Velg [standard {default + 1}]: ").strip()
            except EOFError:
                print()
                return options[default][0]
            if not raw:
                return normalized[default][0]
            if raw.lower() in shortcuts:
                return shortcuts[raw.lower()]
            try:
                selected = int(raw)
                if not 1 <= selected <= len(normalized):
                    raise ValueError
                return normalized[selected - 1][0]
            except ValueError:
                print("Ugyldig valg.")

    import termios
    import tty

    selected = default
    menu_lines = len(options) + 4
    deadline = time.monotonic() + timeout_seconds if timeout_seconds is not None else None
    while True:
        remaining_seconds = max(0, int(deadline - time.monotonic() + 0.999)) if deadline is not None else None
        if deadline is not None and remaining_seconds == 0:
            return normalized[default][0]
        if clear:
            sys.stdout.write("\033[H\033[J")
        print(f"\n{BOLD}{title}{RESET}\n")
        for index, (_, label, shortcut) in enumerate(normalized):
            shortcut_label = f"[{shortcut}] " if shortcut else ""
            if index == selected:
                print(f"  {CYAN}❯ {shortcut_label}{label}{RESET}")
            else:
                print(f"    {DIM}{shortcut_label}{label}{RESET}")
        timeout_message = f" Standard velges om {remaining_seconds} sek." if remaining_seconds is not None else ""
        print(
            f"\n{DIM}Bruk ↑/↓ og Enter, eller snarvei. Ctrl-C avslutter.{timeout_message}{RESET}",
            end="",
            flush=True,
        )

        descriptor = sys.stdin.fileno()
        previous = termios.tcgetattr(descriptor)
        try:
            tty.setraw(descriptor)
            wait_seconds = min(1.0, max(0.0, deadline - time.monotonic())) if deadline is not None else None
            ready, _, _ = select.select([sys.stdin], [], [], wait_seconds)
            if not ready:
                continue
            key = sys.stdin.read(1)
            if key == "\x1b":
                key += sys.stdin.read(2)
            elif key == "\x03":
                raise KeyboardInterrupt
            elif key.lower() in shortcuts:
                if any(shortcut.startswith(key.lower()) and len(shortcut) > 1 for shortcut in shortcuts):
                    ready, _, _ = select.select([sys.stdin], [], [], 0.35)
                    if ready:
                        key += sys.stdin.read(1)
        finally:
            termios.tcsetattr(descriptor, termios.TCSADRAIN, previous)

        if key in ("\r", "\n"):
            print()
            return normalized[selected][0]
        if key.lower() in shortcuts:
            print()
            return shortcuts[key.lower()]
        if key == "\x1b[A":
            selected = (selected - 1) % len(options)
        elif key == "\x1b[B":
            selected = (selected + 1) % len(options)
        else:
            continue
        if not clear:
            sys.stdout.write(f"\r\033[{menu_lines}A\033[J")
            sys.stdout.flush()
