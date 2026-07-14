#!/usr/bin/env python3
"""
Regenererer AGENTS.md-seksjonen for repo-oversikt fra repos.yaml.
Bevarer alt manuelt innhold utenfor den auto-genererte seksjonen.
Bruker ingen tredjeparts-biblioteker.
"""

import sys
import re

MARKER_START = "<!-- AUTO-GENERATED:REPOS START -->"
MARKER_END   = "<!-- AUTO-GENERATED:REPOS END -->"


def parse_repos_yaml(path: str) -> list[dict]:
    """Enkel linje-for-linje parser for vår kontrollerte repos.yaml-struktur."""
    repos, current = [], {}
    in_repos = False
    in_stack = False

    with open(path) as f:
        for raw in f:
            line = raw.rstrip()
            stripped = line.lstrip()

            if stripped.startswith("#") or not stripped:
                continue

            if re.match(r"^repos\s*:", line):
                in_repos = True
                continue

            if not in_repos:
                continue

            # Nytt list-element på øverste repos-nivå
            if re.match(r"^\s{2}-\s+name\s*:", line):
                if current:
                    repos.append(current)
                current = {"stack": []}
                current["name"] = line.split(":", 1)[1].strip()
                in_stack = False
                continue

            if not current:
                continue

            if re.match(r"^\s{4}org\s*:", line):
                current["org"] = line.split(":", 1)[1].strip().split("#")[0].strip()
            elif re.match(r"^\s{4}namespace\s*:", line):
                current["namespace"] = line.split(":", 1)[1].strip()
            elif re.match(r"^\s{4}description\s*:", line):
                current["description"] = line.split(":", 1)[1].strip().strip('"')
            elif re.match(r"^\s{4}managed\s*:", line):
                val = line.split(":", 1)[1].strip().lower()
                current["managed"] = val == "true"
            elif re.match(r"^\s{4}stack\s*:", line):
                in_stack = True
                inline = line.split(":", 1)[1].strip()
                if inline.startswith("["):
                    current["stack"] = [s.strip().strip("]") for s in inline.strip("[]").split(",") if s.strip().strip("]")]
                    in_stack = False
            elif in_stack and re.match(r"^\s{6}-\s+", line):
                current["stack"].append(stripped.lstrip("- ").strip())
            elif re.match(r"^\s{4}default_branch\s*:", line):
                current["default_branch"] = line.split(":", 1)[1].strip()
            elif re.match(r"^\s{4}environments\s*:", line):
                inline = line.split(":", 1)[1].strip()
                if inline.startswith("["):
                    current["environments"] = [s.strip().strip("]") for s in inline.strip("[]").split(",") if s.strip().strip("]")]
            elif in_stack:
                in_stack = False

    if current:
        repos.append(current)
    return repos


def generate_repo_table(repos: list) -> str:
    lines = [
        MARKER_START,
        "",
        "## Teamets repos",
        "",
        "| Repo | Org | Namespace | Miljøer | Forvaltet |",
        "|------|-----|-----------|---------|-----------|",
    ]
    for r in repos:
        name      = r.get("name", "")
        org       = r.get("org", "")
        ns        = r.get("namespace", "")
        envs      = ", ".join(r.get("environments", [])) or "—"
        managed   = "✅" if r.get("managed", True) else "❌"
        url       = f"https://github.com/{org}/{name}"
        lines.append(f"| [{name}]({url}) | `{org}` | `{ns}` | {envs} | {managed} |")
    lines += ["", MARKER_END]
    return "\n".join(lines)


def update_agents_md_from_repos(repos: list, agents_file: str) -> None:
    new_section = generate_repo_table(repos)

    try:
        with open(agents_file) as f:
            content = f.read()
        pattern = re.compile(
            re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END),
            re.DOTALL,
        )
        if pattern.search(content):
            updated = pattern.sub(new_section, content)
        else:
            updated = content.rstrip() + "\n\n" + new_section + "\n"
    except FileNotFoundError:
        updated = new_section + "\n"

    with open(agents_file, "w") as f:
        f.write(updated)


def update_agents_md(repos_file: str, agents_file: str) -> None:
    repos = parse_repos_yaml(repos_file)
    update_agents_md_from_repos(repos, agents_file)


def update_gitignore(repos: list, gitignore_path: str) -> None:
    """Oppdaterer .gitignore med alle repo-navn fra repos.yaml."""
    MARKER_START_GI = "# AUTO-GENERATED:REPOS START"
    MARKER_END_GI   = "# AUTO-GENERATED:REPOS END"

    lines = [MARKER_START_GI]
    for r in repos:
        name = r.get("name", "")
        lines.append(f"{name}/")
    lines.append(MARKER_END_GI)
    new_section = "\n".join(lines)

    try:
        with open(gitignore_path) as f:
            content = f.read()
        import re as _re
        pattern = _re.compile(
            _re.escape(MARKER_START_GI) + r".*?" + _re.escape(MARKER_END_GI),
            _re.DOTALL,
        )
        if pattern.search(content):
            updated = pattern.sub(new_section, content)
        else:
            updated = content.rstrip() + "\n\n" + new_section + "\n"
    except FileNotFoundError:
        updated = new_section + "\n"

    with open(gitignore_path, "w") as f:
        f.write(updated)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Bruk: {sys.argv[0]} <repos.yaml> <AGENTS.md> [.gitignore]", file=sys.stderr)
        sys.exit(1)
    repos = parse_repos_yaml(sys.argv[1])
    update_agents_md_from_repos(repos, sys.argv[2])
    if len(sys.argv) == 4:
        update_gitignore(repos, sys.argv[3])
