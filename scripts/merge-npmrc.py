#!/usr/bin/env python3
"""
Merger teamstandard .npmrc inn i eksisterende .npmrc.
- Legger til manglende nøkler fra malen
- Overskriver IKKE eksisterende verdier
- Beholder kommentarer og rekkefølge i original
"""
import sys
import re


def parse_npmrc(path: str) -> tuple[list[str], dict[str, str]]:
    """Returnerer (linjer, {nøkkel: verdi}) — nøkler uten @-prefiks normalisert."""
    lines, keys = [], {}
    with open(path) as f:
        for line in f:
            lines.append(line.rstrip("\n"))
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                m = re.match(r"^([^=]+)=(.*)$", stripped)
                if m:
                    keys[m.group(1).strip()] = m.group(2).strip()
    return lines, keys


def merge(template_path: str, target_path: str) -> None:
    _, template_keys = parse_npmrc(template_path)
    target_lines, target_keys = parse_npmrc(target_path)

    additions = []
    for key, value in template_keys.items():
        if key not in target_keys:
            additions.append(f"{key}={value}")

    if not additions:
        return

    with open(target_path, "w") as f:
        f.write("\n".join(target_lines))
        if target_lines and target_lines[-1] != "":
            f.write("\n")
        f.write("\n# Lagt til av infotek-parent teamstandard\n")
        for line in additions:
            f.write(line + "\n")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Bruk: {sys.argv[0]} <template.npmrc> <target.npmrc>", file=sys.stderr)
        sys.exit(1)
    merge(sys.argv[1], sys.argv[2])
