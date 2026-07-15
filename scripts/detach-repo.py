#!/usr/bin/env python3
"""
Løsriver et repo fra infotek-teamet.

Gjør for repoet:
  1. Erstatter extends-biome.json med full inline-konfig
  2. Erstatter extends-tsconfig.json med full inline-konfig
  3. Fjerner @navikt/infotek-frontend-config fra devDependencies
  4. Kjører pnpm install for å oppdatere lockfile
  5. Oppretter PR i repoet

Gjør i infotek-parent:
  6. Setter managed: false i repos.yaml
  7. Regenererer ai/AGENTS.md

Bruk:
  python3 scripts/detach-repo.py REPO=<reponavn> [--dry-run]
"""

import json
import re
import subprocess
import sys
from pathlib import Path

REPOS_DIR = Path(__file__).parent.parent / "repos"
REPOS_YAML = Path(__file__).parent.parent / "repos.yaml"
AGENTS_MD = Path(__file__).parent.parent / "ai" / "AGENTS.md"
BASE_DIR = Path(__file__).parent.parent / "platform" / "pnpm"

DRY_RUN = "--dry-run" in sys.argv
REPO_NAME = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("REPO=")), None)

STANDALONE_BIOME = {
    "$schema": "https://biomejs.dev/schemas/2.5.4/schema.json",
    "files": {
        "includes": ["**", "!dist", "!node_modules", "!.vite", "!generated"]
    },
    "formatter": {
        "enabled": True,
        "indentStyle": "space",
        "indentWidth": 2,
        "lineWidth": 100
    },
    "linter": {
        "enabled": True,
        "rules": {
            "recommended": True,
            "suspicious": {"noUnknownAtRules": "off"},
            "complexity": {"noImportantStyles": "off"}
        }
    },
    "javascript": {
        "formatter": {
            "arrowParentheses": "always",
            "jsxQuoteStyle": "double",
            "semicolons": "always",
            "trailingCommas": "es5"
        }
    },
    "json": {
        "formatter": {"trailingCommas": "none"}
    }
}


def run(cmd, cwd=None, check=True):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=check)


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def detach_biome(frontend_dir: Path) -> bool:
    biome_path = frontend_dir / "biome.json"
    if not biome_path.exists():
        return False
    data = json.loads(biome_path.read_text())
    if "extends" not in str(data):
        print("  ⏭  biome.json — allerede standalone")
        return False
    write_json(biome_path, STANDALONE_BIOME)
    print("  ✅ biome.json — inline-konfig skrevet")
    return True


def detach_tsconfig(frontend_dir: Path) -> bool:
    changed = False
    for fname in ["tsconfig.json", "tsconfig.app.json"]:
        tsconfig_path = frontend_dir / fname
        if not tsconfig_path.exists():
            continue
        data = json.loads(tsconfig_path.read_text())
        if "extends" not in data:
            continue
        if "infotek-frontend-config" not in data.get("extends", ""):
            continue

        # Merge base compilerOptions into local, then drop extends
        base_compiler_opts = {
            "target": "ES2020",
            "lib": ["ES2020", "DOM", "DOM.Iterable"],
            "jsx": "react-jsx",
            "module": "ESNext",
            "moduleResolution": "bundler",
            "strict": True,
            "esModuleInterop": True,
            "skipLibCheck": True,
            "forceConsistentCasingInFileNames": True,
            "resolveJsonModule": True,
            "isolatedModules": True,
            "noEmit": True,
            "allowJs": True,
        }
        merged_opts = {**base_compiler_opts, **data.get("compilerOptions", {})}
        new_data = {k: v for k, v in data.items() if k != "extends"}
        new_data["compilerOptions"] = merged_opts
        write_json(tsconfig_path, new_data)
        print(f"  ✅ {fname} — inline-konfig skrevet")
        changed = True
    return changed


def detach_package_json(frontend_dir: Path) -> bool:
    pkg_path = frontend_dir / "package.json"
    if not pkg_path.exists():
        return False
    data = json.loads(pkg_path.read_text())
    dev_deps = data.get("devDependencies", {})
    if "@navikt/infotek-frontend-config" not in dev_deps:
        print("  ⏭  package.json — infotek-frontend-config ikke funnet")
        return False
    del dev_deps["@navikt/infotek-frontend-config"]
    data["devDependencies"] = dict(sorted(dev_deps.items()))
    write_json(pkg_path, data)
    print("  ✅ package.json — @navikt/infotek-frontend-config fjernet")
    return True


def set_managed_false(repo_name: str) -> None:
    content = REPOS_YAML.read_text()
    # Find the repo block and flip managed: true → false
    pattern = rf"(- name: {re.escape(repo_name)}\b.*?managed:) true"
    new_content = re.sub(pattern, r"\1 false", content, flags=re.DOTALL)
    if new_content == content:
        print("  ⚠️  repos.yaml — fant ikke managed: true for dette repoet")
        return
    REPOS_YAML.write_text(new_content)
    print(f"  ✅ repos.yaml — {repo_name} satt til managed: false")


def regenerate_agents() -> None:
    result = run(
        ["python3", "scripts/gen-agents.py", str(REPOS_YAML), str(AGENTS_MD)],
        cwd=Path(__file__).parent.parent,
        check=False,
    )
    if result.returncode == 0:
        print("  ✅ ai/AGENTS.md regenerert")
    else:
        print(f"  ⚠️  gen-agents.py feilet: {result.stderr[:200]}")


def main():
    if not REPO_NAME:
        print("Feil: REPO=<reponavn> er påkrevd")
        print("Bruk: python3 scripts/detach-repo.py REPO=historisk-valutakalkulator [--dry-run]")
        sys.exit(1)

    repo_dir = REPOS_DIR / REPO_NAME
    frontend_dir = repo_dir / "frontend"

    print(f"{'[DRY-RUN] ' if DRY_RUN else ''}🔓 Løsriver {REPO_NAME} fra infotek\n")

    if not repo_dir.exists():
        print(f"  ⚠️  {REPO_NAME} er ikke klonet — kjør 'make clone' først")
        sys.exit(1)

    if DRY_RUN:
        if frontend_dir.exists():
            biome = (frontend_dir / "biome.json").exists()
            pkg = (frontend_dir / "package.json").exists()
            tsconfig = (frontend_dir / "tsconfig.json").exists() or (frontend_dir / "tsconfig.app.json").exists()
            if biome:
                print("  → Vil erstatte biome.json med inline-konfig")
            if tsconfig:
                print("  → Vil erstatte tsconfig.json med inline-konfig")
            if pkg:
                print("  → Vil fjerne @navikt/infotek-frontend-config fra package.json")
        print("  → Vil sette managed: false i repos.yaml")
        print("  → Vil regenerere ai/AGENTS.md")
        return

    # Guard: clean working tree in repo
    status = run(["git", "status", "--porcelain"], cwd=repo_dir)
    if status.stdout.strip():
        print(f"  ⚠️  {REPO_NAME} har uncommitted endringer — commit først")
        sys.exit(1)

    # Get default branch
    branch_result = run(
        ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
        cwd=repo_dir, check=False,
    )
    default_branch = branch_result.stdout.strip().replace("refs/remotes/origin/", "") or "main"

    run(["git", "checkout", default_branch], cwd=repo_dir)
    run(["git", "pull", "--quiet"], cwd=repo_dir)
    detach_branch = "chore/detach-infotek"
    run(["git", "checkout", "-b", detach_branch], cwd=repo_dir, check=False)

    changed = False
    if frontend_dir.exists():
        changed |= detach_biome(frontend_dir)
        changed |= detach_tsconfig(frontend_dir)
        changed |= detach_package_json(frontend_dir)

        if changed:
            print(f"  ⏳ pnpm install...")
            run(
                ["pnpm", "install", "--frozen-lockfile=false"],
                cwd=frontend_dir, check=False,
            )

    if not changed:
        print("  ⏭  Ingen infotek-konfig funnet i repoet")
        run(["git", "checkout", default_branch], cwd=repo_dir)
    else:
        run(["git", "add", "-A"], cwd=repo_dir)
        run(
            ["git", "commit", "-m",
             f"chore: løsriv frå infotek-frontend-config\n\n"
             f"Erstatter extends med inline biome- og tsconfig-konfig.\n"
             f"Fjerner @navikt/infotek-frontend-config som avhengigheit."],
            cwd=repo_dir,
        )
        run(["git", "push", "-u", "origin", detach_branch], cwd=repo_dir)

        result = run(
            [
                "gh", "pr", "create",
                "--title", "chore: løsriv frå @navikt/infotek-frontend-config",
                "--body",
                "Repoet skal overførast til eit anna team.\n\n"
                "**Endringer:**\n"
                "- `biome.json` — erstatta med full inline-konfig\n"
                "- `tsconfig.json` — erstatta med full inline-konfig\n"
                "- Fjerner `@navikt/infotek-frontend-config` som devDependency\n",
                "--base", default_branch,
                "--head", detach_branch,
            ],
            cwd=repo_dir, check=False,
        )
        if result.returncode == 0:
            print(f"  🔗 PR: {result.stdout.strip()}")
        else:
            print(f"  ❌ PR feilet: {result.stderr.strip()}")

    # Update infotek-parent
    print()
    set_managed_false(REPO_NAME)
    regenerate_agents()

    print(f"\nFerdig. Husk å merge PR-en i {REPO_NAME} og overføre repoet til nytt team via GitHub.")


if __name__ == "__main__":
    main()
