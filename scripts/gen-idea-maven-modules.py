#!/usr/bin/env python3
"""
Synker .idea/misc.xml sin liste over Maven-moduler med repos.yaml.

Tar med repos.yaml.repos[] der managed == true OG repos/<name>/pom.xml
faktisk finnes på disk (repoet er klonet og er Maven-basert). Ikke-managed
repos (f.eks. infotek-personkort) og ikke-Maven-repos ekskluderes.

Bevarer alt annet innhold i misc.xml (f.eks. ProjectRootManager/JDK-valg)
uendret. Idempotent — trygt å kjøre flere ganger.

Bruker ingen tredjeparts-biblioteker.
"""

import os
import re
import sys
import xml.etree.ElementTree as ET


def parse_repos_yaml(path: str) -> list[dict]:
    """Enkel linje-for-linje parser for vår kontrollerte repos.yaml-struktur.

    Samme tilnærming som scripts/gen-agents.py sin parse_repos_yaml.
    """
    repos, current = [], {}
    in_repos = False

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
                current = {}
                current["name"] = line.split(":", 1)[1].strip()
                continue

            if not current:
                continue

            if re.match(r"^\s{4}managed\s*:", line):
                val = line.split(":", 1)[1].strip().lower()
                current["managed"] = val == "true"

    if current:
        repos.append(current)
    return repos


def find_maven_module_paths(repos: list, project_dir: str) -> list[str]:
    """Returnerer sortert liste med relative pom.xml-stier for managed Maven-repos."""
    paths = []
    for r in repos:
        if not r.get("managed", False):
            continue
        name = r.get("name", "")
        if not name:
            continue
        pom_path = os.path.join(project_dir, "repos", name, "pom.xml")
        if os.path.isfile(pom_path):
            paths.append(f"repos/{name}/pom.xml")
    return sorted(paths)


NS_MAP = {}


def update_misc_xml(misc_xml_path: str, module_paths: list[str]) -> None:
    """Oppdaterer (eller oppretter) MavenProjectsManager-komponenten i misc.xml.

    Andre komponenter (f.eks. ProjectRootManager) beholdes uendret.
    """
    if os.path.isfile(misc_xml_path):
        tree = ET.parse(misc_xml_path)
        root = tree.getroot()
    else:
        root = ET.Element("project", {"version": "4"})
        tree = ET.ElementTree(root)

    maven_component = None
    for comp in root.findall("component"):
        if comp.get("name") == "MavenProjectsManager":
            maven_component = comp
            break

    if maven_component is None:
        maven_component = ET.SubElement(root, "component", {"name": "MavenProjectsManager"})
    else:
        for child in list(maven_component):
            maven_component.remove(child)

    option = ET.SubElement(maven_component, "option", {"name": "originalFiles"})
    lst = ET.SubElement(option, "list")
    for path in module_paths:
        ET.SubElement(lst, "option", {"value": f"$PROJECT_DIR$/{path}"})

    ET.indent(tree, space="  ")
    body = ET.tostring(root, encoding="unicode")
    with open(misc_xml_path, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write(body)
        f.write("\n")


def main() -> None:
    if len(sys.argv) != 3:
        print(f"Bruk: {sys.argv[0]} <repos.yaml> <.idea/misc.xml>", file=sys.stderr)
        sys.exit(1)

    repos_file = sys.argv[1]
    misc_xml_path = sys.argv[2]
    project_dir = os.path.dirname(os.path.abspath(repos_file))

    repos = parse_repos_yaml(repos_file)
    module_paths = find_maven_module_paths(repos, project_dir)

    update_misc_xml(misc_xml_path, module_paths)

    print(f"✅ Synket {len(module_paths)} Maven-modul(er) til {misc_xml_path}")
    for path in module_paths:
        print(f"   - {path}")


if __name__ == "__main__":
    main()
