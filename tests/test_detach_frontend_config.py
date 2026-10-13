import importlib.util
from contextlib import redirect_stdout
from io import StringIO
import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT = Path(__file__).parent.parent / "scripts" / "detach-frontend-config.py"
SPEC = importlib.util.spec_from_file_location("detach_frontend_config", SCRIPT)
detach = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = detach
SPEC.loader.exec_module(detach)


class DetachFrontendTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).parent / ".detach_frontend_testdata" / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / "repos").mkdir()
        base = self.root / "platform/pnpm"
        base.mkdir(parents=True)
        source = SCRIPT.parent.parent / "platform/pnpm"
        for name in ("tsconfig.base.json", "biome.base.json"):
            shutil.copyfile(source / name, base / name)
        self.ts_base = json.loads((base / "tsconfig.base.json").read_text())
        self.biome_base = json.loads((base / "biome.base.json").read_text())
        (self.root / "repos.yaml").write_text(
            "repos:\n"
            "  - name: app\n    managed: true\n"
            "  - name: nested\n    managed: true\n"
            "  - name: independent\n    managed: true\n"
            "  - name: excluded\n    managed: false\n"
        )
        self.root_patch = patch.object(detach, "ROOT", self.root)
        self.repos_patch = patch.object(detach, "REPOS", self.root / "repos")
        self.root_patch.start()
        self.repos_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.addCleanup(self.repos_patch.stop)

    def frontend(self, name="app", nested=False):
        folder = "backend-for-frontend/frontend" if nested else "frontend"
        frontend = self.root / "repos" / name / folder
        frontend.mkdir(parents=True)
        (frontend / "package.json").write_text(json.dumps({
            "name": name,
            "scripts": {"build": "vite build"},
            "devDependencies": {detach.PACKAGE: "^1.2.0", "@biomejs/biome": "2.5.12"},
        }) + "\n")
        (frontend / "biome.json").write_text(json.dumps({
            "extends": [detach.PACKAGE + "/biome.base.json"],
            "formatter": {"indentWidth": 4},
        }) + "\n")
        (frontend / "tsconfig.json").write_text(json.dumps({
            "extends": detach.PACKAGE + "/tsconfig.base.json",
            "compilerOptions": {"target": "ES2022", "types": ["vite/client"]},
            "include": ["src"],
        }) + "\n")
        (frontend / "pnpm-workspace.yaml").write_text(
            "allowBuilds:\n  esbuild: true\nminimumReleaseAgeExclude:\n"
            "  - '@navikt/infotek-frontend-config'\n"
        )
        (frontend / ".npmrc").write_text(
            "@navikt/infotek-frontend-config:registry=https://npm.pkg.github.com/\n"
            "@nais:registry=https://npm.pkg.github.com/\n"
        )
        (frontend / "pnpm-lock.yaml").write_text(f"lockfileVersion: 9\n{detach.PACKAGE}\n")
        return frontend

    def test_multiselect_and_invalid_selections(self):
        self.assertEqual(detach.choose_repos(["app", "nested"], "2, 1,2"), ["nested", "app"])
        for choice in ("", "0", "3", "1; echo foo", "1,", "../app"):
            with self.subTest(choice=choice), self.assertRaises(ValueError):
                detach.choose_repos(["app", "nested"], choice)

    def test_uses_current_parent_base_and_preserves_local_overrides(self):
        frontend = self.frontend()
        biome_path = frontend / "biome.json"
        local_biome = json.loads(biome_path.read_text())
        local_biome["files"] = {"includes": ["!playwright-report", "!test-results"]}
        biome_path.write_text(json.dumps(local_biome))
        changes, install = detach.planned_files(frontend, self.ts_base, self.biome_base)
        self.assertTrue(install)
        biome = json.loads(changes[frontend / "biome.json"])
        ts = json.loads(changes[frontend / "tsconfig.json"])
        self.assertEqual(biome["$schema"], self.biome_base["$schema"])
        self.assertEqual(biome["formatter"]["lineWidth"], self.biome_base["formatter"]["lineWidth"])
        self.assertEqual(biome["formatter"]["indentWidth"], 4)
        self.assertIn("!**/*.gen.ts", biome["files"]["includes"])
        self.assertIn("!test-results", biome["files"]["includes"])
        self.assertEqual(ts["compilerOptions"]["target"], "ES2022")
        self.assertEqual(ts["compilerOptions"]["strict"], self.ts_base["compilerOptions"]["strict"])
        self.assertEqual(ts["include"], ["src"])
        self.assertNotIn("extends", ts)
        self.assertNotIn(
            detach.PACKAGE,
            b"".join(content for path, content in changes.items() if path.name != "pnpm-lock.yaml").decode(),
        )
        self.assertIn("@nais:registry=", changes[frontend / ".npmrc"].decode())

    def test_nested_frontend_and_already_independent_repo(self):
        nested = self.frontend("nested", nested=True)
        self.assertEqual(detach.frontend_for(nested.parent.parent), nested)
        standalone = self.root / "repos/independent/frontend"
        standalone.mkdir(parents=True)
        (standalone / "package.json").write_text('{"name":"independent"}\n')
        changes, install = detach.planned_files(standalone, self.ts_base, self.biome_base)
        self.assertEqual(changes, {})
        self.assertFalse(install)

    def test_dry_run_and_unmanaged_are_side_effect_free(self):
        frontend = self.frontend()
        original = {path.name: path.read_bytes() for path in frontend.iterdir()}
        output = StringIO()
        with patch.object(detach, "assert_clean"), patch.object(detach, "apply_changes") as apply:
            with redirect_stdout(output):
                self.assertEqual(detach.main(["--repo", "app", "--dry-run"]), 0)
            self.assertEqual(detach.main(["--repo", "excluded", "--yes"]), 1)
            self.assertEqual(detach.main(["--repo", "../app", "--yes"]), 1)
            apply.assert_not_called()
        self.assertIn("regenererer pnpm-lock.yaml", output.getvalue())
        self.assertIn("pnpm run build", output.getvalue())
        self.assertEqual({path.name: path.read_bytes() for path in frontend.iterdir()}, original)

    def test_menu_selects_multiple_and_preflights_before_writing(self):
        self.frontend()
        self.frontend("nested", nested=True)
        with patch.object(detach.sys, "stdin", SimpleNamespace(isatty=lambda: True)), \
             patch("builtins.input", side_effect=["2,1", "j"]), \
             patch.object(detach, "assert_clean"), \
             patch.object(detach, "apply_changes", return_value=({}, None)) as apply:
            self.assertEqual(detach.main([]), 0)
            self.assertEqual(apply.call_count, 2)
        with patch.object(detach, "assert_clean", side_effect=[None, ValueError("urent")]), \
             patch.object(detach, "apply_changes") as apply:
            self.assertEqual(detach.main(["--repo", "app", "--repo", "nested", "--yes"]), 1)
            apply.assert_not_called()

    def test_failed_install_restores_all_frontend_files(self):
        frontend = self.frontend()
        originals = {path.name: path.read_bytes() for path in frontend.iterdir()}
        changes, install = detach.planned_files(frontend, self.ts_base, self.biome_base)

        def failed_install(*args, **kwargs):
            (frontend / "pnpm-lock.yaml").write_text("partial lockfile\n")
            raise detach.subprocess.CalledProcessError(1, args[0])

        with patch.object(detach.subprocess, "run", side_effect=failed_install):
            with self.assertRaises(detach.subprocess.CalledProcessError):
                detach.apply_changes(frontend, changes, install)
        self.assertEqual({path.name: path.read_bytes() for path in frontend.iterdir()}, originals)
        self.assertIn("managed: true", (self.root / "repos.yaml").read_text())

    def test_failed_build_restores_lockfiles_and_previous_node_modules(self):
        frontend = self.frontend()
        (frontend / "package-lock.json").write_text("old npm lock\n")
        modules = frontend / "node_modules"
        modules.mkdir()
        (modules / "old").write_text("previous install")
        originals = {path.name: path.read_bytes() for path in frontend.iterdir() if path.is_file()}
        changes, install = detach.planned_files(frontend, self.ts_base, self.biome_base)

        def run(command, **kwargs):
            if "--no-frozen-lockfile" in command:
                (frontend / "pnpm-lock.yaml").write_text("new lockfile\n")
                modules.mkdir()
                (modules / "new").write_text("new install")
            if command == ["pnpm", "run", "build"]:
                raise detach.subprocess.CalledProcessError(1, command)
            return SimpleNamespace(returncode=0)

        with patch.object(detach.subprocess, "run", side_effect=run):
            with self.assertRaises(detach.subprocess.CalledProcessError):
                detach.apply_changes(frontend, changes, install)
        self.assertEqual({path.name: path.read_bytes() for path in frontend.iterdir() if path.is_file()}, originals)
        self.assertEqual((modules / "old").read_text(), "previous install")
        self.assertFalse((modules / "new").exists())
        self.assertEqual(list(frontend.glob(".node_modules-detach-backup-*")), [])

    def test_success_updates_lockfile_without_touching_other_repos_or_metadata(self):
        frontend = self.frontend()
        (frontend / "package-lock.json").write_text("obsolete\n")
        modules = frontend / "node_modules"
        modules.mkdir()
        (modules / "old").write_text("stale")
        other = self.frontend("nested", nested=True)
        untouched = {path.name: path.read_bytes() for path in other.iterdir()}
        metadata = (self.root / "repos.yaml").read_bytes()
        calls = []

        def install(command, **kwargs):
            calls.append(command)
            if "--no-frozen-lockfile" in command:
                (frontend / "pnpm-lock.yaml").write_text("lockfileVersion: 9\n")
                modules.mkdir()
                (modules / "new").write_text("fresh")
            return SimpleNamespace(returncode=0)

        with patch.object(detach, "assert_clean"), patch.object(detach.subprocess, "run", side_effect=install):
            self.assertEqual(detach.main(["--repo", "app", "--yes"]), 0)

        self.assertEqual(
            calls,
            [
                ["pnpm", "install", "--ignore-scripts", "--no-frozen-lockfile"],
                ["pnpm", "install", "--ignore-scripts", "--frozen-lockfile"],
                ["pnpm", "run", "build"],
            ],
        )
        self.assertEqual(json.loads((frontend / "biome.json").read_text())["formatter"]["indentWidth"], 4)
        self.assertNotIn(detach.PACKAGE, (frontend / "pnpm-lock.yaml").read_text())
        self.assertFalse((frontend / "package-lock.json").exists())
        self.assertFalse((modules / "old").exists())
        self.assertEqual((modules / "new").read_text(), "fresh")
        self.assertEqual(list(frontend.glob(".node_modules-detach-backup-*")), [])
        self.assertEqual({path.name: path.read_bytes() for path in other.iterdir()}, untouched)
        self.assertEqual((self.root / "repos.yaml").read_bytes(), metadata)

    def test_second_repo_failure_restores_first_repo(self):
        frontend = self.frontend()
        self.frontend("nested", nested=True)
        before = {path.name: path.read_bytes() for path in frontend.iterdir()}
        attempts = []

        def apply(folder, changes, needs_install):
            attempts.append(folder)
            if len(attempts) == 2:
                raise ValueError("install feilet")
            snapshots = {path: path.read_bytes() for path in changes}
            (folder / "package.json").write_text("{}")
            return snapshots, None

        with patch.object(detach, "assert_clean"), patch.object(detach, "apply_changes", side_effect=apply):
            self.assertEqual(detach.main(["--repo", "app", "--repo", "nested", "--yes"]), 1)
        self.assertEqual({path.name: path.read_bytes() for path in frontend.iterdir()}, before)

    def test_second_build_failure_restores_both_repos_and_installations(self):
        first = self.frontend()
        second = self.frontend("nested", nested=True)
        originals = {}
        for frontend in (first, second):
            (frontend / "package-lock.json").write_text("old npm lock\n")
            modules = frontend / "node_modules"
            modules.mkdir()
            (modules / "old").write_text("previous install")
            originals[frontend] = {path.name: path.read_bytes() for path in frontend.iterdir() if path.is_file()}

        def run(command, **kwargs):
            frontend = kwargs["cwd"]
            if "--no-frozen-lockfile" in command:
                (frontend / "pnpm-lock.yaml").write_text("fresh lock\n")
                (frontend / "node_modules").mkdir()
            if command == ["pnpm", "run", "build"] and frontend == second:
                raise detach.subprocess.CalledProcessError(1, command)
            return SimpleNamespace(returncode=0)

        with patch.object(detach, "assert_clean"), patch.object(detach.subprocess, "run", side_effect=run):
            self.assertEqual(detach.main(["--repo", "app", "--repo", "nested", "--yes"]), 1)

        for frontend in (first, second):
            self.assertEqual(
                {path.name: path.read_bytes() for path in frontend.iterdir() if path.is_file()},
                originals[frontend],
            )
            self.assertEqual((frontend / "node_modules/old").read_text(), "previous install")
            self.assertEqual(list(frontend.glob(".node_modules-detach-backup-*")), [])

    def test_pnpm_version_mismatch_changes_nothing(self):
        frontend = self.frontend()
        package = json.loads((frontend / "package.json").read_text())
        package["packageManager"] = "pnpm@10.33.0"
        (frontend / "package.json").write_text(json.dumps(package))
        modules = frontend / "node_modules"
        modules.mkdir()
        (modules / "old").write_text("keep")
        before = {path.name: path.read_bytes() for path in frontend.iterdir() if path.is_file()}
        changes, install = detach.planned_files(frontend, self.ts_base, self.biome_base)
        with patch.object(detach.subprocess, "run", return_value=SimpleNamespace(stdout="11.5.1\n")) as pnpm:
            with self.assertRaisesRegex(ValueError, "forventet pnpm 10.33.0"):
                detach.apply_changes(frontend, changes, install)
        pnpm.assert_called_once()
        self.assertEqual({path.name: path.read_bytes() for path in frontend.iterdir() if path.is_file()}, before)
        self.assertEqual((modules / "old").read_text(), "keep")

    def test_unexpected_config_reference_stops_before_editing(self):
        frontend = self.frontend()
        (frontend / "tsconfig.node.json").write_text(json.dumps({
            "extends": [detach.PACKAGE + "/tsconfig.base.json", "./local.json"],
        }))
        originals = {path.name: path.read_bytes() for path in frontend.iterdir()}
        with patch.object(detach, "assert_clean"), patch.object(detach, "apply_changes") as apply:
            self.assertEqual(detach.main(["--repo", "app", "--yes"]), 1)
            apply.assert_not_called()
        self.assertEqual({path.name: path.read_bytes() for path in frontend.iterdir()}, originals)

    def test_dirty_repo_rejected(self):
        repo = self.root / "repos/app"
        repo.mkdir()
        with patch.object(detach.subprocess, "run", return_value=type("Result", (), {"stdout": " M frontend/package.json"})()):
            with self.assertRaisesRegex(ValueError, "lokale endringer"):
                detach.assert_clean(repo)

    def test_symlinked_config_is_rejected_before_read(self):
        frontend = self.frontend()
        (frontend / "tsconfig.json").unlink()
        (frontend / "tsconfig.json").symlink_to(self.root / "platform/pnpm/tsconfig.base.json")
        with self.assertRaisesRegex(ValueError, "peker utenfor"):
            detach.planned_files(frontend, self.ts_base, self.biome_base)


if __name__ == "__main__":
    unittest.main()
