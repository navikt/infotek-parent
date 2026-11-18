import json
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
                'init({ app: "example", namespace: "team", tracing: true });',
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
                'init({ app: "example", namespace: "infotrygd", tracing: true });', module_content
            )
            self.assertIn(
                'app: "example",\n        namespace: "infotrygd",',
                test_content,
            )
            self.assertEqual(
                json.loads(package_path.read_text())["devDependencies"]["vitest"],
                observability.VITEST_VERSION,
            )

    def test_existing_observability_test_adds_missing_vitest_once(self):
        with tempfile.TemporaryDirectory() as directory:
            frontend = Path(directory)
            source = frontend / "src"
            source.mkdir()
            package_path = frontend / "package.json"
            package_path.write_text(json.dumps({"dependencies": {"react": "19.0.0"}}) + "\n")
            (source / "main.tsx").write_text(
                'import { initializeObservability } from "./observability";\n'
                "initializeObservability();\n"
            )
            (source / "observability.ts").write_text(
                observability.observability_module("example", "team")
            )
            (source / "observability.test.ts").write_text(
                observability.observability_test("example", "team")
            )
            repository = observability.Repository("example", "team", "main", ("dev-gcp",))

            preview = observability.Result(repository.name)
            self.assertTrue(
                observability.ensure_frontend_initialization(
                    package_path, repository, False, preview
                )
            )
            self.assertNotIn("devDependencies", json.loads(package_path.read_text()))

            first = observability.Result(repository.name)
            self.assertTrue(
                observability.ensure_frontend_initialization(
                    package_path, repository, True, first
                )
            )
            self.assertEqual(
                json.loads(package_path.read_text())["devDependencies"]["vitest"],
                observability.VITEST_VERSION,
            )
            second = observability.Result(repository.name)
            self.assertFalse(
                observability.ensure_frontend_initialization(
                    package_path, repository, True, second
                )
            )
            self.assertEqual(second.changes, [])

    def test_existing_vitest_version_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            frontend = Path(directory)
            source = frontend / "src"
            source.mkdir()
            package_path = frontend / "package.json"
            package_path.write_text(
                json.dumps({"devDependencies": {"vitest": "^4.0.0"}}) + "\n"
            )
            (source / "main.tsx").write_text(
                'import { initializeObservability } from "./observability";\n'
                "initializeObservability();\n"
            )
            (source / "observability.ts").write_text(
                observability.observability_module("example", "team")
            )
            (source / "observability.test.ts").write_text(
                observability.observability_test("example", "team")
            )
            repository = observability.Repository("example", "team", "main", ("dev-gcp",))
            result = observability.Result(repository.name)

            self.assertFalse(
                observability.ensure_frontend_initialization(
                    package_path, repository, True, result
                )
            )
            self.assertEqual(
                json.loads(package_path.read_text())["devDependencies"]["vitest"],
                "^4.0.0",
            )
            self.assertEqual(result.changes, [])

    def test_existing_test_without_vitest_does_not_add_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            frontend = Path(directory)
            source = frontend / "src"
            source.mkdir()
            package_path = frontend / "package.json"
            package_path.write_text(json.dumps({"dependencies": {"react": "19.0.0"}}) + "\n")
            (source / "main.tsx").write_text(
                'import { initializeObservability } from "./observability";\n'
                "initializeObservability();\n"
            )
            (source / "observability.ts").write_text(
                observability.observability_module("example", "team")
            )
            (source / "observability.test.ts").write_text(
                'import { initializeObservability } from "./observability";\n'
                "test('starter observability', () => initializeObservability());\n"
            )
            repository = observability.Repository("example", "team", "main", ("dev-gcp",))
            result = observability.Result(repository.name)

            self.assertFalse(
                observability.ensure_frontend_initialization(
                    package_path, repository, True, result
                )
            )
            self.assertNotIn("devDependencies", json.loads(package_path.read_text()))

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

    def test_frontend_initialization_adds_app_to_legacy_template(self):
        with tempfile.TemporaryDirectory() as directory:
            frontend = Path(directory)
            source = frontend / "src"
            source.mkdir()
            package_path = frontend / "package.json"
            package_path.write_text(json.dumps({"devDependencies": {"vitest": "3.0.0"}}) + "\n")
            (source / "main.tsx").write_text(
                'import { initializeObservability } from "./observability";\n'
                "initializeObservability();\n"
            )
            (source / "observability.ts").write_text(
                'import { init } from "@nais/apm";\n\n'
                "export function initializeObservability() {\n"
                '    init({ namespace: "historisk", tracing: true });\n'
                "}\n"
            )
            (source / "observability.test.ts").write_text(
                'import { expect, test } from "vitest";\n'
                'expect(init).toHaveBeenCalledWith({ namespace: "historisk", tracing: true });\n'
            )
            repository = observability.Repository("repo", "historisk", "main", ("dev-gcp",))
            first = observability.Result(repository.name)
            second = observability.Result(repository.name)

            observability.ensure_frontend_initialization(
                package_path, repository, True, first, "historisk-app"
            )
            changed = observability.ensure_frontend_initialization(
                package_path, repository, True, second, "historisk-app"
            )

            self.assertIn(
                'init({ app: "historisk-app", namespace: "historisk", tracing: true });',
                (source / "observability.ts").read_text(),
            )
            self.assertIn(
                'toHaveBeenCalledWith({ app: "historisk-app", namespace: "historisk", tracing: true })',
                (source / "observability.test.ts").read_text(),
            )
            self.assertEqual(first.status, "changes-needed")
            self.assertFalse(changed)
            self.assertEqual(second.status, "compliant")

    def test_frontend_initialization_flags_custom_module_without_app(self):
        with tempfile.TemporaryDirectory() as directory:
            frontend = Path(directory)
            source = frontend / "src"
            source.mkdir()
            package_path = frontend / "package.json"
            package_path.write_text(json.dumps({"devDependencies": {"vitest": "3.0.0"}}) + "\n")
            (source / "main.tsx").write_text(
                'import { initializeObservability } from "./observability";\n'
                "initializeObservability();\n"
            )
            module = (
                'import { init } from "@nais/apm";\n\n'
                "export function initializeObservability() {\n"
                '    init({ namespace: "historisk", beforeSend });\n'
                "}\n"
            )
            (source / "observability.ts").write_text(module)
            repository = observability.Repository("repo", "historisk", "main", ("dev-gcp",))
            result = observability.Result(repository.name)

            observability.ensure_frontend_initialization(package_path, repository, True, result)

            self.assertEqual((source / "observability.ts").read_text(), module)
            self.assertIn("mangler app i init()", " ".join(result.warnings))

    def test_frontend_app_name_prefers_frontend_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            repo_dir = Path(directory)
            nais = repo_dir / "nais"
            nais.mkdir()
            for name in ("example-backend", "example-frontend"):
                (nais / f"{name}.yaml").write_text(
                    "apiVersion: nais.io/v1alpha1\nkind: Application\n"
                    f"metadata:\n  name: {name}\nspec:\n  image: x\n"
                )

            self.assertEqual(observability.frontend_app_name(repo_dir), "example-frontend")

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

    def test_npmrc_github_packages_check_ignores_comments_and_other_values(self):
        with tempfile.TemporaryDirectory() as directory:
            frontend = Path(directory)
            (frontend / ".npmrc").write_text(
                "# https://npm.pkg.github.com is documented here\n"
                "registry=https://registry.npmjs.org/?mirror=npm.pkg.github.com\n"
            )

            self.assertFalse(observability.npmrc_uses_github_packages(frontend))

    def test_npmrc_github_packages_check_accepts_registry_and_auth_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            frontend = Path(directory)
            npmrc = frontend / ".npmrc"
            npmrc.write_text("@navikt:registry=https://npm.pkg.github.com/\n")

            self.assertTrue(observability.npmrc_uses_github_packages(frontend))

            npmrc.write_text(
                "//npm.pkg.github.com/:_authToken=${NODE_AUTH_TOKEN}\n"
            )

            self.assertTrue(observability.npmrc_uses_github_packages(frontend))

    def test_workflow_token_check_accepts_composite_action_input(self):
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
                "      env:\n"
                "        NODE_AUTH_TOKEN: ${{ inputs.node-auth-token }}\n"
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
                "      env:\n"
                "        NODE_AUTH_TOKEN: ${{ inputs.node-auth-token }}\n"
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
                "      env:\n"
                "        NODE_AUTH_TOKEN: ${{ inputs.node-auth-token }}\n"
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

    def test_workflow_token_check_rejects_token_mapping_in_unrelated_composite_step(self):
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
                "    - run: echo ready\n"
                "      shell: bash\n"
                "      env:\n"
                "        NODE_AUTH_TOKEN: ${{ inputs.node-auth-token }}\n"
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

            self.assertEqual(
                result.warnings,
                [".github/workflows/test.yml: npm/pnpm/yarn mangler NODE_AUTH_TOKEN"],
            )

    def test_workflow_token_check_rejects_token_for_external_action(self):
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
                "      - uses: attacker/action@v1\n"
                "        with:\n"
                "          node-auth-token: ${{ secrets.READER_TOKEN }}\n"
                "      - run: pnpm install --frozen-lockfile\n"
            )
            result = observability.Result("example")

            observability.ensure_workflow_node_auth_token(frontend, repo_dir, result)

            self.assertEqual(
                result.warnings,
                [".github/workflows/test.yml: npm/pnpm/yarn mangler NODE_AUTH_TOKEN"],
            )

    def test_workflow_token_check_rejects_token_for_unrelated_step(self):
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
                "      - run: echo ready\n"
                "        env:\n"
                "          NODE_AUTH_TOKEN: ${{ secrets.READER_TOKEN }}\n"
                "      - run: pnpm install --frozen-lockfile\n"
            )
            result = observability.Result("example")

            observability.ensure_workflow_node_auth_token(frontend, repo_dir, result)

            self.assertEqual(
                result.warnings,
                [".github/workflows/test.yml: npm/pnpm/yarn mangler NODE_AUTH_TOKEN"],
            )

    def test_workflow_token_check_rejects_token_for_later_named_step(self):
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
                "      - name: Installer avhengigheter\n"
                "        run: pnpm install --frozen-lockfile\n"
                "      - name: Urelatert steg\n"
                "        run: echo ready\n"
                "        env:\n"
                "          NODE_AUTH_TOKEN: ${{ secrets.READER_TOKEN }}\n"
            )
            result = observability.Result("example")

            observability.ensure_workflow_node_auth_token(frontend, repo_dir, result)

            self.assertEqual(
                result.warnings,
                [".github/workflows/test.yml: npm/pnpm/yarn mangler NODE_AUTH_TOKEN"],
            )

    def test_workflow_token_check_rejects_job_level_token(self):
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
                "    env:\n"
                "      NODE_AUTH_TOKEN: ${{ secrets.READER_TOKEN }}\n"
                "    steps:\n"
                "      - uses: attacker/action@v1\n"
                "      - run: pnpm install --frozen-lockfile\n"
            )
            result = observability.Result("example")

            observability.ensure_workflow_node_auth_token(frontend, repo_dir, result)

            self.assertEqual(
                result.warnings,
                [".github/workflows/test.yml: npm/pnpm/yarn mangler NODE_AUTH_TOKEN"],
            )

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
            self.assertEqual(second.status, "manual-review")
            self.assertIn("legg .nais/alerts.yaml til deploy manuelt", second.warnings[0])
            self.assertEqual(second.changes, [])

    def test_process_repository_updates_lockfile_for_existing_observability_test(self):
        with tempfile.TemporaryDirectory() as directory:
            repos_dir = Path(directory)
            repo_dir = self.create_git_repository(repos_dir, "example")
            frontend = repo_dir / "frontend"
            source = frontend / "src"
            source.mkdir(parents=True)
            package_path = frontend / "package.json"
            package_path.write_text(
                json.dumps(
                    {"dependencies": {"react": "19.0.0", "@nais/apm": observability.APM_VERSION}}
                )
                + "\n"
            )
            (source / "main.tsx").write_text(
                'import { initializeObservability } from "./observability";\n'
                "initializeObservability();\n"
            )
            (source / "observability.ts").write_text(
                observability.observability_module("example", "team")
            )
            (source / "observability.test.ts").write_text(
                observability.observability_test("example", "team")
            )
            (frontend / ".npmrc").write_text(
                observability.REGISTRY_LINE + "\n" + observability.AUTH_TOKEN_LINE + "\n"
            )
            (repo_dir / ".github" / "workflows").mkdir(parents=True)
            self.commit_all(repo_dir)
            subprocess.run(
                ["git", "switch", "-c", "bugfix/observability"],
                cwd=repo_dir,
                check=True,
                capture_output=True,
            )
            repository = observability.Repository("example", "team", "main", ("dev-gcp",))

            with patch.object(observability, "update_lockfile") as update_lockfile:
                result = observability.process_repository(
                    repository, apply=True, update_lockfiles=True, repos_dir=repos_dir
                )

            self.assertEqual(result.status, "changes-needed")
            self.assertEqual(
                json.loads(package_path.read_text())["devDependencies"]["vitest"],
                observability.VITEST_VERSION,
            )
            update_lockfile.assert_called_once_with(package_path, result)

    def test_apply_blocks_default_branch(self):
        for default_branch in ("main", "master"):
            with self.subTest(default_branch=default_branch):
                with tempfile.TemporaryDirectory(prefix="observability test ") as directory:
                    repos_dir = Path(directory)
                    repo_dir = self.create_git_repository(
                        repos_dir, "example", default_branch
                    )
                    (repo_dir / "pom.xml").write_text("<project/>\n")
                    (repo_dir / "app.yaml").write_text(
                        "kind: Application\nspec:\n  image: test\n"
                    )
                    self.commit_all(repo_dir)
                    repository = observability.Repository(
                        "example", "team", default_branch, ("dev-gcp",)
                    )

                    with patch.object(observability, "update_lockfile") as update_lockfile:
                        result = observability.process_repository(
                            repository,
                            apply=True,
                            update_lockfiles=True,
                            repos_dir=repos_dir,
                        )

                    self.assertEqual(result.status, "blocked")
                    warning = result.warnings[0]
                    self.assertIn(f"default-branchen {default_branch}", warning)
                    self.assertIn("opprett en feature-branch", warning)
                    command = warning.split("Kjør: ", 1)[1]
                    self.assertEqual(
                        shlex.split(command),
                        ["git", "-C", str(repo_dir), "switch", "-c", "chore/observability"],
                    )
                    self.assertEqual(
                        observability.git_status(repo_dir), (default_branch, False)
                    )
                    update_lockfile.assert_not_called()

    def test_apply_blocks_detached_head_with_default_branch_guidance(self):
        with tempfile.TemporaryDirectory() as directory:
            repos_dir = Path(directory)
            repo_dir = self.create_git_repository(repos_dir, "example", "master")
            (repo_dir / "pom.xml").write_text("<project/>\n")
            (repo_dir / "app.yaml").write_text(
                "kind: Application\nspec:\n  image: test\n"
            )
            self.commit_all(repo_dir)
            subprocess.run(
                ["git", "switch", "--detach"],
                cwd=repo_dir,
                check=True,
                capture_output=True,
            )
            repository = observability.Repository(
                "example", "team", "master", ("dev-gcp",)
            )

            with patch.object(observability, "update_lockfile") as update_lockfile:
                result = observability.process_repository(
                    repository,
                    apply=True,
                    update_lockfiles=True,
                    repos_dir=repos_dir,
                )

            self.assertEqual(result.status, "blocked")
            self.assertIn("detached HEAD", result.warnings[0])
            self.assertIn("git -C", result.warnings[0])
            self.assertIn("switch master", result.warnings[0])
            self.assertNotIn("switch -c", result.warnings[0])
            self.assertEqual(observability.git_status(repo_dir), ("detached", False))
            update_lockfile.assert_not_called()

    def test_apm_dependency_is_not_downgraded(self):
        with tempfile.TemporaryDirectory() as directory:
            package_path = Path(directory) / "package.json"
            package_path.write_text(json.dumps({"dependencies": {"@nais/apm": "^9.0.0"}}))
            result = observability.Result("example")

            changed = observability.ensure_apm_dependency(package_path, True, result)

            self.assertFalse(changed)
            self.assertEqual(json.loads(package_path.read_text())["dependencies"]["@nais/apm"], "^9.0.0")

    def test_node_auth_token_only_required_for_install_commands(self):
        self.assertFalse(observability.command_installs_packages("pnpm run test:e2e"))
        self.assertFalse(observability.command_installs_packages("npm test && pnpm build"))
        self.assertTrue(observability.command_installs_packages("pnpm --dir frontend install"))
        self.assertTrue(observability.command_installs_packages("cd frontend && npm ci"))
        self.assertTrue(observability.command_installs_packages("yarn"))

    def test_existing_apm_initialization_in_other_module_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            frontend = Path(directory)
            (frontend / "src").mkdir()
            package_path = frontend / "package.json"
            package_path.write_text(json.dumps({"dependencies": {"react": "19.0.0"}}))
            (frontend / "src" / "setupLogging.ts").write_text(
                'import { init } from "@nais/apm"\nexport function setupLogging() { init({}) }\n'
            )
            (frontend / "src" / "index.tsx").write_text('import { setupLogging } from "./setupLogging"\n')
            repository = observability.Repository("example", "team", "main", ("dev-gcp",))
            result = observability.Result("example")

            changed = observability.ensure_frontend_initialization(
                package_path, repository, True, result
            )

            self.assertFalse(changed)
            self.assertFalse((frontend / "src" / "observability.ts").exists())
            self.assertEqual(result.changes, [])

    def write_legacy_frontend(self, frontend: Path, entrypoint: str) -> Path:
        (frontend / "src").mkdir(parents=True)
        package_path = frontend / "package.json"
        package_path.write_text(
            json.dumps(
                {"dependencies": {"loglevel": "^1.8.0", "loglevel-plugin-remote": "^0.6.8", "react": "19.0.0"}},
                indent=2,
            )
            + "\n"
        )
        (frontend / "src" / "setupLogging.js").write_text(
            "import log from 'loglevel';\n"
            "import remote from 'loglevel-plugin-remote';\n"
            "export function setupLogging() {\n"
            "    remote.apply(log, { url: '/api/frontendLogger' })\n"
            "}\n"
        )
        (frontend / "src" / "index.tsx").write_text(entrypoint)
        return package_path

    def test_removes_legacy_frontend_logging(self):
        with tempfile.TemporaryDirectory() as directory:
            frontend = Path(directory)
            package_path = self.write_legacy_frontend(
                frontend,
                'import {setupLogging} from "./setupLogging";\n'
                "import log from 'loglevel';\n\n"
                "setupLogging()\n"
                'log.info("start");\n',
            )
            result = observability.Result("example")

            changed, ready = observability.remove_legacy_frontend_logging(package_path, True, result)

            self.assertTrue(changed)
            self.assertTrue(ready)
            self.assertFalse((frontend / "src" / "setupLogging.js").exists())
            self.assertEqual(
                (frontend / "src" / "index.tsx").read_text(),
                "import log from 'loglevel';\n\n" 'log.info("start");\n',
            )
            dependencies = json.loads(package_path.read_text())["dependencies"]
            self.assertNotIn("loglevel-plugin-remote", dependencies)
            self.assertIn("loglevel", dependencies)

    def test_legacy_frontend_logging_with_unknown_usage_requires_review(self):
        with tempfile.TemporaryDirectory() as directory:
            frontend = Path(directory)
            entrypoint = 'import {setupLogging} from "./setupLogging";\nsetupLogging().then(start)\n'
            package_path = self.write_legacy_frontend(frontend, entrypoint)
            result = observability.Result("example")

            changed, ready = observability.remove_legacy_frontend_logging(package_path, True, result)

            self.assertEqual((changed, ready), (False, False))
            self.assertEqual(result.status, "manual-review")
            self.assertTrue((frontend / "src" / "setupLogging.js").exists())
            self.assertEqual((frontend / "src" / "index.tsx").read_text(), entrypoint)

    def write_frontend_logger_controller(self, repo_dir: Path) -> Path:
        controller = repo_dir / "src" / "main" / "kotlin" / "FrontendLoggerController.kt"
        controller.parent.mkdir(parents=True)
        controller.write_text(
            "@RestController\nclass FrontendLoggerController {\n"
            '    @PostMapping("/api/frontendLogger")\n    fun log(@RequestBody body: LoggerDto) {}\n}\n'
            "data class LoggerDto(val logs: List<String>)\n"
        )
        return controller

    def test_removes_frontend_logger_endpoint_and_its_test(self):
        with tempfile.TemporaryDirectory() as directory:
            repo_dir = Path(directory)
            controller = self.write_frontend_logger_controller(repo_dir)
            test = repo_dir / "src" / "test" / "kotlin" / "FrontendLoggerControllerTest.kt"
            test.parent.mkdir(parents=True)
            test.write_text("class FrontendLoggerControllerTest\n")
            result = observability.Result("example")

            observability.remove_frontend_logger_endpoint(repo_dir, True, True, result)

            self.assertFalse(controller.exists())
            self.assertFalse(test.exists())
            self.assertEqual(result.status, "changes-needed")

    def test_keeps_frontend_logger_endpoint_while_frontend_uses_it(self):
        with tempfile.TemporaryDirectory() as directory:
            repo_dir = Path(directory)
            controller = self.write_frontend_logger_controller(repo_dir)
            result = observability.Result("example")

            observability.remove_frontend_logger_endpoint(repo_dir, False, True, result)

            self.assertTrue(controller.exists())
            self.assertEqual(result.status, "manual-review")

    def test_error_response_trace_check_ignores_non_error_classes(self):
        with tempfile.TemporaryDirectory() as directory:
            repo_dir = Path(directory)
            source = repo_dir / "src" / "main" / "kotlin"
            source.mkdir(parents=True)
            (source / "Feilmelding.kt").write_text(
                'data class Feilmelding(val kode: String) {\n    val traceId = MDC.get("traceId")\n}\n'
            )
            (source / "AuditLog.kt").write_text("class AuditLog {\n    val callId = 1\n}\n")

            candidates = observability.error_response_trace_candidates(repo_dir)

            self.assertEqual(len(candidates), 1)
            self.assertIn("Feilmelding.kt: MDC traceId", candidates[0])

    def test_error_response_call_id_from_span_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            repo_dir = Path(directory)
            source = repo_dir / "src" / "main" / "kotlin"
            source.mkdir(parents=True)
            (source / "Feilmelding.kt").write_text(
                "data class Feilmelding(val kode: String) {\n"
                "    val callId: String? = Span.current().spanContext.traceId\n}\n"
            )
            (source / "ProblemDetail.kt").write_text(
                'data class ProblemDetail(val kode: String) {\n    val callId = MDC.get("callId")\n}\n'
            )

            candidates = observability.error_response_trace_candidates(repo_dir)

            self.assertEqual(len(candidates), 1)
            self.assertIn("ProblemDetail.kt: feilsvar bruker callId", candidates[0])

    def create_deployable_repository(self, repos_dir: Path) -> Path:
        repo_dir = self.create_git_repository(repos_dir, "example")
        (repo_dir / "pom.xml").write_text("<project/>\n")
        (repo_dir / "nais" / "app").mkdir(parents=True)
        (repo_dir / "nais" / "prod.json").write_text(json.dumps({"app": "example-app"}))
        (repo_dir / "nais" / "app" / "backend.yaml").write_text(
            "apiVersion: nais.io/v1alpha1\n"
            "kind: Application\n"
            "metadata:\n"
            '  name: "{{app}}"\n'
            "spec:\n"
            "  prometheus:\n"
            "    enabled: true\n"
            "    path: /actuator/prometheus\n"
            "  observability:\n"
            "    autoInstrumentation:\n"
            "      enabled: true\n"
            "      runtime: java\n"
        )
        workflows = repo_dir / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "main.yml").write_text(
            "jobs:\n"
            "  deploy-dev:\n"
            "    steps:\n"
            "      - uses: nais/deploy/actions/deploy@abc # v3\n"
            "        env:\n"
            "          CLUSTER: dev-gcp\n"
            "          RESOURCE: nais/app/backend.yaml\n"
            "  deploy-prod:\n"
            "    steps:\n"
            "      - uses: nais/deploy/actions/deploy@abc # v3\n"
            "        env:\n"
            "          CLUSTER: prod-gcp\n"
            "          RESOURCE: nais/app/backend.yaml\n"
        )
        self.commit_all(repo_dir)
        subprocess.run(
            ["git", "switch", "-c", "chore/observability"],
            cwd=repo_dir,
            check=True,
            capture_output=True,
        )
        return repo_dir

    def test_creates_alerts_and_deploys_them_to_prod_once(self):
        with tempfile.TemporaryDirectory() as directory:
            repos_dir = Path(directory)
            repo_dir = self.create_deployable_repository(repos_dir)
            repository = observability.Repository(
                "example", "historisk", "main", ("dev-gcp", "prod-gcp")
            )

            first = observability.process_repository(repository, True, False, repos_dir)
            self.commit_all(repo_dir)
            second = observability.process_repository(repository, True, False, repos_dir)

            alerts = (repo_dir / "nais" / "alerts.yaml").read_text()
            workflow = (repo_dir / ".github" / "workflows" / "main.yml").read_text()
            self.assertIn("kind: PrometheusRule", alerts)
            self.assertIn('deployment="example-app"', alerts)
            self.assertIn("alert: HoyFeilrate", alerts)
            self.assertNotIn("{{", alerts)
            self.assertEqual(workflow.count("nais/alerts.yaml"), 1)
            self.assertIn("CLUSTER: prod-gcp\n          RESOURCE: nais/app/backend.yaml,nais/alerts.yaml", workflow)
            self.assertIn("#infotek-sheriff", " ".join(first.warnings))
            self.assertEqual(second.changes, [])

    def test_skip_alerts_leaves_alerts_and_workflow_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            repos_dir = Path(directory)
            repo_dir = self.create_deployable_repository(repos_dir)
            workflow = repo_dir / ".github" / "workflows" / "main.yml"
            original = workflow.read_text()
            repository = observability.Repository(
                "example", "historisk", "main", ("dev-gcp", "prod-gcp")
            )

            result = observability.process_repository(
                repository, True, False, repos_dir, skip_alerts=True
            )

            self.assertFalse((repo_dir / "nais" / "alerts.yaml").exists())
            self.assertEqual(workflow.read_text(), original)
            self.assertNotIn("#infotek-sheriff", " ".join(result.warnings))

    def test_deprecated_nais_alert_requires_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            repos_dir = Path(directory)
            repo_dir = self.create_deployable_repository(repos_dir)
            (repo_dir / "nais" / "alert.yml").write_text(
                'apiVersion: "nais.io/v1"\nkind: "Alert"\n'
            )
            repository = observability.Repository("example", "infotrygd", "main", ("prod-gcp",))
            result = observability.Result("example")

            observability.ensure_alerts(repository, repo_dir, True, False, result)

            self.assertIn("nais/alert.yml: migrer nais.io Alert til PrometheusRule", result.warnings)

    @staticmethod
    def create_git_repository(
        repos_dir: Path, name: str, default_branch: str = "main"
    ) -> Path:
        repo_dir = repos_dir / name
        repo_dir.mkdir()
        subprocess.run(
            ["git", "init", "-b", default_branch],
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
