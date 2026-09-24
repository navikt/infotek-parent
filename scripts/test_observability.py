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
                'init({ namespace: "team", tracing: true });',
                (source / "observability.ts").read_text(),
            )

    def test_frontend_initialization_generates_namespace_from_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            frontend = Path(directory)
            source = frontend / "src"
            source.mkdir()
            entrypoint = source / "main.tsx"
            package_path = frontend / "package.json"
            package_path.write_text(json.dumps({}) + "\n")
            entrypoint.write_text(
                'import { createRoot } from "react-dom/client";\n\n'
                'createRoot(document.getElementById("root")!).render(null);\n'
            )
            repository = observability.Repository(
                "example",
                "infotrygd",
                "main",
                ("dev-gcp",),
            )
            result = observability.Result(repository.name)

            observability.ensure_frontend_initialization(
                package_path, repository, True, result
            )

            module_content = (source / "observability.ts").read_text()
            test_content = (source / "observability.test.ts").read_text()
            self.assertIn(
                'init({ namespace: "infotrygd", tracing: true });', module_content
            )
            self.assertIn(
                'toHaveBeenCalledWith({ namespace: "infotrygd", tracing: true });',
                test_content,
            )

    def test_frontend_initialization_flags_missing_namespace_for_review(self):
        with tempfile.TemporaryDirectory() as directory:
            frontend = Path(directory)
            source = frontend / "src"
            source.mkdir()
            entrypoint = source / "main.tsx"
            package_path = frontend / "package.json"
            package_path.write_text(json.dumps({}) + "\n")
            entrypoint.write_text(
                'import { createRoot } from "react-dom/client";\n\n'
                'createRoot(document.getElementById("root")!).render(null);\n'
            )
            (source / "observability.ts").write_text(
                'import { init } from "@nais/apm";\n\n'
                "export function initializeObservability() {\n"
                "    init();\n"
                "}\n"
            )
            repository = observability.Repository(
                "example",
                "infotrygd",
                "main",
                ("dev-gcp",),
            )
            result = observability.Result(repository.name)

            observability.ensure_frontend_initialization(
                package_path, repository, True, result
            )

            self.assertTrue(
                any("mangler namespace" in warning for warning in result.warnings)
            )

    def test_ensure_npmrc_normalizes_trailing_slash_and_old_token_var(self):
        with tempfile.TemporaryDirectory() as directory:
            frontend = Path(directory)
            npmrc = frontend / ".npmrc"
            npmrc.write_text(
                "@nais:registry=https://npm.pkg.github.com\n"
                "//npm.pkg.github.com/:_authToken=${NPM_TOKEN}\n"
            )
            result = observability.Result("example")

            changed = observability.ensure_npmrc(frontend, True, result)

            content = npmrc.read_text()
            self.assertTrue(changed)
            self.assertIn("@nais:registry=https://npm.pkg.github.com/\n", content)
            self.assertIn(
                "//npm.pkg.github.com/:_authToken=${NODE_AUTH_TOKEN}\n", content
            )
            self.assertNotIn("NPM_TOKEN}", content)

            second_result = observability.Result("example")
            unchanged = observability.ensure_npmrc(frontend, True, second_result)
            self.assertFalse(unchanged)

    def test_workflow_token_check_accepts_node_auth_token(self):
        with tempfile.TemporaryDirectory() as directory:
            repo_dir = Path(directory)
            frontend = repo_dir / "frontend"
            workflows = repo_dir / ".github" / "workflows"
            frontend.mkdir()
            workflows.mkdir(parents=True)
            (frontend / ".npmrc").write_text(
                "//npm.pkg.github.com/:_authToken=${NODE_AUTH_TOKEN}\n"
            )
            (workflows / "test.yml").write_text(
                "jobs:\n"
                "  test:\n"
                "    steps:\n"
                "      - run: pnpm install --frozen-lockfile\n"
                "        env:\n"
                "          NODE_AUTH_TOKEN: ${{ secrets.READER_TOKEN }}\n"
            )
            result = observability.Result("example")

            observability.ensure_workflow_node_auth_token(frontend, repo_dir, result)

            self.assertEqual(result.warnings, [])

    def test_workflow_token_check_accepts_composite_action_input(self):
        with tempfile.TemporaryDirectory() as directory:
            repo_dir = Path(directory)
            frontend = repo_dir / "frontend"
            workflows = repo_dir / ".github" / "workflows"
            frontend.mkdir()
            workflows.mkdir(parents=True)
            (frontend / ".npmrc").write_text(
                "//npm.pkg.github.com/:_authToken=${NODE_AUTH_TOKEN}\n"
            )
            (workflows / "test.yml").write_text(
                "jobs:\n"
                "  test:\n"
                "    steps:\n"
                "      - uses: ./.github/actions/setup\n"
                "        with:\n"
                "          node-auth-token: ${{ secrets.READER_TOKEN }}\n"
                "      - run: pnpm install --frozen-lockfile\n"
            )
            result = observability.Result("example")

            observability.ensure_workflow_node_auth_token(frontend, repo_dir, result)

            self.assertEqual(result.warnings, [])

    def test_workflow_token_check_reports_missing_token_for_composite_action(self):
        with tempfile.TemporaryDirectory() as directory:
            repo_dir = Path(directory)
            frontend = repo_dir / "frontend"
            workflows = repo_dir / ".github" / "workflows"
            action = repo_dir / ".github" / "actions" / "setup"
            frontend.mkdir()
            workflows.mkdir(parents=True)
            action.mkdir(parents=True)
            (frontend / ".npmrc").write_text(
                "//npm.pkg.github.com/:_authToken=${NODE_AUTH_TOKEN}\n"
            )
            (action / "action.yml").write_text(
                "runs:\n"
                "  using: composite\n"
                "  steps:\n"
                "    - run: pnpm install --frozen-lockfile\n"
                "      shell: bash\n"
            )
            (workflows / "test.yml").write_text(
                "jobs:\n"
                "  test:\n"
                "    steps:\n"
                "      - uses: ./.github/actions/setup\n"
            )
            result = observability.Result("example")

            observability.ensure_workflow_node_auth_token(frontend, repo_dir, result)

            self.assertEqual(
                result.warnings,
                [".github/workflows/test.yml: npm/pnpm/yarn mangler NODE_AUTH_TOKEN"],
            )

    def test_workflow_token_check_accepts_token_for_composite_action(self):
        with tempfile.TemporaryDirectory() as directory:
            repo_dir = Path(directory)
            frontend = repo_dir / "frontend"
            workflows = repo_dir / ".github" / "workflows"
            action = repo_dir / ".github" / "actions" / "setup"
            frontend.mkdir()
            workflows.mkdir(parents=True)
            action.mkdir(parents=True)
            (frontend / ".npmrc").write_text(
                "//npm.pkg.github.com/:_authToken=${NODE_AUTH_TOKEN}\n"
            )
            (action / "action.yml").write_text(
                "runs:\n"
                "  using: composite\n"
                "  steps:\n"
                "    - run: pnpm install --frozen-lockfile\n"
                "      shell: bash\n"
            )
            (workflows / "test.yml").write_text(
                "jobs:\n"
                "  test:\n"
                "    steps:\n"
                "      - uses: ./.github/actions/setup\n"
                "        with:\n"
                "          node-auth-token: ${{ secrets.READER_TOKEN }}\n"
            )
            result = observability.Result("example")

            observability.ensure_workflow_node_auth_token(frontend, repo_dir, result)

            self.assertEqual(result.warnings, [])

    def test_workflow_token_check_reports_missing_token_without_value(self):
        with tempfile.TemporaryDirectory() as directory:
            repo_dir = Path(directory)
            frontend = repo_dir / "frontend"
            workflows = repo_dir / ".github" / "workflows"
            frontend.mkdir()
            workflows.mkdir(parents=True)
            (frontend / ".npmrc").write_text(
                "//npm.pkg.github.com/:_authToken=${NODE_AUTH_TOKEN}\n"
            )
            (workflows / "test.yml").write_text(
                "jobs:\n"
                "  test:\n"
                "    steps:\n"
                "      - run: pnpm install --frozen-lockfile\n"
            )
            result = observability.Result("example")

            observability.ensure_workflow_node_auth_token(frontend, repo_dir, result)

            self.assertEqual(
                result.warnings,
                [".github/workflows/test.yml: npm/pnpm/yarn mangler NODE_AUTH_TOKEN"],
            )

    def test_workflow_token_check_rejects_hardcoded_token(self):
        with tempfile.TemporaryDirectory() as directory:
            repo_dir = Path(directory)
            frontend = repo_dir / "frontend"
            workflows = repo_dir / ".github" / "workflows"
            frontend.mkdir()
            workflows.mkdir(parents=True)
            (frontend / ".npmrc").write_text(
                "//npm.pkg.github.com/:_authToken=${NODE_AUTH_TOKEN}\n"
            )
            (workflows / "test.yml").write_text(
                "jobs:\n"
                "  test:\n"
                "    steps:\n"
                "      - run: pnpm install --frozen-lockfile\n"
                "        env:\n"
                "          NODE_AUTH_TOKEN: hardcoded-token\n"
            )
            result = observability.Result("example")

            observability.ensure_workflow_node_auth_token(frontend, repo_dir, result)

            self.assertEqual(
                result.warnings,
                [".github/workflows/test.yml: npm/pnpm/yarn mangler NODE_AUTH_TOKEN"],
            )

    def test_workflow_token_check_rejects_token_in_another_job(self):
        with tempfile.TemporaryDirectory() as directory:
            repo_dir = Path(directory)
            frontend = repo_dir / "frontend"
            workflows = repo_dir / ".github" / "workflows"
            frontend.mkdir()
            workflows.mkdir(parents=True)
            (frontend / ".npmrc").write_text(
                "//npm.pkg.github.com/:_authToken=${NODE_AUTH_TOKEN}\n"
            )
            (workflows / "test.yml").write_text(
                "jobs:\n"
                "  install:\n"
                "    steps:\n"
                "      - run: pnpm install --frozen-lockfile\n"
                "  unrelated:\n"
                "    env:\n"
                "      NODE_AUTH_TOKEN: ${{ secrets.READER_TOKEN }}\n"
                "    steps:\n"
                "      - run: echo done\n"
            )
            result = observability.Result("example")

            observability.ensure_workflow_node_auth_token(frontend, repo_dir, result)

            self.assertEqual(
                result.warnings,
                [".github/workflows/test.yml: npm/pnpm/yarn mangler NODE_AUTH_TOKEN"],
            )

    def test_workflow_token_check_detects_multiline_node_command(self):
        with tempfile.TemporaryDirectory() as directory:
            repo_dir = Path(directory)
            frontend = repo_dir / "frontend"
            workflows = repo_dir / ".github" / "workflows"
            frontend.mkdir()
            workflows.mkdir(parents=True)
            (frontend / ".npmrc").write_text(
                "//npm.pkg.github.com/:_authToken=${NODE_AUTH_TOKEN}\n"
            )
            (workflows / "test.yml").write_text(
                "jobs:\n"
                "  test:\n"
                "    steps:\n"
                "      - run: |\n"
                "          pnpm install --frozen-lockfile\n"
            )
            result = observability.Result("example")

            observability.ensure_workflow_node_auth_token(frontend, repo_dir, result)

            self.assertEqual(
                result.warnings,
                [".github/workflows/test.yml: npm/pnpm/yarn mangler NODE_AUTH_TOKEN"],
            )

    def test_workflow_token_check_ignores_workflow_without_node_package_manager(self):
        with tempfile.TemporaryDirectory() as directory:
            repo_dir = Path(directory)
            frontend = repo_dir / "frontend"
            workflows = repo_dir / ".github" / "workflows"
            frontend.mkdir()
            workflows.mkdir(parents=True)
            (frontend / ".npmrc").write_text(
                "//npm.pkg.github.com/:_authToken=${NODE_AUTH_TOKEN}\n"
            )
            (workflows / "deploy.yml").write_text(
                "jobs:\n"
                "  deploy:\n"
                "    steps:\n"
                "      - run: mvn verify\n"
            )
            result = observability.Result("example")

            observability.ensure_workflow_node_auth_token(frontend, repo_dir, result)

            self.assertEqual(result.warnings, [])


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
