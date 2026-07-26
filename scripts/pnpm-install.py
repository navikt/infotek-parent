#!/usr/bin/env python3
"""
Kjører pnpm install i alle frontend-mapper på tvers av repos.

Bruk:
  python3 scripts/pnpm-install.py [--dry-run]
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

DRY_RUN = "--dry-run" in sys.argv
REPOS_DIR = Path(__file__).parent.parent / "repos"


def run_streaming(cmd, cwd=None):
    """Run command and stream output line by line. Returns exit code."""
    env = os.environ.copy()
    env["NODE_NO_WARNINGS"] = "1"
    proc = subprocess.Popen(
        cmd, cwd=cwd, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    for line in proc.stdout:
        print(f"  {line}", end="", flush=True)
    proc.wait()
    return proc.returncode


def find_package_jsons(repo_path):
    results = []
    for p in repo_path.rglob("package.json"):
        parts = p.parts
        if "node_modules" in parts or ".pnpm" in parts:
            continue
        results.append(p.parent)
    return results


def main():
    repos = sorted(d for d in REPOS_DIR.iterdir() if d.is_dir())
    if not repos:
        print("Ingen repos funnet. Kjør 'make git-clone' først.")
        sys.exit(1)

    targets: list[tuple[Path, Path]] = []
    for repo_dir in repos:
        for pkg_dir in find_package_jsons(repo_dir):
            targets.append((repo_dir, pkg_dir))

    if not targets:
        print("Ingen package.json funnet i klonede repos.")
        return

    selected_repo_names: set[str] | None = None
    if sys.stdin.isatty():
        with tempfile.NamedTemporaryFile("w+", delete=False) as tmp:
            for name in sorted({repo_dir.name for repo_dir, _ in targets}):
                tmp.write(f"{name}\n")
            tmp_path = tmp.name
        try:
            selector = subprocess.run(
                [
                    "python3",
                    str(Path(__file__).parent / "select-repos.py"),
                    "--input",
                    tmp_path,
                    "--repos-dir",
                    str(REPOS_DIR),
                    "--default-filter",
                    "a",
                ],
                stdout=subprocess.PIPE,
                text=True,
                check=False,
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)
        picked = [line.strip() for line in selector.stdout.splitlines() if line.strip()]
        if not picked:
            print("Avbrutt.")
            return
        selected_repo_names = set(picked)

    total, ok, failed = 0, 0, 0
    for repo_dir, pkg_dir in targets:
        if selected_repo_names is not None and repo_dir.name not in selected_repo_names:
            continue
        rel = pkg_dir.relative_to(REPOS_DIR)
        total += 1
        print(f"\n{'[DRY-RUN] ' if DRY_RUN else ''}⏳ pnpm install: {rel}", flush=True)
        if DRY_RUN:
            ok += 1
            continue

        rc = run_streaming(["pnpm", "install", "--no-frozen-lockfile"], cwd=pkg_dir)
        if rc == 0:
            print(f"  ✅ OK", flush=True)
            ok += 1
        else:
            print(f"  ❌ Feilet (exit {rc})", flush=True)
            failed += 1

    print(f"\nFerdig: {ok}/{total} OK" + (f", {failed} feilet" if failed else ""))


if __name__ == "__main__":
    main()
