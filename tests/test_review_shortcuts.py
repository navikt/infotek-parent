from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
spec = importlib.util.spec_from_file_location("pr_behandle", SCRIPTS_DIR / "pr-behandle.py")
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class ReviewShortcutTest(unittest.TestCase):
    def test_assigns_numeric_shortcuts_starting_at_one(self) -> None:
        self.assertEqual("1", module.review_pr_shortcut(0))
        self.assertEqual("9", module.review_pr_shortcut(8))
        self.assertEqual("10", module.review_pr_shortcut(9))
        self.assertEqual("25", module.review_pr_shortcut(24))

if __name__ == "__main__":
    unittest.main()
