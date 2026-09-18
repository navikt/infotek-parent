import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import observability


class ObservabilityTest(unittest.TestCase):
    def test_parse_repositories_reads_managed_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "repos.yaml"
            path.write_text(
                "repos:\n"
                "  - name: app\n"
                "    namespace: team\n"
                "    default_branch: main\n"
                "    managed: true\n"
                "    environments: [dev-gcp, prod-gcp]\n"
                "    frontend_observability: false\n"
                "    nais_app: workload\n"
                "  - name: unmanaged\n"
                "    namespace: team\n"
                "    managed: false\n"
            )

            self.assertEqual(
                observability.parse_repositories(path),
                [
                    observability.Repository(
                        name="app",
                        namespace="team",
                        default_branch="main",
                        environments=("dev-gcp", "prod-gcp"),
                        frontend_observability=False,
                        nais_app="workload",
                    )
                ],
            )

    def test_remove_elastic_preserves_other_destinations(self):
        content = (
            "spec:\n"
            "  observability:\n"
            "    logging:\n"
            "      destinations:\n"
            "        - id: elastic\n"
            "        - id: loki\n"
            "        - id: team-logs\n"
        )

        updated, changed = observability.remove_elastic_destination(content)

        self.assertTrue(changed)
        self.assertNotIn("elastic", updated)
        self.assertIn("- id: loki", updated)
        self.assertIn("- id: team-logs", updated)

    def test_adds_java_auto_instrumentation_to_existing_observability(self):
        content = (
            "spec:\n"
            "  image: test\n"
            "  observability:\n"
            "    logging:\n"
            "      destinations:\n"
            "        - id: loki\n"
        )

        updated, status = observability.ensure_java_auto_instrumentation(content)

        self.assertEqual(status, "changed")
        self.assertIn("autoInstrumentation:", updated)
        self.assertIn("runtime: java", updated)
        self.assertIn("logging:", updated)

    def test_sdk_runtime_requires_manual_review(self):
        content = (
            "spec:\n"
            "  observability:\n"
            "    autoInstrumentation:\n"
            "      enabled: true\n"
            "      runtime: sdk\n"
        )

        updated, status = observability.ensure_java_auto_instrumentation(content)

        self.assertEqual(updated, content)
        self.assertEqual(status, "runtime:sdk")

    def test_frontend_initialization_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            frontend = Path(directory)
            package_path = frontend / "package.json"
            source = frontend / "src"
            source.mkdir()
            entrypoint = source / "main.tsx"
            package_path.write_text(
                json.dumps(
                    {
                        "dependencies": {"react": "19.0.0"},
                        "devDependencies": {"vite": "7.0.0", "vitest": "3.0.0"},
                    },
                    indent=2,
                )
                + "\n"
            )
            entrypoint.write_text(
                'import { createRoot } from "react-dom/client";\n\n'
                'createRoot(document.getElementById("root")!).render(null);\n'
            )
            repository = observability.Repository(
                "example",
                "team",
                "main",
                ("dev-gcp",),
            )
            first = observability.Result(repository.name)
            second = observability.Result(repository.name)

            observability.ensure_apm_dependency(package_path, True, first)
            observability.ensure_npmrc(frontend, True, first)
            observability.ensure_frontend_initialization(
                package_path, repository, True, first
            )
            snapshot = {
                path.relative_to(frontend): path.read_text()
                for path in frontend.rglob("*")
                if path.is_file()
            }

            dependency_changed = observability.ensure_apm_dependency(
                package_path, True, second
            )
            npmrc_changed = observability.ensure_npmrc(frontend, True, second)
            source_changed = observability.ensure_frontend_initialization(
                package_path, repository, True, second
            )
            repeated = {
                path.relative_to(frontend): path.read_text()
                for path in frontend.rglob("*")
                if path.is_file()
            }

            self.assertFalse(dependency_changed)
            self.assertFalse(npmrc_changed)
            self.assertFalse(source_changed)
            self.assertEqual(repeated, snapshot)
            self.assertEqual(
                json.loads(package_path.read_text())["dependencies"]["@nais/apm"],
                observability.APM_VERSION,
            )
            self.assertIn(
                "init();",
                (source / "observability.ts").read_text(),
            )

    def test_process_repository_ignores_disabled_frontend(self):
        with tempfile.TemporaryDirectory() as directory:
            repos_dir = Path(directory)
            repo_dir = self.create_git_repository(repos_dir, "example")
            frontend = repo_dir / "frontend"
            (frontend / "src").mkdir(parents=True)
            (frontend / "package.json").write_text(
                json.dumps(
                    {
                        "dependencies": {"react": "19.0.0"},
                        "devDependencies": {"vite": "7.0.0"},
                    }
                )
            )
            (frontend / "src" / "main.tsx").write_text("export {};\n")
            repository = observability.Repository(
                "example",
                "team",
                "main",
                ("dev-fss", "dev-gcp"),
                frontend_observability=False,
            )

            result = observability.process_repository(
                repository,
                apply=False,
                update_lockfiles=False,
                repos_dir=repos_dir,
            )

            self.assertEqual(result.status, "compliant")
            self.assertEqual(result.changes, [])
            self.assertIn(
                "frontend-observability er eksplisitt deaktivert",
                result.warnings,
            )

    def test_process_repository_reports_missing_clone(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = observability.Repository(
                "missing",
                "team",
                "main",
                ("dev-gcp",),
            )

            result = observability.process_repository(
                repository,
                apply=False,
                update_lockfiles=False,
                repos_dir=Path(directory),
            )

            self.assertEqual(result.status, "blocked")
            self.assertIn("mangler lokal arbeidskopi", result.warnings[0])

    def test_process_repository_updates_manifest_once(self):
        with tempfile.TemporaryDirectory() as directory:
            repos_dir = Path(directory)
            repo_dir = self.create_git_repository(repos_dir, "example")
            (repo_dir / "pom.xml").write_text("<project/>\n")
            nais_dir = repo_dir / ".nais"
            nais_dir.mkdir()
            manifest = nais_dir / "app.yaml"
            manifest.write_text(
                "apiVersion: nais.io/v1alpha1\n"
                "kind: Application\n"
                "metadata:\n"
                "  name: example\n"
                "spec:\n"
                "  image: test\n"
                "  observability:\n"
                "    logging:\n"
                "      destinations:\n"
                "        - id: elastic\n"
                "        - id: loki\n"
            )
            self.commit_all(repo_dir)
            subprocess.run(
                ["git", "switch", "-c", "chore/observability"],
                cwd=repo_dir,
                check=True,
                capture_output=True,
            )
            repository = observability.Repository(
                "example",
                "team",
                "main",
                ("dev-gcp",),
            )

            first = observability.process_repository(
                repository,
                apply=True,
                update_lockfiles=False,
                repos_dir=repos_dir,
            )
            updated = manifest.read_text()
            self.commit_all(repo_dir)
            second = observability.process_repository(
                repository,
                apply=True,
                update_lockfiles=False,
                repos_dir=repos_dir,
            )

            self.assertEqual(first.status, "changes-needed")
            self.assertNotIn("elastic", updated)
            self.assertEqual(updated.count("autoInstrumentation:"), 1)
            self.assertEqual(second.status, "compliant")
            self.assertEqual(second.changes, [])

    def test_apply_blocks_default_branch(self):
        with tempfile.TemporaryDirectory() as directory:
            repos_dir = Path(directory)
            repo_dir = self.create_git_repository(repos_dir, "example")
            (repo_dir / "pom.xml").write_text("<project/>\n")
            self.commit_all(repo_dir)
            repository = observability.Repository(
                "example",
                "team",
                "main",
                ("dev-gcp",),
            )

            result = observability.process_repository(
                repository,
                apply=True,
                update_lockfiles=False,
                repos_dir=repos_dir,
            )

            self.assertEqual(result.status, "blocked")
            self.assertIn("opprett en feature-branch", result.warnings[0])

    @staticmethod
    def create_git_repository(repos_dir: Path, name: str) -> Path:
        repo_dir = repos_dir / name
        repo_dir.mkdir()
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=repo_dir,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repo_dir,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=repo_dir,
            check=True,
        )
        return repo_dir

    @staticmethod
    def commit_all(repo_dir: Path) -> None:
        subprocess.run(["git", "add", "-A"], cwd=repo_dir, check=True)
        subprocess.run(
            ["git", "commit", "-m", "test"],
            cwd=repo_dir,
            check=True,
            capture_output=True,
        )


if __name__ == "__main__":
    unittest.main()
