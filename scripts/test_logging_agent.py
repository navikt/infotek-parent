import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import logging_agent


class LoggingAgentTest(unittest.TestCase):
    def test_parse_repositories_only_returns_managed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "repos.yaml"
            path.write_text(
                "repos:\n"
                "  - name: managed-repo\n"
                "    default_branch: master\n"
                "    managed: true\n"
                "  - name: unmanaged-repo\n"
                "    managed: false\n"
            )
            self.assertEqual(
                logging_agent.parse_repositories(path),
                [logging_agent.Repository("managed-repo", "master")],
            )

    def test_agent_command_selects_logging_agent_and_repo(self):
        command = logging_agent.agent_command(Path("/tmp/repos/example"), "example")
        self.assertIn("--agent", command)
        self.assertIn("logging-agent", command)
        self.assertIn("/tmp/repos/example", command)
        self.assertIn("--allow-all-tools", command)
        self.assertIn("--add-dir", command)
        self.assertIn("-C", command)
        self.assertIn("--silent", command)
        self.assertIn("--output-format", command)
        self.assertIn("json", command)
        self.assertIn("com.papertrailapp:logback-syslog4j", command[command.index("-p") + 1])
        self.assertIn("LogstashTcpSocketAppender", command[command.index("-p") + 1])

    def test_audit_usage_reports_managed_and_direct_dependencies_and_appender(self):
        with tempfile.TemporaryDirectory() as directory:
            repo_dir = Path(directory)
            (repo_dir / "pom.xml").write_text(
                "<project><dependencyManagement><dependencies>\n"
                "<dependency><groupId>com.papertrailapp</groupId>\n"
                "<artifactId>logback-syslog4j</artifactId></dependency>\n"
                "</dependencies></dependencyManagement><dependencies>\n"
                "<dependency><groupId>com.papertrailapp</groupId>\n"
                "<artifactId>logback-syslog4j</artifactId></dependency>\n"
                "</dependencies></project>\n"
            )
            backend = repo_dir / "backend"
            backend.mkdir()
            (backend / "pom.xml").write_text(
                "<project><dependencies><dependency>\n"
                "<groupId>com.papertrailapp</groupId>\n"
                "<artifactId>logback-syslog4j</artifactId>\n"
                "</dependency></dependencies><!--\n"
                "<dependency><groupId>com.papertrailapp</groupId>"
                "<artifactId>logback-syslog4j</artifactId></dependency>\n"
                "--></project>\n"
            )
            (backend / "logback-spring.xml").write_text(
                '<!--\n<appender class="com.papertrailapp.logback.Syslog4jAppender"/>\n-->\n'
                '<appender class="com.papertrailapp.logback.Syslog4jAppender"/>\n'
            )
            (repo_dir / "target").mkdir()
            (repo_dir / "target" / "pom.xml").write_text(
                "<dependency><groupId>com.papertrailapp</groupId>"
                "<artifactId>logback-syslog4j</artifactId></dependency>"
            )
            findings = logging_agent.audit_usage(repo_dir, "repos/example")
            self.assertEqual(findings, [
                "`repos/example/backend/pom.xml:3` (direkte avhengighet)",
                "`repos/example/pom.xml:3` (versjon styrt i dependencyManagement)",
                "`repos/example/pom.xml:6` (direkte avhengighet)",
                "`repos/example/backend/logback-spring.xml:4` (Syslog4jAppender)",
            ])

    def test_audit_findings_include_parent_and_only_managed_repos(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = root / "platform" / "maven"
            parent.mkdir(parents=True)
            (parent / "pom.xml").write_text(
                "<dependency><groupId>com.papertrailapp</groupId>"
                "<artifactId>logback-syslog4j</artifactId></dependency>"
            )
            managed = root / "repos" / "managed"
            managed.mkdir(parents=True)
            (managed / "logback.xml").write_text(
                '<appender class="com.papertrailapp.logback.Syslog4jAppender"/>\n'
            )
            unmanaged = root / "repos" / "unmanaged"
            unmanaged.mkdir()
            (unmanaged / "pom.xml").write_text(
                "<dependency><groupId>com.papertrailapp</groupId>"
                "<artifactId>logback-syslog4j</artifactId></dependency>"
            )
            report = root / "findings.md"
            with mock.patch.object(logging_agent, "ROOT", root), \
                    mock.patch.object(logging_agent, "REPOS_DIR", root / "repos"):
                logging_agent.write_audit_findings(
                    [logging_agent.Repository("managed", "main"),
                     logging_agent.Repository("missing", "main")],
                    report,
                )
            text = report.read_text()
            self.assertIn("platform/maven/pom.xml:1", text)
            self.assertIn("repos/managed/logback.xml:1", text)
            self.assertIn("| missing | ikke klonet |", text)
            self.assertNotIn("unmanaged", text)
            self.assertIn("LogstashTcpSocketAppender", text)

    def test_detect_test_command_various_repos(self):
        with tempfile.TemporaryDirectory() as directory:
            repo_dir = Path(directory)
            with self.subTest("maven wrapper"):
                (repo_dir / "mvnw").write_text("")
                self.assertEqual(logging_agent.detect_test_command(repo_dir), ["./mvnw", "test"])
                (repo_dir / "mvnw").unlink()
            with self.subTest("plain maven"):
                (repo_dir / "pom.xml").write_text("<project/>")
                self.assertEqual(logging_agent.detect_test_command(repo_dir), ["mvn", "test"])
                (repo_dir / "pom.xml").unlink()
            with self.subTest("pnpm via lockfile"):
                (repo_dir / "package.json").write_text(json.dumps({"scripts": {"test": "vitest"}}))
                (repo_dir / "pnpm-lock.yaml").write_text("")
                self.assertEqual(logging_agent.detect_test_command(repo_dir), ["pnpm", "test"])

    def test_detect_test_command_returns_none_without_test_script(self):
        with tempfile.TemporaryDirectory() as directory:
            repo_dir = Path(directory)
            (repo_dir / "package.json").write_text(json.dumps({"scripts": {"build": "vite build"}}))
            self.assertIsNone(logging_agent.detect_test_command(repo_dir))

    def test_persistence_only_writes_safe_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.json"
            results = {"version": 1, "repos": {}}
            logging_agent.record_test_result(
                results,
                logging_agent.Repository("example", "main"),
                ["npm", "test"],
                "exit 0",
                path,
            )
            saved = json.loads(path.read_text())
            self.assertEqual(saved["version"], 1)
            fields = set(saved["repos"]["example"].keys())
            self.assertEqual(fields, {"command", "result", "timestamp", "status", "head", "diff_hash"})

    def test_run_repository_test_missing_command_returns_false(self):
        with mock.patch.object(logging_agent, "detect_test_command", return_value=None), \
                mock.patch.object(logging_agent, "record_test_result") as record:
            results = {"version": 1, "repos": {}}
            ok = logging_agent.run_repository_test(logging_agent.Repository("example", "main"), results)
            self.assertFalse(ok)
            record.assert_called_once()

    def test_apply_repository_blocks_existing_logging_branch(self):
        repository = logging_agent.Repository("example", "main")
        with mock.patch("pathlib.Path.is_dir", return_value=True), \
                mock.patch.object(logging_agent, "is_dirty", return_value=False), \
                mock.patch.object(logging_agent, "current_branch", return_value="main"), \
                mock.patch.object(logging_agent, "run") as run_mock, \
                mock.patch.object(logging_agent, "record_test_result"):
            run_mock.return_value = subprocess.CompletedProcess(args=[], returncode=0)
            self.assertFalse(logging_agent.apply_repository(repository, {"version": 1, "repos": {}}))
            self.assertEqual(run_mock.call_count, 1)

    def test_run_repository_test_oserror_returns_false(self):
        with mock.patch.object(logging_agent, "detect_test_command", return_value=["npm", "test"]), \
                mock.patch.object(subprocess, "run", side_effect=OSError("no such file")), \
                mock.patch.object(logging_agent, "record_test_result") as record:
            results = {"version": 1, "repos": {}}
            ok = logging_agent.run_repository_test(logging_agent.Repository("example", "main"), results)
            self.assertFalse(ok)
            record.assert_called_once()

    def test_run_repository_test_nonzero_returncode_returns_false(self):
        completed = subprocess.CompletedProcess(args=["npm", "test"], returncode=1)
        with mock.patch.object(logging_agent, "detect_test_command", return_value=["npm", "test"]), \
                mock.patch.object(subprocess, "run", return_value=completed), \
                mock.patch.object(logging_agent, "record_test_result") as record:
            results = {"version": 1, "repos": {}}
            ok = logging_agent.run_repository_test(logging_agent.Repository("example", "main"), results)
            self.assertFalse(ok)
            record.assert_called_once()

    def test_run_repository_test_success_returns_true(self):
        completed = subprocess.CompletedProcess(args=["npm", "test"], returncode=0)
        with mock.patch.object(logging_agent, "detect_test_command", return_value=["npm", "test"]), \
                mock.patch.object(subprocess, "run", return_value=completed), \
                mock.patch.object(logging_agent, "record_test_result") as record:
            results = {"version": 1, "repos": {}}
            ok = logging_agent.run_repository_test(logging_agent.Repository("example", "main"), results)
            self.assertTrue(ok)
            record.assert_called_once()

    def test_apply_repository_preflight_agent_test_failures(self):
        repository = logging_agent.Repository("example", "main")
        results = {"version": 1, "repos": {}}

        with self.subTest("dirty working copy blocks apply"):
            with mock.patch.object(logging_agent, "REPOS_DIR", Path("/tmp/nonexistent-repos")):
                ok = logging_agent.apply_repository(repository, results)
                self.assertFalse(ok)

        with self.subTest("agent failure returns false"):
            with mock.patch("pathlib.Path.is_dir", return_value=True), \
                    mock.patch.object(logging_agent, "is_dirty", return_value=False), \
                    mock.patch.object(logging_agent, "current_branch", return_value="main"), \
                    mock.patch.object(logging_agent, "run") as run_mock, \
                    mock.patch.object(logging_agent, "record_test_result"):
                run_mock.side_effect = [
                    subprocess.CompletedProcess(args=[], returncode=1),
                    subprocess.CompletedProcess(args=[], returncode=0),
                    subprocess.CompletedProcess(args=[], returncode=1),
                ]
                ok = logging_agent.apply_repository(repository, results)
                self.assertFalse(ok)

        with self.subTest("test failure after successful agent returns false"):
            with mock.patch("pathlib.Path.is_dir", return_value=True), \
                    mock.patch.object(logging_agent, "is_dirty", return_value=False), \
                    mock.patch.object(logging_agent, "current_branch", return_value="main"), \
                    mock.patch.object(logging_agent, "run") as run_mock, \
                    mock.patch.object(logging_agent, "run_repository_test", return_value=False) as test_mock:
                run_mock.side_effect = [
                    subprocess.CompletedProcess(args=[], returncode=1),
                    subprocess.CompletedProcess(args=[], returncode=0),
                    subprocess.CompletedProcess(args=[], returncode=0),
                ]
                ok = logging_agent.apply_repository(repository, results)
                self.assertFalse(ok)
                test_mock.assert_called_once()

    def test_main_skips_pr_when_apply_or_test_fails(self):
        with mock.patch.object(logging_agent, "parse_repositories", return_value=[logging_agent.Repository("example", "main")]), \
                mock.patch.object(logging_agent, "apply_repository", return_value=False), \
                mock.patch.object(logging_agent, "write_status"), \
                mock.patch.object(logging_agent, "write_audit_findings"), \
                mock.patch.object(logging_agent, "run") as run_mock, \
                mock.patch("sys.argv", ["logging_agent.py", "--apply", "--create-pr", "--repo", "example"]):
            exit_code = logging_agent.main()
            self.assertEqual(exit_code, 1)
            run_mock.assert_not_called()

    def test_main_runs_pr_all_flow_on_successful_apply(self):
        with mock.patch.object(logging_agent, "parse_repositories", return_value=[logging_agent.Repository("example", "main")]), \
                mock.patch.object(logging_agent, "apply_repository", return_value=True), \
                mock.patch.object(logging_agent, "write_status"), \
                mock.patch.object(logging_agent, "write_audit_findings"), \
                mock.patch.object(logging_agent, "run", return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")) as run_mock, \
                mock.patch("sys.argv", ["logging_agent.py", "--apply", "--create-pr", "--repo", "example"]):
            exit_code = logging_agent.main()
            self.assertEqual(exit_code, 0)
            called_command = run_mock.call_args[0][0]
            self.assertIn("scripts/pr-all.py", called_command[1])
            self.assertIn(f"BRANCH={logging_agent.BRANCH}", called_command[2])
            self.assertIn("REPOS=example", called_command[4])

    def test_main_requires_explicit_scope_for_apply(self):
        with mock.patch("sys.argv", ["logging_agent.py", "--apply"]), \
                self.assertRaises(SystemExit):
            logging_agent.main()

    def test_main_rejects_pr_creation_without_apply(self):
        with mock.patch("sys.argv", ["logging_agent.py", "--all", "--create-pr"]), \
                self.assertRaises(SystemExit):
            logging_agent.main()

    def test_main_dry_run_does_not_apply(self):
        with mock.patch.object(logging_agent, "parse_repositories", return_value=[
            logging_agent.Repository("example", "main")
        ]), \
                mock.patch.object(logging_agent, "apply_repository") as apply, \
                mock.patch.object(logging_agent, "write_audit_findings") as findings, \
                mock.patch("sys.argv", ["logging_agent.py", "--all", "--dry-run"]):
            self.assertEqual(logging_agent.main(), 0)
            apply.assert_not_called()
            findings.assert_not_called()

    def test_single_repo_run_reports_all_managed_repos(self):
        repositories = [
            logging_agent.Repository("selected", "main"),
            logging_agent.Repository("other", "master"),
        ]
        with mock.patch.object(logging_agent, "parse_repositories", return_value=repositories), \
                mock.patch.object(logging_agent, "write_status"), \
                mock.patch.object(logging_agent, "write_audit_findings") as findings, \
                mock.patch("sys.argv", ["logging_agent.py", "--repo", "selected"]):
            self.assertEqual(logging_agent.main(), 0)
            findings.assert_called_once_with(repositories)

    def test_repo_filter_reject_and_accept(self):
        with self.subTest("rejects unknown repo"):
            result = subprocess.run(
                ["python3", str(logging_agent.__file__), "--repo", "ikke-et-repo"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ikke-et-repo", result.stderr)

        with self.subTest("accepts known managed repo"):
            repositories = logging_agent.parse_repositories()
            names = {r.name for r in repositories}
            self.assertIn("infotek-statistikk", names)


if __name__ == "__main__":
    unittest.main()
