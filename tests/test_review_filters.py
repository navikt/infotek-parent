from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
spec = importlib.util.spec_from_file_location("pr_behandle", SCRIPTS_DIR / "pr-behandle.py")
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class ReviewFiltersTest(unittest.TestCase):
    def setUp(self) -> None:
        module.REVIEW_MODE = True
        module.REVIEW_SELECTED_KEYS = set()
        module.REVIEW_GROUPING = "vanlig"
        module.REVIEW_TITLE_FILTER = None
        module.get_current_user = lambda: "alice"
        self.prs = [
            {"number": 1, "url": "https://example/1", "author": {"login": "alice"}, "headRefName": "feat/a", "title": "Felles oppdatering"},
            {"number": 2, "url": "https://example/2", "author": {"login": "dependabot[bot]"}, "headRefName": "deps/a", "title": "Felles oppdatering"},
            {"number": 3, "url": "https://example/3", "author": {"login": "bob"}, "headRefName": "feat/b", "title": "Annen endring"},
        ]

    def test_defaults_to_human_pull_requests(self) -> None:
        module.REVIEW_AUTHOR_FILTER = "uten_bot"

        self.assertEqual([1, 3], [pr["number"] for pr in module.apply_filter(self.prs)])

    def test_filters_a_specific_bot(self) -> None:
        module.REVIEW_AUTHOR_FILTER = "dependabot[bot]"

        self.assertEqual([2], [pr["number"] for pr in module.apply_filter(self.prs)])

    def test_filters_a_specific_human_author(self) -> None:
        module.REVIEW_AUTHOR_FILTER = "bob"

        self.assertEqual([3], [pr["number"] for pr in module.apply_filter(self.prs)])

    def test_filters_selected_group_entries(self) -> None:
        module.REVIEW_AUTHOR_FILTER = "alle"
        module.REVIEW_SELECTED_KEYS = {module.review_key(self.prs[2])}

        self.assertEqual([3], [pr["number"] for pr in module.apply_filter(self.prs)])

    def test_groups_review_entries_by_branch(self) -> None:
        module.REVIEW_GROUPING = "branch"
        entries = [
            {"name": "repo", "pr": self.prs[2]},
            {"name": "repo", "pr": self.prs[0]},
            {"name": "repo", "pr": self.prs[1]},
        ]

        self.assertEqual([2, 1, 3], [entry["pr"]["number"] for entry in module.review_entries([{"entries": entries}])])

    def test_sorts_review_entries_by_repo_and_author(self) -> None:
        module.REVIEW_GROUPING = "repo_forfatter"
        entries = [
            {"org": "navikt", "name": "b", "pr": self.prs[0]},
            {"org": "navikt", "name": "a", "pr": self.prs[2]},
            {"org": "navikt", "name": "a", "pr": self.prs[1]},
        ]

        self.assertEqual([3, 2, 1], [entry["pr"]["number"] for entry in module.review_entries([{"entries": entries}])])

    def test_selects_sorting_from_separate_menu(self) -> None:
        with patch.object(module, "choose", return_value="tittel") as mocked_choose:
            self.assertEqual("ok", module.pick_review_sorting())

        self.assertEqual("tittel", module.REVIEW_GROUPING)
        self.assertEqual("Sorter tabellen", mocked_choose.call_args.args[0])
        self.assertIn(("tittel", "Etter tittel", "t"), mocked_choose.call_args.args[1])

    def test_selects_title_directly_from_filter_menu(self) -> None:
        repo_groups = [{"raw_prs": self.prs}]
        with patch.object(module, "choose", return_value="title_0") as mocked_choose:
            self.assertEqual("ok", module.pick_review_filter(repo_groups))

        self.assertEqual("Felles oppdatering", module.REVIEW_TITLE_FILTER)
        self.assertEqual("alle", module.REVIEW_AUTHOR_FILTER)
        self.assertEqual([1, 2], [pr["number"] for pr in module.apply_filter(self.prs)])
        self.assertIn(("title_0", "Tittel: Felles oppdatering (2)", "7"), mocked_choose.call_args.args[1])
        self.assertNotIn(("title_1", "Tittel: Annen endring (1)", "8"), mocked_choose.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
