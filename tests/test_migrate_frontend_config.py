import importlib.util
import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parent.parent / "scripts" / "migrate-frontend-config.py"
SPEC = importlib.util.spec_from_file_location("migrate_frontend_config", SCRIPT)
migrate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = migrate
SPEC.loader.exec_module(migrate)

TSCONFIG_BASE = {
    "compilerOptions": {
        "target": "ES2020",
        "strict": True,
        "noEmit": True,
    },
    "exclude": ["node_modules", "dist"],
}
BIOME_BASE = {
    "$schema": "https://biomejs.dev/schemas/2.5.4/schema.json",
    "formatter": {"enabled": True, "indentWidth": 2},
}
REPO_CONFIG = {
    "tsconfig_new": {
        "extends": "@navikt/infotek-frontend-config/tsconfig.base.json",
        "compilerOptions": {
            "target": "ES2022",
            "types": ["vite/client"],
        },
        "include": ["src"],
    }
}


class ScratchTestCase(unittest.TestCase):
    def scratch_root(self) -> Path:
        root = Path(__file__).parent / ".migrate_frontend_config_testdata" / uuid.uuid4().hex
        root.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        return root


class BaseConfigTest(ScratchTestCase):
    def test_loads_explicit_base_configs(self):
        root = self.scratch_root()
        tsconfig = root / "tsconfig.json"
        biome = root / "biome.json"
        tsconfig.write_text(json.dumps(TSCONFIG_BASE))
        biome.write_text(json.dumps(BIOME_BASE))

        self.assertEqual(migrate.load_base_configs(tsconfig, biome), (TSCONFIG_BASE, BIOME_BASE))

    def test_merges_repo_specific_tsconfig_without_extends(self):
        merged = migrate.merge_tsconfig(TSCONFIG_BASE, REPO_CONFIG["tsconfig_new"])

        self.assertNotIn("extends", merged)
        self.assertEqual(merged["compilerOptions"]["strict"], True)
        self.assertEqual(merged["compilerOptions"]["target"], "ES2022")
        self.assertEqual(merged["compilerOptions"]["types"], ["vite/client"])
        self.assertEqual(merged["include"], ["src"])


class RepoSelectionTest(ScratchTestCase):
    def test_filters_managed_repos_and_exact_repo_name(self):
        repos_yaml = self.scratch_root() / "repos.yaml"
        repos_yaml.write_text(
            "repos:\n"
            "  - name: historisk-pensjon\n"
            "    managed: true\n"
            "  - name: historisk-riddler\n"
            "    managed: false\n"
            "  - name: historisk-valutakalkulator\n"
            "    managed: true\n"
        )

        managed = migrate.load_managed_repo_names(repos_yaml)
        configs = {
            "historisk-pensjon": {},
            "historisk-riddler": {},
            "historisk-valutakalkulator": {},
        }

        self.assertEqual(managed, {"historisk-pensjon", "historisk-valutakalkulator"})
        self.assertEqual(
            list(migrate.select_repositories(configs, managed, "historisk-pensjon")),
            ["historisk-pensjon"],
        )
        self.assertEqual(migrate.select_repositories(configs, managed, "pensjon"), {})


class MigrationTest(ScratchTestCase):
    def create_frontend(self) -> tuple[Path, Path]:
        root = self.scratch_root()
        repo_dir = root / "repos" / "historisk-pensjon"
        frontend = repo_dir / "frontend"
        frontend.mkdir(parents=True)
        (frontend / "package.json").write_text(
            json.dumps(
                {
                    "name": "historisk-pensjon",
                    "devDependencies": {
                        "@biomejs/biome": "2.5.4",
                        "@navikt/infotek-frontend-config": "^1.2.0",
                    },
                },
                indent=2,
            )
            + "\n"
        )
        (frontend / "biome.json").write_text(
            json.dumps({"extends": ["@navikt/infotek-frontend-config/biome.base.json"]}, indent=2) + "\n"
        )
        (frontend / "tsconfig.json").write_text(json.dumps(REPO_CONFIG["tsconfig_new"], indent=2) + "\n")
        (frontend / "pnpm-lock.yaml").write_text("lockfileVersion: 9\nold: true\n")
        (frontend / ".npmrc").write_text(
            "@navikt:registry=https://registry.npmjs.org/\n"
            "@navikt/infotek-frontend-config:registry=https://npm.pkg.github.com/\n"
        )
        return root, frontend

    def test_removes_package_and_writes_explicit_config(self):
        root, frontend = self.create_frontend()

        def successful_install(cwd: Path, timeout_seconds: int):
            (cwd / "pnpm-lock.yaml").write_text("lockfileVersion: 9\n")
            return migrate.CommandResult(0, "install ok\n", "")

        with patch.object(migrate, "run_pnpm_install", side_effect=successful_install):
            ok = migrate.migrate_repo(
                "historisk-pensjon",
                REPO_CONFIG,
                repos_dir=root / "repos",
                tsconfig_base=TSCONFIG_BASE,
                biome_base=BIOME_BASE,
                install_timeout_seconds=3,
            )

        self.assertTrue(ok)
        package_json = json.loads((frontend / "package.json").read_text())
        self.assertNotIn(migrate.PACKAGE_NAME, package_json["devDependencies"])
        self.assertEqual(json.loads((frontend / "biome.json").read_text()), BIOME_BASE)
        self.assertEqual(
            json.loads((frontend / "tsconfig.json").read_text()),
            migrate.merge_tsconfig(TSCONFIG_BASE, REPO_CONFIG["tsconfig_new"]),
        )
        npmrc = (frontend / ".npmrc").read_text()
        self.assertIn("@navikt:registry=https://npm.pkg.github.com/", npmrc)
        self.assertIn("@nais:registry=https://npm.pkg.github.com/", npmrc)
        self.assertIn("registry=https://registry.npmjs.org/", npmrc)
        self.assertNotIn(migrate.PACKAGE_NAME, npmrc)

    def test_rolls_back_all_files_when_install_fails(self):
        root, frontend = self.create_frontend()
        originals = {path.name: path.read_bytes() for path in frontend.iterdir()}

        with patch.object(
            migrate,
            "run_pnpm_install",
            return_value=migrate.CommandResult(1, "install output\n", "package unavailable"),
        ):
            ok = migrate.migrate_repo(
                "historisk-pensjon",
                REPO_CONFIG,
                repos_dir=root / "repos",
                tsconfig_base=TSCONFIG_BASE,
                biome_base=BIOME_BASE,
                install_timeout_seconds=3,
            )

        self.assertFalse(ok)
        self.assertEqual({path.name: path.read_bytes() for path in frontend.iterdir()}, originals)

    def test_already_explicit_repo_does_not_run_install(self):
        root, frontend = self.create_frontend()
        package_json = json.loads((frontend / "package.json").read_text())
        del package_json["devDependencies"][migrate.PACKAGE_NAME]
        (frontend / "package.json").write_text(json.dumps(package_json, indent=2) + "\n")
        (frontend / "biome.json").write_text(json.dumps(BIOME_BASE, indent=2) + "\n")
        explicit_tsconfig = migrate.merge_tsconfig(TSCONFIG_BASE, REPO_CONFIG["tsconfig_new"])
        (frontend / "tsconfig.json").write_text(json.dumps(explicit_tsconfig, indent=2) + "\n")
        (frontend / ".npmrc").write_text(
            "@navikt:registry=https://npm.pkg.github.com/\n"
            "@nais:registry=https://npm.pkg.github.com/\n"
            "registry=https://registry.npmjs.org/\n"
        )

        with patch.object(migrate, "run_pnpm_install") as mocked_install:
            ok = migrate.migrate_repo(
                "historisk-pensjon",
                REPO_CONFIG,
                repos_dir=root / "repos",
                tsconfig_base=TSCONFIG_BASE,
                biome_base=BIOME_BASE,
                dry_run=True,
            )

        self.assertTrue(ok)
        mocked_install.assert_not_called()

    def test_workspace_overrides_preserve_existing_settings(self):
        root = self.scratch_root()
        workspace = root / "pnpm-workspace.yaml"
        workspace.write_text(
            "allowBuilds:\n"
            "  esbuild: true\n"
            "\n"
            "minimumReleaseAge: 10080\n"
        )

        migrate._write_pnpm_workspace(workspace, {"semver": "7.8.1"})

        self.assertEqual(
            workspace.read_text(),
            "allowBuilds:\n"
            "  esbuild: true\n"
            "\n"
            "minimumReleaseAge: 10080\n"
            "\n"
            "overrides:\n"
            '  "semver": "7.8.1"\n',
        )


if __name__ == "__main__":
    unittest.main()
