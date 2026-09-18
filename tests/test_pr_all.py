import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch


SCRIPT = Path(__file__).parent.parent / "scripts" / "pr-all.py"
SPEC = importlib.util.spec_from_file_location("pr_all", SCRIPT)
pr_all = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pr_all)


class BranchHasCommitsTest(unittest.TestCase):
    @patch.object(pr_all, "run")
    def test_returns_true_when_feature_branch_has_commit(self, mocked_run):
        mocked_run.return_value.returncode = 0
        mocked_run.return_value.stdout = "1\n"

        self.assertTrue(pr_all.branch_has_commits(Path("/repo"), "main", "chore/image"))

    @patch.object(pr_all, "run")
    def test_falls_back_to_local_default_branch(self, mocked_run):
        first = unittest.mock.Mock(returncode=128, stdout="")
        second = unittest.mock.Mock(returncode=0, stdout="0\n")
        mocked_run.side_effect = [first, second]

        self.assertFalse(pr_all.branch_has_commits(Path("/repo"), "main", "chore/image"))
        self.assertEqual(
            mocked_run.call_args_list[1].args[0],
            ["git", "rev-list", "--count", "main..chore/image"],
        )

    @patch.object(pr_all, "run")
    def test_returns_none_when_default_refs_are_unavailable(self, mocked_run):
        mocked_run.return_value = Mock(returncode=128, stdout="")

        self.assertIsNone(pr_all.branch_has_commits(Path("/repo"), "main", "chore/image"))


class ExistingFeatureBranchTest(unittest.TestCase):
    @patch(
        "builtins.input",
        side_effect=["", "fix: stram inn CI", "Bytt til Chainguard", "", "j"],
    )
    @patch.object(pr_all, "get_existing_pr", return_value=None)
    @patch.object(pr_all, "get_repo_slug", return_value="navikt/app")
    @patch.object(pr_all, "get_local_changes", return_value=[" M Dockerfile"])
    @patch.object(pr_all, "get_current_branch", return_value="chore/chainguard")
    @patch.object(pr_all, "parse_repos", return_value=[
        {"name": "app", "default_branch": "main", "managed": "true"},
    ])
    @patch.object(pr_all, "run")
    def test_commits_and_pushes_when_remote_branch_already_exists(
        self,
        mocked_run,
        _parse_repos,
        _current_branch,
        _local_changes,
        _repo_slug,
        _existing_pr,
        _input,
    ):
        pr_all.REPOS_DIR = Path("/repos")
        repo_dir = pr_all.REPOS_DIR / "app"

        def result_for(command, **_kwargs):
            if command[:3] == ["git", "log", "--oneline"]:
                return Mock(returncode=0, stdout="")
            if command[:3] == ["gh", "pr", "create"]:
                return Mock(returncode=0, stdout="https://github.com/navikt/app/pull/1\n", stderr="")
            return Mock(returncode=0, stdout="", stderr="")

        mocked_run.side_effect = result_for

        with patch.object(Path, "is_dir", return_value=True):
            pr_all.main()

        self.assertIn(call(["git", "add", "-A"], cwd=repo_dir), mocked_run.call_args_list)
        self.assertIn(
            call(["git", "commit", "-m", "fix: stram inn CI"], cwd=repo_dir),
            mocked_run.call_args_list,
        )
        self.assertIn(
            call(["git", "push", "-u", "origin", "chore/chainguard"], cwd=repo_dir),
            mocked_run.call_args_list,
        )

    @patch("builtins.input", side_effect=["", "fix: stram inn CI", "j"])
    @patch.object(pr_all, "get_existing_pr", return_value="https://github.com/navikt/app/pull/1")
    @patch.object(pr_all, "get_repo_slug", return_value="navikt/app")
    @patch.object(pr_all, "get_local_changes", return_value=[" M Dockerfile"])
    @patch.object(pr_all, "get_current_branch", return_value="chore/chainguard")
    @patch.object(pr_all, "parse_repos", return_value=[
        {"name": "app", "default_branch": "main", "managed": "true"},
    ])
    @patch.object(pr_all, "run")
    def test_commits_and_pushes_updates_to_existing_pr(
        self,
        mocked_run,
        _parse_repos,
        _current_branch,
        _local_changes,
        _repo_slug,
        _existing_pr,
        _input,
    ):
        pr_all.REPOS_DIR = Path("/repos")
        repo_dir = pr_all.REPOS_DIR / "app"
        mocked_run.return_value = Mock(returncode=0, stdout="", stderr="")

        with patch.object(Path, "is_dir", return_value=True):
            pr_all.main()

        self.assertIn(call(["git", "add", "-A"], cwd=repo_dir), mocked_run.call_args_list)
        self.assertIn(
            call(["git", "commit", "-m", "fix: stram inn CI"], cwd=repo_dir),
            mocked_run.call_args_list,
        )
        self.assertIn(
            call(["git", "push", "-u", "origin", "chore/chainguard"], cwd=repo_dir),
            mocked_run.call_args_list,
        )
        self.assertFalse(
            any(item.args[0][:3] == ["gh", "pr", "create"] for item in mocked_run.call_args_list)
        )
        prompts = [item.args[0] for item in _input.call_args_list]
        self.assertFalse(any(prompt.startswith("  Tittel") for prompt in prompts))
        self.assertFalse(any(prompt.startswith("  Body") for prompt in prompts))

    @patch("builtins.input", side_effect=[""])
    @patch.object(pr_all, "get_existing_pr", return_value="?")
    @patch.object(pr_all, "get_repo_slug", return_value="navikt/app")
    @patch.object(pr_all, "get_local_changes", return_value=[" M Dockerfile"])
    @patch.object(pr_all, "get_current_branch", return_value="chore/chainguard")
    @patch.object(pr_all, "parse_repos", return_value=[
        {"name": "app", "default_branch": "main", "managed": "true"},
    ])
    @patch.object(pr_all, "run")
    def test_does_not_commit_when_pr_status_is_unknown(
        self,
        mocked_run,
        _parse_repos,
        _current_branch,
        _local_changes,
        _repo_slug,
        _existing_pr,
        _input,
    ):
        pr_all.REPOS_DIR = Path("/repos")
        mocked_run.return_value = Mock(returncode=0, stdout="", stderr="")

        with patch.object(Path, "is_dir", return_value=True):
            pr_all.main()

        commands = [item.args[0] for item in mocked_run.call_args_list]
        self.assertNotIn(["git", "add", "-A"], commands)
        self.assertFalse(any(command[:3] == ["gh", "pr", "create"] for command in commands))
