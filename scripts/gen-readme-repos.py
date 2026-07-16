#!/usr/bin/env python3
"""
Regenererer repo-oversikts-seksjonen i README.md fra repos.yaml.
Henter repo-beskrivelser fra GitHub API via gh CLI.
Bevarer alt manuelt innhold utenfor den auto-genererte seksjonen.
"""

import sys
import re
import subprocess
from collections import defaultdict

MARKER_START = "<!-- AUTO-GENERATED:README-REPOS START -->"
MARKER_END   = "<!-- AUTO-GENERATED:README-REPOS END -->"

NAIS_CONSOLE = "https://console.nav.cloud.nais.io/team"

NAMESPACE_EMOJI = {
    "infotek":   "🟦",
    "infotrygd": "🟧",
    "historisk": "🟩",
}

NAMESPACE_ORDER = ["infotek", "infotrygd", "historisk"]


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

            if re.match(r"^\s{2}-\s+name\s*:", line):
                if current:
                    repos.append(current)
                current = {"stack": [], "environments": []}
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
                    items = inline.strip("[]").split(",")
                    current["stack"] = [i.strip() for i in items if i.strip()]
                    in_stack = False
            elif re.match(r"^\s{4}environments\s*:", line):
                in_stack = False
                inline = line.split(":", 1)[1].strip()
                if inline.startswith("["):
                    items = inline.strip("[]").split(",")
                    current["environments"] = [i.strip() for i in items if i.strip()]
            elif in_stack and re.match(r"^\s{6}-\s+", line):
                current["stack"].append(stripped.lstrip("- ").strip())
            else:
                in_stack = False

    if current:
        repos.append(current)

    return repos


def fetch_github_description(org: str, name: str) -> str:
    """Henter repo-beskrivelse fra GitHub API via gh CLI."""
    try:
        result = subprocess.run(
            ["gh", "api", f"/repos/{org}/{name}", "--jq", ".description"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            desc = result.stdout.strip()
            if desc and desc.lower() != "null":
                return desc
    except Exception:
        pass
    return "—"


def nais_links(namespace: str, name: str, environments: list) -> str:
    """Genererer Nais Console-lenker for alle miljøer."""
    if not environments:
        return "—"
    links = []
    for env in environments:
        url = f"{NAIS_CONSOLE}/{namespace}/app/{env}/{name}"
        links.append(f"[{env}]({url})")
    return " · ".join(links)


def generate_section(repos: list[dict]) -> str:
    groups: dict[str, list] = defaultdict(list)
    for r in repos:
        groups[r.get("namespace", "ukjent")].append(r)

    lines = [MARKER_START, "", "## Teamets repos", ""]

    ordered_namespaces = NAMESPACE_ORDER + [ns for ns in groups if ns not in NAMESPACE_ORDER]

    for namespace in ordered_namespaces:
        if namespace not in groups:
            continue
        ns_repos = groups[namespace]
        emoji = NAMESPACE_EMOJI.get(namespace, "⬜")
        console_url = f"{NAIS_CONSOLE}/{namespace}"

        lines.append(f"### {emoji} `{namespace}` — [Nais Console]({console_url})")
        lines.append("")
        lines.append("| Repo | Beskrivelse | Miljøer | Nais |")
        lines.append("|------|-------------|---------|------|")

        for r in ns_repos:
            repo_name = r["name"]
            org = r.get("org", "navikt")
            envs = r.get("environments", [])
            managed = r.get("managed", True)

            gh_url = f"https://github.com/{org}/{repo_name}"
            print(f"  Henter beskrivelse: {org}/{repo_name} ...", file=sys.stderr)
            desc = fetch_github_description(org, repo_name)
            env_str = ", ".join(envs) if envs else "—"
            nais = nais_links(namespace, repo_name, envs)
            managed_badge = "" if managed else " ⚠️"

            lines.append(f"| [{repo_name}]({gh_url}){managed_badge} | {desc} | {env_str} | {nais} |")

        lines.append("")

    lines.append(MARKER_END)
    return "\n".join(lines)


def update_readme(repos_file: str, readme_file: str) -> None:
    repos = parse_repos_yaml(repos_file)
    new_section = generate_section(repos)

    try:
        with open(readme_file) as f:
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

    with open(readme_file, "w") as f:
        f.write(updated)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Bruk: {sys.argv[0]} <repos.yaml> <README.md>", file=sys.stderr)
        sys.exit(1)
    update_readme(sys.argv[1], sys.argv[2])
