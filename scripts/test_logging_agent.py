import subprocess
import tempfile
import unittest
from pathlib import Path

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

    def test_repo_filter_rejects_unknown_repo(self):
        result = subprocess.run(
            ["python3", str(logging_agent.__file__), "--repo", "ikke-et-repo"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ikke-et-repo", result.stderr)

    def test_repo_filter_accepts_known_managed_repo(self):
        repositories = logging_agent.parse_repositories()
        names = {r.name for r in repositories}
        self.assertIn("infotek-statistikk", names)


if __name__ == "__main__":
    unittest.main()
